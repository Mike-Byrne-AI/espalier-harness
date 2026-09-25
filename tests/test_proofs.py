"""Tests for ``espalier.proofs.run_cc_surface_gate`` and its
helpers (``_is_managed``, ``_mentions_token``, ``_manifest_items``,
``_safe_text``) — the CC-surface verification step every release
candidate runs.

Pins the gate's blocking detectors (``PLACEHOLDERS``,
``SUSPICIOUS_CONTENT``, ``MANAGED_MARKER``-correctness) and the
minimum-valid scaffolding that makes the gate pass. Without this
contract a release that contains placeholder strings or unmarked
managed files would ship silently — the gate is the last automated
checkpoint before tag, and any regression in its detectors removes
that safety net.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from espalier.managed_markers import MANAGED_MARKER
from espalier.proofs import (
    _is_managed,
    _manifest_items,
    _safe_text,
    run_cc_surface_gate,
)


def _write_managed(path: Path, content: str) -> None:
    """Write a file with the espalier:managed marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + MANAGED_MARKER + "\n" + content, encoding="utf-8")


def _scaffold_gate_pass(tmp_path: Path) -> None:
    """Create the minimal harness surface that makes the gate pass."""
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({}), encoding="utf-8"
    )
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "repo_fingerprint.json").write_text("{}", encoding="utf-8")
    (reports / "harness_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cc").mkdir(exist_ok=True)
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")


# ── _safe_text ───────────────────────────────────────────────────────────────


class TestSafeText:
    def test_reads_utf8_file(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("hello world\n", encoding="utf-8")
        assert _safe_text(f) == "hello world\n"

    def test_handles_non_utf8_bytes(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_bytes(b"\xff\xfe bad bytes")
        result = _safe_text(f)
        assert isinstance(result, str)


# ── _is_managed ──────────────────────────────────────────────────────────────


class TestIsManaged:
    def test_returns_false_for_nonexistent_file(self, tmp_path):
        result = _is_managed(tmp_path / "ghost.py")
        assert result is False

    def test_returns_false_for_directory(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        assert _is_managed(d) is False

    def test_returns_true_for_file_with_marker(self, tmp_path):
        f = tmp_path / "managed.py"
        f.write_text("# " + MANAGED_MARKER + "\nx = 1\n", encoding="utf-8")
        assert _is_managed(f) is True

    def test_returns_false_for_file_without_marker(self, tmp_path):
        f = tmp_path / "plain.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert _is_managed(f) is False

    def test_marker_after_yaml_frontmatter_is_detected(self, tmp_path):
        # TP-03: agents/skills carry the marker AFTER YAML frontmatter so
        # frontmatter validity is preserved. _is_managed must still find it.
        f = tmp_path / "agent.md"
        frontmatter = (
            "---\nname: foo\ndescription: bar\nmodel: opus\n---\n"
        )
        f.write_text(
            f"{frontmatter}<!-- {MANAGED_MARKER} -->\n# Body\n",
            encoding="utf-8",
        )
        assert _is_managed(f) is True

    def test_marker_only_in_body_past_scan_window_is_not_detected(self, tmp_path):
        # The marker contract is "near the top". Marker buried past the
        # scan window is treated as a body mention, not an ownership signal.
        f = tmp_path / "body_marker.py"
        padding = "x = 1\n" * 200  # well past MARKER_SCAN_BYTES
        f.write_text(f"{padding}# {MANAGED_MARKER}\n", encoding="utf-8")
        assert _is_managed(f) is False


# ── _manifest_items ──────────────────────────────────────────────────────────


class TestManifestItems:
    def test_returns_empty_set_when_no_manifest(self, tmp_path):
        result = _manifest_items(tmp_path)
        assert result == set()

    def test_returns_items_from_manifest(self, tmp_path):
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/LIVE_SURFACE.md\ncc/COMMANDS.md\n", encoding="utf-8"
        )
        result = _manifest_items(tmp_path)
        assert "cc/LIVE_SURFACE.md" in result
        assert "cc/COMMANDS.md" in result

    def test_ignores_comment_lines(self, tmp_path):
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "# comment\ncc/LIVE_SURFACE.md\n", encoding="utf-8"
        )
        result = _manifest_items(tmp_path)
        assert "# comment" not in result
        assert "cc/LIVE_SURFACE.md" in result

    def test_ignores_blank_lines(self, tmp_path):
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "\ncc/LIVE_SURFACE.md\n\n", encoding="utf-8"
        )
        result = _manifest_items(tmp_path)
        assert "" not in result


