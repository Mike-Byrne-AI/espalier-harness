"""Contract for ``tests/_axis_registry.py``, the adopter-axes registry.

A cell either names the pytest node that proves it, or declares its gap.
A proven node must collect, and its parametrisation id must carry the cell's
value as a token. A test that never varies along its own value proves nothing
about that value. That is the born-blind shape, and the id rule exists to
refuse it. The proven-cell count is a ratchet: it equals the dated floor, and
the floor only rises.

While no cell is proven, the per-cell check has nothing to walk. The planted
rows in ``TestTheIdRuleRefusesTheBornBlindShape`` keep the rule itself honest
in the meantime: every refusal it makes is seen to happen on a scratch tree.
"""
from __future__ import annotations

# slow-exempt: seven short children -- one `--collect-only` per file a proven
# cell names (one today), one per planted-tree row, and one run of the
# registry module -- about 2.5 s for the whole module on the Windows host.

import os
import subprocess
import sys
from pathlib import Path

from _stack_trees import ADOPTER_STACKS
from tests import _axis_registry as reg
from tests import _interpreter_hosts as hosts

REPO_ROOT = Path(__file__).resolve().parent.parent

_LAUNCHER_NODE = (
    "tests/test_hook_exec_form.py::TestInitOnTheTwoInterpreterHosts::"
    "test_the_launcher_wired_write_guard_spawns_and_denies"
)


def _child_env() -> dict[str, str]:
    # A parent's PYTEST_ADDOPTS (a perturbed cell's --basetemp, a -n) must not
    # reach a nested pytest: an explicit --basetemp is emptied by whichever
    # session first asks for a temp dir.
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    return env


def collected_node_ids(node_ids: list[str], rootdir: Path) -> set[str]:
    """Every node id that collects in the files ``node_ids`` live in: one
    ``--collect-only`` subprocess per file, so one file's collection error
    cannot hide another's."""
    files = sorted({nid.split("::", 1)[0] for nid in node_ids})
    out: set[str] = set()
    for rel in files:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", rel],
            cwd=rootdir, env=_child_env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        out.update(line.strip() for line in proc.stdout.splitlines() if "::" in line)
    return out


def refusal(cell: reg.AxisCell, collected: set[str]) -> str | None:
    """Why ``cell`` does not prove its value, or None when it does."""
    if cell.proven_by not in collected:
        return f"{cell.axis}/{cell.value}: {cell.proven_by!r} does not collect"
    tokens = reg.param_tokens(cell.proven_by)
    if cell.value not in tokens:
        return (
            f"{cell.axis}/{cell.value}: {cell.proven_by!r} carries no {cell.value!r} in its "
            f"parametrisation (tokens: {tokens}), so it never varies along the value it is "
            "named for -- parametrise it over the axis, or declare the gap"
        )
    return None


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
            f"holds '-' (pytest joins parameter ids with '-'): {bad}"
        )

    def test_no_cell_is_listed_twice(self):
        keys = [(c.axis, c.value) for c in reg.AXIS_REGISTRY]
        assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)

    def test_every_axis_declares_at_least_two_values(self):
        # An axis with one declared value is blind by construction: no proof
        # could ever show it was run at a second one.
        thin = [axis for axis in reg.AXES if sum(c.axis == axis for c in reg.AXIS_REGISTRY) < 2]
        assert not thin, f"axes declaring fewer than two values: {thin}"

    def test_every_adopter_stack_has_a_stack_cell(self):
        # Derived from the stack table's adopter rows: a new row lands without
        # a cell and this reds. A row name's "-" is a cell value's "_".
        declared = {c.value for c in reg.AXIS_REGISTRY if c.axis == "stack"}
        rows = {stack.replace("-", "_") for stack in ADOPTER_STACKS}
        assert rows, "the stack table has no adopter rows -- the derivation broke"
        missing = sorted(rows - declared)
        assert not missing, f"tests/_stack_trees.py adopter rows with no stack cell: {missing}"

    def test_every_interpreter_host_shape_has_a_host_cell(self):
        # Derived from the shapes the stubbed-PATH oracle builds, never a
        # hand-kept list: a new shape lands without a cell and this reds.
        declared = {c.value for c in reg.AXIS_REGISTRY if c.axis == "host"}
        missing = sorted(set(hosts.SHAPES) - declared)
        assert not missing, f"tests/_interpreter_hosts.py shapes with no host cell: {missing}"


