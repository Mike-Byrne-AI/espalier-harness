# Gates the targeted proofs never show

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Gates the targeted proofs never show"

A lane on `tools/cc/` or `tests/` runs its targeted proofs green, dispatches
its reviewers, runs the full tier once, and reds on a gate that no targeted
proof exercises. Each of the first four below cost the §C12 reflect lane a serial
re-run of the full tier on 2026-09-08 (about ten minutes each on the 8 GB
box). The §C10 scanner lane the same day checked those four before its tier and
none fired. The gates are repo-specific, which is why `/recall` on the task
never surfaces them: they are hazards of the artifact kind, not of the task.

## The first four, with the remedy each wants

1. **A test that iterates a SOURCE container is a census row.** A new test
   that loops over a pattern list, a roster, a tuple of guard files, or any
   population that lives in the source it polices trips
   `tests/test_derived_population_census.py`. Remedy:
   `python3 scripts/derived_population_census.py --print-adjudicated-entry
   <test file>` prints the one line to paste, with a verdict that must cite
   a `path:line` remedy; then move `ADJUDICATED_ROW_COUNT` by the delta.
   The row's identity is the population expression's SOURCE TEXT, byte for
   byte (`population_full` and `bound_via` are two of the three fields
   `file_digest` hashes), so two branches that differ only in how a literal is
   quoted are two distinct rows, and a cosmetic requote moves the digest.
2. **The adopter-pointer gate reads a constant inside a `return` as emitted
   output.** A tuple or string that names a self-host-only file (a memory
   note, a task pack, a report) and is referenced inside a `return`
   expression reads as text an adopter will see
   (`tests/test_adopter_pointer_resolution.py`). Remedy: read the constant
   into a local first, or keep the self-host name out of the returned value.
   The same gate's OUTPUT arm: a path in adopter-visible output (a banner
   line, a deny message) must exist on an adopter's tree, and the test has no
   exemption arm by construction, so state the fact inline instead of naming
   `cc/GOAL.md` (2026-09-15, lane 3).
3. **The probe-shape ratchet rejects a probe that reads TEXT out of its own
   subject file.** A new ledger probe built on `count(`, `findall`, `grep`,
   `.read()`, `read_text`, `in open(` or `splitlines` over its subject is a
   probe the fix's own paperwork can satisfy
   (`tests/test_check_ledger_probes.py`, the `_TEXT_READS` markers and their
   grandfathered baseline). Remedy: build it on `ast.parse(` or drive the
   instance, which the ratchet reads as structural. A strike that retires a
   baselined probe leaves a dead baseline slot; drop the id.
4. **A deployed `tools/cc/` file that defines residue tokens joins the
   placeholder-scan exclusions.** A file under `tools/cc/` that spells the
   placeholder tokens it scans for reds `tests/test_proofs.py` until it is
   listed in `espalier/proofs.py::_PLACEHOLDER_SCAN_EXCLUSIONS` beside the
   siblings that already are.

## How to apply

