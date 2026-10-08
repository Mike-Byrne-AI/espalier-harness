# TP-466b — Recall indexes the adopter's own knowledge where it lives

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: one protected hook (`tools/cc/hooks/_recall.py`, synced to its vendor mirror),
  one engine model field pair and one doctor line, one shipped command body
  (`.claude/commands/recall.md`, synced to its two mirrors), one seeded reference doc
  (`docs/HOOKS.md`, synced to its asset mirror), the example config (regenerated, never
  hand-edited), tests, and one self-host script's trigger list (`scripts/check_handoff_landing.py`).
- **Kind: PACK.** Task 0 can end it, or end one sub-task (the records scope, 1-C, has its own
  stop condition in 0-C).
- **Wave B child of `task-packs/TP-466-migrate-an-adopters-memory-at-setup.md`.** TP-466 stays
  ROADMAP: Waves A, C, D and E are untouched and its §3 row stays open. Of TP-466's *Guards*
  this pack takes two -- **pointer sections kept out of the index** (an in-file marker, 1-B) and
  **the doctor line for the recall corpus** (1-D). It does not take the root-CLAUDE byte budget
  (a banner/doctor surface with no recall mechanism in it) or the one-`## `-per-entry seed rule
  (an `init` seed concern).
- TP-466's Scope (out) stands here verbatim: records stay where they are (indexed, never moved);
  the field-trial adopter's eval questions never ship (2-C's fixture is generic and
  harness-authored); the `docs/MEMORY_SYSTEMS.md` sorting rule for *new* facts is not reopened.
- Ledger: the unit of work for `DEF-1087` (§C73). The other §C73 members are placed under
  *Reach*; two belong to sibling packs drafted today (Scope (out)).
- Gate: **operator decision pending** on D1–D4 (*Decisions*).
- Authored 2026-10-07 at `febfcd4e` on the Air (`python3` only). Every measured sentence names
  its command; the arm scripts live in the author's scratch directory and are described in Task 0
  closely enough to re-type.

## Motivation

`tools/cc/hooks/_recall.py::_iter_corpus` is the one generator behind `indexed_sources`,
`_load_corpus` and `_load_full_corpus`, and it enumerates its sources by literal Espalier path
(`memory/*.md`, `docs/SHARP_EDGES.md` sections, `docs/sharp-edges/*.md`,
`docs/STANDING_PRINCIPLES.md` sections, two self-host-gated tiers). It never reads
`espalier.toml`; `espalier/models.py::HarnessConfig` has no recall field. An adopter's root
CLAUDE.md, their `.claude/rules/*.md`, their own docs and their decision logs are never indexed,
and `/recall` answers their questions with whichever seed note is lexically nearest.

**Measured at authoring (2026-10-07; Task 0-A's command)** on a fresh adopter fixture -- a
Python tree whose root CLAUDE.md has a `## Pitfalls` section, two `.claude/rules/*.md`, a
`docs/GOTCHAS.md` with one pointer section and one three-entry section, an append-only
`docs/decisions/LOG.md` -- after `python3 -m espalier init .`:

- `indexed_sources(root)` → `['memory/', 'docs/sharp-edges/']`; `_load_corpus(root)` → **4
  documents, 0 adopter-authored**.
- The deployed CLI on four generic questions answerable only from the adopter's files: **0 of 4**
  reach an adopter source; `memory/convergence-review-protocol.md` is slot 1 for three.
- Same ranker, corpus swapped for the adopter's own text split at `## `: **4 of 4 top-1** in
  every arm that includes the root CLAUDE.md; 3 of 4 without it.

That is today's rehearsal on a Node tree (`fresh-init/REPORT.md` §5; `logs/05-*`: every question
returned the convergence protocol or nothing) and TP-466's field trial (0 of 15; in place 0/9 → 8/9
on pitfalls) reproduced on `main` with a harness-authored fixture.

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16): the adopter who wrote their pitfalls down --
in the file loaded every turn, in a path-scoped rule that loads only on a matching read, or in a
doc nothing loads -- and runs `/recall` for one of them after a compaction or from a subagent, and
is handed a seed note. Also the maintainer: `tools/cc/reflect_protocol.py`'s fold-here hint
(`nearest_by_title` over the same corpus) can only propose folding an adopter's insight into a seed.

## Scope (in)

1. **1-A** Two flat `espalier.toml` keys read by the hook, `recall_sources` and `recall_records`
   (root-relative path or last-component glob, `.md`), plus a **default roster** read with no
   configuration: the repo's root CLAUDE file split at `## `, and every markdown file under
   `.claude/rules/`. Gated on existence only, like the standing-principles tier.
2. **1-B** The new tiers yielded by `_iter_corpus` under their own families; a whole-file fallback
   for a file with no `## ` section; an in-file skip marker (`<!-- recall: skip -->`) honoured on
   every sectioned source, which keeps a pointer section out of the index.
3. **1-C** A records scope: `recall_records` entries are indexed under `declared records` and
   left out of the default ranking; `python tools/cc/hooks/_recall.py --records <topic>` reaches them.
4. **1-D** `--facts` on the CLI shim (a JSON corpus summary) and a doctor `info` line read from it
   through a bounded child process, as `espalier/doctor.py::_probe_deployed_stop_gate` reads the stop gate.
5. **2-A** `espalier/models.py::HarnessConfig` gains the two fields so
   `espalier/config.py::load_config` does not report them unknown; `examples/espalier.toml` is
   regenerated through `python3 -m espalier render-template toml` (the subject `TP-472` 2-B adds),
   never hand-edited; `tests/test_config_fields_consumed.py::CONSUMERS` names the hook as witness.
6. **2-B** Bodies and docs: `.claude/commands/recall.md`, `docs/HOOKS.md`,
   `docs/MEMORY_SYSTEMS.md`, `memory/recall-engine-extension.md`; and
   `scripts/check_handoff_landing.py::CONDITIONAL` gains the new corpus roots as triggers.
