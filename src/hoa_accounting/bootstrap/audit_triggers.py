"""Install audit triggers on a SQLite connection.

Writes to the existing audit_log table using its column names:
  entity_type, entity_id, action, before_json, after_json, changed_by.

Triggers must be created via individual execute() calls — executescript()
cannot handle the BEGIN…END syntax inside trigger bodies reliably.
Triggers are dropped and recreated at every startup so the audit_user()
UDF expression stays current. Called at app startup after migrations run.
"""

from __future__ import annotations

import sqlite3

_USER_EXPR = "audit_user()"


def _trig(
    conn: sqlite3.Connection,
    name: str,
    timing: str,
    event: str,
    table: str,
    body: str,
) -> None:
    conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    conn.execute(
        f"CREATE TRIGGER {name} " f"{timing} {event} ON {table} BEGIN {body} END"
    )


def _ins(table: str, record_expr: str, new_json: str) -> str:
    return (
        f"INSERT INTO audit_log (entity_type, entity_id, action, changed_by, after_json)"
        f" VALUES ('{table}', {record_expr}, 'INSERT', {_USER_EXPR}, {new_json});"
    )


def _upd(table: str, record_expr: str, old_json: str, new_json: str) -> str:
    return (
        f"INSERT INTO audit_log (entity_type, entity_id, action, changed_by, before_json, after_json)"
        f" VALUES ('{table}', {record_expr}, 'UPDATE', {_USER_EXPR}, {old_json}, {new_json});"
    )


def _del(table: str, record_expr: str, old_json: str) -> str:
    return (
        f"INSERT INTO audit_log (entity_type, entity_id, action, changed_by, before_json)"
        f" VALUES ('{table}', {record_expr}, 'DELETE', {_USER_EXPR}, {old_json});"
    )


