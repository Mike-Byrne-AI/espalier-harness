# TP-466 — Migrate an adopter's existing memory at setup, and make it findable where it lives

## Status

- Version target: unscheduled (after `0.8.0b2`); each wave is scheduled on its own.
- Type: feature (the setup phase) + design (the recall corpus).
- Ledger: one row in §3 names this pack. Each wave's child pack files its own rows.
- Children: `TP-466b` (Wave B, `task-packs/TP-466b-index-adopter-knowledge-in-place.md`, drafted 2026-10-07) is the first; it takes the doctor corpus line from Guards and leaves Waves A, C, D and E here.
- Gate: **operator decision pending** on which waves, if any, to schedule. Wave B is the cheapest and the only one with a measurement behind it.
- **Kind: ROADMAP** — author-and-stop. The deliverable is the analysis and the wave map below. Copy-ready Implementation and Pass criteria are withheld on purpose: every wave changes the protected hook layer or `init`, and each one earns its own pack, Task 0 and reviewers. This pack must not enter an unattended chain.
- Provenance: evidence from one field-trial adopter, a research repo with months of knowledge under a prior harness, where Espalier was installed beside the prior harness on 2026-10-01. The adopter's eval script and question set stay in the adopter's repo. Only counts and mechanisms are reported here.

## Motivation

`init` wires the machinery and moves none of the knowledge. On the field-trial adopter, the day after install:

1. **`/recall` answered 0 of 15 pre-registered questions** (0 top-1, 0 top-3). Nine questions targeted the adopter's operational pitfalls and six its current conclusions and gotchas. The corpus held 8 documents: 4 harness-seeded notes and 4 `## ` sections of the adopter's `docs/SHARP_EDGES.md`. Three of those sections were pointer indexes ("see CLAUDE.md"), and the fourth lumped six entries together because the loader splits only at `## ` (`tools/cc/hooks/_hook_utils.py::iter_doc_sections`). Seven questions landed on a pointer section and two on an unrelated harness note.
2. **Always-on cost was invisible to the guard.** Root `CLAUDE.md` was about 20 KB, loaded on every turn. One pitfalls section was 40% of it, and one bullet was 3.3 KB on a single line, most of it a chain of dated errata. The adopter's guard was a line cap, which cannot see a 3 KB line.
3. **The records stopped loading.** The prior harness loaded a generated digest of the adopter's append-only records (about 100 id'd findings, plus decisions and run logs) at session start. Retiring its continuity hooks retired that load, and nothing replaced it. The only conclusions that still reached a session automatically were machine-local auto-memory notes, outside git.
4. **A harness decision blocked recall by design.** The first Espalier session on the adopter recorded "SHARP_EDGES is a pointer index, not a copy", to avoid drift. Sound alone; combined with (1) it made the pitfalls unreachable by search.
5. **The memory model exists but is not deployed.** The seeded `memory/README.md` points at `docs/MEMORY_SYSTEMS.md` "(Espalier source repo — not deployed by `init`)", and it names auto memory's default path, which misses a relocated `autoMemoryDirectory`.
6. **Every write path worked:** auto memory, the reasoning chain, the session log and the ledger. The failure is on the read side.

`docs/MEMORY_SYSTEMS.md` already sorts *new* facts between the committed layer and auto memory, and `tools/cc/memory_sort_audit.py` detects backslide. Nothing addresses knowledge that predates the install. That is the gap this pack maps.

## Scope (in)

- **Wave A** — a memory and instruction migration step in the setup phase (onboarding rows plus a procedure).
- **Wave B** — index adopter knowledge where it lives: document and region markers, a records scope, and pointer sections kept out of the index.
- **Wave C** — temporary recall markers with a lifetime, stored outside the files.
- **Wave D** — temporary rules: the measured Claude Code behaviour and the constraints that follow from it.
- **Wave E** — an observer agent as the only writer of anything temporary.
- **Guards** so the problem does not regrow: a byte budget for root `CLAUDE.md`, one `## ` per catalog entry, and a doctor line for the recall corpus.

