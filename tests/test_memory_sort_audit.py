"""TP-297c — the memory re-sort backslide detector.

The detector's value is entirely in its calibration: a rule that fires on most
of the live population is noise, and the naive spellings of both classes do
exactly that (a "mentions a repo path" heuristic matches ~63% of the auto store;
a "no ESPALIER_MEMORY.md row" heuristic matches 22 of 40 committed entries, nearly all of
them legitimately reached via a folder router or an explicit ``(unlinked)``
declaration). These tests pin the calibrated behaviour so a later "simplify the
heuristic" edit has to earn the regression.

Deliberately NOT tested here: ``audit()`` against the live machine-local auto
store. That directory (``~/.claude/projects/<enc>/memory/``) is uncommitted,
Claude-written, and absent on CI and on any second machine — asserting on it
would red the suite from a file ``git status`` cannot see, while passing
vacuously everywhere it does not exist. The live-tree assertion below is scoped
to the repo-local half only.
"""
# slow-exempt: the one subprocess test is a single --repo invocation of a
# stdlib-only script over an in-repo glob (measured well under a second); it
# does not warrant dropping the module from the `not slow` fast slice.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "cc" / "memory_sort_audit.py"

sys.path.insert(0, str(REPO_ROOT / "tools" / "cc"))
import memory_sort_audit  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A repo skeleton with a committed memory/ entry and an isolated auto store."""
    (tmp_path / "memory").mkdir()
    (tmp_path / "ESPALIER_MEMORY.md").write_text(
        "# Index\n\n- [Widget lesson](memory/widget-lesson.md) — hook\n",
        encoding="utf-8",
    )
    (tmp_path / "memory" / "widget-lesson.md").write_text(
        '# Widget lesson\n\n**Status:** active\n'
        '**Linked from:** ESPALIER_MEMORY.md row "Widget lesson"\n\nbody\n',
        encoding="utf-8",
    )
    auto = tmp_path / "auto" / "memory"
    auto.mkdir(parents=True)
    monkeypatch.setattr(memory_sort_audit, "_project_dir", lambda cwd: auto.parent)
    return tmp_path, auto


class TestSuppressOnClean:
    def test_clean_repo_reports_nothing(self, fake_repo):
        repo, _ = fake_repo
        assert memory_sort_audit.audit(repo) == []

    def test_live_repo_committed_half_is_clean(self):
        """The self-host tree is the calibration population: the detector must
        be silent on it, or every real finding arrives buried in noise.

        Scoped to ``_audit_unlinked`` on purpose. The class-1 half reads an
        uncommitted machine-local directory; gating the committed suite on it
        would fail from a file outside git on this laptop and pass vacuously
        on every host where that directory does not exist."""
        assert memory_sort_audit._audit_unlinked(REPO_ROOT) == []

    def test_absent_auto_store_is_announced_not_silent(self, tmp_path, monkeypatch, capsys):
        """"Nothing to audit" must not render identically to "clean" — the
        vacuous case is exactly how a broken resolver reads as a pass."""
        monkeypatch.setattr(
            memory_sort_audit, "_project_dir", lambda cwd: tmp_path / "nope"
        )
        assert memory_sort_audit._audit_duplicates(tmp_path) == []
        assert "not audited" in capsys.readouterr().err

    def test_exit_code_is_zero_with_findings(self, fake_repo):
        """Advisory reporter: exit 0 even when it has something to say. Exit 2
        is the blocking channel and would turn store tidiness into a gate.

        The orphan must flag under the fail-soft contract: a real ``git init``
        repo (so ``_tracked_files`` is non-empty) with a headerless, unreferenced
        entry is a genuine orphan -- the finding is real, not a git-unavailable
        false positive."""
        repo, _ = fake_repo
        (repo / "memory" / "orphan.md").write_text(
            "# Orphan\n\n**Status:** active\n\nbody\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert memory_sort_audit.audit(repo), "fixture should produce a finding"
        assert memory_sort_audit.main(["--repo", str(repo)]) == 0


class TestDuplicatedAcrossStores:
    def test_non_pointer_twin_is_flagged(self, fake_repo):
        repo, auto = fake_repo
        (auto / "widget-lesson.md").write_text(
            "---\nname: widget-lesson\n---\n\nA full second copy.\n", encoding="utf-8"
        )
        findings = memory_sort_audit.audit(repo)
        assert any("[duplicated-across-stores]" in f for f in findings)

    def test_sharp_edges_twin_is_flagged(self, fake_repo):
        """The committed layer spans docs/sharp-edges/, not just memory/
        (docs/MEMORY_SYSTEMS.md: "harness/... -> the committed repo layer
        (memory/, docs/)"). An auto note duplicating a sharp-edges twin must
        flag, naming the sharp-edges home. Globbing only memory/ (HEAD) reds
        this — the fail-open I2 closes. The slug is absent from memory/, so the
        finding can ONLY come from the docs/sharp-edges/ arm."""
        repo, auto = fake_repo
        (repo / "docs" / "sharp-edges").mkdir(parents=True)
        (repo / "docs" / "sharp-edges" / "widget-footgun.md").write_text(
            "# Widget footgun\n\nA committed sharp edge.\n", encoding="utf-8"
        )
        (auto / "widget-footgun.md").write_text(
            "---\nname: widget-footgun\n---\n\nA full second copy.\n", encoding="utf-8"
        )
        findings = memory_sort_audit.audit(repo)
        assert any(
            "[duplicated-across-stores]" in f
            and "docs/sharp-edges/widget-footgun.md" in f
            for f in findings
        ), f"sharp-edges twin not flagged (memory/-only fail-open): {findings}"

    def test_standing_principles_twin_is_flagged(self, fake_repo):
        """STANDING_PRINCIPLES.md is the third committed home. An auto note that
        exactly duplicates it flags, naming that doc — earns its inclusion in
        the widened twin set."""
        repo, auto = fake_repo
        (repo / "docs").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "STANDING_PRINCIPLES.md").write_text(
            "# Standing principles\n\nThe committed principles.\n", encoding="utf-8"
        )
        (auto / "standing-principles.md").write_text(
            "---\nname: standing-principles\n---\n\nA machine-local copy.\n",
            encoding="utf-8",
        )
        findings = memory_sort_audit.audit(repo)
        assert any(
            "[duplicated-across-stores]" in f and "docs/STANDING_PRINCIPLES.md" in f
            for f in findings
        ), f"STANDING_PRINCIPLES twin not flagged: {findings}"

    def test_monolithic_doc_twin_is_flagged(self, fake_repo):
        """The sorting rule routes footguns/failure-modes to the MONOLITHIC docs
        (docs/SHARP_EDGES.md, docs/FAILURE_MODES.md, docs/CONVENTIONS.md,
        docs/AUTONOMOUS_EXECUTION.md), whose lessons live under ##/### headings,
        not one-file-per-lesson. Globbing only memory/ + docs/sharp-edges/ +
        STANDING_PRINCIPLES.md (the pre-TP-315 twin-set) left an auto note
        duplicating a monolithic-doc SECTION invisible — a false-clean for the
        whole file-set. This earns the red: the slug is absent from every other
        twin arm, so a [duplicated-across-stores] finding naming FAILURE_MODES.md
        can ONLY come from the new monolithic-doc arm (RED without 1-A)."""
        repo, auto = fake_repo
        (repo / "docs").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "FAILURE_MODES.md").write_text(
            "# Failure modes\n\n"
            "## Widget pipeline race condition\n\n"
            "A committed failure-mode lesson under a section heading.\n",
            encoding="utf-8",
        )
        (auto / "widget-pipeline-race-condition.md").write_text(
            "---\nname: widget-pipeline-race-condition\n---\n\n"
            "A machine-local copy of a lesson that already lives in FAILURE_MODES.md.\n",
            encoding="utf-8",
        )
        findings = memory_sort_audit.audit(repo)
        assert any(
            "[duplicated-across-stores]" in f and "docs/FAILURE_MODES.md" in f
            for f in findings
        ), f"monolithic-doc twin not flagged (pre-TP-315 blind spot): {findings}"

    def test_convention_heading_collision_suppressed(self, fake_repo, monkeypatch):
        """A CONVENTION/architecture heading can share subsystem vocabulary with a
        DISTINCT auto-memory footgun without being the same lesson. The CONVENTIONS
        state_cache heading shares {state,cache,freshness,check,writes} with the
        git-stash footgun note, but the note is NOT a duplicate of that convention
        section — a coincidental token overlap. `_GENERIC_HEADINGS` suppresses the
        false match; this pins the suppression so a later edit cannot silently
        reintroduce the FP. The monkeypatch arm earns the red: with the stop-set
        emptied, the coincidental match re-fires, proving the entry is load-bearing
        (not decorative)."""
        repo, auto = fake_repo
        (repo / "docs").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "CONVENTIONS.md").write_text(
            "# Conventions\n\n"
            "### Consumers read `state_cache`; only `freshness check` writes it\n\n"
            "The state_cache read/write discipline (a convention, not a footgun).\n",
            encoding="utf-8",
        )
        (auto / "freshness-check-writes-state-cache-git-stash-strands-work.md").write_text(
            "---\nname: freshness-check-writes-state-cache-git-stash-strands-work\n---\n\n"
            "A git-stash footgun: freshness check writes state_cache and strands work.\n",
            encoding="utf-8",
        )
        flagged = lambda: any(  # noqa: E731
            "[duplicated-across-stores]" in f
            and "freshness-check-writes-state-cache" in f
            for f in memory_sort_audit.audit(repo)
        )
        # Suppressed: the convention heading is in _GENERIC_HEADINGS -> no twin.
        assert not flagged(), "state_cache convention/footgun collision must be suppressed"
        # Earn-the-red: drop the suppression -> the coincidental match re-flags.
        monkeypatch.setattr(memory_sort_audit, "_GENERIC_HEADINGS", frozenset())
        assert flagged(), (
            "without the suppression the FP must reappear -- proves the "
            "_GENERIC_HEADINGS entry is load-bearing, not decorative"
        )

    @pytest.mark.parametrize(
        "marker", ["Migrated to the repo", "Canonized in the repo"]
    )
    def test_either_pointer_marker_suppresses(self, fake_repo, marker):
        """Both spellings are live in the store. Matching only one misreads
        every note using the other as an un-migrated duplicate — the exact
        false positive that made the first draft of this rule unusable."""
        repo, auto = fake_repo
        (auto / "widget-lesson.md").write_text(
            f"---\nname: widget-lesson\n---\n\n> **{marker}:** see memory/widget-lesson.md.\n",
            encoding="utf-8",
        )
        assert memory_sort_audit.audit(repo) == []

    def test_prose_mention_of_the_marker_does_not_exempt(self, fake_repo):
        """The marker must be the note's own pointer line, not any occurrence
        in the body — otherwise a note ABOUT the migration convention quotes
        the phrase and permanently exempts itself."""
        repo, auto = fake_repo
        (auto / "widget-lesson.md").write_text(
            "---\nname: widget-lesson\n---\n\n"
            "A full second copy that happens to discuss how we mark a note "
            "Migrated to the repo when collapsing it.\n",
            encoding="utf-8",
        )
        findings = memory_sort_audit.audit(repo)
        assert any("[duplicated-across-stores]" in f for f in findings)

    @pytest.mark.parametrize(
        "slug_a,slug_b,same",
        [
            # Function words alone must not merge two distinct lessons.
            ("fix-the-pack-and-proceed", "fix-the-pack-and-stop", False),
            ("do-not-trust-the-oracle", "do-not-trust-the-clock", False),
            # Real vocabulary drift between the stores must still merge.
            ("verify-pack-scope-out-rationale", "verify-a-packs-scope-out-rationale", True),
        ],
    )
    def test_stopwords_gate_slug_similarity(self, slug_a, slug_b, same):
        assert memory_sort_audit._same_subject(slug_a, slug_b) is same

    def test_unrelated_auto_entry_is_not_flagged(self, fake_repo):
        """An operator/machine fact with no committed twin stays put, even
        though it names repo paths — that is correct sorting, not backslide."""
        repo, auto = fake_repo
        (auto / "local-python-is-python3.md").write_text(
            "---\nname: local-python-is-python3\n---\n\n"
            "Use python3; see tools/cc/ and espalier/ and docs/ and tests/.\n",
            encoding="utf-8",
        )
        assert memory_sort_audit.audit(repo) == []


class TestUnlinkedRepoMemory:
    def test_rotted_row_claim_is_flagged(self, fake_repo):
        repo, _ = fake_repo
        (repo / "memory" / "rotted.md").write_text(
            '# Rotted\n\n**Status:** active\n'
            '**Linked from:** ESPALIER_MEMORY.md row "Gone"\n\nbody\n',
            encoding="utf-8",
        )
        findings = memory_sort_audit.audit(repo)
        assert any("[unlinked-repo-memory]" in f and "rotted.md" in f for f in findings)

    def test_multiline_claim_is_read_past_line_one(self, fake_repo):
        """A wrapped claim must be verified in full. A line-bounded regex would
        truncate at the newline and silently pass anything on line 2+."""
        repo, _ = fake_repo
        (repo / "memory" / "wrapped.md").write_text(
            "# Wrapped\n\n**Status:** active\n"
            "**Linked from:** the cool-store router, and formerly\n"
            '                 ESPALIER_MEMORY.md row "Gone"\n\nbody\n',
            encoding="utf-8",
        )
        findings = memory_sort_audit.audit(repo)
        assert any("wrapped.md" in f for f in findings), (
            "claim on a continuation line escaped verification"
        )

    def test_declared_unlinked_is_not_flagged(self, fake_repo):
        """memory/README.md sanctions '(unlinked)' for standalone notes."""
        repo, _ = fake_repo
        (repo / "memory" / "standalone.md").write_text(
            "# Standalone\n\n**Status:** active\n"
            "**Linked from:** (unlinked) — standalone reference.\n\nbody\n",
            encoding="utf-8",
        )
        assert memory_sort_audit.audit(repo) == []

    def test_router_reached_entry_is_not_flagged(self, fake_repo):
        """An entry homed at a folder router rather than the capped hot index
        is correctly homed; the 120-line ESPALIER_MEMORY.md cap makes this the normal
        resting state for an aged-out lesson, not a defect."""
        repo, _ = fake_repo
        (repo / "memory" / "routed.md").write_text(
            "# Routed\n\n**Status:** active\n"
            "**Linked from:** memory/ cool-store — via the `memory/CLAUDE.md` router\n"
            "\nbody\n",
            encoding="utf-8",
        )
        assert memory_sort_audit.audit(repo) == []

    def test_headerless_entry_with_inbound_link_is_not_flagged(self, fake_repo):
        repo, _ = fake_repo
        (repo / "memory" / "atlas.md").write_text(
            "# Atlas\n\n**Status:** active\n\nbody\n", encoding="utf-8"
        )
        (repo / "memory" / "widget-lesson.md").write_text(
            '# Widget lesson\n\n**Status:** active\n'
            '**Linked from:** ESPALIER_MEMORY.md row "Widget lesson"\n\nsee [[atlas]]\n',
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert memory_sort_audit.audit(repo) == []


class TestDeadPathHome:
    """Class 2, the broader case: a `**Linked from:**` whose declared home is a
    PATH that is gitignored or removed (e.g. a landed-and-deleted task-pack) is a
    dead breadcrumb, not a home. When it is the SOLE home and nothing else
    reaches the file, that is the same orphaning `collapse-adds-...` instanced —
    only via a path target instead of a session-row claim. A durable co-home
    (a tracked file) or any inbound link keeps it correctly homed."""

    def test_dead_path_only_home_is_flagged(self, fake_repo):
        """A memory file homed ONLY at a gitignored/removed path, with nothing
        else reaching it, is orphaned and must flag. Earn-the-red: the pre-fix
        code trusts any non-row `Linked from:` and reports nothing here."""
        repo, _ = fake_repo
        (repo / "memory" / "deadhome.md").write_text(
            "# Dead home\n\n**Status:** active\n"
            "**Linked from:** `task-packs/Done/TP-999-gone.md` (after landing)\n\nbody\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        findings = memory_sort_audit._audit_unlinked(repo)
        assert any("[unlinked-repo-memory]" in f and "deadhome.md" in f for f in findings), (
            f"a memory file homed only at a gitignored/removed path must flag: {findings}"
        )

    def test_dead_path_with_valid_cohome_is_not_flagged(self, fake_repo):
        """A dead path ALONGSIDE a durable co-home (a tracked file) is reachable.
        The hardening must not over-flag an intentional soft provenance
        breadcrumb — only a SOLE dead home orphans the file."""
        repo, _ = fake_repo
        (repo / "CLAUDE.md").write_text("# Root\n\nSee memory/cohomed.md\n", encoding="utf-8")
        (repo / "memory" / "cohomed.md").write_text(
            "# Co-homed\n\n**Status:** active\n"
            "**Linked from:** [CLAUDE.md](../CLAUDE.md), "
            "`task-packs/Done/TP-999-gone.md` (after landing)\n\nbody\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        findings = memory_sort_audit._audit_unlinked(repo)
        assert not any("cohomed.md" in f for f in findings), (
            f"a dead path with a valid ../CLAUDE.md co-home must not flag: {findings}"
        )

    def test_headerless_entry_failsoft_when_git_unavailable(self, fake_repo, monkeypatch):
        """Fail-soft contract: with git unavailable (``_tracked_files`` returns []),
        the inbound-link scan has nothing to read, so ``_has_inbound_link`` is False
        for EVERY entry -- a headerless-but-reachable entry must NOT be flagged.
        Earn-the-red: the pre-fix headerless branch (``if not _has_inbound_link``)
        flags it anyway, the same fail-open the sibling dead-path branch already
        guards with its ``tracked_set`` truthiness check.

        Unlike the other tests in this class (which spin up a real ``git init``
        repo), this one monkeypatches ``_tracked_files`` to [] to simulate the
        git-unavailable / not-a-work-tree case directly -- a fresh clone, a second
        machine, or CI where the cwd is not a work tree."""
        repo, _ = fake_repo
        # Isolate: drop the fixture's homed widget entry so the only memory/ file
        # in play is the headerless reachable one under test.
        (repo / "memory" / "widget-lesson.md").unlink()
        (repo / "memory" / "reachable.md").write_text(
            "# Reachable\n\n**Status:** active\n\nbody, no linked-from header\n",
            encoding="utf-8",
        )
        (repo / "ESPALIER_MEMORY.md").write_text(
            "# Index\n\n- see memory/reachable.md for the widget lesson\n",
            encoding="utf-8",
        )
        # Simulate git unavailable / not a work tree: tracked resolves to [].
        monkeypatch.setattr(memory_sort_audit, "_tracked_files", lambda repo: [])
        findings = memory_sort_audit._audit_unlinked(repo)
        assert not any("reachable.md" in f for f in findings), (
            f"a headerless entry must fail soft when git is unavailable: {findings}"
        )

    def test_live_action_justification_not_flagged(self):
        """Live false-positive guard: action-justification-protocol.md carries a
        durable CLAUDE.md co-home beside a dead `task-packs/Done/TP-126-...` path.
        The class-fix must leave it — the design flags only a SOLE dead home."""
        findings = memory_sort_audit._audit_unlinked(REPO_ROOT)
        assert not any("action-justification-protocol.md" in f for f in findings), (
            f"co-homed soft breadcrumb wrongly flagged: {findings}"
        )


class TestIsolationContract:
    def test_zero_espalier_imports(self):
        """tools/cc/ scripts run standalone — CLAUDE.md architecture rule."""
        body = SCRIPT.read_text(encoding="utf-8")
        assert "import espalier" not in body
        assert "from espalier" not in body

    def test_runs_standalone_as_a_subprocess(self):
        """The way an operator actually invokes it, not just as an import."""
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(REPO_ROOT)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert proc.returncode == 0, proc.stderr


class TestRepoRootWhenGitPrintsAPathTheDecoderRefuses:
    """Ledger DEF-821. ``_repo_root`` reads ``git rev-parse --show-toplevel``
    and uses the answer as a filesystem root. A root with a byte UTF-8
    refuses used to raise; a replacement character would have produced a
    root that does not exist, which returns no findings, which reads as
    clean (the comment above the call names exactly that). The strict decode
    under a handler naming ValueError takes the existing fallback instead.
    The oracle is a ``git`` on PATH that prints such a path; skips where
    ``sh`` is absent; unverified on Windows."""

    def test_a_non_decodable_toplevel_falls_back_to_cwd(self, tmp_path, monkeypatch):
        import importlib.util
        import os
        import shutil
        if os.name == "nt" or shutil.which("sh") is None:
            pytest.skip("the git shim is a /bin/sh script")
        spec = importlib.util.spec_from_file_location(
            "memory_sort_audit_under_test",
            Path(__file__).resolve().parent.parent / "tools" / "cc" / "memory_sort_audit.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        shim = bindir / "git"
        shim.write_text("#!/bin/sh\nprintf '/tmp/caf\\351repo\\n'\n", encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
        monkeypatch.chdir(tmp_path)
        assert mod._repo_root(None) == Path.cwd().resolve()
