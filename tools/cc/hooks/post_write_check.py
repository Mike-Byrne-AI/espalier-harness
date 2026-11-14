#!/usr/bin/env python3
"""PostToolUse hook — validates writes to harness infrastructure files.

Advisory only (always exits 0): its findings ride the one JSON object it prints.
Triggers on: .claude/settings.json, .claude/agents/*.md, .claude/commands/*.md,
             tools/cc/**/*.py, root .md files (CLAUDE.md, ESPALIER_MEMORY.md, etc.)
On the harness's own tree it also reads any .py file a Write or an Edit just
left, wherever the file sits, for the 2026-09-17 incident's driver shape
(``driver_shape_advisory``).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _integrity  # noqa: E402
import _hook_utils  # noqa: E402
import _reinject  # noqa: E402

# SoT for cc/ path strings. Lives one directory up at tools/cc/_paths.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _paths  # noqa: E402
from _json_safe import decode_bom, decode_text_or_problem, os_error_text  # noqa: E402

PLACEHOLDERS = ["<repo>", "<fill>", "INSERT HERE", "TEMPLATE_ONLY"]

# ESPALIER_MEMORY.md autoprune contract.
# Pinned to ``tests/test_documented_claims.py``'s ``ESPALIER_MEMORY.md line cap``
# NumericContract (expected_value=120). If the cap changes, update that
# contract — this constant binds to it. ``_AUTOPRUNE_HEADROOM`` keeps
# the file at ``cap - headroom`` after a prune so a subsequent single-row
# append doesn't immediately re-trip the cap.
_MEMORY_MD_CAP = 120
_AUTOPRUNE_HEADROOM = 1

# ⚠ TRAP FOR ANYONE ADDING AN EVENT-LEVEL BUDGET HERE. The guard below is
# ``line_count <= _MEMORY_MD_CAP: return``, so by the time ``excess`` is computed
# it is at least ``_AUTOPRUNE_HEADROOM + 1`` -- i.e. at least 2 today, on EVERY
# invocation. A "this is more than routine session turnover" advisory keyed on a
# LITERAL threshold was designed on 2026-08-20 and killed on that measurement: at
# 1 it is unreachable dead code, at 2 it fires on every routine /handoff. If such
# a budget is ever wanted, DERIVE it (``_AUTOPRUNE_HEADROOM + 1``) and have its
# test assert the RELATION to the headroom -- an assertion of ``>= 1`` is green at
# both the broken value and the correct one, which is how the first draft passed.
# Note also that ``excess`` is a LINE delta consumed as a ROW count; the verb
# reconciles that and reports any shortfall, so do not re-derive it here.

# Committed project-memory filename, routed through one per-file constant so a
# future rename is a value flip. Per-file (not a shared import) — tools/cc scripts
# run standalone; adding a sibling import risks the copy-subset footgun.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

ALLOWLISTED_WRITE_PATHS = {
    _MEMORY_FILENAME,
    _paths.COMMANDS_INDEX_REL,
    _paths.LIVE_SURFACE_REL,
    _paths.PACK_MANIFEST_REL,
    "cc/execution_plan.json",
}
ALLOWLISTED_WRITE_PREFIXES = (
    _paths.BLUEPRINTS_DIR_REL + "/",
    "reports/",
    "tests/",
)


def _is_allowlisted(rel_path: str) -> bool:
    if rel_path in ALLOWLISTED_WRITE_PATHS:
        return True
    for prefix in ALLOWLISTED_WRITE_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    return False


def _integrity_spot_check(repo_root: Path, rel_path: str) -> None:
    """Re-run integrity verification and warn on drift. Never blocks."""
    ok, mismatched = _integrity.verify_integrity(repo_root)
    if ok:
        return
    # Suppress the noisy ABSENT case — no manifest just means the user hasn't
    # initialized integrity yet. A manifest that is present but unusable is NOT
    # suppressed: it reports as MANIFEST_UNREADABLE and falls through to the
    # warning below.
    if mismatched == [_integrity.MANIFEST_ABSENT]:
        return
    _integrity.append_audit(
        repo_root,
        {"event_type": "post_write_integrity_drift",
         "details": {"triggered_by": rel_path, "mismatched": mismatched}},
    )
    _hook_utils.advise_warn(f"integrity drift after write to {rel_path}: {', '.join(mismatched)}")


def _memory_section_lines(text: str) -> "list[tuple[str, int]]":
    """[(section title, line count)] for each ``## `` section, largest first.

    The cap is measured over the WHOLE file while ``espalier memory prune`` only
    ever evicts rows from the Session Log, so growth in any other section is paid
    for out of session history -- an 8-line addition to a pointer section near the
    top of the file once archived eight July session rows, and nobody editing a
    prose section predicts that. A message that reports "still over cap" without
    naming which section is fat mis-attributes the cost to the log.

    Lines before the first ``## `` belong to a synthetic "(preamble)" section so
    the counts sum to the file and a fat header cannot hide.
    """
    sections: "list[tuple[str, int]]" = []
    title, count = "(preamble)", 0
    fence: "str | None" = None
    for line in text.splitlines():
        # Fence tracking, because a ``## `` inside a code block is prose ABOUT a
        # heading, not one. Measured harm today is mild -- the phantom section is
        # always a sub-range of its parent, so the operator is pointed at the right
        # region under a wrong label -- and the trigger population in this repo's
        # own ESPALIER_MEMORY.md is zero across 363 revisions. Handled anyway
        # because it is two lines and the shipped adopter template is not this repo.
        # The grammar is _hook_utils.next_fence_state, shared with every other
        # ``## `` reader in the hook stack (a backtick-only toggle lived here).
        fenced = fence is not None
        fence = _hook_utils.next_fence_state(line, fence)
        if line.startswith("## ") and not fenced:
            sections.append((title, count))
            title, count = line[3:].strip(), 1
        else:
            count += 1
    sections.append((title, count))
    return sorted(sections, key=lambda pair: -pair[1])


def _read_memory_text(memory_path: Path) -> str | None:
    """ESPALIER_MEMORY.md as text, decoded through ``decode_text_or_problem`` --
    the file is hand-edited at every handoff, so a UTF-8 or UTF-16 byte-order
    mark from an editor or a PowerShell re-encode reads as text instead of
    raising (the strict reads here had no local handler, so the hook's
    umbrella printed a traceback line and the autoprune never ran; DEF-797).
    Bytes that are neither, or a byte-order-mark-less UTF-16 file (NUL-laden
    once decoded), are named in the hook's advisory (stderr keeps the debug
    copy) in the helper's sentence, with the encoding to re-save in, and
    ``None`` comes back so the caller stands down."""
    text, problem = decode_text_or_problem(memory_path.read_bytes())
    if problem:
        _hook_utils.advise_warn(f"ESPALIER_MEMORY.md is {problem}; the autoprune cannot count its lines")
        return None
    return text


#: An interpreter's own words for having no engine to run: runpy's for ``-m
#: espalier.cli`` (unquoted, with or without ``.cli``) and the import system's
#: (quoted). Bound to the engine's name, so a missing dependency of an engine
#: that did start (a stale ``.pth``, a plugin) is a refusal, never a reason to
#: try another install. ``tools/cc/record_merge.py`` keeps the same pattern.
_NO_ENGINE_RE = re.compile(r"No module named '?espalier(\.cli)?'?(?![\w.])")


def _maybe_autoprune_memory(repo_root: Path, rel_path: str) -> None:
    """If the just-written file is ESPALIER_MEMORY.md and now exceeds the cap,
    invoke ``espalier memory prune`` to archive the oldest Session Log
    row(s). Never blocks; says what it did in the hook's advisory, the
    additionalContext of its one JSON object (stderr keeps the debug copy).

    Runs this interpreter's own module first (``sys.executable -m
    espalier.cli``): the hook runs under the interpreter Claude Code's
    settings wired at ``init``, so its module is the engine installed for
    this tree, and an ``espalier`` elsewhere on PATH, newer or older, is not
    the engine of record. The PATH ``espalier`` is the one rung below it, for
    an install whose engine lives in a tool venv the wired interpreter cannot
    import (pipx, uv tool), and it runs only when the module rung answered
    that it has no such module (``_NO_ENGINE_RE``, the engine's own name) or
    raised (could not start, or timed out, as before); an engine that ran
    and refused is final, since the PATH binary is whatever install answers
    the name first, not a second opinion. Until DEF-4091 the PATH binary came
    first "for production speed" (both rungs spawn a Python, so the order
    bought none), and the dirty-machine cell's stale ``espalier`` pruned the
    tree's record in the wired engine's place, or exited 0 and pruned
    nothing. Subprocess only -- no espalier IMPORT here, per the
    ``tools/cc/`` isolation rule.
    """
    import shutil
    import subprocess

    if rel_path != _MEMORY_FILENAME:
        return

    memory_path = repo_root / _MEMORY_FILENAME
    if not memory_path.is_file():
        return

    text = _read_memory_text(memory_path)
    if text is None:
        return
    line_count = len(text.splitlines())
    if line_count <= _MEMORY_MD_CAP:
        return

    excess = line_count - _MEMORY_MD_CAP + _AUTOPRUNE_HEADROOM
    # This interpreter's module first, the PATH binary below it (the
    # docstring says why, and when the lower rung runs).
    invocations: list[list[str]] = [[sys.executable, "-m", "espalier.cli"]]
    espalier_bin = shutil.which("espalier")
    if espalier_bin is not None:
        invocations.append([espalier_bin])

    # Self-host bridge: when this hook lives co-located with an
    # ``espalier/`` source tree (the espalier-harness repo itself), add
    # that source root to PYTHONPATH so ``python -m espalier.cli`` finds
    # the package even when the running Python lacks espalier in its
    # site-packages. Production adopters do not have ``espalier/`` next
    # to ``tools/cc/`` -> branch is a no-op for them.
    #
    # Drop any inherited ``PYTHONPATH`` first: a developer with multiple
    # espalier checkouts open (each Claude session under one repo) could
    # otherwise resolve ``espalier`` from an unrelated checkout's source
    # tree. The hook must run the espalier shipped with this repo, not
    # whichever one happens to be on the parent shell's PYTHONPATH.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    # magic-depth: ok hooks live at tools/cc/hooks/<file>.py, so depth=3 is the repo root
    self_host_root = Path(__file__).resolve().parents[3]
    if (self_host_root / "espalier" / "__init__.py").is_file():
        env["PYTHONPATH"] = str(self_host_root)

    last_error = ""
    for base in invocations:
        cmd = base + [
            "memory", "prune",
            "--rows", str(excess),
            "--root", str(repo_root),
            # Hook context is non-blocking by design; never refuse
            # to fix an over-cap ESPALIER_MEMORY.md just because Session Log has
            # only 1 row. Direct CLI users keep the safety default.
            "--allow-empty",
            # ...but --allow-empty alone archives the row the operator just
            # wrote when the log holds exactly one. ESPALIER_MEMORY.md's own
            # pruning policy already promises "the newest rows are always kept";
            # this closes the gap between that shipped sentence and the code.
            # Reserving the newest row can leave the file over cap, which is the
            # deliberate trade -- the residual-over-cap warning below reports it
            # rather than paying for headroom with the newest row.
            "--keep-newest", "1",
        ]
        try:
            result = _hook_utils.run_bounded(  # spawn: ok the autoprune's own two-rung engine ladder and warning above; a reporter
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, env=env
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {os_error_text(exc)}"
            continue
        if result.returncode == 0:
            after = _read_memory_text(memory_path)
            if after is None:
                return
            new_count = len(after.splitlines())
            # `excess` is a LINE-count delta but `memory prune`
            # consumes it as a SESSION-LOG-ROW count. When the bloat lives in the
            # permanent Decisions/Patterns tables (not the Session Log), pruning
            # log rows cannot bring the file under cap — the prune "succeeds" yet
            # the file stays over cap, and the success line below would mask it
            # behind a silent exit 0. Make the residual over-cap state OBSERVABLE.
            # (The structural fix — capping the permanent tables in parity with
            # cognitive_blueprint's truncate-to-cap — is the owed ESPALIER_MEMORY.md
            # spin-out TP, deliberately not bundled here.)
            if new_count > _MEMORY_MD_CAP:
                census = _memory_section_lines(after)
                fattest = ", ".join(
                    f"{title} ({count} lines)" for title, count in census[:3]
                )
                _hook_utils.advise_warn(
                    f"ESPALIER_MEMORY.md autoprune ran ({line_count} -> {new_count} lines) "
                    f"but the file is STILL over the {_MEMORY_MD_CAP}-line cap -- "
                    f"the excess is not in the Session Log ROWS. Largest sections: "
                    f"{fattest}. Trim the fattest one, or spin the permanent "
                    f"tables out; pruning more log rows cannot help."
                )
                return
            # Carry the verb's own line through verbatim: it names the DATES of
            # the rows that left, and the archive is gitignored, so this is the
            # only place anyone learns which sessions were evicted -- which is
            # why it rides the hook's JSON object: on stderr alone it reached the
            # debug log and nobody (the protocol pin; exit 0).
            #
            # ⚠ Keep the LITERAL "docs/session-archive.md" in the sentence below.
            # The verb's stdout names the path too, but only at runtime, and
            # tests/test_adopter_pointer_resolution.py::_NOT_POINTERS carries a
            # declared non-pointer row keyed to this file naming that exact path.
            # Dropping the literal kills that row (driven: it reported the
            # exemption as matching nothing) and leaves the operator with no path
            # at all on the branch where stdout comes back empty.
            detail = result.stdout.strip().splitlines()
            _hook_utils.advise(
                f"[post_write_check] ESPALIER_MEMORY.md autoprune: "
                f"{line_count} -> {new_count} lines "
                f"(archived to docs/session-archive.md; requested "
                f"{_hook_utils.plural(excess, 'row')}"
                + (f" -- {detail[-1]}" if detail else "")
                + ")",
            )
            return
        last_error = (
            f"rc={result.returncode} stderr={result.stderr.strip()}"
        )
        if not _NO_ENGINE_RE.search(result.stderr or ""):
            break   # the engine ran and refused: the PATH binary is not a second opinion

    _word = getattr(_hook_utils, "executable_word", lambda: sys.executable)()
    _hook_utils.advise_warn(
        f"ESPALIER_MEMORY.md autoprune failed: {last_error} "
        f"(file remains at {line_count} lines, cap={_MEMORY_MD_CAP}; "
        # getattr: a kept older _hook_utils.py lacks these names (DEF-2062), and
        # this note must not become a traceback in its place.
        f"run `{_word} -m espalier memory prune "
        f"--rows {excess} --root {getattr(_hook_utils, 'quoted_if_spaced', str)(str(repo_root))} "
        f"--allow-empty --keep-newest 1` by hand"
        f"{getattr(_hook_utils, 'powershell_call_note', lambda _w: '')(_word)})"
    )


def _check_session_log_fragment(repo_root: Path, rel_path: str) -> None:
    """After a write of a Session Log fragment (``memory/session-log.d/``), read
    the written file back and say what every reader would mishandle. Nothing is
    pruned here: until 2026-10-16 this archived and deleted the oldest fragments
    past the cap at every write, so each lane kept the count in its own tree and
    two lanes each at 30 merged to 31 on main; the cap's one writer is the fold
    a lane's push runs (``tools/cc/ship.py``, DEF-5007). In-process through the
    one loader (a ``tools/cc`` sibling, not the engine), so no interpreter
    ladder. Never blocks."""
    if not rel_path.startswith("memory/session-log.d/"):
        return
    fragments = _hook_utils.load_record_fragments()
    if fragments is None:
        # A fragment was written and nothing here can check its name: said, as
        # the SessionStart digest says it beside the same directory (review of
        # #179: this returned in silence).
        _hook_utils.advise_warn(
            f"{rel_path} was written but no Session Log fragment was checked: "
            + (_hook_utils.RECORD_FRAGMENTS_LOAD_ERROR
               or "tools/cc/_record_fragments.py is not beside the hooks")
        )
        return
    # The written file itself: a name the loader does not read, or a file that
    # is not one row, is skipped or half-archived by every reader from now on,
    # so it is said at the write (the handoff driver refuses both; a row
    # written by hand never passes it).
    name = rel_path.rsplit("/", 1)[-1]
    written = repo_root / rel_path
    try:
        if written.is_file() and name.endswith(".md"):
            if not fragments.SESSION_LOG_NAME_RE.match(name):
                _hook_utils.advise_warn(
                    f"{rel_path} is not a Session Log fragment name "
                    f"(<YYYY-MM-DD>-<HHMMSS>-<seat>.md), so every reader skips it; take the "
                    f"name from `python tools/cc/_record_fragments.py new session-log`"
                )
            else:
                held = fragments.rows_from_texts([(name, fragments.decode(written.read_bytes()))], "")
                if len(held) != 1:
                    _hook_utils.advise_warn(
                        f"{rel_path} holds {_hook_utils.plural(len(held), 'dated row')}; a "
                        f"fragment is one `| YYYY-MM-DD | ... |` row"
                    )
        # A tree no fold has reached (pushed by hand, or straight to its
        # default branch without /handoff's fold step) is said once it runs
        # past twice the cap; it is never pruned from here, so the fold stays
        # the one writer of the count (air fc87ad on DEF-5007).
        cap = getattr(fragments, "SESSION_LOG_CAP", None)
        if cap:
            named, _skipped = fragments.session_log_fragments(repo_root)
            if len(named) > 2 * cap:
                _hook_utils.advise_warn(
                    f"{len(named)} Session Log fragments, past twice the cap of {cap}: no fold has run "
                    f"here. A lane's push folds and prunes them (`python tools/cc/ship.py fold` before a "
                    f"push `open` does not make)"
                )
    # Exception, not (OSError, ValueError): a kept older loader missing one name
    # raises AttributeError here, which took the whole post-write check down
    # where the SessionStart digest beside it degrades (review of #179).
    # fail-open: ok telemetry -- the next fragment write reads again, and the advisory says why this one did not
    except Exception as exc:  # noqa: BLE001 -- a broken loader costs this read-back, never the rest of the check
        _hook_utils.advise_warn(
            f"Session Log fragment read failed: {type(exc).__name__}: {os_error_text(exc)}"
        )


_resolve_project_root = _hook_utils.resolve_project_root


# Aliased to `_hook_utils.normalize_path` (single source of truth).
# A non-str payload returns "<invalid>" instead of raising AttributeError —
# the same fail-closed shape `write_guard` already uses.
_normalize_path = _hook_utils.normalize_path


def check_json(content: str, rel_path: str) -> None:
    """Validate JSON parses cleanly."""
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        _hook_utils.advise_warn(f"{rel_path} contains invalid JSON: {e}")


def check_placeholders(content: str, rel_path: str) -> None:
    """Scan for placeholder values."""
    found = [p for p in PLACEHOLDERS if p in content]
    if found:
        _hook_utils.advise_warn(f"{rel_path} contains placeholders: {', '.join(found)}")


def check_python_syntax(content: str, rel_path: str) -> None:
    """Basic Python syntax check via compile()."""
    try:
        compile(content, rel_path, "exec")
    except SyntaxError as e:
        _hook_utils.advise_warn(f"{rel_path} has a Python syntax error: {e}")


# --- Frontmatter Claude Code will not load --------------------------------------
#
# The hook twin of espalier/render_surface.py's frontmatter_hazards (a hook
# cannot import the engine); tests/test_frontmatter_will_not_load.py holds the
# two to one verdict over one corpus, PyYAML the oracle. Claude Code parses a
# body's frontmatter as strict YAML and, when that fails, retries through a
# fallback a trailing carriage return defeats: measured on 2.1.314, a value
# strict YAML rejects loads with LF line endings and fails with CRLF (the agent
# does not register, a skill or command loses its frontmatter), and a ' #'
# cuts the value under both. String scanning only, no pattern. Measured shapes:
# an unquoted ': ' inside a value and a value opening on '[', and a ' #'; every
# other FRAGILE shape is the PyYAML oracle's, not a drive's (probable, not
# measured, that Claude Code's strict parse rejects it the same way).

_FM_FRAGILE = "fragile"
_FM_CUT = "cut"
_FM_PLAIN_FORBIDDEN_FIRST = "]},%@`"
_FM_DQ_SIMPLE_ESCAPES = frozenset("0abt\tnvfre \"/\\N_LP")
_FM_DQ_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}
_FM_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _fm_lines(text: str) -> list[str] | None:
    """The raw lines from the opening to the closing ``---``, or ``None``; one
    leading byte-order mark is read past (whether Claude Code reads a BOM'd
    body's frontmatter at all is unmeasured)."""
    lines = text.removeprefix("\ufeff").split("\n")
    if lines[0].rstrip("\r") != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            return lines[: i + 1]
    return None


def _frontmatter_has_crlf(text: str) -> bool:
    """True when the frontmatter block holds CRLF line endings on disk."""
    lines = _fm_lines(text)
    return lines is not None and any(line.endswith("\r") for line in lines)


def _fm_key(line: str) -> tuple[str | None, str]:
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


def _fm_scan_quoted(value: str) -> tuple[str, int | str]:
    quote = value[0]
    i = 1
    while i < len(value):
        ch = value[i]
        if quote == '"' and ch == "\\":
            nxt = value[i + 1:i + 2]
            if not nxt:
                return "unclosed", ""
            if nxt in _FM_DQ_HEX_ESCAPES:
                width = _FM_DQ_HEX_ESCAPES[nxt]
                digits = value[i + 2:i + 2 + width]
                if len(digits) != width or not set(digits) <= _FM_HEX_DIGITS:
                    return "escape", nxt
                i += 2 + width
                continue
            if nxt not in _FM_DQ_SIMPLE_ESCAPES:
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


def _fm_scan_flow(value: str) -> int | None:
    """A quote opens a quoted item only at an item's start; inside a plain
    item (``[don't, b]``) it is a character."""
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


def _fm_tail_is_clean(tail: str) -> bool:
    rest = tail.lstrip(" ")
    return not rest or (rest.startswith("#") and len(rest) < len(tail))


def _fm_block_header_is_valid(value: str) -> bool:
    head = value[1:]
    cut = head.find(" #")
    if cut != -1:
        head = head[:cut]
    head = head.rstrip(" ")
    chomp = sum(1 for ch in head if ch in "+-")
    indent = sum(1 for ch in head if ch in "123456789")
    return chomp + indent == len(head) and chomp <= 1 and indent <= 1


def _fm_judge(value: str, cont: list[str]) -> tuple[str, str, str] | None:
    value = value.strip(" ")
    if "\t" in value or any("\t" in line for line in cont):
        return None
    more = [line.strip(" ") for line in cont if line.strip(" ")]
    if not value:
        return None
    first = value[0]
    if first == "#":
        return None if more else (_FM_CUT, "a value opening on '#'", "")
    if first in "|>":
        if _fm_block_header_is_valid(value):
            return None
        return _FM_FRAGILE, f"a block-scalar marker '{first}' followed by text", ""
    if first in "\"'":
        state, where = _fm_scan_quoted(value)
        if state == "escape":
            return _FM_FRAGILE, f"an unknown escape '\\{where}' inside double quotes", ""
        if state == "unclosed":
            return None if more else (_FM_FRAGILE, "an unclosed quote", "")
        if more:
            return None
        if _fm_tail_is_clean(value[int(where) + 1:]):
            return None
        return _FM_FRAGILE, "text after the closing quote", ""
    if first in "[{":
        end = _fm_scan_flow(value)
        if end is None:
            return None if more else (_FM_FRAGILE, "an unclosed bracket", "")
        if more or _fm_tail_is_clean(value[end + 1:]):
            return None
        return _FM_FRAGILE, f"text after the closing '{value[end]}'", ""
    if first in _FM_PLAIN_FORBIDDEN_FIRST or first == "*":
        return _FM_FRAGILE, f"an unquoted value opening on '{first}'", ""
    if first == "&" or value.startswith(("!!", "! ")) or value == "!":
        return None
    if first == "!":
        return _FM_FRAGILE, "an unquoted value opening on '!'", ""
    if first in "-?:" and value[1:2] in ("", " "):
        return _FM_FRAGILE, f"an unquoted value opening on '{first}'", ""
    segments = [value] + more
    for n, seg in enumerate(segments):
        if n and seg.startswith("#"):
            if any(not s.startswith("#") for s in segments[n + 1:]):
                return _FM_FRAGILE, "text continuing after a ' #' comment", ""
            return None
        colon = seg.find(":")
        while colon != -1 and seg[colon + 1:colon + 2] not in ("", " "):
            colon = seg.find(":", colon + 1)
        hash_at = seg.find(" #")
        if colon != -1 and (hash_at == -1 or colon < hash_at):
            if colon == len(seg) - 1:
                return _FM_FRAGILE, "an unquoted value ending in ':'", ""
            return _FM_FRAGILE, "': ' inside an unquoted value", ""
        if hash_at != -1:
            if any(not s.startswith("#") for s in segments[n + 1:]):
                return _FM_FRAGILE, "text continuing after a ' #' comment", ""
            kept = " ".join(segments[:n] + [seg[:hash_at].rstrip(" ")])
            return _FM_CUT, "' #' inside an unquoted value", kept
    return None


def _frontmatter_hazards(text: str) -> list[tuple[str, str, str, str]]:
    """``(key, verdict, why, kept)`` for each top-level frontmatter key strict
    YAML reads otherwise than written (the engine twin's contract)."""
    block = _fm_lines(text)
    if block is None:
        return []
    lines = [line.rstrip("\r") for line in block[1:-1]]
    out: list[tuple[str, str, str, str]] = []
    i = 0
    while i < len(lines):
        key, value = _fm_key(lines[i])
        i += 1
        if key is None:
            continue
        cont: list[str] = []
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            cont.append(lines[i])
            i += 1
        verdict = _fm_judge(value, cont)
        if verdict is not None:
            out.append((key, *verdict))
    return out


def _frontmatter_kind(rel_path: str) -> str | None:
    rel = rel_path.replace("\\", "/").lower()
    if rel.startswith(".claude/agents/") and rel.endswith(".md"):
        return "agent"
    if rel.startswith(".claude/commands/") and rel.endswith(".md"):
        return "command"
    if rel.startswith(".claude/skills/") and rel.endswith("/skill.md"):
        return "skill"
    return None


def _fm_sentence(rel_path: str, kind: str, key: str, verdict: str, why: str, kept: str,
                 crlf: bool) -> str | None:
    """What one key does to the body, by the line endings on disk: the engine's
    frontmatter_fragile_sentence / frontmatter_cut_sentence word for word. A CUT
    is said for the description alone: a ' #' after another key's value
    (``model: sonnet  # cheaper``) is idiomatic commenting, and the description
    is the one value Claude Code shows."""
    if verdict == _FM_FRAGILE and crlf and kind == "agent":
        return (
            f"{rel_path}: this agent does not register: its frontmatter has CRLF line "
            f"endings and `{key}` is not strict YAML ({why}), which Claude Code cannot "
            "read past; quote the value"
        )
    if verdict == _FM_FRAGILE and crlf:
        return (
            f"{rel_path}: Claude Code drops this {kind}'s frontmatter (its description "
            f"and allowed tools): the file has CRLF line endings and `{key}` is not "
            f"strict YAML ({why}); quote the value"
        )
    if verdict == _FM_FRAGILE:
        effect = (
            "this agent will not register" if kind == "agent"
            else f"this {kind}'s frontmatter will be dropped"
        )
        return (
            f"{rel_path}: `{key}` is not strict YAML ({why}); Claude Code reads it with "
            f"LF line endings, but {effect} once checked out with CRLF line endings "
            "(core.autocrlf on Windows); quote the value"
        )
    if key != "description":
        return None
    shown = f'"{kept}"' if kept else "no description"
    at = '"#"' if why.startswith("a value opening") else '" #"'
    return (
        f"{rel_path}: the description is cut at {at} (YAML reads the rest as a "
        f"comment), so Claude Code shows {shown}; quote the value to keep it whole"
    )


def check_frontmatter(full_path: Path, rel_path: str, root: Path | None = None,
                      sid: object = None) -> None:
    """Say, at the write, what a body's frontmatter does under each line ending:
    a value strict YAML rejects does not load with CRLF on disk now, and will
    not once a checkout writes CRLF; a description YAML cuts at a comment.
    With a ``root``, each (file, key, verdict, line ending) is said once a
    session: every Edit of a body re-runs this, and the same sentence on each
    is noise; a changed verdict is a new key, so it is said again."""
    kind = _frontmatter_kind(rel_path)
    if kind is None:
        return
    try:
        text = full_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:  # fail-open: ok telemetry -- a body that cannot be read back is not checked
        return
    crlf = _frontmatter_has_crlf(text)
    for key, verdict, why, kept in _frontmatter_hazards(text):
        line = _fm_sentence(rel_path, kind, key, verdict, why, kept, crlf)
        if line is None:
            continue
        if root is None:
            _hook_utils.advise_warn(line)
            continue
        ident = "\0".join((rel_path.lower(), key, verdict, why, "crlf" if crlf else "lf"))
        digest = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:16]
        _say_once_to_claude(root, sid, f"frontmatter-{digest}",
                            "posttooluse_frontmatter_not_strict", line)


def _is_write_tool(tool_name: str) -> bool:
    """The native write tools, plus an MCP tool whose name carries a write verb
    (``mcp__filesystem__write_file``), so the post-write checks fire for both."""
    return tool_name in ("Write", "Edit", "NotebookEdit") or (
        tool_name.startswith("mcp__")
        and any(verb in tool_name.lower() for verb in _MCP_WRITE_VERB_SUBSTRINGS)
    )


def record_file_marker_advisory(tool_name: str, tool_input: dict, root: Path) -> list[str]:
    """One ``additionalContext`` line when a write tool has just left a
    merge-conflict marker in a record file, naming the file and the lines.

    The write-time site of the conflict-marker gate: the rule and the roster
    are ``_hook_utils.conflict_marker_lines`` and ``_hook_utils.RECORD_FILES``
    (the hook side's single owner, shared with the session banner's memory
    digest); the merge-time site is ``ci_guard.check_record_file_markers``,
    the same rule over the same roster. Driven 2026-10-05: a hand merge left
    the memory file half-merged, the commit landed the hunk, and the next
    session's banner read a memory row that was three marker lines. The catch
    belongs at the write, and on THIS channel: a hook that exits 0 has its
    stderr dropped from the transcript by protocol, so a ``warn`` here would
    reach the debug log and nobody else. Adopter-generic, so the caller keeps
    it OUTSIDE the self-host gate the reinject rows sit behind: an adopter
    whose ``init`` seeded a tracked ledger is the named user. The bytes are
    read the way the gate reads them (a byte-order mark of any width, so a
    UTF-16 file a PowerShell redirect wrote is seen whole), and bytes that do
    not decode are replaced: the heads are ASCII. Fail-open and silent for
    anything but a record-file write that carries a marker: a reporter never
    fails the write.
    """
    if not _is_write_tool(tool_name):
        return []
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    if not file_path:
        return []
    base, rel = _hook_utils.resolve_in_checkout(file_path, root)
    if not _hook_utils.is_record_file(rel):
        return []
    full = base / rel
    if not full.is_file():
        return []
    try:
        raw = full.read_bytes()
    except OSError:  # fail-open: ok telemetry -- a record file that cannot be read back is not checked
        return []
    try:
        text = decode_bom(raw)
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    hits = _hook_utils.conflict_marker_lines(text)
    if not hits:
        return []
    lines = ", ".join(str(n) for n, _head in hits)
    heads = " ".join(dict.fromkeys(head for _n, head in hits))
    return [
        f"[post_write_check] {rel}: merge-conflict marker at line {lines} ({heads}). "
        "Resolve the hunk and write the file whole: the record files are read as "
        "whole files, and the merge gate refuses one that carries a marker. A line "
        "that only quotes a marker is read as one too; indent the quote by one space."
    ]


# --- The 2026-09-17 incident's driver shape (self-host only) ------------------
#
# docs/incidents/2026-09-17-real-shell-fixture-wipe.md: a scratch driver,
# written by the Write tool and grown by Edits, ran a fixture row holding a
# variable it never bound; the shell read the empty variable beside a glob as
# the filesystem root, and a recursive delete ran for twenty seconds. The driver
# imported neither bench module, so the conditions there (rules 1 and 2) never
# saw it, and it sat in no checkout, so no tree scanner did either. This is the
# word at the write, 28 s before that run: two predicates over the written
# file's syntax tree, frozen from the census that calibrated them (over every
# .py Write and Edit in this repository's Mac transcripts they fire on the
# incident's two Edits alone, and on no tracked file). Asked of an Edit's payload alone they fire on neither of those Edits
# (the row went in by an Edit that added no shell call), so the file is read
# from disk. A string or a comment never satisfies predicate 1, so a guard
# test's fixture text, both halves in strings, stays silent. Self-host only: the
# calibration is this repository's; an adopter tree's false fires are unmeasured.
_DRIVER_SHELLS = frozenset({"bash", "sh", "zsh", "pwsh", "powershell", "/bin/bash", "/bin/sh", "/bin/zsh"})
_DRIVER_SPAWNS = frozenset({"run", "Popen", "call", "check_output", "check_call"})
_DRIVER_SHELL_FLAGS = ("-c", "-Command")
# Predicate 2, rule 2's glob beside a variable: a delete whose flags hold r, R
# or f, then within twenty characters a $NAME or ${NAME}, quoted or not, an
# optional '/', then '*'. The census spelled the flag run [A-Za-z]*[rRf][A-Za-z]*,
# which backtracks quadratically on a long run (97 ms at 4,000 letters); the
# lookahead reads the run once and accepts the same strings, since either way
# the whole run must hold r, R or f and end at whitespace
# (tests/test_post_write_delete_advisory.py holds the two equal,
# tests/test_redos.py holds this one linear).
_DRIVER_DELETE_RE = re.compile(
    r"\brm\s+-(?=[A-Za-z]*[rRf])[A-Za-z]+\s+[^\n]{0,20}?[\"']?\$\{?\w+\}?[\"']?/?\*"
)
# A larger file is not read. The census's largest judged state was 79 KB, none
# of 3,122 past 128 KiB, so the cap bounds the parse every .py write pays (about
# 20 ms here) without losing a measured driver, and keeps a chain of binary
# operators under half the depth past which a 3.10 parse dies with no exception
# to catch (about 135,000 levels, measured on macOS 2026-11-07); 3.11 and later
# raise RecursionError, which the caller's umbrella catches.
_DRIVER_READ_CAP = 128 * 1024


def _text_of(node: ast.AST) -> "str | None":
    """A string constant's value, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _runs_a_shell_on_built_text(tree: ast.AST) -> bool:
    """Predicate 1: a ``subprocess`` call (one of ``_DRIVER_SPAWNS``) that
    hands a shell text no literal spells: a first argument listing at least
    three items -- a name or one of ``_DRIVER_SHELLS``, then ``-c`` or
    ``-Command``, then anything but a string constant -- or ``shell=True``
    beside a first argument that is not a string constant. The census measured
    this reading's precision, not its recall, and these spellings are not read
    (declared limits): an aliased or bare-name import of subprocess; flags
    before ``-Command`` (PowerShell's own usual order); a list handed to a
    wrapper function, or held in a variable; a shell head that is a call
    (``shutil.which(...)``) or a path outside ``_DRIVER_SHELLS``. Predicate 2
    has no PowerShell delete spelling, so the ``pwsh`` heads fire only beside
    a POSIX delete row."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in _DRIVER_SPAWNS
                and isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, (ast.List, ast.Tuple)) and len(first.elts) >= 3:
            head, flag, text = first.elts[0], first.elts[1], first.elts[2]
            head_named = isinstance(head, ast.Name) or _text_of(head) in _DRIVER_SHELLS
            if head_named and _text_of(flag) in _DRIVER_SHELL_FLAGS and _text_of(text) is None:
                return True
        for keyword in node.keywords:
            if (keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True and _text_of(first) is None):
                return True
    return False


def _first_delete_beside_a_glob(tree: ast.AST) -> "tuple[int, str] | None":
    """Predicate 2: the earliest line holding a string constant with rule 2's
    glob beside a variable, and the text that matched; None where no string
    constant holds one."""
    found: "tuple[int, str] | None" = None
    for node in ast.walk(tree):
        text = _text_of(node)
        if text is None:
            continue
        match = _DRIVER_DELETE_RE.search(text)
        line_no = getattr(node, "lineno", 0)
        if match and (found is None or line_no < found[0]):
            found = (line_no, match.group(0))
    return found


def driver_shape_advisory(data: dict, tool_name: str, tool_input: dict, root: Path,
                          operator: "list[str]") -> None:
    """Tell Claude, once per file and delete text a session, that a Write or
    an Edit has just left a ``.py`` file holding the 2026-09-17 incident's
    driver shape (both predicates above), and the operator the same, on their
    own line. The file is read from disk as Python reads it (a coding cookie
    or a byte-order mark honoured), wherever it sits: the incident's driver was
    a scratchpad file, outside every checkout. The caller gates this to the
    self-host tree and wraps it, so a file that cannot be read, decoded or
    parsed draws no word; the next write reads it again."""
    if tool_name not in ("Write", "Edit"):
        return
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return
    path = Path(file_path)
    if not path.is_absolute():
        path = (_hook_utils.payload_cwd(data, root) or root) / path
    if path.stat().st_size > _DRIVER_READ_CAP:
        return
    tree = ast.parse(path.read_bytes())
    if not _runs_a_shell_on_built_text(tree):
        return
    found = _first_delete_beside_a_glob(tree)
    if found is None:
        return
    line_no, literal = found
    # A subagent and its parent each hear it once (the key carries the agent).
    ident = "\0".join((str(path).replace("\\", "/"), literal, str(data.get("agent_id") or "")))
    digest = hashlib.sha256(ident.encode("utf-8", errors="replace")).hexdigest()[:16]
    spoke = _say_once_to_claude(
        root, data.get("session_id"), f"driver-shape-{digest}", "posttooluse_incident_driver_shape",
        f"{file_path}, line {line_no}: a string holds a recursive delete "
        "of a variable beside a glob, and this file hands built text to a shell -- the shape "
        "of the 2026-09-17 incident (docs/incidents/2026-09-17-real-shell-fixture-wipe.md, "
        "rules 1 and 2), where an unset variable turned the glob into the filesystem root. "
        "Do not run this file with that row in it; ask the guard's classifier about the row "
        "in-process instead (a subagent: put this in your final reply).")
    if spoke:
        operator.append(
            f"espalier: Claude just wrote {file_path} (line {line_no}) in the shape of the "
            "2026-09-17 incident: a recursive delete of a variable beside a glob, in a file "
            "that hands built text to a shell. Claude has been told not to run it.")


# The three deployed body kinds under .claude/ -- ONE tuple, read by both the
# harness-file gate and the placeholder dispatch below. The two used to spell
# the agents-plus-commands pair by hand, twice, and neither learned the third
# kind: a write to .claude/skills/<name>/SKILL.md returned before any check
# ran, so a placeholder left in a deployed skill body surfaced at the next
# doctor instead of at the write (DEF-782; the same hand-typed-pair shape as
# DEF-532, seen from the validation side). A hook cannot import the engine's
# owner (surface_contract.CLAUDE_KIND_GLOBS), so the tuple lives here and a
# parity pin holds the two equal.
_CLAUDE_BODY_KINDS: tuple[str, ...] = ("agents", "commands", "skills", "workflows")


def _is_claude_body(rel_path: str) -> bool:
    """A deployed .claude/ body of any kind, case-insensitively."""
    rel_lc = rel_path.lower()
    return any(rel_lc.startswith(f".claude/{kind}/") for kind in _CLAUDE_BODY_KINDS)


def _is_harness_file(rel_path: str) -> bool:
    """Return True if this path is in the harness infrastructure zones.

    Lowercase comparison so case-varied paths (e.g.,
    ``.CLAUDE/AGENTS/evil.md`` on macOS HFS+ or Windows NTFS) still
    trigger the validation pipeline, matching write_guard + plan_guard.
    """
    rel_lc = rel_path.lower()
    return (
        rel_lc == ".claude/settings.json"
        or _is_claude_body(rel_path)
        or rel_lc.startswith("tools/cc/")
    )


def _is_root_md(rel_path: str) -> bool:
    """Return True if this is a managed governance .md file (root-level or docs/)."""
    managed_docs = {
        "CLAUDE.md", _MEMORY_FILENAME,
        "docs/CONVENTIONS.md", "docs/SHARP_EDGES.md",
        "docs/CHEAT-SHEET.md", "docs/TASK_RECIPES.md",
    }
    return rel_path in managed_docs


# action_justification retroactive advisory. Runs BEFORE the
# Write/Edit-only early-return so Bash/PowerShell mutations also get
# coverage. Non-blocking — emits stderr advisory + audit-log entry on
# miss. Reads the active blueprint via raw json.load — the hook does NOT
# import espalier.cognitive_blueprint.
_AJ_WINDOW_SECS = 60

# The MCP tool-name substrings that mark a write-class call.
# Shared by _check_action_justification_for_mutation (the AJ advisory) and
# _run_main's _is_write_tool gate so the two membership tests cannot drift. Derived
# from the single owner _hook_utils.MCP_WRITE_VERB_SUBSTRINGS (also consumed by
# reflect_trigger's is_mcp_write gate).
_MCP_WRITE_VERB_SUBSTRINGS = _hook_utils.MCP_WRITE_VERB_SUBSTRINGS


def _check_action_justification_for_mutation(
    root: Path, tool_name: str, tool_input: dict
) -> None:
    """If the active blueprint has no matching action_justification
    within the 60s window, emit advisory + audit-log entry. Always
    returns None; never raises."""
    latest = root / "cc" / "blueprints" / "latest.json"
    if not latest.exists():
        return
    try:
        bp = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        # A non-UTF-8 latest.json raises UnicodeDecodeError (a ValueError, not
        # OSError); degrade rather than escape this reporter -- and say once
        # that the justification check cannot run on this blueprint.
        _hook_utils.say_once(
            root, "blueprint-unreadable", "post_write_check", "posttooluse_failed_open_blueprint_read",
            f"blueprint unreadable ({type(exc).__name__}); the action-justification check is skipped this session",
            fault=type(exc).__name__,
        )
        return
    if not isinstance(bp, dict):
        return

    target = ""
    content_hash = None
    if tool_name in ("Write", "Edit", "NotebookEdit") or (
        tool_name.startswith("mcp__")
        and any(v in tool_name.lower() for v in _MCP_WRITE_VERB_SUBSTRINGS)
    ):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if not file_path:
            return
        # Advisory parity with write_guard.check_write_edit's isinstance handling
        # (write_guard DENIES on a non-str payload; this REPORTER returns so a
        # malformed payload loses only its own advisory, not its well-formed
        # siblings' in the same call). Return-not-deny is correct at the advisory
        # tier -- the main() umbrella's AttributeError catch is the sanctioned
        # fail-open; this just keeps it from firing on a typed payload.
        if not isinstance(file_path, str):
            return
        full = root / file_path.replace("\\", "/")
        try:
            content_hash = "sha256:" + hashlib.sha256(full.read_bytes()).hexdigest()
        except OSError:  # fail-open: ok telemetry -- the justification record's hash of a file that is not there
            return
        target = file_path
    elif tool_name in ("Bash", "PowerShell"):
        cmd = tool_input.get("command", "")
        if not cmd:
            return
        content_hash = "sha256:" + hashlib.sha256(cmd.encode("utf-8")).hexdigest()
        target = cmd[:80]
    else:
        return

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=_AJ_WINDOW_SECS)
    # Matcher gates on timestamp window + AJ presence only.
    # The composer in execution_plan.py hashes plan metadata
    # (sha256 of task|index|description); the matcher above computed
    # sha256(file_bytes) for Write/Edit and sha256(cmd) for Bash.
    # Those two hash domains are disjoint by construction; equality
    # would couple the planner to the hook implementation. Trade-off:
    # a single AJ within the 60s window suppresses all mutations in
    # that window. See docs/HOOK_ASSUMPTIONS.md "Action-justification
    # matching" for the full trade-off discussion. content_hash above
    # is preserved for the audit-log payload on miss.
    for aj in bp.get("action_justifications", []):
        if not isinstance(aj, dict):
            continue
        try:
            ts = datetime.fromisoformat(aj.get("timestamp", ""))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= window_start:
            return  # action_justification recorded within window

    print(
        f"[post_write_check] no action_justification recorded for "
        f"{tool_name}:{target} within {_AJ_WINDOW_SECS}s window -- consider: "
        + (f"{_py} tools/cc/cognitive_blueprint.py justify "
           "--from-tool-input-file ..."
           if (_py := _hook_utils.python_command_hint())
           else "record one with cognitive_blueprint.py justify -- no Python "
                f"{_hook_utils.floor_text()}+ interpreter is on PATH to run it"),
        file=sys.stderr,
    )
    try:
        _integrity.append_audit(root, {
            "event_type": "action_justification_missing",
            "details": {
                "tool": tool_name,
                "target": str(target)[:200],
                "content_hash": content_hash,
            },
        })
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass


# The born-weak co-occurrence OBSERVER lives in the co-located sibling
# _born_weak.py (mirrors write_guard's _bash_patterns/_protected_zones split).
# Re-export the symbols tests/test_born_weak_observer.py reaches via
# `import post_write_check as p` so its `p.<symbol>` access is unchanged.
from _born_weak import (  # noqa: E402,F401  (re-export for the test surface)
    _BW_LOG_NAME,
    bw_log_observation,
    observe_born_weak,
    _bw_count_exempt_entries,
    _bw_is_guard_material,
    _observe_born_weak,
)


_BRIDGE_MAX_PATHS = 8


def _dirty_paths_in_checkout(base: Path) -> "set[str] | None":
    """The tracked paths with uncommitted changes under ``base``, by git's own
    answer, in one bounded query per command. ``None`` when git cannot answer
    (no checkout, no git, a timeout): the advisory then keeps its old
    behaviour and fires -- an advisory fails open, never silent.

    Existence alone is not the write: a read-only chain that names a tracked
    doc found the file on disk and drew the deployed-doc advisory for an edit
    that never happened. A file git reports clean after the call was not
    written by it. The limit, stated: a file that was already dirty before
    the call still draws the advisory (a PostToolUse hook has no before
    state), and that file does need the sync it names.
    """
    result = _hook_utils.spawn_checked(
        ["git", "status", "--porcelain", "--untracked-files=no", "-z"],
        root=base, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=5, cwd=str(base),
    )
    if isinstance(result, _hook_utils.SpawnFailure) or result.returncode != 0:
        return None
    dirty: set[str] = set()
    for entry in result.stdout.split("\0"):
        if len(entry) > 3:
            dirty.add(entry[3:].replace("\\", "/"))
    return dirty


