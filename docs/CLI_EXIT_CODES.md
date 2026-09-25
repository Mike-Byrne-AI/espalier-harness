# CLI exit-code convention

Every `espalier` subcommand follows one convention:

| code | meaning |
|---|---|
| `0` | OK — pass / clean / nothing to report. |
| `1` | Findings or a completed-but-failed gate: the command ran fully and is reporting a problem (integrity drift, a reflect gap, a failed release-readiness check). |
| `2` | Usage error **or** an operator-resolvable precondition: argparse usage errors; `integrity verify` detecting a kill-switch setting; `scope-check` finding an unacknowledged scope gap; a repo-scoped command given a path that does not exist or is not a directory, or whose `.claude` is a directory the process cannot search or list (the shared precondition guard `cli._resolve_repo_arg` — `install-ci`, `fingerprint`, `audit`, `scan`, `diff`, `reflect`, `reflect-deep`, `provenance`, `recover`, `audit-accuracy`, `clean-generated`, `strengthen`, `release-pack`, `pre-release`, `scaffolding-bench`, `integrity`, `blueprint`, `scope-check`, `surface-impact`, `verify-landing`, `freshness check`/`pin`/`unpin`, plus the self-host/dev commands `merge-settings`, `selfcheck`, `self-host`, `surface-handoff`, `worktree-plan`, and the hidden `_refresh-self-host-pin`). A `2` means "resolve or acknowledge this, then re-run" — it is not an ordinary finding. Four commands intentionally opt out and reject a bad path with their own contract: `doctor` (exit `1`, per below), `upgrade` (exit `1`, "not a git repository"), `init` (exit `1`, "does not exist or is not a directory") and `fuse` (exit `1`, `[fuse] FAIL:`). Those four ask the `.claude` question at their own pre-flight (`cli._refuse_unreadable_harness_root`, or the same one sentence in their own voice); a new command that resolves its own path must do the same, and `tests/test_cli_commands.py` derives the repo-taking commands from the parser and reds on one that asks neither gate. |

`espalier doctor` uses only `0` (pass/warn) and `1` (fail) — never `2`.

Consumed codes (do not renumber without updating every consumer):
- `bench/run_benchmark.py` keys its kill-switch verifier on `integrity verify` → `2`.
- `tests/test_integrity.py` pins `integrity verify` drift→`1`, kill-switch→`2`.
- `tests/test_cli.py` pins `scope-check` unaccepted-gap→`2`.
- `tests/test_correctness_minors.py` pins the repo-scoped path-precondition guard → `2`.
- CI keys `espalier doctor` on `0` (pass/warn) vs `1` (fail).
