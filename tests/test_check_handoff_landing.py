"""Regression tests for the post-handoff landing gate
(``scripts/check_handoff_landing.py``).

The gate exists because ``/handoff`` commits at step 5 and then keeps writing
(steps 6, 7, 7b), so the artifacts a session writes LAST are the only ones its
suite never saw. That has reddened ``main`` four times on ``ESPALIER_MEMORY.md``
and once locally on the ledger.

Two properties are load-bearing and neither is obvious from reading the module:

1. The canon trailer is PARSED from ``memory/task-packs.md``, never restated
   here or in the script. A guard that restates its canon can disagree with it.
2. The gate selection REFUSES a member that no longer resolves. A hand-written
   list of test paths is exactly the shape that silently runs short after a
   rename (``docs/FAILURE_MODES.md`` 13.25), and a shorter selection is
   indistinguishable from a passing one.
"""
# pytest-marker: integration -- the git cases drive real `git init`/`commit` against
# tmp_path repos, so this module is classified `integration` and listed in
# tests/conftest.py::_SLOW_FILES. pyproject.toml's `unit` bucket says "no
# subprocess", and the parser cases alone would not justify the git ones.
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = REPO_ROOT / "scripts" / "check_handoff_landing.py"

if not _SCRIPT.is_file():
    pytest.skip(
        "scripts/check_handoff_landing.py is dev tooling not shipped in the "
        "sdist; this file applies only to source-checkout runs.",
        allow_module_level=True,
    )


def _load(monkeypatch=None, root: Path | None = None):
    spec = importlib.util.spec_from_file_location("_chl", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if root is not None:
        mod.REPO_ROOT = root
    return mod


class TestACitedKeyInATornRowIsReportedAsUnreadable:
    """DEF-764: the candidate pass skips a log line that is not JSON, so a
    key whose only row is torn is re-proposed as undecided. The landing
    check used to read that as "no row" -- true, and the wrong remedy (an
    append leaves the torn line in place). Now it names the shape."""

    _KEY = "abcdef012345"

    def _root(self, tmp_path: Path, log_body: str) -> Path:
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "# Memory\n\n## Session Log\n\n| Date | Summary |\n|---|---|\n"
            f"| 2026-09-12 | candidate key {self._KEY} logged as skipped |\n\n"
            "## Other\n",
            encoding="utf-8",
        )
        log = tmp_path / ".espalier" / "memory_candidate_log.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(log_body, encoding="utf-8")
        return tmp_path

    def _module(self, monkeypatch, root: Path):
        mod = _load(monkeypatch, root)
        # The enumeration is read from tools/cc/reflect_protocol.py under
        # REPO_ROOT, which the scratch root does not carry.
        monkeypatch.setattr(mod, "_dispositions", lambda: frozenset({"promoted", "updated", "skipped"}))
        return mod

    def test_a_torn_row_is_named_as_unreadable_not_absent(self, tmp_path, monkeypatch):
        root = self._root(
            tmp_path,
            '{"key": "' + self._KEY + '", "disposition": "skipped", "candidate": "torn\nacross lines"}\n',
        )
        problems = self._module(monkeypatch, root).check_candidate_keys()
        assert len(problems) == 1, problems
        assert "does not parse as JSON" in problems[0], problems
        assert "has no row for it" not in problems[0], problems

    def test_a_readable_row_is_clean(self, tmp_path, monkeypatch):
        root = self._root(tmp_path, json.dumps({"key": self._KEY, "disposition": "skipped"}) + "\n")
        assert self._module(monkeypatch, root).check_candidate_keys() == []

    def test_an_absent_row_keeps_the_absent_message(self, tmp_path, monkeypatch):
        root = self._root(tmp_path, json.dumps({"key": "0123456789ab", "disposition": "skipped"}) + "\n")
        problems = self._module(monkeypatch, root).check_candidate_keys()
        assert len(problems) == 1 and "has no row for it" in problems[0], problems


class TestCanonIsParsedNotRestated:
    def test_the_live_canon_resolves_to_one_trailer(self):
        mod = _load()
        canon = mod.canonical_trailer()
        assert canon is not None, (
            "memory/task-packs.md must declare exactly one backticked "
            "`Co-Authored-By: ...` line -- the script parses it as canon."
        )
        assert canon.startswith("Co-Authored-By: ")

    def test_two_declared_trailers_disable_enforcement(self, tmp_path):
        """Ambiguity must refuse, not pick the first."""
        doc = tmp_path / "memory" / "task-packs.md"
        doc.parent.mkdir(parents=True)
        doc.write_text(
            "- `Co-Authored-By: A <a@x.dev>`\n- `Co-Authored-By: B <b@x.dev>`\n",
            encoding="utf-8",
        )
        assert _load(root=tmp_path).canonical_trailer() is None

    def test_no_declared_trailer_disables_enforcement(self, tmp_path):
        doc = tmp_path / "memory" / "task-packs.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("nothing here\n", encoding="utf-8")
        assert _load(root=tmp_path).canonical_trailer() is None


class TestTheSelectionRefusesToRunShort:
    def test_every_named_gate_resolves_today(self):
        mod = _load()
        assert mod._resolve_selection(), "selection must not be empty"

    def test_a_moved_gate_raises_rather_than_running_short(self, tmp_path):
        """The property that makes a hand-written list safe.

        Earn-the-red: without the existence check the selection would simply
        run fewer files and still exit 0 -- green because it checked less.
        """
        mod = _load(root=tmp_path)
        mod.SELECTION = {"tests/test_definitely_not_here.py": "synthetic"}
        with pytest.raises(SystemExit) as exc:
            mod._resolve_selection()
        assert "no longer resolve" in str(exc.value)

    def test_the_selection_covers_the_classes_that_reddened_main(self):
        """Named so that deleting a member has to be deliberate."""
        mod = _load()
        for required in (
            "tests/test_no_internal_codenames.py",       # the 911eb70 class
            "tests/test_forward_ledger_completeness.py",  # the 2026-09-01 class
        ):
            assert required in mod.SELECTION, (
                f"{required} guards a class that has actually reddened main; "
                "removing it needs a recorded reason, not a quiet delete."
            )


