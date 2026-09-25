# Hook authoring

**Status:** active
**Linked from:** tools/cc/hooks/CLAUDE.md ("Read first")

Accumulates lessons from writing and extending hook scripts.

## The exit-code contract (channel-XOR)

Claude Code hooks have TWO mutually exclusive output channels. See
`docs/external/cc-hook-protocol.md` for the pinned external truth.

| Exit code | Meaning                                        |
|-----------|------------------------------------------------|
| 0         | Stdout JSON parsed for decision (allow/deny)   |
| 2         | Stderr text fed back; stdout ignored           |
| 1         | Script error — NOT a governance decision (bug) |

This harness uses **exit 0 + JSON** exclusively for governance
hooks. The block JSON shape is event-specific:

- **PreToolUse** (used by `write_guard.py`, `plan_guard.py`):
  ```json
  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}
  ```
- **Stop / ConfigChange** (used by `stop_gate.py`, `config_guard.py`):
  ```json
  {"decision": "block", "reason": "..."}
  ```

Mixing schemas across events is a real bug class. `tests/test_hook_protocol.py`
enforces correct shape per event.

`ci_guard.py` is the ONLY script in `tools/cc/` that legitimately
exits 1 (in `main()` for infrastructure errors); it runs in GitHub
Actions, not under the Claude Code hook contract.

## The isolation rule

`tools/cc/` scripts have **zero `espalier` imports**. The hook tree
runs in environments where `espalier/` does not exist (e.g.,
post-init adopter repos that pip-installed espalier-harness — the
`tools/cc/` dir is co-installed but the source `espalier/` is not in
the same tree). Any `from espalier ...` or `import espalier` causes
`ModuleNotFoundError` at runtime.

Inter-layer communication uses **subprocess only**. Example: the
autoprune hook calls `espalier memory prune` via
`subprocess.check_call(...)`, not via import. The fallback chain in
`post_write_check.py::_maybe_autoprune_memory` is:

1. `shutil.which("espalier")` — production speed (PATH binary).
2. `sys.executable -m espalier.cli` — fallback for environments where
   the PATH binary resolves to a Python without the espalier module
   (the macOS python-resolver gap documented in SHARP_EDGES).
3. PYTHONPATH self-host bridge — adds `<repo>/espalier` to
   PYTHONPATH when the hook is colocated with the source tree.

## A sibling import is a loader contract, not a dependency

A hook module is imported under two spellings: bare, with the hooks directory
already on the path (`write_guard` and `post_write_check` insert their own
directory), and as `tools.cc.hooks.<module>` from the repo root, where nothing
has. So a module that gains a sibling import must put its own directory on the
path the way `write_guard` does rather than trust every importer to have done
it — `_bash_patterns` shipped the trusting form and broke standalone collection
of the two test files that use the dotted spelling, hidden in the full suite
only by collection order (a file importing `write_guard` is collected ahead of
them, and `write_guard` inserts the directory). Pin it with a fresh-process
import, never an in-suite one. Corollary: a source-mutation harness that execs
a module into a bare module object must give it a file attribute, because an
own-directory insert reads it.

## Maintenance mode — parent-shell launch only

`ESPALIER_MAINTENANCE_MODE=1` bypasses friction-only checks (write_guard
protected-zone scan, plan_guard's plan-required check, stop_gate
docs-refresh + code-review gates, subagent_stop's blueprint append). Must be set in the parent shell
BEFORE launching `claude`:

```bash
ESPALIER_MAINTENANCE_MODE=1 claude --continue
```

**Gotcha**: mid-session inline assignment via a Bash tool call does
NOT propagate to already-running hooks. The hooks were forked with
the parent shell's env at session start; they don't re-read env on
each invocation.

Documented in `docs/SHARP_EDGES.md` under "ESPALIER_MAINTENANCE_MODE
Must Be Set Before Launch" — and the Bash tool's input validator
explicitly denies the inline-set pattern with a recovery message.

## Adopter escape valves — two complementary mechanisms

When you write a hook that adds plan-required or protected-zone friction,
make sure adopters have the right kind of escape:

| Mechanism | Scope | Use case |
|---|---|---|
| `ESPALIER_MAINTENANCE_MODE=1` (env var) | Whole session, all friction checks | Harness self-edit only — operator working on the harness itself |
| `[plan_guard] exempt_prefixes` (`espalier.toml`) | Specific path prefixes, plan_guard only | Adopter customization — e.g., `src/myapp/` carve-out so tiny edits don't trigger plan-required ceremony |

The env var is **harness-self-edit territory**: it bypasses
`write_guard` protected-zone + `plan_guard` plan-required + `stop_gate`
gates 2-3 + `subagent_stop` blueprint append. Adopters reaching for it for "I just want to edit my own
code" is the failure mode TP-97 was filed against — they hit ceremony,
set the bypass in their shell rc, and now the harness's discipline
product silently advisory across the whole session.

The toml knob (TP-97) is **adopter customization territory**: it adds
specific path prefixes to `plan_guard._is_exempt`'s allow-list without
touching `write_guard` or `stop_gate`. Discipline preserved; ergonomics
configurable.

When adding a new plan-gated rule, surface the toml knob in any denial
message the new rule emits (per `_PLAN_EXEMPT_HINT` at
`plan_guard.py::_PLAN_EXEMPT_HINT`). Adopters who hit unfamiliar friction should
land on a customization path, not a bypass path.

## PostToolUse fires on EVERY write

`reflect_trigger.py` and `post_write_check.py` are PostToolUse hooks
matched on `*` (or narrow tool matchers). They run after EVERY tool
call that matches. Design implications:

- **Be idempotent**: the hook can fire many times per session; its
  state changes must not break under repeated invocation.
- **Early-return cheaply**: filter on `rel_path` first (the autoprune
  hook checks `if rel_path != "ESPALIER_MEMORY.md": return` before any work).
- **Use stderr for advisory; stdout structured if blocking**:
  PostToolUse can't deny (the tool already ran), so blocking is moot;
  but the channel-XOR semantics still apply if you're aiming for
  proper protocol shape.
- **No subprocess pytest from inside pytest**: the matrix and
  release_check both hit timeouts when a test runs subprocess pytest
  with `ESPALIER_RELEASE_CHECK_WITH_TESTS=1`; the inner test exceeds
  the outer pytest-timeout (60s).

## Hooks are non-blocking by design (TP-91 rationale)

When the hook is "auto-heal on failure" shape (the autoprune use
case), it should never refuse to do its job because of a safety
default tuned for direct CLI users. TP-91's `--allow-empty` flag is
the canonical example:

- Direct CLI user runs `espalier memory prune` — default refuses to
  empty Session Log table (safety).
- Hook autoprune always passes `--allow-empty` — never refuses to
  fix an over-cap ESPALIER_MEMORY.md, even when the only available row is
  the operator's most recent one.

Apply the same pattern when a new hook calls into espalier CLI: the
hook context wants best-effort cleanup, not principled refusal.

## Path normalization

All path comparisons in hooks use `.replace("\\", "/")`. Windows
paths use backslashes; without normalization, a `.startswith("tools/cc/")`
check silently fails on `tools\cc\hooks\write_guard.py`. Documented in
`docs/CONVENTIONS.md` "Architecture Rules" and enforced by spot-check
via `tests/test_reflect_trigger_path_normalization.py`,
`tests/test_plan_guard.py`, and `tests/test_contracts.py`.

## The integrity manifest

`.espalier/integrity.json` (gitignored, regenerated locally) hashes
specific hook scripts + CI files. The list lives in
`surface_contract._PROTECTED_INTEGRITY_FILES` (~19 entries).

After editing any file in that list, refresh:

```bash
ESPALIER_MAINTENANCE_MODE=1 espalier integrity refresh .
espalier integrity verify .
```

TP-91's `post_write_check.py` edit triggered this — without the
refresh, `integrity verify` reports drift on every subsequent run.

## Bash pattern extraction edge cases (known bypass classes)

`write_guard.py`'s bash extraction (`_HEREDOC_RE`, `_PYTHON_DASH_C_RE`)
catches the common `cat > path << EOF` heredoc form and `-c '...'`
inline strings. The interpreter-on-stdin form (`python3 - <<'PY' ... PY`,
`python3 <<EOF`, the here-string `python3 - <<< "..."`, and the node/ruby/perl
twins) was a KNOWN bypass class -- BC-OOS-003, filed beside the two-step
subprocess class as if the body were invisible to the shell text, and used as
a deliberate protected-zone bypass in TP-15..TP-18 -- until DEF-698 closed it
on 2026-09-06: `_INTERP_STDIN_RE` + `_stdin_program_bodies` read the body
between the operator and its terminator with the same literal-write patterns
the `-c` arm uses (now BC-051). The boundary that stays is the `-c` arm's:
computed paths, a body that is data to a script or module operand, and
file-mediated two-step writes (`BC-OOS-001`). Since DEF-704 (2026-09-07) the
`-c` / `-e` openers share the stdin arm's discipline exactly: anchored on
`_CMD_POS`, matched on the masked string, body sliced from the raw command
by offset, `[ \t]+` joiners -- so a `#` comment or a quoted mention is text,
and a `-c` on the next line is its own statement.

⚠ **Anchoring a raw matcher inherits every hole in the anchor.** DEF-704's first
cut anchored the four openers and LOST five spellings the raw regex had denied by
accident -- a quoted or escaped-space interpreter path, an invocation in an
`if`/`while`/`until` condition, a negated pipeline -- and every targeted test
stayed green because no row spelled them; the reviewer pair drove them. Before
anchoring anything, enumerate what the raw form denied, drive each spelling
through the anchored form, and repair the ANCHOR (the shared prefix serves
every verb), not the one opener. The same enumeration is owed BEFORE the
reviewers are dispatched, not by them. On the cross-shell routing lane the pair
returned seventeen findings and every one was the same shape — a spelling the
opener's tail did not admit (a clustered `-lc`, a positional program, a
slash-led switch, ANSI-C quoting, a doubled quote inside a single-quoted
PowerShell string) — each reproducing the exact asymmetry the lane was closing,
one character after the fix. Write out the outer shell's quote kinds and switch
spellings, drive each through the new opener yourself, and spend the reviewers
on the second-order shapes.

