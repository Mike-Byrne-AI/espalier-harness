#!/usr/bin/env python3
"""Execution plan tracker — multi-phase task state with verification gates.

Tracks step-by-step execution of complex tasks:
- Create a plan with file-level change manifest
- Mark steps as running/passed/failed
- Resume from last successful step after interruption
- Report overall status

Storage: cc/execution_plan.json

Usage:
    python tools/cc/execution_plan.py create --task "..." --steps "step1|step2|step3"
    python tools/cc/execution_plan.py status
    python tools/cc/execution_plan.py mark <step_index> passed|failed [--note "..."]
    python tools/cc/execution_plan.py reset
"""
from __future__ import annotations
import argparse, hashlib, json, os, stat, subprocess, sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Sibling-import the dual-scope JSON chokepoint. Python adds
# this script's own dir to sys.path when run directly; the explicit insert
# also covers importlib/embedded callers. Mirrors _paths/_freshness_cache.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import load_json_dict_safe  # noqa: E402
import _paths  # noqa: E402

# Forced twin of _blueprint_limits.BLUEPRINT_COLD_DIR_NAME. Copied rather
# than imported for the same reason _AJ_MAX_FIELD_CHARS below is: a new
# sibling import here would have to be added to every fixture that copies
# a subset of tools/cc, and a script copied without its deps fails
# SILENTLY in its subprocess.
_COLD_DIR_NAME = "_cold"

# Keys required for an execution_plan step's action_justification
# nested dict. The planner subprocesses to cognitive_blueprint.py justify
# on `mark <i> running` if the dict is populated; absence emits an
# advisory (both branches non-blocking).
_AJ_REQUIRED_KEYS = (
    "goal", "step_rationale", "expected_outcome", "not_doing",
    "tool", "content_hash",
)

# Mirrors cognitive_blueprint._AJ_MAX_FIELD_CHARS. Copied rather than imported:
# this script subprocesses to that CLI on purpose (see
# _record_justification_via_subprocess), and a sibling import here would have to
# be threaded through every fixture that hand-copies a tools/cc subset. Same
# forced-copy shape as cognitive_blueprint._AJ_MUTATION_TOOLS_TOKENS, and pinned the
# same way by tests/test_forced_copy_parity.py::TestActionJustificationFieldCapParity,
# so a cap change on either side reds instead of silently reintroducing the overflow
# this clamp exists to prevent. (This comment first cited
# test_execution_plan_auto_justification.py, which imports the VALIDATOR's cap and
# never reads the planner's -- it would not have caught a drift in either direction.)
_AJ_MAX_FIELD_CHARS = 500
# Marks a clamped field so a reader can tell a short rationale from a cut one.
_AJ_TRUNCATION_MARKER = " [...clamped]"
# Mirrors cognitive_blueprint._EXIT_JUSTIFICATION_REFUSED, and pinned equal by the
# same contract as the cap. ONLY this code says the payload was bad; every other
# non-zero means the write did not happen for an unrelated reason and is not
# evidence against a justification already on the step.
_EXIT_JUSTIFICATION_REFUSED = 2

# Status glyphs for the `status` command's per-step render (hoisted out of
# the print loop — constant per iteration).
_STATUS_ICONS = {"passed": "+", "failed": "X", "pending": ".", "running": ">"}


def _plan_path() -> Path:
    """Resolve cc/execution_plan.json under the repo root.

    Uses the single owner _paths._repo_root (env ``CLAUDE_PROJECT_DIR`` →
    nearest pyproject/tools/cc ancestor → cwd) so launching Claude Code from a
    subdirectory still writes the plan where plan_guard can find it.
    """
    return _paths._repo_root() / "cc" / "execution_plan.json"


def _iso(): return datetime.now(timezone.utc).isoformat()

def _load():
    p = _plan_path()
    if not p.exists(): return None
    # Bytes: the helper decodes tolerantly; a strict read raised past OSError (DEF-829).
    try: return load_json_dict_safe(p.read_bytes(), default=None)
    except OSError: return None

# Flags for the writer's per-call tempfile; the POSIX-only flags fall back to
# 0, a no-op OR (docs/SHARP_EDGES.md "POSIX-only os.O_* flags need getattr
# guards for Windows"). Twin of _hook_utils._TEMPFILE_OPEN_FLAGS.
_TEMPFILE_OPEN_FLAGS = (
    os.O_RDWR | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomic write helper, the fourth copy.

    Inlined copy of ``tools/cc/hooks/_hook_utils.atomic_write_text`` for the
    same reason ``cognitive_blueprint.py`` carries one: this script runs
    standalone, and a sibling import from ``hooks/`` would have to be threaded
    through every fixture that copies a subset of ``tools/cc``. Same algorithm,
    same invariants -- including the target-identity contract in that
    docstring: an existing regular file keeps its mode, a fresh file gets the
    mode ``open()`` would give, a symlinked state file is replaced by a regular
    file (the engine's copy takes a ``follow_symlinks`` keyword for the
    adopter's own files; this one writes state only), a hardlink is severed.
    Bug fixes must be applied to every copy (``tests/test_atomic_io.py`` runs
    each test over all four and derives the roster of copies from the tree).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened with mode 0o666 so the kernel applies the umask -- what open()
    # gives a fresh file -- where tempfile.mkstemp hardcodes 0o600 and every
    # file the harness wrote ended group-unreadable (DEF-783). The visible
    # name is capped at 64 chars for Windows MAX_PATH.
    prefix = f".{path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(str(path.parent), prefix + os.urandom(4).hex() + ".tmp")
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
        except PermissionError:
            # NT raises this, not FileExistsError, when a DIRECTORY bears
            # the chosen name (the case tempfile.mkstemp retries); anything
            # else is a real refusal.
            if os.name == "nt" and os.path.isdir(tmp_path):
                continue
            raise
    else:
        raise FileExistsError(f"no free tempfile name beside {path}")
    f = None
    try:
        if hasattr(os, "fchmod"):
            # An existing regular target keeps its bits; a symlink or other
            # non-regular file at the path is not a mode to copy. A refused
            # fchmod leaves the umask mode rather than failing the write.
            try:
                st = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.fchmod(fd, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        # newline="" writes \n verbatim. Default text mode translates \n -> \r\n
        # on Windows, which inflates serialized byte-size and breaks
        # cross-platform byte-parity of hashed JSON state.
        f = os.fdopen(fd, "w", encoding=encoding, newline="")
        with f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:  # noqa: BLE001 -- unlink the tempfile on ANY failure, then re-raise
        # Not just OSError: a TypeError (non-serializable plan) or
        # UnicodeEncodeError raised inside the with-block above would otherwise
        # leave the tempfile orphaned.
        if f is None:
            # fdopen itself raised (an unknown encoding): the fd is still ours.
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _save(plan):
    _atomic_write_text(_plan_path(), json.dumps(plan, indent=2) + "\n")


@contextmanager
def _plan_lock():
    """Serialize the load->mutate->save critical section of ``cmd_mark`` against
    a concurrent ``mark`` (e.g. a git-capable subagent sharing the live tree).

    POSIX ``flock``; on Windows (no ``fcntl``) or a flock-less FS (some NFS /
    network mounts) the lock degrades to a best-effort no-op rather than crash
    -- the same documented posture as ``_speedbump``'s
    ``_locked_check_and_increment``. ``_save`` is already atomic (a tempfile beside
    the plan, then os.replace -- ``_atomic_write_text``), so the degrade risks
    only a lost update on true concurrency, never a torn file.

    Only lock ACQUISITION (lockfile create + the ``flock`` syscall) is guarded
    by ``try/except OSError``: on a POSIX host where ``fcntl`` imports fine but
    the underlying FS is flock-less, the ``flock`` *syscall* raises ``OSError``
    and we degrade to an unlocked write rather than crash ``cmd_mark``. A
    body-raised ``OSError`` (a real ``_save`` failure -- disk full, read-only,
    a permission-broken plan file) must propagate as ITSELF, so the body
    ``yield`` sits OUTSIDE the acquisition guard: catching it there would
    re-yield into an already-throwing generator and surface a misleading
    ``RuntimeError: generator didn't stop after throw()`` in place of the true
    I/O error.
    """
    try:
        import fcntl  # POSIX only
    except ImportError:
        yield
        return
    lock_path = _plan_path().with_name(_plan_path().name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = open(lock_path, "w", encoding="utf-8")
    except OSError:
        # Lock ACQUISITION failed (flock-less FS can't create the lockfile, a
        # read-only dir, etc.): degrade to an unlocked write rather than crash.
        yield
        return
    try:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            # flock syscall unsupported on this FS: degrade to an unlocked write.
            yield
            return
        # Body runs UNGUARDED by the acquisition except -- a body-raised OSError
        # (a real _save failure) propagates as itself, not a masked RuntimeError.
        try:
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    finally:
        lock_fh.close()

def cmd_create(task, steps, goal="", not_doing=""):
    plan = {
        "task": task,
        "created": _iso(),
        "status": "in_progress",
        "goal": goal,
        "not_doing": not_doing,
        "steps": [
            {"index": i, "description": s.strip(), "status": "pending", "note": "", "timestamp": ""}
            for i, s in enumerate(steps.split("|"))
        ],
    }
    _save(plan)
    print(f"Created plan: {task}")
    print(f"Steps: {len(plan['steps'])}")
    for s in plan["steps"]:
        print(f"  [{s['index']}] {s['description']}")
    return 0

def cmd_status():
    plan = _load()
    if not plan: print("No active plan.", file=sys.stderr); return 1
    # _load returns a dict-or-None (json safe), but a hand-edited /
    # older-schema execution_plan.json can be a valid non-empty dict
    # missing `steps`; guard so the `plan["steps"]` subscripts below
    # degrade gracefully instead of raising an uncaught KeyError.
    if not isinstance(plan.get("steps"), list):
        print("Plan file is malformed (no steps list).", file=sys.stderr); return 1
    passed = sum(1 for s in plan["steps"] if s["status"] == "passed")
    failed = sum(1 for s in plan["steps"] if s["status"] == "failed")
    pending = sum(1 for s in plan["steps"] if s["status"] == "pending")
    total = len(plan["steps"])
    print(f"Task: {plan.get('task', '?')}")
    print(f"Status: {plan.get('status', '?')} ({passed}/{total} passed, {failed} failed, {pending} pending)")
    for s in plan["steps"]:
        mark = _STATUS_ICONS.get(s["status"], "?")
        note = f" -- {s['note']}" if s.get("note") else ""
        print(f"  [{mark}] {s['index']}: {s['description']}{note}")
    # Show next step
    next_step = next((s for s in plan["steps"] if s["status"] == "pending"), None)
    if next_step:
        print(f"\nNext: step {next_step['index']} -- {next_step['description']}")
    return 1 if plan.get("status") == "blocked" else 0

def _parse_justification_fields(pairs):
    """Parse k=v ... pairs into a justification dict. Raises ValueError on
    missing required keys."""
    out = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError(f"justification field must be k=v, got: {p!r}")
        k, _, v = p.partition("=")
        out[k.strip()] = v
    missing = [k for k in _AJ_REQUIRED_KEYS if k not in out]
    if missing:
        raise ValueError(f"justification missing required keys: {missing}")
    return out


def _clamp_prose(text):
    """Fit a composed prose field to the validator's cap, marking the cut.

    The composed rationale is the step DESCRIPTION verbatim, and this repo's
    pack conventions make step descriptions long -- files, proof and rollback
    all live in one string. Without a clamp the relationship is inverted: the
    more carefully a step is written, the more certainly it overflows and the
    justification is refused, so the steps that most need an audit trail are
    exactly the ones that lose it. A marked truncation keeps the trail and says
    where it was cut, which is strictly better than no record at all.
    """
    if len(text) <= _AJ_MAX_FIELD_CHARS:
        return text
    keep = _AJ_MAX_FIELD_CHARS - len(_AJ_TRUNCATION_MARKER)
    return text[:keep] + _AJ_TRUNCATION_MARKER


def _compose_phase_justification(plan, step):
    """Build an action_justification dict from plan + step metadata.

    Returns None unless BOTH plan-level 'goal' AND 'not_doing' are
    populated. Requiring both prevents silently fabricating an audit-
    trail field the author never wrote: if 'not_doing' is empty, the
    advisory path fires instead of inventing a default.

    The recorded ``content_hash`` is sha256(task|index|description) --
    plan-metadata-shaped. ``post_write_check``'s matcher gates on
    timestamp + AJ-presence only; the recorded hash is an
    audit-trail field, not a matching field. See
    ``docs/HOOK_ASSUMPTIONS.md`` "Action-justification matching" for
    the trade-off rationale.

    The hash is over the RAW description, deliberately, even when the recorded
    ``step_rationale`` was clamped: it identifies the step, and re-keying it on the
    truncated text would make the same step hash differently once its description
    grew past the cap. The consequence to know about is that
    ``sha256(task|index|step_rationale)`` does NOT reproduce it for a clamped entry
    -- pinned by ``TestComposeHashIsOverTheRawDescription`` so an audit tool built on
    that assumption fails a test rather than looking like data corruption.
    """
    # Stripped, coerced, and INCLUDING desc: the validator rejects prose that is
    # empty after .strip(), and two composed paths reached it -- a doubled pipe in
    # --steps ("a||b") yields an empty description, and a whitespace-only --goal
    # passes a bare truthiness test. Both then arrived at the validator as a
    # REFUSAL, which told the operator to fix a payload when the real problem was a
    # malformed plan. Returning None here routes them to the advisory instead, which
    # names the actual remedy. str() also stops a hand-edited non-str description
    # from crashing the clamp with a traceback about prose length.
    goal = str(plan.get("goal") or "").strip()
    not_doing = str(plan.get("not_doing") or "").strip()
    desc = str(step.get("description") or "").strip()
    if not goal or not not_doing or not desc:
        return None
    task_id = plan.get("task", "")
    raw_hash = hashlib.sha256(
        f"{task_id}|{step.get('index', '')}|{desc}".encode()
    ).hexdigest()
    return {
        "goal": _clamp_prose(goal),
        "step_rationale": _clamp_prose(desc),
        "expected_outcome": _clamp_prose(f"{desc}: targeted proof passes"),
        "not_doing": _clamp_prose(not_doing),
        "tool": "Bash",
        "content_hash": f"sha256:{raw_hash}",
    }


def _record_justification_via_subprocess(justification):
    """Subprocess to cognitive_blueprint.py justify (isolation rule:
    execution_plan.py cannot import from espalier; the sibling
    hook-side CLI handles validation + write).

    Returns (returncode, stderr)."""
    script = Path(__file__).parent / "cognitive_blueprint.py"
    cmd = [
        sys.executable, str(script), "justify",
        "--goal", justification["goal"],
        "--step-rationale", justification["step_rationale"],
        "--expected-outcome", justification["expected_outcome"],
        "--not-doing", justification["not_doing"],
        "--tool", justification["tool"],
        "--content-hash", justification["content_hash"],
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stderr


def cmd_mark(index, status, note="", justification=None):
    # Serialize the whole read-modify-write under a file lock so a concurrent
    # `mark` (e.g. a git-capable subagent sharing the tree) can't lose an
    # update. Early returns inside the `with` release the lock via the CM's
    # finally; the display print/cmd_status below stay outside the section.
    with _plan_lock():
        plan = _load()
        if not plan: print("No active plan.", file=sys.stderr); return 1
        # Guard a malformed plan (valid dict, no `steps` list) before the
        # raw `plan["steps"]` subscripts crash.
        if not isinstance(plan.get("steps"), list):
            print("Plan file is malformed (no steps list).", file=sys.stderr); return 1
        if index < 0 or index >= len(plan["steps"]):
            print(f"Invalid step index: {index}", file=sys.stderr)
            return 1
        step = plan["steps"][index]
        step["status"] = status
        step["timestamp"] = _iso()
        if note: step["note"] = note

        # Planner trigger. On `mark <i> running`, record
        # action_justification via the sibling CLI if available, else advise.
        # When no explicit / no pre-populated justification AND the
        # plan carries top-level goal+not_doing, auto-compose from metadata.
        if status == "running":
            effective = justification if justification is not None else step.get(
                "action_justification"
            )
            if effective is None:
                effective = _compose_phase_justification(plan, step)
            if effective:
                # Write the step's justification ONLY after the validator has
                # accepted it. Assigning first and validating second left the
                # plan asserting a justification the blueprint never received:
                # post_write_check's matcher gates on AJ-PRESENCE, so a payload
                # the validator refused still read as compliant, and the two
                # records disagreed with the plan being the reassuring one.
                rc, stderr = _record_justification_via_subprocess(effective)
                if rc == 0:
                    step["action_justification"] = effective
                elif rc == _EXIT_JUSTIFICATION_REFUSED:
                    # Refused payloads are not kept, whatever their source. A
                    # rejected justification on disk is worse than none: it
                    # satisfies a presence check while certifying nothing.
                    step.pop("action_justification", None)
                    print(
                        f"[execution_plan] action_justification REFUSED for step "
                        f"{index} and NOT recorded (rc={rc}); the step is running "
                        f"without one. stderr: {stderr.strip()}",
                        file=sys.stderr,
                    )
                else:
                    # Anything else -- no active blueprint above all -- validated
                    # NOTHING, so it is not evidence against the payload. Dropping
                    # here would delete a justification the validator may already
                    # have accepted and written, which is the first failure mode
                    # inverted: the plan would then claim LESS than the blueprint.
                    # Re-marking a step running with the blueprint absent is the
                    # documented resume path, so this is a normal sequence.
                    print(
                        f"[execution_plan] action_justification NOT RECORDED for "
                        f"step {index} (rc={rc}) -- the payload was not refused, "
                        f"there was nowhere to write it. Any justification already "
                        f"on the step is kept. stderr: {stderr.strip()}",
                        file=sys.stderr,
                    )
            else:
                desc = step.get("description", "")
                print(
                    f"[execution_plan] step {index} {desc!r} starting without "
                    "action_justification -- capture rationale via "
                    "cognitive_blueprint justify or extend the step with "
                    "--justification-fields k=v ...",
                    file=sys.stderr,
                )
        # Update overall status. The else clause is load-bearing: without it,
        # status was sticky at "blocked" forever once any step had ever been
        # failed — so cmd_status() returned exit 1 on every subsequent mark
        # even when the failed step had been re-marked passed. The transition
        # back to in_progress when no steps are currently failed (and not all
        # are passed) is the correct shape.
        if all(s["status"] == "passed" for s in plan["steps"]):
            plan["status"] = "complete"
        elif any(s["status"] == "failed" for s in plan["steps"]):
            plan["status"] = "blocked"
        else:
            plan["status"] = "in_progress"
        _save(plan)
    print(f"Step {index}: {status}")
    return cmd_status()

def cmd_reset():
    p = _plan_path()
    if p.exists():
        # A cleared plan is reasoning -- what was attempted and in what
        # order. Demote it beside the blueprint cold store rather than
        # unlinking; a reset is a working-set operation, not a decision
        # to destroy the record. Best-effort: if the demotion cannot be
        # written the reset still has to succeed, so fall back to unlink
        # rather than stranding an active plan the operator asked to clear.
        cold = p.parent / _COLD_DIR_NAME
        try:
            cold.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            p.replace(cold / f"{stamp}-{p.name}")
            # Name the directory from the repo root (``cc/_cold/``): the bare
            # ``_cold/`` sent the reader looking beside wherever they stood.
            try:
                shown = cold.relative_to(_paths._repo_root()).as_posix()
            except ValueError:
                shown = str(cold)
            print(f"Plan cleared (demoted to {shown}/).")
        except OSError:
            p.unlink()
            print("Plan cleared.")
    else:
        print("No active plan.")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execution plan tracker")
    sub = parser.add_subparsers(dest="action", required=True)
    p_create = sub.add_parser("create", help="create execution plan")
    p_create.add_argument("--task", required=True)
    p_create.add_argument("--steps", required=True, help="pipe-separated step descriptions")
    p_create.add_argument("--goal", default="",
                          help="one-line motivation; enables auto-compose of "
                               "action_justification on mark running for every "
                               "step (requires --not-doing also set)")
    p_create.add_argument("--not-doing", default="",
                          help="one-line scope-out; required together with --goal "
                               "to enable auto-compose")
    sub.add_parser("status", help="show plan status")
    p_mark = sub.add_parser("mark", help="mark step status")
    p_mark.add_argument("index", type=int)
    p_mark.add_argument("result", choices=["passed", "failed", "running"])
    p_mark.add_argument("--note", default="")
    # Planner trigger: justification capture on `mark <i> running`.
    _aj_src = p_mark.add_mutually_exclusive_group()
    _aj_src.add_argument(
        "--justification-fields", nargs="+", default=None,
        metavar="K=V",
        help="record action_justification on this step; required keys: "
             "goal step_rationale expected_outcome not_doing tool content_hash"
    )
    _aj_src.add_argument(
        "--justification-json", type=Path, default=None,
        help="path to JSON file with action_justification dict"
    )
    sub.add_parser("reset", help="clear active plan")
    args = parser.parse_args(argv)
    if args.action == "create":
        return cmd_create(args.task, args.steps,
                          goal=args.goal, not_doing=args.not_doing)
    if args.action == "status":
        return cmd_status()
    if args.action == "mark":
        justification = None
        if getattr(args, "justification_json", None):
            # A non-dict justification file → None (treated as
            # "no justification" by cmd_mark), never an AttributeError crash.
            justification = load_json_dict_safe(
                args.justification_json.read_text(encoding="utf-8", errors="replace"),
                default=None,
            )
        elif getattr(args, "justification_fields", None):
            justification = _parse_justification_fields(args.justification_fields)
        return cmd_mark(
            args.index, args.result,
            getattr(args, "note", ""),
            justification=justification,
        )
    if args.action == "reset":
        return cmd_reset()
    return 2

if __name__ == "__main__":
    # UTF-8 on both streams, whatever the console code page: on Windows a
    # redirected stream defaults to the ANSI page, a non-ASCII character in
    # the CONTENT this prints (a plan's text, a recall title, a memory row)
    # goes out as cp1252, and a parent decoding UTF-8 loses the whole stream
    # (CPython's Windows communicate() answers None for a reader thread that
    # died; Portability, 2026-09-24). Content is the operator's and may be
    # anything; the messages around it stay 7-bit ASCII by rule.
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
