"""COA Interview Wizard — page handlers and account-creation service."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from hoa_accounting.web.template_engine import render_template


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AccountPreview:
    account_number: str
    account_name: str
    account_type: str
    fund_code: str
    group_code: str
    is_bank_account: bool
    description: str
    already_exists: bool = False


@dataclass
class WizardResult:
    to_create: list[AccountPreview] = field(default_factory=list)
    already_exist: list[AccountPreview] = field(default_factory=list)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_groups(conn: sqlite3.Connection, step: int) -> list[dict]:
    rows = conn.execute(
        "SELECT group_id, label, sort_order FROM wizard_groups "
        "WHERE step_number=? AND is_active=1 ORDER BY sort_order, label",
        (step,),
    ).fetchall()
    return [dict(r) for r in rows]


def _load_options(conn: sqlite3.Connection, step: int, *, group_id: str | None = None,
                  include_always: bool = False) -> list[dict]:
    sql = ("SELECT id, option_id, group_id, label, description, sort_order, is_system, is_always "
           "FROM wizard_options WHERE step_number=? AND is_active=1")
    params: list = [step]
    if not include_always:
        sql += " AND is_always=0"
    if group_id is not None:
        sql += " AND group_id=?"
        params.append(group_id)
    sql += " ORDER BY sort_order, label"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _load_accounts(conn: sqlite3.Connection, option_db_id: int, *,
                   reserve_only: bool = False) -> list[dict]:
    sql = ("SELECT account_number, account_name, account_type, fund_code, group_code, "
           "is_bank_account, description, is_reserve_account "
           "FROM wizard_option_accounts WHERE wizard_option_id=?")
    if reserve_only:
        sql += " AND is_reserve_account=1"
    else:
        sql += " AND is_reserve_account=0"
    rows = conn.execute(sql, (option_db_id,)).fetchall()
    return [dict(r) for r in rows]


def _option_to_acct_list(conn: sqlite3.Connection, option: dict, *,
                         include_reserve: bool = False) -> list[dict]:
    """Return operating accounts for option; optionally append reserve accounts too."""
    accts = _load_accounts(conn, option["id"], reserve_only=False)
    if include_reserve:
        accts += _load_accounts(conn, option["id"], reserve_only=True)
    return accts


# ── WizardService ─────────────────────────────────────────────────────────────

class WizardService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Build template context for each step ──────────────────────────────

    def step1_context(self) -> dict:
        """Always accounts + optional fund options for Step 1."""
        always_opt = self._conn.execute(
            "SELECT id FROM wizard_options WHERE step_number=1 AND is_always=1 LIMIT 1"
        ).fetchone()
        always_accounts = _load_accounts(self._conn, always_opt["id"], reserve_only=False) if always_opt else []
        options = _load_options(self._conn, 1)
        return {"step1_always": always_accounts, "step1_options": options}

    def step2_context(self) -> dict:
        return {"step2_options": _load_options(self._conn, 2)}

    def step3_context(self) -> dict:
        return {"step3_options": _load_options(self._conn, 3)}

    def step4_context(self) -> dict:
        groups = _load_groups(self._conn, 4)
        for g in groups:
            g["options"] = _load_options(self._conn, 4, group_id=g["group_id"])
        return {"step4_groups": [g for g in groups if g["options"]]}

    def step5_context(self) -> dict:
        """Manual reserve options + reserve_assets from reserve study."""
        manual = _load_options(self._conn, 5)

        # Pull distinct asset_groups from reserve study that aren't already covered
        manual_labels = {o["label"].lower() for o in manual}
        rs_rows = self._conn.execute(
            "SELECT DISTINCT asset_group FROM reserve_assets WHERE active_flag=1 ORDER BY asset_group"
        ).fetchall()
        reserve_study_items = []
        for row in rs_rows:
            ag = row["asset_group"]
            if ag.lower() not in manual_labels:
                reserve_study_items.append({
                    "option_id": f"_rs_{ag.lower().replace(' ', '_')}",
                    "label": ag,
                    "description": f"From Reserve Study — {ag}",
                    "from_reserve_study": True,
                })

        return {
            "step5_options": manual,
            "step5_reserve_study": reserve_study_items,
        }

    # ── Resolve form → account list ───────────────────────────────────────

    def resolve_accounts(self, form) -> list[dict]:
        seen: set[str] = set()
        accounts: list[dict] = []

        def add(acct: dict) -> None:
            n = acct["account_number"]
            if n not in seen:
                seen.add(n)
                accounts.append(acct)

        conn = self._conn

        # Step 1 — always-on
        always_opt = conn.execute(
            "SELECT id FROM wizard_options WHERE step_number=1 AND is_always=1 LIMIT 1"
        ).fetchone()
        if always_opt:
            for a in _load_accounts(conn, always_opt["id"]):
                add(a)

        # Step 1 — selected funds
        selected1 = set(form.getlist("step1"))
        has_reserve = "reserve" in selected1
        for opt in _load_options(conn, 1):
            if opt["option_id"] in selected1:
                for a in _load_accounts(conn, opt["id"]):
                    add(a)

        # Step 2 — income
        selected2 = set(form.getlist("step2"))
        for opt in _load_options(conn, 2):
            if opt["option_id"] in selected2:
                for a in _load_accounts(conn, opt["id"]):
                    add(a)

        # Step 3 — amenities (operating + reserve if reserve fund selected)
        selected3 = set(form.getlist("step3"))
        for opt in _load_options(conn, 3):
            if opt["option_id"] in selected3:
                for a in _load_accounts(conn, opt["id"]):
                    add(a)
                if has_reserve:
                    for a in _load_accounts(conn, opt["id"], reserve_only=True):
                        add(a)

        # Step 4 — operating expenses
        selected4 = set(form.getlist("step4"))
        for opt in _load_options(conn, 4):
            if opt["option_id"] in selected4:
                for a in _load_accounts(conn, opt["id"]):
                    add(a)

        # Step 5 — reserve capital (only if reserve fund selected)
        if has_reserve:
            selected5 = set(form.getlist("step5"))
            for opt in _load_options(conn, 5):
                if opt["option_id"] in selected5:
                    for a in _load_accounts(conn, opt["id"]):
                        add(a)
            # Reserve-study-linked items generate a generic reserve account
            # (auto-numbered from 6601 upward; skips existing)
            rs_selected = {v for v in selected5 if v.startswith("_rs_")}
            if rs_selected:
                existing_nums = {
                    row[0] for row in conn.execute(
                        "SELECT account_number FROM accounts WHERE account_number LIKE '66%'"
                    ).fetchall()
                } | {a["account_number"] for a in accounts if a["account_number"].startswith("66")}
                counter = 6601
                for val in sorted(rs_selected):
                    label = val[4:].replace("_", " ").title()
                    while str(counter) in existing_nums:
                        counter += 1
                    add({
                        "account_number": str(counter),
                        "account_name": f"Reserve — {label}",
                        "account_type": "EXPENSE",
                        "fund_code": "RESERVE",
                        "group_code": "",
                        "is_bank_account": False,
                        "description": f"Reserve fund for {label}",
                    })
                    existing_nums.add(str(counter))
                    counter += 1

        return accounts

    # ── Preview ───────────────────────────────────────────────────────────

    def build_preview(self, form) -> WizardResult:
        accounts = self.resolve_accounts(form)
        existing = {
            row["account_number"]
            for row in self._conn.execute(
                "SELECT account_number FROM accounts WHERE is_active=1"
            ).fetchall()
        }
        result = WizardResult()
        for a in accounts:
            preview = AccountPreview(
                account_number=a["account_number"],
                account_name=a["account_name"],
                account_type=a["account_type"],
                fund_code=a["fund_code"],
                group_code=a.get("group_code", ""),
                is_bank_account=bool(a.get("is_bank_account")),
                description=a.get("description", ""),
                already_exists=a["account_number"] in existing,
            )
            if preview.already_exists:
                result.already_exist.append(preview)
            else:
                result.to_create.append(preview)
        return result

    # ── Create ────────────────────────────────────────────────────────────

    def create_accounts(self, form) -> int:
        accounts = self.resolve_accounts(form)
        existing = {
            row["account_number"]
            for row in self._conn.execute("SELECT account_number FROM accounts").fetchall()
        }
        type_map = {
            row["code"]: row["id"]
            for row in self._conn.execute("SELECT id, code FROM account_types").fetchall()
        }
        created = 0
        for a in accounts:
            if a["account_number"] in existing:
                continue
            type_id = type_map.get(a["account_type"])
            if not type_id:
                continue
            self._conn.execute(
                """INSERT INTO accounts
                   (account_number, account_name, account_type_id, fund_code,
                    group_code, is_bank_account, description, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    a["account_number"],
                    a["account_name"],
                    type_id,
                    a["fund_code"],
                    a.get("group_code", ""),
                    1 if a.get("is_bank_account") else 0,
                    a.get("description", ""),
                ),
            )
            created += 1
        self._conn.commit()
        return created


