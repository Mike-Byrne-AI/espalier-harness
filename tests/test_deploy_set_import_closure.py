"""Every first-party sibling import inside a deployed script must be REACHABLE
at runtime for that script's directory — not merely present somewhere in the
flattened deploy set.

Mechanizes the prose deploy-closure comments at espalier/managed_paths.py.
Catches the failure class where a deployed script gains a sibling import that
init does not deploy (a fresh adopter's subprocess then crashes silently),
closing the presence-only gap that test_init_fresh_hooks.py leaves for tool
scripts.

Two sharpenings over the original membership check:

* **Reachability, not membership** (I1). A ``tools/cc/`` script and a
  ``tools/cc/hooks/`` script do not share a ``sys.path``: a script sees its
  OWN dir, and reaches the sibling dir only if it inserts it explicitly
  (``parent / "hooks"`` for tools→hooks, ``parent.parent`` for hooks→tools).
  A cross-dir import of an otherwise-deployed module still crashes at runtime
  without that shim — membership in the flattened set says nothing about it.
* **The vendored ship surface, not the dev tree** (F3). A fresh adopter never
  receives ``tools/cc/``; ``espalier init`` copies the vendored byte-copy under
  ``espalier/_vendor/cc/`` (``cli._deploy_source_path`` on the wheel branch).
  The guard globs its module universe and reads its analyzed scripts from the
  vendored tree — the surface that actually ships — so its correctness no
  longer rests on ``test_vendor_cc_parity`` holding. The trees are byte-
  identical today, so the live assertion stays GREEN either way.
"""
from __future__ import annotations

import ast
from pathlib import Path

from espalier.cli import INIT_HOOK_SCRIPTS, INIT_TOOL_SCRIPTS

REPO_ROOT = Path(__file__).resolve().parent.parent

# F3: the ship surface `espalier init` copies to an adopter's tools/cc/ — NOT
# the dev tree tools/cc/. Byte-identical today (test_vendor_cc_parity), but the
# guard reasons about what ships, independent of that parity holding.
_VENDOR_CC = REPO_ROOT / "espalier" / "_vendor" / "cc"
_VENDOR_HOOKS = _VENDOR_CC / "hooks"

# First-party sibling modules, partitioned by the directory they live in. A
# hooks/ script reaches hooks-dir modules via its own dir; a tools/cc/ script
# reaches tools/cc-dir modules via its own dir. Crossing dirs needs a sys.path
# shim (see closure_violations).
_HOOKS_MODULES = {p.stem for p in _VENDOR_HOOKS.glob("*.py")}
_TOOLS_MODULES = {p.stem for p in _VENDOR_CC.glob("*.py")}
_LOCAL_MODULES = _HOOKS_MODULES | _TOOLS_MODULES

# Basenames actually shipped by `espalier init`, partitioned by deploy dir.
_HOOKS_DEPLOYED = {Path(s).stem for s in INIT_HOOK_SCRIPTS}
_TOOLS_DEPLOYED = {Path(s).stem for s in INIT_TOOL_SCRIPTS}


def _vendor_path(rel: str) -> Path:
    """Map a ``tools/cc/<rest>`` deploy-set entry to its vendored source."""
    rest = rel.replace("\\", "/").split("tools/cc/", 1)[1]
    return _VENDOR_CC / rest


