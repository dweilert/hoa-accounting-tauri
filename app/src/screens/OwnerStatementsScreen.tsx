import { useEffect, useState } from "react";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type LotStatement = {
  lot_id: number;
  lot_number: string;
  street_address_1: string | null;
  owner_name: string | null;
  owner_email: string | null;
  mailing_address: string | null;
  mailing_city: string | null;
  mailing_state: string | null;
  mailing_postal: string | null;
  charges: LedgerLine[];
  payments: LedgerLine[];
  balance: number;
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
  owner_name: string | null;
  balance: number;
  selected: boolean;
};

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

// ── DB helpers ────────────────────────────────────────────────────────────────

async function loadLotSummaries(): Promise<LotSummary[]> {
  const db = await getDb();
  const rows = await db.select<Omit<LotSummary, "selected">[]>(`
    SELECT l.id AS lot_id, l.lot_number,
           o.display_name AS owner_name,
           COALESCE(
             (SELECT SUM(a.amount) FROM assessments a WHERE a.lot_id=l.id AND a.status IN ('OPEN','PARTIAL')), 0
           ) -
           COALESCE(
             (SELECT SUM(p.amount) FROM payments p
              JOIN deposit_batches d ON p.deposit_batch_id=d.id
              WHERE p.lot_id=l.id AND d.status='POSTED'), 0
           ) AS balance
    FROM lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id=l.id AND lo.end_date IS NULL AND lo.is_primary_contact=1
    LEFT JOIN owners o ON lo.owner_id=o.id
    WHERE l.active_flag=1
    ORDER BY l.lot_number
  `);
  return rows.map((r) => ({ ...r, selected: true }));
}

async function loadLotStatement(lotId: number): Promise<LotStatement> {
  const db = await getDb();

  const [lotRows, chargeRows, paymentRows] = await Promise.all([
    db.select<{ lot_number: string; street_address_1: string | null; owner_name: string | null; owner_email: string | null; mailing_address: string | null; mailing_city: string | null; mailing_state: string | null; mailing_postal: string | null }[]>(`
      SELECT l.lot_number, l.street_address_1,
             o.display_name AS owner_name, o.email AS owner_email,
             o.mailing_address_1 AS mailing_address, o.city AS mailing_city,
             o.state AS mailing_state, o.postal_code AS mailing_postal
      FROM lots l
      LEFT JOIN lot_ownership lo ON lo.lot_id=l.id AND lo.end_date IS NULL AND lo.is_primary_contact=1
      LEFT JOIN owners o ON lo.owner_id=o.id
      WHERE l.id=? LIMIT 1
    `, [lotId]),

    db.select<{ entry_date: string; description: string; amount: number }[]>(`
      SELECT a.assessment_date AS entry_date,
             COALESCE(a.description, c.name, 'Assessment') AS description,
             a.amount
      FROM assessments a
      LEFT JOIN categories c ON c.id=a.category_id
      WHERE a.lot_id=? AND a.status NOT IN ('VOID','WRITTEN_OFF')
      ORDER BY a.assessment_date
    `, [lotId]),

    db.select<{ entry_date: string; description: string; amount: number }[]>(`
      SELECT p.payment_date AS entry_date,
             COALESCE('Payment' || CASE WHEN p.check_number IS NOT NULL THEN ' #'||p.check_number ELSE '' END, 'Payment') AS description,
             p.amount
      FROM payments p
      JOIN deposit_batches d ON p.deposit_batch_id=d.id AND d.status='POSTED'
      WHERE p.lot_id=?
      ORDER BY p.payment_date
    `, [lotId]),
  ]);

  const lot = lotRows[0];
  if (!lot) throw new Error(`Lot ${lotId} not found`);

  // Build combined ledger sorted by date
  type RawLine = { entry_date: string; description: string; charge?: number; payment?: number };
  const combined: RawLine[] = [
    ...chargeRows.map((r) => ({ entry_date: r.entry_date, description: r.description, charge: r.amount })),
    ...paymentRows.map((r) => ({ entry_date: r.entry_date, description: r.description, payment: r.amount })),
  ].sort((a, b) => a.entry_date.localeCompare(b.entry_date));

  let running = 0;
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
    owner_name: lot.owner_name,
    owner_email: lot.owner_email,
    mailing_address: lot.mailing_address,
    mailing_city: lot.mailing_city,
    mailing_state: lot.mailing_state,
    mailing_postal: lot.mailing_postal,
    charges: lines.filter((l) => l.charge !== null),
    payments: lines.filter((l) => l.payment !== null),
    balance: running,
    // Return all lines, not just charges
  };
}

