/**
 * Shared data loaders for the Owner Ledger report.
 * Used by both ReportsScreen (on-screen display) and PublishStatementsScreen (batch S3 publish).
 */
import { getDb } from "./db";

export type OwnerLedgerRow = {
  txn_date: string;
  type: string;
  charge_type: string | null;
  description: string;
  amount: number;
  running_balance: number;
};

export type OLBeginItem = { label: string; amount: number };

export type OLOwnerInfo = {
  display_name: string;
  mailing_address_1: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  phone: string | null;
  email: string | null;
  lot_numbers: string[];
};

export type OwnerLedgerResult = {
  rows: OwnerLedgerRow[];
  beginningBalance: number;
  beginBalanceDetail: OLBeginItem[];
};

export async function loadOwnerLedger(ownerId: number, year: number): Promise<OwnerLedgerResult> {
  const db = await getDb();
  const yearStart = `${year}-01-01`;
  const yearEnd   = `${year}-12-31`;

  // Get all ownership periods active during the year for this owner.
  // A past owner (end_date set) is included if they owned during any part of the year.
  const ownershipRows = await db.select<{ lot_id: number; start_date: string; end_date: string | null }[]>(
    `SELECT lot_id, start_date, end_date FROM lot_ownership
     WHERE owner_id = ?
       AND start_date <= ?
       AND (end_date IS NULL OR end_date >= ?)`,
    [ownerId, yearEnd, yearStart]
  );

  if (ownershipRows.length === 0) {
    return { rows: [], beginningBalance: 0, beginBalanceDetail: [] };
  }

  // Compute beginning balance per ownership period (balance at the time the owner took possession).
  // For year-start owners (start_date <= yearStart) this is the lot balance at Jan 1.
  // For mid-year acquirers this is the lot balance at their acquisition date.
  let beginningBalance = 0;
  let openingBalAmount = 0;
  const chargeDetailMap = new Map<string, number>();
  let priorPayments = 0;

  for (const op of ownershipRows) {
    // "Prior to" = before ownership start date (which may be before year start for long-term owners)
    const priorTo = op.start_date;

    const obRows = await db.select<[{ amount: number }]>(
      `SELECT COALESCE(SUM(amount), 0) AS amount FROM opening_balances
       WHERE entity_type = 'LOT_DUES' AND entity_id = ? AND as_of_date <= ?`,
      [op.lot_id, priorTo]
    );
    const ob = obRows[0]?.amount ?? 0;
    openingBalAmount += ob;

    const assRows = await db.select<{ charge_type: string; total: number }[]>(
      `SELECT COALESCE(charge_type, 'OTHER') AS charge_type, SUM(amount) AS total
       FROM assessments WHERE lot_id = ? AND assessment_date < ?
       GROUP BY charge_type`,
      [op.lot_id, priorTo]
    );
    let lotCharges = 0;
    for (const r of assRows) {
      chargeDetailMap.set(r.charge_type, (chargeDetailMap.get(r.charge_type) ?? 0) + r.total);
      lotCharges += r.total;
    }

    const payRows = await db.select<[{ total: number }]>(
      `SELECT COALESCE(SUM(amount), 0) AS total FROM payments
       WHERE lot_id = ? AND payment_date < ?`,
      [op.lot_id, priorTo]
    );
    const lotPay = payRows[0]?.total ?? 0;
    priorPayments += lotPay;

    beginningBalance += ob - lotCharges + lotPay;
  }

  const beginBalanceDetail: OLBeginItem[] = [
    ...(openingBalAmount !== 0 ? [{ label: "Carried Forward", amount: openingBalAmount }] : []),
    ...Array.from(chargeDetailMap.entries()).map(([ct, total]) => ({ label: ct, amount: -total })),
    ...(priorPayments !== 0 ? [{ label: "Prior Payments", amount: priorPayments }] : []),
  ];

  // Fetch transactions within each ownership period, filtered by year.
  // JOIN with lot_ownership on owner_id so each owner only sees charges during their tenure.
  // Includes: assessments (dues/fees), payments, and lot-linked income_batches (resale fees,
  // late fees, fines, special assessments, NSF — any INCOME category tied to a specific lot).
  const rows = await db.select<Omit<OwnerLedgerRow, "running_balance">[]>(`
    SELECT txn_date, type, charge_type, description, amount FROM (
      SELECT a.assessment_date AS txn_date, 'CHARGE' AS type, a.charge_type,
             COALESCE(a.description, a.charge_type) AS description, -a.amount AS amount
      FROM assessments a
      JOIN lot_ownership lo ON lo.lot_id = a.lot_id AND lo.owner_id = ?
        AND a.assessment_date >= lo.start_date
        AND (lo.end_date IS NULL OR a.assessment_date <= lo.end_date)
      WHERE a.assessment_date BETWEEN ? AND ?
      UNION ALL
      SELECT p.payment_date, 'PAYMENT', NULL, COALESCE(p.memo, 'Payment'), p.amount
      FROM payments p
      JOIN lot_ownership lo ON lo.lot_id = p.lot_id AND lo.owner_id = ?
        AND p.payment_date >= lo.start_date
        AND (lo.end_date IS NULL OR p.payment_date <= lo.end_date)
      WHERE p.payment_date BETWEEN ? AND ?
      UNION ALL
      SELECT ib.income_date, 'FEE', c.name,
             COALESCE(ib.description, c.name) AS description, -ib.amount AS amount
      FROM income_batches ib
      JOIN categories c ON c.id = ib.category_id
      JOIN lot_ownership lo ON lo.lot_id = ib.lot_id AND lo.owner_id = ?
        AND ib.income_date >= lo.start_date
        AND (lo.end_date IS NULL OR ib.income_date <= lo.end_date)
      WHERE ib.lot_id IS NOT NULL
        AND c.category_type = 'INCOME'
        AND c.name != 'HOA Dues'
        AND ib.income_date BETWEEN ? AND ?
    ) ORDER BY txn_date ASC
  `, [ownerId, yearStart, yearEnd, ownerId, yearStart, yearEnd, ownerId, yearStart, yearEnd]);

  let balance = beginningBalance;
  const ledgerRows = rows.map((r) => { balance += r.amount; return { ...r, running_balance: balance }; });
  return { rows: ledgerRows.reverse(), beginningBalance, beginBalanceDetail };
}

