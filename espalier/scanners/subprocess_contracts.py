"""Detect cross-module subprocess invocations not pinned by a contract.

Stdlib-only AST walker. The registry is INLINED so harness-package
imports are forbidden (per TestScannerSelfContainment in
tests/test_scanners.py).

Detection covers:
- ``subprocess.run / check_output / check_call / call / Popen``
- ``subprocess.Popen(...).communicate()`` (chained)
- ``os.system(...)``, ``os.popen(...)``
- ``shell=True`` single-string positional form

OS-utility binaries (git, pytest, tar, ...) are skipped via OS_BINARIES
because they are not part of the espalier-internal contract surface.
Calls whose argv cannot be statically resolved are reported as
UNRESOLVED so the operator must either refactor to a literal list or
attach a ``# subprocess-contract: ok <reason>`` pragma citing the
contract test that pins the surface.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# ─────────────────────────────────────────────────────────────────────
# INLINED registry — per TestScannerSelfContainment contract.
# Key: canonicalized descriptor (interpreter + subcommand + flag NAMES;
#      arg VALUES stripped via _canonicalize).
# Value: dotted "<file>::<test>" path to the contract test that pins
#        the surface; verified by
#        test_subprocess_contracts_parity_with_pinned_tests so the
#        registry can never drift from the live test suite without
#        the parity test failing.
SUBPROCESS_CONTRACTS: dict[str, str] = {
    "espalier memory prune --rows --root --allow-empty":
        "tests/test_subprocess_cli_contract.py::test_memory_prune_accepts_documented_flags",
    "python tools/cc/cognitive_blueprint.py finalize":
        "tests/test_subprocess_cli_contract.py::test_cognitive_blueprint_finalize_subcommand_exists",
    "python tools/cc/cognitive_blueprint.py justify":
        "tests/test_subprocess_cli_contract.py::test_cognitive_blueprint_justify_accepts_six_fields",
    "python -m espalier.cli init":
        "tests/test_subprocess_cli_contract.py::test_espalier_init_subcommand_accepts_target_path",
    "python -m espalier.cli --version":
        "tests/test_subprocess_cli_contract.py::test_espalier_version_flag_returns_zero_with_output",
    # scripts/handoff_mechanics.py resolves the archive stem for the handoff leg
    # from the transcript listing; the flag is the contract.
    "python tools/cc/read_summary.py --list":
        "tests/test_subprocess_cli_contract.py::test_read_summary_list_flag_exists",
}

OS_BINARIES: frozenset[str] = frozenset({
    "git", "pytest", "tar", "gzip", "find", "grep", "sed", "awk",
    "rsync", "cp", "mv", "rm", "ls", "cat", "echo", "true", "false",
})

# Python-interpreter shapes — normalized to "python" in the descriptor.
# subprocess.run([sys.executable, ...]) is the canonical way hooks invoke
# Python; without this normalization the descriptor leading token is
# ${sys.executable} (stripped by _canonicalize), leaving e.g.
# tools/cc/... as the leading token, which would not match any
# ESPALIER_SIGNATURE and real internal subprocesses would be silently
# skipped.
PYTHON_INTERPRETER_ATTRS: frozenset[str] = frozenset({
    "sys.executable", "shutil.which", "sys._base_executable",
})
PYTHON_INTERPRETER_NAMES: frozenset[str] = frozenset({
    "python", "python3",
})

# Espalier-internal interpreter signatures (substrings in the descriptor).
# python3 variants retained even though _normalize_interpreter collapses
# to "python" — defensive coverage for sources that pass a literal
# "python3" string the normalizer leaves as-is.
ESPALIER_SIGNATURES: tuple[str, ...] = (
    "espalier ",
    "python tools/cc/",
    "python -m espalier",
    "python3 tools/cc/",
    "python3 -m espalier",
)

# Pragma to mark a dynamically-built subprocess argv (cmd = base + [...])
# as covered by an external contract test. Reason length ≥12 chars
# enforces a non-trivial justification (e.g. cite the contract test).
# Anchored to ^# so only true source comments match — f-string and
# docstring content that mentions the pragma syntax doesn't false-fire.
# Anchored standalone-comment pragma, scanner-specific token + intentional min-reason.
# Purpose-scoped sibling of the convergence_theater / magic_depth pragmas and the
# unanchored inline one in filesystem_contracts; do NOT collapse into a shared factory
# (it would break scanner self-containment and un-recognize live pragmas).
PRAGMA_RE = re.compile(r"^#\s*subprocess-contract:\s*ok\s+(.{12,})$")
# Raised 5 -> 6 for espalier/red_team_guard.py's dynamic-repro-runner pragma
# (verify_repro intentionally executes caller-supplied red-team repro argvs).
# Raised 6 -> 7 (2026-08-20) for scripts/check_ledger_probes.py, which executes
# the per-row probe commands stored in task-packs/LEDGER_PROBES.json. Same shape
# as red_team_guard's: a runner whose callee is data by design, so there is no
# argv to pin. Both are self-host dev tooling, absent from the sdist.
# Raised 7 -> 8 (2026-09-10) for scripts/host_check.py, which runs the steps
# its plan_steps() builds (the suite and the two PowerShell benches) on the
# host it is started on and ships the results as one pushed commit. Same
# shape again: the argv is a planned step, not a literal, so there is nothing
# to pin; self-host dev tooling, absent from the sdist.
MAX_PRAGMA_COUNT: int = 8

# Sister-site protection: fixture files contain intentional positives.
EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    # espalier/_vendor/cc/ is a byte-identical copy of tools/cc/ (the canonical
    # source, already scanned under the "tools" scope). Skip the vendored dup so
    # its pragmas/sites are not double-counted against the cap.
    "espalier/_vendor/",
)
MAX_EXEMPT_PREFIXES: int = 3
# ─────────────────────────────────────────────────────────────────────


def _skip_nested_repos(dirpath: str, dirnames: list[str]) -> None:
    """Drop embedded-repo subdirs from an os.walk ``dirnames`` in place — parity
    with ``espalier._safe_walk.safe_rglob(skip_nested_repos=True)``. Scanners are
    stdlib-only and cannot import ``_safe_walk``, so the prune is duplicated here
    (like ``_safe_rglob`` itself). A nested ``.git`` (dir OR gitlink file) marks a
    foreign project."""
    import os
    dirnames[:] = [
        d for d in dirnames
        if not os.path.exists(os.path.join(dirpath, d, ".git"))
    ]


def _safe_rglob(root, pattern: str = "*"):
    """Symlink-safe rglob (inline — scanners have zero espalier imports, per
    TestScannerSelfContainment; copied via inspect.getsource). See
    espalier/_safe_walk.py for the canonical version. os.walk(followlinks=
    False) never descends a symlinked dir, so it is crash-safe on CPython
    3.10-3.12 where bare rglob follows dir symlinks (ELOOP on a loop)."""
    import fnmatch
    import os
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        _skip_nested_repos(dirpath, dirnames)
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name


@dataclass(frozen=True, slots=True)
class SubprocessFinding:
    caller_path: Path
    caller_lineno: int
    callee_descriptor: str
    severity: str  # PINNED | UNPINNED | UNRESOLVED
    explanation: str


def scan_repo(root: Path) -> list[SubprocessFinding]:
    """Walk production code only. Tests invoking the CLI are contract
    verification, not coupling — they belong to test_subprocess_cli_contract
    by design, not subprocess-stealth detection."""
    findings: list[SubprocessFinding] = []
    for scope in ("espalier", "tools", "scripts"):
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
                continue
            findings.extend(_scan_file(path, root))
    return findings


def build_report(root: Path) -> dict:
    findings = scan_repo(root)
    return {
        "count": len(findings),
        "findings": [
            {
                "caller_path": str(f.caller_path).replace("\\", "/"),
                "caller_lineno": f.caller_lineno,
                "callee_descriptor": f.callee_descriptor,
                "severity": f.severity,
                "explanation": f.explanation,
            }
            for f in findings
        ],
    }


def _pragma_in_line(line: str) -> bool:
    """Single normalization point shared by both pragma
    readers (count_pragmas + _has_pragma_above). Strip before matching the
    ^#-anchored PRAGMA_RE so an indented pragma is seen consistently by the
    cap counter AND the exemption check -- never honored by one while
    invisible to the other."""
    return PRAGMA_RE.search(line.strip()) is not None


def count_pragmas(root: Path) -> int:
    total = 0
    # Align the cap ACCOUNTING scope to the detector's EFFECT scope (scan_repo
    # walks espalier/tools/scripts and deliberately excludes tests/). A pragma
    # under tests/ suppresses nothing, so counting it toward MAX_PRAGMA_COUNT
    # would inflate the cap with no-op pragmas.
    for scope in ("espalier", "tools", "scripts"):
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            # Honor the same file-scope EXEMPT filter the detector (scan_repo)
            # applies, so a pragma in an exempt fixture file does not eat the
            # MAX_PRAGMA_COUNT budget.
            if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            total += sum(
                1 for line in source.splitlines()
                if _pragma_in_line(line)
            )
    return total


def collect_pragmas(root: Path) -> list[dict]:
    """Like ``count_pragmas`` but keep the reason ``PRAGMA_RE`` group 1 captures.
    Mirrors THIS scanner's count_pragmas scope (``espalier``/``tools``/``scripts``,
    deliberately EXCLUDING ``tests/``) and gates on the SAME ``_pragma_in_line``
    normalization point so ``len(collect_pragmas(root)) == count_pragmas(root)``
    holds. Returns ``{scanner, path, line, reason}`` records."""
    records: list[dict] = []
    for scope in ("espalier", "tools", "scripts"):
        scope_dir = root / scope
        if not scope_dir.is_dir():
            continue
        for path in _safe_rglob(scope_dir, "*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(source.splitlines(), start=1):
                if not _pragma_in_line(line):
                    continue
                m = PRAGMA_RE.search(line.strip())
                records.append({
                    "scanner": "subprocess_contracts", "path": rel, "line": i,
                    "reason": m.group(1).strip() if m else "",
                })
    return records


def _scan_file(path: Path, root: Path) -> Iterable[SubprocessFinding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    source_lines = source.splitlines()
    # Collect function-local Name→List bindings so calls like
    # `cmd = [sys.executable, "-m", "espalier.cli", ...]; subprocess.run(cmd)`
    # resolve to the literal list. The scope is the enclosing FunctionDef
    # only — module-level or class-level Name bindings are not tracked
    # because they're less common for argv construction and cross-scope
    # tracking is brittle.
    # Bindings are scoped per enclosing-function chain, so a
    # subprocess.run(cmd) resolves only against ITS own function's
    # `cmd = [...]` (and enclosing functions, for closures) — never a
    # same-named binding in a SIBLING function.
    call_bindings = _scoped_bindings_for_calls(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        descriptor = _extract_subprocess_descriptor(node, call_bindings.get(id(node), {}))
        if descriptor is None:
            continue
        if not descriptor:
            if _has_pragma_above(source_lines, node.lineno):
                continue
            yield SubprocessFinding(
                caller_path=path.relative_to(root),
                caller_lineno=node.lineno,
                callee_descriptor="<dynamic>",
                severity="UNRESOLVED",
                explanation=(
                    "subprocess.* invocation uses a Name- or dynamic-bound "
                    "argv the scanner cannot statically resolve. Either "
                    "refactor to a literal list, OR add "
                    "`# subprocess-contract: ok <reason citing contract test>` "
                    "on the preceding line."
                ),
            )
            continue
        if _is_os_binary(descriptor):
            continue
        if not _is_espalier_internal(descriptor):
            continue
        if _has_pragma_above(source_lines, node.lineno):
            continue
        yield _classify(path, node.lineno, descriptor, root)


def _has_pragma_above(lines: list[str], stmt_lineno: int) -> bool:
    if stmt_lineno < 2:
        return False
    return _pragma_in_line(lines[stmt_lineno - 2])


def _extract_subprocess_descriptor(
    node: ast.Call,
    local_bindings: Optional[dict[str, ast.List]] = None,
) -> Optional[str]:
    """Return the canonicalized descriptor of a subprocess-shape call,
    or None if this isn't a subprocess call we care about."""
    func = node.func

    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        module_name = func.value.id
        if module_name == "subprocess" and func.attr in {
            "run", "check_output", "check_call", "call", "Popen",
        }:
            return _canonicalize(_extract_argv(node, local_bindings))
        if module_name == "os" and func.attr in {"system", "popen"}:
            return _canonicalize(_extract_string_command(node))

    # Popen(...).communicate() chained
    if isinstance(func, ast.Attribute) and func.attr == "communicate":
        if (
            isinstance(func.value, ast.Call)
            and isinstance(func.value.func, ast.Attribute)
            and isinstance(func.value.func.value, ast.Name)
            and func.value.func.value.id == "subprocess"
            and func.value.func.attr == "Popen"
        ):
            return _canonicalize(_extract_argv(func.value, local_bindings))

    return None


