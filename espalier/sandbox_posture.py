"""The sandbox posture: Claude Code's ``sandbox.filesystem`` deny lists,
derived from the harness's own rosters (TP-476 Wave B-1).

Claude Code's Bash sandbox (macOS, Linux, WSL2; none on native Windows) is a
boundary the operating system enforces around shell commands. ``denyWrite``
and ``denyRead`` entries put the harness zones and the secret paths behind it
for every sandboxed command and the processes it starts. The lists are
derived here and never copied:

* ``denyWrite``: the engine's protected-zone roster
  (``surface_contract.get_protected_mutation_prefixes`` and the exact files
  of ``get_protected_mutation_paths``), ``espalier/`` only on the self-host
  tree as the hook itself applies it, then the adopter's ``protected_paths``
  from ``espalier.toml``. ``cc/`` is left to ``write_guard``: the harness's
  own shell commands write its carve-outs (the plan, the blueprints, the
  working summary), and the sandbox has no documented narrower allow for
  writes. No entry carries a wildcard: Linux and WSL2 skip a ``denyWrite``
  entry that holds one.
* ``denyRead``: the ``_SECRET_PATH_LABEL`` roster of the deployed
  ``tools/cc/hooks/write_guard.py`` (the engine's vendored copy where a tree
  has none yet), parsed from the source by AST so the engine imports no hook;
  ``' / '`` splits a label that names two spellings, and each spelling is
  written at the project root and anywhere below it (the guard matches by
  name wherever the file sits).

Every entry is written ``./``-relative, which Claude Code reads against the
project root for a project settings file. ``sandbox.enabled`` is never
written: turning the sandbox on changes the adopter's network and approval
behaviour, and that is theirs. The user scope (``allowUnsandboxedCommands``)
is read for ``doctor`` and never written. Measured 2026-10-09 (the pack's
0-C): ``denyWrite`` holds for shell writes and ``git checkout`` and NOT for
the ``Write`` tool, so this is a shell layer beside ``write_guard``, never a
replacement for its path check on ``Write``, ``Edit`` and ``NotebookEdit``.
"""
from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from espalier import surface_contract
from espalier._text import os_error_text

#: The opt-in flag ``init`` and ``upgrade`` take to write the lists.
FLAG = "--sandbox-posture"
SANDBOX_KEY = "sandbox"
FILESYSTEM_KEY = "filesystem"
DENY_WRITE = "denyWrite"
DENY_READ = "denyRead"
LISTS: tuple[str, ...] = (DENY_WRITE, DENY_READ)
#: The roster the ``denyRead`` derivation parses out of the guard's source.
ROSTER_NAME = "_SECRET_PATH_LABEL"
GUARD_REL = "tools/cc/hooks/write_guard.py"
#: Zones the hook keeps for itself (its carve-outs are written by the
#: harness's own shell commands, which the sandbox would refuse).
HOOK_KEPT_ZONES: tuple[str, ...] = ("cc/",)
PROJECT_SETTINGS = ".claude/settings.json"
LOCAL_SETTINGS = ".claude/settings.local.json"
_WILDCARD = ("*", "?", "[")


# -- derivation -----------------------------------------------------------------------


def write_guard_source(root: Path) -> Path:
    """The guard whose roster the tree runs: the deployed copy under ``root``,
    else the engine's vendored source (a tree ``init`` has not reached yet)."""
    deployed = Path(root) / GUARD_REL
    if deployed.is_file():
        return deployed
    return Path(__file__).resolve().parent / "_vendor" / "cc" / "hooks" / "write_guard.py"


def secret_roster(source: Path) -> dict[str, str]:
    """``_SECRET_PATH_LABEL`` as the guard's source declares it, by AST.

    Refuses by name when the assignment is gone or is no longer a literal
    dict of strings: a roster that moved must move this derivation with it,
    never fall silent to an empty list."""
    source = Path(source)
    text = source.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text, filename=str(source))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == ROSTER_NAME for t in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError as exc:
            raise ValueError(f"{source}: {ROSTER_NAME} is not a literal ({exc})") from exc
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise ValueError(f"{source}: {ROSTER_NAME} is not a dict of str to str")
        return dict(value)
    raise ValueError(
        f"{source}: no module-level {ROSTER_NAME} assignment; the secret roster moved, "
        "so the denyRead derivation must follow it"
    )


