"""A kept, older ``tools/cc/`` sibling is named with its repair (DEF-5087).

``espalier upgrade`` keeps a managed script that drifted and carries no marker
(``espalier/cli.py::_deploy_managed_py``, its ``skipped_user_file`` answer) and
regenerates the siblings beside it, so a regenerated script can take a name the
kept copy lacks. Until DEF-5087 every ship driver verb, ``--help`` included,
then ended in a traceback naming an attribute. These rows pin the named refusal
and guard against its drift back: they drive the driver from
a copy of ``tools/cc`` with one name gone from a sibling (the row's probe), and
read the one reader every refusal of this shape goes through
(``tools/cc/hooks/_start_refusal.py::_missing_sibling_name``) on the shapes it
must not read as a kept file.
"""
# slow-exempt: one --help child per armed script and a few controls, each over a copied tools/cc tree, each under a second
from __future__ import annotations

from collections.abc import Iterable
import ast
import functools
import importlib.util
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests._live_tree import checkout_glob, copy_checkout
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parent.parent
CC_DIR = REPO_ROOT / "tools" / "cc"


def _reader() -> types.ModuleType:
    """``_start_refusal`` loaded by path under its own alias, registered before
    exec (a path-loaded module needs the registration on 3.14)."""
    alias = "_kept_sibling_test_start_refusal"
    module = sys.modules.get(alias)
    if module is None:
        spec = importlib.util.spec_from_file_location(alias, CC_DIR / "hooks" / "_start_refusal.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    return module


# ── the ship driver on a kept sibling ─────────────────────────────────────────

#: Each plant: the sibling file, the text appended to it, and the name the
#: refusal must give. ``post_merge`` is the row's probe (a module-level read in
#: ship.py, an AttributeError); ``json_safe`` is a ``from`` import (an
#: ImportError); ``raised`` is a sibling that raises for another reason, which
#: keeps its traceback.
_PLANTS = {
    "post_merge": ("_post_merge.py", "\ndel CHECK_GREEN\n", "CHECK_GREEN"),
    "json_safe": ("_json_safe.py", "\ndel fold_newlines\n", "fold_newlines"),
    "raised": ("_post_merge.py", "\nraise KeyError(1)\n", None),
}


def _refusal_then_traceback(stderr: str) -> str:
    """The refusal's one line, asserted to come first, to carry no restore and
    to be followed by the traceback (DEF-5088, air's ruling 92ed0c: a script's
    restore would discard an edit in progress with no copy kept, and the
    traceback is that editor's account)."""
    first, _sep, rest = stderr.partition("\n")
    assert rest.startswith("Traceback (most recent call last):"), stderr[-600:]
    assert first.endswith("the traceback follows."), first
    assert "git restore" not in stderr and "restore the edited file" not in stderr, stderr[-600:]
    return first


def _drive(tmp_path: Path, plant: str | None) -> subprocess.CompletedProcess:
    root = tmp_path / (plant or "intact")
    copy_checkout(CC_DIR, root / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))
    if plant is not None:
        name, text, _taken = _PLANTS[plant]
        target = root / "tools" / "cc" / name
        target.write_bytes(target.read_bytes() + text.encode("utf-8"))
    return subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "ship.py"), "--help"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=scaled(30),
    )


