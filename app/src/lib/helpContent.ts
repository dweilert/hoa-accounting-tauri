export type HelpContent = {
  heading: string;
  description: string;
  tips: string[];
  warning?: string;
};

export const HELP: Record<string, HelpContent> = {
  dashboard: {
    heading: "Dashboard",
    description: "Your HOA accounting home base. Shows bank balances, outstanding AR, quick-action cards, and recent activity.",
    tips: [
      "Click any quick-action card to jump directly to that workflow.",
      "The Financial Summary section shows live bank balances and your last reconciliation.",
      "The Recent Activity table shows the last 8 posted transactions across all accounts.",
      "Announcement banners appear here when you post notices in Admin → Announcements.",
    ],
  },
  lots: {
    heading: "Lots",
    description: "Directory of all HOA lots. Each lot holds ownership history, assessment charges, and payment records.",
    tips: [
      "Click a lot row to open its full ledger and owner history.",
      "Active lots are included in dues billing and AR reports.",
      "Deactivate a lot if it leaves the HOA — history is retained.",
    ],
  },
  lotDetail: {
    heading: "Lot Detail",
    description: "Full ledger for a single lot — charges, payments, balance, and owner history.",
    tips: [
      "The ledger shows all assessments and payments in date order.",
      "Owner History shows when ownership changed and who held the lot.",
      "Use Lot Transfer Wizard (Admin menu) to record a property sale.",
    ],
  },
  owners: {
    heading: "Owners",
    description: "Directory of all property owners. Multiple owners can be linked to the same lot (e.g., couples or co-owners).",
    tips: [
      "Each owner record stores mailing address, phone, and email for correspondence.",
      "The primary contact on a lot receives the owner statement.",
      "Owners without an active lot assignment still appear here — they may be historical.",
    ],
  },
  boardMembers: {
    heading: "Board Members",
    description: "Track current and past board members, their roles, and term dates.",
    tips: [
      "Roles: President, VP, Secretary, Treasurer, Member, At-Large.",
      "Leave Term End blank for current board members.",
      "Past members are shown in a separate section below current board.",
    ],
  },
  renters: {
    heading: "Renters",
    description: "Track tenants renting HOA lots. Useful for contact lists and property management.",
    tips: [
      "Toggle 'Current only' to hide past renters.",
      "Move-Out Date left blank means the renter is active.",
      "Renter info is separate from owner records — lot fees always bill to the owner.",
    ],
  },
  bankAccounts: {
    heading: "Bank Accounts",
    description: "Manage bank accounts linked to the HOA. Typical setup: one Operating checking and one Reserve savings account.",
    tips: [
      "Each account has a fund code (Operating, Reserve, or Special) that drives financial reports.",
      "Opening balance is set under Transactions → Opening Balances.",
      "Account last 4 digits are stored for reference — no full account numbers.",
    ],
  },
  bankImport: {
    heading: "Bank Import — CSV",
    description: "Upload a CSV bank statement downloaded from your bank's online portal.",
    tips: [
      "The app auto-detects column names like Date, Amount, Description.",
      "Adjust the mapping in Step 2 if detection is off.",
      "Already-imported transactions are highlighted as duplicates and skipped.",
      "After import, the column mapping is remembered for that account — next import auto-fills it.",
      "Use Bank → Pending to classify imported transactions.",
    ],
  },
  ofxImport: {
    heading: "OFX / QFX Import",
    description: "Upload an OFX or QFX file downloaded from your bank. OFX provides exact transaction IDs (FITID) for perfect deduplication.",
    tips: [
      "OFX/QFX is available from most US banks under 'Export' or 'Download Transactions'.",
      "Transactions are matched by FITID — importing the same file twice won't create duplicates.",
      "After import, go to Bank → Pending to classify transactions.",
      "Use Undo Import to reverse the last OFX import batch if needed.",
    ],
  },
  bankPending: {
    heading: "Bank Pending",
    description: "Classify imported bank transactions by linking them to income categories or vendor bills.",
    tips: [
      "Click 'Classify' on any transaction to assign it to a category or vendor bill.",
      "Use multi-split to divide one transaction across multiple categories.",
      "'Validate All' posts all classified transactions at once.",
      "'Manual Entry' lets you add a transaction that didn't come from an import.",
      "Filter by bank account using the dropdown when you have multiple accounts.",
    ],
  },
  reconciliations: {
    heading: "Bank Reconciliations",
    description: "Match your book balance to the bank statement — the monthly close that proves your records are accurate.",
    tips: [
      "Enter the bank statement ending balance and date.",
      "Check off each transaction that appears on the statement.",
      "The difference must be zero before you can mark the reconciliation complete.",
      "Completed reconciliations are locked — you can view but not edit them.",
      "Run this after every monthly bank statement arrives.",
    ],
  },
  vendors: {
    heading: "Vendors",
    description: "Directory of companies and contractors paid by the HOA.",
    tips: [
      "Add a vendor before entering their invoices.",
      "Vendor name appears on expense reports and budget-vs-actual.",
      "Inactive vendors are hidden from bill entry but their history is retained.",
    ],
  },
  vendorBills: {
    heading: "Vendor Bills",
    description: "Enter invoices from vendors and record payments against them.",
    tips: [
      "Assign a category to each bill for expense tracking.",
      "Pay a bill using the 'Pay' button — this links to a bank account and records the check or ACH.",
      "Status: OPEN → PARTIAL → PAID as payments are applied.",
      "Use 'VOID' status for cancelled invoices — never delete posted bills.",
    ],
  },
  openingBalances: {
    heading: "Opening Balances",
    description: "Enter starting balances when you first set up the app. Run once per account when going live.",
    tips: [
      "Bank opening balance = your actual bank balance on the cutover date.",
      "Lot opening balance = the amount each lot owed on the cutover date.",
      "Do NOT enter opening balances after you've started posting live transactions.",
      "These are one-time setup entries — they don't repeat each year.",
    ],
  },
  assessments: {
    heading: "Assessments",
    description: "View and manage lot charges — dues, special assessments, late fees, and other charges.",
    tips: [
      "Status flows: OPEN → PARTIAL → PAID as payments are applied.",
      "Use Dues Billing to bulk-post monthly dues to all active lots.",
      "Use Late Fees to find overdue lots and bulk-post late fee charges.",
      "VOID a charge to cancel it without deleting the record.",
    ],
  },
  duesBilling: {
    heading: "Dues Billing",
    description: "Bulk-post monthly (or annual) dues to all active lots in a single operation.",
    tips: [
      "All active lots are checked by default — uncheck any you want to skip.",
      "Enter the amount, description, and due date before posting.",
      "Assessment Date is when the charge is posted; Due Date is the payment deadline.",
      "Review the total (count × amount) at the bottom before confirming.",
    ],
  },
  lateFees: {
    heading: "Late Fees",
    description: "Find lots with overdue balances and bulk-post late fee assessments.",
    tips: [
      "Set the As-Of Date and Minimum Days Overdue, then click 'Find Delinquent Lots'.",
      "Uncheck any lots you want to exclude (e.g., lots with payment arrangements).",
      "Set the fee amount per lot, assessment date, and due date before posting.",
      "Late fees post as LATE_FEE type assessments — they appear on the AR aging report.",
    ],
  },
  resaleFee: {
    heading: "Resale / Transfer Fee",
    description: "Record a resale certificate or transfer fee collected at lot closing.",
    tips: [
      "Select the lot being sold and the bank account where the fee was deposited.",
      "This posts as non-dues income under the 'Resale Fee' category.",
      "Typical fee is set by your HOA CC&Rs — check with your board.",
      "Recent fees are shown at the bottom for reference.",
    ],
  },
  ar: {
    heading: "Accounts Receivable",
    description: "Aging report showing outstanding balances by lot — who owes what and for how long.",
    tips: [
      "Current, 30, 60, and 90+ day buckets help identify delinquent accounts.",
      "Use Late Fees to post charges to overdue accounts.",
      "Click a lot number to jump to its full ledger.",
      "Export to CSV from the DB Admin section in Settings.",
    ],
  },
  deposits: {
    heading: "Deposits",
    description: "Group owner payments into deposit batches — one batch per bank deposit slip.",
    tips: [
      "Create a new batch for each trip to the bank (or ACH settlement date).",
      "Each batch links to a specific bank account.",
      "Post the batch when all payments are added — this applies payments to open assessments.",
      "POSTED batches are locked and included in bank reconciliation.",
    ],
  },
  ownerStatements: {
    heading: "Owner Statements",
    description: "Generate printable account statements for one or all lots. Use your browser's Print → Save as PDF.",
    tips: [
      "Select lots using the checkboxes, or use the 'With Balance' button to select only lots that owe money.",
      "Click 'Generate' to preview all selected statements on screen.",
      "Use the 'Print / Save PDF' button to open your browser print dialog.",
      "In the print dialog, choose 'Save as PDF' to create a file — then email or upload to S3.",
      "Statements include full charge/payment history and current balance.",
    ],
  },
  budgets: {
    heading: "Budgets",
    description: "12-month operating and reserve budget. Enter planned amounts by category per month.",
    tips: [
      "Create one budget per fiscal year (OPERATING fund) and optionally one for RESERVE.",
      "The grid shows 12 months × categories — enter monthly budget amounts.",
      "Budget vs Actual report compares posted expenses to these amounts.",
      "Mark a budget APPROVED once the board adopts it.",
    ],
  },
  transactions: {
    heading: "All Transactions",
    description: "Every posted transaction across all accounts, sorted by date.",
    tips: [
      "Filter by date range, account, or type using the controls at the top.",
      "This is your general ledger — it shows every income and expense entry.",
      "Use Ledger by Account to see a single category's transaction history.",
    ],
  },
  ledgerByAccount: {
    heading: "Ledger by Account",
    description: "View all transactions for a specific income or expense category.",
    tips: [
      "Select an account/category from the dropdown to see its full transaction history.",
      "Use this to verify a specific expense total or trace an unexpected entry.",
      "Running balance is shown for each account.",
    ],
  },
  workflowGuide: {
    heading: "Workflow Guide",
    description: "Step-by-step checklists for routine HOA accounting — monthly cycle, quarter close, year-end, and exceptions.",
    tips: [
      "Each card shows the step number and links to the relevant screen.",
      "The Monthly Cycle tab covers everything you do every month, in order.",
      "Quarter Close and Year-End tabs add extra steps at those intervals.",
      "The Exceptions tab covers non-routine situations (special assessments, write-offs, etc.).",
      "Click 'Print Cheatsheet' for a printer-friendly version of the current tab.",
    ],
  },
  reserveStudy: {
    heading: "Reserve Study",
    description: "Long-term capital reserve planning — inventory assets, project replacement costs, and model funding scenarios.",
    tips: [
      "Enter each major common-area asset under the Assets tab.",
      "Set the Assumptions (inflation rate, investment return, starting balance).",
      "The Funding Plan tab shows the projected year-by-year reserve balance.",
      "Scenarios let you model different annual contribution levels.",
      "Export to CSV or print the report for board meetings.",
    ],
  },
  reserveTransfers: {
    heading: "Reserve Transfers",
    description: "Record fund transfers between the operating and reserve bank accounts.",
    tips: [
      "Use this for the monthly reserve contribution transfer.",
      "Both accounts must be set up under Bank → Accounts.",
      "Transfers appear in the bank ledger for both accounts.",
      "Delete a transfer if entered in error — it does not affect reconciled periods.",
    ],
  },
  editRecords: {
    heading: "Edit Records",
    description: "Correct posted entries — modify payments, non-dues income, and assessments.",
    tips: [
      "Only OPEN and PARTIAL assessments can be edited (PAID/VOID are locked).",
      "Changing an amount on a posted payment affects the running balance immediately.",
      "For complex corrections, use a reversing entry approach instead of editing.",
      "All changes are recorded in the Audit Log.",
    ],
  },
  transactionRules: {
    heading: "Transaction Rules",
    description: "Auto-categorization rules for imported bank transactions. Rules run when you classify in Bank Pending.",
    tips: [
      "CATEGORIZE rules assign an income category to matching transactions.",
      "LINK_EXPENSE rules link matching transactions to a vendor bill.",
      "IGNORE rules skip recurring bank fees or transfers you don't need to classify.",
      "Use the Rule Tester at the bottom to verify a rule matches as expected.",
      "Rules run in priority order — higher confidence rules win ties.",
    ],
  },
  categories: {
    heading: "Chart of Accounts",
    description: "Income and expense categories used across all transaction entry screens.",
    tips: [
      "Each category has a type (Income/Expense/Transfer) and fund code (Operating/Reserve/Special).",
      "System categories (like HOA Dues and Late Fees) cannot be deleted.",
      "The group name is used for grouping on financial reports.",
      "Add custom categories for your specific expenses (e.g., Pool Maintenance).",
      "Deactivate categories you no longer use rather than deleting them.",
    ],
  },
  lotTransfer: {
    heading: "Lot Transfer Wizard",
    description: "Transfer lot ownership when a property sells — closes old ownership records and opens new ones.",
    tips: [
      "Step 1: Select the lot being sold.",
      "Step 2: Review current owners and open assessments — collect outstanding balances before closing.",
      "Step 3: Enter or select the new owner.",
      "Step 4: Confirm — the transfer date closes all existing ownership records and creates new ones.",
      "Open assessments remain on the lot after transfer — the new owner inherits them.",
    ],
  },
  accountingPeriods: {
    heading: "Accounting Periods",
    description: "Lock closed months to prevent accidental backdated entries.",
    tips: [
      "Lock a period after you've reconciled the bank statement for that month.",
      "Locked periods are advisory — they serve as a reminder that the period is closed.",
      "Use 'Lock through last month' to close all months up to the prior month in one click.",
      "Add a note to each period for board meeting dates or audit milestones.",
      "Unlock a period if you need to make a correction (with board approval).",
    ],
  },
  dataImport: {
    heading: "Data Import",
    description: "Bulk import lots, owners, or payments from a CSV spreadsheet.",
    tips: [
      "Choose your import target (Lots, Owners, or Payments) first.",
      "The app auto-detects column names — adjust in the mapping step if needed.",
      "Preview shows which rows will import and which have validation errors.",
      "For Owners, add a 'Lot Number' column to automatically link each owner to their lot.",
      "Payment imports attach to the most recent open deposit batch.",
    ],
  },
  auditLog: {
    heading: "Audit Log",
    description: "Read-only history of every data change made in the app — who changed what and when.",
    tips: [
      "Filter by table name, action type (INSERT/UPDATE/DELETE), or user email.",
      "Click 'Show details' on any row to see the before and after values.",
      "Changed fields are highlighted in yellow with red (old) and green (new) values.",
      "The audit log cannot be edited or deleted — it is the permanent paper trail.",
    ],
  },
  users: {
    heading: "Users",
    description: "Manage app user accounts. Admins have full access; regular users have read-only access to most screens.",
    tips: [
      "Add a user with their email and a temporary password — they can change it in Profile.",
      "Admin role: full read/write access including Settings and Admin menu items.",
      "Standard role: read access to most screens, limited write access.",
      "Deactivate rather than delete users to preserve their audit trail entries.",
    ],
  },
  settings: {
    heading: "Settings",
    description: "Organization configuration, database path, S3 backup, and database maintenance tools.",
    tips: [
      "Organization name and fiscal year settings affect report headers.",
      "Database File path points to the SQLite file — restart the app after changing it.",
      "S3 Backup requires ~/.hoa-system/tauri/s3_config.json with AWS credentials.",
      "VACUUM reclaims space and rebuilds indexes — run monthly for best performance.",
      "Integrity Check verifies the database has no corruption — run if the app behaves unexpectedly.",
      "Export Table downloads any table as a CSV for external analysis.",
    ],
  },
  announcements: {
    heading: "Announcements",
    description: "Post notices that appear as banner messages on the dashboard for all users.",
    tips: [
      "Severity levels: Info (blue), Warning (amber), Urgent (red).",
      "Active announcements appear on the dashboard until you deactivate them.",
      "Use for HOA meeting reminders, payment deadlines, or urgent notices.",
      "Announcements are not emailed — they only appear inside the app.",
    ],
  },
  profile: {
    heading: "Profile",
    description: "Your personal account settings — display name and password.",
    tips: [
      "Change your display name to how you want to appear in the audit log.",
      "Use a strong password — there is no password reset feature.",
      "Your role (admin/standard) is set by an admin user in the Users screen.",
    ],
  },
  reports: {
    heading: "Reports",
    description: "Financial and operational reports. Select a report from the dropdown, set parameters, and click Run.",
    tips: [
      "Date ranges default to Jan 1 of the current year through today.",
      "Year-based reports default to the current calendar year.",
      "Use the print button in your browser to save any report as a PDF.",
      "For detailed owner history, use Owner Statements instead of the Owner Ledger report.",
    ],
  },
  coaWizard: {
    heading: "Chart of Accounts Wizard",
    description: "Answer a few questions to automatically generate a starter chart of accounts for your HOA.",
    tips: [
      "Only use this wizard on a new setup — running it on an existing chart will add duplicate categories.",
      "Answer Yes to Reserve Fund if you maintain a separate savings account for capital repairs.",
      "The wizard creates standard HOA categories; you can add custom ones afterward.",
    ],
  },
};
