"""Load optional espalier.toml configuration."""
from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any, get_args, get_type_hints

from espalier._compat import tomllib
from espalier.models import HarnessConfig
from espalier._text import os_error_text


CONFIG_NAME = "espalier.toml"


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
    filtered = {k: v for k, v in data.items() if k in fields}
    # Light per-field type guard: a hand-edited espalier.toml can put a
    # bare string where a list is expected (`include_paths = "src"`); unchecked,
    # that str flows into analyze._path_allowed, which iterates it character by
    # character and silently drops the whole intended tree. Drop+warn any field
    # whose parsed type does not match its expected type, falling back to the
    # default. The expected type comes from the dataclass default when it is
    # non-None, and otherwise from the field annotation with ``None`` stripped
    # (so a str-typed optional like ``default_profile`` is validated
    # too, not skipped). The permissive forward-compat contract (unknown keys
    # ignored, valid toml parses cleanly) is unchanged.
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
        validated[key] = value
    return HarnessConfig(**validated)