7. **2-C** Tests in the existing modules `tests/test_recall.py`, `tests/test_doctor.py` and
   `tests/test_config_fields_consumed.py` (no new test file, so the conftest owes no
   `_MARKER_RULES` row and no `_SLOW_FILES` entry): the generic adopter-knowledge fixture and its
   four questions, one test per fix, the doctor line, the config fields.
   `tests/test_recall_pasted_counts.py` gains nothing: its corpus-root test is derived and goes red
   on its own until 2-B's triggers land.
8. **3-A** One sync per mirror row touched (`espalier/mirror_registry.py::MIRROR_ROWS`):
   `python3 scripts/sync_vendor_cc.py` (`vendor-cc`), `python3 scripts/sync_claude_mirrors.py`
   (`claude-asset`, `claude-dogfooding`), `python3 scripts/sync_asset_docs.py` (`asset-docs`).
9. **4-A** Red-team (budgeted; see Risks).

The files these touch, for the scope walk:

- `tools/cc/hooks/_recall.py` and its mirror `espalier/_vendor/cc/hooks/_recall.py` (by sync)
- `espalier/models.py`, `espalier/doctor.py`, `examples/espalier.toml`
- `.claude/commands/recall.md` and its mirrors `espalier/assets/claude/commands/recall.md`,
  `examples/dogfooding/.claude/commands/recall.md` (by sync)
- `docs/HOOKS.md` and its mirror `espalier/assets/docs/HOOKS.md` (by sync);
  `docs/MEMORY_SYSTEMS.md` and `memory/recall-engine-extension.md` (no mirror row)