class TestProvenCellsCollectAndVary:
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

    def test_every_proven_node_collects_and_carries_its_value(self):
        cells = reg.proven()
        collected = collected_node_ids([c.proven_by for c in cells], REPO_ROOT)
        refusals = [r for r in (refusal(c, collected) for c in cells) if r]
        assert not refusals, "\n".join(refusals)

    def test_the_one_hook_launched_as_wired_today_does_not_prove_its_host_cell(self):
        """The launcher-only host is the one host a hook is launched on as wired
        today, by one test that is not parametrised over the host. Named as the
        cell's proof, the id rule refuses it, which is why the cell is a gap. When
        that test is parametrised over the host shapes, this reds: prove the
        cell, then delete this test."""
        cell = reg.AxisCell("host", hosts.LAUNCHER_ONLY, _LAUNCHER_NODE, "")
        collected = collected_node_ids([_LAUNCHER_NODE], REPO_ROOT)
        assert _LAUNCHER_NODE in collected, (
            f"{_LAUNCHER_NODE} no longer collects; update this test and the "
            "launcher_only cell's gap"
        )
        reason = refusal(cell, collected)
        assert reason is not None and "carries no" in reason, reason


_PLANTED = '''\
import pytest


@pytest.mark.parametrize("stack", ["python", "node_pnpm"])
@pytest.mark.parametrize("host", ["store_python3"])
def test_varies(stack, host):
    pass


def test_does_not_vary():
    pass
'''


class TestTheIdRuleRefusesTheBornBlindShape:
    """Each refusal the contract makes, seen on a scratch tree."""

    @staticmethod
    def _planted(tmp_path: Path) -> tuple[set[str], str]:
        (tmp_path / "test_planted.py").write_bytes(_PLANTED.encode("utf-8"))
        collected = collected_node_ids(["test_planted.py::x"], tmp_path)
        varied = sorted(n for n in collected if "node_pnpm" in n)
        assert len(collected) == 3 and len(varied) == 1, collected
        return collected, varied[0]

    def test_a_node_parametrised_over_the_value_proves_it(self, tmp_path):
        collected, varied = self._planted(tmp_path)
        assert refusal(reg.AxisCell("stack", "node_pnpm", varied, ""), collected) is None
        assert refusal(reg.AxisCell("host", "store_python3", varied, ""), collected) is None

    def test_a_node_that_never_varies_is_refused(self, tmp_path):
        collected, _ = self._planted(tmp_path)
        reason = refusal(
            reg.AxisCell("host", "launcher_only", "test_planted.py::test_does_not_vary", ""),
            collected,
        )
        assert reason is not None and "carries no" in reason, reason

    def test_a_node_varied_along_another_value_is_refused(self, tmp_path):
        collected, varied = self._planted(tmp_path)
        reason = refusal(reg.AxisCell("stack", "go", varied, ""), collected)
        assert reason is not None and "carries no" in reason, reason

    def test_a_value_that_is_only_part_of_a_token_is_refused(self, tmp_path):
        # "python" is a substring of "store_python3" but not a token of it: a
        # substring match would read this id as varying along the stack.
        collected, _ = self._planted(tmp_path)
        fake = "test_planted.py::test_varies[store_python3]"
        collected = collected | {fake}
        reason = refusal(reg.AxisCell("stack", "python", fake, ""), collected)
        assert reason is not None and "carries no" in reason, reason

    def test_a_node_that_does_not_collect_is_refused(self, tmp_path):
        collected, _ = self._planted(tmp_path)
        reason = refusal(
            reg.AxisCell("stack", "python", "test_planted.py::test_gone[python]", ""), collected,
        )
        assert reason is not None and "does not collect" in reason, reason


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
            encoding="utf-8", errors="replace", timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == reg.render_table() + "\n"
