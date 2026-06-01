import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { DbProvider } from "./contexts/DbContext";
import { AppShell } from "./components/AppShell";
import { Dashboard } from "./screens/Dashboard";
import { CategoriesScreen } from "./screens/CategoriesScreen";
import { LotsScreen } from "./screens/LotsScreen";
import { OwnersScreen } from "./screens/OwnersScreen";
import { BankAccountsScreen } from "./screens/BankAccountsScreen";
import { VendorsScreen } from "./screens/VendorsScreen";
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
            <Route path="opening-balances" element={<Placeholder title="Opening Balances" />} />

            {/* Bank */}
            <Route path="bank/accounts" element={<BankAccountsScreen />} />
            <Route path="bank/import" element={<Placeholder title="Bank Import" />} />
            <Route path="bank/pending" element={<Placeholder title="Pending Transactions" />} />
            <Route path="bank/reconciliations" element={<Placeholder title="Reconciliations" />} />
            <Route path="bank/reconciliations/new" element={<Placeholder title="New Reconciliation" />} />

            {/* Budgets */}
            <Route path="budgets" element={<Placeholder title="Budgets" />} />

            {/* Vendors & Bills */}
            <Route path="vendors" element={<VendorsScreen />} />
            <Route path="bills" element={<Placeholder title="Vendor Bills" />} />

            {/* Assessments & AR */}
            <Route path="assessments" element={<Placeholder title="Assessments" />} />
            <Route path="ar" element={<Placeholder title="Accounts Receivable" />} />
            <Route path="deposits" element={<Placeholder title="Deposits" />} />

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
