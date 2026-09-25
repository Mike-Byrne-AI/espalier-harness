"""TP-95: wheel/sdist payload hygiene contract.

The self-hosted `ESPALIER_MEMORY.md` is a harness-development memory log carrying
TP-IDs, BC-NN class references, and harness-internal vocabulary. Before
TP-95, `MANIFEST.in:16` had an affirmative ``include ESPALIER_MEMORY.md`` that
shipped the file in the sdist. The wheel never contained root files by
default (setuptools doesn't auto-include them), so the leak was
sdist-only — but this contract asserts both directions so a future
refactor that adds root files to wheels can't silently regress.

The adopter-facing template at ``examples/ESPALIER_MEMORY.template.md`` must
remain in the inspectable sdist payload. The wheel does not ship it
because ``examples/`` is not a Python package; the wheel ships the
``espalier/`` package (including the vendored ``espalier/_vendor/cc/``
deploy-source) plus package-data. TP-178 stopped the wheel shipping a bare
top-level ``tools`` package, which squatted that generic import name.

Dual-witness shape (cf. tests/test_release_denylist.py): the wheel
witness and the sdist witness are built independently and asserted
against independently — a single MANIFEST.in regression cannot pass
both at once.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from espalier.artifact_parity import clear_stale_packaging_state

REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_available() -> bool:
    """True only when `python -m build` can be executed by this interpreter."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--help"],
            capture_output=True, text=True, timeout=10, check=False, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0 or "usage" not in (result.stdout + result.stderr).lower():
        return False
    # `build --help` succeeds even without a build backend; the real build
    # (`--no-isolation`) needs setuptools.build_meta, which 3.12+ venvs no
    # longer bundle -- assert it so the skip-guard stops green-washing (W0-2).
    backend = subprocess.run(
        [sys.executable, "-c", "import setuptools.build_meta"],
        capture_output=True, text=True, timeout=10, check=False, encoding="utf-8",
    )
    return backend.returncode == 0


def _require_build_or_skip() -> None:
    """Hard-fail when `python -m build` is missing unless opt-out is set.

    Matches the convention from tests/test_artifact_parity.py — silent
    skip in CI is a silent failure mode for packaging contracts.
    """
    if _build_available():
        return
    if os.environ.get("ESPALIER_ALLOW_PARITY_SKIP") == "1":
        pytest.skip(
            "python -m build unavailable; ESPALIER_ALLOW_PARITY_SKIP=1 set"
        )
    pytest.fail(
        "python -m build is required for wheel/sdist payload contract. "
        "Install with: pip install build. If this environment legitimately "
        "cannot build, set ESPALIER_ALLOW_PARITY_SKIP=1 explicitly."
    )


def _clean_build_dir() -> None:
    """Delegate. The two staleness channels (``build/lib``, which build_py
    never prunes, and ``*.egg-info/SOURCES.txt``, the cached manifest that
    left every payload contract here verifying the PREVIOUS config until it
    was cleared too -- driven three ways on the package-data globs) now have
    one home, ``espalier.artifact_parity.clear_stale_packaging_state``,
    called from every build path. Kept by name because
    ``docs/sharp-edges/include-package-data-ships-tracked-assets.md`` cites
    it.
    """
    clear_stale_packaging_state(REPO_ROOT)


@pytest.fixture(scope="module")
def _built_wheel(tmp_path_factory) -> Path:
    """Build a fresh wheel once per module run."""
    _require_build_or_skip()
    _clean_build_dir()
    dest = tmp_path_factory.mktemp("tp95_wheel")
    subprocess.check_call(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(dest)],
        cwd=str(REPO_ROOT),
    )
    wheels = sorted(dest.glob("espalier_harness-*.whl"))
    assert wheels, f"no wheel produced in {dest}"
    return wheels[-1]


@pytest.fixture(scope="module")
def _built_sdist(tmp_path_factory) -> Path:
    """Build a fresh sdist once per module run."""
    _require_build_or_skip()
    _clean_build_dir()
    dest = tmp_path_factory.mktemp("tp95_sdist")
    subprocess.check_call(
        [sys.executable, "-m", "build", "--sdist", "--no-isolation",
         "--outdir", str(dest)],
        cwd=str(REPO_ROOT),
    )
    sdists = sorted(dest.glob("espalier_harness-*.tar.gz"))
    assert sdists, f"no sdist produced in {dest}"
    return sdists[-1]


