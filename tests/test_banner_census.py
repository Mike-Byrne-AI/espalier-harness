# pytest-marker: default-unit  (planted transcripts under tmp_path and the hook's source read as text; no git)
"""Pins ``scripts/banner_census.py``: what the SessionStart banner spent, start
by start, read from one project directory's transcripts (TP-705, Task 0).

The census carries the hook's headers and health lines as literals, since it
imports nothing from ``tools/cc/``; so the first class reads
``tools/cc/hooks/session_start.py`` as text and holds every literal to the
hook's own (a module constant by its parsed value, an inline header by its
place in the source), and a header the hook renames reds here before the
census quietly folds a section into its neighbour. The rest plant transcripts
in the shape Claude Code writes them (an ``attachment`` record whose
``content`` is a list of strings) and pin each rule the module docstring
states: the kinds read from the text, the sections that sum to the whole in
UTF-16 units, the health figures read from the health section alone, the
ceiling by the merge's date and by HEAD, and the flags.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "banner_census.py"
HOOK_PATH = REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py"

if not MODULE_PATH.is_file():  # pragma: no cover - adopter tree
    pytest.skip("scripts/banner_census.py is self-host dev tooling", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("banner_census", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bc = _load()


def _hook_constant(source: str, name: str):
    """The value the hook's module-level ``name = <literal>`` assigns."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a module-level literal in {HOOK_PATH.name}")


def _banner(*, checkout: str = "", blueprint: str = "# Session Context (depth 3)\n- decided x",
            health: str = "", goal: str = "- shipped the census\n", tail_cut: bool = False,
            memory: bool = True) -> str:
    """A whole banner in the hook's order: header, body (health block first),
    orientation tail."""
    head = (bc.SESSION_START_OPENING + "\n" + "Repo:      espalier-harness\n" + "Branch:    main\n"
            + "Status:    clean\n" + (f"Checkout:  {checkout}\n" if checkout else "")
            + "Memory:    espalier-harness\n" + f"{bc.BLUEPRINT_LINE}{blueprint}\n" + f"{bc.SURFACE_LINE}healthy\n"
            + "Commands: /status\n" + "Run /status to verify harness state.\n")
    body = (f"{bc.HEALTH_HEADER}\n{health}\n\n" if health else "") + f"{bc.WARNINGS_HEADER}\n[WARN] one\n\n"
    body += f"\n{bc.GOAL_HEADER}\n{goal}"
    if memory:
        body += ("\n--- MEMORY (recent sessions -- headlines only; read memory/session-log.d/ for full rows) ---\n"
                 "- a row\n")
    body += ("\n--- STANDING PRINCIPLES: 19 (hold these; titles and bodies in docs/STANDING_PRINCIPLES.md; "
             "/recall <topic> pulls one) ---\n")
    body += f"\n{bc.FOOTGUNS_HEADER}\ndocs/SHARP_EDGES.md\n"
    if tail_cut:
        body += bc.BODY_CUT_MARKER
    tail = ("\nOrientation (on first response -- this REPLACES the old terse status report):\n"
            "- Open with your read.\n\n(/context-load remains available for explicit mid-session re-orient.)")
    return head + body + tail


def _yielded(handed: int, kept: int, goal: int, headroom: int, *, binds: int = 0) -> str:
    """A health block's lines for a start whose blueprint yielded."""
    lines = [f"[banner] goal section is large ({goal + 500} bytes) -- consider trimming cc/GOAL.md",
             f"{bc.HEALTH_YIELD}{handed} -> {kept} characters (its share 3000); the rest is in cc/blueprints "
             "(/read-summary)",
             f"[banner] 9500 characters of the host's 10000: header 2399 (blueprint {kept} of 3000), body 5000 of "
             f"5000, tail 1578; goal {goal} of 2000 bytes (cap 4500), memory 644 of 1200 bytes, standing 123 of "
             f"1000 bytes, footguns 256 bytes; headroom {headroom}"]
    if binds:
        lines.append(f"{bc.HEALTH_BINDS}{binds} characters; shorten cc/GOAL.md")
    return "\n".join(lines)


