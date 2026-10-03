import { useEffect, useState, useCallback, useMemo } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type TxnRow = {
  txn_date: string;
  source_type: string;
  source_id: number;
  account_name: string | null;
  amount: number;
  description: string;
  lot_number: string | null;
  category: string | null;
};

type SortKey = keyof TxnRow;
type SortDir = "asc" | "desc";

async function loadTransactions(limit: number): Promise<TxnRow[]> {
  const db = await getDb();
  const sql = `
    SELECT p.payment_date AS txn_date,
           'PAYMENT'      AS source_type,
           p.id           AS source_id,
           b.account_name,
           p.amount,
           COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
           l.lot_number,
           'HOA Dues' AS category
    FROM   payments p
    JOIN   lots l              ON l.id = p.lot_id
    LEFT JOIN owners o         ON o.id = p.owner_id
    LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id
    LEFT JOIN bank_accounts b  ON b.id = d.bank_account_id

    UNION ALL

    SELECT a.assessment_date,
           'ASSESSMENT',
           a.id,
           NULL,
           -a.amount,
           COALESCE(a.description, a.charge_type) || ' — Lot ' || l.lot_number,
           l.lot_number,
           a.charge_type
    FROM   assessments a
    JOIN   lots l ON l.id = a.lot_id

    UNION ALL

    SELECT bp.payment_date,
           'BILL_PAYMENT',
           bp.id,
           b.account_name,
           -bp.amount,
           'Bill payment — ' || v.vendor_name,
           NULL,
           c.name
    FROM   bill_payments bp
    JOIN   vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN   vendors v       ON v.id = vb.vendor_id
    LEFT JOIN categories c ON c.id = vb.category_id
    JOIN   bank_accounts b ON b.id = bp.bank_account_id

    UNION ALL

    SELECT ib.income_date,
           'INCOME',
           ib.id,
           b.account_name,
           ib.amount,
           COALESCE(ib.description, c.name),
           l.lot_number,
           c.name
    FROM   income_batches ib
    JOIN   bank_accounts b ON b.id = ib.bank_account_id
    JOIN   categories c    ON c.id = ib.category_id
    LEFT JOIN lots l       ON l.id = ib.lot_id

    ORDER BY txn_date DESC
    LIMIT ?
  `;
  return db.select<TxnRow[]>(sql, [limit]);
}

const SOURCE_LABELS: Record<string, string> = {
  PAYMENT:      "Payment",
  BILL_PAYMENT: "Bill Payment",
  INCOME:       "Income",
  ASSESSMENT:   "Assessment",
};

const SOURCE_COLORS: Record<string, string> = {
  PAYMENT:      "bg-green-100 text-green-700",
  BILL_PAYMENT: "bg-red-100 text-red-700",
  INCOME:       "bg-blue-100 text-blue-700",
  ASSESSMENT:   "bg-orange-100 text-orange-700",
};

function colVal(r: TxnRow, key: SortKey): string | number {
  if (key === "source_type") return SOURCE_LABELS[r.source_type] ?? r.source_type;
  return r[key] ?? "";
}

