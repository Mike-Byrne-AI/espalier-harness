"""Gap-coverage tests for ``espalier.cli`` — the corners of the CLI
that ``test_cli_commands.py`` and ``test_init.py`` do not exercise.

Already covered by ``test_cli_commands.py``:
  cmd_init, cmd_fingerprint, cmd_audit, cmd_doctor, cmd_diff, cmd_recover,
  cmd_reflect, cmd_reflect_deep, cmd_scan, cmd_clean_generated, cmd_release_pack,
  cmd_pre_release, cmd_blueprint (start + chain), cmd_worktree_plan,
  cmd_blueprint_handoff, main(), _build_settings_json, build_parser/--version

Already covered by ``test_init.py``:
  _build_settings_json structure, portability contract, init deploy details

This file covers the gaps:
  _build_claude_md, _build_memory_md, _write_seed,
  cmd_blueprint (record, finalize, load, unknown action),
  cmd_self_host, cmd_integrity (unknown action), build_parser (subcommands exist),
  _espalier_root.

Pins the seldom-exercised render and deploy helpers plus the
unhappy-path branches of the blueprint and integrity subcommands.
Without this contract, refactors that touch only these gap helpers
would silently break behavior the larger CLI suites never look at,
and the regression would only surface when an adopter hits the
exact corner case in production.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace with sensible defaults for any cmd_* function."""
    defaults = {"config": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── _build_claude_md ─────────────────────────────────────────────────────────


class TestBuildClaudeMd:
    def _make_fp(self, repo_name="test-repo", languages=("Python",)):
        fp = MagicMock()
        fp.repo_name = repo_name
        fp.languages = list(languages)
        return fp

    def _make_harness(self, profiles=("python",)):
        h = MagicMock()
        h.profiles = list(profiles)
        return h

    def test_returns_string(self):
        from espalier.cli import _build_claude_md
        result = _build_claude_md(self._make_fp(), self._make_harness())
        assert isinstance(result, str)

    def test_contains_repo_name(self):
        from espalier.cli import _build_claude_md
        result = _build_claude_md(self._make_fp("my-service"), self._make_harness())
        assert "my-service" in result

    def test_contains_governance_harness_label(self):
        from espalier.cli import _build_claude_md
        result = _build_claude_md(self._make_fp(), self._make_harness())
        assert "Governance Harness" in result

    def test_contains_session_start_hook(self):
        from espalier.cli import _build_claude_md
        result = _build_claude_md(self._make_fp(), self._make_harness())
        assert "session_start.py" in result

    def test_contains_language(self):
        from espalier.cli import _build_claude_md
        result = _build_claude_md(self._make_fp(languages=["Rust"]), self._make_harness())
        assert "Rust" in result

    def test_neutral_test_fallback_when_no_test_commands(self):
        """TP-174a T02: a non-Python adopter with no detected test command must
        NOT be told to run `pytest -q`; render a neutral placeholder."""
        from espalier.cli import _build_claude_md
        fp = self._make_fp(languages=["Rust"])
        fp.test_commands = []
        fp.architecture = {}
        result = _build_claude_md(fp, self._make_harness())
        assert "configure your test command" in result

    def test_detected_test_command_used_when_present(self):
        from espalier.cli import _build_claude_md
        fp = self._make_fp()
        fp.test_commands = ["cargo test"]
        fp.architecture = {}
        result = _build_claude_md(fp, self._make_harness())
        assert "cargo test" in result

    def test_src_layout_renders_plan_exempt_hint(self):
        """TP-174a T19: a src/-layout adopter gets the plan_exempt_prefixes hint."""
        from espalier.cli import _build_claude_md
        fp = self._make_fp()
        fp.test_commands = ["pytest -q"]
        fp.architecture = {"pattern": "src_layout"}
        result = _build_claude_md(fp, self._make_harness())
        assert "plan_exempt_prefixes" in result
        assert 'plan_exempt_prefixes = ["src/"]' in result

    def test_non_src_layout_renders_generic_plan_exempt_hint(self):
        """TP-176 W2-1: a non-src adopter layout (flat/mvc — where JS lib/ and
        Go cmd/ repos fingerprint) hits the same plan-required deny as src/,
        so it must get the hint too — with generic, non-src-hardcoded wording.
        """
        from espalier.cli import _build_claude_md
        fp = self._make_fp()
        fp.test_commands = ["pytest -q"]
        fp.architecture = {"pattern": "flat"}
        result = _build_claude_md(fp, self._make_harness())
        assert "plan_exempt_prefixes" in result
        assert 'plan_exempt_prefixes = ["your-source-root/"]' in result

    def test_harness_layered_omits_plan_exempt_hint(self):
        """TP-176 W2-1: the self-host repo (harness_layered) ships a
        hand-written Plan Guard section, so init must not render its own.

        Asserts the SECTION's absence rather than the bare token
        ``plan_exempt_prefixes``. The bare token was a proxy that held only
        while the Plan Guard block was the single place it appeared; the
        unconditional ``## Maintenance mode`` section now cross-references the
        same knob in prose ("don't reach for maintenance mode, use
        plan_exempt_prefixes"), which the proxy would read as a Plan Guard
        section that is not there. Both assertions below are tighter than the
        proxy on the intent this test names: no heading, and no TOML example
        block (the ``= [`` form only the Plan Guard section emits).
        """
        from espalier.cli import _build_claude_md
        fp = self._make_fp()
        fp.test_commands = ["pytest -q"]
        fp.architecture = {"pattern": "harness_layered"}
        result = _build_claude_md(fp, self._make_harness())
        assert "## Plan Guard" not in result
        assert 'plan_exempt_prefixes = ["' not in result

    def test_fallback_when_no_languages(self):
        from espalier.cli import _build_claude_md
        result = _build_claude_md(self._make_fp(languages=[]), self._make_harness())
        assert "unknown" in result

    def test_fallback_repo_name_when_none(self):
        from espalier.cli import _build_claude_md
        fp = self._make_fp()
        fp.repo_name = None
        result = _build_claude_md(fp, self._make_harness())
        assert "this project" in result


# ── _build_memory_md ─────────────────────────────────────────────────────────


class TestBuildMemoryMd:
    def _make_fp(self, repo_name="test-repo", languages=("Python",)):
        fp = MagicMock()
        fp.repo_name = repo_name
        fp.languages = list(languages)
        return fp

    def test_returns_string(self):
        from espalier.cli import _build_memory_md
        result = _build_memory_md(self._make_fp())
        assert isinstance(result, str)

    def test_contains_repo_name(self):
        from espalier.cli import _build_memory_md
        result = _build_memory_md(self._make_fp("cool-project"))
        assert "cool-project" in result

    def test_contains_session_log_section(self):
        from espalier.cli import _build_memory_md
        result = _build_memory_md(self._make_fp())
        assert "Session Log" in result

    def test_contains_harness_decisions_section(self):
        from espalier.cli import _build_memory_md
        result = _build_memory_md(self._make_fp())
        assert "Harness Decisions" in result

    def test_contains_patterns_section(self):
        from espalier.cli import _build_memory_md
        result = _build_memory_md(self._make_fp())
        assert "Patterns Learned" in result

    def test_fallback_repo_name_when_none(self):
        from espalier.cli import _build_memory_md
        fp = self._make_fp()
        fp.repo_name = None
        result = _build_memory_md(fp)
        assert "this project" in result

    def test_contains_language(self):
        from espalier.cli import _build_memory_md
        result = _build_memory_md(self._make_fp(languages=["Go"]))
        assert "Go" in result


# ── _write_seed ──────────────────────────────────────────────────────────────


class TestWriteSeed:
    """``_write_seed`` writes a seed's rendered body under its seed-version
    stamp and decides refresh / preserve / skip from that stamp. Until
    2026-09-05 these were the non-``.py`` branch of a path-based
    ``_deploy_file`` that also composed the body (adapt header + source text);
    the composition is now ``managed_inventory.render_seed_body`` -- shared
    with ``doctor``, which prints the stamp of that body (DEF-696) and pinned
    against a driven ``init`` in ``test_managed_inventory.py`` -- and this
    helper only writes. The ``.py`` branch that class also carried had no
    production caller (hook and tool scripts deploy through
    ``_deploy_managed_py``) and went with it."""

    def test_creates_parent_directories_and_stamps(self, tmp_path):
        from espalier.cli import _write_seed
        from espalier.managed_inventory import seed_stamp_line
        dest = tmp_path / "deep" / "nested" / "doc.md"
        assert _write_seed(dest, "BODY\n", label=dest.name) is True
        assert dest.read_text(encoding="utf-8") == seed_stamp_line("BODY\n") + "BODY\n"

    def test_header_is_part_of_the_stamped_body(self, tmp_path):
        # A Tier-2 seed carries the adapt header BELOW the stamp and INSIDE its
        # digest: the renderer composes it, the writer stamps what it is given.
        from espalier.cli import _write_seed
        from espalier.managed_inventory import SEED_ADAPT_HEADER, seed_stamp_line
        dest = tmp_path / "out" / "doc.md"
        rendered = SEED_ADAPT_HEADER + "BODY\n"
        assert _write_seed(dest, rendered, label=dest.name) is True
        # encoding="utf-8" is load-bearing, not decoration: SEED_ADAPT_HEADER
        # contains an em-dash, and a bare read_text() decodes with the locale
        # encoding -- cp1252 on Windows -- which turns it into U+FFFD and fails
        # this comparison for a file that was written correctly.
        assert dest.read_text(encoding="utf-8") == seed_stamp_line(rendered) + rendered

    def test_skips_an_unstamped_existing_copy(self, tmp_path):
        # A legacy or adopter-authored copy with no stamp cannot be proven
        # untouched: preserved, reported as skipped.
        from espalier.cli import _write_seed
        dest = tmp_path / "doc.md"
        dest.write_text("# adopter's own\n", encoding="utf-8")
        assert _write_seed(dest, "BODY\n", label=dest.name) is False
        assert dest.read_text(encoding="utf-8") == "# adopter's own\n"

    def test_refreshes_untouched_seed_on_drift(self, tmp_path):
        # 1-B earn-red: re-deploying an operator-UNTOUCHED seed doc whose
        # packaged content changed refreshes it to the new bytes. Pre-fix the
        # unconditional skip-if-exists kept the stale copy forever.
        from espalier.cli import _write_seed
        dest = tmp_path / "out" / "seed.md"
        assert _write_seed(dest, "OLD BODY\n", label=dest.name) is True             # create (stamped)
        assert _write_seed(dest, "NEW BODY\n", label=dest.name) is True             # untouched -> refresh
        text = dest.read_text(encoding="utf-8")
        assert text.endswith("NEW BODY\n")
        assert "OLD BODY" not in text

    def test_the_seed_banner_says_what_re_init_does(self, tmp_path):
        """DEF-432: the banner promised "never overwritten on re-init" while the
        refresh path above rewrote an untouched seed. Drive both outcomes, then
        read the sentence the adopter is given against them."""
        from espalier.cli import _write_seed
        from espalier.managed_inventory import SEED_ADAPT_HEADER
        dest = tmp_path / "out" / "seed.md"
        assert _write_seed(dest, SEED_ADAPT_HEADER + "OLD\n", label=dest.name) is True
        assert _write_seed(dest, SEED_ADAPT_HEADER + "NEW\n", label=dest.name) is True   # untouched: refreshed
        assert dest.read_text(encoding="utf-8").endswith("NEW\n")
        dest.write_text(dest.read_text(encoding="utf-8") + "my edit\n", encoding="utf-8")
        assert _write_seed(dest, SEED_ADAPT_HEADER + "NEWER\n", label=dest.name) is False  # edited: kept
        assert dest.read_text(encoding="utf-8").endswith("my edit\n")
        assert "never overwritten" not in SEED_ADAPT_HEADER
        assert "refreshed on re-init only while it still matches" in " ".join(
            SEED_ADAPT_HEADER.split()
        )

    def test_a_reverted_edit_matches_its_stamp_again_and_is_refreshed(self, tmp_path):
        """The corner the stubs' first wording ("your first edit makes it
        permanent") overclaimed: an edit undone byte for byte matches the
        stamp again, so the next drift refreshes the copy. The wording every
        copy now carries ("while it still matches the copy it was deployed
        from") survives it."""
        from espalier.cli import _write_seed
        dest = tmp_path / "out" / "seed.md"
        assert _write_seed(dest, "OLD\n", label=dest.name) is True
        deployed = dest.read_text(encoding="utf-8")
        dest.write_text(deployed + "edit\n", encoding="utf-8")
        dest.write_text(deployed, encoding="utf-8")          # reverted byte for byte
        assert _write_seed(dest, "NEW\n", label=dest.name) is True             # matches again: refreshed

    @staticmethod
    def _tracked_texts(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
        # The suite's git oracle (never a raw git call, which the suite
        # ratchets, and never a silently empty list): the floor is far below
        # the tree's real count and only rules out a foreign population.
        from tests._git_oracle import require_tracked_paths
        tracked = require_tracked_paths(
            root, *[f"*{s}" for s in suffixes], minimum=200,
            what="tracked markdown and Python files",
        )
        return [root / p for p in tracked]

    def test_no_copy_of_the_old_promise_survives(self):
        """Every tracked markdown and Python file, checked for the ABSENCE of
        the sentences the writer refutes -- derived from the git index, not
        a hand-listed set: the first cut listed five files and missed the
        fourth copy of the quotation in the deployed reflect protocol and the
        hook rationale that rested on the old rule (the review drove both).
        Record surfaces narrate the old wording as history and are excluded."""
        root = Path(__file__).resolve().parent.parent
        records = (
            "CHANGELOG.md", "docs/session-archive.md",
            "docs/RELEASE_DECISIONS.md", "docs/SHARP_EDGES.md",
            "tests/test_cli.py",
            # the task arm quotes each lane's task text verbatim as a query record
            "tests/test_recall.py",
        )
        phrases = (
            "never overwritten on re-init",
            "skip-if-exists and yours",
            "never overwrites existing files",
            "never overwrites a deployed catalog",
        )
        offenders = [
            (path.relative_to(root).as_posix(), phrase)
            for path in self._tracked_texts(root, (".md", ".py"))
            if path.relative_to(root).as_posix() not in records and path.is_file()
            for phrase in phrases
            if phrase in path.read_text(encoding="utf-8", errors="replace")
        ]
        assert offenders == [], offenders

    def test_the_skill_quotes_the_stub_it_describes(self):
        """The reflect skill presents the stub's sentence in quotation marks;
        the quoted span must be a substring of the stub, or the marks lie
        (the drift this lane repaired, pinned)."""
        import re
        root = Path(__file__).resolve().parent.parent
        skill = (root / ".claude" / "skills" / "reflect" / "SKILL.md").read_text(encoding="utf-8")
        quotes = [
            " ".join(m.group(1).split())
            for m in re.finditer(r'\*"([^"]+)"\*', skill)
        ]
        spans = [q for q in quotes if "refreshed on re-init" in q]
        assert spans, f"the skill no longer quotes the stub's refresh sentence: {quotes}"
        (span,) = spans
        for name in ("SHARP_EDGES.md", "CONVENTIONS.md"):
            raw = (root / "espalier" / "assets" / "seed" / name).read_text(encoding="utf-8")
            # The stub carries the sentence in a blockquote; drop the markers
            # before flattening so the comparison is over words.
            stub = " ".join(re.sub(r"(?m)^\s*>\s?", "", raw).split())
            assert span in stub, (name, span)

    def test_byte_identical_redeploy_is_a_skip(self, tmp_path):
        # No churn: the same rendered body over its own stamped copy is a skip,
        # and the bytes are untouched (a version bump alone never rewrites).
        from espalier.cli import _write_seed
        dest = tmp_path / "seed.md"
        assert _write_seed(dest, "BODY\n", label=dest.name) is True
        before = dest.read_bytes()
        assert _write_seed(dest, "BODY\n", label=dest.name) is False
        assert dest.read_bytes() == before

    def test_preserves_operator_edited_seed_on_drift(self, tmp_path):
        # 1-B guard (green both sides): an operator-EDITED seed doc is never
        # clobbered on re-deploy, even when the packaged content changed.
        from espalier.cli import _write_seed
        dest = tmp_path / "out" / "seed.md"
        assert _write_seed(dest, "OLD BODY\n", label=dest.name) is True             # create (stamped)
        dest.write_text("OPERATOR EDIT\n", encoding="utf-8")       # operator adapts it
        assert _write_seed(dest, "NEW BODY\n", label=dest.name) is False            # preserved -> skip
        assert dest.read_text(encoding="utf-8") == "OPERATOR EDIT\n"

    def test_refreshes_untouched_tier2_seed_with_header_on_drift(self, tmp_path):
        # RE3: the refresh path composes stamp + adapt-header + body for a Tier-2
        # (header-carrying) seed doc, not just header-less docs -- the exact shape
        # a hurried refactor of the stamp/header composition would miss.
        from espalier.cli import _write_seed
        from espalier.managed_inventory import SEED_ADAPT_HEADER, seed_stamp_line
        dest = tmp_path / "out" / "doc.md"
        assert _write_seed(dest, SEED_ADAPT_HEADER + "OLD BODY\n", label=dest.name) is True  # create
        rendered = SEED_ADAPT_HEADER + "NEW BODY\n"
        assert _write_seed(dest, rendered, label=dest.name) is True                          # refresh
        assert dest.read_text(encoding="utf-8") == seed_stamp_line(rendered) + rendered

    def test_overwrite_true_clobbers_non_py_seed(self, tmp_path):
        # RE2/NIT1: overwrite=True is a deliberate unconditional clobber that
        # bypasses the untouched-check -- witnessed here so a future --force
        # reseed adopting overwrite=True gets pinned behavior, not incidental.
        from espalier.cli import _write_seed
        from espalier.managed_inventory import seed_stamp_line
        dest = tmp_path / "out" / "seed.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("OPERATOR EDIT (unstamped)\n", encoding="utf-8")
        assert _write_seed(dest, "NEW\n", overwrite=True, label=dest.name) is True
        assert dest.read_text(encoding="utf-8") == seed_stamp_line("NEW\n") + "NEW\n"


class TestSeedStampHelpers:
    """The seed-version stamp discriminates an operator edit from an untouched
    copy purely from an in-file first-line stamp. The token is a DISTINCT one
    (``espalier:seed-version``, not ``espalier:managed``) so the seed doc stays
    operator-owned for the cleanup lifecycle."""

    def test_seed_stamp_line_records_hash_of_body(self):
        import hashlib

        from espalier.managed_inventory import seed_stamp_line
        body = "HELLO BODY\n"
        line = seed_stamp_line(body)
        assert line.startswith("<!-- espalier:seed-version v")
        assert line.endswith(" -->\n")
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() in line
        # Distinct token -- must NOT read as espalier:managed (cleanup lifecycle).
        assert "espalier:managed" not in line

    def test_seed_redeploy_decision_refreshes_untouched_stale(self, tmp_path):
        # Stamped, operator-untouched, but the packaged content has since changed.
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import seed_stamp_line
        old = "OLD PACKAGED BODY\n"
        dest = tmp_path / "seed.md"
        dest.write_text(seed_stamp_line(old) + old, encoding="utf-8")
        assert _seed_redeploy_decision(dest, "NEW PACKAGED BODY\n") == "refresh"

    def test_seed_redeploy_decision_preserves_operator_edit(self, tmp_path):
        # Stamp records the original body; on-disk body differs -> operator edited.
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import seed_stamp_line
        original = "ORIGINAL BODY\n"
        dest = tmp_path / "seed.md"
        dest.write_text(seed_stamp_line(original) + "OPERATOR EDIT\n", encoding="utf-8")
        assert _seed_redeploy_decision(dest, "NEW PACKAGED BODY\n") == "preserve"

    def test_seed_redeploy_decision_preserves_unstamped_legacy(self, tmp_path):
        # WARN item-8 direct coverage: a legacy copy with no stamp cannot be
        # proven untouched -> preserve (the safe, backward-compatible fallback).
        from espalier.cli import _seed_redeploy_decision
        dest = tmp_path / "seed.md"
        dest.write_text("LEGACY UNSTAMPED BODY\n", encoding="utf-8")
        assert _seed_redeploy_decision(dest, "NEW PACKAGED BODY\n") == "preserve"

    def test_seed_redeploy_decision_preserves_byte_identical_packaged(self, tmp_path):
        # Stamped + untouched, packaged content unchanged -> no churn.
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import seed_stamp_line
        body = "SAME BODY\n"
        dest = tmp_path / "seed.md"
        dest.write_text(seed_stamp_line(body) + body, encoding="utf-8")
        assert _seed_redeploy_decision(dest, body) == "preserve"


# ── _espalier_root ─────────────────────────────────────────────────────────


class TestEspalierRoot:
    def test_returns_path(self):
        from espalier.cli import _espalier_root
        result = _espalier_root()
        assert isinstance(result, Path)

    def test_returned_root_contains_espalier_package(self):
        # TP-178: _espalier_root() returns the dir CONTAINING espalier/ (repo
        # root in editable installs, site-packages in wheel installs). It no
        # longer guarantees a sibling tools/cc/ — the wheel reads the deploy
        # source from espalier/_vendor/cc/ via _deploy_source_path().
        from espalier.cli import _espalier_root
        assert (_espalier_root() / "espalier").is_dir()

    def test_deploy_source_path_resolves_a_real_file(self):
        # The deploy SOURCE for a tools/cc-rooted rel_path resolves to a real
        # file in both install forms (source tree here; vendored copy in a wheel).
        from espalier.cli import _deploy_source_path
        p = _deploy_source_path("tools/cc/hooks/stop_gate.py")
        assert p.exists() and p.name == "stop_gate.py"


# ── cmd_blueprint — record / finalize / load / unknown ──────────────────────


class TestCmdBlueprintExtendedActions:
    def test_record_exits_1_without_description(self, harness_repo):
        from espalier.cli import cmd_blueprint
        # Start a session first
        cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                          kind=None, description=None, evidence=None,
                          fragments=None, json=False))
        ret = cmd_blueprint(_ns(
            repo=str(harness_repo), action="record",
            kind="decision", description=None, evidence=None,
            fragments=None, json=False,
        ))
        assert ret == 1

    def test_record_exits_0_with_description(self, harness_repo):
        from espalier.cli import cmd_blueprint
        cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                          kind=None, description=None, evidence=None,
                          fragments=None, json=False))
        ret = cmd_blueprint(_ns(
            repo=str(harness_repo), action="record",
            kind="decision", description="Chose pytest over unittest",
            evidence="pytest,coverage", fragments=None, json=False,
        ))
        assert ret == 0

    def test_record_exits_1_when_no_blueprint_exists(self, tmp_path):
        from espalier.cli import cmd_blueprint
        ret = cmd_blueprint(_ns(
            repo=str(tmp_path), action="record",
            kind="decision", description="Some decision",
            evidence=None, fragments=None, json=False,
        ))
        assert ret == 1

    def test_finalize_exits_0_after_start(self, harness_repo):
        from espalier.cli import cmd_blueprint
        cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                          kind=None, description=None, evidence=None,
                          fragments=None, json=False))
        ret = cmd_blueprint(_ns(
            repo=str(harness_repo), action="finalize",
            kind=None, description=None, evidence=None,
            fragments=None, json=False,
        ))
        assert ret == 0

    def test_finalize_exits_1_without_active_blueprint(self, tmp_path):
        from espalier.cli import cmd_blueprint
        ret = cmd_blueprint(_ns(
            repo=str(tmp_path), action="finalize",
            kind=None, description=None, evidence=None,
            fragments=None, json=False,
        ))
        assert ret == 1

    def test_finalize_with_custom_fragments(self, harness_repo):
        from espalier.cli import cmd_blueprint
        cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                          kind=None, description=None, evidence=None,
                          fragments=None, json=False))
        ret = cmd_blueprint(_ns(
            repo=str(harness_repo), action="finalize",
            kind=None, description=None, evidence=None,
            fragments="frag1|frag2", json=True,
        ))
        assert ret == 0

    def test_load_exits_0_after_start(self, harness_repo):
        from espalier.cli import cmd_blueprint
        cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                          kind=None, description=None, evidence=None,
                          fragments=None, json=False))
        ret = cmd_blueprint(_ns(
            repo=str(harness_repo), action="load",
            kind=None, description=None, evidence=None,
            fragments=None, json=False,
        ))
        assert ret == 0

    def test_load_exits_1_when_no_blueprint(self, tmp_path):
        from espalier.cli import cmd_blueprint
        ret = cmd_blueprint(_ns(
            repo=str(tmp_path), action="load",
            kind=None, description=None, evidence=None,
            fragments=None, json=False,
        ))
        assert ret == 1

    def test_load_json_mode_prints_valid_json(self, harness_repo, capsys):
        from espalier.cli import cmd_blueprint
        cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                          kind=None, description=None, evidence=None,
                          fragments=None, json=False))
        capsys.readouterr()  # drain the "Started session ..." output before load
        cmd_blueprint(_ns(
            repo=str(harness_repo), action="load",
            kind=None, description=None, evidence=None,
            fragments=None, json=True,
        ))
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert isinstance(parsed, dict)

    def test_unknown_action_exits_1(self, harness_repo):
        from espalier.cli import cmd_blueprint
        ret = cmd_blueprint(_ns(
            repo=str(harness_repo), action="not-a-real-action",
            kind=None, description=None, evidence=None,
            fragments=None, json=False,
        ))
        assert ret == 1


