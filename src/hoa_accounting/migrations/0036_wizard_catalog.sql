-- Wizard Catalog: DB-driven wizard options for the COA Interview Wizard.
-- Replaces wizard_config.py as the source of truth; that file now only seeds.
--
-- wizard_groups  — named groups within each step (mainly Step 4 collapsible groups)
-- wizard_options — individual checkbox options shown to the user
-- wizard_option_accounts — accounts created when an option is checked
--
-- is_system = 1  → shipped with the product; user may deactivate but not delete via UI
-- is_always = 1  → no checkbox, always included (Step 1 core operating accounts)
-- is_reserve_account = 1 → linked via Step 3 amenity's reserve_accounts list

BEGIN;

-- ── Tables ─────────────────────────────────────────────────────────────────

CREATE TABLE wizard_groups (
    id          INTEGER PRIMARY KEY,
    step_number INTEGER NOT NULL,
    group_id    TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 100,
    is_system   INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 1,
    UNIQUE (step_number, group_id)
);

CREATE TABLE wizard_options (
    id          INTEGER PRIMARY KEY,
    step_number INTEGER NOT NULL,
    group_id    TEXT    NOT NULL,
    option_id   TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 100,
    is_system   INTEGER NOT NULL DEFAULT 1,
    is_active   INTEGER NOT NULL DEFAULT 1,
    is_always   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (step_number, option_id)
);

CREATE TABLE wizard_option_accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wizard_option_id INTEGER NOT NULL REFERENCES wizard_options(id) ON DELETE CASCADE,
    account_number   TEXT    NOT NULL,
    account_name     TEXT    NOT NULL,
    account_type     TEXT    NOT NULL,
    fund_code        TEXT    NOT NULL DEFAULT 'OPERATING',
    group_code       TEXT    NOT NULL DEFAULT '',
    is_bank_account  INTEGER NOT NULL DEFAULT 0,
    description      TEXT    NOT NULL DEFAULT '',
    is_reserve_account INTEGER NOT NULL DEFAULT 0
);

-- ── Groups ─────────────────────────────────────────────────────────────────

INSERT INTO wizard_groups (id, step_number, group_id, label, sort_order) VALUES
 (10, 1, 'funds',        'Funds',                             0),
 (20, 2, 'income',       'Income Sources',                    0),
 (30, 3, 'amenities',    'Amenities',                         0),
 (40, 4, 'admin',        'Administration & Management',      10),
 (41, 4, 'professional', 'Professional Services',            20),
 (42, 4, 'insurance',    'Insurance',                        30),
 (43, 4, 'landscaping',  'Landscaping & Grounds',            40),
 (44, 4, 'utilities',    'Utilities — Common Areas',         50),
 (45, 4, 'exterior',     'Exterior Maintenance & Repairs',   60),
 (46, 4, 'mechanical',   'Mechanical Systems',               70),
 (47, 4, 'financial',    'Financial & Administrative',       80),
 (50, 5, 'reserves',     'Reserve Capital',                   0);

-- ── Step 1 — always-on core accounts ──────────────────────────────────────

INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order, is_always) VALUES
 (100, 1, 'funds', '_always', 'Operating Fund Core Accounts', 'Always included', 0, 1);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, fund_code, group_code, is_bank_account, description) VALUES
 (100, '1010', 'Operating Checking Account',       'ASSET',     'OPERATING', '', 1, 'Primary operating checking account'),
 (100, '1100', 'Homeowner Assessments Receivable', 'ASSET',     'OPERATING', '', 0, 'Amounts owed by homeowners for assessments'),
 (100, '1150', 'Prepaid Expenses',                 'ASSET',     'OPERATING', '', 0, 'Expenses paid in advance'),
 (100, '2010', 'Accounts Payable',                 'LIABILITY', 'OPERATING', '', 0, 'Amounts owed to vendors and contractors'),
 (100, '2020', 'Accrued Expenses',                 'LIABILITY', 'OPERATING', '', 0, 'Expenses incurred but not yet paid'),
 (100, '2030', 'Prepaid Assessments',              'LIABILITY', 'OPERATING', '', 0, 'Assessment payments received in advance'),
 (100, '3010', 'Operating Fund Balance',           'EQUITY',    'OPERATING', '', 0, 'Accumulated balance of the operating fund');

