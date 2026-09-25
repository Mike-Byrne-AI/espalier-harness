# An enumeration switch reaches every consumer

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "An enumeration switch reaches every consumer"

When a fix changes WHAT A WALK ENUMERATES (the working tree to the git
index, a glob to a manifest), the unit of work is every consumer of the old
enumeration, not the site the ledger row names. The §C13 release-archive lane
(2026-09-08) moved the two archive builders onto the git index, ran its
targeted proofs green, and both reviewers then found four consumers the first
cut had left on the old enumeration:

1. **The failing sister.** `pre_release._find_internal_leaks` still walked the
   tree, so an untracked `docs/internal/` scratch file became a hard
   `/preflight` failure the archive could never have carried. The warning
   half had been migrated; the failing half had not.
2. **The fixtures.** 34 of 47 release-pack tests and the whole parity module
   proved the fallback branch -- a hand-made `.git/HEAD` makes a tmp tree a
   repository git cannot answer for (rc=128) -- while a docstring the diff had
   just rewritten claimed the index. A green test of the branch that does not
   ship.
3. **The gates.** The fallback was voiced on stderr and nothing read it, so
   git absent from PATH, dubious ownership or a moved gitdir shipped the tree
   at exit 0 with the archive looking plausible.
4. **The other build path.** The wheel and sdist are setuptools filesystem
   sweeps (no `setuptools_scm`), and two in-repo comments called that path
   git-based.

The lane ran at roughly twenty times its 45-line estimate because the
estimate priced the sites the rows named, not the consumers.

## How to apply

Before dispatching the reviewers on an enumeration change:

- `grep` every caller of the old walk in the feature area (the helper,
  `safe_rglob`, `iterdir`, `os.walk`) and every test fixture that fakes the
  marker the new enumeration keys on (`.git`). Migrate or label each one.
- Give the result a FIELD a gate can read (`enumeration: index | tree` on the
  summary) and make the gates refuse the degraded shape. A stderr WARN is not
  something a gate reads.
- Keep the two "nothing to enumerate" shapes apart: no index to ask (a plain
  directory; quiet, the walk is the whole truth there) and an index git could
  not answer for (warn, and refuse at the gates). Collapsing them to one
  empty set re-enters the defect through the error path.
- **The same rule runs backwards when you FILTER a shared enumeration for
  one reader.** The recall lane (2026-09-12) excluded two notes from the pull
  ranker by skipping them inside `_iter_corpus`, the one enumeration every
  recall reader consumes; the failure-mode review drove `nearest_by_title`
  (the reflect protocol's fold-here hint) and found it had silently lost
  exactly those two notes as fold targets, and no test covered that reader's
  corpus membership, so nothing reddened. List the readers of the walk before
  filtering it (here: the ranker, the eval's labels, the title matcher, the
  banner's family list), put the filter at the reader that wants it or give the
  enumeration an explicit `exclude` argument the others pass empty, and pin the
  reader you did NOT filter -- its membership is the claim the filter must not
  touch.
- **And it runs a third way when you WIDEN one.** A shared extraction list
  carries a meaning its readers act on: `_candidate_paths_from_bash` is *files
  this command wrote*, which `post_write_check` turns into a synthesized
  Write/Edit and `scripts/audit_dead_rules.py` reads as a rule's live sites, so
  folding a new effect (an operand a verb deletes or moves) into that list
  makes both readers wrong about what happened. Name the readers first; if any
  acts on the list's *meaning* rather than its membership, the addition is a
  TAGGED SIBLING reader beside it (`iter_removed_or_relocated_operands`,
  yielding `(effect, path)`), and each consumer opts in to the effects it
  wants (2026-09-14).
- A fixture that stages a tree must force-stage (`git add -A -f`): this
  machine's global git ignore excludes `**/.claude/settings.local.json`, and a
  fixture that lets the global excludes decide what is tracked proves the
  contract on whatever survived them.

## The same rule for a RETURN CONTRACT, not only an enumeration

**Attested 2026-09-10.** Changing what a shared path normaliser *returns* — a
string became a base-plus-relative pair — made every consumer that rejoins the
relative part to a directory a site of the class, and none of those sites is a
caller anyone would list. The first pass migrated five bases found by searching
the two guards and the post-write check, and missed the PowerShell twin of a
migrated site plus four rejoins spelled through other helpers; one of them had
already converted a harmless edit in a second checkout into a speed-bump
denial. What found the remainder was a tree-wide text search for the rejoin
idiom itself, run by a reviewer with a different lens, after the lane's
targeted proofs were green.

**So: run the tree-wide consumer census before the FIRST edit, not before the
reviewers.** Classify every hit — migrate, or root-by-construction — and pin
the classification, because a probe keyed on function names cannot see a rejoin
at all: the idiom is an operator between two locals, not a call with a name to
clique on.

Related: [[fix-the-class-not-the-instance]] (the class question, asked first)
· [[sister-site-compression]] · [[four-gates-the-targeted-proofs-never-show]]
(the paperwork gates the same lane tripped at its strike step).
