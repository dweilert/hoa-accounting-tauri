# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for HOA Accounting desktop bundle."""

import sys
from pathlib import Path

block_cipher = None

# Repo root (where this .spec lives)
ROOT = Path(SPECPATH)

# Collect all migrations SQL files
migration_files = [
    (str(p), "src/hoa_accounting/migrations")
    for p in sorted((ROOT / "src/hoa_accounting/migrations").glob("*.sql"))
]

# Collect templates and static assets
template_files = [
    (str(ROOT / "src/hoa_accounting/web/templates"), "src/hoa_accounting/web/templates"),
]
static_files = [
    (str(ROOT / "src/hoa_accounting/web/static"), "src/hoa_accounting/web/static"),
]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=migration_files + template_files + static_files,
    hiddenimports=[
        # Flask and Jinja2
        "flask",
        "jinja2",
        "jinja2.ext",
        "werkzeug",
        "werkzeug.routing",
        "werkzeug.middleware",
        # YAML
        "yaml",
        # boto3 / botocore (S3 backup)
        "boto3",
        "botocore",
        "botocore.loaders",
        "botocore.regions",
        "botocore.handlers",
        "botocore.auth",
        # hoa_accounting packages
        "hoa_accounting",
        "hoa_accounting.web",
        "hoa_accounting.web.app",
        "hoa_accounting.web.routes",
        "hoa_accounting.web.routes.admin",
        "hoa_accounting.web.routes.api",
        "hoa_accounting.web.routes.bank",
        "hoa_accounting.web.routes.budget",
        "hoa_accounting.web.routes.categories",
        "hoa_accounting.web.routes.dashboard",
        "hoa_accounting.web.routes.homeowners",
        "hoa_accounting.web.routes.periods",
        "hoa_accounting.web.routes.reports",
        "hoa_accounting.web.routes.setup",
        "hoa_accounting.web.routes.vendors",
        "hoa_accounting.bootstrap",
        "hoa_accounting.bootstrap.migrator",
        "hoa_accounting.bootstrap.backup_service",
        "hoa_accounting.bootstrap.s3_sync",
        "hoa_accounting.bootstrap.audit_triggers",
        "hoa_accounting.bootstrap.initializer",
        "hoa_accounting.auth",
        "hoa_accounting.auth.factory",
        "hoa_accounting.auth.local",
        "hoa_accounting.config",
        "hoa_accounting.config.loader",
        "hoa_accounting.config.models",
        "hoa_accounting.db",
        "hoa_accounting.db.connection",
        "hoa_accounting.reporting",
        "hoa_accounting.services",
        "hoa_accounting.repositories",
        "hoa_accounting.validators",
        # Reporting / PDF
        "weasyprint",
        "reportlab",
        # Standard lib extras that may be missed
        "email.mime.multipart",
        "email.mime.text",
        "_sqlite3",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HOAAccounting",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # No terminal window on Windows
    icon=None,       # Set to 'assets/icon.ico' if you add one later
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HOAAccounting",
)