- `scripts/check_handoff_landing.py`
- `tests/test_recall.py`, `tests/test_doctor.py`, `tests/test_config_fields_consumed.py` (none in
  the `selfcheck-tests` row's `BYTE_MIRRORED`, so no fourth sync)

## Scope (out)

- **`DEF-1088`** (init deriving zones and actions from the adopter's CLAUDE.md): the plan guard's first-session pack (landed 2026-10-08)'s. Its
  2-B makes `init` write `espalier.toml` from `espalier/cli.py::_build_espalier_toml`, which renders
  every `HarnessConfig` field as a commented key -- this pack's two included; its every-field pin
  names them -- and pins `examples/espalier.toml` as that render's snapshot. The roster needs no
  file, so this pack's mechanism does not depend on it; the example does (2-A, Risk 8).
- **`DEF-1090`** (the banner's `if self_host:` gate on the standing-principles index): `TP-470`'s,
  which names `DEF-1087` as "the recall-corpus pack's unit" -- this pack. Not a corpus change.
- **`DEF-1085`** (seeds beside the adopter's docs with no provenance): the seeded notes stay
  indexed under their plain families. A rank penalty needs a seed-stamp reader the hook layer does
  not have (the row says so); 1-D's line says "from your own files" and prints no seeded count.
- **`DEF-1086`, `DEF-1089`**: an intake stage and the memory-sort tool's deployment are Wave A's.
- **`DEF-1091`** (telemetry opt-in; shipping the eval): not shipped. `scripts/recall_eval.py`
  stays the harness's instrument; this pack *uses* it with `--root <fixture>` as an oracle.
- **Region markers** (`<!-- recall: <id> ; <title> -->` … `<!-- /recall -->`, Wave B's untested
  design): not built. The field trial's gain came from `## `-level spans, which the splitter
  already produces. Only the *skip* marker ships.
- **A `###` split option, or any per-entry option.** The keys are flat string lists so both reader
  arms of `tools/cc/hooks/_hook_utils.py::read_toml_string_list` read them (a hook interpreter
  below 3.11 without `tomli` has only the regex arm, which reads no table). Measure demand first.
- **Folder CLAUDE files by walk.** A recursive walk needs dependency-dir pruning on every
  `/recall` and every SessionStart (`indexed_sources` walks the corpus for the banner: 43–56 ms
  over three runs on self-host, 2026-10-07, by
  `python3 -c "import sys,time;sys.path.insert(0,'tools/cc/hooks');import _recall;from pathlib import Path;t=time.perf_counter();_recall.indexed_sources(Path('.'));print(round((time.perf_counter()-t)*1000))"`).
  Declare one: `recall_sources = ["tests/CLAUDE.md"]`; `**` is refused and said.
- **Indexing seeded reference docs** (`docs/HOOKS.md` and siblings). The rehearsal's "why does the
  plan guard block my edit" has its answer there and `/recall` cannot reach it (`fresh-init/REPORT.md`
  §5). Indexing 20 KB of harness prose on every adopter tree would crowd the adopter's own docs;
  `DEF-1189`, its own decision.
- **Waves A, C, D, E of TP-466**, the byte budget, the one-`## ` seed rule: TP-466's.
- **Any edit to the tests conftest.** No new test module (2-C), so it owes no `_MARKER_RULES` row
  and no `_SLOW_FILES` entry; the other machine's claim on it was released 2026-10-07, so the
  reason is the absent module, not the claim.

## Task 0 — Verify (may end this pack, or 1-C)

Re-run at execution. The authoring run is the table below; the arm scripts were
`pack-TP-466b/{build_fixture,inplace_arms,selfhost_effect,selfhost_checks,records_arm}.py` in the
author's scratchpad.

### 0-A The fixture (the premise)

- **Oracle.** Build the fixture (2-C's helper is its text), `git init` and commit, strip every
  `ESPALIER_*` variable, `python3 -m espalier init .`; then from the fixture root
  `python3 -c "import sys;sys.path.insert(0,'tools/cc/hooks');import _recall;from pathlib import Path;r=Path('.');print(_recall.indexed_sources(r));print([d.source for d in _recall._load_corpus(r)])"`;
  then `python3 tools/cc/hooks/_recall.py "<q>"` for 2-C's four questions.
- **Refuting result.** An adopter-authored source is already in the list, or a question already
  returns its adopter source: `main` indexes in place and the pack is SCRAPPED with the list.
  Second refutation: the swapped-corpus arm (adopter `## ` spans, ranker unchanged) does not reach
  3 of 4 top-1, or `qzxv flurble wompt zzyzx` returns a hit on it: free prose is untenable under
  the half-corpus floor; re-raise with the table.
- **Exit.** Stop and re-raise.

### 0-B The self-host side-effect of the default roster

- **Oracle.** Load the live corpus, add the self-host root CLAUDE file's `## ` sections as one
  tier, run `scripts/recall_eval.py::evaluate` on both; re-count `tests/test_recall.py`'s pinned
  arms (`_MUST_ANSWER` silenced, `_MUST_RANK` wrong, `_OFF_TOPIC_ENGLISH` leaks, distinct winners)
  under both.
- **Refuting result.** Any `_MUST_RANK` winner changes, any `_MUST_ANSWER` query is silenced, the
  leak count moves, or the heading arm's `union_at_1` drops by more than the queries the tier adds.
  Then the roster is opt-in (`recall_sources = ["CLAUDE.md", ".claude/rules/*.md"]`), not default-on; D1 is answered.
- **Exit.** 1-A re-scoped; the pack continues.

### 0-C Records at scale (1-C's stop condition)

- **Oracle.** On the fixture's swapped corpus add N synthetic decision-log sections built from the
  fixture's own vocabulary, N in {25, 100, 300}, in the default ranking; re-run the four questions.
- **Refuting result.** No question loses top-1 at any N: 1-C has no harness-side evidence and is
  dropped (the key stays unknown; TP-466's two-pitfalls-at-~100-records figure is recorded as the
  only evidence, not reproduced).
- **Exit.** 1-C removed and said in Landing.

### 0-D The restating sites

- **Oracle.** `grep -nE 'memory/|docs/sharp-edges/|STANDING_PRINCIPLES' scripts/check_handoff_landing.py tests/test_recall_pasted_counts.py tests/test_recall.py tests/test_session_banner.py docs/HOOKS.md .claude/commands/recall.md memory/recall-engine-extension.md`.
- **Refuting result.** A restating site *Files touched* does not list: add it before 1-B. Derived
  sites (`indexed_sources`, the banner bullet) need nothing.

### Task 0 at authoring (2026-10-07, `febfcd4e`, Air)

| Arm | Result | Verdict |
|---|---|---|
| 0-A corpus | `['memory/', 'docs/sharp-edges/']`; 4 docs; 0 adopter-authored; `is_self_host_repo` False | **holds** |
| 0-A CLI | 0 of 4 reach an adopter source; the convergence protocol is slot 1 for 3 | **holds** |
| 0-A swapped | 11 docs: **4/4 top-1**, 4/4 in union top-4; gibberish `[]`; without the root CLAUDE tier 3/4 | **build** |
| 0-A pointer | the pointer section sits at slot 3 for one question and wins a pointer-shaped query | marker, not a heuristic |
| 0-B eval | 320 → 334 docs; heading `union_at_1` 263/312 → 266/317 (+4 own-heading hits, **one** existing hit lost: `redos budget receipt` → `CLAUDE.md :: Build & Test`, which names `test_redos.py`); stripped 227/276 → 228/278; paraphrase 6/16 and 9/16 unchanged; task 1/72 and 6/72 unchanged | **default-on survives** |
| 0-B pins | `_MUST_RANK` wrong 0 → 0; `_MUST_ANSWER` silenced 0 → 0; off-topic 29/29 → 29/29; distinct winners 19 → 19 (pin 20, band ±1); "expected doc loses to a larger doc" 0 → 0; heading agreement 230/312 → 233/317 (0.737 → 0.735; the body pastes 232/309, inside `tests/_recall_pins.py::BAND`) | **unchanged** |
| 0-B own headings | 1 of the 5 title-queryable sections misses its own heading: `Hooks (Mechanical Enforcement)` (vocab 500) loses to `Priority Order`, whose body says "Mechanical enforcement (hooks)" | breadth, recorded |
| 0-C records | 25 and 100 synthetic records: 4/4; **300: 3/4** (`.claude/rules/testing.md` to slot 2 behind the seed note) | **1-C stays**; evidence synthetic + field |
| 0-D | restating sites: `scripts/check_handoff_landing.py` (triggers), `memory/recall-engine-extension.md` (prose list), `.claude/commands/recall.md` (the "Each is a…" sentence); `docs/HOOKS.md` derived | all in *Files touched* |

## Relevant memory

Recent pattern: the recall engine's history is a run of fixes refuted by measurement -- nine
suppression mechanisms with negative margins, a calibration swept on a corpus forty documents
stale, a count band breached by one memory note. Every ranker claim in this pack was re-run on
the live corpus today; the one this pack adds (a new tier moves nothing pinned) is the one the
red-team should try first, with a large table-shaped section.

| Entry | Where |
|---|---|
| Recall-engine extension gotchas | `memory/recall-engine-extension.md` |
| The recall corpus must gate harness-internal entries for adopters | `docs/SHARP_EDGES.md :: The recall corpus must gate harness-internal entries for adopters` |
| A memory note can be too long to be recalled | `memory/a-memory-note-can-be-too-long-to-be-recalled.md` |
| Recall keys on the hazard, not the task | `memory/recall-keys-on-the-hazard-not-the-task.md` |
| Fix the surface the reader consumes, not the one the fact is authored on | `memory/fix-the-surface-the-reader-consumes.md` |
| A hand-written count that moves on ordinary growth is tax | `memory/a-hand-written-count-that-moves-on-ordinary-growth-is-tax.md` |

Resolved 2026-10-07 by `python3 tools/cc/hooks/_recall.py "<topic>"` with `recall corpus adopter
own knowledge indexed where it lives`, `a memory note can be too long to be recalled`, `pointer
section index search corpus`, `recall keys on the hazard not the task`, `calibration table pasted
count band corpus growth`. Re-run rather than trust this list.

Folders touched, so the folder-CLAUDE ladder fires: `tools/cc/hooks/` (protected zone:
maintenance mode or the approval marker in the PR title; `tests/test_hook_helper_consolidation.py`
forbids a local TOML reader -- route through `_hook_utils`), `.claude/commands/` (sync after),
`docs/` (the `asset-docs` mirror row; sync after), `espalier/_vendor/` and `espalier/assets/`
(never hand-edited).

## Implementation

Every fix is labelled. "Driven" means Task 0 ran the behaviour with the corpus swapped; the code
is untested until 2-C's red is earned.

### 1-A The keys and the roster — `tools/cc/hooks/_recall.py` *(fix shape, driven; untested as code)*

```python target=tools/cc/hooks/_recall.py
#: The two flat espalier.toml keys an adopter declares recall sources with, and
#: the family each yields under. Flat string lists on purpose: both reader arms
#: of _hook_utils.read_toml_string_list read them (the regex arm reads no table).
RECALL_SOURCE_KEYS: tuple[tuple[str, str], ...] = (
    ("recall_sources", "declared documents"),
    ("recall_records", "declared records"),
)
#: A section whose body carries this comment is not indexed (a pointer section).
RECALL_SKIP_MARKER = "<!-- recall: skip -->"


def _declared_sources(root: Path) -> list[tuple[Path, str]]:
    """``(file, family)`` for every file the two keys resolve to. An entry is a
    root-relative POSIX path or a glob whose only wildcard is in its last
    component; ``**``, an absolute path, ``..``, a non-``.md`` target and an
    entry matching no file are ignored and SAID once a session (``say_once``,
    hook ``recall``, event ``recall_source_ignored``). Never raises."""
    ...  # read_toml_string_list(root, key, on_error=...) per key; validate; sorted(root.glob(entry))


def _default_roster(root: Path) -> list[tuple[Path, str]]:
    """<root>/CLAUDE.md and <root>/.claude/rules/**/*.md when present --
    existence is the only gate, as for docs/STANDING_PRINCIPLES.md."""
    ...
```

Refutation: if `read_toml_string_list` cannot return a flat list on the regex arm
(`tests/test_hook_utils.py` pins both arms), the keys need a table and Scope (out)'s portability
reason is wrong -- re-raise.

### 1-B The yields, the fallback, the skip marker *(fix shape, driven)*

One helper for every sectioned source, called for the roster and the declared documents **before**
the `memory/` loop in `_iter_corpus` (the adopter's own text leads `indexed_sources`, so the
banner's bullet names it first):

```python target=tools/cc/hooks/_recall.py
def _yield_sections(rel: str, text: str, family: str) -> "Iterator[_Doc]":
    """One _Doc per `## ` section (the field trial's unit); a file with no
    `## ` heading is one _Doc under its first `# ` heading or stem. A section
    whose body carries RECALL_SKIP_MARKER is not yielded."""
    sections = iter_doc_sections(text)
    if not sections:
        yield _Doc(rel, _first_heading(text) or Path(rel).stem,
                   Counter(_tokenize(text)), family=family)
        return
    for title, body in sections:
        if RECALL_SKIP_MARKER in body:
            continue
        yield _Doc(f"{rel} :: {title}", title,
                   Counter(_tokenize(f"{title} {body}")), family=family)
```

The marker check is also added to the `docs/SHARP_EDGES.md` and `docs/STANDING_PRINCIPLES.md`
loops. Families: `CLAUDE.md sections`, `.claude/rules/`, `declared documents`, `declared records`.
Refutation: `tests/test_recall.py::test_every_corpus_doc_names_its_family` asserts
`indexed_sources` equals the corpus's family order, so either yield order passes -- the order is a
choice this pack records, not a fact a test fixes.

### 1-C The records scope *(fix shape, driven at 300 synthetic records; 0-C)*

`_iter_corpus(root, *, exclude=None, records=False)` yields `declared records` only when
`records=True`. `_load_corpus(root, *, records=False)` and `recall_union` thread the flag through
to the single-answer ranker; `_load_full_corpus` keeps `records=False` (the fold-here hint should
not propose folding an insight into an append-only log). The CLI shim strips a leading `--records`
from argv and sets the flag. `indexed_sources` reads the default scope, so the banner never names
a family `/recall` does not search by default.

### 1-D `--facts` and the doctor line *(fix shape, untested)*

The shim, when `sys.argv[1:] == ["--facts"]`, prints one JSON line
`{"docs": N, "families": {family: count}, "own": M, "records": R}` (`corpus_summary(root)`, a
module function tests call directly; `own` counts the four adopter families). Doctor:

```python target=espalier/doctor.py
def _probe_recall_corpus(repo_root: Path) -> dict | None:
    """The deployed _recall.py's own corpus summary, asked in a child process
    with CLAUDE_PROJECT_DIR set to the root (the shim resolves its root through
    resolve_project_root) -- never imported, the isolation rule, exactly as
    _probe_deployed_stop_gate does. None when the hook is absent, will not
    start, or does not answer in 20 s; the last stdout line is the JSON."""
    ...
```

In `run_doctor_check`, beside the stop-gate posture lines (an entry in the `info` list, never a
`checks` key: `tests/test_troubleshooting_enumerations.py::_doctor_check_names` derives that roster
and a new key would owe a `docs/TROUBLESHOOTING.md` entry), an `info` line: `recall corpus: N
documents, M from your own files (<families>); R records (reach them with /recall --records)`;
when `M == 0`, add the hint `declare your docs with recall_sources in espalier.toml; a root
CLAUDE.md with ## sections and .claude/rules/*.md are indexed without configuration`. No seeded
count is printed
(`DEF-1085`). Refutation: if the probe cannot answer on the fixture, the line reads `recall corpus:
not readable (<reason>)`, never silence; if `harness_repo`-shaped fixtures carry no deployed
`_recall.py`, the test seeds `_recall.py` and `_hook_utils.py` from the SoT first.

### 2-A Model fields, example, consumer map *(fix shape, untested)*

```python target=espalier/models.py
    # The adopter's recall sources, read live by tools/cc/hooks/_recall.py
    # (RECALL_SOURCE_KEYS); mirrored here so load_config does not read the
    # keys as typos. Flat lists of root-relative paths or last-component globs.
    recall_sources: list[str] = field(default_factory=list)
    recall_records: list[str] = field(default_factory=list)
```

`examples/espalier.toml` is **regenerated, never hand-edited** (the coordinator's cross-pack
decision, 2026-10-07): `TP-472` 2-B's `espalier/cli.py::_build_espalier_toml` renders every
`HarnessConfig` field as a commented key with a one-line sentence and pins the example as the
render's snapshot (`tests/test_documented_claims.py::TestDeployTemplateSnapshots`), so this sub-task
supplies the two keys' sentences (both keys, the roster, the skip marker) where that renderer keeps
each field's line, then runs `python3 -m espalier render-template toml` into the example. Order:
if `TP-472` 2-B has landed, regenerate here; if not, add the fields and leave the example alone --
`TP-472`'s first render carries them (its every-field pin names this pack's two fields) and no test
on `main` today reads the example (`grep -rn 'examples/espalier.toml' tests/` hits one docstring,
`tests/test_doctor.py`, on the unknown-key promise). `tests/test_config_fields_consumed.py::CONSUMERS`
maps both fields to `tools/cc/hooks/_recall.py::RECALL_SOURCE_KEYS` (its mutation: rename a key
inside the tuple).

### 2-B Bodies, docs, the handoff gate *(prose; one trigger list)*

- `.claude/commands/recall.md`: the "Each is a `memory/` protocol…" sentence (frontmatter and
  body) gains "a section of this repo's root CLAUDE.md, a `.claude/rules/` file, or a document
  declared under `recall_sources`", plus one sentence for `--records`. The shape sentences pinned by
  `tests/test_recall_eval.py::TestTheDeliveredShapeIsStatedAtEverySourceOfTruth` and the agreement
  figure `tests/_recall_pins.py::BODY_AGREEMENT_RE` reads stay as they are.
- `docs/HOOKS.md`: one clause on the derived-bullet paragraph naming the roster.
- `docs/MEMORY_SYSTEMS.md`: one paragraph after *The sorting rule*: pull-side indexing of
  knowledge that stays in place; the two keys; the rule for new facts unchanged.
- `memory/recall-engine-extension.md`: its hand-listed families become a pointer at
  `indexed_sources` (the in-lane hygiene item (no row; 2-B closes it)).
- `scripts/check_handoff_landing.py::CONDITIONAL`: the pasted-counts entry's triggers gain
  `CLAUDE.md` and `.claude/rules/`;
  `tests/test_recall_pasted_counts.py::test_the_handoff_gate_watches_every_corpus_root` reds until
  they do (derived from the live corpus, which the self-host root CLAUDE file now joins).

### 2-C Tests and the generic fixture *(each names its mutation)*

A helper in `tests/test_recall.py`, `_adopter_knowledge_tree(tmp_path)`, writes the Task 0
fixture: a root CLAUDE file with `## Mission` / `## Pitfalls` / `## Commands`;
`.claude/rules/api-contracts.md` and `.claude/rules/testing.md` with `paths:` frontmatter;
`docs/GOTCHAS.md` with `## Where things live` (carrying the skip marker) and `## Database and
migrations`; `docs/decisions/LOG.md` with three `## DEC-…` sections; an `espalier.toml` declaring
both keys. `_ADOPTER_QUESTIONS` is four `(query, expected source)` rows:

| query | expected |
|---|---|
| `integration tests skipped silently without the test database env var` | `.claude/rules/testing.md` |
| `run the migrator with reset against the shared staging database` | `CLAUDE.md :: Pitfalls` |
| `alembic autogenerate misses enum value changes empty revision` | `docs/GOTCHAS.md :: Database and migrations` |
| `hand-edit a generated client file after a schema change` | `.claude/rules/api-contracts.md` |

Tests, with the mutation each dies to:

- `test_the_adopter_fixture_answers_its_four_questions`: `recall_union` slot 0 is the expected
  source for all four -- **red** with `_default_roster` and `_declared_sources` monkeypatched to
  `[]` (the reconstructed pre-fix state; measured 0 of 4).
- `test_declared_documents_are_indexed_and_named` -- red when the `recall_sources` read is dropped.
- `test_root_claude_md_and_rules_need_no_configuration` -- red when the roster is removed.
- `test_a_skip_marked_section_is_not_yielded` (also on `docs/SHARP_EDGES.md`) -- red when the
  marker check is deleted.
- `test_a_file_with_no_h2_is_indexed_whole` -- red when the fallback branch is removed.
- `test_records_are_out_of_the_default_ranking_and_in_the_records_scope` -- red when the tier is
  yielded unconditionally.
- `test_a_bad_entry_is_ignored_and_said` (absolute, `..`, `**`, no match, not `.md`) -- red when
  validation is skipped; asserts the `say_once` audit record.
- `test_indexed_sources_follows_the_corpus_gates` gains a root-CLAUDE step.
- No new live test: `test_must_rank_arm_returns_the_right_document`,
  `test_must_answer_arm_is_never_suppressed`, `test_off_topic_english_leak_count_does_not_grow`,
  `test_must_answer_winners_do_not_collapse`, `tests/test_recall_calibration.py::TestRetrievalQuality`
  and `test_live_corpus_suppresses_pure_nonsense` run with the roster on. 0-B says they hold;
  execution proves it.
- `tests/test_doctor.py::test_doctor_reports_the_recall_corpus_line` on `harness_repo` with the two
  hook files seeded -- red when the probe is not called.
- Oracle, not a test: `python3 scripts/recall_eval.py --root <fixture> --misses` -- every adopter
  document with a heading query is `union_at_any`; the table goes in Landing.

### 3-A Syncs

One per mirror row this pack touches, read from `espalier/mirror_registry.py::MIRROR_ROWS`:
`python3 scripts/sync_vendor_cc.py` (`vendor-cc`: `tools/cc/hooks/_recall.py`), then
`python3 scripts/sync_claude_mirrors.py` (`claude-asset` and `claude-dogfooding`:
`.claude/commands/recall.md`), then `python3 scripts/sync_asset_docs.py` (`asset-docs`:
`docs/HOOKS.md`; `docs/MEMORY_SYSTEMS.md` and `memory/` have no row). Each script's `--check` then
passes and `git status` is clean on the mirrors; then `mypy tools/cc/hooks/` and `ruff check .`.

### 4-A Red-team (budgeted; see Risks)

`code-reviewer` and `failure-mode-reviewer` on the lane's diff in a snapshot clone, edits frozen.
Ask each for the mutation that survives 2-C and for the large table-shaped adopter section that
displaces a pinned live answer.

## Affected symbols

The single-answer ranker `recall` gains the `records` keyword, but its bare name is a generic
word: at authoring the walk drew every `/recall` prose mention tree-wide (hundreds, in blueprints
and bodies), so it is declared through `recall_union`, its one caller that threads the flag, and
the bullet below is struck from the walk.

### Changed-semantics

- `tools/cc/hooks/_recall.py::_iter_corpus` (four new tiers, the skip marker on every sectioned source, the `records` flag)
- `tools/cc/hooks/_recall.py::_load_corpus` (`records=False` keyword)
- `tools/cc/hooks/_recall.py::_load_full_corpus` (reads the new tiers; records stay out)
- `tools/cc/hooks/_recall.py::indexed_sources` (names the new families, adopter tiers first)
- `tools/cc/hooks/_recall.py::recall_union` (`records` keyword, threaded to the single-answer ranker)
- ~~`tools/cc/hooks/_recall.py::recall`~~ (declared through `recall_union`; see above)
- `espalier/models.py::HarnessConfig` (two list fields)
- `espalier/cli.py::_build_espalier_toml` (`TP-472` 2-B's renderer; the two keys' sentences, only once it has landed -- unresolved on `main` until then, Risk 8)
- `espalier/doctor.py::run_doctor_check` (one `info` line from the probe)
- `scripts/check_handoff_landing.py::CONDITIONAL` (two more triggers on the pasted-counts entry)
- `tests/test_config_fields_consumed.py::CONSUMERS` (two rows)
- `tests/test_recall.py::test_indexed_sources_follows_the_corpus_gates` (one more step)

### Renamed

- (none)

### Added-paths

- `tools/cc/hooks/_recall.py::RECALL_SOURCE_KEYS`
- `tools/cc/hooks/_recall.py::RECALL_SKIP_MARKER`
- `tools/cc/hooks/_recall.py::_declared_sources`
- `tools/cc/hooks/_recall.py::_default_roster`
- `tools/cc/hooks/_recall.py::_yield_sections`
- `tools/cc/hooks/_recall.py::corpus_summary`
- `espalier/doctor.py::_probe_recall_corpus`
- `tests/test_recall.py::_adopter_knowledge_tree`
- `tests/test_recall.py::_ADOPTER_QUESTIONS`
- `task-packs/TP-466b-index-adopter-knowledge-in-place.md`

### Removed-paths

- (none)

## Affected literals

- `recall_sources` — new flat `espalier.toml` key (zero hits today is the baseline).
  EXCLUDE: task-packs/TP-466b-index-adopter-knowledge-in-place.md
- `recall_records` — new flat `espalier.toml` key, the records scope.
  EXCLUDE: task-packs/TP-466b-index-adopter-knowledge-in-place.md

## Reach

Members derived by `grep -nE '^\| \`(DEF-108[5-9]|DEF-109[01]|TP-466)\` ' task-packs/FORWARD_LEDGER.md`
and the §C73 index (`grep -n 'C73' task-packs/FORWARD_LEDGER.md`). The row's probe
(`python3 tools/cc/check_ledger_probes.py --id DEF-1087`) is NO_ORACLE today: `cmd` is null because
the row declined to key on a guessed identifier. Not an absence proof.

| Item | Status | Evidence |
|---|---|---|
| `DEF-1087` | **CLOSED by 1-A to 1-D** if 0-A/0-B build | the fixture's 0 → 4 of 4; proposed probe (it binds this pack's key name, which is why the row has none): a temp tree with `NOTES.md` (two `## `) and `espalier.toml` `recall_sources = ["NOTES.md"]`, `any(d.source.startswith("NOTES.md") for d in _recall._load_corpus(tmp))` -- open value `False` |
| `TP-466` (§3) | **NOT CLOSED** | ROADMAP; Wave B's measured half lands here; A, C, D, E open; its Landing gains a Wave B row |
| `DEF-1088` | **NOT REACHED** | `TP-472`'s; this pack's keys are documented for it to seed |
| `DEF-1090` | **NOT REACHED** | `TP-470`'s (banner surface, not corpus) |
| `DEF-1085` | **NOT REACHED** | no seed provenance in the hook layer; the doctor line prints no seeded count |
| `DEF-1086`, `DEF-1089` | **NOT REACHED** | Wave A's |
| `DEF-1091` | **NOT REACHED** | the eval is an oracle here, not shipped; telemetry untouched |
| `DEF-1189` | **NOT REACHED** | seeded reference docs (`docs/HOOKS.md`) have no recall home on an adopter tree -- indexing 20 KB of harness prose would crowd the adopter's own docs (Scope (out)); its own decision. Probe: the filed one, `python3 tools/cc/check_ledger_probes.py --id DEF-1189`, re-declared 2026-10-07 to key on a corpus document whose `source` path ends in `docs/HOOKS.md` on an init'd tree (not on a family label) -- open value `False`; this pack's four families leave it `False` |
| the in-lane hygiene item (no row; 2-B closes it) | **CLOSED in-lane (2-B)** | `memory/recall-engine-extension.md` hand-lists the corpus families; probe `grep -c 'memory/\*.md' memory/recall-engine-extension.md` -- open value `1` |

## Pass criteria

- Task 0-A re-run prints 0 adopter-authored documents and 0 of 4 before the lane; after it,
  `indexed_sources` leads with `CLAUDE.md sections` and `.claude/rules/`, the fixture's corpus has
  at least 7 adopter documents, and the four questions are 4 of 4 at slot 0 of `recall_union`.
- `python3 scripts/recall_eval.py --root <fixture>` runs and every adopter document with a heading
  query is `union_at_any`; the table is pasted in Landing.
- Every test 2-C adds was seen red against its named mutation, recorded in Landing.
- **No live pin moves and none is loosened**: `_OFF_TOPIC_LEAK_CEILING` is not raised,
  `_MUST_RANK` rows are not retargeted onto `CLAUDE.md` sections, `_MUST_ANSWER_DISTINCT_WINNERS`
  does not move (0-B measured 19 → 19; a move refutes 0-B's "unchanged" verdict and is re-raised,
  never re-pinned to clear the red), `tests/test_recall_calibration.py::MIN_TOP1_ACCURACY` is not
  lowered. Strengthening is allowed and recorded.
- The gibberish contract holds: `qzxv flurble wompt zzyzx` → `[]` on the fixture;
  `test_live_corpus_suppresses_pure_nonsense` and `test_suppresses_near_miss_of_ubiquitous_tokens` green.
- `pytest -q -m 'not heavy_e2e' tests/test_recall.py tests/test_recall_calibration.py tests/test_recall_eval.py tests/test_recall_pasted_counts.py tests/test_session_banner.py tests/test_doctor.py tests/test_config_fields_consumed.py tests/test_hook_utils.py tests/test_hook_helper_consolidation.py`
  green; the three pasted recall counts stay inside `tests/_recall_pins.py`'s band (0-B: 334 live
  against 318 pasted; re-paste only on a breach, last in the commit).
- `python3 scripts/sync_vendor_cc.py --check`, `python3 scripts/sync_claude_mirrors.py --check` and
  `python3 scripts/sync_asset_docs.py --check` all pass and leave no diff; `mypy tools/cc/hooks/`
  and `ruff check .` clean.
- `python3 scripts/proof_tier.py --base origin/main` prints `full` (a hook changed); the tier is
  green under `nohup` with `EXIT=$?` appended.
- `espalier doctor .` on the fixture prints the `recall corpus:` line with `M >= 7`; on a tree with
  no adopter source it prints `0 from your own files` with the hint.

## Risks — what this pack most likely got wrong

1. **The roster is measured on one self-host CLAUDE file.** 0-B is flat here, but an adopter's
   root file can be one 20 KB section (the field trial's was 40% one section with a 3.3 KB bullet);
   such a section has the vocabulary to win slot 1 on breadth, as `Hooks (Mechanical Enforcement)`
   already loses its own heading. The red-team is asked for that tree. If it wins, the remedy is
   TP-466's byte budget and one-`## ` rule said by the doctor line, not a rank penalty in the hook.
2. **Flat keys may be the wrong shape.** They cannot say "split at `###`" or carry a per-entry
   option except by which key an entry sits under. If the first real adopter needs one, the keys
   become a table and the regex arm stops reading them; the pack records the trade.
3. **The records evidence is synthetic.** 0-C saw the loss at 300, not 100; the field trial saw it
   at ~100 real records. If the red-team shows the 300-record loss is a word-pool artefact, 1-C
   still ships as a cheap scope, and Landing says the two measurements disagree on magnitude.
4. **`indexed_sources` order is a choice.** `tests/test_session_banner.py::TestOrientationFootgunLineIsDerived`
   derives the bullet, so nothing reds whichever order is chosen -- and nothing checks it either.
5. **A second child process in `doctor`.** Bounded at 20 s like the stop-gate probe; on a large
   `.claude/rules/` tree the budget trips and the line says `not readable`.
6. **`nearest_by_title` now sees adopter tiers.** The fold-here hint can propose
   `CLAUDE.md :: Pitfalls`, which is the point, but `tools/cc/reflect_protocol.py` renders the
   source as a path and `<file> :: <title>` is a new shape for it. Check the render, not only the ranking.
7. **Seam: `espalier/doctor.py` with `TP-474`.** `TP-474` 2-C edits `_deployed_surface_remains` and
   `_uninstall_leftovers`, and its hook-start sub-task (`DEF-1188`) adds a FAIL line in
   `run_doctor_check`; this pack's 1-D adds `_probe_recall_corpus` and one `info` line in the same
   function. Order: `TP-474` first, this pack's `run_doctor_check` hunk rebases -- a hook that will
   not start then has its FAIL line beside this probe's `not readable`. `espalier/models.py` is
   shared the same way (`TP-474` 3-D edits `RepoFingerprint.from_dict`; this pack `HarnessConfig`):
   different classes, either order.
8. **Seam: `HarnessConfig` and `examples/espalier.toml` with `TP-472` 2-B** (the coordinator's
   decision, 2026-10-07): the example is regenerated through `render-template toml`, never
   hand-edited, and `TP-472`'s every-field pin names this pack's two fields. 2-A states both
   landing orders. What this most likely gets wrong: where the renderer keeps each field's sentence
   is `TP-472`'s to fix, so 2-A's "supplies the two keys' sentences" is a guess at a symbol that
   does not exist yet; the Changed-semantics bullet on `_build_espalier_toml` is unresolved until
   `TP-472` lands, and `scope-check` says so.

## Decisions (operator)

- **D1** Default roster on every tree vs opt-in only. Recommended: default-on (0-B: +4/−1 naming
  queries, no pinned arm moved).
- **D2** Ship the records scope now vs defer until a real log is in hand. Recommended: ship (a flag
  and a second key; the field trial measured the need).
- **D3** Pointer sections: skip marker only vs a thin-section heuristic. Recommended: marker only
  (no field pointer sections here to calibrate on).
- **D4** Family order in `indexed_sources` (and so in the banner's bullet): the adopter's tiers
  first, or appended after the seeded families. Recommended: adopter first -- the bullet is what
  tells an adopter `/recall` reaches their own text; nothing pins the order either way (Risk 4).

## Files touched

- New: `task-packs/TP-466b-index-adopter-knowledge-in-place.md`.
- Modified: `tools/cc/hooks/_recall.py` and its vendor mirror (sync); `espalier/models.py`;
  `espalier/doctor.py`; `examples/espalier.toml` (regenerated by `render-template toml` once
  `TP-472` 2-B has landed, never hand-edited); `.claude/commands/recall.md` and its two
  mirrors (sync); `docs/HOOKS.md` and its asset mirror `espalier/assets/docs/HOOKS.md` (sync);
  `docs/MEMORY_SYSTEMS.md`; `memory/recall-engine-extension.md`;
  `scripts/check_handoff_landing.py`; `tests/test_recall.py`; `tests/test_doctor.py`;
  `tests/test_config_fields_consumed.py`; at landing, `task-packs/FORWARD_LEDGER.md` (the
  `DEF-1087` strike) and `task-packs/TP-466-migrate-an-adopters-memory-at-setup.md` (one Landing row).
- Unmodified on purpose: `tools/cc/hooks/_hook_utils.py` (`iter_doc_sections`,
  `read_toml_string_list`, `say_once` used as they stand); `tools/cc/hooks/session_start.py`
  (`_orientation_footgun_line` derives the bullet); `scripts/recall_eval.py` (`--root` already
  serves the fixture); `tests/test_recall_pasted_counts.py` (its corpus-root test is derived; the
  three pasted counts it reads live in `_recall.py` and `recall.md`, re-pasted only on a band
  breach) and `tests/_recall_pins.py` (band constants); the tests conftest (no new module, 2-C;
  the claim on it was released 2026-10-07); `bench/*`, `CHANGELOG.md` (claimed elsewhere).

## Sub-task ordering

0. Pre-flight per `memory/task-packs.md`: `code-reviewer` with `tools/cc/pack_artifact_checklist.md`;
   `python3 -m espalier scope-check task-packs/TP-466b-index-adopter-knowledge-in-place.md`;
   `python3 tools/cc/sister_site_probe.py --json`;
   `python3 -m espalier surface-impact task-packs/TP-466b-index-adopter-knowledge-in-place.md`.
   Then `python3 tools/cc/execution_plan.py create …` and the mail-channel claim on `tools/cc/hooks/_recall.py`.
1. **Task 0** (0-A to 0-D). Checkpoint: the table re-derived under `reports/tp466b/`. Stop on
   0-A's refutation; re-scope 1-A on 0-B's; drop 1-C on 0-C's.
2. **2-C's fixture and four-question test first**, red (0 of 4). Checkpoint: the red recorded.
3. **1-A, 1-B.** Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_recall.py tests/test_recall_calibration.py`.
4. **1-C.** Checkpoint: the records test; `--records` by hand on the fixture.
5. **2-B's trigger list**, then **1-D** (rebased onto `TP-474`'s `run_doctor_check` if it has
   landed; Risk 7), then **2-A** (the fields; the example regeneration only after `TP-472` 2-B,
   Risk 8). Checkpoint:
   `pytest -q -m 'not heavy_e2e' tests/test_recall_pasted_counts.py tests/test_doctor.py tests/test_config_fields_consumed.py tests/test_hook_utils.py`.
6. **2-B's bodies and docs.** Checkpoint: `tests/test_recall_eval.py`, `tests/test_session_banner.py`.
7. **3-A's three syncs**, `mypy`, `ruff`. Checkpoint: each sync's `--check` passes; no mirror diff
   in `git status`.
8. **4-A red-team**, one fix batch.
9. The `full` tier under `nohup`; the ledger strike (probe seeded first); TP-466's Landing row;
   the commit (subject under 72 characters, no ledger id); `/handoff`, which ships.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 re-run | 1 h |
| 2-C fixture + red | 1.5 h |
| 1-A, 1-B | 3 h |
| 1-C | 1.5 h |
| 1-D | 2 h |
| 2-A | 1 h |
| 2-B | 1.5 h |
| 2-C remaining tests | 2 h |
| 3-A | 0.5 h |
| Red-team and fix batch | half a day |

Total about 2.5 days of lane time, inside TP-466's 2–3-day Wave B estimate. Pack budgets here have
run about 2.7 times over on the one pack measured; read this as a floor.

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: (per fix, 2-C's named mutations; the fixture test's red is the reconstructed pre-fix state)
- Red-team:
- Reach: `DEF-1087` to close; `TP-466` row stays open (Wave B of five)
- Date: 2026-10-07 (authored)
