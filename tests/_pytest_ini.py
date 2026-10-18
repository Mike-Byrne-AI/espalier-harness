"""pyproject.toml's pytest table, read once for every test that needs it.

The suite contract (`tests/test_test_suite_contract.py`) and the ReDoS file's
two timing arms (`tests/test_redos.py`: the PowerShell body arm's timeout pin
and the walker row's time budget) each read the per-test `timeout` pyproject
declares. One reader, scoped to the `[tool.pytest.ini_options]` table (its
header at a line's start, up to the next table header), so a `timeout` key in
another table does not stand in for it (DEF-5023's review: a reader of the
whole file took the first `timeout =` it met). A value it cannot read, such as
one with a trailing comment or a float, fails the assertion loudly rather than
reading as none.
"""
from __future__ import annotations

import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
PYTEST_INI_SECTION = "[tool.pytest.ini_options]"


def pytest_ini_section() -> str:
    """The text of pyproject.toml's ``[tool.pytest.ini_options]`` table: from its
    header, at a line's start, to the next table header at a line's start."""
    text = PYPROJECT.read_text(encoding="utf-8")
    header = re.search(rf"^{re.escape(PYTEST_INI_SECTION)}[ \t]*$", text, re.MULTILINE)
    assert header is not None, f"pyproject.toml has no {PYTEST_INI_SECTION}"
    nxt = re.compile(r"^\[", re.MULTILINE).search(text, header.end())
    # up to, not including, the newline that ends the table's last line
    return text[header.start():] if nxt is None else text[header.start():nxt.start() - 1]


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
