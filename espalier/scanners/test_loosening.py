#!/usr/bin/env python3
"""Scanner for test-loosening patterns.

Detects landed artifacts of test-loosening:
  assert_tautological — `assert True` / `assert 1 == 1` / `assert <truthy literal>`
                        / `assert (cond, "msg")` (non-empty collection literal)
  zero_assertion      — a `test_*` function whose body proves nothing (no
                        assertion at all and no raising call). Tautological-assert
                        bodies are owned by assert_tautological (not double-flagged);
                        skip/xfail-decorated tests are deliberately inert and exempt.
  bare_skip           — `pytest.skip()` with no reason
  skip_no_reason      — `@pytest.mark.skip` decorator without reason= kwarg
  xfail_no_reason     — `@pytest.mark.xfail` decorator without reason= kwarg
  nondiscriminating_hook_assert
                      — a deny-intent `test_*` that invokes the `run_hook` helper and
                        observes ONLY the return code. Under the channel-XOR hook
                        protocol a deny is signalled by exit 0 + a stdout-JSON
                        `permissionDecision`, so `assert result.returncode == 0` is
                        identical for allow and deny — the test cannot fail for its
                        stated (deny) reason. ADVISORY and FP-prone by construction
                        (intent is inferred from the test NAME); the intent keyword set
                        is calibrated to 0 false positives over the live tree, and a
                        test that discriminates via stdout/stderr, a `permissionDecision`
                        literal, or an `assert_hook_*` helper is NOT flagged. A channel
                        mention that only NARRATES -- inside an assert's message, a
                        `raise`, an f-string assigned to a name, or a `print()` /
                        `pytest.fail()` / `pytest.skip()` argument -- does not count:
                        the value is rendered there, never compared or parsed.
  nondiscriminating_hook_allow
                      — the allow-side mirror: an allow-intent `test_*` invoking the
                        same `run_hook`/`_run_hook` helper that observes ONLY the return
                        code. An over-block regression (a legitimate op flipping to a
                        deny) is exit 0 too, so a bare returncode assert cannot catch it.
                        Same invoker scope and channel-observation exemption as the deny
                        arm; the two are mutually exclusive (the deny arm disqualifies
                        allow-intent names). Broader invoker coverage than
                        `run_hook`/`_run_hook` is a shared, deliberate boundary of both
                        arms — a separate calibration, not this rule.

Empirical case: ImpossibleBench (Oct 2025) — GPT-5 exploits test cases 76%
of the time on impossible-SWE-bench. Reward Hacking Benchmark catalogues
6 categories of verifier manipulation. The hook-form would detect the ACT
(diff-aware); this scanner detects the ARTIFACT (current AST state).

Stdlib-only AST walk; constraint pinned by
tests/test_contracts.py::TestScannersStdlibOnly.
"""
from __future__ import annotations

import ast
import json
import os
from typing import Any

# NOTE: "cc" is a bare BASENAME, so os.walk prunes EVERY directory named cc at
# any depth -- the top-level blueprints cc/, tools/cc/, and its
# espalier/_vendor/cc/ byte-mirror. Deliberate: those governed harness-internal
# trees carry their own dense hits that would otherwise flood `espalier scan`.
# Caveat (latent, adopter-only): it also prunes an adopter package coincidentally
# named cc/, and --exclude only ADDs to this set (no override). If that ever
# bites, scope to the three harness cc path-suffixes explicitly, not a repo-root
# prefix (tools/cc & _vendor/cc are NOT at repo root).
DEFAULT_EXCLUDE = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".mypy_cache", ".ruff_cache",
    "cc",
}

# Skip earn-the-gate fixtures so live runs are not polluted by
# the scanner's own positive-case test data. The selfcheck-tests mirror
# (shipped as package-data) carries string-literal positive cases the
# same way; exempt it too.
EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    "espalier/_vendor/selfcheck_tests/",
)