def _bash_derived_payloads(tool_input: dict, root: Path, *, already: int,
                           tool_name: str = "Bash", cwd: Path | None = None,
                           rules: "tuple[_reinject.ReinjectRule, ...] | None" = None) -> list:
    """Registry payloads for the paths a Bash or PowerShell command WROTE.

    The guard's extractor over-yields by design (a path inside a string literal,
    a `cp -t` source, a `grep` pattern) because its caller filters through the
    protected-zone check; this caller filters through existence instead -- a
    path that is not on disk after the call was not written by it, and a
    pointer spent on a mention would be gone when the file arrives (failure-mode
    pass, driven: a `python3 -c` run from /tmp whose body named two paths burnt
    both flags). Each real path is offered as the write it was -- `Write` for a
    file git does not track yet, `Edit` for one it does -- so the sync rows that
    gate on those two names fire for a heredoc exactly as for the Write tool.
    The remaining per-turn budget is passed INTO `check`, which marks a once
    row only when it emits, so the caller never trims a returned list.
    ``rules`` is the registry slice the caller offers (the whole registry when
    None); the payload it synthesizes carries a path and the command, never
    content, so a row that reads ``new_string``/``content`` cannot fire here.
    """
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return []
    try:
        import _bash_patterns  # noqa: E402  -- sibling; the guard's extractors
        # The directory the command ran in (DEF-509), read as write_guard
        # reads it: the payload cwd, moved by the command's own cd chain; a
        # .NET-API path on PowerShell keeps the process directory.
        start = cwd or root
        bash = tool_name != "PowerShell"
        _exists = _hook_utils.directory_exists(start, bash=bash)
        if tool_name == "PowerShell":
            paths = _bash_patterns._candidate_paths_from_powershell(command)
            text, statements = _bash_patterns.powershell_directory_chain(command, _exists)
            fixed = frozenset(_bash_patterns.powershell_dotnet_paths(command))
        else:
            paths = _bash_patterns._candidate_paths_from_bash(command)
            text, statements = _bash_patterns.bash_directory_chain(command, _exists)
            fixed = frozenset()
    # fail-open: ok deliberate -- the guard already judged the command; this reporter's derived payloads are advisory
    except Exception:  # noqa: BLE001 -- a reporter never crashes the hook
        return []
    out: list = []
    seen: set = set()
    dirty_by_base: dict = {}
    budget = _reinject.REINJECT_PER_TURN_CAP - already
    for rel in paths:
        if budget <= 0 or len(seen) >= _BRIDGE_MAX_PATHS:
            break
        if not isinstance(rel, str) or rel in seen:
            continue
        seen.add(rel)
        try:
            # The checkout the path sits in (root or a registered worktree,
            # DEF-743): existence, the index and the synthesized payload's path
            # all belong to it, so the registry re-resolves to the same checkout.
            landed = None
            for spelled in (["."] if rel in fixed
                            else _bash_patterns.statement_directories(text, statements, rel)):
                for at in _hook_utils.joined_directories(start, spelled, bash=bash):
                    base, norm = _hook_utils.resolve_in_checkout(rel, root, base=at)
                    if (base / norm).is_file():
                        landed = (base, norm)
                        break
                if landed is not None:
                    break
            if landed is None:
                continue          # mentioned, not written
            base, norm = landed
        except (OSError, ValueError):
            continue
        tracked = _reinject._is_tracked(base, norm)
        if tracked:
            if base not in dirty_by_base:
                dirty_by_base[base] = _dirty_paths_in_checkout(base)
            dirty = dirty_by_base[base]
            if dirty is not None and norm.replace("\\", "/") not in dirty:
                continue          # on disk and unchanged: mentioned, not written
        synthesized = "Edit" if tracked else "Write"
        for text in _reinject.check("PostToolUse", synthesized,
                                    {"file_path": str(base / norm), "command": command}, root,
                                    rules=_reinject.REINJECTS if rules is None else rules,
                                    budget=budget):
            if text not in out:
                out.append(text)
                budget -= 1
    return out


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: post_write_check is an advisory
    PostToolUse hook, so an uncaught crash in ``_run_main`` (a check helper, a
    producer schema drift) must degrade to a no-op advisory (exit 0 + one
    [ERROR] line), NOT a per-write traceback. Mirrors task_router.main —
    advisory tier fails OPEN.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        # Exit 0, so a stderr line alone reaches the debug log only (the
        # protocol pin): the record, once a session, is what `/status --log`
        # counts. Class name only, never the message's payload text.
        _hook_utils.say_crash(
            "post_write_check", "posttooluse_failed_open_crash", exc,
            "the post-write checks did not run for this call",
        )
        return 0


