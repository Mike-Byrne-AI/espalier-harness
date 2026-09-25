# Standing principles — retrieval aliases

Machine-facing companion to [`STANDING_PRINCIPLES.md`](STANDING_PRINCIPLES.md). Every
phrase here is folded into its principle's token bag at corpus-load time by
`tools/cc/hooks/_recall.py`; none of it is meant to be read as prose.

**Why this file exists.** `/recall` is lexical — a query scores against the words a
document actually contains. A developer describing the situation they are in shares
almost no vocabulary with the principle that answers it: measured on a blind-authored
arm, a four-word "it passes here" complaint and *12. A gate is proven only on a tree it
was not written on* have no content word in common. (⚠ This paragraph used to QUOTE that
query. This file is the brief every blind alias author is handed, so the quote was an open
channel from the held-out arm into the aliases; the row it named was deleted from the
fixture under the fixture's own rule on 2026-09-04, and `tests/test_recall.py` now reds
if any alias line contains, or near-duplicates, a held-out or scored query.) This is the
vocabulary problem (Furnas et al.,
CACM 1987), and the standard remedy is document expansion — give the document the
words people search with. Keeping those words HERE rather than in the principles doc
is deliberate: that doc's job is to be read by a person, this file's job is to be read
by a tokenizer, and merging them degrades the first to serve the second.

**⚠ The discipline that makes the measurement mean anything, and it is easy to
destroy.** These phrases were written by an author that had never seen the evaluation
queries, and the evaluation queries by an author that had never seen these phrases.
Neither could open `tests/`. That independence is the entire reason the reported gain
is credible — an alias written after seeing a query it fails is training on the test
set, and the number stops measuring retrieval and starts measuring memorisation. It
happened during authoring and was caught: a self-scored probe set went 15/48 to 31/48
once its author saw which probes missed, and roughly thirteen of those sixteen gains
were worthless. **If you add an alias because a specific query missed, say so in the
commit — that query is now spent and must leave the benchmark.**

**Measured at adoption** (blind held-out arm, `recall_union(top=2)`): uncontested rows
9/24 → 12/24, all 48 rows 15/48 → 23/48 (+10 gained, −2 regressed). Every guard
unchanged: naming(any) 262/274, element 0 233/274, off-topic leak 29, calibration
top-1 0.850. Both authors read the same source document, so treat the magnitude as an
upper bound on what a stranger's phrasing would get — direction, not magnitude.

