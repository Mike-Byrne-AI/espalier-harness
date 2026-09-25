# Espalier-Harness — Positioning

**Espalier-Harness is a repo-local workflow + governance harness for
Claude Code — a working partner that keeps your coding agent on the rails.**

## What it is

- A **workflow** for solo founders and small teams: plan-gated changes,
  per-step proof, cross-session memory, and a clean session handoff — so
  following the workflow is the path of least resistance.
- Repo-local hooks that add **friction** at risky operations and at the
  moments the agent might drift — most of all the agent disabling its own
  safety mid-task.
- **Reports** that make repo condition visible to the operator and to
  Claude.
- Adversarial **regression tests** preserving every historical slip the
  friction layer catches as a named, reproducible canary.
- A **release/CI gate** that enables merge-time enforcement when paired
  with branch protection.

## What it is not

- A coding agent.
- A sandbox.
- A replacement for CI.
- An adversarial security boundary. The friction here is **seatbelts for
  agent drift** — you don't need to defend against yourself. The threat
  model is the operator and the agent making mistakes, not a motivated
  attacker with local filesystem control.

## The boundary

Local hooks run in the same trust domain as the agent. A user or
process with local filesystem control can disable hooks before Claude
Code invokes them — the `disableAllHooks` setting and the documented
two-step subprocess pattern are both bypasses by design. The honest
enforcement boundary is **CI plus branch protection**, not local hook
code.

Espalier-Harness's claim is not "agents cannot misbehave." The claim is that
bypass attempts are made **visible**, **testable**, and **harder to
merge unnoticed**. That is a strong claim. It is also the only claim
Espalier-Harness makes.

## Three layers

The friction/visibility/guarantee model is the load-bearing structure:

| Layer | Where it runs | What it actually does |
|---|---|---|
| Friction | Local PreToolUse / ConfigChange hooks | Raises the cost of casual mistakes; blocks documented patterns |
| Visibility | Local PostToolUse + integrity manifest + audit log | Records what happened, including bypasses, so they're auditable |
| Guarantee | GitHub Action + branch protection | The only layer outside the agent's reach; gates merges |

If you remove the guarantee layer, what's left is a tool that catches
sloppy edits and surfaces the rest. That's still useful — but
CI + branch protection is where the real boundary lives.

## What enforcement can and can't do (detail)

This is the layer-by-layer breakdown, relocated here from the README so the
README leads with the workflow. Each layer raises a guarantee with explicit
limits — none is a hard boundary on its own.

**Friction layer (default).** Two hooks operate here:

- `write_guard.py` hard-blocks mutations (a write, a delete, a move) of protected harness paths — the
  `tools/cc/` and `cc/` trees,
  plus `espalier/` and `.github/workflows/` on the self-host repo,
  and the exact files `.claude/settings.json`, `.claude/settings.local.json`,
  `.github/workflows/harness-guard.yml`, `.espalier/integrity.json`, and
  `.espalier/freshness.json`. Not a
  security boundary — a two-step bypass (write a script to an unprotected
  path, then execute it) is outside its detection scope.
- `plan_guard.py` requires an active `execution_plan.json` before any
  observed source, config, or project-file mutation. It classifies by
  command, not just by tool: shell redirects (`> file`, `>> file`), common
  mutation commands (`rm`, `mv`, `cp`, `touch`, `mkdir`, `tee`, `sed -i`,
  `perl -pi`), and inline Python write APIs (`open(..., "w")`,
  `.write_text(`, `.unlink(`, `os.remove(`, `shutil.copy(` etc.) are all
  detected and require a plan. Root-level source and config files
  (`main.py`, `pyproject.toml`, `README.md`, `Dockerfile`, etc.) also
  require a plan when edited directly. This is a deterministic command
  classifier — not a hard sandbox — and passes through command patterns it
  cannot classify. Use `/implement-task` or `/implement-task --multi` to
  create a plan before making changes.

`execution_plan.py` exits nonzero on failure states (no plan, out-of-range
step, blocked plan) and zero on success, making it safe to use in scripts
and CI checks.

