-- AISL migration 002: settlement columns, double-entry ledger, and indexes.
--
-- Every object here exists because a blueprint acceptance criterion requires
-- it but the blueprint's table listing does not carry it:
--   * TASK 5 says "Query conversions by Stripe charge ID" -> conversions needs
--     the Stripe payment_intent / charge identifiers.
--   * TASK 5 says a refund inserts a *negative offset entry* while
--     external_order_id is UNIQUE -> a reversal is its own row linked to its
--     parent, with a derived external_order_id.
--   * "Double-Entry Bookkeeping" requires balanced debit/credit legs, which a
--     single denormalised conversions row cannot express.

ALTER TABLE conversions
    ADD COLUMN IF NOT EXISTS currency CHAR(3) NOT NULL DEFAULT 'USD',
    ADD COLUMN IF NOT EXISTS merchant_net_cents BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS entry_type VARCHAR(16) NOT NULL DEFAULT 'SALE',
    ADD COLUMN IF NOT EXISTS parent_conversion_id UUID REFERENCES conversions(id),
    ADD COLUMN IF NOT EXISTS stripe_payment_intent_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS stripe_charge_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversions_entry_type_check') THEN
        ALTER TABLE conversions
            ADD CONSTRAINT conversions_entry_type_check CHECK (entry_type IN ('SALE', 'REVERSAL'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversions_status_check') THEN
        ALTER TABLE conversions
            ADD CONSTRAINT conversions_status_check
            CHECK (status IN ('PENDING_SETTLEMENT', 'SETTLED', 'REFUNDED', 'REVERSAL'));
    END IF;
    -- gross = merchant_net + commission_total, and commission = platform + agent.
    -- Enforced in the database so no future code path can write an unbalanced row.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversions_split_balance_check') THEN
        ALTER TABLE conversions
            ADD CONSTRAINT conversions_split_balance_check CHECK (
                commission_total_cents = aisl_fee_cents + agent_payout_cents
                AND gross_amount_cents = merchant_net_cents + commission_total_cents
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_conversions_stripe_payment_intent
    ON conversions (stripe_payment_intent_id)
    WHERE stripe_payment_intent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversions_stripe_charge
    ON conversions (stripe_charge_id)
    WHERE stripe_charge_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversions_click_id ON conversions (click_id);
CREATE INDEX IF NOT EXISTS idx_conversions_merchant_created ON conversions (merchant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversions_parent ON conversions (parent_conversion_id)
    WHERE parent_conversion_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_intents_agent_created ON agent_intents (agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_intents_merchant ON agent_intents (merchant_id);

-- Product binding for a minted click token. Checkout re-reads this to confirm
-- the agent is buying the variant the token was issued against.
CREATE TABLE IF NOT EXISTS agent_intent_bindings (
    click_id UUID PRIMARY KEY REFERENCES agent_intents(click_id) ON DELETE CASCADE,
    product_id VARCHAR(255) NOT NULL,
    variant_id VARCHAR(255) NOT NULL,
    quoted_price_cents BIGINT NOT NULL,
    currency CHAR(3) NOT NULL,
    query TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_intent_bindings_variant ON agent_intent_bindings (variant_id);

-- True double-entry legs. Each `entry_group_id` is one balanced transaction:
-- SUM(amount) WHERE direction='DEBIT' == SUM(amount) WHERE direction='CREDIT'.
CREATE TABLE IF NOT EXISTS ledger_entries (
    id BIGSERIAL PRIMARY KEY,
    entry_group_id UUID NOT NULL,
    conversion_id UUID NOT NULL REFERENCES conversions(id),
    merchant_id UUID NOT NULL REFERENCES merchants(id),
    account VARCHAR(64) NOT NULL,
    direction VARCHAR(6) NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    currency CHAR(3) NOT NULL,
    memo VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_group ON ledger_entries (entry_group_id);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_conversion ON ledger_entries (conversion_id);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_account ON ledger_entries (merchant_id, account, currency);

-- Durable webhook audit trail. Redis SETNX is the hot-path dedupe; this table
-- is the record of what was actually applied, and survives a Redis flush.
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id VARCHAR(255) PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    outcome VARCHAR(64) NOT NULL,
    conversion_id UUID REFERENCES conversions(id),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_type_received ON webhook_events (event_type, received_at DESC);

-- Checkout idempotency: a replayed checkout returns the original response
-- instead of charging the shared payment token twice.
CREATE TABLE IF NOT EXISTS checkout_idempotency (
    idempotency_key VARCHAR(255) PRIMARY KEY,
    request_sha256 CHAR(64) NOT NULL,
    conversion_id UUID REFERENCES conversions(id),
    response_body JSONB,
    state VARCHAR(16) NOT NULL DEFAULT 'IN_FLIGHT' CHECK (state IN ('IN_FLIGHT', 'COMPLETED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
