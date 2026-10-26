-- ACE v100: allow durable intent recovery to distinguish unknown, rejected and committed outcomes.
-- Mirrors SQLite migration v17. Run once through the existing ordered migration runner.
-- This does not change deployment activation, provider permissions or outbox delivery guarantees.

ALTER TABLE amc.durable_intents
    DROP CONSTRAINT IF EXISTS durable_intents_status_check;
ALTER TABLE amc.durable_intents
    ADD CONSTRAINT durable_intents_status_check
    CHECK (status IN ('INTENT', 'UNCONFIRMED', 'COMMITTED', 'FAILED', 'ABANDONED'));

COMMENT ON COLUMN amc.durable_intents.status IS
    'INTENT before dispatch, UNCONFIRMED after uncertain external outcome, COMMITTED after verified receipt, FAILED after authoritative negative provider response; a timeout is never assumed to be FAILED.';
