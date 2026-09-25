"""External-truth pin parser.

Each pin under `docs/external/` (except `README.md`) carries a YAML
frontmatter block declaring its source URL, fetch date, and the section
of the upstream contract being mirrored. This module reads the
frontmatter without a third-party YAML dependency (a tiny key/value
parser handles the supported field shapes — strings, ISO dates, lists,
and block scalars; see `_parse_frontmatter`).

`list_pins()` is the single entrypoint used by the refresh subsystem
and by future tooling that needs to enumerate the verification surface.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from espalier._text import plural

REQUIRED_FIELDS = ("source_url", "fetched", "section", "purpose")
ALLOWED_REFRESH_POLICIES = {"weekly", "monthly", "manual"}


@dataclass(frozen=True)
class ExternalPin:
    """A pinned excerpt of an external contract."""

    path: Path
    source_url: str
    mirrors: tuple[str, ...]
    fetched: date
    section: str
    section_anchor: str | None
    content_hash: str | None
    refresh_policy: str
    purpose: str
    body: str

    @property
    def name(self) -> str:
        """Stem used for CLI `--pin` selection (e.g. `cc-hook-protocol`)."""
        return self.path.stem


def _frontmatter_block(text: str, *, malformed_msg: str) -> str:
    """Return the literal leading ``---\\n … \\n---`` frontmatter block, both
    delimiters included, from ``text``.

    Shared happy-path extractor for the two pin *writers*
    (``external_diff.write_candidate`` and
    ``refresh_externals._rebuild_with_new_body``), which reconstruct a pin from
    its verbatim frontmatter block plus a new body. Assumes ``text`` opens with
    ``---\\n`` (the caller guards or guarantees it); raises
    ``ValueError(malformed_msg)`` when the closing ``---`` is absent, so each
    caller keeps its own operator-facing message. Deliberately NOT reused by
    ``_split_frontmatter`` (the parser) — that one returns the inner yaml plus
    body and never raises; different shape, see its docstring.
    """
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError(malformed_msg)
    return text[: end + 4]


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a markdown file into (frontmatter_yaml, body).

    Returns ("", text) when no frontmatter is present.

    Deliberately does NOT reuse ``_frontmatter_block`` (the writers' shared
    extractor): this parser returns the INNER yaml (``text[4:end]``) plus the
    body and never raises (returns ``("", text)`` on malformed), where the
    writers slice the whole block (``[:end+4]``) and raise. Different shapes —
    a single helper cannot serve both.
    """
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end < 0:
        return "", text
    fm = text[4:end]
    body_start = end + 4
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return fm, text[body_start:]


def _parse_frontmatter(fm: str) -> dict[str, object]:
    """Parse the supported subset of YAML frontmatter.

    Supported shapes:
      key: value                 — simple string
      key: |                     — literal block scalar (next indented lines)
        line 1
        line 2
      key: >                     — folded block scalar (newlines folded to spaces)
        line 1
        line 2
      key:                       — list (next indented `- item` lines)
        - item1
        - item2

    Anything outside this grammar is rejected via ValueError.
    """
    out: dict[str, object] = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not (m := re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)):
            raise ValueError(
                f"frontmatter line not parseable: {line!r}; "
                "keys must start with [A-Za-z_] and contain only letters, "
                "digits, underscores, and hyphens"
            )
        # Normalize hyphens to underscores so callers can use either
        # `source-url` or `source_url` interchangeably without authors
        # having to remember which form is canonical.
        key, rest = m.group(1).replace("-", "_"), m.group(2).rstrip()
        if rest in {"|", "|+", "|-"}:
            # Literal block scalar — collect indented lines.
            block: list[str] = []
            i += 1
            while i < len(lines) and (
                lines[i].startswith(("  ", "\t")) or not lines[i].strip()
            ):
                block.append(lines[i].lstrip())
                i += 1
            out[key] = "\n".join(line for line in block if line).strip()
            continue
        if rest == ">":
            # Folded block — fold newlines into spaces.
            block = []
            i += 1
            while i < len(lines) and (
                lines[i].startswith(("  ", "\t")) or not lines[i].strip()
            ):
                block.append(lines[i].lstrip())
                i += 1
            out[key] = " ".join(line for line in block if line).strip()
            continue
        if rest == "":
            # Inline list — collect `  - item` lines.
            items: list[str] = []
            i += 1
            while i < len(lines):
                if not (m2 := re.match(r"^\s*-\s+(.+)$", lines[i])):
                    break
                items.append(m2.group(1).strip().strip('"').strip("'"))
                i += 1
            out[key] = items
            continue
        # Strip surrounding quotes if present.
        if (rest.startswith('"') and rest.endswith('"')) or (
            rest.startswith("'") and rest.endswith("'")
        ):
            rest = rest[1:-1]
        out[key] = rest
        i += 1
    return out


