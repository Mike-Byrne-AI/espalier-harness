"""pyproject.toml's pytest table, read once for every test that needs it.

The suite contract (`tests/test_test_suite_contract.py`) and the ReDoS file's
two timing arms (`tests/test_redos.py`: the PowerShell body arm's timeout pin
and the walker row's time budget) each read the per-test `timeout` pyproject
declares. One reader, scoped to `[tool.pytest.ini_options]`, so a `timeout`
key in another table can never stand in for it (DEF-5023's review: a reader of
the whole file took the first `timeout =` it met).
"""
from __future__ import annotations

import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
PYTEST_INI_SECTION = "[tool.pytest.ini_options]"


def pytest_ini_section() -> str:
    """The text of pyproject.toml's ``[tool.pytest.ini_options]`` table."""
    text = PYPROJECT.read_text(encoding="utf-8")
    start = text.find(PYTEST_INI_SECTION)
    assert start >= 0, f"pyproject.toml has no {PYTEST_INI_SECTION}"
    nxt = text.find("\n[tool", start + len(PYTEST_INI_SECTION))
    return text[start:] if nxt < 0 else text[start:nxt]


def declared_pytest_timeout() -> int:
    """pyproject.toml's `[tool.pytest.ini_options] timeout`, READ not copied:
    the per-test ceiling the suite declares (a run can raise it with
    `PYTEST_TIMEOUT`, `--timeout` or a test's own mark; this is the declared one)."""
    match = re.search(r"^\s*timeout\s*=\s*(\d+)\s*$", pytest_ini_section(), re.MULTILINE)
    assert match, (
        f"pyproject.toml {PYTEST_INI_SECTION} declares no `timeout` -- the "
        "contracts that compare against the per-test ceiling have none to read"
    )
    return int(match.group(1))
