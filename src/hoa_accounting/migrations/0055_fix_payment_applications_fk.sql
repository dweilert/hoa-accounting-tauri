-- Migration 0055: Fix payment_applications foreign keys.
--
-- Migration 0049 rebuilt the payments and assessments tables as part of
-- the single-entry cutover but did not rebuild payment_applications. Its
-- FOREIGN KEYs still reference the renamed-old tables _payments_old_0049
-- and _assessments_old_0049, which have since been dropped — making every
-- INSERT into payment_applications fail with an FK error when FK checks
-- are on.

BEGIN TRANSACTION;

-- 1. Snapshot existing rows (there may be legacy rows referencing either
--    the new or the old tables; keep what we have and let FK enforcement
--    flag anything that no longer makes sense).
CREATE TABLE payment_applications_new (
    id              INTEGER PRIMARY KEY,
    payment_id      INTEGER NOT NULL REFERENCES payments(id)    ON DELETE CASCADE,
    assessment_id   INTEGER NOT NULL REFERENCES assessments(id),
    applied_amount  NUMERIC NOT NULL CHECK (applied_amount > 0),
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (payment_id, assessment_id)
);

INSERT INTO payment_applications_new
    (id, payment_id, assessment_id, applied_amount, created_at)
SELECT id, payment_id, assessment_id, applied_amount, created_at
FROM payment_applications
WHERE payment_id IN (SELECT id FROM payments)
  AND assessment_id IN (SELECT id FROM assessments);

-- 2. Drop dependent triggers that reference the old table name.
DROP TRIGGER IF EXISTS audit_payment_applications_insert;
DROP TRIGGER IF EXISTS audit_payment_applications_delete;

-- 3. Swap.
DROP TABLE payment_applications;
ALTER TABLE payment_applications_new RENAME TO payment_applications;

-- 4. Recreate audit triggers against the fresh table.
CREATE TRIGGER audit_payment_applications_insert
AFTER INSERT ON payment_applications
BEGIN
    INSERT INTO audit_log (entity_type, entity_id, action, changed_by, after_json)
    VALUES (
        'payment_applications',
        NEW.id,
        'INSERT',
        audit_user(),
        json_object(
            'id', NEW.id,
            'payment_id', NEW.payment_id,
            'assessment_id', NEW.assessment_id,
            'applied_amount', NEW.applied_amount
        )
    );
END;

CREATE TRIGGER audit_payment_applications_delete
BEFORE DELETE ON payment_applications
BEGIN
    INSERT INTO audit_log (entity_type, entity_id, action, changed_by, before_json)
    VALUES (
        'payment_applications',
        OLD.id,
        'DELETE',
        audit_user(),
        json_object(
            'id', OLD.id,
            'payment_id', OLD.payment_id,
            'assessment_id', OLD.assessment_id,
            'applied_amount', OLD.applied_amount
        )
    );
END;

COMMIT;
