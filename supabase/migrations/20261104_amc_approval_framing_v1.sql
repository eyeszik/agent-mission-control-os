-- Persuasive-framing evidence on approvals (OWASP ASI09). Additive: two nullable columns.
-- Rows written before this migration keep NULL, which reads as "not assessed".
--
-- Rollback:
--   ALTER TABLE amc.approvals DROP COLUMN IF EXISTS framing_codes;
--   ALTER TABLE amc.approvals DROP COLUMN IF EXISTS framing_level;

ALTER TABLE amc.approvals ADD COLUMN IF NOT EXISTS framing_level text CHECK (framing_level IN ('NONE', 'REVIEW', 'HIGH'));
ALTER TABLE amc.approvals ADD COLUMN IF NOT EXISTS framing_codes text;
