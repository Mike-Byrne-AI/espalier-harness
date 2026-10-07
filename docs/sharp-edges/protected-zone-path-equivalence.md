# Protected-Zone Path Spelling-Equivalence (Class-A1)

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Protected-Zone Path Spelling-Equivalence (Class-A1)"

**What it is:** write_guard's friction layer decides "is this write to a
protected harness zone?" by normalising the path to a repo-relative string
and comparing it against `PROTECTED_PREFIXES` / `PROTECTED_FILES` (and the
`ALLOWED_*` allowlist). **Any spelling the OS treats as the same on-disk file
but that differs as a *string* is a bypass.** Convergence review
found five verified-critical spellings, and a follow-up adversarial
pass found two more the first fix missed:

| id | spelling | mechanism |
|----|----------|-----------|
| C1 | `.//tools/cc/hooks/x.py` | one-`./`-strip left a leading slash → read as absolute |
| C-2 | `$CLAUDE_PROJECT_DIR//x` | env-var strip left a residual leading slash |
| C-3 | `.claude/settings.json.` / ` ` | Windows strips trailing dot/space per component |
| C-4 | `${CLAUDE_PROJECT_DIR}\x` | forward-slash-only env-var strip missed the backslash form |
| C-5 | `$env:CLAUDE_PROJECT_DIR/x` / `${env:CLAUDE_PROJECT_DIR}\x` / `$($env:CLAUDE_PROJECT_DIR)/x` | the PowerShell env-var spellings; the strip knew only the two bash forms, so every PowerShell write extractor yielded a path that matched no zone. Its review half: inside a double-quoted span the masker blanked the braces of a `${...}` token and split the path, so the quoted braced form -- and the quoted bash form `"${CLAUDE_PROJECT_DIR}/x"` on the PowerShell tool -- allowed for a second reason (`DEF-716`, 2026-09-07) |
| N1 | `.claude/settings.json::$DATA` | NTFS data-stream suffix names the base file |
| (adv) | `tools/cc::$INDEX_ALLOCATION/x.py` | NTFS *directory* stream is traversable → opens `tools/cc/x.py` |
| (adv) | `> ~/<repo>/.claude/settings.json` | shell expands `~`; the Bash normaliser didn't |

**The chokepoint (two layers).** Fix the *class*, not the spellings:

1. `_hook_utils.normalize_path` / `normalize_bash_path` — `replace("\\","/")`
   at the TOP (separator-agnostic), `lstrip("/")` after each
   `$CLAUDE_PROJECT_DIR` strip and the Bash `./` strip (kills residual leading
   slashes), and `os.path.expanduser` on **both** channels (the Bash channel
   previously lacked it). Output is a faithful repo-relative path — it does
   NOT fold trailing-dot/ADS, because on POSIX `foo.` is a *distinct* file and
   the general normaliser must not corrupt path identity.

2. `_protected_zones._fs_equiv` — folds the Windows trailing-dot/space + NTFS
   ADS spelling-equivalence classes, composed with the existing NFKC+casefold,
   applied to **both** the candidate path AND every set member.

**The asymmetry is load-bearing (`all_components`).** Both directions fail
CLOSED:

- `_is_protected` → `all_components=True`: strip every component, so a
  directory-stream / dotted-directory traversal folds onto the protected
  prefix. Over-PROTECTing an exotic POSIX directory name is a recoverable
  over-block.
- `_is_allowed` → `all_components=False`: strip the **basename only**. A POSIX
  directory literally named `blueprints.` or `blueprints:notes` is a
  *different real directory* from the allowlisted `blueprints/` — folding it
  there would WIDEN the allowlist (fail-OPEN). The basename strip still
  recognises the Windows `execution_plan.json.` / `::$DATA` spelling of a
  legitimately-allowed FILE (this is also what fixes the C-3 over-block).

**How you hit it:** any write spelled with a doubled/back slash, a trailing
dot/space, an NTFS stream (`:`/`::$DATA`/`::$INDEX_ALLOCATION`), a `~`-relative
Bash redirect, or an env-var prefix carrying any of the above resolved to a
protected file but classified ALLOW.

