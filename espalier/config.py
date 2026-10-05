"""Load optional espalier.toml configuration."""
from __future__ import annotations

import dataclasses
import difflib
import warnings
from pathlib import Path
from typing import Any, get_args, get_type_hints

from espalier._compat import tomllib
from espalier.models import HarnessConfig
from espalier._text import os_error_text


CONFIG_NAME = "espalier.toml"

# Keys other readers own. ``load_config`` warns on every top-level key that is
# not a ``HarnessConfig`` field (a typo is otherwise invisible: ``protcted_paths``
# loaded with zero warnings until 2026-09-30, DEF-950), so a key that a script
# outside the engine reads from the same file must be declared here or every load
# of that tree warns -- and the obvious response, deleting the key, removes the
# refusal it carries. Value: the reader, for the message and the census.
FOREIGN_KEYS: dict[str, str] = {
    "record_requires_exclusions": "scripts/record_snapshot.py",
    "record_remote_required": "scripts/record_snapshot.py",
    "handoff_push": "tools/cc/ship.py",
}


def _expected_types(default: Any, annotation: Any) -> tuple[type, ...] | None:
    """Concrete type(s) a config-field value must be an instance of, or None to
    skip validation.

    When the dataclass default is non-None we infer the expected type from it.
    When it's None (e.g. ``default_profile: str | None``) the default carries no
    type information, so strip ``None`` out of the field's annotation and
    validate against what remains — otherwise a str-typed optional field would
    accept any shape.
    """
    if default is not None:
        return (type(default),)
    if annotation is None:
        return None
    concrete = tuple(
        a for a in get_args(annotation)
        if isinstance(a, type) and a is not type(None)
    )
    return concrete or None


def config_sets_key(repo_root: Path, key: str) -> bool:
    """Does ``<repo_root>/espalier.toml`` set the top-level ``key``, whatever its
    value? False when the file is absent, unreadable, malformed or no TOML parser
    imports: a caller that announces a default errs toward announcing it."""
    candidate = repo_root / CONFIG_NAME
    if tomllib is None:
        return False
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return False
    return key in data


