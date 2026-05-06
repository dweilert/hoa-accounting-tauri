-- Migration 0066: Remove audit_user() UDF call from payment_applications triggers.
--
-- Migration 0055 recreated these triggers using audit_user(), a SQLite UDF
-- that was later removed (commit 80b199f) in favour of hardcoding 'system'.
-- audit_triggers.py already overwrites them at every startup, but on a fresh
-- database the migrator must run 0055 before audit_triggers.py is called,
-- which fails with "no such function: audit_user".
--
-- This migration drops and recreates the two triggers with 'system' hardcoded
-- so that a fresh install can complete all migrations without the UDF.

BEGIN TRANSACTION;

DROP TRIGGER IF EXISTS audit_payment_applications_insert;
DROP TRIGGER IF EXISTS audit_payment_applications_delete;

CREATE TRIGGER audit_payment_applications_insert
AFTER INSERT ON payment_applications
BEGIN
    INSERT INTO audit_log (entity_type, entity_id, action, changed_by, after_json)
    VALUES (
        'payment_applications',
        NEW.id,
        'INSERT',
        'system',
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
        'system',
        json_object(
            'id', OLD.id,
            'payment_id', OLD.payment_id,
            'assessment_id', OLD.assessment_id,
            'applied_amount', OLD.applied_amount
        )
    );
END;

COMMIT;
