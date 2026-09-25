# espalier/scanners/

**Doing:** Stdlib-only scanner modules that read source files and report findings (godfile detection, print-statement audit, performance smells, exception patterns).
**Don't break:** Zero third-party imports — scanners must run under any minimal Python install. Pure Python AST walks; no compiled deps. `tests/test_contracts.py::TestScannersStdlibOnly` enforces this.

## Before writing or editing in this folder:

1. Read [`memory/scanner-constraints.md`](../../memory/scanner-constraints.md) — accumulated AST-walk patterns and stdlib-only constraint history.
2. A new scanner WILL self-collide on its own defining material + trip sister-site SoTs — run the sweep in `docs/SHARP_EDGES.md` "A new pattern-detector trips the harness's own defenses".
3. After edits, run `pytest tests/test_scanners.py tests/test_contracts.py::TestScannersStdlibOnly`.

**Read first:** [`memory/scanner-constraints.md`](../../memory/scanner-constraints.md)