def _run_main() -> int:
    # PostToolUse runs AFTER the tool call has already executed —
    # it cannot block. Everything here is advisory; the gate is the
    # `# stop_gate.py` (Stop event) or PreToolUse hooks. A finding lands in
    # the additionalContext of the ONE JSON object this hook prints (the pin
    # delivers it next to the tool result), with a stderr debug copy and, for
    # drift, an audit-log entry -- never as a denied tool call. One object,
    # printed once at the end: two stdout JSON lines fail the whole parse.
    from _hook_utils import read_stdin_safely  # noqa: E402

    _hook_utils.take_advisories()  # a line an in-process caller left is not this run's
    data = read_stdin_safely()
    if not data:
        return 0
    payloads: list[str] = []
    operator: list[str] = []
    try:
        return _check(data, payloads, operator)
    finally:
        # The operator lines are passed only when there are some, so this
        # hook beside a _hook_utils that predates them still prints its object.
        if operator:
            _hook_utils.emit_advisories("PostToolUse", payloads, operator)
        else:
            _hook_utils.emit_advisories("PostToolUse", payloads)


# The zones compared after every shell call. At most this many
# changed paths are named in one report; the rest are counted.
_ZONE_NAMES_SHOWN = 5
_SHELL_TOOLS = ("Bash", "PowerShell")


