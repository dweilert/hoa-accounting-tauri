import type Database from "@tauri-apps/plugin-sql";

const DDL = `
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

export async function initSchema(db: Database): Promise<void> {
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