# ── run_cc_surface_gate ──────────────────────────────────────────────────────


class TestRunCcSurfaceGateRequiredFiles:
    def test_missing_required_files_cause_error_findings(self, tmp_path):
        result = run_cc_surface_gate(tmp_path)
        errors = [f for f in result["findings"] if f["level"] == "error"]
        assert len(errors) > 0

    def test_status_fail_when_required_files_missing(self, tmp_path):
        result = run_cc_surface_gate(tmp_path)
        assert result["status"] == "fail"

    def test_status_pass_when_required_files_present(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        result = run_cc_surface_gate(tmp_path)
        assert result["status"] == "pass"

    def test_result_contains_repo_key(self, tmp_path):
        result = run_cc_surface_gate(tmp_path)
        assert "repo" in result

    def test_result_contains_summary(self, tmp_path):
        result = run_cc_surface_gate(tmp_path)
        assert "summary" in result
        assert "errors" in result["summary"]
        assert "warnings" in result["summary"]

    def test_result_contains_findings_list(self, tmp_path):
        result = run_cc_surface_gate(tmp_path)
        assert "findings" in result
        assert isinstance(result["findings"], list)

    def test_writes_cc_surface_gate_json(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        run_cc_surface_gate(tmp_path)
        gate_file = tmp_path / "reports" / "cc_surface_gate.json"
        assert gate_file.exists()

    def test_written_gate_file_is_valid_json(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        run_cc_surface_gate(tmp_path)
        data = json.loads(
            (tmp_path / "reports" / "cc_surface_gate.json").read_text(encoding="utf-8")
        )
        assert "status" in data

    def test_run_cc_surface_gate_writes_atomically(self):
        """TP-151 D-3: cc_surface_gate.json is read by the SessionStart hook
        (cmd_start) to seed gate_status. A non-atomic write can be caught
        torn by a concurrent reader, so the write must route through
        atomic_write_text (temp + os.replace), not a bare write_text."""
        import ast as _ast
        import inspect

        from espalier import proofs

        tree = _ast.parse(inspect.getsource(proofs.run_cc_surface_gate))
        called = {
            (
                n.func.attr if isinstance(n.func, _ast.Attribute)
                else n.func.id if isinstance(n.func, _ast.Name)
                else None
            )
            for n in _ast.walk(tree)
            if isinstance(n, _ast.Call)
        }
        assert "atomic_write_text" in called, (
            "run_cc_surface_gate must write via atomic_write_text (torn-read "
            "defense for the SessionStart reader)."
        )
        assert "write_text" not in called, (
            "run_cc_surface_gate still uses a non-atomic write_text."
        )

    def test_error_count_matches_findings(self, tmp_path):
        result = run_cc_surface_gate(tmp_path)
        error_count = sum(1 for f in result["findings"] if f["level"] == "error")
        assert result["summary"]["errors"] == error_count

    def test_warning_count_matches_findings(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        result = run_cc_surface_gate(tmp_path)
        warning_count = sum(1 for f in result["findings"] if f["level"] == "warning")
        assert result["summary"]["warnings"] == warning_count


class TestRunCcSurfaceGatePlaceholders:
    def test_placeholder_in_managed_file_is_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        tools_cc = tmp_path / "tools" / "cc"
        tools_cc.mkdir(parents=True)
        managed_file = tools_cc / "my_tool.py"
        _write_managed(managed_file, "# Uses <fill> framework\n")
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["level"] == "warning" and f["check"] == "placeholder"]
        assert len(warnings) > 0

    def test_no_placeholder_means_no_placeholder_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "placeholder"]
        assert len(warnings) == 0

    def test_suspicious_text_causes_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        tools_cc = tmp_path / "tools" / "cc"
        tools_cc.mkdir(parents=True)
        managed_file = tools_cc / "my_tool.py"
        _write_managed(managed_file, "SUMMARY OF LESS COMMANDS\n")
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "malformed_text"]
        assert len(warnings) > 0

    def test_post_write_check_self_reference_excluded(self, tmp_path):
        """R10 fix: post_write_check.py legitimately defines PLACEHOLDERS as
        a constant — scanning it against its own list produced a spurious
        warning on every fresh init. The exclusion in
        ``_PLACEHOLDER_SCAN_EXCLUSIONS`` must keep this specific path off
        the scan list. R11 W: add a direct test so removing the exclusion
        regresses CI immediately.
        """
        _scaffold_gate_pass(tmp_path)
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        # Reproduce a representative slice of post_write_check.py that
        # contains the literal PLACEHOLDERS tokens — the file IS the
        # canonical definition.
        target = hooks_dir / "post_write_check.py"
        _write_managed(
            target,
            'PLACEHOLDERS = ["<repo>", "<fill>", "INSERT HERE", "TEMPLATE_ONLY"]\n',
        )
        result = run_cc_surface_gate(tmp_path)
        placeholder_findings = [
            f for f in result["findings"]
            if f["check"] == "placeholder"
            and "post_write_check.py" in f["detail"]
        ]
        assert placeholder_findings == [], (
            f"post_write_check.py must be excluded from placeholder scan; "
            f"got: {placeholder_findings}"
        )

    def test_hook_utils_self_reference_excluded(self, tmp_path):
        """B-1 #3: _hook_utils.py carries a literal ``<repo>`` token in a
        path-normalization comment. Once managed-marked (every fusion, where the
        scan runs managed_only), it tripped a spurious placeholder warning on the
        adopter's first audit/smoke. It is a sister site of post_write_check.py
        and must be excluded; removing the exclusion regresses CI immediately.
        """
        _scaffold_gate_pass(tmp_path)
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        target = hooks_dir / "_hook_utils.py"
        _write_managed(
            target,
            "# stayed out-of-prefix as a bare ``../<repo>/...`` string).\n",
        )
        result = run_cc_surface_gate(tmp_path)
        placeholder_findings = [
            f for f in result["findings"]
            if f["check"] == "placeholder"
            and "_hook_utils.py" in f["detail"]
        ]
        assert placeholder_findings == [], (
            f"_hook_utils.py must be excluded from placeholder scan; "
            f"got: {placeholder_findings}"
        )

    def test_bash_patterns_self_reference_excluded(self, tmp_path):
        """DEF-689: third site of the post_write_check/_hook_utils shape. The
        docstring cites the literal ``<repo>/build`` path; only the deployed
        copy is managed-marked, so self-host audit stayed green while every
        adopter's first `audit .` warned about it."""
        _scaffold_gate_pass(tmp_path)
        target = tmp_path / "tools" / "cc" / "hooks" / "_bash_patterns.py"
        _write_managed(target, "    # fire on `<repo>/build`, on `/tmp/x`, on\n")
        result = run_cc_surface_gate(tmp_path)
        hits = [
            f for f in result["findings"]
            if f["check"] == "placeholder" and "_bash_patterns.py" in f["detail"]
        ]
        assert hits == [], hits

    def test_deployed_tools_cc_has_no_placeholder_findings(self, tmp_path):
        """The CLASS gate (DEF-689): scan the real deploy source exactly as an
        adopter receives it -- every ``tools/cc/**/*.py`` from the vendored
        deploy tree, managed-marked the way ``init`` marks it. Three sites of
        this shape were excluded one at a time because nothing scanned the
        DEPLOYED bytes; a fourth site reds here, not on an adopter's first
        audit."""
        from espalier.cli import _deploy_source_path

        _scaffold_gate_pass(tmp_path)
        src_root = _deploy_source_path("tools/cc")
        assert src_root.is_dir(), src_root
        from espalier.proofs import TEXT_SUFFIXES

        copied: list[str] = []
        for src in sorted(src_root.rglob("*")):
            rel = src.relative_to(src_root)
            if not src.is_file() or src.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if "__pycache__" in rel.parts or "selfcheck_tests" in rel.parts:
                continue
            _write_managed(tmp_path / "tools" / "cc" / rel, src.read_text(encoding="utf-8"))
            copied.append(rel.as_posix())
        # A named site, not a count floor: the real tree, and the one file whose
        # `<repo>` token started this class.
        assert "hooks/_bash_patterns.py" in copied, copied
        assert "hooks/write_guard.py" in copied, copied
        result = run_cc_surface_gate(tmp_path)
        hits = [f for f in result["findings"] if f["check"] == "placeholder"]
        assert hits == [], (
            "a deployed tools/cc file carries a PLACEHOLDERS token; either "
            "reword it or add it to _PLACEHOLDER_SCAN_EXCLUSIONS with the "
            f"reason:\n  {hits}"
        )

    def test_arbitrary_tools_cc_py_placeholder_is_flagged(self, tmp_path):
        """Companion to the exclusion test: arbitrary ``.py`` templates in
        ``tools/cc/`` (NOT the post_write_check.py file) MUST still trigger
        the placeholder warning. Pre-R11 a too-broad exclusion would have
        silently dropped this signal — pin it here.
        """
        _scaffold_gate_pass(tmp_path)
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        target = hooks_dir / "my_other_hook.py"
        _write_managed(target, "# uses <fill> framework\n")
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "placeholder"]
        assert any("my_other_hook.py" in f["detail"] for f in warnings), (
            f"arbitrary .py template should still trigger placeholder warning; "
            f"got: {warnings}"
        )


