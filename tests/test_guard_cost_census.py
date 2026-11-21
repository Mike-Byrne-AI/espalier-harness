"""``scripts/guard_cost_census.py``, TP-707's instrument (1-A): its statistics on
fixed inputs, the compile proxy on fixture hooks folders whose counts are known,
one real ``--calls 1`` row per kind against this checkout's guard (the decision
only, never a time), a fixture guard whose decisions are not a cost, the cache
and tree reads, and the box lock: a run behind a held lock waits and names its
holder, one inside the holder pair passes through, a free one is taken, recorded
while held and cleared, and what it writes is ``tests/_box_lock.py``'s shape.

Every spawn strips ``ESPALIER_BOX_LOCK`` and ``ESPALIER_BOX_LOCK_HOLDER`` from
the child's environment and sets them only to a fixture lock of its own, so a
run under a seat's tier never queues behind that tier, or another seat's, on the
real box lock.
"""
# slow-exempt: about twenty census children, the guard rows each spawning the guard once or twice (about 0.3 s each on the Air)
from __future__ import annotations

import importlib.util
import io
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest

from tests import _box_lock
from tests._interpreter_hosts import HOOK_PYTHON
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "guard_cost_census.py"
_CHILD_S = 30
_BUDGET_SKIP = ("the guard ran out of its time budget on this runner: a load reading, "
                "not a census defect (the deadline is the guard's, TP-707 Scope out)")


