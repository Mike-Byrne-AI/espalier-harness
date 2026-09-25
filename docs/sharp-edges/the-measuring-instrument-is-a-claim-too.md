# The measuring instrument is a claim too

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "The Measuring Instrument Is a Claim Too"

**What it is:** To answer a question about the codebase you write a probe — a shell
pipeline, a throwaway script, a `find | wc -l`. The probe is **code you wrote seconds ago
and have never tested**, and it is the only thing standing between you and a number you
are about to believe. When it is wrong it does not crash: it produces a plausible figure,
usually a **low or zero** one, and a low number reads as *clean* and ends the
investigation.

**Why it is a distinct trap from its sibling.**
[`source-tree-is-not-an-artifact-oracle.md`](source-tree-is-not-an-artifact-oracle.md)
covers *correct code answering the wrong question* — its own framing is explicit that
"the proxy is not broken; `grep -c` really did count." This entry is the other half:
**incorrect code answering the right question.** You aimed at the right artifact and the
instrument misread it. Both hand you a confident number; neither looks wrong.

**Class signature:** *the probe is unverified, and its failure mode is a plausible null.*

## Attested instances

| The probe | What it reported | What was actually true |
|---|---|---|
| Extract an archive to a temp dir, then count dangling links inside it | **0 dangling** | The extract step had failed (wrong working directory), so the probe walked an **empty directory**. Zero files in, zero findings out. |
| Regex every markdown link out of a docs tree and resolve each one | 2 broken links | Both sat **inside fenced code blocks** — worked examples showing the link *format*. A link in a fence renders as literal text and can never break. |
| Enumerate quoted output blocks to audit them against live behaviour | A doc was "missing a disclaimer its siblings carry" | The enumerator printed only *fenced block contents*, not the prose around them. The disclaimer was there, one line above the fence, and more thorough than the siblings'. |

Three instruments, one unit of work, three different failure modes — a silent upstream
failure, a parsing rule that ignored the format's semantics, and a display that hid its
own input. **Two of the three pushed toward a conclusion more interesting than the
truth**, which is exactly when scrutiny is weakest.

## How to avoid it

**Assert a population floor inside the probe, before you read its answer.** This is the
highest-value habit here, because it converts the dangerous failure — a confident null —
into a loud one:

```python
members = collect(root)
assert len(members) > 500, f"population floor: only {len(members)} -- did the extract fail?"

resolved = 0
# ... walk, resolve, accumulate violations ...
assert resolved >= 100, f"only {resolved} references resolved -- the extractor is broken"
assert not violations, violations
```

Order matters: check the floor **first**. A gate that passes because it found nothing to
check is not a gate.

**Make the probe find something you already know is there.** Before believing a null,
feed the instrument a case that must trip it. If you cannot make it fire on demand you
have not verified it — you have only run it.

**Check the pipeline's exit status, not just its output.** A step that fails upstream (a
bad path, a missing directory, a command run from the wrong place) yields empty input,
and empty input is indistinguishable from a clean result downstream.

**Respect the format's semantics.** Fenced code blocks, comments, string literals and
templated placeholders all look like content to a naive regex. If the probe parses a
structured format it must know what that format means, or it will count decoration as
data — and it will also *hide* real content that sits outside the shape it looks for.

**Suspect the instrument hardest when its answer is convenient.** A number that confirms
what you already argued deserves the re-run more than one that contradicts you.

## Two instances where the *arrangement* was the wrong instrument

Both produced confident, wrong answers while every individual command was correct — the
instrument was the composition, not the code.

**A pipe replaces the exit code you meant to read.** `pytest -q 2>&1 | tail -5` reports
**`tail`'s** status, not pytest's. A suite with failures exits non-zero; pipe it and the
shell reports `0`, so "exit code 0" attests only that `tail` succeeded. The same pipe
discards the tracebacks, so the log cannot even diagnose itself afterwards. Redirect to a
file and read `$?`. Note that the obvious repair is *also* dialect-specific:
`${PIPESTATUS[0]}` is a bash-ism and evaluates to empty under zsh, which spells it
`$pipestatus[1]` — a fix that silently produces nothing is the same failure one layer up.

**Concurrency makes two honest suites lie to each other.** A full suite left running in
the background while review agents are dispatched is not an isolated measurement: those
agents run their *own* suites, and one may `git stash` the working tree mid-run. Measured
once: that contention produced seven `write_guard` errors in one run and two failures plus
three errors in another, **none of which reproduce serially** — the same module passed
408/408 in seventeen seconds alone. Both readers were one step from recording a regression
that did not exist, and one had already started reasoning about its "root cause". Treat a
red observed under concurrency as *unmeasured*, re-run it alone, and do not dispatch a
review while a suite is in flight on the same tree.

The generalisation: when a result surprises you, suspect the **arrangement** — pipes,
parallelism, shared state, shell dialect — before the code under test. An instrument can
be composed entirely of correct parts and still be wrong.

## A docstring that names another test as your backstop

The instrument need not be code. A test docstring that says *"this gap is covered
one layer up by X"* is a claim of exactly the kind this entry is about, and it is
believed more readily than a claim in prose because it sits inside a green test.

Attested 2026-08-12. A generated doc region carried a deliberately permissive
floor, and its guard's docstring justified the permissiveness by naming two exact
population pins elsewhere as the real backstop. One of the two existed. The other
did not — and the half that did not was the half covering **17 of the 40 derived
items**. Deleting a single line from that unpinned inventory silently changed two
shipped documents from *"3 files"* to *"2 files"* while the full suite reported
**8023 passed, zero failures**. Every consumer read the same constant on both
sides of its assertion, so the population narrowed everywhere at once and nothing
was left to disagree.

The docstring had been written in the same session, by the same author, in good
faith, about tests in the same directory. Proximity is not verification. **Open
the test you are citing, or do not cite it** — and if it does not exist yet,
writing the citation is how it stops being written.

## The instrument fails toward the conclusion you are already forming

Five more instances, 2026-08-17, all in one session and all driven. What makes them
worth adding is not the count — it is that **every one erred in the direction of the
answer being assembled at the time**, which is why re-reading the probe never catches it:

- **A sampler handed the subject the wrong shape of input.** Probing whether a denylist
  covered a set of patterns, it passed bare directory names (`.pytest_cache`) instead of
  paths *inside* them (`.pytest_cache/x.txt`), and reported 29 of 47 covered when the
  truth was 42. The under-count would have justified a much heavier fix — more work, in
  the direction the author was leaning.
- **A regex-only probe reported six open bypasses that a driven hook denies.** The
  extraction pattern genuinely stopped matching, but a spelling-independent backstop one
  call downstream still refused every spelling. A false BLOCKER, one step from shipping.
- **A hand-assembled "every plausible consumer" file list under-counted the real pin set
  by 25%.** Nineteen files chosen by grep; the full suite found twelve reds where the
  sweep found nine. A consumer list assembled by search **is itself a derived population**
  — it shrinks to whatever the author thought to look for, and reports silence for the
  rest.
- **A stale `.pyc` in a scratch tree reported GREEN.** Re-driven with `__pycache__`
  cleared and `PYTHONDONTWRITEBYTECODE=1`, the same mutation red.
- **A timing claim survived two bad measurements in a row.** A wall-clock probe said an
  operation had regressed 12×; a second probe written specifically to rule out CPU
  starvation was itself run *inside* that starvation. Even `process_time()` was inflated,
  because cache thrash and context-switch overhead charge to the process. Load average
  was 43 on 8 cores. Measured quiet, the operation took 178 ms against a documented
  ~130 ms — i.e. fine, after a stale-margin finding had already been reported to the
  operator and withdrawn.

**Two rules fall out, both cheap:**

- **Timing:** check the load average *before* trusting any duration. A busy machine
  inflates wall-clock and CPU time alike, so no single clock discriminates — only a quiet
  re-run does. A gate that reds for load rather than truth is one the reader learns to
  skip, and a skipped gate still reads as enforcement.
- **Coverage:** to prove something is unpinned, drive the **full suite**, never a
  hand-picked slice. "Green across N tests" is a claim about the slice, not the repo, and
  the slice was chosen by the same person forming the conclusion.

## Receipts

Recorded 2026-08-01; extended 2026-08-17. All three instruments above were written during a single unit of
work; each was corrected only after its output was cross-checked against the artifact by
hand. The population-floor assertion is now compiled into the two link-resolution gates
that shipped from that work, both of which check a resolved-reference floor before
asserting on violations. This entry is the probe-level companion to
[`docs/STANDING_PRINCIPLES.md`](../STANDING_PRINCIPLES.md) §3 — *a finding is a claim
until grep-verified* — taken one level further down: **the tool that produced the finding
is a claim as well.**
