# Fix the class, not the instance

**Status:** active
**Linked from:** root `CLAUDE.md` Core Rule 12 · `docs/STANDING_PRINCIPLES.md` §8 ·
                 [[sister-site-compression]] · [[premise-check-before-authoring-a-fix]]

Before authoring any fix, ask one question: **is this defect one site of a class?**
If it is, the unit of work is the class, not the site. Fixing the site and moving on
is how a class stays open — and an open class is re-found by the next review as new
work, at full price.

This sits **upstream of `STANDING_PRINCIPLES` §8**. §8 tells you how to *scope* a
class-fix once you know you have one ("the roadmap's site count is a floor —
AST-enumerate the real surface"). It assumes the classification already happened.
This entry is the trigger that makes it happen: §8 is the *how*, this is the *when*.

## The tell

You are fixing an instance when the work is described by a **site** — `foo.py:412`,
"this deny message", "the count in the README". You are fixing a class when the work
is described by a **mechanism** — "a hand-kept set standing in for a derived one",
"a guard whose skip condition cannot fire".

A one-line test that works: *would the fix you are about to write close the second
occurrence if you found one?* If not, you are writing a bandaid.

## A lone instance patch is worse than no patch

Once the class is named, the one thing you may not leave behind is a fix at the site
you tripped over with the siblings filed as rows. Sibling sites are the same question
by construction: the patched site becomes the example the next reader copies, the row
hides the class behind one id, and the class fix (one tokenizer, one predicate, one
derived list) is usually smaller and better than the instance fix it would replace.
Sweep the siblings before the review, so the reviewer verifies the class instead of
discovering it. What may be filed is a *different* question — one that needs its own
oracle — never the remaining members. The bar and the measured cases are
`docs/STANDING_PRINCIPLES.md` §18 (2026-09-05: four of five rows filed in one day were
siblings of the fix under review, sized at ten to thirty lines).

## Then check whether the class is already known

Once the answer is "this is a class", the very next step is **not** to name a new
one. Read the ledger's existing class table first: *"no class covers this"* is an
unverified claim, exactly like *"no store serves this role"* in
[grep-for-a-sibling-store-before-building-a-rival](grep-for-a-sibling-store-before-building-a-rival.md)
— same shape, different object (a taxonomy entry rather than a durable store).

Evidenced twice, in consecutive sessions. A morning went into "discovering" a
class the ledger's §C13 already held, with the root cause stated exactly right
(*"the uninstaller's list is not derived from the installer's"*) and its one-fix
still open. The two findings from that session also landed in **existing** classes;
neither needed a new one. The next session's two findings did the same.

Three practical consequences:

1. **Grep the class table before writing a class description.** A fresh
   description of a known class reads as new work and buys a second full analysis
   at full price.
2. **An open class member is not the same as an open class.** §C13 had one member
   closed and read as progress; its actual one-fix — derive the uninstall inventory
   *from* the install inventory — had not been touched. Check what the class's own
   stated fix is, not just whether some member is struck.
3. **A defect can carry two rows** — a launch-gate row and a root-cause class row.
   Strike both, or the closed work re-surfaces from the row you missed.

This runs *before* the scoping in `docs/STANDING_PRINCIPLES.md` §8: there is no
point AST-enumerating a class's surface if the class already has a table entry
naming a broader fix than the one you are about to scope.

## The mechanical oracle

`tools/cc/sister_site_probe.py` is the answer to "are there sibling sites?" — a
clique detector over function bodies and module-level constants. Run it rather than
eyeballing:

```bash
python3 tools/cc/sister_site_probe.py --json
```

It is wired into `/implement-pack` step 0-C, so pack execution already sweeps.

**Do not mistake it for a general class-detector — its reach was measured, and it is
narrow** (and scope-dependent: an adopter tree gets its own source roots as the
gating scope, the harness's source tree gets hooks + top-level engine — the SCOPE
block names which). What it scans and how it hashes is [[sister-site-compression]]'s *Probe operator
notes*; that is the sole home, and this entry deliberately does not restate it. What
belongs here is the consequence for the class question — three blind spots, structural
and not tunable:

- it hashes **whole function bodies**, so a repeated *statement* is invisible — and so
  are two instances of one bug inside a single function (`§C21` is exactly this: both
  members live in `plan_fusion`);
- its scan set is two directories, so duplication anywhere else is out of reach;
- it cannot see an **absence** — and several classes *are* an absence (`§C23` is a
  missing member of a hand-listed tuple).

Scored against the 25 live classes it reaches **≈0, with 2 partial**. Provenance, because
this figure is load-bearing: it comes from a single dispatched analysis, of which two
classes (`§C21`, `§C23`) were independently re-verified against live code and the
remaining 23 were not. Treat it as *"narrow enough not to rely on"* — which is all the
decision needed — rather than as a re-derived measurement.

So the probe answers "did I duplicate a body?", not "is this defect a class?". For the
classes this repo actually has — a hand-kept set standing in for a derived one, a fact
restated in prose, a guard that cannot fail — **grep the literal and read `§C1`–`§C25`
in the forward ledger**, which already names each class's one fix. A 2026-08-06 draft
(TP-425, retired) proposed firing this probe on every write; the measurement above is
why it was not built. See [[a-packs-prescribed-fix-code-is-a-claim]].

## Why it costs more than it looks

Measured on this repo, 2026-08-05: **all but 12 of the live backlog issues fell into 25
mechanism classes** (`§C0` holds the standalone remainder; `task-packs/FORWARD_LEDGER.md`
§2 is the source of record and sums itself). The backlog was not large because the project
had many separate problems. It was large because ~25 classes had been closed one instance
at a time, and each unclosed class kept regenerating rows.

*(This paragraph has been wrong twice. It first read "225 of 233 … only 11 standalone";
the tables sum to 221 and 12. The correction fixed those two and left a third transcribed
figure — "351 distinct issues" against a source of record that says 355 — **wrong in the
same sentence**, in the commit whose stated method was "sum the tables mechanically instead
of quoting a transcribed number." So the counts are now stated in the one form that
carries the argument and the exact figures are left where they are derived. Deleting the
transcription surface is the class-fix; re-correcting the value was the instance-fix, and
it is what failed the first time. `§C1`/`§C2`.)*

The convergence ledger records the same shape from the other direction:
enumeration-integrity was the arc's longest-running unclosed class at **five rounds**.
Every round found new instances; no round closed the mechanism.

## The trap that makes this hard

A class-fix that lands is not the same as a class that is closed. Two recorded
failure shapes:

1. **The fix reaches fewer members than the class claims.** State explicitly what the
   class-fix does *not* reach, per member — and mark those members, so a later pass
   cannot read the class as shut. A "does not reach" note that names no ids joins to
   nothing and is prose, not a mechanism.
2. **The remediation becomes the next class.** Round 8's fix for the PEP 668 gap was
   the direct cause of round 9's interpreter blocker; every one of round 9's four
   blockers sat on code that landed *after* round 7's green call. Verification
   machinery is the highest-defect subject in this repo — when the deliverable is the
   gate, "the suite is green" is circular evidence.

## What to do when you find a class mid-fix

Do not silently widen the current change. Record the class, name its members, and say
which the current fix reaches. A class discovered and left unstated is worse than one
never found — the next reader believes the surface was swept.

## The strongest trigger is "I just wrote the helper for this"

Core Rule 12 reads like a review-time question. It is not — it fires at **authoring
time**, and the sharpest cue is the one that feels like completion: *you have just
written a general fix for a general problem.* That is the moment the class is most
clearly in view and least likely to be swept, because the site in front of you now
passes and the work feels done.

Measured twice in a single session (2026-08-13), both caught only by the adversarial
pass on a fully green suite:

1. `_flatten_ws` was written *because* a substring scan over wrapped prose was
   diagnosed as a class — then applied to the new check only. `_check_security_policy`
   sat **130 lines up in the same file, scanning the same document**, with phrases up
   to 40 characters. A policy genuinely routing vulnerabilities to public issues
   measured **0 failures wrapped, 1 flat**. The higher-stakes scanner was the one left
   raw.
2. The conditional-GOAL fix reached `session_start` and left the identical
   unconditional instruction in `task_router`'s cold-open directive (a hook with **zero**
   self-host gates, so it ships to every adopter), in `context-load.md`, and in a second
   `docs/HOOKS.md` paragraph. Before the fix the two hooks were *consistently* wrong;
   after it they **contradicted each other inside one session**, which is worse.

