import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";

// ── Types ─────────────────────────────────────────────────────────────────────

type LotStatement = {
  lot_id: number;
  lot_number: string;
  street_address_1: string | null;
  owner_names: string | null;
  owner_email: string | null;
  mailing_address: string | null;
  mailing_city: string | null;
  mailing_state: string | null;
  mailing_postal: string | null;
  opening_balance: number;   // balance before fromDate (0 if no fromDate)
  charges: LedgerLine[];
  payments: LedgerLine[];
  balance: number;           // ending balance of the period
};

type LedgerLine = {
  entry_date: string;
  description: string;
  charge: number | null;
  payment: number | null;
  running_balance: number;
};

type LotSummary = {
  lot_id: number;
  lot_number: string;
  owner_names: string | null;
  balance: number;
  selected: boolean;
};

type DateRange = { fromDate: string; toDate: string };

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

// ── DB helpers ────────────────────────────────────────────────────────────────

async function loadLotSummaries(range: DateRange): Promise<LotSummary[]> {
  const db = await getDb();
  const fromForOwner = range.fromDate || "0000-01-01";
  // Balance shown = ob + all charges up to toDate − all payments up to toDate
  // (same as getLotBalances but filtered to toDate)
  const rows = await db.select<{ lot_id: number; lot_number: string; owner_names: string | null; balance: number }[]>(`
    SELECT
      l.id AS lot_id,
      l.lot_number,
      (SELECT GROUP_CONCAT(o2.display_name, ' / ')
       FROM lot_ownership lo2
       JOIN owners o2 ON o2.id = lo2.owner_id
       WHERE lo2.lot_id = l.id
         AND lo2.start_date <= ?
         AND (lo2.end_date IS NULL OR lo2.end_date >= ?)
      ) AS owner_names,
      ROUND(
        COALESCE(ob.amount, 0)
        + COALESCE((SELECT SUM(a.amount) FROM assessments a
                    WHERE a.lot_id = l.id
                      AND a.status NOT IN ('VOID','WRITTEN_OFF')
                      AND a.assessment_date <= ?), 0)
        - COALESCE((SELECT SUM(p.amount) FROM payments p
                    WHERE p.lot_id = l.id
                      AND p.payment_date <= ?), 0)
      , 2) AS balance
    FROM lots l
    LEFT JOIN opening_balances ob ON ob.entity_type = 'LOT_DUES' AND ob.entity_id = l.id
    WHERE l.active_flag = 1
    ORDER BY l.lot_number
  `, [range.toDate, fromForOwner, range.toDate, range.toDate]);
  return rows.map((r) => ({ ...r, selected: true }));
}

