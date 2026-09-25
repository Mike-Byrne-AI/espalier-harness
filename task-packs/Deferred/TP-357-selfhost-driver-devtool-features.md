# TP-357 — Self-host driver & dev-tool features (pack-chain `--all-draft` · reports/ link-checker · statusline `deny:` counter · verify-landing `--check-working-tree`)

## Status
- Version target: current (self-host, pre-OSS-launch)
- Change type: FEATURE — four **internal dev-tooling** additions. Each is a self-host
  driver/CLI/statusline nicety an OSS adopter never touches. None gates the public flip.
- **Kind: PACK** (four independent sub-tasks; may land as one commit or be cherry-picked)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`, 100 agents /
  6.0M tokens) + `reports/lost-idea-sweep-2026-07-26.md` — section C rows #10, #21, #22 and
  #32. All four are verified-lost forward-work (un-tracked + un-done) surfaced pre-flip; each
  cites the Done-pack/comment where the deferral was originally made.

## Motivation

The pre-flip sweep found 55% of swept references were already tracked/done, and no lost item
gates function. These four are the self-host **feature** residue — each was scoped OUT of a
prior pack as "nice, later," then never entered the FORWARD_LEDGER's lineage (the seam a
self-consistency audit structurally can't catch). They are grouped here because they share one
property: **internal dev tooling, launch-neutral, low leverage.** Packing them makes them
*tracked* (the reason they leaked is they weren't) without asserting any of them must ship
before the OSS flip — the operator's disposition (and this pack's own recommendation) is
**defer to a post-launch cleanup window**.

None is a bug. #10 and #32 add a mode to an existing tool; #21 builds a root-cause guard for a
class TP-340 papered over once; #22 completes a sibling that shipped without its twin.

## Scope (in)

### Sub-task 1-A — `verify-landing --check-working-tree` mode (`espalier/verify_landing.py` + `cli.py`)
The module is HEAD-only and **self-documents the gap**: its docstring (`verify_landing.py:13-14`)
reads *"It is HEAD-only; a ``--check-working-tree`` mode (untracked-but-present) is a deliberate
follow-up."* A pack whose claimed files are written but **not yet committed** classifies every
one of them `OWED` today — indistinguishable from "never written." The follow-up mode
introduces a fourth state: a claimed path that is **absent from HEAD but present in the working
tree** (staged-new or untracked-not-ignored) is `PENDING`, not `OWED`.

**Fix (three coordinated edits, all in shipped surfaces — NO `TP-NNN` literal in any):**

Edit 1 — add the `PENDING` constant beside the existing states (`verify_landing.py:29-31`):
```python
LANDED = "LANDED"
DRIFTED = "DRIFTED"
OWED = "OWED"
PENDING = "PENDING"  # absent from HEAD but present in the working tree (staged-new / untracked)
```

Edit 2 — thread an optional `untracked` set through the pure classifier so it stays
git-I/O-free and unit-testable. Current `_classify_token` (`verify_landing.py:148-164`) resolves
against `tracked` then returns `OWED` on no match; extend the no-match arm:
```python
def _classify_token(
    token: str, tracked: set[str], modified: set[str], untracked: set[str] | None = None
) -> LandingEntry:
    resolved = _resolve_matches(token, tracked)
    if not resolved:
        if untracked and _resolve_matches(token, untracked):
            return LandingEntry(token, "present", PENDING)
        return LandingEntry(token, "absent", OWED)
```
`classify_against` (`verify_landing.py:167-176`) grows the same optional `untracked` param and
forwards it to `_classify_token`. `classify_landing` (`verify_landing.py:196-200`) gains a
`check_working_tree: bool = False` flag; when set it also runs
`git ls-files --others --exclude-standard` (untracked-not-ignored) **plus**
`git diff --cached --name-only` (staged-new) via the existing `_git_lines` helper and passes
the union as `untracked`. `render_table` (`verify_landing.py:203+`) adds a `PENDING` column to
the summary `Counter` line.

Edit 3 — wire the flag in the CLI. `cmd_verify_landing` (`cli.py:3706-3741`) currently calls
`classify_landing(pack_text, repo)`; pass `check_working_tree=args.check_working_tree`. Add the
argparse option to `p_landing` (`cli.py:5052-5056`, beside `--json`):
```python
    p_landing.add_argument(
        "--check-working-tree", action="store_true",
        help="also classify claimed-but-uncommitted paths present on disk as PENDING (default: HEAD-only)",
    )
