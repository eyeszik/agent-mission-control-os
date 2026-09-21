-- AISL migration 004: merchant lifecycle.
--
-- Onboarding was one-shot: a merchant, once created, could never have its
-- credentials rolled or be taken out of service. A leaked Storefront token had
-- no remedy short of a manual UPDATE, and a merchant whose store went away kept
-- being fanned out to on every search.
--
-- `enabled` is deliberately a flag rather than a delete: conversions and ledger
-- entries reference merchants, and the books must stay readable for a merchant
-- that is no longer trading.

ALTER TABLE merchants
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS credentials_rotated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_merchants_enabled ON merchants (enabled) WHERE enabled;
