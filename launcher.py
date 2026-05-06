"""
HOA Accounting — desktop launcher.

Starts a local Flask server on an available port, waits until it accepts
connections, then opens the default browser. Keeps running until the window
is closed or the user presses Ctrl-C.

Usage (development):
    python launcher.py

Usage (installed bundle):
    Double-click HOAAccounting.exe / HOAAccounting.app
"""
from __future__ import annotations

import os
import socket
import sys
import textwrap
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# ── Path helpers ──────────────────────────────────────────────────────────────

def resource_path(relative: str) -> Path:
    """Resolve a bundled resource path (handles PyInstaller _MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def data_dir() -> Path:
    """Platform-appropriate user-writable data directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", str(Path.home()))
        return Path(appdata) / "HOAAccounting"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HOAAccounting"
    # Linux / fallback
    return Path.home() / ".hoa_accounting"


def find_config() -> Path | None:
    """Locate config.yaml: next to the exe first, then in the data directory."""
    # When frozen the exe sits in its own dir; in dev, __file__ is repo root.
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    candidate = exe_dir / "config.yaml"
    if candidate.exists():
        return candidate
    return data_dir() / "config.yaml" if (data_dir() / "config.yaml").exists() else None


_STARTER_CONFIG = textwrap.dedent("""\
    hoa:
      name: "My HOA"
      legal_name: "My Homeowners Association, Inc."
      tax_id_federal: ""
      tax_id_state: ""

    database:
      type: "sqlite"
      path: "{db_path}"

    backup:
      dir: "{backup_dir}"
      max_keep: 10

    app:
      environment: "local"
      debug: false

    accounting:
      fiscal_year_start_month: 1
      default_fund: "OPERATING"
      resale_fee_default_amount: "175.00"

    auth:
      backend: "local"
      session_secret: "{secret}"
""")


def ensure_config() -> Path:
    """Return the config path, creating a starter config + DB dir if needed."""
    existing = find_config()
    if existing:
        return existing

    import secrets as _secrets

    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    db_path = d / "hoa_accounting.db"
    backup_dir = d / "backups"
    config_path = d / "config.yaml"
    secret = _secrets.token_hex(32)

    config_path.write_text(
        _STARTER_CONFIG.format(
            db_path=str(db_path).replace("\\", "/"),
            backup_dir=str(backup_dir).replace("\\", "/"),
            secret=secret,
        ),
        encoding="utf-8",
    )
    print(f"Created starter config: {config_path}")
    return config_path


# ── Port helpers ──────────────────────────────────────────────────────────────

def find_free_port(start: int = 5000, stop: int = 5020) -> int:
    """Return the first available TCP port in [start, stop)."""
    for port in range(start, stop):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start  # give up gracefully; Flask will surface the bind error


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    """Poll until the server responds or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config_path = ensure_config()
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"

    print(f"Starting HOA Accounting on {url}")
    print(f"Config: {config_path}")
    print("Press Ctrl-C to stop the server.")

    # Add the bundled src/ directory to sys.path so hoa_accounting is importable
    # when running as a PyInstaller onedir bundle.
    src_path = resource_path("src")
    if src_path.exists() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from hoa_accounting.web.app import create_app

    app = create_app(config_path=str(config_path))

    def run_server() -> None:
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    if wait_for_server(url):
        webbrowser.open(url)
    else:
        print(f"Server did not start in time. Open {url} manually.")
        webbrowser.open(url)  # try anyway

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