**Visibility layer.** `session_start.py` reports kill-switch findings
(`disableAllHooks: true`, `bypassPermissions`, empty/no-op hook lists) and
integrity drift at session start and records audit events to
`~/.espalier/audit/`, but **SessionStart cannot block Claude Code
execution** per the official hook protocol. Blocking local enforcement
lives in PreToolUse (`write_guard.py` denies any tool call while a
kill-switch is set) and ConfigChange (`config_guard.py` blocks unsafe
project/local/user settings changes). Merge-time enforcement lives in CI
with branch protection (`ci_guard.py` fails the build on an unapproved
protected-path change, and backstops a force-added kill-switch setting —
`.claude/settings.json` is gitignored, so the normal path can't commit one).
The audit log lives under `$HOME`, outside the repo tree — visibility,
not a boundary: it runs in the same trust domain as the agent, so a
session shell can still delete it (write_guard does not protect the audit
dir). The CI layer is the only real guarantee. Hash-drift checking
activates once you create a manifest via `espalier integrity refresh .`.

| Hook event | Can block? | Purpose |
|---|---|---|
| `SessionStart` | No (protocol forbids) | Context loading + warnings only |
| `PreToolUse` | Yes | Blocks pending tool calls (write_guard, plan_guard) |
| `ConfigChange` | Yes for project/local/user | Blocks unsafe settings changes; managed `policy_settings` audit-only |
| `PostToolUse` | No (tool already ran) | Warning/audit only |
| CI (`ci_guard.py`) | Yes | Outside-agent merge-time gate when branch protection is enabled |

```bash
espalier integrity refresh .  # create manifest; activates hash-drift checks
espalier integrity verify .   # 0=clean, 1=drift, 2=kill-switch found
```

**Guarantee layer (opt-in, one manual step).** `espalier install-ci` +
GitHub branch protection. On your repo, a pull request touching protected paths
without the `HARNESS-UPDATE-APPROVED` marker cannot reach `main`. This is the
only layer with a real guarantee — because GitHub's infrastructure is outside
the agent's reach. (Two narrow exemptions exist and are documented in
[`INSTALL-CI.md`](INSTALL-CI.md): genuine Dependabot action-ref bumps, and
direct pushes on the harness's own self-host repo. Neither reaches the
kill-switch scan, which is unconditional.) See [`INSTALL-CI.md`](INSTALL-CI.md) for the one-step
walkthrough.

Protected-path inventory (the canonical CI policy): all hook scripts under
`tools/cc/hooks/`, the kill-switch surface (`.claude/settings.json`,
`.claude/settings.local.json`, `.espalier/integrity.json`),
`tools/cc/ci_guard.py`, and **all GitHub Actions workflows** under
`.github/workflows/` — workflow mutation can change release, test, or
benchmark enforcement, so any `.github/workflows/*.yml` change requires the
approval marker. The authoritative lists live in
`espalier.surface_contract` (`get_protected_ci_files`,
`get_protected_ci_prefixes`, `get_protected_integrity_paths`);
`tools/cc/ci_guard.py` and `tools/cc/hooks/_integrity.py` carry parallel
constants for hook isolation, with
`tests/test_protected_path_contract_parity.py` and
`tests/test_integrity_contract_parity.py` enforcing equality.

If you need true un-bypassability, you need containerization. The honest
claim: for human + Claude Code teams where most failures are inattention and
drift rather than adversarial action, this stack catches almost everything.

## Who this is for

- Individual developers and small teams using Claude Code who want hook
  discipline without pretending hooks are more than they are.
- Maintainers who'd rather pin every historical bypass as a regression
  test than ship a long list of unverifiable claims.
- People who prefer calibrated tools to impressive ones.

## Who this is not for

- Enterprises looking for compliance certification or formal policy
  engines — Espalier-Harness is governance hygiene, not compliance.
- Anyone wanting a turnkey "make my agent good" experience with
  maximum agents and skills bundled by default. The harness ships with
  7 agents and 17 commands chosen for governance hygiene, not
  feature breadth.
- Threat models where the adversary already has local filesystem
  control. The honest answer there is "use sandboxing infrastructure
  outside Espalier-Harness's reach."

## Receipts

Everything above is testable in the repository:

- The friction layer's bypass classes are pinned in
  `tests/test_write_guard.py::TestBashDocumentedOutOfScopeBypasses`
  alongside what *is* caught.
- The visibility layer is exercised by `tests/test_integrity.py` and
  the audit-log contract tests.
- The guarantee layer's CI behavior is enforced by `tools/cc/ci_guard.py`
  and the workflow at `.github/workflows/harness-guard.yml`.
- The benchmark in `bench/` runs the same corpus against multiple
  governance baselines so the comparison is reproducible — see
  [`bench/RESULTS.md`](../bench/RESULTS.md).

If you find a claim in any Espalier-Harness doc that isn't backed by one of
these surfaces, that's a bug worth filing. See `SECURITY.md` for the
private path if it's a security-relevant overclaim.