def _record(text: str, at: str, hook: str = "SessionStart") -> dict:
    return {"type": "attachment", "timestamp": at, "sessionId": "s",
            "attachment": {"type": "hook_additional_context", "content": [text], "hookName": hook,
                           "toolUseID": hook, "hookEvent": hook}}


def _project(tmp_path: Path, **transcripts: list) -> Path:
    """A project directory: one ``<name>.jsonl`` per keyword, a record (or a
    raw line) per entry."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    for name, records in transcripts.items():
        lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
        (project / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return project


def _census(project: Path, **kw) -> dict:
    return bc.census(bc.read_project(project), **kw)


@pytest.fixture(scope="module")
def source() -> str:
    """The hook's source, read as text (never imported)."""
    if not HOOK_PATH.is_file():  # pragma: no cover - adopter tree
        pytest.skip("the hook's source is not in this tree")
    return HOOK_PATH.read_text(encoding="utf-8")


class TestTheLiteralsAreTheHooks:
    """Every header, marker and figure the census reads is the hook's own."""

    def test_the_module_constants_equal_the_hooks(self, source):
        """Dies to: the hook's health header, goal headers, health lines, cut
        markers or ceiling moved without the census."""
        pairs = {"_HEALTH_HEADER": bc.HEALTH_HEADER, "_GOAL_HEADER": bc.GOAL_HEADER,
                 "_GOAL_HEADER_COMPACT": bc.GOAL_HEADER_COMPACT, "_HEALTH_YIELD": bc.HEALTH_YIELD,
                 "_HEALTH_BINDS": bc.HEALTH_BINDS, "_BODY_CUT_MARKER": bc.BODY_CUT_MARKER,
                 "_BLUEPRINT_HEAD_MARKER": bc.BLUEPRINT_HEAD_MARKER, "_MAX_CONTEXT_CHARS": bc.MAX_CONTEXT_CHARS,
                 "_HOST_CONTEXT_CAP_CHARS": bc.HOST_CONTEXT_CAP_CHARS}
        assert {name: _hook_constant(source, name) for name in pairs} == pairs

    def test_the_inline_headers_open_a_string_in_the_hooks_source(self, source):
        """The MEMORY, STANDING, FOOTGUNS and OPEN PLAN headers are literals or
        f-strings that open with a newline. Dies to: a header renamed in the hook."""
        for prefix in (bc.MEMORY_HEADER, bc.STANDING_HEADER, bc.FOOTGUNS_HEADER, bc.OPEN_PLAN_HEADER):
            assert re.search(r'f?"\\n' + re.escape(prefix), source), prefix

    def test_the_warnings_and_notes_headers_are_the_titled_f_string(self, source):
        """The full banner's WARNINGS and NOTES come from one f-string over two
        titles; the plain literal is the short banners'. Dies to: either title
        or the f-string's shape changed."""
        assert 'f"--- {title} ---\\n"' in source
        assert '(("WARNINGS", warnings), ("NOTES", notes))' in source
        assert bc.WARNINGS_HEADER == "--- WARNINGS ---" and bc.NOTES_HEADER == "--- NOTES ---"
        assert f'"{bc.WARNINGS_HEADER}"' in source

    def test_the_orientation_and_banner_openings_are_in_the_hooks_source(self, source):
        """Dies to: the tail's first line, the three openings or the
        ``Blueprint:`` slot's render renamed."""
        assert any(line.startswith(bc.ORIENTATION_HEADER) for line in source.splitlines())
        assert f'"{bc.SESSION_START_OPENING}\\n"' in source
        assert f'"{bc.COMPACT_OPENING}' in source
        assert f'"{bc.SHORT_OPENING}' in source
        assert 'lambda bp: f"Blueprint: {bp}\\n"' in source
        assert f'f"{bc.SURFACE_LINE}{{surface_line}}\\n"' in source


