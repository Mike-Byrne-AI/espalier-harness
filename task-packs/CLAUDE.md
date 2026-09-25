# task-packs/

**Doing:** TP-NN blueprint drafts paired with RUNBOOKs. Each pack scopes a unit of work; `/implement-pack` executes it end-to-end.
**Don't break:** Filename `TP-<n>-<slug>.md`. The required-section list is NOT restated here — it changes, and a copy in this file would go stale silently while reading as authoritative; the [`blueprint-authoring` skill](../.claude/skills/blueprint-authoring/SKILL.md) is its sole home. Two shapes that are easy to skip and cost the most: **Task 0 (verify)**, whose licensed outcomes include *do not build this*, and **Reach**, required whenever a pack claims to close a class. Every pack ends with a `## Landing` stanza whose `State:` is one of `DRAFT | ROADMAP | LANDED | SCRAPPED` — the SoT for whether a pack landed. (Its full field list is not copied here either, for the reason above; `scripts/check_pack_landing.py` keys on `State:` alone, so the stanza tolerates fields the checker never reads — which is what lets the format add one without touching 205 archived packs.) — the `## Landing` stanza itself is the portable record; `scripts/check_pack_landing.py` (self-host tooling, not deployed by `init`) is the mechanical checker that reports any `Done/` pack missing `State: LANDED`. Fan-out findings JSON: namespace pack-item ids as `TP-<n>:LABEL` so they don't collide across packs (`espalier.fan_out_findings` schema). The [`blueprint-authoring` skill](../.claude/skills/blueprint-authoring/SKILL.md) is the source of truth for the format.

## Before writing or editing in this folder:

1. Read the [`blueprint-authoring` skill](../.claude/skills/blueprint-authoring/SKILL.md) — the source of truth for pack format + authoring conventions.
2. Compare the draft's section structure to a recent reference pack (latest in `task-packs/`).
3. **Authoring only:** iterate `/scope-check` while drafting to tighten `Scope (in)`.
   `/implement-pack` re-runs scope-check automatically at execution (its step 0-B), so do NOT
   repeat it on a finished pack. SoT: [`scope-check.md`](../.claude/commands/scope-check.md)
   "When to use".

**Read first:** [`blueprint-authoring` skill](../.claude/skills/blueprint-authoring/SKILL.md)