def _load_census() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("guard_cost_census_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _load_census()


def _run(*args: str, extra_env: dict | None = None, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in (_box_lock.LOCK_KEY, _box_lock.HOLDER_KEY, _box_lock.WAIT_KEY)}
    env.update(extra_env or {})
    return subprocess.run([HOOK_PYTHON, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(cwd), timeout=scaled(_CHILD_S))


class TestSummarize:
    def test_eight_values_read_their_median_and_inclusive_quartiles(self):
        assert census.summarize([5.0, 1.0, 8.0, 3.0, 2.0, 7.0, 4.0, 6.0]) == {
            "n": 8, "median": 4.5, "q1": 2.75, "q3": 6.25, "min": 1.0, "max": 8.0}

    def test_five_values_read_their_median_and_inclusive_quartiles(self):
        assert census.summarize([10.0, 30.0, 20.0, 50.0, 40.0]) == {
            "n": 5, "median": 30.0, "q1": 20.0, "q3": 40.0, "min": 10.0, "max": 50.0}

    def test_two_values_keep_their_quartiles_inside_min_and_max(self):
        got = census.summarize([46.8, 50.0])
        assert got["min"] <= got["q1"] <= got["q3"] <= got["max"], got

    def test_one_value_is_its_own_median_and_quartiles(self):
        assert census.summarize([7.5]) == {"n": 1, "median": 7.5, "q1": 7.5, "q3": 7.5, "min": 7.5, "max": 7.5}

    def test_no_values_read_none(self):
        assert census.summarize([]) == {"n": 0, "median": None, "q1": None, "q3": None, "min": None, "max": None}


class TestDecision:
    def _deny(self, reason: str) -> str:
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": reason}})

    def test_an_empty_exit_zero_is_an_allow(self):
        assert census.decision("read", 0, "") == "allow"

    def test_a_checkpoint_deny_is_a_nudge_named_by_its_id(self):
        assert census.decision("bash", 0, self._deny("[CP-RMRF] a recursive delete: re-issue to proceed")) == "nudge CP-RMRF"

    def test_a_deny_at_the_deadline_names_the_budget(self):
        reason = "Command blocked: write_guard ran out of its 4.0 s time budget before it had judged this command"
        assert census.decision("bash", 0, self._deny(reason)) == "deny (time budget)"

    def test_a_deny_with_no_checkpoint_is_a_deny(self):
        assert census.decision("bash", 0, self._deny("Command blocked: a protected zone")) == "deny"

    @pytest.mark.parametrize("reason", [
        "write_guard internal error (TypeError at tools/cc/hooks/_bash_patterns.py:4560); failing closed.",
        "write_guard internal error while it ran its judging child; failing closed.",
        "write_guard cannot start: tools/cc/hooks/_hook_utils.py raised SyntaxError at line 3",
        "write_guard cannot run here. The harness does not run on Python 3.10.",
    ], ids=["crash-guard", "runner", "start", "floor"])
    def test_a_deny_the_guard_gave_as_it_failed_is_a_crash(self, reason):
        """DEF-2096: the guard judged nothing, so the row's time is no
        judgment's cost (every template is driven in
        tests/test_benchmark_pass_conditions.py::TestACrashIsNoVerdict)."""
        assert census.decision("bash", 0, self._deny(reason)) == "deny (crash)"
        assert census.decision("bash", 0, self._deny(f"Command blocked, quoting: {reason}")) == "deny"

    def test_output_that_is_not_one_object_is_unreadable(self):
        assert (census.decision("read", 0, "[1, 2]"), census.decision("read", 0, "not json")) == (
            "unreadable output", "unreadable output")

    def test_exit_two_is_a_block_and_another_exit_an_error(self):
        assert (census.decision("bash", 2, ""), census.decision("bash", 1, "")) == ("block (exit 2)", "error (exit 1)")

    def test_the_control_reads_its_exit(self):
        assert census.decision("control", 0, "") == "exit 0"


def _fixture_hooks(root: Path, *, write_guard: str | None) -> Path:
    """Two tiny pattern modules: four distinct compiles keyed by pattern and
    flags (``plain`` twice under two flags, and once more under the first,
    which is no new key), 28 characters, two of them embedding the 7-character
    fragment. ``write_guard`` is that file's text, or none is written."""
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "_bash_patterns.py").write_text(
        "import re\n"
        "_CMD_POS_NO_VERB = '(?:^|;)'\n"
        "_CMD_POS = _CMD_POS_NO_VERB + 'x'\n"
        "A = re.compile(_CMD_POS_NO_VERB + 'rm')\n"
        "B = re.compile('plain')\n", encoding="utf-8")
    (hooks / "_speedbump.py").write_text(
        "import re\n"
        "import _bash_patterns\n"
        "C = re.compile(_bash_patterns._CMD_POS_NO_VERB + 'mv', re.I)\n"
        "D = re.compile('plain', re.I)\n"
        "E = re.compile('plain')\n", encoding="utf-8")
    if write_guard is not None:
        (hooks / "write_guard.py").write_text(write_guard, encoding="utf-8")
    return root


_FIGURES = ("method", "loader_ran", "fragment_found", "patterns", "compiled_chars", "hooks_patterns", "hooks_chars",
            "fragment_len", "cmd_pos_len", "embedding_patterns", "embedding_chars")


class TestCompile:
    def _compile(self, root: Path) -> dict:
        proc = _run("--compile", "--root", str(root), "--json")
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout)["compile"]
        assert sorted(Path(m).name for m in got["modules"]) == sorted(
            p.name for p in (root / "tools" / "cc" / "hooks").glob("_*.py"))
        return {k: got[k] for k in _FIGURES}

    def test_two_modules_read_their_known_counts(self, tmp_path):
        assert self._compile(_fixture_hooks(tmp_path, write_guard=None)) == {
            "method": "the two pattern modules imported; this tree has no write_guard.py",
            "loader_ran": False, "fragment_found": True, "patterns": 4, "compiled_chars": 28,
            "hooks_patterns": 4, "hooks_chars": 28, "fragment_len": 7, "cmd_pos_len": 8,
            "embedding_patterns": 2, "embedding_chars": 18}

    def test_the_loader_s_own_compiles_are_counted(self, tmp_path):
        guard = ("import re\n"
                 "import _bash_patterns\n"
                 "def _load_the_pattern_path():\n"
                 "    global F\n"
                 "    F = re.compile(_bash_patterns._CMD_POS_NO_VERB + 'cp')\n")
        got = self._compile(_fixture_hooks(tmp_path, write_guard=guard))
        assert (got["method"], got["loader_ran"], got["patterns"], got["compiled_chars"], got["hooks_chars"],
                got["embedding_patterns"], got["embedding_chars"]) == (
            "imports and write_guard._load_the_pattern_path", True, 5, 37, 37, 3, 27)

    def test_a_guard_without_the_loader_is_read_by_its_imports_and_says_so(self, tmp_path):
        guard = "import re\nimport _speedbump\nG = re.compile('at-import')\n"
        got = self._compile(_fixture_hooks(tmp_path, write_guard=guard))
        assert got["method"].startswith("imports alone: this tree's write_guard has no _load_the_pattern_path")
        assert (got["loader_ran"], got["patterns"], got["compiled_chars"]) == (False, 5, 37)

    def test_a_missing_fragment_says_so(self, tmp_path):
        root = _fixture_hooks(tmp_path, write_guard=None)
        bp = root / "tools" / "cc" / "hooks" / "_bash_patterns.py"
        bp.write_text(bp.read_text(encoding="utf-8").replace("_CMD_POS_NO_VERB", "_RENAMED"), encoding="utf-8")
        (root / "tools" / "cc" / "hooks" / "_speedbump.py").write_text("import re\nC = re.compile('mv')\n",
                                                                       encoding="utf-8")
        got = self._compile(root)
        assert (got["fragment_found"], got["fragment_len"], got["embedding_patterns"]) == (False, None, 0)

    def test_a_path_that_compiles_nothing_prints_no_figure_and_exits_one(self, tmp_path):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "_bash_patterns.py").write_text("_CMD_POS_NO_VERB = '(?:^|;)'\n", encoding="utf-8")
        (hooks / "_speedbump.py").write_text("X = 1\n", encoding="utf-8")
        proc = _run("--compile", "--root", str(tmp_path), "--json")
        assert (proc.returncode, proc.stdout) == (1, "")
        assert "recorded no pattern at all" in proc.stderr

    def test_a_checkout_whose_guard_has_no_loader_is_refused(self, tmp_path, monkeypatch, capsys):
        guard = "import re\nimport _speedbump\nG = re.compile('at-import')\n"
        monkeypatch.setattr(census, "REPO_ROOT", _fixture_hooks(tmp_path, write_guard=guard))
        assert census.main(["--compile", "--json"]) == 1
        captured = capsys.readouterr()
        assert captured.out == "" and "has no _load_the_pattern_path" in captured.err

    def test_this_checkout_runs_the_loader(self):
        proc = _run("--compile", "--json")
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout)["compile"]
        assert got["loader_ran"] and got["fragment_found"] and got["hooks_patterns"] > 100, got


