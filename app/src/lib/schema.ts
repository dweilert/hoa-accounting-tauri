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
  await db.execute(DDL);

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
