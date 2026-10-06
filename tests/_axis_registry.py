"""Adopter-axes registry: which adopter shapes the suite actually runs the harness on.

Every pre-release check once ran the harness on a tree shaped like the harness
itself. That is the pattern ``memory/a-gate-can-be-blind-along-a-whole-dimension.md``
records for the bench corpus, here across the whole verification system. The
registry names the dimensions an adopter can differ along:

* **stack**: what the adopter's tree is (one cell per adopter row of
  ``tests/_stack_trees.py``);
* **host**: which interpreter names answer (one cell per
  ``tests/_interpreter_hosts.py`` shape);
* **session**: one hook event, or a working session that carries state from
  event to event on one tree;
* **root**: whether a path the harness runs from holds a space (the tree's own,
  or the interpreter's);
* **tree**: a fresh tree, a dirty machine (an existing ``.claude/``, a
  ``master`` default branch, a stale ``espalier`` first on PATH), or a CRLF
  checkout.

Each ``(axis, value)`` cell is in one of two states. Either it names the
pytest node that proves it, or it declares its gap with a reason (a ledger
row, or the work that will prove it). ``tests/test_axis_registry.py`` is the
contract:

* every cell has exactly one of the two;
* a proving node is parametrised with an argument **named after the axis**
  (``stack``, ``host``, ``session``, ``root``, ``tree``), whose value, with
  ``-`` read as ``_``, is the cell's value; it carries no ``skip`` or
  ``xfail`` mark; and it runs and passes on the host that checks it. This
  refuses the born-blind shape, a cell naming a test that never varies along
  its own value. The rule reads the parameter, not the id: an id joins
  parameters with ``-``, so ``[node-pnpm]`` would otherwise prove ``node``;
* the stack and host rosters equal the populations they are derived from;
* the count of proven cells equals a dated floor that only rises.

A cell names the strongest test that runs the harness at that value. A value
is one word (``store_python3``, ``node_pnpm``) with no ``-``.

The rule cannot see whether the test body uses the parameter: a test
parametrised over ``stack`` that builds a Python tree whatever its value would
pass it. When the first cell is proven, that test should also check the tree
it built.

``python tests/_axis_registry.py`` prints the table. An axis with fewer than
two proven values is a blind axis, and the table says so in those words.
"""
from __future__ import annotations

from dataclasses import dataclass

AXES: tuple[str, ...] = ("stack", "host", "session", "root", "tree")


@dataclass(frozen=True)
class AxisCell:
    """One ``(axis, value)`` the verification system should run the harness at."""

    axis: str        # one of AXES; also the name of the proving test's parameter
    value: str       # one word, no "-"
    proven_by: str   # a pytest node id parametrised over `axis` at `value`, or ""
    gap: str         # why no test proves this cell yet (a row id, or a reason); "" if proven


# The wired-hooks matrix, the cross-event session driver, the parametrised Walk,
# the perturbed CI cell, the release smoke's flags and the dirty-machine cell are
# the adopter-axes pack's later work; until each lands, its cells are gaps that
# say so.
_MATRIX = "the wired-hooks matrix (tests/test_hooks_as_wired.py, not yet written)"
_DRIVER = "the cross-event session driver (tests/test_adopter_session.py, not yet written)"

