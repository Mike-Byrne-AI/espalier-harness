"""Contract: the ``.espalier-state`` directory name has a single source of truth.

``tools/cc/hooks/_hook_utils.py::STATE_DIR`` is the canonical definition. Every
other hook must reference it -- directly as ``_hook_utils.STATE_DIR`` or via the
canonical ``STATE_DIR = _hook_utils.STATE_DIR`` alias that ``reflect_trigger``
established -- rather than re-spelling the ``".espalier-state"`` literal. A
duplicated literal silently forks the per-session state directory if the SoT is
ever renamed (some hooks write flags, others read them; a drift means a gate
never clears).

Earn-the-red (TP-201 1-A): before consolidation, ``stop_gate``,
``subagent_stop``, ``session_start`` and ``post_write_check`` each carried their
own ``".espalier-state"`` literal (4 sites). This test reds on each of them and
goes green once every reference points at the SoT.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
STATE_DIR_LITERAL = ".espalier-state"
SOT_MODULE = "_hook_utils.py"


def _hook_modules() -> list[Path]:
    """All hook scripts except the SoT module itself (``_vendor`` lives
    under ``espalier/`` so it is already outside ``HOOKS_DIR``)."""
    return sorted(p for p in HOOKS_DIR.glob("*.py") if p.name != SOT_MODULE)


class TestStateDirSingleSource:
    def test_sot_defines_the_literal(self):
        """``_hook_utils.py`` is the one place the literal is allowed to live."""
        src = (HOOKS_DIR / SOT_MODULE).read_text(encoding="utf-8")
        assert (
            f'"{STATE_DIR_LITERAL}"' in src or f"'{STATE_DIR_LITERAL}'" in src
        ), "expected the canonical STATE_DIR literal to live in _hook_utils.py"

    def test_no_other_hook_respells_the_literal(self):
        """No hook other than the SoT may hard-code the ``.espalier-state`` value.

        Walks string-constant AST nodes -- not comments, and not a substring
        inside a longer docstring -- so a real value literal is caught while a
        prose mention like ``.espalier-state`` in a docstring is not.
        """
        offenders: list[str] = []
        for path in _hook_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == STATE_DIR_LITERAL:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, (
            "these hooks re-spell the STATE_DIR literal instead of using "
            f"_hook_utils.STATE_DIR: {offenders}"
        )


class TestColdOpenFlagSingleSource:
    """Contract (TP-242): the ``cold_open_pending`` flag literal has a single
    source of truth -- ``_hook_utils.py::COLD_OPEN_FLAG``. The SessionStart
    producer and the task_router consumer both IMPORT it; neither may re-spell the
    literal, or the one-shot baton silently forks (the producer writes one name,
    the consumer reads another, and the orientation never fires). Sister contract
    of TestStateDirSingleSource -- the drift-proof claim the design rests on, made
    mechanical.
    """

    LITERAL = "cold_open_pending"

    def test_sot_defines_the_literal(self):
        """``_hook_utils.py`` is the one place the flag literal is allowed to live."""
        src = (HOOKS_DIR / SOT_MODULE).read_text(encoding="utf-8")
        assert (
            f'"{self.LITERAL}"' in src or f"'{self.LITERAL}'" in src
        ), "expected COLD_OPEN_FLAG's literal to live in _hook_utils.py"

    def test_no_other_hook_respells_the_literal(self):
        """No hook other than the SoT may hard-code ``cold_open_pending`` -- the
        producer and consumer must import ``COLD_OPEN_FLAG``."""
        offenders: list[str] = []
        for path in _hook_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == self.LITERAL:
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, (
            "these hooks re-spell the cold_open_pending literal instead of "
            f"importing _hook_utils.COLD_OPEN_FLAG: {offenders}"
        )
