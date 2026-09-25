"""Static quality scanner for the test suite itself.

Catches `assert True`, `assert 1 == 1`, and equivalent trivial-body tests
that pass without proving anything. Each was a real footgun: such tests
read as passing in CI while silently testing nothing.

Allowed exception: a test with no assertion may still be valid if it
performs a side effect that can raise (e.g., `pytest.raises`, `pytest.warns`,
or simply `_ = module.some_symbol` so import drift surfaces). The scanner
recognizes these via AST inspection.
"""
from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

_TRIVIAL_ASSERT_TEXTS = ("assert True", "assert 1 == 1", "assert 1")

# Builtin calls that cannot meaningfully raise on their declared inputs and
# therefore do NOT count as "absence-of-exception is the proof." A test body
# whose only side effect is `print(...)` or `len(x)` is a fake test.
_TRIVIAL_BUILTIN_CALLS = frozenset({
    "print", "len", "str", "repr", "type", "id",
    "isinstance", "hasattr", "getattr", "callable",
    "tuple", "list", "dict", "set", "bool", "int", "float",
})


def _walk_test_functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # DR7 round-7: include AsyncFunctionDef. The production scanners
        # (espalier/scanners/test_loosening.py et al.) already handle async;
        # this meta-guard for espalier's OWN suite did not, so an
        # `async def test_x(): assert True` evaded the very anti-vacuity check
        # that exists to catch it.
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")):
            yield node


def _is_trivial_builtin_call(call: ast.Call) -> bool:
    """True when `call.func` is a bare reference to a known no-raise builtin.

    `print("hi")` is `Call(func=Name("print"))` — trivial. `json.loads(...)`
    is `Call(func=Attribute(...))` — non-trivial (any attribute call could
    raise). `clean_generated_surface(...)` is `Call(func=Name("clean_..."))`
    — non-trivial because the name isn't on the builtin allowlist.
    """
    func = call.func
    return isinstance(func, ast.Name) and func.id in _TRIVIAL_BUILTIN_CALLS


def _is_self_comparison(test: ast.expr) -> bool:
    """True for a tautological self-comparison: `x == x` / `x is x` (and any
    structurally-identical operand pair). These pass unconditionally and prove
    nothing, yet read as a 'real' assertion to the text-based trivial filter —
    `assert x == x` is not in _TRIVIAL_ASSERT_TEXTS. AST-equality of the two
    operands is the reliable detector.

    Known gap (deliberate, TP-225-C): `assert <var> is not None` as a body's
    ONLY assertion is NOT flagged. It is a weak-but-real assertion, not a
    tautology — mechanically sized at exactly two legitimate occurrences in
    this suite (a ReDoS still-matches pin and an import smoke), so gating it
    would false-positive on correct tests. A weak assertion is a smell, not a
    vacuity; that distinction is intentional.
    """
    if not (isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Eq, ast.Is))):
        return False
    return ast.dump(test.left) == ast.dump(test.comparators[0])


class _BlankStringLiterals(ast.NodeTransformer):
    """Replace every string constant with an empty one, in place of its text."""

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value=""), node)
        return node


def _assert_text_without_string_literals(stmt: ast.Assert) -> str:
    """Unparse an assert with every string literal blanked out.

    The trivial-assert filter below is a substring test over unparsed source,
    and a substring test cannot tell a USE from a MENTION. A test whose FIXTURE
    is a snippet of Python -- ``_module_spawns_child("def test_x(): assert 1 + 1 == 2")``
    -- carries the characters ``assert 1`` inside a string, and the filter read
    that as the test's own trivial assertion and reported a real, well-asserted
    test as a pass-through. Measured 2026-08-24 against
    tests/test_test_suite_contract.py::TestSubprocessDetector.

    Blanking the string constants first asks about the assertion the test
    actually makes. It can only ever REDUCE the trivial set, never widen it:
    none of the genuinely trivial forms (``assert True``, ``assert 1 == 1``,
    ``assert 1``) contains a string literal, so nothing real stops being caught.

    This is the same mention-versus-use shape the Bash guards, the
    retired-vocab scanner, the bench overclaim gate and the marker opt-out
    check each paid for separately. The lesson has now cost five detectors:
    when a guard fires on text that is *about* the thing rather than *is* the
    thing, the fix is to ask the parser for the role, never `in` for the
    spelling.
    """
    clone = _BlankStringLiterals().visit(copy.deepcopy(stmt))
    return ast.unparse(clone)