class TestRunCcSurfaceGateManifest:
    """Pack 2-F — manifest is strict for promised files, NOT exhaustive."""

    def test_manifest_promised_but_missing_causes_error(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/MISSING.md\n", encoding="utf-8"
        )
        result = run_cc_surface_gate(tmp_path)
        errors = [f for f in result["findings"] if f["check"] == "manifest"]
        assert len(errors) > 0
        assert any("MISSING.md" in f["detail"] for f in errors)

    def test_manifest_promised_and_present_no_error(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "PROMISED.md").write_text("# Promised\n", encoding="utf-8")
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/PROMISED.md\n", encoding="utf-8"
        )
        result = run_cc_surface_gate(tmp_path)
        errors = [f for f in result["findings"] if f["check"] == "manifest"]
        assert len(errors) == 0

    def test_managed_file_not_in_manifest_does_not_fail(self, tmp_path):
        """Contract-owned file absent from PACK_MANIFEST is NOT a manifest error."""
        _scaffold_gate_pass(tmp_path)
        tools_cc = tmp_path / "tools" / "cc"
        tools_cc.mkdir(parents=True)
        unregistered = tools_cc / "unregistered.py"
        _write_managed(unregistered, "x = 1\n")
        # Empty manifest — this file exists but isn't listed
        result = run_cc_surface_gate(tmp_path)
        errors = [f for f in result["findings"] if f["check"] == "manifest"]
        assert len(errors) == 0


