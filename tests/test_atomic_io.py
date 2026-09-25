"""Round-9 B2/B3/B4: atomic write contract.

All four copies of the helper (engine-side ``espalier._atomic_io``,
hook-side ``tools/cc/hooks/_hook_utils``, and the copies inlined into
``tools/cc/cognitive_blueprint.py`` and ``tools/cc/execution_plan.py``)
must satisfy:

- writes content correctly under non-contention
- creates parent dirs
- leaves no tempfile on success
- cleans up tempfile on failure
- under concurrent writers, the final file is one of the writers'
  payloads in full -- never a torn/truncated file
- the target's identity survives: an existing regular file keeps its
  mode, a fresh file gets the mode ``open()`` would give, a hardlinked
  sibling keeps the old bytes (``TestTargetMode``); a symlinked target is
  followed by the engine copy and replaced by the tools/cc copies
  (``TestSymlinkedTarget``, the rule per side)

The tools/cc copies are exercised by importing from their directories
the same way Claude Code itself loads them (sys.path insertion).
"""
from __future__ import annotations

import ast
import contextlib
import errno
import importlib
import json
from collections import Counter
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from tests._symlink_support import requires_symlink

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

#: Engine call sites allowed to write a file without the helper, keyed
#: (module, enclosing function) -> (how many raw writes that function holds,
#: why they are not adopter state). Hand-written on purpose: the census
#: DERIVES the actual population from the tree and asserts equality, so a new
#: raw write reds here and so does a stale exemption; the count is asserted
#: too, so a second raw write added inside an exempt function reds as well
#: (driven 2026-09-11 by both reviewers: a settings.json write injected into
#: an exempt function stayed green under a key-only roster).
_ATOMIC_EXEMPT: dict[tuple[str, str], tuple[int, str]] = {
    ("espalier/selfcheck.py", "check_live_deny_path"): (1,
        "throwaway probe settings in a temp dir the check deletes; a torn "
        "write fails the probe, never the adopter"),
    ("espalier/cli.py", "_git_covered_entries"): (1,
        "a scratch git tree the gitignore probe builds and discards; "
        "write_bytes of the adopter's own gitignore bytes"),
    ("espalier/handoff.py", "write_surface_handoff"): (1,
        "the fallback for a caller-supplied --out that is not a regular file "
        "(a FIFO, /dev/stdout), which cannot host a tempfile beside it; the "
        "default path is the helper"),
    ("espalier/release_pack.py", "_atomic_write_zip"): (1,
        "the release archive's own tempfile create (os.open with the "
        "helper's flags and mode): a ZipFile stream no text or bytes helper "
        "can carry, committed with os.replace and rostered as a writer in "
        "_REPLACE_WRITERS, which pins its mode"),
}

#: Engine sites that APPEND (``open(..., "a")``), keyed the same way. An
#: append is not a whole-file write the helper can make: O_APPEND keeps two
#: sessions' rows whole where a read-and-replace would lose one, so each stays
#: an append and cites its reader's tolerance of a torn tail line instead.
#: Kept apart from the whole-file roster so a function that both appends a log
#: and writes a file (``refresh_externals._interactive_loop``) has only its
#: append exempted, never a raw write that regresses beside it.
_APPEND_EXEMPT: dict[tuple[str, str], tuple[int, str]] = {
    ("espalier/fan_out_findings.py", "_corpus_write_lock"): (1,
        "the lock file, opened for append: being opened IS the lock, there "
        "is no content to make whole"),
    ("espalier/freshness.py", "_freshness_write_lock"): (1,
        "the lock file, as above"),
    ("espalier/cli.py", "_handle_gitignore"): (1,
        "init's one append of a marker-bounded block to the adopter's "
        ".gitignore, which cleanup reads back with a tolerant edge. The "
        "append follows a symlinked .gitignore, and so does the retire on "
        "uninstall (cleanup._retire_gitignore_block, through the helper's "
        "engine rule): both verbs edit the adopter's file where it lives"),
    ("espalier/finding_ledger.py", "append_summary"): (1,
        "append-only JSONL log; read_ledger skips a torn tail line"),
    ("espalier/scan_telemetry.py", "append_run"): (1,
        "append-only JSONL history, one append per run; read_history skips "
        "a torn tail line. _trim_history in the same module is a "
        "read-and-replace past the row cap, so a run appending during the "
        "trim loses its own rows -- advisory, and the same cost as a torn "
        "row"),
    ("espalier/refresh_externals.py", "_interactive_loop"): (1,
        "the accept/reject decision log beside the pins, one JSONL row per "
        "decision; advisory history, never read by the engine"),
}

#: Engine sites that COPY a file (``shutil.copy*`` / ``move`` / ``copytree``),
#: the third shape: a copy opens its destination for truncation before the
#: bytes land, so it tears like a raw write. Every copy of adopter state now
#: goes through ``atomic_write_bytes``; what remains builds the fused OUTPUT
#: tree under ``fuse_repos``' rollback, never the adopter's own tree.
_COPY_EXEMPT: dict[tuple[str, str], tuple[int, str]] = {
    ("espalier/fuse.py", "_copy"): (3,
        "overlays the host and harness trees into the fresh fusion output "
        "directory; a failure rolls the whole output back"),
    ("espalier/fuse.py", "fuse_repos"): (2,
        "the history copy and the post-overlay body copy into the same fresh "
        "output tree"),
}

