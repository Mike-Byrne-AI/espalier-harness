### Fixed

- **A bench run whose hook scenario decided nothing now retries as its
  scenario says and exits non-zero** (DEF-5001). In `bench/end_to_end/`, the
  three wiring scenarios (BCE-001, BCE-002, BCE-003) retry once on an
  inconclusive verdict and report a final one as a warn. Two things were wrong:
  - `bench/end_to_end/assertions.py::evaluate` rewrote the inconclusive to
    warn before the orchestrator read it, so
    `bench/end_to_end/run.py::_run_with_retry` never retried;
  - `bench/end_to_end/run.py::main` exited 1 only on a fail, so a live CLI
    that answered while its hook scenario decided nothing exited 0.

  A maintainer running the bench before a hook-protocol change read a green
  run that tested no hook. Driven in process on the real scenario files: each
  ran once, reported warn and exited 0.
  - **Now:** the verdict records that the scenario decided nothing
    (`undecided`, in the JSON report too). The retry reads that flag. A run
    that itself failed or timed out counts as decided and is not retried, and
    the cost cap still stops a retry. One scenario still undecided after its
    retry makes the run exit `3`. A fail outranks it (`1`), and a cost abort is
    still `2`. The report keeps the warn as its text, names why beside it, and
    counts the undecided scenarios in its header.
  - **A retry that decides leaves its trace:** a note that the first run
    decided nothing, that run's transcript archived as `<id>.run1.json`, and
    the tokens of every run in the totals.
  - **Cost:** every undecided wiring run now pays for its retry, about 0.42,
    0.11 and 0.09 USD for BCE-001, BCE-002 and BCE-003 on Claude Code 2.1.299
    with claude-opus-5-5.
  - **What also counts now:** the retry check's ground-truth inconclusives,
    which are warns as well.
  - **Docs:** the orchestrator's docstring, `bench/end_to_end/SCHEMA.md` and
    `bench/end_to_end/README.md` say when a run exits `3`. SCHEMA.md also no
    longer says a scenario with no `treat_inconclusive_as` defaults to warn
    (it stays inconclusive). The bench workflow (run on dispatch while its
    schedule is off) already fails its step on any non-zero exit and opens
    its issue.
