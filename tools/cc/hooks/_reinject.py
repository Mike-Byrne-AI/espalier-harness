"""Recall engine: trigger-correlated context reinjection (the push side).

A ReinjectRule fires ``render(...) -> advisory text | None`` when its trigger
matches, on an ALREADY-WIRED hook event. The text is delivered on the CALLER's
channel: ``hookSpecificOutput.additionalContext`` JSON on SessionStart / PreToolUse
/ PostToolUse(Failure), and plain stdout on UserPromptSubmit (task_router)
-- see docs/external/cc-hook-protocol.md. FRICTIONLESS: it only injects context, it
NEVER denies (that is ``_speedbump.py``'s job). Stdlib, zero espalier imports. Rides
session_start (SessionStart), task_router (UserPromptSubmit), write_guard (PreToolUse
"*"), post_write_check (PostToolUse), context_reinject_failure (PostToolUseFailure)
at ZERO net hook-count.

Scarcity is mechanical: a flocked
``REINJECT_SESSION_CAP`` bounds total fires EXCEPT ``cap_exempt``
(defensive/safety) rules; a per-call ``REINJECT_PER_TURN_CAP`` bounds how many
payloads emit at once so co-firing injectors cannot dilute the signal. Sibling
of ``_speedbump.py`` with the OPPOSITE posture: the speed-bump GATES an action
(returns a deny reason); this ENRICHES context (returns advisory text) and must
never convert to a deny — see docs/SHARP_EDGES.md "A recall-engine rule is
FRICTIONLESS".
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, NamedTuple
# NamedTuple (not @dataclass): `dataclasses` eagerly imports `inspect` (~4 ms),
# and write_guard imports this module on the PreToolUse('*') hot path, so a
# @dataclass here would re-pay that on every tool call. typing is already loaded.

from _hook_utils import (
    RECALL_LOG_NAME,
    STATE_DIR,
    _append_jsonl,
    _locked_increment,
    _telemetry_enabled,
    host_orientation_line,
    normalize_path,
    resolve_in_checkout,
    stop_gate_mode,
)
from _maintenance_mode import ENV_VAR

REINJECT_SESSION_CAP = 5      # total non-exempt fires per session
REINJECT_PER_TURN_CAP = 2     # max payloads emitted per check() call (anti-dilution)
REINJECT_COUNTER = "reinject_count"


class ReinjectRule(NamedTuple):
    id: str
    event: str                                         # SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | PostToolUseFailure
    render: Callable[[str, dict, Path], "str | None"]  # -> advisory text, or None (silent)
    face: str = "defensive"                            # orientation | defensive | generative | sync
    cap_exempt: bool = False                           # safety rules: never session-cap-suppressed
    priority: int = 50                                 # per-turn-ceiling ordering (higher = kept first)
    # Generative-face rail: a face=="generative" rule may auto-inject ONLY if
    # push_eligible AND parity-tested; else it is /recall pull-only (never auto-pushed).
    push_eligible: bool = False
    # Pointer rows fire at most ONCE per session (a flag under STATE_DIR that
    # session_start clears): their scarcity is the flag, not the session cap,
    # which is why the four catalog pointers below are cap_exempt as well.
    once_per_session: bool = False


_STOP_GATE_ENV = "ESPALIER_STOP_GATE"


# ── Tier-1 SessionStart ambient orientation (ONE conditional row) ─────────────
# The parent-session twin of subagent_start's cold-subagent orientation. ONE row
# whose render returns 1-3 lines from the ACTIVE facts -- a SINGLE payload so the
# per-turn ceiling can never clip a fact (3 separate non-exempt rows would
# self-starve against REINJECT_PER_TURN_CAP=2). Never emits the empty-state
# MAINTENANCE=off / STOP_GATE=light noise.
def _render_orientation(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    lines = [host_orientation_line()]                  # always (host + interpreter)
    if os.environ.get(ENV_VAR) == "1":
        lines.append("MAINTENANCE=on")                 # only when set
    # ONE grammar (_hook_utils.stop_gate_mode). A raw `!= "light"` here meant a
    # padded value rendered a STOP_GATE row that stop_gate itself read as light.
    stop = stop_gate_mode(os.environ.get(_STOP_GATE_ENV))
    if stop and stop != "light":
        lines.append(f"STOP_GATE={stop}")              # only when non-light
    return "\n".join(lines)


# ── consolidated Rule A (PostToolUseFailure) ─────────────────────────────────
# The registry owns the TEXT + cap-exempt/priority metadata; the FIRING predicate
# (_is_old_string_failure) stays in context_reinject_failure.py, which calls
# check() only after its predicate passes -> this render is unconditional for the
# event (the hook is the gate). cap_exempt: a stale-frame re-derive is safety, not
# dilutable noise -> never session-cap-suppressed.
_RULE_A = (
    "Edit/Write failed to find old_string. You may be working from a stale or "
    "fabricated view of this file. Before retrying: re-anchor against the real "
    "bytes (`git show HEAD:<path>` or a fresh Read of the exact region); do NOT "
    "transcribe a prior Read; treat the failure as real signal, not noise."
)


ORIENT_RULE = ReinjectRule(
    id="ORIENT", event="SessionStart", render=_render_orientation,
    face="orientation", priority=90,
)

RULE_A = ReinjectRule(
    id="RULE-A", event="PostToolUseFailure", render=lambda *a: _RULE_A,
    face="defensive", cap_exempt=True, priority=100,
)


# ── PostToolUse multi-surface-sync rules ─────────────────────────────────────
# FRICTIONLESS sync injectors: when a drift-prone edit lands, push the COMPLETE
# sister-site witness set as DATA (not a vague "remember the others") so the model
# closes the sister-sites in the SAME session -- before the offline count contracts
# go red. Distinct priorities => the per-turn ceiling drop-order is deterministic,
# not tuple-position-dependent. A sync row is non-cap-exempt unless it declares
# `cap_exempt=True` on the row itself; the rest share the session budget with
# ORIENT (anti-dilution), and REINJECT_PER_TURN_CAP bounds a co-fire.
#
# SELF-HOST ONLY: every witness below names an Espalier engine internal
# (cli.py::INIT_HOOK_SCRIPTS, espalier/assets/..., examples/dogfooding/, tests/...)
# absent from an adopter repo, so the call site gates these to self-host --
# `post_write_check._run_main` only calls `check("PostToolUse", ...)` when
# `is_self_host_repo(root)`. Any further PostToolUse row inherits that gate for
# free; do NOT add an adopter-generic rule here (it would be suppressed off self-host). The
# SessionStart/UserPromptSubmit orientation + PostToolUseFailure Rule A rows are
# generic and stay ungated (emitted by other hooks, not post_write_check).

# The canonical wired-hook script list -- the parity ANCHOR.
# tests/test_reinject_sync.py::TestWitnessSetParity binds this to
# surface_contract.get_canonical_hook_scripts() so it reddens the moment a 13th
# hook is wired: the witness data is itself a multi-surface SoT, and this makes it
# contract-bound rather than hope-bound (the footgun the rules exist to kill).
# sister-site: ok forced copy across the no-import boundary; test-pinned to surface_contract.get_canonical_hook_scripts()
_CANONICAL_HOOK_SCRIPT_NAMES: tuple[str, ...] = (
    "config_guard.py", "context_reinject_failure.py", "plan_guard.py",
    "post_compact.py", "post_write_check.py", "reflect_trigger.py",
    "session_start.py", "stop_gate.py", "subagent_start.py",
    "subagent_stop.py", "task_router.py", "write_guard.py",
)

# Surfaces a NEW WIRED HOOK must update (docs/QUICKSTART.md is the known
# straggler -- easy to miss).
_HOOK_COUNT_WITNESSES: tuple[str, ...] = (
    "espalier/harness_config.py::CANONICAL_HOOK_WIRING (event -> matcher row)",
    "espalier/surface_contract.py::_CANONICAL_HOOK_SCRIPTS + the protected-mutation "
    "and protected-integrity tuples",
    "espalier/cli.py::INIT_HOOK_SCRIPTS (deploy list) + _build_settings_json + the "
    "n_hook_scripts local in _build_claude_md",
    "tools/cc/hooks/_integrity.py::MANIFEST_FILES (2nd integrity SoT -- must EQUAL "
    "surface_contract; test_integrity_contract_parity)",
    ".espalier/freshness.json (hook-count fragment expected_value)",
    "tests/_surface_expected.py::EXPECTED_HOOK_COUNT",
    "scripts/wheel_smoke.py::EXPECTED_HOOK_ENTRY_COUNT",
    "tests/test_portability_contract.py + tests/test_documented_claims.py "
    "(canonical-hook-count NumericContract)",
    ".claude/settings.json (wired hook entry, exec form)",
    "cc/PACK_MANIFEST.txt + cc/LIVE_SURFACE.md",
    "docs: README.md, docs/HOOKS.md, docs/QUICKSTART.md, "
    ".claude/agents/harness-config-advisor.md hook-count claim",
)

# Underscore HELPER (not a wired hook) -> the smaller helper-count set (the
# surfaces a helper-count bump touches: registered + counted, NOT wired).
_HELPER_COUNT_WITNESSES: tuple[str, ...] = (
    "espalier/managed_inventory.py::_HOOK_HELPERS + its docstring count (the SoT: "
    "surface_contract's protected-mutation/integrity HOOK portion DERIVES from "
    "get_hook_entry_files()|get_hook_helper_files(), so adding a helper "
    "HERE flows into both protected lists automatically -- no surface_contract "
    "edit; NOT _CANONICAL_HOOK_SCRIPTS, that is wired-entries only, stays 12)",
    "tools/cc/hooks/_integrity.py::MANIFEST_FILES (still a hand-mirror -- the "
    "zero-espalier-import rule forbids calling managed_inventory; "
    "test_integrity_contract_parity pins it == get_protected_integrity_paths())",
    "espalier/cli.py::INIT_HOOK_SCRIPTS (deploy list; rationale-ordered, NOT "
    "alphabetical)",
    "tests/_surface_expected.py::EXPECTED_HOOK_HELPER_COUNT",
    "scripts/wheel_smoke.py::EXPECTED_HOOK_HELPERS + EXPECTED_HOOK_HELPER_COUNT",
    "tests/test_managed_inventory.py::test_hook_helper_count (assert len == N)",
    "cc/PACK_MANIFEST.txt + README.md + docs/QUICKSTART.md helper-count prose",
)

# The five command-file sister-sites.
_COMMAND_SURFACE_WITNESSES: tuple[str, ...] = (
    ".claude/commands/<name>.md (the file you just wrote)",
    "espalier/assets/claude/commands/<name>.md (wheel asset mirror -- "
    "TestAssetClaudeMirrorParity)",
    "examples/dogfooding/.claude/commands/<name>.md (dogfooding mirror -- "
    "TestRootMirrorParity)",
    "cc/COMMANDS.md (command reference table)",
    "the command-count contract (tests/test_command_surface_truth.py / "
    "discover_installed_commands)",
)

_HOOK_SCRIPT_RE = re.compile(r"(^|/)tools/cc/hooks/[^_/][^/]*\.py$")
_HOOK_HELPER_RE = re.compile(r"(^|/)tools/cc/hooks/_[^/]*\.py$")
_COMMAND_FILE_RE = re.compile(r"(^|/)\.claude/commands/[^/]*\.md$")
_TEST_PATH_RE = re.compile(r"(^|/)tests/")
_TEST_LOOSEN_RE = re.compile(r"mark\.(?:skip|xfail)|raises\(\s*Exception\s*\)")
# Spans are bounded `[^"']{0,200}` (not unbounded `[^"']*`): two spans straddling
# a required `MANAGED` token is a ReDoS class — quadratic on a repeated-`MANAGED`
# quoted run, and reachable at PostToolUse runtime over `_new_content`, which is
# UNCAPPED (unlike write_guard's 32KB bash cap), so a large attacker-authored write
# would stall past the hook timeout = slow-hook fail-open. The `[^x]*TOKEN[^x]*`
# spelling is outside the dot-star gate's scope by design, so this is additionally
# pinned by a per-pattern SIGALRM budget in `tests/test_redos.py`. A 200-char marker
# context is ample for the forgeable-marker advisory.
_MARKER_SUBSTRING_RE = re.compile(r"""["'][^"']{0,200}MANAGED[^"']{0,200}["']\s+in\b""")
_INTEGRITY_PARITY_TAILS = ("tools/cc/hooks/_integrity.py", "espalier/surface_contract.py")
_MARKER_CANON_HOME_TAILS = ("espalier/managed_markers.py", "espalier/managed_inventory.py")
# Mirror-sync injectors: a tools/cc/**/*.py edit -- or the *.cmd Windows
# statusline shim (DEF-729), the one deployed non-.py file the same mirror
# carries -- needs scripts/sync_vendor_cc.py (espalier/_vendor/cc/ is a
# byte-for-byte mirror); a deployed-doc edit needs the espalier/assets/docs/
# mirror synced. The vendor regex excludes the mirror itself (espalier/_vendor/cc/
# carries no `tools/cc/` segment). _DOCS_ASSET_TAILS is a multi-surface SoT bound
# to the deployed-doc set by tests/test_reinject_sync.py. The path-char class
# `[\w./_-]*` (NOT `.*`) crosses subdirs without the runtime ReDoS surface
# test_redos.py forbids: a single star over a char class + a fixed-suffix anchor
# backtracks linearly, not catastrophically.
_VENDOR_MIRROR_RE = re.compile(r"(^|/)tools/cc/[\w./_-]*\.(?:py|cmd)$")
_DOCS_ASSET_TAILS = (
    "docs/TROUBLESHOOTING.md",
    "docs/sharp-edges/README.md",
    "docs/external/cc-hook-protocol.md",
    "docs/sharp-edges/convergence-is-an-angle-set-property.md",
    "docs/sharp-edges/closed-loop-verification-trap.md",
    "docs/sharp-edges/hook-exit-codes-channel-xor.md",
    "docs/INSTALL-CI.md",
    "docs/FAILURE_MODES.md",
    "docs/PACK_AUTHORING.md",
    "docs/HOOKS.md",
    "docs/HOOK_ASSUMPTIONS.md",
    "docs/WORKFLOW.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
    "docs/FRESHNESS.md",
    "docs/ENV_CATALOG.md",
)
# The GENERATED side of the mirror rows whose sync script OVERWRITES the file it
# lands on. An advisory whose remedy is "run the sync" must never fire on a path
# here: running it discards the edit that triggered the advisory and reports
# success. A suffix test cannot make that distinction on its own -- every mirror
# path ENDS WITH its own source-side path, which is what made `endswith(tail)`
# fire on both sides of four separate rules.
#
# Deliberately NOT listed, and each omission is load-bearing:
#   espalier/assets/github/  -- the one INVERTED row (harness-guard): the asset is
#       the SoT and the ROOT file is generated, so the sides are swapped and a
#       blanket exclusion here would silence the side that must warn.
#   .claude/commands/implement-pack.md, .claude/skills/reflect/SKILL.md -- mirror
#       side of the two checklist-region rows, but ALSO the source of truth of the
#       two claude rows. Excluding them would suppress a correct advisory.
# Because of those three, this is a per-rule early return, never a filter over the
# dispatch loop. The membership is pinned against espalier/mirror_registry.py by
# tests/test_reinject_sync.py::TestMirrorCensusCoverage.
#
# Each alternative is the mirror path of a row, at the row's own granularity --
# the `claude-dogfooding` row mirrors `examples/dogfooding/.claude/`, NOT the
# whole `examples/dogfooding/` tree, which also holds a hand-written README and
# a contracts/ sample that no sync generates. Every caller currently gates on a
# narrower matcher first, so the broader spelling was inert; it is written at
# row granularity anyway, because the next caller to use this as its SOLE gate
# would inherit the imprecision silently.
_GENERATED_MIRROR_RE = re.compile(
    r"(^|/)(espalier/assets/(claude|docs|task-packs)"
    r"|espalier/_vendor/(cc|selfcheck_tests)"
    r"|examples/dogfooding/\.claude)/"
)


