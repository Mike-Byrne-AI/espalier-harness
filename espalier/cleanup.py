"""Clean generated CC surface — marker-aware.

The cleanup contract:

- **Managed file (has the espalier:managed marker):** removed.
- **Unmarked file in a managed directory:** preserved and reported.
- **Local runtime state** (settings.json, everything under the harness's
  runtime roots -- the integrity manifest and its write-lock, session flags,
  reports, the blueprint chain): preserved and reported, every file by name.
- **Bytecode cache under the Python-deploy root** (``tools/cc/**/__pycache__``):
  removed -- debris of the scripts just deleted. The one deletion no marker
  can vouch for; scoped to that root so an adopter's own Python elsewhere
  keeps its cache.
- **The harness's own ``.gitignore`` block:** each entry whose guarded path
  is gone after the cleanup is retired; each still guarding a preserved
  runtime file is kept; both lists are reported.
- **Empty managed directory** (after removal pass): removed.

This module reads the unified inventory from
:mod:`espalier.managed_inventory` so init, cleanup, doctor, and
``PACK_MANIFEST`` agree on what Espalier owns.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Any

from espalier._atomic_io import atomic_write_text
from espalier._report_io import load_harness_plan
from espalier._rmtree import remove_file, remove_tree
from espalier._safe_walk import has_git_entry, safe_rglob
from espalier import surface_contract
from espalier.managed_inventory import (
    settings_backup_rung,
    get_install_ci_artifacts,
    get_managed_public_files,
    get_render_artifacts,
    get_seed_docs,
    local_state_on_disk,
)
from espalier.managed_markers import JSON_SENTINEL_KEY, file_carries_marker
from espalier.managed_paths import STATUSLINE_SCRIPT, STATUSLINE_SHIM
from espalier._text import os_error_text

#: The one managed prefix where the harness deploys Python, so the only place
#: a ``__pycache__`` is bytecode of scripts this cleanup deletes. The other
#: managed prefixes hold markdown, and an adopter's Python-backed skill under
#: ``.claude/skills/`` keeps its cache: regenerable, but theirs. Pinned
#: derived by ``tests/test_cleanup.py::TestBytecodeSweep`` (every ``.py`` in
#: the managed inventory lives under this root).
_BYTECODE_SWEEP_ROOT = "tools/cc/"

#: The statusline script ``init`` wires into ``settings.json``'s ``statusLine``
#: (``cli._statusline_command``), and the Windows shim it wires as the head
#: on an nt render (DEF-729). Cleanup deletes both with the rest of
#: ``tools/cc/``, so the wiring must go with them or every prompt render
#: prints the fallback text at the adopter. Pinned against
#: ``STANDARD_MANAGED_TOOLS`` by
#: ``tests/test_cleanup.py::TestSettingsUnwireFinishesTheJob``.
_STATUSLINE_SCRIPT = STATUSLINE_SCRIPT
_STATUSLINE_SHIM = STATUSLINE_SHIM


def _delete_path(path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    # Strict, both arms: an uninstall that left a read-only file behind (an
    # adopter's `attrib +R` on a hook, DEF-734 -- a hook is a FILE, so the
    # second arm is the one that runs for it) must say so, not report a clean
    # teardown over a file that still exists.
    if path.is_dir() and not path.is_symlink():
        remove_tree(path)
    else:
        remove_file(path)


def _load_plan(repo_root: Path) -> dict[str, Any] | None:
    # Uses the shared owner (full error set, not JSONDecodeError-only): cleanup
    # runs this before the delete loop, so a BOM'd / non-UTF-8 harness_config.json
    # must not traceback a state-changing path.
    return load_harness_plan(repo_root)


def _file_is_managed(path: Path) -> bool:
    """True if ``path`` carries the espalier:managed marker.

    Empty / unreadable files default to **not managed** — refuse to
    delete anything we can't positively identify as ours. Delegates to the
    single owner managed_markers.file_carries_marker, which adds an
    exists()/is_file() guard that hardens this delete loop's FIFO edge.
    """
    return file_carries_marker(path)


def _prune_empty_dirs(repo_root: Path, dry_run: bool) -> list[str]:
    """Remove directories that became empty after file deletion.

    Order matters: prune deepest first (skill subdirs before .claude/skills,
    .claude/skills before .claude). The candidate list is ordered
    inner-to-outer so a single pass handles the cascade.
    """
    removed: list[str] = []
    # Collect skill subdirs dynamically so each gets its own candidacy.
    skill_subdirs: list[Path] = []
    skills_root = repo_root / ".claude" / "skills"
    if skills_root.is_dir():
        skill_subdirs = [p for p in skills_root.iterdir() if p.is_dir()]

    candidates = [
        *skill_subdirs,
        repo_root / ".claude" / "commands",
        repo_root / ".claude" / "agents",
        repo_root / ".claude" / "skills",
        repo_root / ".claude",
        repo_root / "tools" / "cc" / "hooks",
        repo_root / "tools" / "cc",
        repo_root / "tools",
        repo_root / "cc" / "blueprints",
        repo_root / "cc",
        repo_root / "reports",
    ]
    for path in candidates:
        if not path.exists() or not path.is_dir():
            continue
        try:
            next(path.iterdir())
            continue  # not empty
        except StopIteration:
            _delete_path(path, dry_run)
            removed.append(str(path.relative_to(repo_root)).replace("\\", "/"))
    return removed


def _unwire_espalier_hooks(repo_root: Path, dry_run: bool) -> list[str]:
    """Strip Espalier's own hook entries from ``.claude/settings.json``.

    Cleanup deletes every ``tools/cc/hooks/*.py`` but PRESERVES settings.json as
    local runtime, which left the adopter wired to scripts that no longer exist:
    a missing script is a non-blocking error (``docs/external/cc-hook-protocol.md``),
    so every subsequent tool call errors while nothing is enforced, and the only
    way out was hand-editing a JSON file the uninstall never mentioned.

    Surgical by construction, because settings.json is ALSO the adopter's own
    file. Only entries the canonical exec-form oracle resolves to a canonical
    Espalier hook script are dropped; an adopter's `permissions`, their own
    hooks, and any wiring shaped differently from what ``init`` writes are left
    exactly as found. A group emptied of Espalier entries is dropped, and an
    event emptied of groups with it, so no hollow scaffolding is left behind.

    Fails SAFE at every uncertainty — absent, unreadable, or non-dict settings
    return ``[]`` and the file is not touched. Losing an adopter's config to an
    uninstall is far worse than leaving one stale entry: cleanup's whole contract
    is that it never destroys what Espalier did not write.

    Three more things ``init`` (or the merge behind ``merge-settings``,
    ``--wire-hooks`` and ``upgrade --execute``, which adds the ``statusLine``
    when the key is absent -- DEF-798) wrote into the file go with the hooks, because
    each one outlived the uninstall on a driven tree (2026-09-11): the
    ``statusLine`` whose command runs ``tools/cc/statusline.py`` or, on an nt
    render, the ``tools/cc/statusline.cmd`` shim at its head (DEF-729; both
    deleted with ``tools/cc/``, so every prompt render printed the fallback
    text), the
    ``_espalier_managed`` sentinel (the file is the adopter's plain settings
    once nothing in it is ours), and a ``hooks`` key emptied by the strip. An
    adopter's own ``statusLine`` -- any command that does not name the
    harness's script -- is left exactly as found. A symlinked
    ``settings.json`` (a dotfiles-managed one) is edited behind the link,
    which stays (``follow_symlinks=True``: the adopter's own file, the same
    keyword init's settings merge and rewire pass).

    Returns the labels removed: ``"<Event>:<script>"`` per hook entry,
    ``"statusLine:<script>"`` and ``"key:_espalier_managed"``. Under
    ``dry_run`` the same labels are returned as the preview of what
    ``--execute`` would strip, and the file is not touched: a preview that
    said nothing about the unwire left the adopter unable to tell it would
    happen.
    """
    # ⚠ NOT the governance oracle's predicate. These are two different
    # questions with OPPOSITE risk polarity, and sharing one predicate between
    # them is how a tightening on one side became a data-loss bug on the other:
    #   "does this entry EXECUTE the gate?"  -> must fail CLOSED (a doubtful
    #      wiring is reported dead), which is `_hook_executes_script_path`.
    #   "is this entry OURS to remove?"      -> must be PERMISSIVE, because a
    #      miss leaves the event wired to a file uninstall is about to delete.
    # Driven: after `type` was tightened in the shared predicate, uninstall on a
    # tree whose espalier entries had lost their `type` removed 0 of 12 entries
    # and left all 10 events pointing at deleted scripts -- verbatim the failure
    # this function's docstring says it exists to prevent. The permissive,
    # path-anchored recognizer is the same one `cli._event_groups_have_espalier_hook`
    # already falls back to for exactly this reason.
    from espalier.surface_contract import (
        _entry_references_script,
        get_canonical_hook_scripts,
    )

    def _espalier_script_named_by(hook: object) -> str | None:
        """Which canonical script this hook entry references, however wired."""
        if not isinstance(hook, dict):
            return None
        for basename in sorted(canonical):
            if _entry_references_script({"hooks": [hook]}, basename):
                return basename
        return None

    settings_path = repo_root / ".claude" / "settings.json"
    if not os.path.isfile(settings_path):  # uniform on every interpreter (DEF-763)
        return []
    try:
        # BOM-tolerant like every other settings reader: a UTF-16 file (Windows
        # PowerShell `Out-File` default) or a UTF-8 BOM used to land in the
        # except below and return [], which reads as "no Espalier hooks here" --
        # so `uninstall` silently left the harness wired into the adopter's
        # settings and reported success.
        settings = json.loads(
            surface_contract.decode_bom(settings_path.read_bytes())
        )
    except (OSError, ValueError):
        return []
    if not isinstance(settings, dict):
        return []

    canonical = set(get_canonical_hook_scripts())
    unwired: list[str] = []
    rebuilt: dict[str, Any] = {}

    hooks = settings.get("hooks")
    for event, groups in (hooks.items() if isinstance(hooks, dict) else ()):
        if not isinstance(groups, list):
            rebuilt[event] = groups  # unrecognised shape: never ours, never touched
            continue
        kept_groups: list[Any] = []
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(entries, list):
                kept_groups.append(group)
                continue
            kept = []
            for hook in entries:
                name = _espalier_script_named_by(hook)
                if name is not None:
                    unwired.append(f"{event}:{name}")
                else:
                    kept.append(hook)
            if kept or not entries:
                kept_groups.append({**group, "hooks": kept} if kept else group)
        if kept_groups:
            rebuilt[event] = kept_groups

    status_line = settings.get("statusLine")
    status_cmd = (
        str(status_line.get("command", "")).replace("\\", "/")
        if isinstance(status_line, dict) else ""
    )
    # The shim head first: a shim-headed command names statusline.py nowhere,
    # and the label should say which file the wiring ran.
    dropped_statusline = next(
        (rel for rel in (_STATUSLINE_SHIM, _STATUSLINE_SCRIPT) if rel in status_cmd),
        None,
    )
    drop_status_line = dropped_statusline is not None
    if dropped_statusline is not None:
        unwired.append(f"statusLine:{dropped_statusline.rsplit('/', 1)[-1]}")
    drop_sentinel = settings.get(JSON_SENTINEL_KEY) is True
    if drop_sentinel:
        unwired.append(f"key:{JSON_SENTINEL_KEY}")

    if not unwired or dry_run:
        return unwired

    if isinstance(hooks, dict):
        if rebuilt:
            settings["hooks"] = rebuilt
        else:
            del settings["hooks"]
    if drop_status_line:
        del settings["statusLine"]
    if drop_sentinel:
        del settings[JSON_SENTINEL_KEY]
    # Load-modify-save: the helper prevents a torn settings.json, not a lost
    # update. Unguarded because the unwire runs once, by the operator, at
    # uninstall; a session racing it is editing a file about to be retired.
    atomic_write_text(
        settings_path, json.dumps(settings, indent=2) + "\n", follow_symlinks=True,
    )
    return unwired


def _is_doomed(rel: str, doomed: set[str]) -> bool:
    """Is ``rel`` (a repo-relative posix path) deleted by this cleanup, either
    by name or because a directory above it is? ``doomed`` holds the report's
    ``deleted`` entries so far: file paths, and under ``--execute`` the pruned
    directories too. Under a dry run the tree has not moved, so this is how
    "gone after the cleanup" is answered without deleting anything."""
    if rel in doomed:
        return True
    parent = rel.rpartition("/")[0]
    while parent:
        if parent in doomed:
            return True
        parent = parent.rpartition("/")[0]
    return False


def _dir_has_survivor(
    directory: Path, repo_root: Path, doomed: set[str]
) -> str | None:
    """The first file under ``directory`` this cleanup leaves behind, as a
    repo-relative posix path, or ``None`` when it leaves none."""
    if not directory.is_dir() or directory.is_symlink():
        return None
    # Sorted, so the witness is the same file on every walk of the same
    # survivors: the preview and the execute walk different trees (the
    # execute has deleted the doomed files by then) and must name one path.
    for path in sorted(safe_rglob(directory)):
        if path.is_file():
            rel = path.relative_to(repo_root).as_posix()
            if not _is_doomed(rel, doomed):
                return rel
    return None


def _survives_anywhere(
    repo_root: Path, name_pattern: str, doomed: set[str], *, want_dir: bool
) -> str | None:
    """For an any-depth gitignore pattern (``*.pyc``, ``__pycache__/``): the
    first match that survives the cleanup somewhere in the adopter's tree, as
    a repo-relative posix path (a file under the directory, for a directory
    pattern), or ``None``. Walks once, stops at the first survivor, never
    enters ``.git`` or a nested repo.
    Otherwise unpruned by design: a ``.venv`` or ``node_modules`` is walked
    (a ``.venv`` full of bytecode reaches the early return at once), and the
    no-survivor worst case measured 0.04 s over 10,800 files -- an uninstall
    pays it at most twice."""
    for dirpath, dirnames, filenames in os.walk(repo_root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if d != ".git" and not has_git_entry(Path(dirpath) / d)
        )
        base = Path(dirpath)
        if want_dir:
            for d in dirnames:
                if fnmatch.fnmatch(d, name_pattern):
                    witness = _dir_has_survivor(base / d, repo_root, doomed)
                    if witness is not None:
                        return witness
        else:
            for name in sorted(filenames):
                if fnmatch.fnmatch(name, name_pattern):
                    rel = (base / name).relative_to(repo_root).as_posix()
                    if not _is_doomed(rel, doomed):
                        return rel
    return None


def _entry_still_guards(
    repo_root: Path, entry: str, doomed: set[str]
) -> str | None:
    """Would retiring required-gitignore ``entry`` expose something this
    cleanup leaves on disk? Answers with the WITNESS: the repo-relative posix
    path of the first surviving file the entry guards, which the report names
    beside the kept entry, or ``None`` when retiring it exposes nothing.

    The witness matters because the entry can be kept for a file the harness
    never wrote: an adopter's own ``.claude/notes.new`` keeps ``.claude/*.new``,
    and until the report said so the line read as kept for a reason it never
    gave (DEF-808, driven on the Windows host, walk 3 leg 5-F).

    Scoped to the pattern shapes ``cli.REQUIRED_GITIGNORE`` contains (pinned
    there by ``test_required_entry_shapes_are_covered``): a root-anchored
    directory (``/reports/``), a root-relative file or one-directory glob
    (``.claude/settings.json``, ``.claude/*.bak.*``), and an unanchored
    single-component pattern that git matches at every depth
    (``__pycache__/``, ``*.pyc``). A multi-component unanchored pattern
    (``cc/blueprints/``) is root-relative in git's grammar too.
    """
    pattern = entry.lstrip("/")
    is_dir_entry = entry.endswith("/")
    body = pattern.rstrip("/")
    any_depth = not entry.startswith("/") and "/" not in body
    if any(c in pattern for c in "*?["):
        if "/" in pattern:
            parent, _, name = pattern.rpartition("/")
            base = repo_root / parent
            if not base.is_dir():
                return None
            try:
                children = sorted(base.iterdir())
            except OSError:
                return None
            for child in children:
                rel = f"{parent}/{child.name}"
                if (
                    child.is_file()
                    and fnmatch.fnmatch(child.name, name)
                    and not _is_doomed(rel, doomed)
                ):
                    return rel
            return None
        return _survives_anywhere(repo_root, pattern, doomed, want_dir=False)
    if is_dir_entry:
        if any_depth:
            return _survives_anywhere(repo_root, body, doomed, want_dir=True)
        return _dir_has_survivor(repo_root / body, repo_root, doomed)
    target = repo_root / pattern
    if target.is_file() and not _is_doomed(pattern, doomed):
        return pattern
    return None


def _retire_gitignore_block(
    repo_root: Path, dry_run: bool, doomed: set[str]
) -> dict[str, Any]:
    """Retire the harness's own ``.gitignore`` entries that nothing needs.

    ``init`` appends a block -- ``cli.GITIGNORE_BLOCK_HEADER``, the
    ``REQUIRED_GITIGNORE`` entries the file lacked, and (since 2026-09-11)
    ``cli.GITIGNORE_BLOCK_FOOTER`` -- and a re-init can append a second such
    block later. Only lines inside those blocks are ever rewritten; a file
    with no header is not ours to edit (an adopter who removed the header
    made the entries theirs), and a block from which nothing is retired is
    not touched at all, an empty header included.

    The block's EXTENT is exact when the footer is present: header to
    footer, whatever stands between. A legacy block has no footer, so its
    extent is inferred -- the contiguous lines after the header that key to
    a required entry, ending at a blank line or EOF. A non-blank line that
    is not one of ours ends it too, but then the edge is uncertain: the line
    may be the adopter's own (appended straight under the block) or an entry
    a later release dropped from ``REQUIRED_GITIGNORE``. Such a block is
    "truncated": its entries are judged as usual but its header is never
    cut, so no line past the uncertain edge is ever read or removed, and
    whatever follows keeps the marker that says where our block began.

    Within a block every entry still guarding something the cleanup leaves
    behind -- the preserved ``settings.json``, ``.espalier/``, ``/reports/``,
    a ``.bak`` -- is kept, so an uninstall never turns preserved runtime
    state into stageable files; every other entry is removed. A block
    emptied that way, footer-delimited or cleanly ended, goes whole with the
    blank line ``init`` wrote above its header; a file left with nothing but
    whitespace was created by ``init`` and is deleted -- unless ``.gitignore``
    is a symlink, which ``init`` never creates: the link is the adopter's
    (a dotfiles checkout), so it stays and the emptied text is written
    through it.

    Both spellings of one entry match, because the compare goes through
    ``cli._gitignore_key``: a tree initialised before the anchoring fix
    carries the bare ``reports/`` for today's ``/reports/`` (DEF-552). The
    file is read as bytes and written through ``atomic_write_text``, so a
    CRLF file comes back CRLF and an interrupted rewrite never leaves a
    truncated ``.gitignore`` behind; a symlinked ``.gitignore`` is edited
    behind the link (``follow_symlinks=True``: the adopter's own file), the
    same file ``init``'s append wrote through -- before it, the retire
    replaced the link with a regular file (DEF-784).

    Returns ``removed`` and ``kept`` (the entries as they stood in the file),
    ``kept_for`` (each kept entry to the surviving path that keeps it -- the
    file an adopter would otherwise have to hunt for, DEF-808; the FIRST
    match in sorted walk order, not the only one, so deleting it retires
    nothing by itself), ``file_deleted`` and ``failure`` (an OSError text, or
    ``None``). ``kept`` lists an entry once per block that carries it (a
    re-init can append a second block); ``kept_for`` keys it once. The two
    agree as sets, never by length. Under
    ``dry_run`` the verdicts are computed against ``doomed`` -- the paths the
    execute would delete -- and the file is not touched; the two agree
    except after a delete FAILURE, where the execute keeps the entry that
    guards the file it could not remove.
    """
    # Lazy, and load-bearing in both directions: ``cli`` imports this module
    # at load, so a top-level import here would be circular, and ``cli``
    # defines the gitignore constants far below its own import of ``cleanup``,
    # so even a guarded top-level import could read them before they exist.
    # Resolved at call time, when both modules are complete.
    from espalier.cli import (
        GITIGNORE_BLOCK_FOOTER,
        GITIGNORE_BLOCK_HEADER,
        REQUIRED_GITIGNORE,
        _gitignore_key,
    )

    result: dict[str, Any] = {
        "removed": [], "kept": [], "kept_for": {},
        "file_deleted": False, "failure": None,
    }
    gitignore = repo_root / ".gitignore"
    if not gitignore.is_file():
        return result
    try:
        # Bytes, not universal newlines: each line keeps its own terminator,
        # so a CRLF file is rewritten CRLF.
        text = gitignore.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return result
    lines = text.split("\n")
    required = {_gitignore_key(entry): entry for entry in REQUIRED_GITIGNORE}
    header_at = [
        i for i, line in enumerate(lines)
        if line.strip() == GITIGNORE_BLOCK_HEADER
    ]
    if not header_at:
        return result

    removed: list[str] = []
    kept: list[str] = []
    kept_for: dict[str, str] = {}
    for start in reversed(header_at):
        end = start + 1
        footer_at: int | None = None
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped == GITIGNORE_BLOCK_FOOTER:
                footer_at = end
                break
            if not stripped or _gitignore_key(stripped) not in required:
                break
            end += 1
        entries_end = footer_at if footer_at is not None else end
        truncated = (
            footer_at is None and end < len(lines) and bool(lines[end].strip())
        )
        surviving: list[str] = []
        block_removed = False
        for line in lines[start + 1:entries_end]:
            entry = required[_gitignore_key(line.strip())]
            witness = _entry_still_guards(repo_root, entry, doomed)
            if witness is not None:
                kept.append(line.strip())
                kept_for[line.strip()] = witness
                surviving.append(line)
            else:
                removed.append(line.strip())
                block_removed = True
        if not block_removed:
            continue
        if surviving or truncated:
            lines[start + 1:entries_end] = surviving
            continue
        block_end = footer_at + 1 if footer_at is not None else end
        cut_from = start - 1 if start > 0 and not lines[start - 1].strip() else start
        del lines[cut_from:block_end]

    result["kept"] = sorted(kept)
    result["kept_for"] = dict(sorted(kept_for.items()))
    if not removed:
        return result
    result["removed"] = sorted(removed)
    new_text = "\n".join(lines)
    # An emptied file init created is deleted. An emptied file behind a
    # symlink is the adopter's -- init never creates a link -- so the link
    # stays and the emptied text goes through it; unlinking here would sever
    # the one thing at this path that is theirs.
    result["file_deleted"] = not new_text.strip() and not gitignore.is_symlink()
    if dry_run:
        return result
    try:
        if result["file_deleted"]:
            remove_file(gitignore)
        else:
            atomic_write_text(gitignore, new_text, follow_symlinks=True)
    except OSError as exc:
        result["failure"] = f".gitignore: {os_error_text(exc)}"
        result["file_deleted"] = False
    return result


def clean_generated_surface(
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove all harness-managed files. Returns a classified report.

    The report's contract is that every file the harness put on disk and
    leaves behind is NAMED in some bucket, so an adopter reconciling it
    against ``ls`` can tell a deliberately kept file from a forgotten one.
    Driven 2026-09-11 (DEF-410d): before the runtime roots were accounted by
    prefix, the integrity manifest's write-lock and the appended
    ``.gitignore`` block survived an uninstall in no bucket at all.

    Report keys (classifications):

    - ``deleted`` — managed files removed (or that would be removed in
      dry-run), the bytecode caches under a managed prefix, plus empty dirs
      pruned. Directory pruning is reported only
      under ``--execute``: in dry-run nothing is actually deleted, so
      candidate dirs still contain their files and are not listed as pruned
      (the file list previews correctly; the dir teardown is shown on execute).
      ``.gitignore`` appears here when retiring the harness's block left it
      empty.
    - ``already_missing`` — managed files in the inventory not present
      on disk.
    - ``preserved_user_files`` — files in managed directories that
      lacked the ``espalier:managed`` marker; left in place. The adopter's
      pre-merge ``settings.json.bak`` copies land here (their bytes, never
      deleted), and so does ``.gitignore`` while it still carries harness
      entries that guard preserved runtime state.
    - ``settings_backups_kept`` — the ``settings.json.bak`` / ``.bak.N``
      copies a wire took of the adopter's own settings, in ladder order.
      Each is also under ``preserved_user_files``; this view exists so the
      count is visible at a glance. One copy per distinct content: a re-wire
      over bytes an existing copy already holds adds none (DEF-809).
    - ``preserved_local_runtime`` — every present file the harness's runtime
      wrote outside the deployed surface (``settings.json``, everything under
      ``.espalier/``, ``.espalier-state/``, ``reports/`` and
      ``cc/blueprints/``, the per-session local-only files), which the
      cleanup deliberately does not touch. Read from
      ``managed_inventory.local_state_on_disk``, the same owner ``init``'s
      untracked-conflict advisory reads.
    - **Install-ci artifact** (``ci_guard.py``, ``harness-guard.yml``, and the
      ``harness-guard.yml.new`` twin): accounted for by marker — marked
      removed, unmarked preserved and reported (never silently orphaned).
    - ``unwired_hooks`` — what was stripped from ``settings.json`` (or, under
      dry-run, what would be): each Espalier hook entry, the harness
      ``statusLine`` and the managed sentinel. See ``_unwire_espalier_hooks``.
    - ``gitignore_entries_removed`` / ``gitignore_entries_kept`` — the
      harness's own ``.gitignore`` entries retired because nothing they
      guarded survives, and those kept because something does. See
      ``_retire_gitignore_block``.
    - ``gitignore_entries_kept_for`` — for each kept entry, the surviving
      path that keeps it (the first one found), so a line kept for a file the
      harness never wrote -- an adopter's own ``.claude/notes.new`` under
      ``.claude/*.new`` -- is explained rather than left to be hunted for
      (DEF-808, driven on the Windows host, walk 3 leg 5-F).
    - ``failures`` — paths that errored during deletion.
    - ``status`` — ``"fail"`` if any failure, else ``"pass"``.
    """
    repo_root = repo_root.resolve()
    deleted: list[str] = []
    missing: list[str] = []
    failures: list[str] = []
    preserved_user: list[str] = []

    plan = _load_plan(repo_root)
    managed = get_managed_public_files(repo_root, plan)
    runtime_set = set(local_state_on_disk(repo_root))

    for rel_path in managed:
        target = repo_root / rel_path
        if not target.exists():
            missing.append(rel_path)
            continue
        if target.is_dir():
            continue
        # Marker check before deletion. Anything without the
        # ownership marker is treated as a user file regardless of
        # which inventory bucket it appears in.
        if not _file_is_managed(target):
            preserved_user.append(rel_path)
            continue
        try:
            _delete_path(target, dry_run)
            deleted.append(rel_path)
        except OSError as exc:
            failures.append(f"{rel_path}: {os_error_text(exc)}")

    # Scan managed prefixes for files NOT in the inventory but inside
    # directories where Espalier deploys content.
    # - Files WITH the managed marker are legacy harness-managed files
    #   (e.g., from an older init that deployed commands/agents/skills).
    #   They are no longer in the inventory, but clean-generated must
    #   still remove them so users can fully undo an old init.
    # - Files WITHOUT the marker are user-authored; preserved.
    inventory_set = set(managed)
    user_only_prefixes = (".claude/commands/", ".claude/skills/", ".claude/agents/")
    for prefix in user_only_prefixes:
        prefix_dir = repo_root / prefix.rstrip("/")
        if not prefix_dir.is_dir():
            continue
        for file_path in safe_rglob(prefix_dir):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(repo_root).as_posix()
            if rel in inventory_set:
                continue  # already classified above
            if _file_is_managed(file_path):
                # Legacy managed file (not in current inventory) -- delete it
                try:
                    _delete_path(file_path, dry_run)
                    deleted.append(rel)
                except OSError as exc:
                    failures.append(f"{rel}: {os_error_text(exc)}")
            else:
                preserved_user.append(rel)

    # Bytecode caches under the Python-deploy root are debris of the scripts
    # just deleted: `tools/cc/hooks/__pycache__/` fills the first time a hook
    # runs, nothing in the inventory names it, and a non-empty directory is
    # never pruned -- so on any tree that had a session, `tools/` outlived the
    # uninstall holding nothing but .pyc files, in no report bucket. Deleted by
    # directory name, the one place this module removes something no marker
    # can identify: a .pyc cannot carry one, the cache is regenerable, and
    # REQUIRED_GITIGNORE already ignores it. Scoped to _BYTECODE_SWEEP_ROOT so
    # an adopter's own Python under another managed prefix keeps its cache.
    sweep_root = repo_root / _BYTECODE_SWEEP_ROOT.rstrip("/")
    if sweep_root.is_dir():
        for cache_dir in sorted(safe_rglob(sweep_root, "__pycache__")):
            if not cache_dir.is_dir() or cache_dir.is_symlink():
                continue
            rel = cache_dir.relative_to(repo_root).as_posix()
            try:
                _delete_path(cache_dir, dry_run)
                deleted.append(rel)
            except OSError as exc:
                failures.append(f"{rel}: {os_error_text(exc)}")

    # The render artifacts init and merge-settings write BESIDE settings.json
    # (managed_inventory.get_render_artifacts -- the same owner init's
    # untracked-conflict advisory reads, DEF-737). They are not in the managed
    # inventory and live outside the user_only_prefixes scanned above, so they
    # must be accounted here or they orphan after an uninstall.
    # - `.claude/settings.json.new` is the inert template init renders when it
    #   declines to overwrite an existing settings.json. Remove the harness-
    #   rendered one (it carries the _espalier_managed JSON sentinel); preserve
    #   a file lacking it (a hand-saved file).
    # - `.claude/settings.json.bak` and `.bak.N` are merge-settings' copies of
    #   the adopter's OWN pre-merge settings -- their bytes, so preserved and
    #   named, never deleted.
    # The harness's OTHER `.new` -- `.github/workflows/harness-guard.yml.new`,
    # written by cli.py::cmd_install_ci -- is a YAML file with no JSON sentinel;
    # it is reconciled by the install-ci-artifact block below via the text
    # marker (get_install_ci_artifacts).
    render_artifacts = get_render_artifacts(repo_root)
    for rel in render_artifacts:
        artifact = repo_root / rel
        if not rel.endswith(".new"):
            preserved_user.append(rel)
            continue
        try:
            # bom-exempt: the `.new` template is what this tool rendered and
            # wrote itself, so it is our own UTF-8 output rather than a file any
            # editor or shell has touched.
            data = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict) and data.get(JSON_SENTINEL_KEY) is True:
            try:
                _delete_path(artifact, dry_run)
                deleted.append(rel)
            except OSError as exc:
                failures.append(f"{rel}: {os_error_text(exc)}")
        else:
            preserved_user.append(rel)

    # Seed scaffolds live OUTSIDE the managed inventory AND outside the
    # user_only_prefixes scanned above, so without this block a present seed is
    # absent from every report bucket and an operator reconciling the report
    # against the tree can't account for it. The population is get_seed_docs()
    # -- derived at runtime; do NOT enumerate it here, and do NOT state its
    # size. An enumeration in a comment is a drift class, and so is a bare
    # count of one: this comment used to name three files and conclude "all
    # three" long after the derived set had outgrown them, so a maintainer
    # reasoning about teardown from it reasoned about a fraction of the real
    # population. Same owner as the deploy loop (managed_inventory.
    # get_seed_docs) — the two cannot drift. Classify by the same marker check
    # the inventory loop uses: unmarked -> preserved_user (today's honest
    # outcome for every seed); marked -> deleted (honours the ownership
    # contract if a future asset ever gains a marker). Absent seeds are
    # skipped (nothing to reconcile), mirroring the settings.json.new block above.
    for rel in get_seed_docs():
        seed_target = repo_root / rel
        if not seed_target.is_file():
            continue
        if _file_is_managed(seed_target):
            try:
                _delete_path(seed_target, dry_run)
                deleted.append(rel)
            except OSError as exc:
                failures.append(f"{rel}: {os_error_text(exc)}")
        else:
            preserved_user.append(rel)

    # install-ci (cli.py::cmd_install_ci) writes ci_guard.py + harness-guard.yml
    # (+ the conditional harness-guard.yml.new parity twin) OUTSIDE the managed
    # inventory, outside user_only_prefixes, and outside the settings.json.new
    # block above -- so without this loop a present install-ci artifact is absent
    # from every report bucket and an uninstall silently orphans it.
    # get_install_ci_artifacts is a hand-maintained MIRROR of cmd_install_ci's
    # write set (cmd_install_ci does not read it); the two are kept in sync by hand
    # and pinned by test_cleanup.py::TestInstallCiArtifactDriftPin (real cmd_install_ci
    # -> observed writes == the tuple), so a future 4th install-ci write cannot
    # silently escape this loop. Classify by the same marker check the inventory loop uses:
    # marked -> deleted (honours the ownership contract if an artifact ever gains a
    # marker); unmarked -> preserved_user (today's honest outcome -- the shipped
    # ci_guard.py / harness-guard.yml carry no marker, so they are reported for the
    # operator to remove, never silently dropped). Absent artifacts are skipped,
    # mirroring the settings.json.new and seed-doc blocks above.
    for rel in get_install_ci_artifacts():
        artifact_target = repo_root / rel
        if not artifact_target.is_file():
            continue
        if _file_is_managed(artifact_target):
            try:
                _delete_path(artifact_target, dry_run)
                deleted.append(rel)
            except OSError as exc:
                failures.append(f"{rel}: {os_error_text(exc)}")
        else:
            preserved_user.append(rel)

    pruned = _prune_empty_dirs(repo_root, dry_run)
    deleted.extend(pruned)

    unwired = _unwire_espalier_hooks(repo_root, dry_run)

    # Last, on the tree as the cleanup leaves it (or, under dry-run, against
    # the paths it would delete): retire the harness's own .gitignore entries
    # that no surviving file needs, keep the ones that guard preserved runtime
    # state, and name the file in the bucket that matches what was done to it.
    gitignore = _retire_gitignore_block(repo_root, dry_run, set(deleted))
    if gitignore["failure"]:
        failures.append(gitignore["failure"])
    elif gitignore["file_deleted"]:
        deleted.append(".gitignore")
    elif gitignore["kept"] or gitignore["removed"]:
        # Kept entries, or a rewrite that removed every entry but left the
        # file (an emptied .gitignore behind a symlink): the file is on disk
        # and the adopter's, so it is named here rather than in no bucket.
        preserved_user.append(".gitignore")

    return {
        "repo_root": str(repo_root),
        "status": "fail" if failures else "pass",
        "dry_run": dry_run,
        "deleted": sorted(deleted),
        "already_missing": sorted(set(missing)),
        "preserved_user_files": sorted(set(preserved_user)),
        "preserved_local_runtime": sorted(runtime_set),
        # The pre-merge copies of the adopter's own settings.json, in ladder
        # order (the grammar is managed_inventory.settings_backup_rung: one
        # spelling for the predicate, the wire's scan and this listing) so a
        # reader sees at a glance how many remain. Each is theirs (preserved
        # above); a wire writes one only for bytes no rung holds (DEF-809).
        "settings_backups_kept": [
            rel for _, rel in sorted(
                (rung, rel)
                for rel in render_artifacts
                for rung in (settings_backup_rung(rel.rpartition("/")[2]),)
                if rung is not None
            )
        ],
        "unwired_hooks": unwired,
        "gitignore_entries_removed": gitignore["removed"],
        "gitignore_entries_kept": gitignore["kept"],
        "gitignore_entries_kept_for": gitignore["kept_for"],
        "failures": failures,
    }
