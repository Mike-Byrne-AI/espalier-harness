"""Pin the exceptions scanner's behavioral contract.

Earn-the-gate: every documented `kind` surfaces when scan_file walks
the known-positives fixture. Live-scan exemption: EXEMPT_PREFIXES keeps
the fixture out of normal `espalier scan exceptions` runs.

TP-105 / TP-143 / FM-7 §1.7 close.
"""
from __future__ import annotations

from pathlib import Path

from espalier.scanners import exceptions as scn


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_exceptions_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_exceptions_negatives.py"


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """scan_file the fixture directly. EXEMPT_PREFIXES skips the file
    in normal scan_repo runs, but direct-call bypasses the walk."""
    findings = scn.scan_file(str(FIXTURE_PATH))
    kinds_seen = {f["kind"] for f in findings}
    expected_kinds = {
        "swallowed_silent",
        "swallowed_broad_no_log",
        "swallowed_broad_print_only",
    }
    missing = expected_kinds - kinds_seen
    assert not missing, (
        f"earn-the-gate: scanner failed to detect kinds {missing}. "
        f"Found: {kinds_seen}. TP-105/TP-143 pattern."
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: scan_file the negatives corpus directly. Every
    construct is a clean-but-tempting variant of a flagged shape (broad
    catch that re-raises or logs; specific handlers; print+log). The
    scanner must report ZERO findings. Direct-call mirrors the
    earn-the-gate test and is immune to live-tree drift (TP-156)."""
    findings = scn.scan_file(str(NEG_FIXTURE_PATH))
    assert findings == [], (
        f"negatives corpus tripped the scanner: {findings}. "
        f"A construct thought clean is being flagged. TP-156 Tier 1."
    )


def test_nonlogger_error_call_does_not_clear_broad_swallow() -> None:
    """TP-217b: `_is_logger_call` requires a logger-plausible receiver. A broad
    handler whose body is `obj.error()` / `db.collection.info()` /
    `QMessageBox.warning()` is a REAL swallow — receiver-blind matching cleared
    it as logging (false negative)."""
    import ast

    for call in ("response.error()", "db.collection.info()",
                 "QMessageBox.warning()", "x.critical()"):
        h = ast.parse(
            f"try:\n    risky()\nexcept Exception:\n    {call}\n"
        ).body[0].handlers[0]
        has_log, _has_print = scn._contains_log(h.body)
        assert has_log is False, f"{call!r} wrongly counted as a logger call"

    # Positive controls: real logger receivers still count.
    for call in ("logger.error('x')", "logging.warning('x')", "_log.debug('x')"):
        h = ast.parse(
            f"try:\n    risky()\nexcept Exception:\n    {call}\n"
        ).body[0].handlers[0]
        has_log, _ = scn._contains_log(h.body)
        assert has_log is True, f"{call!r} should count as a logger call"


def test_broad_tuple_handler_is_flagged(tmp_path: Path) -> None:
    """TP-217b: `except (ValueError, Exception):` with a non-pass, non-logging
    body is a broad swallow — the tuple-walk gate must flag it. The bare-pass
    tuple sub-case is still caught by _body_is_pass (swallowed_silent)."""
    p = tmp_path / "tuple_handler.py"
    p.write_text(
        "try:\n    risky()\nexcept (ValueError, Exception):\n    x = 1\n",
        encoding="utf-8",
    )
    kinds = {f["kind"] for f in scn.scan_file(str(p))}
    assert "swallowed_broad_no_log" in kinds, f"broad tuple handler not flagged: {kinds}"

    p_pass = tmp_path / "tuple_pass.py"
    p_pass.write_text(
        "try:\n    risky()\nexcept (ValueError, Exception):\n    pass\n",
        encoding="utf-8",
    )
    assert any(f["kind"] == "swallowed_silent" for f in scn.scan_file(str(p_pass)))


def test_fixture_skipped_by_live_scan() -> None:
    """EXEMPT_PREFIXES added in TP-143 must keep the fixture out of
    live scans -- otherwise every espalier audit run would surface
    fixture findings."""
    report = scn.scan_repo(str(REPO_ROOT))
    fixture_rel = "tests/fixtures/test_exceptions_positives.py"
    fixture_findings = [
        f for f in report["findings"]
        if fixture_rel in f["file"].replace("\\", "/")
    ]
    assert fixture_findings == [], (
        f"EXEMPT_PREFIXES did not skip the fixture. Found "
        f"{len(fixture_findings)} fixture finding(s)."
    )


def test_nested_def_raise_does_not_clear_swallow() -> None:
    """TP-190: a `raise` (or logger call) inside an uninvoked nested function in
    the handler body must NOT clear the swallowed-exception finding — it is a
    different scope and never re-raises the handled exception. The prior
    `ast.walk` descended into nested defs (false negative)."""
    import ast

    swallow = ast.parse(
        "try:\n"
        "    risky()\n"
        "except Exception:\n"
        "    def _unused():\n"
        "        raise RuntimeError('not the handler raise')\n"
        "    x = 1\n"
    ).body[0].handlers[0]
    real_reraise = ast.parse(
        "try:\n    risky()\nexcept Exception:\n    raise\n"
    ).body[0].handlers[0]

    # nested-def raise => the handler's own scope has no raise => swallow stands
    assert scn._contains_raise(swallow.body) is False
    # positive control: a real re-raise at the handler's own scope still counts
    assert scn._contains_raise(real_reraise.body) is True


def test_nested_def_log_does_not_clear_swallow() -> None:
    """TP-192 W5-1: the `_contains_log` half of the TP-190 nested-scope change.
    A logger call inside an uninvoked nested function in the handler body must
    NOT register as the handler's own log — it is a different scope and never
    reports the handled exception. Mirror of
    test_nested_def_raise_does_not_clear_swallow; without it, re-broadening
    `_contains_log` alone would pass the suite."""
    import ast

    nested_log = ast.parse(
        "try:\n"
        "    risky()\n"
        "except Exception:\n"
        "    def _unused():\n"
        "        logger.error('not the handler log')\n"
        "    x = 1\n"
    ).body[0].handlers[0]
    same_scope_log = ast.parse(
        "try:\n    risky()\nexcept Exception:\n    logger.error('handled')\n"
    ).body[0].handlers[0]

    # nested-def logger call => the handler's own scope has no log
    assert scn._contains_log(nested_log.body) == (False, False)
    # positive control: a logger call at the handler's own scope still counts
    assert scn._contains_log(same_scope_log.body) == (True, False)


def test_inline_getlogger_receiver_counts_as_logging(tmp_path: Path) -> None:
    """TP-266 Fix 3: `logging.getLogger(__name__).exception(...)` /
    `getLogger('x').error(...)` is a real logging handler, but its attribute
    chain roots at the getLogger() CALL rather than a Name, so the
    receiver-plausibility gate (TP-217b) rejected it and a properly-logged broad
    handler was flagged `swallowed_broad_no_log`. RED before (emits the finding),
    GREEN after (none). The receiver-blindness guard must NOT regress: a
    non-logger `.error()` receiver stays flagged."""
    import ast

    # Positive: a getLogger()-receiver handler is real logging.
    for call in (
        "logging.getLogger(__name__).exception('boom')",
        "getLogger('x').error('boom')",
    ):
        h = ast.parse(
            f"try:\n    risky()\nexcept Exception:\n    {call}\n"
        ).body[0].handlers[0]
        has_log, _ = scn._contains_log(h.body)
        assert has_log is True, f"{call!r} should count as a logger call"

    p = tmp_path / "getlogger_handler.py"
    p.write_text(
        "import logging\n"
        "try:\n    risky()\n"
        "except Exception:\n    logging.getLogger(__name__).exception('boom')\n",
        encoding="utf-8",
    )
    kinds = {f["kind"] for f in scn.scan_file(str(p))}
    assert "swallowed_broad_no_log" not in kinds, (
        f"a getLogger()-logged handler was wrongly flagged as a swallow: {kinds}"
    )

    # Negative control: a non-logger `.error()` receiver is still a real swallow
    # (must not re-open the TP-217b false-negative the receiver-check prevents).
    h = ast.parse(
        "try:\n    risky()\nexcept Exception:\n    response.error()\n"
    ).body[0].handlers[0]
    has_log, _ = scn._contains_log(h.body)
    assert has_log is False, "non-logger response.error() must not count as logging"


def test_inline_snakecase_get_logger_receiver_counts_as_logging(tmp_path: Path) -> None:
    """TP-274 3-A: TP-266 Fix 3 recognized only camelCase stdlib `getLogger`. A
    snake_case `structlog.get_logger().error(...)` / `get_logger(...).exception(...)`
    — the structlog/loguru idiom, common in adopter code — roots at a Call the
    receiver gate rejected, so a properly-logged broad handler was false-flagged
    `swallowed_broad_no_log`. RED before (emits the finding), GREEN after. The
    receiver-blindness guard must NOT regress: a non-logger `.error()` stays flagged."""
    import ast

    for call in (
        "structlog.get_logger().error('boom')",
        "get_logger('x').exception('boom')",
    ):
        h = ast.parse(
            f"try:\n    risky()\nexcept Exception:\n    {call}\n"
        ).body[0].handlers[0]
        has_log, _ = scn._contains_log(h.body)
        assert has_log is True, f"{call!r} should count as a logger call"

    p = tmp_path / "structlog_handler.py"
    p.write_text(
        "import structlog\n"
        "try:\n    risky()\n"
        "except Exception:\n    structlog.get_logger().error('boom')\n",
        encoding="utf-8",
    )
    kinds = {f["kind"] for f in scn.scan_file(str(p))}
    assert "swallowed_broad_no_log" not in kinds, (
        f"a structlog.get_logger()-logged handler was wrongly flagged: {kinds}"
    )

    # Negative control: a non-logger `.error()` receiver is still a real swallow.
    h = ast.parse(
        "try:\n    risky()\nexcept Exception:\n    response.error()\n"
    ).body[0].handlers[0]
    has_log, _ = scn._contains_log(h.body)
    assert has_log is False, "non-logger response.error() must not count as logging"
