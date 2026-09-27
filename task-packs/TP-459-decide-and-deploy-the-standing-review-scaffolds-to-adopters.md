# TP-459 — Decide whether the three standing review scaffolds deploy to adopters through `init`, and land the branch the operator picks

## Status

- Version target: after `0.8.0b2` (nothing here gates the beta; the deploy branch changes the
  wheel's package-data, so it lands on a version boundary and never mid-beta)
- Change type: feature (deploy inventory) on the deploy branch; docs (a recorded no) on the
  other. Task 0 decides which.
- **Kind: PACK**
- Ledger rows: none filed. The unit is the follow-on `TP-457` 0-C left open on 2026-09-26:
  "whether 'ship' also means deploying the three to adopters through `init` ... deploying them
  is its own pack with a deploy-inventory, mirror and parity footprint, to be raised at the
  next session's open."
- Authored 2026-09-27 on the public tree at `781159ca` (PR #19 open, the `DEF-938` row), the
  session after `TP-458` landed. Every "measured" sentence below was driven at authoring on this
  tree; each names its command so execution re-runs it rather than trusting the snapshot.
  Records at execution: `reports/task0-2026-09-27/` (gitignored, record-rooted).

---

## Motivation

`TP-457` 0-C returned the three standing fan-out review scaffolds to `.claude/workflows/` on the
public repository. The operator's framing that day: the workflows were never meant to be
withheld from the repository; good tools ship unless they are only useful to us. The same
decision left one question open, and this pack is that question.

Today three shipped surfaces answer it "no", and each records a reason:

- `espalier/fusion_manifest.py::HARNESS_EXCLUDE` excludes the whole directory from the fusion
  overlay: "each carries espalier refs and would surface as an invokable skill in the fusion.
  The fan-out ENGINE (`espalier/fan_out_findings.py` + `FINDING_SCHEMA`) ships; the operator
  authors host-specific workflows from it." Pinned by
  `tests/test_fuse.py::TestFuseManifestOverlay::test_no_workflow_oneshots_overlay` (exhaustive over
  the tracked scaffolds, floored at three).
- `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` classifies the directory `local_only`
  for the bespoke release zip, and `.gitattributes` carries `.claude/workflows/ export-ignore`
  for `git archive`: "review tooling the harness runs on itself, not deployed by `init`
  (deploying them is its own decision)". Pinned by
  `tests/test_git_archive_parity.py::test_claude_workflows_excluded_from_release_surfaces`.
- `init` deploys only what `espalier/cli.py::_packaged_md_assets` enumerates: the `.md` bodies
  under `espalier/assets/claude/{agents,commands,skills}/`. There is no
  `espalier/assets/claude/workflows/` (`ls espalier/assets/claude/`), and
  `scripts/sync_claude_mirrors.py::SUBDIRS` names the same three kinds.

So the prior answer stands on a premise, "each carries espalier refs", and the premise is
measurable. This pack measures it (Task 0), drives the one thing that can be driven without
the Workflow tool (the persist hop on a real adopter tree), and lets the operator decide with
the measurement in hand. It does not presume the answer: the fusion comment's own claim, "the
operator authors host-specific workflows from it", describes an adopter no adopter has been
asked to be, and the engine ships while the only worked examples of using it do not.

The platform side is settled enough to build on (Claude Code docs, `code.claude.com/docs/en/workflows`,
read 2026-09-27 through the `claude-code-guide` agent): project workflows load automatically
from `.claude/workflows/*.js` and run as `/<name>` slash commands; dynamic workflows are on
for all paid plans (Pro through a `/config` row); every run shows an approval prompt naming its
phases; a project workflow beats a personal one of the same name; `args` arrives as structured
data on current builds (the scaffolds also accept the string shape one host forwarded on
2026-07-17, so both are handled). The docs are silent on a leading underscore in the filename;
the three carry one today and load (this session's skill roster lists all three by their
`meta.name`).

---

## Scope (in)

- **0-A** the coupling census: the deriving command over the three scaffolds, each hit
  classified RUNTIME / PROMPT / COMMENT by the line it sits on.
- **0-B** the adopter-tree drive: the persist hop of each scaffold, extracted from its
  `persistCmd`, run on a tree built by `tests/_adopter_tree.py::build_adopter_tree`; the
  convergence critic's ledger read the same way.
- **0-C** the operator's decision on the fork the measurements leave open.
- **Deploy branch** (if picked): **1-A** the kinds roster gains `workflows` at its one owner
  and every hand-spelled copy of the triple is repointed or re-derived; **1-B** a managed
  marker for a `.js` body; **1-C** the three classification sites flip and their two pins are
  re-derived to the new truth; **1-D** the self-host prompts and the ledger-path default made
  adopter-neutral; **1-E** the count constant, the obligation row, the package-data glob and
  the adopter-facing sentence; **1-F** the two mirrors and their parity.
- **No branch** (if picked): **2-A** one sentence at each of the three surfaces saying the
  decision was taken with the measurement, plus one adopter-facing sentence saying where to
  copy the scaffolds from, and `TP-457`'s follow-on closed in its Landing.
- **3-A** the red-team, on either branch.
- **Files this pack may write** (named here so `/scope-check` can walk them; the deploy branch's
  set, of which the no branch touches only the three comment sites and the two record sites):
  `espalier/surface_contract.py`, `espalier/fusion_manifest.py`, `espalier/cli.py`,
  `espalier/surface_impact.py`, `scripts/sync_claude_mirrors.py`,
  `tools/cc/hooks/post_write_check.py`, `tools/cc/hooks/_reinject.py`, `.gitattributes`,
  `pyproject.toml`, `tests/_surface_expected.py`, `tests/test_git_archive_parity.py`,
  `tests/test_fuse.py`, `tests/test_package_resource_parity.py`, `tests/test_asset_shipping.py`,
  `tests/test_init_tier_split.py`, `tests/test_surface_contract.py`, `tests/test_write_guard.py`,
  `tests/test_managed_paths.py`, `tests/test_surface_impact.py`, `tests/test_denial_reasons.py`,
  `tests/test_reinject_sync.py`, `tests/test_wheel_payload.py`,
  `.claude/workflows/_layered_review.js`, `.claude/workflows/_fanout_audit.js`,
  `.claude/workflows/_convergence_review_template.js`, `.claude/commands/implement-pack.md`,
  `espalier/assets/CLAUDE.md`, `README.md`, `CLAUDE.md`, `memory/convergence-review-protocol.md`,
  `task-packs/Done/TP-457-adopt-the-release-docs-and-sweep-the-withheld-set.md`,
  `espalier/_vendor/cc/hooks/post_write_check.py` (by the vendor sync, never by hand),
  `.claude/CLAUDE.md` (its fan-out sentence names the three kinds), and, read but not
  written unless 1-C moves them: `espalier/fuse.py` (the overlay predicate reads
  `HARNESS_EXCLUDE`), `espalier/render_surface.py` (its dest-read guard mirrors
  `_deploy_asset_md`, so a `.js` marker sibling owes it a parity note), `docs/CONVENTIONS.md`
  (names `_deploy_asset_md` as the managed deploy path).

## Scope (out)

- The seven dated round scripts: records of one run each, not tools (`TP-457` 0-C, operator).
  They stay in the archive under every branch.
- The fan-out engine's behaviour (`espalier/fan_out_findings.py`, `espalier/finding_ledger.py`):
  unchanged. A defect 0-B finds there is a row with its own probe, not a fix here.
- `DEF-938` (the tag-coupled calibration tests): unrelated, its own fix.
- The `harness-guard` mirror row (`espalier/mirror_registry.py`, the one `sot-is-packaged`
  row): a different mirror family in the opposite direction; the workflows, if deployed, join
  the `claude-asset` and `claude-dogfooding` rows (`sot-is-source-tree`).
- `EXPECTED_COMMAND_COUNT` in `tests/_surface_expected.py`: it counts `.claude/commands/*.md`;
  a workflow is a `/<name>` command on the platform but not a command body, so the deploy
  branch adds a sibling constant rather than bumping this one.
- The record surfaces the pre-flight lists as referencing these symbols (`cc/blueprints/`,
  `docs/session-archive.md`, the compact summaries, `bench/demo/STORYBOARD.md`,
  `bench/corpus/BC-026-marker-substring-forgery.json`, the two catalogs, the `memory/` entries
  and the archived packs that cite these symbols): history, never edited; accept them with
  that reason at execution's scope-check.
- A generic "adopter-neutral review" rewrite of the three scaffolds' lenses beyond what 1-D
  names: the layered review's specialist lanes are seated on agents `init` deploys
  (`failure-mode-reviewer`, `architecture-analyst`, `code-reviewer`), and their prompts are
  the deliverable of a later pack if adopters ask; 1-D changes only the sentences that
  describe this tree as if it were the adopter's.

---

## Task 0 — Verify (may end this pack)

Task 0 has three outcomes and the pack states each: **verbatim deploy** (refuted at
authoring, below), **parametrized deploy** (the deploy branch), **recorded no** (the no
branch). Two of the three end the implementation before it starts; only one builds the
inventory.

### 0-A The coupling census (deriving command; the roster is its output)

```bash
command grep -n -oE "(memory/[A-Za-z_./-]+|tests/[A-Za-z_./-]+|reports/[A-Za-z_./-]+|task-packs/[A-Za-z_./-]+|espalier[A-Za-z_./-]*|tools/cc/[A-Za-z_./-]+|cc/[A-Za-z_./-]+|agentType: *['\"][a-z-]+['\"])" .claude/workflows/*.js | sort -u
```

Classify every hit by the line it sits on, not by the token: **RUNTIME** when the script
writes the path or the persist hop imports or reads it (`CORPUS_PATH`, `INPUT_PATH` and
`LEDGER_PATH` defaults; `from espalier.…`; `read_ledger`); **PROMPT** when the token is text an
agent is told (a review scope, a dedup instruction, a cwd claim); **COMMENT** when it is
rationale. The classification is the finding; a bare token count is not.

**Measured at authoring, 2026-09-27** (re-run at execution; the tree moves):

| Scaffold | RUNTIME | PROMPT | COMMENT |
|---|---|---|---|
| `_fanout_audit.js` | `espalier.fan_out_findings`, `espalier.finding_ledger` (engine modules, importable wherever the wheel is installed); `reports/audit-findings.md`, `reports/.fanout_audit_input.json` | the built-in landing-audit finder says "cwd = the Espalier-Harness repo root" and drives `python3 -m espalier verify-landing` over `task-packs/**/TP-*.md` (the no-args default) | `task-packs/FORWARD_LEDGER.md` (the persist comment), `tests/test_contracts.py`, `espalier/fan_out_findings.py` |
| `_layered_review.js` | the same two engine modules; `reports/layered-review-findings.md`, `reports/.layered_review_input.json` | the AR lane's scope is this tree's architecture ("espalier/ imports espalier/ only; tools/cc/ has zero espalier imports; scanners stdlib-only"); the FM lane's scope names `tools/cc/hooks/` (which `init` deploys, so this one holds on an adopter tree); the dedup instruction names `task-packs/FORWARD_LEDGER.md` with an explicit ABSENT-LEDGER fallback ("if that file is absent, as on a clean clone") | `espalier/audit_accuracy.py`, `task-packs/FORWARD_LEDGER.md` (the persist comment), `tests/test_contracts.py` |
| `_convergence_review_template.js` | the same two engine modules; `reports/convergence-review-findings.md`, `reports/.convergence_review_input.json`; **`LEDGER_PATH` defaults to `memory/CONVERGENCE_LEDGER.md`**, which the critic reads with Read and appends to with Edit | the critic's STEP 2 runs `read_ledger()` (engine; the JSONL is `cc/finding_ledger.jsonl` per `espalier/finding_ledger.py::ledger_path`) | `tests/test_catalog_self_consistency.py` (the anchor-ratchet warning in the critic prompt is PROMPT, and it is correct on any tree that has the test, harmless where it does not) |

Two facts decide the verbatim question:

- `ls espalier/assets/memory/` prints `README.md` only, so `init` seeds no
  `memory/CONVERGENCE_LEDGER.md`; the template's critic would read an absent file on its first
  adopter run. A RUNTIME coupling `init` does not create.
- The AR lane and the built-in landing finder describe this tree ("espalier/ imports
  espalier/ only", "cwd = the Espalier-Harness repo root"). A PROMPT coupling that is false on
  an adopter tree, and one an agent would act on.

**Refuting result for a verbatim deploy:** either fact. **Both hold at authoring, so the
verbatim branch is closed here**; execution re-runs the census to confirm nothing moved and
records the table under `reports/task0-2026-09-27/`. **Exit if the census comes back empty at
execution** (someone parametrized the three before this pack ran): the deploy branch loses
1-D and nothing else; the decision in 0-C is unchanged.

### 0-B The adopter-tree drive (the one thing drivable without the Workflow tool)

The JS runs only inside Claude Code's sandbox. What a script can drive is exactly the Python
each scaffold shells out to at its persist phase, the two-hop bridge, and the critic's STEP 2
read. Both are the parts that touch the adopter's disk.

Oracle (a scratch script, not a repo file; write it to the scratchpad as `tp459_0b.py` and run it
by path from the harness checkout; driven at authoring, twice, on fresh trees):

```python
"""Drive each scaffold's persist hop on a real adopter tree. cwd = the harness checkout."""
import json, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from tests._adopter_tree import build_adopter_tree

HERE = Path.cwd()
tree = build_adopter_tree(Path(tempfile.mkdtemp(prefix="tp459-")))
def listing(root: Path) -> set[str]:
    """Every file under root, .git excluded: init gitignores reports/, so git status is blind there."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}

before = listing(tree)
payload = {
    "findings": [
        {"id": "TP-459:one", "title": "t", "rule_or_scanner": "r", "violated_invariant": "v",
         "category": "c", "location": "src/demo/app.py::main", "claim": "survives",
         "minimal_repro": "m", "verification": {}, "confidence": "low", "proposed_fix": "p",
         "severity": "nit", "blocks_release": False, "refutation_outcome": "survived"},
        {"id": "TP-459:two", "title": "t", "rule_or_scanner": "r", "violated_invariant": "v",
         "category": "c", "location": "src/demo/app.py::main", "claim": "refuted",
         "minimal_repro": "m", "verification": {}, "confidence": "low", "proposed_fix": "p",
         "severity": "nit", "blocks_release": False, "refutation_outcome": "refuted"},
    ],
    "known_categories": None,
}
results = {}
scaffolds = sorted((HERE / ".claude" / "workflows").glob("*.js"))
assert len(scaffolds) == 3, scaffolds
for js in scaffolds:
    src = js.read_text(encoding="utf-8")
    m = re.search(r"const INPUT_PATH = '([^']+)'", src)
    c = re.search(r"const CORPUS_PATH = [^\n]*?'([^']+)'", src)
    body = re.search(r"const persistCmd =\n((?:  `[^\n]*\n)+)", src)
    assert m and c and body, (js.name, bool(m), bool(c), bool(body))
    lines = re.findall(r"`(.*?)\\n`", body.group(1))          # each JS line literal
    code = "\n".join(lines)
    assert code.startswith("python3 -c '"), code[:40]
    code = code.split("python3 -c '", 1)[1].rsplit("'", 1)[0]   # inside the quotes
    payload["corpus_path"] = c.group(1)
    (tree / m.group(1)).parent.mkdir(parents=True, exist_ok=True)
    (tree / m.group(1)).write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run([sys.executable, "-c", code.replace("${INPUT_PATH}", m.group(1))],
                          cwd=tree, capture_output=True, text=True)
    results[js.name] = {"rc": proc.returncode, "tail": (proc.stdout + proc.stderr)[-400:]}
after = listing(tree)
ledger = subprocess.run([sys.executable, "-c",
                         "from espalier.finding_ledger import read_ledger; print(len(read_ledger()))"],
                        cwd=tree, capture_output=True, text=True)
print(json.dumps({
    "tree": str(tree),
    "results": results,
    "wrote": sorted(after - before),
    "ledger_rows": (ledger.stdout + ledger.stderr).strip(),
    "convergence_ledger_exists": (tree / "memory" / "CONVERGENCE_LEDGER.md").exists(),
}, indent=1))
```

Read from its output: `rc` per scaffold, and `wrote` (every path the three hops created).
The template's critic STEP 2, `python3 -c 'from espalier.finding_ledger import read_ledger;
print(len(read_ledger()))'` in the tree, must print the number of hops that ran.

**Refuting result:** a non-zero `rc` on any scaffold, or a `wrote` entry outside `reports/`
and `cc/finding_ledger.jsonl`. Either means the persist hop cannot run on an adopter tree even
after 1-D, and **the deploy branch is dead; 0-C offers only the no branch.** **Measured at authoring, 2026-09-27, two runs
on fresh trees:** all three exit 0; each appended one survivor bullet to its `reports/`
corpus and one row to `cc/finding_ledger.jsonl` (the critic's read printed 3); the writes were
the three corpora, the three input JSONs, the JSONL, and three zero-byte `.write.lock` files
left beside the corpora, nothing else; `memory/CONVERGENCE_LEDGER.md` absent. So the deploy
branch is alive on the runtime side, and the template's critic step is the one runtime
coupling 1-D must resolve. Instrument lesson from the first run: a `git status` witness listed
one of the ten writes, because `init` gitignores `reports/`; the script lists the tree instead.
Observation, not a finding of this pack: the lock files outlive the write (`fan_out_findings`'s
atomic writer); if a maintainer is hurt by the litter it is a row with its own probe.

### 0-C The decision (operator)

With 0-A's table and 0-B's result on the table, the fork:

- **(a) Deploy all three, parametrized (the deploy branch, 1-A to 1-F).** An adopter gets
  `/fanout-audit`, `/layered-review` and `/convergence-review-template` on `init`, each with
  the sentences that describe this tree rewritten to read the adopter's, and a seeded
  `memory/CONVERGENCE_LEDGER.md` skeleton (or a create-if-absent critic) so the template's
  first run has a file to append to.
- **(b) Deploy `_fanout_audit.js` only.** It is the generic one (finders and targets through
  `args`); the other two carry a self-host lens in their prompts. Same footprint as (a),
  one file; the other two stay repository-only with the sentence 2-A writes.
- **(c) No, recorded (the no branch, 2-A).** The three stay on the repository as worked
  examples, `init` deploys the engine only, and the three surfaces that say so gain one
  sentence each naming this pack and the measurement, so the next session does not reopen
  the question from the same comment.

**Authoring read, a hypothesis for the operator to overrule:** (c) unless an adopter has
asked. The scaffolds spend dozens of agents a run on a paid-plan feature behind an approval
prompt; their value is the review method, which ships already as the engine, the schema and
the memory protocol; and the deploy footprint (the roster, a second marker syntax, three
classification flips with two pins re-derived, a package-data glob, a count constant, two
mirrors) is carried by every later release for a surface with no measured demand. The
counter-argument the operator made on 2026-09-26 is real too: withholding a working tool from
the repository is what 0-C undid, and (c) withholds it from `init`, not from the repository.
If the answer is (a) or (b), the footprint is the price and 1-A pays most of it once.

**Exit:** the branch the operator picks, recorded in the Landing stanza with the 0-A table
and the 0-B output cited by record path.

---

## Relevant memory

Recent pattern, measured across the last two packs: both reviews of `TP-457` and `TP-458`
found their majors in the repair and in the probes, not in the original defect; a probe keyed
on one fix arm slept under the other, a count over a growing population cried wolf, and a
reviewer's reasoned cost claim was refuted by driving it. Expect the red-team here to bite on
1-C (a pin re-derived into a tautology) and on 1-D (a prompt rewritten to say less than the
scaffold does), not on the copy step.

| Entry | Where |
|---|---|
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |
| Shipping an internal doc verbatim subjects it to every adopter-facing content contract | `docs/sharp-edges/shipping-docs-verbatim-collides-with-content-contracts.md` |
| Fan-out finding schema | `memory/fan-out-finding-schema.md` |
| Completeness gate must discover its population | `memory/completeness-gate-must-discover-its-population.md` |
| A hand-maintained doc enumeration with no code-pinned parity test rots silently | `docs/SHARP_EDGES.md`, the entry of that title |

Resolved at authoring by `python3 tools/cc/hooks/_recall.py "deploying a new asset kind to
adopters through init with mirrors and parity"`, then `"... verbatim collides with content
contracts"` and `"derive the list instead of a hand-written roster of kinds"`; re-run them
rather than trusting this list if the pack has been sitting.

---

## Implementation

Every fix below is a shape, untested at authoring unless it says driven. The oracle beside
each is exact.

### 1-A The kinds roster (deploy branch; the class, not the site)

The roster of deployed `.claude` kinds has one owner already:
`espalier/surface_contract.py::CLAUDE_KIND_GLOBS`, whose keys are
`CLAUDE_SURFACE_KINDS`; `espalier/cli.py`, `espalier/managed_inventory.py` and
`espalier/managed_paths.py` iterate it. Adding `"workflows"` there with its glob (`*.js`) is
the fix at the owner. The class is every site that hand-spells the triple instead of reading
the owner. Deriving command:

```bash
command grep -rnE "\"agents\", *\"commands\", *\"skills\"|'agents', *'commands', *'skills'|\{agents,commands,skills\}" --include="*.py" --include="*.md" --include="*.toml" . | command grep -v "_vendor/\|/Done/\|/Deferred/\|PRE_REBUILD\|session-archive\|cc/blueprints\|reports/\|TP-459"
```

At authoring the live members (records excluded) were:
`scripts/sync_claude_mirrors.py::SUBDIRS` (three spellings); `espalier/cli.py::_packaged_md_assets`
(its `layout` list is a second roster with per-kind iterators; it gains a fourth row or reads
the owner's globs); `tools/cc/hooks/post_write_check.py::_CLAUDE_BODY_KINDS` (a hook: zero
espalier imports, so it cannot read the owner and keeps its own tuple; `tests/test_write_guard.py`
already asserts that tuple equal to `CLAUDE_SURFACE_KINDS`, so the owner's fourth kind reds
that pin until the hook follows, an earned red for free); the parametrize lists and roster
asserts in `tests/test_package_resource_parity.py`, `tests/test_asset_shipping.py`,
`tests/test_init_tier_split.py`, `tests/test_fuse.py`, `tests/test_surface_contract.py`,
`tests/test_denial_reasons.py`, `tests/test_reinject_sync.py`; the advisory sentence in
`tools/cc/hooks/_reinject.py`; the prose in `.claude/commands/implement-pack.md` (and its two
mirrors by the sync), `espalier/assets/CLAUDE.md`, `espalier/surface_impact.py`'s regen note,
and the root `CLAUDE.md` mirror-sync sentence. **Reach is the grep's output at execution, per
member, in the Reach table; the list above is the lower bound.**

Fix shape: the sites that can import `surface_contract` read `CLAUDE_SURFACE_KINDS`; the hook
keeps its tuple and the existing `tests/test_write_guard.py` assertion pins the two equal; the prose sites say "the deployed kinds (`CLAUDE_SURFACE_KINDS`)" and name the
four once. Refuted if a site's triple is deliberately narrower than the owner (the `doctor`
sister-site comment says so for its agents-plus-commands count; leave that one and say why in
the Reach table).

Oracle: the grep prints only the hook's tuple and the sister-site-ok comment sites; then
`python3 -c "from espalier import surface_contract as s; print(s.CLAUDE_SURFACE_KINDS)"`
prints four kinds.

### 1-B A managed marker for a `.js` body

`espalier/cli.py::_deploy_asset_md` injects the `espalier:managed` marker through
`apply_marker_to_md` and recognises it through `has_managed_marker`, so a user-edited copy is
preserved on re-init. A `.js` body needs the same contract in a comment the sandbox ignores.

Fix shape: a sibling `apply_marker_to_js` writing one line, `// espalier:managed`, as the
FIRST line, before `export const meta` (the docs require the meta to be the first
*statement*; a comment is not one), and `has_managed_marker` widened to that spelling.
**Refutation to drive first:** save a copy of one scaffold with the comment on line 1 under a
throwaway name in `.claude/workflows/`, start a session, and read the skill roster; if the
copy is absent, the loader wants the meta byte-first and the marker moves to the line after
the meta block's closing brace. Then delete the copy (it is not a scaffold; the
`STANDING_PERSISTERS` and `LIVE_V2` rosters would red on it if it stayed).

