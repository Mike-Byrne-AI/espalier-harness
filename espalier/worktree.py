"""Generate git worktree lane plans for parallel work with explicit ownership."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git_branch(repo_root: Path) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(repo_root), "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", check=False)
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return "main"
    branch = proc.stdout.strip()
    return branch or "main"


def build_worktree_plan(repo_root: Path) -> dict:
    root_name = repo_root.resolve().name.replace(" ", "-")
    base_branch = _git_branch(repo_root.resolve())
    lanes = [
        {"name": "lane-1-control-plane", "branch": f"{base_branch}-lane-control"},
        {"name": "lane-2-feature", "branch": f"{base_branch}-lane-feature"},
        {"name": "lane-3-review", "branch": f"{base_branch}-lane-review"},
    ]
    commands = [
        f"git -C {repo_root.resolve()} worktree add ../{root_name}-lane-control -b {base_branch}-lane-control",
        f"git -C {repo_root.resolve()} worktree add ../{root_name}-lane-feature -b {base_branch}-lane-feature",
        f"git -C {repo_root.resolve()} worktree add ../{root_name}-lane-review -b {base_branch}-lane-review",
    ]
    return {"repo_root": str(repo_root.resolve()), "base_branch": base_branch, "lanes": lanes, "commands": commands}


def render_worktree_plan(plan: dict) -> str:
    lines = [
        "WORKTREE PLAN",
        "=============",
        f"Repo root: {plan['repo_root']}",
        f"Base branch: {plan['base_branch']}",
        "",
        "Suggested worktree commands:",
    ]
    lines.extend(f"- {cmd}" for cmd in plan["commands"])
    return "\n".join(lines).rstrip() + "\n"
