# Standing Principles

The few cross-cutting lessons worth holding in context for **any** Espalier-Harness
work — the durable layer beneath the specific catalogs. Read at session start and
keep these live while you work.

> **Status:** curated starting set (2026-06-29). Not exhaustive — populated with
> what has earned its place across many sessions; to be de-duped and trimmed later
> against the catalogs below. These are **lessons and governing frames**, not pinned
> factual claims (so they are out of scope for `audit_accuracy`).

> **Writing a title here: the title is the only part that gets injected.** The
> SessionStart banner renders these `##` headings and nothing else — bodies are pulled
> on demand, so the default state of every session is title-only. A title must
> therefore be **safe and correct read completely alone**. Prefer an epistemic frame
> ("a finding is a claim until grep-verified"), a framing ("fast earns scrutiny"), or
> an *ordered* constructive act ("read the neighbours **before** adding a sibling").
> Avoid a bare destructive imperative, and avoid a conditional whose condition is the
> hard judgement the body exists to teach — a reader holding only the title will treat
> the condition as a quick check and over-apply it. §14 shipped briefly as *"if a
> machine can maintain the list, delete the list"* and was retitled for exactly this:
> read alone it licensed the deletion without the replacement, and made the tier
> judgement sound easy when it is the expensive part.

**How this differs from the other reference surfaces** (so they don't drift into each other):

| Surface | Holds | Accessed by |
|---|---|---|
| **This doc** | the few always-relevant cross-cutting frames | held in context always · `/recall <principle name>` |
| [`SHARP_EDGES.md`](SHARP_EDGES.md) | concrete, this-repo footguns | `/recall <topic>` · folder `CLAUDE.md` on entry |
| [`FAILURE_MODES.md`](FAILURE_MODES.md) | generative failure *classes* | `/recall <topic>` |
| `memory/*.md` | topic-scoped accumulated judgment | `/recall <topic>` |

---

## 1. Make it prove it

Don't trust the AI's word — make every load-bearing claim **mechanically** provable.
The verification machinery (untrusted-oracle, earn-the-red, adversarial fan-out,
`red_team_guard`) is one idea and this project's defensible identity. Self-asserted
confidence is a hypothesis, not a result — including your own.

## 2. Toolbelt, not security boundary

The primary job is an importable Claude Code workflow + coding toolbelt for solo
founders and small teams. The threat model is operator/AI **mistakes, not malice**.
False-positives and workflow friction outrank closing bypass classes. Read every
guard, gate, and "security" decision through this lens.

## 3. A finding is a claim until grep-verified

A fan-out or agent finding — even one labeled "adversarially verified" — is a
**claim, not a result**. Grep-verify every cited line/symbol against `HEAD`, and
simulate a clean checkout, before trusting a pack's blockers. (Verify the *absence*
of findings too — see §5.)

Two extensions, both paid for:

- **It applies to what you are about to WRITE DOWN, not only to what you act on.** A
  citation copied from an agent report into a tracker row is laundered into fact by the
  copy — the row does not say where it came from, and the next reader has no way to tell.
  Measured: a filed row named a pin at `file:line` carried verbatim from a lane report;
  that file contained zero references to the constant claimed.
- **The refutation is a claim too.** An adversarial reviewer that overturns a finding is
  making its own assertion, and default-refuted framing makes it *sound* conservative
  while it does so. Measured, same session: a reviewer correctly caught the bad citation
  and gave the wrong reason for it — its stated mechanism was falsified by driving the
  pin in-process, which is how the row's real defect (it pinned the wrong constant
  entirely) came out. Drive the refuter on the same terms you drove the finding.

## 4. Verify tool output through an independent oracle

When a tool's output looks fabricated, empty, or stale, confirm it via a **second,
independent mechanical oracle** before acting. Never trust a single rendered frame —
a rendered test-failure is not a test result; `exit 0` is not acceptance.

## 5. The null result is the signal

A large codebase exceeds any single pass. Correctness is **built** by many
independent, differently-angled passes — and repeatedly finding nothing new is the
strongest correctness signal there is, not a reason to stop. Low yield = confidence
compounding. Track BLOCKER yield + severity trend, not raw finding count. The
precondition: a null counts only once the pass is known to have run — see
[`memory/a-probes-silence-is-not-a-null.md`](../memory/a-probes-silence-is-not-a-null.md).

## 6. Direction ≠ magnitude

A sound mechanism is not a measured effect. State them apart; never let plausibility
smuggle in size. Grade a campaign on the repo's **own** metrics measured before/after
(worktree the base commit), not on "landed green." A self-report that something
"made it work better" is a hypothesis to test, not a result to bank.

## 7. Earn the red

A fix needs a test that goes **red without it**. If a version/OS-gated bug can't go
red on this host, ship the version-agnostic fix + a contract-lock test and label the
target-version magnitude **unverified-on-host** — don't fake the red. Earn-the-red
proves *X*, not "not-also-*Y*": implement → adversarially verify is mandatory even
for green-suite polish.

## 8. Class-fix scope = every shipped surface

When fixing a defect *class*, the roadmap's site count is a **floor** — AST-enumerate
the real surface, and scope the fix + its contract to every shipped/overlaid
directory (sdist + fuse overlay), not just the engine dirs. A new untracked file is
invisible to `git ls-files`-derived gates until `git add`-ed.

**Upstream of this principle:** deciding it *is* a class. This section is the *how*;
the *when* — the trigger that asks whether a defect is one site of a mechanism before
any fix is authored, and the `sister_site_probe.py` oracle that answers it — lives at
[`memory/fix-the-class-not-the-instance.md`](../memory/fix-the-class-not-the-instance.md).

## 9. Fast earns scrutiny

Breakthrough-feeling is the cue to **slow down and check harder**, not to commit.
The better an idea feels, the harder it should get checked. Strip the most flattering
evidence and see what still stands.

## 10. Match the net to the hole

Verification has a mesh size — no single net catches every defect class. **Earn-the-red**
(§7) catches "does this test discriminate the mutation it names"; it does **not** catch
whether an *enforcement contract's* claim about the live population is true. A new scanner or
gate is born-green on a synthetic fixture — the earn-the-red passes — while its real
calibration is false: the rule matches 30 live sites, not the 4 the pack promised. That hole
needs a **different net — calibrate the contract against the live population** before trusting
it. Corollary: a pack is a *hypothesis*; authoring generates claims, execution verifies them.
The strength of the system is the verification, not a perfect pack — chasing a flawless pack
at authoring time is chasing a flawless launch.

## 11. Scope-out cannot cover the deliverable's own defects

A pack's `Scope (out)` and pass criteria govern **what work to undertake**. They never
license shipping a known defect in **the artifact that pack itself produces**. Adjacent
work you spot in passing is a follow-up; a flaw in the gate, test, or mechanism the pack
is *delivering* is the pack. Amend the criterion and record the amendment — do not file
it forward.

**The tell:** a `DEF-*` row you wrote against your own deliverable, in the same session
you built it. That is not a backlog item, it is an unfinished fix.

**Why it needs stating.** The instinct that fails here is a *good* one — respect the
scope contract, propose rather than silently expand (`memory/verify-a-packs-scope-out-rationale.md`).
That instinct is correct for adjacent work and wrong for your own output, and the
failure mode is invisible because every gate stays green: a change re-anchored three
release-surface assertions, spotted that the fourth carried the same defect inverted,
deferred it because a pass criterion pinned that file as "unmodified", and **within the
hour a one-line change dropped 47 files — the entire vendored hook layer — from the
release archive with the full suite green.** The deferred row was the exact hole.

**Corollary — an anti-loosening criterion must constrain STRENGTH, not text.** "No
assertion may be weakened, no sample removed" is enforceable and correct. "File X passes
unmodified" forbids *strengthening* too, which is how a criterion written to protect a
gate ends up welding a defect into it. Phrase the constraint monotonically; see
`.claude/skills/blueprint-authoring/SKILL.md`.

## 12. A gate is proven only on a tree it was not written on

When the deliverable **is** a gate — a guard, a pin, a census, a parity contract, a
derivation — the acceptance oracle must be a tree that gate did not grow up on. A real
`git clone`, an extracted archive or sdist, a non-editable install, a fresh venv, CI.
Not the working tree you wrote it against.