class TestTheShipDriverOnAKeptSibling:
    @pytest.mark.parametrize("plant", ["post_merge", "json_safe"])
    def test_a_name_a_sibling_lacks_is_one_named_refusal(self, tmp_path, plant):
        run = _drive(tmp_path, plant)
        name, _text, taken = _PLANTS[plant]
        assert run.returncode == 1, (run.returncode, run.stderr[-600:])
        _refusal_then_traceback(run.stderr)
        assert run.stderr.startswith("ship.py cannot run: tools/cc/"), run.stderr[-600:]
        taker = run.stderr[len("ship.py cannot run: "):].split(" takes `", 1)[0]
        assert taker.rsplit(":", 1)[1].isdigit(), taker   # the file and its line (the review's NIT 8)
        assert f"`{taken}`" in run.stderr
        assert f"from tools/cc/{name}, which lacks it" in run.stderr
        assert f"If an upgrade kept {name} as yours" in run.stderr
        assert "`# espalier:managed` marker line" in run.stderr
        assert "`espalier upgrade --execute .`" in run.stderr
        assert f"If you are editing tools/cc, the error is your read at {taker};" in run.stderr
        assert run.stdout == ""

    @pytest.mark.parametrize("where", ["module", "call"])
    def test_a_read_in_a_call_says_the_script_stopped(self, tmp_path, where):
        # A read in a call the script made has run part of it, so "cannot run"
        # would mislead; the module body's read has not (the review's NIT 8).
        cc = tmp_path / "tools" / "cc"
        (cc / "hooks").mkdir(parents=True)
        shutil.copy2(CC_DIR / "hooks" / "_start_refusal.py", cc / "hooks" / "_start_refusal.py")
        (cc / "_kept.py").write_text("present = 1\n", encoding="utf-8")
        read = "_kept.absent" if where == "module" else "None"
        (cc / "probe.py").write_text(
            "import importlib.util, sys\nfrom pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('_probe_refusal', Path(__file__).parent / 'hooks' / '_start_refusal.py')\n"
            "reader = importlib.util.module_from_spec(spec); sys.modules[spec.name] = reader; spec.loader.exec_module(reader)\n"
            "reader.refuse_kept_siblings('probe.py')\n"
            "sys.path.insert(0, str(Path(__file__).parent))\nimport _kept\n"
            f"AT_IMPORT = {read}\n"
            "def main():\n    return _kept.absent\n"
            "main()\n", encoding="utf-8")
        run = subprocess.run([sys.executable, str(cc / "probe.py")], cwd=str(tmp_path), capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=scaled(30))
        outcome = "cannot run" if where == "module" else "stopped"
        line = 8 if where == "module" else 10
        assert run.returncode == 1, run.stderr[-600:]
        _refusal_then_traceback(run.stderr)
        assert run.stderr.startswith(
            f"probe.py {outcome}: tools/cc/probe.py:{line} takes `absent` from tools/cc/_kept.py, which lacks it"
        ), run.stderr[-600:]

    def test_the_intact_copy_prints_its_usage(self, tmp_path):
        # A control: it passes on the code before DEF-5087 too, and reds if the
        # reader's install ever costs the intact driver its usage.
        run = _drive(tmp_path, None)
        assert run.returncode == 0, run.stderr[-600:]
        assert run.stdout.startswith("usage: ship.py"), run.stdout[:200]
        assert run.stderr == ""

    def test_a_sibling_that_raises_otherwise_keeps_its_traceback(self, tmp_path):
        # A control: it passes on the code before DEF-5087 too, and reds if the
        # reader ever swallows a raise that is not a kept file's.
        run = _drive(tmp_path, "raised")
        assert run.returncode == 1, run.stderr[-600:]
        assert "Traceback" in run.stderr and "KeyError: 1" in run.stderr, run.stderr[-600:]
        assert "cannot run" not in run.stderr


# ── the reader ────────────────────────────────────────────────────────────────