**A roster spelled for the other shell UNIONs, it never replaces.** PowerShell
runs any executable on PATH, so the bash read verbs are live spellings on that
tool and a translated roster is a narrowing: the first cut of the secret-read
twin traded seventeen verbs for five before an A/B drove it. Include the bash
roster whole, add the native spellings on top, and pin the twin on CLASSES in
both directions — every bash verb present, and every native verb mapped to a
bash class.

## Two constraints on writing a regex in `tools/cc/hooks/`

Both were found the same way: an existing gate refused the code and explained
why. Neither is documented in the hook contract, and both are invisible until
the gate fires.

### 1. Assemble a pattern with `+`, never with an f-string

`tests/test_redos.py::test_no_unreviewed_dotstar_in_hook_regexes` statically
reconstructs every `re.compile(...)` in the hook tree to prove it carries no
unbounded dot-quantifier. Its reconstructor resolves string literals, `+`
concatenation, and module-level `Name` references **recursively** — but **not a
general f-string interpolation** (it makes one exception, for f-strings whose
only interpolations are `re.escape(...)`, whose output is provably dot-star
free).

So a pattern assembled as `rf"...{_FRAGMENT}..."` is **unresolvable**, the gate
**fails closed**, and it refuses to certify the regex at all. Compose from
module-level names with `+`:

```python
_PART = r"(?:env|sudo)"
_ANCHOR = "(?:" + _PART + r"[ \t]+)"          # reconstructable
# _ANCHOR = rf"(?:{_PART}[ \t]+)"             # NOT reconstructable -> gate reds
```

This is a real authoring constraint, not a style preference: the f-string form
ships a regex nothing has proven ReDoS-safe.

### 2. `\S` matches `;` — never use it for a token run

A shell token cannot span `;`, `|` or `&`, but `\S` matches all three. A greedy
`\S*` run inside a pattern that retries at every command separator therefore
scans to end-of-input, fails whatever must follow it, and backtracks one
character at a time — **from every start position**. That is O(n²) on an input
the 32KB command cap happily admits.

Measured instance: `write_guard::_HARNESS_ENV_PREFIX_RE` used
`[A-Za-z_]\w*=\S*[ \t]+` and took **>1000ms** on `"x=1;" * 7500` against a 5s
hook timeout. Bounded to `[^\s;|&]`, the same input takes **1.9ms**.

**The shape hides from the obvious probe.** The same pattern is *linear* on
`"A=1 " * n`, because the spaces stop the run early. Only a **separator-dense,
space-free** payload exposes it — so a ReDoS probe that tests only spaced input
clears a quadratic pattern.

Use `[^\s;|&]` for every token run, and make sure the adversarial payload set
includes a space-free separator run.

