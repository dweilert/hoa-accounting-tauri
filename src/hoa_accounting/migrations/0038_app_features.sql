-- App Feature Catalog: searchable index of pages and sub-page features.
-- Queried by the global search bar alongside live data results.
-- workflow_cards are also searched live from that table (no duplication here).
--
-- category values: Money In, Money Out, Month-End, Reserve Fund, Look It Up,
--                  Setup, Guides, Admin, Settings

BEGIN;

CREATE TABLE app_features (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    keywords    TEXT    NOT NULL DEFAULT '',
    href        TEXT    NOT NULL,
    category    TEXT    NOT NULL DEFAULT '',
    icon        TEXT    NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 100
);

-- ── HOME ──────────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Dashboard',
  'Main dashboard with quick-action cards, alerts, and account summary.',
  'home dashboard main overview summary quick action cards alerts',
  '/', 'Home', '🏠', 10),

 ('Reports',
  'Run financial reports: budget vs actual, income statement, balance sheet, AR aging.',
  'reports financial statements income balance sheet budget actual aging print export',
  '/reports', 'Home', '📊', 20);

-- ── MONEY IN ─────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Charge Annual Dues / Bill Assessments',
  'Post monthly or annual dues assessments to all active lots at once.',
  'bill dues charge assessments annual monthly lot owners billing post assess',
  '/dues-billing', 'Money In', '🏠', 30),

 ('Charge Late Fees',
  'Run a late fee sweep — post late fee charges to all past-due owners at once.',
  'late fee sweep charge past due delinquent penalty billing post',
  '/late-fees', 'Money In', '⏰', 40),

 ('Other Charges / Special Assessments',
  'Bill a special assessment or one-off charge to individual lots or all owners.',
  'special assessment charge bill individual lot one-off extra fee',
  '/bill-assessments', 'Money In', '📋', 50),

 ('Resale Certificate Fee',
  'Record a resale certificate fee payment when a lot is sold.',
  'resale certificate fee sale lot transfer closing',
  '/resale-certificate', 'Money In', '🔖', 60),

 ('Other Income / Non-Dues Income',
  'Record interest income, rental income, or any income that is not owner dues.',
  'income interest non-dues rental other income post record batch',
  '/income-batch', 'Money In', '💰', 70),

 ('Record Payments / Post Deposits',
  'Record owner payments — checks, ACH transfers, and online payments.',
  'payments deposits record post checks ACH owner pay receipt bank',
  '/deposit-batch', 'Money In', '💳', 80),

 ('Who Owes Money / AR by Lot',
  'See which owners have open balances. Shows amount owed per lot.',
  'AR accounts receivable who owes balance due delinquent lot owner outstanding',
  '/ar-lots', 'Money In', '📬', 90),

 ('Past Due Accounts / Delinquency Report',
  'Delinquency report listing all owners past due with aging buckets.',
  'delinquency past due aging 30 60 90 days overdue report collection',
  '/delinquency-report', 'Money In', '⚠️', 100),

 ('Owner Statements / Batch PDF',
  'Generate and publish monthly owner ledger statements as PDFs.',
  'owner statements PDF publish batch ledger statement generate mail send',
  '/batch-pdf', 'Money In', '📨', 110);

-- ── MONEY OUT ────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Pay a Vendor Bill',
  'Enter vendor invoices and record check or ACH payments against open bills.',
  'vendor bill pay invoice check ACH payment accounts payable expense record',
  '/vendor-bills', 'Money Out', '🧾', 120),

 ('Enter a New Vendor Bill',
  'Record a new invoice from a vendor — landscaping, utilities, management fees, etc.',
  'vendor bill new invoice enter record landscaping utilities management expense',
  '/vendor-bill-new', 'Money Out', '📝', 125),

 ('Reserve Fund Transfer',
  'Move the monthly budgeted amount from the Operating account to the Reserve account.',
  'reserve fund transfer operating contribution monthly budgeted move',
  '/reserve-transfer-new', 'Money Out', '🏦', 130);

-- ── MONTH-END ────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Reconcile Bank Account / Bank Reconciliation',
  'Match your book balance to the bank statement. Clear transactions, find differences.',
  'reconcile bank reconciliation statement balance clear match month end close difference',
  '/reconciliation-new', 'Month-End', '🏦', 140),

 ('Lock the Month / Accounting Periods',
  'Close an accounting period to prevent changes. View open and closed periods.',
  'close period lock month accounting period close books prevent changes',
  '/accounting-periods', 'Month-End', '🔒', 150),

 ('Manual Adjustments / Journal Entry',
  'Post a manual journal entry to the general ledger.',
  'journal entry manual adjustment debit credit GL post reclassify correct reverse accrual',
  '/journal-entry-new', 'Month-End', '✏️', 160),

 ('Year-End Close',
  'Close the fiscal year — post closing entries and lock all periods for the year.',
  'year end close fiscal year closing entries lock annual finalize books',
  '/year-end-close', 'Month-End', '🏁', 170);