**Why §7 does not already cover this.** Earn-the-red proves a gate *fires*. It cannot
prove the gate is *correct*, because the red is earned on the same tree — with its
gitignored files present, its `cc/blueprints` populated, its venv active, its
`egg-info` built. A guard validated only there has been tested against its own author's
assumptions, and every one of those assumptions is invisible precisely because it holds.

**The attestation, and it is the whole argument.** A mirror-census pack (2026-08-05)
recorded **four earned reds**, all legitimate — one of them literally *"hand-editing a
count to 'eight' reddened the prose guard."* It also ran a second review round its own
landing record calls *"the workflow step I nearly skipped."* Suite green, `audit` 0/0,
provenance clean.
It shipped a census guard pinned to a **gitignored** file: green for its author, red on
every clone and every CI checkout. §7 was satisfied. §3, §4 and a dispatched reviewer were
satisfied. **The defect was not visible from any tree in the room.**

**The tell:** you can state the gate's pass condition without naming a tree. "The census
guard is green" is not a fact about the code; it is a fact about *a* tree. Ask *which one*,
and then run it somewhere else.

**Cost, stated honestly — the local form is free, the remote one is not.**
`git clone --no-hardlinks . <tmp> && cd <tmp> && pytest -q` is about six minutes of local
CPU and costs nothing; run it every session. `.github/workflows/test.yml`'s
`clean-checkout` job is the same gate on hosted runners, but it answers an hour or more
after the push, so a red found there is found late. Use the local clone as the routine gate and
spend the push deliberately. A 2026-08-05 fan-out review spent six hours and 22M tokens
rediscovering what six local minutes would have shown; the gate had simply not been run in
37 commits. **A gate you own and never run is worth nothing; this principle is mostly an
instruction to run the cheap one.**

**The authoring form — resolve against the tree that ships.** Running the gate elsewhere
catches this; writing it against the shipped set forecloses it. A gate that *resolves*
something — a path, an id, a citation — resolves it against whatever the local tree happens
to hold, and a working tree holds more than a checkout does: ignored scratch directories,
build output, and the status folders a maintainer keeps for landed, merged and abandoned
work. A citation into one of those resolves for its author and dangles for everyone else,
so the gate is green in exactly the case it exists to catch. Measured 2026-09-21: a
completeness gate resolved task-pack ids against any status folder and was green here and
red on a clone whose `Done/` had never existed. **Enumerate the locations the shipped tree
carries and resolve against those only** — then the verdict is identical on both trees, and
the clone confirms the gate instead of being the only thing that can see it. The
earn-the-red is one case per folder the working tree has and the shipped one does not.

§4 (independent oracle) names the discipline and §7 names the proof; this names the
*tree*. The footgun form, with its attested instances, is
[`docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md`](sharp-edges/source-tree-is-not-an-artifact-oracle.md);
the population-axis twin — a guard validated only at the set's current size — is
`docs/FAILURE_MODES.md` §13.21.

## 13. Read the neighbours before adding a sibling

Before adding a **new instance of an existing kind** — an emitted hint, a path helper, a
guard predicate, a warning message, a fixture — read how the file already does that thing.
The correct spelling is usually a few lines away, written by someone who already hit the
footgun you are about to hit.

This is the authoring-side twin of §8 and of `memory/fix-the-class-not-the-instance.md`:
those ask *"is this defect one site of a class?"* before you **fix**; this asks *"is this
addition one site of a class?"* before you **write**.

**The attestation.** An interpreter-detection fix (2026-08-07) survived five review rounds
in which every headline *diagnosis* held and a *prescription* broke each time. Three of the
broken ones were this shape — new code written beside correct code without reading it. A containment
predicate used `Path(resolved).resolve()`, which the sibling fix's own docstring forbade
**in bold, 180 lines earlier**, leaving the guard inert on every POSIX venv. A second
containment helper was added beside an existing importable one, with a *different* body.
A hint was emitted as a bare `` `espalier init .` `` in a file whose ~12 other hints all
used `` `<interp> -m espalier …` `` — which reds `tests/test_no_bare_espalier_hints.py`
and is command-not-found in a fusion. None was hard. Each was a local convention nobody read.