**A switch run has the same shape one level up, and a new sibling is how you
find it.** A run that lets a switch take any bare value gives every shell head
two parses (a repeated head reads each following pair as switch-plus-value), so
the pre-existing here-string opener was quadratic on a repeated head (4.3 s at
28 KB through the write extractor) and nothing saw it until the `-c` opener
added beside it on 2026-09-14 earned a ReDoS row of its own. Refuse the head
word as a value and give both openers ONE run constant
(`_SHELL_SWITCH_RUN_BOUNDED`); `docs/SHARP_EDGES.md` (the ReDoS receipt, "Bound
the span is the remedy for class 2 only") carries the rule for whether a token
bound belongs beside that refusal.

## A gate's doc claim is driven through the protocol's re-fire path (2026-09-07)

"Blocks every Stop until X" is false for any gate behind `_run_main`'s loop
guard: Claude Code re-fires Stop with `stop_hook_active: true` after a block,
and the guard allows that Stop ahead of every gate, so a hygiene gate fires on
the FIRST Stop of each turn, not on every Stop. The first-hour lane wrote the
stronger claim into two docs, a test name and the changelog; the failure-mode
reviewer falsified it with one payload. Before describing what a block buys,
drive the gate with `{"stop_hook_active": true}` and pin that case beside the
block case (`tests/test_hooks.py::TestStopGateV3::test_the_continuation_stop_passes_by_the_loop_guard`).

Two companion invariants from the same lane, both pinned mechanically:

- **The hygiene gates only READ their relief records.** The table is
  `_hook_utils.RELIEF_FLAGS`; `subagent_stop` is the sole writer; an AST pin
  (`tests/test_subagent_stop.py::TestDocsMaintainerReliefFlag::test_stop_gate_hygiene_gates_only_read`)
  fails on a `write_text` inside any gate function. A gate that writes its own
  relief relieves on the request, not the event (DEF-608, the §C14 shape).
- **A bypass a gate offers is announced.** The hand record that relieves
  either gate prints one stderr line when honoured, the way a maintenance-mode
  bypass logs its use, and refuses a note under twenty characters. A silent
  escape spelled out in the deny text is taught to the actor the gate exists
  to catch; observable is the difference between an escape hatch and a hole.

## A state file's reader and writer are a pair on symlinks (2026-09-12)

Every writer of harness state -- the four copies of `atomic_write_text`
(`_hook_utils`, `cognitive_blueprint`, `execution_plan`, and the engine's
`espalier/_atomic_io.py` by default) -- REPLACES a symlinked target with a
regular file: the tempfile is renamed onto the path, so the link goes and
the file behind it is untouched. The readers that refuse a symlink (the
plan file's `read_text_nofollow(within=root)`, the statusline's and the
freshness cache's fd-level `O_NOFOLLOW` opens) therefore recover on the
next write, and a reader that follows links (`Path.read_text`, most of
`cognitive_blueprint`'s loads) reads the same regular file. The pair holds
as long as NO writer of state follows a link: a first cut of DEF-784 had
the engine follow every symlink, and `.espalier/freshness.json` behind a
link became unreadable to its own module's `O_NOFOLLOW` reader forever,
silently (`{}`). The one legitimate follow is the adopter's OWN file --
`.gitignore`, `.claude/settings.json` -- and only the engine's copy takes
`follow_symlinks=True`, at the five sites (the retire, the settings merge, repair, rewire and unwire)
`tests/test_atomic_io.py::TestSymlinkedTarget::test_only_the_adopter_file_sites_pass_the_keyword`
pins. Adding a symlink-refusing reader of a state file is fine; adding a
writer that follows one is a decision to make with that test.

The copies themselves are a derived roster: `tests/test_atomic_io.py::_REPLACE_WRITERS`
is asserted equal to every `os.replace` caller under `espalier/` and
`tools/cc/`, so a fifth inlined tempfile-and-replace reds there rather than
escaping the mode and symlink contracts; the engine's raw-write census also
reads an `os.open` with a create flag as a write.

## An audited funnel in a new hook touches four rosters, and its silence is proven under a real OSError (2026-09-12)

The Stop hook gained `_audit_block` (record, then `block`), the twin of the
PreToolUse hooks' `_audit_deny`. Landing it touched four rosters at once, and
the full tier found the one the targeted proofs never show:
`tests/test_governance_audit_log.py`'s `_AUDIT_WRITERS` (a literal inside a
call to one of these is an emitted event type) and the classifier's funnel
set (a funnel's own body is skipped, because `return block(reason)` forwards
its caller's reason), its `_UNLOGGED_BLOCKERS` (the hook's reasoned exemption
comes out, and an exemption there must now cite a ledger row), and
`tests/test_deny_markers.py::_FUNNEL_NAMES` (the marker contract reads the
reason at the funnel's call sites and needs the funnel's signature to find the
argument). Grep the test tree for the sister funnel's name before writing the
new one; the fourth roster was a tier red.

Every audited funnel claims that a record write that fails puts nothing on
stderr beside the decision JSON. Until this lane the claim was proved against
a monkeypatched `append_audit` that raised, which never reaches the writer's
own `except OSError` branch, and that branch warned. Now `append_audit(...,
quiet=True)` is what the three funnels pass, and each is proven silent under a
REAL failure: `ESPALIER_AUDIT_DIR` pointed under a file, so the mkdir raises
inside the writer. A silence claim is proved by the failure the writer can
actually produce, not by the one the test can most easily inject. Related:
[[one-writer-per-shared-state]] (the log is one shared file), the channel-XOR
entry in `docs/SHARP_EDGES.md`.

A crash guard is a block like any other (DEF-803, 2026-09-15). Its
`except Exception` emit was the one block outside the audited funnel, so the
log could not show a Stop the operator had just watched being blocked. Now
each fail-closed guard writes a typed `*_blocked_internal_error` record before
it emits (the exception's class, never its message), its reason has left
`_denial_reasons.FAIL_CLOSED_REASONS`, and the proof derives its population
from the tree: `tests/test_governance_audit_log.py::_crash_guard_writers`
finds every hook whose source writes such a record, so a fifth blocking hook
joins the proof the moment it copies a guard, and the bare-emitter classifier
accepts a crash guard only when the record write is on the emit's own path
inside its handler -- never a record anywhere in the enclosing function
(DEF-828, 2026-09-16: keyed on the function, a second arm rode its sibling's
record; a sibling handler, the try body above the handler, a statement after
the return, dead code after a return and a preceding branch that returned are
off the path; a flag-guarded record in the try's `finally` reaches every arm;
a record under a condition above the emit is accepted, the rule being
block-prefix, not control flow). The ascent is
`tests/_site_path.py::site_path(fn, emit, bound_at_handler=True)` since
DEF-833 / DEF-834 (2026-09-17), shared with the JSON dict-safety and
deny-marker censuses; the enclosing compound statements' headers are on the
path too. Write the record through a roster writer
(`_AUDIT_WRITERS`, each name pinned to reach `_integrity.append_audit`) in
the handler itself: a record behind a local helper the handler calls is not
seen, and the census reds a correct guard. Each guard carries its invariant:
nothing between the catch and the
emit may prevent the emit, and an interrupt inside a PreToolUse guard is
denied because a propagated one is an allow.

## A rename split across edits wedges the live guard; a shell-state walk must enumerate the constructs that do not run (2026-09-13)

Three lessons from TP-449 group 9, the write-guard layer.

- **Land a rename and its callers in ONE edit, or add-then-switch.** A
  `_speedbump` helper was renamed in the first of two parallel Edit calls; the
  second was refused because the first had already broken the hook, and the
  stale name was reached from `snapshot_discard`, which `write_guard._run_main`
  called unwrapped before the maintenance gate for every mutating tool -- Edit
  and Write were denied along with Bash, and only the operator's `!`-prefixed
  one-liner could repair the file. The call now fails toward allow like
  `check_fired` (a stderr line names the skip; the three deny-owning calls
  above the gate stay unwrapped on purpose, with a test). After any hook edit,
  before the next tool call: `python3 -c "import _bash_patterns, write_guard,
  _speedbump"` from `tools/cc/hooks`.
- **A syntactic model of shell state must enumerate the constructs that do NOT
  execute before it is trusted.** The first directory-chain walk credited every
  `cd` it could read; two review rounds drove eleven shapes against `/bin/bash`
  and each of these wrote into the protected tree past the model: a `cd` to a
  directory that is not there (the shell stays put), a `cd` after `||` or `&&`
  whose followers are not gated on it, a backgrounded or pipelined `cd` (a
  child shell moved), a `cd` inside a function body or an `if` / `case` / loop
  body, and `builtin cd` (not on the wrapper run). The other direction bites
  too: a `cd` into a directory the same command just made is not on disk when
  the hook runs, so the walk credits `mkdir` operands. Ask what the shell does
  with each line, construct by construct, and prove each against the real
  shell, never against the model.
- **A new module-level name can shadow an existing one silently.**
  `_REDIRECT_TOKEN_RE` and `_REDIRECT_OPERATOR_RE` already existed in
  `_bash_patterns` when the walk defined them again; Python keeps the last
  assignment, so the symlink tokenizer read the new pattern and the walk read
  the old one, and every test stayed green. The class-close census caught the
  two unlisted boundary tokens but not the shadowing. Grep `vars(module)` for
  the name before defining a constant in a module this size, and reuse the
  neighbour it collided with (the fix here).

Related: [[one-writer-per-shared-state]], [[fix-the-class-not-the-instance]].

## A delete is placed by offset, a hook edit lands alone, and deployed prose has forbidden tokens (2026-09-13)

Five lessons from TP-449 group 10, the guard trio.

- **A matcher that has an offset pairs by offset or slice; a spelling search
  is for extractors that have none.** `statement_directories` places a
  captured write path by searching its spelling across the chain's statements,
  because the path extractors return strings without positions. The first cut
  of the rm tier borrowed it, and an unrelated mention of the operand's name in
  an earlier statement at `/` lent the delete that directory: `cd / ; ls usr ;
  cd ~ ; rm -rf usr` walled a home-directory target, and the backslash spelling
  `src\gen` never matched the normalised needle at all and was judged in every
  directory the chain visited. The tier now walks each Bash statement's slice
  (`_rm_lands_catastrophic`) and each PowerShell invocation's `m.start("args")`
  against the chain's `(s, e, dirs)`; CP-DISCARD does the same through
  `_statement_bases`. Pair by position wherever the matcher gives one.
- **A hook edit and a Bash call in the same parallel tool batch race.** The
  guard judged the Bash call through a half-written `_speedbump.py` and refused
  it with the internal-error text; the last call in the same batch passed. Land
  hook edits in a batch of their own, import-check, then call the shell.
- **Deployed hook prose may not carry a PLACEHOLDERS token.** `<repo>` is one
  (`espalier/proofs.py::PLACEHOLDERS`, mirrored in
  `post_write_check.PLACEHOLDERS`), and
  `tests/test_proofs.py::TestRunCcSurfaceGatePlaceholders` reds on
  `write_guard.py` and `_denial_reasons.py`; `_bash_patterns.py` and
  `_hook_utils.py` are on the scan's exclusion list, which is why the same token
  in their docstrings did not fire. Say "the checkout by its own name".
- **A test that spawns git belongs in a `_SLOW_FILES` member, not a `unit`
  module.** `tests/test_test_suite_contract.py` reds twice on a
  `subprocess.run` in `test_speedbump_irreversible.py`; the discard-snapshot
  module already builds repositories and is slow-listed and
  security-classified, so the class moved there.
- **A PowerShell flag prefix shared by two parameters is ambiguous, and
  PowerShell itself refuses it.** `-f` on `Remove-Item` is `-Filter` and
  `-Force`; `_ps_removal_target_tokens` reads it as value-taking (the token
  after it is not a target -- the direction that cannot add a wall), and the
  fixture that expected a switch was the wrong one. Only a prefix unique to one
  roster resolves.

Related: [[one-writer-per-shared-state]], [[fix-the-class-not-the-instance]].

## A pattern arm is only blindable if the dispatch resolves it by name (2026-09-14)

A contract test proves an arm is load-bearing by replacing it with a pattern
that never matches and watching its rows allow, and that only works when the
consumer reads the arm off the module at call time: build an inner pattern
table as a map of NAMES and resolve each through `globals()[name]` in the
dispatcher (`_MUTATION_INNER_ARMS`), never as a table of compiled objects
captured at import. Where the arm roster is hand-written, pin it to the readers'
free names with an AST walk over the reader bodies
(`tests/test_write_guard.py::test_the_consumption_tuples_are_the_readers_free_names`,
on the `tests/test_atomic_io.py::_REPLACE_WRITERS` precedent), or the census
note beside it certifies a derivation the code does not have. Sibling:
`docs/STANDING_PRINCIPLES.md` §19 says mutate the component rather than the
fixture; this is what the component has to look like for that to be possible.

## An OSError is rendered through the seam, and a path is never repr'd (2026-09-15)

`str(exc)` on an `OSError` renders the filename through `repr` -- doubled
backslashes and quotes on Windows, where the operator then pastes a path that
does not exist (`DEF-799`: five sites driven on the walk, 95 by the pins on
the prior head across the engine, the hooks, `session_resume`, `statusline`
and the scanners -- every hook's `except Exception` crash guard among them,
because a broad handler catches an OSError and fires on exactly the file read
that fails). In a hook, hand the exception to `_hook_utils.warn_exc(prefix,
exc)`, the one reporter, which renders through `_json_safe.os_error_text`;
where a hook builds its own line, interpolate `os_error_text(exc)` imported
FROM `_hook_utils` (it re-exports the `_json_safe` helper behind a guarded
import that degrades to `str(exc)` when an adopter's `_json_safe.py` is stale
or missing -- a new module-scope `_json_safe` edge sits above every crash
funnel, so do not add one for this). The engine twin is
`espalier._text.os_error_text`, parity-pinned. And never `!r` a path, a hook
command or an interpreter token: plain inside backticks. Two pins in
`tests/test_portability_contract.py` close the class
(`TestOsErrorsRenderAsPaths`, keyed on the handler binding -- types that can
CATCH an OSError, `Exception` included -- so no sink and no closure escapes it,
with every roster helper proven to call the seam; `TestPathsAreNotRenderedThroughRepr`,
on the binding source and a live-pinned vocabulary with a red fixture per
name). The census that scoped the lane missed the six scanner sites and then
the 21 broad handlers the pins and the failure-mode review found, which is
what a derived population and a second reader are for.

## A tier that walks the directory chain pays the walk on every call; gate it on the verb first (2026-09-15)

DEF-815 added a second catastrophic classifier beside the rm one and copied
its shape exactly -- `bash_directory_chain`, then every root judged from each
statement's bases. Correct, and it doubled the dangerous funnel's cost on the
opener-flood budget row: 830 ms to 1,237 ms on a 64 KB flood with no `find`
in it, because the chain walk IS the cost and the funnel runs on every Bash
call, on the tier maintenance mode never bypasses (DEF-817 had already
measured the row at eighty percent of its ceiling). One linear search over
the spliced text for the action the tier cares about
(`_FIND_DELETE_ACTION_RE`), before any walk, brought it back to 823 ms.
Before adding a consumer of the chain, ask what every Bash call will pay for
it, gate the walk on the cheapest witness the tier has, and run the flood
rows (`tests/test_redos.py::test_bash_walker_linear_on_opener_flood`) before
the reviewers, not after. Two smaller lessons from the same lane: a derived
roster keyed on the dispatch tables' NAMES
(`TestRemovedOrRelocatedOperandIsAMutation`) reddens the moment a table entry
becomes a tuple name -- re-key the rows to the tuple and blind the tuple
whole, as the python entries already are; and an inner-language matcher owes
`_UNANCHORED_BY_DESIGN` in `tests/test_speedbump_irreversible.py` its
category and reason, which is the command-position classification a new arm
is said to owe. Related: [[fix-the-class-not-the-instance]].

**A "narrowing" set is the wall's exit, and a predicate's POSITION is part of
its meaning.** The find tier's first cut reused the zone reader's narrowing
set (`-type`, `-size`, `-mtime`, `-user`, ... beside `-name`) and asked only
whether one appeared anywhere in the span; both reviewers drove the one-token
exits in minutes -- `find / -size +0c -delete`, `find . -delete -name zzz`
(find evaluates left to right, so a predicate after the action steers
nothing), `find . ! -name zzz -delete`, `find / -name zzz -o -delete`. A
predicate narrows only when a hook file cannot satisfy it (name or path),
only before the action, only un-negated, and only when no `-o` hands the
action a wider branch. Before shipping a tier keyed on "is this narrowed",
enumerate the predicates a protected file satisfies, the operator's position
relative to the action, and the two re-wideners -- and read the verb the way
the sibling arm reads it (`FIND`, `-exec /bin/rm`, `-exec env rm` were all
exits too, and the rm tokenizer admitted every one).

**The same bill arrives on the binding pre-pass, and the exit is a cheap RAW
check** (DEF-847's lane, 2026-09-19). `_expand_simple_var_assignments` sits on
the same every-Bash-call path -- the walls ask for its reading on every call --
and its first cut masked the text unconditionally to find its binding sites:
the ReDoS chain row went from 0.88 s of its 1 s budget at HEAD to 1.01 s, over
the ceiling, on the heredoc-flood shape of
`tests/test_redos.py::test_the_delete_walk_stays_linear_through_the_chain`. One
raw search for an assignment site before any masking walk restored 0.88 s. What
makes such an exit SOUND is the direction of the pass it skips: the mask only
blanks, so every live site is a raw one and a raw miss can never become a hit --
write that argument beside the exit (the pre-pass does) or the next author reads
the exit as a guess and widens it. So the rule is not about the chain walk.
Anything on a path every Bash call pays -- the pre-pass, the four walls, the
dangerous funnel -- earns its cost only behind the cheapest witness that it has
anything to do at all; nine sites in the module already say so in those words.

## A hook's text-mode capture is decode-guarded by one of two arms (2026-09-16)

`UnicodeDecodeError` is a `ValueError`, not an `OSError`, so the
`(subprocess.TimeoutExpired, OSError)` tuple every hook wraps its git and
blueprint captures in let a non-UTF-8 byte in `git status`, `git log` or a
blueprint's text crash the hook -- and a hook's crash is either a lost banner
or, on a PreToolUse hook, a fail-closed deny of every tool call. The rule
(`DEF-821`; the pin is `tests/test_contracts.py::TestSubprocessDecodeGuarded`
over the derived production surface, `tools/cc/` included): where the captured
text is names, lines or sentences -- `status --porcelain`, `log --oneline`,
`ls-files`, a branch name shown in a summary, the blueprint scripts' output --
add `errors="replace"` and put `ValueError` beside the `OSError` in the tuple;
where it is a structured answer the CONSUMER treats as a value -- an
interpreter's `--version` banner, a `rev-parse HEAD` SHA, `stash create`'s
object id, a `rev-parse --show-toplevel` root that becomes a `Path`, a branch
name fed back to git -- keep the strict decode and add `ValueError` to the
tuple, so a corrupted answer takes the probe's own failure path
(`interpreter_is_python3` returns its "not python3" verdict; `snapshot_discard`
skips the snapshot; `_repo_root` falls back to the cwd) rather than masking the
corruption with a replacement character. The arm follows the consumer, not the
argv: the same `branch --show-current` is replace in a summary and strict in a
worktree plan. Mark every strict-arm handler
`# strict decode: a structured answer (DEF-821)` so it never reads as an
unfinished replace site (the review found the two roots and two version
banners drifted onto replace during the sweep itself; the pin now refuses a
tolerant `errors=` on the roster shapes `--version`, `rev-parse HEAD`,
`--show-toplevel`, `stash create`, and refuses `errors="strict"` or
`errors=None` as a guard). A capture whose pipe is never decoded carries
`# decode-errors-ok: <reason>` on the call line. The sweep was a per-site table
(replace / ValueError / both / pragma), applied by one script that edits
without adding lines and asserts every anchor once, then
`scripts/sync_vendor_cc.py` and `mypy tools/cc/hooks/`.

The `read_text` twin (`DEF-829`, 2026-09-16): a hook's strict read of an
adopter file -- `cc/COMMANDS.md`, the fingerprint, the manifest, its own state
markers and plan file -- under `except OSError` is the same lie, and the
SessionStart crash guard turns it into a lost banner on every session, the
Stop gate's into a block. Where the bytes go to `load_json_dict_safe`, hand it
`read_bytes()` (the helper decodes tolerantly; the strict `read_text` in front
of it was the defect); where the text is shown or parsed loosely,
`errors="replace"` and `ValueError` beside the `OSError`. The pin is
`tests/test_contracts.py::TestTextReadsDecodeGuarded`; the hook rows drive the
real hook on a latin-1 file (`tests/test_hooks.py`, `tests/test_stop_gate.py`,
`tests/test_integrity.py`). A read under no try at all is not this class --
but it is the same symptom where the module promises never to crash
(`session_resume` read `cc/PACK_MANIFEST.txt` for `/status` with no handler
and said "must not crash /status" three times), so a hook-side reader of an
adopter file reads with a replacement character whether or not a handler
wraps it, and `read_text_nofollow`'s docstring names the decode error among
what it raises. The inverse holds too: a tolerant `errors=` on a structured
file (the fingerprint, a manifest, the plan file, the probes) is an offender
in its own right, and the `# strict decode: a structured answer` marker is
checked to sit on a handler naming `ValueError` -- prose nobody reads is not a
contract.

## The other shell's verb table is per platform; drive the resolution before writing the arm (2026-09-16)

The PowerShell guard lane (DEF-824, DEF-822) opened on a premise its own
ledger row carried: that pwsh aliases `rm` to Remove-Item, so the bash
spelling does not execute on that tool. `Get-Command rm,find` under pwsh
7.6.5 on the self-host Mac answered `/bin/rm` and `/usr/bin/find`, and the
lane grew a third sibling nobody had filed -- the bash-flag `rm` on the
PowerShell tool, the real delete on a POSIX host with no wall and no nudge.
The catalog entry is `docs/SHARP_EDGES.md` ("pwsh's alias table is per
platform"); the discipline for this file:

- **Before writing a twin arm, print the resolution on the platform in
  question** (`Get-Command <verb>`), then drive the effect on a throwaway
  with no delete of your own in the command (the classifier trips on a
  command that carries both a recursive delete and fixture vocabulary; a
  `mktemp -d` throwaway needs none).
- **A roster spelled for the other shell UNIONs** (the entry above) has a
  premise-level twin: a VERB the other shell runs natively is a live
  spelling on that tool, and the arm that reads it must read the native
  flag grammar too (`-rf`, `-r -f`, `--recursive`, and bash's rule that an
  `i` after the last `f` cancels force), not only the cmdlet's prefixes.
- **The oracle must read what the shape removes.** An enumerator pipeline
  removes a root's children and leaves the root; a `victim`-directory
  oracle reads it as not reaching. The differential's sweep rows carry an
  oracle field for that reason, and a row is listed only for the platforms
  it reaches on.
- **A bare `{}` is a script block to pwsh.** `find . -exec rm -rf {} +`
  is inert as typed there; the quoted `'{}'` runs. The guard reads both
  toward refusal; the differential drives the one that runs.
- **A narrowing predicate narrows by its VALUE, and lands with its
  degenerate-value twin.** The first cut set `narrowed` on the presence of
  `-Include`/`-Filter`/a wildcard root, shipped three must-allow rows
  (`*.pyc`, `*.log`, `*.tmp`) and no must-deny twin, and its own deny text
  told the operator to add `-Include`; `gci -Recurse -Include * | ri -r
  -fo` and `find . -name '*' -delete` then wiped a throwaway with no tier
  fired, green on 624/624 and 313/313. The born-weak shape: the suppression
  and the guard in one change, un-witnessed by a negative fixture. Every
  carve-out lands with the row that proves it still fires.
- **A premise driven on one fixture is a premise about that fixture.**
  "A recursive enumeration into a plain remove aborts on the prompt and
  deletes nothing" held on a tree whose first entry was a directory with
  children; on a tree of empty directories it deleted everything. State
  the mechanism ("aborts at the first directory with children; everything
  enumerated before it is gone"), not the outcome, and drive a second
  fixture before a row pins an ALLOW on it.
- **Re-ask the class question for the whole roster, not the verbs the
  drive happened to name.** The lane closed `rm`, `rmdir` and `find` and
  stopped; `unlink`, `shred`, `truncate` and `git clean` were the Bash zone
  reader's verbs the PowerShell reader still lacked, and `unlink <hook>`
  deleted the hook under pwsh while Bash refused it. The Bash reader's verb
  roster is the checklist.

## A discovered command is resolved once on each tool's raw pre-pass, never per head (2026-09-16)

`DEF-827` filed the call operator on a command object (`& (Get-Command
find) . -delete`) against the PowerShell find head and proposed an arm on
that head's executable prefix. The lane measured the class first: `& (gcm
ri) -Recurse -Force .`, the dot-source operator, the object's `.Source`
member, and on the Bash tool `$(which find) . -delete`, `"$(command -v
rm)" -rf .` and the backtick form each wiped a throwaway under the real
shell, and nearly every anchored head on both tools answered nothing (the
quoted-verb rosters, spelled with the discovered head, went red on
thirty-one of the thirty-six Bash arms and twenty-seven of the twenty-eight
PowerShell arms with a fixture; the six that held deny through another
reader). The prefix arm would have closed one head of sixty-four. The
discipline for this file:

- **A spelling of INVOCATION is orthogonal to the verb, so it is resolved
  once on the text every head reads, not admitted arm by arm.** The
  PowerShell scan pair (`powershell_scan_pair`) and the Bash splicer
  (`splice_line_continuations`, the raw pre-pass every Bash reader applies
  in one of its two orders) are the two homes; the verb keeps its offset,
  the spelling's own characters are blanked, length is kept. The masker
  is the wrong home on Bash: a reader masks a text it has already spliced
  and reads its operands from the spliced RAW one.
- **A rewrite must reach the RAW twin at the same offsets.** The first
  cut resolved the scan alone; every arm whose operand span begins at the
  blank after the verb then read `) -a <hook>` from the raw text, and
  `_strip_span_tail` cut it at the unmatched close -- nine of the
  thirty-six Bash arms and the PowerShell pipeline reader allowed the
  discovered spelling beside a denied bare one, under a green find matrix.
  Match on the scan (a mention's operator is already blanked there), blank
  both texts where the scan changed (`_blank_where_changed`).
- **A resolver's optional quote is PAIRED with its partner inside the
  match, or it unbalances the command.** An unpaired `["']?` after the
  substitution ate the closing quote of `echo ";$(which find)" . -delete`
  (the `;` inside the string is a separator to the raw-text anchor), the
  masker bailed on the unbalanced command, every quoted mention in it
  went live, and a command that prints text drew the HARD wall (code
  review, driven A/B against HEAD). A backreference (`(?P<q>"?)` ...
  `(?P=q)`) consumes a quote only when the match holds both.
- **The Bash tool is the operator's login shell, not bash.** On the
  self-host Mac `ps -o comm= -p $$` inside the tool answers `/bin/zsh`
  (5.9). zsh's `whence`, `whence -p`, `where` and the equals expansion
  `=find` are the same class by another spelling, and every fixture in the
  lane's first cut spelled a bash-only idiom (failure-mode review, driven
  on /bin/zsh: each wiped a throwaway, the guard allowed each). A Bash-tool
  row is driven under the shell the tool actually runs; a bash-only
  spelling is half a row.
- **The class pin is the existing roster, re-spelled.** `TestDiscoveredCommandHead`
  walks the two quoted-verb `_FIXTURES` rosters with the discovered head,
  so a new anchored arm is proven on it the day it lands. The first cut
  excepted the directory verb "because `which cd` answers a shim that
  moves nothing" -- true for `which` and `type -P`, false for `command -v
  cd`, which answers the builtin's name and moves the caller (driven: the
  write landed in the zone); the exception suppressed a row that passes.
  An exception by reason is still an exception: drive the reason on every
  spelling the resolver admits before writing it.
- **Anchor the resolver on the module's own command position**
  (`_PS_CMD_POS`, `_CMD_POS_NO_VERB`), never a restatement of its class:
  the speed bump's census reads a restated class as SELF-ANCHORED, the
  near-copy that drifts. Every declared limit that stays -- the path held
  in a variable on either tool, a pipeline or a list inside the
  substitution, a parameter as the discovery verb, a discovery that is not
  `Get-Command` -- is a DECLARED matrix row (the PowerShell variable form
  also a rehearsal `KNOWN_GAPS` entry), so it fails the day it closes; a
  limit stated only in prose rots silently (both reviews found the first
  cut's `-CommandType` limit stated in one comment, citing pins that
  covered a different limit).

## A pipeline spans the chain's statements; place its sweep by the enumerator's offset (2026-09-16)

The carrier lane (DEF-826) gave the Bash tool the pipeline arm the
PowerShell tool got from DEF-822: an enumerator piped through `xargs` into
a remove verb, its operands arriving on stdin, judged by the ENUMERATOR's
roots through the same three tiers. What the lane learned about writing an
arm whose shape crosses a statement boundary:

- **The directory chain splits on the pipe.** `bash_directory_chain` treats
  `|` as a statement boundary, so a classifier that judges each statement's
  slice holds half a pipeline in each and matches nothing -- the first cut
  did exactly that and every wall row stayed red. The PowerShell classifier
  already had the answer: read the opener over the whole scan once, take
  each sweep's OFFSET (the enumerator word's, not the match start, which a
  leading `cd` statement can swallow), and place it in the statement that
  holds that offset with one cursor. `has_catastrophic_piped_remove` does
  this; the find arm keeps its per-statement walk (`_bash_sweep_walk`)
  because a find never crosses a pipe.
- **A switch run needs to know which switches take a value.** The first
  cut let any switch take the next word as its value, so a glued count
  (`-n1`) swallowed the command that followed it and the arm read the wrong
  verb. The run is one arm per token: a valued switch spelled alone takes
  one value, every other token none, and the generic arm excludes exactly
  the bare valued spellings so a token has one parse (the ReDoS rule the
  wrapper run learned).
- **Every gate wants the verb where it expects it.** The assignment-prefix
  scrape derives verbs from the word immediately left of the guard, so a
  named group around the head hid it (read the head from the match text
  instead) and a carrier word behind an optional group's close needed its
  own word boundary. The anchor census reads `_UNANCHORED_BY_DESIGN`, not the
  word-axis exemptions, so a span flag or a gate is declared there.
- **The oracle follows the shape, per head.** A find head lists its root
  first, so the victim oracle reads it on both differentials; a listing
  prints names relative to the current location, so its row moves into the
  target and the canary reads it -- a row written the other way reads as
  "did not reach" and reds as a must-reach on its first run.
- **Which tier walls and which nudges was settled one lane earlier:** the
  hard tier walls wipes (a recursing remove, a files-only walk; on Bash any
  walk into the native `rm`, which takes every file), the soft tier nudges
  every un-narrowed sweep. A row's expectation follows that, not the
  author's first guess about a one-level listing. The rule is ONE
  predicate both tools call (`_sweep_is_wipe`), with `native` the only
  input that differs between them.
- **An argv-list element is a process argument; decide which ones the
  readers should see as syntax, narrowly.** The first cut quoted any list
  element carrying a metacharacter or a blank, to make a literal pipe token
  inert -- and quoted a whole shell body handed to `-c` with the POSIX
  escape, which the nested-shell reader does not re-parse (a protected-path
  write inside it went unread), and a quoted separator truncated the rm
  tier's span. The relief the differential wanted needs only the pure
  operator tokens (`|`, `&&`, `;`, a redirection) replaced by a neutral
  word; every other word is joined raw. Both reviewers found the widening
  independently; the narrow rule kept all twelve relieved rows.
- **The other platform's switch table is a roster too.** GNU's placeholder
  switch was read, BSD's twin (the one macOS ships) was not, and the
  unread switch's placeholder became a phantom operand that stopped the
  opener before the verb -- no tier at all, on the self-host box. A switch
  run's valued set is derived from both manuals, and the row for the other
  spelling lands with it.
- **A twin arm is read by the twin's readers, roster for roster.** The
  PowerShell carrier followed only the cmdlet verbs, so the find arm's
  `-exec` verbs (native behind xargs on a POSIX host) were false allows
  there, and its walk flag was find-only, so the recursive listing into a
  plain native remove nudged where the Bash tool walled. The Bash reader's
  verb roster and its walk rule are the checklist, again.
- **A two-word head is a spelling, not a roster word (DEF-831,
  2026-09-16).** The version-control listing joined the carrier's heads on
  both tools, and what a head that composes on another arm's constant
  taught: (1) module order is a dependency -- the git head's one home
  (`_GIT_SUBCOMMAND_AT`) had to move above the carrier that composes on it;
  (2) keep each head alternative behind its own `\b(?!=)` guard inside the
  head group, or the assignment-prefix scrape stops deriving the one-word
  verbs; (3) a pattern that gains the word `git` enrols in the
  git-mentioning gate (`TestCommandPositionClassClose`) and the anchor
  census reads it on the word axis too -- a search-only classifier over a
  match's own text (`_PIPED_HEAD_RE`) was retired for a `head` group on
  both openers instead of being declared twice; (4) read the head from the
  RAW text at its group's offsets, as the spans are read: the match's own
  text is the masked scan's, and a `-C` value on the head carries the root
  (the row probe's paren shape drove the masked read to a nudge, the spaced
  shape to no tier); (5) a quoted global-option value with a blank
  defeated every git arm, since the one home's value class stopped at the
  blank -- widened to bare-or-quoted with the three arms disjoint on their
  first character, pinned by the roster test and flood rows; (6) a
  listing's population rule follows the sibling reader in the module:
  `git clean`'s ignored form is the whole tree and its untracked form is
  the speed bump's, so the listing's untracked-only population is the
  nudge only with the standard excludes applied (driven: without them the
  ignored files are listed too); (7) a listing-shaped head's executing rows
  live where the canary oracle is (the pwsh differential, the repository
  set up inside the row -- the index is what the listing walks, so a
  staged canary needs no commit); the Bash differential's oracle reads a
  directory gone and cannot see a children-only wipe, so a non-reaching
  body there reads as a new false deny, not a row. The review batch added
  three: (8) a hand-written span loop drops redirections the way
  `_operands` does, or a silenced stderr becomes the root -- the listing
  reader and the version-control clean reader had the same hole, one
  class; (9) a population downgrade checks EVERY other selector, not the
  presence of one: git's selectors are additive, and the cached-plus-others
  idiom (the everyday "every non-ignored file" listing) is wider than the
  bare listing, so reading only the others selector took a walled command
  to the nudge; (10) the heads are one table of key and spelling, and the
  readers are a dict checked against the keys at import -- a fourth roster
  word otherwise reaches the opener for free and falls to the last
  branch's grammar with every gate green, since the class-close axes key
  on the word `git` or on compiled patterns and a string added into an
  existing pattern is neither.

## A program operand is one shell word; a row whose mechanism does not reproduce is re-driven, not re-fixed (2026-09-16)

DEF-832 was filed on one mechanism (the joined argv line of an
interpreter's shell-out) and the first drive of its own probe spelling at
the hook denied. What the lane learned:

- **Re-derive by reading the reader, not by walking spellings.** A row's
  stated mechanism is a load-bearing premise, and this one was false
  ([[premise-check-before-authoring-a-fix]] is the sole home of that
  rule; this entry is its hook-specific instance). The honest next move
  after a non-reproducing row is one hypothesis from the code, written as
  one must-deny row, run once by name -- a sequence of single-value probes
  across calls is the input matrix the classifier reads, whatever each
  call prints (the tenth trip; the auto-memory entry carries the rules).
  The real mechanism was one sentence in a helper's
  docstring: the shell concatenates adjacent quoted and bare segments into
  one argument, and every program-operand reader took the first quoted
  span. A path quoted inside a single-quoted program can only be spelled by
  ending the outer quote, spliced or naively, and the shell accepts both
  and strips the quotes -- so the program ran with a bare path and the
  guard saw nothing, on the interpreter, the POSIX shell and the PowerShell
  command operand alike. The class is the readers of a program operand.
- **The neighbours, again** ([[read-the-neighbours-before-adding-a-sibling]]
  is the sole home). A procedural bash-word reader with exactly the
  quote-removal semantics already existed one arm over
  (`_read_shell_word`, the here-string arm's); the lane wrote a second
  tokenizer before finding it and retired it the same hour. The word
  GRAMMAR (`_BASH_QUOTED_WORD`) is new because the openers need a span;
  the quote REMOVAL is the existing reader, through one thin view
  (`_bash_word_text`). And the two are hand-parallel lists: the grammar's
  bare stop set is the reader's explicit blanks and metacharacters, never
  the whitespace class (a form feed is no word break to bash; the class
  cut a word the shell kept whole), and the reader needed the locale arm
  the grammar admitted -- a derived test pins the stop sets equal now.
- **A shared helper changed under a scope note naming one shell.** The
  operand reader (`raw_operand`) serves both legs; the bash word reading
  went in as its default and the PowerShell leg lost a listed protected
  file (a comma joins a path list there) and a quoted directory with a
  trailing separator (a backslash is a separator there, not an escape) --
  both driven old-vs-new by the reviewers with every listed proof green,
  because the proofs were class selections and the file's own cross-shell
  row was never run. The word reading is opt-in per call site, the Bash
  write leg's sites opt in, and a change to a helper both legs read earns
  the whole guard test file plus the PowerShell-leg files, never a class
  selection.
- **A bound with no receipt is a fail-open cliff.** The word grammar's run
  was bounded at first; past the bound the opener still matched a
  truncated word and the reader yielded the truncated text (padding with
  empty segments, driven to a landed write), and the bound bought nothing
  since every iteration consumes a self-delimited segment and the arms are
  disjoint. The switch run three lines above already says so; the receipt
  is the flood rows.
- **Every reader of an opener reads the same group.** The inline openers
  had two readers (the write leg's and the mask's reader-program bodies);
  the second kept the old numbered groups, raised on every inline program,
  and the mask degraded to raw text -- mentions refused on the hard tier
  with every targeted test green. A named group and a grep for every
  consumer of the opener before the first run.
- **The raw scan reads a single-span program; a spliced one only as its
  concatenation.** A POSIX `-c` body is off the masker's roster, so the
  write leg read it raw and needed no reader -- until the body was several
  segments. Its word text now joins the write leg's nested programs, and
  `raw_operand` reads a quoted capture to the end of its word (the glued
  spelling an earlier row kept out of scope).
- **The newline census wants the body named as one literal.** A new body
  shape with several quoted arms reds the allowlisted-opener check until
  the census blanks the word first; the bare arm's escape excludes a
  newline so nothing but the body crosses one.
- **A row's executing oracle wants its own wrapper.** The differential's
  quick set is fixed; the spliced list wrapper joins the full matrix with
  its mention twin, both pinned in the liveness rosters and the needs map.

## A compound statement crosses lines by grammar; its operand spans do not (2026-09-17)

The loop carrier lane (DEF-830) gave the Bash tool a reader for the
enumerator bound to a loop variable and removed in the loop's body -- the
carrier wipe (DEF-826) spelled as a compound statement, which drew only the
soft tier's variable-operand nudge until this lane. What writing an arm whose
shape is a compound statement taught:

- **Three heads, one family.** The pipe into a read loop, the for loop over
  a command substitution and the read loop fed at its tail are one reading
  function on the carrier's building blocks (the enumerator head group, the
  pipeline roots reader, the rm tier's tokenizer, the one wipe predicate),
  one sweep iterator sorted by offset across the openers, and one placement
  helper EXTRACTED from the carrier classifier (`_placed_sweeps_land_catastrophic`)
  so the two readers cannot drift on where a sweep runs. Each tier gains one
  line: the union, the roster iterator, the zone iterator, the wall site.
- **The body's operand must expand the loop variable exactly.** A path beside
  the item (`"$f"/sub`, `"$f".bak`) is not the item; a fixed operand is the rm
  tier's own and the loop is not the carrier (`effect` `none`); another
  variable is the soft tier's; the read builtin with no name binds `REPLY`. One
  token matcher owns the spelling, declared in the anchor census as a tokenizer.
- **Keywords in lower case, where bash reserves them.** Bash reserves `do` and
  `done` only in lower case and only behind a separator, so the openers match
  them so (`(?-i:...)` under the case-insensitive flag) and the witness gate is
  the `do` keyword behind a separator with bounded whitespace -- an English
  "do" in a commit message opens nothing, and a separator flood pays one
  bounded scan each.
- **A compound statement spans lines; the anchored-span newline census needed a
  second declared category, not an exemption.** The census's allowlist promises
  "only the quoted program body crosses a newline" and checks it; a loop's
  keyword joiners and body run cross lines by grammar and are no quoted body.
  The new roster (`_SPAN_MAY_CROSS_NEWLINE_AS_A_COMPOUND`) promises something
  else -- the OPERAND spans (`args`, `rmargs`) stop at their line and the opener
  names the keyword -- and a check asks exactly that of those spans, with a
  mutation witness for each span and for the keyword. A category is a promise
  plus the check that can fail it.
- **A substitution span carries quoted words whole.** The first cut closed the
  span at the first paren, so a root with a paren in its path (the row probe's
  shaped root) ended the enumerator early and two zone rows under the paren
  shape read allow. The arms of the span are told apart by their first
  character (a quote, a backslash, anything else), the ReDoS rule again.
- **An executing row binds its variable at every layer.** A loop row's variable
  is bound by its own `read` or `for` in the row's text; a wrapper that
  re-parses its argument in double quotes expands the variable in the OUTER
  shell first, so the differential's sandbox environment binds the same name
  to a path inside the sandbox that does not exist. The oracle's base bit
  already denied these rows (the nudge is a deny to the bit), so the run
  reports them unchanged; the fix is visible only as a tier, which the hook
  rows pin (`bump` to `wall`). The reach bit is what the differential adds.
- **A sibling shape is asked before it is fixed -- and pinned to its exact
  verdict.** The for loop over a bare glob list and the PowerShell
  statement-form loop were asked at the hook. The first drew the nudge (its
  wall is its own row); the second is the remove cmdlet's variable-operand
  wall already. The first cut pinned both to "a nudge or a wall"; the review
  named that a floor, not a pin -- a two-verdict set cannot see a false deny
  on the narrowed everyday twin -- so each is pinned to the one verdict it
  draws, with the narrowed twin beside it.
- **A bounded statement run must decline the thing it runs up to.** The body
  run stepped over the loop's own remove and its closer and let a LATER
  removal fill the verb group, which then named no bound variable and dropped
  the carrier as "not the carrier" -- a false allow on a loop followed by any
  second cleanup, found by the code review with one classifier value. Each
  statement in the run now declines the remove verb and the closer keyword;
  the rows are the second removal after the closer (the wall) and a loop that
  removes nothing followed by a removal of the variable (not the carrier).
- **A reader spelled through a loop over a tuple is invisible to the AST
  census.** The zone arm searched with `for rx in (...)`, so the consumed-arm
  pin -- which collects `NAME_RE.finditer` calls -- saw nothing, while the row
  census reddened on the three unnamed arms: two contracts mutually
  unsatisfiable until the CALL SPELLING changed. Spell each opener by name in
  the reader, as every sibling arm does; the iterator that the census does
  not cover may keep its loop.
- **A confinement that reads literal operands cannot see a variable.** The
  differential's five conditions passed for `"$name"` whatever the shell
  would substitute. Condition six asks the ENVIRONMENT: every parameter
  expansion in an executing row must name a variable the sandbox environment
  binds inside the sandbox, an unbound name refused before any shell sees it,
  with the must-trip twin. The body contract that forbids `$` in a body
  names the three loop rows as its reasoned exception and pins that their
  expansions are exactly that one bound name.
- **A category's check derives its population.** The compound census's first
  check named two groups by hand and extracted them with a regex that a
  literal paren inside a character class would truncate silently; it now
  walks the pattern source with the regex grammar's own rules and checks
  every named group, witnessed by mutation on every roster entry.

## A head with no enumerator reads its words as the direct remove does -- and every bound on a word run is a cliff (2026-09-18)

The word-list lane (DEF-837) gave the loop family a fourth head, a `for` loop
over a bare word list, which has no enumerator. What it taught, most of it
from the two reviews run at once:

- **A second roots shape, read with the regex that parsed it.** The words
  are the rm tier's own operands, so they are judged by its own rule. They
  are cut by the SAME word regex that matched the list, on the scan span
  (`finditer(m.string, start, end)`), and read raw at each word's offsets.
  Two first cuts each broke a real bash word: the hard tier's whitespace
  split broke a quoted path with a blank, and a quote-aware token stream
  split `"$root"/*` into `$root` and a phantom `/*` judged as the root -- a
  false wall the bench row probe caught under every root shape.
- **A bound on a word run is a cliff, not a safety margin.** A 64-word or
  256-character bound made the WHOLE compound statement stop matching one
  word past it, reopening the gap the head closed. This is the third time
  the file has learned it (`_INTERP_SWITCH_RUN`, the DEF-832 word): read the
  calibrated sibling before writing a new span. Its receipt applies: disjoint
  arms plus mandatory separators give one parse, measured linear to the
  scan cap.
- **"Parity with the twin" copies the twin's gaps.** The head first took the
  rm tier's recursive-AND-forced threshold, so `for f in *; do rm -r "$f"`
  was allowed while the other three heads walled the same body -- the loop
  shape deciding. rm(1) prompts only for an unwritable file and only on a
  terminal, so the rm tier's own threshold is the defect (DEF-842); the head
  takes the family's one wipe rule instead and declares itself stronger.
- **A twin invariant is two-sided, with named exceptions that must still
  hold.** "Never weaker than the twin" could not see the phantom-root false
  wall. The table pins equality, or a DECLARED `stronger` / `weaker`
  divergence with its reason, which reds once it stops diverging. Three
  tokenizers read "the same words", so a parity gate derives its population
  from the rm tier's own flag-order matrix, and a mutation proved it reds.
- **A roster three sites share is one table.** The reading, the zone
  reader's unquote and the sweep iterator's gate each keyed on the opener
  by identity. `_LOOP_OPENERS` now holds the shape, looked up so a miss
  raises, and a test pins it to the derived `_DO_BODY` population and the
  zone reader's by-name arms.
- **The soft tier's roster pass is for an enumerator's unseen tree.** It
  fires on `*` and `*.pyc`, so a word list reaches it only as a wipe; a
  mutation that removed the gate reddened nine rows across three tests.
- **A net's promise must be as wide as what it catches, and survive the
  command.** The discard-snapshot arm learned the loop's roots, and its first
  cut promised a snapshot for a narrowed or untracked-only loop, which takes
  no tracked content, and for `rm -rf .git src`, whose re-issue deletes the
  store the snapshot lives in. The arm now reads only the roots a loop takes
  WHOLE (`_LoopRemoval.whole`), and none when the delete takes the root,
  `.git` or the log. The loop is placed by the wall's own placement, split
  out of its judgment as `_placed_sweeps`.
- **A row rooted where a second rule also answers gates nothing.** The
  narrowed-loop rows were rooted at `.`, so when the narrowing filter was
  mutated away they still passed -- on the store rule, because `.` is the
  checkout root. Rooted at the directory that holds the dirty file, they
  red. Run the mutation before trusting a new guard row.
- **Probing a deny-once tier needs one project per ask.** The bump's flag
  answered `allow` to a second ask of the same shape, and a probe table
  built on one project reported a phantom allow. Strip
  `ESPALIER_MAINTENANCE_MODE` from any env handed to the hook (the test
  conftest does), and pass delete-idiom rows through a file: the guard reads
  the quoted words of a shell `for` list, so a probe command carrying them
  collides with the guard it probes.
- **A "defers to the wall" row that asserts only silence passes on NO tier**
  (DEF-842, 2026-09-18). The nudge's defer rows asserted `not fires`; an
  end-of-options marker that hid the target made the PowerShell wall miss,
  the nudge stayed silent too, and every defer row stayed green under the
  mutation. Each defer row now also asks the hard tier in-process
  (`write_guard._ps_dangerous_reason(...) is not None`), as the Bash defer
  row asks its wall predicate. Silence is what a gap looks like.
- **A rule only one consumer needs goes in a MODE of the shared reader, not
  into the reader.** The binding pre-pass is read by the zone reader, the
  write extractor, the snapshot arm, (since DEF-846) the walls and, through
  the walls since lane 2 (DEF-847), the secret-read leg and both tiers'
  nested-program readers. Two wall-motivated rules edited into it globally
  each broke another consumer:
  a quoted-tilde rewrite let a protected write through a `bash -c` re-parse,
  and a prefix-only binding (`D=~/"a b"`) walled the home directory on the
  walls' reading. `_expand_simple_var_assignments(..., wall=True)` carries
  both; every other reader keeps its older reading, pinned by one test.
- **Grep for the name before defining a module pattern.** A second
  `_PS_RECURSE_SWITCH_RE` went into `_bash_patterns.py` beside an identical
  one 90 lines down; the edit that followed then referenced a name not yet
  defined. One `grep -n '<NAME>'` first.
- **A same-size mutation of a hook module runs stale bytecode** -- canon in
  `docs/SHARP_EDGES.md` ("An earn-the-red snapshot-restore is masked by
  stale bytecode"): the live guard's own import compiled the cache just
  before the edit. Clear `__pycache__` and confirm with `dis`, not `inspect`.
- **Skip what another rung owns, per invocation, or pay twice.** DEF-842's
  PowerShell reader skips an invocation the records' recurse-and-force shape
  matches (`_PS_RECURSIVE_FORCE_RE.search(text, m.start(), m.end())`), so a
  flood of forced operands is not walked a second time; the Bash walls cap
  the inlined reading and cache it per text (`_wall_readings`), because four
  walls and the nudge's deferral asked for the same text.

## A reader that reads the command its own way is the guard's recurring sibling class (2026-09-19)

Lane 2 (DEF-847 / DEF-848, `cb936c0`) fixed one assignment-word defect in the
grammar, and its code review then found the same shape seven more times: a
reader that reads the command ITS OWN way -- raw text, no masker, no binding
pre-pass -- so one text answers differently depending on which reader meets
it. The seven were the symlink, hardlink and relocation readers, the
secret-read leg, the discard snapshot, the directory finder and the
env-prefix target. None was a hard problem; each was a reader written beside
the shared reading without taking it, and each had passed its own review.

Route a new reader through the shared reading instead of fixing it in place.
Three seams in `_bash_patterns.py` own the readings, and a reader takes one
rather than composing a fourth:

- **`_extractor_pair`** for a write-verb reader: `(raw, scan)` -- the capped
  command, continuations spliced, literal bindings inlined, and its masked
  twin of the same length. The reader MATCHES on `scan` and reads each
  operand from `raw` at the match's offsets.
- **`_wall_readings`** for anything that must see a binding the shell
  substitutes: the command as spelled, plus the command with a literal
  binding inlined where that changes it. A verdict on EITHER is the verdict,
  so the inlined reading can only add one.
- **`nested_shell_programs`** for a program the command hands to a shell --
  read over every wall reading since this lane, so a value the shell expands
  into a program is judged where it runs.

The tell is an arm that takes `command` and reaches for `mask_inert_syntax`,
`splice_line_continuations` or a `finditer` of its own: that is a fourth
reading being born. Grep the three seams for the one whose consumers already
ask the question the new arm asks. This is the guard-shaped instance of
[[read-the-neighbours-before-adding-a-sibling]]; its inverse, for when the
shared reading is nearly right, is the word-list lane's bullet (2026-09-18) --
a rule only one consumer needs goes in a MODE of the shared reader, never
into the reader.

## See also

- `docs/external/cc-hook-protocol.md` — pinned external truth for
  the hook contract.
- `bench/corpus/BC-*.json` — class-of-bug catalog. Test additions to
  `tests/test_write_guard.py` or `tests/test_integrity.py::TestKillSwitchScan`
  must have a matching BC entry; `bench/run_benchmark.py` gates
  releases on this.
- `tools/cc/hooks/_hook_contract.py` — shared timing constants
  (STOP_INNER_BUDGET, REFLECT_BUDGET); kept in sync with
  `espalier/hook_contract.py` by parity tests.
- `tools/cc/hooks/_maintenance_mode.py` — the bypass shape every
  friction-only check calls.