-- ── RESERVE FUND ─────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Reserve Study Summary',
  'Overview of the reserve fund — current balance, funding level, and health indicators.',
  'reserve study summary fund balance health funding level percent funded',
  '/reserve-study', 'Reserve Fund', '📐', 180),

 ('Reserve Asset Inventory',
  'List of all reserve components with useful life, condition, and replacement cost.',
  'reserve assets inventory components useful life replacement cost condition items',
  '/reserve-study/assets', 'Reserve Fund', '🗂️', 190),

 ('Reserve Funding Plan',
  'Year-by-year schedule of reserve contributions and projected expenditures.',
  'reserve funding plan schedule contributions expenditure year projection',
  '/reserve-study/plan', 'Reserve Fund', '📅', 200),

 ('Reserve Scenarios',
  'Model different funding levels and contribution amounts for the reserve fund.',
  'reserve scenarios model what-if funding contribution amount plan alternative',
  '/reserve-study/scenarios', 'Reserve Fund', '🔮', 210),

 ('Reserve Assumptions',
  'Set inflation rate, interest rate, and other assumptions for the reserve study.',
  'reserve assumptions inflation interest rate study settings configuration',
  '/reserve-study/assumptions', 'Reserve Fund', '⚙️', 220);

-- ── LOOK IT UP ───────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Transaction History / All Transactions',
  'Browse every posted transaction in the general ledger. Filter by date, account, or type.',
  'transactions history all ledger GL browse filter date account type posted',
  '/all-transactions', 'Look It Up', '📋', 230),

 ('Account Detail / Account Ledger',
  'View all transactions for a specific account. Drill into any GL account.',
  'account ledger detail transactions specific account drill GL balance',
  '/account-ledger', 'Look It Up', '📒', 240);

-- ── SETUP ────────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Homeowners',
  'Add, edit, and manage homeowner records.',
  'homeowners owners add edit manage people members residents',
  '/owners', 'Setup', '👤', 250),

 ('Properties / Lots',
  'Manage lot and property records — addresses, ownership history.',
  'lots properties addresses ownership history parcels units',
  '/lots', 'Setup', '🏡', 260),

 ('Renters',
  'Track renters associated with lots.',
  'renters tenants rental units lots property management',
  '/renters', 'Setup', '🔑', 270),

 ('Vendors',
  'Add and manage vendor records — landscapers, utilities, management companies.',
  'vendors suppliers contractors landscaping utilities management add edit',
  '/vendors', 'Setup', '🏢', 280),

 ('Bill Templates',
  'Create reusable bill templates for recurring vendor invoices.',
  'bill templates vendor recurring invoice template reuse standard',
  '/bill-templates', 'Setup', '📄', 290),

 ('Bank Accounts',
  'Set up operating and reserve bank accounts linked to GL accounts.',
  'bank accounts operating reserve checking savings linked GL setup',
  '/bank-accounts', 'Setup', '🏦', 300),

 ('Budget',
  'Enter account-level budget figures for the fiscal year.',
  'budget annual figures account level fiscal year spending plan',
  '/budgets', 'Setup', '📊', 310),

 ('Chart of Accounts / Account Setup',
  'View and manage the chart of accounts. Add or edit GL accounts.',
  'chart of accounts COA GL general ledger account setup add edit type fund',
  '/accounts', 'Setup', '📑', 320),

 ('COA Setup Wizard',
  'Step-by-step interview to build your chart of accounts from scratch.',
  'wizard setup interview chart of accounts COA new setup guided questions',
  '/accounts/wizard', 'Setup', '🧙', 325);

-- ── GUIDES ───────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Workflow Guide',
  'Step-by-step playbook for monthly, quarter-end, year-end, and exception workflows.',
  'workflow guide playbook monthly quarterly year-end steps how to process',
  '/workflow-guide', 'Guides', '📅', 330),

 ('Quick Reference',
  'Cheat sheet of common accounting entries and HOA-specific bookkeeping rules.',
  'quick reference cheat sheet guide help accounting entries rules HOA',
  '/quick-reference', 'Guides', '⚡', 340);

