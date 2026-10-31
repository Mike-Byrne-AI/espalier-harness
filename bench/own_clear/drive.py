#!/usr/bin/env python3
"""Drive the shipped own-clear mod through a real interactive Claude Code
session in a pty, and read the result from hook payloads on disk, never the
screen.

The sequence, against a throwaway repository with a settings-hook log as the
oracle:

1. ``claude --plugin-dir tools/cc/mods/own-clear`` starts in the throwaway;
   the trust dialog is answered (Down, Enter); a first prompt runs to its Stop,
   which names the session id in the log.
2. The marker is armed for that id by the real writer
   (``tools/cc/ship.py::arm_own_clear``) with a one-line brief.
3. ``/compact`` is typed: the mod's ``session.compact`` hook must refuse it
   (its log says so, and no PreCompact reaches the settings hooks).
4. A second prompt runs: at its turn's end the mod runs the real ``/clear``
   (SessionEnd reason=clear, SessionStart source=clear with a new id), reads
   the marker on that start, consumes it, and submits the brief, which lands
   as a UserPromptSubmit in the new session and runs to its Stop.

Exit 0 when every step is seen, 1 otherwise, with the logs kept under the
output directory (``reports/own-clear-drive-<stamp>/`` by default, gitignored);
2, before anything is written, on a host with no pty.
Interactive only: in ``claude -p`` the process exits right after the clear, so
the re-prime never runs there (measured 2026-10-26). POSIX (pty); the Windows
seats are driven by hand.

Usage: python bench/own_clear/drive.py [--mod DIR] [--out DIR] [--model NAME]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import select
import signal
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The pty is POSIX. The module still loads on Windows -- the bounded-spawn
# census (tests/test_contracts.py::TestEveryTimedSpawnOutsideToolsCcIsBounded)
# imports every file outside the engine that routes a spawn, to read which
# run_bounded it bound, and a bare `import fcntl` here was its windows-latest
# red from #351 -- and main() refuses by name before it writes anything.
try:
    import fcntl
    import pty
    import termios
except ImportError:   # Windows: no pty; the Windows seats are driven by hand
    fcntl = pty = termios = None   # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "tools" / "cc" / "mods" / "own-clear"
#: What a running session sets in its children; carried into the drive's
#: session they would make it a nested child of this one (tools/cc/seat.py
#: strips the same names, and the own-clear's own two beside them).
STRIP = (
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT", "CLAUDE_PROJECT_DIR",
    "CLAUDE_CODE_PLUGIN_DIRS", "ESPALIER_MAINTENANCE_MODE", "ESPALIER_OWN_CLEAR_ROOT", "ESPALIER_OWN_CLEAR_LOG",
)
LOGHOOK = '''import json, os, sys, time
raw = sys.stdin.read()
try:
    d = json.loads(raw) if raw.strip() else {}
except Exception:
    d = {"unparsed": raw[:200]}
row = {"t": round(time.time(), 2), "event": d.get("hook_event_name"), "source": d.get("source"),
       "reason": d.get("reason"), "trigger": d.get("trigger"), "prompt": (d.get("prompt") or "")[:80],
       "session": d.get("session_id") or ""}
with open(os.environ["OWN_CLEAR_DRIVE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\\n")
'''
EVENTS = ("SessionStart", "SessionEnd", "PreCompact", "UserPromptSubmit", "Stop")
BRIEF = "Reply with the single word primed."


def _bounded_spawn():
    """``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, loaded
    by path, never an installed engine's: ``subprocess.run`` whose timeout
    holds on Windows, where ``run`` waits on a grandchild holding its pipe."""
    spec = importlib.util.spec_from_file_location(
        "_json_safe_for_own_clear_drive", REPO / "tools" / "cc" / "_json_safe.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_bounded


run_bounded = _bounded_spawn()


def _load_ship():
    tools = REPO / "tools" / "cc"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location("_own_clear_drive_ship", tools / "ship.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    done = run_bounded(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, check=True, timeout=45)
    return done.stdout.strip()


def _throwaway(out: Path, python: str) -> Path:
    repo = out / "repo"
    (repo / ".claude").mkdir(parents=True)
    loghook = out / "loghook.py"
    loghook.write_text(LOGHOOK, encoding="utf-8")
    hook = {"hooks": [{"type": "command", "command": f"{python} {loghook}"}]}
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {ev: [hook] for ev in EVENTS}}, indent=2), encoding="utf-8")
    (repo / ".gitignore").write_text(".espalier-state/\n.claude/\n", encoding="utf-8")
    (repo / "README.md").write_text("own-clear drive\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "drive"), ("user.email", "drive@example.invalid"), ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


class Drive:
    def __init__(self, repo: Path, out: Path, mod: Path, model: str) -> None:
        self.repo, self.out = repo, out
        self.hooks_log = out / "hooks.jsonl"
        self.mod_log = out / "mod.jsonl"
        self.screen = (out / "screen.txt").open("wb")
        self.alive = True
        env = {k: v for k, v in os.environ.items() if k not in STRIP}
        env.update({"OWN_CLEAR_DRIVE_LOG": str(self.hooks_log), "ESPALIER_OWN_CLEAR_LOG": str(self.mod_log)})
        env.setdefault("TERM", "xterm-256color")
        for f in (self.hooks_log, self.mod_log):
            f.write_text("", encoding="utf-8")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(repo)
            os.execvpe("claude", ["claude", "--plugin-dir", str(mod), "--model", model], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))

    def pump(self, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.2)
            if ready:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    self.alive = False
                    return False
                if not data:
                    self.alive = False
                    return False
                self.screen.write(data)
                self.screen.flush()
        return True

    def send(self, text: str) -> None:
        if self.alive:
            try:
                os.write(self.fd, text.encode())
            except OSError:
                pass

    def prompt(self, text: str) -> None:
        self.send(text)
        self.pump(1)
        self.send("\r")

    def rows(self) -> list[dict]:
        try:
            return [json.loads(ln) for ln in self.hooks_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, ValueError):
            return []

    def mod_rows(self) -> list[dict]:
        try:
            return [json.loads(ln) for ln in self.mod_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, ValueError):
            return []

    def wait_for(self, predicate, seconds: int) -> bool:
        for _ in range(seconds):
            if not self.pump(1):
                return False
            if predicate():
                return True
        return False

    def end(self) -> None:
        self.send("/exit\r")
        self.pump(3)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(self.pid, sig)
                time.sleep(0.5)
            except OSError:
                pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except OSError:
            pass
        self.screen.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mod", type=Path, default=MOD, help="the mod directory (default: the shipped one)")
    parser.add_argument("--out", type=Path, default=None, help="where the throwaway and the logs go")
    parser.add_argument("--model", default="haiku")
    args = parser.parse_args(argv)
    if pty is None:
        print("own-clear drive: POSIX only (it forks a pty), and this host has none; the Windows seats "
              "are driven by hand (the docstring's sequence)", file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or (REPO / "reports" / f"own-clear-drive-{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    repo = _throwaway(out, sys.executable)
    ship = _load_ship()
    verdict: dict[str, bool] = {}
    d = Drive(repo, out, args.mod.resolve(), args.model)
    t0 = time.time()
    try:
        d.pump(6)
        d.send("\x1b[B")      # the trust dialog defaults to "No, exit": Down, then Enter
        d.pump(0.5)
        d.send("\r")
        d.pump(4)
        d.prompt("Reply with the single word ready.")
        verdict["first turn stopped"] = d.wait_for(
            lambda: any(r.get("event") == "Stop" for r in d.rows()), 60)
        starts = [r for r in d.rows() if r.get("event") == "SessionStart" and r.get("source") == "startup"]
        first_id = starts[0]["session"] if starts else ""
        verdict["session id read"] = bool(first_id)
        line = ship.arm_own_clear(repo, session_id=first_id, head=_git(repo, "rev-parse", "HEAD"),
                                  seat="box", role="worker", brief=BRIEF)
        print(line)
        d.prompt("/compact")
        verdict["compaction refused"] = d.wait_for(
            lambda: any("session.compact" in r.get("text", "") and "refused" in r.get("text", "")
                        for r in d.mod_rows()), 20)
        d.pump(2)
        verdict["no PreCompact reached the settings hooks"] = not any(r.get("event") == "PreCompact" for r in d.rows())
        d.prompt("Reply with the single word again.")
        verdict["cleared"] = d.wait_for(
            lambda: any(r.get("event") == "SessionStart" and r.get("source") == "clear" for r in d.rows()), 90)
        new = [r for r in d.rows() if r.get("event") == "SessionStart" and r.get("source") == "clear"]
        new_id = new[0]["session"] if new else ""
        verdict["primed in the new session"] = d.wait_for(
            lambda: any(r.get("event") == "UserPromptSubmit" and r.get("session") == new_id
                        and "primed" in r.get("prompt", "") for r in d.rows()), 30)
        verdict["the re-primed turn stopped"] = d.wait_for(
            lambda: any(r.get("event") == "Stop" and r.get("session") == new_id for r in d.rows()), 60)
        try:   # the mod rewrote it; a torn or missing file is a MISS below, not a crash
            marker = json.loads((repo / ".espalier-state" / "own_clear.json").read_bytes())
        except (OSError, ValueError):
            marker = {}
        verdict["marker consumed for the new session"] = (
            marker.get("state") == "consumed" and marker.get("new_session_id") == new_id
            and marker.get("session_id") == first_id)
        verdict["window alive after"] = d.alive
    finally:
        d.end()
    ok = all(verdict.values())
    print(f"own-clear drive: {'PASS' if ok else 'FAIL'} after {time.time() - t0:.0f}s; logs in {out}")
    for name, seen in verdict.items():
        print(f"  {'ok  ' if seen else 'MISS'} {name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
