"""A corpus attempt's declared ``env`` must reach the hook subprocess.

``bench/run_benchmark.py::_invoke_hook_stdin`` pops ``ESPALIER_MAINTENANCE_MODE``
from the child environment on purpose: the bench measures ENFORCEMENT, and
CLAUDE.md actively recommends developing in a maintenance-mode shell, so an
ambient var would false-ALLOW every protected-zone attempt and false-FAIL the
100%-blocked gate. That strip is correct and this module pins it.

What the strip must NOT do is swallow an env a corpus attempt DECLARES.
``BC-011-maintenance-mode-scope`` exists to catch ``write_guard.main()``
short-circuiting via the maintenance bypass BEFORE the kill-switch and
dangerous-pattern gates. Attempts ``a1``/``a2`` declare
``ESPALIER_MAINTENANCE_MODE=1`` and route through ``write_guard_pretooluse``
-> ``invoke_real_write_guard`` -> ``_invoke_hook_stdin``, where the declaration
was dropped. They therefore ran with maintenance OFF, where ``rm -rf /`` is
refused by the dangerous-pattern check anyway -- so the row PASSED for a reason
unrelated to its contract and could not fail for the one it exists for.
Mutation-proven: hoisting write_guard's maintenance early-return above the
kill-switch + dangerous-pattern gates leaves ``a1``/``a2`` reporting ``blocked``
on the pre-fix path, and correctly reports ``allowed`` once the declared env is
honoured. FAILURE_MODES.md §5.10 (validation-ritual presence vs firing): the
verifier was wired, named correctly, and inert.

WHERE THE PIN HAS TO SIT, learned the hard way. A first cut of this module
tested ``_invoke_hook_stdin`` directly and was itself inert: reverting BOTH call
sites (``invoke_real_write_guard``/``invoke_naive_guard``) back to the 3-arg
form restored the original defect with every test green, because pinning the
PARAMETER does not pin the WIRING. The load-bearing tests here therefore drive
the real invokers end-to-end against a probe hook, and derive the honouring set
from the runner's AST rather than a hand-kept name list (§14: derive the list,
don't test a hand-written copy of it).
"""
# slow-exempt: the only child processes are ~3-line probe scripts written to
# tmp_path; the whole module runs in ~0.2s. Parking it in _SLOW_FILES would
# drop it from the `-m "not slow"` PR slice, which is exactly where a cheap
# wiring contract earns its keep.
from __future__ import annotations

import ast
import json
from pathlib import Path

import bench.run_benchmark as rb
from tests.test_bench_corpus_wiring_parity import _espalier_wiring

ENV_VAR = "ESPALIER_MAINTENANCE_MODE"
# A var the harness itself never reads, so "the mechanism is general" is tested
# rather than asserted. A first cut used ENV_VAR here and a mutant special-cased
# on that one name passed.
SENTINEL_VAR = "ESPALIER_BENCH_PROBE_SENTINEL"

CORPUS_DIR = Path(rb.__file__).resolve().parent / "corpus"
RUNNER_SRC = Path(rb.__file__).resolve()

# Invokers that legitimately build their own env instead of routing through
# _invoke_hook_stdin. Explicit receipt, not a silent exemption: each must be
# shown below to actually apply the attempt's env.
_OWN_ENV_INVOKERS = {"invoke_killswitch_under_maintenance"}

# Attempts allowed to declare an env the runner never applies. An out-of-scope
# row must EARN this by also being expected-allowed; the allowlist means a NEW
# reclassification has to be declared here, not merely performed in the corpus.
_EXEMPT_ATTEMPTS = {"BC-OOS-006-a1"}

_PROBE = (
    "import json, os, sys\n"
    "seen = {k: os.environ.get(k) for k in (%r, %r)}\n"
    "sys.stdout.write(json.dumps({'hookSpecificOutput': {\n"
    "    'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',\n"
    "    'permissionDecisionReason': json.dumps(seen)}}))\n"
) % (ENV_VAR, SENTINEL_VAR)


def _probe_script(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_PROBE, encoding="utf-8")
    return path


def _seen_via_helper(tmp_path, attempt_env, monkeypatch, ambient=None):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.delenv(SENTINEL_VAR, raising=False)
    if ambient is not None:
        monkeypatch.setenv(ENV_VAR, ambient)
    rc, stdout, _ = rb._invoke_hook_stdin(
        _probe_script(tmp_path / "probe.py"),
        {"tool_name": "Bash", "tool_input": {}}, tmp_path, attempt_env,
    )
    assert rc == 0, f"probe failed rc={rc}: {stdout!r}"
    return json.loads(json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"])


def _corpus_docs() -> dict[Path, dict]:
    return {p: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CORPUS_DIR.glob("*.json"))}


# ── the wiring pins (these are the ones that catch a call-site revert) ────────

def test_invoke_real_write_guard_forwards_the_declared_env(tmp_path, monkeypatch):
    """END-TO-END through the real invoker. Reverting bench/run_benchmark.py's
    `invoke_real_write_guard` call site to the 3-arg form must RED this."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(rb, "HOOK_SCRIPT", _probe_script(tmp_path / "hook.py"))
    result = rb.invoke_real_write_guard(
        {"tool_name": "Bash", "tool_input": {}, "env": {ENV_VAR: "1"}}, tmp_path
    )
    assert result.blocked, "probe hook did not deny — invoker did not run it"
    assert json.loads(result.reason)[ENV_VAR] == "1", (
        "invoke_real_write_guard dropped the attempt's declared env — the corpus "
        "row declares a condition the runner never sets, so it cannot fail for "
        "the reason it exists (FAILURE_MODES.md §5.10)"
    )


def test_invoke_naive_guard_forwards_the_declared_env(tmp_path, monkeypatch):
    """The baseline must face identical conditions, or the comparison the
    benchmark publishes is not apples-to-apples."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    _probe_script(tmp_path / ".claude" / "hooks" / "naive_guard.py")
    result = rb.invoke_naive_guard(
        {"tool_name": "Bash", "tool_input": {}, "env": {ENV_VAR: "1"}}, tmp_path
    )
    assert result.blocked and json.loads(result.reason)[ENV_VAR] == "1"


