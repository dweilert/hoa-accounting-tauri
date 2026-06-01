import type { DbHandle } from "./dbTypes";

const DDL = `
CREATE TABLE IF NOT EXISTS vendor_bills (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id       INTEGER NOT NULL REFERENCES vendors(id),
  invoice_number  TEXT    NOT NULL,
  invoice_date    TEXT    NOT NULL,
  due_date        TEXT,
  amount          NUMERIC NOT NULL CHECK(amount != 0),
  fund_code       TEXT    NOT NULL DEFAULT 'OPERATING'
                          CHECK(fund_code IN ('OPERATING','RESERVE','SPECIAL')),
  status          TEXT    NOT NULL DEFAULT 'OPEN'
                          CHECK(status IN ('OPEN','PARTIAL','PAID','VOID')),
  category_id     INTEGER REFERENCES categories(id),
  description     TEXT,
  created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(vendor_id, invoice_number)
);

CREATE TABLE IF NOT EXISTS bill_payments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_bill_id  INTEGER NOT NULL REFERENCES vendor_bills(id),
  payment_date    TEXT    NOT NULL,
  amount          NUMERIC NOT NULL CHECK(amount != 0),
  bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
  check_number    TEXT,
  notes           TEXT,
  created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vendors (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_name   TEXT    NOT NULL,
  contact_name  TEXT,
  email         TEXT,
  phone         TEXT,
  address_1     TEXT,
  address_2     TEXT,
  city          TEXT,
  state         TEXT,
  postal_code   TEXT,
  notes         TEXT,
  active_flag   INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bank_accounts (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  account_name          TEXT    NOT NULL,
  institution_name      TEXT    NOT NULL,
  account_last4         TEXT,
  account_type          TEXT    NOT NULL DEFAULT 'CHECKING'
                                CHECK(account_type IN ('CHECKING','SAVINGS','MONEY_MARKET','OTHER')),
  fund_code             TEXT    NOT NULL DEFAULT 'OPERATING'
                                CHECK(fund_code IN ('OPERATING','RESERVE','SPECIAL')),
  active_flag           INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  opening_balance       NUMERIC NOT NULL DEFAULT 0,
  opening_balance_date  TEXT,
  created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lots (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_number         TEXT    NOT NULL UNIQUE,
  street_address_1   TEXT,
  street_address_2   TEXT,
  city               TEXT,
  state              TEXT,
  postal_code        TEXT,
  legal_description  TEXT,
  active_flag        INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS owners (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_type         TEXT    NOT NULL DEFAULT 'PERSON'
                             CHECK(owner_type IN ('PERSON','ENTITY','TRUST')),
  display_name       TEXT    NOT NULL,
  first_name         TEXT,
  last_name          TEXT,
  entity_name        TEXT,
  mailing_address_1  TEXT,
  mailing_address_2  TEXT,
  city               TEXT,
  state              TEXT,
  postal_code        TEXT,
  phone              TEXT,
  home_phone         TEXT,
  email              TEXT,
  notes              TEXT,
  active_flag        INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lot_ownership (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_id             INTEGER NOT NULL REFERENCES lots(id),
  owner_id           INTEGER NOT NULL REFERENCES owners(id),
  start_date         TEXT    NOT NULL,
  end_date           TEXT,
  ownership_percent  NUMERIC NOT NULL DEFAULT 100
                             CHECK(ownership_percent > 0 AND ownership_percent <= 100),
  is_primary_contact INTEGER NOT NULL DEFAULT 1 CHECK(is_primary_contact IN (0,1)),
  created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lot_renters (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_id             INTEGER NOT NULL REFERENCES lots(id),
  display_name       TEXT    NOT NULL,
  first_name         TEXT,
  last_name          TEXT,
  email              TEXT,
  phone              TEXT,
  start_date         TEXT    NOT NULL,
  end_date           TEXT,
  is_primary_contact INTEGER NOT NULL DEFAULT 1 CHECK(is_primary_contact IN (0,1)),
  notes              TEXT,
  created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  code          TEXT    NOT NULL UNIQUE,
  name          TEXT    NOT NULL,
  category_type TEXT    NOT NULL CHECK(category_type IN ('INCOME','EXPENSE','TRANSFER')),
  fund_code     TEXT    NOT NULL DEFAULT 'OPERATING'
                        CHECK(fund_code IN ('OPERATING','RESERVE','SPECIAL')),
  sort_order    INTEGER NOT NULL DEFAULT 0,
  group_name    TEXT,
  description   TEXT,
  active_flag   INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  system_required INTEGER NOT NULL DEFAULT 0 CHECK(system_required IN (0,1)),
  created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS opening_balances (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type  TEXT    NOT NULL CHECK(entity_type IN ('BANK_ACCOUNT','LOT_DUES','LOT_ASSESSMENT')),
  entity_id    INTEGER NOT NULL,
  as_of_date   TEXT    NOT NULL,
  amount       NUMERIC NOT NULL DEFAULT 0,
  notes        TEXT,
  created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS assessments (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_id               INTEGER NOT NULL REFERENCES lots(id),
  owner_id             INTEGER REFERENCES owners(id),
  charge_type          TEXT    NOT NULL DEFAULT 'DUES'
                               CHECK(charge_type IN ('DUES','LATE_FEE','LEGAL_FEE','OTHER')),
  amount               NUMERIC NOT NULL CHECK(amount > 0),
  assessment_date      TEXT    NOT NULL,
  due_date             TEXT,
  description          TEXT,
  status               TEXT    NOT NULL DEFAULT 'OPEN'
                               CHECK(status IN ('OPEN','PARTIAL','PAID','VOID','WRITTEN_OFF')),
  category_id          INTEGER REFERENCES categories(id),
  created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deposit_batches (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  deposit_date    TEXT    NOT NULL,
  bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  check_count     INTEGER NOT NULL DEFAULT 0,
  notes           TEXT,
  status          TEXT    NOT NULL DEFAULT 'OPEN'
                          CHECK(status IN ('OPEN','POSTED')),
  created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_id               INTEGER NOT NULL REFERENCES lots(id),
  owner_id             INTEGER REFERENCES owners(id),
  deposit_batch_id     INTEGER REFERENCES deposit_batches(id),
  payment_date         TEXT    NOT NULL,
  amount               NUMERIC NOT NULL CHECK(amount > 0),
  payment_method       TEXT    NOT NULL DEFAULT 'CHECK'
                               CHECK(payment_method IN ('CHECK','ACH','ONLINE','CASH','OTHER')),
  check_number         TEXT,
  memo                 TEXT,
  created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payment_applications (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id     INTEGER NOT NULL REFERENCES payments(id),
  assessment_id  INTEGER NOT NULL REFERENCES assessments(id),
  amount         NUMERIC NOT NULL CHECK(amount > 0),
  created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(payment_id, assessment_id)
);

CREATE TABLE IF NOT EXISTS income_batches (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  income_date     TEXT    NOT NULL,
  bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
  category_id     INTEGER NOT NULL REFERENCES categories(id),
  amount          NUMERIC NOT NULL CHECK(amount != 0),
  description     TEXT,
  lot_id          INTEGER REFERENCES lots(id),
  owner_id        INTEGER REFERENCES owners(id),
  reference       TEXT,
  created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bank_transactions (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  bank_account_id      INTEGER NOT NULL REFERENCES bank_accounts(id),
  transaction_date     TEXT    NOT NULL,
  amount               NUMERIC NOT NULL,
  description          TEXT,
  memo                 TEXT,
  transaction_type     TEXT,
  fitid                TEXT,
  dedup_key            TEXT,
  validation_status    TEXT    NOT NULL DEFAULT 'UNVALIDATED'
                               CHECK(validation_status IN ('UNVALIDATED','VALIDATED','IGNORED')),
  import_batch_id      INTEGER,
  created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(bank_account_id, dedup_key)
);

CREATE TABLE IF NOT EXISTS bank_transaction_links (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  bank_transaction_id  INTEGER NOT NULL REFERENCES bank_transactions(id),
  source_type          TEXT    NOT NULL
                               CHECK(source_type IN ('PAYMENT','INCOME_BATCH','BILL_PAYMENT','RESERVE_TRANSFER')),
  source_id            INTEGER NOT NULL,
  created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(bank_transaction_id, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS bank_transaction_rules (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_name            TEXT    NOT NULL,
  description_contains TEXT,
  amount_min           NUMERIC,
  amount_max           NUMERIC,
  transaction_type     TEXT,
  action_type          TEXT    NOT NULL,
  category_id          INTEGER REFERENCES categories(id),
  vendor_id            INTEGER REFERENCES vendors(id),
  confidence_mode      TEXT    NOT NULL DEFAULT 'REVIEW_FIRST'
                               CHECK(confidence_mode IN ('REVIEW_FIRST','AUTO_POST')),
  active_flag          INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  match_count          INTEGER NOT NULL DEFAULT 0,
  created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bank_reconciliations (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  bank_account_id          INTEGER NOT NULL REFERENCES bank_accounts(id),
  statement_ending_date    TEXT    NOT NULL,
  statement_ending_balance NUMERIC NOT NULL,
  beginning_balance        NUMERIC NOT NULL DEFAULT 0,
  book_balance             NUMERIC,
  status                   TEXT    NOT NULL DEFAULT 'OPEN'
                                   CHECK(status IN ('OPEN','FINALIZED')),
  notes                    TEXT,
  created_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(bank_account_id, statement_ending_date)
);

CREATE TABLE IF NOT EXISTS reconciliation_clears (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  reconciliation_id    INTEGER NOT NULL REFERENCES bank_reconciliations(id),
  bank_transaction_id  INTEGER NOT NULL REFERENCES bank_transactions(id),
  created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(reconciliation_id, bank_transaction_id)
);

CREATE TABLE IF NOT EXISTS reserve_transfers (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  transfer_date            TEXT    NOT NULL,
  from_bank_account_id     INTEGER NOT NULL REFERENCES bank_accounts(id),
  to_bank_account_id       INTEGER NOT NULL REFERENCES bank_accounts(id),
  amount                   NUMERIC NOT NULL CHECK(amount > 0),
  category_id              INTEGER REFERENCES categories(id),
  description              TEXT,
  created_at               TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budgets (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  fiscal_year  INTEGER NOT NULL,
  fund_code    TEXT    NOT NULL DEFAULT 'OPERATING'
                       CHECK(fund_code IN ('OPERATING','RESERVE','SPECIAL')),
  status       TEXT    NOT NULL DEFAULT 'DRAFT'
                       CHECK(status IN ('DRAFT','APPROVED','ARCHIVED')),
  notes        TEXT,
  created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(fiscal_year, fund_code)
);

CREATE TABLE IF NOT EXISTS budget_lines (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  budget_id      INTEGER NOT NULL REFERENCES budgets(id),
  category_id    INTEGER NOT NULL REFERENCES categories(id),
  fiscal_period  INTEGER NOT NULL CHECK(fiscal_period BETWEEN 1 AND 12),
  budget_amount  NUMERIC NOT NULL DEFAULT 0,
  UNIQUE(budget_id, category_id, fiscal_period)
);

CREATE TABLE IF NOT EXISTS app_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS local_users (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  email          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
  display_name   TEXT    NOT NULL DEFAULT '',
  role           TEXT    NOT NULL DEFAULT 'reports'
                         CHECK(role IN ('admin', 'reports')),
  password_hash  TEXT    NOT NULL,
  is_active      INTEGER NOT NULL DEFAULT 1,
  last_login_at  TEXT,
  created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS local_role_overrides (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  email      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
  role       TEXT    NOT NULL CHECK(role IN ('admin', 'reports')),
  note       TEXT,
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dashboard_announcements (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  message     TEXT    NOT NULL,
  severity    TEXT    NOT NULL DEFAULT 'info' CHECK(severity IN ('info', 'warning', 'urgent')),
  expires_at  TEXT,
  is_active   INTEGER NOT NULL DEFAULT 1,
  created_by  TEXT,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bank_import_batches (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  bank_account_id  INTEGER NOT NULL REFERENCES bank_accounts(id),
  filename         TEXT,
  imported_count   INTEGER NOT NULL DEFAULT 0,
  skipped_count    INTEGER NOT NULL DEFAULT 0,
  imported_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reserve_study_assumptions (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  study_year               INTEGER NOT NULL,
  reserve_balance_override NUMERIC,
  annual_contribution      NUMERIC NOT NULL DEFAULT 0,
  contribution_growth_rate NUMERIC NOT NULL DEFAULT 0.03,
  investment_return_rate   NUMERIC NOT NULL DEFAULT 0.01,
  num_lots                 INTEGER NOT NULL DEFAULT 1,
  projection_years         INTEGER NOT NULL DEFAULT 30,
  notes                    TEXT,
  is_active                INTEGER NOT NULL DEFAULT 1,
  created_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at               TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reserve_assets (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_group       TEXT    NOT NULL,
  component         TEXT    NOT NULL,
  install_year      INTEGER NOT NULL,
  useful_life_years INTEGER NOT NULL,
  condition         TEXT    NOT NULL DEFAULT 'Good'
                            CHECK(condition IN ('Excellent','Good','Moderate','Poor','Critical')),
  replacement_cost  NUMERIC NOT NULL DEFAULT 0,
  annual_inflation  NUMERIC NOT NULL DEFAULT 0.04,
  notes             TEXT,
  active_flag       INTEGER NOT NULL DEFAULT 1,
  sort_order        INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reserve_study_scenarios (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  scenario_name  TEXT    NOT NULL,
  description    TEXT,
  emergency_cost NUMERIC NOT NULL DEFAULT 0,
  expected_year  INTEGER,
  notes          TEXT,
  sort_order     INTEGER NOT NULL DEFAULT 0,
  active_flag    INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS hoa_profile (
  id                      INTEGER PRIMARY KEY CHECK (id = 1),
  legal_name              TEXT NOT NULL DEFAULT '',
  display_name            TEXT NOT NULL DEFAULT '',
  fiscal_year_start_month INTEGER NOT NULL DEFAULT 1
                                  CHECK(fiscal_year_start_month BETWEEN 1 AND 12),
  timezone                TEXT NOT NULL DEFAULT 'America/Chicago',
  default_annual_dues     TEXT NOT NULL DEFAULT '0.00',
  mailing_address_1       TEXT,
  city                    TEXT,
  state                   TEXT,
  postal_code             TEXT,
  phone                   TEXT,
  email                   TEXT,
  website                 TEXT,
  federal_tax_id          TEXT,
  created_at              TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  event_time   TEXT    NOT NULL DEFAULT (datetime('now')),
  entity_type  TEXT    NOT NULL,
  entity_id    INTEGER NOT NULL,
  action       TEXT    NOT NULL,
  before_json  TEXT,
  after_json   TEXT,
  changed_by   TEXT
);

CREATE TABLE IF NOT EXISTS workflow_tabs (
  id          INTEGER PRIMARY KEY,
  tab_key     TEXT    NOT NULL UNIQUE,
  icon        TEXT    NOT NULL DEFAULT '',
  label       TEXT    NOT NULL,
  description TEXT    NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 100,
  is_system   INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS workflow_sections (
  id          INTEGER PRIMARY KEY,
  tab_id      INTEGER NOT NULL REFERENCES workflow_tabs(id),
  label       TEXT    NOT NULL,
  tip_text    TEXT    NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 100,
  is_system   INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS workflow_cards (
  id          INTEGER PRIMARY KEY,
  section_id  INTEGER NOT NULL REFERENCES workflow_sections(id),
  num_label   TEXT    NOT NULL DEFAULT '',
  icon        TEXT    NOT NULL DEFAULT '',
  title       TEXT    NOT NULL,
  description TEXT    NOT NULL DEFAULT '',
  href        TEXT    NOT NULL DEFAULT '#',
  link_label  TEXT    NOT NULL DEFAULT '',
  color       TEXT    NOT NULL DEFAULT 'slate',
  sort_order  INTEGER NOT NULL DEFAULT 100,
  is_system   INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dues_billing_history (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_type      TEXT    NOT NULL,
  period_label    TEXT    NOT NULL,
  period_year     INTEGER NOT NULL,
  period_sequence INTEGER NOT NULL,
  amount          NUMERIC NOT NULL,
  owner_count     INTEGER NOT NULL DEFAULT 0,
  billed_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bank_account_file_formats (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  bank_account_id      INTEGER NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
  fingerprint          TEXT    NOT NULL,
  mapping_json         TEXT    NOT NULL,
  sample_headers_json  TEXT    NOT NULL,
  created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(bank_account_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS wizard_groups (
  id          INTEGER PRIMARY KEY,
  step_number INTEGER NOT NULL,
  group_id    TEXT    NOT NULL,
  label       TEXT    NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 100,
  is_system   INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1,
  UNIQUE(step_number, group_id)
);

CREATE TABLE IF NOT EXISTS wizard_options (
  id          INTEGER PRIMARY KEY,
  step_number INTEGER NOT NULL,
  group_id    TEXT    NOT NULL,
  option_id   TEXT    NOT NULL,
  label       TEXT    NOT NULL,
  description TEXT    NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 100,
  is_system   INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1,
  is_always   INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(step_number, option_id)
);

CREATE TABLE IF NOT EXISTS dashboard_alert_settings (
  alert_key   TEXT PRIMARY KEY,
  label       TEXT NOT NULL,
  description TEXT,
  enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dashboard_cards (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT    NOT NULL,
  description TEXT,
  card_type   TEXT    NOT NULL DEFAULT 'NAV'
                      CHECK(card_type IN ('NAV','REPORT','COMMENT','FINANCIAL','SECTION')),
  target_url  TEXT,
  report_name TEXT,
  color       TEXT    NOT NULL DEFAULT '#4a5462',
  is_system   INTEGER NOT NULL DEFAULT 0,
  is_active   INTEGER NOT NULL DEFAULT 1,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dashboard_layout (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id    INTEGER NOT NULL REFERENCES dashboard_cards(id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,
  created_at TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(card_id),
  UNIQUE(position)
);

CREATE TABLE IF NOT EXISTS backup_metadata (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  backed_up_at        TEXT    NOT NULL,
  lot_count           INTEGER,
  owner_count         INTEGER,
  renter_count        INTEGER,
  journal_entry_count INTEGER,
  last_gl_entry_date  TEXT
);

CREATE TABLE IF NOT EXISTS accounting_periods (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  period_year INTEGER NOT NULL,
  period_month INTEGER NOT NULL CHECK(period_month BETWEEN 1 AND 12),
  status      TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','LOCKED')),
  locked_at   TEXT,
  locked_by   TEXT,
  notes       TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(period_year, period_month)
);

CREATE TABLE IF NOT EXISTS board_members (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id     INTEGER REFERENCES owners(id),
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL DEFAULT 'MEMBER'
                    CHECK(role IN ('PRESIDENT','VICE_PRESIDENT','SECRETARY','TREASURER','MEMBER','AT_LARGE')),
  term_start   TEXT NOT NULL,
  term_end     TEXT,
  email        TEXT,
  phone        TEXT,
  notes        TEXT,
  active_flag  INTEGER NOT NULL DEFAULT 1 CHECK(active_flag IN (0,1)),
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
`;