class TestWheelPayloadExclusion:
    """Wheel must not ship self-host ESPALIER_MEMORY.md.

    Root-level files like ESPALIER_MEMORY.md aren't typically swept into wheels
    by setuptools, but this contract makes the absence permanent so a
    future package-data change can't silently regress.
    """

    def test_wheel_excludes_self_host_memory(self, _built_wheel):
        with zipfile.ZipFile(_built_wheel) as zf:
            names = zf.namelist()
        root_memory = [n for n in names if n.endswith("/ESPALIER_MEMORY.md") or n == "ESPALIER_MEMORY.md"]
        # espalier/assets/memory/ is package data and is permitted;
        # only the root-level ESPALIER_MEMORY.md (the self-host log) is denied.
        forbidden = [n for n in root_memory if "/assets/memory/" not in n]
        assert not forbidden, (
            f"wheel must not contain root-level ESPALIER_MEMORY.md; found: {forbidden}"
        )

    def test_wheel_ships_every_seed_asset(self, _built_wheel):
        """Every init-seeded doc's packaged body must be IN the wheel.

        The adopter stubs live outside ``espalier/assets/docs/`` (see
        ``managed_inventory._SEED_ASSET_SOURCES``), so they ship only via their
        own ``assets/seed/*.md`` package-data glob. A missing glob is invisible
        in the source tree and in an editable install — the failure surfaces
        only for a wheel adopter, as an ``init`` that raises mid-deploy on a
        seed asset it cannot read. Resolve through the same accessor the deploy
        loop uses, so this covers the identity path and the overridden path
        with one oracle.
        """
        from espalier.managed_inventory import get_seed_asset_source, get_seed_docs

        with zipfile.ZipFile(_built_wheel) as zf:
            names = set(zf.namelist())
        missing = [
            f"{dest} <- espalier/assets/{src}"
            for dest, src in ((d, get_seed_asset_source(d)) for d in get_seed_docs())
            if f"espalier/assets/{src}" not in names
        ]
        assert not missing, (
            "wheel is missing the packaged body for an init-seeded doc; a wheel "
            "adopter's `espalier init` fails mid-deploy:\n  " + "\n  ".join(missing)
        )

    def test_wheel_python_members_are_all_tracked(self, _built_wheel):
        """Sister of the sdist row: the wheel's package-data sweep is a
        filesystem walk too, so an untracked `.py` under `espalier/` ships."""
        from espalier.surface_contract import tracked_paths
        tracked = tracked_paths(REPO_ROOT)
        assert tracked is not None and len(tracked) > 500
        with zipfile.ZipFile(_built_wheel) as zf:
            names = zf.namelist()
        untracked = sorted(
            n for n in names
            if n.endswith(".py") and ".dist-info/" not in n and n not in tracked
        )
        assert not untracked, (
            f"wheel ships Python files git does not track: {untracked}. The "
            f"build swept them off the filesystem; `git add` them or remove them "
            f"before building."
        )

    def test_wheel_excludes_top_level_tools_package(self, _built_wheel):
        # TP-178 (W2-1): the wheel must NOT ship a bare top-level `tools`
        # package — it squatted the generic `tools` import name in every
        # environment that installed Espalier (an irreversible PyPI namespace
        # squat once published). The deploy source ships under
        # espalier/_vendor/cc/ instead. Assert against the ZIP namelist, NOT
        # top_level.txt: a stale build/lib re-shipped tools/ while top_level.txt
        # correctly read espalier-only — packaging metadata can lie.
        with zipfile.ZipFile(_built_wheel) as zf:
            names = zf.namelist()
        squat = [n for n in names if n == "tools" or n.startswith("tools/")]
        assert not squat, (
            "wheel ships a top-level tools/ package (PyPI namespace squat); "
            f"found {len(squat)} entries e.g. {sorted(squat)[:5]}. Ensure "
            "pyproject packages.find drops 'tools*' AND build/ is clean before "
            "the release build (a stale build/lib/tools re-ships silently)."
        )
        vendored = [n for n in names if n.startswith("espalier/_vendor/cc/")]
        assert vendored, (
            "wheel is missing espalier/_vendor/cc/ deploy-source — the "
            "package-data globs (_vendor/cc/*.py, _vendor/cc/hooks/*.py) are "
            "not shipping; init/install-ci would have no source to copy from."
        )
        # Depth invariant: EVERY vendored deploy-source file in the source tree
        # (.py, and the .cmd Windows statusline shim -- DEF-729) must ship in
        # the wheel. The 2-level package-data globs miss any 3rd-level subdir
        # (e.g. _vendor/cc/hooks/sub/foo.py), so cross-check the full set, not
        # just non-emptiness.
        vendor_src = REPO_ROOT / "espalier" / "_vendor" / "cc"
        expected = {
            f"espalier/_vendor/cc/{p.relative_to(vendor_src).as_posix()}"
            for p in vendor_src.rglob("*")
            if p.is_file() and p.suffix in (".py", ".cmd") and "__pycache__" not in p.parts
        }
        assert "espalier/_vendor/cc/statusline.cmd" in expected, sorted(expected)[:5]
        missing = sorted(expected - set(names))
        assert not missing, (
            "wheel is missing vendored deploy-source files (package-data glob "
            f"too shallow for their depth, or the suffix unlisted?): {missing}. Add a "
            "matching _vendor/cc/**/*.py or *.cmd glob to pyproject "
            "[tool.setuptools.package-data]."
        )


