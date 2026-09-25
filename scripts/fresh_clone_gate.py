#!/usr/bin/env python3
"""The release gate: the full proof tier on a tree it was not written on.

Clones this checkout at HEAD -- never the working tree -- once per requested
interpreter, builds a venv for that interpreter, installs the ``dev`` extra,
proves that ``pytest``, ``mypy`` AND the ``espalier`` package resolve under
that venv and that clone, and runs ``scripts/proof_tier.py --run --tier full``
inside the clone under a whitelisted environment. One receipt line per
interpreter, one verdict line, the worst exit propagated. The suite in a clone
is what a contributor gets on day one and what the public repo's push cell
runs; the dev tree is neither.

Why each control exists (every one was measured, not assumed):

- **One clone per interpreter.** A second leg in the first leg's clone runs
  the packaging tests against that leg's ``build/lib`` and egg-info -- the
  stale-manifest defect the tree's own build paths carry -- and the tier
  refuses on untracked residue *before* it runs anything.
- **The runners and the engine are resolved, not trusted.** The tier execs
  bare ``pytest`` and ``mypy`` over the inherited PATH; with the venv first
  that is the control, and this script asserts both resolve UNDER the venv.
  ``import espalier`` is asserted to land UNDER the clone too: a venv built by
  ``pip install -e .`` in another tree carries an editable finder on
  ``sys.meta_path``, which outranks ``pythonpath = ["."]``, so with
  ``--reuse-venv`` the runners could be the venv's while the engine was some
  other tree's (red-team lane A).
- **A whitelisted child environment.** The parent minus a prefix leaves
  ``PYTHONPATH``, ``VIRTUAL_ENV`` and ``PIP_*`` in place; the child gets only
  :data:`ENV_WHITELIST` plus a PATH with the venv first. The two passthroughs
  that shape the run (``PYTEST_ADDOPTS`` can shrink the suite;
  ``PYTEST_XDIST_AUTO_NUM_WORKERS`` unset means one worker per core) are
  echoed into the receipt so a forgotten export leaves a trace.
- **The receipt is read by its tail and its counts are consumed.**
  ``proof_tier`` prints ``proof: PASS -- 3 of 3 command(s) ran`` on green and
  ``proof: FAIL (worst exit N) -- 3 of 3 command(s) ran`` on red; a log with
  neither means nothing ran (the tier's untracked-files refusal exits 2
  before ``--run``), and ``ran`` must equal ``total`` must equal the number
  of commands the CLONE's own ``proof_tier.py`` declares for the full tier.

Usage::

    python3 scripts/fresh_clone_gate.py                      # this interpreter (its base install when run from a venv)
    python3 scripts/fresh_clone_gate.py --python 3.10 --python /opt/homebrew/bin/python3.14
    python3 scripts/fresh_clone_gate.py --keep --scratch /path/to/scratch

A bare ``--python`` version resolves through ``uv python find``. Every spec is
resolved and tagged before the first clone, so two specs naming one
interpreter refuse at once, not after a 25-minute leg. The gate runs alone on
the box (never beside another suite). To enumerate the clone's skips pass
``PYTEST_ADDOPTS=-rfEs`` -- ``-rs`` alone replaces pytest's default ``-rfE``
and the failed names vanish from the short summary.

Exit codes::

    0     every leg's tier passed
    1..5  the worst leg's pytest exit (a red suite, an interrupted run, ...)
    70    the gate itself refused, or crashed: a dirty tree, a clone whose
          HEAD differs, an interpreter that could not be resolved or make a
          venv that starts, a runner or the engine resolved outside the clone,
          a leg whose log carries no tier receipt or whose counts disagree,
          a leg past --leg-timeout, or any unexpected error (printed as
          ``gate: REFUSED``). Outside pytest's 0..5 on purpose -- 3 is
          pytest's own INTERNALERROR.

Stdlib-only and standalone: it runs before anything is installed in the
clone. The helpers are unit-tested in ``tests/test_fresh_clone_gate.py``.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The gate's own refusal code -- outside pytest's 0..5.
GATE_REFUSED = 70

#: The tier's receipt, matched by its TAIL. Both real spellings:
#: ``proof: PASS -- 3 of 3 command(s) ran`` and
#: ``proof: FAIL (worst exit 1) -- 3 of 3 command(s) ran``. Pinned against the
#: producer by running it (tests/test_fresh_clone_gate.py).
RECEIPT_RE = re.compile(
    r"^proof: (?P<verdict>PASS|FAIL \(worst exit (?P<worst>\d+)\)) -- "
    r"(?P<ran>\d+) of (?P<total>\d+) command\(s\) ran\s*$",
    re.MULTILINE,
)

#: The only parent keys the child sees (PATH is built, not copied). Everything
#: else -- PYTHONPATH, VIRTUAL_ENV, PIP_*, ESPALIER_*, CLAUDE_* -- is absent by
#: construction.
ENV_WHITELIST: tuple[str, ...] = (
    "HOME", "TMPDIR", "TMP", "TEMP",
    "LANG", "LC_ALL", "LC_CTYPE",
    "USER", "LOGNAME", "SHELL", "TERM",
    "SYSTEMROOT", "COMSPEC",
    "PYTEST_XDIST_AUTO_NUM_WORKERS", "PYTEST_ADDOPTS",
)

#: The whitelisted keys that change WHAT the tier runs; echoed per leg.
PASSTHROUGH_KEYS: tuple[str, ...] = ("PYTEST_ADDOPTS", "PYTEST_XDIST_AUTO_NUM_WORKERS")

#: The runners the tier execs by bare name; each must resolve under the venv.
RUNNERS: tuple[str, ...] = ("pytest", "mypy")

#: Wall-clock cap per leg (the tier's per-test timeout bounds tests, not
#: collection or ``mypy``); overridable with ``--leg-timeout``.
DEFAULT_LEG_TIMEOUT_S = 7200


class GateRefusal(Exception):
    """The gate cannot vouch for this leg; the message says why."""


def say(line: str) -> None:
    """Print one receipt line and FLUSH it. A gate run is redirected to a log
    for an hour; a block-buffered stdout showed its first two lines and nothing
    else until exit (driven 2026-09-22 on the first real run), which reads as a
    dead process -- the shape auto-memory already names for long redirected
    commands."""
    print(line, flush=True)


@dataclass
class Leg:
    spec: str
    tag: str = "?"
    rc: int | None = None
    wall_s: float = 0.0
    log: Path | None = None
    runners: dict[str, Path] = field(default_factory=dict)
    engine: Path | None = None
    receipt: tuple[str, int, int, int] | None = None
    refused: str | None = None


# ── pure helpers (unit-tested) ─────────────────────────────────────────────


def venv_bin(venv_dir: Path) -> Path:
    """The venv's executables directory (``Scripts`` on Windows, ``bin`` else).
    Parallels ``scripts/wheel_smoke.py::_venv_python``'s platform rule."""
    return venv_dir / ("Scripts" if sys.platform == "win32" else "bin")


def venv_python(venv_dir: Path) -> Path:
    return venv_bin(venv_dir) / ("python.exe" if sys.platform == "win32" else "python")


def child_env(parent: Mapping[str, str], venv_dir: Path) -> dict[str, str]:
    """The whitelist projection of ``parent`` with the venv first on PATH."""
    env = {k: parent[k] for k in ENV_WHITELIST if k in parent}
    env["PATH"] = str(venv_bin(venv_dir)) + os.pathsep + parent.get("PATH", "")
    return env


def passthrough_lines(env: Mapping[str, str]) -> list[str]:
    """One line per :data:`PASSTHROUGH_KEYS`, naming the value or its absence."""
    out = []
    for key in PASSTHROUGH_KEYS:
        if key in env:
            out.append(f"passthrough {key}={env[key]}")
        elif key == "PYTEST_XDIST_AUTO_NUM_WORKERS":
            out.append(f"passthrough {key}=<unset> -- -n auto is one worker per logical core")
        else:
            out.append(f"passthrough {key}=<unset>")
    return out


def read_receipt(log_text: str) -> tuple[str, int, int, int] | None:
    """``(verdict, worst, ran, total)`` from the LAST tier receipt in ``log_text``,
    or ``None`` when the tier never printed one."""
    matches = list(RECEIPT_RE.finditer(log_text))
    if not matches:
        return None
    m = matches[-1]
    verdict = "PASS" if m.group("verdict") == "PASS" else "FAIL"
    worst = int(m.group("worst") or 0)
    return verdict, worst, int(m.group("ran")), int(m.group("total"))


