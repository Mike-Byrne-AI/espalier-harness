"""Fingerprint a repository — detect languages, frameworks, conventions, and risk signals."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from espalier._report_io import safe_text
from espalier._safe_walk import has_git_entry, safe_rglob
from espalier.managed_inventory import get_local_runtime_prefixes
from espalier.managed_markers import path_has_seed_stamp
from espalier.managed_paths import HARNESS_OWNED_ROOTS
from espalier.models import HarnessConfig, LargeFile, RepoFingerprint, Signal
from espalier.profiles import classify_repo


SUFFIX_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".php": "php",
    ".rb": "ruby",
}
DEFAULT_SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    # Type-checker/linter caches. The sibling scanner (scanners.godfiles's
    # DEFAULT_EXCLUDE) already skipped both; this walker did not, so a real run
    # reported 15 `.mypy_cache/*/cache*.db` rows out of 23 large files. The two
    # sets are NOT nested in either direction — godfiles omits coverage/htmlcov/
    # .next/target and adds `cc` — so this is a targeted parity fix, not a merge.
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    ".next",
    "target",
}
# Harness output, as POSIX-style repo-relative path prefixes, matched against
# `_rel(path, repo_root)` by `is_harness_output` -- never by basename, so a
# user's `tools/` is not excluded because its basename matches: only
# `tools/cc/` is Espalier-Harness's. DERIVED from the two inventory owners,
# not re-listed: `managed_paths.HARNESS_OWNED_ROOTS` (`.claude`, `cc`,
# `tools/cc` -- the deployed surface) and
# `managed_inventory.get_local_runtime_prefixes()` (`.espalier/`,
# `.espalier-state/`, `reports/`, `cc/blueprints/` -- what the runtime writes
# per session). `bench/results` is the self-host benchmark's output,
# gitignored and never deployed, so no inventory names it. Until 2026-09-12
# this tuple was a hand copy (`tools/cc`, `reports`, `.claude`,
# `cc/blueprints`, `bench/results`) beside a SECOND hand copy that
# `detect_runtime_surface` consulted (`{".claude", "reports", "cc"}`), and the
# bare-existence detectors consulted neither: a fresh init on a three-file
# repo fingerprinted the `docs/` directory the seeds had just created as the
# adopter's docs surface -- a cue, a `docs_surface` signal and two convention
# lines, saved into reports/repo_fingerprint.json and the build plan because
# `cmd_init` seeds before it fingerprints (DEF-410f, driven). One predicate
# now; every consumer in this module reads it.
#
# A PATH prefix is the wrong key for the seeded docs: the ~20 seeds
# (`managed_inventory.get_seed_docs()`) land at adopter paths
# (`docs/FAILURE_MODES.md`, 464 KB when DEF-686 was driven on 2026-09-05 and
# growing) and are adopter-OWNED after init, so the
# same path unstamped IS the adopter's doc. Those are excluded by CONTENT --
# `managed_markers.path_has_seed_stamp` on the first line -- in `_iter_files`
# and in `detect_docs_surface`, whose `docs` cue needs one adopter-owned file
# in the tree, not the directory the seeds made (DEF-686 closed the file leg
# on 2026-09-05: `Large files detected` naming a seed, a `docs_heavy` profile
# and 20 seeded "docs surface cues" on every wheel install since 2026-07-12).
#
# Adding a detector: a bare `(repo_root / X).exists()` on a path the harness
# deploys is the leak shape. `tests/test_analyze.py::TestBareExistenceCensus`
# walks every such literal in this module against the deployed-path oracle;
# a probe that must stay (install-ci's workflow is a true fact, re-baselined
# at the writer under DEF-688) is a rostered count and reason there, and
# `tests/test_init_fingerprint_differential.py` drives a real `init` on a
# three-file repo for whatever a literal census cannot see (an `iterdir()`
# walk): no fingerprint field may change.
HARNESS_OUTPUT_PREFIXES: tuple[str, ...] = tuple(dict.fromkeys((
    *HARNESS_OWNED_ROOTS,
    *(prefix.rstrip("/") for prefix in get_local_runtime_prefixes()),
    "bench/results",
)))


def is_harness_output(rel: str) -> bool:
    """True when the repo-relative POSIX path is, or is under, harness output.

    The one owner of the harness-output exclusion inside the fingerprint:
    ``_iter_files`` (every file-walker detector), ``detect_runtime_surface``
    (the top-level package scan) and the census in ``tests/test_analyze.py``
    read it. Bounded on a path segment, so ``tools/cc`` excludes
    ``tools/cc/x`` and not ``tools/ccache/``.
    """
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in HARNESS_OUTPUT_PREFIXES)


KNOWN_GENERATED = ["dist", "build", "coverage", "htmlcov", "node_modules", ".next", "target"]
SUSPICIOUS_FILENAMES = {
    "cc_surface_gate.py",
    "cc_rebuild_manifest.ps1",
    "surface_gate_copy.txt",
}
SUSPICIOUS_CONTENT = [
    "SUMMARY OF LESS COMMANDS",
    "diff --git a/",
    "...skipping...",
    "unexpected EOF while looking for matching",
    "PSSecurityException",
]
ENTRYPOINT_CANDIDATES = ["main.py", "app.py", "api.py", "manage.py", "server.py", "wsgi.py", "asgi.py"]
RUNTIME_DIR_CANDIDATES = ["src", "lib", "frontend", "backend", "service", "services", "apps", "packages"]
MANIFEST_NAMES = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle"}


# Trivial posix-relative idiom (`.replace("\\", "/")`) that CLAUDE.md mandates inline
# repo-wide. Intentional twin of reflect_protocol._rel (both mirrors) — a shared helper
# is negative-ROI and the tools/cc leg is a forced no-import boundary anyway. Leave inline.
def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


# allow-text-scan-of-structured-config: analyze.py reads
# pyproject.toml / package.json as a *characterization signal* for repo
# fingerprinting (does the repo mention pytest? ruff? streamlit?). The
# substring heuristics are tolerant by design — a false positive at most
# adds a non-canonical command suggestion. Structural tomllib parsing is
# overkill for the use case and would require sister-site changes across
# the dependency-parsing surface. Sites: detect_tests / _detect_actions /
# detect_ui_surface / _detect_conventions.
def _safe_text(path: Path) -> str:
    return safe_text(path)


def _safe_package_json(repo_root: Path) -> dict:
    package_json = repo_root / "package.json"
    if not package_json.exists():
        return {}
    try:
        data = json.loads(_safe_text(package_json))
    except json.JSONDecodeError:
        return {}
    # A valid-JSON non-dict package.json (`[]`) would crash the `.get()`
    # callers; return {} so they no-op safely.
    return data if isinstance(data, dict) else {}


def _parse_make_targets(makefile: Path) -> list[str]:
    return [m for m in re.findall(r"^([A-Za-z0-9_.-]+):", _safe_text(makefile), flags=re.MULTILINE) if not m.startswith(".")]


def _path_allowed(path: Path, repo_root: Path, config: HarnessConfig) -> bool:
    rel = _rel(path, repo_root)
    # Require a path-segment boundary so include_paths=["src"] admits src/
    # and the bare file "src" but NOT siblings like srcbox/ or src_gen/.
    # Mirrors the exclude predicate's boundary check below.
    if config.include_paths and not any(
        rel == prefix.rstrip("/") or rel.startswith(prefix.rstrip("/") + "/")
        for prefix in config.include_paths
    ):
        return False
    if any(rel == prefix or rel.startswith(prefix.rstrip("/") + "/") for prefix in config.exclude_paths):
        return False
    return True


def _iter_files(repo_root: Path, config: HarnessConfig | None = None):
    config = config or HarnessConfig()
    # os.walk does not descend into symlinked directories (followlinks=False is
    # the default), so a directory-symlink LOOP cannot trap the walk. A bare
    # Path.rglob("*") follows dir symlinks on CPython < 3.13 (recurse_symlinks
    # only became the default-False knob in 3.13), raising OSError(ELOOP) on a
    # loop or inflating language counts on a benign symlinked vendor dir. The
    # downstream filter set is unchanged.
    for dirpath, dirnames, filenames in os.walk(repo_root):
        # An embedded git repo is a foreign project — do not descend into it,
        # even when its .git no longer resolves (has_git_entry, not
        # is_own_git_repo). Prunes in place so os.walk skips the subtree.
        dirnames[:] = [d for d in dirnames if not has_git_entry(Path(dirpath) / d)]
        for fname in filenames:
            path = Path(dirpath) / fname
            if not path.is_file():
                continue
            if any(part in DEFAULT_SKIP_PARTS for part in path.parts):
                continue
            rel = _rel(path, repo_root)
            if is_harness_output(rel):
                continue
            if not _path_allowed(path, repo_root, config):
                continue
            # An init-seeded doc is harness provenance at an adopter path; the
            # first-line seed stamp is the only honest key (see the HOP note).
            # Seeds are Markdown, so the 256-byte peek is paid for `.md` only.
            if path.suffix.lower() == ".md" and path_has_seed_stamp(path):
                continue
            yield path


def detect_languages(repo_root: Path, config: HarnessConfig | None = None) -> tuple[dict[str, int], list[str]]:
    counts: Counter[str] = Counter()
    for path in _iter_files(repo_root, config):
        language = SUFFIX_TO_LANGUAGE.get(path.suffix.lower())
        if language:
            counts[language] += 1
    return dict(counts), [name for name, _ in counts.most_common()]


def detect_package_systems(repo_root: Path) -> list[str]:
    systems: list[str] = []
    if (repo_root / "pyproject.toml").exists() or (repo_root / "requirements.txt").exists():
        systems.append("python")
    if (repo_root / "package.json").exists():
        systems.append("node")
    if (repo_root / "Cargo.toml").exists():
        systems.append("rust")
    if (repo_root / "go.mod").exists():
        systems.append("go")
    if (repo_root / "pom.xml").exists() or (repo_root / "build.gradle").exists():
        systems.append("jvm")
    return systems


def detect_package_roots(repo_root: Path, config: HarnessConfig | None = None) -> list[str]:
    roots: list[str] = []
    for path in _iter_files(repo_root, config):
        if path.name in MANIFEST_NAMES:
            roots.append(_rel(path.parent, repo_root))
    roots = sorted(set(root if root != "." else "/" for root in roots))
    return roots


def detect_entrypoints(repo_root: Path) -> list[str]:
    hits = [name for name in ENTRYPOINT_CANDIDATES if (repo_root / name).exists()]
    package_json = _safe_package_json(repo_root)
    scripts = package_json.get("scripts", {}) if isinstance(package_json.get("scripts"), dict) else {}
    for key in ("dev", "start", "build", "test"):
        if key in scripts:
            hits.append(f"package.json:scripts.{key}")
    # Cargo entrypoints
    if (repo_root / "Cargo.toml").exists():
        if (repo_root / "src" / "main.rs").exists():
            hits.append("src/main.rs")
        elif (repo_root / "src" / "lib.rs").exists():
            hits.append("src/lib.rs")
    # Go entrypoints
    if (repo_root / "go.mod").exists():
        for candidate in ("main.go", "cmd"):
            if (repo_root / candidate).exists():
                hits.append(candidate)
    # pyproject.toml console_scripts
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        text = _safe_text(pyproject)
        if "[project.scripts]" in text or "console_scripts" in text:
            hits.append("pyproject.toml:scripts")
    return list(dict.fromkeys(hits))


def detect_ci(repo_root: Path) -> list[str]:
    providers: list[str] = []
    if (repo_root / ".github" / "workflows").exists():
        providers.append("github_actions")
    if (repo_root / ".gitlab-ci.yml").exists():
        providers.append("gitlab_ci")
    if (repo_root / "azure-pipelines.yml").exists():
        providers.append("azure_pipelines")
    return providers


def _has_python_signals(repo_root: Path) -> bool:
    """Check whether the repo has any Python project indicators."""
    return any((repo_root / name).exists() for name in (
        "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile",
    ))


def _tests_dir_has_pytest_modules(repo_root: Path) -> bool:
    """True when ``tests/`` directly holds a pytest-shaped module
    (``test_*.py`` / ``*_test.py``).

    The ``tests/`` branch of ``detect_tests`` is gated on a packaging file so a
    JS or Rust ``tests/`` never yields ``pytest -q`` -- but a bare ``src/`` +
    ``tests/test_app.py`` Python repo with no ``pyproject.toml`` then reads as
    "No test command was detected" and its generated CLAUDE.md tells the adopter
    to configure one, while QUICKSTART promises auto-detection (DEF-690, driven
    on a three-file wheel-install tree 2026-09-05). A test module IS the Python
    signal. Top-level glob only, so the probe stays cheap on a large suite.
    """
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return False
    try:
        return any(
            p.is_file()
            for pattern in ("test_*.py", "*_test.py")
            for p in tests_dir.glob(pattern)
        )
    except OSError:
        return False


def detect_tests(repo_root: Path) -> list[str]:
    commands: list[str] = []
    if (repo_root / "pytest.ini").exists():
        commands.append("pytest -q")
    elif (repo_root / "tests").exists() and _has_python_signals(repo_root):
        commands.append("pytest -q")
    elif (repo_root / "pyproject.toml").exists():
        text = _safe_text(repo_root / "pyproject.toml").lower()
        if "pytest" in text or "[tool.pytest" in text:
            commands.append("pytest -q")
    elif _tests_dir_has_pytest_modules(repo_root) and not any(
        (repo_root / manifest).exists() for manifest in ("Cargo.toml", "go.mod", "package.json")
    ):
        # A foreign manifest owns the test command; a Rust repo with one
        # python-driven smoke test must not be told its suite is `pytest -q`
        # (the failure-mode pass drove exactly that: pytest listed FIRST).
        commands.append("pytest -q")
    package_json = _safe_package_json(repo_root)
    scripts = package_json.get("scripts", {}) if isinstance(package_json.get("scripts"), dict) else {}
    if "test" in scripts:
        commands.append("npm test")
    if (repo_root / "Cargo.toml").exists():
        commands.append("cargo test")
    if (repo_root / "go.mod").exists():
        commands.append("go test ./...")
    makefile = repo_root / "Makefile"
    if makefile.exists():
        targets = _parse_make_targets(makefile)
        if "test" in targets:
            commands.append("make test")
    return list(dict.fromkeys(commands))


# Canonical base action set. Both detect_actions (here) and
# harness_config._detect_actions build on it; hoisted to one owner so a rename
# or an execution-plan invocation change lands in a single place instead of
# drifting between two verbatim copies. Callers copy it
# (fresh list values per call) before adding their layer-specific actions.
_BASE_ACTIONS: dict[str, list[str]] = {
    "audit": ["espalier audit ."],
    "reflect": ["espalier reflect ."],
    "reflect-deep": ["espalier reflect-deep ."],
    "execution-plan": ["python tools/cc/execution_plan.py status"],
}


def detect_actions(repo_root: Path, test_commands: list[str]) -> dict[str, list[str]]:
    # Only reference tools that build_target_repo() actually generates
    actions: dict[str, list[str]] = {k: list(v) for k, v in _BASE_ACTIONS.items()}
    if test_commands:
        actions["test"] = [test_commands[0]]
    if _has_python_signals(repo_root):
        actions["scan"] = ["espalier scan ."]
    package_json = _safe_package_json(repo_root)
    scripts = package_json.get("scripts", {}) if isinstance(package_json.get("scripts"), dict) else {}
    if "build" in scripts:
        actions["build"] = ["npm run build"]
    if "lint" in scripts:
        actions["lint"] = ["npm run lint"]
    if "dev" in scripts:
        actions["smoke"] = ["npm run dev"]
    elif "start" in scripts:
        actions["smoke"] = ["npm start"]
    makefile = repo_root / "Makefile"
    if makefile.exists():
        targets = _parse_make_targets(makefile)
        if "build" in targets and "build" not in actions:
            actions["build"] = ["make build"]
        if "lint" in targets and "lint" not in actions:
            actions["lint"] = ["make lint"]
        if "smoke" in targets and "smoke" not in actions:
            actions["smoke"] = ["make smoke"]
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists() and "lint" not in actions:
        text = _safe_text(pyproject).lower()
        if "ruff" in text:
            actions["lint"] = ["ruff check ."]
    return actions


# Files a platform or git leaves in a directory that say nothing about who
# owns it: Finder's .DS_Store on every macOS adopter who opens the seeded
# docs/ (driven 2026-09-12: one of these re-earned the docs cue), Explorer's
# Thumbs.db and desktop.ini, and the empty-directory placeholders.
_DOCS_PLACEHOLDER_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini", ".gitkeep", ".keep"})


def detect_docs_surface(repo_root: Path) -> list[str]:
    hits: list[str] = []
    for name in ("README.md", "CONTRIBUTING.md", "ARCHITECTURE.md"):
        if (repo_root / name).exists():
            hits.append(name)
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        # `init` seeds ~20 docs here and, on a repo that had no docs/, makes
        # the directory too. The seeds are excluded by their first-line stamp,
        # not by path (the same path unstamped IS the adopter's doc), and the
        # directory earns the `docs` cue only when it holds a file the adopter
        # owns -- any unstamped file, Markdown or not: a docs/ of images is a
        # docs surface, a docs/ of seeds is the harness's. Counting the seeds
        # made every fresh install `docs_heavy` (profiles.py scores on this
        # list's length, DEF-686); counting the directory gave every fresh
        # install a cue, a `docs_surface` signal and two docs conventions
        # (DEF-410f). A placeholder (`_DOCS_PLACEHOLDER_FILES`) is nobody's
        # documentation; a generated tree under docs/ (a site's node_modules/)
        # is skipped as the walker skips it; a nested git repository is a
        # foreign project `safe_rglob` does not enter, so a docs/ whose only
        # content is a checkout of something else earns no cue. The stamp
        # peek is paid for `.md` only, and every seed under docs/ is `.md`
        # (pinned in tests/test_analyze.py), so no seed reaches the other arm.
        owned_md: list[str] = []
        owned_other = False
        for p in safe_rglob(docs_dir):
            if not p.is_file():
                continue
            if any(part in DEFAULT_SKIP_PARTS for part in p.relative_to(docs_dir).parts):
                continue
            if p.suffix.lower() == ".md":
                if not path_has_seed_stamp(p):
                    owned_md.append(_rel(p, repo_root))
            elif p.name.lower() not in _DOCS_PLACEHOLDER_FILES:
                owned_other = True
        if owned_md or owned_other:
            hits.append("docs")
            hits.extend(sorted(owned_md))
    return list(dict.fromkeys(hits))


def detect_runtime_surface(repo_root: Path) -> list[str]:
    hits = [name for name in ENTRYPOINT_CANDIDATES if (repo_root / name).exists()]
    hits.extend(name for name in RUNTIME_DIR_CANDIDATES if (repo_root / name).exists())
    # Detect Python package directories (top-level dirs with __init__.py).
    # Harness output is skipped by the one predicate, so a user's top-level
    # `tools/` package is still a candidate (only `tools/cc` is the harness's).
    for child in repo_root.iterdir():
        if child.is_dir() and child.name not in DEFAULT_SKIP_PARTS and not is_harness_output(child.name):
            if (child / "__init__.py").exists():
                hits.append(child.name)
    # Cargo src directory
    if (repo_root / "src" / "main.rs").exists() or (repo_root / "src" / "lib.rs").exists():
        if "src" not in hits:
            hits.append("src")
    return list(dict.fromkeys(hits))


def detect_api_surface(repo_root: Path) -> bool:
    for name in ("api.py", "server.py", "app.py", "main.py"):
        path = repo_root / name
        if path.exists():
            text = _safe_text(path).lower()
            if any(token in text for token in ("fastapi", "flask", "django", "router", "@app.", "express(")):
                return True
    package_json = _safe_package_json(repo_root)
    text = json.dumps(package_json).lower() if package_json else ""
    return any(token in text for token in ("express", "koa", "fastify", "nestjs"))


def detect_ui_surface(repo_root: Path) -> bool:
    package_json = _safe_package_json(repo_root)
    text = json.dumps(package_json).lower() if package_json else ""
    if any(token in text for token in ("react", "vite", "next", "svelte", "vue")):
        return True

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        py_text = _safe_text(pyproject).lower()
        if any(token in py_text for token in ("streamlit", "gradio", "dash")):
            return True

    # frontend/ is an unambiguous UI signal — keep it as bare existence.
    if (repo_root / "frontend").is_dir():
        return True
    # pages/, public/, web/ collide with Django/Flask static dirs and
    # static-site/docs trees on pure-Python repos. Require an actual web-ish
    # file inside before firing (bounded scan), so a Django public/ holding
    # only images stays False while a Next.js pages/ with .jsx fires.
    _web_exts = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html", ".css"}
    for name in ("pages", "public", "web"):
        d = repo_root / name
        if not d.is_dir():
            continue
        # NB: safe_rglob yields in os.walk (top-down) order, which differs from
        # Path.rglob's order; combined with the 5000-entry cap this is an
        # order-sensitive heuristic — on a >5000-entry asset tree whose only
        # web-ish files sit past the cut, detection can flip. Acceptable for a
        # surface-detection heuristic.
        for i, p in enumerate(safe_rglob(d)):
            if i >= 5000:  # bounded — don't walk an enormous asset tree
                break
            if p.suffix.lower() in _web_exts and p.is_file():
                return True

    if (repo_root / "index.html").exists() and ((repo_root / "src").exists() or package_json):
        return True

    src_dir = repo_root / "src"
    if src_dir.exists():
        if list(safe_rglob(src_dir, "*.tsx")) or list(safe_rglob(src_dir, "*.jsx")):
            return True

    return False


# ML surface detection.
# Multi-signal: requires evidence in 2+ independent categories before firing.
# Single-token substring matches on pyproject.toml are the false-positive
# vector — "model" in a pytest marker description would otherwise trigger
# ml_surface on espalier-harness itself.

_ML_TRAINING_SCRIPTS = (
    "train.py",
    "train_probes.py",
    "make_big_dataset.py",
    "finetune.py",
    "pretrain.py",
)

_ML_DEP_NAMES = frozenset({
    "torch",
    "tensorflow",
    "keras",
    "jax",
    "flax",
    "transformers",
    "datasets",
    "scikit-learn",
    "sklearn",
    "xgboost",
    "lightgbm",
    "pytorch-lightning",
    "lightning",
    "accelerate",
    "huggingface-hub",
    "wandb",
    "mlflow",
    "optuna",
})

_ML_CONFIG_FILES = (
    "training_config.yaml",
    "train_config.yaml",
    "model_config.yaml",
    "accelerate_config.yaml",
    ".huggingface",
)

_ML_WEIGHT_SUFFIXES = (".pt", ".pth", ".ckpt", ".safetensors", ".h5", ".pb", ".onnx")


def _ml_signal_training_scripts(repo_root: Path) -> bool:
    return any((repo_root / name).exists() for name in _ML_TRAINING_SCRIPTS)


def _dep_spec_matches_ml(spec: str) -> bool:
    name = spec.strip().split("[", 1)[0]
    for op in (">=", "<=", "==", "!=", "~=", ">", "<", "@", ";", " "):
        name = name.split(op, 1)[0]
    return name.strip().lower() in _ML_DEP_NAMES


def _ml_signal_dep_imports(repo_root: Path) -> bool:
    """Match dependency names against pyproject dependency declarations,
    not arbitrary prose. Structured TOML parsing excludes substrings inside
    `description`, `name`, and marker strings by construction.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return False
    from espalier._compat import tomllib
    if tomllib is None:
        return False
    try:
        data = tomllib.loads(_safe_text(pyproject))
    except (ValueError, OSError):
        return False
    project = data.get("project", {}) if isinstance(data, dict) else {}
    for spec in project.get("dependencies", []) or []:
        if isinstance(spec, str) and _dep_spec_matches_ml(spec):
            return True
    for extra_deps in (project.get("optional-dependencies", {}) or {}).values():
        for spec in extra_deps or []:
            if isinstance(spec, str) and _dep_spec_matches_ml(spec):
                return True
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    for section in ("dependencies", "dev-dependencies"):
        for name in (poetry.get(section, {}) or {}):
            if isinstance(name, str) and name.lower() in _ML_DEP_NAMES:
                return True
    for grp in (poetry.get("group", {}) or {}).values():
        if not isinstance(grp, dict):
            continue
        for name in (grp.get("dependencies", {}) or {}):
            if isinstance(name, str) and name.lower() in _ML_DEP_NAMES:
                return True
    return False


