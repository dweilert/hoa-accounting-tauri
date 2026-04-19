-- Extend the existing audit_log table with a changed_by email column.
-- Triggers (installed at startup) will populate this from the per-connection
-- _audit_user temp table so every write is attributed to the logged-in user.

ALTER TABLE audit_log ADD COLUMN changed_by TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_log_changed_by
    ON audit_log (changed_by);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_time
    ON audit_log (event_time DESC);
