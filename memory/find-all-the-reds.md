# Find all the reds — a masking failure hides the ones behind it

**Status:** active

**Linked from:** `memory/` cool-store, reached via the `memory/CLAUDE.md` router
and sibling cross-links (the `ESPALIER_MEMORY.md` hot index is at its 120-line cap). The
operator-facing **dual** of Standing Principle 7 (*Earn the red*): earn-the-red
says *one green isn't done*; this says *one red isn't the whole story*. Kin to
[[complacent-oracle]] and [[forensically-audit-the-workflow-not-just-output]].

## The principle

A gate is a **sequence**. When something early in the sequence fails hard — a
crash, a timeout, an early `return`, a collection error — it **aborts the run
before the later checks execute**. So the failure set you can see is only ever
the **top layer**. Reading one red and fixing it does **not** mean done: fixing
the mask re-runs the sequence and the *next* layer surfaces. Keep fixing and
re-running until the sequence **completes clean** — not until the first red is
gone. Adopt a *find all the reds* mindset, the same way we already refuse to
trust a single green.

Two traps ride along with this:

1. **The character of a red misleads.** A red wears the costume of whatever
   aborted the run, which is rarely the real problem. A 60-second pytest-timeout
   reads as "a slow test on a busy machine" — a shrug — when underneath it was
   eleven assertion failures plus a noise-scanner false-positive. Always ask
   *why is the red this shape?*, not just *make the red go away*.

2. **A red you've learned to expect is as dangerous as a false green.** A gate
   that always fails the same benign-looking way goes unquestioned. If a "gate"
   has a habitual failure mode you route around, treat that as *the gate has
   never actually run* until proven otherwise.

## The scar that taught it (release matrix, stage 02)

`scripts/final_release_matrix.py` — the Tier-3 publish gate — had **never
passed**, and nobody knew, because a nested-suite meta-test blew a 60s
wall-clock timeout every run. The timeout looked like flakiness; it was a
**mask**. Peeling it back, one layer at a time, each fix revealing the next:

- **Mask:** a `not slow` meta-test that subprocess-spawns the whole suite times
  out under the matrix's compounded load (fixed by stripping the release_check
  opt-in env vars from the suite stages, mirroring `check_tests_pass`'s own
  child-env strip).
- **Layer 1 (revealed):** 11 self-host-only contracts fail — they assert
  full-dev-tree invariants (`ESPALIER_MEMORY.md` anchors, committed-manifest byte-parity,
  `task-packs/` routers) against a shipping export that intentionally prunes
  that content. Gated on the full-dev-tree signal (see below).
- **Layer 2 (revealed by fixing Layer 1):** the release-noise scan's non-git
  filesystem fallback flags **runtime state** (`.espalier-state/`, `*.egg-info/`)
  created by the stage's own extract+install+test cycle — content `git ls-files`
  would never list. Fixed by pruning `is_release_excluded` paths in the fallback.

Only after all three did the stage complete clean. Had we stopped at "fixed the
timeout" or "gated the 11," we'd have shipped believing the gate was green.

## Companion scar: verify the discriminator before you build on it

Mid-fix I asserted `is_self_host_repo(archive) == False` from a **misread `ls`**
and built the Layer-1 gate on it — it was **True** (a source archive ships the
full code *layout*; only the *content* is pruned). A wasted 4-minute matrix run
caught it. The rule that recovered it: **`is_self_host_repo` answers "is this
the project?" (layout: `espalier/`+`tools/cc/`+`bench/`+name+hash), NOT "is this
the full dev working tree?"** The discriminator for the latter is a
tracked-but-`export-ignore`'d sentinel — `ESPALIER_MEMORY.md` is present in the dev tree
and any fresh clone, absent from every shipping export. This is itself a
find-all-the-reds instance: a *premise* is a claim until an oracle confirms it
([[complacent-oracle]]) — evaluate the condition empirically **before** spending
the expensive run, not after.

## How to apply

- When a gate goes red, fix it and **re-run to completion** before believing it.
  The green you want is "the sequence ran end to end with nothing failing," not
  "the red I saw is gone."
- Interrogate the *shape* of a red (timeout / import error / early exit) — it
  usually names the mask, not the defect.
- "Fast earns scrutiny" (Standing Principle 9) applies here: fixing the visible
  red *feels* like done — that feeling is the cue to look for the next layer.
- Earn-the-red (Principle 7) and find-all-the-reds are a pair: the first proves a
  fix does something; the second proves you've *seen the whole failure set*.
