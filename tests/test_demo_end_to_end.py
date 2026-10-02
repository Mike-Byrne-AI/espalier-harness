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
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DOC = REPO_ROOT / "docs" / "DEMO.md"
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
DEMO_STORYBOARD = REPO_ROOT / "bench" / "demo" / "STORYBOARD.md"
DEMO_RECORDING = REPO_ROOT / "bench" / "demo" / "RECORDING.md"
SESSION_RESUME = REPO_ROOT / "tools" / "cc" / "session_resume.py"

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


def _heading_at(text: str, marker: str) -> int:
    """Offset of ``marker`` asserted to be a UNIQUE ``### `` heading.

    The markers used to read ``Beat N: ...``, unique by construction. They now
    name the OUTPUT (so a re-cut cannot strand them -- it has twice), which
    makes them ordinary noun phrases: a sentence opening "The plan-gate deny
    fires reliably" placed anywhere above the heading would silently retarget
    ``str.index`` to the wrong fence, and the comparison would then run against
    whatever it got. Anchoring to the heading and asserting uniqueness is what
    makes "the heading names the output" a contract instead of a convention."""
    at = text.index(marker)
    assert text.count(marker) == 1, (
        f"{marker!r} is no longer unique in the doc -- a pin marker must appear "
        "exactly once, as a heading"
    )
    line_start = text.rfind("\n", 0, at) + 1
    assert text[line_start:at] == "### ", (
        f"{marker!r} is matched at offset {at} but is not a '### ' heading there"
    )
    return at


def _raw_fence_after(text: str, marker: str) -> list[str]:
    """The first fenced block after ``marker`` as raw lines (no de-wrap)."""
    at = _heading_at(text, marker)
    start = text.index("```\n", at) + 4
    end = text.index("```", start)
    return text[start:end].splitlines()


def _fenced_block_after(text: str, marker: str) -> str:
    """The first fenced block after ``marker``, without its ``✗`` UI line,
    de-wrapped to one line per clause (a 2-space line continues the headline
    clause; a 4-space line that opens a clause starts one, otherwise continues)."""
    at = _heading_at(text, marker)
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
@pytest.mark.contract
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
@pytest.mark.contract
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


@pytest.mark.contract
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
    """``bench/demo/STORYBOARD.md`` quotes two protected-zone denies verbatim:
    the lockout block (an Edit on a hook file, the hero's climax) and the Bash
    reference block (the ``tee`` row). Each is re-driven here and compared
    clause by clause; a block that elides with ``…`` is a prefix claim, and a
    bare ``…`` documents nothing. ``tests/test_bench_demo_script_quotes.py``
    pins the zone list and the hint in-process; this pins the whole text."""
    text = DEMO_STORYBOARD.read_text(encoding="utf-8")
    live_write = _drive_write_guard(
        {"tool_name": "Edit", "tool_input": {
            "file_path": "tools/cc/hooks/session_start.py",
            "old_string": "a", "new_string": "b"}}
    )
    _assert_clauses_match(
        _fenced_block_after(text, "The protected-zone deny on a hook file"),
        live_write, "bench/demo/STORYBOARD.md protected-zone block",
    )
    live_bash = _drive_write_guard(
        {"tool_name": "Bash", "tool_input": {"command": "echo x | tee --append .claude/settings.json"}}
    )
    _assert_clauses_match(
        _fenced_block_after(text, "Reference: the Bash variant of the protected-zone deny"),
        live_bash, "bench/demo/STORYBOARD.md Bash reference",
    )


