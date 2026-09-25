# Memory systems

Espalier-Harness and Claude Code both carry knowledge across sessions, and
several distinct mechanisms all get called "memory." Two of them were even
named the same file — `MEMORY.md` — until Espalier renamed its committed copy
to `ESPALIER_MEMORY.md` to end that collision (Claude Code's auto-memory name is
hardcoded and cannot move). This document is the canonical model: what each
system is, how it actually reaches the model, and the one rule for deciding
which system owns a given piece of knowledge.

## The four systems

| System | Where | Scope | Who writes | How it reaches the model |
|---|---|---|---|---|
| **Auto memory** (Claude Code) | `~/.claude/projects/<project>/memory/` | per-project, machine-local, **not committed** | Claude writes; you edit/delete | `MEMORY.md` auto-loaded each session (first 200 lines or 25 KB); topic files read on demand |
| **CLAUDE.md ladder** (Claude Code) | managed-policy → `~/.claude/CLAUDE.md` → repo `./CLAUDE.md` → `./CLAUDE.local.md` | machine / user / project / local | you | loaded in full every session (ancestors at launch; nested dirs on demand) |
| **Espalier committed memory** | repo `ESPALIER_MEMORY.md` + `memory/` | committed, portable, review-visible | Espalier hooks + you | SessionStart hook injects a digest of `ESPALIER_MEMORY.md`; long-form `memory/` files pulled via `/recall` |
| **Claude.ai web memory** | account cloud | account-global | the app | not part of Claude Code — a separate product |

