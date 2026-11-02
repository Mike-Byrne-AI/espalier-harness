### Fixed

- **The shipped agents and review workflows say what they stood down from
  on an adopter's tree, instead of reporting the harness's own files or a
  silent clean result.** The harness-config-advisor reads a hook's script
  from `args[]`, where `espalier init` writes it, so a deleted hook script is
  dead config again, and a hook naming no script file is reported as not
  checked rather than clean. The architecture-analyst and docs-maintainer run
  the harness's own checks only on the harness's repository and say what they
  skipped elsewhere, and the circular-import step imports your packages, not
  the installed engine. The fingerprint records the commit it was taken at,
  and the drift checks diff from it, or say there is no baseline rather than
  reading the last five commits; `espalier diff` ignores the new field. The
  three review workflows name a lane that returned nothing or failed, and the
  convergence template writes no `converged` ledger row while a lane did not
  run; the fan-out audit refuses arguments it cannot use, and with none it is
  a dry run that counts its targets until given `confirm: true`.

### Changed

- **Every shipped agent's tools line names whole tools.** A command pattern
  such as `Bash(git *)` on a subagent's tools line does not narrow its shell,
  so the lines now say `Bash`, docs-maintainer gains `Edit`, and each body
  says where its shell's scope is actually set: your permission rules in
  `.claude/settings.json`, which apply to subagents too, and the harness's
  hooks.
