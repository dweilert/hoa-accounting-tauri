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

  const beginRows = await db.select<[{ bal: number }]>(`
    SELECT COALESCE(SUM(amount), 0) AS bal FROM (
      SELECT -a.amount AS amount FROM assessments a WHERE a.owner_id = ? AND a.assessment_date < ?
      UNION ALL
      SELECT p.amount FROM payments p WHERE p.owner_id = ? AND p.payment_date < ?
    )
  `, [ownerId, yearStart, ownerId, yearStart]);
  const beginningBalance = beginRows[0]?.bal ?? 0;

  const chargeDetail = await db.select<{ charge_type: string; total: number }[]>(`
    SELECT COALESCE(charge_type, 'OTHER') AS charge_type, SUM(amount) AS total
    FROM assessments WHERE owner_id = ? AND assessment_date < ?
    GROUP BY charge_type ORDER BY charge_type
  `, [ownerId, yearStart]);

  const payDetail = await db.select<[{ total: number }]>(`
    SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE owner_id = ? AND payment_date < ?
  `, [ownerId, yearStart]);
  const priorPayments = payDetail[0]?.total ?? 0;

  const beginBalanceDetail: OLBeginItem[] = [
    ...chargeDetail.map((r) => ({ label: r.charge_type, amount: -r.total })),
    ...(priorPayments !== 0 ? [{ label: "Prior Payments", amount: priorPayments }] : []),
  ];

  const rows = await db.select<Omit<OwnerLedgerRow, "running_balance">[]>(`
    SELECT txn_date, type, charge_type, description, amount FROM (
      SELECT a.assessment_date AS txn_date, 'CHARGE' AS type, a.charge_type,
             COALESCE(a.description, a.charge_type) AS description, -a.amount AS amount
      FROM assessments a WHERE a.owner_id = ? AND a.assessment_date BETWEEN ? AND ?
      UNION ALL
      SELECT p.payment_date, 'PAYMENT', NULL, COALESCE(p.memo, 'Payment'), p.amount
      FROM payments p WHERE p.owner_id = ? AND p.payment_date BETWEEN ? AND ?
    ) ORDER BY txn_date ASC
  `, [ownerId, yearStart, yearEnd, ownerId, yearStart, yearEnd]);

  let balance = beginningBalance;
  const ledgerRows = rows.map((r) => { balance += r.amount; return { ...r, running_balance: balance }; });
  return { rows: ledgerRows.reverse(), beginningBalance, beginBalanceDetail };
}

export async function loadOwnerDetails(ownerId: number): Promise<OLOwnerInfo[]> {
  const db = await getDb();
  const rows = await db.select<{
    owner_id: number; display_name: string; mailing_address_1: string | null;
    city: string | null; state: string | null; postal_code: string | null;
    phone: string | null; home_phone: string | null; email: string | null; lot_number: string | null;
  }[]>(`
    SELECT o2.id AS owner_id, o2.display_name,
           o2.mailing_address_1, o2.city, o2.state, o2.postal_code,
           o2.phone, o2.home_phone, o2.email, l.lot_number
    FROM lot_ownership lo
    JOIN lots l ON l.id = lo.lot_id
    JOIN lot_ownership lo2 ON lo2.lot_id = l.id AND lo2.end_date IS NULL
    JOIN owners o2 ON o2.id = lo2.owner_id
    WHERE lo.owner_id = ? AND lo.end_date IS NULL
    ORDER BY o2.id = ? DESC, o2.display_name
  `, [ownerId, ownerId]);
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
