Pre-flight scope analysis for a task pack.

Walks the codebase for references to every symbol the pack declares in its
`## Affected symbols` section and reports which references fall inside the
pack's `Scope (in)` versus outside. Use before drafting `cc/execution_plan.json`
to surface integration depth the pack might be undercounting — `/implement-pack`
Step 0 invokes this automatically when a pack is given.

A pack whose blast radius is a raw **literal** (a filename, an env var, a config
key) has a thin symbol surface, so a clean symbol scan is not coverage. Declare
the token under `## Affected literals` and scope-check walks it tree-wide too,
partitioning hits into target / excluded / ambiguous (see `docs/PACK_AUTHORING.md`).
Even undeclared, a literal/path-keyed pack (a `git mv`, or a renamed-file token)
draws a `[warn]` so a rename never exits "0 gaps" silently.

## Usage

```
/scope-check <path-to-TP-NN.md>
/scope-check <path-to-TP-NN.md> --accept-scope-gap "<reason>"
```

The argument is the same path you'd pass to `/implement-pack`. The wrapper
runs:

```bash
python -m espalier scope-check <pack-path>
```

## Exit-code semantics

| Exit | Meaning | Next action |
|---|---|---|
| 0 | No scope gap detected, or gap acknowledged via `--accept-scope-gap` | Proceed to `/implement-pack` |
| 1 | Nothing parsed. Either nothing to walk (neither `## Affected symbols` nor `## Affected literals` is declared, or every bullet declares nothing on purpose): a clean skip. Or a DECLARED section parsed to zero entries: the report carries a `scope-check: DECLARED_BUT_EMPTY --` line and the chain driver treats it as an errored probe, not a skip (the cause is printed) | With the marker: fix the pack so a bullet parses; see `docs/PACK_AUTHORING.md`. Without it: proceed |
| 2 | Scope gap present, not acknowledged — a symbol ref outside `Scope (in)`, OR an ambiguous `## Affected literals` hit | Either widen `Scope (in)` to cover the gap (or add it to the literal's `EXCLUDE:`), or pass `--accept-scope-gap "<reason>"` |

The pre-flight is a signal, not a gate — the test suite is the actual
correctness boundary. `--accept-scope-gap` records the operator's
decision and exits 0 so the next step (`/implement-pack`) can proceed.

## Report shape

_(`docs/SURFACE_SUPPORT_MATRIX.md` below is Espalier source repo — not deployed by `init`.)_

Per affected symbol the report shows:

- Total reference count across the repo.
- A risk tag drawn from `docs/SURFACE_SUPPORT_MATRIX.md` (not deployed) when
  the symbol matches a row: `[HIGH-RISK]` for `guarded`,
  `[MEDIUM-RISK]` for `supported`, raw status label otherwise.
  That matrix is **self-host only and not deployed by `espalier init`** — in an
  adopter repo no symbol matches a row, so every symbol reports untagged. The
  reference count is the signal there.

Then the report partitions files into:

- `Files in pack Scope (in):` — references the pack already declares.
- `Files NOT in pack scope (gap):` — references the operator might
  not have anticipated. This is the high-leverage portion: each entry
  is a file that exists in the codebase, references the pack's
  symbols, and isn't declared as a touched file.

For each out-of-scope file the report prints up to 20 reference lines
(line number + context). Pass `--max-refs-per-file <N>` to widen or
narrow.

When the pack declares `## Affected literals`, the report adds:

- `Literal reference scan:` — one line per declared literal with its
  target / excluded / ambiguous hit counts.
- `Literal refs NOT classified (gap):` — every ambiguous literal hit
  (in neither `Scope (in)` nor an `EXCLUDE:` glob). Any ambiguous hit
  forces exit 2, like an out-of-scope symbol ref.

## When to use

- **Pack authoring:** run as soon as `## Affected symbols` is drafted.
  Iterate on the section + `Scope (in)` until either the report shows
  no gap, or you've reasoned through the gap and named it via
  `--accept-scope-gap`.
- **Pack review:** run before approving a pack PR to verify the
  scope claim matches the codebase reality.
- **Retrofitting:** run against an older pack (with a freshly added
  `## Affected symbols` section) to retroactively check what the
  original execution would have surfaced.

## See also

- `docs/PACK_AUTHORING.md` — required format for the `## Affected
  symbols` section.
- `docs/SURFACE_SUPPORT_MATRIX.md` (self-host only) — surfaces the classifier consults
  for risk tagging. Self-host only; absent in an adopter repo.
- `/implement-pack` — Step 0 invokes scope-check automatically.
