"""Pin ``bench/demo/**``'s quoted product output to the live deny templates.

A demo script is a transcript of *claims*. Every quoted hook output in it is a
citation, and citations rot: commit ``441ad96`` changed the protected-zone deny
string and updated the hook's own tests but not ``bench/demo/script.md``, which
went on asserting that the harness protects ``espalier/`` as well as
``tools/cc/``. Nothing was red, because nothing compared the two. The demo is
the credibility surface a viewer sees first, so an over-claim there is worse
than a stale comment.

This file closes that class the same way
``tests/test_write_guard_pattern_message_coupling.py`` closes its own: read the
LIVE template out of ``_denial_reasons`` and compare, rather than pinning a
second copy of the string that can drift in parallel.

Scope is deliberately narrow — it pins the *protected-zone list* a demo file
claims, not the whole template. Pinning every byte would red on every benign
rewording and get neutered; pinning the zone list catches exactly the
over-claim shape that shipped.

Pure file read + in-process import of a hook helper; no subprocess, no Bash
execution path.
"""

# pytest-marker: default-unit  (doc/template comparison over bench/demo/*.md
# plus one in-process import of a hook helper; no subprocess, no guard
# execution path, so it is not a `security` regression test)

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
DEMO_DIR = REPO_ROOT / "bench" / "demo"

# Same idiom as the sibling pin test: put HOOKS_DIR first so the hook helper
# imports standalone, without dragging espalier/ into its zero-import graph.
sys.path.insert(0, str(HOOKS_DIR))
import _denial_reasons  # noqa: E402

# The "Don't:" clause of the live template names the protected zones. Capture
# the backticked paths from it; that list is what a demo file may claim.
_ZONE_CLAUSE_RE = re.compile(
    r"Don't: edit harness files from a regular session \((.*?)\), and don't",
    re.DOTALL,
)
_BACKTICKED_RE = re.compile(r"`([^`]+)`")


def _live_zone_tokens() -> set[str]:
    """Protected-zone tokens the live PROTECTED_ZONE_WRITE template names."""
    template = _denial_reasons.PROTECTED_ZONE_WRITE
    m = _ZONE_CLAUSE_RE.search(template)
    assert m, (
        "could not locate the \"Don't: edit harness files\" clause in the live "
        "PROTECTED_ZONE_WRITE template — the template shape changed and this "
        "pin can no longer read it. Update the parser, do not delete the test."
    )
    return set(_BACKTICKED_RE.findall(m.group(1)))


def _demo_files() -> list[Path]:
    # docs/DEMO.md is the same kind of transcript (the README's demo beat) and
    # drifted half-updated once; it rides the same gate.
    return sorted(DEMO_DIR.glob("*.md")) + [REPO_ROOT / "docs" / "DEMO.md"]


class TestDemoQuotesMatchLiveDenyTemplates:
    """``bench/demo/**`` may not claim a protected zone the hook never emits."""

    def test_demo_zone_claims_are_a_subset_of_the_live_template(self) -> None:
        live = _live_zone_tokens()
        offenders: list[str] = []
        for path in _demo_files():
            text = path.read_text(encoding="utf-8")
            for m in _ZONE_CLAUSE_RE.finditer(text):
                claimed = set(_BACKTICKED_RE.findall(m.group(1)))
                extra = claimed - live
                if extra:
                    line = text[: m.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{line} claims "
                        f"{sorted(extra)} which the live deny string does not "
                        f"name (live zones: {sorted(live)})"
                    )
        assert not offenders, (
            "demo file(s) quote a protected-zone deny that OVER-CLAIMS what the "
            "hook actually protects. A demo is a transcript of claims; this is "
            "the 441ad96 shape recurring. Re-drive the hook and quote it "
            "verbatim:\n  " + "\n  ".join(offenders)
        )

    def test_at_least_one_demo_file_quotes_the_deny(self) -> None:
        """Non-vacuous floor.

        Without this, deleting or rewording every quoted deny in bench/demo/
        turns the assertion above into a permanent silent pass — a gate that
        cannot fire reads as coverage.
        """
        quoting = [
            p.relative_to(REPO_ROOT)
            for p in _demo_files()
            if _ZONE_CLAUSE_RE.search(p.read_text(encoding="utf-8"))
        ]
        assert quoting, (
            "no file under bench/demo/ quotes the protected-zone \"Don't:\" "
            "clause any more. Either the demo stopped showing the seatbelt "
            "(fix the demo) or the template was reworded (update "
            "_ZONE_CLAUSE_RE). Do not leave this test vacuously green."
        )

    def test_bash_variant_headline_matches_the_live_template(self) -> None:
        """The Bash form has its own template; script.md quotes its headline."""
        headline = _denial_reasons.PROTECTED_ZONE_WRITE_BASH.split("{path}")[0]
        assert headline.strip(), "PROTECTED_ZONE_WRITE_BASH lost its headline"
        claimants = [
            p.relative_to(REPO_ROOT)
            for p in _demo_files()
            if "Bash write to protected harness zone" in p.read_text(encoding="utf-8")
        ]
        assert claimants, (
            "no demo file quotes the Bash-variant deny headline; the demo's "
            "third bypass attempt is what that template documents."
        )
        for path in claimants:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
            assert headline in text, (
                f"{path} quotes a Bash-variant deny headline that no longer "
                f"matches the live template {headline!r}"
            )


class TestDemoRelaunchRemedyMatchesLiveHint:
    """The `relaunch with …` fragment a demo quotes must be the one the hook
    emits on this host; a bare `=1 claude` survived in bench/demo/** after the
    hint gained `--continue`, and the operator records the GIF from it."""

    def test_relaunch_remedy_quotes_match_the_live_hint(self, monkeypatch) -> None:
        import _maintenance_mode  # noqa: E402  (same sys.path insert as _denial_reasons)

        # The transcripts were recorded on POSIX; relaunch_hint() is host-keyed
        # and reads sys.platform at CALL time, so pin the dialect here or the
        # Windows CI leg compares a PowerShell-led triple against POSIX quotes.
        monkeypatch.setattr(_maintenance_mode.sys, "platform", "linux")
        live = _maintenance_mode.relaunch_hint()
        offenders = []
        for path in _demo_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "relaunch with `" in line and live not in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()[:90]}")
        assert not offenders, (
            "demo quotes a relaunch the hook no longer emits; re-drive and paste:\n  "
            + "\n  ".join(offenders)
        )