def _function_has_real_assertion(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A function counts as a real test if any of these hold:

    - It contains a non-trivial assert (anything not in _TRIVIAL_ASSERT_TEXTS).
    - It raises explicitly.
    - It contains an expression-statement function call that could
      meaningfully raise (e.g. `json.loads(x)`, `subprocess.run(...)`,
      `module.do_thing()`, or any non-builtin call). Bare builtin calls
      like `print(...)` or `len(x)` are filtered out — those cannot raise
      on their declared signature and so do not constitute a proof.
    - It uses `with pytest.raises(...)` or a similar non-trivial context
      manager call.
    """
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Assert):
            assert_text = _assert_text_without_string_literals(stmt)
            is_trivial_text = any(t in assert_text for t in _TRIVIAL_ASSERT_TEXTS)
            # TP-225-C: a self-comparison (`assert x == x`) is a tautology the
            # text filter misses — it passes unconditionally. Treat it as
            # trivial so it cannot stand in for a real proof.
            if not is_trivial_text and not _is_self_comparison(stmt.test):
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


class TestTheTrivialAssertFilterReadsRoleNotSpelling:
    """Calibration for ``_assert_text_without_string_literals``.

    Both verdicts, because a filter that stopped detecting anything would make
    ``test_no_pass_through_tests`` pass vacuously forever.
    """

    def _fn(self, src: str) -> ast.FunctionDef:
        return ast.parse(src).body[0]

    def test_a_trivial_pattern_inside_a_string_fixture_is_not_the_assertion(self):
        fn = self._fn(
            "def test_x():\n"
            "    assert not detect('def test_y(): assert 1 + 1 == 2')\n"
        )
        assert _function_has_real_assertion(fn)

    def test_a_genuinely_trivial_assert_is_still_caught(self):
        assert not _function_has_real_assertion(self._fn("def test_x():\n    assert True\n"))
        assert not _function_has_real_assertion(self._fn("def test_x():\n    assert 1 == 1\n"))

    def test_a_docstring_mentioning_assert_true_does_not_rescue_an_empty_test(self):
        fn = self._fn('def test_x():\n    """We used to assert True here."""\n    pass\n')
        assert not _function_has_real_assertion(fn)


def test_no_pass_through_tests():
    """No test function may exist purely as `assert True` / trivial body.

    A test that doesn't assert anything is worse than no test — it
    creates the *appearance* of coverage. If you genuinely need a
    placeholder (e.g., importable smoke check), reference a symbol so
    the absence of failure proves something:

        def test_module_imports():
            from mypkg import some_symbol
            _ = some_symbol  # absence of NameError is the proof
    """
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == "test_test_quality.py":
            continue
        for fn in _walk_test_functions(path):
            if not _function_has_real_assertion(fn):
                offenders.append(f"{path.name}::{fn.name}")
    assert not offenders, (
        "Tests with no real assertion (only `assert True`, `pass`, "
        "or trivial bodies):\n"
        + "\n".join(f"  - {o}" for o in offenders)
    )


def test_walk_catches_async_vacuous_tests(tmp_path):
    """DR7 round-7 earn-the-red: the meta-guard must inspect `async def
    test_*` too. Before the AsyncFunctionDef fix, `_walk_test_functions`
    yielded nothing for an async test, so a vacuous `async def test_x():
    assert True` silently evaded `test_no_pass_through_tests`. Pins both
    halves: the walker yields the async function AND it is judged vacuous.
    """
    f = tmp_path / "test_async_sample.py"
    f.write_text(
        "import pytest\n"
        "async def test_real():\n"
        "    assert compute() == 3\n"
        "async def test_vacuous():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    walked = {fn.name: fn for fn in _walk_test_functions(f)}
    assert set(walked) == {"test_real", "test_vacuous"}, (
        f"async test functions were not walked: {sorted(walked)}"
    )
    assert _function_has_real_assertion(walked["test_real"])
    assert not _function_has_real_assertion(walked["test_vacuous"])


def test_self_comparison_is_vacuous(tmp_path):
    """TP-225-C earn-the-red: `assert x == x` is a tautology the static-text
    trivial filter does not catch (it is not in _TRIVIAL_ASSERT_TEXTS), so
    pre-TP-225 a self-comparison body read as a 'real' assertion and evaded
    test_no_pass_through_tests. Pins both halves: the self-comparison body is
    judged vacuous AND a genuine comparison is still judged real.
    """
    f = tmp_path / "test_selfcmp_sample.py"
    f.write_text(
        "def test_vacuous():\n"
        "    x = compute()\n"
        "    assert x == x\n"
        "def test_real():\n"
        "    assert compute() == 3\n",
        encoding="utf-8",
    )
    fns = {fn.name: fn for fn in _walk_test_functions(f)}
    assert not _function_has_real_assertion(fns["test_vacuous"]), (
        "self-comparison `assert x == x` must be judged vacuous"
    )
    assert _function_has_real_assertion(fns["test_real"])


def test_async_await_bodies_are_real(tmp_path):
    """TP-266 Fix 2 (sister-site lockstep): this vacuity meta-guard shares
    `scanners/test_loosening`'s async-blind block. An `async def test_x():
    await call()` body — or `async with ctx(): await c.go()` — is a real test,
    but pre-fix `_function_has_real_assertion` matched only `ast.Expr(ast.Call)`
    and `ast.With`, missing the `ast.Await` wrapper and its `ast.AsyncWith` twin,
    so such a test read as a pass-through. RED before / GREEN after; fixed in
    lockstep with the scanner copy (see test_state_transitions.py's note on
    the same async-blind walk being fixed across sister sites)."""
    f = tmp_path / "test_async_real_sample.py"
    f.write_text(
        "async def test_await_call():\n    await client.post('/x')\n"
        "async def test_async_with():\n    async with ctx() as c:\n        await c.go()\n"
        "async def test_vacuous():\n    pass\n",
        encoding="utf-8",
    )
    fns = {fn.name: fn for fn in _walk_test_functions(f)}
    assert _function_has_real_assertion(fns["test_await_call"])
    assert _function_has_real_assertion(fns["test_async_with"])
    assert not _function_has_real_assertion(fns["test_vacuous"])


# ── Contract-test rationale (TP-106) ────────────────────────────────────────
#
# Every contract test file must explain WHY it exists in its module
# docstring, not just WHAT it tests. The rationale must be readable
# from the file alone — no external pack/issue/commit reference required
# because the test file is shipped in release artifacts while task packs
# are gitignored.
#
# The 77-file grandfather set below is the pre-TP-106 backlog. It shrinks
# to frozenset() as the backfill lands. New test files added after this
# contract MUST author a substantive docstring; the grandfather slot is
# closed.

RATIONALE_ANCHORS = re.compile(
    r"\b(pins?|prevent[s]?|guards?|invariant|regression|drift|"
    r"failure\s*(mode|shape)|without\s+this|would\s+(break|fail)|"
    r"because|bug\s+class|must\s+satisfy|this\s+test\s+exists|"
    r"this\s+contract|ensures?|catch(es)?|motivated|silent(ly)?|"
    r"bypass(es|ed)?|divergence|surfaced|incident|reproduces|"
    r"(class|kind)\s+of\s+(bug|drift|error)|the\s+moment)\b",
    re.IGNORECASE,
)

MIN_RATIONALE_LINES = 3

GRANDFATHERED_NO_RATIONALE: frozenset[str] = frozenset()
# Two-wave TP-106 backfill complete (2026-05-24):
#   Wave 1 — 31 "too short docstring" files re-authored from scratch.
#   Wave 2 — 41 "has docstring, no anchor" files augmented with
#            rationale-anchor sentences (pins / prevents / silently /
#            without this contract / failure mode / etc.).
# Steady state: zero grandfathered files; every new test file must
# ship a rationale-bearing docstring or the contract fires
# immediately. The empty frozenset is the convention's strongest
# form — re-adding an entry requires conscious justification in the
# diff that introduces it.


class TestContractRationale:
    """Every test file's module docstring must explain WHY the contract
    exists, not just WHAT it tests. The rationale must be readable from
    the file alone — release artifacts include the test file but never
    the originating task pack.

    Two mechanical checks:
      1. Module docstring has >=3 non-empty content lines.
      2. Docstring contains at least one rationale anchor word.

    The anchor lexicon is intentionally narrow (~25 tokens) to keep
    the contract semantic, not just lexical. Extend only via explicit
    pack — drift toward permissiveness defeats the contract.

    Failure mode: pre-this-contract, ~45% of test files had pure-WHAT
    docstrings ("Tests for module X"). Future contributors hitting
    a red test had no in-file context for what the test pinned or
    what would break without it. OSS adopters had even less because
    the task packs were gitignored at the time (the active ones ship since 2026-09-21).
    """

    def test_every_file_has_rationale_docstring(self):
        violations = []
        for f in sorted(TESTS_DIR.glob("test_*.py")):
            if f.name in GRANDFATHERED_NO_RATIONALE:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            doc = ast.get_docstring(tree)
            if not doc:
                violations.append(f"{f.name}: no module docstring")
                continue
            lines = [l for l in doc.split("\n") if l.strip()]
            if len(lines) < MIN_RATIONALE_LINES:
                violations.append(
                    f"{f.name}: docstring has {len(lines)} non-empty "
                    f"lines, need >={MIN_RATIONALE_LINES}"
                )
                continue
            if not RATIONALE_ANCHORS.search(doc):
                violations.append(
                    f"{f.name}: docstring lacks any rationale anchor "
                    f"(pins/prevents/guards/drift/because/...)"
                )
        assert not violations, (
            "Contract test files must self-describe their rationale. "
            "Either revise the docstring to explain what the test "
            "pins + why, or grandfather in GRANDFATHERED_NO_RATIONALE "
            "with an explanatory comment.\n"
            + "\n".join(violations)
        )
