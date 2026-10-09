---
description: Generate tests for a specific file matching project patterns. Delegates to the test-writer agent for orthogonal-context generation.
---

Generate tests for a specific file matching project patterns. Delegates to the test-writer agent for orthogonal-context generation.

The user will specify a file path.

1. Identify the target file and confirm it exists. If the user did not name
   a file, ask which one.

2. Derive the repository's own runner and test layout, the way `/preflight` does,
   so the brief names them instead of assuming pytest (each tool call is a fresh
   shell, so step 4 derives again):
   ```bash
   PY=; for c in 'python3' python 'py -3'; do $c -c 'import sys, espalier; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && { PY=$c; break; }; done; [ -n "$PY" ] || { echo 'no Python 3.10+ with espalier answered to python3, python or py -3' >&2; exit 1; }
   TEST=$($PY -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); from espalier.harness_config import preflight_command; print(preflight_command('test'))") || exit 1
   [ -n "$TEST" ] || { { [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; } && command -v pytest >/dev/null 2>&1 && TEST='pytest -q' && echo 'test gate: pytest -q (the PATH fallback: nothing declared or detected)' >&2; }
   [ -n "$TEST" ] || { echo 'NO TEST GATE RAN - declare [extra_actions] test in espalier.toml' >&2; exit 1; }
   TDIR=; for d in tests test __tests__ spec; do [ -d "$d" ] && { TDIR=$d; break; }; done   # the test tree the repository already has, in that order (ls would re-sort the names)
   echo "runner: ${TEST:-none}  test dir: ${TDIR:-none}"; ls "${TDIR:-.}" 2>/dev/null | head -5   # the file pattern of what is there
   ```
   Dispatch the **test-writer** subagent (`subagent_type='test-writer'`). Brief it on:
   - The target file path.
   - The runner (`TEST`) and the test directory and file pattern printed above --
     the directory the fingerprint's command names when it names one
     (`node --test test/`).
   - The project's fixture conventions (what the test tree already uses; on a pytest
     tree, `tmp_path` and subprocess stdin mocking).
   - Function naming (`test_{specific_behavior}` on a pytest tree; what the tree
     uses otherwise).
   - Whether the target needs unit, integration, or contract coverage —
     ask the user if unclear; on a pytest tree the marker selection affects
     which `-m "..."` slice picks up the new test.

   The agent runs in its own context and emits a test file matching the
   project style exactly. Its output is the test content; this command
   writes it to disk.

3. Write the test file at the path the agent suggested, under the test
   directory step 2 found.

4. Run the new file: set `FILE` to it, and `SEP=1` when the runner is a
   `package.json` script (the file goes after `--`); a declared action of more
   than one command runs whole:
   ```bash
   PY=; for c in 'python3' python 'py -3'; do $c -c 'import sys, espalier; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && { PY=$c; break; }; done; [ -n "$PY" ] || { echo 'no Python 3.10+ with espalier answered to python3, python or py -3' >&2; exit 1; }
   TEST=$($PY -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); from espalier.harness_config import preflight_command; print(preflight_command('test'))") || exit 1
   [ -n "$TEST" ] || { { [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; } && command -v pytest >/dev/null 2>&1 && TEST='pytest -q' && echo 'test gate: pytest -q (the PATH fallback: nothing declared or detected)' >&2; }
   [ -n "$TEST" ] || { echo 'NO TEST GATE RAN - declare [extra_actions] test in espalier.toml' >&2; exit 1; }
   case "$TEST" in *" && "*) echo 'the declared test action is more than one command: running it whole, the targeted form does not apply' >&2; eval "$TEST" || exit 1; exit 0;; esac
   eval "$TEST ${SEP:+-- }${FILE:?set FILE to the new test file, and SEP=1 for a package.json script}" || exit 1
   ```

5. Report results. If any test fails, decide with the user whether to
   fix the production code or refine the test — the agent's output is a
   draft, not a guarantee.