-- ── Step 1 — optional funds ────────────────────────────────────────────────

INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (101, 1, 'funds', 'reserve', 'Reserve Fund',
  'A separate fund for future major repairs and replacements (roofing, paving, etc.)', 10),
 (102, 1, 'funds', 'special', 'Special Assessment Fund',
  'A separate fund for one-time special assessments levied for a specific project', 20);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, fund_code, is_bank_account, description) VALUES
 (101, '1020', 'Reserve Savings Account',          'ASSET',  'RESERVE', 1, 'Reserve fund savings account'),
 (101, '3020', 'Reserve Fund Balance',             'EQUITY', 'RESERVE', 0, 'Accumulated balance of the reserve fund'),
 (102, '1030', 'Special Assessment Account',       'ASSET',  'SPECIAL', 1, 'Special assessment bank account'),
 (102, '3030', 'Special Assessment Fund Balance',  'EQUITY', 'SPECIAL', 0, 'Accumulated balance of special assessment fund');

-- ── Step 2 — Income ────────────────────────────────────────────────────────

INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (201, 2, 'income', 'regular_dues',       'Regular Assessments / Dues',       'Periodic dues charged to all homeowners',                              10),
 (202, 2, 'income', 'special_assessments','Special Assessments',               'One-time assessments for a specific capital project',                  20),
 (203, 2, 'income', 'late_fees',          'Late Fees / Delinquency Charges',  'Fees charged when homeowners pay assessments late',                    30),
 (204, 2, 'income', 'fines',              'Fines & Violations',               'Fines levied for rule violations (architectural, parking, noise, etc.)',40),
 (205, 2, 'income', 'returned_checks',    'Returned Check / NSF Fees',        'Fees charged when a payment is returned by the bank',                  50),
 (206, 2, 'income', 'interest',           'Interest Income',                  'Interest earned on operating and reserve bank accounts',               60),
 (207, 2, 'income', 'rental',             'Rental Income',                    'Income from renting common facilities (parking, storage, clubhouse, etc.)', 70),
 (208, 2, 'income', 'resale_fees',        'Resale / Transfer Fees',           'Fees collected when a home is sold and ownership transfers',            80),
 (209, 2, 'income', 'misc_income',        'Miscellaneous Income',             'Grants, rebates, insurance proceeds, or other one-off income',          90);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, fund_code, description) VALUES
 (201, '4010', 'Homeowner Assessments',        'INCOME', 'OPERATING', 'Regular periodic assessments charged to homeowners'),
 (202, '4020', 'Special Assessments',          'INCOME', 'SPECIAL',   'One-time special assessments for specific projects'),
 (203, '4030', 'Late Fees',                    'INCOME', 'OPERATING', 'Fees charged for late payment of assessments'),
 (204, '4040', 'Fines & Violations',           'INCOME', 'OPERATING', 'Fines assessed against homeowners for HOA rule violations'),
 (205, '4050', 'Returned Check Fees',          'INCOME', 'OPERATING', 'Fees charged for returned or bounced checks'),
 (206, '4060', 'Interest Income — Operating',  'INCOME', 'OPERATING', 'Interest earned on operating accounts'),
 (206, '4070', 'Interest Income — Reserve',    'INCOME', 'RESERVE',   'Interest earned on reserve accounts'),
 (207, '4080', 'Rental Income',                'INCOME', 'OPERATING', 'Income from renting HOA-owned facilities or spaces'),
 (208, '4090', 'Resale & Transfer Fees',       'INCOME', 'OPERATING', 'Fees collected at the time of property sale or transfer'),
 (209, '4099', 'Miscellaneous Income',         'INCOME', 'OPERATING', 'Other income not classified elsewhere');

-- ── Step 3 — Amenities ─────────────────────────────────────────────────────

INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (301, 3, 'amenities', 'pool',         'Pool / Spa',                       'Swimming pool, hot tub, or spa area',                          10),
 (302, 3, 'amenities', 'fitness',      'Fitness Center / Gym',             'Exercise room or fitness facility',                            20),
 (303, 3, 'amenities', 'clubhouse',    'Clubhouse / Community Room',       'Common building used for meetings and events',                 30),
 (304, 3, 'amenities', 'courts',       'Tennis / Pickleball Courts',       'Sport courts of any kind',                                     40),
 (305, 3, 'amenities', 'playground',   'Playground',                       'Children''s play equipment and area',                          50),
 (306, 3, 'amenities', 'gate_security','Gated Entry / Security Systems',   'Entry gates, call boxes, cameras, or security systems',        60),
 (307, 3, 'amenities', 'parking',      'Common Area Parking',              'Shared parking lots or garages',                              70),
 (308, 3, 'amenities', 'trails',       'Walking Trails / Parks / Open Space','Trails, green spaces, or pocket parks maintained by the HOA',80);

-- Step 3 operating accounts
INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, fund_code, group_code, description) VALUES
 (301, '5800', 'Pool & Spa Maintenance',           'EXPENSE', 'OPERATING', 'Amenities', 'Regular pool and spa cleaning, chemicals, and upkeep'),
 (301, '5801', 'Pool Repairs',                     'EXPENSE', 'OPERATING', 'Amenities', 'Non-capital repairs to pool and spa equipment'),
 (302, '5810', 'Fitness Center Maintenance',       'EXPENSE', 'OPERATING', 'Amenities', 'Maintenance of fitness equipment and facility'),
 (303, '5820', 'Clubhouse Maintenance',            'EXPENSE', 'OPERATING', 'Amenities', 'Utilities, cleaning, and upkeep of clubhouse'),
 (304, '5830', 'Sports Court Maintenance',         'EXPENSE', 'OPERATING', 'Amenities', 'Maintenance and cleaning of sports courts'),
 (305, '5840', 'Playground Maintenance',           'EXPENSE', 'OPERATING', 'Amenities', 'Safety inspections, cleaning, and minor repairs'),
 (306, '5850', 'Gate & Security Maintenance',      'EXPENSE', 'OPERATING', 'Amenities', 'Service, repairs, and monitoring of gate and security systems'),
 (307, '5860', 'Parking Area Maintenance',         'EXPENSE', 'OPERATING', 'Amenities', 'Striping, lighting, and upkeep of common parking areas'),
 (308, '5870', 'Trails & Open Space Maintenance',  'EXPENSE', 'OPERATING', 'Amenities', 'Maintenance of walking paths, benches, signage, and open areas');

-- Step 3 reserve accounts (is_reserve_account = 1)
INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, fund_code, description, is_reserve_account) VALUES
 (301, '6300', 'Reserve — Pool / Spa Renovation',              'EXPENSE', 'RESERVE', 'Major pool resurfacing, equipment replacement, or renovation', 1),
 (302, '6310', 'Reserve — Fitness Equipment Replacement',      'EXPENSE', 'RESERVE', 'Replacement of major fitness equipment', 1),
 (303, '6320', 'Reserve — Clubhouse Renovation',               'EXPENSE', 'RESERVE', 'Major renovation or restoration of clubhouse building', 1),
 (304, '6330', 'Reserve — Court Surface Replacement',          'EXPENSE', 'RESERVE', 'Resurfacing or major repair of sport courts', 1),
 (305, '6340', 'Reserve — Playground Equipment Replacement',   'EXPENSE', 'RESERVE', 'Full replacement of playground structure and equipment', 1),
 (306, '6500', 'Reserve — Gate & Security System Replacement', 'EXPENSE', 'RESERVE', 'Full replacement of gate hardware, cameras, or access systems', 1);

-- ── Step 4 — Operating Expenses ────────────────────────────────────────────