// ── Statement component (used for print) ─────────────────────────────────────

function StatementView({ stmt, asOfDate }: { stmt: LotStatement; asOfDate: string }) {
  // Rebuild full ledger from charges+payments combined
  type RawLine = { entry_date: string; description: string; charge?: number; payment?: number };
  const combined: RawLine[] = [];
  stmt.charges.forEach((l) => l.charge !== null && combined.push({ entry_date: l.entry_date, description: l.description, charge: l.charge }));
  stmt.payments.forEach((l) => l.payment !== null && combined.push({ entry_date: l.entry_date, description: l.description, payment: l.payment }));
  combined.sort((a, b) => a.entry_date.localeCompare(b.entry_date));

  let running = 0;
  const lines = combined.map((r) => {
    running += (r.charge ?? 0) - (r.payment ?? 0);
    return { ...r, running_balance: running };
  });

  return (
    <div className="bg-white p-6 print:p-4 print:break-after-page border rounded-lg mb-4 print:border-0 print:mb-0">
      {/* Header */}
      <div className="flex justify-between items-start mb-4 border-b pb-3">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Owner Statement</h2>
          <p className="text-xs text-gray-500 mt-0.5">As of {asOfDate}</p>
        </div>
        <div className="text-right text-sm">
          <p className="font-semibold text-gray-900">Lot {stmt.lot_number}</p>
          {stmt.street_address_1 && <p className="text-gray-500 text-xs">{stmt.street_address_1}</p>}
        </div>
      </div>

      {/* Owner address block */}
      {stmt.owner_name && (
        <div className="mb-4 text-sm">
          <p className="font-medium text-gray-800">{stmt.owner_name}</p>
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
      <div className={`mb-4 rounded p-3 text-sm ${stmt.balance > 0 ? "bg-red-50 border border-red-200" : stmt.balance < 0 ? "bg-green-50 border border-green-200" : "bg-gray-50 border border-gray-200"}`}>
        <span className="font-medium text-gray-700">Current Balance: </span>
        <span className={`font-bold text-lg ${stmt.balance > 0 ? "text-red-700" : stmt.balance < 0 ? "text-green-700" : "text-gray-700"}`}>
          {fmt(stmt.balance)}
        </span>
        {stmt.balance > 0 && <span className="text-xs text-red-600 ml-2">Amount Due</span>}
        {stmt.balance < 0 && <span className="text-xs text-green-600 ml-2">Credit on Account</span>}
        {stmt.balance === 0 && <span className="text-xs text-gray-500 ml-2">Paid in Full</span>}
      </div>

      {/* Ledger */}
      {lines.length === 0 ? (
        <p className="text-sm text-gray-400">No activity on record.</p>
      ) : (
        <table className="min-w-full text-xs">
          <thead className="border-b border-gray-200">
            <tr>
              <th className="text-left py-1.5 text-gray-600 font-medium">Date</th>
              <th className="text-left py-1.5 text-gray-600 font-medium">Description</th>
              <th className="text-right py-1.5 text-gray-600 font-medium">Charge</th>
              <th className="text-right py-1.5 text-gray-600 font-medium">Payment</th>
              <th className="text-right py-1.5 text-gray-600 font-medium">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
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
                <td className={`py-1 text-right font-mono font-medium ${l.running_balance > 0 ? "text-red-700" : l.running_balance < 0 ? "text-green-700" : "text-gray-600"}`}>
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
  const [asOfDate, setAsOfDate] = useState(today);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"select" | "preview">("select");

  useEffect(() => {
    loadLotSummaries()
      .then(setSummaries)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

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
      const stmts = await Promise.all(selected.map((s) => loadLotStatement(s.lot_id)));
      setStatements(stmts);
      setView("preview");
    } catch (e) {
      setError(String(e));
    } finally {
      setGenerating(false);
    }
  }

  const selected = summaries.filter((s) => s.selected);
  const withBalance = summaries.filter((s) => s.balance !== 0).length;

  if (loading) return <div className="p-8 text-gray-400 text-sm">Loading…</div>;

  return (
    <div className="p-6 max-w-5xl">
      {/* Print-only: no header chrome */}
      {view === "preview" && (
        <div className="hidden print:block">
          {statements.map((stmt) => (
            <StatementView key={stmt.lot_id} stmt={stmt} asOfDate={asOfDate} />
          ))}
        </div>
      )}

      {/* Screen UI — hidden when printing */}
      <div className="print:hidden">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Owner Statements</h1>
            <p className="text-sm text-gray-500 mt-1">
              Generate printable account statements for owners. Print to PDF from your browser.
            </p>
          </div>
          {view === "preview" && (
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
          )}
        </div>

        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {view === "select" && (
          <>
            <div className="flex items-center gap-4 mb-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Statement As-Of Date</label>
                <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
                  className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="self-end pb-0.5 flex gap-2 text-sm text-gray-600">
                <button onClick={() => toggleAll(true)} className="text-blue-600 hover:underline">All</button>
                <span>·</span>
                <button onClick={() => toggleAll(false)} className="text-blue-600 hover:underline">None</button>
                <span>·</span>
                <button onClick={() => setSummaries((prev) => prev.map((s) => ({ ...s, selected: s.balance !== 0 })))}
                  className="text-blue-600 hover:underline">
                  With Balance ({withBalance})
                </button>
              </div>
            </div>

            <div className="bg-white border rounded-lg overflow-hidden shadow-sm mb-4">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2.5">
                      <input type="checkbox" checked={summaries.every((s) => s.selected)} onChange={(e) => toggleAll(e.target.checked)} />
                    </th>
                    <th className="text-left px-3 py-2.5 font-medium text-gray-600">Lot</th>
                    <th className="text-left px-3 py-2.5 font-medium text-gray-600">Owner</th>
                    <th className="text-right px-3 py-2.5 font-medium text-gray-600">Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {summaries.map((s) => (
                    <tr key={s.lot_id} className={s.selected ? "" : "opacity-50"}>
                      <td className="px-3 py-2 text-center">
                        <input type="checkbox" checked={s.selected} onChange={() => toggleLot(s.lot_id)} />
                      </td>
                      <td className="px-3 py-2 font-medium text-gray-900">Lot {s.lot_number}</td>
                      <td className="px-3 py-2 text-gray-600">{s.owner_name ?? "—"}</td>
                      <td className={`px-3 py-2 text-right font-mono font-medium ${s.balance > 0 ? "text-red-600" : s.balance < 0 ? "text-green-700" : "text-gray-400"}`}>
                        {s.balance === 0 ? "—" : fmt(s.balance)}
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
              {statements.length} statement{statements.length !== 1 ? "s" : ""} generated.
              Click <strong>Print / Save PDF</strong> to open your browser's print dialog —
              choose "Save as PDF" to create a file you can email or upload to S3.
            </p>
            {statements.map((stmt) => (
              <StatementView key={stmt.lot_id} stmt={stmt} asOfDate={asOfDate} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
