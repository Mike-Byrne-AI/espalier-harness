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
* **target_os**: the operating system a test makes the harness read, through
  ``tests/_platform_standin.py``, on whatever host runs it (``linux``,
  ``macos``, ``windows``); not ``os``, which a proving node's parameter would
  shadow inside the test.

Each ``(axis, value)`` cell is in one of two states. Either it names the
pytest node that proves it, or it declares its gap with a reason (a ledger
row, or the work that will prove it). ``tests/test_axis_registry.py`` is the
contract:

* every cell has exactly one of the two;
* a proving node is parametrised with an argument **named after the axis**
  (``stack``, ``host``, ``session``, ``root``, ``tree``, ``target_os``), whose value,
with
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

``python tests/_axis_registry.py`` prints the table, then the release
instruments and the value each runs at (``INSTRUMENTS``): the report
``docs/RELEASE_CHECKLIST.md``'s blind-axis step pastes into the release notes.
An axis with fewer than two proven values, or that every instrument ran at one
value, is a blind axis, and the report says so in those words.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

AXES: tuple[str, ...] = ("stack", "host", "session", "root", "tree", "target_os")


@dataclass(frozen=True)
class AxisCell:
    """One ``(axis, value)`` the verification system should run the harness at."""

    axis: str        # one of AXES; also the name of the proving test's parameter
    value: str       # one word, no "-"
    proven_by: str   # a pytest node id parametrised over `axis` at `value`, or ""
    gap: str         # why no test proves this cell yet (a row id, or a reason); "" if proven


# The perturbed CI cell, the release smoke's flags and the dirty-machine cell are
# the adopter-axes pack's later work; until each lands, its cells are gaps that
# say so. The wired-hooks matrix landed 2026-11-03; the cross-event session
# driver was dropped that day (the session cells say why).
_MATRIX = ("tests/test_hooks_as_wired.py::"
           "test_every_wired_entry_starts_and_answers_on_one_channel")