class TestRunCcSurfaceGateGeneratedDocs:
    def test_missing_generated_doc_causes_error(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["cc/MISSING.md"]}), encoding="utf-8"
        )
        result = run_cc_surface_gate(tmp_path)
        errors = [f for f in result["findings"] if f["check"] == "generated_docs"]
        assert len(errors) > 0

    def test_present_generated_doc_no_error(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "PROMISED.md").write_text("# Promised\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["cc/PROMISED.md"]}), encoding="utf-8"
        )
        result = run_cc_surface_gate(tmp_path)
        errors = [f for f in result["findings"] if f["check"] == "generated_docs"]
        assert len(errors) == 0


class TestRunCcSurfaceGateLiveSurface:
    def test_live_surface_missing_action_is_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Surface\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"some_action": ["pytest"]}, "agents": []}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "live_surface"]
        assert len(warnings) > 0

    def test_live_surface_containing_action_no_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text(
            "# Surface\nsome_action is here\n", encoding="utf-8"
        )
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"some_action": ["pytest"]}, "agents": []}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "live_surface"]
        assert len(warnings) == 0

    def test_live_surface_missing_agent_is_warning(self, tmp_path):
        """An agent with a body on disk that LIVE_SURFACE.md omits. Since
        2026-09-12 the body is what puts a plan agent in scope (DEF-766): a
        recommendation with none can never be in a doc rendered from the
        tree, so this fixture writes the body the original did not need."""
        _scaffold_gate_pass(tmp_path)
        (tmp_path / ".claude" / "agents").mkdir()
        (tmp_path / ".claude" / "agents" / "missing-agent.md").write_text("# body\n", encoding="utf-8")
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Surface\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({
                "stable_actions": {},
                "agents": [{"name": "missing-agent", "scope": "test"}],
            }),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "live_surface"]
        assert len(warnings) > 0

    def test_a_recommendation_with_no_body_is_not_warned(self, tmp_path):
        """DEF-766 (TP-449 Tier 2, 2026-09-12): driven on an API repo, `audit`
        after `init` warned `LIVE_SURFACE.md missing agent: api-reviewer` --
        a recommendation from harness_config.OPTIONAL_AGENTS no release ships
        a body for. The premise is read from the packaged surface, not typed."""
        from espalier.asset_inventory import packaged_agent_names
        from espalier.harness_config import OPTIONAL_AGENTS
        bodiless = [row[0] for row in OPTIONAL_AGENTS if row[0] not in packaged_agent_names()]
        assert bodiless, "every optional agent now ships a body; retire this case"
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Surface\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {}, "agents": [{"name": bodiless[0], "scope": "api"}]}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "live_surface"]
        assert warnings == [], warnings

    def test_a_packaged_agent_absent_from_disk_is_still_warned(self, tmp_path):
        """The packaged set keeps a deploy the tree is behind on in scope."""
        from espalier.asset_inventory import packaged_agent_names
        name = sorted(packaged_agent_names())[0]
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Surface\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {}, "agents": [{"name": name, "scope": "review"}]}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "live_surface"]
        assert any(name in f["detail"] for f in warnings), warnings

    def test_short_action_not_satisfied_by_longer_token(self, tmp_path):
        """TP-148 148-E: ``review`` must NOT be considered present just
        because ``code-review`` appears in LIVE_SURFACE.md. The bare
        substring check counted the longer token as a mention and silently
        suppressed the missing-action warning; token-boundary matching must
        still flag ``review``.
        """
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text(
            "# Surface\nThe code-review action is documented here.\n",
            encoding="utf-8",
        )
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"review": ["pytest"]}, "agents": []}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        missing = [
            f for f in result["findings"]
            if f["check"] == "live_surface" and "review" in f["detail"]
        ]
        assert missing, (
            "short action 'review' must still be flagged missing when only "
            "'code-review' is present; got no live_surface warning"
        )