Run the four before the tier, not after: the census test, the pointer test,
the ledger-probes test and the proofs test together take under two minutes,
against ten for a tier re-run. The `/implement-task` body's "enumerator pins"
step is the natural place; these four are the enumerators that step did not
name. A fifth check of the same family, cheaper still, is
`python3 -m espalier provenance .`, which catches a pack id written onto a
shipping surface such as the changelog (the §C10 lane's one blocker).

## More gates, found lane by lane (items 5 on; the first from the §C13 strike step, 2026-09-08)

5. **A probe that conjoins a mechanism the fix keeps cannot flip.** DEF-417g's
   text probe required `safe_rglob` present AND `ls-files` absent; the fix
   keeps the tree walk as the no-index fallback, so the probe would have
   printed its open value forever. Re-pin it to a driven instance BEFORE the
   first edit -- `ledger_row.py repin` requires the open value, and pre-fix
   the instance prints it for free; after the fix the repin needs the fix
   stashed.
6. **A TEXT probe over a test module flips when a new test mentions its
   token.** DEF-487's probe (`'dist-info' not in tests/test_wheel_payload.py`)
   became a strike candidate because the lane's new wheel test filters
   `.dist-info/` members, while the licence assertion the row is about was
   still absent. Re-pin to a structural probe (ast: no test function names
   the subject) before trusting a candidate the lane did not earn.
   Again on 2026-09-21, this time in the lane that CLOSED the row. `DEF-412a`'s
   probe counted files under `tests/` containing the origin pack's id; the new
   guard's own class docstring named that pack and took the count to 1. When
   the close is real the flip is still not the evidence for it: strike on a
   driven proof instead -- the guard hunk reverted in a `--shared` clone
   returned 0, restored it returned 2 -- and put that proof in the closing
   text, so the next reader is not resting on a probe the lane's own paperwork
   moved. Items 11 and 13 say re-pin rather than strike; this is the third
   disposition, for the row that has genuinely landed.
7. **A strike text that quotes a regex with a bare `|` mis-splits the ledger
   row** for both member-row parsers (`test_forward_ledger_completeness` reds
   at a ceiling of 0). Escape pipes in any cell.
8. **A row's tag cells follow the class index, axis by axis.** A class the
   index marks MIXED on an axis takes the row's own cell there and the class
   tag on the other, so `ledger_row.py file --section C13 --population
   LOGIC_BUG --audience MAINTAINER` lands (§C13 is `LOGIC_BUG / MIXED` on the
   live ledger, 2026-09-20) while `--population HYGIENE` there is refused by
   name; a fully classed section refuses any cells, and §C0 (MIXED on both)
   takes both. Until 2026-09-20 this entry said the maintainer row of an
   adopter class "goes to the MIXED §C0" -- the both-axes reading the verb
   itself held (`DEF-776`), already false on four live classes at the time.
9. **A deployed hook or skill body that names a doc by path trips two gates
   unless the doc is in `managed_inventory`.** `tests/test_deploy_doc_parity.py`
   (hook string-literal doc refs) and `tests/test_adopter_pointer_resolution.py`
   (bare-path pointers in deployed docs, `.claude/` bodies included) both
   reddened the §C11 lane's first tier on 2026-09-09 because `session_start.py`
   docstrings and the hook-authoring `SKILL.md` table cited
   `docs/external/cc-worktrees.md`, and only `cc-hook-protocol.md` ships.
   Remedy: name the pin without a path (the `cc-worktrees` external pin) or
   state the fact inline; deploying a new managed doc is an enumeration change
   with its own fan-out and a lane of its own. Check before the tier:
   `command grep -rn 'docs/external/' tools/cc/ .claude/` should name only
   `cc-hook-protocol.md`.
10. **A probe that reads a node's SOURCE SEGMENT is a text read wearing
   structural clothes.** The ratchet exempts a predicate that parses, on the
   ground that comments leave no AST node -- but a docstring does, and a node's
   source segment carries it verbatim. A clause looking for a helper's NAME
   inside a function's source segment was satisfied by the docstring bullet the
   fix itself wrote: reword the bullet and a closed row reads reopened, delete
   the call and leave the prose and it stays closed. Pin such a clause at the
   CALL (the name with its opening paren) or at a node type, never at a bare
   name a docstring can carry -- 26 live probes read a source segment on
   2026-09-11, so this is a population, not a one-off.
11. **Same class as 10, the other sign: a probe whose predicate conjoins a
   mention with a bare attribute name flips on a lane that never touched its
   subject.** One row's probe counted files that import a registry AND mention
   an attribute name; an unrelated class gaining a same-named attribute moved
   the count, and the row is gitignored, so acting on that candidate is
   unrecoverable. Run the strikes check after every lane, and when a candidate
   appears your lane did not earn, re-pin the probe rather than strike the row.
12. **Two more bookkeeping gates, both review blockers on 2026-09-12, neither
   visible to any targeted proof:** the bare-anchor ratchet
   (`tests/test_catalog_self_consistency.py`) reds on a NEW `path:NN` spelling
   anywhere in the tree, a helper's comment included (`_MAX_BARE_ANCHORS` only
   moves down -- spell the example as `path::symbol`); and the census's
   `ADJUDICATED_FILE_COUNT` moves with `ADJUDICATED_ROW_COUNT` when the new
   entry is a new FILE (`tests/test_derived_population_census.py`, 85 s). Run
   both beside the enumerator pins before dispatching the reviewers.
13. **A probe whose open value is a hand-kept COUNT is moved by the lane that
   fixes the row's own class.** DEF-720 pins `cmd_scan`'s hand-kept telemetry
   roster at `10:0:12`; enrolling the eleventh scanner by hand in three lists
   -- the very defect the row names -- printed `11:0:13` and read as a
   STRIKE_CANDIDATE while the gap the row names had not closed. A candidate
   your lane DID earn is still a re-pin when what moved is the count the probe
   prints rather than the defect the row states: `ledger_row.py repin
   --reason` records why the number moved, and the strike waits for the
   derivation (2026-09-14).