Oracle: `tests/test_init_tier_split.py`'s four-state deploy tests parametrized over the new
kind (created, updated_managed, skipped_no_drift, skipped_user_file) go green; the
skipped_user_file case is driven by removing the comment from a deployed copy and re-running
`init`.

### 1-C The classification flip (three sites, two pins re-derived)

Sites: `espalier/fusion_manifest.py::HARNESS_EXCLUDE` (remove the prefix, or move the three
to `_INCLUDE_EXACT` per the comment's own instruction "shipping a specific one requires a
deliberate `_INCLUDE_EXACT` entry + reorder"), `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES`
(remove the prefix), `.gitattributes` (remove the `export-ignore` line and its comment block).

The two pins do not get deleted; they get re-derived to the new truth, because each carries
a floor and an exhaustive-enumeration shape worth keeping:

- `tests/test_git_archive_parity.py::test_claude_workflows_excluded_from_release_surfaces`
  becomes its opposite: every tracked scaffold classifies `public` and appears in the archive.
  Same floor, same enumeration, inverted assertions, renamed to say what it now pins.
- `tests/test_fuse.py::TestFuseManifestOverlay::test_no_workflow_oneshots_overlay` becomes
  "every tracked standing scaffold overlays": same floor, `_should_overlay` true for each.

**Earn the red for each:** with the three sites flipped and the pins still in their old shape,
both must be red; flip the pins, green. A pin that is green in both shapes has no subject.

### 1-D The adopter-neutral prompts and the ledger-path default

From 0-A's PROMPT column, the sentences that describe this tree:

- `_layered_review.js`, the AR lane: replace the parenthetical architecture rule with a
  scope an adopter tree has ("the import direction and layer boundaries this repository's
  `CLAUDE.md` and `docs/CONVENTIONS.md` declare; where they declare none, report that as the
  finding"). The FM lane keeps `tools/cc/hooks/`; `init` deploys it.
- `_fanout_audit.js`, the built-in landing finder: "cwd = the repository root".
- `_convergence_review_template.js`: `LEDGER_PATH` keeps its default; the critic's STEP 1
  gains "if the file is absent, create it with the row-schema header below and treat the
  prior rows as none", or `init` seeds a skeleton `memory/CONVERGENCE_LEDGER.md` through
  `espalier/assets/memory/` (the second is the cleaner contract: a file that exists is a
  file the critic can read; the first puts a create in an Edit-only step). Pick at execution
  by driving the critic prompt once on the 0-B tree; record which.

Oracle: 0-A's census re-run prints no PROMPT hit that names `espalier/` as an architecture
rule or the harness as the cwd; `tests/test_contracts.py::TestFanoutSchemaParity` and the
`STANDING_PERSISTERS` test stay green (the schema block and the persist calls are untouched).

### 1-E The count, the obligation, the glob and the sentence

- `tests/_surface_expected.py::EXPECTED_WORKFLOW_COUNT = 3  # class: literal`, beside the
  command and skill counts, read by the same asset-shipping test that reads them.
- `espalier/surface_impact.py`'s obligation table gains a `.claude/workflows/` row (today a
  new top-level directory prints "no declared obligations"): the count constant, the mirror
  sync, the package-data glob, the README and `CLAUDE.md` table row.
- `pyproject.toml` `[tool.setuptools.package-data]`: `"assets/claude/workflows/*.js"` beside
  the three per-kind `.md` globs; `tests/test_wheel_payload.py` and `tests/test_asset_shipping.py`
  pin that the wheel carries it (build the wheel and list it: the artifact, not the source
  tree, is the oracle).
- One adopter-facing sentence in `README.md`'s surface table and the root `CLAUDE.md`
  "Skills" neighbourhood: the three workflows, invoked as `/<name>`, need dynamic workflows on
  (paid plans) and show an approval prompt per run.

### 1-F The mirrors and their parity

`scripts/sync_claude_mirrors.py::SUBDIRS` reads the owner (1-A), so one run populates
`espalier/assets/claude/workflows/` and `examples/dogfooding/.claude/workflows/`;
`tests/test_package_resource_parity.py` parametrizes over the owner and pins both. The
`mirror_registry.py` rows `claude-asset` and `claude-dogfooding` already name `.claude/` as
the SoT and need no new row; the PostToolUse advisory that names the sync fires on the new
subdirectory by prefix (`tools/cc/hooks/_reinject.py`, the generated-mirror sentence, gains
the fourth kind in its text).

Oracle: `python3 scripts/sync_claude_mirrors.py` then `git status --short` shows the six new
mirror files; `pytest -q tests/test_package_resource_parity.py` green; then the full tier
(this diff touches `tools/cc/` and `espalier/`, so `scripts/proof_tier.py` prints `full`).

### 2-A The recorded no (no branch)

One sentence at each of the three surfaces, in the existing comment or comment block, in
this shape: "Decided 2026-09-DD (`TP-459` 0-C, with the coupling census and the adopter-tree
drive on record): the scaffolds stay repository-only; `init` deploys the engine." Sites:
`espalier/fusion_manifest.py::HARNESS_EXCLUDE` (the comment above the prefix),
`espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` (the comment above the prefix),
`.gitattributes` (the comment block above the `export-ignore` line). One adopter-facing
sentence where the fan-out engine is documented (`memory/convergence-review-protocol.md`'s
"Generic scaffold" bullet, which already says the scaffold runs through the Workflow tool):
the three scaffolds are on the repository at `.claude/workflows/`, copy the one you want into
your own `.claude/workflows/`. `TP-457`'s Landing gains one line: the follow-on decided by
`TP-459`.