#: A pattern module holding each shape the first-use rule must keep or leave:
#: two accessors it keeps (``_grown_re``, whose source is ``{n}`` characters,
#: and ``_other_re``) beside one taking an argument, one taking a keyword only,
#: one returning text, one returning an import-time pattern without naming
#: ``compile``, and an uncached compile.
_FIRST_USE_A = (
    "import functools\n"
    "import re\n"
    "_CMD_POS_NO_VERB = '(?:^|;)'\n"
    "_CMD_POS = _CMD_POS_NO_VERB + 'x'\n"
    "A = re.compile(_CMD_POS_NO_VERB + 'rm')\n"
    "_GROWN = 'g' * {n}\n\n\n"
    "@functools.lru_cache(maxsize=1)\ndef _grown_re():\n    return re.compile(_GROWN)\n\n\n"
    "@functools.cache\ndef _other_re():\n    return re.compile('other')\n\n\n"
    "@functools.lru_cache(maxsize=8)\ndef _with_arg_re(text):\n    return re.compile(text)\n\n\n"
    "@functools.lru_cache(maxsize=1)\ndef _keyword_re(*, flags=0):\n    return re.compile('kw', flags)\n\n\n"
    "@functools.lru_cache(maxsize=1)\ndef _text():\n    return 'compiled by nobody'\n\n\n"
    "@functools.lru_cache(maxsize=1)\ndef _held():\n    return A\n\n\n"
    "def _uncached_re():\n    return re.compile('uncached')\n"
)
#: A second module: an accessor it imports from the first (the first's, never
#: its own), one of its own, and one whose pattern an import compiled first.
_FIRST_USE_B = (
    "import functools\n"
    "import re\n"
    "from {a} import _other_re\n"
    "S = re.compile('plain')\n\n\n"
    "@functools.lru_cache(maxsize=1)\ndef _sb_re():\n    return re.compile('speed', re.I)\n\n\n"
    "@functools.lru_cache(maxsize=1)\ndef _dup_re():\n    return re.compile('plain')\n"
)


def _first_use_hooks(root: Path, *, n: int) -> Path:
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "_bash_patterns.py").write_text(_FIRST_USE_A.format(n=n), encoding="utf-8")
    (hooks / "_speedbump.py").write_text(_FIRST_USE_B.format(a="_bash_patterns"), encoding="utf-8")
    return root


