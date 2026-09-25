"""Fire/silent matrices + witness-set parity for the TP-165 multi-surface-sync
reinject rules (165-A..E).

These PostToolUse sync rules are FRICTIONLESS injectors: each pushes a complete
sister-site witness set (as DATA) when a drift-prone edit lands. This module proves
(a) each rule's positive repro fires and its silent-on-no-op negative stays silent,
and (b) TestWitnessSetParity binds the witness DATA to the live surfaces so it cannot
silently rot (the witness set is itself a multi-surface SoT -- sister to the thing it
guards). Sibling of tests/test_reinject.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from espalier import mirror_registry, surface_contract, surface_impact
from tests._git_oracle import require_is_gitignored

REPO = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _reinject  # noqa: E402


def _fire(tool, tool_input, tmp_path):
    """First payload for a PostToolUse trigger, or '' if silent. tmp_path is the
    per-test session-counter dir; callers stay within REINJECT_SESSION_CAP."""
    out = _reinject.check("PostToolUse", tool, tool_input, tmp_path)
    return out[0] if out else ""


# ── 165-A: REINJECT-HOOK-WITHOUT-WIRING ──────────────────────────────────────

def test_165a_fires_on_write_to_wired_hook(tmp_path):
    out = _fire("Write", {"file_path": "/r/tools/cc/hooks/zzz_probe.py"}, tmp_path)
    assert "wired-hook script" in out
    assert "CANONICAL_HOOK_WIRING" in out  # the witness DATA is in the payload


def test_165a_helper_variant_renders_helper_witness(tmp_path):
    out = _fire("Write", {"file_path": "/r/tools/cc/hooks/_zzz.py"}, tmp_path)
    assert "hook HELPER" in out
    assert "_HOOK_HELPERS" in out
    assert "wired-entries only" in out  # the exact TP-163 _CANONICAL_HOOK_SCRIPTS trap


def test_165a_silent_on_edit_not_write(tmp_path):
    # Write-only: a typo Edit to an existing hook must NOT dump the new-hook witness
    # checklist. (The vendor-cc-sync rule DOES fire on a tools/cc/ Edit -- that is its
    # job -- so assert the new-hook witness specifically is absent, not that the whole
    # check is empty.)
    out = _fire("Edit", {"file_path": "/r/tools/cc/hooks/write_guard.py",
                         "new_string": "x"}, tmp_path)
    assert "wired-hook script" not in out and "hook HELPER" not in out


def test_165a_silent_on_non_hook_write(tmp_path):
    assert _fire("Write", {"file_path": "/r/espalier/foo.py", "content": "x"}, tmp_path) == ""


# ── 165-B: REINJECT-INTEGRITY-SoT-PARITY ─────────────────────────────────────

def test_165b_fires_on_integrity_sot_edits(tmp_path):
    for path in ("/r/tools/cc/hooks/_integrity.py", "/r/espalier/surface_contract.py"):
        out = _fire("Edit", {"file_path": path, "new_string": "x"}, tmp_path)
        assert "MANIFEST_FILES" in out and "must stay EQUAL" in out


def test_165b_silent_on_unrelated_edit(tmp_path):
    assert _fire("Edit", {"file_path": "/r/espalier/cli.py", "new_string": "x"}, tmp_path) == ""


# ── 165-C: REINJECT-COMMAND-FILE-SYNC ────────────────────────────────────────

def test_165c_fires_on_command_write(tmp_path):
    out = _fire("Write", {"file_path": "/r/.claude/commands/foo.md", "content": "x"}, tmp_path)
    assert "five-surface SoT" in out
    assert "espalier/assets/claude/commands" in out


def test_165c_silent_on_edit_and_non_command(tmp_path):
    """165-C's own narrowness: it fires on a command WRITE and nothing else.

    Asserted against the rule's renderer rather than the whole registry. The
    original form checked that the hook stayed globally silent on these two
    inputs, which stopped being the right question once the claude SoT gained a
    mirror-sync advisory of its own -- both paths are mirrored, and warning on
    them is the point. Keeping the global form would have pinned the ABSENCE of
    that coverage, which is the shape of a test that quietly forbids a fix.
    """
    render = _reinject.COMMAND_SYNC_RULE.render
    assert render("Edit", {"file_path": "/r/.claude/commands/foo.md",
                           "new_string": "x"}, tmp_path) is None
    assert render("Write", {"file_path": "/r/.claude/agents/foo.md",
                            "content": "x"}, tmp_path) is None


def test_claude_sot_edit_now_warns_about_both_mirrors(tmp_path):
    """The coverage 165-C deliberately did not provide: an EDIT to any claude SoT
    file warns, not just a Write, and names both byte-pinned mirrors."""
    out = _fire("Edit", {"file_path": "/r/.claude/agents/foo.md",
                         "new_string": "x"}, tmp_path)
    assert "sync_claude_mirrors.py" in out
    assert "espalier/assets/claude/" in out
    assert "examples/dogfooding/.claude/" in out


# ── 165-D: REINJECT-TEST-LOOSENING (post-state only) ─────────────────────────

def test_165d_fires_on_skip_xfail_and_broad_raises(tmp_path):
    cases = [
        ("Edit", "new_string", "@pytest.mark.skip(reason='x')"),
        ("Edit", "new_string", "@pytest.mark.xfail"),
        ("Write", "content", "with pytest.raises(Exception):"),
    ]
    for tool, key, content in cases:
        out = _fire(tool, {"file_path": "/r/tests/test_x.py", key: content}, tmp_path)
        assert "loosening" in out, (tool, content)


def test_165d_silent_on_narrow_raises_and_non_test(tmp_path):
    # narrow exception type is not a loosening; a skip OUTSIDE tests/ is out of scope.
    assert _fire("Edit", {"file_path": "/r/tests/test_x.py",
                          "new_string": "pytest.raises(ValueError)"}, tmp_path) == ""
    assert _fire("Edit", {"file_path": "/r/espalier/foo.py",
                          "new_string": "@pytest.mark.skip"}, tmp_path) == ""


# ── 165-E: REINJECT-MARKER-SUBSTRING (post-state only) ───────────────────────

def test_165e_fires_on_marker_substring_membership(tmp_path):
    out = _fire("Edit", {"file_path": "/r/espalier/foo.py",
                         "new_string": 'if "MANAGED:" in text:'}, tmp_path)
    assert "has_managed_marker" in out


def test_165e_silent_on_canonical_homes_and_no_pattern(tmp_path):
    # The canonical homes legitimately do marker string ops -> excluded by path.
    assert _fire("Edit", {"file_path": "/r/espalier/managed_markers.py",
                          "new_string": '"MANAGED:" in t'}, tmp_path) == ""
    assert _fire("Edit", {"file_path": "/r/espalier/foo.py",
                          "new_string": "x = 1"}, tmp_path) == ""


# ── REINJECT-ARTIFACT-PROXY-ORACLE (post-state; Bash, not a file edit) ───────

def test_artifact_proxy_fires_on_git_archive(tmp_path):
    out = _fire("Bash", {"command": "git archive HEAD | tar t | grep assets"}, tmp_path)
    assert "index" in out.lower()
    assert "export-ignore" in out

def test_artifact_proxy_fires_after_a_shell_separator(tmp_path):
    # Command position is not only start-of-string: a real invocation can follow
    # a pipe, `&&`, a newline, or a subshell open.
    for cmd in ("cd /r && git archive HEAD | tar t",
                "echo hi; git archive HEAD",
                "M=$(git archive HEAD | wc -c)",
                "set -e\ngit archive HEAD > out.tar"):
        assert _fire("Bash", {"command": cmd}, tmp_path) != "", cmd


def test_artifact_proxy_silent_when_the_phrase_is_only_an_ARGUMENT(tmp_path):
    """The rule's own first live firing was a false positive on this shape.

    A blueprint `record --description "...\\`git archive\\` ..."` merely QUOTED the
    phrase; an unanchored regex fired anyway. A recall rule that cries wolf on prose
    is one that gets tuned out, so command-position anchoring is load-bearing here,
    not cosmetic.
    """
    assert _fire("Bash", {
        "command": 'python3 tools/cc/cognitive_blueprint.py record '
                   '--description "two proxies (git archive + sdist) are both blind"',
    }, tmp_path) == ""
    assert _fire("Bash", {"command": 'grep -rn "git archive" docs/'}, tmp_path) == ""
    assert _fire("Bash", {"command": "echo 'run git archive later'"}, tmp_path) == ""


def test_artifact_proxy_silent_on_unrelated_bash_and_on_edits(tmp_path):
    # The FP shapes: ordinary git usage, an unrelated archive word, and a file edit
    # whose CONTENT merely mentions the phrase (this rule reads the command, not a diff).
    assert _fire("Bash", {"command": "git log --oneline -3"}, tmp_path) == ""
    assert _fire("Bash", {"command": "tar czf out.tgz docs/"}, tmp_path) == ""
    assert _fire("Bash", {"command": "ls docs/archive/"}, tmp_path) == ""
    assert _fire("Edit", {"file_path": "/r/docs/X.md",
                          "new_string": "run `git archive HEAD`"}, tmp_path) == ""


# ── per-turn ceiling holds with the full shipped registry ────────────────────

def test_postttooluse_sync_rules_form_a_distinct_priority_ladder():
    """Distinct, even, descending priorities => a deterministic ceiling drop-order.

    The count lives in the assertion, not in the test NAME. The name used to carry
    it ("...has_twelve...") and nothing checks a name, so it was one more hand-kept
    copy of a number -- stale the first time a row was added.
    """
    sync = [r for r in _reinject.REINJECTS if r.event == "PostToolUse"]
    # cap_exempt is allowed on a PostToolUse row ONLY when its scarcity is the
    # once-per-session flag (the four catalog pointers, 2026-09-06); every
    # other sync row stays inside the session cap.
    assert all(r.face == "sync" and (not r.cap_exempt or r.once_per_session) for r in sync)
    # and the converse: a once row that is NOT cap-exempt could lose to the
    # session cap with its flag intact today, but the rule authors' intent is
    # that the flag IS the scarcity -- keep the two fields paired
    assert all(r.cap_exempt for r in sync if r.once_per_session)
    # a rule id becomes a state-file name (`reinject_once_<id>`): a safe charset,
    # and distinct after case-folding so two ids cannot collide on APFS
    assert all(re.fullmatch(r"[A-Za-z0-9-]+", r.id) for r in _reinject.REINJECTS), [r.id for r in _reinject.REINJECTS]
    assert len({r.id.casefold() for r in _reinject.REINJECTS}) == len(_reinject.REINJECTS)
    prios = [r.priority for r in sync]
    assert len(set(prios)) == len(sync)  # distinct => deterministic drop-order
    assert sorted(prios, reverse=True) == [
        78, 76, 74, 72,   # the once-per-session pointers outrank the sync ladder
        70, 68, 66, 62, 60, 58, 56, 54, 52, 50, 48, 46, 44, 42, 40
    ]


def test_realistic_cofire_d_and_e_within_per_turn_cap(tmp_path):
    # The only realistic co-fire: a tests/** edit whose new content has BOTH a skip
    # marker AND a marker-substring membership check. Both non-exempt; CAP=2 admits
    # exactly both (D=60 > E=58), neither starved.
    content = '@pytest.mark.skip\nif "MANAGED:" in text:'
    out = _reinject.check("PostToolUse", "Edit",
                          {"file_path": "/r/tests/test_x.py", "new_string": content}, tmp_path)
    assert len(out) == 2
    assert any("loosening" in o for o in out)
    assert any("has_managed_marker" in o for o in out)


# Sync scripts deliberately outside the mirror census. Empty today: every
# tracked scripts/sync_*.py backs a declared row. An entry here needs a reason.
_CENSUS_EXCLUDED_SYNC_SCRIPTS: frozenset[str] = frozenset()

# Files that state the mirror-row COUNT in prose, in a form the guard can read.
# Membership is asserted both ways: a listed site whose count is stale reds, AND a
# listed site the pattern cannot see at all reds. The second half matters more than
# it looks -- two entries here originally pinned NOTHING (their counts were bolded
# or absent), so the tuple advertised coverage it did not have, which is worse than
# a shorter list.
#
# Deliberately ABSENT and why:
#   espalier/mirror_registry.py -- it IS the canon; pinning it against itself is
#     circular, and its docstring discusses subsets of the rows ("three rows
#     compare through a normalisation") rather than the total.
#   memory/asset-mirroring.md  -- states rows by NAME, not by count. Guarded by
#     test_asset_mirroring_table_names_every_row instead, which is a stronger check.
#   CHANGELOG.md -- an append-only record. "advisories for the five mirror rows
#     that had none" is permanently correct as history and must never red.
_CENSUS_PROSE_SITES: tuple[str, ...] = (
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "tools/cc/CLAUDE.md",
    "docs/SHARP_EDGES.md",
    "scripts/sync_github_workflow_asset.py",
)


def _census_prose_sites() -> tuple[str, ...]:
    """The prose sites the census-count guard actually reads.

    DERIVED, not hand-kept. A declared site that ``git ls-files`` does not know
    is not a site -- it is a dev-tree artifact, and pinning one is exactly what
    made ``test_prose_never_restates_a_stale_row_count`` red on every fresh
    clone (2026-08-05: the tuple named a gitignored ``task-packs/`` runbook).
    Tracked-ness is the right discriminator because the guard's subject is
    *shipped* prose.

    ``check=True`` is load-bearing, not stylistic. Outside a git work tree
    ``git ls-files`` exits 128 with EMPTY stdout; under ``check=False`` that
    yields an empty population, the caller's loop runs zero times, and its
    ``assert not wrong`` passes having examined nothing -- a gate green because
    it was blind. Raising makes that case a loud ERROR instead. This mirrors
    ``test_every_tracked_sync_script_is_claimed_by_a_row`` above, which already
    uses ``check=True`` for the same call. A ``pytest.skip`` here would be the
    ``docs/FAILURE_MODES.md`` 13.20 shape (a guard that skips when its fixture
    is absent cannot catch the fixture being deleted) and is deliberately NOT
    used.

    ⚠ §C21 (2026-08-14): ``check=True`` covers rc 128 and NOTHING ELSE. git has a
    SECOND way of declining -- inside a gitignored directory of another worktree
    it answers **rc 0 with zero rows**, sailing straight past ``check=True`` into
    exactly the blind-green this paragraph describes. Three sibling paragraphs
    making the same claim were corrected then; this one was in a file the same
    commit edited and was missed, which is its own small lesson about sweeps.
    What covers this site is not the ``check=`` mode: it is the ``full_tree``
    registration of its consumer. Do not copy "use ``check=True`` and you are
    covered" out of here -- route new callers through ``tests/_git_oracle.py``,
    which collapses both cases into one refusal.
    """
    import subprocess  # function-local, matching this module's established idiom

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=REPO,
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout.split()
    )
    return tuple(p for p in _CENSUS_PROSE_SITES if p in tracked)


# ── Fire/silent matrices for the four added mirror rules ─────────────────────

class TestAddedMirrorAdvisories:
    """An advisory that fires on everything is noise, and noise gets tuned out --
    the calibration lesson recorded on _ARTIFACT_PROXY_RE in the hook itself. So
    every rule added here carries at least one negative alongside its positive."""

    def test_claude_mirror_edit_is_told_the_edit_will_be_discarded(self, tmp_path):
        # NOT "run the sync": the generator overwrites the mirror from .claude/,
        # so syncing would destroy the edit and report success.
        out = _fire("Edit", {"file_path": "/r/espalier/assets/claude/agents/foo.md",
                             "new_string": "x"}, tmp_path)
        assert "DISCARDED" in out
        assert "Re-apply" in out

    def test_dogfooding_path_gets_the_mirror_message_not_the_sot_one(self, tmp_path):
        """Order pin. `_CLAUDE_SOT_RE`'s `(^|/)` anchor is satisfied mid-path, so
        BOTH regexes match `examples/dogfooding/.claude/agents/foo.md`. The mirror
        branch is tested first and must stay first -- reversing them would tell the
        author to run a sync that discards the edit."""
        out = _fire(
            "Edit",
            {"file_path": "/r/examples/dogfooding/.claude/agents/foo.md",
             "new_string": "x"},
            tmp_path,
        )
        assert "DISCARDED" in out
        assert "Re-apply" in out

    def test_claude_rule_silent_on_unmirrored_claude_files(self, tmp_path):
        # Only {agents,commands,skills} are mirrored. The folder router and the
        # settings file live in .claude/ and are NOT.
        render = _reinject.CLAUDE_SURFACE_SYNC_RULE.render
        assert render("Edit", {"file_path": "/r/.claude/CLAUDE.md"}, tmp_path) is None
        assert render("Edit", {"file_path": "/r/.claude/settings.json"}, tmp_path) is None

    def test_task_packs_router_rule_silent_on_other_pack_files(self, tmp_path):
        render = _reinject.TASK_PACKS_ROUTER_SYNC_RULE.render
        assert render("Edit", {"file_path": "/r/task-packs/TP-001-a.md"}, tmp_path) is None
        assert render("Edit", {"file_path": "/r/task-packs/FORWARD_LEDGER.md"}, tmp_path) is None

    def test_selfcheck_and_vendor_cc_do_not_answer_for_each_other(self, tmp_path):
        # The mandatory negative pair: two mirror families share the
        # espalier/_vendor/ prefix but have DIFFERENT sync scripts. Naming the
        # wrong one is worse than naming none -- it exits 0 having fixed nothing.
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()

        selfcheck = _fire(
            "Edit", {"file_path": "/r/espalier/_vendor/selfcheck_tests/test_x.py"}, a
        )
        assert "sync_selfcheck_tests.py" in selfcheck
        assert "sync_vendor_cc.py will not fix this" in selfcheck

        # The other direction: the selfcheck rule must not claim a tools/cc path,
        # and the vendor rule must not claim a selfcheck one. Asserted per-rule
        # because the two live under one prefix and a loose pattern on either
        # side reproduces the misdirection this pack removed from
        # surface_impact.classify_surface.
        assert _reinject.SELFCHECK_MIRROR_SYNC_RULE.render(
            "Edit", {"file_path": "/r/espalier/_vendor/cc/hooks/x.py"}, b
        ) is None
        vendor_sot = _fire("Edit", {"file_path": "/r/tools/cc/hooks/x.py"}, b)
        assert "sync_vendor_cc.py" in vendor_sot
        assert "selfcheck" not in vendor_sot

    def test_selfcheck_rule_silent_on_unmirrored_tests(self, tmp_path):
        # Only a curated subset of tests/ is mirrored; the rest must stay silent
        # or the rule fires on hundreds of files.
        render = _reinject.SELFCHECK_MIRROR_SYNC_RULE.render
        assert render(
            "Edit", {"file_path": "/r/tests/test_definitely_not_mirrored.py"}, tmp_path
        ) is None

    def test_harness_guard_names_the_inverted_direction_on_the_root_file(self, tmp_path):
        out = _fire("Edit", {"file_path": "/r/.github/workflows/harness-guard.yml"}, tmp_path)
        assert "INVERTED" in out
        assert "espalier/assets/github/workflows/harness-guard.yml is the source" in out
        # Direction before remedy: running the sync at this moment would discard
        # the edit that just landed, so the message has to say so.
        assert "Re-apply this edit to the ASSET" in out
        assert "overwrite what you just wrote" in out

    def test_harness_guard_asset_edit_points_at_the_root_copy(self, tmp_path):
        out = _fire(
            "Edit",
            {"file_path": "/r/espalier/assets/github/workflows/harness-guard.yml"},
            tmp_path,
        )
        assert "source of truth" in out
        assert "sync_github_workflow_asset.py" in out

    def test_harness_guard_rule_silent_on_sibling_workflows(self, tmp_path):
        # Only harness-guard.yml is generated. Every other workflow in the same
        # directory is edited in place -- this is the whole reason the row bites.
        render = _reinject.HARNESS_GUARD_SYNC_RULE.render
        assert render("Edit", {"file_path": "/r/.github/workflows/ci.yml"}, tmp_path) is None
        assert render(
            "Edit", {"file_path": "/r/.github/workflows/release.yml"}, tmp_path
        ) is None


# ── TestMirrorCensusCoverage: the census is derived, and every row is advised ─

class TestMirrorCensusCoverage:
    """Every declared mirror row must warn at EDIT time, on both advisory surfaces.

    This is the enumeration guard. It exists because the mirror census was kept by
    hand in four independent places that said three, four, two and four when the
    answer was seven rows -- and because the two advisory surfaces between them
    covered two of those seven. A longer hand-list would rot the same way the next
    time a family is added, so the contract is inverted: a row may not exist
    without an advisory, and the only place a row may be declared is the registry.

    The probe path per row is DERIVED from the registry, never listed here. A
    hand-list of probe paths would be the same defect one level up -- a new row
    would be silently untested rather than silently unadvised.
    """

    @staticmethod
    def _probe(r) -> str:
        """A real source-side file this row mirrors, resolved from the tree."""
        glob = mirror_registry.glob_row_parts(r.sot)
        if glob is not None:
            base_rel, suffixes = glob
            base = REPO / base_rel
            hits = sorted(
                p for p in base.rglob("*")
                if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts
            )
        elif r.sot.endswith("/"):
            base = REPO / r.sot
            hits = sorted(
                p for p in base.rglob("*")
                if p.is_file()
                and "__pycache__" not in p.parts
                and mirror_registry.covers(
                    r, str(p.relative_to(REPO)).replace("\\", "/"), REPO
                )
            )
        else:
            return r.sot
        assert hits, f"row {r.name!r} matched no real file under {r.sot!r}"
        return str(hits[0].relative_to(REPO)).replace("\\", "/")

    def test_every_row_declares_paths_that_exist(self):
        missing = []
        for r in mirror_registry.MIRROR_ROWS:
            for side in (self._probe(r), *r.mirrors):
                if not (REPO / side).exists():
                    missing.append(f"{r.name}: {side}")
        assert not missing, (
            "mirror registry rows name paths that are not on disk: " + str(missing)
        )

    def test_every_tracked_sync_script_is_claimed_by_a_row(self):
        """The completeness oracle -- without it the registry only documents.

        Every other test here iterates MIRROR_ROWS, so all of them are structurally
        incapable of noticing a mirror family that was never declared: add the sync
        script, the mirror tree and the parity test, skip the registry row, and the
        suite stays green. That is the failure this whole change exists to remove,
        so it cannot be left resting on a convention.

        `git ls-files` is the reference set, matching the shape
        tests/test_doc_test_citations.py::TestSweepCompleteness already uses. It is
        a proxy -- a family could in principle arrive without a sync script -- but
        it is a DERIVED one, and it converts the most common way a family actually
        lands into a red.

        TWO blind spots, both real, both recorded in the ledger rather than left
        implicit:
          * an UNTRACKED script is invisible -- this resolves against `git
            ls-files`, so `git add` before trusting a green run. That is the same
            rule tests/CLAUDE.md already states for new test files.
          * a family arriving with NO sync script (a hand-copied pair) is not seen
            at all; `harness-guard` was exactly that for months.
        """
        import subprocess

        tracked = {
            line for line in subprocess.run(
                ["git", "ls-files", "scripts/sync_*.py"],
                capture_output=True, text=True, cwd=REPO, check=True, encoding="utf-8",
            ).stdout.split()
        }
        # The oracle is a SET DIFFERENCE, so an empty reference set makes it
        # unconditionally green: `unclaimed` would be empty because `tracked` was,
        # not because every family is claimed. Rename the scripts or move them to
        # scripts/sync/ and this completeness check goes permanently blind to the
        # exact failure it exists to catch. `check=True` above covers "git broke";
        # this covers "git worked and the glob matched nothing".
        assert tracked, (
            "git ls-files 'scripts/sync_*.py' matched NOTHING -- the completeness "
            "oracle would pass having read nothing. The sync scripts moved or were "
            "renamed; update the glob."
        )
        claimed = {r.sync.split()[-1] for r in mirror_registry.MIRROR_ROWS if r.sync}
        unclaimed = sorted(tracked - claimed - _CENSUS_EXCLUDED_SYNC_SCRIPTS)
        assert not unclaimed, (
            "sync scripts no mirror row claims -- a mirror family was added without "
            "a row in espalier/mirror_registry.py, so every census guard is blind to "
            f"it: {unclaimed}. Add the row, or add the script to "
            "_CENSUS_EXCLUDED_SYNC_SCRIPTS with a reason."
        )

    def test_prose_never_restates_a_stale_row_count(self):
        """The recursion guard.

        Replacing "the census in prose" with "a pointer to the census, plus the
        count restated in prose in eight places" is a smaller version of the
        defect, not its removal -- and the ladder rule this repo already holds
        says never restate another SoT. Any number-word next to "rows" in these
        files must equal the real count, so an eighth row reds instead of
        quietly leaving eight sites wrong.
        """
        words = {
            "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        # Deliberately TIGHT: only a number-word that directly quantifies "rows"
        # counts as a total claim. Prose like "six of this repo's seven mirror
        # rows" is correct and must not red -- a guard that cries wolf on accurate
        # sentences is one that gets suppressed, which costs more than it saves.
        # At most two adjective words may sit between, and none may contain
        # punctuation (so "six families / seven rows" reads only the "seven").
        # `\*{0,2}` after the captured word is load-bearing, not decoration.
        # Without it a markdown-bolded count -- `**seven** byte-pinned mirror
        # rows`, which is exactly how the root CLAUDE.md states it -- has no
        # whitespace directly after the word, so the guard silently skipped the
        # one site read every session. A stale-count guard blind to the most
        # prominent statement of the count is the bug it was written to prevent.
        pattern = re.compile(
            r"\b(" + "|".join(words) + r")\*{0,2}\s+(?:[\w'-]+\s+){0,2}rows?\b",
            re.IGNORECASE,
        )
        n = len(mirror_registry.MIRROR_ROWS)
        wrong = []
        sites = _census_prose_sites()
        # Not vacuous: a derivation that filtered everything out would pass by
        # checking nothing, which is the failure this whole guard exists to catch.
        assert sites, (
            "_census_prose_sites() derived an EMPTY population -- every declared "
            "site is untracked. The guard would pass having read nothing; fix the "
            "declaration rather than accepting a green."
        )
        # ...and no site leaves the population SILENTLY. Filtering by tracked-ness
        # is what keeps a gitignored path from reddening every clone, but a silent
        # filter conflates the two absences that must stay distinct: "deliberately
        # gitignored" and "you forgot to `git add` it" (tests/CLAUDE.md names the
        # second as this repo's live footgun). Without this, adding a new prose
        # site and forgetting to stage it reads as full coverage. Declare it or
        # drop it -- do not let it vanish.
        dropped = sorted(set(_CENSUS_PROSE_SITES) - set(sites))
        assert not dropped, (
            f"declared census prose site(s) are UNTRACKED: {dropped} -- git does "
            "not know them, so the guard would silently skip them while the tuple "
            "advertises coverage. `git add` them, or remove them from "
            "_CENSUS_PROSE_SITES."
        )
        for rel in sites:
            path = REPO / rel
            if not path.is_file():
                # Reached only for a TRACKED site that vanished from the working
                # tree -- the case this branch was written for. A gitignored site
                # never gets here; it left the population above.
                wrong.append(f"{rel}: MISSING (census prose site moved or renamed)")
                continue
            seen = 0
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "mirror" not in line.lower():
                    continue
                for m in pattern.finditer(line):
                    seen += 1
                    said = words[m.group(1).lower()]
                    if said != n:
                        wrong.append(f"{rel}:{lineno} says {m.group(1)!r}, rows={n}")
            # A listed site the pattern cannot read is NOT covered, and silently
            # reading as covered is how a stale-count guard goes green while the
            # count it guards drifts. Either the site states the count in a form
            # this pattern sees, or it does not belong in the tuple.
            if seen == 0:
                wrong.append(
                    f"{rel}: declared a census prose site but states no readable "
                    "row count -- fix the wording or drop it from _CENSUS_PROSE_SITES"
                )
        assert not wrong, (
            "prose restates a row count that no longer matches the registry: "
            + "; ".join(wrong)
        )

    def test_asset_mirroring_table_names_every_row(self):
        """The count's stronger sibling: names, not numbers.

        `memory/asset-mirroring.md` carries a per-row table added alongside the
        registry -- a fresh hand-maintained enumeration in the very change that
        removed one, which is the recursion worth guarding. Names have none of the
        ambiguity a bare number does ("two of seven rows" defeats a count regex),
        so this is derived straight from canon with no false-positive surface.
        """
        text = (REPO / "memory" / "asset-mirroring.md").read_text(encoding="utf-8")
        named = set(re.findall(r"`([a-z][a-z-]+)`", text))
        missing = sorted(mirror_registry.ROW_NAMES - named)
        assert not missing, (
            "memory/asset-mirroring.md's row table omits declared mirror rows: "
            f"{missing}. Add them, or the table quietly under-enumerates the census "
            "it sits beside."
        )

    def test_single_mirror_assumption_is_pinned(self):
        """`counterpart()` and `remedy()` both read `mirrors[0]` and ignore the rest.

        Harmless today because every row has exactly one mirror -- the two legs of
        the claude mirror are modelled as two rows, not one row with a 2-tuple. But
        the field is typed `tuple[str, ...]` and documented as "one or more", which
        invites a future author to add a genuine two-mirror row and trust helpers
        that would silently drop the second. Fail here, loudly, instead of there,
        quietly.
        """
        multi = [r.name for r in mirror_registry.MIRROR_ROWS if len(r.mirrors) != 1]
        assert not multi, (
            f"rows with != 1 mirror: {multi}. counterpart()/remedy() read mirrors[0] "
            "only -- teach them to handle the rest before adding such a row."
        )

    def test_mirror_advisories_rank_below_correctness_nudges(self, tmp_path):
        """Documents a real starvation case, and pins the ordering that causes it.

        The per-turn ceiling admits 2 payloads. An edit to a MIRRORED test file
        that also loosens a test trips three rules, and the mirror-sync advisory
        is the one dropped. That is the pre-existing convention -- the vendor and
        docs-asset rules already sat below test-loosening and marker-substring
        before this change, and the rules added here inherit the same band rather
        than jumping the queue. Pinned so a future priority edit has to face the
        trade-off deliberately instead of discovering it in the field.
        """
        sync = sorted(
            (r for r in _reinject.REINJECTS if r.event == "PostToolUse"),
            key=lambda r: -r.priority,
        )
        by_id = {r.id: r.priority for r in sync}
        correctness = max(by_id["REINJECT-TEST-LOOSENING"], by_id["REINJECT-MARKER-SUBSTRING"])
        # Named explicitly rather than substring-matched on "SYNC": the command
        # rule is REINJECT-COMMAND-FILE-SYNC and a substring filter silently swept
        # it in, failing this test on a rule it was never about.
        mirror_rule_ids = frozenset({
            "REINJECT-VENDOR-CC-SYNC",
            "REINJECT-DOCS-ASSET-SYNC",
            "REINJECT-CLAUDE-SURFACE-SYNC",
            "REINJECT-TASK-PACKS-ROUTER-SYNC",
            "REINJECT-SELFCHECK-MIRROR-SYNC",
            "REINJECT-HARNESS-GUARD-SYNC",
            "REINJECT-PACK-CHECKLIST-SYNC",
            "REINJECT-PACK-CHECKLIST-REGION",
            # The generated-doc-region family. It carries no MIRROR_ROWS row by
            # design (a render-from-Python is not a byte-mirror), which is
            # exactly why it arrived advisory-less: the coverage requirement
            # above iterates MIRROR_ROWS and could not see it. Listed here so
            # the drop-order contract holds it anyway.
            "REINJECT-GENERATED-DOC-REGION",
        })
        missing = mirror_rule_ids - set(by_id)
        assert not missing, f"mirror rule renamed or removed: {sorted(missing)}"
        # ...and the other direction. `missing` alone is one-directional: it
        # catches a rule renamed AWAY from this set, never a rule ADDED outside
        # it -- so a new mirror advisory escapes the drop-order contract entirely
        # and nobody finds out. Measured: that is exactly what happened when the
        # pack-checklist row landed.
        unlisted = {
            i for i, _ in by_id.items()
            if i.endswith(("-SYNC", "-REGION")) and i not in mirror_rule_ids
            and i != "REINJECT-COMMAND-FILE-SYNC"
        }
        assert not unlisted, (
            f"mirror-ish advisory rule(s) not held to the drop-order contract: "
            f"{sorted(unlisted)} -- add them to mirror_rule_ids (or exclude with a "
            "reason, as REINJECT-COMMAND-FILE-SYNC is)."
        )
        mirrors = [by_id[i] for i in mirror_rule_ids]
        assert all(p < correctness for p in mirrors), (
            "a mirror-sync advisory now outranks the correctness nudges; that is a "
            "deliberate change to drop-order under the per-turn cap -- update this test "
            "with the reasoning rather than deleting it."
        )
        assert _reinject.REINJECT_PER_TURN_CAP == 2

    def test_every_row_pinning_test_resolves(self):
        """A row citing a dead test is a row with no guard behind it."""
        unresolved = []
        for r in mirror_registry.MIRROR_ROWS:
            mod, _, node = r.pinning_test.partition("::")
            path = REPO / mod
            if not path.exists():
                unresolved.append(f"{r.name}: no module {mod}")
                continue
            text = path.read_text(encoding="utf-8")
            for part in node.split("::"):
                token = f"class {part}:" if part[:1].isupper() else f"def {part}("
                if token not in text:
                    unresolved.append(f"{r.name}: {mod} has no {part}")
        assert not unresolved, (
            "mirror registry rows cite tests that do not exist: " + str(unresolved)
        )

    def test_every_row_has_an_edit_time_advisory(self, tmp_path):
        """The spine. A row with no advisory is a drift you learn about from a
        full-suite red six minutes later -- if a full suite is run at all."""
        unadvised = []
        for i, r in enumerate(mirror_registry.MIRROR_ROWS):
            # A FRESH counter dir per row. The per-turn ceiling is a real product
            # behaviour, and a single shared dir would exhaust it partway down the
            # list -- reporting the tail rows as unadvised when they are merely
            # capped. That reads as a coverage gap and is not one.
            session = tmp_path / f"row{i}"
            session.mkdir()
            probe = self._probe(r)
            # `root` reaches renderers as the project root in production
            # (post_write_check passes _resolve_project_root()), so a rule may
            # decide curated-subset membership by statting the mirror tree. Give
            # it a root where this row's counterpart exists, or such a rule can
            # never fire under test and would look like a coverage gap.
            twin = mirror_registry.counterpart(r, probe)
            if twin:
                dest = session / twin
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.touch()
            # ALL payloads, not _fire's first one. The row's own advisory may not
            # be the top-priority match for a path that trips several rules.
            out = _reinject.check(
                "PostToolUse", "Edit", {"file_path": f"/r/{probe}"}, session
            )
            if not out:
                unadvised.append(f"{r.name} (probe: {probe}) -- SILENT")
                continue
            # "Something fired" is not coverage, and neither is "the right SCRIPT
            # was named": two scripts cover four rows (sync_claude_mirrors serves
            # both claude rows, sync_asset_docs serves asset-docs AND
            # task-packs-router), so a neighbouring rule naming the shared script
            # satisfies a script-keyed assertion while the row has no advisory of
            # its own -- and sends the reader to a parity test that cannot fail for
            # their file. The MIRROR PATH is row-unique by construction; key on it.
            joined = "\n".join(out)
            if r.mirrors[0].rstrip("/") not in joined:
                unadvised.append(
                    f"{r.name} (probe: {probe}) -- advised by another rule; "
                    f"no payload names {r.mirrors[0]}"
                )
        assert not unadvised, (
            "mirror rows with no advisory of their OWN: " + "; ".join(unadvised)
        )

    def test_no_generated_side_advisory_prescribes_its_own_destruction(self):
        """An advisory on the GENERATED side may name its sync only after the discard.

        The gap this closes is in the guard above, not in the hook: ``_probe``
        returns "a real SOURCE-side file this row mirrors", so every assertion in
        this class drove one side of every row and the other side was untested by
        construction. Four rules answered "run the sync" on a path that sync
        OVERWRITES -- ``endswith(tail)`` cannot separate the sides, because every
        mirror path ends with its own source path -- and following any of them
        deletes the edit and exits 0. The census guard whose whole job is "no row
        without an advisory" could not see it.

        The property is one-directional on purpose. Silence on the mirror side is
        NOT a failure here (vendor-cc is deliberately silent, and whether that is
        a gap is a separate question); what is forbidden is naming the destroying
        command without saying the edit is already lost.

        Keyed on the script BASENAME -- the same
        ``r.sync.split()[-1].rsplit("/", 1)[-1]`` its sibling
        ``test_every_row_has_a_surface_impact_obligation`` already uses ten lines
        below. Keying on the PATH (``scripts/sync_asset_docs.py``) was measured to
        miss the defect outright: re-introduce the bug with the payload spelling
        the command as a bare ``sync_asset_docs.py`` and this test goes GREEN.
        That spelling is not hypothetical -- ``_reinject.py`` already writes
        "sync_vendor_cc.py will not fix this" in a live payload.

        Renderers are called DIRECTLY rather than through ``check()``: the
        per-turn ceiling would clip payloads, and a clipped bad payload is
        indistinguishable from an absent one -- a cap that can hide the defect
        makes the test report health it did not establish.
        """
        # "discard" / "overwrit*" are the two concepts a correct generated-side
        # message uses. Substring, case-folded: tolerant of rewording, intolerant
        # of the warning going missing.
        warned = ("discard", "overwrit")
        # Rows whose generated side is deliberately SILENT, with the reason. An
        # exemption must be argued here, not inferred from a global count.
        silent_by_design = {
            "vendor-cc": "no mirror-side advisory at all (a known, separate gap)",
        }
        # Several generated-side rules are content-gated so an ordinary edit to a
        # large file stays quiet. A blob of "x" therefore never reaches the most
        # REACHABLE generated-side advisory in the module (the checklist regions,
        # under unprotected .claude/), and 3 of 9 rows contributed nothing at all
        # -- the guard was blind to them while reporting healthy. Seed every gate
        # token so each row is actually exercised.
        blob = ("x deploy-inventory: required-gitignore: pack-artifact-checklist: "
                "reasoning-review-checklist: Line-number accuracy")
        offenders, examined, mis_sided, unnamed = [], 0, [], []
        for r in mirror_registry.MIRROR_ROWS:
            if not r.has_sync:
                continue
            examined += 1
            probe = self._probe(r)
            twin = mirror_registry.counterpart(r, probe)
            # If `counterpart` ever stops resolving, `twin` goes None/equal and
            # every row below would be driven on its SOURCE side -- the exact
            # blindness this test exists to end, silently reintroduced inside the
            # test written to close it.
            if not twin or twin == probe:
                mis_sided.append(f"{r.name}: counterpart({probe!r}) -> {twin!r}")
                continue
            script = r.sync.split()[-1].rsplit("/", 1)[-1]
            named_here = 0
            for rule in _reinject.REINJECTS:
                for tool in ("Edit", "Write"):
                    payload = rule.render(
                        tool,
                        {"file_path": twin, "new_string": blob, "content": blob},
                        REPO,
                    )
                    if not payload or script not in payload:
                        continue
                    named_here += 1
                    if not any(w in payload.casefold() for w in warned):
                        offenders.append(
                            f"{r.name} [{rule.id}] on {twin}: names {script} with no "
                            f"discard warning -- running it overwrites this file"
                        )
            if not named_here and r.name not in silent_by_design:
                unnamed.append(f"{r.name} (probe: {twin}, key: {script})")
        assert not mis_sided, (
            "the generated-side probe did not resolve, so the rows below were "
            f"never driven on their mirror side: {mis_sided}. Fix the probe; do "
            "not relax the assertion -- an unresolved side is untested, not clean."
        )
        assert examined >= 8, (
            f"only {examined} rows with a sync script were examined; the registry "
            "carries more. The row filter has broken and this test is passing "
            "vacuously."
        )
        # The KEYING floor, per row. A global count is a POPULATION floor wearing
        # this docstring: losing one row's keying costs a couple of hits out of a
        # dozen and a global threshold stays satisfied, so the defect returns
        # green on that row. Measured -- with a path-shaped key and the bug
        # reintroduced under a basename spelling, the global form passed. Every
        # row must name its own script, or be exempt above with a reason.
        assert not unnamed, (
            "no generated-side payload named these rows' own sync script: "
            f"{unnamed}. Either the payload wording no longer contains the script "
            "basename -- in which case this test checks NOTHING for that row and "
            "the key must be re-pointed -- or that row's advisory went silent. Add "
            "it to `silent_by_design` only with a stated reason."
        )
        assert not offenders, (
            "generated-side advisories that prescribe the command that destroys "
            "the edit:\n  " + "\n  ".join(offenders)
        )

    def test_surface_impact_generated_side_also_never_prescribes_its_own_destruction(self):
        """The SAME property, on the second advisory surface.

        The sibling below already calls ``surface_impact`` "the second advisory
        surface" and already requires the mirror-side obligation to NAME the row's
        sync -- while never requiring it to say the edit is lost first. So the
        exact defect fixed in the PostToolUse hook survived here on the same two
        rows, and ``asset-docs`` was the worse of the pair: it listed affirmative
        work to do (``_SEED_DOC_REL_PATHS``, ``_ALLOWED_UNDEPLOYED_DOC_REFS``,
        ``_reinject._DOCS_ASSET_TAILS``, the onboarding-honesty list) on a file
        ``sync_asset_docs.py`` overwrites.

        Fixing one producer and not the other is how a class comes back. Both
        surfaces now answer to one property.

        ⚠ The token tuple is the SAME as its sibling's, deliberately, and getting
        there took a correction worth recording. The first cut of this test used a
        WIDENED tuple -- ``("discard", "overwrit", "hand-edit")`` -- and passed.
        Measured afterwards: two rows (``vendor-cc``, ``selfcheck-tests``) passed
        ONLY via that third token; their obligations said "do NOT hand-edit" and
        stopped, giving neither the WHY (it gets overwritten) nor the remedy
        (re-apply to the source, then sync). So the tuple had been widened to
        accommodate the weakest pre-existing prose rather than the prose raised to
        the standard the rest of this session established -- which is exactly the
        "a guard whose red is inconvenient gets widened until it covers nothing"
        failure this repo has already recorded once. Both messages were rewritten;
        the tuple is back to strict. If a future row reds here, raise its prose --
        do not re-add a token.
        """
        warned = ("discard", "overwrit")
        offenders, checked = [], 0
        for r in mirror_registry.MIRROR_ROWS:
            if not r.has_sync:
                continue
            probe = self._probe(r)
            twin = mirror_registry.counterpart(r, probe)
            if not twin or twin == probe:
                continue
            answer = surface_impact.classify_surface(twin)
            if answer is None:
                continue
            text = str(answer)
            script = r.sync.split()[-1].rsplit("/", 1)[-1]
            if script not in text:
                continue
            checked += 1
            if not any(w in text.casefold() for w in warned):
                offenders.append(f"{r.name} on {twin} (kind={answer[0]!r})")
        assert checked >= 4, (
            f"only {checked} generated-side obligations named their row's sync "
            "script; the key or the obligation wording has moved and this check is "
            "vacuous. Re-point it rather than lowering the floor."
        )
        assert not offenders, (
            "surface-impact obligations that name the destroying sync on the "
            "GENERATED side with no 'do NOT hand-edit' / discard warning:\n  "
            + "\n  ".join(offenders)
        )

    def test_generated_doc_region_advisory_is_anchored_to_the_exact_file(self):
        """The one renderer in this module with no behavioural test of its own.

        ``_render_generated_doc_region_edit`` matches ``README.md`` -- a BARE
        BASENAME -- so the pre-fix ``fp.endswith(r[0])`` fired on every README in
        the tree; only the content gate kept the blast radius down, and a content
        gate is not a path identity. Nothing anywhere in ``tests/`` drove this
        renderer: ``TestTheEditTimeAdvisoryCoversEveryRegion`` checks the
        ``_GENERATED_DOC_REGIONS`` tuple's DATA against the generator's own
        ``REGIONS``, and never calls the function; the row-driven guards here
        iterate ``MIRROR_ROWS``, which this family deliberately does not join. So
        the firing predicate could be changed in either direction, silently.

        The negative cases are what make the positives mean anything -- and the
        path FORMS are the point. A hand-rolled root-strip passes the canonical
        absolute path and silently retires the rule on the rest.
        """
        blob = "deploy-inventory: some hand-typed text"
        fires = [
            REPO / "README.md",                    # canonical absolute
            "./README.md",                         # cwd-relative
            "$CLAUDE_PROJECT_DIR/README.md",       # Write tool_input carries this verbatim
            "${CLAUDE_PROJECT_DIR}/README.md",     # brace form
            REPO / "docs" / ".." / "README.md",    # traversal
            "README.md",                           # bare relative
        ]
        silent = [
            REPO / "docs" / "sharp-edges" / "README.md",
            REPO / "task-packs" / "README.md",
            REPO / "examples" / "dogfooding" / "README.md",
            REPO / "espalier" / "assets" / "docs" / "sharp-edges" / "README.md",
        ]
        missed = [
            str(p) for p in fires
            if _reinject._render_generated_doc_region_edit(
                "Edit", {"file_path": str(p), "new_string": blob}, REPO) is None
        ]
        assert not missed, (
            f"the generated-region advisory went SILENT on {missed}. Silence is the "
            "wrong failure direction for an advisory -- the author keeps the edit "
            "and the next regenerate discards it. Use _hook_utils.normalize_path "
            "(the declared single owner) rather than a local root-strip."
        )
        false_fires = [
            str(p) for p in silent
            if _reinject._render_generated_doc_region_edit(
                "Edit", {"file_path": str(p), "new_string": blob}, REPO) is not None
        ]
        assert not false_fires, (
            f"the advisory fired on a README that carries no generated region: "
            f"{false_fires}. `README.md` is a bare basename; match the ROOT-RELATIVE "
            "path, never a suffix."
        )

    def test_every_row_has_a_surface_impact_obligation(self):
        """The second advisory surface -- the shipped, adopter-facing one.

        Both sides of every row, and the obligation must name the row's own sync.
        An earlier form skipped any mirror side that was a directory, which was 5
        of the 7 rows -- including the one whose wrong-family answer this change
        exists to fix. It passed while the defect was live: a skip-on-shape guard
        cannot catch what it declines to look at.
        """
        bad = []
        for r in mirror_registry.MIRROR_ROWS:
            probe = self._probe(r)
            # Resolve a directory mirror to a real file rather than skipping it.
            mirror_side = mirror_registry.counterpart(r, probe) or r.mirrors[0]
            script = r.sync.split()[-1].rsplit("/", 1)[-1]

            for side in (probe, mirror_side):
                if side.endswith("/"):
                    bad.append(f"{r.name}: {side} did not resolve to a file")
                    continue
                if surface_impact.classify_surface(side) is None:
                    bad.append(f"{r.name}: {side} -> None")

            # The MIRROR side must name the row's own sync. A mirror path belongs
            # to exactly one row by construction, so there is no ambiguity to
            # excuse a generic answer -- and a generic answer on a mirror path is
            # how the selfcheck family came to be told to run the wrong script.
            #
            # The SOURCE side is held to non-None only, and that is a DEFERRAL,
            # not a principle. An earlier version of this comment justified it as
            # "classify_surface is a pure path function that cannot know
            # curated-subset membership" -- which is false: build_report already
            # holds repo_root and calls _scan_existing(repo_root, ...) two lines
            # below the classify_surface call, so the filesystem is a parameter
            # away. The real reason is scope. Tracked as DEF-419d; until it lands,
            # the edit-time advisory is the only net on a mirrored docs/ or tests/
            # file, and it does not fire during pack authoring.
            got = surface_impact.classify_surface(mirror_side)
            if got is not None and script not in " ".join(got[1]):
                bad.append(
                    f"{r.name}: mirror {mirror_side} -> {got[0]!r} does not name {script}"
                )
        assert not bad, "surface_impact gaps on declared mirror paths: " + "; ".join(bad)

    def test_every_row_remedy_names_its_real_sync(self):
        for r in mirror_registry.MIRROR_ROWS:
            text = mirror_registry.remedy(r.name)
            assert r.has_sync, f"row {r.name!r} lost its sync script"
            assert r.sync in text and "by hand" not in text, r.name

    def test_an_unscripted_row_is_told_to_copy_not_to_run(self):
        """The branch every row currently escapes.

        Every row ships a sync script today, so the guard above can no longer
        exercise the unscripted case -- and a branch with no population is one
        that rots unnoticed. Drive it directly with a synthetic row instead of
        trusting that it still behaves.
        """
        synthetic = mirror_registry.MirrorRow(
            name="synthetic", sot="a/b.yml", mirrors=("c/b.yml",), sync=None,
            pinning_test="tests/test_x.py::TestX", comparator=mirror_registry.BYTES,
            kind=mirror_registry.BYTE, direction=mirror_registry.SOT_IS_PACKAGED,
        )
        text = mirror_registry.remedy(synthetic)
        assert "run `" not in text
        assert "by hand" in text and "a/b.yml" in text and "c/b.yml" in text

    def test_unknown_row_name_raises(self):
        """A typo must fail loudly rather than silently disable a guard."""
        with pytest.raises(KeyError):
            mirror_registry.row("no-such-row")


# ── TestWitnessSetParity: the witness DATA is contract-bound, not hope-bound ──

class TestWitnessSetParity:
    """Bind the witness DATA to the live surfaces so it cannot silently rot. The
    witness set is itself a multi-surface SoT (sister to the thing it guards); these
    assertions convert the docs/SHARP_EDGES prose wish into a mechanical guard."""

    def test_canonical_script_names_match_surface_contract(self):
        # Auto-reddens the moment a 13th hook is wired: the embedded anchor MUST equal
        # the curated SoT, not drift behind it.
        assert set(_reinject._CANONICAL_HOOK_SCRIPT_NAMES) == set(
            surface_contract.get_canonical_hook_scripts()
        )

    def test_witness_paths_resolve_on_disk(self):
        # Every concrete file path named in any witness set must exist (catches a
        # renamed/removed surface). Entries with a <name> placeholder are skipped
        # whole (their parent dirs are pinned in test_command_surface_dirs_resolve).
        tok = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|json|md|txt)")
        entries = (*_reinject._HOOK_COUNT_WITNESSES,
                   *_reinject._HELPER_COUNT_WITNESSES,
                   *_reinject._COMMAND_SURFACE_WITNESSES)
        missing = []
        for entry in entries:
            if re.search(r"<[a-z]", entry):
                continue  # real <name> placeholder; a `->` arrow must NOT skip the entry
                          # (else its named path goes existence-unchecked -- TP-168 168-F)
            for path in tok.findall(entry):
                if (REPO / path).exists():
                    continue
                # A gitignored, never-committed surface (e.g. .claude/settings.json)
                # is legitimately absent on a fresh clone / CI. Only a git-TRACKED
                # path that no longer resolves signals a renamed/removed surface.
                # (TP-177 W0-1)
                #
                # §C21/`DEF-574`: this used to swallow every git failure into
                # `ignored = False`, which reads as fail-closed and is -- for the
                # rc-128 case. It is NOT for the other one: with REPO inside
                # another worktree's gitignored directory, `check-ignore` returns
                # rc 0 for EVERY path, so every absent witness was waved through
                # and `missing` stayed empty. Unlike the two sibling sites with
                # this shape (`test_doc_source_citations.py::
                # test_record_surfaces_are_excluded`, `test_record_axis_
                # reconciliation.py::test_every_member_is_a_name_git_knows_about`)
                # this test has no
                # upstream `if not tracked: skip`, so nothing else was covering
                # it. The oracle refuses instead of answering about a foreign tree.
                ignored = require_is_gitignored(REPO, path)
                if not ignored:
                    missing.append(path)
        assert not missing, f"witness names a surface that no longer resolves: {missing}"

    def test_command_surface_dirs_resolve(self):
        for d in (".claude/commands", "espalier/assets/claude/commands",
                  "examples/dogfooding/.claude/commands"):
            assert (REPO / d).is_dir(), f"command surface dir missing: {d}"
        assert (REPO / "cc" / "COMMANDS.md").exists()

    def test_witness_counts_pinned(self):
        # A silent shortening of any witness list fails here (the list IS the value).
        assert len(_reinject._HOOK_COUNT_WITNESSES) == 11
        assert len(_reinject._HELPER_COUNT_WITNESSES) == 7
        assert len(_reinject._COMMAND_SURFACE_WITNESSES) == 5
        assert len(_reinject._CANONICAL_HOOK_SCRIPT_NAMES) == 12

    def test_docs_asset_tails_match_deployed_set(self):
        # _DOCS_ASSET_TAILS is a multi-surface SoT: bind it to the LIVE deployed-doc
        # set so it reds the moment a doc is added to / removed from
        # espalier/assets/docs/ without updating the rule. Mirrors the absent-dir
        # guard in test_deploy_doc_parity::TestSourceAssetDocByteParity.
        asset_docs = REPO / "espalier" / "assets" / "docs"
        if not asset_docs.is_dir():
            return  # nothing deployed (stripped tree); the rule is legitimately inert
        deployed = {f"docs/{p.relative_to(asset_docs).as_posix()}"
                    for p in asset_docs.rglob("*.md")}
        assert deployed == set(_reinject._DOCS_ASSET_TAILS), (
            "_DOCS_ASSET_TAILS drifted from espalier/assets/docs/ -- "
            f"deployed={deployed}, rule={set(_reinject._DOCS_ASSET_TAILS)}"
        )


# ── TP-238: vendor-cc + docs-asset mirror-sync fire/silent matrices ───────────

def test_vendor_sync_fires_on_non_hook_tools_cc_python(tmp_path):
    out = _fire("Edit", {"file_path": "/r/tools/cc/session_summary.py",
                         "new_string": "x"}, tmp_path)
    assert "sync_vendor_cc.py" in out
    assert "byte-for-byte mirror" in out


def test_vendor_sync_fires_on_hook_edit(tmp_path):
    # An Edit (not Write) of an existing hook: the new-hook rule is Write-only and
    # stays silent, so the vendor-cc-sync nudge is the one that fires.
    out = _fire("Edit", {"file_path": "/r/tools/cc/hooks/session_start.py",
                         "new_string": "x"}, tmp_path)
    assert "sync_vendor_cc.py" in out


def test_vendor_sync_silent_on_vendor_mirror(tmp_path):
    # Editing the mirror itself must NOT nudge (no `tools/cc/` segment in the path).
    out = _fire("Edit", {"file_path": "/r/espalier/_vendor/cc/hooks/x.py",
                         "new_string": "x"}, tmp_path)
    assert "sync_vendor_cc.py" not in out


def test_vendor_sync_silent_on_non_python(tmp_path):
    out = _fire("Edit", {"file_path": "/r/tools/cc/x.md", "new_string": "x"}, tmp_path)
    assert "sync_vendor_cc.py" not in out


def test_vendor_sync_fires_on_the_windows_shim(tmp_path):
    # DEF-729: the .cmd statusline shim is a deploy source the same mirror
    # carries; an edit to it needs the same sync.
    out = _fire("Edit", {"file_path": "/r/tools/cc/statusline.cmd", "new_string": "x"}, tmp_path)
    assert "sync_vendor_cc.py" in out


def test_docs_asset_sync_fires_on_each_deployed_doc(tmp_path):
    # Fresh session dir per tail: REINJECT_SESSION_CAP (5) would otherwise silence
    # fires past the 5th now that the deployed-doc set is larger than the cap.
    for i, tail in enumerate(_reinject._DOCS_ASSET_TAILS):
        session = tmp_path / str(i)
        session.mkdir()
        out = _fire("Edit", {"file_path": f"/r/{tail}", "new_string": "x"}, session)
        assert "assets/docs/" in out, f"docs-asset rule silent on deployed {tail}"


def test_docs_asset_sync_silent_on_non_deployed_doc(tmp_path):
    # CONVENTIONS.md IS init-seeded, but its packaged body is the hand-authored
    # adopter stub at espalier/assets/seed/CONVENTIONS.md — deliberately NOT a
    # byte-mirror of this file (managed_inventory._SEED_ASSET_SOURCES). The
    # nudge exists to keep byte-mirrors under espalier/assets/docs/ in sync, so
    # firing here would tell the operator to sync a mirror that must never
    # match. Being init-seeded is not what makes a doc need the nudge; having a
    # byte-pinned asset twin is.
    out = _fire("Edit", {"file_path": "/r/docs/CONVENTIONS.md", "new_string": "x"}, tmp_path)
    assert "assets/docs/" not in out
