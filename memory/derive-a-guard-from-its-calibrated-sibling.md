# Derive a guard from its calibrated sibling, don't author it fresh

**Status:** active
**Linked from:** [a-packs-prescribed-fix-code-is-a-claim](a-packs-prescribed-fix-code-is-a-claim.md) (kin cross-link); `docs/STANDING_PRINCIPLES.md` §8 is the canon this inverts.
**Kin:** [a-packs-prescribed-fix-code-is-a-claim](a-packs-prescribed-fix-code-is-a-claim.md) —
that one says *test the snippet*; this one says *you should not have written the
snippet*. See "Not the same failure".
**Canon:** `docs/STANDING_PRINCIPLES.md` §8 (class-fix scope) — this is §8 **read backwards**.

When a guard needs to solve a sub-problem, **grep for a module that already
solves it before writing a new one.** A freshly authored pattern is not neutral
— it is a *regression against whatever calibrated version already exists*,
because the existing one has absorbed every edge case someone hit and fixed,
and the new one has absorbed none of them.

§8 says *scope a class fix to every shipped surface*. The inverse failure is
just as expensive and much less visible: **re-solving a solved problem, worse,
in a new place.** Nothing reds. There is no drift to detect — the two
implementations were never the same to begin with.

## Attested (TP-414, 2026-08-03)

A pack prescribed a fresh command-position anchor, `_CMD_POS`, for
`tools/cc/hooks/_bash_patterns.py`. Measured against the real hook, applying it
as written **converted 18 genuine protected-zone writes from DENY to ALLOW** —
including a symlink forgery of `cc/blueprints/latest.json`, which is the exact
threat the module's own comment says that deny exists to stop.

Three independent causes. **All three were already solved** in
`tools/cc/hooks/write_guard.py::_HARNESS_ENV_PREFIX_RE`, one file over:

| the fresh version | the calibrated sibling |
|---|---|
| separators `[;\|&\n]` | `` [;&\|\n(`{] `` — includes `(`, backtick, `{`, each a real command position |
| wrappers `(?:sudo\|command\|env)\s+` | `(?:env\|sudo)(?:[ \t]+-\S+)*[ \t]+` — flag-tolerant |
| authored from scratch | exercised by the release-gating benchmark |

Rewritten as a **derivation** from that sibling plus measured extensions, the
same population gave **0 regressions and removed 10 of 10 measured false
positives**.

## Not the same failure as "prescribed code is a claim"

They stack, and the responses differ:

| | prescribed-code-is-a-claim | this |
|---|---|---|
| the defect | the snippet was never executed | the snippet should never have been authored |
| the fix | run it against live data before adopting | find the sibling and derive from it |
| what it costs you if missed | one wrong regex, caught on first run | a second, permanently divergent implementation nobody compares |

Testing the fresh `_CMD_POS` would have caught the 18 bypasses. It would **not**
have told you a better grammar already existed twenty lines away in a file the
same guard imports.

## The check

- Before authoring any pattern/parser/normaliser: **grep the sibling modules for
  the same sub-problem.** "Does something here already decide where a command
  starts / what a token is / how a path normalises?"
- If a sibling exists, **derive**, and say so in the commit message so the next
  reader knows the two are meant to track.
- If you deliberately diverge, **state why in the code**, or the divergence
  reads as an oversight to everyone who finds it later.
- **Prefer the bench-exercised version even when it looks uglier.** Its
  ugliness is usually a list of edge cases you have not thought of yet.

## Generalisation

The strongest signal that you are about to make this mistake is the feeling
that the sub-problem is small: *"I just need to know if the verb is at the start
of a command."* Sub-problems that feel small are exactly the ones already solved
somewhere in a mature codebase — and exactly the ones where a fresh solution
looks obviously correct and is quietly worse.