class TestTrailerCheck:
    @pytest.mark.slow
    def test_a_mismatched_trailer_is_reported_with_both_spellings(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m",
             "s\n\nCo-Authored-By: Wrong Name <wrong@example.com>"],
            cwd=repo, check=True,
        )
        doc = repo / "memory" / "task-packs.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("- `Co-Authored-By: Right <right@x.dev>`\n", encoding="utf-8")

        problems = _load(root=repo).check_trailer("HEAD")
        assert len(problems) == 1
        assert "wrong@example.com" in problems[0]
        assert "right@x.dev" in problems[0]

    @pytest.mark.slow
    def test_a_matching_trailer_is_clean(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m",
             "s\n\nCo-Authored-By: Right <right@x.dev>"],
            cwd=repo, check=True,
        )
        doc = repo / "memory" / "task-packs.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("- `Co-Authored-By: Right <right@x.dev>`\n", encoding="utf-8")

        assert _load(root=repo).check_trailer("HEAD") == []

    @pytest.mark.slow
    def test_a_commit_with_no_trailer_is_reported(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "no trailer"], cwd=repo, check=True)
        doc = repo / "memory" / "task-packs.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("- `Co-Authored-By: Right <right@x.dev>`\n", encoding="utf-8")

        problems = _load(root=repo).check_trailer("HEAD")
        assert len(problems) == 1
        assert "carries no Co-Authored-By trailer" in problems[0]


class TestOwedListIsReDerived:
    """The arm that exists because an instruction was not enough.

    The prior remedy told the author to diff a commit range. That oracle answers
    "what changed recently", and an owed item that landed in an ALREADY-PUSHED
    commit sits outside it -- which is how a landed item survived as "owed" for
    two sessions. These probes ask "is this done" instead.

    Every case below is a red-team finding from 2026-09-01 turned into a test,
    on the principle that a finding fixed without a test is a defect that can
    return silently.
    """

    @staticmethod
    def _write(root: Path, bullets, owed: list[dict], count=None) -> None:
        """`bullets` is a list of (marker_id_or_None, spelling)."""
        import json as _json
        (root / "cc").mkdir(parents=True, exist_ok=True)
        body = "# G\n\n## Still owed\n\n"
        for mid, mark in bullets:
            tag = f" <!--owed:{mid}-->" if mid else ""
            body += f"{mark} item{tag}\n"
        body += "\n## How close\n\ndone\n"
        (root / "cc" / "GOAL.md").write_text(body, encoding="utf-8")
        payload = {"owed": owed}
        if count is not None:
            payload["_count"] = count
        (root / "cc" / "GOAL_OWED.json").write_text(_json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _probe(pid, prints="True", open_value="True"):
        return {"id": pid, "cmd": f"python3 -c \"print('{prints}')\"",
                "open_value": open_value, "why_not": None}

    def test_no_goal_doc_means_nothing_to_check(self, tmp_path):
        assert _load(root=tmp_path).check_owed() == []

    def test_an_item_whose_probe_stopped_reporting_open_is_flagged(self, tmp_path):
        self._write(tmp_path, [("a", "-")], [self._probe("a", prints="False")])
        problems = _load(root=tmp_path).check_owed()
        assert any("looks DONE" in p and "'a'" in p for p in problems)

    def test_an_item_still_open_is_silent(self, tmp_path):
        self._write(tmp_path, [("a", "-")], [self._probe("a")])
        assert _load(root=tmp_path).check_owed() == []

    def test_a_star_bullet_is_counted(self, tmp_path):
        """FAILS OPEN if only `- ` is matched: the invisible bullet is the unchecked one."""
        self._write(tmp_path, [("a", "-"), ("b", "*")], [self._probe("a")])
        problems = _load(root=tmp_path).check_owed()
        assert problems, "a `*` bullet with no probe must not pass silently"
        assert any("do not match" in p or "marker" in p for p in problems)

    def test_a_bullet_without_a_marker_is_flagged(self, tmp_path):
        self._write(tmp_path, [(None, "-")], [self._probe("a")])
        assert any("no\n`<!--owed:id-->` marker" in p.replace(" ", "\n") or "marker" in p
                   for p in _load(root=tmp_path).check_owed())

    def test_equal_counts_with_swapped_identities_are_flagged(self, tmp_path):
        """Cardinality is not correspondence -- the laundering shape, one layer up."""
        self._write(tmp_path, [("brand-new", "-")], [self._probe("retired-item")])
        problems = _load(root=tmp_path).check_owed()
        assert any("do not match" in p for p in problems)

    def test_a_declared_count_that_disagrees_is_flagged(self, tmp_path):
        """The limb the sibling runner was burned into growing."""
        self._write(tmp_path, [("a", "-")], [self._probe("a")], count=7)
        assert any("_count=7" in p for p in _load(root=tmp_path).check_owed())

    def test_an_empty_owed_list_is_refused(self, tmp_path):
        """Zero probes is indistinguishable from zero stale items."""
        self._write(tmp_path, [], [])
        assert any("no owed items at all" in p for p in _load(root=tmp_path).check_owed())

    @staticmethod
    def _goal_only(root: Path, body: str) -> list[str]:
        """A goal doc and NO probe file: the absent-file limb, nothing else."""
        (root / "cc").mkdir(parents=True, exist_ok=True)
        (root / "cc" / "GOAL.md").write_text(body, encoding="utf-8")
        return _load(root=root).check_owed()

    def test_a_goal_doc_with_the_none_witness_and_no_probe_file_is_clean(self, tmp_path):
        """The state the empty-list limb prescribes ("say so in the goal doc and
        remove this file") must read clean, or nothing-owed can never land: until
        2026-09-26 the absent-file limb refused it too, so an empty list red one way
        and a removed file red the other. "Say so" is the `<!--owed:none-->`
        witness on a non-bullet line."""
        problems = self._goal_only(
            tmp_path,
            "# G\n\n## Still owed\n\n_Nothing owed at this handoff._ <!--owed:none-->\n"
            "\n## How close\n\ndone\n",
        )
        assert problems == []

    def test_nothing_owed_in_prose_without_the_witness_is_refused(self, tmp_path):
        """Clean is a presence: prose alone is an absence the parser cannot tell
        from a drifted heading."""
        problems = self._goal_only(
            tmp_path, "# G\n\n## Still owed\n\n_Nothing owed at this handoff._\n\n## How close\n\ndone\n"
        )
        assert len(problems) == 1 and "owed:none" in problems[0]

    def test_a_goal_doc_with_owed_bullets_and_no_probe_file_is_refused(self, tmp_path):
        """An owed bullet with no probe file is the unchecked list the limb exists for."""
        problems = self._goal_only(
            tmp_path, "# G\n\n## Still owed\n\n- item <!--owed:a-->\n\n## How close\n\ndone\n"
        )
        assert len(problems) == 1 and "is absent" in problems[0]

    def test_a_drifted_heading_cannot_hide_an_owed_marker_from_the_absent_file_limb(
        self, tmp_path
    ):
        """Driven 2026-09-26: a Title-Cased heading made `_goal_owed_ids` see no
        bullet, and with the probe file gone the owed item was green. The marker
        is what survives the drift, so a stray marker anywhere reds, even beside
        a `none` witness."""
        problems = self._goal_only(
            tmp_path,
            "# G\n\n## Still Owed\n\n- item <!--owed:a-->\n\n## Still owed\n\n"
            "_Nothing owed._ <!--owed:none-->\n\n## How close\n\ndone\n",
        )
        assert len(problems) == 1 and "is absent" in problems[0]

    def test_an_item_with_neither_cmd_nor_why_not_is_refused(self, tmp_path):
        self._write(tmp_path, [("u", "-")],
                    [{"id": "u", "cmd": None, "open_value": None, "why_not": None}])
        assert any("neither a `cmd` nor a `why_not`" in p
                   for p in _load(root=tmp_path).check_owed())

    def test_an_empty_cmd_is_not_a_declared_absence(self, tmp_path):
        """`cmd: ""` + any why_not silently disabled a probe."""
        self._write(tmp_path, [("e", "-")],
                    [{"id": "e", "cmd": "", "open_value": "True", "why_not": "looks declared"}])
        assert any("EMPTY `cmd`" in p for p in _load(root=tmp_path).check_owed())

    def test_a_declared_why_not_is_accepted(self, tmp_path):
        self._write(tmp_path, [("n", "-")],
                    [{"id": "n", "cmd": None, "open_value": None,
                      "why_not": "not derivable from this repo"}])
        assert _load(root=tmp_path).check_owed() == []

    def test_an_erroring_probe_is_not_read_as_done(self, tmp_path):
        self._write(tmp_path, [("b", "-")],
                    [{"id": "b", "cmd": "python3 -c \"raise SystemExit(3)\"",
                      "open_value": "True", "why_not": None}])
        problems = _load(root=tmp_path).check_owed()
        assert len(problems) == 1
        assert "could not be re-derived" in problems[0]
        assert not any("looks DONE" in p for p in problems)

    def test_bullets_are_counted_only_inside_the_owed_section(self, tmp_path):
        mod = _load(root=tmp_path)
        text = ("## Notes\n\n- not owed\n\n## Still owed\n\n"
                "- one <!--owed:x-->\n  - nested does not count\n- two <!--owed:y-->\n\n"
                "## How close\n\n- not owed either\n")
        assert mod._goal_owed_ids(text) == ["x", "y"]


class TestTheLiveOwedProbesAreSound:
    """The live probe file, not a fixture -- findings land in DATA as often as code."""

    def test_no_live_probe_swallows_its_oracles_failure(self):
        """A probe must not turn a tool failure into a confident verdict.

        The `push-main` probe originally read git's stdout with an `or 0`
        fallback and never checked its return code, so on a repo with no
        `origin`, a detached HEAD, or a differently-named branch it printed
        `False` -- and the gate told the operator to DELETE a live owed item.
        """
        probes = REPO_ROOT / "cc" / "GOAL_OWED.json"
        if not probes.is_file():
            pytest.skip("cc/GOAL_OWED.json is local session state")
        import json as _json
        for item in _json.loads(probes.read_text(encoding="utf-8"))["owed"]:
            cmd = item.get("cmd") or ""
            if "subprocess.run" not in cmd:
                continue
            assert "check=True" in cmd or "returncode" in cmd, (
                f"owed probe {item['id']!r} shells out but never inspects the "
                "exit status. An oracle that cannot run must report that, not "
                "answer -- see the 2026-09-01 push-main regression."
            )
            assert " or 0" not in cmd, (
                f"owed probe {item['id']!r} defaults its oracle's output. A "
                "default converts a failure into a definitive answer."
            )


class TestConditionalMembersFailClosed:
    """A member that runs only sometimes must never SKIP when it cannot decide.

    A silently-skipped gate is indistinguishable from a passing one, which is
    the same shape as the probe that reported a live item DONE because it read
    git's stdout without reading git's exit status. Conditional membership has
    that bug's blast radius multiplied by a whole test module, so the
    undeterminable case is pinned here rather than trusted.
    """

    def test_an_undeterminable_condition_runs_the_member(self):
        mod = _load()
        mod._session_changed_paths = lambda: None
        run, notes = mod._conditional_members()
        assert run, (
            "FAIL-OPEN: git could not report changed paths and the member was "
            "skipped. An unanswerable condition must run the gate."
        )
        assert any("unanswerable" in n for n in notes)

    def test_a_matching_change_runs_the_member(self):
        mod = _load()
        # One changed path per member: the census member watches tests/, the
        # recall-counts member watches the corpus roots.
        mod._session_changed_paths = lambda: ["tests/test_something_new.py",
                                             "memory/a-new-note.md"]
        run, _ = mod._conditional_members()
        assert run == list(mod.CONDITIONAL)

    def test_an_unrelated_change_skips_with_a_stated_reason(self):
        mod = _load()
        mod._session_changed_paths = lambda: ["README.md", "docs/X.md"]
        run, notes = mod._conditional_members()
        assert run == []
        assert any("skipped" in n and "nothing touched" in n for n in notes)

    def test_every_conditional_member_declares_triggers_and_a_reason(self):
        mod = _load()
        for path, value in mod.CONDITIONAL.items():
            why, triggers = value
            assert why and triggers, f"{path} has an empty reason or trigger set"
            assert (REPO_ROOT / path).is_file(), f"{path} does not resolve"

    def test_a_conditional_member_is_not_also_unconditional(self):
        """Otherwise the condition is decorative and the cost is never saved."""
        mod = _load()
        overlap = set(mod.CONDITIONAL) & set(mod.SELECTION)
        assert not overlap, f"{overlap} is in both SELECTION and CONDITIONAL"


class TestTheLocalCodenameArmMustExist:
    """DEF-708: the codename gate's local pattern file is gitignored, so its
    absence is a silent green for every term that lives only there. This arm
    is the one place that can say "not armed" instead of "nothing to enforce".
    A red only on the operator's tree (the owed arm's own tell: a goal doc at
    cc/GOAL.md); a printed note elsewhere, because a contributor's clone cannot
    recreate a file whose content is not theirs (the code-review lane drove
    the hard red on a public clone). Earn-the-red: absent and comments-only
    both report on the operator's tree; one pattern is clean and counted; a
    BOM'd comment line is not a pattern."""

    @staticmethod
    def _operator(root: Path) -> None:
        (root / "cc").mkdir(exist_ok=True)
        (root / "cc" / "GOAL.md").write_text("# G\n", encoding="utf-8")

    def test_an_absent_file_is_a_red_on_the_operator_tree(self, tmp_path):
        self._operator(tmp_path)
        problems = _load(root=tmp_path).check_local_codename_arm()
        assert len(problems) == 1 and "is absent" in problems[0], problems

    def test_an_absent_file_is_a_note_elsewhere(self, tmp_path):
        notes: list[str] = []
        assert _load(root=tmp_path).check_local_codename_arm(notes) == []
        assert len(notes) == 1 and "is absent" in notes[0] and "not the operator's" in notes[0]

    def test_a_comments_only_file_is_reported(self, tmp_path):
        self._operator(tmp_path)
        (tmp_path / ".local-codenames.txt").write_text("# nothing\n\n  \n", encoding="utf-8")
        problems = _load(root=tmp_path).check_local_codename_arm()
        assert len(problems) == 1 and "no patterns" in problems[0], problems

    def test_one_pattern_is_clean_and_the_count_is_printed(self, tmp_path):
        self._operator(tmp_path)
        (tmp_path / ".local-codenames.txt").write_text("# a comment\nzebra-\\d{3}\n", encoding="utf-8")
        notes: list[str] = []
        assert _load(root=tmp_path).check_local_codename_arm(notes) == []
        assert notes == ["local arm: 1 pattern(s) from .local-codenames.txt"]

    def test_a_bom_does_not_count_as_a_pattern(self, tmp_path):
        """Read as plain utf-8, `\\ufeff# only a comment` is not a comment and
        counts as one pattern -- a comments-only file reading armed."""
        self._operator(tmp_path)
        (tmp_path / ".local-codenames.txt").write_bytes(b"\xef\xbb\xbf# only a comment\n")
        problems = _load(root=tmp_path).check_local_codename_arm()
        assert len(problems) == 1 and "no patterns" in problems[0], problems

    def test_an_undecodable_file_is_a_red_everywhere(self, tmp_path):
        (tmp_path / ".local-codenames.txt").write_bytes(b"caf\xe9\n")
        problems = _load(root=tmp_path).check_local_codename_arm()
        assert len(problems) == 1 and "unreadable" in problems[0], problems

    def test_the_arm_reads_the_same_name_the_gate_does(self):
        """One string, three homes: the gate's constant, this script's, and the
        .gitignore row the gate pins. A rename in one place must red here."""
        mod = _load()
        gate = (REPO_ROOT / "tests" / "test_no_internal_codenames.py").read_text(encoding="utf-8")
        assert f'LOCAL_PATTERNS_REL = "{mod.LOCAL_CODENAMES}"' in gate

    def test_the_arm_runs_from_main_and_can_be_skipped(self, tmp_path, capsys):
        mod = _load(root=tmp_path)
        # --skip-wiring-arm: this tmp root carries no settings file, and that
        # arm's red is tested in its own class.
        others = ["--skip-tests", "--skip-trailer", "--skip-shape", "--skip-owed", "--skip-keys",
                  "--skip-wiring-arm"]
        assert mod.main(others) == 0  # not an operator tree: a note, clean
        assert "note: .local-codenames.txt is absent" in capsys.readouterr().out
        self._operator(tmp_path)
        assert mod.main(others) == 2
        assert "is absent" in capsys.readouterr().err
        (tmp_path / ".local-codenames.txt").write_text("zebra-\\d{3}\n", encoding="utf-8")
        assert mod.main(others) == 0
        out = capsys.readouterr().out
        assert "local arm: 1 pattern(s)" in out and "clean" in out
        assert mod.main([*others, "--skip-local-arm"]) == 2
        assert "NOTHING CHECKED" in capsys.readouterr().err


class TestCitedCandidateKeysResolveToTheLog:
    """The fourth arm (DEF-685). A handoff row cited five reflect-candidate keys
    as "logged as proposals"; zero were in the candidate log, the pass had only
    printed them, and the next session's pass -- which re-proposes from the log
    alone -- printed none. A key in the memory row is a claim about a file, so
    this arm reads the file. Cases are written to pin exact problem counts so a
    spurious extra reds too.
    """

    @staticmethod
    def _write(root: Path, rows, log_rows=None) -> None:
        """``rows`` are Session Log lines; ``log_rows`` are (key, disposition)
        pairs for the candidate log, or None for no log at all."""
        import json as _json
        body = ("# M\n\n## Session Log\n\n| Date | Summary | Next |\n|---|---|---|\n"
                + "\n".join(rows) + "\n")
        (root / "ESPALIER_MEMORY.md").write_text(body, encoding="utf-8")
        if log_rows is not None:
            log = root / ".espalier" / "memory_candidate_log.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                "".join(_json.dumps({"key": k, "disposition": d}) + "\n" for k, d in log_rows),
                encoding="utf-8",
            )

    def test_no_memory_doc_means_nothing_to_check(self, tmp_path):
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_a_cited_key_with_no_log_row_is_flagged(self, tmp_path):
        self._write(tmp_path, ["| 2026-09-04 | **X.** Five reflect keys logged as proposals: ce8174fe9fd9. | -- |"],
                    log_rows=[])
        problems = _load(root=tmp_path).check_candidate_keys()
        assert len(problems) == 1
        assert "ce8174fe9fd9" in problems[0]
        assert "has no row for it" in problems[0]

    def test_an_absent_log_is_a_note_not_a_red(self, tmp_path):
        """The log is machine-local and gitignored. A fresh clone or a second
        worktree cannot verify a claim the authoring tree logged, and a red
        there would ask the author to falsify the record or the log. The
        failure this arm exists for had a log PRESENT and rows missing; the
        module's convention for a missing canon (see ``canonical_trailer``)
        is to stand down and say so, not to red."""
        self._write(tmp_path, ["| 2026-09-04 | **X.** key ce8174fe9fd9 held. | -- |"])
        notes: list[str] = []
        assert _load(root=tmp_path).check_candidate_keys(notes) == []
        assert len(notes) == 1
        assert "is absent on this tree" in notes[0]
        assert "--skip-keys" in notes[0]

    def test_a_key_logged_under_an_unreadable_disposition_is_flagged(self, tmp_path):
        # Presence alone is the born-weak shape: `hold` is in the log, the pass
        # reads only promoted/updated/skipped/held, and the hold is lost with
        # the row sitting right there.
        self._write(tmp_path, ["| 2026-09-04 | **X.** key ce8174fe9fd9 held. | -- |"],
                    log_rows=[("ce8174fe9fd9", "hold")])
        problems = _load(root=tmp_path).check_candidate_keys()
        assert len(problems) == 1
        assert "under disposition `hold`" in problems[0]
        assert "cannot read" in problems[0]

    def test_the_context_vocabulary_carries_every_disposition_name(self, tmp_path):
        # Derived from the pass at call time; pinned here by the literal names
        # (the literal sibling of the enum lives in test_reflect_memory_candidates).
        mod = _load(root=tmp_path)
        context = mod._key_context_re(mod._dispositions())
        for word in ("promoted", "updated", "skipped", "held", "promotions", "reflect", "logged"):
            assert context.search(f"x {word} y"), word

    def test_a_promotion_sentence_is_a_claim_about_the_log(self, tmp_path):
        # The shape a handoff actually writes, with none of the original words.
        self._write(tmp_path, ["| 2026-09-04 | **X.** Reflect: two promotions (8c0c57061b76), eight skipped. | -- |"],
                    log_rows=[])
        problems = _load(root=tmp_path).check_candidate_keys()
        assert len(problems) == 1
        assert "8c0c57061b76" in problems[0]

    def test_a_dated_row_outside_the_session_log_does_not_win(self, tmp_path):
        import json as _json
        body = ("# M\n\n## Session Log\n\n| Date | Summary | Next |\n|---|---|---|\n"
                "| 2026-09-04 | **NEW.** nothing cited. | -- |\n\n"
                "## Harness Decisions\n\n| Date | Decision |\n|---|---|\n"
                "| 2027-01-01 | key aaaaaaaaaaaa logged |\n")
        (tmp_path / "ESPALIER_MEMORY.md").write_text(body, encoding="utf-8")
        log = tmp_path / ".espalier" / "memory_candidate_log.jsonl"
        log.parent.mkdir(parents=True); log.write_text("", encoding="utf-8")
        assert _load(root=tmp_path).check_candidate_keys() == []
        assert _json  # keep the import shape identical to the sibling helper

    def test_a_known_ledger_row_sha_is_not_a_key(self, tmp_path):
        import json as _json
        self._write(tmp_path, ["| 2026-09-04 | **X.** the probe's key row_sha re-pinned to 697c2e1513f0. | -- |"],
                    log_rows=[])
        (tmp_path / "task-packs").mkdir()
        (tmp_path / "task-packs" / "LEDGER_PROBES.json").write_text(
            _json.dumps({"probes": [{"id": "DEF-1", "row_sha": "697c2e1513f0"}]}), encoding="utf-8")
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_the_problem_names_the_way_out_for_a_non_key_token(self, tmp_path):
        self._write(tmp_path, ["| 2026-09-04 | **X.** the candidate keys landed upstream in aa11bb22cc33. | -- |"],
                    log_rows=[])
        problems = _load(root=tmp_path).check_candidate_keys()
        assert len(problems) == 1
        assert "--skip-keys" in problems[0]
        assert "row_sha" in problems[0]

    def test_each_missing_key_is_its_own_problem(self, tmp_path):
        self._write(tmp_path, ["| 2026-09-04 | **X.** keys ce8174fe9fd9 13cc1e7faaf0 logged; 280753a0016d too. | -- |"],
                    log_rows=[("13cc1e7faaf0", "skipped")])
        problems = _load(root=tmp_path).check_candidate_keys()
        assert len(problems) == 2
        assert "ce8174fe9fd9" in problems[0]
        assert "280753a0016d" in problems[1]

    def test_a_held_row_satisfies_the_citation(self, tmp_path):
        self._write(tmp_path, ["| 2026-09-04 | **X.** key ce8174fe9fd9 held for review. | -- |"],
                    log_rows=[("ce8174fe9fd9", "held")])
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_only_the_newest_row_by_date_is_read(self, tmp_path):
        # An older row's dead key is history; the newest row is the claim the
        # handoff just made. Position is not recency: the old row sits on top.
        self._write(tmp_path, ["| 2026-09-01 | **OLD.** key aaaaaaaaaaaa logged. | -- |",
                               "| 2026-09-04 | **NEW.** nothing cited. | -- |"], log_rows=[])
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_same_day_rows_read_the_topmost_as_newest(self, tmp_path):
        # /handoff prepends, so of two same-day rows the topmost is the newest.
        self._write(tmp_path, ["| 2026-09-04 | **NEWER.** nothing cited. | -- |",
                               "| 2026-09-04 | **OLDER.** key aaaaaaaaaaaa logged. | -- |"], log_rows=[])
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_a_hex_token_with_no_candidate_context_is_not_a_key(self, tmp_path):
        # A ledger row_sha, re-pinned in prose: twelve hex, no claim about the log.
        self._write(tmp_path, ["| 2026-09-04 | **X.** probe row_sha re-pinned 697c2e1513f0 -> 76d69156b6dd. | -- |"],
                    log_rows=[])
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_a_longer_hex_run_is_not_a_key(self, tmp_path):
        # A full sha256 contains many 12-hex windows; none of them is a key.
        sha = "a" * 64
        self._write(tmp_path, [f"| 2026-09-04 | **X.** the candidate file hashed to {sha}. | -- |"],
                    log_rows=[])
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_a_commit_abbreviation_is_not_a_key(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], cwd=tmp_path, check=True)
        sha12 = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=tmp_path,
                               capture_output=True, text=True, check=True, encoding="utf-8").stdout.strip()
        assert len(sha12) == 12
        self._write(tmp_path, [f"| 2026-09-04 | **X.** the candidate keys landed in commit {sha12}. | -- |"],
                    log_rows=[])
        assert _load(root=tmp_path).check_candidate_keys() == []

    def test_the_arm_runs_from_main_and_can_be_skipped(self, tmp_path, capsys):
        self._write(tmp_path, ["| 2026-09-04 | **X.** key ce8174fe9fd9 logged. | -- |"], log_rows=[])
        mod = _load(root=tmp_path)
        # --skip-local-arm: this tmp root carries no local codename file, and
        # that arm's red is tested in its own class.
        others = ["--skip-tests", "--skip-trailer", "--skip-shape", "--skip-owed", "--skip-local-arm",
                  "--skip-wiring-arm"]
        assert mod.main(others) == 2
        assert "ce8174fe9fd9" in capsys.readouterr().err
        # An absent log surfaces as a printed note and a clean exit.
        (tmp_path / ".espalier" / "memory_candidate_log.jsonl").unlink()
        assert mod.main(others) == 0
        assert "note:" in capsys.readouterr().out
        assert mod.main([*others, "--skip-keys"]) == 2
        assert "NOTHING CHECKED" in capsys.readouterr().err


