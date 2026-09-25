"""Pin the test_loosening scanner's behavioral contract.

Earn-the-gate: every documented `rule` (assert_tautological / bare_skip /
skip_no_reason / xfail_no_reason) surfaces from the fixture.
Live-scan exemption: EXEMPT_PREFIXES keeps the fixture out of normal
`espalier scan test_loosening` runs.

TP-105 / TP-143 / FM-7 §1.7 close.
"""
from __future__ import annotations

from pathlib import Path

from espalier.scanners import test_loosening as scn


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_test_loosening_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_test_loosening_negatives.py"


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """scan_file the fixture directly; assert every documented rule
    appears at least once in the findings."""
    result = scn.scan_file(str(FIXTURE_PATH))
    rules_seen = {f["rule"] for f in result["findings"]}
    expected_rules = {
        "assert_tautological",
        "bare_skip",
        "skip_no_reason",
        "xfail_no_reason",
    }
    missing = expected_rules - rules_seen
    assert not missing, (
        f"earn-the-gate: scanner failed to detect rules {missing}. "
        f"Found: {rules_seen}."
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: scan_file the negatives fixture directly; assert
    the scanner reports ZERO findings on clean-but-tempting constructs.

    The positives fixture proves the scanner FIRES; this proves it
    STAYS SILENT on legitimate near-boundary shapes (asserts over
    runtime values, skips/xfails WITH reasons)."""
    result = scn.scan_file(str(NEG_FIXTURE_PATH))
    assert result["findings"] == [], (
        f"negatives corpus tripped the scanner; expected zero findings, "
        f"got: {result['findings']}."
    )


def test_fixture_skipped_by_live_scan() -> None:
    """EXEMPT_PREFIXES added in TP-143 must keep the fixture out of
    live scans."""
    report = scn.scan_repo(str(REPO_ROOT))
    fixture_rel = "tests/fixtures/test_test_loosening_positives.py"
    fixture_rows = [
        r for r in report["results"]
        if fixture_rel in r["file"].replace("\\", "/")
    ]
    assert fixture_rows == [], (
        f"EXEMPT_PREFIXES did not skip the fixture; found "
        f"{len(fixture_rows)} per-file row(s) in scan_repo results."
    )


def test_detects_always_true_tuple_assert(tmp_path) -> None:
    """TP-200 (R9-SCAN-1): `assert (cond, "msg")` is a non-empty tuple literal
    — always truthy (CPython warns "assertion is always true"). It is the
    canonical pytest test-vacuity footgun, and the scanner's whole job is
    catching landed test-loosening artifacts, so it must surface.

    Written to a tmp file (not the shared positives fixture) so the always-true
    literal does not trigger a SyntaxWarning when pytest imports the fixture."""
    src = "def shape_tuple():\n    assert (1 == 2, 'msg')\n"
    p = tmp_path / "test_tuple_assert_fixture.py"
    p.write_text(src, encoding="utf-8")
    # earn-the-red: pre-fix _is_tautological_assert ignored ast.Tuple -> 0 findings.
    rules = {f["rule"] for f in scn.scan_file(str(p))["findings"]}
    assert "assert_tautological" in rules, (
        f"scanner missed the always-true tuple assert; found rules {rules}"
    )


def test_does_not_flag_empty_or_value_collection_asserts(tmp_path) -> None:
    """Must-NOT-trip: an EMPTY collection literal is falsy (an always-FAIL, a
    different bug); an assert over a runtime collection value is legitimate; and
    a literal whose elements are EXCLUSIVELY unpacks (`[*xs]` / `{*xs}` /
    `{**ys}`) is falsy when the operand is empty — none is a parse-time
    tautology (TP-200 adversarial pass: the starred/unpack false-positive)."""
    src = (
        "def shape_empty_tuple():\n    assert ()\n"
        "def shape_runtime_list(xs):\n    assert [x for x in xs]\n"
        "def shape_starred_list(xs):\n    assert [*xs]\n"
        "def shape_starred_set(xs):\n    assert {*xs}\n"
        "def shape_doublestar_dict(ys):\n    assert {**ys}\n"
    )
    p = tmp_path / "test_negatives_fixture.py"
    p.write_text(src, encoding="utf-8")
    rules = [f["rule"] for f in scn.scan_file(str(p))["findings"]]
    assert "assert_tautological" not in rules, (
        f"scanner false-positived on a non-tautological assert; rules {rules}"
    )


def test_zero_assertion_fires_on_proofless_test_and_not_on_real_ones(tmp_path) -> None:
    """TP-226b (TQ-adopter-3) earn-the-red: a `test_*` function whose body proves
    nothing (`print("hi")` / `pass`) must yield a `zero_assertion` finding; a body
    with a real assert / `pytest.raises` / non-builtin call must NOT.

    Pre-fix HEAD has no `zero_assertion` rule, so the positive assertion goes RED
    on a `git stash` of Fix 1 and GREEN with it. Written to tmp files (not the
    shared positives fixture) so the vacuous `test_`-prefixed bodies are neither
    pytest-collected nor scanned by live `espalier scan` runs."""
    positive = (
        "def test_only_print():\n    print('hi')\n"
        "def test_only_pass():\n    pass\n"
    )
    p = tmp_path / "test_zero_assertion_positives_fixture.py"
    p.write_text(positive, encoding="utf-8")
    za = [f for f in scn.scan_file(str(p))["findings"] if f["rule"] == "zero_assertion"]
    flagged = {f["function"] for f in za}
    assert flagged == {"test_only_print", "test_only_pass"}, (
        f"zero_assertion missed a proofless test; flagged {flagged}"
    )

    negatives = (
        "import pytest\n"
        "def test_real_assert():\n    assert compute() == 3\n"
        "def test_raises():\n    with pytest.raises(ValueError):\n        boom()\n"
        "def test_nonbuiltin_call():\n    do_real_work()\n"
        "def helper_not_a_test():\n    print('hi')\n"
    )
    n = tmp_path / "test_zero_assertion_negatives_fixture.py"
    n.write_text(negatives, encoding="utf-8")
    neg_rules = [f["rule"] for f in scn.scan_file(str(n))["findings"]]
    assert "zero_assertion" not in neg_rules, (
        f"zero_assertion false-positived on a real test; rules {neg_rules}"
    )


def test_zero_assertion_does_not_double_flag_or_flag_skipped(tmp_path) -> None:
    """Precision gates: a tautological-assert body is owned by assert_tautological
    alone (no zero_assertion double-flag, so `findings[0]` ordering and counts the
    other rules pin stay intact), and a skip/xfail-decorated test is deliberately
    inert (an absent assertion there is expected, owned by skip_no_reason)."""
    src = (
        "import pytest\n"
        "def test_taut():\n    assert True\n"
        "@pytest.mark.skip\n"
        "def test_skipped():\n    pass\n"
        "@pytest.mark.xfail\n"
        "def test_xfailed():\n    pass\n"
    )
    p = tmp_path / "test_zero_assertion_precision_fixture.py"
    p.write_text(src, encoding="utf-8")
    rules = [f["rule"] for f in scn.scan_file(str(p))["findings"]]
    assert "zero_assertion" not in rules, (
        f"zero_assertion double-flagged a tautological/skipped body; rules {rules}"
    )


def test_zero_assertion_recognizes_async_call_bodies(tmp_path) -> None:
    """TP-266 Fix 2 earn-the-red: an `async def test_*` whose proof is an
    `await call()` expression statement — or an `async with ctx(): await c.go()`
    body — is a REAL test, not a proofless one. Pre-fix
    `_function_has_real_assertion` matched only `ast.Expr(ast.Call)` and `ast.With`,
    so the `ast.Await` wrapper and its `ast.AsyncWith` twin were missed and the
    scanner false-flagged both shapes as `zero_assertion` over an adopter's async
    test suite. RED before the fix (both flagged), GREEN after (neither).
    A genuinely-proofless async body must STILL flag — the precision gate."""
    real_async = (
        "async def test_await_call():\n    await client.post('/x')\n"
        "async def test_async_with():\n    async with ctx() as c:\n        await c.go()\n"
    )
    p = tmp_path / "test_async_real_fixture.py"
    p.write_text(real_async, encoding="utf-8")
    za = {
        f["function"]
        for f in scn.scan_file(str(p))["findings"]
        if f["rule"] == "zero_assertion"
    }
    assert za == set(), (
        f"await / async-with bodies wrongly flagged zero_assertion: {za}"
    )

    # Precision: a proofless async body (only a trivial builtin call) still flags.
    vacuous_async = "async def test_only_builtin():\n    len([])\n"
    v = tmp_path / "test_async_vacuous_fixture.py"
    v.write_text(vacuous_async, encoding="utf-8")
    vza = {
        f["function"]
        for f in scn.scan_file(str(v))["findings"]
        if f["rule"] == "zero_assertion"
    }
    assert vza == {"test_only_builtin"}, (
        f"proofless async body should still flag zero_assertion; got {vza}"
    )


def test_nondiscriminating_hook_deny_fires_and_clears(tmp_path) -> None:
    """TP-303 earn-the-red: a deny-intent ``test_*`` that invokes a hook and observes
    ONLY the return code cannot distinguish a deny from an allow — under the channel-XOR
    protocol both are exit 0 with a stdout-JSON decision — so it must yield a
    ``nondiscriminating_hook_assert`` finding.

    Two shapes must FIRE: (1) a returncode-only deny test; (2) a deny test whose
    DOCSTRING narrates "permissionDecision=deny" but whose CODE only asserts the return
    code — the narration must not count as a channel observation (a docstring is an
    unreliable signal, the same reason intent is read from the name only).

    Four shapes must CLEAR: (1) an allow-intent returncode-only test (returncode IS the
    correct observation for an allow); (2) a deny-intent test that parses
    ``permissionDecision`` from stdout; (3) a deny-intent test that discriminates via the
    ``assert_hook_denied`` helper — the dominant idiom the body-only AST walk must resolve
    THROUGH (else the detector false-positives on the very tests that discriminate through
    it); (4) a NEGATED-deny name (``test_does_not_block_...``) that asserts only the
    return code — an honest allow-test whose name happens to contain a deny keyword, on
    which a false denial is worse than one un-caught instance (the governing frame).

    Pre-implementation HEAD has no ``nondiscriminating_hook_assert`` rule, so the positive
    assertion goes RED before the detector lands and GREEN after. Written to tmp files
    (not the shared fixture) so the deny-named returncode-only bodies are neither
    pytest-collected nor scanned by live ``espalier scan`` runs."""
    positive = (
        "def test_blocks_traversal_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "def test_denies_protected_zone():\n"
        "    '''Verify write_guard denies via permissionDecision=deny.'''\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
    )
    p = tmp_path / "test_nd_hook_positive_fixture.py"
    p.write_text(positive, encoding="utf-8")
    flagged = {
        f["function"]
        for f in scn.scan_file(str(p))["findings"]
        if f["rule"] == "nondiscriminating_hook_assert"
    }
    assert flagged == {"test_blocks_traversal_write", "test_denies_protected_zone"}, (
        f"nondiscriminating_hook_assert missed a returncode-only deny test (or was fooled "
        f"by docstring narration into clearing one); flagged {flagged}"
    )

    negatives = (
        "import json\n"
        "def test_allows_safe_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "def test_denies_protected_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    out = json.loads(r.stdout)\n"
        "    assert out['hookSpecificOutput']['permissionDecision'] == 'deny'\n"
        "def test_blocks_write_via_helper():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "    assert_hook_denied(r)\n"
        "def test_does_not_block_safe_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
    )
    n = tmp_path / "test_nd_hook_negatives_fixture.py"
    n.write_text(negatives, encoding="utf-8")
    neg = {
        f["function"]
        for f in scn.scan_file(str(n))["findings"]
        if f["rule"] == "nondiscriminating_hook_assert"
    }
    assert neg == set(), (
        f"nondiscriminating_hook_assert false-positived on an allow test, a "
        f"discriminating deny test, or a negated-deny allow-name; flagged {neg}"
    )


def test_nondiscriminating_hook_channel_mention_in_narration_does_not_clear(tmp_path) -> None:
    """DEF-312b earn-the-red: a channel reference that only NARRATES -- inside an
    assert's message, or as a ``print()`` / ``pytest.fail()`` argument -- renders the
    value without comparing or parsing it, so the test still cannot fail for its
    stated reason and must be flagged. Before the fix one such mention anywhere in the
    body cleared the finding; the rule flagged nothing on the live tree while its
    docstring claimed this exact catch.

    Six deny shapes and one allow shape must FIRE (the narration is their only
    channel mention): the assert message, ``print()``, ``pytest.fail()``, a ``raise``,
    an f-string assigned to a name and passed as the message one line later, and
    ``pytest.skip()``. Four shapes must CLEAR. Two are real observations: the
    dominant live idiom that parses stdout into a variable in an ASSIGNMENT and
    asserts on the parsed decision (an assert-subject-only reading false-positived on
    five such tests, measured 2026-09-08 -- this negative pins that refutation), and
    a test that narrates AND observes (the narration must not mask a real
    observation). Two are labelled WITNESSES of the boundary's known blind spots -- a
    message built by concatenation, and a logging call outside ``_NARRATION_CALLS``
    -- so a future widening of the narration set flips these pins in lockstep instead
    of drifting the rule's meaning silently (the same convention as the allow arm's
    ``run_bash_guard`` witness)."""
    positive = (
        "import logging\n"
        "import pytest\n"
        "def test_blocks_traversal_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0, f'expected deny; got {r.stdout}'\n"
        "def test_denies_protected_zone():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    print(r.stdout, r.stderr)\n"
        "    assert r.returncode == 0\n"
        "def test_blocks_kill_switch():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    if r.returncode != 0:\n"
        "        pytest.fail(msg=f'hook errored: {r.stderr}')\n"
        "    assert r.returncode == 0\n"
        "def test_blocks_secret_read():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    if r.returncode != 0:\n"
        "        raise AssertionError(f'hook errored: {r.stderr}')\n"
        "    assert r.returncode == 0\n"
        "def test_denies_via_built_message():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    msg = f'expected deny; got {r.stdout}'\n"
        "    assert r.returncode == 0, msg\n"
        "def test_blocks_when_not_skipped():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    if r.returncode != 0:\n"
        "        pytest.skip(f'no verdict: {r.stderr}')\n"
        "    assert r.returncode == 0\n"
        "def test_allows_safe_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0, r.stderr\n"
    )
    p = tmp_path / "test_nd_hook_narration_positive_fixture.py"
    p.write_text(positive, encoding="utf-8")
    flagged = {
        (f["rule"], f["function"])
        for f in scn.scan_file(str(p))["findings"]
        if f["rule"].startswith("nondiscriminating_hook_")
    }
    assert flagged == {
        ("nondiscriminating_hook_assert", "test_blocks_traversal_write"),
        ("nondiscriminating_hook_assert", "test_denies_protected_zone"),
        ("nondiscriminating_hook_assert", "test_blocks_kill_switch"),
        ("nondiscriminating_hook_assert", "test_blocks_secret_read"),
        ("nondiscriminating_hook_assert", "test_denies_via_built_message"),
        ("nondiscriminating_hook_assert", "test_blocks_when_not_skipped"),
        ("nondiscriminating_hook_allow", "test_allows_safe_write"),
    }, (
        f"a channel mention that only narrates (assert message, print, pytest.fail, "
        f"raise, an f-string assigned to a name, pytest.skip) cleared a "
        f"returncode-only hook test; flagged {flagged}"
    )

    negatives = (
        "import json\n"
        "import logging\n"
        "def test_blocks_disable_all_hooks():\n"
        "    result = _run_hook('config_guard.py', payload, env)\n"
        "    assert result.returncode == 0\n"
        "    data = json.loads(result.stdout)\n"
        "    assert data.get('decision') == 'block'\n"
        "def test_denies_protected_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    body = json.loads(r.stdout)\n"
        "    assert r.returncode == 0, f'got {r.stdout}'\n"
        "    assert body['hookSpecificOutput']['permissionDecision'] == 'deny'\n"
        # Known narration blind spot, WITNESSED: a message built by concatenation is
        # not an f-string, so the `.stdout` inside it still reads as an observation.
        # A future widening of `_narration_node_ids` flips this pin in lockstep.
        "def test_blocks_via_concatenated_message():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    msg = 'expected deny; got ' + str(r.stdout)\n"
        "    assert r.returncode == 0, msg\n"
        # Known narration blind spot, WITNESSED: a logging call is outside
        # `_NARRATION_CALLS`. A future widening of that set flips this pin in lockstep.
        "def test_blocks_with_logged_output():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    logging.info('out=%s', r.stdout)\n"
        "    assert r.returncode == 0\n"
    )
    n = tmp_path / "test_nd_hook_narration_negatives_fixture.py"
    n.write_text(negatives, encoding="utf-8")
    neg = {
        f["function"]
        for f in scn.scan_file(str(n))["findings"]
        if f["rule"].startswith("nondiscriminating_hook_")
    }
    assert neg == set(), (
        f"a test that parses stdout in an assignment, narrates AND observes, or sits "
        f"in a witnessed narration blind spot was flagged as non-discriminating "
        f"(if the blind spot was closed on purpose, move its witness to the fire side); "
        f"flagged {neg}"
    )


def test_nondiscriminating_hook_deny_detects_underscore_run_hook(tmp_path) -> None:
    """TP-312 earn-the-red: the hook-invocation helper has TWO live names in this
    repo — the bare ``run_hook`` (189 call sites) and the underscore-prefixed private
    ``_run_hook`` (65 sites, including the kill-switch + integrity deny-tests). Pre-fix
    ``_invokes_hook`` matched the callee by EXACT equality against ``_HOOK_INVOKER =
    "run_hook"``, so every ``_run_hook``-based deny-test was invisible to the
    nondiscriminating-assert detector. Widening the constant to the set
    ``_HOOK_INVOKERS = {"run_hook", "_run_hook"}`` closes the blind spot.

    A deny-intent ``_run_hook`` test that observes ONLY ``.returncode`` must FIRE
    (RED on the pre-fix exact-``run_hook`` scanner, GREEN after the widening); an
    allow-name ``_run_hook`` returncode-only test and a discriminating ``_run_hook``
    deny test must both CLEAR — the precision gate proving the widening does not
    manufacture a false denial on the newly-visible call sites."""
    positive = (
        "def test_blocks_kill_switch_write():\n"
        "    r = _run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
    )
    p = tmp_path / "test_underscore_run_hook_positive_fixture.py"
    p.write_text(positive, encoding="utf-8")
    flagged = {
        f["function"]
        for f in scn.scan_file(str(p))["findings"]
        if f["rule"] == "nondiscriminating_hook_assert"
    }
    assert flagged == {"test_blocks_kill_switch_write"}, (
        f"nondiscriminating_hook_assert missed a _run_hook-invoking returncode-only "
        f"deny test (exact-run_hook blindness); flagged {flagged}"
    )

    negatives = (
        "import json\n"
        "def test_allows_safe_write_via_underscore():\n"
        "    r = _run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "def test_denies_protected_via_underscore():\n"
        "    r = _run_hook('write_guard.py', payload, env)\n"
        "    out = json.loads(r.stdout)\n"
        "    assert out['hookSpecificOutput']['permissionDecision'] == 'deny'\n"
        "def test_denies_kill_switch_via_audit():\n"
        "    r = _run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "    assert 'pretooluse_blocked_kill_switch' in audit_log\n"
    )
    n = tmp_path / "test_underscore_run_hook_negatives_fixture.py"
    n.write_text(negatives, encoding="utf-8")
    neg = {
        f["function"]
        for f in scn.scan_file(str(n))["findings"]
        if f["rule"] == "nondiscriminating_hook_assert"
    }
    assert neg == set(), (
        f"nondiscriminating_hook_assert false-positived on an allow-name or a "
        f"discriminating _run_hook deny test; flagged {neg}"
    )


def test_blocked_audit_token_stays_coupled_to_the_hooks_real_block_events(tmp_path):
    """TP-312 coupling-lock. `_observes_decision_channel` recognizes an audit-log
    discrimination via the underscore-anchored `_blocked` token. That token is coupled
    BY NAME to the hooks' real block-decision audit events -- a coupling that otherwise
    lives only in a code comment. Pin it: if a hook renames its block event to something
    WITHOUT `_blocked` (e.g. `pretooluse_denied_kill_switch`), a test that discriminates
    via the new event would be wrongly flagged -- the exact false-positive class this
    recognition closes, silently reintroduced. This reds instead, forcing the hook-event
    name and the scanner token to move in lockstep.

    The two block-decision audit events currently emitted (the ONLY ones that fire on a
    deny, vs the non-blocking `*_detected` siblings):
      - tools/cc/hooks/write_guard.py  -> pretooluse_blocked_kill_switch
      - tools/cc/hooks/config_guard.py -> configchange_blocked_kill_switch
    """
    hooks = REPO_ROOT / "tools" / "cc" / "hooks"
    block_events = {
        "write_guard.py": "pretooluse_blocked_kill_switch",
        "config_guard.py": "configchange_blocked_kill_switch",
    }
    for hook, event in block_events.items():
        src = (hooks / hook).read_text(encoding="utf-8")
        assert event in src, (
            f"{hook} no longer emits '{event}'. If the block-audit event was renamed, "
            f"update the scanner's `_blocked` recognition (_observes_decision_channel) "
            f"and this pin in lockstep -- else a deny-test discriminating via the new "
            f"event name silently becomes a false positive."
        )
        assert "_blocked" in event, f"'{event}' lost the `_blocked` token the scanner keys on"
        # End-to-end: a deny-test that discriminates via THIS real event must CLEAR.
        fixture = (
            "def test_denies_via_audit_log():\n"
            "    r = run_hook('h.py', payload, env)\n"
            "    assert r.returncode == 0\n"
            f"    assert '{event}' in audit_log\n"
        )
        p = tmp_path / f"test_coupling_{event}_fixture.py"
        p.write_text(fixture, encoding="utf-8")
        flagged = {
            f["function"]
            for f in scn.scan_file(str(p))["findings"]
            if f["rule"] == "nondiscriminating_hook_assert"
        }
        assert flagged == set(), (
            f"scanner failed to recognize audit-discrimination via the real block event "
            f"'{event}' -- the `_blocked` token has drifted from the hook vocabulary: {flagged}"
        )


def test_nondiscriminating_hook_allow_fires_and_clears(tmp_path) -> None:
    """TP-322 earn-the-red: the allow-side mirror of the deny-arm. An allow-intent
    ``test_*`` that invokes ``run_hook``/``_run_hook`` and observes ONLY the return code
    cannot catch an over-block flip to deny (also exit 0 under channel-XOR), so it must
    yield a ``nondiscriminating_hook_allow`` finding.

    Three shapes must FIRE: (1) an ``allow``-name ``run_hook`` returncode-only test; (2) a
    ``permit``-name ``_run_hook`` returncode-only test (both invoker names, both intent
    stems); (3) an allow-intent ``run_hook`` returncode-only test whose ONLY ``.stdout``
    reference is inside the assert *message*. Shape (3) was pinned on the CLEAR side
    when the arm landed, as a deliberate false negative -- ``_observes_decision_channel``
    then treated any body ``.stdout`` as an observation, so message interpolation
    exempted it. DEF-312b moved narration (an assert message, a ``raise``, an f-string
    assigned to a name, a ``print()`` / ``pytest.fail()`` argument) out of the
    observation set, so the witness flipped to the FIRE side in lockstep, as its pin
    was written to do.

    Five shapes must CLEAR: (1) an allow-intent test resolving through the
    ``assert_hook_allowed`` helper (the discriminating idiom); (2) an allow-intent test
    that parses ``permissionDecision`` from stdout; (3) a deny-intent returncode-only test
    (owned by the deny arm, not this one — no allow keyword in the name); (4) an
    allow-intent test that never invokes a hook (not a hook test at all); (5) an
    allow-intent test invoking ``run_bash_guard`` — outside ``_HOOK_INVOKERS``, so BOTH
    arms are blind to it (the deliberate, documented invoker boundary; widening the
    invoker set is a separate deny-arm calibration, tracked as a follow-up). Shape (5)
    WITNESSES a known blind spot: a future tightening of that boundary flips the pin in
    lockstep instead of drifting the arm's meaning silently.

    Pre-implementation HEAD has no ``nondiscriminating_hook_allow`` rule, so the positive
    assertion goes RED before the arm lands and GREEN after. Written to tmp files (not the
    shared fixture) so the allow-named returncode-only bodies are neither pytest-collected
    nor scanned by live ``espalier scan`` runs."""
    positive = (
        "def test_allows_safe_write():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "def test_permits_readonly_via_underscore():\n"
        "    r = _run_hook('plan_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        # (3) narration witness: the ONLY .stdout reference is in the assert MESSAGE,
        # rendered on failure and never compared -- a returncode-only test (DEF-312b).
        "def test_allows_stdout_only_in_message():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0, f'expected allow, got {r.stdout!r}'\n"
    )
    p = tmp_path / "test_nd_hook_allow_positive_fixture.py"
    p.write_text(positive, encoding="utf-8")
    flagged = {
        f["function"]
        for f in scn.scan_file(str(p))["findings"]
        if f["rule"] == "nondiscriminating_hook_allow"
    }
    assert flagged == {
        "test_allows_safe_write",
        "test_permits_readonly_via_underscore",
        "test_allows_stdout_only_in_message",
    }, (
        f"nondiscriminating_hook_allow missed a returncode-only allow/permit test "
        f"(or a message-only stdout mention cleared one); flagged {flagged}"
    )

    negatives = (
        "import json\n"
        "def test_allows_via_helper():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert_hook_allowed(r)\n"
        "def test_allows_checks_stdout():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    out = json.loads(r.stdout)\n"
        "    assert out['hookSpecificOutput']['permissionDecision'] != 'deny'\n"
        "def test_denies_protected_zone():\n"
        "    r = run_hook('write_guard.py', payload, env)\n"
        "    assert r.returncode == 0\n"
        "def test_allows_non_hook_operation():\n"
        "    result = compute_something()\n"
        "    assert result.returncode == 0\n"
        # (5) invoker-boundary witness: run_bash_guard is outside _HOOK_INVOKERS,
        # so both arms are blind to it. Deliberate, documented boundary.
        "def test_allows_via_bash_guard():\n"
        "    r = run_bash_guard('ls tools/', tmp_path)\n"
        "    assert r.returncode == 0\n"
    )
    n = tmp_path / "test_nd_hook_allow_negatives_fixture.py"
    n.write_text(negatives, encoding="utf-8")
    neg = {
        f["function"]
        for f in scn.scan_file(str(n))["findings"]
        if f["rule"] == "nondiscriminating_hook_allow"
    }
    assert neg == set(), (
        f"nondiscriminating_hook_allow false-positived on a channel-observing allow test, "
        f"a deny-intent test (deny arm's job), or a non-hook test; flagged {neg}"
    )