def aggregate(legs: list[Leg]) -> int:
    """The gate's exit: 70 when any leg was refused, else the worst leg rc."""
    if any(leg.refused for leg in legs):
        return GATE_REFUSED
    return max((leg.rc or 0) for leg in legs) if legs else GATE_REFUSED


def dirty_line(count: int, sha: str) -> str:
    return f"gate: proves HEAD {sha}; {count} path(s) in the working tree are not in it"


def _under(path: Path, root: Path) -> bool:
    """``path`` lies under ``root`` -- both resolved, compared case-normalised
    (macOS folds case; ``Path.parents`` does not)."""
    p = os.path.normcase(str(path.resolve()))
    r = os.path.normcase(str(root.resolve())).rstrip(os.sep) + os.sep
    return p.startswith(r)


def resolve_runners(env: Mapping[str, str], venv_dir: Path) -> dict[str, Path]:
    """Every runner in :data:`RUNNERS` as the tier will exec it, refused unless
    it lies under ``venv_dir``."""
    found: dict[str, Path] = {}
    for name in RUNNERS:
        hit = shutil.which(name, path=env.get("PATH", ""))
        if hit is None:
            raise GateRefusal(
                f"`{name}` does not resolve on the clone's PATH -- the dev extra "
                f"did not install it (pip install -e '.[dev]')"
            )
        path = Path(hit).resolve()
        if not _under(path, venv_dir):
            raise GateRefusal(
                f"`{name}` resolves to {path}, outside the venv {venv_dir.resolve()} -- the "
                f"tier would run a host runner, not the clone's"
            )
        found[name] = path
    return found


def full_tier_command_count(clone: Path) -> int:
    """How many commands the CLONE's own ``scripts/proof_tier.py`` declares for
    the full tier -- the number the receipt must report as ran and total."""
    module_path = clone / "scripts" / "proof_tier.py"
    if not module_path.is_file():
        raise GateRefusal(f"{module_path} is missing -- the clone carries no proof tier to run")
    spec = importlib.util.spec_from_file_location("_proof_tier_under_test", module_path)
    if spec is None or spec.loader is None:
        raise GateRefusal(f"{module_path} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        commands = module.FULL_COMMANDS
    except Exception as exc:  # the clone's tier is what is under test; any failure to read it refuses
        raise GateRefusal(f"{module_path} did not expose FULL_COMMANDS: {type(exc).__name__}: {exc}") from exc
    return len(commands)


def check_receipt(receipt: tuple[str, int, int, int] | None, expected_total: int, tag: str,
                  log: Path) -> tuple[str, int, int, int]:
    """The receipt with its counts consumed: every declared command ran."""
    if receipt is None:
        head = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[:3])
        raise GateRefusal(f"NOTHING RAN ({tag}): the tier printed no receipt; log {log}\n{head}")
    verdict, worst, ran, total = receipt
    if ran != total or total != expected_total:
        raise GateRefusal(
            f"the tier reported {ran} of {total} command(s) ran on {tag}, but the clone's "
            f"proof_tier declares {expected_total} for the full tier; log {log}"
        )
    return receipt


# ── subprocess helpers ─────────────────────────────────────────────────────
#
# Every call spells its argv as a literal list at the call site (no generic
# runner), so the subprocess-contract scanner resolves each one instead of
# reporting a dynamic runner that needs a pragma -- the pragma budget is a
# ratchet and this script is not the thing to spend it on.


