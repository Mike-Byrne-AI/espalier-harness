"""A kept, older ``tools/cc/`` sibling is named with its repair (DEF-5087).

``espalier upgrade`` keeps a managed script that drifted and carries no marker
(``espalier/cli.py::_deploy_managed_py``, its ``skipped_user_file`` answer) and
regenerates the siblings beside it, so a regenerated script can take a name the
kept copy lacks. Until DEF-5087 every ship driver verb, ``--help`` included,
then ended in a traceback naming an attribute. These rows drive the driver from
a copy of ``tools/cc`` with one name gone from a sibling (the row's probe), and
read the one reader every refusal of this shape goes through
(``tools/cc/hooks/_start_refusal.py::_missing_sibling_name``) on the shapes it
must not read as a kept file.
"""
# slow-exempt: four ship.py --help children over copied tools/cc trees, each under a second
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests._live_tree import copy_checkout
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
        assert "Traceback" not in run.stderr, run.stderr[-600:]
        assert run.stderr.startswith("ship.py cannot run: tools/cc/"), run.stderr[-600:]
        taker = run.stderr[len("ship.py cannot run: "):].split(" takes `", 1)[0]
        assert taker.rsplit(":", 1)[1].isdigit(), taker   # the file and its line (the review's NIT 8)
        assert f"`{taken}`" in run.stderr
        assert f"from tools/cc/{name}, which lacks it" in run.stderr
        assert f"If an upgrade kept {name} as yours" in run.stderr
        assert "`# espalier:managed` marker line" in run.stderr
        assert "`espalier upgrade --execute .`" in run.stderr
        assert f"tools/cc/{name}" in run.stderr.split("restore the edited file to HEAD:", 1)[1]
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
        assert run.returncode == 1 and "Traceback" not in run.stderr, run.stderr[-600:]
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
