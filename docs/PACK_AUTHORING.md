# Pack Authoring Guide

A task pack is the unit of planned work in Espalier-Harness. Each pack
proposes a focused change set, declares its scope in prose, and ships
verification steps. This guide covers the conventions a pack must
follow so the `espalier scope-check` pre-flight can reason
about it.

## Standard pack sections

Most existing packs already use this shape. It is shown here for orientation
and is **deliberately partial** — this guide covers what `scope-check` reasons
about, and the full required-section list has one home, the
`blueprint-authoring` skill (`.claude/skills/blueprint-authoring/SKILL.md`).
Read that before authoring; it carries the parts a parser cannot check.

```markdown
# TP-<N> — <one-line title>

## Status
…

## Motivation
…

## Scope (in)
…

## Scope (out)
…

## Task 0 — Verify     ← the oracle, the refuting result, and the exit
…                        its licensed outcomes include "do not build this"

## Affected symbols
…

## Reach          ← required only when the pack claims to close a class
…

## Implementation
…

## Pass criteria
…
```

`Scope (in)` and `Scope (out)` are prose; the parser only requires
that file-shaped tokens appear in backticks. On the Espalier-Harness source
tree `Scope (out)` is also machine-read (`scripts/check_pack_landing.py::scope_out`,
self-host tooling): the ledger's strike verb refuses to close a row an active
pack's Scope (out) still cites, and a gate requires every pack id named there
to resolve. So spell a row id with its prefix in backticks (`DEF-412a`) or as
a backticked list of tails, and name a pack id only when the pack exists.

List style does not matter: `- ` bullets, markdown table rows (`| … |`)
and ordered items (`1.`, `10.`, `3)`) are all read, and a path on a
wrapped continuation line still counts. Ordered items were added after a
census found that packs writing a numbered `Scope (in)` declared **zero**
files, so the pre-flight reported every reference as a scope gap and its
output carried no signal.

## The `Affected symbols` section

`espalier scope-check` reads this section to build the symbol list it
greps for. Without the section, the pre-flight can't run and exits
with status 1.

```markdown
## Affected symbols

### Removed paths
- `path/A` — reason
- `path/B/` — reason

### Renamed symbols
- `old_name` — see X-Y; renamed to `new_name`

### Changed semantics
- `symbol` — old behavior → new behavior

### Added paths/symbols
- `new_path` — purpose
- `new_function` — purpose
```

Format rules:

- The section heading is `## Affected symbols` (case-sensitive).
- Each subsection is `### <one of the four labels>`.
  - `Removed paths`
  - `Renamed symbols`
  - `Changed semantics`
  - `Added paths/symbols` (the alias `### Added` is also accepted)
- Each bullet starts with `- ` and the symbol/path goes in the first
  pair of backticks: `` `name` ``.
- An em-dash (`—`) or hyphen (`-`) introduces the description.
- The parser stops at the next `## ` header, so put `Affected symbols`
  before `## Implementation`.
- A bullet struck through (`~~...~~`) is withdrawn: the parser and the
  pre-flight skip it, a wrapped strike included, and `scope-check` says
  which token the strike withdrew. Keep the record of why as prose above
  the list. `<del>` and a `STRUCK:` prefix are not honoured and are
  reported.
- A sub-section that declares nothing says so: `- (none — ...)` or
  `- None.`. A bullet under one of the four sub-headings above that names
  no backticked token is one the walk cannot see; `scope-check` prints it
  as a `!` line, and a pack whose bullets all sit under a sub-heading the
  pre-flight does not route is told which heading that was.
- A doc path is not a symbol. Declared here, a path such as
  `docs/CONVENTIONS.md` is grepped as a token and draws every prose mention
  of the file tree-wide (measured 2026-09-23: one maintainer doc drew 372
  hits, all but three in records and read-only citations), so the report
  carries no signal. Declare the operand the edit replaces under
  `## Affected literals` instead, with `EXCLUDE:` globs for the sites where
  the token is right as it stands.

## The `Affected literals` section

`scope-check` walks *symbols* (functions, classes, constants). A pack
whose blast radius is a raw **literal** — a filename, an env var, a
config key — has a thin symbol surface, so a clean symbol scan is NOT
coverage: the string the change is keyed on is invisible to the symbol
walk. Declaring the literal turns that blind spot into a checked
partition.

```markdown
## Affected literals

- `MEMORY.md` — a committed filename being renamed (an Espalier source repo
  example; here, to
  `ESPALIER_MEMORY.md`); trace the OLD token to find every committed-file
  reference, and EXCLUDE the files where it means something else.
  EXCLUDE: docs/MEMORY_SYSTEMS.md, examples/auto-memory.template.md
```

Format rules:

- The section heading is `## Affected literals`.
- Each bullet's first backticked token is the literal traced tree-wide.
- An em-dash (`—`) or hyphen (`-`) introduces the description.
- An optional `EXCLUDE:` clause (on the bullet or a wrapped continuation
  line) is a comma-separated list of file globs where the token
  legitimately appears **unchanged** — a homonym twin (e.g. the committed
  file, now `ESPALIER_MEMORY.md`, vs. Claude's auto-memory `MEMORY.md`
(machine-local, not deployed by `init`), which
  historically shared the name). Globs are
  `fnmatch` patterns; a bare directory (`examples/`) excludes everything
  under it. Note `*` matches across `/` (so `*.md` excludes **every**
  `.md` file tree-wide, not one directory) — keep EXCLUDE globs tight, or
  an over-broad one silently swallows real hits. The report lists the
  excluded files (capped) under each literal so an over-broad glob is
  visible rather than a silent "0 ambiguous".

Each declared literal is walked tree-wide and its hits are partitioned:

- **target** — the hit is inside `Scope (in)` (the change will cover it).
- **excluded** — the hit matches an `EXCLUDE:` glob (a homonym twin,
  left alone).
- **ambiguous** — neither. An unaccounted-for occurrence a blind `sed`
  would corrupt. Any ambiguous hit is a scope gap (exit 2) until you
  widen `Scope (in)`, add it to `EXCLUDE:`, or acknowledge it with
  `--accept-scope-gap`.

Even without a declaration, a pack that looks literal/path-keyed (a
`git mv`, or a renamed-file token in `## Affected symbols`) draws a
`[warn]` nudging you to declare its literals — so a rename pack never
exits "0 gaps" silently.

## Running `espalier scope-check`

```bash
espalier scope-check "task-packs/TP-N-your-pack.md"
```

Three exit codes:

| Exit | Meaning |
|---|---|
| 0 | No scope gap, or operator accepted the gap with a reason |
| 1 | Nothing parsed. Either nothing to walk (neither section is declared, or every bullet declares nothing on purpose): a clean skip. Or a DECLARED section parsed to zero entries (the cause is printed -- an unrouted sub-heading, bullets with no backticked token, an empty literals section) and the report carries a `scope-check: DECLARED_BUT_EMPTY --` line, which the chain driver reads as an errored probe, not a skip |
| 2 | Scope gap present and not acknowledged — a symbol ref outside `Scope (in)`, OR an ambiguous `## Affected literals` hit |

The report shows, per affected symbol:

- Total reference count across the repo.
- Risk tag drawn from `docs/SURFACE_SUPPORT_MATRIX.md` (Espalier source repo — not deployed by `init`;
  in an adopter repo no symbol matches a row and every symbol reports
  untagged):
  `[HIGH-RISK]` for `guarded` surfaces, `[MEDIUM-RISK]` for
  `supported`, raw status label for others.

The report also separates files referenced inside `Scope (in)` from
files referenced outside. The "outside" list is the pre-flight's
contribution — references the pack didn't anticipate.

When a pack declares `## Affected literals`, the report adds a
`Literal reference scan:` line per literal (with its target / excluded /
ambiguous counts) and a `Literal refs NOT classified (gap):` block
listing every ambiguous hit — the literal-arm twin of the symbol gap
block.

## Accepting a scope gap

`scope-check` is a signal, not a gate. If the operator deliberately
chooses test-driven discovery over scope expansion, run:

```bash
espalier scope-check <pack> --accept-scope-gap "test-driven discovery on small pack"
```

The reason is printed and the exit code becomes 0. The test suite is
still the actual gate — pack execution proceeds regardless.

## When `scope-check` underclaims or overclaims

The walker is intentionally simple: literal string match (via ripgrep
or a Python fallback) plus AST imports. It will miss:

- References via dynamic attribute access (`getattr(module, sym_name)`).
- References inside data files that aren't `.md` / `.json` / `.toml` /
  `.yaml`.
- Symbol renames where the old and new names differ by case only
  (it's a fixed-string search).

It will over-claim when:

- A common token appears in unrelated contexts (e.g. searching for
  `agents` matches both `.claude/agents/` paths and the literal token
  in `experiment-analyst` agent names).
- A test fixture string mentions the path by happenstance.

The recommended workflow: run `scope-check` early in pack drafting,
review the report, expand `Scope (in)` if the surfaces are
legitimately in flight, and rely on the test suite for the final
correctness gate.

## The `Reach` section

Required whenever a pack claims to close a **class** — a defect family, a
pattern with N sites, anything counted.

**Target size is not reach.** "This class has 47 members" is a fact about the
problem. "This mechanism closes 47 members" is a claim about the fix, and it
needs its own measurement. Both are real numbers, which is exactly why they get
confused: writing one *feels* like having measured the other.

State reach per member, by id, before execution:

```markdown
## Reach

| Item | Status | Evidence |
|---|---|---|
| `DEF-484` | CLOSED | mechanism driven against it; goes red |
| `DEF-473` | NOT REACHED | absence-shaped — a positive match cannot express an omission |
```

- **Per-member, not aggregate.** "closes most of the class" is not reach.
- **Cannot enumerate yet?** Make the enumeration the pack's first sub-task and
  give it a **stop condition**: *"if fewer than N are reachable, re-raise rather
  than build."*
- **Say what is NOT reached, and why** — otherwise a later pass reads the class
  as shut.
- **Avoid "closes toward".** The hedge carries the whole claim while reading as
  a measurement.

The failure this prevents is not carelessness. A pack can cite accurately, scope
honestly, order its sub-tasks correctly, and still be built on a mechanism that
reaches almost none of what it names — because the author measured how big the
problem was and never measured how much of it the fix touches.

## Authoring discipline

Three habits keep `scope-check` informative:

1. **Mention every directory you touch in `Scope (in)` with a trailing
   slash.** `path/` matches all files under `path/`; `path` only
   matches the file at exactly `path`. (The walker treats both as
   prefixes when the token has no extension, but explicit is better.)
2. **List every symbol your change adds, renames, or removes in the
   `Affected symbols` section.** The reference graph is only as good
   as the symbol list you give it.
3. **Re-run `scope-check` after expanding `Scope (in)`.** A clean
   `✓ No scope gaps detected.` means the pack and the codebase agree
   on what's in flight.

## Citing the tree

How a pack should write a claim about the repo — cite by symbol rather than by
line, state a baseline as the command that derives it, and never restate a
count another surface owns — has one home: the **`blueprint-authoring` skill**
(`.claude/skills/blueprint-authoring/SKILL.md`, section *Citing the tree*),
which also defines the `target=` tag that marks a fence as prescribed rather
than quoted. It is deliberately not restated here: a rule kept in two places
drifts, and this guide already shares its `Reach` section with that skill.