def _ml_signal_directories_with_content(repo_root: Path) -> bool:
    """A `models/` or `notebooks/` directory by name is not enough. The
    directory must contain ML-shaped contents: `.ipynb` for notebooks,
    weight-file suffixes for models/checkpoints/weights.
    """
    notebooks = repo_root / "notebooks"
    if notebooks.is_dir():
        try:
            if any(safe_rglob(notebooks, "*.ipynb")):
                return True
        except OSError:
            pass
    for name in ("models", "checkpoints", "weights"):
        d = repo_root / name
        if not d.is_dir():
            continue
        try:
            for child in safe_rglob(d):
                if child.suffix.lower() in _ML_WEIGHT_SUFFIXES:
                    return True
        except OSError:
            continue
    return False


def _ml_signal_config_files(repo_root: Path) -> bool:
    return any((repo_root / name).exists() for name in _ML_CONFIG_FILES)


def detect_ml_surface(repo_root: Path) -> bool:
    """Detect ML repos via multi-signal co-occurrence.

    Returns True only when 2+ of the four signal categories hit. Each
    signal is independently weak; the conjunction is strong.
    """
    signals = (
        _ml_signal_training_scripts(repo_root),
        _ml_signal_dep_imports(repo_root),
        _ml_signal_directories_with_content(repo_root),
        _ml_signal_config_files(repo_root),
    )
    return sum(signals) >= 2


