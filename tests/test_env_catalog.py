"""Pin every `os.environ.get("ESPALIER_*")` reader to `docs/ENV_CATALOG.md`.

A reader that doesn't appear in the catalog is an undeclared stealth
contract. New env vars must be cataloged before they ship.

Detection covers TWO call shapes (the live repo uses both):
- Literal:   `os.environ.get("ESPALIER_FOO")`
- Constant:  `ENV_VAR = "ESPALIER_FOO"`; `os.environ.get(ENV_VAR)`

Constant-form resolution walks module-level assignments
(`NAME = "ESPALIER_..."`) and binds them to any `os.environ.get(NAME)`
call in the same module. Without this, hooks like
`_maintenance_mode.py` (`ENV_VAR = "ESPALIER_MAINTENANCE_MODE"` then
`os.environ.get(ENV_VAR)`) silently bypass the catalog contract.
"""

import ast
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[1]
_CATALOG = _REPO / "docs" / "ENV_CATALOG.md"

_SCOPE_DIRS = ("espalier", "tools", "scripts", "tests")

# Vars in the catalog that are NOT accessed via `os.environ.get` /
# `os.getenv` — these would false-positive `test_catalog_has_no_dead_entries`
# because the AST walker only matches read-shape calls.
# CLAUDE_PROJECT_DIR: injected by Claude Code via hook protocol implicit
# environment.
# PYTHONPATH: accessed via `env.pop` / `env[]=` (write-shape) in
# post_write_check.py — modified for subprocess invocation, not read.
_IMPLICIT_READERS = {"CLAUDE_PROJECT_DIR", "PYTHONPATH"}

# A catalog table row: `| \`VAR\` | ...` — the leading cell is the variable.
_CATALOG_ROW_RE = re.compile(r"^\|\s*`(?P<var>[A-Z][A-Z0-9_]*)`\s*\|")

# A cited read site anywhere in that row. Scanned per-row rather than pinned to
# the Consumer(s) column, because that column is free-form: most rows name a
# bare module with no line, one names three modules, and a row may grow a
# second cited site later. Every `path.py:NN` token in the row gets checked.
_READ_SITE_RE = re.compile(r"`(?P<path>[\w./-]+\.py):(?P<line>\d+)`")

# Nearest-occurrence tolerance, in lines.
_READ_SITE_TOLERANCE = 15

# A drift no reasonable tolerance should forgive. Used by the earn-the-red as a
# FIXED reference point so the test cannot scale along with the constant it is
# pinning — and asserted to stay above _READ_SITE_TOLERANCE, which turns "widen
# the window" from a silent one-character edit into a visible decision.
_ABSURD_DRIFT = 200

# The catalog carries at least this many cited read sites. Without the floor a
# parse regression that matched ZERO rows would green vacuously — asserting
# nothing while reporting success.
_MIN_READ_SITES = 4


def _catalog_read_sites() -> list[tuple[str, str, int]]:
    """``(var, repo-relative path, cited line)`` for every catalog row that
    cites a concrete ``file.py:NN`` read site."""
    if not _CATALOG.exists():
        pytest.fail(f"{_CATALOG} missing; create per TP-137 §C")
    sites: list[tuple[str, str, int]] = []
    for line in _CATALOG.read_text(encoding="utf-8").splitlines():
        row = _CATALOG_ROW_RE.match(line)
        if not row:
            continue
        for cite in _READ_SITE_RE.finditer(line):
            sites.append(
                (row.group("var"), cite.group("path"), int(cite.group("line")))
            )
    return sites


def _is_recognized(var: str) -> bool:
    if var.startswith("ESPALIER_"):
        return True
    return var in {"CLAUDE_PROJECT_DIR", "TMPDIR", "PYTHONPATH"}


def _catalog_vars() -> set[str]:
    if not _CATALOG.exists():
        pytest.fail(f"{_CATALOG} missing; create per TP-137 §C")
    text = _CATALOG.read_text(encoding="utf-8")
    found: set[str] = set()
    for line in text.splitlines():
        if line.startswith("| `") and "` |" in line:
            var = line.split("`")[1]
            if var and var.isupper():
                found.add(var)
    return found


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Build a {NAME: "string_value"} map of module-level constants."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                constants[tgt.id] = node.value.value
    return constants


def _extract_var_from_call(call: ast.Call, constants: dict[str, str]) -> str:
    """Return the env var name an `os.environ.get(...)` / `os.getenv(...)`
    call reads, or empty string if not an env-read."""
    fn = call.func
    if not isinstance(fn, ast.Attribute):
        return ""
    fn_name = fn.attr
    if fn_name == "get":
        if not (isinstance(fn.value, ast.Attribute) and fn.value.attr == "environ"):
            return ""
        if not (isinstance(fn.value.value, ast.Name) and fn.value.value.id == "os"):
            return ""
    elif fn_name == "getenv":
        if not (isinstance(fn.value, ast.Name) and fn.value.id == "os"):
            return ""
    else:
        return ""
    if not call.args:
        return ""
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name) and arg.id in constants:
        return constants[arg.id]
    return ""


