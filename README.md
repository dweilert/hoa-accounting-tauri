# HOA Accounting Engine (Reporting Added)

This package is a refined starter accounting engine for the HOA schema.

## Added reporting modules

- `reporting/trial_balance.py`
- `reporting/general_ledger.py`

These reports are read-only and intended to be called by:
- the future web UI
- API routes
- admin scripts
- exports to CSV/PDF later

## Current scope

Posting workflows:
- assessment posting
- owner payment posting
- vendor bill posting
- vendor payment posting
- reserve transfer posting
- manual journal posting via `JournalService`

Reporting workflows:
- trial balance
- general ledger detail

## Typical development commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest
ruff check .
black --check .
mypy src
```