def test_demo_storyboard_other_quoted_outputs_are_pinned_too():
    """The storyboard's two other quoted hook outputs. The plan-gate deny is
    formatted in-process from the live template with the storyboard's own
    arguments -- ``missing`` for a tree that never had a plan, the adopter
    exemption hint -- so the pin does not depend on this checkout's plan state.
    The maintenance-mode advisory is the guard's own stderr with the variable
    set.

    The headings are the OUTPUT's name, never a beat number: the hero was
    re-cut twice (2026-09-28, 2026-10-02) and a beat-keyed marker stranded
    these pins both times. There is deliberately no banner pin -- an exit-0
    hook's stdout never reaches the screen, so the storyboard no longer claims
    it as on-screen text (see its "Why there is no banner block")."""
    sys.path.insert(0, str(HOOKS_DIR))
    import _denial_reasons  # noqa: E402
    import plan_guard  # noqa: E402

    text = DEMO_STORYBOARD.read_text(encoding="utf-8")

    live_plan = _denial_reasons.NO_ACTIVE_PLAN_FILE.format(
        state="missing", path="src/utils.py", exempt_hint=plan_guard._PLAN_EXEMPT_HINT,
    )
    _assert_clauses_match(
        _fenced_block_after(text, "The plan-gate deny"),
        live_plan, "bench/demo/STORYBOARD.md plan-gate block",
    )

    env = {**os.environ, "ESPALIER_MAINTENANCE_MODE": "1"}
    result = subprocess.run(
        [sys.executable, "tools/cc/hooks/write_guard.py"],
        input=json.dumps({"tool_name": "Edit", "tool_input": {
            "file_path": "tools/cc/hooks/session_start.py",
            "old_string": "a", "new_string": "b"}}),
        capture_output=True, text=True, timeout=15, cwd=str(REPO_ROOT),
        encoding="utf-8", env=env,
    )
    assert result.returncode == 0, result.stderr
    advisory = [ln for ln in result.stderr.splitlines() if "MAINTENANCE_MODE" in ln]
    assert advisory, f"the guard wrote no maintenance advisory: {result.stderr!r}"
    doc_line = _fenced_block_after(text, "The maintenance-mode advisory")
    assert doc_line == advisory[0], (
        f"the advisory block quotes {doc_line!r}; the guard writes {advisory[0]!r}"
    )



def _drive_resume(*args: str) -> str:
    """``session_resume.py`` with maintenance mode scrubbed, stdout only."""
    env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
    result = subprocess.run(
        [sys.executable, "tools/cc/session_resume.py", *args],
        capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        encoding="utf-8", env=env,
    )
    assert result.returncode == 0, f"{args}: rc={result.returncode} {result.stderr}"
    return result.stdout


