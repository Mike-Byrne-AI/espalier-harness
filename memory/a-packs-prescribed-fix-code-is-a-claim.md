# A pack's prescribed fix code is a claim — test it before you trust it

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "A pack's prescribed fix code is a claim — test it"

**Kin:** [derive-a-guard-from-its-calibrated-sibling](derive-a-guard-from-its-calibrated-sibling.md) — testing the prescribed snippet catches a wrong one; it does not tell you a calibrated version already exists elsewhere in the tree.

A regex, snippet, or code block written **into a task pack** is **untested author
intent**, not working code. Execute it against live data before adopting it.

## The class is wider than packs: a TRACKER ROW's prescription too (2026-08-15)

A ledger row's *prescribed remedy* is the same untested author intent, and it is
worse defended, because a row arrives as **structure** — a cell in a table you
are working down — so it never reads as a claim to be checked.

`DEF-410i`'s RECORD stanza said to mark four `docs/CHEAT-SHEET.md` verbs
"self-host only". Driven on a foreign `init` tree, **three of the four were
wrong**: `self-host` returns a real gate report (`mode_resolved:
initialized_consumer_repo`), `verify-landing` runs a real pack landing check,
`scaffolding-bench` writes a real report. Executing the prescription would have
shipped three false statements into a doc every adopter receives.

Two details worth carrying:

- **A fresher measurement already existed and disagreed.**
  `tests/test_adopter_verb_stand_down.py::UNGATED_REASONS` had recorded all
  three as adopter-applicable, with reasons, on 2026-08-13. The stanza was
  stale. When a row and a test disagree, the test is the one that gets re-run.
- **A review lane relayed the stale prescription back to me as its ship-list.**
  A subagent reading the row inherits its authority; it does not re-derive it
  unless told to. Ask an agent for the *measurement*, not for confirmation of
  the row.

## Why the suite gives you no protection here

The test suite has **zero coverage on prose**. A pack document can carry a
subtly-wrong regex or an API misuse indefinitely and every gate stays green,
because nothing executes the pack. The first execution is when you copy the
snippet into source — at which point the defect is now *yours*, and it looks like
your bug, not the pack's.

## The evidence

- **Copied violations shipped verbatim.** A new tool script shipped with two
  repo-contract violations — provenance tags and `subprocess.run(text=True)` calls
  missing `encoding="utf-8"`. **Both offending lines were copied verbatim from the
  pack's prescribed code.** They then compounded with the `git ls-files`
  blindness (see `docs/SHARP_EDGES.md`): the file was untracked at gate time, so
  the full suite false-greened them.
- **A no-op exemption.** A pack prescribed a `globals().get("cmd_fuse")`
  exemption that could never fire — `cmd_fuse` is a `build_parser` **local**,
  never a module global. Copied faithfully, it was a silent no-op until replaced
  with a live import.
- **An unverified complexity claim.** A pack described a per-symbol
  `walk_references` loop as "O(files), fast." Measured on a real tree it took
  **242 seconds**. See `docs/FAILURE_MODES.md` on per-item subprocess loops:
  "fast" was direction, not magnitude (`docs/STANDING_PRINCIPLES.md` §6).

## The same shape from a REVIEW AGENT, and it is now the more common source

A pack is authored once; a review agent prescribes a fix on every round, so this
is where the shape actually recurs. **An agent's finding and its proposed remedy
are two separate claims, and confirming the first tells you nothing about the
second.** Measured over one pack execution (2026-08-11, `TP-436`): three reviewer
findings were real, and **three of three prescribed fixes were wrong** —

- *"Add the freshness scanner to `_SCANNER_EXEMPT_REGISTRIES`."* That registry
  asserts each entry resolves to a real **file**; the attribute it named holds
  **globs**. Adopting it would have red the existing test.
- *"Add `.catch(` to the required-token dict — it reds exactly the two files
  lacking a persist catch."* Both files already `.catch` on their *finder* calls,
  so the token was present and the check passed **vacuously**. The working
  version had to scope to the persist call specifically.
- *"Constrain the exemption scan by attribute-name regex."* Sound, but strictly
  weaker than replacing the static scan with a probe that **runs the scanner**
  and looks at what it flags.

Every one was caught by a single probe costing under a minute. The failure mode
if you skip it is worse than a wasted fix: you land a *plausible* change under a
confirmed finding's authority, and the green suite now certifies it.

Note the asymmetry with `docs/STANDING_PRINCIPLES.md` §3 — a *finding* is
falsifiable by grep, so it gets verified as a matter of course. A *remedy* reads
as the reviewer's expertise rather than as a claim, so it slips past the same
reflex. Convergence between agents confirms a defect **exists**; it never
confirms either agent's fix is right.

