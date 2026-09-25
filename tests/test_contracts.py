"""Contract tests — turn ``docs/SHARP_EDGES.md`` entries into
automated assertions.

Each test corresponds to a documented footgun in SHARP_EDGES or
CLAUDE.md. If any test fails it means a documented contract has
been violated in code. Pins the doc-to-mechanical-enforcement
bridge: a sharp-edge entry is just a warning until a contract test
makes it CI-blocking. Without this layer the SHARP_EDGES catalog
would silently drift toward describing failures the code can still
cause, and adopters reading the doc would get advice that the
harness no longer enforces.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

from _legacy_pathlib import legacy_pathlib_probes, probes_raise_on_eacces
from espalier.scanners.encoding_contracts import NON_FILE_OPENERS
from _locked import locked
from espalier.cli import _build_settings_json

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
SCANNERS_DIR = REPO_ROOT / "espalier" / "scanners"
TOOLS_CC_DIR = REPO_ROOT / "tools" / "cc"
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"
MEMORY_PATH = REPO_ROOT / "ESPALIER_MEMORY.md"
README_PATH = REPO_ROOT / "README.md"
PLAN_GUARD_PATH = HOOKS_DIR / "plan_guard.py"

# stdlib modules allowed in scanners (from SHARP_EDGES.md + CLAUDE.md)
STDLIB_ALLOWLIST = {
    "os", "re", "sys", "ast", "json", "math", "pathlib", "typing",
    "collections", "itertools", "functools", "dataclasses",
    # commonly used stdlib extras
    "abc", "enum", "io", "copy", "string", "textwrap", "warnings",
    "contextlib", "types", "operator", "hashlib", "struct",
    "__future__",
}


# ---------------------------------------------------------------------------
# 1. Hook exit codes — no sys.exit(1) in governance paths
# ---------------------------------------------------------------------------

def _exit_one_call_sites(source: str, filename: str = "<hook>") -> list[int]:
    """Line numbers of ``sys.exit(1)`` OR bare ``exit(1)`` calls in *source*.

    TP-150 F-3: the bare-``exit(1)`` arm closes a detector gap. The pre-fix
    second branch tested ``func.attr == "exit"`` on an ``ast.Name`` (which
    has no ``.attr``), guarded by ``hasattr(func, "attr")`` -- so it could
    never fire, and a governance hook calling bare ``exit(1)`` slipped past.
    """
    tree = ast.parse(source, filename=filename)
    sites: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_exit = (
            isinstance(func, ast.Attribute)
            and func.attr == "exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sys"
        ) or (
            isinstance(func, ast.Name) and func.id == "exit"
        )
        if not is_exit:
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 1
        ):
            sites.append(node.lineno)
    return sites


class TestHookExitCodesNoStrayOne:
    """Hook scripts must not use sys.exit(1) for governance decisions.

    Governance protocol channels (per SHARP_EDGES.md "Hook Exit Codes — Channel XOR"):
      - exit 0 + JSON on stdout (structured, preferred)
      - exit 2 + reason on stderr (simple)

    sys.exit(1) is reserved for script bugs (uncaught exceptions, crash paths).
    Channel-XOR enforcement lives in tests/test_hook_protocol.py.
    """

    def test_no_stray_sys_exit_one(self):
        """Hook scripts must not call sys.exit(1)/exit(1) in governance paths."""
        violations = []
        for hook_file in HOOKS_DIR.glob("*.py"):
            if hook_file.name == "__init__.py" or hook_file.name.startswith("_"):
                continue
            source = hook_file.read_text(encoding="utf-8")
            for lineno in _exit_one_call_sites(source, str(hook_file)):
                violations.append(f"{hook_file.name}:{lineno} — exit(1)")
        assert not violations, (
            "Hook scripts must not use sys.exit(1) for governance decisions. "
            "Use exit 0 + JSON (structured) or exit 2 + stderr (simple). "
            "sys.exit(1) is reserved for script bugs.\n"
            + "\n".join(violations)
        )

    def test_detector_catches_bare_exit_one(self):
        """F-3 earn-the-red: a bare ``exit(1)`` (not ``sys.exit(1)``) must be
        flagged. Pre-fix the detector's second branch checked a non-existent
        attribute on ast.Name and never fired, so bare ``exit(1)`` slipped by."""
        assert _exit_one_call_sites("def main():\n    exit(1)\n") == [2]
        assert _exit_one_call_sites("import sys\nsys.exit(1)\n") == [2]
        # exit(0)/sys.exit(2) are not governance-bug signals -> ignored
        assert _exit_one_call_sites("exit(0)\nsys.exit(2)\n") == []


# ---------------------------------------------------------------------------
# 2. Hook wiring — every hook file is registered in settings.json
# ---------------------------------------------------------------------------

class TestHookWiring:
    def _get_hook_settings(self) -> dict:
        """Return hook settings from the generated template (not from disk).

        settings.json is gitignored (machine-detected interpreter name).
        We validate against the generated template instead.
        """
        return _build_settings_json()

    def test_every_hook_file_wired_in_settings(self):
        """Every .py in tools/cc/hooks/ (except __init__) must appear in generated settings."""
        settings = self._get_hook_settings()
        hooks_config = settings.get("hooks", {})

        wired_scripts: set[str] = set()
        for event_entries in hooks_config.values():
            for entry in event_entries:
                for hook in entry.get("hooks", []):
                    # TP-35: exec form puts the script path in args; the
                    # pre-TP-35 shell form embedded it in command. Walk
                    # both to survive the switchover.
                    tokens: list[str] = []
                    for arg in hook.get("args") or []:
                        if isinstance(arg, str):
                            tokens.append(arg)
                    cmd = hook.get("command", "")
                    if isinstance(cmd, str):
                        tokens.extend(cmd.split())
                    for tok in tokens:
                        clean = tok.strip('"\'')
                        if clean.endswith(".py"):
                            wired_scripts.add(Path(clean).name)

        hook_files = {
            f.name for f in HOOKS_DIR.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        }

        unwired = hook_files - wired_scripts
        assert not unwired, (
            f"Hook files exist but are not wired in generated settings: {unwired}\n"
            "Add them under the appropriate event in _build_settings_json()."
        )

    def test_every_wired_hook_exists_on_disk(self):
        """Every hook script referenced in generated settings must exist on disk."""
        settings = self._get_hook_settings()
        hooks_config = settings.get("hooks", {})

        missing = []
        for event_entries in hooks_config.values():
            for entry in event_entries:
                for hook in entry.get("hooks", []):
                    # TP-35: exec form puts the script in args; shell form
                    # embeds it in command. Inspect both.
                    candidates: list[str] = []
                    for arg in hook.get("args") or []:
                        if isinstance(arg, str):
                            candidates.append(arg)
                    cmd = hook.get("command", "")
                    if isinstance(cmd, str):
                        candidates.extend(cmd.split())
                    for part in candidates:
                        clean = part.strip('"\'')
                        if clean.endswith(".py") and "hooks" in clean:
                            script_name = Path(clean).name
                            if not (HOOKS_DIR / script_name).exists():
                                missing.append(f"{script_name} (referenced in settings template)")

        assert not missing, (
            "Hook scripts referenced in settings template do not exist on disk:\n"
            + "\n".join(missing)
        )

    # TP-35 cleanup: the pre-TP-35
    # ``test_hook_commands_follow_portability_contract`` asserted the
    # old shell-form contract (absolute interpreter + bare
    # $CLAUDE_PROJECT_DIR in command). Exec form has no interpreter
    # path to validate; the new contract — ``command == "python"`` plus
    # ``args[0]`` carries ``${CLAUDE_PROJECT_DIR}/...`` — is pinned in
    # ``tests/test_hook_exec_form.py``.


# ---------------------------------------------------------------------------
# 3. Scanner stdlib-only constraint
# ---------------------------------------------------------------------------

class TestScannersStdlibOnly:
    def test_scanners_stdlib_only(self):
        """espalier/scanners/*.py must only import stdlib modules."""
        violations = []
        for scanner_file in SCANNERS_DIR.glob("*.py"):
            if scanner_file.name == "__init__.py":
                continue
            source = scanner_file.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=str(scanner_file))
            except SyntaxError as e:
                violations.append(f"{scanner_file.name}: SyntaxError — {e}")
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in STDLIB_ALLOWLIST and top not in sys.stdlib_module_names:
                            violations.append(
                                f"{scanner_file.name}:{node.lineno} — "
                                f"non-stdlib import: {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module is None:
                        continue
                    top = node.module.split(".")[0]
                    if top not in STDLIB_ALLOWLIST and top not in sys.stdlib_module_names:
                        violations.append(
                            f"{scanner_file.name}:{node.lineno} — "
                            f"non-stdlib import: from {node.module}"
                        )

        assert not violations, (
            "espalier/scanners/ modules must be stdlib-only — no third-party deps.\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 4. tools/cc/ has zero espalier imports
# ---------------------------------------------------------------------------

def _scan_for_espalier_imports(root: Path) -> list[str]:
    """Return ``espalier``-import violation strings for every ``*.py`` under ``root``.

    The tools/cc→espalier namespace-firewall predicate, extracted so BOTH the
    contract test below and its negative-proof in ``test_finding_ledger.py``
    (``test_tools_cc_import_of_ledger_is_caught_by_the_namespace_firewall``)
    invoke the REAL scan instead of an inline copy — weakening this predicate
    now reds both, not just the contract.
    """
    violations: list[str] = []
    for py_file in root.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as e:
            violations.append(f"{py_file}: SyntaxError — {e}")
            continue
        try:
            rel = py_file.relative_to(root)
        except ValueError:
            rel = py_file
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "espalier" or alias.name.startswith("espalier."):
                        violations.append(f"{rel}:{node.lineno} — import espalier")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "espalier" or mod.startswith("espalier."):
                    violations.append(f"{rel}:{node.lineno} — from espalier import")
    return violations


# pins: claim:claude-core-rule-5-tools-cc-isolation
class TestToolsCcNoEspalierImports:
    def test_tools_cc_has_zero_espalier_imports(self):
        """tools/cc/**/*.py must never import from espalier/."""
        violations = _scan_for_espalier_imports(TOOLS_CC_DIR)
        assert not violations, (
            "tools/cc/ scripts must have zero espalier imports — they run standalone.\n"
            + "\n".join(violations)
        )

    # TP-174b T03: the reverse direction (espalier -/-> tools/cc) had no AST
    # test, so CLAUDE.md "Architecture Rules"'s "never from tools/cc/" invariant was mechanically
    # unenforced. TP-178 went further — it vendored the deploy SOURCE under
    # espalier/_vendor/cc/ and removed the 3 suppress()-guarded `import tools.cc`
    # fallbacks entirely, so espalier/ now imports `tools` ZERO times. The
    # sanctioned set is empty: any `import tools` in espalier/ is a violation.
    _SANCTIONED_TOOLS_IMPORTS: set[tuple[str, int]] = set()

    def test_espalier_does_not_import_tools_cc_except_sanctioned(self):
        """espalier/ must not import tools/cc at all (CLAUDE.md "Architecture Rules").

        TP-178 vendored the deploy source and removed every `import tools`
        fallback, so the sanctioned set is empty. assets/ and _vendor/cc/ are
        skipped — both are deployed/vendored verbatim copies governed by their
        own source (tools/cc), not the espalier runtime package."""
        espalier_dir = REPO_ROOT / "espalier"
        violations = []
        for py_file in espalier_dir.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(("espalier/assets/", "espalier/_vendor/")):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                mod = None
                if isinstance(node, ast.Import):
                    mod = next(
                        (a.name for a in node.names
                         if a.name == "tools" or a.name.startswith("tools.")),
                        None,
                    )
                elif isinstance(node, ast.ImportFrom):
                    m = node.module or ""
                    if m == "tools" or m.startswith("tools."):
                        mod = m
                if mod and (rel, node.lineno) not in self._SANCTIONED_TOOLS_IMPORTS:
                    violations.append(f"{rel}:{node.lineno} — import {mod}")
        assert not violations, (
            "espalier/ must not import tools/cc except the 3 sanctioned "
            "file-path fallbacks (CLAUDE.md 'Architecture Rules').\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 5. Path normalization — no bare str(Path(...)) in path comparisons
# ---------------------------------------------------------------------------

def _bare_str_path_call_sites(source: str, filename: str = "<src>") -> list[int]:
    """Line numbers of ``str(...)`` calls whose argument references ``Path`` —
    a proxy for a missing ``.replace('\\\\', '/')`` Windows-path normalization
    (SHARP_EDGES "Path Normalization on Windows")."""
    tree = ast.parse(source, filename=filename)
    sites: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "str"):
            continue
        if not node.args:
            continue
        if "Path" in ast.unparse(node.args[0]):
            sites.append(node.lineno)
    return sites


class TestPathNormalization:
    def test_managed_paths_use_forward_slashes(self):
        """Path comparisons in espalier/ must use .replace('\\\\', '/') for Windows compat."""
        managed_paths = REPO_ROOT / "espalier" / "managed_paths.py"
        if not managed_paths.exists():
            return  # file not present, nothing to check
        violations = _bare_str_path_call_sites(
            managed_paths.read_text(encoding="utf-8"), str(managed_paths),
        )
        # Soft/advisory: the live file uses lowercase ``path`` vars so this
        # finds nothing today; kept as a non-firing guard (do NOT tighten to
        # ==0 — a legitimate display-only str(Path(...)) would then false-fire).
        assert len(violations) < 20, (
            "Many bare str(Path(...)) calls found in managed_paths.py — "
            "review for Windows path compat.\n"
            + "\n".join(f"managed_paths.py:{n}" for n in violations)
        )

    def test_bare_str_path_detector_fires(self):
        """TP-174b T04 earn-the-red: a literal ``str(Path(...))`` must be
        flagged. The live managed_paths.py uses lowercase ``path`` vars so the
        detector finds nothing there — without this unit test the detector
        could rot to matching nothing and the contract above would stay
        vacuously green."""
        src = 'from pathlib import Path\nx = str(Path("a") / "b")\n'
        assert _bare_str_path_call_sites(src) == [2]
        # lowercase ``path`` var via .as_posix() is NOT a ``Path``-literal hit
        assert _bare_str_path_call_sites("y = str(path.as_posix())\n") == []


# ---------------------------------------------------------------------------
# 6. ESPALIER_MEMORY.md line limit
# ---------------------------------------------------------------------------

# pins: claim:claude-core-rule-4-memory-state
class TestMemoryMdLineLimit:
    def test_memory_md_within_cap(self):
        """ESPALIER_MEMORY.md must stay within the line cap (loaded every session).

        Cap history: 60 (original) → 75 (TP-RELEASE-20 added the 14-line OSS
        header) → 80 (raised post-Sprint-6 review when /handoff hit the
        gate with zero headroom) → 120 (TP-183 handoff: the Harness Decisions
        + Patterns Learned reference tables had grown to ~57 lines, leaving
        room for only ~2 session rows, so the autoprune was archiving recent
        material; raised to give the session log real breathing room until
        the permanent tables are spun out to a reference doc). Session log
        pruning policy keeps the variable part bounded.
        """
        lines = MEMORY_PATH.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 120, (
            f"ESPALIER_MEMORY.md is {len(lines)} lines — must stay at 120 or fewer. "
            "Prune the session log. See SHARP_EDGES.md for the policy."
        )


# ---------------------------------------------------------------------------
# 7. plan_guard EXEMPT_PREFIXES documented
# ---------------------------------------------------------------------------

class TestPlanGuardExemptsPrescribedWrites:
    """§C23 class fix: the harness must not deny the workflow it prescribes.

    The failure this closes is not "two prefixes were missing" — it is that the
    exempt list was a HAND-KEPT set with no relationship to the thing it had to
    cover. `memory/` and `docs/` were absent while the deployed reflect skill,
    `/handoff` and `stop_gate` Gate 2 all instructed writes there, so the harness
    PreToolUse-denied its own instructions (DEF-440, DEF-495).

    This DERIVES the population instead: every path the `.claude/` command and
    skill bodies instruct a write to must be covered by an exempt prefix. A new
    command that tells Claude to write somewhere new now reds here instead of
    silently producing a denial at the moment it runs.
    """

    _VERB = re.compile(r"\b(writ|creat|draft|append|updat|edit|promot)\w*\b", re.I)
    _PATH = re.compile(r"`([A-Za-z_.][\w./-]*/[\w./-]+)`")

    def _prescribed_write_paths(self) -> dict[str, set[str]]:
        """Repo-relative paths the harness's own bodies instruct a write to.

        Restricted to matches whose leading segment is a real directory in the
        repo, which drops code tokens (`Path.write_text`, `json.dump`) that the
        backtick pattern would otherwise pick up.
        """
        bodies = sorted(REPO_ROOT.glob(".claude/commands/*.md"))
        bodies += sorted(REPO_ROOT.glob(".claude/skills/*/SKILL.md"))
        found: dict[str, set[str]] = {}
        for body in bodies:
            for line in body.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not self._VERB.search(line):
                    continue
                for match in self._PATH.findall(line):
                    top = match.split("/")[0]
                    if not (REPO_ROOT / top).is_dir():
                        continue
                    found.setdefault(match, set()).add(body.name)
        return found

    def test_derivation_has_a_population(self):
        """Floor: a regex that matches nothing would make the gate below vacuous."""
        paths = self._prescribed_write_paths()
        assert len(paths) >= 8, (
            f"prescribed-write derivation found only {len(paths)} paths — the "
            f"pattern has stopped matching the .claude/ bodies, so the coverage "
            f"assertion below is passing vacuously. Found: {sorted(paths)}"
        )

    def test_every_prescribed_write_path_is_plan_exempt(self):
        exempt = TestPlanGuardExemptPrefixes()._extract_exempt_prefixes()
        assert exempt, "could not parse EXEMPT_PREFIXES from plan_guard.py"
        uncovered = {
            path: sorted(sources)
            for path, sources in self._prescribed_write_paths().items()
            if not any(path.startswith(prefix) for prefix in exempt)
        }
        assert not uncovered, (
            "plan_guard would DENY writes the harness's own commands/skills "
            "instruct — add the prefix to _hook_utils.EXEMPT_UNIVERSAL_PREFIXES "
            "(and plan_guard's mirrored literal), or stop instructing the write:\n"
            + "\n".join(f"  {p}  <- {s}" for p, s in sorted(uncovered.items()))
        )

    def test_gate_fires_when_a_prescribed_prefix_is_dropped(self):
        """Earn-the-red: the coverage assertion must be able to fail."""
        shrunk = {p for p in TestPlanGuardExemptPrefixes()._extract_exempt_prefixes()
                  if p != "memory/"}
        uncovered = [
            path for path in self._prescribed_write_paths()
            if not any(path.startswith(prefix) for prefix in shrunk)
        ]
        assert uncovered, (
            "dropping `memory/` from the exempt set left every prescribed-write "
            "path still covered — the derivation is not actually reaching the "
            "memory/ write instructions it is supposed to bind"
        )

    # -- second arm: a derivation that needs no prose recognition -----------
    #
    # The prose arm above missed a live denial (an adopter following the seeded
    # docs/PACK_AUTHORING.md was PreToolUse-denied writing their first pack to
    # `task-packs/`). The obvious repair — widen the verb list and the corpus —
    # was MEASURED before being adopted, and does not work. Recorded so it is
    # not re-proposed:
    #
    #   * adding "move" to _VERB is INERT: 12 paths before, 12 after, 0 newly
    #     uncovered. The binding constraint is _PATH, not the verb — it wants a
    #     bare backticked path, and the live instruction is embedded in a longer
    #     span (`mkdir -p task-packs/Done && mv ...`), as is the seeded doc's
    #     `espalier scope-check "task-packs/TP-N-your-pack.md"` (quoted, not
    #     backticked). Loosening _PATH to reach inside those spans is where the
    #     false positives start.
    #   * adding the seeded docs to the population yields UNCOVERED paths that
    #     are all correct prose: symbol references the backtick pattern cannot
    #     distinguish from paths (`espalier/surface_contract.is_self_host_repo`,
    #     `espalier/_safe_walk.safe_rglob`) and self-host-only paths
    #     (`bench/RESULTS.md`, `espalier/_vendor/cc/`). Measured 18 against this
    #     repo's own doc bodies and 7 against the ADOPTER-deployed bodies (the
    #     stubs `_SEED_ASSET_SOURCES` substitutes for SHARP_EDGES/CONVENTIONS) —
    #     the deployed figure is the honest one, and both are false positives.
    #     A gate that reds on correct prose is a gate that gets switched off
    #     (§C19).
    #
    # A shape-based sweep over the OTHER carriers of this prefix list was
    # measured too, and also rejected: "any line with >=3 backticked exempt
    # prefixes must carry all of them" yields 60 candidates, of which ~59 are
    # blueprints, task packs, session archives, `dist/` build artifacts and
    # declared record surfaces (Core Rule 13) — while still missing two real
    # carriers that use fewer than three backticks. The live carriers are a
    # small editorial set, not a derivable one.
    #
    # So the prose arm keeps its narrow, precise scope, and this arm covers the
    # gap by sidestepping recognition entirely: if `init` SEEDS A DOC into a
    # top-level directory, the harness put that directory on the adopter's tree
    # and routes them into it, so writes there must not require a plan.
    #
    # That predicate is derived, exact, and historically self-confirming: the
    # seeded top-level set is {docs, memory, task-packs}, and `docs/` +
    # `memory/` are precisely the two prefixes the PREVIOUS §C23 fix added
    # (DEF-440, DEF-495). This arm reproduces that fix mechanically and
    # extends it to the member left behind — with no prose matching at all.

    @staticmethod
    def _seeded_parent_dirs() -> set[str]:
        """Directories `init` seeds a doc INTO, as `dir/`-suffixed prefixes.

        Keyed on the seed doc's PARENT, not its top-level segment. The precise
        question this arm asks is "can an adopter author a sibling next to the
        doc the harness just put here" — `task-packs/CLAUDE.md` tells them the
        pack-naming convention, so `task-packs/TP-1-mine.md` must be writable.
        Keying on the top-level segment would ask the coarser "is the whole
        top-level tree exempt", which gives a WRONG answer whenever coverage is
        granted by a nested prefix: a seed doc at `tools/cc/x.md` is genuinely
        exempt via the `tools/cc/` prefix, while `tools/` as a whole is not.
        """
        from espalier.managed_inventory import get_seed_docs

        parents = set()
        for rel in get_seed_docs():
            posix = str(rel).replace("\\", "/")
            if "/" in posix:
                parents.add(posix.rsplit("/", 1)[0] + "/")
        return parents

    def test_seeded_derivation_has_a_population(self):
        """Floor: an empty seed set would make the arm below vacuous."""
        parents = self._seeded_parent_dirs()
        assert len(parents) >= 3, (
            f"only {len(parents)} seeded dir(s) derived from get_seed_docs() — "
            f"the seed inventory has moved and the coverage assertion below is "
            f"passing vacuously. Found: {sorted(parents)}"
        )

    def test_every_seeded_directory_is_plan_exempt(self):
        exempt = TestPlanGuardExemptPrefixes()._extract_exempt_prefixes()
        assert exempt, "could not parse EXEMPT_PREFIXES from plan_guard.py"
        uncovered = sorted(
            seeded for seeded in self._seeded_parent_dirs()
            if not any(seeded.startswith(prefix) for prefix in exempt)
        )
        assert not uncovered, (
            "`init` seeds a doc into these directories but plan_guard would DENY "
            "an adopter writing there — the harness routes them in, then blocks "
            "them. Add the prefix to _hook_utils.EXEMPT_UNIVERSAL_PREFIXES (and "
            "plan_guard's mirrored literal):\n"
            + "\n".join(f"  {seeded}" for seeded in uncovered)
        )

    def test_seeded_arm_fires_when_a_seeded_prefix_is_dropped(self):
        """Earn-the-red for the arm itself: it must be able to fail."""
        shrunk = {p for p in TestPlanGuardExemptPrefixes()._extract_exempt_prefixes()
                  if p != "docs/"}
        uncovered = [
            seeded for seeded in self._seeded_parent_dirs()
            if not any(seeded.startswith(prefix) for prefix in shrunk)
        ]
        assert uncovered, (
            "dropping `docs/` from the exempt set left every seeded directory "
            "still covered — this arm is not actually binding the seed inventory"
        )

    def test_derivation_keys_on_the_parent_not_the_top_segment(self):
        """Pin the parent-keying itself, by asserting the derivation's SHAPE.

        The obvious spelling of this guard is a tautology and was shipped as one
        before review caught it: asserting `any("tools/cc/".startswith(p) for p
        in exempt)` is unconditionally true the moment `"tools/cc/" in exempt`,
        so it could not fail for the reason its name gives. Assert instead on
        the one thing that actually changes — top-segment keying yields bare
        {docs, memory, task-packs} with no nesting and no trailing slash, so a
        nested member is present under parent-keying and absent under the
        regression.

        Why the distinction is load-bearing: a seed doc at `tools/cc/x.md` IS
        plan-exempt via the real `tools/cc/` prefix, but its top segment
        `tools/` is NOT exempt — so top-segment keying would report a false
        uncoverage and red on correct code.
        """
        parents = self._seeded_parent_dirs()
        nested = sorted(p for p in parents if p.count("/") > 1)
        assert nested, (
            "no nested seed dir remains, so this arm can no longer distinguish "
            "parent-keying from top-segment keying — re-point it at a live "
            f"nested seed, or retire it. Derived: {sorted(parents)}"
        )
        assert all(p.endswith("/") for p in parents), (
            "the derivation has regressed to top-segment keying (bare segments, "
            f"no trailing slash): {sorted(parents)}"
        )

    def test_every_exempt_prefix_still_has_a_seed_justifying_it(self):
        """The §C23 prefixes must keep the justification that put them there.

        Closes the one path that routes around every other pin in this class.
        `memory/`, `docs/` and `task-packs/` are exempt ONLY because `init`
        seeds a doc into them and the harness's own instructions route an
        adopter there. If a seed row is later dropped, the coverage arm above
        goes quiet — it only asks "is every SEEDED dir exempt", and a dir that
        is no longer seeded trivially satisfies it. The prefix then sits exempt
        for no derived reason, and the next tidy-up removes it against a fully
        green suite, restoring the exact denial this class exists to prevent.

        This asserts the CONCLUSION rather than re-deriving the population, so
        it is deliberately a short literal list: the point is that dropping a
        seed row must force someone to re-state the justification, not silently
        inherit one.
        """
        seeded = self._seeded_parent_dirs()
        for prefix in ("memory/", "docs/", "task-packs/"):
            assert any(s.startswith(prefix) for s in seeded), (
                f"`{prefix}` is in plan_guard.EXEMPT_PREFIXES on §C23 grounds "
                f"(the harness seeds a doc there and routes the adopter in), but "
                f"`init` no longer seeds anything under it. Either restore the "
                f"seed row, or write down the new justification for keeping the "
                f"exemption and update this list. Derived: {sorted(seeded)}"
            )


class TestPlanGuardExemptPrefixes:
    def _extract_exempt_prefixes(self) -> set[str]:
        source = PLAN_GUARD_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "EXEMPT_PREFIXES":
                        if isinstance(node.value, ast.Tuple):
                            return {
                                elt.value for elt in node.value.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            }
        return set()

    def _documented_prefixes(self) -> set[str]:
        """DERIVE the documented set from SHARP_EDGES.md, don't restate it.

        The previous version hard-coded the six prefixes and read `sharp_edges`
        without ever using it — a born-weak gate that could only fail if someone
        edited the hook, never if the doc drifted, and which restated the very
        population it was supposed to bind (§C1). Parsing the doc means adding a
        prefix to the hook without documenting it still reds, AND deleting one
        from the doc reds too.
        """
        sharp_edges = (REPO_ROOT / "docs" / "SHARP_EDGES.md").read_text(encoding="utf-8")
        universal = re.search(r"universal\s+—\s+(.+?);", sharp_edges)
        assert universal, (
            "docs/SHARP_EDGES.md no longer carries a `universal — ...;` prefix list "
            "in the Plan Guard Exemption section — the derivation anchor is gone"
        )
        documented = set(re.findall(r"`([^`]+/)`", universal.group(1)))
        # The self-host carve-out is documented in the sentence's clause (2).
        selfhost = re.search(r"self-host carve-out\s+—\s+`([^`]+/)`", sharp_edges)
        if selfhost:
            documented.add(selfhost.group(1))
        assert len(documented) >= 5, f"derivation produced too few prefixes: {documented}"
        return documented

    def test_plan_guard_exempt_prefixes_documented(self):
        """EXEMPT_PREFIXES in plan_guard.py must match what SHARP_EDGES.md documents."""
        documented_prefixes = self._documented_prefixes()
        actual_prefixes = self._extract_exempt_prefixes()
        assert actual_prefixes, "Could not parse EXEMPT_PREFIXES from plan_guard.py"

        undocumented = actual_prefixes - documented_prefixes
        assert not undocumented, (
            f"plan_guard.py has EXEMPT_PREFIXES not documented in SHARP_EDGES.md: "
            f"{undocumented}\nUpdate SHARP_EDGES.md to document the new exemptions."
        )

    def test_documented_prefixes_are_all_real(self):
        """The REVERSE direction: the doc must not promise an exemption the hook
        does not grant.

        The forward check above is one-directional, which leaves the worse of
        the two failures uncovered — proven by mutation: removing a prefix from
        BOTH code sites while leaving it in SHARP_EDGES.md keeps the forward
        assertion GREEN. The shipped doc then tells an adopter a path is exempt
        while plan_guard denies it, and `/audit-accuracy` reads clean. A doc
        that over-promises misdirects; a doc that under-promises merely
        under-sells.

        `espalier/` is carved out because it is the CONDITIONAL member — exempt
        only on the self-host repo, documented in its own clause and folded into
        `_documented_prefixes` from a separate regex, so it is legitimately
        present in the doc and absent from the universal tuple.
        """
        documented_prefixes = self._documented_prefixes()
        actual_prefixes = self._extract_exempt_prefixes()
        assert actual_prefixes, "Could not parse EXEMPT_PREFIXES from plan_guard.py"

        overpromised = documented_prefixes - actual_prefixes - {"espalier/"}
        assert not overpromised, (
            f"docs/SHARP_EDGES.md documents plan-exempt prefixes that plan_guard "
            f"does NOT grant: {overpromised}\nAn adopter reading this would expect "
            f"to write there without a plan and be DENIED. Either restore the "
            f"prefix in _hook_utils.EXEMPT_UNIVERSAL_PREFIXES (and plan_guard's "
            f"mirrored literal), or remove the claim from the doc."
        )


# ---------------------------------------------------------------------------
# 8. README hook count matches reality
# ---------------------------------------------------------------------------

class TestReadmeHookCount:
    def test_readme_hook_count_matches_reality(self):
        """README must not claim a different number of hooks than actually exist."""
        hook_files = [
            f for f in HOOKS_DIR.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ]
        actual_count = len(hook_files)

        readme = README_PATH.read_text(encoding="utf-8")

        # Find all digit-word or numeric hook count claims
        numeric_claims = re.findall(
            r"(\d+)\s+hook(?:s|\s+script)", readme, re.IGNORECASE
        )
        word_map = {
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        word_claims = re.findall(
            r"(six|seven|eight|nine|ten)\s+hook", readme, re.IGNORECASE
        )

        wrong_claims = []
        for claim in numeric_claims:
            if int(claim) != actual_count:
                wrong_claims.append(f'README claims "{claim} hooks" but {actual_count} exist')
        for claim in word_claims:
            n = word_map.get(claim.lower(), -1)
            if n != actual_count:
                wrong_claims.append(
                    f'README claims "{claim} hooks" but {actual_count} exist'
                )

        assert not wrong_claims, (
            "README hook count is stale. Update README to match the "
            f"{actual_count} hook files in tools/cc/hooks/.\n"
            + "\n".join(wrong_claims)
        )


# ---------------------------------------------------------------------------
# N. Subprocess text decoding pins UTF-8, never the OS locale (TP-189 XPLAT-1)
# ---------------------------------------------------------------------------
#
# A text-mode subprocess call (``text=True`` / ``universal_newlines=True`` /
# a text-mode ``check_output``) that omits ``encoding=`` decodes the child
# tool's stdout with the OS *locale* encoding, NOT UTF-8 (Python defaults to
# ``locale.getpreferredencoding()``). On a UTF-8 host this is invisible; on a
# stock Windows cp1252 console git/rg/build's UTF-8 output mis-decodes — silent
# mojibake on accented commit authors or CJK paths, or a hard
# ``UnicodeDecodeError`` on a byte cp1252 leaves undefined. Every
# ``read_text()`` in these modules already pins ``encoding="utf-8"``; only the
# subprocess decodes had been left to the locale. This contract pins that they
# don't, so the bug class (XPLAT-1) can't regress as new call sites are added.

_SUBPROCESS_TEXT_FUNCS = {"run", "check_output", "Popen", "call", "check_call"}

# The scan surface is DERIVED from `git ls-files` (the repo's tracked-code
# source of truth), NOT a hardcoded root list — so a NEW dir that ships to or
# runs for an adopter is gated automatically and the bench/ + top-level tools/
# scope gap (TP-189 XPLAT-1 adversarial: the first fix scoped only to
# espalier+tools/cc+scripts and missed two fuse-overlaid / sdist-shipped dirs)
# cannot silently reopen. A ship-manifest derivation was rejected: it would drop
# scripts/ (maintainer/CI code that isn't shipped but runs on the Windows CI
# legs) and miss not-yet-created dirs — tracked-code is the strict superset.
# Excluded: test code (it decodes fixture data via the locale by design and is
# not shipped), the espalier/_vendor/ byte-mirror (parity-pinned to tools/cc/),
# and espalier/assets/ static templates.
_SUBPROC_SKIP_PREFIXES = ("tests/", "espalier/assets/", "espalier/_vendor/")

# A file that always exists. The enumeration MUST contain it; if it doesn't,
# `git ls-files` failed and the contract would pass VACUOUSLY — so the helper
# fails closed (skips loudly) rather than reporting a false green.
_SUBPROC_ENUM_SENTINEL = "espalier/cli.py"

# Escape hatch for the rare call that genuinely must follow the host locale:
# an inline ``# encoding-locale-ok: <reason>`` pragma anywhere in the call's
# source span exempts it. Today there are zero — every site pins UTF-8.
_ENCODING_OK_PRAGMA = "# encoding-locale-ok:"


def _is_test_file(rel: str) -> bool:
    """A test/fixture file (anywhere in the tree) — excluded from the gate."""
    base = rel.rsplit("/", 1)[-1]
    return base == "conftest.py" or base.startswith("test_") or base.endswith("_test.py")


def _iter_production_py():
    """(rel, Path) for every tracked production ``.py`` the encoding contract
    gates — derived from ``git ls-files`` so the surface tracks the repo's real
    code with no hardcoded root list to drift (TP-189 XPLAT-1 recurrence guard).

    Skips test code (anywhere), the ``_vendor`` mirror, and ``assets/``. Fails
    CLOSED: if ``git ls-files`` yields nothing usable the contract SKIPS rather
    than passing vacuously.
    """
    import subprocess as _sp

    try:
        tracked = _sp.run(
            ["git", "ls-files", "*.py"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=True,
        ).stdout.splitlines()
    except (OSError, _sp.SubprocessError):
        tracked = []
    files = [
        (rel, REPO_ROOT / rel)
        for rel in (r.strip() for r in tracked)
        if rel
        and not rel.startswith(_SUBPROC_SKIP_PREFIXES)
        and not _is_test_file(rel)
    ]
    if not any(rel == _SUBPROC_ENUM_SENTINEL for rel, _ in files):
        import pytest
        pytest.skip(
            "could not enumerate tracked production .py via `git ls-files` "
            f"(sentinel {_SUBPROC_ENUM_SENTINEL!r} absent) — the subprocess-"
            "encoding contract would pass vacuously; skipping over false-green"
        )
    return files


def _is_true_const(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _encoding_pinned_utf8(kw: dict) -> bool:
    """True iff ``encoding=`` is present AND set to a UTF-8 string literal.

    Key presence alone is not enough (SOUND-3): ``encoding=None`` or
    ``encoding="latin-1"`` is still the locale/non-UTF-8 bug. A non-constant
    ``encoding=<expr>`` can't be judged statically, so it's given the benefit of
    the doubt (rare; the reviewer reads it). A wrong literal is an offender.
    """
    if "encoding" not in kw:
        return False
    v = kw["encoding"]
    if isinstance(v, ast.Constant):
        return isinstance(v.value, str) and v.value.lower().replace("-", "") == "utf8"
    return True


#: A text-mode capture is decode-guarded when it carries ``errors=`` (any
#: value), or sits in a try BODY whose handler catches the decode error, or
#: carries this pragma with a reason. Two arms, deliberately (ledger DEF-821,
#: reconciling the text-mode-subprocess sharp edge with the row that found
#: seventeen unguarded engine captures): ``errors="replace"`` where the text is
#: names, lines or sentences (a filename git prints in a non-UTF-8 encoding is
#: a legitimate repository state, and a replacement character where a path was
#: is still a sentence); a STRICT decode only under a handler that names
#: ValueError or UnicodeDecodeError, so a corrupted structured answer (a SHA, a
#: version banner) becomes the site's own failure verdict rather than a
#: traceback -- never ``errors="replace"`` on one, which would mask the
#: corruption the strict decode exists to surface.
_DECODE_OK_PRAGMA = "# decode-errors-ok:"
_DECODE_CATCHING = {"UnicodeDecodeError", "ValueError", "Exception", "BaseException"}
#: The ``errors=`` values that cannot raise. ``errors="strict"`` and
#: ``errors=None`` are the default spelled out, and a non-literal value cannot
#: be judged: none of those is a guard (the same lesson ``_encoding_pinned_utf8``
#: learned -- key presence is not a value).
_DECODE_TOLERANT_ERRORS = {"replace", "ignore", "backslashreplace", "surrogateescape"}
#: Constant argv shapes whose answer is structured -- a version banner, a SHA,
#: a repository root used as a path, a stash object id. A tolerant ``errors=``
#: on one masks the corruption the strict decode exists to surface, so it is an
#: offender in its own right; the rule is otherwise a per-site judgment, and
#: this roster holds the shapes the sweep itself drifted on before review.
_STRUCTURED_ARGV_TOKENS = ("--version", "rev-parse HEAD", "--show-toplevel", "stash create")
_TRY_TYPES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)


def _errors_tolerant(kw: dict) -> bool:
    node = kw.get("errors")
    return isinstance(node, ast.Constant) and node.value in _DECODE_TOLERANT_ERRORS


def _argv_is_structured_answer(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
        return False
    joined = " ".join(
        e.value for e in call.args[0].elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
    )
    return any(tok in joined for tok in _STRUCTURED_ARGV_TOKENS)


def _walk_same_frame(node: ast.AST):
    """``ast.walk`` that does not descend into a nested ``def`` or ``lambda``:
    a call inside one runs later, outside the try that lexically holds it."""
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # its body runs later -- whether it is the root or a child
        stack.extend(ast.iter_child_nodes(cur))


def _try_catches_decode_error(try_node: ast.AST) -> bool:
    """A handler naming UnicodeDecodeError, ValueError, Exception or
    BaseException, or a bare ``except:``. UnicodeDecodeError is a ValueError,
    not an OSError, so an ``(OSError, SubprocessError)`` tuple does NOT count.
    Both ``except ValueError:`` (a Name) and ``except (OSError, ValueError):``
    (a Tuple of Names) are read."""
    for handler in try_node.handlers:
        if handler.type is None:
            return True
        names = {n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)}
        if names & _DECODE_CATCHING:
            return True
    return False


def _in_a_try_body_that_catches_decode_error(call: ast.AST, scope: ast.AST) -> bool:
    """Only a call in a try's BODY is protected by its handlers -- one in its
    ``else:`` or ``finally:`` block is not (Python routes only body-raised
    exceptions through the except clauses), so containment is checked against
    the body, not the whole Try node."""
    return any(
        any(call is d for stmt in t.body for d in _walk_same_frame(stmt))
        and _try_catches_decode_error(t)
        for t in ast.walk(scope)
        if isinstance(t, _TRY_TYPES)
    )


def _text_subprocess_calls_not_decode_guarded(rel: str, source: str) -> list[tuple[int, str, str]]:
    """(lineno, func, why) for each ``subprocess.<f>`` call that decodes to text
    (``text=True``, ``universal_newlines=True`` or an ``encoding=``) and is
    neither tolerant-``errors=``-bearing, nor in a try body whose handler
    catches the decode error, nor pragma-declared -- or that carries a tolerant
    ``errors=`` on a structured-answer argv (``_STRUCTURED_ARGV_TOKENS``).
    Declared limit: a ``Popen`` decodes at ``communicate()``, later than the
    constructor this reads; the surface holds one, binary."""
    tree = ast.parse(source, filename=rel)
    src_lines = source.splitlines()
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (
            isinstance(f, ast.Attribute)
            and f.attr in _SUBPROCESS_TEXT_FUNCS
            and isinstance(f.value, ast.Name)
            and f.value.id == "subprocess"
        ):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        text_mode = (
            _is_true_const(kw.get("text"))
            or _is_true_const(kw.get("universal_newlines"))
            or "encoding" in kw
        )
        if not text_mode:
            continue
        if _errors_tolerant(kw):
            if _argv_is_structured_answer(node):
                out.append((node.lineno, f.attr, "a tolerant errors= on a structured answer masks corruption; keep the strict decode under a handler naming ValueError"))
            continue
        if _in_a_try_body_that_catches_decode_error(node, tree):
            continue
        span = src_lines[node.lineno - 1 : (node.end_lineno or node.lineno)]
        if any(_DECODE_OK_PRAGMA in line for line in span):
            continue
        out.append((node.lineno, f.attr, "no tolerant errors=, and no handler naming ValueError or UnicodeDecodeError around the call"))
    return out


def _thin_decode_pragmas(source: str) -> list[tuple[int, str]]:
    """(lineno, reason) for each decode pragma whose reason is under 25 chars."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(source.splitlines(), 1):
        if _DECODE_OK_PRAGMA in line:
            reason = line.split(_DECODE_OK_PRAGMA, 1)[1].strip()
            if len(reason) < 25:
                out.append((i, reason))
    return out


