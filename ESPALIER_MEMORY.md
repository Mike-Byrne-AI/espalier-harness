<!-- Espalier-Harness self-hosted memory. This is the project's OWN working
memory (kept public as a dogfooding artifact — not adopter documentation);
adopters get the template shape from `examples/ESPALIER_MEMORY.template.md`. It is a
LIVING log — the Session-Log tail accretes between curation passes; the full
internal decision/session history lives off the public tree. Tracked, but
excluded from the package + archive. -->

# Espalier-Harness — Project Memory

## Repo Context

**Repo:** espalier-harness
**Stack:** Python CLI (`espalier`) + pytest + markdown docs
**Architecture:** `espalier/` engine → `tools/cc/` hooks → `.claude/` config → root docs
**Key constraint:** `tools/cc/` scripts have zero espalier imports (run standalone)
**Test suite:** `tests/test_fingerprint.py`, `tests/test_hooks.py`, `tests/test_scanners.py`, `tests/test_scanner_magic_depth.py`
**Continuity:** `cc/_working_summary.md` is the live, always-current session-resume doc (pull-only, rewritten at every compaction + `/handoff`); pull it or `/read-summary` for the full pick-up picture. Per-session archive: `cc/blueprints/compact_summaries/`.
**Citation form:** cite `path/to/file.py::symbol`, never a line anchor — `path.py:NN` rots on any edit above the cited line and is ratcheted DOWN by `tests/test_catalog_self_consistency.py`. A bare `::Class.member` names the syntax itself rather than any resolvable target. _(This line is the stable home for that placeholder: it was pinned inside a Session-Log row, and the tail auto-prunes, so the pin died the moment the row aged out — 2026-08-16d.)_

## Harness Decisions

The running architecture-decision log is kept off the public tree (it names
internal work items). Landed decisions are described plainly in `CHANGELOG.md`;
the rationale behind a specific change lives in that change's session blueprint
(`cc/blueprints/`) and, for reusable judgment, in `memory/`.

## Patterns Learned

This project's actual patterns live in `docs/CONVENTIONS.md`; its real footguns
in `docs/SHARP_EDGES.md`; reusable cross-session judgment in `memory/` (recalled
via `/recall`); the epistemic disciplines in `docs/STANDING_PRINCIPLES.md` (index
injected every SessionStart) — newest §15, *many attempts failing a **different**
way each time means the problem is mis-specified, not hard*.

## Session Log

**Pruning policy:** Bounded at 120 lines. The Session Log is one file per row under
`memory/session-log.d/`, read by `tools/cc/_record_fragments.py` (`rows` prints them
newest first, `new session-log` names the next file). The table that stood here was
folded into those files on 2026-10-11. The newest 30 files are kept, older ones
archive to `docs/session-archive.md`.

## Categorized memory

For long-form entries that don't fit in the index above, see [`memory/`](memory/) —
reusable project judgment (footguns, feedback, governing frames), recalled on demand via `/recall`.

Review/authoring discipline — [`memory/`](memory/):

