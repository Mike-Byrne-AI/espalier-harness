"""Pin the perf_smells scanner's behavioral contract.

Earn-the-gate: every functional GENERAL_PATTERNS label surfaces in
scan_file's counts dict. The fixture omits a `nested_loop_pattern`
shape because the scanner's regex (`for...\\n\\s+for`) uses `\\n`,
which never appears in src.splitlines()-derived lines -- pre-existing
limitation. If the scanner adds multi-line support in the future, the
fixture and this assertion should expand together.

Live-scan exemption: EXEMPT_PREFIXES keeps the fixture out of normal
`espalier scan perf_smells` runs.

TP-105 / TP-143 / FM-7 §1.7 close.
"""
from __future__ import annotations

from pathlib import Path

from espalier.scanners import perf_smells as scn


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_perf_smells_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_perf_smells_negatives.py"


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """scan_file the fixture with the default GENERAL_PATTERNS set;
    assert each currently-detectable label has at least one hit."""
    patterns = scn.select_patterns()
    result = scn.scan_file(str(FIXTURE_PATH), patterns)
    # Patterns the scanner can currently match line-by-line. The
    # `nested_loop_pattern` regex uses `\n` and is structurally dead
    # in scan_file's single-line search; documented in the fixture.
    detectable_labels = {
        "subprocess_shell",
        "global_import_star",
        "bare_open",
    }
    missing = {
        label for label in detectable_labels
        if result["counts"].get(label, 0) == 0
    }
    assert not missing, (
        f"earn-the-gate: scanner failed to detect patterns {missing}. "
        f"Counts seen: {result['counts']}."
    )


def test_each_ml_pattern_detected_independently(tmp_path: Path) -> None:
    """C-1: every ML label must be detectable ON ITS OWN, not masked by
    device_transfer (``model.cuda()`` alone satisfying a bulk
    ``files_with_hits >= 1``). Each label gets a minimal single-line snippet
    that triggers only itself, so defanging any one pattern's regex (e.g.
    ``model_forward`` at perf_smells.py:24) reds exactly that label here."""
    ml_cases = {
        "device_transfer": "x = tensor.cuda()",
        "tokenize_call": "ids = tokenizer(text)",
        "model_forward": "out = model(inputs)",
        "no_grad_block": "with torch.no_grad():",
        "autocast_block": "with torch.cuda.amp.autocast():",
        "load_model": 'm = AutoModel.from_pretrained("bert-base")',
    }
    patterns = scn.select_patterns(ml=True)
    for label, line in ml_cases.items():
        snippet = tmp_path / f"ml_{label}.py"
        snippet.write_text(line + "\n", encoding="utf-8")
        result = scn.scan_file(str(snippet), patterns)
        assert result["counts"].get(label, 0) >= 1, (
            f"ML pattern {label!r} not detected in {line!r} — masked or "
            f"defanged. counts={result['counts']}"
        )


