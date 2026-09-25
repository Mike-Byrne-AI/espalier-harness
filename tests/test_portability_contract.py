"""Portability contract tests — lock the OS-portability guarantees
established in Pack 0 for hook command emission and active operator
documentation.

Pins the rule that hook commands emit via Claude Code's exec form
(no shell tokenization, no interpreter-path quoting required) and
that user-facing docs contain no Unix-only default workflows.
Without this contract a hook-emission refactor or doc edit could
silently break Windows users — they would see ``settings.json``
referencing paths that fail to tokenize correctly, and the
regression would not surface in the macOS/Linux CI matrix at all.
"""
from __future__ import annotations

import ast
import builtins
import inspect
import json
import re
import textwrap
from pathlib import Path

import pytest


from espalier.cli import _build_settings_json

REPO_ROOT = Path(__file__).resolve().parent.parent


def _all_hook_commands() -> list[str]:
    settings = _build_settings_json()
    commands = []
    for event_entries in settings["hooks"].values():
        for entry in event_entries:
            for hook in entry.get("hooks", []):
                commands.append(hook["command"])
    return commands


# TP-35 cleanup: the pre-TP-35 portability checks (absolute interpreter
# path, sys.executable identity, spaces-in-interpreter-path quoting) are
# obsolete now that hooks use exec form. Exec form spawns ``python``
# directly via Claude Code with each arg passed verbatim, so there is no
# interpreter path to quote and no shell tokenization to worry about.
# See ``tests/test_hook_exec_form.py`` for the new contract.


# ---------------------------------------------------------------------------
# Test 4 — active operator docs contain no Unix-only default workflows
# ---------------------------------------------------------------------------