**The tell:** you are about to say *"I need a hint / helper / predicate here"* and reach
for a fresh one, instead of asking *"how does this file already spell it?"* The risk is
highest where it feels lowest — the fourteenth hint string feels mechanical, so it skips
the scrutiny a new mechanism would get.

**The habit,** two questions in order: (1) *Does this already exist?* If yes, import it —
a twin with a different body is worse than a duplicate, because it reads as intentional.
(2) *If it must be new, what shape do its neighbours have?* Match it, or state why not. A
new shape beside twelve old ones is a claim that the twelve are wrong; make that claim
explicitly or not at all. Grep the **target file**, not the tree.

This does not say "always conform" — sometimes the neighbours are the defect, which is
what §8 is for. It says you must have *read* them and chosen. Deviating with a reason is
fine; deviating without noticing is the failure.

**Why review does not save you:** an agent reads the diff, not the file. A new hint looks
locally correct in isolation and is wrong only *relative to its neighbours* — visible only
to a reader holding the whole file. The habit belongs to the author, before the diff
exists. Sole home: [`memory/read-the-neighbours-before-adding-a-sibling.md`](../memory/read-the-neighbours-before-adding-a-sibling.md).

## 14. Derive the list, don't test a hand-written copy of it

**Deletion is the second half of this principle, never the first.** Build the
derivation, prove it produces the current content, *then* delete the hand copy — and
only for the subset that qualifies, which is smaller than it looks. Deleting an
enumeration without standing up its replacement destroys information and passes every
test, because nothing pins prose.

When a hand-written list is supposed to mirror something the code can already compute,
the fix is to **emit or read from the computation and drop the hand copy** — not to add
a test that recomputes the answer in order to check the copy.

The contract-first instinct is strong because a test feels like the safe, additive
move. It is the more expensive one. It leaves two copies and a human in the loop for
every legitimate change, and the second edit is the one people forget — which is the
original defect, now with a guard bolted on. A generated list has no second copy to
drift.

**The measurement.** A census of this repo's largest defect class — every catalogued
case of a declared population standing in for a derivable one — tiered its 30 members,
then two adversarial passes attacked every tier call. Of the 26 that still reproduce:
**ten** are better closed by deriving the list out of existence, **seven** genuinely
need a contract, and **nine** are human judgement no oracle can compute. The class's own
written prescription was "assert declared == derived" for all of them. That prescription
is *wrong* for the ten and *impossible* for the nine, which is why five successive review
rounds failed to close a class that a single pack was supposed to shut.

**Read that measurement with its own warning attached.** The unopposed census produced
11 / 10 / 5; the refuted result is 10 / 7 / 9. The headline barely moved — and **15 of
26 rows changed tier**, the movements cancelling almost exactly. Reporting the aggregate
after one pass would have looked like confirmation while nearly every per-row instruction
was still wrong. An aggregate can be right while its components are noise, and the
aggregate is the thing that reads as a measurement. Tier a population once and you have a
hypothesis; the number is only worth quoting after something has tried to break each row.

**The honest bound — this principle does not say generation is always better.**
Generation removes drift *between copies*; it does not verify the *single remaining
copy*. Delete the hand-list and a bug in the derivation produces a confident,
complete-looking, silently-wrong answer with nothing left to disagree with it. So:

**The discriminator is not how messy the derivation is — it is which side of the
assertion it lands on:**

> **Derive the population and a narrowing is silent. Derive the expectation and a
> narrowing is loud.**

A filthy computation is *safe* on the right-hand side of a subset assertion: shrink it
and the assertion fails, so the failure direction is inverted and the derivation cannot
hide anything. A pristine declaration is *dangerous* when it defines the set of things
being checked at all: shrink that and everything still passes, over fewer cases. The
attested pair — a driven-subprocess parse feeding an expectation survived every attempt
to break it, while a clean directory glob defining a test's population failed at
`1 skipped`, exit 0, on a supply-chain gate. Before deriving anything, ask: *if this
returned fewer items tomorrow, would something red?*