def _sibling_imports(path: Path) -> set[str]:
    """Top-level module names imported by `path` that are first-party siblings.

    Walks the WHOLE tree, so function-local imports (e.g. reflect_protocol's
    deferred `from _json_safe import ...`) are caught — strictly more complete
    than a runtime --help probe.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # `from . import X` (level>0) -> the imported names are the modules.
            if node.level and node.module is None:
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif node.module:
                names.add(node.module.split(".")[0])
    return {n for n in names if n in _LOCAL_MODULES}


def closure_violations(
    script_rel: str,
    script_text: str,
    sibling_imports: set[str],
    hooks_deployed: set[str],
    tools_deployed: set[str],
    hooks_modules: set[str],
    tools_modules: set[str],
) -> list[str]:
    """A violation = a sibling import unreachable at runtime for this script's dir.

    Same-dir import: reachable via the script's own dir on ``sys.path`` — only
    requires the module be deployed in THIS dir's deploy set.
    Cross-dir import: requires (a) the module be deployed in the OTHER dir AND
    (b) the script text insert the other dir on ``sys.path`` (the shim).
    Membership in the flattened deploy set is NOT reachability — the fail-open
    this predicate closes: ``_hook_utils`` (a hooks/ module) IS deployed, so a
    ``tools/cc/`` script importing it bare passes a membership check yet crashes
    in a fresh adopter's subprocess.
    """
    in_hooks = "/hooks/" in "/" + script_rel.replace("\\", "/")
    same_modules = hooks_modules if in_hooks else tools_modules
    same_deployed = hooks_deployed if in_hooks else tools_deployed
    cross_modules = tools_modules if in_hooks else hooks_modules
    cross_deployed = tools_deployed if in_hooks else hooks_deployed
    # The sys.path shim a script must contain to reach the OTHER dir. hooks →
    # tools/cc inserts `...parent.parent`; tools/cc → hooks inserts
    # `...parent / "hooks"` (reflect_protocol.py:205). Require a real sys.path
    # insertion of the cross dir, not just the anchor token.
    if in_hooks:
        has_shim = "sys.path" in script_text and "parent.parent" in script_text
        shim_desc = '`parent.parent` sys.path shim'
    else:
        has_shim = "sys.path" in script_text and '/ "hooks"' in script_text
        shim_desc = '`parent / "hooks"` sys.path shim'

    out: list[str] = []
    for sib in sorted(sibling_imports):
        if sib in same_modules:
            # Same-dir: reachable via the script's own dir — needs only that the
            # module ship in this dir's deploy set.
            if sib not in same_deployed:
                out.append(
                    f"{script_rel}: same-dir sibling '{sib}' is NOT in this dir's "
                    f"deploy set — a fresh adopter would crash silently."
                )
        elif sib in cross_modules:
            if sib not in cross_deployed:
                out.append(
                    f"{script_rel}: cross-dir import '{sib}' is NOT in the other "
                    f"dir's deploy set — a fresh adopter would crash silently."
                )
            elif not has_shim:
                out.append(
                    f"{script_rel}: imports cross-dir sibling '{sib}' without the "
                    f"{shim_desc} — reachable in the dev checkout but crashes at "
                    f"runtime in a fresh adopter's subprocess (membership is not "
                    f"reachability)."
                )
        else:
            out.append(
                f"{script_rel}: sibling import '{sib}' is in no deploy set."
            )
    return out


def test_every_deployed_script_sibling_import_is_also_deployed():
    violations: list[str] = []
    for rel in (*INIT_HOOK_SCRIPTS, *INIT_TOOL_SCRIPTS):
        if not rel.endswith(".py"):
            continue  # the .cmd statusline shim (DEF-729) imports nothing
        script = _vendor_path(rel)
        script_rel = script.relative_to(REPO_ROOT).as_posix()
        violations.extend(
            closure_violations(
                script_rel,
                script.read_text(encoding="utf-8"),
                _sibling_imports(script),
                _HOOKS_DEPLOYED,
                _TOOLS_DEPLOYED,
                _HOOKS_MODULES,
                _TOOLS_MODULES,
            )
        )
    assert not violations, "Deploy-set import closure broken:\n" + "\n".join(violations)


def test_closure_flags_unshimmed_cross_dir_import():
    """The witness the guard never had (I1). A membership-only predicate MISSES
    an un-shimmed cross-dir import because the module IS deployed; the
    reachability predicate flags it, and clears the SAME import once shimmed.
    Reverting closure_violations to `sib not in deployed` reds this test."""
    hooks_modules = {"_hook_utils", "session_start"}
    tools_modules = {"reflect_protocol", "_paths"}
    hooks_deployed = {"_hook_utils", "session_start"}
    tools_deployed = {"reflect_protocol", "_paths"}

    # A tools/cc/ script importing a hooks-dir sibling (_hook_utils, which IS
    # deployed) with NO sys.path shim -> unreachable at runtime -> violation.
    unshimmed = closure_violations(
        "tools/cc/reflect_protocol.py",
        "import _hook_utils\n",
        {"_hook_utils"},
        hooks_deployed,
        tools_deployed,
        hooks_modules,
        tools_modules,
    )
    assert unshimmed, (
        "fail-open: a membership-only predicate misses an un-shimmed cross-dir "
        "import (the module IS deployed) — this is the witness the guard lacked"
    )
    assert "without the" in unshimmed[0]

    # The SAME import WITH the `parent / "hooks"` shim -> reachable -> clean.
    shimmed_text = (
        'hooks_dir = Path(__file__).resolve().parent / "hooks"\n'
        "sys.path.insert(0, str(hooks_dir))\n"
        "import _hook_utils\n"
    )
    shimmed = closure_violations(
        "tools/cc/reflect_protocol.py",
        shimmed_text,
        {"_hook_utils"},
        hooks_deployed,
        tools_deployed,
        hooks_modules,
        tools_modules,
    )
    assert not shimmed, f"a shimmed cross-dir import must be clean: {shimmed}"

    # `/ "hooks"` present for an unrelated reason (a log path) but with NO
    # sys.path insertion -> still unreachable -> must be flagged. The anchor
    # token alone is not the shim; requiring sys.path closes the born-weak twin
    # of this arm (a bare-anchor false-green the tools->hooks arm once had).
    anchor_only = closure_violations(
        "tools/cc/reflect_protocol.py",
        'LOG_DIR = Path(__file__).resolve().parent / "hooks"\nimport _hook_utils\n',
        {"_hook_utils"},
        hooks_deployed,
        tools_deployed,
        hooks_modules,
        tools_modules,
    )
    assert anchor_only and "without the" in anchor_only[0], (
        "anchor token present but no sys.path insertion — must still flag; the "
        "anchor alone is not reachability"
    )

    # And a hooks/ script reaching tools/cc/ without the parent.parent shim.
    hook_unshimmed = closure_violations(
        "tools/cc/hooks/config_guard.py",
        "import _json_safe\n",
        {"_json_safe"},
        hooks_deployed,
        tools_deployed | {"_json_safe"},
        hooks_modules,
        tools_modules | {"_json_safe"},
    )
    assert hook_unshimmed and "without the" in hook_unshimmed[0]


def test_closure_guard_analyzes_vendored_ship_surface_not_dev_tree():
    """F3: the guard's module universe and analyzed scripts resolve under the
    vendored deploy tree (what ships), not the dev tree. A regression that
    re-points the glob root at tools/cc/ reds here."""
    p = _vendor_path("tools/cc/hooks/session_start.py")
    posix = p.as_posix()
    assert "espalier/_vendor/cc/hooks/session_start.py" in posix, posix
    assert "/tools/cc/" not in posix, posix
    assert p.exists()
    # The module universe is drawn from the vendored tree, partitioned by dir.
    assert _HOOKS_MODULES == {q.stem for q in _VENDOR_HOOKS.glob("*.py")}
    assert _TOOLS_MODULES == {q.stem for q in _VENDOR_CC.glob("*.py")}
    assert "_hook_utils" in _HOOKS_MODULES  # a hooks-only module, in the universe
