"""The install on the machine an adopter actually has: ``init``, ``install-ci``,
``doctor`` and ``upgrade`` on a dirty tree beside a clean one.

**Why.** The first install ever driven on an ordinary developer machine (the
first Windows walk, 2026-08-18) found five findings that are not Windows at all:
they surfaced because that machine had a prior espalier on PATH, a ``master``
default branch, a ``.claude/`` of its own, spaces in every path and an operator
who pastes verbatim. Every install test and CI job since ran on a clean tree in a
clean checkout, so that class was found by a human on a host or not at all.

**The trees** (the ``tree`` parameter, the axis registry's ``tree`` cells):

* ``dirty`` -- the Python adopter row on ``master``, under a parent folder whose
  name holds a space; the adopter's own ``.claude/`` committed with it (a
  ``settings.json`` carrying their own hook and allow rule, the shared project
  settings Claude Code expects in source control, so ``init`` takes its
  tracked-settings branch; and ``agents/my-reviewer.md``); and a stale
  ``espalier`` first on PATH that answers an old version and records each call.
* ``clean`` -- the same row on ``main`` in a plain folder, with none of that.

Both run with the folder of the interpreter under test right after the stale
command, as an activated environment puts it, so a remedy's ``python`` is the
engine under test; a ``python`` that is some other environment's is not one of
the four conditions.

**The oracles** are the walk's five findings, read from its record by the
dispatcher (ack ``20261011T220856Z-air-9b8938``), each asserted as what the
verbs do now:

1. A prior espalier on PATH: no verb here runs it (none spawns a bare
   ``espalier``; a verb that starts to reds the proving node), and no remedy the
   verbs print spells the bare command, which a paste would send to it.
2. A ``master`` default branch: the guard workflow ``install-ci`` writes is
   triggered by a push to the tree's own branch.
3. A pre-existing ``.claude/``: ``init`` preserves the adopter's file and agent,
   renders the fresh template beside it, no verb names a render or a backup as
   the adopter's uncommitted work, and the remedy ``init`` prints wires the hooks
   while keeping the adopter's own hook and rule.
4. Spaces in every path: a control with no oracle of its own (the dirty tree's
   parent holds one, and the proving node checks that it does).
5. An operator who pastes verbatim: the remedy ``init`` prints is run as
   printed, and every remedy's interpreter resolves on that PATH. That arm reds
   only on a host where the spelled name is absent (the Windows host with no
   ``python3``); the interpreter-host matrix in ``tests/test_hooks_as_wired.py``
   is that axis's home.

Not here: that no install step runs ``--version`` is the install docs' (no verb
prints a step); ``fuse``'s closing line is not one of these verbs; and no verb
here prints the maintenance-mode line or an owner/repo placeholder (read in
their output, 2026-11-03). Each tree is built and driven once per module, about
fourteen seconds on the Windows host, so the module is in ``_SLOW_FILES``.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from espalier.harness_config import CANONICAL_HOOK_WIRING
from tests._hook_runner import iter_hooks, script_arg
from tests._stubs import write_stub

pytestmark = pytest.mark.timeout(300)

TREES = ("clean", "dirty")

#: The adopter's own Claude Code settings: one hook and one allow rule of theirs.
_ADOPTER_HOOK = {"type": "command", "command": "echo adopter-hook"}
_ADOPTER_ALLOW = "Bash(make test)"
_ADOPTER_SETTINGS = (json.dumps({
    "permissions": {"allow": [_ADOPTER_ALLOW]},
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [_ADOPTER_HOOK]}]},
}, indent=2) + "\n").encode("utf-8")
_ADOPTER_AGENT = b"---\nname: my-reviewer\ndescription: The adopter's own reviewer.\n---\nReview the diff.\n"

#: The line ``init`` ends its summary with when the adopter's settings kept the
#: hooks out, and the remedy after its colon.
_ACTIVATE = re.compile(r"To activate \(keeps your settings[^)]*\): (?P<remedy>.+)$", re.M)

#: An interpreter spelled before ``-m espalier``: a quoted path, or one word
#: that is not a flag, with the launcher's version flag (``py -3``) allowed
#: between; and the verb after it.
_REMEDY = re.compile(r"""(?:"(?P<quoted>[^"]+)"|(?P<word>[^\s`'"(\-][^\s`'"(]*))(?: -[23][\w.-]*)? """
                     r"""-m espalier(?:\.cli)? (?P<verb>[a-z][a-z-]*)""")

#: A ``.claude/`` render or backup named on the untracked-work note's line
#: (``cli._print_untracked_conflicts``).
_NAMED_AS_WORK = re.compile(r"-- you have uncommitted: .*\.claude/[^,\s]*\.(?:new|bak)")


@dataclass
class Machine:
    tree: Path
    path: str                                   # the PATH every verb ran with
    record: Path | None                         # the stale espalier's call record (dirty only)
    runs: dict[str, subprocess.CompletedProcess]  # each step's run, in order
    settings: dict[str, bytes]                  # .claude/settings.json after each step
    remedy_problem: str = ""                    # why the dirty tree's remedy did not run


def _stale_espalier(bin_dir: Path, record: Path) -> Path:
    """An ``espalier`` that answers an old version and appends each call to ``record``."""
    if os.name == "nt":
        return write_stub(bin_dir / "espalier.cmd",
                          f'@echo off\necho call %*>>"{record}"\necho espalier 0.1.0', crlf=True)
    return write_stub(bin_dir / "espalier",
                      f"#!/bin/sh\nprintf 'call %s\\n' \"$*\" >> {shlex.quote(str(record))}\n"
                      "echo 'espalier 0.1.0'", crlf=False)


def _dirty(tree: Path) -> None:
    """The adopter's own ``.claude/``, committed as a team commits its shared settings."""
    (tree / ".claude" / "agents").mkdir(parents=True)
    (tree / ".claude" / "settings.json").write_bytes(_ADOPTER_SETTINGS)
    (tree / ".claude" / "agents" / "my-reviewer.md").write_bytes(_ADOPTER_AGENT)
    for args in (["add", "-A"], ["commit", "-qm", "our Claude Code settings"]):
        subprocess.run(["git", *args], cwd=tree, check=True, capture_output=True, timeout=45)


def _pasted(remedy: str) -> list[str]:
    """``remedy`` split as the host's shell reads a paste: POSIX rules off
    Windows, and on it the native rules (a backslash is a path separator, not an
    escape), with a quoted token's quotes taken off."""
    if os.name != "nt":
        return shlex.split(remedy)
    return [token[1:-1] if len(token) > 1 and token[0] == token[-1] == '"' else token
            for token in shlex.split(remedy, posix=False)]


def _remedy_argv(text: str, path: str) -> tuple[list[str], str]:
    """``init``'s activate remedy as an operator pastes it, its interpreter
    resolved on ``path`` as their shell resolves it; or no argv and why. Said,
    never raised: a raise here errors every dirty test at setup and hides the
    proving node's own reading of what ``init`` did."""
    found = _ACTIVATE.search(text)
    if not found:
        return [], f"init printed no activate remedy for the adopter's settings:\n{text[-3000:]}"
    argv = _pasted(found["remedy"].strip())
    resolved = shutil.which(argv[0], path=path)
    if not resolved:
        return [], f"init's remedy {found['remedy']!r} names {argv[0]!r}, which is not on this PATH"
    return [resolved, *argv[1:]], ""


@pytest.fixture(scope="module")
def machine(tmp_path_factory, tree: str) -> Machine:
    root = tmp_path_factory.mktemp(f"machine-{tree}")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ESPALIER", "CLAUDE"))}
    env["ESPALIER_AUDIT_DIR"] = str(root / "audit")
    head = [os.path.dirname(sys.executable)]
    record = None
    if tree == "dirty":
        bin_dir = root / "stale bin"
        bin_dir.mkdir()
        record = bin_dir / "calls.txt"
        _stale_espalier(bin_dir, record)
        head.insert(0, str(bin_dir))
    env["PATH"] = os.pathsep.join([*head, os.environ.get("PATH", "")])

    parent = root / ("dirty machine" if tree == "dirty" else "clean")
    repo = build_adopter_tree(parent, stack="python", tree="git",
                              branch="master" if tree == "dirty" else "main")
    if tree == "dirty":
        _dirty(repo)
    m = Machine(repo, env["PATH"], record, {}, {})

    def step(label: str, argv: list[str]) -> subprocess.CompletedProcess:
        run = subprocess.run(argv, cwd=repo, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=90)
        m.runs[label] = run
        settings = repo / ".claude" / "settings.json"
        m.settings[label] = settings.read_bytes() if settings.is_file() else b""
        return run

    cli = [sys.executable, "-m", "espalier.cli"]
    init = step("init", [*cli, "init", "."])
    step("install-ci", [*cli, "install-ci", "."])
    step("doctor", [*cli, "doctor", "."])
    if tree == "dirty":
        remedy, m.remedy_problem = _remedy_argv(init.stdout + init.stderr, env["PATH"])
        if remedy:
            step("remedy", remedy)
    step("upgrade", [*cli, "upgrade", "."])
    step("upgrade --execute", [*cli, "upgrade", ".", "--execute"])
    step("doctor, last", [*cli, "doctor", "."])
    return m


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _doctor(run: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(run.stdout)
    except ValueError:
        raise AssertionError(
            f"doctor printed no JSON report (rc={run.returncode}):\n{_output(run)}") from None


def _output(run: subprocess.CompletedProcess) -> str:
    """What the operator reads from ``run``: its two streams, with a JSON
    report on stdout (``doctor``'s) read as its strings, never its escapes."""
    try:
        report = json.loads(run.stdout)
    except ValueError:
        return run.stdout + run.stderr
    return "\n".join(_strings(report)) + "\n" + run.stderr


def _wired(settings: bytes) -> set[tuple[str, str]]:
    return {(event, script_arg(hook).replace("\\", "/").rsplit("/", 1)[-1])
            for event, hook in iter_hooks(json.loads(settings))}


def _keeps_the_adopters(settings: bytes) -> bool:
    doc = json.loads(settings)
    hooks = [hook for event, hook in iter_hooks(doc) if event == "PreToolUse"]
    return _ADOPTER_HOOK in hooks and _ADOPTER_ALLOW in doc.get("permissions", {}).get("allow", [])


def _push_branches(workflow: str) -> list[str] | None:
    """The branch names a workflow's ``push:`` filter lists inline, or None."""
    push = re.search(r"^  push:\n(?:(?:\s*#.*|\s*)\n)*\s+branches: \[(?P<names>[^\]]*)\]", workflow, re.M)
    return [name.strip().strip("'\"") for name in push["names"].split(",")] if push else None


@pytest.mark.parametrize("tree", TREES, scope="module")
def test_the_install_keeps_what_the_adopter_brought_and_wires_the_harness(machine, tree):
    """The proving node of the registry's ``tree`` cells: on the clean tree
    ``init`` wires every canonical hook itself; on the dirty one, under its
    spaced parent with the stale ``espalier`` first on PATH, ``init`` preserves
    the adopter's file byte for byte, ``doctor`` says the gates are not wired
    and names the remedy, the remedy as printed wires every hook while the
    adopter's own hook, allow rule and agent survive it and ``upgrade
    --execute``, and no verb ran the stale command. On both, ``doctor`` passes
    at the end."""
    m = machine
    if tree == "dirty":
        assert " " in str(m.tree.parent), f"the dirty tree's parent holds no space: {m.tree}"
        assert m.settings["init"] == _ADOPTER_SETTINGS, (
            "init changed the adopter's own .claude/settings.json:\n" + m.settings["init"].decode("utf-8", "replace"))
        assert not m.remedy_problem, m.remedy_problem
    failed = {label: run.returncode for label, run in m.runs.items()
              if run.returncode != 0 and not (tree == "dirty" and label == "doctor")}
    assert not failed, f"verbs that did not exit 0 on the {tree} tree: {failed}"
    canonical = {(spec["event"], script) for script, spec in CANONICAL_HOOK_WIRING.items()}
    missing = canonical - _wired(m.settings["doctor, last"])
    assert not missing, f"the {tree} tree's settings end without these canonical hooks: {sorted(missing)}"
    assert _doctor(m.runs["doctor, last"])["status"] == "pass", _output(m.runs["doctor, last"])[-3000:]

    first = _doctor(m.runs["doctor"])
    if tree == "clean":
        assert canonical <= _wired(m.settings["init"]), "init did not wire the clean tree itself"
        assert first["status"] == "pass", _output(m.runs["doctor"])[-3000:]
        return
    assert first["status"] == "fail" and "merge-settings" in first["primary_reason"], (
        f"doctor before the remedy did not say the gates are unwired: {first['status']}: {first['primary_reason']}")
    lost = [label for label in ("remedy", "upgrade --execute") if not _keeps_the_adopters(m.settings[label])]
    assert not lost, f"the adopter's own hook or allow rule is gone after: {lost}"
    agents = m.tree / ".claude" / "agents"
    assert (agents / "my-reviewer.md").read_bytes() == _ADOPTER_AGENT, "the adopter's own agent was changed"
    assert (agents / "code-reviewer.md").is_file(), "the harness's agents were not deployed beside the adopter's"
    # The stale command resolves first on the verbs' PATH (else an empty record
    # proves nothing), and none of them ran it.
    assert m.record is not None
    resolved = shutil.which("espalier", path=m.path)
    assert resolved and Path(resolved).parent == m.record.parent, (
        f"the stale espalier is not what `espalier` resolves to on the verbs' PATH: {resolved}")
    calls = m.record.read_text(encoding="utf-8", errors="replace") if m.record.exists() else ""
    assert not calls, f"a verb ran the stale espalier first on PATH:\n{calls}"


@pytest.mark.parametrize("tree", TREES, scope="module")
def test_every_remedy_the_verbs_print_runs_on_this_path(machine, tree):
    """Each interpreter a remedy spells before ``-m espalier`` resolves on the
    PATH the verbs ran with, and no line spells the bare ``espalier`` command
    with a verb the cell ran or a remedy named, which on the dirty tree is the
    stale one."""
    m = machine
    texts = {label: _output(run) for label, run in m.runs.items()}
    seen: dict[str, str] = {}
    verbs = {run.args[run.args.index("espalier.cli") + 1] for run in m.runs.values() if "espalier.cli" in run.args}
    for label, text in texts.items():
        for hit in _REMEDY.finditer(text):
            seen.setdefault(hit["quoted"] or hit["word"], label)
            verbs.add(hit["verb"])
    assert seen, f"no verb printed a remedy on the {tree} tree, so this read nothing"
    unresolved = {word: label for word, label in seen.items() if not shutil.which(word, path=m.path)}
    assert not unresolved, f"remedies whose interpreter is not on this PATH (word: first verb): {unresolved}"
    bare = re.compile(r"(?<!-m )(?<![\w./\\-])espalier (?:" + "|".join(map(re.escape, sorted(verbs))) + r")\b")
    spelled = {label: bare.findall(text) for label, text in texts.items() if bare.search(text)}
    assert not spelled, f"lines that spell the bare espalier command: {spelled}"


@pytest.mark.parametrize("tree", TREES, scope="module")
def test_a_push_to_the_trees_own_branch_triggers_the_guard(machine, tree):
    """The workflow ``install-ci`` writes is triggered by a push to the branch
    the tree was made on: ``main`` on the clean tree, ``master`` on the dirty."""
    m = machine
    branch = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=m.tree, capture_output=True,
                            text=True, encoding="utf-8", timeout=45, check=True).stdout.strip()
    assert branch == ("master" if tree == "dirty" else "main")
    names = _push_branches((m.tree / ".github" / "workflows" / "harness-guard.yml").read_text(encoding="utf-8"))
    assert names is not None, "the guard workflow carries no inline push branch filter this test can read"
    assert branch in names, f"a push to {branch!r} does not trigger the guard (push branches: {names})"


@pytest.mark.parametrize("tree", TREES, scope="module")
def test_no_verb_calls_a_render_or_a_backup_the_adopters_work(machine, tree):
    """Beside the adopter's settings ``init`` renders the fresh template as
    ``settings.json.new`` (the clean tree, whose settings ``init`` wrote, gets
    none), and no verb's untracked-work note names a ``.claude/`` render or
    backup as the adopter's uncommitted work with advice to commit it."""
    m = machine
    rendered = (m.tree / ".claude" / "settings.json.new").is_file()
    assert rendered == (tree == "dirty"), f"settings.json.new rendered: {rendered} on the {tree} tree"
    named = {label: [line for line in _output(run).splitlines() if _NAMED_AS_WORK.search(line)]
             for label, run in m.runs.items()}
    named = {label: lines for label, lines in named.items() if lines}
    assert not named, f"verbs that named a render or a backup as the adopter's uncommitted work: {named}"


def test_the_patterns_read_the_lines_they_are_for():
    """Planted lines through the module's own patterns, so a pattern that reads
    nothing cannot pass the tests above by reading nothing."""
    assert _ACTIVATE.search("    To activate (keeps your settings and a .bak of them): python -m espalier "
                            "merge-settings .")["remedy"] == "python -m espalier merge-settings ."
    reads = [(h["quoted"] or h["word"], h["verb"]) for h in _REMEDY.finditer(
        "run `python3 -m espalier upgrade .`; or \"C:\\Program Files\\Py\\python.exe\" -m espalier.cli doctor; "
        "or py -3 -m espalier merge-settings .")]
    assert reads == [("python3", "upgrade"), ("C:\\Program Files\\Py\\python.exe", "doctor"),
                     ("py", "merge-settings")], reads
    if os.name == "nt":
        assert _pasted(r'"C:\Program Files\Py\python.exe" -m espalier merge-settings .') == [
            r"C:\Program Files\Py\python.exe", "-m", "espalier", "merge-settings", "."]
        assert _pasted(r"C:\hostedtoolcache\python.exe -m espalier init .")[0] == r"C:\hostedtoolcache\python.exe"
    assert _NAMED_AS_WORK.search("  .claude/*.new  -- you have uncommitted: .claude/settings.json.new")
    assert _NAMED_AS_WORK.search("  .claude/*.bak  -- you have uncommitted: notes.md, .claude/settings.json.bak")
    assert not _NAMED_AS_WORK.search("  /task-packs/*  -- you have uncommitted: task-packs/TP-1-mine.md")
    assert _push_branches("on:\n  push:\n    # a comment\n\n    branches: [main, 'master']\n") == ["main", "master"]
    assert _push_branches("on:\n  pull_request:\n    branches: [main]\n") is None