-- ── ADMIN ────────────────────────────────────────────────────────────────────

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Preferences / System Settings',
  'Change HOA name, default annual dues amount, and UI color theme.',
  'preferences settings system name dues default annual color theme palette appearance',
  '/system-settings', 'Admin', '⚙️', 350),

 ('Dashboard Layout',
  'Add, remove, and reorder the quick-action cards shown on the dashboard.',
  'dashboard layout customize cards quick action add remove reorder configure',
  '/dashboard-config', 'Admin', '🎛️', 360),

 ('Starting Balances / Opening Balances',
  'Enter opening balances for accounts when setting up the system for the first time.',
  'starting opening balances initial setup beginning balance migration convert',
  '/opening-balances', 'Admin', '🔢', 370),

 ('Activity Log / Audit Log',
  'View a log of all changes made in the system — who changed what and when.',
  'activity audit log changes history who changed what when user actions',
  '/audit-log', 'Admin', '📋', 380),

 ('Export / Backup Database',
  'Download a full backup of the database or export data.',
  'export backup database download copy archive data restore',
  '/admin/database', 'Admin', '💾', 390),

 ('Import Data',
  'Import owner, lot, or transaction data from a CSV or spreadsheet.',
  'import data CSV spreadsheet upload bulk owners lots transactions migrate',
  '/import', 'Admin', '📥', 400),

 ('Wizard Catalog',
  'Manage the questions and account options shown in the COA Setup Wizard.',
  'wizard catalog admin manage questions options accounts COA setup interview',
  '/admin/wizard-catalog', 'Admin', '🗂️', 410),

 ('Workflow Editor',
  'Add, edit, move, and reorder cards in the Workflow Guide.',
  'workflow editor admin manage cards sections tabs guide edit customize',
  '/admin/workflow-guide', 'Admin', '✏️', 420),

 ('Users',
  'Manage user accounts and access to the system.',
  'users accounts access manage add remove login credentials',
  '/admin/users', 'Admin', '👥', 430),

 ('Role Overrides',
  'Override role-based access permissions for individual users.',
  'roles permissions access override user role admin read write',
  '/admin/role-overrides', 'Admin', '🔐', 440);

-- ── SUB-PAGE FEATURES (Settings) ─────────────────────────────────────────────
-- These point to a specific section within a page via the anchor column.
-- The href includes the anchor so browsers scroll directly there.

INSERT INTO app_features (name, description, keywords, href, category, icon, sort_order) VALUES
 ('Color Theme / UI Appearance',
  'Choose a color palette: Warm, Slate, Sage, Ocean, Sand, or Dusk.',
  'color theme appearance palette warm slate sage ocean sand dusk dark light UI look',
  '/system-settings#theme', 'Settings', '🎨', 500),

 ('Default Annual Dues Amount',
  'Set the default dues amount that pre-fills when billing owners each month.',
  'default dues amount annual monthly billing assessment pre-fill dollar amount',
  '/system-settings#dues', 'Settings', '💲', 510),

 ('HOA Name / Legal Name',
  'Change the full legal name and abbreviated display name of the HOA.',
  'HOA name legal name abbreviated display organization association rename',
  '/system-settings#identity', 'Settings', '🏛️', 520),

 ('Add a New Account / Chart of Accounts',
  'Add a new GL account to the chart of accounts manually.',
  'add new account GL chart of accounts manual create income expense asset liability',
  '/accounts', 'Settings', '➕', 530),

 ('Close an Accounting Period',
  'Lock a month so no entries can be added or changed.',
  'close period lock month accounting period prevent changes books finalize',
  '/accounting-periods', 'Settings', '🔒', 540),

 ('Open a New Accounting Period',
  'Create a new accounting period to begin posting transactions for a month.',
  'open new accounting period month create start January fiscal',
  '/accounting-period-new', 'Settings', '📅', 550),

 ('Set Fiscal Year',
  'Configure which month the fiscal year starts.',
  'fiscal year start month configuration settings annual period',
  '/system-settings', 'Settings', '📆', 555),

 ('Write Off a Bad Debt',
  'Journal entry to remove an uncollectable owner balance from AR.',
  'write off bad debt uncollectable owner balance AR remove journal entry',
  '/journal-entry-new', 'Settings', '✏️', 560),

 ('Reverse a Journal Entry',
  'Post a reversing entry to undo a prior journal entry.',
  'reverse reversal journal entry undo correct prior posting',
  '/journal-entry-new', 'Settings', '↩️', 570),

 ('Reclassify an Expense / Coding Error',
  'Fix an expense posted to the wrong account using a reversing journal entry.',
  'reclassify expense coding error wrong account fix correct reverse journal entry',
  '/journal-entry-new', 'Settings', '🔁', 580),

 ('Accrual Entry',
  'Post an accrual for an expense incurred but not yet billed.',
  'accrual expense incurred not billed month end estimate accrue',
  '/journal-entry-new', 'Settings', '📝', 590),

 ('AR Aging / Who Owes What',
  'View balances owed per lot, grouped by how many days overdue.',
  'AR aging balance owed due lot 30 60 90 days delinquent receivable',
  '/ar-lots', 'Settings', '📬', 600);

COMMIT;