class TestFirstUse:
    """DEF-4122: a pattern moved behind a cached accessor is still compiled by
    every call that opens its check, so the census counts it, and the summed
    line is what a cost gate reads."""

    def _figures(self, root: Path) -> dict:
        proc = _run("--compile", "--root", str(root), "--json")
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout)["compile"]
        assert "summed_chars" in got, f"the census counts no first-use compile: it read {sorted(got)}"
        return got

    def test_each_first_use_pattern_is_counted_beside_the_imports(self, tmp_path):
        got = self._figures(_first_use_hooks(tmp_path, n=40))
        assert (got["hooks_patterns"], got["hooks_chars"]) == (2, 14), got
        assert got["first_use_names"] == ["_bash_patterns._grown_re()", "_bash_patterns._other_re()",
                                          "_speedbump._dup_re()", "_speedbump._sb_re()"], got
        assert (got["first_use_patterns"], got["first_use_chars"]) == (4, 40 + 15), got
        # _dup_re's pattern is the import's own key: no new compile, so the
        # distinct sum leaves it out where the per-accessor figure counts it
        assert (got["summed_patterns"], got["summed_chars"]) == (5, 14 + 40 + 10), got

    def test_a_first_use_pattern_grown_on_a_scratch_copy_raises_the_sum(self, tmp_path):
        small = self._figures(_first_use_hooks(tmp_path / "small", n=40))
        grown = self._figures(_first_use_hooks(tmp_path / "grown", n=1_040))
        assert grown["hooks_chars"] == small["hooks_chars"], (small, grown)
        assert grown["first_use_chars"] - small["first_use_chars"] == 1_000, (small, grown)
        assert grown["summed_chars"] - small["summed_chars"] == 1_000, (small, grown)

    def test_the_text_prints_the_first_use_and_summed_lines(self, tmp_path):
        proc = _run("--compile", "--root", str(_first_use_hooks(tmp_path, n=40)))
        assert proc.returncode == 0, proc.stderr
        assert "compiled on first use (all kinds): 4 patterns, 55 characters" in proc.stdout, proc.stdout
        assert "path plus first use (distinct):    5 patterns, 64 characters" in proc.stdout, proc.stdout

    def test_the_carried_rule_is_the_helpers_both_ways(self, tmp_path, monkeypatch):
        """The census cannot import ``tests/_first_use_patterns.py``, so it
        carries the rule; every shape the fixture holds, kept or left, reads
        the same through both (an accessor one keeps and the other drops reds
        on the set, either way round)."""
        import re

        from tests._first_use_patterns import first_use_patterns

        a_name, b_name = "first_use_fixture_a_4122", "first_use_fixture_b_4122"
        (tmp_path / f"{a_name}.py").write_text(_FIRST_USE_A.format(n=40), encoding="utf-8")
        (tmp_path / f"{b_name}.py").write_text(_FIRST_USE_B.format(a=a_name), encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        for name in (a_name, b_name):
            spec = importlib.util.spec_from_file_location(name, tmp_path / f"{name}.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            monkeypatch.setitem(sys.modules, name, module)
            spec.loader.exec_module(module)
        carried: dict = {"re": re}
        exec(census.FIRST_USE_RULE, carried)  # noqa: S102 -- the script's own constant, run as its child runs it
        expected = {a_name: {"_grown_re()", "_other_re()"}, b_name: {"_sb_re()", "_dup_re()"}}
        for name, keys in expected.items():
            module = sys.modules[name]
            helper = {k: v.pattern for k, v in first_use_patterns(module).items()}
            ours = {k: v.pattern for k, v in carried["first_use_patterns"](module).items()}
            assert set(helper) == keys, (name, sorted(helper))
            assert ours == helper, (name, sorted(ours), sorted(helper))

    def test_the_carried_rule_is_the_helpers_statement_for_statement(self):
        """A drift no fixture shape exercises (a new skip in the helper) still
        reds: the two function bodies are one AST, the docstring and the
        annotations apart."""
        import ast

        def body(source: str) -> str:
            fn = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
                      and n.name == "first_use_patterns")
            stmts = fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(
                fn.body[0].value, ast.Constant) else fn.body
            plain = [ast.Assign(targets=[s.target], value=s.value, lineno=0) if isinstance(s, ast.AnnAssign)
                     else s for s in stmts]
            return ast.dump(ast.Module(body=plain, type_ignores=[]))

        helper = (REPO_ROOT / "tests" / "_first_use_patterns.py").read_text(encoding="utf-8")
        assert body(census.FIRST_USE_RULE) == body(helper)

    def test_the_child_walks_the_roster_the_anchoring_contract_walks(self, monkeypatch):
        monkeypatch.syspath_prepend(str(REPO_ROOT / "tools" / "cc" / "hooks"))
        import _reinject

        assert census.FIRST_USE_MODULES == _reinject._GUARD_PATTERN_MODULES

    def test_this_checkouts_sum_is_its_imports_plus_each_first_use_pattern(self, monkeypatch):
        """On the live tree the summed line is the import figure plus note
        0b0d58's hand probe, and the census names the accessors the helper
        names."""
        import importlib
        import re

        from tests._first_use_patterns import first_use_patterns

        got = self._figures(REPO_ROOT)
        monkeypatch.syspath_prepend(str(REPO_ROOT / "tools" / "cc" / "hooks"))
        modules = [importlib.import_module(name) for name in census.FIRST_USE_MODULES]
        guard = next(m for m in modules if m.__name__ == "write_guard")
        guard._load_the_pattern_path()   # as the child does, before any accessor is called
        helper = {f"{m.__name__}.{k}": v for m in modules for k, v in first_use_patterns(m).items()}
        assert helper, "the helper reads no first-use pattern on this tree: re-derive this row"
        # DEF-2084: every first-use object of the modules, read by type, is a name the census read
        objects = {f"{m.__name__}.{n}" for m in modules for n, v in vars(m).items()
                   if type(v) is getattr(m, "_FirstUse", None)}
        assert objects and not objects - set(got["first_use_names"]), (
            f"first-use objects the census does not read: {sorted(objects - set(got['first_use_names']))}")
        assert got["first_use_names"] == sorted(helper), (got["first_use_names"], sorted(helper))
        chars = sum(len(v.pattern) for v in helper.values() if isinstance(v, re.Pattern))
        assert (got["first_use_patterns"], got["first_use_chars"]) == (len(helper), chars), got
        assert (got["summed_patterns"], got["summed_chars"]) == (
            got["hooks_patterns"] + len(helper), got["hooks_chars"] + chars), (
            "the distinct sum is not the import figure plus each first-use pattern: an accessor's pattern an "
            "import or the loader also compiles (no first use: drop the accessor), or an accessor compiling "
            f"more than the pattern it returns (read it): {got}")


class TestCallsAgainstTheCheckout:
    @pytest.mark.parametrize("kind", census.KINDS[1:])
    def test_one_call_of_each_kind_reads_its_decision(self, kind):
        proc = _run("--calls", "1", "--kind", kind, "--json")
        result = json.loads(proc.stdout) if proc.stdout.strip() else {}
        seen = result.get("kinds", {}).get(kind, {}).get("decisions")
        if seen == {"deny (time budget)": 1}:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        assert (seen, result["kinds"]["control"]["decisions"]) == ({"allow": 1}, {"exit 0": 1})
        assert (result["unguarded"], result["lock"]["outcome"], result["decisions_as_expected"]) == (
            True, "unguarded", True)
        assert set(result["bytecode_cache"].values()) <= {"fresh", "stale", "absent", "hashed"}

    def test_an_unguarded_run_says_so_beside_every_figure(self):
        proc = _run("--calls", "1", "--kind", "read")
        if "deny (time budget)" in proc.stdout:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        lines = proc.stdout.splitlines()
        rows = [line for line in lines if line.startswith(("control ", "read "))]
        assert len(rows) == 2 and all("unguarded" in line.rsplit("[", 1)[-1] for line in rows), lines
        assert "lock:    unguarded (ESPALIER_BOX_LOCK is not set)" in lines

    def test_options_outside_their_mode_are_refused(self):
        for args in (("--compile", "--kind", "bash"), ("--calls", "1", "--rounds", "3"), ("--compile", "--at", " ")):
            proc = _run(*args)
            assert proc.returncode == 2 and "guard_cost_census:" in proc.stderr, (args, proc.stderr)


#: A stand-in guard that refuses on its deadline and writes the record. Its log
#: is named as tools/cc/hooks/_integrity.py::audit_path names the real one, by
#: ``_safe_slug``'s rule, which strips a trailing ``_``: a raw folder name left a
#: mkdtemp name ending in ``_`` (one in 37) uncounted, a red on about one run in
#: nineteen (run 43251681324, the perturbed cell).
_BUDGET_GUARD = '''\
import json, os, re, sys
from datetime import datetime, timezone
if __name__ == "__main__":
    sys.stdin.read()
    name = os.path.basename(os.environ["CLAUDE_PROJECT_DIR"])
    project = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "repo"
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with open(os.path.join(os.environ["ESPALIER_AUDIT_DIR"], f"{project}-{day}.log"), "a", encoding="utf-8") as log:
        log.write(json.dumps({"event_type": "pretooluse_blocked_time_budget", "details": {}}) + "\\n")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                      "permissionDecisionReason": "write_guard ran out of its 4.0 s time budget"}}))
'''


class TestDecisionsThatAreNotACost:
    def test_a_budget_refusal_is_named_counted_tagged_and_exits_three(self, tmp_path):
        root = _fixture_hooks(tmp_path, write_guard=_BUDGET_GUARD)
        proc = _run("--calls", "2", "--kind", "bash", "--root", str(root), "--json")
        assert proc.returncode == census.DECISIONS_MIXED_EXIT, proc.stderr
        result = json.loads(proc.stdout)
        row = result["kinds"]["bash"]
        assert (row["decisions"], row["budget_records"], row["as_expected"]) == ({"deny (time budget)": 2}, 2, False)
        assert (result["kinds"]["control"]["as_expected"], result["decisions_as_expected"]) == (True, False)

    def test_a_project_name_ending_in_an_underscore_is_counted(self, tmp_path, monkeypatch):
        # The draw the two tests here leave to tempfile, fixed: the stand-in
        # guard's record for a folder named with a trailing `_` is counted
        # under its own kind (it read "unknown" with the raw folder name).
        import runpy
        guard = tmp_path / "budget_guard.py"
        guard.write_text(_BUDGET_GUARD, encoding="utf-8")
        audit = tmp_path / "census-audit"   # the suite's own fixtures hold `audit`
        audit.mkdir()
        project = tmp_path / "p-abcdefg_"
        project.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit))
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
        runpy.run_path(str(guard), run_name="__main__")
        assert census.budget_records(audit, {project.name: "bash"}) == {"bash": 1}

    def test_the_text_tags_the_mixed_row_alone(self, tmp_path):
        root = _fixture_hooks(tmp_path, write_guard=_BUDGET_GUARD)
        proc = _run("--calls", "1", "--kind", "read", "--root", str(root))
        assert proc.returncode == census.DECISIONS_MIXED_EXIT, proc.stderr
        lines = proc.stdout.splitlines()
        read = next(line for line in lines if line.startswith("read "))
        control = next(line for line in lines if line.startswith("control "))
        assert "decisions mixed" in read and "1 budget record(s)" in read and "decisions mixed" not in control


