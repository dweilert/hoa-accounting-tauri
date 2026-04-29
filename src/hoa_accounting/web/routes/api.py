"""Lightweight JSON APIs (used by JS in form pages)."""

from __future__ import annotations

import sqlite3

from flask import Blueprint, Response, g, redirect, request
from flask.typing import ResponseReturnValue
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext


def make_api_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("api", __name__)
    org_context = ctx.org_context

    def _open_db() -> sqlite3.Connection:
        return ctx.open_db()

    # ── API helpers ───────────────────────────────────────────────────────

    @bp.get("/api/lots/<int:lot_id>/open-charges")
    def api_lot_open_charges(lot_id: int) -> ResponseReturnValue:
        """Return open assessments for a lot's current owner in payment-order.

        Used by the deposit batch form to show the treasurer what charges
        will be covered by a payment before it is posted.
        """
        import json
        from decimal import Decimal
        from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
        from hoa_accounting.repositories.lots_repo import LotsRepository

        db_path = org_context.get("db_path")
        if not db_path:
            return Response(json.dumps({"error": "no db"}), status=500,
                            mimetype="application/json")

        conn = _open_db()
        try:
            owner_id = LotsRepository(conn).get_current_owner_id(lot_id)
            if owner_id is None:
                return Response(json.dumps({"charges": [], "total_outstanding": "0.00"}),
                                mimetype="application/json")

            rows = AssessmentsRepository(conn).list_open_for_owner(owner_id)
            charges = []
            total = Decimal("0.00")
            for r in rows:
                outstanding = Decimal(str(r["amount"])) - Decimal(str(r["already_applied"]))
                if outstanding <= 0:
                    continue
                charges.append({
                    "id": int(r["id"]),
                    "charge_type": r["charge_type"],
                    "description": r["description"] or "",
                    "due_date": r["due_date"] or "",
                    "outstanding": str(outstanding),
                })
                total += outstanding
            return Response(
                json.dumps({"charges": charges, "total_outstanding": str(total)}),
                mimetype="application/json",
            )
        finally:
            conn.close()

    return bp
