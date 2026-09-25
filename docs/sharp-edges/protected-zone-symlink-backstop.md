# Protected-Zone Symlink Backstop (Class-A3)

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Protected-Zone Symlink Backstop (Class-A3)"

**What it is:** a symlink is the friction layer's blind spot from both directions.
*Reader side:* a hook that READS a governed state file (cc/execution_plan.json,
the cc/ surface docs, .espalier state) following a planted symlink ingests
attacker-controlled content. The freeze-blocker (**N3**): `plan_guard` read
cc/execution_plan.json with `exists()`+`read_text()`, so a symlinked plan whose
target said `status=in_progress` made `_has_active_plan()` True and **opened the
PreToolUse mutation gate** for unplanned source writes. *Writer side:* symlink
*creation* into a governed zone (**R1 M-1**) plants that redirect — and it was
denied only on the Bash `ln` channel; MCP verbs, `cp -s`, and PowerShell
`New-Item SymbolicLink` all fell through the allowlist-aware write check.

**The fix — both directions, fail-closed:**

1. **Reader: `_hook_utils.read_text_nofollow(path, within=root)`** — one
   symlink-refusing reader (consolidates the `statusline`/`_freshness_cache`
   fd-level pattern): `O_NOFOLLOW` (atomic, no TOCTOU) + `O_NONBLOCK` +
   `S_ISREG` + size cap. `O_NOFOLLOW` guards only the FINAL component, so
   `within=root` ALSO refuses a symlinked **ancestor** dir (**N3-EXT**: a
   symlinked `cc/` parent was followed otherwise). `FileNotFoundError`→missing,
   `OSError`→untrusted; the caller fails closed on both (a symlinked plan →
   "malformed" → gate stays CLOSED). Routed through `plan_guard._plan_state_label`
   (N3); `_integrity._load_manifest_unlocked` (orientation-poison) uses an
   equivalent inline `is_symlink` + parent-`is_symlink` refusal rather than the
   shared reader — functionally equivalent (refuses a symlinked manifest AND a
   symlinked `.espalier/` parent).

2. **Writer: a symlink may NEVER land in a governed zone, on ANY channel** —
   allowlist-BLIND (deny if the linkname `_is_protected`, ignoring `_is_allowed`,
   because an allowlisted dir like `cc/blueprints/` legitimately accepts file
   writes but a *symlink* there is the attack). Channels: Bash `ln` (pre-existing)
   + Bash `cp -s`/`--symbolic-link` (`_bash_patterns._CP_SYMLINK_RE`), MCP
   symlink verbs (`write_guard._is_mcp_symlink_verb` + `_mcp_leaf_denied`
   allowlist-blind branch; `unlink`/`hardlink` excluded — hardlink is the
   separate A4 fix), PowerShell `New-Item SymbolicLink`
   (`powershell_symlink_linknames`). `_is_protected` now also matches the BARE
   governed dir name (`cc`, `tools/cc`, `.github/workflows`) so planting the dir
   itself (`ln -s evil cc`) is denied (N3-EXT plant primitive).

3. **169-T channel-XOR (surfaced by the `cp -s` earn-the-red):** `deny()`
   returned a plain `0`, which is FALSY, so `rc = check(...); if rc: return rc`
   never short-circuited — a command matching more than one check (`cp -s` =
   symlink AND write candidate; a plan payload with several gated leaves)
   double-printed a second decision JSON, corrupting it. `deny()` now returns
   `_hook_utils.DENIED`, a truthy int-`0` sentinel: the dispatch short-circuits
   after a deny, exactly ONE JSON is printed, and the exit code stays 0
   (`raise SystemExit(int(main()))`).

**How you hit it:** a write that reads a governed file decides policy on
attacker content via a planted symlink (gate-open); or a symlink-create into a
governed zone through a non-Bash-`ln` channel; or a command matching more than
one check double-prints.

**How to avoid breaking it:**
- Any hook reading a governed/state file MUST use `read_text_nofollow`
  (with `within=root` when the parent dir is itself governed) — never bare
  `read_text()`/`json.loads(path.read_text())`.
- Any new symlink-creation channel MUST get an allowlist-blind linkname check
  (deny on `_is_protected` alone); do NOT route it through the allowlist-aware
  write check.
- `deny()`/`block()` must return a truthy-zero sentinel; never a plain `0`
  (the `if rc:` dispatch idiom depends on it).
- Regression: `tests/test_write_guard.py::TestClassA3SymlinkBackstop`,
  `tests/test_hooks.py::TestPlanGuard` (N3 / N3-EXT / 169-T).

**Known limits — residuals the WRITE-side creation check does NOT close** (the
READER side — N3/N3-EXT and every governed-file reader refusing symlinks — is
the decisive defense and is airtight; these are best-effort defense-in-depth on
the creation channel, and a *committed* governed-file change is still caught by
`ci_guard` / `harness-guard.yml`):
1. **Inline-interpreter symlink** — `python -c "import os; os.symlink(...)"`,
   `node fs.symlinkSync`, `perl symlink`, `ruby File.symlink`. The
   inline-interpreter extraction models `open(f,'w')` writes, not symlink APIs.
   Same documented out-of-scope class as runtime-constructed paths and `$(...)`
   command substitution; the reader-side `O_NOFOLLOW` makes a planted symlink
   inert at read time.
2. **`ln`/`cp` `-t` / `--target-directory=dir` (and glued `cp -st dir src`)** —
   the link LOCATION is the FLAG's argument (before the sources), not the last
   positional, so the last-positional capture misses it. The common spellings
   (`ln -s t link`, `cp -s s d`, multi-source `ln -s a b dir/`, and the `--`
   end-of-options marker) ARE caught. Closing the `-t` family needs a
   tokenizer-based linkname picker (the same flag-parsing discipline
   `has_catastrophic_recursive_rm` uses for `rm`) — deferred as defense-in-depth.
3. **MCP symlink-verb classification is an inherent heuristic** — `check_mcp`
   must know whether an MCP tool *creates a symlink* (→ allowlist-blind) or
   *writes a file* (→ allowlist-aware, because allowlisted zones like
   `cc/blueprints/` legitimately accept file writes). The only signal is the
   verb name, so `_is_mcp_symlink_verb` enumerates symlink terms
   (symlink/symbolic/softlink/junction/reparse/mklink/link/ln). You CANNOT make
   all writes allowlist-blind without breaking legitimate allowlisted writes, so
   the enumeration is forced. An exotic *unknown* symlink verb misclassifies as
   a write → a FILE-symlink can land at an allowlisted file. Bounded: it only
   affects allowlisted paths (protected-non-allowlisted still DENY allowlist-
   aware), the dangerous dir-plant (`cc/blueprints` itself) is denied on every
   channel (`_is_protected` true, `_is_allowed` false), and the reader side
   refuses the planted symlink. The Bash/PowerShell channels do NOT share this
   (they match real command syntax, not server-defined verb strings).
4. **`cognitive_blueprint._load_latest` symlinked-blueprints-dir** — its
   `is_symlink()` guard is final-component-only, so a symlinked `cc/blueprints/`
   *directory* would be followed. Unreachable today (planting that dir-symlink
   is denied on every write channel); a recommended follow-up is to route its
   read through `read_text_nofollow(within=root)` like `plan_guard`.