class TestTheTreeAndTheCache:
    def test_a_cache_is_fresh_then_stale_then_absent(self, tmp_path):
        source = tmp_path / "mod.py"
        source.write_text("X = 1\n", encoding="utf-8")
        cached = importlib.util.cache_from_source(str(source))
        py_compile.compile(str(source), cfile=cached, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        assert census.pyc_state(source) == "fresh"
        source.write_text("X = 22\n", encoding="utf-8")
        later = time.time() + 5
        os.utime(source, (later, later))
        assert census.pyc_state(source) == "stale"
        os.remove(cached)
        assert census.pyc_state(source) == "absent"

    def test_this_checkout_says_whether_its_tools_cc_is_origin_main(self):
        tree = census.checkout_tree()
        assert tree["kind"] == "checkout" and tree["head"] and tree["tools_cc_is_origin_main"] in (True, False, None)

    @pytest.mark.skipif(sys.platform != "win32", reason="GetSystemTimes is Windows-only; POSIX reads the load average")
    def test_windows_reads_the_cpu_busy_share(self):
        start = census.system_times()
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            pass
        busy = census.cpu_busy(start, census.system_times())
        assert busy is not None and 0.0 <= busy <= 1.0


@pytest.fixture
def held_lock(tmp_path, monkeypatch):
    """A fixture lock this test process holds through the tiers' own plugin
    (``tests/_box_lock.py::BoxLock``), so a change to what a tier locks reaches
    these rows; the holder variable it exports is put back after the test."""
    monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
    path = tmp_path / "box.lock"
    record = {"seat": "fixture-seat", "lane": "lane/fixture", "checkout": str(tmp_path), "pid": os.getpid(),
              "started": "2026-11-12T00:00:00+00:00", "argv": ["pytest", "-q"]}
    holder = _box_lock.BoxLock(path, dict(record), _box_lock._primitive(), stream=io.StringIO())
    holder.acquire()
    assert holder.held
    try:
        yield path, holder.record
    finally:
        holder.release()


def _log_lines(lock: Path) -> list[dict]:
    log = Path(f"{lock}.log")
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


class TestTheBoxLock:
    def test_a_run_behind_a_held_lock_waits_names_its_holder_and_gives_up_past_the_bound(self, held_lock):
        path, record = held_lock
        proc = _run("--calls", "1", "--kind", "read",
                    extra_env={_box_lock.LOCK_KEY: str(path), _box_lock.WAIT_KEY: "0.5"})
        assert proc.returncode == _box_lock.DID_NOT_RUN_EXIT, proc.stderr
        assert f"box lock: waiting on fixture-seat lane/fixture (pid {record['pid']}, held " in proc.stderr
        assert "did not run" in proc.stderr and "nothing was timed" in proc.stderr
        lines = _log_lines(path)
        assert [line["outcome"] for line in lines][-1:] == ["gave_up"]
        assert lines[-1]["holder"] == {"seat": "fixture-seat", "lane": "lane/fixture", "pid": record["pid"]}

    def test_with_no_bound_set_the_census_waits_its_own_default(self, held_lock, monkeypatch):
        path, _ = held_lock
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)  # the fixture's holder exported this pid
        monkeypatch.setattr(census, "DEFAULT_WAIT_S", 0.3)
        lock = census.BoxLock(stream=io.StringIO())
        with pytest.raises(SystemExit) as stopped:
            lock.acquire()
        assert stopped.value.code == census.DID_NOT_RUN_EXIT
        assert "waits at most 0.3 s" in lock.stream.getvalue()

    def test_inside_the_holder_pair_it_passes_through(self, held_lock):
        path, record = held_lock
        proc = _run("--calls", "1", "--kind", "read", "--json",
                    extra_env={_box_lock.LOCK_KEY: str(path), _box_lock.HOLDER_KEY: str(record["pid"]),
                               _box_lock.WAIT_KEY: "5"})  # a broken pass-through gives up, never waits out the child's bound
        if "deny (time budget)" in proc.stdout:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert (result["lock"]["outcome"], result["lock"]["holder"]["seat"]) == ("inside", "fixture-seat")
        assert "inside a holder" in result["tags"]
        assert [line["outcome"] for line in _log_lines(path)][-1:] == ["inside"]

    def test_a_free_lock_is_taken_recorded_while_held_and_cleared(self, tmp_path, monkeypatch):
        path = tmp_path / "box.lock"
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        lock = census.BoxLock(stream=io.StringIO())
        lock.acquire()
        try:
            assert lock.outcome == "taken"
            record = _box_lock.read_record(path)
            assert record is not None and record["pid"] == os.getpid()
            assert set(record) == set(_box_lock.build_record(types.SimpleNamespace(rootpath=tmp_path),
                                                             _box_lock._primitive())) | {"slot"}
            assert record["slot"] == _box_lock.EVERY_SLOT and "draining" not in record, record
            with open(path, "a+", encoding="utf-8") as other:
                assert _box_lock._primitive().try_lock_file(other) is False
            assert census.waiting_line(record, 0.0) == _box_lock.waiting_line(record, waited_s=0.0)
        finally:
            lock.release()
        assert path.read_text(encoding="utf-8") == ""
        lines = _log_lines(path)
        assert [line["outcome"] for line in lines] == ["taken", "released"], lines
        assert lines[1]["run"]["pid"] == os.getpid() and lines[1]["held_s"] >= 0 and "held_s" not in lines[0], lines

    def test_the_census_logs_its_release_before_the_lock_goes(self, tmp_path, monkeypatch):
        """``tests/_box_lock.py::BoxLock.release``'s order (DEF-3084): the
        line written while the census still holds, so a tier waiting behind
        it logs its acquire after the census's release. Mutation: the line
        logged after ``unlock_file``, or not at all."""
        path, at_unlock = tmp_path / "box.lock", []
        real_unlock = census._JSON_SAFE.unlock_file

        def unlock_file(fh):
            at_unlock.append([line["outcome"] for line in _log_lines(path)])
            real_unlock(fh)

        monkeypatch.setattr(census._JSON_SAFE, "unlock_file", unlock_file)
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        lock = census.BoxLock(stream=io.StringIO())
        lock.acquire()
        lock.release()
        assert at_unlock == [["taken", "released"]], at_unlock

    def test_the_census_times_its_hold_from_the_take_never_from_the_queue(self, tmp_path, monkeypatch):
        """The plugin's rule: three refused takes at a 0.1 s poll, then a
        release at once. Mutation: the hold timed from the wait's start."""
        path, refusals = tmp_path / "box.lock", [3]
        real_try = census._JSON_SAFE.try_lock_file

        def try_lock_file(fh):
            if refusals[0]:
                refusals[0] -= 1
                return False
            return real_try(fh)

        monkeypatch.setattr(census._JSON_SAFE, "try_lock_file", try_lock_file)
        monkeypatch.setattr(census, "POLL_S", 0.1)
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        lock = census.BoxLock(stream=io.StringIO())
        lock.acquire()
        lock.release()
        waited, released = _log_lines(path)
        assert (waited["outcome"], released["outcome"]) == ("waited", "released"), (waited, released)
        assert waited["waited_s"] >= 0.25 and released["held_s"] < waited["waited_s"] / 2, (waited, released)

    def test_a_census_acquire_that_fails_before_its_line_logs_no_release(self, tmp_path, monkeypatch):
        """A record the take cannot write (one value JSON cannot encode) fails
        after the take and before the acquire line: the run goes unguarded and
        leaves no ``released`` line to pair with nothing. Mutation: the release
        line keyed on the hold alone."""
        path = tmp_path / "box.lock"
        monkeypatch.setattr(census, "build_record", lambda: {"seat": "s", "lane": "l", "pid": os.getpid(),
                                                             "unwritable": object()})
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        lock = census.BoxLock(stream=io.StringIO())
        lock.acquire()
        assert lock.outcome == "unguarded" and not lock.held
        assert [line["outcome"] for line in _log_lines(path)] == ["unguarded"], _log_lines(path)

    def test_a_census_run_takes_and_clears_a_free_lock(self, tmp_path):
        path = tmp_path / "box.lock"
        proc = _run("--calls", "1", "--kind", "read", "--json", extra_env={_box_lock.LOCK_KEY: str(path)})
        if "deny (time budget)" in proc.stdout:
            pytest.skip(_BUDGET_SKIP)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["lock"]["outcome"] == "taken"
        taken, released = _log_lines(path)
        assert taken["outcome"] == "taken" and taken["run"]["pid"] not in (None, os.getpid())
        assert released["outcome"] == "released" and released["run"] == taken["run"] and released["held_s"] > 0
        assert path.read_text(encoding="utf-8") == ""