**The mechanical check, in order** — do it before the commit, not at review:

1. Grep the helper's **own file** first. Both misses above had a sibling in the same
   module or the same subsystem; the nearest sibling is the likeliest and the easiest
   to miss precisely because you are already "in" that file.
2. Then every caller that reads the **same input** — same document, same event, same
   config — not merely every caller of the helper.
3. `python3 tools/cc/sister_site_probe.py --json` is still the name-keyed oracle, so an
   `rc=0` is **not** an absence proof for a *behavioural* class like this one. Neither
   miss above was name-keyed; both were found by asking "what else reads this?"

Related: [[classify-the-surface-before-measuring-it]], and the inverse-direction
sibling — an exemption or narrowing added to close a defect can re-blind the gate to
that defect's own recurrence, so after any fix ask both *can X now claim less?* and
*does my new exemption excuse the site I verified, or the whole pair?*

## A tracker row count is the class's lower bound, never its census

The section above answers *"is this class already known?"*. This one answers the
question after it: **once the ledger names a class, how many members does it
have?** The row count is the answer to *"how many did somebody write down"*, and
those are two different numbers.

**Attested (2026-08-16).** A ledger class named **two** major members in one
module. Driving the actual mechanism — rather than reading the rows — found
**six** in that module, and an adversarial pass then found a **seventh in a
different module entirely**. The four unledgered members were not obscure:

- one fired on a path reachable **without** maintenance mode, making it the most
  reachable member of the whole class while the two ledgered ones needed it;
- one matched a **bare basename**, so it fired on five unrelated files, and only
  an unrelated content gate had kept the blast radius small;
- one named the destroying command with no warning attached;
- the seventh lived on a **second producer** of the same advice, which a sibling
  test in the very same test class already described as *"the second advisory
  surface"*.

**The operative move: enumerate the producers, not the sites.** A class is a
*mechanism*, and a mechanism has a small number of places that emit it. Ask "what
else generates this kind of statement?" and sweep each one, reporting the clean
ones by name — an unswept producer and a clean producer are indistinguishable in
a report that only lists findings. Fixing one producer and not the other is how a
class comes back wearing a new row number.

**Corollary for the ledger.** After closing a class, the count you strike and the
count you found will differ. Record the members you found that had no row, or the
next pass re-derives them at full price — and its author will trust the row count
again, because it will once again look complete.

Kin: `docs/FAILURE_MODES.md` §13.34 (a floor that counts the population cannot
see a member that stopped keying) and
[[a-gate-can-be-blind-along-a-whole-dimension]] — in all three the number looks
like coverage and is not.

## When the class fix reaches for a better oracle

A class fix often needs a stronger test than the one the buggy site used. Before
substituting one oracle for another, drive both across the same tree set and read
the matrix: "catches something the other misses" is equally consistent with
*strictly stronger* and with *complementary*, and those have opposite correct
actions. Attested 2026-08-27, where substituting would have reopened the very
defect the class fix was closing — [[a-second-oracle-may-be-complementary-not-stronger]].

## The fix you just wrote is a site of the class

Attested 2026-08-27 (`56dc018`), four instances in one block and three of them
found only by review — of the fix, not of the original defect. The class was
"a claim the command does not keep": the post-init banner narrated every unwired
governance gate with one shape's prose. The dispatch that fixed it then (1)
dropped an *unhandled* shape silently, rendering `Hooks are NOT yet active: .`
with the gate gone from the output; (2) offered `merge-settings` on files the
merge refuses whole; (3) omitted two shapes from its own "this does NOT fix X"
caveat; and (4) left the sister surface's step with no caveat at all.

**So after writing a class fix, attack it with the question that produced it.**
The fix is new code that makes claims about a population — which is the exact
shape you just spent the session proving is easy to get wrong. Reviewing it for
*correctness* will not surface this; reviewing it as a fresh instance of the
class will.

**Prefer the gate that fires when the next member is BORN.** The graceful
degradation arm added here (an unknown shape gets a vague-but-honest clause
instead of vanishing) converts silent loss into loud contradiction — a real
improvement, and not a foreclosure: it fires only when someone happens to build
a tree carrying the new shape. What forecloses the next round is
`harness_config.GATE_SHAPES` plus a roster pin that reds the moment a fifth
shape constant is written, while its author is still looking. A gate sited at
authoring time beats a gate sited at trigger time, because the trigger may not
arrive for months and the author is gone by then.

Kin: [[a-gate-can-be-blind-along-a-whole-dimension]] and
`docs/STANDING_PRINCIPLES.md` §8 (class-fix scope is every shipped surface —
which is how sites (2) and (4) above were found, on surfaces the original
defect never touched).

