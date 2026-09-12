-- AISL migration 001: blueprint-locked core schema.
--
-- The four tables below are reproduced from the AISL production blueprint,
-- TASK 2 ("Database Schema & Idempotent Ledger Deployment"), without semantic
-- change. Settlement columns required by TASK 4/5 that the blueprint does not
-- enumerate are added in 002_settlement_extensions.sql so this file stays
-- auditable against the specification.

-- 1. Merchants Table
CREATE TABLE IF NOT EXISTS merchants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    platform VARCHAR(50) NOT NULL, -- 'shopify', 'woocommerce', 'stripe_custom'
    api_credentials_encrypted JSONB NOT NULL,
    commission_rate_bps INT NOT NULL DEFAULT 500, -- 500 bps = 5.0%
    aisl_cut_bps INT NOT NULL DEFAULT 80, -- 80 bps = 0.8%
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Click & Intent Telemetry
CREATE TABLE IF NOT EXISTS agent_intents (
    click_id UUID PRIMARY KEY, -- UUIDv7
    agent_id VARCHAR(128) NOT NULL,
    sub_id_1 VARCHAR(64),
    sub_id_2 VARCHAR(64),
    merchant_id UUID REFERENCES merchants(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Attributed Conversions & Double-Entry Ledger
CREATE TABLE IF NOT EXISTS conversions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    click_id UUID REFERENCES agent_intents(click_id),
    merchant_id UUID REFERENCES merchants(id),
    external_order_id VARCHAR(255) NOT NULL UNIQUE,
    gross_amount_cents BIGINT NOT NULL,
    commission_total_cents BIGINT NOT NULL,
    aisl_fee_cents BIGINT NOT NULL,
    agent_payout_cents BIGINT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING_SETTLEMENT', -- 'PENDING_SETTLEMENT', 'SETTLED', 'REFUNDED'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Idempotency Lock Table for S2S Postbacks
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key VARCHAR(255) PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