async function loadLotStatement(lotId: number, range: DateRange): Promise<LotStatement> {
  const db = await getDb();

  const hasFrom = range.fromDate !== "";

  const [lotRows, openingRows, chargeRows, paymentRows] = await Promise.all([
    // Lot info + owners active during period
    db.select<{ lot_number: string; street_address_1: string | null; owner_names: string | null; owner_email: string | null; mailing_address: string | null; mailing_city: string | null; mailing_state: string | null; mailing_postal: string | null }[]>(`
      SELECT l.lot_number, l.street_address_1,
             GROUP_CONCAT(o.display_name, ' / ') AS owner_names,
             MAX(o.email) AS owner_email,
             MAX(o.mailing_address_1) AS mailing_address, MAX(o.city) AS mailing_city,
             MAX(o.state) AS mailing_state, MAX(o.postal_code) AS mailing_postal
      FROM lots l
      LEFT JOIN lot_ownership lo ON lo.lot_id = l.id
        AND lo.start_date <= ?
        AND (lo.end_date IS NULL OR lo.end_date >= ?)
      LEFT JOIN owners o ON lo.owner_id = o.id
      WHERE l.id = ?
      GROUP BY l.id
    `, [range.toDate, hasFrom ? range.fromDate : "0000-01-01", lotId]),

    // Opening balance:
    //   hasFrom  → ob + charges before fromDate − payments before fromDate
    //   no from  → just ob.amount (stored opening balance)
    db.select<{ opening: number }[]>(`
      SELECT ROUND(
        COALESCE(ob.amount, 0)
        ${hasFrom ? `
        + COALESCE((SELECT SUM(a.amount) FROM assessments a
                    WHERE a.lot_id = ? AND a.status NOT IN ('VOID','WRITTEN_OFF')
                      AND a.assessment_date < ?), 0)
        - COALESCE((SELECT SUM(p.amount) FROM payments p
                    WHERE p.lot_id = ? AND p.payment_date < ?), 0)
        ` : ""}
      , 2) AS opening
      FROM lots l
      LEFT JOIN opening_balances ob ON ob.entity_type = 'LOT_DUES' AND ob.entity_id = l.id
      WHERE l.id = ?
    `, hasFrom ? [lotId, range.fromDate, lotId, range.fromDate, lotId] : [lotId]),

    // Period charges
    db.select<{ entry_date: string; description: string; amount: number }[]>(`
      SELECT a.assessment_date AS entry_date,
             COALESCE(a.description, c.name, 'Assessment') AS description,
             a.amount
      FROM assessments a
      LEFT JOIN categories c ON c.id = a.category_id
      WHERE a.lot_id = ?
        AND a.status NOT IN ('VOID','WRITTEN_OFF')
        AND (? = '' OR a.assessment_date >= ?)
        AND a.assessment_date <= ?
      ORDER BY a.assessment_date
    `, [lotId, range.fromDate, range.fromDate, range.toDate]),

    // Period payments (only from posted batches)
    db.select<{ entry_date: string; description: string; amount: number }[]>(`
      SELECT p.payment_date AS entry_date,
             COALESCE('Payment' || CASE WHEN p.check_number IS NOT NULL THEN ' #' || p.check_number ELSE '' END, 'Payment') AS description,
             p.amount
      FROM payments p
      JOIN deposit_batches d ON p.deposit_batch_id = d.id AND d.status = 'POSTED'
      WHERE p.lot_id = ?
        AND (? = '' OR p.payment_date >= ?)
        AND p.payment_date <= ?
      ORDER BY p.payment_date
    `, [lotId, range.fromDate, range.fromDate, range.toDate]),
  ]);

  const lot = lotRows[0];
  if (!lot) throw new Error(`Lot ${lotId} not found`);

  const opening = openingRows[0]?.opening ?? 0;

  type RawLine = { entry_date: string; description: string; charge?: number; payment?: number };
  const combined: RawLine[] = [
    ...chargeRows.map((r) => ({ entry_date: r.entry_date, description: r.description, charge: r.amount })),
    ...paymentRows.map((r) => ({ entry_date: r.entry_date, description: r.description, payment: r.amount })),
  ].sort((a, b) => a.entry_date.localeCompare(b.entry_date));

  let running = opening;
  const lines: LedgerLine[] = combined.map((r) => {
    running += (r.charge ?? 0) - (r.payment ?? 0);
    return {
      entry_date: r.entry_date,
      description: r.description,
      charge: r.charge ?? null,
      payment: r.payment ?? null,
      running_balance: running,
    };
  });

  return {
    lot_id: lotId,
    lot_number: lot.lot_number,
    street_address_1: lot.street_address_1,
    owner_names: lot.owner_names,
    owner_email: lot.owner_email,
    mailing_address: lot.mailing_address,
    mailing_city: lot.mailing_city,
    mailing_state: lot.mailing_state,
    mailing_postal: lot.mailing_postal,
    opening_balance: opening,
    charges: lines.filter((l) => l.charge !== null),
    payments: lines.filter((l) => l.payment !== null),
    balance: running,
  };
}

// ── Statement component ───────────────────────────────────────────────────────