class TestSdistPayloadShape:
    """Sdist must exclude self-host ESPALIER_MEMORY.md AND include adopter template.

    This is the half where TP-95 actually fixes a regression — before
    the MANIFEST.in change, ``include ESPALIER_MEMORY.md`` shipped the
    harness-dev memory log to anyone untarring the source archive.
    """

    def test_sdist_excludes_self_host_memory(self, _built_sdist):
        with tarfile.open(_built_sdist, "r:gz") as tf:
            names = tf.getnames()
        # Filter to root-level ESPALIER_MEMORY.md (one path segment after the
        # archive's top-level directory); allow espalier/assets/memory/.
        root_memory = [
            n for n in names
            if n.endswith("/ESPALIER_MEMORY.md") and "/assets/memory/" not in n
            and n.count("/") == 1  # archive_top/ESPALIER_MEMORY.md == one slash
        ]
        assert not root_memory, (
            f"sdist must not contain root-level ESPALIER_MEMORY.md (the self-host "
            f"harness-dev log); found: {root_memory}. Check MANIFEST.in for "
            f"a re-introduced affirmative include rule."
        )

    def test_sdist_includes_adopter_template(self, _built_sdist):
        with tarfile.open(_built_sdist, "r:gz") as tf:
            names = tf.getnames()
        templates = [n for n in names if n.endswith("examples/ESPALIER_MEMORY.template.md")]
        assert templates, (
            "sdist must include examples/ESPALIER_MEMORY.template.md (the "
            "adopter-facing template); check MANIFEST.in for the "
            "recursive-include examples *.md rule."
        )

    def test_sdist_includes_tools_source(self, _built_sdist):
        # TP-178: the wheel drops the top-level `tools` package (it squatted the
        # generic `tools` import name), but the sdist MUST keep tools/cc/*.py —
        # it is the source-reader deploy copy for anyone building from sdist
        # (MANIFEST.in `recursive-include tools *.py`). No other test pins this
        # positive direction, so dropping that include rule would silently strip
        # the source readers' copy with nothing failing.
        with tarfile.open(_built_sdist, "r:gz") as tf:
            names = tf.getnames()
        tools_py = [n for n in names if "/tools/cc/" in n and n.endswith(".py")]
        assert tools_py, (
            "sdist must ship tools/cc/*.py (the source-reader deploy copy); "
            "check MANIFEST.in retains `recursive-include tools *.py`."
        )
        assert any(n.endswith("tools/cc/hooks/write_guard.py") for n in tools_py), (
            "sdist is missing tools/cc/hooks/write_guard.py — the "
            "recursive-include may have been narrowed."
        )

    def test_sdist_includes_bench_baseline_setup_scripts(self, _built_sdist):
        # LICENSE-1: run_benchmark.py hard-requires bench/baselines/<name>/setup.sh
        # (run_benchmark.py raises FileNotFoundError without it). MANIFEST.in shipped
        # only `*.json *.md` under bench/baselines — the `*.json` matched nothing (a
        # dead pattern that warned every build) and `*.sh` was absent, so an sdist
        # consumer running the adversarial benchmark dead-ended on baseline one. No
        # other test pins this positive direction; narrowing the include rule would
        # silently strip the scripts again.
        with tarfile.open(_built_sdist, "r:gz") as tf:
            names = tf.getnames()
        setup_scripts = [
            n for n in names
            if "/bench/baselines/" in n and n.endswith("/setup.sh")
        ]
        assert setup_scripts, (
            "sdist must ship bench/baselines/*/setup.sh (run_benchmark.py "
            "requires them); check MANIFEST.in has "
            "`recursive-include bench/baselines *.sh *.md`."
        )
        # Shape: all four baselines' setup.sh ship — a narrowed include that
        # dropped one baseline dir would still pass the presence check above.
        for baseline in ("espalier", "minimal-hooks", "no-governance",
                         "settings-deny-only"):
            assert any(
                n.endswith(f"bench/baselines/{baseline}/setup.sh")
                for n in setup_scripts
            ), f"sdist is missing bench/baselines/{baseline}/setup.sh."

    def test_sdist_includes_dogfooding_mirror(self, _built_sdist):
        """98-F: the dogfooding reference mirror at
        examples/dogfooding/.claude/ ships in the sdist intentionally.

        Pre-98-F the test only asserted ESPALIER_MEMORY.template.md presence;
        nothing pinned the dogfooding-mirror inclusion either way. A
        future contributor "tidying" MANIFEST.in could narrow the
        recursive-include and silently drop the ~32 .md files of
        agents/commands/skills reference content — adopters
        inspecting the sdist would lose the working reference config
        with no contract firing.

        Pin both presence (sample files exist) and shape (the mirror
        spans agents + commands + skills subdirectories).
        """
        with tarfile.open(_built_sdist, "r:gz") as tf:
            names = tf.getnames()

        mirror_files = [
            n for n in names
            if "examples/dogfooding/.claude/" in n and n.endswith(".md")
        ]
        assert mirror_files, (
            "sdist must include examples/dogfooding/.claude/**/*.md "
            "(the dogfooding reference mirror that adopters compare "
            "against when customizing). Check MANIFEST.in for the "
            "'recursive-include examples *.md' rule — removing or "
            "narrowing it silently drops this content."
        )

        # Shape check: the mirror has agents/, commands/, skills/.
        # If a future change drops a whole subdirectory, fire here.
        for subdir in ("agents/", "commands/", "skills/"):
            hits = [n for n in mirror_files
                    if f"examples/dogfooding/.claude/{subdir}" in n]
            assert hits, (
                f"sdist dogfooding mirror is missing the {subdir} "
                f"subtree. Check MANIFEST.in didn't get narrowed to "
                f"exclude examples/dogfooding/.claude/{subdir}."
            )