def _skip_nested_repos(dirpath: str, dirnames: list[str]) -> None:
    """Drop embedded-repo subdirs from an os.walk ``dirnames`` in place — parity
    with ``espalier._safe_walk.safe_rglob(skip_nested_repos=True)``. Scanners are
    stdlib-only and cannot import ``_safe_walk``, so the prune is duplicated here.
    A nested ``.git`` (dir OR gitlink file) marks a foreign project."""
    dirnames[:] = [
        d for d in dirnames
        if not os.path.exists(os.path.join(dirpath, d, ".git"))
    ]


def iter_test_files(root: str, exclude: set[str] | None = None) -> list[str]:
    """Walk root, return paths to pytest-convention test files (test_*.py).

    "Is this a pytest FILE to scan for loosening?" — strictly ``test_*.py`` basenames.
    Deliberately narrower than strengthen._is_test_path (which also counts any ``tests``
    path as covered) and surface_impact's test-module check. Same words, different
    question; not a collapse/parity candidate.
    """
    exclude = exclude or DEFAULT_EXCLUDE
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude]
        _skip_nested_repos(dirpath, dirnames)
        for fn in filenames:
            if fn.startswith("test_") and fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def _is_tautological_assert(node: ast.expr) -> bool:
    """True if the assert expression is provably tautological at parse time."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    # A collection LITERAL with a literal element is always truthy. The
    # canonical footgun is `assert (cond, "msg")` — a parenthesized tuple that
    # always passes (CPython itself emits SyntaxWarning "assertion is always
    # true" for any non-empty tuple); the scanner's whole job is catching
    # landed test-vacuity artifacts, and this is the most common one.
    #   - Tuple: any non-empty tuple is provably truthy (incl. `(*xs,)`),
    #     matching CPython's own warning.
    #   - List/Set/Dict: truthy ONLY if it has a non-unpack element. A
    #     literal whose elements are EXCLUSIVELY unpacks (`[*xs]`, `{*xs}`,
    #     `{**ys}`) is FALSY when the operand is empty, so it is NOT a
    #     parse-time tautology — and CPython does not warn on those.
    # (An EMPTY literal is falsy — an always-FAIL, a different bug.)
    if isinstance(node, ast.Tuple):
        return bool(node.elts)
    if isinstance(node, (ast.List, ast.Set)):
        return any(not isinstance(e, ast.Starred) for e in node.elts)
    if isinstance(node, ast.Dict):
        # A `**unpack` entry contributes a None key; a real key does not.
        return any(k is not None for k in node.keys)
    if isinstance(node, ast.Compare):
        if (isinstance(node.left, ast.Constant)
                and len(node.comparators) == 1
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)
                and isinstance(node.comparators[0], ast.Constant)):
            return node.left.value == node.comparators[0].value
    return False


def _dotted_name(node: ast.expr) -> str | None:
    """Return dotted attribute chain (a.b.c) for a Name/Attribute, else None."""
    parts: list[str] = []
    cur: ast.expr | None = node
    while isinstance(cur, ast.Attribute):
        parts.insert(0, cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.insert(0, cur.id)
    return ".".join(parts) if parts else None


def _is_pytest_skip_call(call: ast.Call) -> bool:
    name = _dotted_name(call.func)
    # Require the explicit ``pytest.skip`` dotted form. The
    # bare name ``skip`` matched user-defined helpers and aliased
    # imports (``from contextlib import suppress as skip``). The
    # scanner is scoped to test files, but local helpers and aliases
    # do show up there.
    return name == "pytest.skip"


def _decorator_target(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return _dotted_name(target)


def _has_reason_kwarg(dec: ast.expr) -> bool:
    if not isinstance(dec, ast.Call):
        return False
    for kw in dec.keywords:
        if kw.arg == "reason":
            # An empty/whitespace string literal is not a real reason —
            # ``reason=""`` would otherwise evade skip_no_reason. A
            # non-literal kwarg (e.g. ``reason=SOME_CONST``) gets the benefit
            # of the doubt — treat it as present.
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return bool(kw.value.value.strip())
            return True
    # pytest accepts a POSITIONAL reason: ``@pytest.mark.skip("reason")`` /
    # ``pytest.skip("reason")``. A non-empty string positional arg is a valid
    # reason; treat it as present (otherwise the positional decorator form
    # false-flags skip_no_reason).
    return any(
        isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.strip()
        for a in dec.args
    )


# Ported from the self-host meta-guard's _function_has_real_assertion: a test
# function with NO real assertion is worse than no test — it fakes coverage. The
# meta-guard never shipped to adopters; the scanner gains a shippable analog.
# This omits the meta-guard's self-comparison check, so it is strictly WEAKER
# (never false-positives relative to it).
_TRIVIAL_ASSERT_TEXTS = ("assert True", "assert 1 == 1", "assert 1")

# Builtin calls that cannot meaningfully raise on their declared inputs and so
# do NOT count as "absence-of-exception is the proof" (a body whose only side
# effect is `print(...)` / `len(x)` is a fake test).
_TRIVIAL_BUILTIN_CALLS = frozenset({
    "print", "len", "str", "repr", "type", "id",
    "isinstance", "hasattr", "getattr", "callable",
    "tuple", "list", "dict", "set", "bool", "int", "float",
})

# Decorator targets that make an absent assertion legitimate: a skipped or
# xfailed test deliberately does not execute, so "no assertion" is expected,
# not a defect (a missing reason is owned by skip_no_reason / xfail_no_reason).
# Scoping zero_assertion away from these avoids false-positiving on every
# intentionally-skipped test.
_SKIP_XFAIL_DECORATORS = frozenset({
    "pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail",
})


def _is_trivial_builtin_call(call: ast.Call) -> bool:
    """True when ``call.func`` is a bare reference to a known no-raise builtin."""
    func = call.func
    return isinstance(func, ast.Name) and func.id in _TRIVIAL_BUILTIN_CALLS


def _function_has_real_assertion(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A function counts as a real test if it contains a non-trivial assert, an
    explicit raise, a non-builtin expression-statement call, or a non-trivial
    ``with`` context-manager call (e.g. ``pytest.raises``)."""
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Assert):
            assert_text = ast.unparse(stmt)
            if not any(t in assert_text for t in _TRIVIAL_ASSERT_TEXTS):
                return True
        if isinstance(stmt, ast.Raise):
            return True
        if isinstance(stmt, ast.Expr):
            call = stmt.value
            if isinstance(call, ast.Await):
                call = call.value  # `await foo()` — unwrap to the inner call
            if isinstance(call, ast.Call) and not _is_trivial_builtin_call(call):
                return True
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and not _is_trivial_builtin_call(ctx):
                    return True
    return False


