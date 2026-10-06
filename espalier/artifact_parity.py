"""Structural parity between source-path init and wheel-install init.

`init` writes a bare interpreter NAME it detects on PATH, so the two runs
need not agree on that token — they are launched by different interpreters
and may see a different PATH. Comparing settings.json textually would make
parity depend on that detection. Structural parity strips the interpreter
token and compares everything else, so the check is about the deployed
SHAPE rather than about which interpreter name each run happened to pick.

Public API:

- `extract_script_arg(command)` — pull the `$CLAUDE_PROJECT_DIR/...` anchor out
  of a hook command, ignoring the interpreter token in front.
- `structural_diff(left, right)` — compare two settings dicts; return a list of
  difference descriptions (empty = parity).
- `clear_stale_packaging_state(repo_root)` — remove `build/` and the top-level
  `*.egg-info` so a build in the live tree reads the committed tree, not a
  cached manifest (the two hand-run release-ladder builds; the suite's never
  build there).
- `stage_build_tree(repo_root, staging_root)` — copy the working tree, less what
  no artifact ships, for a build to run in.
- `build_wheel(repo_root, dest)` / `build_sdist(repo_root, dest)` — build a
  fresh wheel or sdist via `python -m build` from a staged copy of the tree;
  the root is read once and never written.
- `run_init_in_clean_venv(wheel_path, target_repo)` — install the wheel into a
  scratch venv and run `espalier init` on a fresh target.
- `check_source_vs_wheel(repo_root)` — the full dance: build, run source-path
  init, run wheel-install init, diff. Returns `{"parity": bool, "diffs": [...]}`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from espalier._rmtree import remove_file, remove_tree


CLAUDE_PROJECT_DIR_MARKER = '"$CLAUDE_PROJECT_DIR/'


def extract_script_arg(command: str) -> str:
    """Return the $CLAUDE_PROJECT_DIR-anchored portion of a shell-form command.

    Raises ValueError if the anchor is missing. Used to compare hook
    commands across hosts where the interpreter token differs but the
    script-path tail must match. Newly generated settings use the exec
    form (which puts the script in ``args``, not embedded in the command
    string); this function is retained for reading legacy settings files.
    """
    idx = command.find(CLAUDE_PROJECT_DIR_MARKER)
    if idx == -1:
        raise ValueError(
            f"command missing $CLAUDE_PROJECT_DIR anchor: `{command}`"
        )
    return command[idx:]


def extract_script_path(hook: dict) -> str | None:
    """Extract the hook script path from either exec or shell form.

    Returns the path string (e.g. ``"${CLAUDE_PROJECT_DIR}/tools/cc/hooks/X.py"``)
    or ``None`` if the entry has no recognisable script reference. Exec
    form stores it in ``args[0]``; the older shell form embeds it inside
    the ``command`` string.

    The returned string preserves the original placeholder form
    (``${CLAUDE_PROJECT_DIR}`` for exec, ``"$CLAUDE_PROJECT_DIR``
    quoted for shell) so callers can spot shape mismatches if needed.
    For shape-agnostic comparisons callers should normalise the prefix.
    """
    args = hook.get("args")
    if isinstance(args, list):
        for arg in args:
            if isinstance(arg, str) and arg.endswith(".py"):
                return arg
    cmd = hook.get("command")
    if isinstance(cmd, str):
        try:
            return extract_script_arg(cmd)
        except ValueError:
            return None
    return None


def _normalize_script_path(path: str) -> str:
    """Strip leading ``${CLAUDE_PROJECT_DIR}/`` (curly or bare) and any
    surrounding quotes so paths from exec form and shell form compare
    equal.
    """
    s = path.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    for prefix in ("${CLAUDE_PROJECT_DIR}/", "$CLAUDE_PROJECT_DIR/"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _event_hooks(settings: dict, event: str) -> list[dict]:
    """Flatten all hook entries for an event into a single list."""
    event_cfg = (settings.get("hooks") or {}).get(event, [])
    flat: list[dict] = []
    if not isinstance(event_cfg, list):
        return flat
    for entry in event_cfg:
        if not isinstance(entry, dict):
            continue
        hooks = entry.get("hooks", [])
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if isinstance(hook, dict):
                merged = {"matcher": entry.get("matcher", "")}
                merged.update(hook)
                flat.append(merged)
    return flat


def structural_diff(left: dict, right: dict) -> list[str]:
    """Compare two settings dicts structurally. Empty result == parity."""
    diffs: list[str] = []

    left_events = set((left.get("hooks") or {}).keys())
    right_events = set((right.get("hooks") or {}).keys())
    if left_events != right_events:
        only_left = sorted(left_events - right_events)
        only_right = sorted(right_events - left_events)
        if only_left:
            diffs.append(f"events only on source side: {only_left}")
        if only_right:
            diffs.append(f"events only on wheel side: {only_right}")

    common = left_events & right_events
    for event in sorted(common):
        lh = _event_hooks(left, event)
        rh = _event_hooks(right, event)
        if len(lh) != len(rh):
            diffs.append(
                f"event {event!r} hook count differs: source={len(lh)}, wheel={len(rh)}"
            )
            continue
        for i, (a, b) in enumerate(zip(lh, rh)):
            if a.get("matcher", "") != b.get("matcher", ""):
                diffs.append(
                    f"event {event!r} entry {i} matcher differs: "
                    f"source={a.get('matcher')!r}, wheel={b.get('matcher')!r}"
                )
            if a.get("timeout") != b.get("timeout"):
                diffs.append(
                    f"event {event!r} entry {i} timeout differs: "
                    f"source={a.get('timeout')}, wheel={b.get('timeout')}"
                )
            a_script = extract_script_path(a)
            b_script = extract_script_path(b)
            if a_script is None or b_script is None:
                diffs.append(
                    f"event {event!r} entry {i} hook missing script reference: "
                    f"source={a_script}, wheel={b_script}"
                )
                continue
            if _normalize_script_path(a_script) != _normalize_script_path(b_script):
                diffs.append(
                    f"event {event!r} entry {i} script arg differs: "
                    f"source={a_script}, wheel={b_script}"
                )

    # Sanity: UserPromptSubmit must be present (stale-wheel regression lock).
    if "UserPromptSubmit" not in (left.get("hooks") or {}):
        diffs.append("source-side settings missing UserPromptSubmit event")
    if "UserPromptSubmit" not in (right.get("hooks") or {}):
        diffs.append("wheel-side settings missing UserPromptSubmit event")

    # Sanity: all canonical hook scripts must be wired, by name, on both sides.
    from espalier import surface_contract
    canonical = surface_contract.get_canonical_hook_scripts()
    for label, data in (("source", left), ("wheel", right)):
        wired: set[str] = set()
        for event_cfg in (data.get("hooks") or {}).values():
            if not isinstance(event_cfg, list):
                continue
            for entry in event_cfg:
                if not isinstance(entry, dict):
                    continue
                for hook in entry.get("hooks", []) or []:
                    if not isinstance(hook, dict):
                        continue
                    script_arg = extract_script_path(hook)
                    if script_arg is None:
                        continue
                    normalised = _normalize_script_path(script_arg)
                    for name in canonical:
                        if normalised.endswith(f"/{name}") or normalised == name:
                            wired.add(name)
        missing = sorted(set(canonical) - wired)
        if missing:
            diffs.append(f"{label}-side missing canonical hooks: {missing}")

    return diffs


# ---------------------------------------------------------------------------
# Integration: build a wheel and run both sides
# ---------------------------------------------------------------------------


def clear_stale_packaging_state(repo_root: Path) -> list[Path]:
    """Remove ``repo_root/build`` and every top-level ``*.egg-info`` before a
    build, so the artifact reflects the committed source tree and not a
    cached manifest. Returns the paths it removed.

    Two independent staleness channels, both of which silently re-ship a path
    the current config drops: ``build/lib`` (setuptools' build_py never prunes
    it between runs -- a stale ``build/lib/tools`` re-shipped a top-level
    ``tools`` squat while ``top_level.txt`` read espalier-only) and
    ``*.egg-info/SOURCES.txt`` (a cached file list setuptools reuses, so a
    deleted ``package-data`` glob still ships what it used to match; driven
    three ways in ``tests/test_wheel_payload.py``'s history, whose fixtures
    now build through ``build_wheel`` / ``build_sdist`` below). In this
    repository both are gitignored, so removing them needs no restore. One
    home for the builds that still run in the live tree: the release matrix's
    sdist and wheel stages (hand-run, alone), with ``scripts/wheel_smoke.py``'s
    stdlib twin pinned by driven parity in ``tests/test_wheel_smoke.py``. The
    suite's builds stage a copy that carries neither channel
    (``stage_build_tree``) and have nothing to clear (``DEF-1138``). A nested
    ``*.egg-info`` is left alone (only
    the top-level one is the package's own), so is a plain file of either
    name; a symlinked ``build`` is unlinked, never followed (on Windows a
    directory symlink is removed with ``rmdir``, which drops the link and
    not its target).
    """
    removed: list[Path] = []
    for path in [repo_root / "build", *sorted(repo_root.glob("*.egg-info"))]:
        if path.is_symlink():
            if sys.platform == "win32" and path.is_dir():
                path.rmdir()  # a directory symlink: rmdir drops the link, not the target
            else:
                remove_file(path)
        elif path.is_dir():
            remove_tree(path)
        else:
            continue
        removed.append(path)
    return removed


# ---------------------------------------------------------------------------
# Staging: a build reads a copy of the tree, never the tree
# ---------------------------------------------------------------------------

#: The directory names a staged build copy leaves out, at every depth: what
#: no sdist or wheel ever ships (``MANIFEST.in`` prunes or globally excludes
#: each, or ``.gitignore`` keeps it out of the tree a fresh clone has), so
#: leaving them out changes no artifact and drops the bulk of a working tree:
#: the git store, the last build's leftovers, the session state, the caches.
#: ``tests/test_artifact_parity.py`` pins every name to one of those two
#: files, and pins that no tracked path carries one.
BUILD_TREE_SKIP_NAMES: frozenset[str] = frozenset({
    ".git", "build", "dist", "reports", ".espalier-state",
    ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "htmlcov",
})

#: A ``*.egg-info`` is the cached manifest setuptools reuses (the second
#: staleness channel ``clear_stale_packaging_state`` names); the copy leaves
#: every one out, at any depth, so the build in it starts cold.
BUILD_TREE_SKIP_SUFFIX = ".egg-info"

#: Repo-relative directories the copy leaves out whole: the session and run
#: state a live Claude Code session or a bench run writes while a build is
#: copying. ``shutil.copytree`` lists a directory, then copies each entry,
#: and an entry gone between the two raises ``shutil.Error`` out of the
#: copy, so a blueprint node rotating under ``cc/blueprints/`` mid-copy would
#: error every test behind a module-scoped build fixture (the lane's
#: failure-mode review, driven 2026-10-06). Each is a ``prune`` rule in
#: ``MANIFEST.in`` and a directory rule in ``.gitignore``; pinned beside the
#: names.
BUILD_TREE_SKIP_PATHS: frozenset[str] = frozenset({
    "cc/blueprints", "bench/results", "bench/end_to_end/runs",
})


def _build_tree_ignore(repo_root: Path) -> Callable[[str, list[str]], set[str]]:
    """``shutil.copytree``'s ``ignore`` callback for a copy of ``repo_root``:
    given one directory and its entries, the names to leave out."""
    root = repo_root.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        rel = Path(directory).resolve().relative_to(root)
        return {
            n for n in names
            if n in BUILD_TREE_SKIP_NAMES or n.endswith(BUILD_TREE_SKIP_SUFFIX)
            or (rel / n).as_posix() in BUILD_TREE_SKIP_PATHS
        }

    return ignore


def stage_build_tree(repo_root: Path, staging_root: Path) -> Path:
    """Copy the working tree at ``repo_root`` under ``staging_root``; return
    the copy, named as the root is.

    The working tree, not ``HEAD``: a build proves the tree as it is, the
    lane's uncommitted edits included, which is what a build in the live
    tree proved. ``BUILD_TREE_SKIP_NAMES``, ``BUILD_TREE_SKIP_PATHS`` and
    every ``*.egg-info`` are left out. A symlink is copied as a link: none is
    tracked today, and a tracked one would need the symlink privilege on a
    Windows host, where following it would have been the quieter default.
    """
    staged = staging_root / repo_root.resolve().name
    shutil.copytree(repo_root, staged, symlinks=True, ignore=_build_tree_ignore(repo_root))
    return staged


def _build_artifact(
    repo_root: Path, dest_dir: Path, kind: Literal["wheel", "sdist"],
) -> Path:
    """Build one artifact from a staged copy of ``repo_root`` into
    ``dest_dir``; return its path.

    The copy lives under a per-call temp root for the length of the build
    and is removed after it, so the release tree setuptools stages beside
    the sources for an sdist, the ``build/`` a wheel build leaves, and the
    ``*.egg-info`` both write all land in the copy and die with it:
    ``repo_root`` is read once and never written. Under xdist a tree-walking
    test on another worker used to see all three (``DEF-1138``: a red
    required cell on a pull request whose diff never touched the file it
    named). ``dest_dir`` is resolved against this process's cwd before the
    build subprocess is given the copy as its own, so a relative path lands
    where the caller meant it, not inside the copy.
    """
    dest_dir = dest_dir.resolve()
    staging_root = Path(tempfile.mkdtemp(prefix="espalier-build-"))
    try:
        staged = stage_build_tree(repo_root, staging_root)
        dest_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [sys.executable, "-m", "build", f"--{kind}", "--no-isolation",
             "--outdir", str(dest_dir)],
            cwd=str(staged),
        )
    finally:
        remove_tree(staging_root, best_effort=True)
        if staging_root.exists():  # a handle still open on Windows: say where it is
            sys.stderr.write(
                f"[artifact_parity] the staged build copy could not be removed: {staging_root}\n"
            )
    suffix = ".whl" if kind == "wheel" else ".tar.gz"
    artifacts = sorted(dest_dir.glob(f"espalier_harness-*{suffix}"))
    if not artifacts:
        raise FileNotFoundError(f"no {kind} produced in {dest_dir}")
    return artifacts[-1]


def build_wheel(repo_root: Path, dest_dir: Path) -> Path:
    """Build a wheel from a staged copy of `repo_root` into `dest_dir`;
    return the wheel path. The root is never written (``_build_artifact``)."""
    return _build_artifact(repo_root, dest_dir, "wheel")


def build_sdist(repo_root: Path, dest_dir: Path) -> Path:
    """Build an sdist from a staged copy of `repo_root` into `dest_dir`;
    return the sdist path. The root is never written (``_build_artifact``)."""
    return _build_artifact(repo_root, dest_dir, "sdist")


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run_init_in_clean_venv(wheel_path: Path, target_repo: Path) -> dict:
    """Install `wheel_path` into a fresh venv and run init on `target_repo`.

    Returns the parsed `.claude/settings.json` from the target.
    """
    target_repo.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", str(target_repo)])
    venv_dir = target_repo.parent / "venv"
    subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    vpython = _venv_python(venv_dir)
    subprocess.check_call([str(vpython), "-m", "pip", "install", "--quiet", str(wheel_path)])
    subprocess.check_call(
        [str(vpython), "-m", "espalier.cli", "init", str(target_repo)],
    )
    settings_path = target_repo / ".claude" / "settings.json"
    # bom-exempt: this reads a settings.json espalier itself generated in a
    # throwaway tree moments earlier, so the encoding is our own UTF-8 write,
    # never an operator-edited or PowerShell-written file.
    return json.loads(settings_path.read_text(encoding="utf-8"))  # json-dict-safe: ok -- freshly init-generated settings, always a dict


def run_init_source_path(target_repo: Path) -> dict:
    """Run `python -m espalier.cli init <target>` with the current interpreter."""
    target_repo.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", str(target_repo)])
    subprocess.check_call(
        [sys.executable, "-m", "espalier.cli", "init", str(target_repo)],
    )
    settings_path = target_repo / ".claude" / "settings.json"
    # bom-exempt: this reads a settings.json espalier itself generated in a
    # throwaway tree moments earlier, so the encoding is our own UTF-8 write,
    # never an operator-edited or PowerShell-written file.
    return json.loads(settings_path.read_text(encoding="utf-8"))  # json-dict-safe: ok -- freshly init-generated settings, always a dict


def check_source_vs_wheel(repo_root: Path) -> dict[str, Any]:
    """Full parity check: build wheel, run both init flows, structurally diff."""
    repo_root = repo_root.resolve()
    scratch = Path(tempfile.mkdtemp(prefix="cc-parity-"))
    try:
        wheel_path = build_wheel(repo_root, scratch / "dist")
        source_target = scratch / "source-repo"
        wheel_target = scratch / "wheel-repo"
        source_settings = run_init_source_path(source_target)
        wheel_settings = run_init_in_clean_venv(wheel_path, wheel_target)
        diffs = structural_diff(source_settings, wheel_settings)
        return {
            "parity": not diffs,
            "diffs": diffs,
            "source_settings_path": str(source_target / ".claude" / "settings.json"),
            "wheel_settings_path": str(wheel_target / ".claude" / "settings.json"),
        }
    finally:
        remove_tree(scratch, best_effort=True)