-- Administration & Management
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (401, 4, 'admin', 'mgmt_fees',      'Property Management Fees',       'Monthly fees paid to a professional management company', 10),
 (402, 4, 'admin', 'office',         'Office Supplies & Equipment',    'Paper, postage, printer ink, small equipment',           20),
 (403, 4, 'admin', 'postage',        'Postage & Mailing',              'Stamps, certified mail, courier services',               30),
 (404, 4, 'admin', 'phone_internet', 'Telephone & Internet',           'Phone lines or internet service for the HOA office',    40),
 (405, 4, 'admin', 'printing',       'Printing & Copying',             'Newsletters, notices, meeting materials',                50),
 (406, 4, 'admin', 'licenses',       'Licenses, Permits & Compliance', 'Business licenses, pool permits, government filing fees',60),
 (407, 4, 'admin', 'software',       'Software & Technology',          'Accounting software, website hosting, community portal', 70),
 (408, 4, 'admin', 'meetings',       'Meeting Expenses',               'Room rental, refreshments, annual meeting costs',        80),
 (409, 4, 'admin', 'training',       'Education & Training',           'Board member certifications, HOA seminars, training materials', 90);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (401, '5100', 'Management Fees',      'EXPENSE', 'Administration', 'Fees paid to property management company'),
 (402, '5110', 'Office Supplies',      'EXPENSE', 'Administration', 'Office supplies and small equipment'),
 (403, '5120', 'Postage & Mailing',    'EXPENSE', 'Administration', 'Postage, shipping, and mailing costs'),
 (404, '5130', 'Telephone & Internet', 'EXPENSE', 'Administration', 'HOA telephone and internet service'),
 (405, '5140', 'Printing & Copying',   'EXPENSE', 'Administration', 'Printing, copying, and reproduction costs'),
 (406, '5150', 'Licenses & Permits',   'EXPENSE', 'Administration', 'Government licenses, permits, and compliance fees'),
 (407, '5160', 'Software & Technology','EXPENSE', 'Administration', 'Software subscriptions, website, and technology costs'),
 (408, '5170', 'Meeting Expenses',     'EXPENSE', 'Administration', 'Costs associated with board and annual meetings'),
 (409, '5180', 'Education & Training', 'EXPENSE', 'Administration', 'Board training, certifications, and educational programs');

-- Professional Services
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (410, 4, 'professional', 'legal',       'Legal Fees',                  'Attorney fees for collections, contracts, disputes, or compliance', 10),
 (411, 4, 'professional', 'accounting',  'Accounting & Audit Services', 'Bookkeeping, CPA review, annual audit',                             20),
 (412, 4, 'professional', 'tax_prep',    'Tax Preparation',             'Annual HOA tax return filing',                                      30),
 (413, 4, 'professional', 'engineering', 'Engineering & Consulting',    'Reserve studies, structural inspections, architectural review',      40);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (410, '5200', 'Legal Fees',               'EXPENSE', 'Professional Services', 'Attorney and legal counsel fees'),
 (411, '5210', 'Accounting & Audit',       'EXPENSE', 'Professional Services', 'CPA, bookkeeping, and audit services'),
 (412, '5220', 'Tax Preparation',          'EXPENSE', 'Professional Services', 'Annual tax return preparation and filing'),
 (413, '5230', 'Engineering & Consulting', 'EXPENSE', 'Professional Services', 'Reserve studies, engineering reports, and consulting');

-- Insurance
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (420, 4, 'insurance', 'property_ins', 'Property Insurance',             'Master policy covering HOA-owned structures and common areas', 10),
 (421, 4, 'insurance', 'liability_ins','General Liability Insurance',    'Coverage for injuries or damage in common areas',             20),
 (422, 4, 'insurance', 'do_ins',       'Directors & Officers (D&O) Insurance','Protects board members from personal liability',         30),
 (423, 4, 'insurance', 'crime_ins',    'Crime / Fidelity Insurance',     'Coverage for employee dishonesty or theft of HOA funds',      40),
 (424, 4, 'insurance', 'umbrella_ins', 'Umbrella Insurance',             'Excess liability coverage above primary policies',            50),
 (425, 4, 'insurance', 'workers_comp', 'Workers'' Compensation',          'Required if HOA has direct employees',                        60);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (420, '5300', 'Property Insurance',              'EXPENSE', 'Insurance', 'Master property insurance covering HOA structures'),
 (421, '5310', 'General Liability Insurance',     'EXPENSE', 'Insurance', 'Liability coverage for common area incidents'),
 (422, '5320', 'Directors & Officers Insurance',  'EXPENSE', 'Insurance', 'D&O liability protection for board members'),
 (423, '5330', 'Crime & Fidelity Insurance',      'EXPENSE', 'Insurance', 'Fidelity bond and crime coverage for HOA funds'),
 (424, '5340', 'Umbrella Insurance',              'EXPENSE', 'Insurance', 'Excess liability umbrella policy'),
 (425, '5350', 'Workers Compensation Insurance',  'EXPENSE', 'Insurance', 'Workers compensation coverage for HOA employees');