export function TransactionsScreen() {
  const [rows, setRows]       = useState<TxnRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [limit, setLimit]     = useState(250);

  // Sort
  const [sortKey, setSortKey] = useState<SortKey>("txn_date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Per-column filters
  const [fDate, setFDate]     = useState("");
  const [fType, setFType]     = useState("");
  const [fDesc, setFDesc]     = useState("");
  const [fCat, setFCat]       = useState("");
  const [fAcct, setFAcct]     = useState("");
  const [fLot, setFLot]       = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await loadTransactions(limit));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { void load(); }, [load]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "amount" ? "desc" : "asc");
    }
  }

  const visible = useMemo(() => {
    let out = rows;

    if (fDate) out = out.filter((r) => r.txn_date.includes(fDate.trim()));
    if (fType) {
      const q = fType.trim().toLowerCase();
      out = out.filter((r) => (SOURCE_LABELS[r.source_type] ?? r.source_type).toLowerCase().includes(q));
    }
    if (fDesc) { const q = fDesc.trim().toLowerCase(); out = out.filter((r) => r.description.toLowerCase().includes(q)); }
    if (fCat)  { const q = fCat.trim().toLowerCase();  out = out.filter((r) => (r.category ?? "").toLowerCase().includes(q)); }
    if (fAcct) { const q = fAcct.trim().toLowerCase(); out = out.filter((r) => (r.account_name ?? "").toLowerCase().includes(q)); }
    if (fLot)  { const q = fLot.trim().toLowerCase();  out = out.filter((r) => (r.lot_number ?? "").toLowerCase().includes(q)); }

    out = [...out].sort((a, b) => {
      const av = colVal(a, sortKey);
      const bv = colVal(b, sortKey);
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });

    return out;
  }, [rows, fDate, fType, fDesc, fCat, fAcct, fLot, sortKey, sortDir]);

  const hasFilters = fDate || fType || fDesc || fCat || fAcct || fLot;

  function SortTh({ col, label, right }: { col: SortKey; label: string; right?: boolean }) {
    const active = sortKey === col;
    return (
      <th
        className={`px-3 py-2 text-xs font-medium text-gray-600 cursor-pointer select-none whitespace-nowrap ${right ? "text-right" : "text-left"}`}
        onClick={() => handleSort(col)}
      >
        {label}
        <span className="ml-1 text-gray-400">
          {active ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
        </span>
      </th>
    );
  }

  function FilterInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Filter…"}
        className="w-full border border-gray-200 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
      />
    );
  }

  return (
    <PageLayout
      title="All Transactions"
      subtitle="Payments, assessments, income, and expenses in date order."
      helpId="transactions"
      actions={
        <div className="flex items-center gap-2">
          {hasFilters && (
            <button
              onClick={() => { setFDate(""); setFType(""); setFDesc(""); setFCat(""); setFAcct(""); setFLot(""); }}
              className="text-xs px-2 py-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
            >
              Clear filters
            </button>
          )}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={100}>Last 100</option>
            <option value={250}>Last 250</option>
            <option value={500}>Last 500</option>
            <option value={1000}>Last 1000</option>
            <option value={9999}>All</option>
          </select>
        </div>
      }
    >
      <div>
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            <p className="text-xs text-gray-500 mb-2">
              {visible.length === rows.length
                ? `${rows.length} transactions`
                : `${visible.length} of ${rows.length} transactions`}
            </p>
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <SortTh col="txn_date"     label="Date" />
                    <SortTh col="source_type"  label="Type" />
                    <SortTh col="description"  label="Description" />
                    <SortTh col="category"     label="Category" />
                    <SortTh col="account_name" label="Account" />
                    <SortTh col="lot_number"   label="Lot" />
                    <SortTh col="amount"       label="Amount" right />
                  </tr>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <td className="px-2 py-1"><FilterInput value={fDate} onChange={setFDate} placeholder="2026-01…" /></td>
                    <td className="px-2 py-1"><FilterInput value={fType} onChange={setFType} placeholder="Payment…" /></td>
                    <td className="px-2 py-1"><FilterInput value={fDesc} onChange={setFDesc} /></td>
                    <td className="px-2 py-1"><FilterInput value={fCat}  onChange={setFCat}  /></td>
                    <td className="px-2 py-1"><FilterInput value={fAcct} onChange={setFAcct} /></td>
                    <td className="px-2 py-1"><FilterInput value={fLot}  onChange={setFLot}  placeholder="4207…" /></td>
                    <td className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">
                        {hasFilters ? "No matches." : "No transactions yet."}
                      </td>
                    </tr>
                  )}
                  {visible.map((r, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-3 py-1.5 text-gray-600 font-mono text-xs">{r.txn_date}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${SOURCE_COLORS[r.source_type] ?? "bg-gray-100 text-gray-700"}`}>
                          {SOURCE_LABELS[r.source_type] ?? r.source_type}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-gray-700 text-xs">{r.description}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-xs">{r.category ?? "—"}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-xs">{r.account_name ?? "—"}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-xs">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                      <td className={`px-3 py-1.5 text-right font-mono text-xs ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                        {fmt(r.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </PageLayout>
  );
}