export async function loadOwnerDetails(ownerId: number, year?: number): Promise<OLOwnerInfo[]> {
  const db = await getDb();
  const yearEnd   = year ? `${year}-12-31` : "9999-12-31";
  const yearStart = year ? `${year}-01-01` : "0001-01-01";

  // Get lots this owner held during the year (or ever, if no year given).
  const lotRows = await db.select<{ lot_id: number }[]>(
    `SELECT lot_id FROM lot_ownership
     WHERE owner_id = ?
       AND start_date <= ?
       AND (end_date IS NULL OR end_date >= ?)`,
    [ownerId, yearEnd, yearStart]
  );

  if (lotRows.length === 0) {
    // Owner exists but had no lots — return their basic info only.
    const ownRows = await db.select<{
      id: number; display_name: string; mailing_address_1: string | null;
      city: string | null; state: string | null; postal_code: string | null;
      phone: string | null; home_phone: string | null; email: string | null;
    }[]>("SELECT id, display_name, mailing_address_1, city, state, postal_code, phone, home_phone, email FROM owners WHERE id = ?", [ownerId]);
    return ownRows.map((o) => ({
      display_name: o.display_name, mailing_address_1: o.mailing_address_1,
      city: o.city, state: o.state, postal_code: o.postal_code,
      phone: o.phone ?? o.home_phone, email: o.email, lot_numbers: [],
    }));
  }

  const inClause = lotRows.map((r) => r.lot_id).join(",");

  // Get all co-owners of these lots whose ownership overlapped with the requesting owner's period.
  const rows = await db.select<{
    owner_id: number; display_name: string; mailing_address_1: string | null;
    city: string | null; state: string | null; postal_code: string | null;
    phone: string | null; home_phone: string | null; email: string | null; lot_number: string | null;
  }[]>(`
    SELECT o.id AS owner_id, o.display_name,
           o.mailing_address_1, o.city, o.state, o.postal_code,
           o.phone, o.home_phone, o.email, l.lot_number
    FROM lot_ownership lo1
    JOIN lots l ON l.id = lo1.lot_id
    JOIN lot_ownership lo2 ON lo2.lot_id = lo1.lot_id
      AND lo2.start_date <= COALESCE(lo1.end_date, '9999-12-31')
      AND (lo2.end_date IS NULL OR lo2.end_date >= lo1.start_date)
    JOIN owners o ON o.id = lo2.owner_id
    WHERE lo1.owner_id = ?
      AND lo1.lot_id IN (${inClause})
      AND lo1.start_date <= ?
      AND (lo1.end_date IS NULL OR lo1.end_date >= ?)
    ORDER BY o.id = ? DESC, o.display_name
  `, [ownerId, yearEnd, yearStart, ownerId]);

  const map = new Map<number, OLOwnerInfo>();
  for (const r of rows) {
    if (!map.has(r.owner_id)) {
      map.set(r.owner_id, {
        display_name: r.display_name, mailing_address_1: r.mailing_address_1,
        city: r.city, state: r.state, postal_code: r.postal_code,
        phone: r.phone ?? r.home_phone, email: r.email, lot_numbers: [],
      });
    }
    if (r.lot_number) map.get(r.owner_id)!.lot_numbers.push(r.lot_number);
  }
  return Array.from(map.values());
}
