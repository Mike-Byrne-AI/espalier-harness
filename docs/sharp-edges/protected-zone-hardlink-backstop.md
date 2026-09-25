# Protected-Zone Hardlink Backstop (Class-A4)

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Protected-Zone Hardlink Backstop (Class-A4)"

**What it is:** a hardlink is the inode sister of the symlink blind spot
([Class-A3](protected-zone-symlink-backstop.md)). A hardlink aliases one inode
under a second directory entry, so

```
ln tools/cc/hooks/write_guard.py wg_alias   # wg_alias and write_guard.py share an inode
echo evil > wg_alias                          # rewrites write_guard.py's BYTES
```

rewrites the protected file while the write lands on an **unprotected path
string**. Unlike a symlink, a hardlink has no target to follow, so
`Path.resolve()` (which the whole path-string protected-zone check relies on)
sees only the unprotected linkname — `_is_protected("wg_alias")` is False and the
write is allowed. Verified live: `ln -li` confirmed the two
names share the inode, and a redirect through the alias rewrote the protected
bytes with no deny. The dangerous positional is the **SOURCE** (the protected
file aliased OUT), the *inverse* of the symlink linkname capture — so the
existing `_LN_S_RE` symlink check does not cover it.

**The fix — two layers, the write-through being decisive:**

1. **Part B (decisive, channel-agnostic): an inode-aware write-through deny.**
   `_protected_zones.aliases_protected_inode(rel, root)` — if a write target
   EXISTS, is a regular file, and has `st_nlink >= 2` (so it CAN be an alias),
   and its `(st_dev, st_ino)` is in the protected-not-allowed inode set, the
   write is denied. Wired into **every** write channel: `check_write_edit`
   (Write/Edit/NotebookEdit), `check_bash_for_protected_mutations` (every extracted
   Bash candidate), `check_powershell_for_protected_mutations`, and `check_mcp`
   **canonical fields** (`MCP_PATH_FIELDS`). This catches the write-through
   regardless of HOW the alias was created (Bash `ln`, `cp -l`, an MCP hardlink
   verb, or a pre-existing alias). The protected-inode set
   (`_protected_not_allowed_inodes`) reuses the EXACT `_is_protected and not
   _is_allowed` predicate the string check uses — keyed on inode instead of
   spelling — so the allow/deny semantics are identical, just spelling-agnostic.

2. **Part A (early friction, Bash creation): deny `ln`/`cp -l` of a protected
   source.** `check_bash_for_protected_hardlinks` + the
   `_bash_patterns.iter_hardlink_operands` tokenizer (flag-order-independent,
   ReDoS-free — the same shape as `rm_recursive_force_operands`): `ln` is a
   hardlink UNLESS it carries a symlink flag (`-s` cluster / `--symbolic`); `cp`
   is a hardlink ONLY with a link flag (`-l` cluster / `--link`) and no symlink
   flag. **Allowlist-AWARE** (unlike the A3 symlink check, which is allowlist-
   blind): aliasing an allowlist-writable file (`cc/blueprints/x.json`) confers
   nothing — the threat is aliasing a protected-NOT-allowed file. The check denies
   when ANY positional is protected-not-allowed.

**Performance:** the inode check fast-paths on `st_nlink < 2` (the overwhelming
common case — new files, single-named files), so the hot path is a single
`stat`. The protected-inode-set walk runs ONLY for a surviving `nlink >= 2`
candidate, prunes the allowlist-writable `cc/blueprints/` bulk, and stats
`PROTECTED_FILES` first (never budget-dropped).

**How you hit it:** any write whose path string is unprotected but whose inode is
a protected file's — i.e. a hardlink alias. Earn-the-red: every shape below was
ALLOW on the pre-fix HEAD and DENY after.

**How to avoid breaking it:**
- Any NEW write channel MUST run `aliases_protected_inode` on its resolved write
  target alongside the `_is_protected`/`_is_allowed` string check — the inode
  backstop is per-channel, not central.
- Run the inode check **UNCONDITIONALLY** on a canonical path field — do NOT gate
  it on `not symlink_verb`. Gating it lets
  a write-semantics MCP tool whose name merely CONTAINS a symlink substring
  (`write_symlink_data`, `update_symlink_target`) be classed `symlink_verb=True`
  and skip the backstop, rewriting protected bytes via its `path` field. A true
  symlink-CREATE at an existing `nlink>=2` file would `EEXIST` anyway, so the
  check is harmless there; suppressing it on a misclassified writer was the live
  gap. Now closed: `check_mcp` runs the inode check on every canonical field.
- Keep the `st_nlink >= 2` + regular-file + `getattr(st, "st_ino", 0)` POSIX
  guards — `st_ino` is unreliable on Windows, so the backstop is a no-op there
  (the Bash creation-deny + CI still apply).
- Regression: `tests/test_write_guard.py::TestClassA4HardlinkBackstop`.

**Known limits — residuals the inode backstop does NOT close** (the Part-B
write-through is the decisive defense for the channels it covers; these are
documented gaps, and a *committed* governed-file change is still caught by
`ci_guard` / `harness-guard.yml`):

1. **MCP leaf-walk inode residual.** The inode check is applied to the bounded
   `check_mcp` **canonical** fields ONLY, NOT the unbounded Class-A2 leaf-walk —
   a per-leaf `stat()` over a deeply nested / very wide payload would re-introduce
   the slow-hook fail-open the A2 fix exists to prevent. So a hardlink alias
   buried in a NESTED non-canonical MCP key (`{files:[{path: alias}]}`,
   `output_path: alias`) reaches the filesystem without an inode check. The
   string-target version of this is the documented A2 leaf-walk residual; the
   inode version is its sibling. CI-backstopped.
2. **Walk-budget exhaustion (fail-CLOSED).** `_protected_not_allowed_inodes` caps
   the prefix walk at `_INODE_WALK_BUDGET` (5000) nodes. On exhaustion it returns
   `complete=False` and `aliases_protected_inode` FAILS CLOSED (denies the
   `nlink>=2` candidate) rather than waving it through. This is **not session-
   reachable**: inflating the count past the budget requires planting thousands
   of files under a protected prefix, which write_guard itself denies; the real
   harness tree is in the low hundreds of files (`cc/blueprints/` is pruned), and
   `PROTECTED_FILES` are statted first and never dropped. The fail-closed
   direction is deliberate — a fail-open-on-exhaustion would be a
   wrong-direction latent weakening.
3. **Pre-existing alias created outside the session.** A hardlink planted before
   the harness/session started (or via a channel Part A does not model) is not
   denied at creation — but its write-through IS caught by Part B on the four
   covered channels. Consistent with "Local Hooks Are Not a Sandbox": CI /
   branch protection is the real enforcement.
4. **Windows `st_ino`.** POSIX-only; on Windows the `getattr` guard makes the
   inode backstop a no-op (the Bash creation-deny + CI cover that platform).
**NotebookEdit `notebook_path` channel (was a live gap, now closed both hooks).**
The harness's mutation-path extraction read only
`file_path`, but `NotebookEdit` carries its target as `notebook_path` —
**confirmed against the Claude Code Agent SDK reference** (an external source).
So every NotebookEdit was skipping the
protected-zone string check, the inode backstop (`write_guard`), AND the
plan-required gate (`plan_guard`). Both hooks now read BOTH fields, `file_path`
first (precedence keeps Write/Edit unaffected): `write_guard.check_write_edit`
and `plan_guard`'s Write/Edit/NotebookEdit branch. A literal protected-path
NotebookEdit was the broader pre-existing version of this gap and is closed by
the same change.
