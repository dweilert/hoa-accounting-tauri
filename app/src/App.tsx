import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { DbProvider } from "./contexts/DbContext";
import { AuthProvider } from "./contexts/AuthContext";
import { AuthGate } from "./screens/LoginScreen";
import { RequireAdmin } from "./components/RequireAdmin";
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
import { TransactionsScreen } from "./screens/TransactionsScreen";
import { LedgerByAccountScreen } from "./screens/LedgerByAccountScreen";
import { ReportsScreen } from "./screens/ReportsScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { LotDetailScreen } from "./screens/LotDetailScreen";
import { ReserveStudyScreen } from "./screens/ReserveStudyScreen";
import { UsersScreen } from "./screens/UsersScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { CoaWizardScreen } from "./screens/CoaWizardScreen";
import { AnnouncementsScreen } from "./screens/AnnouncementsScreen";
import { DuesBillingScreen } from "./screens/DuesBillingScreen";
import { EditRecordsScreen } from "./screens/EditRecordsScreen";
import { TransactionRulesScreen } from "./screens/TransactionRulesScreen";
import { WorkflowGuideScreen } from "./screens/WorkflowGuideScreen";
import { AuditLogScreen } from "./screens/AuditLogScreen";
import { ReserveTransfersScreen } from "./screens/ReserveTransfersScreen";
import { LotTransferScreen } from "./screens/LotTransferScreen";
import { LateFeesScreen } from "./screens/LateFeesScreen";
import { AccountingPeriodsScreen } from "./screens/AccountingPeriodsScreen";
import { BoardMembersScreen } from "./screens/BoardMembersScreen";
import { DataImportScreen } from "./screens/DataImportScreen";
import { ResaleFeeScreen } from "./screens/ResaleFeeScreen";
import { RentersScreen } from "./screens/RentersScreen";
import { OFXImportScreen } from "./screens/OFXImportScreen";
import { OwnerStatementsScreen } from "./screens/OwnerStatementsScreen";

export default function App() {
  return (
    <AuthProvider>
    <DbProvider>
      <BrowserRouter>
        <AuthGate>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />

            {/* Lots & Owners */}
            <Route path="lots" element={<LotsScreen />} />
            <Route path="lots/:id" element={<LotDetailScreen />} />
            <Route path="lots/transfer" element={<RequireAdmin><LotTransferScreen /></RequireAdmin>} />
            <Route path="owners" element={<OwnersScreen />} />

            {/* Transactions */}
            <Route path="transactions" element={<TransactionsScreen />} />
            <Route path="ledger/by-account" element={<LedgerByAccountScreen />} />
            <Route path="opening-balances" element={<OpeningBalancesScreen />} />

            {/* Bank */}
            <Route path="bank/accounts" element={<BankAccountsScreen />} />
            <Route path="bank/import" element={<BankImportScreen />} />
            <Route path="bank/ofx-import" element={<OFXImportScreen />} />
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
            <Route path="reserve" element={<ReserveStudyScreen />} />
            <Route path="reserve/transfers" element={<ReserveTransfersScreen />} />

            {/* Workflow Guide */}
            <Route path="workflow-guide" element={<WorkflowGuideScreen />} />

            {/* Audit Log */}
            <Route path="audit-log" element={<RequireAdmin><AuditLogScreen /></RequireAdmin>} />

            {/* Owner Statements */}
            <Route path="owner-statements" element={<OwnerStatementsScreen />} />

            {/* Reports */}
            <Route path="reports" element={<ReportsScreen />} />

            {/* Profile */}
            <Route path="profile" element={<ProfileScreen />} />

            {/* Billing & Editing */}
            <Route path="billing/dues" element={<RequireAdmin><DuesBillingScreen /></RequireAdmin>} />
            <Route path="billing/late-fees" element={<RequireAdmin><LateFeesScreen /></RequireAdmin>} />
            <Route path="billing/resale-fee" element={<RequireAdmin><ResaleFeeScreen /></RequireAdmin>} />
            <Route path="edit-records" element={<EditRecordsScreen />} />

            {/* Board Members & Renters */}
            <Route path="board-members" element={<BoardMembersScreen />} />
            <Route path="renters" element={<RentersScreen />} />

            {/* Admin — requires admin role */}
            <Route path="accounting-periods" element={<RequireAdmin><AccountingPeriodsScreen /></RequireAdmin>} />
            <Route path="data-import" element={<RequireAdmin><DataImportScreen /></RequireAdmin>} />
            <Route path="announcements" element={<RequireAdmin><AnnouncementsScreen /></RequireAdmin>} />
            <Route path="categories/wizard" element={<RequireAdmin><CoaWizardScreen /></RequireAdmin>} />
            <Route path="categories" element={<RequireAdmin><CategoriesScreen /></RequireAdmin>} />
            <Route path="admin/transaction-rules" element={<RequireAdmin><TransactionRulesScreen /></RequireAdmin>} />
            <Route path="users" element={<RequireAdmin><UsersScreen /></RequireAdmin>} />
            <Route path="settings" element={<RequireAdmin><SettingsScreen /></RequireAdmin>} />
          </Route>
        </Routes>
        </AuthGate>
      </BrowserRouter>
    </DbProvider>
    </AuthProvider>
  );
}
