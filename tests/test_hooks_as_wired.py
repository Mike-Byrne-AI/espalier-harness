"""Every hook an adopter's tree wires, launched the way Claude Code launches it,
on each adopter stack and each interpreter host shape (the adopter-axes pack's
wired-hooks matrix).

The hook suites spawn the source scripts under ``HOOK_PYTHON``, so they read a
hook's verdict and never whether it starts on an adopter's machine. There the
interpreter is the name ``init`` wired into ``.claude/settings.json``, resolved
on that machine's PATH. A name that resolves to something that cannot run a
hook (a Store alias, a launcher with no Python behind it) exits outside the
blocking range on every event, so every guard is open while ``init`` reported
success and the source-script runs stay green.

Each ``(stack, host)`` cell builds one init'd tree with that host's stubs first
on PATH (``tests/_interpreter_hosts.py``), so ``init`` wires the name the host
answers to, then launches every entry the tree's settings wire through
``tests/_hook_runner.py::run_hook_as_wired`` on the same PATH, each on its
event's no-op input. It reads three things: every launch exits 0 or 2 under the
channel rule; the wired command is the name that host answers to; and the tree
is the stack's (its fingerprint names the stack's language). The last two are
the second witness the axis registry's rule cannot give: the parameters changed
what was built and launched.

The stacks are the two Decision 2 of the pack holds the expensive cells to,
``python`` and ``node``. Each tree is built once, read by this module alone
(the launches write its ``.espalier-state``), and a cell launches about a dozen
hooks, so the module is in ``_SLOW_FILES``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from tests import _interpreter_hosts as hosts
from tests._hook_assertions import is_decision_or_silent
from tests._hook_runner import NOOP_INPUT, iter_hooks, run_hook_as_wired, script_arg

#: The stacks the pack's Decision 2 runs the expensive cells on.
STACKS = ("python", "node")

#: The language the fingerprint reads for each stack's tree.
_LANGUAGE = {"python": "python", "node": "javascript"}

#: The Stop gate runs light (no test command), and an exported override of
#: this shell's never reaches a launch.
_ENV = {"ESPALIER_STOP_GATE": "light", "ESPALIER_STOP_GATE_TEST_CMD": None}


@pytest.fixture(scope="module")
def wired_tree(tmp_path_factory, stack: str, host: str) -> tuple[Path, str]:
    """``(tree, PATH)``: ``stack``'s adopter tree, init'd with ``host``'s stubs
    first on PATH, and that PATH for its launches."""
    root = tmp_path_factory.mktemp(f"wired-{stack}-{host}")
    path = hosts.path_with(hosts.build_host(root / "host", host))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", path)
        tree = build_adopter_tree(root, stack=stack)
    return tree, path


@pytest.mark.timeout(300)
@pytest.mark.parametrize("host", hosts.SHAPES, scope="module")
@pytest.mark.parametrize("stack", STACKS, scope="module")
def test_every_wired_entry_starts_and_answers_on_one_channel(wired_tree, stack, host):
    tree, path = wired_tree
    settings = json.loads((tree / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = [(event, script_arg(hook).rsplit("/", 1)[-1]) for event, hook in iter_hooks(settings)]
    assert entries, "init wired no hook"
    unknown = sorted({event for event, _ in entries} - set(NOOP_INPUT))
    assert not unknown, f"wired events with no no-op input in tests/_hook_runner.py::NOOP_INPUT: {unknown}"

    bad = {}
    for event, name in entries:
        payload = {"session_id": "wired", **NOOP_INPUT[event], "hook_event_name": event}
        if event == "ConfigChange":
            payload["file_path"] = str(tree / ".claude" / "settings.json")
        run = run_hook_as_wired(tree, name, payload, path=path, env_overrides=_ENV)
        if not is_decision_or_silent(run):
            bad[f"{event} {name}"] = (run.returncode, run.stdout[-200:], run.stderr[-300:])
    assert not bad, f"wired launches on the {host} host that did not answer on one channel: {bad}"

    commands = {hook.get("command") for _, hook in iter_hooks(settings)}
    assert commands == set(hosts.WORKING_NAMES[host]), (
        f"init on the {host} host wired {sorted(commands)}, not the name that host answers to")
    fingerprint = json.loads((tree / "reports" / "repo_fingerprint.json").read_text(encoding="utf-8"))
    assert _LANGUAGE[stack] in fingerprint["languages"], fingerprint["languages"]