class TestSdistClassifierDrivenPayload:
    """TP-176 W1: bind the built-sdist payload to the SoT classifier.

    The sdist include/exclude list (MANIFEST.in) is hand-maintained and not
    derived from classify_release_path(); the release zip's
    is_internal_release_leak() filter and the wheel (setuptools package-data)
    are. git-archive uses its own hand-maintained .gitattributes export-ignore
    list, whose membership intentionally diverges from the classifier (ESPALIER_MEMORY.md
    is classify=='public' yet export-ignored; docs/session-archive.md is
    'internal' yet excluded only because it is untracked). These two contracts
    bind the sdist to the classifier from both sides:

      * no classify_release_path=='internal' file may ship (absence — catches
        docs/session-archive.md and any future file the classifier already
        marks 'internal'; a not-yet-classified sister, e.g. a hypothetical
        docs/session-archive-v2.md, classifies 'public' and would NOT be
        caught — closing that needs a classifier pattern change, out of scope);
      * every pre_release.REQUIRED_PUBLIC_FILES entry must ship (presence —
        catches the SECURITY.md / CODE_OF_CONDUCT.md drop). That tuple is
        the whole list: nothing in the repo actually links CODE_OF_CONDUCT.md,
        so "plus the linked community-health files" described a set that
        does not exist.

    Both run against a freshly *built* sdist, not the working tree. The
    release gate (release_check / pre_release._check_required_files) only
    inspects the source tree, so a MANIFEST omission or leak passes it
    green — these contracts are the artifact-level witness.
    """

    @staticmethod
    def _sdist_relpaths(sdist: Path) -> list[str]:
        """Members with the archive's top-level directory stripped."""
        with tarfile.open(sdist, "r:gz") as tf:
            names = tf.getnames()
        rel = []
        for n in names:
            parts = n.split("/", 1)
            if len(parts) == 2 and parts[1]:
                rel.append(parts[1])
        return rel

    def test_sdist_python_members_are_all_tracked(self, _built_sdist):
        """setuptools enumerates the FILESYSTEM (no setuptools_scm in the build
        requires), so an untracked `.py` lying under a swept package dir at
        build time ships in the sdist -- driven on a replica of this packaging
        config, 2026-09-08. The bespoke archive builders enumerate the git
        index since the same day; the PyPI path cannot without a packaging
        change (a ledger row holds it), so this is the artifact-level witness:
        every Python member must be in the index at build time."""
        from espalier.surface_contract import tracked_paths
        tracked = tracked_paths(REPO_ROOT)
        assert tracked is not None and len(tracked) > 500
        untracked = sorted(
            rel for rel in self._sdist_relpaths(_built_sdist)
            if rel.endswith(".py") and not rel.startswith("espalier_harness.egg-info")
            and rel not in tracked
        )
        assert not untracked, (
            f"sdist ships Python files git does not track: {untracked}. The "
            f"build swept them off the filesystem; `git add` them or remove them "
            f"before building."
        )

    def test_sdist_excludes_internal_classified_files(self, _built_sdist):
        """No classify_release_path=='internal' file may ship in the sdist."""
        from espalier.surface_contract import classify_release_path

        leaks = []
        for rel in self._sdist_relpaths(_built_sdist):
            # setuptools' own sdist metadata dir is always present and is
            # not source content — never a leak.
            if rel == "espalier_harness.egg-info" or rel.startswith(
                "espalier_harness.egg-info/"
            ):
                continue
            if classify_release_path(rel) == "internal":
                leaks.append(rel)
        assert not leaks, (
            "sdist ships classify_release_path=='internal' file(s): "
            f"{sorted(leaks)}. A recursive-include swept them in; add an "
            "`exclude` rule to MANIFEST.in mirroring the classifier. "
            "(This is the docs/session-archive.md self-host-log leak class.)"
        )

    def test_sdist_includes_required_public_files(self, _built_sdist):
        """Every release-gate-required public root file must ship."""
        from espalier.pre_release import REQUIRED_PUBLIC_FILES

        root_members = {
            rel for rel in self._sdist_relpaths(_built_sdist) if "/" not in rel
        }
        # REQUIRED_PUBLIC_FILES is the release-gate SoT and now carries
        # CODE_OF_CONDUCT.md itself, so this reads the tuple straight. The
        # manual `| {"CODE_OF_CONDUCT.md"}` union that used to sit here was
        # the compensating half of a gate that did not require the CoC at
        # all; keeping it once the SoT covers it would hide which list is
        # authoritative.
        required = set(REQUIRED_PUBLIC_FILES)
        missing = sorted(f for f in required if f not in root_members)
        assert not missing, (
            "sdist is missing required public root file(s): "
            f"{missing}. Add `include <file>` to MANIFEST.in's core block. "
            "README.md / CONTRIBUTING.md link to SECURITY.md, so its "
            "absence leaves dangling in-archive links."
        )


