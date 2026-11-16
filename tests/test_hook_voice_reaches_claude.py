"""Every exit-0 hook advisory reaches a channel the protocol pin says is seen.

The pin (``docs/external/cc-hook-protocol.md``) sends the stderr of a hook that
exits 0 to Claude Code's debug log only: Claude never sees it and the
transcript never shows it. So a line someone must read takes one of two seen
channels: the additionalContext of the hook's ONE stdout JSON object (the
SessionStart banner, a PostToolUse object), or a ``say_once`` record that
``/status --log`` counts. ``tests/test_failopen_voice.py`` is the derived gate
over the source; these are the witnesses: each drives a repaired hook in a
scratch tree and asserts the text sits inside one stdout JSON object, or that
an audit record exists under ``ESPALIER_AUDIT_DIR`` (which conftest points at
a per-test directory).

Earn-the-red (2026-10-06): run against the tree before the repairs, 32 of the
34 rows here were red -- the lines went to stderr only, stdout held no object
naming them, and no record was written. The two green ones are guards, green
on both trees by design: a quiet boot renders no Warnings block, and the
crash-guard roster is every non-blocking hook entry point.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from tests._cut_start import skip_if_cut
from tests._live_tree import checkout_glob

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))


def _hook(name: str, payload: dict, root: Path, **env: str) -> subprocess.CompletedProcess:
    """Run a hook as Claude Code does: JSON on stdin, the project at ``root``,
    and none of the launching shell's harness variables. A SessionStart cut
    at its wall skips as cannot-tell (DEF-2048): its short banner carries only
    the warnings the phases before the cut raised, so the quiet-boot row would
    pass on it unseen."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ESPALIER_"))}
    clean.update(CLAUDE_PROJECT_DIR=str(root), ESPALIER_AUDIT_DIR=os.environ["ESPALIER_AUDIT_DIR"], **env)
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / f"{name}.py")],
        input=json.dumps(payload), capture_output=True, encoding="utf-8",
        env=clean, cwd=str(root), timeout=45,
    )
    skip_if_cut(result.stdout)
    return result


def _one_object(stdout: str) -> str:
    """The additionalContext of the ONE JSON object on stdout; two objects, or
    none, fail the whole parse the way Claude Code reads it."""
    text = stdout.strip()
    assert text, "the hook printed no JSON object"
    assert len(text.splitlines()) == 1, f"more than one stdout line: {text!r}"
    return json.loads(text)["hookSpecificOutput"]["additionalContext"]


