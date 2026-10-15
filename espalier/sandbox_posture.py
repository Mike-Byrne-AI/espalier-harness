"""The sandbox posture: Claude Code's ``sandbox.filesystem`` deny lists,
derived from the harness's own rosters.

Claude Code's Bash sandbox (macOS, Linux, WSL2; none on native Windows) is a
boundary the operating system enforces around shell commands and the
processes they start. ``denyWrite`` and ``denyRead`` entries put the harness
zones and the secret paths behind it for every sandboxed command. The lists
are derived here and never copied:

* ``denyWrite``: the prefixes the hook denies at runtime on this kind of tree
  (``surface_contract.get_runtime_protected_prefixes``: ``tools/cc/`` on
  every tree, ``.github/workflows/`` and ``espalier/`` on the self-host tree
  alone, as ``_hook_utils.harness_protected_prefixes`` applies them), the
  exact protected files of ``get_protected_mutation_paths`` not under one,
  then the adopter's ``protected_paths`` from ``espalier.toml``. Two things
  stay with ``write_guard`` because the harness's own shell commands write
  them and the sandbox has no documented narrower allow for writes: ``cc/``
  (the plan, the blueprints, the working summary) and the two manifests
  under ``.espalier/`` (``integrity refresh`` and the freshness scanner). No
  entry carries a wildcard: Linux and WSL2 skip a ``denyWrite`` entry that
  holds one.
* ``denyRead``: the ``_SECRET_PATH_LABEL`` roster of the deployed
  ``tools/cc/hooks/write_guard.py`` (the engine's vendored copy where a tree
  has none yet), parsed from the source by AST so the engine imports no hook;
  ``' / '`` splits a label that names two spellings, and each spelling is
  written at the project root and anywhere below it, since the guard matches
  by name wherever the file sits.
* ``allowRead``: the dotenv template files the guard exempts (its own
  ``_DOTENV_TEMPLATE_SUFFIXES``, parsed the same way), re-opened under the
  glob deny by the documented narrower-allow rule for read rules. Not yet
  driven on a live sandbox: if the Mac drive shows an exact ``allowRead``
  does not narrow a glob ``denyRead``, the glob stays and the divergence is
  documented instead.

Every entry is ``./``-relative, which Claude Code resolves against the
project root for a project settings file (and against ``~/.claude`` for a
user settings file, which is why only the project and local files count
towards the posture). ``sandbox.enabled`` is never written: turning the
sandbox on changes the adopter's network and approval behaviour. The user
scope (``allowUnsandboxedCommands``) is read for ``doctor`` and never
written. Measured 2026-10-09 on macOS: ``denyWrite`` holds for shell writes
and ``git checkout`` and NOT for the ``Write`` tool, so this is a shell layer
beside ``write_guard``, never a replacement for its path check on ``Write``,
``Edit`` and ``NotebookEdit``. ``denyRead`` itself has not been driven yet.
"""
from __future__ import annotations

