"""Fusion inclusion manifest — the source of truth for what `espalier fuse`
overlays from the espalier checkout into a new fusion repo.

The fusion repo = a copy of the user's HOST project + this harness overlay, both
originals untouched. Default is GENEROUS bring; only the clearly
build-espalier-only surfaces are excluded.

Two principles keep this safe + small:
  1. `fuse` copies git-TRACKED files only — so heavy gitignored artifacts
     (bench/results/, reports/, cc/blueprints/, .espalier/, dist/, __pycache__)
     never travel. The reusable *system* is tracked; espalier's *artifacts* are not.
  2. SYSTEM vs CONTENT — bring the mechanism, reseed espalier-specific content
     empty (ESPALIER_MEMORY.md, blueprints, conventions). See RESEED_* below.

This is v1: a deliberately generous, mechanically-safe overlay. The deep
repurposing (emptying espalier-pinned scanner registries, re-pointing ci_guard,
stripping espalier paths from the verifier tests, re-seeding agent bodies) is the
FIRST Claude-session task in the fused repo, not a mechanical copy — see
`FINISH_UP_STEPS`.
"""
from __future__ import annotations

# Single source of truth for the committed project-memory filename — routed
# through one constant so a future rename is a value flip, not scattered edits.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

# ── Top-level dirs/files copied WHOLE from the espalier checkout ────────────
# Paths are repo-root-relative. A trailing "/" means "the whole tracked tree".
# espalier/ and tools/ are pulled whole: partial inclusion breaks the import
# closure (tools/cc) / package (espalier), and whole-pull is cleaner than
# surgical exclusion. MOST build-only modules they carry are inert in a
# fusion (a host never runs `espalier self-host`), but a few would over-flag —
# e.g. retired_vocab fires on an adopter's own roadmap vocab in the
# label shapes `**BLOCKER**` / `**MAJOR**` (uppercase bold) and `- MAJOR:` /
# `BLOCKER:` (bullet/section colon, any case); only the LOWERCASE bold/cell
# prose shapes (`**blocker**`, `| major |`) are suppressed. Whole-package pull
# means it can't be excluded piecemeal. The mechanical foreclosure is the
# self-host gate in cmd_scan: the five espalier-pinned scanners
# (subprocess/filesystem/magic_depth/retired_vocab/encoding_contracts) emit empty reports on a
# non-self-host repo, so `espalier scan` never over-flags an adopter. The
# FINISH_UP step-2 registry-empty below is now a fusion-specific belt (it keeps
# the SHIPPED registries honest for a fused operator's own future edits), not
# the primary adopter foreclosure.
HARNESS_INCLUDE: tuple[str, ...] = (
    "tools/",                       # the whole hook + script tree (zero-espalier-import, runs standalone)
    "espalier/",                    # the whole engine package (CLI + library)
    ".claude/agents/",              # governance agents (carry "adapt to your repo" sections)
    ".claude/commands/",            # slash commands
    ".claude/skills/",              # on-demand skills
    ".claude/workflows/",           # every espalier review/audit one-shot is EXCLUDEd below;
                                    # the fan-out ENGINE ships via espalier/fan_out_findings.py
    "bench/run_benchmark.py",       # the regression-coverage runner
    "bench/corpus/",                # slip-class corpus (verifies the overlaid hooks)
    "bench/baselines/",             # delta-over-baseline credibility
    "bench/end_to_end/",            # receiver-side behavioral verifier (hardest to rebuild)
    "bench/README.md",
    "scripts/check_exception_policy.py",
    "scripts/exception_policy_allowlist.json",
    "scripts/check_memory_md_tag_parity.py",
    # NOTE: pyproject.toml / .gitattributes are deliberately NOT overlaid — the
    # host owns those (a Python host has its own pyproject). The engine needs
    # `tomli` only on Python <3.11 (_compat.py falls back to stdlib tomllib on
    # 3.11+); the handoff notes the one `pip install tomli` line for <3.11 hosts.
    # Reusable engineering-knowledge docs (cross-project, low espalier coupling):
    "docs/FAILURE_MODES.md",        # the crown jewel — named bug-class catalog + disciplines
    "docs/MEMORY_SYSTEMS.md",       # memory-systems model + sorting rule; producer for memory/README.md's cross-ref
    "docs/external/",               # cc-hook-protocol.md (Claude-Code-specific, not espalier)
    "docs/TROUBLESHOOTING.md",
    "docs/HOOKS.md",
    "docs/WORKFLOW.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
    # NOTE: docs/HOOK_ASSUMPTIONS.md is deliberately NOT overlaid: it is espalier's
    # INTERNAL hook-design rationale ("for future maintainers and external
    # reviewers" of espalier itself) and links espalier's own tests +
    # POSITIONING.md, none of which a fusion ships. An adopter has docs/HOOKS.md
    # (usage); the rationale is maintainer noise. Dropping it removes 5 dangling
    # links rather than shipping espalier-internal targets to resolve them.
    # NOTE: docs/QUICKSTART.md is deliberately NOT overlaid — it is the sole
    # user-facing doc carrying espalier's `pip install -e .` product narrative.
    # Enforcement is its ABSENCE from this INCLUDE tuple (`_should_overlay`
    # returns False at the INCLUDE check, before RESEED_SKIP is consulted). The
    # RESEED_SKIP entry below is belt-and-suspenders: it documents the reseed intent
    # and would catch QUICKSTART if a future blanket `docs/` INCLUDE were added.
    "docs/FRESHNESS.md",
    "docs/PACK_AUTHORING.md",
    "docs/ENV_CATALOG.md",
    "docs/sharp-edges/README.md",   # the sharp-edges folder router (structure spec)
    # 3 sharp-edges bodies whose LESSON is cross-project; the rest are
    # espalier-mechanism-specific (protected-zone-*, malformed-json, …) and stay
    # self-scoped. Like FAILURE_MODES.md (also shipped), these carry illustrative
    # espalier examples — a version/agent reference is provenance, not product
    # narrative; the finish-up doc pass generalizes the examples to the host.
    "docs/sharp-edges/convergence-is-an-angle-set-property.md",
    "docs/sharp-edges/closed-loop-verification-trap.md",
    "docs/sharp-edges/hook-exit-codes-channel-xor.md",
    "memory/README.md",             # the categorized-memory convention (empty dir otherwise)
    "task-packs/CLAUDE.md",         # the task-pack folder router (format spec)
)

