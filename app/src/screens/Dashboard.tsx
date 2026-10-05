import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getDb } from "../lib/db";
import { readConfig } from "../lib/config";
import { listActiveAnnouncements, type Announcement } from "../repositories/announcementRepo";
import { PageLayout } from "../components/PageLayout";
import { useTableSort } from "../lib/useTableSort";
import { SortableTh } from "../components/SortableTh";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// Map old Flask URLs → Tauri routes
const ROUTE_MAP: Record<string, string> = {
  "/dues-billing": "/billing/dues",
  "/deposits": "/deposits",
  "/deposit": "/deposits",
  "/vendor-bills": "/bills",
  "/vendor-bills/new": "/bills",
  "/income": "/bank/pending",
  "/income/new": "/bank/pending",
  "/reconciliations": "/bank/reconciliations",
  "/reconciliations/new": "/bank/reconciliations",
  "/assessments/bill": "/assessments",
  "/ar/lots": "/ar",
  "/ar": "/ar",
  "/late-fees": "/billing/late-fees",
  "/batch-pdf": "/reports",
  "/resale-fee": "/billing/resale-fee",
  "/ledger/transactions": "/transactions",
  "/ledger/by-account": "/ledger/by-account",
  "/journal-entry-new": "/transactions",
  "/journal-entries": "/transactions",
  // Flask admin paths → Tauri equivalents
  "/admin/audit-log": "/audit-log",
  "/admin/transaction-rules": "/admin/transaction-rules",
  "/admin/database": "#",
  "/manage/edit-records": "/transactions",
  // Flask bank paths
  "/bank-transactions/pending": "/bank/pending",
  "/bank-import/upload": "/bank/import",
  "/ofx-inbox": "/bank/ofx-inbox",
  // Reserve
  "/reserve-study": "/reserve",
  "/reserve-transfers": "/reserve/transfers",
};

function resolveRoute(url: string | null): string {
  if (!url) return "#";
  return ROUTE_MAP[url] ?? url;
}

// ── DB card types ─────────────────────────────────────────────────────────────

type DashCard = {
  id: number;
  title: string;
  description: string | null;
  card_type: "NAV" | "REPORT" | "COMMENT" | "FINANCIAL" | "SECTION";
  target_url: string | null;
  report_name: string | null;
  color: string;
  is_active: number;
  position: number;
};

async function loadDashboardCards(): Promise<DashCard[]> {
  const db = await getDb();
  return db.select<DashCard[]>(`
    SELECT dc.id, dc.title, dc.description, dc.card_type, dc.target_url,
           dc.report_name, dc.color, dc.is_active, dl.position
    FROM dashboard_cards dc
    JOIN dashboard_layout dl ON dl.card_id = dc.id
    WHERE dc.is_active = 1
    ORDER BY dl.position
  `);
}

// ── Financial tile data ───────────────────────────────────────────────────────

type BankTile = { account_name: string; fund_code: string; current_balance: number };
type LastRecon = { bank_account: string; end_date: string; ending_balance: number } | null;
type BudgetLine = { category_name: string; budgeted: number; actual: number };

async function loadBankTiles(): Promise<BankTile[]> {
  const db = await getDb();
  return db.select<BankTile[]>(`
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
    FROM bank_accounts b WHERE b.active_flag = 1
    ORDER BY b.fund_code, b.account_name
  `);
}

async function loadLastRecon(): Promise<LastRecon> {
  const db = await getDb();
  const rows = await db.select<{ bank_account: string; end_date: string; ending_balance: number }[]>(`
    SELECT ba.account_name AS bank_account, br.end_date, br.ending_balance
    FROM bank_reconciliations br
    JOIN bank_accounts ba ON br.bank_account_id = ba.id
    ORDER BY br.end_date DESC LIMIT 1
  `);
  return rows[0] ?? null;
}

async function loadBudgetCategories(): Promise<BudgetLine[]> {
  const db = await getDb();
  const year = new Date().getFullYear();
  return db.select<BudgetLine[]>(`
    SELECT c.name AS category_name,
           COALESCE(bl.amount, 0) AS budgeted,
           COALESCE((
             SELECT SUM(bp2.amount)
             FROM bill_payments bp2
             JOIN vendor_bills vb ON vb.id = bp2.vendor_bill_id
             WHERE vb.category_id = c.id
               AND strftime('%Y', bp2.payment_date) = ?
           ), 0) AS actual
    FROM budget_lines bl
    JOIN budgets bu ON bl.budget_id = bu.id AND bu.fiscal_year = ?
    JOIN categories c ON bl.category_id = c.id
    WHERE c.category_type = 'EXPENSE'
    ORDER BY budgeted DESC
    LIMIT 5
  `, [String(year), year]);
}

