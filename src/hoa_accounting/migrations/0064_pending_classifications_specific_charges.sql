-- Migration 0064: Specific-charges mode on pending classifications.
--
-- When set, ``apply_to_assessment_ids`` is a JSON-encoded list of
-- assessment ids that the Post step should drain in order — overriding
-- the default "drain by charge_type, oldest-first" behavior.
--
-- This mirrors DepositBatchService's two modes:
--   - charge_type_filter set, no explicit ids → regular mode
--     (e.g. dues check drains DUES + LATE_FEE oldest-first)
--   - apply_to_assessment_ids set → specific mode
--     (treasurer picked exactly which charges this check covers)
--
-- The format is JSON because SQLite has no array type and we want
-- order preservation. NULL or empty string means "use charge_type
-- drain"; anything else is parsed as a JSON list of integers.

BEGIN TRANSACTION;

ALTER TABLE pending_classifications
    ADD COLUMN apply_to_assessment_ids TEXT;

COMMIT;