```
Update the `verify_landing.py:13-14` docstring to describe the shipped mode (drop "deliberate
follow-up") — this closes the self-described debt comment (row #32's sole anchor).

**Earn the red:** extend `tests/test_verify_landing.py` (a pure-classifier test against
`classify_against`) — a pack claiming `foo/new.py` with `foo/new.py` in the `untracked` set but
NOT in `tracked` asserts `PENDING` under the new param and `OWED` when `untracked` is omitted.
RED before Edit 2 (the arg doesn't exist / returns OWED); GREEN after.

### Sub-task 1-B — Statusline `deny:<N>` counter (`tools/cc/statusline.py` + vendor mirror)
`/status --explain <path>` shipped as TP-332 and `/status --log` (the audit-tail reader) as
TP-330, but the passive at-a-glance counter — how many governance denials the harness logged
for this repo *today* — never made it to the status line (row #22). The audit log already
records them: `_integrity.DENIAL_EVENT_TYPES` (`tools/cc/hooks/_integrity.py:728-734`) is the
single-owner set, and `_integrity.tail_audit(repo, n, event_types=...)`
(`_integrity.py:737-773`) already filters to it.

**Fix (add one indicator; NO `TP-NNN` literal):** add a `_deny_count_indicator(root)` to
`statusline.py`. Lazy-import `_integrity` from the `hooks/` subdir with the **exact
sys.path pattern `session_resume._print_audit_tail` uses** (statusline lives in `tools/cc/`,
`_integrity` in `tools/cc/hooks/`), count today's denials, suppress at zero:
```python
def _deny_count_indicator(root: Path) -> str | None:
    """Count of governance DENIALS logged for this repo today, or None if zero.

    Reuses _integrity's own DENIAL_EVENT_TYPES + audit-path resolution so the
    count can never drift from what `/status --log` shows. Lazy sibling import
    (hooks/ is a subdir) — never at module top, mirroring _print_audit_tail.
    """
    hooks_dir = Path(__file__).resolve().parent / "hooks"
    inserted = str(hooks_dir) not in sys.path
    if inserted:
        sys.path.insert(0, str(hooks_dir))
    try:
        import _integrity  # noqa: E402
    except Exception:  # noqa: BLE001 -- statusline never raises
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(str(hooks_dir))
            except ValueError:
                pass
    lines = _integrity.tail_audit(root, 1_000_000, event_types=_integrity.DENIAL_EVENT_TYPES)
    return f"deny:{len(lines)}" if lines else None
```
Add it to the `indicators` tuple in `main` (`statusline.py:185-190`) — after
`_freshness_summary`; the existing per-indicator `try/except` in the loop
(`statusline.py:191-198`) already isolates a failing segment, so a broken audit read degrades
only itself. Add a `- ``deny:<N>``` bullet to the module docstring (`statusline.py:5-14`).
Then `python3 scripts/sync_vendor_cc.py` (byte-parity-pinned mirror
`espalier/_vendor/cc/statusline.py`; `tests/test_vendor_cc_parity.py` reds on drift — never
hand-edit the mirror).

**Latency caveat (measure before landing):** statusline runs **every prompt cycle**. Unlike the
other segments (env-var reads + one bounded JSON read), this lazy-imports `_integrity` and reads
today's audit log each cycle. Re-deriving the audit path inline in statusline would avoid the
import but **drift from `_integrity.audit_path`'s resolution** (the ESPALIER_AUDIT_DIR override +
repo-slug + date owner) — the documented anti-pattern — so the import is the correct call. Before
landing, measure the added per-prompt wall-clock against the ~170ms hook-latency prior
(`docs/HOOK_ASSUMPTIONS.md` context); if material, gate the segment behind an opt-in env var.

**Earn the red:** extend `tests/test_statusline.py` — seed a denial via
`append_audit(tmp_repo, {"event_type": "pretooluse_blocked_protected_zone", ...})` (using an
`ESPALIER_AUDIT_DIR` override for isolation), run `main`, assert `deny:1` in stdout; assert the
segment is ABSENT when no denials exist. RED before the indicator is added to the tuple; GREEN
after.

### Sub-task 1-C — Committed link-checker over gitignored `reports/` (`scripts/check_reports_links.py`, new)
`espalier/reflect_protocol._iter_surface_files` (`reflect_protocol.py:109-143`) walks only the
committed CC surface (root docs, `docs/`, `cc/` minus `LOCAL_ONLY_PREFIXES`, `.claude/`) — it
**never walks `reports/`** (confirmed gitignored via `git check-ignore`). So phantom
cross-reference rot inside `reports/*.md` is invisible to the broken-link guard; TP-340 papered
over one such instance by hand. This builds the root-cause guard (row #21).

**Fix (new standalone script; `scripts/` is scanned for `TP-NNN` — introduce none):** a
stdlib-only `scripts/check_reports_links.py` that walks `reports/**/*.md`, extracts local
markdown links, resolves each relative to its file, and reports the unresolvable ones (exit 1 if
any, 0 if clean). It takes a `--root` arg (default `reports/`) so it is testable against a tmp
fixture tree. It **deliberately re-inlines a minimal link regex** rather than importing
`reflect_protocol._extract_local_links` (a module-private symbol): `reports/` is
gitignored/regenerable and must not couple to the engine's reflect internals (a rename there
would silently break this guard). The regex mirrors `LOCAL_LINK_RE`
(`reflect_protocol.py:38`): `\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)`, split on `#` for
anchors, skip fenced code blocks.