def _zone_names(unaccounted: dict, only: "list[str] | None" = None) -> str:
    """``changed a; added b; and 3 more`` for the report's two lines."""
    named = [(kind, rel) for kind in ("changed", "added", "removed")
             for rel in unaccounted[kind] if only is None or rel in only]
    text = "; ".join(f"{kind} {rel}" for kind, rel in named[:_ZONE_NAMES_SHOWN])
    more = len(named) - _ZONE_NAMES_SHOWN
    return text + (f"; and {more} more" if more > 0 else "")


def _say_once_to_claude(root: Path, sid: object, key: str, event_type: str, line: str) -> bool:
    """A once-a-session notice Claude reads (``advise``) as well as the
    record ``say_once`` writes: an exit-0 hook's stderr reaches no one. Keyed
    by session, so a sibling session's notice does not silence this one's.
    True when this call told Claude, so a caller can tell the operator once too."""
    full_key = f"{key}-{_hook_utils.safe_session_id(sid) or 'nosid'}"
    flag = root / _hook_utils.STATE_DIR / (_hook_utils.ONCE_FLAG_PREFIX + full_key)
    try:
        said = flag.exists()
    except OSError:  # fail-open: ok deliberate -- an unreadable flag: say it; say_once keeps it to once a process
        said = False
    if not said:
        _hook_utils.advise_warn(line)
    _hook_utils.say_once(root, full_key, "post_write_check", event_type, line)
    return not said


