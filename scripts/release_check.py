#!/usr/bin/env python3
"""Release-readiness gate.

Single command — `python scripts/release_check.py` — that a maintainer
runs before publishing and that fails if any release blocker is present.
Each check is the CI-enforceable shape of correctness landed by a prior
pack; if any prior pack regresses, this gate blocks the next release
rather than silently degrading public claims.

Exit codes:
    0  — every required check passed.
    1  — at least one required check failed.

Output: one line per check, then a summary count.

Heavy checks (`tests_pass`) are skipped by default to keep local
invocations fast; CI invokes the gate with `ESPALIER_RELEASE_CHECK_WITH_TESTS=1`
to opt in. The release-CI matrix already runs the full test suite as a
separate job, so this gate is the *fast* signal.
"""
from __future__ import annotations

import http.client
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Make `import espalier.*` work even if the package isn't installed (CI runs
# `pip install -e .` first, but local invocations might not).
sys.path.insert(0, str(REPO_ROOT))

from espalier.pre_release import REQUIRED_PUBLIC_FILES  # noqa: E402
from espalier.release_noise import RELEASE_NOISE_PATTERNS  # noqa: E402
from espalier.changelog import (  # noqa: E402
    DATED_VERSION_RE,
    UNRELEASED_BODY_RE,
    has_content,
    section_body,
    substantive_entries,
)


#: Every Tier-1 opt-in flag this module reads -- the single census, and the set
#: that must be stripped from any child process this module spawns.
#:
#: It exists because ``check_tests_pass`` stripped exactly ONE of them. The
#: strip is anti-recursion: a nested pytest that still sees an opt-in re-enters
#: the check that spawned it. With only ``WITH_TESTS`` removed, a nested run
#: still saw ``WITH_WHEEL_SMOKE`` -- and ``.github/workflows/release.yml`` sets
#: BOTH at job scope while ``docs/RELEASE_CHECKLIST.md`` tells the maintainer to
#: export both locally, so the leak was armed on the two paths that matter. Two
#: live callers in ``tests/test_release_check.py`` then build a real wheel and
#: provision a venv INSIDE a pytest running ``--timeout 60``.
#:
#: A strip-set rather than an allow-list on purpose: a minimal child env would
#: have to carry PATH/HOME/TMPDIR/VIRTUAL_ENV plus Windows' SYSTEMROOT/COMSPEC/
#: PATHEXT, and an omission there is a cross-platform break rather than a leak.
#: Membership is pinned against the module's own ``os.environ`` reads by
#: tests/test_release_check.py::TestOptInEnvCensus, so a fourth flag cannot be
#: added without joining this tuple.
OPT_IN_ENV_FLAGS: tuple[str, ...] = (
    "ESPALIER_RELEASE_CHECK_WITH_TESTS",
    "ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE",
    "ESPALIER_RELEASE_CHECK_WITH_URLS",
)


#: The `not slow` pytest leg that `check_tests_pass` below runs is the leg the
#: release matrix's stage 01 runs too (`scripts/final_release_matrix.py`
#: imports these two names for it), serially, in this checkout. The bound both
#: hand the child is DERIVED from one recorded measurement here, never typed
#: beside a call: twice the leg, the rule the matrix states for its archive
#: stages -- a bound trimmed to the measurement fires on a slow day. Measured
#: on the 8 GB self-host box, 2026-09-23: 592 s (8,558 tests) and 604 s the
#: same day as the child of the matrix test file's stage-one smoke; the bare
#: 600 both sites carried then killed the leg at 97 % (8,352 of about 8,600
#: tests, no red), which extrapolates to about 620 s, the figure recorded.
#: Sized on the self-host box; the CI runners' headroom readings that landed as
#: fixes are recorded in the ledger's `DEF-856` strike (Actions on again since
#: 2026-09-23). Pinned by tests/test_release_check.py and by the matrix's own
#: driven rows.
NOT_SLOW_LEG_MEASURED_S = 620
NOT_SLOW_LEG_BOUND_S = 2 * NOT_SLOW_LEG_MEASURED_S


def child_env_without_opt_ins() -> dict:
    """``os.environ`` minus every opt-in flag, for a child this module spawns."""
    env = os.environ.copy()
    for flag in OPT_IN_ENV_FLAGS:
        env.pop(flag, None)
    return env


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    detail: str = ""


# Explicit SKIP status so the summary distinguishes truly-passed from
# env-gated opt-in checks. Exit code stays 0 if no FAIL, regardless of
# SKIP — preserves "fast signal green" semantics while making the proof
# distinction visible to a human reading the output.
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


# ── Package-level checks ────────────────────────────────────────────