**Earn the red:** add `tests/test_check_reports_links.py` — a tmp `--root` with `a.md` linking a
present `b.md` (resolves) and a missing `gone.md` (broken): assert exit 1 + `gone.md` named. Fix
the fixture link → assert exit 0. RED is the broken-link detection itself (proves the checker
sees rot the reflect surface can't); GREEN after the fixture is repaired.

### Sub-task 1-D — `run_pack_chain.sh --all-draft` auto-discovery (`scripts/run_pack_chain.sh`)
The driver requires explicit `TP-NNN` tokens (`run_pack_chain.sh:75` usage; `for pack in "$@"`
at `:663`). Row #10 wants a `--all-draft` mode that discovers every top-level DRAFT pack and
runs them in TP-order.

**⚠ Convention tension (must be honored, not ignored):** this cuts directly against the
**author-then-STOP** discipline (`memory/make-a-pack-means-author-then-stop.md`) — authoring a
pack and *executing* it are deliberately separate operator decisions. Auto-running **every**
DRAFT pack removes the per-pack "is this one ready?" gate. The feature is therefore gated behind
**an explicit, must-be-typed opt-in flag** (never a default, never inferred) **plus a loud
stderr banner** that lists exactly which packs will run and restates the caveat, so the operator
sees the full batch before a cent is spent. Pairing `--all-draft` with the existing `--dry-run`
lists the batch without running it — the recommended first invocation.

**Fix (`scripts/` — no `TP-NNN` literal):** add the flag to the arg-parse `case`
(`run_pack_chain.sh:63-73`):
```sh
    --dry-run) DRY_RUN=1; shift;;
    --fresh)   FRESH=1; shift;;
    --all-draft) ALL_DRAFT=1; shift;;
```
Add a discovery function (near `resolve_pack_file`, `run_pack_chain.sh:105-120`) that greps the
top-level pack dir (NOT `Done/`) for `State: DRAFT`, extracts the `TP-NNN` token from each
filename, and sorts numerically:
```sh
discover_draft_packs() {   # echoes TP-NNN tokens, one per line, TP-number-sorted
  grep -lE '^- State: DRAFT' "$PACKDIR"/TP-*.md 2>/dev/null \
    | sed -E 's#.*/(TP-[0-9]+)-.*#\1#' \
    | sort -t- -k2,2n -u
}
```
Then, **before** the empty-args guard (`run_pack_chain.sh:75`), expand the discovery into the
positional params and emit the caveat banner:
```sh
if [[ ${ALL_DRAFT:-0} -eq 1 ]]; then
  mapfile -t _drafts < <(discover_draft_packs)
  [[ ${#_drafts[@]} -gt 0 ]] || { echo "--all-draft: no DRAFT packs in $PACKDIR/" >&2; exit 2; }
  echo ">> --all-draft: will run ${#_drafts[@]} DRAFT pack(s) in TP-order: ${_drafts[*]}" >&2
  echo ">> --all-draft OVERRIDES author-then-STOP (each pack is normally a deliberate run). Ctrl-C now to abort; add --dry-run to list only." >&2
  set -- "${_drafts[@]}"
fi
```
(`mapfile` is bash 4+; the driver is already bash-only — it uses `[[ ]]`/arrays throughout.)

**Earn the red:** extend `tests/test_run_pack_chain.py` — point `PACK_CHAIN_PACKDIR` at a tmp
fixture holding three DRAFT packs (`TP-401`, `TP-402`, `TP-410`) + one non-DRAFT, invoke
`--all-draft --dry-run`, assert the banner lists exactly the three DRAFT tokens in numeric order
and the non-DRAFT is excluded. RED before the flag exists (`unknown flag: --all-draft`, exit 2);
GREEN after.

## Scope (out)
- **NO interactive confirmation prompt on `--all-draft`.** The driver's whole purpose is
  unattended `claude -p` chaining (`memory/autonomous-p-loop-is-disk-baton-cycle.md`); a blocking
  `read` would defeat it. The explicit flag + loud banner + `--dry-run` list-first path IS the
  gate. (If a stronger interlock is ever wanted, a separate `ESPALIER_ALLOW_ALL_DRAFT=1` env
  guard is the follow-up — deliberately not built here.)
- **1-C does NOT fold `reports/` into the reflect surface** (`_iter_surface_files`). `reports/`
  is gitignored/regenerable; adding it to the committed-surface walker would make the reflect
  guard fire on transient scratch. A separate opt-in checker is the correct shape — the item's
  own framing ("committed link-checker OVER gitignored reports/").
- **1-C does NOT reuse `reflect_protocol._extract_local_links`.** Importing a module-private
  symbol from the engine into a gitignored-tree guard invites silent breakage on a reflect
  rename. The tiny regex is duplicated on purpose (documented in the script).
- **1-B does NOT add a new `_integrity` helper** (e.g. `count_audit`). `tail_audit` with a large
  `n` already returns every filtered record; a new helper would widen the vendored-hook surface
  (its own sync + parity obligation) for no gain.
- **The other section-C long-tail rows** (#1/#4/#6/#9/#11-13/#17-20/#23/#25/#27-31/#33/#34/#39)
  and section-B/E items are NOT in this pack — they are distinct concerns (test-debt, latency
  levers, scanner extensions, ledger rows). This pack is scoped to the four **driver/dev-tool
  FEATURE** rows only; the rest belong in their own packs or one-line ledger rows.

## Affected symbols

### Changed-semantics
- `espalier/verify_landing.py::_classify_token` — new optional `untracked` param; PENDING arm (1-A)
- `espalier/verify_landing.py::classify_against` — forwards `untracked` (1-A)
- `espalier/verify_landing.py::classify_landing` — new `check_working_tree` flag; runs `ls-files --others` + `diff --cached` (1-A)
- `espalier/verify_landing.py::render_table` — PENDING column in the summary line (1-A)
- `espalier/cli.py::cmd_verify_landing` — passes `check_working_tree`; adds `--check-working-tree` to `p_landing` (1-A)
- `tools/cc/statusline.py::main` — `_deny_count_indicator` added to the `indicators` tuple (1-B)
- `espalier/_vendor/cc/statusline.py` — byte-mirror regenerated via `sync_vendor_cc.py` (1-B)
- `scripts/run_pack_chain.sh` — `--all-draft` arg-parse branch + pre-empty-check expansion (1-D)

### Added-paths
- `espalier/verify_landing.py::PENDING` — new state constant (1-A)
- `tools/cc/statusline.py::_deny_count_indicator` — new indicator function (1-B)
- `scripts/check_reports_links.py::main` — new standalone checker (1-C)
- `scripts/run_pack_chain.sh::discover_draft_packs` — new discovery function (1-D)
- `tests/test_verify_landing.py` — PENDING classifier assertion (1-A)
- `tests/test_statusline.py` — `deny:<N>` segment assertion (1-B)
- `tests/test_check_reports_links.py` — broken/clean-link fixture (1-C)
- `tests/test_run_pack_chain.py` — `--all-draft --dry-run` discovery assertion (1-D)

### Renamed
- (none)

## Pass criteria
- **Earn-red 1-A:** the PENDING classifier assertion REDs (arg absent / returns OWED) before
  Edit 2; GREEN after. `--check-working-tree` on a real uncommitted-file pack shows PENDING, not
  OWED; the flagless run still shows OWED.
- **Earn-red 1-B:** the `deny:1` statusline assertion REDs before the indicator is wired into the
  tuple; GREEN after. `deny:` segment ABSENT at zero denials. Latency measured and recorded in
  Landing.
- **Earn-red 1-C:** the broken-link fixture REDs (checker exits 1, names `gone.md`); repaired
  fixture GREENs (exit 0).
- **Earn-red 1-D:** `--all-draft --dry-run` lists exactly the DRAFT tokens in TP-order (banner +
  caveat present); REDs (`unknown flag`) before the branch exists.
- **Mirrors:** `python3 scripts/sync_vendor_cc.py` run after 1-B; `tests/test_vendor_cc_parity.py`
  green. (No `.claude/` edit → `sync_claude_mirrors.py` not required.)
- **Full gate:** `pytest -q` green; `ruff check .` clean; `python3 -m espalier audit .` 0/0.
- **No `TP-NNN` literal** in any shipped surface this pack touches — `espalier/verify_landing.py`,
  `espalier/cli.py`, `tools/cc/statusline.py`, `scripts/run_pack_chain.sh`,
  `scripts/check_reports_links.py` are all scanned (only `espalier/_vendor/` is exempt, and the
  vendor `statusline.py` inherits the clean SoT byte-for-byte). This pack file lives under
  `task-packs/Deferred/` (gitignored) so its own `TP-357` literals never reach a scanned surface.

## Files touched
- **Modified:** `espalier/verify_landing.py` (1-A), `espalier/cli.py` (1-A),
  `tools/cc/statusline.py` (1-B), `scripts/run_pack_chain.sh` (1-D).
- **New:** `scripts/check_reports_links.py` (1-C).
- **New test cases (extend existing files):** `tests/test_verify_landing.py`,
  `tests/test_statusline.py`, `tests/test_run_pack_chain.py`; **new file**
  `tests/test_check_reports_links.py`.
- **Mirrors (regenerated, never hand-edited):** `espalier/_vendor/cc/statusline.py` via
  `scripts/sync_vendor_cc.py` (1-B).
- **Unmodified on purpose:** `espalier/reflect_protocol.py` (`reports/` stays out of the reflect
  surface — see Scope out); `tools/cc/hooks/_integrity.py` (reused as-is, no new helper).

## Sub-task ordering
1. **1-C** (smallest, isolated new file — build momentum, surface env issues early): write
   `scripts/check_reports_links.py` + `tests/test_check_reports_links.py` → observe RED on the
   broken fixture → GREEN on repair. Checkpoint: `pytest -q tests/test_check_reports_links.py`.
2. **1-A** verify-landing mode: add PENDING + thread `untracked` + CLI flag → RED on the
   classifier assertion → GREEN. Checkpoint: `pytest -q tests/test_verify_landing.py`.
3. **1-D** `--all-draft`: add flag + `discover_draft_packs` + banner → RED (`unknown flag`) →
   GREEN on `--all-draft --dry-run`. Checkpoint: `pytest -q tests/test_run_pack_chain.py`.
4. **1-B** statusline counter (last of the four — carries the vendor-mirror step): add
   `_deny_count_indicator` → RED → GREEN → `python3 scripts/sync_vendor_cc.py` → measure
   per-prompt latency. Checkpoint: `pytest -q tests/test_statusline.py tests/test_vendor_cc_parity.py`.
5. **final** full `pytest -q` + `ruff check .` + `python3 -m espalier audit .`; confirm no
   `TP-NNN` literal in the five touched shipped files; stamp Landing.

## Estimated effort
- 1-C ~30m · 1-A ~40m · 1-D ~35m · 1-B ~35m (incl. latency measurement + vendor sync) ·
  verify+land ~20m. **Total ≈ 2.5–3 h.**

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) 1-A PENDING assertion reds when `untracked` is omitted/absent; 1-B
  `deny:1` reds before the indicator joins the tuple; 1-C broken-link fixture reds (exit 1);
  1-D `--all-draft` reds as `unknown flag` before the branch exists.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (`wf_c28406bf-13f` /
  `reports/lost-idea-sweep-2026-07-26.md` rows #10/#21/#22/#32). All four are self-host dev
  tooling — an OSS adopter never touches any of them — so this pack is DEFERRED to a post-launch
  cleanup window per operator; none gates the public flip. Packing them makes them tracked (the
  reason they leaked is they never entered the FORWARD_LEDGER's lineage). 1-B carries a
  measure-before-shipping latency obligation (statusline runs every prompt).
