### Fixed

- **A Python project's inferred test and lint commands run inside its
  environment.** A tree whose root holds `uv.lock`, `poetry.lock`,
  `Pipfile.lock`, `pdm.lock` or rye's `requirements.lock` was fingerprinted
  with `pytest -q` and, where ruff is declared, `ruff check .`, which run only
  where a shell activated the environment, and a `uv run` workflow never does:
  `/preflight`'s test step failed with `pytest: command not found`, and no
  allow rule covered `uv run pytest`. The lockfile now names the tool, and the
  commands run under its `run` (`uv run pytest -q`, `poetry run ruff check
  .`), with the stop gate's opt-in test run, `/preflight`'s exclude of the
  deployed `tools/cc/`, the SessionStart ruff check and the derived allow rules
  following (those cover the inferred command's own form, `uv run pytest -q
  ...`; another spelling still asks). Gate 1 runs the prefixed command whole
  at the root, even on a tree that holds files named like the harness's own
  default tests, where a bare `pytest -q` ran those files alone. The lockfile
  alone decides, as a Node
  lockfile names its package manager: whether the tool is installed is not
  checked, and a `requirements.lock` some other tool wrote reads as rye's.
  Lockfiles of two tools, or a lockfile one directory down, leave the commands
  bare, and so does Hatch's, whose `pylock.toml` is a standard name other
  tools write too. `uv run` syncs the environment before it runs, so the first
  run in a fresh checkout can be slow and can rewrite `uv.lock`; declare
  `uv run --locked pytest -q` (or any other command) under `[extra_actions]`
  in `espalier.toml` to choose another. The five tools' lockfile names are
  also plan-gated root files by name now, which matters only where
  `plan_exempt_prefixes` exempts the root (a root `.lock` file was already
  gated by its suffix).
