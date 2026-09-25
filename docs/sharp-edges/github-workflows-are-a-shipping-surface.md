# `.github/workflows/` is a shipping surface for the provenance census

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "`.github/workflows/` Is a Provenance Shipping Surface"

**What it is:** `.github/workflows/*.yml` counts as a **public shipping surface**.
`tests/test_no_provenance_in_shipped_code.py::test_no_build_history_on_shipping_surfaces`
scans it and fails on any internal build-history tag appearing in a workflow
comment. This is easy to miss because a workflow comment *feels* like private dev
scaffolding — it is not. Workflows ship verbatim to adopters via `install-ci` and
`fuse`, so an internal task tag there leaks provenance exactly as it would in
shipped source.

**Scope is wider than `.github/`:** the census covers **every public-classified
tracked file**, engine source included. One session leaked internal tags into
three engine modules' code comments, producing seven census offenders — and
leaked it *twice in one session*. The full suite caught both, but treat the
census as the safety net, not the plan.

**A second gate, differently scoped: the seeded-doc mirrors.** A dated
annotation appended to a catalog such as `docs/FAILURE_MODES.md` is copied
verbatim into `espalier/assets/docs/`, and
`tests/test_init_tier_split.py::test_common_tier_assets_have_no_internal_pack_ids`
sweeps the common-tier assets for the same id shapes the census matches, so one
annotation reds two gates over two different populations. A comment-only lane
that changes no behaviour at all is enough to trip both. Write the **date** the
fact was verified beside the behavioral text: it is what a future reader can
act on, and it carries no tag.

**`CHANGELOG.md` is now in scope too.** It was removed from the census allowlist
once its public dated history was collapsed and de-provenanced for the OSS launch
(6150 → 160 lines, 494 → 0 tags), so the dev-log residue cannot silently
re-accrue. A build-history tag in the CHANGELOG now reds the gate.

**Regex nuance:** a pattern written with a backslash-escaped digit class (rather
than a literal digit following the tag prefix) does **not** match
`PROVENANCE_RE`. That is why a denylist *pattern* string is fine while a literal
tag in a comment is not.

**How to avoid it:** Write workflow and source comments **behaviorally** — say
what the step does and why ("PRs run the fast slice for a quick feedback loop"),
never the internal task label. The convention is visible in the engine's own
modules, which cite zero pack IDs in comments: the internal reference lives only
in the task pack and in the census allowlist.

**When the suite reds on this, strip the tag and keep the behavioral text — do
not add a census allowlist entry.**