class TestAStringIsReadForItsKind:
    """No record names its source, so the kind is read from the text, and
    every string is counted under one kind."""

    def test_each_kind_is_counted_apart(self, tmp_path):
        """Dies to: a spill preview counted as a banner (the prototype's
        miscount), a compact spill counted as a start's spill, or a string of
        no kind dropped."""
        preview = ("<persisted-output>\nOutput too large (10.6KB). Full output saved to: /x/hook.txt\n\n"
                   "Preview (first 2KB):\n")
        project = _project(tmp_path, a=[
            _record(_banner(), "2026-11-01T00:00:00Z"),
            _record(preview + bc.SESSION_START_OPENING + "\nRepo: x", "2026-10-30T00:00:00Z"),
            _record(preview + bc.SESSION_START_OPENING + "\nRepo: y", "2026-10-31T06:45:50Z"),
            _record(bc.COMPACT_OPENING + " (mid-session) ===\nRepo: x", "2026-11-01T01:00:00Z"),
            _record(preview + bc.COMPACT_OPENING + " (mid-session) ===\nRepo: x", "2026-11-01T02:00:00Z"),
            _record(bc.SHORT_OPENING + " the rest resumes at the next start) ===", "2026-11-01T03:00:00Z"),
            _record("something new the hook says", "2026-11-01T04:00:00Z"),
            _record("[WARN] espalier: integrity drift", "2026-11-01T05:00:00Z", hook="PostToolUse:Edit"),
            {"type": "user", "timestamp": "2026-11-01T06:00:00Z", "message": "hook_additional_context"},
            '{"attachment": {"type": "hook_additional_context", ',
        ])
        data = _census(project)
        assert data["population"] == {"whole": 1, "spill": 2, "compact": 1, "compact_spill": 1, "short": 1,
                                      "unclassified": 1, "not_banner": 1}
        assert data["strings"] == 8 and data["transcripts"] == 1 and data["unparsed_lines"] == 1
        assert data["newest"]["spill"] == "2026-10-31T06:45:50Z"

    def test_only_the_directorys_own_transcripts_are_read(self, tmp_path):
        """One transcript per session directly under the directory; a session
        folder's subagent transcripts are not read. Dies to: a recursive walk."""
        project = _project(tmp_path, a=[_record(_banner(), "2026-11-01T00:00:00Z")])
        nested = project / "a" / "subagents"
        nested.mkdir(parents=True)
        (nested / "agent-1.jsonl").write_text(json.dumps(_record(_banner(), "2026-11-01T01:00:00Z")) + "\n",
                                              encoding="utf-8")
        data = _census(project)
        assert data["transcripts"] == 1 and data["population"]["whole"] == 1