class TestRunCcSurfaceGateCommandsDoc:
    def test_commands_doc_missing_action_is_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "COMMANDS.md").write_text("# Commands\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"deploy": ["make deploy"]}}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "commands"]
        assert len(warnings) > 0

    def test_commands_doc_containing_action_no_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "COMMANDS.md").write_text("# Commands\ndeploy is listed\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"stable_actions": {"deploy": ["make deploy"]}}),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "commands"]
        assert len(warnings) == 0


class TestRunCcSurfaceGateRootGarbage:
    def test_suspicious_root_file_is_warning(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc_surface_dump.txt").write_text("garbage", encoding="utf-8")
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "root_garbage"]
        assert len(warnings) > 0

    def test_normal_root_file_is_not_flagged(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "README.md").write_text("# Normal file\n", encoding="utf-8")
        result = run_cc_surface_gate(tmp_path)
        warnings = [f for f in result["findings"] if f["check"] == "root_garbage"]
        assert len(warnings) == 0

    def test_benign_less_substring_not_flagged(self, tmp_path):
        """TP-192 W6-2: a benign root file whose name merely CONTAINS ``less``
        as a word-internal substring (painless/flawless/useless/blessing) must
        not draw a spurious root_garbage warning — the ``*less*`` regex was
        word-bound to the pager-spillage token shape (governing-frame: a benign
        false-positive in audit/smoke output)."""
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "painless_setup.py").write_text("x = 1\n", encoding="utf-8")
        result = run_cc_surface_gate(tmp_path)
        garbage = [
            f for f in result["findings"]
            if f["check"] == "root_garbage" and "painless" in f["detail"]
        ]
        assert garbage == [], f"benign 'painless_setup.py' must not be flagged; got: {garbage}"

    def test_genuine_less_spillage_still_flagged(self, tmp_path):
        """Negative control: a real ``less``-token root artifact is still caught."""
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "less.out").write_text("SUMMARY OF LESS\n", encoding="utf-8")
        result = run_cc_surface_gate(tmp_path)
        garbage = [
            f for f in result["findings"]
            if f["check"] == "root_garbage" and "less.out" in f["detail"]
        ]
        assert len(garbage) > 0, "genuine less-spillage artifact must still be flagged"