class TestChangelogRecordsOnTheRecordRef:
    """CHANGELOG.md's "the record itself is kept, unedited, in the maintainers'
    tree" has one mechanism behind it, handoff step 7b. On the operator's tree
    a parked record the ``record`` ref cannot resolve is a red that names the
    snapshot run; on any other tree it is a note."""

    _REC = "task-packs/Done/CHANGELOG_archive_20990101.md"

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        rec = repo / self._REC
        rec.parent.mkdir(parents=True)
        rec.write_text("# record\n", encoding="utf-8")
        return repo

    @pytest.mark.slow
    def test_operator_tree_reds_until_the_record_ref_carries_the_file(self, tmp_path):
        repo = self._repo(tmp_path)
        (repo / "cc").mkdir()
        (repo / "cc" / "GOAL.md").write_text("# goal\n", encoding="utf-8")
        mod = _load(root=repo)

        notes: list[str] = []
        problems = mod.check_changelog_records_on_record_branch(notes)
        assert len(problems) == 1, problems
        assert "CHANGELOG_archive_20990101.md" in problems[0]
        assert "record_snapshot.py" in problems[0]

        # A ref named `record` carrying the file at its repo path resolves
        # exactly as the orphan snapshot ref does.
        subprocess.run(["git", "checkout", "-q", "--orphan", "record"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-f", self._REC], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "record"], cwd=repo, check=True)
        notes = []
        assert mod.check_changelog_records_on_record_branch(notes) == []
        assert any("all on record" in n for n in notes), notes

    @pytest.mark.slow
    def test_a_tree_that_is_not_the_operators_gets_a_note(self, tmp_path):
        repo = self._repo(tmp_path)
        mod = _load(root=repo)
        notes: list[str] = []
        assert mod.check_changelog_records_on_record_branch(notes) == []
        assert any("not the operator" in n for n in notes), notes

    def test_no_parked_record_is_a_note_not_a_red(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / "cc").mkdir()
        (repo / "cc" / "GOAL.md").write_text("# goal\n", encoding="utf-8")
        mod = _load(root=repo)
        notes: list[str] = []
        assert mod.check_changelog_records_on_record_branch(notes) == []
        assert any("none parked" in n for n in notes), notes


class TestMessageShape:
    """A commit message is an email to someone who has never seen this repo's
    packs or ledger: subject at most 72 characters, no internal id anywhere in
    the prose. The gate reads every unmerged commit beneath the rev, skips
    merge commits (GitHub writes their subjects) and exempts trailer lines."""

    @staticmethod
    def _git(repo: Path, *args: str, **kw) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, **kw)

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "r"
        repo.mkdir()
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@t.com")
        self._git(repo, "config", "user.name", "T")
        # A one-row ledger, so the DEF prefix is derived here as it is on the
        # real tree rather than assumed.
        ledger = repo / "task-packs" / "FORWARD_LEDGER.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("| `DEF-1` | seeded |\n", encoding="utf-8")
        return repo

    def _commit(self, repo: Path, message: str, name: str = "f.txt") -> None:
        path = repo / name
        path.write_text(path.read_text(encoding="utf-8") + "x" if path.exists() else "x",
                        encoding="utf-8")
        self._git(repo, "add", name)
        self._git(repo, "commit", "-q", "-F", "-", input=message, text=True, encoding="utf-8")

    _CLEAN = (
        "fix(tests): import pytest in the ledger-wiring tests\n\n"
        "The skip path called pytest.skip without the import, so a tree without\n"
        "node raised NameError instead of skipping.\n\n"
        "Co-Authored-By: Right <right@x.dev>\n"
        "Claude-Session: https://claude.ai/code/session_0123456789\n"
    )

    @pytest.mark.slow
    def test_a_clean_message_passes(self, tmp_path):
        repo = self._repo(tmp_path)
        self._commit(repo, self._CLEAN)
        assert _load(root=repo).check_message_shape("HEAD") == []

    @pytest.mark.slow
    def test_a_subject_past_72_is_reported_with_its_length(self, tmp_path):
        repo = self._repo(tmp_path)
        subject = "docs(memory): " + "x" * 80
        self._commit(repo, subject + "\n\nbody\n")
        problems = _load(root=repo).check_message_shape("HEAD")
        assert len(problems) == 1, problems
        assert str(len(subject)) in problems[0] and "72" in problems[0]
        # The remedy amends without the rest of the index: a bare `--amend`
        # takes a change left staged by a path-limited commit into the fix-up,
        # and from a tool call the editor keeps the old message, so `-F`.
        assert "git commit --amend --only -F" in problems[0], problems[0]

    @pytest.mark.slow
    def test_a_subject_after_leading_blank_lines_is_still_the_subject(self, tmp_path):
        repo = self._repo(tmp_path)
        self._commit(repo, "\n\n" + "fix: " + "y" * 80 + "\n")
        problems = _load(root=repo).check_message_shape("HEAD")
        assert len(problems) == 1 and "72" in problems[0], problems

    @pytest.mark.slow
    @pytest.mark.parametrize("where, message, expected", [
        ("subject", "docs(packs): TP-459, fold the two reviews\n\nbody\n", "TP-459"),
        ("body", "fix: the thing\n\nCloses DEF-892 and the round-7 leftover.\n", "DEF-892"),
    ])
    def test_an_internal_id_anywhere_in_the_prose_is_named(self, tmp_path, where, message, expected):
        repo = self._repo(tmp_path)
        self._commit(repo, message)
        problems = _load(root=repo).check_message_shape("HEAD")
        assert len(problems) == 1, (where, problems)
        assert expected in problems[0], problems[0]

    def test_a_long_id_is_reported_once_never_as_its_truncated_twin(self):
        pats = _load()._internal_id_patterns()
        found = _load()._maximal_matches(pats, "docs(packs): TP-459 and TP-2000 folded")
        assert found == ["TP-2000", "TP-459"], found

    @pytest.mark.slow
    def test_trailer_lines_are_exempt_from_the_id_scan_in_any_case(self, tmp_path):
        repo = self._repo(tmp_path)
        message = (self._CLEAN.replace("Co-Authored-By:", "Co-authored-by:")
                   + "Signed-off-by: TP-1 Bot <bot@x.dev>\n")
        self._commit(repo, message)
        assert _load(root=repo).check_message_shape("HEAD") == []

    @pytest.mark.slow
    def test_every_unmerged_commit_on_the_branch_is_read(self, tmp_path):
        repo = self._repo(tmp_path)
        self._commit(repo, "chore: base\n")
        self._git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self._commit(repo, "feat: " + "z" * 90 + "\n", name="a.txt")
        bad = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout.strip()
        self._commit(repo, "chore: a clean follow-up\n", name="b.txt")
        problems = _load(root=repo).check_message_shape("HEAD")
        assert len(problems) == 1 and bad[:12] in problems[0], problems

    @pytest.mark.slow
    def test_a_merge_commit_is_skipped_with_a_note(self, tmp_path):
        repo = self._repo(tmp_path)
        self._commit(repo, "chore: base\n")
        self._git(repo, "switch", "-q", "-c", "topic")
        self._commit(repo, "feat: on the branch\n", name="t.txt")
        self._git(repo, "switch", "-q", "-")
        self._git(repo, "merge", "-q", "--no-ff", "topic", "-m",
                  "Merge pull request #24 from " + "w" * 70)
        notes: list[str] = []
        assert _load(root=repo).check_message_shape("HEAD", notes) == []
        assert any("merge commit, skipped" in n for n in notes), notes

    def test_the_ledger_prefixes_are_derived_from_the_ledger_itself(self):
        """DEF, DEC, INV and EXP are all live prefixes; a hand-kept list of five
        missed forty-one INV-/EXP- ids before this derivation (2026-09-27)."""
        mod = _load()
        prefixes = mod.ledger_prefixes()
        assert {"DEF", "DEC", "INV", "EXP"} <= prefixes, prefixes
        pats = mod._internal_id_patterns()
        assert mod._maximal_matches(pats, "Closes INV-12 and EXP-3.") == ["EXP-3", "INV-12"]
        assert mod._maximal_matches(pats, "pin encoding to UTF-8; SHA-256; PEP-440") == []

    def test_the_vocabulary_is_derived_from_its_owners(self):
        from espalier.provenance_census import PROVENANCE_RE
        from espalier.surface_hygiene import SPECIFIC_ID_RE

        pats = _load()._internal_id_patterns()
        assert PROVENANCE_RE in pats and SPECIFIC_ID_RE in pats
        assert len(pats) == 3

    @pytest.mark.slow
    def test_the_arm_runs_from_main_and_can_be_skipped(self, tmp_path, capsys):
        repo = self._repo(tmp_path)
        others = ["--skip-tests", "--skip-trailer", "--skip-owed", "--skip-keys",
                  "--skip-local-arm", "--skip-wiring-arm"]
        self._commit(repo, "chore: a clean subject\n")
        mod = _load(root=repo)
        assert mod.main(others) == 0
        assert "clean" in capsys.readouterr().out
        self._commit(repo, "chore: " + "q" * 80 + "\n", name="g.txt")
        assert mod.main(others) == 2
        assert "subject is" in capsys.readouterr().err
        assert mod.main([*others, "--skip-shape"]) == 2
        assert "NOTHING CHECKED" in capsys.readouterr().err

    def test_the_subject_limit_prose_names_the_gates_number(self):
        """Four documents state the limit in prose; a flip of SUBJECT_MAX reds
        here until each says the new number."""
        limit = str(_load().SUBJECT_MAX)
        for rel in (".claude/commands/commit.md", ".claude/commands/handoff.md",
                    "memory/task-packs.md", "memory/commit-messages-must-stand-alone.md"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert limit in text, f"{rel} does not state the {limit}-character limit"


class TestALinkedWorktreeOfTheOperatorsTreeIsTheOperators:
    """DEF-1137: the operator-tree tell is the gitignored ``cc/GOAL.md``, and a
    linked worktree (``git worktree add``; a Claude Code worktree) checks out
    tracked files only -- so from one, the codename arm, the changelog-record
    arm and the candidate-key arm read the operator's own session as a
    reviewer's clone and demote their reds to notes. One oracle,
    ``_operator_root``, lets the main checkout's tell count for its worktrees,
    and each gitignored input is read where this session could have written
    it: the gate read the worktree's own codename file, so that red stands
    until the file is copied; the candidate log of a session that entered the
    worktree mid-session is the main checkout's, so it is read there."""

    @staticmethod
    def _repo(tmp_path: Path, *, operator: bool) -> tuple[Path, Path]:
        main = tmp_path / "main"
        main.mkdir()

        def git(*argv: str) -> None:
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                 "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", *argv],
                cwd=main, capture_output=True, text=True, encoding="utf-8", check=True,
            )

        git("init", "-q")
        (main / "a.txt").write_text("a\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-qm", "a")
        if operator:
            (main / "cc").mkdir()
            (main / "cc" / "GOAL.md").write_text("# G\n", encoding="utf-8")  # untracked, as the tell is
        wt = tmp_path / "wt"
        git("worktree", "add", "-q", str(wt))
        return main, wt

    def test_the_oracle_answers_the_main_checkouts_tell_for_its_worktree(self, tmp_path):
        main, wt = self._repo(tmp_path, operator=True)
        assert _load(root=wt)._operator_root() == main.resolve()
        assert _load(root=main)._operator_root() == main
        assert _load(root=tmp_path)._operator_root() is None  # no checkout and no tell

    def test_a_worktree_of_a_tree_without_the_tell_is_nobodys(self, tmp_path):
        _main, wt = self._repo(tmp_path, operator=False)
        mod = _load(root=wt)
        assert mod._operator_root() is None
        notes: list[str] = []
        assert mod.check_local_codename_arm(notes) == []
        assert len(notes) == 1 and "not the operator's" in notes[0], notes

    def test_the_codename_arm_reds_from_the_worktree_and_says_what_to_copy(self, tmp_path):
        main, wt = self._repo(tmp_path, operator=True)
        problems = _load(root=wt).check_local_codename_arm()
        assert len(problems) == 1 and "is absent" in problems[0], problems
        assert "linked worktree" in problems[0] and str(main.resolve()) in problems[0], problems
        assert "copy" in problems[0], problems

    def test_the_main_checkouts_codename_file_does_not_arm_the_worktree(self, tmp_path):
        main, wt = self._repo(tmp_path, operator=True)
        (main / ".local-codenames.txt").write_text("zebra-\\d{3}\n", encoding="utf-8")
        problems = _load(root=wt).check_local_codename_arm()
        assert len(problems) == 1 and "is absent" in problems[0], problems
        (wt / ".local-codenames.txt").write_text("zebra-\\d{3}\n", encoding="utf-8")
        notes: list[str] = []
        assert _load(root=wt).check_local_codename_arm(notes) == []
        assert notes == ["local arm: 1 pattern(s) from .local-codenames.txt"]

    def test_the_owed_arm_says_where_the_goal_lives_from_the_worktree(self, tmp_path):
        """The fourth tell-reader cannot grade a list it cannot read (its probes
        run against this tree), so it says where the list lives instead of
        falling silent; elsewhere an absent goal stays the quiet skip."""
        main, wt = self._repo(tmp_path, operator=True)
        notes: list[str] = []
        assert _load(root=wt).check_owed(notes) == []
        assert len(notes) == 1 and str(main.resolve()) in notes[0], notes
        assert "not checked from this worktree" in notes[0], notes
        quiet: list[str] = []
        assert _load(root=tmp_path).check_owed(quiet) == [] and quiet == []

    def test_the_changelog_record_arm_reds_from_the_worktree(self, tmp_path):
        _main, wt = self._repo(tmp_path, operator=True)
        rec = wt / "task-packs" / "Done" / "CHANGELOG_archive_20990101.md"
        rec.parent.mkdir(parents=True)
        rec.write_text("# record\n", encoding="utf-8")
        problems = _load(root=wt).check_changelog_records_on_record_branch()
        assert len(problems) == 1 and "record_snapshot.py" in problems[0], problems

    def test_the_candidate_arm_reads_the_main_checkouts_log_when_the_worktree_has_none(self, tmp_path):
        import json as _json

        main, wt = self._repo(tmp_path, operator=True)
        TestCitedCandidateKeysResolveToTheLog._write(
            wt, ["| 2026-09-04 | **X.** key ce8174fe9fd9 held. | -- |"]
        )
        log = main / ".espalier" / "memory_candidate_log.jsonl"
        log.parent.mkdir()
        log.write_text("", encoding="utf-8")
        problems = _load(root=wt).check_candidate_keys()
        assert len(problems) == 1 and "has no row for it" in problems[0], problems
        log.write_text(_json.dumps({"key": "ce8174fe9fd9", "disposition": "held"}) + "\n", encoding="utf-8")
        notes: list[str] = []
        assert _load(root=wt).check_candidate_keys(notes) == []
        assert notes == [], notes

    def test_the_worktrees_own_log_is_read_first(self, tmp_path):
        """A session launched inside the worktree logs there; its own log wins
        over the main checkout's."""
        import json as _json

        main, wt = self._repo(tmp_path, operator=True)
        TestCitedCandidateKeysResolveToTheLog._write(
            wt, ["| 2026-09-04 | **X.** key ce8174fe9fd9 held. | -- |"],
            log_rows=[("ce8174fe9fd9", "held")],
        )
        (main / ".espalier").mkdir()
        (main / ".espalier" / "memory_candidate_log.jsonl").write_text(
            _json.dumps({"key": "ce8174fe9fd9", "disposition": "hold"}) + "\n", encoding="utf-8"
        )
        assert _load(root=wt).check_candidate_keys() == []