# ── EXCLUDE: tracked paths under an INCLUDE that are build-espalier-only ─────
# Matched as path-prefix OR exact against the repo-relative tracked path.
HARNESS_EXCLUDE: tuple[str, ...] = (
    # EXCLUDE EVERY .claude/workflows one-shot: each carries espalier refs and
    # would surface as an invokable skill in the fusion. The fan-out ENGINE
    # (espalier/fan_out_findings.py + FINDING_SCHEMA) ships; the operator authors
    # host-specific workflows from it.
    #
    # FAIL-CLOSED: this is a single whole-directory prefix, not a per-file
    # denylist. A per-file model is fail-OPEN — a new one-shot leaks into the
    # overlay unless someone remembers to add its prefix. The whole-dir prefix
    # covers every current AND future workflow by construction; shipping a
    # specific one requires a deliberate _INCLUDE_EXACT entry + reorder, not a
    # silent default. Pinned by tests/test_fuse.py::test_no_workflow_oneshots_overlay.
    ".claude/workflows/",
    # bench marketing/demo (espalier-the-product screencast).
    "bench/demo/",
    # espalier release machinery (host doesn't publish espalier).
    "scripts/release_check.py", "scripts/wheel_smoke.py",
    "scripts/build_release_archive.py", "scripts/final_release_matrix.py",
    "scripts/audit_dead_rules.py",
)

# ── RESEED FRESH: espalier-specific CONTENT that must NOT be copied ──────────
# These are NOT copied from espalier; `espalier init` (run after the overlay)
# generates host-appropriate versions, or they start empty. This is the
# SYSTEM-vs-CONTENT line that stops espalier's history shipping into the host.
RESEED_SKIP: tuple[str, ...] = (
    _MEMORY_FILENAME,               # init writes a fresh skeleton from the host fingerprint
    "CLAUDE.md",                    # init writes a fresh host-context version
    "docs/CONVENTIONS.md",          # MUST start near-empty (CLAUDE.md rule #2: describes THIS repo)
    "docs/SHARP_EDGES.md",          # seed host-scoped (the folder router + FAILURE_MODES carry the rest)
    "docs/README.md",               # espalier's docs index
    # espalier-specific memory CONTENT (the *system* ships via memory/README.md):
    "memory/",                      # everything under memory/ EXCEPT README.md (re-added by INCLUDE)
    # espalier's own task packs + review evidence (system ships via task-packs/CLAUDE.md):
    "task-packs/",                  # everything EXCEPT CLAUDE.md (re-added by INCLUDE)
    # espalier-maintainer folder ladders: "before editing espalier's engine /
    # scripts / scanners / hooks / assets, read this dev-note" — guidance for
    # editing the ENGINE internals, citing espalier-specific machinery (import
    # direction, _vendor byte-mirror, marker taxonomy) and memory CONTENT
    # (RESEED_SKIP'd above) that a fused adopter neither has nor edits. Dropping
    # them removes their dangling maintainer-internal links. The dirs themselves
    # still ship (the engine); only the maintainer CLAUDE.md ladder is skipped.
    # espalier/CLAUDE.md + tools/cc/CLAUDE.md sit under the blanket espalier/+tools/
    # INCLUDEs, so they need an explicit skip here (a non-included path would not).
    "espalier/assets/CLAUDE.md",
    "espalier/scanners/CLAUDE.md",
    "tools/cc/hooks/CLAUDE.md",
    "espalier/CLAUDE.md",           # engine root guide (blanket espalier/ include)
    "tools/cc/CLAUDE.md",           # scripts root guide (blanket tools/ include)
    # rendered surface indexes (init re-renders host identity):
    "cc/",                          # LIVE_SURFACE/COMMANDS/etc. + blueprints — init/fingerprint regenerate
    # operator doc carrying espalier's pip-install product narrative — reseeded
    # host-generic by the FINISH_UP doc-rewrite step:
    "docs/QUICKSTART.md",
    # espalier marketing / release-process docs:
    "docs/POSITIONING.md", "docs/DEMO.md", "docs/RELEASE_CHECKLIST.md",
    "docs/RELEASE_DECISIONS.md", "docs/REDEFINED_INFORMATION_REGISTRY.md",
    "docs/INSTALL-CI.md", "docs/SECURITY_TAXONOMY.md", "docs/ADAPTER_BOUNDARY.md",
)