def head_sha(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise GateRefusal(f"git rev-parse failed at {root}: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def dirty_paths(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise GateRefusal(f"git status failed at {root}: {proc.stderr.strip()[:200]}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def default_interpreter() -> Path:
    """This interpreter -- or its base install when this process is itself a
    venv python. On CPython 3.10 a venv's ``sys._base_executable`` is the venv's
    own python, so a venv built FROM a venv python gets ``home = <that venv>/bin``
    and cannot import anything (measured 2026-09-22); 3.11+ record the base."""
    if sys.prefix == sys.base_prefix:
        return Path(sys.executable)
    major, minor = sys.version_info[:2]
    base = Path(sys.base_prefix)
    for candidate in (base / "bin" / f"python{major}.{minor}", base / "bin" / "python3", base / "python.exe"):
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def resolve_interpreter(spec: str, *, find: Callable[[str], str | None] | None = None) -> Path:
    """An interpreter path from ``spec``: an existing executable FILE is itself
    (a directory named like a version is not); a bare ``major.minor`` goes
    through ``uv python find`` (``find`` overrides it for tests); anything else
    is looked up on PATH."""
    candidate = Path(spec).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate.resolve()
    if re.fullmatch(r"\d+\.\d+", spec):
        if find is None:
            uv = shutil.which("uv")
            if uv is None:
                raise GateRefusal(
                    f"--python {spec}: a bare version needs `uv` on PATH "
                    f"(`uv python install {spec}`), or pass the interpreter's path"
                )

            def find(version: str, _uv: str = uv) -> str | None:
                proc = subprocess.run([_uv, "python", "find", version], capture_output=True, text=True, encoding="utf-8", errors="replace")
                out = proc.stdout.strip().splitlines()
                return out[0] if proc.returncode == 0 and out else None

        hit = find(spec)
        if not hit:
            raise GateRefusal(
                f"--python {spec}: `uv python find {spec}` found nothing -- "
                f"`uv python install {spec}`"
            )
        return Path(hit).resolve()
    hit = shutil.which(spec)
    if hit is None:
        raise GateRefusal(f"--python {spec}: not an executable file, not a version, not on PATH")
    return Path(hit).resolve()


def interpreter_tag(exe: Path) -> str:
    proc = subprocess.run(
        [str(exe), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"], capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise GateRefusal(f"{exe} did not report a version: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def resolve_all(specs: list[str], *, find: Callable[[str], str | None] | None = None) -> list[tuple[str, Path, str]]:
    """``(spec, exe, tag)`` for every spec, refused as a whole when two specs
    name one interpreter -- BEFORE any clone, so a collision never costs a leg."""
    out: list[tuple[str, Path, str]] = []
    for spec in specs:
        exe = resolve_interpreter(spec, find=find)
        out.append((spec, exe, interpreter_tag(exe)))
    seen: dict[str, str] = {}
    for spec, _exe, tag in out:
        if tag in seen:
            raise GateRefusal(
                f"--python {seen[tag]!r} and --python {spec!r} are both {tag} -- one clone per "
                f"interpreter; drop one"
            )
        seen[tag] = spec
    return out


def clone_head(root: Path, dest: Path) -> str:
    proc = subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(root), str(dest)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise GateRefusal(f"git clone into {dest} failed: {proc.stderr.strip()[:200]}")
    return head_sha(dest)


def make_venv(exe: Path, venv_dir: Path) -> Path:
    proc = subprocess.run([str(exe), "-m", "venv", str(venv_dir)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise GateRefusal(f"{exe} -m venv failed: {(proc.stderr or proc.stdout).strip()[-300:]}")
    vpy = venv_python(venv_dir)
    # Can the venv's python START? A venv built from a venv python on CPython
    # 3.10 answers `--version` and cannot import anything (its `home` points
    # at the parent venv); name that cause, not ensurepip's symptom.
    start = subprocess.run([str(vpy), "-c", "import sys"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if start.returncode != 0:
        raise GateRefusal(
            f"the venv at {venv_dir} cannot start ({(start.stderr or start.stdout).strip()[-160:]}); "
            f"built from {exe} -- a venv built from a venv python on CPython < 3.11 has no stdlib; "
            f"pass the base interpreter"
        )
    # Bytes, never decoded: only the return code says whether pip is there
    # (a version banner is a structured answer; decoding it tolerantly would
    # mask corruption, and the gate has no use for its text).
    if subprocess.run([str(vpy), "-m", "pip", "--version"], capture_output=True).returncode != 0:
        boot = subprocess.run([str(vpy), "-m", "ensurepip", "--upgrade"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if boot.returncode != 0:
            raise GateRefusal(
                f"the venv at {venv_dir} has no pip and `ensurepip` failed: "
                f"{(boot.stderr or boot.stdout).strip()[-300:]}"
            )
    return vpy


def install_dev(vpy: Path, clone: Path) -> None:
    proc = subprocess.run(
        [str(vpy), "-m", "pip", "install", "-q", "-e", ".[dev]"], cwd=str(clone), timeout=1800, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise GateRefusal(f"pip install -e '.[dev]' failed in {clone}: {(proc.stderr or proc.stdout).strip()[-400:]}")


def verify_engine(vpy: Path, clone: Path, env: Mapping[str, str]) -> Path:
    """Where ``import espalier`` lands for the venv's python run inside the
    clone -- refused unless under the clone (an editable finder from another
    tree outranks ``pythonpath``)."""
    proc = subprocess.run(
        [str(vpy), "-c", "import espalier, pathlib; print(pathlib.Path(espalier.__file__).resolve())"],
        cwd=str(clone), env=dict(env), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise GateRefusal(
            f"`import espalier` failed under {vpy} inside {clone}: {(proc.stderr or proc.stdout).strip()[-200:]}"
        )
    engine = Path(proc.stdout.strip().splitlines()[-1])
    if not _under(engine, clone):
        raise GateRefusal(
            f"`espalier` imports from {engine}, outside the clone {clone.resolve()} -- the venv carries "
            f"another tree's editable install; the tier would test that tree's engine"
        )
    return engine


def run_tier(vpy: Path, clone: Path, env: Mapping[str, str], log_path: Path,
             echo: Callable[[str], None] = say, timeout_s: float = DEFAULT_LEG_TIMEOUT_S) -> int:
    """Run ``scripts/proof_tier.py --run --tier full`` inside ``clone``; stream
    every line to ``echo`` and the log. A leg past ``timeout_s`` is killed and
    refused."""
    timed_out = threading.Event()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(vpy), "scripts/proof_tier.py", "--run", "--tier", "full"],
            cwd=str(clone), env=dict(env), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )

        def _kill() -> None:
            timed_out.set()
            proc.kill()

        watchdog = threading.Timer(timeout_s, _kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                echo(line.rstrip("\n"))
            rc = proc.wait()
        finally:
            watchdog.cancel()
    if timed_out.is_set():
        raise GateRefusal(f"the tier ran past --leg-timeout {timeout_s:.0f}s and was killed; log {log_path}")
    return rc


# ── one leg ────────────────────────────────────────────────────────────────


def run_leg(spec: str, exe: Path, tag: str, *, root: Path, scratch: Path, parent_env: Mapping[str, str],
            reuse_venv: Path | None = None, echo: Callable[[str], None] = say,
            leg_timeout_s: float = DEFAULT_LEG_TIMEOUT_S) -> Leg:
    leg = Leg(spec=spec, tag=tag)
    clone = scratch / f"clone-{tag}"
    if clone.exists():
        raise GateRefusal(f"{clone} already exists -- one clone per interpreter, and the gate never reuses one")
    root_sha = head_sha(root)
    clone_sha = clone_head(root, clone)
    if clone_sha != root_sha:
        raise GateRefusal(f"the clone's HEAD {clone_sha} differs from {root}'s {root_sha}")
    echo(f"CLONE_HEAD_{tag}={clone_sha} at {clone}")
    if reuse_venv is not None:
        venv_dir = reuse_venv
        vpy = venv_python(venv_dir)
    else:
        venv_dir = scratch / f"venv-{tag}"
        vpy = make_venv(exe, venv_dir)
        install_dev(vpy, clone)
    env = child_env(parent_env, venv_dir)
    leg.runners = resolve_runners(env, venv_dir)
    for name, path in leg.runners.items():
        echo(f"runner {name}={path}")
    leg.engine = verify_engine(vpy, clone, env)
    echo(f"engine espalier={leg.engine}")
    for line in passthrough_lines(env):
        echo(line)
    expected_total = full_tier_command_count(clone)
    leg.log = scratch / f"gate-{tag}.log"
    started = time.monotonic()
    leg.rc = run_tier(vpy, clone, env, leg.log, echo=echo, timeout_s=leg_timeout_s)
    leg.wall_s = time.monotonic() - started
    leg.receipt = check_receipt(
        read_receipt(leg.log.read_text(encoding="utf-8", errors="replace")), expected_total, tag, leg.log,
    )
    echo(f"PYTEST_EXIT_{tag}={leg.rc} wall={leg.wall_s:.0f}s log={leg.log}")
    return leg


# ── CLI ────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(REPO_ROOT), help="the checkout to clone (default: this one)")
    ap.add_argument("--python", action="append", default=[], metavar="EXE_OR_VERSION",
                    help="an interpreter path, a name on PATH, or a bare major.minor resolved by "
                         "`uv python find`; repeatable (default: this interpreter's base install)")
    ap.add_argument("--scratch", help="where the clones, venvs and logs go (default: a fresh temp dir)")
    ap.add_argument("--keep", action="store_true", help="never remove the scratch, even on PASS")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="clone HEAD although the working tree has uncommitted paths (they are NOT in the proof)")
    ap.add_argument("--reuse-venv", metavar="DIR",
                    help="run the tier under an existing venv instead of making one (the runners must "
                         "already be there and `espalier` must import from the clone; one --python at most)")
    ap.add_argument("--leg-timeout", type=float, default=DEFAULT_LEG_TIMEOUT_S, metavar="SECONDS",
                    help=f"kill and refuse a leg past this wall clock (default {DEFAULT_LEG_TIMEOUT_S})")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(parse_args(argv))
    except GateRefusal as exc:
        print(f"gate: REFUSED: {exc}", flush=True)
        return GATE_REFUSED
    except Exception as exc:  # any crash is the gate's, never a leg's: never pytest's 1
        print(f"gate: REFUSED: {type(exc).__name__}: {exc}", flush=True)
        return GATE_REFUSED


def _main(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    specs = args.python or [str(default_interpreter())]
    if args.reuse_venv and len(specs) > 1:
        raise GateRefusal("--reuse-venv takes one interpreter")
    sha = head_sha(root)
    dirty = dirty_paths(root)
    if dirty and not args.allow_dirty:
        raise GateRefusal(
            f"the working tree has {len(dirty)} path(s) not in HEAD {sha}; the gate proves HEAD. "
            f"Commit them, or pass --allow-dirty to prove HEAD anyway."
        )
    if dirty:
        print(dirty_line(len(dirty), sha), flush=True)
    resolved = resolve_all(specs)
    for spec, exe, tag in resolved:
        print(f"interpreter {tag}={exe} (from --python {spec!r})", flush=True)
    made_scratch = args.scratch is None
    scratch = Path(tempfile.mkdtemp(prefix="espalier-gate-")) if made_scratch else Path(args.scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    reuse = Path(args.reuse_venv).resolve() if args.reuse_venv else None

    legs: list[Leg] = []
    for spec, exe, tag in resolved:
        leg: Leg
        try:
            leg = run_leg(spec, exe, tag, root=root, scratch=scratch, parent_env=os.environ,
                          reuse_venv=reuse, leg_timeout_s=args.leg_timeout)
        except GateRefusal as exc:
            leg = Leg(spec=spec, tag=tag, refused=str(exc))
            print(f"gate: REFUSED ({tag}): {exc}", flush=True)
        legs.append(leg)

    rc = aggregate(legs)
    ran = sum(1 for leg in legs if leg.rc is not None)
    verdict = "PASS" if rc == 0 else "FAIL"
    tail = f"; {len(dirty)} working-tree path(s) NOT in this proof" if dirty else ""
    print(f"gate: {verdict} -- {ran} of {len(legs)} interpreter(s) ran; HEAD {sha}{tail}", flush=True)
    if rc == 0 and not args.keep:
        _remove_own(scratch, legs, made_scratch, reuse)
    else:
        print(f"gate: scratch kept at {scratch}", flush=True)
    return rc


def _remove_own(scratch: Path, legs: list[Leg], made_scratch: bool, reuse_venv: Path | None) -> None:
    """Remove only what this run created: its clones, its own venvs (never a
    reused one) and its logs, and the scratch root itself only when the gate
    made it."""
    for leg in legs:
        paths = [scratch / f"clone-{leg.tag}", scratch / f"gate-{leg.tag}.log"]
        if reuse_venv is None:
            paths.append(scratch / f"venv-{leg.tag}")
        for path in paths:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
    if made_scratch and reuse_venv is None:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