class TestShippedBenchmarkReproducesFromSdist:
    """BENCH-03: the published reproduction command must work on the artifact.

    ``bench/RESULTS.md`` publishes a 153/153 in-scope figure and tells a reader
    to reproduce it with ``python bench/run_benchmark.py``. The sdist ships
    ``bench/`` but ``MANIFEST.in`` prunes ``tests/`` and ``scripts/`` wholesale,
    so the shipped runner could not reach ``tests/_corpus_ref_resolver.py`` (it
    imports it) or ``scripts/release_check.py`` (BC-010 targets it). Measured
    before the fix: **147/153, exit 2** — a published benchmark that fails to
    reproduce its own published number, on the one surface whose entire job is
    credibility.

    Two targeted ``include`` lines fix it without un-pruning either tree. This
    test is the guard that keeps them: delete either line and the reproduction
    silently regresses to 147/153 again, which no other contract notices.
    """

    # ~15s idle, but it drives the whole 154-attempt corpus through a real
    # guard subprocess per row, so its cost tracks corpus growth (39 -> 154
    # in-scope since the 60s global ceiling was set) and it degrades sharply
    # under machine load. `timeout_method = "thread"` kills the WHOLE run on a
    # breach, so a breach here costs the entire suite rather than one test.
    # Covered by _SLOW_FILES membership, so the timeout contract needs no
    # module-wide exempt marker (which would blanket future sites here).
    @pytest.mark.timeout(300)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "the shipped runner shells `bash` for each baseline's setup.sh "
            "(bench/run_benchmark.py::setup_baseline); Windows has no usable "
            "bash, so this measures the runner's shell, not the sdist payload"
        ),
    )
    def test_shipped_runner_scores_full_in_scope_from_the_sdist(
        self, _built_sdist, tmp_path
    ):
        extract_root = tmp_path / "sdist_bench"
        with tarfile.open(_built_sdist, "r:gz") as tf:
            tf.extractall(extract_root, filter="data")
        inner = next(p for p in extract_root.iterdir() if p.is_dir())

        runner = inner / "bench" / "run_benchmark.py"
        assert runner.exists(), (
            "the sdist no longer ships bench/run_benchmark.py — RESULTS.md's "
            "documented reproduction command cannot run at all"
        )

        proc = subprocess.run(
            [sys.executable, str(runner)],
            cwd=str(inner),
            capture_output=True,
            text=True, encoding="utf-8",
        )
        combined = proc.stdout + proc.stderr

        # The espalier baseline line is the published figure.
        match = re.search(
            r"espalier\s+in-scope blocked:\s*(\d+)/(\d+)\s+OOS allowed:\s*(\d+)/(\d+)",
            combined,
        )
        assert match, (
            "could not parse the espalier baseline line from the shipped "
            f"runner's output — did the report format change?\n{combined[-2000:]}"
        )
        blocked, total, oos_ok, oos_total = (int(g) for g in match.groups())

        assert (blocked, total) == (total, total) and (oos_ok, oos_total) == (
            oos_total,
            oos_total,
        ), (
            f"shipped benchmark scored {blocked}/{total} in-scope and "
            f"{oos_ok}/{oos_total} OOS from the sdist. RESULTS.md publishes a "
            "full in-scope score and tells readers to reproduce it with this "
            "command. A shortfall means MANIFEST.in stopped shipping a file "
            "the corpus needs (check the targeted `include tests/"
            "_corpus_ref_resolver.py` / `include scripts/release_check.py` "
            f"lines).\n{combined[-2000:]}"
        )
        assert proc.returncode == 0, (
            f"shipped runner exited {proc.returncode} from the sdist "
            f"(expected 0)\n{combined[-2000:]}"
        )