def _module(name: str, where: Path, **bound: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(where / f"{name}.py")
    for key, value in bound.items():
        setattr(module, key, value)
    return module


def _attribute_error(module: types.ModuleType, name: str) -> AttributeError:
    try:
        getattr(module, name)
    except AttributeError as exc:
        return exc
    raise AssertionError(f"{name} is bound on {module.__name__}")


class TestTheReader:
    def test_a_name_a_tools_cc_module_lacks_reads_as_kept(self):
        module = _module("_kept_probe", CC_DIR)
        assert _reader()._missing_sibling_name(_attribute_error(module, "gone"), CC_DIR.resolve()) == (
            "gone", (CC_DIR / "_kept_probe.py").resolve())

    def test_a_hooks_module_reads_as_kept_too(self):
        module = _module("_kept_probe", CC_DIR / "hooks")
        reading = _reader()._missing_sibling_name(_attribute_error(module, "gone"), CC_DIR.resolve())
        assert reading == ("gone", (CC_DIR / "hooks" / "_kept_probe.py").resolve())

    def test_a_from_import_reads_its_module(self, monkeypatch):
        module = _module("_kept_probe", CC_DIR)
        monkeypatch.setitem(sys.modules, "_kept_probe", module)
        exc = ImportError("cannot import name 'gone' from '_kept_probe'", name="_kept_probe")
        assert _reader()._missing_sibling_name(exc, CC_DIR.resolve()) == (
            "gone", (CC_DIR / "_kept_probe.py").resolve())

    def test_a_module_outside_tools_cc_is_not_read(self, tmp_path):
        module = _module("_kept_probe", tmp_path)
        assert _reader()._missing_sibling_name(_attribute_error(module, "gone"), CC_DIR.resolve()) is None

    def test_a_name_the_module_holds_is_not_read(self):
        module = _module("_kept_probe", CC_DIR, here=1)
        exc = AttributeError("module '_kept_probe' has no attribute 'here'", name="here", obj=module)
        assert _reader()._missing_sibling_name(exc, CC_DIR.resolve()) is None

    def test_a_module_still_running_its_body_is_not_read(self):
        # A circular import names a name its module has not bound yet: an edit,
        # never a kept copy, so no upgrade is offered for it.
        module = _module("_kept_probe", CC_DIR)
        module.__spec__ = types.SimpleNamespace(_initializing=True)  # type: ignore[assignment]
        assert _reader()._missing_sibling_name(_attribute_error(module, "gone"), CC_DIR.resolve()) is None

    def test_an_error_that_names_no_module_is_not_read(self):
        assert _reader()._missing_sibling_name(KeyError(1), CC_DIR.resolve()) is None
        assert _reader()._missing_sibling_name(ImportError("planted"), CC_DIR.resolve()) is None


# ── the banner's pull-request block on a kept _post_merge.py ──────────────────

def _banner() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_kept_sibling_test_banner", CC_DIR / "hooks" / "session_start.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reads_of_the_loaded_module() -> dict[str, set[str]]:
    """``{name: keywords}``: what the banner takes from ``_post_merge``, read by
    the upgrade's own walker (``espalier/cli.py::_sibling_reads``: a walrus, an
    annotated binding, a chained ``_load_post_merge().<name>`` and a module
    handed to a parameter included), so the table and the upgrade's reading
    cannot see different reads (the failure-mode review on DEF-5087)."""
    from espalier.cli import _sibling_takes

    banner = "tools/cc/hooks/session_start.py"
    names, keywords = _sibling_takes(CC_DIR)
    reads = {name: set() for name, takers in names.get("_post_merge", {}).items() if banner in takers}
    for func, passed in keywords.get("_post_merge", {}).items():
        for keyword, takers in passed.items():
            if banner in takers:
                reads.setdefault(func, set()).add(keyword)
    return reads


def _older_post_merge(**overrides: object) -> types.ModuleType:
    """A stand-in for a copy of tools/cc/_post_merge.py from before 68bcc8b,
    whose ``read_required`` takes neither ``head=`` nor ``runs=``."""
    module = types.ModuleType("_older_post_merge")

    def read_required(number, gh, fields=""):  # noqa: ARG001 -- the shape is the point
        return None

    for name in ("check_outcome", "latest_run_per_check", "verdicts"):
        setattr(module, name, lambda *a: None)
    module.read_required = read_required  # type: ignore[attr-defined]
    for name, value in overrides.items():
        setattr(module, name, value)
    return module


class TestTheBannerOnAKeptPostMerge:
    def test_the_reads_table_is_every_read_the_block_makes(self):
        found = _reads_of_the_loaded_module()
        assert len(found) >= 4, found   # the floor at authoring: four names, one call with keywords
        table = _banner()._POST_MERGE_READS
        assert {name: set(kw) for name, kw in table.items()} == found

    def test_todays_module_lacks_nothing(self):
        banner = _banner()
        assert banner._post_merge_lacks(banner._load_post_merge()) == ""
        assert banner._post_merge_unread() == ""

    def test_a_copy_without_the_head_keyword_is_one_line_naming_the_file(self, monkeypatch):
        banner = _banner()
        monkeypatch.setattr(banner, "_load_post_merge", _older_post_merge)
        line = banner._post_merge_unread()
        assert line.startswith("pull requests unread (tools/cc/_post_merge.py has `read_required` without `head=`")
        assert "`# espalier:managed` marker line" in line and "`espalier upgrade --execute .`" in line

    def test_a_copy_without_a_name_is_named_by_it(self, monkeypatch):
        banner = _banner()

        def read_required(number, gh, fields="", *, head="", runs=None):  # noqa: ARG001
            return None

        older = _older_post_merge(read_required=read_required)
        del older.verdicts
        monkeypatch.setattr(banner, "_load_post_merge", lambda: older)
        assert "tools/cc/_post_merge.py lacks `verdicts`" in banner._post_merge_unread()

    def test_a_keyword_catch_all_takes_every_keyword(self):
        banner = _banner()

        def read_required(number, gh, **rest):  # noqa: ARG001
            return None

        assert banner._post_merge_lacks(_older_post_merge(read_required=read_required)) == ""

    def test_no_module_keeps_its_own_line(self, monkeypatch):
        banner = _banner()
        monkeypatch.setattr(banner, "_load_post_merge", lambda: None)
        assert banner._post_merge_unread() == banner._POST_MERGE_UNREAD


# ── every script that takes a sibling arms the reader (DEF-5088) ─────────────

#: The one text every armed script carries, placed right after its leading run
#: of standard-library imports, so no sibling is read before it. Until DEF-5088
#: only ``ship.py`` named a kept sibling; the twenty other scripts that take a
#: sibling's name ended in a traceback naming an attribute (``board.py --help``
#: over a copy whose ``_post_merge.py`` lacks ``RUN_RED``, driven 2026-11-08).
#: Lazy, so a run that raises nothing pays nothing: ``ship.py``'s eager by-path
#: load cost 1.5 ms a run (median of 25 on the Air), and ``statusline.py`` runs at
#: every render. ``_KEPT_*`` are read when the block runs, since ``__main__``'s
#: ``__file__`` can read as None by the time an excepthook runs; the traceback
#: type is aliased because ``_explain_path.py`` evaluates its annotations; the
#: previous hook is put back before the reader installs its own, which wraps it
#: (without that, a raise that is not a kept file's recurses through the hook).
#: Twenty-one copies and no shared module, on purpose: any sibling, a shared one
#: included, may be the kept file, so the block reaches the reader by path with
#: nothing on the way. To change it: edit ARM_BLOCK here, replace HEAD's text of
#: it in every script the population names, then run scripts/sync_vendor_cc.py.
ARM_BLOCK = '''\
# A kept, older sibling is named with its repair, never a traceback that names
# an attribute: an uncaught exception loads hooks/_start_refusal.py by path and
# hands it to that module's refuse_kept_siblings. The one text of this block,
# and why each line is there, is tests/test_kept_sibling.py's ARM_BLOCK.
if __name__ == "__main__":
    from types import TracebackType as _KeptTraceback

    _KEPT_FROM = Path(__file__).resolve().parent
    _KEPT_SCRIPT = Path(__file__).name
    _KEPT_BEFORE = sys.excepthook

    def _name_a_kept_sibling(kind: type[BaseException], exc: BaseException, tb: _KeptTraceback | None) -> None:
        sys.excepthook = _KEPT_BEFORE
        try:
            import importlib.util
            at = (_KEPT_FROM if _KEPT_FROM.name == "hooks" else _KEPT_FROM / "hooks") / "_start_refusal.py"
            spec = importlib.util.spec_from_file_location("_start_refusal_by_path", at)
            if spec is not None and spec.loader is not None:
                reader = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = reader
                spec.loader.exec_module(reader)
                refuse = getattr(reader, "refuse_kept_siblings", None)
                if callable(refuse):
                    reconfigure = getattr(sys.stderr, "reconfigure", None)
                    if callable(reconfigure):
                        reconfigure(encoding="utf-8", errors="replace")
                    refuse(_KEPT_SCRIPT)
        # fail-open: ok deliberate without the reader a kept sibling keeps its traceback, as before
        except Exception:  # noqa: BLE001, S110
            pass
        sys.excepthook(kind, exc, tb)

    sys.excepthook = _name_a_kept_sibling
'''


def _sibling_stems() -> set[str]:
    return {p.stem for p in [*checkout_glob(CC_DIR, "*.py"), *checkout_glob(CC_DIR / "hooks", "*.py")]} - {"__init__"}


def _runs_as_a_script(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in tree.body)


def _armed_population() -> list[Path]:
    """Every ``tools/cc`` source that takes a sibling's name, as the upgrade's
    kept-file check reads it (``espalier/cli.py::_sibling_takes``), and runs as
    a script, less the event hooks (``espalier/surface_contract.py::
    _CANONICAL_HOOK_SCRIPTS``: the deny hooks refuse through their own start
    guard, and no hook path carries this block's weight)."""
    from espalier.cli import _sibling_takes
    from espalier.surface_contract import _CANONICAL_HOOK_SCRIPTS

    names, keywords = _sibling_takes(CC_DIR)
    takers = {rel for taken in names.values() for sources in taken.values() for rel in sources}
    takers |= {rel for calls in keywords.values() for passed in calls.values()
               for sources in passed.values() for rel in sources}
    population = []
    for rel in sorted(takers):
        path = REPO_ROOT / rel
        if path.parent.name == "hooks" and path.name in _CANONICAL_HOOK_SCRIPTS:
            continue
        if _runs_as_a_script(ast.parse(path.read_text(encoding="utf-8"))):
            population.append(path)
    return population


def _head_problems(head: str, siblings: set[str]) -> list[str]:
    """What stands before the block that may not: anything but the docstring and
    imports of modules that are not siblings, and ``sys`` or ``Path`` unbound
    (the block reads both when it runs)."""
    problems: list[str] = []
    bound: set[str] = set()
    for i, node in enumerate(ast.parse(head).body):
        if i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Import):
            tops = {alias.name.split(".")[0] for alias in node.names}
            bound |= {alias.asname or alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            tops = {(node.module or "").split(".")[0]}
            bound |= {alias.asname or alias.name for alias in node.names}
        else:
            problems.append(f"line {node.lineno}: a {type(node).__name__} statement before the block")
            continue
        if tops & siblings:
            problems.append(f"line {node.lineno}: a sibling import before the block")
    problems += [f"`{name}` is not bound before the block" for name in ("sys", "Path") if name not in bound]
    return problems


class TestEveryScriptThatTakesASiblingArmsTheReader:
    def test_the_population_is_the_takers_that_run_as_scripts(self):
        rels = {p.relative_to(REPO_ROOT).as_posix() for p in _armed_population()}
        # A floor, not the census: a walk that read nothing would pass the
        # placement row below on no member at all.
        anchors = {"tools/cc/ship.py", "tools/cc/board.py", "tools/cc/ledger_row.py",
                   "tools/cc/statusline.py", "tools/cc/hooks/_recall.py", "tools/cc/hooks/_explain_path.py"}
        assert anchors <= rels, sorted(anchors - rels)
        assert len(rels) >= 21, sorted(rels)
        assert _HELP_REACHES_NO_TAKE <= rels, sorted(_HELP_REACHES_NO_TAKE - rels)
        # The per-member drive is parametrized over the files carrying the
        # block; held equal here, a member that lost it is named, not skipped.
        assert set(_armed_files()) == rels, (sorted(rels - set(_armed_files())),
                                             sorted(set(_armed_files()) - rels))
        assert not any(rel.endswith(("/write_guard.py", "/stop_gate.py")) for rel in rels)

    def test_every_member_carries_the_one_block_ahead_of_its_siblings(self):
        siblings = _sibling_stems()
        problems: dict[str, list[str]] = {}
        for path in _armed_population():
            rel = path.relative_to(REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            count = text.count(ARM_BLOCK)
            if count != 1:
                problems[rel] = [f"carries the block {count} times"]
            elif found := _head_problems(text[:text.index(ARM_BLOCK)], siblings):
                problems[rel] = found
        assert not problems, (
            "each script that takes a sibling's name carries ARM_BLOCK once, right after its leading"
            " standard-library imports:\n"
            + "\n".join(f"  {rel}: {'; '.join(found)}" for rel, found in sorted(problems.items()))
            + "\nthe block, byte for byte:\n" + ARM_BLOCK)

    def test_the_placement_reader_names_what_stands_before_the_block(self):
        # A control on the reader the row above trusts: a sibling import, a
        # statement and an unbound Path are each named, so an empty answer
        # from it never reads as a clean head.
        head = '"""doc."""\nimport sys\nimport mail\nX = 1\n'
        assert _head_problems(head, {"mail"}) == [
            "line 3: a sibling import before the block",
            "line 4: a Assign statement before the block",
            "`Path` is not bound before the block",
        ]
        assert _head_problems('"""doc."""\nimport sys\nfrom pathlib import Path\n', {"mail"}) == []

    def test_no_event_hook_carries_the_block(self):
        from espalier.surface_contract import _CANONICAL_HOOK_SCRIPTS

        carrying = [name for name in _CANONICAL_HOOK_SCRIPTS
                    if "_name_a_kept_sibling" in (CC_DIR / "hooks" / name).read_text(encoding="utf-8")]
        assert carrying == []


#: Each cell: the script driven, its plants (the file, the text appended) and
#: the name the refusal must give (None: a control that keeps its traceback).
#: ``module_read`` is the row's probe (an attribute read at module level);
#: ``from_import`` a member in ``hooks/`` failing a ``from`` import;
#: ``loader_read`` a sibling loaded by path under an alias, then read.
_SCRIPT_CELLS = {
    "module_read": ("board.py", [("_post_merge.py", "\ndel RUN_RED\n")], "RUN_RED"),
    "from_import": ("hooks/_recall.py", [("hooks/_hook_utils.py", "\ndel is_seeded_placeholder\n")],
                    "is_seeded_placeholder"),
    "loader_read": ("ledger_row.py", [("generate_ledger_regions.py", "\ndel record_fragments\n")],
                    "record_fragments"),
    "raised": ("board.py", [("_post_merge.py", "\nraise KeyError(1)\n")], None),
    "typo": ("board.py", [("_post_merge.py", "\nimport _json_safe as _typo_js\n_TYPO = _typo_js.fold_newlinez\n")],
             "fold_newlinez"),
    "no_reader": ("board.py", [("_post_merge.py", "\ndel RUN_RED\n"),
                               ("hooks/_start_refusal.py", "\ndel refuse_kept_siblings\n")], None),
}


#: The two members whose ``--help`` reaches no take the walker lists:
#: ``generate_ledger_regions.py`` reads its siblings in calls, and
#: ``ledger_row.py`` through ``_load``, a loader handed the module's name
#: (DEF-5089's shape). A block dropped from either is the placement row's to
#: catch, and the population row names both.
_HELP_REACHES_NO_TAKE = frozenset({"tools/cc/generate_ledger_regions.py", "tools/cc/ledger_row.py"})

#: The block's own def line: the collection-time reader of who carries it.
_ARM_DEF_LINE = "    def _name_a_kept_sibling(kind: type[BaseException]"


def _armed_files() -> list[str]:
    """The files carrying the block, read by its def line alone, since the walk
    behind the population costs about two seconds and this runs at collection;
    the population row holds the two sets equal."""
    return sorted("tools/cc/" + p.relative_to(CC_DIR).as_posix()
                  for p in [*checkout_glob(CC_DIR, "*.py"), *checkout_glob(CC_DIR / "hooks", "*.py")]
                  if _ARM_DEF_LINE in p.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _takes_by_taker() -> dict[str, frozenset[str]]:
    """Each taker's sibling modules, by stem, from ``_sibling_takes``'s names."""
    from espalier.cli import _sibling_takes

    names, _keywords = _sibling_takes(CC_DIR)
    by: dict[str, set[str]] = {}
    for module, taken in names.items():
        for sources in taken.values():
            for rel in sources:
                by.setdefault(rel, set()).add(module)
    return {rel: frozenset(modules) for rel, modules in by.items()}


def _sibling_file(cc: Path, stem: str) -> Path:
    """The module ``stem`` names under a ``tools/cc`` copy: top level, else its
    hooks folder (no stem is in both; the walk keys modules by stem)."""
    top = cc / f"{stem}.py"
    return top if top.is_file() else cc / "hooks" / f"{stem}.py"


def _drive_script(tmp_path: Path, script: str, plants: list[tuple[str, str]],
                  empty: Iterable[str] = ()) -> subprocess.CompletedProcess:
    """``script --help`` from a copy of ``tools/cc`` with each plant appended
    to its file and each module stem in ``empty`` kept as an empty file."""
    root = tmp_path / "copy"
    copy_checkout(CC_DIR, root / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))
    for name, text in plants:
        target = root / "tools" / "cc" / name
        target.write_bytes(target.read_bytes() + text.encode("utf-8"))
    for stem in empty:
        _sibling_file(root / "tools" / "cc", stem).write_bytes(b"")
    return subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / script), "--help"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=scaled(30),
    )


