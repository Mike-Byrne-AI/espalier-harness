# Deleted-Governance-Event Fail-Open (N7)

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Deleted-Governance-Event Fail-Open (N7)"

**What it is:** deleting a whole governance EVENT key from
`.claude/settings.json` silently removes a DENY/blocking gate while every
health signal stays green. The hook *files* stay on disk, so presence checks
pass; the gate is simply never wired, so it never fires.

```jsonc
// before: config_guard wired under ConfigChange (the only settings-change DENY)
"hooks": { "ConfigChange": [ { "hooks": [ { "command": "python3",
            "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/config_guard.py"] } ] } ], ... }
// after a hand-edit / partial upgrade: the key is just gone.
"hooks": { /* no ConfigChange */ ... }
```

The pre-fix detection gap was structural: `ci_guard`'s kill-switch scan loops
`for event, entries in hooks.items()` — it only sees **present** keys, so a
*deleted* key never enters the loop. `doctor` inspected presence + audit +
self-host but never the on-disk event→script wiring. The only canonical-wiring
check (`artifact_parity.structural_diff`) runs on scratch source-vs-wheel
repos, never the adopter's on-disk file. So a deleted `ConfigChange` / `Stop` /
`PreToolUse` key produced **at most a `warn`** from doctor (the settings file
changed → diff drift), never a `fail` — the gate was gone and CI was green.

The sharpest edge: the real-world trigger is an **approved** harness change.
`.claude/settings.json` changes are gated by the protected-path + approval
marker; a legitimate `HARNESS-UPDATE-APPROVED` commit that *accidentally* drops
an event key sails straight through that gate. So the fix is **unconditional**
(approval does not bypass it), exactly like the kill-switch check.

**The fix — one SoT + a completeness oracle on two surfaces:**

