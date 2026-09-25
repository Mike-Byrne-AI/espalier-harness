# Ladder CLAUDE.md design: pointer, not restatement

**Status:** active

**Linked from:** ESPALIER_MEMORY.md row "folder-CLAUDE.md ladder: pointer, not restatement"

The per-folder `CLAUDE.md` router ladder is **causally load-bearing**: a single
in-context line shapes the work a session does, and it wins the cold open over a
correction that lived only in conversation and evaporated. So a stale ladder line
does not merely fail to help — it actively re-drives the wrong behavior, session
after session. That is the harness's own durable-memory thesis turned on itself.

## The design each ladder file follows

- **Doing** — what this folder *is* (one line of orientation).
- **Don't break** — the **sole-home** mechanical rules for this folder: the
  obligations that live *here and nowhere else* (sync-this-mirror, git-add-before-gating,
  the filename/section contract). High-value how-to belongs here.
- **Read first** — a **pointer** to the source of truth, not a copy of it.

## The sharp axis: restates-a-drifting-SoT vs sole-home-of-a-rule

The line to cut is **not** "how-to vs what-is." A sync obligation is high-value
how-to and stays. The line to cut is a step that **restates a slice of another
authority's behavior** — an authority that can *drift out from under the copy*.

- **Sole home of a rule** → keep it. Nothing else states it; it cannot go stale
  against a moving original because it *is* the original.
- **Restates a drifting SoT** → convert to a pointer. The moment the authority it
  paraphrases changes, the copy is a lie that reads as truth.

The canonical offender: `task-packs/CLAUDE.md` told drafters to "run `/scope-check`
before invoking `/implement-pack`." That restated `/implement-pack`'s own behavior —
and went stale the moment `/implement-pack` absorbed scope-check into its step **0-B**
(the same `espalier scope-check`). The ladder line then pointed at duplicate work.
The fix was not to delete the scope-check mention but to **re-scope it to its true
distinct use** (authoring-only, while drafting) and **link the SoT** rather than
paraphrase it.

## What this does and does not buy

A mechanical guard can pin the *link* half of a pointer — a footgun test walks each
folder `CLAUDE.md`, resolves every markdown link target, and freshness-checks every
`` `symbol`+`file.py:NN` `` anchor, so a pointer whose target *file or anchor* rots
reds. It **cannot** catch a pointer whose target *command changed behavior* while
staying at the same path (exactly the 0-B case: `scope-check.md` never moved;
`/implement-pack` grew around it). Full behavior-drift detection is not mechanically
tractable here. Naming that limit honestly is the point — the principle plus the
link-guard *reduce* recurrence; they do not seal it.

## When a router actually loads — and what that forecloses

A folder router enters context **only when the Read tool touches a file in that
folder**. It does not load at SessionStart, and it does not load on a `grep`, `sed`
or other Bash read of the same path. Measured directly rather than assumed: reading
a scanner module injected both its own folder router and its parent's, while several
preceding Bash reads of those identical paths injected nothing.

**Confirmed against the official documentation 2026-08-19**, which is worth recording
because it upgrades a measured-here claim to a documented-platform one:
*"Instead of loading them at launch, they are included when Claude reads files in
those subdirectories"* (`code.claude.com/docs/en/memory.md`). Two consequences the
measurement above already implies but that are easy to miss when designing:
**there is no folder-OPEN event at all** — `ls`, `Glob` and navigation trigger
nothing — and **`README.md` has zero special treatment**, so a directory holding only
`CLAUDE.md` and `README.md` has no trigger and its router can never fire. A
navigation design must therefore be driven by *reading an index file*, which is
itself the trigger that loads that folder's router. The parent-too behaviour measured
above is the part the docs leave ambiguous; trust the measurement, and note it means
an intermediate rung still fires when a session jumps straight to a leaf.

⚠ **This section answered a question a later session re-derived from scratch via an
external agent dispatch, because `/recall` did not surface it.** Driven: the jargon
query "folder router load trigger" returns this note; the plain-English questions
"when does a folder CLAUDE.md load" and "does a nested CLAUDE.md load on folder open"
both miss it entirely. That is the paraphrase gap costing a real dispatch on a
question already answered here — the cleanest attestation the repo has that captured
knowledge and delivered knowledge are different problems.

That single fact decides what a router may be used for. A router is the right home
for a constraint **any touch in the folder risks tripping** — the trigger and the
delivery coincide. It is the wrong home for a rule that must fire at a decision
**preceding any file touch**, because at that moment the router has not loaded and
cannot. For those, the venues that actually deliver are the root charter (injected
natively every session), the SessionStart standing-principles index, the machine-global
`~/.claude/CLAUDE.md`, and the command or skill body that scripts the behavior.

The practical trap: fanning a rule across every router *feels* like thorough coverage
and is closer to the opposite — it multiplies restatement surface (above) while adding
no delivery at the moment the rule is needed. Ask **when** the line has to be in
context, not just **who** should see it.

## How to apply

When you edit or add a folder `CLAUDE.md`: keep sole-home rules, keep sync/how-to
obligations, and make every reference to another command/skill/doc a **link**, never
a paraphrase of its behavior. Before restating what another SoT does, ask: *can that
SoT drift without this line knowing?* If yes, point — don't copy. And land the
correction **durably** (in the ladder file + canon), not only in the session — the
whole reason this class exists is that a conversational fix evaporates while the
durable line persists and wins.

Related: [[grep-for-a-sibling-store-before-building-a-rival]] (reuse an authority,
don't clone it), [[measure-efficacy-not-just-correctness]] (a ladder line is judged
by the work it drives, not by whether it is technically true).