def _relative(raw: str) -> str | None:
    """``./``-relative spelling of a roster entry; ``None`` for an empty one."""
    entry = raw.strip().replace("\\", "/")
    while entry.startswith("./"):
        entry = entry[2:]
    entry = entry.rstrip("/")
    return f"./{entry}" if entry else None


def deny_read_entries(source: Path | None = None, *, root: Path | None = None) -> list[str]:
    """Two ``./``-relative globs per spelling of the roster's labels, in roster
    order, duplicates folded: the spelling at the project root (``./.env``)
    and anywhere below it (``./**/.env``). The guard matches a dotenv by its
    NAME wherever it sits and a ``secrets/`` segment anywhere in a path, so
    the root form alone would under-cover; both forms are written because the
    docs do not say whether ``**/`` matches zero directories. ``denyRead``
    wildcards work on every platform the sandbox runs on."""
    if source is None:
        if root is None:
            raise TypeError("deny_read_entries needs the guard's source or the tree's root")
        source = write_guard_source(root)
    out: list[str] = []
    for label in secret_roster(source).values():
        for spelling in label.split(" / "):
            bare = spelling.strip().replace("\\", "/")
            while bare.startswith(("**/", "./")):
                bare = bare[3:] if bare.startswith("**/") else bare[2:]
            for form in (bare, f"**/{bare}"):
                rel = _relative(form)
                if rel is not None and rel not in out:
                    out.append(rel)
    return out


def _write_entry(raw: str) -> str | None:
    """A ``denyWrite`` entry the sandbox honours everywhere: relative, inside
    the tree, no wildcard; ``None`` for one that is not."""
    entry = raw.strip().replace("\\", "/")
    if not entry or entry.startswith("/") or (len(entry) > 1 and entry[1] == ":"):
        return None
    if any(ch in entry for ch in _WILDCARD):
        return None
    if any(part == ".." for part in entry.split("/")):
        return None
    return _relative(entry)


def _adopter_paths(root: Path) -> list[str]:
    from espalier.config import load_config

    try:
        return [str(p) for p in load_config(Path(root)).protected_paths]
    except (OSError, ValueError, TypeError):
        return []  # an unreadable config adds no entry; doctor names the config elsewhere


def deny_write_entries(
    root: Path,
    *,
    self_host: bool | None = None,
    protected_paths: Iterable[str] | None = None,
) -> list[str]:
    """The zone prefixes, the exact protected files not under one, then the
    adopter's ``protected_paths``, each ``./``-relative; ``cc/`` left to the
    hook, ``espalier/`` only on the self-host tree."""
    root = Path(root)
    if self_host is None:
        self_host = surface_contract.is_self_host_repo(root)
    prefixes = [p for p in surface_contract.get_protected_mutation_prefixes() if p not in HOOK_KEPT_ZONES]
    if not self_host:
        prefixes = [p for p in prefixes if p != "espalier/"]
    covered = tuple(prefixes) + HOOK_KEPT_ZONES
    files = [p for p in surface_contract.get_protected_mutation_paths() if not p.startswith(covered)]
    if protected_paths is None:
        protected_paths = _adopter_paths(root)
    out: list[str] = []
    for raw in [*prefixes, *files, *protected_paths]:
        rel = _write_entry(raw)
        if rel is not None and rel not in out:
            out.append(rel)
    return out


def posture(root: Path) -> dict[str, list[str]]:
    """Both lists for ``root``, as ``init`` prints and the flag writes them."""
    return {DENY_WRITE: deny_write_entries(root), DENY_READ: deny_read_entries(root=root)}


# -- the write ------------------------------------------------------------------------