class TestTheHookWiringArm:
    """2026-10-08: two sessions launched in a Claude Code worktree of this repo
    ran with no hooks at all -- ``/hooks`` listed none, no banner, no guard, no
    stop gate -- because the gitignored ``.claude/settings.json`` is not checked
    out into a worktree and Claude Code reads it from the session's primary
    working directory. No hook can report its own absence, so the landing check
    asks. Earn-the-red: an absent file reds on the operator's tree and its linked
    worktree (mutation: treat absent as nothing to check); a file that wires no
    gate reds (mutation: check presence only); a wired file is clean; a checker
    that raises is a red, never a pass (mutation: swallow the error as clean)."""

    _WIRED = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{
        "type": "command", "command": "python",
        "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
    }]}]}}

    @staticmethod
    def _operator(root: Path) -> None:
        (root / "cc").mkdir(exist_ok=True)
        (root / "cc" / "GOAL.md").write_text("# G\n", encoding="utf-8")

    @staticmethod
    def _gate(root: Path) -> None:
        """One blocking gate on disk, so ci_guard's check has a gate to require."""
        hooks = root / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "write_guard.py").write_text("", encoding="utf-8")

    @staticmethod
    def _settings(root: Path, data: dict) -> None:
        path = root / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_an_absent_settings_file_is_a_red_on_the_operator_tree(self, tmp_path):
        self._operator(tmp_path)
        problems = _load(root=tmp_path).check_hook_wiring_arm()
        assert len(problems) == 1 and "is absent" in problems[0], problems
        assert "loads none of the harness's hooks" in problems[0], problems

    def test_an_absent_settings_file_is_a_note_elsewhere(self, tmp_path):
        notes: list[str] = []
        assert _load(root=tmp_path).check_hook_wiring_arm(notes) == []
        assert len(notes) == 1 and "is absent" in notes[0] and "not the operator's" in notes[0]

    def test_a_linked_worktree_says_what_to_copy_from_where(self, tmp_path):
        main, wt = TestALinkedWorktreeOfTheOperatorsTreeIsTheOperators._repo(tmp_path, operator=True)
        problems = _load(root=wt).check_hook_wiring_arm()
        assert len(problems) == 1 and "is absent" in problems[0], problems
        assert str(main.resolve() / ".claude" / "settings.json") in problems[0], problems
        assert ".worktreeinclude" in problems[0], problems

    def test_a_file_that_wires_no_gate_is_a_red_naming_the_gate(self, tmp_path):
        self._operator(tmp_path)
        self._gate(tmp_path)
        self._settings(tmp_path, {"permissions": {}})
        problems = _load(root=tmp_path).check_hook_wiring_arm()
        assert len(problems) == 1 and "write_guard.py" in problems[0], problems
        assert "does not wire every gate" in problems[0], problems

    def test_a_wired_file_is_clean_and_says_so(self, tmp_path):
        self._operator(tmp_path)
        self._gate(tmp_path)
        self._settings(tmp_path, self._WIRED)
        notes: list[str] = []
        assert _load(root=tmp_path).check_hook_wiring_arm(notes) == []
        assert notes == ["wiring arm: .claude/settings.json wires every blocking gate on disk"]

    def test_a_checker_that_raises_is_a_red_not_a_pass(self, tmp_path):
        self._settings(tmp_path, self._WIRED)
        mod = _load(root=tmp_path)

        def _broken():
            raise ImportError("ci_guard moved")

        mod._ci_guard = _broken
        problems = mod.check_hook_wiring_arm()
        assert len(problems) == 1 and "unverified" in problems[0], problems

    def test_the_arm_runs_from_main_and_can_be_skipped(self, tmp_path, capsys):
        mod = _load(root=tmp_path)
        others = ["--skip-tests", "--skip-trailer", "--skip-shape", "--skip-owed", "--skip-keys",
                  "--skip-local-arm"]
        assert mod.main(others) == 0  # not an operator tree: a note, clean
        assert "note: .claude/settings.json is absent" in capsys.readouterr().out
        self._operator(tmp_path)
        assert mod.main(others) == 2
        assert "is absent" in capsys.readouterr().err
        self._gate(tmp_path)
        self._settings(tmp_path, self._WIRED)
        assert mod.main(others) == 0
        assert "wiring arm:" in capsys.readouterr().out
        assert mod.main([*others, "--skip-wiring-arm"]) == 2
        assert "NOTHING CHECKED" in capsys.readouterr().err

    def test_every_worktreeinclude_path_is_gitignored_and_settings_is_listed(self):
        """Claude Code copies only a path that matches ``.worktreeinclude`` AND is
        gitignored (code.claude.com/docs/en/worktrees, read 2026-10-08), so a
        listed path that git tracks is copied never, silently. The settings file
        is the line the arm's remedy names."""
        include = REPO_ROOT / ".worktreeinclude"
        if not (REPO_ROOT / ".git").exists():
            pytest.skip("not a git checkout (an extracted archive): check-ignore cannot answer")
        lines = [ln.strip() for ln in include.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        assert _load().SETTINGS_REL in lines, lines
        for rel in lines:
            probe = subprocess.run(["git", "check-ignore", "-q", rel],
                                   cwd=REPO_ROOT, capture_output=True, text=True)
            assert probe.returncode == 0, f"{rel} is listed in .worktreeinclude but not gitignored"