# Ops surface directories: signal that a repo manages operational workflows,
# content pipelines, or AI-orchestrated processes beyond just code.
OPS_CONTENT_DIRS = {"content", "drafts", "published", "posts", "output", "generated"}
OPS_STRATEGY_DIRS = {"brand", "strategy", "playbook", "guidelines"}
# "data" is excluded here — overwhelmingly a code-repo fixtures/datasets dir,
# not an analytics surface, and a data+tasks false-positive vector.
OPS_ANALYTICS_DIRS = {"analytics", "metrics", "engagement", "signals", "feedback"}
OPS_WORKFLOW_DIRS = {"workflows", "pipelines", "orchestration", "tasks", "prompts", "agents"}
OPS_STRATEGY_FILES = {"strategy.md", "voice.md", "brand.md", "pillars.md", "audience.md",
                       "guidelines.md", "playbook.md", "calendar.md"}


def detect_ops_surface(repo_root: Path) -> tuple[bool, list[str]]:
    """Detect whether a repo manages operational/content workflows beyond code.

    Returns (is_ops, list_of_detected_ops_directories).
    Triggers when 2+ ops directory categories are present, or when
    strategy files are found alongside content directories.
    """
    found_dirs: list[str] = []
    categories_hit: set[str] = set()

    for child in repo_root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        name = child.name.lower()
        if name in OPS_CONTENT_DIRS:
            found_dirs.append(child.name)
            categories_hit.add("content")
        elif name in OPS_STRATEGY_DIRS:
            found_dirs.append(child.name)
            categories_hit.add("strategy")
        elif name in OPS_ANALYTICS_DIRS:
            found_dirs.append(child.name)
            categories_hit.add("analytics")
        elif name in OPS_WORKFLOW_DIRS:
            found_dirs.append(child.name)
            categories_hit.add("workflow")

    # Also check for strategy files in root
    for child in repo_root.iterdir():
        if child.is_file() and child.name.lower() in OPS_STRATEGY_FILES:
            categories_hit.add("strategy")
            if child.name not in found_dirs:
                found_dirs.append(child.name)

    # Require 2+ categories AND at least one *defining* ops marker (content or
    # strategy). Without this, a plain code repo with two generic dirs
    # (analytics + workflow, e.g. metrics/ + tasks/) is mis-classified as
    # ai_ops_channel. content/strategy is what makes a repo a content-ops repo;
    # analytics+workflow alone is ambiguous.
    is_ops = len(categories_hit) >= 2 and bool({"content", "strategy"} & categories_hit)
    return is_ops, sorted(found_dirs)


