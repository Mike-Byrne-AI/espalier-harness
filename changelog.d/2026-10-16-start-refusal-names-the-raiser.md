### Fixed

- **A deny hook that cannot start names the file that broke it.** When a
  sibling of `write_guard`, `plan_guard`, `config_guard` or `stop_gate` raised
  at import, the refusal blamed a kept, older `_hook_utils.py` and sent you to
  `espalier upgrade --execute .`, whatever had raised. That upgrade would have
  regenerated the file you were editing. The refusal now names:
  - the file under `tools/cc/` that raised, its line and the exception;
  - every other `tools/cc/` file on its traceback, since the file you edited is
    often an outer one;
  - the upgrade, only when a name a sibling takes is missing from
    `_hook_utils.py`.
- **A wedged guard lets its own repair through.** A guard that cannot start, or
  whose judgment crashes, used to refuse every call, the one that would repair
  it included, so the repair waited for someone at a terminal. Now
  `write_guard` lets through exactly one Bash call: one `git restore` or
  `git checkout --` to HEAD of a file its refusal names.
  - **The command.** The refusal names `git restore --source=HEAD -- <file>`,
    which repairs a staged break and an unmerged path as well.
  - **The copy.** Before the call passes, the file's bytes are copied under
    `.espalier-state/wedge-restore/`, because the restore discards the file's
    uncommitted edit.
  - **No decision.** The call carries no permission decision, so your
    permission mode decides it.
  - **Still refused.** A second command, a shell operator, another ref, another
    file, the PowerShell tool, and an Edit or Write of the file.
  - **The other three hooks.** They judge no Bash call, so they name the same
    restore for a terminal.
