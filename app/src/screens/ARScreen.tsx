import { useEffect, useState, useCallback } from "react";
import { getLotBalances, type LotBalance } from "../repositories/assessmentRepo";
import { PageLayout } from "../components/PageLayout";
import { useTableSort } from "../lib/useTableSort";
import { SortableTh } from "../components/SortableTh";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

function BalanceRow({ row }: { row: LotBalance }) {
  const isCredit = row.balance_due < -0.005;
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50">
      <td className="px-4 py-2.5 text-sm font-medium text-gray-900">Lot {row.lot_number}</td>
      <td className="px-4 py-2.5 text-sm text-gray-500">{row.owner_name ?? "— No owner —"}</td>
      <td className="px-4 py-2.5 text-right font-mono text-sm text-gray-700">{fmt(row.billed)}</td>
      <td className="px-4 py-2.5 text-right font-mono text-sm text-gray-700">{fmt(row.paid)}</td>
      <td className={`px-4 py-2.5 text-right font-mono text-sm font-semibold ${isCredit ? "text-green-700" : "text-red-700"}`}>
        {isCredit ? `(${fmt(Math.abs(row.balance_due))})` : fmt(row.balance_due)}
      </td>
    </tr>
  );
}

export function ARScreen() {
  const [rows, setRows] = useState<LotBalance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getLotBalances();
      setRows(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const outstanding = rows.filter((r) => r.balance_due > 0.005);
  const credits = rows.filter((r) => r.balance_due < -0.005);
  const current = rows.filter((r) => Math.abs(r.balance_due) <= 0.005);

  const lotAccessors = {
    lot: (r: LotBalance) => r.lot_number,
    owner: (r: LotBalance) => r.owner_name,
    billed: (r: LotBalance) => r.billed,
    paid: (r: LotBalance) => r.paid,
    balance: (r: LotBalance) => r.balance_due,
  };
  const outstandingSort = useTableSort(outstanding, lotAccessors);
  const creditsSort = useTableSort(credits, lotAccessors);
  const currentSort = useTableSort(current, lotAccessors);

  const totalOutstanding = outstanding.reduce((s, r) => s + r.balance_due, 0);
  const totalCredits = credits.reduce((s, r) => s + Math.abs(r.balance_due), 0);

  function Table({ title, data, sort, emptyMsg, headerClass }: {
    title: string;
    data: LotBalance[];
    sort: ReturnType<typeof useTableSort<LotBalance>>;
    emptyMsg: string;
    headerClass: string;
  }) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl overflow-auto max-h-[calc(100vh-200px)] mb-6">
        <div className={`px-4 py-3 border-b ${headerClass}`}>
          <span className="text-sm font-semibold">{title}</span>
        </div>
        {data.length === 0 ? (
          <p className="px-4 py-6 text-sm text-center text-gray-400">{emptyMsg}</p>
        ) : (
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-gray-50 border-b">
              <tr>
                <SortableTh label="Lot" col="lot" sortKey={sort.sortKey} sortDir={sort.sortDir} onSort={sort.toggleSort} />
                <SortableTh label="Owner" col="owner" sortKey={sort.sortKey} sortDir={sort.sortDir} onSort={sort.toggleSort} />
                <SortableTh label="Billed" col="billed" sortKey={sort.sortKey} sortDir={sort.sortDir} onSort={sort.toggleSort} right />
                <SortableTh label="Paid" col="paid" sortKey={sort.sortKey} sortDir={sort.sortDir} onSort={sort.toggleSort} right />
                <SortableTh label="Balance" col="balance" sortKey={sort.sortKey} sortDir={sort.sortDir} onSort={sort.toggleSort} right />
              </tr>
            </thead>
            <tbody>
              {sort.sorted.map((r) => <BalanceRow key={r.lot_id} row={r} />)}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  return (
    <PageLayout
      title="Accounts Receivable"
      subtitle="Balances by lot — outstanding, credits, and current."
      helpId="ar"
    >
      <div>
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            {/* Summary bar */}
            <div className="grid grid-cols-3 gap-4 mb-6">
              <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3">
                <p className="text-xs text-red-600 font-medium mb-1">Outstanding</p>
                <p className="font-mono text-lg font-bold text-red-800">{fmt(totalOutstanding)}</p>
                <p className="text-xs text-red-500">{outstanding.length} lot{outstanding.length !== 1 ? "s" : ""}</p>
              </div>
              <div className="bg-green-50 border border-green-100 rounded-xl px-4 py-3">
                <p className="text-xs text-green-600 font-medium mb-1">Credits / Prepaid</p>
                <p className="font-mono text-lg font-bold text-green-800">{fmt(totalCredits)}</p>
                <p className="text-xs text-green-500">{credits.length} lot{credits.length !== 1 ? "s" : ""}</p>
              </div>
              <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">
                <p className="text-xs text-gray-500 font-medium mb-1">Current / Paid</p>
                <p className="font-mono text-lg font-bold text-gray-700">{fmt(0)}</p>
                <p className="text-xs text-gray-400">{current.length} lot{current.length !== 1 ? "s" : ""}</p>
              </div>
            </div>

            <Table
              title="Outstanding Balances"
              data={outstanding}
              sort={outstandingSort}
              emptyMsg="No outstanding balances."
              headerClass="bg-red-50 text-red-700"
            />

            <Table
              title="Credits / Prepaid"
              data={credits}
              sort={creditsSort}
              emptyMsg="No credit balances."
              headerClass="bg-green-50 text-green-700"
            />

            <Table
              title="Current (No Balance)"
              data={current}
              sort={currentSort}
              emptyMsg="No lots with zero balance."
              headerClass="bg-gray-50 text-gray-600"
            />
          </>
        )}
      </div>
    </PageLayout>
  );
}