Downstream half: [[a-class-one-fix-is-a-claim]]. This note decides the *unit* of
work; that one tests the *prescription* — a class's stated "one fix" is itself a
claim, and driving §C9's showed it bundled four independent changes, three of
them not parsing problems at all. Read them as a pair: deciding to fix the class
does not tell you that the named fix closes it.

**2026-09-11, the copies a doc sweep cannot see (§C20).** A shipped sentence's
class lives in code as well as docs. The seed banner's "never overwritten on
re-init" had six copies across the banner, two stubs, a generated bullet, a
skill quotation and a gloss, and two more in deployed code: a comment in
`tools/cc/reflect_protocol.py` and the rationale that keeps a hook's
placeholder-body history append-only. Both vendored mirrors carried the stale
copies in parity, so `sync_vendor_cc --check` was green over the drift, and a
hand-listed absence test over five paths missed both; the reviewers found them.
Sweep a sentence class over every tracked `*.md` and `*.py` through the suite's
git oracle with the record surfaces excluded, and expect a byte-mirror to agree
with a stale source rather than flag it.

**2026-09-11, the sweep that stops at the folders it knows (§C17, DEF-348a).**
A rename swept over `espalier/ tools/ scripts/ tests/` missed five sites in
`bench/run_benchmark.py`, behind a try/except that scored the release-gating
arm as not blocked with a reason blaming the install; both reviewers found
it. Sweep a class over the tracked tree (`git ls-files '*.py'` through the
suite's git oracle) and turn the plan's constraint sentence into an assert in
the same lane: a sentence nobody runs is not a sweep. The sibling, driven the
same day: a census that exempts by (module, function) is blind to a second
write added inside an exempt function; key the roster with a count, so an
exemption says how many as well as where.

**2026-09-12, the class narrower than its population (DEF-410f).** Three
shapes of the same miss in one lane, each found by a reviewer after the fix
was green. A content-keyed contract -- "the docs cue needs an adopter-owned
file" -- was defeated by a platform artifact: Finder's `.DS_Store` in the
seeded `docs/` re-earned the cue, the signal and the conventions. A census
keyed on a parameter NAME (`repo_root`) and on the one spelling it parsed
(`repo_root / "x"`) was silent, not red, on `joinpath`, `Path(root, ...)`,
`os.path.*` and a detector that called its root anything else; make the
unresolvable case loud (`<unresolved>` is a finding) and pin that every
prober names the root. A comment in a test that is byte-mirrored into the
shipped selfcheck subset is a shipping surface: one `TP-` tag in
`tests/test_analyze.py` redded the provenance census through
`espalier/_vendor/selfcheck_tests/`. The sibling, driven the same day: the
sister site the sweep did not name (`strengthen._EXEMPT_PREFIXES`) reported
395 harness symbols and none of the adopter's, and needed only a self-host
fork, not its own oracle -- drive the sibling before deciding it is a row.

**2026-09-13, DEF-509 (a relative Bash write judged against the root).** The
row named one site, a leading `cd`; the class question found three members and
a sister reader: the payload `cwd` the hook never read (Claude Code moves it on
an earlier call's `cd`), the `cd` inside the command, the PowerShell
`Set-Location` twin -- and `post_write_check`, which resolves the same
extractor's output root-relative and would have gone quiet for exactly the
writes the guard learned to see. All four landed through one resolver keyword
(`base=`) and one chain, with the .NET file API's process-directory exemption
driven in pwsh. The deliberate exclusion, the rm hard tier and the friction
bumps still reading a relative operand against the root, was filed as its own
row (DEF-790) because its classifier has its own oracle -- §18's line between
an in-lane sibling and a row.

**2026-09-14, the sweep's blind spots are the net's too (DEF-792).** An
AST-positioned rewrite pinned `encoding="utf-8"` at 816 sites, and the scanner
written beside it read the same shapes from the same model, so both were blind
the same way: a positional `read_text("utf-8")` read as missing and was doubled
into a runtime `TypeError`, and the module under `import subprocess as _sub`
was missed twice -- the 1,527-test targeted proof green on both (the doubled
call sat in a file it did not include), both found by the reviewers on the
whole diff. When one lane ships the sweep AND the net that forecloses its
class, enumerate the argument positions and import aliases the sweep could not
resolve and drive the net at those shapes first: a shape neither recognises
reads as a clean tree.
