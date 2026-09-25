"""Detect text-mode file and subprocess I/O that follows the OS locale, not UTF-8.

Stdlib-only AST walker (zero espalier imports, per TestScannerSelfContainment).

The class: text-mode I/O that omits ``encoding="utf-8"`` decodes or encodes
through ``locale.getpreferredencoding()``. Invisible on a UTF-8 host; on a
stock Windows cp1252 console a UTF-8 fixture mis-decodes (mojibake, or
``UnicodeDecodeError`` on a byte cp1252 leaves undefined) and a character
outside cp1252 cannot be written at all. The cp1252 defects of 2026-08 and
2026-09 were this shape. The two gates that caught them
(``tests/test_git_conventions_encoding.py`` and
``tests/test_contracts.py::TestSubprocessEncodingPinned``) pin the SITES already
found -- the subprocess shape on production code -- not the shape; this scanner
reads the shape on every tree, tests included, because the user it protects is
a contributor running the SUITE under a non-UTF-8 locale.

The shapes, judged by the ``encoding=`` VALUE wherever it is given (keyword or
the positional slot the signature puts it in); a key present but set to
``None`` or ``"latin-1"`` is still the bug:

- ``open(p)`` / ``io.open(p, "w")`` / ``os.fdopen(fd, mode="a+")`` -- the
  builtin family; text mode is any literal mode without ``b``, ``"r"`` when
  omitted. A non-literal mode cannot be judged and is left alone.
- ``<receiver>.open(...)`` -- the ``pathlib.Path`` idiom, same mode rule, the
  mode in the FIRST slot. A receiver that is a module known to open something
  other than a text file (``os``, ``tarfile``, ``zipfile``, ``gzip``, ...) is
  skipped; any other receiver is judged, so a ``ZipFile.open`` held in a
  variable can over-fire -- the pragma is for that.
- ``.read_text(...)`` / ``.write_text(...)`` -- by attribute name.
- ``subprocess.run / check_output / Popen / call / check_call`` with a literal
  ``text=True`` or ``universal_newlines=True`` -- the module under any alias
  (``import subprocess as sp``) and the functions imported by name
  (``from subprocess import run``).
- ``tempfile.NamedTemporaryFile / TemporaryFile / SpooledTemporaryFile`` in a
  literal text mode (the default ``w+b`` is binary and never fires).
- ``io.TextIOWrapper(buffer, ...)`` -- always text; the encoding is the second
  positional slot.

``encoding=<name or call>`` and a call that splats ``**kwargs`` are given the
benefit of the doubt (the reviewer reads them). UTF-8 in any spelling
(``UTF8``, ``utf_8``, ``utf-8-sig``) is pinned. Known limits, declared rather
than guessed at: ``codecs.open``, ``gzip.open(p, "rt")`` and the other
module-level text openers, ``print(file=...)`` to a handle opened elsewhere,
and a mode or receiver the AST cannot resolve.

Opt-out: ``# encoding-locale-ok: <reason>`` on the line ABOVE the call -- the
family idiom the other generative scanners use: ``^#``-anchored so an inline
trailing comment cannot suppress a flagged line, and ``_pragma_in_line`` is the
one normalization point both the cap counter and the exemption reader go
through. The pragma population IS this scanner's allow-list: capped by
``MAX_PRAGMA_COUNT`` and pinned live by the scanner's own test (a pragma above a
site that no longer follows the locale is a dead entry and reds), so it can
neither grow silently nor outlive its reason.

Walk: the whole tree under the root (no root list to drift). It is the one
scanner in the family that walks the root rather than a declared source
directory, so ``_skip_nested_repos`` here prunes, in the one statement the
walk-loop parity pin allows, three kinds of tree that are never this
repository's code: a nested repository, the tool directories in
``PRUNE_DIRS`` by name, and any virtualenv by the ``pyvenv.cfg`` every venv
carries. ``tools/cc/`` IS walked. Sources are read through a byte-order mark
(``utf-8-sig``: CPython runs a BOM'd module, so it is live code), and a file
that cannot be read or parsed is reported under ``skipped`` rather than passed
over. ``tests/fixtures/`` is exempt (own defining material and the other
scanners' corpora), as is ``espalier/_vendor/cc/``, the byte-mirror covered
through ``tools/cc/``; the transformed selfcheck mirror beside it is walked.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# ─────────────────────────────────────────────────────────────────────
# INLINED configuration -- per TestScannerSelfContainment (no espalier imports).
PRAGMA_RE = re.compile(r"^#\s*encoding-locale-ok:\s*(.{12,})$")
# One live pragma: tests/test_hook_exec_form.py decodes the deployed batch shim
# strictly as ASCII because seven-bit-ness IS the assertion. Raising the cap is
# a deliberate act with a written reason here, like every sibling scanner's.
MAX_PRAGMA_COUNT: int = 1

# Sister-site protection: fixture files contain intentional positives; the
# cc byte-mirror is covered through the tools/cc sources it copies; task-packs/
# is the gitignored pack workspace whose one-off probe scripts are neither
# shipped nor run by the suite. The selfcheck-tests mirror under _vendor/ is a
# TRANSFORM (not a byte copy) that ships, so it is walked, not exempt.
EXEMPT_PREFIXES: tuple[str, ...] = (
    "tests/fixtures/",
    "espalier/_vendor/cc/",
    "espalier/assets/",
    "task-packs/",
)
MAX_EXEMPT_PREFIXES: int = 4

# Directories never walked, by name. The family-1 set minus ``cc`` (the hook
# tree under tools/cc/ is a surface this scanner exists to read) plus the
# tool trees .gitignore anticipates; a virtualenv under ANY name is pruned by
# its pyvenv.cfg in _skip_nested_repos, so this list need not guess names.
PRUNE_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "env", ".tox", ".nox", ".eggs", "htmlcov",
    "site-packages", "__pycache__", ".pytest_cache", "node_modules",
    "dist", "build", ".mypy_cache", ".ruff_cache",
})

SUBPROCESS_TEXT_FUNCS: frozenset[str] = frozenset({
    "run", "check_output", "Popen", "call", "check_call",
})
TEMPFILE_FUNCS: frozenset[str] = frozenset({
    "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile",
})
#: Modules whose ``.open`` opens something other than a text file: never a
#: Path-style ``.open()`` site. ``io`` is NOT here -- ``io.open`` is the builtin.
NON_FILE_OPENERS: frozenset[str] = frozenset({
    "os", "tarfile", "zipfile", "gzip", "bz2", "lzma", "webbrowser", "codecs",
    "socket", "urllib", "shelve", "dbm", "mailbox", "wave", "aifc", "sunau",
})
#: ``encoding=`` literals that pin UTF-8, after lower-casing and dropping ``-``
#: and ``_``. ``utf-8-sig`` is UTF-8 with BOM tolerance, not a locale.
UTF8_SPELLINGS: frozenset[str] = frozenset({"utf8", "utf8sig"})

SEVERITY_MISSING = "MISSING"      # no encoding at all: the locale decides
SEVERITY_NOT_UTF8 = "NOT_UTF8"    # an encoding is given but is None or not UTF-8
# ─────────────────────────────────────────────────────────────────────


def _skip_nested_repos(dirpath: str, dirnames: list[str]) -> None:
    """Drop from an os.walk ``dirnames``, in place, every subtree that is not
    this repository's code: an embedded repository (parity with
    ``espalier._safe_walk.safe_rglob(skip_nested_repos=True)``; a nested ``.git``
    dir OR gitlink file marks a foreign project), a tool directory named in
    ``PRUNE_DIRS``, and a virtualenv under any name (the ``pyvenv.cfg`` every
    venv carries). One statement in the walk loop -- the shape
    ``tests/test_safe_walk.py`` pins across every inline ``_safe_rglob`` copy --
    and the superset this whole-root walker needs where its siblings, which
    walk a declared source directory, need only the repository prune."""
    import os
    dirnames[:] = [
        d for d in dirnames
        if d not in PRUNE_DIRS
        and not os.path.exists(os.path.join(dirpath, d, ".git"))
        and not os.path.exists(os.path.join(dirpath, d, "pyvenv.cfg"))
    ]


def _safe_rglob(root, pattern: str = "*"):
    """Symlink-safe rglob (inline -- scanners have zero espalier imports). See
    espalier/_safe_walk.py for the canonical version. ``os.walk(followlinks=
    False)`` never descends a symlinked dir, so it is crash-safe on CPython
    3.10-3.12 where bare rglob follows dir symlinks (ELOOP on a loop)."""
    import fnmatch
    import os
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        _skip_nested_repos(dirpath, dirnames)
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name


@dataclass(frozen=True, slots=True)
class EncodingFinding:
    path: Path          # relative to the scanned root
    lineno: int
    shape: str          # open | read_text | write_text | subprocess | tempfile | TextIOWrapper
    severity: str       # MISSING | NOT_UTF8
    explanation: str


def _is_exempt(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def _iter_scoped_files(root: Path) -> Iterable[tuple[Path, str]]:
    """(path, repo-relative) for every ``.py`` under ``root`` that is not exempt.
    ONE walk shared by the detector and both pragma readers, so the cap's
    accounting scope can never drift from the exemption's effect scope."""
    for path in _safe_rglob(root, "*.py"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        if _is_exempt(rel):
            continue
        yield path, rel


def _read_source(path: Path) -> str:
    """Read through a UTF-8 byte-order mark: CPython imports a BOM'd module, so
    it is live code, and ``ast.parse`` would otherwise refuse it. Raises what
    the caller accounts for."""
    return path.read_text(encoding="utf-8-sig")


def scan_repo(root: Path) -> list[EncodingFinding]:
    findings, _skipped = scan_repo_with_skips(root)
    return findings


def scan_repo_with_skips(root: Path) -> tuple[list[EncodingFinding], list[dict]]:
    """Findings plus the files the scan could NOT read or parse, so a parse
    failure is a reported gap and never a silent pass. The ``skipped`` entries
    carry the family's ``file`` key, the one ``cmd_scan``'s WARN reads."""
    findings: list[EncodingFinding] = []
    skipped: list[dict] = []
    for path, rel in _iter_scoped_files(Path(root)):
        findings.extend(_scan_file(path, Path(root), skipped))
    return findings, skipped


def build_report(root: Path) -> dict:
    findings, skipped = scan_repo_with_skips(root)
    return {
        "count": len(findings),
        "findings": [
            {
                "path": str(f.path).replace("\\", "/"),
                "line": f.lineno,
                "shape": f.shape,
                "severity": f.severity,
                "explanation": f.explanation,
            }
            for f in findings
        ],
        "skipped": skipped,
    }


def _pragma_in_line(line: str) -> bool:
    """Single normalization point shared by both pragma readers
    (``count_pragmas`` + ``_has_pragma_above``). Strip before matching the
    ``^#``-anchored PRAGMA_RE so an indented pragma is seen consistently by the
    cap counter AND the exemption check -- never honored by one while
    invisible to the other."""
    return PRAGMA_RE.search(line.strip()) is not None


def _has_pragma_above(lines: list[str], stmt_lineno: int) -> bool:
    if stmt_lineno < 2:
        return False
    return _pragma_in_line(lines[stmt_lineno - 2])


def count_pragmas(root: Path) -> int:
    return len(collect_pragmas(root))


def collect_pragmas(root: Path) -> list[dict]:
    """Every honored pragma as ``{scanner, path, line, reason}``, over the SAME
    scope the detector walks (``_iter_scoped_files``), so
    ``len(collect_pragmas(root)) == count_pragmas(root)`` holds by construction
    and a pragma in an exempt fixture never eats the cap."""
    records: list[dict] = []
    for path, rel in _iter_scoped_files(Path(root)):
        try:
            source = _read_source(path)
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(source.splitlines(), start=1):
            if not _pragma_in_line(line):
                continue
            m = PRAGMA_RE.search(line.strip())
            records.append({
                "scanner": "encoding_contracts", "path": rel, "line": i,
                "reason": m.group(1).strip() if m else "",
            })
    return records


def pins_utf8(node: ast.expr | None) -> bool | None:
    """``True`` when the encoding node is a UTF-8 literal, ``False`` when it is a
    literal that is not (``None`` included), ``None`` when it cannot be judged
    statically (a name, a call) and is given the benefit of the doubt."""
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        value = node.value
        if not isinstance(value, str):
            return False
        return value.lower().replace("-", "").replace("_", "") in UTF8_SPELLINGS
    return None


def _literal_mode(call: ast.Call, kw: dict[str, ast.expr], index: int, default: str) -> str | None:
    """The mode literal at positional ``index`` or ``mode=``: ``default`` when
    omitted, ``None`` when it is not a literal (unjudgeable)."""
    node: ast.expr | None = None
    if len(call.args) > index:
        node = call.args[index]
    elif "mode" in kw:
        node = kw["mode"]
    if node is None:
        return default
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_text_mode(mode: str | None) -> bool:
    return mode is not None and "b" not in mode


def _subprocess_bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """The names the module binds to ``subprocess`` (the module itself, under
    any alias) and to its text-capable functions (``from subprocess import
    run as r``), so an alias cannot hide a call from the scan."""
    modules = {"subprocess"}
    funcs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in SUBPROCESS_TEXT_FUNCS:
                    funcs.add(alias.asname or alias.name)
    return modules, funcs


def _encoding_slot(call: ast.Call, kw: dict[str, ast.expr], index: int) -> tuple[bool, ast.expr | None]:
    """``(given, node)``: the encoding as ``encoding=`` or at positional
    ``index`` (``read_text(encoding, errors)`` puts it first, ``write_text(data,
    encoding, errors)`` second, ``TextIOWrapper(buffer, encoding, ...)`` second)."""
    if "encoding" in kw:
        return True, kw["encoding"]
    if len(call.args) > index:
        return True, call.args[index]
    return False, None


def _shape_of(
    call: ast.Call, kw: dict[str, ast.expr], modules: set[str], funcs: set[str],
) -> tuple[str, bool, ast.expr | None] | None:
    """``(shape, encoding_given, encoding_node)`` for a text-mode call, or
    ``None`` when ``call`` is not one of the shapes (or is binary / unjudgeable)."""
    func = call.func
    # the builtin family: open / io.open / os.fdopen -- mode in the SECOND slot
    if (isinstance(func, ast.Name) and func.id == "open") or (
        isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
        and ((func.value.id == "io" and func.attr == "open")
             or (func.value.id == "os" and func.attr == "fdopen"))
    ):
        if not _is_text_mode(_literal_mode(call, kw, 1, "r")):
            return None
        return "open", "encoding" in kw, kw.get("encoding")
    if isinstance(func, ast.Attribute):
        recv = func.value
        # a Path-style .open() -- mode in the FIRST slot; module openers skipped
        if func.attr == "open":
            if isinstance(recv, ast.Name) and recv.id in NON_FILE_OPENERS:
                return None
            if not _is_text_mode(_literal_mode(call, kw, 0, "r")):
                return None
            return "open", "encoding" in kw, kw.get("encoding")
        if func.attr == "read_text":
            given, node = _encoding_slot(call, kw, 0)
            return "read_text", given, node
        if func.attr == "write_text":
            given, node = _encoding_slot(call, kw, 1)
            return "write_text", given, node
        if isinstance(recv, ast.Name):
            if recv.id in modules and func.attr in SUBPROCESS_TEXT_FUNCS:
                return _subprocess_shape(kw)
            if recv.id == "tempfile" and func.attr in TEMPFILE_FUNCS:
                if not _is_text_mode(_literal_mode(call, kw, 0, "w+b")):
                    return None
                return "tempfile", "encoding" in kw, kw.get("encoding")
            if recv.id == "io" and func.attr == "TextIOWrapper":
                given, node = _encoding_slot(call, kw, 1)
                return "TextIOWrapper", given, node
        return None
    if isinstance(func, ast.Name) and func.id in funcs:
        return _subprocess_shape(kw)
    return None


def _subprocess_shape(kw: dict[str, ast.expr]) -> tuple[str, bool, ast.expr | None] | None:
    for flag in ("text", "universal_newlines"):
        node = kw.get(flag)
        if isinstance(node, ast.Constant) and node.value is True:
            return "subprocess", "encoding" in kw, kw.get("encoding")
    return None


def sites_in_source(source: str) -> list[tuple[int, str, str]]:
    """Every locale-following call in ``source`` as ``(lineno, shape,
    severity)``, BEFORE the pragma filter. Raises ``SyntaxError`` on a source
    that does not parse -- the caller accounts for it. The scanner's own
    liveness test reads this to prove each honored pragma still sits above a
    real site."""
    tree = ast.parse(source)
    modules, funcs = _subprocess_bindings(tree)
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if any(k.arg is None for k in node.keywords):
            continue  # **kwargs: the encoding may ride in the splat
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        shape = _shape_of(node, kw, modules, funcs)
        if shape is None:
            continue
        name, given, enc = shape
        if not given:
            out.append((node.lineno, name, SEVERITY_MISSING))
            continue
        verdict = pins_utf8(enc)
        if verdict is False:
            out.append((node.lineno, name, SEVERITY_NOT_UTF8))
    return out


def _scan_file(path: Path, root: Path, skipped: list[dict] | None = None) -> Iterable[EncodingFinding]:
    rel = path.relative_to(root)
    rel_s = str(rel).replace("\\", "/")
    try:
        source = _read_source(path)
    except (OSError, UnicodeDecodeError) as exc:
        if skipped is not None:
            skipped.append({"file": rel_s, "reason": f"unreadable: {type(exc).__name__}"})
        return
    try:
        sites = sites_in_source(source)
    except SyntaxError as exc:
        if skipped is not None:
            skipped.append({"file": rel_s, "reason": f"unparseable: {exc.msg} (line {exc.lineno})"})
        return
    lines = source.splitlines()
    for lineno, shape, severity in sites:
        if _has_pragma_above(lines, lineno):
            continue
        if severity == SEVERITY_MISSING:
            explanation = (
                f"{shape} call has no encoding -- the text is decoded or encoded "
                "through the OS locale, not UTF-8 (cp1252 on a stock Windows "
                'console). Pin encoding="utf-8", or add '
                "`# encoding-locale-ok: <reason>` on the preceding line."
            )
        else:
            explanation = (
                f"{shape} call pins an encoding that is not UTF-8 (None follows "
                "the locale; another codec cannot read a UTF-8 file). Pin "
                'encoding="utf-8", or add `# encoding-locale-ok: <reason>` on '
                "the preceding line."
            )
        yield EncodingFinding(
            path=rel, lineno=lineno, shape=shape, severity=severity,
            explanation=explanation,
        )