## And from YOUR OWN HANDOFF — where the prescription names a shape that does not exist (2026-09-03)

The third source, after packs and review agents, is **the note you wrote to
yourself**. It is the worst defended of the three: a handoff prescription arrives
already carrying your own authority, at the moment you have the least context to
audit it, and the session-opening instructions tell you to orient by *reasoning
over it* rather than re-deriving it.

`DEF-639`'s residue was prescribed in two places — `cc/GOAL.md`'s notes and the
`_collect_indirect_operator_strings` docstring — as:

> a constructor-shape rule for the `CP_* = Speedbump(reason=...)` form

**That form does not exist.** The live shape is `SpeedBump(body=...)`: different
class casing, different kwarg. A rule keyed on the prescription would have
matched nothing, collected zero strings, and **read as coverage** — the
born-blind gate that became `docs/STANDING_PRINCIPLES.md` §18/§19 in the very
session that wrote this prescription. The handoff reproduced the defect it was
written about.

Note the failure MODE, because it is not the pack-prescription one. A wrong
regex reds and you notice. A prescription naming a **non-existent symbol shape**
produces a rule that is *silently vacuous* — it passes, it looks like a gate, and
nothing distinguishes it from a working one without a driven mutation.

The same handoff's second prescription — *"a constructor rule MUST exclude
`re.compile` or it re-collects patterns as messages"* — was **unsound in the
other direction**. `tools/cc/hooks/_bash_patterns.py` holds 46 constants: 44 are
`re.compile`, and the two that a message-collector would actually trip over
(`_CMD_POS_WRAPPER`, `_PS_CMD_POS_EXEC_QUOTE`) are bare `r"..."` regex *sources*
compiled elsewhere. The prescribed exclusion misses exactly the cases it was
prescribed for.

What replaced both: the **constructor kwarg is the classification signal**, and
it is derived rather than declared. On one `Profile(...)` constant,
`description=` holds prose up to 406 chars while `allow=` holds permission
patterns capped at 27 — so a kwarg-keyed rule separates message from data
structurally, and needs no `re.compile` exclusion at all, because a regex never
lives in a `body=` or `description=`.

## How to apply

1. **Execute every prescribed snippet against live data** before committing it —
   a regex against the real corpus, a predicate over the real file set. This
   applies verbatim to a review agent's proposed fix: adopt the finding, drive
   the remedy. Where the remedy is a new assertion, the probe is "does it red on
   the state it claims to catch?" — a token check that was already satisfied
   elsewhere in the file is the common failure.
2. Treat a pack's stated **complexity or performance property** as a claim
   requiring measurement, exactly like a correctness claim.
3. When the snippet is wrong, **fix the pack too**, not just your copy — see
   [[fix-the-pack-and-proceed-on-a-pre-flight-defect]]. A prescription in
   `cc/GOAL.md` or a docstring counts: correct it in the handoff artifact, or the
   next session inherits it with your authority attached.
4. **`ast.unparse` the real site before writing a rule that keys on its shape.**
   A prescribed *shape* (class name, kwarg, call form) is checkable in one
   command and is the cheapest claim in this whole note to falsify — and when it
   is wrong the resulting gate is vacuous rather than red, so nothing else will
   tell you.

This is the authoring-side sibling of `docs/STANDING_PRINCIPLES.md` §3
(a finding is a claim until grep-verified) and the direct parent of
[[verify-a-packs-scope-out-rationale]] (the same scrutiny, applied to what a pack
says to *leave alone*).

## The fix SHAPE in prose is the same claim, and a run summary is where it comes from (2026-09-20)

A pack's "fix shape" paragraph, written at a handoff from the run's own
summary, described the rows a rebuild had held as "a co-id that is the
primary id of its own §1 row" and prescribed a structural rule (decide by
the first id; consult a co-id only when it has no row of its own). A
five-line probe over the file before the first edit showed the §1 rows carry
the **identical** id pair, member id first, so the structural rule decided
nothing; the routing fact was the workflow's own keying (a `section` field
its merge sets), and the rule that shipped was a different one. Then both
review lanes drove the candidate fix on the real ledger and found two mis-keys
a synthetic fixture could not reach — an extra strike on a real launch gate
deleting the row while its member row lived, and a struck member's first id
swallowed. Third instance in one pack of a fixture, or the prose beside it,
missing the real file's shape: measure the rows the prescription is about
before the first edit, and ask the reviewers for the real-artifact drive, not
for confirmation of the prescription.