Oracle: `python3 -m espalier provenance .` clean (a pack id in a comment on a shipping
surface is exactly what it polices; if it reds, cite the decision by date and the record path
instead of by pack id); the contract tier green.

### 3-A Red-team

Two lanes on a snapshot clone built from `git diff HEAD --name-only`, both briefed with the
harness frame and FORBIDDEN to stash or check out on the live tree: `code-reviewer` over the
diff for correctness, `failure-mode-reviewer` for the ways the next session trips. Name what
this pack most likely got wrong, so the lanes have something to bite on:

- 1-C: a pin re-derived by inverting assertions can become a tautology (green for every
  classification). Ask for the mutation each re-derived pin dies to.
- 1-D: a prompt rewritten to be adopter-neutral can say less than the scaffold does; the AR
  lane's replacement must still produce a finding on a tree with declared layers.
- 1-B: the marker's position is a platform claim; ask whether the drive in 1-B was recorded.
- 0-B: the extraction regex reads the scaffold's source shape; a scaffold edit that
  re-indents `persistCmd` silently makes the oracle drive nothing. Ask whether the script
  asserts it found three payloads.

A clean red-team is the surprise; record its verdicts in Landing either way.

---

## Affected symbols

The deploy branch's set; the no branch changes comments only, which is declared under
Changed-semantics as the three comment sites so the walk sees them.