def _text_subprocess_calls_missing_encoding(rel: str, source: str) -> list[tuple[int, str]]:
    """(lineno, func) for each ``subprocess.<f>`` call that decodes to text
    but does not pin ``encoding="utf-8"`` and carries no opt-out pragma."""
    tree = ast.parse(source, filename=rel)
    src_lines = source.splitlines()
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (
            isinstance(f, ast.Attribute)
            and f.attr in _SUBPROCESS_TEXT_FUNCS
            and isinstance(f.value, ast.Name)
            and f.value.id == "subprocess"
        ):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        text_mode = _is_true_const(kw.get("text")) or _is_true_const(
            kw.get("universal_newlines")
        )
        if not text_mode or _encoding_pinned_utf8(kw):
            continue
        span = src_lines[node.lineno - 1 : (node.end_lineno or node.lineno)]
        if any(_ENCODING_OK_PRAGMA in line for line in span):
            continue
        out.append((node.lineno, f.attr))
    return out


class TestSubprocessEncodingPinned:
    """TP-189 XPLAT-1: text-mode subprocess decodes pin ``encoding="utf-8"``,
    never the OS locale."""

    def test_scan_surface_covers_shipped_dirs_and_excludes_test_and_mirror(self):
        # The surface is git-derived (no hardcoded root list), so a NEW shipped/
        # run dir is gated automatically. Pin the breadth + the exclusions so a
        # regression to a narrow hardcoded subset — the original bench/+tools/
        # gap the adversarial pass caught — reds HERE, not silently in prod.
        files = _iter_production_py()
        dirs = {rel.split("/", 1)[0] for rel, _ in files}
        for d in ("espalier", "tools", "scripts", "bench"):
            assert d in dirs, (
                f"{d}/ dropped from the subprocess-encoding scan surface — the "
                "bench/ + top-level tools/ scope gap (XPLAT-1) must stay closed"
            )
        leaked = [
            rel for rel, _ in files
            if rel.startswith(_SUBPROC_SKIP_PREFIXES) or _is_test_file(rel)
        ]
        assert not leaked, f"excluded paths leaked into the scan surface: {leaked[:5]}"

    def test_no_text_mode_subprocess_omits_encoding(self):
        offenders: list[str] = []
        for rel, p in _iter_production_py():
            for lineno, func in _text_subprocess_calls_missing_encoding(
                rel, p.read_text(encoding="utf-8")
            ):
                offenders.append(f"{rel}:{lineno} subprocess.{func}")
        assert not offenders, (
            f"{len(offenders)} text-mode subprocess call(s) do not pin "
            'encoding="utf-8" (absent, None, or a non-UTF-8 literal) — they '
            "decode the child tool's output with the OS locale, not UTF-8 "
            "(mojibake / UnicodeDecodeError on a non-UTF-8 Windows console). "
            'Add encoding="utf-8" (TP-189 XPLAT-1):\n  ' + "\n  ".join(offenders)
        )

    def test_no_aliased_subprocess_import_evades_the_scan(self):
        # The AST scan keys on ``subprocess.<f>(...)``. ``from subprocess
        # import run`` or ``import subprocess as sp`` would make those calls
        # invisible to it — a silent bypass of the encoding contract. Forbid
        # the aliasing so the canonical form the scan sees is the only form.
        alias_re = re.compile(
            r"^\s*(?:from subprocess import|import subprocess as)\b", re.M
        )
        offenders = [
            rel for rel, p in _iter_production_py()
            if alias_re.search(p.read_text(encoding="utf-8"))
        ]
        assert not offenders, (
            "aliased subprocess import(s) would evade the encoding contract; "
            "use `import subprocess` + `subprocess.<f>`:\n  "
            + "\n  ".join(offenders)
        )

    def test_encoding_optout_pragmas_carry_a_reason(self):
        # An opt-out without a documented reason is a silent escape hatch —
        # mirror the allowlist-hygiene discipline used elsewhere in the suite.
        bad: list[str] = []
        for rel, p in _iter_production_py():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if _ENCODING_OK_PRAGMA in line:
                    if not line.split(_ENCODING_OK_PRAGMA, 1)[1].strip():
                        bad.append(f"{rel}:{i}")
        assert not bad, f"encoding-locale-ok pragma(s) missing a reason: {bad}"

    def test_write_required_surface_read_is_decode_guarded(self):
        # EA-2: the adopter-init drift read must never regrow a bare-strict
        # read_text — a non-UTF-8 pre-existing cc/ doc must not abort
        # `espalier init`. Every read_text(...) inside write_required_surface
        # must carry errors= OR sit under a try that catches UnicodeDecodeError.
        # UnicodeDecodeError is a ValueError (not an OSError), so an OSError-only
        # guard does NOT satisfy this — the handler must name UnicodeDecodeError,
        # ValueError, Exception/BaseException, or be a bare `except:`.
        src = (REPO_ROOT / "espalier" / "render_surface.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "write_required_surface"
        )

        def _guarded(call_node):
            # The module-level helper (shared with the subprocess decode-guard
            # pin) reads the try's BODY, not the whole node.
            return _in_a_try_body_that_catches_decode_error(call_node, fn)

        offenders = []
        for call in ast.walk(fn):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "read_text"
                and not any(k.arg == "errors" for k in call.keywords)
                and not _guarded(call)
            ):
                offenders.append(ast.get_source_segment(src, call) or "read_text(...)")
        assert not offenders, (
            "write_required_surface has an unguarded bare-strict read_text — a "
            "non-UTF-8 pre-existing cc/ doc would abort `espalier init` (EA-2):\n  "
            + "\n  ".join(offenders)
        )


