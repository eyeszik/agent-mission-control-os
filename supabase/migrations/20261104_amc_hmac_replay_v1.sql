-- HMAC ingress replay protection (OWASP ASI07), shared across workers and processes.
-- One row per accepted nonce, kept until its replay window closes. Mirrors SQLite migration v21.
-- Additive only. Grants nothing to anon or authenticated Data API roles; the API service is the only
-- writer.
--
-- Rollback (no other table references this):
--   DROP TABLE IF EXISTS amc.hmac_replay_nonces;

CREATE TABLE IF NOT EXISTS amc.hmac_replay_nonces (
    nonce text PRIMARY KEY CHECK (char_length(nonce) BETWEEN 16 AND 128),
    expires_at bigint NOT NULL,
    recorded_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amc_hmac_replay_nonces_expiry ON amc.hmac_replay_nonces(expires_at);

REVOKE ALL ON amc.hmac_replay_nonces FROM anon, authenticated;
