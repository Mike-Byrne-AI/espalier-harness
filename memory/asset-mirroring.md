# Asset mirroring (3-way SoT)

**Status:** active
**Linked from:** espalier/assets/CLAUDE.md ("Read first")

Accumulates lessons from maintaining the asset-source-of-truth
pattern.

## The 3-way mirror

For `.claude/` agents / commands / skills, the harness keeps three
mirrors:

1. **`.claude/<area>/<file>`** — the SINGLE SOURCE OF TRUTH: the live
   self-host config Claude Code loads. Hand-edit here only.
2. **`espalier/assets/claude/<area>/<file>`** — GENERATED; shipped in
   the wheel, deployed to adopters by `init`.
3. **`examples/dogfooding/.claude/<area>/<file>`** — GENERATED; the
   adopter-facing reference example (per TP-31), shipped in the sdist.

The live shape: `.claude/` is the SoT; `espalier init` deploys the
roster from the `espalier/assets/claude/` mirror into an adopter's
`.claude/` (TP-50 reinstated this — TP-31 had removed the deploy loop),
honoring user edits via the `espalier:managed` marker. Both mirrors are
regenerated from the `.claude/` SoT by `scripts/sync_claude_mirrors.py`.

## The parity contract

`tests/test_package_resource_parity.py` enforces byte-equality (modulo
line endings) across all three legs: `TestRootMirrorParity` pins
`.claude/<area>` ↔ `examples/dogfooding/.claude/<area>` and
`TestAssetClaudeMirrorParity` (TP-151 G-4) pins
`espalier/assets/claude/<area>` ↔ the dogfooding reference, for
`area in {agents, commands, skills}`. `TestClaudeMirrorGenerator`
additionally pins that the committed mirrors are EXACTLY what the
generator produces from the SoT.

Edit the `.claude/` SoT, then regenerate the two mirrors with the
generator (do NOT hand-`cp` or hand-edit a mirror):

```bash
# Edit .claude/agents/X.md (the SoT), then:
python scripts/sync_claude_mirrors.py
pytest tests/test_package_resource_parity.py -q
```

`.gitattributes` pins `*.md text eol=lf` so the trees stay
byte-identical on every platform. The parity tests fail loudly if any
leg drifts.

## The wheel package-data class-of-bug (TP-90)

When a new content surface is added under `espalier/assets/<area>/`,
TWO surfaces must be updated for the wheel to ship it:

1. `pyproject.toml [tool.setuptools.package-data]` — add the glob
   pattern (e.g., `"assets/memory/*.md"`).
2. `tests/test_wheel_install_surface_parity.py::COMPARED_ROOTS` — add
   the runtime path (e.g., `"memory"`) so the parity test exercises
   it on every wheel build.

TP-88 added `assets/memory/README.md` + `assets/docs/sharp-edges/README.md`
but didn't update either surface. The result: built wheel had 0
paths under `memory/` or `docs/sharp-edges/`; adopter `pip install`
hit `FileNotFoundError` at cli.py's `as_file(source_node)` deploy load.
Caught by the 4-agent pre-cut deep-dive (failure-mode-reviewer's
supply-chain instinct). Fixed in TP-90.

**Rule**: every new `assets/<X>/<Y>` surface needs the
package-data glob AND the COMPARED_ROOTS entry. Build a wheel and
empirically check the content lands:

```bash
python -m build --wheel --outdir /tmp/wheel-check .
python -c "import zipfile; z = zipfile.ZipFile('/tmp/wheel-check/<wheel>'); print([n for n in z.namelist() if 'X' in n])"
```

## Wheel-safe asset resolution

`espalier/assets.py` provides the canonical resolver:

- `assets_root() -> Traversable` returns `files("espalier").joinpath("assets")`.
- For non-`.claude/` assets, use `assets_root().joinpath(*relpath.split("/"))`.
- For a deploy that needs a real `Path` in a wheel-installed environment,
  materialize via the `as_file(traversable)` context manager. A *read* does
  not need it -- `traversable.read_text(encoding="utf-8")` is wheel-safe
  (see the seed-doc loop below).

The seed-doc loop (`cli._deploy_seed_docs`, shared by `cmd_init` and
`cmd_upgrade`) renders and writes through two shared helpers:

```python
from espalier.managed_inventory import get_seed_docs, render_seed_body

outcome = {"created": [], "refreshed": []}
for dest_relpath in get_seed_docs():
    dest = repo_root / dest_relpath
    existed = dest.exists()
    if _write_seed(dest, render_seed_body(dest_relpath), label=dest_relpath, dry_run=dry_run):
        outcome["refreshed" if existed else "created"].append(dest_relpath)
```

`label` is required (the root-relative path the stderr line prints; the
basename default printed two seeds as `README.md`, DEF-774) and `dry_run`
answers through the same decision without writing, which is how `upgrade`'s
preview names the seeds `--execute` will refresh.

