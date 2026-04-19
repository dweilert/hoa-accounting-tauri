-- Workflow Guide Catalog: DB-driven content for the Workflow Guide.
-- Replaces hardcoded Jinja2 data with editable DB records.
--
-- workflow_tabs     — top-level tab panels (Monthly Cycle, Quarter Close, etc.)
-- workflow_sections — named sections within each tab (Billing, Cash Receipts, etc.)
-- workflow_cards    — individual step cards within sections

BEGIN;

CREATE TABLE workflow_tabs (
    id          INTEGER PRIMARY KEY,
    tab_key     TEXT    NOT NULL UNIQUE,
    icon        TEXT    NOT NULL DEFAULT '',
    label       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 100,
    is_system   INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE workflow_sections (
    id          INTEGER PRIMARY KEY,
    tab_id      INTEGER NOT NULL REFERENCES workflow_tabs(id),
    label       TEXT    NOT NULL,
    tip_text    TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 100,
    is_system   INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE workflow_cards (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES workflow_sections(id),
    num_label   TEXT    NOT NULL DEFAULT '',
    icon        TEXT    NOT NULL DEFAULT '',
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    href        TEXT    NOT NULL DEFAULT '#',
    link_label  TEXT    NOT NULL DEFAULT '',
    color       TEXT    NOT NULL DEFAULT 'slate',
    sort_order  INTEGER NOT NULL DEFAULT 100,
    is_system   INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Tabs ───────────────────────────────────────────────────────────────────

INSERT INTO workflow_tabs (id, tab_key, icon, label, description, sort_order) VALUES
 (1, 'monthly',     '📅', 'Monthly Cycle',   'Run these steps every month, roughly in order. Special assessments, late fees, and one-off adjustments live in the Exceptions tab — only use those when needed.', 10),
 (2, 'quarter',     '📊', 'Quarter Close',    'After completing the regular monthly cycle for March, June, September, or December, run these additional quarter-end steps.', 20),
 (3, 'yearend',     '🏁', 'Year-End',         'Runs December–January. Complete the final monthly and quarter-close first, then work through these year-end steps before opening the new fiscal year.', 30),
 (4, 'adjustments', '⚡', 'Exceptions',       'These workflows don''t happen every month — only run them when the situation calls for it. Keeping these out of the Monthly Cycle prevents confusion about what''s routine vs. occasional.', 40);

-- ── Sections ───────────────────────────────────────────────────────────────

INSERT INTO workflow_sections (id, tab_id, label, tip_text, sort_order) VALUES
 -- Monthly
 (10, 1, 'Billing',         '', 10),
 (11, 1, 'Cash Receipts',   '', 20),
 (12, 1, 'Vendor Payables', '', 30),
 (13, 1, 'Month-End Close',
  'Step 1 can be done as early as the 1st of the month. Steps 2–5 happen throughout the month as payments and bills arrive. Steps 6–8 wait until you have the bank statement in hand, usually by the 10th of the following month. For special assessments or late fees, use the Exceptions tab.',
  40),
 -- Quarter
 (20, 2, 'Receivables Review',  '', 10),
 (21, 2, 'Financial Reporting', '', 20),
 (22, 2, 'Reserve Health',
  'Board packet tip: Export the Budget vs Actual and Ledger by Account reports from the Reports page and attach them to your quarterly board meeting agenda. Most boards want to see these within 15 days of quarter end.',
  30),
 -- Year-End
 (30, 3, 'Wrap Up the Closing Year', '', 10),
 (31, 3, 'Plan the New Year',        '', 20),
 (32, 3, 'Open the New Year',
  'Timeline: Aim to complete Y1–Y4 by January 15. Steps Y5–Y8 can run in parallel with the first weeks of January. Present the new budget and dues to the board before billing owners in Y10.',
  30),
 -- Exceptions
 (40, 4, 'Special Assessments',
  'Accounting: A special assessment posts DR Accounts Receivable / CR Assessment Income — identical to monthly dues, just a different description. The board resolution is your paper trail; keep it on file.',
  10),
 (41, 4, 'Late Fee Sweep',
  'Key rule: Income is recognized at billing time (step 2). Collecting the fee in step 4 reduces AR — it does not post new income. This is the most common late-fee bookkeeping mistake.',
  20),
 (42, 4, 'Owner Write-Off',
  'Journal entry: Debit Bad Debt Expense (expense account), Credit Accounts Receivable (asset account) for the exact balance being written off. This removes the receivable from your books without touching cash.',
  30),
 (43, 4, 'Coding Error — Reclassify an Expense',
  'Why two entries? Always reverse-then-correct rather than editing the original. This preserves the audit trail — the Audit Log shows who changed what and when. Editing posted entries breaks your reconciliation history.',
  40),
 (44, 4, 'Accrual — Expense Incurred but Not Yet Billed',
  'Common accruals for HOAs: management fee not yet invoiced, annual insurance premium split across months, or landscaping done in December but billed in January. Accruals match the expense to the month it was incurred — important for accurate budget-vs-actual reporting.',
  50),
 (45, 4, 'Income Tax Payment',
  'Why HOAs pay tax on interest: Most HOAs are exempt from federal income tax on dues, assessments, and late fees. But interest income and income from non-members is typically taxable. Consult your CPA each year.',
  60),
 (46, 4, 'ACH & Auto-Drafts',
  'At reconciliation: Both auto-drafts and owner ACH payments show up on the bank statement exactly like checks and deposits. Match them the same way — your book entry date should match the bank settlement date.',
  70),
 (47, 4, 'Reserve Fund — When to Use a Journal Entry',
  'Rule of thumb: Use the Reserve Transfer workflow for routine monthly contributions. Use a manual Journal Entry only for one-time items like interest income, insurance reimbursements, or corrections. Never move reserve funds to operating without a board resolution.',
  80);

-- ── Cards ──────────────────────────────────────────────────────────────────

-- Monthly — Billing
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (100, 10, '1', '🏠', 'Bill Dues', 'Post monthly assessment for every active lot.', '/dues-billing', 'Bill Dues', 'blue', 10);

-- Monthly — Cash Receipts
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (110, 11, '2', '💳', 'Post Payments', 'Record all owner payments — checks, ACH auto-deposits, and online payments. Use ''ACH'' or the bank ref number in the Check # / Ref field.', '/deposit-batch', 'Deposits', 'green', 10),
 (111, 11, '3', '💰', 'Other Income', 'Interest, resale fees, or any non-dues income.', '/income-batch', 'Non-Dues Income', 'green', 20);

-- Monthly — Vendor Payables
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (120, 12, '4', '🧾', 'Enter Bills', 'Record invoices — landscaping, management, utilities, etc. For auto-drafts enter the bill when the invoice arrives, or on the draft date if no invoice.', '/vendor-bill-new', 'Vendor Bills', 'rose', 10),
 (121, 12, '5', '💸', 'Pay Bills', 'Record check or ACH payment against open bills. Use ''ACH'' or ''AUTO-DRAFT'' as the check number for electronic payments.', '/vendor-bills', 'Pay Bills', 'rose', 20);

-- Monthly — Month-End Close
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (130, 13, '6', '🏦', 'Reconcile Bank', 'Match your book balance to the bank statement.', '/reconciliation-new', 'Reconcile', 'teal', 10),
 (131, 13, '7', '📨', 'Owner PDFs', 'Generate and publish monthly owner ledger statements.', '/batch-pdf', 'Publish PDFs', 'teal', 20),
 (132, 13, '8', '🔒', 'Close Period', 'Lock the accounting period so no entries can be changed.', '/accounting-periods', 'Periods', 'slate', 30);

-- Quarter — Receivables Review
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (200, 20, 'Q1', '📬', 'AR Aging Review', 'Check AR by Lot for balances 30/60/90+ days overdue.', '/ar-lots', 'AR by Lot', 'blue', 10),
 (201, 20, 'Q2', '⚖️', 'Collection Follow-up', 'Document outreach for delinquent owners per HOA policy.', '#', 'AR Detail', 'amber', 20);

-- Quarter — Financial Reporting
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (210, 21, 'Q3', '📊', 'Budget vs Actual', 'Compare YTD spending to the approved budget.', '/reports', 'Reports', 'violet', 10),
 (211, 21, 'Q4', '📈', 'All Transactions', 'Scan the full GL for any unexpected or miscoded entries.', '/all-transactions', 'All Transactions', 'violet', 20),
 (212, 21, 'Q5', '📒', 'Ledger by Account', 'Spot-check key accounts: cash, AP, dues income, reserves.', '/account-ledger', 'Account Ledger', 'violet', 30);

-- Quarter — Reserve Health
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (220, 22, 'Q6', '🏦', 'Reserve Transfer', 'Move budgeted monthly amount from Operating to Reserve account.', '/reserve-transfer-new', 'Reserve Transfers', 'teal', 10),
 (221, 22, 'Q7', '📐', 'Reserve Study Check', 'Review funding plan vs actual reserve balance.', '/reserve-study', 'Reserve Study', 'teal', 20);

-- Year-End — Wrap Up
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (300, 30, 'Y1', '🔍', 'Final AR Sweep', 'Confirm all owner payments posted; identify write-offs if any.', '/ar-lots', 'AR by Lot', 'blue', 10),
 (301, 30, 'Y2', '🧾', 'Clear Open Bills', 'Pay or void any outstanding vendor bills before year-end.', '/vendor-bills', 'Vendor Bills', 'rose', 20),
 (302, 30, 'Y3', '📋', 'Verify All Periods', 'All 12 accounting periods must be closed before year-end close.', '/accounting-periods', 'Periods', 'slate', 30),
 (303, 30, 'Y4', '🏁', 'Year-End Close', 'Post closing journal entries and lock the fiscal year.', '/year-end-close', 'Year-End Close', 'violet', 40);

-- Year-End — Plan the New Year
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (310, 31, 'Y5', '📐', 'Update Reserve Study', 'Refresh component costs, useful life, and funding plan.', '/reserve-study', 'Reserve Study', 'teal', 10),
 (311, 31, 'Y6', '📊', 'Set New Budget', 'Enter account-level budget figures for the new fiscal year.', '/budgets', 'Budgets', 'violet', 20),
 (312, 31, 'Y7', '💲', 'Set New Dues', 'Update default annual dues in System Settings.', '/system-settings', 'System Settings', 'amber', 30),
 (313, 31, 'Y8', '📦', 'Backup Database', 'Download a full database backup before the new year begins.', '/admin/database', 'Database', 'slate', 40);

-- Year-End — Open the New Year
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (320, 32, 'Y9',  '📅', 'Open New Period', 'Create January accounting period for the new fiscal year.', '/accounting-period-new', 'New Period', 'green', 10),
 (321, 32, 'Y10', '🏠', 'Bill January Dues', 'Post the first dues billing of the new year.', '/dues-billing', 'Bill Dues', 'green', 20),
 (322, 32, 'Y11', '📨', 'Notify Owners', 'Publish December statements and new-year dues notice via PDF.', '/batch-pdf', 'Publish PDFs', 'green', 30);

-- Exceptions — Special Assessments
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (400, 40, '1', '🗳️', 'Board Approval', 'Obtain board resolution authorizing the special assessment — amount, purpose, and due date.', '#', 'Document only', 'amber', 10),
 (401, 40, '2', '📋', 'Bill All or Select Lots', 'Use ''Bill All'' for a flat amount across every lot, or enter individual amounts per lot.', '/bill-assessments', 'Bill Assessments', 'blue', 20),
 (402, 40, '3', '💳', 'Post Payments', 'As owners pay, record deposits and apply to the open special assessment charge.', '/deposit-batch', 'Deposits', 'green', 30),
 (403, 40, '4', '📬', 'Follow Up on Overdue', 'Check AR by Lot after the due date — treat unpaid special assessments the same as overdue dues.', '/ar-lots', 'AR by Lot', 'rose', 40);

-- Exceptions — Late Fee Sweep
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (410, 41, '1', '📬', 'Review AR Aging', 'Check AR by Lot to identify which owners are past due by your policy threshold (e.g. 30 days).', '/ar-lots', 'AR by Lot', 'blue', 10),
 (411, 41, '2', '⏰', 'Run Late Fee Sweep', 'Posts DR Accounts Receivable / CR Late Fee Income per delinquent owner. Income is recognized now.', '/late-fees', 'Late Fees', 'amber', 20),
 (412, 41, '3', '📨', 'Notify Owners', 'Publish updated owner statements so each owner sees the late fee charge.', '/batch-pdf', 'Publish PDFs', 'teal', 30),
 (413, 41, '4', '💳', 'Post Payment if Received', 'When the owner pays, record it via Deposits — this reduces AR, it does not post new income.', '/deposit-batch', 'Deposits', 'green', 40),
 (414, 41, '5', '🗳️', 'Waiver if Board Approves', 'Reversing JE: DR Late Fee Income / CR Accounts Receivable. Attach the board resolution.', '/journal-entry-new', 'New JE', 'rose', 50);

-- Exceptions — Owner Write-Off
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (420, 42, '1', '📬', 'Age the Balance', 'Confirm the amount is genuinely uncollectable — typically 90+ days with no payment or response.', '/ar-lots', 'AR by Lot', 'blue', 10),
 (421, 42, '2', '🗳️', 'Board Approval', 'Obtain written board approval to write off the balance. File the resolution in your records.', '#', 'Document only', 'amber', 20),
 (422, 42, '3', '✏️', 'Journal Entry', 'DR Bad Debt Expense / CR Accounts Receivable for the approved amount.', '/journal-entry-new', 'New JE', 'rose', 30),
 (423, 42, '4', '📋', 'Note on Account', 'Post a memo assessment of $0 with a description noting the write-off date and board resolution.', '/bill-assessments', 'Bill Assessments', 'slate', 40);

-- Exceptions — Coding Error
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (430, 43, '1', '🔍', 'Find the Entry', 'Locate the original journal entry in All Transactions or Ledger by Account.', '/all-transactions', 'All Transactions', 'blue', 10),
 (431, 43, '2', '✏️', 'Reversing JE', 'Post a new JE that is the mirror image of the original — same amount, accounts swapped.', '/journal-entry-new', 'New JE', 'rose', 20),
 (432, 43, '3', '✏️', 'Correcting JE', 'Post another JE with the correct accounts. Use a memo that references the entry being corrected.', '/journal-entry-new', 'New JE', 'green', 30),
 (433, 43, '4', '🔒', 'Verify Balance', 'Check the Ledger by Account for both old and new accounts to confirm the reclassification netted to zero.', '/account-ledger', 'Account Ledger', 'slate', 40);

-- Exceptions — Accrual
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (440, 44, '1', '✏️', 'Accrual JE', 'At month-end, DR the expense account, CR Accrued Liabilities for the estimated amount.', '/journal-entry-new', 'New JE', 'amber', 10),
 (441, 44, '2', '✏️', 'Reversal JE', 'On the 1st of the next month, post the exact reverse: DR Accrued Liabilities, CR Expense.', '/journal-entry-new', 'New JE', 'rose', 20),
 (442, 44, '3', '🧾', 'Enter the Bill', 'When the actual invoice arrives, enter it as a normal Vendor Bill.', '/vendor-bill-new', 'Vendor Bills', 'green', 30);

-- Exceptions — Income Tax Payment
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (450, 45, '1', '✅', 'Confirm Income Posted', 'Verify the interest income journal entry is already posted. Income was recognized when the bank credited it — this tax payment is a separate expense.', '/all-transactions', 'All Transactions', 'blue', 10),
 (451, 45, '2', '📒', 'Add Tax Expense Account', 'If you don''t have one, add ''Income Tax Expense'' to the Chart of Accounts (type: Expense, fund: OPERATING).', '/accounts', 'Chart of Accounts', 'slate', 20),
 (452, 45, '3', '🏢', 'Set Up Tax Vendor', 'Add the IRS and/or your state taxing authority as a vendor if not already in the system.', '/vendors', 'Vendors', 'slate', 30),
 (453, 45, '4', '🧾', 'Enter the Vendor Bill', 'Vendor = IRS (or state). Expense account = Income Tax Expense. Amount = tax owed. Invoice # = your tax return or notice number.', '/vendor-bill-new', 'Vendor Bills', 'rose', 40),
 (454, 45, '5', '💸', 'Pay the Bill', 'Record the check payment against the open bill. Enter the check number for the paper trail.', '/vendor-bills', 'Pay Bills', 'rose', 50),
 (455, 45, '6', '📁', 'File the Return', 'Attach a copy of the filed return to your HOA records. The paid bill in the system is your books entry; the return is your legal filing.', '#', 'Document only', 'amber', 60);

-- Exceptions — ACH & Auto-Drafts
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (460, 46, '', '🏦', 'Auto-Draft Bills (Outgoing ACH)',
  'If invoice arrives before draft: enter the vendor bill when it arrives; on the draft date go to Pay Bills and use ACH or AUTO-DRAFT as the check number. If found at reconciliation: enter the bill and payment together on the draft date. Recurring monthly: same process every month.',
  '/vendor-bill-new', 'Enter Vendor Bill', 'teal', 10),
 (461, 46, '', '💳', 'Owner ACH Payments (Incoming)',
  'Owner auto-pays via their bank''s bill pay or ACH. Record it on the Deposits page — select the owner lot, enter the amount, put ACH or the bank confirmation number in the Check # / Ref field. Use the settlement date shown in online banking, not the date the owner initiated it.',
  '/deposit-batch', 'Post Payments', 'green', 20);

-- Exceptions — Reserve Fund
INSERT INTO workflow_cards (id, section_id, num_label, icon, title, description, href, link_label, color, sort_order) VALUES
 (470, 47, '1', '💸', 'Reserve Spending', 'A reserve component is repaired or replaced. Pay the vendor bill against the Reserve fund expense account.', '/vendor-bill-new', 'Vendor Bills', 'rose', 10),
 (471, 47, '2', '🏦', 'Reserve Transfer', 'Move the budgeted monthly contribution from Operating → Reserve bank account.', '/reserve-transfer-new', 'Reserve Transfers', 'teal', 20),
 (472, 47, '3', '✏️', 'Interest Earned', 'Bank interest credited to the reserve account: DR Reserve Cash, CR Interest Income.', '/journal-entry-new', 'New JE', 'green', 30),
 (473, 47, '4', '📐', 'Update Study', 'After a major expenditure, update the Reserve Study component.', '/reserve-study', 'Reserve Study', 'violet', 40);

COMMIT;