-- Landscaping & Grounds
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (430, 4, 'landscaping', 'lawn_care',          'Lawn Care & Landscaping',          'Mowing, edging, trimming, and general grounds upkeep',            10),
 (431, 4, 'landscaping', 'tree_trimming',      'Tree Trimming & Removal',          'Pruning, trimming, and removing trees in common areas',           20),
 (432, 4, 'landscaping', 'irrigation',         'Irrigation System Maintenance',    'Sprinkler system service, repairs, and seasonal adjustments',      30),
 (433, 4, 'landscaping', 'snow_removal',       'Snow Removal',                     'Plowing, shoveling, and ice treatment for common areas',          40),
 (434, 4, 'landscaping', 'pest_control',       'Pest Control & Fertilization',     'Lawn treatments, weed control, and pest extermination',           50),
 (435, 4, 'landscaping', 'seasonal_plantings', 'Seasonal Plantings & Flowers',     'Annual flowers, mulch, seasonal decorations',                     60);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (430, '5400', 'Lawn Care & Landscaping',      'EXPENSE', 'Landscaping', 'Mowing, edging, trimming, and general landscape maintenance'),
 (431, '5410', 'Tree Trimming & Removal',      'EXPENSE', 'Landscaping', 'Tree and shrub trimming and removal services'),
 (432, '5420', 'Irrigation Maintenance',       'EXPENSE', 'Landscaping', 'Sprinkler and irrigation system service and repairs'),
 (433, '5430', 'Snow Removal',                 'EXPENSE', 'Landscaping', 'Snow plowing, shoveling, and ice removal'),
 (434, '5440', 'Pest Control & Fertilization', 'EXPENSE', 'Landscaping', 'Weed control, fertilization, and pest extermination'),
 (435, '5450', 'Seasonal Plantings & Mulch',   'EXPENSE', 'Landscaping', 'Seasonal flowers, plants, and mulching');

-- Utilities
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (440, 4, 'utilities', 'electricity', 'Electricity',              'Electric service for common areas, lighting, and amenities',  10),
 (441, 4, 'utilities', 'water',       'Water',                    'Water for irrigation, fountains, and common area plumbing',   20),
 (442, 4, 'utilities', 'gas',         'Natural Gas',              'Gas service for heating common spaces or amenities',          30),
 (443, 4, 'utilities', 'trash',       'Trash & Waste Removal',    'Garbage collection and disposal for common areas',            40),
 (444, 4, 'utilities', 'stormwater',  'Stormwater / Drainage Fees','Municipal stormwater utility charges',                       50);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (440, '5500', 'Electricity',           'EXPENSE', 'Utilities', 'Electric utility for common areas and facilities'),
 (441, '5510', 'Water',                 'EXPENSE', 'Utilities', 'Water utility for common areas and irrigation'),
 (442, '5520', 'Natural Gas',           'EXPENSE', 'Utilities', 'Gas utility for common area heating'),
 (443, '5530', 'Trash & Waste Removal', 'EXPENSE', 'Utilities', 'Garbage collection and disposal services'),
 (444, '5540', 'Stormwater & Drainage', 'EXPENSE', 'Utilities', 'Stormwater utility and drainage fees');