class TestOperatorDocsPortability:
    def test_operator_docs_no_unix_only_default_workflows(self):
        active_docs = [
            REPO_ROOT / "README.md",
            REPO_ROOT / "docs" / "CHEAT-SHEET.md",
            REPO_ROOT / "docs" / "SHARP_EDGES.md",
            *sorted((REPO_ROOT / ".claude" / "agents").glob("*.md")),
            *sorted((REPO_ROOT / ".claude" / "commands").glob("*.md")),
        ]

        forbidden_tokens = ["python3 ", "/tmp/"]

        violations = []
        for doc in active_docs:
            if not doc.exists():
                continue
            text = doc.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    violations.append(
                        f"{doc.relative_to(REPO_ROOT)}: contains {token!r}"
                    )

        assert not violations, (
            "Tracked operator docs contain Unix-only default-workflow tokens:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Test 5 — managed hooks inventory matches disk
# ---------------------------------------------------------------------------

class TestManagedHooksMatchDisk:
    def test_canonical_hook_inventory_matches_disk(self):
        from espalier import surface_contract
        hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        disk_hooks = sorted(
            p.name for p in hooks_dir.glob("*.py") if not p.name.startswith("_")
        )
        canonical = sorted(surface_contract.get_canonical_hook_scripts())
        assert canonical == disk_hooks, (
            f"Canonical hook inventory does not match disk.\n"
            f"  Canonical: {canonical}\n"
            f"  Disk:      {disk_hooks}"
        )


# ---------------------------------------------------------------------------
# Test 6 — exactly 9 hooks wired
# ---------------------------------------------------------------------------

class TestNineHooksWired:
    def test_all_nine_hooks_wired(self):
        # TP-40: 9 -> 10 hooks (SubagentStop added). TP-163: 10 -> 12
        # (subagent_start + context_reinject_failure). Test name kept for
        # git-blame continuity; assertion bumped.
        commands = _all_hook_commands()
        assert len(commands) == 12, (
            f"Expected 12 hook commands in generated settings, got {len(commands)}"
        )

    def test_settings_is_valid_json(self):
        settings = _build_settings_json()
        # Round-trip must not raise
        json.loads(json.dumps(settings))


# ---------------------------------------------------------------------------
# TP-32 amendment: no non-ASCII in runtime print() output
# ---------------------------------------------------------------------------

# Directories whose .py files are runtime-output sources.
_RUNTIME_SOURCES = (
    REPO_ROOT / "espalier",
    REPO_ROOT / "tools" / "cc",
    REPO_ROOT / "scripts",
)

# Functions whose string-literal arguments are user-facing.
_USER_FACING_CALLS = {"print", "sys.stderr.write", "sys.stdout.write"}

# Result constructors whose ``detail`` string reaches the user via an indirect
# print (release_check.print_results renders r.detail; selfcheck serializes it).
# A literal handed to CheckResult(..., detail=...) is never a direct print() arg,
# so the _USER_FACING_CALLS walk alone is blind to it. Both live CheckResult
# dataclasses (scripts/release_check.py, espalier/selfcheck.py) place ``detail``
# at positional index 2 / keyword ``detail=``.
#
# This allowlist IS the coverage boundary of the indirect-print half of the net
# (see the SHARP_EDGES entry "An AST content-scanner gated on a call-name
# allowlist is blind to every user-facing sink the allowlist omits"). Other
# indirect-print idioms are DELIBERATELY not covered -- FP-prone dataflow with
# no cheap AST answer: ``argparse`` ``help=`` / ``add_parser`` strings
# (rendered on --help), and sibling result constructors (e.g. ``CanonFinding``).
# So a GREEN here means "direct prints + CheckResult.detail + the (a)-(g)
# indirect collector + leading-echo .sh are ASCII", NOT "all runtime output is
# ASCII". Add a constructor here only when a live operator-facing one appears --
# not speculatively.
#
# ⚠ RETIRED FROM THAT LIST, 2026-09-03 (DEF-677): this block used to name
# build-a-list-then-``"\n".join``-then-print as deliberately out of scope, on
# the stated rationale "FP-prone dataflow with no cheap AST answer". The
# rationale had never been tested, and measurement falsified it -- rule (g)
# below resolves the shape in ~15 lines of AST and yields 26 offending strings
# across five functions with ZERO false positives in the red column. A
# scope-out is a claim like any other (STANDING_PRINCIPLES §11); this one was
# load-bearing for six rounds of widening and cost 18 crash-capable characters
# on Windows redirected stdout. Do not re-add an idiom to this list without a
# measurement showing the FP rate that justifies it.
_USER_FACING_CONSTRUCTORS = {"CheckResult"}


def _dotted_call_name(func: ast.expr) -> str | None:
    """FULL dotted name for a Call.func (``print`` / ``sys.stderr.write``), else None.

    DISTINCT from the ``_call_name`` helpers in ``espalier/strengthen.py`` and
    ``espalier/scanners/test_loosening.py`` -- those take an ``ast.Call`` and
    return the bare last attribute (``write``); this takes the ``.func`` node and
    returns the FULL dotted path (``sys.stderr.write``), which the allowlist
    below matches against. Do NOT consolidate them into one helper: a merge to
    the last-attr-only form would make ``sys.stderr.write`` never match and
    silently blind the stderr/stdout arm of this net (born-blind, un-witnessed
    because the live tree has no offenders there).
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        cur: ast.expr = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
    return None


def _collect_print_string_args(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, string_literal) for every user-facing string arg.

    Covers (1) direct literals passed to _USER_FACING_CALLS and (2) the
    ``detail`` argument of a _USER_FACING_CONSTRUCTORS call (indirectly
    printed). f-string (JoinedStr) constant pieces count for both.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out: list[tuple[int, str]] = []

    def _emit(node: ast.expr) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    out.append((piece.lineno, piece.value))
        elif isinstance(node, ast.Call) and _dotted_call_name(node.func) in (
            "json.dumps", "dumps",
        ):
            # `print(json.dumps({...}))` is a user-facing PROSE sink this scan
            # was blind to: the arg is a Call, not a literal, so a non-ASCII
            # sentence inside the dict escaped entirely. It does not crash --
            # `ensure_ascii=True` is the default -- it renders the six literal
            # characters `—` in the reader's terminal, which is worse than
            # a mojibake because it looks like a bug in the tool. Found when a
            # stand-down message added exactly this sink; walk the dict's
            # string VALUES (keys are ASCII identifiers by construction).
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    for value in arg.values:
                        _emit(value)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_call_name(node.func)
        if name in _USER_FACING_CALLS:
            for arg in node.args:
                _emit(arg)
        elif name in _USER_FACING_CONSTRUCTORS:
            # ``detail`` only: positional index 2 or keyword detail=.
            # name/status/passed are ASCII enums, deliberately not collected.
            if len(node.args) >= 3:
                _emit(node.args[2])
            for kw in node.keywords:
                if kw.arg == "detail":
                    _emit(kw.value)
    return out


def _register_joined_accumulators(expr: ast.expr, acc: set[str]) -> None:
    """Add to ``acc`` every local name that ``expr`` joins into a string.

    Walks the WHOLE expression rather than matching its top node, because the
    top node is almost never the ``join``. Measured shape population in this
    repo (DEF-677 adversarial pass, 2026-09-03) -- the first cut of this rule
    matched only shape 1 and reached 3 of 13:

        1  return sep.join(lines)                      <- the exemplar
        2  return sep.join(lines) + "\\n"               <- 20+ live sites, the
                                                          house renderer idiom
        3  return sep.join(lines).strip() + "\\n"
        4  out = sep.join(lines); return out
        5  print(sep.join(lines))                      <- the SHARP_EDGES
                                                          instance, named by
                                                          hand and still open
        6  out = sep.join(lines); print(out)
        7  return sep.join(sorted(lines))
        8  return sep.join(lines[:20])
        9  return sep.join(x for x in lines)
       10  return sep.join(x for y in lines for x in y)

    ``ast.walk`` closes 1/2/3/5/7/8/9/10 by itself (a ``BinOp``, an
    ``Attribute`` call, or a print argument all contain the ``join`` as a
    descendant). Shapes 4 and 6 need the assignment hop the caller adds.

    ⚠ This matches ``attr == "join"``, so ``os.path.join(a, b)`` registers ``a``
    too. That is deliberate over-collection: a path fragment is a string the
    operator may well see, the false-positive rate measured ZERO across the
    tree, and the alternative -- a receiver allowlist -- is exactly the
    hand-kept register this module's docstring warns against twice.
    """
    for sub in ast.walk(expr):
        if not (isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "join"):
            continue
        for arg in sub.args:
            if isinstance(arg, ast.Name):                       # join(acc)
                acc.add(arg.id)
            elif isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name):
                acc.add(arg.value.id)                           # join(acc[:20])
            elif isinstance(arg, ast.Call):                     # join(sorted(acc))
                for inner in arg.args:
                    if isinstance(inner, ast.Name):
                        acc.add(inner.id)
            elif isinstance(arg, (ast.GeneratorExp, ast.ListComp)) and arg.generators:
                it = arg.generators[0].iter                     # join(f(x) for x in acc)
                if isinstance(it, ast.Name):
                    acc.add(it.id)
                elif isinstance(it, ast.Call):
                    for inner in it.args:
                        if isinstance(inner, ast.Name):
                            acc.add(inner.id)


def _collect_indirect_operator_strings(path: Path) -> list[tuple[int, str]]:
    """Operator-facing strings that never appear as a literal argument to a
    user-facing call, so ``_collect_print_string_args`` is structurally blind
    to them.

    SEVEN widenings, every one DERIVED from the module's own shape rather than
    from a hand-kept list of receiver names. A hand-kept list is what failed
    here before: the pack that widened this net named
    ``failures``/``warnings``/``info``/``next_steps``, and measurement showed
    ``info`` receives ZERO appends while ``issues`` (2) and ``findings`` (2) --
    both live -- were unnamed. ``issues`` is ``_check_python_resolver``'s
    accumulator, so the guard would have shipped green and only failed to fire
    once that function's own new strings landed in it.

    (a) ``.append`` / ``.extend`` onto a local name the enclosing function
        RETURNS -- the accumulator shape, derived from the return statement.
    (b) string VALUES of a dict literal a function RETURNS -- the report-payload
        shape. This is where the only escapes that actually fire live
        (``doctor.py::_source_checkout_report``); they are not ``.append``
        calls, so no receiver-keyed walk of any width reaches them.
    (c) a module-level constant passed BY NAME to a user-facing call --
        ``print(INSTALL_CI_INSTRUCTIONS)`` passes an ``ast.Name``.
    (d) a module-level tuple/list of strings ITERATED by a loop whose body makes
        a user-facing call -- ``FINISH_UP_STEPS``.
    (e) a module-level constant the module's OWN declared operator-facing
        registry names (``_OPERATOR_FACING_TEMPLATES``).
    (f) the RETURN VALUE of a helper whose result is printed, resolved within
        the defining file (``print(render(...))`` hands the call an ``ast.Call``
        that no rule above unwraps). Cross-module resolution is NOT covered:
        ``surface_impact.render_report`` is printed from ``cli.py``, two modules
        away, so (f) never reached it -- (g) is what does.
    (g) an accumulator returned through ``sep.join(...)`` -- both the plain
        ``sep.join(acc)`` form and the ``sep.join(f(x) for x in acc)``
        comprehension form. This is the dominant idiom for building an operator
        report BODY, and it defeated (a) structurally: (a) registers an
        accumulator only from a ``Return`` whose value is a bare ``ast.Name``,
        and a ``join`` call is an ``ast.Call``, so the function collected ZERO
        strings and read as clean rather than as unscanned.

    ⚠ **(e) exists because (a)-(d) reached ZERO strings in the two largest
    operator-message modules in the deployed tree** (``DEF-639``, measured
    2026-09-03): ``_denial_reasons.py`` (377 lines) and ``_speedbump.py`` (925)
    both returned an EMPTY population, so all four predicates below ran over
    nothing and reported green. ``_denial_reasons``' templates are consumed by
    ``write_guard`` ACROSS the import boundary, and not even as call arguments
    but as elements of a rule-registry tuple, so no receiver-keyed or
    sink-keyed walk of any width reaches them from the defining module.

    The rule is DERIVED: the module already publishes
    ``_OPERATOR_FACING_TEMPLATES``, its own list of which constants are operator
    text, already under contract in ``tests/test_denial_reasons.py``. Keying on
    that beats a list in THIS file, which would be exactly the hand-kept
    register this docstring warns about two paragraphs up.

    Calibrated before adoption, because a wider rule was tried first and
    rejected on measurement: collecting every module-level ``UPPER = <string>``
    added 1,820 strings and would have redded on CORRECT code -- 19 non-ASCII
    hits were em-dashes in generated MARKDOWN templates (documents, not terminal
    output) and the interpreter-token hits were the literal patterns
    ``scanners/subprocess_contracts.py`` searches FOR. The registry rule adds 17
    strings from one module with none of those, and found exactly what
    ``DEF-639`` predicted: the versioned interpreter token in
    ``_denial_reasons.py::HARNESS_ENV_PREFIX_INLINE`` plus nine non-ASCII
    escapes in live deny text. (Cited by SYMBOL, not line: the line moved
    when that constant was edited two commits later, which is exactly the
    rot `test_tree_wide_bare_line_anchors_resolve` ratchets against.)

    ⚠ **Known residue, MEASURED rather than estimated.** ``DEF-639`` is not
    closed, and the hole is wider than that row or the first pass through this
    docstring claimed. Eight modules under ``_RUNTIME_SOURCES`` still collect
    ZERO strings while holding a module-level string constant of 120+ chars
    (2026-09-03):

        tools/cc/hooks/_bash_patterns.py    2828 loc
        tools/cc/hooks/_reinject.py          946 loc   <- CONFIRMED operator text
        tools/cc/hooks/_speedbump.py         925 loc
        espalier/surface_impact.py           736 loc
        espalier/harness_config.py           631 loc
        espalier/claim_extractor.py          405 loc
        espalier/settings_profiles.py        276 loc
        espalier/provenance_census.py        266 loc

    ``_reinject._RULE_A`` is the confirmed one: it is injected as
    ``hookSpecificOutput.additionalContext`` and read by the operator on every
    failed Edit, so it is as operator-facing as anything in
    ``_denial_reasons.py``. The others are unclassified -- several
    (``_bash_patterns``) are regex/pattern constants that would be false
    positives, which is exactly why this is a MEASURED list of candidates and
    not a widening.

    ⚠ **The prescription that used to close this docstring was WRONG on both
    clauses, and is retired (2026-09-03).** It said: write a constructor-shape
    rule for the ``CP_* = Speedbump(reason=...)`` form, and that such a rule
    MUST exclude ``re.compile``. Measured: there is no ``Speedbump(reason=...)``
    -- the real symbol is ``SpeedBump(body=...)``, wrong class casing AND wrong
    kwarg, so a rule keyed on that spec collects ZERO strings and reads as
    coverage (the born-blind shape ``STANDING_PRINCIPLES`` §18/§19 exists for).
    And the ``re.compile`` exclusion catches 44 of ``_bash_patterns``' 46
    constants while missing exactly the two that matter (``_CMD_POS_WRAPPER``,
    ``_PS_CMD_POS_EXEC_QUOTE`` are bare r-strings compiled elsewhere). The
    derived replacement, if this is ever taken up: the CONSTRUCTOR KWARG is the
    classification signal -- ``Profile(description=)`` is prose (max 406 chars)
    while ``Profile(allow=)`` is permission patterns (max 27) on the SAME
    constant, so a kwarg-keyed rule needs no ``re.compile`` exclusion at all,
    because a regex never lives in a ``body=`` / ``description=``. A
    prescription inherited from a handoff is a CLAIM: unparse the real AST
    before writing the rule it asks for.

    ⚠ **Note which CONTRACT consumes this collector.** It feeds
    ``_all_operator_strings``, and until 2026-09-03 the ONLY consumer of that
    union was ``TestOperatorStringsArePortable`` (the interpreter-token
    contract). ``TestNoNonAsciiInRuntimePrints`` called
    ``_collect_print_string_args`` directly, so every widening in this function
    -- six rounds of them -- reached the token contract and NONE of them reached
    the ASCII contract. Two nets in one file that did not share a collector.
    ``DEF-677`` was that gap: 26 offending strings, 18 crash-capable characters,
    all under a green ASCII contract. Both tests now consume the union. If you
    add a rule here, it lands in BOTH contracts -- check the blast radius
    against both before adopting.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []
    out: list[tuple[int, str]] = []

    def _strings_of(node: ast.expr) -> list[tuple[int, str]]:
        """Every string literal reachable from ``node``, through containers.

        Recursion is the point. The two escapes that actually FIRE in this repo
        live inside a returned dict, but not at its top level: one is the else
        arm of an ``IfExp`` under ``primary_reason``, the other is an element of
        a ``List`` under ``info``. A one-level dict-value walk collects neither,
        which is exactly how a widening can look done and reach nothing.
        """
        found: list[tuple[int, str]] = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    found.append((piece.lineno, piece.value))
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.elts:
                found.extend(_strings_of(elt))
        elif isinstance(node, ast.Dict):
            for v in node.values:
                if v is not None:
                    found.extend(_strings_of(v))
        elif isinstance(node, ast.IfExp):
            found.extend(_strings_of(node.body))
            found.extend(_strings_of(node.orelse))
        elif isinstance(node, ast.BinOp):
            found.extend(_strings_of(node.left))
            found.extend(_strings_of(node.right))
        return found

    # ---- module-level constants, and which of them are operator-facing ----
    const_str: dict[str, ast.expr] = {}
    const_seq: dict[str, ast.expr] = {}
    for node in tree.body:
        # BOTH assignment forms. Handling only `ast.Assign` made rule (d)'s own
        # named exemplar invisible to rule (d): `FINISH_UP_STEPS` is declared
        # `X: tuple[str, ...] = (...)`, an AnnAssign, and this house style
        # accounts for 151 module-level constants. A live POSIX env-prefix
        # shipped behind that gap.
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            tgt, val = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            tgt, val = node.target, node.value
        else:
            continue
        if not isinstance(tgt, ast.Name) or not tgt.id.isupper():
            continue
        if isinstance(val, (ast.Constant, ast.JoinedStr)):
            const_str[tgt.id] = val
        elif isinstance(val, (ast.Tuple, ast.List)):
            const_seq[tgt.id] = val

    printed_by_name: set[str] = set()
    iterated_and_printed: set[str] = set()
    for node in ast.walk(tree):
        # (c) a Name handed straight to a user-facing call
        if isinstance(node, ast.Call) and _dotted_call_name(node.func) in _USER_FACING_CALLS:
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    printed_by_name.add(arg.id)
        # (d) a constant iterated by a loop whose body prints
        if isinstance(node, ast.For):
            it = node.iter
            name = (it.id if isinstance(it, ast.Name)
                    else it.attr if isinstance(it, ast.Attribute) else None)
            if name and any(
                isinstance(b, ast.Call)
                and _dotted_call_name(b.func) in _USER_FACING_CALLS
                for b in ast.walk(node)
            ):
                iterated_and_printed.add(name)

    for name in printed_by_name & set(const_str):
        out.extend(_strings_of(const_str[name]))
    for name in (printed_by_name | iterated_and_printed) & set(const_seq):
        for elt in const_seq[name].elts:
            out.extend(_strings_of(elt))
    # A constant iterated-and-printed HERE may be DEFINED in another module
    # (fuse.py iterates fusion_manifest.FINISH_UP_STEPS), so also collect any
    # module-level sequence constant this file defines that some file prints.
    # Cross-file resolution is out of scope for one AST pass; the caller unions
    # per-file results, so defining-file collection is what closes that gap.
    for name, seq in const_seq.items():
        if name in _CROSS_MODULE_OPERATOR_SEQUENCES:
            for elt in seq.elts:
                out.extend(_strings_of(elt))

    # ---- (f) helpers whose RETURN VALUE is printed ----
    # `print(render(...))` hands the call an `ast.Call`, which no rule above
    # unwraps, so a helper that returns an f-string is outside the net. That is
    # the shape the dialect-aware maintenance renderer itself uses -- which is
    # how its own exemption came to suppress nothing while reading as coverage.
    printed_helpers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted_call_name(node.func) in _USER_FACING_CALLS:
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Call):
                        nm = _dotted_call_name(sub.func)
                        if nm:
                            printed_helpers.add(nm.split(".")[-1])
    if printed_helpers:
        for fn in ast.walk(tree):
            if (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.name in printed_helpers):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Return) and node.value is not None:
                        out.extend(_strings_of(node.value))

    # ---- function-level accumulators and returned payloads ----
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        returned_names: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
                returned_names.add(node.value.id)
            # (g) an accumulator returned through ``sep.join(...)`` -- the
            # dominant idiom for building an operator report body, and the
            # shape rule (a) below was structurally blind to. (a) keys on
            # ``returned_names``, which only ever registered a ``Return`` whose
            # value is a bare ``Name``; ``return "\n".join(lines)`` returns an
            # ``ast.Call``, so the accumulator was never registered, every
            # ``.append`` into it was skipped, and the whole function collected
            # ZERO strings -- reading as clean rather than as unscanned.
            #
            # MEASURED before widening (DEF-677, 2026-09-03), because the
            # earlier scope-out justified itself as "FP-prone dataflow with no
            # cheap AST answer" and that rationale had never been tested.
            # ``sister_site_probe._format_report_text`` is printed at :1171 --
            # the Core-Rule-12 class oracle CLAUDE.md tells you to run -- and
            # ``surface_impact.render_report`` is the ``/implement-pack`` step
            # 0-D pre-flight every adopter runs.
            #
            # ⚠ THE FIRST CUT OF THIS RULE ANCHORED ON ``Return`` -> bare
            # ``Call`` AND COVERED 3 OF 13 LIVE SHAPES. The adversarial pass
            # enumerated them: it missed ``sep.join(x) + "\n"`` -- which is THIS
            # repo's dominant renderer idiom at 20+ sites (``render_status_report``,
            # ``render_live_surface``, ``_memory_toc``, ...) -- and it missed
            # ``print(sep.join(parts))``, the very instance docs/SHARP_EDGES.md
            # named by hand. Twelve live non-ASCII strings stayed invisible,
            # including an em-dash in ``session_start.py::_memory_toc`` that
            # prints on EVERY session start. A rule that catches the exemplar
            # you wrote it against and misses the house idiom reads as coverage:
            # see ``_register_joined_accumulators`` for the shape matrix.
            if isinstance(node, ast.Return) and node.value is not None:
                _register_joined_accumulators(node.value, returned_names)
            # ...and the same shape handed straight to a user-facing call:
            # ``print("\n".join(parts))`` never returns at all. This is the
            # instance docs/SHARP_EDGES.md named by hand; anchoring only on
            # ``Return`` would have left it open while the doc claimed it closed.
            if (isinstance(node, ast.Call)
                    and _dotted_call_name(node.func) in _USER_FACING_CALLS):
                for call_arg in node.args:
                    _register_joined_accumulators(call_arg, returned_names)
            # (b) a dict literal returned directly
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for v in node.value.values:
                    if v is None:
                        continue
                    out.extend(_strings_of(v))
                    # A dict VALUE that is a bare Name is an accumulator built
                    # by `.append()` elsewhere in the body -- opaque to
                    # `_strings_of`, which only walks literal containers. This
                    # is the shape of `doctor.py::run_doctor_check`, the single
                    # largest report-builder in the engine: it returns a dict
                    # literal whose `warnings` / `failures` / `info` /
                    # `next_steps` values are all bare Names, so BOTH rules
                    # missed it -- (b) because the value is not a literal, and
                    # (a) because the function does not `return <bare name>`.
                    # The result was a false green over doctor's whole
                    # pass-status branch, proven by a real `\u2014` reaching the
                    # operator on any healthy repo.
                    if isinstance(v, ast.Name):
                        returned_names.add(v.id)
        # Shapes 4 and 6 -- `out = sep.join(lines)` then `return out` / `print(out)`.
        # The join is one hop away from the sink, so neither the Return walk nor
        # the print-arg walk above sees `lines`; `out` is what they register.
        # Map each assigned name back to the accumulators its value joined, then
        # expand. One hop only: chains (`a = join(x); b = a; return b`) are not
        # followed, and that boundary is stated here rather than left implied.
        joined_via: dict[str, set[str]] = {}
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                sources: set[str] = set()
                _register_joined_accumulators(node.value, sources)
                if sources:
                    joined_via.setdefault(node.targets[0].id, set()).update(sources)
        if joined_via:
            # A bare name handed to print() is a sink too, not just a return.
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and _dotted_call_name(node.func) in _USER_FACING_CALLS):
                    for call_arg in node.args:
                        if isinstance(call_arg, ast.Name):
                            returned_names.add(call_arg.id)
            for name in list(returned_names):
                returned_names |= joined_via.get(name, set())
        if not returned_names:
            continue
        for node in ast.walk(fn):  # (a)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("append", "extend")
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in returned_names):
                for arg in node.args:
                    out.extend(_strings_of(arg))
                    if isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            out.extend(_strings_of(elt))

    # (e) constants the module's OWN registry declares operator-facing.
    # Keyed on the module's declaration rather than a list in this file, so it
    # cannot go stale the way the hand-kept register in (a)'s docstring did.
    declared: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = ([node.target] if isinstance(node, ast.AnnAssign)
                       else node.targets)
            if any(getattr(t, "id", None) == "_OPERATOR_FACING_TEMPLATES"
                   for t in targets):
                declared = {
                    e.value for e in getattr(node.value, "elts", [])
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
    if declared:
        # ⚠ The registry marks the MODULE, not the members. Collecting only the
        # names IN `_OPERATOR_FACING_TEMPLATES` covered 9 of 27 string
        # constants, because that tuple was never authored to mean
        # "operator-facing" -- it is the parametrize source for the Don't/Do
        # pairing contract in tests/test_denial_reasons.py, and the module says
        # so at its `CATASTROPHIC_RM` definition: "intentionally NOT in
        # _OPERATOR_FACING_TEMPLATES -- no Don't/Do habit pair". Keying on
        # membership inverted the incentive: a hard-stop message deliberately
        # without a pair became permanently exempt from portability checking.
        # Declaring the registry is the signal that this module holds operator
        # text; every module-level string constant in it is then in scope.
        # Measured: 17 strings -> 66, +2 real non-ASCII escapes in
        # GATE_CODE_REVIEW_FLAG_WRITE_FAILED_SUFFIX (outside the registry), and
        # zero new false positives on any of the four predicates.
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = ([node.target] if isinstance(node, ast.AnnAssign)
                       else node.targets)
            name = next((getattr(t, "id", None) for t in targets), None)
            if name and name.replace("_", "").isupper():
                out.extend(_strings_of(node.value))

    return out


#: Sequence constants DEFINED in one runtime module and printed from another.
#: Cross-module resolution is beyond one AST pass, so the defining file is
#: named here. Keep this SHORT -- it is the one hand-kept element in an
#: otherwise derived collector, and every entry is a coverage claim.
_CROSS_MODULE_OPERATOR_SEQUENCES = frozenset({"FINISH_UP_STEPS"})


def _enclosing_def(path: Path, lineno: int) -> str:
    """Name of the innermost def/class containing ``lineno``, else ``<module>``.

    Exclusions below are keyed on this rather than on a line number, because a
    line-numbered exclusion silently starts covering a different string the
    first time anything above it grows -- the citation-rot shape this repo has
    closed repeatedly.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return "<module>"
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.lineno <= lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best[0]:
                    best = (node.lineno, node.name)
    return best[1] if best else "<module>"


def _all_operator_strings(path: Path) -> list[tuple[int, str]]:
    """Direct + indirect, deduped. The union IS the net."""
    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, str]] = []
    for item in (_collect_print_string_args(path)
                 + _collect_indirect_operator_strings(path)):
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


#: Deliberate, ARGUED exclusions -- (relative-path-suffix, enclosing def).
#: Each is a coverage claim; adding one is a decision, not a convenience.
#:
#: ⚠ RULE (g) WIDENED THE POPULATION THIS LIST GUARDS (DEF-677, 2026-09-03).
#: It adds ~349 strings tree-wide, and some come from functions that are not
#: operator prose at all but string RECONSTRUCTORS -- notably
#: `espalier/scanners/subprocess_contracts.py::_argv_from_list`, an argv
#: rebuilder whose vocabulary (`"${"`, `"}"`, `"<dynamic>"`) now flows into the
#: interpreter-token contract. Measured at adoption: ZERO of the 349 trip any
#: predicate today, so NO exemption is added here -- this list's own rule is
#: "argued, and only when a live case appears," and a pre-emptive row would be
#: the speculative entry it forbids. But the failure is one edit away: a future
#: `parts.append("python3")` in that data function reds the token contract with
#: a remedy message ("interpolate the resolved interpreter") that is meaningless
#: for a scanner's normalization vocabulary. If that day comes, exempt it here
#: rather than corrupting the scanner -- and note exemptions key on the
#: INNERMOST enclosing def, so extracting a helper out of an exempt function
#: silently drops its exemption.
_INTERPRETER_TOKEN_EXEMPT = frozenset({
    # The token IS the message: this warning names the `python3` shim the
    # operator should create. Mangling it would destroy the remedy.
    ("hooks/session_start.py", "_warn_if_hook_interpreter_unresolved"),
    # A SELF-HOST MAINTAINER verb that happens to live inside the scanned tree.
    # Dev/bench tooling uses the versioned spelling by the opposite convention
    # to operator docs; excluding by DIRECTORY (`scripts/`) does not reach it.
    ("espalier/cli.py", "cmd_refresh_self_host_pin"),
})

_ENV_PREFIX_EXEMPT = frozenset({
    # The ONE dialect-aware renderer for PRINTED output. It is allowed --
    # required -- to spell the POSIX form, because it also spells the PowerShell,
    # cmd.exe and Git Bash forms and picks by host. Every other printed site
    # routes through it.
    ("espalier/cli.py", "_maintenance_mode_invocation"),
    # The adopter's generated CLAUDE.md. A printed line is rendered on the
    # operator's machine at that moment, so host-keying it is correct; this file
    # is COMMITTED and read by collaborators on other operating systems, so
    # host-keying it is wrong on the merits (and would make a checked-in
    # snapshot fail the Windows CI leg). It therefore lists every dialect
    # unconditionally -- the remedy, not the defect.
    ("espalier/cli.py", "_build_claude_md"),
})


class TestOperatorStringsArePortable:
    """The operator-string net, widened past ``print()`` literals.

    FOUR predicates, asserted SEPARATELY so each reds on its own. A single
    combined assertion cannot tell you which property broke, and a fix for one
    can mask a regression in another.

    WARNING: ``scripts/`` is excluded from the interpreter-token and env-prefix
    assertions by DIRECTORY. It is self-host developer tooling governed by the
    opposite convention (dev tooling spells the versioned interpreter; operator
    docs stay bare), and several of its assignment-shaped strings are prose,
    not commands.
    """

    def _hits(self, pattern, *, skip_scripts: bool, exempt=frozenset()):
        found = []
        for src in _RUNTIME_SOURCES:
            if not src.exists():
                continue
            for path in src.rglob("*.py"):
                # Exclude by DIRECTORY, not by a substring of the filename.
                # `"test" in path.name` dropped two live shipped modules:
                # `espalier/scanners/test_loosening.py` (a /scan sub-mode, 11
                # operator strings) and `scripts/sync_selfcheck_tests.py` (9).
                # A `startswith("test_")` rule would not have helped -- the
                # scanner IS named test_loosening.py. Real test files inside
                # these roots live under a `*tests/` directory
                # (`espalier/_vendor/selfcheck_tests/`), and the repo's own
                # suite is in `tests/`, which is not a runtime source at all.
                if any(part.endswith("tests") for part in path.parts[:-1]):
                    continue
                rel = path.as_posix()
                if skip_scripts and "/scripts/" in rel:
                    continue
                for lineno, s in _all_operator_strings(path):
                    if not pattern.search(s):
                        continue
                    fn = _enclosing_def(path, lineno)
                    if any(rel.endswith(suffix) and fn == name
                           for suffix, name in exempt):
                        continue
                    found.append(f"{rel}:{lineno}: {s[:90]!r}")
        return found

    def test_collector_reaches_the_largest_report_builder(self):
        """The net must ENGAGE its biggest target, not merely be green.

        `doctor.py::run_doctor_check` returns a dict literal whose `warnings` /
        `failures` / `info` / `next_steps` values are bare `ast.Name`s pointing
        at accumulators built by `.append()` through the body. Both original
        rules missed it -- the dict-value rule because a Name is not a literal
        container, the accumulator rule because the function does not
        `return <bare name>` -- so the whole of doctor's pass-status branch sat
        outside the net while every assertion above went green. That is a false
        green over the engine's single largest report-builder, and it shipped a
        real escape: a healthy repo's report carried a literal `\u2014`.

        A count floor here would be vacuous; assert the SITE.
        """
        doctor = REPO_ROOT / "espalier" / "doctor.py"
        collected = _all_operator_strings(doctor)
        tree = ast.parse(doctor.read_text(encoding="utf-8"))
        span = next(
            (n.lineno, n.end_lineno) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "run_doctor_check"
        )
        inside = [s for ln, s in collected if span[0] <= ln <= (span[1] or span[0])]
        assert inside, (
            "the operator-string net collects NOTHING from run_doctor_check -- "
            "the dict-value-is-a-Name rule has regressed and doctor's whole "
            "pass-status branch is unscanned again."
        )
        assert any("coherent" in s for s in inside), (
            "the net reaches run_doctor_check but not its next_steps "
            f"accumulator; collected {len(inside)} strings but none of the "
            "known pass-status guidance."
        )

    def test_collector_reaches_a_joined_accumulator(self):
        """Rule (g) must ENGAGE, not merely leave the suite green (§19).

        Mutation-proven at adoption: with rule (g) neutered, all nine tests in
        this class and ``TestNoNonAsciiInRuntimePrints`` stayed GREEN. Both
        halves of ``DEF-677`` were deletable by a careless refactor with no
        consequence -- the exact born-weak shape the sibling tests above were
        written to prevent for rules (b) and (e), and the shape a future session
        would reproduce by reading the ``_USER_FACING_CONSTRUCTORS`` comment's
        FP warning and deciding rule (g) is the FP source.

        Assert the SITE, not a count: a floor would be vacuous.
        """
        ssp = REPO_ROOT / "tools" / "cc" / "sister_site_probe.py"
        collected = _all_operator_strings(ssp)
        tree = ast.parse(ssp.read_text(encoding="utf-8"))
        span = next(
            (n.lineno, n.end_lineno) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_format_report_text"
        )
        inside = [s for ln, s in collected if span[0] <= ln <= (span[1] or span[0])]
        assert any("re-implements" in s for s in inside), (
            "rule (g) no longer registers the `return sep.join(out)` accumulator; "
            "sister_site_probe._format_report_text -- printed at :1171, the "
            "Core-Rule-12 class oracle -- is unscanned again (DEF-677)."
        )

    def test_ascii_contract_consumes_the_union_net(self):
        """The union swap must ENGAGE (§19), and this test must not go vacuous.

        ``TestNoNonAsciiInRuntimePrints`` read green for its whole life over 26
        offending strings because it called ``_collect_print_string_args``
        directly while every widening fed ``_all_operator_strings``. Reverting
        that one call site is a silent, green-preserving regression, so pin it
        two ways: the collectors must still DIVERGE (else the assertion below
        proves nothing), and the ASCII test must consume the wider one.
        """
        ssp = REPO_ROOT / "tools" / "cc" / "sister_site_probe.py"
        indirect = {s for _, s in _collect_indirect_operator_strings(ssp)}
        direct = {s for _, s in _collect_print_string_args(ssp)}
        assert indirect - direct, (
            "the direct and indirect collectors no longer diverge on "
            "sister_site_probe.py, so this test can no longer detect a revert "
            "of the union swap -- it has gone vacuous, fix the fixture."
        )
        # Pin the CALL, parsed from the AST -- never the source TEXT. A text
        # match here was born weak and mutation-proved so at adoption: the
        # explanatory comment above that loop names `_all_operator_strings`,
        # so `"_all_operator_strings" in getsource(...)` stayed TRUE with the
        # call reverted to the direct collector, and the mutation went green.
        # A guard defeated by the comment that explains it is the exact shape
        # this test exists to prevent (STANDING_PRINCIPLES §19).
        src = inspect.getsource(
            TestNoNonAsciiInRuntimePrints.test_no_non_ascii_in_runtime_prints
        )
        called = {
            n.func.id for n in ast.walk(ast.parse(textwrap.dedent(src)))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_all_operator_strings" in called, (
            "the ASCII contract stopped CALLING the union net (calls found: "
            f"{sorted(called)}); every rule (a)-(g) widening is again invisible "
            "to it (DEF-677)."
        )

    def test_collector_reaches_the_denial_reason_registry(self):
        """Rule (e) must ENGAGE ``_denial_reasons.py``, not merely leave the
        suite green (``STANDING_PRINCIPLES`` §19; sibling of
        ``test_collector_reaches_the_largest_report_builder``).

        This is the negative twin the widening needs. Before rule (e) the net
        collected ZERO strings from this module -- 377 lines of live deny text
        that every predicate below then "passed" over an empty population, which
        is the precise shape ``DEF-639`` names. Deleting rule (e) restores that
        silence and the four assertions stay green, so without this test the
        widening is removable without consequence.

        Asserts REACH and CONTENT: the count must be non-trivial, and a string
        only rule (e) can see -- a registry-declared template, consumed across
        the import boundary as a tuple element rather than a call argument --
        must be in the net.
        """
        # DERIVED, not a hardcoded path: every module that declares the registry
        # is pinned, so a second adopter (the docstring above invites
        # `_speedbump.py` to become one) is covered on arrival rather than
        # silently unreached. A hardcoded path pinned exactly one module and
        # would have let the next one in unmeasured.
        declaring = sorted(
            p for p in (REPO_ROOT / "tools" / "cc" / "hooks").glob("*.py")
            if "_OPERATOR_FACING_TEMPLATES" in p.read_text(encoding="utf-8")
        )
        assert declaring, (
            "no module declares _OPERATOR_FACING_TEMPLATES; rule (e) now has no "
            "subject at all, so the widening is dead code"
        )
        for path in declaring:
            assert len(_all_operator_strings(path)) >= 10, (
                f"{path.name} declares the registry but rule (e) collects "
                f"almost nothing from it"
            )

        path = REPO_ROOT / "tools" / "cc" / "hooks" / "_denial_reasons.py"
        collected = _all_operator_strings(path)
        assert len(collected) >= 10, (
            f"rule (e) collects only {len(collected)} strings from the largest "
            f"deny-template module; it reached ZERO before the widening, so a "
            f"small number here means the registry walk has regressed"
        )
        joined = " ".join(s for _, s in collected)
        assert "kill-switch" in joined, (
            "KILL_SWITCH_DETECTED is declared in _OPERATOR_FACING_TEMPLATES and "
            "consumed by write_guard across the import boundary; if it is not in "
            "the net, rule (e) is not running"
        )

    def test_no_non_ascii(self):
        """Widened from print-literals to the full net. ``ensure_ascii`` turns a
        non-ASCII character in a JSON payload into a literal escape sequence in
        the operator's terminal, which reads as a bug in the tool."""
        hits = self._hits(re.compile(r"[^\x00-\x7f]"), skip_scripts=False)
        assert not hits, "non-ASCII in operator-facing strings:\n  " + "\n  ".join(hits)

    def test_no_bare_interpreter_token(self):
        """Operator-facing text stays bare ``python``; the versioned spelling is
        absent on many Windows installs. WARNING: the doc-side token carries a
        TRAILING SPACE, so a trailing-position occurrence evades it -- this uses
        a word boundary instead, deliberately."""
        hits = self._hits(re.compile(r"\bpython3\b"), skip_scripts=True,
                          exempt=_INTERPRETER_TOKEN_EXEMPT)
        assert not hits, (
            "operator-facing versioned interpreter token outside the argued "
            "exemptions:\n  " + "\n  ".join(hits)
        )

    def test_no_bare_python_instruction(self):
        """The DELIBERATE TWIN of ``test_no_bare_interpreter_token``, and the
        two are opposite on purpose. Read them together or you will "fix" one
        by breaking the other.

        That test bans ``python3`` because many Windows installs ship only
        ``python``. This one bans ``python <arg>`` because a stock macOS ships
        only ``python3`` -- 3.9.6 through Sequoia, and no ``python`` at all.
        **Neither literal is portable, so the pair forces the only correct
        answer: interpolate the interpreter resolved on THIS host** --
        ``_hook_utils.python_command_hint`` on the hook side, and on the engine
        side ``cli._remedy_interpreter()`` for a command the operator will TYPE.
        ``cli._detect_python_command()`` is the answer that gets WRITTEN into
        settings.json, and on a host where nothing validated it is the broken
        name itself (a Python 2 ``python``), so a remedy spelled with it cannot
        run (``DEF-727``; the remaining write-answer remedies are ``DEF-758``).

        ``DEF-383a``, and it was observed live rather than reasoned about: the
        decision-shape advisory told a session on this maintainer's Mac to run
        ``python tools/cc/cognitive_blueprint.py ...`` while ``python`` was not
        on PATH. The harness's own remediation for its own advisory was
        unrunnable on the modal Mac.

        The predicate is the INSTRUCTION shape (``python`` followed by an
        argument), not the bare word. Measured against the live population: a
        message that NAMES the token (``Falling back to the literal name
        'python'``) and a package-system label (``analyze.detect_package_systems``)
        both correctly stay out, while both live instructions were caught.

        ⚠ DOCS are deliberately NOT in this net -- they keep bare ``python`` by
        the opposite convention (``TestOperatorDocsPortability`` above bans
        ``python3`` in them, for the Windows reason). A doc cannot interpolate,
        so ``DEF-531`` gives those pages the macOS caveat instead. Code
        interpolates; prose carries the caveat.
        """
        # ⚠ The character class used to be `[-\w]`, which missed every
        # argument starting with / . ~ ' " or $ -- driven, `python ./tools/x.py`,
        # `python /usr/local/bin/fix.py`, `python 'x.py'` and `python ~/fix.py`
        # all survived a 790-test green run. `(?=\S)` accepts ANY non-space
        # first character instead of enumerating them, so the class cannot
        # go stale again. `py -3` is folded in: it is the Windows launcher
        # form and equally unrunnable on macOS.
        # ⚠ CALIBRATED TWICE, in both directions. `[-\w]` was too NARROW:
        # `python ./x.py`, `python /usr/local/bin/f.py`, `python 'x.py'` and
        # `python ~/f.py` all survived a 790-test green run. A bare `(?=\S)`
        # was too WIDE: it fired on prose -- "a working Python 3 on this host",
        # "no Python surface found". The discriminator is the INSTRUCTION
        # shape: lowercase `python` (prose capitalises it) followed by a flag
        # or a path-ish token. `py -3` is folded in as the Windows launcher
        # form, equally unrunnable on macOS. Verified against 8 known-bad
        # commands and 9 legitimate strings before landing.
        hits = self._hits(
            re.compile(r"""(?<![\w.-])(?:python\s+(?=[-/.~'"$]|[\w-]*[/.])|py\s+-3)"""),
            skip_scripts=True)
        assert not hits, (
            "operator-facing text spells a bare `python` INSTRUCTION, which "
            "does not exist on a stock macOS. Interpolate the resolved "
            "interpreter instead -- `_hook_utils.python_command_hint()` in "
            "hooks, `_remedy_py()` in the engine (never `_detect_python_command()`, "
            "the write answer -- DEF-758). Do NOT 'fix' "
            "this by writing `python3`: its twin test bans that for Windows.\n"
            "  " + "\n  ".join(hits)
        )

    def test_no_posix_env_prefix(self):
        """A leading ``VAR=1 cmd`` env assignment is POSIX-only and a syntax
        error in PowerShell. WARNING: this matches the TRAILING form too -- the
        live sites are f-strings whose literal piece ENDS at the assignment (the
        command itself is interpolated), so a ``VAR=value <word>`` predicate
        sees none of them."""
        hits = self._hits(re.compile(r"\bESPALIER_[A-Z0-9_]+=\S*\s"),
                          skip_scripts=True, exempt=_ENV_PREFIX_EXEMPT)
        assert not hits, (
            "POSIX-only env assignment outside the single dialect-aware "
            "renderer:\n  " + "\n  ".join(hits)
        )

    def test_no_placeholder_inside_a_url(self):
        """The placeholder predicate needs TWO classes, not one, and this is the
        one that matters. An ARGUMENT placeholder (``init <repo>``) is fine --
        the operator knows their own repo. A placeholder inside a URL they are
        told to VISIT is not: it demands knowledge they do not have at that
        moment and cannot be clicked. That distinction is why a single predicate
        over ``<...>`` would either red on working messages or miss the real
        one."""
        hits = self._hits(
            re.compile(r"(?:https?://|\bgithub\.com/)\S*<[a-z][a-z0-9_-]*>"),
            skip_scripts=False,
        )
        assert not hits, (
            "un-clickable URL with an unresolved placeholder:\n  " + "\n  ".join(hits)
        )


# .sh files whose echo/printf emit strings are user-facing.
_SH_SOURCES = (
    REPO_ROOT / "scripts",
    REPO_ROOT / "bench" / "baselines",
)

# Leading shell tokens that emit their arguments to the user.
_SH_EMIT_TOKENS = ("echo", "printf")


def _collect_sh_emit_non_ascii(path: Path) -> list[tuple[int, list[str]]]:
    """Return (line_no, sorted-non-ascii-chars) for every echo/printf emit line.

    Bash has no cheap AST, so the net is deliberately narrow: a line whose FIRST
    token is echo/printf is an emit statement. Comments (#-led) and heredoc
    bodies -- the live .sh population's only non-ASCII -- are exempt by
    construction. OUT OF SCOPE (all zero-instance on the live tree, all the
    bash-has-no-AST tradeoff): non-leading echo (`... && echo`, `{ echo`,
    case-arm `-*) echo`), variable-then-echo, and backslash-continued
    echo/printf (the non-ASCII would sit on a continuation line whose leading
    token is not echo/printf). A trailing `# ...` comment on an emit line IS
    scanned (narrowness cuts the other way there).
    """
    out: list[tuple[int, list[str]]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if not stripped:
            continue
        token = stripped.split(None, 1)[0]
        if token not in _SH_EMIT_TOKENS:
            continue
        non_ascii = sorted({c for c in line if ord(c) > 127})
        if non_ascii:
            out.append((lineno, non_ascii))
    return out


class TestNoNonAsciiInRuntimePrints:
    """TP-32: runtime print/stderr strings must be 7-bit ASCII.

    PowerShell on default Windows codepages renders non-ASCII
    inconsistently; some CI log sinks also fail on non-ASCII output.

    Applies to: espalier/, tools/cc/, scripts/.
    Does NOT apply to: docs, tests, comments, docstrings.
    """

    def test_no_non_ascii_in_runtime_prints(self):
        offenders = []
        for src in _RUNTIME_SOURCES:
            if not src.exists():
                continue
            for path in src.rglob("*.py"):
                # Exclude by DIRECTORY, matching the sibling `_hits` rule 260
                # lines up. `"test" in path.name` dropped two live SHIPPED
                # modules -- `espalier/scanners/test_loosening.py` (a /scan
                # sub-mode) and `scripts/sync_selfcheck_tests.py` -- and
                # DEF-677 unified these two tests' COLLECTOR while leaving their
                # file filter divergent, which is the same "two components in
                # one file that don't agree" class DEF-677 was fixing, one line
                # away, with the correct replacement already written above.
                if any(part.endswith("tests") for part in path.parts[:-1]):
                    continue
                # THE UNION NET, not the direct-print collector. This test read
                # green for its whole life over 26 offending strings because it
                # called `_collect_print_string_args` -- direct `print()` args
                # plus `CheckResult.detail` -- while every rule (a)-(g) widening
                # in this file fed `_all_operator_strings`, which only
                # `TestOperatorStringsArePortable` consumed. Two nets in one
                # file that did not share a collector: the interpreter-token
                # contract got six rounds of widening; the ASCII contract got
                # none of them. An operator report built with
                # `lines.append(...)` and returned via `"\n".join(lines)` is
                # invisible to the direct collector no matter how wide rule (a)
                # gets, so the em-dashes in `sister_site_probe`,
                # `surface_impact`, `refresh_externals`, `audit_accuracy` and
                # `strengthen` all shipped under a green contract (DEF-677).
                # MEASURED at adoption: the swap adds exactly 26 reds, all five
                # of them known targets, zero collateral.
                for lineno, s in _all_operator_strings(path):
                    non_ascii = sorted({c for c in s if ord(c) > 127})
                    if non_ascii:
                        rel = path.relative_to(REPO_ROOT)
                        offenders.append(
                            f"  {rel}:{lineno}: {non_ascii} in "
                            f"{s[:60]!r}"
                        )
        assert not offenders, (
            "Runtime print/stderr strings contain non-ASCII characters.\n"
            "PowerShell and some CI sinks render these inconsistently.\n"
            "Replace with ASCII tokens (-- for em-dash, -> for arrow,\n"
            "WARN: for warning glyph, OK/PASS/FAIL for check marks).\n"
            + "\n".join(offenders)
        )

    def test_no_non_ascii_in_sh_emit_strings(self):
        # COVERAGE BOUNDARY: only LEADING-token echo/printf lines under
        # _SH_SOURCES (scripts/ + bench/baselines/) are scanned. Non-leading
        # echo, backslash-continued emit, and .sh files in other dirs are out of
        # scope (see _collect_sh_emit_non_ascii). A green here is NOT "all shell
        # output is ASCII" -- a new .sh elsewhere, or `... && echo "<glyph>"`,
        # passes unflagged.
        offenders = []
        for src in _SH_SOURCES:
            if not src.exists():
                continue
            for path in src.rglob("*.sh"):
                for lineno, non_ascii in _collect_sh_emit_non_ascii(path):
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"  {rel}:{lineno}: {non_ascii}")
        assert not offenders, (
            "Shell echo/printf emit strings contain non-ASCII characters.\n"
            "PowerShell and some CI sinks render these inconsistently.\n"
            "Replace with ASCII tokens (-- for em-dash, -> for arrow).\n"
            "(Scope: leading-token echo/printf under scripts/ + bench/baselines/;\n"
            "non-leading and continuation-line emit are not scanned.)\n"
            + "\n".join(offenders)
        )


class TestUserFacingContractEarnRed:
    """Earn-the-red for the TP-344 net extensions."""

    def test_checkresult_detail_literal_is_collected(self, tmp_path):
        # Non-ASCII reaches the user only via CheckResult(detail=...); the
        # direct-print walk alone returns []. Extended collector must surface it.
        # This covers the POSITIONAL index-2 path (release_check.py's form).
        src = tmp_path / "mod.py"
        src.write_text(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class CheckResult:\n"
            "    name: str\n    status: str\n    detail: str = ''\n\n"
            "def f():\n"
            "    return CheckResult('x', 'FAIL', 'cost \\u2014 high')\n",
            encoding="utf-8",
        )
        collected = [s for _, s in _collect_print_string_args(src)]
        assert any(ord(c) > 127 for s in collected for c in s), (
            "extended collector must surface a non-ASCII CheckResult.detail literal"
        )

    def test_checkresult_detail_keyword_is_collected(self, tmp_path):
        # Lock the KEYWORD detail= path directly -- the form selfcheck.py actually
        # uses (every live CheckResult in selfcheck.py passes detail by keyword,
        # so the positional fixture above would not exercise its extraction path).
        src = tmp_path / "mod.py"
        src.write_text(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class CheckResult:\n"
            "    name: str\n    passed: bool = True\n    detail: str = ''\n\n"
            "def f():\n"
            "    return CheckResult('x', detail='cost \\u2014 high')\n",
            encoding="utf-8",
        )
        collected = [s for _, s in _collect_print_string_args(src)]
        assert any(ord(c) > 127 for s in collected for c in s), (
            "extended collector must surface a keyword CheckResult(detail=...) literal"
        )

    def test_sh_emit_flags_echo_but_not_comment(self, tmp_path):
        good = tmp_path / "a.sh"
        good.write_text(
            "# note — comment\necho \"cost — high\"\n", encoding="utf-8"
        )
        found = _collect_sh_emit_non_ascii(good)
        # The echo line (2) is flagged; the comment line (1) is not.
        assert found and all(ln == 2 for ln, _ in found), found


def _ast_scope_nodes(scope: ast.AST):
    """The nodes of one scope, not descending into nested functions (each of
    those is its own scope), so a name bound in one function is never read
    against an f-string in another."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(node))


def _ast_scopes(path: Path):
    """``(name, node)`` for the module and every function in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    yield "<module>", tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node


def _ast_callee(node: ast.Call) -> str | None:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


#: Every shipped Python module the two DEF-799 pins walk: the engine (minus
#: its byte-mirror of tools/cc, which test_contracts pins to the source) and
#: the deployed scripts and hooks. DERIVED, so a new module is walked the day
#: it appears. The shipped surface ONLY: `scripts/`, `bench/` and `tests/`
#: are operator-local and render however they like -- copy a message shape
#: from them into a shipped module and these pins catch it there.
_SHIPPED_PY_MODULES = tuple(sorted(
    p for p in (
        [q for q in (REPO_ROOT / "espalier").rglob("*.py") if "_vendor" not in q.parts]
        + list((REPO_ROOT / "tools" / "cc").rglob("*.py"))
    )
))


class TestRemediesSpellTheRemedyInterpreter:
    """DEF-758: a remedy the operator will TYPE spells ``cli._remedy_py()``
    (the resolver's answer when it clears the floor, else the interpreter
    running the command), never ``_detect_python_command()`` -- whose answer is
    what gets WRITTEN into settings.json and, on a host where nothing
    validated, is the literal ``python`` (a Python 2 shim, a Store alias,
    absent). Census 2026-09-10: 39 f-strings interpolated the resolver beside
    ``-m espalier``, plus ``py = _detect_python_command()`` locals reaching
    one, plus the resolver passed as an argument to a remedy-building helper.

    The POPULATION is every call of the resolver in the three modules, by
    name, wherever it sits -- an f-string, a local, a helper argument, the
    help epilog -- attributed to its innermost enclosing function. The
    EXEMPTIONS are the argued sites that need the WRITE answer: the resolver's
    reader ``_remedy_interpreter``, ``_build_settings_json`` (writes it),
    ``rewire_interpreter_in_settings`` (the rewire target) and
    ``doctor._resolver_hint`` (the seam for a sentence about what init wrote).
    A call anywhere else reds with its function named. Reads the AST, not the
    resolver's output, which on a healthy host agrees with the remedy answer
    and would pass every wrong site (the closed-loop trap).
    """

    #: Both names that answer with the WRITE value: the resolver, and doctor's
    #: descriptive alias of it. The first cut keyed on the resolver alone, and
    #: a `--rewire-interpreter` re-run spelled through the alias sailed past it
    #: (both reviewers, 2026-09-12); a wrapper of either belongs here too.
    _RESOLVERS = ("_detect_python_command", "_resolver_hint")
    #: Every engine module, DERIVED -- a fourth module that imports the
    #: resolver is walked the day it appears, not the day someone lists it.
    _MODULES = tuple(sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "espalier").rglob("*.py")
        if "_vendor" not in p.parts
    ))
    #: (module, innermost function, callee) -> the argument for the write answer.
    _ALLOWED = {
        ("espalier/cli.py", "_remedy_interpreter", "_detect_python_command"):
            "reads the resolver to decide whether its answer clears the floor",
        ("espalier/cli.py", "_build_settings_json", "_detect_python_command"):
            "writes the value into settings.json",
        ("espalier/cli.py", "rewire_interpreter_in_settings", "_detect_python_command"):
            "the rewire target is what settings.json will carry",
        ("espalier/cli.py", "_unwired_gate_diagnosis", "_detect_python_command"):
            "four hand-edit sentences name the value to write (the `written` local)",
        ("espalier/doctor.py", "_resolver_hint", "_detect_python_command"):
            "the descriptive seam itself",
        ("espalier/doctor.py", "_check_reporter_hook_wiring", "_resolver_hint"):
            "three hand-edit sentences name the value to write (the `written` local)",
        ("espalier/doctor.py", "run_doctor_check", "_resolver_hint"):
            "three hand-edit sentences name the value to write (the `written` local)",
    }

    @staticmethod
    def _callee(node: ast.Call) -> str | None:
        f = node.func
        return (
            f.id if isinstance(f, ast.Name)
            else f.attr if isinstance(f, ast.Attribute)
            else None
        )

    @staticmethod
    def _scope_nodes(scope: ast.AST):
        """The nodes of one scope, not descending into nested functions (each
        of those is its own scope to the callers below), so a name bound in
        one function is never read against an f-string in another."""
        yield from _ast_scope_nodes(scope)

    @classmethod
    def _scopes(cls, rel: str):
        yield from _ast_scopes(REPO_ROOT / rel)

    @classmethod
    def _resolver_calls(cls, rel: str):
        """``(innermost enclosing function, callee, line)`` per resolver call."""
        for owner, scope in cls._scopes(rel):
            for node in cls._scope_nodes(scope):
                if isinstance(node, ast.Call) and cls._callee(node) in cls._RESOLVERS:
                    yield owner, cls._callee(node), node.lineno

    @classmethod
    def _laundered_remedies(cls, rel: str):
        """``(function, line)`` per f-string that carries ``-m espalier`` and
        interpolates a resolver call, or a name the same scope bound from one
        -- the ``py = _detect_python_command()`` shape the row named, and the
        ``written = _resolver_hint()`` shape a descriptive sentence uses
        legitimately ONLY in an f-string of its own."""
        for owner, scope in cls._scopes(rel):
            bound: set[str] = set()
            for node in cls._scope_nodes(scope):
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                    targets, value = [node.target], node.value
                else:
                    continue
                if value is not None and any(
                    isinstance(c, ast.Call) and cls._callee(c) in cls._RESOLVERS
                    for c in ast.walk(value)
                ):
                    bound.update(
                        n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)
                    )
            for js in cls._scope_nodes(scope):
                if not isinstance(js, ast.JoinedStr):
                    continue
                if not any(
                    isinstance(v, ast.Constant) and isinstance(v.value, str)
                    and "-m espalier" in v.value
                    for v in js.values
                ):
                    continue
                for fv in js.values:
                    if isinstance(fv, ast.FormattedValue) and any(
                        (isinstance(n, ast.Call) and cls._callee(n) in cls._RESOLVERS)
                        or (isinstance(n, ast.Name) and n.id in bound)
                        for n in ast.walk(fv.value)
                    ):
                        yield owner, js.lineno
                        break

    def test_the_resolver_is_called_only_where_its_write_answer_is_wanted(self):
        stray = [
            f"{rel}:{line} {callee}() in {func}()"
            for rel in self._MODULES
            for func, callee, line in self._resolver_calls(rel)
            if (rel, func, callee) not in self._ALLOWED
        ]
        assert not stray, (
            "a write-answer resolver is called outside the argued sites. A "
            "remedy spelled with it cannot run on a host where nothing "
            "validated: spell `_remedy_py()` (cli.py and doctor.py each define "
            "one) for a command the operator will type, or read "
            "`doctor._resolver_hint()` into a `written` local for a sentence "
            "about what init WROTE; add a site to _ALLOWED only with the "
            "argument for the write answer.\n  " + "\n  ".join(stray)
        )

    def test_no_remedy_f_string_carries_a_write_answer(self):
        """The laundering shapes: a resolver call, or a local bound from one,
        interpolated in the same f-string as ``-m espalier``. A descriptive
        sentence keeps its ``written`` value in an f-string of its own,
        joined with ``+``, so the command and the value are two nodes."""
        laundered = sorted({
            f"{rel}:{line} in {func}()"
            for rel in self._MODULES
            for func, line in self._laundered_remedies(rel)
        })
        assert not laundered, (
            "an f-string carrying `-m espalier` interpolates a write-answer "
            "resolver (or a local bound from one). Spell the command with "
            "`_remedy_py()`; if the same sentence also names the value to "
            "WRITE, put that in its own f-string joined with `+`.\n  "
            + "\n  ".join(laundered)
        )

    # ── DEF-805: the interpreter slot, followed through parameters ──────────
    #: Calls whose value IS the remedy answer -- the interpreter to spell --
    #: by callee name: cli's pair, and doctor's seam over them.
    _REMEDY_ANSWERS = ("_remedy_py", "_remedy_interpreter", "_remedy_hint")
    _MODULE_PATHS = tuple(REPO_ROOT / rel for rel in _MODULES)

    @classmethod
    def _remedy_bound(cls, scope: ast.AST) -> set[str]:
        """Names ``scope`` binds from a remedy-answer call: ``py = _remedy_py()``
        and the FIRST element of an unpacked tuple (``hint, clears =
        _remedy_interpreter()``; the other elements are a flag and a names
        string, not an interpreter)."""
        bound: set[str] = set()
        for node in _ast_scope_nodes(scope):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                targets, value = [node.target], node.value
            else:
                continue
            if value is None or not any(
                isinstance(c, ast.Call) and _ast_callee(c) in cls._REMEDY_ANSWERS
                for c in ast.walk(value)
            ):
                continue
            for target in targets:
                head = target.elts[0] if isinstance(target, ast.Tuple) and target.elts else target
                if isinstance(head, ast.Name):
                    bound.add(head.id)
        return bound

    @classmethod
    def _interpreter_slots(cls, path: Path):
        """``(function, scope, line, slot)`` per f-string whose ``-m espalier``
        is preceded by an interpolated value -- the interpreter slot."""
        for owner, scope in _ast_scopes(path):
            for js in _ast_scope_nodes(scope):
                if not isinstance(js, ast.JoinedStr):
                    continue
                for i, v in enumerate(js.values):
                    if not (isinstance(v, ast.Constant) and isinstance(v.value, str)
                            and "-m espalier" in v.value):
                        continue
                    before = v.value[: v.value.index("-m espalier")]
                    if before.strip() == "" and i > 0 and isinstance(js.values[i - 1], ast.FormattedValue):
                        yield owner, scope, js.lineno, js.values[i - 1].value

    @staticmethod
    def _calls_of(name: str, paths):
        """``(path, caller scope, call)`` per call of ``name`` in ``paths``."""
        for path in paths:
            for _owner, scope in _ast_scopes(path):
                for node in _ast_scope_nodes(scope):
                    if isinstance(node, ast.Call) and _ast_callee(node) == name:
                        yield path, scope, node

    @staticmethod
    def _argument_for(call: ast.Call, fn: ast.FunctionDef, param: str):
        """The expression a call passes for ``param``; ``None`` when the call
        leaves it to its default; the ``ast.Starred`` node itself when a
        ``*args`` / ``**kwargs`` at the site makes it unresolvable."""
        positional = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        if param in positional:
            index = positional.index(param)
            if index < len(call.args):
                return call.args[index]
            starred = [a for a in call.args if isinstance(a, ast.Starred)]
            if starred:
                return starred[0]
        for kw in call.keywords:
            if kw.arg == param:
                return kw.value
        if any(kw.arg is None for kw in call.keywords):
            return ast.Starred(value=ast.Name(id="kwargs", ctx=ast.Load()), ctx=ast.Load())
        return None

    @classmethod
    def _slot_verdict(cls, path: Path, scope: ast.AST, slot: ast.AST, paths, seen: set) -> str | None:
        """``None`` when ``slot`` is the remedy answer: a remedy-answer call
        (or its ``[0]``), a name bound from one in this scope, or a parameter
        that EVERY call site of this function passes the remedy answer to --
        the parameter-borne case DEF-758's pin was blind to (DEF-805: `name`
        unpacked from a parameter tuple). Else the reason, with the site.

        Scope limits, stated so nobody mistakes green for more than it is:
        call sites are matched by the callee's bare NAME across the walked
        modules, not by binding, so two same-named functions would share a
        verdict (none exist today; ``test_every_traced_function_name_is_unique``
        holds that); a parameter reached twice on one chain (``seen``) is
        judged once; a starred argument at a call site is unresolvable and
        reds as such rather than passing."""
        if isinstance(slot, ast.Call) and _ast_callee(slot) in cls._REMEDY_ANSWERS:
            return None
        if (isinstance(slot, ast.Subscript) and isinstance(slot.value, ast.Call)
                and _ast_callee(slot.value) in cls._REMEDY_ANSWERS):
            return None
        if not isinstance(slot, ast.Name):
            return f"interpolates `{ast.unparse(slot)}`"
        if slot.id in cls._remedy_bound(scope):
            return None
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return f"interpolates `{slot.id}`, bound from no remedy answer"
        params = {a.arg for a in scope.args.posonlyargs + scope.args.args + scope.args.kwonlyargs}
        if slot.id not in params:
            return f"interpolates `{slot.id}`, bound from neither a remedy answer nor a parameter"
        key = (scope.name, slot.id)
        if key in seen:
            return None
        seen.add(key)
        calls = list(cls._calls_of(scope.name, paths))
        if not calls:
            return f"parameter `{slot.id}` of {scope.name}() has no call site in the walked modules"
        reasons = []
        for cpath, cscope, call in calls:
            where = f"{cpath.relative_to(REPO_ROOT).as_posix() if cpath.is_relative_to(REPO_ROOT) else cpath.name}:{call.lineno}"
            arg = cls._argument_for(call, scope, slot.id)
            if arg is None:
                reasons.append(f"{where} leaves `{slot.id}` to its default")
                continue
            if isinstance(arg, ast.Starred):
                reasons.append(f"{where} passes `{slot.id}` through a starred argument, unresolvable")
                continue
            why = cls._slot_verdict(cpath, cscope, arg, paths, seen)
            if why:
                reasons.append(f"{where} {why}")
        return "; ".join(reasons) or None

    @classmethod
    def _laundered_slots(cls, paths):
        for path in paths:
            for owner, scope, line, slot in cls._interpreter_slots(path):
                why = cls._slot_verdict(path, scope, slot, paths, set())
                if why:
                    yield path, line, owner, why

    def test_the_interpreter_slot_of_every_remedy_is_the_remedy_answer(self):
        """DEF-805 widened DEF-758: the two tests above key on a RESOLVER call
        (the write answer) leaking into a remedy; this one asks the positive
        question of the interpreter slot itself -- what precedes ``-m espalier``
        -- and follows a parameter-borne name to every call site, one level at
        a time. RED on HEAD at exactly one site: ``_warn_interpreter_below_floor``
        spelled the candidate that had just failed the floor."""
        stray = sorted(
            f"{path.relative_to(REPO_ROOT).as_posix()}:{line} in {owner}(): {why}"
            for path, line, owner, why in self._laundered_slots(self._MODULE_PATHS)
        )
        assert not stray, (
            "the interpreter slot of a `-m espalier` remedy is not the remedy "
            "answer. Spell `_remedy_py()`, bind a local from it, or pass it "
            "through the parameter at every call site:\n  " + "\n  ".join(stray)
        )

    def test_every_traced_function_name_is_unique(self):
        """The call-site match is by bare name (see ``_slot_verdict``), which is
        sound only while no two shipped functions with a parameter-borne
        interpreter slot share a name."""
        traced: dict[str, set[str]] = {}
        for path in self._MODULE_PATHS:
            for _owner, scope, _line, slot in self._interpreter_slots(path):
                if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(slot, ast.Name):
                    params = {a.arg for a in scope.args.posonlyargs + scope.args.args + scope.args.kwonlyargs}
                    if slot.id in params:
                        traced.setdefault(scope.name, set()).add(path.relative_to(REPO_ROOT).as_posix())
        for name, sites in traced.items():
            defs = [
                p.relative_to(REPO_ROOT).as_posix()
                for p in self._MODULE_PATHS
                for node in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
            ]
            assert len(defs) == 1, f"{name}() is defined in {defs}; the name-keyed call-site match is ambiguous"

    @pytest.mark.parametrize("src", [
        # the DEF-805 shape: unpacked from a parameter tuple
        'def warn(probe):\n    name, path, said = probe\n    print(f"`{name} -m espalier init .`")\n',
        # a parameter a call site fills with a literal
        'def g(py):\n    print(f"{py} -m espalier x")\ng("python")\n',
        # a parameter nobody calls
        'def g(py):\n    print(f"{py} -m espalier x")\n',
        # a parameter left to its default at one of two sites
        'def g(py="python"):\n    print(f"{py} -m espalier x")\ng(_remedy_py())\ng()\n',
        # the resolver itself
        'py = _detect_python_command()\nprint(f"{py} -m espalier x")\n',
        # the second element of the unpacked tuple is the flag, not the interpreter
        'py, clears = _remedy_interpreter()\nprint(f"{clears} -m espalier x")\n',
        # a starred argument at the call site is unresolvable, so it reds
        'def g(py):\n    print(f"{py} -m espalier x")\nargs = [_remedy_py()]\ng(*args)\n',
    ])
    def test_the_slot_gate_reds_on_a_laundered_interpreter(self, tmp_path, src):
        mod = tmp_path / "m.py"
        mod.write_text(src, encoding="utf-8")
        assert list(self._laundered_slots((mod,))), src

    @pytest.mark.parametrize("src", [
        'print(f"{_remedy_py()} -m espalier x")\n',
        'py = _remedy_py()\nprint(f"{py} -m espalier x")\n',
        'hint, clears = _remedy_interpreter()\nprint(f"{hint} -m espalier x")\n',
        'def g(py):\n    print(f"{py} -m espalier x")\ng(_remedy_py())\n',
        # two levels: h passes its own parameter on, and is itself called right
        'def g(py):\n    print(f"{py} -m espalier x")\ndef h(py):\n    g(py)\nh(_remedy_py())\n',
        'def g(*, py):\n    print(f"{py} -m espalier x")\ng(py=_remedy_py())\n',
        # a literal interpreter is the bare-token gate\'s business, not this one
        'print("python -m espalier x")\n',
    ])
    def test_the_slot_gate_is_quiet_on_the_remedy_answer(self, tmp_path, src):
        mod = tmp_path / "m.py"
        mod.write_text(src, encoding="utf-8")
        assert not list(self._laundered_slots((mod,))), src

    def test_every_exemption_is_a_live_site(self):
        """The allowlist is a census of the sites that call a resolver, not a
        wish list: an entry for a function that stopped calling it (or no
        longer exists) is a stale argument and reds here."""
        live = {
            (rel, func, callee)
            for rel in self._MODULES
            for func, callee, _ in self._resolver_calls(rel)
        }
        assert live == set(self._ALLOWED), sorted(live ^ set(self._ALLOWED))