// ── Stat row ──────────────────────────────────────────────────────────────────

type DashStats = {
  activeLots: number;
  openArTotal: number;
  openArCount: number;
};

async function loadStats(): Promise<DashStats> {
  const db = await getDb();
  const [lotRows, arRows] = await Promise.all([
    db.select<[{ n: number }]>("SELECT COUNT(*) as n FROM lots WHERE active_flag = 1"),
    db.select<[{ total: number; cnt: number }]>(
      "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as cnt FROM assessments WHERE status IN ('OPEN','PARTIAL')"
    ),
  ]);
  return {
    activeLots: lotRows[0]?.n ?? 0,
    openArTotal: arRows[0]?.total ?? 0,
    openArCount: arRows[0]?.cnt ?? 0,
  };
}

async function loadRecentTxns() {
  const db = await getDb();
  return db.select<{ txn_date: string; description: string; amount: number; account_name: string | null }[]>(`
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
  `);
}

// ── Prominent fin-tiles (top of dashboard, like Flask) ───────────────────────

const BANK_COLORS = ["#2f6046", "#26503a", "#1e3d2c", "#3a7a5a"];

function FinTileRow() {
  const [bankTiles, setBankTiles] = useState<BankTile[]>([]);
  const [recon, setRecon] = useState<LastRecon>(null);
  const [budgetLines, setBudgetLines] = useState<BudgetLine[]>([]);

  useEffect(() => {
    Promise.all([loadBankTiles(), loadLastRecon(), loadBudgetCategories()])
      .then(([b, r, bl]) => { setBankTiles(b); setRecon(r); setBudgetLines(bl); })
      .catch(() => {});
  }, []);

  const year = new Date().getFullYear();
  const totalBudgeted = budgetLines.reduce((s, l) => s + l.budgeted, 0);
  const totalActual   = budgetLines.reduce((s, l) => s + l.actual, 0);
  const budgetPct     = totalBudgeted > 0 ? Math.round((totalActual / totalBudgeted) * 100) : null;
  const overBudget    = budgetLines.filter((l) => l.actual > l.budgeted).length;
  const onTrack       = budgetLines.filter((l) => l.actual <= l.budgeted).length;

  return (
    <div className="grid grid-cols-2 gap-3" style={{ gridTemplateColumns: `repeat(${bankTiles.length + 2}, minmax(0,1fr))` }}>
      {bankTiles.map((t, i) => (
        <Link key={t.account_name} to="/bank/accounts"
          className="rounded-lg p-4 text-white hover:opacity-90 transition-opacity"
          style={{ backgroundColor: BANK_COLORS[i % BANK_COLORS.length] }}
        >
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ opacity: 0.75 }}>{t.account_name}</p>
          <p className="text-2xl font-bold mt-1">{fmt(t.current_balance)}</p>
          <p className="text-xs mt-0.5" style={{ opacity: 0.6 }}>{t.fund_code} Fund</p>
        </Link>
      ))}

      <Link to="/budgets"
        className="rounded-lg p-4 text-white hover:opacity-90 transition-opacity"
        style={{ backgroundColor: "#7a5312" }}
      >
        <p className="text-xs font-semibold uppercase tracking-wide" style={{ opacity: 0.75 }}>{year} Expenses vs Budget</p>
        {budgetPct !== null ? (
          <>
            <p className="text-2xl font-bold mt-1">{budgetPct}%</p>
            <div className="mt-1.5 h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: "rgba(255,255,255,0.25)" }}>
              <div className="h-full rounded-full bg-white" style={{ width: `${Math.min(100, budgetPct)}%` }} />
            </div>
            <p className="text-xs mt-1" style={{ opacity: 0.7 }}>
              {overBudget} over budget · {onTrack} on track
            </p>
          </>
        ) : (
          <p className="text-sm mt-2" style={{ opacity: 0.75 }}>No budget data</p>
        )}
      </Link>

      <Link to="/bank/reconciliations"
        className="rounded-lg p-4 text-white hover:opacity-90 transition-opacity"
        style={{ backgroundColor: "#5a3a7a" }}
      >
        <p className="text-xs font-semibold uppercase tracking-wide" style={{ opacity: 0.75 }}>Last Reconciliation</p>
        {recon ? (
          <>
            <p className="text-2xl font-bold mt-1">{fmt(recon.ending_balance)}</p>
            <p className="text-xs mt-0.5" style={{ opacity: 0.7 }}>{recon.bank_account} · {recon.end_date}</p>
          </>
        ) : (
          <p className="text-sm mt-2" style={{ opacity: 0.75 }}>No reconciliations yet</p>
        )}
      </Link>
    </div>
  );
}