-- Exterior Maintenance
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (450, 4, 'exterior', 'roofing',       'Roof Repairs',                   'Patching, flashing, gutter cleaning — non-capital repairs',            10),
 (451, 4, 'exterior', 'siding',        'Siding, Stucco & Exterior Walls','Repairs and maintenance of building exteriors',                       20),
 (452, 4, 'exterior', 'fencing',       'Fencing & Gates',                'Fence repairs, gate hardware, and perimeter maintenance',              30),
 (453, 4, 'exterior', 'painting',      'Painting & Refinishing',         'Exterior paint, staining, sealing',                                   40),
 (454, 4, 'exterior', 'paving',        'Roads, Paving & Concrete',       'Pothole repairs, crack sealing, concrete patching',                   50),
 (455, 4, 'exterior', 'windows_doors', 'Windows & Doors',                'Common area door hardware, window repairs, weather stripping',        60),
 (456, 4, 'exterior', 'janitorial',    'Janitorial & Cleaning',          'Cleaning of common buildings, lobbies, and exterior areas',           70),
 (457, 4, 'exterior', 'lighting',      'Street & Common Area Lighting',  'Streetlight maintenance, bulb replacement, electrical repairs',       80),
 (458, 4, 'exterior', 'signage',       'Signage',                        'Entry signs, street signs, community notices',                        90);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (450, '5600', 'Roof Repairs',                    'EXPENSE', 'Exterior Maintenance', 'Non-capital roof patching, flashing, and repairs'),
 (451, '5610', 'Siding & Exterior Repairs',       'EXPENSE', 'Exterior Maintenance', 'Siding, stucco, trim, and exterior wall repairs'),
 (452, '5620', 'Fence & Gate Repairs',            'EXPENSE', 'Exterior Maintenance', 'Repair and upkeep of fences, gates, and perimeter'),
 (453, '5630', 'Painting & Refinishing',          'EXPENSE', 'Exterior Maintenance', 'Exterior painting, staining, and surface refinishing'),
 (454, '5640', 'Roads, Paving & Concrete',        'EXPENSE', 'Exterior Maintenance', 'Road repairs, asphalt patching, and concrete maintenance'),
 (455, '5650', 'Windows & Doors',                 'EXPENSE', 'Exterior Maintenance', 'Common area window and door repairs'),
 (456, '5660', 'Janitorial & Cleaning',           'EXPENSE', 'Exterior Maintenance', 'Cleaning services for common areas and buildings'),
 (457, '5670', 'Street & Common Area Lighting',   'EXPENSE', 'Exterior Maintenance', 'Maintenance and repair of common area lighting'),
 (458, '5680', 'Signage',                         'EXPENSE', 'Exterior Maintenance', 'Common area signs, community entry monument maintenance');

-- Mechanical Systems
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (460, 4, 'mechanical', 'hvac',        'HVAC Maintenance',                  'Heating and cooling system service for common buildings',         10),
 (461, 4, 'mechanical', 'plumbing',    'Plumbing Repairs',                  'Leaks, drain clearing, pipe repairs in common areas',             20),
 (462, 4, 'mechanical', 'electrical',  'Electrical System Maintenance',     'Panel service, wiring, outlet repairs in common areas',           30),
 (463, 4, 'mechanical', 'fire_systems','Fire Suppression & Safety Systems', 'Sprinkler system inspections, fire extinguisher service',         40);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (460, '5700', 'HVAC Maintenance',        'EXPENSE', 'Mechanical', 'Heating, ventilation, and cooling system maintenance'),
 (461, '5710', 'Plumbing Repairs',        'EXPENSE', 'Mechanical', 'Common area plumbing service and repairs'),
 (462, '5720', 'Electrical Maintenance',  'EXPENSE', 'Mechanical', 'Common area electrical system maintenance and repairs'),
 (463, '5730', 'Fire & Safety Systems',   'EXPENSE', 'Mechanical', 'Fire suppression, sprinkler, and safety system maintenance');

-- Financial & Administrative
INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (470, 4, 'financial', 'bank_fees',            'Bank Fees & Charges',       'Monthly service fees, wire transfer fees, lockbox fees',    10),
 (471, 4, 'financial', 'bad_debt',             'Bad Debt / Write-offs',     'Uncollectible homeowner balances written off',               20),
 (472, 4, 'financial', 'reserve_contribution', 'Reserve Fund Contribution', 'Budgeted transfer from operating fund to reserves',          30),
 (473, 4, 'financial', 'misc_expense',         'Miscellaneous Expenses',    'Incidental costs not captured elsewhere',                    40);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, group_code, description) VALUES
 (470, '5900', 'Bank Fees & Charges',       'EXPENSE', 'Financial', 'Bank service charges, wire fees, and lockbox fees'),
 (471, '5910', 'Bad Debt Expense',          'EXPENSE', 'Financial', 'Write-off of uncollectible homeowner assessment balances'),
 (472, '5920', 'Reserve Fund Contribution', 'EXPENSE', 'Financial', 'Budgeted operating-to-reserve transfer expense'),
 (473, '5990', 'Miscellaneous Expense',     'EXPENSE', 'Financial', 'Miscellaneous operating expenses not classified elsewhere');

