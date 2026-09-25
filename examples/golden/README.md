# Golden example tests

Four runnable, heavily-annotated **reference tests** that demonstrate the
test-design patterns that made this project trustworthy — the *make-it-prove-it*
discipline as exemplars, not prose. Each file is self-contained and runs under
bare `pytest` with **no `espalier` import**, so you can copy any of them into any
repo:

```bash
pytest examples/golden/
```

Each file is named `test_*.py` on purpose: that's the pattern `pytest` collects by
default, so `pytest <dir>` finds them. A test file pytest silently skips (because
it was named `mytest.py` or `G1.py`) is the very first footgun these examples
teach you to avoid — a test that never runs proves nothing.

The header comment in each file is the deliverable as much as the code: it
explains *why the test is golden*, *what failure mode it guards*, and *how to
adapt it* to your own code. Read the header first.

| Pattern | Use when | Guards | File |
|---|---|---|---|
| **G1 — Earn-the-gate + negative corpus** | You wrote a detector/linter and want to prove it flags the real thing *and* stays silent on look-alikes | FAILURE_MODES §13.5 (earn-the-gate) + §13.9 (complacent oracle) | `test_g1_earn_the_gate.py` |
| **G2 — Earn-the-red** | You want proof a test actually catches the bug it targets — watch it go RED on the mutation, GREEN on the fix | FAILURE_MODES §11.11 (earn-the-red is necessary, not sufficient) | `test_g2_earn_the_red.py` |
| **G3 — Closed-loop parity** | A consumer is tested against a hand-written fixture that could silently drift from the real producer output | CONVENTIONS "Closed-loop verification — producer/consumer parity"; BC-041 | `test_g3_closed_loop_parity.py` |
| **G4 — Characterization** | You're about to refactor untested code and need a regression net that pins current behavior (bugs included) | The "characterize before you refactor" discipline (NOT a correctness proof) | `test_g4_characterization.py` |

## How to use this set

- **Starting a new detector/gate?** Copy **G1** — the negative corpus is the part
  beginners skip, and it's what keeps the gate honest.
- **Not sure a test is real?** Apply **G2**: break the code, watch the test fail,
  then revert. A test you've never seen fail is decoration.
- **Wiring a producer to a consumer?** Copy **G3**: feed the producer's real
  output into the consumer instead of a fixture you typed by hand.
- **Inheriting untested legacy code?** Copy **G4** first — pin what it does today
  before you change it, and be honest that it's a regression net, not a proof.

These four are the patterns this repo actually proved. The set stays small on
purpose (signal density) — a new pattern earns a slot only after it has earned
its keep in real use.