class TestSubprocessDecodeGuarded:
    """Ledger DEF-821: every text-mode subprocess capture on the derived
    production surface is decode-guarded -- a tolerant ``errors=`` where the
    text is names, lines or sentences, or a strict decode under a handler that
    catches the decode error, or a reasoned ``# decode-errors-ok:`` pragma on
    the call's own line. Without this, ``subprocess.run(..., text=True,
    encoding="utf-8")`` raises ``UnicodeDecodeError`` -- a ValueError -- on
    output that is not UTF-8, and an ``(OSError, SubprocessError)`` tuple lets
    it past: an adopter whose repository holds a filename git prints in a
    non-UTF-8 encoding (the ``core.quotePath=false`` ``ls-files`` in
    ``repo_mode``) got a traceback from ``doctor``, ``audit`` and ``init`` on a
    tree that was otherwise fine. Measured at HEAD before the sweep: 78
    offenders. A tolerant ``errors=`` on a structured-answer argv is an
    offender too: the review of the sweep found two version banners on the
    replace arm and two repository roots consumed as paths, so the roster
    pins the shapes the prose rule drifted on at author time. Same surface
    and pragma discipline as ``TestSubprocessEncodingPinned`` above; the
    handler helper is the one ``test_write_required_surface_read_is_decode_guarded``
    lifts."""

    def test_no_text_mode_subprocess_lets_a_decode_error_escape(self):
        offenders: list[str] = []
        for rel, p in _iter_production_py():
            for lineno, func, why in _text_subprocess_calls_not_decode_guarded(
                rel, p.read_text(encoding="utf-8")
            ):
                offenders.append(f"{rel}:{lineno} subprocess.{func} -- {why}")
        assert not offenders, (
            f"{len(offenders)} text-mode subprocess call(s) are not decode-guarded. "
            "Where the output is names, lines or sentences decode with "
            'errors="replace" (ValueError beside an OSError tuple is the belt); '
            "where it is a structured answer (a SHA, a version banner, a root used "
            "as a path) keep the strict decode and add ValueError to the handler so "
            "corruption becomes the site's own failure verdict, marked "
            "`# strict decode: a structured answer (DEF-821)`; a call whose pipe is "
            "never decoded declares `# decode-errors-ok: <why>` on its own line:\n  "
            + "\n  ".join(offenders)
        )

    def test_decode_optout_pragmas_carry_a_reason(self):
        thin = [
            f"{rel}:{ln} ({reason!r})"
            for rel, p in _iter_production_py()
            for ln, reason in _thin_decode_pragmas(p.read_text(encoding="utf-8"))
        ]
        assert not thin, (
            "decode-errors-ok pragma(s) whose reason is a word or nothing -- an "
            f"exemption whose justification is a word outlives the argument for it: {thin}"
        )

    def test_the_reason_floor_reads_the_reason(self):
        """Earn the red on the floor itself (a mutation to ``< 0`` survived
        the live surface, which holds only long reasons)."""
        assert _thin_decode_pragmas("x = 1  # decode-errors-ok: because\n") == [(1, "because")]
        assert _thin_decode_pragmas("x = 1  # decode-errors-ok: no pipe is captured, nothing is decoded\n") == []

    def test_the_guard_reads_the_handler_and_the_try_body_not_the_try(self):
        """Earn the red on the pin's own arms, on synthetic modules: an
        OSError-only tuple is not a guard; a catching handler guards only the
        try BODY and only the same frame; a tolerant errors= guards anywhere
        except on a structured answer; errors='strict' and errors=None are the
        default spelled out; an encoding= without text=True is still a text
        decode."""
        def offenders(src: str) -> list[int]:
            return [ln for ln, _f, _w in _text_subprocess_calls_not_decode_guarded("synthetic.py", src)]

        oserror_only = (
            "import subprocess\n"
            "def f():\n"
            "    try:\n"
            "        return subprocess.run(['git'], capture_output=True, text=True, encoding='utf-8')\n"
            "    except (OSError, subprocess.SubprocessError):\n"
            "        return None\n"
        )
        value_error = oserror_only.replace("(OSError, subprocess.SubprocessError)", "(OSError, ValueError)")
        in_else = (
            "import subprocess\n"
            "def f():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        return None\n"
            "    else:\n"
            "        return subprocess.run(['git'], capture_output=True, text=True, encoding='utf-8')\n"
        )
        in_a_nested_def = (
            "import subprocess\n"
            "def f():\n"
            "    try:\n"
            "        def later():\n"
            "            return subprocess.run(['git'], capture_output=True, text=True, encoding='utf-8')\n"
            "    except ValueError:\n"
            "        return None\n"
            "    return later\n"
        )
        replaced = (
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['git', 'status'], capture_output=True, text=True, encoding='utf-8', errors='replace')\n"
        )
        strict_spelled_out = replaced.replace("errors='replace'", "errors='strict'")
        errors_none = replaced.replace("errors='replace'", "errors=None")
        replace_on_a_banner = replaced.replace("['git', 'status']", "[python, '--version']")
        replace_on_a_sha = replaced.replace("['git', 'status']", "['git', '-C', str(root), 'rev-parse', 'HEAD']")
        strict_banner_under_a_handler = (
            "import subprocess\n"
            "def f():\n"
            "    try:\n"
            "        return subprocess.run([python, '--version'], capture_output=True, text=True, encoding='utf-8')\n"
            "    except (OSError, ValueError):\n"
            "        return None\n"
        )
        encoding_only = (
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['git'], capture_output=True, encoding='utf-8')\n"
        )
        declared = (
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['pytest'], text=True, encoding='utf-8')  # decode-errors-ok: no pipe is captured, nothing is decoded here\n"
        )
        assert offenders(oserror_only) == [4]
        assert offenders(value_error) == []
        assert offenders(in_else) == [8]
        assert offenders(in_a_nested_def) == [5]
        assert offenders(replaced) == []
        assert offenders(strict_spelled_out) == [3]
        assert offenders(errors_none) == [3]
        assert offenders(replace_on_a_banner) == [3]
        assert offenders(replace_on_a_sha) == [3]
        assert offenders(strict_banner_under_a_handler) == []
        assert offenders(encoding_only) == [3]
        assert offenders(declared) == []