# ── cmd_self_host ─────────────────────────────────────────────────────────────


class TestCmdSelfHost:
    def test_returns_integer(self, harness_repo):
        from espalier.cli import cmd_self_host
        ret = cmd_self_host(_ns(repo=str(harness_repo)))
        assert isinstance(ret, int)

    def test_no_crash_on_empty_repo(self, tmp_path):
        from espalier.cli import cmd_self_host
        ret = cmd_self_host(_ns(repo=str(tmp_path)))
        assert ret in (0, 1)

    def test_outputs_json(self, harness_repo, capsys):
        from espalier.cli import cmd_self_host
        cmd_self_host(_ns(repo=str(harness_repo)))
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert isinstance(parsed, dict)


# ── cmd_integrity unknown action ─────────────────────────────────────────────


class TestCmdIntegrityUnknownAction:
    def test_unknown_action_exits_1(self, tmp_path):
        from espalier.cli import cmd_integrity
        ret = cmd_integrity(_ns(repo=str(tmp_path), action="unknown-action"))
        assert ret == 1


# ── cmd_integrity verify — absent-manifest parity with audit / doctor ────────


class TestCmdIntegrityVerifyUninitializedParity:
    """An absent manifest means two different things, and only one is a failure.

    ``.espalier/integrity.json`` is gitignored and per-install, so a repo someone
    cloned but has not run ``init`` on has no manifest BY CONSTRUCTION -- the
    ordinary state for a second developer on a governed repo, or for a contributor
    following CONTRIBUTING.md, which never runs ``init``. ``audit`` and ``doctor``
    both return 0 with first-run guidance there, and SessionStart exempts the same
    sentinel from its drift warning. ``verify`` was the one holdout, and it became
    load-bearing when the pre-PR gate started calling it: the gate would have
    hard-failed on a tree that was merely un-set-up.

    An INITIALIZED repo whose manifest has gone missing is the opposite case --
    something was removed -- and must still exit 1. Both directions are pinned
    here, because a fix that returned 0 for both would silently retire the
    tamper-detection signal this command exists to give.
    """

    def test_uninitialized_repo_is_guidance_not_failure(self, tmp_path, capsys):
        from espalier.cli import cmd_integrity
        ret = cmd_integrity(_ns(repo=str(tmp_path), action="verify"))
        assert ret == 0, "an un-inited tree must not read as tamper detection failing"
        out = capsys.readouterr().out
        assert "init" in out, f"the 0 must carry first-run guidance, got: {out!r}"

    def test_initialized_repo_with_a_missing_manifest_still_fails(self, tmp_path):
        # Same absent sentinel, opposite meaning: the deployed surface is present,
        # so the manifest's absence means it was removed rather than never made.
        from espalier.cli import cmd_integrity
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".espalier").mkdir()
        from espalier.repo_mode import (
            REPO_MODE_SOURCE_CHECKOUT,
            REPO_MODE_UNINITIALIZED,
            detect_repo_mode,
        )
        if detect_repo_mode(tmp_path) in (REPO_MODE_SOURCE_CHECKOUT, REPO_MODE_UNINITIALIZED):
            pytest.skip(
                "fixture did not reach an initialized repo_mode; the arm above already "
                "covers the uninitialized direction"
            )
        assert cmd_integrity(_ns(repo=str(tmp_path), action="verify")) == 1