Only the first two are native Claude Code mechanisms (the docs call them "two
complementary memory systems"). The third is a construct Espalier layers on
top — committed files bound into the session by a hook. The fourth is a
different product and is listed only so it is not confused with the others.

## How auto memory actually works

Verified against the Claude Code memory documentation
(<https://code.claude.com/docs/en/memory>):

- **Storage.** Each project gets `~/.claude/projects/<project>/memory/`. The
  `<project>` segment is derived from the git repository, so every worktree
  and subdirectory of one repo shares a single auto-memory directory. It is
  **machine-local** — not committed, and not shared across machines or cloud
  environments.
- **Injection cap.** "The first 200 lines of `MEMORY.md`, or the first 25KB,
  whichever comes first, are loaded at the start of every conversation."
  Content past that threshold is not loaded at session start. `MEMORY.md` is
  an **index**; Claude moves detail into topic files (`debugging.md`, …) that
  are read on demand, not at startup.
- **Who writes.** Claude writes auto memory itself, from your corrections and
  the things it discovers; you can read, edit, or delete any of it via
  `/memory`. It is on by default (`autoMemoryEnabled` /
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` toggle it).
- **Advisory, not enforced.** Both auto memory and CLAUDE.md are "context, not
  enforced configuration." To make something hold regardless of the model's
  judgment, the docs point to a **PreToolUse hook** — which is exactly the
  layer Espalier already governs. So auto memory is an *advisory* channel; it
  cannot make the model "just know" a rule in a binding way. This is the same
  split Espalier's standing principles draw: hooks are the enforcement layer,
  memory (of every kind) is advisory.

## The two memory files (formerly both `MEMORY.md`)

Two different systems each put a memory file in front of the model. Until
Espalier renamed its committed file to `ESPALIER_MEMORY.md`, **both were named
`MEMORY.md`** — and conflating them is the recurring confusion this document
exists to prevent (and the confusion the rename was meant to retire):

| | Espalier committed `ESPALIER_MEMORY.md` | Auto-memory `MEMORY.md` |
|---|---|---|
| Path | repo root (`./ESPALIER_MEMORY.md`) | `~/.claude/projects/<project>/memory/MEMORY.md` |
| Committed? | yes — travels with the repo | no — machine-local |
| Written by | Espalier hooks + you | Claude |
| Reaches the model via | SessionStart hook digest + `/recall` | Claude Code's native 200-line / 25 KB auto-inject |
| Cap | ~120-line index (Espalier convention) | 200 lines / 25 KB (Claude Code) |

They are different systems with different owners, lifecycles, and audiences.
When a session says "write it to memory," decide *which* memory with the rule
below.

## The sorting rule

> Is this about the **operator / machine / collaboration**? → **auto memory**.
> Is this about the **harness / its code / its discipline**? → the **repo**
> (`memory/`, `docs/`).

Worked examples:

- "The interpreter here is `python3`, not `python`." → **auto memory**
  (machine fact).
- "Prefer `pnpm test`; commit straight to `main` on this project, no branch."
  → **auto memory** (operator / collaboration preference Claude discovers).
- "The repo-root walkers must skip embedded nested git repos, or fixture setup
  breaks." → **repo `memory/`** (a footgun in the harness's own code).
- "A dedup catalog's 'collapse to canon' is a *claim* — classify intent before
  prescribing." → **repo `memory/` + `docs/`** (a durable review discipline).

### When the lesson is about the harness but already canonized

A harness-discipline lesson is not automatically a *new* repo file. First check
whether it is already a `docs/STANDING_PRINCIPLES.md` principle, a
`docs/sharp-edges/` entry, or a `memory/` protocol. If it is, the correct home
is a **pointer**, not a duplicate. The rule is three-way, not two:

- **Already canon in the repo** → collapse the machine-local note to a one-line
  pointer at the repo canon (keeps the auto-memory index priming the topic;
  avoids a `/recall` twin that dilutes ranking across two copies of one idea).
- **Harness lesson, no repo home yet** → migrate: a footgun goes to
  `docs/sharp-edges/`, a durable review discipline to `memory/`.
- **Operator / machine / collaboration** → stays in auto memory.

The pointer line has a **literal form**, because the detector keys on it. Write
it as a blockquote with one of these two exact markers:

```markdown
> **Migrated to the repo:** this lesson now lives at `memory/<slug>.md`.
> **Canonized in the repo:** see `memory/<slug>.md`.
```

A third spelling is not a style choice — `tools/cc/memory_sort_audit.py` will
read it as an un-collapsed duplicate and report drift that isn't there. If you
genuinely need new wording, add it to `_POINTER_MARKERS` in the same commit.

The failure this prevents is the *duplicate*, not the misfile: an entry that
lives in full in both stores has two editable copies that drift apart, and
neither side knows which is current. One home per fact, with a pointer if the
other side needs to find it.

`tools/cc/memory_sort_audit.py` flags backslide against this rule — see
[Maintaining the split](#maintaining-the-split).

The reason the split matters: only the repo layer ships. Auto memory never
travels to a teammate or an adopter, so any knowledge that must govern the
harness for *everyone who clones it* has to live in the committed repo. Auto
memory is the operator/machine layer and the router *into* the committed
source of truth — not a substitute for it.

## Maintaining the split

Auto memory drifts toward holding harness-discipline lessons, because the base
reflex when asked to "remember" is to write auto memory. Re-sort periodically:

1. For each auto-memory entry, apply the sorting rule.
2. If it is **harness / code / discipline**, move it into the repo `memory/`
   in the repo's format (`# Title`, a `Status:` line, and — for a lesson — the
   *why* and *how to apply*), add a one-line pointer from the committed
   `ESPALIER_MEMORY.md` index, then delete it from auto memory.
3. If it is **operator / machine / collaboration**, leave it in auto memory.
4. Never duplicate an entry across both systems — one home per fact, with a
   pointer if the other side needs to find it.

The migration is applied by Claude to its own auto memory (auto memory is not
in the repo, so it is not a repo change); this document is the method it
follows.

To find backslide instead of hunting for it by eye, run the detector:

```bash
python3 tools/cc/memory_sort_audit.py    # advisory; silent when clean, exit 0 always
```

It reports two drift classes — an auto-memory entry duplicating a committed
twin instead of pointing at it, and a `memory/` entry whose reverse-link header
claims a home that does not link back. The committed twin population the
duplicate-scan reads is the whole committed knowledge layer: `memory/*.md`, the
per-file `docs/sharp-edges/*.md`, `docs/STANDING_PRINCIPLES.md`, and — keyed by
section heading — the monolithic docs `docs/SHARP_EDGES.md`,
`docs/FAILURE_MODES.md`, `docs/CONVENTIONS.md`, and
`docs/AUTONOMOUS_EXECUTION.md`. Reading the monolithic docs at section
granularity is what catches a note duplicating one *section* of a multi-lesson
doc (the sorting rule routes footguns and failure-modes there), not just a
whole-file twin. A periodic `/handoff`-adjacent check;
deliberately **not** a wired blocking gate, because the knowledge store is an
advisory channel and blocking a session on store tidiness is the wrong
friction. Note it cannot see another machine's auto memory — it audits the
store on the host it runs on.

## See also

- Your project's `CLAUDE.md` — the operating home for the sorting rule and a
  trigger-tied recall discipline (a "## Memory systems" section).
- [../memory/README.md](../memory/README.md) — the convention for the
  committed `memory/` cool-store.
- `examples/auto-memory.template.md` (in the Espalier source) — a starter for
  your own auto-memory `MEMORY.md` that routes into the committed repo.
