"""Mechanical test-gap engine — the spine of ``espalier strengthen``.

Enumerate a repo's public Python surface via ``ast`` (no import, no
execution), cross-reference each symbol against the test tree by NAME, risk-rank
the untested gaps with a weighted mechanical score, and build an advisory
report. This is the ``make-it-prove-it`` half of ``strengthen``: every claim it
makes ("this public symbol has no test reference") is derived mechanically and
re-derivable. It does NOT generate tests, dispatch agents, or auto-commit
anything — the AI-assisted scaffold layer is a *planned* separate surface
(a future ``strengthen --suggest``), not yet built.

Three honest limits are documented in the report itself and must not be
overread:

- The cross-reference is by NAME (an AST token index over the repo's ``.py``
  files, comments/strings excluded), NOT coverage.py ground truth: a symbol
  referenced by name in a test — even without an assertion — reads as "tested",
  and a same-named symbol in another module shares the signal.
- The risk score is a weighted sum of mechanical SIGNALS (exported, fan-in,
  I/O-heuristic, size). The weights are tunable guesses, not measured
  severities — they order the list; they are not magnitudes.
- A characterization test over existing code locks in CURRENT behavior (a
  regression net), NOT correctness. The report says so in plain language.

A single-pass token index (O(files)) is used deliberately in place of a
per-symbol reference walk (O(symbols × files)): on a ~1000-symbol repo the
latter measured minutes, the former seconds.

``espalier/`` may import ``espalier/`` freely (the stdlib-only rule binds
``espalier/scanners/``, not this module).
"""
from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from espalier.analyze import detect_tests, is_harness_output
from espalier._safe_walk import safe_rglob
from espalier._text import plural
from espalier.surface_contract import is_self_host_repo

# Repo-relative prefixes never counted as public surface. ``tests/`` keeps the
# strengthen_fixture (and any adopter test tree) out of a live self-scan;
# ``espalier/_vendor/`` is the byte-mirror; the rest are build/vendor noise.
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/", "__pycache__", "espalier/_vendor/", "build/", "dist/",
    "vendor/", ".venv/", "venv/", "node_modules/", ".git/",
)

# For the reference index we DO scan the test tree (that is where test
# references live) but still skip the vendored mirror + build noise.
_REF_EXEMPT_PREFIXES: tuple[str, ...] = tuple(
    p for p in _EXEMPT_PREFIXES if p != "tests/"
)

# Call names treated as an I/O or state-change signal when they appear inside a
# symbol's body. A coarse heuristic (a same-named pure function trips it too) —
# documented in the report as a signal, not a proof.
_IO_CALL_NAMES: frozenset[str] = frozenset({
    "open", "write", "writelines", "write_text", "write_bytes",
    "read", "read_text", "read_bytes", "connect", "request", "urlopen",
    "execute", "executemany", "commit", "send", "sendall", "recv",
    "save", "remove", "unlink", "rmtree", "mkdir", "makedirs",
    "system", "popen", "check_call", "check_output", "dump",
})

# Mechanical risk weights. UNMEASURED tunable guesses (direction, not
# magnitude): they order the list, they are not severities. See module docstring.
_W_EXPORTED = 3      # named in __all__ — a deliberate public contract
_W_IO = 3            # touches I/O or state — a bug here escapes the process
_W_FANIN_PER_REF = 1  # each reference; contribution capped below
_W_FANIN_CAP = 5     # so one hub symbol can't dwarf every other signal
_W_COMPLEX = 2       # large body — more untested branches
_COMPLEX_LOC = 40    # LOC span at/above which a symbol counts as "large"

_DEFAULT_TOP_N = 20


@dataclass(frozen=True, slots=True)
class PublicSymbol:
    """One public top-level symbol discovered by AST enumeration."""

    module_path: str   # repo-relative, POSIX-normalized (Windows parity)
    name: str
    kind: str          # "function" | "class" | "constant" | "reexport"
    lineno: int
    end_lineno: int
    is_exported: bool  # named in __all__
    does_io: bool      # an I/O/state call name appears in the body


@dataclass(frozen=True, slots=True)
class RankedGap:
    """An untested :class:`PublicSymbol` with its mechanical risk score."""

    symbol: PublicSymbol
    risk_score: int
    reason: str


