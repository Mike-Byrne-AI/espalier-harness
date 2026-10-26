"""Contract for ``tests/_axis_registry.py``, the adopter-axes registry.

This contract exists because every pre-release check ran the harness on a
tree shaped like the harness and still read green: a gate can be blind along
a whole dimension of its input. It pins which adopter shapes the suite runs,
and guards against the registry claiming a shape no test varies along.

A cell either names the pytest node that proves it, or declares its gap. A
proving node is parametrised with an argument named after the cell's axis whose
value (``-`` read as ``_``) is the cell's value, carries no ``skip`` or
``xfail`` mark (a ``target_os`` node no ``skipif`` either: a stand-in's point is
that the required Linux cells see the other host's shape, so a ``target_os`` cell is proven
on every host or not at all, and the run-time check below sees only the host it
runs on), and runs and passes here. A test that never varies along its
own value proves nothing about that value. That is the born-blind shape, and
the rule exists to refuse it. The rule reads the collected item's parameters,
never its id: an id joins parameters with ``-``, so ``[node-pnpm]`` would read
as proving ``node``. The proven-cell count is a ratchet: it equals the dated
floor, and the floor only rises.

While no cell is proven, the per-cell checks have nothing to walk. The planted
rows in ``TestTheRuleRefusesTheBornBlindShape`` keep the rule itself honest in
the meantime: every refusal it makes is seen to happen on a scratch tree.
"""
from __future__ import annotations

# slow-exempt: short children -- one collection per file a proven cell names,
# one collection and one run per planted-tree row, and one run of the registry
# module, a few seconds in all. The one long child, the run of the proving
# nodes, is `test_every_proven_node_runs_and_passes_here`, marked slow itself.

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _stack_trees import ADOPTER_STACKS
from tests import _axis_registry as reg
from tests._live_tree import checkout_glob
from tests import _interpreter_hosts as hosts

REPO_ROOT = Path(__file__).resolve().parent.parent

_LAUNCHER_NODE = (
    "tests/test_hook_exec_form.py::TestInitOnTheTwoInterpreterHosts::"
    "test_the_launcher_wired_write_guard_spawns_and_denies"
)

# Prints one line per collected item: its node id, its parameters (callspec)
# and the names of its marks. Run as `python -c` so the collection happens in a
# child: one file's collection error cannot take this module down with it.
_COLLECT = r'''
import json, sys
import pytest

class _Report:
    def pytest_collection_finish(self, session):
        for item in session.items:
            spec = getattr(item, "callspec", None)
            params = {k: str(v) for k, v in spec.params.items()} if spec else {}
            marks = sorted({m.name for m in item.iter_markers()})
            print("AXIS-ITEM " + json.dumps({"id": item.nodeid, "params": params, "marks": marks}), flush=True)

sys.exit(pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", *sys.argv[1:]], plugins=[_Report()]))
'''

_REFUSING_MARKS = frozenset({"skip", "xfail"})
# A `target_os` cell is proven on every host or not at all (the module docstring), so a
# `skipif` on its node, whatever its condition, is refused at collection.
_REFUSING_MARKS_BY_AXIS = {"target_os": _REFUSING_MARKS | {"skipif"}}


def _child_env() -> dict[str, str]:
    # A parent's PYTEST_ADDOPTS (a perturbed cell's --basetemp, a -n) must not
    # reach a nested pytest: an explicit --basetemp is emptied by whichever
    # session first asks for a temp dir.
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    return env