| Row label | Entry |
|---|---|
| One writer per shared state (root `CLAUDE.md` Core Rule 14) | [one-writer-per-shared-state](memory/one-writer-per-shared-state.md) |
| A second oracle may be COMPLEMENTARY, not stronger | [a-second-oracle-may-be-complementary-not-stronger](memory/a-second-oracle-may-be-complementary-not-stronger.md) |
| An exemption outlives its own premise | [an-exemption-outlives-its-own-premise](memory/an-exemption-outlives-its-own-premise.md) |
| folder-CLAUDE.md ladder: pointer, not restatement | [ladder-claudemd-design](memory/ladder-claudemd-design.md) |
| Gates the targeted proofs never show | [four-gates-the-targeted-proofs-never-show](memory/four-gates-the-targeted-proofs-never-show.md) |
| A hand-written count that moves on ordinary growth is tax | [a-hand-written-count-that-moves-on-ordinary-growth-is-tax](memory/a-hand-written-count-that-moves-on-ordinary-growth-is-tax.md) |
| An enumeration switch reaches every consumer | [an-enumeration-switch-reaches-every-consumer](memory/an-enumeration-switch-reaches-every-consumer.md) |
| Grep for a sibling store before building a rival | [grep-for-a-sibling-store-before-building-a-rival](memory/grep-for-a-sibling-store-before-building-a-rival.md) |
| Verify a pack's scope-OUT rationale, not just prescriptions | [verify-a-packs-scope-out-rationale](memory/verify-a-packs-scope-out-rationale.md) |
| Removing a leak can break a contract that rode on it | [removing-a-leak-can-break-a-contract-that-rode-on-it](memory/removing-a-leak-can-break-a-contract-that-rode-on-it.md) |
| A dedup catalog's "collapse to canon" is a CLAIM | [dedup-collapse-suggestions-are-claims](memory/dedup-collapse-suggestions-are-claims.md) |
| Pizza-test review lens — hunt the singular out-of-place error | [pizza-test-review-lens](memory/pizza-test-review-lens.md) |
| Calibrate an enforcement contract against the live population | [calibrate-an-enforcement-contract-against-the-live-population](memory/calibrate-an-enforcement-contract-against-the-live-population.md) |
| Fix the pack and proceed on a 0-A defect | [fix-the-pack-and-proceed-on-a-pre-flight-defect](memory/fix-the-pack-and-proceed-on-a-pre-flight-defect.md) |
| "Make a pack" = author then STOP | [make-a-pack-means-author-then-stop](memory/make-a-pack-means-author-then-stop.md) |
| Reviews before the one full run | [reviews-before-the-one-full-run](memory/reviews-before-the-one-full-run.md) |
| Recall keys on the hazard, not the task | [recall-keys-on-the-hazard-not-the-task](memory/recall-keys-on-the-hazard-not-the-task.md) |
| Choose the artifact by where the risk lives — a pack cannot answer "does this mechanism work" | [choose-the-artifact-by-where-the-risk-lives](memory/choose-the-artifact-by-where-the-risk-lives.md) |
| A review workflow needs TWO classifications | [a-review-workflow-needs-two-classifications](memory/a-review-workflow-needs-two-classifications.md) |
| Craft surface isn't converged (unlike correctness) | [craft-surface-is-not-converged-unlike-correctness](memory/craft-surface-is-not-converged-unlike-correctness.md) |
| Commit messages must stand alone | [commit-messages-must-stand-alone](memory/commit-messages-must-stand-alone.md) |
| A pack's prescribed fix code is a claim — test it | [a-packs-prescribed-fix-code-is-a-claim](memory/a-packs-prescribed-fix-code-is-a-claim.md) |
| The handoff record goes stale if work continues past it | [the-handoff-record-goes-stale-if-work-continues](memory/the-handoff-record-goes-stale-if-work-continues.md) |
| A staged/prepared transform draft is a CLAIM — re-derive + verify-no-drops before applying | [staged-transform-draft-is-a-claim](memory/staged-transform-draft-is-a-claim.md) |

Footguns — [`docs/sharp-edges/`](docs/sharp-edges/):

| Row label | Entry |
|---|---|
| The source tree is not an oracle for the produced artifact | [source-tree-is-not-an-artifact-oracle](docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md) |
| Citation rot — repoint before you reword | [citation-rot-verify-fix-target-tree-wide](docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md) |
| skipif→marker migration drops filter-less consumers | [skipif-to-marker-drops-filterless-consumers](docs/sharp-edges/skipif-to-marker-drops-filterless-consumers.md) |
| Install-doc break green-masked by cwd-shadow | [install-path-green-masked-by-cwd-shadow](docs/sharp-edges/install-path-green-masked-by-cwd-shadow.md) |
| Shipping docs verbatim collides with content contracts | [shipping-docs-verbatim-collides-with-content-contracts](docs/sharp-edges/shipping-docs-verbatim-collides-with-content-contracts.md) |
| A stale egg-info makes a packaging gate verify the previous config | [include-package-data-ships-tracked-assets](docs/sharp-edges/include-package-data-ships-tracked-assets.md) |
| A hook-blocked Bash call skips its bundled git-add | [blocked-bash-call-skips-its-bundled-git-add](docs/sharp-edges/blocked-bash-call-skips-its-bundled-git-add.md) |
| Public source is provenance-scanned | [github-workflows-are-a-shipping-surface](docs/sharp-edges/github-workflows-are-a-shipping-surface.md) |
| A long-latent issue that "just now bites" is a CLASS | [a-latent-issue-that-just-bit-is-a-class](docs/sharp-edges/a-latent-issue-that-just-bit-is-a-class.md) |
