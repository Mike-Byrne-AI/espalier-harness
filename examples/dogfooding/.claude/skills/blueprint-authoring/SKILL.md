---
name: blueprint-authoring
description: Task-pack authoring conventions. Use when composing or refining a TP-N task pack, scoping a pack to a defect class, drafting code-fix instructions, structuring scope-in vs scope-out, or naming tasks within a pack — also when the user mentions task pack format, blueprint structure, RUNBOOK, or pack execution. Encodes Espalier-Harness's blueprint-authoring discipline.
---

# Blueprint Authoring

Use when composing a task pack (TP-N) for espalier or a similar repo.
A "blueprint" here is the static design document; a "RUNBOOK" is the
ordered execution plan that pairs with it.

**What a pack is for.** A pack exists because work gets authored at one moment
and executed at another, by someone — often something — that does not carry the
authoring context. Everything below follows from that gap. A pack is not a
script to be replayed; it is a **briefing that must survive being wrong**.

## The one inversion to hold

**Be exact about how to MEASURE. Be provisional about what to WRITE.**

The reflex runs the other way: packs arrive precise about the code and vague
about the proof. That is backwards, because the code is the part the author
could not test and the proof is the part they could. A prescribed fix is a
hypothesis formed without running anything; the command that decides whether it
worked can be stated exactly, today, at zero risk.

So: spell the oracle to the flag. Offer the fix as the current best guess, and
say so in those words.

## Scope a pack to a class, not a site

Before authoring, ask whether the defect is one site of a class. If it is, the
class is the unit of work — not the site, and not a list of sites someone
noticed.

**The pack names the oracle that enumerates members. It does not carry the
roster.** A hand-written member list is a declared population: it is a snapshot
of what one reader saw on one day, it stales while the pack waits, and it reads
as authoritative precisely because it is specific. Write the *deriving command*
and let it produce the roster at execution time.

Two failure modes to write against, both observed:

- **A tracker's row count is a class's lower bound, never its census.** A class
  ledgered with two members had six in one module and a seventh in another
  producer. Enumerate *producers of the mechanism*, not tracked instances.
- **A silent probe is not an absence proof.** The repo's sister-site probe is
  name-keyed and scoped to particular trees, so a clean exit means "no clique
  under this key in this scope" — never "no class." A pack that cites a green
  probe as evidence of completeness has cited the wrong thing. Name the scope
  the oracle actually covers.

**Partial closure is a first-class outcome, not a failure.** A pack may close
part of a class and ledger the remainder, provided the remainder is named with
its reason. What is forbidden is finishing with the class *reading* shut when it
is not. If the honest end state is "four members closed, two deferred because
their writer emits five incompatible formats," that is a good pack.

## Mark every claim: measured or hypothesised

Tag load-bearing sentences at the sentence level. A pack mixes three kinds of
statement and they are indistinguishable in prose:

| Kind | Example | Owed |
|---|---|---|
| **Measured** | "driven on a synthetic tree: the candidate list came back empty" | the command, so a reader can re-run it |
| **Hypothesised** | "likely because the filter drops the prefix" | nothing — but it must be labelled |
| **Prescribed** | "add the predicate at the third reader" | an oracle that can refute it |

The failure this prevents is specific and it is not laziness: prose written
while designing a fix describes the *fix intended*, and slides into the tense of
something already established. The author has the measurement — they simply do
not re-read it before writing the sentence. Sessions here have shipped
docstrings asserting a class was closed at two sites while four existed, with
the correct census written by the same author an hour earlier.

**Before a pack is finished, re-run the oracle for each measured claim.** Not as
review — as authoring.

## Task 0 — try to kill the pack

Every pack's first sub-task is a **verify pass whose licensed outcome includes
"do not build this."**

This is not the same as checking whether the premise is stale. A premise can be
perfectly current while the prescription is inert. Both fixes queued into one
recent session had accurate, well-cited premises and prescriptions that
measurement refuted: one would have recovered nothing because a downstream
filter dropped exactly the records it restored; the other was blocked by a gate
that pinned the broken form it meant to replace. Neither was knowable from the
row. Both were knowable in twenty minutes of driving.

Task 0 states, explicitly:

- **The oracle** — the command whose output decides.
- **The refuting result** — what output means *do not build this*.
- **The exit** — what to do then. The default is **stop and re-raise**, not
  "adjust and continue." An approval was granted against a stated reason; when
  measurement falsifies the reason, the approval is gone with it.

⚠ **A verify step that can only confirm or amend will rationalise.** If Task 0
has no outcome that ends the pack, it is not a verify step, it is a warm-up.

