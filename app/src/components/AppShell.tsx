import { useState, useEffect } from "react";
import { Outlet, NavLink, Link } from "react-router-dom";
import { useAuth, useCurrentUser } from "../contexts/AuthContext";
import { NavHistoryProvider } from "../lib/navHistory";
import { getHoaSettings } from "../repositories/setupRepo";
import { ErrorBoundary } from "./ErrorBoundary";
import { logNote } from "../lib/errorLog";

type NavItem = { label: string; to: string };
type NavSection = { heading: string; items: NavItem[]; adminOnly?: boolean };

const NAV: NavSection[] = [
  {
    heading: "Overview",
    items: [{ label: "Dashboard", to: "/dashboard" }],
  },
  {
    heading: "Properties",
    items: [
      { label: "Lots", to: "/lots" },
      { label: "Owners", to: "/owners" },
      { label: "Board Members", to: "/board-members" },
      { label: "Renters", to: "/renters" },
    ],
  },
  {
    heading: "Transactions",
    items: [
      { label: "All Transactions", to: "/transactions" },
      { label: "Opening Balances", to: "/opening-balances" },
    ],
  },
  {
    heading: "Bank",
    items: [
      { label: "Accounts", to: "/bank/accounts" },
      { label: "Import CSV", to: "/bank/import" },
      { label: "Import OFX/QFX", to: "/bank/ofx-import" },
      { label: "OFX Inbox", to: "/bank/ofx-inbox" },
      { label: "Pending", to: "/bank/pending" },
      { label: "Reconciliations", to: "/bank/reconciliations" },
      { label: "Transfers", to: "/bank/transfers" },
    ],
  },
  {
    heading: "Budgets",
    items: [{ label: "Budgets", to: "/budgets" }],
  },
  {
    heading: "Vendors & Bills",
    items: [
      { label: "Vendors", to: "/vendors" },
      { label: "Bills", to: "/bills" },
    ],
  },
  {
    heading: "Assessments",
    items: [
      { label: "Assessments", to: "/assessments" },
      { label: "Dues Billing", to: "/billing/dues" },
      { label: "Late Fees", to: "/billing/late-fees" },
      { label: "Resale Fee", to: "/billing/resale-fee" },
      { label: "Accounts Receivable", to: "/ar" },
      { label: "Deposits", to: "/deposits" },
      { label: "Owner Statements", to: "/owner-statements" },
    ],
  },
  {
    heading: "Corrections",
    items: [
      { label: "Edit Records", to: "/edit-records" },
    ],
  },
  {
    heading: "Reserve Study",
    items: [
      { label: "Reserve Study", to: "/reserve" },
      { label: "Reserve Transfers", to: "/reserve/transfers" },
    ],
  },
  {
    heading: "Workflow Guide",
    items: [{ label: "Workflow Guide", to: "/workflow-guide" }],
  },
  {
    heading: "Reports",
    items: [{ label: "Reports", to: "/reports" }, { label: "Publish to S3", to: "/reports/publish" }],
  },
  {
    heading: "Admin",
    adminOnly: true,
    items: [
      { label: "Chart of Accounts", to: "/categories" },
      { label: "Transaction Rules", to: "/admin/transaction-rules" },
      { label: "Lot Transfer Wizard", to: "/lots/transfer" },
      { label: "Accounting Periods", to: "/accounting-periods" },
      { label: "Data Import", to: "/data-import" },
      { label: "Audit Log", to: "/audit-log" },
      { label: "Sanity Check", to: "/sanity-check" },
      { label: "Announcements", to: "/announcements" },
      { label: "Users", to: "/users" },
      { label: "Settings", to: "/settings" },
    ],
  },
];

// ── Hamburger icon ────────────────────────────────────────────────────────────

function HamburgerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
      <rect x="1" y="3" width="16" height="2" rx="1" />
      <rect x="1" y="8" width="16" height="2" rx="1" />
      <rect x="1" y="13" width="16" height="2" rx="1" />
    </svg>
  );
}

// ── AppShell ──────────────────────────────────────────────────────────────────

