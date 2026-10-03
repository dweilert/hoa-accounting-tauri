import { describe, it, expect, beforeEach } from "vitest";
import { createTestDb } from "./testDb";
import type { DbHandle } from "../dbTypes";

describe("initSchema", () => {
  let db: DbHandle;

  beforeEach(async () => {
    db = await createTestDb();
  });

  // ── Tables ──────────────────────────────────────────────────────────────────

  const EXPECTED_TABLES = [
    "lots", "owners", "lot_ownership", "bank_accounts", "categories",
    "assessments", "deposit_batches", "payments", "payment_applications",
    "income_batches", "bank_transactions", "bank_transaction_links",
    "vendors", "vendor_bills", "bill_payments",
    "opening_balances", "accounting_periods", "reserve_transfers",
    "budgets", "budget_lines", "app_settings",
  ];

  it.each(EXPECTED_TABLES)("creates table: %s", async (table) => {
    const rows = await db.select<{ name: string }[]>(
      "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
      [table]
    );
    expect(rows).toHaveLength(1);
  });

  // ── Category seeds ──────────────────────────────────────────────────────────

  it("seeds at least 18 categories", async () => {
    const rows = await db.select<{ n: number }[]>("SELECT COUNT(*) AS n FROM categories");
    expect(rows[0]?.n).toBeGreaterThanOrEqual(18);
  });

  const REQUIRED_CODES = [
    "DUES", "LATE_FEE", "RESALE_FEE",
    "BANK_INTEREST", "RESERVE_INTEREST", "OTHER_INCOME",
    "BANK_FEE", "NSF_CHARGE",
    "LANDSCAPING", "UTILITIES", "INSURANCE", "MANAGEMENT",
    "LEGAL", "REPAIRS", "ADMIN", "TAXES", "OTHER_EXPENSE",
    "RESERVE_TRANSFER",
  ];

  it.each(REQUIRED_CODES)("seeds category code: %s", async (code) => {
    const rows = await db.select<{ code: string }[]>(
      "SELECT code FROM categories WHERE code=?", [code]
    );
    expect(rows).toHaveLength(1);
  });

  it("marks DUES, LATE_FEE, RESALE_FEE as system_required", async () => {
    const rows = await db.select<{ code: string }[]>(
      "SELECT code FROM categories WHERE system_required=1 ORDER BY code"
    );
    const codes = rows.map((r) => r.code);
    expect(codes).toContain("DUES");
    expect(codes).toContain("LATE_FEE");
    expect(codes).toContain("RESALE_FEE");
  });

  it("BANK_FEE is EXPENSE type", async () => {
    const rows = await db.select<{ category_type: string }[]>(
      "SELECT category_type FROM categories WHERE code='BANK_FEE'"
    );
    expect(rows[0]?.category_type).toBe("EXPENSE");
  });

  it("NSF_CHARGE is EXPENSE type", async () => {
    const rows = await db.select<{ category_type: string }[]>(
      "SELECT category_type FROM categories WHERE code='NSF_CHARGE'"
    );
    expect(rows[0]?.category_type).toBe("EXPENSE");
  });

  it("BANK_INTEREST is INCOME type", async () => {
    const rows = await db.select<{ category_type: string }[]>(
      "SELECT category_type FROM categories WHERE code='BANK_INTEREST'"
    );
    expect(rows[0]?.category_type).toBe("INCOME");
  });

  // ── Idempotency ─────────────────────────────────────────────────────────────

  it("calling initSchema twice does not duplicate seeds", async () => {
    const { initSchema } = await import("../schema");
    await initSchema(db); // second call
    const rows = await db.select<{ n: number }[]>("SELECT COUNT(*) AS n FROM categories");
    expect(rows[0]?.n).toBeGreaterThanOrEqual(18);
    // Ensure no duplicates
    const dups = await db.select<{ code: string; n: number }[]>(
      "SELECT code, COUNT(*) AS n FROM categories GROUP BY code HAVING n > 1"
    );
    expect(dups).toHaveLength(0);
  });

  // ── Constraints ─────────────────────────────────────────────────────────────

  it("rejects invalid assessment charge_type", async () => {
    await db.execute("INSERT INTO lots (lot_number, active_flag) VALUES ('X1', 1)");
    const lotRows = await db.select<{ id: number }[]>("SELECT id FROM lots WHERE lot_number='X1'");
    const lotId = lotRows[0]!.id;
    await expect(
      db.execute(
        "INSERT INTO assessments (lot_id, charge_type, amount, assessment_date) VALUES (?, 'INVALID', 100, '2024-01-01')",
        [lotId]
      )
    ).rejects.toThrow();
  });

  it("rejects assessment with zero amount", async () => {
    await db.execute("INSERT INTO lots (lot_number, active_flag) VALUES ('X2', 1)");
    const lotRows = await db.select<{ id: number }[]>("SELECT id FROM lots WHERE lot_number='X2'");
    const lotId = lotRows[0]!.id;
    await expect(
      db.execute(
        "INSERT INTO assessments (lot_id, charge_type, amount, assessment_date) VALUES (?, 'DUES', 0, '2024-01-01')",
        [lotId]
      )
    ).rejects.toThrow();
  });

  it("rejects income_batch with zero amount", async () => {
    await db.execute(
      "INSERT INTO bank_accounts (account_name, institution_name, account_type, fund_code, active_flag, opening_balance) VALUES ('A','B','CHECKING','OPERATING',1,0)"
    );
    const acctRows = await db.select<{ id: number }[]>("SELECT last_insert_rowid() AS id");
    const acctId = acctRows[0]!.id;
    const catRows = await db.select<{ id: number }[]>("SELECT id FROM categories WHERE code='BANK_INTEREST'");
    const catId = catRows[0]!.id;
    await expect(
      db.execute(
        "INSERT INTO income_batches (income_date, bank_account_id, category_id, amount) VALUES ('2024-01-01', ?, ?, 0)",
        [acctId, catId]
      )
    ).rejects.toThrow();
  });
});
