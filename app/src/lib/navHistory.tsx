import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

// ── Route label map ───────────────────────────────────────────────────────────

const ROUTE_LABELS: [RegExp, string][] = [
  [/^\/dashboard$/, "Dashboard"],
  [/^\/lots\/transfer/, "Lot Transfer"],
  [/^\/lots\/\d+/, "Lot Detail"],
  [/^\/lots$/, "Lots"],
  [/^\/owners$/, "Owners"],
  [/^\/transactions$/, "Transactions"],
  [/^\/ledger\/by-account$/, "Ledger"],
  [/^\/opening-balances$/, "Opening Balances"],
  [/^\/bank\/accounts$/, "Bank Accounts"],
  [/^\/bank\/other-income$/, "Other Income"],
  [/^\/bank\/import$/, "Bank Import"],
  [/^\/bank\/ofx-import$/, "OFX Import"],
  [/^\/bank\/ofx-inbox$/, "OFX Inbox"],
  [/^\/bank\/pending$/, "Pending Transactions"],
  [/^\/bank\/reconciliations/, "Reconciliations"],
  [/^\/budgets$/, "Budgets"],
  [/^\/vendors$/, "Vendors"],
  [/^\/bills$/, "Bills"],
  [/^\/assessments$/, "Assessments"],
  [/^\/ar$/, "Accounts Receivable"],
  [/^\/deposits$/, "Deposits"],
  [/^\/reserve\/transfers$/, "Reserve Transfers"],
  [/^\/reserve$/, "Reserve Study"],
  [/^\/workflow-guide$/, "Workflow Guide"],
  [/^\/audit-log$/, "Audit Log"],
  [/^\/owner-statements$/, "Owner Statements"],
  [/^\/reports\/publish$/, "Publish Statements"],
  [/^\/reports$/, "Reports"],
  [/^\/profile$/, "Profile"],
  [/^\/billing\/dues$/, "Dues Billing"],
  [/^\/billing\/late-fees$/, "Late Fees"],
  [/^\/billing\/resale-fee$/, "Resale Fee"],
  [/^\/renters$/, "Renters"],
  [/^\/accounting-periods$/, "Accounting Periods"],
  [/^\/data-import$/, "Data Import"],
  [/^\/announcements$/, "Announcements"],
  [/^\/categories\/wizard$/, "Account Setup Wizard"],
  [/^\/categories$/, "Chart of Accounts"],
  [/^\/admin\/transaction-rules$/, "Transaction Rules"],
  [/^\/users$/, "Users"],
  [/^\/settings$/, "Settings"],
];

export function getLabelForPath(path: string): string {
  for (const [re, label] of ROUTE_LABELS) {
    if (re.test(path)) return label;
  }
  return path.replace(/^\//, "").replace(/-/g, " ");
}

// ── Context ───────────────────────────────────────────────────────────────────

export type Crumb = { path: string; label: string };

const NavHistoryContext = createContext<Crumb[]>([]);

const MAX = 6;

export function NavHistoryProvider({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  const lastPath = useRef("");

  useEffect(() => {
    const path = location.pathname;
    if (path === lastPath.current) return;
    lastPath.current = path;
    const label = getLabelForPath(path);

    setCrumbs((prev) => {
      // Navigating back to a page already in the trail → truncate there
      const idx = prev.findIndex((c) => c.path === path);
      if (idx >= 0) return prev.slice(0, idx + 1);
      // Push new crumb, cap at MAX
      const next = [...prev, { path, label }];
      return next.length > MAX ? next.slice(next.length - MAX) : next;
    });
  }, [location.pathname]);

  return (
    <NavHistoryContext.Provider value={crumbs}>
      {children}
    </NavHistoryContext.Provider>
  );
}

export function useNavHistory(): Crumb[] {
  return useContext(NavHistoryContext);
}
