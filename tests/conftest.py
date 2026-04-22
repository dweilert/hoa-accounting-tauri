"""Shared pytest setup.

Monkey-patches :func:`sqlite3.connect` to register the ``audit_user``
UDF on every connection the way the production ``connect_sqlite`` helper
does. Audit triggers in migrations 0049+ call ``audit_user()``; tests
that create raw in-memory connections (via ``sqlite3.connect(':memory:')``
inside per-file ``build_conn()`` helpers) would otherwise fail with
``no such function: audit_user``.

Autouse at session scope so every test benefits without any edits to
individual test files.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture(autouse=True, scope="session")
def _register_audit_user_udf():
    """Wrap ``sqlite3.connect`` once for the whole session."""
    original_connect = sqlite3.connect

    def connect_with_audit_user(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.create_function("audit_user", 0, lambda: "test")
        return conn

    sqlite3.connect = connect_with_audit_user  # type: ignore[assignment]
    try:
        yield
    finally:
        sqlite3.connect = original_connect  # type: ignore[assignment]
