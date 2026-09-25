# Documentation

## Start here

| Doc | Audience | What it covers |
|-----|----------|----------------|
| [QUICKSTART.md](QUICKSTART.md) | New users | Install, initialize, first session, uninstall |
| [HOOKS.md](HOOKS.md) | All users | What each hook does, deny messages, configuration |
| [WORKFLOW.md](WORKFLOW.md) | All users | Day-to-day usage: commands, agents, session lifecycle |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | All users | Common failure symptoms and fixes (deployed by `init`) |
| [ADOPTING.md](ADOPTING.md) | New users | After init: ground the harness on your repo (`/analyze`) and adapt the bundled agents |

## Reference

| Doc | Audience | What it covers |
|-----|----------|----------------|
| [CHEAT-SHEET.md](CHEAT-SHEET.md) | Daily users | One-page quick reference for commands and conventions |
| [SHARP_EDGES.md](SHARP_EDGES.md) | All users | Known gotchas, footguns, and documented bypass classes |
| [INSTALL-CI.md](INSTALL-CI.md) | Repo admins | Enabling the CI guarantee layer with branch protection |
| [SURFACE_SUPPORT_MATRIX.md](SURFACE_SUPPORT_MATRIX.md) | Evaluators | Normative per-surface support tiers (the front-door docs — README, QUICKSTART, CHEAT-SHEET — are tested against it for overclaiming) |
| [FRESHNESS.md](FRESHNESS.md) | Contributors | How documented numeric claims are pinned and re-verified |
| [CONVENTIONS.md](CONVENTIONS.md) | Contributors | Part I: layout, code style, agent/command/hook/testing design. Part II: the test-cited invariant registry (reach via its index). |
| [TASK_RECIPES.md](TASK_RECIPES.md) | Contributors | Step-by-step recipes for common harness tasks |
| [PACK_AUTHORING.md](PACK_AUTHORING.md) | Contributors | Task-pack format and the `## Affected symbols` section |
| [CLI_EXIT_CODES.md](CLI_EXIT_CODES.md) | All users | Exit-code convention for `espalier` CLI commands |
| [ENV_CATALOG.md](ENV_CATALOG.md) | Repo admins | Environment variables that configure the harness |
| [FAILURE_MODES.md](FAILURE_MODES.md) | Contributors | Catalog of named failure modes the harness guards against |
| [STANDING_PRINCIPLES.md](STANDING_PRINCIPLES.md) | Contributors | The few cross-cutting lessons/frames worth holding in context for any harness work |
| [MEMORY_SYSTEMS.md](MEMORY_SYSTEMS.md) | All users | The distinct "memory" systems (CLAUDE.md, Claude Code auto memory, committed `memory/`), the committed `ESPALIER_MEMORY.md` vs. Claude's auto-memory `MEMORY.md` (once both named `MEMORY.md`), and the sorting rule for which owns what |
| [AUTONOMOUS_EXECUTION.md](AUTONOMOUS_EXECUTION.md) | Contributors | The dev-only loop-over-`claude -p` driver: architecture, safety design, install-green gate, and failure modes |
| [CC_AUTOMATION.md](CC_AUTOMATION.md) | Contributors | Claude Code automation primitives the harness composes with: `/goal`, `/loop` (interval vs dynamic), ScheduleWakeup/Monitor/cron, auto-mode (pinned to a CC version) |

## Design background

| Doc | Audience | What it covers |
|-----|----------|----------------|
| [POSITIONING.md](POSITIONING.md) | Evaluators | What Espalier-Harness is and isn't, and why |
| [SECURITY_TAXONOMY.md](SECURITY_TAXONOMY.md) | Evaluators | Security coverage mapped to the OWASP ASI taxonomy |
| [ADAPTER_BOUNDARY.md](ADAPTER_BOUNDARY.md) | Contributors | How the Claude Code adapter layer separates from the governance core |
| [DEEP-WORK.md](DEEP-WORK.md) | Contributors | The design bet behind structured reflection (hypothesis, not a measured effect) |
| [HOOK_ASSUMPTIONS.md](HOOK_ASSUMPTIONS.md) | Contributors | Claude Code hook-protocol assumptions the harness relies on |
| [DEMO.md](DEMO.md) | Evaluators | Scripted 5-minute walkthrough with expected outputs |
| [CLASSIFIER_FALSE_POSITIVES.md](CLASSIFIER_FALSE_POSITIVES.md) | Evaluators | Why the guard's test fixtures trip automated safety classifiers, and the wording discipline that keeps them neutral |
| [incidents/2026-09-17-real-shell-fixture-wipe.md](incidents/2026-09-17-real-shell-fixture-wipe.md) | Evaluators | The one incident record we publish: a maintainer's throwaway fixture driver, not the shipped guard, expanded an unbound variable beside a glob on a real shell, and what that changed in how the guard's own tests are run |
| [epistemic-partnership.md](epistemic-partnership.md) | Evaluators | The epistemic-partnership concept behind the checkpoints and review passes: which principles are wired into a built mechanism, and which are not built |

## Maintainer-only (in the private archive, not in the public repository or the release)

Release-engineering ritual for this repo specifically — it names the maintainer's
own accounts, settings, and one-time pre-flip sequence, so it is excluded from the
sdist, the release archive, and GitHub's "Download ZIP". The two files are kept in
the maintainers' private archive; the public repository and every shipped
artifact omit them, so they are not beside this index wherever you are reading it
from unless that is the private tree itself.

| Doc | Audience | What it covers |
|-----|----------|----------------|
| `RELEASE_CHECKLIST.md` | Maintainer | Tag posture, alpha→beta→GA cadence, and the release-decisions appendix |
| `RELEASE_DECISIONS.md` | Maintainer | Chronological log of decisions shaping the release path |

Deliberately unlinked: a markdown link here would resolve only in the private
development archive and 404 here and in both shipped artifacts. `tests/test_git_archive_parity.py` and
`tests/test_wheel_payload.py` each check one of those two artifacts.

## External references

| Doc | Source | What it covers |
|-----|--------|----------------|
| [external/README.md](external/README.md) | this repo | How a pin works: the frontmatter schema every pin carries, the refresh command and its CI workflow, and what a failing bound test means when upstream drifts |
| [external/cc-hook-protocol.md](external/cc-hook-protocol.md) | Anthropic | Claude Code hook protocol specification (pinned copy) |
| [external/cc-statusline.md](external/cc-statusline.md) | Anthropic | Claude Code status line contract (pinned excerpt) |
| [external/cc-worktrees.md](external/cc-worktrees.md) | Anthropic | Claude Code worktrees: hook `cwd` follows Claude, `CLAUDE_PROJECT_DIR` stays put, the worktree lock (pinned excerpt) |