#: The text-read spellings the read pin gates (ledger DEF-829): ``Path.read_text``,
#: ``bytes.decode`` (the spelling behind ``read_text_nofollow`` and ``decode_bom``;
#: its ``errors`` slot is positional too) and a text-mode ``open`` that READS -- the
#: builtin, ``io.open``/``codecs.open`` (mode at position 1), ``<path>.open`` (mode
#: at position 0), and ``gzip``/``bz2``/``lzma`` ``.open`` only with a ``t`` in a
#: literal mode. The module-level ``.open``s that are not text files come from the
#: encoding scanner's canon roster (``NON_FILE_OPENERS``: descriptors, archives,
#: sockets) so one census cannot drift from the other; ``codecs`` leaves that set
#: here (it IS a text opener) and ``subprocess`` joins it. A handle opened to write
#: (``a+``, ``w+``) decodes nothing unless it is read: it counts only when its
#: ``with`` body or its enclosing function reads or iterates the bound name.
_OPEN_MODULE_HEADS = {"io", "codecs"}
_COMPRESSED_TEXT_OPEN_HEADS = {"gzip", "bz2", "lzma"}
_NON_TEXT_OPEN_HEADS = (set(NON_FILE_OPENERS) - _OPEN_MODULE_HEADS) | {"subprocess"}
_HANDLE_READ_METHODS = {"read", "readline", "readlines"}
#: The structured files this lane's strict arm covers, by the words a read of
#: one carries in its own call text or its enclosing function's name: a tolerant
#: ``errors=`` on one masks corruption behind a clean parse (a replacement
#: character inside a probe id or a fingerprint command is still valid JSON),
#: so it is an offender in its own right -- the file twin of the subprocess
#: pin's ``_STRUCTURED_ARGV_TOKENS``. The ledger and the docs are prose and stay
#: out. Over-collecting costs a rename; under-collecting is the drift this
#: exists to stop.
_STRUCTURED_FILE_TOKENS = (
    "fingerprint", "MANIFEST_PATH", "integrity.json", "freshness.json",
    "execution_plan", "PROBES", "allowlist",
)
#: The strict-arm marker (DEF-821 on captures, DEF-829 on files). It is READ:
#: every line carrying it must be an ``except`` naming ``ValueError``, so it
#: cannot be copied onto a replace site as prose.
_STRICT_DECODE_MARKER = "# strict decode: a structured answer"


