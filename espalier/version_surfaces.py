"""Single source of truth for every file that carries the release version
literal. The release gate, the bump checklist, and the parity test all
consume this registry so adding a new version surface extends all three
at once (closes the version-SoT proliferation class; FAILURE_MODES §4.5
+ §1.11 gate credibility)."""
from __future__ import annotations

import re
from pathlib import Path

# Each row: (repo_relative_path, compiled_extractor_capturing_group_1)
VERSION_SURFACES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pyproject.toml", re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)),
    ("espalier/__init__.py", re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)),
    ("bench/RESULTS.md", re.compile(r"^espalier version:\s*(\S+)", re.MULTILINE)),
)


def read_surface_version(repo_root: Path, relpath: str, pattern: re.Pattern[str]) -> str | None:
    """Return the version literal a surface declares, or None if absent."""
    path = repo_root / relpath
    if not path.is_file():
        return None
    m = pattern.search(path.read_text(encoding="utf-8"))
    return m.group(1) if m else None
