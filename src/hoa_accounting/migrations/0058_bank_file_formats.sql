-- Migration 0058: Saved column maps for CSV-style bank files.
--
-- When a user uploads a CSV from a bank we've never seen before, the
-- dispatcher routes through the mapping wizard. The saved mapping lives
-- in ``bank_account_file_formats`` keyed by ``(bank_account_id,
-- fingerprint)`` where fingerprint is a SHA of the normalized header row.
-- Subsequent uploads with the same headers are parsed silently using the
-- saved mapping.
--
-- ``bank_import_stash`` holds the raw upload in between the dispatcher
-- saying "needs mapping" and the user finishing the wizard. Tokens are
-- short-lived (cleaned up on successful ingest or on a periodic sweep).

BEGIN TRANSACTION;

CREATE TABLE bank_account_file_formats (
    id                   INTEGER PRIMARY KEY,
    bank_account_id      INTEGER NOT NULL
        REFERENCES bank_accounts(id) ON DELETE CASCADE,
    fingerprint          TEXT    NOT NULL,     -- hash of normalized headers
    mapping_json         TEXT    NOT NULL,     -- {canonical_field: csv_header}
    sample_headers_json  TEXT    NOT NULL,     -- preview for the UI
    created_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bank_account_id, fingerprint)
);

CREATE INDEX idx_bank_account_file_formats_acct
    ON bank_account_file_formats(bank_account_id);

CREATE TABLE bank_import_stash (
    token            TEXT    PRIMARY KEY,       -- short random id
    bank_account_id  INTEGER NOT NULL
        REFERENCES bank_accounts(id) ON DELETE CASCADE,
    filename         TEXT    NOT NULL DEFAULT '',
    file_content     BLOB    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