class TestAWholeBannerIsMeasured:
    """Units are UTF-16 units, the sections sum to the whole, and the health
    figures are read from the health section alone."""

    def test_the_sections_sum_to_the_whole_in_utf16_units(self):
        """An astral character is two units, as the host counts. Dies to:
        ``len()`` in place of the UTF-16 count, or a section boundary that
        drops or doubles a line."""
        text = _banner(goal="- a rocket \U0001F680 shipped\n", health=_yielded(2651, 815, 3763, 0))
        row = bc.measure(text, "2026-11-04T16:57:37Z", "t")
        assert row["units"] == len(text) + 1
        assert sum(row["sections"].values()) == row["units"]
        assert list(row["sections"]) == ["header", "health", "warnings", "goal", "memory", "standing", "footguns",
                                         "orientation"]
        goal = bc.split_sections(text)["goal"]
        assert goal.startswith("\n") is False and goal.startswith(bc.GOAL_HEADER)

    def test_a_header_quoted_inside_a_later_section_is_content(self):
        """A goal file quoting an earlier section's header does not reopen it.
        Dies to: any header line opening a section wherever it falls."""
        text = _banner(goal=f"{bc.HEALTH_HEADER}\n{bc.WARNINGS_HEADER}\nquoted\n", health="[banner] one flag")
        parts = bc.split_sections(text)
        assert parts["health"].count(bc.HEALTH_HEADER) == 1
        assert parts["goal"].count(bc.HEALTH_HEADER) == 1 and "quoted" in parts["goal"]

    def test_the_yield_ledger_and_binds_lines_are_read_from_the_health_section(self):
        """Dies to: the yield's two figures, the goal bytes, the soft budget,
        the headroom or the body loss misread."""
        text = _banner(health=_yielded(2747, 73, 4493, -1375, binds=1380), tail_cut=True,
                       blueprint="# Session Context (depth 297)" + bc.BLUEPRINT_HEAD_MARKER)
        row = bc.measure(text, "2026-11-01T18:22:43Z", "t")
        assert row["yield"] == {"handed": 2747, "kept": 73, "share": 3000}
        assert (row["goal_bytes"], row["goal_soft"], row["headroom"], row["loss"]) == (4493, 2000, -1375, 1380)
        assert row["clipped"] is True and row["head_only"] is True

    def test_a_health_line_a_goal_file_quotes_is_not_read(self):
        """Dies to: the yield or ledger read from the whole text, where the
        goal file's own notes quote yesterday's line, or a quoted body-cut
        marker read as a clip (the hook's sits where the kept body stops)."""
        quoted = _yielded(2651, 815, 3763, 0) + bc.BODY_CUT_MARKER
        row = bc.measure(_banner(goal=quoted + "\n", health="[banner] one flag"), "2026-11-01T00:00:00Z", "t")
        assert row["yield"] is None and row["goal_bytes"] is None and row["headroom"] is None
        assert row["clipped"] is False

    def test_the_blueprint_slot_is_the_yield_lines_kept_figure(self):
        """The slot's units are what the hook's yield line says it kept.
        Dies to: the slot measured with its label or past the Surface line."""
        blueprint = "# Session Context (depth 9)\n- decided one\n- decided two"
        kept = bc.units(blueprint)
        row = bc.measure(_banner(blueprint=blueprint, health=_yielded(3000, kept, 3000, 0)), "2026-11-01T00:00:00Z",
                         "t")
        assert row["blueprint"] == kept == row["yield"]["kept"]

    def test_the_head_is_read_from_the_checkout_lines_now(self):
        """Dies to: a HEAD invented for a branch the catch-up left as is."""
        caught = bc.measure(_banner(checkout="caught up -- main fast-forwarded, 16 commits, now 970a6464 (hooks or "
                                             "CLAUDE.md changed with it)"), "2026-10-31T07:47:47Z", "t")
        on_lane = bc.measure(_banner(checkout="on lane/x (3 commits not in main)"), "2026-11-04T00:24:54Z", "t")
        none = bc.measure(_banner(), "2026-11-04T00:00:00Z", "t")
        assert (caught["head"], on_lane["head"], none["head"]) == ("970a6464", None, None)


