import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { DbProvider } from "./contexts/DbContext";
import { AppShell } from "./components/AppShell";
import { Dashboard } from "./screens/Dashboard";
import { CategoriesScreen } from "./screens/CategoriesScreen";
import { LotsScreen } from "./screens/LotsScreen";
import { OwnersScreen } from "./screens/OwnersScreen";
import { BankAccountsScreen } from "./screens/BankAccountsScreen";
import { BankImportScreen } from "./screens/BankImportScreen";
import { BankPendingScreen } from "./screens/BankPendingScreen";
import { ReconciliationsScreen } from "./screens/ReconciliationsScreen";
import { VendorsScreen } from "./screens/VendorsScreen";
import { VendorBillsScreen } from "./screens/VendorBillsScreen";
import { OpeningBalancesScreen } from "./screens/OpeningBalancesScreen";
import { AssessmentsScreen } from "./screens/AssessmentsScreen";
import { ARScreen } from "./screens/ARScreen";
import { DepositsScreen } from "./screens/DepositsScreen";
import { BudgetsScreen } from "./screens/BudgetsScreen";
import { Placeholder } from "./screens/Placeholder";

export default function App() {
  return (
    <DbProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />

            {/* Lots & Owners */}
            <Route path="lots" element={<LotsScreen />} />
            <Route path="lots/:id" element={<Placeholder title="Lot Detail" />} />
            <Route path="owners" element={<OwnersScreen />} />

            {/* Transactions */}
            <Route path="transactions" element={<Placeholder title="All Transactions" />} />
            <Route path="ledger/by-account" element={<Placeholder title="Ledger by Account" />} />
            <Route path="opening-balances" element={<OpeningBalancesScreen />} />

            {/* Bank */}
            <Route path="bank/accounts" element={<BankAccountsScreen />} />
            <Route path="bank/import" element={<BankImportScreen />} />
            <Route path="bank/pending" element={<BankPendingScreen />} />
            <Route path="bank/reconciliations" element={<ReconciliationsScreen />} />
            <Route path="bank/reconciliations/new" element={<ReconciliationsScreen />} />

            {/* Budgets */}
            <Route path="budgets" element={<BudgetsScreen />} />

            {/* Vendors & Bills */}
            <Route path="vendors" element={<VendorsScreen />} />
            <Route path="bills" element={<VendorBillsScreen />} />

            {/* Assessments & AR */}
            <Route path="assessments" element={<AssessmentsScreen />} />
            <Route path="ar" element={<ARScreen />} />
            <Route path="deposits" element={<DepositsScreen />} />

            {/* Reserve Study */}
            <Route path="reserve" element={<Placeholder title="Reserve Study" />} />

            {/* Reports */}
            <Route path="reports" element={<Placeholder title="Reports" />} />

            {/* Admin */}
            <Route path="categories" element={<CategoriesScreen />} />
            <Route path="users" element={<Placeholder title="Users" />} />
            <Route path="settings" element={<Placeholder title="Settings" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </DbProvider>
  );
}