# ── Wizard admin service ──────────────────────────────────────────────────────

class WizardAdminService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def all_groups(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, step_number, group_id, label, sort_order, is_system, is_active "
            "FROM wizard_groups ORDER BY step_number, sort_order, label"
        ).fetchall()
        return [dict(r) for r in rows]

    def options_for_step(self, step: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT o.id, o.step_number, o.group_id, o.option_id, o.label, o.description, "
            "o.sort_order, o.is_system, o.is_active, o.is_always, "
            "g.label AS group_label "
            "FROM wizard_options o "
            "LEFT JOIN wizard_groups g ON g.step_number=o.step_number AND g.group_id=o.group_id "
            "WHERE o.step_number=? ORDER BY o.sort_order, o.label",
            (step,),
        ).fetchall()
        options = [dict(r) for r in rows]
        for opt in options:
            opt["accounts"] = self._accounts_for_option(opt["id"])
        return options

    def _accounts_for_option(self, option_db_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, account_number, account_name, account_type, fund_code, "
            "group_code, is_bank_account, description, is_reserve_account "
            "FROM wizard_option_accounts WHERE wizard_option_id=? ORDER BY account_number",
            (option_db_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_option(self, option_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, step_number, group_id, option_id, label, description, "
            "sort_order, is_system, is_active, is_always "
            "FROM wizard_options WHERE id=?", (option_id,)
        ).fetchone()
        if not row:
            return None
        opt = dict(row)
        opt["accounts"] = self._accounts_for_option(opt["id"])
        return opt

    def toggle_option(self, option_db_id: int) -> None:
        self._conn.execute(
            "UPDATE wizard_options SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
            (option_db_id,),
        )
        self._conn.commit()

    def add_option(self, step: int, group_id: str, label: str, description: str,
                   accounts: list[dict]) -> int:
        """Insert a new custom option and its accounts; returns new option id."""
        # Generate a slug option_id
        slug = label.lower().replace(" ", "_").replace("/", "_")[:40] + "_custom"
        # Ensure unique within step
        existing = {
            row[0] for row in self._conn.execute(
                "SELECT option_id FROM wizard_options WHERE step_number=?", (step,)
            ).fetchall()
        }
        base = slug
        n = 2
        while slug in existing:
            slug = f"{base}_{n}"
            n += 1

        max_sort = (self._conn.execute(
            "SELECT MAX(sort_order) FROM wizard_options WHERE step_number=?", (step,)
        ).fetchone()[0] or 100) + 10

        self._conn.execute(
            "INSERT INTO wizard_options (step_number, group_id, option_id, label, description, "
            "sort_order, is_system, is_active, is_always) VALUES (?,?,?,?,?,?,0,1,0)",
            (step, group_id, slug, label, description, max_sort),
        )
        new_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for a in accounts:
            self._conn.execute(
                "INSERT INTO wizard_option_accounts "
                "(wizard_option_id, account_number, account_name, account_type, fund_code, "
                "group_code, is_bank_account, description, is_reserve_account) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    a["account_number"], a["account_name"], a["account_type"],
                    a.get("fund_code", "OPERATING"), a.get("group_code", ""),
                    1 if a.get("is_bank_account") else 0,
                    a.get("description", ""), 1 if a.get("is_reserve_account") else 0,
                ),
            )
        self._conn.commit()
        return new_id

    def delete_option(self, option_db_id: int) -> None:
        """Delete a custom (non-system) option and its accounts."""
        self._conn.execute(
            "DELETE FROM wizard_option_accounts WHERE wizard_option_id=?", (option_db_id,)
        )
        self._conn.execute(
            "DELETE FROM wizard_options WHERE id=? AND is_system=0", (option_db_id,)
        )
        self._conn.commit()

    def groups_for_step(self, step: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, group_id, label, sort_order, is_system, is_active "
            "FROM wizard_groups WHERE step_number=? AND is_active=1 ORDER BY sort_order, label",
            (step,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_group(self, step: int, label: str) -> str:
        slug = label.lower().replace(" ", "_")[:40] + "_custom"
        existing = {
            row[0] for row in self._conn.execute(
                "SELECT group_id FROM wizard_groups WHERE step_number=?", (step,)
            ).fetchall()
        }
        base = slug
        n = 2
        while slug in existing:
            slug = f"{base}_{n}"
            n += 1
        max_sort = (self._conn.execute(
            "SELECT MAX(sort_order) FROM wizard_groups WHERE step_number=?", (step,)
        ).fetchone()[0] or 80) + 10
        self._conn.execute(
            "INSERT INTO wizard_groups (step_number, group_id, label, sort_order, is_system) "
            "VALUES (?,?,?,?,0)",
            (step, slug, label, max_sort),
        )
        self._conn.commit()
        return slug


# ── Page handlers ─────────────────────────────────────────────────────────────

STEP_LABELS = {
    1: "Funds", 2: "Income", 3: "Amenities", 4: "Operating Costs", 5: "Reserves"
}

STEPS = [
    {"number": 1, "title": "Funds"},
    {"number": 2, "title": "Income"},
    {"number": 3, "title": "Amenities"},
    {"number": 4, "title": "Operating Costs"},
    {"number": 5, "title": "Reserves"},
]


class WizardPages:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._svc = WizardService(conn)

    def _render(self, template: str, **ctx) -> tuple[int, str]:
        return 200, render_template(template, ctx)

    def render_wizard(self, org: dict, theme: str) -> tuple[int, str]:
        ctx = {
            "org": org, "theme": theme,
            "heading": "Chart of Accounts Setup Wizard",
            "page_key": "accounts",
            "steps": STEPS,
        }
        ctx.update(self._svc.step1_context())
        ctx.update(self._svc.step2_context())
        ctx.update(self._svc.step3_context())
        ctx.update(self._svc.step4_context())
        ctx.update(self._svc.step5_context())
        return self._render("coa_wizard.html", **ctx)

    def render_preview(self, form, org: dict, theme: str) -> tuple[int, str]:
        result = self._svc.build_preview(form)
        form_snapshot = {k: form.getlist(k) for k in ("step1", "step2", "step3", "step4", "step5")}
        return self._render(
            "coa_wizard_preview.html",
            org=org, theme=theme,
            heading="Review Accounts to Create",
            page_key="accounts",
            result=result,
            form_snapshot=form_snapshot,
            steps=STEPS,
        )

    def handle_create(self, form, org: dict, theme: str) -> str:
        count = self._svc.create_accounts(form)
        return f"/accounts?msg={count}+accounts+created+successfully."


class WizardAdminPages:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._svc = WizardAdminService(conn)

    def _render(self, template: str, **ctx) -> tuple[int, str]:
        return 200, render_template(template, ctx)

    def render_catalog(self, org: dict, theme: str, active_step: int = 1,
                       flash: str = "") -> tuple[int, str]:
        steps_data = []
        for n in range(1, 6):
            steps_data.append({
                "number": n,
                "label": STEP_LABELS[n],
                "options": self._svc.options_for_step(n),
                "groups": self._svc.groups_for_step(n),
            })
        return self._render(
            "admin_wizard_catalog.html",
            org=org, theme=theme,
            heading="Wizard Question Catalog",
            page_key="admin",
            steps_data=steps_data,
            active_step=active_step,
            flash=flash,
            step_labels=STEP_LABELS,
        )

    def handle_toggle(self, option_db_id: int, org: dict, theme: str,
                      active_step: int) -> str:
        self._svc.toggle_option(option_db_id)
        return f"/admin/wizard-catalog?step={active_step}"

    def handle_add_option(self, form, org: dict, theme: str) -> str:
        step = int(form.get("step", 1))
        group_id = form.get("group_id", "")
        label = (form.get("label") or "").strip()
        description = (form.get("description") or "").strip()
        if not label:
            return f"/admin/wizard-catalog?step={step}"

        # Parse account rows from form (account_number_0, account_name_0, …)
        accounts = []
        i = 0
        while form.get(f"account_number_{i}"):
            accounts.append({
                "account_number": form.get(f"account_number_{i}", "").strip(),
                "account_name":   form.get(f"account_name_{i}", "").strip(),
                "account_type":   form.get(f"account_type_{i}", "EXPENSE"),
                "fund_code":      form.get(f"fund_code_{i}", "OPERATING"),
                "group_code":     form.get(f"group_code_{i}", ""),
                "is_bank_account": form.get(f"is_bank_{i}") == "1",
                "description":    form.get(f"acct_desc_{i}", ""),
                "is_reserve_account": form.get(f"is_reserve_{i}") == "1",
            })
            i += 1

        self._svc.add_option(step, group_id, label, description, accounts)
        return f"/admin/wizard-catalog?step={step}&flash=Option+added"

    def handle_delete_option(self, option_db_id: int, active_step: int) -> str:
        self._svc.delete_option(option_db_id)
        return f"/admin/wizard-catalog?step={active_step}&flash=Option+deleted"

    def handle_add_group(self, form) -> str:
        step = int(form.get("step", 4))
        label = (form.get("label") or "").strip()
        if label:
            self._svc.add_group(step, label)
        return f"/admin/wizard-catalog?step={step}&flash=Group+added"