## Scope (out)

- **Moving an adopter's records into harness memory.** Records are evidence with ids, append-only and checked by the adopter's own tools. They stay where they are and get indexed in a separate scope (Wave B).
- **The `docs/MEMORY_SYSTEMS.md` sorting rule for new facts.** It stands. This pack extends it to knowledge that predates the install, and does not reopen it.
- **Shipping the adopter's eval script or questions.** A child pack that wants a harness-side eval writes generic fixtures. `scripts/recall_eval.py` and its task arm are the harness's own measuring tool.
- **Changing Claude Code.** Wave D works within the loader as probed.
- **A symptom-phrased eval of curated entries against in-place markers.** It is an open question (see Wave B), not a wave. Until it runs, "curated searches better" is a hypothesis.

## Task 0 — Verify

The evidence above comes from an adopter install of the 0.8.0b2-era hooks, not from `main`. Re-derive each load-bearing observation on `main` before any wave is scheduled.

- **Oracle:** a fresh adopter fixture with a non-trivial root `CLAUDE.md` (a pitfalls section), two `.claude/rules/*.md` files, a `docs/SHARP_EDGES.md` holding one pointer section and one multi-entry section, and an append-only records file. Run `init` on it, then:
  - list `_recall._load_corpus(root)` titles: how many documents are adopter-authored?
  - read the seeded `memory/README.md`: does it point at an undeployed doc, and at the default auto-memory path?
  - read `init`'s onboarding rows: does any row ask about pre-existing memory systems?
  - read the session-start banner: does any adopter record reach it?
- **Refuting result:** the corpus already includes adopter instruction files, or an onboarding row already inventories prior memory systems. Then the waves that duplicate it are scrapped or re-scoped, and this pack records which.
- **Exit:** a short table in this pack's Landing, one row per observation, marked held or refuted on `main`.

## Relevant memory

Recent pattern: recall answers confidently with the nearest match, so a missing entry looks like a wrong answer, not a gap. The adopter's 0/15 baseline is that pattern at install scale.

| Entry | Where |
|---|---|
| A memory note can be too long to be recalled | `memory/a-memory-note-can-be-too-long-to-be-recalled.md` |
| Recall keys on the hazard, not the task | `memory/recall-keys-on-the-hazard-not-the-task.md` |
| Fix the surface the reader consumes, not the one the fact is authored on | `memory/fix-the-surface-the-reader-consumes.md` |
| The recall corpus must gate harness-internal entries for adopters | `docs/SHARP_EDGES.md` |

Resolved 2026-10-02 by `python tools/cc/hooks/_recall.py "<topic>"` on `main` with the topics `memory note too long recalled` and `pointer section index search corpus`. The topics `auto memory sorting rule two stores`, `path-scoped rules load` and `temporary marker expiry` returned nothing applicable, which is itself the gap Wave B addresses.

## Implementation — the waves

Each wave becomes a child pack. Every prescription is labelled **measured** (run on the adopter), **probed** (Claude Code behaviour observed directly), or **untested** (a design).

### Wave A — a migration step in setup [untested as a harness feature; run by hand once]