function StatementView({ stmt, range }: { stmt: LotStatement; range: DateRange }) {
  type RawLine = { entry_date: string; description: string; charge?: number; payment?: number };
  const combined: RawLine[] = [
    ...stmt.charges.map((l) => ({ entry_date: l.entry_date, description: l.description, charge: l.charge! })),
    ...stmt.payments.map((l) => ({ entry_date: l.entry_date, description: l.description, payment: l.payment! })),
  ].sort((a, b) => a.entry_date.localeCompare(b.entry_date));

  let running = stmt.opening_balance;
  const lines = combined.map((r) => {
    running += (r.charge ?? 0) - (r.payment ?? 0);
    return { ...r, running_balance: running };
  });

  const hasFrom = range.fromDate !== "";
  const periodLabel = hasFrom
    ? `${range.fromDate} — ${range.toDate}`
    : `Through ${range.toDate}`;

  return (
    <div className="bg-white p-6 print:p-4 print:break-after-page border rounded-lg mb-4 print:border-0 print:mb-0">
      {/* Header */}
      <div className="flex justify-between items-start mb-4 border-b pb-3">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Owner Statement</h2>
          <p className="text-xs text-gray-500 mt-0.5">{periodLabel}</p>
        </div>
        <div className="text-right text-sm">
          <p className="font-semibold text-gray-900">Lot {stmt.lot_number}</p>
          {stmt.street_address_1 && <p className="text-gray-500 text-xs">{stmt.street_address_1}</p>}
        </div>
      </div>

      {/* Owner address block */}
      {stmt.owner_names && (
        <div className="mb-4 text-sm">
          <p className="font-medium text-gray-800">{stmt.owner_names}</p>
          {stmt.mailing_address && <p className="text-gray-600">{stmt.mailing_address}</p>}
          {(stmt.mailing_city || stmt.mailing_state) && (
            <p className="text-gray-600">
              {[stmt.mailing_city, stmt.mailing_state, stmt.mailing_postal].filter(Boolean).join(", ")}
            </p>
          )}
          {stmt.owner_email && <p className="text-gray-500 text-xs mt-0.5">{stmt.owner_email}</p>}
        </div>
      )}

      {/* Balance summary */}
      <div className={`mb-4 rounded p-3 text-sm ${stmt.balance > 0.005 ? "bg-red-50 border border-red-200" : stmt.balance < -0.005 ? "bg-green-50 border border-green-200" : "bg-gray-50 border border-gray-200"}`}>
        <span className="font-medium text-gray-700">
          {hasFrom ? "Period Ending Balance: " : "Current Balance: "}
        </span>
        <span className={`font-bold text-lg ${stmt.balance > 0.005 ? "text-red-700" : stmt.balance < -0.005 ? "text-green-700" : "text-gray-700"}`}>
          {fmt(stmt.balance)}
        </span>
        {stmt.balance > 0.005 && <span className="text-xs text-red-600 ml-2">Amount Due</span>}
        {stmt.balance < -0.005 && <span className="text-xs text-green-600 ml-2">Credit on Account</span>}
        {Math.abs(stmt.balance) <= 0.005 && <span className="text-xs text-gray-500 ml-2">Paid in Full</span>}
      </div>

      {/* Ledger */}
      {lines.length === 0 && !hasFrom ? (
        <p className="text-sm text-gray-400">No activity on record.</p>
      ) : (
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 z-10 border-b border-gray-200">
            <tr>
              <th className="text-left py-1.5 text-gray-600 font-medium">Date</th>
              <th className="text-left py-1.5 text-gray-600 font-medium">Description</th>
              <th className="text-right py-1.5 text-gray-600 font-medium">Charge</th>
              <th className="text-right py-1.5 text-gray-600 font-medium">Payment</th>
              <th className="text-right py-1.5 text-gray-600 font-medium">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {hasFrom && (
              <tr className="bg-gray-50">
                <td className="py-1 text-gray-400 pr-3 whitespace-nowrap">{range.fromDate}</td>
                <td className="py-1 text-gray-500 pr-3 italic">Balance Forward</td>
                <td className="py-1 text-right font-mono text-gray-400" />
                <td className="py-1 text-right font-mono text-gray-400" />
                <td className={`py-1 text-right font-mono font-medium ${stmt.opening_balance > 0.005 ? "text-red-700" : stmt.opening_balance < -0.005 ? "text-green-700" : "text-gray-400"}`}>
                  {fmt(stmt.opening_balance)}
                </td>
              </tr>
            )}
            {lines.map((l, i) => (
              <tr key={i}>
                <td className="py-1 text-gray-500 pr-3 whitespace-nowrap">{l.entry_date}</td>
                <td className="py-1 text-gray-700 pr-3">{l.description}</td>
                <td className="py-1 text-right font-mono text-gray-800">
                  {l.charge != null ? fmt(l.charge) : ""}
                </td>
                <td className="py-1 text-right font-mono text-green-700">
                  {l.payment != null ? fmt(l.payment) : ""}
                </td>
                <td className={`py-1 text-right font-mono font-medium ${l.running_balance > 0.005 ? "text-red-700" : l.running_balance < -0.005 ? "text-green-700" : "text-gray-600"}`}>
                  {fmt(l.running_balance)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="mt-4 text-xs text-gray-400 print:mt-2">
        Please remit payment to: HOA — contact your property manager with questions.
      </p>
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function OwnerStatementsScreen() {
  const today = new Date().toISOString().slice(0, 10);
  const [summaries, setSummaries] = useState<LotSummary[]>([]);
  const [statements, setStatements] = useState<LotStatement[]>([]);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState(today);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"select" | "preview">("select");

  const range: DateRange = { fromDate, toDate };

  const reload = useCallback(() => {
    setLoading(true);
    loadLotSummaries(range)
      .then(setSummaries)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromDate, toDate]);

  useEffect(() => { reload(); }, [reload]);

  function toggleAll(checked: boolean) {
    setSummaries((prev) => prev.map((s) => ({ ...s, selected: checked })));
  }

  function toggleLot(lotId: number) {
    setSummaries((prev) => prev.map((s) => s.lot_id === lotId ? { ...s, selected: !s.selected } : s));
  }

  async function handleGenerate() {
    const selected = summaries.filter((s) => s.selected);
    if (selected.length === 0) return;
    setGenerating(true);
    setError(null);
    try {
      const stmts = await Promise.all(selected.map((s) => loadLotStatement(s.lot_id, range)));
      setStatements(stmts);
      setView("preview");
    } catch (e) {
      setError(String(e));
    } finally {
      setGenerating(false);
    }
  }

  const selected = summaries.filter((s) => s.selected);
  const withBalance = summaries.filter((s) => Math.abs(s.balance) > 0.005).length;

  if (loading) return <div className="p-8 text-gray-400 text-sm">Loading…</div>;

  return (
    <PageLayout
      title="Owner Statements"
      subtitle="Generate printable account statements for owners."
      helpId="ownerStatements"
      actions={view === "preview" ? (
        <div className="flex gap-2">
          <button onClick={() => window.print()}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
            Print / Save PDF
          </button>
          <button onClick={() => setView("select")}
            className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
            ← Back
          </button>
        </div>
      ) : undefined}
    >
      <div>
        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {view === "select" && (
          <>
            {/* Date range controls */}
            <div className="flex flex-wrap items-end gap-4 mb-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">From Date <span className="font-normal text-gray-400">(optional — leave blank for full history)</span></label>
                <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
                  className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">To Date</label>
                <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
                  className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              {fromDate && (
                <button onClick={() => setFromDate("")} className="text-xs text-gray-400 hover:text-gray-600 self-end pb-2">
                  Clear From Date
                </button>
              )}
              <div className="self-end pb-0.5 flex gap-2 text-sm text-gray-600 ml-auto">
                <button onClick={() => toggleAll(true)} className="text-blue-600 hover:underline">All</button>
                <span>·</span>
                <button onClick={() => toggleAll(false)} className="text-blue-600 hover:underline">None</button>
                <span>·</span>
                <button onClick={() => setSummaries((prev) => prev.map((s) => ({ ...s, selected: Math.abs(s.balance) > 0.005 })))}
                  className="text-blue-600 hover:underline">
                  With Balance ({withBalance})
                </button>
              </div>
            </div>

            {fromDate && (
              <p className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded px-3 py-1.5 mb-3">
                Period mode: statements will show a "Balance Forward" line for activity before {fromDate}, then period activity through {toDate}. Owners active during the period will appear — including former owners.
              </p>
            )}

            <div className="bg-white border rounded-lg overflow-auto max-h-[calc(100vh-200px)] shadow-sm mb-4">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 z-10 bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2.5">
                      <input type="checkbox" checked={summaries.length > 0 && summaries.every((s) => s.selected)} onChange={(e) => toggleAll(e.target.checked)} />
                    </th>
                    <th className="text-left px-3 py-2.5 font-medium text-gray-600">Lot</th>
                    <th className="text-left px-3 py-2.5 font-medium text-gray-600">
                      {fromDate ? `Owner (${fromDate} – ${toDate})` : "Current Owner"}
                    </th>
                    <th className="text-right px-3 py-2.5 font-medium text-gray-600">
                      {fromDate ? "Period Ending Balance" : "Balance"}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {summaries.map((s) => (
                    <tr key={s.lot_id} className={s.selected ? "" : "opacity-50"}>
                      <td className="px-3 py-2 text-center">
                        <input type="checkbox" checked={s.selected} onChange={() => toggleLot(s.lot_id)} />
                      </td>
                      <td className="px-3 py-2 font-medium text-gray-900">Lot {s.lot_number}</td>
                      <td className="px-3 py-2 text-gray-600">{s.owner_names ?? "—"}</td>
                      <td className={`px-3 py-2 text-right font-mono font-medium ${s.balance > 0.005 ? "text-red-600" : s.balance < -0.005 ? "text-green-700" : "text-gray-400"}`}>
                        {Math.abs(s.balance) <= 0.005 ? "—" : fmt(s.balance)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <button onClick={() => void handleGenerate()} disabled={generating || selected.length === 0}
              className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
              {generating ? "Generating…" : `Generate ${selected.length} Statement${selected.length !== 1 ? "s" : ""}`}
            </button>
          </>
        )}

        {view === "preview" && (
          <div className="space-y-4">
            <p className="text-sm text-gray-500">
              {statements.length} statement{statements.length !== 1 ? "s" : ""} generated
              {fromDate ? ` for period ${fromDate} – ${toDate}` : ""}.
              Click <strong>Print / Save PDF</strong> to open in your browser.
            </p>
            <div id="statements-output" className="space-y-4">
              {statements.map((stmt) => (
                <StatementView key={stmt.lot_id} stmt={stmt} range={range} />
              ))}
            </div>
          </div>
        )}
      </div>
    </PageLayout>
  );
}
