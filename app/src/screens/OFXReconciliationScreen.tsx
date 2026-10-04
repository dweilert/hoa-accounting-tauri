import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { appAlert, appConfirm } from "../components/AppDialogs";
import type { BankAccount } from "../types/bankAccount";

// ── Types ─────────────────────────────────────────────────────────────────────

type OFXRow = {
  id: number;
  transaction_date: string;
  amount: number;
  description: string;
  validation_status: "UNVALIDATED" | "VALIDATED" | "IGNORED";
};

type AppRow = {
  source_type: "INCOME_BATCH" | "DEPOSIT_BATCH" | "BILL_PAYMENT" | "RESERVE_TRANSFER";
  source_id: number;
  date: string;
  amount: number;
  description: string;
  detail: string; // category name, vendor name, etc.
};

type Pair = {
  ofx: OFXRow;
  app: AppRow;
  linkType: "bank_transaction_links" | "deposit_batch";
  amountMatch: boolean;
  dateMatchDays: number;
};

type ScreenData = {
  pairs: Pair[];
  unmatchedOFX: OFXRow[];
  unmatchedApp: AppRow[];
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

function daysDiff(a: string, b: string): number {
  return Math.abs((new Date(a).getTime() - new Date(b).getTime()) / 86400000);
}

function pairStatus(p: Pair): "ok" | "warn" | "error" {
  if (!p.amountMatch) return "error";
  if (p.dateMatchDays > 5) return "warn";
  return "ok";
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadData(bankAccountId: number, yearMonth: string): Promise<ScreenData> {
  const db = await getDb();

  // All OFX transactions for this account + month
  const ofxRows = await db.select<OFXRow[]>(
    `SELECT id, transaction_date, amount, COALESCE(description, '') AS description, validation_status
     FROM bank_transactions
     WHERE bank_account_id = ? AND strftime('%Y-%m', transaction_date) = ?
     ORDER BY transaction_date, id`,
    [bankAccountId, yearMonth]
  );

  // Linked via bank_transaction_links
  type LinkRow = {
    bank_transaction_id: number;
    source_type: string;
    source_id: number;
    app_date: string;
    app_amount: number;
    app_desc: string;
    app_detail: string;
  };

  const linked = await db.select<LinkRow[]>(`
    SELECT
      btl.bank_transaction_id,
      btl.source_type,
      btl.source_id,
      CASE btl.source_type
        WHEN 'INCOME_BATCH' THEN ib.income_date
        WHEN 'BILL_PAYMENT' THEN b.invoice_date
        WHEN 'RESERVE_TRANSFER' THEN rt.transfer_date
        ELSE ''
      END AS app_date,
      CASE btl.source_type
        WHEN 'INCOME_BATCH' THEN ib.amount
        WHEN 'BILL_PAYMENT' THEN -b.amount
        WHEN 'RESERVE_TRANSFER' THEN rt.amount
        ELSE 0
      END AS app_amount,
      CASE btl.source_type
        WHEN 'INCOME_BATCH' THEN COALESCE(ib.description, '')
        WHEN 'BILL_PAYMENT' THEN COALESCE(b.description, '')
        WHEN 'RESERVE_TRANSFER' THEN COALESCE(rt.description, 'Reserve Transfer')
        ELSE ''
      END AS app_desc,
      CASE btl.source_type
        WHEN 'INCOME_BATCH' THEN COALESCE(c.name, '')
        WHEN 'BILL_PAYMENT' THEN COALESCE(v.vendor_name, '')
        WHEN 'RESERVE_TRANSFER' THEN COALESCE(rta.account_name, '') || ' → ' || COALESCE(rtb.account_name, '')
        ELSE ''
      END AS app_detail
    FROM bank_transaction_links btl
    JOIN bank_transactions bt ON bt.id = btl.bank_transaction_id
    LEFT JOIN income_batches ib    ON btl.source_type='INCOME_BATCH'    AND ib.id = btl.source_id
    LEFT JOIN categories c         ON btl.source_type='INCOME_BATCH'    AND c.id = ib.category_id
    LEFT JOIN vendor_bills b       ON btl.source_type='BILL_PAYMENT'    AND b.id = btl.source_id
    LEFT JOIN vendors v            ON btl.source_type='BILL_PAYMENT'    AND v.id = b.vendor_id
    LEFT JOIN reserve_transfers rt ON btl.source_type='RESERVE_TRANSFER' AND rt.id = btl.source_id
    LEFT JOIN bank_accounts rta    ON btl.source_type='RESERVE_TRANSFER' AND rta.id = rt.from_bank_account_id
    LEFT JOIN bank_accounts rtb    ON btl.source_type='RESERVE_TRANSFER' AND rtb.id = rt.to_bank_account_id
    WHERE bt.bank_account_id = ? AND strftime('%Y-%m', bt.transaction_date) = ?
  `, [bankAccountId, yearMonth]);

  // Linked via deposit_batches.bank_transaction_id
  type DepositLinkRow = {
    bank_transaction_id: number;
    deposit_batch_id: number;
    deposit_date: string;
    total_amount: number;
    check_count: number;
    notes: string | null;
  };

  const depositLinks = await db.select<DepositLinkRow[]>(`
    SELECT bt.id AS bank_transaction_id,
           db.id AS deposit_batch_id,
           db.deposit_date,
           db.total_amount,
           db.check_count,
           db.notes
    FROM deposit_batches db
    JOIN bank_transactions bt ON bt.id = db.bank_transaction_id
    WHERE bt.bank_account_id = ? AND strftime('%Y-%m', bt.transaction_date) = ?
  `, [bankAccountId, yearMonth]);

  // Build matched OFX id set and pairs
  const matchedOFXIds = new Set<number>();
  const pairs: Pair[] = [];

  for (const l of linked) {
    const ofx = ofxRows.find((r) => r.id === l.bank_transaction_id);
    if (!ofx) continue;
    matchedOFXIds.add(ofx.id);
    const app: AppRow = {
      source_type: l.source_type as AppRow["source_type"],
      source_id: l.source_id,
      date: l.app_date,
      amount: l.app_amount,
      description: l.app_desc,
      detail: l.app_detail,
    };
    pairs.push({
      ofx,
      app,
      linkType: "bank_transaction_links",
      amountMatch: Math.abs(ofx.amount - app.amount) < 0.01,
      dateMatchDays: daysDiff(ofx.transaction_date, app.date),
    });
  }

  for (const d of depositLinks) {
    const ofx = ofxRows.find((r) => r.id === d.bank_transaction_id);
    if (!ofx) continue;
    matchedOFXIds.add(ofx.id);
    const app: AppRow = {
      source_type: "DEPOSIT_BATCH",
      source_id: d.deposit_batch_id,
      date: d.deposit_date,
      amount: d.total_amount,
      description: `Deposit Batch #${d.deposit_batch_id}`,
      detail: `${d.check_count} check${d.check_count !== 1 ? "s" : ""}${d.notes ? ` — ${d.notes}` : ""}`,
    };
    pairs.push({
      ofx,
      app,
      linkType: "deposit_batch",
      amountMatch: Math.abs(ofx.amount - app.amount) < 0.01,
      dateMatchDays: daysDiff(ofx.transaction_date, app.date),
    });
  }

  // Sort pairs by OFX date
  pairs.sort((a, b) => a.ofx.transaction_date.localeCompare(b.ofx.transaction_date));

  // Unmatched OFX
  const unmatchedOFX = ofxRows.filter((r) => !matchedOFXIds.has(r.id));

  // Unmatched app transactions for this account + month
  // income_batches with no link
  type UnmatchedIB = { id: number; income_date: string; amount: number; description: string | null; category_name: string | null };
  const unmatchedIB = await db.select<UnmatchedIB[]>(`
    SELECT ib.id, ib.income_date, ib.amount,
           COALESCE(ib.description, '') AS description,
           c.name AS category_name
    FROM income_batches ib
    LEFT JOIN categories c ON c.id = ib.category_id
    WHERE ib.bank_account_id = ?
      AND strftime('%Y-%m', ib.income_date) = ?
      AND ib.id NOT IN (SELECT source_id FROM bank_transaction_links WHERE source_type = 'INCOME_BATCH')
    ORDER BY ib.income_date
  `, [bankAccountId, yearMonth]);

  // deposit_batches with no bank_transaction_id
  type UnmatchedDB = { id: number; deposit_date: string; total_amount: number; check_count: number; notes: string | null };
  const unmatchedDB = await db.select<UnmatchedDB[]>(`
    SELECT id, deposit_date, total_amount, check_count, notes
    FROM deposit_batches
    WHERE bank_account_id = ?
      AND strftime('%Y-%m', deposit_date) = ?
      AND bank_transaction_id IS NULL
      AND status = 'POSTED'
    ORDER BY deposit_date
  `, [bankAccountId, yearMonth]);

  const unmatchedApp: AppRow[] = [
    ...unmatchedIB.map((r) => ({
      source_type: "INCOME_BATCH" as const,
      source_id: r.id,
      date: r.income_date,
      amount: r.amount,
      description: r.description ?? "",
      detail: r.category_name ?? "",
    })),
    ...unmatchedDB.map((r) => ({
      source_type: "DEPOSIT_BATCH" as const,
      source_id: r.id,
      date: r.deposit_date,
      amount: r.total_amount,
      description: `Deposit Batch #${r.id}`,
      detail: `${r.check_count} check${r.check_count !== 1 ? "s" : ""}${r.notes ? ` — ${r.notes}` : ""}`,
    })),
  ].sort((a, b) => a.date.localeCompare(b.date));

  return { pairs, unmatchedOFX, unmatchedApp };
}

// ── Link / unlink actions ─────────────────────────────────────────────────────

async function unlinkPair(pair: Pair): Promise<void> {
  const db = await getDb();
  if (pair.linkType === "bank_transaction_links") {
    await db.execute(
      "DELETE FROM bank_transaction_links WHERE bank_transaction_id = ? AND source_type = ? AND source_id = ?",
      [pair.ofx.id, pair.app.source_type, pair.app.source_id]
    );
  } else {
    // deposit_batch link
    await db.execute(
      "UPDATE deposit_batches SET bank_transaction_id = NULL WHERE id = ?",
      [pair.app.source_id]
    );
  }
  // Revert OFX back to UNVALIDATED
  await db.execute(
    "UPDATE bank_transactions SET validation_status = 'UNVALIDATED' WHERE id = ?",
    [pair.ofx.id]
  );
}

async function linkOFXToApp(ofxId: number, app: AppRow): Promise<void> {
  const db = await getDb();
  if (app.source_type === "DEPOSIT_BATCH") {
    await db.execute(
      "UPDATE deposit_batches SET bank_transaction_id = ? WHERE id = ?",
      [ofxId, app.source_id]
    );
  } else {
    await db.execute(
      `INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id)
       VALUES (?, ?, ?)`,
      [ofxId, app.source_type, app.source_id]
    );
  }
  await db.execute(
    "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
    [ofxId]
  );
}

// ── Row components ────────────────────────────────────────────────────────────

function OFXCell({ row }: { row: OFXRow }) {
  return (
    <div>
      <div className="text-xs text-gray-500">{row.transaction_date}</div>
      <div className="font-medium text-gray-800 text-sm truncate max-w-[220px]" title={row.description}>
        {row.description || "(no description)"}
      </div>
      <div className={`text-sm font-mono font-semibold ${row.amount < 0 ? "text-red-600" : "text-green-700"}`}>
        {fmt(row.amount)}
      </div>
    </div>
  );
}

function AppCell({ row }: { row: AppRow }) {
  const label: Record<AppRow["source_type"], string> = {
    INCOME_BATCH: "Income",
    DEPOSIT_BATCH: "Deposit",
    BILL_PAYMENT: "Bill",
    RESERVE_TRANSFER: "Transfer",
  };
  return (
    <div>
      <div className="text-xs text-gray-500">{row.date} · <span className="font-medium">{label[row.source_type]}</span></div>
      <div className="font-medium text-gray-800 text-sm truncate max-w-[220px]" title={row.description}>
        {row.description || "(no description)"}
      </div>
      <div className="text-xs text-gray-500 truncate max-w-[220px]">{row.detail}</div>
      <div className={`text-sm font-mono font-semibold ${row.amount < 0 ? "text-red-600" : "text-green-700"}`}>
        {fmt(row.amount)}
      </div>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function OFXReconciliationScreen() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [yearMonth, setYearMonth] = useState<string>(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  });
  const [data, setData] = useState<ScreenData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Arm-to-link: user clicks an unmatched OFX row, then clicks an unmatched app row to link
  const [armedOFX, setArmedOFX] = useState<OFXRow | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await loadData(accountId, yearMonth);
      setData(d);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [accountId, yearMonth]);

  useEffect(() => {
    listBankAccounts(true).then((accts) => {
      setAccounts(accts);
      if (accts.length > 0) setAccountId(accts[0]!.id);
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (accountId) void load();
  }, [accountId, yearMonth, load]);

  async function handleUnlink(pair: Pair) {
    if (!await appConfirm(`Unlink this pair?\n\n${pair.ofx.description} / ${fmt(pair.ofx.amount)}\n↔ ${pair.app.description}\n\nOFX transaction will revert to UNVALIDATED.`)) return;
    try {
      await unlinkPair(pair);
      await load();
    } catch (e) {
      await appAlert(String(e));
    }
  }

  async function handleLink(ofx: OFXRow, app: AppRow) {
    // Check if either side is already linked
    try {
      await linkOFXToApp(ofx.id, app);
      setArmedOFX(null);
      await load();
    } catch (e) {
      await appAlert(String(e));
    }
  }

  function handleArmOFX(row: OFXRow) {
    setArmedOFX((prev) => prev?.id === row.id ? null : row);
  }

  const totalOFX = (data?.pairs.length ?? 0) + (data?.unmatchedOFX.length ?? 0);
  const totalApp = (data?.pairs.length ?? 0) + (data?.unmatchedApp.length ?? 0);
  const matchedCount = data?.pairs.length ?? 0;

  // Generate month options: 18 months back from now
  const monthOptions: string[] = [];
  const today = new Date();
  for (let i = 0; i < 18; i++) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    monthOptions.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }

  return (
    <PageLayout
      title="OFX Reconciliation"
      subtitle="Match every OFX bank transaction to an app transaction."
      helpId="ofxReconciliation"
    >
      <div>
        {/* Controls */}
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <select
            value={accountId ?? ""}
            onChange={(e) => { setAccountId(Number(e.target.value)); setArmedOFX(null); }}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
          <select
            value={yearMonth}
            onChange={(e) => { setYearMonth(e.target.value); setArmedOFX(null); }}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {monthOptions.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          {data && (
            <span className="text-xs text-gray-500">
              {matchedCount}/{totalOFX} OFX matched · {data.unmatchedOFX.length} unmatched OFX · {data.unmatchedApp.length} unmatched app
            </span>
          )}
          {armedOFX && (
            <span
              className="text-xs px-2 py-1 rounded font-medium cursor-pointer"
              style={{ backgroundColor: "#fef3c7", color: "#92400e" }}
              onClick={() => setArmedOFX(null)}
            >
              Armed: {fmt(armedOFX.amount)} on {armedOFX.transaction_date} — click an app row to link · click here to cancel
            </span>
          )}
        </div>

        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}
        {loading && <p className="text-sm text-gray-400">Loading…</p>}

        {data && !loading && (
          <div className="space-y-6">

            {/* ── Matched pairs ── */}
            {data.pairs.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
                  Matched ({data.pairs.length})
                </h2>
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-[42%]">OFX Transaction</th>
                        <th className="px-2 py-2 text-center text-xs font-medium text-gray-600 w-[6%]"></th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-[42%]">App Transaction</th>
                        <th className="px-2 py-2 w-[10%]"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {data.pairs.map((p, i) => {
                        const status = pairStatus(p);
                        const rowBg = status === "ok" ? "" : status === "warn" ? "bg-amber-50" : "bg-red-50";
                        const connectorColor = status === "ok" ? "#16a34a" : status === "warn" ? "#d97706" : "#dc2626";
                        return (
                          <tr key={i} className={`hover:bg-gray-50 ${rowBg}`}>
                            <td className="px-4 py-3"><OFXCell row={p.ofx} /></td>
                            <td className="px-2 py-3 text-center">
                              <div className="flex flex-col items-center gap-0.5">
                                <div className="w-8 border-t-2" style={{ borderColor: connectorColor }} />
                                <span className="text-xs font-bold" style={{ color: connectorColor }}>
                                  {status === "ok" ? "✓" : status === "warn" ? "!" : "✗"}
                                </span>
                                <div className="w-8 border-t-2" style={{ borderColor: connectorColor }} />
                              </div>
                            </td>
                            <td className="px-4 py-3"><AppCell row={p.app} /></td>
                            <td className="px-2 py-3 text-right">
                              <button
                                onClick={() => void handleUnlink(p)}
                                className="text-xs text-gray-400 hover:text-red-600 transition-colors"
                                title="Unlink this pair"
                              >
                                Unlink
                              </button>
                              {(status === "warn" || status === "error") && (
                                <div className="text-xs text-amber-600 mt-0.5">
                                  {!p.amountMatch && `Δ${fmt(Math.abs(p.ofx.amount - p.app.amount))}`}
                                  {p.amountMatch && `${Math.round(p.dateMatchDays)}d gap`}
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* ── Unmatched section (two columns side by side) ── */}
            {(data.unmatchedOFX.length > 0 || data.unmatchedApp.length > 0) && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-red-500 mb-2">
                  Unmatched — click OFX row to arm, then click App row to link
                </h2>
                <div className="border border-red-200 rounded-lg overflow-hidden">
                  <div className="grid grid-cols-2 divide-x divide-red-200">

                    {/* Left: unmatched OFX */}
                    <div>
                      <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-xs font-semibold text-red-700">
                        OFX — No App Transaction ({data.unmatchedOFX.length})
                      </div>
                      {data.unmatchedOFX.length === 0 ? (
                        <div className="px-4 py-6 text-center text-xs text-gray-400">All OFX matched ✓</div>
                      ) : (
                        <ul className="divide-y divide-red-100">
                          {data.unmatchedOFX.map((row) => {
                            const armed = armedOFX?.id === row.id;
                            return (
                              <li
                                key={row.id}
                                onClick={() => handleArmOFX(row)}
                                className={`px-4 py-3 cursor-pointer transition-colors ${
                                  armed
                                    ? "bg-amber-100 ring-1 ring-amber-400"
                                    : "hover:bg-red-50"
                                }`}
                              >
                                <OFXCell row={row} />
                                {armed && (
                                  <div className="mt-1 text-xs text-amber-700 font-medium">
                                    Armed — click an app row →
                                  </div>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>

                    {/* Right: unmatched App */}
                    <div>
                      <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-xs font-semibold text-red-700">
                        App — No OFX Transaction ({data.unmatchedApp.length})
                      </div>
                      {data.unmatchedApp.length === 0 ? (
                        <div className="px-4 py-6 text-center text-xs text-gray-400">All app transactions matched ✓</div>
                      ) : (
                        <ul className="divide-y divide-red-100">
                          {data.unmatchedApp.map((row, i) => {
                            const canLink = armedOFX !== null;
                            return (
                              <li
                                key={i}
                                onClick={() => {
                                  if (armedOFX) void handleLink(armedOFX, row);
                                }}
                                className={`px-4 py-3 transition-colors ${
                                  canLink
                                    ? "cursor-pointer bg-amber-50 hover:bg-amber-100 ring-1 ring-amber-300"
                                    : "hover:bg-red-50"
                                }`}
                              >
                                <AppCell row={row} />
                                {canLink && (
                                  <div className="mt-1 text-xs text-amber-700 font-medium">
                                    ← Click to link with {fmt(armedOFX.amount)}
                                  </div>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {data.pairs.length > 0 && data.unmatchedOFX.length === 0 && data.unmatchedApp.length === 0 && (
              <div className="text-center py-4 text-sm text-green-700 font-medium">
                All {data.pairs.length} transactions matched ✓
              </div>
            )}

            {totalOFX === 0 && totalApp === 0 && (
              <div className="text-center py-10 text-sm text-gray-400">
                No OFX transactions for {yearMonth}.
              </div>
            )}
          </div>
        )}
      </div>
    </PageLayout>
  );
}