class TestTheCensusHoldsEverySlot:
    """DEF-2105: on a box of several slots the census times on a quiet box, so
    it holds every slot as a tier's serial line does, and reads the pair over
    every slot before any try. In-process, the test holding the other slots on
    handles of its own."""

    @staticmethod
    def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: str) -> Path:
        path = tmp_path / "box.lock"
        Path(f"{path}.slots").write_text(count, encoding="utf-8")
        monkeypatch.setenv(_box_lock.LOCK_KEY, str(path))
        monkeypatch.delenv(_box_lock.HOLDER_KEY, raising=False)
        monkeypatch.delenv(_box_lock.WAIT_KEY, raising=False)
        monkeypatch.setattr(census, "POLL_S", 0.05)
        return path

    @staticmethod
    def _hold(path: Path, record: dict) -> "io.TextIOWrapper":
        fh = open(path, "a+", encoding="utf-8")
        assert _box_lock._primitive().try_lock_file(fh), path
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(record))
        fh.flush()
        return fh

    def test_on_a_free_box_it_holds_every_slot_and_clears_each(self, tmp_path, monkeypatch):
        """Mutation: the census taking slot 1 alone (a parallel line could run
        beside its timing)."""
        path = self._box(tmp_path, monkeypatch, "2")
        lock = census.BoxLock(stream=io.StringIO())
        lock.acquire()
        try:
            assert lock.outcome == "taken" and lock.taken == [1, 2], lock.taken
            for slot in (path, Path(f"{path}.slot2")):
                with open(slot, "a+", encoding="utf-8") as other:
                    assert _box_lock._primitive().try_lock_file(other) is False, slot
                assert _box_lock.read_record(slot)["slot"] == "every", slot
        finally:
            lock.release()
        assert all(p.read_text(encoding="utf-8") == "" for p in (path, Path(f"{path}.slot2")))
        assert [(ln["outcome"], ln["slot"], ln["slots"]) for ln in _log_lines(path)] == [
            ("taken", "every", 2), ("released", "every", 2)], _log_lines(path)

    def test_behind_a_parallel_line_it_keeps_slot_one_and_gives_up_clean(self, tmp_path, monkeypatch):
        """With slot 2 held, the census takes slot 1, says in its record that
        it waits for the rest, names slot 2's holder, and past its bound leaves
        slot 1 empty and free. Mutation: a part-hold kept, or its record left
        behind, past the give-up."""
        path = self._box(tmp_path, monkeypatch, "2")
        monkeypatch.setattr(census, "DEFAULT_WAIT_S", 0.3)
        seen: list = []
        real_try = census._JSON_SAFE.try_lock_file

        def try_lock_file(fh):
            got = real_try(fh)
            if not got:
                seen.append(_box_lock.read_record(path))
            return got

        monkeypatch.setattr(census._JSON_SAFE, "try_lock_file", try_lock_file)
        other = self._hold(Path(f"{path}.slot2"), {"seat": "par", "lane": "lane/p", "pid": os.getpid(), "slot": 2})
        try:
            lock = census.BoxLock(stream=io.StringIO())
            with pytest.raises(SystemExit):
                lock.acquire()
            assert seen and seen[0]["draining"] is True and seen[0]["slot"] == "every", seen[:1]
            assert "waiting on par lane/p" in lock.stream.getvalue()
            assert path.read_text(encoding="utf-8") == "" and lock.fh is None
            with open(path, "a+", encoding="utf-8") as probe:
                assert _box_lock._primitive().try_lock_file(probe) is True
                _box_lock._primitive().unlock_file(probe)
        finally:
            other.close()
        assert [ln["outcome"] for ln in _log_lines(path)] == ["gave_up"], _log_lines(path)

    def test_it_stops_at_its_first_refused_slot(self, tmp_path, monkeypatch):
        """With slot 1 held and slot 2 free the census tries slot 1 alone: out
        of order, two whole-box holders could each hold half the box (the code
        review's mutant, the census's copy). Mutation: a refused slot skipped."""
        path = self._box(tmp_path, monkeypatch, "2")
        monkeypatch.setattr(census, "DEFAULT_WAIT_S", 0.3)
        tried: list = []
        real_try = census._JSON_SAFE.try_lock_file

        def try_lock_file(fh):
            tried.append(Path(fh.name).name)
            return real_try(fh)

        monkeypatch.setattr(census._JSON_SAFE, "try_lock_file", try_lock_file)
        held = self._hold(path, {"seat": "x", "lane": "l", "pid": os.getpid(), "slot": "every"})
        try:
            with pytest.raises(SystemExit):
                census.BoxLock(stream=io.StringIO()).acquire()
        finally:
            held.close()
        assert tried and set(tried) == {"box.lock"}, tried

    @pytest.mark.parametrize("count", ["2", "1"], ids=["count-2", "count-lowered"])
    def test_the_pair_is_read_over_every_slot_before_any_try(self, tmp_path, monkeypatch, count):
        """Inside a holder on slot 2 the census passes through and takes no
        slot, the count lowered since included. Mutation: the pair read after
        the first try, or over the count's slots alone."""
        path = self._box(tmp_path, monkeypatch, count)
        monkeypatch.setattr(census, "DEFAULT_WAIT_S", 0.5)
        monkeypatch.setenv(_box_lock.HOLDER_KEY, str(os.getpid()))
        other = self._hold(Path(f"{path}.slot2"), {"seat": "par", "lane": "lane/p", "pid": os.getpid(), "slot": 2})
        try:
            lock = census.BoxLock(stream=io.StringIO())
            lock.acquire()
            assert lock.outcome == "inside" and not lock.taken and lock.fh is None, lock.outcome
        finally:
            other.close()
        assert [(ln["outcome"], ln["slot"], ln["slots"]) for ln in _log_lines(path)] == [("inside", 2, int(count))]