`render_seed_body` reads the packaged asset straight from the
`assets_root()` Traversable (a read needs no `as_file`
materialisation), resolves the two grounding stubs through
`get_seed_asset_source`, and prepends `SEED_ADAPT_HEADER` for a Tier-2
seed. It lives in `managed_inventory`, not `cli`, because `doctor`
prints `render_seed_stamp` -- the stamp of that same body -- for a seed
whose first line is gone (DEF-696); one renderer, so the printed stamp
and the written one cannot drift. The `as_file` context manager is still
the pattern for a deploy that needs a real `Path` (the CI workflow copy):
it materialises the resource to a temp file when running from a wheel and
returns the real path directly in source-checkout mode.

## Deploy helpers — when to use which

`espalier/cli.py` has three deploy functions; their semantics
differ in how they handle drift between asset SoT and what's on
disk:

| Helper | Existence semantics | Use case |
|---|---|---|
| `_write_seed(dst, rendered, *, label, overwrite=False, dry_run=False)` | Seed docs: seed-version-stamp aware — writes `rendered` (from `managed_inventory.render_seed_body`) under `seed_stamp_line`; refreshes an operator-untouched-but-stale copy, preserves an edited or legacy-unstamped one (TP-348). Until 2026-09-05 this was the non-`.py` branch of a path-based `_deploy_file` that also rendered the body. | Adopter init for content operators may edit (memory/README.md, the Tier-2 seed docs); shared by `cmd_init` + `cmd_upgrade` via `_deploy_seed_docs`. |
| `_deploy_managed_py(src, dst)` | compares marker + drift; regenerates managed copies | Hook scripts (`tools/cc/hooks/*.py`). Drift detection via TP-03 `# espalier:managed` marker. |
| `_deploy_asset_md(src, dst)` | compares hash; regenerates managed | `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`. Similar to managed_py but for markdown. |

The TP-88 README deploys use `_write_seed` (operator-edit
preservation). The class-of-bug once **deferred** here — managed-vs-edited
drift for non-`.py`, non-`.claude/` assets, where a re-deploy kept the old
`memory/README.md` bytes even for an operator who never touched it — is
**resolved by TP-348** via the second resolution shape: an in-file
`espalier:seed-version` stamp written by `_write_seed`,
refreshing only a hash-verified-untouched copy (see `_seed_redeploy_decision`).
The rejected alternative (routing seeds through `_deploy_asset_md`) would have
injected `espalier:managed` and flipped the seed lifecycle — `cleanup.py` would
reclassify a marked seed as *deletable* and regenerate a marked-and-edited
Tier-2 doc, clobbering the operator's adaptation. The distinct `seed-version`
token keeps `clean-generated` treating the seed as operator-owned.

## Sister-site sweep discipline

When a class of edit applies to N assets, sweep ALL of them in the
same change set. TP-87's first pass scrubbed 4 common-tier asset
bodies (architecture-analyst, failure-mode-reviewer, debug skill,
arch-check skill) of harness-specific narration. The 4-agent
pre-cut deep-dive surfaced 3 sister sites (code-reviewer.md,
test-writer.md, review/SKILL.md) that needed the same treatment but
were left in the original pack as deferred 87-6.

TP-90 swept them. The pattern: when authoring an edit class, grep
the WHOLE tier for the same shape:

```bash
grep -l "harness-specific\|Espalier-Harness-specific" .claude/agents/ .claude/skills/
```

…and either widen the pack scope or explicitly defer with a
named-pack reference (e.g., "87-6 follow-up").

## Full-surface deploy + asset hygiene (tier split retired)

`espalier init` deploys the **full** managed surface — every packaged
agent, command, and skill — to every repo. There is no common /
harness-dev tier split: the `HARNESS_DEV_ASSETS` allowlist, the
`--tier` / `--include-harness-dev` flag, and self-host tier
auto-detection were **retired by TP-212** once every asset became
adopter-relevant. (The earlier model gated a ~12-entry harness-dev
roster behind a flag opened by `--tier harness-dev` or self-host
auto-detection; that distinction no longer exists.)

Because every asset now ships to every adopter, **every** asset body
must be adopter-fit — no harness-internal narration as the working
assumption.

`tests/test_init_tier_split.py::TestCommonTierAssetHygiene` pins it:

- No internal `TP-NN` / `BC-NNN` pack IDs in shipped asset bodies
  (TP-80 contract).
- No reference to harness-only tools (e.g.,
  `tools/review_agent_audit.py` — TP-72 contract).

## The sibling pattern: artifacts that travel WITH the engine (`_vendor/`)

The 3-way `.claude/` mirror above is ONE of two instances of a single
meta-pattern — **SoT → generated mirror → sync-script → parity-test →
per-level package-data glob**. They differ only in DESTINATION:

> **The census of mirror rows is NOT here.** Its sole home is
> [`espalier/mirror_registry.py`](../espalier/mirror_registry.py) — one row per
> `(SoT, mirror)` pair a test byte-pins, with each row's sync script, pinning
> test, comparator, curated-vs-whole-tree `kind`, and direction. Read the count
> off that module, never off a table. This file kept its own list for a while and
> drifted to four rows when the answer was seven; the table below is deliberately
> about a *different* axis — how a mirror reaches the adopter — which the registry
> does not model.

| Instance | Which rows | Reaches the adopter by |
|---|---|---|
| Deploy-into-tree | `claude-dogfooding`, `claude-asset` | `init` COPIES it into the adopter's `.claude/` |
| Travel-with-engine | `vendor-cc`, `selfcheck-tests` | rides the wheel + `fuse` overlay; run from the INSTALLED location, NEVER copied into the adopter tree |
| Ship-as-package-data | `asset-docs`, `task-packs-router` | shipped inside the wheel and read from there |
| Generated-into-this-repo | `harness-guard` | **inverted** — the packaged asset is the SoT and this repo's `.github/workflows/` copy is generated from it |
| Chained | `pack-checklist`, `reasoning-checklist` | **two hops** — each mirror IS another row's source (see below) |

**The chained rows, and why their order is load-bearing.** `pack-checklist` and
`reasoning-checklist` each render a canonical `tools/cc/` checklist into a marked
region of a shipped `.claude/` body (`commands/implement-pack.md` and
`skills/reflect/SKILL.md` respectively). Neither target is a leaf:
it is the *source side* of `claude-asset` and `claude-dogfooding`. So the adopter
copy is two hops away, and the syncs have an order —

```
tools/cc/{pack_artifact,reasoning_review}_checklist.md
  └─ sync_checklist_regions.py  →  .claude/{commands/implement-pack,skills/reflect/SKILL}.md
       └─ sync_claude_mirrors.py  →  espalier/assets/claude/ + examples/dogfooding/.claude/
```

— which is the one thing a reader is likely to get wrong, because every other row
in the census is a single hop. Run them in that order; running only the second
propagates a stale region into both mirrors byte-perfectly. The SoT itself is
never deployed (`tools/cc/*.md` is not in `INIT_TOOL_SCRIPTS` and not package
data), which is *why* the items are inlined at all: an earlier version told
adopters to read a file they would never receive.

`_vendor/cc/` is the deploy SOURCE that `init`/`install-ci` copy from (so
`espalier/` never imports `tools/`); `_vendor/selfcheck_tests/` is run by
`espalier selfcheck` against the installed mirror in a tmp cwd, so the adopter
tree is never the pytest rootdir.

**Two gotchas, both load-bearing:**

- A `_vendor/<dir>/**` *recursive* package-data glob sweeps `__pycache__/*.pyc`
  (env-specific bytecode) into the wheel — use per-level `*.py` / `*.ini` globs
  (the `_vendor/cc/` precedent). A stale `build/` dir can re-inject the pyc; clean
  both. (TP-226c)
- `run_selfcheck` must hand the running engine's import root to its `pytest`
  subprocess (`env=` with `PYTHONPATH` = the `espalier` parent dir): the throwaway
  cwd means the subprocess cannot import `espalier` off the cwd, so without it the
  channel works only when pip-installed and `ModuleNotFound`s on a source checkout
  (env-relative green). (f1867a3)

The travel-with-engine half is also a **positioning** signal — a trust tool that
"doesn't move into your house" (the workbench travels with the engine); see the
workshop frame in `docs/POSITIONING.md`.

## See also

- `docs/CONVENTIONS.md` "Categorized memory + sharp-edges" — the
  read-time/write-time split this file participates in.
- `tests/test_package_resource_parity.py` — TP-01 + TP-31 parity
  contracts.
- `tests/test_wheel_install_surface_parity.py` — wheel-vs-source
  parity for content surfaces (TP-90's `COMPARED_ROOTS` lesson).
- `tests/test_skill_tier_contract.py` — a shipped skill body must not
  name an agent that doesn't resolve to a real agent file. The
  surviving invariant of TP-80's tier contract; its
  `bench/corpus/BC-043-*.json` row (a common-tier skill referencing a
  harness-dev agent) was removed with the deploy tier by TP-212.

## An in-place edit skips the mirror advisory (2026-09-12)

The PostToolUse advisory that names the sync for a mirrored row fires on the
Edit and Write tools. A Bash in-place edit of a mirrored file (a
`python3 - <<EOF` replace, a `sed -i`) raises nothing, and the next full tier
reds on the mirror instead: `tests/test_analyze.py` is byte-mirrored into
`espalier/_vendor/selfcheck_tests/` (`scripts/sync_selfcheck_tests.py`), and
one in-place edit of its predicate pin cost four reds in the group-6 tier --
three selfcheck runs of the stale copy plus the byte-parity test. After any
in-place edit, grep `espalier/mirror_registry.py` for the file's row and run
its sync before the tier; the registry is the census, not this note.
