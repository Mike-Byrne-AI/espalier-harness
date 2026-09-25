# The install path can be broken while every test is green — cwd shadowing hides it

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "The Install Path Can Break While Every Test Is Green"

**What it is:** A repo's documented primary install path can be **structurally
broken for a fresh adopter** while the dev machine and the entire test suite
report green. The masking agent is Python's cwd shadowing: when the working
directory *is* the source checkout, `python -m <pkg>` resolves against `sys.path`
regardless of whether the package was ever installed.

**How you hit it:** The README's "govern in place" / "clone a governed repo"
blocks `cd` off the source checkout and then run `python -m espalier init .` —
with **no `pip install` anywhere in the README**. A fresh adopter hits
`No module named espalier` on command 1. It was doubly masked:

- On the dev machine espalier is *not* pip-installed (`pip show espalier` →
  nothing). Commands "work" only because cwd = the checkout. The moment a doc
  `cd`s away, `python -m espalier` fails — which never happens in a normal dev
  session, so it looks fine.
- The **test suite is structurally blind**: every lifecycle test (`test_init`,
  `test_fuse`, `test_doctor`, `test_wheel_install_surface_parity`, …) runs with
  the package already importable. None simulates "adopter hasn't installed yet,
  cwd is their repo." Static review rounds read the prose but never *executed* it
  from a clean cwd.

**How to avoid it:** Before any launch, run the **dynamic first-hour walk** —
fresh clone → fresh venv (no `pip install`) → follow README then QUICKSTART
verbatim → observe. Doing exactly this confirmed RED (`No module named espalier`
from the adopter's cwd, pre-install) → GREEN for both `python -m espalier` and
bare `espalier` after `pip install -e .`.

**Companion constraint:** operator-doc install examples must use bare `python`,
not the version-suffixed spelling — `tests/test_portability_contract.py` reds on
a version-suffixed interpreter token or a `/tmp/` token in
README/commands/agents/CHEAT-SHEET/SHARP_EDGES. Portability belongs in the prose
macOS note, widened to cover `python -m pip`.

**Class signature:** an environment-relative green. Zero blockers across many
rounds of *engine-logic* review says nothing about the least-attacked
first-hour/narrative surface.