# ── DECISION RECORD — v1 judgment calls (NOT read by fuse.py) ───────────────
# These five module constants have ZERO readers (verified) — fuse.py does not
# branch on any of them. They are NOT live toggles; flipping one changes
# nothing. They are kept as a written record of the v1 manifest decisions so the
# reasoning travels with the manifest. The ACTUAL behavior lives in the
# INCLUDE/EXCLUDE/RESEED_SKIP tuples + FINISH_UP_STEPS above and below.
#
# (a) CP-RELEASE speed-bump (fires on `git tag vN` -> PyPI publish): v1 ships
#     _speedbump WHOLE — espalier/ is pulled whole, and CP-RELEASE is inert unless
#     the host tags vN-shaped releases. No stripping in v1; revisit only if a host
#     finds it noisy. (The constant's name+`False` read as "exclude CP-RELEASE",
#     which is the opposite of what v1 does — hence "not read by the script".)
INCLUDE_CP_RELEASE = False
# (b) subprocess/filesystem_contracts scanners: shipped present (inside espalier/,
#     pulled whole), registries emptied in FINISH_UP — harmless when empty.
SHIP_CONTRACT_SCANNERS_INERT = True
# (c) SHARP_EDGES seed depth: near-empty (folder router only); FAILURE_MODES +
#     the 3 portable sharp-edges bodies carry the portable content. The producer
#     is `fuse._seed_sharp_edges`, which seeds a near-empty docs/SHARP_EDGES.md so
#     the overlaid harness docs' relative `SHARP_EDGES.md` links resolve.
SHARP_EDGES_SEED = "near-empty"
# (d) task-packs/: bring the format/router (task-packs/CLAUDE.md); the host's packs
#     stay gitignored (init's default). espalier's own tree tracks its ledger and
#     active packs since 2026-09-21, but RESEED_SKIP keeps them out of the overlay.
#     Host can flip to tracked later.
TASK_PACKS_TRACKED = False
# (e) Tests: v1 brings NO tests. The ~140 verifier subset is real but not a clean
#     mechanical copy — surface/manifest/content-pinned tests reference espalier's
#     own counts/paths and go RED until repurposed (regenerate
#     tests/_surface_expected.py, strip espalier paths). That is finish-up session
#     work (FINISH_UP step 1).
BRING_TESTS_V1 = False

# ── Finish-up steps (the taste the script can't mechanize) ──────────────────
# fuse already ran init + install-ci + fingerprint. These are the remaining steps
# that need host taste / a Claude session.
FINISH_UP_STEPS: tuple[str, ...] = (
    "Bring + repurpose the ~140 verifier tests against the FUSED surface; "
    "regenerate tests/_surface_expected.py; strip espalier paths/counts.",
    "Empty espalier-pinned scanner registries (magic_depth, subprocess_contracts, "
    "filesystem_contracts, retired_vocab) and widen their scope to the host's "
    "source roots. NOTE: `espalier scan` already self-host-gates these four "
    "(they emit empty reports on a non-self-host repo), so this step is a belt "
    "for a fused operator's OWN future scanner edits, not the adopter foreclosure.",
    "Re-point the installed CI workflow (.github/workflows/harness-guard.yml, "
    "written by `fuse`) + ci_guard.py at the fused protected-zone set. NOTE: "
    "both are write_guard-protected paths -- do this in a "
    "maintenance-mode session (see CLAUDE.md, \"Maintenance mode\", for the "
    "spelling your shell needs).",
    "Re-seed agent/skill bodies (code-reviewer, failure-mode-reviewer, "
    "docs-maintainer) from the host's own invariants; flag espalier examples.",
    "Rewrite the overlaid operator docs (TROUBLESHOOTING, TASK_RECIPES, WORKFLOW, "
    "CHEAT-SHEET, HOOKS) host-generic -- they ship carrying espalier-product "
    "(`pip install`/`pip uninstall espalier-harness`) narrative. NOTE: QUICKSTART "
    "is NOT overlaid (de-shipped); init seeds a host one, so there is nothing to "
    "rewrite there.",
    "Populate docs/CONVENTIONS.md from the host codebase via /analyze + "
    "repo-analyst (it intentionally starts near-empty).",
    "Repurpose bench/ for the host (corpus + baselines targeting the host's "
    "protected zones), THEN run bench/run_benchmark.py with --update-canonical "
    "to write the fusion's RESULTS.md -- it fail-closes on espalier's raw corpus, "
    "so `fuse` deliberately does not run it.",
)