def _open_mode_literal(call: ast.Call, pos: int) -> object:
    """The ``mode`` argument as a literal -- positional at ``pos`` or by keyword;
    ``"r"`` when absent (the default); ``None`` when it is not a literal."""
    mode: object = "r"
    if len(call.args) > pos:
        arg = call.args[pos]
        mode = arg.value if isinstance(arg, ast.Constant) else None
    for k in call.keywords:
        if k.arg == "mode":
            mode = k.value.value if isinstance(k.value, ast.Constant) else None
    return mode


def _enclosing_function(tree: ast.AST, node: ast.AST) -> ast.AST | None:
    """The innermost def holding ``node``, or None at module level."""
    best = None
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            node is d for d in ast.walk(fn)
        ):
            if best is None or fn.lineno > best.lineno:
                best = fn
    return best


def _plus_mode_handle_is_read(call: ast.Call, tree: ast.AST) -> bool:
    """A ``+``-mode text handle is a read when the name it is bound to (a
    ``with`` item or an assignment) is read or iterated in that ``with`` body
    or, for an assignment, anywhere in the enclosing function."""
    name, body = None, []
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if item.context_expr is call and isinstance(item.optional_vars, ast.Name):
                    name, body = item.optional_vars.id, node.body
        elif (
            isinstance(node, ast.Assign) and node.value is call
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        ):
            fn = _enclosing_function(tree, node)
            name, body = node.targets[0].id, (fn.body if fn is not None else tree.body)
    if name is None:
        return False
    for stmt in body:
        for d in ast.walk(stmt):
            if (
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr in _HANDLE_READ_METHODS
                and isinstance(d.func.value, ast.Name) and d.func.value.id == name
            ):
                return True
            if isinstance(d, ast.For) and isinstance(d.iter, ast.Name) and d.iter.id == name:
                return True
    return False


