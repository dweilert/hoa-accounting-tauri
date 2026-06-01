import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type TxnRow = {
  txn_date: string;
  source_type: string;
  source_id: number;
  account_name: string;
  amount: number;
  description: string;
  lot_number: string | null;
};

async function loadTransactions(limit: number): Promise<TxnRow[]> {
  const db = await getDb();

  // Union of all transaction-like sources
  const sql = `
    SELECT p.payment_date       AS txn_date,
           'PAYMENT'            AS source_type,
           p.id                 AS source_id,
           b.account_name,
           p.amount,
           COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
           l.lot_number
    FROM   payments p
    JOIN   lots l         ON l.id = p.lot_id
    LEFT JOIN owners o    ON o.id = p.owner_id
    LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id
    LEFT JOIN bank_accounts b   ON b.id = d.bank_account_id

    UNION ALL

    SELECT bp.payment_date,
           'BILL_PAYMENT',
           bp.id,
           b.account_name,
           -bp.amount,
           'Bill payment — ' || v.vendor_name,
           NULL
    FROM   bill_payments bp
    JOIN   vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN   vendors v       ON v.id = vb.vendor_id
    JOIN   bank_accounts b ON b.id = bp.bank_account_id

    UNION ALL

    SELECT ib.income_date,
           'INCOME',
           ib.id,
           b.account_name,
           ib.amount,
           COALESCE(ib.description, c.name),
           l.lot_number
    FROM   income_batches ib
    JOIN   bank_accounts b ON b.id = ib.bank_account_id
    JOIN   categories c    ON c.id = ib.category_id
    LEFT JOIN lots l       ON l.id = ib.lot_id

    ORDER BY txn_date DESC
    LIMIT ?
  `;
  return db.select<TxnRow[]>(sql, [limit]);
}

export function TransactionsScreen() {
  const [rows, setRows] = useState<TxnRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);

  const load = useCallback(async () => {
    try {
      setRows(await loadTransactions(limit));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { void load(); }, [load]);

  const SOURCE_LABELS: Record<string, string> = {
    PAYMENT: "Payment",
    BILL_PAYMENT: "Bill Payment",
    INCOME: "Income",
  };

  return (
    <PageLayout
      title="All Transactions"
      subtitle="Posted transactions across all accounts."
      helpId="transactions"
      actions={
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value={50}>Last 50</option>
          <option value={100}>Last 100</option>
          <option value={250}>Last 250</option>
          <option value={500}>Last 500</option>
        </select>
      }
    >
      <div className="max-w-5xl">
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">
                      No transactions yet.
                    </td>
                  </tr>
                )}
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="px-4 py-2 text-gray-600">{r.txn_date}</td>
                    <td className="px-4 py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        r.source_type === "PAYMENT" ? "bg-green-100 text-green-700"
                        : r.source_type === "BILL_PAYMENT" ? "bg-red-100 text-red-700"
                        : "bg-blue-100 text-blue-700"
                      }`}>
                        {SOURCE_LABELS[r.source_type] ?? r.source_type}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-700">{r.description}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{r.account_name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                    <td className={`px-4 py-2 text-right font-mono ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                      {fmt(r.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </PageLayout>
  );
}
