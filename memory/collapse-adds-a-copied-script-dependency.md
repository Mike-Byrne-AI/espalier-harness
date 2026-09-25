# A collapse adds a dependency to every copied script

**Status:** active
**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md` folder router and sibling cross-links (the ESPALIER_MEMORY.md hot index is at its 120-line cap; not indexed there).

Collapsing an inline helper into a shared module (a script's own `_repo_root` →
`_paths._repo_root`) is behavior-preserving for the LOGIC but ADDS a runtime
`import` to every file that now delegates. Real `espalier init` deploys all of
`tools/cc/`, so the new dependency is present in the field — but any context that
copies a **minimal subset** of a script's files (test fixtures, partial deploys,
`claude -p` sandboxes) suddenly misses it, the script crashes on import in its
subprocess, and its side-effect (a written file) silently doesn't happen.

## Why (the cost it prevents)

The failure is **silent and downstream**. A crashing copied-script exits its
subprocess non-zero with no captured traceback; the symptom surfaces one layer
later as a *missing artifact* — e.g. `FileNotFoundError: cc/blueprints/latest.json`
in the fixture that expected `cognitive_blueprint.py start` to write it — not as a
`ModuleNotFoundError`. So the diagnosis has to trace back from "the expected output
wasn't written," which is exactly the misdirection [[complacent-oracle]] and
[[forensically-audit-the-workflow-not-just-output]] warn about: audit the
execution, not just the end-state.

Targeted tests miss it: they exercise the collapsed helper directly, in-process,
with the real dependency importable. Only the FULL suite — which includes the
unrelated fixtures that hand-copy a curated file subset — reds. The honest oracle
is the whole suite, not the slice that shares your mental model of "what this
change touches" — the same coverage-blind-spot shape as an untracked new file
slipping a `git ls-files` contract (see [[git-artifact-hygiene]] on the
tracked-vs-untracked check).

## Evidence (TP-276 Wave 1-G, 2026-07-14)

`cognitive_blueprint._repo_root` and `execution_plan._plan_path` were collapsed to
route through a new `import _paths`. Targeted probe/unit tests stayed green. The
full suite went **8 red** — four fixtures across `test_hooks` /
`test_session_resume` / `test_session_start_source_aware` /
`test_subprocess_env_isolation` each copy `("cognitive_blueprint.py",
"_blueprint_limits.py", "_json_safe.py")` into a tmp `tools/cc/` but NOT
`_paths.py`. cognitive_blueprint hit `ModuleNotFoundError: _paths`, wrote no
blueprint, and the fixtures failed downstream on the missing `latest.json`. Fix:
add `_paths.py` to each fixture's copy list — honest, because the dependency is
real and always deployed.

## How to apply

1. When a collapse adds an `import` to a file that is COPIED (not pip-installed)
   anywhere, grep for every place that copies that file's dependency set and
   extend it. `grep -rn '<known_sibling_dep>.py' tests/` finds the fixtures — here
   `_blueprint_limits` / `_json_safe` were the tell.
2. Run the FULL suite for the collapse's commit gate, not a targeted slice — the
   subset-copying fixture lives in an unrelated test file a slice skips.
3. Trace a "missing artifact" failure back to a possible silent subprocess crash,
   not just to the assertion that read the artifact.
4. Prefer a shared-helper home the consumers ALREADY depend on; when the correct
   home is genuinely a new dependency (`_paths` is), fix the fixtures rather than
   contorting the collapse to avoid the import.

From the TP-276 concept-duplication class fix (Wave 1-G).