14. **A fold into `memory/` or `docs/` reds gates the lane's own proofs never
   touch, and the pasted recall figures live at THREE sites.** A fold into a doc
   the asset sync mirrors (`scripts/sync_asset_docs.py::_MIRRORED` derives the
   set: `docs/FAILURE_MODES.md`, `docs/HOOKS.md` and three of the 25
   `docs/sharp-edges/` files; `--check` verifies parity without writing) breaks
   byte-parity in `tests/test_deploy_doc_parity.py`. Any fold the pull corpus
   reads moves the recall figures pasted at three sites, all guarded by
   `tests/_recall_pins.py` and red together at the handoff gate
   (`tests/test_recall_pasted_counts.py`): the `LENGTH_NORM_ALPHA` table in
   `tools/cc/hooks/_recall.py` (regenerate with `scripts/recall_eval.py
   --alpha-sweep`; keep the three `<-` markers and the alpha-0 parenthetical),
   the strip table in `scripts/recall_eval.py` (`--sweep`), and the count in
   `.claude/commands/recall.md` (re-paste from the report). Order: every fold
   first; then the sweeps, which read the tree they run in; then the sync each
   paste owes (`sync_vendor_cc.py` for the hook, `sync_claude_mirrors.py` for
   the command, `sync_asset_docs.py` for the doc). The `recall` tier shows
   these reds; the lane's targeted proofs show none (as of 2026-09-15: the
   09-14 folds moved the alpha-0 tie column 3 -> 4, the 09-15 folds 4 -> 3).
   The `/recall` body also carries a DATE beside its pasted figures: re-date
   it with the re-paste, and expect the bucket counts to move on any corpus
   edit, not only a fold (lane 8's two `docs/SHARP_EDGES.md` entries moved the
   four-line bucket 34 -> 45 on 2026-09-15).
   Each site has its own band, so re-paste only the sites that red (the
   2026-09-21 lane re-pasted the alpha table, green at HEAD, beside the red
   strip table; every elective paste is one more chance to drop a marker or
   strand a sentence). The full tier collects `tests/test_recall_eval.py`
   (`RECALL_SLICE_FILES` is what the recall tier ADDS), so a 0-red full tier
   says the tables were inside their bands on that tree and nothing more.
   The prose beside each table restates cells, and the sub-second
   `test_the_prose_beside_the_tables_restates_their_cells` in
   `tests/test_recall_eval.py` pins the strip paragraph's figures, the sign
   of every delta, the min-kept ratio and accuracy readings, the alpha
   block's dated gain pair and margin, and the date on every such reading
   against its own table's paste date, so a paste that leaves a sentence or a
   date behind reds; the gain itself is held as a property by
   `test_alpha_zero_shows_the_bias_the_exponent_corrects`. A provenance line
   carries the paste date, the counts and a prior paste's dated facts (the
   308-by-coincidence note stays); never THIS re-paste's cause, which goes in
   the commit and the ledger row, or the next re-paste inherits a false
   history (both tables carried one on 2026-09-21 until the failure-mode
   review struck them).
15. **The `file` verb cannot open a section: `--after` is required and refuses
   when no member row carries that id, so a brand-new class has nothing to
   follow.** §C52 was seeded on 2026-09-14 by a hand block that reused the
   verb's own helpers (`check_ledger_probes.run_probe`, `_pins`, `_load_probes`,
   `_commit_both`), so the probe was still driven before the write and both
   files still committed together; a hand edit that skips them leaves `_count`
   disagreeing with its rows and the next verb refuses outright. Seed a new
   class that way until `ledger_row.py file` grows a `--first-in-section`
   mode, never by editing the two files directly.
16. **A word swept through the shipped prose trips two contracts a guard's own
   proofs never touch.** Renaming a doc HEADING orphans the anchor a doc-parity
   table pins it by (`tests/test_hook_utils.py::_DOC_ENUMERATION_SITES`
   re-anchored on 2026-09-14 when "Protected-zone writes" became
   "Protected-zone mutations"), and adding one `bench/corpus/` row moves a count
   the README fragment and its claim test both carry
   (`tests/test_documented_claims.py`, the bypass-class count). Grep the anchor
   table for the old wording and run those two files before the tier whenever
   a lane renames a heading or adds a corpus row: both reds came back from the
   reviewers, not from the lane's own proof set.
   The PowerShell rehearsal's count sentence is the same shape: it is derived
   from its rows, so re-measure it after adding rows (four rows moved it to
   465 in lane 8, 2026-09-15).

17. **A new `append_audit` swallow in a hook must carry the canonical noqa
   template verbatim.** `tests/test_hook_audit_noqa_annotations.py` pins the
   reason text of `_hook_utils.HOOK_AUDIT_NOQA_TEMPLATE`, not merely its words:
   a swallow annotated in your own phrasing reds the tier. Copy the template
   from a sister site (2026-09-15, lane 3).
