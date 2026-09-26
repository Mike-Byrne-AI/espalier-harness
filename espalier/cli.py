"""Espalier-Harness CLI — governance harness for Claude Code repositories."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import copy
import json
import re
import shlex
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from dataclasses import dataclass, field
from importlib.resources import as_file
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO, TYPE_CHECKING, NamedTuple, NoReturn


from espalier import __version__
from espalier._atomic_io import atomic_write_bytes, atomic_write_text
from espalier._integrity_bridge import load_integrity_module
from espalier._python_floor import (
    floor_text,
    interpreter_meets_floor,
    is_below_floor_python3,
    meets_python_floor,
)
from espalier._safe_walk import safe_rglob, is_own_git_repo as _is_own_git_repo
from espalier._text import os_error_text, plural, quoted_if_spaced
from espalier._venv import (
    after_head_index,
    interpreter_site_token,
    interpreter_token,
    is_statusline_shim_head,
    path_without,
)
from espalier.analyze import fingerprint_repo
from espalier.assets import (
    AssetNotFound,
    claude_assets_root,
    github_workflow_asset,
)
from espalier.managed_markers import (
    SEED_STAMP_RE,
    JSON_SENTINEL_KEY,
    apply_marker_to_md,
    has_managed_marker,
)
from espalier.managed_inventory import (
    get_local_runtime_prefixes,
    is_render_artifact,
    settings_backup_rung,
)
from espalier.managed_paths import (
    DEPLOYED_SCRIPT_SUFFIXES,
    STANDARD_MANAGED_TOOLS,
    STATUSLINE_SCRIPT,
    STATUSLINE_SHIM,
)
from espalier.cleanup import clean_generated_surface
from espalier.config import load_config
from espalier.cognitive_blueprint import (
    add_reasoning, auto_continuation_fragments, list_blueprint_chain,
    load_latest_blueprint, record_reflect_pass, render_blueprint_md,
    render_context_load, save_blueprint, set_continuation_fragments,
    start_session,
)
from espalier.diffing import diff_repo
from espalier.doctor import run_doctor_check
from espalier.harness_config import build_harness_config
from espalier.handoff import build_surface_handoff, write_surface_handoff
from espalier.pre_release import run_pre_release_check
from espalier.models import BuildPlan, RepoFingerprint  # hoisted from runtime-local imports to satisfy `typing.get_type_hints()` on `_build_claude_md` / `_build_memory_md`.
from espalier.proofs import run_cc_surface_gate
from espalier.recovery import assess_repo_state
from espalier.reflect_protocol import run_reflect_pass, render_reflect_pass
from espalier.reflection import reflect_repo
from espalier import doctor as _doctor
from espalier import surface_contract
from espalier.release_pack import create_release_zip
from espalier import pack_manifest as _pack_manifest
from espalier.render_surface import (
    PLAN_READERS,
    write_required_surface,
    _block_scalar_body_continues,
    _is_block_scalar_header,
    _normalize_description_text,
    _unquote_frontmatter_value,
)
from espalier.self_hosting import gate_failure_reason, run_self_host_check
from espalier.worktree import build_worktree_plan, render_worktree_plan

from espalier.harness_config import CANONICAL_HOOK_WIRING  # noqa: E402
from espalier.harness_config import unwired_governance_gates  # noqa: E402
from espalier.harness_config import (  # noqa: E402
    GATE_ABSENT,
    GATE_EVENT_OF,
    GATE_INERT,
    GATE_LEGACY_FORM,
    GATE_MISWIRED,
    blob_names_script,
    GATE_ORPHANED,
    GATE_SHAPES,
    GATE_VOIDED_SETTINGS,
    classify_unwired_gate,
    group_unwired_gates_by_shape,
    group_unwired_reporters_by_shape,
    miswiring_detail,
    unwired_reporter_hooks,
)

# Single source of truth for the committed project-memory filename — routed
# through one constant so a future rename is a value flip, not scattered edits.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"
# The pre-rename name (still Claude Code's hardcoded auto-memory filename). Used
# only to detect a repo initialized before the rename and nudge a migration —
# never as the committed-memory target. Named to sidestep the line-anchored
# `_MEMORY_FILENAME` agreement guard (tests/test_memory_filename_constant.py).
_LEGACY_MEMORY_FILENAME = "MEMORY.md"

if TYPE_CHECKING:
    from collections.abc import Iterable

    from espalier.pack_manifest import PackManifest


# Leading `| YYYY-MM-DD` ESPALIER_MEMORY.md row-date prefix. Module-level (hoisted from a
# former function-local compile) so it can be pinned equal to the hook-side twin
# session_start._MEMORY_DATE_RE — tests/test_forced_copy_parity.py.
_MEMORY_DATE_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})")


def _load_config(repo_root: Path, args: argparse.Namespace):
    config = load_config(repo_root, Path(args.config).resolve()) if getattr(args, "config", None) else load_config(repo_root)
    return config


# ── Init deployment ──────────────────────────────────────────────────

# Paths relative to repo root that init deploys
# sister-site: ok purpose-scoped: init DEPLOY list, not the integrity-hash set (_integrity.MANIFEST_FILES)
INIT_HOOK_SCRIPTS = [
    "tools/cc/hooks/session_start.py",
    "tools/cc/hooks/task_router.py",
    "tools/cc/hooks/plan_guard.py",
    "tools/cc/hooks/write_guard.py",
    "tools/cc/hooks/config_guard.py",
    "tools/cc/hooks/post_write_check.py",
    "tools/cc/hooks/reflect_trigger.py",
    "tools/cc/hooks/stop_gate.py",
    "tools/cc/hooks/subagent_stop.py",
    "tools/cc/hooks/post_compact.py",
    "tools/cc/hooks/subagent_start.py",
    "tools/cc/hooks/context_reinject_failure.py",
    # Helper modules imported by the hook entry scripts above.
    # Must be deployed alongside entry hooks or any hook that imports them
    # will raise ModuleNotFoundError on first use in a fresh target repo.
    "tools/cc/hooks/_hook_utils.py",
    "tools/cc/hooks/_integrity.py",
    "tools/cc/hooks/_hook_contract.py",
    "tools/cc/hooks/_maintenance_mode.py",
    # SHA pin mirror imported by _hook_utils.is_self_host_repo via the 5th
    # signal. Without this file the hook-side detector falls back to returning
    # False (safer default — treat as user repo), but parity with the
    # library-side detector is lost.
    "tools/cc/hooks/_self_host_fingerprint.py",
    # Shared denial-reason templates. Imported by write_guard, plan_guard,
    # config_guard, stop_gate via sys.path.insert + bare imports; missing this
    # file would raise ModuleNotFoundError on any deny()/block() path.
    "tools/cc/hooks/_denial_reasons.py",
    # Both modules are imported by write_guard.py via sys.path.insert + bare
    # imports; missing either one raises ModuleNotFoundError on the very first
    # PreToolUse fire.
    "tools/cc/hooks/_bash_patterns.py",
    "tools/cc/hooks/_protected_zones.py",
    # The speed-bump mechanism, imported by write_guard. Must deploy alongside
    # the entry hooks or write_guard's `import _speedbump` raises
    # ModuleNotFoundError on the first PreToolUse fire in a fresh target repo.
    "tools/cc/hooks/_speedbump.py",
    # The recall-engine reinjection registry, imported by session_start,
    # write_guard, post_write_check, context_reinject_failure. Same deploy
    # requirement -- omit it and those hooks' `import _reinject` raises
    # ModuleNotFoundError on first fire in a fresh target repo.
    "tools/cc/hooks/_reinject.py",
    # The pull-recall engine. Not imported by a wired hook, but the /recall
    # command subprocesses it (and it imports _reinject for EXEMPLAR_MAP) --
    # omit it and /recall raises ModuleNotFoundError in a fresh target repo.
    "tools/cc/hooks/_recall.py",
    # The born-weak co-occurrence observer, imported by post_write_check
    # (extracted from it) -- fresh-init ModuleNotFoundError if undeployed.
    "tools/cc/hooks/_born_weak.py",
    # The /status --explain resolver. Not imported by a wired hook, but
    # session_resume.py subprocesses/imports it (and it imports _protected_zones,
    # plan_guard, _hook_utils, _maintenance_mode) -- omit it and /status --explain
    # raises ModuleNotFoundError in a fresh target repo.
    "tools/cc/hooks/_explain_path.py",
]

# Non-hook tool scripts init deploys. Derived from the single owner
# ``espalier.managed_paths.STANDARD_MANAGED_TOOLS`` so init deployment and the
# managed inventory agree by construction (the per-script rationale lives at the
# SoT). ``list(...)`` copies so callers that concatenate cannot mutate the SoT.
INIT_TOOL_SCRIPTS = list(STANDARD_MANAGED_TOOLS)


_WIRED_PATH_END_RE = re.compile(r"[\"'\s]")
"""Terminates a hook script path lifted out of a settings.json command string.
The bare-interpreter form stores the path alone in ``args``; the legacy
pre-v0.6.5 shell form embeds it in a quoted ``command``. Splitting on the first
quote-or-space handles both without the caller knowing which it has."""


_SEED_STAMP_RE = SEED_STAMP_RE
"""First-line provenance stamp for an init-seeded doc. The token is
``espalier:seed-version`` -- deliberately NOT ``espalier:managed`` -- so
``has_managed_marker`` / ``cleanup._file_is_managed`` still treat the doc as
operator-owned (``clean-generated`` never deletes it). The captured sha256 is
the digest of every byte BELOW the stamp line. Alias of the single owner in
``managed_markers`` -- ``analyze`` and ``doctor`` read the same regex, and the
line it reads back is written by ``managed_inventory.seed_stamp_line`` (the
renderer moved there beside ``render_seed_body`` on 2026-09-05 so ``doctor``
can print the stamp itself, DEF-696)."""


def _seed_redeploy_decision(dest_path: Path, rendered: str) -> str:
    """Return ``"refresh"`` or ``"preserve"`` for an existing seed doc.

    ``"refresh"`` only when the on-disk copy still carries our stamp AND its
    post-stamp bytes hash to the recorded digest (operator untouched) AND the
    freshly-``rendered`` content differs. Everything else preserves: an operator
    edit (hash mismatch), a byte-identical copy (no churn), or a legacy
    *unstamped* copy we cannot prove untouched.
    """
    try:
        existing = dest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "preserve"
    m = _SEED_STAMP_RE.match(existing)
    if m is None:
        return "preserve"  # unstamped legacy copy -- safe fallback
    recorded = m.group(1)
    on_disk_rest = existing[m.end():]
    if hashlib.sha256(on_disk_rest.encode("utf-8")).hexdigest() != recorded:
        return "preserve"  # operator edited since we wrote it
    if hashlib.sha256(rendered.encode("utf-8")).hexdigest() == recorded:
        return "preserve"  # packaged content unchanged
    return "refresh"


def _write_seed(
    dest_path: Path, rendered: str, *, label: str, overwrite: bool = False,
    dry_run: bool = False,
) -> bool:
    """Write a seed doc's ``rendered`` body (``managed_inventory.render_seed_body``)
    under its seed-version stamp, or leave the existing copy alone.

    On a re-deploy over an existing copy the stamp lets us refresh an
    operator-untouched-but-stale seed doc (``_seed_redeploy_decision`` returns
    ``"refresh"``) while preserving an operator-edited or legacy-unstamped
    copy. The stamp is ``managed_inventory.seed_stamp_line`` over exactly the
    bytes written below it -- the same function ``doctor`` prints for a seed
    whose first line is gone (DEF-696), so the printed line and the written
    line cannot differ. Until 2026-09-05 this was the non-``.py`` branch of a
    path-based ``_deploy_file`` that also rendered the body (adapt header +
    source text) itself; the rendering now has one home and this helper only
    writes. The ``.py`` deploys never came through here in production
    (``_deploy_managed_py`` owns them).

    ``label`` is what the stderr lines call the file: the caller's
    root-relative path, never this helper's guess -- required, with no
    default, because the basename was the only spelling until 2026-09-12
    and two seeds print as ``README.md`` (DEF-774); a caller that forgets
    it fails at the call, not on the adopter's terminal. ``dry_run`` answers
    the same question without writing or printing, so ``upgrade``'s preview
    and its ``--execute`` read one decision; it reads the decision, not the
    disk's willingness, so a preview can promise a create that a read-only
    parent then refuses -- the write's own error names that.

    Returns True if deployed (or refreshed) -- on a dry run, if it would be;
    False if skipped.
    """
    from espalier.managed_inventory import seed_stamp_line

    shown = label
    if dest_path.exists() and not overwrite:
        if _seed_redeploy_decision(dest_path, rendered) == "refresh":
            if dry_run:
                return True
            atomic_write_text(dest_path, seed_stamp_line(rendered) + rendered)
            print(f"  refresh (seed drift): {shown}", file=sys.stderr)
            return True
        if not dry_run:
            print(f"  skip (exists): {shown}", file=sys.stderr)
        return False
    if dry_run:
        return True
    # Fresh create, or an explicit overwrite=True: a deliberate, unconditional
    # write that bypasses the untouched-check above (overwrite=True is "force",
    # not preservation). No production caller passes overwrite=True for a seed
    # doc today; test_overwrite_true_clobbers_non_py_seed pins the intent so a
    # future --force reseed can't mistake it for edit-preserving.
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(dest_path, seed_stamp_line(rendered) + rendered)
    return True


def _deploy_managed_py(
    source_path: Path, dest_path: Path, *, dry_run: bool = False,
) -> str:
    """Deploy a managed script -- a ``.py``, or the ``.cmd`` statusline shim
    (DEF-729) -- with drift detection.

    Returns one of:

    - ``"created"``           — target absent; rendered fresh with the marker.
    - ``"updated_managed"``   — target present + marker + drift; regenerated.
    - ``"skipped_no_drift"``  — target present, content matches what we would
       have written. The most common rerun outcome; not noisy.
    - ``"skipped_user_file"`` — target present + drift + no marker; user edit
       is preserved. Caller emits the operator-facing warning.
    - ``"skipped_source_missing"`` — packaged source absent (defensive).

    Compares the expected deploy output (source + injected marker) against
    what's on disk; managed copies regenerate, hand-patched copies are
    preserved. This keeps a repo upgraded across versions from silently
    keeping stale hook scripts when the canonical source has changed.

    ``dry_run=True`` classifies without writing: the same five answers from
    the same compare, with the two writing arms (``created`` and
    ``updated_managed``) reporting what a write WOULD do. ``upgrade``'s
    preview reads the copied surface through this one classifier
    (``preview_managed_surface``), so the preview and the deploy classify a
    COPIED file identically (DEF-726); the three rendered cc/ docs are the
    declared exception, see ``preview_managed_surface``.

    The compare is ``str == str`` after ``read_text``, whose universal-newline
    translation is what makes a CRLF working copy of an LF source read as
    ``skipped_no_drift``. That is load-bearing for a Windows checkout under
    ``core.autocrlf`` (DEF-725 is the manifest's separate answer): a byte
    compare here would turn every such tree into ~70 files of permanent
    ``updated_managed`` drift that ``--execute`` rewrites and git re-converts.
    Pinned by the CRLF-copy test in ``tests/test_cli_deploy.py``.
    """
    from espalier.managed_markers import (  # `has_managed_marker` available from module-top import
        apply_marker_to_batch,
        apply_marker_to_text,
    )
    if not source_path.is_file():
        return "skipped_source_missing"
    source_text = source_path.read_text(encoding="utf-8")
    # Exact suffix: the deploy sources are ours and spelled lowercase, and
    # every other enumerator of the set (the mirror row, the sync, the wheel
    # globs, the orphan scan) reads the exact spelling too.
    if source_path.suffix == ".cmd":
        # The batch marker sits after `@echo off`: a `#` line is a command
        # to cmd.exe, and a line before the echo-off is echoed to stdout --
        # the statusline's own channel.
        expected = apply_marker_to_batch(source_text)
    else:
        expected = apply_marker_to_text(source_text)
    if not dest_path.exists():
        if not dry_run:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(dest_path, expected)
        return "created"
    try:
        actual = dest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "skipped_user_file"
    if actual == expected:
        return "skipped_no_drift"
    if has_managed_marker(actual):
        if not dry_run:
            atomic_write_text(dest_path, expected)
        return "updated_managed"
    return "skipped_user_file"


def _deploy_asset_md(
    source_path: Path, dest_path: Path, *, dry_run: bool = False,
) -> str:
    """Deploy a managed markdown asset with four-state semantics.

    assets/claude/{agents,commands,skills}/<file>.md ships via
    ``deploy_harness`` with marker-aware regeneration. Unlike
    ``_write_seed`` (stamp-driven refresh/preserve), this honors the
    ``espalier:managed`` marker so user-edited copies are preserved.

    ``skipped_no_drift`` gives parity with ``_deploy_managed_py``: the
    no-drift early return means an idempotent rerun on an unchanged repo
    reports ``skipped_no_drift`` for every asset that already matches the
    packaged copy, rather than rewriting it and surfacing it as "updated"
    drift in the init report.

    Returns one of:
    - ``"created"`` — target absent; rendered with marker injected.
    - ``"updated_managed"`` — target present + marker + drift → regenerated.
    - ``"skipped_no_drift"`` — target present, content already matches.
    - ``"skipped_user_file"`` — target present without marker; preserved.
    - ``"skipped_source_missing"`` — source absent (defensive).

    ``dry_run=True`` classifies without writing, as ``_deploy_managed_py``.
    """
    # apply_marker_to_md and has_managed_marker are both at module-top.
    if not source_path.is_file():
        return "skipped_source_missing"
    body = source_path.read_text(encoding="utf-8")
    rendered = apply_marker_to_md(body)
    if not dest_path.exists():
        if not dry_run:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(dest_path, rendered)
        return "created"
    try:
        existing = dest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "skipped_user_file"
    if existing == rendered:
        return "skipped_no_drift"
    if has_managed_marker(existing):
        if not dry_run:
            atomic_write_text(dest_path, rendered)
        return "updated_managed"
    return "skipped_user_file"


def _packaged_md_assets(harness_root: Path) -> list[tuple[str, Path]]:
    """``(rel, source_path)`` for every packaged agent, command and skill body.

    The ``.md`` half of the deploy set (the ``.py`` half is
    ``INIT_HOOK_SCRIPTS`` + ``INIT_TOOL_SCRIPTS``), enumerated from the
    packaged sources under ``espalier/assets/claude/`` per the BC-030/031
    iteration invariant. One owner for ``deploy_harness`` (which writes it)
    and ``preview_managed_surface`` (which classifies it without writing),
    so the preview cannot enumerate a different set from the deploy.
    """
    asset_root = harness_root / "espalier" / "assets" / "claude"
    layout = [
        ("agents", asset_root / "agents", lambda d: sorted(d.glob("*.md"))),
        ("commands", asset_root / "commands", lambda d: sorted(d.glob("*.md"))),
        ("skills", asset_root / "skills",
         lambda d: sorted(p for p in d.rglob("SKILL.md"))),  # espalier:safe-walk-ok deploy-source skills (espalier package data, never an adopter tree)
    ]
    out: list[tuple[str, Path]] = []
    for kind, src_dir, src_iter in layout:
        if not src_dir.is_dir():
            continue
        for src in src_iter(src_dir):
            out.append((".claude/" + kind + "/" + src.relative_to(src_dir).as_posix(), src))
    return out


def _espalier_root() -> Path:
    """Return Espalier-Harness's own install root — the dir CONTAINING ``espalier/``.

    Editable/source install: the repo root (sibling of both ``espalier/`` and
    ``tools/``). Wheel install: ``site-packages/`` (``espalier/`` lives there;
    ``tools/`` no longer ships — the wheel does not ship a bare top-level
    ``tools`` package, which would squat that generic import name).

    Callers needing the ``tools/cc/`` deploy SOURCE must use
    :func:`_deploy_source_path` (the wheel reads it from ``espalier/_vendor/cc/``);
    callers needing packaged assets join ``espalier/assets/`` onto this root,
    which is present in both install forms.
    """
    return Path(__file__).resolve().parent.parent


def _stream_isatty(stream: object | None) -> bool:
    """True only when ``stream`` is a real TTY. Returns False when the stream is
    None (closed fd ``0<&-`` / pythonw / embedded interpreter), lacks ``isatty``,
    OR whose ``isatty()`` raises — a *closed* (non-None) file object raises
    ``ValueError`` — so an interactive gate degrades to the non-interactive
    default instead of propagating (``AttributeError`` on ``None.isatty()`` or
    ``ValueError`` on a closed stream)."""
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        return False


def _resolve_repo_arg(raw: str) -> Path | None:
    """Resolve a repo-path CLI arg. Print the standard error and return None
    if it is not an existing directory, or if its ``.claude`` is a directory
    this process cannot search or list; callers translate None -> exit code 2.

    The ``.claude`` question is asked HERE, once, for every command that
    resolves a repo argument: asked later, site by site, the same tree read as
    "absent" on CPython 3.14 and raised out of the first ``Path.exists()`` on
    3.10-3.13 (DEF-763). ``init``, ``upgrade`` and ``fuse`` resolve their own
    argument and ask through ``_refuse_unreadable_harness_root``.
    """
    repo_root = Path(raw).resolve()
    if not repo_root.is_dir():
        print(
            f"error: repo path does not exist or is not a directory: {raw}",
            file=sys.stderr,
        )
        return None
    unreadable = surface_contract.unreadable_harness_root(repo_root)
    if unreadable is not None:
        print(
            f"error: {surface_contract.unreadable_root_sentence(unreadable)}",
            file=sys.stderr,
        )
        return None
    return repo_root


def _deploy_source_path(rel_path: str) -> Path:
    """Resolve the deploy SOURCE for a ``tools/cc/``-rooted ``rel_path``.

    The deploy DEST stays ``tools/cc/...`` in the adopter repo (the
    adopter-facing layout is unchanged). Only the SOURCE differs by install form:

    * editable/source: ``tools/cc/`` is a sibling of ``espalier/``.
    * wheel: the script ships as package-data under ``espalier/_vendor/cc/``
      (``tools/cc`` is no longer a top-level package in the wheel).

    Maps ``tools/cc/<rest>`` → ``espalier/_vendor/cc/<rest>`` on the wheel branch.
    """
    here = Path(__file__).resolve().parent  # espalier/
    src_tree = here.parent / rel_path  # repo_root / tools/cc/...  (editable)
    if src_tree.exists():
        return src_tree
    # Wheel: strip the leading "tools/" segment, re-root under espalier/_vendor/.
    rest = rel_path.split("/", 1)[1] if "/" in rel_path else rel_path
    return here / "_vendor" / rest


_SETTINGS_SCHEMA_URL = "https://json.schemastore.org/claude-code-settings.json"

# Matcher strings live in harness_config.CANONICAL_HOOK_WIRING. CHW declares
# matcher="*" for write_guard (kill-switch reach + defense in depth via
# write_guard's internal MUTATION_TOOLS filter) and matcher="Write|Edit|NotebookEdit" for plan_guard
# (narrowed to the tools plan_guard actually gates, so Bash/MCP tool calls
# don't fork it and the false-positive denials are removed). plan_guard
# retains its internal MUTATION_TOOLS filter as defense-in-depth if a future
# operator re-widens the matcher.
#
# PostToolUse stays narrow for perf — post_write_check's matcher is tracked in
# CHW as the canonical string. reflect_trigger keeps matcher="*" because its
# every-Nth-call cadence must observe every tool.
def _matcher_for(script_name: str) -> str:
    """Resolve the Claude Code matcher string from CHW for a hook script."""
    from espalier.harness_config import CANONICAL_HOOK_WIRING
    return CANONICAL_HOOK_WIRING[script_name]["matcher"]


def _timeout_for(script_name: str) -> int:
    """Resolve the hook timeout (seconds) from CHW for a hook script.

    ``CANONICAL_HOOK_WIRING`` is the timeout SoT — ``_build_settings_json``
    derives every hook's timeout from it, so no hook carries an inline literal
    that could silently drift from CHW.
    """
    from espalier.harness_config import CANONICAL_HOOK_WIRING
    return CANONICAL_HOOK_WIRING[script_name]["timeout"]


def _resolves_only_inside_a_virtualenv(name: str, resolved: str) -> bool:
    """True when ``name`` resolves to a virtualenv shim and to nothing else.

    ``settings.json`` outlives the shell that ran ``init``; a venv shim does
    not. An activated venv puts its own ``bin/`` first on PATH and that
    directory holds BOTH a ``python`` and a ``python3`` shim regardless of
    which name created it — so the plain ``shutil.which`` probe cannot tell a
    host-wide interpreter from one that disappears at ``deactivate``.

    The question is asked of the CANDIDATE, not of the running interpreter.
    ``init`` is frequently executed by a python that is NOT in the venv first
    on PATH (pipx, a global install, a different venv), and ``sys.prefix``
    cannot see that.

    NEVER use ``Path(resolved).resolve()`` for containment: a POSIX venv's
    ``bin/python`` is a symlink chain out to the base install, so resolving the
    FILE lands outside the venv every time and the predicate is dead. Ask the
    candidate itself for its ``sys.prefix``/``sys.base_prefix`` instead.

    On any probe it cannot read this returns False — the PERMISSIVE direction:
    the candidate gets wired. That is deliberate. Rejecting on an unreadable
    probe can reject BOTH candidates and fall through to a name that does not
    exist on the host, which is a worse failure than the one this closes. The
    payload is a tagged JSON line rather than a line count so that a
    sitecustomize banner, a corporate ``.pth`` or a deprecation notice printed
    before it cannot silently disable the guard.
    """
    import subprocess
    try:
        probe = subprocess.run(
            [resolved, "-c", "import sys,json;"
             "print('ESPALIER_PROBE'+json.dumps([sys.prefix,sys.base_prefix]))"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        payload = None
        for line in (probe.stdout or "").splitlines():
            if line.startswith("ESPALIER_PROBE"):
                payload = json.loads(line[len("ESPALIER_PROBE"):])  # json-dict-safe: ok -- probe emits a 2-element LIST, guarded by the isinstance/len check below
                break
        if not isinstance(payload, list) or len(payload) != 2:
            return False
        cand_prefix = Path(payload[0]).resolve()
        cand_base = Path(payload[1]).resolve()
    except (subprocess.SubprocessError, OSError, ValueError):
        # ValueError covers json.JSONDecodeError (a subclass).
        return False
    if cand_prefix == cand_base:
        return False  # the candidate is not a venv shim
    return shutil.which(name, path=path_without(cand_prefix)) is None


#: The bare names `_detect_python_command` probes, in order: `python` first
#: (Windows + Linux distros that symlink), then `python3` (macOS Homebrew + most
#: modern Linux). ONE home, because the sentences that say "nothing on PATH
#: clears the floor" must name exactly what was probed -- "no interpreter on
#: PATH" overclaimed on a Windows host carrying `python3.12.exe` and `py -3`
#: (DEF-727 review), which is the error class `_python_floor` exists to stop.
RESOLVER_CANDIDATES: tuple[str, ...] = ("python", "python3")


def resolver_candidate_names() -> str:
    """``"'python' or 'python3'"`` -- the probed names, rendered for a sentence
    that scopes its claim to them."""
    return " or ".join(repr(name) for name in RESOLVER_CANDIDATES)


#: Set once the unvalidated-interpreter warning has been emitted in this
#: process. The resolver has 30 call sites and is NOT memoized -- `doctor`
#: alone calls it ten times -- so an unguarded warning would print ten
#: identical lines on exactly the broken host it exists to help. Tests reset
#: it via `cli._INTERPRETER_WARNING_EMITTED = False`.
_INTERPRETER_WARNING_EMITTED = False


def _warn_interpreter_below_floor(probe: "tuple[str, str, str]") -> None:
    """Say, once and loudly, that the wired interpreter is too OLD.

    Distinct from :func:`_warn_interpreter_unvalidated`, because the state and
    the remedy are different: there IS a working Python 3 here, the blocking
    guards WILL run, and what is dead is the blueprint chain, Gate 4 finalize
    and subagent-reasoning capture (``tools/cc/cognitive_blueprint.py`` is
    3.10+ ``match`` syntax). Telling this operator "no interpreter could be
    validated" sends them hunting for a missing install they already have.
    """
    global _INTERPRETER_WARNING_EMITTED
    if _INTERPRETER_WARNING_EMITTED:
        return
    _INTERPRETER_WARNING_EMITTED = True
    name, resolved, said = probe
    floor = floor_text()
    # `python -m espalier`, not a bare `espalier`: in a FUSION the engine is
    # vendored and the console script does not exist. And spelled with the
    # remedy answer, never `name` -- the candidate that just failed the floor
    # is the one interpreter this command cannot run under (DEF-805, the
    # residue of DEF-758). Re-entry is safe: the emitted flag above is set
    # before this print, so the resolver `_remedy_interpreter()` re-runs
    # returns here without printing again. Three states: the resolver's
    # answer clears the floor (not this branch), the interpreter running this
    # command does (spell it), or neither -- a fusion driven under a
    # below-floor interpreter -- in which case no interpreter can be spelled
    # yet and saying so beats spelling the broken one.
    remedy, _clears = _remedy_interpreter()
    if remedy == name:
        after = (
            "After upgrading, re-wire with the new interpreter: "
            "`<that interpreter> -m espalier init . --rewire-interpreter` "
            "(nothing on PATH, nor the interpreter running this command, "
            "clears the floor, so no command can be spelled yet)."
        )
    else:
        after = f"After upgrading, re-wire with `{remedy} -m espalier init . --rewire-interpreter`."
    print(
        f"WARNING: {name!r} ({resolved}) reports {said}, which is BELOW the "
        f"Python {floor} this package requires. Wiring it anyway so the "
        f"blocking guards keep working -- a name that does not resolve would "
        f"disarm them entirely. What will NOT work until you install Python "
        f"{floor} or newer: the blueprint chain, Gate 4 finalize, and "
        f"subagent-reasoning capture. SessionStart will say 'No active "
        f"blueprint' every session. " + after,
        file=sys.stderr,
    )


def _warn_interpreter_unvalidated(
    probe: "tuple[str, str, str] | None",
) -> None:
    """Say once, on stderr, that the returned interpreter name is a guess.

    Scoped deliberately to the case where NOTHING validated. It is not called
    when `_detect_python_command` falls back to a virtualenv-only candidate:
    that is a documented, deliberate fail-safe, and warning there would fire
    for every developer who runs `init` inside an activated venv -- an
    advisory that cries wolf gets ignored or deleted.
    """
    global _INTERPRETER_WARNING_EMITTED
    if _INTERPRETER_WARNING_EMITTED:
        return
    _INTERPRETER_WARNING_EMITTED = True
    floor = floor_text()
    below_floor = False
    if probe is not None:
        name, resolved, said = probe
        detail = f"{name!r} resolves to {resolved} but reported: {said}"
        # A host whose only interpreter is 3.9 is NOT "no Python 3" -- saying so
        # sends the operator hunting for a missing install when what they have
        # is a version too old. Name the real problem or the remedy is wrong.
        # And a Python 2 is NOT a too-old Python 3: the parse-succeeds gate that
        # stood here (the banner parsed, so it was called below-floor) admitted
        # it, at this site and at `_detect_python_command` (DEF-727). The pin
        # `tests/test_python_floor.py::test_the_two_python_2_admitting_predicates_are_narrowed_together`
        # greps this file for that gate's spelling, so it is not quoted here.
        below_floor = is_below_floor_python3(said)
    else:
        detail = "no interpreter answered to 'python' or 'python3'"
    headline = (
        f"no Python interpreter on PATH meets this package's floor of "
        f"{floor}+" if below_floor else
        f"no Python {floor}+ interpreter could be validated on PATH"
    )
    print(
        f"WARNING: {headline} -- "
        f"{detail}. Falling back to the literal name 'python', which may not "
        f"run. Hooks wired to a name that is not a working Python {floor}+ "
        f"exit outside the blocking range, so guards fail OPEN, and the "
        f"blueprint chain dies silently. Install Python {floor} or newer and "
        f"run this command again with it on PATH.",
        # ⚠ Deliberately does NOT say "re-run `espalier init .` to rewire":
        # `init` does not overwrite an existing `.claude/settings.json` (user
        # sovereignty), so on an already-initialised repo that is a no-op the
        # operator can follow forever -- DEF-620. The rewire remedy arrives
        # with `init --rewire-interpreter`; point at it from here once it does.
        file=sys.stderr,
    )


def _maintenance_mode_invocation(command: str) -> str:
    """Render the maintenance-mode invocation for THIS host's shell.

    A bare ``VAR=1 cmd`` env-prefix is POSIX-only. Pasted into PowerShell it is
    a syntax error, and the first install rehearsal on a real Windows host hit
    exactly that -- the engine printed a line the operator could not run.

    ONE function spells this, and `tests/test_portability_contract.py` asserts
    that no other operator-facing string does. That is the shape this repo
    prefers over N restatements: the dialect question gets answered once, and a
    reworded copy elsewhere reds instead of silently shipping POSIX syntax to a
    Windows operator.

    Note this is a command for the operator's OWN terminal. Maintenance mode is
    read at process launch, so a mid-session export cannot reach an
    already-running hook -- handing this to an in-session tool call would
    accomplish nothing even where it is permitted.
    """
    # `sys.platform`, not `os.name`: binding `os` in this module would be a real
    # change to its import surface, and three fixtures in
    # tests/test_check_pack_fences.py use "cli.py never binds os" as their
    # premise. `sys` is already imported here, and `sys.platform == "win32"` is
    # this repo's established spelling for the same question.
    if sys.platform == "win32":
        return (
            f'    PowerShell:      $env:ESPALIER_MAINTENANCE_MODE="1"; {command}\n'
            f"    cmd.exe:         set ESPALIER_MAINTENANCE_MODE=1 && {command}\n"
            f"    Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 {command}"
        )
    return f"    ESPALIER_MAINTENANCE_MODE=1 {command}"


def _detect_python_command() -> str:
    """Pick a Python 3 interpreter name resolvable on PATH on this host.

    Originally an init-time-only helper: it detected what was on PATH and
    wrote that into ``.claude/settings.json`` (which is per-machine and
    gitignored, so the detection result is locally correct without affecting
    other operators). That avoids every hook fire emitting ``Executable not
    found in $PATH: "python"`` when a hard-coded ``"python"`` has no symlink
    on the host.

    Writing settings.json is still its primary use but no longer its only
    one. The interpreter-hint work widened it into a general resolver: call
    sites across ``cli.py``, ``doctor.py`` and ``fuse.py`` now thread the
    return value into printed ``f"{py} -m espalier <verb>"`` remediation
    hints that never touch settings.json. Read the return value as "what to
    spell in a command the operator will type", not as "what init wrote".

    Probe ``--version`` after ``which`` and reject Python 2 candidates: on
    macOS with a stale ``python`` symlink pointing at Python 2, returning
    ``"python"`` would make hooks die with f-string syntax errors at first
    fire. The probe closes that day-one footgun.

    Order: ``python`` first (Windows + Linux distros that symlink),
    then ``python3`` (macOS Homebrew + most modern Linux distros). If
    neither resolves to Python 3, returns ``"python"`` and WARNS on stderr.

    That warning is load-bearing, and this docstring used to argue the
    opposite. It claimed the failure "surfaces at first hook fire with the
    same 'command not found' message", which is true only when nothing
    resolves at all. A name that RESOLVES but is not Python -- a Microsoft
    Store App Execution Alias, a stale Python-2 symlink, an unset pyenv shim
    -- produces no command-not-found: the hook spawns, exits outside the
    ``{0, 2}`` the hook protocol treats as a decision, and a non-decision is
    NON-BLOCKING. So every blocking guard fails OPEN while ``init`` reports
    success. That sentence is why nobody built this check.

    A candidate that resolves ONLY inside an activated virtualenv is
    rejected: the shim vanishes with the shell, but settings.json outlives
    it. See :func:`_resolves_only_inside_a_virtualenv`.
    """
    import subprocess
    last_resort = None
    # What the FIRST candidate that resolved-but-failed-identity actually said.
    # The loop's `path` / `result` are per-iteration locals, so without this the
    # warning below could name only the candidate, not the evidence. FIRST,
    # like the two siblings below, because the candidate order is deliberate:
    # this used to be assigned on every iteration, so on a Windows host whose
    # `python` was a Python 2 shim and whose `python3` was the Store alias the
    # warning quoted the alias's "Python was not found" and the Python 2
    # evidence was discarded -- the operator was told the wrong thing about
    # the wrong interpreter (DEF-804, driven on the walk 2026-09-14).
    first_probe: tuple[str, str, str] | None = None
    # A candidate whose probe itself raised (a broken shim: ENOEXEC, ENOENT
    # through a dead shebang) said nothing; keep the first such failure only
    # as the evidence of last resort, so a later candidate's real banner is
    # what the warning quotes (the "first INFORMATIVE probe" of DEF-804).
    first_failure: tuple[str, str, str] | None = None
    # A working Python 3 that is BELOW the floor -- preferred over the
    # literal 'python' fallback, because a name that does not resolve
    # disarms every guard while an old one merely disables blueprints.
    below_floor: tuple[str, str, str] | None = None
    for candidate in RESOLVER_CANDIDATES:
        path = shutil.which(candidate)
        if not path:
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True, encoding="utf-8",
                timeout=2,
            )
        except (subprocess.SubprocessError, OSError, ValueError) as exc:  # strict decode: a structured answer (DEF-821)
            if first_failure is None:
                first_failure = (candidate, path, f"probe failed: {type(exc).__name__}")
            continue
        version_str = (result.stdout or result.stderr).strip()
        # THE FLOOR, not merely "is it a Python 3" (DEF-636). `pyproject.toml`
        # says `requires-python = ">=3.10"`, and stock `/usr/bin/python3` on
        # macOS is 3.9.6 -- which passed the old `startswith("Python 3.")` test,
        # got written into 13 hook-command sites, and killed every consumer of
        # `tools/cc/cognitive_blueprint.py` (3.10+ `match` syntax) silently.
        if meets_python_floor(version_str):
            if _resolves_only_inside_a_virtualenv(candidate, path):
                # An ACTIVATED VIRTUALENV supplies a shim that vanishes with
                # the shell. settings.json outlives that shell -- Claude Code
                # is routinely launched from another terminal, an IDE, or the
                # desktop app -- so writing this name wires 13 sites to a
                # command that cannot be spawned, and every blocking guard
                # then fails OPEN.
                #
                # FIRST-rejected wins: overwriting here would make a tree with
                # a venv and no system interpreter return `python3` where the
                # pre-guard behaviour returned `python`, silently reversing
                # the deliberate python-first order documented above.
                if last_resort is None:
                    last_resort = candidate
                continue
            return candidate
        # A WORKING Python 3 that is merely too OLD is a third state, and
        # collapsing it into "nothing validated" made things WORSE than before
        # the floor existed (driven 2026-09-03, adversarial pass). On a stock
        # macOS -- python3 = 3.9.6, no `python` at all -- refusing 3.9 fell
        # through to the literal "python", which is command-not-found there, so
        # every hook exited outside {0, 2} and EVERY BLOCKING GUARD FAILED
        # OPEN. That trades "blueprints dead, enforcement intact" for
        # "enforcement dead", which is the worse half of the trade on the one
        # property this product is sold on. Operator decision, 2026-09-03: wire
        # it and warn loudly.
        #
        # A Python 2 banner PARSES too, and a gate that asked only whether
        # `parse_python_version` returned something admitted it here: on the
        # Windows walk 2 host `python` was a 2.7 shim, so this branch wired it
        # with the warning that promises working guards -- on the one
        # interpreter that cannot parse the hook scripts at all, so every guard
        # failed OPEN (DEF-727). Ask the classifier, which reads the banner's
        # major, at this site and at the twin in `_warn_interpreter_unvalidated`.
        if below_floor is None and is_below_floor_python3(version_str):
            below_floor = (candidate, path, version_str)
        if first_probe is None:
            first_probe = (candidate, path, version_str or "(no output)")
    if last_resort is not None:
        return last_resort
    if below_floor is not None:
        _warn_interpreter_below_floor(below_floor)
        return below_floor[0]
    _warn_interpreter_unvalidated(first_probe or first_failure)
    return "python"


def _remedy_interpreter() -> tuple[str, bool]:
    """The interpreter to SPELL in a remediation the operator will type, and
    whether the resolver's own answer clears the floor.

    :func:`_detect_python_command` answers "what does PATH offer" and, on a host
    where nothing validates, returns the literal ``"python"`` -- the right thing
    to WRITE (a name that exists beats one that does not) and the wrong thing to
    PRESCRIBE: on the Windows walk 2 host it spelled ``python -m espalier init .
    --rewire-interpreter`` with a ``python`` that was a Python 2 shim
    (``DEF-727``), a command that cannot run. The interpreter running THIS
    process demonstrably can -- espalier is running in it -- so it is the
    fallback, as an absolute path (the shape ``_hook_utils.python_command_hint``
    already uses across the no-import boundary). The second value is False
    exactly when ``--rewire-interpreter`` itself would find no target on this
    PATH (``REWIRE_NO_TARGET``), so a caller can say "install first" instead of
    prescribing a repair that reports nothing to do.
    """
    py = _detect_python_command()
    if interpreter_meets_floor(py):
        return py, True
    if sys.executable and interpreter_meets_floor(sys.executable):
        # An absolute path the operator will paste, so quoted when it carries
        # whitespace (`C:\Program Files\...`). Under `pipx run` / `uvx` it is
        # an ephemeral cache root a later shell may not have -- still the
        # truest name available, and every sentence built on it says to put a
        # durable interpreter on PATH first.
        return quoted_if_spaced(sys.executable), False
    return py, False


def _remedy_py() -> str:
    """The interpreter to SPELL in a remedy the operator will type: the first
    element of :func:`_remedy_interpreter`.

    Every ``f"{...} -m espalier ..."`` in this module, ``doctor.py`` and
    ``fuse.py`` spells this -- never :func:`_detect_python_command`, whose
    answer is what gets WRITTEN into settings.json and, on a host where nothing
    validated, is the literal ``python`` (a Python 2 shim, a Store alias,
    absent): a command that cannot run, handed to an operator who demonstrably
    has a working interpreter because espalier is running in it. Census
    2026-09-10: 39 f-strings interpolated the resolver beside ``-m espalier``,
    plus the ``py = _detect_python_command()`` locals that reached one
    (``DEF-758``). The split is pinned by the resolver's CALL SITES --
    ``tests/test_portability_contract.py`` reds a call outside the argued
    write-answer sites -- not by the resolver's output, which on this host
    happens to agree.
    """
    return _remedy_interpreter()[0]


def _profile_allow_list(
    profile_name: str | None,
    *,
    repo_root: Path | None = None,
    fingerprint: dict | None = None,
    posix: bool | None = None,
) -> list[str]:
    """The allow rules ``init`` writes for a profile on this tree: the static
    list, then the fingerprint-derived patterns (``reports/repo_fingerprint.json``
    read best-effort when ``fingerprint`` is not given), deduplicated -- and,
    when the render host is Windows, the ``PowerShell(...)`` twin of every
    ``Bash(...)`` rule so far (:func:`settings_profiles.powershell_twins`),
    because Claude Code's PowerShell tool is a separate tool and a
    ``Bash(...)`` rule is inert for it. ``posix`` is the same seam the
    statusLine uses (``None`` reads the host); ``doctor`` and the ``upgrade``
    preview call this without it, so on a Windows host they report the twins a
    pre-existing file lacks and ``merge-settings --add-allows`` appends them.

    Spawn-free -- it never resolves the interpreter -- so ``doctor`` and the
    ``upgrade`` preview can compare a live settings.json against it on the
    healthy path (DEF-715).
    """
    from espalier.settings_profiles import (
        DEFAULT_PROFILE,
        get_profile,
        powershell_twins,
    )

    profile = get_profile(profile_name or DEFAULT_PROFILE)
    if fingerprint is None and repo_root is not None:
        fp_path = repo_root / "reports" / "repo_fingerprint.json"
        if fp_path.exists():
            try:
                fingerprint = json.loads(fp_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                # A non-UTF-8 / BOM-prefixed repo_fingerprint.json raises
                # UnicodeDecodeError (a ValueError, not JSONDecodeError); fall back
                # to no-fingerprint rather than tracebacking the settings build.
                fingerprint = None
    static_allow = list(profile.allow)
    if isinstance(fingerprint, dict):
        derived = profile.fingerprint_allows(fingerprint)
        # Static first (curated), derived second (auto). Dedupe by
        # exact pattern. Adopter can edit either; the dedup means
        # ``Bash(pytest *)`` already in static stays put even if the
        # fingerprint also derives it.
        for pat in derived:
            if pat not in static_allow:
                static_allow.append(pat)
    if posix is None:
        posix = _render_host_is_posix()
    if not posix:
        # Bash rules first (curated, then derived), their PowerShell twins
        # after, so a file diff reads as "the same list, once per shell tool".
        static_allow.extend(powershell_twins(static_allow))
    return static_allow


def _allow_gaps(existing: dict, canonical_allow: list[str]) -> tuple[list[str], str]:
    """``(missing, note)``: the canonical allow rules ``existing`` lacks, in
    canonical order, or an empty list plus a note naming the shape that made
    the comparison impossible. An absent ``permissions`` block or ``allow``
    list is simply empty (every rule missing), not malformed."""
    permissions = existing.get("permissions")
    if permissions is None:
        return list(canonical_allow), ""
    if not isinstance(permissions, dict):
        return [], f"permissions is {type(permissions).__name__}, not an object"
    allow = permissions.get("allow")
    if allow is None:
        return list(canonical_allow), ""
    if not isinstance(allow, list):
        return [], f"permissions.allow is {type(allow).__name__}, not a list"
    present = {rule for rule in allow if isinstance(rule, str)}
    # A rule the operator DENIED or set to ASK is a judgement, not a gap: it is
    # neither reported as lacking nor appended (an allow beside a deny of the
    # same rule would be the file contradicting itself). Exact strings only.
    for key in ("deny", "ask"):
        ruled = permissions.get(key)
        if isinstance(ruled, list):
            present.update(rule for rule in ruled if isinstance(rule, str))
    return [rule for rule in canonical_allow if rule not in present], ""


def settings_allow_gaps(
    settings_path: Path, *, profile: str, repo_root: Path,
) -> tuple[list[str], str] | None:
    """Read-only twin of the merge's allow comparison for ``doctor`` and the
    ``upgrade`` preview: ``None`` when the file is absent, unreadable,
    unparseable or not an object (those states have their own reporters),
    else ``(missing, note)`` exactly as :func:`merge_hooks_into_settings`
    would compute them. Spawn-free."""
    try:
        existing = json.loads(surface_contract.decode_bom(Path(settings_path).read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(existing, dict):
        return None
    return _allow_gaps(existing, _profile_allow_list(profile, repo_root=repo_root))


def _would_add_statusline(existing: object) -> bool:
    """The merge's absent-key test (DEF-798), spelled once: espalier's
    ``statusLine`` is added only to an object with NO such key. A present key
    of any value -- an explicit ``null`` turns Claude Code's statusline off on
    purpose -- is the operator's and is never rewritten."""
    return isinstance(existing, dict) and "statusLine" not in existing


def _statusline_key_absent(settings_path: Path) -> bool:
    """Read-only twin of the merge's absent-key test (DEF-798), for the
    stale-install ``upgrade`` preview ("would add"): what ``--execute``'s
    merge will write. Reads the file the way the merge does and asks
    :func:`_would_add_statusline`; a file that cannot be read has its own
    reporters, so it reads False. The version-current branch and ``doctor``
    ask a different question -- is espalier's statusline missing on THIS
    tree -- through ``doctor.espalier_statusline_missing``."""
    try:
        existing = json.loads(surface_contract.decode_bom(Path(settings_path).read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(existing, dict):
        # The predicate guards this too; the census that pins every engine
        # parse wants the guard in the reading function (tests/test_json_dict_safe.py).
        return False
    return _would_add_statusline(existing)


def _report_allow_gaps(
    *,
    missing: "Sequence[str]",
    added: "Sequence[str]",
    note: str,
    profile: str,
    prefix: str,
    hint_command: "Callable[[], str]",
    stream: "TextIO | None" = None,
    announce_added: bool = True,
) -> None:
    """One voice for every caller of the merge: what was appended, what the
    file still lacks (with the opt-in that appends it), or why the block could
    not be compared. ``prefix`` carries its own separator (``merge-settings:``,
    ``[upgrade]``); ``hint_command`` is a callable so the interpreter probe it
    may spell runs only when there is a gap to report; ``announce_added`` is
    off when the caller's own summary line already said what was appended."""
    out = stream or sys.stdout
    if added:
        if announce_added:
            print(f"{prefix} appended {plural(len(added), 'allow rule')} of the "
                  f"{profile!r} profile:", file=out)
        for rule in added:
            print(f"    {rule}", file=out)
    if missing:
        n = len(missing)
        print(f"{prefix} {plural(n, 'allow rule')} of the {profile!r} profile "
              f"{'is' if n == 1 else 'are'} not in .claude/settings.json:", file=out)
        for rule in missing:
            print(f"    {rule}", file=out)
        print(f"    {hint_command()} appends what is missing, after your own rules; "
              f"nothing is ever removed, and nothing appends without that opt-in "
              f"-- permissions are yours. The comparison is exact-string, so a "
              f"rule you spelled differently is appended beside yours.", file=out)
    if note:
        print(f"{prefix} WARN: {note}; the {profile!r} profile's allow rules "
              f"were not compared or appended. Fix the block by hand.",
              file=sys.stderr)


def installed_settings_profile(repo_root: Path) -> str:
    """The settings profile this install's ``.claude/settings.json`` was
    rendered from: the effective name ``init`` recorded in
    ``reports/harness_config.json`` (``settings_profile``), else the
    ``espalier.toml`` ``default_profile`` the same report carries, else the
    engine default. The per-machine settings file records nothing itself, and
    comparing every install against ``workflow`` told a ``minimal`` install it
    lacked the eleven rules that profile exists to withhold (DEF-715 review).
    """
    from espalier.settings_profiles import DEFAULT_PROFILE, PROFILES

    plan_path = repo_root / "reports" / "harness_config.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return DEFAULT_PROFILE
    if not isinstance(plan, dict):
        return DEFAULT_PROFILE
    recorded = plan.get("settings_profile")
    if not isinstance(recorded, str) or recorded not in PROFILES:
        config = plan.get("config")
        recorded = config.get("default_profile") if isinstance(config, dict) else None
    if isinstance(recorded, str) and recorded in PROFILES:
        return recorded
    return DEFAULT_PROFILE


def _merge_settings_hint(profile: str) -> str:
    """The one command that appends the gap, spelled for THIS install's profile
    (the wrong profile appended is a posture change, not a top-up)."""
    return (f"`{_remedy_py()} -m espalier merge-settings . "
            f"--profile {profile} --add-allows`")


def _report_allow_gaps_read_only(
    repo_root: Path, *, profile: str, prefix: str, stream: "TextIO | None" = None,
) -> bool:
    """Report the gap without touching the file (``upgrade`` in both modes).
    Returns whether the file lacks anything, so a "nothing to do" can be true
    when it is said."""
    settings_path = repo_root / ".claude" / "settings.json"
    gaps = settings_allow_gaps(settings_path, profile=profile, repo_root=repo_root)
    if gaps is None:
        return False
    missing, note = gaps
    _report_allow_gaps(
        missing=missing, added=(), note=note, profile=profile, prefix=prefix,
        hint_command=lambda: _merge_settings_hint(profile), stream=stream,
    )
    return bool(missing)


#: What the statusline shows when its own command did not run. An OBSERVATION,
#: not a diagnosis: the shell that prints it cannot know why the command failed
#: (the interpreter gone, ``tools/cc/statusline.py`` gone, the placeholder left
#: unexpanded, a partial deploy), so the line names none of those and makes no
#: claim about the hooks -- ``doctor`` and the seeded TROUBLESHOOTING doc do the
#: diagnosing. Sits inside single quotes in a shell string, so: plain ASCII, no
#: quotes, no shell metacharacters; no interpreter name (``--rewire-interpreter``
#: swaps only argv[0]); and no bare ``espalier <verb>`` hint -- a fusion has no
#: console script (``tests/test_no_bare_espalier_hints.py``), and the one thing
#: this line knows is that the interpreter it would spell may be gone.
STATUSLINE_FALLBACK_TEXT = (
    "espalier: statusline did not run -- see docs/TROUBLESHOOTING.md"
)


def _statusline_command(python_cmd: str, *, posix: bool | None = None) -> str:
    """The ``statusLine.command`` string for ``python_cmd``.

    The placeholder is QUOTED: this string is handed to a shell (Claude Code
    documents ``sh -c`` for shell-form hook commands on macOS and Linux and,
    for the statusline itself, names only the Windows shells: Git Bash when
    installed, else PowerShell -- ``docs/external/cc-statusline.md``), and an
    unquoted ``${CLAUDE_PROJECT_DIR}`` containing a space word-splits, so the
    interpreter receives only the pre-space fragment. Quoting is orthogonal to
    the exec-form migration that ``tests/test_hook_exec_form.py`` scopes out
    -- statusLine stays a single ``command`` string.

    ON A POSIX HOST the command carries ``|| echo '<fallback>'`` (DEF-508).
    Every hook and this statusline are wired to the ONE interpreter ``init``
    detected, so when that name stops resolving nothing espalier installs can
    say so: SessionStart's own interpreter warning is spawned by the
    interpreter it would warn about, and Claude Code blanks a statusline whose
    command exits non-zero or prints nothing. The fallback is the one surface
    that runs WITHOUT the interpreter: the shell prints the line, exit 0, and
    the operator sees it on every refresh instead of a blank. The clause is
    the same under sh, bash, dash and zsh, which is what the test drives.
    (Claude Code also shows its own ``Executable not found in $PATH`` notice
    per hook fire; ``docs/TROUBLESHOOTING.md`` maps both to the remedy.)

    ON WINDOWS the head is the deployed batch shim, ``tools/cc/statusline.cmd``,
    and the interpreter is its first argument (DEF-729). Windows PowerShell
    5.1 has no ``||`` -- a parse error would blank the statusline on a
    HEALTHY install, the exact failure the fallback exists to make visible --
    and walk 2 drove the ``cmd`` spellings dead: a bare ``/c`` is rewritten
    into a drive path by Git Bash and ``//c`` starts an interactive cmd under
    PowerShell, a process blocked on stdin per refresh rather than a blank.
    Batch has the or-operator, so the shim runs the interpreter it is handed
    against ``statusline.py`` beside it and prints the same fallback text,
    exit 0 either way, and a ``.cmd`` is invocable from Git Bash, the shell
    Claude Code names for the statusline when it is installed. Under
    PowerShell without Git Bash a quoted head is an expression, not a
    command; whether that shell runs the shim is the walk's to witness, and
    the plain render it replaces expanded nothing there either. ``init``
    renders settings.json on the host that will run it, so ``os.name`` at
    render time is the key; ``posix`` overrides it for tests. The file can
    still travel (a repo that already tracks ``.claude/settings.json``,
    DEF-11): ``doctor`` flags a ``||`` or a shim head seen on the other host,
    and a string with neither (an install rendered before they existed:
    the merge adds ``statusLine`` only when the key is absent and the rewire
    swaps only the interpreter the line names -- DEF-798, DEF-810 -- so an
    older string is kept, and a fresh ``init``'s ``settings.json.new`` is
    where the current render can be read).
    """
    script = f'{python_cmd} "${{CLAUDE_PROJECT_DIR}}/{STATUSLINE_SCRIPT}"'
    if posix is None:
        posix = _render_host_is_posix()
    if not posix:
        return f'"${{CLAUDE_PROJECT_DIR}}/{STATUSLINE_SHIM}" {python_cmd}'
    return f"{script} || echo '{STATUSLINE_FALLBACK_TEXT}'"


def _render_host_is_posix() -> bool:
    """The host key for the statusLine fallback: a seam, so a test can render
    for the other host without patching ``os.name`` (which breaks pathlib)."""
    return os.name != "nt"


def _build_settings_json(
    *,
    profile_name: str | None = None,
    fingerprint: dict | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Build a default .claude/settings.json with hook wiring.

    ``profile_name`` selects the allow-list shape. ``None`` resolves
    to ``settings_profiles.DEFAULT_PROFILE`` (``"workflow"``). The deny list
    and hook wiring are profile-independent. The ``$schema`` link points at
    the live schemastore.org schema so editors with schema-aware completion
    validate the file.

    Hooks emit exec form (``command`` + ``args``) so Claude Code
    spawns the interpreter directly with each arg passed verbatim — no
    shell, no tokenization, no platform-specific variable syntax. The
    ``${CLAUDE_PROJECT_DIR}`` placeholder uses curly form per Claude
    Code's documented interpolation rules.

    Matchers are narrowed to mutation tools on PreToolUse and
    PostToolUse so non-mutating tool calls (Read, Grep, Glob) skip the
    hook spawn entirely. ``reflect_trigger.py`` keeps ``"*"`` because
    its "every Nth tool call" logic must observe every tool, not just
    mutations.

    Optional ``fingerprint`` + ``repo_root`` keyword args opt
    INTO fingerprint-derived ``Bash(<binary> *)`` allow patterns. If
    ``fingerprint`` is provided directly, it's used as-is; otherwise,
    if ``repo_root`` is provided, ``reports/repo_fingerprint.json``
    is read best-effort (absence + parse errors are treated as "no
    fingerprint" — no regression). Static profile allow patterns
    come first; derived patterns are appended after dedup; on a Windows
    render host the ``PowerShell(...)`` twin of every ``Bash(...)`` rule
    follows (see :func:`_profile_allow_list`). Both
    callers in this module pass ``repo_root=repo_root`` so non-Python
    adopters' test_commands reach the permission allow-list.
    """
    from espalier.settings_profiles import (
        deny_defaults,
    )

    python_cmd = _detect_python_command()
    static_allow = _profile_allow_list(
        profile_name, repo_root=repo_root, fingerprint=fingerprint,
    )

    def _hook(script_relpath: str) -> dict:
        # Timeout derived from CANONICAL_HOOK_WIRING by basename (the SoT),
        # not an inline literal.
        basename = script_relpath.rsplit("/", 1)[-1]
        return {
            "type": "command",
            "command": python_cmd,
            "args": [f"${{CLAUDE_PROJECT_DIR}}/{script_relpath}"],
            "timeout": _timeout_for(basename),
        }

    return {
        "$schema": _SETTINGS_SCHEMA_URL,
        "permissions": {
            "allow": static_allow,
            "deny": list(deny_defaults()),
        },
        # Surface harness state in Claude Code's prompt statusline so MAINT /
        # STOP gate / blueprint depth are observable. The script is
        # stdlib-only and exits 0 on every failure mode (graceful), so a
        # broken statusline never interrupts session flow. The command is a
        # shell string (Claude Code's statusLine schema has no exec form) and
        # on a POSIX host carries the interpreter-missing fallback --
        # see :func:`_statusline_command`. Adopters who already ran `init`
        # keep the string they have until a re-`init`.
        "statusLine": {
            "type": "command",
            "command": _statusline_command(python_cmd),
        },
        "hooks": {
            "SessionStart": [{
                "hooks": [_hook("tools/cc/hooks/session_start.py")],
            }],
            "UserPromptSubmit": [{
                "hooks": [_hook("tools/cc/hooks/task_router.py")],
            }],
            # write_guard's matcher stays "*" via CHW so Agent (formerly Task) / TodoWrite /
            # SlashCommand / BashOutput tool dispatches reach write_guard's
            # kill-switch. plan_guard's matcher narrows to
            # Write|Edit|NotebookEdit — Bash and MCP tool calls no longer fork
            # plan_guard, eliminating Bash write-intent false positives. The
            # two hooks resolve different matcher strings, so they emit as
            # separate PreToolUse entries (write_guard first, defense-in-depth
            # ordering preserved).
            "PreToolUse": [
                {
                    "matcher": _matcher_for("write_guard.py"),
                    "hooks": [_hook("tools/cc/hooks/write_guard.py")],
                },
                {
                    "matcher": _matcher_for("plan_guard.py"),
                    "hooks": [_hook("tools/cc/hooks/plan_guard.py")],
                },
            ],
            # Split PostToolUse — post_write_check fires only on mutations;
            # reflect_trigger fires on every tool call so it can count toward
            # the every-Nth-call cadence.
            "PostToolUse": [
                {
                    "matcher": _matcher_for("post_write_check.py"),
                    "hooks": [_hook("tools/cc/hooks/post_write_check.py")],
                },
                {
                    "matcher": "*",
                    "hooks": [_hook("tools/cc/hooks/reflect_trigger.py")],
                },
            ],
            "ConfigChange": [{
                "hooks": [_hook("tools/cc/hooks/config_guard.py")],
            }],
            "Stop": [{
                "hooks": [_hook("tools/cc/hooks/stop_gate.py")],
            }],
            # SubagentStop — appends subagent reasoning to the active
            # blueprint. Never blocks the subagent.
            "SubagentStop": [{
                "hooks": [_hook("tools/cc/hooks/subagent_stop.py")],
            }],
            "PostCompact": [{
                "hooks": [_hook("tools/cc/hooks/post_compact.py")],
            }],
            # Recall-engine substrate (Track B reporters). SubagentStart
            # carries no matcher (fires at every subagent spawn);
            # PostToolUseFailure narrows to the edit tools whose old_string
            # replacement can fail on a stale frame.
            "SubagentStart": [{
                "hooks": [_hook("tools/cc/hooks/subagent_start.py")],
            }],
            "PostToolUseFailure": [{
                "matcher": _matcher_for("context_reinject_failure.py"),
                "hooks": [_hook("tools/cc/hooks/context_reinject_failure.py")],
            }],
        },
    }


# Composed from the PARSER's own heading grammar rather than hand-typed, so the
# "did this pack declare the section?" test and the parser that reads it cannot
# desync — a rival literal here would re-open exactly the drift the shared
# _HEADING_PREFIX closes.
# The literals heading only. The symbols half is the parser's own match,
# `PackManifest.affected_symbols_heading`, reported verbatim; one regex over
# both headings made a literals-only pack that parsed to zero read as
# "declares an Affected symbols section", and sent its author to the symbols
# format (DEF-431).
_AFFECTED_LITERALS_HEADING_RE = re.compile(
    _pack_manifest._HEADING_PREFIX + r"Affected literals"
)


def _parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Stdlib-only YAML frontmatter parser.

    Handles the subset Espalier asset files use: scalar `key: value` lines
    plus block-scalar forms (`description: >` / `>-` / `>+` / `|` / `|-` /
    `|+` / `|2`), joining the indented body into a single space-separated
    string. Returns an empty dict if no frontmatter is detected.

    Value-interpretation (which markers open a block, and quote-stripping on
    single-line scalars) delegates to render_surface's canonical helpers
    (`_is_block_scalar_header`, `_unquote_frontmatter_value`), and so does the
    BODY FOLD — where a block ends (`_block_scalar_body_continues`) and how its
    lines join (`_normalize_description_text`). render_surface is the single
    source of truth shared with the sister renderer that produces
    `cc/LIVE_SURFACE.md` + `cc/COMMANDS.md`.

    Only the key-value walk stays cli-local, because cli needs the full
    `name`/`model`/`description` dict while the render_surface helper extracts
    `description` alone. The fold used to be cli-local too, and it had drifted:
    cli terminated a block at the first blank line, silently dropping every
    later paragraph from the CLAUDE.md tables.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    cur_key: str | None = None
    cur_buf: list[str] = []
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if cur_key is not None:
            if _block_scalar_body_continues(line):
                cur_buf.append(line)
                i += 1
                continue
            out[cur_key] = _normalize_description_text("\n".join(cur_buf))
            cur_key = None
            cur_buf = []
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if _is_block_scalar_header(val):
                cur_key = key
                cur_buf = []
            else:
                out[key] = _unquote_frontmatter_value(val)
        i += 1
    if cur_key is not None:
        out[cur_key] = _normalize_description_text("\n".join(cur_buf))
    return out


def _opening_paragraph(text: str) -> str:
    """The first prose paragraph of a command body: frontmatter and a leading
    markdown heading skipped, wrapped lines joined. This is the text
    ``_first_sentence`` renders into the CLAUDE.md tables for a command with no
    ``description:`` -- a test that wants to see what the table will show must
    call THIS, not re-implement the walk (the two drifted once, silently)."""
    body = text
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:]
    para: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # skip a leading markdown heading
        if stripped:
            para.append(stripped)
        elif para:
            break  # first blank line ends the opening paragraph
    return " ".join(para)


def _first_sentence(text: str, max_chars: int = 100) -> str:
    """Truncate a description for table rendering: first sentence or
    `max_chars`, whichever is shorter. Collapses internal whitespace."""
    collapsed = " ".join(text.split())
    cut = collapsed.split(". ", 1)[0]
    if len(cut) > max_chars:
        return cut[: max_chars - 1].rstrip() + "…"
    if cut != collapsed and len(cut) < len(collapsed):
        return cut + "."
    return cut


def _md_cell(text: str) -> str:
    """Escape a markdown-table cell so a literal ``|`` doesn't spawn a phantom
    column. Backslash is escaped first so an already-escaped pipe survives."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _build_asset_tables() -> str:
    """Render Command/Skill/Agent tables from the asset SoT.

    Reads bundled package resources via `claude_assets_root()` so the
    tables are correct at init time before files are deployed to the
    target repo. The `/smoke` checks grep CLAUDE.md for these tables, so
    all of command / skill / agent must render here.
    """
    # claude_assets_root available from module-top import.
    root = claude_assets_root()

    def _read(rel: str) -> str:
        node = root.joinpath(rel)
        try:
            return node.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            return ""

    cmd_rows: list[str] = []
    cmds_dir = root.joinpath("commands")
    if cmds_dir.is_dir():
        for entry in sorted(cmds_dir.iterdir(), key=lambda p: p.name):
            if not entry.name.endswith(".md"):
                continue
            text = _read(f"commands/{entry.name}")
            # Prefer a frontmatter `description:` (the skill/agent branches
            # below do the same). A command that opens with YAML frontmatter
            # — e.g. audit-accuracy.md — otherwise renders its `---` delimiter
            # as the Purpose, because the first non-empty line IS `---`.
            desc = _parse_yaml_frontmatter(text).get("description", "").strip()
            if not desc:
                # Prose-first-line commands (every command but audit-accuracy):
                # the purpose is the first paragraph, which usually wraps across
                # several physical lines. Take the whole first paragraph — not
                # just line one — so _first_sentence sees the full sentence
                # instead of truncating at the first line break.
                desc = _opening_paragraph(text)
            purpose = _first_sentence(desc)
            stem = entry.name[: -len(".md")]
            cmd_rows.append(f"| `/{stem}` | {_md_cell(purpose)} |")

    skill_rows: list[str] = []
    skills_dir = root.joinpath("skills")
    if skills_dir.is_dir():
        for sub in sorted(skills_dir.iterdir(), key=lambda p: p.name):
            if not sub.is_dir():
                continue
            text = _read(f"skills/{sub.name}/SKILL.md")
            front = _parse_yaml_frontmatter(text)
            trigger = _first_sentence(front.get("description", ""))
            skill_rows.append(f"| `{sub.name}` | {_md_cell(trigger)} |")

    agent_rows: list[str] = []
    agents_dir = root.joinpath("agents")
    if agents_dir.is_dir():
        for entry in sorted(agents_dir.iterdir(), key=lambda p: p.name):
            if not entry.name.endswith(".md"):
                continue
            text = _read(f"agents/{entry.name}")
            front = _parse_yaml_frontmatter(text)
            role = _first_sentence(front.get("description", ""))
            model = front.get("model", "—").strip()
            if model.lower() in ("opus", "sonnet", "haiku"):
                model = model.capitalize()
            stem = entry.name[: -len(".md")]
            agent_rows.append(f"| `{stem}` | {_md_cell(model)} | {_md_cell(role)} |")

    sections: list[str] = []
    if cmd_rows:
        sections.append(
            "## Slash Commands\n\n"
            "| Command | Purpose |\n|---|---|\n"
            + "\n".join(cmd_rows)
        )
    if skill_rows:
        sections.append(
            "## Skills\n\n"
            "Skills auto-invoke on trigger-phrase detection and are also "
            "callable as `/name`. Bodies load on-demand.\n\n"
            "| Skill | Trigger phrase |\n|---|---|\n"
            + "\n".join(skill_rows)
        )
    if agent_rows:
        sections.append(
            "## Agents\n\n"
            "| Agent | Model | Role |\n|---|---|---|\n"
            + "\n".join(agent_rows)
        )
    return "\n\n".join(sections)


# Sections the adopter's root CLAUDE.md is required to carry. A blocked adopter
# reads `see CLAUDE.md "Plan Guard" section` and searches their own CLAUDE.md
# for that string, so every name here must be a section ``_build_claude_md``
# actually renders -- otherwise the harness points them at nothing.
#
# ONE hand-written list, and it is a RATCHET, not a mirror.
# ``tests/test_denial_reasons.py`` derives the live citation set by walking the
# string constants of every hook script plus the text of every init-deployed
# doc and .claude/ asset (a citation reaches the adopter through all three
# carriers), and asserts DERIVED ⊆ this tuple -- subset, deliberately not
# equality. That asymmetry is the whole design:
#
#   a NEW citation appears    -> not in the tuple -> RED. Add it here and
#                                render the section. The gate does its job.
#   a citation is REWORDED    -> derived shrinks -> still a subset -> GREEN,
#     or deleted                 and the entry stays, so the section is still
#                                required to render. Nothing to "fix", so
#                                nothing to get wrong.
#
# Equality was tried first and is why this comment exists. Under `==`, losing a
# citation FORCES you to delete the entry, and the only prose that names
# "Cross-platform Python invocation" is a single clause in a doc that gets
# reworded routinely -- so an ordinary doc edit would have walked someone
# through un-requiring an adopter-facing section in four individually
# reasonable steps. The first attempt to resist that added a second,
# byte-identical hand-maintained tuple as a "floor"; the subset operator gets
# the same floor for free, with one list instead of two.
#
# The trade: a section nobody cites any more can linger here. That is not
# hypothetical -- "Cross-platform Python invocation" is exactly that today. Its
# one citation was a prose cross-reference in a shipped doc, and cross-file
# section references are a rot hazard worth spending down (147 of them across
# 88 files at last count), so the citation was deleted rather than tracked. The
# section stays required on its own merit: every `.claude/` command body an
# adopter receives spells the interpreter bare `python`, which fails on a host
# shipping only `python3`.
#
# Deleting that citation was a no-op against this contract -- which is the
# subset operator paying for itself. Under `==` the same edit would have reded
# and asked to drop the entry, i.e. punished exactly the cleanup worth doing.
# Every entry is asserted to render, so a lingering one costs a slightly longer
# skeleton, visible in the examples/ snapshot diff, and retiring one stays a
# deliberate edit.
REQUIRED_CLAUDE_MD_SECTIONS: tuple[str, ...] = (
    "Plan Guard",
    "Maintenance mode",
    "Cross-platform Python invocation",
)

# The ``skipped`` entry deploy_harness records when the adopter already owns a
# root CLAUDE.md. A module constant rather than a repeated literal because the
# init summary reads it back to decide whether a missing section means "your
# file, preserved" or "our generator is broken" -- two spellings would silently
# pick the wrong one of those messages.
_CLAUDE_MD_SKIPPED_MARKER = "CLAUDE.md (exists)"


def _build_claude_md(fp: 'RepoFingerprint', harness: 'BuildPlan') -> str:
    """Build a skeleton CLAUDE.md for the target repo."""
    name = fp.repo_name or "this project"
    languages = ", ".join(fp.languages) if fp.languages else "unknown"
    profiles = ", ".join(harness.profiles) if harness.profiles else "general"
    # Use the detected test command rather than a hard-coded `pytest -q`.
    # When detection yields nothing (empty repo, a JS repo with no `test`
    # script, an unfingerprintable stack), fall back to a neutral placeholder
    # rather than `pytest -q`, which is meaningless on a non-Python tree.
    test_cmd = (
        fp.test_commands[0]
        if getattr(fp, "test_commands", None)
        else "# configure your test command (e.g. pytest -q, npm test, cargo test)"
    )
    tier_tables = _build_asset_tables()
    n_hook_scripts = len(
        [s for s in INIT_HOOK_SCRIPTS if not Path(s).name.startswith("_")]
    )
    # An adopter editing source under a non-root directory hits plan-required
    # denials (those roots aren't in plan_guard's default EXEMPT_PREFIXES), and
    # the deny message points at this "Plan Guard" section. plan_guard denies
    # writes to ANY non-root, non-exempt path — a JS adopter under lib/, a Go
    # adopter under cmd/ or internal/, an app/ or mvc layout all fingerprint as
    # "flat" or "mvc" (not "src_layout") and hit the same deny. Render for every
    # adopter layout; skip only the self-host repo (harness_layered), which
    # ships a hand-written Plan Guard section.
    #
    # A falsy `pattern` (unfingerprintable / empty tree) used to skip the
    # section too, on the reasoning that such a tree "has no non-root source
    # root to gate". That reasoning was wrong in one direction that matters:
    # the fingerprint describes the tree at INIT time, while the citation in
    # plan_guard's deny fires forever after. A repo that was empty when the
    # adopter ran init grows a lib/ the next day and starts hitting a deny that
    # names a section their CLAUDE.md never got. The citation is unconditional,
    # so the section is unconditional -- the pairing is pinned by
    # tests/test_denial_reasons.py::TestRequiredClaudeMdSectionsAreRendered.
    plan_hint = ""
    pattern = (getattr(fp, "architecture", {}) or {}).get("pattern")
    if pattern != "harness_layered":
        if pattern == "src_layout":
            root_desc = "Your source lives under `src/`."
            example = 'plan_exempt_prefixes = ["src/"]'
        else:
            root_desc = (
                "If your source lives under a top-level directory other than "
                "the repo root (e.g. `src/`, `lib/`, `app/`, `cmd/`, "
                "`internal/`), routine edits there may hit plan-required "
                "denials."
            )
            example = 'plan_exempt_prefixes = ["your-source-root/"]'
        plan_hint = (
            "\n## Plan Guard\n\n"
            f"{root_desc} The plan guard requires an active execution plan "
            "before editing tracked source roots. Declare your source "
            "root(s) as plan-exempt in `espalier.toml` so routine edits "
            "aren't plan-gated:\n\n"
            f"```toml\n{example}\n```\n"
        )

    return f"""# {name} — Claude Code Governance Harness

## Project Context

{name} uses Espalier-Harness for governance. Hooks enforce quality mechanically.
Session context is loaded by the SessionStart hook automatically.

> **First-response governance check (fresh clone / new machine).** Espalier's
> hooks are wired in `.claude/settings.json`, which is per-machine and
> gitignored — it does NOT travel with a clone. If you did **not** receive the
> Espalier `=== Session Start ===` context block at the start of this session,
> the governance hooks are **not active** on this machine: tell the user to run
> `python -m espalier init .` before relying on mechanical enforcement. (When
> unsure, run `python -m espalier doctor .`.)

- **Languages:** {languages}
- **Profiles:** {profiles}

## Hooks (Mechanical Enforcement)

Espalier wires {n_hook_scripts} hook scripts that run automatically on Claude Code events:

| Hook | Event | What It Does |
|---|---|---|
| `session_start.py` | SessionStart | Reports kill-switch findings + integrity drift; loads the blueprint chain (and advances it on a new session — source `startup`/`clear`); cleans flags. Cannot block (protocol). |
| `task_router.py` | UserPromptSubmit | Classifies prompt scope; routes toward /implement-task or /implement-task --multi |
| `plan_guard.py` | PreToolUse | Blocks source file writes without an active execution plan |
| `write_guard.py` | PreToolUse | Blocks tool calls when kill-switch is set; blocks mutations of protected zones (a write into, a delete of, a move out of); blocks dangerous bash patterns |
| `config_guard.py` | ConfigChange | Blocks unsafe project/local/user settings changes; audits managed policy_settings (non-blockable) |
| `post_write_check.py` | PostToolUse | Validates each written file for JSON validity and path consistency |
| `reflect_trigger.py` | PostToolUse | Runs reflect protocol every 10th source write |
| `stop_gate.py` | Stop | Lightweight session hygiene by default (docs, review, blueprint, state); full core pytest gate opt-in via `ESPALIER_STOP_GATE=full` |
| `subagent_stop.py` | SubagentStop | Appends subagent reasoning to the active blueprint (Gate 4 only); never blocks the subagent |
| `post_compact.py` | PostCompact | Re-injects critical context after conversation compaction |
| `subagent_start.py` | SubagentStart | Injects cold-subagent orientation (host facts + fan-out finding-schema pointer); never blocks (reporter) |
| `context_reinject_failure.py` | PostToolUseFailure | On a failed Edit/Write, injects the untrusted-oracle re-derivation discipline (Rule A); never blocks (reporter) |

**Hook semantics rule:** SessionStart reports. PreToolUse and ConfigChange deny. CI guarantees. SessionStart cannot block per the official Claude Code hook protocol.

{tier_tables}
{plan_hint}
## Maintenance mode

`ESPALIER_MAINTENANCE_MODE=1` is a scoped, friction-only opt-out for editing the
harness's own files. Set it in the parent shell **before** launching Claude Code —
Claude Code inherits its environment at launch, so a mid-session `export` never
reaches hooks that are already running:

```
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude
cmd.exe:                 set ESPALIER_MAINTENANCE_MODE=1 && claude
```

Add `--continue` to any of these to resume the session you were denied in;
a bare `claude` starts a new conversation and a new blueprint node.

While it is active, `write_guard` skips its protected-zone path check,
`plan_guard` skips the plan-required check, `stop_gate` skips the docs-refresh
and code-review gates, and `subagent_stop` skips the blueprint append. Still
enforced: the kill-switch denial, dangerous-command patterns, the speed-bump
checkpoints, `config_guard`, `post_write_check`, and CI. Every bypass logs a
line to stderr, so the use is visible in the session transcript.

**Do not reach for this to edit your own source tree.** It disarms far more than
the plan gate. Declare your source roots in `plan_exempt_prefixes` in
`espalier.toml` instead — that knob is scoped to exactly the plan requirement.

## Cross-platform Python invocation

The command and skill bodies under `.claude/` show `python <script>` for
brevity. They are not host-specific, unlike `.claude/settings.json`, which
`espalier init` wrote with the interpreter it actually detected on this
machine. When following one of those bodies, try `python3` first and fall back
to `python` if the shell reports `command not found` — macOS typically ships
only `python3`, while some Windows installs ship only `python`.

## Architecture Rules

- `tools/cc/` scripts run standalone — zero project-specific imports
- Hook exit codes: `0` = allow OR structured channel (JSON on stdout for permission/decision); `2` = simple block (plain stderr, no stdout JSON); `1` = script error (bug).
- Path comparisons use `.replace("\\\\", "/")` for Windows compatibility

## Build & Test

```bash
# Run tests
{test_cmd}

# Harness integrity check
espalier audit .
```
"""


def _self_host_plan_overlay(plan_dict: dict, repo_root: Path) -> dict:
    """Amend a generic plan dict with the discovered self-host surface.

    For Espalier-Harness itself, the saved `reports/harness_config.json` should
    reflect disk reality (the discovered agent/command/hook surface) rather than
    the generic "agents we'd recommend for a Python repo" list.
    """
    surface = surface_contract.discover_self_host_surface(repo_root)
    updated = dict(plan_dict)

    # Agents: convert discovered .claude/agents/*.md into AgentSpec-shaped dicts.
    agents: list[dict] = []
    for agent_path in surface.get("agents", []):
        name = Path(agent_path).stem
        agents.append({
            "name": name,
            "description": "",
            "write_access": False,
            "scope": "self_host",
            "model": "sonnet",
            "primary_paths": [],
            "generated_paths": [],
            "test_commands": [],
        })
    updated["agents"] = agents

    # Hooks: use the canonical wiring anchored to disk-present scripts.
    hooks: list[dict] = []
    for hook_path in surface.get("hooks", []):
        name = Path(hook_path).name
        wiring = CANONICAL_HOOK_WIRING.get(name, {})
        hooks.append({
            "event": wiring.get("event", "PostToolUse"),
            "script": hook_path,
            "timeout": wiring.get("timeout", 10),
            "matcher": wiring.get("matcher", ""),
            "reason": wiring.get("reason", ""),
            "is_async": False,
        })
    updated["hooks"] = hooks

    # Generated docs: required init files + installed command docs.
    docs: list[str] = list(surface_contract.get_required_init_files())
    docs.extend(surface.get("commands", []))
    updated["generated_docs"] = sorted(set(docs))

    return updated


def _build_memory_md(fp: 'RepoFingerprint') -> str:
    """Build a skeleton ESPALIER_MEMORY.md for the target repo."""
    name = fp.repo_name or "this project"
    languages = ", ".join(fp.languages) if fp.languages else "unknown"

    return f"""# {name} — Project Memory

## Repo Context

**Repo:** {name}
**Stack:** {languages}

## Harness Decisions

| Decision | Date | Reason |
|----------|------|--------|

## Patterns Learned

| Pattern | Notes |
|---------|-------|

## Session Log

**Pruning policy:** Keep the 5 most recent entries; keep this file short.

| Date | What Happened | Notes |
|------|--------------|-------|

## Categorized memory

For long-form entries that don't fit in the index above, see
[`memory/`](memory/).  `espalier init .` creates an empty `memory/`
folder with a README explaining the convention.
"""


def _build_changelog_md() -> str:
    """Build a clean Keep a Changelog skeleton for a target repo.

    Repo-agnostic (unlike the CLAUDE.md/ESPALIER_MEMORY.md templates it carries no
    fingerprint-derived content), so an adopter can start a user-facing
    changelog from `espalier render-template changelog` without hand-copying
    the boilerplate — and with the "plain language, no internal IDs" norm
    baked in from line one.
    """
    return """# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- _Record user-facing changes here as you land them. At release, fold them into
  a new dated `## [X.Y.Z] — YYYY-MM-DD` section and bump your version. Keep every
  entry in plain language — internal ticket or task-pack IDs don't belong on a
  changelog a user reads._
"""


def _scan_managed_orphans(repo_root: Path) -> list[str]:
    """Detect managed ``.py`` files in the deploy dirs that are NO LONGER in
    the current ``INIT_*`` sets — retired across a version upgrade.

    REPORT-ONLY: this never deletes; init has no authority to remove an
    operator's tree. The forward deploy loop only writes the CURRENT set, so a
    hook/tool retired in a newer version lingers on disk and a hand-merged
    ``.claude/settings.json`` can still reference a deleted hook. Mirrors
    ``cleanup.py``'s marker-aware orphan scan but scoped to the ``tools/cc/``
    Python deploy dirs (which cleanup's ``user_only_prefixes`` omits) — files
    WITHOUT the managed marker are user-authored and never named. The scan also
    covers marker-carrying ``.claude/{commands,agents,
    skills}`` assets, compared against the packaged surface
    (``asset_inventory.get_packaged_surface``): only an asset the package no
    longer ships (genuinely retired) is named.
    """
    current = {p.replace("\\", "/") for p in (INIT_HOOK_SCRIPTS + INIT_TOOL_SCRIPTS)}
    orphans: list[str] = []
    seen: set[str] = set()
    scan_targets = [
        (repo_root / "tools" / "cc" / "hooks", True),   # recursive
        (repo_root / "tools" / "cc", False),            # top-level only
    ]
    for base, recursive in scan_targets:
        if not base.is_dir():
            continue
        # Every deploy-source suffix (the .py scripts and the .cmd statusline
        # shim, DEF-729): a retired shim must be named like a retired script.
        files = safe_rglob(base, "*") if recursive else base.iterdir()
        for fp_path in files:
            if fp_path.suffix not in DEPLOYED_SCRIPT_SUFFIXES or not fp_path.is_file():
                continue
            rel = fp_path.relative_to(repo_root).as_posix()
            if rel in current or rel in seen:
                continue
            seen.add(rel)
            try:
                text = fp_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if has_managed_marker(text):
                orphans.append(rel)

    # Marker-carrying .claude/** assets retired across an upgrade.
    try:
        from espalier.asset_inventory import get_packaged_surface
        surface = get_packaged_surface()
        claude_targets = [
            (
                f".claude/{kind}",
                surface_contract.CLAUDE_KIND_GLOBS[kind],
                set(getattr(surface, kind).paths),
            )
            for kind in surface_contract.CLAUDE_SURFACE_KINDS
        ]
        for subdir, pattern, packaged in claude_targets:
            base = repo_root / subdir
            if not base.is_dir():
                continue
            for fp_path in base.glob(pattern):
                if not fp_path.is_file():
                    continue
                asset_rel = fp_path.relative_to(base).as_posix()
                if asset_rel in packaged:
                    continue  # still shipped at some tier -> not retired
                rel = fp_path.relative_to(repo_root).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                try:
                    text = fp_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if has_managed_marker(text):
                    orphans.append(rel)
    except Exception:  # noqa: BLE001, S110 -- orphan scan is advisory; never fail init
        pass

    return sorted(orphans)


def _event_groups_have_espalier_hook(groups: object) -> bool:
    """True when ONE settings.json event's value (a list of group dicts) carries
    an entry that *executes* an Espalier hook script.

    The per-event core, shared so the same exec-form + legacy-shell-form
    recognition serves BOTH the any-event "already wired" banner discriminator
    AND the per-event top-up in ``merge_hooks_into_settings`` (append only the
    canonical events still missing an Espalier hook). Single implementation — no
    parallel-inventory drift."""
    if not isinstance(groups, list):
        return False
    espalier_basenames = {Path(s).name for s in INIT_HOOK_SCRIPTS}
    for group in groups:
        if not isinstance(group, dict):
            continue
        # Strict exec-form match (the canonical post-v0.6.4 wiring): the
        # shape-aware oracle returns the executed script path per hook entry.
        for entry in group.get("hooks", []) or []:
            if not isinstance(entry, dict):
                continue
            script = surface_contract._hook_executes_script_path(entry)
            if script and Path(script).name in espalier_basenames:
                return True
        # Legacy shell-form fallback: pre-v0.6.5 deployments wired SHELL-FORM
        # commands (`python ${CLAUDE_PROJECT_DIR}/.../write_guard.py`, no args),
        # which the exec-form-only oracle above fails CLOSED on. Reuse the
        # codebase's permissive, basename-ANCHORED recognizer (the same one the
        # stale-matcher WARN uses for these exact configs) so an UPGRADE over a
        # legacy espalier install reads as already-wired — otherwise merge
        # double-appends the canonical hooks (double enforcement) and the banner
        # mis-reports "NOT wired." It anchors on `/<basename>`, so the
        # directory-fragment bait (`echo tools/cc/hooks ...`) still reads as NOT
        # wired.
        if any(
            surface_contract._entry_references_script(group, name)
            for name in espalier_basenames
        ):
            return True
    return False


def _settings_has_espalier_hooks(settings: object) -> bool:
    """True when a ``settings.json`` dict actually *executes* Espalier's hooks.

    Walks the ``hooks`` block and matches each entry against the shape-aware
    oracle ``surface_contract._hook_executes_script_path`` (the canonical
    exec-form extractor), then checks the resolved script's basename against
    ``INIT_HOOK_SCRIPTS``. A non-dict, a dict with no ``hooks`` block, an
    adopter's own unrelated hooks, OR a hooks block that merely *mentions* the
    ``tools/cc/hooks`` path fragment in a non-executing position (an ``echo``
    command, a comment, a sys.argv string) all read as ``False`` — a bare
    substring match would false-read any settings merely containing the fragment
    as already-wired, the false-green class this harness exists to prevent.

    This is the discriminator between two existing-``settings.json`` cases:
    a genuine Espalier *upgrade* (hooks already live -> the stale-matcher /
    recall-event WARNs apply) versus a brand-new adopter who brought their own
    ``settings.json`` (no Espalier hooks -> init/fuse preserves it untouched and
    enforcement never gets wired, the case the upgrade WARNs mis-frame).

    ⚠ THAT IS THE ONLY QUESTION IT ANSWERS. It is NOT an "is enforcement
    armed" oracle, and must never be used as the basis of an enforcement
    claim. For the upgrade question, permissiveness is CORRECT -- the legacy
    shell-form fallback above exists so an upgrade over a pre-v0.6.5 install
    reads as already-wired instead of double-appending the canonical hooks.
    For the armament question, that same permissiveness is a lie: this returns
    ``True`` for a settings.json whose gates are wired to ``echo``, whose
    scripts were never deployed, or whose PreToolUse matcher cannot reach a
    Write. Measured 2026-08-27: it read ``True`` on a tree where ``doctor``
    reported four governance-wiring failures in the same second.

    Callers asserting enforcement want :func:`_enforcement_claim_blockers`,
    which unions path-resolution with executable-wiring. Conflating the two
    questions in this one predicate is the defect class that produced the
    false "Hooks now intercept Claude Code tool calls" banner on the default
    ``init`` path.
    """
    if not isinstance(settings, dict):
        return False
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return any(_event_groups_have_espalier_hook(groups) for groups in hooks.values())


@dataclass
class SettingsOutcome:
    """Result of reconciling a pre-existing ``.claude/settings.json``.

    ``_reconcile_existing_settings`` returns this so ``deploy_harness`` folds a
    single value into its tallies instead of nesting the four adopter-state cases
    inline. The helper performs the operator-facing WARN/INFO prints and the
    ``.new`` render as side effects (message wording is contract-pinned by
    tests/test_init_upgrade_paths.py); these fields carry only what
    ``deploy_harness`` threads into its return dict and lists.
    """

    settings_hooks_wired: bool
    skipped_reason: str | None
    deployed: list[str]


def _reconcile_existing_settings(
    settings_path: Path,
    *,
    wire_hooks: bool,
    profile_name: str | None,
    repo_root: Path,
) -> SettingsOutcome:
    """Reconcile a pre-existing ``.claude/settings.json``.

    Three adopter states are handled here -- new-adopter honest "NOT active"
    WARN (case b), genuine-upgrade stale-matcher / recall-event WARNs (case a),
    and the ``.new`` side-by-side render -- while the ``--wire-hooks`` one-shot
    in-place merge routes out to ``_wire_hooks_into_existing`` (the single shared
    arming path). The WARN/INFO prints and the atomic ``.new`` write are side
    effects; ``skipped_reason`` is returned for the caller to append
    (deploy_harness owns the single ``skipped`` list).
    """
    deployed: list[str] = []
    # An upgrade from an older deployment can keep a stale matcher (no
    # ``mcp__.*``) on disk. Without it, Claude Code filters write_guard out of
    # the hook pipeline for every MCP tool call. Detect the gap and tell the
    # operator how to refresh. (We don't auto-overwrite an existing
    # settings.json because users hand-edit it.)
    skipped_reason = ".claude/settings.json (exists -- merge manually)"
    try:
        # decode_bom (UTF-8/16/32 BOM-tolerant), consistent with the other
        # settings.json readers (the stale-matcher warn must still fire on a
        # BOM'd upgrade settings.json).
        existing = json.loads(
            surface_contract.decode_bom(settings_path.read_bytes())
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        existing = None
    # An existing settings.json is one of two very different things.
    #  (a) UPGRADE — a prior Espalier deployment; it already wires the
    #      tools/cc/hooks/ scripts, enforcement is live, and the
    #      stale-matcher / recall-event upgrade WARNs below apply.
    #  (b) NEW ADOPTER — someone who already uses Claude Code and brought
    #      their OWN settings.json (permissions, no Espalier hooks). init/fuse
    #      will NOT overwrite it (user sovereignty), so NO hooks get wired and
    #      the harness silently ships disarmed. This is the common case the
    #      upgrade WARNs mis-frame (e.g. "missing 2 reporters" when in fact ALL
    #      hooks are absent). Detect it and tell the honest truth.
    # TWO DIFFERENT QUESTIONS, computed separately on purpose. This one --
    # "did a prior Espalier deployment wire this file?" -- selects the case
    # (a)/(b) branch below, and permissive is CORRECT for it. It is NOT the
    # armament answer; that is derived from the blockers at the return.
    has_espalier_hooks = _settings_has_espalier_hooks(existing)
    # --wire-hooks: the operator asked for one-shot in-place arming. Route
    # through the shared helper (the SAME merge `merge-settings` uses) and
    # return its outcome directly — a wired-in-place file suppresses the .new
    # render, so there is nothing left for the case (a)/(b) tail to do.
    if wire_hooks:
        return _wire_hooks_into_existing(
            settings_path, existing=existing,
            profile_name=profile_name, repo_root=repo_root,
        )
    py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
    if isinstance(existing, dict) and not has_espalier_hooks:
        # Case (b): new adopter — governance is NOT active. Offer to arm now,
        # but ONLY interactively. Off a TTY (CI, pytest, a captured subprocess)
        # _stream_isatty is False, so we skip the prompt and fall through to the
        # preserve+WARN default unchanged — a bare `input()` on a pipe would
        # EOFError and break every non-interactive init. _stream_isatty is also
        # None-safe (a closed fd `0<&-` / pythonw sets sys.stdin/stderr to None),
        # so the gate never raises. The prompt goes to stderr (this function's
        # whole narration stream); the default is NO.
        if _stream_isatty(sys.stdin) and _stream_isatty(sys.stderr):
            print(
                "Espalier's hooks are not wired into your existing "
                ".claude/settings.json, so enforcement is inactive.\n"
                "Wire them now? (preserves your keys, keeps a .bak of them) [y/N] ",
                end="", file=sys.stderr, flush=True,
            )
            try:
                answer = input()
            except EOFError:
                # Ctrl+D (Ctrl+Z then Enter on Windows) at the prompt is the
                # same answer as an empty line: the default, NO. Before
                # DEF-800 it was an uncaught EOFError over a half-deployed tree.
                answer = ""
            except KeyboardInterrupt:
                # Ctrl+C: init stops HERE, with the scripts deployed and the
                # settings untouched, so name that state before `main` turns
                # the interrupt into a one-line exit 130 (DEF-800) -- a
                # traceback said nothing about what the operator now has.
                print(
                    "\nInterrupted at the wire prompt. Deployed so far: reports/, "
                    "the seeded docs, and the hook and tool scripts under "
                    "tools/cc/. Not done: .claude/settings.json is unchanged "
                    "(hooks NOT wired), and the rest of the deploy did not run. "
                    f"Re-run `{py} -m espalier init . --wire-hooks` to finish in "
                    "one shot.",
                    file=sys.stderr,
                )
                raise
            if answer.strip().lower() in ("y", "yes"):
                return _wire_hooks_into_existing(
                    settings_path, existing=existing,
                    profile_name=profile_name, repo_root=repo_root,
                )
        # Not a TTY, or the operator declined: preserve + WARN (self-remedying).
        print(
            "WARN: .claude/settings.json already exists but has NO Espalier "
            "hooks wired -- enforcement (write_guard, plan_guard, stop_gate, "
            "...) is NOT active. Your file was preserved unchanged. To wire "
            "the hooks in while keeping your existing settings, run: "
            f"{py} -m espalier merge-settings <repo>  (or merge the rendered .new "
            "template below by hand; or re-run init with --wire-hooks).",
            file=sys.stderr,
        )
        skipped_reason = (
            ".claude/settings.json (exists, NO HOOKS WIRED -- see WARN; "
            f"run `{py} -m espalier merge-settings` to activate)"
        )
    else:
        # Case (a): genuine Espalier upgrade — the upgrade-path WARNs apply
        # (they are nonsensical for a brand-new adopter, so they are gated
        # here behind "already has Espalier hooks").
        #
        # Scope the stale-matcher detection to the write_guard ENTRY. The WARN
        # fires only when write_guard's OWN matcher cannot reach MCP tool calls
        # (the real pre-v0.6.5 regression) — scanning EVERY hook entry for
        # `"Write" in matcher and "mcp__" not in matcher` would trip on
        # plan_guard's and context_reinject_failure's narrow-by-design
        # "Write|Edit|NotebookEdit" matchers on every re-init of a CORRECT
        # config, a false alarm whose recommended remedy (`rm + re-init`) is
        # destructive. `existing` is dict|None; the helper guards non-dict input.
        if surface_contract.write_guard_matcher_excludes_mcp(existing):
            print(
                "WARN: .claude/settings.json appears to be from a pre-v0.6.5 "
                "deployment (write_guard's PreToolUse matcher excludes "
                "`mcp__.*`). MCP tool calls bypass write_guard with this "
                "matcher. To refresh non-destructively: "
                f"{py} -m espalier upgrade .  (preview; add --execute to apply).",
                file=sys.stderr,
            )
            skipped_reason = (
                ".claude/settings.json (exists, STALE MATCHER -- "
                f"see WARN; run `{py} -m espalier upgrade .` to refresh)"
            )
        # A settings.json from a deployment that predates the recall-engine
        # reporter hooks: re-init writes the scripts into tools/cc/hooks/
        # (forward loop above) but never rewires an existing settings.json, so
        # the SubagentStart / PostToolUseFailure events stay unwired and
        # `doctor` still reports pass. Name the missing event keys so the
        # operator knows to pick them up from the .new render below (no
        # auto-rewrite — settings.json is hand-editable).
        if isinstance(existing, dict):
            hooks_block = existing.get("hooks")
            wired_events = (
                set(hooks_block.keys())
                if isinstance(hooks_block, dict) else set()
            )
            recall_events = {
                "SubagentStart": "subagent_start.py",
                "PostToolUseFailure": "context_reinject_failure.py",
            }
            missing_events = [
                ev for ev in recall_events if ev not in wired_events
            ]
            if missing_events:
                print(
                    "WARN: .claude/settings.json is missing "
                    f"{plural(len(missing_events), 'recall-engine hook event')}: "
                    + ", ".join(
                        f"{ev} -> {recall_events[ev]}" for ev in missing_events
                    )
                    + ". These reporters were added in a later harness version; re-init does "
                    "not rewire an existing settings.json. "
                    f"`{py} -m espalier merge-settings .` adds the missing "
                    "events non-destructively (`upgrade` says 'nothing to do' "
                    "on a version-current install), or pick them up from the "
                    "rendered .new template below (diff + merge).",
                    file=sys.stderr,
                )
    # Render the fresh template alongside so the operator can diff the existing
    # file against what a fresh init would emit. The only case that suppresses
    # this — a wired-in-place --wire-hooks merge — already returned above.
    _render_settings_new_template(
        settings_path, existing=existing,
        profile_name=profile_name, repo_root=repo_root, deployed=deployed,
    )
    # The banner's answer is the ARMAMENT one, read back off the file that is
    # now on disk -- never the upgrade discriminator above. `== []` and not
    # `not blockers`: None is UNVERIFIABLE and must not read as armed.
    # BOTH halves are required. The blockers ask "does what is wired work?" --
    # on a settings.json that wires no Espalier hooks at all they are EMPTY,
    # because there is nothing to find fault with. That is the brought-your-own
    # adopter (case b), the single most common disarmed state there is, and
    # reading it as armed is a fail-open. The discriminator supplies the other
    # half: is anything wired at all.
    blockers = _enforcement_claim_blockers(repo_root, settings_path)
    return SettingsOutcome(
        settings_hooks_wired=(has_espalier_hooks and blockers == []),
        skipped_reason=skipped_reason,
        deployed=deployed,
    )


def _wire_hooks_into_existing(
    settings_path: Path,
    *,
    existing: object,
    profile_name: str | None,
    repo_root: Path,
) -> SettingsOutcome:
    """Arm an existing hookless ``.claude/settings.json`` in place.

    The single shared arming path behind BOTH ``--wire-hooks`` and the
    interactive case-(b) "wire now?" prompt, so the two cannot drift. Runs the
    SAME merge ``merge-settings`` uses (preserve every key, append Espalier's
    hooks, write a ``.bak``) and returns the ``SettingsOutcome`` deploy_harness
    folds into its tallies. The merge is intentionally NOT pre-conditioned on
    ``isinstance(existing, dict)``: a malformed file (unparseable -> ``None``;
    non-object top level -> list/str/num) must STILL get the honest refusal, not
    silently fall through to the generic case-(a) message.
    """
    deployed: list[str] = []
    skipped_reason: str | None = ".claude/settings.json (exists -- merge manually)"
    has_espalier_hooks = _settings_has_espalier_hooks(existing)
    # Bound up front: the REFUSAL arm below returns without reaching either
    # merge branch, and a refusal is definitionally not armed. (Leaving this to
    # the branches raised UnboundLocalError on all three malformed-input
    # tests -- caught by them, which is why they exist.)
    settings_hooks_wired = False
    # Gate on the merge core's verdict, not `not settings_hooks_wired`: the core
    # is the single source of truth for "fully wired" — it tops up a PARTIAL
    # upgrade (older engine missing a newer canonical event) and returns
    # MERGE_ALREADY only when EVERY event is wired.
    merge_result = merge_hooks_into_settings(
        settings_path, profile=profile_name or "workflow",
        repo_root=repo_root,
    )
    # The profile's allow rules the file lacks are the operator's to accept;
    # --wire-hooks appends hook events (and espalier's statusLine when that key
    # is absent), never allow rules, so say what it did not append -- after the
    # line that says what it did.
    def _wire_hooks_gaps() -> None:
        _report_allow_gaps(
            missing=merge_result.missing_allows, added=(), note=merge_result.allow_note,
            profile=profile_name or "workflow", prefix="--wire-hooks:",
            hint_command=lambda: _merge_settings_hint(profile_name or "workflow"),
            stream=sys.stderr,
        )
    if merge_result.status == MERGE_WIRED:
        # Wired in place -> the live file already carries the hooks, so suppress
        # the .new render (it would diff the now-wired file against a fresh-only
        # template and misleadingly suggest merging again) and return directly.
        wired_line = (
            f"--wire-hooks: {_merge_did_phrase(merge_result)} into "
            ".claude/settings.json (your other "
            f"settings were preserved; backup at {merge_result.detail})."
        )
        # Topping up the SETTINGS does not arm a gate whose script is absent or
        # whose command is inert, so re-read the file we just wrote.
        blockers = _enforcement_claim_blockers(repo_root, settings_path)
        if blockers is None:
            print(wired_line, file=sys.stderr)
            print(_unverifiable_settings_warning(settings_path), file=sys.stderr)
        elif blockers:
            print(wired_line, file=sys.stderr)
            print(_disarmed_hook_tree_warning(
                repo_root, prefix="--wire-hooks", wrote_settings=True,
            ), file=sys.stderr)
        else:
            print(wired_line + _merge_claim(merge_result), file=sys.stderr)
            reporters_line = _dead_reporters_line(repo_root, _remedy_py())
            if reporters_line:
                print("--wire-hooks: " + reporters_line, file=sys.stderr)
        _wire_hooks_gaps()
        deployed.append(".claude/settings.json")
        deployed.append(".claude/" + merge_result.detail)
        return SettingsOutcome(
            settings_hooks_wired=(blockers == []),
            skipped_reason=None, deployed=deployed,
        )
    if merge_result.status == MERGE_ALREADY:
        # Already FULLY wired — a clean no-op (no .bak churn, no re-merge), and
        # stays one on re-run. (A partial upgrade returns MERGE_WIRED above and
        # gets topped up.) "Every event is wired" is NOT "every gate fires":
        # ALREADY is exactly the branch that touches nothing, so an inert gate
        # survives it untouched. Ask the blockers, not the merge status.
        settings_hooks_wired = (
            _enforcement_claim_blockers(repo_root, settings_path) == []
        )
        _wire_hooks_gaps()
    else:
        # Refusal (malformed file). Name the reason; preserve the file
        # (decision: never overwrite content).
        py = _remedy_py()
        print(
            "WARN: --wire-hooks could not wire .claude/settings.json "
            f"({merge_result.status}: {merge_result.detail}). Your file "
            "was preserved unchanged -- enforcement is NOT active. Fix "
            f"the file, then run `{py} -m espalier merge-settings <repo>`.",
            file=sys.stderr,
        )
        skipped_reason = (
            ".claude/settings.json (exists, --wire-hooks REFUSED -- see "
            f"WARN; fix the file + run `{py} -m espalier merge-settings`)"
        )
    # MERGE_ALREADY and refusal did NOT wire in place -> render the fresh
    # template alongside for the operator to diff + merge (parity with the
    # non-wire case (a)/(b) tail).
    _render_settings_new_template(
        settings_path, existing=existing,
        profile_name=profile_name, repo_root=repo_root, deployed=deployed,
    )
    return SettingsOutcome(
        settings_hooks_wired=settings_hooks_wired,
        skipped_reason=skipped_reason,
        deployed=deployed,
    )


def _render_settings_new_template(
    settings_path: Path,
    *,
    existing: object,
    profile_name: str | None,
    repo_root: Path,
    deployed: list[str],
) -> None:
    """Render a fresh settings template beside an existing file as
    ``settings.json.new`` so the operator can diff the existing file against
    what a fresh init would emit (otherwise a user can't pick up newer hook
    additions without ``rm`` + re-init).

    The ``.new`` file is an inert artifact; config_guard scopes its checks to
    the bare filenames (settings.json + settings.local.json), not suffix-extended
    siblings, so the render doesn't trip the guard. No-op when the existing file
    already equals a fresh render (an empty-diff artifact that ``git add -A``
    would otherwise stage). Appends the rendered path to ``deployed`` on success.
    """
    try:
        new_settings = _build_settings_json(
            profile_name=profile_name, repo_root=repo_root
        )
        new_settings[JSON_SENTINEL_KEY] = True
        if isinstance(existing, dict) and existing == new_settings:
            return
        new_path = settings_path.with_name(settings_path.name + ".new")
        atomic_write_text(
            new_path,
            json.dumps(new_settings, indent=2, sort_keys=True) + "\n",
        )
        print(
            f"INFO: rendered fresh template at {new_path.name}. "
            f"Compare with: diff .claude/{settings_path.name} "
            f".claude/{new_path.name}",
            file=sys.stderr,
        )
        deployed.append(".claude/" + new_path.name)
    except OSError as exc:
        print(
            f"WARN: could not write {settings_path.name}.new template: "
            f"{os_error_text(exc)}",
            file=sys.stderr,
        )


def _print_legacy_memory_nudge() -> None:
    """Nudge a pre-rename adopter (a legacy ``MEMORY.md`` present, no
    ``ESPALIER_MEMORY.md`` yet) to migrate. Shared by ``deploy_harness`` (the init
    / ``upgrade --execute`` path) and ``cmd_upgrade`` (the dry-run preview) so the
    two surfaces cannot word-drift."""
    print(
        "\nNOTE: found a legacy MEMORY.md -- this name now collides with Claude "
        "Code's machine-local auto-memory. Rename it to end the collision:\n"
        "    git mv MEMORY.md ESPALIER_MEMORY.md"
    )


def _print_claude_md_nudge(claude_md: Path, *, preserved: bool = True) -> None:
    """Tell an adopter whose own CLAUDE.md was preserved which harness sections
    it lacks.

    ``init`` never rewrites a CLAUDE.md the adopter already owns. That is the
    right call, but it leaves the hook deny messages citing sections by name
    (``see CLAUDE.md "Plan Guard" section``) with nothing to resolve to -- and
    the skip was previously reported only as an anonymous entry in a count.
    Name the file, name the missing sections, and point at the command that
    prints them.

    The check is a case-insensitive match for the name in a HEADING at any
    depth, not a bare substring anywhere in the file. Both directions were
    considered and the asymmetry decides it: ``maintenance mode`` and ``plan
    guard`` are ordinary English phrases that appear incidentally in real
    CLAUDE.md prose ("we freeze deploys during maintenance mode"), and a bare
    substring match treats that as coverage -- leaving the adopter with a
    dangling citation AND no report, the exact pair this exists to break. A
    false alarm costs one line of stdout; a false silence costs the whole fix.
    Matching any heading depth still honours an adopter who wrote the section
    themselves under ``###``. Silent when nothing is missing.
    """
    try:
        text = claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    missing = [
        s for s in REQUIRED_CLAUDE_MD_SECTIONS
        if not re.search(rf"(?mi)^#{{1,6}}\s.*{re.escape(s)}", text)
    ]
    if not missing:
        return
    quoted = [f'"{s}"' for s in missing]
    names = quoted[0] if len(quoted) == 1 else (
        " and ".join((", ".join(quoted[:-1]), quoted[-1]))
    )
    noun = "section" if len(missing) == 1 else "sections"
    them = "it" if len(missing) == 1 else "them"
    lede = (
        "kept your existing CLAUDE.md (never rewritten)"
        if preserved
        # Init just rendered this file and it STILL lacks a required section
        # -- that is a defect in the generator, not an adopter choice. Say
        # which it is rather than blaming the adopter for a file they did not
        # write.
        else "the CLAUDE.md just generated is incomplete (please report this)"
    )
    # "SOME hook denials", not "the harness cites them". REQUIRED_CLAUDE_MD_
    # SECTIONS is a superset of what is cited right now -- a section stays
    # required after its last citation is deleted -- so a message asserting
    # every missing section is pointed at by name goes false the moment a
    # citation is cleaned up. It already did once.
    print(
        f"\nNOTE: {lede}. It has no {names} {noun}. Espalier expects a "
        f"CLAUDE.md to carry {them}, and some hook denials name {them} "
        f"directly, so a denial that says \"see CLAUDE.md ...\" can send you "
        f"looking for nothing. No write is blocked by this -- every denial "
        f"also states its full remedy inline. To add the {noun}:\n"
        # The host interpreter, not a bare `python`. Printing `python` here
        # would be `command not found` on a macOS host that ships only
        # `python3` -- while telling the adopter to go add a section named
        # "Cross-platform Python invocation".
        f"    {_remedy_py()} -m espalier render-template claude"
        f"   # prints the whole skeleton; copy the sections you want"
    )


def deploy_harness(
    repo_root: Path,
    harness: 'BuildPlan',
    fp: 'RepoFingerprint',
    *,
    profile_name: str | None = None,
    wire_hooks: bool = False,
) -> dict:
    """Deploy the mechanical harness layer into a target repo.

    ``profile_name`` selects the settings profile shape written
    to ``.claude/settings.json``. ``None`` resolves to the default
    profile (``"workflow"``).

    Iteration invariant (BC-030/031): the asset set this function
    regenerates is derived from import-time enumeration of packaged
    sources — ``INIT_HOOK_SCRIPTS`` + ``INIT_TOOL_SCRIPTS`` (module-level
    constants) for ``.py`` deploys and ``_packaged_md_assets`` (glob over
    ``espalier/assets/claude/``) for ``.md`` deploys. It MUST NOT consult
    ``cc/PACK_MANIFEST.txt`` for the iteration set. The manifest is a
    *report* of what was deployed, written post-deploy by
    ``write_required_surface``; it is not the *authority* for what to
    deploy. Trusting the on-disk manifest opens BC-031: an attacker who
    can write to it can silently shrink the deploy set and prevent the
    regeneration of a hand-disabled hook (the marker-preserving silent
    disable). The contract is enforced by
    ``tests/test_cli_deploy.py::TestDeployIterationInvariant``.
    """
    repo_root = repo_root.resolve()
    harness_root = _espalier_root()

    deployed: list[str] = []
    skipped: list[str] = []
    # Ownership tallies: created (new file), updated_managed (regenerated
    # an existing managed file), skipped_user_files (preserved an unmarked
    # file), skipped_no_drift (byte-identical copy, no rewrite). Reported in
    # init's printed summary.
    created: list[str] = []
    updated_managed: list[str] = []
    skipped_user_files: list[str] = []
    skipped_no_drift_files: list[str] = []

    # 1. Deploy hook scripts and tool scripts with drift detection.
    # ``_deploy_managed_py`` compares the expected output (source + marker)
    # against the deployed copy; managed files regenerate on drift,
    # user-patched files are preserved with a stderr warning so the operator
    # notices the divergence (a plain exists/not-exists check would keep stale
    # hook scripts silently across an upgrade).
    for rel_path in INIT_HOOK_SCRIPTS + INIT_TOOL_SCRIPTS:
        source = _deploy_source_path(rel_path)
        dest = repo_root / rel_path
        action = _deploy_managed_py(source, dest)
        if action == "created":
            deployed.append(rel_path)
            created.append(rel_path)
        elif action == "updated_managed":
            deployed.append(rel_path)
            updated_managed.append(rel_path)
        elif action == "skipped_no_drift":
            skipped.append(rel_path)
            skipped_no_drift_files.append(rel_path)
        elif action == "skipped_user_file":
            skipped_user_files.append(rel_path)
            skipped.append(f"{rel_path} (user file preserved)")
            print(
                f"[WARN] hook drift: {rel_path} differs from packaged "
                f"version; preserving user edit. Add a managed marker "
                f"line (# espalier:managed) to opt back into automatic "
                f"updates on next init.",
                file=sys.stderr,
            )
        elif action == "skipped_source_missing":
            skipped.append(f"{rel_path} (source missing)")

    # 1b. Reverse pass — detect managed `.py` files left in the deploy
    # dirs by a PRIOR version that retired a hook/tool. The forward loop above
    # only writes the current set, so retired files linger and a hand-merged
    # settings.json can reference a deleted hook. REPORT only (never delete).
    managed_orphans = _scan_managed_orphans(repo_root)
    if managed_orphans:
        print(
            "[WARN] retired managed files found (deployed by an older "
            "espalier version, no longer shipped at any tier):",
            file=sys.stderr,
        )
        for rel in managed_orphans:
            print(f"         {rel}", file=sys.stderr)
        print(
            "       These are inert but may be loaded by Claude Code or "
            "referenced by a hand-merged .claude/settings.json. To remove: "
            "rm " + " ".join(managed_orphans),
            file=sys.stderr,
        )

    # 2. Deploy or merge settings.json
    settings_path = repo_root / ".claude" / "settings.json"
    # Whether the LIVE settings.json ends up with Espalier's hooks wired.
    # Drives the honest cmd_init banner (don't claim "Hooks now intercept ..."
    # when they don't). Fresh write -> True; existing file -> only if it
    # already wires the hooks (a genuine upgrade).
    settings_hooks_wired = False
    # An EMPTY file is absent for this decision: there is no content to
    # preserve, and preserving it sent the adopter through a move-aside round
    # trip (DEF-700). Any non-empty bytes, parseable or not, keep the
    # never-overwrite-content rule below.
    settings_effectively_empty = surface_contract.is_effectively_empty_file(settings_path)
    settings_presence, unreadable_detail = surface_contract.path_presence(settings_path)
    if settings_presence == surface_contract.PRESENCE_UNREADABLE:
        # A parent that denies traversal: nothing can be reconciled or
        # written here, and pathlib's `exists()` answered it per interpreter
        # (DEF-763). The command layer refuses first with the one sentence;
        # a library caller gets the OS's own error, the same on every floor.
        raise PermissionError(unreadable_detail)
    if settings_presence == surface_contract.PRESENCE_PRESENT and not settings_effectively_empty:
        outcome = _reconcile_existing_settings(
            settings_path,
            wire_hooks=wire_hooks,
            profile_name=profile_name,
            repo_root=repo_root,
        )
        settings_hooks_wired = outcome.settings_hooks_wired
        deployed.extend(outcome.deployed)
        # skipped_reason is None only when --wire-hooks merged in place (the
        # file was wired, not skipped). Every other path records a reason.
        if outcome.skipped_reason is not None:
            skipped.append(outcome.skipped_reason)

    else:
        if settings_effectively_empty:
            print(
                "INFO: .claude/settings.json was empty (0 bytes or whitespace); "
                "rewriting it in place with a fresh template.",
                file=sys.stderr,
            )
        settings = _build_settings_json(
            profile_name=profile_name, repo_root=repo_root
        )
        # JSON_SENTINEL_KEY sentinel lets cleanup's orphan-sweep and the
        # harness-config-advisor tooling distinguish harness-deployed
        # settings from hand-edited.
        settings[JSON_SENTINEL_KEY] = True
        # Atomic write: a crash mid-write would leave config_guard reading a
        # truncated JSON every session, which raises JSONDecodeError and exits
        # 1 -- hook bug surfaces on every tool call. atomic_write_text closes
        # the window.
        if (
            settings_effectively_empty
            and not surface_contract.is_effectively_empty_file(settings_path)
        ):
            # The empty file gained content between the check above and this
            # write -- an editor's truncate-then-save landing mid-init. That is
            # content now, and content is never overwritten; the next init
            # takes the preserve path for it.
            print(
                "WARN: .claude/settings.json gained content while init ran; "
                "it was left untouched. Re-run init to reconcile it.",
                file=sys.stderr,
            )
            skipped.append(
                ".claude/settings.json (gained content during init -- "
                "preserved unchanged; re-run init)"
            )
        else:
            atomic_write_text(
                settings_path,
                json.dumps(settings, indent=2, sort_keys=True) + "\n",
            )
            deployed.append(".claude/settings.json")
            # A fresh write lands the full hooks block -- but only the SETTINGS
            # half. If the deploy above skipped a hook source (a package-data
            # regression yields `skipped_source_missing`, which is non-fatal and
            # reported only as an aggregate count), the entries point at nothing.
            # Read the file back rather than asserting from the write.
            settings_hooks_wired = (
                _enforcement_claim_blockers(repo_root, settings_path) == []
            )

    # 3. Deploy skeleton CLAUDE.md
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        skipped.append(_CLAUDE_MD_SKIPPED_MARKER)
    else:
        atomic_write_text(claude_md, _build_claude_md(fp, harness))
        deployed.append("CLAUDE.md")

    # 4. Deploy skeleton ESPALIER_MEMORY.md
    memory_md = repo_root / _MEMORY_FILENAME
    legacy_memory = repo_root / _LEGACY_MEMORY_FILENAME
    if memory_md.exists():
        skipped.append("ESPALIER_MEMORY.md (exists)")
    elif legacy_memory.exists():
        # A repo initialized before the MEMORY.md -> ESPALIER_MEMORY.md rename.
        # Deploying a fresh empty ESPALIER_MEMORY.md would strand the adopter's
        # existing memory in the legacy file (whose name now collides with Claude
        # Code's hardcoded auto-memory MEMORY.md). Nudge; never mutate their
        # tracked file silently.
        skipped.append("ESPALIER_MEMORY.md (legacy MEMORY.md present -- see note)")
        _print_legacy_memory_nudge()
    else:
        atomic_write_text(memory_md, _build_memory_md(fp))
        deployed.append(_MEMORY_FILENAME)

    # 5. Create blueprints directory
    bp_dir = repo_root / "cc" / "blueprints"
    bp_dir.mkdir(parents=True, exist_ok=True)

    # 6. Deploy agents / commands / skills with the three-state marker policy.
    # ``espalier/assets/claude/<kind>/`` is the deploy source-of-truth;
    # ``_deploy_asset_md`` injects the ``espalier:managed`` marker on write so
    # reruns can distinguish harness-deployed copies (safe to regenerate) from
    # user-edited files (must be preserved). Ships the live roster by default
    # while honoring user edits via the marker contract.
    for rel, src in _packaged_md_assets(harness_root):
        dest = repo_root / rel
        action = _deploy_asset_md(src, dest)
        if action == "created":
            deployed.append(rel)
            created.append(rel)
        elif action == "updated_managed":
            deployed.append(rel)
            updated_managed.append(rel)
        elif action == "skipped_no_drift":
            skipped_no_drift_files.append(rel)
        elif action == "skipped_user_file":
            skipped_user_files.append(rel)
            skipped.append(rel + " (user file preserved)")
        elif action == "skipped_source_missing":
            skipped.append(rel + " (source missing)")

    # 7. Render required surface docs (cc/LIVE_SURFACE.md, cc/COMMANDS.md,
    # cc/PACK_MANIFEST.txt). write_required_surface applies the same
    # 3-state policy and returns (rel, action) pairs so init can fold the
    # cc/ surface into its tally.
    surface_actions = write_required_surface(repo_root)
    for rel, action in surface_actions:
        # Fold the cc/ surface into the same ownership tally as the asset loop
        # above: only created/updated_managed count as "deployed"; a
        # skipped_no_drift lands in skipped_no_drift_files (an idempotent re-init
        # would otherwise phantom-count the unchanged surface docs as
        # deployments); a skipped_user_file is preserved and reported once.
        if action == "created":
            deployed.append(rel)
            created.append(rel)
        elif action == "updated_managed":
            deployed.append(rel)
            updated_managed.append(rel)
        elif action == "skipped_no_drift":
            skipped_no_drift_files.append(rel)
        elif action == "skipped_user_file":
            skipped_user_files.append(rel)
            skipped.append(f"{rel} (user file preserved)")

    return {
        "deployed": deployed,
        "skipped": skipped,
        "created": created,
        "updated_managed": updated_managed,
        "skipped_user_files": skipped_user_files,
        "skipped_no_drift": skipped_no_drift_files,
        "managed_orphans": managed_orphans,
        # Did the live settings.json end up with Espalier hooks wired?
        # cmd_init reads this to keep the "Hooks now intercept ..." banner honest.
        "settings_hooks_wired": settings_hooks_wired,
    }


def preview_managed_surface(repo_root: Path) -> dict[str, list[str]]:
    """Classify every packaged managed asset against the tree WITHOUT writing.

    The content oracle ``upgrade`` consults before it says "nothing to do"
    (DEF-726): the same three enumerations ``deploy_harness`` writes from
    (``INIT_HOOK_SCRIPTS`` + ``INIT_TOOL_SCRIPTS``, ``_packaged_md_assets``,
    the cc/ surface renderers) through the same classifiers, with their
    writes switched off. Returns the deploy tally's vocabulary so a reader of
    one can read the other: ``created`` (packaged, absent from the tree),
    ``updated_managed`` (present with the marker, differs from the packaged
    bytes), ``skipped_user_files`` (differs, no marker: preserved),
    ``skipped_no_drift`` and ``source_missing``. The three root files a
    deploy creates when absent and never rewrites when present
    (``.claude/settings.json`` -- also when effectively empty, DEF-700 --
    ``CLAUDE.md`` and ``ESPALIER_MEMORY.md``) are classified on the same
    rule: ``created`` when the deploy would write them, otherwise not
    compared. Not consulted at all: the seed docs (their own stamp-driven
    refresh, which ``upgrade`` runs before the deploy) and the CI gate
    (``install-ci``'s). ``tests/test_cli_deploy.py`` pins that every path in
    ``managed_inventory.get_managed_public_files`` is either classified here
    or one of the packaged root docs, so a new managed surface cannot slip
    past the preview silently.

    Declared caveat: the three cc/ docs render FROM THE TREE. The deploy
    renders them after its asset writes land; this preview renders them
    against the tree as it is, so on a tree that is behind by an asset the
    preview can name a cc/ doc the deploy then finds unchanged, or miss one
    the deploy rewrites. The asset itself is always named, so the verdict
    (something to do) holds and one ``--execute`` converges; only the
    per-doc listing is approximate (DEF-757; FAILURE_MODES 5.25).

    The integrity manifest is NOT this oracle. It answers "did a protected
    file change since the manifest was written", which reads a stale deploy
    with a refreshed manifest as clean (walk 2's three-week-old fusion had a
    current manifest and a ``write_guard.py`` three thousand lines behind the
    engine) and is absent on a tree that never refreshed it. Comparing
    against the packaged bytes answers the question the command's sentence
    makes: would ``--execute`` write anything?
    """
    repo_root = repo_root.resolve()
    harness_root = _espalier_root()
    tally: dict[str, list[str]] = {
        "created": [],
        "updated_managed": [],
        "skipped_user_files": [],
        "skipped_no_drift": [],
        "source_missing": [],
    }
    # The .md half has no per-file source-missing answer (a missing kind
    # directory enumerates as nothing), so a wheel that shipped the hooks but
    # not the bodies would read as "nothing to do" over an empty roster. Name
    # the missing directory as a missing source instead.
    asset_root = harness_root / "espalier" / "assets" / "claude"
    for kind in surface_contract.CLAUDE_SURFACE_KINDS:
        if not (asset_root / kind).is_dir():
            tally["source_missing"].append(f".claude/{kind}/ (packaged bodies)")

    def _fold(rel: str, action: str) -> None:
        if action == "skipped_source_missing":
            tally["source_missing"].append(rel)
        elif action == "skipped_user_file":
            tally["skipped_user_files"].append(rel)
        else:
            tally.setdefault(action, []).append(rel)

    for rel_path in INIT_HOOK_SCRIPTS + INIT_TOOL_SCRIPTS:
        _fold(rel_path, _deploy_managed_py(
            _deploy_source_path(rel_path), repo_root / rel_path, dry_run=True,
        ))
    for rel, src in _packaged_md_assets(harness_root):
        _fold(rel, _deploy_asset_md(src, repo_root / rel, dry_run=True))
    for rel, action in write_required_surface(repo_root, dry_run=True):
        _fold(rel, action)
    # The root files, on the deploy's own rule (steps 2-4 of deploy_harness):
    # written when absent -- settings.json also when effectively empty -- and
    # otherwise left alone, so "present" is not compared and "absent" is a
    # created. A deleted settings.json is the state of an adopter who took
    # init's default gitignore entry and cloned onto a second machine: their
    # hooks are unwired, and this is where upgrade says so.
    settings_path = repo_root / ".claude" / "settings.json"
    settings_presence, unreadable_detail = surface_contract.path_presence(settings_path)
    if settings_presence == surface_contract.PRESENCE_UNREADABLE:
        # Never "would create" on a directory that cannot be searched: this
        # dry run said exactly that, and exited 0, on CPython 3.14 (DEF-763).
        raise PermissionError(unreadable_detail)
    if (
        settings_presence == surface_contract.PRESENCE_ABSENT
        or surface_contract.is_effectively_empty_file(settings_path)
    ):
        tally["created"].append(".claude/settings.json")
    if not (repo_root / "CLAUDE.md").exists():
        tally["created"].append("CLAUDE.md")
    if not (repo_root / _MEMORY_FILENAME).exists() and not (
        repo_root / _LEGACY_MEMORY_FILENAME
    ).exists():
        tally["created"].append(_MEMORY_FILENAME)
    return tally


# ── Deploy template rendering ──────────────────────────────────────────────


def _canonical_template_fingerprint() -> RepoFingerprint:
    """Build a deterministic fingerprint used to render canonical templates.

    The deploy templates that `init` produces depend on the target repo's
    fingerprint (name, languages, profiles, etc.). For documentation /
    snapshot purposes we render against a fixed neutral fingerprint named
    `your-repo` so the output is stable across machines and reads as a
    placeholder rather than as espalier-harness's own metadata.
    """
    return RepoFingerprint(
        repo_name="your-repo",
        repo_root=".",
        languages=["python"],
        profiles=["ci_cd"],
        # A representative adopter layout, so examples/CLAUDE.template.md
        # reads like a real adopter's file rather than a degenerate one. It no
        # longer decides WHETHER the `## Plan Guard` section renders -- that is
        # unconditional for every non-self-host layout -- only which wording
        # the section carries (generic here, `src/`-specific for src_layout).
        architecture={"pattern": "flat"},
    )


def _canonical_template_build_plan() -> BuildPlan:
    """Build a deterministic empty build plan paired with the canonical fp."""
    return BuildPlan(repo_name="your-repo", profiles=["ci_cd"])


def render_canonical_template(subject: str) -> str:
    """Return the canonical deploy-template text for ``subject``.

    `subject` is "claude", "memory", or "changelog". The "claude"/"memory"
    output mirrors what `espalier init` deploys to a fresh user repo, rendered
    against a neutral fingerprint; "changelog" is an on-demand skeleton (not
    init-deployed). Used by the `render-template` CLI subcommand and pinned by
    tests/test_documented_claims.py::TestDeployTemplateSnapshots so the
    snapshots in examples/ cannot drift from the generators.
    """
    if subject == "changelog":
        return _build_changelog_md()
    fp = _canonical_template_fingerprint()
    if subject == "claude":
        return _build_claude_md(fp, _canonical_template_build_plan())
    if subject == "memory":
        return _build_memory_md(fp)
    raise ValueError(f"unknown subject: {subject!r}")


def cmd_render_template(args: argparse.Namespace) -> int:
    """Print the canonical deploy template for `claude`, `memory`, or `changelog`."""
    print(render_canonical_template(args.subject), end="")
    return 0


# Machine-specific or per-install runtime state that must not be committed.
# Module-level single source of truth: the init-gitignore test fixtures import
# this and assert their REQUIRED_IGNORE_PATHS mirrors it
# (test_required_ignore_paths_match_cli_source), so a new entry added here can
# never again silently outrun its fixture coverage.
# ANCHORING (DEF-429): git matches a pattern carrying no leading or embedded
# separator at ANY depth. The test for whether an entry needs a leading slash
# is NOT "does the harness write it only at the root" -- it is "could this
# NAME collide with something the adopter owns".
#   /reports/  -- anchored. A generic English word an adopter plausibly owns:
#     a Django/Rails reports app, a dashboard module, a folder of committed
#     templates. Unanchored, init silently excluded every one of those from
#     `git add -A`, which is the defect.
#   .espalier/, .espalier-state/  -- deliberately NOT anchored. They are the
#     harness's own namespace and cannot collide with adopter content, so
#     any-depth costs nothing and protects more: a hook whose repo root
#     mis-resolves, or an extracted archive sitting inside the tree, still
#     gets its state ignored rather than committed.
#   __pycache__/, *.pyc  -- deliberately NOT anchored: bytecode is unwanted
#     wherever it appears.
# The five entries with an embedded separator (.claude/settings.json,
# cc/blueprints/, ...) are already root-relative under the same git rule.
# `tests/..._default.py::test_required_entry_shapes_are_covered` is the gate:
# a new single-segment entry must be anchored or declared any-depth on purpose.
#: Header line introducing the block ``init`` appends to an adopter's
#: ``.gitignore``. One owner because it had five copies: three in this module
#: (the append path and both ``--no-write-gitignore`` print paths), one in the
#: test that locates the block, and one hand-pasted into ``docs/QUICKSTART.md``
#: -- which is now generated from here by ``scripts/generate_doc_regions.py``.
GITIGNORE_BLOCK_HEADER = "# Espalier-Harness runtime -- generated, never committed"
#: Closes the block the header opens. Written since 2026-09-11 so that
#: ``clean-generated`` can retire the harness's own entries by their exact
#: extent instead of inferring it from content: without an end marker, a line
#: the adopter appended directly under the block, or an entry a later release
#: drops from REQUIRED_GITIGNORE, is indistinguishable from the block's edge
#: (``cleanup._retire_gitignore_block`` says how a footer-less legacy block is
#: read).
GITIGNORE_BLOCK_FOOTER = "# end Espalier-Harness runtime"

REQUIRED_GITIGNORE = (
    ".claude/settings.json",   # interpreter name detected per machine
    ".espalier/",              # integrity manifest, per-install
    ".espalier-state/",        # stop_gate session flags
    "/reports/",               # fingerprint + harness_config outputs
    "cc/blueprints/",          # cognitive blueprint state
    "cc/_cold/",               # plan records the reset verb demotes
                               #   (execution_plan.py reset); before this
                               #   entry every reset the session banner
                               #   prescribed left a `??` in git status
    "cc/_working_summary.md",  # live working-summary doc, per-machine disposable
    "__pycache__/",            # compiled bytecode (cf. release_noise
    "*.pyc",                   #   TRANSIENT_DIRS); else an adopter
                               #   commits hook bytecode on day one
    ".claude/*.new",           # re-init settings.json.new render artifact
    ".claude/*.bak",           # merge-settings settings.json.bak backup
    ".claude/*.bak.*",         # ...and its .bak.1/.bak.2 siblings, which the
                               #   glob above does NOT match (driven). Both
                               #   merge and --rewire-interpreter fall back to
                               #   a numbered backup rather than clobber an
                               #   existing pristine one, and a settings backup
                               #   can carry the operator's `env` block.
    # Anchored, and the anchor is load-bearing: driven against real git, the
    # un-anchored `task-packs/` also swallows an adopter's own
    # `src/vendor/task-packs/`, which is DEF-429 reintroduced under a new
    # name. `init` seeds a router CLAUDE.md here and the deployed
    # /implement-pack already calls this directory gitignored local state --
    # before this entry that instruction was FALSE on every adopter tree,
    # and each of them committed a bare directory they never asked for.
    "/task-packs/",            # pack drafts: local working state, per-machine
)


def _gitignore_key(line: str) -> str:
    """Normalize a .gitignore line for equality against a required entry.

    Stripping the leading anchor and the trailing directory slash makes the
    anchored and unanchored spellings of one directory compare equal, which
    is what the upgrade path needs: every tree initialized before DEF-429
    carries the bare ``reports/``, and that pattern is strictly BROADER than
    ``/reports/`` -- it excludes the repo-root directory the harness needs
    excluded, and more besides -- so it genuinely satisfies the requirement.
    Without this, anchoring would append three duplicate lines to every
    existing adopter's .gitignore on the next re-init.

    Deliberately NOT a substring or prefix relation: ``reports/sub/`` still
    normalizes to ``reports/sub`` and does not satisfy ``/reports/`` -- a
    narrower sub-path must never be read as covering the broad ignore the
    harness needs.

    The contents form ``X/*`` normalizes with ``X/`` for the same reason the
    anchored and unanchored spellings do: both keep the directory's contents
    out of git, which IS the requirement. They differ only in whether a later
    ``!`` line can re-include one child -- and a tree carrying that pair has
    an operator who wrote the negation on purpose. Treating ``X/*`` as
    unsatisfied would append ``/X/`` beneath their negation and silently kill
    it, converting a required-state check into the destructive edit it exists
    to avoid. Measured on this very repo: without this, ``init .`` on the
    source checkout reports ``/task-packs/`` missing and appending it makes
    the tracked ``!task-packs/CLAUDE.md`` inert.

    Since DEF-635 this key answers the coverage question only as the
    FALLBACK, when git cannot (``_git_covered_entries`` returns ``None``);
    otherwise it serves the ``unanchored`` advisory, which is a question
    about SPELLING and stays a string compare. A spelling compare cannot see
    that ``*.py[cod]`` covers ``*.pyc`` or that ``cc/_working_summary*``
    covers ``cc/_working_summary.md``, and it read a trailing-comment line
    (``*.pyc  # note`` -- pattern text to git, which has no trailing
    comments) the same way git does, as absent.
    """
    return line.strip().removesuffix("/*").strip("/")


#: The token a derived probe path uses for the part of a required entry a
#: glob leaves open. Synthetic on purpose: a token carrying a word is a token
#: an adopter's glob can swallow, and the first cut carried two -- an adopter
#: of a tool named espalier plausibly ignores ``*espalier*``, and under that
#: one line eight of twelve required entries read as covered (the failure-mode
#: pass drove it). ``_GITIGNORE_CONTROL_PROBE`` is the backstop for the
#: patterns no token escapes.
_GITIGNORE_PROBE_TOKEN = "zq9vzx3k"

#: A probe NO required entry covers, sent beside the real ones. When git
#: excludes it, the adopter's file swallows arbitrary paths (``*``, ``zq*``)
#: and the real probes' answers say nothing about coverage -- so the oracle
#: declines to answer and the labelled fallback stands in, rather than reading
#: every glob entry as covered. A probe with no negative control cannot tell
#: silence from a null (``memory/a-probes-silence-is-not-a-null.md``).
_GITIGNORE_CONTROL_PROBE = (
    f"{_GITIGNORE_PROBE_TOKEN}-control/{_GITIGNORE_PROBE_TOKEN}-control"
)


def _entry_is_any_depth(entry: str) -> bool:
    """Does git float ``entry`` to every depth?

    git roots a pattern that carries a leading OR embedded separator; only a
    single-segment pattern (a trailing slash does not count) matches at any
    depth -- the same rule ``_ignore_pattern_matches`` applies to the
    tracked-path question.
    """
    return "/" not in entry.rstrip("/")


def _entry_probe_paths(entry: str) -> tuple[str, ...]:
    """Derive the paths git must exclude for ``entry`` to count as covered.

    Derived from the entry's SHAPE, never hand-listed per entry, so a new
    ``REQUIRED_GITIGNORE`` member gets its probes for free and
    ``test_every_required_entry_covers_its_own_probes`` reds on a shape this
    derivation does not model instead of letting it go unchecked.

    * a directory entry (``.espalier/``, ``/reports/``) probes one file
      INSIDE it -- the requirement is that the directory's contents stay out
      of git, which the contents form ``X/*`` also satisfies;
    * a glob (``*.pyc``, ``.claude/*.bak.*``) probes one concrete instance,
      the token standing in for each ``*``;
    * a plain path (``.claude/settings.json``) probes itself.

    An any-depth entry also probes one level down: ``*.pyc`` means bytecode
    ANYWHERE, so an adopter's root-only ``/*.pyc`` must read as not covering
    it -- their ``src/pkg/mod.pyc`` would still be committed.
    """
    token = _GITIGNORE_PROBE_TOKEN
    if entry.endswith("/"):
        leaf = entry.strip("/") + "/" + token
    else:
        leaf = entry.lstrip("/").replace("*", token)
    probes = [leaf]
    if _entry_is_any_depth(entry):
        probes.append(f"{token}/{leaf}")
    return tuple(probes)


#: Environment keys that redirect git at ANOTHER repository. Dropped before
#: the hermetic check, or a ``doctor`` run from inside a git hook (where git
#: exports them) would init and query the adopter's own repository instead
#: of the scratch one. The same six ``tests/_git_oracle.py`` strips.
_GIT_REDIRECT_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
)


def _git_covered_entries(
    gitignore: Path, entries: tuple[str, ...], *, fold: bool
) -> frozenset[str] | None:
    """Ask git which required ``entries`` the root ``.gitignore`` already covers.

    ``fold`` is the ADOPTER repository's ``core.ignorecase`` (``_git_ignorecase``),
    passed in because ``git init`` reads that setting off the filesystem it
    inits on -- the scratch directory's, which on a Mac is case-insensitive
    while the adopter's volume may not be. Left to the scratch default,
    ``REPORTS/`` read as covering ``/reports/`` on this Mac and as missing on
    Linux CI for the same file; the same fold every sibling in this family
    (``_tracked_conflicts``, ``_untracked_conflicts``) applies.

    ``None`` when git cannot answer -- no binary, an init or check-ignore
    that fails or hangs, a scratch directory that cannot be made -- so the
    caller can fall back to the line-exact compare and SAY so. An empty set
    is a real answer: git ran and excluded nothing.

    Hermetic on purpose. The question is "does THIS FILE keep the harness's
    state out of everyone's commits", so the check runs in a throwaway
    repository holding only a byte-copy of the adopter's root ``.gitignore``:

    * ``git init --template=`` copies no template, so there is no
      ``.git/info/exclude`` -- the adopter's real one is per-machine and
      protects no collaborator's clone;
    * ``-c core.excludesFile=<absent>`` silences the operator's global
      excludes for the same reason (``~/.config/git/ignore`` is consulted
      only while that key is unset, so pointing it at nothing covers both);
    * ``_GIT_REDIRECT_ENV`` is dropped from the environment;
    * ``--no-index`` asks about the patterns alone, so a path the adopter
      already tracks (the DEF-11 state ``_tracked_conflicts`` reports) still
      gets a coverage verdict.

    The bytes are copied rather than the decoded text so git reads exactly
    what it reads in the adopter's tree -- CRLF, a BOM, a non-UTF-8 byte.
    Nested ``.gitignore`` files are not consulted: ``init`` appends to the
    root file, and a nested one that already covers an entry costs the
    adopter one redundant root line, never a leak. ``TimeoutExpired`` is in
    the except tuple BECAUSE ``timeout=`` is set -- same posture as
    ``_tracked_conflicts``. Scratch cleanup errors are ignored: a verdict git
    already gave must not become ``None`` because ``rmtree`` tripped on a
    Windows handle after the fact.
    """
    if not entries:
        return frozenset()
    probes = {entry: _entry_probe_paths(entry) for entry in entries}
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REDIRECT_ENV}
    try:
        gi_bytes = gitignore.read_bytes() if gitignore.exists() else b""
    except OSError:
        gi_bytes = b""
    try:
        with tempfile.TemporaryDirectory(
            prefix="espalier-check-ignore-", ignore_cleanup_errors=True,
        ) as scratch:
            scratch_root = Path(scratch)
            init = subprocess.run(
                ["git", "init", "-q", "--template=", str(scratch_root)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False, timeout=30, env=env,
            )
            if init.returncode != 0:
                return None
            (scratch_root / ".gitignore").write_bytes(gi_bytes)
            stdin = "".join(
                path + "\0" for paths in probes.values() for path in paths
            ) + _GITIGNORE_CONTROL_PROBE + "\0"
            proc = subprocess.run(
                ["git", "-C", str(scratch_root),
                 "-c", f"core.excludesFile={scratch_root / 'no-global-excludes'}",
                 "-c", f"core.ignorecase={'true' if fold else 'false'}",
                 "check-ignore", "--no-index", "-z", "--stdin"],
                input=stdin, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False, timeout=30, env=env,
            )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    # 0: at least one path is excluded; 1: none is; anything else is an error.
    if proc.returncode not in (0, 1):
        return None
    excluded = {path for path in proc.stdout.split("\0") if path}
    if _GITIGNORE_CONTROL_PROBE in excluded:
        return None
    return frozenset(
        entry for entry, paths in probes.items()
        if all(path in excluded for path in paths)
    )


def _entry_covers_an_open_set(entry: str) -> bool:
    """Does ``entry`` match paths beyond the ones that exist right now?

    The discriminator for what to do about a collision with a tracked path.
    A directory pattern or a glob keeps matching files created later -- the
    harness's own generated state among them -- so ignoring it still buys
    protection even when something tracked already sits inside. An entry
    naming one concrete path does not: if that path is tracked, ignoring it
    protects nothing at all, and only produces the both-tracked-and-ignored
    state. Hence directories and globs are written; exact tracked paths are
    withheld.
    """
    return entry.endswith("/") or any(c in entry for c in "*?[")


def _ignore_pattern_matches(entry: str, rel_path: str, *, fold: bool = False) -> bool:
    """Would gitignore pattern ``entry`` exclude repo-relative ``rel_path``?

    Scoped to the pattern shapes ``REQUIRED_GITIGNORE`` actually contains:
    root-anchored directories (``/reports/``), root-relative files and
    globs (``.claude/settings.json``, ``.claude/*.new``), and unanchored
    any-depth patterns (``__pycache__/``, ``*.pyc``).
    ``test_required_entry_shapes_are_covered`` pins that no entry escapes
    those shapes, so a future addition cannot silently go unchecked here.
    Deliberately NOT a general gitignore engine -- negation, ``**`` and
    character classes are absent from the tuple and are not handled.
    ``test_required_entry_shapes_are_covered`` is the gate that keeps them
    absent, so an entry of an unhandled shape reds instead of silently
    going unchecked.

    ``fold`` casefolds both sides, for hosts where git itself is
    case-insensitive (``core.ignorecase``, the default on macOS and
    Windows). Without it the check misses ``Reports/q4.md`` against
    ``/reports/`` and silently creates the very state it exists to prevent.
    """
    core = entry.strip("/")
    is_dir = entry.endswith("/")
    if fold:
        core = core.casefold()
        rel_path = rel_path.casefold()
    pat_segs = core.split("/")
    path_segs = rel_path.split("/")
    # git roots a pattern that carries a leading OR embedded separator;
    # only a single-segment pattern floats to any depth.
    #
    # Both branches below accept a path LONGER than the pattern, not just an
    # exact-length one. When a pattern matches a path COMPONENT and that
    # component is a directory, git excludes everything beneath it -- so
    # `.claude/*.new` matches `.claude/x.new/y`, and `*.pyc` matches
    # `src/foo.pyc/bar`. Checking only the leaf missed those, reporting "no
    # conflict" and letting the entry be written over a tracked path: the
    # DEF-11 state, produced by the check meant to prevent it. `zip` stops at
    # the pattern's length, which is exactly the prefix comparison wanted.
    if entry.startswith("/") or len(pat_segs) > 1:
        return (
            len(path_segs) > len(pat_segs) if is_dir
            else len(path_segs) >= len(pat_segs)
        ) and all(fnmatch.fnmatchcase(a, b)
                  for a, b in zip(path_segs, pat_segs))
    if is_dir:
        return core in path_segs[:-1]
    # Any component, not just the basename -- a matched directory takes its
    # contents with it.
    return any(fnmatch.fnmatchcase(seg, core) for seg in path_segs)


def _git_ignorecase(repo_root: Path) -> bool:
    """Whether git itself matches paths case-insensitively here.

    `core.ignorecase` is TRUE by default on macOS and Windows. Hoisted into
    one owner because two functions need it and the first cut had only one of
    them folding -- a sister-site gap 60 lines wide, in a predicate whose own
    docstring says an unfolded match "silently creates the very state it
    exists to prevent".

    False on any failure: an unfolded match under-reports, which is the safe
    direction for a diagnostic that must never abort a completed deploy.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "config", "--type=bool",
             "core.ignorecase"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=30,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return proc.stdout.strip() == "true"


def _is_harness_owned(rel: str, managed: set[str], *, fold: bool) -> bool:
    """True when ``rel`` is the harness's own output rather than the adopter's.

    Path-exact membership is NOT enough, and assuming it was is what made the
    first cut noisy on an `upgrade`: `cc/blueprints/*.json`, `.espalier-state/*`
    and scanner reports are generated at RUNTIME, so no inventory can list
    them, and naming a blueprint chain back to the operator as "your
    uncommitted work" -- with advice to commit it -- is the §C19 noise that
    gets an advisory switched off. The prefix arm reads the inventory's
    local-runtime prefixes (``managed_inventory.get_local_runtime_prefixes``),
    the same owner ``clean-generated``'s accounting reads, so the two cannot
    disagree about whose a runtime file is.

    The third arm is the render artifacts: ``settings.json.new`` (what init
    itself writes beside a settings.json it declines to overwrite) and the
    ``.bak`` copies merge-settings takes. Driven on the Windows host (walk 2,
    W2-32): one init run announced the ``.new`` render and, seven lines later,
    reported that same path back as the adopter's uncommitted work with advice
    to commit it -- a file ``REQUIRED_GITIGNORE`` deliberately ignores. Exact
    names via ``managed_inventory.is_render_artifact``, never a ``.claude/*.new``
    prefix: a ``.new`` the adopter authored is theirs and must be named
    (DEF-737).
    """
    probe = rel.casefold() if fold else rel
    if probe in ({m.casefold() for m in managed} if fold else managed):
        return True
    if is_render_artifact(probe):
        return True
    return probe.startswith(_HARNESS_OWNED_PREFIXES)


#: The harness's OWN runtime roots, read from the inventory (one owner, shared
#: with cleanup's accounting). Each is covered by a REQUIRED_GITIGNORE entry;
#: every other required entry (`/task-packs/`, `__pycache__/`, `*.pyc`,
#: `.claude/*.new|bak`) covers content an adopter can legitimately author, so
#: a hit there is theirs and must be disclosed.
_HARNESS_OWNED_PREFIXES: tuple[str, ...] = get_local_runtime_prefixes()


def _untracked_conflicts(
    repo_root: Path, entries: list[str]
) -> dict[str, list[str]]:
    """Entries about to hide work the adopter has written but not committed.

    The complement of ``_tracked_conflicts``, which answers from
    ``git ls-files`` and therefore cannot see an uncommitted draft. Only
    open-set entries qualify: a one-concrete-path entry is the harness's own
    file by construction, so a match there is not the adopter's work.

    ``--exclude-standard`` is what makes this precise rather than noisy -- it
    already honours the adopter's EXISTING ignore rules, so a file they have
    themselves chosen to ignore is not reported back at them. It must run
    BEFORE the append, or the entry being added would suppress the very files
    this exists to name.

    Degrades to empty on any git failure, matching the posture of every other
    diagnostic here: init has deployed by now and must not abort on advice.
    """
    open_set = [e for e in entries if _entry_covers_an_open_set(e)]
    if not open_set:
        return {}
    # Same case-folding the sibling applies, for the same reason and on the
    # same default: on macOS/Windows `core.ignorecase` is true, so git hides
    # `Task-Packs/draft.md` under `/task-packs/` while an unfolded match here
    # reports nothing -- the disclosure would go silent on precisely the
    # platform most operators are sitting on.
    fold = _git_ignorecase(repo_root)
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repo_root, capture_output=True, text=True,
            # errors= AND ValueError, together: a filename that is not valid
            # UTF-8 (a latin-1 name from an old checkout, a `mv` off a mounted
            # share) makes text-mode decoding raise UnicodeDecodeError, which
            # is a ValueError and would sail past an (OSError,
            # SubprocessError) tuple. This runs AFTER init has deployed every
            # file, so an escape means a repo with hooks wired, no .gitignore,
            # no summary banner, and an identical failure on every re-run --
            # the exact shape this repo has already paid for once. The
            # immediate sibling `_tracked_conflicts` carries both defenses.
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    untracked = [p for p in result.stdout.split("\0") if p]
    if not untracked:
        return {}
    # Only the ADOPTER's work belongs in this report. The harness's own
    # freshly-written files are untracked too -- integrity.json,
    # repo_fingerprint.json, the seeded router -- and naming those back to
    # the operator as "your uncommitted work" is precisely the noise (§C19)
    # that gets an advisory switched off; measured, the first cut reported
    # five of them. Built from the harness's WRITE inventory, deliberately
    # not from `surface_contract.is_local_only`: that predicate answers
    # "must this never ship?", which is True for an adopter's own pack too,
    # so it would suppress the one file this report exists to name.
    from espalier import managed_inventory as _mi
    managed = {
        str(r).replace("\\", "/")
        for r in (
            *_mi.get_seed_docs(),
            *_mi.local_runtime_rel_paths(),
            *_mi.get_local_only_files(),
            *_mi.get_generated_docs(),
        )
    }
    conflicts: dict[str, list[str]] = {}
    for entry in open_set:
        hits = [
            p for p in untracked
            if _ignore_pattern_matches(entry, p, fold=fold)
            and not _is_harness_owned(p, managed, fold=fold)
        ]
        if hits:
            conflicts[entry] = sorted(hits)
    return conflicts


def _print_untracked_conflicts(
    conflicts: dict[str, list[str]], *, written: bool
) -> None:
    """Name the uncommitted work an entry hides (or would hide), and the way out.

    ``written`` is not cosmetic. This is reachable from three paths that did
    NOT touch the adopter's .gitignore -- `init --no-write-gitignore`,
    `upgrade` dry-run (the documented default), and a withheld entry -- and
    on those an accomplished-fact tense tells the operator their working tree
    already changed when it did not. The sibling `_print_tracked_conflicts`
    carries the same wording and the same latent bug; this one is newly
    reachable from a preview, so it is fixed here first.
    """
    if not conflicts:
        return
    print()
    if written:
        print("NOTE: the entries below cover files you have written but not "
              "committed yet. They were still written --")
        print("nothing is deleted and nothing is blocked -- but these will "
              "stop appearing in `git add -A`:")
    else:
        print("NOTE: the entries below would cover files you have written "
              "but not committed yet. Nothing has changed --")
        print("but if you apply them, these will stop appearing in "
              "`git add -A`:")
    print()
    for entry, hits in conflicts.items():
        shown = ", ".join(hits[:3])
        more = f", (+{len(hits) - 3} more)" if len(hits) > 3 else ""
        print(f"  {entry}  -- you have uncommitted: {shown}{more}")
    print()
    print("Commit them first if you want them in history, or use "
          "`git add -f <path>` from here on.")


def _tracked_conflicts(
    repo_root: Path, entries: list[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Split ``entries`` by how they collide with paths git already tracks.

    Returns ``(withheld, shared)`` -- two different collisions that want two
    different answers, which is the correction driving this signature.

    ``withheld``: the entry names one concrete path and that path IS tracked --
    ``.claude/settings.json`` against a repo that committed its own. Ignoring it
    cannot protect anything (git ignores nothing already tracked) and produces the
    both-tracked-and-ignored state, which `git check-ignore` will not even report
    because it skips indexed paths. These are dropped from the append.

    ``shared``: the entry covers an OPEN set -- a directory or a glob -- that the
    adopter partly occupies: ``/reports/`` against a committed
    ``reports/2025-summary.md``, or ``*.pyc`` against one legacy committed bytecode
    file. Not the same pathology, and verified by driving git rather than by reading
    it: the adopter's committed file goes on staging and committing exactly as
    before, because gitignore governs untracked paths only. Withholding here is the
    worse trade -- it leaves the harness's own generated state
    (``repo_fingerprint.json``, the hook bytecode ``*.pyc`` exists to stop) headed
    for the adopter's shared history, the exact leak this tuple exists to prevent.
    So the entry IS written, and the operator is told the one real consequence: a
    NEW untracked file it covers will not stage.

    Both are empty when git cannot answer -- a missing binary, a non-git host, a
    failing or slow invocation. init has deployed every file by the time this runs
    and must never abort on a diagnostic, matching the OSError posture the rest of
    ``_handle_gitignore`` takes. ``TimeoutExpired`` is in the except tuple BECAUSE
    ``timeout=`` is set; the two belong to one edit, and adding the timeout without
    the handler would convert a degrade-to-empty into a crash after every file is
    already deployed.
    """
    if not entries:
        return {}, {}
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=120,
        )
        # git itself is case-insensitive on macOS/Windows checkouts; match it,
        # or the check misses `Reports/q4.md` against `/reports/` and silently
        # creates the state it exists to prevent.
        case_proc = subprocess.run(
            ["git", "-C", str(repo_root), "config", "--type=bool",
             "core.ignorecase"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=30,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}, {}
    if proc.returncode != 0:
        return {}, {}
    fold = case_proc.stdout.strip() == "true"
    tracked = [p for p in proc.stdout.split("\0") if p]
    if not tracked:
        return {}, {}
    withheld: dict[str, list[str]] = {}
    shared: dict[str, list[str]] = {}
    for entry in entries:
        hits = [p for p in tracked
                if _ignore_pattern_matches(entry, p, fold=fold)]
        if not hits:
            continue
        bucket = shared if _entry_covers_an_open_set(entry) else withheld
        bucket[entry] = hits
    return withheld, shared


def _print_tracked_conflicts(
    withheld: dict[str, list[str]], shared: dict[str, list[str]]
) -> None:
    """Report both collision kinds: the entries not written because the repo
    already tracks them, and the directories the repo shares with the harness."""
    def _sample(hits: list[str]) -> str:
        shown = ", ".join(hits[:3])
        return shown + (f", (+{len(hits) - 3} more)" if len(hits) > 3 else "")

    if withheld:
        print()
        n = len(withheld)
        print(f"WARN: {plural(n, 'required .gitignore entry', 'required .gitignore entries')} "
              f"NOT written -- this repo already tracks the path itself.")
        print("Ignoring an already-tracked path protects nothing and leaves it "
              "BOTH tracked and ignored, a state `git check-ignore`")
        print("does not report (it skips indexed paths), so nothing downstream "
              "would tell you.")
        print()
        for entry, hits in withheld.items():
            print(f"  {entry}  -- already tracked: {_sample(hits)}")
        print()
        print("To hand these paths to the harness, untrack them first, then "
              "re-run init:")
        # Derived from the matched paths, not from the pattern: the pattern
        # spelling is not always a usable pathspec, and `--` keeps a path that
        # looks like an option (or a glob) out of the operator's shell.
        for hits in withheld.values():
            for hit in hits:
                # shlex.quote as well as `--`: the guard keeps a path that
                # looks like an option out of the command, the quoting keeps a
                # path with a space from word-splitting into two pathspecs.
                print(f"  git rm --cached -- {shlex.quote(hit)}")
        print("Otherwise keep them as they are -- the harness will not manage "
              "a path you already own.")

    if shared:
        print()
        n = len(shared)
        print(f"NOTE: {plural(n, 'entry', 'entries')} below also "
              f"{'covers' if n == 1 else 'cover'} content you already track. "
              f"{'It was' if n == 1 else 'They were'} still written -- your")
        print("committed files are unaffected (git ignores nothing already "
              "tracked) and the harness's generated state stays out of your "
              "history.")
        print()
        for entry, hits in shared.items():
            print(f"  {entry}  -- you also track: {_sample(hits)}")
        print()
        print("One consequence to know: a NEW file matching these will not "
              "stage. Use `git add -f <path>` for it, or drop the entry")
        print("and keep the harness's outputs out of git some other way.")


class GitignoreStatus(NamedTuple):
    """Read-only verdict on a repo's required ``.gitignore`` entries.

    Extracted out of ``_handle_gitignore`` (DEF-551, ledger §C6) so a
    NON-MUTATING caller can ask the question. Before this, the only code that
    ever told an adopter a required entry was missing lived on the
    ``init``/``upgrade`` write path -- so an adopter who ran ``init`` once,
    dismissed the WARN, and later ran ``doctor`` had no read-only command that
    would mention it again.

    Every field is computed, never printed. ``_handle_gitignore`` owns the
    operator-facing rendering and the append; this owns the facts.

    * ``exists`` -- whether a ``.gitignore`` file is present at all.
    * ``missing`` -- required entries the file does not cover: git's answer
      (``_git_covered_entries``) when git can give one, else the line-exact
      spelling compare. ``oracle`` says which.
    * ``unanchored`` -- entries present only in the pre-anchoring bare
      spelling (matches at every depth; DEF-429).
    * ``withheld`` -- entries in ``missing`` that git already TRACKS, so
      writing them would strand the path in the tracked-and-ignored state
      (DEF-11). Withheld entries remain in ``missing``: the required state is
      genuinely not reached.
    * ``shared`` -- tracked paths that collide with a required entry.
    * ``oracle`` -- ``"git"`` when ``missing`` is git's own verdict on the
      file, ``"line-exact"`` when git could not answer and a spelling compare
      stood in (DEF-635: that compare reads a broader pattern that already
      covers an entry as absent, so a renderer should say so). No default on
      purpose: a constructor that omits it would silently claim the stronger
      answer, and a fixture copied from a test does exactly that.

    ``withheld`` and ``shared`` keep ``_tracked_conflicts``'s own
    ``dict[str, list[str]]`` shape -- entry -> colliding tracked paths. They
    are NOT flattened to names: ``_print_tracked_conflicts`` reads
    ``.items()``, and collapsing them to keys drops the paths it prints.
    """

    exists: bool
    missing: tuple[str, ...]
    unanchored: tuple[str, ...]
    withheld: dict[str, list[str]]
    shared: dict[str, list[str]]
    oracle: str

    @property
    def ok(self) -> bool:
        """True when nothing is required of the operator."""
        return not self.missing and not self.unanchored


def _read_gitignore_text(gitignore: Path) -> str:
    """Read ``.gitignore`` the way the write side spells it.

    A bare ``read_text()`` uses the locale codec (cp1252 on Windows) and raises
    on a ``.gitignore`` with non-ASCII bytes. A file that exists but cannot be
    READ (a directory in its place, a permission wall) degrades to "" so every
    required entry reads as absent -- the safe direction.
    """
    try:
        return (
            gitignore.read_text(encoding="utf-8", errors="replace")
            if gitignore.exists() else ""
        )
    except OSError:
        return ""


def gitignore_status(repo_root: Path) -> GitignoreStatus:
    """Compute the required-.gitignore verdict for ``repo_root``. Pure.

    Runs no writes and prints nothing, so ``doctor`` and any other read-only
    surface can call it. ``_handle_gitignore`` calls it too, which is what
    keeps the mutating and reporting paths from drifting apart.
    """
    gitignore = repo_root / ".gitignore"
    gi_text = _read_gitignore_text(gitignore)
    gi_keys = {_gitignore_key(ln) for ln in gi_text.splitlines()}

    # Coverage is git's question, so git answers it (DEF-635). The spelling
    # compare it replaces read `*.pyc` as absent from every tree carrying
    # GitHub's stock Python template (`*.py[cod]`, which covers it) and
    # `cc/_working_summary.md` as absent beside `cc/_working_summary*` -- a
    # read-only diagnostic crying wolf on two of the three entries it named on
    # this very repo, and `init` appending a redundant line on the strength of
    # it. The compare stays as the fallback for a host where git cannot
    # answer; it is line-exact rather than substring so a narrower sub-path
    # (`reports/sub/`) never reads as the broad ignore the harness needs, and
    # it keys through _gitignore_key so the bare pre-anchoring spelling still
    # satisfies the anchored requirement (see that docstring).
    covered = _git_covered_entries(
        gitignore, REQUIRED_GITIGNORE, fold=_git_ignorecase(repo_root),
    )
    if covered is None:
        oracle = "line-exact"
        missing = [
            entry for entry in REQUIRED_GITIGNORE
            if _gitignore_key(entry) not in gi_keys
        ]
    else:
        oracle = "git"
        missing = [entry for entry in REQUIRED_GITIGNORE if entry not in covered]

    gi_lines_raw = {ln.strip() for ln in gi_text.splitlines()}
    # Disjoint from `missing` by construction, as it was when both were
    # spelling questions: with `reports/` then `!reports/`, git says missing
    # while the spelling says bare-present, and without this clause init
    # printed "Nothing was rewritten" and appended `/reports/` in one breath.
    unanchored = [
        entry for entry in REQUIRED_GITIGNORE
        if entry.startswith("/")
        and entry not in missing
        and entry not in gi_lines_raw
        and _gitignore_key(entry) in gi_keys
    ]

    withheld, shared = _tracked_conflicts(repo_root, missing)
    return GitignoreStatus(
        exists=gitignore.exists(),
        missing=tuple(missing),
        unanchored=tuple(unanchored),
        withheld=withheld,
        shared=shared,
        oracle=oracle,
    )


def _handle_gitignore(
    repo_root: Path,
    *,
    write_gitignore: bool,
    rerun_hint: str = (
        "Rerun without --no-write-gitignore to append automatically "
        "(default)."
    ),
) -> list[str]:
    """Compute (and optionally append) the required .gitignore entries.

    Separated from cmd_init so the line-exact membership check is unit-testable
    without a full init. Returns the still-missing entries so the caller's
    final-line WARN stays in sync; prints the WARN/append block as a side
    effect.
    """
    # Gitignore protection runs regardless of whether .gitignore exists; a
    # fresh repo with no .gitignore would otherwise get zero guidance and
    # `git add -A` after init would stage machine-specific runtime state. The
    # required-ignore set is a constant; .gitignore presence only affects how
    # we phrase the output, not whether we emit it.
    gitignore = repo_root / ".gitignore"

    # One computation, shared with the read-only surfaces (DEF-551). Everything
    # below this line is rendering and the append; the facts come from
    # gitignore_status so `doctor` and `init` can never disagree about them.
    status = gitignore_status(repo_root)
    needs_gitignore = list(status.missing)

    # DEF-635: the read-only `doctor` qualifies a spelling-compare verdict;
    # this is the path that APPENDS on it, so it must say so too.
    if needs_gitignore and status.oracle != "git":
        print()
        print("NOTE: git could not be asked, so the required entries were "
              "matched by spelling. A broader pattern you already carry "
              "(`*.py[cod]` for `*.pyc`) reads as missing under that check "
              "and is appended beside it -- harmless, but yours to trim.")

    # A tree initialized before the anchoring fix is satisfied by the bare
    # spelling (see _gitignore_key), so it would otherwise carry DEF-429
    # forever and never hear about it -- re-running init is exactly when the
    # adopter is listening. Say it once; do not rewrite their file, because
    # the bare form may be what they meant.
    unanchored = list(status.unanchored)
    if unanchored:
        print()
        print(f"NOTE: {plural(len(unanchored), 'entry', 'entries')} in your "
              ".gitignore predates a fix and matches at EVERY depth:")
        print()
        for entry in unanchored:
            bare = entry.strip("/")
            print(f"  {bare}/  -- also excludes any src/**/{bare}/ you own; "
                  f"the harness only needs {entry}")
        print()
        print("Nothing was rewritten -- if the broad form is what you meant, "
              "keep it. Otherwise add the leading slash.")

    # OWNERSHIP (DEF-11): never ignore a path the host already tracks. git
    # goes on tracking it, so the file lands in the both-tracked-and-ignored
    # state -- and the one diagnostic an adopter reaches for, git
    # check-ignore, skips indexed paths unless --no-index, so it reports
    # nothing. Withhold the entry and hand over the remedy instead. The
    # withheld entries stay in the return value: the harness's required
    # state is genuinely not reached, so the caller's closing reminder
    # should still fire.
    withheld, shared = status.withheld, status.shared
    if withheld or shared:
        _print_tracked_conflicts(withheld, shared)
    # `_tracked_conflicts` answers from `git ls-files`, so it is blind to work
    # the adopter has WRITTEN but not committed -- and that is the common
    # mid-flight state, not an edge case. Measured on a driven tree: an
    # adopter holding an uncommitted pack draft got no
    # disclosure at all, the draft silently stopped staging on the next
    # `git add -A`, and the entry that caused it never appeared in the output
    # (the append reports a COUNT, not the names). The operator accepted this
    # cost explicitly as a DISCLOSED one, so it must not be reachable in
    # silence. Runs BEFORE the append, because afterwards the files are
    # ignored and `--exclude-standard` would no longer list them.
    _print_untracked_conflicts(
        _untracked_conflicts(repo_root, needs_gitignore),
        written=write_gitignore,
    )
    writable = [e for e in needs_gitignore if e not in withheld]

    if writable:
        if write_gitignore:
            block = (
                f"\n{GITIGNORE_BLOCK_HEADER}\n"
                + "\n".join(writable)
                + f"\n{GITIGNORE_BLOCK_FOOTER}\n"
            )
            try:
                with open(gitignore, "a", encoding="utf-8") as fh:
                    fh.write(block)
            except OSError as exc:
                # init has already deployed every file and wired every hook by
                # the time this runs. A .gitignore that cannot be appended to
                # -- a dangling symlink into a not-yet-cloned dotfiles dir, a
                # directory in its place, a full disk -- is a ONE-LINE manual
                # step, not a reason to abort a successful install with a bare
                # errno and no success banner. Before this guard, init exited 1
                # after deploying 96 files, the "What just happened" banner
                # never printed, and every re-run failed the same way.
                # Degrade to exactly the guidance --no-write-gitignore gives.
                print()
                print(f"WARN: could not update .gitignore ({exc.strerror}). "
                      "The harness writes machine-specific runtime state that "
                      "should not be committed. Add these entries manually:")
                print()
                print(GITIGNORE_BLOCK_HEADER)
                for entry in writable:
                    print(entry)
                print(GITIGNORE_BLOCK_FOOTER)
                print()
            else:
                print(f"\nWrote {len(writable)} entries to .gitignore")
                # Written, so nothing is STILL missing -- except any entry
                # withheld above because the host already tracks that exact
                # path; that one IS still missing and needs the operator.
                # Returning the pre-write list here is what forced the caller
                # to gate its closing reminder on `not write_gitignore` --
                # which then swallowed the reminder on the failure path above,
                # where it matters most.
                needs_gitignore = list(withheld)
        else:
            print()
            if not gitignore.exists():
                print("WARN: This repo has no .gitignore. The harness writes "
                      "machine-specific runtime state that should not be "
                      "committed. Create a .gitignore with at minimum:")
            else:
                print("WARN: Add these entries to your .gitignore to avoid "
                      "committing machine-specific runtime state:")
            print()
            print(GITIGNORE_BLOCK_HEADER)
            for entry in writable:
                print(entry)
            print(GITIGNORE_BLOCK_FOOTER)
            print()
            print(rerun_hint)
    return needs_gitignore


def _print_init_summary(
    *,
    fp: "RepoFingerprint",
    harness: "BuildPlan",
    result: dict,
    profile_name: str | None,
    repo_root: Path,
    write_gitignore: bool,
    suppress_epilogue: bool = False,
) -> None:
    """Emit cmd_init's post-deploy operator report. Pure presentation:
    filesystem install counts, the ownership tally, the honest hooks-wired
    banner, the gitignore section (via _handle_gitignore, positioned between
    the tally and the narrative), and the orientation narrative."""
    # Step 5: Report
    print(f"Initialized harness for: {fp.repo_name}")
    print(f"Languages: {', '.join(fp.languages)}")
    # A non-Python adopter must not read the armed banner as a full governance
    # toolbelt — the code scanners (/scan, quality gates) are Python-AST-specific
    # and no-op on their repo. The workflow, hooks, and memory still apply.
    # (Empty fp.languages = no detected source: stay quiet.)
    if fp.languages and fp.languages[0] != "python":
        print(
            "Note: the code scanners (/scan, quality gates) are Python-AST-specific "
            "and will no-op on this repo. The workflow, hooks, and memory still apply."
        )
    print(f"Profiles: {', '.join(harness.profiles)}")
    # Granular install labels sourced from the filesystem rather than the
    # profile recommendation set, so the printed counts match what landed on
    # disk.
    installed = {
        kind: len(surface_contract.discover_claude_kind(repo_root, kind))
        for kind in surface_contract.CLAUDE_SURFACE_KINDS
    }
    n_agent_files = installed["agents"]
    n_command_files = installed["commands"]
    n_skill_files = installed["skills"]
    n_hook_entries = sum(1 for s in INIT_HOOK_SCRIPTS if not Path(s).name.startswith("_"))
    n_hook_helpers = sum(1 for s in INIT_HOOK_SCRIPTS if Path(s).name.startswith("_"))
    n_recommended_agents = len(harness.agents) if harness.agents else 0
    profile_label = harness.profiles[0] if harness.profiles else "general"

    print("Installed (filesystem):")
    print(f"  Agent files:         {n_agent_files}")
    print(f"  Command files:       {n_command_files}")
    print(f"  Skill files:         {n_skill_files}")
    print(f"  Hook entry scripts:  {n_hook_entries}")
    print(f"  Hook helper scripts: {n_hook_helpers}")
    print(f"Profile: {profile_label}")
    print(f"  Recommended active agents (for this profile): {n_recommended_agents}")
    # A recommendation is a claim; only a packaged body (or one the adopter
    # wrote at the recommended path) is a deploy. Name the ones this release
    # has no body for, so the count above is not read as agents on disk
    # (DEF-766; doctor reports the same set as `unshipped_saved_agents`).
    from espalier.asset_inventory import packaged_agent_names
    with_a_packaged_body = packaged_agent_names()
    bodiless = [
        a.name for a in (harness.agents or [])
        if a.name not in with_a_packaged_body
        and not os.path.isfile(repo_root / ".claude" / "agents" / f"{a.name}.md")
    ]
    if bodiless:
        print(
            "    recorded as a recommendation only, no packaged body in this "
            f"release: {', '.join(bodiless)}"
        )
    # Agents / commands / skills are deployed by default from
    # ``espalier/assets/claude/``. A count of 0 here means the asset tree
    # did not ship with the install (e.g., a legacy editable install, or a
    # wheel built without ``package-data`` declarations). Tell the operator
    # how to recover.
    if any(n == 0 for n in installed.values()):
        print(
            "  WARN: one of agents / commands / skills landed at zero. The "
            "harness assets at espalier/assets/claude/ may be missing from "
            "this install. Refresh with: pip install --force-reinstall "
            "espalier-harness (wheel installs) or `pip install -e .` in the "
            "harness checkout (editable installs)."
        )
    print(f"Settings profile: {profile_name}")
    print(f"Deployed: {len(result['deployed'])} files")
    # Ownership tally — `created` (new), `updated_managed` (regenerated
    # managed file), `skipped_no_drift` (already-matching content),
    # `skipped_user_files` (preserved unmarked file). Operators read this to
    # confirm rerunning init didn't stomp their hand-edits and to see how much
    # of a rerun was a true no-op.
    n_created = len(result.get('created', []))
    n_updated = len(result.get('updated_managed', []))
    n_no_drift = len(result.get('skipped_no_drift', []))
    n_user = len(result.get('skipped_user_files', []))
    # `created` and `updated_managed` are subsets of `deployed`; the remaining
    # deployed files (settings.json, CLAUDE.md, ESPALIER_MEMORY.md, the seed
    # docs, integrity.json, the surface-gate report) reach `deployed` through
    # append-only sites that never touch `created`. Surface them as `other` so
    # the written buckets partition `Deployed` exactly. `skipped_no_drift` /
    # `skipped_user_files` are files considered but NOT written (absent from
    # `deployed`), so they are excluded from the residual — this reconciles on a
    # fresh init (created + other == Deployed) and a re-init alike, where the
    # naive `deployed - created - updated - no_drift - user` would go negative.
    n_other = len(result['deployed']) - n_created - n_updated
    if n_created or n_updated or n_other or n_no_drift or n_user:
        print(
            f"  created: {n_created}  "
            f"updated_managed: {n_updated}  "
            f"other: {n_other}  "
            f"skipped_no_drift: {n_no_drift}  "
            f"skipped_user_files: {n_user}"
        )
        print(
            "  (created + updated_managed + other = Deployed; "
            "skipped_* were preserved, not written)"
        )
        # DEF-774: a count is not a next step; a path is. A marked file the
        # adopter hand-edited is regenerated from the packaged copy with no
        # backup, so the block that reports the count names the files -- the
        # deploy loop had collected them all along and this printer dropped
        # them. The refreshed seeds likewise: stdout folded them into `other`
        # while stderr named them by basename.
        updated = list(result.get('updated_managed', []))
        if updated:
            # Never truncated: this line is the only record of which
            # hand-edited files were overwritten, with no backup taken.
            print(
                "  regenerated from the packaged copy (a managed marker keeps "
                "a file on this list; local edits to it are replaced): "
                + _name_paths(updated, limit=len(updated))
            )
        refreshed_seeds = list(result.get('refreshed_seed_docs', []))
        if refreshed_seeds:
            print(
                "  seed docs refreshed (untouched copies whose packaged content "
                "changed): " + _name_paths(refreshed_seeds)
            )
        # The third count in this block whose members are the next step: a
        # packaged source this engine install lacks, so nothing was deployed
        # for it. `upgrade` names these and says reinstall; init, the
        # first-run verb, folded them into "Skipped (other)".
        source_missing = [
            s[: -len(" (source missing)")]
            for s in result.get('skipped', []) if s.endswith(" (source missing)")
        ]
        if source_missing:
            print(
                "  not deployed (packaged source missing from this engine "
                "install; reinstall espalier): "
                + _name_paths(source_missing, limit=len(source_missing))
            )
    if result['skipped']:
        print(f"Skipped (other): {len(result['skipped']) - n_user} entries")

    # Called unconditionally, and from the CALLER rather than deploy_harness, on
    # purpose. Its own predicate -- "does the CLAUDE.md on disk contain the
    # sections the deny messages cite?" -- is the right question no matter which
    # branch deploy_harness took: silent when init just rendered the skeleton
    # (nothing missing), and it also reaches an adopter whose CLAUDE.md was
    # deployed by an EARLIER espalier that had no such section, which a
    # skip-branch call would never see. Printing here rather than mid-deploy
    # keeps it with the rest of the adopter guidance instead of scrolling off
    # the top above the "Initialized harness for:" banner.
    _print_claude_md_nudge(
        repo_root / "CLAUDE.md",
        preserved=_CLAUDE_MD_SKIPPED_MARKER in result.get("skipped", ()),
    )

    needs_gitignore = _handle_gitignore(repo_root, write_gitignore=write_gitignore)

    # Orientation narrative + uninstall pointer.
    print()
    print("What just happened:")
    # Keep this banner honest. When the operator's pre-existing settings.json
    # blocked hook wiring, the hooks are NOT active — claiming they "now
    # intercept" would be a governance tool lying about being armed.
    # Spelled with an interpreter that can RUN the commands below, not the one
    # written into settings.json: on a host whose `python` is a Python 2 shim
    # the resolver's answer IS that shim, and the uninstall line three bullets
    # down read `python -m espalier clean-generated` under the narration that
    # had just called it broken (DEF-727 review, driven).
    py, _ = _remedy_interpreter()
    # Default FALSE: an absent key means nobody established the claim, and a
    # governance tool must not assert enforcement from a missing measurement.
    if result.get("settings_hooks_wired", False):
        print("  - Hooks now intercept Claude Code tool calls "
              "(write_guard, plan_guard, stop_gate, ...).")
        # DEF-619: that sentence is about the blocking gates, and it used to
        # be the whole story -- a reporter (SubagentStart, PostToolUseFailure,
        # PostCompact, ...) could be deleted or neutered with every surface
        # still reading armed. Say so here, in the one line the adopter reads.
        # Only on the armed branch: the disarmed diagnosis above already sends
        # them to merge-settings / doctor, which lists the reporters too.
        reporters_line = _dead_reporters_line(repo_root, py)
        if reporters_line:
            print("  - " + reporters_line)
    else:
        reason, remedies = _disarmed_diagnosis(repo_root)
        print(f"  - {reason}")
        for line in remedies:
            print(f"    {line}")
    print("  - Agents are dispatched as subagents by name "
          "(subagent_type='code-reviewer', ...).")
    print("  - Slash commands: type `/` in Claude Code to list them, or browse "
          ".claude/commands/. Quick reference: https://github.com/"
          "Mike-Byrne-AI/espalier-harness/blob/main/docs/CHEAT-SHEET.md "
          "(/status, /implement-task, /preflight, /commit, /handoff).")
    print("  - To remove all managed files later: "
          f"{py} -m espalier clean-generated --execute .")
    # The "Start Claude Code" epilogue is init's final call-to-action. When init
    # runs as a `fuse` sub-step, fuse emits more output after this (install-ci,
    # the fusion summary + finish-up banner), so this line must not appear
    # mid-stream — fuse suppresses it here and prints its own single
    # "Start Claude Code" line as its true last output.
    if not suppress_epilogue:
        print()
        # Same anchor as fuse's epilogue, for the same reason: `init <path>` need
        # not target cwd, and an operator who obeys "start Claude Code" literally
        # gets a session in the wrong tree. Emitted only when the two actually
        # differ -- `init .` is the common case and a redundant `cd` there is
        # noise -- and BOTH branches are pinned in tests/test_init.py, because an
        # unfired conditional is this pack's own recurring defect.
        if repo_root != Path.cwd():
            print("Start Claude Code in the initialized repo (not this directory):")
            print(f'    cd "{repo_root}"')
            print("    claude")
        else:
            print("Start Claude Code with: claude")
        print("The SessionStart hook will load context automatically.")
    # `needs_gitignore` is now "STILL missing after this run" — empty when the
    # append succeeded — so the `not write_gitignore` arm is no longer needed
    # and was actively harmful: it suppressed this reminder on the write-FAILED
    # path, where the operator is one `git add -A` away from committing
    # .claude/settings.json. The root CLAUDE.md calls that gitignore the primary
    # foreclosure against a committed kill switch.
    if needs_gitignore:
        print("WARN: Address the .gitignore warning above before `git add -A`.")


def _deploy_seed_docs(repo_root: Path, *, dry_run: bool = False) -> dict[str, list[str]]:
    """Deploy the init-seeded convention scaffolds (skip / refresh via the
    seed-version stamp). Shared by ``cmd_init`` (in its pre-fingerprint
    position, so the saved fingerprint reflects the post-deploy state) and
    ``cmd_upgrade`` so both entry points refresh an operator-untouched seed doc
    when its packaged content changes. Returns the dest relpaths written under
    ``"created"`` (absent before) and ``"refreshed"`` (present, untouched, and
    behind the packaged copy) for the operator-facing deploy report; a
    ``dry_run`` returns what a write would do, through the same decision, and
    writes and prints nothing (``upgrade``'s preview, DEF-774).

    The body is ``managed_inventory.render_seed_body`` -- the adapt header for
    a Tier-2 seed, then the packaged asset resolved through
    ``get_seed_asset_source`` (the adopter stubs live under
    ``espalier/assets/seed/``, not beside their destination). That renderer is
    shared with ``doctor``, which prints the stamp of the same body for a seed
    whose first line is gone; rendering here by any other route would let the
    printed stamp and the written one drift (DEF-696).
    """
    from espalier.managed_inventory import get_seed_docs, render_seed_body
    outcome: dict[str, list[str]] = {"created": [], "refreshed": []}
    for dest_relpath in get_seed_docs():
        dest = repo_root / dest_relpath
        existed = dest.exists()
        if _write_seed(
            dest, render_seed_body(dest_relpath), label=dest_relpath, dry_run=dry_run,
        ):
            outcome["refreshed" if existed else "created"].append(dest_relpath)
    return outcome


def _seed_outcome_sentence(outcome: dict[str, list[str]], *, done: bool) -> str:
    """One sentence naming what a seed deploy did (``done``) or, on a dry
    run, would do: the refreshed and the created seeds by root-relative
    path, or that none needed it. The same sentence on both arms, from the
    same outcome shape, so the preview cannot say less than the write."""
    parts: list[str] = []
    refreshed = outcome.get("refreshed", [])
    created = outcome.get("created", [])
    if refreshed:
        parts.append(
            f"{plural(len(refreshed), 'seed doc')} refreshed (untouched "
            f"{'copy' if len(refreshed) == 1 else 'copies'} whose packaged "
            "content changed): " + _name_paths(refreshed)
        )
    if created:
        absent = (
            ("was" if len(created) == 1 else "were") + " absent" if done else "absent"
        )
        parts.append(
            f"{plural(len(created), 'seed doc')} created ({absent}): "
            + _name_paths(created)
        )
    if not parts:
        return "none need it (every copy is current, edited by you, or unstamped)."
    return "; ".join(parts) + "."


def _preview_seed_docs(repo_root: Path) -> dict[str, list[str]] | None:
    """``_deploy_seed_docs`` on a dry run, for the read-only ``upgrade`` arms.
    ``None`` when the packaged seed source cannot be read -- a wheel built
    without its package data, the state this command already warns about
    for the managed surface -- with the same warning on stderr, so the
    preview an adopter runs to diagnose a broken install degrades to the
    warning instead of a traceback (the failure-mode review drove it).
    The write arms keep raising: a write that cannot render has nothing
    honest to write."""
    try:
        return _deploy_seed_docs(repo_root, dry_run=True)
    except OSError as exc:
        print(
            "[upgrade] WARN: the packaged seed source is missing from this "
            f"engine install ({os_error_text(exc)}); the seed preview is skipped -- "
            "reinstall espalier.",
            file=sys.stderr,
        )
        return None


def _count_unstamped_seed_docs(repo_root: Path) -> int:
    """Count present seed docs carrying no seed-version stamp -- copies deployed
    by a pre-stamp engine, or seeds whose first line an adopter removed.
    ``cmd_upgrade`` surfaces this so a "re-deployed 0 seed doc(s)" line is not
    misread as "all current" when it really means "N copies cannot be proven
    untouched and were left as-is"; ``doctor`` asks the same counter (DEF-691).
    The body lives in ``managed_inventory.count_unstamped_seed_docs`` because
    ``doctor`` must not import this module."""
    from espalier.managed_inventory import count_unstamped_seed_docs
    return count_unstamped_seed_docs(repo_root)


def _refuse_unreadable_harness_root(repo_root: Path, command: str) -> int | None:
    """Exit 1 with the one sentence when ``.claude`` is a directory this
    process cannot search or list, else ``None`` so the command proceeds.

    For ``init``, ``upgrade`` and ``fuse``, which resolve their own repo
    argument (exit 1 for a bad one, where ``_resolve_repo_arg``'s callers
    exit 2) and so never pass the gate the resolver carries for every other
    command. Asked first, before any deploy or tally. Asked later, the same
    tree read as "absent" on CPython 3.14 -- ``init`` printed its seed lines
    and died at the settings write, ``upgrade`` dry-ran green and exited 0
    -- and raised out of the first ``Path.exists()`` on 3.10-3.13 (DEF-763,
    driven on real 3.10, 3.13 and 3.14 interpreters 2026-09-13). ``doctor``
    and ``audit`` ask the same question inside their library entry points
    too, so their JSON reports carry the finding for every caller.
    ``tests/test_cli_commands.py`` derives the set of repo-taking commands
    from the parser and reds on one that asks neither gate.
    """
    detail = surface_contract.unreadable_harness_root(repo_root)
    if detail is None:
        return None
    print(
        f"{command}: {surface_contract.unreadable_root_sentence(detail)} "
        f"`{_remedy_py()} -m espalier {command} .`",
        file=sys.stderr,
    )
    return 1


def cmd_init(args: argparse.Namespace) -> int:
    """First-time harness configuration for a host repo."""
    from espalier.settings_profiles import DEFAULT_PROFILE, get_profile

    repo_root = Path(args.repo).resolve()

    # A mistyped / nonexistent path resolves fine but isn't a directory; diagnose
    # that distinctly instead of letting the next check call it "not a git repository".
    if not repo_root.is_dir():
        print(
            f"[init] FAIL: {repo_root} does not exist or is not a directory.\n"
            f"       Check the path; init operates on an existing repo directory.",
            file=sys.stderr,
        )
        return 1

    # Git-init pre-flight. Every hook fires ``git diff`` / ``git log``; a
    # non-git target produces confusing per-fire noise.
    # Fail fast with an actionable message instead. Exit 1 (precondition
    # failure), not 2 (governance deny).
    if not (repo_root / ".git").exists():
        print(
            f"[init] FAIL: {repo_root} is not a git repository.\n"
            f"       Run `git init` first; this command requires a git "
            f"directory because hooks invoke `git diff` / `git log`.",
            file=sys.stderr,
        )
        return 1

    refused = _refuse_unreadable_harness_root(repo_root, "init")
    if refused is not None:
        return refused

    config = _load_config(repo_root, args)

    # Settings profile selection precedence:
    #   1. --profile CLI flag
    #   2. espalier.toml `default_profile`
    #   3. settings_profiles.DEFAULT_PROFILE ("workflow")
    # Raise a clear error if espalier.toml names an unknown profile so the
    # user catches typos at init time rather than via downstream validation.
    # Attribute the error source (CLI flag vs config file) so the operator
    # knows where to fix the typo.
    cli_profile = getattr(args, "profile", None)
    cfg_profile = getattr(config, "default_profile", None)

    # Post-v0.6.5: ``self-host`` is opt-in *only* via the CLI flag, per the
    # docstring promise in ``espalier/settings_profiles.py``. Allowing
    # ``espalier.toml default_profile = "self-host"`` to select it lets an
    # upstream repo widen permissions for every downstream operator running
    # ``espalier init`` against a fresh clone. Reject before the precedence
    # cascade so the error names the actual cause.
    #
    # Post-v0.6.6: case- and whitespace-tolerant compare so ``Self-Host`` /
    # ``SELF-HOST`` / ``" self-host "`` hit the named error rather than
    # falling through to ``get_profile``'s generic "Unknown profile" message.
    # The "must be opt-in via CLI" rule lives on the Profile itself
    # (``Profile.config_selectable=False`` on ``_SELF_HOST``) — the CLI
    # consults the attribute instead of carrying string knowledge.
    cfg_profile_normalized = (cfg_profile or "").strip().lower()
    if cfg_profile_normalized:
        from espalier.settings_profiles import PROFILES
        target_profile = PROFILES.get(cfg_profile_normalized)
        if target_profile is not None and not target_profile.config_selectable:
            cli_profile_normalized = (cli_profile or "").strip().lower()
            if cli_profile_normalized != cfg_profile_normalized:
                print(
                    f"Error: profile {target_profile.name!r} must be opt-in via "
                    f"--profile {target_profile.name} on the CLI; espalier.toml "
                    f"default_profile cannot select it.",
                    file=sys.stderr,
                )
                return 2

    profile_name = cli_profile or cfg_profile or DEFAULT_PROFILE
    profile_source = (
        "--profile flag" if cli_profile
        else "espalier.toml default_profile" if cfg_profile
        else "built-in default"
    )
    try:
        get_profile(profile_name)
    except ValueError as exc:
        print(
            f"Error: invalid profile {profile_name!r} from {profile_source}: {exc}",
            file=sys.stderr,
        )
        return 2

    # --dry-run short-circuit. Compute the fingerprint + plan,
    # print a preview of what the live init would write, exit without
    # touching the filesystem. Adopters use this to inspect the deploy
    # surface before committing.
    if getattr(args, "dry_run", False):
        from espalier.asset_inventory import get_packaged_surface
        surface = get_packaged_surface()
        agent_paths = list(surface.agents.paths)
        command_paths = list(surface.commands.paths)
        skill_paths = list(surface.skills.paths)
        print(f"[dry-run] Would initialize harness for: {repo_root.name}")
        print(f"[dry-run] Would deploy {len(agent_paths)} agents, "
              f"{len(command_paths)} commands, {len(skill_paths)} skills")
        print(f"[dry-run] Would deploy {len(INIT_HOOK_SCRIPTS)} hook scripts "
              f"to tools/cc/hooks/")
        print("[dry-run] Would write .claude/settings.json + CLAUDE.md + "
              "ESPALIER_MEMORY.md (skeleton)")
        from espalier.managed_inventory import get_seed_docs
        print(f"[dry-run] Would seed {len(get_seed_docs())} docs "
              "(memory/README.md, docs/sharp-edges/README.md, docs/*.md ...) + "
              ".espalier/integrity.json")
        print("[dry-run] Would write reports/repo_fingerprint.json + "
              "reports/harness_config.json")
        print("[dry-run] No filesystem changes made. "
              "Re-run without --dry-run to apply.")
        return 0

    # Bootstrap memory/ and docs/sharp-edges/ READMEs BEFORE
    # fingerprint so the saved fingerprint reflects the post-deploy
    # state (otherwise doctor.diff_repo flags docs_surface drift on
    # every post-init run). Drift-aware via _write_seed's seed-version
    # stamp: an operator-untouched-but-stale copy refreshes, an edited or
    # legacy-unstamped copy is preserved on re-init. Extracted to
    # _deploy_seed_docs so cmd_upgrade shares the same refresh path.
    seed_outcome = _deploy_seed_docs(repo_root)

    # Step 1: Fingerprint
    fp = fingerprint_repo(repo_root, config)

    # Step 2: Build harness config
    harness = build_harness_config(fp, config)

    # Step 3: Save reports
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    # Atomic writes so a parallel CC session reading the fingerprint mid-write
    # doesn't see a torn JSON.
    atomic_write_text(
        reports_dir / "repo_fingerprint.json",
        json.dumps(fp.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    plan_dict = harness.to_dict()
    if surface_contract.is_self_host_repo(repo_root):
        plan_dict = _self_host_plan_overlay(plan_dict, repo_root)
    # The EFFECTIVE settings profile (CLI flag, espalier.toml, or the default):
    # the per-machine settings.json records nothing itself, and every later
    # reader that compares it against a profile (doctor, upgrade,
    # merge-settings) needs the one it was rendered from (DEF-715 review). The
    # report has the same per-machine lifecycle as the file it describes.
    plan_dict["settings_profile"] = profile_name
    atomic_write_text(
        reports_dir / "harness_config.json",
        json.dumps(plan_dict, indent=2, sort_keys=True) + "\n",
    )

    # Step 3b: --rewire-interpreter. Runs BEFORE the deploy so the rest of this
    # command, and the `doctor` the operator runs next, both see the repaired
    # file. Opt-in only: without the flag nothing here touches settings.json.
    if getattr(args, "rewire_interpreter", False):
        _report_interpreter_rewire(repo_root / ".claude" / "settings.json")

    # Step 4: Deploy harness files.
    result = deploy_harness(
        repo_root, harness, fp,
        profile_name=profile_name,
        wire_hooks=getattr(args, "wire_hooks", False),
    )

    # Record the README deploys (already done above-fingerprint) in the deploy
    # report so the operator-facing count includes them, and carry the
    # refreshed seeds by path for the summary (DEF-774: stdout folded them
    # into `other: 11` while stderr named them by basename).
    result["deployed"].extend(seed_outcome["created"] + seed_outcome["refreshed"])
    result["refreshed_seed_docs"] = list(seed_outcome["refreshed"])

    # Step 4b: Seed integrity manifest so fresh installs have a valid baseline.
    try:
        integrity = load_integrity_module()
        integrity.write_manifest(repo_root)
        result["deployed"].append(".espalier/integrity.json")
    except (FileNotFoundError, OSError) as exc:
        print(f"WARN: could not seed integrity manifest: {os_error_text(exc)}", file=sys.stderr)

    # Step 4c: Seed the surface gate so the adopter's first `/status` reads
    # SURFACE: healthy, not DEGRADED. reports/cc_surface_gate.json is a
    # REQUIRED_PATH for session_resume.py (the /status body); otherwise it is
    # written only by `espalier audit`, an onboarding cliff. run_cc_surface_gate
    # writes the file as a side effect (proofs.py).
    try:
        run_cc_surface_gate(repo_root)
        result["deployed"].append("reports/cc_surface_gate.json")
    except OSError as exc:
        print(f"WARN: could not seed surface gate: {os_error_text(exc)}", file=sys.stderr)

    _print_init_summary(
        fp=fp,
        harness=harness,
        result=result,
        profile_name=profile_name,
        repo_root=repo_root,
        # The parser's declared default (True since v0.7.9). An embedder's
        # hand-built Namespace read False here and got the print-only
        # behaviour the flag retired -- with a WARN telling them to rerun
        # without a flag they never passed (DEF-399b); the suite's own
        # adopter-tree builder was one such caller.
        write_gitignore=getattr(args, "write_gitignore", True),
        # fuse sets this so init's "Start Claude Code" epilogue doesn't print
        # mid-stream; the standalone `init` path leaves it unset (epilogue on).
        suppress_epilogue=getattr(args, "suppress_epilogue", False),
    )

    return 0


class MergeResult(NamedTuple):
    """Outcome of ``merge_hooks_into_settings``.

    ``status`` is one of the stable codes below; callers compose their own
    operator-facing message from it (``merge-settings`` and ``init/fuse
    --wire-hooks`` word the same outcome differently). ``detail`` carries the
    ``.bak`` filename on a successful wire, or a short machine reason on refusal
    (e.g. the bad ``hooks`` type name, the parse exception). ``event_count`` is
    the number of Espalier hook events merged (0 unless wired).

    The profile's allow rules are the operator's to accept (DEF-715):
    ``missing_allows`` names the rules of the selected profile the file still
    lacks after this call -- computed on every outcome that read the file (a
    refusal carries ``()``), so every caller can say so -- and ``added_allows``
    the ones this call appended (only on ``add_allows``; ``allow_count`` is
    its length).
    ``allow_note`` is non-empty when the ``permissions`` block has a shape the
    merge will not read or rewrite (a string, a non-list ``allow``); the gap
    is then unknowable and nothing is appended.
    ``statusline_added`` is True when this call wrote espalier's ``statusLine``
    into a file that had no such key (DEF-798); a present key of any value is
    the operator's and is never rewritten.
    """

    status: str
    detail: str = ""
    event_count: int = 0
    missing_allows: tuple[str, ...] = ()
    added_allows: tuple[str, ...] = ()
    allow_note: str = ""
    statusline_added: bool = False

    @property
    def allow_count(self) -> int:
        return len(self.added_allows)


def _merge_did_phrase(
    result: MergeResult, *, profile: str | None = None, noun: str = "Espalier hook event",
) -> str:
    """One phrase for every narrator of a wired merge (``--wire-hooks``,
    ``merge-settings``, ``upgrade --execute``): what this call wrote -- hook
    events, the profile's allow rules (opt-in), espalier's ``statusLine`` when
    the key was absent (DEF-798) -- so a top-up that wrote only the statusLine
    is said as such, never as "wired 0 hook events"."""
    did: list[str] = []
    if result.event_count:
        did.append(f"wired {plural(result.event_count, noun)}")
    if result.added_allows:
        did.append(f"appended {plural(len(result.added_allows), 'allow rule')}"
                   + (f" of the {profile!r} profile" if profile else ""))
    if result.statusline_added:
        did.append("added espalier's statusLine")
    if not did:
        return "rewrote nothing"
    if len(did) == 1:
        return did[0]
    return ", ".join(did[:-1]) + " and " + did[-1]


def _merge_claim(result: MergeResult, *, repaired: bool = False) -> str:
    """The enforcement sentence every narrator of an armed merge appends.
    "now" claims a transition; a run that wired no hook event -- an allow-only
    or statusline-only top-up on a wired file -- made none, unless a repair
    rewrote entries (its rewrite is the transition). One helper for
    ``--wire-hooks`` and ``merge-settings``: the first shipped the shared
    did-phrase and kept an unconditional "now" (both reviewers, 2026-09-15)."""
    return (" Enforcement is now active." if (result.event_count or repaired)
            else " Enforcement was already active.")


# Stable MergeResult.status codes. Shared by both callers so the merge logic
# lives in ONE place — no parallel-inventory drift between the operator command
# and the deploy-time opt-in.
MERGE_WIRED = "wired"            # hooks merged in; detail = .bak filename
MERGE_ALREADY = "already"        # Espalier hooks already present; no-op
MERGE_NO_FILE = "no_file"        # no settings.json to merge into
MERGE_UNREADABLE = "unreadable"  # a parent of settings.json denies traversal; detail = OS message
MERGE_PARSE_ERROR = "parse_error"  # settings.json is not valid JSON
MERGE_NOT_OBJECT = "not_object"  # top-level JSON is not an object
MERGE_BAD_HOOKS = "bad_hooks"    # 'hooks' value is a non-object (malformed)


def _settings_backup_rung(settings_path: Path, n: int) -> Path:
    """Rung ``n`` of the backup ladder beside ``settings_path``:
    ``settings.json.bak`` at 0, then ``.bak.1``, ``.bak.2``, ..."""
    if n == 0:
        return settings_path.with_name(settings_path.name + ".bak")
    return settings_path.with_name(f"{settings_path.name}.bak.{n}")


def _back_up_settings(settings_path: Path) -> Path:
    """Copy ``settings_path`` beside itself before a rewrite; return the copy.

    Shared by the three paths that mutate an operator-owned ``settings.json``:
    :func:`repair_hook_wiring_in_settings`,
    :func:`merge_hooks_into_settings` and
    :func:`rewire_interpreter_in_settings`. Climbs the ladder from ``.bak``:
    an existing rung that already holds these exact bytes IS the copy, and is
    returned without a write; otherwise the first free rung is written. Never
    clobbers an existing backup -- both ``settings.json`` and its ``.bak`` are
    gitignored, so that ``.bak`` may be the only on-disk copy of what the
    operator wrote -- and never removes one: this only declines to add a
    duplicate. Driven on the Windows host (walk 3, leg 5-F) and again on
    POSIX: three wire / uninstall / wire cycles left ``.bak``, ``.bak.1`` and
    ``.bak.2``, the last two byte-identical, because an uninstall unwires the
    file back to the bytes the previous wire backed up (DEF-809). Every rung
    on disk is compared, not only the contiguous climb: an operator who
    deleted ``.bak.1`` by hand and kept ``.bak.2`` still has ``.bak.2``
    recognised. A rung that cannot be read is not a match.
    """
    # bom-exempt: the bytes are copied to the backup verbatim and compared to
    # a rung's bytes, never decoded -- a byte-order mark travels with them.
    current = settings_path.read_bytes()
    for rung in _settings_backup_rungs_on_disk(settings_path):
        try:
            # bom-exempt: a bytes-to-bytes compare; nothing is decoded.
            if rung.read_bytes() == current:
                return rung
        except OSError:
            continue
    n = 0
    while os.path.exists(_settings_backup_rung(settings_path, n)):
        n += 1
    fresh = _settings_backup_rung(settings_path, n)
    atomic_write_bytes(fresh, current)
    return fresh


def _settings_backup_rungs_on_disk(settings_path: Path) -> list[Path]:
    """Every ``settings.json.bak`` / ``.bak.N`` regular file beside
    ``settings_path``, in ladder order (the grammar is
    ``managed_inventory.settings_backup_rung``, spelled once). A ``.bak.old``
    the operator made by hand is theirs and never a rung. A symlink is never
    a rung either: a link to the settings file itself would compare equal
    before the write and hold the post-write bytes after it, so the climb
    passes it and writes a real copy on the next free rung."""
    try:
        siblings = list(settings_path.parent.iterdir())
    except OSError:
        return []
    rungs: list[tuple[int, Path]] = []
    for sibling in siblings:
        if sibling.is_symlink() or not sibling.is_file():
            continue
        rung = settings_backup_rung(sibling.name, base=settings_path.name)
        if rung is not None:
            rungs.append((rung, sibling))
    return [rung for _, rung in sorted(rungs)]


def merge_hooks_into_settings(
    settings_path: Path,
    *,
    profile: str = "workflow",
    repo_root: Path,
    add_allows: bool = False,
) -> MergeResult:
    """Merge Espalier's hook events into an existing ``settings.json`` in place.

    The single implementation behind both ``espalier merge-settings`` (operator
    opt-in) and ``init``/``fuse --wire-hooks`` (deploy-time opt-in). Preserves
    every operator key, APPENDS only Espalier's hook events per event and adds
    its ``statusLine`` when that key is absent (DEF-798), keeps a ``.bak`` of
    the pre-write bytes first (written, or the rung that already holds them),
    and is idempotent. It NEVER stamps the file managed
    (it stays the operator's hand-editable file) and NEVER overwrites a malformed
    file — a parse/shape problem returns a refusal status, not a clobber, so the
    operator's content is never silently destroyed.

    Returns a :class:`MergeResult`; the caller maps ``status`` to its own message
    + exit code.
    """
    settings_path = Path(settings_path)
    # By errno, never `Path.exists()`: a parent that denies traversal raised
    # here on CPython 3.10-3.13 and read as "no file" on 3.14, sending the
    # adopter to `init` on a directory it cannot search (DEF-763).
    presence, unreadable_detail = surface_contract.path_presence(settings_path)
    if presence == surface_contract.PRESENCE_ABSENT:
        return MergeResult(MERGE_NO_FILE)
    if presence == surface_contract.PRESENCE_UNREADABLE:
        return MergeResult(MERGE_UNREADABLE, detail=unreadable_detail)
    try:
        raw = settings_path.read_bytes()
    except OSError as exc:
        # The FILE, not its parent: a mode-000 settings.json is present and
        # unreadable, and "could not parse" was a lie for bytes never read.
        # The file-level predicate `merge_refusal_for_file` splits the same way.
        return MergeResult(MERGE_UNREADABLE, detail=os_error_text(exc))
    try:
        existing = json.loads(surface_contract.decode_bom(raw))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        # ValueError: json.loads raises it bare (not JSONDecodeError) for an
        # over-long int literal (the int-str digit limit, 3.10.7+). The
        # file-level predicate `merge_refusal_for_file` mirrors this tuple.
        return MergeResult(MERGE_PARSE_ERROR, detail=str(exc))
    if not isinstance(existing, dict):
        return MergeResult(MERGE_NOT_OBJECT, detail=type(existing).__name__)
    canonical = _build_settings_json(profile_name=profile, repo_root=repo_root)
    managed_hooks = canonical.get("hooks", {})
    existing_hooks = existing.get("hooks")
    # DEF-798: espalier's statusLine is its own key, and the fresh render was
    # the only path that wrote it -- an adopter arriving with a permissions-
    # only file and running --wire-hooks got the shim and the script on disk
    # and no key, with every narrator silent. Add it when the KEY is absent,
    # never when present: an explicit ``null`` turns Claude Code's statusline
    # off on purpose, and any other value is the operator's own. The key is
    # the test, not the files on disk (a deployed shim is not a wiring).
    canonical_statusline = canonical.get("statusLine")
    add_statusline = _would_add_statusline(existing) and isinstance(canonical_statusline, dict)
    # The profile's allow rules the file lacks: ALWAYS computed and reported,
    # appended only on ``add_allows`` (DEF-715: an install predating a profile
    # rule never received it, and nothing said so). ``permissions`` stays the
    # operator's -- nothing is ever removed, and a malformed block is named,
    # never rewritten.
    missing_allows, allow_note = _allow_gaps(
        existing, canonical.get("permissions", {}).get("allow", []),
    )
    append_allows = add_allows and bool(missing_allows) and not allow_note
    # Idempotent ONLY when EVERY canonical event already carries an Espalier
    # hook and the statusLine key is present. Returning MERGE_ALREADY the
    # moment ANY single Espalier hook is found would leave a settings.json
    # wired by an OLDER engine but missing a NEWER canonical event
    # (PostToolUseFailure / SubagentStart) never topped up.
    # Fall through to the per-event loop (which appends ONLY the missing events)
    # unless all canonical events are wired; a re-run on a fully-wired file is
    # still a clean no-op (no .bak churn).
    _existing_hooks_dict = existing_hooks if isinstance(existing_hooks, dict) else {}
    hooks_current = bool(managed_hooks) and all(
        _event_groups_have_espalier_hook(_existing_hooks_dict.get(event))
        for event in managed_hooks
    )
    if hooks_current and not append_allows and not add_statusline:
        return MergeResult(
            MERGE_ALREADY, missing_allows=tuple(missing_allows), allow_note=allow_note,
        )
    merged = dict(existing)
    topped_up_events = 0
    if not hooks_current:
        if existing_hooks is None:
            # Absent or explicit null -> no operator hooks to preserve; start empty.
            existing_hooks = {}
        elif not isinstance(existing_hooks, dict):
            # Claude Code's `hooks` is an object keyed by event name. ANY non-object
            # value — truthy (a list, a string, a number) OR falsy ([], "", 0) — is
            # malformed. Refuse uniformly with the exact type so the caller can name
            # it; coercing a FALSY non-object to {} before this check would silently
            # replace it (status=wired) and contradict the docstring's "NEVER
            # overwrites a malformed file."
            return MergeResult(MERGE_BAD_HOOKS, detail=type(existing_hooks).__name__)
        # Per-event merge: preserve the operator's own events/hooks and APPEND
        # Espalier's. We reach here when NOT every canonical event is wired (a brand-
        # new adopter OR a partial upgrade); the per-event guard below skips events
        # that already carry an Espalier hook, so a partial upgrade tops up only the
        # missing events and never duplicates an existing one.
        merged_hooks = dict(existing_hooks)
        for event, entries in managed_hooks.items():
            existing_entries = existing_hooks.get(event)
            if existing_entries is None:
                existing_entries = []
            elif not isinstance(existing_entries, list):
                # A valid hooks dict whose ONE event value is a truthy non-list (a
                # dict/string) would make `dict + list` raise an uncaught TypeError
                # here — a raw traceback BEFORE the backup below, leaving no .bak.
                # Refuse cleanly, naming the offending event.
                return MergeResult(
                    MERGE_BAD_HOOKS,
                    detail=f"hooks.{event}: {type(existing_entries).__name__}",
                )
            # An event that ALREADY carries an Espalier hook is left untouched —
            # only top up the canonical events still missing one.
            if _event_groups_have_espalier_hook(existing_entries):
                merged_hooks[event] = existing_entries
                continue
            merged_hooks[event] = existing_entries + list(entries)
            topped_up_events += 1
        merged["hooks"] = merged_hooks
    added: list[str] = []
    if append_allows:
        # Append-only, in canonical order, after the operator's own rules; an
        # absent block or list is created. Never the deny list: a deny the
        # operator removed is a judgement, a missing allow is friction.
        permissions = dict(existing.get("permissions") or {})
        allow = list(permissions.get("allow") or [])
        allow.extend(missing_allows)
        permissions["allow"] = allow
        merged["permissions"] = permissions
        added = list(missing_allows)
    if add_statusline:
        # After the operator's keys, like an appended event: their order is
        # kept (no sort_keys below) and the new key lands last.
        merged["statusLine"] = dict(canonical_statusline)
    # Back up the original verbatim before overwriting (operator can revert).
    backup_path = _back_up_settings(settings_path)
    # Preserve the operator's key order (no sort_keys); hooks is appended/updated
    # in place. Deliberately do NOT stamp `_espalier_managed`: this remains the
    # operator's hand-editable file, so future `init` keeps preserving it.
    atomic_write_text(settings_path, json.dumps(merged, indent=2) + "\n", follow_symlinks=True)
    return MergeResult(
        MERGE_WIRED, detail=backup_path.name, event_count=topped_up_events,
        missing_allows=() if added else tuple(missing_allows),
        added_allows=tuple(added), allow_note=allow_note,
        statusline_added=add_statusline,
    )


REPAIR_DONE = "repaired"      # entries rewritten; detail = .bak filename
REPAIR_NOTHING = "nothing"    # every deployed espalier hook already executably wired
REPAIR_REFUSED = "refused"    # the file is one the merge refuses, or its hooks block is voided
#: The one refusal kind the repair adds to the merge's: rendered by
#: ``_report_hook_repair`` itself, since the plain merge never produces it
#: (it tops up a null event; the repair cannot edit inside a block Claude
#: Code discards whole).
REPAIR_REFUSED_VOIDED = "voided"


class RepairResult(NamedTuple):
    """Outcome of :func:`repair_hook_wiring_in_settings`.

    ``changes`` is one ``(script, shape, action)`` per entry rewritten;
    ``still_unwired`` is the wiring oracle's answer AFTER the write (or now, on
    ``REPAIR_NOTHING``) -- a repair that reports success without re-deriving
    its post-condition is the DEF-620 shape, so every caller prints it.
    """

    status: str
    detail: str = ""
    changes: tuple[tuple[str, str, str], ...] = ()
    still_unwired: tuple[str, ...] = ()
    strays: tuple[str, ...] = ()


def _entry_blob(entry: dict) -> str:
    args = entry.get("args")
    return " ".join(
        str(x) for x in [entry.get("command"), *(args if isinstance(args, list) else [])]
        if isinstance(x, str)
    )


def _blob_names_script(entry: object, script: str) -> bool:
    """Does this hook entry carry ``script`` as a whole path token? The SAME
    reading ``harness_config._gate_command_blobs`` makes
    (:func:`harness_config.blob_names_script`: basename equality per token,
    never a substring), so the repair touches exactly the entries the oracle
    classified and an operator's ``my_plan_guard.py`` or
    ``tests/test_write_guard.py`` argument is never read as ours. An operator
    entry that carries the exact basename as DATA (a wrapper logging our path)
    is still read as ours -- so every removal is NAMED in the report."""
    if not isinstance(entry, dict):
        return False
    return blob_names_script(_entry_blob(entry), script)


def _canonical_group_for(canonical_hooks: dict, script: str) -> dict | None:
    """The canonical event group (matcher + hooks) whose entry names ``script``."""
    for groups in canonical_hooks.values():
        for group in groups:
            if any(_blob_names_script(e, script) for e in group.get("hooks", [])):
                return copy.deepcopy(group)
    return None


def _remove_entries_naming(hooks: dict, script: str) -> list[tuple[str, dict]]:
    """Drop every entry naming ``script`` from every event; drop a group only
    when the removal empties it (an operator's own entries sharing the group
    stay, with their matcher). Returns ``(event, entry)`` for each removal, so
    the caller can NAME what went -- an operator entry that mentions the exact
    basename as data is removed too, and a removal nobody is told about is the
    failure the report exists to prevent."""
    removed: list[tuple[str, dict]] = []
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            kept = [e for e in group["hooks"] if not _blob_names_script(e, script)]
            removed.extend((event, e) for e in group["hooks"] if _blob_names_script(e, script))
            if kept or len(group["hooks"]) == 0:
                new_group = dict(group)
                new_group["hooks"] = kept
                kept_groups.append(new_group)
            # else: the group held only our entry -- drop it whole
        hooks[event] = kept_groups
    return removed


#: The shapes ``repair_hook_wiring_in_settings`` rewrites, and the ones it
#: deliberately leaves alone. Their union is pinned to ``GATE_SHAPES`` in
#: tests/test_hook_event_contracts.py, so a new shape reds here until it is
#: filed on one side -- otherwise it would fall out of the dispatch silently
#: while both narrators pointed at ``--repair`` for it.
_REPAIR_HANDLED_SHAPES = frozenset({
    GATE_ABSENT, GATE_ORPHANED, GATE_INERT, GATE_LEGACY_FORM, GATE_MISWIRED,
})
_REPAIR_SKIPPED_SHAPES = frozenset({GATE_VOIDED_SETTINGS})  # refused whole, above


def _describe_entry(entry: dict) -> str:
    return _entry_blob(entry) or json.dumps(entry, sort_keys=True)[:80]


def _stray_espalier_entries(hooks: dict, canonical_hooks: dict) -> list[str]:
    """Canonical scripts that ALSO appear under an event other than their
    own. The oracle reads such a gate as wired (its canonical entry is live),
    so the repair never touches the copy; it is reported, not removed."""
    strays: list[str] = []
    for script in sorted(CANONICAL_HOOK_WIRING):
        home = GATE_EVENT_OF(script)
        for event, groups in hooks.items():
            if event == home or not isinstance(groups, list):
                continue
            for group in groups:
                if isinstance(group, dict) and any(
                    _blob_names_script(e, script) for e in (group.get("hooks") or [])
                    if isinstance(e, dict)
                ):
                    strays.append(f"{script} under {event!r}")
    return strays


def repair_hook_wiring_in_settings(
    settings_path: Path | str, repo_root: Path, *, profile: str | None = None,
) -> RepairResult:
    """Rewrite espalier's OWN hook entries to canonical wherever the wiring
    oracle finds them dead -- the opt-in behind ``merge-settings --repair``
    (DEF-618).

    The plain merge's unit of work is the EVENT, by a pinned contract: it tops
    up a missing event and never touches an entry inside an existing one, so
    an entry that runs no interpreter, is missing from an event that exists,
    sits under the wrong event or with a narrowed matcher, or is still in the
    pre-v0.6.5 shell form, had a hand edit as its only remedy on every surface.
    This function is that hand edit, done by the tool that knows the canonical
    shape, for BOTH tiers (gates and reporters), on the operator's explicit
    request:

    * only entries naming a canonical ``tools/cc/hooks/<script>`` are touched;
      an operator's own hooks, ``permissions`` and every other key are left
      byte-for-byte (an operator entry sharing a group keeps the group and its
      matcher; ours is re-added in a fresh canonical group);
    * a file the merge would refuse, or whose hooks block is voided by some
      entry's ``type``, is refused with the reason and left unwritten;
    * a ``.bak`` of the pre-write bytes is kept first, via the merge's own
      helper (written, or the rung that already holds them);
    * the post-condition is RE-DERIVED from the written file and returned in
      ``still_unwired`` -- the caller prints it, so a repair can never report
      success over a gate it left dead (the DEF-620 shape).

    ``GATE_ABSENT`` is handled too (the event and its entry are added), so
    ``--repair`` on its own leaves a tree fully wired; the plain merge is still
    run first by the command, for the allow-rule reporting it owns.
    """
    settings_path = Path(settings_path)
    refused = merge_refusal_for_file(settings_path, repo_root)
    if refused:
        return RepairResult(REPAIR_REFUSED, detail=refused)
    voided = surface_contract.hooks_config_voided_by(
        surface_contract._load_settings_hooks_cfg(repo_root)
    )
    if voided is not None:
        return RepairResult(REPAIR_REFUSED, detail=f"{REPAIR_REFUSED_VOIDED}: {voided}")
    existing = json.loads(surface_contract.decode_bom(settings_path.read_bytes()))
    if not isinstance(existing, dict):
        # Unreachable past merge_refusal_for_file (it refuses a non-object),
        # kept so this loader cannot become a fail-open if that predicate moves.
        return RepairResult(REPAIR_REFUSED, detail=f"{MERGE_REFUSED_NOT_OBJECT}: {type(existing).__name__}")
    hooks = existing.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    new_hooks: dict = copy.deepcopy(hooks)
    canonical_hooks = _build_settings_json(profile_name=profile, repo_root=repo_root)["hooks"]

    shapes: dict[str, list[str]] = {}
    for tier_shapes in (
        group_unwired_gates_by_shape(repo_root),
        group_unwired_reporters_by_shape(repo_root),
    ):
        for shape, scripts in tier_shapes.items():
            shapes.setdefault(shape, []).extend(scripts)

    changes: list[tuple[str, str, str]] = []
    for shape in sorted(shapes):
        if shape not in _REPAIR_HANDLED_SHAPES:
            continue  # voided is refused above; a shape not filed on either side reds in the roster test
        for script in sorted(shapes[shape]):
            group = _canonical_group_for(canonical_hooks, script)
            if group is None:
                continue  # not a canonical hook of this profile; not ours
            event = GATE_EVENT_OF(script)
            if shape == GATE_ABSENT:
                new_hooks.setdefault(event, []).append(group)
                action = f"added the {event!r} event with its entry"
            elif shape == GATE_ORPHANED:
                new_hooks.setdefault(event, []).append(group)
                action = f"added the entry under the existing {event!r} event"
            else:
                removed = _remove_entries_naming(new_hooks, script)
                new_hooks.setdefault(event, []).append(group)
                if shape == GATE_INERT:
                    action = "replaced the entry that ran no interpreter"
                elif shape == GATE_LEGACY_FORM:
                    action = "converted the shell-form entry to exec form"
                else:
                    action = "rewired it: was " + miswiring_detail(repo_root, script)
                # NAME every removal, with the keys the canonical entry does not
                # carry (an operator's raised timeout, a note): the .bak is then
                # actionable rather than archaeological, and an operator entry
                # that merely mentioned the exact basename is not lost in silence.
                canonical_entry = group["hooks"][0] if group.get("hooks") else {}
                notes = []
                for ev, entry in removed:
                    dropped = sorted(
                        k for k, v in entry.items()
                        if canonical_entry.get(k) != v and k not in ("command", "args", "type")
                    )
                    notes.append(
                        f"removed from {ev!r}: `{_describe_entry(entry)}`"
                        + (f" (dropped your {', '.join(f'{k}={entry[k]!r}' for k in dropped)})"
                           if dropped else "")
                    )
                if notes:
                    action += "; " + "; ".join(notes)
            changes.append((script, shape, action))
    strays = tuple(_stray_espalier_entries(new_hooks, canonical_hooks))
    if not changes:
        deployed_any = any(
            (repo_root / "tools" / "cc" / "hooks" / script).is_file()
            for script in CANONICAL_HOOK_WIRING
        )
        return RepairResult(
            REPAIR_NOTHING,
            detail="" if deployed_any else "nothing-deployed",
            still_unwired=tuple(
                sorted(unwired_governance_gates(repo_root) + unwired_reporter_hooks(repo_root))
            ),
            strays=strays,
        )
    merged = dict(existing)
    merged["hooks"] = new_hooks
    backup_path = _back_up_settings(settings_path)
    atomic_write_text(settings_path, json.dumps(merged, indent=2) + "\n", follow_symlinks=True)
    still = sorted(unwired_governance_gates(repo_root) + unwired_reporter_hooks(repo_root))
    return RepairResult(
        REPAIR_DONE, detail=backup_path.name, changes=tuple(changes),
        still_unwired=tuple(still), strays=strays,
    )


def _report_hook_repair(result: RepairResult, py: str) -> None:
    """Say exactly what ``--repair`` did, and what it did NOT -- the
    re-derived post-condition is printed on every branch, to stderr, since
    it is the warning half of the report."""
    if result.status == REPAIR_REFUSED:
        kind, _sep, detail = result.detail.partition(": ")
        if kind == REPAIR_REFUSED_VOIDED:
            why = (
                f"fix {detail} in .claude/settings.json -- Claude Code discards "
                "the whole hooks block over it, and --repair cannot edit inside "
                "a block that is not loaded"
            )
        else:
            why = merge_refusal_step(result.detail, py)
        print(
            f"merge-settings --repair refused .claude/settings.json: {why}. "
            "Nothing was rewritten; the plain merge below still runs.",
            file=sys.stderr,
        )
    elif result.status == REPAIR_NOTHING:
        if result.detail == "nothing-deployed":
            print(
                "merge-settings --repair: nothing deployed to repair -- no "
                "espalier hook script is on disk under tools/cc/hooks/."
            )
        elif not result.still_unwired:
            print(
                "merge-settings --repair: nothing to repair -- every deployed "
                "espalier hook is executably wired."
            )
        else:
            print(
                "merge-settings --repair: nothing this command can repair, and "
                + ", ".join(result.still_unwired)
                + (" is" if len(result.still_unwired) == 1 else " are")
                + f" still not executably wired -- run `{py} -m espalier doctor .` "
                "for the shape.",
                file=sys.stderr,
            )
    else:
        print(
            f"merge-settings --repair: rewrote {len(result.changes)} espalier hook "
            f"{'entry' if len(result.changes) == 1 else 'entries'} in "
            f".claude/settings.json (backup at {result.detail}); entries that do "
            "not name espalier's scripts, permissions and every other key were "
            "left as they were; every removal is listed:"
        )
        for script, shape, action in result.changes:
            print(f"    {script} ({shape}): {action}")
        if result.still_unwired:
            print(
                "merge-settings --repair: STILL not executably wired after the "
                "rewrite: " + ", ".join(result.still_unwired)
                + f" -- run `{py} -m espalier doctor .`; the pre-rewrite file is "
                f".claude/{result.detail}.",
                file=sys.stderr,
            )
    if result.strays:
        print(
            "merge-settings --repair: left in place (a copy under an event that "
            "is not its own, while the canonical entry is live): "
            + "; ".join(result.strays)
            + " -- remove the copy by hand if you did not mean it.",
            file=sys.stderr,
        )


def _report_interpreter_rewire(settings_path: Path) -> str:
    """Run the rewire and say, on stderr, exactly what changed.

    Every status gets a sentence naming what the operator should do next --
    a repair verb that reports only "done" or nothing is how ``DEF-620``'s
    no-op survived: the operator re-ran it, saw success, and re-ran ``doctor``
    to find the identical failure. Returns the status for callers/tests.
    """
    result = rewire_interpreter_in_settings(settings_path)
    if result.status == REWIRE_DONE:
        print(
            f"--rewire-interpreter: rewired "
            f"{plural(len(result.changes), 'hook command')} in "
            f".claude/settings.json (backup at {result.detail}). Only the "
            f"interpreter name changed; your args and other keys were preserved.",
            file=sys.stderr,
        )
        for where, old_command, new_command in result.changes:
            print(f"    {where}: `{old_command}` -> `{new_command}`", file=sys.stderr)
    elif result.status == REWIRE_NOTHING:
        print(
            f"--rewire-interpreter: nothing to rewire -- every interpreter this "
            f"command can read already meets Python {floor_text()}+. No file "
            f"was written.",
            file=sys.stderr,
        )
    if result.declined:
        # NEVER folded into the all-clear above. Saying "everything passes"
        # while skipping sites the walk could not parse is exactly how DEF-620
        # survived: a repair that reports success and changes nothing.
        print(
            f"WARN: --rewire-interpreter left "
            f"{plural(len(result.declined), 'Python hook command')} alone "
            f"because the command shape is not a bare interpreter -- the `py` "
            f"launcher (its `-3` is a LAUNCHER flag, and rewriting argv[0] "
            f"alone would brick every hook), an unterminated quote, or a script "
            f"run by its shebang. Fix these by hand:",
            file=sys.stderr,
        )
        for where, command in result.declined:
            print(f"    {where}: `{command}`", file=sys.stderr)
    elif result.status == REWIRE_UNREADABLE:
        print(
            f"--rewire-interpreter: .claude/settings.json could not be read "
            f"({result.detail}) -- fix its permissions, then re-run. Your file "
            "was NOT modified.",
            file=sys.stderr,
        )
    elif result.status == REWIRE_NO_FILE:
        print(
            f"--rewire-interpreter: no .claude/settings.json to rewire. Run "
            f"`{_remedy_py()} -m espalier init .` first to "
            f"create one.",
            file=sys.stderr,
        )
    elif result.status == REWIRE_NO_TARGET:
        print(
            f"WARN: --rewire-interpreter found no interpreter on PATH meeting "
            f"Python {floor_text()}+ (best candidate: `{result.detail}`), so "
            f"nothing was changed. Rewiring to an interpreter that fails the "
            f"same floor would report success and fix nothing. Install Python "
            f"{floor_text()} or newer first.",
            file=sys.stderr,
        )
    elif result.status == REWIRE_DUPLICATE_KEYS:
        print(
            f"WARN: --rewire-interpreter refused .claude/settings.json: it has a "
            f"{result.detail}. JSON keeps the LAST of a repeated key, so "
            f"rewriting the file would silently DELETE the earlier block -- "
            f"possibly your own hooks. Your file was NOT modified. Merge the "
            f"duplicate by hand, then re-run.",
            file=sys.stderr,
        )
    elif result.status not in (REWIRE_DONE, REWIRE_NOTHING):
        # Only a refusal lands here. This used to be a bare `else`, and the
        # chain above it starts fresh at `if result.declined`, so a DONE or
        # NOTHING run with no declines fell through to "refused ... Fix the
        # JSON by hand" directly under its own success line (driven).
        print(
            f"WARN: --rewire-interpreter refused .claude/settings.json "
            f"({result.status}: {result.detail}). Your file was NOT modified. "
            f"Fix the JSON by hand, then re-run.",
            file=sys.stderr,
        )
    return result.status


REWIRE_DONE = "rewired"            # interpreter swapped; detail = .bak filename
REWIRE_NOTHING = "nothing"         # every wired interpreter already clears the floor
REWIRE_NO_FILE = "no_file"         # no settings.json to rewire
REWIRE_UNREADABLE = "unreadable"   # a parent of settings.json denies traversal; detail = OS message
REWIRE_PARSE_ERROR = "parse_error"  # settings.json is not valid JSON
REWIRE_NOT_OBJECT = "not_object"   # top-level JSON is not an object
REWIRE_NO_TARGET = "no_target"     # nothing on PATH clears the floor either
REWIRE_DUPLICATE_KEYS = "duplicate_keys"  # settings.json has a repeated key


@dataclass
class RewireResult:
    """Result of :func:`rewire_interpreter_in_settings`."""

    status: str
    detail: str = ""
    #: ``(json_path, old_command, new_command)`` per site changed, for the
    #: operator-facing report. Empty on every non-``REWIRE_DONE`` status.
    changes: list = field(default_factory=list)
    #: ``(json_path, command)`` per Python site RECOGNISED but deliberately not
    #: rewritten (the ``py`` launcher, an unterminated quote, a shebang script).
    #: Reported, never silent: an all-clear that covers sites the walk never
    #: examined is the DEF-620 shape the whole verb exists to close.
    declined: list = field(default_factory=list)


def _swap_interpreter_token(command: str, new_name: str) -> str:
    """Replace ONLY argv[0] of ``command``, leaving the rest byte-for-byte.

    Exec form (``"python3"``) and legacy shell form
    (``"python tools/cc/hooks/write_guard.py"``) are the same operation: swap
    the leading token. Quoting survives because
    :func:`~espalier._venv.interpreter_token` returns the token WITHOUT its
    quotes, so the surrounding quotes are outside the replaced span --
    ``'"C:\\Program Files\\python.exe" x.py'`` keeps both quotes.
    """
    head = interpreter_token(command)
    if not head:
        return command
    start = 0
    old = head
    if is_statusline_shim_head(head):
        # The Windows statusline shim is the head and the interpreter is its
        # first argument (DEF-729): swap THAT word, searching past the head so
        # a shim path that happens to contain the interpreter's name is safe.
        # The offset is measured on the unstripped string: trailing
        # whitespace from a hand edit once put it past the word.
        old = interpreter_site_token(command)
        start = after_head_index(command, head)
        if not old or start < 0:
            return command
    idx = command.find(old, start)
    if idx < 0:  # unreachable via the token readers, but never corrupt on a surprise
        return command
    return command[:idx] + new_name + command[idx + len(old):]


def _same_file(a: str, b: str) -> bool:
    """``os.path.samefile`` that answers False instead of raising."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


def _interpreter_base_name(token: str) -> str:
    """``/usr/bin/python3.11`` -> ``python3.11``; ``py.exe`` -> ``py``."""
    base = Path(token).name
    if base.lower().endswith(".exe"):
        base = base[: -len(".exe")]
    return base


def _is_python_interpreter_site(token: str) -> bool:
    """Does ``token`` name a Python interpreter at all?

    Wider than :func:`_is_rewirable_interpreter`: this is "is this site about
    Python", used to tell a site we DECLINED from a site that was never ours.
    Reporting "every wired interpreter already meets the floor" while silently
    skipping python sites we could not parse is the DEF-620 shape one level in.
    """
    if not token or "${" in token:
        return False
    base = _interpreter_base_name(token)
    return base == "py" or base.startswith("python")


def _is_rewirable_interpreter(token: str) -> bool:
    """Is ``token`` a python-like name this may SAFELY replace?

    Deliberately narrow, because a wrong rewrite here bricks every hook. An
    unexpanded ``${...}``, or a bare script run by its shebang (``.py``/``.sh``),
    is not an interpreter name -- the same exclusions
    ``doctor._check_python_resolver`` applies.

    Two refusals both driven, not imagined (adversarial pass, 2026-09-03):

    * **``py`` -- the Windows Python Launcher -- is refused.** Its ``-3`` /
      ``-3.11`` are LAUNCHER flags, not interpreter flags, and this function's
      caller only swaps argv[0]: ``py -3 <hook>`` became ``python3 -3 <hook>``,
      which exits non-zero with ``Unknown option: -3``. From a PreToolUse hook
      that is a BLOCK, so the repair command bricked every tool call in the
      session. The harness manufactures this input itself -- ``doctor`` tells
      Windows operators to try ``py -3``.
    * **A token containing whitespace is refused.** argv[0] never has any; the
      token only looks that way when ``interpreter_token`` hits an unterminated
      quote and returns the rest of the line. Swapping then DELETED every
      argument (``"python3 -u -m x hook`` -> ``"python3``) while the report
      said "your args were preserved". An unclosed quote around a Windows path
      with spaces is the likeliest hand-edit typo on this exact surface.
    """
    if not _is_python_interpreter_site(token):
        return False
    if token.endswith((".py", ".sh")):
        return False
    if any(ch.isspace() for ch in token):
        return False
    return _interpreter_base_name(token) != "py"


def rewire_interpreter_in_settings(
    settings_path: Path, *, new_interpreter: str | None = None,
) -> RewireResult:
    """Swap below-floor Python interpreters in an existing ``settings.json``.

    Closes ``DEF-620``. ``doctor`` told an adopter to "re-run `init` to rewire
    the hook commands with an interpreter that resolves on this host", but
    ``init`` does not overwrite an existing ``settings.json`` (user
    sovereignty), so the step was a no-op the adopter could follow forever --
    measured before and after: ``group_unwired_gates_by_shape`` returned the
    identical ``{'legacy_form': [...]}`` both times.

    Deliberately narrow, because this writes a file the operator owns:

    * **Only argv[0] of a hook command changes.** Every other key, every
      ``args`` entry, every permission -- untouched. The file is re-serialised
      with ``indent=2``, exactly as ``merge_hooks_into_settings`` already does.
    * **Only interpreters that FAIL the floor are touched.** One already
      clearing ``MIN_PYTHON`` is left alone even if it spells a different name,
      so the command is idempotent and creates no ``.bak`` churn.
    * **A ``.bak`` of the pre-write bytes is kept first**, via the same helper
      the merge path uses (written, or the rung that already holds them).
    * **A malformed file is refused, never clobbered** -- the operator's
      content is not this function's to destroy.

    Covers all 13 interpreter sites: the 12 ``hooks[*].hooks[*].command``
    entries plus ``statusLine.command``, which lives outside ``hooks`` and is
    a shell string.
    """
    settings_path = Path(settings_path)
    presence, unreadable_detail = surface_contract.path_presence(settings_path)
    if presence == surface_contract.PRESENCE_ABSENT:
        return RewireResult(REWIRE_NO_FILE)
    if presence == surface_contract.PRESENCE_UNREADABLE:
        return RewireResult(REWIRE_UNREADABLE, detail=unreadable_detail)
    def _reject_duplicates(pairs):
        # `json.loads` keeps the LAST duplicate key, and re-serialising then
        # PERSISTS the loss -- driven: a settings.json with two `PreToolUse`
        # blocks came back with the operator's own `node` hook silently gone.
        # Refusing is the only safe answer; this function may not quietly
        # delete a block the operator wrote.
        seen = set()
        for key, _ in pairs:
            if key in seen:
                raise ValueError(f"duplicate key {key!r}")
            seen.add(key)
        return dict(pairs)

    try:
        existing = json.loads(
            surface_contract.decode_bom(settings_path.read_bytes()),
            object_pairs_hook=_reject_duplicates,
        )
    except ValueError as exc:
        # ValueError covers JSONDecodeError AND the duplicate-key raise above.
        if "duplicate key" in str(exc):
            return RewireResult(REWIRE_DUPLICATE_KEYS, detail=str(exc))
        return RewireResult(REWIRE_PARSE_ERROR, detail=str(exc))
    except OSError as exc:
        # The file itself could not be read (a mode-000 settings.json): not a
        # parse failure, and the merge's own split says the same (DEF-763).
        return RewireResult(REWIRE_UNREADABLE, detail=os_error_text(exc))
    except UnicodeDecodeError as exc:
        return RewireResult(REWIRE_PARSE_ERROR, detail=str(exc))
    if not isinstance(existing, dict):
        return RewireResult(REWIRE_NOT_OBJECT, detail=type(existing).__name__)

    # Every (container, key, json_path) holding an interpreter command.
    sites: list[tuple[dict, str, str]] = []
    hooks = existing.get("hooks")
    if isinstance(hooks, dict):
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            for gi, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                inner = group.get("hooks")
                if not isinstance(inner, list):
                    continue
                for hi, entry in enumerate(inner):
                    if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                        sites.append((entry, "command", f"hooks.{event}[{gi}].hooks[{hi}]"))
    status_line = existing.get("statusLine")
    if isinstance(status_line, dict) and isinstance(status_line.get("command"), str):
        sites.append((status_line, "command", "statusLine"))

    stale, declined = [], []
    for container, key, where in sites:
        # argv[0], or argv[1] behind the Windows statusline shim (DEF-729);
        # doctor's resolver check reads the same helper.
        token = interpreter_site_token(container[key])
        if not _is_python_interpreter_site(token):
            continue  # not a Python site at all -- never ours to touch
        if not _is_rewirable_interpreter(token):
            # A Python site we recognise but must not rewrite (the `py`
            # launcher, an unterminated quote, a shebang script). Counted, so
            # the all-clear below cannot claim a site it never examined.
            declined.append((where, container[key]))
            continue
        if not interpreter_meets_floor(token):
            stale.append((container, key, where))
    if not stale:
        return RewireResult(REWIRE_NOTHING, declined=declined)

    target = new_interpreter or _detect_python_command()
    # Refuse rather than wire a name that fails the same floor. Rewiring 3.9 to
    # 3.9 would report success and change nothing -- the exact shape of the
    # defect this function exists to close.
    if not interpreter_meets_floor(target):
        return RewireResult(REWIRE_NO_TARGET, detail=target)

    # ⚠ DEF-636, RE-CREATED INSIDE ITS OWN REPAIR, and driven on this host: the
    # floor above is checked against the PATH of the shell running THIS command,
    # then a bare NAME is written into a file that outlives that shell.
    # Claude Code is routinely launched from the Dock/launchd with a minimal
    # PATH, where `python3` resolves to /usr/bin/python3 -- 3.9.6, below the
    # floor. The repair printed success and left exactly the state
    # `_python_floor`'s docstring calls the defect. `_venv.py` names this trap
    # for the venv case; this is its sibling, the resolves-to-something-OLDER
    # case. Write the absolute path when the two resolutions disagree AND the
    # minimal one fails -- unambiguous under any launcher.
    resolved = shutil.which(target)
    minimal = shutil.which(target, path=os.defpath)
    if resolved and minimal and not _same_file(resolved, minimal):
        if not interpreter_meets_floor(minimal):
            target = resolved

    changes = []
    for container, key, where in stale:
        old_command = container[key]
        new_command = _swap_interpreter_token(old_command, target)
        if new_command == old_command:
            # A site can land here without changing: the floor probe has a 2s
            # timeout, and a shim that is slow ONCE (pyenv/asdf on a loaded
            # box) reads as below-floor. Writing then produced an identical
            # file, a real `.bak`, and a "rewired 1 hook command" report --
            # and a repeat run produced `.bak.1`, `.bak.2`, ... Compare the
            # rendered strings, not the probe verdict.
            continue
        container[key] = new_command
        changes.append((where, old_command, new_command))
    if not changes:
        return RewireResult(REWIRE_NOTHING, declined=declined)

    backup_path = _back_up_settings(settings_path)
    # ensure_ascii=False: escaping the operator's own non-ASCII paths back to
    # \uXXXX is a gratuitous rewrite of content this function does not own.
    atomic_write_text(
        settings_path,
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        follow_symlinks=True,
    )
    return RewireResult(REWIRE_DONE, detail=backup_path.name,
                        changes=changes, declined=declined)


#: Paths Espalier itself deploys under ``tools/cc/``. Derived from the deploy
#: lists, never hand-typed, so it cannot go stale when a hook is added.
#: ``_missing_wired_hook_scripts`` checks ONLY these: an operator's own hook that
#: happens to sit under a ``tools/cc/`` path is not ours to judge, and reporting
#: it as "missing enforcement" would be friction against a correct tree.
def _espalier_deployed_scripts() -> frozenset[str]:
    return frozenset(INIT_HOOK_SCRIPTS) | frozenset(INIT_TOOL_SCRIPTS)


def _wired_espalier_entries(
    settings_path: Path,
) -> list[tuple[str | None, list[str]]] | None:
    """Every hook entry in ``settings_path`` that names an Espalier-deployed
    script, as ``(command, [repo-relative paths it names])``; ``None`` when the
    file cannot be read or parsed.

    ONE walker for the enforcement claim's per-entry arms -- the existence arm
    (:func:`_missing_from_entries`) and the identity arm
    (:func:`_not_python3_from_entries`) -- so the two cannot disagree about
    which entries are ours; :func:`_enforcement_claim_blockers` and
    :func:`_disarmed_diagnosis` each read the file ONCE and hand the entries
    to both. Derived from the settings file that was just
    written, not from a hand-maintained path list (STANDING_PRINCIPLES §14):
    the question is "what did THIS file wire?", so reading it back is the only
    answer that cannot go stale when the deploy list changes. An entry that
    names no deployed script is not ours to judge -- an operator's own hook
    under a ``tools/cc/`` path, a ``node`` reporter -- and is omitted.

    ⚠ ``None`` is NOT "nothing wired". An unverifiable settings file is exactly
    the state the claim exists to refuse to make a claim about, so callers
    withhold the enforcement assertion rather than print it. Returning ``[]``
    here would restore the defect the existence arm was added to close, gated
    behind an I/O failure instead of unconditionally.

    Reads through ``surface_contract.decode_bom`` for the same reason every
    other settings reader in this module does (``merge_hooks_into_settings``,
    ``_settings_has_espalier_hooks``): PowerShell's ``Out-File`` writes UTF-16LE
    by default and editors add a UTF-8 BOM, and a bare
    ``read_text(encoding="utf-8")`` raises ``UnicodeDecodeError`` on the first --
    a ``ValueError``, not a ``JSONDecodeError`` -- which escaped the handler and
    crashed the command on a healthy Windows tree.
    """
    try:
        data = json.loads(
            surface_contract.decode_bom(settings_path.read_bytes())
        )
    except (OSError, ValueError):
        # ValueError covers BOTH json.JSONDecodeError and UnicodeDecodeError.
        return None
    if not isinstance(data, dict):
        return None

    deployed = _espalier_deployed_scripts()

    def _deployed_rel(candidate: object) -> str | None:
        if not isinstance(candidate, str):
            return None
        norm = candidate.replace("\\", "/")
        idx = norm.find("tools/cc/")
        if idx == -1:
            return None
        # Cut at the first quote or whitespace: the legacy shell form spells the
        # hook as `python3 "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/x.py"`, and
        # keeping the trailing quote made every path fail to resolve -- reporting
        # a fully-armed tree as disarmed.
        rel = _WIRED_PATH_END_RE.split(norm[idx:], 1)[0]
        return rel if rel and rel in deployed else None

    hooks_cfg = data.get("hooks")
    if hooks_cfg is None:
        # ABSENT is legitimate and common: it is the brought-your-own adopter
        # whose file wires nothing. That is "no hooks", not "unreadable" -- the
        # caller must be able to tell those apart, because one of them has a
        # remedy and the other is a broken file.
        hooks_cfg = {}
    if not isinstance(hooks_cfg, dict):
        # `hooks` may be any JSON type in a hand-edited file. `or {}` is not a
        # guard: a truthy non-dict (42, "on", a list) sails through it and
        # AttributeErrors on .values(). Driven -- {"hooks": 42} crashed init
        # rc=1 on an adopter tree whose file we had already refused to touch.
        return None
    entries: list[tuple[str | None, list[str]]] = []
    for groups in hooks_cfg.values():
        if not isinstance(groups, list):
            continue
        for entry in groups:
            if not isinstance(entry, dict):
                continue
            hooks_list = entry.get("hooks")
            if not isinstance(hooks_list, list):
                continue
            for hook in hooks_list:
                if not isinstance(hook, dict):
                    continue
                # Depth 2. The docstring above says "`or {}` is not a guard: a
                # truthy non-dict sails through it" -- and then the first
                # draft applied that only at depth 1. `args` is any JSON
                # type in a hand-edited file; a scalar made `init` exit 1
                # with a traceback and a PARTIAL DEPLOY, on the first
                # command a new adopter runs.
                args = hook.get("args")
                command = hook.get("command")
                rels: list[str] = []
                for candidate in [*(args if isinstance(args, list) else []), command]:
                    rel = _deployed_rel(candidate)
                    if rel and rel not in rels:
                        rels.append(rel)
                if rels:
                    entries.append((command if isinstance(command, str) else None, rels))
    return entries


def _missing_from_entries(
    repo_root: Path, entries: list[tuple[str | None, list[str]]],
) -> list[str]:
    """The existence arm over walked entries: the deployed scripts they name
    that are NOT on disk, sorted."""
    return sorted({
        rel
        for _command, rels in entries
        for rel in rels
        if not (repo_root / rel).is_file()
    })


def _missing_wired_hook_scripts(
    repo_root: Path, settings_path: Path
) -> list[str] | None:
    """The Espalier-deployed scripts a wired settings.json points at that do
    NOT exist on disk -- the existence arm of the enforcement claim, reading
    the file itself. ``None`` when the file cannot be read; that rule, and the
    walk, are :func:`_wired_espalier_entries`'s.
    """
    entries = _wired_espalier_entries(settings_path)
    if entries is None:
        return None
    return _missing_from_entries(repo_root, entries)


def _wired_interpreters_not_python3(
    settings_path: Path,
) -> dict[str, tuple[str | None, list[str]]] | None:
    """The identity arm of the enforcement claim, reading the file itself:
    :func:`_not_python3_from_entries` over :func:`_wired_espalier_entries`, or
    ``None`` when the settings cannot be read."""
    entries = _wired_espalier_entries(settings_path)
    if entries is None:
        return None
    return _not_python3_from_entries(entries)


def _not_python3_from_entries(
    entries: list[tuple[str | None, list[str]]],
) -> dict[str, tuple[str | None, list[str]]]:
    """The identity arm of the enforcement claim: each interpreter word a wired
    Espalier entry runs under that does NOT answer as a Python 3, mapped to
    ``(what it resolves to or None, [the deployed scripts wired through it])``.

    The other two arms ask whether the wired PATHS resolve and whether each
    entry is EXECUTABLE in shape; neither runs the interpreter. On the Windows
    walk 2 host (``DEF-727``) ``python`` was a Python 2 shim: every path
    resolved, every entry was canonical exec-form, and every hook exited 0 with
    a version banner on stdout -- not JSON, not a decision, so NON-BLOCKING --
    while ``init`` printed "Hooks now intercept Claude Code tool calls". A word
    that does not resolve at all (a settings.json committed from another OS)
    is the same non-decision one step earlier.

    IDENTITY, not the floor: the question is ``doctor._interpreter_is_python3``'s,
    called through the module so the seam tests patch there serves this caller
    too. A below-floor 3.9 answers True and passes -- the blocking guards run
    on it, and only the blueprint chain is lost (``DEF-636``'s half, which
    ``doctor`` and the wiring warnings own). Blocking the claim there would
    tell a 3.9 host its guards are off when they are on.

    Only python-shaped words are asked (:func:`_is_python_interpreter_site`);
    ``echo``, ``node`` and a shell string are the executability arm's shapes.
    Each distinct word is probed once per call, so twelve sites cost one spawn
    -- none at all when the word is the interpreter running this process -- and
    a word that resolved but did not answer is asked once more before the claim
    is withheld: the probe has a 2 s timeout, and a shim that is slow ONCE
    (pyenv/asdf on a loaded box) reads as not-Python-3 -- the flake
    :func:`rewire_interpreter_in_settings` records. A false "NOT yet active"
    is a false alarm the operator can re-run, never a false all-clear, so the
    arm asserts rather than abstains; the retry keeps the alarm rare.
    """
    verdicts: dict[str, tuple[str | None, bool]] = {}
    failing: dict[str, list[str]] = {}
    for command, rels in entries:
        token = interpreter_token(command or "")
        if not _is_python_interpreter_site(token):
            continue
        if token not in verdicts:
            resolved = shutil.which(token) or (
                token if Path(token).is_file() else None
            )
            answered = _doctor._interpreter_is_python3(resolved)
            if resolved and not answered:
                # A genuine Python 2 answers fast, so the retry costs it little;
                # a slow shim gets the second chance the docstring describes.
                answered = _doctor._interpreter_is_python3(resolved)
            verdicts[token] = (resolved, answered)
        if verdicts[token][1]:
            continue
        bucket = failing.setdefault(token, [])
        bucket.extend(rel for rel in rels if rel not in bucket)
    return {
        token: (verdicts[token][0], sorted(rels)) for token, rels in failing.items()
    }


#: Sentinel for "the caller did not pre-walk the settings"; distinct from
#: ``None``, which is the walker's own "could not read the file".
_ENTRIES_UNREAD: object = object()


def _enforcement_claim_blockers(
    repo_root: Path, settings_path: Path, *, entries: object = _ENTRIES_UNREAD,
) -> list[str] | None:
    """Everything that forbids asserting "enforcement is active", or ``None``
    when the settings file cannot be read.

    The union of three oracles, because each is blind exactly where the others
    see (the first two measured 2026-08-27 across four trees; the third driven
    on the Windows walk 2 host, 2026-09-09):

    * ``_missing_wired_hook_scripts`` -- do the wired paths RESOLVE on disk?
      Catches the tree where ``tools/cc/`` was never deployed. Reads a gate
      wired to ``echo`` as clean: the path is right, the file is there, and
      nothing runs.
    * ``harness_config.unwired_governance_gates`` -- is each deployed blocking
      gate EXECUTABLY wired? Catches the echo-neutered and deleted-event trees.
      Skips gates whose file is absent by design, so it reads the
      never-deployed tree as clean.
    * ``doctor._interpreter_is_python3`` over each interpreter word a wired
      entry runs under (:func:`_not_python3_from_entries`) -- does what is
      wired ANSWER as a Python 3? Catches the host whose ``python`` is a
      Python 2 shim or a Store alias, and the word that does not resolve at
      all: every path present, every entry canonical, and every hook a
      non-decision (``DEF-727``). Neither arm above runs the interpreter.

    Substituting one for another is not a strengthening, it is a swap of
    blind spots -- and one of those blind spots is DEF-427 itself. Only the
    union is a safe basis for the claim.

    ⚠ ``None`` means UNVERIFIABLE and is NOT ``[]``. Callers must branch on
    ``blockers == []``, never on ``not blockers``: ``not None`` is ``True`` in
    Python, so the falsy spelling silently upgrades an unreadable settings file
    to "armed" -- the exact defect this check exists to prevent, merely gated
    behind an I/O failure instead of firing unconditionally.

    ``entries`` lets a caller that has already walked the file
    (:func:`_disarmed_diagnosis_shape`) hand the walk in, so one narration
    reads settings.json once and probes each interpreter word once.
    """
    if entries is _ENTRIES_UNREAD:
        entries = _wired_espalier_entries(settings_path)
    if entries is None:
        return None
    assert isinstance(entries, list)
    blockers = set(_missing_from_entries(repo_root, entries))
    blockers.update(
        f"tools/cc/hooks/{script}"
        for script in unwired_governance_gates(repo_root)
        if not _gate_wiring_is_unreadable_legacy_form(repo_root, script)
    )
    for _resolved, rels in _not_python3_from_entries(entries).values():
        blockers.update(rels)
    return sorted(blockers)


def _gate_wiring_is_unreadable_legacy_form(repo_root: Path, script: str) -> bool:
    """True when this gate's spelling is one the exec-form oracle cannot read,
    so the CLAIM must abstain rather than call it inert.

    ``discover_executable_hook_wirings`` fails CLOSED on the pre-v0.6.5 shell
    form -- deliberately, because for ``doctor`` a shape it cannot verify should
    be loud. For an enforcement claim the same failure is a regression: a legacy
    adopter whose gates genuinely fire would be told they are dead. That exact
    false negative was found by a red team and closed in b517a72; unioning the
    executability oracle in reintroduces it from the other side unless the claim
    abstains here.

    ⚠ This is POLICY and belongs to the claim alone. The classification it rests
    on is shared (``harness_config.classify_unwired_gate``), but the decision to
    forgive is not pushed down: that predicate is count-parity-locked with
    ``tools/cc/ci_guard.py``, and relaxing it there would weaken a deny path to
    soften a claim.

    ⚠ Known residue, driven rather than assumed: a ``#``-commented command names
    an interpreter, so it classifies LEGACY_FORM and the claim survives.
    ``doctor`` still reports that gate per-gate, which bounds it. Closing it
    needs a positive comment-detector -- a different unit of work.
    """
    return classify_unwired_gate(repo_root, script) == GATE_LEGACY_FORM


def _merge_refusal_detail(existing: object, managed_hooks: object) -> str | None:
    """Why ``merge_hooks_into_settings`` would refuse this file outright, or
    ``None`` if it would proceed.

    ⚠ ONE HOME, TWO CALLERS, and the second caller is the reason this exists.
    The merge refuses the WHOLE FILE the moment any canonical event's existing
    value is a truthy non-list -- it does NOT skip the bad event and top up the
    rest. The disarmed-tree banner offers ``merge-settings`` as the remedy for
    an ABSENT gate, so on a file the merge will refuse, that offer is false.

    Driven 2026-08-27 on a real ``init`` tree: with ``hooks.PreToolUse`` set to
    a string and ``ConfigChange`` deleted, the banner said ``merge-settings``
    would wire ConfigChange; the merge returned ``bad_hooks`` and wrote nothing.
    That is this diff's own defect class -- promising a repair the command does
    not perform -- reappearing one input shape over, which is why the banner now
    ASKS the mechanism instead of re-deriving its rule. A private copy of this
    condition would be free to drift from the merge it describes;
    ``tests/test_merge_settings.py::TestMergeRefusalOracleAgreesWithTheMerge``
    pins the two together over a matrix of malformed shapes.

    ⚠ Deliberately does NOT restructure ``merge_hooks_into_settings``: that is a
    write path on an operator's own file, and the agreement test buys the
    no-drift guarantee without touching it.
    """
    if not isinstance(existing, dict):
        return type(existing).__name__
    existing_hooks = existing.get("hooks")
    if existing_hooks is None:
        return None
    if not isinstance(existing_hooks, dict):
        return type(existing_hooks).__name__
    if not isinstance(managed_hooks, dict):
        return None
    for event in managed_hooks:
        value = existing_hooks.get(event)
        if value is not None and not isinstance(value, list):
            return f"hooks.{event}: {type(value).__name__}"
    return None


#: File-level refusal verdicts, in the order ``merge_hooks_into_settings``
#: decides them, each a prefix followed by ``": <detail>"``. The event-value
#: verdict keeps ``_merge_refusal_detail``'s own ``hooks.<event>: <type>``.
#: ⚠ Self-describing on purpose (DEF-700 review): a bare type name cannot say
#: whether the TOP LEVEL or the HOOKS BLOCK is the wrong type, and the first
#: renderer guessed "top level" for both -- a specific falsehood that sent an
#: operator to the wrong node.
MERGE_REFUSED_ABSENT = "absent"
MERGE_REFUSED_UNREADABLE = "unreadable"
MERGE_REFUSED_UNPARSEABLE = "unparseable"
MERGE_REFUSED_NOT_OBJECT = "not-object"
MERGE_REFUSED_HOOKS_BLOCK = "hooks-block"
MERGE_REFUSED_EVENT_VALUE = "hooks."
#: Every verdict prefix the predicate can emit; the renderer must own a
#: sentence for each (pinned by tests/test_merge_settings.py).
MERGE_REFUSAL_KINDS: tuple[str, ...] = (
    MERGE_REFUSED_ABSENT, MERGE_REFUSED_UNREADABLE, MERGE_REFUSED_UNPARSEABLE,
    MERGE_REFUSED_NOT_OBJECT, MERGE_REFUSED_HOOKS_BLOCK, MERGE_REFUSED_EVENT_VALUE,
)


def merge_refusal_for_file(settings_path: Path, repo_root: Path) -> str | None:
    """Why ``merge-settings`` would refuse THIS FILE outright, or ``None``.

    ONE HOME, FOUR OFFER SITES: doctor's two unwired-gate arms, the init
    banner (``_disarmed_diagnosis``) and the fuse banner all name
    ``merge-settings`` as a remedy, and every one of them had offered it on a
    file the merge refuses. ``_merge_refusal_detail`` answers for the hook
    VALUES; this answers for the file, mirroring ``merge_hooks_into_settings``
    branch for branch and in its order: ``exists()`` (MERGE_NO_FILE -- the
    same call, so a not-a-directory or permission failure on the way to the
    file reads as absent here exactly as it does there), then the read and
    the decode/parse (MERGE_PARSE_ERROR, the same exception tuple), then the
    top-level object, then the hooks block, then the event values.

    ⚠ Driven 2026-09-06 (DEF-700) on a settings.json truncated to 0 bytes:
    doctor's predicate parsed inside a blanket ``except`` that returned
    ``None``, so both arms printed "run merge-settings" and the merge exited 1
    with "could not parse". The settings build stays best-effort: losing it
    costs a caveat, never a wrong finding.
    """
    settings_path = Path(settings_path)
    presence, unreadable_detail = surface_contract.path_presence(settings_path)
    if presence == surface_contract.PRESENCE_ABSENT:
        return MERGE_REFUSED_ABSENT
    if presence == surface_contract.PRESENCE_UNREADABLE:
        return f"{MERGE_REFUSED_UNREADABLE}: {unreadable_detail}"
    try:
        raw = settings_path.read_bytes()
    except OSError as exc:
        return f"{MERGE_REFUSED_UNREADABLE}: {os_error_text(exc)}"
    try:
        existing = json.loads(surface_contract.decode_bom(raw))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        return f"{MERGE_REFUSED_UNPARSEABLE}: {exc}"
    if not isinstance(existing, dict):
        return f"{MERGE_REFUSED_NOT_OBJECT}: {type(existing).__name__}"
    hooks = existing.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        return f"{MERGE_REFUSED_HOOKS_BLOCK}: {type(hooks).__name__}"
    try:
        managed = _build_settings_json(
            profile_name="workflow", repo_root=repo_root
        ).get("hooks", {})
    except Exception:  # noqa: BLE001 -- best-effort: a build failure must not turn a diagnostic into a traceback
        return None
    return _merge_refusal_detail(existing, managed)


def merge_refusal_step(refused: str, py: str) -> str:
    """The next step to print INSTEAD of ``merge-settings`` when the merge
    would refuse the file, one sentence per verdict kind.

    Shared by every offer site so they cannot drift. The absent and
    unparseable sentences spell the ``init`` command exactly as doctor's
    presence and unreadable branches do, so ``doctor._append_step`` folds
    them into one line when both fire on the same tree. An unreadable file
    gets its own sentence: "does not parse" was a lie for a file that was
    never read, and "move it aside" is the one remedy a Windows lock defeats.
    """
    kind, _sep, detail = refused.partition(": ")
    if kind == MERGE_REFUSED_ABSENT:
        return (
            f"run `{py} -m espalier init <repo>` to create .claude/settings.json "
            "-- `merge-settings` has no file to merge into"
        )
    if kind == MERGE_REFUSED_UNREADABLE:
        return (
            f".claude/settings.json could not be read ({detail}) -- close "
            "whatever holds it open or fix its permissions, then re-run "
            f"`{py} -m espalier doctor .`; `merge-settings` cannot read it either"
        )
    if kind == MERGE_REFUSED_UNPARSEABLE:
        return (
            "move .claude/settings.json aside (or delete it), then run "
            f"`{py} -m espalier init .` to redeploy it -- the file does not "
            f"parse ({detail}), and while it does not, `merge-settings` "
            "refuses the whole file and wires nothing"
        )
    if kind == MERGE_REFUSED_NOT_OBJECT:
        return (
            f"fix .claude/settings.json -- its top level is a {detail}, not a "
            "JSON object, and `merge-settings` refuses the whole file"
        )
    if kind == MERGE_REFUSED_HOOKS_BLOCK:
        return (
            f"fix the hooks block in .claude/settings.json -- it is a {detail}, "
            "not an object keyed by event name, and `merge-settings` refuses "
            "the whole file"
        )
    if refused.startswith(MERGE_REFUSED_EVENT_VALUE):
        return (
            f"fix {refused} in .claude/settings.json -- that value must be a "
            "list of hook entries, and while it is not, `merge-settings` "
            "refuses the whole file and wires nothing"
        )
    # A verdict this renderer does not know. Honest-but-vague beats a crash
    # in a diagnostic; the kinds test reds the moment a new prefix is added
    # without a sentence, so this line is reachable only by that omission.
    return (
        f"fix .claude/settings.json ({refused}) -- `merge-settings` refuses "
        "the whole file as it stands"
    )


def _unwired_gate_diagnosis(
    shapes: dict[str, list[str]], py: str, merge_refused: str | None = None,
    voided_detail: str | None = None,
) -> tuple[str, list[str]]:
    """Reason + remedies for gates that are deployed but not executably wired.

    Takes the ALREADY-BUCKETED population
    (:func:`harness_config.group_unwired_gates_by_shape`, legacy_form dropped by
    the caller) because each shape gets its own sentence and its own remedy,
    and only ``GATE_ABSENT``'s remedy is a command.

    ⚠ ``GATE_VOIDED_SETTINGS`` is narrated FIRST and alone: it is a whole-FILE
    fact, so the per-entry clauses would invite the operator to "also" repair
    wiring that is already correct.

    ⚠ The bug this replaces, driven 2026-08-27 on real ``espalier init`` trees:
    the whole population was narrated as INERT -- "wired but the entry runs no
    interpreter", "No command repairs this" -- when on an ABSENT tree both
    halves are false and ``merge-settings`` measurably restores the gate, and on
    an ORPHANED tree there is no entry to restore the interpreter ON. On a mixed
    tree it was worse than wrong per-gate: the hand-edit line named
    ``sorted(...)[0]``, which is whichever gate sorts first, so the operator was
    pointed at the one gate a command WOULD have fixed.

    Ordering is absent -> inert -> orphaned, matching ``doctor``'s ``next_steps``
    on the same tree, so the two surfaces an operator reads do not disagree
    about what to do first. The "does NOT fix" clause rides INSIDE the
    merge-settings line rather than trailing after the list: a caveat at the
    bottom is a caveat an operator who already ran the command and saw success
    will not come back for, and a false finish is the specific harm here
    (``merge-settings`` reports success on an orphaned gate and leaves it dead).
    """
    absent = shapes.get(GATE_ABSENT, [])
    orphaned = shapes.get(GATE_ORPHANED, [])
    inert = shapes.get(GATE_INERT, [])
    # ``py`` is the REMEDY interpreter (a command the operator types). The four
    # hand-edit sentences below name the VALUE to write into settings.json,
    # which is what init writes -- the resolver's answer, never quoted, so a
    # remedy path that came pre-quoted no longer renders ""...""  (DEF-758).
    # Kept out of every f-string that carries `-m espalier`; the AST pin in
    # tests/test_portability_contract.py reads that pairing as a remedy
    # spelled with the write answer.
    written = _detect_python_command()
    # ⚠ The leftover arm, and the reason this dispatch is not three ifs and a
    # shrug. A shape this function does not know used to fall through EVERY
    # branch: the reason rendered as "Hooks are NOT yet active: ." and the gate
    # itself vanished from the output -- which is the defect this whole
    # function exists to fix, one level up and silent instead of merely wrong.
    # Measured by adding a hypothetical fifth shape, not reasoned about. So an
    # unknown shape now degrades to vague-but-honest and still NAMES the gate;
    # the trailing doctor line carries the action.
    # ⚠ legacy_form gets NO clause (the claim forgives it -- see
    # `_gate_wiring_is_unreadable_legacy_form`) but it DOES ride in the caveat
    # below. Driven: on a pre-v0.6.5 tree with one deleted event, the operator
    # ran the offered merge-settings, init then claimed "Hooks now intercept",
    # and `doctor` on the same tree exited 1 on the legacy gate. Forgiving a
    # shape in the CLAIM is not a licence to omit it from a list of what a
    # command will not fix.
    legacy = shapes.get(GATE_LEGACY_FORM, [])
    unrecognized = sorted(
        script
        for shape, scripts in shapes.items() if shape not in GATE_SHAPES
        for script in scripts
    )

    def _events(scripts: list[str]) -> list[str]:
        return sorted({GATE_EVENT_OF(s) for s in scripts})

    # Narrated FIRST and alone: it is the only shape that is not a fact about
    # the gate's own entry, and the only one whose remedy may point at a hook
    # espalier does not manage. Mixing it with per-entry clauses would invite
    # the operator to "also" fix wiring that is already correct.
    voided = shapes.get(GATE_VOIDED_SETTINGS, [])
    clauses: list[str] = []
    if voided:
        clauses.append(
            "Claude Code is loading NO hooks from .claude/settings.json"
            + (f" ({voided_detail})" if voided_detail else "")
            + ", so "
            + ", ".join(voided)
            + (" is dead" if len(voided) == 1 else " are all dead")
            + " regardless of how "
            + ("it is" if len(voided) == 1 else "they are")
            + " wired"
        )
    if absent:
        events = _events(absent)
        clauses.append(
            ", ".join(absent)
            + (" is" if len(absent) == 1 else " are")
            + " not wired at all -- settings.json has no "
            + ", ".join(events)
            + (" section" if len(events) == 1 else " sections")
        )
    if inert:
        clauses.append(
            ", ".join(inert)
            + (" is" if len(inert) == 1 else " are")
            + " wired but the entry runs no interpreter, so the "
            + ("gate never fires" if len(inert) == 1 else "gates never fire")
        )
    if orphaned:
        events = _events(orphaned)
        clauses.append(
            ", ".join(orphaned)
            + (" has" if len(orphaned) == 1 else " have")
            + " no entry under "
            + ", ".join(events)
            + ", which exists but does not name "
            + ("it" if len(orphaned) == 1 else "them")
        )
    miswired = shapes.get(GATE_MISWIRED, [])
    if miswired:
        clauses.append(
            ", ".join(miswired)
            + (" is" if len(miswired) == 1 else " are")
            + " wired under the wrong event or with a matcher that excludes "
            "tools "
            + ("it" if len(miswired) == 1 else "they")
            + " must see, so the "
            + ("gate does not fire where it must"
               if len(miswired) == 1 else "gates do not fire where they must")
        )
    if unrecognized:
        clauses.append(
            ", ".join(unrecognized)
            + (" is" if len(unrecognized) == 1 else " are")
            + " not executably wired, in a shape this banner cannot name"
        )

    remedies: list[str] = []
    if voided:
        # ⚠ The detail is the whole value of this remedy. The first draft said
        # only "give every entry a `type`" -- true of one member of the class
        # and false of the other seven (a group that is a string, a missing
        # "hooks" key, a non-string matcher, "args" as a string, ...). Claude
        # Code schema-validates the whole block and reports nothing, so without
        # naming the offending node the operator has no way to find it.
        remedies.append(
            "Fix "
            + (voided_detail or "the malformed hook entry")
            + " in .claude/settings.json. Claude Code validates the WHOLE hooks "
            "block and discards ALL of it if any group or entry is malformed, "
            "and it reports nothing -- so the offending entry may be one of "
            "your own hooks, under an event unrelated to espalier."
        )
    if absent and merge_refused:
        # The offer is WITHHELD, not reworded. merge-settings refuses this file
        # whole, so naming it here -- even with a caveat -- sends the operator
        # to a command that exits non-zero and changes nothing.
        remedies.append(
            f"First fix {merge_refused} in .claude/settings.json: that value "
            "must be a list of hook entries, and while it is not, "
            "`merge-settings` refuses the whole file and repairs nothing."
        )
    elif absent:
        events = _events(absent)
        # Everything merge-settings leaves behind, INCLUDING the shapes this
        # function abstains on or cannot name. The caveat exists to prevent a
        # false finish, and a gate omitted from it IS a false finish.
        #
        # ⚠ DERIVED, not hand-unioned (STANDING_PRINCIPLES §14). This was
        # `sorted(inert + orphaned + unrecognized + legacy)` -- a hand list that
        # silently omits any shape added later, which is exactly how a new shape
        # becomes a false finish with nothing red. GATE_ABSENT is the only shape
        # merge-settings repairs (driven 2026-08-27), so every OTHER shape
        # present on this tree belongs in the caveat by construction.
        unfixed = sorted(
            script
            for shape, scripts in shapes.items() if shape != GATE_ABSENT
            for script in scripts
        )
        remedies.append(
            f"Run `{py} -m espalier merge-settings .` to wire the missing "
            + ", ".join(events)
            + (" event" if len(events) == 1 else " events")
            + (f" -- this does NOT fix {', '.join(unfixed)}." if unfixed
               else ".")
        )
    if inert:
        remedies.append(
            f"Run `{py} -m espalier merge-settings . --repair`: "
            + ", ".join(inert)
            + (" is" if len(inert) == 1 else " are")
            + " wired but the entry runs no interpreter; --repair rewrites "
            "espalier's own entry to canonical (backup first), or set the "
            f"command back to \"{written}\" with the script path in args by hand."
        )
    if miswired:
        remedies.append(
            f"Run `{py} -m espalier merge-settings . --repair`: "
            + ", ".join(miswired)
            + (" is" if len(miswired) == 1 else " are")
            + " wired under the wrong event or with a narrowed matcher; "
            "--repair puts espalier's own entry back under its canonical "
            "event with its canonical matcher (backup first); "
            f"`{py} -m espalier doctor .` prints which half is wrong."
        )
    if orphaned:
        events = _events(orphaned)
        # ⚠ The RATIONALE is dropped when the merge is refused. "merge-settings
        # will NOT add it because that event key already exists" is the true
        # reason on a well-formed file and the WRONG reason on a refused one,
        # where the merge never reaches the event at all -- and a remedy whose
        # stated reason is false is the same fault as a remedy that is false,
        # just harder to catch. The line above already names the real blocker.
        remedies.append(
            (
                "Edit .claude/settings.json by hand: add an entry for "
                + ", ".join(orphaned) + " under " + ", ".join(events)
                + (" (command: \"%s\", the script path in args)." % written)
            ) if merge_refused else (
                f"Run `{py} -m espalier merge-settings . --repair` to add an "
                "entry for " + ", ".join(orphaned) + " under " + ", ".join(events)
                + " -- plain merge-settings will NOT add it, because that event "
                f"key already exists; or add it by hand (command: \"{written}\", the "
                "script path in args)."
            )
        )
    if legacy:
        remedies.append(
            ", ".join(legacy)
            + (" is" if len(legacy) == 1 else " are")
            + " wired in the pre-v0.6.5 shell form this check cannot verify "
            + ("and most likely fires" if len(legacy) == 1 else "and most likely fire")
            + f"; `{py} -m espalier merge-settings . --repair` converts "
            + ("it" if len(legacy) == 1 else "them")
            + " to exec form (backup first), or re-wire by hand (command "
            f"\"{written}\", script path in args)."
        )
    remedies.append(f"Then: {py} -m espalier doctor .")

    return "Hooks are NOT yet active: " + "; ".join(clauses) + ".", remedies


def _dead_reporters_line(repo_root: Path, py: str) -> str | None:
    """The sentence every armed-claim narrator appends when a deployed reporter
    hook is not executably wired (DEF-619), or ``None`` when none is.

    ONE home for four narrators -- ``init``'s banner, ``--wire-hooks``,
    ``merge-settings`` and ``fuse`` -- because the first cut put it on one of
    them, and ``doctor``'s own remedy sent the operator to another that said
    "Enforcement is now active" over a reporter it had just left dead (driven
    by the failure-mode pass). Legacy-form reporters are DROPPED, exactly as
    the enforcement claim forgives legacy-form gates
    (:func:`_gate_wiring_is_unreadable_legacy_form`): that shape is one the
    oracle cannot read, not one that is dead, and ``doctor`` reports it in its
    own words. A claim must not call it dead in the same breath as "Hooks now
    intercept".
    """
    shapes = group_unwired_reporters_by_shape(repo_root)
    dead = sorted(
        script
        for shape, scripts in shapes.items()
        if shape != GATE_LEGACY_FORM
        for script in scripts
    )
    if not dead:
        return None
    return (
        "NOT wired: " + ", ".join(dead)
        + (" is a reporter hook" if len(dead) == 1 else " are reporter hooks")
        + " (they inject, record or advise and never block, so nothing fails "
        f"visibly). Run `{py} -m espalier doctor .` for the remedy per hook."
    )


def _disarmed_diagnosis_shape(repo_root: Path) -> tuple[str, list[str], bool]:
    """Why enforcement is not active on THIS tree, and what to actually do.

    Returns ``(reason, remedy_lines, arms_on_deploy)``; :func:`_disarmed_diagnosis`
    drops the flag. The flag is True only for the one shape a deploy fixes
    (wired paths that do not resolve), so "the settings arm the moment the
    harness is deployed" is said only where it is true -- it was said for an
    interpreter that does not answer as Python 3 on a fully deployed tree
    (driven by the DEF-727 failure-mode review). Recomputed from the tree at
    print time rather than threaded down as a bool, because the caller needs
    the SHAPE and a bool cannot carry it. SEVEN shapes reach this function, and
    they do not share a remedy -- four of them are not ``merge-settings``:

    * unreadable settings -- no claim either way; fix the JSON, then ask doctor.
    * no Espalier hooks wired -- the brought-your-own adopter whose file init
      preserved. ``merge-settings`` genuinely fixes this one.
    * wired paths that do not resolve -- the deploy did not land the scripts.
      ``merge-settings`` would report success and change nothing; the tree
      needs a deploy.
    * a wired interpreter word that does not answer as Python 3, or does not
      resolve -- every hook through it is a non-decision, whatever shape the
      entries have. The remedy is ``--rewire-interpreter`` spelled with an
      interpreter that can run it, or a hand edit for the shapes that verb
      declines (``DEF-727``).
    * the per-gate shapes -- ABSENT / ORPHANED / INERT -- plus the whole-file
      VOIDED_SETTINGS, which :func:`_unwired_gate_diagnosis` narrates from the
      shared bucketing, and which can co-occur on ONE tree (VOIDED_SETTINGS
      cannot: it claims every gate at once, by construction). That last part is why the dispatch is a
      composition and not an if/elif: a real adopter can have a deleted event,
      a dropped entry and an echoed command at once, and each needs its own
      sentence.

    ⚠ Two rounds of the same mistake are recorded here. The FIRST version told
    every one of these operators that their "existing .claude/settings.json was
    preserved", true for one shape of four. The SECOND (2026-08-27) split that
    up but then bucketed every unwired gate as INERT, so ABSENT and ORPHANED
    gates were still told "the entry runs no interpreter" and "No command
    repairs this" -- on a tree where ``merge-settings`` measurably restores the
    gate. Both versions failed the same way: a population narrated with one
    member's prose. If a shape is added, give it a clause, not a bucket.
    """
    settings_path = repo_root / ".claude" / "settings.json"
    # Every remedy below is a command the operator will type, so it is spelled
    # with an interpreter that can run it -- not the resolver's answer, which
    # on the host the identity clause below fires for IS the broken word
    # (DEF-727: `python -m espalier ...` spelled with a Python 2 `python`).
    py, resolver_clears_floor = _remedy_interpreter()

    # ONE walk of the file for every per-entry clause below (the reader is
    # `_wired_espalier_entries`; `None` is its "could not read").
    entries = _wired_espalier_entries(settings_path)
    # The FILE first, before any shape of its contents: absent, unreadable,
    # unparseable, not an object, or a hooks block of the wrong type. Every
    # one of those is a file `merge-settings` refuses whole, and this banner's
    # first arm used to offer it anyway (DEF-700 failure-mode review, driven:
    # banner said "To activate ... merge-settings ." on the tree doctor called
    # refused). The event-value verdict falls through: its narration belongs
    # to the arm that knows which gates it blocks.
    refused = merge_refusal_for_file(settings_path, repo_root)
    if refused is not None and not refused.startswith(MERGE_REFUSED_EVENT_VALUE):
        kind = refused.partition(": ")[0]
        return (
            "Hooks are NOT yet active: .claude/settings.json is not a file "
            f"`merge-settings` can wire ({kind}), so Claude Code cannot load "
            "hooks from it either.",
            [merge_refusal_step(refused, py)],
            False,
        )
    if entries is None:
        # NOT "unverified". Claude Code parses this file with the same rules we
        # just failed on, so a file we cannot read is a file it cannot load
        # hooks from -- enforcement is definitively off, and the stronger true
        # statement beats the hedge. (merge-settings' UNVERIFIED wording is for
        # a different situation: there the merge SUCCEEDED and wrote valid JSON,
        # so a failed read-back is anomalous rather than diagnostic.)
        return (
            "Hooks are NOT yet active: .claude/settings.json could not be "
            "parsed, so Claude Code cannot load any hooks from it either.",
            [f"Fix the JSON, then run: {py} -m espalier doctor ."],
            False,
        )

    try:
        existing = json.loads(
            surface_contract.decode_bom(settings_path.read_bytes())
        )
    except (OSError, ValueError):
        existing = None
    if not _settings_has_espalier_hooks(existing):
        if refused:
            # A brought-your-own file with an event value the merge refuses:
            # the offer would exit 1 and write no .bak. Name the value instead.
            return (
                "Hooks are NOT yet active: your existing .claude/settings.json "
                "was preserved, and `merge-settings` would refuse it as it "
                "stands.",
                [merge_refusal_step(refused, py)],
                False,
            )
        return (
            "Hooks are NOT yet active: your existing .claude/settings.json was "
            "preserved, so enforcement (write_guard, plan_guard, stop_gate, "
            "...) is not wired in.",
            [f"To activate (keeps your settings and a .bak of them): "
             f"{py} -m espalier merge-settings ."],
            False,
        )

    # NOT `absent`: that name belongs to `GATE_ABSENT` twenty lines down, which
    # means something else entirely (the EVENT KEY is missing from
    # settings.json). This list is paths that do not RESOLVE on disk. The two
    # failures share no remedy, and the collision cost a reader once already.
    unresolved = _missing_from_entries(repo_root, entries)
    if unresolved:
        head = unresolved[0]
        extra = (f" (and {plural(len(unresolved) - 1, 'other')})"
                 if len(unresolved) > 1 else "")
        return (
            f"Hooks are NOT yet active: settings.json wires {head}{extra}, "
            f"which is not on disk in this repo.",
            [f"Deploy the hook tree: {py} -m espalier init ."],
            True,
        )

    not_python3 = _not_python3_from_entries(entries)
    if not_python3:
        # A word that does not answer as Python 3 disarms every hook wired
        # through it at once, whatever shape the entries have, so it is named
        # before the per-gate shapes. Sorted for a stable sentence: the first
        # word carries the prose, the rest are counted.
        token, (resolved, _rels) = sorted(not_python3.items())[0]
        extra = (f" (and {plural(len(not_python3) - 1, 'other interpreter word')})"
                 if len(not_python3) > 1 else "")
        found = (
            f"resolves to {resolved} but does not answer as Python 3"
            if resolved else "does not resolve on this host"
        )
        if not _is_rewirable_interpreter(token):
            # DEF-620's rule at this prescriber too: `--rewire-interpreter`
            # DECLINES the `py` launcher, a shebang script and an unterminated
            # quote, and then reports "nothing to rewire" -- a success-shaped
            # sentence on a tree where every guard fails open (driven by the
            # DEF-727 failure-mode review). Ask the one predicate that decides,
            # as `doctor._check_python_resolver` does.
            remedy = (
                f"`--rewire-interpreter` declines this command shape (the `py` "
                f"launcher, a shebang script, an unterminated quote), so edit the "
                f"hook commands in .claude/settings.json by hand to an interpreter "
                f"that answers as Python {floor_text()}+."
            )
        else:
            rewire = f"`{py} -m espalier init . --rewire-interpreter`"
            if resolver_clears_floor:
                remedy = (f"Rewire the hook commands to one that does: {rewire} "
                          f"(changes only the interpreter name; keeps a .bak of the file).")
            else:
                # The rewire computes its target with the same resolver, so on
                # this host it would refuse (REWIRE_NO_TARGET). The blocker is
                # PATH, not a missing install: this command is running under a
                # Python that clears the floor. Say what was probed, and what
                # to do about PATH -- "install Python" prescribed an install the
                # operator had already done (driven by the code review).
                remedy = (f"No {resolver_candidate_names()} on PATH answers as "
                          f"Python {floor_text()}+, so the rewire has no target to "
                          f"write. Put a Python {floor_text()}+ on PATH under one of "
                          f"those names, then run {rewire} (changes only the "
                          f"interpreter name; keeps a .bak of the file).")
        return (
            f"Hooks are NOT yet active: settings.json runs its hooks with "
            f"{token!r}{extra}, which {found}, so every hook spawned with it "
            f"exits outside the blocking range -- a non-decision, which is "
            f"non-blocking -- and each guard fails OPEN.",
            [remedy],
            False,
        )

    shapes = group_unwired_gates_by_shape(repo_root)
    # The abstention, applied HERE rather than in the shared grouper because it
    # is this caller's policy alone -- `doctor` reports legacy_form and must go
    # on doing so. Identical to the predicate `_enforcement_claim_blockers`
    # uses, and it has to stay identical: a gate the CLAIM forgave but the
    # DIAGNOSIS names would tell an operator enforcement is off and then, one
    # command later, that it is on.
    # The full dict goes through -- the narrator gives legacy_form no clause
    # but still names it in the caveat. Only the DECISION to narrate at all
    # excludes it: a tree whose sole finding is legacy_form has empty claim
    # blockers, so there is nothing to explain.
    if set(shapes) - {GATE_LEGACY_FORM}:
        # Ask the merge whether it would even accept this file before offering
        # it as the remedy. Best-effort: a build failure must not turn an
        # advisory banner into a traceback, and losing the check only costs the
        # caveat, never correctness of the shape narration itself.
        try:
            managed = _build_settings_json(
                profile_name="workflow", repo_root=repo_root
            ).get("hooks", {})
            refused = _merge_refusal_detail(existing, managed)
        except Exception:  # noqa: BLE001 -- banner must not crash init
            refused = None
        reason, remedies = _unwired_gate_diagnosis(
            shapes, py, merge_refused=refused,
            voided_detail=surface_contract.hooks_config_voided_by(
                surface_contract._load_settings_hooks_cfg(repo_root)
            ),
        )
        return reason, remedies, False

    return (
        "Hooks are NOT yet active.",
        [f"Run {py} -m espalier doctor . for the specific finding."],
        False,
    )


def _disarmed_diagnosis(repo_root: Path) -> tuple[str, list[str]]:
    """``(reason, remedy_lines)`` -- :func:`_disarmed_diagnosis_shape` without
    the deploy flag, for the narrators that print the reason and remedies
    alone (``init``'s banner)."""
    reason, remedies, _arms_on_deploy = _disarmed_diagnosis_shape(repo_root)
    return reason, remedies


def _unverifiable_settings_warning(settings_path: Path) -> str:
    """WARN for the case where the wired settings cannot be read back.

    Withholding the enforcement claim is the whole point: the operator gets a
    smaller, honest statement instead of a confident wrong one. Not a refusal --
    the merge itself already succeeded and the file on disk is correct.
    """
    return (
        "merge-settings: WARNING -- could not re-read "
        f"{settings_path} to confirm the wired hooks resolve, so enforcement "
        "state is UNVERIFIED. The merge itself succeeded. Check the file is "
        f"valid JSON, then run `{_remedy_py()} -m espalier doctor .`"
    )


def _disarmed_hook_tree_warning(
    repo_root: Path, *, prefix: str, wrote_settings: bool
) -> str:
    """The operator-facing WARN that replaces the enforcement claim.

    Deliberately not a refusal: wiring settings ahead of a deploy is a
    legitimate operator move, and ``merge-settings`` is the documented escape
    from the preserved-but-disarmed state ``init`` leaves behind, so it must
    warn and still write. Names the state AND an action -- a warning that
    reports a problem without one is the defect one row over (DEF-433).

    Three things it used to get wrong, all driven:

    * The ``merge-settings:`` prefix was hard-coded, so the same text reached an
      operator who had run ``init --wire-hooks``.
    * The remedy was always "run init", which is circular when init is what
      printed it.
    * It said the scripts "are missing from this repo". Once the caller passes
      the UNION of blockers that is false for an inert gate, whose script is
      present and whose wiring simply runs no interpreter. The body now comes
      from :func:`_disarmed_diagnosis`, which distinguishes the shapes.

    ``wrote_settings`` gates the "wired anyway" clause: it is past tense, and
    the MERGE_ALREADY branch that used to print it wrote nothing at all. The
    "arm the moment the harness is deployed" half is said only for the shape a
    deploy fixes (:func:`_disarmed_diagnosis_shape`'s flag): it was said about
    an interpreter that does not answer as Python 3 on a fully deployed tree
    (DEF-727 review) -- the population-narrated-with-one-member's-prose defect
    this docstring already records twice, one shape later.
    """
    reason, remedies, arms_on_deploy = _disarmed_diagnosis_shape(repo_root)
    parts = [f"{prefix}: WARNING -- {reason}"]
    if wrote_settings and arms_on_deploy:
        parts.append(
            "The settings were wired anyway so they arm the moment the harness "
            "is deployed."
        )
    elif wrote_settings:
        parts.append("The settings were wired anyway.")
    parts.extend(remedies)
    return " ".join(parts)


def cmd_merge_settings(args: argparse.Namespace) -> int:
    """Wire Espalier's hook events into an operator's existing settings.json.

    ``init``/``fuse`` never overwrites an existing ``.claude/settings.json``
    (user sovereignty), so a brand-new adopter who already uses Claude Code ends
    up with the harness preserved-but-disarmed. This operator-invoked command is
    the explicit opt-in: it merges Espalier's hook events into the existing
    file (and adds its ``statusLine`` when that key is absent, DEF-798),
    preserves every other key (permissions, env, ...), keeps a ``.bak`` of the
    pre-write bytes first (written, or the rung that already holds them), and
    is idempotent (a second run is a no-op once hooks are live).
    It never touches the file unless the operator runs it.

    The merge itself lives in :func:`merge_hooks_into_settings` so the
    ``--wire-hooks`` deploy path shares ONE implementation; this command only maps
    the result to operator-facing prose + exit codes.
    """
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    settings_path = repo_root / ".claude" / "settings.json"
    profile = getattr(args, "profile", None) or installed_settings_profile(repo_root)
    repaired = False
    repair = None
    if getattr(args, "repair", False) and os.path.lexists(settings_path):
        # BEFORE the merge, so an entry the oracle finds under the wrong event
        # is moved rather than left as a stray copy beside the event the merge
        # would then top up (driven: a config_guard moved onto
        # PostToolUseFailure stayed there when the merge ran first). The merge
        # follows for the allow-rule reporting it owns; on a refused file the
        # merge's own refusal line says why.
        repair = repair_hook_wiring_in_settings(settings_path, repo_root, profile=profile)
        _report_hook_repair(repair, _remedy_py())
        # A refusal does NOT end the command: the plain merge tops up a null
        # event the repair refuses over (driven -- `--repair` used to exit 1 on
        # a tree the flag-less run fully wired), and it owns its own refusal
        # wording for the kinds the two share.
        repaired = repair.status == REPAIR_DONE
    result = merge_hooks_into_settings(
        settings_path,
        profile=profile,
        repo_root=repo_root,
        add_allows=bool(getattr(args, "add_allows", False)),
    )
    if result.status == MERGE_NO_FILE:
        # Detect the interpreter lazily -- only on the error branches that print a
        # hint, never on the MERGE_WIRED/ALREADY success path (keeps the common
        # case free of the subprocess probe _detect_python_command spawns).
        print(
            f"merge-settings: no {settings_path} found. Run "
            f"`{_remedy_py()} -m espalier init {args.repo}` to create a fully-wired settings.json.",
            file=sys.stderr,
        )
        return 1
    if result.status == MERGE_UNREADABLE:
        # The file-level predicate's own sentence, so doctor's step and this
        # refusal cannot drift: the remedy is the permission, never `init`.
        print(
            f"merge-settings: {merge_refusal_step(f'{MERGE_REFUSED_UNREADABLE}: {result.detail}', _remedy_py())}",
            file=sys.stderr,
        )
        return 1
    if result.status == MERGE_PARSE_ERROR:
        print(
            f"merge-settings: could not parse {settings_path}: {result.detail}. "
            f"Fix it (or rm it and run `{_remedy_py()} -m espalier init {args.repo}`).",
            file=sys.stderr,
        )
        return 1
    if result.status == MERGE_NOT_OBJECT:
        print(
            f"merge-settings: {settings_path} is not a JSON object; refusing to "
            "merge.",
            file=sys.stderr,
        )
        return 1
    if result.status == MERGE_BAD_HOOKS:
        print(
            f"merge-settings: {settings_path} has a malformed 'hooks' block "
            f"({result.detail}); Claude Code expects 'hooks' to be an object keyed "
            "by event name, each event mapping to a list. Fix (or remove) the "
            "offending 'hooks' entry and re-run.",
            file=sys.stderr,
        )
        return 1
    # DEF-427: both success branches asserted enforcement without ever
    # checking that the scripts they wired exist. Gate BOTH -- a re-run hits
    # the idempotent branch, so fixing only the first leaves the claim live.
    #
    # `None` means the settings could not be re-read or parsed. That is NOT the
    # same as "nothing missing": the claim is withheld, because asserting live
    # enforcement from an unverifiable file is the defect itself.
    # The UNION, not path-existence alone: every script can be on disk with
    # every gate wired to `echo`, which this command used to report as active.
    missing = _enforcement_claim_blockers(repo_root, settings_path)
    unverified = missing is None

    def _gaps(announce_added: bool = True) -> None:
        _report_allow_gaps(
            missing=result.missing_allows, added=result.added_allows,
            note=result.allow_note, profile=profile, prefix="merge-settings:",
            hint_command=lambda: f"re-running with `--profile {profile} --add-allows`",
            announce_added=announce_added,
        )

    if result.status == MERGE_ALREADY:
        head = (
            "merge-settings: every Espalier hook event is wired after the repair above"
            if repaired else
            "merge-settings: Espalier hooks are already wired in .claude/settings.json"
        )
        # "Nothing to do" only when it is true: a wired file can still lack
        # the profile's allow rules, and those are reported right below.
        tail = ("" if repaired and not result.missing_allows
                else " Nothing to do." if not result.missing_allows
                else " Hook events are current; the allow rules below are not.")
        if unverified:
            print(head + "." + tail, flush=True)
            print(_unverifiable_settings_warning(settings_path), file=sys.stderr)
        elif missing:
            print(head + "." + tail, flush=True)
            print(_disarmed_hook_tree_warning(
                repo_root, prefix="merge-settings", wrote_settings=False,
            ), file=sys.stderr)
        else:
            print(head + " -- enforcement is active." + tail)
        _gaps()
        return 0
    # MERGE_WIRED: hook events, profile allow rules (opt-in), the statusLine
    # (absent key), or any combination -- one phrase for every narrator.
    wired = (
        f"merge-settings: {_merge_did_phrase(result, profile=profile)} into "
        f".claude/settings.json (your other settings were preserved; backup at "
        f"{result.detail})."
    )
    # "now" claims a transition; an allow-only or statusline-only run on a
    # wired file made none -- unless the repair above made one.
    claim = _merge_claim(result, repaired=repaired)
    if repaired and repair is not None:
        # Two writes this run, two backups: say which is the pre-run file, since
        # the line the operator reads last names the later one.
        print(
            f"merge-settings: two backups this run -- .claude/{repair.detail} is "
            f"the file before --repair; .claude/{result.detail} is after it."
        )
    if unverified:
        print(wired, flush=True)
        print(_unverifiable_settings_warning(settings_path), file=sys.stderr)
    elif missing:
        print(wired, flush=True)
        print(_disarmed_hook_tree_warning(
            repo_root, prefix="merge-settings", wrote_settings=True,
        ), file=sys.stderr)
    else:
        print(wired + claim)
        reporters_line = _dead_reporters_line(repo_root, _remedy_py())
        if reporters_line:
            print("merge-settings: " + reporters_line)
    _gaps(announce_added=False)
    return 0


def _read_deployed_version(repo_root: Path) -> str | None:
    """Read the engine version stamped into cc/PACK_MANIFEST.txt at deploy time.

    The discriminator between "this harness is current" and "an older engine
    deployed it." Returns the stamped version string, or None when the manifest
    is absent or carries no stamp (treated as "unknown / definitely stale").
    """
    manifest = repo_root / "cc" / "PACK_MANIFEST.txt"
    if not manifest.is_file():
        return None
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# espalier-version:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _name_paths(paths: list[str], limit: int = 10) -> str:
    """Comma-join up to ``limit`` paths for an operator line; count the rest."""
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        shown += f" (+{len(paths) - limit} more)"
    return shown


def _surface_drift_lines(
    surface: dict[str, list[str]], ownership: dict[str, list[str]],
) -> list[str]:
    """The lines ``upgrade`` prints when the stamp is current and the deployed
    surface is not -- one per REPAIRABLE drift class, each naming its files
    and what ``--execute`` does about it. Empty when both oracles agree with
    the stamp.

    Two classes are deliberately not lines here, because nothing ``--execute``
    writes changes them, so counting them as drift would make every later run
    fall through to the stages and say the same thing forever:
    ``source_missing`` (a defect of the engine install, not of the tree; the
    caller warns on stderr) and ``skipped_user_files`` (a managed file the
    adopter edited and un-marked; the deploy keeps it by contract, and the
    caller names it beside the sentence instead of saying "nothing to do").
    """
    lines: list[str] = []
    # The three cc/ docs have no packaged version to differ from: they render
    # from the tree, so their sentence says that, and says the render lands
    # after the copied files above do (the preview classifies them against
    # the tree as it is -- preview_managed_surface's declared caveat).
    copied = [p for p in surface["updated_managed"] if not p.startswith("cc/")]
    rendered = [p for p in surface["updated_managed"] if p.startswith("cc/")]
    if copied:
        n = len(copied)
        lines.append(
            f"{plural(n, 'managed file')} with content that differs from the "
            f"packaged version (regenerated on --execute): " + _name_paths(copied)
        )
    if surface["created"]:
        n = len(surface["created"])
        lines.append(
            f"{plural(n, 'file')} the deploy writes, absent from this tree "
            f"(created on --execute): " + _name_paths(surface["created"])
        )
    if rendered:
        n = len(rendered)
        verb = "renders" if n == 1 else "render"
        lines.append(
            f"{plural(n, 'cc/ surface doc')} that {verb} differently from what "
            f"is on disk (re-rendered on --execute, after the files above land): "
            + _name_paths(rendered)
        )
    stale = ownership.get("stale_saved_paths", [])
    if stale:
        lines.append(
            f"{plural(len(stale), 'saved-plan path')} no longer on disk (the plan "
            f"is re-baselined on --execute): " + _name_paths(stale)
        )
    missing = ownership.get("missing_from_saved_plan", [])
    if missing:
        lines.append(
            f"{plural(len(missing), 'on-disk managed path')} absent from the saved "
            f"plan (re-baselined on --execute): " + _name_paths(missing)
        )
    return lines


def cmd_upgrade(args: argparse.Namespace) -> int:
    """Re-deploy a stale harness in place: stamp-diff -> re-deploy + merge-settings
    + orphan-surface + integrity-refresh, as ONE --dry-run-able flow.

    Dry-run is the DEFAULT (the clean-generated convention); pass --execute to
    apply. Reuses the existing primitives verbatim (merge_hooks_into_settings,
    _scan_managed_orphans, deploy_harness) -- no new deploy or merge machinery.

    "Stale" has three answers, not one: the engine version moved past the
    stamp in ``cc/PACK_MANIFEST.txt``; a managed file differs from the
    packaged bytes (``preview_managed_surface``); the saved plan no longer
    matches the tree (``doctor``'s three-way ownership). A version-current
    tree is asked the other two before it is told there is nothing to do.
    """
    repo_root = Path(args.repo).resolve()
    if not (repo_root / ".git").exists():
        print(
            f"[upgrade] FAIL: {repo_root} is not a git repository.",
            file=sys.stderr,
        )
        return 1
    refused = _refuse_unreadable_harness_root(repo_root, "upgrade")
    if refused is not None:
        return refused
    deployed_version = _read_deployed_version(repo_root)
    if deployed_version is None:
        # No stamp: either uninitialized, or deployed by an older engine.
        manifest = repo_root / "cc" / "PACK_MANIFEST.txt"
        if not manifest.is_file():
            print(
                "[upgrade] no harness deployment found "
                f"(cc/PACK_MANIFEST.txt absent). Run `{_remedy_py()} -m espalier init .` "
                "for a first-time setup.",
                file=sys.stderr,
            )
            return 1
        print(
            "[upgrade] deployed harness carries no version stamp "
            "(pre-0.8.0a13 deployment) -- treating as stale.",
            file=sys.stderr,
        )
    elif deployed_version == __version__:
        # The stamp answers "did the ENGINE move?" and nothing else. Walk 2
        # drove the two answers it cannot give (DEF-726 / DEF-728, both on the
        # Windows host): a managed hook altered by one appended line read as
        # current while `doctor` said fail in the same minute, and a
        # three-week-old fusion -- write_guard.py three thousand lines behind,
        # a saved plan listing a retired agent -- read as current because an
        # alpha version string does not move between releases. So the
        # deployed surface gets its own two oracles BEFORE the claim: the
        # packaged bytes, through the classifiers deploy_harness writes with
        # (their writes switched off), and the saved plan, through the same
        # three-way ownership `doctor` reports. Drift falls through to the
        # stages below, which name it and (on --execute) repair it; only a
        # tree both oracles clear reaches the "nothing to do" sentence.
        from espalier._report_io import load_harness_plan
        from espalier.doctor import _three_way_ownership  # one owner of the delta; doctor and upgrade must not be able to disagree
        py = _remedy_py()
        self_host = surface_contract.is_self_host_repo(repo_root)
        if self_host:
            # The deploy source IS this tree (tools/cc/ is the source of the
            # vendored mirror, .claude/ of the packaged bodies), so every
            # source-of-truth file would read as an un-marked adopter edit
            # and the "add the marker" remedy would invite a later deploy to
            # write the mirror over the source. Nothing to compare; say so.
            surface = {
                "created": [], "updated_managed": [], "skipped_user_files": [],
                "skipped_no_drift": [], "source_missing": [],
            }
        else:
            surface = preview_managed_surface(repo_root)
        plan = load_harness_plan(repo_root)
        ownership = _three_way_ownership(repo_root, plan)
        # What was NOT compared, said on both arms: an oracle that could not
        # run is narrated, never read as clean.
        not_compared: list[str] = []
        if self_host:
            not_compared.append(
                "the packaged surface (self-host tree: the deploy source is this tree)"
            )
        if plan is None:
            not_compared.append(
                "the saved plan (reports/harness_config.json is absent; "
                f"`{py} -m espalier doctor .` names what restores it)"
            )
        for item in not_compared:
            print(f"[upgrade] not compared: {item}.")
        if (repo_root / "tools" / "cc" / "ci_guard.py").exists():
            # install-ci's files sit outside both oracles; an adopter whose
            # merge gate is three engines behind would otherwise hear nothing.
            print("[upgrade] the CI gate (tools/cc/ci_guard.py, "
                  ".github/workflows/harness-guard.yml) is install-ci's and is "
                  f"not compared here; `{py} -m espalier install-ci .` rewrites the "
                  "script and, when your workflow differs from the packaged one, "
                  "parks the packaged workflow as harness-guard.yml.new for you to "
                  "merge (a gate input the script needs and the workflow does not "
                  "forward fails every protected pull request closed).")
        if surface["source_missing"]:
            n = len(surface["source_missing"])
            print("[upgrade] WARN: "
                  f"{plural(n, 'packaged source')} missing from this engine "
                  f"install, so nothing is deployed for {'it' if n == 1 else 'them'} "
                  "(reinstall espalier): " + _name_paths(surface["source_missing"]),
                  file=sys.stderr)
        kept = surface["skipped_user_files"]
        if kept:
            # Named on both paths, never a reason to fall through: the deploy
            # keeps an un-marked file by contract, so this line reads the same
            # after --execute as before it.
            print(f"[upgrade] kept as yours: {_name_paths(kept)} -- "
                  f"{'differs' if len(kept) == 1 else 'differ'} from the "
                  "packaged version and carry no managed marker; add the "
                  "marker line to opt back into regeneration.")
        unshipped = ownership.get("unshipped_saved_agents", [])
        if unshipped:
            # Also both arms, also not drift (DEF-756): the plan recommends
            # them, no engine ships a body, nothing will put them on disk.
            print(f"[upgrade] recommended, not shipped: {_name_paths(unshipped)} -- "
                  "the saved plan lists "
                  f"{'this agent' if len(unshipped) == 1 else 'these agents'} and "
                  "no engine ships a body, so nothing is deployed for "
                  f"{'it' if len(unshipped) == 1 else 'them'}.")
        drift_lines = _surface_drift_lines(surface, ownership)
        # A fourth oracle, for the seeds (DEF-774): a seed doc whose packaged
        # content changed without a version bump (the 2026-09-11 banner
        # rewording did exactly that) is refreshed by `init` and by the seed
        # stage below, but this branch said "nothing to do" without asking,
        # so the preview an adopter ran before `init` promised nothing and
        # `git status` then showed eleven modified docs. Same decision as
        # the write (`_deploy_seed_docs` on a dry run); skipped on self-host
        # with the packaged-surface preview, for the same reason.
        if not self_host:
            would_seed = _preview_seed_docs(repo_root)
            # Refreshed only: an untouched copy behind its packaged content
            # is drift the adopter did not choose. An ABSENT seed is not --
            # they are invited to own these files, and a deploy that never
            # seeded (a bare deploy_harness tree) or an adopter who deleted
            # one would otherwise never hear "nothing to do" again. The seed
            # stage below still previews the create, since --execute does it.
            pending_seeds = would_seed["refreshed"] if would_seed else []
            if pending_seeds:
                drift_lines.append(
                    f"{plural(len(pending_seeds), 'init-seeded doc')} behind the "
                    "packaged copy (re-deployed on --execute, named in the seed "
                    "stage below; an edited or unstamped copy is never counted)"
                )
        if drift_lines:
            print(f"[upgrade] engine version matches the stamp ({__version__}), "
                  "but the deployed surface is not current:")
            for line in drift_lines:
                print(f"[upgrade]   {line}")
            # Fall through: the stages below are the preview and the repair.
        else:
            # "Nothing to do" must be TRUE when it is said. The version stamp
            # answers "is the deployed code stale?", which is orthogonal to "is
            # your .gitignore missing required entries?" -- an adopter who ran
            # `--no-write-gitignore`, or who dropped an entry, is version-current
            # and still unprotected. Run the check (read-only here; it is silent
            # when nothing is missing) before making the claim.
            needed_entries = _handle_gitignore(
                repo_root,
                write_gitignore=getattr(args, "execute", False),
                rerun_hint="Re-run `upgrade --execute` to append these.",
            )
            # Same rule, same branch, for the profile's allow rules (DEF-715): a
            # version-current install is the steady state of the installed base,
            # and it was the one state that never heard the profile had moved.
            lacking = False
            if os.path.isfile(repo_root / ".claude" / "settings.json"):
                lacking = _report_allow_gaps_read_only(
                    repo_root, profile=installed_settings_profile(repo_root), prefix="[upgrade]",
                )
            # And once more for espalier's statusLine (DEF-798): a file wired
            # before the merge learned to add the key has none, and this branch
            # never merges -- name the state with the verb that does.
            no_statusline = False
            if os.path.isfile(repo_root / ".claude" / "settings.json"):
                # doctor's predicate, not the merge's: this branch never merges,
                # so it speaks about THIS tree -- key absent AND the script
                # deployed -- exactly as doctor's fourth note does, and the
                # two narrators cannot disagree about one tree.
                no_statusline = _doctor.espalier_statusline_missing(
                    repo_root / ".claude" / "settings.json", repo_root,
                )
            # And the same rule once more for the wiring itself (DEF-618, driven):
            # a version-current tree with an `echo`-neutered or shell-form gate
            # was told "nothing to do". The enforcement claim decides; the
            # disarmed narration names --repair.
            disarmed = False
            settings_path = repo_root / ".claude" / "settings.json"
            if os.path.isfile(settings_path):
                blockers = _enforcement_claim_blockers(repo_root, settings_path)
                if blockers is None or blockers:
                    disarmed = True
                    print(_disarmed_hook_tree_warning(
                        repo_root, prefix="[upgrade]", wrote_settings=False,
                    ), file=sys.stderr)
            # "Nothing to do" is said only when it is whole. The states that
            # keep the sentence true without being drift are counted beside
            # it: a kept file (the surface is not at packaged bytes), a
            # missing source, a .gitignore report, and every "not compared".
            # An unshipped recommendation (DEF-756) is named above but does
            # not qualify: the surface IS at packaged bytes, and no run of
            # this command could ever change that line.
            qualifiers: list[str] = []
            if kept:
                qualifiers.append(
                    f"{plural(len(kept), 'managed file')} kept as yours (listed above)"
                )
            if surface["source_missing"]:
                qualifiers.append(
                    f"{plural(len(surface['source_missing']), 'packaged source')} "
                    "missing from this engine install (see the warning above)"
                )
            if needed_entries:
                qualifiers.append("see the .gitignore report above")
            qualifiers.extend(f"not compared: {item}" for item in not_compared)
            if lacking or disarmed or no_statusline:
                states: list[str] = []
                if disarmed:
                    states.append("the hook tree above is not armed")
                if lacking:
                    states.append(("it" if states else "your .claude/settings.json")
                                  + " lacks the allow rules above")
                if no_statusline:
                    states.append(("it" if states else "your .claude/settings.json")
                                  + " has no statusLine")
                if disarmed:
                    remedy = " -- `merge-settings . --repair` does, on request"
                elif no_statusline:
                    remedy = (f" -- `{_remedy_py()} -m espalier merge-settings .` adds "
                              "espalier's statusLine, on request, and never touches one "
                              "of yours (set the key to null to keep the statusline off)")
                else:
                    remedy = ""
                joined = (states[0] if len(states) == 1
                          else ", ".join(states[:-1]) + " and " + states[-1])
                print(f"[upgrade] harness is current ({__version__}); "
                      + joined
                      + ", and upgrade never rewrites your settings.json"
                      + remedy + ".")
                for qualifier in qualifiers:
                    print(f"[upgrade] {qualifier}.")
            elif qualifiers:
                print(f"[upgrade] harness is current ({__version__}) on the "
                      "compared surface; " + "; ".join(qualifiers) + ".")
            else:
                print(f"[upgrade] harness is current ({__version__}); nothing to do.")
            return 0
    else:
        print(
            f"[upgrade] deployed {deployed_version} -> engine {__version__}.",
        )

    execute = getattr(args, "execute", False)
    mode = "EXECUTE" if execute else "dry-run"
    print(f"[upgrade] mode: {mode}")

    # A pre-rename adopter (a legacy MEMORY.md, no ESPALIER_MEMORY.md yet) learns of
    # the required migration only on --execute, where deploy_harness emits the
    # nudge. Surface it in the dry-run PREVIEW too, so the documented `upgrade .`
    # preview is not silent about a tracked file needing a rename. Execute still
    # gets it from deploy_harness; gated on dry-run here to avoid a double-print.
    if not execute and (repo_root / _LEGACY_MEMORY_FILENAME).exists() and not (
        repo_root / _MEMORY_FILENAME
    ).exists():
        _print_legacy_memory_nudge()

    # Captured before the deploy: on the (rare) path where the adopter deleted
    # their CLAUDE.md, the execute branch below re-renders it, and a nudge that
    # then said "kept your existing CLAUDE.md" would be false.
    claude_md_existed = (repo_root / "CLAUDE.md").exists()

    # Seed docs FIRST, as init orders them (cmd_init seeds before it calls
    # deploy_harness): the manifest deploy_harness renders lists the packaged
    # root docs that exist on disk, so seeding after that render left
    # cc/PACK_MANIFEST.txt one run behind, and the preview an adopter ran to
    # confirm their --execute reported the command's own work as drift (driven
    # by the failure-mode review of DEF-726: two rounds to converge).
    # Re-deploy through the SAME stamp-driven refresh path init uses, so an
    # operator-untouched-but-stale convention scaffold gets the current
    # packaged bytes on upgrade (edited / legacy-unstamped copies are
    # preserved). deploy_harness never re-visits the seed docs -- this is the
    # only upgrade path to them.
    # The preview and the write read ONE decision (`_deploy_seed_docs` on a
    # dry run): until 2026-09-12 the preview was a static sentence and only
    # --execute named the seeds, so an adopter read eleven modified docs in
    # `git status` after an upgrade whose preview had said nothing (DEF-774).
    if not execute:
        would = _preview_seed_docs(repo_root)
        if would is not None:
            print("[upgrade] would re-deploy init-seeded docs: "
                  + _seed_outcome_sentence(would, done=False))
    else:
        done = _deploy_seed_docs(repo_root)
        print("[upgrade] re-deployed init-seeded docs: "
              + _seed_outcome_sentence(done, done=True))
        legacy = _count_unstamped_seed_docs(repo_root)
        if legacy:
            # The same state `doctor` names, so the same two remedies in the
            # same order: the stamp (which `doctor` prints) keeps an edited
            # copy; delete-then-re-seed is for a copy never edited -- said so,
            # because for the two grounding docs the re-seed is the near-empty
            # stub (a bare "delete a stale one" stood here until 2026-09-05).
            py = _remedy_py()
            print(f"[upgrade] note: {plural(legacy, 'seed doc')} carry no "
                  "seed-version stamp (legacy, or the first line was removed) -- "
                  f"can't prove untouched, so left as-is. `{py} -m espalier "
                  "doctor .` names each one and prints the exact stamp line to "
                  "paste back as line 1, which keeps your edits; only for a copy "
                  "you never edited, delete the file and re-run "
                  f"`{py} -m espalier init .` to re-seed it at current bytes.")

    # Re-deploy plan (preview vs apply). deploy_harness is idempotent and honors
    # the managed-marker policy: drifted managed files regenerate; unmarked user
    # files are preserved.
    if not execute:
        print("[upgrade] would re-deploy managed assets (hooks, agents, "
              "commands, skills, cc/ surface) via deploy_harness.")
        rebaseline_targets = [
            rel for rel in (
                "reports/repo_fingerprint.json", "reports/harness_config.json",
                "cc/SURFACE_HANDOFF.md",
            ) if (repo_root / rel).exists()
        ]
        if rebaseline_targets:
            print(f"[upgrade] would re-baseline {', '.join(rebaseline_targets)} "
                  "against the re-deployed surface -- the plan is regenerated "
                  "from the fingerprint and only settings_profile is carried "
                  "over, so hand edits to it are replaced.")
        # The two plan-reading cc/ docs follow the re-baselined plan on
        # --execute (DEF-806), while the drift line above classifies them
        # against the plan on DISK -- so a plan whose actions change under a
        # fresh fingerprint would leave the preview naming nothing that the
        # execute then rewrites (the lane's failure-mode review drove it: a
        # one-file preview, three files modified). Predict it from the same
        # fingerprint --execute takes; only a doc that exists and carries the
        # marker follows, as the classifier would decide.
        if "reports/harness_config.json" in rebaseline_targets:
            from espalier.render_surface import _load_stable_actions

            config = _load_config(repo_root, args)
            fresh = build_harness_config(fingerprint_repo(repo_root, config), config)
            if fresh.stable_actions != _load_stable_actions(repo_root):
                followers: list[str] = []
                for rel in PLAN_READERS:
                    try:
                        if has_managed_marker((repo_root / rel).read_text(encoding="utf-8")):
                            followers.append(rel)
                    except (OSError, ValueError):
                        continue  # absent or unreadable: the classifier leaves it alone too
                if followers:
                    print(f"[upgrade] would re-render {plural(len(followers), 'cc/ surface doc')} "
                          "that read the plan, whose actions change under a fresh "
                          "fingerprint: " + _name_paths(followers))
        if surface_contract.is_effectively_empty_file(
            repo_root / ".claude" / "settings.json"
        ):
            # The one preserve-rule exception deploy_harness makes (DEF-700):
            # say so here, where the operator reads before --execute.
            print("[upgrade] would rewrite an EMPTY .claude/settings.json in "
                  "place (0 bytes or whitespace: nothing to preserve).")
    else:
        config = _load_config(repo_root, args)
        fp = fingerprint_repo(repo_root, config)
        harness = build_harness_config(fp, config)
        result = deploy_harness(repo_root, harness, fp)
        written = list(result["deployed"])
        print(f"[upgrade] re-deployed {plural(len(written), 'file')}"
              + (": " + _name_paths(written) if written else "") + ".")
        # The saved plan is the inventory oracle `doctor` reads. A deploy that
        # left it as it was would leave the two narrators disagreeing after
        # the one command whose job is to reconcile them (DEF-728), the way
        # install-ci did before it re-baselined what it changed (DEF-688).
        # Existence-guarded the same way: a tree that never ran init gains no
        # reports/. The fingerprint and plan were computed above, for the
        # deploy, so this writes what was just deployed from. It REPLACES the
        # plan (as `fingerprint .` does; settings_profile is the one carried
        # key), and both modes say so.
        fp_path = repo_root / "reports" / "repo_fingerprint.json"
        had_fingerprint = fp_path.exists()
        try:
            if had_fingerprint:
                atomic_write_text(
                    fp_path, json.dumps(fp.to_dict(), indent=2, sort_keys=True) + "\n",
                )
            refreshed, refresh_failures = _refresh_fingerprint_derivatives(
                repo_root, fp, config,
            )
        except Exception as exc:  # noqa: BLE001 -- best-effort; the deploy above already landed
            print(f"[upgrade] WARN: could not re-baseline the saved plan: {os_error_text(exc)}",
                  file=sys.stderr)
        else:
            rebaselined = (["reports/repo_fingerprint.json"] if had_fingerprint else []) + refreshed
            if rebaselined:
                print(f"[upgrade] re-baselined {', '.join(rebaselined)} "
                      "(regenerated from the fingerprint; settings_profile kept, "
                      "hand edits to the plan replaced).")
            if refresh_failures:
                print(f"[upgrade] WARN: "
                      f"{plural(len(refresh_failures), 'downstream artifact')} "
                      f"failed to refresh: {refresh_failures}", file=sys.stderr)

    # `upgrade` is the path this report matters most on, and it was nearly
    # missed: an adopter running an espalier old enough to predate a required
    # section has a CLAUDE.md that never contained it, and `upgrade` -- not
    # `init` -- is the verb they reach for ("deployed X -> engine Y"). Since
    # nothing in this command ever rewrites a CLAUDE.md that already exists, the
    # check is read-only and correct on the dry-run path too, so it is NOT
    # gated on `execute`: a preview that stayed silent about it would be the
    # same silence the fix exists to remove.
    _print_claude_md_nudge(
        repo_root / "CLAUDE.md", preserved=claude_md_existed
    )

    # .gitignore: the SAME reasoning as the nudge directly above, and it was
    # missed for exactly as long. `_handle_gitignore` had one call site
    # (`_print_init_summary` <- `cmd_init`), so an adopter who installed once
    # and thereafter runs `upgrade` received NONE of the required entries
    # added since their install -- not just the newest one, every one. The
    # installed base is precisely the population a required-entry addition
    # exists for, and it was the only population that never heard about it.
    #
    # Writes on --execute, reports on dry-run: `_handle_gitignore` prints the
    # paste-me block either way, so the preview is honest rather than silent.
    _handle_gitignore(
        repo_root,
        write_gitignore=execute,
        rerun_hint="Re-run `upgrade --execute` to append these.",
    )

    # settings.json: route through the SAME merge primitive init --wire-hooks
    # uses. Never clobbers operator keys.
    settings_path = repo_root / ".claude" / "settings.json"
    if os.path.isfile(settings_path):
        # Permissions are the operator's: upgrade appends hook events (and
        # espalier's statusLine when that key is absent, DEF-798) and REPORTS
        # the profile allow rules the file lacks, in both modes, with the
        # opt-in that appends them (DEF-715: an install predating a profile rule
        # never received it, and nothing said so).
        profile = installed_settings_profile(repo_root)
        if not execute:
            print("[upgrade] would run merge-settings on .claude/settings.json "
                  "(preserves your keys; keeps a .bak of them).")
            if _statusline_key_absent(settings_path):
                print("[upgrade] would add espalier's statusLine (the key is absent; "
                      "a statusLine of your own is never touched).")
            _report_allow_gaps_read_only(repo_root, profile=profile, prefix="[upgrade]")
        else:
            merge_result = merge_hooks_into_settings(
                settings_path, profile=profile, repo_root=repo_root,
            )
            if merge_result.status == MERGE_WIRED:
                print(f"[upgrade] {_merge_did_phrase(merge_result, noun='hook event')} "
                      f"into settings.json (backup {merge_result.detail}).")
            elif merge_result.status == MERGE_ALREADY:
                # "Current" is the merge's word for "every event carries an
                # espalier entry"; a neutered or shell-form entry counts. Say
                # so only when the enforcement claim holds, else narrate the
                # disarmed tree the way init does (it names --repair).
                if _enforcement_claim_blockers(repo_root, settings_path) == []:
                    print("[upgrade] settings.json hooks already current.")
                else:
                    print(_disarmed_hook_tree_warning(
                        repo_root, prefix="[upgrade]", wrote_settings=False,
                    ), file=sys.stderr)
            else:
                print(f"[upgrade] WARN: settings.json not merged "
                      f"({merge_result.status}: {merge_result.detail}); "
                      "preserved unchanged.", file=sys.stderr)
            _report_allow_gaps(
                missing=merge_result.missing_allows, added=(), note=merge_result.allow_note,
                profile=profile, prefix="[upgrade]",
                hint_command=lambda: _merge_settings_hint(profile),
            )

    # Surface retired managed files (report-only; never deletes -- Scope (out)).
    orphans = _scan_managed_orphans(repo_root)
    if orphans:
        print("[upgrade] retired managed files (review; remove with "
              f"`{_remedy_py()} -m espalier clean-generated . --execute` if unwanted):")
        for rel in orphans:
            print(f"  - {rel}")

    # Integrity: refresh on --execute, report on dry-run.
    if not execute:
        print("[upgrade] would refresh .espalier/integrity.json after re-deploy.")
    else:
        try:
            load_integrity_module().write_manifest(repo_root)
            print("[upgrade] refreshed .espalier/integrity.json.")
        except (FileNotFoundError, OSError) as exc:
            print(f"[upgrade] WARN: could not refresh integrity manifest: {os_error_text(exc)}",
                  file=sys.stderr)

    if not execute:
        print("[upgrade] dry-run complete. Re-run with --execute to apply.")
    return 0


def _refresh_fingerprint_derivatives(repo_root: Path, fp, config) -> tuple[list[str], list[str]]:
    """Re-derive the artifacts downstream of ``reports/repo_fingerprint.json``
    -- ``reports/harness_config.json``, the cc/ docs that read the plan
    (``render_surface.PLAN_READERS``: ``cc/LIVE_SURFACE.md`` and
    ``cc/COMMANDS.md``) and ``cc/SURFACE_HANDOFF.md`` -- but only where they
    already exist; first-time creation belongs to ``init``.

    Returns ``(refreshed, failures)`` as repo-relative labels. Each refresh is
    wrapped so a failure in one does not hide that the fingerprint was
    already written (the caller prints both lists). Shared by
    ``cmd_fingerprint``, ``cmd_install_ci`` and ``cmd_upgrade``: install-ci
    changes what the fingerprint reports (``ci_providers``) and must leave
    the same baseline a hand-run ``fingerprint`` would. The two plan-reading
    docs follow the plan for the same reason (DEF-806): a plan that gained
    an action -- a non-Python host's fusion gains ``scan`` once the engine
    is overlaid -- left the docs init rendered from the old plan stale, and
    the next ``upgrade`` named them as drift on a change this refresh made.
    A doc is listed under ``refreshed`` only when its render moved; a
    byte-identical render, an absent doc and an un-marked (adopter-owned)
    doc are left alone, the way ``init`` and ``upgrade`` treat them.
    """
    refreshed: list[str] = []
    failures: list[str] = []
    plan_path = repo_root / "reports" / "harness_config.json"
    if plan_path.exists():
        try:
            # A rebuild must not forget which settings profile init rendered
            # (`settings_profile`); the value only init knows is carried over.
            recorded = installed_settings_profile(repo_root)
            harness = build_harness_config(fp, config)
            plan_dict = harness.to_dict()
            if surface_contract.is_self_host_repo(repo_root):
                plan_dict = _self_host_plan_overlay(plan_dict, repo_root)
            plan_dict["settings_profile"] = recorded
            atomic_write_text(plan_path, json.dumps(plan_dict, indent=2, sort_keys=True) + "\n")
            refreshed.append("reports/harness_config.json")
        except Exception as e:  # noqa: BLE001
            failures.append(f"reports/harness_config.json ({type(e).__name__}: {os_error_text(e)})")

    # The plan's readers follow the plan -- and only after the plan was
    # rewritten above, so a failed plan write never re-renders docs from a
    # plan the tree does not hold. Through the one classifier init and
    # upgrade use (marker-aware, byte-identical render left untouched),
    # existing docs only. PACK_MANIFEST.txt is not a reader (see PLAN_READERS).
    if "reports/harness_config.json" in refreshed:
        for rel in PLAN_READERS:  # one call per doc: a failure names its own path
            try:
                for _rel, action in write_required_surface(
                    repo_root, targets=(rel,), existing_only=True,
                ):
                    if action == "updated_managed":
                        refreshed.append(_rel)
            except Exception as e:  # noqa: BLE001 -- best-effort like its siblings; the plan is already written
                failures.append(f"{rel} ({type(e).__name__}: {os_error_text(e)})")

    handoff_path = repo_root / "cc" / "SURFACE_HANDOFF.md"
    if handoff_path.exists():
        try:
            write_surface_handoff(repo_root)
            refreshed.append("cc/SURFACE_HANDOFF.md")
        except Exception as e:  # noqa: BLE001
            failures.append(f"cc/SURFACE_HANDOFF.md ({type(e).__name__}: {os_error_text(e)})")
    return refreshed, failures


def cmd_fingerprint(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    config = _load_config(repo_root, args)
    fp = fingerprint_repo(repo_root, config)
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    fp_path = reports_dir / "repo_fingerprint.json"
    atomic_write_text(fp_path, json.dumps(fp.to_dict(), indent=2, sort_keys=True) + "\n")
    print(json.dumps(fp.to_dict(), indent=2, sort_keys=True))

    # Refresh downstream artifacts that derive from the fingerprint, but only
    # when they already exist — first-time creation belongs to `init`. This
    # keeps `harness_config.json`, the two cc/ docs that read it and
    # `cc/SURFACE_HANDOFF.md` from silently diverging from a freshly captured
    # baseline.
    #
    # Each downstream refresh is wrapped so a failure in one doesn't
    # leave the user unaware that `repo_fingerprint.json` was updated but
    # its derivatives weren't (an unwrapped exception in build_harness_config
    # would surface as a raw traceback with no hint that the fingerprint had
    # already been refreshed).
    refreshed, refresh_failures = _refresh_fingerprint_derivatives(repo_root, fp, config)

    if refresh_failures:
        print(
            f"WARN: fingerprint was refreshed but {plural(len(refresh_failures), 'downstream artifact')} "
            f"failed: {refresh_failures}. "
            f"Inconsistency between fingerprint and these artifacts may "
            f"surface in later commands. Re-run after fixing the underlying "
            f"issue.",
            file=sys.stderr,
        )

    if refreshed:
        print(f"Refreshed downstream: {', '.join(refreshed)}", file=sys.stderr)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    # Parity with `doctor`: a fresh source checkout or never-initialized repo is
    # not an audit failure — the surface gate's required files are init-
    # generated. Detect the mode and give first-run guidance instead of a red
    # exit-1, matching cmd_doctor's uninitialized branch so the two commands
    # agree on a fresh tree. Mirrors the cmd_init onboarding-nudge idiom,
    # OSError guard included (detect_repo_mode probes the tree with
    # Path.exists(), which can raise PermissionError).
    from espalier.repo_mode import (
        detect_repo_mode,
        REPO_MODE_SOURCE_CHECKOUT,
        REPO_MODE_UNINITIALIZED,
    )
    try:
        mode = detect_repo_mode(repo_root)
    except OSError:
        mode = None  # unreadable tree — fall through to the normal surface gate
    if mode in (REPO_MODE_SOURCE_CHECKOUT, REPO_MODE_UNINITIALIZED):
        print(
            f"{repo_root.name}: source checkout / not initialized -- "
            f"harness surface not deployed yet. Run `{_remedy_py()} -m espalier init .` "
            f"first; audit checks the deployed surface."
        )
        return 0
    report = run_cc_surface_gate(repo_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] == "pass":
        return 0
    # Actionable next step on stderr — operator scanning the terminal
    # sees what to do without parsing the JSON above.
    print(
        f"Audit failed: {plural(report['summary']['errors'], 'error')}, "
        f"{plural(report['summary']['warnings'], 'warning')}. Address the findings "
        f"above, then re-run: {_remedy_py()} -m espalier audit {args.repo}",
        file=sys.stderr,
    )
    return 1


def cmd_selfcheck(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    from espalier.selfcheck import run_contracts, run_selfcheck

    # The three deployed-tree contracts (live deny-path, upstream parity,
    # live kill-switch) read the adopter's tree, so they are a separate arm
    # from the bundled engine tests, which never do (DEF-735). On a tree
    # that was never initialized there is no deployed tree to read: say so
    # with the next step, at the precondition exit, instead of a report that
    # fails C-1 on a missing hook and names no remedy (the DEF-770 shape).
    if getattr(args, "contracts", False):
        from espalier.repo_mode import REPO_MODE_UNINITIALIZED, detect_repo_mode
        if detect_repo_mode(repo_root) == REPO_MODE_UNINITIALIZED:
            py, _clears = _remedy_interpreter()
            print(
                f"selfcheck --contracts: {repo_root} is not initialized for "
                "Espalier-Harness, and the contracts read the deployed tree. "
                f"Run `{py} -m espalier init {repo_root}` first.",
                file=sys.stderr,
            )
            return 2
        return run_contracts(repo_root)
    return run_selfcheck(repo_root)


def cmd_diff(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    report = diff_repo(repo_root, Path(args.config).resolve() if args.config else None)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["fingerprint_changed"] or report["build_plan_changed"] else 0


def cmd_recover(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    report = assess_repo_state(repo_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "pass" else 1


def cmd_reflect(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    report = reflect_repo(repo_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    healthy = not report.get("plan_missing_docs") and not report.get("broken_markdown_links")
    return 0 if healthy else 1


def cmd_reflect_deep(args: argparse.Namespace) -> int:
    """Run the full structured reflect protocol from DEEP-WORK.md."""
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    pass_number = getattr(args, "pass_number", 1)
    rp = run_reflect_pass(repo_root, pass_number=pass_number)
    if args.json:
        print(json.dumps(rp.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_reflect_pass(rp), end="")
    # Record in active blueprint if one exists
    blueprint = load_latest_blueprint(repo_root)
    if blueprint:
        record_reflect_pass(blueprint, rp)
        save_blueprint(repo_root, blueprint)
        print(f"\nRecorded pass {pass_number} in blueprint {blueprint.session_id}")
    return 0 if rp.gap_count == 0 else 1


def cmd_blueprint(args: argparse.Namespace) -> int:
    """Cognitive blueprint operations: start, record, finalize, load, chain."""
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    action = args.action

    match action:
        case "start":
            bp = start_session(repo_root)
            save_blueprint(repo_root, bp)
            print(f"Started session {bp.session_id} (depth {bp.accumulated_depth})")
            if bp.parent_session_id:
                # Show continuation fragments from parent if they were carried
                print(f"Chained from: {bp.parent_session_id}")
            return 0

        case "record":
            bp = load_latest_blueprint(repo_root)
            if not bp:
                print(f"No active blueprint. Run `{_remedy_py()} -m espalier blueprint start` first.", file=sys.stderr)
                return 1
            kind = args.kind or "decision"
            description = args.description
            if not description:
                print("--description is required for record", file=sys.stderr)
                return 1
            evidence = args.evidence.split(",") if args.evidence else []
            add_reasoning(bp, kind, description, evidence)
            save_blueprint(repo_root, bp)
            print(f"Recorded {kind}: {description}")
            return 0

        case "finalize":
            bp = load_latest_blueprint(repo_root)
            if not bp:
                print("No active blueprint.", file=sys.stderr)
                return 1
            if args.fragments:
                bp = set_continuation_fragments(bp, args.fragments.split("|"))
            else:
                frags = auto_continuation_fragments(bp)
                bp = set_continuation_fragments(bp, frags)
            save_blueprint(repo_root, bp)
            if args.json:
                print(json.dumps(bp.to_dict(), indent=2, sort_keys=True))
            else:
                print(render_blueprint_md(bp), end="")
            return 0

        case "load":
            bp = load_latest_blueprint(repo_root)
            if not bp:
                print("No blueprint found.", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(bp.to_dict(), indent=2, sort_keys=True))
            else:
                print(render_context_load(bp), end="")
            return 0

        case "chain":
            chain = list_blueprint_chain(repo_root)
            if args.json:
                print(json.dumps(chain, indent=2, sort_keys=True))
            else:
                print(f"Session chain: {len(chain)} blueprints")
                for entry in chain:
                    depth = entry.get("accumulated_depth", "?")
                    reasoning = entry.get("reasoning_count", 0)
                    reflects = entry.get("reflect_pass_count", 0)
                    frags = entry.get("continuation_fragment_count", 0)
                    conv = entry.get("gap_convergence", [])
                    conv_str = " -> ".join(str(g) for g in conv) if conv else "—"
                    print(f"  [{depth}] {entry['session_id']}  "
                          f"reasoning={reasoning} reflects={reflects} "
                          f"fragments={frags} gaps={conv_str}")
            return 0

        case _:
            # Reachable via a DIRECT cmd_blueprint(...) call (argparse pins the
            # action choices only on the CLI path); pinned by
            # tests/test_cli.py::TestCmdBlueprintExtendedActions. Keep the
            # defensive default — not dead.
            print(f"Unknown blueprint action: {action}", file=sys.stderr)
            return 1


def cmd_surface_handoff(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    if args.json:
        print(json.dumps(build_surface_handoff(repo_root), indent=2, sort_keys=True))
        return 0
    out = write_surface_handoff(repo_root, Path(args.out).resolve() if args.out else None)
    print(f"Wrote surface handoff: {out}")
    return 0


def cmd_self_host(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    mode = getattr(args, "mode", "auto")
    report = run_self_host_check(repo_root, mode=mode)
    print(json.dumps(report, indent=2, sort_keys=True))
    # 'uninitialized' is a structured-hint state and 'skipped_release_export' a
    # correct stand-down -- neither is a failure, so first-run users don't see a
    # generic error code. The accept-set is owned by self_hosting, shared with
    # its own main(), doctor and pre_release.
    return 0 if gate_failure_reason(report) is None else 1


def cmd_worktree_plan(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    plan = build_worktree_plan(repo_root)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(render_worktree_plan(plan), end="")
    return 0


# Shared clause for every verb that must stand down off the self-host tree.
# One literal so the three messages cannot drift, and so the contract test can
# assert on a phrase with a single owner.
_SELF_HOST_SCOPE_CLAUSE = "applies only to the Espalier-Harness source tree"


def _off_self_host(repo_root: Path) -> bool:
    """True when ``repo_root`` is NOT the Espalier-Harness source tree.

    Gate for the verbs measured applying Espalier's OWN standards, vocabulary
    or branding to an adopter's content. Deliberately checked at the VERB and
    not at each caller: five deployed command bodies actually invoke one of
    these (seven name one, counting the agent body), and the reason a
    per-carrier fix is the wrong unit is already visible in the tree --
    `/preflight` wraps `pre-release` in this very predicate while
    `/implement-pack` runs the identical command unguarded. Gating here makes
    every carrier safe at once, including the ones nobody remembers.

    Note the direction of failure. If `is_self_host_repo` ever false-negatives
    on this repo (it needs 5 signals, one a content-hash pin on write_guard.py),
    these verbs would stand down HERE. That is why the census keeps a caller
    that does not route through the CLI: `tests/test_no_provenance_in_shipped_code.py`
    calls `census_offenders()` directly, so the regression gate cannot be
    disabled by a stale pin — only the convenience verb goes quiet, and
    `tests/test_adopter_verb_stand_down.py::TestTheGateIsNotVacuousOnSelfHost`
    reds when it does.
    """
    return surface_contract.off_self_host(repo_root)


def cmd_provenance(args: argparse.Namespace) -> int:
    """De-provenance census: exit 2 if any internal build-history tag survives on
    a shipping surface, outside the load-bearing allowlist. The fast-loop twin of
    tests/test_no_provenance_in_shipped_code.py — same source of truth
    (espalier.provenance_census), so /smoke (or an ad-hoc run) catches a stray tag
    before the full-suite gate does."""
    from espalier.provenance_census import census_offenders, format_offenders
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    if _off_self_host(repo_root):
        # Exit 0, and that code is the point. The deployed .claude/commands/
        # commit.md instructs this command and says "Do NOT stage until it
        # exits 0"; PROVENANCE_RE matches `TP-`/`TQ-`/`XPLAT-`, which are
        # Espalier's internal task vocabulary AND ordinary ticket prefixes, and
        # the census scans the adopter's own tracked source. So on an adopter
        # tree this exited 2 over their Jira references and told them to edit
        # `_ALLOWED_HITS` — a private constant inside the installed engine that
        # they cannot change and that would not survive an upgrade. Standing
        # down with 0 unwedges the commit path everywhere at once.
        print(
            f"Provenance census {_SELF_HOST_SCOPE_CLAUSE} -- skipping "
            f"(adopter repo). It polices Espalier's own internal build-history "
            f"tags, which have no meaning in your repo."
        )
        return 0
    offenders = census_offenders(repo_root)
    if offenders:
        print(format_offenders(offenders), file=sys.stderr)
        return 2
    print("Provenance census: clean (no build-history tags on shipping surfaces).")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    from espalier.scanners.exceptions import scan_repo as scan_exc
    from espalier.scanners.prints import scan_repo as scan_prints
    from espalier.scanners.godfiles import scan_repo as scan_god
    from espalier.scanners.perf_smells import scan_repo as scan_perf
    from espalier.scanners.test_loosening import scan_repo as scan_test_loose
    from espalier.scanners.convergence_theater import build_report as scan_ct_report
    from espalier.scanners.subprocess_contracts import build_report as scan_sc_report
    from espalier.scanners.filesystem_contracts import build_report as scan_fc_report
    from espalier.scanners.magic_depth import build_report as scan_md_report
    from espalier.scanners.retired_vocab import build_report as scan_rv_report
    from espalier.scanners.encoding_contracts import build_report as scan_ec_report

    # Honest WARN for non-Python primary repos. Scanners are
    # AST-based and produce empty findings against non-Python code; the
    # WARN distinguishes "0 findings because not applicable" from "0
    # findings because clean."
    fp = fingerprint_repo(repo_root)
    primary = fp.languages[0] if fp.languages else None
    if primary and primary != "python":
        print(
            f"[WARN] Espalier scanners are Python-specific (AST-based). "
            f"Running on a primarily-{primary} repo will likely produce "
            f"empty findings. This is not a guarantee of code quality. "
            f"See README.md 'Honest scope' for what v0.7 does and does "
            f"not cover for non-Python repos.",
            file=sys.stderr,
        )

    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Every finding report is written through this one helper, which records
    # the terminal label and the headline count beside the file it wrote. The
    # counts line and the details line below are derived from that record,
    # so the terminal cannot name a file the scan did not write or drop one
    # it did (DEF-773: until 2026-09-12 the counts line was the whole output,
    # and nothing said that the reports under reports/ carry the file and
    # line of every finding it counted).
    # (label, report basename, headline count, whether the scanner ran here)
    written: list[tuple[str, str, int, bool]] = []

    def _write_report(
        path: Path, payload: dict, label: str, count: int, *, ran: bool = True,
    ) -> None:
        # The full path at each call site, `reports_dir / "<name>.json"`, on
        # purpose: tests/test_forced_copy_parity.py reads those literals to
        # pin that every canonical scan_composition.REPORT_FILES name is
        # written here.
        atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))
        written.append((label, path.name, count, ran))

    exc_report = scan_exc(str(repo_root))
    _write_report(reports_dir / "scan_exceptions.json", exc_report, "Exceptions", exc_report["count"])

    prints_report = scan_prints(str(repo_root))
    _write_report(reports_dir / "scan_prints.json", prints_report, "Prints", prints_report["count"])

    god_report = scan_god(str(repo_root))
    _write_report(reports_dir / "godfiles_report.json", god_report, "Large files", god_report["above_threshold"])

    perf_report = scan_perf(str(repo_root))
    _write_report(reports_dir / "scan_perf_smells.json", perf_report, "Perf hotspots", perf_report["files_with_hits"])

    test_loose_report = scan_test_loose(str(repo_root))
    _write_report(reports_dir / "scan_test_loosening.json", test_loose_report, "Test-loosening", test_loose_report["count"])

    ct_report = scan_ct_report(repo_root)
    _write_report(reports_dir / "scan_convergence_theater.json", ct_report, "Theater", ct_report["count"])

    # The espalier-pinned scanners (subprocess/filesystem/magic_depth registries
    # + retired_vocab's retired migration vocab + encoding_contracts' whole-tree
    # net over locale-following text I/O, tests included) police ESPALIER's own
    # contract/migration terms — zero value on an adopter repo, and retired_vocab
    # over-flags an adopter's own uppercase-bold roadmap severity labels (see the
    # fusion_manifest FINISH_UP note). Gate them to the self-host repo: emit an
    # EMPTY report (count 0, findings []) on adopter repos so every downstream
    # key/telemetry row/report file stays present (the summary + scan_telemetry
    # contracts pin all 11), while the no-value repo-walk is skipped. Mechanical
    # replacement for the fragile manual FINISH_UP step-2 registry-empty.
    _pinned_self_host = surface_contract.is_self_host_repo(repo_root)

    # Each adopter-path report gets its OWN fresh dict + findings list (inline
    # literal, not a shared template) so the five reports can never alias one
    # another's findings list under a future mutating edit.
    sc_report = scan_sc_report(repo_root) if _pinned_self_host else {"count": 0, "findings": []}
    _write_report(reports_dir / "scan_subprocess_contracts.json", sc_report, "Subproc",
                  sc_report["count"], ran=_pinned_self_host)

    fc_report = scan_fc_report(repo_root) if _pinned_self_host else {"count": 0, "findings": []}
    _write_report(reports_dir / "scan_filesystem_contracts.json", fc_report, "FS",
                  fc_report["count"], ran=_pinned_self_host)

    md_report = scan_md_report(repo_root) if _pinned_self_host else {"count": 0, "findings": []}
    _write_report(reports_dir / "scan_magic_depth.json", md_report, "MagicDepth",
                  md_report["count"], ran=_pinned_self_host)

    rv_report = scan_rv_report(repo_root) if _pinned_self_host else {"count": 0, "findings": []}
    _write_report(reports_dir / "scan_retired_vocab.json", rv_report, "RetiredVocab",
                  rv_report["count"], ran=_pinned_self_host)

    ec_report = scan_ec_report(repo_root) if _pinned_self_host else {"count": 0, "findings": []}
    _write_report(reports_dir / "scan_encoding_contracts.json", ec_report, "Encoding",
                  ec_report["count"], ran=_pinned_self_host)

    # Typed result envelope so consumers can distinguish silence
    # (no .py files) from emptiness (.py files scanned, no findings).
    py_files_scanned = exc_report.get("files_scanned", 0)
    if py_files_scanned == 0:
        summary = {"status": "skipped_no_python_files"}
        print("Result: skipped_no_python_files (no .py files in repo)")
    else:
        summary = {
            "status": "scanned",
            "files_scanned": py_files_scanned,
            "exceptions": exc_report["count"],
            "prints": prints_report["count"],
            "large_files": god_report["above_threshold"],
            "perf_hotspots": perf_report["files_with_hits"],
            "test_loosening": test_loose_report["count"],
            "convergence_theater": ct_report["count"],
            "subprocess_contracts": sc_report["count"],
            "filesystem_contracts": fc_report["count"],
            "magic_depth": md_report["count"],
            "retired_vocab": rv_report["count"],
            "encoding_contracts": ec_report["count"],
        }
        # The record that wrote the files prints the counts, in write order,
        # then names the report behind each non-zero count -- the usable next
        # step -- or the directory when there is nothing to open.
        print(" | ".join(f"{label}: {count}" for label, _name, count, _ran in written))
        # Paths as the operator can open them: relative when the scanned
        # repo is the cwd, else under the repo they named.
        rel_ok = repo_root.resolve() == Path.cwd().resolve()
        # the directory spelled by the host (`Path` joins with its separator);
        # the trailing `/` is the message's, not a path component -- `os.sep`
        # here tripped the repo's own path-hazard audit (2026-09-24)
        where = "reports/" if rel_ok else f"{Path(repo_root) / 'reports'}/"
        with_findings = [name for _label, name, count, _ran in written if count]
        not_run = [label for label, _name, _count, ran in written if not ran]
        if with_findings:
            print(
                f"Details (file and line per finding), under {where}: "
                + ", ".join(with_findings)
            )
        else:
            print(
                f"No findings; the {plural(len(written), 'scan report')} this "
                f"run wrote are under {where}"
                + (
                    f" ({', '.join(not_run)}: Espalier-only scanners that do "
                    "not run here, so their reports are empty)."
                    if not_run else "."
                )
            )

    # Surface unreadable/skipped files at the interface the user actually sees.
    # A single dangling symlink / permission-denied .py no longer aborts the
    # scan (each scan_repo tolerates it per-file); this WARN points at the
    # 'skipped' key the four dict-returning scanners now carry.
    skipped_files = {
        s["file"]
        for r in (exc_report, prints_report, perf_report, test_loose_report, ec_report)
        for s in r.get("skipped", [])
    }
    if skipped_files:
        print(
            f"[WARN] {len(skipped_files)} unreadable file(s) (dangling symlink / "
            f"permission-denied) were skipped; the scan completed on the rest. "
            f"See the 'skipped' key in reports/scan_*.json.",
            file=sys.stderr,
        )
    # Append per-scanner telemetry history (fires + exemptions) BEFORE the
    # point-in-time scan_summary.json write. `fires` come from the `summary`
    # dict already built above (display keys diverge from scanner names:
    # godfiles->large_files, perf_smells->perf_hotspots); `exemptions` come from
    # count_pragmas on the 3 pragma scanners (each walks its OWN divergent
    # scope), 0 otherwise. History lands in an espalier-owned reports/ artifact,
    # never the hook audit log (import-direction boundary).
    if summary.get("status") == "scanned":
        from datetime import datetime, timezone
        from espalier import scan_telemetry
        from espalier.scanners import convergence_theater as _ct
        from espalier.scanners import magic_depth as _md
        from espalier.scanners import subprocess_contracts as _sc
        from espalier.scanners import encoding_contracts as _ec
        _FIRES_KEY = {
            "exceptions": "exceptions", "prints": "prints",
            "godfiles": "large_files", "perf_smells": "perf_hotspots",
            "test_loosening": "test_loosening",
            "convergence_theater": "convergence_theater",
            "subprocess_contracts": "subprocess_contracts",
            "filesystem_contracts": "filesystem_contracts",
            "magic_depth": "magic_depth", "retired_vocab": "retired_vocab",
            "encoding_contracts": "encoding_contracts",
        }
        exemptions = {  # each count_pragmas walks its OWN scope
            "convergence_theater": _ct.count_pragmas(repo_root),
            "magic_depth": _md.count_pragmas(repo_root),
            "subprocess_contracts": _sc.count_pragmas(repo_root),
            # gated like its report: the whole-root walk has no value on an
            # adopter tree and would read third-party code beside the sources
            "encoding_contracts": _ec.count_pragmas(repo_root) if _pinned_self_host else 0,
        }
        run_ts = datetime.now(timezone.utc).isoformat()
        counts = {
            scanner: {"fires": summary[skey], "exemptions": exemptions.get(scanner, 0)}
            for scanner, skey in _FIRES_KEY.items()
        }
        scan_telemetry.append_run(reports_dir, run_ts, counts)
        # Persist the honored-pragma corpus (the labeled false-positive-budget
        # data a credibility pass consumes). Each collect_pragmas mirrors its
        # OWN scanner's divergent scope.
        overrides = (
            _ct.collect_pragmas(repo_root)
            + _md.collect_pragmas(repo_root)
            + _sc.collect_pragmas(repo_root)
            + (_ec.collect_pragmas(repo_root) if _pinned_self_host else [])
        )
        atomic_write_text(
            reports_dir / "scan_overrides.json",
            json.dumps({"count": len(overrides), "overrides": overrides},
                       indent=2, sort_keys=True) + "\n",
        )
        # Advisory scanner-credibility budget over telemetry history (CLI-layer
        # stdout; never exits non-zero). Silent unless a scanner is
        # candidate-wallpaper/candidate-noisy — no per-run noise.
        from espalier import scan_credibility
        wp = scan_credibility.wallpaper_report(scan_telemetry.read_history(reports_dir))
        flagged = {s: r for s, r in wp.items() if r["status"] not in ("healthy", "insufficient-data")}
        if flagged:
            print("Scan credibility (advisory): " + ", ".join(
                f"{s}={r['status']}" for s, r in sorted(flagged.items())))
        # --baseline snapshots current findings; otherwise, when a prior
        # baseline exists, annotate this run new vs pre-existing (advisory
        # stdout, never gates).
        if getattr(args, "baseline", False):
            n = scan_credibility.snapshot_baseline(reports_dir)
            print(f"Baseline snapshot: {n} findings -> reports/{scan_credibility.BASELINE_FILENAME}")
        else:
            _baseline = scan_credibility.load_baseline(reports_dir)
            if _baseline is not None:
                _diff = scan_credibility.diff_against_baseline(reports_dir, _baseline)
                if _diff["new"] or _diff["pre_existing"]:
                    print(f"Baseline diff (advisory): {len(_diff['new'])} new / "
                          f"{plural(len(_diff['pre_existing']), 'pre-existing finding')} vs baseline")
        # Advisory cross-scanner composition (files >=2 scanners flagged).
        # CLI-layer stdout; silent when none; never gates.
        from espalier import scan_composition
        shared = scan_composition.intersect(reports_dir)
        if shared:
            print(f"Cross-scanner (advisory): {plural(len(shared), 'file')} flagged by >=2 scanners")
    atomic_write_text(
        reports_dir / "scan_summary.json",
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    # A typo'd / missing path is NOT a fresh repo. Without this guard a
    # nonexistent path falls through to the "uninitialized" branch and advises
    # `init` on a path that does not exist, exiting 0. Return 1 (fail) — NOT 2 —
    # to honor the doctor exit-code contract in
    # docs/CLI_EXIT_CODES.md ("doctor uses only 0 and 1, never 2"; CI keys on
    # 0=pass/warn vs 1=fail). The distinct message differentiates it for humans.
    if not repo_root.is_dir():
        print(
            f"error: path does not exist or is not a directory: {args.repo}",
            file=sys.stderr,
        )
        return 1
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    # --mode auto -> detect; --mode source-checkout / initialized -> override.
    mode_arg = getattr(args, "mode", "auto")
    explicit_mode: str | None = None
    if mode_arg == "source-checkout":
        from espalier.doctor import REPO_MODE_SOURCE_CHECKOUT
        explicit_mode = REPO_MODE_SOURCE_CHECKOUT
    elif mode_arg == "initialized":
        # Caller asserts the repo IS initialized; let auto-detect pick
        # self-host vs consumer downstream.
        from espalier.doctor import (
            REPO_MODE_INITIALIZED_CONSUMER,
            REPO_MODE_INITIALIZED_SELF_HOST,
        )
        from espalier import surface_contract
        explicit_mode = (
            REPO_MODE_INITIALIZED_SELF_HOST
            if surface_contract.is_self_host_repo(repo_root)
            else REPO_MODE_INITIALIZED_CONSUMER
        )
    report = run_doctor_check(
        repo_root,
        config_path=config_path,
        skip_self_host=getattr(args, "skip_self_host", False),
        check_doc_drift=getattr(args, "check_doc_drift", False),
        mode=explicit_mode,
    )
    status = report.get("status", "unknown")

    # Uninitialized repos get a clean human-readable message rather than a
    # JSON dump of "everything is missing."
    if status == "uninitialized":
        repo_name = repo_root.name
        leftovers = report.get("leftovers") or []
        if leftovers:
            # DEF-770: the saved plan and the runtime markers outlived the
            # surface they describe (clean-generated --execute, or an init
            # that did not finish). Say that, name them, offer both next steps.
            hint, _clears = _remedy_interpreter()
            print(
                f"{repo_name}: harness not on disk (uninstalled, or an init that "
                "did not finish).\n"
                "Runtime state still here (clean-generated keeps it by contract): "
                f"{', '.join(leftovers)}\n"
                f"\n"
                f"Run `{hint} -m espalier init .` from the repo root to reinstall "
                "the harness.\n"
                "Removing it for good: delete the files above. .claude/settings.json "
                "is yours and\n"
                "stays (left unwired); the docs init seeded are listed under "
                "preserved_user_files\n"
                "in clean-generated's report, and the copies a wire took of your "
                "settings under\n"
                "settings_backups_kept.\n"
                f"\n"
                f"After init, re-run `{hint} -m espalier doctor .` for a full health check."
            )
            return 0  # Not a failure -- an uninstalled tree is a clean state.
        py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
        print(
            f"{repo_name}: not initialized for Espalier-Harness.\n"
            f"\n"
            f"Run `{py} -m espalier init .` from the repo root to set up the harness.\n"
            f"This deploys hooks, agents, and a `.claude/settings.json` wired\n"
            f"to enforce governance on every Claude Code tool call.\n"
            f"\n"
            f"After init, re-run `{py} -m espalier doctor .` for a full health check."
        )
        return 0  # Not a failure — first-run guidance.

    print(json.dumps(report, indent=2, sort_keys=True))
    # Human-facing one-liner on stderr so a terminal-scanning newcomer gets a
    # verdict without parsing ~300 lines of JSON. The machine contract (JSON on
    # stdout) is unchanged; the uninitialized case already returned above.
    if status == "warn":
        n = len(report.get("warnings", []))
        print(
            f"doctor: warn -- {plural(n, 'warning')}; review the report above.",
            file=sys.stderr,
        )
    elif status == "fail":
        n = len(report.get("failures", []))
        print(
            f"doctor: fail -- {plural(n, 'error')}; address the findings above.",
            file=sys.stderr,
        )
    elif status == "pass":
        print(f"doctor: {status} -- repo is healthy.", file=sys.stderr)
    # pass -> 0, warn -> 0 (advisory), fail -> 1
    return 1 if status == "fail" else 0


def cmd_clean_generated(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    dry_run = not getattr(args, "execute", False)
    report = clean_generated_surface(repo_root, dry_run=dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


def cmd_release_pack(args: argparse.Namespace) -> int:
    # A missing repo path would otherwise sail through and write an empty
    # 22-byte zip with exit 0 (looks like a successful release). Fail loudly.
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    if _off_self_host(repo_root):
        # REFUSES rather than standing down at 0, and the asymmetry with
        # provenance/pre-release is deliberate: no deployed command body runs
        # release-pack, so it is only ever typed by a human who wants an
        # artifact. A silent success producing nothing would be worse than a
        # refusal. Measured on a driven adopter tree, the unguarded verb wrote
        # dist/espalier-harness.zip containing the ADOPTER's own source
        # (src/, their README.md, their pyproject.toml) under Espalier's
        # branded archive name. The existing files_written == 0 guard below
        # cannot catch it — an initialized adopter tree packages 102 files, so
        # its premise ("not an espalier repo?") is false for exactly the
        # population that needed catching.
        print(
            f"error: release-pack {_SELF_HOST_SCOPE_CLAUSE}; refusing to "
            f"bundle this repo's contents into an Espalier release archive.",
            file=sys.stderr,
        )
        return 2
    output = Path(getattr(args, "output", "dist/espalier-harness.zip"))
    summary = create_release_zip(repo_root, repo_root / output)
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    # The is_dir() guard catches a MISSING path, but an existing empty /
    # non-harness dir would still produce a 22-byte zip with files_written=0 and
    # exit 0 — the same successful-looking no-op release. Fail loudly on zero.
    if summary.files_written == 0:
        print(
            f"error: no files packaged from {args.repo} (not an espalier repo?); "
            f"refusing to write an empty release archive",
            file=sys.stderr,
        )
        return 2
    if summary.enumeration == "tree" and _is_own_git_repo(repo_root):
        # The archive was written (the builder is honest about what it did),
        # but a git root that answered "tree" is git failing, and the artifact
        # holds every untracked public file. The WARN above on stderr is the
        # only other trace; a human typing this verb gets the exit code too.
        print(
            f"error: release archive built from the WORKING TREE of {args.repo}, "
            f"which owns a .git git could not answer for (see the WARN above); "
            f"untracked files would ship -- fix git rather than publish this",
            file=sys.stderr,
        )
        return 2
    return 0


def _manifest_algorithm(integrity, repo_root: Path) -> "str | None":
    """The algorithm name the manifest on disk declares, or ``None`` when there
    is no readable manifest (a fresh tree, an unreadable file) or the bridge
    module predates ``load_manifest`` (the one pre-split name this reads, so
    the ``getattr`` is the honest form rather than a backfill of a whole
    reader). A label beside the verdict, never the verdict itself."""
    loader = getattr(integrity, "load_manifest", None)
    if loader is None:
        return None
    try:
        manifest = loader(repo_root)
    except Exception:  # noqa: BLE001 -- the verdict came from verify_integrity; this is a label
        return None
    if not isinstance(manifest, dict):
        return None
    value = manifest.get("algorithm")
    return value if isinstance(value, str) else None


def cmd_integrity(args: argparse.Namespace) -> int:
    """Verify or refresh .espalier/integrity.json for protected files."""
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    action = args.action
    integrity = load_integrity_module()

    if action == "refresh":
        path = integrity.write_manifest(repo_root)
        rel = path.relative_to(repo_root) if path.is_relative_to(repo_root) else path
        print(f"Wrote {rel}")
        return 0

    if action == "verify":
        findings = integrity.scan_for_kill_switches(repo_root)
        ok, mismatched = integrity.verify_integrity(repo_root)
        algorithm = _manifest_algorithm(integrity, repo_root)
        print(json.dumps({
            "algorithm": algorithm,
            "integrity_ok": ok,
            "mismatched": mismatched,
            "kill_switches": findings,
        }, indent=2, sort_keys=True))
        if ok and algorithm is not None and algorithm != integrity.MANIFEST_HASH_ALGORITHM:
            # A legacy raw-bytes manifest verifies clean on the tree it was written
            # over and reports every managed file changed on the next checkout git
            # re-ends (DEF-725). Say once that one refresh ends that -- the one
            # sentence the operator burned by that remedy needs.
            py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
            print(
                f"This manifest predates the line-ending canon (algorithm {algorithm!r}, "
                "raw bytes). Refresh it once, in your own terminal:\n"
                + _maintenance_mode_invocation(
                    f'{py} -m espalier integrity refresh "{args.repo}"')
                + f"\nto adopt {integrity.MANIFEST_HASH_ALGORITHM!r}; after that a checkout "
                "git re-ends to CRLF no longer reports drift.",
                file=sys.stderr,
            )
        # Actionable next step on stderr — operator sees the
        # remediation command without grepping docs.
        if findings:
            print(
                f"{plural(len(findings), 'kill-switch setting')} detected in active settings: "
                f"{findings}. Remove them before continuing.",
                file=sys.stderr,
            )
            return 2
        if not ok:
            py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
            if integrity.is_protocol_mismatch(mismatched):
                # Not drift: a manifest this verifier cannot read. The deployed
                # hooks under tools/cc/hooks/ are the readers a session uses, and
                # the writer is the engine's own copy, so redeploy the hooks; a
                # refresh would rewrite the same manifest (DEF-725).
                print(
                    "The integrity manifest was written by a newer espalier than the "
                    f"deployed hooks under tools/cc/hooks/ ({mismatched[0]}). Redeploy "
                    "the hooks by running, in your own terminal:\n"
                    + _maintenance_mode_invocation(
                        f'{py} -m espalier upgrade --execute "{args.repo}"')
                    + "\nA refresh would rewrite the same manifest.",
                    file=sys.stderr,
                )
                return 1
            # An ABSENT manifest is not edit-drift — verify_integrity returns the
            # MANIFEST_ABSENT sentinel. Frame it as "create one", not "revert
            # your edits", so a never-initialized repo gets the right next step.
            # A present-but-unusable manifest returns MANIFEST_UNREADABLE and
            # deliberately does NOT take this branch: "create one" would be the
            # wrong instruction for a manifest that already exists.
            if mismatched == [integrity.MANIFEST_ABSENT]:
                # Parity with `audit` and `doctor`: a fresh source checkout or a
                # never-initialized repo has no manifest BY CONSTRUCTION, and both
                # of those commands return 0 with first-run guidance rather than a
                # red exit. `.espalier/integrity.json` is gitignored and per-install,
                # so this is the ordinary state of a repo someone cloned but has not
                # run `init` on yet — a second developer on a governed repo, or a
                # contributor following CONTRIBUTING.md, which never runs `init`.
                # Exiting 1 there reports "tamper detection is broken" about a repo
                # that simply has not been set up, and it does so in a command the
                # pre-PR gate now calls. The hook side already agrees: SessionStart
                # exempts MANIFEST_ABSENT from its drift warning for this reason.
                #
                # Scoped deliberately to the uninitialized modes: an INITIALIZED repo
                # whose manifest has gone missing is genuinely anomalous and still
                # exits 1, because there the absence means something was removed.
                from espalier.repo_mode import (
                    REPO_MODE_SOURCE_CHECKOUT,
                    REPO_MODE_UNINITIALIZED,
                    detect_repo_mode,
                )
                try:
                    mode = detect_repo_mode(repo_root)
                except OSError:
                    mode = None  # unreadable tree — fall through to the red exit
                if mode in (REPO_MODE_SOURCE_CHECKOUT, REPO_MODE_UNINITIALIZED):
                    print(
                        f"{repo_root.name}: source checkout / not initialized -- no "
                        f"integrity manifest yet. Run `{py} -m espalier init .` first; "
                        "integrity verifies the deployed manifest.",
                    )
                    return 0
                print(
                    "No integrity manifest found (.espalier/integrity.json). "
                    "Create one by running, in your own terminal:\n"
                    + _maintenance_mode_invocation(
                        f'{py} -m espalier integrity refresh "{args.repo}"'),
                    file=sys.stderr,
                )
                return 1
            if mismatched == [integrity.MANIFEST_UNREADABLE]:
                # Same reasoning as doctor's branch: nothing was COMPARED, so
                # "revert the unintended edits" names an edit that never
                # happened. Rebuilding is the only action that helps.
                print(
                    "Integrity manifest present but unreadable "
                    "(.espalier/integrity.json) -- tamper detection is not "
                    "running. Inspect it, then rebuild by running, in your own "
                    "terminal:\n"
                    + _maintenance_mode_invocation(
                        f'{py} -m espalier integrity refresh "{args.repo}"'),
                    file=sys.stderr,
                )
                return 1
            print(
                f"Integrity drift in {plural(len(mismatched), 'file')}. Either revert "
                f"the unintended edits or refresh the manifest by running, in "
                f"your own terminal:\n"
                + _maintenance_mode_invocation(
                    f'{py} -m espalier integrity refresh "{args.repo}"'),
                file=sys.stderr,
            )
            return 1
        return 0

    # Reachable via a DIRECT cmd_integrity(...) call (argparse pins
    # choices=["verify","refresh"] only on the CLI path); pinned by
    # tests/test_cli.py::TestCmdIntegrityUnknownAction. Keep the defensive
    # fallback — the branch is not dead.
    print(f"Unknown integrity action: {action}", file=sys.stderr)
    return 1


INSTALL_CI_INSTRUCTIONS = """\
Harness Guard installed. To enable enforcement:

  1. In your repository on GitHub, open Settings -> Branches
  2. Add a branch protection rule for your DEFAULT BRANCH -- whatever it is
     named. Check Settings -> General if you are unsure; a rule whose pattern
     matches no branch is accepted by GitHub and protects nothing.
  3. Require status check 'verify' to pass before merging
     ('verify' is the JOB name -- 'Harness Guard' is the workflow and is
      not selectable as a required check)
  4. Require pull request reviews before merging (recommended)

Until branch protection is enabled, the workflow runs but cannot block merges.
"""


def _same_ignoring_eol(dst: Path, src: Path) -> bool:
    """Compare two files ignoring line endings.

    A raw ``read_bytes()`` compare reports an IDENTICAL file as different on a
    Windows adopter whose committed YAML came back from git as CRLF. The cost
    was not cosmetic: ``install-ci`` printed "exists and differs from
    espalier's", littered ``harness-guard.yml.new``, and set
    ``report['ci_gate_active'] = False`` -- so the adopter's PR merge-gate was
    reported parked over a line-ending difference alone.

    Our ``.gitattributes`` pins ``eol=lf`` for ``*.py`` and ``*.md`` but NOT
    ``*.yml``, and an adopter's repo does not inherit our ``.gitattributes``
    at all, so normalizing HERE is the load-bearing fix rather than a
    ``.gitattributes`` pin. The rule is the integrity manifest's own canon,
    ``_integrity.canonical_text_bytes`` (DEF-725: the manifest hashes the same
    form, so a CRLF checkout is not drift there either), read through the
    integrity bridge so it has ONE owner (the bridge backfills the name on a
    pre-DEF-725 hook module, the bisect skew both reviews drove);
    ``tests/test_package_resource_parity.py``'s ``_normalize`` carries the EOL
    arm of the same rule, including bare CR, without the BOM strip.

    A leading UTF-8 BOM is stripped for the same reason. Normalizing EOLs but
    not the BOM would have left half the class open: this project already
    treats a BOM as a first-class Windows hazard in three other scanners, and
    Notepad or a PowerShell ``Out-File`` round-trip adds one — reproducing the
    exact symptom (".new" littered, merge-gate reported inactive) that the EOL
    half was fixed to stop.
    """
    canon = load_integrity_module().canonical_text_bytes
    return canon(dst.read_bytes()) == canon(src.read_bytes())


def cmd_install_ci(args: argparse.Namespace, *, report: dict | None = None) -> int:
    """Write the harness-guard workflow and ci_guard.py into a target repo.

    The workflow ships as a package resource under
    ``espalier/assets/github/workflows/`` so wheel installs can install it
    into a fresh target repo. ``ci_guard.py`` ships as package-data under the
    vendored ``espalier/_vendor/cc/`` tree and is located via
    ``_deploy_source_path()``.

    When ``report`` is supplied, ``report['ci_gate_active']`` is set
    to ``True`` when espalier's ``harness-guard.yml`` becomes (or already is) the
    active workflow, and ``False`` when a host's *differing* workflow is kept and
    espalier's gate is parked in ``harness-guard.yml.new`` (the gate is NOT live).
    Both paths return ``0``, so a caller that prints "CI gate installed" MUST read
    this flag instead of the rc — otherwise it claims a merge-gate that isn't
    active. ``report`` is ``None`` for the plain CLI (``espalier install-ci``),
    which has no banner to gate.
    """
    # A nonexistent target would otherwise be scaffolded by the mkdir(parents=True)
    # calls below (a phantom tools/cc + .github tree) and exit 0 — fail cleanly first.
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2

    workflow_dst = repo_root / ".github" / "workflows" / "harness-guard.yml"
    guard_src = _deploy_source_path("tools/cc/ci_guard.py")
    guard_dst = repo_root / "tools" / "cc" / "ci_guard.py"

    try:
        workflow_node = github_workflow_asset("harness-guard.yml")
    except AssetNotFound as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not guard_src.exists():
        print(f"Error: source ci_guard.py missing at {guard_src}", file=sys.stderr)
        return 1

    # Every path emitted below goes out as POSIX. `Path.relative_to` returns a
    # Path, and `str()`/f-string interpolation of one yields BACKSLASHES on
    # Windows -- so an adopter running `install-ci` there read
    # `.github\\workflows\\harness-guard.yml` against docs that spell it with
    # forward slashes, and the sibling emitters (reflection.py, managed_paths,
    # the scanners) all normalise while these did not. Architecture rule:
    # path comparisons and path OUTPUT use forward slashes.
    wrote: list[str] = []
    with as_file(workflow_node) as workflow_src:
        # ci_guard.py is espalier's own file — always (over)write it.
        guard_dst.parent.mkdir(parents=True, exist_ok=True)
        if guard_dst.exists() and _same_ignoring_eol(guard_dst, guard_src):
            print(f"  unchanged: {guard_dst.relative_to(repo_root).as_posix()}")
        else:
            atomic_write_bytes(guard_dst, Path(guard_src).read_bytes())
            wrote.append(guard_dst.relative_to(repo_root).as_posix())

        # harness-guard.yml may be HOST-authored: a fusion copies the host tree
        # first, and plan_fusion's collision check never sees this file (it is not
        # in the fusion manifest — install-ci writes it). Never clobber a DIFFERENT
        # existing workflow; write `.new` + WARN, mirroring init's settings.json.new
        # so the operator reviews and merges.
        workflow_dst.parent.mkdir(parents=True, exist_ok=True)
        if not workflow_dst.exists():
            atomic_write_bytes(workflow_dst, Path(workflow_src).read_bytes())  # bom-exempt: a verbatim byte copy of the packaged workflow, never decoded here
            wrote.append(workflow_dst.relative_to(repo_root).as_posix())
            if report is not None:
                report["ci_gate_active"] = True
        elif _same_ignoring_eol(workflow_dst, workflow_src):
            print(f"  unchanged: {workflow_dst.relative_to(repo_root).as_posix()}")
            if report is not None:
                report["ci_gate_active"] = True
        else:
            # The host already ships a DIFFERING harness-guard.yml. We
            # never clobber it (sovereignty), so espalier's gate is parked in
            # `.new` and the HOST's (gate-less) workflow stays the active one.
            # This path still returns 0, so the caller MUST consult
            # report['ci_gate_active'] before claiming a live PR merge-gate.
            new_dst = workflow_dst.with_name(workflow_dst.name + ".new")
            atomic_write_bytes(new_dst, Path(workflow_src).read_bytes())
            wrote.append(new_dst.relative_to(repo_root).as_posix())
            if report is not None:
                report["ci_gate_active"] = False
            print(f"  WARN: {workflow_dst.relative_to(repo_root).as_posix()} exists and differs "
                  f"from espalier's; wrote {new_dst.relative_to(repo_root).as_posix()} instead -- "
                  f"review and merge (your workflow was left untouched). Espalier's "
                  f"PR merge-gate is NOT active until you merge it.",
                  file=sys.stderr)
            # A gate input the freshly written ci_guard.py needs and the parked
            # workflow does not forward fails EVERY protected pull request
            # closed, with a red that names this command as the remedy -- and
            # this command just parked the fix. Name the key and the line.
            try:
                asset_text = Path(workflow_src).read_text(encoding="utf-8", errors="replace")
                host_text = workflow_dst.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                asset_text = host_text = ""
            if "PR_HEAD_SHA:" in asset_text and "PR_HEAD_SHA:" not in host_text:
                print("  WARN: your workflow does not forward PR_HEAD_SHA, which the "
                      "installed tools/cc/ci_guard.py requires on every pull request "
                      "touching a protected path (the gate fails closed without it). "
                      "Merge the .new, or add to the env block of the 'Check protected "
                      "paths' step: PR_HEAD_SHA: ${{ github.event.pull_request.head.sha "
                      "|| github.event.merge_group.head_sha }}",
                      file=sys.stderr)

    if wrote:
        print("Wrote:")
        for rel in wrote:
            print(f"  {rel}")
    # init seeds .espalier/integrity.json BEFORE ci_guard.py and
    # harness-guard.yml exist, so the init→install-ci flow leaves both files
    # absent from the manifest (tampering goes undetected). Re-seed now that
    # they're deployed — but ONLY if the manifest already exists, so a repo
    # that opted out of integrity tracking stays opt-out.
    integrity_manifest = repo_root / ".espalier" / "integrity.json"
    if integrity_manifest.exists():
        integrity = load_integrity_module()
        try:
            integrity.write_manifest(repo_root)
        except (FileNotFoundError, OSError) as exc:
            # Best-effort reseed. A failure here must NOT turn a SUCCESSFUL
            # install-ci into a false "CI not installed" rc=1 — the gate files
            # (ci_guard.py + harness-guard.yml) are already deployed; only the
            # manifest coverage is best-effort. Unwrapped, an OSError here would
            # set ci_gate_active=False at the load-bearing PR-guarantee step on
            # a successful install. Mirror the non-fatal guard cmd_init /
            # cmd_upgrade use.
            print(f"[info] WARN: could not re-seed integrity manifest: {os_error_text(exc)}",
                  file=sys.stderr)
        else:
            # Don't claim "newly deployed" — this runs on every install-ci,
            # including an idempotent re-run where both files were already
            # present (printed "unchanged:" above). The re-seed covers them
            # either way.
            print(
                "[info] re-seeded .espalier/integrity.json to cover "
                "ci_guard.py + harness-guard.yml"
            )
    # The workflow just written flips `detect_ci`'s raw `.github/workflows`
    # probe, so the baseline `init` saved (`ci_providers: []`) now disagrees
    # with a fresh inference and the adopter's next documented step, `doctor .`,
    # warns "saved reports differ from fresh inference" and tells them to
    # re-baseline what install-ci itself changed (DEF-688; driven 2026-09-05,
    # the ONLY changed key was ci_providers). The fact is TRUE -- the repo now
    # has GitHub Actions -- so the fix is to re-baseline here, not to blind the
    # detector. Existence-guarded like the manifest re-seed above: a repo that
    # never ran `init` gets no reports from install-ci.
    fp_path = repo_root / "reports" / "repo_fingerprint.json"
    if fp_path.exists():
        try:
            config = _load_config(repo_root, args)
            fp = fingerprint_repo(repo_root, config)
            atomic_write_text(fp_path, json.dumps(fp.to_dict(), indent=2, sort_keys=True) + "\n")
            refreshed, refresh_failures = _refresh_fingerprint_derivatives(repo_root, fp, config)
        except Exception as exc:  # noqa: BLE001 -- best-effort; the gate files are already deployed
            print(
                f"[info] WARN: could not re-baseline reports/repo_fingerprint.json: {os_error_text(exc)}",
                file=sys.stderr,
            )
        else:
            print(
                "[info] re-baselined reports/repo_fingerprint.json "
                "(ci_providers now records the workflow just installed)"
                + (f"; refreshed {', '.join(refreshed)}" if refreshed else "")
            )
            if refresh_failures:
                print(
                    f"[info] WARN: fingerprint re-baselined but "
                    f"{plural(len(refresh_failures), 'downstream artifact')} failed: "
                    f"{refresh_failures}",
                    file=sys.stderr,
                )
    print()
    print(INSTALL_CI_INSTRUCTIONS)
    return 0


def cmd_audit_accuracy(args: argparse.Namespace) -> int:
    """Accuracy audit: verify documented claims against evidence."""
    repo_arg = getattr(args, "repo", ".")
    if _resolve_repo_arg(repo_arg) is None:
        return 2
    from espalier.audit_accuracy import cli_main
    return cli_main(args)


def cmd_refresh_externals(args: argparse.Namespace) -> int:
    """Refresh `docs/external/` pins against their canonical URLs."""
    if _resolve_repo_arg(args.repo) is None:
        return 2
    from espalier.refresh_externals import cli_main
    return cli_main(args)


#: Every file carrying a literal copy of the write_guard prefix SHA. Three,
#: not one: `tools/cc/` may not import espalier, so the hook-side detector and
#: the standalone `ci_guard.py` each inline their own copy of the value the
#: engine holds. They are a lockstep set -- a stale member does not fail
#: loudly, it silently answers "not self-host" on this repo.
#:
#: Named here, and DERIVED from the tree by
#: `tests/test_self_host_fingerprint_parity.py::test_every_pin_carrier_is_refreshed`,
#: so a fourth copy cannot be added without the refresh verb learning about it.
#: The pin's home. Named on its own so the verb below can stand down on its
#: absence by NAME: keyed on the tuple's first slot, a reorder would silently
#: move the stand-down onto a carrier adopters do have (review, 2026-09-23).
SELF_HOST_PIN_SOURCE = "espalier/_self_host_fingerprint.py"
SELF_HOST_PIN_CARRIERS: tuple[str, ...] = (
    SELF_HOST_PIN_SOURCE,
    "tools/cc/hooks/_self_host_fingerprint.py",
    "tools/cc/ci_guard.py",
)

#: Matches both spellings in use: a plain `NAME = "<hash>"` and the
#: parenthesized `NAME = (\n    "<hash>"\n)` that black produces for the
#: longer `_CI_`-prefixed name. Groups 1 and 2 bracket the hash so a
#: substitution preserves whichever form the file already uses.
SELF_HOST_PIN_ASSIGNMENT_RE = re.compile(
    r'(WRITE_GUARD_PREFIX_SHA256\s*=\s*\(?\s*")[0-9a-f]*(")'
)


def cmd_refresh_self_host_pin(args: argparse.Namespace) -> int:
    """Refresh the write_guard.py content pin (harness-dev only).

    Reads the first 200 bytes of ``tools/cc/hooks/write_guard.py``,
    computes SHA-256, and rewrites the constant in EVERY pin carrier
    (``SELF_HOST_PIN_CARRIERS``). Run this after any legitimate edit to
    ``write_guard.py``.

    Every carrier, not one: neither the hook tree nor ``ci_guard.py`` may
    import espalier, so each keeps its own copy of the hash and all of them
    must move in lockstep. This verb previously rewrote only the library
    copy, which left the suite RED and sent the operator hand-editing
    mirrors -- measured twice in one session, on the very edit that added
    the DO-NOT-REFLOW warning to ``write_guard.py`` naming this command as
    the remedy. A refresh verb that does part of its job is worse than none,
    because the warning promises it is sufficient. The first repair of that
    defect then missed ``ci_guard.py``, which is why the carrier set is now
    a named constant with a derived-population test rather than a list
    inlined here.
    """
    import hashlib
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    if not (repo_root / SELF_HOST_PIN_SOURCE).is_file():
        # An adopter tree has no pin to refresh (it has no `espalier/` at all).
        # Before this branch an adopter who typed the hidden verb read
        # `error: <tree>/espalier/_self_host_fingerprint.py not found` -- an
        # internal path they cannot act on -- while the three sibling
        # self-host verbs name the reason; this refuses like `release-pack`
        # (exit 2, stderr). Deliberately NOT `_off_self_host`: that predicate's
        # fifth signal is the write_guard content pin -- the thing this verb
        # refreshes -- so gating on it would refuse the remedy on the source
        # tree exactly when the pin is stale (a gate written and then refuted
        # on 2026-09-23; `tests/test_adopter_verb_stand_down.py` pins the rule).
        print(
            f"error: _refresh-self-host-pin {_SELF_HOST_SCOPE_CLAUSE}; there is "
            "no write_guard content pin to refresh on an adopter repo.",
            file=sys.stderr,
        )
        return 2
    write_guard = repo_root / "tools" / "cc" / "hooks" / "write_guard.py"
    pin_files = [repo_root / rel for rel in SELF_HOST_PIN_CARRIERS]
    if not write_guard.is_file():
        print(f"error: {write_guard} not found", file=sys.stderr)
        return 2
    for pin_file in pin_files:
        if not pin_file.is_file():
            print(f"error: {pin_file} not found", file=sys.stderr)
            return 2
    prefix = write_guard.read_bytes()[:200]
    new_hash = hashlib.sha256(prefix).hexdigest()
    # Rewrite every carrier before writing ANY of them: a partial refresh is
    # the exact state this verb exists to prevent, so a constant that cannot
    # be located in one carrier aborts the whole run rather than leaving the
    # tree half-updated.
    rewritten: list[tuple[Path, str]] = []
    for pin_file in pin_files:
        text = pin_file.read_text(encoding="utf-8")
        updated, n = SELF_HOST_PIN_ASSIGNMENT_RE.subn(
            lambda m: f"{m.group(1)}{new_hash}{m.group(2)}", text, count=1
        )
        if n != 1:
            print(
                f"error: failed to locate WRITE_GUARD_PREFIX_SHA256 in {pin_file}",
                file=sys.stderr,
            )
            return 2
        rewritten.append((pin_file, updated))
    for pin_file, updated in rewritten:
        atomic_write_text(pin_file, updated)
    print(f"refreshed: WRITE_GUARD_PREFIX_SHA256 = {new_hash}")
    for pin_file in pin_files:
        print(f"  {pin_file.relative_to(repo_root).as_posix()}")
    print(
        f"Run `{_remedy_py()} scripts/sync_vendor_cc.py` to carry "
        "the tools/cc changes into espalier/_vendor/cc/."
    )
    return 0


def _renamed_names_a_file(manifest: "PackManifest") -> bool:
    """True if the pack declares a RENAMED symbol whose token looks like a
    file/path — a rename keyed on a literal the symbol-walk under-measures.

    The recognizer is surface-impact's, so 0-B and 0-D read the same
    ``### Renamed`` entry the same way: a ``.``-or-``/`` test read
    ``Klass.DEFAULT`` as a file and ``Makefile`` as a symbol, the opposite of
    the pre-flight that reports the rename as a path removal (DEF-410j)."""
    from espalier.pack_manifest import RENAMED
    from espalier.surface_impact import _looks_like_path
    return any(
        s.change_type == RENAMED and _looks_like_path(s.name)
        for s in manifest.affected_symbols
    )


def _file_matches_globs(rfile: str, globs: "Iterable[str]") -> bool:
    """True if ``rfile`` matches any EXCLUDE glob. Supports fnmatch globs
    (``docs/*.md``, ``CLAUDE.md``) and a bare directory prefix (``examples/``
    matches everything under it). Paths are normalized to ``/`` first so a
    Windows-shaped ref still matches."""
    import fnmatch
    rfile = rfile.replace("\\", "/")
    for g in globs:
        g = g.replace("\\", "/").strip()
        if not g:
            continue
        if fnmatch.fnmatch(rfile, g):
            return True
        # Directory-prefix convenience: `examples/` (or `examples`) excludes
        # every file under it.
        if fnmatch.fnmatch(rfile, g.rstrip("/") + "/*"):
            return True
    return False


def _looks_literal_keyed(pack_path: Path, manifest: "PackManifest") -> bool:
    """A pack is 'literal/path-keyed' when its blast radius is a raw string a
    symbol-walk cannot see: a ``git mv`` in the pack body, or a renamed-file
    token in ``## Affected symbols``. Such a pack has a thin symbol surface, so
    a clean symbol scan is NOT coverage — scope-check warns rather than let a
    '0 gaps' result read as reassurance."""
    body = pack_path.read_text(encoding="utf-8", errors="replace")
    return (
        re.search(r"\bgit mv\b", body) is not None
        or _renamed_names_a_file(manifest)
    )


#: Printed once, on its own line, by ``cmd_scope_check`` when a DECLARED
#: ``## Affected symbols`` / ``## Affected literals`` section parsed to zero
#: entries (DEF-781). ``scripts/run_pack_chain.sh`` greps the line-anchored
#: prefix BEFORE the two clean-skip phrases, so the pack's declared blast
#: radius reads as an errored probe rather than a pack with nothing to walk;
#: ``tests/test_run_pack_chain.py`` lifts the driver's pattern and runs the
#: real CLI, so the two literals cannot drift apart.
_SCOPE_DECLARED_BUT_EMPTY = (
    "scope-check: DECLARED_BUT_EMPTY -- a declared section parsed to zero entries,"
    " so the blast radius it declares was never walked (an errored probe, not a skip)."
)


def cmd_scope_check(args: argparse.Namespace) -> int:
    """Pack scope pre-flight.

    Exit codes:
        0  pack has no scope gap (or operator accepted with reason).
        1  pack file missing / not a file, or nothing parsed: neither an
           Affected symbols nor an Affected literals section is declared, or
           a declared one parsed to zero entries (the cause is printed).
        2  scope gap detected (no --accept-scope-gap given), or --repo is not an
           existing directory (the shared repo-arg precondition guard).
    """
    from espalier.pack_manifest import parse_pack
    from espalier.scope_walker import classify_references, walk_references_multi
    from espalier.surface_matrix import load_matrix

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    pack_path = Path(args.pack_path).resolve()
    if not pack_path.exists():
        print(f"FAIL: pack file not found: {pack_path}")
        return 1
    # `.` / a directory arg passes exists() but parse_pack would read it and leak
    # a raw `[Errno 21] Is a directory`; give the same wrapped FAIL verify-landing does.
    if not pack_path.is_file():
        print(f"FAIL: pack path is not a file (is it a directory?): {pack_path}")
        return 1

    manifest = parse_pack(pack_path)
    # Read ONCE and reuse. parse_pack() already read this file with identical
    # args, and two more reads followed below (the diagnostics feed and the
    # declares-but-empty probe) — three reads of one small markdown file, with
    # inconsistent error handling between them: one was wrapped against a
    # mid-run delete, the other was not. One read, one handler, one behaviour.
    try:
        pack_text = pack_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pack_text = ""  # unreadable → diagnostics stay quiet, bail branch decides
    matrix = load_matrix(repo_root / args.matrix)

    print(f"\n{manifest.pack_id} scope pre-flight")
    print("=" * 40)
    print(f"Pack: {pack_path.relative_to(repo_root) if pack_path.is_relative_to(repo_root) else pack_path}")
    print(f"Scope (in) declares {len(manifest.scope_in_files)} files.")
    # Name the heading the parser matched: the numbered and h3 spellings parse,
    # so the line the reader is told about is the line in their pack; the plain
    # heading keeps the historical sentence byte for byte.
    _heading = manifest.affected_symbols_heading
    if _heading is None:
        print("Affected symbols section: absent (no heading matched).")
    elif _heading == "## Affected symbols":
        print(f"Affected symbols section declares {len(manifest.affected_symbols)} symbols.")
    else:
        print(
            f"Affected symbols section (matched '{_heading}') declares "
            f"{len(manifest.affected_symbols)} symbols."
        )
    # That count is the only thing the parser can report, and it cannot say what
    # it dropped. A bullet declaring several path/symbol tokens contributes only
    # its FIRST, so a partially-collapsed section yields a plausible NON-ZERO
    # number and trips nothing — a wrong number is worse than a missing one.
    for _note in _pack_manifest.affected_symbols_diagnostics(pack_text):
        print(f"  ! {_note}")
    # A strike that registered is said so, not inferred from a count.
    for _tok in _pack_manifest.affected_symbols_withdrawn(pack_text):
        print(f"  ~ withdrawn by strike: {_tok}")
    print()

    # A literal/path-keyed pack (a pure rename) can have a thin or empty SYMBOL
    # surface yet a rich LITERAL surface — exactly what the literal arm exists
    # for — so only bail when the pack declares NEITHER section. A pack with
    # genuinely nothing to walk keeps the "no 'Affected symbols' section" /
    # "cannot walk references" phrases the chain driver's rc==1 grep and the
    # suite both key on; a pack that DECLARED a section which parsed to zero
    # carries the _SCOPE_DECLARED_BUT_EMPTY line as well (printed once, below).
    if not manifest.affected_symbols and not manifest.affected_literals:
        # Distinguish "the heading is absent" from "the heading is present but
        # parsed to zero entries". The second sent an author who FOLLOWED the
        # format to PACK_AUTHORING.md for a format they already followed, and
        # it burned a real pack-author cycle.
        #
        # run_pack_chain.sh reads rc==1 in a fixed order: the line-anchored
        # _SCOPE_DECLARED_BUT_EMPTY marker first (an errored probe: the declared
        # blast radius was never walked -- DEF-781), then `no 'Affected symbols'
        # section|cannot walk references` LINE BY LINE (a clean skip), else an
        # errored probe. So each phrase must sit CONTIGUOUSLY on one printed
        # line, and the literals-only message below may keep the no-section
        # phrase (it is true) only because the marker is read first. Do not
        # reflow these.
        #
        # Five causes, each named (DEF-430, DEF-431): every bullet declares
        # nothing on purpose (nothing to walk, checked FIRST so a none
        # declaration under an unrouted sub-heading is still the author's
        # escape); every sub-heading in the symbols section is one the
        # pre-flight does not route (the bullets under `### Fixed` are correct
        # and the format message was a lie); the section has routed
        # sub-headings, or none at all, and no bullet parsed (the `!` lines
        # above name each dropped bullet); only a literals section exists and
        # it parsed to zero; neither section exists. The summary line above
        # already says which heading matched.
        symbols_present = manifest.affected_symbols_heading is not None
        literals_present = _AFFECTED_LITERALS_HEADING_RE.search(pack_text) is not None
        subsections = (
            _pack_manifest.affected_symbols_subsections(pack_text)
            if symbols_present else []
        )
        unrouted = [h for h, routed in subsections if not routed]
        declares_nothing = (
            symbols_present and _pack_manifest.affected_symbols_all_declare_nothing(pack_text)
        )
        if declares_nothing:
            print(f"This pack's '{manifest.affected_symbols_heading}' section parsed to zero entries")
            print("because every bullet in it declares nothing on purpose (a none spelling or a")
            print("parenthesised aside), so there is nothing to walk. scope-check cannot walk references")
            print("it was not given. (Reported the same way as: no 'Affected symbols' section.)")
        elif symbols_present and subsections and len(unrouted) == len(subsections):
            named = ", ".join(f"'### {h}'" for h in unrouted)
            print(f"This pack's '{manifest.affected_symbols_heading}' section parsed to zero entries")
            print(f"because every sub-heading in it ({named}) is one the pre-flight does not")
            print("route. scope-check cannot walk references until a bullet sits under one of")
            print("`### Added`, `### Changed`, `### Renamed` or `### Removed` (the four the")
            print("walk reads), or a bullet declares nothing on purpose (a none spelling).")
            print("See docs/PACK_AUTHORING.md for the format.")
        elif symbols_present:
            matched = (
                "" if manifest.affected_symbols_heading == "## Affected symbols"
                else f" (matched '{manifest.affected_symbols_heading}')"
            )
            print(f"This pack declares an 'Affected symbols' section{matched}, but it parsed to zero")
            print("entries: scope-check cannot walk references until the bullets match")
            print("`path::symbol` under a `### Added`, `### Changed`, `### Renamed` or")
            print("`### Removed` sub-heading.")
            print("See docs/PACK_AUTHORING.md for the format.")
        elif literals_present:
            print("This pack has no 'Affected symbols' section; its 'Affected literals' section")
            print("parsed to zero entries: scope-check cannot walk references until a literal")
            print("bullet reads `- `token` -- description` (see docs/PACK_AUTHORING.md,")
            print("the Affected literals section).")
        else:
            print("This pack has no 'Affected symbols' section and no 'Affected")
            print("literals' section. scope-check cannot walk references until one")
            print("is added. See docs/PACK_AUTHORING.md for the format.")
        if symbols_present and literals_present:
            # Both sections declared, both empty: say so, or the author fixes
            # the symbols cause, reruns, and meets the literals one cold.
            print("Its 'Affected literals' section parsed to zero entries as well: a literal")
            print("bullet reads `- `token` -- description` (docs/PACK_AUTHORING.md).")
        # The marker is computed from the two facts, never typed per branch: a
        # declared symbols section that did not declare nothing on purpose, or
        # a declared literals section (it parsed to zero, or we would not be
        # here) -- so a malformed literals section beside a none-declaring
        # symbols section is still the errored probe DEF-781 names.
        if (symbols_present and not declares_nothing) or literals_present:
            print(_SCOPE_DECLARED_BUT_EMPTY)
        return 1

    use_rg = not args.no_ripgrep
    out_of_scope_by_file: dict[str, list[dict]] = {}
    in_scope_by_file: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}

    # One batched tree pass for ALL symbols (reads the tree once, not once per
    # symbol — the O(symbols x files) -> O(files) fix); the per-symbol
    # classification loop below is unchanged.
    all_refs = walk_references_multi(
        repo_root, [s.name for s in manifest.affected_symbols], use_ripgrep=use_rg
    )
    for symbol in manifest.affected_symbols:
        refs = all_refs.get(symbol.name, [])
        classified = classify_references(refs, scope_in=manifest.scope_in_files)
        symbol_counts[symbol.name] = len(refs)
        for ref in classified["in_scope"]:
            in_scope_by_file[ref["file"]] = in_scope_by_file.get(ref["file"], 0) + 1
        for ref in classified["out_of_scope"]:
            ref_with_symbol = dict(ref)
            ref_with_symbol["symbol"] = symbol.name
            out_of_scope_by_file.setdefault(ref["file"], []).append(ref_with_symbol)
        symbol.classification = matrix.classify(symbol.name)

    # --- Literal / token arm ---
    # A rename/config pack's blast radius is a raw string the symbol-walk cannot
    # see. Walk each declared literal tree-wide (the batched walker already
    # substring-matches a non-identifier token) and partition its hits with the
    # SAME in-scope logic the symbol arm uses (classify_references): target (in
    # Scope-in) / excluded (a declared homonym twin) / ambiguous (neither — an
    # unaccounted-for occurrence a blind sed would corrupt).
    literal_ambiguous_by_file: dict[str, list[dict]] = {}
    literal_excluded_by_token: dict[str, set[str]] = {}
    literal_summaries: list[tuple[str, int, int, int, int]] = []
    if manifest.affected_literals:
        lit_all = walk_references_multi(
            repo_root,
            [lit.token for lit in manifest.affected_literals],
            use_ripgrep=use_rg,
        )
        for lit in manifest.affected_literals:
            refs = lit_all.get(lit.token, [])
            classified = classify_references(refs, scope_in=manifest.scope_in_files)
            n_target = len(classified["in_scope"])
            n_excluded = 0
            n_ambiguous = 0
            for ref in classified["out_of_scope"]:
                if _file_matches_globs(ref["file"], lit.exclude_globs):
                    n_excluded += 1
                    literal_excluded_by_token.setdefault(lit.token, set()).add(ref["file"])
                else:
                    n_ambiguous += 1
                    ref_with_token = dict(ref)
                    ref_with_token["token"] = lit.token
                    literal_ambiguous_by_file.setdefault(ref["file"], []).append(
                        ref_with_token
                    )
            literal_summaries.append(
                (lit.token, len(refs), n_target, n_excluded, n_ambiguous)
            )

    if manifest.affected_symbols:
        print("Symbol reference scan:")
        for symbol in manifest.affected_symbols:
            count = symbol_counts[symbol.name]
            marker = ""
            if symbol.classification == "guarded":
                marker = "  [HIGH-RISK]"
            elif symbol.classification == "supported":
                marker = "  [MEDIUM-RISK]"
            elif symbol.classification:
                marker = f"  [{symbol.classification}]"
            print(f"  {symbol.name:<40} -> {count} references{marker}")
        print()

    if in_scope_by_file:
        print("Files in pack Scope (in):")
        for path in sorted(in_scope_by_file):
            print(f"  {path:<48} [ok] {in_scope_by_file[path]} refs")
        print()

    # Blind-spot warning: a literal/path-keyed pack (a rename, a constant/config
    # change) has a thin symbol surface, so the symbol scan above under-measures
    # its blast radius. Warn on BOTH the gap and the no-gap path so a clean
    # symbol scan never reads as coverage. Declaring literals (below) silences it.
    if _looks_literal_keyed(pack_path, manifest) and not manifest.affected_literals:
        print("[warn] This pack looks literal/path-keyed (a rename / config /")
        print("       constant change). scope-check walks SYMBOLS and under-")
        print("       measures literal blast radius. Declare the literal(s) under")
        print("       '## Affected literals', or grep them: git grep '<literal>'.")
        print()

    cap = max(1, args.max_refs_per_file)

    if out_of_scope_by_file:
        print("Files NOT in pack scope (gap):")
        for path in sorted(out_of_scope_by_file):
            refs = out_of_scope_by_file[path]
            print(f"  {path:<48} [!] {len(refs)} refs")
            for ref in refs[:cap]:
                ctx = ref["context"][:120]
                print(f"     L{ref['line']}: {ctx}")
            if len(refs) > cap:
                print(f"     ... and {len(refs) - cap} more")
        print()

    if literal_summaries:
        print("Literal reference scan:")
        for tok, total, n_target, n_excluded, n_ambiguous in literal_summaries:
            print(
                f"  {tok:<40} -> {total} refs  "
                f"({n_target} target / {n_excluded} excluded / {n_ambiguous} ambiguous)"
            )
            # Name WHICH files an EXCLUDE: glob swallowed (capped) so an
            # over-broad glob (fnmatch '*' crosses '/') is observable, not a
            # silent '0 ambiguous' that re-creates the false reassurance the
            # literal arm exists to kill.
            excluded_files = sorted(literal_excluded_by_token.get(tok, set()))
            if excluded_files:
                shown = ", ".join(excluded_files[:cap])
                more = (
                    f" ... (+{len(excluded_files) - cap} more)"
                    if len(excluded_files) > cap else ""
                )
                print(f"       excluded: {shown}{more}")
        print()

    if literal_ambiguous_by_file:
        # Distinct header from the symbol gap block so each arm is separately
        # fold-parseable; identical `  <path>  [!] N refs` line shape so a fold
        # parser reuses one regex.
        print("Literal refs NOT classified (gap):")
        for path in sorted(literal_ambiguous_by_file):
            refs = literal_ambiguous_by_file[path]
            print(f"  {path:<48} [!] {len(refs)} refs")
            for ref in refs[:cap]:
                ctx = ref["context"][:120]
                print(f"     L{ref['line']}: {ctx}")
            if len(refs) > cap:
                print(f"     ... and {len(refs) - cap} more")
        print()

    # A symbol gap OR an ambiguous literal hit is an unacknowledged scope gap.
    if out_of_scope_by_file or literal_ambiguous_by_file:
        if args.accept_scope_gap:
            print(f"Scope gap acknowledged: {args.accept_scope_gap!r}")
            return 0
        print("Recommendation:")
        print("  Either expand Scope (in) to cover the out-of-scope files,")
        print("  or proceed with test-driven discovery via:")
        print(f"    {_remedy_py()} -m espalier scope-check {pack_path} \\")
        print("        --accept-scope-gap '<reason>'")
        return 2

    print("[ok] No scope gaps detected.")
    return 0


def cmd_surface_impact(args: argparse.Namespace) -> int:
    """Shipped-surface obligation pre-flight (0-D).

    Reads a pack's declared ``### Added-paths`` and ``### Removed-paths`` (a
    path-shaped ``### Renamed`` entry is the removal of its old name; a new CLI
    subcommand registered inside an existing file is detected too), matches
    each to its surface, and prints the obligations the full suite will demand
    — so the executor can bundle the implied SoT edits into the plan up front.
    A removal names the same sites in reverse. Advisory, like scope-check.

    Exit codes:
        0  no public surface additions or removals (or operator accepted with
           reason).
        1  pack file missing / not a file.
        2  public surface addition(s) or removal(s) declared (no
           --accept-surface-gap given), or --repo is not an existing directory
           (the shared repo-arg guard).
    """
    from espalier.surface_impact import build_report, render_report

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    pack_path = Path(args.pack_path).resolve()
    if not pack_path.exists():
        print(f"FAIL: pack file not found: {pack_path}")
        return 1
    if not pack_path.is_file():
        print(f"FAIL: pack path is not a file (is it a directory?): {pack_path}")
        return 1

    report = build_report(repo_root, pack_path)
    pack_rel = (
        pack_path.relative_to(repo_root)
        if pack_path.is_relative_to(repo_root)
        else pack_path
    )
    # Display strings render forward slashes on every host (DEF-410k; the
    # `.replace("\\", "/")` contract governs comparisons, `as_posix` the shown
    # path): the last bare `relative_to` print in this module.
    print(render_report(report, pack_rel.as_posix()))

    if report.has_public_changes():
        if args.accept_surface_gap:
            print(f"Surface obligations acknowledged: {args.accept_surface_gap!r}")
            return 0
        print("Recommendation:")
        print("  Bundle the obligations above into the execution plan up front,")
        print("  or acknowledge them via:")
        print(f"    {_remedy_py()} -m espalier surface-impact {pack_path} \\")
        print("        --accept-surface-gap '<reason>'")
        return 2

    return 0


def cmd_verify_landing(args: argparse.Namespace) -> int:
    """Report whether a pack's claimed files have landed.

    Advisory: exits 0 (after a clean parse) with a LANDED/DRIFTED/OWED table;
    exits 1 when the pack file cannot be read (missing, or not valid UTF-8 — a
    clean message, never a traceback); exits 2 when ``--repo`` is not an
    existing directory (the shared repo-arg precondition guard).
    """
    from espalier.verify_landing import classify_landing, render_table

    repo = _resolve_repo_arg(args.repo)
    if repo is None:
        return 2
    pack_path = Path(args.pack_path).resolve()
    if not pack_path.exists():
        print(f"FAIL: pack file not found: {pack_path}")
        return 1
    try:
        pack_text = pack_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        print(f"FAIL: cannot read pack file {pack_path}: {os_error_text(exc)}")
        return 1

    entries = classify_landing(pack_text, repo)
    if args.json:
        print(
            json.dumps(
                [
                    {"path": e.path, "head_state": e.head_state, "status": e.status}
                    for e in entries
                ],
                indent=2,
            )
        )
    else:
        print(f"\n{pack_path.name} landing check")
        print("=" * 40)
        print(render_table(entries))
    return 0


def cmd_scaffolding_bench(args: argparse.Namespace) -> int:
    """Emit the scaffolding-quality canon report.

    Reads raw `cc/blueprints/*.json` directly; never routes through
    `/reflect`'s walker modules (see espalier/scaffolding_canon.py).
    """
    from dataclasses import asdict
    from datetime import datetime, timezone

    from espalier.scaffolding_canon import compute_canon

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    report = compute_canon(repo_root, last_n=args.last)
    payload = asdict(report)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    out_json = Path(args.out or (repo_root / "reports" / "scaffolding_canon.json"))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    wrote_current = _write_text_if_changed(out_json, rendered)

    # One snapshot per DISTINCT report, never one per run. A run that finds
    # nothing to report (no blueprints under cc/blueprints/) or the same
    # payload as the newest snapshot adds nothing an adopter can read later;
    # until 2026-09-12 every run left a new timestamped file behind regardless
    # (DEF-567). The current json/md are rewritten only when their bytes
    # change, for the same reason -- the printed line says which happened.
    history_dir = repo_root / "reports" / "scaffolding_canon"
    newest = _newest_snapshot(history_dir)
    if report.n_sessions == 0:
        # Four states read as zero sessions (no dir, an empty dir, only
        # latest.json, nothing that parses); "no readable blueprint" is true
        # of all four, "no blueprints" is not.
        history_note = "no snapshot: nothing to report, no readable blueprint under cc/blueprints/"
    elif newest is not None and _holds_text(newest, rendered):
        history_note = f"no snapshot: unchanged since {newest.name}"
    else:
        history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot = history_dir / f"{stamp}.json"
        # Two distinct reports inside one second: a suffix, not an overwrite
        # (`_` sorts after `.`, so the newest-by-name read stays right).
        n = 1
        while snapshot.exists():
            n += 1
            snapshot = history_dir / f"{stamp}_{n}.json"
        atomic_write_text(snapshot, rendered)
        history_note = f"snapshot {snapshot.name}"

    out_md = out_json.with_suffix(".md")
    lines = [
        "# Scaffolding-quality canon",
        "",
        f"- n_sessions: {report.n_sessions}",
        f"- Signal 1 — continuity (1-hop): "
        f"value={report.signal_1_continuity.value} "
        f"sample={report.signal_1_continuity.sample_size} "
        f"({report.signal_1_continuity.notes})",
        f"- Signal 2 — human reasoning density: "
        f"value={report.signal_2_human_density.value} "
        f"sample={report.signal_2_human_density.sample_size} "
        f"({report.signal_2_human_density.notes})",
        f"- Signal 3 — reflect coverage: "
        f"value={report.signal_3_reflect_coverage.value} "
        f"sample={report.signal_3_reflect_coverage.sample_size}",
        "",
        "See docs/CONVENTIONS.md 'scaffolding-quality canon' for the",
        "interpretation contract (curated-highlights caveat for Signal 1;",
        "[subagent: autorecord filter for Signal 2; coverage-only for",
        "Signal 3 to preserve de-circularization).",
    ]
    wrote_md = _write_text_if_changed(out_md, "\n".join(lines) + "\n")

    # Guard the relative_to so a --out path outside the repo (or an in-repo
    # path under an unresolved symlinked root) prints the absolute path instead
    # of crashing on ValueError. Same idiom as the integrity/ pack-path prints
    # above. The verb reads BOTH writes: the .md alone regenerated is a write.
    shown = out_json.relative_to(repo_root) if out_json.is_relative_to(repo_root) else out_json
    verb = "wrote" if (wrote_current or wrote_md) else "unchanged"
    print(f"[ok] {verb} {shown} (n_sessions={report.n_sessions}; {history_note})")
    return 0


def _holds_text(path: Path, text: str) -> bool:
    """True when ``path`` is a file holding exactly ``text`` (UTF-8 bytes)."""
    try:
        return path.is_file() and path.read_bytes() == text.encode("utf-8")
    except OSError:
        return False


def _write_text_if_changed(path: Path, text: str) -> bool:
    """Write ``text`` through the atomic writer unless ``path`` already holds
    those bytes; True when a write happened. A report the adopter re-runs
    with nothing new keeps its mtime and its bytes."""
    if _holds_text(path, text):
        return False
    atomic_write_text(path, text)
    return True


def _newest_snapshot(history_dir: Path) -> Path | None:
    """The newest ``<UTC stamp>.json`` directly under ``history_dir``, or
    None. The stamps are zero-padded UTC, so lexical order is chronological;
    a flat listing, not a walk."""
    if not history_dir.is_dir():
        return None
    snapshots = sorted(
        p for p in history_dir.iterdir() if p.suffix == ".json" and p.is_file()
    )
    return snapshots[-1] if snapshots else None


def cmd_pre_release(args: argparse.Namespace) -> int:
    # A nonexistent / non-dir path would otherwise reach run_pre_release_check
    # and surface a Python-internal PosixPath repr at exit 1. Fail with a clean
    # message + exit 2, matching the cmd_release_pack sibling.
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    if _off_self_host(repo_root):
        # Grades a tree against ESPALIER's release requirements (LICENSE,
        # CONTRIBUTING.md, SECURITY.md, scripts/release_check.py) — on an
        # adopter repo it reported their project "missing required file" for
        # files only Espalier's own PyPI release needs. `/preflight` already
        # guards this call; `/implement-pack` runs the identical command
        # unguarded, which is the sister-site this verb-level gate closes.
        # Still JSON on stdout: the output contract is a parseable report, and
        # a plain sentence here would break any consumer that reads one.
        print(json.dumps({
            "status": "skipped",
            "reason": (
                f"pre-release {_SELF_HOST_SCOPE_CLAUSE} -- skipping (adopter "
                f"repo). It validates Espalier's own release artifact, not yours."
            ),
        }, indent=2, sort_keys=True))
        return 0
    report = run_pre_release_check(
        repo_root,
        output_zip=getattr(args, "output", "dist/espalier-harness.zip"),
        skip_tests=getattr(args, "skip_tests", False),
        skip_pack=getattr(args, "skip_pack", False),
        skip_parity=getattr(args, "skip_parity", False),
    )

    # Chain the release-readiness gate. Imported lazily so
    # `espalier pre-release` still works on environments where the
    # scripts/ directory hasn't been packaged with the wheel.
    gate_results: list[dict] = []
    gate_status = "pass"
    if not getattr(args, "skip_release_check", False):
        gate_script = repo_root / "scripts" / "release_check.py"
        if not gate_script.exists():
            # Absence is precisely the case the operator most needs to be told
            # about; passing silently here with empty gate_results would hide
            # wheel-only installs and accidental deletes. Operator must
            # explicitly opt out with --skip-release-check.
            gate_status = "fail"
            gate_results = [{
                "name": "release_check_present",
                "status": "FAIL",
                "detail": (
                    f"scripts/release_check.py not found at {gate_script} — "
                    "release gate cannot run. Re-install from a source "
                    "checkout or pass --skip-release-check to acknowledge "
                    "the gap."
                ),
            }]
        else:
            sys.path.insert(0, str(repo_root / "scripts"))
            try:
                import release_check  # type: ignore[import-not-found]
                results = release_check.run_all_checks(repo_root)
                gate_results = [
                    {"name": r.name, "status": r.status, "detail": r.detail}
                    for r in results
                ]
                if any(r.status == "FAIL" for r in results):
                    gate_status = "fail"
            except Exception as exc:  # noqa: BLE001
                gate_status = "fail"
                gate_results = [{
                    "name": "release_check_invocation",
                    "status": "FAIL",
                    "detail": f"raised: {os_error_text(exc)}",
                }]
            finally:
                sys.path.pop(0)

    report["release_check"] = {
        "status": gate_status,
        "results": gate_results,
    }

    # Aggregate: pre_release_check fails OR gate fails -> fail.
    overall = "pass" if (report["status"] == "pass" and gate_status == "pass") else "fail"
    report["status"] = overall

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if overall == "pass" else 1


def _bounds_intersect(
    bound: tuple[str, ...],
    changed: set[str],
    *,
    closure_paths: set[str] | None = None,
) -> bool:
    """Return True iff any path in ``bound`` (or ``closure_paths``)
    is in or under any entry of ``changed``.

    The check is path-prefix-aware: bound ``espalier/foo.py`` is
    considered "intersecting" with changed ``espalier`` (directory
    edit covers the file). When ``closure_paths`` is provided (the
    fragment opted into ``bound_closure=true``), the intersection
    widens to include caller files computed by
    ``_resolve_bound_closure``.
    """
    if not changed:
        return False
    candidates: set[str] = set(closure_paths or ())
    for entry in bound:
        path = entry.split("::", 1)[0]
        if path:
            candidates.add(path)
    for cand in candidates:
        for c in changed:
            if cand == c:
                return True
            if cand.startswith(c.rstrip("/") + "/"):
                return True
            if c.startswith(cand.rstrip("/") + "/"):
                return True
    return False


def cmd_freshness_check(args: argparse.Namespace) -> int:
    """Report freshness state per fragment and persist the derived
    state_cache (to its gitignored per-install file) for downstream consumers.

    ``--changed-files`` scopes the exit-2 decision to only
    fragments whose bound paths (optionally widened by
    ``bound_closure=true``) intersect the PR's changed-files set.
    Display rows still show all criticals; only the gate's blocking
    decision is scoped.
    """
    from espalier.freshness import (
        FreshnessError,
        scan_repo,
        update_state_cache,
    )
    from espalier.scanners.freshness import (
        _head_sha, _resolve_bound_closure, _utc_now_iso,
        cohort_warning as freshness_cohort_warning,
    )

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    try:
        states = scan_repo(repo_root)
    except FreshnessError as exc:
        print(f"freshness scan failed: {exc}", file=sys.stderr)
        return 2

    critical_only = bool(getattr(args, "critical_only", False))
    as_json = bool(getattr(args, "json", False))
    changed_files_raw = getattr(args, "changed_files", "") or ""
    changed: set[str] = {
        p.strip().replace("\\", "/")
        for p in changed_files_raw.split(",")
        if p.strip()
    }
    # --changed-files only scopes the exit decision when
    # --critical-only is also set (the `if critical_only and changed:` branch
    # below). Passed alone it is silently ignored and the gate stays repo-wide
    # (every critical fragment blocks) — warn so the operator isn't misled into
    # thinking a PR was scoped.
    if changed and not critical_only:
        print(
            "WARN: --changed-files is only applied together with "
            "--critical-only; without it the freshness exit decision stays "
            "repo-wide. Add --critical-only to scope the exit to fragments "
            "whose bound intersects the changed files.",
            file=sys.stderr,
        )

    rows: list[dict] = [{
        "id": s.fragment.id,
        "state": s.state,
        "policy": s.fragment.policy,
        "bound": list(s.fragment.bound),
        "last_verified_sha": s.last_verified_sha,
        "commits_since": s.commits_since,
        "days_since": s.days_since,
        "dirty_paths": list(s.dirty_paths),
        "message": s.message,
        "source_path": s.fragment.source_path,
        "source_line": s.fragment.source_line,
    } for s in states]

    if critical_only:
        rows = [r for r in rows if r["state"] == "critical"]

    counts = {
        "fresh": sum(1 for s in states if s.state == "fresh"),
        "stale": sum(1 for s in states if s.state == "stale"),
        "critical": sum(1 for s in states if s.state == "critical"),
        "unpinned": sum(1 for s in states if s.state == "unpinned"),
    }

    # §C22 advisory: a re-created cohort is reported at the moment it exists,
    # on both output paths (the JSON path fed the machine readers nothing).
    cohort = freshness_cohort_warning(repo_root)
    # The hand-edited-literal check reads the manifest committed at HEAD; on
    # a tree that gitignores .espalier/ (every adopter tree init writes) it
    # stands down, and says so here rather than reading fresh in silence.
    from espalier.scanners.freshness import hand_edit_check_note
    literal_note = hand_edit_check_note(repo_root)
    if as_json:
        print(json.dumps({
            "counts": counts, "fragments": rows, "advisory": cohort,
            "literal_check": literal_note,
        }, indent=2, sort_keys=True))
    else:
        print(
            f"Fragments: {len(states)}  "
            f"fresh={counts['fresh']} stale={counts['stale']} "
            f"critical={counts['critical']} unpinned={counts['unpinned']}"
        )
        if literal_note:
            print(f"  (advisory) {literal_note}")
        for r in rows:
            print(
                f"  [{r['state']:>9}] {r['id']:<24} "
                f"{r['source_path']}:{r['source_line']}  "
                f"{r['message']}"
            )
        # Never affects the exit code.
        if cohort:
            print(f"  [ advisory] {cohort}")

    try:
        update_state_cache(
            repo_root,
            counts=counts,
            critical=[
                {
                    "id": s.fragment.id,
                    "source": f"{s.fragment.source_path}:{s.fragment.source_line}",
                    "reason": s.message,
                }
                for s in states if s.state == "critical"
            ],
            stale=[
                {
                    "id": s.fragment.id,
                    "source": f"{s.fragment.source_path}:{s.fragment.source_line}",
                    "reason": s.message,
                }
                for s in states if s.state == "stale"
            ],
            computed_at=_utc_now_iso(),
            computed_at_sha=_head_sha(repo_root),
        )
    except OSError as exc:
        # R3: the state cache is an optimization, not the gate result. A
        # read-only repo (cannot create .espalier/) must NOT mask the freshness
        # verdict — the 0/2 exit computed below is the command's exit code
        # regardless of whether the cache could be written.
        print(
            f"[freshness] WARN: state cache not written ({os_error_text(exc)}); verdict unaffected.",
            file=sys.stderr,
        )

    criticals = [s for s in states if s.state == "critical"]
    if not criticals:
        return 0
    if critical_only and changed:
        blocking: list = []
        for s in criticals:
            closure: set[str] | None = None
            if s.fragment.bound_closure:
                closure = set()
                for b in s.fragment.bound:
                    closure |= _resolve_bound_closure(b, repo_root)
            if _bounds_intersect(s.fragment.bound, changed,
                                 closure_paths=closure):
                blocking.append(s)
        return 2 if blocking else 0
    return 2


def _manifest_entries_on_disk(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """The manifest's per-fragment entries as written on disk, keyed by id.

    ``{}`` when the file is missing, unreadable or not the expected shape: a
    corrupt freshness.json no-ops the read, never raises past the command
    (DEF-829). ``pin --all``'s pre-flight and ``unpin`` read the file through
    it (the single pin reads nothing: the engine carries the literal).
    """
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-829)
        return {}
    frags = data.get("fragments", {}) if isinstance(data, dict) else {}
    if not isinstance(frags, dict):
        return {}
    return {fid: entry for fid, entry in frags.items() if isinstance(entry, dict)}


def _note_missing_literal(fragment_id: str, entry: dict[str, Any]) -> None:
    """One stderr line when a numeric-contract fragment is pinned with no
    literal: the policy then holds no number (``check`` reads the bound
    only, and the hand-edit check has nothing to compare). A first pin's
    honest state -- every numeric-contract fragment on the harness's own tree
    was seeded this way -- and nothing else's, so it is said, not refused."""
    if entry.get("policy") == "numeric-contract" and "expected_value" not in entry:
        print(
            f"note: {fragment_id!r} is a numeric-contract fragment pinned with no "
            f"expected_value; it holds no number until one is given with "
            f"--expected-value",
            file=sys.stderr,
        )


def cmd_freshness_pin(args: argparse.Namespace) -> int:
    """Pin a fragment at HEAD.

    ``--all`` walks every discovered fragment and pins each.
    Useful for an initial seeding pass; safe to re-run idempotently
    when no operator-verification has happened (each pin just refreshes
    SHA + timestamp).
    """
    from espalier.freshness import (
        pin_fragment, DirtyBoundRefusedError, FreshnessError, RebindingRefusedError,
        StaleLiteralRefusedError, carried_literal,
    )
    from espalier.scanners.freshness import discover_fragments

    if getattr(args, "all", False) and args.fragment_id is not None:
        # ``pin --all <repo>``: the optional fragment-id positional swallows
        # the repo path, and the bulk pass then ran on the CURRENT directory
        # -- a different tree than the one named (driven 2026-09-12: a test
        # naming a scratch repo re-pinned the self-host manifest). A
        # directory in that slot is the repo; anything else is a usage error,
        # since --all takes no fragment id.
        # An empty string is a directory to ``Path`` (it resolves to the
        # cwd) -- the ``"$UNSET"`` shape ``_nonempty_path`` refuses on the
        # REPO positional, refused here the same way.
        if (
            str(args.repo) == "."
            and args.fragment_id.strip()
            and Path(args.fragment_id).is_dir()
        ):
            args.repo = args.fragment_id
            args.fragment_id = None
        else:
            print(
                f"usage: {_remedy_py()} -m espalier freshness pin --all [repo]  "
                f"(--all takes no fragment id; got {args.fragment_id!r})",
                file=sys.stderr,
            )
            return 1

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    force = getattr(args, "force", False)
    expected = getattr(args, "expected_value", None)
    parsed_expected: object = None
    if expected is not None:
        try:
            parsed_expected = json.loads(expected)
        except (TypeError, json.JSONDecodeError):
            parsed_expected = expected

    if getattr(args, "all", False):
        if force:
            print(
                "--all is mutually exclusive with --force (bulk seeding "
                "must not silently re-bind; review and re-pin "
                "individual fragments with --force after confirming "
                "each diff)",
                file=sys.stderr,
            )
            return 1
        if expected is not None:
            print(
                "--all is mutually exclusive with --expected-value "
                "(per-fragment expected_value cannot be supplied in "
                "bulk; pin individually for numeric-contract policy)",
                file=sys.stderr,
            )
            return 1
        try:
            frags = discover_fragments(repo_root)
        except FreshnessError as exc:
            print(f"discover failed: {exc}", file=sys.stderr)
            return 1
        on_disk = _manifest_entries_on_disk(repo_root / ".espalier" / "freshness.json")
        # A cohort re-attestation resets every clock together or not at all:
        # refuse BEFORE pinning anything when a bound has uncommitted changes
        # (HEAD is not the tree that was verified) or when an entry's literal
        # cannot be carried -- the bound moved since the pin that verified it,
        # or on a tree that commits its manifest the literal was edited by
        # hand beside an unchanged pin (a number this pass would otherwise
        # re-stamp as verified at a new HEAD). The rule is the engine's own
        # (carried_literal), asked here so the refusal lands before the first
        # pin; the remedy is one --all cannot take: a commit, or the one
        # fragment pinned on its own with --expected-value.
        from espalier.scanners.freshness import dirty_bound_paths
        refused: list[dict[str, object]] = []
        for frag in frags:
            dirty = dirty_bound_paths(repo_root, frag.bound)
            if dirty:
                refused.append({"id": frag.id, "reason": (
                    f"bound has uncommitted changes ({', '.join(dirty)}): commit "
                    f"the bound first, or pin {frag.id!r} on its own with --force"
                )})
                continue
            try:
                carried_literal(repo_root, frag, on_disk.get(frag.id))
            except StaleLiteralRefusedError as exc:
                refused.append({"id": frag.id, "reason": (
                    f"{exc} (pin {frag.id!r} on its own)"
                )})
        if refused:
            print(
                f"pin --all refused before pinning: {len(refused)} fragment(s) "
                f"have a bound with uncommitted changes or a literal edited by "
                f"hand (see skipped); nothing was pinned",
                file=sys.stderr,
            )
            print(json.dumps({
                "pinned_all": [],
                "count": 0,
                "skipped": refused,
                "skipped_count": len(refused),
            }, indent=2, sort_keys=True))
            return 1
        pinned: list[str] = []
        skipped: list[dict[str, object]] = []
        for frag in frags:
            try:
                entry = pin_fragment(frag.id, repo_root)
            except DirtyBoundRefusedError as exc:
                # The pre-flight above ran on the same tree; a change in
                # between is reported with --all's own remedy, not --force.
                skipped.append({"id": frag.id, "reason": (
                    f"bound has uncommitted changes ({', '.join(exc.paths)}): commit "
                    f"the bound first, or pin {frag.id!r} on its own with --force"
                )})
                continue
            except RebindingRefusedError as exc:
                skipped.append({"id": frag.id, "reason": str(exc)})
                continue
            except FreshnessError as exc:
                print(f"pin {frag.id!r} failed: {exc}", file=sys.stderr)
                return 1
            pinned.append(frag.id)
            _note_missing_literal(frag.id, entry)
        print(json.dumps({
            "pinned_all": pinned,
            "count": len(pinned),
            "skipped": skipped,
            "skipped_count": len(skipped),
        }, indent=2, sort_keys=True))
        return 1 if skipped else 0

    # Validate the positional before pinning. fragment_id is
    # nargs="?" default=None, so `freshness pin` with no id and no --all
    # otherwise reaches pin_fragment(None) and emits the confusing
    # "pin failed: fragment id None not found ..." (leaks the literal None).
    if args.fragment_id is None:
        print(
            f"usage: {_remedy_py()} -m espalier freshness pin <fragment_id> [repo]  "
            "(or --all to pin every fragment)\n"
            "no fragment id given; pass a fragment id, or --all to seed "
            "every discovered fragment",
            file=sys.stderr,
        )
        return 1

    try:
        if expected is None:
            # No --expected-value: the engine carries the entry's literal
            # under carried_literal's rules (a re-pin refreshes the clock,
            # not the number; a bound that moved or a literal edited by hand
            # is refused and the number restated). This path passed None
            # here and the engine, rebuilding the entry, dropped the literal
            # -- ff9eaff (2026-09-19) lost hook-count's 12 that way, the
            # pre-cut review's D1. `--expected-value null` is the explicit
            # None: record no literal.
            entry = pin_fragment(args.fragment_id, repo_root, force=force)
        else:
            entry = pin_fragment(
                args.fragment_id, repo_root,
                expected_value=parsed_expected,
                force=force,
            )
    except FreshnessError as exc:
        print(f"pin failed: {exc}", file=sys.stderr)
        return 1

    _note_missing_literal(args.fragment_id, entry)
    print(json.dumps({
        "pinned": args.fragment_id,
        "entry": entry,
    }, indent=2, sort_keys=True))
    return 0


def cmd_freshness_unpin(args: argparse.Namespace) -> int:
    """Remove a fragment's manifest entry."""
    from espalier.freshness import unpin_fragment, FreshnessError

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    prior = _manifest_entries_on_disk(
        repo_root / ".espalier" / "freshness.json",
    ).get(args.fragment_id, {})
    try:
        removed = unpin_fragment(args.fragment_id, repo_root)
    except FreshnessError as exc:
        print(f"unpin failed: {exc}", file=sys.stderr)
        return 1

    if removed:
        line = f"Removed manifest entry for {args.fragment_id}"
        if "expected_value" in prior:
            # The rebind refusal's own remedy is unpin-then-pin, and the next
            # pin has nothing to carry: say what went with the entry.
            line += (
                f" (it carried expected_value {prior['expected_value']!r}; "
                f"the next pin needs --expected-value)"
            )
        print(line)
        return 0
    print(
        f"No manifest entry for {args.fragment_id}",
        file=sys.stderr,
    )
    return 1


# DEF-793: `memory prune` moves Session Log rows out of ESPALIER_MEMORY.md (the
# repo root) into an archive elsewhere, and a link is resolved from the doc that
# CONTAINS it -- by both reflect link checkers and by any markdown renderer. A row
# copied verbatim kept its root-relative targets (`](memory/x.md)`), which broke
# the moment it landed in docs/ and read as a high broken link on every reflect
# pass. `_rebase_row_links` re-spells them from the archive as the row moves.
#
# An inline link or image destination: `](dest)`, `](dest "title")`, or the
# angle-bracket form `](<dest>)`. The lookahead requires the link to close, so a
# stray `](` in prose is left alone; a bare destination holding `<` is a
# placeholder example (`memory/<slug>.md`) and does not match. A reference
# definition (`[id]: dest`) must begin its own line and every line the prune
# moves begins with `|`, so a moved row cannot carry one.
_ROW_LINK_DEST_RE = re.compile(
    r"(\]\(\s*)(<[^<>\n]*>|[^\s()<>]+)"
    r"(?=(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\))"
)
# `scheme:` at the start of a target: http(s), mailto, ftp, any absolute URL.
_URL_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_BACKTICK_RUN_RE = re.compile(r"`+")


def _code_span_bounds(line: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each inline code span in ``line``.

    CommonMark's rule: a run of N backticks opens a span that the next run of
    exactly N backticks closes; a run with no such closer is literal text.
    """
    runs = [(m.start(), m.end()) for m in _BACKTICK_RUN_RE.finditer(line)]
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(runs):
        start, end = runs[i]
        closer = next(
            (j for j in range(i + 1, len(runs))
             if runs[j][1] - runs[j][0] == end - start),
            None,
        )
        if closer is None:
            i += 1
            continue
        spans.append((start, runs[closer][1]))
        i = closer + 1
    return spans


def _rebase_row_links(row: str, source_dir: Path, archive_dir: Path) -> str:
    """Return ``row`` with each relative link target re-spelled from
    ``archive_dir`` instead of ``source_dir``, every other byte unchanged.

    The prefix is the relative path from the archive's directory to the source's,
    so an ``--archive`` anywhere gets its own. Left alone: a URL of any scheme, a
    same-doc ``#``/``?`` reference, a root-anchored ``/`` path (the checkers read
    it from the repo root wherever it sits), a target that resolves from the
    archive's directory but not the source's (written for where the row lands --
    a row restored from the archive or hand-repaired, where a second prefix would
    break it), and anything inside an inline code span, which is a mention, not a
    link. A ``../`` target is decided by that resolution, never by its spelling:
    one written at the source for a sibling checkout is re-based like any other.
    """
    try:
        rel = os.path.relpath(source_dir, archive_dir)
    except ValueError:  # different Windows drives: no relative spelling exists
        return row
    if rel == os.curdir:
        return row
    prefix = rel.replace("\\", "/") + "/"

    def _rebase(m: re.Match[str]) -> str:
        dest = m.group(2)
        bracketed = dest.startswith("<")
        target = dest[1:-1] if bracketed else dest
        if (not target or target.startswith(("#", "?", "/"))
                or _URL_SCHEME_RE.match(target)):
            return m.group(0)
        path = target.split("#", 1)[0]
        # os.path.exists, not Path.exists: it answers False on ANY OSError (a
        # name too long, a character the platform refuses), never raises.
        # Normalised LEXICALLY first, as a markdown link resolves: the
        # archive's directory may not exist yet on a first prune, and the
        # kernel cannot walk `docs/..` through a directory that is not there.
        if (path and not os.path.exists(os.path.normpath(os.path.join(source_dir, path)))
                and os.path.exists(os.path.normpath(os.path.join(archive_dir, path)))):
            return m.group(0)
        while target.startswith("./"):
            target = target[2:]
        rebased = prefix + target
        return m.group(1) + (f"<{rebased}>" if bracketed else rebased)

    pieces: list[str] = []
    pos = 0
    for start, end in _code_span_bounds(row):
        pieces.append(_ROW_LINK_DEST_RE.sub(_rebase, row[pos:start]))
        pieces.append(row[start:end])
        pos = end
    pieces.append(_ROW_LINK_DEST_RE.sub(_rebase, row[pos:]))
    return "".join(pieces)


def cmd_memory_prune(args: argparse.Namespace) -> int:
    """Archive oldest N Session Log rows from ESPALIER_MEMORY.md.

    Locates the ``## Session Log`` table, moves the oldest ``--rows N``
    data rows to ``docs/session-archive.md`` under a date-stamped
    heading, and rewrites ESPALIER_MEMORY.md without them. Refuses to leave the
    Session Log table empty unless ``--allow-empty`` is set. ``--rows 0``
    is a no-op smoke.

    ``--allow-empty`` opts out of the minimum-1-row floor. Hook
    context (``tools/cc/hooks/post_write_check.py``) always passes this
    so autoprune never blocks on a single-row Session Log. Direct CLI
    users keep the safety default.

    ``--keep-newest N`` reserves the N newest rows from eviction and is NOT
    waived by ``--allow-empty``. It exists because ESPALIER_MEMORY.md's own
    pruning policy already promises "the newest rows are always kept" while,
    with a one-row Session Log, ``--allow-empty`` archived that very row --
    the documented contract and the behaviour had drifted apart.

    The file and its archive are decoded through
    ``surface_contract.decode_text_or_problem`` -- both are hand-edited (the
    memory file at every handoff) and the autoprune hook shells out to this
    verb, so a UTF-8 or UTF-16 byte-order mark from an editor or a PowerShell
    re-encode reads as text and both files are written back as UTF-8. Bytes
    that are neither, or a byte-order-mark-less UTF-16 file (NUL-laden once
    decoded), are refused with exit 1 and the encoding to re-save in, before
    either write, because pruning such a file would write the garbage back
    (DEF-797).
    """
    from datetime import date

    repo_root = Path(args.root or ".").resolve()
    memory_path = repo_root / _MEMORY_FILENAME
    archive_rel = args.archive or "docs/session-archive.md"
    archive_path = repo_root / archive_rel

    if not memory_path.is_file():
        print(f"ESPALIER_MEMORY.md not found: {memory_path}", file=sys.stderr)
        return 1

    text, problem = surface_contract.decode_text_or_problem(memory_path.read_bytes())
    if problem:
        print(f"ESPALIER_MEMORY.md is {problem}", file=sys.stderr)
        return 1
    lines = text.splitlines(keepends=False)

    section_start: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "## Session Log":
            section_start = i
            break
    if section_start is None:
        print("ESPALIER_MEMORY.md has no '## Session Log' section", file=sys.stderr)
        return 1

    header_idx: int | None = None
    separator_idx: int | None = None
    for i in range(section_start + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if header_idx is None and lines[i].startswith("| Date "):
            header_idx = i
            continue
        if header_idx is not None and lines[i].startswith("|---"):
            separator_idx = i
            break

    if header_idx is None or separator_idx is None:
        print("Session Log table header not found", file=sys.stderr)
        return 1

    data_row_indices: list[int] = []
    for i in range(separator_idx + 1, len(lines)):
        line = lines[i]
        if line.startswith("## "):
            break
        if line.startswith("|"):
            data_row_indices.append(i)
        # Blank or non-pipe lines inside the section are skipped, not
        # treated as table terminators — hand-edits sometimes leave a
        # blank between rows and the prune verb must still see the
        # whole table.

    rows_to_prune = args.rows
    if rows_to_prune <= 0:
        print(f"nothing to prune (rows={rows_to_prune})")
        return 0

    allow_empty = getattr(args, "allow_empty", False)

    # ONE reservation concept, not two. The minimum-1-row floor below IS a
    # keep-newest of 1 that ``--allow-empty`` waives; ``--keep-newest N`` states
    # the same reservation explicitly and is deliberately NOT waivable, because
    # the caller that passes it (the autoprune hook) passes ``--allow-empty``
    # too and means both at once: prune even a one-row Session Log, but never
    # the newest row. Written as one ``max()`` so a future reader cannot satisfy
    # one and silently miss the other.
    #
    # ``getattr``, not ``args.keep_newest``: tests/test_memory_prune_cli.py
    # builds bare ``argparse.Namespace`` objects, so a direct attribute read
    # raises AttributeError across every one of its cases.
    keep_newest = max(0, getattr(args, "keep_newest", 0))
    reserved = max(keep_newest, 0 if allow_empty else 1)

    # THE UNIT RECONCILIATION LIVES HERE, and it lives here on purpose.
    # ``--rows`` arrives from the autoprune hook as a LINE delta (over-cap lines
    # plus headroom) and is consumed below as a ROW count. The conversion is
    # sound -- a Session Log row is exactly one line, because ``data_row_indices``
    # is built from lines beginning with "|" -- but it is only sound while enough
    # rows EXIST, and the excess may live in prose that no row eviction can
    # reach. Under ``--allow-empty`` the request was silently clamped, so a caller
    # asking for eight and getting two could not tell.
    #
    # The hook does NOT do this arithmetic itself, deliberately: it would need its
    # own Session Log parser, which is a second spelling of the one above, and the
    # tie-break comment below is a standing record of what a second spelling costs
    # here. The verb already has the parse, so the verb reports the shortfall and
    # the hook carries its line through verbatim.
    requested_rows = rows_to_prune

    if rows_to_prune > len(data_row_indices):
        if allow_empty:
            # Best-effort under --allow-empty — archive as many rows as exist,
            # even if that's fewer than requested. The
            # caller (hook autoprune) wants the file shrunk; refusing
            # because the request exceeded availability re-creates the
            # cap-stack-floor friction the flag was designed to fix.
            rows_to_prune = len(data_row_indices)
            if rows_to_prune == 0:
                print("nothing to prune (Session Log already empty)")
                return 0
        else:
            print(
                f"requested --rows {rows_to_prune} but Session Log has only "
                f"{plural(len(data_row_indices), 'data row')}",
                file=sys.stderr,
            )
            return 1

    remaining = len(data_row_indices) - rows_to_prune
    if remaining < 1 and not allow_empty:
        print(
            "refusing to prune: would leave fewer than 1 row in Session Log "
            "(pass --allow-empty to opt out of the minimum-row floor)",
            file=sys.stderr,
        )
        return 1

    # Date-aware ordering: pre-fix this took data_row_indices[:N] which
    # is "first N by file position." That presumes a fixed insertion
    # convention (newest-at-bottom). When operators insert at top (the
    # de-facto reading order is newest-first), the implementation
    # archived the NEWEST rows. Parse the leading `| YYYY-MM-DD` prefix
    # and sort ascending so "oldest" is by date, not by position. Rows
    # without a parseable date sort to the end (preserved, not silently
    # archived).
    #
    # The tie-break is NEGATED file index, and that sign is the whole contract:
    # within one date the BOTTOM-most row is the oldest, because `/handoff`
    # prepends. A plain `line_index` treats the topmost same-day row as oldest,
    # which under prepend is the row the operator just wrote -- driven: with
    # three rows sharing today's date and one from yesterday, `--rows 2`
    # archived yesterday's row AND the just-written one, keeping both older
    # same-day rows. That is exactly the footgun docs/SHARP_EDGES.md names in
    # "ESPALIER_MEMORY.md Autoprune Archives the Row You Just Added".
    #
    # This sign was correct while `handoff.md` said "append" and became wrong the
    # moment that doc was corrected to "prepend" to match a decade of practice
    # and the live artifact. Sister site: `tools/cc/hooks/session_start.py`'s
    # `_memory_toc` sorts DESCENDING and must therefore key on the date ALONE
    # (`reverse=True` would reverse an index tie-break too). Opposite spellings,
    # one shared meaning -- pinned together by
    # tests/test_forced_copy_parity.py::TestMemoryDateRegexParity.
    def _row_sort_key(line_index: int) -> tuple[str, int]:
        m = _MEMORY_DATE_RE.match(lines[line_index])
        if m:
            return (m.group(1), -line_index)
        return ("9999-12-31", -line_index)

    sorted_indices = sorted(data_row_indices, key=_row_sort_key)

    # The reservation is a SLICE of sorted_indices, never a second derivation.
    # sorted_indices is oldest-first under the date key with the NEGATED index
    # tie-break, so the newest rows are its tail and reserving them is a single
    # slice. Re-deriving "newest" here would give the tie-break a second, silent
    # spelling -- exactly the drift the sign comment above warns about.
    evictable = sorted_indices[:max(0, len(sorted_indices) - reserved)]
    if rows_to_prune > len(evictable):
        # Only reachable when a reservation binds harder than the two checks
        # above: --allow-empty waives the floor but not --keep-newest, so a hook
        # asking for more rows than are evictable gets as many as it may have
        # rather than an error. With no --keep-newest this line is unreachable --
        # the checks above have already returned.
        rows_to_prune = len(evictable)
        if rows_to_prune == 0:
            print(
                f"nothing to prune ({plural(len(data_row_indices), 'data row')}, "
                f"{plural(reserved, 'newest row')} reserved)"
            )
            return 0
    oldest_indices = evictable[:rows_to_prune]
    pruned_rows = [lines[i] for i in oldest_indices]

    today = date.today().isoformat()
    # Re-based as they move (DEF-793): each row was written at the memory file's
    # directory and is about to be read from the archive's.
    archive_chunk = (
        "\n"
        f"## Pruned {today} (via espalier memory prune)\n\n"
        "| Date | What Happened | Notes |\n"
        "|------|--------------|-------|\n"
        + "\n".join(
            _rebase_row_links(row, memory_path.parent, archive_path.parent)
            for row in pruned_rows
        )
        + "\n"
    )

    pruned_set = set(oldest_indices)
    new_lines = [line for i, line in enumerate(lines) if i not in pruned_set]
    trailing_nl = "\n" if text.endswith("\n") else ""
    new_text = "\n".join(new_lines) + trailing_nl

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if archive_path.is_file():
        # The archive is the memory file's sibling and an operator appends to
        # it by hand the same way; the same decode, refused before either
        # write (failure-mode review, 2026-09-15: a byte-order-marked archive
        # tracebacked out of this verb three lines after the memory file was
        # refused politely).
        existing, problem = surface_contract.decode_text_or_problem(archive_path.read_bytes())
        if problem:
            print(f"{archive_rel} is {problem}", file=sys.stderr)
            return 1
    if existing and not existing.endswith("\n"):
        existing += "\n"
    # Archive first, then memory — order preserved so an interrupt between
    # the two writes duplicates rows (recoverable) rather than losing them.
    # Both writes are atomic (tempfile + os.replace) so a concurrent reader
    # never sees a torn file.
    atomic_write_text(archive_path, existing + archive_chunk)
    atomic_write_text(memory_path, new_text)

    # Name the rows. The archive destination is gitignored and export-ignored, and
    # shrinking ESPALIER_MEMORY.md afterwards does not bring a row back -- so the
    # dates printed here plus the "## Pruned <date>" heading are the only handle an
    # operator gets on what left.
    archived_dates = [
        m.group(1) for m in (_MEMORY_DATE_RE.match(r) for r in pruned_rows) if m
    ] or ["undated"]
    # Name the shortfall when the request was clamped. Silence here is what let a
    # line-denominated request read as satisfied while only some of it could be
    # met; the caller cannot compute this without re-parsing the table.
    shortfall = (
        f"; requested {requested_rows}, "
        f"{plural(len(data_row_indices) - reserved, 'row')} evictable "
        f"({plural(reserved, 'newest row')} reserved)"
        if requested_rows > rows_to_prune else ""
    )
    print(
        f"pruned {plural(rows_to_prune, 'row')} from ESPALIER_MEMORY.md to "
        f"{archive_rel} (dated {', '.join(archived_dates)}){shortfall}"
    )
    return 0


def _nonempty_path(value: str) -> str:
    """argparse type for the REPO positional. An empty string (e.g. from an
    unset shell var: `espalier audit "$TARGET"`) would otherwise resolve to cwd
    silently and exit 0 on the wrong tree. Reject it at parse time with an
    actionable message; '.' remains the explicit cwd opt-in."""
    if not value or not value.strip():
        raise argparse.ArgumentTypeError(
            "repo path must not be empty (use '.' for the current directory)"
        )
    return value


def cmd_strengthen(args: argparse.Namespace) -> int:
    """Mechanical test-gap report: risk-rank untested public symbols (advisory).

    Exit codes (docs/CLI_EXIT_CODES.md): ``0`` = report produced (including the
    Python-only and no-gaps cases); ``2`` = precondition failure (path missing
    or not a directory). NEVER ``1`` — an advisory report has no
    completed-but-failed gate for ``1`` to signal.
    """
    from espalier.strengthen import build_strengthen_report, render_strengthen_md
    from espalier._atomic_io import atomic_write_text

    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2

    report = build_strengthen_report(
        repo_root,
        top_n=getattr(args, "top_n", 20),
        skip_fan_in=getattr(args, "skip_fan_in", False),
    )
    # Advisory scanner-artifact output, not a cross-module coordination
    # surface — the filesystem-contracts scanner exempts strengthen_report.json
    # via OUTPUT_FILENAME_SUFFIXES, the same class as the scan_*.json reports.
    reports_dir = repo_root / "reports"
    atomic_write_text(
        reports_dir / "strengthen_report.json",
        json.dumps(report, indent=2, sort_keys=True),
    )
    atomic_write_text(
        reports_dir / "strengthen_report.md",
        render_strengthen_md(report),
    )
    print(render_strengthen_md(report))
    print("\nWrote reports/strengthen_report.json + reports/strengthen_report.md")
    return 0


def _add_repo_arg(parser: argparse.ArgumentParser, *, optional: bool = False) -> None:
    """CLI-5/CLI-4: one repo positional with a consistent metavar + help."""
    if optional:
        parser.add_argument("repo", metavar="REPO", nargs="?", default=".",
                            type=_nonempty_path,
                            help="repo path (default: current dir)")
    else:
        parser.add_argument("repo", metavar="REPO", type=_nonempty_path,
                            help="repo path; '.' for current dir")


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    """CLI-5: one --config declaration with help + metavar."""
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="path to an espalier.toml config (default: repo/espalier.toml)")


# Placeholder the top-level epilog carries for the interpreter the operator
# should type. Resolved when help is RENDERED, never when the parser is built:
# `_detect_python_command` spawns `--version` probes and `build_parser()` runs
# on every CLI call (DEF-383a -- the epilog used to spell a literal `python`,
# which is command-not-found on stock macOS).
_HELP_INTERPRETER_FIELD = "{py}"


class _CuratedChoiceParser(argparse.ArgumentParser):
    """ArgumentParser whose ``invalid choice`` error lists only help-carrying
    subcommands -- mirroring the curated ``--help``, so a typo never advertises
    the dev/self-host commands registered without ``help=`` (which stay in
    ``sub.choices`` and remain fully callable). Closes the error-path residual of
    the internal-command leak (the ``--help`` metavar half already landed).

    argparse propagates ``parser_class`` to subparsers, so this class also governs
    the freshness/memory sub-verb error paths; those groups are entirely
    help-carrying, so their enumeration is unchanged -- pinned by
    ``TestArgparseErrorCuration.test_curation_does_not_drop_nested_subverbs``.

    It also resolves the epilog's interpreter placeholder lazily -- see
    ``_HELP_INTERPRETER_FIELD``.
    """

    def format_help(self) -> str:
        if self.epilog and _HELP_INTERPRETER_FIELD in self.epilog:
            self.epilog = self.epilog.replace(
                _HELP_INTERPRETER_FIELD, _remedy_py()
            )
        return super().format_help()

    def error(self, message: str) -> NoReturn:
        sub = (
            next(
                (a for a in self._subparsers._group_actions
                 if isinstance(a, argparse._SubParsersAction)),
                None,
            )
            if self._subparsers is not None
            else None
        )
        if sub is not None:
            # Rewrite ONLY the subparsers-selection message (``argument
            # <command>: invalid choice: ...``), anchored on this action's own
            # metavar/dest so a future choices-argument on the same parser (e.g.
            # ``--flag {a,b}``) is never mis-rewritten with the subcommand list.
            prefix = sub.metavar or sub.dest
            m = re.match(
                rf"(?P<head>argument {re.escape(prefix)}: invalid choice: "
                rf"'[^']*' \(choose from )(?P<choices>.*)\)\Z",
                message,
            )
            if m is not None:
                # ``_choices_actions`` holds exactly the subcommands registered
                # with ``help=`` -- the ones ``--help`` lists.
                public = {a.metavar or a.dest for a in sub._choices_actions}
                # Filter the interpreter's OWN rendering rather than rebuilding
                # it: argparse quotes the choice names on some CPython minors and
                # not others (repr vs str across 3.10-3.14), so keeping each
                # surviving entry verbatim preserves the native styling instead
                # of hardcoding one style and diverging from every sibling error.
                kept = [
                    c for c in m.group("choices").split(", ")
                    if c.strip().strip("'\"") in public
                ]
                if kept:
                    message = f"{m.group('head')}{', '.join(kept)})"
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _CuratedChoiceParser(
        prog="espalier",
        description=(
            "Claude Code governance harness. Analyzes your repo, deploys CC "
            "hooks, and enforces quality on every tool call."
        ),
        epilog=(
            "First-time setup: " + _HELP_INTERPRETER_FIELD + " -m espalier init . "
            "(current dir). "
            "Quickstart: https://github.com/Mike-Byrne-AI/espalier-harness"
            "/blob/main/docs/QUICKSTART.md. Sharp edges and known limits: "
            "https://github.com/Mike-Byrne-AI/espalier-harness"
            "/blob/main/docs/SHARP_EDGES.md."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # metavar="<command>" collapses the auto-generated {choices} brace (which
    # lists every subcommand inline on the usage line and repeats it as the
    # positional-args header). The per-command description rows below still list
    # each subcommand that carries a help= string, so this both declutters the
    # top-level --help and keeps `_`-prefixed dev commands (registered without
    # help=) out of the listing — the choices brace was previously leaking them.
    # The commands stay in `sub.choices` and remain fully callable.
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_init = sub.add_parser(
        "init",
        help="first-time harness setup for this repo",
        description=(
            "Fingerprint the repo, build a harness config, deploy hook "
            "scripts + .claude/settings.json, and seed the integrity "
            "manifest. Re-runnable: existing .claude/settings.json, "
            "CLAUDE.md, ESPALIER_MEMORY.md are preserved; hook scripts re-deploy."
        ),
    )
    _add_repo_arg(p_init, optional=True)
    _add_config_arg(p_init)
    # Default-flip so a bare `espalier init .` writes the harness-managed
    # gitignore entries (otherwise adopters following QUICKSTART ran
    # `git add -A` and committed `.claude/settings.json` + per-install state).
    # The mutually-exclusive group preserves both flags: `--write-gitignore` is
    # now a no-op (already True); `--no-write-gitignore` is the opt-out.
    # Breaking change documented in CHANGELOG `### Breaking changes (pre-1.0)`.
    git_group = p_init.add_mutually_exclusive_group()
    git_group.add_argument(
        "--write-gitignore",
        dest="write_gitignore",
        action="store_true",
        default=True,
        help="Append missing required entries to .gitignore "
             "(creates the file if absent). Default since v0.7.9.",
    )
    git_group.add_argument(
        "--no-write-gitignore",
        dest="write_gitignore",
        action="store_false",
        help="Suppress the gitignore write; print the required "
             "entries to stdout only (pre-v0.7.9 behavior).",
    )
    p_init.add_argument(
        "--profile",
        choices=["minimal", "workflow", "self-host", "full"],
        default=None,
        help="Settings profile for .claude/settings.json. "
             "minimal = Read/Grep/Glob only (no Write, no Bash); "
             "workflow (default) = + narrow test commands + governed "
             "Write; self-host = for meta-harnesses governing "
             "themselves (Espalier on Espalier) — adds `python -m "
             "espalier *` and broader git inspection; full = v0.6.x "
             "broad-bash defaults (advanced). Overrides espalier.toml's "
             "default_profile.",
    )
    p_init.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Compute the deploy plan and print what would be written; "
             "make no filesystem changes. Useful for previewing init "
             "output before committing.",
    )
    p_init.add_argument(
        "--wire-hooks",
        dest="wire_hooks",
        action="store_true",
        help="Opt in to one-shot hook wiring. When an existing "
             ".claude/settings.json has NO Espalier hooks (the common "
             "permissions-only Claude Code starting state), init normally "
             "preserves it and points you at the `merge-settings` command. "
             "With this flag, init runs that merge itself (appends Espalier's "
             "hook events and adds its statusLine when that key is absent, "
             "preserves your other keys, keeps a .bak of them) so the "
             "harness is armed in one command; profile allow rules your file "
             "lacks are reported, not appended (`merge-settings --add-allows` "
             "does that). A malformed settings.json is "
             "refused, never overwritten. Default (no flag) is unchanged: "
             "never auto-edit your file.",
    )
    p_init.add_argument(
        "--rewire-interpreter",
        dest="rewire_interpreter",
        action="store_true",
        help="Opt in to swapping a below-floor Python interpreter in an "
             "existing .claude/settings.json. Espalier requires Python "
             f"{floor_text()}+; a settings.json wired to an older one (stock "
             "/usr/bin/python3 is 3.9 on macOS) leaves the blocking guards "
             "working while the blueprint chain dies silently every session. "
             "This changes ONLY the interpreter name at the front of each hook "
             "command -- your args, permissions and every other key are "
             "preserved -- and keeps a .bak of the file first. Interpreters that already "
             "meet the floor are left alone, so it is idempotent. A malformed "
             "settings.json is refused, never overwritten.",
    )
    p_init.set_defaults(func=cmd_init)

    # `espalier merge-settings` — opt-in hook wiring for an adopter whose
    # own .claude/settings.json blocked init/fuse from wiring the hooks.
    p_merge = sub.add_parser(
        "merge-settings",
        help="wire Espalier hooks into an existing .claude/settings.json "
             "(preserves your keys; keeps a .bak of them; reports the profile allow "
             "rules your file lacks, --add-allows appends them)",
        description="Merge Espalier's hook events into an existing "
                    ".claude/settings.json without overwriting your other "
                    "settings, and add its statusLine when that key is absent "
                    "(a statusLine of your own is never touched). Idempotent; "
                    "keeps a .bak of it. Always reports "
                    "which allow rules of the selected profile your file lacks; "
                    "appends them only with --add-allows, and never removes "
                    "a rule of your own.",
    )
    _add_repo_arg(p_merge, optional=True)
    p_merge.add_argument(
        "--profile", default=None,
        help="settings profile to source the hook block and allow rules from "
             "(default: the profile this install was rendered from, as recorded "
             "in reports/harness_config.json; else workflow)",
    )
    p_merge.add_argument(
        "--add-allows", dest="add_allows", action="store_true",
        help="append the selected profile's allow rules your settings.json lacks "
             "(append-only, after your own rules; a rule you denied or set to "
             "ask is never appended; the comparison is exact-string; a .bak is "
             "written). Without this flag they are only reported: permissions "
             "are yours.",
    )
    p_merge.add_argument(
        "--repair", dest="repair", action="store_true",
        help="also rewrite espalier's OWN hook entries to canonical wherever "
             "doctor finds them dead: an entry running no interpreter, missing "
             "from an event that exists, under the wrong event, with a narrowed "
             "matcher, or in the pre-v0.6.5 shell form -- on both tiers. Only "
             "entries naming espalier's scripts are touched, and every removal "
             "is listed; permissions and other keys are untouched; a .bak is "
             "written; the wiring is re-checked after the write and anything "
             "still dead is named. Without this flag those shapes are only "
             "reported (the plain merge never rewrites an entry).",
    )
    p_merge.set_defaults(func=cmd_merge_settings)

    # `espalier upgrade` — re-deploy a stale harness in place. Optional
    # positional repo default "." + --config via the shared CLI-1/CLI-4/CLI-5
    # helpers, so its metavar/help match every other command.
    p_upgrade = sub.add_parser(
        "upgrade",
        help="re-deploy a stale harness in place "
             "(default: dry-run; pass --execute to apply)",
        description=(
            "Detect a stale committed harness (engine version moved past the "
            "deployed stamp, a managed file that differs from the packaged "
            "version, or a saved plan that no longer matches the tree) and "
            "re-deploy managed assets, re-baseline the saved plan, merge hook "
            "settings, surface retired files, and refresh integrity -- as ONE "
            "dry-run-able flow. Dry-run is the default; --execute applies. "
            "Your hand-authored ESPALIER_MEMORY.md / CLAUDE.md / docs are "
            "never rewritten."
        ),
    )
    _add_repo_arg(p_upgrade, optional=True)
    _add_config_arg(p_upgrade)
    p_upgrade.add_argument(
        "--execute", action="store_true",
        help="apply the upgrade (default: dry-run prints what would change)",
    )
    p_upgrade.set_defaults(func=cmd_upgrade)

    # `espalier fuse` — build a NEW fusion repo = host copy + harness
    # overlay (both originals untouched). The source-of-truth for the fusion
    # model; the folder + fetcher channels all call it. Resilient: a deploy that
    # omits fuse.py must not brick the rest of the CLI — skip the subcommand.
    try:
        from espalier.fuse import cmd_fuse  # noqa: PLC0415  (deferred: fuse imports cli lazily)
    except ImportError:
        cmd_fuse = None
    if cmd_fuse is not None:
        p_fuse = sub.add_parser(
            "fuse",
            help="build a new fusion repo = host copy + espalier harness overlay",
            description=(
                "Create a NEW third repo combining a host project with the espalier "
                "harness, leaving both originals untouched. Copies the host (git-"
                "tracked) + overlays the harness per the fusion manifest, reseeds "
                "espalier-specific content empty, then wires it via init. The "
                "mechanical bootstrap; finish-up (verifier tests, scanner-registry "
                "emptying, agent re-seeding) is the first Claude session in the fusion."
            ),
        )
        p_fuse.add_argument("host", metavar="HOST", help="path to the host repo to fuse")
        p_fuse.add_argument("--out", required=True, metavar="DIR",
                            help="path for the NEW fusion repo (must not exist / be empty)")
        p_fuse.add_argument("--fresh", action="store_true",
                            help="start a fresh git history instead of preserving the host's")
        p_fuse.add_argument("--no-init", action="store_true",
                            help="skip the post-overlay `init` wiring (copy/overlay only)")
        p_fuse.add_argument("--dry-run", action="store_true",
                            help="report the plan (file counts + collisions) without writing")
        p_fuse.add_argument("--wire-hooks", dest="wire_hooks", action="store_true",
                            help="opt in to one-shot hook wiring: if the host's copied "
                                 ".claude/settings.json has no Espalier hooks, the fusion's "
                                 "init merges them in (appends Espalier's hook events and "
                                 "adds its statusLine when that key is absent; preserves "
                                 "your keys; keeps a .bak of them) so "
                                 "the fusion is armed in one command. Malformed files are "
                                 "refused, never overwritten. Default: never auto-edit.")
        p_fuse.set_defaults(func=cmd_fuse)

    # Each subparser gets a `description` (body text printed by
    # `espalier <cmd> --help`) and `repo` gets a metavar so the help
    # output names the expected argument.
    for name, help_text, description, func in [
        (
            "fingerprint",
            "re-fingerprint a repo and refresh what derives from it",
            "Re-fingerprint the repo and overwrite reports/repo_fingerprint.json "
            "atomically. Downstream artifacts (harness_config.json, the cc/ docs "
            "that read it, cc/SURFACE_HANDOFF.md) refresh only if they already exist.",
            cmd_fingerprint,
        ),
        (
            "audit",
            "run proof gates on an existing CC surface",
            "Print a JSON surface-gate report. Exit 0 if status=pass, 1 if the "
            "surface has findings. See docs/CLI_EXIT_CODES.md for the repo-wide "
            "0/1/2 exit convention (other commands also use 2 for usage errors "
            "and operator-resolvable preconditions). Stderr names a re-run "
            "command on failure.",
            cmd_audit,
        ),
        (
            "recover",
            "assess if the CC surface is coherent enough to resume",
            "Inspect the harness surface and return a recovery state "
            "(ok / degraded / fail) plus remediation recommendations.",
            cmd_recover,
        ),
        (
            "reflect",
            "scan for broken links and drift",
            "Cross-reference markdown links, find orphaned references, "
            "and report surface drift. See `reflect-deep` for the full "
            "structured pass.",
            cmd_reflect,
        ),
    ]:
        p = sub.add_parser(name, help=help_text, description=description)
        _add_repo_arg(p, optional=True)
        _add_config_arg(p)
        p.set_defaults(func=func)

    p_diff = sub.add_parser("diff", help="compare saved reports against fresh inference")
    _add_repo_arg(p_diff, optional=True)
    _add_config_arg(p_diff)
    p_diff.set_defaults(func=cmd_diff)

    p_handoff = sub.add_parser("surface-handoff", description="Write a surface handoff report.")
    _add_repo_arg(p_handoff, optional=True)
    p_handoff.add_argument("--out", default=None)
    p_handoff.add_argument("--json", action="store_true")
    p_handoff.set_defaults(func=cmd_surface_handoff)

    p_self = sub.add_parser("self-host", description="Prove the harness works against itself (harness-developer command).")
    _add_repo_arg(p_self, optional=True)
    p_self.add_argument(
        "--mode", choices=("auto", "source-checkout", "initialized"),
        default="auto",
        help=(
            "explicit repo-mode override. 'source-checkout' "
            "proves the committed surface only — does not require init-generated "
            "runtime files (.claude/settings.json, reports/*.json, "
            ".espalier/integrity.json). 'initialized' runs the full strict "
            "gate. 'auto' (default) detects mode from disk state."
        ),
    )
    p_self.set_defaults(func=cmd_self_host)

    # `help=` is what lists a verb in `--help`; a subparser with only
    # `description=` is registered and callable but hidden (the mechanism the
    # underscore-prefixed developer verb uses on purpose). Three adopter verbs
    # the README documents were hidden by that accident until 2026-09-12
    # (DEF-772); the self-host-only verbs stay hidden and stand down elsewhere.
    p_wt = sub.add_parser(
        "worktree-plan",
        help="print multi-lane git worktree commands for parallel work",
        description="Print multi-lane worktree commands.",
    )
    _add_repo_arg(p_wt, optional=True)
    p_wt.add_argument("--json", action="store_true")
    p_wt.set_defaults(func=cmd_worktree_plan)

    p_scan = sub.add_parser("scan", help="run all code quality scanners")
    _add_repo_arg(p_scan, optional=True)
    p_scan.add_argument(
        "--baseline", action="store_true",
        help="snapshot current findings to reports/scan_baseline.json "
             "for new-vs-pre-existing diffing (advisory)",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_strengthen = sub.add_parser(
        "strengthen",
        help="risk-rank untested public symbols (advisory test-gap report)",
        description="Mechanically enumerate the repo's public Python surface "
                    "(AST — no import, no execution), cross-reference each "
                    "symbol against the test tree, and risk-rank the untested "
                    "gaps. Writes an advisory reports/strengthen_report.{json,md}. "
                    "Surfaces where test rails are missing; it never generates "
                    "or commits tests.",
    )
    _add_repo_arg(p_strengthen, optional=True)
    p_strengthen.add_argument(
        "--top-n", type=int, default=20, metavar="N",
        help="show the top N highest-risk untested symbols (default: 20)",
    )
    p_strengthen.add_argument(
        "--skip-fan-in", action="store_true",
        help="skip the fan-in reference count (faster; drops one risk signal)",
    )
    p_strengthen.set_defaults(func=cmd_strengthen)

    p_prov = sub.add_parser(
        "provenance",
        # no help= on purpose: a hidden dev verb (tests/test_cli_commands.py::
        # TestArgparseErrorCuration keeps the twelve out of --help and the
        # invalid-choice list); the ledger row that called this a defect was wrong
        description="Scan the files that ship to users (docs, package source, "
                    "deployed config) for leftover internal development tags "
                    "(e.g. task-pack IDs). Exit 0 = clean, 2 = tags found.",
    )
    _add_repo_arg(p_prov, optional=True)
    p_prov.set_defaults(func=cmd_provenance)

    p_selfcheck = sub.add_parser(
        "selfcheck",
        help="run the bundled host-agnostic engine-integrity tests against the "
             "installed espalier; --contracts runs the three deployed-tree "
             "contracts against REPO instead",
        description="Run the bundled host-agnostic engine-integrity tests against "
                    "the INSTALLED espalier engine. Catches an installed/fused "
                    "engine regressing (a relaxed scanner rule, a broken detector) "
                    "which the presence-based checks cannot see. Builds synthetic "
                    "repos under tmp_path; never reads the adopter repo tree. "
                    "With --contracts, runs the three contracts that DO read the "
                    "deployed tree: the deployed write_guard still denies (C-1), "
                    "the deployed hooks match the installed package (C-2), and "
                    "the live settings carry no kill-switch (C-3).",
    )
    _add_repo_arg(p_selfcheck, optional=True)
    p_selfcheck.add_argument(
        "--contracts",
        action="store_true",
        help="run the three deployed-tree contracts (live deny-path, upstream "
             "parity, live kill-switch) against REPO instead of the bundled tests",
    )
    p_selfcheck.set_defaults(func=cmd_selfcheck)

    # ── Health, cleanup, and release commands ─────────────────────────
    p_doc = sub.add_parser(
        "doctor", help="pre-flight health check (pass/warn/fail)",
        description="Pre-flight health check for the harness install: surface "
                    "inventory, managed-file ownership, hook wiring, and (unless "
                    "--skip-self-host) the self-host contract. Reports pass / warn / fail.",
    )
    _add_repo_arg(p_doc, optional=True)
    _add_config_arg(p_doc)
    p_doc.add_argument("--skip-self-host", action="store_true", help="skip the self-host check for speed")
    p_doc.add_argument(
        "--check-doc-drift", action="store_true",
        help="compare numerical claims in docs (hook count, bypass classes) against live repo state",
    )
    p_doc.add_argument(
        "--mode", choices=("auto", "source-checkout", "initialized"),
        default="auto",
        help=(
            "explicit repo-mode override. 'source-checkout' skips checks "
            "that depend on init-generated runtime files (.claude/settings.json, "
            "reports/*.json, .espalier/integrity.json). 'initialized' forces full "
            "checks. 'auto' (default) detects mode from disk state."
        ),
    )
    p_doc.set_defaults(func=cmd_doctor)

    p_clean = sub.add_parser(
        "clean-generated",
        help="remove all harness-managed files (default: dry-run; pass --execute to delete)",
    )
    _add_repo_arg(p_clean, optional=True)
    p_clean.add_argument(
        "--execute", action="store_true",
        help="actually delete the files (default: dry-run prints what would be deleted)",
    )
    p_clean.set_defaults(func=cmd_clean_generated)

    p_pack = sub.add_parser("release-pack", description="Bundle a distributable release zip.")
    _add_repo_arg(p_pack, optional=True)
    # CLI-3: --out is the canonical artifact-path flag (3/5 majority); --output
    # stays a hidden back-compat alias (same dest, no command-body change).
    p_pack.add_argument("--out", dest="output", default="dist/espalier-harness.zip",
                        metavar="PATH", help="output archive path")
    p_pack.add_argument("--output", dest="output", help=argparse.SUPPRESS)
    p_pack.set_defaults(func=cmd_release_pack)

    p_audit = sub.add_parser(
        "audit-accuracy",
        help="verify documented claims against live repo + pinned externals",
    )
    _add_repo_arg(p_audit, optional=True)
    p_audit.add_argument("--json", action="store_true",
                         help="emit a structured JSON report instead of markdown")
    p_audit.add_argument("--only-failing", action="store_true",
                         help="omit unverifiable + passing sections from the markdown report")
    p_audit.add_argument("--doc", default=None,
                         help="audit a single doc file (path glob relative to repo)")
    p_audit.add_argument("--no-llm", action="store_true",
                         help="no-op compatibility flag: mechanical-only is already the "
                              "default (the LLM-dispatch path is dormant — see "
                              "espalier/audit_accuracy.py). Kept so existing invocations "
                              "still parse; passing it changes nothing.")
    p_audit.set_defaults(func=cmd_audit_accuracy)

    p_refresh = sub.add_parser(
        "refresh-externals",
        description="Refresh docs/external/ pins against canonical URLs.",
    )
    _add_repo_arg(p_refresh, optional=True)
    p_refresh.add_argument("--apply", action="store_true",
                           help="write .candidate.md files for non-none drift and re-run pin-bound tests")
    p_refresh.add_argument("--interactive", action="store_true",
                           help="prompt accept/reject/skip per pin (overwrites pin on accept)")
    p_refresh.add_argument("--pin", default=None,
                           help="refresh only the named pin (e.g. cc-hook-protocol)")
    p_refresh.add_argument("--json", action="store_true",
                           help="emit a structured JSON refresh report instead of the text table")
    p_refresh.set_defaults(func=cmd_refresh_externals)

    # Hidden harness-dev subcommand. The leading underscore in the subcommand
    # name signals "internal" -- not listed in user-facing docs. Run after
    # legitimate edits to write_guard.py.
    p_pin = sub.add_parser(
        # No `help=` (not argparse.SUPPRESS, which renders a literal
        # `==SUPPRESS==` line in `--help` on some argparse versions). Omitting
        # help keeps this `_`-prefixed dev command out of the per-command
        # description rows; the metavar="<command>" on add_subparsers (above)
        # suppresses the auto {choices} brace that would otherwise still name it
        # on the usage line. Both together fully hide it from `--help`, while it
        # stays in `sub.choices` and remains callable.
        "_refresh-self-host-pin",
        description=(
            "Refresh the write_guard.py content pin in "
            "espalier/_self_host_fingerprint.py. Harness-developer only."
        ),
    )
    _add_repo_arg(p_pin, optional=True)
    p_pin.set_defaults(func=cmd_refresh_self_host_pin)

    p_pre = sub.add_parser(
        "pre-release",
        description=(
            "Tier 2 readiness gate. Runs the fast release signal plus "
            "targeted tests. The --skip-* flags exist for narrow debug loops; "
            "any --skip invocation produces fast signal, NOT publish proof — "
            "use scripts/final_release_matrix.py (self-host only — not "
            "deployed by `init`; Tier 3) for tag-readiness."
        ),
    )
    _add_repo_arg(p_pre, optional=True)
    # CLI-3: canonical --out + hidden --output back-compat alias (same dest="output").
    p_pre.add_argument("--out", dest="output", default="dist/espalier-harness.zip",
                       metavar="PATH", help="output archive path")
    p_pre.add_argument("--output", dest="output", help=argparse.SUPPRESS)
    p_pre.add_argument(
        "--skip-tests", action="store_true",
        help="skip targeted test runs (fast signal only; not publish proof)",
    )
    p_pre.add_argument("--skip-pack", action="store_true")
    p_pre.add_argument(
        "--skip-parity", action="store_true",
        help="skip the source-vs-wheel structural parity check "
             "(fast signal only; not publish proof)",
    )
    p_pre.add_argument(
        "--skip-release-check", action="store_true",
        help="skip the release-readiness gate "
             "(scripts/release_check.py — self-host only, not deployed by "
             "`init`)",
    )
    p_pre.set_defaults(func=cmd_pre_release)

    # ── Document freshness ────────────────────────────────────────────
    p_fresh = sub.add_parser(
        "freshness",
        help="document freshness signal (check/pin/unpin fragments)",
        description=(
            "Report or update freshness state for documentation fragments. "
            "See docs/CONVENTIONS.md section 'Document freshness' for the "
            "fragment marker format and pin/unpin workflow."
        ),
    )
    fresh_sub = p_fresh.add_subparsers(
        dest="freshness_action", required=True
    )

    p_fc = fresh_sub.add_parser(
        "check",
        help="report freshness state per fragment",
    )
    _add_repo_arg(p_fc, optional=True)
    p_fc.add_argument(
        "--critical-only", action="store_true",
        help="only print fragments whose state is 'critical'",
    )
    p_fc.add_argument(
        "--json", action="store_true",
        help="emit a structured JSON report instead of the text table",
    )
    p_fc.add_argument(
        "--changed-files", default="",
        help=(
            "Comma-separated list of repo-relative paths to scope "
            "the --critical-only exit decision to; criticals whose "
            "bound paths do not intersect this set are reported but "
            "do not affect exit code. Empty (default) = repo-wide. "
            "Used by the CI gate."
        ),
    )
    p_fc.set_defaults(func=cmd_freshness_check)

    p_fp = fresh_sub.add_parser(
        "pin",
        help="record HEAD as verified for a fragment",
    )
    p_fp.add_argument("fragment_id", nargs="?", default=None)
    _add_repo_arg(p_fp, optional=True)
    p_fp.add_argument(
        "--expected-value", default=None,
        help=(
            "record an expected literal value alongside the pin "
            "(JSON-parsed if possible; numeric-contract policy fragments "
            "only, and needed on their first pin). Omitted, a re-pin "
            "carries the entry's existing literal across an unchanged bound "
            "-- it refreshes the clock, not the number -- and refuses to "
            "carry one whose bound moved or that was edited by hand; "
            "`null` records no literal."
        ),
    )
    p_fp.add_argument(
        "--all", action="store_true",
        help=(
            "pin every discovered fragment to HEAD (bulk seeding "
            "pass; mutually exclusive with --expected-value and "
            "--force; bound-drift cases and bounds with uncommitted "
            "changes are skipped + reported with exit code 1)."
        ),
    )
    p_fp.add_argument(
        "--force", action="store_true",
        help=(
            "consent to a bound-change rebinding (BC-040 pin-time "
            "defense), or to a pin over a bound with uncommitted "
            "changes (HEAD is then not the tree you verified). "
            "Required when the marker's bound differs from the "
            "manifest entry's bound; verify the new bound is correct "
            "before passing this. Mutually exclusive with --all."
        ),
    )
    p_fp.set_defaults(func=cmd_freshness_pin)

    p_fu = fresh_sub.add_parser(
        "unpin",
        help="remove the verification record for a fragment",
    )
    p_fu.add_argument("fragment_id")
    _add_repo_arg(p_fu, optional=True)
    p_fu.set_defaults(func=cmd_freshness_unpin)

    # ── Cognitive system commands ─────────────────────────────────────
    p_rd = sub.add_parser(
        "reflect-deep",
        help="run the full structured reflect protocol (cross-artifact drift)",
        description="Run the full structured reflect protocol.",
    )
    _add_repo_arg(p_rd, optional=True)
    p_rd.add_argument("--json", action="store_true")
    p_rd.add_argument("--pass-number", type=int, default=1)
    p_rd.set_defaults(func=cmd_reflect_deep)

    p_int = sub.add_parser(
        "integrity",
        help="verify/refresh .espalier/integrity.json (verify exits 2 on a "
             "kill-switch; see docs/CLI_EXIT_CODES.md)",
        description="Verify the protected-file manifest (.espalier/integrity.json) "
                    "against disk, or refresh it after intended edits. `verify` exits "
                    "2 on a kill-switch setting, 1 on hash drift, 0 when clean.",
    )
    p_int.add_argument("action", choices=["verify", "refresh"])
    _add_repo_arg(p_int, optional=True)
    p_int.set_defaults(func=cmd_integrity)

    p_ci = sub.add_parser(
        "install-ci", help="install the Harness Guard workflow + ci_guard",
        description="Install the Harness Guard GitHub Actions workflow and ci_guard "
                    "script into the repo, so merges are gated by the same integrity "
                    "and kill-switch checks the local hooks enforce.",
    )
    _add_repo_arg(p_ci, optional=True)
    # The re-baseline must read the same config the adopter baselined with,
    # or install-ci rewrites reports under the DEFAULT config and the next
    # doctor reports the very drift the re-baseline exists to end.
    _add_config_arg(p_ci)
    p_ci.set_defaults(func=cmd_install_ci)

    p_bp = sub.add_parser(
        "blueprint",
        help="cognitive blueprint state operations (the session reasoning chain)",
        description="Advanced cognitive blueprint state operations.",
    )
    _add_repo_arg(p_bp)
    p_bp.add_argument("action", choices=["start", "record", "finalize", "load", "chain"])
    p_bp.add_argument("--kind", choices=["decision", "alternative_rejected", "pattern_discovered", "reflect_insight"])
    p_bp.add_argument("--description", default=None)
    p_bp.add_argument("--evidence", default=None, help="comma-separated evidence items")
    p_bp.add_argument("--fragments", default=None, help="pipe-separated continuation fragments")
    p_bp.add_argument("--json", action="store_true")
    p_bp.set_defaults(func=cmd_blueprint)

    p_rt = sub.add_parser(
        "render-template",
        help="print a canonical CLAUDE.md / ESPALIER_MEMORY.md / CHANGELOG.md template",
    )
    p_rt.add_argument("subject", choices=["claude", "memory", "changelog"])
    p_rt.set_defaults(func=cmd_render_template)

    # Pack scope pre-flight
    p_scope = sub.add_parser(
        "scope-check",
        help="walk the codebase for references to a pack's affected symbols",
        description=(
            "Pre-flight that grounds a pack's Scope (in) in the actual "
            "codebase reference graph. Reports references that fall "
            "outside the pack's declared scope — the operator can either "
            "expand Scope (in) to cover them or acknowledge the gap via "
            "--accept-scope-gap. See docs/PACK_AUTHORING.md for the "
            "Affected symbols section format the pre-flight reads."
        ),
    )
    p_scope.add_argument("pack_path", help="path to the pack markdown file")
    # CLI-1: canonical optional positional repo (metavar REPO); --repo kept as a
    # hidden back-compat alias (same dest). The positional uses default=SUPPRESS so
    # it never clobbers an explicit --repo; the --repo default supplies ".".
    p_scope.add_argument("repo", metavar="REPO", nargs="?",
                         default=argparse.SUPPRESS,
                         help="repo path (default: current dir)")
    p_scope.add_argument("--repo", dest="repo", default=".", help=argparse.SUPPRESS)
    p_scope.add_argument(
        "--matrix",
        default="docs/SURFACE_SUPPORT_MATRIX.md",
        help="path to the surface support matrix for risk tagging",
    )
    p_scope.add_argument(
        "--accept-scope-gap", metavar="REASON", default=None,
        help="acknowledge out-of-scope references with the given reason; "
             "exits 0 instead of 2 when gap is present",
    )
    p_scope.add_argument(
        "--max-refs-per-file", type=int, default=20,
        help="cap per-file ref count in report (default: 20)",
    )
    p_scope.add_argument(
        "--no-ripgrep", action="store_true",
        help="skip ripgrep even if available (use pure-Python walk)",
    )
    p_scope.set_defaults(func=cmd_scope_check)

    p_surface = sub.add_parser(
        "surface-impact",
        help="report the shipped-surface obligations a pack's added or removed files imply",
        description=(
            "Pre-flight (0-D) that reads a pack's declared Added-paths and "
            "Removed-paths (a path-shaped Renamed entry is the removal of its "
            "old name; a new or removed CLI subcommand is detected too), "
            "matches each to its surface, and prints the count pins / mirrors / "
            "hygiene / provenance obligations the full suite will demand once "
            "the files land or leave — a removal names the same sites in "
            "reverse — so the executor can bundle them into the plan up front. "
            "Advisory, like scope-check: exits 2 when a declared path "
            "classifies public (it will ship, or stop shipping), which "
            "--accept-surface-gap acknowledges. See docs/PACK_AUTHORING.md for "
            "the section formats the pre-flight reads."
        ),
    )
    p_surface.add_argument("pack_path", help="path to the pack markdown file")
    p_surface.add_argument("repo", metavar="REPO", nargs="?",
                           default=argparse.SUPPRESS,
                           help="repo path (default: current dir)")
    p_surface.add_argument("--repo", dest="repo", default=".", help=argparse.SUPPRESS)
    p_surface.add_argument(
        "--accept-surface-gap", metavar="REASON", default=None,
        help="acknowledge the public surface additions or removals with the given "
             "reason; exits 0 instead of 2 when public additions or removals are "
             "present",
    )
    p_surface.set_defaults(func=cmd_surface_impact)

    # Pack landing verification
    p_landing = sub.add_parser(
        "verify-landing",
        description=(
            "Parse a pack's '## Files touched' + '## Pass criteria' sections, "
            "extract the backticked path tokens, and classify each against the "
            "repo's git state: LANDED (tracked in HEAD, clean), DRIFTED (tracked "
            "but changed in the working tree), or OWED (not in HEAD). Advisory "
            "tool — prints a table and exits 0; it does not gate. HEAD-only."
        ),
    )
    p_landing.add_argument("pack_path", help="path to the pack markdown file")
    # CLI-1: canonical optional positional repo + hidden --repo alias (positional
    # default=SUPPRESS so it never clobbers an explicit --repo; --repo default=".").
    p_landing.add_argument("repo", metavar="REPO", nargs="?",
                           default=argparse.SUPPRESS,
                           help="repo path (default: current dir)")
    p_landing.add_argument("--repo", dest="repo", default=".", help=argparse.SUPPRESS)
    p_landing.add_argument(
        "--json", action="store_true",
        help="emit the classification as JSON instead of a table",
    )
    p_landing.set_defaults(func=cmd_verify_landing)

    p_bench = sub.add_parser(
        "scaffolding-bench",
        description=(
            "Compute three independent quality signals — continuity, human "
            "reasoning density, and reflect coverage — from the session "
            "blueprints under cc/blueprints/."
        ),
    )
    # CLI-1: canonical optional positional repo; keep --repo as a hidden alias so
    # existing `scaffolding-bench --repo X` still parses (positional default=SUPPRESS
    # so it never clobbers an explicit --repo; --repo default=".").
    p_bench.add_argument("repo", metavar="REPO", nargs="?",
                         default=argparse.SUPPRESS,
                         help="repo path (default: current dir)")
    p_bench.add_argument("--repo", dest="repo", default=".", help=argparse.SUPPRESS)
    p_bench.add_argument(
        "--out", type=Path, default=None,
        help="output JSON path (default: reports/scaffolding_canon.json)",
    )
    p_bench.add_argument(
        "--last", type=int, default=20,
        help="N most recent sessions to analyze (default: 20; 0 = all)",
    )
    p_bench.add_argument(
        "--json", action="store_true",
        help="emit to stdout instead of writing files",
    )
    p_bench.set_defaults(func=cmd_scaffolding_bench)

    p_mem = sub.add_parser(
        "memory",
        help="ESPALIER_MEMORY.md utilities (prune, archive)",
        description=(
            "Operations on ESPALIER_MEMORY.md (the session-log file). Sub-verbs: "
            "prune (archive oldest session-log rows)."
        ),
    )
    mem_sub = p_mem.add_subparsers(
        dest="memory_action", required=True
    )
    p_prune = mem_sub.add_parser(
        "prune",
        help="archive oldest Session Log rows to docs/session-archive.md",
        description=(
            "Move the oldest N Session Log rows from ESPALIER_MEMORY.md into "
            "docs/session-archive.md under a date-stamped heading. "
            "Refuses to leave the Session Log table empty unless "
            "--allow-empty is set. --rows 0 is a no-op smoke."
        ),
    )
    p_prune.add_argument(
        "--rows", type=int, default=1,
        help="number of oldest rows to archive (default: 1; 0 = no-op)",
    )
    p_prune.add_argument(
        "--archive", default=None,
        help="archive destination relative to repo root "
             "(default: docs/session-archive.md)",
    )
    # CLI-1 exception: `memory prune` keeps --root canonical. argparse rejects
    # dest= on a positional (TypeError on 3.14), and renaming the body's
    # args.root is out of scope — so this one command stays flag-based.
    p_prune.add_argument(
        "--root", default=None,
        help="repository root (default: cwd)",
    )
    p_prune.add_argument(
        "--allow-empty", action="store_true",
        help="opt out of the minimum-1-row floor; hook context "
             "uses this so autoprune never blocks on a 1-row Session Log",
    )
    p_prune.add_argument(
        "--keep-newest", type=int, default=0, metavar="N",
        help="reserve the N newest Session Log rows from eviction; not waived "
             "by --allow-empty (default: 0)",
    )
    p_prune.set_defaults(func=cmd_memory_prune)

    # Enumeration-integrity: derive each sub-verb metavar from its registered
    # add_parser choices so the brace list shown in `--help` usage and in the
    # required-arg error can never drift from the actual sub-verbs (a hand-kept
    # literal silently rots when a sibling sub-verb is added). Set AFTER every
    # add_parser() call so any sub-verb above is captured; choices preserve
    # insertion order and neither subparsers action registers aliases, so this
    # equals the primary sub-verb list. metavar=None is NOT equivalent -- it
    # leaks the raw dest in the required-arg error.
    fresh_sub.metavar = "{" + ",".join(fresh_sub.choices) + "}"
    mem_sub.metavar = "{" + ",".join(mem_sub.choices) + "}"

    return parser


# Commands whose job is to wire / extend / validate the harness itself must not
# nudge — for them the source-checkout state is the expected operating state, not
# a misconfiguration. That covers the wiring commands (init, merge-settings,
# upgrade, install-ci, fuse), the mode-aware doctor, and the self-host validators
# (self-host / _refresh-self-host-pin), which operate on a source checkout BY
# DESIGN — nudging them toward `init` would corrupt the very state they check.
# Keyed on the resolved func to avoid depending on the subparser dest.
def _maybe_nudge_source_checkout(args: "argparse.Namespace") -> None:
    """One-line interactive nudge when a command runs in a governed-source
    repo whose hooks aren't wired yet (no .claude/settings.json). TTY-gated so
    it never noises CI logs; reuses repo_mode's exact classifier. _stream_isatty
    is None-safe (closed fd / pythonw), so the gate never raises."""
    if not _stream_isatty(sys.stderr):
        return
    func = getattr(args, "func", None)
    exempt = {
        cmd_init, cmd_merge_settings, cmd_doctor, cmd_upgrade, cmd_install_ci,
        cmd_self_host, cmd_refresh_self_host_pin,
    }
    # cmd_fuse is imported lazily inside build_parser (fuse imports cli), so it
    # is NOT a module global here — resolve the same function object the fuse
    # subparser binds via the live import, mirroring build_parser's try/except.
    try:
        from espalier.fuse import cmd_fuse  # noqa: PLC0415
        exempt.add(cmd_fuse)
    except ImportError:
        pass
    if func in exempt:
        return
    repo = getattr(args, "repo", None)
    if repo is None:
        return
    from espalier.repo_mode import detect_repo_mode, REPO_MODE_SOURCE_CHECKOUT
    try:
        # detect_repo_mode probes the tree with Path.exists(), which can raise
        # PermissionError (an OSError subclass) on permission-restricted paths.
        mode = detect_repo_mode(Path(repo).resolve())
    except OSError:
        return
    if mode == REPO_MODE_SOURCE_CHECKOUT:
        print(
            "espalier: this repo ships the harness but governance is NOT active "
            "on this machine (no .claude/settings.json -- it is per-machine and "
            f"gitignored). Run `{_remedy_py()} -m espalier init {repo}` to wire the hooks.",
            file=sys.stderr,
        )


def _install_clean_warning_format() -> None:
    """Render warnings as a plain ``Warning: <message>`` line on stderr.

    Python's default ``showwarning`` prints the warning's filename, line number,
    and source line. For an installed package that leaks the absolute
    site-packages path plus a raw code line, so a benign degrade (a malformed
    ``espalier.toml`` falling back to defaults, an absent ``--config`` path)
    reads on an adopter's first run like an internal traceback. This keeps the
    ``warnings.warn`` call sites intact (so ``pytest.warns`` capture, dedup, and
    filters still work) and only cleans the terminal rendering. Scoped to
    ``main()`` — a library consumer that imports espalier keeps Python's default.
    """
    def _show(message, category, filename, lineno, file=None, line=None):
        stream = file if file is not None else sys.stderr
        try:
            stream.write(f"Warning: {message}\n")
        except (OSError, AttributeError):
            pass

    warnings.showwarning = _show


def main() -> int:
    _install_clean_warning_format()
    parser = build_parser()
    args = parser.parse_args()
    try:
        _maybe_nudge_source_checkout(args)
        return args.func(args)
    except KeyboardInterrupt:
        # Ctrl+C is BaseException, so the handlers below never saw it: at
        # init's interactive wire prompt it dumped runpy frames over a
        # half-deployed tree (DEF-800; the prompt site says what the tree
        # holds before re-raising here). 130 is the shell's own convention
        # for a SIGINT exit, and one line is what an interrupt earns.
        print("Interrupted.", file=sys.stderr)
        return 130
    except OSError as exc:
        # FileNotFoundError / PermissionError are OSError subclasses;
        # catching the base also gives NotADirectoryError + disk-full OSError a
        # clean "Error: ..." + exit 1 instead of a raw traceback. No behavior
        # lost (json.JSONDecodeError is a ValueError, not an OSError — its
        # distinct message branch stays below).
        print(f"Error: {os_error_text(exc)}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: malformed data -- {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