# ── build_parser — structural checks ─────────────────────────────────────────


class TestBuildParser:
    def _parser(self):
        from espalier.cli import build_parser
        return build_parser()

    def test_parser_is_argumentparser(self):
        import argparse as ap
        assert isinstance(self._parser(), ap.ArgumentParser)

    def test_prog_name_is_espalier(self):
        assert self._parser().prog == "espalier"

    def test_pre_release_help_gates_its_self_host_script_mentions(self):
        """``scripts/`` is not deployed by ``init``, so an adopter reading this
        help would be sent to a path their tree does not contain. Both mentions
        carry TP-382's standardized gate phrase.

        Asserted on the SOURCE strings, not the rendered help: argparse hard-
        wraps at the terminal width and will split ``self-host`` across lines,
        so a rendered-text assertion fails on a formatting detail rather than a
        missing gate.
        """
        parser = self._parser()
        sub = next(
            a for a in parser._actions if getattr(a, "choices", None) and "pre-release" in a.choices
        )
        pre = sub.choices["pre-release"]

        assert "scripts/final_release_matrix.py" in pre.description
        assert "self-host only" in pre.description, pre.description

        skip = next(a for a in pre._actions if "--skip-release-check" in a.option_strings)
        assert "scripts/release_check.py" in skip.help
        assert "self-host only" in skip.help, skip.help

    def test_init_subcommand_exists(self):
        p = self._parser()
        args = p.parse_args(["init", "/tmp"])
        assert args.command == "init"

    def test_fingerprint_subcommand_exists(self):
        p = self._parser()
        args = p.parse_args(["fingerprint", "/tmp"])
        assert args.command == "fingerprint"

    def test_audit_subcommand_exists(self):
        p = self._parser()
        args = p.parse_args(["audit", "/tmp"])
        assert args.command == "audit"

    def test_scan_subcommand_exists(self):
        p = self._parser()
        args = p.parse_args(["scan", "/tmp"])
        assert args.command == "scan"

    def test_upgrade_subcommand_exists(self):
        # TP-189-D CAPGAP-1: `espalier upgrade` subparser, TP-189-C CLI-1 repo arg.
        p = self._parser()
        assert p.parse_args(["upgrade", "/tmp"]).command == "upgrade"
        assert p.parse_args(["upgrade"]).repo == "."        # bare defaults to cwd
        assert p.parse_args(["upgrade", "/tmp", "--execute"]).execute is True

    def test_doctor_subcommand_skip_self_host_flag(self):
        p = self._parser()
        args = p.parse_args(["doctor", "/tmp", "--skip-self-host"])
        assert args.skip_self_host is True

    def test_blueprint_subcommand_action_choices(self):
        p = self._parser()
        args = p.parse_args(["blueprint", "/tmp", "start"])
        assert args.action == "start"

    def test_integrity_subcommand_action_choices(self):
        p = self._parser()
        args = p.parse_args(["integrity", "verify", "/tmp"])
        assert args.action == "verify"

    def test_reflect_deep_pass_number_default(self):
        p = self._parser()
        args = p.parse_args(["reflect-deep", "/tmp"])
        assert args.pass_number == 1

    def test_reflect_deep_pass_number_custom(self):
        p = self._parser()
        args = p.parse_args(["reflect-deep", "/tmp", "--pass-number", "3"])
        assert args.pass_number == 3

    def test_clean_generated_execute_flag(self):
        p = self._parser()
        args = p.parse_args(["clean-generated", "/tmp", "--execute"])
        assert args.execute is True

    def test_empty_repo_arg_rejected(self):
        """DR7 round-7 (TP-196): an empty-string REPO positional (e.g. from an
        unset shell var `espalier audit "$TARGET"`) used to resolve to cwd and
        exit 0 on the wrong tree. The _nonempty_path type rejects it at parse
        time across every command; '.' remains the explicit cwd opt-in."""
        import pytest
        p = self._parser()
        for cmd in ("audit", "fingerprint", "doctor"):
            with pytest.raises(SystemExit):
                p.parse_args([cmd, ""])
        # '.' and a real path still parse
        assert p.parse_args(["audit", "."]).repo == "."
        assert p.parse_args(["audit", "/tmp"]).repo == "/tmp"


