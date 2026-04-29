"""Lint gate: run ruff + black against src/ and tests/.

Both tools are configured in ``pyproject.toml``. This test invokes
each in its check-only mode and fails if either reports issues. Pair
with the mypy gate at ``test_mypy_strict.py`` to catch style and
type drift in one pytest run.

To autoformat: ``.venv/bin/black src/hoa_accounting tests``.
To autofix lint: ``.venv/bin/ruff check --fix src/hoa_accounting tests``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGETS = [str(_REPO_ROOT / "src" / "hoa_accounting"), str(_REPO_ROOT / "tests")]


def test_ruff_clean() -> None:
    try:
        import ruff  # noqa: F401
    except ImportError:
        pytest.skip("ruff not installed")
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *_TARGETS],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    if proc.returncode != 0:
        pytest.fail(
            "ruff reported issues:\n\n" + proc.stdout + "\n"
            "Fix with: .venv/bin/ruff check --fix src/hoa_accounting tests"
        )


def test_black_clean() -> None:
    try:
        import black  # noqa: F401
    except ImportError:
        pytest.skip("black not installed")
    proc = subprocess.run(
        [sys.executable, "-m", "black", "--check", *_TARGETS],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    if proc.returncode != 0:
        pytest.fail(
            "black would reformat files:\n\n" + proc.stderr + "\n"
            "Fix with: .venv/bin/black src/hoa_accounting tests"
        )
