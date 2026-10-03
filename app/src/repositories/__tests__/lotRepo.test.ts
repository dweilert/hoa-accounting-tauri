import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  listLots,
  getLot,
  insertLot,
  updateLot,
  deleteLot,
  assignOwner,
  endOwnership,
  hasCurrentOwners,
  getOwnershipHistory,
} from "../lotRepo";
import { createTestDb, seedOwner } from "../../lib/__tests__/testDb";
import type { DbHandle } from "../../lib/dbTypes";

vi.mock("../../lib/db", () => ({ getDb: vi.fn() }));
import { getDb } from "../../lib/db";
const mockGetDb = vi.mocked(getDb);

let db: DbHandle;

beforeEach(async () => {
  db = await createTestDb();
  mockGetDb.mockResolvedValue(db);
});

// ── insertLot ─────────────────────────────────────────────────────────────────

describe("insertLot", () => {
  it("creates a lot and returns id", async () => {
    const id = await insertLot({ lot_number: "201", active_flag: 1 });
    expect(id).toBeGreaterThan(0);
  });

  it("lot number is stored correctly", async () => {
    const id = await insertLot({ lot_number: "202", active_flag: 1 });
    const lot = await getLot(id);
    expect(lot?.lot_number).toBe("202");
  });

  it("stores optional address fields", async () => {
    const id = await insertLot({
      lot_number: "203",
      street_address_1: "123 Main St",
      city: "Testville",
      state: "TX",
      postal_code: "75001",
      active_flag: 1,
    });
    const lot = await getLot(id);
    expect(lot?.street_address_1).toBe("123 Main St");
    expect(lot?.city).toBe("Testville");
  });
});

// ── listLots ──────────────────────────────────────────────────────────────────

describe("listLots", () => {
  it("returns all lots when activeOnly=false", async () => {
    await insertLot({ lot_number: "301", active_flag: 1 });
    await insertLot({ lot_number: "302", active_flag: 0 });
    const lots = await listLots(false);
    expect(lots.length).toBeGreaterThanOrEqual(2);
  });

  it("excludes inactive lots when activeOnly=true", async () => {
    await insertLot({ lot_number: "401", active_flag: 1 });
    const id402 = await insertLot({ lot_number: "402", active_flag: 1 });
    // deactivate via updateLot (insertLot does not set active_flag)
    await updateLot(id402, { lot_number: "402", active_flag: 0 });
    const lots = await listLots(true);
    expect(lots.every((l) => l.active_flag === 1)).toBe(true);
    expect(lots.some((l) => l.lot_number === "402")).toBe(false);
  });

  it("returns null owner_names for lots without owners", async () => {
    await insertLot({ lot_number: "501", active_flag: 1 });
    const lots = await listLots();
    const lot = lots.find((l) => l.lot_number === "501");
    expect(lot?.owner_names).toBeNull();
  });

  it("returns owner_names for lots with current owners", async () => {
    const id = await insertLot({ lot_number: "601", active_flag: 1 });
    const ownerId = await seedOwner(db, "Alice Smith");
    await assignOwner(id, ownerId, "2020-01-01");
    const lots = await listLots();
    const lot = lots.find((l) => l.lot_number === "601");
    expect(lot?.owner_names).toContain("Alice Smith");
  });
});

// ── getLot ────────────────────────────────────────────────────────────────────

describe("getLot", () => {
  it("returns null for nonexistent id", async () => {
    const lot = await getLot(99999);
    expect(lot).toBeNull();
  });

  it("returns correct lot by id", async () => {
    const id = await insertLot({ lot_number: "701", active_flag: 1 });
    const lot = await getLot(id);
    expect(lot?.id).toBe(id);
    expect(lot?.lot_number).toBe("701");
  });
});

// ── updateLot ─────────────────────────────────────────────────────────────────

describe("updateLot", () => {
  it("updates lot_number and address", async () => {
    const id = await insertLot({ lot_number: "800", active_flag: 1 });
    await updateLot(id, { lot_number: "801", street_address_1: "456 Elm", active_flag: 1 });
    const lot = await getLot(id);
    expect(lot?.lot_number).toBe("801");
    expect(lot?.street_address_1).toBe("456 Elm");
  });

  it("can deactivate a lot", async () => {
    const id = await insertLot({ lot_number: "802", active_flag: 1 });
    await updateLot(id, { lot_number: "802", active_flag: 0 });
    const lot = await getLot(id);
    expect(lot?.active_flag).toBe(0);
  });
});

// ── deleteLot ─────────────────────────────────────────────────────────────────

describe("deleteLot", () => {
  it("removes the lot", async () => {
    const id = await insertLot({ lot_number: "901", active_flag: 1 });
    await deleteLot(id);
    const lot = await getLot(id);
    expect(lot).toBeNull();
  });
});

// ── assignOwner / hasCurrentOwners ───────────────────────────────────────────

describe("assignOwner", () => {
  it("creates a lot_ownership row", async () => {
    const lotId = await insertLot({ lot_number: "1001", active_flag: 1 });
    const ownerId = await seedOwner(db, "Bob Jones");
    await assignOwner(lotId, ownerId, "2023-06-01");
    expect(await hasCurrentOwners(lotId)).toBe(true);
  });

  it("lot with no ownership returns false", async () => {
    const lotId = await insertLot({ lot_number: "1002", active_flag: 1 });
    expect(await hasCurrentOwners(lotId)).toBe(false);
  });
});

// ── endOwnership ─────────────────────────────────────────────────────────────

describe("endOwnership", () => {
  it("sets end_date and lot no longer has current owners", async () => {
    const lotId = await insertLot({ lot_number: "1101", active_flag: 1 });
    const ownerId = await seedOwner(db, "Carol White");
    await assignOwner(lotId, ownerId, "2020-01-01");
    const history = await getOwnershipHistory(lotId);
    const rowId = history[0]!.id;
    await endOwnership(rowId, "2023-12-31");
    expect(await hasCurrentOwners(lotId)).toBe(false);
  });
});

// ── getOwnershipHistory ───────────────────────────────────────────────────────

describe("getOwnershipHistory", () => {
  it("returns all ownership rows for a lot", async () => {
    const lotId = await insertLot({ lot_number: "1201", active_flag: 1 });
    const o1 = await seedOwner(db, "Owner One");
    const o2 = await seedOwner(db, "Owner Two");
    await assignOwner(lotId, o1, "2018-01-01");
    const history1 = await getOwnershipHistory(lotId);
    await endOwnership(history1[0]!.id, "2020-12-31");
    await assignOwner(lotId, o2, "2021-01-01");
    const history = await getOwnershipHistory(lotId);
    expect(history).toHaveLength(2);
    const names = history.map((h) => h.display_name);
    expect(names).toContain("Owner One");
    expect(names).toContain("Owner Two");
  });

  it("returns empty array for lot with no history", async () => {
    const lotId = await insertLot({ lot_number: "1301", active_flag: 1 });
    const history = await getOwnershipHistory(lotId);
    expect(history).toHaveLength(0);
  });
});