def test_every_invoker_wired_for_an_env_declaring_attempt_forwards_it():
    """Derive, don't hand-maintain (§14). AST-resolve each in-scope
    env-declaring attempt's verifier through BASELINE_INVOKERS["espalier"] to an
    invoker function, then require that function either forwards a 4th argument
    to _invoke_hook_stdin or is a declared own-env builder."""
    tree = ast.parse(RUNNER_SRC.read_text(encoding="utf-8"))
    forwarding = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)
            and c.func.id == "_invoke_hook_stdin"
            and (len(c.args) >= 4 or any(k.arg == "attempt_env" for k in c.keywords))
            for c in ast.walk(fn)
        )
    }
    assert forwarding, "AST derivation found no forwarding invoker — parse broke"

    wiring = _espalier_wiring()
    docs = _corpus_docs()
    declaring = [
        (a.get("attempt_id", "?"), a.get("verifier", "?"))
        for d in docs.values() if d.get("in_scope")
        for a in d.get("canonical_attempts", []) if a.get("env")
    ]
    assert declaring, "no in-scope attempt declares an env — derivation is vacuous"

    bad = [
        (aid, v) for aid, v in declaring
        if wiring.get(v) not in forwarding | _OWN_ENV_INVOKERS
    ]
    assert not bad, (
        f"in-scope attempts declare an env but resolve to an invoker that drops it: "
        f"{bad}. espalier wiring={ {v: wiring.get(v) for _, v in declaring} }; "
        f"forwarding invokers={sorted(forwarding)}. Either forward attempt_env to "
        f"_invoke_hook_stdin from that invoker, or drop the declaration so the "
        f"corpus does not imply a condition it never sets."
    )


def test_own_env_invokers_really_do_apply_the_attempt_env(tmp_path, monkeypatch):
    """_OWN_ENV_INVOKERS is a receipt, not a hall pass — prove each member."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(rb, "HOOK_SCRIPT", _probe_script(tmp_path / "hook.py"))
    result = rb.invoke_killswitch_under_maintenance(
        {"tool_name": "Write", "tool_input": {"file_path": "x.txt", "content": "x"},
         "env": {ENV_VAR: "1"}}, tmp_path
    )
    assert json.loads(result.reason)[ENV_VAR] == "1"


# ── the helper-level pins (ordering + the ambient strip) ─────────────────────

def test_declared_attempt_env_reaches_the_hook(tmp_path, monkeypatch):
    assert _seen_via_helper(tmp_path, {ENV_VAR: "1"}, monkeypatch)[ENV_VAR] == "1"


def test_ambient_maintenance_mode_is_still_stripped(tmp_path, monkeypatch):
    """The documented protection must survive the fix: a developer's shell must
    NOT opt the corpus into maintenance mode."""
    assert _seen_via_helper(tmp_path, None, monkeypatch, ambient="1")[ENV_VAR] is None


def test_declared_env_overrides_the_ambient_strip(tmp_path, monkeypatch):
    """Ordering: strip ambient FIRST, then apply declared."""
    assert _seen_via_helper(tmp_path, {ENV_VAR: "1"}, monkeypatch, ambient="1")[ENV_VAR] == "1"


def test_mechanism_is_not_special_cased_on_the_harness_var(tmp_path, monkeypatch):
    """A var the harness never reads must travel too, or the loop has been
    narrowed to one name and the general contract is unpinned."""
    seen = _seen_via_helper(tmp_path, {SENTINEL_VAR: "travelled"}, monkeypatch)
    assert seen[SENTINEL_VAR] == "travelled"


# ── the corpus-side witness ─────────────────────────────────────────────────

def test_exempt_env_declaring_attempts_are_declared_and_expected_allowed():
    """An out-of-scope row may declare an env the runner ignores, but must EARN
    it: named in _EXEMPT_ATTEMPTS and expected_outcome=allowed. Blocks the dodge
    of silently flipping in_scope to escape the wiring contract above."""
    docs = _corpus_docs()
    exempt = [
        (a.get("attempt_id", "?"), a.get("expected_outcome"))
        for d in docs.values() if not d.get("in_scope")
        for a in d.get("canonical_attempts", []) if a.get("env")
    ]
    for attempt_id, expected in exempt:
        assert attempt_id in _EXEMPT_ATTEMPTS, (
            f"{attempt_id} declares an env, is out-of-scope, and is not in "
            f"_EXEMPT_ATTEMPTS. If the rescope is deliberate, add it here with a "
            f"reason; if not, the row lost its in_scope status by accident."
        )
        assert expected == "allowed", (
            f"{attempt_id} is out-of-scope but expected_outcome={expected!r}; "
            f"in_scope:false alone is not a licence to declare an env the runner "
            f"then ignores."
        )
    assert set(_EXEMPT_ATTEMPTS) == {a for a, _ in exempt}, (
        f"_EXEMPT_ATTEMPTS is stale: declared {_EXEMPT_ATTEMPTS}, corpus has "
        f"{ {a for a, _ in exempt} }. Remove entries whose row no longer declares "
        f"an env so the allowlist cannot outlive its reason."
    )
