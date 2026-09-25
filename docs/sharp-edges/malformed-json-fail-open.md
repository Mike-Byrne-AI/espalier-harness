# Malformed / Non-Dict JSON Fail-Open (Class-B)

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Malformed / Non-Dict JSON Fail-Open (Class-B)"

**What it is:** a bare parse-then-dereference

```python
data = json.loads(raw)
return data.get("name", root.name)
```

fails **open** on valid-JSON-but-non-dict input. `[]`, `"s"`, `42`, `null`
all parse cleanly, so the `except json.JSONDecodeError` handler never fires —
then `data.get(...)` raises `AttributeError` (`'list' object has no attribute
'get'`), which sails past that handler, the hook exits 1, and Claude Code
**fail-opens** per the hook protocol. Concretely:

- A `[]` `package.json` crashed `_repo_name` in `session_start.py` /
  `post_compact.py` → SessionStart exited 1 → the *entire* MEMORY +
  SHARP_EDGES-TOC context injection was dropped.
- A non-dict `cc/blueprints/latest.json` crashed every
  `cognitive_blueprint` mutator (`bp["reasoning_entries"]` on a list).
- A non-dict blueprint file crashed `cmd_chain`.
- Plus loader-pattern siblings (`_load`, `_load_latest`,
  `_load_manifest_unlocked`, `_load_json`) that `return json.loads(...)` raw, so
  a non-dict escapes the function and crashes the *caller*; and an audit-log
  first-line reader (`_integrity`) and a reflect-report parser
  (`reflect_trigger`, `cmd_record_reflect`) with the same shape.

A manual enumeration of this shape across the harness is not reliably
complete — building the regression gate (below) surfaces sites the
enumeration misses (e.g. a fail-open hidden inside a ternary assignment).

**The fix — one chokepoint + one gate, not N point patches:**

1. **Chokepoint** — `tools/cc/_json_safe.py :: load_json_dict_safe(source, *,
   default=_MISSING)`. Returns the parse iff it is a `dict`, else `default` (a
   *fresh* `{}` when unspecified — no shared-mutable trap; pass `default=None`
   for a loader typed `dict | None`). Collapses *every* failure shape — non-str
   input, undecodable bytes (BOM-tolerant via `utf-8-sig`), `JSONDecodeError` /
   `ValueError`, deep-nesting `RecursionError` (the pure-Python scanner; the C
   scanner is iterative), and valid-JSON-non-dict. Lives at the `tools/cc/`
   level (sibling to `_paths` / `_freshness_cache`) so both `tools/cc/*.py` and
   `tools/cc/hooks/*.py` import it; hooks add `tools/cc` to `sys.path` via
   `parent.parent`. **It must be deployed** — registered in
   `cli.INIT_TOOL_SCRIPTS` + `managed_paths.STANDARD_MANAGED_TOOLS`, or a fresh
   `espalier init` hits `ModuleNotFoundError`.

2. **The gate (class-closer)** — `tests/test_json_dict_safe.py ::
   find_json_fail_opens` AST-walks **both `tools/cc/` and `espalier/`**
   (`espalier/` cannot import the `tools/cc` chokepoint per the isolation rule,
   so its sites satisfy the gate via inline `isinstance(x, dict)` guards or the
   pragma). It fails on
   any `json.loads` / `json.load` whose result is dict-dereferenced
   (`.get`/`[..]`/`.items`/`.keys`/`.values`/`.setdefault`/`.pop`/`.update`)
   **or escapes via `return`**, without an `isinstance(x, dict)` guard in the
   same function and not routed through the chokepoint. It exempts
   `_json_safe.py`, honours a `# json-dict-safe: ok <reason>` pragma, and flags
   `from json import loads/load` aliasing (which would defeat the attribute
   match). The gate is **earn-the-red-validated** (`TestGateEarnsRed`): it must
   flag synthetic fail-opens and pass guarded twins, so it can never silently
   degrade to a no-op.

**Two valid ways to satisfy the gate** — both close the fail-open:

- Route through `load_json_dict_safe` (preferred for sites that want a silent
  graceful default).
- Keep inline `json.loads` + an `isinstance(data, dict)` guard (used by
  `_repo_name` ×2 and `_blueprint_summary`, where the existing **malformed-JSON
  WARN** is observability worth preserving — the chokepoint would swallow it
  silently).

The `RecursionError` catch is load-bearing on a deeply-nested JSON bomb. A
nested non-dict value pulled back out of the now-safe dict is a separate
hazard: a corrupt `.espalier/integrity.json` whose `files` key is a non-dict
would crash `sorted(recorded.items())` in `_verify_unlocked` (`espalier
integrity verify` exit 1 = a visibility fail-open), so a non-dict `files`
returns `(False, ["<files_not_object: …>"])`, matching the schema/algorithm
guards. The gate follows `B = A` aliases and `import json as j`, treats
`.pop`/`.update` as dict-derefs, and flags non-Name assign targets (tuple-unpack
/ attribute / subscript / chained).

**The chokepoint guarantees only the TOP level is a dict.** A nested value
(`data["k"]`) is still untyped — guard it per-field with `isinstance` where it's
dereffed as a dict (most sites already do, e.g. `stop_gate` `isinstance(cmds,
list)`). The gate does not model this (it would over-fire); it is a separate
per-field discipline.

**Known-limits** (documented, not bypasses): the gate's guard-detection is a
*proxy* (`isinstance(X, dict)` on the way to the deref — the statements that
run before it in its block and in each enclosing block, a preceding branch
that returns pruned, the `if` header around it; since DEF-833, 2026-09-17,
never "anywhere in the function", which greened a second deref once one
branch type-checked the name), so a deliberately fake/no-op guard would pass
it — malicious authoring, not honest drift, and CI/`harness-guard.yml` is the
real enforcement. The rule is block-prefix, not control flow: a guard under
a condition above the deref counts, and the header's polarity is not read.
The gate models same-function dataflow (incl. simple aliases + the
loader-return escape: the raw value returned bare, in a container, a
conditional or a boolean — a parse handed to a call inside the `return` is
the pass to a consumer the gate does not follow, exactly as it is on any
other line), not arbitrary cross-function flow or a parse stored into a
container then dereffed elsewhere. Inputs are size-capped by callers upstream.

See ESPALIER_MEMORY.md and `docs/RELEASE_FINDINGS_LEDGER.md` for the execution record.
