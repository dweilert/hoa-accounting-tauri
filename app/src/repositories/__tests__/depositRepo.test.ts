import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  insertDepositBatch,
  listDepositBatches,
  updateDepositBatch,
  deleteDepositBatch,
  postDepositBatch,
  insertPayment,
  deletePayment,
  assignPaymentsToBatch,
  unassignPaymentFromBatch,
  listUnassignedPayments,
  listPaymentsForBatch,
  listPayments,
} from "../depositRepo";
import { createTestDb, seedBankAccount, seedLot, seedOwner, seedOwnership } from "../../lib/__tests__/testDb";
import type { DbHandle } from "../../lib/dbTypes";

vi.mock("../../lib/db", () => ({ getDb: vi.fn() }));
import { getDb } from "../../lib/db";
const mockGetDb = vi.mocked(getDb);

let db: DbHandle;
let accountId: number;
let lotId: number;

beforeEach(async () => {
  db = await createTestDb();
  mockGetDb.mockResolvedValue(db);
  accountId = await seedBankAccount(db);
  lotId = await seedLot(db);
  const ownerId = await seedOwner(db);
  await seedOwnership(db, lotId, ownerId);
});

// ── insertDepositBatch ────────────────────────────────────────────────────────

describe("insertDepositBatch", () => {
  it("creates a batch and returns its id", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId);
    expect(id).toBeGreaterThan(0);
  });

  it("stores notes when provided", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId, "March collection");
    const batches = await listDepositBatches();
    const batch = batches.find((b) => b.id === id);
    expect(batch?.notes).toBe("March collection");
  });

  it("starts with OPEN status and zero totals", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId);
    const batches = await listDepositBatches();
    const batch = batches.find((b) => b.id === id);
    expect(batch?.status).toBe("OPEN");
    expect(batch?.total_amount).toBe(0);
    expect(batch?.check_count).toBe(0);
  });

  it("includes account_name in list", async () => {
    await insertDepositBatch("2024-03-01", accountId);
    const batches = await listDepositBatches();
    expect(batches[0]?.account_name).toBe("Test Checking");
  });
});

// ── updateDepositBatch ────────────────────────────────────────────────────────

describe("updateDepositBatch", () => {
  it("changes date, account, and notes", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId, "old");
    const acct2 = await seedBankAccount(db, "Reserve Account");
    await updateDepositBatch(id, "2024-04-15", acct2, "updated notes");
    const batches = await listDepositBatches();
    const b = batches.find((x) => x.id === id)!;
    expect(b.deposit_date).toBe("2024-04-15");
    expect(b.account_name).toBe("Reserve Account");
    expect(b.notes).toBe("updated notes");
  });
});

// ── postDepositBatch ──────────────────────────────────────────────────────────

describe("postDepositBatch", () => {
  it("changes status to POSTED", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId);
    await postDepositBatch(id);
    const batches = await listDepositBatches();
    expect(batches.find((b) => b.id === id)?.status).toBe("POSTED");
  });
});

// ── deleteDepositBatch ────────────────────────────────────────────────────────

describe("deleteDepositBatch", () => {
  it("deletes a batch with zero total_amount", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId);
    await deleteDepositBatch(id);
    const batches = await listDepositBatches();
    expect(batches.find((b) => b.id === id)).toBeUndefined();
  });

  it("does NOT delete a batch that has payments", async () => {
    const id = await insertDepositBatch("2024-03-01", accountId);
    await insertPayment(id, {
      lot_id: lotId, payment_date: "2024-03-01",
      amount: 200, payment_method: "CHECK", payment_type: "DUES",
    });
    await deleteDepositBatch(id);
    // Batch should still exist because total_amount > 0
    const batches = await listDepositBatches();
    expect(batches.find((b) => b.id === id)).toBeDefined();
  });
});

// ── insertPayment + batch totals ──────────────────────────────────────────────

describe("insertPayment", () => {
  it("creates unassigned payment when batchId is null", async () => {
    const id = await insertPayment(null, {
      lot_id: lotId, payment_date: "2024-03-01",
      amount: 150, payment_method: "CHECK", payment_type: "DUES",
    });
    expect(id).toBeGreaterThan(0);
    const unassigned = await listUnassignedPayments();
    expect(unassigned.some((p) => p.id === id)).toBe(true);
  });

  it("assigns payment to batch and recalculates totals", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    await insertPayment(batchId, {
      lot_id: lotId, payment_date: "2024-03-01",
      amount: 275, payment_method: "ACH", payment_type: "DUES",
    });
    const batches = await listDepositBatches();
    const b = batches.find((x) => x.id === batchId)!;
    expect(b.total_amount).toBe(275);
    expect(b.check_count).toBe(1);
  });

  it("accumulates total when multiple payments added", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    const lot2 = await seedLot(db, "102");
    await insertPayment(batchId, { lot_id: lotId, payment_date: "2024-03-01", amount: 100, payment_method: "CHECK", payment_type: "DUES" });
    await insertPayment(batchId, { lot_id: lot2,  payment_date: "2024-03-01", amount: 200, payment_method: "CHECK", payment_type: "DUES" });
    const batches = await listDepositBatches();
    const b = batches.find((x) => x.id === batchId)!;
    expect(b.total_amount).toBe(300);
    expect(b.check_count).toBe(2);
  });

  it("payment shows lot_number", async () => {
    await insertPayment(null, { lot_id: lotId, payment_date: "2024-03-01", amount: 100, payment_method: "CHECK", payment_type: "DUES" });
    const payments = await listPayments();
    expect(payments[0]?.lot_number).toBe("101");
  });
});

// ── assignPaymentsToBatch ─────────────────────────────────────────────────────