def _has_skip_or_xfail_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the function carries a pytest skip/skipif/xfail decorator — a
    deliberately-inert test for which an absent assertion is expected."""
    return any(
        _decorator_target(dec) in _SKIP_XFAIL_DECORATORS
        for dec in node.decorator_list
    )


# A deny-intent hook test whose only observation is the return code cannot fail for its
# stated reason (channel-XOR: a deny is exit 0 + a stdout-JSON decision, the same exit
# code as an allow). Intent is not mechanically obvious — the only cheap signal is the
# test name — so this detector is FP-prone by construction and its keyword set is
# CALIBRATED to 0 false positives over the live tree. It is ADVISORY (not wired to a
# release gate). Per the governing frame (a false denial on an honest allow-test is
# worse than one un-caught instance of the class), the predicate is deliberately
# conservative: it fires only when a `run_hook(...)` call, a non-negated deny-intent
# name, and a `.returncode` assertion all co-occur AND no decision-channel observation
# exists.
# The hook-invocation helper names deny-tests use. BOTH the bare `run_hook` and the
# underscore-prefixed private `_run_hook` are live in this repo (189 vs 65 call sites);
# exact-equality on `run_hook` alone is blind to the `_run_hook` helper — including the
# kill-switch + integrity deny-tests. (Sister-hazard to `_has_deny_intent`'s substring note.)
_HOOK_INVOKERS = frozenset({"run_hook", "_run_hook"})
# Deny-intent substring signals (matched against the lowercased test NAME). Enumerated
# by stem so substring matching covers inflections ("block" ⊂ "blocks"/"blocked");
# "deny" is NOT a substring of "denied"/"denies", so those stems are listed explicitly.
_DENY_INTENT: frozenset[str] = frozenset({
    "deny", "denied", "denies", "denial",
    "block", "reject", "refuse", "forbid", "traversal",
})
# Allow-sense negation markers. The SAME deny keyword in an honest allow-test name
# ("does_not_block", "allows_...", "warns_but_does_not_block", "no_traversal_false_
# positive") describes the ALLOW path, where a bare `returncode == 0` IS the correct
# observation. A name carrying any of these is NOT deny-intent regardless of a deny
# substring hit — this keeps the detector on the FP-averse side of its own governing
# frame (over-suppression here is a safe false-NEGATIVE, never a false denial).
_ALLOW_NEGATION: frozenset[str] = frozenset({
    "allow", "permit", "unblock", "does_not", "doesnt", "do_not",
    "not_block", "not_deny", "not_reject", "advisory", "warns_but", "false_positive",
})
# Allow-intent substring signals (matched against the lowercased test NAME), the
# mirror of _DENY_INTENT. "allow" ⊂ "allows"/"allowed"; "permit" ⊂ "permitted"/
# "permits". No deny-negation gate is needed: _has_deny_intent already disqualifies
# any name carrying an _ALLOW_NEGATION marker (which includes "allow"/"permit"), so
# the allow-arm and deny-arm are mutually exclusive by construction.
_ALLOW_INTENT: frozenset[str] = frozenset({"allow", "permit"})


def _call_name(call: ast.Call) -> str | None:
    """The simple callee name for a Call — `func.id` for a bare name, `func.attr` for
    an attribute call (`mod.run_hook(...)`), else None."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return getattr(func, "attr", None)


