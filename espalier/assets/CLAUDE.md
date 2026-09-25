# espalier/assets/

**Doing:** Wheel-shipped asset content that `espalier init` deploys into adopter repos. For `.claude/` agents/commands/skills this tree is **GENERATED, not authored** — the live `.claude/{agents,commands,skills}` is the single source of truth. Hook scripts + README templates are authored here.
**Don't break:** `.claude/` triplet SoT pattern — hand-edit the live `.claude/{agents,commands,skills}` ONLY, then run `python scripts/sync_claude_mirrors.py` to regenerate this `assets/claude/` copy AND `examples/dogfooding/.claude/`. **Never hand-edit a mirror** — the generator overwrites it from `.claude/`, so the edit is discarded, not merged. The 3-way parity is enforced by `tests/test_package_resource_parity.py` (+ `TestClaudeMirrorGenerator`). This is the `.claude` analog of `scripts/sync_vendor_cc.py` (`tools/cc/` → `espalier/_vendor/cc/`). **⚠ Not everything under `assets/` runs this direction:** `assets/github/workflows/harness-guard.yml` is itself a **source of truth** whose mirror is the repo's root `.github/workflows/` copy (`scripts/sync_github_workflow_asset.py`). Read the direction off `espalier/mirror_registry.py` before assuming.

## Before writing or editing in this folder:

1. Read [`memory/asset-mirroring.md`](../../memory/asset-mirroring.md) — the SoT + generator discipline.
2. For `.claude/{agents,commands,skills}`: do **NOT** edit here — edit the live `.claude/` SoT, then run `python scripts/sync_claude_mirrors.py`.
3. Run `pytest tests/test_package_resource_parity.py` to confirm parity.

**Read first:** [`memory/asset-mirroring.md`](../../memory/asset-mirroring.md)
