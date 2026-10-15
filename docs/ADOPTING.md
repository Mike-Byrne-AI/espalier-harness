# Adopting Espalier-Harness onto your repo

`espalier init` (or `fuse`) deploys the mechanical harness and writes
fingerprint-shaped skeletons. That is the *structural* half. This page is
the *semantic* half — the one-time steps that make the harness about **your
project**, not Espalier's. Do them in your first Claude Code session.

## The sequence

1. **Install** — `python -m espalier init .` in place, or `python -m
   espalier fuse <repo> --out <governed>` for a governed copy. See
   [QUICKSTART.md](QUICKSTART.md).
2. **Ground the harness — run `/analyze`.** This is the load-bearing step.
   `repo-analyst` establishes the baseline fingerprint and `docs-maintainer`
   populates `docs/CONVENTIONS.md` and `docs/SHARP_EDGES.md` from your
   actual code. Without it the harness is scaffolded onto your repo but not
   grounded in it. `espalier doctor .` nudges you here while
   `docs/CONVENTIONS.md` is still empty.
3. **(fusion path only) Follow the finish-up checklist `fuse` printed.** It
   lists the host-taste steps the script can't mechanize (repurpose the
   verifier tests, re-point CI + scanners, rewrite the overlaid operator
   docs host-generic). In-place `init` skips this — it deploys no overlay.
4. **Adapt the bundled agents (ongoing, optional).** Each agent body ships
   an `## Adapting me to YOUR repo` section: its worked examples are
   Espalier's own — replace them with your project's equivalents as you
   customize. The methodology is the value; the examples are scaffolding.
5. **Verify** — `python -m espalier doctor .`.

## Why grounding matters

The fingerprint gives the harness your languages, structure, and test
command mechanically. It cannot write *your* conventions with real code
examples, distill *your* footguns, or calibrate FACT/INFERENCE/SPECULATION
— those are reading-and-judgment tasks. That is exactly why grounding is
agent-driven (`/analyze`), not a script.

## The sandbox posture (macOS, Linux, WSL2)

Claude Code's Bash sandbox is a boundary the operating system enforces around
the shell commands Claude runs and the processes they start. It is off by
default, it covers shell commands only (the `Write`, `Edit` and
`NotebookEdit` tools, MCP servers and hooks run outside it), and there is
none on native Windows. Where it is on, the harness can stand behind it:

- `python -m espalier init .` and `python -m espalier upgrade .` print the
  posture they would write; `--sandbox-posture` writes it (`init
  --wire-hooks --sandbox-posture` on a settings file you already had, or
  `upgrade --execute --sandbox-posture`), appended under your keys in
  `.claude/settings.json` through the same merge that wires the hooks, a
  backup kept first.
- `sandbox.filesystem.denyWrite` names the harness zones (`tools/cc/`,
  `.github/workflows/`, the integrity and freshness manifests, the two
  settings files) and your `protected_paths` from `espalier.toml`;
  `denyRead` names the secret paths `write_guard` refuses to read (`.env`
  and `.env.*`, `secrets/`, `.aws/credentials`, `credentials.json`), each at
  the project root and anywhere below it, as the guard matches them. Both
  lists are derived from the guard's own rosters at the time of the write,
  never copied by hand. `cc/` is left to
  `write_guard`: the harness's own shell commands write its carve-outs (the
  plan, the blueprints, the working summary), and the sandbox has no
  narrower allow for writes.
- `sandbox.enabled` is never written. Turning the sandbox on changes how your
  network and command approvals behave, so it stays yours: `/sandbox` in a
  session. Set `allowUnsandboxedCommands` to `false` in your user settings
  (`~/.claude/settings.json`) to stop a refused command being retried outside
  the sandbox; a user-scope `false` holds against a project's `true`.
- `python -m espalier doctor .` reports the state: no sandbox on native
  Windows (the after-check and the guard's path check are the location layer
  there), off, or on and from which file, with the derived entries present
  and missing and whether your user settings disable the retry.

What this is not: a replacement for `write_guard`. Measured on macOS, a
`denyWrite` path refuses shell writes and `git checkout` and not the `Write`
tool, so the guard's path check on the file tools stays the layer there. An
`espalier upgrade` run from inside the sandbox over a denied path is refused
by the sandbox too; run it outside, or let the unsandboxed retry take it.

## See also

- [QUICKSTART.md](QUICKSTART.md) — install + verify walkthrough
- [WORKFLOW.md](WORKFLOW.md) — day-to-day loop once grounded
- [CONVENTIONS.md](CONVENTIONS.md) — what grounding populates