def _records(event_type: str) -> list[dict]:
    out = []
    for log in Path(os.environ["ESPALIER_AUDIT_DIR"]).glob("*.log"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("event_type") == event_type:
                    out.append(rec)
    return out


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_voice_witness_{name}", HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── SessionStart: the reporters' and builders' lines join the banner ──────────


class TestSessionStartWarningsJoinTheBanner:
    def test_an_unresolvable_stop_gate_override_is_in_the_banner(self, tmp_path):
        r = _hook("session_start", {"source": "startup", "hook_event_name": "SessionStart"}, tmp_path,
                  ESPALIER_STOP_GATE="full", ESPALIER_STOP_GATE_TEST_CMD="nosuchprog-xyz --run")
        assert r.returncode == 0, r.stderr
        banner = _one_object(r.stdout)
        assert "--- WARNINGS ---" in banner
        assert "nosuchprog-xyz" in banner and "will not start" in banner, banner

    def test_the_maintenance_mode_explanation_is_in_the_banner(self, tmp_path):
        r = _hook("session_start", {"source": "startup"}, tmp_path, ESPALIER_MAINTENANCE_MODE="1")
        banner = _one_object(r.stdout)
        assert "ESPALIER_MAINTENANCE_MODE active" in banner and "bypassed for this session" in banner, banner

    def test_a_builder_warning_is_in_the_banner(self, tmp_path):
        """A goal file that exists and cannot be read: the builder's line,
        not only the missing section."""
        (tmp_path / "cc" / "GOAL.md").mkdir(parents=True)  # a directory: read_bytes raises
        r = _hook("session_start", {"source": "startup"}, tmp_path)
        banner = _one_object(r.stdout)
        assert "cc/GOAL.md unreadable" in banner, banner

    def test_the_compact_banner_carries_the_block_too(self, tmp_path):
        r = _hook("session_start", {"source": "compact"}, tmp_path, ESPALIER_MAINTENANCE_MODE="1")
        banner = _one_object(r.stdout)
        assert "POST-COMPACTION RE-ORIENT" in banner
        assert "ESPALIER_MAINTENANCE_MODE active" in banner, banner

    def test_one_long_warning_cannot_push_the_others_out(self, monkeypatch):
        """A wholesale integrity drift lists every file in one line: each line
        is cut to its head before the block is bounded, so the override line
        behind it survives, and an [INFO] line reads under NOTES."""
        ss = _load("session_start")
        ss._hook_utils.take_advisories()
        drift = "[WARN] Espalier-Harness integrity drift:\n  " + "\n  ".join(
            f"tools/cc/hooks/hook_{i:02d}.py" for i in range(40))
        for line in (drift, "[WARN] espalier: ESPALIER_MEMORY.md is UTF-16 without a mark",
                     "[WARN] espalier: ESPALIER_STOP_GATE_TEST_CMD names `nosuch`, which ... will not start",
                     "[INFO] session cwd is inside worktree w of this repository"):
            ss._hook_utils.advise(line, echo=False)
        block = ss._warnings_section()
        assert "will not start" in block and "UTF-16" in block, block
        assert "hook_39.py" not in block and "the full line is in the debug log" in block, block
        warnings, _, notes = block.partition("--- NOTES ---")
        assert "--- WARNINGS ---" in warnings and "session cwd is inside worktree" in notes, block

    def test_a_quiet_boot_renders_no_block(self, tmp_path):
        r = _hook("session_start", {"source": "startup"}, tmp_path)
        assert "--- WARNINGS ---" not in _one_object(r.stdout)


# ── PostToolUse: the warnings fold into the hook's one JSON object ────────────


class TestPostWriteCheckWarningsFoldIntoItsObject:
    def test_a_truncated_settings_file_is_named_in_one_object(self, tmp_path):
        target = tmp_path / ".claude" / "settings.json"
        target.parent.mkdir()
        target.write_text("{oops", encoding="utf-8")
        r = _hook("post_write_check", {"tool_name": "Write", "tool_input": {"file_path": str(target)},
                                       "hook_event_name": "PostToolUse"}, tmp_path)
        assert r.returncode == 0, r.stderr
        context = _one_object(r.stdout)
        assert ".claude/settings.json contains invalid JSON" in context, context

    def test_a_syntax_error_under_tools_cc_is_named(self, tmp_path):
        target = tmp_path / "tools" / "cc" / "broken.py"
        target.parent.mkdir(parents=True)
        target.write_text("def f(:\n", encoding="utf-8")
        r = _hook("post_write_check", {"tool_name": "Write", "tool_input": {"file_path": str(target)}}, tmp_path)
        assert "tools/cc/broken.py has a Python syntax error" in _one_object(r.stdout)

    def test_a_payload_and_a_warning_share_the_one_object(self, tmp_path):
        """The conflict-marker advisory (a payload the hook already printed)
        and a placeholder warning on the same write: ONE object carries both,
        because two stdout JSON lines fail the whole parse."""
        target = tmp_path / "ESPALIER_MEMORY.md"
        target.write_text("# memory\n" + "<" * 7 + " HEAD\nrow <fill>\n" + "=" * 7 + "\nrow\n"
                          + ">" * 7 + " theirs\n", encoding="utf-8")
        r = _hook("post_write_check", {"tool_name": "Write", "tool_input": {"file_path": str(target)}}, tmp_path)
        context = _one_object(r.stdout)
        assert "conflict" in context.lower(), context
        assert "ESPALIER_MEMORY.md contains placeholders: <fill>" in context, context

    def test_the_autoprune_eviction_line_reaches_the_object(self, tmp_path, monkeypatch, capsys):
        """The line that names which sessions left -- the only place anyone
        learns it, the archive being gitignored -- rides the hook's object."""
        pwc = _load("post_write_check")
        memory = tmp_path / "ESPALIER_MEMORY.md"
        memory.write_text("\n".join(f"line {i}" for i in range(pwc._MEMORY_MD_CAP + 5)), encoding="utf-8")

        def fake_run(cmd, **_kw):
            memory.write_text("short\n", encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="archived 2 rows (2026-01-01, 2026-01-02)\n",
                                         stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pwc._hook_utils.take_advisories()
        pwc._maybe_autoprune_memory(tmp_path, "ESPALIER_MEMORY.md")
        pwc._hook_utils.emit_advisories("PostToolUse")
        context = _one_object(capsys.readouterr().out)
        assert "autoprune" in context and "2026-01-01, 2026-01-02" in context, context


class TestReflectTriggerWarningsFoldIntoItsObject:
    @staticmethod
    def _tenth_write(root: Path) -> subprocess.CompletedProcess:
        state = root / ".espalier-state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "write_count").write_text("9", encoding="utf-8")
        return _hook("reflect_trigger", {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}}, root)

    def test_a_dark_reflect_pipeline_is_named_in_the_object(self, tmp_path):
        r = self._tenth_write(tmp_path)
        assert r.returncode == 0, r.stderr
        context = _one_object(r.stdout)
        assert "reflect_protocol.py not found" in context and "drift detection DISABLED" in context, context

    def test_the_drift_summary_and_a_dark_record_path_share_one_object(self, tmp_path):
        tools = tmp_path / "tools" / "cc"
        tools.mkdir(parents=True)
        (tools / "reflect_protocol.py").write_text(
            "import json\nprint(json.dumps({'findings': [{'kind': 'gap', 'severity': 'high',"
            " 'description': 'CLAUDE.md links docs/gone.md'}], 'gap_count': 1,"
            " 'orphan_count': 0, 'files_analyzed': 3}))\n",
            encoding="utf-8",
        )
        r = self._tenth_write(tmp_path)
        context = _one_object(r.stdout)
        assert "Reflect pass flagged surface drift" in context, context
        assert "cognitive_blueprint.py not found" in context, context
        assert "drift detection DISABLED" not in context, "the record path's line says what it loses"


# ── Records: the crash guards, the Stop gate's skips, the rest ────────────────


REPORTER_CRASH_GUARDS = [
    ("session_start", "sessionstart_failed_open_crash"),
    ("task_router", "userpromptsubmit_failed_open_crash"),
    ("post_write_check", "posttooluse_failed_open_crash"),
    ("reflect_trigger", "posttooluse_failed_open_reflect_crash"),
    ("post_compact", "postcompact_failed_open_crash"),
    ("subagent_start", "subagentstart_failed_open_crash"),
    ("subagent_stop", "subagentstop_failed_open_crash"),
    ("context_reinject_failure", "posttoolusefailure_failed_open_crash"),
]


@pytest.mark.parametrize("hook,event_type", REPORTER_CRASH_GUARDS)
def test_a_reporter_crash_guard_leaves_a_record(hook, event_type, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    mod = _load(hook)

    def _boom(*_a):  # session_start's main() hands _run_main its wall start
        raise RuntimeError("simulated at /secret/path")

    monkeypatch.setattr(mod, "_run_main", _boom)
    assert mod.main() == 0
    assert f"[ERROR] {hook} crashed: RuntimeError" in capsys.readouterr().err
    records = _records(event_type)
    assert len(records) == 1, records
    assert records[0]["details"] == {"hook": hook, "key": f"{hook}-crash-RuntimeError", "fault": "RuntimeError"}
    assert "secret" not in json.dumps(records[0])


def test_the_reporter_crash_guards_are_the_eight_the_census_named():
    """The witness roster above is every non-blocking hook entry point: a
    ninth reporter joins it or this reds."""
    blocking = {"write_guard", "plan_guard", "config_guard", "stop_gate"}
    entries = {p.stem for p in checkout_glob(HOOKS_DIR, "*.py") if not p.name.startswith("_")}
    assert {h for h, _ in REPORTER_CRASH_GUARDS} == entries - blocking


class TestStopGateSkipsLeaveARecord:
    def test_no_test_paths_skip(self, tmp_path):
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            json.dumps({"test_commands": ["pytest tests/test_moved_away.py"]}), encoding="utf-8")
        r = _hook("stop_gate", {}, tmp_path, ESPALIER_STOP_GATE="full")
        assert r.returncode == 0, r.stderr
        assert "Gate 1 skipped" in r.stderr
        assert len(_records("stop_failed_open_pytest_no_paths")) == 1

    def test_the_timeout_arm(self, tmp_path, monkeypatch):
        sg = _load("stop_gate")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
        monkeypatch.setattr(sg, "_resolve_core_tests", lambda root: sg.ResolvedTests(
            paths=["tests/test_x.py"], status="ok", note=""))

        def _slow(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=60)

        monkeypatch.setattr(sg._hook_utils, "spawn_tree_checked", _slow)
        assert sg._gate_pytest(tmp_path) == 0
        records = _records("stop_failed_open_pytest_did_not_run")
        assert len(records) == 1 and records[0]["details"]["fault"] == "TimeoutExpired", records

    def test_an_unreadable_fingerprint(self, tmp_path, monkeypatch):
        sg = _load("stop_gate")
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text("{}", encoding="utf-8")

        def _denied(_raw):
            raise PermissionError("simulated")

        monkeypatch.setattr(sg, "load_json_dict_safe", _denied)
        assert sg._read_fingerprint_test_commands(tmp_path) == []
        assert len(_records("stop_failed_open_fingerprint_read")) == 1

    def test_an_override_that_splits_to_nothing(self, tmp_path):
        sg = _load("stop_gate")
        assert sg._run_command_gate(tmp_path, (" ",), source="env") == 0
        assert len(_records("stop_failed_open_env_override_empty")) == 1


class TestTheRestLeaveARecord:
    def test_config_guard_scan_arm(self, tmp_path, monkeypatch):
        cg = _load("config_guard")

        def _broken(_root):
            raise OSError("simulated")

        monkeypatch.setattr(cg._integrity, "scan_for_kill_switches", _broken)
        assert cg._scan_payload(None, tmp_path) == []
        assert len(_records("configchange_failed_open_scan")) == 1

    def test_post_compact_unreadable_blueprint(self, tmp_path):
        bp = tmp_path / "cc" / "blueprints" / "latest.json"
        bp.parent.mkdir(parents=True)
        bp.write_bytes('{"session_id": "ab"}'.encode("utf-16"))
        r = _hook("post_compact", {"hook_event_name": "PostCompact"}, tmp_path)
        assert r.returncode == 0, r.stderr
        assert len(_records("postcompact_failed_open_blueprint_read")) == 1

    def test_post_compact_malformed_blueprint(self, tmp_path):
        bp = tmp_path / "cc" / "blueprints" / "latest.json"
        bp.parent.mkdir(parents=True)
        bp.write_text("{not json", encoding="utf-8")
        _hook("post_compact", {}, tmp_path)
        assert len(_records("postcompact_failed_open_blueprint_json")) == 1

    @staticmethod
    def _transcript(tmp_path: Path) -> Path:
        tp = tmp_path / "t1.jsonl"
        tp.write_text(json.dumps({"isCompactSummary": True, "message": {"content": "the summary"}}) + "\n",
                      encoding="utf-8")
        return tp

    def test_post_compact_working_summary_not_written(self, tmp_path):
        pc = _load("post_compact")
        (tmp_path / "cc" / "_working_summary.md").mkdir(parents=True)  # a directory: the replace fails
        pc._capture_compact_summary(tmp_path, str(self._transcript(tmp_path)))
        assert len(_records("postcompact_failed_open_working_summary")) == 1

    def test_post_compact_resume_index_not_built(self, tmp_path, monkeypatch):
        pc = _load("post_compact")
        stub = types.ModuleType("session_summary")

        def _broken(*_a, **_k):
            raise RuntimeError("simulated")

        stub.build_resume_index = _broken
        monkeypatch.setitem(sys.modules, "session_summary", stub)
        pc._capture_compact_summary(tmp_path, str(self._transcript(tmp_path)))
        assert len(_records("postcompact_failed_open_resume_index")) == 1
        assert (tmp_path / "cc" / "_working_summary.md").read_text(encoding="utf-8").startswith("the summary")

    def test_post_compact_mail_line(self, tmp_path):
        pc = _load("post_compact")
        broken = types.SimpleNamespace(machine_setting=lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
        assert pc._mail_unread_line(tmp_path, mail=broken) == ""
        assert len(_records("postcompact_failed_open_mail")) == 1

    def test_subagent_stop_renamed_message_key(self, tmp_path):
        r = _hook("subagent_stop", {"agent_type": "code-reviewer", "agent_transcript_path": "t.jsonl"}, tmp_path)
        assert r.returncode == 0, r.stderr
        assert len(_records("subagentstop_failed_open_message_key")) == 1

    def test_plan_guard_ignored_exemption(self, tmp_path):
        pg = _load("plan_guard")
        (tmp_path / "espalier.toml").write_text('plan_exempt_prefixes = ["/abs/"]\n', encoding="utf-8")
        assert pg._load_adopter_exempt_prefixes(tmp_path) == ()
        records = _records("config_zone_ignored")
        assert len(records) == 1 and records[0]["details"]["hook"] == "plan_guard", records

    def test_integrity_unlocked_read(self, tmp_path, monkeypatch):
        integrity = _load("_integrity")
        (tmp_path / ".espalier").mkdir()

        def _refused(*_a, **_k):
            raise OSError("no lock here")

        monkeypatch.setattr(integrity._hook_utils, "lock_file", _refused)
        integrity.verify_integrity(tmp_path)
        assert len(_records("integrity_failed_open_unlocked_read")) == 1

    def test_the_cli_bridge_warns_every_run_and_records_nothing(self, tmp_path, monkeypatch, capsys):
        """Under the engine's CLI (doctor, audit) the unlocked read warns on the
        terminal every run, as before the voice repair, and writes no hook
        once-flag or record: the bridge switches the module's records off."""
        from espalier._integrity_bridge import load_integrity_module

        integrity = load_integrity_module()
        (tmp_path / ".espalier").mkdir()

        def _refused(*_a, **_k):
            raise OSError("no lock here")

        monkeypatch.setattr(integrity._hook_utils, "lock_file", _refused)
        integrity.verify_integrity(tmp_path)
        integrity.verify_integrity(tmp_path)
        assert capsys.readouterr().err.count("reading UNLOCKED") == 2
        assert not (tmp_path / ".espalier-state").exists()
        assert not _records("integrity_failed_open_unlocked_read")

    def test_write_guard_discard_snapshot_fault(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        wg = _load("write_guard")
        monkeypatch.setattr(wg._hook_utils, "read_stdin_safely",
                            lambda: {"tool_name": "Bash", "tool_input": {"command": "echo hi"}})

        def _boom(*_a, **_k):
            raise RuntimeError("simulated")

        monkeypatch.setattr(wg._speedbump, "snapshot_discard", _boom)
        assert wg._run_main() == 0
        records = _records("pretooluse_failed_open_discard_snapshot")
        assert len(records) == 1 and records[0]["details"]["fault"] == "RuntimeError", records


# ── config_guard: the settings-read record means a settings file, and names it ─


class TestTheSettingsReadRecordNamesASettingsFile:
    """DEF-3092: a change to a command or skill file reaches config_guard as a
    ConfigChange with ``source: skills`` and the markdown file's path (driven
    on Claude Code 2.1.321, 2026-11-16: an append to, a replace of and an add
    under ``.claude/commands/`` and an append to a ``SKILL.md``, one payload
    each). ``_scan_payload`` parsed whatever in-root file a payload named as
    JSON, so each such change wrote ``configchange_failed_open_settings_read``
    though no settings file went unread: the inventory scan ran after it. A
    SessionStart catch-up that moves ``.claude/commands/`` wrote one seconds
    into the session. The payload's file is read now only where it is the
    local or the project settings file, and the record names that file by
    its label, once a session for each."""

    @pytest.mark.parametrize("rel", [".claude/commands/status.md", ".claude/skills/probe/SKILL.md"])
    def test_a_skills_change_writes_no_settings_read_record(self, tmp_path, rel):
        changed = tmp_path / rel
        changed.parent.mkdir(parents=True)
        changed.write_text("---\ndescription: probe\n---\n\nbody\n", encoding="utf-8")
        r = _hook("config_guard", {"hook_event_name": "ConfigChange", "source": "skills",
                                   "file_path": str(changed)}, tmp_path)
        assert r.returncode == 0, r.stderr
        assert not r.stdout.strip(), r.stdout
        assert not _records("configchange_failed_open_settings_read")

    @pytest.mark.parametrize("label,source", [
        (".claude/settings.json", "project_settings"),
        (".claude/settings.local.json", "local_settings"),
    ])
    def test_an_unparseable_settings_file_is_named_in_the_record(self, tmp_path, label, source):
        (tmp_path / ".claude").mkdir()
        (tmp_path / label).write_text("{ not json", encoding="utf-8")
        r = _hook("config_guard", {"hook_event_name": "ConfigChange", "source": source,
                                   "file_path": str(tmp_path / label)}, tmp_path)
        assert r.returncode == 0, r.stderr
        records = _records("configchange_failed_open_settings_read")
        assert [rec["details"].get("file") for rec in records] == [label], records

    def test_each_settings_file_says_once_a_session(self, tmp_path):
        """The once-key carries the label: the local file's fault is said
        after the project file's, and the project file's again is not."""
        (tmp_path / ".claude").mkdir()
        for name in ("settings.json", "settings.local.json"):
            (tmp_path / ".claude" / name).write_text("{ not json", encoding="utf-8")
        for name, source in (("settings.json", "project_settings"),
                             ("settings.local.json", "local_settings"),
                             ("settings.json", "project_settings")):
            r = _hook("config_guard", {"hook_event_name": "ConfigChange", "source": source,
                                       "file_path": str(tmp_path / ".claude" / name)}, tmp_path)
            assert r.returncode == 0, r.stderr
        files = [rec["details"].get("file") for rec in _records("configchange_failed_open_settings_read")]
        assert sorted(files) == [".claude/settings.json", ".claude/settings.local.json"], files

    def test_a_kill_switch_beside_a_skills_change_is_still_refused(self, tmp_path):
        """The skills read is the one judgment moved: the inventory scan
        still reads both settings files on such a change."""
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
        changed = tmp_path / ".claude" / "commands" / "x.md"
        changed.write_text("body\n", encoding="utf-8")
        r = _hook("config_guard", {"hook_event_name": "ConfigChange", "source": "skills",
                                   "file_path": str(changed)}, tmp_path)
        assert json.loads(r.stdout).get("decision") == "block", (r.stdout, r.stderr)

    def test_an_unknown_sources_in_root_file_is_still_judged(self, tmp_path):
        """A source this hook does not know is judged, never waved through:
        its in-root file is read whatever it is (the failure-mode review drove
        a block on main and an allow on the first cut of this fix)."""
        (tmp_path / "ci-settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
        r = _hook("config_guard", {"hook_event_name": "ConfigChange", "source": "flag_settings",
                                   "file_path": str(tmp_path / "ci-settings.json")}, tmp_path)
        assert json.loads(r.stdout).get("decision") == "block", (r.stdout, r.stderr)

    def test_an_unreadable_other_file_is_named_by_a_fixed_word(self, tmp_path):
        (tmp_path / "ci-settings.json").write_text("{ not json", encoding="utf-8")
        _hook("config_guard", {"hook_event_name": "ConfigChange", "source": "flag_settings",
                               "file_path": str(tmp_path / "ci-settings.json")}, tmp_path)
        records = _records("configchange_failed_open_settings_read")
        assert [rec["details"].get("file") for rec in records] == ["another-in-root-file"], records

    def test_a_settings_file_it_cannot_locate_writes_its_own_type(self, tmp_path, monkeypatch):
        """The gate-switch site's fault is a file it could not locate, not one
        it read and could not parse: its own type, so the read type's count
        means the second alone."""
        cg = _load("config_guard")

        def _lost(*_a):
            raise OSError("simulated")

        monkeypatch.setattr(cg, "_changed_settings_label", _lost)
        assert cg._judge_gate_switch(".claude/settings.json", "project_settings", tmp_path) == ([], None, None)
        assert len(_records("configchange_failed_open_settings_locate")) == 1
        assert not _records("configchange_failed_open_settings_read")
