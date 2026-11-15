### Fixed

- **An agent's Write or Edit of your user settings file that turns the hooks
  off or loosens a gate is refused.** `write_guard` judges a Write or Edit of
  `~/.claude/settings.json` (or `settings.json` under `CLAUDE_CONFIG_DIR`) by
  `config_guard`'s rule, now one function in `_integrity`, and refuses a
  result that turns `disableAllHooks` on or loosens `ESPALIER_MAINTENANCE_MODE`,
  `ESPALIER_STOP_GATE` or `ESPALIER_STOP_GATE_TEST_CMD` in its `env` map;
  every other edit of the file goes through. `config_guard` already refused
  the change at ConfigChange, but its refusal left the file as written, and
  every session on the machine launched from it next. The check runs under
  maintenance mode, judges the file on its own as well as for the session
  (a value a higher file in one repository outranks still reaches the
  others), reads an Edit the way Claude Code's Edit tool applies it, and
  leaves a Bash, PowerShell or MCP write of the file a declared limit with no
  per-call cost. The audit record is `pretooluse_blocked_kill_switch` with
  `kind: user_settings_write`. Two helper names join the start floor of
  `plan_guard` and `stop_gate` (and one of `write_guard`): `stop_gate_mode`,
  in v0.8.0b2's helper, and `STOP_GATE_TEST_CMD_ENV`, added 2026-09-30, both
  older than names those floors already held.