def _body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """The function body with a leading docstring statement stripped, so a scan of the
    real CODE is not fooled by prose narrated in the docstring."""
    body = node.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def _invokes_hook(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the body CALLS a hook-invocation helper — the bare `run_hook(...)` or the
    underscore-prefixed private `_run_hook(...)` — i.e. the test actually exercises a hook
    (as opposed to merely naming one in a string)."""
    return any(
        isinstance(n, ast.Call) and _call_name(n) in _HOOK_INVOKERS
        for n in ast.walk(node)
    )


def _has_deny_intent(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the test NAME signals a deny/block intent AND is not negated into an
    allow-sense name. Calibration over the live tree showed the docstring is an
    unreliable intent source: a deny keyword there is as often NEGATED — "advisory
    warning, not a hard block", "auto-finalizes instead of blocking" — describing the
    ALLOW path as it is a genuine deny intent, so intent is read from the name only. The
    name carries the same negation hazard ("does_not_block", "allows_...",
    "warns_but_does_not_block"), so a deny keyword is disqualified when an allow-negation
    marker is also present — a false denial on an honest allow-test is worse than one
    un-caught instance (the governing frame). Substring match — underscore-delimited
    names defeat ``\\b`` word boundaries since ``_`` is a word char."""
    name = node.name.lower()
    if any(marker in name for marker in _ALLOW_NEGATION):
        return False
    return any(kw in name for kw in _DENY_INTENT)


def _asserts_returncode(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the body ASSERTS on a ``.returncode`` attribute — a ``.returncode`` access
    reached from inside an ``ast.Assert``. Requiring the assert context (not a bare read
    like ``print(r.returncode)``) makes the finding precise — "the test leans on the
    return code as its proof" — and keeps this rule disjoint from ``zero_assertion``: a
    ``.returncode`` assertion is a "real assertion" to that rule's predicate, so the two
    never double-flag the same body."""
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Assert) and any(
            isinstance(n, ast.Attribute) and n.attr == "returncode"
            for n in ast.walk(stmt)
        ):
            return True
    return False


# Calls whose arguments RENDER a value rather than compare or parse it. A channel
# reference passed to one of these narrates the failure; it observes nothing. Matched
# by simple callee name (``_call_name``), so `pytest.fail` / `pytest.skip` /
# `pytest.xfail` and any `x.fail(...)` count. A logging call, a `sys.stderr.write`,
# or a message built by concatenation is NOT in this set -- a known, witnessed blind
# spot (see the narration test), not a claim.
_NARRATION_CALLS = frozenset({"print", "fail", "skip", "xfail"})


def _narration_node_ids(stmt: ast.stmt) -> set[int]:
    """The ``id()`` of every node under a narration context in ``stmt``: an assert's
    message expression, a ``raise``'s exception and cause, an f-string assigned to a
    name (a message being built for a later assert), and the arguments of a call in
    ``_NARRATION_CALLS``. An f-string inside an assert's TEST keeps counting: there
    the value is compared, not rendered. ``id()`` keys are safe here because the tree
    outlives the walk that reads them."""
    ids: set[int] = set()
    for n in ast.walk(stmt):
        if isinstance(n, ast.Assert) and n.msg is not None:
            ids.update(id(x) for x in ast.walk(n.msg))
        elif isinstance(n, ast.Raise):
            for part in (n.exc, n.cause):
                if part is not None:
                    ids.update(id(x) for x in ast.walk(part))
        elif (isinstance(n, (ast.Assign, ast.AnnAssign))
                and isinstance(n.value, ast.JoinedStr)):
            ids.update(id(x) for x in ast.walk(n.value))
        elif isinstance(n, ast.Call) and _call_name(n) in _NARRATION_CALLS:
            for arg in (*n.args, *(kw.value for kw in n.keywords)):
                ids.update(id(x) for x in ast.walk(arg))
    return ids


def _observes_decision_channel(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the test genuinely inspects the hook's decision channel: a stdout/stderr
    access, a ``permissionDecision`` string literal in CODE, an audit-log
    ``<event>_blocked`` event token, OR a call to any ``assert_hook_*`` helper (the
    shared discrimination idiom in ``tests/_hook_assertions.py``, which does the
    ``json.loads(stdout)`` + ``permissionDecision`` check itself). Resolving THROUGH that
    helper is essential: it is the dominant idiom, and a body-only walk would otherwise
    false-positive on the very tests that discriminate through it. A bare
    ``result.returncode`` assertion does NOT count.

    Narration does not count either (DEF-312b): a channel reference inside an assert's
    MESSAGE (``assert r.returncode == 0, f"expected deny; got {r.stdout}"``), in a
    ``raise``, in an f-string assigned to a name, or in a ``print()`` /
    ``pytest.fail()`` / ``pytest.skip()`` argument renders the value without ever
    comparing or parsing it, so the test still cannot fail for its stated reason.
    Before this, one such mention anywhere in the body cleared the finding.
    The boundary is deliberately the narration CONTEXT, not "inside an assert subject":
    the dominant live idiom parses stdout into a variable in an assignment and asserts
    on the parsed decision one line later -- measured 2026-09-08, an assert-subject-only
    reading false-positived on five such tests -- so an access outside a narration
    context keeps counting wherever it sits.

    The audit log is a second decision channel: a hook records a
    ``<event>_blocked_<reason>`` entry (e.g. ``pretooluse_blocked_kill_switch``,
    ``configchange_blocked_kill_switch``) ONLY on a block, so a test asserting such an
    event token IS discriminating deny from allow. Matching the underscore-delimited
    ``_blocked`` event-name shape — not a bare prose "blocked" in an assert message,
    which carries a space, not the ``_`` — keeps this on the 0-false-positive side.

    The function docstring is excluded from the scan: a docstring that merely NARRATES
    "denies via permissionDecision=deny" without the code actually checking it must not
    count as a channel observation, else an accurate-sounding but non-discriminating test
    escapes — the same docstring-unreliability that moved ``_has_deny_intent`` to
    name-only."""
    for stmt in _body_without_docstring(node):
        narration = _narration_node_ids(stmt)
        for n in ast.walk(stmt):
            if id(n) in narration:
                continue
            if isinstance(n, ast.Attribute) and n.attr in ("stdout", "stderr"):
                return True
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and "permissionDecision" in n.value):
                return True
            # Audit-log channel: a `<event>_blocked_<reason>` token is recorded ONLY on a
            # block, so asserting it discriminates deny from allow. The underscore-anchored
            # `_blocked` matches the event-name shape without catching a prose "blocked".
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and "_blocked" in n.value):
                return True
            if isinstance(n, ast.Call):
                name = _call_name(n)
                if isinstance(name, str) and name.startswith("assert_hook_"):
                    return True
    return False


