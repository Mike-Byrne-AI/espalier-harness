### Fixed

- **A diff that edits only a doc, a memory note or a top-level file now runs
  the test files that name it.** `scripts/proof_tier.py` mapped a changed path
  to the integration-classified test files naming it for the agent, command
  and skill bodies alone, so an edit to `docs/WORKFLOW.md` (the contract tier)
  or `memory/parallel-work-protocol.md` (the recall tier) ran no row of
  `tests/test_mail.py`, which asserts phrases in each, and a red there arrived
  on `main` after the merge. The map (`path_readers`, renamed from
  `body_readers`) now reads every changed path, and a name a test only writes
  into a tree it builds no longer counts as a read: a join that receives a
  write, a move or a removal, `open` or `shutil.copy` writing it, or a
  variable bound to one and used for nothing else. A join on a scratch tree
  the test reads back still counts, since `espalier init` copies this
  checkout's files into it. One `README.md` edit's own line holds 84 files, 60
  of them non-contract, where reading every path without the discriminator
  would hold 112 (86). Not seen: a file only the code under test reads (a
  check run on the repository root, `git`, an `init`-built tree the engine
  reads back). A staged rename now counts its original path on the local
  receipt, as the `--base` diff already did.
