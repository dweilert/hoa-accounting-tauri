# Initialization Guide

This package now supports config-driven database initialization.

## Single source of truth

The database path now comes from:

- `config.yaml`

Current configured path:

- `/Users/bob/hoa-system/data/hoa_accounting.db`

## How to initialize the database

From the project root, run:

```bash
python initialize_database.py
```

The script will:
- load `config.yaml`
- create the SQLite database at the configured path
- install the base schema
- create the HOA profile row
- create the initial admin user
- seed roles
- seed account types
- seed starter chart of accounts
- seed bank accounts
- seed accounting periods
- seed a starter assessment rule
- seed demo master data so the example scripts can run immediately

## Demo records seeded

The initializer now adds these minimal records by default:

- `lots.id = 1`
- `owners.id = 1`
- `lot_ownership.id = 1`
- `vendors.id = 1`

That means:
- `python example_usage.py`
- `python example_reporting_usage.py`

can run after initialization without manual inserts.

## Important note

If the database file already exists, initialization will stop rather than overwriting it.

That is intentional.

If you want to recreate the database, delete the existing file first.

## What to configure first

Before running initialization, review:

- `config.yaml`

You should update:
- HOA name
- legal name
- Federal tax ID
- State tax ID

Later, we can extend initialization so bank names, bank account last-4 values, assessment amounts, and fiscal year also come from config.