def _status_canon_labels() -> tuple[set[str], set[str]]:
    """``(unconditional, conditional)`` labels ``render_status_report`` emits.

    DERIVED from the emitter's AST, never a hand-written copy: the function
    builds one ``lines = [...]`` literal (always printed) and appends further
    lines under an ``if`` (printed only in some states -- ``MISSING:`` today).
    A hand-kept label list here would be the very shape
    ``docs/SHARP_EDGES.md`` "A Hand-Maintained Doc Enumeration With No
    Code-Pinned Parity Test Rots Silently" warns about, one level up."""
    import ast

    fn = next(
        n for n in ast.walk(ast.parse(SESSION_RESUME.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "render_status_report"
    )

    def labels_of(node: ast.AST) -> set[str]:
        out: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.JoinedStr):
                literal = "".join(
                    v.value for v in sub.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                out |= set(re.findall(r"\b([A-Z]{3,}):", literal))
        return out

    conditional: set[str] = set()
    for node in fn.body:
        if isinstance(node, ast.If):
            conditional |= labels_of(node)
    return labels_of(fn) - conditional, conditional


def _check_status_block(doc_text: str, live: str) -> None:
    """Compare the ``/status`` block against the emitter's canon and a live drive.

    Raises ``AssertionError`` on drift. Factored out of the test so the negative
    twin below can drive it against a mutated copy -- a pin whose loosening is
    not witnessed by a must-fail case re-loosens on the next refactor.

    Two directions, because one-way is how the retired banner pin went blind:
    the block's labels must EQUAL the unconditionally-emitted set (so an added,
    removed or renamed field all red), and any conditional label must be
    documented in ``RECORDING.md`` so a new one forces a troubleshooting row
    rather than a stale quoted block.

    Values are compared only where they are session-independent. The surface
    counts are elided ``<N>`` on purpose (storyboard rule 5) and REPO/BRANCH are
    the target's own, so neither is compared."""
    fence = "\n".join(_raw_fence_after(doc_text, "The `/status` read-out"))
    doc_labels = set(re.findall(r"\b([A-Z]{3,}):", fence))
    uncond, cond = _status_canon_labels()
    assert doc_labels, "the /status block lost its labels"
    assert doc_labels == uncond, (
        "the /status block's labels drifted from render_status_report's "
        f"unconditional set.\n  block only: {sorted(doc_labels - uncond)}\n"
        f"  canon only: {sorted(uncond - doc_labels)}"
    )
    recording = DEMO_RECORDING.read_text(encoding="utf-8")
    undocumented = [lb for lb in cond if lb not in recording]
    assert not undocumented, (
        f"render_status_report can print {undocumented} conditionally and "
        "RECORDING.md's troubleshooting table does not mention it, so a "
        "recorder meeting that line has no row to read"
    )
    # Every label in the block must really be printed by a live drive.
    live_labels = set(re.findall(r"\b([A-Z]{3,}):", live))
    missing = sorted(doc_labels - live_labels)
    assert not missing, (
        f"the /status block names fields the script did not print: {missing}\n"
        f"live was:\n{live}"
    )


def test_storyboard_status_readout_labels_are_live():
    """The ``/status`` block is the hero's orientation beat, and it replaced a
    banner block that claimed on-screen text the UI never draws. See
    ``_check_status_block`` for what is compared and why."""
    _check_status_block(DEMO_STORYBOARD.read_text(encoding="utf-8"),
                        _drive_resume("--mode", "status"))


def test_storyboard_status_blueprint_value_is_the_in_session_one():
    """``blueprint=`` is the one value in the block that depends on WHEN it was
    driven, and the beat is filmed from inside a session. A shell drive before
    any session reads ``missing``; the hero session's SessionStart has already
    auto-started a blueprint, so the camera sees ``found``. The block quoting
    ``missing`` would send a recorder to a troubleshooting table over a correct
    read-out.

    ``cc/blueprints/`` is gitignored, so a fresh clone and CI have no blueprint
    and a live comparison there would red on a correct block. The pin therefore
    compares only where this tree actually has one, and says so rather than
    quietly passing."""
    fence = "\n".join(_raw_fence_after(
        DEMO_STORYBOARD.read_text(encoding="utf-8"), "The `/status` read-out"))
    doc = re.search(r"blueprint=(\w+)", fence)
    assert doc, "the /status block lost its blueprint= value"
    live = re.search(r"blueprint=(\w+)", _drive_resume("--mode", "status"))
    assert live, "the live read-out printed no blueprint= value"
    if live.group(1) == "missing":
        pytest.skip("this tree has no blueprint (gitignored); nothing to compare")
    assert doc.group(1) == live.group(1), (
        f"the /status block quotes blueprint={doc.group(1)} but an in-session "
        f"drive reads blueprint={live.group(1)}"
    )


_EXPLAIN_MARKER = "The per-path enforcement read-out"
_EXPLAIN_PATHS = ("src/utils.py", "tools/cc/hooks/session_start.py")


def _explain_arms(doc_text: str) -> dict[str, list[str]]:
    """The ``--explain`` fence split into one arm per path, keyed on the path in
    its ``$ ...`` prompt line.

    Binding each arm to its own path is the point: comparing a live line against
    the WHOLE fence lets the two arms be swapped -- the storyboard then says the
    adopter's source is DENIED and the protected hook is allowed, the hero's
    floor beat inverted, with the suite green."""
    arms: dict[str, list[str]] = {}
    current: str | None = None
    for ln in _raw_fence_after(doc_text, _EXPLAIN_MARKER):
        if ln.startswith("$ "):
            current = next((p for p in _EXPLAIN_PATHS if ln.rstrip().endswith(p)), None)
            assert current, f"the --explain fence has a $ line for no known path: {ln!r}"
            arms[current] = []
        elif current is not None:
            arms[current].append(ln)
    return arms


def _check_explain_block(doc_text: str, drives: dict[str, str]) -> None:
    """Compare each ``--explain`` arm against its OWN live drive.

    Raises ``AssertionError`` on drift; factored out so the negative twins can
    drive it against mutated copies.

    Compared per arm, by LINE membership rather than substring -- a substring
    test passes a truncating reword, which is the fragment-pin class
    ``_assert_clauses_match`` exists to close: the ``Path:`` line, both
    predicate lines, the ``live state`` line, and the verdict up to the clause
    that names whether a plan is active (that tail, and only that tail, varies
    with the session). The ``live state`` line is compared whole on purpose: it
    is the only place a paste from a maintenance-mode drive shows, and the
    ``Path:`` and predicate lines are byte-identical with the variable set."""
    arms = _explain_arms(doc_text)
    assert set(arms) == set(_EXPLAIN_PATHS), (
        f"the --explain block documents {sorted(arms)}; the pin expects "
        f"{sorted(_EXPLAIN_PATHS)}"
    )
    tail = "; edits require an active plan"
    for path, live in drives.items():
        arm = arms[path]
        for ln in live.splitlines():
            bare = ln.strip()
            if not bare:
                continue
            if bare.startswith("=>"):
                head = ln.split(tail)[0] if tail in ln else ln
                assert any(a.startswith(head) for a in arm), (
                    f"the --explain block's {path} verdict drifted.\n"
                    f"live head not in that arm: {head!r}"
                )
            elif ln.startswith("Path:") or bare.startswith(
                ("plan_guard :", "write_guard:", "live state :")
            ):
                assert ln in arm, (
                    f"the --explain block drifted from the live read-out for "
                    f"{path}.\n  live line not in that arm: {ln!r}"
                )


def test_storyboard_explain_readout_matches_the_live_predicates():
    """The ``--explain`` block is the hero's floor beat and the most
    deterministic beat in the take, so it is pinned per arm against both live
    drives. See ``_check_explain_block`` for what is compared and why."""
    _check_explain_block(
        DEMO_STORYBOARD.read_text(encoding="utf-8"),
        {p: _drive_resume("--explain", p) for p in _EXPLAIN_PATHS},
    )


def test_the_new_readout_pins_red_on_the_drift_they_claim_to_catch():
    """Earn the red for the two read-out pins, in-memory, on the three mutants a
    2026-10-02 review proved the first draft of them passed.

    The first draft compared live lines against the whole joined fence, so a
    truncating reword, an arm swap and a maintenance-mode paste were all green;
    and the label pin ran doc->live only, so a label the canon grew was
    invisible. Each mutation below is one of those, and each must now raise. A
    loosened pin that nothing must-fails re-loosens on the next refactor."""
    doc = DEMO_STORYBOARD.read_text(encoding="utf-8")
    drives = {p: _drive_resume("--explain", p) for p in _EXPLAIN_PATHS}
    live_status = _drive_resume("--mode", "status")

    _check_explain_block(doc, drives)           # control: the real pair passes
    _check_status_block(doc, live_status)

    # (a) the two arms' write_guard verdicts swapped -- the floor beat inverted
    swapped = doc.replace(
        "  write_guard: allowed -- unprotected", "  write_guard: @@HOLD@@", 1
    ).replace(
        "  write_guard: DENIED -- protected zone `tools/cc/`",
        "  write_guard: allowed -- unprotected", 1
    ).replace(
        "  write_guard: @@HOLD@@",
        "  write_guard: DENIED -- protected zone `tools/cc/`", 1
    )
    assert swapped != doc, "the arm-swap mutation did not apply"
    with pytest.raises(AssertionError, match="drifted"):
        _check_explain_block(swapped, drives)

    # (b) a predicate line truncated -- the reason dropped
    truncated = doc.replace(
        "  plan_guard : exempt  (exempt -- harness-universal prefix `tools/cc/`)",
        "  plan_guard : exempt", 1
    )
    assert truncated != doc, "the truncation mutation did not apply"
    with pytest.raises(AssertionError, match="drifted"):
        _check_explain_block(truncated, drives)

    # (c) the allowed arm pasted from a maintenance-ON drive
    maint = doc.replace(
        "  live state : maintenance mode off; plan none active",
        "  live state : maintenance mode ON -- protected-zone + plan checks "
        "bypassed this session; plan none active", 1
    )
    assert maint != doc, "the maintenance-mode mutation did not apply"
    with pytest.raises(AssertionError, match="drifted"):
        _check_explain_block(maint, drives)

    # (d) the canon grows a /status label the block does not carry
    with pytest.raises(AssertionError, match="drifted from render_status_report"):
        _check_status_block(
            doc.replace("REPO:     demo-target", "REPO:     demo-target\nPLAN:     none", 1),
            live_status,
        )


_BANNER_ON_SCREEN_RE = re.compile(
    r"banner[^.\n]{0,60}\b(header|on screen|appears|scrolls|carries|go by)", re.I
)
_BANNER_TOMBSTONE = "### Why there is no banner block"
_NEGATION_RE = re.compile(r"\b(never|not|no|cannot|without|instead of)\b", re.I)


def test_no_demo_doc_claims_the_banner_is_on_screen():
    """The class guard for this pair's oldest and most-repeated defect.

    The SessionStart banner is never drawn on screen: an exit-0 hook's plain
    stdout reaches Claude Code's debug log and the model's context, and the UI
    renders none of it. Three shipped sites claimed otherwise for weeks, a
    recorder followed one and waited for a frame that cannot exist, and the
    2026-10-02 fix caught the hero but left the zero-to-ahead clip and two
    walkthrough chapters -- an instance fix where the defect was a class.

    The only mechanical trace of the claim anywhere was the banner-label assert
    in the pin above, and that was deleted with the block it read. This is its
    replacement. Scope honestly: it matches an ENUMERATED set of phrasings
    (``banner`` within 60 characters of ``header``/``on screen``/``appears``/
    ``scrolls``/``carries``/``go by``), so it catches three of the four
    instances found on 2026-10-02 and would have missed the fourth
    ("This repo's own banner: the depth counter", which implies filming without
    using any of those words). It raises the cost of the next instance; it does
    not prove the class absent. A sentence carrying a negation before or after
    the claim, or an ``*Avoid:*`` marker, is a denial and passes; the tombstone
    section is exempt entirely, since it exists to state the negative."""
    for path in (DEMO_STORYBOARD, DEMO_RECORDING):
        text = path.read_text(encoding="utf-8")
        head, _, tail = text.partition(_BANNER_TOMBSTONE)
        # the tombstone runs to the next heading
        exempt_end = tail.index("\n### ") if "\n### " in tail else len(tail)
        scanned = head + tail[exempt_end:]
        # Markdown wraps prose, so a sentence's negation often sits on a
        # different physical line than its claim. Scan sentences, not lines.
        paragraphs = re.split(r"\n\s*\n", scanned)
        offenders = []
        for para in paragraphs:
            flat = " ".join(para.split())
            for sentence in re.split(r"(?<=[.;])\s+", flat):
                if not _BANNER_ON_SCREEN_RE.search(sentence):
                    continue
                if _NEGATION_RE.search(sentence) or "Avoid:" in sentence:
                    continue
                offenders.append(sentence[:120])
        assert not offenders, (
            f"{path.relative_to(REPO_ROOT)} claims the SessionStart banner "
            f"reaches the screen: {offenders}. It does not -- an exit-0 hook's "
            "stdout goes to the debug log and the model. Film `/status` or "
            "`/read-summary` instead, or put the sentence in "
            f"'{_BANNER_TOMBSTONE}'."
        )


_HERO_ROW_RE = re.compile(r"^\| \*{0,2}(\d+) ([A-Za-z][^|*]*?)\*{0,2} \|", re.M)
_BEAT_REF_RE = re.compile(r"\b[Bb]eats? (\d+)(?: to (\d+))?(?: and (\d+))?")


def _hero_rows() -> dict[int, str]:
    """``{beat number: beat name}`` parsed from the hero table, which is the
    only place the numbering is defined."""
    text = DEMO_STORYBOARD.read_text(encoding="utf-8")
    hero = text[text.index('## HERO: "the human holds the key"'):text.index("### End card")]
    rows = {int(n): name.strip() for n, name in _HERO_ROW_RE.findall(hero)}
    assert rows, "the hero table's beat rows no longer parse"
    return rows


def _beat_named(rows: dict[int, str], needle: str) -> int:
    hits = [n for n, name in rows.items() if needle.lower() in name.lower()]
    assert len(hits) == 1, f"expected exactly one hero beat named {needle!r}, got {hits}"
    return hits[0]


def test_every_beat_reference_matches_the_hero_table():
    """The prose anchors, which the 2026-10-02 heading rename did NOT fix.

    That rename decoupled the quoted-output PINS from beat numbers, because a
    re-cut had stranded them twice. It left roughly fifteen human-facing
    couplings: "one cut before beat 5", "Phase 2, beat 5", four `Beat 4:`
    troubleshooting rows, "(beats 1 to 4)" in the checklist. The troubleshooting
    table -- the surface a recorder opens the moment something goes wrong -- is
    the most beat-coupled text in the pair, and nothing mechanical reads it. A
    third re-cut silently points every one of them at the wrong beat.

    This parses the hero table (the only definition of the numbering) and binds
    the load-bearing references to it by NAME, so a renumber reds instead of
    rotting. Range-checks everything else."""
    rows = _hero_rows()
    lockout = _beat_named(rows, "Lockout")
    relaunch = _beat_named(rows, "Relaunch")
    floor = _beat_named(rows, "floor")
    orient = _beat_named(rows, "Orient")

    storyboard = DEMO_STORYBOARD.read_text(encoding="utf-8")
    recording = DEMO_RECORDING.read_text(encoding="utf-8")

    # 1. Every beat number mentioned anywhere must exist in the table. The
    #    zero-to-ahead clip has its own 1-5 numbering, so the range check is
    #    the honest bound here, not an identity.
    for doc, text in (("STORYBOARD.md", storyboard), ("RECORDING.md", recording)):
        for match in _BEAT_REF_RE.finditer(text):
            for group in match.groups():
                if group is None:
                    continue
                assert int(group) in rows, (
                    f"bench/demo/{doc} references beat {group} "
                    f"({match.group(0)!r}); the hero table defines {sorted(rows)}"
                )

    # 2. The single cut and phase 2 must name the Relaunch beat.
    for doc, text in (("STORYBOARD.md", storyboard), ("RECORDING.md", recording)):
        for phrase in ("one cut before beat ", "Phase 2, beat "):
            at = text.find(phrase)
            if at == -1:
                continue
            got = int(re.match(r"(\d+)", text[at + len(phrase):]).group(1))
            assert got == relaunch, (
                f"bench/demo/{doc} says {phrase!r}{got}, but the hero table's "
                f"Relaunch beat is {relaunch}"
            )

    # 3. Bind each troubleshooting-row FORM to the beat it actually describes.
    #    Three forms ship, and an earlier draft of this check assumed only the
    #    Lockout and Relaunch beats had rows -- false, beat 2 has the
    #    interpreter-fallback row. Each form is keyed to its own beat by name so
    #    a renumber reds on the row rather than range-checking vacuously.
    row_forms = (
        (r"^\| Beat (\d+): ", lockout, "Lockout"),
        (r"^\| Beat (\d+)'s ", relaunch, "Relaunch"),
        (r"^\| Beat (\d+) prints ", orient, "Orient"),
    )
    for pattern, expected, name in row_forms:
        found = {int(n) for n in re.findall(pattern, recording, re.M)}
        assert found, (
            f"RECORDING.md lost every troubleshooting row of the form "
            f"{pattern!r}; if the row moved, re-bind it here rather than "
            "deleting the check"
        )
        assert found == {expected}, (
            f"RECORDING.md has {pattern!r} rows for beat(s) {sorted(found)}, but "
            f"the hero table's {name} beat is {expected}"
        )

    # 4. The checklist's maintenance-mode range must stop at the beat before
    #    Relaunch: beat 5 is the one place the variable is deliberately set.
    at = storyboard.index("(beats 1 to ")
    upper = int(re.match(r"(\d+)", storyboard[at + len("(beats 1 to "):]).group(1))
    assert upper == relaunch - 1, (
        f"the checklist scrubs maintenance mode for beats 1 to {upper}, but the "
        f"Relaunch beat (where it is set on purpose) is {relaunch}"
    )

    # 5. The floor beat is referenced as carrying the floor if the lockout misses.
    assert f"Beats {floor} to {relaunch}" in storyboard, (
        f"the fallback no longer names 'Beats {floor} to {relaunch}'; the hero "
        f"table has floor={floor}, relaunch={relaunch}"
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