describe("assignPaymentsToBatch", () => {
  it("assigns multiple unassigned payments to a batch", async () => {
    const p1 = await insertPayment(null, { lot_id: lotId, payment_date: "2024-03-01", amount: 100, payment_method: "CHECK", payment_type: "DUES" });
    const lot2 = await seedLot(db, "102");
    const p2 = await insertPayment(null, { lot_id: lot2,  payment_date: "2024-03-01", amount: 150, payment_method: "CHECK", payment_type: "DUES" });
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    await assignPaymentsToBatch([p1, p2], batchId);
    const batches = await listDepositBatches();
    const b = batches.find((x) => x.id === batchId)!;
    expect(b.total_amount).toBe(250);
    expect(b.check_count).toBe(2);
    const unassigned = await listUnassignedPayments();
    expect(unassigned.some((p) => p.id === p1)).toBe(false);
    expect(unassigned.some((p) => p.id === p2)).toBe(false);
  });

  it("no-op when paymentIds is empty", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    await expect(assignPaymentsToBatch([], batchId)).resolves.toBeUndefined();
    const batches = await listDepositBatches();
    expect(batches.find((b) => b.id === batchId)?.total_amount).toBe(0);
  });
});

// ── unassignPaymentFromBatch ──────────────────────────────────────────────────

describe("unassignPaymentFromBatch", () => {
  it("removes payment from batch and recalculates total", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    const pId = await insertPayment(batchId, { lot_id: lotId, payment_date: "2024-03-01", amount: 175, payment_method: "CHECK", payment_type: "DUES" });
    await unassignPaymentFromBatch(pId, batchId);
    const batches = await listDepositBatches();
    const b = batches.find((x) => x.id === batchId)!;
    expect(b.total_amount).toBe(0);
    expect(b.check_count).toBe(0);
    const unassigned = await listUnassignedPayments();
    expect(unassigned.some((p) => p.id === pId)).toBe(true);
  });
});

// ── listPaymentsForBatch ──────────────────────────────────────────────────────

describe("listPaymentsForBatch", () => {
  it("returns only payments for the specified batch", async () => {
    const b1 = await insertDepositBatch("2024-03-01", accountId);
    const b2 = await insertDepositBatch("2024-03-15", accountId);
    const lot2 = await seedLot(db, "102");
    const p1 = await insertPayment(b1, { lot_id: lotId, payment_date: "2024-03-01", amount: 100, payment_method: "CHECK", payment_type: "DUES" });
    await insertPayment(b2, { lot_id: lot2,  payment_date: "2024-03-15", amount: 200, payment_method: "CHECK", payment_type: "DUES" });
    const rows = await listPaymentsForBatch(b1);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.id).toBe(p1);
  });
});

// ── deletePayment ─────────────────────────────────────────────────────────────

describe("deletePayment", () => {
  it("removes payment and recalculates batch totals", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    const pId = await insertPayment(batchId, { lot_id: lotId, payment_date: "2024-03-01", amount: 200, payment_method: "CHECK", payment_type: "DUES" });
    await deletePayment(pId, batchId);
    const batches = await listDepositBatches();
    const b = batches.find((x) => x.id === batchId)!;
    expect(b.total_amount).toBe(0);
    const payments = await listPayments();
    expect(payments.some((p) => p.id === pId)).toBe(false);
  });

  it("removes unassigned payment (null batch)", async () => {
    const pId = await insertPayment(null, { lot_id: lotId, payment_date: "2024-03-01", amount: 100, payment_method: "CHECK", payment_type: "DUES" });
    await deletePayment(pId, null);
    const payments = await listPayments();
    expect(payments.some((p) => p.id === pId)).toBe(false);
  });
});

// ── NSF flow (payment_applications reversal) ──────────────────────────────────

describe("NSF reversal flow", () => {
  it("deleting payment_applications re-opens the assessment", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    const pId = await insertPayment(batchId, { lot_id: lotId, payment_date: "2024-03-01", amount: 300, payment_method: "CHECK", payment_type: "DUES" });
    // Manually create an assessment and apply the payment
    await db.execute(
      "INSERT INTO assessments (lot_id, charge_type, amount, assessment_date, status) VALUES (?, 'DUES', 300, '2024-01-01', 'PAID')",
      [lotId]
    );
    const asmtRows = await db.select<{ id: number }[]>("SELECT id FROM assessments WHERE lot_id=?", [lotId]);
    const asmtId = asmtRows[0]!.id;
    await db.execute(
      "INSERT INTO payment_applications (payment_id, assessment_id, amount) VALUES (?, ?, 300)",
      [pId, asmtId]
    );
    // NSF: delete applications then payment
    await db.execute("DELETE FROM payment_applications WHERE payment_id = ?", [pId]);
    await deletePayment(pId, batchId);
    // Verify applications gone
    const apps = await db.select<unknown[]>("SELECT id FROM payment_applications WHERE assessment_id=?", [asmtId]);
    expect(apps).toHaveLength(0);
    // Verify payment gone
    const payments = await listPayments();
    expect(payments.some((p) => p.id === pId)).toBe(false);
  });
});

// ── listUnassignedPayments ────────────────────────────────────────────────────

describe("listUnassignedPayments", () => {
  it("excludes payments assigned to a batch", async () => {
    const batchId = await insertDepositBatch("2024-03-01", accountId);
    await insertPayment(batchId, { lot_id: lotId, payment_date: "2024-03-01", amount: 100, payment_method: "CHECK", payment_type: "DUES" });
    await insertPayment(null,    { lot_id: lotId, payment_date: "2024-03-02", amount: 200, payment_method: "CHECK", payment_type: "DUES" });
    const unassigned = await listUnassignedPayments();
    expect(unassigned).toHaveLength(1);
    expect(unassigned[0]?.amount).toBe(200);
  });
});