# ── DR7 round-7 (TP-196): CLI edge-case guards ───────────────────────────────


class TestDoctorMissingPath:
    """`espalier doctor <typo>` on a nonexistent path used to fall through to
    the 'uninitialized' branch — advising `init` on a path that does not exist
    and exiting 0. A missing path is not a fresh repo; it must error + exit
    non-zero (DR7 round-7 polish, mirrors the W10-1 release-pack guard)."""

    def test_nonexistent_path_errors_nonzero(self, tmp_path, capsys):
        from espalier.cli import cmd_doctor
        ghost = tmp_path / "does-not-exist"
        ret = cmd_doctor(_ns(repo=str(ghost), mode="auto",
                             skip_self_host=True, check_doc_drift=False))
        # 1 (fail), not 2 — docs/CLI_EXIT_CODES.md pins doctor to {0,1}.
        assert ret == 1
        err = capsys.readouterr().err
        assert "does not exist" in err
        assert "init" not in err  # must NOT advise init on a missing path


class TestReleasePackEmptyDir:
    """`espalier release-pack <empty-existing-dir>` wrote a 22-byte zip with
    files_written=0 and exit 0 — the same 'successful-looking no-op release'
    the W10-1 guard prevents for a MISSING path, surviving via the is_dir()
    sibling. Fail loudly on zero files (DR7 round-7 polish)."""

    def test_empty_dir_refuses_nonzero(self, tmp_path, capsys, as_self_host_tree):
        from espalier.cli import cmd_release_pack
        ret = cmd_release_pack(_ns(repo=str(tmp_path),
                                   output="dist/espalier-harness.zip"))
        assert ret == 2
        assert "no files packaged" in capsys.readouterr().err

    def test_empty_dir_does_not_clobber_existing_archive(self, tmp_path, as_self_host_tree):
        """The 'refusing to write' guard must be TRUE: a zero-files run must
        NOT write an empty zip — and must NOT clobber a pre-existing valid
        archive at the output path (the R10-B3 no-clobber invariant). Pre-fix,
        create_release_zip os.replace'd an empty 22-byte zip BEFORE the check,
        destroying any prior artifact while the message claimed otherwise."""
        from espalier.cli import cmd_release_pack
        out = tmp_path / "dist" / "espalier-harness.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PRE-EXISTING-VALID-ARTIFACT")
        before = out.read_bytes()
        ret = cmd_release_pack(_ns(repo=str(tmp_path), output="dist/espalier-harness.zip"))
        assert ret == 2
        assert out.read_bytes() == before, "zero-files run clobbered the prior archive"