def install_audit_triggers(conn: sqlite3.Connection) -> None:
    """Create all audit triggers (idempotent — safe to call on every startup)."""

    # ── assessments ────────────────────────────────────────────────────────
    _j_assess_new = (
        "json_object('id',NEW.id,'lot_id',NEW.lot_id,'owner_id',NEW.owner_id,"
        "'amount',NEW.amount,'charge_type',NEW.charge_type,'status',NEW.status,"
        "'assessment_date',NEW.assessment_date,'due_date',NEW.due_date,"
        "'description',NEW.description)"
    )
    _j_assess_old = _j_assess_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_assessments_insert",
        "AFTER",
        "INSERT",
        "assessments",
        _ins("assessments", "NEW.id", _j_assess_new),
    )
    _trig(
        conn,
        "audit_assessments_update",
        "AFTER",
        "UPDATE",
        "assessments",
        _upd("assessments", "NEW.id", _j_assess_old, _j_assess_new),
    )
    _trig(
        conn,
        "audit_assessments_delete",
        "BEFORE",
        "DELETE",
        "assessments",
        _del("assessments", "OLD.id", _j_assess_old),
    )

    # ── payments ───────────────────────────────────────────────────────────
    _j_pay_new = (
        "json_object('id',NEW.id,'owner_id',NEW.owner_id,'amount',NEW.amount,"
        "'payment_date',NEW.payment_date,'payment_method',NEW.payment_method,"
        "'receipt_number',NEW.receipt_number,'reference_number',NEW.reference_number,"
        "'bank_account_id',NEW.bank_account_id,'notes',NEW.notes)"
    )
    _j_pay_old = _j_pay_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_payments_insert",
        "AFTER",
        "INSERT",
        "payments",
        _ins("payments", "NEW.id", _j_pay_new),
    )
    _trig(
        conn,
        "audit_payments_update",
        "AFTER",
        "UPDATE",
        "payments",
        _upd("payments", "NEW.id", _j_pay_old, _j_pay_new),
    )
    _trig(
        conn,
        "audit_payments_delete",
        "BEFORE",
        "DELETE",
        "payments",
        _del("payments", "OLD.id", _j_pay_old),
    )

    # ── payment_applications ───────────────────────────────────────────────
    _j_pa_new = (
        "json_object('id',NEW.id,'payment_id',NEW.payment_id,"
        "'assessment_id',NEW.assessment_id,'applied_amount',NEW.applied_amount)"
    )
    _j_pa_old = _j_pa_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_payment_applications_insert",
        "AFTER",
        "INSERT",
        "payment_applications",
        _ins("payment_applications", "NEW.id", _j_pa_new),
    )
    _trig(
        conn,
        "audit_payment_applications_delete",
        "BEFORE",
        "DELETE",
        "payment_applications",
        _del("payment_applications", "OLD.id", _j_pa_old),
    )

    # ── owner_adjustments ──────────────────────────────────────────────────
    _j_oa_new = (
        "json_object('id',NEW.id,'owner_id',NEW.owner_id,'lot_id',NEW.lot_id,"
        "'adjustment_type',NEW.adjustment_type,'amount',NEW.amount,"
        "'adjustment_date',NEW.adjustment_date,'description',NEW.description)"
    )
    _j_oa_old = _j_oa_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_owner_adjustments_insert",
        "AFTER",
        "INSERT",
        "owner_adjustments",
        _ins("owner_adjustments", "NEW.id", _j_oa_new),
    )
    _trig(
        conn,
        "audit_owner_adjustments_update",
        "AFTER",
        "UPDATE",
        "owner_adjustments",
        _upd("owner_adjustments", "NEW.id", _j_oa_old, _j_oa_new),
    )
    _trig(
        conn,
        "audit_owner_adjustments_delete",
        "BEFORE",
        "DELETE",
        "owner_adjustments",
        _del("owner_adjustments", "OLD.id", _j_oa_old),
    )

    # ── lots ───────────────────────────────────────────────────────────────
    _j_lot_new = (
        "json_object('id',NEW.id,'lot_number',NEW.lot_number,"
        "'street_address_1',NEW.street_address_1,'city',NEW.city,"
        "'state',NEW.state,'postal_code',NEW.postal_code,'active_flag',NEW.active_flag)"
    )
    _j_lot_old = _j_lot_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_lots_insert",
        "AFTER",
        "INSERT",
        "lots",
        _ins("lots", "NEW.id", _j_lot_new),
    )
    _trig(
        conn,
        "audit_lots_update",
        "AFTER",
        "UPDATE",
        "lots",
        _upd("lots", "NEW.id", _j_lot_old, _j_lot_new),
    )
    _trig(
        conn,
        "audit_lots_delete",
        "BEFORE",
        "DELETE",
        "lots",
        _del("lots", "OLD.id", _j_lot_old),
    )

    # ── owners ─────────────────────────────────────────────────────────────
    _j_own_new = (
        "json_object('id',NEW.id,'display_name',NEW.display_name,"
        "'first_name',NEW.first_name,'last_name',NEW.last_name,"
        "'email',NEW.email,'phone',NEW.phone,'active_flag',NEW.active_flag)"
    )
    _j_own_old = _j_own_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_owners_insert",
        "AFTER",
        "INSERT",
        "owners",
        _ins("owners", "NEW.id", _j_own_new),
    )
    _trig(
        conn,
        "audit_owners_update",
        "AFTER",
        "UPDATE",
        "owners",
        _upd("owners", "NEW.id", _j_own_old, _j_own_new),
    )
    _trig(
        conn,
        "audit_owners_delete",
        "BEFORE",
        "DELETE",
        "owners",
        _del("owners", "OLD.id", _j_own_old),
    )

    # ── lot_ownership ──────────────────────────────────────────────────────
    _j_lo_new = (
        "json_object('id',NEW.id,'lot_id',NEW.lot_id,'owner_id',NEW.owner_id,"
        "'start_date',NEW.start_date,'end_date',NEW.end_date,"
        "'is_primary_contact',NEW.is_primary_contact)"
    )
    _j_lo_old = _j_lo_new.replace("NEW.", "OLD.")

    _trig(
        conn,
        "audit_lot_ownership_insert",
        "AFTER",
        "INSERT",
        "lot_ownership",
        _ins("lot_ownership", "NEW.id", _j_lo_new),
    )
    _trig(
        conn,
        "audit_lot_ownership_update",
        "AFTER",
        "UPDATE",
        "lot_ownership",
        _upd("lot_ownership", "NEW.id", _j_lo_old, _j_lo_new),
    )
    _trig(
        conn,
        "audit_lot_ownership_delete",
        "BEFORE",
        "DELETE",
        "lot_ownership",
        _del("lot_ownership", "OLD.id", _j_lo_old),
    )

    # journal_entries triggers removed — table retired in migration 0061.

    conn.commit()