def test_sync_request_api_pattern_detected(tmp_path: Path) -> None:
    """C-1: the API-only ``sync_request`` label
    (``requests.get/post/put/delete/patch``) has zero coverage otherwise.
    Pin it under ``select_patterns(api=True)`` so a regex defang reds."""
    snippet = tmp_path / "api.py"
    snippet.write_text("r = requests.get(url)\n", encoding="utf-8")
    result = scn.scan_file(str(snippet), scn.select_patterns(api=True))
    assert result["counts"].get("sync_request", 0) >= 1, (
        f"sync_request not detected; counts={result['counts']}"
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: scan_file the clean-but-tempting negatives corpus
    with the default GENERAL_PATTERNS set; assert ZERO findings. Proves
    the scanner stays silent on defanged variants of the same shapes the
    earn-the-gate test confirms it fires on (TP-156 Tier 1)."""
    patterns = scn.select_patterns()
    result = scn.scan_file(str(NEG_FIXTURE_PATH), patterns)
    assert result["total_hits"] == 0, (
        f"perf_smells fired on the negatives corpus; expected zero. "
        f"Counts seen: {result['counts']}."
    )


def test_bare_open_skips_strings_comments_and_dotted(tmp_path: Path) -> None:
    """TP-217b: bare_open is token-aware — `open(` inside a string literal or a
    comment, and a dotted `os.open`/`webbrowser.open`, must NOT count; a real
    bare builtin `open(...)` still does. `with open(...)` stays exempt (matching
    the `(?<!with\\s)` lookbehind the detector replaces, and the existing
    shape_open_with_context_manager negative fixture)."""
    src = (
        'import os\n'
        'data = "a string mentioning open( as data, not code"\n'
        '# explaining how to open( a file in a comment\n'
        'fd = os.open("/tmp/x", os.O_RDONLY)\n'
        'import webbrowser\n'
        'webbrowser.open("http://x")\n'
        'real = open("/tmp/y")\n'
        'with open("/tmp/z") as fh:\n'
        '    fh.read()\n'
    )
    p = tmp_path / "probe.py"
    p.write_text(src, encoding="utf-8")
    result = scn.scan_file(str(p), [("bare_open", dict(scn.GENERAL_PATTERNS)["bare_open"])])
    linenos = sorted(h["lineno"] for h in result["hits"]["bare_open"])
    # Only the one bare builtin open() call (line 7 `real = open(...)`). Line 8
    # `with open(...)` is exempt; the dotted/string/comment cases never fire.
    assert linenos == [7], (
        f"bare_open token detector fired on the wrong lines: {linenos}. "
        f"Expected only the bare builtin open() call at line 7 (`with open()` is exempt)."
    )


def test_bare_open_skips_def_open(tmp_path: Path) -> None:
    """TP-275 1-A: a function DEFINITION named ``open`` (``def open(...)``) is not
    a bare builtin ``open()`` call — the ``def`` keyword one token back must
    exempt it. A real bare ``open(...)`` call on a later line still counts."""
    src = (
        "class C:\n"
        "    def open(self, path):\n"
        "        return path\n"
        "\n"
        'real = open("/tmp/y")\n'
    )
    p = tmp_path / "defopen.py"
    p.write_text(src, encoding="utf-8")
    result = scn.scan_file(str(p), [("bare_open", dict(scn.GENERAL_PATTERNS)["bare_open"])])
    linenos = sorted(h["lineno"] for h in result["hits"]["bare_open"])
    # Only the real bare open() call on line 5; the `def open(` on line 2 is a
    # definition, not a call, and must be exempt.
    assert linenos == [5], (
        f"bare_open fired on the wrong lines: {linenos}. Expected only the real "
        f"bare open() call at line 5 (`def open(` is a definition, not a call)."
    )


def test_fixture_skipped_by_live_scan() -> None:
    """EXEMPT_PREFIXES added in TP-143 must keep the fixture out of
    live scans."""
    report = scn.scan_repo(str(REPO_ROOT))
    fixture_rel = "tests/fixtures/test_perf_smells_positives.py"
    fixture_rows = [
        r for r in report["results"]
        if fixture_rel in r["file"].replace("\\", "/")
    ]
    assert fixture_rows == [], (
        f"EXEMPT_PREFIXES did not skip the fixture; found "
        f"{len(fixture_rows)} per-file row(s)."
    )


def test_n_plus_one_is_documented_dead_sister(tmp_path: Path) -> None:
    """TP-152 E-7: n_plus_one mirrors nested_loop_pattern's `\\n`-based
    multi-line shape, so it is inert under scan_file's line-by-line search;
    it is additionally API-only (espalier scan never passes --api). Pin both
    facts so the dead detector can't masquerade as live coverage."""
    api_labels = dict(scn.API_PATTERNS)
    assert "n_plus_one" in api_labels
    assert r"\n" in api_labels["n_plus_one"]  # multi-line by construction
    # not in the GENERAL set the espalier CLI actually scans
    assert "n_plus_one" not in dict(scn.GENERAL_PATTERNS)
    # even with --api, the \n regex matches nothing line-by-line
    snippet = tmp_path / "nplus.py"
    snippet.write_text(
        "def f(users):\n    for u in users:\n        u.query()\n",
        encoding="utf-8",
    )
    result = scn.scan_file(str(snippet), scn.select_patterns(api=True))
    assert result["counts"].get("n_plus_one", 0) == 0


def test_nested_loop_pattern_is_documented_dead(tmp_path: Path) -> None:
    """TP-191 W6: nested_loop_pattern's `\\n`-based multi-line regex is inert
    under scan_file's line-by-line search. Unlike n_plus_one it lives in
    GENERAL_PATTERNS (every `espalier scan` evaluates it) yet matches nothing.
    Pin both facts so the dead detector can't masquerade as live coverage."""
    general = dict(scn.GENERAL_PATTERNS)
    assert "nested_loop_pattern" in general
    assert r"\n" in general["nested_loop_pattern"]  # multi-line by construction
    # not in the API-only set (the n_plus_one sister lives there)
    assert "nested_loop_pattern" not in dict(scn.API_PATTERNS)
    # even on a genuine nested loop, the \n regex matches nothing line-by-line
    snippet = tmp_path / "nested.py"
    snippet.write_text(
        "def f(rows):\n    for r in rows:\n        for c in r:\n            pass\n",
        encoding="utf-8",
    )
    result = scn.scan_file(str(snippet), scn.select_patterns(api=False))
    assert result["counts"].get("nested_loop_pattern", 0) == 0
