Surface where a repo's test rails are missing: enumerate the public Python
surface mechanically, cross-reference it against the test tree, and risk-rank
the untested gaps.

```bash
python -m espalier strengthen .
```

Writes an advisory report to `reports/strengthen_report.json` and
`reports/strengthen_report.md`, and prints the ranked table. It reads code; it
never writes, generates, or commits a test.

## What it does

1. **Enumerate** — parse every `*.py` file with `ast` (no import, no execution)
   and collect the public top-level surface: names in `__all__`, or
   non-underscore functions / classes / constants when there is no `__all__`.
2. **Cross-reference** — build a one-pass name index over the repo and mark a
   symbol *tested* when its name is referenced in a test file. Two modes:
   - **mode-a** — a test tree exists → report the symbols no test references.
   - **mode-b** — no test infrastructure → every public symbol is reported
     untested (the honest state of a fresh repo).
3. **Risk-rank** — score each untested symbol by mechanical signals (exported,
   fan-in, an I/O/state heuristic, body size) and show the highest-risk first.

## Options

| Flag | Meaning |
|---|---|
| `--top-n N` | Show the top N highest-risk untested symbols (default: 20). The report always states how many gaps were bounded out of view. |
| `--skip-fan-in` | Skip the fan-in reference count (faster; drops one ranking signal). |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Report produced (including the Python-only and no-gaps cases). |
| `2` | Precondition failure — the repo path is missing or not a directory. |

It never returns `1`: an advisory report has no completed-but-failed gate.

## When to use

- **On a fresh or thin repo**, before leaning on the harness's gates — the
  gates are only as strong as the tests they can run, so build the highest-risk
  rails first.
- **Periodically**, to see which new public surface has drifted ahead of its
  tests.

## Read the report honestly

- The cross-reference is **by name** (an AST token index; comments and strings
  are excluded), not coverage.py ground truth. A symbol referenced by name in a
  test — even without an assertion — reads as tested, and a same-named symbol
  in another module shares the signal.
- The risk score is a weighted sum of **mechanical heuristics**, not measured
  severities. It orders the list; it is not a magnitude.
- A starting test written over existing code is a **characterization** test: it
  captures *current* behavior as a regression net, **not** a correctness proof.
  It can lock in a current bug. Review each one before you trust it.

Mechanical enumeration supports Python only for now; a non-Python repo gets a
plain notice, not a crash.

## Next step — hand a gap to `/test-this`

`strengthen` ranks the gaps; by design it never writes a test (advisory-only). To close
the top-ranked gap, feed the file to `/test-this`:

```
/test-this <top-ranked file>
```

`/test-this` delegates to the `test-writer` agent, which matches the project's existing
test patterns. Review the generated test before trusting it (see "Read the report
honestly" above — a starting test captures *current* behavior, not correctness).
