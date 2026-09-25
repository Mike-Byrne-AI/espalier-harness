# minimal-hooks baseline

**What this represents:** A simple hook script (~45 lines of Python) that
checks `tool_input.file_path` against a hardcoded list of protected paths.
No path normalization, no Bash command inspection, no kill-switch detection.

**What it claims to handle:** Direct `Write` / `Edit` calls to any of the
listed protected paths.

**What it does NOT claim to handle:**
- Path traversal (`safe_dir/../tools/cc/hooks/x.py`)
- Bash commands that write to, delete or move protected paths via redirect, tee, cp/mv, rm, etc.
- Settings.json modifications that disable hooks (kill-switch class)
- Any of the bypass classes that motivated Espalier-Harness's adversarial regression
  suite

**Expected results:** Catches the obvious direct cases. Misses everything
else.

**Why it's in the benchmark:** Distinguishes "wrote a hook" from "wrote a
hook with adversarial coverage." The delta between this and the espalier
baseline is the value of the regression suite, made visible.