class TestRunCcSurfaceGateMalformedPlanValues:
    """TP-192 W3-3: ``_load_json`` guards only the TOP-LEVEL report shape (TP-191
    W2); a present-but-wrong-typed FIELD (generated_docs/stable_actions/agents =
    null/str/list-of-str) still tracebacked the ``build_plan.get(...)`` derefs in
    ``run_cc_surface_gate``. Coerce each to its expected type at the call sites."""

    def test_malformed_plan_values_do_not_traceback(self, tmp_path):
        _scaffold_gate_pass(tmp_path)
        # LIVE_SURFACE + COMMANDS must exist to exercise the stable_actions /
        # agents loops (both blocks are guarded on the doc existing).
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# live\n", encoding="utf-8")
        (tmp_path / "cc" / "COMMANDS.md").write_text("# cmds\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({
                "generated_docs": None,                  # not a list
                "stable_actions": "oops",                # not a dict
                "agents": ["notadict", {"name": "x"}],   # list with a non-dict member
            }),
            encoding="utf-8",
        )
        # Pre-fix: TypeError (iterate None) / AttributeError (str.keys / str.get).
        result = run_cc_surface_gate(tmp_path)
        assert isinstance(result, dict)
        assert "status" in result

    def test_wellformed_plan_still_classifies(self, tmp_path):
        # Negative control: a well-formed plan runs and emits the expected
        # missing-action/agent findings unchanged.
        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# live\nfoo\nbar_agent\n", encoding="utf-8")
        (tmp_path / "cc" / "COMMANDS.md").write_text("# cmds\nfoo\n", encoding="utf-8")
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({
                "stable_actions": {"foo": {}},
                "agents": [{"name": "bar_agent"}],
                "generated_docs": [],
            }),
            encoding="utf-8",
        )
        result = run_cc_surface_gate(tmp_path)
        assert isinstance(result, dict)
        missing = [f for f in result["findings"] if f["check"] in {"live_surface", "commands"}]
        assert missing == [], missing


class TestRunCcSurfaceGatePathNormalization:
    def test_managed_file_paths_use_forward_slashes(self, tmp_path):
        """Paths in findings use forward slashes for Windows compat."""
        _scaffold_gate_pass(tmp_path)
        tools_cc = tmp_path / "tools" / "cc"
        tools_cc.mkdir(parents=True)
        # A managed file under a NESTED path (tools/cc/...) whose content trips
        # the placeholder scan, so the gate emits a finding whose `detail`
        # embeds that multi-segment relative path. The prior fixture wrote inert
        # content ("x = 1\n") that produced NO finding -- so result["findings"]
        # was empty and the forward-slash assertion ran zero times: green under
        # any separator regression on a Windows path it was meant to catch.
        placeholder_file = tools_cc / "unmanaged.py"
        _write_managed(placeholder_file, "value = 'TEMPLATE_ONLY'\n")
        result = run_cc_surface_gate(tmp_path)
        detail_findings = [
            f for f in result["findings"]
            if f["check"] in {"placeholder", "malformed_text"}
        ]
        # Positive: our nested managed file produced a path-bearing finding, and
        # its detail carries the forward-slashed relative path (not tools\cc\...).
        assert any(
            "tools/cc/unmanaged.py" in f["detail"] for f in detail_findings
        ), f"expected a path-bearing finding for the nested managed file; got {result['findings']!r}"
        # Windows compat: NO path-bearing finding may contain a backslash.
        for finding in detail_findings:
            assert "\\" not in finding["detail"], finding

    def test_freshness_finding_path_uses_forward_slashes(self, tmp_path):
        """A `freshness` (missing-required-file) finding forward-slashes its path.

        The required files are all multi-segment (reports/..., cc/..., .claude/...),
        so on Windows the raw Path.relative_to() rendered backslashes. A bare repo
        is missing every required file, firing the branch that embeds the path.
        """
        result = run_cc_surface_gate(tmp_path)
        freshness = [f for f in result["findings"] if f["check"] == "freshness"]
        assert freshness, f"expected a freshness finding; got {result['findings']!r}"
        # The nested required path is present, forward-slashed...
        assert any(
            "reports/repo_fingerprint.json" in f["detail"] for f in freshness
        ), freshness
        # ...and no freshness detail carries a backslash.
        for finding in freshness:
            assert "\\" not in finding["detail"], finding

    def test_toml_finding_path_uses_forward_slashes(self, tmp_path):
        """A `toml` (invalid managed .toml) finding forward-slashes its path.

        A managed .toml under a NESTED .claude subdir with broken TOML fires the
        parse-error branch, whose detail embeds the multi-segment relative path.
        """
        bad = tmp_path / ".claude" / "sub" / "bad.toml"
        _write_managed(bad, "this is = not valid = toml\n")
        result = run_cc_surface_gate(tmp_path)
        toml_findings = [f for f in result["findings"] if f["check"] == "toml"]
        assert toml_findings, f"expected a toml finding; got {result['findings']!r}"
        assert any(
            ".claude/sub/bad.toml" in f["detail"] for f in toml_findings
        ), toml_findings
        for finding in toml_findings:
            assert "\\" not in finding["detail"], finding


