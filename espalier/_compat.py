"""Compatibility shims for cross-version stdlib support."""
from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

__all__ = ["tomllib"]