AXIS_REGISTRY: tuple[AxisCell, ...] = (
    # -- stack ---------------------------------------------------------------
    # One cell per adopter row of tests/_stack_trees.py (the contract derives
    # the roster from ADOPTER_STACKS, "-" spelled "_"). Every stack's tree is
    # built and installed by tests/test_stack_trees.py::TestEveryStackInstalls
    # (`init` and `install-ci` exit zero; the fingerprint reads the stack).
    # That is not yet the cell's proof: the cell asks whether the hooks govern
    # a session on that tree, and nothing runs a hook on one yet.
    # Proven 2026-10-06 by the Node-defaults lane's session test: on a copy of
    # each init'd tree it launches the DEPLOYED plan_guard, reflect_trigger,
    # stop_gate and subagent_stop on one session's events and asserts the
    # stack's own files are governed (a root source file needs a plan, ten
    # source writes arm the hygiene gates, Stop blocks, the adopter's declared
    # agents relieve both gates). The wired-hooks matrix launches every hook
    # as wired on the python and node trees too, but one no-op event at a
    # time; this test stays the cells' proof because it asserts what the
    # hooks govern (the cross-event driver was dropped, 2026-11-03).
    AxisCell("stack", "python",
             "tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::"
             "test_the_hooks_govern_a_session_on_the_tree[python]", ""),
    AxisCell("stack", "node",
             "tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::"
             "test_the_hooks_govern_a_session_on_the_tree[node]", ""),
    # Proven 2026-10-06 by the stack registry's package-manager lane: the same
    # session test on the pnpm and Bun trees, which also asserts that each
    # tree's fingerprint names its own package manager (the second witness the
    # parameter rule cannot give).
    AxisCell("stack", "node_pnpm",
             "tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::"
             "test_the_hooks_govern_a_session_on_the_tree[node-pnpm]", ""),
    AxisCell("stack", "node_bun",
             "tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::"
             "test_the_hooks_govern_a_session_on_the_tree[node-bun]", ""),
    # Proven 2026-10-07 by the stack registry's source-and-manifests lane:
    # the same session test on the Go and Rust trees (the pack's Decision 6,
    # a session proof in place of a ruling on the install cells).
    AxisCell("stack", "go",
             "tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::"
             "test_the_hooks_govern_a_session_on_the_tree[go]", ""),
    AxisCell("stack", "rust",
             "tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::"
             "test_the_hooks_govern_a_session_on_the_tree[rust]", ""),
    # -- host ----------------------------------------------------------------
    # Exactly the tests/_interpreter_hosts.py shapes (the contract derives the
    # roster from SHAPES): which interpreter names answer, and nothing else.
    # Proven 2026-11-03 by the wired-hooks matrix: on each host shape it runs
    # `init` with that host's stubs first on PATH, then launches every entry
    # the tree's settings wire as Claude Code does (the command resolved on
    # that PATH), and reads every launch exiting 0 or 2 on one channel and the
    # wired command being the name the host answers to. The cells name its
    # Python tree; its Node tree runs beside it.
    AxisCell("host", "store_python3", f"{_MATRIX}[python-store_python3]", ""),
    AxisCell("host", "launcher_only", f"{_MATRIX}[python-launcher_only]", ""),
    AxisCell("host", "python3_only", f"{_MATRIX}[python-python3_only]", ""),
    # -- session -------------------------------------------------------------
    AxisCell("session", "single_event", "",
             f"{_MATRIX} launches one event per launch on every wired entry, but no test "
             "is parametrised over the session axis: a function collected at one session "
             "value is the born-blind shape the rule refuses, and the other value is a gap"),
    AxisCell("session", "cross_event", "",
             "the cross-event session driver was dropped on 2026-11-03: the pack's 0-D, "
             "re-run at a291436 on the python, node .mjs and node .js trees with every "
             "hook launched as wired, found no differential the single-event tests miss "
             "(the one it pre-registered was closed by the Node-defaults and stack-registry "
             "lanes), so the pack's refuting clause shrank its session work to the wired "
             "matrix; the measurement is in task-packs/TP-468-adopter-axes.md's Landing"),
    # -- root ----------------------------------------------------------------
    AxisCell("root", "plain", "",
             "every test runs here, and none is parametrised against a spaced root"),
    AxisCell("root", "spaced", "",
             "the perturbed CI cell (a spaced --basetemp) and the release smoke's "
             "--spaced-root leg"),
    AxisCell("root", "spaced_interpreter", "",
             "no CI interpreter a hook runs from holds a space (the release smoke's "
             "second leg runs the CLI from a venv under a spaced root and launches "
             "no hook, so its INSTRUMENTS row claims spaced). On the Windows host, whose venv "
             "does, the stop-gate override pair reds because its fixture spells "
             "sys.executable unquoted (measured 2026-10-06). DEF-968 closed the "
             "product half (struck 2026-10-16: tests/test_hook_entry_argv.py spawns "
             "a real interpreter under a spaced directory on every host), but no "
             "test is parametrised over this axis"),
    # -- tree ----------------------------------------------------------------
    AxisCell("tree", "clean", "",
             "every test runs here, and none is parametrised against a dirty machine"),
    AxisCell("tree", "dirty", "", "DEF-937 (the dirty-machine install cell)"),
    AxisCell("tree", "crlf", "",
             "tests/_stack_trees.py writes LF on every host since 2026-10-06; before, "
             "Windows runs built CRLF fixture trees by accident. A CRLF checkout (Git "
             "for Windows' autocrlf default) is now built by no test"),
    # -- target_os -----------------------------------------------------------
    # The operating system a test makes the harness read, through
    # tests/_platform_standin.py (the platform the harness reads, and the
    # alarm Windows lacks), on whatever host runs it. A cell is proven by a
    # node parametrised over `target_os`; the surfaces the kernel decides (LockFileEx
    # on one byte, PATHEXT, a grandchild holding a pipe past the timeout) are
    # the Windows leg's and no stand-in on another host proves them.
    # Proven 2026-10-26 by the platform stand-ins lane: the bounded spawn's
    # timeout-shape test, one node parametrised over linux and windows, drives
    # the three copies of run_bounded with the standard library's own run in
    # place (its _is_stdlib_run guard sends a replaced run down the run branch
    # at both values, so only a real run can tell them apart) and asserts the
    # shape that differs: read as Windows the tree is ended, the pipes drained
    # and the child reaped; read as Linux the call is run's and the child alone
    # is killed. The alarm test of tests/test_redos.py is the home of the
    # Windows-alarm behaviour (the suite's timers skip where SIGALRM is missing,
    # the alarm taken away through the same stand-in); its timers are the
    # suite's own, not harness code, so it proves no cell.
    AxisCell("target_os", "linux",
             "tests/test_bounded_spawn.py::TestEveryCopysWindowsBranch::"
             "test_the_timeout_shape_follows_the_platform_the_harness_reads[linux]", ""),
    AxisCell("target_os", "macos", "",
             "the harness reads darwin nowhere, and its one Mac-differing read is "
             "platform.system() in tools/cc/hooks/_hook_utils.py::host_orientation_line, from uname, "
             "which no sys.platform patch reaches (read 2026-10-26): a stand-in cannot make "
             "the harness do anything as macOS that it does not do as linux, so a node at "
             "this value could assert nothing of its own, the born-blind shape"),
    AxisCell("target_os", "windows",
             "tests/test_bounded_spawn.py::TestEveryCopysWindowsBranch::"
             "test_the_timeout_shape_follows_the_platform_the_harness_reads[windows]", ""),
)