# ---------------------------------------------------------------------------
# ARCHIVE-03, sdist leg. Same class as the git-archive guard in
# tests/test_git_archive_parity.py, different exclusion mechanism: the archive
# drops files via .gitattributes export-ignore, the sdist via MANIFEST.in.
# A doc can therefore be clean in one artifact and broken in the other.
# ---------------------------------------------------------------------------

# Trees MANIFEST.in prunes ON PURPOSE, with the rationale recorded there:
# shipping tests/ breaks ~25 source-tree assertions from an sdist install, and
# .github/ + folder-router .md files are dev surface. A doc that references a
# REAL file under one of these is making a dev-facing reference, not rotting.
#
# The `must still exist in the repo` condition is what keeps this from becoming
# a blanket: a link to tests/does_not_exist.py reds here exactly as it would
# anywhere else. The shape is exempt; a phantom is never exempt.
_SDIST_PRUNED_PREFIXES: tuple[str, ...] = (
    "tests/",
    "scripts/",
    ".github/",
)


def _is_pruned_dev_reference(candidates: list[str]) -> bool:
    for cand in candidates:
        if not (REPO_ROOT / cand).exists():
            continue
        if cand.startswith(_SDIST_PRUNED_PREFIXES):
            return True
        # tools/ ships *.py only; its folder-router .md files are dev surface.
        if cand.startswith("tools/") and not cand.endswith(".py"):
            return True
    return False