class TestOsErrorsRenderAsPaths:
    """DEF-799, mechanism one: ``str(exc)`` on an ``OSError`` renders its path
    through ``repr`` -- ``[Errno 13] Access is denied: 'C:\\\\repo\\\\.claude'`` --
    so a Windows operator who pastes the path a doctor failure or a hook
    warning names is told no such file. Driven on the Windows walk 2026-09-14
    at five sites; the census found fifty-two loads of a handler-bound name
    across the engine, the hooks and ``session_resume``.

    The POPULATION is every handler that CAN bind an ``OSError`` -- one
    naming the OSError family, ``Exception`` or ``BaseException`` (a hook's
    crash guard is ``except Exception as exc``, and it fires on exactly the
    file read that fails) -- and every load of that name inside it, nested
    functions included. Not a list of types that ARE OSErrors but of types
    that can CATCH one: a handler naming only non-OSError types is out by
    construction, never by omission. A load is clean when it is an attribute
    base (``exc.errno``), a ``raise``, a type question (``isinstance``,
    ``type``), or the argument of a renderer on the roster below; anything
    else -- an f-string, ``str()``, a ``print`` or ``.format`` argument, a
    return, an append -- is the raw text escaping to a reader, and reds with
    its function named. Keyed on the HANDLER BINDING, not on a list of
    printing calls, because a scanner gated on call names is blind to every
    sink the list omits (SHARP_EDGES). Reads the AST, never a rendered
    message, which on POSIX with a plain path is indistinguishable from the
    fix (the closed-loop trap). ``os_error_text`` is total (a non-OSError
    comes back as ``str(exc)``), so routing a broad handler costs nothing.
    """

    #: Every handler type that can bind an OSError: the family, DERIVED from
    #: the interpreter's builtins (``IOError`` and ``EnvironmentError`` are
    #: aliases; ``TimeoutError`` and the connection errors are subclasses),
    #: plus the two bases a broad handler names -- never a hand list.
    _CATCHES_AN_OSERROR = frozenset(
        name for name, value in vars(builtins).items()
        if isinstance(value, type) and issubclass(value, OSError)
    ) | {"Exception", "BaseException"}
    #: Callees a handler-bound exception may be handed to, each with its
    #: kind: ``seam`` (the renderer itself), ``routes`` (a helper whose body
    #: is PROVEN below to call the seam -- the roster is not the place a red
    #: is silenced by adding a line), ``errno-only`` (never renders the text;
    #: the one argued exemption). Liveness-pinned both ways.
    _RENDERERS = {
        "os_error_text": ("seam", "espalier/_text.py and tools/cc/_json_safe.py"),
        "warn_exc": ("routes", "the hooks' one exception reporter (tools/cc/hooks/_hook_utils.py)"),
        "_is_permission_refusal": ("errno-only", "reads exc.errno and never the text (espalier/_rmtree.py)"),
    }
    _CLEAN_CALLEES = frozenset({"isinstance", "issubclass", "type", "getattr", "hasattr"})

    @classmethod
    def _handler_types(cls, handler: ast.ExceptHandler) -> set[str]:
        if handler.type is None:
            return set()
        return {
            n.id if isinstance(n, ast.Name) else n.attr
            for n in ast.walk(handler.type)
            if isinstance(n, (ast.Name, ast.Attribute))
        }

    @classmethod
    def _escapes(cls, path: Path):
        """``(function, line, shape)`` per load of an OSError-family handler's
        bound name that is neither structural nor routed to a renderer; and
        ``(function, line, "renderer:<callee>")`` per routed load, so the
        roster can be held equal to the callees in use."""
        for owner, scope in _ast_scopes(path):
            nodes = list(_ast_scope_nodes(scope))
            parents = {c: p for p in nodes for c in ast.iter_child_nodes(p)}
            for handler in nodes:
                if not isinstance(handler, ast.ExceptHandler) or not handler.name:
                    continue
                if not (cls._handler_types(handler) & cls._CATCHES_AN_OSERROR):
                    continue
                name = handler.name
                # Parents over the WHOLE handler, nested functions included: a
                # closure that renders the bound name is the same escape.
                parents = {c: p for p in ast.walk(handler) for c in ast.iter_child_nodes(p)}
                for node in ast.walk(handler):
                    if not (isinstance(node, ast.Name) and node.id == name
                            and isinstance(node.ctx, ast.Load)):
                        continue
                    parent = parents.get(node)
                    if isinstance(parent, (ast.Attribute, ast.Raise)):
                        continue
                    if isinstance(parent, ast.Call) and _ast_callee(parent) in cls._CLEAN_CALLEES:
                        continue
                    if isinstance(parent, ast.Call) and _ast_callee(parent) in cls._RENDERERS:
                        yield owner, node.lineno, f"renderer:{_ast_callee(parent)}"
                        continue
                    if isinstance(parent, ast.FormattedValue):
                        shape = f"`{name}` in an f-string"
                    elif isinstance(parent, ast.Call):
                        shape = f"`{name}` as an argument of {_ast_callee(parent)}()"
                    else:
                        shape = f"`{name}` in a {type(parent).__name__}"
                    yield owner, node.lineno, shape

    def test_no_oserror_text_escapes_raw(self):
        stray = sorted(
            f"{path.relative_to(REPO_ROOT).as_posix()}:{line} {shape} in {func}()"
            for path in _SHIPPED_PY_MODULES
            for func, line, shape in self._escapes(path)
            if not shape.startswith("renderer:")
        )
        assert not stray, (
            "an OSError bound by an except handler reaches text raw -- its path "
            "is rendered through repr, doubled backslashes and all, on the one "
            "platform whose paths carry them. Route it through "
            "`os_error_text(exc)` (espalier._text in the engine, _json_safe in "
            "tools/cc), or hand it to a renderer on the roster with the "
            "argument for why:\n  " + "\n  ".join(stray)
        )

    def test_every_renderer_on_the_roster_is_live_and_every_live_one_is_on_it(self):
        live = {
            shape.removeprefix("renderer:")
            for path in _SHIPPED_PY_MODULES
            for _func, _line, shape in self._escapes(path)
            if shape.startswith("renderer:")
        }
        assert live == set(self._RENDERERS), sorted(live ^ set(self._RENDERERS))

    def test_every_routing_renderer_calls_the_seam_in_its_own_body(self):
        """The roster is where a red would be silenced by one added line, so
        a ``routes`` entry is held to its claim: its ``def`` in the shipped
        modules calls ``os_error_text``. The seam is exempt as the root; the
        errno-only entry is the one argued exemption and must NOT render."""
        for name, (kind, _why) in self._RENDERERS.items():
            defs = [
                node
                for path in _SHIPPED_PY_MODULES
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
            ]
            assert defs, f"roster entry {name!r} has no def in the shipped modules"
            calls_seam = [
                any(isinstance(n, ast.Call) and _ast_callee(n) == "os_error_text" for n in ast.walk(d))
                for d in defs
            ]
            if kind == "routes":
                assert all(calls_seam), f"{name}() is on the roster as routing through the seam and does not"
            elif kind == "errno-only":
                renders = [
                    n for d in defs for n in ast.walk(d)
                    if isinstance(n, (ast.JoinedStr,)) or (isinstance(n, ast.Call) and _ast_callee(n) == "str")
                ]
                assert not renders, f"{name}() is argued errno-only and renders text"
            else:
                assert kind == "seam" and name == "os_error_text", (name, kind)

    @pytest.mark.parametrize("handler", ["(OSError, ValueError)", "Exception", "BaseException", "PermissionError"])
    @pytest.mark.parametrize("body", [
        'print(f"cannot read: {exc}")',
        'return str(exc)',
        'failures.append(f"{rel}: {exc!r}")',
        'print("cannot read:", exc)',
        'return "cannot read: {}".format(exc)',
        'warn(exc)',
        # a closure that renders the bound name is the same escape
        'def later():\n            return f"{exc}"\n        failures.append(later)',
    ])
    def test_the_gate_reds_on_a_raw_render(self, tmp_path, body, handler):
        mod = tmp_path / "m.py"
        mod.write_text(
            "def f(rel, failures):\n"
            "    try:\n"
            "        open(rel)\n"
            f"    except {handler} as exc:\n"
            f"        {body}\n",
            encoding="utf-8",
        )
        assert [s for _f, _l, s in self._escapes(mod) if not s.startswith("renderer:")], (handler, body)

    def test_the_gate_is_out_by_construction_on_a_handler_that_cannot_bind_an_oserror(self, tmp_path):
        mod = tmp_path / "m.py"
        mod.write_text(
            "def f(rel):\n"
            "    try:\n"
            "        int(rel)\n"
            "    except (ValueError, KeyError) as exc:\n"
            '        print(f"bad: {exc}")\n',
            encoding="utf-8",
        )
        assert not list(self._escapes(mod))

    @pytest.mark.parametrize("body", [
        'print(f"cannot read: {os_error_text(exc)}")',
        'raise RuntimeError(exc.strerror) from exc',
        'if isinstance(exc, PermissionError): return exc.errno',
        'warn_exc("read failed", exc)',
        'def later():\n            return exc.errno\n        return later',
    ])
    def test_the_gate_is_quiet_on_a_routed_or_structural_load(self, tmp_path, body):
        mod = tmp_path / "m.py"
        mod.write_text(
            "def f(rel):\n"
            "    try:\n"
            "        open(rel)\n"
            "    except OSError as exc:\n"
            f"        {body}\n",
            encoding="utf-8",
        )
        assert not [s for _f, _l, s in self._escapes(mod) if not s.startswith("renderer:")], body