def _zone_check(data: dict, tool_name: str, tool_input: dict, root: Path, operator: list[str]) -> None:
    """After a shell call, report a protected-zone change that nothing
    accounts for; after a file tool, refresh the written file's entry (it
    was judged by path before it ran). The wording says the zones changed
    since the previous check, never that this command wrote them. A change
    that landed before the call began (a person's editor, another session, a
    background job) goes to the operator's line only; Claude is asked to stop
    for what landed during the call."""
    sid = data.get("session_id")
    try:
        import _zone_watch  # noqa: E402 -- lazily: only the calls it judges pay its import
    except ImportError as exc:  # a deploy that predates the helper: said once, never every call
        _hook_utils.say_once(
            root, "zone-watch-import", "post_write_check", "posttooluse_failed_open_zone_import",
            f"tools/cc/hooks/_zone_watch.py could not be imported ({type(exc).__name__}); "
            "the protected-file check after shell calls is off -- run espalier upgrade --execute",
        )
        return
    if tool_name not in _SHELL_TOOLS:
        file_path = (tool_input.get("file_path") or tool_input.get("path")
                     or tool_input.get("notebook_path") or "")
        if file_path and isinstance(file_path, str):
            base, rel = _hook_utils.resolve_in_checkout(file_path, root)
            if base == root:
                _zone_watch.after_file_tool(root, sid, [rel])
        return
    try:
        result = _zone_watch.after_shell_call(root, sid, data.get("duration_ms"))
    finally:
        # A fresh walk's once-a-session line (DEF-2031), rendered even when the
        # call raised after saying it; an older kept _zone_watch has no queue.
        for line in getattr(_zone_watch, "take_notices", list)():
            _hook_utils.advise_warn(line)
    if result is None:
        return
    if result["status"] == "unchecked":
        _say_once_to_claude(
            root, sid, "zone-unchecked", "posttooluse_failed_open_zone_unchecked",
            f"protected-file check: {result['reason']}; this shell call's state was taken "
            "as the baseline, so this call was not checked")
        return
    if result["status"] == "off":
        _say_once_to_claude(
            root, sid, "zone-off", "posttooluse_failed_open_zone_off",
            f"protected-file check is off this session: the watched files are too many to walk "
            f"({result['reason']}); narrow protected_paths, or name the large directories "
            "in espalier.toml's dependency_dirs")
        return
    during, between = result["during"], result["between"]
    _integrity.append_audit(root, {
        "event_type": "post_shell_zone_change",
        "details": {"tool": tool_name,
                    **{f"{kind}": during[kind][:20] for kind in during},
                    **{f"{kind}_between_calls": between[kind][:20] for kind in between},
                    "count": sum(len(v) for v in during.values()),
                    "count_between_calls": sum(len(v) for v in between.values())},
    })
    notes = "".join(f" ({note})" for note in result.get("notes", ()))
    if any(during.values()):
        _hook_utils.advise_warn(
            "protected files changed during this shell call, and nothing accounts "
            "for the change (no file tool judged it, it is not the content committed "
            "at HEAD, not a mirror synced to its source, and no harness writer "
            f"recorded it): {_zone_names(during)}. This call or a parallel one made "
            "it; this check cannot say which. Stop and tell the operator what "
            "changed before going on (a subagent: put this in your final reply)."
            + notes
        )
    told_during = [r for r in result["operator"] if any(r in v for v in during.values())]
    told_between = [r for r in result["operator"] if any(r in v for v in between.values())]
    if told_during:
        operator.append(
            "espalier: protected files changed during Claude's last shell call and nothing "
            f"accounts for it: {_zone_names(during, told_during)}. Claude has been told to "
            "stop and tell you.")
    if told_between:
        operator.append(
            "espalier: protected files changed between Claude's calls and nothing accounts "
            f"for it: {_zone_names(between, told_between)}. If you or another session made "
            "the change, nothing is needed; otherwise look before going on.")