def collected_items(node_ids: list[str], rootdir: Path) -> dict[str, dict]:
    """``{node id: {"params": {...}, "marks": [...]}}`` for every item collected
    from the files ``node_ids`` live in, one child per file."""
    files = sorted({nid.split("::", 1)[0] for nid in node_ids})
    out: dict[str, dict] = {}
    for rel in files:
        # One file's collection: under a second here. The bound sits below the
        # 60 s per-test ceiling so a hung child fails this test by name.
        proc = subprocess.run(
            [sys.executable, "-c", _COLLECT, rel], cwd=rootdir, env=_child_env(),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("AXIS-ITEM "):
                item = json.loads(line[len("AXIS-ITEM "):])
                out[item["id"]] = item
    return out


def refusal(cell: reg.AxisCell, items: dict[str, dict]) -> str | None:
    """Why ``cell``'s proving node does not vary along its value, or None."""
    item = items.get(cell.proven_by)
    if item is None:
        return f"{cell.axis}/{cell.value}: {cell.proven_by!r} does not collect"
    marks = sorted(_REFUSING_MARKS_BY_AXIS.get(cell.axis, _REFUSING_MARKS) & set(item["marks"]))
    if marks:
        if marks == ["skipif"]:
            return (
                f"{cell.axis}/{cell.value}: {cell.proven_by!r} carries {marks}: an {cell.axis!r} "
                "cell is proven on every host or not at all, and a node that skips on one host "
                "proves nothing there"
            )
        return (
            f"{cell.axis}/{cell.value}: {cell.proven_by!r} carries {marks}, so it never "
            "runs green at the value it is named for"
        )
    param = item["params"].get(cell.axis)
    if param is None or param.replace("-", "_") != cell.value:
        return (
            f"{cell.axis}/{cell.value}: {cell.proven_by!r} carries no {cell.axis!r} "
            f"parameter at {cell.value!r} (parameters: {item['params']}), so it never "
            f"varies along the value it is named for -- parametrise it with a "
            f"{cell.axis!r} argument, or declare the gap"
        )
    # A parameter with one value is the born-blind shape with a parameter on it:
    # the function is collected at that value alone, so nothing it asserts was
    # ever seen to differ along the axis. The function's other items are in
    # `items`, collected from the same file.
    function = cell.proven_by.split("[", 1)[0]
    values = {it["params"].get(cell.axis) for nid, it in items.items()
              if nid.split("[", 1)[0] == function} - {None}
    if len(values) < 2:
        return (
            f"{cell.axis}/{cell.value}: {cell.proven_by!r}'s function is collected at one "
            f"{cell.axis!r} value only ({sorted(values)}), so the node never varies along "
            f"the axis -- give the parameter a second value the test can honestly take, or "
            "declare the gap"
        )
    return None


def outcomes(node_ids: list[str], rootdir: Path, timeout: float = 45) -> dict[str, set[str]]:
    """Run ``node_ids`` once and read each one's outcome from the ``-v`` lines
    (``-rA`` names a skipped test by file and line, not by node id).

    ``timeout`` defaults below the 60 s per-test ceiling, which is all a planted
    row needs; a caller running real proving nodes passes its own and carries a
    ``pytest.mark.timeout`` above it."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", "--color=no", "--tb=line",
         *node_ids],
        cwd=rootdir, env=_child_env(), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    seen: dict[str, set[str]] = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^(\S+::\S+)\s+(PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)\b", line)
        if m:
            seen.setdefault(m.group(1), set()).add(m.group(2))
    return seen


def not_passed(node_ids: list[str], rootdir: Path, timeout: float = 45) -> list[str]:
    ran = outcomes(node_ids, rootdir, timeout) if node_ids else {}
    return [f"{nid}: {sorted(ran.get(nid, set())) or 'never ran'}"
            for nid in node_ids if ran.get(nid) != {"PASSED"}]


class TestEveryCellIsWellFormed:
    def test_every_cell_has_exactly_one_of_a_proof_or_a_gap(self):
        bad = [
            f"{c.axis}/{c.value}" for c in reg.AXIS_REGISTRY
            if bool(c.proven_by.strip()) == bool(c.gap.strip())
        ]
        assert not bad, f"cells with both or neither of proven_by and gap: {bad}"

    def test_every_cell_names_a_declared_axis_and_a_one_word_value(self):
        bad = [
            f"{c.axis}/{c.value}" for c in reg.AXIS_REGISTRY
            if c.axis not in reg.AXES or not c.value or "-" in c.value
            or c.value != c.value.strip() or " " in c.value
        ]
        assert not bad, (
            f"cells outside {reg.AXES}, or with a value that is empty, spaced, or "
            f"holds '-': {bad}"
        )

    def test_no_cell_is_listed_twice(self):
        keys = [(c.axis, c.value) for c in reg.AXIS_REGISTRY]
        assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)

    def test_every_axis_declares_at_least_two_values(self):
        # An axis with one declared value is blind by construction: no proof
        # could ever show it was run at a second one.
        thin = [axis for axis in reg.AXES if sum(c.axis == axis for c in reg.AXIS_REGISTRY) < 2]
        assert not thin, f"axes declaring fewer than two values: {thin}"

    def test_no_axis_is_named_for_a_standard_library_module(self):
        """A proving node's parameter is named after its axis, so an axis named
        ``os`` would shadow the module inside every proving function, where
        ``hasattr(os, "geteuid")`` reads False and ``getattr(os, "name", "posix")``
        the default, silently; no selected lint rule sees it (probed 2026-10-26,
        when the platform axis was nearly named ``os``). The list is the
        interpreter's own, so this rule cannot go stale by hand."""
        assert reg.stdlib_shadowing() == [], reg.stdlib_shadowing()
        assert reg.stdlib_shadowing(("stack", "os", "platform")) == ["os", "platform"]

    def test_the_stack_cells_are_the_adopter_rows(self):
        # Derived from the stack table both ways: a new row with no cell, or a
        # cell whose row was deleted, reds. A row name's "-" is a value's "_".
        declared = {c.value for c in reg.AXIS_REGISTRY if c.axis == "stack"}
        rows = {stack.replace("-", "_") for stack in ADOPTER_STACKS}
        assert rows, "the stack table has no adopter rows -- the derivation broke"
        assert declared == rows, (
            f"rows with no cell: {sorted(rows - declared)}; "
            f"cells with no row: {sorted(declared - rows)}"
        )

    def test_the_host_cells_are_the_interpreter_host_shapes(self):
        # Derived from the shapes the stubbed-PATH oracle builds, both ways.
        declared = {c.value for c in reg.AXIS_REGISTRY if c.axis == "host"}
        assert declared == set(hosts.SHAPES), (
            f"shapes with no cell: {sorted(set(hosts.SHAPES) - declared)}; "
            f"cells with no shape: {sorted(declared - set(hosts.SHAPES))}"
        )


class TestProvenCellsVaryRunAndPass:
    def test_the_proven_count_equals_the_dated_floor(self):
        count = len(reg.proven())
        assert count >= reg.PROVEN_FLOOR, (
            f"{count} proven cells against a floor of {reg.PROVEN_FLOOR}: a cell lost its "
            "proof. Restore the proving test, or say in review why the axis went blind -- "
            "never lower the floor to admit it."
        )
        assert count == reg.PROVEN_FLOOR, (
            f"{count} proven cells against a floor of {reg.PROVEN_FLOOR}: raise "
            "PROVEN_FLOOR (with the date) in the change that proved the cell, so the "
            "ratchet cannot absorb a later regression in the space just gained."
        )

    def test_every_proven_node_varies_along_its_value(self):
        cells = reg.proven()
        items = collected_items([c.proven_by for c in cells], REPO_ROOT)
        refusals = [r for r in (refusal(c, items) for c in cells) if r]
        assert not refusals, "\n".join(refusals)

    # Six session tests in one child (an init and four deployed hooks per
    # stack): 25 s on ubuntu and 55 s on the Windows Portability runner on
    # 2026-10-07, 65 s alone on the Windows self-host box -- past the 60 s
    # per-test ceiling, which ended that Portability run with no test named.
    # The child's own bound sits under this mark, so its message is the one a
    # reader sees.
    @pytest.mark.slow
    @pytest.mark.timeout(660)
    def test_every_proven_node_runs_and_passes_here(self):
        """Collection cannot see a ``skipif`` that fires, a ``pytest.skip`` in
        the body or a marker that deselects the node, so the proving nodes run."""
        cells = reg.proven()
        if not cells:
            pytest.skip("no proven cell yet -- the floor test says so")
        problems = not_passed([c.proven_by for c in cells], REPO_ROOT, timeout=600)
        assert not problems, "proving nodes that do not run and pass here:\n" + "\n".join(problems)

    def test_the_one_hook_launched_as_wired_today_does_not_prove_its_host_cell(self):
        """The launcher-only host is the one host a hook is launched on as wired
        today, by one test that is not parametrised over the host. Named as the
        cell's proof, the rule refuses it, which is why the cell is a gap. When
        that test is parametrised over the host shapes, this reds: prove the
        cell, then delete this test."""
        cell = reg.AxisCell("host", hosts.LAUNCHER_ONLY, _LAUNCHER_NODE, "")
        items = collected_items([_LAUNCHER_NODE], REPO_ROOT)
        assert _LAUNCHER_NODE in items, (
            f"{_LAUNCHER_NODE} no longer collects; update this test and the "
            "launcher_only cell's gap"
        )
        reason = refusal(cell, items)
        assert reason is not None and "carries no 'host' parameter" in reason, reason


_PLANTED = '''\
import sys

import pytest


@pytest.mark.parametrize("stack", ["python", "node-pnpm"])
@pytest.mark.parametrize("host", ["store_python3", "launcher_only"])
def test_varies(stack, host):
    pass


@pytest.mark.parametrize("label", ["go"])
def test_other_parameter(label):
    pass


@pytest.mark.parametrize("stack", [pytest.param("node", marks=pytest.mark.xfail(strict=True))])
def test_xfailed(stack):
    assert False


@pytest.mark.skip(reason="planted")
@pytest.mark.parametrize("stack", ["rust"])
def test_skipped(stack):
    pass


@pytest.mark.parametrize("stack", ["go", "rust"])
def test_skips_in_the_body(stack):
    pytest.skip("planted")


def test_does_not_vary():
    pass


@pytest.mark.parametrize("stack", ["go"])
def test_one_value(stack):
    pass


@pytest.mark.skipif(sys.platform == "win32", reason="planted")
@pytest.mark.parametrize("target_os", ["windows"])
def test_skips_on_one_host(target_os):
    pass


@pytest.mark.skipif(sys.platform == "win32", reason="planted")
@pytest.mark.parametrize("stack", ["rust", "go"])
def test_skips_on_one_host_along_another_axis(stack):
    pass
'''


class TestTheRuleRefusesTheBornBlindShape:
    """Each refusal the contract makes, seen on a scratch tree."""

    @staticmethod
    def _planted(tmp_path: Path) -> dict[str, dict]:
        (tmp_path / "test_planted.py").write_bytes(_PLANTED.encode("utf-8"))
        items = collected_items(["test_planted.py::x"], tmp_path)
        assert len(items) == 14, sorted(items)
        return items

    @staticmethod
    def _node(items: dict[str, dict], fn: str, **params: str) -> str:
        found = [nid for nid, item in items.items()
                 if nid.split("::")[1].split("[")[0] == fn and item["params"] == params]
        assert len(found) == 1, (fn, params, sorted(items))
        return found[0]

    def test_a_node_parametrised_over_the_axis_at_the_value_proves_it(self, tmp_path):
        items = self._planted(tmp_path)
        pnpm = self._node(items, "test_varies", stack="node-pnpm", host="store_python3")
        assert refusal(reg.AxisCell("stack", "node_pnpm", pnpm, ""), items) is None
        assert refusal(reg.AxisCell("host", "store_python3", pnpm, ""), items) is None
        assert not_passed([pnpm], tmp_path) == []

    def test_a_dashed_value_does_not_prove_its_first_word(self, tmp_path):
        # The id is `[node-pnpm-store_python3]`: split on "-", it holds `node`.
        items = self._planted(tmp_path)
        pnpm = self._node(items, "test_varies", stack="node-pnpm", host="store_python3")
        reason = refusal(reg.AxisCell("stack", "node", pnpm, ""), items)
        assert reason is not None and "carries no 'stack' parameter at 'node'" in reason, reason

    def test_a_node_that_never_varies_is_refused(self, tmp_path):
        items = self._planted(tmp_path)
        reason = refusal(
            reg.AxisCell("host", "launcher_only", "test_planted.py::test_does_not_vary", ""),
            items,
        )
        assert reason is not None and "carries no 'host' parameter" in reason, reason

    def test_a_value_carried_by_another_parameter_is_refused(self, tmp_path):
        items = self._planted(tmp_path)
        node = self._node(items, "test_other_parameter", label="go")
        reason = refusal(reg.AxisCell("stack", "go", node, ""), items)
        assert reason is not None and "carries no 'stack' parameter" in reason, reason

    def test_a_node_varied_along_another_value_is_refused(self, tmp_path):
        items = self._planted(tmp_path)
        python = self._node(items, "test_varies", stack="python", host="store_python3")
        reason = refusal(reg.AxisCell("stack", "go", python, ""), items)
        assert reason is not None and "carries no 'stack' parameter at 'go'" in reason, reason

    def test_an_xfail_or_skip_node_is_refused(self, tmp_path):
        items = self._planted(tmp_path)
        for fn, value in (("test_xfailed", "node"), ("test_skipped", "rust")):
            node = self._node(items, fn, stack=value)
            reason = refusal(reg.AxisCell("stack", value, node, ""), items)
            assert reason is not None and "carries ['" in reason, (fn, reason)

    def test_a_node_that_skips_in_its_body_does_not_pass(self, tmp_path):
        # Collection sees nothing wrong here; only the run does.
        items = self._planted(tmp_path)
        node = self._node(items, "test_skips_in_the_body", stack="go")
        assert refusal(reg.AxisCell("stack", "go", node, ""), items) is None
        assert not_passed([node], tmp_path) == [f"{node}: ['SKIPPED']"]

    def test_a_skipif_on_an_os_node_is_refused_at_collection(self, tmp_path):
        """A ``skipif`` whose condition is false here would pass the run-time
        check on this host and skip the proof on another; for a ``target_os`` cell that
        is the Linux cell skipping the Windows shape, so collection refuses it.
        The rule is the ``target_os`` axis's: along another axis a ``skipif`` is left to
        the run-time check, as before."""
        items = self._planted(tmp_path)
        node = self._node(items, "test_skips_on_one_host", target_os="windows")
        reason = refusal(reg.AxisCell("target_os", "windows", node, ""), items)
        assert reason is not None and "carries ['skipif']" in reason and "every host" in reason, reason
        other = self._node(items, "test_skips_on_one_host_along_another_axis", stack="rust")
        assert refusal(reg.AxisCell("stack", "rust", other, ""), items) is None

    def test_a_function_collected_at_one_value_of_its_axis_is_refused(self, tmp_path):
        """A parameter with one value passes the parameter rule and still never
        varies: the function is collected at that value alone, which is the
        born-blind shape with a parameter on it (the alarm test's one-value
        parameter was one, found 2026-10-26). Collection refuses it, so a cell
        cannot be proven by a node that could not have run any other way."""
        items = self._planted(tmp_path)
        node = self._node(items, "test_one_value", stack="go")
        reason = refusal(reg.AxisCell("stack", "go", node, ""), items)
        assert reason is not None and "collected at one 'stack' value only" in reason, reason
        varied = self._node(items, "test_varies", stack="python", host="store_python3")
        assert refusal(reg.AxisCell("host", "store_python3", varied, ""), items) is None

    def test_a_node_that_does_not_collect_is_refused(self, tmp_path):
        items = self._planted(tmp_path)
        reason = refusal(
            reg.AxisCell("stack", "python", "test_planted.py::test_gone[python]", ""), items,
        )
        assert reason is not None and "does not collect" in reason, reason


class TestTheTargetOsCellsHoldOnEveryHost:
    """A ``target_os`` cell is proven on every host or not at all (the module docstring),
    and two things besides a ``skipif`` can take a host away: the platform roster
    in ``tests/conftest.py``, whose marks are added only on the matching host, so
    a Linux collection never sees them; and the harness growing a read that
    splits macOS from Linux, which would make the ``macos`` gap text false
    without a word. Both are pinned here, because the registry's own rules read
    the collected items and the cell text, never the roster or the source."""

    _HOSTS = (("linux", {"GITHUB_ACTIONS": "true"}), ("win32", {"GITHUB_ACTIONS": "true"}),
              ("darwin", {"GITHUB_ACTIONS": "true"}), ("darwin", {}))

    def test_no_target_os_proving_node_is_on_the_platform_roster(self):
        from tests.conftest import _expected_failures_for
        cells = [c for c in reg.proven() if c.axis == "target_os"]
        assert cells, "no proven target_os cell -- the floor test says so; delete this test with the axis"
        marked = [
            f"{c.proven_by} on {host} {sorted(env)}" for c in cells for host, env in self._HOSTS
            if _expected_failures_for(c.proven_by, host, env)
        ]
        assert not marked, "target_os proving nodes the platform roster marks on a host:\n" + "\n".join(marked)

    # The harness tells the platforms apart by these comparisons alone; the one
    # Mac-differing read is the SubagentStart host line's platform.system(),
    # which prints and never branches. A new read that splits darwin from linux
    # (a comparison to another string, a startswith, a platform.system() branch)
    # reds here and names its site: re-read the target_os/macos gap text with it.
    # The allowed site is cited path::symbol, never by line.
    _PLATFORM_VALUES = {"win32"}
    _OS_NAME_VALUES = {"nt", "posix"}
    _ALLOWED_MAC_READS = {"tools/cc/hooks/_hook_utils.py::host_orientation_line"}

    @staticmethod
    def _harness_sources():
        for base in (REPO_ROOT / "tools" / "cc", REPO_ROOT / "espalier"):
            for path in checkout_glob(base, "**/*.py"):
                if "_vendor" not in path.parts:
                    yield path

    def test_the_harness_reads_the_platform_as_win32_or_not_and_the_macos_gap_holds(self):
        import ast
        compared: list[str] = []
        other_reads: list[str] = []
        mac_reads: list[str] = []
        for path in self._harness_sources():
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            spans = [(n.lineno, n.end_lineno or n.lineno, n.name) for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    sides = [node.left, *node.comparators]
                    for side in sides:
                        read = _platform_read(side)
                        if read is None:
                            continue
                        allowed = self._PLATFORM_VALUES if read == "sys.platform" else self._OS_NAME_VALUES
                        for other in sides:
                            for value in _constants(other):
                                compared.append(f"{rel}:{node.lineno} {read} vs {value!r}")
                                if value not in allowed:
                                    other_reads.append(f"{rel}:{node.lineno} compares {read} with {value!r}")
                elif isinstance(node, ast.Call):
                    if (isinstance(node.func, ast.Attribute) and node.func.attr == "startswith"
                            and _platform_read(node.func.value) == "sys.platform"):
                        other_reads.append(f"{rel}:{node.lineno} sys.platform.startswith(...)")
                    if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "platform"
                            and node.func.attr in {"system", "mac_ver", "uname", "platform"}):
                        mac_reads.append(f"{_site(rel, spans, node.lineno)} platform.{node.func.attr}()")
        assert len(compared) >= 40, f"only {len(compared)} platform comparisons read -- the walk regressed"
        assert not other_reads, (
            "a harness read that could split macOS from Linux; re-read the target_os/macos gap text in "
            "tests/_axis_registry.py with it:\n" + "\n".join(other_reads)
        )
        unexpected = [r for r in mac_reads if r.split(" ", 1)[0] not in self._ALLOWED_MAC_READS]
        assert mac_reads and not unexpected, (
            f"platform.* reads under the harness roots: {mac_reads}; the target_os/macos gap text in "
            f"tests/_axis_registry.py names only {sorted(self._ALLOWED_MAC_READS)} -- re-read it"
        )


def _platform_read(node) -> str | None:
    """``"sys.platform"`` or ``"os.name"`` when ``node`` reads one, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "sys" and node.attr == "platform":
            return "sys.platform"
        if node.value.id == "os" and node.attr == "name":
            return "os.name"
    return None


def _site(rel: str, spans: list, lineno: int) -> str:
    """``path::function`` for the innermost def holding ``lineno``, else the path."""
    holding = [(end - start, name) for start, end, name in spans if start <= lineno <= end]
    return f"{rel}::{min(holding)[1]}" if holding else rel


def _constants(node) -> list:
    """The string constants ``node`` holds: one, or the members of a tuple, list or set."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [c for e in node.elts for c in _constants(e)]
    return []


class TestTheTable:
    def test_the_table_names_every_cell_and_every_blind_axis(self):
        table = reg.render_table()
        for c in reg.AXIS_REGISTRY:
            assert f"| {c.axis} | {c.value} |" in table, (c.axis, c.value)
        for axis in reg.blind_axes():
            assert f"- {axis}: **a blind axis**" in table, axis

    def test_one_proven_value_reads_as_a_blind_axis(self):
        cells = (
            reg.AxisCell("stack", "python", "t.py::t[python]", ""),
            reg.AxisCell("stack", "node", "", "not yet"),
            reg.AxisCell("host", "store_python3", "t.py::t[store_python3]", ""),
            reg.AxisCell("host", "launcher_only", "t.py::t[launcher_only]", ""),
        )
        assert "stack" in reg.blind_axes(cells) and "host" not in reg.blind_axes(cells)
        table = reg.render_table(cells)
        assert "- stack: **a blind axis** -- every proving test ran at one value (python)." in table
        assert "- host: proven at 2 values (store_python3, launcher_only)." in table

    def test_running_the_module_prints_the_table(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tests" / "_axis_registry.py")],
            cwd=REPO_ROOT, env=_child_env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=45,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == reg.render_table() + "\n"