class TestAnArmedScriptOnAKeptSibling:
    @pytest.mark.parametrize("cell", ["module_read", "from_import", "loader_read"])
    def test_a_name_a_sibling_lacks_is_one_named_refusal(self, tmp_path, cell):
        script, plants, taken = _SCRIPT_CELLS[cell]
        run = _drive_script(tmp_path, script, plants)
        kept = plants[0][0]
        name = Path(script).name
        assert run.returncode == 1, (run.returncode, run.stderr[-600:])
        _refusal_then_traceback(run.stderr)
        assert run.stderr.startswith(f"{name} cannot run: tools/cc/{script}:"), run.stderr[-600:]
        assert f"takes `{taken}` from tools/cc/{kept}, which lacks it" in run.stderr, run.stderr[-600:]
        assert "`espalier upgrade --execute .`" in run.stderr

    def test_a_typo_under_edit_names_its_read_and_offers_no_restore(self, tmp_path):
        # An edit in progress reads exactly like a kept file: _post_merge.py,
        # the file under edit, asks _json_safe for a name it never had. The
        # refusal names the read and keeps the traceback, and offers no restore,
        # which would discard the edit with no copy kept (air's ruling 92ed0c).
        script, plants, taken = _SCRIPT_CELLS["typo"]
        run = _drive_script(tmp_path, script, plants)
        assert run.returncode == 1, (run.returncode, run.stderr[-600:])
        first = _refusal_then_traceback(run.stderr)
        assert "the error is your read at tools/cc/_post_merge.py:" in first, first
        assert f"`{taken}`" in first, first
        assert f"AttributeError: module '_json_safe' has no attribute '{taken}'" in run.stderr.split("\n", 1)[1]

    def test_a_sibling_that_raises_otherwise_keeps_its_traceback(self, tmp_path):
        script, plants, _taken = _SCRIPT_CELLS["raised"]
        run = _drive_script(tmp_path, script, plants)
        assert run.returncode == 1, run.stderr[-600:]
        assert "Traceback" in run.stderr and "KeyError: 1" in run.stderr, run.stderr[-600:]
        assert "cannot run" not in run.stderr and "Error in sys.excepthook" not in run.stderr

    def test_a_kept_reader_without_the_refusal_leaves_the_traceback_alone(self, tmp_path):
        # A _start_refusal.py kept from before the refusal existed: the block
        # hands the exception on untouched, and never fails inside the hook.
        script, plants, _taken = _SCRIPT_CELLS["no_reader"]
        run = _drive_script(tmp_path, script, plants)
        assert run.returncode == 1, run.stderr[-600:]
        assert "Traceback" in run.stderr and "RUN_RED" in run.stderr, run.stderr[-600:]
        assert "Error in sys.excepthook" not in run.stderr and "cannot run" not in run.stderr

    @pytest.mark.parametrize("member", _armed_files())
    def test_each_member_names_a_sibling_kept_older_than_every_name_it_reads(self, tmp_path, member):
        # Every sibling the member takes a name from is kept as an empty file,
        # a copy older than each name it reads, so whichever read comes first is
        # a kept file's and never a raise inside the sibling: the member names
        # the file that lacks it. The two whose --help reaches no take run clean.
        script = member[len("tools/cc/"):]
        run = _drive_script(tmp_path, script, [], empty=sorted(_takes_by_taker().get(member, ())))
        name = Path(script).name
        if member in _HELP_REACHES_NO_TAKE:
            assert run.returncode == 0 and "Traceback" not in run.stderr, (
                f"{member}'s --help now reaches a take (rc {run.returncode}): drop it from "
                f"_HELP_REACHES_NO_TAKE so its refusal is pinned here\n{run.stderr[-600:]}")
            return
        assert run.returncode == 1, (run.returncode, run.stderr[-600:])
        _refusal_then_traceback(run.stderr)
        assert run.stderr.startswith((f"{name} cannot run: tools/cc/", f"{name} stopped: tools/cc/")), \
            run.stderr[-600:]
        assert ", which lacks it (" in run.stderr, run.stderr[-600:]

    def test_the_intact_copy_prints_its_usage(self, tmp_path):
        run = _drive_script(tmp_path, "board.py", [])
        assert run.returncode == 0, run.stderr[-600:]
        assert run.stdout.startswith("usage: board.py"), run.stdout[:200]
        assert run.stderr == ""