**How to avoid breaking it:**
- Any new `normalize_*` helper in `tools/cc/` must: canonicalise separators
  first, `lstrip("/")` after every prefix strip, `expanduser`, and translate
  the drive spelling through `_hook_utils._msys_drive_to_windows` (the Git
  Bash, extended-length, device and loopback-share forms) before any compare
  against the root — on both sides of that compare.
- Any new protected/allowed comparison must route the path AND the set members
  through `_fs_equiv` with the correct `all_components` flag — never add a raw
  `rel_path in SET` check (it skips the fold; that was the original C-3 hole).
- Regression coverage:
  `tests/test_write_guard.py::TestClassA1PathCanonicalization`,
  `::TestClassA1ChokepointEndToEnd`, `::TestClassA1AdversarialExtensions`.

**Known limits — residuals the string chokepoint does NOT close** (all are
*friction-layer* gaps — a **committed**
write to the real protected file is still caught by `ci_guard` /
`harness-guard.yml`, which read git's forward-slash diff output regardless of
spelling):

1. **A Windows share spelled by anything but the two loopback names** —
   a non-administrative share (`\\localhost\Users\…`), another host's share
   (`\\server\share\…`), and an administrative share reached through the
   machine's own hostname or another loopback address (`\\MYPC\C$\…`,
   `\\127.0.0.2\C$\…`), each also in its extended-length `\\?\UNC\…`
   spelling. Nothing static maps a share name to a local path, so such a
   spelling of a protected file reads out of every zone, and the hostname
   form of a local administrative share does so even though it opens the
   same file as the drive path. Only a checkout that is itself presented as
   that share (both sides of the compare in the share's spelling) relativises.
   The rest of this class closed on 2026-10-07 (`DEF-935`): the
   extended-length and device forms `\\?\C:\…` and `\\.\C:\…`, and the
   loopback administrative shares `\\localhost\C$\…` / `\\127.0.0.1\C$\…`
   in their plain and extended-length (`\\?\UNC\localhost\C$\…`) spellings,
   fold to the drive path in `_hook_utils._windows_prefixes_to_drive`, called from the
   drive-spelling chokepoint (`_msys_drive_to_windows`), so the write
   extractors on every channel, the root side and the recursive-delete tier's
   `_posix` read the drive form with no edit of their own. Measured on a
   Windows host on 2026-09-26 (walk 4): nine of eleven such spellings passed
   every hook and reached the file with no audit record, because
   `ntpath.realpath` keeps a `\\?\` prefix its input carried and the checkout
   compare then saw `//?/C:/…` against `C:/…`. Pinned by
   `tests/test_write_guard.py::TestWindowsPrefixSpellings`: the string fold
   and the FS-free layer under emulation on every host, the `resolve()` layer
   on the portability workflow's Windows cell.
2. **Bash dynamic parameter-expansion** — `${CLAUDE_PROJECT_DIR:-x}`,
   `${CLAUDE_PROJECT_DIR%/}`, `${…##pat}`, `${…/a/b}`. This is the documented
   dynamic-shell-eval out-of-scope class (see "Variable-Indirect Bash
   Expansion"); the literal `$CLAUDE_PROJECT_DIR/` strip catches the two
   bash literal forms and, case-insensitively, PowerShell's `$env:`,
   `${env:}` and `$($env:)` spellings (C-5) -- a variable read through the
   `env:` drive (`(Get-Item env:CLAUDE_PROJECT_DIR).Value`), `Join-Path`, or
   any other computed form is the dynamic class and stays open.
3. **8.3 short names** — `SETTIN~1.JSON`. The long↔short map is live-FS state
   the hook cannot compute statically.
4. **Bare leading-slash absolute** — `/tools/cc/hooks/x.py` falls to the
   raw-string fallback and misses the prefix, but is SAFE today: it names
   filesystem-root (a different file), and `_is_protected` has no leading-slash
   branch. It would only become a bypass if a future change taught
   `_is_protected` to tolerate a leading slash.