def detect_monorepo(package_roots: list[str]) -> bool:
    normalized = [item for item in package_roots if item not in {"/", "."}]
    return len(normalized) >= 2


def detect_generated_zones(repo_root: Path, package_roots: list[str]) -> tuple[list[str], list[str]]:
    generated = [name for name in KNOWN_GENERATED if (repo_root / name).exists()]
    risky = [name for name in generated if name in {"dist", "build", "target"}]
    # Count real roots only — strip the "/"/"." sentinels the same way
    # detect_monorepo does, so the "/" sentinel can't inflate the count.
    if len([r for r in package_roots if r not in {"/", "."}]) >= 3:
        risky.append("multiple_package_roots")
    return sorted(set(generated)), sorted(set(risky))


def detect_large_files(repo_root: Path, config: HarnessConfig | None = None, threshold_bytes: int = 200_000) -> list[LargeFile]:
    hits: list[LargeFile] = []
    for path in _iter_files(repo_root, config):
        size = path.stat().st_size
        if size >= threshold_bytes:
            loc = 0
            try:
                raw = path.read_bytes()
            except OSError:  # PermissionError is a subclass of OSError
                raw = b""  # Unreadable file — report size only
            if raw and b"\x00" not in raw[:8192]:
                # Text-shaped: count real lines. The previous form decoded with
                # errors="replace", which NEVER raises — so the `except OSError`
                # branch below could not be reached by a binary file at all, and
                # a SQLite database decoded to replacement-character garbage and
                # yielded a fabricated line count. A NUL sniff is what makes
                # "binary — report size only" reachable.
                loc = len(raw.splitlines())
            hits.append(LargeFile(path=_rel(path, repo_root), size_bytes=size, loc=loc))
    hits.sort(key=lambda item: item.size_bytes, reverse=True)
    return hits[:50]


