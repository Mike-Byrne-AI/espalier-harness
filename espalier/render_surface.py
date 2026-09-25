"""Render operator-facing surface docs from the discovered surface.

Produces `cc/LIVE_SURFACE.md`, `cc/COMMANDS.md`, and `cc/PACK_MANIFEST.txt`
from `surface_contract.discover_self_host_surface(repo_root)` so the
content tracks disk reality instead of drifting from hand-edited
templates.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path

from espalier import __version__  # deploy-time version stamp
from espalier import surface_contract
from espalier._atomic_io import atomic_write_text
from espalier.harness_config import CANONICAL_HOOK_WIRING
from espalier.managed_markers import MANAGED_MARKER

# The core-loop commands surfaced in the SessionStart banner's "Commands:" line.
# SINGLE SOURCE OF TRUTH for "core" -- render_commands_doc emits these into
# cc/COMMANDS.md's `## Core flow` section, which the banner's _commands_footer
# reads. Replaces the former hardcoded tuple in session_start.py (which could
# not see a newly-added core command). Order is the getting-started loop order.
# sister-site: ok SoT for the core-flow command list; session_start._CORE_FLOW_COMMANDS is a crash-fallback copy of this
CORE_FLOW_COMMANDS = (
    "/status", "/implement-task", "/smoke", "/preflight", "/commit", "/handoff",
)


def _agent_name(path: str) -> str:
    return Path(path).stem


def _command_name(path: str) -> str:
    return Path(path).stem


def _skill_name(path: str) -> str:
    # The path ends in ".../<name>/SKILL.md", so .stem would return the literal
    # "SKILL"; the skill's name is the parent directory.
    return Path(path).parent.name


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

    Commands typically open with a short paragraph as their summary
    rather than carrying a YAML ``description:`` field. This fallback
    surfaces those summaries instead of emitting ``—`` for every such
    command.

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
    files that document their purpose in plain prose (the dominant shape
    for ``.claude/commands/*.md``) are not rendered as ``—``.
    """
    desc = _read_frontmatter_description(path)
    if desc:
        return desc
    return _read_body_description(path)


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
    hooks = surface.get("hooks", [])
    stable_actions = _load_stable_actions(repo_root)

    lines = [
        f"<!-- {MANAGED_MARKER} -->",
        "# Live Surface",
        "",
        "Canonical index for the Espalier-Harness governance harness. Rendered from the",
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
            "CI is the merge-time guarantee. SessionStart cannot block Claude "
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
        name = _agent_name(agent_path)
        desc = _read_description(repo_root / agent_path)
        if desc:
            lines.append(f"- `{name}` -- {desc}")
        else:
            lines.append(f"- `{name}`")

    lines.append("")
    lines.append(f"## Commands ({len(commands)} commands)")
    for cmd_path in commands:
        name = _command_name(cmd_path)
        desc = _read_description(repo_root / cmd_path)
        if desc:
            lines.append(f"- `/{name}` -- {desc}")
        else:
            lines.append(f"- `/{name}`")

    lines.append("")
    lines.append(f"## Skills ({len(skills)} skills)")
    for skill_path in skills:
        name = _skill_name(skill_path)
        desc = _read_description(repo_root / skill_path)
        if desc:
            lines.append(f"- `/{name}` -- {desc}")
        else:
            lines.append(f"- `/{name}`")

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


def render_pack_manifest(repo_root: Path) -> str:
    """Render cc/PACK_MANIFEST.txt listing shipped self-host surface files.

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
        "# Operator-facing manifest for shipped self-host surface files.",
        "# The authoritative ownership inventory lives in espalier.managed_inventory.",
        # Stamp the deploying engine version so `espalier upgrade` can detect a
        # stale committed harness. Re-rendered on every deploy/upgrade; read by
        # cli._read_deployed_version. NOT a numeric-SoT contract — it tracks
        # __version__ by construction (f-string ref, no literal).
        f"# espalier-version: {__version__}",
    ]
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