def _live_readers() -> dict[str, list[str]]:
    """Walk source via AST; return {var_name: [reader_path, ...]}."""
    readers: dict[str, list[str]] = {}
    for scope in _SCOPE_DIRS:
        for path in (_REPO / scope).rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            constants = _module_string_constants(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                var = _extract_var_from_call(node, constants)
                if not var or not _is_recognized(var):
                    continue
                rel = str(path.relative_to(_REPO)).replace("\\", "/")
                readers.setdefault(var, []).append(rel)
    return readers


def test_every_live_reader_is_cataloged() -> None:
    cataloged = _catalog_vars()
    readers = _live_readers()
    uncatalogued = sorted(set(readers) - cataloged)
    assert not uncatalogued, (
        f"env vars read in source but not in docs/ENV_CATALOG.md: {uncatalogued}. "
        "Add the row to the catalog before merging."
    )


def test_catalog_has_no_dead_entries() -> None:
    """Catch the reverse drift: var listed in catalog but no live reader."""
    cataloged = _catalog_vars()
    readers = _live_readers()
    dead = sorted(c for c in cataloged if c not in readers)
    # Allow implicit readers — vars consumed via hook-protocol injection
    # (CLAUDE_PROJECT_DIR) or write-shape mutation (PYTHONPATH) rather
    # than `os.environ.get`. Documented explicit reader sites only.
    dead = [d for d in dead if d not in _IMPLICIT_READERS]
    assert not dead, (
        f"docs/ENV_CATALOG.md lists vars with no live reader: {dead}. "
        "Either remove the row or document why the reader is implicit."
    )


def test_env_catalog_read_sites_are_fresh() -> None:
    """Every cited `file.py:NN` read site still points at its variable.

    This catalog is deliberately excluded from the tree-wide line-anchor scan
    (`tests/test_catalog_self_consistency.py::_ANCHOR_SCAN_EXCLUDE_DOCS`), and
    that exclusion is CORRECT: the tree-wide resolver looks up AST symbols, and
    an env-var name appearing in a comment or a subprocess `env` dict is not
    one. Un-excluding the file would red-lock it on a check that cannot
    evaluate its citation shape. What was not correct is the consequence — the
    shape ended up checked by nothing at all, and every anchor drifted. This is
    the purpose-built replacement for the coverage the exclusion costs.

    Nearest-occurrence, not exact-line. An exact-line rule reds on any
    insertion above the cited line — which is precisely how these drifted — and
    would demand a doc edit on every unrelated change to a cited file. The
    looseness is the design, not a concession.

    On `_READ_SITE_TOLERANCE`, and why not to re-tune it blind: when the value
    was chosen the four live drifts measured -2, +32, +138 and +141. Any
    threshold between roughly 5 and 30 yields the same verdict, so the number
    is nowhere near finely balanced — the in-tolerance anchor and the drifted
    ones are two orders of magnitude apart. `PYTHONPATH` is the built-in
    negative control: it sits inside the window on purpose. **A change that
    makes this test red on EVERY cited row has not tightened the check, it has
    collapsed it into an exact-line match** — the maintenance tax this guard
    exists to avoid. Widen the window if it false-fires; do not shrink it to
    manufacture a red.

    What this does NOT cover: a variable that still appears near its cited line
    but for an unrelated reason (a comment mentioning it, say) reads as fresh.
    The check is that the anchor still lands you in the right neighbourhood,
    not that the neighbourhood is a read.
    """
    sites = _catalog_read_sites()
    assert len(sites) >= _MIN_READ_SITES, (
        f"parsed {len(sites)} cited read sites from docs/ENV_CATALOG.md, "
        f"expected at least {_MIN_READ_SITES}. Most likely the table shape "
        "changed — fix _CATALOG_ROW_RE / _READ_SITE_RE. If a row LEGITIMATELY "
        "dropped its `:NN` (the drift-proof remedy the sibling anchor scan "
        "recommends), remove that row from the derived set and say so — do NOT "
        "lower this floor to absorb it. Lowering it once per row ratchets the "
        "floor to zero and the guard ends up asserting over nothing."
    )
    _check_read_sites_fresh(sites)


def _check_read_sites_fresh(sites: list[tuple[str, str, int]]) -> None:
    """Assert every ``(var, path, cited-line)`` still resolves within tolerance.

    Split out from the test so the comparison is INJECTABLE. Written inline it
    could only be exercised through the live catalog, and once that catalog is
    correct there is no input left that reds — so widening
    ``_READ_SITE_TOLERANCE`` to a billion would leave a permanently green test
    that checks nothing. ``test_earn_the_red_read_site_drift`` closes that by
    handing this function a known-stale pair directly.
    """
    stale: list[str] = []
    for var, rel, cited in sites:
        target = _REPO / rel
        if not target.exists():
            stale.append(f"{var}: cited file {rel} does not exist")
            continue
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            stale.append(f"{var}: cited file {rel} unreadable ({exc})")
            continue
        # Word-boundary, not substring: the catalog already carries a prefix
        # pair (`ESPALIER_STOP_GATE` and `ESPALIER_STOP_GATE_TEST_CMD`), and a
        # substring test lets the longer name satisfy the shorter one's anchor —
        # 8 of 13 apparent hits for the short name are the long one.
        pattern = re.compile(rf"\b{re.escape(var)}\b")
        hits = [n for n, text in enumerate(lines, start=1) if pattern.search(text)]
        if not hits:
            stale.append(
                f"{var}: does not appear anywhere in {rel} — the read site "
                "moved to another file, or the variable was renamed"
            )
            continue
        if cited < 1:
            stale.append(f"{var}: cited {rel}:{cited}; line numbers are 1-based")
            continue
        nearest = min(hits, key=lambda n: abs(n - cited))
        drift = nearest - cited
        if abs(drift) > _READ_SITE_TOLERANCE:
            stale.append(
                f"{var}: cited {rel}:{cited}, nearest occurrence is "
                f"{rel}:{nearest} (drift {drift:+d}, tolerance "
                f"±{_READ_SITE_TOLERANCE})"
            )

    assert not stale, (
        "docs/ENV_CATALOG.md read-site anchors have drifted:\n  "
        + "\n  ".join(stale)
        + "\nCorrect each cited line to the reported nearest occurrence, then "
        "re-run `python3 scripts/sync_asset_docs.py` to regenerate the twin."
    )


def test_earn_the_red_read_site_drift() -> None:
    """The comparison fires on a stale anchor and clears on a correct one.

    Without this, the guard's only red lived in the transcript of the session
    that wrote it. Measured: setting ``_READ_SITE_TOLERANCE`` to 10**9 left
    ``test_env_catalog_read_sites_are_fresh`` GREEN — the floor catches a regex
    collapse but nothing caught a comparison that can never fire.
    """
    var, rel = "ESPALIER_AUDIT_DIR", "tools/cc/hooks/_integrity.py"
    live = [
        n
        for n, text in enumerate(
            (_REPO / rel).read_text(encoding="utf-8").splitlines(), start=1
        )
        if re.search(rf"\b{var}\b", text)
    ]
    assert live, f"fixture premise gone: {var} no longer appears in {rel}"
    # Offset from the LAST occurrence, not the first. Occurrences of a variable
    # cluster around its read site, so a shift measured from the first one lands
    # near a later one and greens — the same property that makes a blanket
    # "re-point it 20 lines" mutation unreliable here. Only a shift clear of
    # `max(live)` is guaranteed to exceed the tolerance for every occurrence.
    #
    # _ABSURD_DRIFT is a FIXED number and deliberately not derived from
    # _READ_SITE_TOLERANCE. Scaling it to the constant makes this test move with
    # the mutation it exists to catch: a maintainer widening the tolerance to a
    # billion would leave a self-scaling fixture still passing, which is exactly
    # the hole this test was added to close.
    with pytest.raises(AssertionError, match="drift"):
        _check_read_sites_fresh([(var, rel, max(live) + _ABSURD_DRIFT)])
    _check_read_sites_fresh([(var, rel, live[0])])  # correct line -> no raise
    assert _READ_SITE_TOLERANCE < _ABSURD_DRIFT, (
        f"_READ_SITE_TOLERANCE ({_READ_SITE_TOLERANCE}) has been widened past "
        f"the {_ABSURD_DRIFT}-line offset this test calls unambiguous rot. "
        "Widening it that far is a real decision, not a tuning nudge — make it "
        "deliberately and raise _ABSURD_DRIFT with a stated reason."
    )


def test_earn_the_red_read_site_absent_from_file() -> None:
    """The other branch: a variable that has left the cited file entirely — the
    shape a rename produces, and the reason the check is not merely a line
    comparison."""
    with pytest.raises(AssertionError, match="does not appear anywhere"):
        _check_read_sites_fresh(
            [("ESPALIER_NO_SUCH_VAR_XYZ", "tools/cc/hooks/_integrity.py", 1)]
        )
