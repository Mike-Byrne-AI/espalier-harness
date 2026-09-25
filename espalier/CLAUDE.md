# espalier/

**Doing:** The harness engine — fingerprinting, analysis, the cognitive system, surface inventory + contracts, release gating, pack manifests, atomic I/O.
**Don't break:** `espalier/` imports from `espalier/` ONLY — never `tools/cc/` (pinned by `tests/test_contracts.py::TestToolsCcNoEspalierImports`). `espalier/scanners/` is stdlib-only. `espalier/_vendor/cc/` is a byte-mirror of `tools/cc/` governed by THAT folder's rules — never hand-edit it here. A new `espalier/*.py` auto-enrolls in the public-surface contracts (provenance no-build-tags, import-direction, mirror + hygiene); the full suite catches a miss only after the fact. Path comparisons use `.replace("\\", "/")`.

## Before writing or editing in this folder:

1. Check the import direction: a new `import tools` in `espalier/`, or a third-party lib inside a
   scanner, is a contract violation.
2. Adding a new shipped path? Run `python -m espalier surface-impact <pack>` to see its
   count-pin / mirror / hygiene / provenance obligations up front.
3. Operator-facing strings are 7-bit ASCII — *including* a report body built with `lines.append(...)`
   and returned via `"\n".join(...)`. A `—`/`•`/`→`/`…`/emoji crashes Windows redirected stdout.
4. Touched the engine or a hook? Refresh the integrity manifest before commit.
5. Writing a file into the adopter's tree? `_atomic_io.atomic_write_text` (or `atomic_write_bytes`
   for a verbatim copy): `tests/test_atomic_io.py`'s census reds on a raw `write_text`, dump,
   `open(..., "w")` or `shutil` copy here; an exemption is a rostered count and reason.

**Read first:** the root [`CLAUDE.md`](../CLAUDE.md) "Architecture Rules" +
[`docs/CONVENTIONS.md`](../docs/CONVENTIONS.md)