def _text_read_spelling(call: ast.Call, tree: ast.AST | None = None) -> tuple[str, bool] | None:
    """``(label, tolerant)`` when ``call`` decodes a file to text -- the label
    names the spelling, ``tolerant`` whether an ``errors=`` that cannot raise
    is on it (``strict`` and ``None`` are the default spelled out, and no
    guard); else None."""
    f = call.func
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    tolerant = _errors_tolerant(kw)
    if isinstance(f, ast.Attribute) and f.attr == "read_text":
        return "read_text", tolerant
    if isinstance(f, ast.Attribute) and f.attr == "decode":
        positional = (
            len(call.args) > 1 and isinstance(call.args[1], ast.Constant)
            and call.args[1].value in _DECODE_TOLERANT_ERRORS
        )
        return "decode", tolerant or positional
    if isinstance(f, ast.Name) and f.id == "open":
        mode, label = _open_mode_literal(call, 1), "open"
    elif isinstance(f, ast.Attribute) and f.attr == "open":
        head = f.value.id if isinstance(f.value, ast.Name) else None
        if head in _COMPRESSED_TEXT_OPEN_HEADS:
            mode = _open_mode_literal(call, 1)
            if not isinstance(mode, str) or "t" not in mode:
                return None  # a binary archive handle
            label = f"{head}.open"
        elif head in _NON_TEXT_OPEN_HEADS:
            return None
        else:
            pos = 1 if head in _OPEN_MODULE_HEADS else 0
            mode, label = _open_mode_literal(call, pos), f"{head or '<path>'}.open"
    else:
        return None
    if not isinstance(mode, str) or "b" in mode:
        return None
    if "r" not in mode and not (
        "+" in mode and tree is not None and _plus_mode_handle_is_read(call, tree)
    ):
        return None
    return label, tolerant


def _strict_text_read_spelling(call: ast.Call, tree: ast.AST | None = None) -> str | None:
    """The label from ``_text_read_spelling`` when the read is strict, else None."""
    read = _text_read_spelling(call, tree)
    return None if read is None or read[1] else read[0]


def _reads_a_structured_file(call: ast.Call, tree: ast.AST, source: str) -> str | None:
    """The first ``_STRUCTURED_FILE_TOKENS`` word in the call's own text or the
    enclosing function's name, or None."""
    fn = _enclosing_function(tree, call)
    window = (ast.get_source_segment(source, call) or "") + " " + (fn.name if fn is not None else "")
    return next((t for t in _STRUCTURED_FILE_TOKENS if t in window), None)


def _text_reads_under_a_handler_that_lets_the_decode_error_past(
    rel: str, source: str,
) -> list[tuple[int, str, str]]:
    """(lineno, spelling, why) for each strict text read inside a try BODY --
    same frame -- when none of the tries enclosing it catches the decode error,
    and for each tolerant read of a structured file (anywhere). A strict read
    under no try at all is the site's stated crash, not a handler that lies,
    and is not counted (the declared limit the class docstring measures); so
    is one in an ``else:`` or ``finally:`` block, which no handler covers."""
    tree = ast.parse(source, filename=rel)
    tries = [t for t in ast.walk(tree) if isinstance(t, _TRY_TYPES)]
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        read = _text_read_spelling(node, tree)
        if read is None:
            continue
        spelling, tolerant = read
        if tolerant:
            token = _reads_a_structured_file(node, tree, source)
            if token is not None:
                out.append((node.lineno, spelling, (
                    f"a tolerant errors= on a structured file ({token}) masks corruption "
                    "behind a clean parse; hand the bytes to the tolerant helper or keep "
                    "the strict read under a handler naming ValueError"
                )))
            continue
        enclosing = [
            t for t in tries
            if any(node is d for stmt in t.body for d in _walk_same_frame(stmt))
        ]
        if not enclosing or any(_try_catches_decode_error(t) for t in enclosing):
            continue
        names = sorted({
            n.id for t in enclosing for h in t.handlers if h.type is not None
            for n in ast.walk(h.type) if isinstance(n, ast.Name)
        })
        out.append((node.lineno, spelling, (
            f"under except({', '.join(names) or '<none>'}), which cannot catch "
            "UnicodeDecodeError (a ValueError)"
        )))
    return out


def _strict_decode_markers_off_a_value_error_handler(source: str) -> list[int]:
    """Line numbers carrying ``_STRICT_DECODE_MARKER`` that are not an ``except``
    naming ``ValueError`` -- the marker read as a contract, not prose."""
    out: list[int] = []
    for i, line in enumerate(source.splitlines(), 1):
        if _STRICT_DECODE_MARKER in line:
            head = line.split("#", 1)[0].strip()
            if not (head.startswith("except") and "ValueError" in head):
                out.append(i)
    return out