class TestTheHolderIsTheBoxLocksShape:
    """The census cannot import ``tests/_box_lock.py`` (it imports pytest), so
    these hold its copy of a holder's behaviour to the plugin's."""

    def test_the_names_and_the_exit_status_are_the_plugins(self):
        assert (census.LOCK_KEY, census.HOLDER_KEY, census.WAIT_KEY, census.DID_NOT_RUN_EXIT, census.POLL_S,
                census.REPORT_S, census.EVERY_SLOT) == (_box_lock.LOCK_KEY, _box_lock.HOLDER_KEY, _box_lock.WAIT_KEY,
                                                        _box_lock.DID_NOT_RUN_EXIT, _box_lock.POLL_S,
                                                        _box_lock.REPORT_S, _box_lock.EVERY_SLOT)

    def test_the_holder_record_carries_build_records_keys(self, tmp_path):
        config = types.SimpleNamespace(rootpath=tmp_path)
        assert set(census.build_record()) == set(_box_lock.build_record(config, _box_lock._primitive()))

    def test_the_launchers_old_default_reads_as_the_new_one_in_both(self):
        old = os.path.join(tempfile.gettempdir(), "espalier-box.lock")
        assert census.current_path(old, stream=io.StringIO()) == _box_lock.current_path(old, stream=io.StringIO())
        assert census.current_path(old, stream=io.StringIO()) == _box_lock.home_default()
        assert census.current_path("/elsewhere/box.lock") == "/elsewhere/box.lock"

    def test_the_wait_bound_reads_as_the_plugins(self):
        for raw in (None, "", " ", "2.5", "0", "-1", "nan", "inf", "soon"):
            assert census.wait_bound(raw, stream=io.StringIO()) == _box_lock.wait_bound(raw, stream=io.StringIO()), raw

    def test_the_waiting_line_reads_as_the_plugins_under_its_ceiling(self):
        for record in (None, {}, {"seat": "s", "lane": "l", "pid": 7, "argv": ["/x/bin/pytest", "-q", "-n", "4"]},
                       {"seat": "s", "lane": "l", "pid": 7, "started": "not a stamp"}, {"seat": "s"},
                       {"seat": "s", "pid": "abc", "started": "2026-11-12T00:00:00+00:00"},
                       {"seat": "s", "lane": "l", "pid": 7, "slot": "every", "draining": True,
                        "started": "2026-11-12T00:00:00+00:00"}):
            assert census.waiting_line(record, 61.0) == _box_lock.waiting_line(record, waited_s=61.0), record

    def test_the_holder_pair_reads_as_the_plugins(self, monkeypatch):
        me = {"pid": os.getpid()}
        dead = {"pid": 2 ** 22 + 12345}
        for env_pid, record in ((str(os.getpid()), me), (str(dead["pid"]), dead), ("", me), ("x", me),
                                (str(os.getpid()), None), (str(os.getpid()), {"pid": "other"})):
            monkeypatch.setenv(_box_lock.HOLDER_KEY, env_pid)
            assert census.inside_holder(record) == _box_lock.inside_holder(record), (env_pid, record)
        monkeypatch.setenv(_box_lock.HOLDER_KEY, str(os.getpid()))
        assert census.inside_holder(me) is True

    def test_the_log_line_has_the_plugins_shape(self, tmp_path):
        run, holder = {"seat": "s", "lane": "l", "pid": 1}, {"seat": "h", "lane": "m", "pid": 2}
        census.log_outcome(tmp_path / "a", "waited", run, holder, 3.25, why="w", slot="every", slots=2)
        _box_lock.log_outcome(tmp_path / "b", "waited", run, holder, 3.25, why="w", slot="every", slots=2)
        (ours,) = _log_lines(tmp_path / "a")
        (theirs,) = _log_lines(tmp_path / "b")
        assert set(ours) == set(theirs)
        assert {k: ours[k] for k in ("outcome", "run", "holder", "waited_s", "why", "slot", "slots")} == {
            k: theirs[k] for k in ("outcome", "run", "holder", "waited_s", "why", "slot", "slots")}

    def test_the_release_line_has_the_plugins_shape(self, tmp_path):
        """DEF-3084: a hold's ``released`` line, its length in ``held_s`` and
        its start at the take, the wait left on the acquire line."""
        from datetime import datetime
        run = {"seat": "s", "lane": "l", "pid": 1}
        census.log_outcome(tmp_path / "a", "released", run, held_s=90.5)
        _box_lock.log_outcome(tmp_path / "b", "released", run, held_s=90.5)
        (ours,) = _log_lines(tmp_path / "a")
        (theirs,) = _log_lines(tmp_path / "b")
        assert set(ours) == set(theirs) and "held_s" in ours
        keys = ("outcome", "run", "holder", "waited_s", "held_s")
        assert {k: ours[k] for k in keys} == {k: theirs[k] for k in keys} == {
            "outcome": "released", "run": run, "holder": {"seat": None, "lane": None, "pid": None},
            "waited_s": 0.0, "held_s": 90.5}
        for line in (ours, theirs):
            start, end = (datetime.fromisoformat(line[k]) for k in ("start", "end"))
            assert 90 <= (end - start).total_seconds() <= 91, line