## Prescribe the oracle; propose the fix

When a pack carries a concrete code change, keep the formatting rules under
*Code-fix output format* below — copy-ready, one fix at a time, fenced with its
target. Those rules make a fix *unambiguous*; they say nothing about whether it
is *right*.

So pair every prescribed fix with two things:

1. **A label.** "Fix shape (untested)" or "Fix (driven — see Task 0)". A pack's
   prescribed code is a claim like any other, and an unlabelled fix is read as
   settled.
2. **Its refutation.** What would show this fix is the wrong shape? Name it.
   "If the formatter cannot derive site three, the registry lacks the field and
   this fix is incomplete" is worth more than another paragraph of how-to.

A pack that says *"here is the defect, here is what might close it, here is how
to tell"* survives being wrong. A pack that says *"do exactly this"* gets
executed exactly, including when it is wrong — and unattended execution has no
one to notice.

## Relevant memory — titles and a pointer, never the prose

The pack carries three things, and **no memory body**:

1. **What has been biting lately** — two or three sentences of measured
   context, not advice. *"The last three defects found here were in the fix, not
   the original code."*
2. **The titles** of the memory and footgun entries that bear on this work, with
   their paths. Titles only.
3. **The query that resolved them**, so a reader can re-derive the list instead
   of trusting a snapshot.

```markdown
## Relevant memory

Recent pattern: every defect found in this subsystem in the last four sessions
was introduced by the repair, not present in the original code. Two were in the
test written to prove the fix.

| Entry | Where |
|---|---|
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A rotted citation's fix target is itself a claim | `docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md` |
| The measuring instrument is a claim too | `docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "<topic>"`;
re-run it rather than trusting this list if the pack has been sitting.
That command prints **up to four candidates per query**, from two rankers
deliberately calibrated differently, alternating: line one is the winner of the
ranker that favours queries that NAME a doc; line two is the winner of the ranker
that favours queries that DESCRIBE one when the two disagree, and the naming
ranker's runner-up when they agree (most title-shaped queries); then the runners-up.
Pick the one that fits the pack; do not paste more than one, and do not take the
first just because it is first.
```

**Why titles rather than a `/recall` command to run later.** A command is a
*guess* at what the retriever will match, and it tells the reader nothing until
they execute it. A title is legible at a glance — the reader decides relevance
before spending anything. And the retriever is not reliable enough to be the
only path: measured over five realistic authoring-time questions, roughly two
returned the right entry, and one unrelated entry won twice, because a few long
generic documents dominate the ranking. Pre-resolving the list at authoring
time, by someone who looked, is worth more than a lookup at execution time.

**Why titles rather than the prose.** A pasted body is a copy that drifts from
its source and then silently contradicts it. A stale *title* fails visibly — it
resolves to nothing — which is the failure mode you want.

**Why this section sits before Implementation.** Orientation-time recall does
not defend an authoring-time trap: sessions here have read a lesson at startup
and reproduced it hours later, so presence in the context window is not presence
at the edit. The list has to be on screen at the moment of writing, which is why
it is slotted at 4.6 rather than filed at the end.

⚠ **Do not treat this as the defence.** Deciding to look something up requires
already suspecting the problem, and the suspicion is usually the missing part.
This section helps a reader who is about to start; it cannot help one who does
not know to ask. The mechanical push tier — the folder `CLAUDE.md` ladder and
the edit-time advisories — is what fires without being asked, so a pack that
names the files it touches gets that layer for free. **Name them.**

## Red-team is a step, with a realistic prior

Budget the adversarial pass as a sub-task with time against it, not as a
courtesy at the end.

Set the expectation correctly: in a recent session, **five of eight independent
review lanes returned REQUEST CHANGES on work that was already full-suite
green**, and none of the findings were stylistic. Several were in the *repair*
rather than the original defect — a guard that reproduced the collapse it was
built to catch, a floor that measured a different function than the assertion it
protected, a probe blind to the one mutation it existed to detect.

Write the pack so a clean red-team is the surprise, and so the pass has
something to bite on:

- Name what the pack is **most likely to have gotten wrong**. Authors know.
- Ask for the mutation that survives, not for approval.
- A red-team that ran and found nothing is a result worth recording in Landing.

## Earn the red — per fix, against a named mutation

A test that has only ever passed proves nothing. For each fix, the pack states
**the mutation the new test must die to**, and Landing records that it did.

Two ways this goes hollow, both seen:

- **The fixture agrees with the implementation by accident.** Tests written
  around one artifact shape can be blind to the mirror-image defect — fixtures
  authored in a single consistent order let a wrong selection pass because
  position and value happened to coincide. Build the fixture so the two
  *disagree*, in both directions.