def merge_posture(existing: dict, posture: Mapping[str, Iterable[str]]) -> list[str]:
    """Append the posture's missing entries under ``sandbox.filesystem`` of a
    settings object in place, touching nothing else; returns the entries added
    as ``"<list> <entry>"`` strings (empty: nothing was missing).

    A ``sandbox`` or ``filesystem`` value that is not an object, or a list that
    is not a list, is the operator's to fix and is left alone (nothing added)."""
    sandbox = existing.get(SANDBOX_KEY)
    if sandbox is None:
        sandbox = {}
    elif not isinstance(sandbox, dict):
        return []
    fs = sandbox.get(FILESYSTEM_KEY)
    if fs is None:
        fs = {}
    elif not isinstance(fs, dict):
        return []
    added: list[str] = []
    for name in LISTS:
        wanted = [e for e in posture.get(name, ()) if isinstance(e, str)]
        current = fs.get(name)
        if current is None:
            current = []
        elif not isinstance(current, list):
            continue
        for entry in wanted:
            if entry not in current:
                current.append(entry)
                added.append(f"{name} {entry}")
        if current:
            fs[name] = current
    if added:
        sandbox[FILESYSTEM_KEY] = fs
        existing[SANDBOX_KEY] = sandbox
    return added


def describe(posture: Mapping[str, Iterable[str]], *, written: bool, prefix: str) -> list[str]:
    """The lines ``init`` and ``upgrade`` print: the lists, and whether the
    flag wrote them or would."""
    lists = {name: list(posture.get(name, ())) for name in LISTS}
    total = sum(len(v) for v in lists.values())
    if written:
        head = (f"{prefix} sandbox posture: written to {PROJECT_SETTINGS} ({total} entries under "
                "sandbox.filesystem; sandbox.enabled untouched, /sandbox in a session turns it on)")
    else:
        head = (f"{prefix} sandbox posture (not written; {FLAG} writes it into {PROJECT_SETTINGS}, "
                "never sandbox.enabled):")
    lines = [head]
    for name in LISTS:
        lines.append(f"{prefix}   {name}: " + (", ".join(lists[name]) or "(none)"))
    lines.append(f"{prefix}   a shell layer beside write_guard where the sandbox is on (macOS, Linux, WSL2; "
                 "none on native Windows); the Write, Edit and NotebookEdit tools run outside it; see docs/ADOPTING.md")
    return lines


# -- doctor's read ----------------------------------------------------------------------


@dataclass
class SandboxState:
    """What ``doctor`` can read of the sandbox from the files on this box."""

    supported: bool
    enabled: bool = False
    source: str = ""
    present: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)
    #: ``allowUnsandboxedCommands`` in the user scope; ``None`` when unset or unreadable.
    user_retry: bool | None = None
    user_path: str = ""
    notes: list[str] = field(default_factory=list)


def user_settings_path(environ: Mapping[str, str] | None = None) -> Path:
    """``<CLAUDE_CONFIG_DIR>/settings.json``, else ``~/.claude/settings.json``."""
    env = os.environ if environ is None else environ
    config_dir = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    if config_dir:
        return Path(config_dir).expanduser() / "settings.json"
    home = env.get("HOME") or env.get("USERPROFILE")
    base = Path(home).expanduser() if home else Path.home()
    return base / ".claude" / "settings.json"


