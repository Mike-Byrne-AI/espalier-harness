"""End-to-end exercise of the docs/DEMO.md walkthrough — TP-RELEASE-10 §B.

Each demo beat is invoked as a subprocess (the way a new reader would
run it) and the output shape is verified. The full output isn't
exact-matched — version strings and timestamps drift — but the
structural anchors that the demo doc relies on must remain stable.

A separate static check verifies the demo doc avoids unqualified
overclaims (`sandbox`, `cannot be bypassed`, `hard security guarantee`).
The check uses positive-claim detection (e.g. "is a sandbox" → flagged;
"is not a sandbox" → allowed) so calibrated non-claims survive.

Stem `test_demo_end_to_end` is registered under `integration` and
`slow` in `tests/conftest.py::_MARKER_RULES` (subprocess-heavy).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DOC = REPO_ROOT / "docs" / "DEMO.md"
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
DEMO_SCRIPT = REPO_ROOT / "bench" / "demo" / "script.md"

# The quoted deny in docs/DEMO.md is one JSON line inside a fence.
_DEMO_JSON_LINE_RE = re.compile(r'^\{"hookSpecificOutput": .*\}$', re.MULTILINE)
# The POSIX spelling the transcripts were recorded with (relaunch_hint() is
# host-keyed: PowerShell and cmd.exe forms lead on Windows).
_POSIX_HINT = "`ESPALIER_MAINTENANCE_MODE=1 claude --continue`"


def _live_hint() -> str:
    import sys as _sys

    _sys.path.insert(0, str(HOOKS_DIR))
    import _maintenance_mode  # noqa: E402

    return _maintenance_mode.relaunch_hint()


def _drive_write_guard(payload: dict) -> str:
    """The live deny reason for ``payload``, from the hook as a subprocess with
    maintenance mode scrubbed (set, the guard allows and prints nothing)."""
    import os

    env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
    result = subprocess.run(
        [sys.executable, "tools/cc/hooks/write_guard.py"],
        input=json.dumps(payload), capture_output=True, text=True, timeout=15,
        cwd=str(REPO_ROOT), encoding="utf-8", env=env,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", out
    return out["permissionDecisionReason"]


def _normalise_hint(text: str, live_hint: str) -> str:
    """On a POSIX host the transcripts' spelling IS the live one, so the hint is
    compared verbatim and a changed relaunch spelling reds (the 2026-09-22
    failure-mode review drove the blind spot: normalising both sides on every
    host made a stale doc compare equal to a changed hint). Only on Windows,
    where relaunch_hint() leads with the PowerShell and cmd.exe forms, is the
    hint token normalised on both sides."""
    if sys.platform != "win32":
        return text
    return text.replace(live_hint, "<HINT>").replace(_POSIX_HINT, "<HINT>")


def _assert_clauses_match(doc_reason: str, live_reason: str, where: str) -> None:
    """Clause by clause (the template joins clauses with a newline and two
    spaces), the host-keyed hint normalised on both sides, a documented ``…``
    truncation accepted as a prefix. A fragment pin (``"--continue" in reason``)
    stays green while a whole clause rewords; this does not."""
    hint = _live_hint()
    doc = [_normalise_hint(c, hint) for c in doc_reason.split("\n  ")]
    live = [_normalise_hint(c, hint) for c in live_reason.split("\n  ")]
    assert len(doc) == len(live), (
        f"{where} quotes {len(doc)} clauses; the live deny has {len(live)}"
    )
    drift = []
    for i, (d, lv) in enumerate(zip(doc, live)):
        if d.endswith("…"):
            head = d[:-1].rstrip()
            ok = bool(head) and lv.startswith(head)  # a bare `…` documents nothing
        else:
            ok = d == lv
        if not ok:
            drift.append(f"clause {i}:\n    doc:  {d}\n    live: {lv}")
    assert not drift, (
        f"{where} quotes a deny reason that drifted from the live one; re-drive "
        "the hook and paste it:\n  " + "\n  ".join(drift)
    )


def _fenced_block_after(text: str, marker: str) -> str:
    """The first fenced block after ``marker``, without its ``✗`` UI line,
    de-wrapped to one line per clause (a 2-space line continues the headline
    clause; a 4-space line that opens a clause starts one, otherwise continues)."""
    at = text.index(marker)
    start = text.index("```\n", at) + 4
    end = text.index("```", start)
    lines = [ln for ln in text[start:end].splitlines() if not ln.startswith("✗")]
    clauses: list[str] = []
    for ln in lines:
        body = ln.strip()
        opens = ln.startswith("    ") and body.split(" ", 1)[0] in {"Don't:", "Do:", "Your"}
        if not clauses or opens:
            clauses.append(body)
        else:
            clauses[-1] += " " + body
    return "\n  ".join(clauses)


@pytest.mark.slow
def test_demo_doc_exists():
    assert DEMO_DOC.exists(), "docs/DEMO.md missing — TP-RELEASE-10 §A required"


@pytest.mark.slow
def test_demo_version_command_runs():
    """`espalier --version` (Beat: setup) prints a version string."""
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "--version"],
        capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    assert result.returncode == 0, f"--version failed: {result.stderr}"
    assert "espalier" in result.stdout, (
        f"expected 'espalier' in --version output, got: {result.stdout!r}"
    )
    assert re.search(r"\d+\.\d+\.\d+", result.stdout), (
        f"expected semver in --version output, got: {result.stdout!r}"
    )


@pytest.mark.slow
def test_demo_beat1_write_guard_denies_protected():
    """Beat 1: piping a Write to tools/cc/hooks/* yields a deny payload."""
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "tools/cc/hooks/demo_target.py"},
    })
    result = subprocess.run(
        [sys.executable, "tools/cc/hooks/write_guard.py"],
        input=payload, capture_output=True, text=True, timeout=15,
        cwd=str(REPO_ROOT), encoding="utf-8",
    )
    # TP-9 protocol: exit 0 + structured JSON on stdout
    assert result.returncode == 0, (
        f"write_guard returned {result.returncode}, expected 0 "
        f"(TP-9 channel-XOR contract). stderr: {result.stderr!r}"
    )
    payload_out = json.loads(result.stdout)
    decision = payload_out["hookSpecificOutput"]["permissionDecision"]
    reason = payload_out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision == "deny"
    assert "tools/cc/hooks/demo_target.py" in reason
    assert "protected harness zone" in reason.lower()
    # The remedy the sample in docs/DEMO.md quotes must keep the session the
    # deny happened in; a bare relaunch drifted here once before review caught it.
    assert "--continue" in reason, reason
    # TP-177 W7: DEMO.md Beat 1 documents the maintenance-relaunch tail of the
    # deny reason. Pin it so the doc can't silently drift from the live reason.
    assert "ESPALIER_MAINTENANCE_MODE" in reason, (
        "deny reason no longer carries the maintenance-relaunch guidance that "
        "docs/DEMO.md Beat 1 documents — regenerate the demo block."
    )
    # Clause by clause, not by fragment (2026-09-22): the "Relocate it" clause
    # had grown "from your own terminal, outside a Claude Code session" while
    # every fragment pin above stayed green -- the doc quoted a reason the hook
    # no longer emits. Earned red on that clause before the doc was regenerated.
    doc_line = _DEMO_JSON_LINE_RE.search(DEMO_DOC.read_text(encoding="utf-8"))
    assert doc_line, "docs/DEMO.md Beat 1 lost its quoted JSON deny line"
    doc_reason = json.loads(doc_line.group(0))["hookSpecificOutput"]["permissionDecisionReason"]
    _assert_clauses_match(doc_reason, reason, "docs/DEMO.md Beat 1")


@pytest.mark.slow
def test_demo_beat2_doctor_runs_on_self(initialized_repo_root):
    """Beat 2: `espalier doctor .` runs cleanly on the espalier repo."""
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "doctor", "."],
        capture_output=True, text=True, timeout=120,
        cwd=str(initialized_repo_root), encoding="utf-8",
    )
    # doctor exits 0 on pass/warn, non-zero on fail. The demo notes
    # warn is normal; fail would be a real regression.
    assert result.returncode == 0, (
        f"espalier doctor . failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    # Must be parseable JSON with the contract fields the demo references.
    parsed = json.loads(result.stdout)
    for key in ("repo_root", "status", "checks"):
        assert key in parsed, (
            f"doctor output missing key {key!r} that DEMO.md references"
        )
    assert parsed["status"] in {"pass", "warn", "fail"}, (
        f"unexpected doctor status: {parsed['status']!r}"
    )


@pytest.mark.slow
def test_demo_beat3_release_check_runs(initialized_repo_root):
    """Beat 3: `python scripts/release_check.py` exits 0 on the live repo."""
    result = subprocess.run(
        [sys.executable, "scripts/release_check.py"],
        capture_output=True, text=True, timeout=60,
        cwd=str(initialized_repo_root), encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"release_check.py failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "release_check OK" in result.stdout, (
        "release_check.py must print 'release_check OK' on success — the "
        "DEMO.md expected-output block depends on it."
    )


# ── Static overclaim checks ──────────────────────────────────────────


# Positive-claim detectors. Each pattern matches an *unqualified* claim
# and skips the calibrated negation. Window of ±60 chars is enough to
# pick up "X. It is not." or "is not a sandbox" without spanning whole
# paragraphs.
_OVERCLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("is a sandbox",
     re.compile(r"\bis\s+a\s+sandbox\b", re.IGNORECASE)),
    ("cannot be bypassed",
     re.compile(r"\bcannot\s+be\s+bypassed\b", re.IGNORECASE)),
    ("hard security guarantee",
     re.compile(r"\bhard\s+security\s+guarantee\b", re.IGNORECASE)),
)
_NEGATION_WINDOW = 60


def test_demo_doc_does_not_overclaim():
    """DEMO.md must not contain unqualified overclaim phrases."""
    text = DEMO_DOC.read_text(encoding="utf-8")
    text_lower = text.lower()
    offenders: list[tuple[str, str]] = []
    for label, pattern in _OVERCLAIM_PATTERNS:
        for m in pattern.finditer(text_lower):
            start = max(0, m.start() - _NEGATION_WINDOW)
            end = min(len(text_lower), m.end() + _NEGATION_WINDOW)
            window = text_lower[start:end]
            # Look for an immediate negation: "is not a sandbox", "It is not.",
            # "It does not", "no", "never". Anything that flips the claim.
            negated = bool(
                re.search(r"\bis\s+not\b", window)
                or re.search(r"\bit\s+is\s+not\b", window)
                or re.search(r"\bdoes\s+not\b", window)
                or re.search(r"\bnot\s+a\s+sandbox\b", window)
            )
            if not negated:
                offenders.append((label, window.strip()))
    assert not offenders, (
        "DEMO.md contains unqualified overclaim language:\n"
        + "\n".join(f"  - {label}: {ctx!r}" for label, ctx in offenders)
        + "\nEither remove the claim or qualify it with explicit negation "
        "in the same sentence."
    )


def test_demo_script_quotes_match_the_live_deny_clause_by_clause():
    """``bench/demo/script.md`` quotes the settings.json deny twice verbatim
    (Attempt 1, the Write; Attempt 3, the Bash tee). Each is re-driven here and
    compared clause by clause; the storyboard's elided form (``…``) is not a
    verbatim claim and is not read. ``tests/test_bench_demo_script_quotes.py``
    pins the zone list and the hint in-process; this pins the whole text."""
    text = DEMO_SCRIPT.read_text(encoding="utf-8")
    live_write = _drive_write_guard(
        {"tool_name": "Write", "tool_input": {"file_path": ".claude/settings.json"}}
    )
    _assert_clauses_match(
        _fenced_block_after(text, "Attempt 1: direct edit of settings.json"),
        live_write, "bench/demo/script.md Attempt 1",
    )
    live_bash = _drive_write_guard(
        {"tool_name": "Bash", "tool_input": {"command": "echo x | tee --append .claude/settings.json"}}
    )
    _assert_clauses_match(
        _fenced_block_after(text, "Attempt 3: tee long-form flag"),
        live_bash, "bench/demo/script.md Attempt 3",
    )


@pytest.mark.skipif(sys.platform == "win32", reason="the verbatim arm is the POSIX one")
def test_a_changed_relaunch_spelling_is_drift_on_this_host(monkeypatch):
    """Earn the red for the verbatim arm (the 2026-09-22 failure-mode review's
    scenario): relaunch_hint() changes its POSIX spelling, the live clause
    carries the new one, the doc still quotes the old -- with the hint token
    normalised on both sides the two compared EQUAL. Now they are drift. A bare
    `…` clause matches nothing either."""
    moved = "`ESPALIER_MAINTENANCE_MODE=1 claude -c`"
    monkeypatch.setitem(globals(), "_live_hint", lambda: moved)
    doc = "Harness self-edits: exit and relaunch with " + _POSIX_HINT + " (env read at launch)."
    live = "Harness self-edits: exit and relaunch with " + moved + " (env read at launch)."
    with pytest.raises(AssertionError, match="drifted"):
        _assert_clauses_match(doc, live, "scratch")
    with pytest.raises(AssertionError, match="drifted"):
        _assert_clauses_match("…", live, "scratch")
    _assert_clauses_match(live, live, "scratch")
