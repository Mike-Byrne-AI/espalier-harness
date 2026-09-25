# tools/cc/

**Doing:** Standalone scripts run without espalier — `cognitive_blueprint`, `execution_plan`, `sister_site_probe`, `ci_guard`, `session_resume`, `_paths`, `reflect_protocol` (hooks live in `hooks/`).
**Don't break:** ZERO espalier imports — these run standalone. **Every `.py` edit byte-mirrors to `espalier/_vendor/cc/` — run `python3 scripts/sync_vendor_cc.py` before commit** (`tests/test_vendor_cc_parity.py` reds on drift). That mirror is `**/*.py` only, so the `.md` files here have no vendored twin; it is one of nine byte-pinned rows whose census is `espalier/mirror_registry.py`, and a sibling family under `espalier/_vendor/` needs a DIFFERENT script — `sync_vendor_cc.py` exits 0 without fixing it. Sibling imports resolve via the script's own dir on `sys.path` (`import _paths`); a script COPIED without its sibling deps crashes SILENTLY in its subprocess (symptom: a missing artifact downstream, not an import error), so when you add a sibling import, extend every fixture/deploy that copies a file subset.

## Before writing or editing in this folder:

1. After editing, sync the vendor mirror (`sync_vendor_cc.py`) — the single most-missed step here.
2. Added a new `import <sibling>`? `grep -rn '<sibling>.py' tests/` and extend every fixture that hand-copies a subset.
3. Run `pytest tests/test_vendor_cc_parity.py` + the touched script's tests.
4. Operator-facing strings are 7-bit ASCII — *including* a report body built with `lines.append(...)`
   and returned via `"\n".join(...)`, and hook text reaching the operator via `additionalContext`.
   A `—`/`•`/`→`/`…`/emoji crashes Windows redirected stdout.

**Read first:** [`hooks/CLAUDE.md`](hooks/CLAUDE.md) (the hook contract, same folder family)