import ast
import json
import os
import posixpath
import re
import warnings
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
ALLOW_READ = "allowRead"
LISTS: tuple[str, ...] = (DENY_WRITE, DENY_READ, ALLOW_READ)
#: The roster the ``denyRead`` derivation parses out of the guard's source,
#: and the suffix tuple the ``allowRead`` derivation parses beside it.
ROSTER_NAME = "_SECRET_PATH_LABEL"
TEMPLATE_SUFFIXES_NAME = "_DOTENV_TEMPLATE_SUFFIXES"
DOTENV_NAME = ".env"
GUARD_REL = "tools/cc/hooks/write_guard.py"
#: What the hook keeps for itself: the harness's own shell commands write
#: these (the plan and blueprints under cc/, the two manifests), and the
#: sandbox would refuse them with no narrower allow to carve them back out.
HOOK_KEPT_ZONES: tuple[str, ...] = ("cc/",)
HOOK_KEPT_FILES: tuple[str, ...] = (".espalier/integrity.json", ".espalier/freshness.json")
#: Entries an earlier engine wrote that a later one no longer derives:
#: ``(list, entry, why)``. The merge only appends, so a retired entry stays in
#: an adopter's file until they delete it; ``doctor`` names each one present.
RETIRED_ENTRIES: tuple[tuple[str, str, str], ...] = ()
PROJECT_SETTINGS = ".claude/settings.json"
LOCAL_SETTINGS = ".claude/settings.local.json"
USER_SETTINGS = "the user settings"
DOC = "docs/TROUBLESHOOTING.md"
_WILDCARD = ("*", "?", "[")
#: A roster spelling is a path or a glob; anything else is a label that
#: stopped being one (a readability edit), refused by name rather than
#: written as a path.
_SPELLING_RE = re.compile(r"^[A-Za-z0-9_.*/-]+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:(/|$)")


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

    Refuses by name when the assignment is gone, is no longer a literal dict
    of strings, or holds a spelling that is not a path or a glob: a roster
    that moved or was reworded must move this derivation with it, never fall
    silent to an empty list or write a sentence as a path."""
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
        for key, label in value.items():
            for spelling in label.split(" / "):
                if not _SPELLING_RE.match(spelling.strip()):
                    raise ValueError(
                        f"{source}: {ROSTER_NAME}[{key!r}] spells {spelling.strip()!r}, which is "
                        "not a path or a glob; the denyRead derivation reads the label as one"
                    )
        return dict(value)
    raise ValueError(
        f"{source}: no module-level {ROSTER_NAME} assignment; the secret roster moved, "
        "so the denyRead derivation must follow it"
    )


def template_suffixes(source: Path) -> tuple[str, ...]:
    """``_DOTENV_TEMPLATE_SUFFIXES`` as the guard's source declares it, by AST:
    the dotenv names the guard allows a read of. ``()`` when the guard has no
    such tuple (one from before the exemption, which then allows none);
    refused by name when it is there and not a literal sequence of strings."""
    source = Path(source)
    text = source.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text, filename=str(source))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == TEMPLATE_SUFFIXES_NAME for t in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError as exc:
            raise ValueError(f"{source}: {TEMPLATE_SUFFIXES_NAME} is not a literal ({exc})") from exc
        if not isinstance(value, (tuple, list)) or not all(
            isinstance(s, str) and _SPELLING_RE.match(s) for s in value
        ):
            raise ValueError(f"{source}: {TEMPLATE_SUFFIXES_NAME} is not a sequence of suffix strings")
        return tuple(value)
    return ()


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
    and anywhere below it (``./**/.env``). Both forms are written because the
    docs do not say whether ``**/`` matches zero directories; ``denyRead``
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


def allow_read_entries(source: Path | None = None, *, root: Path | None = None) -> list[str]:
    """Two ``./``-relative paths per template suffix the guard exempts, the
    dotenv name plus the suffix at the project root and anywhere below it:
    the files the glob ``denyRead`` would otherwise refuse and the guard
    allows. Empty on a guard with no suffix tuple."""
    if source is None:
        if root is None:
            raise TypeError("allow_read_entries needs the guard's source or the tree's root")
        source = write_guard_source(root)
    out: list[str] = []
    for suffix in template_suffixes(source):
        name = f"{DOTENV_NAME}{suffix}"
        for form in (name, f"**/{name}"):
            rel = _relative(form)
            if rel is not None and rel not in out:
                out.append(rel)
    return out


def write_entry(raw: str) -> tuple[str | None, str | None]:
    """``(entry, why)``: a ``denyWrite`` entry the sandbox honours on every
    host, normalised and ``./``-relative, or ``None`` with the reason it was
    dropped (absolute, a drive, a home path, a climb, a wildcard, the whole
    project)."""
    entry = raw.strip().replace("\\", "/")
    if not entry:
        return None, "empty"
    if entry.startswith("/") or _DRIVE_RE.match(entry):
        return None, "absolute: the posture is written relative to the project root"
    if entry.startswith("~"):
        return None, "a home path: the posture covers the project tree alone"
    if any(ch in entry for ch in _WILDCARD):
        return None, "a wildcard: Linux and WSL2 skip a denyWrite entry that holds one"
    norm = posixpath.normpath(entry)
    if norm in (".", "") or norm == ".." or norm.startswith("../"):
        return None, ("the whole project" if norm in (".", "") else "a climb out of the project")
    return f"./{norm}", None


def _adopter_paths(root: Path) -> list[str]:
    from espalier.config import load_config

    try:
        with warnings.catch_warnings():
            # The loader names an unknown key once per command; doctor and
            # init already read it, so this second read stays quiet.
            warnings.simplefilter("ignore")
            return [str(p) for p in load_config(Path(root)).protected_paths]
    except (OSError, ValueError, TypeError):
        return []  # an unreadable config adds no entry; doctor names the config elsewhere


def deny_write_entries(
    root: Path,
    *,
    self_host: bool | None = None,
    protected_paths: Iterable[str] | None = None,
    dropped: list[str] | None = None,
) -> list[str]:
    """The runtime zone prefixes for this kind of tree, the exact protected
    files not under one or kept by the hook, then the adopter's
    ``protected_paths``, each normalised and ``./``-relative. An adopter entry
    the sandbox could not honour is left out and, when ``dropped`` is given,
    recorded there as ``"<entry>: <why>"``."""
    root = Path(root)
    if self_host is None:
        self_host = surface_contract.is_self_host_repo(root)
    prefixes = [p for p in surface_contract.get_runtime_protected_prefixes(self_host)
                if p not in HOOK_KEPT_ZONES]
    covered = tuple(prefixes) + HOOK_KEPT_ZONES
    files = [p for p in surface_contract.get_protected_mutation_paths()
             if not p.startswith(covered) and p not in HOOK_KEPT_FILES]
    if protected_paths is None:
        protected_paths = _adopter_paths(root)
    out: list[str] = []
    for raw in prefixes + files:
        rel, _why = write_entry(raw)
        if rel is not None and rel not in out:
            out.append(rel)
    for raw in protected_paths:
        rel, why = write_entry(raw)
        if rel is None:
            if dropped is not None:
                dropped.append(f"{str(raw).strip()}: {why}")
        elif rel not in out:
            out.append(rel)
    return out


@dataclass
class Posture:
    """Both lists for a tree, the adopter entries the derivation dropped and
    why, and the guard whose roster it read."""

    lists: dict[str, list[str]]
    dropped: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.lists.values())


def posture(root: Path) -> Posture:
    """Both lists for ``root``, as ``init`` prints and the flag writes them.
    Raises ``ValueError`` (the roster), ``SyntaxError`` (the guard's source)
    or ``OSError`` (the read); the write sites take ``posture_or_refusal``."""
    root = Path(root)
    dropped: list[str] = []
    source = write_guard_source(root)
    lists = {
        DENY_WRITE: deny_write_entries(root, dropped=dropped),
        DENY_READ: deny_read_entries(source),
        ALLOW_READ: allow_read_entries(source),
    }
    return Posture(lists=lists, dropped=dropped, source=str(source))


def posture_or_refusal(root: Path) -> tuple[Posture | None, str | None]:
    """``(posture, None)``, or ``(None, why)`` when the derivation cannot read
    the tree's guard: the write sites print the reason and go on without the
    posture, never a traceback half-way through a deploy."""
    try:
        return posture(root), None
    except (OSError, ValueError, SyntaxError) as exc:
        return None, os_error_text(exc)


# -- the write ------------------------------------------------------------------------


@dataclass
class PostureMerge:
    """What ``merge_posture`` did: the entries appended (``"<list> <entry>"``)
    and the keys it could not write into because the operator's value there
    is not the shape the sandbox reads (``"sandbox.filesystem.denyWrite is
    not a list"``), left untouched and named."""

    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added)


def merge_posture(existing: dict, posture: Mapping[str, Iterable[str]]) -> PostureMerge:
    """Append the posture's missing entries under ``sandbox.filesystem`` of a
    settings object in place, touching nothing else. A ``sandbox`` or
    ``filesystem`` value that is not an object, or a list that is not a list,
    is the operator's to fix: nothing is written under it and the key is
    named in ``skipped``."""
    result = PostureMerge()
    sandbox = existing.get(SANDBOX_KEY)
    if sandbox is None:
        sandbox = {}
    elif not isinstance(sandbox, dict):
        result.skipped.append(f"{SANDBOX_KEY} is not an object")
        return result
    fs = sandbox.get(FILESYSTEM_KEY)
    if fs is None:
        fs = {}
    elif not isinstance(fs, dict):
        result.skipped.append(f"{SANDBOX_KEY}.{FILESYSTEM_KEY} is not an object")
        return result
    for name in LISTS:
        wanted = [e for e in posture.get(name, ()) if isinstance(e, str)]
        current = fs.get(name)
        if current is None:
            current = []
        elif not isinstance(current, list):
            result.skipped.append(f"{SANDBOX_KEY}.{FILESYSTEM_KEY}.{name} is not a list")
            continue
        for entry in wanted:
            if entry not in current:
                current.append(entry)
                result.added.append(f"{name} {entry}")
        if current:
            fs[name] = current
    if result.added:
        sandbox[FILESYSTEM_KEY] = fs
        existing[SANDBOX_KEY] = sandbox
    return result


def init_hint(remedy_py: str) -> str:
    return f"`{remedy_py} -m espalier init . {FLAG}`"


def upgrade_hint(remedy_py: str) -> str:
    return f"`{remedy_py} -m espalier upgrade . --execute {FLAG}`"


def describe(posture: Posture, *, written: bool, prefix: str, remedy_py: str) -> list[str]:
    """The lines ``init`` and ``upgrade`` print: the lists, the adopter
    entries dropped and why, and whether the flag wrote them or would."""
    if written:
        head = (f"{prefix} sandbox posture: written to {PROJECT_SETTINGS} ({posture.total} entries under "
                "sandbox.filesystem; sandbox.enabled untouched, /sandbox in a session turns it on)")
    else:
        head = (f"{prefix} sandbox posture (not written; {FLAG} writes it into {PROJECT_SETTINGS}, "
                f"never sandbox.enabled: {init_hint(remedy_py)} on a fresh tree, "
                f"{upgrade_hint(remedy_py)} on an installed one):")
    lines = [head]
    for name in LISTS:
        lines.append(f"{prefix}   {name}: " + (", ".join(posture.lists.get(name, [])) or "(none)"))
    for item in posture.dropped:
        lines.append(f"{prefix}   left out of denyWrite, from protected_paths: {item}")
    if posture.lists.get(ALLOW_READ):
        lines.append(f"{prefix}   allowRead re-opens the dotenv template files under the denyRead glob by the "
                     "sandbox's narrower-allow rule for reads (not yet driven on a live sandbox)")
    lines.append(f"{prefix}   a shell layer beside write_guard where the sandbox is on (macOS, Linux, WSL2; "
                 "none on native Windows), for every process a sandboxed command starts; the Write, Edit "
                 f"and NotebookEdit tools run outside it; see {DOC}")
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
    #: Retired entries still present: ``"<list> <entry> (<why>)"``.
    retired: list[str] = field(default_factory=list)
    #: Files or keys the read could not take as the sandbox would: one line each.
    notes: list[str] = field(default_factory=list)


def user_settings_path(environ: Mapping[str, str] | None = None) -> Path | None:
    """``<CLAUDE_CONFIG_DIR>/settings.json``, else ``settings.json`` under the
    home's ``.claude`` (``USERPROFILE`` first on Windows, ``HOME`` first
    elsewhere); ``None`` when no home can be found."""
    env = os.environ if environ is None else environ
    config_dir = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    if config_dir:
        return Path(config_dir).expanduser() / "settings.json"
    order = ("USERPROFILE", "HOME") if os.name == "nt" else ("HOME", "USERPROFILE")
    home = next((env.get(k) for k in order if env.get(k)), None)
    if home:
        return Path(home).expanduser() / ".claude" / "settings.json"
    try:
        return Path.home() / ".claude" / "settings.json"
    except RuntimeError:
        return None


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
    posture: Posture | Mapping[str, Iterable[str]],
    host_is_windows: bool,
    environ: Mapping[str, str] | None = None,
) -> SandboxState:
    """Read the project, local and user settings files: enabled by the highest
    of local, project, user that sets it; the posture's entries present in
    the project and local files (a ``./`` entry in the user file resolves
    under ``~/.claude``, so it counts for nothing here); malformed keys named;
    the user scope's ``allowUnsandboxedCommands``. Never writes."""
    root = Path(root)
    lists = posture.lists if isinstance(posture, Posture) else dict(posture)
    state = SandboxState(supported=not host_is_windows)
    user = user_settings_path(environ)
    state.user_path = str(user) if user is not None else "(no home directory found)"
    read: dict[str, dict | None] = {}
    files = [(PROJECT_SETTINGS, root / ".claude" / "settings.json"),
             (LOCAL_SETTINGS, root / ".claude" / "settings.local.json")]
    if user is not None:
        files.append((USER_SETTINGS, user))
    for label, path in files:
        body, problem = _read_object(path)
        if problem:
            state.notes.append(f"{label} ({path}) {problem}")
        read[label] = body
    for label in (LOCAL_SETTINGS, PROJECT_SETTINGS, USER_SETTINGS):
        sandbox = _sandbox_of(read.get(label))
        if sandbox is not None and "enabled" in sandbox:
            state.enabled = sandbox["enabled"] is True
            state.source = label
            break
    found: dict[str, list[str]] = {name: [] for name in LISTS}
    for label in (PROJECT_SETTINGS, LOCAL_SETTINGS):
        body = read.get(label)
        if body is None:
            continue
        raw_sandbox = body.get(SANDBOX_KEY)
        if raw_sandbox is None:
            continue
        if not isinstance(raw_sandbox, dict):
            state.notes.append(f"{label}: {SANDBOX_KEY} is not an object")
            continue
        fs = raw_sandbox.get(FILESYSTEM_KEY)
        if fs is None:
            continue
        if not isinstance(fs, dict):
            state.notes.append(f"{label}: {SANDBOX_KEY}.{FILESYSTEM_KEY} is not an object")
            continue
        for name in LISTS:
            entries = fs.get(name)
            if entries is None:
                continue
            if not isinstance(entries, list):
                state.notes.append(f"{label}: {SANDBOX_KEY}.{FILESYSTEM_KEY}.{name} is not a list")
                continue
            found[name].extend(e for e in entries if isinstance(e, str))
    wanted = {name: [e for e in lists.get(name, ()) if isinstance(e, str)] for name in LISTS}
    state.present = {name: [e for e in wanted[name] if e in found[name]] for name in LISTS}
    state.missing = {name: [e for e in wanted[name] if e not in found[name]] for name in LISTS}
    state.retired = [f"{name} {entry} ({why})" for name, entry, why in RETIRED_ENTRIES
                     if entry in found.get(name, [])]
    user_sandbox = _sandbox_of(read.get(USER_SETTINGS))
    if user_sandbox is not None and isinstance(user_sandbox.get("allowUnsandboxedCommands"), bool):
        state.user_retry = user_sandbox["allowUnsandboxedCommands"]
    return state


