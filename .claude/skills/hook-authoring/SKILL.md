---
name: hook-authoring
description: Hook script authoring conventions for tools/cc/hooks/. Use when writing or extending a hook, adding a bash extraction pattern to write_guard, modifying _normalize_path or path-handling helpers, reasoning about hook event ordering, or when the user mentions hook authoring, hook contract, hook regression, or path traversal in the harness. Codifies the contract every hook script must satisfy.
---

# Hook Authoring

Patterns for writing and extending hook scripts in `tools/cc/hooks/`.
Every hook script in this repo runs **standalone** — zero `espalier/`
imports — because hooks ship into target repos as copied files, not as
package imports.

## Hook event types

| Event              | When it fires                                       | Stdin shape                                             |
| ------------------ | --------------------------------------------------- | ------------------------------------------------------- |
| `SessionStart`     | New session opens (or `/clear`)                     | `{"source": "startup", "cwd": "/abs/dir"}` (`source` is startup, resume, clear or compact; `cwd` follows Claude into a worktree while `CLAUDE_PROJECT_DIR` stays at the project root, per Claude Code's worktrees page, which espalier pins as the `cc-worktrees` external pin) |
| `UserPromptSubmit` | User sends a prompt                                 | `{"prompt": "..."}`                                     |
| `PreToolUse`       | Before any tool executes                            | `{"tool_name": "...", "tool_input": {...}}`             |
| `PostToolUse`      | After any tool returns                              | `{"tool_name": "...", "tool_input": {...}, "tool_response": {...}}` |
| `Stop`             | Claude finishes its turn                            | `{}`                                                    |
| `PostCompact`      | After conversation compaction                       | `{}`                                                    |
| `ConfigChange`       | A settings file is about to change    | `{"source": "...", "file_path": "..."}` (config_guard reads `source`/`settings_source` + `file_path`) |
| `PostToolUseFailure` | After a tool call fails               | `{"tool_name": "...", "tool_response": {...}}` (or `"error"`) |
| `SubagentStart`      | A subagent is spawned                 | `{}` (reporter — consumes stdin, reads no field) |
| `SubagentStop`       | A subagent finishes                   | `{"agent_type": "...", "stop_hook_active": <bool>}` |

The twelve hooks in this repo wire as: `session_start.py` (SessionStart),
`task_router.py` (UserPromptSubmit), `plan_guard.py` (PreToolUse, matcher
`"Write|Edit|NotebookEdit"`) + `write_guard.py` (PreToolUse, matcher `"*"`),
`config_guard.py` (ConfigChange), `post_write_check.py` (PostToolUse, matcher
`"Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*"`) + `reflect_trigger.py`
(PostToolUse, matcher `"*"`), `stop_gate.py` (Stop), `subagent_stop.py`
(SubagentStop), `post_compact.py` (PostCompact), `subagent_start.py`
(SubagentStart), `context_reinject_failure.py` (PostToolUseFailure, matcher
`"Write|Edit|NotebookEdit"`).

`stop_gate.py` runs lightweight session hygiene by default. Set
`ESPALIER_STOP_GATE=full` to run the core pytest gate on Stop.

## Exit code contract

Exit codes are **channel-XOR**: each code pairs with exactly one output
channel — exit 0 with JSON on stdout, or exit 2 with plain text on stderr,
never both at once.

| Code | Meaning                                                              |
| ---- | -------------------------------------------------------------------- |
| `0`  | Allow, OR a structured permission/decision emitted as JSON on **stdout**. A plain allow writes nothing. |
| `2`  | Simple block — write a plain message to **stderr** (NOT stdout, NO JSON); the user sees it inline. |
| `1`  | Script error — treated as allow with warning. **Never use 1 deliberately.** Means a bug in the hook. |

There are two ways to deny, by channel:

- **Simple block** — exit `2` with a plain stderr message; nothing on stdout.
- **Structured permission/decision** — exit `0` and write a JSON object to
  stdout (e.g. a PreToolUse `permissionDecision` or a Stop `decision`).

Mixing the two — exit `2` *and* stdout JSON — is the common mistake: Claude
Code ignores stdout when the exit code is `2`. Exit `1` is reserved for
genuine script failures and is invisible to the user as a deny signal.

## JSON stdin / stdout

Hooks read JSON from stdin and may write JSON to stdout. Schemas:

- `tool_input` shape varies per tool. `Write`/`Edit` carry
  `file_path` (string) and `content`/`new_string`. `Bash` carries
  `command` (string).
- For PreToolUse blocks, write to stderr with a clear message and exit
  `2`. The user sees the stderr text inline.

## The path-traversal contract

Any hook that maps a string path to a filesystem location **must**
canonicalize before checking against protected/exempt prefixes:

```python
def _normalize_path(file_path: str, root: Path) -> str:
    p = file_path.replace("\\", "/")
    candidate = Path(p)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    return str(candidate.relative_to(root)).replace("\\", "/")
```

Without `(root / p).resolve().relative_to(root)`,
`safe_dir/../tools/cc/hooks/write_guard.py` does *not* start with
`tools/cc/` and slips past the guard while still landing at the
protected file on disk. Regression coverage (Espalier source repo) lives in
`tests/test_write_guard.py::TestPathTraversalBlocked` and the
parametrised case in `tests/test_hooks.py::TestPlanGuard`.

And relativise against the checkout that *contains* the resolved path,
not the root alone. A Claude Code session that enters a git worktree
keeps `CLAUDE_PROJECT_DIR` at the project root while every path it edits
sits under the worktree (`cwd` follows Claude; the `cc-worktrees` external
pin), so `relative_to(root)` read a worktree target as the unprotected,
plan-exempt `.claude/worktrees/<name>/tools/cc/x.py` and both blocking
guards covered nothing there. `_hook_utils.resolve_in_checkout` is the
owner: it returns `(base, rel)` over the root and its registered
worktrees, read from git's own registry on disk (never a subprocess), and
`normalize_path`, `normalize_path_str` and `normalize_bash_path` are its
string faces. A site that rejoins `rel` to a directory afterwards -- a
stat, a read-back, a prune -- joins it to `base`, never to `root`.

`_normalize_*` helpers exist in four files as aliases of those owners;
any new variant must follow the same shape.

## Bash + PowerShell extraction patterns

`write_guard.py` extracts target paths from Bash commands, and from
PowerShell commands on the PowerShell tool (a PowerShell payload handed to
the **Bash** tool is not extracted -- DEF-637, the routing question). Every
arm matches on the MASKED scan and reads its operand from the RAW command
at the match's offsets (`raw_operand` / `raw_span`, DEF-794): the masker
blanks a quoted span's parens and a bare capture stops at a blank, so an
operand read off the scan is a path that exists nowhere; a source census in
the guard's own test suite (`TestQuotedTargetSurvivesTheRoot`, Espalier
source repo -- not deployed by `init`) refuses the next `m.group()` operand
read. The friction-layer scope:

**Caught (literal forms):**
- Redirects: `> path`, `>> path`, `>| path` (the clobber operator), with
  `--append`, `-i`, `-p`
- `tee path`, `tee --append path`, multi-arg `tee log .claude/settings.json`
- `cp src dst/`, `mv src dst/` (computes landed path
  `dst/basename(src)` for directory destinations)
- The operand a verb REMOVES or RELOCATES, on both shells and through an
  interpreter literal (§C52): a protected zone refuses the mutations the
  guard can read, not only a write -- a delete of it, a move of it out of
  the zone, a rename within it, a `find` that removes under it, a `git
  clean` that takes it, and a delete or a move of a directory that ENCLOSES
  a protected path. The allowlist holds for a delete as for a write. The
  reader is a sibling of the write extractor
  (`iter_removed_or_relocated_operands` and its PowerShell twin); its verb
  rosters and its declared limits are ONE table, driven by name, in the
  guard's test class `TestRemovedOrRelocatedOperandIsAMutation` (Espalier
  source repo -- not deployed by `init`), and the arm tuples it consumes are
  pinned to the readers by an AST walk there -- that class, not a list here,
  is the oracle. An UN-NARROWED `find` with a delete action is read one
  tier up as well (DEF-815): from a catastrophic root -- the repo or a
  parent of it, your home, the filesystem root, a shallow system path --
  it is the same hard stop the recursive force-delete draws, ahead of the
  maintenance gate; from any other root it is the CP-RMRF nudge, and a
  roster-ephemeral root (`find build -delete`) passes. NARROWED means a
  `-name`/`-path`/`-regex` predicate (or `-samefile`, `-inum`, `-empty`)
  in force BEFORE the action: find evaluates left to right, so a predicate
  after the action steers nothing, a negated one (`! -name`) selects nearly
  everything, and an `-o` whose right operand is not a name predicate
  re-widens; `-type` and the attribute tests (`-size`, `-perm`, `-mtime`,
  `-user`, `-links`) never narrow (each was a one-token exit from the wall
  in the first cut). On the PowerShell tool the same arm reads the same
  span (DEF-824): pwsh's alias table is per platform, and on macOS and
  Linux `find`, `rm` and `rmdir` are the native binaries, so `find .
  -delete` there is the real sweep. Its siblings on that tool (DEF-822):
  an enumerator piped into a remove verb (`Get-ChildItem -Recurse |
  Remove-Item -Recurse -Force`, by any alias or unambiguous switch
  prefix) is judged by ITS root -- the current location when it names
  none, across a line break after the pipe -- as a wipe when the remove
  verb recurses or the enumeration is files-only (`-File`, `-Attributes
  !Directory`; a recursive enumeration into a plain remove deletes
  everything up to the first directory with children, driven, and earns
  the nudge), and `-Include`, `-Filter`, a positional filter or a wildcard
  root narrows it only by a VALUE that excludes something: **a narrowing
  predicate lands with its degenerate-value twin** (`-Include *`, `-name
  '*'`, `gci *`) pinned as a must-deny row, because the first cut read
  presence and its own deny text taught the catch-all; the recursive .NET
  directory delete is the third spelling of the same wipe, judged from the
  process directory; the head reads a bare verb, a quoted verb, an
  executable path or a wrapper word behind the call operator, and the
  call operator on a command object (`& (Get-Command find)`, `& $f`) is a
  declared gap (DEF-827) the rehearsal carries; the recurse and force
  switches are read by every spelling that runs (`_PS_RECURSE_SWITCH`,
  `_PS_FORCE_SWITCH`: the cmdlet prefixes, the long forms, the `/bin/rm`
  clusters with bash's own rule that an `i` after the last `f` cancels
  force). A variable in a sweep's root is the wall on that tool, as the
  Remove-Item tier's rule has it. The oracles are the PowerShell guard
  rehearsal and the pwsh-gated reachability differential (Espalier source
  repo -- not deployed by `init`), whose sweep rows must reach on the
  platform they are listed for. The carrier (DEF-826): on BOTH tools an
  enumerator -- a `find` with no action, or `ls` -- piped through `xargs`
  into the remove verb is the same wipe with its operands arriving on
  stdin, and the Bash tool had no pipeline arm at all; now `_PIPED_REMOVE_RE`
  reads it as the PowerShell arm reads `gci | ri` -- the enumerator's roots
  are the operands (`_bash_pipeline_roots`, shared by the PowerShell arm for
  a `find` head), a files-only walk, a recursing remove or, on Bash, any walk
  into the native `rm` is the wipe, the hard tier walls wipes from a
  catastrophic root (`has_catastrophic_piped_remove`, under
  `has_catastrophic_bash_sweep` beside the find arm) and the soft tier
  nudges every un-narrowed sweep (`iter_unnarrowed_bash_sweep_roots`); a
  pipeline spans the chain's statements, so each sweep is PLACED by the
  offset of its enumerator, never judged from a per-statement slice. The
  carrier's switch run is one arm per token (a valued switch spelled alone
  takes the next token, every other token none), the head group keeps the
  one-word roster behind one assignment guard (the scrape wants the verb
  right before its guard), and a stage between the enumerator and `xargs`
  and a single path echoed into it are declared limits. The loop carrier
  -- the enumerator's output bound to a loop variable and removed in the
  body -- is read by its own openers (DEF-830): three composed on the same
  head group, and a fourth (DEF-837) for a for loop over a bare word list,
  which has no enumerator -- its roots are the list's words, cut by the
  word regex that parsed them (on the scan span, read raw) and judged one
  per word by the rm tier's own rule, its wipe the family's one rule
  (`_sweep_is_wipe`), and it reaches the soft tier's sweep pass only as a
  wipe; the four openers and the shape each reads are ONE table
  (`_LOOP_OPENERS`), derived-pinned -- all placed through the carrier's
  own placement helper; a
  compound statement crosses lines by grammar, so those openers sit in the
  newline census's compound roster, whose promise is checked on every
  named group. The version-control listing (DEF-831) is the third head on both
  tools -- a two-word SPELLING composed on the git head's one home
  (`_GIT_SUBCOMMAND_AT`, so that block sits before the carrier), not a
  roster word. The heads are ONE table (`_PIPED_ENUM_HEAD_SPELLINGS`, key
  and spelling): both openers' head groups, the keys, the readers table
  (`_PIPED_ENUM_HEAD_READERS`, checked against the keys at import -- a
  head with no reader refuses at load, never falls to another head's
  grammar) and the roster test derive from it; each multi-word spelling
  sits behind a guard of its own, and every head text keys through
  `_enum_head_key`. Each opener carries a `head` group and both readers
  take it from the RAW text at its offsets as they take the spans, never
  from the masked match text (a `-C` value carries the root, and the row
  probe's paren shape drove the masked read to a nudge); every consumer of
  an opener reads the head through the dispatching reader, never the
  cmdlet grammar over whatever span the head selected. A hand-written span
  loop drops redirections as `_operands` does (a silenced stderr displaced
  the listing's root, and the clean reader had the same hole). The
  listing's population follows the sibling reader in the module: the
  tracked and ignored forms are the wipe, the untracked-only form with the
  standard excludes is `git clean`'s untracked form (the nudge) -- and
  only when no tracked-family selector rides beside it (selectors are
  additive; the cached-plus-others idiom is wider than the bare listing).
  A pattern that gains the word `git` enrols in the git-mentioning gate; a
  search-only classifier over a match's text was retired for the `head`
  group rather than declared on two census axes
- `git restore [opts] path`, `git checkout path`, `git checkout ref -- path`
  -- the `--` separator bare or quoted in either kind (DEF-814: `git
  checkout "--" <hook>` hands git a bare `--` after quote-removal), a global
  option between `git` and the subcommand (`git -C <dir> checkout`, `git
  --no-pager restore`; `_GIT_PREOPT_RUN`, one home for every git arm and the
  discard bump), `restore -s <ref>`, the three arms on the PowerShell tool
  too (until DEF-814's lane that leg had none)
- `chmod`/`chown`/`chgrp`/`chflags`/`chattr` on a protected path (every
  positional after the mode/owner/flags token; `--reference=` and macOS
  `chmod -E`/`-N`/`-I` make every positional a target) and `setfacl` (every
  positional -- its ACL spec rides on a flag and `-b`/`-k` carry none) — a
  permission, flag, attribute or ACL change is the quietest way to silence a
  hook; `chflags uchg` is the macOS-native spelling
- PowerShell `Copy-Item`/`Move-Item` (and `cpi`/`copy`/`cp`/`mi`/`move`/`mv`)
  by `-Destination` or the positional `src dst` pair; a directory destination
  lands `dst/basename(src)`
- PowerShell permission verbs, the Windows twins of the `chmod` line above:
  `icacls`/`cacls` on a protected path under any switch not on the read list
  (`/save`, `/verify`, `/findsid`, `/T`, `/C`, `/L`, `/Q`; the file `/save`
  names is a write), `takeown /f`, `attrib` with a `+X`/`-X` attribute token
  in either order around the path, and `Set-Acl` / `Set-ItemProperty` (alias
  `sp`) by `-Path` (any unambiguous prefix, `:` binding) or the positional --
  every non-switch operand is a candidate. A bare `icacls PATH` / `attrib
  PATH` displays and is a read. Switches and attributes are read after
  unquoting, and a quoted argument list holding whitespace is split as well,
  so `attrib "+R" <hook>` and `Start-Process icacls -ArgumentList "<hook>
  /deny ..." -Verb RunAs` (the elevation idiom) are caught
- A PowerShell re-parsing wrapper's switch run carries ONE bare value per
  switch (`_PS_SWITCH_RUN`, composed into the exec-quote arm AND the
  lookbehind that keeps a literal span live), so `Start-Process powershell
  -Verb RunAs -ArgumentList "..."`, `powershell -ExecutionPolicy Bypass
  -Command "..."` and `-WindowStyle Hidden` before the payload open the
  command position. Declared limits, pinned: a value that is a QUOTED string
  (`-Verb "RunAs"`), an `=`-bound value (`-ArgumentList="..."`) and the array
  spelling (`-ArgumentList "-Command","..."`) end the run before the payload,
  which then stays inert
- PowerShell backtick line-continuation (`` ` `` before a newline) is joined
  after masking at every PowerShell entry point (write leg, symlink leg,
  hard-deny tier, speed bump), so a path split across lines is read whole
- Bash operand spans stop at a newline: every command-position-anchored span
  regex joins its operands with `[ \t]`, never `\s`, and a bounded span class
  carries `\n` (`[^|;&\n]`), so `cp x <hook>` + newline + `echo done` denies
  (the second line used to displace the destination) and `tee log` + newline
  + a line naming a hook is not an operand. A backslash-newline IS a
  continuation and is spliced first, by the one shared splicer, at every
  entry point (write extractor, symlink leg, hardlink iterator, hard-deny
  tier, secret-read leg, speed bump -- the order rule is in the splicer's
  docstring); a CRLF after the backslash is two statements. A source-level
  census in the pattern-roster tests refuses the next `\s` joiner, with a
  negative twin of nine evasions it must name
- A `#` that starts a word outside quotes opens a comment and ends every bash
  argument span (last-positional and permission verbs, `tee`, `ln`/`cp -s`,
  hardlinks), so a comment that names a protected path never becomes a
  target; a `#` inside a word (`file#1`, `b$(x)#y`) is operand text
- `patch`: every positional plus a glued `--output=`/`--directory=` value is a
  candidate (its originalfile is the FIRST positional; the patchfile is last)
- A trailing token after the target -- a flag, a redirection, a comment, the
  `)` of a subshell -- does not shift a last-positional pick (`install x
  <hook> 2>/dev/null`, `ln -s t <link> -v`, `( install x <hook> )`): the
  operand span is tokenised, never regex-captured to its last token; a
  redirect whose operator carries `&` BEFORE the target (`install x 2>&1
  <hook>`, `&> /dev/null`, `>& out`) is neutralised first, since `&` ends
  every span; `>&<hook>` itself is read as the redirect write it is; and `--`
  ends option parsing, so `cp -- -weird <hook>` keeps its dash-leading source
- `cp`/`mv`: the destination is the LAST positional and every earlier one a
  source (`cp a b <hooks>/` lands both; `cp -S .bak src <target>` lands
  `<target>`)
- Interpreter inline writes: `python -c "..."`, `node -e "..."`,
  `ruby -e "..."`, `perl -e "..."`, `pypy -c "..."` -- and the same
  interpreters fed their PROGRAM on stdin: a heredoc (`python3 - <<'PY' ...
  PY`, `python3 <<EOF`, `node - <<'JS'`, `ruby <<'RB'`, `perl <<'PL'`) or a
  here-string (`python3 - <<< "..."`). The opener is `_CMD_POS`-anchored and
  matched on the MASKED string, so the same line inside a quoted-delimiter
  documentation heredoc or behind a `#` is a mention; the body is sliced from
  the raw command by offset and read with the interpreter's literal-write
  patterns (`open(<lit>,'w')`, `Path(<lit>).write_text`, `shutil.copy(_,
  <lit>)`, `os.replace(_, <lit>)`, the node/ruby/perl siblings -- perl in
  both the two-argument `open(F, '>path')` and the three-argument `open(my
  $fh, '>', 'path')` spelling, DEF-813, the read twins `'<'` alike). Filed as
  out of scope beside the two-step class until 2026-09-06; now an in-scope
  corpus row.
- A program operand is ONE bash WORD, not one quoted span (DEF-832): bash
  concatenates adjacent segments -- single-quoted, ANSI-C, double-quoted,
  bare -- with each segment's quote removal into the one argument the
  program receives, so a path quoted inside a single-quoted program (spelled
  by ending the outer quote, spliced or naively) reached the interpreter, the
  POSIX shell and the PowerShell command operand as a bare path while every
  opener took the first quoted span and every tier saw nothing (driven at the
  hook and on a throwaway). The word grammar is one home
  (`_BASH_QUOTED_WORD`: a quoted segment first, bare runs never adjacent,
  each quote arm self-delimited, the run UNBOUNDED -- a bound was a
  fail-open cliff past which a truncated word was read, and the disjoint
  arms keep the run linear; the bare arm's stop set is the reader's, never
  the whitespace class) composed into the four inline openers, the POSIX
  `-c` opener and the `-Command` opener as a `word` group; the quote
  removal is the existing bash-word reader (`_read_shell_word`, the
  here-string arm's, which gained the locale-quoted arm the grammar admits)
  through `_bash_word_text`, and `raw_operand` reads a quoted capture to the
  end of its word the same way -- OPT-IN at the Bash write leg's call
  sites, never by default: the reader serves the PowerShell leg too, where
  a comma joins a path list and a backslash is a separator, and the bash
  word grammar there lost a listed protected file (both reviews, driven).
  A change to a helper both legs read earns the whole guard test file plus
  the PowerShell-leg files, never a class selection. Two derived pins: every
  program-operand opener carries the `word` group under its declared flag
  regime, and the grammar's stop set equals the reader's.
  Every consumer of an opener reads the word group, never a kind group or a
  numbered one -- a second reader of the same openers (the mask's
  reader-program bodies) kept the old numbered groups and every inline
  program raised inside it, which degraded the mask to raw text and refused
  mentions on the hard tier. The newline census blanks the word as the body
  before its two questions. A POSIX `-c` word's text also joins the write
  leg's nested programs: the raw scan reads a single-span program already,
  a spliced one only as its concatenation. The PowerShell tool's own inline
  openers are a different word grammar and stay as they are.
- The same on the PowerShell tool (DEF-712): four `_PS_CMD_POS`-anchored
  inline openers (`python -c`, `node -e`, `ruby -e`, `perl -e`, the `py`
  launcher) and one piped-stdin opener (`| <interpreter> [switches] [-]` at
  the end of a statement -- PowerShell has no heredoc), the head given as a
  bare or `&`-called quoted executable path (`_PS_EXE_PREFIX`, shared with
  the permission verbs), the switch run before `-c` the DEF-717 constant --
  one bare value per switch, and the Bash openers carry the same run
  (`python3 -W ignore -c` denies on both shells). The opener is matched on
  the scan text and the body sliced from a same-length RAW twin
  (`powershell_scan_pair`) with PowerShell's escapes undone, then dispatched
  through the SAME inner write tables; a piped PowerShell program (`| pwsh
  -Command -`) is re-scanned by the extractor, the program being the LAST
  here-string or quoted literal of the stage before the pipe. The pipe
  bounds each opener's segment, and the segment boundaries are found in one
  pass: a flood of openers must stay linear through the whole extractor,
  which is what the hook runs (the ReDoS suite drives that shape).
- Variable-indirect: `VAR=path; ... > $VAR` (a binding of any name case,
  bare or behind a declaration builtin, bound at any statement start --
  DEF-847, 2026-09-19; literal values only, no `$(...)` or
  `${VAR:-default}`) — handled by `_expand_simple_var_assignments`; and
  its PowerShell twin `_expand_simple_ps_var_assignments` (DEF-801,
  2026-09-15: `$p = '<hook>'; Set-Content -Path $p`, the .NET spelling,
  `"$d/x.py"` interpolation), run on the RAW command
  before the scan pair so every offset read downstream survives. Both are
  sequential — each reference takes the most recent binding before it, a
  later computed assignment unbinds the name — and both stand down rather
  than expand a value referenced past the scan cap

**Documented out-of-scope:**
- Two-step subprocess (write to /tmp, then `cp /tmp/x dest`)
- On the PowerShell tool: an UNBOUND variable holding the program (`$code |
  python -`, `python -c $code`; a same-line literal binding is inlined
  first since DEF-801), a program read from a file (`Get-Content x.py |
  python -`), `Start-Process python -ArgumentList "-c ..."` (the `-c` sits
  inside the argument list, no opener shape), and a quoted executable
  behind an EXPANDABLE wrapper span (`powershell -Command "& 'C:\...\
  python.exe' -c ..."`: the masker blanks the call operator inside it;
  the single-quoted wrapper twin denies), a here-string as the `-c`
  argument (`python -c @'...'@`), and a QUOTED switch value before `-c`
  (`-W "ignore" -c`, the run's own limit). A module operand (`python -m x`)
  is read as a stdin consumer -- the over-capture direction -- while a
  `-File <script>` on a shell head names the program and the pipe is data
- Inside an interpreter program (`-c`, `-e`, or stdin): a computed path
  (variable, f-string, `argv`), a valued flag before the `-` operand (`python3
  -W ignore - <<EOF`), and a body that is DATA to a script or module operand
  (`python3 script.py <<EOF`, `python3 -m json.tool <<EOF`) -- there the body
  is not the interpreter's program
- Command substitution: `> $(cat path.txt)`
- Multi-line variable forms (heredoc-assigned, function-set)
- Lowercase or mixed-case variable names on Bash (a PowerShell name binds
  in any case, as the shell reads it)
- PowerShell copy/move with a value-taking switch before or between the
  positional pair (`Copy-Item -Filter *.py src dst`, `Copy-Item src -Filter *.py
  dst`): the filter value reads as an operand and the pair misses; the
  `-Destination` spelling (any unambiguous prefix, `:` binding, quoted operand)
  is the covered one. The bash twin no longer misses: `cp`/`mv` read the LAST
  positional as the destination, so `cp -S .bak src dst` lands on `dst`;
  `cp -t dir src` (glued `-tdir`, a cluster `-vt dir`, any GNU abbreviation
  of `--target-directory` `=` or space bound, quoted or bare) is read off the
  tokenizer's option view -- one reader, no regex beside it -- its positionals
  are sources landing under `dir` (`cp -t .claude/ settings.json` names the
  protected file), so backing a hook up (`cp -t backups/ <hook>`, `install
  -t`) is a read; a file named `-t` after `--` is a source, not the flag
- The remove/relocate class's declared limits (§C52), each pinned by an
  allow row in `TestRemovedOrRelocatedOperandIsAMutation`: an operand that
  arrives on stdin (`echo <hook> | xargs rm`), a `find -exec` whose action is
  not a remove verb, an UNBOUND variable holding the operand (`Remove-Item
  $p`; a same-line literal binding is inlined first on both shells since
  DEF-801 closed on 2026-09-15, so `$p = '<hook>'; Remove-Item $p` denies),
  and a directory operand
  that merely CONTAINS a secret (`tar -cf backup.tar .`). The recursive
  spelling on a zone directory, forced or not since DEF-842, is bumped first by `_speedbump` (CP-RMRF:
  deny-once, ahead of the maintenance gate, keyed on the SPELLING and not on
  the operand -- the same bump fires on an unprotected directory, so it is
  not zone coverage) and its re-issue reaches the zone check; a plain delete
  and every move never bump and are the zone check's alone. Until
  2026-09-14 this bullet said a delete was governed by `_speedbump`; driven,
  no bump fired on any plain delete or move-away shape, and the zone check
  never examined the operand (DEF-795)
- PowerShell permission verbs reached without a cmdlet or a literal path: the
  property-assignment form `(Get-Item <hook>).IsReadOnly = $true` (nothing to
  anchor on), a piped path or one held in an UNBOUND variable (`Get-Item
  <hook> | Set-Acl`, `attrib +R $hook` with no same-line literal binding;
  `$hook = '<hook>'; attrib +R $hook` denies since DEF-801, the pre-pass
  inlining the literal before this arm reads it), an executable given by
  path behind an
  EXPANDABLE wrapper span (`powershell -Command "& 'C:\...\icacls.exe'
  <hook> /deny ..."`: the same masker limit the interpreter arm declares;
  the bare path, the `&`-called quoted path outside a wrapper, and the
  single-quoted wrapper twin are matched), and the Bash tool's Git Bash twin
  of `attrib`/`icacls` -- from a bash prompt one reaches for `chmod`, which
  is matched, and those two heads need a metamorphic no-op row only a
  Windows bash can vouch for

The boundary is the friction layer's contract: catch casual bypass,
not motivated bypass. Motivated bypass is the visibility layer's job
(`_integrity.py`, audit log) and the CI guarantee
(`harness-guard.yml`, `ci_guard.py`).

## Test pattern

Every closed bypass class has a regression test parameterized over
canonical forms:

```python
@pytest.mark.parametrize("payload", [
    "echo x > .claude/settings.json",
    "echo x > ./.claude/settings.json",
    "echo x > $CLAUDE_PROJECT_DIR/.claude/settings.json",
    # ... canonical forms
])
def test_blocks_redirect_to_protected(payload, tmp_path):
    result = run_hook("write_guard.py",
        {"tool_name": "Bash", "tool_input": {"command": payload}})
    # Current Claude Code: structured decisions use exit 0 + stdout JSON.
    # Exit 2 is reserved for simple stderr blocking with no JSON.
    assert result.returncode == 0
    out = json.loads(result.stdout)
    decision = out["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny"
```

Every documented out-of-scope case has a **negative** test pinning the
boundary — proving the hook does *not* claim to catch what it can't:

```python
def test_does_not_claim_to_block_two_step_subprocess(tmp_path):
    payload = "echo x > /tmp/y && cp /tmp/y .claude/settings.json"
    # ... assert returncode == 0 (out-of-scope is documented, not enforced)
```

Negative tests prevent silent scope creep — if someone adds detection
for a documented-out case, the negative test fails loudly and the
docs/SHARP_EDGES.md entry must be revised. A class whose rows are keyed by
name pins its limits the same way, as allow rows beside its deny rows
(`TestRemovedOrRelocatedOperandIsAMutation`'s `control` and declared-limit
keys), so the boundary and the coverage are read from one table.

## Subprocess-tested hook contract

Hook tests pipe JSON to stdin via subprocess (not direct function
calls), to exercise the actual entry point:

```python
result = run_hook(script,
    {"tool_name": "Write", "tool_input": {"file_path": "...", "content": "..."}})
assert result.returncode == 0
```

`run_hook` lives in `tests/conftest.py` (Espalier source repo; a fork keeps its own copy). Use it; don't roll your own.

## Stdlib-only constraint

Hook scripts may import from `tools/cc/hooks/_hook_utils.py` and
stdlib only. **No `espalier/` imports**, no third-party packages. This
keeps hooks copy-deployable into target repos.

## Hook ordering inside an event

Within a single event (e.g., two PreToolUse hooks), order is the
order they're declared in `.claude/settings.json`. If `plan_guard`
should run before `write_guard`, it must be listed first. Both run
on every PreToolUse — there's no early-exit chain.

## See also

- `docs/external/cc-hook-protocol.md` — the pinned Claude Code hook-protocol
  excerpt; the designated verification target for the exit-code and channel
  semantics restated above.
- `docs/HOOK_ASSUMPTIONS.md` — the empirically-established protocol assumptions
  (channel-XOR, additionalContext delivery, Stop-on-graceful-exit) that this
  contract rests on. `init` deploys it, so the path resolves in your repo;
  the assumptions it records are also restated above and verifiable against
  `docs/external/cc-hook-protocol.md`,
  which *is* seeded.
