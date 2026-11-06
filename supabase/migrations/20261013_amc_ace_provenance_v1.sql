-- ACE v100 authenticated per-project provenance journal.
-- Mirrors SQLite migration v18. This migration is additive and does not
-- activate external execution or grant rights to anonymous API roles.

CREATE TABLE IF NOT EXISTS amc.ace_provenance (
    tenant_id text NOT NULL REFERENCES amc.tenants(tenant_id),
    project_id text NOT NULL REFERENCES amc.projects(project_id),
    sequence bigint NOT NULL CHECK (sequence >= 1),
    key_id text NOT NULL,
    actor text NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    previous_hash text NOT NULL,
    payload_digest text NOT NULL,
    record_hash text NOT NULL,
    signature text NOT NULL,
    observed_at text NOT NULL,
    PRIMARY KEY (tenant_id, project_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_amc_ace_provenance_project
    ON amc.ace_provenance(project_id, sequence);

REVOKE ALL ON amc.ace_provenance FROM anon, authenticated;
COMMENT ON TABLE amc.ace_provenance IS
    'Authenticated HMAC-chained provenance records written through server-side service policy; DB admin modifications remain possible and should be independently audited.';