def derivation_warning(why: str, *, remedy_py: str) -> tuple[str, str]:
    """``(warning, next step)`` for a tree whose deployed guard has no readable
    secret roster: the guard was edited, stubbed, or is from before the
    roster. ``upgrade`` keeps an unmarked edited hook as yours, so the step
    names the marker, or the delete and a fresh ``init``."""
    warning = (f"sandbox: the posture could not be derived ({why}): the deployed {GUARD_REL} has no "
               "readable secret roster, so its own secret-read deny is in doubt too")
    step = (f"restore {GUARD_REL}: if you edited it, add the managed marker line (# espalier:managed) "
            f"and run `{remedy_py} -m espalier upgrade . --execute`; otherwise delete it and run "
            f"`{remedy_py} -m espalier init .`")
    return warning, step


def doctor_lines(state: SandboxState, *, remedy_py: str) -> tuple[list[str], list[str], list[str]]:
    """``(info, warnings, next steps)`` for the doctor report: the three
    states, the entries, the user scope's retry setting, and the one line on
    what the posture is not."""
    info: list[str] = []
    warnings_out: list[str] = []
    steps: list[str] = []
    if not state.supported:
        info.append(
            "sandbox: none on native Windows (Claude Code runs shell commands unsandboxed there; this "
            "line reads the host doctor runs on, and a session inside WSL2 has the sandbox); the "
            "location layer on this host is the after-check and write_guard's path check"
        )
        return info, warnings_out, steps
    n_present = sum(len(v) for v in state.present.values())
    n_missing = sum(len(v) for v in state.missing.values())
    total = n_present + n_missing
    malformed = [n for n in state.notes if " is not " in n]
    if total == 0:
        tally = "no posture entries derived"
    elif n_missing == 0:
        tally = f"all {total} posture entries present"
    else:
        missing = ", ".join(f"{name} {e}" for name in LISTS for e in state.missing.get(name, []))
        tally = f"{n_missing} posture entries missing of {total} ({missing})"
    if malformed:
        tally += "; not readable as the sandbox reads it: " + "; ".join(malformed)
    writes = (f"{upgrade_hint(remedy_py)} appends them under your keys"
              if not malformed else "fix the named key by hand first, then " + upgrade_hint(remedy_py))
    if state.enabled:
        line = f"sandbox: on (sandbox.enabled true in {state.source}); {tally}"
        if n_missing or malformed:
            warnings_out.append(f"{line}; {writes}")
            steps.append(
                ("fix the sandbox key the warning names in .claude/settings.json by hand, then "
                 if malformed else "")
                + f"run {upgrade_hint(remedy_py)} to append the missing sandbox deny entries under your "
                "keys: the sandbox is on and the harness zones or the secret paths are not behind it"
            )
        else:
            info.append(line)
    else:
        info.append(
            f"sandbox: off (the default: sandbox.enabled is not true in {PROJECT_SETTINGS}, "
            f"{LOCAL_SETTINGS} or the user settings; a managed settings file or --settings is not read "
            f"here); {tally}; {writes}, and /sandbox in a session turns the sandbox on"
        )
    if state.retired:
        info.append("sandbox: entries an earlier init wrote that this engine no longer derives, yours to "
                    "delete: " + "; ".join(state.retired))
    if state.user_retry is False:
        info.append(
            "sandbox: the user settings set allowUnsandboxedCommands false, which holds against a "
            "project's true (Claude Code 2.1.285 or later): a command the sandbox refuses is not "
            "retried outside it"
        )
    else:
        info.append(
            f"sandbox: allowUnsandboxedCommands is not false in the user settings ({state.user_path}; "
            "the scope whose false holds against a project's true; a managed false holds too and is "
            "not read here), so a command the sandbox refuses is retried outside it (with no prompt "
            "in the permission mode that skips prompts; measured 2026-10-09); set it there yourself, "
            "doctor never writes the user scope"
        )
    for note in state.notes:
        if note not in malformed:
            info.append(f"sandbox: {note}")
    info.append(
        "sandbox: the posture is a shell layer beside write_guard, never a replacement for its path "
        "check on Write, Edit and NotebookEdit (the sandbox covers shell commands and the processes "
        f"they start; the file tools run outside it); {DOC} has what it refuses"
    )
    return info, warnings_out, steps
