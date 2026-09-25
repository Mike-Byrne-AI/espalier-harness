# Scanner constraints

**Status:** active
**Linked from:** espalier/scanners/CLAUDE.md ("Read first")

Accumulates lessons from authoring and extending the stdlib-only
scanner modules under `espalier/scanners/`.

## The stdlib-only rule

`espalier/scanners/*.py` must use ONLY Python stdlib. No `requests`,
no `pydantic`, no third-party anything. They ship as part of the
installed package and must work without third-party deps present
(adopters may pin specific dep sets; scanners must survive in any
minimal Python env).

**Permitted imports** (from `architecture-analyst.md`'s example):

`os`, `re`, `sys`, `ast`, `json`, `math`, `pathlib`, `typing`,
`collections`, `itertools`, `functools`, `dataclasses`, `abc`, `io`,
`copy`, `hashlib`, `textwrap`, `string`, `enum`, `contextlib`,
`warnings`, `from __future__`.

Anything else is a violation.

## The actual contract test class

The class that pins the stdlib-only rule is:

```python
# tests/test_contracts.py
class TestScannersStdlibOnly:
    ...
```

**Not** `TestScannerImports` — TP-89's first-draft pack body cited
the wrong class name in the `espalier/scanners/CLAUDE.md` router
body and the matching verification step. The TP-62 pack-artifact
review v1 caught the wrong name only in the router body; the v2
review caught the stale name in the Motivation table. Lesson: when
naming a test class in pack prose, grep `^class Test` against the
live `tests/` tree to verify before commit.

To verify the rule's coverage:

```bash
grep -n "^class Test" tests/test_contracts.py | grep -i Scanner
# Expected: 179:class TestScannersStdlibOnly:
```

## AST walks, not regex

Scanners parse source via `ast.parse(source)` + `ast.walk(tree)` —
not regex pattern matching. Reasons:

- Regex misses aliased imports (`import requests as r`), conditional
  imports (`if X: import Y`), and matches in strings/comments.
- AST nodes give precise line numbers + column offsets for
  reporting.
- The dual-witness pattern (TP-37) used in `tests/test_release_denylist.py::TestNoSharedImports`
  is itself an AST-walk check: the test asserts the denylist module
  has no shared imports with the classifier module by walking
  Import/ImportFrom nodes (NOT substring grep, which false-fires on
  error-message strings naming the same module).

## Pre-cut pack-artifact review for scanner-adjacent packs

Any pack that:

- adds a new scanner module
- modifies an existing scanner's import list
- references the stdlib-only rule in its body

…must run the TP-62 0-A review against `tests/test_contracts.py`
specifically. The v1 → v2 reauthor cycle (TP-89) is documented in
`memory/task-packs.md`; scanner-class-name accuracy is a recurring
miss.

## Conditional imports inside functions are still scanned

A scanner module that does:

```python
def scan(repo: Path):
    if sys.platform == "win32":
        import some_third_party  # WRONG — caught by AST walk
```

…fails the stdlib-only rule even though the import is conditional.
The AST walker sees the `ImportFrom` node regardless of containing
control flow. If a scanner genuinely needs an optional dep, the
pattern is: don't write it as a scanner — write it as a separate
helper in `espalier/` (which does NOT have the stdlib-only rule)
and have the scanner call it via subprocess if needed.

## Adopter context

When the `architecture-analyst` agent (common-tier) runs in an
adopter repo, the `espalier/scanners/` directory doesn't exist. The
agent body (post-TP-87 genericization) treats the rule as an
"Example (Espalier-Harness's own)" — adopters substitute their own
isolation layer (or skip the check if they have no such layer).

The genericization pattern is documented in
`memory/asset-mirroring.md` and the docs/CONVENTIONS.md
"Categorized memory + sharp-edges" section.

## See also

- `docs/CONVENTIONS.md` "Architecture Rules" — the stdlib-only rule
  as the canonical statement.
- `tests/test_contracts.py::TestScannersStdlibOnly` — the binding
  contract.
- `tests/test_release_denylist.py::TestNoSharedImports` — example of
  AST-walk independence verification (different rule, same shape).