-- ── Step 5 — Reserve Capital ───────────────────────────────────────────────

INSERT INTO wizard_options (id, step_number, group_id, option_id, label, description, sort_order) VALUES
 (501, 5, 'reserves', 'res_roof',        'Roofing',                          'Full roof replacement on HOA-maintained buildings',                          10),
 (502, 5, 'reserves', 'res_building_ext','Building Exterior / Siding',       'Full replacement of siding, stucco, or building envelope',                   20),
 (503, 5, 'reserves', 'res_fencing',     'Fencing & Perimeter Walls',        'Full fence or retaining wall replacement',                                   30),
 (504, 5, 'reserves', 'res_paving',      'Roads & Paving',                   'Full pavement overlay or replacement of private roads and lots',             40),
 (505, 5, 'reserves', 'res_concrete',    'Concrete (Walks, Curbs, Stairs)',  'Large-scale concrete replacement throughout the community',                  50),
 (506, 5, 'reserves', 'res_painting',    'Exterior Painting',                'Community-wide exterior repainting cycle',                                   60),
 (507, 5, 'reserves', 'res_hvac',        'HVAC System Replacement',          'Full replacement of heating/cooling systems in common buildings',             70),
 (508, 5, 'reserves', 'res_plumbing',    'Plumbing System',                  'Major common area plumbing replacement or re-piping',                        80),
 (509, 5, 'reserves', 'res_electrical',  'Electrical System',                'Panel upgrades, rewiring, or electrical infrastructure',                      90),
 (510, 5, 'reserves', 'res_fire',        'Fire Suppression System',          'Full replacement of fire sprinkler or suppression system',                  100),
 (511, 5, 'reserves', 'res_irrigation',  'Irrigation System',                'Full replacement of community-wide irrigation infrastructure',               110),
 (512, 5, 'reserves', 'res_lighting',    'Street & Common Area Lighting',    'LED conversion or full lighting fixture replacement',                        120),
 (513, 5, 'reserves', 'res_other',       'Other Capital Projects',           'Major projects not covered by the categories above',                         130);

INSERT INTO wizard_option_accounts (wizard_option_id, account_number, account_name, account_type, fund_code, description) VALUES
 (501, '6100', 'Reserve — Roof Replacement',               'EXPENSE', 'RESERVE', 'Full roof replacement for HOA-maintained structures'),
 (502, '6110', 'Reserve — Building Exterior Replacement',  'EXPENSE', 'RESERVE', 'Major building envelope, siding, or stucco replacement'),
 (503, '6120', 'Reserve — Fence & Wall Replacement',       'EXPENSE', 'RESERVE', 'Replacement of perimeter fences and retaining walls'),
 (504, '6200', 'Reserve — Road & Pavement Replacement',    'EXPENSE', 'RESERVE', 'Full road, parking lot, and pavement replacement'),
 (505, '6210', 'Reserve — Concrete Replacement',           'EXPENSE', 'RESERVE', 'Replacement of community sidewalks, curbs, and stairs'),
 (506, '6220', 'Reserve — Exterior Painting',              'EXPENSE', 'RESERVE', 'Scheduled full community exterior repainting'),
 (507, '6400', 'Reserve — HVAC Replacement',               'EXPENSE', 'RESERVE', 'Replacement of HVAC systems in common area buildings'),
 (508, '6410', 'Reserve — Plumbing System',                'EXPENSE', 'RESERVE', 'Major re-piping or plumbing system replacement'),
 (509, '6420', 'Reserve — Electrical System',              'EXPENSE', 'RESERVE', 'Major electrical infrastructure upgrades or rewiring'),
 (510, '6430', 'Reserve — Fire Suppression System',        'EXPENSE', 'RESERVE', 'Replacement of fire suppression and safety systems'),
 (511, '6510', 'Reserve — Irrigation System Replacement',  'EXPENSE', 'RESERVE', 'Replacement of main irrigation lines and control systems'),
 (512, '6520', 'Reserve — Street Lighting Replacement',    'EXPENSE', 'RESERVE', 'Community-wide lighting upgrade or fixture replacement'),
 (513, '6600', 'Reserve — Other Capital Projects',         'EXPENSE', 'RESERVE', 'Reserve funding for other major capital expenditures');

COMMIT;