const SEEDS: Array<[string, string, string, string, number, number]> = [
  // code, name, type, fund, sort_order, system_required
  ["DUES",             "HOA Dues",               "INCOME",   "OPERATING", 10, 1],
  ["LATE_FEE",         "Late Fee",                "INCOME",   "OPERATING", 20, 1],
  ["RESALE_FEE",       "Resale Fee",              "INCOME",   "OPERATING", 30, 1],
  ["BANK_INTEREST",    "Bank Interest",           "INCOME",   "OPERATING", 40, 0],
  ["RESERVE_INTEREST", "Reserve Interest",        "INCOME",   "RESERVE",   50, 0],
  ["OTHER_INCOME",     "Other Income",            "INCOME",   "OPERATING", 60, 0],
  ["LANDSCAPING",      "Landscaping",             "EXPENSE",  "OPERATING", 10, 0],
  ["UTILITIES",        "Utilities",               "EXPENSE",  "OPERATING", 20, 0],
  ["INSURANCE",        "Insurance",               "EXPENSE",  "OPERATING", 30, 0],
  ["MANAGEMENT",       "Management Fees",         "EXPENSE",  "OPERATING", 40, 0],
  ["LEGAL",            "Legal & Professional",    "EXPENSE",  "OPERATING", 50, 0],
  ["REPAIRS",          "Repairs & Maintenance",   "EXPENSE",  "OPERATING", 60, 0],
  ["ADMIN",            "Administrative",          "EXPENSE",  "OPERATING", 70, 0],
  ["TAXES",            "Taxes",                   "EXPENSE",  "OPERATING", 80, 0],
  ["OTHER_EXPENSE",    "Other Expense",           "EXPENSE",  "OPERATING", 90, 0],
  ["RESERVE_EXPENSE",  "Reserve Expenditure",     "EXPENSE",  "RESERVE",  100, 0],
  ["RESERVE_TRANSFER", "Reserve Fund Transfer",   "TRANSFER", "RESERVE",   10, 0],
];

export async function initSchema(db: DbHandle): Promise<void> {
  // Tauri SQL plugin only executes one statement per execute() call.
  // Split on semicolons and run each statement individually so all
  // CREATE TABLE IF NOT EXISTS blocks are applied on every open.
  const statements = DDL
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  for (const stmt of statements) {
    await db.execute(stmt + ";");
  }

  // Seed only if categories table is empty
  const rows = await db.select<[{ n: number }]>(
    "SELECT COUNT(*) as n FROM categories"
  );
  if (rows[0]?.n === 0) {
    for (const [code, name, type, fund, sort, sys] of SEEDS) {
      await db.execute(
        `INSERT INTO categories (code, name, category_type, fund_code, sort_order, system_required)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [code, name, type, fund, sort, sys]
      );
    }
  }
}