def _read_object(path: Path) -> tuple[dict | None, str | None]:
    """``(object, problem)``: the file as a JSON object, or why it is not
    one; an absent file is ``(None, None)``."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"could not be read ({os_error_text(exc)})"
    try:
        body = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"could not be read as JSON ({type(exc).__name__})"
    if not isinstance(body, dict):
        return None, "is not a JSON object"
    return body, None


def _sandbox_of(body: dict | None) -> dict | None:
    sandbox = (body or {}).get(SANDBOX_KEY)
    return sandbox if isinstance(sandbox, dict) else None


def read_state(
    root: Path,
    *,
    posture: Mapping[str, Iterable[str]],
    host_is_windows: bool,
    environ: Mapping[str, str] | None = None,
) -> SandboxState:
    """Read the project, local and user settings files for the sandbox's
    state: enabled by the highest of local, project, user that sets it; the
    posture's entries present anywhere in the three; the user scope's
    ``allowUnsandboxedCommands``. Never writes."""
    root = Path(root)
    state = SandboxState(supported=not host_is_windows)
    user = user_settings_path(environ)
    state.user_path = str(user)
    read: dict[str, dict | None] = {}
    for label, path in (
        (PROJECT_SETTINGS, root / ".claude" / "settings.json"),
        (LOCAL_SETTINGS, root / ".claude" / "settings.local.json"),
        ("the user settings", user),
    ):
        body, problem = _read_object(path)
        if problem:
            state.notes.append(f"{label} ({path}) {problem}")
        read[label] = body
    for label in (LOCAL_SETTINGS, PROJECT_SETTINGS, "the user settings"):
        sandbox = _sandbox_of(read[label])
        if sandbox is not None and "enabled" in sandbox:
            state.enabled = sandbox["enabled"] is True
            state.source = label
            break
    found: dict[str, list[str]] = {name: [] for name in LISTS}
    for body in read.values():
        sandbox = _sandbox_of(body)
        fs = sandbox.get(FILESYSTEM_KEY) if sandbox is not None else None
        if not isinstance(fs, dict):
            continue
        for name in LISTS:
            entries = fs.get(name)
            if isinstance(entries, list):
                found[name].extend(e for e in entries if isinstance(e, str))
    wanted = {name: [e for e in posture.get(name, ()) if isinstance(e, str)] for name in LISTS}
    state.present = {name: [e for e in wanted[name] if e in found[name]] for name in LISTS}
    state.missing = {name: [e for e in wanted[name] if e not in found[name]] for name in LISTS}
    user_sandbox = _sandbox_of(read["the user settings"])
    if user_sandbox is not None and isinstance(user_sandbox.get("allowUnsandboxedCommands"), bool):
        state.user_retry = user_sandbox["allowUnsandboxedCommands"]
    return state


def doctor_lines(state: SandboxState) -> tuple[list[str], list[str]]:
    """``(info, warnings)`` for the doctor report: the three states, the
    entries, the user scope's retry setting, and the one line on what the
    posture is not."""
    info: list[str] = []
    warnings: list[str] = []
    if not state.supported:
        info.append(
            "sandbox: none on native Windows (Claude Code runs shell commands unsandboxed there); "
            "the location layer on this host is the after-check and write_guard's path check; "
            "run Claude Code inside WSL2 to have the sandbox"
        )
        return info, warnings
    n_present = sum(len(v) for v in state.present.values())
    n_missing = sum(len(v) for v in state.missing.values())
    total = n_present + n_missing
    if total == 0:
        tally = "no posture entries derived"
    elif n_missing == 0:
        tally = f"all {total} posture entries present"
    else:
        missing = ", ".join(f"{name} {e}" for name in LISTS for e in state.missing.get(name, []))
        tally = f"{n_missing} posture entries missing of {total} ({missing})"
    writes = f"`{FLAG}` on `init` or `upgrade --execute` writes them"
    if state.enabled:
        line = f"sandbox: on (sandbox.enabled true in {state.source}); {tally}"
        if n_missing:
            warnings.append(f"{line}; {writes}")
        else:
            info.append(line)
    else:
        info.append(
            f"sandbox: off (the default: sandbox.enabled is not true in {PROJECT_SETTINGS}, "
            f"{LOCAL_SETTINGS} or the user settings); {tally}; {writes}, and /sandbox in a session "
            "turns the sandbox on"
        )
    if state.user_retry is False:
        info.append(
            "sandbox: the user settings set allowUnsandboxedCommands false, which holds against a "
            "project's true (Claude Code 2.1.285 or later): a command the sandbox refuses is not "
            "retried outside it"
        )
    else:
        info.append(
            f"sandbox: allowUnsandboxedCommands is not false in the user settings ({state.user_path}), "
            "so a command the sandbox refuses is retried outside it (under bypassPermissions with no "
            "prompt; measured 2026-10-09); set it there yourself, doctor never writes the user scope"
        )
    for note in state.notes:
        info.append(f"sandbox: {note}")
    info.append(
        "sandbox: the posture is a shell layer beside write_guard, never a replacement for its path "
        "check on Write, Edit and NotebookEdit (the sandbox covers shell commands; the file tools run "
        "outside it)"
    )
    return info, warnings