export function AppShell() {
  const { logout } = useAuth();
  const currentUser = useCurrentUser();
  const isAdmin = currentUser?.role === "admin";
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const [hoaName, setHoaName] = useState("HOA Accounting");
  const [reportingBug, setReportingBug] = useState(false);
  const [bugNote, setBugNote] = useState("");
  const [bugLogged, setBugLogged] = useState(false);

  function toggleSection(heading: string) {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      next.has(heading) ? next.delete(heading) : next.add(heading);
      return next;
    });
  }

  useEffect(() => {
    getHoaSettings().then((s) => { if (s.hoa_name) setHoaName(s.hoa_name); }).catch(() => {});
  }, []);

  return (
    <div className="flex flex-col h-screen overflow-hidden print:block print:h-auto print:overflow-visible">

      {/* ── Fixed hairline top bar ── */}
      <header
        className="fixed top-0 left-0 right-0 z-30 flex items-center gap-2 px-3 print:hidden"
        style={{
          height: "40px",
          backgroundColor: "#f2f5f1",
          borderBottom: "1px solid #c5d0c0",
        }}
      >
        {/* Hamburger */}
        <button
          onClick={() => setSidebarOpen((o) => !o)}
          className="p-1.5 rounded text-gray-500 hover:text-gray-900 transition-colors"
          title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
        >
          <HamburgerIcon />
        </button>

        {/* Org name from settings */}
        <span className="text-sm font-semibold text-gray-900 mr-2 select-none truncate max-w-xs">
          {hoaName}
        </span>

        <div className="flex-1" />

        {/* User info + sign out */}
        <div className="flex items-center gap-3 text-xs">
          {currentUser && (
            <>
              <Link
                to="/profile"
                className="text-gray-600 hover:text-gray-900 transition-colors hidden sm:block"
              >
                {currentUser.displayName ?? currentUser.email}
              </Link>
              <span
                className="px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide hidden sm:inline"
                style={{ fontSize: "10px", backgroundColor: "#d9ede9", color: "#2f6046" }}
              >
                {currentUser.role}
              </span>
            </>
          )}
          <button
            onClick={() => { setReportingBug(true); setBugLogged(false); setBugNote(""); }}
            title="Report a bug"
            className="text-gray-400 hover:text-red-600 transition-colors"
            style={{ fontSize: "15px" }}
          >
            🐛
          </button>
          <button
            onClick={logout}
            className="text-gray-500 hover:text-gray-900 transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* ── Body (below fixed top bar) ── */}
      <div className="flex flex-1 overflow-hidden" style={{ marginTop: "40px" }}>

        {/* ── Sidebar ── */}
        <aside
          className="shrink-0 flex flex-col overflow-y-auto overflow-x-hidden transition-all duration-200 print:hidden"
          style={{
            width: sidebarOpen ? "224px" : "0px",
            backgroundColor: "#e8ede6",
            borderRight: "1px solid #cdd6c9",
          }}
        >
          <nav className="flex-1 px-2 py-3 space-y-4" style={{ minWidth: "224px" }}>
            {NAV.filter((s) => !s.adminOnly || isAdmin).map((section) => {
              const collapsed = collapsedSections.has(section.heading);
              return (
                <div key={section.heading}>
                  {/* Section heading — click to collapse */}
                  <button
                    onClick={() => toggleSection(section.heading)}
                    className="w-full flex items-center gap-2 mb-1 pl-1 cursor-pointer select-none"
                    style={{ borderLeft: "3px solid #2a6b5e" }}
                  >
                    <p
                      className="flex-1 px-2 text-xs font-semibold uppercase tracking-wider text-left"
                      style={{ color: "#2a6b5e" }}
                    >
                      {section.heading}
                    </p>
                    <span className="pr-2 text-xs" style={{ color: "#2a6b5e" }}>
                      {collapsed ? "▸" : "▾"}
                    </span>
                  </button>
                  {!collapsed && (
                    <ul className="space-y-0.5">
                      {section.items.map((item) => (
                        <li key={item.to}>
                          <NavLink
                            to={item.to}
                            className={({ isActive }) =>
                              isActive
                                ? "block px-3 py-1.5 rounded text-sm font-medium transition-colors"
                                : "block px-3 py-1.5 rounded text-sm transition-colors hover:bg-[#d9ede9]"
                            }
                            style={({ isActive }) =>
                              isActive
                                ? { backgroundColor: "#d9ede9", color: "#2a6b5e" }
                                : { color: "#4d5e49" }
                            }
                          >
                            {item.label}
                          </NavLink>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </nav>

          {/* Sidebar footer */}
          <div className="px-3 py-2 text-xs" style={{ borderTop: "1px solid #cdd6c9", minWidth: "224px" }}>
            <p style={{ color: "#4d5e49" }}>{currentUser?.email}</p>
          </div>
        </aside>

        {/* ── Main content ── */}
        <main className="flex-1 overflow-y-auto print:overflow-visible print:w-full">
          <NavHistoryProvider>
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </NavHistoryProvider>
        </main>
      </div>
      {/* Bug report modal */}
      {reportingBug && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: "rgba(0,0,0,0.3)" }}>
          <div className="bg-white rounded-lg shadow-xl p-5 w-80 space-y-3">
            <p className="font-semibold text-gray-900 text-sm">Report an Issue</p>
            <p className="text-xs text-gray-500">
              Describe what happened. Logged to ~/hoa-system/tauri/errors.log.
            </p>
            <textarea
              autoFocus
              value={bugNote}
              onChange={(e) => setBugNote(e.target.value)}
              rows={4}
              placeholder="e.g. Clicked Reconcile → screen went blank"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            {bugLogged && (
              <p className="text-xs text-green-700">Logged ✓</p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setReportingBug(false)}
                className="text-xs px-3 py-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                disabled={!bugNote.trim()}
                onClick={async () => {
                  await logNote(`screen=${window.location.pathname} | ${bugNote.trim()}`);
                  setBugLogged(true);
                  setTimeout(() => setReportingBug(false), 1200);
                }}
                className="text-xs px-3 py-1.5 rounded text-white disabled:opacity-50"
                style={{ backgroundColor: "#2f6046" }}
              >
                Log it
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