1. **SoT** — `espalier.harness_config.GOVERNANCE_BLOCKING_HOOKS` maps each
   blocking hook to the event it must be wired under (`write_guard.py` +
   `plan_guard.py` → `PreToolUse`; `config_guard.py` → `ConfigChange`;
   `stop_gate.py` → `Stop` — exactly the "Can block? Yes" hooks). Validated
   against `CANONICAL_HOOK_WIRING` (each script's event must agree) and the
   4-member set is pinned, so adding a blocking hook forces an oracle update.

2. **`espalier.doctor._check_governance_event_wiring`** (initialized branch) —
   uses the event-aware `surface_contract.discover_executable_hook_wirings`
   (the existing `discover_wired_hooks` flattens events and can't tell a live
   gate from a neutered one, so it cannot see a script wired under the *wrong*
   event). Appends a FAILURE for each blocking
   hook **present on disk** but not wired under its canonical event.

3. **`tools/cc/ci_guard.py`** — an **inline literal mirror**
   (`_GOVERNANCE_BLOCKING_HOOKS`, zero-imports rule) + `scan_missing_governance_events`,
   called **unconditionally** in `run()` (returns 2; approval does not bypass).
   The mirror is parity-pinned to the SoT (`test_ci_guard.py::
   test_governance_mirror_matches_sot`).

**Why the trigger keys on "file on disk":** it models N7 exactly — *the scripts
stay on disk* — and avoids false-positives on a repo that never installed the
harness (no hook files → nothing to check; `{"hooks": {}}` passes). The
complementary case (the hook **file** deleted too) is caught by a different,
pre-existing layer: all four gates are `cc/PACK_MANIFEST.txt`-promised, so
`run_cc_surface_gate` flags the missing file (→ doctor `audit did not pass`),
and `tools/cc/hooks/` is a protected path for `ci_guard`. No single-deletion
hole.

## "Wired" is not enough — the gate must be EXECUTABLE

A path-present check is too weak. A blocking gate can be **dead while its
script path is still textually present** — every one a fail-OPEN the path-only
check rubber-stamped:

- a no-op command carrying the path as bait: `command: "true"` (path in `args`),
  or shell `": <path>"` / `"echo <path>"` / `"true # python <path>"`;
- `type` is not EXACTLY `"command"` — **including absent**. Measured on real
  Claude Code 2.1.247 (marker rig, every negative bracketed by a control that
  fired): an untyped entry does not run, and it **voids the entire
  `settings.json` hooks block** — a correctly-typed hook in another entry, and
  even under another event, stops firing too, with nothing on stderr. So one
  stray hook the adopter wrote disables every governance gate at once.
  (This doc previously recorded `absent → command`, CC's apparent default;
  that was never pinned against the platform and was a fail-OPEN.)
- a **stale-copy path** (`.claude/hooks/<script>.py`) wired while the canonical
  `tools/cc/hooks/<script>.py` sits unused on disk;
- a **tool-excluding matcher** (`"Bash"`/`"Read"`/`"Task"`) — the gate is wired
  under the right event but CC filters it out before Write/Edit ever reach it;
- an **interpreter flag** that makes the path inert `sys.argv`: `python3 -c pass
  <path>` / `python3 -m pytest <path>` — python runs the flag, never the script;
- any **shell control operator** that short-circuits the run: `false && python3
  <path>`, `python3 -c '' || …`, `python3 --version ; cat <path>`.

The decisive lesson (the repo's own *convergence-is-an-angle-set-property*
doctrine): statically deciding "does this arbitrary shell string execute the
guard" is **undecidable** — each round produced another construct. So the oracle
stops parsing shell and instead **whitelists the one canonical exec form,
failing CLOSED on everything else** (`surface_contract._hook_executes_script_path`
+ the `ci_guard` mirror). A gate counts as *effectively wired* only when:

1. `type` is EXACTLY `"command"` (absent does NOT count — see above; an
   untyped entry anywhere voids the whole file);
2. `command` is a **bare python interpreter** (a single `python`/`python3`/`py`
   token, no spaces — so any shell-form `command` string is rejected outright);
3. `args[0]` (after stripping `${CLAUDE_PROJECT_DIR}/` and a leading `./`) is the
   `.py` — python's *program* slot, so `-c`/`-m`/flag prefixes that displace the
   script are rejected;
4. the resolved path equals the canonical `tools/cc/hooks/<script>`; and
5. the matcher is **at least as broad as the hook's CANONICAL matcher**
   (`matcher_covers_canonical`, derived per-hook from `CANONICAL_HOOK_WIRING`):
   `write_guard` canonical `"*"` → the deployed matcher must also fire on ALL
   tools (its kill-switch must reach Task/Bash/MCP/…); `plan_guard` canonical
   `Write|Edit|NotebookEdit` → must `fullmatch`-cover those mutation tools
   (`fullmatch`, not `search`, so a substring-only matcher fails CLOSED). A
   `write_guard` matcher that *covers mutations* but isn't fire-on-all (e.g.
   `Write|Edit|NotebookEdit`) silently collapses the kill-switch's reach — the
   per-hook check catches it; a generic covers-mutations check did not.

This is structurally convergent: if all five hold, CC genuinely runs
`python <canonical-script>` and the guard fires — there is no dead-gate-reads-as-
wired residual. The doctor and `ci_guard` legs are byte-parity on the extractor
(`tests/test_surface_contract.py::test_doctor_ci_extractor_parity`) and on the
canonical matchers (`test_canonical_matcher_mirror_matches_chw`), and the
governance check also runs in doctor's **source-checkout** branch (a forced
`--mode source-checkout` on a present, neutered settings.json must not skip it).