def _on_generated_mirror(fp: str) -> bool:
    """True when ``fp`` is a file a sync script overwrites (see the note above)."""
    return bool(_GENERATED_MIRROR_RE.search(fp))


def _fp(tool_input: dict) -> str:
    return (tool_input.get("file_path", "") or tool_input.get("path", "")).replace("\\", "/")


def _new_content(tool_input: dict) -> str:
    # PostToolUse post-state only: Write carries ``content``; Edit carries
    # ``new_string``. We do NOT read ``old_string`` -- it is not pinned on the
    # PostToolUse event (docs/external/cc-hook-protocol.md is silent) and no other
    # hook reads it there; differential cases stay with the offline scanner.
    return tool_input.get("new_string", "") or tool_input.get("content", "")


def _bullets(items: tuple[str, ...]) -> str:
    return "\n".join(f"  - {w}" for w in items)


def _render_new_hook_witness(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    if tool_name != "Write":
        return None
    fp = _fp(tool_input)
    if _HOOK_HELPER_RE.search(fp):
        return ("You wrote a hook HELPER (_*.py). Helper-count is a multi-surface SoT; "
                "close these sister-sites THIS session (the offline count contracts only "
                f"catch a miss at pytest time):\n{_bullets(_HELPER_COUNT_WITNESSES)}")
    if _HOOK_SCRIPT_RE.search(fp):
        return ("You wrote a wired-hook script. Wiring a hook is a multi-surface edit "
                f"(currently {len(_CANONICAL_HOOK_SCRIPT_NAMES)} wired). Close these "
                f"sister-sites THIS session:\n{_bullets(_HOOK_COUNT_WITNESSES)}")
    return None


def _render_integrity_parity(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    if any(_fp(tool_input).endswith(t) for t in _INTEGRITY_PARITY_TAILS):
        return ("You edited an integrity SoT. `_integrity.MANIFEST_FILES` and "
                "`surface_contract`'s protected-integrity tuple must stay EQUAL "
                "(tests/test_integrity_contract_parity.py::"
                "test_integrity_manifest_equals_surface_contract); if you changed the "
                "managed set, run `espalier integrity refresh .` before commit.")
    return None


def _render_command_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """Source-side only. ``_COMMAND_FILE_RE``'s ``(^|/)`` anchor is satisfied
    MID-path, so ``examples/dogfooding/.claude/commands/*.md`` matched it and got
    the five-surface source-of-truth message on a generated file. That side is
    already answered correctly by ``_render_claude_surface_sync``'s mirror branch
    (which says the edit will be DISCARDED), so the fix here is silence, not a
    second message. Reachable without maintenance mode -- ``examples/`` is not a
    protected zone -- which made this the most reachable member of the class.
    """
    if tool_name != "Write":
        return None
    fp = _fp(tool_input)
    if _COMMAND_FILE_RE.search(fp) and not _on_generated_mirror(fp):
        return ("You wrote a slash-command file. A command is a five-surface SoT; sync "
                f"the mirrors THIS session:\n{_bullets(_COMMAND_SURFACE_WITNESSES)}")
    return None


def _render_test_loosening(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    if tool_name not in ("Edit", "Write"):
        return None
    if not _TEST_PATH_RE.search(_fp(tool_input)):
        return None
    if _TEST_LOOSEN_RE.search(_new_content(tool_input)):
        return ("Your test edit adds a skip/xfail marker or a broad `raises(Exception)`. "
                "Is the loosening load-bearing, or hiding a regression? Prefer a narrow "
                "exception type + a reason; a skip needs a tracking note. (The offline "
                "test_loosening scanner flags unreasoned skip/xfail markers + tautological "
                "asserts in the current file at /scan + stop_gate; it reads AST state, "
                "not diffs.)")
    return None


def _render_marker_substring(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    if any(fp.endswith(t) for t in _MARKER_CANON_HOME_TAILS):
        return None  # canonical homes legitimately do marker string ops
    if _MARKER_SUBSTRING_RE.search(_new_content(tool_input)):
        return ("Your edit introduces a raw substring membership test over a managed-"
                "marker string. Route through `managed_markers.has_managed_marker` and "
                "anchor to line-start -- substring markers are forgeable (a marker quoted "
                "in a comment or mid-line would false-match).")
    return None


def _render_vendor_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    if tool_name not in ("Edit", "Write"):
        return None
    if _VENDOR_MIRROR_RE.search(_fp(tool_input)):
        return ("You edited a tools/cc/ deploy-source file. espalier/_vendor/cc/ is a "
                "byte-for-byte mirror (tests/test_vendor_cc_parity.py reds on drift) -- "
                "run `python3 scripts/sync_vendor_cc.py` before commit.")
    return None


def _render_docs_asset_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """Fires on the deployed-doc SoT and, with the opposite message, on its mirror.

    Every entry of ``_DOCS_ASSET_TAILS`` is also a suffix of its own
    ``espalier/assets/docs/`` twin, so the bare ``endswith`` this rule used to
    carry answered "run the sync" on BOTH sides -- and ``sync_asset_docs.py``
    copies docs/ -> assets/, so following it on the mirror side deletes the edit
    and exits 0. The mirror branch runs first and says the opposite thing.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    if not any(fp.endswith(t) for t in _DOCS_ASSET_TAILS):
        return None
    if _on_generated_mirror(fp):
        return ("You edited a GENERATED deployed-doc mirror. docs/ is the only source "
                "of truth; `scripts/sync_asset_docs.py` overwrites this file from it, "
                "so this edit will be DISCARDED -- running the sync now would delete it "
                "and report success. Re-apply it to the docs/ original, then sync.")
    return ("You edited a deployed doc. espalier/assets/docs/ ships the adopter "
            "copy (tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity reds "
            "on drift) -- run `python3 scripts/sync_asset_docs.py` before commit.")


# The remaining mirror rows. These patterns are hand-written HERE and cannot read
# espalier/mirror_registry.py -- this file is under tools/cc/ and runs standalone
# with zero espalier imports. The binding is a test rather than an import:
# tests/test_reinject_sync.py::TestMirrorCensusCoverage walks the registry and
# DRIVES this hook once per row, so a row added there with no renderer here reds.
# Anchored at a path boundary, and with the `[\w./_-]*` char class rather than
# `.*` -- see _VENDOR_MIRROR_RE's note on the ReDoS surface test_redos.py forbids.
_CLAUDE_SOT_RE = re.compile(r"(^|/)\.claude/(agents|commands|skills)/[\w./_-]+\.md$")
_CLAUDE_MIRROR_RE = re.compile(
    r"(^|/)(espalier/assets/claude|examples/dogfooding/\.claude)/[\w./_-]+\.md$"
)
_TASK_PACKS_ROUTER_TAIL = "task-packs/CLAUDE.md"
_SELFCHECK_MIRROR_RE = re.compile(r"(^|/)espalier/_vendor/selfcheck_tests/[\w./_-]+$")
_SELFCHECK_MIRROR_DIR = "espalier/_vendor/selfcheck_tests"
# Flat by construction: the mirror is a single directory, so only a direct child
# of tests/ can have a counterpart in it.
_SELFCHECK_SOT_RE = re.compile(r"(^|/)tests/(?P<name>[\w._-]+\.(?:py|ini))$")
#: (canonical source, generated-into target, region name). Both checklists have
#: the same shape: a tools/cc/ .md that `init` never deploys, inlined into a
#: shipped body, with the inline copy GENERATED between markers.
_CHECKLIST_REGIONS: tuple[tuple[str, str, str], ...] = (
    ("tools/cc/pack_artifact_checklist.md",
     ".claude/commands/implement-pack.md", "pack-artifact-checklist"),
    ("tools/cc/reasoning_review_checklist.md",
     ".claude/skills/reflect/SKILL.md", "reasoning-review-checklist"),
)
_GENERATE_DOC_REGIONS_SCRIPT = "scripts/generate_doc_regions.py"

#: ``(target tail, region name, canonical source)`` for the regions rendered
#: from a live Python object by ``scripts/generate_doc_regions.py``.
#: Deliberately NOT derived from ``mirror_registry``: that family is not a
#: byte-mirror and carries no row there, which is exactly why it arrived with
#: no advisory -- the census that FORCES an advisory iterates MIRROR_ROWS and
#: therefore could not see it. Hand-kept here, and pinned against the script's
#: own REGIONS tuple by
#: tests/test_doc_regions.py::TestTheEditTimeAdvisoryCoversEveryRegion
#: (both membership AND the canonical-source string) so the two cannot drift.
_GENERATED_DOC_REGIONS: tuple[tuple[str, str, str], ...] = (
    ("README.md", "deploy-inventory",
     "espalier/managed_inventory.py + espalier/cli.py::INIT_TOOL_SCRIPTS"),
    ("docs/QUICKSTART.md", "deploy-inventory-quickstart",
     "espalier/managed_inventory.py + espalier/cli.py::INIT_TOOL_SCRIPTS"),
    ("docs/QUICKSTART.md", "required-gitignore",
     "espalier/cli.py::REQUIRED_GITIGNORE"),
)
_HARNESS_GUARD_ASSET_TAIL = "espalier/assets/github/workflows/harness-guard.yml"
_HARNESS_GUARD_ROOT_TAIL = ".github/workflows/harness-guard.yml"


def _render_claude_surface_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """One rule for BOTH claude rows -- they share a single SoT and one script.

    Fires on the SoT and, separately, on either mirror. The mirror message must not
    say "run the sync": the edit is already lost, because the generator overwrites
    the mirror from .claude/. Telling the author to sync would silently discard
    their work and report success.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    if _CLAUDE_MIRROR_RE.search(fp):
        return ("You edited a GENERATED claude mirror. .claude/{agents,commands,skills} "
                "is the only source of truth; scripts/sync_claude_mirrors.py overwrites "
                "this file from it, so this edit will be DISCARDED. Re-apply it to the "
                ".claude/ original, then run the sync.")
    if _CLAUDE_SOT_RE.search(fp):
        return ("You edited the .claude/ source of truth. TWO mirrors are byte-pinned to "
                "it (espalier/assets/claude/ and examples/dogfooding/.claude/, "
                "tests/test_package_resource_parity.py) -- run "
                "`python3 scripts/sync_claude_mirrors.py` before commit.")
    return None


def _render_task_packs_router_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """The router that sits OUTSIDE docs/, so the docs-asset rule never sees it.

    Same two-sided shape as ``_render_docs_asset_sync``: the mirror path
    ``espalier/assets/task-packs/CLAUDE.md`` ends with the SoT tail, so the bare
    ``endswith`` answered "run the sync" on the generated side too.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    if not fp.endswith(_TASK_PACKS_ROUTER_TAIL):
        return None
    if _on_generated_mirror(fp):
        return ("You edited the GENERATED task-packs router mirror. "
                "task-packs/CLAUDE.md is the source of truth; "
                "`scripts/sync_asset_docs.py` overwrites this file from it, so this "
                "edit will be DISCARDED. Re-apply it to task-packs/CLAUDE.md, then sync.")
    return ("You edited task-packs/CLAUDE.md. It is byte-mirrored to "
            "espalier/assets/task-packs/CLAUDE.md and pinned SEPARATELY from the "
            "docs mirrors (tests/test_deploy_doc_parity.py::"
            "TestSourceAssetDocByteParity::test_task_packs_asset_matches_source) -- "
            "run `python3 scripts/sync_asset_docs.py` before commit.")


def _render_selfcheck_mirror_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """The second family under espalier/_vendor/, with a DIFFERENT sync script.

    Fires on the mirror side only. The source side is a curated subset of tests/,
    and firing on every tests/ edit would be noise -- the calibration lesson
    recorded on _ARTIFACT_PROXY_RE.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    if _SELFCHECK_MIRROR_RE.search(fp):
        # Lead with the DISCARD, not with which script governs the family. The
        # earlier wording answered only "which of the two _vendor/ scripts is
        # yours" and then named it -- and that script copies tests/ ONTO this
        # file, so the one action the message made obvious was the one that
        # destroys the edit. Same shape as the docs-asset and task-packs-router
        # mirror leaks: a generated-side advisory whose remedy overwrites the
        # generated side.
        return ("You edited a GENERATED mirror. espalier/_vendor/selfcheck_tests/ is a "
                "copy of a CURATED tests/ subset; `scripts/sync_selfcheck_tests.py` "
                "overwrites this file from tests/, so this edit will be DISCARDED -- "
                "running the sync now would delete it. Re-apply it to the tests/ "
                "original, then sync. (Note this is NOT the tools/cc/ vendor mirror "
                "next to it: sync_vendor_cc.py will not fix this and exits 0; "
                "tests/test_selfcheck_tests_parity.py reds on drift.)")
    # Source side. Only PART of tests/ is mirrored, so membership is decided by
    # asking whether the counterpart exists -- never by a tests/ prefix, which
    # would fire on hundreds of unmirrored files and get the rule tuned out.
    # The mirror tree is the oracle; this file cannot import the registry that
    # says so (zero espalier imports), but it can stat the same tree.
    m = _SELFCHECK_SOT_RE.search(fp)
    if m and (root / _SELFCHECK_MIRROR_DIR / m.group("name")).exists():
        return ("You edited a test that is MIRRORED into "
                "espalier/_vendor/selfcheck_tests/ (only a curated subset of tests/ is). "
                "Run `python3 scripts/sync_selfcheck_tests.py` before commit -- "
                "tests/test_selfcheck_tests_parity.py reds on drift. Note the mirror is "
                "not a plain copy: some files are rewritten in transit.")
    return None


def _render_pack_checklist_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """The CHAINED row: its mirror is another row's SOURCE, so two syncs run in order.

    Source side only, deliberately. The generated region lives inside
    .claude/commands/implement-pack.md, and the claude-surface rule already fires
    on every edit to that file for all the other reasons someone edits it. A
    second payload there would attach to edits that never touch the region --
    the calibration lesson recorded on _ARTIFACT_PROXY_RE.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    hit = next((r for r in _CHECKLIST_REGIONS if fp.endswith(r[0])), None)
    if hit is None:
        return None
    _, target, _name = hit
    # No count here. The items are GENERATED from this file, so stating how many
    # there are would restate a number this very edit can change -- the rule the
    # blueprint-authoring skill states as "never restate a count another surface
    # owns", broken in the advisory that ships alongside it.
    return (f"You edited a canonical fixed checklist. Its items are GENERATED "
            f"into a marked region of {target}, and that file is itself the "
            "source of the .claude mirrors -- so TWO syncs run, in this order: "
            "`python3 scripts/sync_checklist_regions.py`, THEN "
            "`python3 scripts/sync_claude_mirrors.py`. Running only the second "
            "propagates the stale region into both mirrors byte-perfectly.")


def _render_pack_checklist_region_edit(tool_name: str, tool_input: dict,
                                       root: Path) -> "str | None":
    """The side that is actually WRITABLE, and was being told the wrong thing.

    ``tools/cc/`` is a protected zone, so the source-side rule above only fires
    under maintenance mode. ``.claude/commands/`` is not protected -- so the
    reachable path for a hurried session is to grep an item's text, hit the
    command body, and edit it there. Before this rule the only payload it got was
    the generic claude-mirror advisory: "run sync_claude_mirrors.py". Following
    that literally propagates the hand edit into both mirrors, reds the region
    test against the SoT, and the eventual repair DISCARDS the edit.

    Content-gated so ordinary edits to this command -- which has many other
    sections -- stay silent. That is the _ARTIFACT_PROXY_RE calibration lesson,
    and it is the same shape REINJECT-TEST-LOOSENING already uses.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    hit = next((r for r in _CHECKLIST_REGIONS if fp.endswith(r[1])), None)
    if hit is None:
        return None
    sot, _target, name = hit
    blob = "".join(str(tool_input.get(k, "") or "")
                   for k in ("old_string", "new_string", "content"))
    if f"{name}:" not in blob and not any(
        w in blob for w in ("Line-number accuracy", "Agent composition adequacy")
    ):
        return None
    return (f"That checklist region is GENERATED and your edit will be DISCARDED "
            f"by the next sync. Re-apply it to {sot} (the source of truth), then "
            "run `python3 scripts/sync_checklist_regions.py` THEN "
            "`python3 scripts/sync_claude_mirrors.py` -- in that order. Running "
            "only the mirror sync propagates your edit and then loses it.")


def _render_generated_doc_region_edit(tool_name: str, tool_input: dict,
                                      root: Path) -> "str | None":
    """A hand edit inside a Python-sourced doc region, which will be discarded.

    ``README.md`` and ``docs/QUICKSTART.md`` are unprotected and heavily edited,
    so the reachable path is: someone corrects a path or a count directly in the
    front door, it looks right, and the next ``generate_doc_regions.py`` run
    reverts it -- or nobody runs it and the block rots exactly as the hand-list
    it replaced did.

    Content-gated on the region name so ordinary edits to these two large docs
    stay silent (the ``_ARTIFACT_PROXY_RE`` calibration lesson). Says what to
    change instead: the region's content comes from a Python object, so the fix
    is upstream and then a regenerate -- never a retype.

    Matched on the ROOT-RELATIVE path, not a suffix. ``README.md`` is a bare
    basename: ``endswith`` made this rule fire on every README in the tree --
    ``docs/sharp-edges/``, ``task-packs/``, ``examples/dogfooding/`` and its
    ``contracts/`` subdir, ``espalier/assets/docs/sharp-edges/`` -- all verified.
    Only the content gate kept the blast radius down, and a content gate is not a
    path identity. Same root cause as the mirror-side leaks above: a suffix test
    standing in for "is this THE file".

    Relativised through ``_hook_utils.normalize_path`` -- that module's declared
    "single source of truth for path normalization" -- and NOT a local helper. A
    hand-rolled ``fp.startswith(str(root))`` strip looks equivalent and silently
    retires the rule on five path forms this repo actually emits: ``./README.md``,
    the literal ``$CLAUDE_PROJECT_DIR/`` and ``${CLAUDE_PROJECT_DIR}/`` prefixes
    that Write ``tool_input`` carries verbatim (``normalize_path``'s own docstring
    names that case), a ``~/`` form, and any path containing ``..``. Going SILENT
    is the wrong failure direction for an advisory -- and the local copy also
    reddened ``sister_site_probe.py`` as a fourth divergent ``_rel``.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = normalize_path(_fp(tool_input), root)
    blob = "".join(str(tool_input.get(k, "") or "")
                   for k in ("old_string", "new_string", "content"))
    hit = next((r for r in _GENERATED_DOC_REGIONS
                if fp == r[0] and f"{r[1]}:" in blob), None)
    if hit is None:
        return None
    _target, name, source = hit
    return (f"That `{name}` region is GENERATED and your edit will be DISCARDED "
            f"by the next run of `python3 {_GENERATE_DOC_REGIONS_SCRIPT}`. Its "
            f"content comes from {source} -- change it there, then regenerate. "
            "Editing the rendered block is never the fix.")


def _render_harness_guard_sync(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """The one INVERTED row: the packaged asset is the SoT, the root file is generated.

    "Edit the file where it lives" is right for every other mirror in this repo and
    wrong here, and the wrong case looks exactly like the other workflow files in
    the same directory. Both messages name the DIRECTION explicitly, because a
    reader who reaches them is holding the wrong model and "run the sync" alone
    would let them re-apply the fix backwards.
    """
    if tool_name not in ("Edit", "Write"):
        return None
    fp = _fp(tool_input)
    if fp.endswith(_HARNESS_GUARD_ROOT_TAIL):
        return ("You edited .github/workflows/harness-guard.yml, which is GENERATED. "
                "Unlike every other mirror here the direction is INVERTED: "
                "espalier/assets/github/workflows/harness-guard.yml is the source of "
                "truth. Re-apply this edit to the ASSET, then run "
                "`python3 scripts/sync_github_workflow_asset.py` -- running it now would "
                "overwrite what you just wrote (the script refuses unless --force). "
                "This path is in _integrity.MANIFEST_FILES, so run "
                "`espalier integrity refresh .` after syncing. "
                "tests/test_package_resource_parity.py::TestRootMirrorParity"
                "::test_root_workflow_mirrors_package reds on drift.")
    if fp.endswith(_HARNESS_GUARD_ASSET_TAIL):
        return ("You edited the harness-guard workflow ASSET -- correct, it is the source "
                "of truth, and .github/workflows/harness-guard.yml is generated FROM it. "
                "Run `python3 scripts/sync_github_workflow_asset.py` before commit, then "
                "`espalier integrity refresh .` (the generated copy is in "
                "_integrity.MANIFEST_FILES); tests/test_package_resource_parity.py reds "
                "on the drift.")
    return None


# Anchored to a COMMAND POSITION (start of string, or after `;` `|` `&` newline, or
# a `$(` command substitution), matching _bash_patterns.py's convention. Two
# calibration passes, both against real misfires:
#   1. An unanchored `\bgit\s+archive\b` matched the phrase inside an ARGUMENT --
#      it fired on a blueprint `record --description "...git archive..."` that
#      merely quoted it.
#   2. Accepting a bare `(` as a separator (intended for subshells) then matched
#      PROSE parentheses -- `"(git archive + sdist)"` inside that same description.
# Command substitution is `$(`, never a lone `(`. A recall rule that cries wolf on
# prose is one that gets tuned out, so this anchoring is load-bearing, not cosmetic.
_ARTIFACT_PROXY_RE = re.compile(r"(?:^|[;|&\n]|\$\()\s*(?:sudo\s+)?git\s+archive\b")


def _render_artifact_proxy(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    """`git archive` is index-based, so it cannot answer "what actually ships".

    Fires AFTER the command, when the output is in hand and about to be believed.
    Chosen because the blindness is structural rather than situational: the archive
    is built from the git INDEX, so it can never contain an untracked file, and it
    honours ``export-ignore``, so it silently omits tracked paths a filesystem-walking
    packager would include. Both directions read CLEAN. Two independent probes
    (`git archive` and an sdist build) agreeing is not confirmation -- they are blind
    for the identical reason.
    """
    if tool_name not in ("Bash", "PowerShell"):
        return None
    if not _ARTIFACT_PROXY_RE.search(str(tool_input.get("command") or "")):
        return None
    return (
        "`git archive` reads the git INDEX, not the working tree -- so it can never "
        "show an untracked file, and `.gitattributes` `export-ignore` silently drops "
        "tracked paths from it. If you are asking *what actually ships*, this cannot "
        "answer: a filesystem-walking packager includes both. Attested twice here -- a "
        "package asset that `init` needed was export-ignored out of the archive AND out "
        "of the probe, and untracked scratch shipped in a release zip while every "
        "archive-based check stayed green. Drive the real artifact instead (a real "
        "`clone` / `init` / non-editable install) and diff it. **A proxy is usable for a "
        "floor, never for a null** -- absence in the proxy is not absence in the artifact, "
        "and two proxies agreeing is not confirmation when both read the same wrong source."
    )


NEW_HOOK_RULE = ReinjectRule(
    id="REINJECT-HOOK-WITHOUT-WIRING", event="PostToolUse",
    render=_render_new_hook_witness, face="sync", priority=70,
)
ARTIFACT_PROXY_RULE = ReinjectRule(
    id="REINJECT-ARTIFACT-PROXY-ORACLE", event="PostToolUse",
    render=_render_artifact_proxy, face="sync", priority=68,
)
COMMAND_SYNC_RULE = ReinjectRule(
    id="REINJECT-COMMAND-FILE-SYNC", event="PostToolUse",
    render=_render_command_sync, face="sync", priority=66,
)
INTEGRITY_PARITY_RULE = ReinjectRule(
    id="REINJECT-INTEGRITY-SoT-PARITY", event="PostToolUse",
    render=_render_integrity_parity, face="sync", priority=62,
)
TEST_LOOSENING_RULE = ReinjectRule(
    id="REINJECT-TEST-LOOSENING", event="PostToolUse",
    render=_render_test_loosening, face="sync", priority=60,
)
MARKER_SUBSTRING_RULE = ReinjectRule(
    id="REINJECT-MARKER-SUBSTRING", event="PostToolUse",
    render=_render_marker_substring, face="sync", priority=58,
)
VENDOR_SYNC_RULE = ReinjectRule(
    id="REINJECT-VENDOR-CC-SYNC", event="PostToolUse",
    render=_render_vendor_sync, face="sync", priority=56,
)
DOCS_ASSET_SYNC_RULE = ReinjectRule(
    id="REINJECT-DOCS-ASSET-SYNC", event="PostToolUse",
    render=_render_docs_asset_sync, face="sync", priority=54,
)
# The remaining mirror-registry rows (added when the census found them with no
# edit-time advisory). Coverage is judged against espalier/mirror_registry.py,
# never against a count here: tests/test_reinject_sync.py::TestMirrorCensusCoverage
# drives this hook once per registry row. Priorities continue the existing
# even-numbered descent and stay clustered with the two mirror rules above, so the
# per-turn ceiling drops the least-specific mirror advice first.
CLAUDE_SURFACE_SYNC_RULE = ReinjectRule(
    id="REINJECT-CLAUDE-SURFACE-SYNC", event="PostToolUse",
    render=_render_claude_surface_sync, face="sync", priority=52,
)
TASK_PACKS_ROUTER_SYNC_RULE = ReinjectRule(
    id="REINJECT-TASK-PACKS-ROUTER-SYNC", event="PostToolUse",
    render=_render_task_packs_router_sync, face="sync", priority=50,
)
SELFCHECK_MIRROR_SYNC_RULE = ReinjectRule(
    id="REINJECT-SELFCHECK-MIRROR-SYNC", event="PostToolUse",
    render=_render_selfcheck_mirror_sync, face="sync", priority=48,
)
HARNESS_GUARD_SYNC_RULE = ReinjectRule(
    id="REINJECT-HARNESS-GUARD-SYNC", event="PostToolUse",
    render=_render_harness_guard_sync, face="sync", priority=46,
)
PACK_CHECKLIST_SYNC_RULE = ReinjectRule(
    id="REINJECT-PACK-CHECKLIST-SYNC", event="PostToolUse",
    render=_render_pack_checklist_sync, face="sync", priority=44,
)
PACK_CHECKLIST_REGION_RULE = ReinjectRule(
    id="REINJECT-PACK-CHECKLIST-REGION", event="PostToolUse",
    render=_render_pack_checklist_region_edit, face="sync", priority=42,
)
GENERATED_DOC_REGION_RULE = ReinjectRule(
    id="REINJECT-GENERATED-DOC-REGION", event="PostToolUse",
    render=_render_generated_doc_region_edit, face="sync", priority=40,
)


# Registry consumed by check(): the SessionStart orientation row, the consolidated
# PostToolUseFailure Rule A, and the PostToolUse multi-surface-sync rows (count
# pinned by tests/test_reinject_sync.py, not restated here -- it was stale by one
# before this comment was rewritten and by five after). New
# rules append rows only -- no new wiring, no hook-count change.
# ── Event-keyed pointers to the catalog ───────────────────────────────────────
# The pull side of the recall engine (`/recall`, `_recall.py`) needs the
# HAZARD's vocabulary; a lane's task text carries the GOAL's. Measured
# 2026-09-06 across two lanes: seven task and step texts recalled NONE of the
# four catalog entries the red teams then found applicable (escaped pipes in a
# markdown table, a new test file defaulting to `unit`, `python3` in an
# operator doc, a hand-kept inventory), while the hazard words recalled all
# four. Telemetry for the same day: 3 PostToolUse pushes in hundreds of tool
# calls, because heredoc edits carry no file_path (post_write_check now
# derives them). So these rows key on the EVENT that carries the hazard and
# point at the mechanical gate that would otherwise red, plus the catalog
# entry. Once per session each, frictionless like every row, and each
# referent they name is pinned by tests/test_reinject_pins.py so a pointer
# cannot rot into a lie.

_TEST_FILE_RE = re.compile(r"(^|/)tests/test_[a-z0-9_]+\.py$")
_SCRIPT_FILE_RE = re.compile(r"(^|/)scripts/[a-z0-9_]+\.py$")
#: The population tests/test_portability_contract.py scans -- restated because
#: a hook cannot import tests/; the pin test binds the two.
_OPERATOR_DOC_RE = re.compile(
    r"(^|/)(README\.md|docs/CHEAT-SHEET\.md|docs/SHARP_EDGES\.md"
    r"|\.claude/(agents|commands)/[^/]+\.md)$"
)
_LEDGER_PARSER_RE = re.compile(r"(^|/)(scripts|tools)/.{1,256}\.py$")   # bounded: ReDoS class 5
_PIPE_SPLIT_RE = re.compile(r"""split\(\s*['"]\|['"]""")


def _once_flag(root: Path, rid: str) -> Path:
    return root / STATE_DIR / f"reinject_once_{rid}"


def _mark_once(root: Path, rid: str) -> None:
    try:
        flag = _once_flag(root, rid)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("1", encoding="utf-8")
    except OSError:
        pass   # no state dir: the row may fire again; never raise in a reporter


def _is_tracked(root: Path, rel: str) -> bool:
    """Is ``rel`` in git's index? A NEW file is the event these rows key on; an
    edit to a tracked one is not. Module-level so the tests bind it without a
    subprocess. When git cannot be asked the answer is 'tracked': silence on a
    guess, never noise."""
    import subprocess
    try:
        rc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
            capture_output=True, timeout=5,
        ).returncode
    except (OSError, subprocess.TimeoutExpired):
        return True
    # 0 = tracked; 1 = git answered "not tracked"; anything else (128: not a
    # repository at all) is git NOT answering, and a non-answer is silence
    if rc == 0:
        return True
    return rc != 1


def _written_text(tool_input: dict, base: Path, rel: str) -> str:
    """The post-write content: Write/Edit carry it in tool_input; a path derived
    from a Bash command does not, so read the file (PostToolUse runs after)
    from ``base``, the checkout ``_pointer_target`` found it in."""
    text = _new_content(tool_input)
    if text:
        return text
    try:
        return (base / rel).read_text(encoding="utf-8", errors="replace")[:200_000]
    except (OSError, ValueError):
        return ""


def _pointer_target(
    tool_input: dict, root: Path, pattern: "re.Pattern[str]",
) -> "tuple[Path, str] | None":
    """``(base, rel)`` for the path a pointer row may speak about, or None: the
    pattern must match, the path must not be a generated mirror, must
    relativise INSIDE a checkout of the repository -- the root, or a registered
    worktree of it (DEF-743; an absolute path `resolve_in_checkout` could not
    fold under one would make `base / rel` escape it -- code-review pass,
    driven on a /tmp README) -- and must exist there after the call (a Write
    or Edit always leaves it; a Bash-derived candidate that is only mentioned
    in a string literal does not). ``base`` is where the file is read back and
    whose index answers "tracked?"; ``rel`` is what the row names."""
    fp = _fp(tool_input)
    if not fp or not pattern.search(fp) or _on_generated_mirror(fp):
        return None
    try:
        base, rel = resolve_in_checkout(fp, root)
    except (OSError, ValueError):
        return None
    if not rel or Path(rel).is_absolute() or rel.startswith(("..", "/", "\\")) or ":" in rel[:3]:
        return None
    try:
        if not (base / rel).is_file():
            return None
    except OSError:
        return None
    return base, rel


def _render_new_test_file(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    hit = _pointer_target(tool_input, root, _TEST_FILE_RE)
    if hit is None or _once_flag(root, "REINJECT-NEW-TEST-FILE-CLASSIFY").exists():
        return None   # spent for the session: no git call on the hot path
    base, rel = hit
    if _is_tracked(base, rel):
        return None
    return (
        f"New test file `{rel}`: a stem absent from tests/conftest.py::_MARKER_RULES is "
        "`unit` SILENTLY, and a file that spawns a process must also be in _SLOW_FILES "
        "(or carry `# slow-exempt: <reason>`). Classify it now, `git add -N` it so the "
        "gates that read `git ls-files` see it in the next run (an untracked file is "
        "invisible to them until it is committed), then run the enumerator pins: "
        "`pytest tests/test_marker_taxonomy.py tests/test_test_suite_contract.py -q`. "
        "Recall: docs/SHARP_EDGES.md :: New Test Files Default to `unit` Silently."
    )


def _render_new_script(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    hit = _pointer_target(tool_input, root, _SCRIPT_FILE_RE)
    if hit is None or _once_flag(root, "REINJECT-NEW-SCRIPT-INVENTORY").exists():
        return None
    base, rel = hit
    if _is_tracked(base, rel):
        return None
    return (
        f"New script `{rel}`: scripts/ is inventory-pinned by tests/_surface_expected.py::"
        "EXPECTED_SCRIPT_NAMES -- add the name with a dated line (EXPECTED_SCRIPT_COUNT is "
        "derived from that roster; never hand-edit the count), "
        "`git add -N` the file so the gates that read `git ls-files` (encoding pins, "
        "citation resolvers) see it before the commit, and run `pytest "
        "tests/test_test_suite_contract.py tests/test_contracts.py -q`. Recall: docs/SHARP_EDGES.md :: "
        "A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently."
    )


def _render_operator_doc_interpreter(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    hit = _pointer_target(tool_input, root, _OPERATOR_DOC_RE)
    if hit is None:
        return None
    base, rel = hit
    text = _written_text(tool_input, base, rel)
    if "python3 " not in text and "/tmp/" not in text:
        return None
    return (
        f"`{rel}` is an operator doc and now carries `python3 ` or `/tmp/`: tests/"
        "test_portability_contract.py::test_operator_docs_no_unix_only_default_workflows "
        "forbids both (Windows ships no `python3`; the docs stay bare `python`, or a shell "
        "block uses `PY=python3; command -v \"$PY\" >/dev/null 2>&1 || PY=python`). "
        "Recall: docs/SHARP_EDGES.md :: Two operator-doc contracts can collide on one line."
    )


def _render_ledger_parser(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    hit = _pointer_target(tool_input, root, _LEDGER_PARSER_RE)
    if hit is None:
        return None
    base, rel = hit
    if rel.endswith("hooks/_reinject.py"):
        return None   # the rule's own defining module names both files; a detector exempts itself
    text = _written_text(tool_input, base, rel)
    if "FORWARD_LEDGER.md" not in text and "LEDGER_PROBES.json" not in text:
        return None
    if not _PIPE_SPLIT_RE.search(text):
        return None
    return (
        f"`{rel}` splits the ledger's markdown tables on `|`: split on UNESCAPED pipes only "
        "(`re.split(r\"(?<!\\\\)\\|\", ...)`) and refuse a row that is not the cell count you "
        "expect -- the ledger escapes a literal pipe as `\\|`, dozens of rows carry one, and "
        "scripts/generate_ledger_regions.py owns the member-row parsers. Recall: "
        "docs/SHARP_EDGES.md :: Markdown Escaped Pipes Silently Drop Matrix Rows."
    )


NEW_TEST_FILE_RULE = ReinjectRule(
    id="REINJECT-NEW-TEST-FILE-CLASSIFY", event="PostToolUse",
    render=_render_new_test_file, face="sync", cap_exempt=True, priority=76,
    once_per_session=True,
)
NEW_SCRIPT_RULE = ReinjectRule(
    id="REINJECT-NEW-SCRIPT-INVENTORY", event="PostToolUse",
    render=_render_new_script, face="sync", cap_exempt=True, priority=74,
    once_per_session=True,
)
OPERATOR_DOC_INTERPRETER_RULE = ReinjectRule(
    id="REINJECT-OPERATOR-DOC-INTERPRETER", event="PostToolUse",
    render=_render_operator_doc_interpreter, face="sync", cap_exempt=True, priority=78,
    once_per_session=True,
)
LEDGER_PARSER_RULE = ReinjectRule(
    id="REINJECT-LEDGER-TABLE-PARSER", event="PostToolUse",
    render=_render_ledger_parser, face="sync", cap_exempt=True, priority=72,
    once_per_session=True,
)

REINJECTS: tuple[ReinjectRule, ...] = (
    ORIENT_RULE, RULE_A,
    OPERATOR_DOC_INTERPRETER_RULE, NEW_TEST_FILE_RULE, NEW_SCRIPT_RULE, LEDGER_PARSER_RULE,
    NEW_HOOK_RULE, ARTIFACT_PROXY_RULE, COMMAND_SYNC_RULE, INTEGRITY_PARITY_RULE,
    TEST_LOOSENING_RULE, MARKER_SUBSTRING_RULE,
    VENDOR_SYNC_RULE, DOCS_ASSET_SYNC_RULE,
    CLAUDE_SURFACE_SYNC_RULE, TASK_PACKS_ROUTER_SYNC_RULE,
    SELFCHECK_MIRROR_SYNC_RULE, HARNESS_GUARD_SYNC_RULE,
    PACK_CHECKLIST_SYNC_RULE, PACK_CHECKLIST_REGION_RULE,
    GENERATED_DOC_REGION_RULE,
)


# ── the generative EXEMPLAR_MAP catalog ──────────────────────────────────────
# The generative face injects the canonical exemplar BEFORE an artifact is born, at
# UserPromptSubmit (task_router dispatch). The generative RAIL: an exemplar may be
# auto-PUSHED only via a ReinjectRule(face="generative", push_eligible=True) that has
# a red-on-violation parity test (tests/test_exemplar_parity.py) byte-deriving it from
# its canonical source. But most canonical shapes (a scanner's contract, a hook's
# posture, a pack skeleton) are CROSS-FILE abstractions with no single byte-source,
# so they cannot be parity-pinned -> they ship PULL-ONLY: catalogued here, served by
# the _recall.py pull engine, NEVER auto-injected. The catalog ships ALL pull-only
# (zero generative REINJECTS rows; every Exemplar push_eligible=False); the dispatch
# is wired so no later change re-touches task_router.


class Exemplar(NamedTuple):
    """A catalogued canonical shape served (later) by the recall engine.

    ``trigger`` is a plain ``re`` pattern SOURCE (the pull engine compiles and
    matches it against the prompt; the catalog is inert DATA -- nothing fires here).
    ``source`` points at where the canonical shape actually lives -- a path, or a
    cross-file note when no single file embodies it. ``push_eligible`` is the
    generative gate: True requires BOTH a parity test AND a generative REINJECTS row;
    False (the default, and every entry here) means ``/recall`` pull-only.
    """
    id: str
    trigger: str
    source: str
    push_eligible: bool = False


EXEMPLAR_MAP: dict[str, Exemplar] = {
    "GEN-NEW-SCANNER": Exemplar(
        id="GEN-NEW-SCANNER",
        trigger=r"\bnew\b.{0,40}\bscanner\b",
        source="espalier/scanners/<name>.py + its earn-the-gate fixture + must-NOT-trip "
               "negative corpus + tests/test_scanners.py (cross-file contract: stdlib-"
               "only + earn-fixture + negative-corpus; no single byte-source -> pull-only)",
    ),
    "GEN-NEW-HOOK": Exemplar(
        id="GEN-NEW-HOOK",
        trigger=r"\bnew\b.{0,40}\bhook\b",
        source="tools/cc/hooks/<name>.py (cross-file posture: channel-XOR + "
               "read_stdin_safely stdin contract + zero-espalier-imports + reporter/gate "
               "shape; no single byte-source -> pull-only)",
    ),
    "GEN-NEW-TEST": Exemplar(
        id="GEN-NEW-TEST",
        trigger=r"\bnew\b.{0,40}\btest\b",
        source="tests/test_<module>.py (project idiom: class-per-feature, "
               "test_<behavior>, the fixture shape; the shape spans the suite -> pull-only)",
    ),
    "GEN-PACK-SKELETON": Exemplar(
        id="GEN-PACK-SKELETON",
        trigger=r"\bdraft\b.{0,30}\bpack\b",
        source="task-packs/TP-<n>-<slug>.md (required sections: Task 0 verify -- its "
               "outcomes include DO NOT BUILD THIS, Affected symbols, Reach if the pack "
               "claims a class, Pass criteria, Sub-task ordering; per-pack prose varies "
               "-> pull-only)",
    ),
    "GEN-CHANGELOG-FLATPROSE": Exemplar(
        id="GEN-CHANGELOG-FLATPROSE",
        trigger=r"\bchangelog\b",
        source="CHANGELOG.md [Unreleased] flat-prose contract (intentionally empty "
               "between releases -> no stable byte-source -> pull-only)",
    ),
}


def _log_recall_event(root: Path, **fields: object) -> None:
    """Append one recall-engine telemetry record. Never raises (reporter discipline).

    ``**fields`` is annotated because ``[tool.mypy] disallow_untyped_defs`` is
    scoped to ``files = ["tools/cc/hooks"]`` and CI runs ``mypy tools/cc/hooks/``;
    an unannotated ``**fields`` reds that job while pytest stays green.
    """
    if not _telemetry_enabled(root):
        return
    _append_jsonl(root / STATE_DIR, RECALL_LOG_NAME, fields)


def check(
    event: str,
    tool_name: str,
    tool_input: dict,
    root: Path,
    *,
    rules: tuple[ReinjectRule, ...] = REINJECTS,
    budget: "int | None" = None,
) -> list[str]:
    """Return the additionalContext payloads to inject for ``event``, ceiling-capped.

    ``cap_exempt`` rules bypass the session cap but STILL count against the
    per-turn slice (they are inside the same ``[:REINJECT_PER_TURN_CAP]`` window);
    non-exempt rules consume one flocked session slot per fire. A render that
    raises is swallowed (a reporter never crashes the hook). The ``rules`` keyword
    mirrors ``_speedbump.check(..., bumps=)`` so the registry-injection canary test
    can inject a synthetic registry without monkeypatching the module global.
    """
    matched = []                                 # [(priority, cap_exempt, text, rule_id)]
    for rule in rules:
        if rule.event != event:
            continue
        # Mechanical (not just test-enforced): a generative rule auto-injects ONLY if
        # push_eligible. The parity rail guarantees push_eligible => parity-tested, so
        # this makes "pull-only = never auto-pushed" true in the firing path -- a
        # pull-only generative row mistakenly placed in REINJECTS silently does NOT
        # fire (served by /recall). No-op until a generative row exists; non-generative
        # faces (orientation/defensive/sync) are unaffected.
        if rule.face == "generative" and not rule.push_eligible:
            continue
        try:
            text = rule.render(tool_name, tool_input, root)
        except Exception:  # noqa: BLE001 -- a render error never blocks/raises (reporter)
            continue
        if text:
            matched.append((rule.priority, rule.cap_exempt, text, rule.id, rule.once_per_session))
    if not matched:
        return []
    # once-per-session rows that already fired drop out BEFORE the per-turn
    # slice is cut, so a spent pointer never displaces a live row from it.
    live = []
    for m in matched:
        if m[4] and _once_flag(root, m[3]).exists():
            _log_recall_event(root, side="push", rid=m[3], event=event,
                              disposition="once_suppressed", exempt=m[1])
            continue
        live.append(m)
    matched = live
    if not matched:
        return []
    # cap_exempt rows sort first; they COUNT AGAINST the per-turn slice (they are
    # inside the same [:CAP] window). Registering >CAP exempt rows on ONE event
    # would therefore starve every non-exempt row on that event -- a documented
    # invariant for future-pack authors, exercised by the canary test.
    matched.sort(key=lambda m: (not m[1], -m[0]))      # cap_exempt first, then priority
    # ``budget`` is the caller's remaining per-turn slots (the Bash bridge asks
    # once per written path); the slice is never wider than the module cap.
    # Cutting it HERE, where the once-flag is marked, is what keeps a marked
    # row and an emitted row the same set -- a caller that trims the returned
    # list would spend flags on text nobody saw (failure-mode pass, driven).
    slice_n = REINJECT_PER_TURN_CAP if budget is None else max(0, min(budget, REINJECT_PER_TURN_CAP))
    out: list[str] = []
    for _prio, exempt, text, rid, once in matched[:slice_n]:
        if exempt:
            out.append(text)
            if once:
                _mark_once(root, rid)    # after the emit decision, never before
            _log_recall_event(root, side="push", rid=rid, event=event,
                              disposition="emitted", exempt=True)
        else:
            # one flocked session slot per non-exempt fire. NOTE: unlike
            # _speedbump's compare-inside-lock, _locked_increment ALWAYS increments
            # then we compare post-hoc -- so reinject_count climbs past CAP on
            # suppressed fires (harmless given the >CAP guard; do NOT reuse the raw
            # value as a 'fires remaining' display).
            n = _locked_increment(root / STATE_DIR, REINJECT_COUNTER)
            if n > REINJECT_SESSION_CAP:
                _log_recall_event(root, side="push", rid=rid, event=event,
                                  disposition="session_capped", exempt=False)
                continue
            out.append(text)
            if once:
                _mark_once(root, rid)    # a session-capped once row stays unspent
            _log_recall_event(root, side="push", rid=rid, event=event,
                              disposition="emitted", exempt=False)
    # The rules that MATCHED but lost the per-turn race -- otherwise invisible.
    # This loop runs AFTER the emit loop, never fused into it: fusing would change
    # when _locked_increment fires relative to the log write, making session-cap
    # accounting depend on log-write success.
    for _prio, exempt, _text, rid, _once in matched[slice_n:]:
        _log_recall_event(root, side="push", rid=rid, event=event,
                          disposition="per_turn_capped", exempt=exempt)
    return out
