#!/usr/bin/env python3
"""The mechanical half of ``/handoff``, in the order its constraints require.

A handoff is three hand-authored texts -- the ESPALIER_MEMORY.md row, the
working-summary body, the GOAL notes -- wrapped in about eight mechanical
steps whose ORDER matters: the memory file is pruned to its cap before it is
committed; the blueprint is finalized; the memory commit lands BEFORE the
summary and the goal snapshot are written, so both can measure the ahead
count instead of asserting it; the resume index is appended to the summary
body; the handoff leg is appended to this session's archive under the exact
header ``read_summary`` splits on; the record branch is snapshotted AFTER the
goal file is rewritten and then pushed to its remote, because a snapshot
nobody pushes is one disk from gone (31 of 49 were unpushed on 2026-09-07,
DEF-710); and the landing check runs last because everything above it writes
after the session's last verification. The command body
carries a "this runs before that on purpose" warning for each of those, and
each was still a separate tool call done by feel (eight of them on
2026-09-06). This script encodes the order; the three texts stay yours.

Two phases, because the hand-authored texts sit between the mechanical steps::

    # after you have prepended the ESPALIER_MEMORY.md row (and any step-1b
    # promotion under memory/ or docs/):
    python3 scripts/handoff_mechanics.py after-memory-row \\
        --message "docs(memory): <what this session established>" \\
        [--also memory/new-note.md] [--trailer "Claude-Session: <url>"] [--dry-run]

    # after you have written the 9-section body to cc/_working_summary.md
    # and rewritten cc/GOAL.md:
    python3 scripts/handoff_mechanics.py after-goal [--dry-run]

``--dry-run`` on either phase prints the plan and writes nothing (its reads --
the ahead count, the owed probes, the transcript list -- still run). The memory
cap, the co-author trailer and the archive header are READ from their owners
(``post_write_check._MEMORY_MD_CAP``, ``check_handoff_landing.canonical_trailer``,
``read_summary._ARTIFACT_HEADER``), never restated here. Exit codes: 0 done;
2 refused with the reason on stderr (a precondition the hand step owed is
missing, or a sub-step failed -- nothing after a failed step runs).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]
_SUMMARY_REL = "cc/_working_summary.md"
_ARCHIVE_DIR_REL = "cc/blueprints/compact_summaries"
_MEMORY_REL = "ESPALIER_MEMORY.md"
_RESUME_INDEX_MARK = "## Resume index"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def memory_cap(root: Path) -> int:
    """The ESPALIER_MEMORY.md line cap, read from the hook that enforces it."""
    hook = _load(root / "tools" / "cc" / "hooks" / "post_write_check.py", "_pwc_for_handoff")
    return int(hook._MEMORY_MD_CAP)


def rows_to_prune(line_count: int, cap: int) -> int:
    """How many Session-Log rows must be archived to land at or under the cap
    (one row per line over)."""
    return max(0, line_count - cap)


def newest_transcript_stem(list_output: str) -> str | None:
    """The stem of the newest ``[transcript]`` row of ``read_summary.py --list``.
    A ``[durable]`` row is an archive with no live transcript and is never the
    current session."""
    for line in list_output.splitlines():
        m = re.match(r"\s*(\S+)\s+compactions=\d+\s+\[transcript\]", line)
        if m:
            return m.group(1)
    return None


def compose_commit_message(subject: str, trailers: list[str], canonical: str) -> str:
    """Subject, blank line, the canonical co-author trailer, then any extra
    trailers (a session URL line) -- the shape the landing check accepts."""
    lines = [subject.rstrip(), "", canonical]
    lines += [t.strip() for t in trailers if t.strip() and t.strip() != canonical]
    return "\n".join(lines) + "\n"


def summary_body_state(text: str) -> str:
    """``ok`` when the working summary holds a hand-authored body and no resume
    index yet; otherwise the reason it is not ready for ``after-goal``."""
    if not text.strip():
        return "cc/_working_summary.md is empty -- write the 9-section body first (handoff step 6.1)"
    if not text.lstrip().startswith("# Working summary"):
        return "cc/_working_summary.md does not start with '# Working summary' -- is the hand-authored body there?"
    if _RESUME_INDEX_MARK in text:
        return ("cc/_working_summary.md already carries a resume index -- after-goal has run, the "
                "body was not rewritten, or a prior after-goal failed after appending it: delete "
                "the '## Resume index' section and re-run")
    if "## 9." not in text and "9. Optional Next Step" not in text:
        return "cc/_working_summary.md lacks section 9 -- the 9-section body is incomplete"
    return "ok"


def _announce(argv: list[str], dry_run: bool) -> bool:
    """Print the step; True when it should actually run. Every subprocess in this
    file is a LITERAL argv at its own call site (the subprocess-contract scanner
    pins each harness-CLI shape to a sister test in
    tests/test_subprocess_cli_contract.py), never routed through a generic
    runner the scanner cannot resolve."""
    print(("would run: " if dry_run else "run: ") + " ".join(argv))
    return not dry_run


def _ok(proc: subprocess.CompletedProcess, label: str) -> subprocess.CompletedProcess:
    """Exit 2 on a failed sub-step, the code the module docstring promises for a
    refusal; ``raise SystemExit("<text>")`` exits 1, which this repo reads as a
    script bug."""
    if proc.returncode != 0:
        print(f"handoff_mechanics: {label} exited {proc.returncode}; stopping here", file=sys.stderr)
        raise SystemExit(2)
    return proc


def _no_prompt_env() -> dict[str, str]:
    """The environment for a git call that touches the network from an
    automated phase: a credential prompt cannot be answered from a tool call,
    so git must fail instead of waiting on a terminal."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