### Changed-semantics
- `espalier/surface_contract.py::CLAUDE_KIND_GLOBS` (gains `workflows`; deploy branch)
- `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` (loses `.claude/workflows/`, or its comment gains the decision)
- `espalier/fusion_manifest.py::HARNESS_EXCLUDE` (loses `.claude/workflows/`, or its comment gains the decision)
- `espalier/cli.py::_packaged_md_assets` (a fourth kind, or reads the owner's globs; deploy branch)
- `espalier/cli.py::_deploy_asset_md` (a `.js` marker sibling; deploy branch)
- `espalier/surface_impact.py` (the obligation table gains a row; deploy branch)
- `scripts/sync_claude_mirrors.py::SUBDIRS` (reads the owner; deploy branch)
- `tools/cc/hooks/post_write_check.py::_CLAUDE_BODY_KINDS` (gains `workflows`, pinned equal to the owner; deploy branch)
- `tests/test_git_archive_parity.py::test_claude_workflows_excluded_from_release_surfaces` (re-derived to its opposite; deploy branch)
- `tests/test_fuse.py::TestFuseManifestOverlay::test_no_workflow_oneshots_overlay` (re-derived to its opposite; deploy branch)
- `.claude/workflows/_layered_review.js` (the AR lane's scope sentence, 1-D; deploy branch)
- `.claude/workflows/_fanout_audit.js` (the built-in finder's cwd sentence, 1-D; deploy branch)
- `.claude/workflows/_convergence_review_template.js` (the critic's STEP 1 on an absent ledger, 1-D; deploy branch)

### Renamed
- (none -- the two re-derived pins may be renamed to say what they now pin; a rename there is a test name, not a production symbol)

### Added-paths
- `espalier/assets/claude/workflows/` (deploy branch; three files by the sync)
- `examples/dogfooding/.claude/workflows/` (deploy branch; three files by the sync)
- `tests/_surface_expected.py::EXPECTED_WORKFLOW_COUNT` (deploy branch)
- `espalier/assets/memory/CONVERGENCE_LEDGER.md` (deploy branch, only if 1-D picks the seeded skeleton)

### Removed-paths
- (none -- the `.gitattributes` `export-ignore` line is a line, not a path; the no branch removes nothing)

---

## Reach

The deploy branch claims the class "every site that enumerates the deployed `.claude` kinds
without reading the owner". Members derived by the 1-A grep at execution (its output is the
roster; the list in 1-A is the lower bound seen at authoring). Fill per member:

| Member | Status | Evidence |
|---|---|---|
| `scripts/sync_claude_mirrors.py::SUBDIRS` | (at execution) | reads `CLAUDE_SURFACE_KINDS`, or a parity test pins it equal |
| `tools/cc/hooks/post_write_check.py::_CLAUDE_BODY_KINDS` | (at execution) | cannot import the owner; `tests/test_write_guard.py` pins it equal, red first by the owner's change |
| `espalier/cli.py::_packaged_md_assets` | (at execution) | the `layout` list carries the fourth kind or derives from the owner |
| the test parametrize lists (five files at authoring) | (at execution) | each reads the owner or is named here with the reason it stays literal |
| `espalier/doctor.py` (agents-plus-commands count) | NOT REACHED, by design | its own `sister-site: ok purpose-scoped` comment: the saved plan carries no skills source |
| the two prose sites | (at execution) | name the four kinds once and the owner |

Stop condition: if the grep at execution prints members outside these shapes (a fifth
roster with its own semantics), re-raise before 1-A rather than widening the pack to fit.

On the no branch the pack claims no class and this section records "not claimed".

---

## Pass criteria

Either branch:

- Task 0's three records exist under `reports/task0-2026-09-27/`: the 0-A table, the 0-B
  script output, and the operator's 0-C decision with date. A pack whose Landing cites a
  decision with no record is not landed.
- `python3 -m espalier provenance .` exits 0; `python3 scripts/proof_tier.py --run` PASS at
  the tier it prints for the diff (the deploy branch earns `full`; the no branch `contract`).
- No assertion in `tests/test_git_archive_parity.py`, `tests/test_fuse.py`,
  `tests/test_finding_ledger.py`, `tests/test_contracts.py` or
  `tests/test_convergence_workflow_stages.py` may be weakened; a floor may rise, a re-derived
  pin must have died to the mutation 1-C names before it went green, and no roster in those
  files may shrink.

Deploy branch:

- `python3 -c "from espalier import surface_contract as s; print(s.CLAUDE_SURFACE_KINDS)"`
  prints four kinds, and the 1-A grep prints only the sites the Reach table names as
  deliberately literal.
- A wheel built from the tree (`python3 -m build --wheel`, then list it) carries the three
  `.js` under `espalier/assets/claude/workflows/`; `espalier init` on a tree built by
  `tests/_adopter_tree.py::build_adopter_tree` writes the three under `.claude/workflows/`
  with the marker, and a second `init` reports `skipped_no_drift` for each; a copy with the
  marker removed reports `skipped_user_file`.
- 0-A's census re-run after 1-D prints no PROMPT hit that describes this tree as the
  adopter's.
- `python3 scripts/sync_claude_mirrors.py` is a no-op after the pack (both mirrors already
  converged), and `tests/test_package_resource_parity.py` is green.

No branch:

- The three comment sites and the protocol memo's bullet each carry the decision sentence,
  `TP-457`'s Landing names this pack, and nothing under `espalier/assets/` changed.

---

## Files touched

Deploy branch:

- **Modified:** `espalier/surface_contract.py`, `espalier/fusion_manifest.py`,
  `espalier/cli.py`, `espalier/surface_impact.py`, `scripts/sync_claude_mirrors.py`,
  `tools/cc/hooks/post_write_check.py` (then `python3 scripts/sync_vendor_cc.py`),
  `tools/cc/hooks/_reinject.py` (the advisory sentence; same sync), `.gitattributes`,
  `pyproject.toml`, `tests/_surface_expected.py`, `tests/test_git_archive_parity.py`,
  `tests/test_fuse.py`, `tests/test_package_resource_parity.py`, `tests/test_asset_shipping.py`,
  `tests/test_init_tier_split.py`, `tests/test_surface_contract.py`,
  the three scaffolds under `.claude/workflows/`,
  `.claude/commands/implement-pack.md` (then `python3 scripts/sync_claude_mirrors.py`),
  `espalier/assets/CLAUDE.md`, `README.md`, `CLAUDE.md`.
- **Read at 1-A and 1-C, edited only if their assertion message spells three kinds or names
  the workflows prefix:** `tests/test_write_guard.py` (the hook-tuple pin, red until the hook
  follows the owner), `tests/test_managed_paths.py` (re-derives the deployed set from
  `_packaged_md_assets`), `tests/test_surface_impact.py` (pins the obligation table's file
  list), `tests/test_paths_parity.py` and `tests/test_release_archive_class_regression.py`
  (assert other prefixes stay in `_LOCAL_ONLY_PREFIXES`; at authoring neither names
  `.claude/workflows/`), `tests/test_denial_reasons.py`, `tests/test_reinject_sync.py`.
- **New:** `espalier/assets/claude/workflows/*.js` and `examples/dogfooding/.claude/workflows/*.js`
  (by the sync, never by hand); `espalier/assets/memory/CONVERGENCE_LEDGER.md` if 1-D picks
  the skeleton.
- **Deleted:** none.
- **Unmodified on purpose:** `espalier/fan_out_findings.py`, `espalier/finding_ledger.py`,
  `espalier/mirror_registry.py` (no new row: the existing two rows cover the new
  subdirectory by prefix), `espalier/doctor.py`.

No branch:

- **Modified:** `espalier/fusion_manifest.py`, `espalier/surface_contract.py`,
  `.gitattributes` (comments only), `memory/convergence-review-protocol.md` (one sentence),
  `task-packs/Done/TP-457-adopt-the-release-docs-and-sweep-the-withheld-set.md` (one Landing line).
- **New / Deleted:** none.

---

## Sub-task ordering

0. **0-A** the census (five minutes; the table into the record) → **0-B** the drive (the
   script by path; its JSON into the record) → **0-C** the operator's decision (recorded).
   Checkpoint: the three record files exist. Either of the refuting results ends here.
1. Deploy branch: **1-A** the roster at the owner and the class sweep → checkpoint: the grep
   and the four-kinds print. **1-B** the marker, with its platform drive first → checkpoint:
   the four-state tests. **1-C** the flip, pins red then green → checkpoint: the two tests'
   earned reds recorded. **1-D** the prompts and the ledger default → checkpoint: the census
   re-run. **1-E** the count, the obligation, the glob, the sentence → checkpoint: the wheel
   listing. **1-F** the syncs and parity → checkpoint: `sync_claude_mirrors.py` a no-op, then
   the full tier.
   No branch: **2-A** the sentences → checkpoint: provenance clean, contract tier green.
2. **3-A** red-team on a snapshot clone; fold every accepted finding as one batch; re-prove
   at the tier the final diff earns.
3. Branch, commit, PR with auto-merge (Core Rule 10); the deploy branch's diff touches
   `tools/cc/hooks/`, so the PR title carries the approval marker bound to the head SHA.

---

## Estimated effort

| Sub-task | Budget |
|---|---|
| 0-A census and classification | 0.5 h |
| 0-B adopter-tree drive (script, run, read) | 1 h |
| 0-C decision (operator) | 0.25 h |
| 1-A roster and class sweep | 2 h |
| 1-B marker and its platform drive | 1.5 h |
| 1-C flip and two re-derived pins with earned reds | 1.5 h |
| 1-D prompts and ledger default | 1.5 h |
| 1-E count, obligation, glob, sentence | 1 h |
| 1-F syncs, parity, full tier | 1.5 h (the tier runs unattended) |
| 2-A the recorded no | 0.5 h |
| 3-A red-team and the fold | 2 h |
| **Deploy branch total** | **about 13 h** over two sessions |
| **No branch total** | **about 4 h** in one session |

---

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: (deploy branch) the two re-derived pins red under the flipped sites in their old shape, green in the new; the four-state marker tests red with the marker sibling absent
- Red-team:
- Reach: (deploy branch) per member from the 1-A grep at execution; (no branch) not claimed
- Date:
