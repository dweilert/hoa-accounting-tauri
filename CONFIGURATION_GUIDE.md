# Configuration Guide

This package now uses a single `config.yaml` file at the project root.

## Main configuration file

- `config.yaml`

This is where you set:
- HOA name
- legal HOA name
- Federal tax ID
- State tax ID
- SQLite database path
- environment flags
- accounting defaults

## Example

```yaml
hoa:
  name: "MMPOA-IIA"
  legal_name: "Mountain Master Property Owners Association II-A"
  tax_id_federal: "99-9999999"
  tax_id_state: "TX-9999999"

database:
  type: "sqlite"
  path: "./data/hoa_accounting.db"

app:
  environment: "local"
  debug: true

accounting:
  fiscal_year_start_month: 1
  default_fund: "OPERATING"
```

## Important note

The tax IDs are currently stored in the YAML file as plain text for local development simplicity.

That is acceptable for early local development, but later you should move sensitive values to:
- environment variables
- OS keychain/credential storage
- AWS Secrets Manager or Parameter Store in cloud deployments

## How it is used

The code now loads configuration through:

- `hoa_accounting.config.loader.load_config`

That config object is then used by example scripts and can later be used by:
- FastAPI/Flask startup
- background jobs
- CLI tools
- installer/bootstrap logic

## Recommended folder layout

```text
project/
  config.yaml
  data/
    hoa_accounting.db
  src/
  tests/
```
