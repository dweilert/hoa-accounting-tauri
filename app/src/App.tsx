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
import { PublishStatementsScreen } from "./screens/PublishStatementsScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { LotDetailScreen } from "./screens/LotDetailScreen";
import { ReserveStudyScreen } from "./screens/ReserveStudyScreen";
import { UsersScreen } from "./screens/UsersScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { CoaWizardScreen } from "./screens/CoaWizardScreen";
import { AnnouncementsScreen } from "./screens/AnnouncementsScreen";
import { DuesBillingScreen } from "./screens/DuesBillingScreen";
import { TransactionRulesScreen } from "./screens/TransactionRulesScreen";
import { WorkflowGuideScreen } from "./screens/WorkflowGuideScreen";
import { AuditLogScreen } from "./screens/AuditLogScreen";
import { ReserveTransfersScreen } from "./screens/ReserveTransfersScreen";
import { BankTransfersScreen } from "./screens/BankTransfersScreen";
import { LotTransferScreen } from "./screens/LotTransferScreen";
import { LateFeesScreen } from "./screens/LateFeesScreen";
import { AccountingPeriodsScreen } from "./screens/AccountingPeriodsScreen";
import { DataImportScreen } from "./screens/DataImportScreen";
import { ResaleFeeScreen } from "./screens/ResaleFeeScreen";
import { RentersScreen } from "./screens/RentersScreen";
import { OFXImportScreen } from "./screens/OFXImportScreen";
import { OFXInboxScreen } from "./screens/OFXInboxScreen";
import { OFXReconciliationScreen } from "./screens/OFXReconciliationScreen";
import { OwnerStatementsScreen } from "./screens/OwnerStatementsScreen";
import { PaymentsScreen } from "./screens/PaymentsScreen";
import { PettyCashScreen } from "./screens/PettyCashScreen";
import { OtherIncomeScreen } from "./screens/OtherIncomeScreen";
import { SanityCheckScreen } from "./screens/SanityCheckScreen";
import { AppDialogHost } from "./components/AppDialogs";

export default function App() {
  return (
    <AuthProvider>
    <DbProvider>
      <BrowserRouter>
        <AppDialogHost />
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
            <Route path="bank/ofx-inbox" element={<OFXInboxScreen />} />
            <Route path="bank/ofx-reconciliation" element={<OFXReconciliationScreen />} />
            <Route path="bank/pending" element={<BankPendingScreen />} />
            <Route path="bank/reconciliations" element={<ReconciliationsScreen />} />
            <Route path="bank/reconciliations/new" element={<ReconciliationsScreen />} />
            <Route path="bank/transfers" element={<BankTransfersScreen />} />

            {/* Budgets */}
            <Route path="budgets" element={<BudgetsScreen />} />

            {/* Vendors & Bills */}
            <Route path="vendors" element={<VendorsScreen />} />
            <Route path="bills" element={<VendorBillsScreen />} />

            {/* Assessments & AR */}
            <Route path="assessments" element={<AssessmentsScreen />} />
            <Route path="ar" element={<ARScreen />} />
            <Route path="payments" element={<PaymentsScreen />} />
            <Route path="petty-cash" element={<PettyCashScreen />} />
            <Route path="bank/other-income" element={<OtherIncomeScreen />} />
            <Route path="deposits" element={<DepositsScreen />} />

            {/* Reserve Study */}
            <Route path="reserve" element={<ReserveStudyScreen />} />
            <Route path="reserve/transfers" element={<ReserveTransfersScreen />} />

            {/* Workflow Guide */}
            <Route path="workflow-guide" element={<WorkflowGuideScreen />} />

            {/* Audit Log */}
            <Route path="audit-log" element={<RequireAdmin><AuditLogScreen /></RequireAdmin>} />
            <Route path="sanity-check" element={<RequireAdmin><SanityCheckScreen /></RequireAdmin>} />

            {/* Owner Statements */}
            <Route path="owner-statements" element={<OwnerStatementsScreen />} />

            {/* Reports */}
            <Route path="reports" element={<ReportsScreen />} />
            <Route path="reports/publish" element={<PublishStatementsScreen />} />

            {/* Profile */}
            <Route path="profile" element={<ProfileScreen />} />

            {/* Billing & Editing */}
            <Route path="billing/dues" element={<RequireAdmin><DuesBillingScreen /></RequireAdmin>} />
            <Route path="billing/late-fees" element={<RequireAdmin><LateFeesScreen /></RequireAdmin>} />
            <Route path="billing/resale-fee" element={<RequireAdmin><ResaleFeeScreen /></RequireAdmin>} />

            {/* Board Members & Renters */}
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