def _leads_with_suspicious(text: str, *, max_lines: int = 3) -> bool:
    """True if a SUSPICIOUS_CONTENT marker appears in the first ``max_lines``
    non-blank lines. An accidental dump (less-pager output, a raw git-diff
    paste) LEADS with the junk; a README/CONTRIBUTING that merely *quotes* a
    marker embeds it inside a fenced example deeper in the body."""
    seen = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if any(token in line for token in SUSPICIOUS_CONTENT):
            return True
        seen += 1
        if seen >= max_lines:
            break
    return False


def detect_garbage_files(repo_root: Path) -> list[str]:
    hits: list[str] = []
    for path in repo_root.iterdir():
        if not path.is_file():
            continue
        if path.name in SUSPICIOUS_FILENAMES:
            hits.append(path.name)
            continue
        # .py is excluded from the content scan — a source file that merely
        # quotes a marker (a patch-parser constant, a test fixture) is not
        # junk, and known-bad code files are caught by SUSPICIOUS_FILENAMES.
        # For doc/text suffixes, only flag when the marker LEADS the file, so a
        # README fencing a `diff --git a/` example is not mistaken for a dump.
        if path.suffix.lower() in {".md", ".txt", ".ps1", ".sh", ".log"}:
            if _leads_with_suspicious(_safe_text(path)):
                hits.append(path.name)
    return sorted(set(hits))