AXIS_REGISTRY: tuple[AxisCell, ...] = (
    # -- stack ---------------------------------------------------------------
    # One cell per adopter row of tests/_stack_trees.py (the contract derives
    # the roster from ADOPTER_STACKS, "-" spelled "_"). Every stack's tree is
    # built and installed by tests/test_stack_trees.py::TestEveryStackInstalls
    # (`init` and `install-ci` exit zero; the fingerprint reads the stack).
    # That is not yet the cell's proof: the cell asks whether the hooks govern
    # a session on that tree, and nothing runs a hook on one yet.
    AxisCell("stack", "python", "",
             f"{_MATRIX} and {_DRIVER}. Today the hooks run only on Python-shaped "
             "trees, and no test is parametrised over the stack"),
    AxisCell("stack", "node", "",
             f"{_MATRIX} and {_DRIVER}. The hooks' source set was measured blind to "
             "Node (deleting .js/.ts/.jsx/.tsx moved 0 of 329 verdicts, 2026-10-06), "
             "a .mjs write never arms Stop's gates, and the fingerprint reads the "
             "adopter-node tree as no language (DEF-961)"),
    AxisCell("stack", "node_pnpm", "",
             "DEF-976 (the stack registry) proves it on the adopter-node-pnpm tree, "
             "whose test command still reads `npm test`"),
    AxisCell("stack", "go", "",
             "the adopter-go tree installs and reads as Go "
             "(tests/test_stack_trees.py::TestEveryStackInstalls); no hook runs on it. "
             "Whether that install cell proves the stack is the operator's call"),
    AxisCell("stack", "rust", "",
             "the adopter-rust tree installs and reads as Rust "
             "(tests/test_stack_trees.py::TestEveryStackInstalls); no hook runs on it. "
             "Whether that install cell proves the stack is the operator's call"),
    # -- host ----------------------------------------------------------------
    # Exactly the tests/_interpreter_hosts.py shapes (the contract derives the
    # roster from SHAPES): which interpreter names answer, and nothing else.
    AxisCell("host", "store_python3", "",
             f"the perturbed CI cell (a Store-alias python3 first on PATH) and {_MATRIX}"),
    AxisCell("host", "launcher_only", "",
             "tests/test_hook_exec_form.py::TestInitOnTheTwoInterpreterHosts::"
             "test_the_launcher_wired_write_guard_spawns_and_denies launches one hook "
             f"as wired on this host but is not parametrised over the host; {_MATRIX} "
             "proves the cell"),
    AxisCell("host", "python3_only", "", f"{_MATRIX}"),
    # -- session -------------------------------------------------------------
    AxisCell("session", "single_event", "", f"{_MATRIX} (one event per launch)"),
    AxisCell("session", "cross_event", "", f"{_DRIVER}"),
    # -- root ----------------------------------------------------------------
    AxisCell("root", "plain", "",
             "every test runs here, and none is parametrised against a spaced root"),
    AxisCell("root", "spaced", "",
             "the perturbed CI cell (a spaced --basetemp) and the release smoke's "
             "--spaced-root leg"),
    AxisCell("root", "spaced_interpreter", "",
             "no CI interpreter path holds a space. On the Windows host, whose venv "
             "does, the stop-gate override pair reds because its fixture spells "
             "sys.executable unquoted (measured 2026-10-06); DEF-968 is the product "
             "half of the shape"),
    # -- tree ----------------------------------------------------------------
    AxisCell("tree", "clean", "",
             "every test runs here, and none is parametrised against a dirty machine"),
    AxisCell("tree", "dirty", "", "DEF-937 (the dirty-machine install cell)"),
    AxisCell("tree", "crlf", "",
             "tests/_stack_trees.py writes LF on every host since 2026-10-06; before, "
             "Windows runs built CRLF fixture trees by accident. A CRLF checkout (Git "
             "for Windows' autocrlf default) is now built by no test"),
)

# The proven-cell floor: it may only rise. Raise it in the same change that
# proves a cell, and never lower it to admit a cell going back to a gap. A cell
# that loses its proof is a regression for review, not a number to edit.
# 2026-10-06: 0 -- the registry lands with every cell a declared gap.
PROVEN_FLOOR = 0


def proven(cells: tuple[AxisCell, ...] = AXIS_REGISTRY) -> list[AxisCell]:
    return [c for c in cells if c.proven_by]


def proven_values_by_axis(cells: tuple[AxisCell, ...] = AXIS_REGISTRY) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {axis: [] for axis in AXES}
    for c in proven(cells):
        out.setdefault(c.axis, []).append(c.value)
    return out


def blind_axes(cells: tuple[AxisCell, ...] = AXIS_REGISTRY) -> list[str]:
    """Axes with fewer than two proven values: reported, not failed. One proven
    value means every proving test ran at that value, so the axis is blind."""
    return [axis for axis, values in proven_values_by_axis(cells).items() if len(values) < 2]


def render_table(cells: tuple[AxisCell, ...] = AXIS_REGISTRY) -> str:
    lines = ["| Axis | Value | State | Proven by, or the gap |", "|---|---|---|---|"]
    for c in cells:
        state = "proven" if c.proven_by else "gap"
        lines.append(f"| {c.axis} | {c.value} | {state} | {c.proven_by or c.gap} |")
    lines.append("")
    by_axis = proven_values_by_axis(cells)
    for axis in AXES:
        values = by_axis.get(axis, [])
        if len(values) >= 2:
            lines.append(f"- {axis}: proven at {len(values)} values ({', '.join(values)}).")
        elif values:
            lines.append(f"- {axis}: **a blind axis** -- every proving test ran at one "
                         f"value ({values[0]}).")
        else:
            lines.append(f"- {axis}: **a blind axis** -- no value is proven.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_table())
