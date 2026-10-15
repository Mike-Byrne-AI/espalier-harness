### Fixed

- **`/ship`'s hand catch-up line finishes the merge instead of throwing the
  hand resolution away.** When a catch-up conflicted on a hand file and a record
  file, the body's one-line call to the record resolver listed the memory file,
  the forward ledger and its probes roster whatever had conflicted. The resolver
  refuses any listed file that is not a content conflict, so the line raised
  every time, and the next step the body named, `git merge --abort`, discarded
  the staged hand resolution. The line now resolves the paths git reports
  unmerged and prints what it resolved. It also refuses, before committing, a
  record file staged with its conflict markers (a `git add -A`), naming the
  `git update-index --unresolve` that gives the file back to it. The body says
  what each refusal leaves standing and what to do next, so `git merge --abort`
  is the last resort, not the next step.

### Changed

- **The bodies and docs name where the folded records' rows live.** The forward
  ledger's class rows and its probes moved to `task-packs/ledger.d/` and
  `task-packs/probes.d/`, and the Session Log's rows to `memory/session-log.d/`.
  The agent, command, skill and workflow bodies, the shipped docs and the seeds
  now name the folder, or `tools/cc/_record_fragments.py`, beside the old file,
  and say what holds on a tree that keeps one file. The docs-maintainer agent's
  pruning check counts the Session Log's files where the loader is deployed (it
  counted 0 rows there before). The SessionStart digest is described as gated on
  the Session Log's rows wherever they live. `/ship` describes `open`'s row check
  as accepting a new Session Log file.