# ── P1: public-surface enumeration ────────────────────────────────────────

def _str_elements(seq: ast.List | ast.Tuple) -> set[str]:
    """String constants in a list/tuple literal (non-string elements skipped)."""
    return {
        el.value for el in seq.elts
        if isinstance(el, ast.Constant) and isinstance(el.value, str)
    }


def _read_dunder_all(tree: ast.Module) -> set[str] | None:
    """Return the string members of a module-level ``__all__``, or None.

    None (no ``__all__``) and an empty set (``__all__ = []``) are distinct:
    the first means "fall back to non-underscore names", the second means
    "nothing is public". A full ``__all__ = [...]`` sets the base surface; an
    augmented ``__all__ += [...]`` (the split-declaration idiom) accumulates on
    top of it — both are honored so a facade module's whole public list counts.
    """
    found = False
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                found = True
                names = _str_elements(node.value)  # full assignment REPLACES
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.op, ast.Add)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            found = True
            names |= _str_elements(node.value)     # augmented ADDS
    return names if found else None


def _node_name_kind(node: ast.stmt) -> tuple[str | None, str]:
    """Map a top-level statement to (public-symbol-name, kind), or (None, "")."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name, "function"
    if isinstance(node, ast.ClassDef):
        return node.name, "class"
    if isinstance(node, ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id, "constant"
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id, "constant"
    return None, ""


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _body_does_io(node: ast.stmt) -> bool:
    return any(
        isinstance(child, ast.Call) and _call_name(child) in _IO_CALL_NAMES
        for child in ast.walk(node)
    )


def _import_bind_lines(tree: ast.Module) -> dict[str, int]:
    """Map each name bound by a top-level import to that import's line number.

    Handles ``from m import A`` / ``... as B``, ``import m`` / ``... as B``, and
    ``import m.sub`` (which binds the top name ``m``). Gives a re-exported
    ``__all__`` name — bound by an import, not a def/class/assign — a real bind
    site so a facade ``__init__.py``'s public API is not under-reported.
    """
    binds: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                binds.setdefault(local, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                binds.setdefault(local, node.lineno)
    return binds


def _symbols_from_tree(tree: ast.Module, module_path: str) -> list[PublicSymbol]:
    all_names = _read_dunder_all(tree)
    out: list[PublicSymbol] = []
    emitted: set[str] = set()
    for node in tree.body:
        name, kind = _node_name_kind(node)
        if name is None:
            continue
        if name.startswith("__") and name.endswith("__"):
            continue  # dunder — never public surface (__all__, __version__, …)
        if all_names is not None:
            if name not in all_names:
                continue
        elif name.startswith("_"):
            continue
        emitted.add(name)
        lineno = getattr(node, "lineno", 0)
        out.append(PublicSymbol(
            module_path=module_path,
            name=name,
            kind=kind,
            lineno=lineno,
            end_lineno=getattr(node, "end_lineno", lineno),
            is_exported=all_names is not None and name in all_names,
            does_io=_body_does_io(node),
        ))
    # A name listed in __all__ but bound by an IMPORT (the re-export / facade
    # idiom) is never a def/class/assign node, so the loop above misses it. Emit
    # each remaining __all__ name as a re-export at its import bind site (or the
    # module top when the binding is not statically visible) so a facade's
    # declared public API is not falsely reported as covered.
    if all_names is not None:
        bind_lines = _import_bind_lines(tree)
        for name in sorted(all_names - emitted):
            if name.startswith("__") and name.endswith("__"):
                continue
            lineno = bind_lines.get(name, 0)
            out.append(PublicSymbol(
                module_path=module_path,
                name=name,
                kind="reexport",
                lineno=lineno,
                end_lineno=lineno,
                is_exported=True,
                does_io=False,
            ))
    return out


def _posix_relpath(path: Path, repo_root: Path) -> str:
    """Repo-relative path, POSIX-normalized (forward slashes on every host).

    The ``.as_posix()`` is load-bearing on Windows, where ``relative_to``
    yields backslash separators; on POSIX it is a no-op. Raises ``ValueError``
    when ``path`` is not under ``repo_root`` (the caller skips those)."""
    return path.relative_to(repo_root).as_posix()


def _iter_repo_py(repo_root: Path, exempt: tuple[str, ...]):
    """Yield (path, repo_relative_posix) for every ``.py`` file not under an
    exempt prefix. Symlink-safe (``safe_rglob``).

    Harness output -- the deployed ``tools/cc/``, ``.claude/`` and ``cc/``,
    the runtime's ``reports/`` and ``.espalier*`` (``analyze.is_harness_output``,
    the fingerprint's own predicate) -- is skipped on an adopter tree: a fresh
    ``init`` followed by ``strengthen`` reported 395 untested public symbols,
    every one of them the harness's hooks and scripts, and the adopter's own
    module nowhere in the top twenty (DEF-410f sister site, driven
    2026-09-12). On the self-host tree that same ``tools/cc/`` is this repo's
    source and stays in the report.
    """
    skip_harness_output = not is_self_host_repo(repo_root)
    for path in sorted(safe_rglob(repo_root, "*.py")):
        if not path.is_file():
            continue
        try:
            rel = _posix_relpath(path, repo_root)
        except ValueError:
            continue
        if any(rel.startswith(pre) for pre in exempt):
            continue
        if skip_harness_output and is_harness_output(rel):
            continue
        yield path, rel


def enumerate_public_surface(repo_root: Path) -> tuple[list[PublicSymbol], list[str]]:
    """Walk ``repo_root`` for ``*.py`` and return (symbols, unparseable_paths).

    Files under an exempt prefix are skipped so a live self-scan never reports
    its own fixtures/vendored mirror.
    """
    symbols: list[PublicSymbol] = []
    unparseable: list[str] = []
    for path, rel in _iter_repo_py(repo_root, _EXEMPT_PREFIXES):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            unparseable.append(rel)
            continue
        symbols.extend(_symbols_from_tree(tree, rel))
    return symbols, unparseable


# ── P2: test-reference cross-reference (single-pass token index) + mode ────

def _key(symbol: PublicSymbol) -> str:
    return f"{symbol.module_path}::{symbol.name}"


# "Does this path count as EXISTING test coverage?" — true for a `test_*.py` base OR
# any path with a `tests` component. One of three deliberately-different "is it a test
# path?" questions in the tree: cf. test_loosening.iter_test_files ("is it a pytest FILE
# to scan") and surface_impact's `tests/`-prefix module check. They give different
# answers ON PURPOSE — a parity test across the three would fail by design. Leave separate.
def _is_test_path(file_path: str) -> bool:
    norm = file_path.replace("\\", "/")
    parts = norm.split("/")
    base = parts[-1]
    if base.startswith("test_") and base.endswith(".py"):
        return True
    # A repo-relative path has NO leading slash, so a top-level "tests/uses.py"
    # would fail a `"/tests/" in norm` substring check — match the path
    # COMPONENT instead (catches top-level `tests/` and any nested test tree).
    return "tests" in parts


def _referenced_names(tree: ast.AST) -> Counter[str]:
    """Count every identifier USED in a parsed module (comments/strings excluded).

    Captures ``Name`` uses, attribute accesses (``x.foo`` → ``foo``), and import
    bindings. A definition (``def foo`` / ``class Foo``) is NOT a ``Name`` node,
    so the def site does not self-inflate the count — the reference count is
    genuine usage, not "the symbol exists".
    """
    names: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names[node.id] += 1
        elif isinstance(node, ast.Attribute):
            names[node.attr] += 1
        elif isinstance(node, ast.alias):
            names[(node.asname or node.name).split(".")[-1]] += 1
    return names


def _build_reference_index(
    repo_root: Path,
) -> tuple[set[str], Counter[str], dict[str, Counter[str]]]:
    """One pass over the repo's ``.py`` files → (names-referenced-in-tests,
    non-test reference counts, non-test reference counts BY module). The
    per-module map lets the ranker subtract a symbol's same-module references so
    fan-in proxies CROSS-module blast radius, not internal self-references.
    O(files), replacing an O(symbols) reference walk.
    """
    test_names: set[str] = set()
    prod_counts: Counter[str] = Counter()
    prod_by_module: dict[str, Counter[str]] = {}
    for path, rel in _iter_repo_py(repo_root, _REF_EXEMPT_PREFIXES):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        refs = _referenced_names(tree)
        if not refs:
            continue
        if _is_test_path(rel):
            test_names.update(refs)
        else:
            prod_counts.update(refs)
            prod_by_module[rel] = refs
    return test_names, prod_counts, prod_by_module


def _identify_tested_symbols(
    symbols: list[PublicSymbol],
    repo_root: Path,
    test_names: set[str] | None = None,
) -> set[str]:
    """Keys of symbols whose NAME is referenced in a test file.

    ``test_names`` lets a caller share a single reference-index pass; omitted,
    one is built here. AST-based, so comment/string mentions never count.
    """
    if test_names is None:
        test_names, _, _ = _build_reference_index(repo_root)
    return {_key(s) for s in symbols if s.name in test_names}


# ── P3: mechanical risk ranking ───────────────────────────────────────────

def _rank_gaps(
    untested: list[PublicSymbol],
    fan_in_counts: dict[str, int],
    *,
    skip_fan_in: bool = False,
    self_ref_by_module: dict[str, Counter[str]] | None = None,
) -> list[RankedGap]:
    """Weighted mechanical risk score per untested symbol, highest first.

    ``fan_in_counts`` maps symbol name → non-test reference count. When
    ``self_ref_by_module`` is supplied, references inside a symbol's OWN defining
    module are subtracted so fan-in proxies cross-module blast radius (a large
    internal dataclass no longer floats to the top on self-references). Ties
    break on (module_path, name) so the order is stable across runs.
    """
    ranked: list[RankedGap] = []
    for symbol in untested:
        score = 0
        reasons: list[str] = []
        if symbol.is_exported:
            score += _W_EXPORTED
            reasons.append("exported")
        if symbol.does_io:
            score += _W_IO
            reasons.append("io/state")
        if not skip_fan_in:
            total = fan_in_counts.get(symbol.name, 0)
            self_refs = 0
            if self_ref_by_module is not None:
                self_refs = self_ref_by_module.get(symbol.module_path, {}).get(symbol.name, 0)
            fan_in = max(0, total - self_refs)  # cross-module reach only
            if fan_in:
                capped = min(fan_in, _W_FANIN_CAP)
                score += capped * _W_FANIN_PER_REF
                # Surface the CAPPED value (what the score credits) so the row's
                # arithmetic reconciles; keep the raw count as context past the cap.
                if fan_in > _W_FANIN_CAP:
                    reasons.append(f"fan-in {capped} (capped; {fan_in} cross-module refs)")
                else:
                    reasons.append(f"fan-in {fan_in}")
        if symbol.end_lineno - symbol.lineno + 1 >= _COMPLEX_LOC:
            score += _W_COMPLEX
            reasons.append("large")
        ranked.append(RankedGap(
            symbol=symbol,
            risk_score=score,
            reason=", ".join(reasons) if reasons else "public, untested",
        ))
    ranked.sort(key=lambda g: (-g.risk_score, g.symbol.module_path, g.symbol.name))
    return ranked


# ── P4 (engine half): report build + markdown render ──────────────────────

_CAVEATS: tuple[str, ...] = (
    "Cross-reference is by NAME (AST token index, comments/strings excluded), "
    "not coverage.py: a symbol referenced by name in a test — even without an "
    "assertion — reads as 'tested', and a same-named symbol elsewhere shares "
    "the signal.",
    "Risk scores are mechanical heuristics (tunable weights), not measured "
    "severities — they order the list, they are not magnitudes.",
    "A starting test over existing code is a CHARACTERIZATION test: it locks in "
    "CURRENT behavior as a regression net, NOT a correctness proof. It can lock "
    "in a current bug. Review each before trusting it.",
)


def build_strengthen_report(
    repo_root: Path,
    *,
    top_n: int = _DEFAULT_TOP_N,
    skip_fan_in: bool = False,
) -> dict:
    """Enumerate → cross-reference → rank; return an advisory report dict.

    ``mode`` is ``"a"`` (test tree present → cross-reference) or ``"b"`` (no
    test infrastructure → every public symbol reported untested) or
    ``"non_python"`` (no Python surface found). Always names how many gaps were
    bounded out of the top-N view — silent truncation reads as "you're covered".
    """
    top_n = max(0, top_n)  # a negative top-n would silently slice off the LAST gaps
    symbols, unparseable = enumerate_public_surface(repo_root)
    caveats = list(_CAVEATS)

    if not symbols and not unparseable:
        return {
            "repo": str(repo_root),
            "mode": "non_python",
            "total_public": 0,
            "total_untested": 0,
            "top_n": top_n,
            "bounded": 0,
            "scope_note": "no Python surface found -- mechanical enumeration "
                          "supports Python only (for now)",
            "gaps": [],
            "unparseable": [],
            "caveats": caveats,
        }

    test_commands = detect_tests(repo_root)
    if test_commands:
        mode = "a"
        test_names, prod_counts, prod_by_module = _build_reference_index(repo_root)
        tested = _identify_tested_symbols(symbols, repo_root, test_names=test_names)
        untested = [s for s in symbols if _key(s) not in tested]
    else:
        mode = "b"
        if skip_fan_in:
            prod_counts, prod_by_module = Counter(), {}
        else:
            _, prod_counts, prod_by_module = _build_reference_index(repo_root)
        untested = list(symbols)
        caveats = [
            "No test infrastructure detected (mode-b): every public symbol is "
            "reported as untested. Establish a test tree, then re-run.",
            *caveats,
        ]

    ranked = _rank_gaps(
        untested, prod_counts, skip_fan_in=skip_fan_in, self_ref_by_module=prod_by_module
    )
    total = len(symbols)
    n_untested = len(untested)
    shown = ranked[:top_n]
    bounded = max(0, n_untested - len(shown))
    scope_note = (
        f"enumerated {total} public symbols, {n_untested} untested; "
        f"showing top {len(shown)}, bounded {bounded}"
    )
    return {
        "repo": str(repo_root),
        "mode": mode,
        "total_public": total,
        "total_untested": n_untested,
        "top_n": top_n,
        "bounded": bounded,
        "scope_note": scope_note,
        "gaps": [
            {
                "module_path": g.symbol.module_path,
                "name": g.symbol.name,
                "kind": g.symbol.kind,
                "lineno": g.symbol.lineno,
                "is_exported": g.symbol.is_exported,
                "risk_score": g.risk_score,
                "reason": g.reason,
            }
            for g in shown
        ],
        "unparseable": unparseable,
        "caveats": caveats,
    }


def render_strengthen_md(report: dict) -> str:
    """Render a :func:`build_strengthen_report` dict as operator-facing markdown."""
    lines: list[str] = ["# Strengthen report", ""]
    lines.append(f"- Repo: `{report['repo']}`")
    lines.append(f"- Mode: `{report['mode']}`")
    lines.append(f"- {report['scope_note']}")
    lines.append("")

    if report["mode"] == "non_python":
        lines.append(
            "Mechanical enumeration supports Python only (for now). No Python "
            "surface was found under this repo."
        )
        lines.append("")
        return "\n".join(lines)

    gaps = report["gaps"]
    if gaps:
        lines.append("## Highest-risk untested public symbols")
        lines.append("")
        lines.append("| Rank | Symbol | Kind | Location | Score | Why |")
        lines.append("|---|---|---|---|---|---|")
        for i, g in enumerate(gaps, start=1):
            exported = " (exported)" if g["is_exported"] else ""
            location = f"{g['module_path']}:{g['lineno']}"
            lines.append(
                f"| {i} | `{g['name']}`{exported} | {g['kind']} | "
                f"`{location}` | {g['risk_score']} | {g['reason']} |"
            )
    elif report.get("total_untested", 0) == 0:
        lines.append("No untested public symbols found. ALL CLEAR.")
    else:
        lines.append(
            f"No symbols shown: {plural(report['total_untested'], 'untested public symbol')} "
            f"bounded out by `--top-n {report['top_n']}`."
        )
    lines.append("")

    if report["bounded"]:
        lines.append(
            f"> {plural(report['bounded'], 'further untested symbol')} not shown "
            f"(top-{report['top_n']} bound). Re-run with `--top-n` to widen."
        )
        lines.append("")

    if report.get("unparseable"):
        lines.append("## Unparseable files (skipped)")
        lines.append("")
        for f in report["unparseable"]:
            lines.append(f"- `{f}`")
        lines.append("")

    lines.append("## Read this honestly")
    lines.append("")
    for caveat in report["caveats"]:
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)
