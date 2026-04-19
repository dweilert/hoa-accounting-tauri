-- Local authentication users and role overrides for the HOA accounting system.
-- Supports both standalone local auth and role overrides for Cognito-authenticated users.

CREATE TABLE IF NOT EXISTS local_users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    display_name    TEXT    NOT NULL DEFAULT '',
    role            TEXT    NOT NULL DEFAULT 'reports'
                            CHECK(role IN ('admin', 'reports')),
    password_hash   TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_login_at   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS local_role_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    role        TEXT    NOT NULL CHECK(role IN ('admin', 'reports')),
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