def _scoped_bindings_for_calls(tree: ast.AST) -> dict[int, dict[str, ast.List]]:
    """Map each Call node (keyed by ``id``) to the ``name -> ast.List`` bindings
    visible in its enclosing-function scope chain, so a ``subprocess.run(cmd)``
    resolves only against the ``cmd = [...]`` in ITS OWN function (and enclosing
    functions, for closures) — never a same-named binding in a SIBLING function.

    Also handles ``name = X + [literal] + Y`` patterns (via ``_resolve_list_value``).
    Within a scope, last assignment wins (mirrors execution order at
    static-analysis precision); inner scopes shadow enclosing ones.
    """
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def _own_scope_bindings(func: ast.AST) -> dict[str, ast.List]:
        bindings: dict[str, ast.List] = {}

        def visit(node: ast.AST) -> None:
            for child in ast.iter_child_nodes(node):
                # A nested def/lambda/class opens its own scope — its bindings
                # are NOT this function's locals; skip into them.
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                    continue
                if isinstance(child, ast.Assign):
                    list_value = _resolve_list_value(child.value)
                    if list_value is not None:
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                bindings[target.id] = list_value
                visit(child)

        visit(func)
        return bindings

    func_bindings: dict[int, dict[str, ast.List]] = {
        id(node): _own_scope_bindings(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    call_bindings: dict[int, dict[str, ast.List]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Walk the enclosing-function chain outermost→innermost so an inner
        # function's binding shadows an enclosing one (closure semantics).
        chain: list[ast.AST] = []
        cur = parents.get(id(node))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chain.append(cur)
            cur = parents.get(id(cur))
        merged: dict[str, ast.List] = {}
        for fn in reversed(chain):
            merged.update(func_bindings.get(id(fn), {}))
        call_bindings[id(node)] = merged
    return call_bindings


def _resolve_list_value(value: ast.expr) -> Optional[ast.List]:
    """Extract a representative List from a Name binding's RHS.
    - `[a, b]` → that list
    - `base + [a, b]` / `[a, b] + tail` → the literal list operand
    - `base + [a, b] + tail` → the largest list operand
    Used by _scoped_bindings_for_calls."""
    if isinstance(value, ast.List):
        return value
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        candidates: list[ast.List] = []
        stack: list[ast.expr] = [value]
        while stack:
            node = stack.pop()
            if isinstance(node, ast.List):
                candidates.append(node)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                stack.append(node.left)
                stack.append(node.right)
        if candidates:
            return max(candidates, key=lambda n: len(n.elts))
    return None


def _extract_argv(
    call: ast.Call,
    local_bindings: Optional[dict[str, ast.List]] = None,
) -> str:
    if not call.args:
        return ""
    first = call.args[0]
    # `[A, B, ...] + name` / `[A, B] + suffix + [...]` — common in hooks
    # where the dynamic suffix is collected from config but the leading
    # interpreter + script tokens are literal. Extract from the leftmost
    # List literal only; the rest is suffix noise the contract doesn't
    # pin.
    if isinstance(first, ast.BinOp) and isinstance(first.op, ast.Add):
        leftmost = first
        while (
            isinstance(leftmost, ast.BinOp)
            and isinstance(leftmost.op, ast.Add)
            and not isinstance(leftmost.left, ast.List)
        ):
            leftmost = leftmost.left
        if isinstance(leftmost, ast.BinOp) and isinstance(leftmost.left, ast.List):
            return _argv_from_list(leftmost.left)
    if isinstance(first, ast.List):
        return _argv_from_list(first)
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    # `cmd = [literal, ...]; subprocess.run(cmd, ...)` — resolve via
    # function-scope local bindings.
    if isinstance(first, ast.Name) and local_bindings and first.id in local_bindings:
        return _argv_from_list(local_bindings[first.id])
    return ""


def _argv_from_list(list_node: ast.List) -> str:
    parts: list[str] = []
    for idx, elt in enumerate(list_node.elts):
        normalized = _normalize_interpreter(elt) if idx == 0 else None
        if normalized is not None:
            parts.append(normalized)
            continue
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            parts.append(elt.value)
        elif isinstance(elt, ast.Name):
            parts.append(f"${{{elt.id}}}")
        elif isinstance(elt, ast.Attribute):
            parts.append(f"${{{_attr_chain(elt)}}}")
        else:
            parts.append("<dynamic>")
    return " ".join(parts)


def _normalize_interpreter(elt: ast.expr) -> Optional[str]:
    if isinstance(elt, ast.Attribute):
        if _attr_chain(elt) in PYTHON_INTERPRETER_ATTRS:
            return "python"
    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
        if elt.value in PYTHON_INTERPRETER_NAMES:
            return "python"
    if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Attribute):
        if _attr_chain(elt.func) in PYTHON_INTERPRETER_ATTRS:
            return "python"
    return None


def _extract_string_command(call: ast.Call) -> str:
    if call.args and isinstance(call.args[0], ast.Constant):
        if isinstance(call.args[0].value, str):
            return call.args[0].value
    return ""


def _canonicalize(descriptor: str) -> str:
    """Strip arg values to get the contract shape.
    'espalier memory prune --rows ${N} --root ${root}' →
    'espalier memory prune --rows --root'.

    Drops:
    - `${name}` Name placeholders (`_argv_from_list` emits)
    - `<dynamic>` placeholders (Call / unresolvable expressions)
    - positional values following a `--flag`
    """
    if not descriptor:
        return ""
    parts: list[str] = []
    tokens = descriptor.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("$") or token == "<dynamic>":
            i += 1
            continue
        if not token.startswith("-") and parts and parts[-1].startswith("--"):
            i += 1
            continue
        parts.append(token)
        i += 1
    return " ".join(parts)


def _is_os_binary(descriptor: str) -> bool:
    tokens = descriptor.split()
    if not tokens:
        return False
    first_token = tokens[0]
    if first_token in OS_BINARIES:
        return True
    if "/" in first_token:
        basename = first_token.rsplit("/", 1)[-1]
        if basename in OS_BINARIES:
            return True
    return False


def _is_espalier_internal(descriptor: str) -> bool:
    # The bare `espalier ` signature is the CLI-entrypoint interpreter and must
    # anchor to the LEADING token: `npm run espalier deploy` / `kubectl espalier
    # get` / `docker espalier build` mention "espalier" mid-command but are not
    # espalier-internal subprocesses (and `_is_os_binary` returns False for
    # npm/kubectl/docker, so they reach here). The `python .../espalier` /
    # `python -m espalier` signatures stay substring-matched — already
    # interpreter-prefixed, so an interior match is itself the leading shape.
    tokens = descriptor.split()
    first_token = tokens[0] if tokens else ""
    for sig in ESPALIER_SIGNATURES:
        if sig == "espalier ":
            if first_token == "espalier":
                return True
            continue
        if sig in descriptor:
            return True
    return False


def _attr_chain(attr: ast.expr) -> str:
    parts: list[str] = []
    cur: ast.expr = attr
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _classify(
    path: Path, lineno: int, descriptor: str, root: Path,
) -> SubprocessFinding:
    rel = path.relative_to(root)
    if descriptor in SUBPROCESS_CONTRACTS:
        return SubprocessFinding(
            caller_path=rel, caller_lineno=lineno,
            callee_descriptor=descriptor, severity="PINNED",
            explanation=f"contract: {SUBPROCESS_CONTRACTS[descriptor]}",
        )
    return SubprocessFinding(
        caller_path=rel, caller_lineno=lineno,
        callee_descriptor=descriptor, severity="UNPINNED",
        explanation=(
            f"Stealth subprocess: caller {rel}:{lineno} depends on CLI "
            f"surface of `{descriptor}` with no pinned contract. Add an "
            f"entry to SUBPROCESS_CONTRACTS + a sister test in "
            f"tests/test_subprocess_cli_contract.py."
        ),
    )
