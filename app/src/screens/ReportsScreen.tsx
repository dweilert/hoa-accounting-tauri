import React, { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankAccount } from "../types/bankAccount";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── AR Aging ──────────────────────────────────────────────────────────────────

type AgingBucket = { lot_number: string; owner_name: string | null; current: number; d30: number; d60: number; d90plus: number; total: number };

async function loadARaging(): Promise<AgingBucket[]> {
  const db = await getDb();
  const today = new Date().toISOString().slice(0, 10);
  const rows = await db.select<AgingBucket[]>(`
    SELECT l.lot_number,
           o.display_name AS owner_name,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) <= 30 THEN a.amount ELSE 0 END) AS current,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) BETWEEN 31 AND 60 THEN a.amount ELSE 0 END) AS d30,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) BETWEEN 61 AND 90 THEN a.amount ELSE 0 END) AS d60,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) > 90 THEN a.amount ELSE 0 END) AS d90plus,
           SUM(a.amount) AS total
    FROM assessments a
    JOIN lots l ON l.id = a.lot_id
    LEFT JOIN owners o ON o.id = a.owner_id
    WHERE a.status IN ('OPEN', 'PARTIAL')
    GROUP BY l.lot_number, o.display_name
    HAVING total > 0
    ORDER BY total DESC
  `, [today, today, today, today]);
  return rows;
}

// ── Expense Summary ───────────────────────────────────────────────────────────

type ExpenseRow = { category_name: string; total: number };

async function loadExpenseSummary(year: number): Promise<ExpenseRow[]> {
  const db = await getDb();
  const rows = await db.select<ExpenseRow[]>(`
    SELECT category_name, SUM(total) AS total FROM (
      -- Vendor bill payments
      SELECT c.name AS category_name, SUM(bp.amount) AS total
      FROM bill_payments bp
      JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
      JOIN categories c ON c.id = vb.category_id
      WHERE strftime('%Y', bp.payment_date) = ?
      GROUP BY c.name
      UNION ALL
      -- Direct expense entries via income_batches (negative = outflow, positive = reimbursement reducing expense)
      SELECT c.name AS category_name, SUM(-ib.amount) AS total
      FROM income_batches ib
      JOIN categories c ON c.id = ib.category_id
      WHERE c.category_type = 'EXPENSE'
        AND strftime('%Y', ib.income_date) = ?
      GROUP BY c.name
    )
    GROUP BY category_name
    ORDER BY total DESC
  `, [String(year), String(year)]);
  return rows;
}

// ── Income Summary ────────────────────────────────────────────────────────────

type IncomeRow = { category_name: string; total: number };

async function loadIncomeSummary(year: number): Promise<IncomeRow[]> {
  const db = await getDb();
  const [payments, income] = await Promise.all([
    db.select<Array<{ total: number }>>(`
      SELECT SUM(amount) AS total FROM payments
      WHERE strftime('%Y', payment_date) = ?
    `, [String(year)]),
    db.select<IncomeRow[]>(`
      SELECT c.name AS category_name, SUM(ib.amount) AS total
      FROM income_batches ib
      JOIN categories c ON c.id = ib.category_id
      WHERE c.category_type = 'INCOME'
        AND strftime('%Y', ib.income_date) = ?
      GROUP BY c.name ORDER BY total DESC
    `, [String(year)]),
  ]);
  const rows: IncomeRow[] = [
    { category_name: "HOA Dues Payments", total: payments[0]?.total ?? 0 },
    ...income,
  ];
  return rows.filter((r) => r.total > 0);
}

// ── Transaction History ───────────────────────────────────────────────────────

type TxnRow = { txn_date: string; source_type: string; account_name: string | null; description: string; lot_number: string | null; amount: number };

async function loadTransactionHistory(limit: number): Promise<TxnRow[]> {
  const db = await getDb();
  return db.select<TxnRow[]>(`
    SELECT txn_date, source_type, account_name, description, lot_number, amount FROM (
      SELECT p.payment_date AS txn_date, 'PAYMENT' AS source_type, b.account_name,
             COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description, l.lot_number, p.amount
      FROM payments p JOIN lots l ON l.id = p.lot_id LEFT JOIN owners o ON o.id = p.owner_id
      LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id LEFT JOIN bank_accounts b ON b.id = d.bank_account_id
      UNION ALL
      SELECT bp.payment_date, 'BILL_PAYMENT', b.account_name,
             'Bill — ' || v.vendor_name, NULL, -bp.amount
      FROM bill_payments bp JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
      JOIN vendors v ON v.id = vb.vendor_id JOIN bank_accounts b ON b.id = bp.bank_account_id
      UNION ALL
      SELECT ib.income_date, 'INCOME', b.account_name,
             COALESCE(ib.description, c.name), l.lot_number, ib.amount
      FROM income_batches ib JOIN categories c ON c.id = ib.category_id
      JOIN bank_accounts b ON b.id = ib.bank_account_id LEFT JOIN lots l ON l.id = ib.lot_id
    ) ORDER BY txn_date DESC LIMIT ?
  `, [limit]);
}

const SOURCE_LABELS: Record<string, string> = { PAYMENT: "Payment", BILL_PAYMENT: "Bill Payment", INCOME: "Income" };

// ── Homeowner Contact List ────────────────────────────────────────────────────

type ContactRow = {
  lot_number: string;
  owner_name: string | null;
  owner_type: string | null;
  email: string | null;
  phone: string | null;
  home_phone: string | null;
  mailing_address_1: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
};

async function loadContactList(): Promise<ContactRow[]> {
  const db = await getDb();
  return db.select<ContactRow[]>(`
    SELECT l.lot_number,
           o.display_name AS owner_name, o.owner_type,
           o.email, o.phone, o.home_phone,
           o.mailing_address_1, o.city, o.state, o.postal_code
    FROM lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
    LEFT JOIN owners o ON o.id = lo.owner_id
    WHERE l.active_flag = 1
    ORDER BY l.lot_number
  `);
}