// ── Financial card renderers (used in DB-driven sections) ─────────────────────

function FinancialCard({ card }: { card: DashCard }) {
  // These are now replaced by FinTileRow at top; render nothing to avoid duplication
  void card;
  return null;
}

// ── Card renderers ────────────────────────────────────────────────────────────

function NavCard({ card }: { card: DashCard }) {
  const navigate = useNavigate();
  const route = resolveRoute(card.target_url);
  const canNav = route !== "#";

  return (
    <button
      onClick={() => canNav && navigate(route, { state: { from: "/dashboard", fromLabel: "Dashboard" } })}
      disabled={!canNav}
      className={`w-full text-left rounded-lg border-t-4 bg-white p-3.5 shadow-sm transition-all
        ${canNav ? "hover:shadow-md hover:-translate-y-0.5 cursor-pointer" : "opacity-60 cursor-not-allowed"}`}
      style={{ borderTopColor: card.color }}
    >
      <p className="font-semibold text-gray-900 text-sm">{card.title}</p>
      {card.description && (
        <p className="text-xs text-gray-500 mt-0.5 leading-snug">{card.description}</p>
      )}
      {!canNav && <p className="text-xs text-gray-400 italic mt-1">Coming soon</p>}
    </button>
  );
}

function ReportCard({ card }: { card: DashCard }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate("/reports", { state: { from: "/dashboard", fromLabel: "Dashboard" } })}
      className="w-full text-left rounded-lg border bg-white p-3.5 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all"
      style={{ borderColor: card.color + "88" }}
    >
      <p className="font-semibold text-sm" style={{ color: card.color }}>{card.title}</p>
      {card.description && (
        <p className="text-xs text-gray-500 mt-0.5">{card.description}</p>
      )}
      <p className="text-xs text-blue-600 mt-1">Open report →</p>
    </button>
  );
}

// ── Announcements ─────────────────────────────────────────────────────────────

const BANNER_STYLE: Record<string, string> = {
  info:    "bg-blue-50 border-blue-200 text-blue-900",
  warning: "bg-amber-50 border-amber-200 text-amber-900",
  urgent:  "bg-red-50 border-red-200 text-red-900",
};

// ── Onboarding helpers ────────────────────────────────────────────────────────

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

// ── Dashboard ─────────────────────────────────────────────────────────────────

