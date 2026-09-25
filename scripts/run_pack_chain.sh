#!/usr/bin/env bash
# run_pack_chain.sh - autonomous task-pack chain driver (PILOT / draft)
#
# Dev-only maintainer tool: not packaged, never reaches an adopter wheel/sdist
# (see docs/AUTONOMOUS_EXECUTION.md). Kept in-tree for unattended self-maintenance.
#
# Runs each task pack as its OWN fresh `claude -p` session. The SessionStart hook
# auto-injects the on-disk baton (blueprint + MEMORY) before the model's first
# turn. The -p goal INVOKES the real /implement-pack slash command (so its whole
# body runs, not a paraphrased subset) and requires the session to write one
# cc/_pack_receipt.json the driver verifies. Fresh context per pack = the token
# saving; the on-disk baton is the only state that crosses the session boundary.
#
# SAFETY (each gate is an INDEPENDENT oracle - never the goal's self-report):
#   * Scope gate (advisory): before spending -p budget, run `espalier scope-check`
#     and fold any undeclared references into the goal so the session widens the
#     pack. It never halts on scope - scope-check is a signal, not a gate, and its
#     severity is too noisy for an automated halt; a genuinely major scope problem
#     is caught by the -p session's own /implement-pack review + the gates below.
#   * Chain preflight: validate EVERY named pack resolves to exactly one pack-shaped
#     file before the first -p fires, so a typo'd pack N never wastes packs 1..N-1.
#   * Halts the WHOLE chain if any pack fails - in -p there is no human to triage,
#     so we never build pack N+1 on a broken pack N.
#   * Verifies each pack actually committed, re-runs the red-team's blocker repros,
#     and re-checks green in a clean install env before advancing.
#   * Resume ledger: a re-invoke skips already-landed packs (--fresh resets it). A
#     separate committed-but-ungated marker (written the instant HEAD advances) lets a
#     re-invoke re-gate a pack whose commit landed but whose post-commit gates did not
#     finish, instead of re-running the session and false-halting as nocommit.
#   * Commits are LOCAL only. Nothing is ever pushed.
#
# Usage:
#   ./run_pack_chain.sh TP-NNN TP-MMM                 # run (NO $ cap by default)
#   ./run_pack_chain.sh --dry-run TP-NNN              # print plan, run nothing
#   ./run_pack_chain.sh --budget 8 TP-NNN             # opt in to an $8/pack cap
#   ./run_pack_chain.sh --fresh TP-NNN TP-MMM         # ignore the resume ledger
set -uo pipefail

# Absolute dir of THIS script, so helpers can import sibling scripts/ modules
# (e.g. check_pack_landing) regardless of the cwd the driver runs a pack from.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=0
FRESH=0
# Per-pack dollar cap is OPT-IN. Empty (the default) = NO cap: a long but productive
# pack is never killed mid-way (the driver would read a --max-budget-usd cut-off as a
# halt and lose the work). On a Claude subscription there is no per-token dollar
# billing anyway - the real limit is the subscription usage window, which this flag
# does not govern.
BUDGET="${PACK_CHAIN_BUDGET:-}"
# Paths are env-overridable so the test harness can drive the script hermetically
# (fixture packs + a throwaway ledger) without touching the real tree.
PACKDIR="${PACK_CHAIN_PACKDIR:-task-packs}"
LEDGER="${PACK_CHAIN_LEDGER:-cc/_pack_chain_ledger.txt}"      # resume ledger (gitignored); --fresh clears it
# Committed-but-ungated marker (gitignored; --fresh clears it). Records a pack whose
# commit LANDED but whose post-commit gates did NOT finish (a transient install-green
# flake or a mid-verify kill), so a re-invoke re-gates the existing commit instead of
# re-running the -p session and false-halting as HALTED-nocommit. Distinct from LEDGER,
# which means "fully landed". Lines are `pack|short-sha`.
COMMITTED_MARKER="${PACK_CHAIN_COMMITTED_MARKER:-cc/_pack_chain_committed.txt}"
SCOPE_INJECT_CAP=12   # max undeclared refs folded into a goal verbatim (rest summarized as "+N more")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift;;
    --fresh)   FRESH=1; shift;;
    --budget)  [[ $# -ge 2 ]] || { echo "usage: --budget requires a value" >&2; exit 2; }
               BUDGET="$2"; shift 2;;
    --)        shift; break;;
    -*)        echo "unknown flag: $1" >&2; exit 2;;
    *)         break;;
  esac
done