_NETWORK_TIMEOUT_S = 120


def after_memory_row(root: Path, *, message: str, also: list[str], trailers: list[str],
                     dry_run: bool) -> int:
    memory = root / _MEMORY_REL
    if not memory.is_file():
        print(f"handoff_mechanics: {_MEMORY_REL} missing under {root}", file=sys.stderr)
        return 2
    status = subprocess.run(["git", "status", "--porcelain", "--", _MEMORY_REL],
                            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    if not status:
        print("handoff_mechanics: ESPALIER_MEMORY.md is unmodified -- prepend the session row "
              "first (handoff step 2); 'nothing to commit' is never the answer here",
              file=sys.stderr)
        return 2
    landing = _load(root / "scripts" / "check_handoff_landing.py", "_landing_for_handoff")
    canonical = landing.canonical_trailer()
    if canonical is None:
        print("handoff_mechanics: memory/task-packs.md declares no single Co-Authored-By trailer",
              file=sys.stderr)
        return 2
    # 1. prune to the cap (the hook does this on Write/Edit; a row prepended by
    #    a script or a heredoc lands without it)
    cap = memory_cap(root)
    n = rows_to_prune(len(memory.read_text(encoding="utf-8").splitlines()), cap)
    if n:
        argv = [sys.executable, "-m", "espalier", "memory", "prune", "--rows", str(n)]
        if _announce(argv, dry_run):
            _ok(subprocess.run(argv, cwd=root), "memory prune")
    else:
        print(f"memory at or under the {cap}-line cap; no prune")
    # 2. finalize the blueprint
    argv = [sys.executable, "tools/cc/cognitive_blueprint.py", "finalize"]
    if _announce(argv, dry_run):
        _ok(subprocess.run(argv, cwd=root), "blueprint finalize")
    # 3. stage by explicit path: the memory file, the step-1b paths, and each
    #    path's byte-mirror twin when the registry has one (committing one side
    #    alone reds the parity contract)
    paths = [_MEMORY_REL] + list(also)
    twins: list[str] = []
    syncs: list[str] = []
    sys.path.insert(0, str(root))
    try:
        from espalier import mirror_registry  # type: ignore
        for rel in also:
            for row in mirror_registry.MIRROR_ROWS:
                if mirror_registry.covers(row, rel, root):
                    twin = mirror_registry.counterpart(row, rel)
                    if twin and (root / twin).exists():
                        twins.append(twin)
                    if row.sync not in syncs:
                        syncs.append(row.sync)
    except Exception as exc:  # noqa: BLE001 -- no engine here means no twins to stage
        print(f"(mirror twins not derived: {type(exc).__name__}: {exc})")
    finally:
        sys.path.pop(0)
    # every matched row's OWN sync, read from the registry -- the first cut ran
    # the docs sync only, so a promotion into a skill body staged both twins
    # and synced neither (failure-mode pass, driven). The sync scripts are
    # imported by path and run in-process rather than shelled out.
    import shlex
    for cmd in syncs:
        script = next((t for t in shlex.split(cmd) if t.endswith(".py")), None)
        if script is None:
            print(f"(sync command has no script to import: {cmd})")
            continue
        print(("would run: " if dry_run else "run: ") + cmd)
        if not dry_run:
            rc = _load(root / script, f"_sync_{Path(script).stem}").main([])
            if rc not in (0, None):
                raise SystemExit(f"handoff_mechanics: {cmd} exited {rc}; stopping here")
    paths += [t for t in twins if t not in paths]
    argv = ["git", "add", "--", *paths]
    if _announce(argv, dry_run):
        _ok(subprocess.run(argv, cwd=root), "git add")
    msg = compose_commit_message(message, trailers, canonical)
    if dry_run:
        print("would commit with message:\n" + msg)
    else:
        proc = subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=root, input=msg, text=True, encoding="utf-8")  # decode-errors-ok: the message goes IN through input=; no pipe is captured or decoded
        if proc.returncode != 0:
            raise SystemExit("handoff_mechanics: git commit failed; stopping here")
    # 4. the number GOAL.md may now quote: derived after the commit, never carried
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    ahead = subprocess.run(["git", "rev-list", "--count", f"origin/{branch}..{branch}"],
                           cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ahead.returncode == 0:
        print(f"ahead of origin/{branch}: {ahead.stdout.strip()}  (write this into cc/GOAL.md)")
    else:
        print(f"no origin/{branch} to count against")
    # 5. the owed-list probes, so step 7's rewrite starts from their verdicts
    #    rather than from the list the banner carried in (sub-second)
    owed = subprocess.run([sys.executable, "scripts/check_handoff_landing.py", "--skip-tests",
                           "--skip-trailer", "--skip-keys"], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("owed-list probes:")
    print(owed.stdout.strip() or "(no output)")
    if owed.returncode != 0:
        print(owed.stderr.strip())
    print("next: write cc/GOAL.md (notes first -- the banner opens on them), then "
          "cc/_working_summary.md (9 sections), then run after-goal")
    return 0


def after_goal(root: Path, *, dry_run: bool) -> int:
    summary = root / _SUMMARY_REL
    state = summary_body_state(summary.read_text(encoding="utf-8") if summary.is_file() else "")
    if state != "ok":
        print(f"handoff_mechanics: {state}", file=sys.stderr)
        return 2
    goal = root / "cc" / "GOAL.md"
    if goal.is_file():
        # a stale date is the visible staleness signal the goal file exists for;
        # find the line, never a line INDEX (a blank line shifts an index)
        import datetime as _dt
        today = _dt.date.today().isoformat()
        updated = next((ln for ln in goal.read_text(encoding="utf-8").splitlines()
                        if ln.lstrip().startswith("_Updated:")), "")
        if updated and today not in updated:
            print(f"handoff_mechanics: cc/GOAL.md's _Updated line does not carry today ({today}): "
                  f"{updated.strip()[:60]!r} -- rewrite the goal snapshot first (handoff step 7); "
                  "if the session crossed midnight, restamp it: the date is the staleness "
                  "signal, not a typo", file=sys.stderr)
            return 2
    # 0. resolve the archive stem BEFORE anything is appended, so a failure here
    #    cannot leave the resume index in place and block the retry
    listing = subprocess.run([sys.executable, "tools/cc/read_summary.py", "--list"], cwd=root,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
    stem = newest_transcript_stem(listing.stdout)
    if stem is None:
        print("handoff_mechanics: read_summary --list shows no [transcript] row; cannot place "
              "the archive leg; nothing appended", file=sys.stderr)
        return 2
    # 1. the resume index, appended beneath the hand-authored body
    argv = [sys.executable, "tools/cc/session_summary.py"]
    if _announce(argv, dry_run):
        idx = _ok(subprocess.run(argv, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace"), "session_summary")
        with summary.open("a", encoding="utf-8") as fh:
            fh.write(idx.stdout if idx.stdout.startswith("\n") else "\n" + idx.stdout)
    # 2. the archive leg for THIS session, under the header read_summary splits on
    rs = _load(root / "tools" / "cc" / "read_summary.py", "_read_summary_for_handoff")
    header = f"\n\n===== compaction captured (transcript {stem}) =====\n\n"
    assert rs._ARTIFACT_HEADER.search(header), "archive header drifted from read_summary's splitter"
    leg = root / _ARCHIVE_DIR_REL / f"{stem}.md"
    print(("would append" if dry_run else "append") + f" the handoff leg to {leg.relative_to(root)}")
    if not dry_run:
        leg.parent.mkdir(parents=True, exist_ok=True)
        block = header + summary.read_text(encoding="utf-8")
        # Idempotent: a later step in this phase can fail (the record push
        # reaches the network) and the re-run must not append the leg twice.
        existing = leg.read_text(encoding="utf-8") if leg.is_file() else ""
        if existing.endswith(block):
            print("  (the leg already ends with this session's block; not appended twice)")
        else:
            with leg.open("a", encoding="utf-8") as fh:
                fh.write(block)
    # 3. the record branch, after the goal file was rewritten
    argv = [sys.executable, "scripts/record_snapshot.py"]
    if _announce(argv, dry_run):
        _ok(subprocess.run(argv, cwd=root), "record snapshot")
    # 3b. push it: the record exists for what the tracked tree does not carry,
    #     and until 2026-09-14 the only off-disk copy was whatever the last
    #     manual push left (DEF-710). The ref is READ from its owner, never
    #     restated. The FIRST push of a record stays a deliberate act: the
    #     exclusion vocabulary binds at write time and history is forever, so
    #     `--audit-history` must run before anything leaves the disk -- the
    #     remote is probed and a missing ref refuses with that instruction.
    #     A plain push -- the record is append-only and chains onto the
    #     remote tip, so it fast-forwards; never --force. No prompt, a bounded
    #     wait, and a refusal (no remote, a diverged ref, credentials the
    #     helper could not supply) stops the phase HERE, loudly, before the
    #     landing check: the landing check's exit code is this phase's, and a
    #     green landing over an unpushed record would read as done.
    #     The REMOTE is read from the same owner, once (DEC-31): the
    #     checkout-local `espalier.recordRemote` key when set, else `origin`.
    #     On the public checkout that key names the private archive, so the
    #     record never reaches the public remote; a literal `origin` at any of
    #     the three sites below would publish it.
    rs_owner = _load(root / "scripts" / "record_snapshot.py", "_record_snapshot_for_handoff")
    record_ref = str(rs_owner.RECORD_REF)
    branch = record_ref.rsplit("/", 1)[-1]
    assert record_ref.startswith("refs/heads/") and branch, "record_snapshot.RECORD_REF is not a branch ref"
    try:
        remote = str(rs_owner.record_remote(root))
    except getattr(rs_owner, "RecordError", RuntimeError) as exc:
        # The owner refuses (the key is required by espalier.toml and unset, or
        # the config could not be read): no probe, no push, the phase stops
        # here -- the default would be the publishing direction.
        print(f"handoff_mechanics: record remote unresolved -- {exc}", file=sys.stderr)
        return 2
    if not remote or "/" in remote or ":" in remote or remote.startswith("-"):
        print(f"handoff_mechanics: record remote {remote!r} is not a remote name; refusing to push",
              file=sys.stderr)
        return 2
    probe = ["git", "ls-remote", "--exit-code", remote, record_ref]
    if _announce(probe, dry_run):
        try:
            seen = subprocess.run(probe, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=_NETWORK_TIMEOUT_S, env=_no_prompt_env())
        except subprocess.TimeoutExpired:
            print(f"handoff_mechanics: record remote probe timed out after {_NETWORK_TIMEOUT_S}s; "
                  "stopping here", file=sys.stderr)
            return 2
        if seen.returncode == 2:
            print(f"handoff_mechanics: {remote} has no {record_ref} yet -- the first push is the "
                  "deliberate act: run `python3 scripts/record_snapshot.py --audit-history`, "
                  f"then `git push {remote} {branch}` by hand, then re-run after-goal", file=sys.stderr)
            return 2
        _ok(seen, "record remote probe")
    argv = ["git", "push", remote, branch]
    if _announce(argv, dry_run):
        try:
            proc = subprocess.run(argv, cwd=root, timeout=_NETWORK_TIMEOUT_S, env=_no_prompt_env())
        except subprocess.TimeoutExpired:
            print(f"handoff_mechanics: record push timed out after {_NETWORK_TIMEOUT_S}s; "
                  "stopping here", file=sys.stderr)
            return 2
        _ok(proc, "record push")
    # 4. the landing check, last: its exit code is this phase's
    argv = [sys.executable, "scripts/check_handoff_landing.py"]
    if not _announce(argv, dry_run):
        return 0
    proc = subprocess.run(argv, cwd=root)
    return 0 if proc.returncode == 0 else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(_ROOT))
    sub = ap.add_subparsers(dest="phase", required=True)
    a = sub.add_parser("after-memory-row", help="prune to cap, finalize, commit the memory row by explicit path")
    a.add_argument("--message", required=True, help="the commit subject/body (trailers are added)")
    a.add_argument("--also", action="append", default=[], help="a step-1b path to stage too (repeatable)")
    a.add_argument("--trailer", action="append", default=[], help="an extra trailer line, e.g. Claude-Session: <url>")
    g = sub.add_parser("after-goal", help="resume index, archive leg, record snapshot + push, landing check")
    for sp in (a, g):   # the flag rides on the phase, where a caller types it
        sp.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.phase == "after-memory-row":
        return after_memory_row(root, message=args.message, also=args.also,
                                trailers=args.trailer, dry_run=args.dry_run)
    return after_goal(root, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
