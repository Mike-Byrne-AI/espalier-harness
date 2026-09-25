# plan_guard adopter source roots — config knob, not MAINTENANCE_MODE

**Status:** active
**Linked from:** docs/SHARP_EDGES.md "Plan Guard Adopter Source Roots"

**What it is:** plan_guard's default `EXEMPT_PREFIXES` cover the
harness's own layout (`tests/`, `tools/cc/`, `.claude/`, `cc/`,
`reports/`, `memory/`, `docs/`, `task-packs/`). Conventional Python adopters keep source under `src/`
or `lib/` — neither is exempt. Every tiny edit to `src/myapp/foo.py`
(typo, type annotation, rename) trips the plan-required gate.

The load-bearing comment in `tools/cc/hooks/plan_guard.py` (just above the
`EXEMPT_PREFIXES` tuple) is explicit about *why* the default is strict:

> Critical: a user repo with its own `espalier/` directory MUST NOT
> skip plan discipline — that would silently disable the gate for
> user code.

The same logic applies to `src/`: adding it to the universal exempt
list would silently turn off plan discipline for every conventional
Python adopter.

**How you hit it:** The frustration shape this relieves:

1. `pip install espalier-harness && espalier init .`
2. Source lives in `src/myapp/`.
3. Every Edit triggers plan_guard with "No active execution plan
   (status='missing')…" — even for a one-character typo fix.
4. Adopter, frustrated, sets `ESPALIER_MAINTENANCE_MODE=1` in their
   shell rc to make it stop.
5. From that point forward, `MAINTENANCE_MODE` silently bypasses
   plan_guard's plan-required check **and** write_guard's
   protected-zone check **and** stop_gate's documentation-refresh
   and code-review gates **and** subagent_stop's blueprint append. The harness's discipline product becomes
   advisory.

**How to avoid it:** Add the exempt prefix in `espalier.toml`
(opt-in, narrow, no env-var leakage):

```toml
# espalier.toml — adopter customization
plan_exempt_prefixes = ["src/", "lib/"]
```

Schema rules:

- Each entry must end with `/`.
- Absolute paths (`/usr/...`) are rejected.
- `..` traversal (`../foo/`) is rejected.
- An invalid entry drops the *entire* list back to strict mode and
  writes a `[plan_guard]` advisory to stderr. (Strict fallback is
  intentional: a broken config should not silently relax the gate
  on entries that happened to parse.)
- A `[plan_guard]` table or a bare `exempt_prefixes` key (without
  the `plan_` prefix) in `espalier.toml` triggers a second
  `[plan_guard]` advisory naming the correct flat key. The hook
  reads ONLY the top-level `plan_exempt_prefixes`; the documented-
  wrong shapes are silent-fallback typos pre-fix docs taught for
  a period. The advisory makes the schema mismatch observable
  instead of silently denying every write.

The hook-side reader is
`tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes`. The
espalier-side mirror is `HarnessConfig.plan_exempt_prefixes` in
`espalier/models.py` (populated by `espalier.config.load_config`
via its flat top-level fields filter). Both readers must agree —
the contract test `tests/test_plan_guard_adopter_config.py` pins
the schema.

**Why this is the right relief, not `MAINTENANCE_MODE`:**

| Mechanism | Scope | Plan_guard | Write_guard | Stop_gate |
|---|---|---|---|---|
| `plan_exempt_prefixes` | adopter source roots | bypassed for matching paths only | unchanged | unchanged |
| `ESPALIER_MAINTENANCE_MODE=1` | harness self-edits | bypassed entirely | protected-zone check bypassed | gates 2+3 bypassed |

`MAINTENANCE_MODE` is scoped for harness self-edits (committing to
`tools/cc/hooks/` from inside this very repo). It is documented in
`docs/SHARP_EDGES.md` ("Maintenance Mode") as an env-var that must
be set in the parent shell **before launching** Claude Code; mid-
session `export` does not reach already-running hooks. Adopters
should never need it.

**Discoverability:** `docs/QUICKSTART.md` includes the customization
section as a first-class adopter step, named explicitly as "the
right way" to relieve plan_guard friction. The pre-OSS philosophy
is *discipline IS the product* by default, with
*customization is expected* exposed via a concrete, narrow
mechanism — not by a sweeping env-var bypass.
