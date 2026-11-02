"""Render operator-facing surface docs from the discovered surface.

Produces `cc/LIVE_SURFACE.md`, `cc/COMMANDS.md`, and `cc/PACK_MANIFEST.txt`
from `surface_contract.discover_self_host_surface(repo_root)` so the
content tracks disk reality instead of drifting from hand-edited
templates.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from espalier import __version__  # deploy-time version stamp
from espalier import surface_contract
from espalier._atomic_io import atomic_write_text
from espalier._safe_walk import safe_rglob, visible
from espalier.harness_config import CANONICAL_HOOK_WIRING
from espalier.managed_markers import MANAGED_MARKER

#: What re-checks a change once the local hooks are off, in a sentence true on
#: every tree: plain ``init`` installs no CI gate, and the texts that carry this
#: (cc/LIVE_SURFACE.md here, the root CLAUDE.md ``cli._build_claude_md`` writes
#: once) outlive the tree they were rendered on, so a claim keyed on today's tree
#: would turn false at the adopter's next ``install-ci``. The hooks' own texts,
#: judged live at each event, say which case holds.
CI_RECHECK_SENTENCE = (
    "CI re-checks pull requests where the CI gate is installed "
    "(`espalier install-ci`; plain `init` installs none)."
)

# The core-loop commands surfaced in the SessionStart banner's "Commands:" line.
# SINGLE SOURCE OF TRUTH for "core" -- render_commands_doc emits these into
# cc/COMMANDS.md's `## Core flow` section, which the banner's _commands_footer
# reads. Replaces the former hardcoded tuple in session_start.py (which could
# not see a newly-added core command). Order is the getting-started loop order:
# /ship comes AFTER /handoff because a session pushes each lane once, at its
# end -- the handoff's row rides the same push as the work, so the list's
# order is the instruction (eight handoff-only pull requests since the
# 2026-09-25 cut, each a full check cycle, were the cost of the other order).
# sister-site: ok SoT for the core-flow command list; session_start._CORE_FLOW_COMMANDS is a crash-fallback copy of this
CORE_FLOW_COMMANDS = (
    "/status", "/implement-task", "/smoke", "/preflight", "/commit", "/handoff", "/ship",
)


def _agent_name(path: str) -> str:
    return Path(path).stem


def _command_name(path: str) -> str:
    return Path(path).stem


def _skill_name(path: str) -> str:
    # The path ends in ".../<name>/SKILL.md", so .stem would return the literal
    # "SKILL"; the skill's name is the parent directory.
    return Path(path).parent.name


_WORKFLOW_META_BLOCK_RE = re.compile(r"export\s+const\s+meta\s*=\s*\{(.*?)\n\}", re.S)
_WORKFLOW_NAME_RE = re.compile(r"^\s*name\s*:\s*(['\"`])((?:(?!\1)[^\\]|\\.)*)\1", re.M)


def _workflow_name(path: Path) -> str:
    """The ``/<name>`` a workflow runs as, from the ``name`` field of its
    ``export const meta`` block (single-, double- or back-quoted), the first
    such field inside that block only. The filename (leading underscore
    stripped, underscores to hyphens) is the fallback when the block is absent
    or unreadable. Only the name renders: a description edit must not stale
    the committed surface doc, whose pin runs on the maintainer machine alone.
    """
    fallback = path.stem.lstrip("_").replace("_", "-")
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return fallback
    block = _WORKFLOW_META_BLOCK_RE.search(head)
    if not block:
        return fallback
    m = _WORKFLOW_NAME_RE.search(block.group(1))
    return m.group(2) if m and m.group(2) else fallback


_BLOCK_SCALAR_MARKERS = ("|", "|-", "|+", ">", ">-", ">+")


def _is_block_scalar_header(head: str) -> bool:
    """Recognize a YAML block-scalar header, including the explicit
    indentation-indicator forms (``|2``, ``>2``, ``|-2``, ``|2-``) that the
    plain marker tuple misses. A block-scalar header is never a literal
    one-line value, so a leaked ``|2`` must route to the block branch instead
    of being returned verbatim as the description. A real single-line value like
    ``> see docs`` has non-digit/non-chomp content after the marker and stays on
    the single-line path."""
    if head in _BLOCK_SCALAR_MARKERS:
        return True
    if not head or head[0] not in "|>":
        return False
    # Strip a chomp indicator (-/+) from either side; the remainder of a valid
    # block-scalar header is the optional indent indicator (a single digit) or
    # nothing.
    rest = head[1:].strip("+-")
    return rest == "" or rest.isdigit()


def _unquote_frontmatter_value(value: str) -> str:
    """Strip matched single or double quotes from a single-line scalar."""
    value = value.strip()
    if (value.startswith("\"") and value.endswith("\"")) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1].strip()
    return value


def _normalize_description_text(text: str) -> str:
    """Collapse whitespace/newlines into a single renderable sentence."""
    return " ".join(text.split()).strip()


def _block_scalar_body_continues(line: str) -> bool:
    """True if ``line`` still belongs to an open block-scalar body.

    A blank line is a paragraph break INSIDE the block, not a terminator; only a
    nonblank line at column 0 — the next top-level frontmatter key — ends it.

    Shared with ``cli._parse_yaml_frontmatter`` so the two frontmatter parsers
    cannot drift on where a block ends. They did: cli stopped at the first blank
    line and silently dropped every following paragraph from the CLAUDE.md
    tables, while this renderer kept reading. Neither is YAML-correct (real YAML
    turns a blank line into a literal newline, so PyYAML agrees with neither) —
    the contract here is that the two AGREE, not that either conforms.
    """
    return not line.strip() or line.startswith((" ", "\t"))


def _read_frontmatter_description(path: Path) -> str:
    """Pull the `description:` field from a YAML frontmatter block, if any.

    Supports the description shapes this repo actually uses:
      - single-line: ``description: text`` / ``"text"`` / ``'text'``
      - folded block: ``description: >`` / ``>-`` / ``>+``
      - literal block: ``description: |`` / ``|-`` / ``|+``

    Block-scalar bodies are captured by indentation: every nonblank line
    indented past the ``description:`` key belongs to it; the block ends at
    the next top-level frontmatter key. The body is whitespace-normalized
    to a single line so it renders cleanly in tables and bullet lists.

    Never returns the raw block markers (``>``, ``|``, etc.).

    This is a deliberately small parser — not a full YAML implementation.
    Out-of-scope inputs (multi-document streams, complex anchors, mappings
    nested inside ``description``) are not supported, and that is fine for
    the agent/command frontmatter shape the harness controls.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    block = text[3:end]
    lines = block.splitlines()

    # Find the description key line.
    desc_idx: int | None = None
    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r")
        # Top-level key only — must start at column 0.
        if line.startswith("description:"):
            desc_idx = i
            break
    if desc_idx is None:
        return ""

    head = lines[desc_idx][len("description:"):].strip()

    # Block-scalar form: marker on the same line as the key, body on
    # subsequent indented lines.
    if _is_block_scalar_header(head):
        body_lines: list[str] = []
        for follow in lines[desc_idx + 1:]:
            # Blank = paragraph break inside the block; a nonblank line at
            # column 0 is the next top-level key and terminates it.
            if not _block_scalar_body_continues(follow):
                break
            body_lines.append(follow)
        return _normalize_description_text("\n".join(body_lines))

    # Single-line form (possibly quoted).
    return _unquote_frontmatter_value(head)


def _skip_non_prose_block(lines: list[str], i: int) -> int:
    """If ``lines[i]`` opens a non-prose block, return the index AFTER it.

    Non-prose block shapes (any one of these at line ``i``):
      - blank line
      - markdown heading (line starts with ``#``)
      - blockquote line (line starts with ``>``)
      - HTML comment (line starts with ``<!--``) — may span multiple
        lines; skipped through the matching ``-->`` (same line OK)
      - fenced code block (line starts with ``` ``` ```) — multi-line;
        skipped through the matching closing fence

    Returns ``i`` unchanged when ``lines[i]`` is prose. Unterminated
    HTML comments or code fences consume to EOF.
    """
    if i >= len(lines):
        return i
    stripped = lines[i].strip()
    if not stripped:
        return i + 1
    if stripped.startswith(("#", ">")):
        return i + 1
    if stripped.startswith("<!--"):
        if "-->" in stripped:
            return i + 1
        j = i + 1
        while j < len(lines):
            if "-->" in lines[j]:
                return j + 1
            j += 1
        return j
    if stripped.startswith("```"):
        j = i + 1
        while j < len(lines):
            if lines[j].strip().startswith("```"):
                return j + 1
            j += 1
        return j
    return i


def _read_body_description(path: Path) -> str:
    """Return the first prose paragraph of the body (skipping frontmatter).

    A command may open with a short paragraph as its summary rather
    than carrying a YAML ``description:`` field (an adopter's own; the
    packaged ones all carry the field, DEF-1097). This fallback surfaces
    that summary instead of emitting ``—`` for such a command.

    The scan rules:
      - YAML frontmatter (a leading ``---`` block) is consumed first.
      - Leading blank lines, markdown headings (``# ...``), blockquote
        lines (``> ...``), HTML comments (``<!-- ... -->`` — multi-line
        permitted), and fenced code blocks (``` ``` ``` ``) are skipped
        — they are not prose summaries. Internal markers like
        ``<!-- espalier:managed -->`` would otherwise leak into the
        rendered surface index.
      - The first contiguous run of prose lines is captured and
        whitespace-normalized to a single renderable line (matches the
        folded-block frontmatter behavior). A non-prose line in the
        middle of a paragraph also terminates the capture.

    Returns ``""`` if the file is unreadable, missing, or has no prose
    body content.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = text.splitlines()
    i = 0
    # Skip a leading frontmatter block, if present.
    if lines and lines[0].rstrip("\r") == "---":
        for j in range(1, len(lines)):
            if lines[j].rstrip("\r") == "---":
                i = j + 1
                break
        else:
            # Unclosed frontmatter — nothing to scan.
            return ""

    # Skip phase: consume non-prose blocks until we find a prose line.
    while i < len(lines):
        new_i = _skip_non_prose_block(lines, i)
        if new_i == i:
            break  # lines[i] is prose
        i = new_i
    if i >= len(lines):
        return ""

    # Capture phase: first contiguous prose paragraph. A non-prose line
    # mid-paragraph terminates the capture.
    paragraph: list[str] = []
    while i < len(lines):
        if _skip_non_prose_block(lines, i) != i:
            break
        paragraph.append(lines[i].strip())
        i += 1
    return _normalize_description_text(" ".join(paragraph))


def _read_description(path: Path) -> str:
    """Read a surface description: frontmatter takes precedence over body.

    Wraps ``_read_frontmatter_description`` with a body-line fallback so
    a file that documents its purpose in plain prose (an adopter's own
    command, say) is not rendered as ``—``.
    """
    desc = _read_frontmatter_description(path)
    if desc:
        return desc
    return _read_body_description(path)


# --- Frontmatter Claude Code will not load --------------------------------------
#
# Claude Code parses a body's frontmatter as strict YAML and, when that fails,
# retries after quoting each value with a pattern a trailing carriage return
# defeats. Measured on Claude Code 2.1.314 (2026-11-02): a value strict YAML
# rejects (an unquoted ``: `` inside it, a value opening on ``[``) loads with LF
# line endings and fails with CRLF, so the agent does not register and a skill
# or command loads with its frontmatter dropped; a `` #`` loads under both, the
# rest read as a comment. The two readers above are lenient line splitters and
# see neither. ``frontmatter_hazards`` names both shapes per top-level key; its
# hook twin is ``post_write_check._frontmatter_hazards`` (a hook cannot import
# the engine), held to the same verdicts by
# tests/test_frontmatter_will_not_load.py, whose oracle is PyYAML.

# What was measured, and what was not. On Claude Code 2.1.314, one headless run
# per shape: an unquoted ``: `` inside a value and a value opening on ``[`` (each
# loads with LF; with CRLF the agent does not register and a skill or command
# loads with its frontmatter dropped, its description the body's first line),
# and a `` #`` (loads under both, the description cut). Every other shape below
# is FRAGILE by the PyYAML oracle, not by a drive: that Claude Code's strict
# parse rejects it as PyYAML does, and so loses it under CRLF the same way, is
# probable, not measured.
FRONTMATTER_FRAGILE = "fragile"
FRONTMATTER_CUT = "cut"

# YAML forbids these at the start of a plain scalar; '-', '?' and ':' open one
# only when a non-space follows.
_PLAIN_FORBIDDEN_FIRST = "]},%@`"
_DQ_SIMPLE_ESCAPES = frozenset("0abt\tnvfre \"/\\N_LP")
_DQ_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _frontmatter_lines(text: str) -> list[str] | None:
    """The raw lines between the opening and closing ``---``, carriage returns
    kept, or ``None`` when the body opens no closed block. One leading
    byte-order mark is read past: whether Claude Code reads a BOM'd body's
    frontmatter at all is unmeasured, so the check judges what follows it."""
    lines = text.removeprefix("\ufeff").split("\n")
    if lines[0].rstrip("\r") != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            return lines[: i + 1]
    return None


def frontmatter_has_crlf(text: str) -> bool:
    """True when the frontmatter block holds CRLF line endings on disk."""
    lines = _frontmatter_lines(text)
    return lines is not None and any(line.endswith("\r") for line in lines)


def _top_level_key(line: str) -> tuple[str | None, str]:
    """``(key, value)`` for a ``key: value`` line at column 0, else ``(None, "")``."""
    if not line or line[0] in " \t#-":
        return None, ""
    pos = line.find(":")
    while pos != -1 and line[pos + 1:pos + 2] not in ("", " "):
        pos = line.find(":", pos + 1)
    if pos <= 0:
        return None, ""
    key = line[:pos]
    if not all(ch.isalnum() or ch in "_-." for ch in key):
        return None, ""
    return key, line[pos + 1:]


def _scan_quoted(value: str) -> tuple[str, int | str]:
    """Where a value opening on a quote closes: ``("closed", index)``,
    ``("unclosed", "")`` or ``("escape", char)`` for an escape YAML refuses."""
    quote = value[0]
    i = 1
    while i < len(value):
        ch = value[i]
        if quote == '"' and ch == "\\":
            nxt = value[i + 1:i + 2]
            if not nxt:
                return "unclosed", ""
            if nxt in _DQ_HEX_ESCAPES:
                width = _DQ_HEX_ESCAPES[nxt]
                digits = value[i + 2:i + 2 + width]
                if len(digits) != width or not set(digits) <= _HEX_DIGITS:
                    return "escape", nxt
                i += 2 + width
                continue
            if nxt not in _DQ_SIMPLE_ESCAPES:
                return "escape", nxt
            i += 2
            continue
        if ch == quote:
            if quote == "'" and value[i + 1:i + 2] == "'":
                i += 2
                continue
            return "closed", i
        i += 1
    return "unclosed", ""


def _scan_flow(value: str) -> int | None:
    """The index closing a flow collection that opens the value, or ``None``.
    A quote opens a quoted item only at an item's start (after ``[``, ``{``,
    ``,`` or ``: ``, spaces skipped); inside a plain item it is a character,
    as in ``[don't, b]``."""
    depth, quote, i, item_start = 0, "", 0, True
    while i < len(value):
        ch = value[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == " ":
            pass
        elif ch in "\"'" and item_start:
            quote = ch
            item_start = False
        elif ch in "[{":
            depth += 1
            item_start = True
        elif ch == "," or (ch == ":" and value[i + 1:i + 2] in ("", " ")):
            item_start = True
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return i
            item_start = False
        else:
            item_start = False
        i += 1
    return None


def _tail_is_clean(tail: str) -> bool:
    """Nothing, or a comment, after a closed quote or bracket."""
    rest = tail.lstrip(" ")
    return not rest or (rest.startswith("#") and len(rest) < len(tail))


def _block_header_is_valid(value: str) -> bool:
    """``|`` or ``>`` with at most one chomping and one indentation indicator,
    then nothing or a comment."""
    head = value[1:]
    cut = head.find(" #")
    if cut != -1:
        head = head[:cut]
    head = head.rstrip(" ")
    chomp = sum(1 for ch in head if ch in "+-")
    indent = sum(1 for ch in head if ch in "123456789")
    return chomp + indent == len(head) and chomp <= 1 and indent <= 1


def _judge_frontmatter_value(value: str, cont: list[str]) -> tuple[str, str, str] | None:
    """``(verdict, why, kept)`` for one top-level value and the continuation
    lines under it, or ``None`` for a value strict YAML reads as written (or
    one outside this check: a nested node, a multi-line quote or flow, a tab,
    an anchor or a standard tag)."""
    value = value.strip(" ")
    if "\t" in value or any("\t" in line for line in cont):
        return None
    more = [line.strip(" ") for line in cont if line.strip(" ")]
    if not value:
        return None
    first = value[0]
    if first == "#":
        return None if more else (FRONTMATTER_CUT, "a value opening on '#'", "")
    if first in "|>":
        if _block_header_is_valid(value):
            return None
        return FRONTMATTER_FRAGILE, f"a block-scalar marker '{first}' followed by text", ""
    if first in "\"'":
        state, where = _scan_quoted(value)
        if state == "escape":
            return FRONTMATTER_FRAGILE, f"an unknown escape '\\{where}' inside double quotes", ""
        if state == "unclosed":
            return None if more else (FRONTMATTER_FRAGILE, "an unclosed quote", "")
        if more:
            return None
        if _tail_is_clean(value[int(where) + 1:]):
            return None
        return FRONTMATTER_FRAGILE, "text after the closing quote", ""
    if first in "[{":
        end = _scan_flow(value)
        if end is None:
            return None if more else (FRONTMATTER_FRAGILE, "an unclosed bracket", "")
        if more or _tail_is_clean(value[end + 1:]):
            return None
        return FRONTMATTER_FRAGILE, f"text after the closing '{value[end]}'", ""
    if first in _PLAIN_FORBIDDEN_FIRST or first == "*":
        return FRONTMATTER_FRAGILE, f"an unquoted value opening on '{first}'", ""
    if first == "&" or value.startswith(("!!", "! ")) or value == "!":
        return None
    if first == "!":
        return FRONTMATTER_FRAGILE, "an unquoted value opening on '!'", ""
    if first in "-?:" and value[1:2] in ("", " "):
        return FRONTMATTER_FRAGILE, f"an unquoted value opening on '{first}'", ""
    segments = [value] + more
    for n, seg in enumerate(segments):
        if n and seg.startswith("#"):
            if any(not s.startswith("#") for s in segments[n + 1:]):
                return FRONTMATTER_FRAGILE, "text continuing after a ' #' comment", ""
            return None
        colon = seg.find(":")
        while colon != -1 and seg[colon + 1:colon + 2] not in ("", " "):
            colon = seg.find(":", colon + 1)
        hash_at = seg.find(" #")
        if colon != -1 and (hash_at == -1 or colon < hash_at):
            if colon == len(seg) - 1:
                return FRONTMATTER_FRAGILE, "an unquoted value ending in ':'", ""
            return FRONTMATTER_FRAGILE, "': ' inside an unquoted value", ""
        if hash_at != -1:
            if any(not s.startswith("#") for s in segments[n + 1:]):
                return FRONTMATTER_FRAGILE, "text continuing after a ' #' comment", ""
            kept = " ".join(segments[:n] + [seg[:hash_at].rstrip(" ")])
            return FRONTMATTER_CUT, "' #' inside an unquoted value", kept
    return None


def frontmatter_hazards(text: str) -> list[tuple[str, str, str, str]]:
    """``(key, verdict, why, kept)`` for each top-level frontmatter key strict
    YAML reads otherwise than written: :data:`FRONTMATTER_FRAGILE` where it
    rejects the value (Claude Code then loads the body only through a fallback
    that CRLF line endings defeat), :data:`FRONTMATTER_CUT` where it reads the
    value shorter (``kept`` is what it reads). Empty for a body with no closed
    frontmatter block."""
    block = _frontmatter_lines(text)
    if block is None:
        return []
    lines = [line.rstrip("\r") for line in block[1:-1]]
    out: list[tuple[str, str, str, str]] = []
    i = 0
    while i < len(lines):
        key, value = _top_level_key(lines[i])
        i += 1
        if key is None:
            continue
        cont: list[str] = []
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            cont.append(lines[i])
            i += 1
        verdict = _judge_frontmatter_value(value, cont)
        if verdict is not None:
            out.append((key, *verdict))
    return out


def frontmatter_body_kind(rel_path: str) -> str | None:
    """``agent``, ``command`` or ``skill`` for a ``.claude`` body Claude Code
    reads frontmatter from, else ``None``."""
    rel = rel_path.replace("\\", "/").lower()
    if rel.startswith(".claude/agents/") and rel.endswith(".md"):
        return "agent"
    if rel.startswith(".claude/commands/") and rel.endswith(".md"):
        return "command"
    if rel.startswith(".claude/skills/") and rel.endswith("/skill.md"):
        return "skill"
    return None


def frontmatter_fragile_sentence(rel_path: str, kind: str, key: str, why: str, crlf: bool) -> str:
    """What a FRAGILE key does to the body, by the line endings on disk."""
    if crlf and kind == "agent":
        return (
            f"{rel_path}: this agent does not register: its frontmatter has CRLF line "
            f"endings and `{key}` is not strict YAML ({why}), which Claude Code cannot "
            "read past; quote the value"
        )
    if crlf:
        return (
            f"{rel_path}: Claude Code drops this {kind}'s frontmatter (its description "
            f"and allowed tools): the file has CRLF line endings and `{key}` is not "
            f"strict YAML ({why}); quote the value"
        )
    effect = (
        "this agent will not register" if kind == "agent"
        else f"this {kind}'s frontmatter will be dropped"
    )
    return (
        f"{rel_path}: `{key}` is not strict YAML ({why}); Claude Code reads it with "
        f"LF line endings, but {effect} once checked out with CRLF line endings "
        "(core.autocrlf on Windows); quote the value"
    )


def frontmatter_cut_sentence(rel_path: str, why: str, kept: str) -> str:
    """What a CUT description reads as."""
    shown = f'"{kept}"' if kept else "no description"
    at = '"#"' if why.startswith("a value opening") else '" #"'
    return (
        f"{rel_path}: the description is cut at {at} (YAML reads the rest as a "
        f"comment), so Claude Code shows {shown}; quote the value to keep it whole"
    )


def frontmatter_notes(rel_path: str, text: str) -> list[tuple[str, str]]:
    """``(kind_of_note, sentence)`` for what the audit and the roster say of a
    body: ``drop`` for a FRAGILE key with CRLF on disk (the body does not load
    whole now), ``cut`` for a cut description. A FRAGILE key with LF on disk
    loads, so it is said only at the write and by ``doctor``."""
    kind = frontmatter_body_kind(rel_path)
    if kind is None:
        return []
    crlf = frontmatter_has_crlf(text)
    notes: list[tuple[str, str]] = []
    for key, verdict, why, kept in frontmatter_hazards(text):
        if verdict == FRONTMATTER_FRAGILE and crlf:
            notes.append(("drop", frontmatter_fragile_sentence(rel_path, kind, key, why, True)))
        elif verdict == FRONTMATTER_CUT and key == "description":
            # A CUT is said for the description alone: a ` #` after another
            # key's value (`model: sonnet  # cheaper`) is idiomatic commenting,
            # and the description is the one value Claude Code shows.
            notes.append(("cut", frontmatter_cut_sentence(rel_path, why, kept)))
    return notes


def frontmatter_body_paths(repo_root: Path) -> list[str]:
    """Repo-relative paths of every agent, command and skill body under
    ``.claude``, nested ones included (a namespaced command, an agent in a
    team folder, a skill under a group): the bodies the write-time check
    judges, where discovery lists the top level the roster renders."""
    out: list[str] = []
    for kind, pattern in (("agents", "*.md"), ("commands", "*.md"), ("skills", "SKILL.md")):
        base = repo_root / ".claude" / kind
        if not base.is_dir():
            continue
        for path in visible(safe_rglob(base, pattern), base):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if frontmatter_body_kind(rel) is not None:
                out.append(rel)
    return sorted(out)


def _read_body_bytes(path: Path) -> str:
    """A body's text with its line endings as on disk (``read_text`` would
    turn CRLF into LF), or ``""`` when it cannot be read."""
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _roster_entry(repo_root: Path, rel_path: str, label: str) -> str:
    """One roster line: the body as Claude Code loads it, marked where its
    frontmatter is dropped or its description cut."""
    text = _read_body_bytes(repo_root / rel_path)
    kind = frontmatter_body_kind(rel_path)
    hazards = frontmatter_hazards(text) if kind else []
    crlf = bool(hazards) and frontmatter_has_crlf(text)
    for key, verdict, why, _kept in hazards:
        if verdict == FRONTMATTER_FRAGILE and crlf:
            mark = "NOT REGISTERED" if kind == "agent" else "FRONTMATTER DROPPED"
            return (
                f"- `{label}` -- {mark}: CRLF line endings and `{key}` is not strict "
                f"YAML ({why}); quote the value"
            )
    for key, verdict, _why, kept in hazards:
        if verdict == FRONTMATTER_CUT and key == "description":
            return f"- `{label}` -- {kept or '--'} (description cut at \"#\"; quote the value)"
    desc = _read_description(repo_root / rel_path)
    return f"- `{label}` -- {desc}" if desc else f"- `{label}`"


def _load_stable_actions(repo_root: Path) -> dict[str, list[str]]:
    """Read stable_actions from the saved harness_config.json, if present."""
    path = repo_root / "reports" / "harness_config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    actions = data.get("stable_actions", {}) if isinstance(data, dict) else {}
    return actions if isinstance(actions, dict) else {}


def render_live_surface(repo_root: Path) -> str:
    """Render cc/LIVE_SURFACE.md content from the discovered surface."""
    surface = surface_contract.discover_self_host_surface(repo_root)
    agents = surface.get("agents", [])
    commands = surface.get("commands", [])
    skills = surface.get("skills", [])
    workflows = surface.get("workflows", [])
    hooks = surface.get("hooks", [])
    stable_actions = _load_stable_actions(repo_root)

    lines = [
        f"<!-- {MANAGED_MARKER} -->",
        "# Live Surface",
        "",
        "Canonical index of the harness surface deployed to this repository. Rendered from the",
        "discovered surface; edit `espalier init` rendering logic, not this file.",
        "",
        "## Session bootstrap",
        "1. SessionStart hook loads blueprint chain, cleans per-session flags, writes timestamp.",
        "2. Run `/status` to verify harness state.",
        "3. Run `/smoke` to verify surface integrity (folds the former `/audit`'s `espalier audit .` invocation as Step 7).",
        "",
        "## Hook semantics",
        (
            "SessionStart loads context and reports integrity state. "
            "ConfigChange and PreToolUse are the blocking local hook surfaces. "
            f"{CI_RECHECK_SENTENCE} SessionStart cannot block Claude "
            "Code execution per the official hook protocol "
            "(docs/external/cc-hook-protocol.md)."
        ),
        "",
        f"## Hook architecture ({len(hooks)} hooks across canonical events)",
    ]
    for hook_path in hooks:
        name = Path(hook_path).name
        wiring = CANONICAL_HOOK_WIRING.get(name, {})
        event = wiring.get("event", "?")
        matcher = wiring.get("matcher", "")
        matcher_suffix = f' ("{matcher}")' if matcher else ""
        reason = wiring.get("reason", "")
        lines.append(f"- `{event}{matcher_suffix}` -> `{name}` -- {reason}")

    if stable_actions:
        lines.append("")
        lines.append("## Stable actions")
        for action, cmds in sorted(stable_actions.items()):
            cmd = cmds[0] if cmds else ""
            lines.append(f"- `{action}` -> `{cmd}`")

    lines.append("")
    lines.append(f"## Agent roster ({len(agents)} agents)")
    for agent_path in agents:
        lines.append(_roster_entry(repo_root, agent_path, _agent_name(agent_path)))

    lines.append("")
    lines.append(f"## Commands ({len(commands)} commands)")
    for cmd_path in commands:
        lines.append(_roster_entry(repo_root, cmd_path, f"/{_command_name(cmd_path)}"))

    lines.append("")
    lines.append(f"## Skills ({len(skills)} skills)")
    for skill_path in skills:
        lines.append(_roster_entry(repo_root, skill_path, f"/{_skill_name(skill_path)}"))

    lines.append("")
    lines.append(f"## Workflows ({len(workflows)} workflows)")
    for wf_path in workflows:
        lines.append(f"- `/{_workflow_name(repo_root / wf_path)}`")

    return "\n".join(lines) + "\n"


def render_commands_doc(repo_root: Path) -> str:
    """Render cc/COMMANDS.md content from the discovered command surface."""
    surface = surface_contract.discover_self_host_surface(repo_root)
    commands = surface.get("commands", [])
    stable_actions = _load_stable_actions(repo_root)

    lines = [
        f"<!-- {MANAGED_MARKER} -->",
        "# Commands",
        "",
        "Rendered from `.claude/commands/` and saved stable_actions.",
        "",
        "| Command | Purpose |",
        "|---|---|",
    ]
    for cmd_path in commands:
        name = _command_name(cmd_path)
        # Escape literal pipes so a description containing '|' does not inject
        # an extra column into this 2-column GFM table.
        desc = (_read_description(repo_root / cmd_path) or "--").replace("|", "\\|")
        lines.append(f"| `/{name}` | {desc} |")
    # Core-flow section: the source of truth for the banner's "Commands:" line
    # (session_start._commands_footer reads it). Emit only names present in the
    # discovered surface, in CORE_FLOW_COMMANDS order, so a removed command never
    # lingers and a newly-marked one surfaces on regen.
    discovered = {f"/{_command_name(c)}" for c in commands}
    core_present = [c for c in CORE_FLOW_COMMANDS if c in discovered]
    if core_present:
        lines.append("")
        lines.append("## Core flow")
        lines.append("")
        lines.append(" ".join(f"`{c}`" for c in core_present))
    if stable_actions:
        lines.append("")
        lines.append("## Stable actions")
        lines.append("")
        lines.append("| Action | Command |")
        lines.append("|---|---|")
        for action, cmds in sorted(stable_actions.items()):
            esc_action = action.replace("|", "\\|")
            cmd = (cmds[0] if cmds else "").replace("|", "\\|")
            lines.append(f"| `{esc_action}` | `{cmd}` |")
    return "\n".join(lines) + "\n"


def _surface_digest(files: "Iterable[tuple[str, Any]]") -> str:
    """sha256 over ``(rel, source)`` pairs, in ``rel`` order, each source read
    as its canonical text -- a leading BOM stripped, CRLF and bare CR folded to
    LF, the integrity manifest's rule (``_integrity.canonical_text_bytes``, its
    one owner) -- so a Windows checkout's line endings are the same build (the
    content-hash CRLF edge in docs/SHARP_EDGES.md) while a changed byte or a
    moved file is another. A source that cannot be read counts as missing,
    never as a crash of the render that stamps the digest."""
    from espalier._integrity_bridge import load_integrity_module

    canon = load_integrity_module().canonical_text_bytes
    digest = hashlib.sha256()
    for rel, source in sorted(files, key=lambda item: item[0]):
        digest.update(f"{rel}\0".encode("utf-8"))
        try:
            digest.update(canon(source.read_bytes()))
        except OSError:
            digest.update(b"\0missing")
        digest.update(b"\0")
    return digest.hexdigest()


@functools.lru_cache(maxsize=1)
def engine_build() -> str:
    """This engine's build, stamped as ``# espalier-build:`` under the version
    (DEF-1104): a pre-release string does not move between merges, so two
    builds shared one stamp, and an older build's rewrite of a newer one's
    tree read as repairing drift. Twelve hex digits of :func:`_surface_digest`
    over ``cli._deploy_sources``, the files the writing verbs copy, so two
    installs that deploy the same bytes are one build (neither can roll the
    other back) and a file nothing deploys moves nothing. The digest alone is
    stamped: install provenance, a commit included, would make one set of
    bytes read as drift between two machines. Read once a process."""
    from espalier.cli import _deploy_sources  # lazy: cli imports this module

    return _surface_digest(_deploy_sources())[:12]


def render_pack_manifest(repo_root: Path) -> str:
    """Render cc/PACK_MANIFEST.txt listing the files ``espalier init`` manages in this repository.

    Sources from ``espalier.managed_inventory.get_managed_public_files`` so the
    manifest cannot drift from init/cleanup/doctor's view of the managed
    surface. Local-only files (settings.local.json, cc/SURFACE_HANDOFF.md,
    cc/execution_plan.json, reports/*) and local runtime artifacts
    (settings.json, integrity.json) are excluded by construction.
    """
    from espalier.managed_inventory import get_managed_public_files
    entries = get_managed_public_files(repo_root)
    # Root-level scaffold docs (CLAUDE.md, ESPALIER_MEMORY.md, the seeded docs/*)
    # are sourced from get_managed_public_files — the renderer is a thin consumer
    # of the inventory, no longer a second SoT for the list. README.md is not
    # among them: init never writes an adopter's README (DEF-556).
    unique = sorted(set(entries))
    lines = [
        f"# {MANAGED_MARKER}",
        "# Operator-facing manifest of the files `espalier init` manages in this repository.",
        "# The authoritative ownership inventory lives in espalier.managed_inventory.",
        # Stamp the deploying engine version so `espalier upgrade` can detect a
        # stale committed harness. Re-rendered on every deploy/upgrade; read by
        # cli._read_deployed_version. NOT a numeric-SoT contract — it tracks
        # __version__ by construction (f-string ref, no literal).
        f"# espalier-version: {__version__}",
    ]
    if not surface_contract.is_self_host_repo(repo_root):
        # The build beside the version (DEF-1104), read by
        # cli._read_deployed_build. Not here on the self-host tree: its
        # committed manifest is pinned to this render
        # (tests/test_manifest_truth.py) and its deploy source is its own
        # tools/cc/, so a build line would be one tracked line every lane
        # touching tools/cc/ recomputes.
        lines.append(f"# espalier-build: {engine_build()}")
    lines.extend(unique)
    return "\n".join(lines) + "\n"


# The three required cc/ docs and the renderer each regenerates from, in the
# order init writes and reports them. ``write_required_surface`` classifies
# through this registry; the contract that pins ``PLAN_READERS`` derives its
# own answer from the same renderers' source.
REQUIRED_SURFACE_RENDERERS: dict[str, Callable[[Path], str]] = {
    "cc/LIVE_SURFACE.md": render_live_surface,
    "cc/COMMANDS.md": render_commands_doc,
    "cc/PACK_MANIFEST.txt": render_pack_manifest,
}

# The required docs whose render READS the saved plan (``_load_stable_actions``
# over ``reports/harness_config.json``). Every writer of the plan re-renders
# exactly these afterwards, or the next ``upgrade`` names them as drift on a
# change the writer itself made (DEF-806: a non-Python host's post-overlay
# plan gains ``scan``, and the docs init rendered from the host-only plan
# never learned it; the same class at ``fingerprint``, ``install-ci`` and
# ``upgrade --execute``). ``cc/PACK_MANIFEST.txt`` is not one: it renders
# from the managed inventory and carries the version stamp ``upgrade``
# compares, so a plan re-baseline leaves it alone. A hand-kept pair, pinned
# by a contract that derives the set from the renderers themselves.
PLAN_READERS: tuple[str, ...] = ("cc/LIVE_SURFACE.md", "cc/COMMANDS.md")


def write_required_surface(
    repo_root: Path,
    *,
    dry_run: bool = False,
    targets: Iterable[str] | None = None,
    existing_only: bool = False,
) -> list[tuple[str, str]]:
    """Write the three required cc/ docs with marker-aware semantics.

    Returns a list of ``(rel_path, action)`` tuples — one entry per
    target, regardless of whether the file was written. Actions:

    - ``"created"``           — target did not exist; rendered fresh
    - ``"updated_managed"``   — target existed + marker + drift; regenerated
    - ``"skipped_no_drift"``  — target existed + marker + byte-identical render;
                                left untouched (no mtime churn)
    - ``"skipped_user_file"`` — target existed without the marker, or could not
                                be decoded as UTF-8; preserved untouched

    The renderers always emit the marker themselves (see ``render_live_surface``
    et al.), so a freshly-rendered file passes ``has_managed_marker`` on the
    next init and is treated as managed.

    ``dry_run=True`` returns the same actions from the same compare without
    writing (no directory is created either): ``upgrade``'s preview reads
    the cc/ surface through this one classifier (DEF-726). The compare is
    the same; the TREE is not: these three docs render from disk, and the
    deploy calls this after its asset writes have landed while the preview
    calls it before them, so a preview can name a doc the deploy then finds
    unchanged, or miss one the deploy rewrites. Both converge in one
    ``--execute``; ``preview_managed_surface`` states the caveat (DEF-757).

    ``targets`` narrows the pass to a subset of the required docs, in
    registry order (``None`` is all three; a name outside the registry raises
    ``ValueError``, so a misspelt target cannot classify nothing and read as
    clean). ``existing_only=True`` leaves a target that is absent from the
    tree out of the returned list instead of creating it -- the plan
    re-baseline's mode (``cli._refresh_fingerprint_derivatives``), where
    first-time creation belongs to ``init``.
    """
    from espalier.managed_markers import has_managed_marker

    if targets is None:
        chosen = REQUIRED_SURFACE_RENDERERS
    else:
        wanted = set(targets)
        unknown = sorted(wanted - REQUIRED_SURFACE_RENDERERS.keys())
        if unknown:
            raise ValueError(f"not a required surface doc: {unknown}")
        chosen = {rel: fn for rel, fn in REQUIRED_SURFACE_RENDERERS.items() if rel in wanted}
    actions: list[tuple[str, str]] = []
    for rel, renderer in chosen.items():
        path = repo_root / rel
        if not path.exists():
            if existing_only:
                continue
            if not dry_run:
                atomic_write_text(path, renderer(repo_root))
            actions.append((rel, "created"))
            continue
        try:
            actual = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A pre-existing managed doc we cannot read as UTF-8 is not one we
            # can prove is ours -- preserve it rather than abort `espalier init`.
            # Mirrors the _deploy_managed_py / _deploy_asset_md dest-read guard.
            # (UnicodeDecodeError is a ValueError, not an OSError, so an
            # `except OSError`-only guard would miss it and still crash.)
            actions.append((rel, "skipped_user_file"))
            continue
        if not has_managed_marker(actual):
            actions.append((rel, "skipped_user_file"))
            continue
        rendered = renderer(repo_root)
        # A byte-identical render must NOT rewrite the file -- an unconditional
        # write churns the mtime and reports "updated_managed" on a no-op
        # re-init. Parity with _deploy_managed_py / _deploy_asset_md.
        if actual == rendered:
            actions.append((rel, "skipped_no_drift"))
            continue
        if not dry_run:
            atomic_write_text(path, rendered)
        actions.append((rel, "updated_managed"))
    return actions