_RAW_WRITE_ATTRS = frozenset({"write_text", "write_bytes"})
_DUMPERS = frozenset({"json", "pickle", "yaml", "toml", "tomli_w"})
_COPIERS = frozenset({"copy", "copy2", "copyfile", "copyfileobj", "move", "copytree"})
_MODE_UNSPELLED = object()  # a mode argument that is not a string literal


def _open_mode(call: ast.Call) -> str | object | None:
    """The mode an ``open(...)`` / ``Path.open(...)`` call names: the literal,
    ``_MODE_UNSPELLED`` when a mode is passed but not as a literal, ``None``
    when no mode is passed (a read). The builtin takes the path first and the
    mode second; the method takes the mode first."""
    positional = 0 if isinstance(call.func, ast.Attribute) else 1
    mode_node = call.args[positional] if len(call.args) > positional else None
    for kw in call.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    if mode_node is None:
        return None
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return _MODE_UNSPELLED


def _raw_write_kind(node: ast.AST, constants: dict[str, ast.AST] | None = None) -> str | None:
    """``"write"`` for a whole-file write the helper could make, ``"append"``
    for an ``open(..., "a")``, ``"copy"`` for a ``shutil`` copy or move,
    ``None`` for anything else (a read, the helper). A mode that is not a
    string literal counts as a write: the maintainer spells it plainly or
    rosters it."""
    if not isinstance(node, ast.Call):
        return None
    constants = constants or {}
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in _RAW_WRITE_ATTRS:
            return "write"
        if func.attr == "dump" and isinstance(func.value, ast.Name) and func.value.id in _DUMPERS:
            return "write"
        if func.attr in _COPIERS and isinstance(func.value, ast.Name) and func.value.id == "shutil":
            return "copy"
    if isinstance(func, ast.Attribute) and func.attr == "open" and isinstance(func.value, ast.Name) and func.value.id == "os":
        # os.open takes flag constants, not a mode string. The flags are read
        # from the expression (or the module-level constant it names): a
        # create or write flag is a write, O_APPEND an append, a bare
        # O_RDONLY a read, and flags the census cannot read count as a write
        # (spell them plainly or roster the site). The helper's own tempfile
        # create is skipped by name in _engine_raw_writes; an inlined copy of
        # it elsewhere reds here (driven 2026-09-12: an os.open + os.replace
        # writer in a new module was invisible to every gate).
        flags = node.args[1] if len(node.args) > 1 else None
        for kw in node.keywords:
            if kw.arg == "flags":
                flags = kw.value
        if isinstance(flags, ast.Name) and flags.id in constants:
            flags = constants[flags.id]
        attrs = {
            n.attr for n in ast.walk(flags) if isinstance(n, ast.Attribute) and n.attr.startswith("O_")
        } if flags is not None else set()
        if not attrs:
            return "write"
        if "O_APPEND" in attrs:
            return "append"
        if attrs & {"O_CREAT", "O_WRONLY", "O_RDWR", "O_TRUNC"}:
            return "write"
        return None
    if (isinstance(func, ast.Attribute) and func.attr == "open") or (
        isinstance(func, ast.Name) and func.id == "open"
    ):
        mode = _open_mode(node)
        if mode is None:
            return None
        if mode is _MODE_UNSPELLED:
            return "write"
        if "a" in mode:
            return "append"
        if any(ch in mode for ch in "wx+"):
            return "write"
    return None


def _module_constants(tree: ast.AST) -> dict[str, ast.AST]:
    """Module-level ``NAME = <expr>`` assignments, so an ``os.open`` whose
    flags are a named constant (``_CACHE_OPEN_FLAGS``) is read by the
    constant's expression rather than counted as unreadable."""
    out: dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def raw_write_sites(tree: ast.AST, rel: str) -> Counter[tuple[str, str, str]]:
    """How many raw writes of each kind every function in ``tree`` holds,
    keyed ``(rel, innermost enclosing function, kind)``; ``<module>`` when the
    write is at module level. A count, not a set, so a second raw write
    inside an already-exempt function is visible."""
    found: Counter[tuple[str, str, str]] = Counter()
    constants = _module_constants(tree)

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = node.name
        kind = _raw_write_kind(node, constants)
        if kind is not None:
            found[(rel, owner, kind)] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(tree, "<module>")
    return found


_SKIPPED_TREES = ("espalier/_vendor/", "espalier/scanners/")