def check_package_import(repo_root: Path = REPO_ROOT) -> CheckResult:
    """`import espalier` works (espalier is the installed top-level package name)."""
    result = subprocess.run(
        [sys.executable, "-c", "import espalier; print('ok')"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, cwd=str(repo_root),
        env=child_env_without_opt_ins(),
    )
    if result.returncode != 0:
        # Surface a concrete remediation so an operator running release_check
        # locally on a fresh clone doesn't have to grep docs for the install
        # command.
        return CheckResult(
            "package_import", "FAIL",
            f"{result.stderr.strip()[:120]} -- run: pip install -e .",
        )
    return CheckResult("package_import", "PASS")


def check_cli_entrypoint(repo_root: Path = REPO_ROOT) -> CheckResult:
    """`python -m espalier.cli --version` returns 0 and prints a non-empty version."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "--version"],
            capture_output=True, text=True, encoding="utf-8", timeout=15, cwd=str(repo_root),
            env=child_env_without_opt_ins(),
        )
    except ValueError as exc:  # strict decode: a structured answer (DEF-821)
        return CheckResult("cli_entrypoint", "FAIL", f"--version output was not UTF-8: {exc}")
    if result.returncode != 0 or not result.stdout.strip():
        return CheckResult(
            "cli_entrypoint", "FAIL",
            f"rc={result.returncode}, stdout={result.stdout!r}",
        )
    return CheckResult("cli_entrypoint", "PASS", result.stdout.strip())


def check_tests_pass(repo_root: Path = REPO_ROOT) -> CheckResult:
    """`pytest -m "not slow"` returns 0. Skipped unless explicitly opted in.

    The child pytest invocation has EVERY flag in `OPT_IN_ENV_FLAGS` stripped
    from its environment — otherwise tests under `tests/test_release_check.py`
    re-invoke the opt-in checks and recurse via subprocess until pytest-timeout
    fires. Stripping only the flag that gated THIS check left the nested run
    still seeing `..._WITH_WHEEL_SMOKE`, which CI and the checklist both set
    alongside it; see the note on `OPT_IN_ENV_FLAGS`.
    """
    if os.environ.get("ESPALIER_RELEASE_CHECK_WITH_TESTS") != "1":
        return CheckResult(
            "tests_pass", SKIP,
            "set ESPALIER_RELEASE_CHECK_WITH_TESTS=1 to run",
        )
    child_env = child_env_without_opt_ins()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "not slow", "-q", "--timeout", "60"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=NOT_SLOW_LEG_BOUND_S, cwd=str(repo_root),
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        # A bound, not a red: the leg outgrew the recorded measurement. Say so
        # here, where the name is known, instead of letting run_all_checks file
        # the exception as `raised: ...` with the reason lost.
        return CheckResult(
            "tests_pass", "FAIL",
            f"TIMED OUT at {NOT_SLOW_LEG_BOUND_S}s (twice the recorded "
            f"{NOT_SLOW_LEG_MEASURED_S}s leg): a bound, not a failed suite -- "
            "re-measure NOT_SLOW_LEG_MEASURED_S",
        )
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        return CheckResult(
            "tests_pass", "FAIL", f"rc={result.returncode}; {' / '.join(tail)}"[:200],
        )
    summary = next(
        (ln for ln in reversed(result.stdout.splitlines()) if "passed" in ln),
        "",
    )
    return CheckResult("tests_pass", "PASS", summary[:120])


def check_wheel_smoke(repo_root: Path = REPO_ROOT) -> CheckResult:
    """`scripts/wheel_smoke.py` returns 0. Skipped unless explicitly opted in.

    The canonical wheel-vs-fresh-repo gate. Skipped by default because it
    builds a wheel + provisions a venv (slow, network-bound if pip is
    cold). Release CI invokes the smoke directly per matrix cell; this
    opt-in lets a maintainer reproduce the gate locally.

    Set ``ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE=1`` to run.
    """
    if os.environ.get("ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE") != "1":
        return CheckResult(
            "wheel_smoke", SKIP,
            "release CI runs scripts/wheel_smoke.py per matrix cell; "
            "set ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE=1 to run locally",
        )
    smoke_script = repo_root / "scripts" / "wheel_smoke.py"
    if not smoke_script.exists():
        return CheckResult(
            "wheel_smoke", "FAIL",
            f"scripts/wheel_smoke.py missing at {smoke_script}",
        )
    result = subprocess.run(
        [sys.executable, str(smoke_script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, cwd=str(repo_root),
        # Stripped for the same anti-recursion reason as check_tests_pass, and
        # because OPT_IN_ENV_FLAGS' stated scope is "any child this module spawns"
        # -- a claim that was false here. Inert today (wheel_smoke.py never shells
        # to pytest) and deliberately fixed anyway: the trap is that the next step
        # added to that script inherits the recursion with the suite green.
        env=child_env_without_opt_ins(),
    )
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        return CheckResult(
            "wheel_smoke", "FAIL",
            f"rc={result.returncode}; {' / '.join(tail)}"[:200],
        )
    summary = next(
        (ln for ln in reversed(result.stdout.splitlines()) if "wheel_smoke" in ln),
        "",
    )
    return CheckResult("wheel_smoke", "PASS", summary[:120])


# ── Tracked-file hygiene ────────────────────────────────────────────


def _glob_to_regex(pat: str) -> str:
    """Translate a release-noise glob pattern to an anchored regex.

    Rules:
    - Trailing '/' = directory prefix; glob wildcards in name are honoured.
    - '*.ext' style = basename suffix match.
    - Literal names = exact path-segment match.
    """
    if pat.endswith("/"):
        # Directory prefix — translate glob wildcards in the name.
        name_re = re.escape(pat[:-1]).replace(r"\*", r".*").replace(r"\?", ".")
        return r"(?:^|/)" + name_re + "/"
    if pat.startswith("*."):
        # Extension match — any basename ending with this suffix.
        return r"(?:^|/)[^/]*" + re.escape(pat[1:]) + r"$"
    # Literal name — match exact path segment anywhere in path.
    return r"(?:^|/)" + re.escape(pat) + r"$"


# Patterns the tracked-noise scan rejects. Sourced from
# espalier.release_noise (the SoT) plus release-check-specific additions
# that aren't relevant to surface_contract (e.g. TP-*.md task packs).
_TRACKED_NOISE_PATTERNS: tuple[str, ...] = tuple(
    _glob_to_regex(p) for p in RELEASE_NOISE_PATTERNS
) + (
    # release-check-only: a task pack outside its two shipped locations. The
    # forward ledger, its probes file, the router and the packs directly under
    # task-packs/ and task-packs/Deferred/ are tracked and ship (2026-09-21); a
    # TP-*.md anywhere else, and anything under the landed / merged / scrapped
    # subtrees, is working-note noise (gitignored, but belt-and-suspenders if a
    # contributor untracks .gitignore briefly). Mirrored, independently
    # written, by tests/test_no_tracked_release_noise.py::FORBIDDEN_PATTERNS;
    # the classifier's side is surface_contract.is_shipped_pack.
    r"^(?!task-packs/(?:Deferred/)?TP-[^/]+\.md$)(?:.*/)?TP-[^/]+\.md$",
    r"^task-packs/(?:Done|Merged|Scrapped)/",
    r"(?:^|/)TP-[^/]+/",
    r"_task_pack\.md$",
    # (the release denylist's task-pack rule spells the same carve-out; the
    # code-review lane aligned the three on 2026-09-21)
    # release-check-only: per-install runtime that .gitignore handles
    # but is worth catching at audit time too.
    r"^\.claude/settings\.json$",
    r"^\.claude/settings\.local\.json$",
    # release-check-only: workspace local artifacts.
    r"(?:^|/)zDone/",
    r"^bench/results/",
    r"^cc/blueprints/",
)


def check_tracked_noise(repo_root: Path = REPO_ROOT) -> CheckResult:
    """Verify no tracked / present file matches a release-noise pattern.

    Falls back to a filesystem walk on non-git contexts so the check is
    meaningful in source-archive / sdist install modes.
    """
    sys.path.insert(0, str(repo_root))
    try:
        from espalier.repo_mode import list_tracked_or_walked_files
    finally:
        sys.path.pop(0)

    files, source = list_tracked_or_walked_files(repo_root)
    compiled = [(re.compile(p), p) for p in _TRACKED_NOISE_PATTERNS]
    offenders: list[tuple[str, str]] = []
    for path in files:
        for pattern, source_pattern in compiled:
            if pattern.search(path):
                offenders.append((path, source_pattern))
                break

    if offenders:
        return CheckResult(
            "tracked_noise", "FAIL",
            f"{len(offenders)} offender(s) via {source}; first: {offenders[0][0]}",
        )
    return CheckResult(
        "tracked_noise", "PASS",
        f"no release-noise paths ({len(files)} files scanned via {source})",
    )


# ── Release archive ─────────────────────────────────────────────────


def _archive_member_to_rel(name: str) -> str:
    """Strip the ``espalier-harness-<version>/`` archive prefix.

    Build outputs members like ``espalier-harness-0.5.0/espalier/cli.py``;
    classification operates on repo-relative paths, so strip the leading
    package directory before delegating to ``surface_contract``.
    """
    parts = name.split("/", 1)
    if len(parts) == 2 and parts[0].startswith("espalier-harness-"):
        return parts[1]
    return name


# Name-safety gate. Both the classifier and the denylist look at what
# bucket a member NAME falls into; neither rejects member names that
# are malformed. A poisoned release ZIP whose entries are ``/etc/passwd``
# or ``../escape.txt`` slips past both — defeating the dual-witness
# promise. This pre-witness check rejects any name that:
#   - contains a ``..`` path segment after normalisation
#   - starts with a forward slash (absolute POSIX path)
#   - starts with a Windows drive letter (``C:`` etc.)
# Fail-closed: the operator running ``--validate-archive`` should never
# see a PASS on an archive with these member shapes.
_UNSAFE_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_unsafe_member_name(name: str) -> str | None:
    """Return a reason string if the archive member name is unsafe, else None."""
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        return "absolute path"
    if _UNSAFE_DRIVE_RE.match(name):
        return "Windows drive prefix"
    if any(part == ".." for part in norm.split("/")):
        return "parent-directory traversal segment"
    return None


def _scan_members(
    members: list[str],
) -> tuple[
    list[tuple[str, str]],  # name_safety_rejects: (raw_name, reason)
    list[tuple[str, str]],  # classifier_rejects:  (raw_name, bucket)
    list[tuple[str, str]],  # denylist_rejects:    (rel, reason)
]:
    """Run the three release-archive witnesses over ``members`` once.

    Single SoT for the name-safety pre-witness + classifier + independent
    denylist. Members are partitioned into unsafe / safe a single time, so
    ``_is_unsafe_member_name`` is evaluated once per member instead of three
    times. Both archive-scan call sites consume the returned reject lists and
    apply only their own formatting; keeping the computation here means the
    witness set is a single edit point and the two sites cannot drift (the
    sister-site footgun class this gate guards).
    """
    from espalier import surface_contract
    from espalier.release_denylist import find_denied_members

    name_safety_rejects: list[tuple[str, str]] = []
    safe: list[str] = []
    for name in members:
        reason = _is_unsafe_member_name(name)
        if reason is not None:
            name_safety_rejects.append((name, reason))
        else:
            safe.append(name)

    classifier_rejects: list[tuple[str, str]] = []
    for name in safe:
        rel = _archive_member_to_rel(name)
        bucket = surface_contract.classify_release_path(rel)
        if bucket != "public":
            classifier_rejects.append((name, bucket))

    denylist_rejects = find_denied_members(
        _archive_member_to_rel(n) for n in safe
    )
    return name_safety_rejects, classifier_rejects, denylist_rejects


#: The load-bearing members every release archive must carry: the public files
#: the pre-release gate already requires of the tree (ONE census,
#: ``espalier.pre_release.REQUIRED_PUBLIC_FILES`` -- the inline tuple this
#: replaced was a third hand-kept copy that had dropped SECURITY.md,
#: CONTRIBUTING.md and CODE_OF_CONDUCT.md) plus the two engine files without
#: which nothing imports. One home for both validation paths -- the
#: built-archive check and ``--validate-archive`` -- because the standalone
#: validator ran only the three reject-scanners, so a near-empty ZIP (a README
#: and nothing else) passed it as clean.
REQUIRED_ARCHIVE_MEMBERS: tuple[str, ...] = (
    *REQUIRED_PUBLIC_FILES,
    "espalier/cli.py", "espalier/__init__.py",
)


def missing_required_members(members: list[str]) -> list[str]:
    """The entries of ``REQUIRED_ARCHIVE_MEMBERS`` no member of ``members``
    names once the version-stamped root is stripped (``_archive_member_to_rel``,
    the anchor the classifier reads; a suffix match would have accepted
    ``docs/README.md`` under a wrong root)."""
    present = {_archive_member_to_rel(m) for m in members}
    return [r for r in REQUIRED_ARCHIVE_MEMBERS if r not in present]


def check_release_archive_builds_and_clean(repo_root: Path = REPO_ROOT):
    """Combined check: build the archive, then scan it. Returns 2 results.

    The scan delegates classification to
    ``espalier.surface_contract.classify_release_path`` — the same function
    ``build_release_archive`` uses to decide what to include. By
    construction, the build and the scan cannot disagree.
    """
    scripts_dir = str(repo_root / "scripts")
    sys.path.insert(0, scripts_dir)
    try:
        from build_release_archive import build_release_archive  # type: ignore[import-not-found]
    except ImportError as e:
        miss = CheckResult("release_archive_builds", "FAIL", f"import failed: {e}")
        return miss, CheckResult("release_archive_clean", "FAIL", "skipped (build failed)")
    finally:
        # build_release_archive inserts repo_root at sys.path[0] on import, so a
        # bare pop(0) would remove the WRONG entry; remove our own path by value.
        # build_release_archive does no lazy sibling imports, so scripts/ is only
        # needed for the import above, so it is safe to drop before the body.
        if scripts_dir in sys.path:
            sys.path.remove(scripts_dir)
    try:
        # Importability PROBE — the witness use moved to _scan_members
        # (which imports surface_contract itself), but this early check
        # still returns a clean FAIL instead of crashing later if the
        # package is broken. Intentionally unused binding.
        from espalier import surface_contract  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as e:
        miss = CheckResult("release_archive_builds", "FAIL", f"surface_contract import failed: {e}")
        return miss, CheckResult("release_archive_clean", "FAIL", "skipped")

    out_dir = repo_root / "dist" / "_release_check_tmp"
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Suppress build_release_archive's progress chatter; the gate's own
    # CheckResult is the only output that should reach a caller piping
    # the parent process's stdout (e.g. `espalier pre-release`).
    import contextlib, io
    silenced_stdout = io.StringIO()
    try:
        try:
            with contextlib.redirect_stdout(silenced_stdout):
                archive = build_release_archive(repo_root, output_dir=out_dir)
        except SystemExit as e:
            return (
                CheckResult("release_archive_builds", "FAIL", f"exit {e.code}"),
                CheckResult("release_archive_clean", "FAIL", "skipped (build failed)"),
            )
        if not archive.exists() or archive.stat().st_size == 0:
            return (
                CheckResult("release_archive_builds", "FAIL", "no archive produced"),
                CheckResult("release_archive_clean", "FAIL", "skipped"),
            )
        # The builder says which enumeration answered, but only on the stdout
        # silenced above and on stderr, and no gate reads either. A root that
        # owns its `.git` and still walked the tree is git failing (absent from
        # PATH, dubious ownership, a moved gitdir), and the artifact holds every
        # untracked public file -- the shape the index enumeration closes.
        # Re-derive the answer here rather than trust a log line.
        from espalier import surface_contract as _sc
        from espalier._safe_walk import is_own_git_repo as _own
        if _own(repo_root) and _sc.tracked_paths(repo_root) is None:
            return (
                CheckResult(
                    "release_archive_builds", "FAIL",
                    "built from the working tree on a root that owns its .git "
                    "(git could not answer for this checkout; untracked files "
                    "would ship)",
                ),
                CheckResult("release_archive_clean", "FAIL", "skipped (tree-enumerated build)"),
            )
        builds = CheckResult("release_archive_builds", "PASS", archive.name)

        with zipfile.ZipFile(archive) as zf:
            members = zf.namelist()
        # Dual-witness — classifier (the build SoT) AND independent denylist.
        # The classifier walks the build glob; the denylist is a separate
        # pattern list with no shared code. Two independent rejections give
        # defense in depth against the closed-loop trap that shipped
        # ``project.zip``. A name-safety pre-witness rejects
        # malformed member names (absolute, ``..``, Windows drive) BEFORE
        # either witness runs.
        name_safety_rejects, classifier_rejects, denylist_rejects = (
            _scan_members(members)
        )
        if name_safety_rejects or classifier_rejects or denylist_rejects:
            parts = []
            if name_safety_rejects:
                n, reason = name_safety_rejects[0]
                parts.append(
                    f"name-safety: {len(name_safety_rejects)} offender(s); "
                    f"first: {n} ({reason})"
                )
            if classifier_rejects:
                n, lbl = classifier_rejects[0]
                parts.append(
                    f"classifier: {len(classifier_rejects)} offender(s); "
                    f"first: {n} ({lbl})"
                )
            if denylist_rejects:
                m, reason = denylist_rejects[0]
                parts.append(
                    f"denylist: {len(denylist_rejects)} offender(s); "
                    f"first: {m} ({reason})"
                )
            clean = CheckResult(
                "release_archive_clean", "FAIL", " | ".join(parts),
            )
        else:
            # Positive content floor: the witnesses above only REJECT bad
            # members, so a near-empty archive (e.g. only README) would pass as
            # "clean". Require the load-bearing public members in
            # ``REQUIRED_ARCHIVE_MEMBERS`` (shared with ``--validate-archive``)
            # so an INCOMPLETE build is caught, not blessed.
            missing_required = missing_required_members(members)
            if missing_required:
                clean = CheckResult(
                    "release_archive_clean", "FAIL",
                    f"missing required content: {', '.join(missing_required)}",
                )
            else:
                clean = CheckResult(
                    "release_archive_clean", "PASS",
                    f"{len(members)} members (classifier + denylist clean, "
                    "content floor met)",
                )
        return builds, clean
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


# ── Doc surface truth ───────────────────────────────────────────────


def _public_doc_paths(repo_root: Path) -> list[Path]:
    out = [
        repo_root / "README.md",
        repo_root / "CONTRIBUTING.md",
    ]
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        out.extend(sorted(docs_dir.glob("*.md")))
    return [p for p in out if p.exists()]


_PHANTOM_DOC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("WORKTREE_LANES", re.compile(r"\bWORKTREE_LANES\b")),
    ("exact_test_count", re.compile(r"Total test count:\s*\d", re.IGNORECASE)),
    ("test_count_1607", re.compile(r"\b1,?607\b")),
    ("test_count_1431", re.compile(r"\b1,?431\b")),
)


def check_docs_no_phantom_files(repo_root: Path = REPO_ROOT) -> CheckResult:
    offenders: list[str] = []
    for doc in _public_doc_paths(repo_root):
        text = doc.read_text(encoding="utf-8")
        for label, pat in _PHANTOM_DOC_PATTERNS:
            if pat.search(text):
                offenders.append(f"{doc.name}: {label}")
    if offenders:
        return CheckResult(
            "docs_no_phantom_files", "FAIL",
            f"{len(offenders)} offender(s); first: {offenders[0]}",
        )
    return CheckResult("docs_no_phantom_files", "PASS")


_OVERCLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("is a sandbox", re.compile(r"\bis\s+a\s+sandbox\b", re.IGNORECASE)),
    ("cannot be bypassed", re.compile(r"\bcannot\s+be\s+bypassed\b", re.IGNORECASE)),
    ("hard security guarantee", re.compile(r"\bhard\s+security\s+guarantee\b", re.IGNORECASE)),
)
_NEGATION_WINDOW = 60


def _is_negated(window: str) -> bool:
    """Window contains an explicit negation flipping the claim."""
    return bool(
        re.search(r"\bis\s+not\b", window, re.IGNORECASE)
        or re.search(r"\bdoes\s+not\b", window, re.IGNORECASE)
        or re.search(r"\bnot\s+a\s+sandbox\b", window, re.IGNORECASE)
        or re.search(r"\bnever\b", window, re.IGNORECASE)
    )


def check_docs_no_overclaim(repo_root: Path = REPO_ROOT) -> CheckResult:
    """README must not assert any unqualified overclaim. Calibrated
    non-claims ('is not a sandbox') survive via negation-window detection."""
    readme = repo_root / "README.md"
    if not readme.exists():
        return CheckResult("docs_no_overclaim", "FAIL", "README.md missing")
    text = readme.read_text(encoding="utf-8")
    offenders: list[str] = []
    for label, pat in _OVERCLAIM_PATTERNS:
        for m in pat.finditer(text):
            start = max(0, m.start() - _NEGATION_WINDOW)
            end = min(len(text), m.end() + _NEGATION_WINDOW)
            if not _is_negated(text[start:end]):
                offenders.append(label)
                break
    if offenders:
        return CheckResult(
            "docs_no_overclaim", "FAIL", f"unqualified: {', '.join(offenders)}",
        )
    return CheckResult("docs_no_overclaim", "PASS")


def check_docs_count_claims(repo_root: Path = REPO_ROOT) -> CheckResult:
    """Verify command/agent/helper count claims in public docs match disk.

    Scans every doc in surface_contract.discover_public_docs (not just three
    hand-curated paths) and accepts spelled-out numbers ("three helpers") in
    addition to digits ("3 helpers").
    """
    sys.path.insert(0, str(repo_root))
    try:
        from espalier.surface_contract import (
            discover_public_docs,
            get_canonical_hook_scripts,
            make_count_claim_regex,
            parse_count_token,
        )
    finally:
        sys.path.pop(0)

    agents_dir = repo_root / ".claude" / "agents"
    commands_dir = repo_root / ".claude" / "commands"
    hooks_dir = repo_root / "tools" / "cc" / "hooks"
    actual_agents = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0
    actual_commands = len(list(commands_dir.glob("*.md"))) if commands_dir.is_dir() else 0
    actual_helpers = len([
        p for p in hooks_dir.glob("_*.py")
        if p.name != "__init__.py"
    ]) if hooks_dir.is_dir() else 0
    # Live counts for the audit nouns.
    # SoT for check count is tests/test_release_check.py's pinned assertion.
    # (Result count differs from def-check-* count: one function returns 2 results.)
    _test_rc = repo_root / "tests" / "test_release_check.py"
    # The check count is scraped from the `len(results) == N` SoT assertion in
    # tests/test_release_check.py. Two PRESENT-file conditions both fail LOUD --
    # a silent fall-back to 0 would let a stale "N checks" doc claim pass
    # unverified and could trip a confusing false FAIL elsewhere:
    #   (1) oversized (>= 500 KB): an adversarially-huge test file. The raise
    #       fires BEFORE read_text, so it is never read into memory -- and it is
    #       NOT silently skipped (which would resurrect the very silent-0 this
    #       guards against; a half-megabyte test_release_check.py is an anomaly
    #       worth surfacing, not swallowing).
    #   (2) drifted anchor: present-and-readable but the assertion was
    #       renamed/reworded so the regex no longer matches.
    # The file-ABSENT case stays a benign 0 (a synthetic or adopter repo without
    # this test never claims "N checks").
    actual_checks = 0
    if _test_rc.is_file():
        if _test_rc.stat().st_size >= 500_000:
            raise RuntimeError(
                "release_check.docs_count_claims: tests/test_release_check.py is "
                "unexpectedly large (>= 500 KB) -- refusing to scrape the "
                "`len(results) == N` check-count anchor rather than silently "
                "fall back to 0."
            )
        _m = re.search(
            r"assert\s+len\(results\)\s*==\s*(\d+)",
            _test_rc.read_text(encoding="utf-8"),
        )
        if _m is None:
            raise RuntimeError(
                "release_check.docs_count_claims: the `len(results) == N` "
                "check-count anchor in tests/test_release_check.py did not match "
                "-- the SoT assertion drifted (renamed/reworded). Restore it or "
                "update this scrape; refusing to verify 'N checks' doc claims "
                "against a silent 0."
            )
        actual_checks = int(_m.group(1))
    corpus_dir = repo_root / "bench" / "corpus"
    actual_bypass = len([
        p for p in corpus_dir.glob("BC-[0-9]*.json")
    ]) if corpus_dir.is_dir() else 0
    # Intersect with the canonical roster so a stray non-canonical .py (e.g.
    # a refactor backup write_guard_backup.py) cannot inflate the count and
    # trip a false-positive docs_count_claims release block. Sister-site of
    # doctor._check_doc_drift + audit_accuracy._live_count_hooks.
    _canonical_hooks = set(get_canonical_hook_scripts())
    actual_hooks = len([
        p for p in hooks_dir.glob("*.py")
        if p.name in _canonical_hooks
    ]) if hooks_dir.is_dir() else 0
    tests_dir = repo_root / "tests"
    actual_test_fns = sum(
        ln.lstrip().startswith("def test_")
        for p in tests_dir.rglob("test_*.py")
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
    ) if tests_dir.is_dir() else 0

    skip_markers = ("per minute", "per second", "concurrent")

    # (regex, live_count, offender_label) — the label is interpolated as
    # "claims {token} {label} (live: {count})". The seven nouns are the
    # doc-truth audit set; the suite spec uses "(test suite)" so its
    # offender string omits a bare noun (it counts test functions, not a
    # noun a doc would name inline).
    claim_specs: list[tuple[re.Pattern[str], int, str]] = [
        (make_count_claim_regex(r"agents?"), actual_agents, "agents"),
        (make_count_claim_regex(r"commands?"), actual_commands, "commands"),
        (make_count_claim_regex(r"(?:hook\s+)?helpers?(?:\s+modules?)?"),
         actual_helpers, "helpers"),
        (make_count_claim_regex(r"checks?"), actual_checks, "checks"),
        (make_count_claim_regex(r"bypass\s+classes?"), actual_bypass,
         "bypass classes"),
        (make_count_claim_regex(r"hook\s+scripts?"), actual_hooks, "hooks"),
        (make_count_claim_regex(r"(?:test\s+)?suite"), actual_test_fns,
         "(test suite)"),
    ]

    public_docs = discover_public_docs(repo_root)
    offenders: list[str] = []
    for doc in public_docs:
        text = doc.read_text(encoding="utf-8")
        rel = doc.relative_to(repo_root).as_posix()
        for line in text.splitlines():
            if any(s in line.lower() for s in skip_markers):
                continue
            for claim_re, actual, label in claim_specs:
                for m in claim_re.finditer(line):
                    n = parse_count_token(m.group(1))
                    if n is None:
                        continue
                    if n != actual:
                        offenders.append(
                            f"{rel}: claims {m.group(1)} {label} (live: {actual})"
                        )
    if offenders:
        return CheckResult(
            "docs_count_claims", "FAIL",
            f"{len(offenders)} mismatch(es); first: {offenders[0]}",
        )
    return CheckResult(
        "docs_count_claims", "PASS",
        f"{actual_agents} agents, {actual_commands} commands, "
        f"{actual_helpers} helpers, {actual_checks} checks, "
        f"{actual_bypass} bypass classes, {actual_hooks} hooks "
        f"across {len(public_docs)} docs",
    )


# ── Hook protocol correctness ───────────────────────────────────────


def check_hook_protocol_correct(repo_root: Path = REPO_ROOT) -> CheckResult:
    """tools/cc/hooks/*.py must not return 2 (the channel-XOR contract)."""
    hooks_dir = repo_root / "tools" / "cc" / "hooks"
    if not hooks_dir.is_dir():
        return CheckResult("hook_protocol_correct", "FAIL", "hooks dir missing")
    offenders: list[str] = []
    for hook in sorted(hooks_dir.glob("*.py")):
        if hook.name.startswith("_"):
            continue
        text = hook.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#", 1)[0]  # ignore comments
            if re.search(r"\breturn\s+2\b", stripped):
                offenders.append(f"{hook.name}:{i}")
            if re.search(r"\bsys\.exit\(\s*2\s*\)", stripped):
                offenders.append(f"{hook.name}:{i}")
    if offenders:
        return CheckResult(
            "hook_protocol_correct", "FAIL",
            f"{len(offenders)} offender(s); first: {offenders[0]}",
        )
    return CheckResult("hook_protocol_correct", "PASS")


def check_sharp_edges_correct(repo_root: Path = REPO_ROOT) -> CheckResult:
    """docs/SHARP_EDGES.md must not say 'exit 2 + JSON' (stale wording)."""
    sharp = repo_root / "docs" / "SHARP_EDGES.md"
    if not sharp.exists():
        return CheckResult("sharp_edges_correct", "PASS", "docs/SHARP_EDGES.md absent")
    text = sharp.read_text(encoding="utf-8")
    for m in re.finditer(r"exit\s*2.{0,20}JSON", text, re.IGNORECASE):
        return CheckResult(
            "sharp_edges_correct", "FAIL",
            f"stale 'exit 2 + JSON' phrasing at offset {m.start()}",
        )
    return CheckResult("sharp_edges_correct", "PASS")


# ── SessionStart correction ─────────────────────────────────────────


def check_sessionstart_no_block_claim(repo_root: Path = REPO_ROOT) -> CheckResult:
    """README/CLAUDE/SHARP_EDGES/INSTALL-CI must not assert SessionStart blocks
    or refuses anything (calibrated 'cannot block' survives)."""
    targets = [
        repo_root / "README.md",
        repo_root / "CLAUDE.md",
        repo_root / "docs" / "SHARP_EDGES.md",
        repo_root / "docs" / "INSTALL-CI.md",
    ]
    pat = re.compile(r"\bSessionStart\b[^.\n]{0,80}\b(refuse|block)s?\b", re.IGNORECASE)
    offenders: list[str] = []
    for doc in targets:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for m in pat.finditer(text):
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 5)
            window = text[start:end]
            if _is_negated(window) or "cannot" in window.lower():
                continue
            offenders.append(f"{doc.name}: {m.group(0)!r}")
    if offenders:
        return CheckResult(
            "sessionstart_no_block_claim", "FAIL",
            f"{len(offenders)} offender(s); first: {offenders[0]}",
        )
    return CheckResult("sessionstart_no_block_claim", "PASS")


# ── Renderer fix ────────────────────────────────────────────────────


def check_live_surface_clean(repo_root: Path = REPO_ROOT) -> CheckResult:
    """cc/LIVE_SURFACE.md must not contain raw YAML block markers."""
    live = repo_root / "cc" / "LIVE_SURFACE.md"
    if not live.exists():
        return CheckResult("live_surface_clean", "FAIL", "cc/LIVE_SURFACE.md missing")
    text = live.read_text(encoding="utf-8")
    if re.search(r"—\s*[>|]", text) or re.search(r"description:\s*[>|]", text):
        return CheckResult(
            "live_surface_clean", "FAIL",
            "raw YAML block scalar marker leaked into rendered surface",
        )
    return CheckResult("live_surface_clean", "PASS")


# ── Security policy ─────────────────────────────────────────────────


def check_security_policy_private(repo_root: Path = REPO_ROOT) -> CheckResult:
    """SECURITY.md exists + private vuln reporting + no public-issue routing.

    Delegates to the single source of truth
    ``espalier.pre_release._check_security_policy`` so this release gate and
    ``espalier pre-release`` can never disagree about what a valid SECURITY.md
    is. Parity is pinned by ``tests/test_release_check.py``.
    """
    from espalier.pre_release import _check_security_policy

    sec = repo_root / "SECURITY.md"
    if not sec.exists():
        # _check_security_policy defers the missing-file failure to
        # _check_required_files; this gate reports it explicitly (prior behaviour).
        return CheckResult("security_policy_private", "FAIL", "SECURITY.md missing")
    failures = _check_security_policy(repo_root)
    if failures:
        return CheckResult("security_policy_private", "FAIL", failures[0])
    return CheckResult("security_policy_private", "PASS")


# ── Frontmatter & plugin ────────────────────────────────────────────


def _read_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    current_key: str | None = None
    for line in block.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            key, _, val = line.partition(":")
            current_key = key.strip()
            out[current_key] = val.strip()
        elif current_key:
            out[current_key] += " " + line.strip()
    return out


def check_claude_agent_frontmatter(repo_root: Path = REPO_ROOT) -> CheckResult:
    agents_dir = repo_root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return CheckResult("claude_agent_frontmatter", "FAIL", "agents dir missing")
    required_fields = ("name", "description")
    offenders: list[str] = []
    n = 0
    for agent in sorted(agents_dir.glob("*.md")):
        n += 1
        fm = _read_frontmatter(agent)
        if not fm:
            offenders.append(f"{agent.name}: no frontmatter")
            continue
        missing = [f for f in required_fields if not fm.get(f)]
        if missing:
            offenders.append(f"{agent.name}: missing {missing}")
    if offenders:
        return CheckResult(
            "claude_agent_frontmatter", "FAIL",
            f"{len(offenders)}/{n} bad; first: {offenders[0]}",
        )
    return CheckResult("claude_agent_frontmatter", "PASS", f"{n} agents")


# ── Versioning ──────────────────────────────────────────────────────

# The dated-header and [Unreleased]-body regexes are owned by espalier.changelog
# (the importable canon shared with the documented-claims tests); aliased to the
# private names this module already uses. Content detection (has_content /
# substantive_entries / section_body) is canon there too and is imported above --
# it used to be hand-rolled inline here as `^###`, which is precisely how this
# gate went blind. Do not re-roll it.
_DATED_VERSION_RE = DATED_VERSION_RE
_UNRELEASED_BODY_RE = UNRELEASED_BODY_RE


def check_version_consistent(repo_root: Path = REPO_ROOT) -> CheckResult:
    """Verify CHANGELOG reflects the pyproject version.

    Structural checks (not a plain string-match):

    - The pyproject version must have a dated CHANGELOG section
      (## [X.Y.Z] — YYYY-MM-DD).
    - That dated section must not be empty — a header minted without its
      release notes is the release-cut slip this gate exists to catch.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return CheckResult("version_consistent", "FAIL", "pyproject.toml missing")
    # The gate's credibility is only as wide as its surface list. Every file
    # carrying the version literal is enumerated in the VERSION_SURFACES
    # registry (pyproject is index 0 / the canonical); fail if ANY surface
    # disagrees so the gate can no longer print OK on a version-skewed tree
    # (e.g. bench/RESULTS.md stamped one prerelease behind pyproject while
    # this check inspected only CHANGELOG).
    # Read the canonical version through the registry too (not a second inline
    # regex). The registry pattern is column-0 anchored, so an indented decoy
    # `version = ...` in an earlier [tool.*] table cannot shadow the real
    # [project].version.
    from espalier.version_surfaces import VERSION_SURFACES, read_surface_version

    version = read_surface_version(repo_root, *VERSION_SURFACES[0])
    if version is None:
        return CheckResult("version_consistent", "FAIL", "version not found in pyproject")

    surface_drift = []
    for relpath, pattern in VERSION_SURFACES[1:]:
        path = repo_root / relpath
        if not path.is_file():
            continue  # absent surface (e.g. adopter without bench/RESULTS.md)
        got = read_surface_version(repo_root, relpath, pattern)
        if got is None:
            # The file is present but the extractor stopped matching — the
            # surface's format drifted. read_surface_version collapses "absent"
            # and "no-match" to None; the is_file() pre-check above
            # distinguishes them so a stranded surface fails the gate instead
            # of being silently treated as "agrees".
            surface_drift.append(
                f"{relpath} present but version literal not found "
                f"(extractor stopped matching - surface stranded)"
            )
        elif got != version:
            surface_drift.append(
                f"{relpath} declares {got!r}, pyproject declares {version!r}"
            )
    if surface_drift:
        return CheckResult(
            "version_consistent", FAIL,
            "version surface drift: " + "; ".join(surface_drift),
        )

    changelog = repo_root / "CHANGELOG.md"
    if not changelog.exists():
        return CheckResult("version_consistent", "FAIL", "CHANGELOG.md missing")
    text = changelog.read_text(encoding="utf-8")

    # 1. The current version must have a dated section.
    dated_versions = {
        match.group("version"): match.group("date")
        for match in _DATED_VERSION_RE.finditer(text)
    }
    if version not in dated_versions:
        return CheckResult(
            "version_consistent", "FAIL",
            f"pyproject {version!r} has no dated CHANGELOG section "
            f"(format: '## [{version}] - YYYY-MM-DD'). "
            f"Dated versions in CHANGELOG: {sorted(dated_versions)}",
        )

    # 2. The dated section for the current version must carry content.
    #
    #    This leg used to assert the OPPOSITE side of the same slip --
    #    "[Unreleased] must be empty" -- and decided "empty" by counting
    #    `### Heading` lines. CHANGELOG.md has never contained an h3; it
    #    labels groups `**Bold**`. So the detector matched nothing on every
    #    tree and the gate printed OK over a 2,400-line backlog: green
    #    because it could not fail, not because the property held. Filed
    #    twice as the line number drifted (DEF-457, DEF-591).
    #
    #    Repointing it at bullets was refuted by measurement. [Unreleased]
    #    legitimately accumulates the dev record between releases, and this
    #    gate runs on every push to main -- the release-check job in
    #    .github/workflows/release.yml carries no `if:` -- so an emptiness
    #    assertion reds main for the whole pre-release period. Emptiness is
    #    only owed AT the cut, and the cut is not detectable from the tree.
    #
    #    So the invariant is asserted from the side that is true on every
    #    tree: the section you just dated must not be empty. It catches the
    #    same operator slip -- version bumped, header added, notes never
    #    moved -- and it catches the half that actually reaches users, since
    #    a published `## [0.9.0]` with nothing under it tells a reader
    #    nothing changed.
    #
    #    Check 1 above guarantees the section exists, so the None branch is
    #    unreachable today -- and it FAILS rather than skipping, deliberately.
    #    `if body is not None and not has_content(body)` reads harmless but
    #    resolves an internal inconsistency to a silent PASS, which is the
    #    fail-open shape this repo keeps finding in its own gates. A reorder
    #    that decouples the two DATED_VERSION_RE reads should be loud.
    body = section_body(text, version)
    if body is None:
        return CheckResult(
            "version_consistent", "FAIL",
            f"internal: {version!r} has a dated header per check 1 but "
            f"section_body could not extract it -- the two reads have "
            f"diverged; treat as a gate bug, not a CHANGELOG defect.",
        )
    if not has_content(body):
        unrel_match = _UNRELEASED_BODY_RE.search(text)
        staged = (
            len(substantive_entries(unrel_match.group("body")))
            if unrel_match else 0
        )
        stranded = (
            f" while [Unreleased] holds {staged} "
            f"{'entry' if staged == 1 else 'entries'}"
        ) if staged else ""
        return CheckResult(
            "version_consistent", "FAIL",
            f"[{version}] is dated but carries no release notes{stranded}. "
            f"Move the notes into the dated section.",
        )

    return CheckResult(
        "version_consistent", "PASS",
        f"{version} (dated {dated_versions[version]})",
    )


# ── Required files ──────────────────────────────────────────────────


def _file_exists_check(name: str, rel: str, repo_root: Path) -> CheckResult:
    if (repo_root / rel).exists():
        return CheckResult(name, "PASS")
    return CheckResult(name, "FAIL", f"{rel} missing")


def check_license_present(repo_root: Path = REPO_ROOT) -> CheckResult:
    return _file_exists_check("license_present", "LICENSE", repo_root)


def check_security_present(repo_root: Path = REPO_ROOT) -> CheckResult:
    return _file_exists_check("security_present", "SECURITY.md", repo_root)


def check_contributing_present(repo_root: Path = REPO_ROOT) -> CheckResult:
    return _file_exists_check("contributing_present", "CONTRIBUTING.md", repo_root)


def check_changelog_present(repo_root: Path = REPO_ROOT) -> CheckResult:
    cl = repo_root / "CHANGELOG.md"
    if not cl.exists():
        return CheckResult("changelog_present", "FAIL", "CHANGELOG.md missing")
    text = cl.read_text(encoding="utf-8")
    if not re.search(r"^##\s*\[\d", text, re.MULTILINE):
        return CheckResult(
            "changelog_present", "FAIL",
            "CHANGELOG.md has no dated version section",
        )
    return CheckResult("changelog_present", "PASS")


# ── Publish-time URL gate ───────────────────────────────────────────


def _canonical_release_urls(repo_root: Path) -> list[tuple[str, str]]:
    """The (label, url) pairs the publish-time gate verifies: the canonical
    project Homepage (from ``[project.urls]``) and the CI-badge SVG (from the
    README). Every self-referential doc link + clone URL derives from the
    Homepage slug, so these two are the load-bearing pair."""
    urls: list[tuple[str, str]] = []
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        # Accept either TOML quote style (double or single).
        m = re.search(
            r"""(?m)^\s*Homepage\s*=\s*["']([^"']+)["']""",
            pyproject.read_text(encoding="utf-8"),
        )
        if m:
            urls.append(("Homepage", m.group(1)))
    readme = repo_root / "README.md"
    if readme.is_file():
        # Anchor to the CI-workflow badge specifically (an `actions/workflows/
        # <wf>/badge.svg` URL), not just the first `badge.svg` in the README
        # (shields.io status/python badges also end in `.svg`).
        m = re.search(
            r"(https://[^\s)]+?/actions/workflows/[^\s)]+?badge\.svg[^\s)]*)",
            readme.read_text(encoding="utf-8"),
        )
        if m:
            urls.append(("CI badge", m.group(1)))
    return urls


# HTTP statuses that mean "the server is momentarily unhappy", NOT "this URL is
# wrong". A release cut drives a burst of traffic to GitHub, which answers 429
# (rate limit) and transient 5xx; treating those as FAIL would block a cut on a
# blip. They are classified as offline (SKIP) so only a STABLE client error
# (404/410/451 …) — the genuine unpublished/wrong-slug signal — fails.
_TRANSIENT_HTTP: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

# Transport-layer exceptions that mean "could not complete the request" — all
# indistinguishable from no-network, so SKIP. http.client.HTTPException
# (IncompleteRead / BadStatusLine) is NOT an OSError subclass, so it must be
# named explicitly or it escapes as an uncaught "raised:" FAIL.
_TRANSPORT_ERRORS = (
    urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException,
)


def _classify_http_status(status: int) -> tuple[str, object]:
    """Map a resolved HTTP status to a probe outcome. 2xx/3xx is ok; a
    transient status is offline (SKIP); any other 4xx/5xx is a real error."""
    if 200 <= status < 400:
        return ("ok", status)
    if status in _TRANSIENT_HTTP:
        return ("offline", f"transient HTTP {status}")
    return ("http_error", status)


def _probe_url(url: str, timeout: float = 10.0) -> tuple[str, object]:
    """Visit ``url``. Returns one of:

    - ``("ok", status)``         — resolved with a 2xx/3xx status.
    - ``("http_error", code)``   — resolved to a STABLE client error (404/410/
      451 …) — the URL is genuinely dead. The caller FAILs on this.
    - ``("offline", reason)``    — could not reach the host (DNS/connection/
      timeout) OR a transient HTTP status (429/5xx/408). Indistinguishable
      from "no network / try again later", so the caller treats it as SKIP,
      never FAIL.

    A 403/405 (HEAD often disallowed) retries once with GET so a method
    quirk cannot masquerade as a dead URL.
    """
    # Scheme allowlist (mirrors espalier.external_fetch's guard): a canonical
    # URL with a non-http(s) scheme is itself a defect, and urlopen on
    # file:/custom schemes is the S310 risk we refuse outright.
    if not url.lower().startswith(("http://", "https://")):
        return ("http_error", f"blocked-scheme:{url.split(':', 1)[0]}")
    headers = {"User-Agent": "espalier-release-check"}

    def _open(method: str) -> int:
        req = urllib.request.Request(url, method=method, headers=headers)  # noqa: S310 -- scheme guarded to http(s) above
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- scheme guarded to http(s) above
            return getattr(resp, "status", None) or resp.getcode()

    try:
        # A non-raising response still gets status-classified (don't assume a
        # returned response is 2xx — a redirect chain or non-raising transport
        # could yield otherwise).
        return _classify_http_status(_open("HEAD"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 405):  # HEAD not allowed — confirm with GET
            try:
                return _classify_http_status(_open("GET"))
            except urllib.error.HTTPError as e2:
                return _classify_http_status(e2.code)
            except _TRANSPORT_ERRORS as e2:
                return ("offline", getattr(e2, "reason", str(e2)))
        return _classify_http_status(e.code)
    except _TRANSPORT_ERRORS as e:
        return ("offline", getattr(e, "reason", str(e)))


def check_canonical_urls(repo_root: Path = REPO_ROOT) -> CheckResult:
    """The canonical project Homepage + CI-badge SVG resolve (HTTP 200).

    On publish day every badge, clone URL, and self-referential doc link
    derives from the ``[project.urls]`` Homepage slug. If the repo is
    unpublished or the slug is wrong they all 404 silently. This gate visits
    the Homepage and the CI-badge SVG so a non-200 fails the cut and the
    dead-link state can never ship unverified.

    OPT-IN — skipped unless ``ESPALIER_RELEASE_CHECK_WITH_URLS=1``. The repo
    is unpublished pre-launch (every URL 404s today) and the default offline
    test suite must not depend on the network; the operator flips this on at
    the release cut. OFFLINE-SAFE — a connection/DNS error, timeout, or
    transient HTTP status (429/5xx) is SKIP, not FAIL; only a URL that
    resolves to a STABLE client error (404/410/451 …) fails the cut.
    """
    name = "canonical_urls"
    if os.environ.get("ESPALIER_RELEASE_CHECK_WITH_URLS") != "1":
        return CheckResult(
            name, SKIP,
            "opt-in publish-time gate; set ESPALIER_RELEASE_CHECK_WITH_URLS=1 "
            "to verify the canonical Homepage + CI badge resolve (200)",
        )
    urls = _canonical_release_urls(repo_root)
    if not urls:
        return CheckResult(
            name, FAIL,
            "no canonical URLs found (pyproject [project.urls].Homepage / "
            "README badge.svg)",
        )
    failures: list[str] = []
    unreachable: list[str] = []
    for label, url in urls:
        outcome, info = _probe_url(url)
        if outcome == "http_error":
            failures.append(f"{label} -> HTTP {info}: {url}")
        elif outcome == "offline":
            unreachable.append(f"{label} ({info})")
    if failures:
        return CheckResult(name, FAIL, "; ".join(failures))
    if unreachable:
        return CheckResult(
            name, SKIP, f"network unreachable, not verified: {'; '.join(unreachable)}",
        )
    return CheckResult(name, PASS, f"{len(urls)} canonical URL(s) resolve (200)")


# ── Aggregator ──────────────────────────────────────────────────────


# Order matters for the printed table — keep package/CLI first, files
# at the end as a "did anything obvious go missing" sanity floor.
ALL_CHECKS = (
    check_package_import,
    check_cli_entrypoint,
    check_tracked_noise,
    check_release_archive_builds_and_clean,  # returns 2 results; handled in main
    check_docs_no_phantom_files,
    check_docs_no_overclaim,
    check_docs_count_claims,
    check_hook_protocol_correct,
    check_sharp_edges_correct,
    check_sessionstart_no_block_claim,
    check_live_surface_clean,
    check_security_policy_private,
    check_claude_agent_frontmatter,
    check_version_consistent,
    check_license_present,
    check_security_present,
    check_contributing_present,
    check_changelog_present,
    check_canonical_urls,
    check_tests_pass,
    check_wheel_smoke,
)


def run_all_checks(repo_root: Path = REPO_ROOT) -> list[CheckResult]:
    results: list[CheckResult] = []
    for fn in ALL_CHECKS:
        try:
            out = fn(repo_root)
        except Exception as e:  # noqa: BLE001
            results.append(CheckResult(fn.__name__.removeprefix("check_"), "FAIL", f"raised: {e}"))
            continue
        if isinstance(out, tuple):
            results.extend(out)
        else:
            results.append(out)
    return results


def print_results(results: list[CheckResult]) -> None:
    width = max(len(r.name) for r in results) + 2
    for r in results:
        line = f"{r.name:<{width}}{r.status}"
        if r.detail:
            line += f"   {r.detail}"
        print(line)
    passes = [r for r in results if r.status == PASS]
    fails = [r for r in results if r.status == FAIL]
    skips = [r for r in results if r.status == SKIP]
    if fails:
        print(f"\n{len(fails)} check(s) failed.")
        return
    # Distinguish truly-passed from env-gated SKIP in the summary.
    # The "release_check OK" trailer is part of the docs/DEMO.md contract
    # (tests/test_demo_end_to_end.py asserts it). Exit code stays 0 when
    # no FAIL regardless of SKIP — preserves fast-signal-green semantics.
    if skips:
        print(f"\n{len(passes)} passed, {len(skips)} skipped "
              f"(set ESPALIER_RELEASE_CHECK_WITH_TESTS=1 and "
              f"ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE=1 for full ladder).")
    else:
        print(f"\nAll {len(results)} checks passed.")
    print("release_check OK")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Release-readiness gate. Default: fast local signal.",
    )
    parser.add_argument(
        "--validate-archive",
        metavar="PATH",
        help="Validate an existing release ZIP path (e.g. one downloaded "
             "from GitHub releases) rather than the freshly-built archive. "
             "Runs name-safety + classifier + independent denylist, then the "
             "required-content floor.",
    )
    args = parser.parse_args(argv)

    if args.validate_archive:
        return _validate_existing_archive(Path(args.validate_archive))

    results = run_all_checks(REPO_ROOT)
    print_results(results)
    return 1 if any(r.status == FAIL for r in results) else 0


def _validate_existing_archive(path: Path) -> int:
    """Validate an existing release ZIP: name-safety, classifier and denylist
    (three independent witnesses, fail if any rejects), then the required-
    content floor the built-archive check applies (fail if a load-bearing
    member is missing -- a near-empty ZIP passed the witnesses alone).
    """
    if not path.exists():
        print(f"FAIL: {path} not found")
        return 1
    if not path.is_file() or path.suffix.lower() != ".zip":
        print(f"FAIL: {path} is not a .zip file")
        return 1
    try:
        with zipfile.ZipFile(path) as zf:
            members = zf.namelist()
    except zipfile.BadZipFile as e:
        print(f"FAIL: {path} is not a valid ZIP archive ({e})")
        return 1
    name_safety_rejects, classifier_rejects, denylist_rejects = (
        _scan_members(members)
    )
    if name_safety_rejects or classifier_rejects or denylist_rejects:
        print(f"FAIL: {path} contains rejected members:")
        for m, reason in name_safety_rejects:
            print(f"  {m}: name-safety: {reason}")
        # This site historically prints the repo-relative path for classifier
        # rejects; _scan_members returns the raw member name, so convert here
        # to keep the output byte-identical to the pre-extraction block.
        for name, c in classifier_rejects:
            print(f"  {_archive_member_to_rel(name)}: classifier: {c}")
        for m, r in denylist_rejects:
            print(f"  {m}: denylist: {r}")
        return 1
    missing = missing_required_members(members)
    if missing:
        print(f"FAIL: {path} missing required content: {', '.join(missing)}")
        return 1
    print(
        f"PASS: {path} ({len(members)} members) clean per name-safety + classifier "
        "+ denylist + content floor"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