def declined_gitignore_entries(repo_root: Path) -> tuple[str, ...]:
    """The ``gitignore_declined`` list from ``<repo_root>/espalier.toml``: the
    required ``.gitignore`` entries the adopter keeps out on purpose (DEF-1106).

    The one reader of the key: ``cli.gitignore_status`` calls it, and init's
    append, both ``upgrade`` arms and ``doctor`` all reach the key through
    that status, so no consumer parses it itself. Quiet like
    ``config_sets_key``: the status is asked several times per command, and
    ``load_config`` already warns once about a malformed file or a wrong-typed
    value. Empty when the file is absent, unreadable or malformed, or the value
    is not a list; non-string items are dropped.
    """
    candidate = repo_root / CONFIG_NAME
    if tomllib is None:
        return ()
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return ()
    value = data.get("gitignore_declined")
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def load_config(repo_root: Path, config_path: Path | None = None) -> HarnessConfig:
    candidate = config_path or (repo_root / CONFIG_NAME)
    if not candidate.exists():
        # An EXPLICIT --config path that does not exist is an
        # operator typo, not "no config present" — warn instead of silently
        # running every --config-taking subcommand with default settings (the
        # operator believes their config was applied). The implicit default
        # (config_path is None, repo/espalier.toml simply absent) stays silent.
        # Mirrors the warn-on-degrade discipline the malformed-TOML branch below
        # already follows.
        if config_path is not None:
            warnings.warn(
                f"--config path {candidate} not found; using default configuration.",
                stacklevel=2,
            )
        return HarnessConfig()
    if tomllib is None:
        warnings.warn(
            f"Found {candidate.name} but no TOML parser available. "
            "Install tomli (`pip install tomli`) for Python < 3.11. "
            "Using default configuration.",
            stacklevel=2,
        )
        return HarnessConfig()
    try:
        text = candidate.read_text(encoding="utf-8")
        data: dict[str, Any] = tomllib.loads(text)
    except (ValueError, OSError) as exc:
        # espalier.toml is the most hand-edited file in an adopter repo. A malformed
        # table (TOMLDecodeError) and a non-UTF-8 byte (UnicodeDecodeError) are both
        # ValueError subclasses; OSError covers a read race. Degrade to defaults with
        # a warning rather than tracebacking through every caller (init / fingerprint
        # / analyze / doctor / diffing) — matches the wrapped sister parses in
        # surface_contract.py and analyze.py.
        warnings.warn(
            f"Found {candidate.name} but could not read or parse it ({os_error_text(exc)}); "
            "using default configuration.",
            stacklevel=2,
        )
        return HarnessConfig()
    if not isinstance(data, dict):
        return HarnessConfig()
    # Allow-set derived from the dataclass schema rather than a hand-mirrored
    # literal: a new HarnessConfig field is then accepted automatically instead
    # of being silently dropped by a set that forgot to list it. Behavior-
    # preserving — the derived names equal the prior 12-name literal set today.
    fields = {f.name for f in dataclasses.fields(HarnessConfig)}
    # An unknown key loads (dropped) but never silently: the file is the most
    # hand-edited one in an adopter repo, and a typo that loads clean is a setting
    # the user wrote that does nothing. A table (``[stack]``) arrives as a
    # dict-valued key and is caught by the same loop. Keys declared in
    # FOREIGN_KEYS belong to another reader and are not unknown.
    for key in sorted(k for k in data if k not in fields and k not in FOREIGN_KEYS):
        near = difflib.get_close_matches(key, sorted(fields), n=1, cutoff=0.6)
        hint = f" (did you mean `{near[0]}`?)" if near else ""
        warnings.warn(
            f"{candidate.name}: unknown key `{key}` is ignored{hint}; "
            f"known keys: {', '.join(sorted(fields))}",
            stacklevel=2,
        )
    filtered = {k: v for k, v in data.items() if k in fields}
    # Light per-field type guard: a hand-edited espalier.toml can put a
    # bare string where a list is expected (`include_paths = "src"`); unchecked,
    # that str flows into analyze._path_allowed, which iterates it character by
    # character and silently drops the whole intended tree. Drop+warn any field
    # whose parsed type does not match its expected type, falling back to the
    # default. The expected type comes from the dataclass default when it is
    # non-None, and otherwise from the field annotation with ``None`` stripped
    # (so a str-typed optional like ``default_profile`` is validated
    # too, not skipped). The permissive forward-compat contract (an unknown key
    # is dropped and the load succeeds; valid toml parses cleanly) is unchanged --
    # the drop now speaks, above.
    defaults = HarnessConfig()
    try:
        hints = get_type_hints(HarnessConfig)
    except Exception:  # noqa: BLE001 -- annotation resolution is best-effort; any failure degrades to "skip None-default validation", never crashes config loading
        hints = {}
    validated: dict[str, Any] = {}
    for key, value in filtered.items():
        expected = _expected_types(getattr(defaults, key), hints.get(key))
        if expected is not None and not isinstance(value, expected):
            warnings.warn(
                f"{candidate.name}: `{key}` expects "
                f"{' | '.join(t.__name__ for t in expected)}, got "
                f"{type(value).__name__}; ignoring it (using default).",
                stacklevel=2,
            )
            continue
        # bool subclasses int, so `lane_count = true` passes the
        # isinstance(value, (int,)) guard above and would be kept as True (=1).
        # Reject a bool where an int (and not bool) is expected. (The reverse —
        # an int where a bool is expected — is already caught by the isinstance
        # check above, since isinstance(1, bool) is False.)
        if (
            expected is not None
            and isinstance(value, bool)
            and int in expected
            and bool not in expected
        ):
            warnings.warn(
                f"{candidate.name}: `{key}` expects "
                f"{' | '.join(t.__name__ for t in expected)}, got bool; "
                f"ignoring it (using default).",
                stacklevel=2,
            )
            continue
        if key == "extra_actions":
            value = _command_lists_only(value, candidate.name)
        validated[key] = value
    return HarnessConfig(**validated)


def _command_lists_only(table: dict[str, Any], file_name: str) -> dict[str, Any]:
    """``table`` without the entries that are not a list of command strings,
    each dropped one named in a warning.

    The guard above checks that ``extra_actions`` is a table and nothing
    inside it, and TOML puts every key written below a table's header INTO
    that table -- so a top-level key placed under ``[extra_actions]`` (the
    example file keeps the table last for this reason) arrives here as an
    action. The plan builder calls ``list()`` on each value: a number raised a
    ``TypeError`` that named no file, from every verb that builds a plan, and a
    string became one command per character, saved without a word. Dropped at
    the one loader those verbs share, so none of them meets it.
    """
    kept: dict[str, Any] = {}
    for name, commands in table.items():
        if isinstance(commands, list) and all(isinstance(c, str) for c in commands):
            kept[name] = commands
            continue
        if isinstance(commands, list):
            strays = sorted({type(c).__name__ for c in commands if not isinstance(c, str)})
            found = "a list holding " + ", ".join(strays)
        else:
            found = type(commands).__name__
        warnings.warn(
            f"{file_name}: under [extra_actions], `{name}` expects a list of "
            f"command strings, got {found}; ignoring it. A key written below "
            "the [extra_actions] header belongs to that table: if this is a "
            "top-level key, move it above the header.",
            stacklevel=3,
        )
    return kept
