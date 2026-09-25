"""``bare_skip`` rule fires only on dotted ``pytest.skip(...)``,
never on bare ``skip(...)`` or aliased imports.

Pins the precision of ``_is_pytest_skip_call``: pre-fix, the predicate
accepted both the dotted ``pytest.skip`` form AND the bare name
``skip``. Test files that import ``from contextlib import suppress as
skip`` or define a local ``def skip()`` helper triggered the
``bare_skip`` rule spuriously. Scanner scope is limited to
``tests/test_*.py``, which narrows but does not eliminate the
false-positive surface.

Failure mode prevented: a future refactor relaxes the predicate
back to substring / membership form, re-introducing bare-name
matching. The four assertions below trip the moment that happens.
The final test exercises ``scan_file`` end-to-end against a real
positional-arg ``pytest.skip("reason")`` to pin the "positional
reason is fine" carve-out (the original rule already exempts it via
``not node.args and not _has_reason_kwarg(node)``; this contract
catches a refactor that removes either side of the conjunction).
"""
import ast
import os
import tempfile

from espalier.scanners.test_loosening import (
    _has_reason_kwarg,
    _is_pytest_skip_call,
    scan_file,
)


def _decorator_call(src: str) -> ast.Call:
    """Parse a single decorator expression like ``pytest.mark.skip("x")``."""
    tree = ast.parse(src, mode="eval")
    assert isinstance(tree.body, ast.Call)
    return tree.body


def _scan_src(src: str) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        return scan_file(path).get("findings", [])
    finally:
        os.unlink(path)


def test_has_reason_kwarg_accepts_positional_string():
    """a non-empty positional string IS a valid pytest reason."""
    assert _has_reason_kwarg(_decorator_call('pytest.mark.skip("env not ready")'))


def test_has_reason_kwarg_still_accepts_keyword():
    """The original ``reason=`` keyword path must keep working."""
    assert _has_reason_kwarg(_decorator_call('pytest.mark.skip(reason="x")'))


def test_has_reason_kwarg_rejects_empty_and_missing():
    """Negative control — do not over-widen. A genuinely reasonless marker
    (no args, or a whitespace-only positional) must still report no reason."""
    assert not _has_reason_kwarg(_decorator_call("pytest.mark.skip()"))
    assert not _has_reason_kwarg(_decorator_call('pytest.mark.skip("   ")'))


def test_skip_decorator_with_positional_reason_not_flagged():
    """earn-the-red: ``@pytest.mark.skip("reason")`` (positional)
    was wrongly flagged ``skip_no_reason`` because ``_has_reason_kwarg`` only
    looked at keywords. After the fix it is clean."""
    findings = _scan_src(
        "import pytest\n"
        "\n"
        '@pytest.mark.skip("env not ready on CI")\n'
        "def test_foo():\n"
        "    pass\n"
    )
    assert not [r for r in findings if r.get("rule") == "skip_no_reason"]


def test_skip_decorator_without_reason_still_flagged():
    """Negative control end-to-end: a truly reasonless decorator still trips."""
    findings = _scan_src(
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_bar():\n"
        "    pass\n"
    )
    assert [r for r in findings if r.get("rule") == "skip_no_reason"]


def _call(src: str) -> ast.Call:
    tree = ast.parse(src, mode="eval")
    assert isinstance(tree.body, ast.Call)
    return tree.body


def test_pytest_skip_dotted_matches():
    assert _is_pytest_skip_call(_call("pytest.skip('reason')"))


def test_bare_skip_does_not_match():
    """``skip(...)`` could be a user-defined helper or aliased
    ``suppress as skip``. Without dotted module, do not flag."""
    assert not _is_pytest_skip_call(_call("skip('reason')"))


def test_unrelated_attribute_does_not_match():
    assert not _is_pytest_skip_call(_call("foo.skip('reason')"))
    assert not _is_pytest_skip_call(_call("self.skip('reason')"))


def test_pytest_skip_with_positional_reason_does_not_fire_bare_skip():
    """Empirical gap: the ``bare_skip`` rule should NOT fire on
    ``pytest.skip("reason")`` — a positional reason is fine.

    The check is ``not node.args and not _has_reason_kwarg(node)``;
    positional args satisfy ``node.args``, so the rule correctly
    exempts. Pinning this catches a future refactor that drops
    ``not node.args`` from the conjunction.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(
            "import pytest\n"
            "\n"
            "def test_foo():\n"
            "    pytest.skip('env not ready')\n"
        )
        path = f.name
    try:
        report = scan_file(path)
        bare_skips = [
            r for r in report.get("findings", [])
            if r.get("rule") == "bare_skip"
        ]
        assert not bare_skips, (
            "bare_skip rule fired on pytest.skip('reason') positional "
            f"form: {bare_skips}"
        )
    finally:
        os.unlink(path)
