"""
COA Interview Wizard — account catalog.

Each STEP has one or more GROUPS of checkbox options.
Each OPTION maps to one or more ACCOUNTS to create when selected.

Account dicts:
    account_number  str   e.g. "4010"
    account_name    str
    account_type    str   ASSET | LIABILITY | EQUITY | INCOME | EXPENSE
    fund_code       str   OPERATING | RESERVE | SPECIAL
    group_code      str   optional expense grouping label
    is_bank_account bool
    description     str
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _acct(number, name, atype, fund="OPERATING", group="", bank=False, desc=""):
    return dict(
        account_number=number, account_name=name, account_type=atype,
        fund_code=fund, group_code=group, is_bank_account=bank, description=desc,
    )


# ---------------------------------------------------------------------------
# Step 1 — Funds
# Always creates core operating accounts; Reserve/Special are conditional.
# ---------------------------------------------------------------------------

STEP1_ALWAYS_ACCOUNTS = [
    _acct("1010", "Operating Checking Account",        "ASSET",     bank=True,  desc="Primary operating checking account"),
    _acct("1100", "Homeowner Assessments Receivable",  "ASSET",                 desc="Amounts owed by homeowners for assessments"),
    _acct("1150", "Prepaid Expenses",                  "ASSET",                 desc="Expenses paid in advance"),
    _acct("2010", "Accounts Payable",                  "LIABILITY",             desc="Amounts owed to vendors and contractors"),
    _acct("2020", "Accrued Expenses",                  "LIABILITY",             desc="Expenses incurred but not yet paid"),
    _acct("2030", "Prepaid Assessments",               "LIABILITY",             desc="Assessment payments received in advance"),
    _acct("3010", "Operating Fund Balance",            "EQUITY",                desc="Accumulated balance of the operating fund"),
]

STEP1_OPTIONS = [
    {
        "id": "reserve",
        "label": "Reserve Fund",
        "desc": "A separate fund for future major repairs and replacements (roofing, paving, etc.)",
        "accounts": [
            _acct("1020", "Reserve Savings Account",   "ASSET",  fund="RESERVE", bank=True, desc="Reserve fund savings account"),
            _acct("3020", "Reserve Fund Balance",      "EQUITY", fund="RESERVE",            desc="Accumulated balance of the reserve fund"),
        ],
    },
    {
        "id": "special",
        "label": "Special Assessment Fund",
        "desc": "A separate fund for one-time special assessments levied for a specific project",
        "accounts": [
            _acct("1030", "Special Assessment Account", "ASSET",  fund="SPECIAL", bank=True, desc="Special assessment bank account"),
            _acct("3030", "Special Assessment Fund Balance", "EQUITY", fund="SPECIAL",       desc="Accumulated balance of special assessment fund"),
        ],
    },
]

# ---------------------------------------------------------------------------
# Step 2 — Income Sources
# ---------------------------------------------------------------------------

STEP2_OPTIONS = [
    {
        "id": "regular_dues",
        "label": "Regular Assessments / Dues",
        "desc": "Periodic dues charged to all homeowners",
        "accounts": [
            _acct("4010", "Homeowner Assessments",  "INCOME", desc="Regular periodic assessments charged to homeowners"),
        ],
    },
    {
        "id": "special_assessments",
        "label": "Special Assessments",
        "desc": "One-time assessments for a specific capital project",
        "accounts": [
            _acct("4020", "Special Assessments",    "INCOME", fund="SPECIAL", desc="One-time special assessments for specific projects"),
        ],
    },
    {
        "id": "late_fees",
        "label": "Late Fees / Delinquency Charges",
        "desc": "Fees charged when homeowners pay assessments late",
        "accounts": [
            _acct("4030", "Late Fees",              "INCOME", desc="Fees charged for late payment of assessments"),
        ],
    },
    {
        "id": "fines",
        "label": "Fines & Violations",
        "desc": "Fines levied for rule violations (architectural, parking, noise, etc.)",
        "accounts": [
            _acct("4040", "Fines & Violations",     "INCOME", desc="Fines assessed against homeowners for HOA rule violations"),
        ],
    },
    {
        "id": "returned_checks",
        "label": "Returned Check / NSF Fees",
        "desc": "Fees charged when a payment is returned by the bank",
        "accounts": [
            _acct("4050", "Returned Check Fees",    "INCOME", desc="Fees charged for returned or bounced checks"),
        ],
    },
    {
        "id": "interest",
        "label": "Interest Income",
        "desc": "Interest earned on operating and reserve bank accounts",
        "accounts": [
            _acct("4060", "Interest Income — Operating", "INCOME",              desc="Interest earned on operating accounts"),
            _acct("4070", "Interest Income — Reserve",   "INCOME", fund="RESERVE", desc="Interest earned on reserve accounts"),
        ],
    },
    {
        "id": "rental",
        "label": "Rental Income",
        "desc": "Income from renting common facilities (parking, storage, clubhouse, etc.)",
        "accounts": [
            _acct("4080", "Rental Income",          "INCOME", desc="Income from renting HOA-owned facilities or spaces"),
        ],
    },
    {
        "id": "resale_fees",
        "label": "Resale / Transfer Fees",
        "desc": "Fees collected when a home is sold and ownership transfers",
        "accounts": [
            _acct("4090", "Resale & Transfer Fees", "INCOME", desc="Fees collected at the time of property sale or transfer"),
        ],
    },
    {
        "id": "misc_income",
        "label": "Miscellaneous Income",
        "desc": "Grants, rebates, insurance proceeds, or other one-off income",
        "accounts": [
            _acct("4099", "Miscellaneous Income",   "INCOME", desc="Other income not classified elsewhere"),
        ],
    },
]

# ---------------------------------------------------------------------------
# Step 3 — Amenities
# Selections here add expense accounts AND reserve accounts (Step 5 uses same ids)
# ---------------------------------------------------------------------------

STEP3_OPTIONS = [
    {
        "id": "pool",
        "label": "Pool / Spa",
        "desc": "Swimming pool, hot tub, or spa area",
        "accounts": [
            _acct("5800", "Pool & Spa Maintenance",        "EXPENSE", group="Amenities", desc="Regular pool and spa cleaning, chemicals, and upkeep"),
            _acct("5801", "Pool Repairs",                  "EXPENSE", group="Amenities", desc="Non-capital repairs to pool and spa equipment"),
        ],
        "reserve_accounts": [
            _acct("6300", "Reserve — Pool / Spa Renovation", "EXPENSE", fund="RESERVE", desc="Major pool resurfacing, equipment replacement, or renovation"),
        ],
    },
    {
        "id": "fitness",
        "label": "Fitness Center / Gym",
        "desc": "Exercise room or fitness facility",
        "accounts": [
            _acct("5810", "Fitness Center Maintenance",    "EXPENSE", group="Amenities", desc="Maintenance of fitness equipment and facility"),
        ],
        "reserve_accounts": [
            _acct("6310", "Reserve — Fitness Equipment Replacement", "EXPENSE", fund="RESERVE", desc="Replacement of major fitness equipment"),
        ],
    },
    {
        "id": "clubhouse",
        "label": "Clubhouse / Community Room",
        "desc": "Common building used for meetings and events",
        "accounts": [
            _acct("5820", "Clubhouse Maintenance",         "EXPENSE", group="Amenities", desc="Utilities, cleaning, and upkeep of clubhouse"),
        ],
        "reserve_accounts": [
            _acct("6320", "Reserve — Clubhouse Renovation", "EXPENSE", fund="RESERVE", desc="Major renovation or restoration of clubhouse building"),
        ],
    },
    {
        "id": "courts",
        "label": "Tennis / Pickleball Courts",
        "desc": "Sport courts of any kind",
        "accounts": [
            _acct("5830", "Sports Court Maintenance",      "EXPENSE", group="Amenities", desc="Maintenance and cleaning of sports courts"),
        ],
        "reserve_accounts": [
            _acct("6330", "Reserve — Court Surface Replacement", "EXPENSE", fund="RESERVE", desc="Resurfacing or major repair of sport courts"),
        ],
    },
    {
        "id": "playground",
        "label": "Playground",
        "desc": "Children's play equipment and area",
        "accounts": [
            _acct("5840", "Playground Maintenance",        "EXPENSE", group="Amenities", desc="Safety inspections, cleaning, and minor repairs"),
        ],
        "reserve_accounts": [
            _acct("6340", "Reserve — Playground Equipment Replacement", "EXPENSE", fund="RESERVE", desc="Full replacement of playground structure and equipment"),
        ],
    },
    {
        "id": "gate_security",
        "label": "Gated Entry / Security Systems",
        "desc": "Entry gates, call boxes, cameras, or security systems",
        "accounts": [
            _acct("5850", "Gate & Security Maintenance",   "EXPENSE", group="Amenities", desc="Service, repairs, and monitoring of gate and security systems"),
        ],
        "reserve_accounts": [
            _acct("6500", "Reserve — Gate & Security System Replacement", "EXPENSE", fund="RESERVE", desc="Full replacement of gate hardware, cameras, or access systems"),
        ],
    },
    {
        "id": "parking",
        "label": "Common Area Parking",
        "desc": "Shared parking lots or garages",
        "accounts": [
            _acct("5860", "Parking Area Maintenance",      "EXPENSE", group="Amenities", desc="Striping, lighting, and upkeep of common parking areas"),
        ],
    },
    {
        "id": "trails",
        "label": "Walking Trails / Parks / Open Space",
        "desc": "Trails, green spaces, or pocket parks maintained by the HOA",
        "accounts": [
            _acct("5870", "Trails & Open Space Maintenance", "EXPENSE", group="Amenities", desc="Maintenance of walking paths, benches, signage, and open areas"),
        ],
    },
]

# ---------------------------------------------------------------------------
# Step 4 — Operating Expenses
# ---------------------------------------------------------------------------

STEP4_GROUPS = [
    {
        "id": "admin",
        "label": "Administration & Management",
        "options": [
            {
                "id": "mgmt_fees",
                "label": "Property Management Fees",
                "desc": "Monthly fees paid to a professional management company",
                "accounts": [_acct("5100", "Management Fees", "EXPENSE", group="Administration", desc="Fees paid to property management company")],
            },
            {
                "id": "office",
                "label": "Office Supplies & Equipment",
                "desc": "Paper, postage, printer ink, small equipment",
                "accounts": [_acct("5110", "Office Supplies", "EXPENSE", group="Administration", desc="Office supplies and small equipment")],
            },
            {
                "id": "postage",
                "label": "Postage & Mailing",
                "desc": "Stamps, certified mail, courier services",
                "accounts": [_acct("5120", "Postage & Mailing", "EXPENSE", group="Administration", desc="Postage, shipping, and mailing costs")],
            },
            {
                "id": "phone_internet",
                "label": "Telephone & Internet",
                "desc": "Phone lines or internet service for the HOA office",
                "accounts": [_acct("5130", "Telephone & Internet", "EXPENSE", group="Administration", desc="HOA telephone and internet service")],
            },
            {
                "id": "printing",
                "label": "Printing & Copying",
                "desc": "Newsletters, notices, meeting materials",
                "accounts": [_acct("5140", "Printing & Copying", "EXPENSE", group="Administration", desc="Printing, copying, and reproduction costs")],
            },
            {
                "id": "licenses",
                "label": "Licenses, Permits & Compliance",
                "desc": "Business licenses, pool permits, government filing fees",
                "accounts": [_acct("5150", "Licenses & Permits", "EXPENSE", group="Administration", desc="Government licenses, permits, and compliance fees")],
            },
            {
                "id": "software",
                "label": "Software & Technology",
                "desc": "Accounting software, website hosting, community portal",
                "accounts": [_acct("5160", "Software & Technology", "EXPENSE", group="Administration", desc="Software subscriptions, website, and technology costs")],
            },
            {
                "id": "meetings",
                "label": "Meeting Expenses",
                "desc": "Room rental, refreshments, annual meeting costs",
                "accounts": [_acct("5170", "Meeting Expenses", "EXPENSE", group="Administration", desc="Costs associated with board and annual meetings")],
            },
            {
                "id": "training",
                "label": "Education & Training",
                "desc": "Board member certifications, HOA seminars, training materials",
                "accounts": [_acct("5180", "Education & Training", "EXPENSE", group="Administration", desc="Board training, certifications, and educational programs")],
            },
        ],
    },
    {
        "id": "professional",
        "label": "Professional Services",
        "options": [
            {
                "id": "legal",
                "label": "Legal Fees",
                "desc": "Attorney fees for collections, contracts, disputes, or compliance",
                "accounts": [_acct("5200", "Legal Fees", "EXPENSE", group="Professional Services", desc="Attorney and legal counsel fees")],
            },
            {
                "id": "accounting",
                "label": "Accounting & Audit Services",
                "desc": "Bookkeeping, CPA review, annual audit",
                "accounts": [_acct("5210", "Accounting & Audit", "EXPENSE", group="Professional Services", desc="CPA, bookkeeping, and audit services")],
            },
            {
                "id": "tax_prep",
                "label": "Tax Preparation",
                "desc": "Annual HOA tax return filing",
                "accounts": [_acct("5220", "Tax Preparation", "EXPENSE", group="Professional Services", desc="Annual tax return preparation and filing")],
            },
            {
                "id": "engineering",
                "label": "Engineering & Consulting",
                "desc": "Reserve studies, structural inspections, architectural review",
                "accounts": [_acct("5230", "Engineering & Consulting", "EXPENSE", group="Professional Services", desc="Reserve studies, engineering reports, and consulting")],
            },
        ],
    },
    {
        "id": "insurance",
        "label": "Insurance",
        "options": [
            {
                "id": "property_ins",
                "label": "Property Insurance",
                "desc": "Master policy covering HOA-owned structures and common areas",
                "accounts": [_acct("5300", "Property Insurance", "EXPENSE", group="Insurance", desc="Master property insurance covering HOA structures")],
            },
            {
                "id": "liability_ins",
                "label": "General Liability Insurance",
                "desc": "Coverage for injuries or damage in common areas",
                "accounts": [_acct("5310", "General Liability Insurance", "EXPENSE", group="Insurance", desc="Liability coverage for common area incidents")],
            },
            {
                "id": "do_ins",
                "label": "Directors & Officers (D&O) Insurance",
                "desc": "Protects board members from personal liability",
                "accounts": [_acct("5320", "Directors & Officers Insurance", "EXPENSE", group="Insurance", desc="D&O liability protection for board members")],
            },
            {
                "id": "crime_ins",
                "label": "Crime / Fidelity Insurance",
                "desc": "Coverage for employee dishonesty or theft of HOA funds",
                "accounts": [_acct("5330", "Crime & Fidelity Insurance", "EXPENSE", group="Insurance", desc="Fidelity bond and crime coverage for HOA funds")],
            },
            {
                "id": "umbrella_ins",
                "label": "Umbrella Insurance",
                "desc": "Excess liability coverage above primary policies",
                "accounts": [_acct("5340", "Umbrella Insurance", "EXPENSE", group="Insurance", desc="Excess liability umbrella policy")],
            },
            {
                "id": "workers_comp",
                "label": "Workers' Compensation",
                "desc": "Required if HOA has direct employees",
                "accounts": [_acct("5350", "Workers Compensation Insurance", "EXPENSE", group="Insurance", desc="Workers compensation coverage for HOA employees")],
            },
        ],
    },
    {
        "id": "landscaping",
        "label": "Landscaping & Grounds",
        "options": [
            {
                "id": "lawn_care",
                "label": "Lawn Care & Landscaping",
                "desc": "Mowing, edging, trimming, and general grounds upkeep",
                "accounts": [_acct("5400", "Lawn Care & Landscaping", "EXPENSE", group="Landscaping", desc="Mowing, edging, trimming, and general landscape maintenance")],
            },
            {
                "id": "tree_trimming",
                "label": "Tree Trimming & Removal",
                "desc": "Pruning, trimming, and removing trees in common areas",
                "accounts": [_acct("5410", "Tree Trimming & Removal", "EXPENSE", group="Landscaping", desc="Tree and shrub trimming and removal services")],
            },
            {
                "id": "irrigation",
                "label": "Irrigation System Maintenance",
                "desc": "Sprinkler system service, repairs, and seasonal adjustments",
                "accounts": [_acct("5420", "Irrigation Maintenance", "EXPENSE", group="Landscaping", desc="Sprinkler and irrigation system service and repairs")],
            },
            {
                "id": "snow_removal",
                "label": "Snow Removal",
                "desc": "Plowing, shoveling, and ice treatment for common areas",
                "accounts": [_acct("5430", "Snow Removal", "EXPENSE", group="Landscaping", desc="Snow plowing, shoveling, and ice removal")],
            },
            {
                "id": "pest_control",
                "label": "Pest Control & Fertilization",
                "desc": "Lawn treatments, weed control, and pest extermination",
                "accounts": [_acct("5440", "Pest Control & Fertilization", "EXPENSE", group="Landscaping", desc="Weed control, fertilization, and pest extermination")],
            },
            {
                "id": "seasonal_plantings",
                "label": "Seasonal Plantings & Flowers",
                "desc": "Annual flowers, mulch, seasonal decorations",
                "accounts": [_acct("5450", "Seasonal Plantings & Mulch", "EXPENSE", group="Landscaping", desc="Seasonal flowers, plants, and mulching")],
            },
        ],
    },
    {
        "id": "utilities",
        "label": "Utilities — Common Areas",
        "options": [
            {
                "id": "electricity",
                "label": "Electricity",
                "desc": "Electric service for common areas, lighting, and amenities",
                "accounts": [_acct("5500", "Electricity", "EXPENSE", group="Utilities", desc="Electric utility for common areas and facilities")],
            },
            {
                "id": "water",
                "label": "Water",
                "desc": "Water for irrigation, fountains, and common area plumbing",
                "accounts": [_acct("5510", "Water", "EXPENSE", group="Utilities", desc="Water utility for common areas and irrigation")],
            },
            {
                "id": "gas",
                "label": "Natural Gas",
                "desc": "Gas service for heating common spaces or amenities",
                "accounts": [_acct("5520", "Natural Gas", "EXPENSE", group="Utilities", desc="Gas utility for common area heating")],
            },
            {
                "id": "trash",
                "label": "Trash & Waste Removal",
                "desc": "Garbage collection and disposal for common areas",
                "accounts": [_acct("5530", "Trash & Waste Removal", "EXPENSE", group="Utilities", desc="Garbage collection and disposal services")],
            },
            {
                "id": "stormwater",
                "label": "Stormwater / Drainage Fees",
                "desc": "Municipal stormwater utility charges",
                "accounts": [_acct("5540", "Stormwater & Drainage", "EXPENSE", group="Utilities", desc="Stormwater utility and drainage fees")],
            },
        ],
    },
    {
        "id": "exterior",
        "label": "Exterior Maintenance & Repairs",
        "options": [
            {
                "id": "roofing",
                "label": "Roof Repairs",
                "desc": "Patching, flashing, gutter cleaning — non-capital repairs",
                "accounts": [_acct("5600", "Roof Repairs", "EXPENSE", group="Exterior Maintenance", desc="Non-capital roof patching, flashing, and repairs")],
            },
            {
                "id": "siding",
                "label": "Siding, Stucco & Exterior Walls",
                "desc": "Repairs and maintenance of building exteriors",
                "accounts": [_acct("5610", "Siding & Exterior Repairs", "EXPENSE", group="Exterior Maintenance", desc="Siding, stucco, trim, and exterior wall repairs")],
            },
            {
                "id": "fencing",
                "label": "Fencing & Gates",
                "desc": "Fence repairs, gate hardware, and perimeter maintenance",
                "accounts": [_acct("5620", "Fence & Gate Repairs", "EXPENSE", group="Exterior Maintenance", desc="Repair and upkeep of fences, gates, and perimeter")],
            },
            {
                "id": "painting",
                "label": "Painting & Refinishing",
                "desc": "Exterior paint, staining, sealing",
                "accounts": [_acct("5630", "Painting & Refinishing", "EXPENSE", group="Exterior Maintenance", desc="Exterior painting, staining, and surface refinishing")],
            },
            {
                "id": "paving",
                "label": "Roads, Paving & Concrete",
                "desc": "Pothole repairs, crack sealing, concrete patching",
                "accounts": [_acct("5640", "Roads, Paving & Concrete", "EXPENSE", group="Exterior Maintenance", desc="Road repairs, asphalt patching, and concrete maintenance")],
            },
            {
                "id": "windows_doors",
                "label": "Windows & Doors",
                "desc": "Common area door hardware, window repairs, weather stripping",
                "accounts": [_acct("5650", "Windows & Doors", "EXPENSE", group="Exterior Maintenance", desc="Common area window and door repairs")],
            },
            {
                "id": "janitorial",
                "label": "Janitorial & Cleaning",
                "desc": "Cleaning of common buildings, lobbies, and exterior areas",
                "accounts": [_acct("5660", "Janitorial & Cleaning", "EXPENSE", group="Exterior Maintenance", desc="Cleaning services for common areas and buildings")],
            },
            {
                "id": "lighting",
                "label": "Street & Common Area Lighting",
                "desc": "Streetlight maintenance, bulb replacement, electrical repairs",
                "accounts": [_acct("5670", "Street & Common Area Lighting", "EXPENSE", group="Exterior Maintenance", desc="Maintenance and repair of common area lighting")],
            },
            {
                "id": "signage",
                "label": "Signage",
                "desc": "Entry signs, street signs, community notices",
                "accounts": [_acct("5680", "Signage", "EXPENSE", group="Exterior Maintenance", desc="Common area signs, community entry monument maintenance")],
            },
        ],
    },
    {
        "id": "mechanical",
        "label": "Mechanical Systems",
        "options": [
            {
                "id": "hvac",
                "label": "HVAC Maintenance",
                "desc": "Heating and cooling system service for common buildings",
                "accounts": [_acct("5700", "HVAC Maintenance", "EXPENSE", group="Mechanical", desc="Heating, ventilation, and cooling system maintenance")],
            },
            {
                "id": "plumbing",
                "label": "Plumbing Repairs",
                "desc": "Leaks, drain clearing, pipe repairs in common areas",
                "accounts": [_acct("5710", "Plumbing Repairs", "EXPENSE", group="Mechanical", desc="Common area plumbing service and repairs")],
            },
            {
                "id": "electrical",
                "label": "Electrical System Maintenance",
                "desc": "Panel service, wiring, outlet repairs in common areas",
                "accounts": [_acct("5720", "Electrical Maintenance", "EXPENSE", group="Mechanical", desc="Common area electrical system maintenance and repairs")],
            },
            {
                "id": "fire_systems",
                "label": "Fire Suppression & Safety Systems",
                "desc": "Sprinkler system inspections, fire extinguisher service",
                "accounts": [_acct("5730", "Fire & Safety Systems", "EXPENSE", group="Mechanical", desc="Fire suppression, sprinkler, and safety system maintenance")],
            },
        ],
    },
    {
        "id": "financial",
        "label": "Financial & Administrative",
        "options": [
            {
                "id": "bank_fees",
                "label": "Bank Fees & Charges",
                "desc": "Monthly service fees, wire transfer fees, lockbox fees",
                "accounts": [_acct("5900", "Bank Fees & Charges", "EXPENSE", group="Financial", desc="Bank service charges, wire fees, and lockbox fees")],
            },
            {
                "id": "bad_debt",
                "label": "Bad Debt / Write-offs",
                "desc": "Uncollectible homeowner balances written off",
                "accounts": [_acct("5910", "Bad Debt Expense", "EXPENSE", group="Financial", desc="Write-off of uncollectible homeowner assessment balances")],
            },
            {
                "id": "reserve_contribution",
                "label": "Reserve Fund Contribution",
                "desc": "Budgeted transfer from operating fund to reserves",
                "accounts": [_acct("5920", "Reserve Fund Contribution", "EXPENSE", group="Financial", desc="Budgeted operating-to-reserve transfer expense")],
            },
            {
                "id": "misc_expense",
                "label": "Miscellaneous Expenses",
                "desc": "Incidental costs not captured elsewhere",
                "accounts": [_acct("5990", "Miscellaneous Expense", "EXPENSE", group="Financial", desc="Miscellaneous operating expenses not classified elsewhere")],
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Step 5 — Reserve Accounts (only if reserve fund selected in Step 1)
# ---------------------------------------------------------------------------

STEP5_OPTIONS = [
    {
        "id": "res_roof",
        "label": "Roofing",
        "desc": "Full roof replacement on HOA-maintained buildings",
        "accounts": [_acct("6100", "Reserve — Roof Replacement", "EXPENSE", fund="RESERVE", desc="Full roof replacement for HOA-maintained structures")],
    },
    {
        "id": "res_building_ext",
        "label": "Building Exterior / Siding",
        "desc": "Full replacement of siding, stucco, or building envelope",
        "accounts": [_acct("6110", "Reserve — Building Exterior Replacement", "EXPENSE", fund="RESERVE", desc="Major building envelope, siding, or stucco replacement")],
    },
    {
        "id": "res_fencing",
        "label": "Fencing & Perimeter Walls",
        "desc": "Full fence or retaining wall replacement",
        "accounts": [_acct("6120", "Reserve — Fence & Wall Replacement", "EXPENSE", fund="RESERVE", desc="Replacement of perimeter fences and retaining walls")],
    },
    {
        "id": "res_paving",
        "label": "Roads & Paving",
        "desc": "Full pavement overlay or replacement of private roads and lots",
        "accounts": [_acct("6200", "Reserve — Road & Pavement Replacement", "EXPENSE", fund="RESERVE", desc="Full road, parking lot, and pavement replacement")],
    },
    {
        "id": "res_concrete",
        "label": "Concrete (Walks, Curbs, Stairs)",
        "desc": "Large-scale concrete replacement throughout the community",
        "accounts": [_acct("6210", "Reserve — Concrete Replacement", "EXPENSE", fund="RESERVE", desc="Replacement of community sidewalks, curbs, and stairs")],
    },
    {
        "id": "res_painting",
        "label": "Exterior Painting",
        "desc": "Community-wide exterior repainting cycle",
        "accounts": [_acct("6220", "Reserve — Exterior Painting", "EXPENSE", fund="RESERVE", desc="Scheduled full community exterior repainting")],
    },
    {
        "id": "res_hvac",
        "label": "HVAC System Replacement",
        "desc": "Full replacement of heating/cooling systems in common buildings",
        "accounts": [_acct("6400", "Reserve — HVAC Replacement", "EXPENSE", fund="RESERVE", desc="Replacement of HVAC systems in common area buildings")],
    },
    {
        "id": "res_plumbing",
        "label": "Plumbing System",
        "desc": "Major common area plumbing replacement or re-piping",
        "accounts": [_acct("6410", "Reserve — Plumbing System", "EXPENSE", fund="RESERVE", desc="Major re-piping or plumbing system replacement")],
    },
    {
        "id": "res_electrical",
        "label": "Electrical System",
        "desc": "Panel upgrades, rewiring, or electrical infrastructure",
        "accounts": [_acct("6420", "Reserve — Electrical System", "EXPENSE", fund="RESERVE", desc="Major electrical infrastructure upgrades or rewiring")],
    },
    {
        "id": "res_fire",
        "label": "Fire Suppression System",
        "desc": "Full replacement of fire sprinkler or suppression system",
        "accounts": [_acct("6430", "Reserve — Fire Suppression System", "EXPENSE", fund="RESERVE", desc="Replacement of fire suppression and safety systems")],
    },
    {
        "id": "res_irrigation",
        "label": "Irrigation System",
        "desc": "Full replacement of community-wide irrigation infrastructure",
        "accounts": [_acct("6510", "Reserve — Irrigation System Replacement", "EXPENSE", fund="RESERVE", desc="Replacement of main irrigation lines and control systems")],
    },
    {
        "id": "res_lighting",
        "label": "Street & Common Area Lighting",
        "desc": "LED conversion or full lighting fixture replacement",
        "accounts": [_acct("6520", "Reserve — Street Lighting Replacement", "EXPENSE", fund="RESERVE", desc="Community-wide lighting upgrade or fixture replacement")],
    },
    {
        "id": "res_other",
        "label": "Other Capital Projects",
        "desc": "Major projects not covered by the categories above",
        "accounts": [_acct("6600", "Reserve — Other Capital Projects", "EXPENSE", fund="RESERVE", desc="Reserve funding for other major capital expenditures")],
    },
]

# ---------------------------------------------------------------------------
# Public API used by WizardService
# ---------------------------------------------------------------------------

STEPS = [
    {"number": 1, "title": "Funds",           "subtitle": "Which funds does your HOA maintain?"},
    {"number": 2, "title": "Income",          "subtitle": "How does your HOA collect money?"},
    {"number": 3, "title": "Amenities",       "subtitle": "What does your community have?"},
    {"number": 4, "title": "Operating Costs", "subtitle": "What does your HOA pay for?"},
    {"number": 5, "title": "Reserves",        "subtitle": "What major assets will eventually need replacement?"},
]