18. **`docs/ENV_CATALOG.md` cites read-site line numbers with a 15-line
   tolerance.** A hook edit that moves an environment read by more than
   `tests/test_env_catalog.py::_READ_SITE_TOLERANCE` reds the catalog test:
   re-anchor the cited line and sync the asset. Do not re-tune the tolerance
   blind; the test's own docstring says why (2026-09-15, lane 3).
19. **Every module-level regex in the hook modules the census walks is
   anchored or declared, and a `(?!=)` literal enrols it as a verb regex.**
   `tests/test_speedbump_irreversible.py::test_every_pattern_is_anchored_or_classified`
   reds on a pattern that is not anchored to a command position unless it is
   declared in `_UNANCHORED_BY_DESIGN` (and in `_ANCHOR_EXEMPT` when it carries
   a verb word); a declaration that outlives its pattern reds
   `test_no_stale_anchor_exemptions`. Five new patterns reded the census in
   lane 8. The sibling assignment-guard census in the same file enrols any
   pattern carrying the literal `(?!=)` as a verb regex: spell a non-verb
   lookahead `(?![=])` (2026-09-15, lane 8).
20. **The dot-star gate walks every `re.compile` in a hook file and cannot
   reconstruct one built from `re.escape(name)`.** `tests/test_redos.py`'s
   dot-star completeness gate reads each compiled pattern statically; a
   `re.compile` inside a function whose argument is composed from an escaped
   name is opaque to it and reds the gate. Keep a pattern STRING and pass it
   to `re.sub` / `re.findall` (2026-09-15, lane 8).
21. **The derived-regex ReDoS row drives `search`, not `match`.**
   `tests/test_redos.py` floods every derived hook pattern through `search`,
   so a pattern whose head can begin at any position of a leading blank run is
   quadratic on a blank flood even when the hook only ever calls `match`.
   Refuse the blank-led start with `(?<![ \t])` (2026-09-15, lane 8).

22. **A ledger row COUNTS once, by its first id, and is ADDRESSED by any id
   its cell carries.** `generate_ledger_regions.live_member_ids` /
   `struck_member_ids` are the counting sets (the json-mode floor and the
   cut's conservation check compare them); `live_cell_ids` / `struck_cell_ids`
   are the membership sets, and `cell_ids(row)` reads every id-shaped token of
   the first cell up to the first unescaped pipe. A gate that asks about an ID
   -- index-row parity, a probe on a struck row, a probe with no hash -- keys
   on membership: keyed on first ids, three gates were blind to nine live
   co-ids and eight unstamped probes, and widening the counting sets instead
   would have moved the floors. The verbs and the checker's two readers
   address a row by any id; `strike` closes the whole cell with every index
   row and probe it owns; `repin` stamps only the id it drove and names the
   siblings, so a two-id row is one `repin` per id that owns a probe
   (2026-09-20, `DEF-863`, both reviews).
23. **A pack id in a COMMENT EXAMPLE on a `scripts/` file is a provenance tag,
   and the contract tier is the first proof that reads it.**
   `python3 -m espalier provenance .` (one second) reds on a `TP-` id in a
   shipped script's comment or docstring; no targeted run sees it, and the trip
   cost the tier twice in two sessions on the same ledger scripts. Spell an
   example id `DEF-N`, `LG-N` or `PR-N`, and run the census before the tier
   whenever a comment in `scripts/` changed (2026-09-20, 1-D sessions 1 and 2).
24. **A decision row that owns a probe has no verb.** `scripts/ledger_row.py::_cells`
   refuses any row that is not 4 or 6 cells, and `repin`, `strike` and `file
   --after` all pass through it; §4A (open operator forks) is a three-cell table
   and three of its rows (`DEC-28`, `DEC-29`, `DEC-32`) carry pinned probes. A
   rebuild that rewrites one leaves a STALE_CLAIM no verb clears (`DEF-869`). Until
   the verb exists, stamp it the way `repin` would and nothing less: drive the
   probe with `check_ledger_probes.run_probe`, set `row_sha`/`text_sha` from the
   checker's own functions, re-derive `_count`, record the reason in
   `verified_<date>`; never touch the pin without driving the probe (2026-09-20,
   1-D session 3, the live write's re-pin pass).

Related: [[recall-keys-on-the-hazard-not-the-task]] (why the task text never
recalls these) · [[calibrate-an-enforcement-contract-against-the-live-population]]
(the census and the ratchet are both contracts calibrated against the live tree).