def parse_pin(path: Path) -> ExternalPin:
    """Read and validate a single pin file. Raises ValueError on missing fields."""
    text = path.read_text(encoding="utf-8")
    fm_text, body = _split_frontmatter(text)
    if not fm_text:
        raise ValueError(
            f"{path.name}: no YAML frontmatter found. Pin must start with `---`."
        )
    fm = _parse_frontmatter(fm_text)

    missing = [f for f in REQUIRED_FIELDS if not fm.get(f)]
    if missing:
        raise ValueError(
            f"{path.name}: missing {plural(len(missing), 'required frontmatter field')}: {missing}"
        )

    fetched_raw = fm["fetched"]
    if not isinstance(fetched_raw, str):
        raise ValueError(f"{path.name}: `fetched` must be a YYYY-MM-DD string")
    try:
        fetched_date = date.fromisoformat(fetched_raw)
    except ValueError as e:
        raise ValueError(
            f"{path.name}: `fetched` is not a valid YYYY-MM-DD date: {e}"
        ) from e

    refresh_policy = fm.get("refresh_policy") or "manual"
    if refresh_policy not in ALLOWED_REFRESH_POLICIES:
        raise ValueError(
            f"{path.name}: `refresh_policy` must be one of "
            f"{ALLOWED_REFRESH_POLICIES}, got {refresh_policy!r}"
        )

    mirrors_raw = fm.get("mirrors", [])
    if isinstance(mirrors_raw, str):
        mirrors_tuple: tuple[str, ...] = (mirrors_raw,) if mirrors_raw else ()
    else:
        mirrors_tuple = tuple(mirrors_raw or ())

    content_hash = fm.get("content_hash") or None
    if isinstance(content_hash, str) and not content_hash.strip():
        content_hash = None

    section_anchor = fm.get("section_anchor") or None
    if isinstance(section_anchor, str) and not section_anchor.strip():
        section_anchor = None

    return ExternalPin(
        path=path,
        source_url=str(fm["source_url"]),
        mirrors=mirrors_tuple,
        fetched=fetched_date,
        section=str(fm["section"]),
        section_anchor=section_anchor if isinstance(section_anchor, str) else None,
        content_hash=content_hash if isinstance(content_hash, str) else None,
        refresh_policy=str(refresh_policy),
        purpose=str(fm["purpose"]),
        body=body,
    )


def list_pins(repo_root: Path) -> list[ExternalPin]:
    """All parseable pins under `<repo_root>/docs/external/`.

    Excludes README.md and any file whose stem starts with `_` or `.`.
    Files that fail to parse raise ValueError to the caller — this is
    intentional. A malformed pin is a release blocker, not a soft warning.
    """
    pins_dir = repo_root / "docs" / "external"
    if not pins_dir.is_dir():
        return []
    out: list[ExternalPin] = []
    for path in sorted(pins_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        if path.stem.startswith(("_", ".")):
            continue
        if path.name.endswith(".candidate.md"):
            continue
        out.append(parse_pin(path))
    return out


def list_pins_lenient(
    repo_root: Path,
) -> tuple[list[ExternalPin], list[tuple[str, str]]]:
    """Like :func:`list_pins`, but collect a malformed pin as a
    ``(name, error)`` pair instead of raising.

    For consumers (audit-accuracy) that must degrade a single bad pin
    to an ``unverifiable`` verdict and keep running, rather than abort
    the whole pass with an exit code indistinguishable from real doc
    drift. The strict :func:`list_pins` stays the release-gate
    entrypoint (refresh subsystem), where a malformed pin IS a blocker.
    """
    pins_dir = repo_root / "docs" / "external"
    if not pins_dir.is_dir():
        return [], []
    out: list[ExternalPin] = []
    errors: list[tuple[str, str]] = []
    for path in sorted(pins_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        if path.stem.startswith(("_", ".")):
            continue
        if path.name.endswith(".candidate.md"):
            continue
        try:
            out.append(parse_pin(path))
        except ValueError as exc:
            errors.append((path.name, str(exc)))
    return out, errors


def compute_body_hash(body: str) -> str:
    """SHA-256 of the normalized body.

    Normalization: strip trailing whitespace per line, collapse to LF
    line endings, drop trailing blank lines. This makes the hash stable
    across editor settings and minor reformatting.
    """
    normalized = "\n".join(line.rstrip() for line in body.splitlines())
    normalized = normalized.rstrip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