class TestTextReadsDecodeGuarded:
    """Ledger DEF-829: the ``read_text`` twin of ``TestSubprocessDecodeGuarded``.
    A strict text-file read -- ``Path.read_text(encoding="utf-8")``, a
    ``bytes.decode``, or a text-mode ``open`` that reads -- raises
    ``UnicodeDecodeError``, a ``ValueError``, on a file that is not UTF-8, and
    an ``except OSError:`` around it lets that past: a handler that promises
    the file's failure path and does not keep it. Measured at HEAD before the
    sweep: 17 sites on the derived surface, seven of them under ``tools/cc``
    -- the adopter-tree readers ``cc/COMMANDS.md`` (the SessionStart banner,
    lost on every session through the fail-open crash guard), the fingerprint
    (the Stop gate's fail-closed crash guard, a block on every Stop under the
    full mode) and the manifest (every integrity check) among them. The arm
    follows the CONSUMER: bytes handed to a tolerant helper
    (``load_json_dict_safe``), or ``errors="replace"`` with ``ValueError``
    beside the ``OSError``, where the text is names, lines or sentences; a
    strict read under a handler naming ``ValueError`` where the file is a
    structured answer whose parse failure already has a path (a JSON file),
    marked ``# strict decode: a structured answer (DEF-829)``; a source file
    parsed from bytes, so a non-UTF-8 file is the ``SyntaxError`` the handler
    already names. The inverse arm holds too: a tolerant ``errors=`` on one of
    the lane's structured files (``_STRUCTURED_FILE_TOKENS``) is an offender,
    and the marker is read (``_strict_decode_markers_off_a_value_error_handler``).

    Declared limits, each re-derivable with these helpers over
    ``_iter_production_py`` (the figures were measured 2026-09-17, after the
    sweep): a strict read under NO try at all is not counted -- it is the
    site's stated crash only where nothing promises otherwise, and the two
    readers of ``cc/PACK_MANIFEST.txt`` behind ``/status`` and ``doctor``
    (``session_resume._manifest_missing_docs``, ``self_hosting``) were such a
    promise and now read with a replacement character; the population left is
    78 strict reads, 14 of them ``bytes.decode`` calls
    whose callers all catch. A ``+``-mode text handle counts only when it is
    read (9 such handles on the surface, the lock-file idiom, none
    read). A read in a try's ``else:`` or ``finally:`` block is outside every
    handler and reads as no-try; a non-literal mode cannot be judged and is not
    a read; ``io.TextIOWrapper`` is not a spelling here (none on the surface).
    """

    def test_no_strict_text_read_sits_under_a_handler_that_lets_the_decode_error_past(self):
        offenders: list[str] = []
        for rel, p in _iter_production_py():
            for lineno, spelling, why in (
                _text_reads_under_a_handler_that_lets_the_decode_error_past(
                    rel, p.read_text(encoding="utf-8")
                )
            ):
                offenders.append(f"{rel}:{lineno} {spelling}: {why}")
        assert not offenders, (
            f"{len(offenders)} text read(s) are not decode-guarded. Decide by the "
            "CONSUMER first: where the bytes go to a tolerant helper (load_json_dict_safe, "
            "decode_bom) hand it read_bytes(); where the file is a structured answer (a "
            "JSON file, a fingerprint, a manifest) keep the strict read and add ValueError "
            "to the handler, marked `# strict decode: a structured answer (DEF-829)` -- "
            "never errors=\"replace\" there; where the file is Python source parse the "
            "bytes so the failure is the SyntaxError already named; only where the text is "
            'names, lines or sentences read with errors="replace" and put ValueError beside '
            "the OSError. A settings file or an operator-written record belongs to "
            "tests/test_settings_reader_bom_contract.py instead: read BYTES through "
            "decode_bom, never a tolerant read_text:\n  " + "\n  ".join(offenders)
        )

    def test_every_strict_decode_marker_sits_on_a_handler_naming_value_error(self):
        bad = [
            f"{rel}:{ln}"
            for rel, p in _iter_production_py()
            for ln in _strict_decode_markers_off_a_value_error_handler(p.read_text(encoding="utf-8"))
        ]
        assert not bad, (
            "`# strict decode: a structured answer` marks a handler that names ValueError; "
            f"on any other line it is prose copied onto a site it does not describe: {bad}"
        )

    def test_the_marker_check_reads_the_line(self):
        """Earn the red on the marker contract itself."""
        assert _strict_decode_markers_off_a_value_error_handler(
            "try:\n    x = p.read_text(encoding='utf-8')\n"
            "except (OSError, ValueError):  # strict decode: a structured answer (DEF-829)\n    pass\n"
        ) == []
        assert _strict_decode_markers_off_a_value_error_handler(
            "x = p.read_text(encoding='utf-8', errors='replace')  # strict decode: a structured answer (DEF-829)\n"
        ) == [1]
        assert _strict_decode_markers_off_a_value_error_handler(
            "try:\n    pass\nexcept OSError:  # strict decode: a structured answer (DEF-829)\n    pass\n"
        ) == [3]

    def test_the_census_reads_the_spelling_the_handler_and_the_try_body(self):
        """Earn the red on the pin's own arms, on synthetic modules."""
        def offenders(src: str) -> list[int]:
            return [
                ln for ln, _s, _w in
                _text_reads_under_a_handler_that_lets_the_decode_error_past("synthetic.py", src)
            ]

        def module(read: str, handler: str = "OSError") -> str:
            return (
                "import gzip, io, os\n"
                "from pathlib import Path\n"
                "def f(p, raw):\n"
                "    try:\n"
                f"        return {read}\n"
                f"    except {handler}:\n"
                "        return None\n"
            )

        # The handler: an OSError-only tuple is not a guard; naming the decode
        # error, ValueError, Exception or a bare except is.
        assert offenders(module("p.read_text(encoding='utf-8')")) == [5]
        assert offenders(module("p.read_text(encoding='utf-8')", "(OSError, ValueError)")) == []
        assert offenders(module("p.read_text(encoding='utf-8')", "UnicodeDecodeError")) == []
        assert offenders(module("p.read_text(encoding='utf-8')", "Exception")) == []
        assert offenders(module("p.read_text(encoding='utf-8')").replace("except OSError:", "except:")) == []
        # errors=: tolerant is a guard; strict and None are the default spelled out.
        assert offenders(module("p.read_text(encoding='utf-8', errors='replace')")) == []
        assert offenders(module("p.read_text(encoding='utf-8', errors='strict')")) == [5]
        assert offenders(module("p.read_text(encoding='utf-8', errors=None)")) == [5]
        # The spelling: bytes and descriptors decode nothing; a write-mode handle
        # is the lock-file idiom unless it is read; every reading text open
        # counts, the default mode included, at the position each head takes
        # its mode; a compressed opener is text only with a `t` in the mode;
        # bytes.decode counts, with its errors slot positional or by keyword.
        assert offenders(module("p.read_bytes()")) == []
        assert offenders(module("open(p, 'rb')")) == []
        assert offenders(module("open(p, 'a+', encoding='utf-8')")) == []
        assert offenders(module("os.open(p, os.O_RDONLY)")) == []
        assert offenders(module("open(p, encoding='utf-8')")) == [5]
        assert offenders(module("open(p, 'r', encoding='utf-8')")) == [5]
        assert offenders(module("open(p, mode='r', encoding='utf-8')")) == [5]
        assert offenders(module("io.open(p, 'r', encoding='utf-8')")) == [5]
        assert offenders(module("p.open()")) == [5]
        assert offenders(module("p.open('r', encoding='utf-8')")) == [5]
        assert offenders(module("p.open('rb')")) == []
        assert offenders(module("open(p, mode, encoding='utf-8')")) == []  # not a literal
        assert offenders(module("gzip.open(p, 'rt', encoding='utf-8')")) == [5]
        assert offenders(module("gzip.open(p)")) == []
        assert offenders(module("raw.decode('utf-8')")) == [5]
        assert offenders(module("raw.decode()")) == [5]
        assert offenders(module("raw.decode('utf-8', 'replace')")) == []
        assert offenders(module("raw.decode('utf-8', errors='replace')")) == []
        assert offenders(module("raw.decode('utf-8')", "(OSError, ValueError)")) == []
        # A `+` handle that IS read is a read: in its with body, or after an
        # assignment anywhere in the function.
        plus_read_in_with = (
            "def f(p):\n    try:\n        with open(p, 'a+', encoding='utf-8') as fh:\n"
            "            fh.seek(0)\n            return fh.read()\n    except OSError:\n        return None\n"
        )
        plus_iterated = plus_read_in_with.replace("return fh.read()", "return list(fh)").replace(
            "fh.seek(0)", "for line in fh:\n                pass"
        )
        plus_assigned = (
            "def f(p):\n    try:\n        fh = open(p, 'a+', encoding='utf-8')\n"
            "    except OSError:\n        return None\n    return fh.readline()\n"
        )
        plus_locked_only = (
            "def f(p):\n    try:\n        with open(p, 'a+', encoding='utf-8') as fh:\n"
            "            fh.write('x')\n    except OSError:\n        return None\n"
        )
        assert offenders(plus_read_in_with) == [3]
        assert offenders(plus_iterated) == [3]
        assert offenders(plus_assigned) == [3]
        assert offenders(plus_locked_only) == []
        # The inverse arm: a tolerant errors= on a structured file is an offender
        # wherever it sits; the same read of prose is not.
        assert offenders("def f(p):\n    return p.read_text(encoding='utf-8', errors='replace')\n") == []
        assert offenders("def f(fingerprint_path):\n    return fingerprint_path.read_text(encoding='utf-8', errors='replace')\n") == [2]
        assert offenders("def _read_fingerprint(p):\n    return p.read_text(encoding='utf-8', errors='replace')\n") == [2]
        assert offenders("def f(p):\n    return _PROBES.read_text(encoding='utf-8', errors='replace')\n") == [2]
        # The try body, same frame: a read in else:, finally:, under no try, or
        # in a nested def inside the body runs outside the handler.
        in_else = (
            "def f(p):\n    try:\n        pass\n    except OSError:\n        return None\n"
            "    else:\n        return p.read_text(encoding='utf-8')\n"
        )
        in_finally = (
            "def f(p):\n    try:\n        pass\n    except OSError:\n        return None\n"
            "    finally:\n        p.read_text(encoding='utf-8')\n"
        )
        no_try = "def f(p):\n    return p.read_text(encoding='utf-8')\n"
        nested = (
            "def f(p):\n    try:\n        def g():\n            return p.read_text(encoding='utf-8')\n"
            "        return g\n    except OSError:\n        return None\n"
        )
        inner_catches = (
            "def f(p):\n    try:\n        try:\n            return p.read_text(encoding='utf-8')\n"
            "        except ValueError:\n            return ''\n    except OSError:\n        return None\n"
        )
        assert offenders(in_else) == []
        assert offenders(in_finally) == []
        assert offenders(no_try) == []
        assert offenders(nested) == []
        assert offenders(inner_catches) == []

    def test_the_non_text_opener_roster_is_the_scanners(self):
        """Derived, not forked: the roster is the encoding scanner's canon set
        minus the text opener it declines to judge, plus subprocess."""
        assert "codecs" not in _NON_TEXT_OPEN_HEADS and "codecs" in _OPEN_MODULE_HEADS
        assert "subprocess" in _NON_TEXT_OPEN_HEADS
        assert _NON_TEXT_OPEN_HEADS - {"subprocess"} == set(NON_FILE_OPENERS) - {"codecs"}