class TestLoadJsonRobustness:
    """TP-191 W2: a present-but-malformed reports/*.json must degrade to {}
    (so run_cc_surface_gate keeps working), not traceback. The read is already
    decode-safe via _safe_text; this guards the json.loads parse."""

    def test_malformed_json_degrades_to_empty(self, tmp_path):
        from espalier.proofs import _load_json
        p = tmp_path / "cc_surface_gate.json"
        p.write_text("{ not: valid json,,", encoding="utf-8")
        assert _load_json(p) == {}

    def test_non_dict_json_degrades_to_empty(self, tmp_path):
        from espalier.proofs import _load_json
        p = tmp_path / "cc_surface_gate.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert _load_json(p) == {}


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits and a non-root user",
)
class TestTheGateNamesAnUnreadableClaudeOnce:
    """DEF-763, driven 2026-09-13: with `.claude` mode 000 the gate reported
    `missing generated file: .claude/settings.json` plus every manifest
    entry as a promised-but-missing file on CPython 3.14, and raised out of
    the first `Path.exists()` on 3.10-3.13. One presence finding naming the
    permission, on every interpreter, and the report file still lands."""

    @staticmethod
    def _run_locked(tmp_path: Path, mode: int = 0) -> dict:
        from _locked import locked
        from espalier.proofs import run_cc_surface_gate

        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            ".claude/settings.json\n.claude/agents/one.md\n", encoding="utf-8"
        )
        with locked(tmp_path / ".claude", mode):
            return run_cc_surface_gate(tmp_path)

    def test_one_presence_error_and_no_phantom_missing_list(self, tmp_path):
        report = self._run_locked(tmp_path)
        assert report["status"] == "fail", report
        errors = [f for f in report["findings"] if f["level"] == "error"]
        assert len(errors) == 1 and errors[0]["check"] == "presence", report["findings"]
        assert ".claude cannot be read" in errors[0]["detail"], errors[0]
        assert "Permission denied" in errors[0]["detail"], errors[0]
        joined = " ".join(f["detail"] for f in report["findings"])
        assert "missing generated file" not in joined and "promises missing" not in joined, joined
        assert report["summary"] == {"errors": 1, "warnings": 0}, report["summary"]

    def test_the_report_file_still_lands_and_doctor_forwards_the_sentence(self, tmp_path):
        from espalier.proofs import first_error_detail

        report = self._run_locked(tmp_path)
        on_disk = json.loads((tmp_path / "reports" / "cc_surface_gate.json").read_text(encoding="utf-8"))
        assert on_disk == report
        assert first_error_detail(report).startswith(".claude cannot be read")

    @pytest.mark.parametrize("mode", [0o400, 0o100], ids=["read only", "search only"])
    def test_each_lock_shape_is_the_same_finding(self, tmp_path, mode):
        errors = [f for f in self._run_locked(tmp_path, mode)["findings"] if f["level"] == "error"]
        assert [f["check"] for f in errors] == ["presence"], errors

    def test_a_readable_claude_walks_the_manifest_as_before(self, tmp_path):
        from espalier.proofs import run_cc_surface_gate

        _scaffold_gate_pass(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(".claude/agents/one.md\n", encoding="utf-8")
        report = run_cc_surface_gate(tmp_path)
        assert any("promises missing files" in f["detail"] for f in report["findings"]), report
