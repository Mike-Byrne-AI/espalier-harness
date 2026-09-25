"""TP-122: QUICKSTART's session-start banner + doctor JSON samples
must reference keys/fields that the live binaries actually emit.

Sister-shape to
``tests/test_documented_claims.py::TestReadmeDoctorExampleMatchesLiveOutput``
(TP-29) but extended to a second public-facing doc surface. README
is the 30-second pitch; QUICKSTART is the install-and-verify walk
that adopters follow line-by-line — silent drift here trains
adopters to mistrust the docs.

Failure modes prevented:
- QUICKSTART doctor JSON sample references a key (e.g.
  ``hooks``, ``settings``, ``integrity``) that the live binary no
  longer emits. Pre-TP-122 the sample showed exactly this fictional
  shape.
- QUICKSTART session-start banner sample omits the ``Memory:`` and
  ``Blueprint:`` lines that the live hook emits, training adopters
  to expect a 5-line block when the live output is 8+.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _json_key_paths import key_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "docs" / "QUICKSTART.md"
HOOK = REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestQuickstartDoctorExampleMatchesLiveOutput:
    """The QUICKSTART doctor JSON example must reference only keys
    the live ``espalier doctor`` command emits."""

    def _extract_doctor_keys(self, text: str) -> set[str]:
        """Find the doctor JSON sample block and return every key PATH in it.

        ⚠ This returned ``set(parsed.keys())`` — the OUTERMOST keys only —
        while claiming to check "keys the live command emits". The sample's
        top-level keys were all real; the false one was
        ``checks.presence.status``, two layers down, where a depth-1 compare
        cannot look. `presence` has six keys and `status` is not among them,
        and this test was green for as long as the defect existed (DEF-468).
        Recursing is the whole fix; `key_paths` is shared with the README twin
        so the two cannot drift back apart.
        """
        candidates = []
        for match in re.finditer(
            r"```json\s*\n([\s\S]+?)\n```", text
        ):
            block = match.group(1)
            if '"status"' not in block:
                continue
            try:
                parsed = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "status" in parsed:
                candidates.append(parsed)
        # ⚠ Selection used to be first-fence-wins, which is a silent shadow.
        # QUICKSTART already discusses `source_checkout` mode in prose ABOVE
        # the healthy sample, so illustrating that mode with a JSON block is
        # one ordinary edit away — and source-checkout's key paths are a
        # strict SUBSET of the initialized ones, so the gate would check the
        # earlier block and be unconditionally green. Measured: with a clean
        # block inserted first, this file goes fully green on a QUICKSTART
        # whose real sample carries `checks.presence.status` again, including
        # the recursion pin below, because the decoy happens to contain the
        # three paths that pin demands. Refuse the ambiguity instead.
        assert len(candidates) <= 1, (
            f"{len(candidates)} ```json fences in this doc carry a top-level "
            f"`status` key. This gate checks ONE sample and cannot tell which "
            f"is the doctor output, so it would silently verify the wrong "
            f"block. Anchor the doctor sample or split this gate."
        )
        return key_paths(candidates[0]) if candidates else set()

    def test_quickstart_doctor_keys_subset_of_live(self, initialized_repo_root):
        """`DEF-575`: drive an INITIALIZED tree, not whatever tree the suite
        happens to be running in.

        The sample depicts an initialized repo -- `checks.audit`, `checks.diff`,
        `checks.self_host`. `doctor` returns a strict SUBSET of those keys
        (`checks.presence` alone) for `source_checkout` mode, which is what any
        tree without the init-generated runtime artifacts reports -- and those
        artifacts are gitignored, so a fresh `git clone` is source_checkout too.
        Pointing this at `REPO_ROOT` therefore asserted "the maintainer ran init
        here", not "the sample is accurate", and it passed only on the tree it
        was written on (docs/STANDING_PRINCIPLES.md §12).

        VERIFIED RED 2026-08-14 on a plain `git clone`: 1 failed, 3 passed,
        missing `checks.audit`, `checks.audit.status`, `checks.diff`,
        `checks.diff.fingerprint_changed`, `checks.diff.status`. Since
        `.github/workflows/test.yml` runs the full suite on a fresh checkout and
        nothing runs `espalier init` first, this was red in CI too -- masked only
        because CI was off -- and its message ("fix the SAMPLE, not
        the code") sent the reader at the one thing that was correct.

        `initialized_repo_root` reports `mode=initialized_self_host` with all six
        check nodes, so the comparison is against the mode the sample actually
        depicts, on every tree.
        """
        text = _read(QUICKSTART)
        demo_keys = self._extract_doctor_keys(text)
        assert demo_keys, (
            "Cannot locate or parse QUICKSTART doctor JSON sample. "
            "If the sample was removed, delete this test."
        )
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "doctor",
             str(initialized_repo_root), "--skip-self-host"],
            capture_output=True,
            text=True, encoding="utf-8",
        )
        try:
            live_obj = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"espalier doctor output is not valid JSON: {exc}\n"
                f"stdout: {result.stdout[:500]}"
            )
        live_keys = key_paths(live_obj)
        unknown_keys = demo_keys - live_keys
        assert not unknown_keys, (
            f"QUICKSTART doctor sample references key paths not in live "
            f"output: {sorted(unknown_keys)}.\n"
            f"Live paths under that parent: "
            f"{sorted(k for k in live_keys if any(u.startswith(k.rsplit('.', 1)[0] + '.') for u in unknown_keys))}\n"
            f"Refresh docs/QUICKSTART.md against current "
            f"`espalier doctor .` output — fix the SAMPLE, not the code.\n"
            f"(Live output here comes from the `initialized_repo_root` fixture, "
            f"NOT this checkout, so 'my tree isn't init'ed' is not the cause — "
            f"see `DEF-575` for why it used to be.)"
        )

    def test_the_compare_is_recursive(self):
        """Earn-the-red guard for the depth-1 regression itself.

        Reverting `_extract_doctor_keys` to `set(parsed.keys())` would make
        the test above green again with the sample still wrong, and nothing
        else would notice. Pin the property directly: a nested key must be
        reachable, or the gate is depth-1 again.
        """
        nested = key_paths({"checks": {"presence": {"status": "pass"}}})
        assert "checks.presence.status" in nested, (
            "key_paths stopped recursing — the gate is depth-1 again and "
            "cannot see the class of defect it exists for (DEF-468)."
        )
        # ⚠ Pinned against a SYNTHETIC block, not against live QUICKSTART.
        # The first cut asserted the live doc still yielded
        # {status, checks, checks.presence} — but that sample is captioned
        # "truncated to the most-watched fields", so trimming it further is a
        # CORRECT edit, and it red this pin with the message "the extractor is
        # no longer returning nested paths". That sends the next reader into
        # `_json_key_paths.py` hunting a bug that is not there, and the
        # low-friction way out is to loosen this assertion — re-creating the
        # born-weak gate the commit existed to end. A pin must own its input.
        fixture = (
            '```json\n'
            '{"status": "pass", "checks": {"presence": {"surface_present": true}}}\n'
            '```\n'
        )
        assert "checks.presence.surface_present" in self._extract_doctor_keys(
            fixture
        ), "the extractor is no longer returning nested paths"

    def test_a_second_status_sample_is_refused_not_shadowed(self):
        """Two candidate blocks must fail loudly, never silently pick one.

        Earn-the-red for the shadowing gap: a decoy block placed BEFORE the
        doctor sample used to be selected instead of it, and because the
        source-checkout key set is a subset of the initialized one, the gate
        stayed green on a QUICKSTART carrying the DEF-468 defect again.
        """
        two = (
            '```json\n{"status": "pass", "checks": {}}\n```\n\n'
            '```json\n{"status": "pass", "failures": []}\n```\n'
        )
        with pytest.raises(AssertionError, match="carry a top-level"):
            self._extract_doctor_keys(two)


_BANNER_DOCS = ("docs/QUICKSTART.md", "docs/HOOKS.md", "docs/WORKFLOW.md")
_BANNER_OPEN = "=== Espalier-Harness === Session Start ==="
_LABEL_RE = re.compile(r"^([A-Z][A-Za-z_]*):")


def _banner_head(block: str) -> list[str]:
    """The lines of a banner after its `===` opener, up to its first `---` section."""
    head: list[str] = []
    for line in block.splitlines()[1:]:
        if line.startswith("---"):
            break
        head.append(line)
    return head


def _labels(lines: list[str]) -> set[str]:
    out: set[str] = set()
    for line in lines:
        m = _LABEL_RE.match(line.strip())
        if m:
            out.add(m.group(1) + ":")
    return out


def _doc_banner_sample(text: str, rel: str) -> str:
    m = re.search(r"```\n(" + re.escape(_BANNER_OPEN) + r"[\s\S]+?)\n```", text)
    assert m, f"{rel}: no fenced session-start banner sample"
    return m.group(1)


def _line(lines: list[str], label: str, where: str) -> str:
    """The banner line carrying ``label``, or a failure that names the doc --
    never a bare StopIteration."""
    hits = [l for l in lines if l.startswith(label)]
    assert hits, f"{where}: no `{label}` line in the banner"
    return hits[0]


# Lines whose VALUE is the same on every fresh init tree, so a doc sample must
# carry them verbatim: the label-set check above them is value-blind by design
# (Repo, Branch, Status, Host and Memory vary by tree and machine).
_STABLE_LABELS = ("Surface:", "Integrity:", "Commands:", "Run /status")


class TestBannerSamplesMatchTheDrivenHook:
    """DEF-470 / DEF-518 (§C21): every shipped doc that quotes the SessionStart
    banner is checked against ONE driven capture -- the deployed hook run on a
    real `espalier init` tree -- in both directions.

    The predecessor kept a hand-typed label tuple that rotted in the permissive
    direction (it never learned `Host:`, so it blocked the refresh that was
    correcting the sample) and watched one doc. The samples in HOOKS.md and
    WORKFLOW.md drifted unwatched -- one missing lines the hook prints, the
    other inventing a `Blueprint:` line the hook cannot produce -- and
    QUICKSTART promised `Stack: unknown` on a tree `init` fingerprints as
    `python`. Verified red on all three docs before they were regenerated.
    """

    @pytest.fixture(scope="class")
    def driven_banner(self, adopter_tree, tmp_path_factory) -> list[str]:
        """Head lines of the banner the DEPLOYED hook prints on a copy of the
        adopter tree (a copy, because a startup SessionStart begins a blueprint
        and writes session state)."""
        import shutil
        copy = tmp_path_factory.mktemp("banner") / "tree"
        shutil.copytree(adopter_tree, copy, symlinks=True)
        env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
        env["CLAUDE_PROJECT_DIR"] = str(copy)
        result = subprocess.run(
            [sys.executable, str(copy / "tools" / "cc" / "hooks" / "session_start.py")],
            cwd=str(copy),
            input=json.dumps({
                "hook_event_name": "SessionStart", "source": "startup",
                "session_id": "banner-pin",
            }),
            capture_output=True, text=True, env=env, timeout=60, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert ctx.startswith(_BANNER_OPEN), ctx[:200]
        head = _banner_head(ctx)
        # The floor the capture must clear before it is allowed to judge a doc:
        # every line the hook prints unconditionally. A hook regression that
        # drops one reds HERE, as a hook fault, not below as a doc fault.
        assert _labels(head) >= {
            "Host:", "Repo:", "Branch:", "Status:", "Memory:", "Blueprint:",
            "Surface:", "Integrity:", "Commands:",
        }, head
        return head

    @pytest.mark.parametrize("rel", _BANNER_DOCS)
    def test_sample_labels_equal_the_driven_labels(self, rel, driven_banner):
        sample = _banner_head(_doc_banner_sample(_read(REPO_ROOT / rel), rel))
        assert _labels(sample) == _labels(driven_banner), (
            f"{rel}: banner sample labels {sorted(_labels(sample))} != what the "
            f"deployed hook prints {sorted(_labels(driven_banner))}. If the hook "
            f"changed on purpose, regenerate the sample from a driven run; if it "
            f"did not, the hook regressed (the floor in `driven_banner` names the "
            f"unconditional lines) -- fix whichever moved."
        )

    @pytest.mark.parametrize("rel", _BANNER_DOCS)
    def test_stable_lines_equal_the_driven_lines(self, rel, driven_banner):
        """Value-level pin for the lines that do not vary by tree or machine.
        DEF-470 was a wrong VALUE (`Stack: unknown`); the label-set check
        cannot see that class, so the stable lines are compared verbatim."""
        sample = _banner_head(_doc_banner_sample(_read(REPO_ROOT / rel), rel))
        for label in _STABLE_LABELS:
            assert _line(sample, label, rel).split() == _line(driven_banner, label, "hook").split(), (
                f"{rel}: `{label}` line differs from what the deployed hook prints."
            )

    @pytest.mark.parametrize("rel", _BANNER_DOCS)
    def test_sample_blueprint_line_is_one_the_hook_prints(self, rel, driven_banner):
        sample = _banner_head(_doc_banner_sample(_read(REPO_ROOT / rel), rel))
        sample_bp = _line(sample, "Blueprint:", rel)
        driven_bp = _line(driven_banner, "Blueprint:", "hook")
        assert sample_bp.split() == driven_bp.split(), (
            f"{rel}: {sample_bp!r} is not a Blueprint line the hook prints on a "
            f"fresh tree ({driven_bp!r})."
        )

    def test_quickstart_stack_is_what_init_detects(self, driven_banner):
        """QUICKSTART depicts a Python project right after `init`; its Memory
        line must say what init's fingerprint said, not `unknown` (DEF-470)."""
        def stack(lines: list[str]) -> str:
            memory = _line(lines, "Memory:", "banner")
            assert "**Stack:**" in memory, f"Memory line has no Stack field: {memory!r}"
            return memory.split("**Stack:**", 1)[1].strip()
        sample = _banner_head(_doc_banner_sample(_read(QUICKSTART), "docs/QUICKSTART.md"))
        assert stack(sample) == stack(driven_banner)