function ContactListReport({
  hoaName = "",
  runDate = "",
}: {
  hoaName?: string;
  runDate?: string;
}) {
  const [rows, setRows] = useState<ContactRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadContactList()
      .then(setRows)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;

  // Page splitting. Each row has a 2-line address (~47px tall).
  // 10.5in page, 0.5in padding each side = 9.5in usable.
  // PDF confirmed ~16-17 rows fit on page 1 before overflow — use 16.
  // Continuation pages have a smaller header so can fit slightly more — use 18.
  const ROWS_PAGE_1 = 16;
  const ROWS_PER_PAGE = 18;

  const page1Rows = rows.slice(0, ROWS_PAGE_1);
  const remaining = rows.slice(ROWS_PAGE_1);
  const extraPages: ContactRow[][] = [];
  for (let i = 0; i < remaining.length; i += ROWS_PER_PAGE) {
    extraPages.push(remaining.slice(i, i + ROWS_PER_PAGE));
  }
  const totalPages = 1 + extraPages.length;

  function TableHead() {
    return (
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Owner</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Email</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold whitespace-nowrap">Phone</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Mailing Address</th>
        </tr>
      </thead>
    );
  }

  function TableRows({ pageRows }: { pageRows: ContactRow[] }) {
    return (
      <tbody className="divide-y divide-gray-100">
        {pageRows.length === 0 && (
          <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">No homeowners found.</td></tr>
        )}
        {pageRows.map((r) => {
          const phone = r.phone ?? r.home_phone;
          const hasOwner = !!r.owner_name;
          return (
            <tr key={r.lot_number} className={hasOwner ? "" : "bg-gray-50"}>
              <td className="px-3 py-2">
                {hasOwner
                  ? <span className="font-semibold text-gray-900">{r.owner_name}</span>
                  : <span className="italic text-gray-400">— No owner —</span>}
              </td>
              <td className="px-3 py-2 text-gray-500">{r.email ?? <span className="text-gray-300">—</span>}</td>
              <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{phone ?? <span className="text-gray-300">—</span>}</td>
              <td className="px-3 py-2 text-gray-500">
                {r.mailing_address_1 ? (
                  <>
                    <span>{r.mailing_address_1}</span>
                    {(r.city || r.state || r.postal_code) && (
                      <><br /><span>{[r.city, r.state, r.postal_code].filter(Boolean).join(", ")}</span></>
                    )}
                  </>
                ) : <span className="text-gray-300">—</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    );
  }

  return (
    <>
      {/* Page 1 */}
      <div className="rpt-wrap">
        <div className="rpt-inner">
          <div className="rpt-content">
            <div className="hidden print:block mb-4 pb-3 border-b-2 border-gray-400">
              <p className="text-[9px] text-gray-400 mb-1">{runDate}</p>
              {hoaName && <p className="text-[11px] font-semibold text-gray-700 text-center">{hoaName}</p>}
              <p className="text-sm font-semibold text-gray-700 text-center mt-0.5">Contact List</p>
            </div>
            <table className="w-full text-[11px]">
              <TableHead />
              <TableRows pageRows={page1Rows} />
            </table>
          </div>
          <div className="rpt-footer">
            <span>{hoaName}</span>
            <span>Page 1 of {totalPages}</span>
          </div>
        </div>
      </div>

      {/* Continuation pages */}
      {extraPages.map((pageRows, i) => (
        <div key={i} className="rpt-wrap">
          <div className="rpt-inner">
            <div className="rpt-content">
              <div className="hidden print:block mb-3">
                {hoaName && <p className="text-[11px] font-semibold text-gray-700 text-center">{hoaName}</p>}
                <p className="text-[10px] text-gray-500 text-center">Contact List (continued)</p>
              </div>
              <table className="w-full text-[11px]">
                <TableHead />
                <TableRows pageRows={pageRows} />
              </table>
            </div>
            <div className="rpt-footer">
              <span>{hoaName}</span>
              <span>Page {i + 2} of {totalPages}</span>
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

// ── Owner Ledger ──────────────────────────────────────────────────────────────
// Types and data loaders shared with PublishStatementsScreen via lib/ownerLedgerData.ts
import {
  loadOwnerLedger, loadOwnerDetails,
  type OLOwnerInfo, type OwnerLedgerResult,
} from "../lib/ownerLedgerData";

type OwnerSummary = { id: number; display_name: string; lot_number: string | null };

async function loadOwners(): Promise<OwnerSummary[]> {
  const db = await getDb();
  return db.select<OwnerSummary[]>(`
    SELECT o.id, o.display_name,
           GROUP_CONCAT(l.lot_number) AS lot_number
    FROM owners o
    LEFT JOIN lot_ownership lo ON lo.owner_id = o.id AND lo.end_date IS NULL
    LEFT JOIN lots l ON l.id = lo.lot_id
    WHERE o.active_flag = 1
    GROUP BY o.id
    ORDER BY o.display_name
  `);
}

function olFmtAbs(n: number) {
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(n));
}
function olFmtBal(n: number) { return n < 0 ? `-${olFmtAbs(n)}` : olFmtAbs(n); }
function olBalColor(n: number) { return n < 0 ? "text-red-600" : "text-gray-900"; }
function olFmtCharge(ct: string | null) {
  if (!ct) return "Charge";
  return ct.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function OwnerLedgerReport({
  ownerId = 0,
  year = new Date().getFullYear(),
}: {
  ownerId?: number;
  year?: number;
  hoaName?: string;
  runDate?: string;
}) {
  const [result, setResult]           = useState<OwnerLedgerResult | null>(null);
  const [ownerDetails, setOwnerDetails] = useState<OLOwnerInfo[]>([]);
  const [loading, setLoading]         = useState(true);
  const [loadError, setLoadError]     = useState<string | null>(null);

  useEffect(() => {
    if (!ownerId) { setLoading(false); return; }
    setLoading(true);
    setLoadError(null);
    Promise.all([loadOwnerLedger(ownerId, year), loadOwnerDetails(ownerId, year)])
      .then(([res, details]) => { setResult(res); setOwnerDetails(details); })
      .catch((e) => setLoadError(String(e)))
      .finally(() => setLoading(false));
  }, [ownerId, year]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (loadError) return <p className="text-sm text-red-600">Error: {loadError}</p>;
  if (!result)  return null;

  const rows       = result.rows; // descending (most recent first)
  const beginBal   = result.beginningBalance;
  const closingBal = rows[0]?.running_balance ?? beginBal;

  return (
    <div className="space-y-4 text-[11px]">

      {/* Owner info */}
      {ownerDetails.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Owner</div>
          <div className="p-4 grid grid-cols-2 gap-4">
            {ownerDetails.map((o, i) => (
              <div key={i}>
                <p className="font-bold text-gray-900 text-sm">{o.display_name}</p>
                {o.lot_numbers.length > 0 && <p className="text-gray-500">Lot{o.lot_numbers.length > 1 ? "s" : ""}: {o.lot_numbers.join(", ")}</p>}
                {o.email && <p className="text-gray-500">{o.email}</p>}
                {o.phone && <p className="text-gray-500">{o.phone}</p>}
                {o.mailing_address_1 && <p className="text-gray-500 mt-0.5">{o.mailing_address_1}</p>}
                {(o.city || o.state || o.postal_code) && (
                  <p className="text-gray-500">{[o.city, o.state, o.postal_code].filter(Boolean).join(" ")}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Single transaction table — beginning balance at bottom, closing at top */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-auto max-h-[calc(100vh-200px)] ">
        <table className="w-full text-[11px]">
          <thead className="bg-gray-50 border-b sticky top-0 z-10">
            <tr className="bg-slate-800 text-white">
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Date</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Type</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Description</th>
              <th className="px-3 py-2 text-right text-[10px] font-semibold">Charge</th>
              <th className="px-3 py-2 text-right text-[10px] font-semibold">Payment</th>
              <th className="px-3 py-2 text-right text-[10px] font-semibold">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {/* Closing balance row */}
            <tr className="bg-gray-50 font-semibold">
              <td className="px-3 py-2 text-gray-500">{year}</td>
              <td colSpan={4} className="px-3 py-2 text-gray-700">Closing Balance</td>
              <td className={`px-3 py-2 text-right font-mono ${olBalColor(closingBal)}`}>{olFmtBal(closingBal)}</td>
            </tr>

            {/* Transactions — most recent first */}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">No transactions for {year}.</td></tr>
            )}
            {rows.map((r, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-3 py-1.5 text-gray-600">{r.txn_date}</td>
                <td className="px-3 py-1.5">
                  {r.type === "PAYMENT"
                    ? <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-100 text-green-700 min-w-[60px] text-center">Payment</span>
                    : <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-100 text-red-700 min-w-[60px] text-center">{olFmtCharge(r.charge_type)}</span>
                  }
                </td>
                <td className="px-3 py-1.5 text-gray-700">{r.description}</td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-800">{r.amount < 0 ? olFmtAbs(r.amount) : ""}</td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-800">{r.amount >= 0 ? olFmtAbs(r.amount) : ""}</td>
                <td className={`px-3 py-1.5 text-right font-mono ${olBalColor(r.running_balance)}`}>{olFmtBal(r.running_balance)}</td>
              </tr>
            ))}

            {/* Beginning balance — always shown */}
            <tr className="bg-gray-50 font-semibold border-t-2 border-gray-300">
              <td className="px-3 py-2 text-gray-500">Jan 1</td>
              <td colSpan={4} className="px-3 py-2 text-gray-700">
                Beginning Balance
                {result.beginBalanceDetail.length > 0 && (
                  <span className="ml-2 font-normal text-gray-500 text-[10px]">
                    ({result.beginBalanceDetail.map((d) => `${olFmtCharge(d.label)}: ${olFmtBal(d.amount)}`).join(" · ")})
                  </span>
                )}
              </td>
              <td className={`px-3 py-2 text-right font-mono ${olBalColor(beginBal)}`}>{olFmtBal(beginBal)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Budget vs Actual ──────────────────────────────────────────────────────────

type BvARow = { category_name: string; budget_amount: number; actual_amount: number; variance: number };

async function loadBudgetVsActual(year: number): Promise<BvARow[]> {
  const db = await getDb();
  return db.select<BvARow[]>(`
    SELECT c.name AS category_name,
           COALESCE(SUM(bl.budget_amount), 0) AS budget_amount,
           COALESCE(SUM(bp.amount), 0) AS actual_amount,
           COALESCE(SUM(bl.budget_amount), 0) - COALESCE(SUM(bp.amount), 0) AS variance
    FROM categories c
    LEFT JOIN budgets b ON b.fiscal_year = ? AND b.fund_code = c.fund_code
    LEFT JOIN budget_lines bl ON bl.budget_id = b.id AND bl.category_id = c.id
    LEFT JOIN vendor_bills vb ON vb.category_id = c.id
    LEFT JOIN bill_payments bp ON bp.vendor_bill_id = vb.id AND strftime('%Y', bp.payment_date) = ?
    WHERE c.category_type = 'EXPENSE'
    GROUP BY c.id, c.name
    HAVING budget_amount > 0 OR actual_amount > 0
    ORDER BY c.sort_order, c.name
  `, [year, String(year)]);
}

function BudgetVsActualReport({ year }: { year: number }) {
  const [rows, setRows] = useState<BvARow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadBudgetVsActual(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  const totalBudget = rows.reduce((s, r) => s + r.budget_amount, 0);
  const totalActual = rows.reduce((s, r) => s + r.actual_amount, 0);

  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Category</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Budget</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Actual</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Variance</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">vs Budget</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">No budget or expense data for {year}.</td></tr>}
        {rows.map((r) => {
          const pct = r.budget_amount > 0 ? (r.actual_amount / r.budget_amount) * 100 : null;
          return (
            <tr key={r.category_name}>
              <td className="px-3 py-1.5 text-gray-700">{r.category_name}</td>
              <td className="px-3 py-1.5 text-right font-mono text-gray-500">{fmt(r.budget_amount)}</td>
              <td className="px-3 py-1.5 text-right font-mono text-red-600">{fmt(r.actual_amount)}</td>
              <td className={`px-3 py-1.5 text-right font-mono ${r.variance >= 0 ? "text-green-700" : "text-red-600"}`}>{fmt(r.variance)}</td>
              <td className="px-3 py-1.5">
                {pct !== null ? (
                  <div className="flex items-center gap-2">
                    <div className="w-20 bg-gray-200 rounded-full h-1.5">
                      <div className={`h-1.5 rounded-full ${pct > 100 ? "bg-red-500" : pct > 80 ? "bg-orange-400" : "bg-green-500"}`}
                        style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                    <span className="text-gray-500">{pct.toFixed(0)}%</span>
                  </div>
                ) : "—"}
              </td>
            </tr>
          );
        })}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono text-gray-600">{fmt(totalBudget)}</td>
            <td className="px-3 py-1.5 text-right font-mono text-red-700">{fmt(totalActual)}</td>
            <td className={`px-3 py-1.5 text-right font-mono ${totalBudget - totalActual >= 0 ? "text-green-700" : "text-red-600"}`}>{fmt(totalBudget - totalActual)}</td>
            <td className="px-3 py-1.5" />
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ── Expense Detail ────────────────────────────────────────────────────────────

type ExpenseDetailRow = {
  payment_date: string;
  vendor_name: string;
  invoice_number: string;
  category_name: string;
  amount: number;
  check_number: string | null;
};

async function loadExpenseDetail(year: number): Promise<ExpenseDetailRow[]> {
  const db = await getDb();
  return db.select<ExpenseDetailRow[]>(`
    SELECT bp.payment_date, v.vendor_name, vb.invoice_number,
           c.name AS category_name, bp.amount, bp.check_number
    FROM bill_payments bp
    JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN vendors v ON v.id = vb.vendor_id
    LEFT JOIN categories c ON c.id = vb.category_id
    WHERE strftime('%Y', bp.payment_date) = ?
    ORDER BY bp.payment_date DESC
  `, [String(year)]);
}

function ExpenseDetailReport({ year }: { year: number }) {
  const [rows, setRows] = useState<ExpenseDetailRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadExpenseDetail(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Date</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Vendor</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Invoice</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Category</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Amount</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">No expense payments for {year}.</td></tr>}
        {rows.map((r, i) => (
          <tr key={i}>
            <td className="px-3 py-1.5 text-gray-600">{r.payment_date}</td>
            <td className="px-3 py-1.5 text-gray-700">{r.vendor_name}</td>
            <td className="px-3 py-1.5 text-gray-500">{r.invoice_number}</td>
            <td className="px-3 py-1.5 text-gray-500">{r.category_name ?? "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono text-red-600">{fmt(r.amount)}</td>
          </tr>
        ))}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td colSpan={4} className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono text-red-700">{fmt(rows.reduce((s, r) => s + r.amount, 0))}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ── Vendor Expenses ───────────────────────────────────────────────────────────

type VendorExpenseRow = { vendor_name: string; paid: number; open: number; total: number };

async function loadVendorExpenses(year: number): Promise<VendorExpenseRow[]> {
  const db = await getDb();
  return db.select<VendorExpenseRow[]>(`
    SELECT v.vendor_name,
           COALESCE(SUM(CASE WHEN vb.status IN ('PAID','PARTIAL') THEN bp.amount ELSE 0 END), 0) AS paid,
           COALESCE(SUM(CASE WHEN vb.status = 'OPEN' THEN vb.amount ELSE 0 END), 0) AS open,
           COALESCE(SUM(vb.amount), 0) AS total
    FROM vendors v
    JOIN vendor_bills vb ON vb.vendor_id = v.id AND strftime('%Y', vb.invoice_date) = ?
    LEFT JOIN bill_payments bp ON bp.vendor_bill_id = vb.id
    GROUP BY v.id, v.vendor_name
    ORDER BY total DESC
  `, [String(year)]);
}

function VendorExpensesReport({ year }: { year: number }) {
  const [rows, setRows] = useState<VendorExpenseRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadVendorExpenses(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Vendor</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Paid</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Open</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Total Invoiced</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">No vendor invoices for {year}.</td></tr>}
        {rows.map((r) => (
          <tr key={r.vendor_name}>
            <td className="px-3 py-1.5 text-gray-700">{r.vendor_name}</td>
            <td className="px-3 py-1.5 text-right font-mono text-green-700">{fmt(r.paid)}</td>
            <td className="px-3 py-1.5 text-right font-mono text-orange-600">{r.open > 0 ? fmt(r.open) : "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono font-semibold text-gray-900">{fmt(r.total)}</td>
          </tr>
        ))}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono text-green-800">{fmt(rows.reduce((s, r) => s + r.paid, 0))}</td>
            <td className="px-3 py-1.5 text-right font-mono text-orange-700">{fmt(rows.reduce((s, r) => s + r.open, 0))}</td>
            <td className="px-3 py-1.5 text-right font-mono text-gray-900">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ── Deposits Report ───────────────────────────────────────────────────────────

type DepositReportRow = {
  deposit_date: string;
  account_name: string;
  check_count: number;
  total_amount: number;
  status: string;
};

async function loadDepositsReport(year: number): Promise<DepositReportRow[]> {
  const db = await getDb();
  return db.select<DepositReportRow[]>(`
    SELECT d.deposit_date, b.account_name, d.check_count, d.total_amount, d.status
    FROM deposit_batches d
    JOIN bank_accounts b ON b.id = d.bank_account_id
    WHERE strftime('%Y', d.deposit_date) = ?
    ORDER BY d.deposit_date DESC
  `, [String(year)]);
}

function DepositsReport({ year }: { year: number }) {
  const [rows, setRows] = useState<DepositReportRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadDepositsReport(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Date</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Account</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Amount</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={3} className="px-3 py-6 text-center text-gray-400">No deposits for {year}.</td></tr>}
        {rows.map((r, i) => (
          <tr key={i}>
            <td className="px-3 py-1.5 text-gray-600">{r.deposit_date}</td>
            <td className="px-3 py-1.5 text-gray-500">{r.account_name}</td>
            <td className="px-3 py-1.5 text-right font-mono text-green-700">{fmt(r.total_amount)}</td>
          </tr>
        ))}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td colSpan={2} className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono text-green-800">{fmt(rows.reduce((s, r) => s + r.total_amount, 0))}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ── Delinquency Report ────────────────────────────────────────────────────────

type DelinquencyRow = {
  lot_number: string;
  owner_name: string | null;
  email: string | null;
  phone: string | null;
  open_amount: number;
  oldest_due_date: string | null;
  days_overdue: number;
};

async function loadDelinquency(): Promise<DelinquencyRow[]> {
  const db = await getDb();
  const today = new Date().toISOString().slice(0, 10);
  return db.select<DelinquencyRow[]>(`
    SELECT l.lot_number, o.display_name AS owner_name, o.email, o.phone,
           SUM(a.amount) AS open_amount,
           MIN(COALESCE(a.due_date, a.assessment_date)) AS oldest_due_date,
           CAST(julianday(?) - julianday(MIN(COALESCE(a.due_date, a.assessment_date))) AS INTEGER) AS days_overdue
    FROM assessments a
    JOIN lots l ON l.id = a.lot_id
    LEFT JOIN owners o ON o.id = a.owner_id
    WHERE a.status IN ('OPEN','PARTIAL')
      AND julianday(?) > julianday(COALESCE(a.due_date, a.assessment_date))
    GROUP BY l.id
    ORDER BY days_overdue DESC
  `, [today, today]);
}

function DelinquencyReport() {
  const [rows, setRows] = useState<DelinquencyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDelinquency()
      .then(setRows)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;
  if (rows.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-green-700 bg-green-50 rounded-lg border border-green-200">
        No delinquent accounts — all assessments are current.
      </div>
    );
  }

  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Lot</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Owner</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Contact</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Oldest Due</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Days Overdue</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Balance Due</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.map((r) => (
          <tr key={r.lot_number} className={r.days_overdue > 90 ? "bg-red-50" : r.days_overdue > 30 ? "bg-orange-50" : ""}>
            <td className="px-3 py-1.5 font-medium text-gray-900">Lot {r.lot_number}</td>
            <td className="px-3 py-1.5 text-gray-700">{r.owner_name ?? "—"}</td>
            <td className="px-3 py-1.5 text-gray-500">{r.email ?? r.phone ?? "—"}</td>
            <td className="px-3 py-1.5 text-gray-500">{r.oldest_due_date ?? "—"}</td>
            <td className={`px-3 py-1.5 text-right font-mono font-semibold ${r.days_overdue > 90 ? "text-red-600" : r.days_overdue > 30 ? "text-orange-600" : "text-yellow-700"}`}>
              {r.days_overdue}d
            </td>
            <td className="px-3 py-1.5 text-right font-mono font-semibold text-red-700">{fmt(r.open_amount)}</td>
          </tr>
        ))}
        <tr className="bg-gray-50 font-semibold text-[11px]">
          <td colSpan={5} className="px-3 py-1.5 text-gray-600">Total ({rows.length} lots)</td>
          <td className="px-3 py-1.5 text-right font-mono text-red-700">{fmt(rows.reduce((s, r) => s + r.open_amount, 0))}</td>
        </tr>
      </tbody>
    </table>
  );
}

function TransactionHistoryReport({ limit = 500 }: { limit?: number }) {
  const [rows, setRows] = useState<TxnRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setRows(await loadTransactionHistory(limit)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [limit]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;

  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Date</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Type</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Description</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Account</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Lot</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Amount</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">No transactions yet.</td></tr>}
        {rows.map((r, i) => (
          <tr key={i}>
            <td className="px-3 py-1.5 text-gray-600">{r.txn_date}</td>
            <td className="px-3 py-1.5">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.source_type === "PAYMENT" ? "bg-green-100 text-green-700" : r.source_type === "BILL_PAYMENT" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"}`}>
                {SOURCE_LABELS[r.source_type] ?? r.source_type}
              </span>
            </td>
            <td className="px-3 py-1.5 text-gray-700">{r.description}</td>
            <td className="px-3 py-1.5 text-gray-400">{r.account_name ?? "—"}</td>
            <td className="px-3 py-1.5 text-gray-400">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
            <td className={`px-3 py-1.5 text-right font-mono ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(r.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Account Detail (Ledger) ───────────────────────────────────────────────────

type LedgerRow = { txn_date: string; source_type: string; description: string; amount: number; lot_number: string | null; running_balance?: number };

async function loadLedger(bankAccountId: number, limit: number): Promise<LedgerRow[]> {
  const db = await getDb();
  const rows = await db.select<LedgerRow[]>(`
    SELECT p.payment_date AS txn_date, 'PAYMENT' AS source_type,
           COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
           p.amount, l.lot_number
    FROM payments p JOIN lots l ON l.id = p.lot_id LEFT JOIN owners o ON o.id = p.owner_id
    LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id WHERE d.bank_account_id = ?
    UNION ALL
    SELECT bp.payment_date, 'BILL_PAYMENT', 'Bill — ' || v.vendor_name, -bp.amount, NULL
    FROM bill_payments bp JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN vendors v ON v.id = vb.vendor_id WHERE bp.bank_account_id = ?
    UNION ALL
    SELECT ib.income_date, 'INCOME', COALESCE(ib.description, c.name), ib.amount, l.lot_number
    FROM income_batches ib JOIN categories c ON c.id = ib.category_id
    LEFT JOIN lots l ON l.id = ib.lot_id WHERE ib.bank_account_id = ?
    ORDER BY txn_date ASC LIMIT ?
  `, [bankAccountId, bankAccountId, bankAccountId, limit]);
  let balance = 0;
  for (const r of rows) { balance += r.amount; r.running_balance = balance; }
  return rows.reverse();
}

function AccountDetailReport({ accountId = 0, limit = 500 }: { accountId?: number; limit?: number }) {
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) { setLoading(false); return; }
    setLoading(true);
    try { setRows(await loadLedger(accountId, limit)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [accountId, limit]);

  useEffect(() => { if (accountId) void load(); }, [load, accountId]);

  return (
    <div className="space-y-3">
      {!accountId && !loading && <p className="text-sm text-gray-500">No bank account selected. Select one above and click Run Report.</p>}
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && rows.length > 0 && (
        <table className="w-full text-[11px]">
          <thead className="bg-gray-50 border-b sticky top-0 z-10">
            <tr className="bg-slate-800 text-white">
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Date</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Type</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Description</th>
              <th className="px-3 py-2 text-left text-[10px] font-semibold">Lot</th>
              <th className="px-3 py-2 text-right text-[10px] font-semibold">Amount</th>
              <th className="px-3 py-2 text-right text-[10px] font-semibold">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="px-3 py-1.5 text-gray-600">{r.txn_date}</td>
                <td className="px-3 py-1.5">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${r.source_type === "PAYMENT" ? "bg-green-100 text-green-700" : r.source_type === "BILL_PAYMENT" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"}`}>
                    {SOURCE_LABELS[r.source_type] ?? r.source_type}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-gray-700">{r.description}</td>
                <td className="px-3 py-1.5 text-gray-400">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                <td className={`px-3 py-1.5 text-right font-mono ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(r.amount)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-700">{r.running_balance !== undefined ? fmt(r.running_balance) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Report types ──────────────────────────────────────────────────────────────

// ── Inline summary report components ─────────────────────────────────────────

function ARAgingReport() {
  const [rows, setRows] = useState<AgingBucket[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { loadARaging().then(setRows).finally(() => setLoading(false)); }, []);
  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Lot</th>
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Owner</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Current (0–30d)</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">31–60d</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">61–90d</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">90d+</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Total</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-400">No outstanding balances.</td></tr>}
        {rows.map((r) => (
          <tr key={r.lot_number}>
            <td className="px-3 py-1.5 font-medium text-gray-900">Lot {r.lot_number}</td>
            <td className="px-3 py-1.5 text-gray-600">{r.owner_name ?? "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono">{r.current > 0 ? fmt(r.current) : "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono">{r.d30 > 0 ? fmt(r.d30) : "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono text-orange-600">{r.d60 > 0 ? fmt(r.d60) : "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono text-red-600">{r.d90plus > 0 ? fmt(r.d90plus) : "—"}</td>
            <td className="px-3 py-1.5 text-right font-mono font-semibold text-gray-900">{fmt(r.total)}</td>
          </tr>
        ))}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td colSpan={2} className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono">{fmt(rows.reduce((s, r) => s + r.current, 0))}</td>
            <td className="px-3 py-1.5 text-right font-mono">{fmt(rows.reduce((s, r) => s + r.d30, 0))}</td>
            <td className="px-3 py-1.5 text-right font-mono">{fmt(rows.reduce((s, r) => s + r.d60, 0))}</td>
            <td className="px-3 py-1.5 text-right font-mono">{fmt(rows.reduce((s, r) => s + r.d90plus, 0))}</td>
            <td className="px-3 py-1.5 text-right font-mono text-gray-900">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function IncomeSummaryReport({ year }: { year: number }) {
  const [rows, setRows] = useState<IncomeRow[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { setLoading(true); loadIncomeSummary(year).then(setRows).finally(() => setLoading(false)); }, [year]);
  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Category</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Total {year}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={2} className="px-3 py-6 text-center text-gray-400">No income for {year}.</td></tr>}
        {rows.map((r) => (
          <tr key={r.category_name}>
            <td className="px-3 py-1.5 text-gray-700">{r.category_name}</td>
            <td className="px-3 py-1.5 text-right font-mono text-green-700">{fmt(r.total)}</td>
          </tr>
        ))}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono text-green-800">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function ExpenseSummaryReport({ year }: { year: number }) {
  const [rows, setRows] = useState<ExpenseRow[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { setLoading(true); loadExpenseSummary(year).then(setRows).finally(() => setLoading(false)); }, [year]);
  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <table className="w-full text-[11px]">
      <thead className="bg-gray-50 border-b sticky top-0 z-10">
        <tr className="bg-slate-800 text-white">
          <th className="px-3 py-2 text-left text-[10px] font-semibold">Category</th>
          <th className="px-3 py-2 text-right text-[10px] font-semibold">Total {year}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.length === 0 && <tr><td colSpan={2} className="px-3 py-6 text-center text-gray-400">No expenses for {year}.</td></tr>}
        {rows.map((r) => (
          <tr key={r.category_name}>
            <td className="px-3 py-1.5 text-gray-700">{r.category_name}</td>
            <td className="px-3 py-1.5 text-right font-mono text-red-600">{fmt(r.total)}</td>
          </tr>
        ))}
        {rows.length > 0 && (
          <tr className="bg-gray-50 font-semibold text-[11px]">
            <td className="px-3 py-1.5 text-gray-600">Total</td>
            <td className="px-3 py-1.5 text-right font-mono text-red-700">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ── Report definitions ────────────────────────────────────────────────────────

type ReportType =
  | "ar_aging" | "expense_summary" | "income_summary" | "txn_history"
  | "account_detail" | "contact_list" | "owner_ledger" | "budget_vs_actual"
  | "expense_detail" | "vendor_expenses" | "deposits" | "delinquency";

type ParamType = "year" | "owner" | "account" | "limit" | "none";

const REPORT_DEFS: { key: ReportType; title: string; description: string; params: ParamType[] }[] = [
  { key: "ar_aging",         title: "AR Aging",            description: "Outstanding balances by lot, bucketed by age",              params: ["none"] },
  { key: "delinquency",      title: "Delinquency",         description: "Overdue accounts ranked by days past due",                  params: ["none"] },
  { key: "contact_list",     title: "Contact List",        description: "Homeowner directory with addresses and contact info",       params: ["none"] },
  { key: "income_summary",   title: "Income Summary",      description: "Total income by category for the year",                    params: ["year"] },
  { key: "expense_summary",  title: "Expense Summary",     description: "Total expenses by category for the year",                  params: ["year"] },
  { key: "expense_detail",   title: "Expense Detail",      description: "Every expense payment with vendor and check number",       params: ["year"] },
  { key: "vendor_expenses",  title: "Vendor Expenses",     description: "Total invoiced and paid per vendor for the year",          params: ["year"] },
  { key: "budget_vs_actual", title: "Budget vs Actual",    description: "Compare budgeted vs actual spending by category",         params: ["year"] },
  { key: "deposits",         title: "Deposits",            description: "All deposit batches for the year",                        params: ["year"] },
  { key: "txn_history",      title: "Transaction History", description: "All transactions across all accounts",                    params: ["limit"] },
  { key: "account_detail",   title: "Account Detail",      description: "Ledger with running balance for one bank account",        params: ["account", "limit"] },
  { key: "owner_ledger",     title: "Owner Ledger",        description: "Charges and payments for a specific owner, with beginning and ending balances for the year.", params: ["owner", "year"] },
];

// Preserved for type compatibility — not used in new UI
const REPORTS = REPORT_DEFS;
// eslint-disable-next-line @typescript-eslint/no-unused-vars
void REPORTS;

const CURRENT_YEAR = new Date().getFullYear();

// ── Main screen ───────────────────────────────────────────────────────────────

import { PageLayout } from "../components/PageLayout";
import { appAlert } from "../components/AppDialogs";

export function ReportsScreen() {
  const [selected, setSelected] = useState<ReportType | "">("");
  const [year, setYear] = useState(CURRENT_YEAR);
  const [ownerId, setOwnerId] = useState(0);
  const [owners, setOwners] = useState<OwnerSummary[]>([]);
  const [accountId, setAccountId] = useState(0);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [txnLimit, setTxnLimit] = useState(100);
  const [runKey, setRunKey] = useState(0);
  const [hasRun, setHasRun] = useState(false);
  const [runDate, setRunDate] = useState("");
  const [hoaName, setHoaName] = useState("HOA Accounting");

  const def = REPORT_DEFS.find((r) => r.key === selected);
  const needsYear    = def?.params.includes("year");
  const needsOwner   = def?.params.includes("owner");
  const needsAccount = def?.params.includes("account");
  const needsLimit   = def?.params.includes("limit");

  useEffect(() => {
    loadOwners().then((o) => { setOwners(o); if (o[0]) setOwnerId(o[0].id); }).catch(() => {});
    listBankAccounts().then((a) => { setAccounts(a); if (a[0]) setAccountId(a[0].id); }).catch(() => {});
    // Load association name
    getDb()
      .then((db) => db.select<{ value: string }[]>(
        "SELECT value FROM app_settings WHERE key = 'hoa_name' LIMIT 1"
      ))
      .then((rows) => { if (rows[0]?.value) setHoaName(rows[0].value); })
      .catch(() => {});
  }, []);

  useEffect(() => { setHasRun(false); }, [selected]);

  function handleRun() {
    setRunKey((k) => k + 1);
    setHasRun(true);
    setRunDate(new Date().toLocaleString("en-US", {
      year: "numeric", month: "long", day: "numeric",
      hour: "numeric", minute: "2-digit",
    }));
  }

  /**
   * Generate a real PDF via @react-pdf/renderer, save to disk, and open in the
   * system PDF viewer (macOS Preview, Windows Edge, Linux evince, etc.).
   * No browser print dialog, no WKWebView layout quirks, exact page geometry.
   */
  async function handleSavePDF() {
    if (!selected || !hasRun) return;
    try {
      const { pdf } = await import("@react-pdf/renderer");
      const { writeFile } = await import("@tauri-apps/plugin-fs");
      const { homeDir } = await import("@tauri-apps/api/path");
      const { openPath } = await import("@tauri-apps/plugin-opener");

      const rDate = `Generated: ${runDate}`;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let docEl: React.ReactElement<any> | null = null;

      if (selected === "contact_list") {
        const { ContactListPDF } = await import("../reports/ContactListPDF");
        const rows = await loadContactList();
        docEl = <ContactListPDF rows={rows} hoaName={hoaName} runDate={rDate} />;

      } else if (selected === "owner_ledger") {
        const { OwnerLedgerPDF } = await import("../reports/OwnerLedgerPDF");
        const [result, details] = await Promise.all([loadOwnerLedger(ownerId, year), loadOwnerDetails(ownerId, year)]);
        docEl = <OwnerLedgerPDF result={result} ownerDetails={details} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "ar_aging") {
        const { ARAgingPDF } = await import("../reports/ARAgingPDF");
        const rows = await loadARaging();
        docEl = <ARAgingPDF rows={rows} hoaName={hoaName} runDate={rDate} />;

      } else if (selected === "delinquency") {
        const { DelinquencyPDF } = await import("../reports/DelinquencyPDF");
        const rows = await loadDelinquency();
        docEl = <DelinquencyPDF rows={rows} hoaName={hoaName} runDate={rDate} />;

      } else if (selected === "income_summary") {
        const { IncomeSummaryPDF } = await import("../reports/IncomeSummaryPDF");
        const rows = await loadIncomeSummary(year);
        docEl = <IncomeSummaryPDF rows={rows} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "expense_summary") {
        const { ExpenseSummaryPDF } = await import("../reports/ExpenseSummaryPDF");
        const rows = await loadExpenseSummary(year);
        docEl = <ExpenseSummaryPDF rows={rows} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "expense_detail") {
        const { ExpenseDetailPDF } = await import("../reports/ExpenseDetailPDF");
        const rows = await loadExpenseDetail(year);
        docEl = <ExpenseDetailPDF rows={rows} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "vendor_expenses") {
        const { VendorExpensesPDF } = await import("../reports/VendorExpensesPDF");
        const rows = await loadVendorExpenses(year);
        docEl = <VendorExpensesPDF rows={rows} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "budget_vs_actual") {
        const { BudgetVsActualPDF } = await import("../reports/BudgetVsActualPDF");
        const rows = await loadBudgetVsActual(year);
        docEl = <BudgetVsActualPDF rows={rows} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "deposits") {
        const { DepositsPDF } = await import("../reports/DepositsPDF");
        const rows = await loadDepositsReport(year);
        docEl = <DepositsPDF rows={rows} hoaName={hoaName} runDate={rDate} year={year} />;

      } else if (selected === "txn_history") {
        const { TransactionHistoryPDF } = await import("../reports/TransactionHistoryPDF");
        const rows = await loadTransactionHistory(txnLimit);
        docEl = <TransactionHistoryPDF rows={rows} hoaName={hoaName} runDate={rDate} />;

      } else if (selected === "account_detail") {
        const { AccountDetailPDF } = await import("../reports/AccountDetailPDF");
        const rows = await loadLedger(accountId, txnLimit);
        const acct = accounts.find((a) => a.id === accountId);
        docEl = <AccountDetailPDF rows={rows} hoaName={hoaName} runDate={rDate} accountName={acct?.account_name} />;
      }

      if (!docEl) {
        await appAlert("PDF generation not yet available for this report.");
        return;
      }

      const blob   = await pdf(docEl).toBlob();
      const buffer = await blob.arrayBuffer();
      const home   = await homeDir();
      const path   = `${home}/hoa-system/tauri/hoa-report.pdf`;
      await writeFile(path, new Uint8Array(buffer));
      await openPath(path);
    } catch (e) {
      await appAlert(`PDF generation failed: ${String(e)}`);
    }
  }

  return (
    <PageLayout title="Reports" subtitle="Financial summaries and operational reports." helpId="reports">
      <div className="max-w-5xl print:max-w-none print:w-full">
        {/* Selector + params — hidden when printing */}
        <div className="bg-white border rounded-lg p-4 mb-5 space-y-4 print:hidden">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-1">
              <label className="block text-xs font-medium text-gray-700 mb-1">Report</label>
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value as ReportType | "")}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="">— Select a report —</option>
                <optgroup label="AR &amp; Collections">
                  {REPORT_DEFS.filter((r) => ["ar_aging","delinquency"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
                <optgroup label="Income &amp; Expenses">
                  {REPORT_DEFS.filter((r) => ["income_summary","expense_summary","expense_detail","vendor_expenses","budget_vs_actual","deposits"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
                <optgroup label="Transactions &amp; Ledgers">
                  {REPORT_DEFS.filter((r) => ["txn_history","account_detail","owner_ledger"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
                <optgroup label="Directory">
                  {REPORT_DEFS.filter((r) => ["contact_list"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
              </select>
              {def && <p className="mt-1 text-xs text-gray-500">{def.description}</p>}
            </div>

            {needsYear && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Year</label>
                <select
                  value={year}
                  onChange={(e) => setYear(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {[CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2, CURRENT_YEAR - 3].map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-400">Jan 1 – Dec 31, {year}</p>
              </div>
            )}

            {needsOwner && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Owner</label>
                <select
                  value={ownerId}
                  onChange={(e) => setOwnerId(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {owners.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.display_name}{o.lot_number ? ` (Lot ${o.lot_number})` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {needsAccount && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
                <select
                  value={accountId}
                  onChange={(e) => setAccountId(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.account_name}</option>
                  ))}
                </select>
              </div>
            )}

            {needsLimit && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Row Limit</label>
                <select
                  value={txnLimit}
                  onChange={(e) => setTxnLimit(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  <option value={50}>Last 50</option>
                  <option value={100}>Last 100</option>
                  <option value={250}>Last 250</option>
                  <option value={500}>Last 500</option>
                </select>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 pt-1 border-t border-gray-100">
            <button
              onClick={handleRun}
              disabled={!selected}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Run Report
            </button>
            {hasRun && def && (
              <span className="text-xs text-gray-400">
                Showing: <strong>{def.title}</strong>
                {needsYear && ` — ${year}`}
              </span>
            )}
          </div>
        </div>

        {/* Report output */}
        {!hasRun && (
          <div className="text-center py-12 text-gray-400 text-sm border border-dashed border-gray-200 rounded-lg print:hidden">
            Select a report above and click <strong className="text-gray-500">Run Report</strong>.
          </div>
        )}

        {hasRun && (
          <>
            {/* Print CSS — Retirement Planner nested-flex pattern.
                .rpt-wrap is the page (flex col, min-height = page).
                .rpt-inner (flex col, flex:1) holds content + footer.
                .rpt-content (flex:1) expands; .rpt-footer (margin-top:auto) pins to bottom. */}
            <style>{`
              @page { size: letter portrait; margin: 0; }
              .rpt-wrap {
                min-height: 11in;
                padding: 0.6in 0.55in;
                display: flex;
                flex-direction: column;
                box-sizing: border-box;
                position: relative;
              }
              .rpt-inner {
                flex: 1;
                display: flex;
                flex-direction: column;
              }
              .rpt-content { flex: 1; }
              .rpt-footer {
                margin-top: auto;
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding-top: 6pt;
                border-top: 0.5px solid #d1d5db;
                font-size: 8pt;
                color: #6b7280;
              }
              @media print {
                /* Reset ancestors (html/body/root/main) and clamp .max-w-5xl
                   so it doesn't overflow the 8.5in page width. */
                html, body, #root, main, .max-w-5xl {
                  margin: 0 !important;
                  padding: 0 !important;
                  height: auto !important;
                  min-height: 0 !important;
                  max-width: none !important;
                  width: 100% !important;
                  overflow: visible !important;
                  -webkit-print-color-adjust: exact;
                  print-color-adjust: exact;
                }
                /* CRITICAL: collapse the AppShell flex wrapper and PageLayout's
                   padding div with display:contents so they are removed from the
                   layout tree entirely. Otherwise they remain block-level boxes
                   whose trailing height pushes content onto a phantom 2nd page. */
                #root > div, .p-6 {
                  display: contents !important;
                }
                thead { display: table-header-group; }
                tbody tr { page-break-inside: avoid; }
                .rpt-wrap {
                  /* 10.5in leaves a comfortable 0.5in safety margin under
                     the 11in letter page so rounding/footer-border math
                     can never spill across the page break. */
                  min-height: 10.5in;
                  height: auto;
                  padding: 0.5in 0.5in;
                  margin: 0;
                  width: 100%;
                  max-width: 8.5in;
                  box-sizing: border-box;
                  overflow: hidden;
                  page-break-after: avoid;
                  break-after: avoid-page;
                }
                .rpt-wrap ~ .rpt-wrap {
                  page-break-before: always;
                  break-before: page;
                  page-break-after: auto;
                  break-after: auto;
                }
                .rpt-wrap:last-child {
                  page-break-after: avoid !important;
                  break-after: avoid-page !important;
                }
                /* Flush trailing block accumulation in WKWebView — a zero-height
                   sibling after the last page wrap absorbs phantom margin. */
                .rpt-wrap:last-child::after {
                  content: "";
                  display: block;
                  height: 0;
                  page-break-after: avoid;
                  break-after: avoid-page;
                }
                .rpt-wrap, .rpt-wrap * {
                  -webkit-print-color-adjust: exact !important;
                  print-color-adjust: exact !important;
                }
              }
            `}</style>

            {/* Print button — hidden when printing */}
            <div className="flex justify-end mb-4 print:hidden">
              <button
                onClick={handleSavePDF}
                className="flex items-center gap-1.5 px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 text-gray-700"
              >
                <span>🖨</span>
                Print / PDF
              </button>
            </div>

            {/* Reports that manage their own page containers (multi-page capable) */}
            {selected === "owner_ledger" && (
              <OwnerLedgerReport key={runKey} ownerId={ownerId} year={year} hoaName={hoaName} runDate={`Generated: ${runDate}`} />
            )}
            {selected === "contact_list" && (
              <ContactListReport key={runKey} hoaName={hoaName} runDate={`Generated: ${runDate}`} />
            )}

            {/* All other reports: single page container */}
            {selected !== "owner_ledger" && selected !== "contact_list" && (
              <div className="rpt-wrap">
                <div className="rpt-inner">
                  {/* Print-only header */}
                  <div className="hidden print:block mb-6 pb-3 border-b-2 border-gray-400">
                    <p className="text-[9px] text-gray-400 mb-1">Generated: {runDate}</p>
                    {hoaName && <p className="text-[11px] font-semibold text-gray-700 text-center">{hoaName}</p>}
                    <p className="text-sm font-semibold text-gray-700 text-center mt-0.5">{def?.title ?? "Report"}{needsYear ? ` — ${year}` : ""}</p>
                  </div>

                  {/* Report components */}
                  <div id="report-output" className="rpt-content">
                  {selected === "ar_aging"         && <ARAgingReport        key={runKey} />}
                  {selected === "delinquency"       && <DelinquencyReport    key={runKey} />}
                  {selected === "income_summary"    && <IncomeSummaryReport  key={runKey} year={year} />}
                  {selected === "expense_summary"   && <ExpenseSummaryReport key={runKey} year={year} />}
                  {selected === "expense_detail"    && <ExpenseDetailReport  key={runKey} year={year} />}
                  {selected === "vendor_expenses"   && <VendorExpensesReport key={runKey} year={year} />}
                  {selected === "budget_vs_actual"  && <BudgetVsActualReport key={runKey} year={year} />}
                  {selected === "deposits"          && <DepositsReport       key={runKey} year={year} />}
                  {selected === "txn_history"       && <TransactionHistoryReport key={runKey} limit={txnLimit} />}
                  {selected === "account_detail"    && <AccountDetailReport  key={runKey} accountId={accountId} limit={txnLimit} />}
                  </div>

                  {/* Footer — pinned to page bottom via margin-top:auto */}
                  <div className="rpt-footer">
                    <span>{hoaName}</span>
                    <span>Page 1 of 1</span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </PageLayout>
  );
}
