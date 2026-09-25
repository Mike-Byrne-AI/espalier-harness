"""Atomic file writes for engine-side state (TP-R9 B2/B3/B4).

Mirrors ``tools/cc/hooks/_hook_utils.atomic_write_text`` because
``espalier/`` cannot import from ``tools/cc/`` (isolation rule --
hook scripts are copied verbatim into client repos and run standalone,
so they get their own copy of the helper). Same algorithm; same
guarantees; one addition stated in the docstring below: this copy takes
a ``follow_symlinks`` keyword for the adopter's own files.

Use for every file the engine writes into an adopter's tree -- the JSON
state hook subprocesses read concurrently (``reports/repo_fingerprint.json``,
``reports/harness_config.json``, ``.espalier/integrity.json``), and equally
the cc/ docs, the seeds, the fused tree's stubs and the settings unwire on
uninstall. A whole-file write by any spelling -- ``write_text``,
``write_bytes``, a ``json``/``pickle`` dump, ``open`` in a writing mode, an
``os.open`` with a create flag, a ``shutil`` copy -- anywhere in
``espalier/`` outside the ``_vendor/`` byte mirror and the stdlib-only
``scanners/`` is what
``tests/test_atomic_io.py::TestEveryEngineWriteOfAdopterStateIsAtomic``
reds on; the exemptions carry their reason in its rosters (append-only
logs, lock files, the fused output tree, an ``--out`` that is not a
regular file). ``atomic_write_bytes`` is the verbatim twin for a copy of an
existing file (a settings backup, the CI gate script), where a text
round-trip would rewrite the line endings.

What a write does to the target's IDENTITY -- its mode, a symlink at its
path, a second hardlinked name -- is the contract ``docs/CONVENTIONS.md``
"Atomic whole-file writes" states and ``tests/test_atomic_io.py``
(``TestTargetMode``, ``TestSymlinkedTarget``) pins over every copy; the
copies themselves are a derived roster there (``_REPLACE_WRITERS``), so a
fifth inlined writer reds instead of escaping the contract.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

# Flags for the writer's per-call tempfile: create-exclusive, never following
# a symlink planted at the random name, binary on Windows so the CRT does not
# translate newlines under the text layer. The POSIX-only flags fall back to
# 0, a no-op OR (docs/SHARP_EDGES.md "POSIX-only os.O_* flags need getattr
# guards for Windows").
_TEMPFILE_OPEN_FLAGS = (
    os.O_RDWR | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)


def atomic_write_text(
    path: Path, content: str, *, encoding: str = "utf-8", follow_symlinks: bool = False,
) -> None:
    """Write ``content`` to ``path`` atomically via tempfile + ``os.replace``.

    Concurrent readers (parallel CC sessions, hook subprocesses) see
    either the old contents or the new contents -- never a torn/truncated
    file. The tempfile is created in the target's parent dir so
    ``os.replace`` is on the same filesystem (a requirement of POSIX
    atomicity; NTFS provides equivalent semantics via MoveFileEx).

    Parent directories are created as needed. The tempfile is unlinked
    on failure; on success it has been renamed onto ``path``.

    The target's identity survives the write (DEF-783, DEF-784):

    - MODE: an existing regular file keeps the bits it had (the operator's
      ``chmod +x`` on a hook script, ``chmod g+r`` on a settings file); a
      fresh file gets the mode ``open()`` would give under the process
      umask. The helper imposes no mode of its own. (Windows keeps one
      read-only bit and has no ``fchmod``; the mode leg is a no-op there.)
    - SYMLINK, decided per TARGET, not per copy. By default a symlinked
      target is REPLACED by a regular file: harness state under ``cc/``,
      ``.espalier`` and ``reports/`` is the harness's own, the readers of
      it that refuse a symlink (the plan file's ``read_text_nofollow``, the
      freshness cache's and the statusline's ``O_NOFOLLOW`` opens) can read
      what the write leaves, and no adopter manages harness state by
      dotfiles. ``follow_symlinks=True`` is for the adopter's OWN file -- a
      dotfiles-managed ``.gitignore`` or ``settings.json`` -- and rewrites
      the real file in place, its mode with it, keeping the link; the
      retire and the settings merge, repair, rewire and unwire pass it. The
      tools/cc copies carry no keyword: they write state only.
    - HARDLINK: the new bytes are a new inode, so a second name for the old
      one keeps the old bytes. A property of rename-based atomicity, not a
      defect; the harness never hardlinks its own state.

    The tempfile's visible name is capped at 64 chars so it cannot exceed
    Windows MAX_PATH (260) for an unusually long target filename.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if follow_symlinks:
        # Resolved AFTER the mkdir above: a dangling link into a directory
        # that does not exist fails at the create below instead of creating
        # that directory (a dotfiles checkout not cloned yet); init reports
        # the OSError as a one-line manual step. The tempfile lands beside
        # the REAL file, so a write killed between create and replace can
        # leave a `.<name>.<hex>.tmp` in the linked-to directory.
        path = Path(os.path.realpath(path))
    # Opened with mode 0o666 so the kernel applies the umask -- what open()
    # gives a fresh file -- where tempfile.mkstemp hardcodes 0o600 and every
    # file the harness wrote ended group-unreadable (DEF-783).
    prefix = f".{path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(str(path.parent), prefix + os.urandom(4).hex() + ".tmp")
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
        except PermissionError:
            # NT raises this, not FileExistsError, when a DIRECTORY bears
            # the chosen name (the case tempfile.mkstemp retries); anything
            # else is a real refusal.
            if os.name == "nt" and os.path.isdir(tmp_path):
                continue
            raise
    else:
        raise FileExistsError(f"no free tempfile name beside {path}")
    f = None
    try:
        if hasattr(os, "fchmod"):
            # An existing regular target keeps its bits; a symlink or other
            # non-regular file at the path is not a mode to copy. A refused
            # fchmod leaves the umask mode rather than failing the write.
            try:
                st = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.fchmod(fd, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        # newline="" writes \n verbatim. Default text mode translates \n -> \r\n
        # on Windows, which inflates serialized byte-size (defeating size caps
        # that count \n) and breaks cross-platform byte-parity of hashed JSON
        # state. POSIX is unaffected (os.linesep=\n).
        f = os.fdopen(fd, "w", encoding=encoding, newline="")
        with f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:  # noqa: BLE001 -- clean up tempfile on any failure, then re-raise
        # ANY failure (OSError on replace, TypeError on non-str content,
        # UnicodeEncodeError, even KeyboardInterrupt mid-write) must unlink
        # the tempfile so no orphan is left, then re-raise the original error.
        if f is None:
            # fdopen itself raised (an unknown encoding): the fd is still ours.
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes, *, follow_symlinks: bool = False) -> None:
    """``atomic_write_text`` for bytes: the same tempfile-and-replace, no
    encoding or newline translation, so a copy of an existing file lands
    verbatim or not at all, and the same target-identity contract (mode
    kept, a symlinked target replaced unless ``follow_symlinks``, a
    hardlink severed). Kept as its own body rather than a shared private
    core so the text helper stays byte-identical in shape to the hook-side
    copy it mirrors."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if follow_symlinks:
        path = Path(os.path.realpath(path))
    prefix = f".{path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(str(path.parent), prefix + os.urandom(4).hex() + ".tmp")
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
        except PermissionError:
            if os.name == "nt" and os.path.isdir(tmp_path):
                continue
            raise
    else:
        raise FileExistsError(f"no free tempfile name beside {path}")
    f = None
    try:
        if hasattr(os, "fchmod"):
            try:
                st = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.fchmod(fd, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        f = os.fdopen(fd, "wb")
        with f:
            f.write(data)
        os.replace(tmp_path, path)
    except BaseException:  # noqa: BLE001 -- clean up tempfile on any failure, then re-raise
        if f is None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