class TestCmdScopeCheck:
    """TP-38: scope-check CLI handler. Tests cover the three exit paths.

    Exercises ``espalier/cli.py::cmd_scope_check`` directly rather than via
    subprocess so failure modes are visible at unit-test resolution.
    """

    def _scope_args(self, *, repo, pack_path, matrix="docs/SURFACE_SUPPORT_MATRIX.md",
                    no_ripgrep=True, max_refs_per_file=3, accept_scope_gap=None):
        return _ns(
            repo=str(repo),
            pack_path=str(pack_path),
            matrix=matrix,
            no_ripgrep=no_ripgrep,
            max_refs_per_file=max_refs_per_file,
            accept_scope_gap=accept_scope_gap,
        )

    def test_missing_pack_returns_one(self, tmp_path, capsys):
        from espalier.cli import cmd_scope_check
        args = self._scope_args(repo=tmp_path, pack_path=tmp_path / "nope.md")
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "pack file not found" in out

    def test_pack_without_affected_symbols_returns_one(self, tmp_path, capsys):
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-99-empty.md"
        pack.write_text(
            "# TP-99 — empty\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=tmp_path, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "no 'Affected symbols' section" in out

    def test_declared_but_empty_affected_symbols_says_so(self, tmp_path, capsys):
        """A pack that HAS the heading but parses to zero entries got told the
        heading was absent, sending an author who followed the format to
        PACK_AUTHORING.md for a format they already followed. It burned a real
        pack-author cycle.

        A declared section that parsed to zero is a blast radius that was never
        walked, not a pack with nothing to walk: the message carries the
        ``DECLARED_BUT_EMPTY`` marker on one line, and no longer borrows the
        no-section phrase that made ``scripts/run_pack_chain.sh`` read rc==1 as
        a clean skip (DEF-781).
        """
        from espalier.cli import cmd_scope_check
        pack = tmp_path.parent / "TP-98-declared-but-empty.md"
        pack.write_text(
            "# TP-98 — declared but empty\n\n## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n## Affected symbols\n\n"
            "To be determined during execution.\n\n## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=tmp_path, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "parsed to zero" in out, out
        self._declared_but_empty_marker_on_one_line(out)
        assert "no 'Affected symbols' section" not in out, (
            "a declared section must not borrow the phrase the driver reads as "
            "a clean skip"
        )

    @staticmethod
    def _driver_phrases_each_on_one_line(out: str) -> None:
        """``scripts/run_pack_chain.sh`` greps these LINE BY LINE to read rc==1
        as a clean skip. Only a pack with genuinely nothing to walk keeps them
        -- no section at all, or a section whose every bullet declares nothing
        on purpose. A DECLARED section that parsed to zero carries the
        ``DECLARED_BUT_EMPTY`` marker instead (DEF-781)."""
        lines = out.splitlines()
        assert any("cannot walk references" in ln for ln in lines), out
        assert any("no 'Affected symbols' section" in ln for ln in lines), out
        assert "DECLARED_BUT_EMPTY" not in out, (
            "a pack with nothing to walk must not read as an errored probe"
        )

    @staticmethod
    def _declared_but_empty_marker_on_one_line(out: str) -> None:
        """The marker ``scripts/run_pack_chain.sh`` checks BEFORE the skip
        phrases, contiguous on one line, so a declared-but-empty section is an
        errored probe and not a clean skip; the borrowed parenthetical that
        used to carry the skip phrase is gone."""
        lines = out.splitlines()
        assert sum("DECLARED_BUT_EMPTY" in ln for ln in lines) == 1, out
        assert any(ln.startswith("scope-check: DECLARED_BUT_EMPTY --") for ln in lines), out
        assert "Reported the same way as" not in out, out

    def test_bullets_under_an_unrouted_subheading_are_named_not_called_malformed(
        self, tmp_path, capsys
    ):
        """DEF-430: a correctly written bullet under a sub-heading the
        pre-flight does not route (``### Fixed``) parsed to zero and was told
        its bullets were malformed -- the format it had followed. The message
        now names the sub-heading and the four the walk reads."""
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-96-fixed.md"
        pack.write_text(
            "# TP-96\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n### Fixed\n- `src/a.py::f` — y\n\n"
            "## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        rc = cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=pack))
        out = capsys.readouterr().out
        assert rc == 1
        assert "'### Fixed'" in out, out
        assert "does not" in out and "`### Added`" in out, out
        assert "until the bullets match" not in out, (
            "the format message is a lie for bullets that follow the format"
        )
        assert any("parsed to zero" in ln for ln in out.splitlines()), out
        self._declared_but_empty_marker_on_one_line(out)

    def test_a_literals_only_pack_that_parses_to_zero_is_not_told_it_declares_symbols(
        self, tmp_path, capsys
    ):
        """DEF-431: one regex over both headings made a literals-only pack read
        as declaring an Affected symbols section, and prescribed the symbols
        format for a literal bullet."""
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-97-literals.md"
        pack.write_text(
            "# TP-97\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "## Affected literals\n\n- the config key, to be named during execution\n\n"
            "## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        rc = cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=pack))
        out = capsys.readouterr().out
        assert rc == 1
        assert "declares an 'Affected symbols' section" not in out, out
        assert "'Affected literals' section" in out, out
        assert "parsed to zero" in out, out
        assert "Affected symbols section: absent" in out, out
        self._declared_but_empty_marker_on_one_line(out)

    def test_a_section_whose_bullets_all_declare_nothing_is_not_called_malformed(
        self, tmp_path, capsys
    ):
        """The fifth cause: `- none. The event is observational` is a correct
        declaration of nothing, and the format message was DEF-430 again."""
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-93-none.md"
        pack.write_text(
            "# TP-93\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n### Changed-semantics\n"
            "- none. The event is observational; nothing reads the probe's output.\n\n"
            "## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        rc = cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=pack))
        out = capsys.readouterr().out
        assert rc == 1
        assert "declares nothing on purpose" in out, out
        assert "until the bullets match" not in out, out
        assert any("parsed to zero" in ln for ln in out.splitlines()), out
        self._driver_phrases_each_on_one_line(out)

    def test_both_sections_declared_and_both_empty_names_both_causes(self, tmp_path, capsys):
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-92-both.md"
        pack.write_text(
            "# TP-92\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n### Fixed\n- `src/a.py::f` — y\n\n"
            "## Affected literals\n\n- the key, to be named later\n\n"
            "## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        rc = cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=pack))
        out = capsys.readouterr().out
        assert rc == 1
        assert "'### Fixed'" in out, out
        assert "'Affected literals' section parsed to zero entries as well" in out, out
        self._declared_but_empty_marker_on_one_line(out)

    def test_a_literals_section_that_parsed_to_zero_beside_a_declare_nothing_symbols_section_is_declared_but_empty(
        self, tmp_path, capsys
    ):
        """DEF-781's own named shape, a malformed literals section, must carry
        the marker even when the symbols section declares nothing on purpose:
        the marker is computed from the two facts, not typed per branch (the
        failure-mode review found the first cut printing it in three branches
        and this shape falling through to the clean-skip one)."""
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-90-none-plus-literals.md"
        pack.write_text(
            "# TP-90\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n### Changed-semantics\n"
            "- none. The event is observational; nothing reads the probe's output.\n\n"
            "## Affected literals\n\n- the key, to be named later\n\n"
            "## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        rc = cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=pack))
        out = capsys.readouterr().out
        assert rc == 1
        assert "declares nothing on purpose" in out, out
        assert "'Affected literals' section parsed to zero entries as well" in out, out
        lines = out.splitlines()
        assert sum("DECLARED_BUT_EMPTY" in ln for ln in lines) == 1, out

    def test_a_strike_that_registered_is_said_so(self, tmp_path, capsys):
        from espalier.cli import cmd_scope_check
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
        pack = tmp_path / "TP-91-struck.md"
        pack.write_text(
            "# TP-91\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n### Changed-semantics\n- `src/a.py::f` — y\n"
            "- ~~`src/a.py::gone`~~ *(withdrawn)*\n\n## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=pack))
        out = capsys.readouterr().out
        assert "Affected symbols section declares 1 symbols." in out, out
        assert "~ withdrawn by strike: src/a.py::gone" in out, out

    def test_the_summary_names_the_heading_it_matched(self, tmp_path, capsys):
        """The numbered spelling parses, so the summary says which line it
        read; the plain heading keeps the historical sentence byte for byte."""
        from espalier.cli import cmd_scope_check
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
        body = (
            "## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nnothing\n\n"
            "{heading}\n\n### Changed-semantics\n- `src/a.py::f` — y\n\n"
            "## Pass criteria\n\n1. x\n"
        )
        numbered = tmp_path / "TP-95-numbered.md"
        numbered.write_text("# TP-95\n\n" + body.format(heading="## 5. Affected symbols"), encoding="utf-8")
        cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=numbered))
        out = capsys.readouterr().out
        assert "Affected symbols section (matched '## 5. Affected symbols') declares 1 symbols." in out, out

        plain = tmp_path / "TP-94-plain.md"
        plain.write_text("# TP-94\n\n" + body.format(heading="## Affected symbols"), encoding="utf-8")
        cmd_scope_check(self._scope_args(repo=tmp_path, pack_path=plain))
        out = capsys.readouterr().out
        assert "Affected symbols section declares 1 symbols." in out, out

    def test_no_scope_gap_returns_zero(self, tmp_path, capsys):
        """All affected-symbol references land inside Scope (in).

        Pack file is placed outside the synthetic repo so its own backticked
        mentions of the symbol don't count as out-of-scope references.
        """
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text(
            "TARGET_SYMBOL_XYZ = 'x'\n", encoding="utf-8",
        )
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-clean.md"
        pack.write_text(
            "# TP-99 — clean\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `TARGET_SYMBOL_XYZ` — sole reference is in src/a.py\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 0, f"expected clean pack to exit 0, got {rc}; output:\n{out}"
        assert "No scope gaps detected" in out

    def test_scope_gap_returns_two(self, tmp_path, capsys):
        """A reference outside Scope (in) triggers exit 2 unless accepted."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text(
            "TARGET_SYMBOL_ABC = 'x'\n", encoding="utf-8",
        )
        (repo / "other").mkdir()
        (repo / "other" / "consumer.py").write_text(
            "from src.a import TARGET_SYMBOL_ABC\n", encoding="utf-8",
        )
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-gap.md"
        pack.write_text(
            "# TP-99 — gap\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `TARGET_SYMBOL_ABC` — see consumer\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 2
        assert "Files NOT in pack scope" in out
        assert "other/consumer.py" in out

    def test_literal_keyed_pack_warns_even_when_no_symbol_gap(self, tmp_path, capsys):
        """TP-318 1-A: a rename/config pack has a thin symbol surface, so a
        clean symbol scan is NOT coverage — the blast radius is a raw string
        the walk can't see. scope-check must WARN (never let '0 gaps' read as
        reassurance) when a pack looks literal/path-keyed (a ``git mv`` line or
        a renamed-file token) but declares no ``## Affected literals``.
        Earn-the-red: pre-1-A there is no warning on the clean-scan path."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("LONELY_SYMBOL_QQ = 1\n", encoding="utf-8")
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-rename.md"
        pack.write_text(
            "# TP-99 — rename\n\n"
            "This pack does `git mv old.md new.md` across the tree.\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `LONELY_SYMBOL_QQ` — sole ref in src/a.py\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 0, out                     # symbol scan is clean
        assert "No scope gaps detected" in out
        assert "[warn]" in out                  # ...warning fires anyway (RED pre-1-A)
        assert "literal/path-keyed" in out

    def test_renamed_file_token_triggers_the_literal_warning(self, tmp_path, capsys):
        """1-A's second trigger: a ``### Renamed symbols`` bullet whose token
        looks like a file (contains ``.``/``/``) is a literal-keyed rename even
        without a ``git mv`` line — ``_renamed_names_a_file`` catches it."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("KEEP_SYMBOL_QQ = 1\n", encoding="utf-8")
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-renamed.md"
        pack.write_text(
            "# TP-99 — renamed\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Renamed symbols\n"
            "- `old_config.yml` — renamed to `new_config.yml`\n\n"
            "### Changed semantics\n"
            "- `KEEP_SYMBOL_QQ` — sole ref\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert "[warn]" in out, out
        assert "literal/path-keyed" in out

    def test_normal_pack_does_not_warn(self, tmp_path, capsys):
        """The 1-A warning must NOT fire on an ordinary (non-rename) pack — the
        heuristic is specific to ``git mv`` / renamed-file tokens, so a plain
        change never trips the false-positive."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("ORDINARY_SYMBOL_QQ = 1\n", encoding="utf-8")
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-normal.md"
        pack.write_text(
            "# TP-99 — normal\n\n"
            "An ordinary change, no rename.\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `ORDINARY_SYMBOL_QQ` — sole ref in src/a.py\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "[warn]" not in out

    def test_literals_only_pack_reaches_the_literal_arm(self, tmp_path, capsys):
        """TP-318: a pure-rename pack has a thin/zero SYMBOL surface but a real
        LITERAL surface — exactly what the literal arm exists for. It must NOT
        early-exit 1 ('no Affected symbols') and skip the literal walk; a
        declared literal with an out-of-scope ref still forces exit 2.
        Earn-the-red: pre-fix a symbols-less pack returns 1 before the arm runs."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("keep = 1\n", encoding="utf-8")
        (repo / "out").mkdir()
        (repo / "out" / "leak.md").write_text(
            "RENAME_ME_TOKEN appears here\n", encoding="utf-8",
        )
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-litonly.md"
        pack.write_text(
            "# TP-99 — literals only\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected literals\n\n"
            "- `RENAME_ME_TOKEN` — a pure rename, no symbol changes\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 2, out                                    # RED pre-fix (was 1)
        assert "Literal refs NOT classified (gap):" in out
        assert "out/leak.md" in out

    def test_pack_with_neither_symbols_nor_literals_still_returns_one(self, tmp_path, capsys):
        """The exit-1 guard remains for a pack that declares NEITHER section —
        scope-check has nothing to walk. The message keeps the phrases the
        existing suite and the chain driver's rc==1 grep both rely on
        (``no 'Affected symbols' section`` / ``cannot walk references``)."""
        from espalier.cli import cmd_scope_check
        pack = tmp_path / "TP-99-empty2.md"
        pack.write_text(
            "# TP-99 — empty\n\n## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=tmp_path, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "no 'Affected symbols' section" in out
        assert "cannot walk references" in out
        assert "DECLARED_BUT_EMPTY" not in out, out

    def test_declared_literal_with_out_of_scope_ref_forces_exit_two(self, tmp_path, capsys):
        """TP-318 2-A: a declared ``## Affected literals`` token whose refs fall
        outside Scope (in) is an ambiguous literal hit — a scope gap that forces
        exit 2, the same semantics as an out-of-scope symbol ref. Earn-the-red:
        pre-2-A the literal arm doesn't exist, so the literal is ignored and the
        pack exits 0."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("SYM_IN_SCOPE = 1\n", encoding="utf-8")
        (repo / "elsewhere").mkdir()
        (repo / "elsewhere" / "notes.md").write_text(
            "see LEGACY_TOKEN_X for details\n", encoding="utf-8",
        )
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-literal.md"
        pack.write_text(
            "# TP-99 — literal\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `SYM_IN_SCOPE` — sole ref in src/a.py\n\n"
            "## Affected literals\n\n"
            "- `LEGACY_TOKEN_X` — a renamed token; every ref migrates\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 2, out                                     # RED pre-2-A (was 0)
        assert "Literal reference scan:" in out
        assert "Literal refs NOT classified (gap):" in out
        assert "elsewhere/notes.md" in out

    def test_literal_exclude_glob_drops_homonym_hits_but_flags_the_rest(self, tmp_path, capsys):
        """TP-318 3-A: a literal's ``EXCLUDE:`` glob marks files where the token
        legitimately appears unchanged (a homonym twin). Excluded hits drop out
        of the gap; an unaccounted hit stays ``ambiguous`` and forces exit 2 —
        the load-bearing safety for a rename with a homonym twin. Earn-the-red:
        pre-3-A there is no literal arm at all, so the pack exits 0."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("HOMONYM_TOKEN_Z = 1\n", encoding="utf-8")
        (repo / "twin").mkdir()
        (repo / "twin" / "legit.md").write_text(
            "HOMONYM_TOKEN_Z lives here unchanged\n", encoding="utf-8",
        )
        (repo / "stray").mkdir()
        (repo / "stray" / "oops.md").write_text(
            "HOMONYM_TOKEN_Z leaked here\n", encoding="utf-8",
        )
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-exclude.md"
        pack.write_text(
            "# TP-99 — exclude\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `SOME_OTHER_SYM` — placeholder, no refs\n\n"
            "## Affected literals\n\n"
            "- `HOMONYM_TOKEN_Z` — renamed everywhere except its homonym twin\n"
            "  EXCLUDE: twin/legit.md\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 2, out
        # twin/legit.md is EXCLUDED -> not a gap; stray/oops.md is ambiguous -> gap.
        assert "stray/oops.md" in out
        assert "Literal refs NOT classified (gap):" in out
        gap_block = out.split("Literal refs NOT classified (gap):", 1)[1]
        assert "twin/legit.md" not in gap_block
        # src/a.py in-scope target, twin excluded, stray ambiguous.
        assert "1 target / 1 excluded / 1 ambiguous" in out

    def test_excluded_files_are_listed_so_over_broad_glob_is_visible(self, tmp_path, capsys):
        """TP-318 (step-6 fix): an EXCLUDE glob's swallowed files are printed
        (capped) so an over-broad glob (fnmatch `*` crosses `/`, so `docs/*.md`
        excludes every `.md` under docs) is observable, not a silent `0 ambiguous`
        that re-creates the false reassurance the literal arm exists to kill."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("BROAD_TOKEN_X = 1\n", encoding="utf-8")
        (repo / "docs").mkdir()
        (repo / "docs" / "one.md").write_text("BROAD_TOKEN_X mention\n", encoding="utf-8")
        (repo / "docs" / "two.md").write_text("BROAD_TOKEN_X mention\n", encoding="utf-8")
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-broad.md"
        pack.write_text(
            "# TP-99 — broad\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nx\n\n"
            "## Affected literals\n\n"
            "- `BROAD_TOKEN_X` — over-broad exclude\n"
            "  EXCLUDE: docs/*.md\n",
            encoding="utf-8",
        )
        args = self._scope_args(repo=repo, pack_path=pack, max_refs_per_file=5)
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        # docs/*.md swallows both -> 2 excluded, 0 ambiguous, no gap (rc 0).
        assert rc == 0, out
        assert "2 excluded" in out
        assert "excluded:" in out
        assert "docs/one.md" in out and "docs/two.md" in out

    def test_accept_scope_gap_returns_zero(self, tmp_path, capsys):
        """--accept-scope-gap acknowledges the gap and exits 0."""
        from espalier.cli import cmd_scope_check
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text(
            "TARGET_SYMBOL_DEF = 'x'\n", encoding="utf-8",
        )
        (repo / "other").mkdir()
        (repo / "other" / "consumer.py").write_text(
            "from src.a import TARGET_SYMBOL_DEF\n", encoding="utf-8",
        )
        pack_dir = tmp_path / "packs"
        pack_dir.mkdir()
        pack = pack_dir / "TP-99-accept.md"
        pack.write_text(
            "# TP-99 — accept\n\n"
            "## Scope (in)\n\n- `src/a.py`\n\n"
            "## Scope (out)\n\nnothing\n\n"
            "## Affected symbols\n\n"
            "### Changed semantics\n"
            "- `TARGET_SYMBOL_DEF` — see test for context\n",
            encoding="utf-8",
        )
        args = self._scope_args(
            repo=repo, pack_path=pack,
            accept_scope_gap="test-driven discovery",
        )
        rc = cmd_scope_check(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Scope gap acknowledged" in out
        assert "test-driven discovery" in out


def _hook_timeout_in_settings(settings: dict, basename: str):
    """Return the timeout of the hook whose script arg ends with ``basename``."""
    for event_cfg in settings["hooks"].values():
        for entry in event_cfg:
            for hook in entry.get("hooks", []):
                arg = (hook.get("args") or [""])[0]
                if arg.endswith("/" + basename):
                    return hook.get("timeout")
    return None


class TestSettingsTimeoutDerivedFromCHW:
    """TP-151 G-2: ``_build_settings_json`` derives every hook timeout from
    ``CANONICAL_HOOK_WIRING`` (the SoT), not inline literals (only stop_gate
    was SoT-derived before). Mutating a non-Stop CHW timeout must flow through
    to the emitted settings.json."""

    def test_non_stop_timeout_tracks_canonical_hook_wiring(self, monkeypatch):
        import espalier.harness_config as hc
        from espalier.cli import _build_settings_json

        original = hc.CANONICAL_HOOK_WIRING["reflect_trigger.py"]
        monkeypatch.setitem(
            hc.CANONICAL_HOOK_WIRING,
            "reflect_trigger.py",
            {**original, "timeout": 999},
        )
        settings = _build_settings_json()
        assert _hook_timeout_in_settings(settings, "reflect_trigger.py") == 999, (
            "reflect_trigger timeout did not track CANONICAL_HOOK_WIRING — "
            "_build_settings_json still uses an inline literal (TP-151 G-2)."
        )


class TestRepoArgConvergence:
    """TP-189-C CLI-1: the --repo/--root FLAG commands converge onto the canonical
    optional positional `repo` (default "."), with --repo kept as a hidden
    back-compat alias. memory-prune keeps --root (argparse rejects dest= on a
    positional). Existing flag invocations must keep parsing.

    Scope note: TP-189-E lands the required->optional WIDENING of the bare-positional
    commands (the 16 whose only positional is `repo`). `blueprint` stays required
    because a trailing required `action` makes a bare `blueprint record` ambiguous;
    `memory prune` keeps --root (argparse rejects dest= on a positional)."""

    def _parser(self):
        from espalier.cli import build_parser
        return build_parser()

    @pytest.mark.parametrize("cmd", ["scope-check", "verify-landing"])
    def test_pack_command_repo_positional_and_alias(self, cmd):
        p = self._parser()
        assert p.parse_args([cmd, "PACK.md"]).repo == "."                 # default
        assert p.parse_args([cmd, "PACK.md", "R"]).repo == "R"            # canonical positional
        assert p.parse_args([cmd, "PACK.md", "--repo", "X"]).repo == "X"  # back-compat alias

    def test_scaffolding_bench_repo_positional_and_alias(self):
        p = self._parser()
        assert p.parse_args(["scaffolding-bench"]).repo == "."
        assert p.parse_args(["scaffolding-bench", "R"]).repo == "R"
        assert p.parse_args(["scaffolding-bench", "--repo", "X"]).repo == "X"

    def test_memory_prune_keeps_root_flag(self):
        assert self._parser().parse_args(["memory", "prune", "--root", "X"]).root == "X"

    @pytest.mark.parametrize("cmd", [
        "init", "merge-settings", "fingerprint", "audit", "recover", "reflect",
        "diff", "surface-handoff", "self-host", "worktree-plan", "scan", "doctor",
        "clean-generated", "release-pack", "pre-release", "reflect-deep",
    ])
    def test_widened_repo_command_bare_defaults_to_dot(self, cmd):
        """TP-189-E CLI-1: the 16 bare-required `repo` positionals widened to optional
        (default '.'). Bare now parses to repo='.' (RED pre-widening: required
        positional -> SystemExit); an explicit repo is still honored."""
        p = self._parser()
        assert p.parse_args([cmd]).repo == "."
        assert p.parse_args([cmd, "R"]).repo == "R"

    def test_blueprint_repo_stays_required(self):
        """The documented widening exception: `blueprint` keeps a required `repo`
        because a trailing required `action` would make a bare `blueprint record`
        ambiguous (is `record` the repo or the action?)."""
        # Introspect the blueprint subparser directly. `parse_args(["blueprint"])`
        # raises on the missing required `action` whether or not `repo` is
        # required, so it cannot isolate the `repo`-required property this test
        # names — widening `repo` to optional would leave that vector green.
        subparsers = next(
            a for a in self._parser()._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        repo_action = next(
            a for a in subparsers.choices["blueprint"]._actions if a.dest == "repo"
        )
        assert repo_action.required and repo_action.default is None, (
            "blueprint's `repo` positional was widened to optional"
        )
        # The canonical (repo, action) vector still parses.
        ns = self._parser().parse_args(["blueprint", ".", "load"])
        assert ns.repo == "." and ns.action == "load"


class TestCleanWarningFormat:
    """TP-224 (TQ-newtest-3): ``_install_clean_warning_format`` (landed
    10e8f79) replaces ``warnings.showwarning`` so a benign degrade does not
    leak the absolute site-packages path + raw source line on an adopter's
    first run. No test pinned this; a revert to Python's default re-leaks the
    path with the suite green."""

    def test_warning_redacts_absolute_path(self):
        import io
        import warnings

        from espalier import cli

        leaky_filename = "/Users/someone/site-packages/espalier/config.py"
        leaky_source_line = 'raise ValueError("/abs/internal/path/leak")'

        saved = warnings.showwarning
        try:
            cli._install_clean_warning_format()
            buf = io.StringIO()
            warnings.showwarning(
                "malformed espalier.toml; falling back to defaults",
                UserWarning,
                leaky_filename,
                412,
                file=buf,
                line=leaky_source_line,
            )
            rendered = buf.getvalue()
        finally:
            warnings.showwarning = saved

        assert rendered == "Warning: malformed espalier.toml; falling back to defaults\n"
        assert leaky_filename not in rendered
        assert "site-packages" not in rendered
        assert "412" not in rendered
        assert leaky_source_line not in rendered


class TestWriteSeedLabelsAndDryRun:
    """DEF-774, the seed half. The stderr line named the file by basename,
    so two seeds printed as ``README.md``; and ``upgrade``'s preview was a
    static sentence because nothing could ask the writer what it would do.
    The caller now hands the writer its root-relative label, and a dry run
    answers through the same decision without writing or printing."""

    def test_stderr_names_the_label_the_caller_gives_not_the_basename(self, tmp_path, capsys):
        from espalier.cli import _write_seed
        dest = tmp_path / "docs" / "sharp-edges" / "README.md"
        assert _write_seed(dest, "OLD\n", label=dest.name) is True
        capsys.readouterr()
        assert _write_seed(dest, "NEW\n", label="docs/sharp-edges/README.md") is True
        assert _write_seed(dest, "NEW\n", label="docs/sharp-edges/README.md") is False
        err = capsys.readouterr().err
        assert "refresh (seed drift): docs/sharp-edges/README.md" in err, err
        assert "skip (exists): docs/sharp-edges/README.md" in err, err
        assert "): README.md" not in err, err

    def test_a_dry_run_answers_without_writing_or_printing(self, tmp_path, capsys):
        from espalier.cli import _write_seed
        dest = tmp_path / "out" / "seed.md"
        assert _write_seed(dest, "OLD\n", dry_run=True, label=dest.name) is True        # would create
        assert not dest.exists()
        assert _write_seed(dest, "OLD\n", label=dest.name) is True
        capsys.readouterr()
        assert _write_seed(dest, "NEW\n", dry_run=True, label=dest.name) is True        # would refresh
        assert dest.read_text(encoding="utf-8").endswith("OLD\n")
        assert _write_seed(dest, "OLD\n", dry_run=True, label=dest.name) is False       # current: would skip
        dest.write_text(dest.read_text(encoding="utf-8") + "edit\n", encoding="utf-8")
        assert _write_seed(dest, "NEW\n", dry_run=True, label=dest.name) is False       # edited: would keep
        assert capsys.readouterr().err == ""

    def test_deploy_seed_docs_reports_created_and_refreshed_by_path(self, tmp_path, capsys):
        """The outcome the summary and the upgrade preview print: created and
        refreshed, by root-relative path, from one decision on both arms."""
        from espalier.cli import _deploy_seed_docs
        from espalier.managed_inventory import get_seed_docs, seed_stamp_line
        first = _deploy_seed_docs(tmp_path)
        assert sorted(first["created"]) == sorted(get_seed_docs())
        assert first["refreshed"] == []
        # Age one untouched copy: a stamp over an older body, so the packaged
        # rendering differs while the on-disk bytes still match their stamp.
        rel = next(iter(get_seed_docs()))
        (tmp_path / rel).write_text(seed_stamp_line("older\n") + "older\n", encoding="utf-8")
        preview = _deploy_seed_docs(tmp_path, dry_run=True)
        assert preview == {"created": [], "refreshed": [rel]}, preview
        assert (tmp_path / rel).read_text(encoding="utf-8").endswith("older\n"), "a dry run wrote"
        capsys.readouterr()
        second = _deploy_seed_docs(tmp_path)
        assert second == preview
        assert f"refresh (seed drift): {rel}" in capsys.readouterr().err
        assert not (tmp_path / rel).read_text(encoding="utf-8").endswith("older\n")