1. **Inventory.** List root and folder `CLAUDE.md` files with byte sizes, `.claude/rules/`, record logs (append-only, id'd), generated digests, any prior continuity chain, and the auto-memory folder. Read `autoMemoryDirectory` from settings rather than assuming the default path.
2. **Sort by kind, not by system:**

| Kind | Examples | Home |
|---|---|---|
| Record | Findings, decisions, run logs | Keep in place; point at it; index in a records scope (Wave B) |
| Judgment | Pitfalls, principles | Searchable catalogs: footguns one `## ` each, principles |
| Synthesis | Current conclusions that cite record ids | Committed `memory/` notes, linked from the session log |
| Continuity | Goal, last session's reasoning | The harness chain; archive the old one |
| Personal | Cross-project working preferences | Auto memory, kept small |

3. **Keep, merge or replace per system,** each choice filed as an onboarding row with a probe. The default for records is keep and point.
4. **Decide the always-on budget item by item.** If an item need not load on every turn, move it to a folder `CLAUDE.md` or a path-scoped rule (loads on touch), or to a searchable catalog (loads on demand).
5. **Supersede conflicting harness decisions explicitly,** with the new evidence (Motivation 4).
6. **Measure before and after:** pre-registered questions and accepted answers, plus a fresh-agent check (an agent without private notes answers from the repo alone).

Where content can live, by load timing:

| Place | Loads when | Use for |
|---|---|---|
| Root `CLAUDE.md` | Every turn | Identity, mission, limits that apply everywhere, pointers |
| Folder `CLAUDE.md` | A file in that folder is read | That folder's pitfalls, short |
| `.claude/rules/*.md` with `paths:` | A matching file is read | Rules for root files that cannot have a folder file |
| Searchable catalogs | `/recall`, or when read | The full story, including erratum history |

### Wave B — index in place [measured, one adopter, 15 questions]

**Two axes, not one.** Today an item must be moved into a catalog and reshaped to be findable, which makes curation a precondition of search, and curation is the step that gets skipped at install. Separate the two:
- **push** (when an item loads) is decided by where it is placed;
- **pull** (whether it can be found) is decided by indexing, through curated entries or through markers on text where it already lives.

**The measurement.** Fifteen questions and their accepted answers were fixed before any arm ran. The ranker was the shipped `recall()` in every arm; only the corpus changed, passed through its `docs` parameter. Region markers were simulated by indexing spans of the adopter's root `CLAUDE.md`, each titled with its own bold lead. The ranker is deterministic, so each arm ran once.

| Arm | What is indexed | Docs | Top-1 /15 | Top-3 /15 | Pitfalls top-1 /9 |
|---|---|---|---|---|---|
| A | As installed | 8 | 0 | 0 | 0 |
| B0 | + region spans in root `CLAUDE.md`, SHARP_EDGES split at `###`, each rule file | 32 | 7 | 9 | 7 |
| B0-np | B0 minus the pointer sections | 29 | 8 | 9 | **8** |
| B0-rc | B0-np, erratum histories split from their rules in place | 31 | 8 | 9 | 8 |
| B1 | B0 + about 100 record entries | 137 | 7 | 10 | 5 |
| B2 | B1 + 13 machine-local notes | 150 | **10** | **13** | 5 |

What the table shows:
- **Location does not matter to the ranker; composition and chunk boundaries do.** Indexing in place, with no byte moved, took pitfalls from 0/9 to 7/9.
- **Pointer sections hurt once real entries are indexed.** Removing them fixed one more question.
- **Records flood judgment.** Adding the records won two conclusion questions and cost two pitfalls (7 → 5). That is the same reason the harness keeps its round log out of default search. Records need their own scope (for example `/recall --records`).
- **Boundaries matter, but not monotonically.** Splitting errata from their rules fixed one question and demoted another.
- **Machine-local notes help only on their own machine.** B2's gain came from notes outside git.

Limits:
- The experimenter wrote the questions, phrased like the rules, which favours in-place text.
- `recall()` alone was measured, not the two-ranker `/recall` front door.
- A one-question difference is noise.

**Markers (untested design).**

- **Document marker:** "index this whole file, split by this rule, in this scope". It is a header line such as `<!-- recall:doc split="### " scope=records -->`, or a registry entry for files that should not be edited (append-only records, generated files, notes outside the repo). Lint: the split rule matches something.
- **Region marker:** "index this span as one entry". In Markdown it is an opening comment `<!-- recall: <id> ; <title> ; aliases: ... -->` closed by `<!-- /recall -->`, and in code `# recall:` … `# /recall`. Lint: balanced pairs, unique ids, no nesting, not inside a code fence, not double-indexed inside a document-marked file.

Titles and aliases on markers generalise the aliases sidecar the harness already supports for principles. Named in-file regions exist elsewhere (mdBook `ANCHOR:`, editor `#region` folds, Sphinx `literalinclude` start-after/end-before); using them as search units is the new part.

**Doctor line (untested).** `recall corpus: N documents, M adopter-authored`. On the adopter at install it would have read `8 / 0`.

### Wave C — temporary recall markers [untested; feasibility read on `main`]

Markers with a limited lifetime, **stored outside the files** in the harness state folder. Each records file, anchor (a heading or quoted text, plus a content hash), title, aliases, reason, author and expiry. They are merged into search as their own tier and labelled "temporary, marked at T because R". They never displace curated entries.

| Lifetime | Expires via | Value |
|---|---|---|
| One search | Passed with the query | A filter |
| Session | Session-start sweep | High: survives compaction, and subagents can find what the parent relied on |
| Days | Checked at index load | High: a searchable working set across sessions |

**Promotion loop.** Log every hit. A temporary marker that keeps being used is evidence the text deserves a curated entry, so "curate where needed" becomes a decision made on usage data.

Feasibility on `main`:
- `recall()` takes a caller-supplied `docs` list, and the corpus is assembled in one function (`_load_corpus`).
- Session start already clears per-session state, and a gitignored state folder exists.

The change is in the protected hook layer.

### Wave D — temporary rules [probed against Claude Code]

Claude Code loads `.claude/rules/**/*.md`. A rule with `paths:` loads when Claude reads a matching file, and one without `paths:` loads at launch. Mid-session behaviour is undocumented, so it was probed. Each probe rule carried a random token that appeared in no prompt, and an existing path-scoped rule served as the positive control.

| Rule created mid-session | Main session | Subagent spawned afterwards |
|---|---|---|
| Path-scoped, in a `temp/` subfolder | Loaded on the next matching read | Loaded on the matching read (its report quoted the token) |
| `paths: ["**/*"]` | Loaded on the next read of any file | Not tested |
| No `paths:` | Never appeared in about 8 tool rounds | Not in its starting context (its own report) |

Constraints that follow:
1. **Path-scoped only.** A session-wide temporary rule uses `paths: ["**/*"]`.
2. **They bind subagents** (path-scoped ones, at least).
3. **They cannot be revoked mid-session.** Delivered text stays in context until compaction; deleting the file only stops future loads. Each rule carries its own expiry in its text, backed by file deletion.
4. **They fire on Read only.** A file changed only by a script never triggers its rule. Rules are guidance; hard enforcement needs hooks.
5. **Add-only.** A temporary rule may add a restriction or a method, never loosen a gate. Loosening goes to the operator out of band.
6. **Kept in a gitignored subfolder** and excluded from any inventory that counts rules.

Open:
- Does a subagent ever load an unconditional rule, or is the rule set fixed at the main session's launch?
- The probe subagent reported seeing the auto-memory index at startup. That is self-report only and worth a direct test, because it decides whether "private" notes are private from subagents.

### Wave E — the observer, the only writer of temporary things [untested; precedent on `main`]

1. **Propose.** The working session writes a structured proposal: kind (marker or rule), file and span, title, reason, lifetime.
2. **Review.** An observer agent in fresh context, **default reject**. It sees the proposal, the source text and the curated entries, but not the working session's reasoning. It checks that the span says what the title claims, that it neither duplicates nor contradicts a curated entry, that the lifetime is sane, and that a rule only adds.
3. **Write by hook.** Only approved entries are written, by the hook that fires when the observer finishes. Precedent on `main`: `subagent_stop.py` is the only hook that sees `agent_type`, and it is the only writer of the stop gate's relief flags (`_hook_utils.RELIEF_FLAGS`). With the store in a protected folder, the working session can propose but not write: friction, not a sandbox.
4. **Expire, log, promote** through the session-start sweep and the handoff.

**Cost and impartiality.**
- Review markers in batches at natural checkpoints (before compaction, before dispatching subagents, at handoff). Temporary *rules* always get a full review.
- Impartiality is a hypothesis: fresh context removes accumulated salience, but it is the same model and the proposal frames the question. Measure it by planting bad proposals (misleading titles, stale spans, duplicates, rules that quietly loosen a gate) among good ones, with the pass threshold fixed in advance.

### Guards

- **A byte budget for the adopter's root `CLAUDE.md`,** reported by the doctor, instead of a line cap. A line cap cannot see a 3 KB line.
- **One `## ` per catalog entry** in seeded catalogs, because the loader's split is the recall unit.
- **Pointer sections are kept out of the index,** or carry a marker that excludes them.

## Affected symbols

### Changed-semantics
- (none -- each wave's child pack declares its own)

## Reach

No class is claimed. Each child pack declares its own reach.

## Pass criteria

Withheld for the waves (Kind: ROADMAP). This pack is done when two things are true:
- Task 0's table is recorded in its Landing.
- Every wave has either a child pack or a recorded decision not to build it.

## Files touched

- New: `task-packs/TP-466-migrate-an-adopters-memory-at-setup.md` (this file).
- Modified: `task-packs/FORWARD_LEDGER.md` (one §3 row naming this pack).
- Children declare their own files.

## Sub-task ordering

1. **Task 0** on `main`. Checkpoint: the held/refuted table.
2. **Wave B** first. It is the only measured wave, and the doctor line plus pointer exclusion are small. Checkpoint: a harness-side fixture eval with generic questions, before and after.
3. **Wave A**, after B, so the migration step has somewhere findable to put things. Checkpoint: one adopter dry run with the before/after eval.
4. **Wave D**, which is independent of B/C and mostly documentation plus a gitignored folder convention.
5. **Wave C**, after B, since it shares the corpus assembly.
6. **Wave E**, last; it gates C and D writes. Checkpoint: the planted-proposal catch rate.

## Estimated effort

- Task 0: half a day.
- Wave B: 2–3 days, including the fixture eval.
- Wave A: 2 days.
- Wave D: 1 day.
- Wave C: 2–3 days.
- Wave E: 3 days, including the catch-rate measurement.
- Each wave: one red-team pass (both reviewers).
- Total: about 2.5 weeks of lane time if every wave is built. These are estimates, not measurements.

## Landing
- State: ROADMAP
- Commits:
- Suite: n/a (authoring only; the contract tier ran at authoring)
- Earn-the-red: n/a (no code)
- Red-team: none yet (the child TP-466b ran its own two-lane red-team)
- Reach: n/a; Wave B landed in TP-466b:
  Wave B (measured half) landed 2026-10-08 in `task-packs/TP-466b-index-adopter-knowledge-in-place.md` (the lane commit is named in ESPALIER_MEMORY.md's row): `/recall` indexes the adopter's root `CLAUDE.md` per `## ` section and every `.claude/rules/**/*.md` with no configuration, plus `recall_sources` documents and `recall_records` logs (the latter only under `/recall --records`); the in-file skip marker `<!-- recall: skip -->` (one of the two Guards this pack named) ships, fence-aware and any-case; the doctor line for the recall corpus (the other) ships, naming what is reached, what was ignored and which generated sections still carry init's headings unmarked. Not taken here, still this pack's: the root-CLAUDE byte budget and the one-`## `-per-entry seed rule (Risk 1 of the child did not reproduce in two red-team arms, so the budget is not yet measured as needed), region markers, the `###` split option, Waves A, C, D and E.
- Date: 2026-10-02 (authored); Wave B 2026-10-08