class TestTheCeilingSplitsBeforeAndSince:
    """By the date of DEF-674's merge to main, and by HEAD where read."""

    def test_a_banner_of_the_lanes_own_commit_days_is_before_the_merge(self, tmp_path):
        """DEF-674's lane committed on 2026-10-29 and merged on 2026-10-31.
        Dies to: the cut read from the commit day, which would make the 29th's
        over-ceiling banners rows."""
        project = _project(tmp_path, a=[
            _record(_banner(goal="x" * 9000), "2026-10-29T07:28:35Z"),
            _record(_banner(), "2026-10-31T07:14:27Z"),
            _record(_banner(health=_yielded(2651, 815, 3763, 0)), "2026-10-31T07:14:28Z"),
            _record(_banner(), "not a stamp"),
        ])
        data = _census(project)
        assert data["ceiling"]["by_date"] == {"before": 2, "since": 1, "undated": 1}
        assert [o["at"] for o in data["over_ceiling"]] == ["2026-10-29T07:28:35Z"]
        assert data["over_ceiling"][0]["since_by_date"] is False
        assert data["yields"]["since"] == 1 and data["yields"]["since_of"] == 1

    def test_by_head_reads_each_named_head_through_the_ancestry_check(self, tmp_path):
        """Dies to: a banner with no HEAD sent to git, or an unknown HEAD
        counted on either side."""
        seen = []

        def is_ancestor(head):
            seen.append(head)
            return {"aaaaaaaa": True, "bbbbbbbb": False}.get(head)

        project = _project(tmp_path, a=[
            _record(_banner(checkout=f"caught up -- main fast-forwarded, 1 commits, now {sha}"), f"2026-11-0{i}T00:00:00Z")
            for i, sha in enumerate(("aaaaaaaa", "bbbbbbbb", "cccccccc"), start=1)
        ] + [_record(_banner(checkout="on lane/x (1 commits not in main)"), "2026-11-05T00:00:00Z")])
        data = _census(project, is_ancestor=is_ancestor)
        assert data["ceiling"]["by_head"] == {"named": 3, "since": 1, "before": 1, "unknown": 1}
        assert seen == ["aaaaaaaa", "bbbbbbbb", "cccccccc"]

    def test_the_git_check_asks_merge_base_and_reads_its_exit(self, monkeypatch):
        """0 is an ancestor, 1 is not, anything else (128: an object not in
        the clone) or a git that will not start is unknown; one call per HEAD.
        Dies to: the merge and the HEAD swapped, or an error read as before."""
        calls = []
        answers = {"a1a1a1a1": 0, "b2b2b2b2": 1, "c3c3c3c3": 128}

        class Done:
            def __init__(self, rc):
                self.returncode = rc

        def run(argv, **kw):
            calls.append(argv)
            if argv[-1] == "d4d4d4d4":
                raise OSError("no git")
            return Done(answers[argv[-1]])

        monkeypatch.setattr(bc.subprocess, "run", run)
        check = bc.git_is_ancestor(Path("/repo"))
        assert [check(h) for h in ("a1a1a1a1", "b2b2b2b2", "c3c3c3c3", "d4d4d4d4", "a1a1a1a1")] == [
            True, False, None, None, True]
        assert calls[0] == ["git", "-C", str(Path("/repo")), "merge-base", "--is-ancestor", bc.CEILING_MERGE, "a1a1a1a1"]
        assert len(calls) == 4