- **Derive** where the result feeds an expectation, or where the source is a declaration
  with no logic to go wrong — a literal registry, a field the data already carries.
- **Keep two independent derivations** where the derived thing *is* the population and
  the logic carries exclusions, filters, direction or special cases. Some things cannot
  be derived at all: you can compute a population, but an *exclusion* is a judgement
  about that population, and *direction* is not recoverable from two byte-identical
  files — measured here on a mirror pair identical to the byte, with no mtime in git and
  17 of 18 commits touching both sides. Independence is the whole load, and it fails
  silently when absent — see [`docs/FAILURE_MODES.md`](FAILURE_MODES.md) §13.26. If the
  only available second derivation would restate the subject, the answer is not a
  contract; a contract there is theatre.
- **Write the reason** where the list is a decision rather than a fact. Naming it as a
  decision closes it; leaving it in an open-work list implies a fix that cannot exist.

**There is a second discriminator, and it is about deployment.** The rule above decides
whether a population should be derived at all. This one decides *where the derived text
is allowed to live*:

> **Generate where the doc has no downstream copies; contract where it ships.**

A generated region is a standing promise that something will regenerate it. That promise
is false the moment the file lands somewhere no generator runs — and actively harmful
when the file *also* ships under an ownership promise. An `init` seed doc that is also a
mirror source is exactly that shape: `espalier/cli.py::_seed_redeploy_decision` returns
`"preserve"` **permanently** once an adopter's post-stamp bytes stop hashing to the
recorded digest. So the first time they edit one word, they are frozen holding a block
headed *do not hand-edit*, with no `scripts/` to run. The region has converted a stale
hand-list into a stale hand-list nobody is permitted to repair — strictly worse than what
it replaced, because the banner discourages the one fix a human would otherwise make.

Measured on this repo when the rule was written: of four docs enumerating a code-owned
population, two (`README.md`, `docs/QUICKSTART.md`) have zero downstream copies and took
generated regions; two (`docs/TROUBLESHOOTING.md`, `docs/WORKFLOW.md`) are seed-and-mirror
and took a contract test over hand-written prose instead. One class, one defect, two
mechanisms — chosen by where the bytes end up, not by how the list is maintained.

**The tell:** you are about to write a test whose body recomputes the correct answer in
order to compare it against something a human typed. Ask why the typed copy still
exists. If the answer is "so the test has something to check", delete it.

**Generation is not free of contracts — it collapses them.** A generated region still
needs one check: *do these bytes match what the generator produces now?* Without it, a
hand-edit inside the block silently reverts on the next regeneration, or nobody
regenerates and it rots exactly as the hand-list did. But that is **one** trivial,
reusable assertion covering every generated region, instead of N bespoke ones — which
is the actual prize.

That assertion now exists — `tests/test_doc_regions.py::TestEveryGeneratedRegionHasAGenerator`
— and it is worth recording that it did not, for the whole period this paragraph claimed
it as the prize. Nothing scanned the tree for markers, so a region with no generator
behind it was invisible to the suite while reading as machine-maintained to every human
who saw the banner. A principle that names its own mechanism still has to be built; until
it is, the paragraph is a plan, not a guarantee.

## 15. Many attempts, a different failure each time — the problem is mis-specified

A hard defect fails the **same way** repeatedly: you are fighting a known thing, and
each attempt gets closer. A **mis-specified** problem fails a **new way each time**,
because every attempt uncovers more of the actual shape. The tell is not how many
times you have tried — it is whether the failure mode is novel.

When round N dies for a reason nobody had considered, stop writing fix code. The next
fix will fail for reason N+1. Go back and ask what the thing actually is.