def _is_nondiscriminating_hook_deny(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A ``test_*`` whose intent is a hook deny/block but whose only observation is the
    return code — which, under channel-XOR, is identical for allow and deny."""
    return (
        node.name.startswith("test_")
        and _invokes_hook(node)
        and _has_deny_intent(node)
        and _asserts_returncode(node)
        and not _observes_decision_channel(node)
    )


def _has_allow_intent(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The allow-side mirror of ``_has_deny_intent``: True when the test NAME signals an
    allow/permit intent. No deny-negation gate is needed — ``_has_deny_intent`` already
    disqualifies any allow-negation name, so the two arms never fire on the same body."""
    name = node.name.lower()
    return any(kw in name for kw in _ALLOW_INTENT)


def _is_nondiscriminating_hook_allow(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The allow-side mirror of ``_is_nondiscriminating_hook_deny``: an allow-intent
    ``test_*`` that invokes a hook and observes ONLY the return code. Under channel-XOR an
    over-block regression (a legitimate op flipping to a deny) is exit 0 too, so a bare
    ``returncode`` assertion cannot catch it.

    Invoker scope is the same ``_HOOK_INVOKERS`` ({run_hook, _run_hook}) as the deny-arm —
    its calibrated scope. Other hook-invoker helpers in the suite (run_bash_guard,
    run_hook_edit, …) are outside BOTH arms; widening ``_HOOK_INVOKERS`` also shifts the
    deny-arm population, so it is a separate calibration, not this rule."""
    return (
        node.name.startswith("test_")
        and _invokes_hook(node)
        and _has_allow_intent(node)
        and _asserts_returncode(node)
        and not _observes_decision_channel(node)
    )


def scan_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {
            "file": path,
            "syntax_error": str(e),
            "count": 0,
            "findings": [],
        }

    findings: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and _is_tautological_assert(node.test):
            findings.append({
                "rule": "assert_tautological",
                "lineno": node.lineno,
            })

        if isinstance(node, ast.Call) and _is_pytest_skip_call(node):
            if not node.args and not _has_reason_kwarg(node):
                findings.append({
                    "rule": "bare_skip",
                    "lineno": node.lineno,
                })

        # Also inspect async test functions — `@pytest.mark.skip`
        # on an `async def test_x` would otherwise evade the no-reason check.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # A `test_*` function that proves nothing fakes coverage. Scoped to
            # `test_` names so helpers/fixtures don't flag.
            # Two precision gates keep it from double-flagging or false-positiving:
            #   - a body with any `assert` is owned by assert_tautological (if the
            #     assert is vacuous) or already has a real assertion — so requiring
            #     NO assert node confines zero_assertion to its unique niche
            #     (bodies with no assertion at all, e.g. only `print(...)` / `pass`);
            #   - a skip/xfail-decorated test is deliberately inert, so an absent
            #     assertion is expected (missing-reason is skip_no_reason's job).
            if (node.name.startswith("test_")
                    and not _function_has_real_assertion(node)
                    and not any(isinstance(s, ast.Assert) for s in ast.walk(node))
                    and not _has_skip_or_xfail_decorator(node)):
                findings.append({
                    "rule": "zero_assertion",
                    "lineno": node.lineno,
                    "function": node.name,
                })
            # Deny-intent hook test that observes only the return code. Disjoint from
            # zero_assertion by construction — this fires only when the body ASSERTS on
            # `.returncode` (a "real assertion" to the weak zero_assertion predicate),
            # which is exactly the gap that lets a non-discriminating deny test ship
            # green.
            if _is_nondiscriminating_hook_deny(node):
                findings.append({
                    "rule": "nondiscriminating_hook_assert",
                    "lineno": node.lineno,
                    "function": node.name,
                })
            # Allow-side mirror: an allow-intent hook test that observes only the
            # return code cannot catch an over-block flip to deny (also exit 0).
            # Additive and mutually exclusive with the deny arm above.
            if _is_nondiscriminating_hook_allow(node):
                findings.append({
                    "rule": "nondiscriminating_hook_allow",
                    "lineno": node.lineno,
                    "function": node.name,
                })
            for dec in node.decorator_list:
                target = _decorator_target(dec)
                if target == "pytest.mark.skip" and not _has_reason_kwarg(dec):
                    findings.append({
                        "rule": "skip_no_reason",
                        "lineno": dec.lineno,
                        "function": node.name,
                    })
                elif target == "pytest.mark.xfail" and not _has_reason_kwarg(dec):
                    findings.append({
                        "rule": "xfail_no_reason",
                        "lineno": dec.lineno,
                        "function": node.name,
                    })

    return {
        "file": path,
        "count": len(findings),
        "findings": findings,
    }


def scan_repo(root: str, exclude: set[str] | None = None) -> dict[str, Any]:
    """Scan all pytest test files under root for test-loosening patterns."""
    files = iter_test_files(root, exclude)
    files = [
        f for f in files
        if not any(
            os.path.relpath(f, root).replace("\\", "/").startswith(prefix)
            for prefix in EXEMPT_PREFIXES
        )
    ]
    file_reports: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for p in files:
        try:
            file_reports.append(scan_file(p))
        except OSError as e:
            # The path is its own key; the OS reason stands alone, so the
            # record never carries a repr'd path (DEF-799).
            skipped.append({"file": p, "error": e.strerror or type(e).__name__})
    total = sum(r["count"] for r in file_reports)
    hotspots = sorted(
        [r for r in file_reports if r["count"] > 0],
        key=lambda r: r["count"],
        reverse=True,
    )
    by_rule: dict[str, int] = {}
    for r in file_reports:
        for f in r["findings"]:
            by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
    return {
        "root": os.path.abspath(root),
        "files_scanned": len(files),
        "files_with_findings": len(hotspots),
        "skipped": skipped,
        "count": total,
        "by_rule": by_rule,
        "results": hotspots[:30],
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Scan for test-loosening patterns")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="reports/scan_test_loosening.json")
    args = ap.parse_args()

    report = scan_repo(args.root)
    # Guard against flat `--out` paths (no directory
    # component). ``os.path.dirname("flat.json")`` returns ``""``
    # and ``os.makedirs("")`` raises ``FileNotFoundError``.
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(
        f"Scanned {report['files_scanned']} test files: "
        f"{report['count']} loosening findings in {report['files_with_findings']} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
