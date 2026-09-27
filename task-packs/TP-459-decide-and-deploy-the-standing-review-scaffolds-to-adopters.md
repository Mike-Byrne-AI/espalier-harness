# TP-459 — Decide whether the three standing review scaffolds deploy to adopters through `init`, and land the branch the operator picks

## Status

- Version target: after `0.8.0b2` (nothing here gates the beta; the deploy branch changes the
  wheel's package-data, so it lands on a version boundary and never mid-beta)
- Change type: feature (deploy inventory) on the deploy branch; docs (a recorded no) on the
  other. Task 0 decides which.
- **Kind: PACK**
- Ledger rows: `DEC-34` (§4A, the fork; filed by hand at authoring, 2026-09-27, three-cell rows
  being outside the verbs). The unit is the follow-on `TP-457` 0-C left open on 2026-09-26:
  "whether 'ship' also means deploying the three to adopters through `init` ... deploying them
  is its own pack with a deploy-inventory, mirror and parity footprint, to be raised at the
  next session's open." Two live rows sit on this pack's files and stay theirs: `DEF-892`
  (nothing executes the persist program the layered review assembles) and `DEF-324c` (the
  template's worktree rule with no consumer); see Scope (out).
- Cross-pack: `TP-449` (State: ROADMAP) names `espalier/surface_contract.py` for other
  symbols (`is_transient`, `tracked_paths`); no semantic overlap, a merge-collision surface
  only. Expect the conflict on that file if both are in flight.
- Authored 2026-09-27 on the public tree at `781159ca` (PR #19 open, the `DEF-938` row), the
  session after `TP-458` landed. Every "measured" sentence below was driven at authoring on this
  tree; each names its command so execution re-runs it rather than trusting the snapshot.
  Reviewed at authoring by two lanes on a snapshot clone (code-reviewer: REQUEST CHANGES, 2
  BLOCK 8 WARN 6 NIT; failure-mode-reviewer: REQUEST CHANGES, 4 BLOCK 1 WARN 1 NIT); every
  finding verified against the bytes and folded here in one batch: the provenance tags the
  deploy branch would ship, the two gates blind to a deployed `.js`, the kinds roster the
  one-line grep could not see, the marker recogniser's leader set and scan window, the seed
  roster, the classification sister sites, the mutation direction of the re-derived pins, and
  the ordering of Task 0's refutations. Records at execution: `reports/task0-2026-09-27/`
  (gitignored, record-rooted).

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
  the tracked scaffolds, floored at three). The same file's `HARNESS_INCLUDE` carries the
  directory too, with the comment "every espalier review scaffold is EXCLUDEd below".
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

The platform side, read once and re-read by Task 0's outcome (d) (Claude Code docs,
`code.claude.com/docs/en/workflows`, read 2026-09-27 through the `claude-code-guide` agent):
project workflows load automatically from `.claude/workflows/*.js` and run as `/<name>` slash
commands; dynamic workflows are on for all paid plans (Pro through a `/config` row); every run
shows an approval prompt naming its phases; a project workflow beats a personal one of the
same name; `args` arrives as structured data on current builds (the scaffolds also accept the
string shape one host forwarded on 2026-07-17, so both are handled). The docs are silent on a
leading underscore in the filename; the three carry one today and load (this session's skill
roster lists all three by their `meta.name`).

---

## Scope (in)

- **0-A** the coupling census: the deriving command over the three scaffolds, each hit
  classified RUNTIME / PROMPT / COMMENT by the line it sits on, the refuting rule stated first.
- **0-B** the adopter-tree drive: the persist hop of each scaffold, extracted from its
  `persistCmd`, run on a tree built by `tests/_adopter_tree.py::build_adopter_tree`; the
  convergence critic's ledger read the same way; an instrument gate before the loop.
- **0-C** the operator's decision on the fork the measurements leave open, with outcome (d),
  the re-raise when the platform premise has moved.
- **Deploy branch** (if picked): **1-A** the kinds roster gains `workflows` at its one owner
  and every roster that spells the triple without reading the owner is repointed, re-derived or
  named as deliberately literal; **1-B** a managed marker for a `.js` body at the recogniser,
  its hand-copy and its forgery corpus, the marker on line 1 only; **1-C** the three
  classification sites flip, their two pins are re-derived with the mutation named in the
  right direction, and every sister site of the classification is swept; **1-C-2** the
  public-surface content audit the flip makes due (provenance, codenames, machine-local paths)
  over the scaffold bodies and over their deployed copies; **1-D** the self-host prompts and
  the two ledger-path defaults made adopter-neutral, with a positive pin on the replacement;
  **1-E** the count constant, the obligation row, the package-data glob, the seed roster and
  the adopter-facing sentence; **1-F** the two mirrors and their parity.
- **No branch** (if picked): **2-A** one sentence at each of the three surfaces saying the
  decision was taken with the measurement, plus one adopter-facing sentence saying where to
  copy the scaffolds from, and `TP-457`'s follow-on closed by an appended Landing line.
- **3-A** the red-team, on either branch.
- **Files this pack may write** (named here so `/scope-check` can walk them; the deploy branch's
  set, of which the no branch touches only the three comment sites and the two record sites):
  `espalier/surface_contract.py`, `espalier/fusion_manifest.py`, `espalier/cli.py`,
  `espalier/surface_impact.py`, `espalier/managed_markers.py`, `espalier/managed_inventory.py`,
  `espalier/provenance_census.py`, `espalier/cleanup.py`, `espalier/asset_inventory.py`,
  `espalier/render_surface.py`, `scripts/sync_claude_mirrors.py`, `scripts/wheel_smoke.py`,
  `tools/cc/hooks/post_write_check.py`, `tools/cc/hooks/_reinject.py`,
  `tools/cc/sister_site_probe.py`, `.gitattributes`, `pyproject.toml`,
  `bench/corpus/BC-026-marker-substring-forgery.json`, `tests/_surface_expected.py`,
  `tests/test_git_archive_parity.py`, `tests/test_fuse.py`, `tests/test_package_resource_parity.py`,
  `tests/test_asset_shipping.py`, `tests/test_init_tier_split.py`, `tests/test_surface_contract.py`,
  `tests/test_write_guard.py`, `tests/test_managed_paths.py`, `tests/test_surface_impact.py`,
  `tests/test_denial_reasons.py`, `tests/test_reinject_sync.py`, `tests/test_wheel_payload.py`,
  `tests/test_managed_markers.py`, `tests/test_no_internal_codenames.py`,
  `tests/test_no_provenance_in_shipped_code.py`, `tests/test_pre_release.py`, `tests/conftest.py`,
  `scripts/final_release_matrix.py`,
  `.claude/workflows/_layered_review.js`, `.claude/workflows/_fanout_audit.js`,
  `.claude/workflows/_convergence_review_template.js`, `.claude/commands/implement-pack.md`,
  `espalier/assets/CLAUDE.md`, `README.md`, `CLAUDE.md`, `memory/convergence-review-protocol.md`,
  `task-packs/Done/TP-457-adopt-the-release-docs-and-sweep-the-withheld-set.md`,
  `espalier/_vendor/cc/hooks/post_write_check.py` and `espalier/_vendor/cc/sister_site_probe.py`
  (by the vendor sync, never by hand), `.claude/CLAUDE.md` (its fan-out sentence names the
  three kinds), and, read but not written unless a sub-task says so: `espalier/fuse.py` (the
  overlay predicate reads `HARNESS_EXCLUDE` before its include-exact set), `docs/CONVENTIONS.md`
  (names `_deploy_asset_md` as the managed deploy path), `espalier/audit_accuracy.py` and
  `bench/run_benchmark.py` (the AST census prints them; 1-A classifies them).

## Scope (out)

- The seven dated round scripts: records of one run each, not tools (the adopt-the-release-docs
  pack's 0-C, operator, 2026-09-26; landed in `Done/`). They stay in the archive under every
  branch.
- The fan-out engine's behaviour (`espalier/fan_out_findings.py`, `espalier/finding_ledger.py`):
  unchanged. A defect 0-B finds there is a row with its own probe, not a fix here.
- `DEF-892`: nothing executes the persist program the layered review assembles, and its stated
  fix shape is an extractor inside `tests/test_finding_ledger.py`. 0-B's scratch script is
  that extractor in all but its home; landing it as the test is that row's fix, a follow-on
  of about an hour, not a branch of this decision. `DEF-324c`: the template's
  `isolation: worktree` rule has no consumer; the deploy branch ships the rule as it stands and
  the row keeps its own oracle.
- `DEF-938` (the tag-coupled calibration tests): unrelated, its own fix.
- The `harness-guard` mirror row (`espalier/mirror_registry.py`, the one `sot-is-packaged`
  row): a different mirror family in the opposite direction; the workflows, if deployed, join
  the `claude-asset` and `claude-dogfooding` rows (`sot-is-source-tree`).
- `EXPECTED_COMMAND_COUNT` in `tests/_surface_expected.py`: it counts `.claude/commands/*.md`;
  a workflow is a `/<name>` command on the platform but not a command body, so the deploy
  branch adds a sibling constant rather than bumping this one.
- The fusion overlay's include-exact arm: `espalier/fuse.py` derives its include-exact set from
  `HARNESS_INCLUDE`'s file entries and its overlay predicate checks `HARNESS_EXCLUDE` before
  that set, so "move the three to an exact include" would need a reorder of every
  include-exclude interaction. Not taken; 1-C removes the exclude prefix instead.
- Widening `MARKER_SCAN_BYTES` (and its hand-copy `_MANAGED_MARKER_SCAN_CHARS`): a hardened
  constant; 1-B puts the marker on line 1 or re-raises, never widens the window.
- The record surfaces the pre-flight lists as referencing these symbols (`cc/blueprints/`,
  `docs/session-archive.md`, the compact summaries, `bench/demo/STORYBOARD.md`, the two
  catalogs, the `memory/` entries and the archived packs that cite these symbols): history,
  never edited; accept them with that reason at execution's scope-check. `bench/corpus/BC-026-marker-substring-forgery.json`
  is NOT in this set: it is a live guard corpus and 1-B edits it. The one archived pack 2-A
  touches, the adopt-the-release-docs pack (landed in `Done/`), takes an appended Landing line under the append-an-amendment
  convention (`Done/` is under the local-only `task-packs/` prefix, so a clone does not carry
  it; the edit is a record amendment on this checkout).
- A generic "adopter-neutral review" rewrite of the three scaffolds' lenses beyond what 1-D
  names: the layered review's specialist lanes are seated on agents `init` deploys
  (`failure-mode-reviewer`, `architecture-analyst`, `code-reviewer`), and their prompts are
  the deliverable of a later pack if adopters ask; 1-D changes only the sentences that
  describe this tree as if it were the adopter's and the paths `init` does not create.

---

## Task 0 — Verify (may end this pack)

Task 0 has four outcomes and the pack states each before its measurement: **verbatim deploy**
(refuted at authoring), **parametrized deploy** (the deploy branch), **recorded no** (the no
branch), and **(d) the premise moved, re-raise** (the platform read in Motivation is one
agent's doc-read on one day; the pack's Pre-work is a re-read of
`code.claude.com/docs/en/workflows` for two facts, that `.claude/workflows/*.js` still
autoloads and that dynamic workflows are still gated to paid plans; if either moved, stop and
re-raise with the new text rather than adjust). 0-B also carries an instrument gate whose
failure is neither outcome: it means the oracle could not run, not that the deploy is refuted.

### 0-A The coupling census (deriving command; the roster is its output)

**Refuting result for a verbatim deploy, stated before the table:** any RUNTIME hit that
`init` does not create on an adopter tree, or any PROMPT hit that names a path `init` does not
create or describes the harness's own tree as if it were the adopter's. Either closes the
verbatim branch; the live branches are then parametrize or no.

```bash
command grep -n -oE "(memory/[A-Za-z_./-]+|tests/[A-Za-z_./-]+|reports/[A-Za-z_./-]+|task-packs/[A-Za-z_./-]+|espalier[A-Za-z_./-]*|tools/cc/[A-Za-z_./-]+|cc/[A-Za-z_./-]+|agentType: *['\"][a-z-]+['\"])" .claude/workflows/*.js | sort -u
```

Classify every hit by the line it sits on, not by the token: **RUNTIME** when the script
writes the path or the persist hop imports or reads it (`CORPUS_PATH`, `INPUT_PATH` and
`LEDGER_PATH` defaults; `from espalier.…`; `read_ledger`); **PROMPT** when the token is text an
agent is told (a review scope, a dedup instruction, a cwd claim, a file to confirm); **COMMENT**
when it is rationale. The classification is the finding; a bare token count is not.

**Measured at authoring, 2026-09-27** (re-run at execution; the tree moves):

| Scaffold | RUNTIME | PROMPT | COMMENT |
|---|---|---|---|
| `_fanout_audit.js` | `espalier.fan_out_findings`, `espalier.finding_ledger` (engine modules, importable wherever the wheel is installed); `reports/audit-findings.md`, `reports/.fanout_audit_input.json` | the built-in landing-audit finder says "cwd = the Espalier-Harness repo root" and drives `python3 -m espalier verify-landing` over `task-packs/**/TP-*.md` (the no-args default) | `task-packs/FORWARD_LEDGER.md` (the persist comment), `tests/test_contracts.py`, `espalier/fan_out_findings.py` |
| `_layered_review.js` | the same two engine modules; `reports/layered-review-findings.md`, `reports/.layered_review_input.json` | the AR lane's scope is this tree's architecture ("espalier/ imports espalier/ only; tools/cc/ has zero espalier imports; scanners stdlib-only"); the FM lane's scope names `tools/cc/hooks/` (which `init` deploys, so this one holds on an adopter tree); the dedup instruction names `task-packs/FORWARD_LEDGER.md` with an explicit ABSENT-LEDGER fallback ("if that file is absent, as on a clean clone") | `espalier/audit_accuracy.py`, `task-packs/FORWARD_LEDGER.md` (the persist comment), `tests/test_contracts.py` |
| `_convergence_review_template.js` | the same two engine modules; `reports/convergence-review-findings.md`, `reports/.convergence_review_input.json`; **`LEDGER_PATH` defaults to `memory/CONVERGENCE_LEDGER.md`**, which the critic reads with Read and appends to with Edit | the critic's STEP 2 runs `read_ledger()` (engine; the JSONL is `cc/finding_ledger.jsonl` per `espalier/finding_ledger.py::ledger_path`); the critic's anchor-ratchet warning names `tests/test_catalog_self_consistency.py` (correct on any tree that has the test, harmless where it does not); **the SMOKE lane is told to confirm `memory/convergence-review-protocol.md` exists and names the four scope-breakers**, a file `init` does not seed; the finder, refuter and corpus-blind lanes name `task-packs/FORWARD_LEDGER.md` (grep it, cross-reference it, do NOT read it), the first with an absent-file clause | the persist comment's `task-packs/FORWARD_LEDGER.md`; the critic comment's `memory/convergence-review-protocol.md` |

Three facts decide the verbatim question, each of the shape the refuting rule names:

- `ls espalier/assets/memory/` prints `README.md` only, so `init` seeds neither
  `memory/CONVERGENCE_LEDGER.md` (the template's RUNTIME default) nor
  `memory/convergence-review-protocol.md` (the template's smoke-lane PROMPT).
- The AR lane and the built-in landing finder describe this tree ("espalier/ imports
  espalier/ only", "cwd = the Espalier-Harness repo root"): PROMPT couplings an agent would act
  on that are false on an adopter tree.

**So the verbatim branch is closed here.** Execution re-runs the census to confirm nothing moved
and records the table under `reports/task0-2026-09-27/`. **Exit if the census comes back empty
at execution** (someone parametrized the three before this pack ran): the deploy branch loses
1-D and nothing else; the decision in 0-C is unchanged.

### 0-B The adopter-tree drive (the one thing drivable without the Workflow tool)

The JS runs only inside Claude Code's sandbox. What a script can drive is exactly the Python
each scaffold shells out to at its persist phase, the two-hop bridge, and the critic's STEP 2
read. Both are the parts that touch the adopter's disk.

**Refuting result, stated before the script:** a non-zero `rc` on any scaffold, a `wrote`
entry outside `reports/` and `cc/finding_ledger.jsonl`, or a ledger row count that is not the
number of hops that ran. Any of the three means the persist hop cannot run on an adopter tree
even after 1-D, and **the deploy branch is dead; 0-C offers only the no branch.** **Instrument
failures are not refutations:** the script asserts, before the loop, that `espalier` imports
from the adopter tree (a fresh-clone venv or an interpreter leg without the wheel makes that
assert fail, and that is the instrument, not the subject); and it asserts, per scaffold, that
the extraction found the block, that every physical line but the closing one was captured, that
the payload names both persist functions, and that the payload carries no apostrophe (which
would break the `-c` quoting). An assert failure means "fix the script", never "the deploy is
refuted".

Oracle (a scratch script, not a repo file; write it to the scratchpad as `tp459_0b.py` and run it
by path from the harness checkout; driven at authoring three times on fresh trees, the last with
every assert in place):

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
# INSTRUMENT gate: a persist hop that cannot import the engine is not a refutation of the deploy.
assert subprocess.run([sys.executable, "-c", "import espalier"], cwd=tree).returncode == 0, \
    "INSTRUMENT: espalier not importable from the adopter tree; this is not a refutation"
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
    # Every physical line of the block but the closing one carries a `\n` literal; a
    # second silent drop would be indistinguishable from a correct parse without this.
    physical = body.group(1).rstrip("\n").count("\n") + 1
    assert len(lines) == physical - 1, (js.name, len(lines), physical)
    code = "\n".join(lines)
    assert "append_findings_to_corpus" in code and "append_summary" in code, js.name
    assert "'" not in code.split("python3 -c '", 1)[1].rsplit("'", 1)[0], (js.name, "an apostrophe inside the payload breaks the -c quoting")
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
rows = int((ledger.stdout + ledger.stderr).strip() or 0)
assert rows == len(results), ("ledger rows", rows, "hops", len(results))
print(json.dumps({
    "tree": str(tree),
    "results": results,
    "wrote": sorted(after - before),
    "ledger_rows": (ledger.stdout + ledger.stderr).strip(),
    "convergence_ledger_exists": (tree / "memory" / "CONVERGENCE_LEDGER.md").exists(),
}, indent=1))
```

Read from its output: `rc` per scaffold, `wrote` (every path the three hops created) and
`ledger_rows` (the critic's STEP 2 read, asserted equal to the number of hops).

**Measured at authoring, 2026-09-27, three runs on fresh trees, the last with every assert:**
all three exit 0; each appended one survivor bullet to its `reports/` corpus and one row to
`cc/finding_ledger.jsonl` (the critic's read printed 3); the writes were the three corpora,
the three input JSONs, the JSONL, and three zero-byte `.write.lock` files left beside the
corpora, nothing else; `memory/CONVERGENCE_LEDGER.md` absent. So the deploy branch is alive
on the runtime side, and the template's ledger default is the one runtime coupling 1-D must
resolve. Instrument lesson from the first run: a `git status` witness listed one of the ten
writes, because `init` gitignores `reports/`; the script lists the tree instead. Observation,
not a finding of this pack: the lock files outlive the write (`fan_out_findings`'s atomic
writer); if a maintainer is hurt by the litter it is a row with its own probe. The extractor
is, in shape, the fix `DEF-892` asks for (Scope (out)).

### 0-C The decision (operator)

With 0-A's table and 0-B's result on the table, the fork:

- **(a) Deploy all three, parametrized (the deploy branch, 1-A to 1-F).** An adopter gets
  `/fanout-audit`, `/layered-review` and `/convergence-review-template` on `init`, each with
  the sentences that describe this tree rewritten to read the adopter's, the smoke lane's
  protocol-memo check made conditional, and a seeded `memory/CONVERGENCE_LEDGER.md` skeleton
  (or a create-if-absent critic) so the template's first run has a file to append to. The
  price is the footprint 1-A to 1-F name, carried by every later release.
- **(b) Deploy `_fanout_audit.js` only.** It is the generic one (finders and targets through
  `args`); the other two carry a self-host lens in their prompts. Same footprint as (a), one
  file; the other two stay repository-only with the sentence 2-A writes.
- **(c) No, recorded (the no branch, 2-A).** The three stay on the repository as worked
  examples, `init` deploys the engine only, and the three surfaces that say so gain one
  sentence each naming this decision and the measurement, so the next session does not reopen
  the question from the same comment.
- **(d) The premise moved.** The Pre-work re-read shows the platform no longer autoloads
  project workflows, or gates them differently: stop and re-raise with the new text.

**Authoring read, a hypothesis for the operator to overrule:** (c) unless an adopter has
asked. The scaffolds spend dozens of agents a run on a paid-plan feature behind an approval
prompt; their value is the review method, which ships already as the engine, the schema and
the memory protocol; and the deploy footprint (the roster at its owner and every literal copy,
a second marker syntax at a hardened recogniser and its hand-copy, three classification flips
with two pins re-derived and a dozen sister sites swept, a content audit over three bodies
that carry seven build-history tags today, a package-data glob, a count constant, a seed-roster
row, two mirrors) is carried by every later release for a surface with no measured demand. The
counter-argument the operator made on 2026-09-26 is real too: withholding a working tool from
the repository is what 0-C undid, and (c) withholds it from `init`, not from the repository.
If the answer is (a) or (b), the footprint is the price and 1-A pays most of it once.

**Exit:** the branch the operator picks, recorded in the Landing stanza with the 0-A table
and the 0-B output cited by record path.

---

## Relevant memory

Recent pattern, measured across the last two packs and this pack's own authoring review: the
majors were in the repair and in the oracles, not in the original defect. A probe keyed on one
fix arm slept under the other; a count over a growing population cried wolf; a reviewer's
reasoned cost claim was refuted by driving it; and here, a one-line grep offered as a class
roster could not see five rosters that spell the same triple across lines, and a pass criterion
asked for a gate the same pack's flip made impossible. Expect the red-team at execution to bite
on 1-C (a pin re-derived into a tautology) and on 1-D (a prompt rewritten to say less than the
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
`espalier/managed_paths.py` iterate it. Adding `"workflows": "*.js"` there is the fix at the
owner. The class is every roster that spells the triple without reading the owner.

**Deriving oracle (structural; the roster is its output).** A one-line grep for the
comma-separated triple was the first draft and is refuted: five production rosters spell the
three kinds on separate lines (`espalier/cli.py::_packaged_md_assets`'s `layout` list,
`espalier/cleanup.py::_prune_empty_dirs`'s candidate list, `espalier/asset_inventory.py`'s
`AssetGroup` rows, `espalier/render_surface.py`'s `surface.get(...)` reads,
`scripts/wheel_smoke.py`'s per-kind count) and the grep printed none of them. The census that
sees them is an AST walk for modules whose string constants include all three kind names:

```python
import ast, pathlib
for p in sorted(pathlib.Path('.').glob('**/*.py')):
    if any(s in p.parts for s in ('.venv', '_vendor', 'build', 'dist', 'node_modules', '.git')): continue
    try: t = ast.parse(p.read_text(encoding='utf-8'))
    except Exception: continue
    vals = {n.value for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    if {'agents', 'commands', 'skills'} <= vals: print(p.as_posix())
```

Driven at authoring (2026-09-27): twenty-nine modules, of which the production set is
`bench/run_benchmark.py`, `espalier/asset_inventory.py`, `espalier/audit_accuracy.py`,
`espalier/cleanup.py`, `espalier/cli.py`, `espalier/render_surface.py`,
`espalier/surface_contract.py` (the owner itself), `scripts/sync_claude_mirrors.py`,
`scripts/wheel_smoke.py` and `tools/cc/hooks/post_write_check.py`; the other nineteen are test
modules. Prose sites the census cannot see and the pack names: `.claude/commands/implement-pack.md`
(and its two mirrors by the sync), `espalier/assets/CLAUDE.md`, `espalier/surface_impact.py`'s
regen note, `espalier/assets.py`'s accessor docstring, the root `CLAUDE.md` mirror-sync
sentence and `.claude/CLAUDE.md`'s fan-out sentence. **Reach is the census's output at
execution, per member, in the Reach table; the list above is the lower bound.** The
one-line grep stays as a secondary check for prose.

Fix shape per member: a module that can import `surface_contract` reads
`CLAUDE_SURFACE_KINDS` or `CLAUDE_KIND_GLOBS[kind]`; `tools/cc/hooks/post_write_check.py::_CLAUDE_BODY_KINDS`
(a hook: zero espalier imports) keeps its own tuple, and the existing `tests/test_write_guard.py`
assertion that it equals `CLAUDE_SURFACE_KINDS` reds when the owner gains the fourth kind
until the hook follows: an earned red for free; the test parametrize lists read the owner
**except** `tests/test_package_resource_parity.py`'s assertion that `SUBDIRS` equals the
literal set, which exists so that dropping a kind from the sync is caught while the byte-parity
tests still pass; pointing both sides at the owner would make it read `X == X` and see
nothing, so that pin stays literal (four names) and is listed in Reach as deliberately literal.
`espalier/cleanup.py::_prune_empty_dirs` matters for adopters: without the fourth kind an
adopter's `clean-generated` would leave `.claude/workflows/` standing and so never prune
`.claude/` itself (the module's own docstring names the harm). `scripts/wheel_smoke.py` must
smoke the fourth kind or the wheel's `.js` is never checked. Refuted if a member's triple is
deliberately narrower than the owner: `espalier/doctor.py`'s agents-plus-commands count says so
in its `sister-site: ok purpose-scoped` comment; leave it and say why in the Reach table.

Oracle: the AST census prints only the owner, the hook's tuple and the sites the Reach table
names as deliberately literal; `python3 -c "from espalier import surface_contract as s; print(s.CLAUDE_SURFACE_KINDS)"`
prints four kinds; `tests/test_write_guard.py`'s kinds pin went red on the owner's change
before the hook followed (record the red).

### 1-B A managed marker for a `.js` body

`espalier/cli.py::_deploy_asset_md` injects the `espalier:managed` marker through
`apply_marker_to_md` and recognises it through `has_managed_marker`, so a user-edited copy is
preserved on re-init. A `.js` body needs the same contract in a comment the sandbox ignores,
and the recogniser is hardened: `espalier/managed_markers.py::_MARKER_LINE_RE` accepts a closed
leader set (`#`, `<!--`, `::`) at the start of a line, scans only the first
`MARKER_SCAN_BYTES` (600) of the file, is hand-copied into
`tools/cc/sister_site_probe.py::_MANAGED_MARKER_RE` with `_MANAGED_MARKER_SCAN_CHARS` (a
zero-espalier-import sister site), and is driven by
`bench/corpus/BC-026-marker-substring-forgery.json` through the benchmark's
`marker_recognition` verifier and by `tests/test_managed_markers.py::TestLineAnchoredRecognition`.

Fix shape: the leader set gains `//` at both the recogniser and its hand-copy (then
`python3 scripts/sync_vendor_cc.py`); a sibling `apply_marker_to_js` writes
`// espalier:managed` as the FIRST line, before `export const meta` (the docs require the meta
to be the first *statement*; a comment is not one); one new forgery attempt in BC-026 and one
new negative test (a `// espalier:managed` inside a JS string literal, and inside a Markdown
fence, must NOT count) so the widened recogniser is not a born-weak guard.

**Line 1 is the only acceptable position.** Measured 2026-09-27: the meta blocks' closing
braces sit at byte 501 (`_fanout_audit.js`), 795 (`_convergence_review_template.js`) and 1011
(`_layered_review.js`) against the 600-byte window, so a marker after the meta block would be
invisible for two of the three files: re-init would classify them `skipped_user_file` forever
and `cleanup.file_carries_marker` would never remove them, while the third behaved. If the
loader refuses a comment on line 1, the pack re-raises; it never widens the window (Scope
(out)).

**The loader question is an OPERATOR step with a pause, driven outside the harness tree.** A
session cannot read its own future skill roster, and a fourth file under this tree's
`.claude/workflows/` reds the `STANDING_PERSISTERS` glob (the `LIVE_V2` partition enumerates
tracked files only, so it would not see an untracked copy, but the finding-ledger roster
would). So: create a scratch project directory with its own `.claude/workflows/` holding one
copy of a scaffold with the line-1 comment, start a Claude Code session there, read the
roster, record the outcome in Landing as 1-B's precondition, and delete the scratch project.
Ordering places this drive before any 1-B edit; an unattended executor stops at it.

Oracle: `tests/test_init_tier_split.py`'s four-state deploy tests parametrized over the new
kind (created, updated_managed, skipped_no_drift, skipped_user_file) go green; the
skipped_user_file case is driven by removing the comment from a deployed copy and re-running
`init`; BC-026 with its new attempt passes the verifier; the negative test reds with the
recogniser widened to a bare `espalier:managed` anywhere (earn the red).

### 1-C The classification flip (three sites, two pins re-derived, a dozen sister sites)

Sites: `espalier/fusion_manifest.py::HARNESS_EXCLUDE` (remove the prefix; the `HARNESS_INCLUDE`
entry for the same directory stays and its comment, "every espalier review scaffold is
EXCLUDEd below", is rewritten), `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` (remove
the prefix), `.gitattributes` (remove the `export-ignore` line and its comment block).

The two pins do not get deleted; they get re-derived to the new truth, because each carries
a floor and an exhaustive-enumeration shape worth keeping, and each carries a remediation
string naming the old sites, which is inverted with the assertion:

- `tests/test_git_archive_parity.py::test_claude_workflows_excluded_from_release_surfaces`
  becomes its opposite: every tracked scaffold classifies `public` and appears in the archive.
  Same floor, same enumeration, inverted assertions, renamed to say what it now pins.
- `tests/test_fuse.py::TestFuseManifestOverlay::test_no_workflow_oneshots_overlay` becomes
  "every tracked standing scaffold overlays": same floor, `_should_overlay` true for each.

**Earn the red in the direction that matters:** the mutation each NEW pin must die to is a
regression *back*: restore `.claude/workflows/` to `_LOCAL_ONLY_PREFIXES` (the first pin reds)
and to `HARNESS_EXCLUDE` (the second reds). "Old pins red under the flipped sites" only shows
the old pins were sensitive to the flip; it says nothing about the re-derived ones.

**Sister sites of the classification** (deriving command:
`command grep -rn "claude/workflows" tests/ scripts/ espalier/ docs/ .gitattributes | command grep -v _vendor`;
at authoring): `tests/conftest.py`'s five comments on the export-pruned `full_tree` marker set
(the scaffolds are named as content an export lacks; after the flip an export carries them and
the registrations keyed on their absence are re-read), `tests/test_pre_release.py`'s
classification table rows for `.claude/workflows/`, `tests/test_fuse.py`'s two other mentions
(the supported-mode docstring and the `_is_managed_md` assert), `tests/test_git_archive_parity.py`'s
docstring sentence, `scripts/final_release_matrix.py`'s full-dev-tree comment, and
`tests/test_no_internal_codenames.py::TestNoMachineLocalPaths`'s docstring, which reasons from
the withheld classification ("export-ignores `.claude/workflows/` and classifies it
`local_only`, so the wheel, the sdist and the Download-ZIP are all clean"): the deploy branch
falsifies that sentence, and that guard's own history says its trigger was a review workflow
moving from untracked to tracked. Each is rewritten to the new truth in the same commit.

### 1-C-2 The public-surface content audit (deploy branch; before the mirrors are synced)

The flip makes three internal scaffolds shipping surface, and the memory entry the pack cites
says what follows: every adopter-facing content contract now applies to them. Measured
2026-09-27: the three bodies carry seven build-history tags (`TP-186` five times in
`_fanout_audit.js`, `TP-287` twice in `_convergence_review_template.js`, plus a `round 9`) and
`espalier/provenance_census.py::path_is_scanned` scans whatever classifies `public` with no
suffix filter, so `python3 -m espalier provenance .` exits 2 the moment 1-C lands and
`tests/test_no_provenance_in_shipped_code.py` reds. And the deployed copies are scanned by
nothing: `_EXCLUDED_PREFIXES` skips `espalier/assets/` and `examples/dogfooding/.claude/`
wholesale, and `tests/test_init_tier_split.py::TestCommonTierAssetHygiene::test_common_tier_assets_have_no_internal_pack_ids`
globs `*.md` under the three kinds, so a fourth kind in that loop still matches zero `.js`.

Fix shape: (i) strip the tags from the two bodies (the rationale keeps its content and loses
its ids) or add `_ALLOWED_HITS` rows with reasons; (ii) widen the hygiene test's glob to
`CLAUDE_KIND_GLOBS[kind]` so the deployed `.js` copies are scanned; earn the red by leaving one
tag in a mirrored `.js`; (iii) run `tests/test_no_internal_codenames.py` (codenames and
machine-local paths) over the bodies; the adopt-the-release-docs pack's 0-C read them clean for
account, path and person tokens on 2026-09-26, and the re-run at execution is the record.

Oracle: `python3 -m espalier provenance .` exits 0 after (i), before the mirrors are synced;
the hygiene test reds on the planted tag and greens on its removal; the codename gate green.

### 1-D The adopter-neutral prompts and the two ledger-path defaults

From 0-A's PROMPT column, the sentences that describe this tree or name a path `init` does
not create:

- `_layered_review.js`, the AR lane: replace the parenthetical architecture rule with a
  scope an adopter tree has ("the layer boundaries this repository's `CLAUDE.md` and
  `docs/CONVENTIONS.md` declare; where they declare none, report that as the finding"). The
  FM lane keeps `tools/cc/hooks/`; `init` deploys it. **Positive pin:**
  `command grep -c "layer boundaries this repository" .claude/workflows/_layered_review.js`
  prints 1, and 3-A drives the lane once on a tree with declared layers and records a finding;
  an absence-shaped oracle alone would go green if the lane were deleted outright.
- `_fanout_audit.js`, the built-in landing finder: "cwd = the repository root".
- `_convergence_review_template.js`, the smoke lane's "confirm `memory/convergence-review-protocol.md`
  exists": made conditional ("where the repository carries it"), since `init` does not seed
  that file; the dedup instructions keep their absent-file clause.
- `_convergence_review_template.js`, `LEDGER_PATH`: keep the default; then either the critic's
  STEP 1 gains "if the file is absent, create it with the row-schema header below and treat
  the prior rows as none", or `init` seeds a skeleton `memory/CONVERGENCE_LEDGER.md`. **Seeding
  is a roster, not a directory:** dropping a file into `espalier/assets/memory/` deploys
  nothing; the seed set is `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS` (where
  `memory/README.md` sits), the single source for the deploy loop and for `clean-generated`'s
  undeploy accounting, and a hand-authored asset there is caught by no census unless it is
  also named in `espalier/provenance_census.py::_CENSUS_FORCE_SCAN` (the `memory/README.md`
  precedent; the module says an asset outside that set "would ship and be caught by NOTHING").
  Pick at execution by driving the critic prompt once on the 0-B tree; the seeded skeleton is
  the cleaner contract if both rosters are paid.

Oracle: 0-A's census re-run prints no PROMPT hit that names a path `init` does not create
unconditionally and none that describes this tree as the adopter's; the positive pin above
prints 1; `tests/test_contracts.py::TestFanoutSchemaParity` and the `STANDING_PERSISTERS`
test stay green (the schema block and the persist calls are untouched).

### 1-E The count, the obligation, the glob, the seed roster and the sentence

- `tests/_surface_expected.py` gains `EXPECTED_WORKFLOW_COUNT = 3  # class: literal`, beside
  the command and skill counts, read by the same asset-shipping test that reads them.
- `espalier/surface_impact.py`'s obligation table gains a `.claude/workflows/` row (today a
  new top-level directory prints "no declared obligations"): the count constant, the mirror
  sync, the package-data glob, the hygiene test's glob, the README and `CLAUDE.md` table row.
- `pyproject.toml` `[tool.setuptools.package-data]`: `"assets/claude/workflows/*.js"` beside
  the three per-kind `.md` globs; `tests/test_wheel_payload.py` and `tests/test_asset_shipping.py`
  pin that the wheel carries it (build the wheel and list it: the artifact, not the source
  tree, is the oracle), and `scripts/wheel_smoke.py` smokes it (1-A).
- If 1-D picked the seeded skeleton: the `_SEED_DOC_REL_PATHS` row and the
  `_CENSUS_FORCE_SCAN` row, with `pyproject.toml`'s `assets/memory/*.md` glob already
  covering the file.
- One adopter-facing sentence in `README.md`'s surface table and the root `CLAUDE.md`
  "Skills" neighbourhood, and the fan-out sentence in `.claude/CLAUDE.md`: the three
  workflows, invoked as `/<name>`, need dynamic workflows on (paid plans) and show an approval
  prompt per run.

### 1-F The mirrors and their parity

`scripts/sync_claude_mirrors.py::SUBDIRS` will read the owner (1-A), so one run populates
`espalier/assets/claude/workflows/` and `examples/dogfooding/.claude/workflows/`;
`tests/test_package_resource_parity.py`'s two parametrize lists will read the owner (its
`SUBDIRS` pin stays literal, 1-A) and pin both mirrors. The `mirror_registry.py` rows
`claude-asset` and `claude-dogfooding` already name `.claude/` as the SoT and need no new row;
the PostToolUse advisory that names the sync fires on the new subdirectory by prefix
(`tools/cc/hooks/_reinject.py`, the generated-mirror sentence, gains the fourth kind in its
text; then the vendor sync).

Oracle: `python3 scripts/sync_claude_mirrors.py` then `git status --short` shows the six new
mirror files; `pytest -q tests/test_package_resource_parity.py` green; then the full tier
(this diff touches `tools/cc/` and `espalier/`, so `scripts/proof_tier.py` prints `full`).

### 2-A The recorded no (no branch)

One sentence at each of the three surfaces, in the existing comment or comment block, in
this shape: "Decided 2026-09-DD (with the coupling census and the adopter-tree drive on
record): the scaffolds stay repository-only; `init` deploys the engine." Sites:
`espalier/fusion_manifest.py::HARNESS_EXCLUDE` (the comment above the prefix),
`espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` (the comment above the prefix),
`.gitattributes` (the comment block above the `export-ignore` line). One adopter-facing
sentence where the fan-out engine is documented (`memory/convergence-review-protocol.md`'s
"Generic scaffold" bullet, which already says the scaffold runs through the Workflow tool):
the three scaffolds are on the repository at `.claude/workflows/`, copy the one you want into
your own `.claude/workflows/`. `TP-457`'s Landing gains one appended line: the follow-on
decided, by date and record path.

Oracle: `python3 -m espalier provenance .` clean (a pack id in a comment on a shipping
surface is exactly what it polices; cite the decision by date and record path, never by pack
id); the contract tier green.

### 3-A Red-team

Two lanes on a snapshot clone built from `git diff HEAD --name-only`, both briefed with the
harness frame and FORBIDDEN to stash or check out on the live tree: `code-reviewer` over the
diff for correctness, `failure-mode-reviewer` for the ways the next session trips. Name what
this pack most likely got wrong, so the lanes have something to bite on:

- 1-C: a pin re-derived by inverting assertions can become a tautology (green for every
  classification). Ask for the regression-back mutation each re-derived pin died to, recorded.
- 1-A: a literal pin repointed at the owner reads `X == X`; ask which pins stayed literal and
  why.
- 1-D: a prompt rewritten to be adopter-neutral can say less than the scaffold does; the AR
  lane's replacement must have produced a finding on a tree with declared layers.
- 1-B: the marker's position is a platform claim; ask whether the operator's drive in the
  scratch project was recorded before any 1-B edit.
- 1-C-2: ask for the planted-tag red on the deployed `.js` copy.
- 0-B: ask whether the script's four asserts held on the execution run.

A clean red-team is the surprise; record its verdicts in Landing either way.

---

## Affected symbols

The deploy branch's set; the no branch changes comments only, which is declared under
Changed-semantics as the three comment sites so the walk sees them.

### Changed-semantics
- `espalier/surface_contract.py::CLAUDE_KIND_GLOBS` (gains `workflows`; deploy branch)
- `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` (loses `.claude/workflows/`, or its comment gains the decision)
- `espalier/fusion_manifest.py::HARNESS_EXCLUDE` (loses `.claude/workflows/`, or its comment gains the decision)
- `espalier/fusion_manifest.py::HARNESS_INCLUDE` (its `.claude/workflows/` comment rewritten; deploy branch)
- `espalier/cli.py::_packaged_md_assets` (a fourth kind, or reads the owner's globs; deploy branch)
- `espalier/cli.py::_deploy_asset_md` (a `.js` marker sibling; deploy branch)
- `espalier/managed_markers.py::_MARKER_LINE_RE` (the `//` leader; deploy branch)
- `tools/cc/sister_site_probe.py::_MANAGED_MARKER_RE` (the hand-copy, same leader; deploy branch)
- `espalier/cleanup.py::_prune_empty_dirs` (the fourth kind in its candidates; deploy branch)
- `espalier/asset_inventory.py` (a fourth `AssetGroup`; deploy branch)
- `espalier/render_surface.py` (reads the fourth kind; deploy branch)
- `scripts/wheel_smoke.py` (smokes the fourth kind; deploy branch)
- `espalier/surface_impact.py` (the obligation table gains a row; deploy branch)
- `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS` (the ledger skeleton row, if 1-D picks it; deploy branch)
- `espalier/provenance_census.py::_CENSUS_FORCE_SCAN` (the same row's census entry, if 1-D picks it; deploy branch)
- `scripts/sync_claude_mirrors.py::SUBDIRS` (reads the owner; deploy branch)
- `tools/cc/hooks/post_write_check.py::_CLAUDE_BODY_KINDS` (gains `workflows`, pinned equal to the owner; deploy branch)
- `tests/_surface_expected.py` (gains `EXPECTED_WORKFLOW_COUNT`; deploy branch)
- `tests/test_git_archive_parity.py::test_claude_workflows_excluded_from_release_surfaces` (re-derived to its opposite; deploy branch)
- `tests/test_fuse.py::TestFuseManifestOverlay::test_no_workflow_oneshots_overlay` (re-derived to its opposite; deploy branch)
- `tests/test_init_tier_split.py::TestCommonTierAssetHygiene` (the glob per kind; deploy branch)
- `tests/test_managed_markers.py::TestLineAnchoredRecognition` (the `//` negative test; deploy branch)
- `.claude/workflows/_layered_review.js` (the AR lane's scope sentence, 1-D; deploy branch)
- `.claude/workflows/_fanout_audit.js` (the built-in finder's cwd sentence and its tags, 1-D and 1-C-2; deploy branch)
- `.claude/workflows/_convergence_review_template.js` (the smoke lane's memo check, the critic's STEP 1 on an absent ledger, and its tags, 1-D and 1-C-2; deploy branch)

### Renamed
- (none -- the two re-derived pins may be renamed to say what they now pin; a rename there is a test name, not a production symbol)

### Added-paths
- `espalier/assets/claude/workflows/` (deploy branch; three files by the sync)
- `examples/dogfooding/.claude/workflows/` (deploy branch; three files by the sync)
- `espalier/assets/memory/CONVERGENCE_LEDGER.md` (deploy branch, only if 1-D picks the seeded skeleton)

### Removed-paths
- (none -- the `.gitattributes` `export-ignore` line is a line, not a path; the no branch removes nothing)

---

## Reach

The deploy branch claims the class "every roster that spells the deployed `.claude` kinds
without reading the owner". Members derived by the 1-A AST census at execution (its output is
the roster; the list in 1-A is the lower bound seen at authoring). Fill per member:

| Member | Status | Evidence |
|---|---|---|
| `espalier/cli.py::_packaged_md_assets` | (at execution) | the `layout` list carries the fourth kind or derives from the owner |
| `espalier/cleanup.py::_prune_empty_dirs` | (at execution) | the fourth kind in its candidates; driven: `clean-generated` prunes `.claude/workflows/` then `.claude/` |
| `espalier/asset_inventory.py`, `espalier/render_surface.py`, `scripts/wheel_smoke.py` | (at execution) | each reads the owner or carries the fourth kind with the reason it stays literal |
| `espalier/audit_accuracy.py`, `bench/run_benchmark.py` | (at execution) | classified: a roster (fixed) or an incidental triple (named, left) |
| `scripts/sync_claude_mirrors.py::SUBDIRS` | (at execution) | reads `CLAUDE_SURFACE_KINDS` |
| `tools/cc/hooks/post_write_check.py::_CLAUDE_BODY_KINDS` | (at execution) | cannot import the owner; `tests/test_write_guard.py` pins it equal, red first by the owner's change |
| `tests/test_package_resource_parity.py`, the `SUBDIRS` pin | DELIBERATELY LITERAL | it catches a kind dropped from the sync; pointed at the owner it would read `X == X` |
| the other test modules the census prints (eighteen at authoring) | (at execution) | each reads the owner or is named here with the reason it stays literal |
| `espalier/doctor.py` (agents-plus-commands count) | NOT REACHED, by design | its own `sister-site: ok purpose-scoped` comment: the saved plan carries no skills source |
| the prose sites (six at authoring) | (at execution) | name the four kinds once and the owner |

Stop condition: if the census at execution prints members outside these shapes (a roster
with its own semantics the fourth kind cannot join), re-raise before 1-A rather than widening
the pack to fit.

On the no branch the pack claims no class and this section records "not claimed".

---

## Pass criteria

Either branch:

- Task 0's four records exist under `reports/task0-2026-09-27/`: the Pre-work re-read, the
  0-A table, the 0-B script output, and the operator's 0-C decision with date. A pack whose
  Landing cites a decision with no record is not landed.
- `python3 scripts/proof_tier.py --run` PASS at the tier it prints for the diff (the deploy
  branch earns `full`; the no branch `contract`).
- No assertion in `tests/test_git_archive_parity.py`, `tests/test_fuse.py`,
  `tests/test_finding_ledger.py`, `tests/test_contracts.py`, `tests/test_managed_markers.py` or
  `tests/test_convergence_workflow_stages.py` may be weakened; a floor may rise, a re-derived
  pin must have died to the regression-back mutation 1-C names before it went green, and no
  roster in those files may shrink.

Deploy branch:

- `python3 -m espalier provenance .` exits 0 **after 1-C-2** (it exits 2 between 1-C and
  1-C-2 by construction; that red is recorded, not a failure of the criterion).
- `python3 -c "from espalier import surface_contract as s; print(s.CLAUDE_SURFACE_KINDS)"`
  prints four kinds, and the 1-A AST census prints only the owner, the hook's tuple and the
  sites the Reach table names as deliberately literal.
- A wheel built from the tree (`python3 -m build --wheel`, then list it) carries the three
  `.js` under `espalier/assets/claude/workflows/`; `espalier init` on a tree built by
  `tests/_adopter_tree.py::build_adopter_tree` writes the three under `.claude/workflows/`
  with the marker on line 1, and a second `init` reports `skipped_no_drift` for each; a copy
  with the marker removed reports `skipped_user_file`; `clean-generated --execute` on that tree
  removes them and prunes the directory.
- 0-A's census re-run after 1-D prints no PROMPT hit that describes this tree as the adopter's
  and none naming a path `init` does not create unconditionally; the 1-D positive pin prints 1.
- The hygiene test reds on a planted tag in a mirrored `.js` and greens on its removal.
- `python3 scripts/sync_claude_mirrors.py` is a no-op after the pack (both mirrors already
  converged), and `tests/test_package_resource_parity.py` is green.

No branch:

- The three comment sites and the protocol memo's bullet each carry the decision sentence,
  `TP-457`'s Landing carries the appended line, `python3 -m espalier provenance .` exits 0, and
  nothing under `espalier/assets/` changed.

---

## Files touched

Deploy branch:

- **Modified:** `espalier/surface_contract.py`, `espalier/fusion_manifest.py`,
  `espalier/cli.py`, `espalier/surface_impact.py`, `espalier/managed_markers.py`,
  `espalier/cleanup.py`, `espalier/asset_inventory.py`, `espalier/render_surface.py`,
  `scripts/sync_claude_mirrors.py`, `scripts/wheel_smoke.py`,
  `tools/cc/hooks/post_write_check.py`, `tools/cc/hooks/_reinject.py`,
  `tools/cc/sister_site_probe.py` (then `python3 scripts/sync_vendor_cc.py` for all three),
  `.gitattributes`, `pyproject.toml`, `bench/corpus/BC-026-marker-substring-forgery.json`,
  `tests/_surface_expected.py`, `tests/test_git_archive_parity.py`, `tests/test_fuse.py`,
  `tests/test_package_resource_parity.py`, `tests/test_asset_shipping.py`,
  `tests/test_init_tier_split.py`, `tests/test_managed_markers.py`,
  `tests/test_surface_contract.py`, `tests/test_no_internal_codenames.py` (the docstring),
  `tests/test_pre_release.py` (the classification rows), `tests/conftest.py` (the five
  comments), `scripts/final_release_matrix.py` (the comment), the three scaffolds under
  `.claude/workflows/`, `.claude/commands/implement-pack.md` (then
  `python3 scripts/sync_claude_mirrors.py`), `espalier/assets/CLAUDE.md`, `.claude/CLAUDE.md`,
  `README.md`, `CLAUDE.md`; and, if 1-D picks the seeded skeleton,
  `espalier/managed_inventory.py` and `espalier/provenance_census.py`.
- **Read at 1-A and 1-C, edited only if their assertion message spells three kinds or names
  the workflows prefix:** `tests/test_write_guard.py` (the hook-tuple pin, red until the hook
  follows the owner), `tests/test_managed_paths.py` (re-derives the deployed set from
  `_packaged_md_assets`), `tests/test_surface_impact.py` (pins the obligation table's file
  list), `tests/test_paths_parity.py` and `tests/test_release_archive_class_regression.py`
  (assert other prefixes stay in `_LOCAL_ONLY_PREFIXES`; at authoring neither names
  `.claude/workflows/`), `tests/test_denial_reasons.py`, `tests/test_reinject_sync.py`,
  `tests/test_no_provenance_in_shipped_code.py` (red between 1-C and 1-C-2, green after),
  `espalier/fuse.py` (the overlay predicate; unchanged, its include-exact arm not taken),
  `docs/CONVENTIONS.md` (names the managed deploy path; gains nothing unless a sentence spells
  three kinds), `espalier/audit_accuracy.py` and `bench/run_benchmark.py` (classified by 1-A).
- **New:** `espalier/assets/claude/workflows/*.js` and `examples/dogfooding/.claude/workflows/*.js`
  (by the sync, never by hand); `espalier/assets/memory/CONVERGENCE_LEDGER.md` if 1-D picks
  the skeleton.
- **Deleted:** none.
- **Unmodified on purpose:** `espalier/fan_out_findings.py`, `espalier/finding_ledger.py`,
  `espalier/mirror_registry.py` (no new row: the existing two rows cover the new
  subdirectory by prefix), `espalier/doctor.py`, `espalier/managed_markers.py::MARKER_SCAN_BYTES`
  and its hand-copy (never widened).

No branch:

- **Modified:** `espalier/fusion_manifest.py`, `espalier/surface_contract.py`,
  `.gitattributes` (comments only), `memory/convergence-review-protocol.md` (one sentence),
  `task-packs/Done/TP-457-adopt-the-release-docs-and-sweep-the-withheld-set.md` (one appended
  Landing line; local-only, a record amendment).
- **New / Deleted:** none.

---

## Sub-task ordering

0. **Pre-work** the platform re-read (two facts; outcome (d) if either moved) → **0-A** the
   census (the refuting rule first; the table into the record) → **0-B** the drive (the
   script by path; the instrument gate; its JSON into the record) → **0-C** the operator's
   decision (recorded). Checkpoint: the four record files exist. A refuting result or
   outcome (d) ends here.
1. Deploy branch: **1-B's operator drive first** (the scratch project, the line-1 comment, the
   roster read; recorded; a refusal re-raises) → **1-A** the roster at the owner and the class
   sweep → checkpoint: the census and the four-kinds print, the hook pin's earned red. **1-B**
   the marker at the recogniser, its hand-copy, the corpus twin, the negative test →
   checkpoint: the four-state tests and the earned red. **1-C** the flip, then the two new
   pins red under the regression-back mutation and green after, then the sister-site sweep →
   checkpoint: the two earned reds recorded, provenance red as expected. **1-C-2** the content
   audit → checkpoint: provenance clean, the planted-tag red on the hygiene test. **1-D** the
   prompts and the ledger default → checkpoint: the census re-run and the positive pin.
   **1-E** the count, the obligation, the glob, the seed rows, the sentence → checkpoint: the
   wheel listing. **1-F** the syncs and parity → checkpoint: `sync_claude_mirrors.py` a
   no-op, then the full tier.
   No branch: **2-A** the sentences → checkpoint: provenance clean, contract tier green.
2. **3-A** red-team on a snapshot clone; fold every accepted finding as one batch; re-prove
   at the tier the final diff earns.
3. Branch, commit, PR with auto-merge (Core Rule 10); the deploy branch's diff touches
   `tools/cc/hooks/`, so the PR title carries the approval marker bound to the head SHA.

---

## Estimated effort

| Sub-task | Budget |
|---|---|
| Pre-work re-read, 0-A census and classification | 0.75 h |
| 0-B adopter-tree drive (script, run, read) | 1 h |
| 0-C decision (operator) | 0.25 h |
| 1-B operator drive in a scratch project | 0.5 h (operator) |
| 1-A roster at the owner and the class sweep (ten production modules, nineteen tests, six prose sites) | 3 h |
| 1-B marker: recogniser, hand-copy, corpus twin, negative test, four-state tests | 2.5 h |
| 1-C flip, two re-derived pins with regression-back reds, sister-site sweep | 2.5 h |
| 1-C-2 content audit: tags, hygiene glob, codename gate | 1.5 h |
| 1-D prompts, the memo check, the ledger default with its two roster rows | 2 h |
| 1-E count, obligation, glob, seed rows, sentence | 1 h |
| 1-F syncs, parity, full tier | 1.5 h (the tier runs unattended) |
| 2-A the recorded no | 0.5 h |
| 3-A red-team and the fold | 2 h |
| **Deploy branch total** | **about 18.5 h** over three sessions |
| **No branch total** | **about 4.5 h** in one session |

---

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: (deploy branch) the two re-derived pins red under the regression-back mutation, green after; the hook's kinds pin red on the owner's change; the hygiene test red on a planted tag in a mirrored `.js`; the recogniser's negative test red when widened to a bare token
- Red-team: (authoring) two lanes on a snapshot clone, both REQUEST CHANGES, every finding verified against the bytes and folded in one batch, 2026-09-27; (execution) to record
- Reach: (deploy branch) per member from the 1-A AST census at execution; (no branch) not claimed
- Date:
