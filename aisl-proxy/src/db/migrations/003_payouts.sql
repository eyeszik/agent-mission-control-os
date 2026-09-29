-- AISL migration 003: agent payouts.
--
-- Migrations 001/002 make the gateway an accurate book of record: every sale
-- credits `agent_payable` and every reversal debits it back. Nothing ever
-- settled that liability. This migration adds the tables that let money
-- actually leave, without ever letting it leave twice.
--
-- The invariant that matters here: a conversion contributes to at most one
-- payout. `idx_payout_items_conversion` is a hard UNIQUE index, so a double
-- claim is a constraint violation rather than a duplicated transfer.

CREATE TABLE IF NOT EXISTS agent_accounts (
    agent_id VARCHAR(128) PRIMARY KEY,
    display_name VARCHAR(255),
    -- Stripe Connect account the transfer is destined for. NULL means the
    -- agent is onboarded for attribution but cannot yet be paid.
    stripe_account_id VARCHAR(255),
    payout_currency CHAR(3) NOT NULL DEFAULT 'USD',
    -- Below this, a run accrues rather than transferring: a 3-cent payout
    -- costs more in rail fees and reconciliation than it moves.
    minimum_payout_cents BIGINT NOT NULL DEFAULT 0 CHECK (minimum_payout_cents >= 0),
    payouts_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(128) NOT NULL REFERENCES agent_accounts(agent_id),
    currency CHAR(3) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'IN_FLIGHT'
        CHECK (status IN ('IN_FLIGHT', 'PAID', 'FAILED')),
    -- Passed verbatim to Stripe as the request idempotency key, so a retried
    -- run after an ambiguous network failure cannot create a second transfer.
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    stripe_transfer_id VARCHAR(255),
    destination_account VARCHAR(255),
    failure_code VARCHAR(128),
    failure_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payouts_agent_status ON payouts (agent_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payouts_status_created ON payouts (status, created_at)
    WHERE status = 'IN_FLIGHT';

-- Which conversions a payout discharged. `amount_cents` is signed: a sale
-- contributes its positive agent_payout_cents, a reversal its negative one, so
-- SUM(amount_cents) over a payout's items always equals payouts.amount_cents.
CREATE TABLE IF NOT EXISTS payout_items (
    payout_id UUID NOT NULL REFERENCES payouts(id) ON DELETE CASCADE,
    conversion_id UUID NOT NULL REFERENCES conversions(id),
    amount_cents BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (payout_id, conversion_id)
);

-- The double-claim guard. A failed payout releases its items (they are deleted)
-- so the money becomes claimable again; the payouts row survives for audit.
CREATE UNIQUE INDEX IF NOT EXISTS idx_payout_items_conversion ON payout_items (conversion_id);
