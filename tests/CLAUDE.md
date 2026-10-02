# tests/

**Doing:** The pytest suite — contract tests (surface pins, parity, hygiene, provenance), unit tests, shared fixtures (`conftest.py`).
**Don't break:** A new `test_*.py` file MUST be classified in `_MARKER_RULES` (`tests/conftest.py`)
or carry a `# pytest-marker: default-unit` opt-out — `test_marker_taxonomy` fails the FULL suite
otherwise. `git add` a new test file BEFORE gating: the git-ls-files-based contracts are blind to
an untracked file (it false-greens). Names follow `TestX` classes + `test_{specific_behavior}`
(docs/CONVENTIONS.md). Load `tools/cc/` modules via `importlib.spec_from_file_location`, never a
plain import — that would drag espalier into their zero-import graph.

## Before writing or editing in this folder:
1. Earn the red: write the test, prove it RED against the UNFIXED code, then fix → GREEN. A test
   that only ever passed proves nothing.
2. Classify a new test file in `conftest.py::_MARKER_RULES` (or opt out explicitly).
3. Tight loop on the target test; but the FULL suite is the honest gate — contracts and a newly-tracked file only fire there.
4. A test that drives a CLI with a repo path `monkeypatch.chdir`s into a scratch repo first: a dropped
   argument falls back to the cwd, THIS checkout, which the live-tree guard does not watch under `.espalier/` (a `pin --all <repo>` test re-pinned the live manifest, 2026-09-12).
5. A test that reads live-tree content (a doc, `git ls-files`, the memory corpus, a walk from the repo root) or asserts anything ABOUT the tree it runs in (that it is or is not an export, that a path is tracked, a population's size): drive it once on an extracted release archive BEFORE the matrix does -- `python3 scripts/archive_probe.py -- tests/<module>.py -q -p no:cacheprovider` (about four minutes; `git add -N` a new file first, the builder enumerates the index) -- and drive EVERY test file a pack touches, the one it adds included, not only the modules the defect named (stage 02 caught a pack's own new file an hour later, 2026-09-23). A red there is a registration in `conftest.py::_FULL_TREE_NODEIDS` at test granularity, measured; the file-granular contract sees only the literal-path shape.

**Read first:** [`docs/CONVENTIONS.md`](../docs/CONVENTIONS.md) (test naming + fixture patterns)