# The proven-cell floor: it may only rise. Raise it in the same change that
# proves a cell, and never lower it to admit a cell going back to a gap. A cell
# that loses its proof is a regression for review, not a number to edit.
# 2026-10-06: 0 -- the registry lands with every cell a declared gap.
# 2026-10-06: 2 -- stack/python and stack/node, by the Node-defaults session test.
# 2026-10-06: 4 -- stack/node_pnpm and stack/node_bun, by the same test on the
#   pnpm and Bun trees (the stack registry's package-manager lane).
# 2026-10-07: 6 -- stack/go and stack/rust, by the same test on the Go and Rust
#   trees (the stack registry's source-and-manifests lane, Decision 6).
# 2026-10-26: 8 -- target_os/linux and target_os/windows, by the platform stand-ins lane (the
#   bounded spawn's timeout-shape node over linux and windows).
# 2026-11-03: 11 -- host/store_python3, host/launcher_only and host/python3_only, by the
#   wired-hooks matrix (the adopter-axes pack's session-and-stack lane).
PROVEN_FLOOR = 11


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


def stdlib_shadowing(axes: tuple[str, ...] = AXES) -> list[str]:
    """Axes named for a standard-library module. A proving node's parameter is
    named after its axis (the contract's rule), so such an axis puts that name
    in every proving function, where ``hasattr(os, "geteuid")`` reads False and
    ``getattr(os, "name", "posix")`` the default, silently, with no lint rule
    watching (the platform axis was nearly named ``os``, 2026-10-26). The list
    is the interpreter's own (3.10 and later, the suite's floor), never a
    hand-kept one."""
    return [axis for axis in axes if axis in sys.stdlib_module_names]


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


# -- the instruments ---------------------------------------------------------
# The cells above say which values the suite's tests reach. These say which the
# machines that run a release's checks reach: the tree each installs the harness
# into, the interpreter names its host answers to, whether its root holds a
# space, and whether one run carries hook state from event to event. Read
# 2026-11-03 from each instrument's own lines. A value outside the axis's cells
# is shown and never counts: "both" (python and python3 answer, the shape no
# cell perturbs), "none" (the instrument installs into no stack tree, or
# launches no hook), "not measured" and "not built".
INSTRUMENT_AXES: tuple[str, ...] = ("stack", "host", "root", "session")
OUTSIDE_VALUES = frozenset({"both", "none", "not measured", "not built"})

#: The workflows whose jobs run the suite or a release instrument: the contract
#: names every job of these in a row, and holds every workflow to this list or
#: to NOT_INSTRUMENTS.
INSTRUMENT_WORKFLOWS: tuple[str, ...] = (
    "clean-checkout.yml", "end-to-end-bench.yml", "portability.yml", "post-merge.yml",
    "post-merge-windows.yml", "release.yml", "test.yml",
)
NOT_INSTRUMENTS: dict[str, str] = {
    "benchmark.yml": "the guard's bypass benchmark over its command corpus; it installs the harness into no tree",
    "harness-guard.yml": "the merge gate's own checks (title, ci_guard, freshness, lint, mypy); it runs no suite",
    "publish.yml": "builds and uploads a tagged release; its gate calls release.yml, which is read",
    "refresh-externals.yml": "refreshes the external pins; it runs no suite",
}


@dataclass(frozen=True)
class Instrument:
    """One release check, and the value it runs the harness at on each axis."""

    name: str
    runs: tuple[str, ...]   # the workflow jobs (``<file>::<job>``) or scripts it is
    stack: str
    host: str
    root: str
    session: str


INSTRUMENTS: tuple[Instrument, ...] = (
    # Run alone on the release box (TP-468's Motivation: the Windows box answers
    # python only, the Mac python3 only); which box cuts a tag is not recorded.
    Instrument("fresh_clone_gate (Tier 3 step 0)", ("scripts/fresh_clone_gate.py",),
               "python", "not measured", "not measured", "single_event"),
    # Stages 1 to 3 run the suite: the source checkout's, the extracted archive's
    # after a pip install, and the sdist's where it ships test modules.
    Instrument("final_release_matrix stages 1 to 3, the checkout's, archive's and sdist's tests",
               ("scripts/final_release_matrix.py",), "python", "not measured", "not measured", "single_event"),
    # Stage 4 smokes the wheel on a README tree (doctor_target); 5 and 6 read
    # the artifacts and install nothing.
    Instrument("final_release_matrix stages 4 to 6, the wheel smoke and the artifacts",
               ("scripts/final_release_matrix.py",), "none", "not measured", "not measured", "none"),
    # One row per wheel_smoke run in the job (tests/test_axis_registry.py reads
    # its lines): the first into an empty `git init`, the second (TP-468 3-B)
    # into the Node adopter row under a spaced root. The venv sits under that
    # root too, but wheel_smoke launches no hook, so session is "none" and the
    # spaced interpreter is not claimed. Every row with a Windows leg reads
    # "not measured" for host: windows-latest answering python3 is probable,
    # not measured (TP-468 0-C).
    Instrument("release.yml matrix-smoke, the wheel on three operating systems",
               ("release.yml::matrix-smoke",), "none", "not measured", "plain", "none"),
    Instrument("release.yml matrix-smoke's second smoke, a Node tree under a spaced root",
               ("release.yml::matrix-smoke",), "node", "not measured", "spaced", "none"),
    Instrument("release.yml release-check", ("release.yml::release-check",),
               "python", "both", "plain", "single_event"),
    Instrument("test.yml test and test-serial, the required cells",
               ("test.yml::test", "test.yml::test-serial"), "python", "both", "plain", "single_event"),
    Instrument("the tier computations and the audit jobs", (
        "test.yml::tier", "clean-checkout.yml::clean-tier", "test.yml::ripgrep-parity",
        "test.yml::stdlib-audit", "test.yml::code-review-audit", "test.yml::artifact-parity",
        "test.yml::workflow-lint",
    ), "none", "both", "plain", "none"),
    Instrument("the perturbed cell (TP-468 3-A)", (), "not built", "not built", "not built", "not built"),
    Instrument("portability.yml on ubuntu, windows and macos", ("portability.yml::portability",),
               "python", "not measured", "plain", "single_event"),
    Instrument("clean-checkout.yml, the full tier with the heavy stages", ("clean-checkout.yml::clean-checkout",),
               "python", "both", "plain", "single_event"),
    Instrument("post-merge.yml, main after each merge", ("post-merge.yml::full-tier",),
               "python", "both", "plain", "single_event"),
    Instrument("post-merge-windows.yml, main's serial files on Windows", ("post-merge-windows.yml::serial-leg",),
               "python", "not measured", "plain", "single_event"),
    # It installs Claude Code and drives a live session; which tree, host, root
    # and session it runs the harness at is not read here.
    Instrument("end-to-end-bench.yml, a live Claude Code session", ("end-to-end-bench.yml::e2e",),
               "not measured", "not measured", "not measured", "not measured"),
)


def instrument_values_by_axis(
    instruments: tuple[Instrument, ...] = INSTRUMENTS,
    cells: tuple[AxisCell, ...] = AXIS_REGISTRY,
) -> dict[str, list[str]]:
    """For each instrument axis, the cell values some instrument reaches, in
    first-reached order; a value outside the axis's cells never counts."""
    out: dict[str, list[str]] = {}
    for axis in INSTRUMENT_AXES:
        known = {c.value for c in cells if c.axis == axis}
        out[axis] = list(dict.fromkeys(v for i in instruments if (v := getattr(i, axis)) in known))
    return out


def blind_instrument_axes(
    instruments: tuple[Instrument, ...] = INSTRUMENTS,
    cells: tuple[AxisCell, ...] = AXIS_REGISTRY,
) -> list[str]:
    """Instrument axes every instrument ran at one cell value, or at none."""
    return [axis for axis, values in instrument_values_by_axis(instruments, cells).items() if len(values) < 2]


def render_instruments(
    instruments: tuple[Instrument, ...] = INSTRUMENTS,
    cells: tuple[AxisCell, ...] = AXIS_REGISTRY,
) -> str:
    lines = ["| Instrument | " + " | ".join(INSTRUMENT_AXES) + " |",
             "|---|" + "---|" * len(INSTRUMENT_AXES)]
    for i in instruments:
        lines.append(f"| {i.name} | " + " | ".join(getattr(i, axis) for axis in INSTRUMENT_AXES) + " |")
    lines.append("")
    # Each row is the instrument's OWN machine, tree, root and run; the tests it
    # runs reach the cells above, which this half does not credit.
    for axis, values in instrument_values_by_axis(instruments, cells).items():
        if len(values) >= 2:
            lines.append(f"- {axis}: the instruments' own runs take {len(values)} values ({', '.join(values)}).")
        elif values:
            lines.append(f"- {axis}: **a blind axis** -- every instrument's own run is at one value ({values[0]}).")
        else:
            lines.append(f"- {axis}: **a blind axis** -- no instrument's own run is at a value its cells name.")
    return "\n".join(lines)


def render_report() -> str:
    """The table the release notes carry (docs/RELEASE_CHECKLIST.md): the cells
    the suite proves, then the values the release instruments run at."""
    return render_table() + "\n\n" + render_instruments()


if __name__ == "__main__":
    print(render_report())
