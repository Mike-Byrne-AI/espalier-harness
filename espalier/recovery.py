"""Assess whether an existing Claude Code surface is coherent enough to resume work.

Thin compatibility wrapper: delegates to tools/cc/session_resume.py so
both the slash command and the CLI recovery check share one engine.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from espalier import surface_contract


def _load_session_resume():
    """Load session_resume.py without making tools/cc an espalier dep.

    Editable/source install: ``tools/cc/`` is a sibling of ``espalier/``.
    Wheel install: the script ships as package-data under
    ``espalier/_vendor/cc/`` — ``tools/cc`` is not a top-level package in
    the wheel, since shipping it there would squat the generic ``tools``
    import name in every environment that installed Espalier.
    """
    here = Path(__file__).resolve().parent  # espalier/
    candidate = here.parent / "tools" / "cc" / "session_resume.py"
    if not candidate.exists():
        candidate = here / "_vendor" / "cc" / "session_resume.py"
    spec = importlib.util.spec_from_file_location("_cc_session_resume", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot locate session_resume.py at {candidate}")
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(module)
    return module


_sr = _load_session_resume()

# Re-export the public API so existing imports keep working:
#   from espalier.recovery import REQUIRED_PATHS, assess_repo_state, render_recovery_report
REQUIRED_PATHS = _sr.REQUIRED_PATHS
assess_repo_state = _sr.assess_repo_state
render_recovery_report = _sr.render_recovery_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess Claude Code repo recovery state")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    # The same question `espalier recover` asks in `cli._resolve_repo_arg`,
    # with the same exit: this entry point resolves its own argument
    # (DEF-763; the sibling `self_hosting.main` crashed on a locked `.claude`).
    unreadable = surface_contract.unreadable_harness_root(args.repo_root)
    if unreadable is not None:
        print(
            f"error: {surface_contract.unreadable_root_sentence(unreadable)}",
            file=sys.stderr,
        )
        return 2
    report = assess_repo_state(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_recovery_report(report), end="")
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