class TestSdistLinksResolveInsideThePayload:
    """A doc shipped in the sdist may not link to something the sdist lacks."""

    # espalier/assets/** are templates for the tree `init` deploys them into —
    # same rationale as ARTIFACT_LINK_ALLOWLIST in test_git_archive_parity.py.
    # That the targets land on the deployed tree is proven against a driven
    # `init` by tests/test_adopter_pointer_resolution.py.
    _ALLOWLIST: dict[str, str] = {
        "espalier/assets/seed/SHARP_EDGES.md -> sharp-edges/":
            "seed stub; docs/sharp-edges/ is deployed by init",
        "espalier/assets/task-packs/CLAUDE.md -> ../.claude/commands/scope-check.md":
            "seed template; deployed by init",
        "espalier/assets/task-packs/CLAUDE.md -> ../.claude/skills/blueprint-authoring/SKILL.md":
            "seed template; deployed by init",
    }

    def test_sdist_has_no_dangling_relative_links(self, _built_sdist, tmp_path):
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from _artifact_links import artifact_members, iter_relative_links

        dest = tmp_path / "sdist_links"
        with tarfile.open(_built_sdist, "r:gz") as tf:
            tf.extractall(dest, filter="data")
        root = next(p for p in dest.iterdir() if p.is_dir())

        present = artifact_members(root)
        violations: list[str] = []
        resolved = 0
        for path in sorted(root.rglob("*.md")):
            rel = str(path.relative_to(root)).replace("\\", "/")
            text = path.read_text(encoding="utf-8", errors="replace")
            for target, candidates, _fragment in iter_relative_links(text, rel):
                if any(c in present for c in candidates):
                    resolved += 1
                    continue
                if _is_pruned_dev_reference(candidates):
                    continue
                key = f"{rel} -> {target}"
                if key in self._ALLOWLIST:
                    continue
                violations.append(key)

        assert resolved >= 100, (
            f"only {resolved} relative links resolved inside the sdist — the "
            "extractor or the payload changed and this gate is near-vacuous."
        )
        assert not violations, (
            "doc(s) shipped in the sdist link to a target the sdist does not "
            "carry. Note this is a DIFFERENT exclusion mechanism from the "
            "git-archive guard (MANIFEST.in vs export-ignore), so a doc can be "
            "clean there and broken here:\n  " + "\n  ".join(violations)
        )

    def test_pruned_prefix_exemption_still_reds_on_a_phantom(self, _built_sdist):
        """The pruned-tree exemption is a SHAPE, never a blanket.

        A reference to a real file under a pruned tree is a dev-facing
        reference. A reference to a file that does not exist anywhere is rot,
        and must red even under the same prefix — otherwise the exemption
        silently absorbs the class it was scoped to narrow.
        """
        assert _is_pruned_dev_reference(["tests/conftest.py"]), (
            "a real file under a pruned tree should be treated as a dev reference"
        )
        assert not _is_pruned_dev_reference(["tests/test_does_not_exist_anywhere.py"]), (
            "a PHANTOM under a pruned tree must NOT be exempt — that would let "
            "the exemption swallow real citation rot"
        )


def test_the_build_fixtures_clear_stale_state_before_the_builder():
    """The one build path with a recorded false green (payload contracts read
    against a cached manifest) is pinned like the other four: in each fixture
    the delegate's call precedes the builder's, by source position. Fails if
    either call is dropped or the two swap."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    fixtures = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in ("_built_wheel", "_built_sdist")
    }
    assert set(fixtures) == {"_built_wheel", "_built_sdist"}
    for name, fn in fixtures.items():
        calls = sorted(
            (node.lineno, ast.unparse(node.func))
            for node in ast.walk(fn) if isinstance(node, ast.Call)
        )
        names = [func for _, func in calls]
        assert "_clean_build_dir" in names and "subprocess.check_call" in names, (name, names)
        assert names.index("_clean_build_dir") < names.index("subprocess.check_call"), (name, names)