#: Names this repo binds to paths and commands without a path source in the
#: same scope (``cmd`` iterating a set of interpreter tokens). Hand-written,
#: so held live both ways by the class below, and each name has its own red
#: fixture there.
_VOCABULARY = frozenset({
    "cmd", "command", "old_command", "new_command", "resolved", "interp",
    "script", "a_script", "b_script", "path", "root",
})


class TestPathsAreNotRenderedThroughRepr:
    """DEF-799, mechanism two: an explicit ``!r`` on a path, a hook command
    or an interpreter token -- ``resolves to 'C:\\\\Python311\\\\python.exe'`` --
    the line the Windows walk quoted verbatim with the doubled backslashes
    already on screen. The house rendering is the value plain inside backticks,
    the delimiter every remedy in this repo already uses.

    Two rules, one population (every f-string and ``.format`` template in the
    shipped modules). Rule one is DERIVED per scope: ``!r`` on a name bound
    from a path source (``shutil.which``, ``Path``, ``sys.executable``,
    ``exc.filename``, ``os.path.*``) or from a ``Path``-typed parameter reds.
    Rule two is the vocabulary below -- names this repo binds to paths and
    commands without a path source in the same scope (``cmd`` iterating a set
    of interpreter tokens) -- and it is held live both ways: a name nobody
    interpolates plain any more is a dead entry and reds too.
    """

    _PATH_CALLS = frozenset({
        "which", "Path", "PurePath", "PurePosixPath", "PureWindowsPath", "resolve",
        "absolute", "abspath", "realpath", "expanduser", "fspath", "fsdecode",
        "getcwd", "cwd", "home", "joinpath", "relative_to",
    })
    _PATH_ATTRS = frozenset({"executable", "filename", "filename2", "parent", "__file__"})
    _VOCABULARY = _VOCABULARY

    @classmethod
    def _path_bound_names(cls, scope: ast.AST) -> set[str]:
        bound: set[str] = set()
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in scope.args.args + scope.args.kwonlyargs + scope.args.posonlyargs:
                if arg.annotation is not None and "Path" in ast.unparse(arg.annotation):
                    bound.add(arg.arg)
        for node in _ast_scope_nodes(scope):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                targets, value = [node.target], node.value
            elif isinstance(node, ast.For):
                targets, value = [node.target], node.iter
            else:
                continue
            if value is None:
                continue
            if any(
                (isinstance(c, ast.Call) and _ast_callee(c) in cls._PATH_CALLS)
                or (isinstance(c, ast.Attribute) and c.attr in cls._PATH_ATTRS)
                for c in ast.walk(value)
            ):
                bound |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        return bound

    @classmethod
    def _reprd(cls, path: Path):
        """``(function, line, expression)`` per ``!r`` on a path-bound or
        vocabulary name in an f-string, or ``{name!r}`` in a plain-string
        template; and ``(function, line, "plain:<name>")`` per vocabulary
        name interpolated without a conversion, for the liveness pin."""
        template = re.compile(r"\{(" + "|".join(sorted(cls._VOCABULARY)) + r")!r\}")
        for owner, scope in _ast_scopes(path):
            pathy = cls._path_bound_names(scope) | cls._VOCABULARY
            for node in _ast_scope_nodes(scope):
                if isinstance(node, ast.JoinedStr):
                    for value in node.values:
                        if not isinstance(value, ast.FormattedValue):
                            continue
                        names = {n.id for n in ast.walk(value.value) if isinstance(n, ast.Name)}
                        if value.conversion == 114 and names & pathy:
                            yield owner, node.lineno, ast.unparse(value.value)
                        elif value.conversion == -1 and value.format_spec is None:
                            for name in names & cls._VOCABULARY:
                                yield owner, node.lineno, f"plain:{name}"
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for m in template.finditer(node.value):
                        yield owner, node.lineno, m.group(0)

    def test_no_path_command_or_interpreter_is_reprd(self):
        stray = sorted(
            f"{path.relative_to(REPO_ROOT).as_posix()}:{line} {{{expr}!r}} in {func}()"
            for path in _SHIPPED_PY_MODULES
            for func, line, expr in self._reprd(path)
            if not expr.startswith("plain:")
        )
        assert not stray, (
            "a path, hook command or interpreter token is rendered through "
            "repr -- on Windows that is doubled backslashes and quotes the "
            "operator cannot paste. Render it plain inside backticks "
            "(`{cmd}`), the delimiter every remedy here already uses:\n  "
            + "\n  ".join(stray)
        )

    def test_every_vocabulary_name_is_still_interpolated_plain_somewhere(self):
        live = {
            expr.removeprefix("plain:")
            for path in _SHIPPED_PY_MODULES
            for _func, _line, expr in self._reprd(path)
            if expr.startswith("plain:")
        }
        assert live == self._VOCABULARY, sorted(live ^ self._VOCABULARY)

    @pytest.mark.parametrize("body", [
        'found = shutil.which("git"); print(f"git at {found!r}")',
        'here = Path(root) / "x"; print(f"{here!r}")',
        'exe = sys.executable; print(f"running {exe!r}")',
        'TEMPLATE = "timeout running {cmd!r}"',
    ] + [
        # one fixture per vocabulary name, so deleting a name to silence a red
        # reds its own fixture instead of shrinking the liveness set with it
        f'print(f"value {{{name}!r}} is stale")' for name in sorted(_VOCABULARY)
    ])
    def test_the_gate_reds_on_a_reprd_path(self, tmp_path, body):
        mod = tmp_path / "m.py"
        params = ", ".join(sorted(self._VOCABULARY | {"root"}))
        mod.write_text(f"def f({params}):\n    {body}\n", encoding="utf-8")
        assert [e for _f, _l, e in self._reprd(mod) if not e.startswith("plain:")], body

    @pytest.mark.parametrize("body", [
        'found = shutil.which("git"); print(f"git at `{found}`")',
        'print(f"the {event!r} event carries no entry")',
        'print(f"hook interpreter `{cmd}` is stale")',
    ])
    def test_the_gate_is_quiet_on_a_plain_or_non_path_repr(self, tmp_path, body):
        mod = tmp_path / "m.py"
        mod.write_text(f"def f(event, cmd):\n    {body}\n", encoding="utf-8")
        assert not [e for _f, _l, e in self._reprd(mod) if not e.startswith("plain:")], body