def _raw_writes_under(root: Path, prefixes: tuple[str, ...]) -> Counter[tuple[str, str, str]]:
    found: Counter[tuple[str, str, str]] = Counter()
    for py in sorted((root / "espalier").rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if not rel.startswith(prefixes):
            continue
        found |= raw_write_sites(ast.parse(py.read_text(encoding="utf-8")), rel)
    return found


def _engine_raw_writes(root: Path) -> Counter[tuple[str, str, str]]:
    """Walks ``espalier/`` and skips ``_vendor/`` (a byte mirror of
    ``tools/cc``, the hooks' own class), ``scanners/`` (stdlib-only by
    contract, so they cannot import the helper; their ``--out`` dumps are
    maintainer CLI outputs and ``espalier scan`` writes the same reports
    atomically -- pinned by ``test_the_scanners_write_only_from_main``) and
    the helper itself."""
    found: Counter[tuple[str, str, str]] = Counter()
    for py in sorted((root / "espalier").rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if rel.startswith(_SKIPPED_TREES) or rel == "espalier/_atomic_io.py":
            continue
        found |= raw_write_sites(ast.parse(py.read_text(encoding="utf-8")), rel)
    return found


def _sites_of_kind(root: Path, wanted: str) -> dict[tuple[str, str], int]:
    return {(rel, fn): n for (rel, fn, kind), n in _engine_raw_writes(root).items() if kind == wanted}


def non_atomic_engine_writes(root: Path) -> set[tuple[str, str]]:
    """Every engine site that writes a WHOLE file without ``atomic_write_text``."""
    return set(_sites_of_kind(root, "write"))


def append_sites(root: Path) -> set[tuple[str, str]]:
    """Every engine site that appends to a file."""
    return set(_sites_of_kind(root, "append"))


def copy_sites(root: Path) -> set[tuple[str, str]]:
    """Every engine site that copies or moves a file with ``shutil``."""
    return set(_sites_of_kind(root, "copy"))



def _load_hook_helper():
    """Load _hook_utils via sys.path the way Claude Code does."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import _hook_utils  # type: ignore
        return _hook_utils
    finally:
        sys.path.pop(0)


def _load_tools_cc_module(name: str):
    """Load a ``tools/cc/*.py`` script the way its hook callers do (its own
    directory on ``sys.path``); the module inserts its sibling dir itself."""
    sys.path.insert(0, str(REPO_ROOT / "tools" / "cc"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


#: The FOUR source copies of the text writer: the engine's, the hook helper's,
#: and the two inlined into the standalone CLIs. The two ``espalier/_vendor/cc/``
#: mirrors are byte-identical (``test_vendor_cc_parity`` pins them), so they are
#: covered transitively. Every copy is one body shape; the engine's differs by
#: the one statement that resolves a symlinked target (``TestSymlinkedTarget``).
_COPIES = ("engine", "hook", "blueprint", "plan")
_TOOLS_CC_COPIES = tuple(c for c in _COPIES if c != "engine")


def _load_copy(name: str):
    if name == "engine":
        from espalier._atomic_io import atomic_write_text
        return atomic_write_text
    if name == "hook":
        return _load_hook_helper().atomic_write_text
    if name == "blueprint":
        return _load_tools_cc_module("cognitive_blueprint")._atomic_write_text
    if name == "plan":
        return _load_tools_cc_module("execution_plan")._atomic_write_text
    raise ValueError(name)


@pytest.fixture(params=_COPIES)
def atomic_write(request):
    """Parametrised: run every test against all four source copies."""
    return _load_copy(request.param)


def _engine_writers(*, follow_symlinks: bool = False) -> dict[str, object]:
    """The engine's two spellings, adapted to one ``(path, str)`` signature:
    ``atomic_write_bytes`` is the text helper's verbatim twin and carries the
    same target-identity contract, keyword included."""
    from espalier._atomic_io import atomic_write_bytes, atomic_write_text
    return {
        "text": lambda p, s: atomic_write_text(p, s, follow_symlinks=follow_symlinks),
        "bytes": lambda p, s: atomic_write_bytes(p, s.encode("utf-8"), follow_symlinks=follow_symlinks),
    }


@contextlib.contextmanager
def _umask(value: int):
    old = os.umask(value)
    try:
        yield
    finally:
        os.umask(old)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


#: errno values that mean "this filesystem has no hardlinks" (EPERM is what
#: Linux returns for a link across users under fs.protected_hardlinks too).
_NO_HARDLINKS_ERRNOS = frozenset(
    getattr(errno, name) for name in ("EPERM", "EXDEV", "ENOSYS", "EOPNOTSUPP", "ENOTSUP")
    if hasattr(errno, name)
)

#: File modes are a POSIX concept; Windows keeps one read-only bit and has no
#: ``fchmod``, so the mode leg is unverified-on-host there (FAILURE_MODES 13.7).
posix_modes = pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="file modes are POSIX; Windows has no fchmod and one read-only bit",
)


class TestBasicWrite:
    def test_writes_content(self, atomic_write, tmp_path):
        target = tmp_path / "file.json"
        atomic_write(target, '{"a": 1}')
        assert target.read_text(encoding="utf-8") == '{"a": 1}'

    def test_creates_parent_dirs(self, atomic_write, tmp_path):
        target = tmp_path / "nested" / "deep" / "file.json"
        atomic_write(target, "x")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "x"

    def test_overwrites_existing(self, atomic_write, tmp_path):
        target = tmp_path / "file.json"
        target.write_text("old", encoding="utf-8")
        atomic_write(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_temp_left_on_success(self, atomic_write, tmp_path):
        target = tmp_path / "file.json"
        atomic_write(target, "ok")
        # The temp file's prefix matches `.{name[:64]}.` per the helper
        # (the visible name is truncated for Windows MAX_PATH safety).
        leftover = list(tmp_path.glob(f".{target.name[:64]}.*"))
        assert leftover == [], f"tempfile left on disk: {leftover}"

    def test_encoding_respected(self, atomic_write, tmp_path):
        target = tmp_path / "file.txt"
        # Latin-1 fallback shouldn't be silently picked.
        atomic_write(target, "café", encoding="utf-8")
        assert target.read_bytes() == b"caf\xc3\xa9"


class TestFailureCleanup:
    def test_oserror_during_write_does_not_leave_temp(
        self, atomic_write, tmp_path, monkeypatch,
    ):
        """If os.replace raises (e.g., target is a busy directory on Win32),
        the temp file must be cleaned up."""
        target = tmp_path / "file.json"
        target.write_text("seed", encoding="utf-8")

        original_replace = os.replace
        called = {"n": 0}

        def boom(src, dst):
            called["n"] += 1
            if called["n"] == 1:
                raise OSError(13, "permission denied (simulated)")
            return original_replace(src, dst)

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            atomic_write(target, "new")
        # Target untouched
        assert target.read_text(encoding="utf-8") == "seed"
        # No temp leak
        leftover = list(tmp_path.glob(f".{target.name[:64]}.*"))
        assert leftover == []

    def test_non_oserror_during_write_does_not_leave_temp(
        self, atomic_write, tmp_path,
    ):
        """A TypeError (non-str content) raised inside the fdopen block must
        STILL unlink the tempfile — the docstring guarantees cleanup on
        failure, not only on OSError. Pre-fix this leaked a ``.{name}.*.tmp``
        orphan because the cleanup was gated on ``except OSError:`` alone."""
        target = tmp_path / "file.json"
        with pytest.raises(TypeError):
            atomic_write(target, 123)  # non-str -> TypeError inside f.write
        leftover = list(tmp_path.glob(f".{target.name[:64]}.*"))
        assert leftover == [], f"tempfile leaked on non-OSError failure: {leftover}"


class TestConcurrency:
    """Final file must be one writer's content in full, never a mix.

    Pre-fix, ``Path.write_text`` would truncate then write, so a reader
    catching the file mid-write saw either empty or partial bytes. The
    atomic helper closes that window: the rename is the only commit.
    """

    def test_many_writers_produce_one_complete_payload(self, atomic_write, tmp_path):
        target = tmp_path / "racy.json"
        payloads = [json.dumps({"writer": i, "data": "x" * 1000}) for i in range(32)]

        def writer(payload: str) -> None:
            atomic_write(target, payload)

        threads = [threading.Thread(target=writer, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Whatever landed must be a complete valid JSON object — never torn.
        content = target.read_text(encoding="utf-8")
        parsed = json.loads(content)  # raises if torn
        assert parsed in [json.loads(p) for p in payloads]

    def test_commit_is_a_single_atomic_rename_never_in_place(
        self, atomic_write, tmp_path, monkeypatch,
    ):
        """Deterministic atomicity proof — spy the MECHANISM, do not race it
        (concurrency-test-must-be-deterministic). The torn-read window the
        helper closes exists iff the commit is a direct in-place write to the
        target; the guarantee is that the ONLY commit is a single ``os.replace``
        of a tempfile onto ``target``. The sibling many-writers test joins all
        threads before reading, so it never actually observes a torn state and
        stays green even if the helper writes in place — this pins the invariant
        directly instead."""
        target = tmp_path / "state.json"
        calls = {"replace": 0, "direct_write_text": 0}
        real_replace = os.replace
        real_write_text = Path.write_text

        def _spy_replace(src, dst):
            calls["replace"] += 1
            return real_replace(src, dst)

        def _spy_write_text(self, *a, **k):
            if Path(self) == target:  # an in-place write to the target is the bug
                calls["direct_write_text"] += 1
            return real_write_text(self, *a, **k)

        monkeypatch.setattr(os, "replace", _spy_replace)
        monkeypatch.setattr(Path, "write_text", _spy_write_text)
        atomic_write(target, '{"a": 1}')

        assert calls["replace"] == 1, (
            f"atomic commit must be exactly one os.replace, got {calls['replace']}"
        )
        assert calls["direct_write_text"] == 0, (
            "helper must not write the target in place (opens a torn-read window)"
        )
        # And the payload actually landed, complete.
        assert target.read_text(encoding="utf-8") == '{"a": 1}'

    def test_many_writers_no_tempfile_leak(self, atomic_write, tmp_path):
        """After all writers finish, no .tmp files survive in the target dir."""
        target = tmp_path / "racy.json"

        def writer(i: int) -> None:
            atomic_write(target, f"writer-{i}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        leftover = list(tmp_path.glob(f".{target.name[:64]}.*"))
        assert leftover == [], f"leaked temp files after concurrent writes: {leftover}"


class TestHookHelperHasNoEspalierImport:
    """Isolation invariant: the hook-side copy must not pull in espalier.

    ``tools/cc/`` is copied verbatim into client repos and runs standalone.
    Importing from ``espalier/`` would break that contract — and would also
    create a cycle if espalier eventually imports the helper back.

    Use AST walk (not substring grep) so docstring mentions of the word
    ``espalier`` don't false-fire.
    """

    def test_hook_utils_zero_espalier_imports(self):
        import ast
        hu_path = HOOKS_DIR / "_hook_utils.py"
        tree = ast.parse(hu_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("espalier"), (
                    f"from-import: {node.module}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("espalier"), (
                        f"import: {alias.name}"
                    )


class TestExecutionPlanSaveCleanup:
    """``tools/cc/execution_plan.py::_save`` serialises the plan and hands it
    to the module's ``_atomic_write_text`` (the fourth copy, since 2026-09-12;
    before that an inlined tempfile-and-replace of its own shape), so the
    cleanup contract holds end to end: a non-OSError raised while writing
    must STILL unlink the tempfile. Pre-fix the inlined copy caught
    ``except OSError:`` alone and leaked a ``.execution_plan.json.*.tmp``
    orphan on a TypeError. The copy itself is covered by
    ``test_non_oserror_during_write_does_not_leave_temp``; this pins the
    ``_save`` entry point with a non-serialisable plan."""

    def _load_execution_plan(self):
        sys.path.insert(0, str(REPO_ROOT / "tools" / "cc"))
        try:
            import execution_plan  # type: ignore
            return execution_plan
        finally:
            sys.path.pop(0)

    def test_non_oserror_during_save_does_not_leave_temp(self, tmp_path, monkeypatch):
        ep = self._load_execution_plan()
        plan_path = tmp_path / "cc" / "execution_plan.json"
        monkeypatch.setattr(ep, "_plan_path", lambda: plan_path)
        # A non-serializable value -> json.dumps raises TypeError inside the
        # with-block, exactly the path the narrow `except OSError` would miss.
        with pytest.raises(TypeError):
            ep._save({"bad": object()})
        leftover = list((tmp_path / "cc").glob(f".{plan_path.name}.*"))
        assert leftover == [], f"tempfile leaked on non-OSError _save failure: {leftover}"


class TestEveryEngineWriteOfAdopterStateIsAtomic:
    """Engine sites wrote files an adopter relies on -- the settings unwire
    on uninstall, the three cc/ docs, the fused tree's seeds and stubs, the
    surface handoff, the scan baseline and telemetry, a refreshed external
    pin -- with ``Path.write_text``, and copied the CI gate script, the
    workflow and the settings backups with ``shutil.copy2``, so a crash or a
    concurrent reader mid-write saw a half-written file, while the deploy
    beside them already wrote every seed, body and hook script through the
    helper (DEF-348a, driven 2026-09-11: 12 census entries -- 13 call sites,
    ``render_surface.write_required_surface`` writes twice -- outside the
    two scratch exemptions, plus six copies). The census derives the
    population from every tree but ``_vendor/`` and ``scanners/`` and the
    rosters are hand-written with a count and a reason each, so a new raw
    write, a stale exemption and a second write inside an exempt function
    all red."""

    def test_no_engine_write_bypasses_the_helper(self):
        actual = non_atomic_engine_writes(REPO_ROOT)
        expected = set(_ATOMIC_EXEMPT)
        assert actual == expected, (
            f"raw writes not in the exemption roster: {sorted(actual - expected)}; "
            f"stale exemptions: {sorted(expected - actual)}"
        )

    def test_every_append_is_a_known_log_with_a_tolerant_reader(self):
        actual = append_sites(REPO_ROOT)
        expected = set(_APPEND_EXEMPT)
        assert actual == expected, (
            f"appends not in the roster: {sorted(actual - expected)}; "
            f"stale entries: {sorted(expected - actual)}"
        )

    def test_every_copy_builds_the_fused_output_tree(self):
        actual = copy_sites(REPO_ROOT)
        expected = set(_COPY_EXEMPT)
        assert actual == expected, (
            f"shutil copies not in the roster: {sorted(actual - expected)}; "
            f"stale entries: {sorted(expected - actual)}"
        )

    def test_each_exempt_function_holds_exactly_the_raw_writes_its_entry_counts(self):
        """A second raw write added inside an exempt function is the way the
        roster goes blind (driven 2026-09-11: a settings.json write injected
        into check_live_deny_path stayed green under a key-only roster)."""
        drift = []
        for kind, roster in (("write", _ATOMIC_EXEMPT), ("append", _APPEND_EXEMPT), ("copy", _COPY_EXEMPT)):
            counts = _sites_of_kind(REPO_ROOT, kind)
            for key, (expected_n, _reason) in roster.items():
                if counts.get(key) != expected_n:
                    drift.append((kind, key, counts.get(key), expected_n))
        assert not drift, f"(kind, site, found, rostered): {drift}"

    def test_the_scanners_write_only_from_main(self):
        """The census skips ``scanners/`` because they are stdlib-only by
        contract and cannot import the helper. That skip is a prefix, so pin
        its premise: every raw write in the subtree is a CLI ``--out`` dump
        inside ``main`` (driven 2026-09-11: a scanner writing reports/ from
        another function stayed green under the bare skip)."""
        writers = {(rel, fn) for (rel, fn, _k) in _raw_writes_under(REPO_ROOT, ("espalier/scanners/",))}
        assert writers, "no scanner writes at all -- the pin's premise vanished, re-derive it"
        strays = sorted(w for w in writers if w[1] != "main")
        assert not strays, f"scanner writes outside main, invisible to the engine census: {strays}"

    def test_the_census_sees_every_raw_write_shape_and_nothing_else(self):
        """Vacuity guard: the detector names each spelling it claims to catch
        and stays quiet on reads and on the helper."""
        src = (
            "import json, os, pickle, shutil, yaml\n"
            "from pathlib import Path\n"
            "from espalier._atomic_io import atomic_write_text\n"
            "READ_FLAGS = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)\n"
            "WRITE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL\n"
            "def a(p): p.write_text('x')\n"
            "def b(p): p.write_bytes(b'x')\n"
            "def c(p):\n"
            "    with open(p, 'w') as f: json.dump({}, f)\n"
            "def d(p):\n"
            "    with p.open(mode='wb') as f: pickle.dump({}, f)\n"
            "def d2(p):\n"
            "    with open(p, 'a') as f: f.write('row')\n"
            "def d3(p):\n"
            "    with open(p, 'x') as f: f.write('y')\n"
            "def d4(p):\n"
            "    with p.open('w', 1) as f: f.write('y')\n"
            "def d5(p):\n"
            "    yaml.dump({}, open(p, 'w'))\n"
            "def d6(p, mode):\n"
            "    with open(p, mode) as f: f.write('y')\n"
            "def d7(p):\n"
            "    with open(p, 'r+') as f: f.seek(0); f.write('y'); f.truncate()\n"
            "def d8(p, q): shutil.copy2(p, q)\n"
            "def d9(p, q): shutil.move(p, q)\n"
            "def e(p): atomic_write_text(p, 'x')\n"
            "def f(p):\n"
            "    with open(p) as fh: return fh.read()\n"
            "def f2(p):\n"
            "    with p.open('rb') as fh: return fh.read()\n"
            "def g(p): return p.read_text()\n"
            "def g2(p):\n"
            "    import os; return os.open(p, os.O_RDONLY)\n"
            "def g3(p): return os.open(p, READ_FLAGS)\n"
            "def d10(p): return os.open(p, os.O_WRONLY | os.O_CREAT, 0o666)\n"
            "def d11(p): return os.open(p, WRITE_FLAGS)\n"
            "def d12(p): return os.open(p, os.O_WRONLY | os.O_APPEND)\n"
            "def d13(p, flags): return os.open(p, flags)\n"
            "h = Path('x').write_text('module level')\n"
            "def two(p): p.write_text('x'); p.write_text('y')\n"
        )
        sites = raw_write_sites(ast.parse(src), "m.py")
        assert dict(sites) == {
            ("m.py", "a", "write"): 1, ("m.py", "b", "write"): 1, ("m.py", "c", "write"): 2,
            ("m.py", "d", "write"): 2, ("m.py", "d2", "append"): 1, ("m.py", "d3", "write"): 1,
            ("m.py", "d4", "write"): 1, ("m.py", "d5", "write"): 2, ("m.py", "d6", "write"): 1,
            ("m.py", "d7", "write"): 1, ("m.py", "d8", "copy"): 1, ("m.py", "d9", "copy"): 1,
            ("m.py", "d10", "write"): 1, ("m.py", "d11", "write"): 1,
            ("m.py", "d12", "append"): 1, ("m.py", "d13", "write"): 1,
            ("m.py", "<module>", "write"): 1, ("m.py", "two", "write"): 2,
        }, dict(sites)
        owners = {fn for _rel, fn, _kind in sites}
        assert not owners & {"e", "f", "f2", "g", "g2", "g3"}, owners

    def test_every_exemption_names_a_real_function(self):
        for (rel, func), (_n, reason) in {**_ATOMIC_EXEMPT, **_APPEND_EXEMPT, **_COPY_EXEMPT}.items():
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assert func in names, f"{rel}: exempt function {func!r} no longer exists"
            assert reason.strip(), (rel, func)


class TestTargetMode:
    """DEF-783: the writer takes a target's mode from the target, never from
    the tempfile. Measured before the fix on the self-host box (umask 022): a
    fresh file landed 0600 where ``open()`` gives 0644, an existing 0644
    target was 0600 after one write, and an existing 0755 hook script lost
    its exec bit -- so an adopter's ``chmod +x`` or ``chmod g+r`` was undone
    by the next init, upgrade or session, invisibly (git tracks only the exec
    bit). The helper imposes no policy of its own: a fresh file gets what
    ``open()`` would give under the process umask, an existing regular file
    keeps the bits it had."""

    @posix_modes
    @pytest.mark.parametrize("umask,expected", [(0o022, 0o644), (0o027, 0o640), (0o077, 0o600)])
    def test_a_fresh_file_gets_the_mode_open_would_give(self, atomic_write, tmp_path, umask, expected):
        target = tmp_path / "fresh.json"
        with _umask(umask):
            atomic_write(target, "x")
        assert _mode(target) == expected

    @posix_modes
    @pytest.mark.parametrize("mode", [0o755, 0o640, 0o664, 0o600])
    def test_an_existing_target_keeps_its_mode(self, atomic_write, tmp_path, mode):
        target = tmp_path / "hook.py"
        target.write_text("old", encoding="utf-8")
        target.chmod(mode)
        with _umask(0o022):
            atomic_write(target, "new")
        assert _mode(target) == mode
        assert target.read_text(encoding="utf-8") == "new"

    @posix_modes
    @pytest.mark.parametrize("writer", ["text", "bytes"])
    def test_the_bytes_twin_carries_the_same_contract(self, tmp_path, writer):
        write = _engine_writers()[writer]
        fresh = tmp_path / "fresh"
        kept = tmp_path / "kept"
        kept.write_text("old", encoding="utf-8")
        kept.chmod(0o755)
        with _umask(0o027):
            write(fresh, "x")
            write(kept, "y")
        assert _mode(fresh) == 0o640
        assert _mode(kept) == 0o755

    def test_a_hardlinked_target_is_unlinked_from_its_sibling_which_keeps_the_old_bytes(
        self, atomic_write, tmp_path,
    ):
        """The third leg of the target's identity, a property of rename-based
        atomicity rather than a defect: the new bytes are a new inode, so a
        second name for the old one keeps the old bytes. Stated in
        ``docs/CONVENTIONS.md`` beside the mode and symlink rules."""
        target = tmp_path / "state.json"
        target.write_text("old", encoding="utf-8")
        assert target.is_file()
        sibling = tmp_path / "alias.json"
        try:
            os.link(target, sibling)
        except OSError as exc:
            # Only a filesystem without hardlinks skips; a missing target or
            # a renamed fixture is a red, not a skip.
            if exc.errno not in _NO_HARDLINKS_ERRNOS:
                raise
            pytest.skip(f"hardlinks unavailable here: {exc}")
        atomic_write(target, "new")
        assert target.read_text(encoding="utf-8") == "new"
        assert sibling.read_text(encoding="utf-8") == "old"
        assert target.stat().st_nlink == 1


@requires_symlink
class TestSymlinkedTarget:
    """DEF-784, the contract per TARGET. Every copy replaces a symlinked
    state file with a regular file: harness state is the harness's own,
    the readers of it that refuse a symlink (the plan file's
    ``read_text_nofollow``, the freshness cache's and the statusline's
    ``O_NOFOLLOW`` opens) can read what the write leaves, and no adopter
    manages harness state by dotfiles. The engine's copy takes
    ``follow_symlinks=True`` for the adopter's OWN file (a dotfiles-managed
    ``.gitignore`` or ``settings.json``): the real file is rewritten in
    place, its mode with it, and the link stays. Before the fix init's
    append wrote through the link while uninstall's retire, the settings
    merge and the unwire replaced it with a regular file; a first cut of the
    fix followed the link from EVERY engine write and left a symlinked
    ``.espalier/freshness.json`` unreadable to its own module's reader
    (driven 2026-09-12 by the failure-mode review)."""

    def test_every_copy_replaces_a_symlinked_state_file_with_a_regular_file(self, atomic_write, tmp_path):
        real = tmp_path / "elsewhere" / "plan.json"
        real.parent.mkdir()
        real.write_text("old", encoding="utf-8")
        link = tmp_path / "cc" / "execution_plan.json"
        link.parent.mkdir()
        link.symlink_to(real)
        atomic_write(link, "new")
        assert not link.is_symlink() and link.is_file()
        assert link.read_text(encoding="utf-8") == "new"
        assert real.read_text(encoding="utf-8") == "old", "the file behind the link was touched"

    def test_the_engine_default_leaves_the_freshness_manifest_readable_by_its_nofollow_reader(self, tmp_path):
        """The oracle from the failure-mode review: write the manifest through
        a symlink, then read it the way ``freshness`` does (``O_NOFOLLOW``).
        A writer that followed the link left the reader ``{}`` forever."""
        from espalier import freshness
        real = tmp_path / "elsewhere" / "freshness.json"
        real.parent.mkdir()
        real.write_text("{}", encoding="utf-8")
        link = tmp_path / freshness.MANIFEST_REL_PATH
        link.parent.mkdir(parents=True)
        link.symlink_to(real)
        freshness._write_manifest(tmp_path, {"fragments": {"b": {}}})
        assert freshness._read_fragments_safe(tmp_path) == {"b": {}}

    @pytest.mark.parametrize("writer", ["text", "bytes"])
    def test_with_the_keyword_the_engine_rewrites_the_file_behind_the_link_and_keeps_it(self, tmp_path, writer):
        write = _engine_writers(follow_symlinks=True)[writer]
        real = tmp_path / "dotfiles" / "gitignore"
        real.parent.mkdir()
        real.write_text("old", encoding="utf-8")
        link = tmp_path / "repo" / ".gitignore"
        link.parent.mkdir()
        link.symlink_to(real)
        write(link, "new")
        assert link.is_symlink(), "the link was replaced by a regular file"
        # Windows' os.readlink hands back the `\\?\` extended form of an absolute
        # link's target -- the way the reparse point stores it -- and the 3.12.10
        # realpath keeps the prefix; compare the two spellings of one file with
        # the prefix dropped and the case folded (Portability, 2026-09-23)
        def _same_file(spelling: str) -> str:
            if spelling.startswith("\\\\?\\"):
                spelling = spelling[4:]
            return os.path.normcase(os.path.realpath(spelling))
        assert _same_file(os.readlink(link)) == _same_file(str(real))
        assert real.read_text(encoding="utf-8") == "new"
        for d in (real.parent, link.parent):
            assert list(d.glob(".*.tmp")) == [], f"tempfile left in {d}"

    @posix_modes
    def test_with_the_keyword_the_file_behind_the_link_keeps_its_mode(self, tmp_path):
        from espalier._atomic_io import atomic_write_text
        real = tmp_path / "dotfiles" / "settings.json"
        real.parent.mkdir()
        real.write_text("{}", encoding="utf-8")
        real.chmod(0o640)
        link = tmp_path / "repo" / "settings.json"
        link.parent.mkdir()
        link.symlink_to(real)
        with _umask(0o022):
            atomic_write_text(link, "{ }", follow_symlinks=True)
        assert _mode(real) == 0o640

    def test_with_the_keyword_a_dangling_link_whose_directory_exists_gets_its_file(self, tmp_path):
        from espalier._atomic_io import atomic_write_text
        dotfiles = tmp_path / "dotfiles"
        dotfiles.mkdir()
        link = tmp_path / "repo" / ".gitignore"
        link.parent.mkdir()
        link.symlink_to(dotfiles / "gitignore")
        atomic_write_text(link, "x", follow_symlinks=True)
        assert link.is_symlink()
        assert (dotfiles / "gitignore").read_text(encoding="utf-8") == "x"

    def test_with_the_keyword_a_dangling_link_into_a_missing_directory_fails_and_creates_nothing(self, tmp_path):
        """A link into a dotfiles checkout that is not cloned yet: the write
        fails with the OSError init already turns into a one-line manual step,
        the missing directory is NOT created, and the link is not replaced."""
        from espalier._atomic_io import atomic_write_text
        link = tmp_path / "repo" / ".gitignore"
        link.parent.mkdir()
        link.symlink_to(tmp_path / "not-cloned" / "gitignore")
        with pytest.raises(OSError):
            atomic_write_text(link, "x", follow_symlinks=True)
        assert not (tmp_path / "not-cloned").exists()
        assert link.is_symlink() and not link.exists()
        assert list(link.parent.iterdir()) == [link]

    def test_only_the_adopter_file_sites_pass_the_keyword(self):
        """The keyword is for the adopter's own files and nothing else; the
        sites that pass it are the retire, the settings merge, the hook-wiring
        repair, the interpreter rewire and the unwire. A new site that follows a link is a decision, not a
        side effect -- confirm the target is the adopter's, then add it."""
        sites: set[tuple[str, str]] = set()
        for rel in ("espalier/cli.py", "espalier/cleanup.py"):
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))

            def visit(node: ast.AST, owner: str) -> None:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = node.name
                if isinstance(node, ast.Call) and any(
                    kw.arg == "follow_symlinks" for kw in node.keywords
                ):
                    sites.add((rel, owner))
                for child in ast.iter_child_nodes(node):
                    visit(child, owner)

            visit(tree, "<module>")
        assert sites == {
            ("espalier/cli.py", "merge_hooks_into_settings"),
            ("espalier/cli.py", "repair_hook_wiring_in_settings"),
            ("espalier/cli.py", "rewire_interpreter_in_settings"),
            ("espalier/cleanup.py", "_retire_gitignore_block"),
            ("espalier/cleanup.py", "_unwire_espalier_hooks"),
        }


#: Every function in the shipped source that commits a write with
#: ``os.replace``: the four copies of the helper, its bytes twin, and the
#: release archive's writer (a ``ZipFile`` stream no text or bytes helper can
#: carry; it creates its tempfile the same way). Derived from the tree and
#: asserted equal both ways, so a fifth inlined copy reds here instead of
#: escaping the mode and symlink contracts (driven 2026-09-12 by the
#: failure-mode review: an inlined ``os.open`` + ``os.replace`` writer was
#: invisible to every gate). The values name the ``_COPIES`` member each
#: writer is tested as, or the reason it is not one.
_REPLACE_WRITERS: dict[tuple[str, str], str] = {
    ("espalier/_atomic_io.py", "atomic_write_text"): "engine",
    ("espalier/_atomic_io.py", "atomic_write_bytes"): "the engine's bytes twin: _engine_writers",
    ("tools/cc/hooks/_hook_utils.py", "atomic_write_text"): "hook",
    ("tools/cc/cognitive_blueprint.py", "_atomic_write_text"): "blueprint",
    ("tools/cc/execution_plan.py", "_atomic_write_text"): "plan",
    ("espalier/release_pack.py", "_atomic_write_zip"): (
        "the release archive: a ZipFile stream, no text or bytes payload; the "
        "same create (mode 0o666 under the umask), pinned by TestReplaceWriters"
    ),
}


def replace_writers(root: Path) -> set[tuple[str, str]]:
    """Every ``(module, innermost function)`` under ``espalier/`` (minus the
    ``_vendor/`` mirror) and ``tools/cc/`` that calls ``os.replace``."""
    found: set[tuple[str, str]] = set()
    for sub in ("espalier", "tools/cc"):
        for py in sorted((root / sub).rglob("*.py")):
            rel = py.relative_to(root).as_posix()
            if rel.startswith("espalier/_vendor/"):
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"))

            def visit(node: ast.AST, owner: str) -> None:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = node.name
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "replace"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                ):
                    found.add((rel, owner))
                for child in ast.iter_child_nodes(node):
                    visit(child, owner)

            visit(tree, "<module>")
    return found


class TestReplaceWriters:
    def test_every_os_replace_writer_is_rostered_and_every_roster_entry_is_live(self):
        actual = replace_writers(REPO_ROOT)
        expected = set(_REPLACE_WRITERS)
        assert actual == expected, (
            f"writers not in the roster (a fifth copy of the helper?): {sorted(actual - expected)}; "
            f"stale roster entries: {sorted(expected - actual)}"
        )

    def test_every_copy_the_fixture_runs_is_a_rostered_writer(self):
        tested = {v for v in _REPLACE_WRITERS.values() if v in _COPIES}
        assert tested == set(_COPIES), (tested, _COPIES)

    @posix_modes
    def test_the_release_archive_gets_the_mode_open_would_give(self, tmp_path):
        from espalier.release_pack import _atomic_write_zip
        src = tmp_path / "a.txt"
        src.write_text("a", encoding="utf-8")
        out = tmp_path / "dist" / "pack.zip"
        with _umask(0o022):
            _atomic_write_zip(out, [(src, Path("a.txt"))])
        assert _mode(out) == 0o644
        assert list(out.parent.glob(".*.tmp")) == []