export function Dashboard() {
  const [stats, setStats] = useState<DashStats | null>(null);
  const [recentTxns, setRecentTxns] = useState<{ txn_date: string; description: string; amount: number; account_name: string | null }[]>([]);
  const [cards, setCards] = useState<DashCard[]>([]);
  const [onboarding, setOnboarding] = useState<{ obEntered: boolean; dismissed: boolean } | null>(null);
  const [banners, setBanners] = useState<Announcement[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dbDiag, setDbDiag] = useState<string>("checking…");
  const { sorted, sortKey, sortDir, toggleSort } = useTableSort(recentTxns, {
    date: (r) => r.txn_date,
    description: (r) => r.description,
    account: (r) => r.account_name,
    amount: (r) => r.amount,
  });

  useEffect(() => {
    Promise.all([getDb(), readConfig()])
      .then(async ([db, cfg]) => {
        const [lotRows, ownerRows, userRows] = await Promise.all([
          db.select<[{n:number}]>("SELECT COUNT(*) as n FROM lots"),
          db.select<[{n:number}]>("SELECT COUNT(*) as n FROM owners"),
          db.select<[{n:number}]>("SELECT COUNT(*) as n FROM local_users"),
        ]);
        setDbDiag(
          `✓ connected | path: ${cfg?.db_path ?? "browser"} | lots: ${lotRows[0]?.n ?? 0} | owners: ${ownerRows[0]?.n ?? 0} | users: ${userRows[0]?.n ?? 0}`
        );
      })
      .catch((e: unknown) => setDbDiag(`✗ ERROR: ${String(e)}`));
  }, []);

  useEffect(() => {
    Promise.all([
      loadStats(),
      loadRecentTxns(),
      loadDashboardCards(),
      loadOnboardingState(),
      listActiveAnnouncements(),
    ])
      .then(([s, txns, cds, o, b]) => {
        setStats(s);
        setRecentTxns(txns);
        setCards(cds);
        setOnboarding(o);
        setBanners(b);
      })
      .catch((e) => setError(String(e)));
  }, []);

  async function handleDismiss() {
    await dismissOnboardingAlert();
    setOnboarding((o) => o ? { ...o, dismissed: true } : o);
  }

  const showObAlert = onboarding && !onboarding.obEntered && !onboarding.dismissed;

  // Group cards into runs: financial cards span the full grid, NAV/REPORT cards share a grid row
  // Split into sections based on SECTION cards acting as headers
  type Section = { heading: DashCard | null; items: DashCard[] };
  const sections: Section[] = [];
  let current: Section = { heading: null, items: [] };
  for (const card of cards) {
    if (card.card_type === "SECTION") {
      if (current.items.length > 0 || current.heading) sections.push(current);
      current = { heading: card, items: [] };
    } else {
      current.items.push(card);
    }
  }
  if (current.items.length > 0 || current.heading) sections.push(current);

  return (
    <PageLayout title="Dashboard" subtitle="HOA Accounting overview." helpId="dashboard">
      <div className="space-y-6">
      {/* DB diagnostic */}
      <div className="font-mono text-xs p-2 bg-black text-green-400 rounded break-all">
        {dbDiag}
      </div>

      {/* Prominent financial tiles */}
      <FinTileRow />

      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Announcements */}
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

      {/* Stat summary row */}
      {stats && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Link to="/lots" className="block bg-white border rounded-lg p-4 hover:shadow-md transition-shadow">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Active Lots</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{stats.activeLots}</p>
          </Link>
          <Link to="/ar" className="block bg-white border rounded-lg p-4 hover:shadow-md transition-shadow">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Outstanding AR</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{fmt(stats.openArTotal)}</p>
            <p className="text-xs text-gray-400">{stats.openArCount} open charge{stats.openArCount !== 1 ? "s" : ""}</p>
          </Link>
          <Link to="/reports" className="block bg-white border rounded-lg p-4 hover:shadow-md transition-shadow">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Reports</p>
            <p className="text-sm font-medium text-blue-600 mt-2">View all reports →</p>
          </Link>
        </div>
      )}

      {/* DB-driven sections */}
      {sections.map((sec, si) => (
        <div key={si}>
          {sec.heading && (
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
              {sec.heading.title}
            </h2>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sec.items.map((card) => {
              if (card.card_type === "FINANCIAL") return <FinancialCard key={card.id} card={card} />;
              if (card.card_type === "NAV") return <NavCard key={card.id} card={card} />;
              if (card.card_type === "REPORT") return <ReportCard key={card.id} card={card} />;
              if (card.card_type === "COMMENT") {
                return (
                  <div key={card.id} className="col-span-full text-xs text-gray-500 italic">
                    {card.description ?? card.title}
                  </div>
                );
              }
              return null;
            })}
          </div>
        </div>
      ))}

      {/* Recent activity */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-800">Recent Activity</h2>
          <Link to="/reports" className="text-xs text-blue-600 hover:underline">View all →</Link>
        </div>
        <div className="border rounded-lg overflow-auto max-h-[calc(100vh-200px)] bg-white">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 border-b">
              <tr>
                <SortableTh label="Date" col="date" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Description" col="description" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Account" col="account" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortableTh label="Amount" col="amount" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} right />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {recentTxns.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-400 text-sm">No transactions yet.</td>
                </tr>
              )}
              {sorted.map((r, i) => (
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
      </div>
    </PageLayout>
  );
}
