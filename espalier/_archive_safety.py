"""Safe-extraction wrappers for tarfile and zipfile.

Shared so that ``espalier/`` modules and downstream consumers can reuse the same
member-validation discipline without re-implementing it.

The public-shaped names (``safe_extract_tar``, ``safe_extract_zip``)
signal stable consumer surface; the private member-path validator stays
prefixed because it is an implementation detail.

Class-of-bug background: ZIP-slip / tarbomb (``bench/corpus/BC-010``).
``ZipFile.extractall`` has no ``filter=`` analog, so a manual member
sweep is the only defense. Python 3.12+'s ``tarfile.data_filter``
covers the tar case structurally; the manual sweep here keeps 3.10 /
3.11 paths from regressing.
"""
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path


def _check_member_path(name: str, dest_resolved: Path, dest_prefix: str) -> None:
    """Reject members whose resolved path escapes ``dest_resolved``.

    ``dest_prefix`` must be the forward-slash form of ``dest_resolved``
    with a trailing ``/``. Callers compute it once and reuse across
    every member to avoid per-call string work.
    """
    member_path = (dest_resolved / name).resolve()
    member_str = str(member_path).replace("\\", "/")
    if member_str != str(dest_resolved).replace("\\", "/") and not member_str.startswith(dest_prefix):
        raise ValueError(
            f"refusing extraction of {name!r} -- path escapes {dest_resolved}"
        )


def safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    """Extract a tarfile while rejecting path-traversal and absolute-path members.

    Python 3.12+ ships a built-in ``data`` filter for ``extractall``;
    prefer it when available. For 3.10 / 3.11 compatibility, each
    member's resolved path is validated against ``dest`` before
    extraction.
    """
    dest_resolved = dest.resolve()
    dest_prefix = str(dest_resolved).replace("\\", "/").rstrip("/") + "/"
    for member in tf.getmembers():
        try:
            _check_member_path(member.name, dest_resolved, dest_prefix)
        except ValueError as exc:
            raise tarfile.TarError(str(exc)) from exc
    if hasattr(tarfile, "data_filter"):
        tf.extractall(dest, filter="data")
    else:
        tf.extractall(dest)  # noqa: S202 -- members pre-validated above; Python <3.12 has no filter= kwarg


def safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zipfile after validating each member resolves inside ``dest``.

    ``zipfile.ZipFile.extractall`` has no ``filter=`` analog (parallels the
    tarfile helper above). Same bug class, same fix shape.
    """
    dest_resolved = dest.resolve()
    dest_prefix = str(dest_resolved).replace("\\", "/").rstrip("/") + "/"
    for name in zf.namelist():
        try:
            _check_member_path(name, dest_resolved, dest_prefix)
        except ValueError as exc:
            raise zipfile.BadZipFile(str(exc)) from exc
    zf.extractall(dest)  # noqa: S202 -- members pre-validated above