class TestTheSummaryAndTheFlags:
    """The text summary, ``--last``, ``--ranking`` and ``--json``."""

    @pytest.fixture
    def project(self, tmp_path):
        return _project(tmp_path, a=[
            _record(_banner(), "2026-10-20T00:00:00Z"),
            _record(_banner(health=_yielded(3000, 305, 3295, 788)), "2026-11-03T19:50:10Z"),
            _record(_banner(health=_yielded(2747, 73, 4493, -1375, binds=1380), tail_cut=True),
                    "2026-11-01T18:22:43Z"),
        ], b=[_record(_banner(health=_yielded(2651, 815, 3763, 0)), "2026-11-04T16:57:37Z")])

    @pytest.fixture(autouse=True)
    def _no_git(self, monkeypatch):
        monkeypatch.setattr(bc, "git_is_ancestor", lambda repo: (lambda head: None))

    def test_the_summary_prints_the_population_and_the_figures(self, project, capsys):
        """Dies to: a summary line missing or printing another figure under
        the same words."""
        assert bc.main(["--project", str(project)]) == 0
        out = capsys.readouterr().out
        assert "population: whole 4, spill 0, compact 0, compact spill 0, short 0, unclassified 0" in out
        assert "window: all 4 whole banners, 2026-10-20T00:00:00Z .. 2026-11-04T16:57:37Z" in out
        assert "by date: before 1, since 3;" in out
        assert "yields: 3 of 4 (since the ceiling by date 3 of 3)" in out
        assert "loss n 3, min/median/max 1836/2674/2695" in out
        assert "clips: 1 (the body-cut marker), the binds line on 1" in out
        assert "goal bytes (the health ledger): n 3, min/median/max 3295/3763/4493; soft budget 2000" in out
        assert "headroom n 3, min/median/max -1375/0/788" in out
        assert [line.split(":")[0] for line in out.splitlines() if line.startswith("section ")] == [
            "section header", "section health", "section warnings", "section notes", "section open_plan",
            "section goal", "section memory", "section standing", "section footguns", "section orientation"]

    def test_last_keeps_the_newest_whole_banners(self, project, capsys):
        """Newest by timestamp across transcripts, never by file. Dies to: the
        window cut in file order."""
        assert bc.main(["--project", str(project), "--last", "2", "--ranking"]) == 0
        out = capsys.readouterr().out
        assert "window: the newest 2 of 4 whole banners, 2026-11-03T19:50:10Z .. 2026-11-04T16:57:37Z" in out
        rows = [line for line in out.splitlines() if line.startswith("2026-")]
        assert [r.split()[0] for r in rows] == ["2026-11-03T19:50:10Z", "2026-11-04T16:57:37Z"]

    def test_the_ranking_prints_one_row_per_start_with_tasks_arithmetic(self, project, capsys):
        """Kept/handed from the yield line, the loss, the excess past the soft
        budget and whether excess plus headroom covers it. Dies to: a column
        read from another start or the arithmetic turned round."""
        assert bc.main(["--project", str(project), "--ranking"]) == 0
        rows = {line.split()[0]: line.split() for line in capsys.readouterr().out.splitlines()
                if line.startswith("2026-")}
        assert len(rows) == 4
        assert rows["2026-11-03T19:50:10Z"][3:] == ["305/3000", "3295", "788", "no", "2695", "1295", "no"]
        assert rows["2026-11-01T18:22:43Z"][3:] == ["73/2747", "4493", "-1375", "yes", "2674", "2493", "no"]
        assert rows["2026-10-20T00:00:00Z"][3:5] == [str(bc.units("# Session Context (depth 3)\n- decided x")),
                                                     "whole"]

    def test_json_gives_the_same_figures_as_data(self, project, capsys):
        """Dies to: the JSON and the text reading different figures, or the
        per-start rows riding without --ranking."""
        assert bc.main(["--project", str(project), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert "starts" not in data
        assert data["population"]["whole"] == 4 and data["yields"]["n"] == 3 and data["clips"]["n"] == 1
        assert bc.main(["--project", str(project), "--json", "--ranking"]) == 0
        assert len(json.loads(capsys.readouterr().out)["starts"]) == 4

    def test_the_output_is_seven_bit_ascii(self, tmp_path, capsys):
        """A banner quoting a non-ASCII character, in a directory whose name
        holds one. Dies to: banner text or the path printed raw."""
        project = _project(tmp_path / "café", a=[_record(_banner(goal="- naïve \U0001F680\n"),
                                                                "2026-11-01T00:00:00Z")])
        for flags in ([], ["--ranking"], ["--json", "--ranking"]):
            assert bc.main(["--project", str(project), *flags]) == 0
            capsys.readouterr().out.encode("ascii")

    def test_a_directory_with_no_whole_banner_is_a_note(self, tmp_path, capsys):
        project = _project(tmp_path, a=[_record("[WARN] x", "2026-11-01T00:00:00Z", hook="PostToolUse:Bash")])
        assert bc.main(["--project", str(project), "--ranking"]) == 0
        assert "note: no whole banner in this directory" in capsys.readouterr().out

    def test_usage_errors_exit_two(self, tmp_path, capsys):
        """Dies to: a missing directory or a window of none read as an empty census."""
        assert bc.main(["--project", str(tmp_path / "missing")]) == 2
        assert bc.main(["--project", str(tmp_path), "--last", "0"]) == 2
        err = capsys.readouterr().err
        assert "is not a directory" in err and "--last N" in err