**The measurement this came from.** One population — the `path:NN` anchors in a
findings corpus — was attacked six times over two months. Not one round failed because
its fix did not work. Every round failed because the problem was framed wrong, and each
for a fresh reason: the guard swept two docs while the rot ran free elsewhere; the
regex had never matched anything, so the count had always been zero and nothing was
looking; the allowlist key drifted and got bumped (which the ledger itself called "a
patch, not a fix"); a second registry carried the same drift in a different file; the
citation *form* turned out to be the problem rather than the guard; and finally two of
the four populations were not defects at all — one was an append-only log aging
normally.

**Attempt count alone discriminates nothing**, which is why "we have looked at this
three times" is not evidence either way. Some real defects are simply expensive. Read
the *variety* of the failures, not their number.

**The corollary that costs the most to learn.** Searching harder does not fix a
mis-specification — it produces one more careful measurement of the wrong thing. The
sixth pass above measured more precisely than the first five and would have reached the
same wrong conclusion, because the question ("how many are broken?") had a tool behind
it while the question that mattered ("what is this surface *for*?") did not. Prefer a
different first question over a deeper search. See root `CLAUDE.md` Core Rule 13 and
[`../memory/classify-the-surface-before-measuring-it.md`](../memory/classify-the-surface-before-measuring-it.md).

**Origin: the operator, 2026-08-09**, watching the sixth round land — *"maybe that
means a 'sign' of that is a repeated attempt at a fix that is invalidated in different
ways each time."* Recorded with attribution because the diagnostic arrived from outside
the loop that kept failing, which is itself part of the lesson.

---

## 16. Name the user, or it is not a defect yet

Before a finding earns any work, answer in one sentence: **who gets hurt, and what
were they doing?** *"Someone runs the documented uninstall and every later tool call
errors on a script it deleted"* qualifies. *"Two registries disagree about a
classification"* does not — not yet. If the sentence cannot be written, the finding is
recorded and the session moves on. It is not argued about, not scoped, not packed.

**Latent is not urgent, and the two are easy to confuse** because both are real. A
mechanism that *would* fail is a fact about the code; a user who *does* fail is a fact
about the product. Only the second sets priority. Everything else is a fact you are
allowed to write down and leave.

**Find the handler that terminates the path before you price the harm.** The
"who gets hurt" sentence is a claim about what reaches a user, and a catch-all one
layer up can falsify it without touching the mechanism. Attested 2026-09-17 on
`DEF-835`: the row's sentence was *the adopter's banner or command dies on a
code-page file*, and it was wrong in both halves. `espalier/cli.py::main` catches
`(json.JSONDecodeError, ValueError)` for the entire engine surface and a
`UnicodeDecodeError` **is** a `ValueError`, so no engine command could produce the
traceback the row described; and all three callers of the one genuine file-reading
hook helper name the decode error explicitly, so the hook surface — the surface the
original defect actually bit — was clean. The mechanism was real and stayed real; the
harm sentence was not. What the trace did surface was a defect the row had not
raised, and the only one an adopter would ever see: the catch-all's message names no
file. Two consequences worth keeping. Trace one path to its terminating handler
before writing the sentence, and write down which handler it was, so the next reader
can check it rather than re-derive it. And when the catch-all turns out to hold, read
what it *prints* — a handled error with a useless message is a real defect hiding
behind a correct one.

**What this corrects.** §§1, 3, 5, 7, 8, 9, 14 and Core Rules 12 and 13 all amplify —
they widen scope, raise suspicion, demand more proof. Every one was learned from a
quality failure and every one is right. But a ruleset whose every member says *dig
deeper* has no brake, and applied to a self-referential codebase — scanners that scan
themselves, registries about registries — it will return findings forever. §5 is the
matching half and is often misread: *"the null result is the signal"* means a clean
pass is **evidence**, not permission to re-point the instrument at a fresh corner.

**The failure that produced this.** One session opened by executing a pack against a
guard whose population was narrower than its subject. Four review rounds, ~735k agent
tokens, four genuine corrections, one new defect class, four new gaps — and zero lines
of changed source. Every finding in it was real. **Not one had ever fired**, and none
was on the day-one list of twelve verified defects that a stranger hits on first
install. The reviews were correct; the target was not. Meanwhile the release did not
move.

**The operator's form of it, which is the version to keep:** *"I want to know how the
change affects the reality of the program."* State every fix as an outward change —
*this stops crashing when they do X*, *this stops silently dropping their files* — and
a fix with no outward change is a fix looking for a reason.

**Origin: the operator, 2026-08-11**, mid-session, watching the fourth review round
land on a pack that had not yet changed a line — *"the wheels are just spinning after
so much progress."* Recorded with attribution because, like §15, the diagnostic came
from outside the loop that was failing, which is again part of the lesson.

## 17. When the expensive net catches it, move the catch earlier — and sweep the class

A full suite that finds a real defect has done its job and revealed a gap in the same
breath. The defect is the visible half; the gap is that **nothing cheaper or earlier
saw it**, and cheap gates are the ones that actually get run. So a catch by the
expensive net is not a closed loop — it opens three questions, in order:

1. **Could something cheaper have caught this?** Measure both costs before answering.
   A 14-minute suite finding what a 2-second contract could have found means the
   contract exists and is not wired where the work happens.
2. **Could something *earlier* have caught it?** Position matters as much as price. A
   check that runs after the commit costs an amend; the same check before it costs
   nothing.
3. **What else is in this class?** One instance is a sample. The gate that fired names
   a category — a registration obligation, a shipping-surface rule, a paired literal —
   and the other members of that category are unguarded in the same way until swept.

**The same applies when a red team finds something a green suite missed.** Grade every
finding: *was this mechanically checkable?* If it was, the red team was doing work the
suite should own — slow, expensive, and non-repeating in place of fast, cheap and
permanent. Convert it to a test rather than patching the instance. Only the findings
that survive that grading — design judgement, a premise nobody stated — are what a red
team is actually for, and their number should fall as the net improves.

**A caution against the obvious over-correction.** Not everything belongs in the fast
gate. A cheap check is only cheap while it stays cheap, and a gate that grows until
nobody runs it has become the expensive net wearing a smaller name. Add a member when
it has *actually caught something*, state the new cost where the old one is claimed,
and let the trend in what the expensive net still finds tell you whether the net is
improving.

⚠ **Beware deriving the cheap gate's population from a single failure mode.** The first
version of this repo's post-handoff gate was assembled from the artifacts `/handoff`
writes last, so it caught every *content-drift* class and was blind to every
*registration* class — a new test file, a new pragma, a new derived population, a new
probe. Four of the nine gates that caught something real in the session that built it
were outside it, and they shared a category the selection could not see because the
selection had been derived from a different one. A gate's population needs the same
scrutiny as any other derived list (§14).

**Origin: the operator, 2026-09-01**, after a session in which eleven full-suite runs
each found something no targeted run could — *"if the expensive test catches something,
see if a cheaper gate or something earlier could catch it, and other in the/a similar
class."*


## 18. Fix the class in place; file only what needs its own oracle

You are sent to fix X. Doing it puts you inside Y, and Y is broken too. Two pulls
compete: fix it now while the context is loaded, or file it and keep the commit
scoped. The first version of this principle chose filing, and named the cost of the
other choice — a diff that answers two questions, a passenger fix nobody red-teamed,
a row held hostage by unscoped risk. Those costs are real, and they belong to a
*different question*. They do not belong to a sibling of the question you are already
answering, and the first version's title ("outside the blast radius") let a sibling be
filed as if it were one. Measured 2026-09-05: five rows were filed in one day, all from
review passes on a fix, and four of the five were siblings of the fix — same file,
same oracle, sized at ten to thirty lines. Each will cost a future session more to
reorient against than it cost to write, and one of them (a span class that folds a
trailing comment into the targets) was left fixed at the new site and open at five
older ones with a row pointing at them.

**The discriminator is the oracle, not the file.** A found defect is in-lane when the
lane's existing proof can prove the fix: the same test file, the same corpus, the same
probe. It is a row when proving it needs a proof of its own — a new population, a new
gate, a real install walk, a platform rule, an operator decision. Ask: *what would I
have to build to know this fix is right?* If the answer is "nothing I do not already
have running", it is not a row.

**The bar is the filing tax.** A row with driven evidence and a probe costs about
fifteen minutes to write, the next session about twenty to reorient and plan against,
and the strike with its probe retirement another ten: roughly forty-five minutes before
the fix is touched. A fix that passes the oracle test and is smaller than that is
strictly more work filed than fixed, at the same quality — the suite and the review pair
run over the widened diff exactly as they would over a scoped one. **If the fix is
shorter than the row, write the fix.** The rows already size themselves in lines;
nothing sized at "~15 LOC" should be one.

**A class is never patched one instance at a time.** Sibling sites are the same
question by construction. Fixing the site you tripped over and filing the rest is not
a scoped commit, it is a monkey patch with a ticket attached, and it is worse than
leaving the class alone: the patched site sets the example the next reader copies, the
row hides the class behind a single id, and the class fix — one tokenizer, one
predicate, one derived list — is usually smaller and better than the instance fix it
replaces. Core Rule 12 names the class as the unit of work; this is its consequence for
what you are allowed to leave behind. Sweep the siblings *before* the review, so the
reviewer verifies the class rather than discovers it. One question per commit, not one
site: the commit stays reviewable because the class is one idea.

**The one thing an in-lane fix must not skip.** A fix landed after the last review pass
has had no independent eyes. Land it as that reviewer prescribed it, or it earns one
more pass; the widened diff is reviewed exactly as the narrow one would have been. What
made the 2026-09-02 case below expensive was not that a second component was fixed in
place — it was that two gates for it shipped born-weak (§19) with nobody asked to
attack them.

**What remains a row, with the measured case.** A defect in a *different component*,
reached by tripping rather than by reading, that needs its own proof. 2026-09-02: a
session scoped to one ledger row — propagate a ratified decision into a publish runbook —
re-pointed that row's probe, and re-pointing it revealed the probe *runner* was
non-deterministic: the same probe printed 5, then 3, with no change to the code it
measures. A real defect, a different oracle (the runner's, not the row's), fixed in
place anyway: **668 of the commit's 1,368 changed lines** belonged to a component the
task never named, and catching its born-weak gates cost an adversarial round the scoped
work did not need. That is the shape this principle files. A sibling regex in the file
you are already editing is not.

**Origin: the operator, 2026-09-02**, reading a session that spent six hours and struck
a single row — *"That seemed like a lot of work, a long time for a few rows, not even a
full class fix"* — and **2026-09-05**, reading a day that closed as many rows as it
filed: *"if we just hand patched a single instance of a class, leaving, even with ledger
rows filed, is not only a waste but dangerous. The 'real' class fix would be better than
the monkeypatch."*

## 19. Name the mutation before you write the gate

A gate is a claim: *this condition cannot pass unnoticed.* A green test is not evidence
for that claim. It is evidence that the code returns the right answer on the input you
happened to give it — which is also what a gate that can never fire returns.

**So state the mutation first.** Before writing the check, write down the specific edit
to the component that must turn it red. If you cannot name that edit, you do not have a
gate yet; you have a function that agrees with you today.

This is §7 with the ordering repaired. §7 says prove it reds. §19 says decide *what*
must red **before** the thing exists, because a mutation invented afterwards is chosen
from the set of mutations the test already catches. That set is never empty, and it is
often much smaller than the class the gate's docstring claims.

⚠ **The specific trap: mutate the COMPONENT, not the fixture.** A gate's tests usually
reach the component through a seam — a monkeypatched constant, an injected literal, a
tmp fixture. Mutations aimed at that seam prove the seam works. The derivation behind it
can be deleted outright and every one of them stays green.

⚠ **MEASURED, 2026-09-02, twice in one session, both while fixing a fail-open probe.**
A contamination detector shipped with six tests, all of which monkeypatched the
population to a literal; replacing the whole derivation with `return {}` — so the gate
could never fire, for any tree, ever — left the module **28/28 green**. In the same
batch a ratchet claimed "no new one can be authored blind" while recognising three
spellings of a shape with at least seven: it saw **30 of 131** live instances and missed
101, and its own fixture was satisfied by four separate wrong classifiers, including a
constant. Both were caught by an adversarial pass, not by the suite that had just gone
green over them.

**A caution against the obvious over-correction.** One honest mutation beats four that
all strike the same branch — a mutation count is not a coverage measure. And a gate
whose mutation you can name but never actually drive is still an assertion about the
future; drive it once, in situ, and record what it printed.

**Origin: the operator, 2026-09-02** — *"Write a new gate's mutation test before the
gate. If I can't state the mutation that reds it, I don't have a gate yet."*