class TestFanoutSchemaParity:
    """The live (re-runnable) fan-out workflows inline a copy of FINDING_SCHEMA
    because the JS Workflow sandbox cannot import Python. This pins those copies
    to the Python SoT (espalier/fan_out_findings.FINDING_SCHEMA) so a new fan-out
    cannot silently drift. The v1 12-field one-shots are DELIBERATELY frozen
    (memory/fan-out-finding-schema.md) and are excluded by explicit allowlist.
    """

    # Go-forward set: copies that MUST track the SoT.
    LIVE_V2 = {
        "_deep_review_2026_06_18.js",
        "_deep_review_round7.js",
        "_fanout_audit.js",
        "_oss_convergence_round4.js",
        "_layered_review.js",      # added by Task 2-A; lands schema-correct on day one
        "_convergence_2026_07_13.js",  # post-batch review; inlines the current 13-field v2 schema
        "_convergence_review_template.js",  # TP-287 scope-breaker-complete scaffold; STANDING persister, current v2 schema
        # Round 9 (2026-08-05), tracked by TP-423. Both were untracked, so
        # `git ls-files` could not see them and this partition read green
        # vacuously over them; committing enrols them. Measured before landing:
        # each file's required[] equals the FINDING_SCHEMA SoT exactly (13
        # fields, zero diff) and each REFUTE_RESULT is a strict subset of the
        # schema properties, so the two sibling contracts below stay green.
        "_oss_launch_review_2026_08_05.js",
        "_goalie_unswept_2026_08_05.js",
    }
    # Frozen historical one-shots (12-field v1 capture) have all been pruned —
    # the tracked corpus now carries only go-forward LIVE_V2 copies. Kept as an
    # empty set so the partition below stays exhaustive and a future deliberately
    # -frozen capture re-adds here (otherwise a new inlining workflow must track
    # the SoT). See memory/fan-out-finding-schema.md.
    FROZEN_V1: set[str] = set()

    @staticmethod
    def _finding_const_files():
        """Mechanically enumerate workflows that inline a FINDING_SCHEMA-shaped
        const (fingerprint: BOTH 'minimal_repro' and 'verification' appear as
        quoted keys). The named sets above are a FLOOR — this derives the REAL
        set so a new inlining workflow can't land unclassified.

        QUOTE-AGNOSTIC: the v1 frozen schemas use JSON-style double-quoted keys
        ("verification"); the v2 live schemas use JS-style single-quoted keys
        ('verification'). A single-quote-only fingerprint matched 5 of 12 files
        and the partition test shipped RED. Match either quote style.
        """
        import subprocess

        out = subprocess.run(
            ["git", "ls-files", ".claude/workflows/*.js"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout.split()
        hits = set()
        for rel in out:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            if re.search(r"""['"]minimal_repro['"]""", text) and \
               re.search(r"""['"]verification['"]""", text):
                hits.add(Path(rel).name)
        return hits

    @staticmethod
    def _required_set(text):
        # The LIVE_V2 copies are uniformly single-quoted JS literals (the
        # go-forward shape); grab the FIRST `required: [ ... ]` block and take
        # the single-quoted tokens — set-compare ignores order/whitespace.
        m = re.search(r"required:\s*\[(.*?)\]", text, re.DOTALL)
        assert m, "no required[] array found"
        return set(re.findall(r"'([a-z_]+)'", m.group(1)))

    def test_live_copies_track_sot(self):
        from espalier.fan_out_findings import FINDING_SCHEMA

        sot_required = set(FINDING_SCHEMA["required"])
        for name in sorted(self.LIVE_V2):
            text = (REPO_ROOT / ".claude/workflows" / name).read_text(encoding="utf-8")
            assert self._required_set(text) == sot_required, (
                f"{name} required[] drifted from FINDING_SCHEMA SoT"
            )

    def test_classification_partitions_all_finding_workflows(self):
        """No inlining workflow may be unclassified: the real fingerprinted set
        must equal LIVE_V2 u FROZEN_V1, so a NEW copy forces a deliberate
        classify-or-freeze decision (fail-closed)."""
        found = self._finding_const_files()
        assert found == (self.LIVE_V2 | self.FROZEN_V1), (
            f"unclassified fan-out schema copy: {found ^ (self.LIVE_V2 | self.FROZEN_V1)}"
        )

    def test_refute_fields_subset_finding_props(self):
        # The refuter verdict is merged {...f, ...v} into each finding; since
        # FINDING_SCHEMA is additionalProperties:false, a refute-only field not
        # in the schema (e.g. the historical corrected_severity) marks EVERY
        # finding invalid at persist. Pin REFUTE_RESULT keys ⊆ schema props so
        # such a field can never reach a workflow. See
        # memory/fanout-refute-fields-must-subset-finding-schema.md.
        from espalier.fan_out_findings import FINDING_SCHEMA

        allowed = set(FINDING_SCHEMA["properties"])
        for name in sorted(self.LIVE_V2):
            text = (REPO_ROOT / ".claude/workflows" / name).read_text(encoding="utf-8")
            m = re.search(
                r"REFUTE_RESULT\s*=\s*\{.*?properties:\s*\{(.*?)\n\s*\},",
                text, re.DOTALL,
            )
            if not m:
                continue  # not every live workflow defines a REFUTE_RESULT
            keys = set(re.findall(r"\n\s*([a-z_]+):\s*\{", m.group(1)))
            stray = keys - allowed
            assert not stray, f"{name} REFUTE_RESULT has non-schema field(s): {stray}"


def _engine_modules() -> list[Path]:
    """Every ``espalier/**/*.py`` that IS the engine: the two byte-mirrors
    (``_vendor/``, the ``tools/cc`` copy; ``assets/``, the deployed bodies)
    are governed by their sources' rules and excluded."""
    return sorted(
        p for p in (REPO_ROOT / "espalier").rglob("*.py")
        if "_vendor" not in p.parts and "assets" not in p.parts
    )


# pins: claim:def-763-settings-presence-by-errno
class TestSettingsPresenceNeverAsksPathlib:
    """DEF-763: ``Path.exists()``, ``is_file()``, ``is_dir()`` and
    ``is_symlink()`` answer a parent that denies traversal per interpreter --
    CPython 3.10-3.13 let the stat's ``PermissionError`` out, 3.14 returns
    ``False`` (measured on real interpreters 2026-09-13; the boundary itself is
    pinned in ``tests/test_surface_contract.py``) -- so every existence check
    on ``.claude/settings.json`` in the engine gave a different verdict per
    floor: a bare crash on four, "absent, run init" on the fifth. The one
    oracle is ``surface_contract.path_presence`` (by errno) with the
    ``os.path.*`` predicates, which swallow uniformly, for the yes/no sites
    behind it.

    Two nets, because each has a hole the other covers. The static one
    derives its population from EVERY engine module by AST, never a typed
    list, and names a settings-named receiver asking a pathlib existence
    method -- it cannot see a receiver spelled ``path`` or ``target``. The
    behavioural one (``TestTheEngineHoldsUnderLegacyPathlib``) runs the
    product against a locked ``.claude`` under the 3.10-3.13 pathlib bodies
    on this host, so any spelling that raises is caught, at the cost of
    covering only the entry points it drives. The third test keeps the
    static one from passing vacuously.
    """

    PATHLIB_EXISTENCE = frozenset({"exists", "is_file", "is_dir", "is_symlink"})

    def _pathlib_existence_calls_on_settings_paths(self) -> list[str]:
        hits: list[str] = []
        for path in _engine_modules():
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.PATHLIB_EXISTENCE
                    and not node.args and not node.keywords
                ):
                    continue
                receiver = ast.unparse(node.func.value)
                if "settings" in receiver.lower():
                    hits.append(f"{rel}:{node.lineno} {receiver}.{node.func.attr}()")
        return hits

    def test_no_settings_path_asks_pathlib_whether_it_exists(self):
        hits = self._pathlib_existence_calls_on_settings_paths()
        assert not hits, (
            "a settings-path existence check bypasses surface_contract.path_presence "
            "(pathlib answers a no-traverse parent per interpreter -- DEF-763). Route "
            "it through the oracle, or through os.path.isfile / os.path.lexists for a "
            "uniform yes/no; do NOT rename the variable to slip past this matcher:\n"
            + "\n".join(hits)
        )

    def test_the_oracle_is_asked_where_the_verdicts_are_rendered(self):
        """Population floor: cli (the merge, its predicate, the rewire, the
        command gate) and doctor (the presence loop, the gate) each ask the
        oracle; proofs asks the root question. An empty population would let
        the first test pass over a tree that deleted every site."""
        asked: dict[str, set[str]] = {}
        for rel in ("espalier/cli.py", "espalier/doctor.py", "espalier/proofs.py"):
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
            names = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            }
            asked[rel] = names & {"path_presence", "unreadable_harness_root"}
        assert {"path_presence", "unreadable_harness_root"} <= asked["espalier/cli.py"], asked
        assert {"path_presence", "unreadable_harness_root"} <= asked["espalier/doctor.py"], asked
        assert "unreadable_harness_root" in asked["espalier/proofs.py"], asked


class TestTheEngineHoldsUnderLegacyPathlib:
    """The behavioural net for DEF-763: the entry points that answer for
    ``.claude/settings.json`` run against a locked ``.claude`` with the
    3.10-3.13 pathlib bodies substituted (``tests/_legacy_pathlib.py``), so a
    raise reproduces on the 3.14 dev host. ``probes_raise_on_eacces`` is the
    negative control: if the emulation is not in force the block proves
    nothing, and the test says so rather than passing.
    """

    def test_every_entry_point_answers_instead_of_raising(self, harness_repo, capsys):
        from espalier import cleanup, cli, doctor, harness_config, proofs, repo_mode, self_hosting

        claude_dir = harness_repo / ".claude"
        settings = claude_dir / "settings.json"
        with locked(claude_dir), legacy_pathlib_probes():
            assert probes_raise_on_eacces(settings), "emulation not in force; nothing proven"
            assert doctor.run_doctor_check(harness_repo, skip_self_host=True)["status"] == "fail"
            assert proofs.run_cc_surface_gate(harness_repo)["status"] == "fail"
            assert cli.merge_hooks_into_settings(settings, repo_root=harness_repo).status == cli.MERGE_UNREADABLE
            assert cli.merge_refusal_for_file(settings, harness_repo).startswith("unreadable")
            assert cli.rewire_interpreter_in_settings(settings).status == cli.REWIRE_UNREADABLE
            assert cli._resolve_repo_arg(str(harness_repo)) is None
            assert harness_config.unwired_reporter_hooks(harness_repo) == []
            assert cleanup._unwire_espalier_hooks(harness_repo, dry_run=True) == []
            assert repo_mode.detect_repo_mode(harness_repo) in {
                repo_mode.REPO_MODE_UNINITIALIZED, repo_mode.REPO_MODE_SOURCE_CHECKOUT,
                repo_mode.REPO_MODE_INITIALIZED_CONSUMER, repo_mode.REPO_MODE_INITIALIZED_SELF_HOST,
            }
            assert self_hosting.main([str(harness_repo)]) == 2
            with pytest.raises(PermissionError):
                cli.preview_managed_surface(harness_repo)
        err = capsys.readouterr().err
        assert err.count(".claude cannot be read") >= 2, err  # the resolver and the module entry point


class TestTreeRemovalClearsReadOnly:
    """DEF-734: on Windows a file carrying the read-only attribute -- every
    packfile git writes, preserved by ``shutil.copytree`` when ``fuse`` copies
    a host's ``.git`` -- makes ``os.unlink`` raise, so a bare ``shutil.rmtree``
    stops there: the ``fuse`` rollback (``ignore_errors=True``) silently left
    the partial fusion its own non-empty guard then refused on retry, and
    ``cleanup`` raised mid-teardown. On POSIX the same file deletes without
    complaint, so a green delete here is no evidence about the Windows one.

    The class fix is two helpers in ``espalier._rmtree`` -- ``remove_tree``
    and, because a hook is a FILE and ``cleanup`` deletes it through its file
    arm, ``remove_file`` -- whose handler clears the bit and retries. Two nets,
    each derived by AST: no engine module calls ``rmtree`` directly, and the
    two teardown modules (``cleanup``, the ``fuse`` rollback) call no
    ``unlink``/``remove`` directly either, so the next site cannot regrow the
    class one call at a time at either shape. The third test is the
    population floor, read from the same walker the first net uses: the two
    teardown modules must be in the population and must call both helpers, or
    a walker that returned nothing would pass the nets over an empty set.
    """

    OWNER = "espalier/_rmtree.py"
    TEARDOWN_MODULES = ("espalier/fuse.py", "espalier/cleanup.py")

    @staticmethod
    def _population() -> dict[str, Path]:
        return {p.relative_to(REPO_ROOT).as_posix(): p for p in _engine_modules()}

    @staticmethod
    def _calls(tree: ast.AST, names: frozenset[str]) -> list[ast.Call]:
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in names:
                out.append(node)
        return out

    def _direct_rmtree_calls(self) -> list[str]:
        hits: list[str] = []
        for rel, path in self._population().items():
            if rel == self.OWNER:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            hits.extend(
                f"{rel}:{node.lineno} {ast.unparse(node.func)}(...)"
                for node in self._calls(tree, frozenset({"rmtree"}))
            )
        return hits

    def test_no_engine_module_calls_rmtree_directly(self):
        hits = self._direct_rmtree_calls()
        assert not hits, (
            "a tree removal bypasses espalier._rmtree.remove_tree (a read-only "
            "file makes a bare rmtree stop on Windows -- DEF-734). Route it through "
            "the helper: strict for a teardown that must report what it left, "
            "best_effort=True inside a rollback that must not mask the original "
            "fault:\n" + "\n".join(hits)
        )

    def test_the_teardown_modules_delete_no_file_directly(self):
        """The file arm: ``Path.unlink()`` / ``os.unlink`` / ``os.remove`` in
        cleanup or the fuse rollback is the same class at the shape the first
        walk actually hit (an ``attrib +R`` hook is a file)."""
        hits: list[str] = []
        for rel in self.TEARDOWN_MODULES:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
            hits.extend(
                f"{rel}:{node.lineno} {ast.unparse(node.func)}(...)"
                for node in self._calls(tree, frozenset({"unlink", "remove"}))
            )
        assert not hits, (
            "a file delete in a teardown module bypasses espalier._rmtree.remove_file "
            "(the Windows read-only attribute makes a bare unlink raise -- DEF-734):\n"
            + "\n".join(hits)
        )

    def test_the_teardown_modules_are_in_the_population_and_call_both_helpers(self):
        population = self._population()
        assert set(self.TEARDOWN_MODULES) <= set(population), sorted(population)[:5]
        assert self.OWNER in population, "the owner left the walker's population"
        for rel in self.TEARDOWN_MODULES:
            tree = ast.parse(population[rel].read_text(encoding="utf-8"), filename=rel)
            called = {
                node.func.id for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            assert {"remove_tree", "remove_file"} <= called, (rel, sorted(called))
