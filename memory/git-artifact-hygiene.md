# Git artifact hygiene

**Status:** active
**Linked from:** [`memory/task-packs.md`](task-packs.md) (cross-ref under "Pre-flight discipline")

Discipline for repo-internal artifacts vs. tracked source: don't reach
for git as the default move/stage verb.

## Rule

Before invoking `git mv`, `git add`, or `git rm` on a path, verify it is
tracked in the git index. For repo-internal artifacts use plain shell
ops (`mv`, `rm`) directly.

## Gitignored artifact surfaces in this repo

| Path pattern | Purpose | Tracked? |
|---|---|---|
| `task-packs/Done/`, `Merged/`, `Scrapped/` and the dated archive files | Landed / folded / abandoned packs and pre-rebuild records | ❌ — gitignored, on the record branch. **Since 2026-09-21 the active packs at the root and under `Deferred/`, the ledger and its probes file are TRACKED** (they ship); the ignore rules are an allow-list |
| `cc/blueprints/*.json` | Session blueprint chain | ❌ — local-only |
| `cc/execution_plan.json` | Active execution plan | ❌ — singleton, per-session |
| `cc/SURFACE_HANDOFF.md` | Inter-session handoff doc | ❌ — gitignored sibling of LIVE_SURFACE |
| `reports/*` | Fingerprint + harness_config outputs | ❌ — operator-side |
| `.espalier/integrity.json` | Integrity manifest | ❌ — regenerated locally |
| `.espalier/freshness.json` | Freshness state cache | ❌ — operator-side |
| `.espalier/audit/*` | Audit log entries | ❌ — operator-side |

## Why

Reaching for `git mv` on any of these exits **128 with "not under version
control"** — wastes a tool call. (Since 2026-09-21 the reverse trap exists for a
pack: `git mv task-packs/TP-N-*.md task-packs/Done/` SUCCEEDS, because the source is
tracked, and force-tracks the landed pack inside the gitignored `Done/` -- the
tracked-noise gate reds on it. Land a pack with `git rm --cached -- "task-packs/TP-N-*.md"`
first, then `mv`.) The fact that they're gitignored is
observable in context (`.gitignore` + `ESPALIER_MEMORY.md` patterns), so the
failure is never a knowledge gap — it's a reflex of treating git as the
default move/stage verb when it should be reserved for tracked source.

The `TP-*.md` pattern is particularly load-bearing: `tests/conftest.py`
`initialized_repo_root` fixture uses `shutil.copytree + git add -A`, so
*any* untracked file not in `.gitignore` becomes tracked in the test's
isolated repo. `_TRACKED_NOISE_PATTERNS` (incl. `TP-*.md`) then fires
on them. If the gitignore lines were commented out, 4 tests fail —
the gitignore IS a contract, not a convenience.

## How to apply

1. **Default to `mv`/`rm`** for any of the artifact paths in the table
   above. No git tooling needed.
2. **Check before reaching for git** — if unsure whether a path is
   tracked, scan the project's `.gitignore` first, or run
   `git ls-files <path>` (empty output = untracked).
3. **`git mv` is only correct when source AND destination both live in
   tracked-or-trackable paths.** For artifact hygiene (moving completed
   pack files to `Done/`, archiving blueprints, etc.), it's never the
   right tool -- and for a tracked active pack it is actively wrong (it
   force-tracks the file into the ignored folder): `git rm --cached` the
   pack, then `mv`.
4. **Broader habit:** before any git operation, ask "is this path
   tracked?" The answer should come from context (gitignore, prior
   reads, MEMORY notes) — not from probing with the operation itself
   and watching for exit 128.

## Origin

Recorded after a session where `git mv task-packs/TP-98-*.md
task-packs/Done/` failed with exit 128, despite ESPALIER_MEMORY.md row 56 being
loaded in the orient context. The reflex (default to git for any
move/stage op) survived having the relevant fact in working memory —
which means the rule needs to be retrievable at *operation-decision*
time, not just at *context-load* time.
