import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDb, getConfiguredDbPath } from "../lib/db";
import { listActiveAnnouncements, type Announcement } from "../repositories/announcementRepo";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type DashStats = {
  activeLots: number;
  openArTotal: number;
  openArCount: number;
  bankAccounts: { account_name: string; fund_code: string; current_balance: number }[];
  recentTxns: { txn_date: string; description: string; amount: number; account_name: string | null }[];
};

async function loadStats(): Promise<DashStats> {
  const db = await getDb();

  const [lotRows, arRows, bankRows, txnRows] = await Promise.all([
    db.select<[{ n: number }]>("SELECT COUNT(*) as n FROM lots WHERE active_flag = 1"),
    db.select<[{ total: number; cnt: number }]>(
      "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as cnt FROM assessments WHERE status IN ('OPEN','PARTIAL')"
    ),
    db.select<{ account_name: string; fund_code: string; current_balance: number }[]>(`
      SELECT b.account_name, b.fund_code,
             COALESCE(b.opening_balance, 0)
             + COALESCE((SELECT SUM(p.amount) FROM payments p
                         JOIN deposit_batches d ON d.id = p.deposit_batch_id
                         WHERE d.bank_account_id = b.id), 0)
             + COALESCE((SELECT SUM(ib.amount) FROM income_batches ib
                         WHERE ib.bank_account_id = b.id), 0)
             - COALESCE((SELECT SUM(bp.amount) FROM bill_payments bp
                         WHERE bp.bank_account_id = b.id), 0)
             AS current_balance
      FROM bank_accounts b
      WHERE b.active_flag = 1
      ORDER BY b.fund_code, b.account_name
    `),
    db.select<{ txn_date: string; description: string; amount: number; account_name: string | null }[]>(`
      SELECT txn_date, description, amount, account_name FROM (
        SELECT p.payment_date AS txn_date,
               COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
               p.amount, b.account_name
        FROM payments p
        JOIN lots l ON l.id = p.lot_id
        LEFT JOIN owners o ON o.id = p.owner_id
        LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id
        LEFT JOIN bank_accounts b ON b.id = d.bank_account_id
        UNION ALL
        SELECT bp.payment_date, 'Bill — ' || v.vendor_name, -bp.amount, b.account_name
        FROM bill_payments bp
        JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
        JOIN vendors v ON v.id = vb.vendor_id
        JOIN bank_accounts b ON b.id = bp.bank_account_id
        UNION ALL
        SELECT ib.income_date, COALESCE(ib.description, c.name), ib.amount, b.account_name
        FROM income_batches ib
        JOIN categories c ON c.id = ib.category_id
        JOIN bank_accounts b ON b.id = ib.bank_account_id
      ) ORDER BY txn_date DESC LIMIT 8
    `),
  ]);

  return {
    activeLots: lotRows[0]?.n ?? 0,
    openArTotal: arRows[0]?.total ?? 0,
    openArCount: arRows[0]?.cnt ?? 0,
    bankAccounts: bankRows,
    recentTxns: txnRows,
  };
}

async function loadOnboardingState(): Promise<{ obEntered: boolean; dismissed: boolean }> {
  const db = await getDb();
  const [obRows, settingRows] = await Promise.all([
    db.select<[{ n: number }]>("SELECT COUNT(*) as n FROM opening_balances"),
    db.select<{ value: string }[]>(
      "SELECT value FROM app_settings WHERE key = 'dismiss_onboarding_ob'"
    ),
  ]);
  return {
    obEntered: (obRows[0]?.n ?? 0) > 0,
    dismissed: settingRows.length > 0,
  };
}