def _starts_with_emoji(msg: str) -> bool:
    """True if ``msg`` begins with an emoji glyph (advisory commit-format
    metadata). Replaces the ``ord(m[0]) > 127`` heuristic, which counted any
    non-ASCII leading char — so accented-Latin, Cyrillic, and CJK commit
    histories were mislabeled ``emoji_prefix``. Covers the main emoji blocks
    (pictographs/emoticons/transport/supplemental, misc-symbols + dingbats,
    regional-indicator flags) without third-party deps."""
    if not msg:
        return False
    cp = ord(msg[0])
    return (
        0x1F300 <= cp <= 0x1FAFF       # pictographs, emoticons, transport, supplemental
        or 0x2600 <= cp <= 0x27BF      # misc symbols + dingbats (✨ ✅ ✏ …)
        or 0x1F1E6 <= cp <= 0x1F1FF    # regional-indicator flags
    )


def detect_git_conventions(repo_root: Path) -> dict[str, Any]:
    """Analyze git log to detect commit message patterns."""
    import subprocess
    result: dict[str, Any] = {"format": "freeform", "evidence": [], "confidence": 0.0}

    try:
        log = subprocess.run(
            ["git", "log", "--oneline", "-30", "--format=%s"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            # Decode git's UTF-8 output, not the OS locale (cp1252 on a
            # stock Windows console would mojibake/crash on accented authors or
            # CJK subjects). errors="replace" here — unlike the strict UTF-8 at
            # the other sites — because a commit can carry a non-UTF-8
            # i18n.commitEncoding; degrade a stray byte to U+FFFD rather than
            # crash convention detection on one odd commit.
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if log.returncode != 0 or not log.stdout.strip():
            return result
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return result

    messages = [m.strip() for m in log.stdout.strip().splitlines() if m.strip()]
    if len(messages) < 5:
        return result

    # Check for conventional commits: type(scope): description
    conventional_re = re.compile(r"^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)(\(.+\))?!?:\s")
    conventional_count = sum(1 for m in messages if conventional_re.match(m))

    # Check for ticket prefixes: PROJ-123, #123
    ticket_re = re.compile(r"^[A-Z]{2,}-\d+|^#\d+")
    ticket_count = sum(1 for m in messages if ticket_re.match(m))

    # Check for emoji prefixes
    emoji_count = sum(1 for m in messages if _starts_with_emoji(m))

    total = len(messages)
    if conventional_count / total >= 0.6:
        result["format"] = "conventional"
        result["confidence"] = conventional_count / total
        result["evidence"] = [m for m in messages[:5] if conventional_re.match(m)]
    elif ticket_count / total >= 0.5:
        result["format"] = "ticket_prefix"
        result["confidence"] = ticket_count / total
        result["evidence"] = [m for m in messages[:5] if ticket_re.match(m)]
    elif emoji_count / total >= 0.5:
        result["format"] = "emoji_prefix"
        result["confidence"] = emoji_count / total
        result["evidence"] = messages[:5]

    return result


def detect_architecture(repo_root: Path) -> dict[str, Any]:
    """Detect architectural layer patterns: harness_layered, src_layout, mvc, flat."""
    layers: list[str] = []
    layer_rules: dict[str, str] = {}
    pattern = "flat"

    has_espalier = (repo_root / "espalier").is_dir()
    has_tools_cc = (repo_root / "tools" / "cc").is_dir()
    has_scanners = (repo_root / "espalier" / "scanners").is_dir()

    if has_espalier and has_tools_cc:
        pattern = "harness_layered"
        layers = ["espalier", "tools/cc"]
        if has_scanners:
            layers.append("espalier/scanners")
        layer_rules = {
            "tools/cc": "zero_espalier_imports",
            "espalier/scanners": "stdlib_only",
        }
    elif (repo_root / "src").is_dir():
        pattern = "src_layout"
        src_dir = repo_root / "src"
        layers = [
            f"src/{d.name}"
            for d in sorted(src_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]
    elif any((repo_root / d).is_dir() for d in ("controllers", "services", "models")):
        pattern = "mvc"
        layers = [
            d for d in ("controllers", "services", "models", "views", "repositories")
            if (repo_root / d).is_dir()
        ]

    result: dict[str, Any] = {"pattern": pattern, "layers": layers}
    if layer_rules:
        result["layer_rules"] = layer_rules
    return result


def detect_conventions(repo_root: Path, fingerprint_inputs: dict[str, object] | None = None) -> dict[str, list[str]]:
    context = dict(fingerprint_inputs or {})
    package_roots = list(context.get("package_roots", []) or [])
    # The docs conventions key on the detected surface, never on a bare
    # `docs/` existence probe (the directory init's seeds create is not the
    # adopter's docs surface -- DEF-410f); a caller that passes no surface
    # gets it detected, a caller that passes an empty one means "none". Key
    # PRESENCE, not truthiness -- deliberately unlike the five `.get(...) or
    # []` siblings around it, which have no detector to fall back to.
    docs_surface = (
        list(context["docs_surface"] or [])
        if "docs_surface" in context
        else detect_docs_surface(repo_root)
    )
    runtime_surface = list(context.get("runtime_surface", []) or [])
    test_commands = list(context.get("test_commands", []) or [])
    generated_zones = list(context.get("generated_zones", []) or [])
    risky_mutable_zones = list(context.get("risky_mutable_zones", []) or [])

    conventions: dict[str, list[str]] = {
        "layout": [],
        "commands": [],
        "tests": [],
        "docs": [],
        "guardrails": [],
    }

    pyproject = repo_root / "pyproject.toml"
    pyproject_text = _safe_text(pyproject).lower() if pyproject.exists() else ""
    package_json = _safe_package_json(repo_root)
    package_scripts = package_json.get("scripts", {}) if isinstance(package_json.get("scripts"), dict) else {}

    if (repo_root / "src").exists():
        conventions["layout"].append("src/ layout is present; prefer imports and extractions that preserve src-root boundaries.")
    if package_roots:
        conventions["layout"].append("Detected package roots: " + ", ".join(package_roots[:6]))
    if runtime_surface:
        conventions["layout"].append("Runtime surface cues: " + ", ".join(runtime_surface[:6]))

    if (repo_root / "Makefile").exists():
        conventions["commands"].append("Makefile targets are part of the live command surface.")
    if package_scripts:
        conventions["commands"].append("package.json scripts are a live command surface.")
    # Through the filtered walker, never a raw repo-root glob: the deployed
    # Windows statusline shim (tools/cc/statusline.cmd, DEF-729) is harness
    # output, and a raw walk read it as the adopter's own Windows helper --
    # a fingerprint that changed on every fresh init (the DEF-410f shape).
    # tests/test_analyze.py pins that no detector walks the root outside it.
    if any(p.suffix.lower() in (".ps1", ".cmd") for p in _iter_files(repo_root)):
        conventions["commands"].append("Windows shell helpers are present; preserve existing command style where possible.")
    if "ruff" in pyproject_text:
        conventions["commands"].append("Ruff appears in repo metadata; keep lint guidance aligned with ruff.")
    if "mypy" in pyproject_text:
        conventions["commands"].append("Mypy appears in repo metadata; typing-sensitive edits should preserve type-checkability.")

    if test_commands:
        conventions["tests"].append("Detected test entrypoints: " + ", ".join(test_commands[:4]))
    if (repo_root / "tests").exists():
        conventions["tests"].append("A tests/ tree is present; prefer the smallest targeted proof before broad suites.")
    if (repo_root / "pytest.ini").exists() or "pytest" in pyproject_text:
        conventions["tests"].append("Pytest-style testing signals are present.")

    if docs_surface:
        conventions["docs"].append("Docs surface cues: " + ", ".join(docs_surface[:6]))
    if (repo_root / "README.md").exists():
        conventions["docs"].append("README.md is part of the operator surface and should stay in sync with commands and setup.")
    if "docs" in docs_surface:
        conventions["docs"].append("docs/ exists; prefer repo-local documentation patterns over invented ones.")

    if generated_zones:
        conventions["guardrails"].append("Treat generated zones as read-only by default: " + ", ".join(generated_zones[:8]))
    if risky_mutable_zones:
        conventions["guardrails"].append("Mutable or risky zones need explicit ownership: " + ", ".join(risky_mutable_zones[:8]))
    # Count real package roots only. The raw list can carry a "/" (or ".")
    # sentinel; counting it would trip this guardrail on a single-root repo.
    # detect_monorepo already strips the sentinels and uses the same >=2
    # threshold, so reuse it rather than re-deriving the strip here.
    if detect_monorepo(package_roots):
        conventions["guardrails"].append("Multiple package roots were detected; avoid cross-root edits without an explicit boundary plan.")

    # Ops conventions — detected when content/brand/analytics directories are present
    ops_surface, ops_dirs = detect_ops_surface(repo_root)
    if ops_surface:
        if any(d in {"content", "drafts", "posts"} for d in ops_dirs):
            conventions["guardrails"].append("Content drafts must be reviewed against brand voice before scheduling. Use /draft-review.")
        if any(d in {"brand", "strategy"} for d in ops_dirs):
            conventions["guardrails"].append("Strategy and brand docs are governance documents; changes require explicit approval and downstream impact review.")
        # Reference the canonical OPS_ANALYTICS_DIRS rather than a literal, so
        # the set can't drift — every analytics ops dir (including signals/ and
        # feedback/) gets the analytics guardrail.
        if any(d in OPS_ANALYTICS_DIRS for d in ops_dirs):
            conventions["guardrails"].append("Analytics data is an input signal, not a target. Do not fabricate or adjust engagement metrics.")
        conventions["layout"].append("Ops surface directories: " + ", ".join(ops_dirs[:8]))

    return {name: values for name, values in conventions.items() if values}

def _signals(
    languages: list[str],
    package_systems: list[str],
    package_roots: list[str],
    entrypoints: list[str],
    docs_surface: list[str],
    api_surface: bool,
    ui_surface: bool,
    ml_surface: bool,
    ops_surface: bool,
    ops_directories: list[str],
    monorepo: bool,
) -> list[Signal]:
    signals: list[Signal] = []
    if languages:
        signals.append(Signal(name="languages", evidence=languages[:5], confidence=0.9))
    if package_systems:
        signals.append(Signal(name="package_systems", evidence=package_systems, confidence=0.9))
    if package_roots:
        signals.append(Signal(name="package_roots", evidence=package_roots[:10], confidence=0.8))
    if entrypoints:
        signals.append(Signal(name="entrypoints", evidence=entrypoints[:10], confidence=0.8))
    if len(docs_surface) >= 2:
        signals.append(Signal(name="docs_surface", evidence=docs_surface[:10], confidence=0.7))
    if api_surface:
        signals.append(Signal(name="api_surface", evidence=["api/framework markers"], confidence=0.75))
    if ui_surface:
        signals.append(Signal(name="ui_surface", evidence=["ui package or directory markers"], confidence=0.75))
    if ml_surface:
        signals.append(Signal(name="ml_surface", evidence=["training/model markers"], confidence=0.75))
    if ops_surface:
        signals.append(Signal(name="ops_surface", evidence=ops_directories[:10], confidence=0.8))
    if monorepo:
        signals.append(Signal(name="monorepo", evidence=package_roots[:10], confidence=0.85))
    return signals


def risk_notes(fingerprint: RepoFingerprint) -> list[str]:
    notes: list[str] = []
    if fingerprint.garbage_files:
        notes.append("Suspicious root junk files detected; route through the root-garbage gate before trusting the control plane.")
    if fingerprint.large_files:
        notes.append("Large files detected; extraction and seam planning should be available in the generated CC surface.")
    if fingerprint.monorepo:
        notes.append("Multiple package roots detected; lane planning and boundary ownership should be explicit.")
    if not fingerprint.test_commands:
        notes.append("No test command was detected automatically; proof coverage is partial by default.")
    return notes


def fingerprint_repo(repo_root: Path, config: HarnessConfig | None = None) -> RepoFingerprint:
    repo_root = repo_root.resolve()
    config = config or HarnessConfig()
    language_counts, languages = detect_languages(repo_root, config)
    package_roots = detect_package_roots(repo_root, config)
    package_systems = detect_package_systems(repo_root)
    ci_providers = detect_ci(repo_root)
    entrypoints = detect_entrypoints(repo_root)
    test_commands = detect_tests(repo_root)
    inferred_actions = detect_actions(repo_root, test_commands)
    docs_surface = detect_docs_surface(repo_root)
    runtime_surface = detect_runtime_surface(repo_root)
    api_surface = detect_api_surface(repo_root)
    ui_surface = detect_ui_surface(repo_root)
    ml_surface = detect_ml_surface(repo_root)
    ops_surface, ops_directories = detect_ops_surface(repo_root)
    monorepo = detect_monorepo(package_roots)
    generated_zones, risky_mutable_zones = detect_generated_zones(repo_root, package_roots)
    large_files = detect_large_files(repo_root, config)
    garbage_files = detect_garbage_files(repo_root)
    git_conventions = detect_git_conventions(repo_root)
    architecture = detect_architecture(repo_root)
    conventions = detect_conventions(
        repo_root,
        {
            "package_roots": package_roots,
            "docs_surface": docs_surface,
            "runtime_surface": runtime_surface,
            "test_commands": test_commands,
            "generated_zones": generated_zones,
            "risky_mutable_zones": risky_mutable_zones,
        },
    )
    # Add git convention summary to conventions dict
    if git_conventions["format"] != "freeform":
        conf_pct = int(git_conventions["confidence"] * 100)
        examples = ", ".join(git_conventions["evidence"][:3])
        conventions.setdefault("git", []).append(
            f"{git_conventions['format'].replace('_', ' ').title()} commits "
            f"({conf_pct}% of last 30 commits): {examples}"
        )
    confidence = {
        "languages": 0.9 if languages else 0.2,
        "package_systems": 0.9 if package_systems else 0.2,
        "entrypoints": 0.8 if entrypoints else 0.2,
        "tests": 0.8 if test_commands else 0.2,
        "profiles": 0.7,
    }
    fingerprint = RepoFingerprint(
        repo_name=repo_root.name,
        repo_root=str(repo_root),
        language_counts=language_counts,
        languages=languages,
        package_systems=package_systems,
        package_roots=package_roots,
        ci_providers=ci_providers,
        entrypoints=entrypoints,
        test_commands=test_commands,
        inferred_actions=inferred_actions,
        docs_surface=docs_surface,
        runtime_surface=runtime_surface,
        api_surface=api_surface,
        ui_surface=ui_surface,
        ml_surface=ml_surface,
        ops_surface=ops_surface,
        ops_directories=ops_directories,
        monorepo=monorepo,
        generated_zones=generated_zones,
        risky_mutable_zones=risky_mutable_zones,
        large_files=large_files,
        garbage_files=garbage_files,
        conventions=conventions,
        git_conventions=git_conventions,
        architecture=architecture,
        notes=[],
        signals=_signals(languages, package_systems, package_roots, entrypoints, docs_surface, api_surface, ui_surface, ml_surface, ops_surface, ops_directories, monorepo),
        confidence=confidence,
    )
    notes = risk_notes(fingerprint)
    profiles, _ = classify_repo(fingerprint, None)
    return replace(fingerprint, notes=notes, profiles=profiles)
