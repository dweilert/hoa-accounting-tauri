import { Outlet, NavLink, Link } from "react-router-dom";
import { useAuth, useCurrentUser } from "../contexts/AuthContext";

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
    ],
  },
  {
    heading: "Transactions",
    items: [
      { label: "Opening Balances", to: "/opening-balances" },
    ],
  },
  {
    heading: "Bank",
    items: [
      { label: "Accounts", to: "/bank/accounts" },
      { label: "Import", to: "/bank/import" },
      { label: "Pending", to: "/bank/pending" },
      { label: "Reconciliations", to: "/bank/reconciliations" },
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
      { label: "Accounts Receivable", to: "/ar" },
      { label: "Deposits", to: "/deposits" },
    ],
  },
  {
    heading: "Reserve Study",
    items: [{ label: "Reserve Study", to: "/reserve" }],
  },
  {
    heading: "Reports",
    items: [{ label: "Reports", to: "/reports" }],
  },
  {
    heading: "Admin",
    adminOnly: true,
    items: [
      { label: "Chart of Accounts", to: "/categories" },
      { label: "Users", to: "/users" },
      { label: "Settings", to: "/settings" },
    ],
  },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  [
    "block px-3 py-1.5 rounded text-sm transition-colors",
    isActive
      ? "bg-blue-600 text-white font-medium"
      : "text-gray-300 hover:bg-gray-700 hover:text-white",
  ].join(" ");

export function AppShell() {
  const { logout } = useAuth();
  const currentUser = useCurrentUser();
  const isAdmin = currentUser?.role === "admin";

  return (
    <div className="flex h-screen bg-gray-100 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-gray-800 flex flex-col overflow-y-auto">
        <div className="px-4 py-4 border-b border-gray-700">
          <span className="text-white font-semibold text-sm tracking-wide">HOA Accounting</span>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-4">
          {NAV.filter((s) => !s.adminOnly || isAdmin).map((section) => (
            <div key={section.heading}>
              {section.items.length > 1 && (
                <p className="px-3 mb-1 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  {section.heading}
                </p>
              )}
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <li key={item.to}>
                    <NavLink to={item.to} className={linkClass}>
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        {/* User footer */}
        <div className="px-3 py-3 border-t border-gray-700">
          <Link to="/profile" className="block text-xs text-gray-300 hover:text-white truncate mb-1">
            {currentUser?.displayName ?? currentUser?.email}
          </Link>
          <p className="text-xs text-gray-500 truncate mb-2">{currentUser?.role}</p>
          <button
            onClick={logout}
            className="w-full text-left text-xs text-gray-400 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
