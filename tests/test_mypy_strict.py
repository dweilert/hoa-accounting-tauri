"""Run mypy on a filtered subset of error codes and fail on new bugs.

Full ``--strict-optional`` produces ~700 errors against this codebase,
mostly noise (untyped generics, the Flask redirect/Response quirk,
``int(row['id'])`` against ``sqlite3.Row.__getitem__: int | None``). This
test runs mypy and only inspects the error categories that have
historically caught real bugs:

- ``name-defined``  — undefined name (caught a real ``NameError``
  in bank_statement_pages.py:1026)
- ``call-overload`` — calling something with the wrong type (the
  pattern that hides ``int(some_object)`` mistakes)

A baseline of known-acceptable errors is encoded in ``BASELINE`` below.
Any error of the watched codes that isn't on the baseline fails the
test, with a message pointing at the offending file:line.

To accept a new pre-existing error: add it to the baseline.
To fix a real bug: edit the source. The baseline shrinks naturally as
the codebase improves.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _REPO_ROOT / "src" / "hoa_accounting"


# Error codes whose mypy reports have historically been actionable
# rather than noise. The first two each caught real bugs in this
# codebase; the rest were added once the wider --strict-optional
# pass landed at zero errors (commit 16c170d), so any regression in
# any of these categories surfaces immediately.
WATCHED_CODES = (
    "name-defined",
    "call-overload",
    "union-attr",
    "assignment",
    "arg-type",
    "attr-defined",
    "no-any-return",
    "no-untyped-def",
    "type-arg",
    "var-annotated",
    "valid-type",
    "return-value",
    "misc",
)


# Pre-existing errors accepted as not-a-bug. Each entry is a
# ``(relative_path, line, code)`` triple. Lines may shift as files are
# edited — when that happens, update the baseline.
#
# To remove an entry: fix the underlying issue in the source.
# To add an entry: confirm it's truly noise (e.g., a loose
# ``int(form_data.get(...))`` whose runtime value is always a string).
BASELINE: set[tuple[str, int, str]] = set()


_LINE_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+): error: .*\[(?P<code>[a-z-]+)\]\s*$"
)


def _parse_mypy_line(raw: str) -> tuple[str, int, str] | None:
    m = _LINE_RE.match(raw.strip())
    if not m:
        return None
    return m.group("path"), int(m.group("line")), m.group("code")


def test_mypy_strict_subset() -> None:
    try:
        import mypy  # noqa: F401
    except ImportError:
        pytest.skip("mypy not installed")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--ignore-missing-imports",
            "--strict-optional",
            str(_SRC_ROOT),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )

    new_errors: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        parsed = _parse_mypy_line(line)
        if parsed is None:
            continue
        abs_path, line_no, code = parsed
        if code not in WATCHED_CODES:
            continue
        try:
            rel = str(Path(abs_path).resolve().relative_to(_SRC_ROOT))
        except ValueError:
            rel = abs_path
        if (rel, line_no, code) in BASELINE:
            continue
        new_errors.append((rel, line_no, code))

    if new_errors:
        msg = (
            "New mypy errors in watched categories — likely real bugs.\n"
            "Either fix the source, or (after confirming it's noise) add "
            "the entry to BASELINE in tests/test_mypy_strict.py.\n\n"
            + "\n".join(f"  {rel}:{ln} [{code}]" for rel, ln, code in new_errors)
        )
        pytest.fail(msg)
