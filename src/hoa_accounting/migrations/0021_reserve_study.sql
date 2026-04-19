BEGIN;

CREATE TABLE reserve_assets (
    id              INTEGER PRIMARY KEY,
    asset_group     TEXT NOT NULL,
    component       TEXT NOT NULL,
    install_year    INTEGER NOT NULL,
    useful_life_years INTEGER NOT NULL,
    condition       TEXT NOT NULL DEFAULT 'Good'
                        CHECK (condition IN ('Good','Moderate','Poor','Critical')),
    replacement_cost NUMERIC NOT NULL DEFAULT 0,
    annual_inflation NUMERIC NOT NULL DEFAULT 0.04,
    notes           TEXT,
    active_flag     INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reserve_study_assumptions (
    id                          INTEGER PRIMARY KEY,
    study_year                  INTEGER NOT NULL,
    reserve_balance_override    NUMERIC,  -- NULL = pull live from GL
    annual_contribution         NUMERIC NOT NULL DEFAULT 0,
    contribution_growth_rate    NUMERIC NOT NULL DEFAULT 0.03,
    investment_return_rate      NUMERIC NOT NULL DEFAULT 0.01,
    num_lots                    INTEGER NOT NULL DEFAULT 1,
    projection_years            INTEGER NOT NULL DEFAULT 30,
    notes                       TEXT,
    is_active                   INTEGER NOT NULL DEFAULT 1,
    created_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reserve_study_scenarios (
    id                  INTEGER PRIMARY KEY,
    scenario_name       TEXT NOT NULL,
    description         TEXT,
    emergency_cost      NUMERIC NOT NULL DEFAULT 0,
    expected_year       INTEGER,
    notes               TEXT,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    active_flag         INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── Seed: assumptions ─────────────────────────────────────────────────────
INSERT INTO reserve_study_assumptions
    (study_year, reserve_balance_override, annual_contribution,
     contribution_growth_rate, investment_return_rate, num_lots,
     projection_years, notes, is_active)
VALUES
    (2026, 19000.00, 7600.00, 0.03, 0.01, 16, 30,
     'April 2026 study — MMPOA II-A. Balance is override until GL reserve fund is reconciled.',
     1);

-- ── Seed: assets ──────────────────────────────────────────────────────────
-- Private Road (MMPOAII)
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Private Road (MMPOAII)', 'Full resurfacing (21,000 sq ft)',
     2026, 10, 'Moderate', 25000.00, 0.04,
     'Fair — being repaired 2026', 10),
    ('Private Road (MMPOAII)', 'Partial replacement (~1,000 sq ft)',
     2026, 20, 'Poor', 0.00, 0.04,
     'Being replaced 2026 — cost included in resurfacing budget', 20),
    ('Private Road (MMPOAII)', 'Next major reseal',
     2026, 8, 'Good', 18000.00, 0.04,
     'New after 2026 repair', 30);

-- Shared Road (w/MMPOAI)
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Shared Road (w/MMPOAI)', 'Reseal (16,000 sq ft, 40% share)',
     2026, 8, 'Good', 0.00, 0.04,
     'Being resealed 2026 — already budgeted', 40),
    ('Shared Road (w/MMPOAI)', 'Asphalt replacement (40% of $75K)',
     2026, 4, 'Good', 30000.00, 0.04,
     'Planned — est. 2030; MMPOAII share 40%', 50);

-- Retaining Wall
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Retaining Wall', 'Railroad tie section (~80 ft)',
     2014, 20, 'Good', 24000.00, 0.04,
     '12 yrs old; est. $600/linear ft', 60),
    ('Retaining Wall', 'Limestone — good section (~80 ft)',
     1983, 60, 'Good', 48000.00, 0.04,
     '43 yrs old; est. $600/linear ft', 70),
    ('Retaining Wall', 'Limestone — moderate section (~270 ft)',
     1983, 50, 'Moderate', 162000.00, 0.04,
     '43 yrs old; est. $600/linear ft; showing wear', 80),
    ('Retaining Wall', 'Limestone — poor section (~150 ft)',
     1983, 45, 'Poor', 90000.00, 0.04,
     '43 yrs old; priority replacement; est. $600/linear ft', 90);

-- Sewage Lift Station
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Sewage Lift Station', 'Electric motors (2)',
     2019, 15, 'Good', 18000.00, 0.04,
     '7 yrs old', 100),
    ('Sewage Lift Station', 'Control electronics',
     1991, 30, 'Critical', 15000.00, 0.04,
     '35 yrs old — past useful life; immediate replacement priority', 110),
    ('Sewage Lift Station', 'Alarm/monitoring system',
     2024, 10, 'Good', 3000.00, 0.04,
     '2 yrs old', 120);

-- Security Gate
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Security Gate', 'Gate structure (swing)',
     2024, 25, 'Good', 15000.00, 0.04,
     '2 yrs old', 130),
    ('Security Gate', 'Gate operators/motors',
     2018, 15, 'Good', 8000.00, 0.04,
     '8 yrs old; recently inspected', 140),
    ('Security Gate', 'Access system (keypads/remotes)',
     2018, 12, 'Good', 4000.00, 0.04,
     '8 yrs old', 150);

-- Mail Kiosk
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Mail Kiosk', 'Structure (painted, tile roof)',
     2021, 25, 'Good', 6000.00, 0.04,
     '5 yrs old; painted 2 yrs ago', 160),
    ('Mail Kiosk', 'Mailbox unit (USPS compliant)',
     2015, 12, 'Poor', 4500.00, 0.04,
     '11 yrs old; needs replacement soon', 170);

-- Common Areas
INSERT INTO reserve_assets
    (asset_group, component, install_year, useful_life_years, condition,
     replacement_cost, annual_inflation, notes, sort_order)
VALUES
    ('Common Areas', 'Landscaping (complete redo)',
     2020, 15, 'Good', 20000.00, 0.04,
     '6 yrs old; well maintained', 180),
    ('Common Areas', 'Sprinkler system',
     2020, 15, 'Good', 12000.00, 0.04,
     '6 yrs old; $500/yr maintenance budget', 190),
    ('Common Areas', 'Lighting system',
     2020, 15, 'Good', 8000.00, 0.04,
     '6 yrs old; replaced with landscape project', 200);

-- ── Seed: scenarios ───────────────────────────────────────────────────────
INSERT INTO reserve_study_scenarios
    (scenario_name, description, emergency_cost, expected_year, notes, sort_order)
VALUES
    ('Limestone Wall Collapse (150 ft poor section)',
     'Major collapse of the 150 ft poor-condition limestone wall.',
     90000.00, 2028,
     'Based on 2018 collapse: ~$600/ft. Poor section is highest risk.',
     10),
    ('Lift Station Electronics Failure',
     '35-year-old control electronics fail; emergency replacement required.',
     25000.00, 2026,
     'Electronics are 10+ years past typical useful life. Emergency premium included.',
     20),
    ('Combined — Wall + Lift Station Same Year',
     'Both critical assets fail in the same year (worst case).',
     115000.00, 2028,
     'Combined worst case. Both assets are past or near end of useful life.',
     30),
    ('Gate + Road Emergency (Storm Damage)',
     'Major storm damages gate and causes road washout.',
     40000.00, NULL,
     'Hillside community is vulnerable to storm/drainage events.',
     40),
    ('Moderate Wall Repair (270 ft section)',
     'Moderate-condition limestone section requires structural repair.',
     80000.00, 2033,
     'Preventive repair before full failure. Estimated at 50% of replacement cost.',
     50);

COMMIT;