[[ $# -eq 0 ]] && { echo "usage: $0 [--dry-run] [--fresh] [--budget N] TP-NNN [TP-NNN ...]" >&2; exit 2; }
[[ -d "$PACKDIR" ]] || { echo "error: $PACKDIR/ not found - run from repo root." >&2; exit 2; }

# Build the per-pack claude invocation once. --max-budget-usd is appended ONLY when a
# budget is set (via --budget N or PACK_CHAIN_BUDGET); "none"/"0" are explicit no-cap
# spellings. No cap = a long pack runs to completion instead of being killed mid-way.
CLAUDE_BASE=( claude -p --permission-mode auto )
BUDGET_NOTE="no cap"
if [[ -n "$BUDGET" && "$BUDGET" != "none" && "$BUDGET" != "0" ]]; then
  CLAUDE_BASE+=( --max-budget-usd "$BUDGET" )
  BUDGET_NOTE="\$$BUDGET cap"
fi

# Maintenance mode lets the harness edit its own protected zones without
# friction; exported here so every nested session inherits it.
export ESPALIER_MAINTENANCE_MODE=1
# Turn the nested stop_gate's pytest gate (Gate 1) ON for every pack session, so a test
# regression is caught mechanically at the session's Stop rather than depending on the
# operator's invocation env. Mirrors scripts/launch.sh. NOTE (accuracy): on the self-host
# repo Gate 1 runs the 4-file HARNESS SUBSET (_HARNESS_DEFAULT_TESTS: fingerprint / hooks
# / scanners / magic_depth), NOT the full suite -- the full-suite gate is /implement-pack's
# own step-6 integration check, and verify_install_green (clean-env selfcheck) remains the
# authoritative land oracle. This is the mechanical Stop backstop, not suite-level proof.
export ESPALIER_STOP_GATE=full

# --- Pack resolution (shared by the preflight and the run loop) ---------------
# Resolve a pack token to exactly one file. Echoes the path on success. Returns
# 1 (no match) or 2 (ambiguous - >1 file matches). A bare `matches[0]` silently
# ran one file and dropped the rest, so an ambiguous token is a HALT, not a
# coin-flip.
resolve_pack_file() {
  local token="$1" matches
  matches=( "$PACKDIR/${token}"-*.md )
  # nullglob is OFF, so a no-match leaves the literal unexpanded pattern as the
  # single element; -e distinguishes that from a real single match.
  if [[ ${#matches[@]} -eq 1 && ! -e "${matches[0]}" ]]; then
    echo "no pack file for '$token' in $PACKDIR/" >&2
    return 1
  fi
  if [[ ${#matches[@]} -gt 1 ]]; then
    { echo "ambiguous pack token '$token' - ${#matches[@]} files match:"
      printf '  %s\n' "${matches[@]}"; } >&2
    return 2
  fi
  printf '%s\n' "${matches[0]}"
}

# --- Fail-fast chain preflight ------------------------------------------------
# Validate the WHOLE chain before the first -p spends a cent: every token resolves
# to exactly one file, and every file is pack-shaped (carries a `## Landing`
# State: line). A malformed pack named 5th thus fails NOW, not after packs 1-4
# already spent budget.
preflight_chain() {
  local token file problems=0
  for token in "$@"; do
    # A pack already landed this chain (in the ledger) has moved to Done/, so
    # validating it would spuriously fail - skip it (the ledger is the SoT for done).
    if [[ $FRESH -eq 0 && -f "$LEDGER" ]] && grep -qxF "$token" "$LEDGER"; then
      continue
    fi
    # Same skip for a pack that a prior invocation COMMITTED but was killed before the
    # ledger append (a committed-but-ungated marker is recorded the instant HEAD advances).
    # Such a pack may already be moved to Done/ (a kill in the finalize->ledger window),
    # where resolve_pack_file fails - but the main loop re-gates it against the recorded
    # commit (see the committed-marker resume below), so it must NOT count as an unresolved
    # preflight problem. Without this, preflight (ledger-only) false-HALTs the whole chain
    # before that resume path runs. Mirrors the loop's _lookup_committed_marker precedence;
    # the $FRESH guard makes a deliberate clean re-run (--fresh) skip this clause and force
    # full re-validation (--fresh also clears the marker itself later, before the loop).
    if [[ $FRESH -eq 0 && -n "$(_lookup_committed_marker "$token")" ]]; then
      continue
    fi
    if ! file=$(resolve_pack_file "$token"); then
      problems=$((problems + 1)); continue   # resolve_pack_file already said why
    fi
    # State:-line SHAPE check (any authoring state - DRAFT is expected pre-run;
    # NOT a LANDED/SCRAPPED terminal check, which would reject every runnable pack).
    if ! grep -qE '(\*\*)?State:(\*\*)?[[:space:]]+[A-Za-z]' "$file"; then
      echo "preflight: '$token' ($file) has no '## Landing' State: line - not a runnable pack." >&2
      problems=$((problems + 1))
    fi
  done
  if [[ $problems -gt 0 ]]; then
    echo ">> preflight FAILED: $problems pack(s) unresolved/malformed - halting before any -p spend." >&2
    return 1
  fi
  echo ">> preflight: all $# pack(s) resolve + are pack-shaped."
  return 0
}

# --- Scope gate (advisory) ----------------------------------------------------
# Run BEFORE the -p session (the same "surface the signal early" spirit as the
# commit / red-team / install gates). scope-check exit: 0 = clean/acknowledged,
# 1 = nothing parsed (a clean skip, a DECLARED_BUT_EMPTY errored probe, or a
# crash - scope_gate tells them apart), 2 = unacknowledged gap.
#
# ADVISORY-ONLY by design: the gate NEVER halts on scope. scope-check is officially
# a signal, not a gate, and its severity signals are noise-dominated for an
# automated halt - a raw gap-FILE count trips on a common affected-symbol token
# like `.gitignore` that matches hundreds of files, and the [HIGH-RISK] guarded tag
# trips on an ordinary symbol name like `main` (which token-matches the "Main
# session" surface). So the gate auto-accepts every gap and folds the ACTIONABLE
# undeclared references into the goal; a genuinely major scope problem is caught by
# the -p session's own /implement-pack 0-A review + the commit / red-team / install
# gates. Sets the global SCOPE_INJECT; always returns 0.
SCOPE_INJECT=""
scope_gate() {
  local file="$1" report rc gap_section actionable n lit_section lit_actionable
  SCOPE_INJECT=""
  report=$(python3 -m espalier scope-check "$file" 2>&1); rc=$?

  if [[ $rc -eq 0 ]]; then
    echo ">> scope-check: clean (no gap, or already acknowledged in the pack)."
    return 0
  fi
  if [[ $rc -eq 1 ]]; then
    # rc==1 is THREE things: "pack has no 'Affected symbols' section - nothing to walk"
    # (a legitimate skip; /implement-pack's own 0-B skips scope-check in exactly this
    # case); a pack that DECLARED an Affected section which parsed to zero entries (its
    # blast radius was never walked - an errored probe, DEF-781); AND what a crashing
    # scope-check returns (Python exits 1 on an unhandled exception). Only the first is
    # a real skip; the others must SURFACE, not be swallowed as "nothing to inject".
    # cli.py::cmd_scope_check marks the second with a line that STARTS
    # `scope-check: DECLARED_BUT_EMPTY --`, read FIRST because such a message also
    # carries the skip phrases, and line-anchored so a traceback quoting the source
    # cannot match it (tests/test_run_pack_chain.py lifts this pattern and runs the real
    # CLI against it); the legitimate case prints a recognizable line; a crash prints a
    # traceback with neither. scope_gate is advisory (always returns 0) - this only makes
    # the cause VISIBLE, it does not halt.
    if grep -qE '^scope-check: DECLARED_BUT_EMPTY --' <<<"$report"; then
      echo ">> scope-check: the pack DECLARES an Affected section that parsed to zero entries - treating as an errored probe, NOT a clean skip (its declared blast radius was never walked). Output:" >&2
      echo "$report" >&2
    elif grep -qiE "no 'Affected symbols' section|cannot walk references" <<<"$report"; then
      echo ">> scope-check: pack declares no affected symbols - skipping the scope gate (advisory; proceeding)."
      # The cause is in the report (a sub-heading the pre-flight does not
      # route, a section whose bullets all declare nothing, a literals
      # section that parsed to zero); show it, or the operator never learns
      # why the gate stood down.
      sed 's/^/   /' <<<"$report"
    else
      echo ">> scope-check: exited 1 WITHOUT the 'no Affected symbols section' signal - treating as an errored probe, NOT a clean skip. Output:" >&2
      echo "$report" >&2
    fi
    return 0
  fi

  # rc == 2: an unacknowledged gap. Auto-accept + inject the ACTIONABLE undeclared
  # references (real governed source; archive/self-ref noise filtered) so the -p
  # session folds them into the plan. The gap-file block runs from its header to the
  # next blank line; a file line is `  <path>  [!] N refs` (exactly 2 leading
  # spaces), context lines indent deeper, so `^  [^ ]...\[!\]` selects file lines.
  gap_section=$(sed -n '/^Files NOT in pack scope (gap):/,/^$/p' <<<"$report")
  actionable=$(grep -E '^  [^ ].*\[!\]' <<<"$gap_section" \
    | sed -E 's/^  ([^ ]+).*/\1/' \
    | grep -vE '^(cc/|task-packs/|memory/|reports/|ESPALIER_MEMORY\.md|CHANGELOG\.md)')
  # A literal-keyed pack (rename/config) reports its ambiguous hits in a SEPARATE
  # `Literal refs NOT classified (gap):` block. Those targets legitimately live in
  # the very prefixes the symbol noise-filter drops (memory/, cc/, ESPALIER_MEMORY.md), so
  # fold them WITHOUT that filter - else a literal rename's real blast radius
  # silently drops out of the -p goal (the exact false reassurance this fold exists
  # to kill). Same file-line shape as the symbol block, so one grep/sed pair parses both.
  lit_section=$(sed -n '/^Literal refs NOT classified (gap):/,/^$/p' <<<"$report")
  lit_actionable=$(grep -E '^  [^ ].*\[!\]' <<<"$lit_section" \
    | sed -E 's/^  ([^ ]+).*/\1/')
  # Merge symbol + literal refs: drop blanks, dedup, preserve first-seen order.
  actionable=$(printf '%s\n%s\n' "$actionable" "$lit_actionable" \
    | grep -v '^[[:space:]]*$' | awk '!seen[$0]++')
  if [[ -z "$actionable" ]]; then
    echo ">> scope-check: gap is reference-noise only (no actionable source) - proceeding, nothing to inject."
    SCOPE_INJECT=""
    return 0
  fi
  n=$(grep -c . <<<"$actionable")
  echo ">> scope-check: auto-accepting gap - $n actionable undeclared ref(s); injecting into the goal."
  if [[ $n -gt $SCOPE_INJECT_CAP ]]; then
    SCOPE_INJECT="$(head -n "$SCOPE_INJECT_CAP" <<<"$actionable" | paste -sd ' ' -) (+$((n - SCOPE_INJECT_CAP)) more)"
  else
    SCOPE_INJECT="$(paste -sd ' ' - <<<"$actionable")"
  fi
  return 0
}

# Pack-receipt gate (integration A): the -p session writes ONE cc/_pack_receipt.json
# every run (red-team + 0-A + suite counts). The driver REQUIRES it - its absence
# means the session did not attest its steps, a HALT (a skipped safety pass in an
# unattended chain is not a pass; the old "no artifact = honest null = pass" could
# not tell "red-teamed, clean" from "skipped it"). A receipt claiming blockers still
# needs re-runnable repros the driver INDEPENDENTLY re-executes via
# espalier.red_team_guard; a fabricated blocker (a repro that does not reproduce)
# halts the chain.
PACK_RECEIPT="cc/_pack_receipt.json"     # proof the session ran its steps (counts, even 0)
RT_FINDINGS="cc/red_team_findings.json"  # blocker repros (written only when blocker_count > 0)
RT_REPROS="cc/red_team_repros.json"

verify_pack_receipt() {
  local expected_pack="$1"
  if [[ ! -f "$PACK_RECEIPT" ]]; then
    echo ">> receipt: no $PACK_RECEIPT - session did not attest its steps. Halting." >&2
    return 1
  fi
  python3 - "$PACK_RECEIPT" "$RT_FINDINGS" "$RT_REPROS" "$(git rev-parse --short HEAD)" "$expected_pack" <<'PY'
import json, os, sys
receipt = json.loads(open(sys.argv[1], encoding="utf-8").read())
rt = receipt.get("red_team", {})
pr = receipt.get("pack_review", {})
# Pack-identity oracle: the receipt must attest THIS pack. The on-disk receipt is a
# single shared file (cc/_pack_receipt.json) that each session rm's + rewrites; the
# resume path re-verifies it WITHOUT re-running the session, so a receipt left by an
# UNRELATED pack (run between the halt and the re-invoke) would otherwise green-wash
# this pack with a foreign attestation (a false-GREEN). The goal template always writes
# receipt.pack, so a present-but-mismatched value is a foreign/stale receipt -> HALT.
# (An absent pack field falls through: an older/degenerate receipt is still gated by the
# ran/blocker checks below, and no cross-pack green-wash is possible without the field.)
expected_pack = sys.argv[5] if len(sys.argv) > 5 else ""
rc_pack = str(receipt.get("pack", ""))
if expected_pack and rc_pack and rc_pack != expected_pack:
    print(f">> receipt: receipt attests pack {rc_pack!r}, not {expected_pack!r} - a foreign/stale "
          "receipt (its owning session did not attest THIS pack). Halting."); sys.exit(1)
# Skip-detection: red-team AND 0-A must both have RUN.
if rt.get("ran") is not True:
    print(">> receipt: red_team.ran != true - red-team skipped. Halting."); sys.exit(1)
if pr.get("ran") is not True:
    print(">> receipt: pack_review.ran != true - 0-A pack-artifact review skipped. Halting."); sys.exit(1)
# Advisory (implements the verification-map 'commit' row): the session's self-reported
# commit should match the HEAD the driver already confirmed advanced. A mismatch => a
# stale/confused receipt -> WARN, never halt (HEAD-advance stays the commit oracle).
head = sys.argv[4] if len(sys.argv) > 4 else ""
rc_commit = str(receipt.get("commit", ""))
if head and rc_commit and rc_commit != head:
    print(f">> receipt: WARN - receipt.commit {rc_commit!r} != HEAD {head!r} (advisory; a commit was already confirmed).")
blockers = int(rt.get("blocker_count", 0))
if blockers == 0:
    print(f">> receipt: red-team RAN, {rt.get('finding_count', 0)} finding(s), 0 blockers; "
          f"0-A RAN, {pr.get('blocks', 0)} block(s) (auto_fixed: {pr.get('auto_fixed', [])}). Clean.")
    sys.exit(0)
# blockers claimed -> the repro artifacts must exist and independently reproduce.
if not (os.path.exists(sys.argv[2]) and os.path.exists(sys.argv[3])):
    print(f">> receipt: claims {blockers} blocker(s) but repro artifacts are missing. Halting."); sys.exit(1)
from espalier.red_team_guard import guard_findings, format_report
findings = json.loads(open(sys.argv[2], encoding="utf-8").read())
repros = json.loads(open(sys.argv[3], encoding="utf-8").read())
result = guard_findings(findings, repros, root=".", min_finders=1)
print(format_report(result))
sys.exit(0 if result.passed else 1)
PY
}

verify_install_green() {
  # Independent install-green gate (trust the oracle, not the agent's "green").
  # An autonomous gate's "full suite green" can be env-relative: a stale editable
  # install (.pth -> deleted path) lets the -p agent satisfy pytest only with
  # PYTHONPATH=repo.
  #
  # NOTE (verified, not assumed): re-running the FULL pytest suite in a venv does
  # NOT fix this here - pyproject's `pythonpath = ["."]` puts the source tree on
  # sys.path for every run, so the suite passes even with espalier uninstalled.
  # The repo's REAL install-green oracle is `espalier selfcheck`: it resolves its
  # bundled mirror from the INSTALLED package via importlib.resources and runs it
  # from a throwaway cwd, so it exercises the install, not the source.
  #
  # Design notes (each closes a false-halt / footgun the toolbelt frame forbids):
  #   * venv + foreign cwd live under mktemp (outside the worktree) - never an
  #     `rm -rf` of an operator dir, never pollutes `git status`, auto-fresh.
  #   * `. pytest` (not `.[dev]`) - the minimal closure the mirror imports
  #     (espalier + pytest + stdlib); the 9 `[dev]` deps would only widen the
  #     network-flake surface for zero gate value.
  #   * `--retries/--timeout` so a transient PyPI/DNS blip does not false-halt a
  #     long unattended chain; the failure message says "flake OR regression",
  #     not "the agent's green was env-relative".
  if [[ "${PACK_CHAIN_SKIP_INSTALL_GATE:-0}" == "1" ]]; then
    echo ">> install-green gate: skipped (PACK_CHAIN_SKIP_INSTALL_GATE=1)"
    return 0
  fi
  # TEST SEAM (no production use): force the gate to FAIL without building a venv, so
  # the test suite can exercise the post-commit HALTED-install arm + the re-gate
  # resume path hermetically (a real install failure needs a network pip build). Only
  # ever makes the gate STRICTER (fail, never pass) -- it can never be a safety bypass.
  if [[ "${PACK_CHAIN_FORCE_INSTALL_FAIL:-0}" == "1" ]]; then
    echo ">> install-green gate: FORCED FAILURE (PACK_CHAIN_FORCE_INSTALL_FAIL=1 test seam)" >&2
    return 1
  fi
  local gate_root foreign vpy rc
  gate_root="$(mktemp -d)"
  foreign="$(mktemp -d)"
  echo ">> install-green gate: building clean venv in $gate_root"
  if ! python3 -m venv "$gate_root"; then
    echo ">> install-green: venv create failed (infra) - halting." >&2
    rm -rf "$gate_root" "$foreign"; return 1
  fi
  vpy="$gate_root/bin/python"   # mktemp path is absolute; survives the cd below
  if ! "$vpy" -m pip install --quiet --retries 5 --timeout 30 . pytest; then
    echo ">> install-green: 'pip install . pytest' FAILED - a network flake OR a real packaging regression (NOT necessarily env-relative green). This is a POST-COMMIT halt: the pack is already committed, and the driver recorded a committed-but-ungated marker, so a plain re-invoke re-runs ONLY this gate against the existing commit (not the -p session) - re-run to clear a transient flake. A --fresh re-invoke instead discards the marker, re-runs the session, and false-halts as nocommit; in that case reset the commit or re-gate by hand. Halting." >&2
    rm -rf "$gate_root" "$foreign"; return 1
  fi
  # Run the install-green oracle from a FOREIGN cwd so `import espalier` resolves
  # to site-packages, not ./espalier.
  ( cd "$foreign" && "$vpy" -m espalier selfcheck ); rc=$?
  rm -rf "$gate_root" "$foreign"
  return "$rc"
}

# --- Dispatch sentinel (pre-first-pack) ---------------------------------------
# The whole pipeline rests on the -p goal INVOKING the real /implement-pack command
# (headless -p expands a leading-slash prompt into the command body). A future silent
# regression -- a CC downgrade below the version that added -p slash dispatch, a
# different execution machine, an upstream change to headless slash-expansion -- would
# degrade the goal to a prose paraphrase and reintroduce the mechanically-green-but-
# incomplete class. Nothing else catches it: a prose-degraded session still reads the
# goal's receipt instruction as text and writes a receipt claiming it ran, so the
# receipt gate passes. So before the first pack, probe the EXACT production shape (a
# prefixed slash) and confirm it dispatched by its distinctive /status banner; halt the
# whole chain if it did not, before any pack spends budget on a degraded run.
SENTINEL_MARKER="SURFACE:"   # a stable /status banner token; absent => not dispatched
                             # (coupling point: if /status's banner changes, update this)
verify_dispatch_sentinel() {
  if [[ "${PACK_CHAIN_SKIP_DISPATCH_SENTINEL:-0}" == "1" ]]; then
    echo ">> dispatch sentinel: skipped (PACK_CHAIN_SKIP_DISPATCH_SENTINEL=1)"
    return 0
  fi
  local out
  out=$("${CLAUDE_BASE[@]}" "Run the real slash command: /status" 2>&1)
  if grep -qF "$SENTINEL_MARKER" <<<"$out"; then
    echo ">> dispatch sentinel: /status dispatched (found '$SENTINEL_MARKER') - the goal's real-command invocation is live."
    return 0
  fi
  echo ">> dispatch sentinel: a prefixed slash did NOT dispatch (no '$SENTINEL_MARKER' in the probe output) - the -p goal would degrade to a prose paraphrase and silently reintroduce incomplete packs. Halting before any pack. Check that this Claude Code binary expands a leading-slash -p prompt." >&2
  return 1
}

# --- Driver-owned Landing finalize (step 12) ----------------------------------
# After a pack's commit + gates pass, ensure it moved to <PACKDIR>/Done/ with a
# complete Landing stanza. The first overnight run showed only 1/9 sessions did
# step 12 (the rest committed but left the pack at State: DRAFT, re-surfacing as
# pending work); deterministic bash is a more reliable owner than a one-shot -p
# session whose budget cuts off right after the commit. Stamps only what the driver
# mechanically knows (State/Commits/Date) + the session-ATTESTED suite count from
# the receipt (never a fabricated number); leaves any field the session already
# filled. Reuses check_pack_landing's Landing parser (no rival parser).
finalize_landing() {
  local file="$1" commit="$2" pack_base done_dir dest target moved result rc cand candidates
  pack_base=$(basename "$file")
  done_dir="$(dirname "$file")/Done"
  dest="$done_dir/$pack_base"

  # Completeness, not location: pick the stamp target. If the session already moved the
  # pack to Done/, stamp it THERE -- a re-stamp COMPLETES any partial stanza (set_field
  # leaves session-filled fields alone), rather than assuming "in Done/" == "fully
  # stamped". A one-shot session is unreliable at step 12; a moved-but-partially-stamped
  # pack is exactly the partial this finalize exists to complete.
  if [[ -f "$file" ]]; then
    target="$file"; moved=0
  elif [[ -f "$dest" ]]; then
    target="$dest"; moved=1
  else
    # The pack file is at NEITHER $file NOR Done/<original-basename>. A bare `return 0`
    # here reported a silent clean LANDED even though the driver could not confirm the
    # Landing was ever stamped -- the exact green-wash class this finalize exists to
    # close (STANDING_PRINCIPLES §8 class-fix = every surface; FAILURE_MODES §11.14
    # green-but-incomplete). Two-step, so a legitimately renamed-and-landed pack is NOT
    # over-triaged:
    #   (1) search Done/ for the pack under ANY basename by TP-id ($pack is the loop's
    #       token global). If a match is terminally stamped, it renamed + stamped itself
    #       under a new name -- a TRUE LANDED the driver just couldn't locate by the old
    #       name. nullglob is OFF, so a no-match leaves the literal pattern; -e
    #       distinguishes it (mirrors resolve_pack_file). ckl.landed_state (reused, not a
    #       rival parser) reads the terminal state tolerantly (bold, Landing-scoped).
    #   (2) still not found (or found only un-stamped): emit LANDED-unverified + a stderr
    #       diagnostic so the report row / resume ledger carry a triage marker, NOT a
    #       clean claim. Do NOT blanket return 3/4 (that over-triages every renamed pack).
    candidates=( "$done_dir/${pack}"-*.md )
    if [[ ${#candidates[@]} -ge 1 && -e "${candidates[0]}" ]]; then
      for cand in "${candidates[@]}"; do
        if python3 - "$cand" "$SELF_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[2])          # the driver's own dir -> scripts/check_pack_landing.py
import check_pack_landing as ckl
text = open(sys.argv[1], encoding="utf-8").read()
sys.exit(0 if ckl.landed_state(text) in ("LANDED", "SCRAPPED") else 1)
PY
        then
          echo ">> $pack: original basename gone, but a terminally-stamped pack for $pack is in Done/ ($(basename "$cand")) - true LANDED (session renamed + stamped it)."
          return 0
        fi
      done
    fi
    echo ">> $pack: pack file vanished from both $file and $dest - cannot verify/stamp Landing; check for a rename/delete during the session." >&2
    return 4   # LANDED-unverified: caller reports a distinct triage outcome, NOT a clean LANDED
  fi

  result=$(python3 - "$target" "$commit" "$PACK_RECEIPT" "$(date +%Y-%m-%d)" "$SELF_DIR" <<'PY'
import json, os, re, sys
sys.path.insert(0, sys.argv[5])          # the driver's own dir -> scripts/check_pack_landing.py
import check_pack_landing as ckl

pack_path, commit, receipt_path, today = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(pack_path, encoding="utf-8").read()
state = ckl.landed_state(text)           # bound once; reused by the AMBIGUOUS check below
if state == "SCRAPPED":
    print("SCRAPPED"); sys.exit(0)

# Session-attested suite count (never fabricate; fall back if the receipt lacks it).
suite_val = "(unrecorded)"
try:
    s = (json.load(open(receipt_path, encoding="utf-8")).get("suite") or {})
    if "passed" in s:
        suite_val = (f"{s['passed']} passed / {s.get('skipped', 0)} skipped "
                     "(session-attested; driver verified install-green via selfcheck, not the full count)")
except Exception:
    pass

m = ckl._LANDING_RE.search(text)
if not m:
    print("NO_LANDING"); sys.exit(0)
nxt = re.search(r"^\#{1,6}\s", text[m.end():], re.MULTILINE)
end = m.end() + nxt.start() if nxt else len(text)
head, region, tail = text[:m.start()], text[m.start():end], text[end:]

# Defensive: decide ambiguity from the BOUNDED region (the same scope set_field
# mutates), NOT the unbounded `state` above -- ckl.landed_state scans ## Landing -> EOF,
# so a readable State: line in a LATER section would mask an unparseable one inside this
# stanza and defeat the guard. A Landing region that HAS a State: line _STATE_RE cannot
# read cleanly (e.g. a bold VALUE `State: **SCRAPPED**`, whose `(\w+)` rejects the `**`)
# is AMBIGUOUS -- never overwrite it. (A ## Landing with NO State line at all is not
# ambiguous; it falls through and gets a fresh stamp.)
if ckl._STATE_RE.search(region) is None and re.search(r"(?m)^\s*-?\s*\*{0,2}State:", region):
    print("AMBIGUOUS"); sys.exit(0)

def set_field(region, field, value, is_state=False):
    pat = re.compile(r"^(\s*-?\s*\*{0,2}" + re.escape(field) + r":\*{0,2})[ \t]*(.*)$", re.MULTILINE)
    mm = pat.search(region)
    if mm:
        existing = mm.group(2).strip()
        if is_state:
            if existing in ("LANDED", "SCRAPPED"):
                return region          # already terminal -> idempotent
        elif existing:
            return region              # leave a session-filled value alone
        return region[:mm.start()] + mm.group(1) + " " + value + region[mm.end():]
    return region.rstrip("\n") + "\n- **" + field + ":** " + value + "\n"   # absent -> append

new = region
for field, value, is_state in (("State", "LANDED", True), ("Commits", commit, False),
                                ("Suite", suite_val, False), ("Date", today, False)):
    new = set_field(new, field, value, is_state)

if new != region:
    tmp = pack_path + ".tmp"                      # atomic write: never truncate a real pack
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(head + new + tail)
    os.replace(tmp, pack_path)
print("STAMPED")
PY
)
  rc=$?

  if [[ "$result" == "SCRAPPED" || "$result" == "AMBIGUOUS" ]]; then
    echo ">> $pack: Landing stanza is $result - respecting it; not stamping or moving." >&2
    return 3   # left-in-place, not stamped: caller must NOT report a clean LANDED
  fi
  # FAIL CLOSED: only a positively-confirmed stamp (result==STAMPED, rc==0) may move
  # the pack to Done/. NO_LANDING (a pack with no ## Landing stanza) or a python crash
  # (empty $result / nonzero rc) must NOT move it -- moving an unstamped pack into
  # Done/ with a false "stamped" line is the exact unstamped-Done defect this finalize
  # exists to prevent. Leave it in place for triage; the commit already landed, so do
  # not halt the chain over best-effort landing hygiene.
  if [[ $rc -ne 0 || "$result" != "STAMPED" ]]; then
    echo ">> $pack: finalize did NOT stamp (result='${result:-<none>}', rc=$rc) - leaving the pack in place, NOT moving to Done/. Needs a '## Landing' stanza or manual triage." >&2
    return 3   # left-in-place, not stamped: caller must NOT report a clean LANDED
  fi
  # Target was already in Done/ (session did the move): the stamp above COMPLETED any
  # partial stanza in place. Confirm; never move again.
  if [[ $moved -eq 1 ]]; then
    echo ">> $pack: landing already in Done/; driver completed/confirmed its stanza."
    return 0
  fi
  mkdir -p "$done_dir"
  mv "$file" "$dest"
  echo ">> $pack: driver finalized move-to-Done (session skipped step 12); stamped State/Commits/Date + session-attested Suite."
}

# --- Committed-but-ungated marker (post-commit resume) -----------------------
# Records a pack whose commit LANDED but whose post-commit gates did not finish, the
# instant HEAD advances -- BEFORE the gates. A re-invoke consults it (see the loop) and
# re-runs ONLY the post-commit gates against the recorded commit, instead of re-running
# the -p session (which, the work already committed, makes no new commit and false-halts
# as HALTED-nocommit). Pack tokens are TP-<n> (no regex metacharacters), so an anchored
# `^${pack}|` grep is safe.
_record_committed_marker() {
  local pack="$1" commit="$2"
  mkdir -p "$(dirname "$COMMITTED_MARKER")"
  if [[ -f "$COMMITTED_MARKER" ]] && grep -q "^${pack}|" "$COMMITTED_MARKER"; then
    return 0   # idempotent: one line per pack (a re-gate that halts again must not dup)
  fi
  printf '%s|%s\n' "$pack" "$commit" >> "$COMMITTED_MARKER"
}

_clear_committed_marker() {
  local pack="$1" tmp
  [[ -f "$COMMITTED_MARKER" ]] || return 0
  tmp="${COMMITTED_MARKER}.tmp"
  # grep -v exits 1 when every line is dropped (empty result) - not an error here.
  grep -v "^${pack}|" "$COMMITTED_MARKER" > "$tmp" 2>/dev/null || true
  mv "$tmp" "$COMMITTED_MARKER"
}

_lookup_committed_marker() {   # echoes the recorded short-sha for $1, or nothing
  local pack="$1"
  [[ -f "$COMMITTED_MARKER" ]] || return 0
  grep -m1 "^${pack}|" "$COMMITTED_MARKER" | cut -d'|' -f2
}

# --- Post-commit gate + finalize (shared) ------------------------------------
# Runs every post-commit gate against an ALREADY-MADE commit, then finalizes the
# Landing. Shared by the fresh-run path (HEAD just advanced this invocation) and the
# re-gate resume path (a prior invocation committed but halted before the gates
# finished). On a gate failure it records the row + exits the chain; on success it
# finalizes, clears the committed marker, appends the resume ledger, and records the
# LANDED / LANDED-nostamp / LANDED-unverified row.
# Args: pack file commit pre_head pack_start   (pre_head "" on the re-gate path)
post_commit_verify_and_finalize() {
  local pack="$1" file="$2" commit="$3" pre_head="$4" pack_start="$5"
  local fin_rc cl_real cl_claim
  # Verify the session's pack receipt (trust the oracle, not the agent's self-report):
  # the receipt must exist + attest red-team AND 0-A ran, and any claimed blocker's
  # repro must independently reproduce. Missing/skipped halts.
  if ! verify_pack_receipt "$pack"; then
    echo ">> $pack: pack-receipt gate FAILED - missing/foreign receipt, a skipped step, or a claimed blocker did not reproduce. Halting chain." >&2
    REPORT_ROWS+=("$pack|HALTED-receipt|-|$((SECONDS - pack_start))")
    exit 1
  fi
  # Then re-run the suite in a clean install env so "green" is CI-equivalent by
  # construction, not dev-shell-relative. Cheap checks first, this heavy one last.
  if ! verify_install_green; then
    echo ">> $pack: install-green gate FAILED (env-relative green, a packaging regression, or a network flake). The pack IS committed ($commit); a plain re-invoke re-runs ONLY the post-commit gates against it (via $COMMITTED_MARKER), so re-run to clear a transient flake. (A --fresh re-invoke discards that marker, re-runs the session, and false-halts as nocommit - reset or re-gate by hand.) Halting." >&2
    REPORT_ROWS+=("$pack|HALTED-install|-|$((SECONDS - pack_start))")
    exit 1
  fi
  # Advisory changelog cross-check (never halts): did the session's changelog_touched
  # claim match the commit's reality? Skipped on the re-gate path (no pre_head to diff).
  if [[ -n "$pre_head" && "$pre_head" != "none" ]]; then
    if grep -qx "CHANGELOG.md" <<<"$(git diff "$pre_head"..HEAD --name-only 2>/dev/null)"; then cl_real=1; else cl_real=0; fi
    cl_claim=$(python3 -c "import json;print(1 if json.load(open('$PACK_RECEIPT')).get('changelog_touched') else 0)" 2>/dev/null || echo 0)
    [[ "$cl_claim" != "$cl_real" ]] && echo ">> $pack: NOTE - receipt.changelog_touched=$cl_claim but commit CHANGELOG.md change=$cl_real (advisory; not every pack needs one)."
  fi
  echo ">> $pack committed ($commit) + receipt verified + install-green; advancing."
  finalize_landing "$file" "$commit"; fin_rc=$?   # driver owns move-to-Done + Landing stamp
  # Record the land in the resume ledger FIRST, then drop the committed-but-ungated marker.
  # A kill in the two-statement window (crash, budget cut-off) must never strand a
  # fully-landed pack -- already moved to Done/ by finalize_landing -- invisible to both
  # resume paths. Appending the ledger before the clear means the worst a window-kill leaves
  # is a stale marker the ledger-skip shadows (and --fresh clears); the clear-first order
  # instead left BOTH empty, false-HALTing the next invoke at preflight ("no pack file").
  echo "$pack" >> "$LEDGER"         # resume ledger: mark landed (commit is in; do NOT re-run)
  # Test seam: simulate a kill INSIDE the finalize window (between the ledger-append and the
  # marker-clear) so the resume-ledger ordering earn-red is faithful to a real mid-window
  # crash/budget-cut, not a static mock. Never set in production.
  if [[ "${PACK_CHAIN_FORCE_KILL_IN_FINALIZE_WINDOW:-0}" == "1" ]]; then
    echo ">> $pack: TEST SEAM - simulated kill in finalize window" >&2; exit 143
  fi
  _clear_committed_marker "$pack"   # fully landed now: drop the committed-but-ungated marker
  if [[ $fin_rc -eq 3 ]]; then
    # Commit landed but the pack was NOT stamped/moved (malformed/absent ## Landing, or a
    # respected SCRAPPED/AMBIGUOUS). Do NOT report a clean LANDED - the green-but-
    # incomplete mask this fix closes; it sits at DRAFT in root.
    echo ">> $pack: committed but landing NOT stamped - reporting LANDED-nostamp (needs triage)." >&2
    REPORT_ROWS+=("$pack|LANDED-nostamp|$commit|$((SECONDS - pack_start))")
  elif [[ $fin_rc -eq 4 ]]; then
    # Committed, but the pack file was at neither location and no terminally-stamped
    # rename was found in Done/ - the Landing could not be verified. Distinct from
    # -nostamp (which knows the file + its state); here the file itself is unaccounted for.
    echo ">> $pack: committed but Landing UNVERIFIED (pack file unaccounted for) - reporting LANDED-unverified (needs triage)." >&2
    REPORT_ROWS+=("$pack|LANDED-unverified|$commit|$((SECONDS - pack_start))")
  else
    REPORT_ROWS+=("$pack|LANDED|$commit|$((SECONDS - pack_start))")
  fi
}

# --- Run report ---------------------------------------------------------------
# One row per pack (outcome / verified commit / wall-clock). Printed via an EXIT
# trap so it surfaces whether the chain completes OR halts mid-way. Rows are
# `pack|outcome|commit|seconds`.
REPORT_ROWS=()
CHAIN_STARTED=0
print_report() {
  [[ $CHAIN_STARTED -eq 1 ]] || return 0   # skip on usage/arg errors before the run
  echo
  echo "=========================================================="
  echo "PACK-CHAIN RUN REPORT"
  echo "=========================================================="
  printf '%-16s %-14s %-12s %8s\n' "PACK" "OUTCOME" "COMMIT" "SECONDS"
  local row p o c s
  # bash 3.2 (macOS /bin/bash) raises "unbound variable" on "${arr[@]}" for an EMPTY
  # array under `set -u` (fixed in bash 4.4+). REPORT_ROWS is empty whenever the chain
  # is interrupted before the first pack records an outcome - e.g. the -p session is
  # killed mid-run - and print_report fires via the EXIT trap, so the report itself
  # would crash on exactly the aborted runs that most need a readout. Guard on length
  # (${#arr[@]} is safe on an empty array on 3.2).
  if [[ ${#REPORT_ROWS[@]} -eq 0 ]]; then
    echo "(chain halted before any pack recorded an outcome - see the halt reason above)"
    return 0
  fi
  for row in "${REPORT_ROWS[@]}"; do
    IFS='|' read -r p o c s <<<"$row"
    printf '%-16s %-14s %-12s %8s\n' "$p" "$o" "$c" "$s"
  done
}

# --- Chain preflight + ledger reset (before any -p) ---------------------------
preflight_chain "$@" || exit 1
# Confirm headless slash-dispatch is live before spending any -p budget (skipped in
# --dry-run, which fires no real -p). A halt here exits before CHAIN_STARTED=1, so no
# run-report row prints -- the chain never started.
if [[ $DRY_RUN -eq 0 ]]; then
  verify_dispatch_sentinel || exit 1
fi
if [[ $FRESH -eq 1 && -f "$LEDGER" ]]; then
  if [[ $DRY_RUN -eq 1 ]]; then
    echo ">> --fresh (dry-run): WOULD clear resume ledger $LEDGER - leaving it intact (run nothing)."
  else
    : > "$LEDGER"
    echo ">> --fresh: cleared resume ledger $LEDGER"
  fi
fi
if [[ $FRESH -eq 1 && -f "$COMMITTED_MARKER" ]]; then
  if [[ $DRY_RUN -eq 1 ]]; then
    echo ">> --fresh (dry-run): WOULD clear committed-but-ungated marker $COMMITTED_MARKER - leaving it intact (run nothing)."
  else
    : > "$COMMITTED_MARKER"
    echo ">> --fresh: cleared committed-but-ungated marker $COMMITTED_MARKER"
  fi
fi

CHAIN_STARTED=1
trap print_report EXIT

for pack in "$@"; do
  pack_start=$SECONDS

  # Resume ledger FIRST, before resolving: a pack this chain already landed has been
  # moved to task-packs/Done/, so resolving it would fail - the ledger is the SoT for
  # "already done", so it is checked before resolution. --fresh cleared it above.
  if [[ $FRESH -eq 0 && -f "$LEDGER" ]] && grep -qxF "$pack" "$LEDGER"; then
    echo ">> $pack: already in resume ledger ($LEDGER) - skipping."
    REPORT_ROWS+=("$pack|SKIPPED-resumed|-|-")
    continue
  fi

  # Post-commit resume: a prior invocation committed this pack but halted (or was
  # killed) before the post-commit gates finished, recording a committed-but-ungated
  # marker the instant HEAD advanced. Re-running the -p session now would make no new
  # commit (the work is already in git) and false-halt as HALTED-nocommit. Instead
  # re-run ONLY the post-commit gates against the existing HEAD. (--fresh cleared the
  # marker above, so this never fires on a deliberate clean re-run.) This precedes the
  # hard `|| exit 1` resolve below because a prior finalize may have already moved the
  # pack to Done/ (killed before the ledger append), where resolution would fail.
  prior_commit=""
  if [[ $FRESH -eq 0 ]]; then
    prior_commit=$(_lookup_committed_marker "$pack")
  fi
  if [[ -n "$prior_commit" ]]; then
    # --dry-run must mutate nothing: a committed-but-ungated marker would otherwise send us
    # into post_commit_verify_and_finalize below, which runs the receipt + install-green gates,
    # finalizes the Landing (moves the pack to Done/, rewrites its stanza, appends the ledger),
    # and `exit 1`s on any gate miss -- all forbidden by the documented "--dry-run = print plan,
    # run nothing" contract. Print the intended re-gate and continue; touch neither the tree, the
    # ledger, nor the marker. Append + echo + continue only -- no `"${arr[@]}"` empty-array
    # expansion, so bash 3.2 (macOS) / set -u safe.
    if [[ $DRY_RUN -eq 1 ]]; then
      echo "=========================================================="
      echo ">> $pack: DRY-RUN - committed-but-ungated marker present ($prior_commit); a real run would re-gate the RECORDED commit (receipt + install-green + finalize/move-to-Done), NOT re-run the -p session. Running nothing."
      echo "=========================================================="
      REPORT_ROWS+=("$pack|DRY-RUN-regate|$prior_commit|-")
      continue
    fi
    # The recorded commit must still be REAL and IN HEAD's history before we re-gate
    # against it. Re-gating current HEAD blindly would false-GREEN a pack whose work was
    # reset/rebased away (land it against a HEAD that no longer contains its commit) --
    # the same forbidden direction the marker exists to avoid. If the commit vanished or
    # is not an ancestor of HEAD, HALT: the pack must be re-run, not phantom-landed.
    head_now=$(git rev-parse --short HEAD 2>/dev/null || echo none)
    if ! git cat-file -e "${prior_commit}^{commit}" 2>/dev/null; then
      echo ">> $pack: recorded committed-but-ungated commit $prior_commit no longer exists in git (history rewritten?). NOT re-gating a phantom landing; re-run the session or use --fresh." >&2
      REPORT_ROWS+=("$pack|HALTED-regate|-|$((SECONDS - pack_start))")
      exit 1
    fi
    if ! git merge-base --is-ancestor "$prior_commit" HEAD 2>/dev/null; then
      echo ">> $pack: recorded commit $prior_commit is NOT an ancestor of HEAD ($head_now) - the pack's work was reset/rebased away. NOT re-gating a phantom landing; re-run the session or use --fresh." >&2
      REPORT_ROWS+=("$pack|HALTED-regate|-|$((SECONDS - pack_start))")
      exit 1
    fi
    if ! file=$(resolve_pack_file "$pack" 2>/dev/null); then
      # Pack no longer in packdir (a prior run finalized/moved it to Done/ but died
      # before the ledger append). Hand finalize_landing a placeholder so its
      # Done/-by-TP-id search adjudicates the true landing state.
      file="$PACKDIR/${pack}-unresolved.md"
    fi
    echo "=========================================================="
    echo ">> $pack: already committed ($prior_commit) by a prior invocation that halted before the post-commit gates finished; re-running ONLY the post-commit gates against the RECORDED commit, NOT the -p session."
    [[ "$head_now" != "$prior_commit" && "$head_now" != "none" ]] && \
      echo ">> $pack: NOTE - HEAD ($head_now) is ahead of the recorded commit ($prior_commit); gating + stamping the recorded commit (later commits are not this pack's)." >&2
    echo "=========================================================="
    # Gate + stamp the RECORDED commit (not head_now): the Landing must record the pack's
    # own commit even if HEAD advanced with unrelated work since the halt.
    post_commit_verify_and_finalize "$pack" "$file" "$prior_commit" "" "$pack_start"
    continue
  fi

  # Resolve (preflight already proved this succeeds + is unambiguous for non-skipped).
  file=$(resolve_pack_file "$pack") || exit 1

  # Scope gate BEFORE spending -p budget (advisory: auto-accepts + injects any
  # undeclared references into the goal; never halts on scope).
  scope_gate "$file"

  goal="Run the real slash command: /implement-pack ${file}
Carry it to completion - run the command's OWN body (0-A pack-artifact review, 0-B \
scope-check, 0-C compression probe, 0-D surface-impact, the phase execution, the \
step-6 integration check + orthogonal review, CHANGELOG, mirror sync, the blueprint \
entry, ONE atomic commit, closing the plan, and step 12: stamp the Landing stanza + \
move the pack to task-packs/Done/). Do NOT re-derive or skip steps. \
CRITICAL - one-shot \`-p\`, NO loop to resume into: run EVERY gate (full pytest \
suite, audit, pre-release) SYNCHRONOUSLY in the foreground and read its result \
inline in the SAME turn. Foreground subagents (0-A, step-6) are fine - the session \
waits for them. Never background a gate, never use the Monitor, ScheduleWakeup, or \
Workflow tools (a background fan-out cannot complete in a one-shot -p), never defer \
- anything you defer is lost and the commit will NOT happen. \
0-A POLICY (unattended, no operator to hand back to): if 0-A raises a BLOCK, FIX \
mechanical findings (wrong line number, renamed symbol, false line-count) in the \
pack yourself, note each in the receipt's pack_review.auto_fixed, and PROCEED; HALT \
and explain only on a structural BLOCK you cannot mechanically resolve. \
RECEIPT (required, always - even on a clean run): as your FINAL step write \
cc/_pack_receipt.json = {\"pack\": \"${pack}\", \"commit\": <short-sha you made>, \
\"suite\": {\"passed\": <int>, \"skipped\": <int>}, \"red_team\": {\"ran\": true, \
\"finding_count\": <int>, \"blocker_count\": <int>, \"finders\": [<lens names>]}, \
\"pack_review\": {\"ran\": true, \"blocks\": <int>, \"auto_fixed\": [<one-liners>]}, \
\"changelog_touched\": <bool>}. If blocker_count > 0 you MUST ALSO write \
cc/red_team_findings.json (FINDING_SCHEMA findings) and cc/red_team_repros.json (one \
executable repro per blocker: {\"id\": the finding id, \"argv\": a command list, \
\"expect\": \"fail\", \"match\": a failure-signature regex}) so the driver can \
INDEPENDENTLY re-run each blocker; a blocker whose repro does not reproduce halts \
the chain. \
The pack is DONE only when git log shows that commit AND the full suite is green. \
Do not push. If a release gate or test fails and cannot be resolved, STOP and \
explain - do not force it. Or stop after 40 turns."

  # Fold a benign scope gap's undeclared references into the goal so the session
  # widens the pack's Scope (in) / Affected symbols before committing.
  if [[ -n "$SCOPE_INJECT" ]]; then
    goal="$goal \
NOTE: scope-check surfaced these references NOT yet in the pack's Scope (in): \
${SCOPE_INJECT}. Fold them into your plan and widen the pack's Scope (in) / \
Affected symbols before committing."
  fi

  echo "=========================================================="
  echo "PACK: $pack  ($file)   budget=$BUDGET_NOTE   dry_run=$DRY_RUN"
  echo "=========================================================="

  if [[ $DRY_RUN -eq 1 ]]; then
    echo "+ ${CLAUDE_BASE[*]} <goal>"
    echo "--- goal ---"; printf '%s\n' "$goal"
    REPORT_ROWS+=("$pack|DRY-RUN|-|-")
    continue
  fi

  rm -f "$RT_FINDINGS" "$RT_REPROS" "$PACK_RECEIPT"  # clear any stale artifact from a prior pack
  pre_head=$(git rev-parse HEAD 2>/dev/null || echo none)
  if "${CLAUDE_BASE[@]}" "$goal"; then
    # Defense in depth: confirm a commit was actually MADE before advancing - trust
    # the mechanical oracle, not the session's "I committed". Verify by HEAD ADVANCE
    # (HEAD moved since pre_head), NOT by grepping the commit message for the pack
    # token: this repo's convention FORBIDS pack IDs in commit messages, so a
    # token-grep false-halts after every correctly-messaged commit (the exact failure
    # the first real run hit). HEAD-advance is convention-independent and robust.
    if [[ "$(git rev-parse HEAD 2>/dev/null)" != "$pre_head" ]]; then
      commit=$(git rev-parse --short HEAD)
      # Record the commit as soon as HEAD is seen to have advanced -- one
      # `rev-parse --short` sits between the check above and this record, so a kill
      # inside that window still re-runs the session -- and BEFORE the post-commit
      # gates, so a gate halt / mid-verify kill leaves a committed-but-ungated marker
      # a re-invoke can re-gate, instead of re-running the session and false-halting
      # as HALTED-nocommit. Cleared by post_commit_verify_and_finalize once landed.
      _record_committed_marker "$pack" "$commit"
      post_commit_verify_and_finalize "$pack" "$file" "$commit" "$pre_head" "$pack_start"
    else
      echo ">> $pack: goal returned 0 but HEAD did not advance - no commit made. Halting." >&2
      REPORT_ROWS+=("$pack|HALTED-nocommit|-|$((SECONDS - pack_start))")
      exit 1
    fi
  else
    rc=$?
    echo ">> $pack: claude exited $rc (cap or failure) - halting chain." >&2
    REPORT_ROWS+=("$pack|HALTED-claude|-|$((SECONDS - pack_start))")
    exit "$rc"
  fi
done

echo "ALL PACKS COMPLETE."