def _check(data: dict, payloads: list[str], operator: "list[str] | None" = None) -> int:
    """The body of ``_run_main``: fills ``payloads`` with the reinject and
    conflict-marker texts and runs the post-write checks, whose findings the
    collector keeps, and ``operator`` with the lines meant for the person at
    the terminal; ``_run_main`` prints the one JSON object after it."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    if operator is None:
        operator = []

    # action_justification retroactive advisory runs FIRST so
    # Bash/PowerShell mutations also get coverage (the JSON-validity /
    # path-consistency checks below remain Write/Edit-only via the
    # existing early-return). Non-blocking — never affects return value.
    root_for_aj = _resolve_project_root()
    _check_action_justification_for_mutation(root_for_aj, tool_name, tool_input)

    # The zones after a shell call, or the file tool's refresh.
    # Runs for every tool this hook is matched on, before the write-only
    # return below, and never costs the rest of this hook.
    if tool_name in _SHELL_TOOLS or _is_write_tool(tool_name):
        try:
            _zone_check(data, tool_name, tool_input, root_for_aj, operator)
        except Exception as e:  # noqa: BLE001 — advisory; never lose the rest of this hook
            _hook_utils.advise_exc("post_write_check: zone check failed", e)

    # config_guard refused a project settings change that unwires
    # the gates, or a settings change that switches one off (DEF-3081). That
    # refusal reaches no one (ConfigChange has no channel), so each note is
    # told here, once, beside the next tool result.
    # Each reader is looked up inside its try: under a kept, older _integrity
    # a missing one costs its own notice, never the rest of this hook.
    for take, what in (("take_unwired_notice", "settings-unwired"),
                       ("take_switch_notice", "settings-switch")):
        try:
            notice = getattr(_integrity, take)(root_for_aj)
        except Exception as e:  # noqa: BLE001 — advisory; never lose the rest of this hook
            _hook_utils.advise_exc(f"post_write_check: {what} notice failed", e)
            notice = None
        if notice:
            _hook_utils.advise(notice)

    # Advisory PostToolUse reinject -- delivered next to the tool result, BEFORE
    # the write-only early-return below. The JSON/path validation below keeps
    # its findings in the collector, and the one object carries both.
    #
    # Scoped by ROW, not by call site. The PostToolUse sync rows whose witnesses
    # name engine internals (cli.py::INIT_HOOK_SCRIPTS, examples/dogfooding/,
    # tests/...) keep `scope="self_host"` and are offered only on the harness's
    # own tree, read off the repo root (here `root_for_aj`, ==
    # _resolve_project_root()) like the born-weak observer below -- so an adopter
    # who creates a command/hook is not told about Espalier's mirrors. The rows
    # whose text is true everywhere (`scope="any"`: the test-loosening nudge, the
    # `git archive` proxy note) are offered on every tree; until 2026-10-08 one
    # gate over the whole call silenced them off self-host. The whole registry on
    # self-host, in its own order, so the harness tree's output is unchanged.
    # SessionStart/UserPromptSubmit orientation + PostToolUseFailure Rule A are
    # generic and ride other hooks. An empty slice => [] => no print.
    self_host = _hook_utils.is_self_host_repo(root_for_aj)
    rules = _reinject.REINJECTS if self_host else _reinject.REINJECTS_ANY
    _reinject_payloads = _reinject.check("PostToolUse", tool_name, tool_input, root_for_aj,
                                         rules=rules)
    # A Bash write carries no file_path, so every path-keyed row above was
    # silent for a heredoc, `printf >>`, `sed -i` or `python -c` edit --
    # measured 2026-09-06: 3 pushes in a session of hundreds of tool calls.
    # Derive the written paths with the guard's own extractor and ask the
    # registry once per path, under the same per-turn ceiling. The bridge keeps
    # the tree-identity gate: it synthesizes an Edit/Write from a written path
    # alone, with no content and never a Bash tool name, so neither any-tree row
    # can fire through it (`_reinject._new_content` reads new_string/content
    # only), and off self-host its per-path git reads would buy nothing.
    if tool_name in ("Bash", "PowerShell") and self_host:
        _reinject_payloads = _reinject_payloads + _bash_derived_payloads(
            tool_input, root_for_aj, already=len(_reinject_payloads), tool_name=tool_name,
            cwd=_hook_utils.payload_cwd(data, root_for_aj), rules=rules,
        )
    # The record-file conflict-marker advisory rides the same single stdout
    # JSON (one print per run: channel-XOR), and sits OUTSIDE the self-host
    # gate above -- an adopter with a tracked ledger is its named user -- and
    # outside the reinject ceiling, since it is a finding about the file just
    # written, not a pointer row.
    marker_advisory = record_file_marker_advisory(tool_name, tool_input, root_for_aj)
    payloads.extend(_reinject_payloads + marker_advisory)

    # Include MCP write tools so post-write JSON / Python / placeholder
    # checks still fire when the agent uses `mcp__filesystem__write_file`
    # instead of the native Write tool.
    if not _is_write_tool(tool_name):
        return 0

    # MCP tool_input uses `path` more than `file_path`. Sweep both.
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    root = _resolve_project_root()
    # `base` is the checkout the written file sits in -- the root, or a registered
    # worktree of the repository (DEF-743) -- and `rel_path` is relative to it;
    # every read-back, the observer's diff and the memory prune below go through
    # `base`. The integrity spot-check runs for a root write only: the manifest
    # describes the root's deployed surface, which a worktree write cannot drift.
    base, rel_path = _hook_utils.resolve_in_checkout(file_path, root)

    # Born-weak co-occurrence OBSERVER (self-host only; observe-first instrument).
    # Runs BEFORE the harness-file gate below, which would skip tests/ + scanners.
    # Observe-only, best-effort, never affects the return value.
    if _hook_utils.is_self_host_repo(root):
        _observe_born_weak(root, rel_path, base=base)

    # The 2026-09-17 incident's driver shape, read from disk (self-host only).
    # Before the harness-file gate below, which skips every file outside the
    # harness's own paths: the incident's driver was a scratchpad file.
    if self_host:
        try:
            driver_shape_advisory(data, tool_name, tool_input, root, operator)
        # fail-open: ok deliberate -- a file that cannot be read, decoded or parsed (a mid-edit state, a deep expression the parser refuses) draws no word; the next write reads it again
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):  # noqa: S110
            pass
        except Exception as exc:  # noqa: BLE001 -- a defect in the advisory itself is said, and never costs the checks below
            _say_once_to_claude(
                root, data.get("session_id"), "driver-shape-failed", "posttooluse_failed_open_driver_shape",
                f"post_write_check: the 2026-09-17 driver-shape check failed ({type(exc).__name__}), "
                "so it said nothing about this write; the next write runs it again")

    # The Session Log fragment's read-back runs before the gate below, which
    # reads a fragment as neither harness file nor root doc; never on a
    # fragment the marker advisory just named as half-merged.
    if not marker_advisory:
        _check_session_log_fragment(base, rel_path)

    # Only activate for harness infrastructure or root managed docs
    if not _is_harness_file(rel_path) and not _is_root_md(rel_path):
        return 0

    full_path = base / rel_path
    if not full_path.exists():
        return 0

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # fail-open: ok telemetry -- a written file that cannot be read back is not checked
        return 0

    # .claude/settings.json → JSON validation
    if rel_path == ".claude/settings.json":
        check_json(content, rel_path)

    # .claude/{agents,commands,skills,workflows}/ bodies → placeholder check;
    # an agent, command or skill body → what Claude Code reads of its frontmatter
    if _is_claude_body(rel_path):
        check_placeholders(content, rel_path)
        check_frontmatter(full_path, rel_path, root, data.get("session_id"))

    # tools/cc/**/*.py → Python syntax check
    if rel_path.startswith("tools/cc/") and rel_path.endswith(".py"):
        check_python_syntax(content, rel_path)

    # Root .md files → placeholder check
    if _is_root_md(rel_path):
        check_placeholders(content, rel_path)

    # Integrity spot-check for non-allowlisted writes in protected zones.
    if not _is_allowlisted(rel_path) and base == root:
        _integrity_spot_check(root, rel_path)

    # Auto-prune ESPALIER_MEMORY.md when the just-completed write pushes
    # the file past the line cap. Always last (advisory action; never
    # blocks) -- and never on a file the advisory above just named as
    # half-merged: a half-merged memory file carries both sides' rows, so it
    # is the one most likely to cross the cap, and a prune would rewrite the
    # file under the line numbers the operator is reading (failure-mode
    # review, 2026-10-05). Resolve the hunk first; the next write prunes.
    if not marker_advisory:
        _maybe_autoprune_memory(base, rel_path)

    return 0


if __name__ == "__main__":
    # UTF-8 on both streams, whatever the console code page: on Windows a
    # redirected stream defaults to the ANSI page, a non-ASCII character in
    # the CONTENT this prints (a plan's text, a recall title, a memory row)
    # goes out as cp1252, and a parent decoding UTF-8 loses the whole stream
    # (CPython's Windows communicate() answers None for a reader thread that
    # died; Portability, 2026-09-24). Content is the operator's and may be
    # anything; the messages around it stay 7-bit ASCII by rule.
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