async function dismissOnboardingAlert(): Promise<void> {
  const db = await getDb();
  await db.execute(
    "INSERT INTO app_settings (key, value) VALUES ('dismiss_onboarding_ob', '1') ON CONFLICT(key) DO UPDATE SET value = '1'"
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, to }: { label: string; value: string; sub?: string; to?: string }) {
  const inner = (
    <div className="bg-white border rounded-lg p-4 space-y-1">
      <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  );
  return to ? <Link to={to} className="block hover:shadow-md transition-shadow">{inner}</Link> : inner;
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

const BANNER_STYLE: Record<string, string> = {
  info:    "bg-blue-50 border-blue-200 text-blue-900",
  warning: "bg-amber-50 border-amber-200 text-amber-900",
  urgent:  "bg-red-50 border-red-200 text-red-900",
};

export function Dashboard() {
  const [stats, setStats] = useState<DashStats | null>(null);
  const [onboarding, setOnboarding] = useState<{ obEntered: boolean; dismissed: boolean } | null>(null);
  const [banners, setBanners] = useState<Announcement[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dbDiag, setDbDiag] = useState<string>("checking…");

  useEffect(() => {
    const path = getConfiguredDbPath();
    getDb()
      .then((db) => db.select<[{n:number}]>("SELECT COUNT(*) as n FROM lots"))
      .then(([r]) => setDbDiag(`✓ connected | path: ${path} | lots: ${r?.n ?? 0}`))
      .catch((e: unknown) => setDbDiag(`✗ ERROR: ${String(e)} | path: ${path}`));
  }, []);

  useEffect(() => {
    Promise.all([loadStats(), loadOnboardingState(), listActiveAnnouncements()])
      .then(([s, o, b]) => { setStats(s); setOnboarding(o); setBanners(b); })
      .catch((e) => setError(String(e)));
  }, []);

  async function handleDismiss() {
    await dismissOnboardingAlert();
    setOnboarding((o) => o ? { ...o, dismissed: true } : o);
  }

  const showObAlert = onboarding && !onboarding.obEntered && !onboarding.dismissed;

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">HOA Accounting overview.</p>
      </div>

      {/* TEMP DB DIAGNOSTIC — remove once confirmed working */}
      <div className="font-mono text-xs p-2 bg-black text-green-400 rounded break-all">
        {dbDiag}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Announcement banners */}
      {banners.map((b) => (
        <div key={b.id} className={`border rounded-lg px-4 py-3 ${BANNER_STYLE[b.severity]}`}>
          <p className="text-sm font-medium">{b.message}</p>
        </div>
      ))}

      {/* Onboarding alert */}
      {showObAlert && (
        <div className="flex items-start justify-between bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          <div>
            <p className="text-sm font-semibold text-amber-800">Opening balances not entered</p>
            <p className="text-xs text-amber-700 mt-0.5">
              Your books may be inaccurate until you record starting balances for bank accounts and outstanding lots.{" "}
              <Link to="/opening-balances" className="underline font-medium">Enter Opening Balances →</Link>
            </p>
          </div>
          <button
            onClick={() => void handleDismiss()}
            className="ml-4 text-xs text-amber-600 hover:text-amber-800 whitespace-nowrap"
          >
            Don't show again
          </button>
        </div>
      )}

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard
            label="Active Lots"
            value={String(stats.activeLots)}
            to="/lots"
          />
          <StatCard
            label="Outstanding AR"
            value={fmt(stats.openArTotal)}
            sub={`${stats.openArCount} open charge${stats.openArCount !== 1 ? "s" : ""}`}
            to="/ar"
          />
          {stats.bankAccounts.slice(0, 2).map((a) => (
            <StatCard
              key={a.account_name}
              label={a.account_name}
              value={fmt(a.current_balance)}
              sub={a.fund_code === "RESERVE" ? "Reserve Fund" : "Operating"}
              to="/bank/accounts"
            />
          ))}
        </div>
      )}

      {/* Bank accounts overflow (if more than 2) */}
      {stats && stats.bankAccounts.length > 2 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {stats.bankAccounts.slice(2).map((a) => (
            <StatCard
              key={a.account_name}
              label={a.account_name}
              value={fmt(a.current_balance)}
              sub={a.fund_code === "RESERVE" ? "Reserve Fund" : "Operating"}
              to="/bank/accounts"
            />
          ))}
        </div>
      )}

      {/* Recent activity */}
      {stats && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-gray-800">Recent Activity</h2>
            <Link to="/reports" className="text-xs text-blue-600 hover:underline">View all →</Link>
          </div>
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {stats.recentTxns.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-400 text-sm">
                      No transactions yet.
                    </td>
                  </tr>
                )}
                {stats.recentTxns.map((r, i) => (
                  <tr key={i}>
                    <td className="px-4 py-2 text-gray-500 text-xs whitespace-nowrap">{r.txn_date}</td>
                    <td className="px-4 py-2 text-gray-700 text-xs">{r.description}</td>
                    <td className="px-4 py-2 text-gray-400 text-xs">{r.account_name ?? "—"}</td>
                    <td className={`px-4 py-2 text-right font-mono text-xs ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                      {fmt(r.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
