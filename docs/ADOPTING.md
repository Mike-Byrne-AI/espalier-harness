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

## See also

- [QUICKSTART.md](QUICKSTART.md) — install + verify walkthrough
- [WORKFLOW.md](WORKFLOW.md) — day-to-day loop once grounded
- [CONVENTIONS.md](CONVENTIONS.md) — what grounding populates