- **The mutation is broader than the defect.** Disabling a helper entirely
  reddens tests for reasons unrelated to the bug. Reconstruct the *actual*
  pre-fix state where you can; a broad mutation can go red for the wrong reason
  and read as proof.

## Standard task-pack section structure

A complete blueprint contains, in order:

1. **Status** — version target, what type of change (feature, modernization,
   cleanup, security, refactor), and a **`Kind:`** line:
   - **`Kind: PACK`** — an executable unit of work; full skeleton required
     (copy-ready Implementation + Pass criteria), executed and
     verified-as-landed.
   - **`Kind: ROADMAP`** — routes/sequences work and spawns lettered child
     packs (TP-Na, TP-Nb…); MAY omit copy-ready Implementation + Pass criteria
     for waves it delegates to children.
2. **Motivation** — why now; what platform shift, internal pain point, or
   discovery prompted this pack
3. **Scope (in)** — what this pack does, broken into sub-tasks
4. **Scope (out)** — what is deliberately deferred, with reasoning
4.5. **Task 0 — Verify** — the oracle, the refuting result, and the exit. See
   *Task 0* above. Required on every `Kind: PACK`.
4.6. **Relevant memory** — a short measured note on what has been going wrong
   lately, the TITLES of the bearing memory/footgun entries with their paths,
   and the query that resolved them. No memory bodies. Sits BEFORE
   Implementation, not after Reach: a list read after the editing is done is a
   reading list, which is the thing the section exists not to be. (Moved here on
   first use — authoring a real pack against the 5.7 slot put it past the point
   where it fires.)
5. **Implementation** / **Conversion procedure** — concrete how-to per
   sub-task, each prescribed fix labelled measured or untested
5.5. **Affected symbols** — under `## Affected symbols`, with
   `### Changed-semantics` / `### Renamed` / `### Added-paths` /
   `### Removed-paths` subsections, one bullet per production symbol as
   `path::symbol` (a whole file the pack adds or removes is declared by its
   path alone -- `surface-impact` reads both directions, and a path-shaped
   `### Renamed` entry as the removal of its old name). This is the section
   `/scope-check` walks (`pack_manifest.parse_affected_symbols`). A rename/config
   pack keyed on a raw literal instead declares `## Affected literals` (walked by
   `parse_affected_literals`); a pack with NEITHER section fails scope-check.
   A bullet struck with `~~...~~` is withdrawn from the walk (record the why
   as prose above the list; `<del>` and a `STRUCK:` prefix are not honoured and
   are reported). A sub-section that declares nothing says so with
   `- (none -- ...)` or `- None.`; a routed bullet with no backticked token is
   one the walk cannot see, and `scope-check` prints it as a `!` line.
5.6. **Reach** — REQUIRED if the pack claims to close a class or defect
   family: which members it closes, **by id**, and which it does not, with the
   reason. Target size is not reach. See *Reach* below.
6. **Pass criteria** — verifiable assertions (test counts, audit results,
   smoke checks) that prove the pack landed.
   ⚠ **A criterion that protects a gate must constrain STRENGTH, not text.**
   Write *"no assertion may be weakened; no sample removed from
   `TRANSIENT_SAMPLES`"* — **never** *"`test_foo.py` passes unmodified"*.
   The intent behind both is the same good rule (don't loosen a gate to clear
   your own red), but an immutability phrasing forbids **strengthening** too,
   and that is the half that bites: it welds any defect already in the gate
   into place, and the executor who spots one is told by your own criterion to
   leave it. One pack shipped a criterion reading *"passes unmodified apart from
   Fix 3's three methods"*; the fourth method in the same class carried the
   same defect, was deferred to honour that wording, and hours later a one-line
   change dropped **47 files — the whole vendored hook layer — from the release
   archive with the full suite green.** The underlying rule: **a pack's Scope (out)
   and pass criteria govern what work to undertake — they never license shipping
   a known defect in the artifact the pack itself produces.** Adjacent work you
   spot in passing is a follow-up; a flaw in the gate or test the pack is
   *delivering* is the pack. Phrase criteria so they cannot be read as if it
   were otherwise.
7. **Files touched** — explicit lists: new files, modified files, deleted
   files, unmodified-on-purpose
8. **Sub-task ordering** — the dependency-correct execution sequence,
   each ending with a checkpoint
9. **Estimated effort** — per-sub-task time budget, plus a total. Include the
   red-team pass.
