# The source tree is not an oracle for the produced artifact

**Status:** active
**Linked from:** docs/SHARP_EDGES.md; `memory/complacent-oracle.md` (the standing-tool
twin); `docs/STANDING_PRINCIPLES.md` §4 and §12 (§12 is the prescription for the
tree-state axis added 2026-08-05)

**What it is:** When the question is *"what does a user actually get?"* — an adopter
after `init`, a cloner after `git clone`, a consumer after `pip install`, a reader of the
release archive — **inspecting the source tree cannot answer it.** The tree is the input;
the question is about the output. A grep, a file-existence test, or a packaging listing
will return a confident, correct number that answers a *different* question, and nothing
about the output looks wrong.

**Why it slips through:** the proxy is not broken. `grep -c` really did count. `git
archive | tar t` really did list the archive. The defect is that the oracle **cannot
express the failure being looked for** — so it reports clean, and a clean report from a
working command reads as evidence. This is the ad-hoc twin of
[`memory/complacent-oracle.md`](../../memory/complacent-oracle.md): that entry covers a
standing tool you built and trust; this covers a one-liner you invented thirty seconds
ago and trusted immediately, which is worse — there is no accumulated suspicion to audit.

**Class signature:** *the oracle reads the source, the claim is about the artifact.*

## Attested instances

| The question | The proxy that lied | Why it could not see it |
|---|---|---|
| Does this self-host-gated test skip on an adopter clone? | a `tmp_path` fixture | models "directory absent"; the real state is "present, empty" — only a real `git clone` reproduces it |
| Does `espalier init` ship every package asset? | `git archive HEAD \| tar t` | `.gitattributes` `export-ignore` strips it from the archive *and* from the probe |
| Do untracked files ship in the release archive? | `git archive` / sdist build | both are **index-based** and physically cannot contain an untracked file; the release walker reads the *filesystem* |
| Does an adopter have `docs/X.md` that our agents cite? | `test -f espalier/assets/docs/X.md` | assets are one of four delivery paths (packaged asset · `_SEED_DOC_REL_PATHS` · `fuse` stub-seed · workflow-generated) — asset absence proves nothing |
| Does `espalier <verb>` work for a user? | running it from the repo root | the repo root **shadows** the install; see `install-path-green-masked-by-cwd-shadow.md` |
| Is this guard correct, or only correct here? | `pytest` on the working tree | the tree the guard was **written against** has the gitignored files, the populated `cc/blueprints`, the built `egg-info`. Every assumption is invisible because it holds. Attested 2026-08-05: a census guard pinned to a gitignored runbook, green locally, red on every clone — through four earned reds and a dispatched second review |
| Does the release archive pass its own test suite? | driving the **real** extracted archive — under `dist/` | `dist/` is inside this repo, so `git` in the extraction walks **up** to the parent `.git` and answers about *it*: `git ls-files` returns rc 0 with zero rows. A downloaded zip in `~/Downloads` has no parent worktree and returns rc 128. Same artifact, same command, two different failures |
| How large is the corpus `/recall` searches? | counting `## ` sections across the source docs | headings are **authored** units; the retriever's are **indexed** ones. `docs/FAILURE_MODES.md` was counted at 202 sections where `_load_corpus` admits **6** shards — inflating a 261-document corpus to "452 retrievable units". The count was the denominator of a whole pack's justification |

Eight instances, one shape. The first five vary the *artifact*; the sixth and
seventh vary the **conditions the oracle runs under**, and each earned its own
prescription. The eighth varies neither — it counts the right files and still
answers a different question, because *authored* and *indexed* are not the same
population.

**The sixth varies the tree.** Same command, same repo, different state. The prescription is
[`docs/STANDING_PRINCIPLES.md`](../STANDING_PRINCIPLES.md) §12: *when the deliverable is a
gate, the acceptance oracle must be a tree the gate was not written on.*

**The seventh varies the location — and it is the one that survives "drive the real
artifact."** You did everything this page asks: you built the artifact and ran it. But an
artifact does not carry its own filesystem context. Extract it inside a git worktree and
every `git` call in it silently reports about the *parent*; extract it outside one and the
same call raises. Neither result is wrong — they answer different questions, and the
comfortable one is the one you get by extracting into a convenient scratch directory
under the repo.

> **Rule:** when the artifact's behaviour depends on ambient state it does not own —
> a `.git` up-chain, `$HOME`, an installed package, `PATH` — the *location* is part of
> the measurement. Drive it in **both** places and diff, or report the result as scoped
> to where you drove it.

Attested twice on the identical mechanism. `e9a1802` (2026-08-10) hit it in the
release-archive builder: asking `git` for the ignore set inside an extraction under
`dist/` answered about the parent and emptied the set. That was recorded in a ledger row
and a commit message and **never reached canon** — the §C25 class — so four days later it
took the suite. A stage-02 measurement reported 5 export failures where a downloaded zip
has 6; the missing sixth was a module's *vacuity guard*, so marking the five turned the
stage green while a sibling assertion passed over zero files. The near-miss is the
receipt: this page's own advice, followed correctly, still produced a false green.

## How to avoid it

**Produce the artifact and look at it.** Not "read the code that produces it," not "list
what would go in." Drive the thing:

```bash
# adopter reality -> a real init into a scratch repo
WORK=$(mktemp -d); cd "$WORK"; git init -q .
python3 -m espalier init "$WORK"; find docs -name '*.md'

# cloner reality -> a real clone, never a fixture
git clone --quiet . "$WORK/clone"

# consumer reality -> a non-editable install, outside the repo
pip install <wheel>; cd /tmp && python3 -c "import espalier"
```

**Before trusting any measurement, ask one question:** *if the defect I am hunting were
present, would this command's output differ?* If you cannot say yes, the number is
decoration. Two independent proxies agreeing is not confirmation when both read the same
wrong source — the release-archive case had `git archive` **and** the sdist build agreeing,
and both were blind for the identical reason.

**Corollary — a proxy is fine for a floor, never for a null.** "This grep found 30" is a
usable lower bound. "This grep found 0, therefore clean" is the trap: absence in a proxy
is not absence in the artifact.

## Receipts

Recorded 2026-08-01 after three proxy-driven miscounts inside one session: an agent's
simulated-tree figure relayed as a live measurement (real value: zero); an asset-presence
test reported as an adopter-reachability result; and a "4 hard-dead references" count that
was 2 once each site was actually opened. Every one was corrected only by driving the real
artifact — a real `espalier init` walk settled the last two. The runbook's own framing of
the same lesson is **"execute what you have only read."**