def test_the_census_is_stdlib_only():
    """No import outside the standard library: the script runs on a bare interpreter."""
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module.split(".")[0] for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    assert names - {"__future__"} <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


class TestTheFileToolKinds:
    """DEF-3106: the Write and Edit kinds spawn in a worker seat's layout (a
    linked worktree as the project, so the worktree registry is there to walk),
    each with a twin that runs under maintenance mode."""

    def test_the_project_is_a_linked_worktree_of_a_fresh_repository(self, tmp_path):
        worktree = census._new_repo_project(tmp_path)
        gitlink = (worktree / ".git").read_text(encoding="utf-8")
        assert gitlink.startswith("gitdir:") and "/.git/worktrees/" in gitlink.replace("\\", "/"), gitlink
        assert worktree.parent.parent.name == ".claude" and (worktree / "notes.txt").read_text(encoding="utf-8") == "x\n"
        assert census._new_repo_project(tmp_path).name != worktree.name   # each spawn's project named apart

    def test_only_the_maintenance_twins_set_the_switch(self, tmp_path):
        assert census.MAINTENANCE_KINDS < census.REPO_KINDS <= set(census.KINDS)
        # held whole, so the loop below cannot narrow with it unseen
        assert census.REPO_KINDS == {"write", "edit", "write_maintenance", "edit_maintenance"}
        assert census.child_env(tmp_path, tmp_path, maintenance=True)["ESPALIER_MAINTENANCE_MODE"] == "1"
        assert "ESPALIER_MAINTENANCE_MODE" not in census.child_env(tmp_path, tmp_path)
        for kind in census.REPO_KINDS:
            body = census.payload(kind, tmp_path)
            assert body["tool_name"] in ("Write", "Edit") and body["tool_input"]["file_path"] == str(tmp_path / "notes.txt")