**Second blind round, 2026-09-04** — the same protocol, run again: a fresh author was given this file and the principles doc, forbidden everything else, and asked afterwards to list every file it opened (two). It wrote 219 lines across all nineteen principles. Before any of them touched this file the round was judged on the held-out arm at `recall_union(top=2)`: uncontested **13/24 → 16/24**, none lost; contested 12/24 → 12/24 (three gained, three lost). Guards unchanged: heading@1 84.4%, heading union@any 95.9%, stripped@1 83.3%, off-topic leak 29, must-answer 0 silenced, must-rank 0 wrong. **One guard failed on the full set and was repaired by a rule, not by hand:** three principles stopped winning a query made of their own title — §7's fifth line carried `make` and tied §1's two-word title (the tie then falls to the source-string tie-break), §7's own title fell below a SHARP_EDGES entry that cites it once its block passed four lines, and §13's block tipped a same-titled `memory/` twin sitting 1.4% away. The rule, fixed before any held-out number was read at it: per-block prefix caps in the author's order, extended one block at a time in principle order while every principle still wins its own name. Result: §7 keeps 4 of its 11 lines, §13 keeps 10 of 12, every other block is whole — 210 lines — and the held-out result at that configuration is the same 16/24 with the same three rows gained. **Cost, recorded rather than tuned away:** one two-token stripped heading query for §16 left the front door's four (stripped union@any 93.2% → 92.8%), and on the scored 16-row arm §16 lost one paraphrase while §7 and §13 each gained one — §16 is one of nine blocks that took all twelve lines and, its author said unprompted, the most diffuse (the section's honest symptom is a stall, not a mechanism). The next round should give §16 fewer, sharper lines, not more; pruning them now, having seen which queries moved, would be tuning against the benchmark. No held-out row was seen by the author. **Two checks on that claim, run after the adversarial pass asked for them:** (1) §7's four new lines paraphrase a §7 held-out row closely (token overlap 0.31, the highest of any alias-row pair) — both authors read §7's own case study, which is convergence, not copying — and an A/B with those four lines removed leaves the uncontested set byte-identical at 16/24, so they bought none of the gain (on the unscored contested arm they are worth one row: 11 with them, 12 without — recorded, since the contested pin stayed at 11); (2) this header used to quote a §12 held-out query verbatim, which made it an open channel whatever the author did with it — the row is deleted from the fixture and a containment/near-duplicate gate now guards every alias line against both arms. ⚠ The instrument that scored the capped set first merged it against a sidecar that already held the uncapped round, doubling every bag; that read was discarded and the base pinned to the pre-round file before the number above was taken.

**Editing.** One `## N. <title>` block per principle, titles byte-identical to the
live doc; `tests/test_recall.py` derives both sets and reds on any mismatch, so a
renamed or removed principle cannot silently orphan its aliases. Prefer ordinary words
the principle does not already contain — a word already in the section adds nothing to
a bag-of-words index and costs length normalisation.

## 1. Make it prove it

- took the model's word for it
- should I believe what it told me
- it said it passed but showed no run
- a confident answer with no receipts
- no evidence behind it
- shipping on vibes, not a demonstration
- convinced by an unproven statement
- no way to check the claim myself
- the assistant says done how do I know
- it assured me the migration succeeded
- the summary sounds right but nothing backs it up
- show me the run not the sentence about it
- a reassuring reply I cannot reproduce
- talk is cheap where is the log
- the bot swears it tested this
- accepted a fix because it sounded convincing
- demand a repro command not a paragraph
- reported the suite passing without ever executing it
- success announced with nothing attached

## 2. Toolbelt, not security boundary

- could an attacker exploit this
- a real vulnerability or a careless slip
- too paranoid about a hostile adversary
- hardening against accidents, not sabotage
- over-engineering a check nobody will attack
- annoying legitimate users to stop an unlikely attack
- how locked down does this have to be
- someone could get around this hook on purpose
- is this a cve or a footgun
- meant to catch typos not intruders
- do I need to defend against a malicious contributor
- how much circumvention resistance is worth it
- blocking honest work to close a loophole nobody uses
- an escape hatch is fine if it is deliberate
- protecting me from myself not from an enemy
- treating a convenience feature like a firewall
- the check is trivially defeated does that matter
- guardrail not a lock

## 3. A finding is a claim until grep-verified

- did the subagent hallucinate this file
- the cited line may not exist
- before I paste an agent citation somewhere permanent
- the reviewer overruled it without opening the file
- quoting a bot as though it were checked
- is the symbol sitting where the report puts it
- second-hand blockers nobody has seen
- the review points at a spot where no such function lives
- open the source before copying the path into the ledger
- a rebuttal that sounds careful but was never run
- is that filename real or invented
- a verdict I have not opened myself
- the number they gave does not match what is in the tree
- confirm the location before recording it anywhere durable
- the sweep flagged a bug in code that does not exist
- a rejection needs the same checking as the original
- transcribing an unread reference into a permanent record
- the path in the writeup points nowhere
- did anyone actually open the file they named

## 4. Verify tool output through an independent oracle

- the command printed nothing and I doubt it ran
- zero results returned, sanity check it
- a surprising total, confirm it another way
- the terminal claims success
- cached or lying output
- recount with a different command
- did it silently skip executing
- the notification said passed but the log shows failures
- the count looks wrong cross-check it with ls
- the screen shows an old version of the file
- I don't believe this number
- a status code that disagrees with what I see
- read it back with a different program before trusting it
- the background job reported finishing suspiciously fast
- the search found nothing is it looking at the right folder
- was the file actually written or just echoed
- a blank response that could mean success or nothing ran
- double-check with wc or cat before acting on it
- the summary line contradicts the body

## 5. The null result is the signal

- the audit came back clean, wasted effort?
- no bugs turned up, was it useless
- several quiet sweeps in a row
- when is it safe to stop auditing
- boring uneventful rounds are not a failure
- diminishing returns from one more review
- judging a sweep by how much it turns up
- the reviewers keep coming back empty-handed
- three independent looks found the same zero
- is an empty report good news or bad news
- another wide inspection turned up no showstoppers
- zero new items for the fourth time running
- should I be worried the checkers found so little
- the report is getting shorter each iteration
- a dry search means we are converging not failing
- weigh severity of what remains not how many
- keep going even though the last two turned up nil
- silence from the graders is information

## 6. Direction ≠ magnitude

- it feels faster but I never timed it
- I think it improved but never measured the gain
- sure it helps, no idea by how much
- no baseline numbers from before
- guessing at the improvement instead of measuring seconds
- how big is the difference
- a plausible speedup that was never benchmarked
- the change should reduce noise but by what percent
- a theory of why it works is not a delta
- quantify the win instead of describing it
- compare the old commit against the new one on real data
- it ought to be better where is the chart
- the story makes sense but the count barely moved
- merged and passing yet no figures from either side
- claiming a large uplift from a small sample
- sounds like it would help and that is all I have
- ran once saw a good number called it a win
- how much did token usage actually drop

## 7. Earn the red

- added the test after the fix, never watched it fail
- would it still pass if I deleted the patch
- prove the test catches a regression
- a vacuous check that survives either way
- cannot trigger the crash on this python version
- undo the fix and see if anything complains
- revert the change and confirm the suite objects
- I never saw it break before I repaired it
- the bug only reproduces on windows and I am on mac
- cannot reproduce the failure on my laptop

## 8. Class-fix scope = every shipped surface

- fixed it in one spot, where else does it appear
- other occurrences of the same pattern
- did I miss a copy in another folder
- stragglers left behind after a partial cleanup
- the same defect is scattered across other files
- forgot the duplicated twin
- how wide does this repair have to reach
- the mirror under vendor still has the old version
- enumerate every place this helper is called
- the packaged tarball still carries the bug
- the ticket said four instances but I count nine
- did the change land in the installed package too
- hunt down the rest of them before closing
- the search misses the ones under the bundled tree
- new file not yet staged so the census cannot see it
- how many callers share this mistake
- a partial rollout of a one-line correction
- the estimate of affected files was too low

## 9. Fast earns scrutiny

- this was too easy
- the answer came suspiciously quickly
- solved it in minutes and ready to commit
- a one-line fix that explains everything
- it clicked immediately, which is suspicious
- an elegant solution I have not attacked yet
- obvious in hindsight, so pause
- eureka moment before lunch
- I feel great about this which worries me
- the whole problem collapsed into a single insight
- everything fell into place at once
- excited to ship it right now
- a tidy story that explains all the symptoms
- rushing because it finally makes sense
- got it working on the first attempt
- what happens if I drop the best-looking data point
- the cleanest theory deserves the meanest test
- too neat to be the whole answer

## 10. Match the net to the hole

- the new rule flags far more files than expected
- the regex matched things I never meant
- tried it on a toy example, not the project
- validated on a fixture, never on production data
- how many places does this trip on
- far broader than the pack promised
- overmatch across the whole codebase
- the lint passed its unit tests then lit up half the repo
- run the new linter on the real tree first
- unit-tested the checker but never pointed it at actual code
- expected a handful of hits got dozens
- one kind of proof does not cover the other kind
- the detector works on its sample and nowhere else
- what does this actually catch when run for real
- the plan's numbers were a guess not a survey
- a written task is a bet that execution settles
- drafted before anyone looked at the live data
- perfecting the plan instead of running it

## 11. Scope-out cannot cover the deliverable's own defects

- I broke something inside the thing I am building
- a known bug in the gate I am shipping
- punting a ticket about work I have not finished
- the plan forbids touching the file holding the flaw
- noting a defect against code I wrote an hour ago
- defer it or finish it before handing it over
- leaving a hole in today's deliverable
- the task says leave that alone but the bug is in my output
- opening a follow-up for a crack in what I just made
- out of bounds according to the brief yet it is my own work
- the acceptance rule would stop me from fixing my own mistake
- can I hand this over with a problem I introduced
- the boundary was meant for other people's code not my own product
- a constraint that blocks improvement as well as damage
- the mechanism I built has a weakness I am about to postpone
- reword the acceptance condition rather than skip the repair
- tempted to log it and move on but I authored it
- the wording freezes the file so I cannot strengthen it

## 12. A gate is proven only on a tree it was not written on

- works on my machine, nowhere else has run it
- passes locally, untested on a fresh download
- the test leans on files that were never committed
- leftover untracked files are propping it up
- try it in a throwaway scratch directory
- somebody else's computer would behave differently
- passing here failing on github actions
- the pipeline broke the moment it left my laptop
- a check that depends on my local setup
- ignored files are quietly making it succeed
- copy it somewhere cold and rerun
- the runner has no build folder and so it falls over
- environment-dependent success in the suite
- only tested inside the editable dev install
- a clean environment tells a different story
- my dev box is not a neutral judge
- try it from the wheel not the source
- I have not run the cheap sanity step in weeks

## 13. Read the neighbours before adding a sibling

- is there already a function like this here
- my addition does not match local conventions
- adding a fifth warning without reading the other four
- my new function looks nothing like the ones surrounding it
- reinventing a utility the module already provides
- match the style of the file I am editing
- wrote my own variant instead of importing theirs
- copied the pattern from memory instead of from the code above
- check how the rest of this class phrases its error strings
- the other messages all use a prefix mine does not
- accidentally wrote a second version of an existing routine
- look at the road before paving a new one
- one of these things is not like the others
- the existing implementation forbids exactly what I typed
- my new entry breaks the format the list already had
- borrowed an idiom from elsewhere that this codebase avoids
- diverged from the established wording without meaning to

## 14. Derive the list, don't test a hand-written copy of it

- two lists kept in sync by hand
- a declared list compared against a computed one
- someone has to remember to update the number in the docs
- the count in the readme drifts from the code
- a test that retypes what the program already knows
- a hardcoded table nobody remembers to edit twice
- manually maintained enumeration, out of date
- the same names appear in the source and in a markdown block
- can the script print this section instead of me typing it
- forgot to add the new command to the help text
- a spreadsheet of modules that nobody keeps current
- auto-generate the catalogue from the registry
- should this be a template rendered at build time
- the doc claims twelve hooks and the code has fourteen
- an assertion that mirrors the very thing it checks
- a stale inventory paragraph
- if the loop returned fewer items would anything notice
- a machine-maintained block that no machine maintains
- who checks the generator once the typed version is gone

## 15. Many attempts, a different failure each time — the problem is mis-specified

- third try and a brand new error every time
- whack a mole, every fix breaks something unrelated
- going in circles on this
- maybe I am solving the wrong thing entirely
- each attempt fails in a way nobody predicted
- am I even asking the right question
- step back and reframe rather than searching harder
- fourth patch and it died somewhere we never looked
- every rerun surfaces a different surprise
- the symptoms keep changing on me
- this is not narrowing down it is wandering
- rewrite the problem statement before touching code again
- the diagnosis changes every week
- we keep being surprised by this bug
- more precise measurement of the same mistaken framing
- the bug moved again after the last change
- I have lost count of the approaches
- what is this thing even supposed to do
- the same defect wears a new mask each time

## 16. Name the user, or it is not a defect yet

- does anyone actually hit this or is it theoretical
- nobody has ever complained about it
- worth fixing something no user hits
- which of forty correct findings are worth doing
- a harmless cosmetic mismatch with no visible impact
- what changes for the person using it
- triage: interesting versus important
- an inconsistency that never reaches anyone
- who is the developer that would notice this
- we have spent a week and the release has not budged
- so much reviewing so little shipped
- internal tidiness masquerading as a bug
- what would a customer see differently after the change
- picking which of these actually matters to somebody
- a real flaw with no victim
- the tools are inspecting each other endlessly
- describe the breakage from the operator's chair
- stop polishing the metadata and fix the crash people see
- how does this show up in the running program

## 17. When the expensive net catches it, move the catch earlier — and sweep the class

- the full suite caught it but nothing faster did
- could a cheaper check have found this
- why did this only show up in the long run
- the red team found something the tests missed
- should this be a test instead of a review finding
- move the check earlier so it fails before the commit
- what else is unguarded in the same way
- fifteen minutes of pytest to learn what a lint could tell me
- promote this to a pre-commit hook
- the slow job is the only thing that notices this
- a human spotted it so automate the spotting
- why is the quick pass blind to this
- wire the two-second contract in where the typing happens
- the manual audit keeps discovering the same kind of thing
- turn the reviewer's catch into a permanent guard
- an overnight run should not be the first line of defence
- the quick smoke never sees this kind of break
- one registration was forgotten which others are also unregistered
- don't let the fast path bloat until nobody runs it

## 18. Fix the class in place; file only what needs its own oracle

- I found another bug while fixing this one
- I just hand-patched one instance of a class
- is filing this cheaper than fixing it now
- does this fix need its own proof or can the current one prove it
- should I fix this too while I am in here
- the commit is growing beyond what I was asked to do
- scope creep in a bug fix
- is this the same class or a different component
- file it as a ticket instead of fixing it now
- half the diff is something nobody asked for
- I tripped over this rather than looking for it
- while I was in there I noticed the next module over is broken
- drive-by repair of something unrelated
- the pull request now does two jobs
- resist the urge to tidy the mess next door
- note it down and stay on task
- a side quest that hijacked the afternoon
- my change is entangled with a second problem
- came for a typo left with a refactor
- keep the changeset about one thing
- it would only take five minutes so why not
- the bystander flaw deserves its own planning
- spent all day and closed just one item

## 19. Name the mutation before you write the gate

- the test passes but is it actually checking anything
- how do I know this new check would fail
- my gate went green immediately
- what would break this test
- the mocks make everything pass
- I deleted the logic and the tests still passed
- writing the check before the assertion
- does this guard actually guard anything
- a validator that has never once rejected anything
- what change to the real code would make this suite complain
- the stub is what's being exercised not the implementation
- replaced the body with nothing and nobody noticed
- patched the input so the scanner sees only my sample
- decide the damage before building the detector
- the safety net has never been tried with a real fall
- it only proves the harness agrees with itself
- which line would I have to corrupt to see this go wrong
- a monitor that agrees with every answer
- name the specific breakage first then write the alarm
- recognises three spellings and misses a hundred others