> **⚠ The count that used to open this paragraph was wrong, and the sentence
> was enforced by nothing.** It read "All seven settings.json readers…". Measured
> 2026-08-26 by AST census: **sixteen** settings-shaped readers, of which **six**
> decoded plain UTF-8 — including `cleanup._unwire_espalier_hooks`, where a
> UTF-16 file made `uninstall` silently leave every Espalier hook wired in the
> adopter's settings (driven: 0 unwired vs 12). A prose count cannot notice the
> next reader. `tests/test_settings_reader_bom_contract.py` now enforces the
> property instead: every settings reader routes through a BOM helper or carries
> a `# bom-exempt:` comment saying why not.

**Fail-CLOSED on an unprovable file, BOM-tolerant.** A present
settings.json the oracle cannot prove wires the gates — no `hooks` key, non-dict
`hooks`, malformed JSON, non-dict top-level — is the *most complete* neutering
(all gates dead at once); both legs build an empty wiring set and **fall through
to the completeness loop** (flag every deployed gate), never early-return `[]`.
Settings.json readers decode through a shared BOM-detecting helper
(`decode_bom` — handles **UTF-8/16/32 BOMs**, incl. PowerShell `Out-File`'s
UTF-16 default; one copy per isolation domain — `surface_contract.decode_bom`,
`tools/cc/_json_safe.decode_bom`, `ci_guard._ci_decode_bom` — parity-pinned) so
a BOM'd (or any-encoding) byte-canonical settings.json neither false-flags a
healthy repo nor lets a BOM'd `disableAllHooks`/`bypassPermissions` evade
enforcement: the two offline oracle legs (`surface_contract.
_load_settings_hooks_cfg`, `ci_guard._scan_settings_for_missing_governance_events`),
the CI kill-switch scan (`ci_guard._scan_settings_file_for_kill_switch`), the
python-resolver and init-merge readers — **and the two RUNTIME kill-switch
readers** (`_integrity._load_settings_json` feeding write_guard's live PreToolUse
DENY, and `config_guard`'s inline reader). A **dangling-symlink** settings.json (lexists
but not exists — a per-machine target absent on CI) is treated as
present-but-broken (fail CLOSED → flag the gates), not absent. A sibling Class-B
crash in `doctor._check_python_resolver` (non-dict settings → `AttributeError`)
was guarded too, and the `espalier/` Class-B loaders
(`analyze`/`cli`/`cognitive_blueprint`/`freshness`/`proofs`/`diffing`) were
guarded + folded into the malformed-JSON gate's AST walk
([`malformed-json-fail-open.md`](malformed-json-fail-open.md)).

**Earn-the-red:** `harness_repo` was made a faithful initialized harness (all
four gates wired); deleting `ConfigChange` from it left doctor at `warn` on the
pre-fix tree and ci_guard at `approval marker present -- allowed` (rc 0) — the
fail-open reproduced — then `fail` / rc 2 after the fix. See
`tests/test_doctor.py::TestN7GovernanceEventWiring` and
`tests/test_ci_guard.py::TestN7GovernanceEventCompleteness`.

**Known-limits (documented, all fail-CLOSED — a false-positive that flags a
working gate, never a fail-open):**
- **Only the canonical exec form is recognized.** Any non-canonical-but-
  functional wiring is conservatively flagged ("re-wire via `espalier init` /
  use exec form"): a genuine shell-form `command: "python3 <path>"`, an
  `env python3 <path>` wrapper, interpreter flags (`-X`/`-E`/`-S`) before the
  script, an absolute (non-`${CLAUDE_PROJECT_DIR}`) path, or an embedded `/./` /
  `/../` in the path (only a *leading* `./` is normalized). This is the
  deliberate trade for convergence — recognizing arbitrary shell is undecidable
  (see above), so the oracle trusts exactly one shape.
- `ci_guard` checks only the project `.claude/settings.json` (the committed,
  shipped governance contract); `settings.local.json` is a gitignored local
  override and Claude Code hook arrays merge additively (local cannot *delete* a
  project event).

See ESPALIER_MEMORY.md and `docs/RELEASE_FINDINGS_LEDGER.md` for the execution record.