10. **Landing** — every pack ends with a `## Landing` stanza recording its own
    landing state (the SoT for "did this pack land?", read by tooling and
    stamped at execution time):

    ````markdown
    ## Landing
    - State: DRAFT            # DRAFT | ROADMAP | LANDED | SCRAPPED
    - Commits:               # alive SHAs, TP-tag-derived (never a MEMORY SHA)
    - Suite:                 # e.g. 5296 passed / 0 failed
    - Earn-the-red: <one line on how fixes were confirmed RED before the fix>
    - Red-team: <lanes run, verdicts, what they changed — "none found" is a result>
    - Reach: <members closed / deferred, if the pack claimed a class>
    - Date:
    ````
11. **Optional**: Sharp-edge entry to add (if the pack discovers a footgun)

Pair with a `RUNBOOK.md` that you write alongside the pack (it does not
exist yet, and is not deployed by `init`) — it translates Implementation+Sub-task ordering
into ordered shell commands. The runbook is what Claude Code executes;
the blueprint is what humans read to evaluate the design.

## Task naming

Format: `(*number)-(*letter) *descriptive text`

- Number tracks the major sub-task (5-A, 5-B, 5-C…)
- Letter tracks the step within the sub-task (5-B-1, 5-B-2…)
- Letters cycle A–Z then a–z; reset to A when number increments
- Always pair number-letter with descriptive text — "5-B-1 Convert reflect
  to skill", not just "5-B-1"

Examples from real packs:
- `Task 1-A Fix agent frontmatter`
- `5-B-2 Convert /design to skill`
- `5-F-final Verify + tag`

## Code-fix output format

When the blueprint includes a concrete code change:

- **One fix at a time.** Never bundle multiple file edits into a single
  block.
- **Copy-ready.** Reader should be able to apply directly without
  paraphrasing.
- **Surrounding context.** Include 2–3 lines before and after the change
  at proper indentation, so placement is unambiguous.
- **Never "change this" without exact placement.** "In the import block,
  add X" is too vague; show the existing imports plus the inserted line.
- **Tag a prescribed fence with the file it lands in.** Write the language
  *and* the target: ` ```python target=espalier/cli.py `. A pack quotes
  existing source and prescribes new source in the *same* syntax, and nothing
  downstream can tell the two apart without the tag. An untagged fence is
  read as a quotation, so it is skipped by the check that resolves prescribed
  code against the namespace it will actually run in — which is how a pack
  once prescribed `os.pathsep` for a module that does not import `os`.
- **Label its status.** These rules make a fix unambiguous, not correct. See
  *Prescribe the oracle; propose the fix*.

Example:

````markdown
**Fix 3 — Add path-traversal resolution to `_normalize_input_path`** *(fix
shape, untested — refuted if the helper is reached with an already-resolved
path, which Task 0's oracle decides):*

```python target=tools/cc/hooks/write_guard.py
def _normalize_input_path(p: str, root: Path) -> Path:
    p = p.replace("\\", "/")
    candidate = Path(p)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    return candidate
```
````

## Citing the tree

A pack is read against a tree that moved after it was written. Every claim it
makes about the repo is hand-copied, with no diff, no blame and no CI behind
it — so write claims in the forms that survive an edit.

1. **Cite by symbol, not by line.** `` `espalier/cli.py::_detect_python_command` ``
   over `` `espalier/cli.py:NNN` ``. A symbol survives every edit above it; a line
   number goes stale the moment anyone inserts a line anywhere earlier in the
   file. Use a bare line anchor only where there is no enclosing symbol — a
   module-level constant block, a prose file — and pair it with the symbol
   whenever both exist.
2. **Write a baseline as the command that derives it, not as a number.**
   ``Suite: `pytest -q` `` over `Suite: 7616 / 8 / 4`. A pack's baseline is
   stale as soon as any sibling pack lands, which is the normal case, not the
   unlucky one: one pack's stated baseline was already wrong before it ever
   executed, by exactly the count a pack landing the same day had added.
3. **Never restate a count another surface owns.** Name the deriving command
   or the owning constant instead. This is the rule the rest of the repo
   already holds, applied to packs: state the deriving expression — never the
   members, and never the cardinality either.

The test for all three: **if someone edits an unrelated file, does this claim
become false?** If yes, you wrote a snapshot where a reference belonged. A
count over a population defined as "the most recent N" is the sharpest case —
it rots when the population moves, which for an active repo is several times a
day, and nothing was broken and nothing was fixed.

## Reach — required whenever a pack claims to close a class

**Target size is not reach, and the two feel identical because both are real
numbers.** "This class has 47 members" is a fact about the *problem*. "This
mechanism closes 47 members" is a claim about the *fix*, and it needs its own
measurement.

A pack that names a class, a defect family, or a member count MUST carry a
`## Reach` section. **Lead with the deriving command**, then the per-member
verdict it produced:

````markdown
## Reach
Members derived by: `python3 tools/cc/sister_site_probe.py --json`
(scope: whatever its SCOPE block names — your source roots on an adopter
tree, hooks + top-level engine on the harness's own; a clean exit is not an
absence proof)

| Item | Status | Evidence |
|---|---|---|
| `DEF-484` | **CLOSED** | the mechanism was driven against it and it goes red |
| `DEF-473` | **NOT REACHED** | absence-shaped; a positive match cannot express an omission |
````

Rules:

- **Per-member, not aggregate.** "closes most of §C1" is not a reach statement.
- **The roster is the oracle's output, not the author's memory.** If the two
  disagree at execution time, the oracle wins and the pack is re-scoped.
- **If reach cannot be enumerated at authoring time**, make the enumeration the
  pack's first sub-task and give it a **stop condition** ("if fewer than N are
  reachable, re-raise rather than build").
- **State what is NOT reached and why**, so a later pass cannot read the class as
  shut. A "does not reach" note naming no ids joins to nothing and is prose.
- **Never write "closes toward".** The hedge carries the whole claim while
  reading as a measurement.

**Why this is a required section.** Two consecutive packs were authored against a
real gap, with a sound mechanism and honest citations, and both stated a target
size in place of a reach: one proposed a duplicate-code advisory for a backlog
whose classes were not duplication-shaped (reach ~0 of 25); its replacement
proposed a restatement grep for a class whose members are *omissions*, which a
positive match structurally cannot see (reach ~1 of 47). The second was written
one day after the first was retired, by the same author, citing the retirement
note that names this exact failure. Attention did not prevent it; a required
section is the mechanism.

## Scope discipline

- **Scope (in)** = what this pack actually does. Each entry must map to a
  sub-task and to entries in *Files touched*.
- **Scope (out)** = what could plausibly be in this pack but is being
  deferred. Each entry includes the *reason* for deferral (cost,
  dependency, separate concern, future version target). Out-of-scope is
  not "we forgot" — it's "we considered and chose not to."
- A pack with no Scope (out) section is suspicious — almost any change
  has adjacent work that *could* be bundled but shouldn't. On the
  Espalier-Harness source tree the section is machine-read: the ledger's
  strike verb refuses to close a row an active pack's Scope (out) still
  cites, so spell row ids with their prefix in backticks, and a pack id only
  when the pack exists.
- **A scope-out is a claim too.** "Deferred because X" is refutable, and
  refuting it is cheap. Verify the *rationale*, not only the prescription — a
  deferral resting on a false reason silently drops real work.

## Sub-task ordering rules

- Task 0 (verify) comes first, always, and may end the pack
- First implementation sub-task should be the smallest concrete change (build
  momentum, surface execution-environment issues early)
- Heavy/risky work in the middle
- Red-team pass, then verification + tag last
- Each sub-task ends with a checkpoint command (audit, smoke, pytest)
  that produces a green/red signal
- If a sub-task's premise depends on an earlier sub-task's output, make
  the dependency explicit in the sub-task heading

## Pre-work / RUNBOOK conventions

- If the pack assumes a platform schema, the RUNBOOK's Pre-work step
  fetches the live docs and pauses on breaking deltas — don't guess.
- If the pack will edit source files, the RUNBOOK creates an execution
  plan via `tools/cc/execution_plan.py` first (plan_guard requires it).
- Tag a `pre-pack` git tag at start; rollback uses `git reset --hard
  pre-pack`.

## When the pack and reality drift

Two different drifts, with two different exits.

**A stale premise** — the file the pack says is 54 lines is now 5 after a merge.
Pause and report the delta. The blueprint is a design snapshot; the RUNBOOK is
execution orders. Neither is permission to ignore changed ground truth.

**A refuted prescription** — the premise is current and the *fix* is wrong or
inert. This is the harder one, because nothing looks stale: the citations
resolve, the class is real, the mechanism is described correctly, and the
prescribed change simply would not accomplish it. Do not adjust the fix and
continue. **Re-raise**, with the measurement that refuted it, and let the
decision be re-made against what is now known. The narrow discriminator: the
justifying *reason* is gone — not merely that the work turned out harder or the
executor is unsure.

Recording the refutation is part of the work. A prescription that was disproved
and quietly replaced teaches the next author nothing, and the ledger row it came
from will re-propose it.
