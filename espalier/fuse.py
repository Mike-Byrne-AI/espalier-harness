"""``espalier fuse`` — build a new fusion repo = host copy + harness overlay.

The single source of truth for the fusion model. Both the host repo and
the espalier checkout are left 100% untouched; a NEW third directory is created
holding a copy of the host + the espalier harness overlaid at root.

This is the core every distribution channel calls: the folder model runs it
directly (`python3 -m espalier fuse <host> --out <dir>`); a future single-file
fetcher / pipx shim fetches espalier then runs this same command.

v1 does the MECHANICAL bootstrap (copy + overlay + reseed + wire via init). The
taste — repurposing the verifier tests, emptying espalier-pinned scanner
registries, re-seeding agent bodies — is the first Claude session in the fused
repo (see ``fusion_manifest.FINISH_UP_STEPS``).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from espalier import fusion_manifest
from espalier._atomic_io import atomic_write_text
from espalier._rmtree import remove_file, remove_tree
from espalier._text import os_error_text, plural

# Noise never copied even from a non-git host (mirrors the gitignored set).
_NONGIT_SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", "dist", "build", ".espalier",
    ".espalier-state", "reports",
}

_INCLUDE_EXACT = frozenset(p for p in fusion_manifest.HARNESS_INCLUDE if not p.endswith("/"))


def _espalier_source_root() -> Path:
    """The espalier checkout root (where tools/, espalier/, docs/ live).

    Under a NON-EDITABLE (wheel) install this resolves to ``site-packages/``,
    which is NOT a checkout root: see :func:`_require_source_checkout`.
    """
    return Path(__file__).resolve().parent.parent


def missing_source_entries(src: Path) -> list[str]:
    """``HARNESS_INCLUDE`` entries that do not exist under ``src``.

    The overlay copies these paths out of the espalier source tree. Under a
    wheel install the harness payload DOES ship, but at REMAPPED locations
    (``tools/`` -> ``espalier/_vendor/cc/``, ``.claude/*`` and ``docs/*`` ->
    ``espalier/assets/...``), so a source-root walk finds almost none of it.
    """
    return [
        rel for rel in fusion_manifest.HARNESS_INCLUDE
        if not (src / rel.rstrip("/")).exists()
    ]


def _require_source_checkout(src: Path) -> None:
    """Refuse a fusion this install layout cannot actually build.

    ``fuse`` overlays the harness by reading it out of the espalier SOURCE
    TREE. A non-editable (wheel) install has no source tree: ``tools/`` is
    deliberately not shipped as a top-level package (it would squat a generic
    import name), so ``_espalier_source_root()`` lands in ``site-packages/``
    where only ``espalier/`` itself resolves.

    Before this check, that produced a confidently wrong result rather than an
    error: the overlay plan could never contain a file ``init`` also deploys,
    so the "init deployed it already" branch was structurally unreachable,
    ``harness_via_init`` was pinned at 0 by construction, and ``fuse`` exited 1
    with "init did not wire the governance surface" -- blaming init, which had
    in fact succeeded -- AFTER leaving a half-built fusion on disk. Refusing up
    front is both accurate and cheaper to recover from.

    ``init`` is unaffected and still works under a wheel: it reads its deploy
    source from packaged data via ``cli._deploy_source_path``. Only ``fuse``
    needs the source tree, and teaching it the remapped layout is a separate,
    larger job (it also has to decide what to do about the self-host-only
    entries that ship in no install mode at all).
    """
    if (src / "tools").is_dir():
        return
    missing = missing_source_entries(src)
    # The remediation spells the interpreter the operator will type; resolve it
    # on the host (DEF-383a: a literal `python` is command-not-found on stock
    # macOS). Lazy import: cli imports fuse at parser-build time.
    from espalier.cli import _remedy_py
    py = _remedy_py()
    raise ValueError(
        f"`fuse` needs an espalier SOURCE CHECKOUT, but espalier is running "
        f"from a non-editable (wheel) install: {src} is not a checkout root "
        f"({len(missing)} of {len(fusion_manifest.HARNESS_INCLUDE)} fusion-"
        f"manifest entries are absent there; under a wheel they ship at "
        f"remapped paths the overlay cannot read).\n"
        f"  Supported: clone the repo and install it editable, then re-run:\n"
        f"    git clone https://github.com/Mike-Byrne-AI/espalier-harness.git\n"
        f"    cd espalier-harness && {py} -m pip install -e .\n"
        f"    {py} -m espalier fuse <host> --out <out>\n"
        f"  (`{py} -m espalier init <repo>` works normally under this "
        f"install — it deploys from packaged data. Only `fuse` needs the "
        f"source tree.)"
    )


# Display aliases for the overlay summary. Anything NOT listed falls back to
# its own top-level path segment, so a new fusion-manifest root shows up named
# after itself rather than silently vanishing from the summary.
_OVERLAY_CATEGORY_ALIASES = {"espalier": "engine", ".claude": "claude"}


def _overlay_categories(rels) -> list[str]:
    """Category labels for the paths that ACTUALLY got overlaid.

    The summary line used to be the hardcoded literal
    ``(engine, bench, docs, workflows)`` -- four names printed regardless of
    what was copied. It was wrong in both directions: under a wheel install it
    read ``188 overlaid (engine, bench, docs, workflows)`` while bench/,
    scripts/ and .github/ contributed nothing at all (188 was exactly the
    ``espalier/`` file count -- one category, four names), and even in the
    supported source-checkout mode it never named ``scripts/``, which does
    contribute. Deriving from the copy loop's own output makes the line
    unable to disagree with the fusion it describes.
    """
    seen: list[str] = []
    for rel in rels:
        top = rel.split("/", 1)[0]
        label = _OVERLAY_CATEGORY_ALIASES.get(top, top)
        if label not in seen:
            seen.append(label)
    return sorted(seen)


def _tracked_files(repo: Path) -> list[str] | None:
    """git-tracked repo-relative paths, or None if ``repo`` is not a git repo."""
    try:
        r = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # errors= AND ValueError together, the way cli.py's git captures are
        # written: a host filename that is not valid UTF-8 would otherwise
        # raise UnicodeDecodeError (a ValueError) past the tuple.
        return None
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.split("\0") if p]


def _matches(rel: str, patterns) -> bool:
    """True if ``rel`` equals or is under any pattern (trailing-/ = dir prefix).

    A non-trailing-slash pattern is a FILE and matches by equality only — a
    bare ``startswith`` here would over-match a sibling sharing the prefix
    (``bench/run_benchmark.py.bak`` ⊂ ``bench/run_benchmark.py``), leaking
    stray editor swapfiles/backups into the fusion overlay.
    """
    for pat in patterns:
        if pat.endswith("/"):
            if rel == pat.rstrip("/") or rel.startswith(pat):
                return True
        elif rel == pat:
            return True
    return False


def _should_overlay(rel: str) -> bool:
    """Decide whether espalier's tracked ``rel`` is overlaid into the fusion.

    An EXACT file include (e.g. ``memory/README.md``) overrides a RESEED_SKIP
    dir prefix (``memory/``), so the convention doc ships while espalier's
    memory CONTENT does not.
    """
    if not _matches(rel, fusion_manifest.HARNESS_INCLUDE):
        return False
    if _matches(rel, fusion_manifest.HARNESS_EXCLUDE):
        return False
    if rel in _INCLUDE_EXACT:
        return True
    if _matches(rel, fusion_manifest.RESEED_SKIP):
        return False
    return True


def _nongit_source_files(src: Path) -> list[str]:
    """Repo-relative files for a non-git espalier SOURCE (skip _NONGIT_SKIP_DIRS).

    The primary fetcher channel ships espalier as a ``git archive`` tag tarball
    with no ``.git``, so ``_tracked_files`` returns ``None`` and the overlay
    would silently be empty. This walks the filesystem instead, mirroring
    the host-side noise skip so junk under an INCLUDE'd dir (``espalier/__pycache__/``,
    a stray ``reports/``) never overlays. ``_should_overlay`` still gates the
    result against the manifest exactly as it gates the git-tracked set.
    """
    out: list[str] = []
    for p in src.rglob("*"):  # espalier:safe-walk-ok src is _espalier_source_root (the package's own tree), never an adopter repo
        if not p.is_file():
            continue
        rel_parts = p.relative_to(src).parts
        if any(part in _NONGIT_SKIP_DIRS for part in rel_parts):
            continue
        out.append(p.relative_to(src).as_posix())
    return out


def _copy(src_root: Path, rels: list[str], out: Path) -> int:
    n = 0
    for rel in rels:
        src = src_root / rel
        # Preserve symlinks the host tracks. A plain `if not src.is_file()`
        # both SKIPS symlinks-to-dirs / dangling symlinks (the file vanishes in
        # the fusion) and silently DEREFERENCES file-symlinks (copy2 follows by
        # default, so the fused copy is a regular file). Either way a host that
        # tracks symlinks comes out dirty on its first `git status`. Copy the link
        # itself instead.
        is_symlink = src.is_symlink()
        if not (src.is_file() or is_symlink):
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_symlink:
            # A privilege-less Windows host (core.symlinks=true but no
            # SeCreateSymbolicLinkPrivilege) raises OSError/WinError 1314 from the
            # os.symlink inside copy2(follow_symlinks=False). The broad except in
            # fuse_repos would then roll back the ENTIRE fusion — failing closed on
            # a host config quirk. Mirror git's core.symlinks=false fallback:
            # dereference to a regular-file copy so the fusion completes, WARNing
            # that the link itself was not preserved.
            try:
                shutil.copy2(src, dst, follow_symlinks=False)
            except OSError:
                # If the DEREFERENCE also fails (disk full / dangling target),
                # let it PROPAGATE — fuse_repos rolls back rather than silently
                # shipping an incomplete tree (a skip-with-continue here would
                # turn a genuine ENOSPC into silent data loss). The broad
                # `except OSError` is unavoidable cross-platform — WinError 1314
                # carries no portable errno — so re-raising on the dereference is
                # what keeps non-privilege faults loud.
                shutil.copy2(src, dst, follow_symlinks=True)
                print(f"[fuse] WARN: could not recreate symlink {rel} on this host; "
                      f"copied its target as a regular file (link not preserved).",
                      file=sys.stderr)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        n += 1
    return n


_ESPALIER_TOML_STUB = """\
# espalier.toml — harness configuration for this repo.
#
# Plan Guard: your source is plan-gated by default — routine source edits run
# through an execution plan (start one with /implement-task). That is the
# feature, not a papercut: it keeps changes intentional and reviewable. If a
# directory is pure boilerplate and you want a lighter touch THERE, uncomment
# the line below and list it (a repo-relative path prefix). Leaving this
# commented keeps the plan-gate ON for all of your source.
#
# plan_exempt_prefixes = ["src/", "lib/"]
"""


def _seed_espalier_toml(out: Path) -> bool:
    """Write the commented plan_exempt_prefixes stub iff the fusion has no
    espalier.toml (a host that already ships one owns it). Returns True if
    written. An all-comment TOML parses to defaults (the stub is fully inert)."""
    dst = out / "espalier.toml"
    if dst.exists():
        return False
    atomic_write_text(dst, _ESPALIER_TOML_STUB)
    return True


# A fusion overlays the FULL espalier/ engine into the host, so
# `espalier/__init__.py` presence — the discriminator `harness-guard.yml`'s
# self-host CI jobs gate on — is TRUE in a fusion too, and those jobs (which
# check espalier's OWN source + memory) would fire on the adopter's first PR.
# This tracked marker is the second half of the gate: those jobs run only when
# the engine is present AND this marker is ABSENT (i.e. only in espalier-the-
# source). Plain adopters have no engine; fusions carry the marker; only the
# source repo has the engine and no marker. CI's hashFiles reads the COMMITTED
# file, so the marker must be tracked (it deliberately sits outside the
# gitignored .espalier/ runtime dir).
_FUSION_MARKER = ".espalier-fusion"
_FUSION_MARKER_BODY = """\
# This directory is an Espalier *fusion*: a host repo with the Espalier harness
# overlaid at its root (built by `espalier fuse`). It is NOT the Espalier source
# repository.
#
# DO NOT DELETE. `.github/workflows/harness-guard.yml` reads this marker: the
# espalier-self-host CI jobs (freshness, ruff-lint, mypy-hooks,
# memory-tag-parity)
# check Espalier's OWN source and memory and must never run against your code,
# so they gate on this marker's ABSENCE. Remove it and your first PR will run
# espalier-internal jobs against the host tree and fail. Tracked on purpose —
# CI evaluates the committed file, not the working tree.
"""


def _seed_fusion_marker(out: Path) -> bool:
    """Write the tracked ``.espalier-fusion`` marker (idempotent). Returns True
    if written. Presence — not content — is what `harness-guard.yml` gates on."""
    dst = out / _FUSION_MARKER
    if dst.exists():
        return False
    atomic_write_text(dst, _FUSION_MARKER_BODY)
    return True


# The overlay RESEED_SKIPs espalier's docs/SHARP_EDGES.md monolith
# (espalier-specific CONTENT), but the overlaid harness docs it DOES ship
# (docs/HOOKS.md, docs/WORKFLOW.md — NOT HOOK_ASSUMPTIONS.md, which the
# fusion deliberately does not overlay, see fusion_manifest) still link
# `SHARP_EDGES.md` (relative, same docs/ dir). Without the file those links
# dangle, and a fused adopter's first `reflect`/`doctor` warns on them. This
# seed makes the link target exist — the producer for
# fusion_manifest.SHARP_EDGES_SEED's "near-empty (folder router only)" intent.
# (It does NOT affect the SessionStart orientation step-2 gap — that is
# `is_self_host_repo`-gated, intentional for adopters/fusions, not file-gated.)
#
# The BODY is not defined here. `espalier init` also seeds docs/SHARP_EDGES.md
# (managed_inventory._SEED_DOC_REL_PATHS, sourced through
# _SEED_ASSET_SOURCES -> espalier/assets/seed/SHARP_EDGES.md), and fuse_repos
# runs cmd_init BEFORE this seeder — so on the default run_init=True path init
# writes the file and the skip-if-exists check below makes this a no-op. A
# module-local body would therefore be the flag-dependent second version of one
# adopter-facing file: improved on one side, silently stale on the other.
# Reading the same asset keeps ONE body and keeps this seeder meaningful on the
# `--no-init` path, where it is still the only producer.


def _seed_sharp_edges(out: Path) -> bool:
    """Seed a near-empty ``docs/SHARP_EDGES.md`` folder-router stub iff the
    fusion lacks one (a host that already ships the monolith owns it, and on the
    default path ``cmd_init`` has already seeded it — see the note above).
    Returns True if written. The stub exists so the overlaid harness docs'
    relative ``SHARP_EDGES.md`` links resolve (a fusion RESEED_SKIPs the source
    monolith). The body is ``managed_inventory.render_seed_body`` -- the same
    bytes ``init`` writes below the stamp, through the same renderer, so the
    stub cannot diverge from what ``doctor`` prints a stamp for if this seed
    ever gains an adapt header (until 2026-09-05 this read the asset itself;
    equal only because the seed is Tier-1). Stamped since 2026-09-11 with the
    same ``seed_stamp_line`` ``init`` writes: an unstamped stub was preserved
    by every later ``init`` and ``upgrade`` forever, so the sentence the stub
    carries ("refreshed on re-init only while it still matches the copy it
    was deployed from") was false on every fused tree (DEF-432's review)."""
    dst = out / "docs" / "SHARP_EDGES.md"
    if dst.exists():
        return False
    from espalier.managed_inventory import render_seed_body, seed_stamp_line

    body = render_seed_body("docs/SHARP_EDGES.md")
    atomic_write_text(dst, seed_stamp_line(body) + body)
    return True


# bench/README.md ships (the bench corpus + runner verify the overlaid hooks)
# and links `RESULTS.md`, but the scoreboard is a FINISH_UP
# artifact — `bench/run_benchmark.py --update-canonical` writes it AFTER the
# operator repurposes the corpus for the host (the raw espalier corpus
# fail-closes against a fresh fusion by design). Without the file bench/README.md
# dangles on day one; this placeholder makes the link resolve and points at the
# finish-up step.
_BENCH_RESULTS_SEED_BODY = """\
# Benchmark Results

This scoreboard has not been generated for this repo yet. It is a FINISH_UP step:

```
# 1. repurpose bench/corpus + bench/baselines for THIS host's protected zones
# 2. then write the canonical scoreboard:
python3 bench/run_benchmark.py --update-canonical
```

Running it against espalier's raw corpus fail-closes by design (the corpus
attacks espalier's own protected surface, not yours) — see `bench/README.md`.
This placeholder exists so that link resolves until you generate the real table.
"""


def _seed_bench_results(out: Path) -> bool:
    """Seed a placeholder ``bench/RESULTS.md`` iff the fusion lacks one.
    bench/README.md ships and links RESULTS.md, but the scoreboard is a
    FINISH_UP artifact; the stub resolves the link and points at the step that
    generates the real table. Skipped if bench/ was not overlaid or a RESULTS.md
    already exists. Returns True if written."""
    bench_dir = out / "bench"
    if not bench_dir.is_dir():
        return False
    dst = bench_dir / "RESULTS.md"
    if dst.exists():
        return False
    atomic_write_text(dst, _BENCH_RESULTS_SEED_BODY)
    return True


def _fresh_baseline_commit(out: Path, host: Path) -> bool:
    """Commit the copied host files as the fusion's baseline.

    A ``--fresh`` (or worktree-declined) fusion has no history to preserve, so
    without a baseline it would have ZERO commits — ``git log`` says "no commits
    yet" and the operator faces a wall of ``??``. Committing the host snapshot
    NOW (before init/overlay) mirrors the history-preserving path: the harness
    then reads as reviewable uncommitted changes on top of a real baseline.
    Tries the operator's configured git identity first; falls back to a neutral
    one so the baseline always lands. Best-effort — a failure (e.g. an empty
    host with nothing to commit) is non-fatal. Returns True if a commit was made.
    """
    subprocess.run(["git", "-C", str(out), "add", "-A"],
                   check=False, capture_output=True)
    msg = f"Baseline: {host.name} (pre-Espalier-fusion snapshot)"
    r = subprocess.run(["git", "-C", str(out), "commit", "-q", "-m", msg],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return True
    # No git identity configured in this environment -> supply a neutral one
    # inline (does not persist to the repo config) so the baseline still exists.
    r2 = subprocess.run(
        ["git", "-C", str(out), "-c", "user.name=Espalier Fusion",
         "-c", "user.email=fusion@localhost", "commit", "-q", "-m", msg],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r2.returncode == 0


# The workflow install-ci writes into the fusion. Not in the fusion manifest
# (install-ci owns it), so it is spelled here beside the one reader.
_WORKFLOW_REL = ".github/workflows/harness-guard.yml"


def _workflow_tracked(out: Path) -> bool | None:
    """Whether git tracks the CI workflow inside the fusion.

    ``True`` when the file is in the index (staged or committed), ``False``
    when it is on disk and untracked, ``None`` when there is nothing to ask
    about (the file is absent) or git could not answer (no ``git`` on PATH,
    ``out`` is not a repository, a timeout, output that is not UTF-8). The
    epilogue reads this instead of assuming a commit it never made
    (DEF-807, driven on the Windows host 2026-09-14): on the fresh path the
    baseline commit lands at step 2 and install-ci writes the workflow at
    step 5, and on the history-preserving path nothing commits at all -- so
    the file is untracked on BOTH paths until the adopter stages it, and
    GitHub runs nothing it cannot see. A non-answer claims nothing either
    way; it never reads as tracked.
    """
    try:
        if not (out / _WORKFLOW_REL).is_file():
            return None
        r = subprocess.run(
            ["git", "-C", str(out), "ls-files", "--error-unmatch", "--", _WORKFLOW_REL],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:  # the pathspec matched no tracked file
        return False
    return None  # 128: not a repository, or another failure of git's own


# The overlay re-writes the same `.claude` `.md` families init deploys.
# init marks everything it writes with `espalier:managed` so `clean-generated`
# recognizes the managed surface on uninstall; the overlay's unmarked copies
# would be ORPHANED. Mark the same .md families init does.
# Purpose-scoped MARKER-policy (which .md families get the managed marker) — NOT the
# same as reflect's DISCOVERY_DIRS (orphan-detection policy); do not collapse them.
_MANAGED_MD_PREFIXES = (".claude/agents/", ".claude/commands/", ".claude/skills/")


def _is_managed_md(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return r.endswith(".md") and r.startswith(_MANAGED_MD_PREFIXES)


def _mark_overlaid_md(dst: Path) -> None:
    """Insert the `espalier:managed` marker into an overlaid .claude .md body
    (idempotent: apply_marker_to_md returns the content unchanged if marked)."""
    from espalier import managed_markers
    text = dst.read_text(encoding="utf-8")
    marked = managed_markers.apply_marker_to_md(text)
    if marked != text:
        atomic_write_text(dst, marked)


def plan_fusion(host: Path, out: Path) -> dict:
    """Compute (no writes) the host file set, the harness overlay set, and any
    host/harness path collisions. Collision-detection-FIRST so a real fuse never
    half-writes."""
    host = host.resolve()
    src = _espalier_source_root()
    # Install-mode precondition FIRST: plan_fusion is the only path into a
    # fusion (dry-run and real both route through it) and it runs before any
    # write, so refusing here means an unsupported install never leaves a
    # half-built tree behind.
    _require_source_checkout(src)

    host_tracked = _tracked_files(host)
    # §C21: a non-empty tracked set is a PRECONDITION, asserted before any plan
    # is built. `git ls-files` says "absent" with None and "empty" with [] — both
    # mean there is no host source to copy, so both must refuse here. Testing
    # only for None let a git-inited-but-uncommitted host through, and `fuse`
    # then built a fusion containing zero of the user's files and exited 0
    # reporting "history preserved".
    if host_tracked is not None and not host_tracked:
        raise ValueError(
            f"host git repo tracks no files: {host}. `fuse` copies git-tracked "
            f"files only, so the fusion would contain none of your source. "
            f"`git add -A && git commit` in the host first."
        )
    if host_tracked is None:
        # Refuse a non-git host. `fuse` copies git-tracked files only; a
        # filesystem walk of an un-inited host would (1) carry secrets
        # (.env, *.sqlite) it has no .gitignore to exclude, (2) silently DROP
        # real source nested under a generic dir name (`src/reports/x.py` —
        # `reports` is in _NONGIT_SKIP_DIRS), and (3) break the history-
        # preservation assumption. `git init` first is one line and removes
        # all three.
        raise ValueError(
            f"host is not a git repo: {host}. Run `git init` (and commit) in the "
            f"host first — `fuse` copies git-tracked files only, so an un-inited "
            f"host would carry secrets and miss source under ignored dir names."
        )
    host_files = host_tracked
    host_set = set(host_files)

    # A non-git SOURCE (git-archive tarball) has no .git → fall back to a
    # manifest-gated filesystem walk so the overlay is never silently empty.
    esp_tracked = _tracked_files(src)
    # §C21, same rule on the SOURCE half: an extracted git-archive export sitting
    # under a parent git worktree answers rc 0 with NO paths, so `is None` never
    # fires and the overlay is silently empty. Falsiness catches both shapes.
    if not esp_tracked:
        esp_tracked = _nongit_source_files(src)
    harness_files = [rel for rel in esp_tracked if _should_overlay(rel)]
    reseed_skipped = sum(
        1 for rel in esp_tracked
        if _matches(rel, fusion_manifest.HARNESS_INCLUDE)
        and not _matches(rel, fusion_manifest.HARNESS_EXCLUDE)
        and rel not in _INCLUDE_EXACT
        and _matches(rel, fusion_manifest.RESEED_SKIP)
    )
    collisions = sorted(set(harness_files) & host_set)

    return {
        "host": str(host), "out": str(out.resolve()),
        "host_is_git": True,  # non-git hosts are refused above
        "host_files": host_files, "harness_files": harness_files,
        "collisions": collisions, "reseed_skipped": reseed_skipped,
    }


def fuse_repos(host: Path, out: Path, *, preserve_history: bool = True,
               dry_run: bool = False, run_init: bool = True,
               wire_hooks: bool = False) -> dict:
    """Build the fusion repo. Returns a report dict. Raises on bad inputs /
    collisions (before any write)."""
    host = host.resolve()
    out = out.resolve()
    src = _espalier_source_root()

    if not host.is_dir():
        raise FileNotFoundError(f"host repo not found: {host}")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(
            f"--out exists and is not empty: {out} (refusing to clobber)")
    if out == host or out == src or src in out.parents or host in out.parents:
        raise ValueError(
            "--out must be a NEW directory outside both the host and espalier")

    plan = plan_fusion(host, out)
    if plan["collisions"]:
        raise RuntimeError(
            f"{plural(len(plan['collisions']), 'host/harness path collision')}; refusing "
            f"to clobber host files: {plan['collisions'][:15]}. Resolve the "
            f"overlapping paths in the host or adjust the fusion manifest.")

    report = {
        "host": str(host), "out": str(out), "dry_run": dry_run,
        "host_is_git": plan["host_is_git"],
        "host_files": len(plan["host_files"]),
        "host_files_planned": len(plan["host_files"]),
        "harness_overlaid": 0, "harness_via_init": 0,
        "overlay_categories": [],
        "history_preserved": False, "init_rc": None,
    }
    if dry_run:
        # Best-effort overlay estimate (real run skips init's managed surface).
        report["harness_overlaid"] = len(plan["harness_files"])
        report["overlay_categories"] = _overlay_categories(plan["harness_files"])
        return report

    # A mid-write fault leaves a half-built `out` that then BLOCKS retry via
    # the non-empty-out guard above. The fault is not only OSError (disk full,
    # perms) — `cmd_init` and the seed helpers can raise
    # ValueError / KeyError / subprocess.SubprocessError / ImportError, which a
    # narrow `except OSError` would let escape PAST the rollback, re-poisoning the
    # directory. Catch broadly before re-raising; the rollback below removes a
    # fuse-created `out` node entirely, or clears the CONTENTS of a
    # pre-existing dir the operator pointed --out at without deleting the node.
    created_out = not out.exists()
    try:
        out.mkdir(parents=True, exist_ok=True)
        host_set = set(plan["host_files"])

        # 1. host copy (tracked-only; structure preserved; original untouched).
        # Capture the REAL copied count: _copy silently skips any tracked path
        # that is not a regular file/symlink (a locally-deleted tracked file in a
        # dirty worktree, a submodule gitlink). Reporting the git-ls-files PLANNED
        # count while the fusion is actually short would print a full count, exit
        # 0, no signal — an INCOMPLETE copy passing as complete. In --fresh the
        # dropped file is absent on disk AND in HEAD, so it is unrecoverable
        # within the fusion; the operator must be told.
        copied = _copy(host, plan["host_files"], out)
        report["host_files"] = copied
        planned = len(plan["host_files"])
        if copied < planned:
            print(
                f"[fuse] WARN: {plural(planned - copied, 'host file')} tracked by git "
                f"could not be copied (not present as regular files/symlinks) -- the "
                f"fusion is an INCOMPLETE copy ({copied}/{planned} host files). A "
                f"locally-deleted tracked file or a submodule gitlink is the usual "
                f"cause; commit or restore it in the host before fusing.",
                file=sys.stderr,
            )
        git_path = host / ".git"
        if preserve_history and plan["host_is_git"] and git_path.is_dir():
            shutil.copytree(git_path, out / ".git")
            report["history_preserved"] = True
        elif preserve_history and plan["host_is_git"] and git_path.is_file():
            # A git worktree / submodule host stores `.git` as a
            # FILE (`gitdir: ...` pointer) whose real object store lives OUTSIDE
            # the host dir (a shared common-dir / the parent's modules/). Copying
            # the pointer would dangle; copying the resolved common-dir risks
            # importing an unrelated repo's history. Decline honestly rather than
            # silently fall through to a fresh `git init` (history dropped with no
            # signal). report["history_preserved"] stays False.
            print(f"[fuse] WARN: host {host} is a git worktree/submodule (.git is "
                  f"a file, not a directory); its commit history is NOT preserved "
                  f"in the fusion. For full lineage, fuse from a normal `git clone`.",
                  file=sys.stderr)

        # 2. the fusion must be a git repo for init's hooks (git diff/log per fire)
        if not (out / ".git").exists():
            subprocess.run(["git", "init", "-q", str(out)], check=False)
            # A fresh init (--fresh, or the worktree-declined case) has
            # no preserved history. Commit the host files as a baseline now so the
            # fusion is never left with zero commits; the harness (init + overlay
            # below) then reads as reviewable uncommitted changes on top.
            report["fresh_baseline_commit"] = _fresh_baseline_commit(out, host)

        # 3. init FIRST — it owns + MARKS the managed surface (hooks/agents/commands/
        #    skills + settings.json + integrity + a host-flavored CLAUDE.md/ESPALIER_MEMORY.md
        #    from a fingerprint of the HOST code only, since the engine isn't overlaid
        #    yet). is_self_host_repo is False here (host pyproject name preserved).
        if run_init:
            from espalier.cli import cmd_init
            init_args = argparse.Namespace(
                repo=str(out), config=None, profile=None,
                write_gitignore=True, dry_run=False,
                wire_hooks=wire_hooks,  # one-shot wiring opt-in pass-through
                # Suppress init's "Start Claude Code" epilogue mid-stream; fuse
                # prints a single one as its true last output (see cmd_fuse end).
                suppress_epilogue=True,
            )
            report["init_rc"] = cmd_init(init_args)

        # 4. overlay the EXTRAS init doesn't deploy (engine, bench, rich docs,
        #    workflows, the tools/cc gap). Skip anything init already created
        #    (marked managed surface) so we don't shadow it with an unmarked copy.
        #    Host collisions were already rejected in plan_fusion (nothing host-owned
        #    is touched).
        overlaid = via_init = 0
        overlaid_rels: list[str] = []
        for rel in plan["harness_files"]:
            if rel in host_set:
                continue  # host-owned (defensive; plan already aborts on these)
            if (out / rel).exists():
                via_init += 1  # init deployed it (marked) — leave it
                continue
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, dst)
            if _is_managed_md(rel):
                _mark_overlaid_md(dst)  # keep the uninstall contract
            overlaid += 1
            overlaid_rels.append(rel)
        report["harness_overlaid"] = overlaid
        report["harness_via_init"] = via_init
        report["overlay_categories"] = _overlay_categories(overlaid_rels)

        # 4b. seed a COMMENTED plan_exempt_prefixes stub (settled decision in
        #     docs/RELEASE_DECISIONS.md). The adopter's source is
        #     plan-gated by DEFAULT — that is the feature. The stub is inert (no
        #     active key); it just makes the lighter-touch knob discoverable. Never
        #     seeded as an active exemption. Skipped if the host already ships one.
        report["seeded_espalier_toml"] = _seed_espalier_toml(out)

        # 4c. drop the tracked `.espalier-fusion` marker so the installed
        #     harness-guard.yml's self-host CI jobs gate OFF here —
        #     a fusion overlays espalier/ but is not the source repo.
        report["fusion_marker"] = _seed_fusion_marker(out)

        # 4d. seed a near-empty docs/SHARP_EDGES.md folder-router.
        #     The overlay skips espalier's monolith (RESEED_SKIP), but the
        #     overlaid harness docs link SHARP_EDGES.md, so without the file a
        #     fused adopter's first reflect/doctor dangles on those links.
        report["seeded_sharp_edges"] = _seed_sharp_edges(out)

        # 4e. seed a placeholder bench/RESULTS.md. bench/README.md
        #     ships and links it, but the scoreboard is a FINISH_UP artifact.
        report["seeded_bench_results"] = _seed_bench_results(out)
    except Exception:  # noqa: BLE001 — re-raised; rollback must run for ANY fault (cmd_init/seed helpers raise non-OSError)
        if out.exists():
            if created_out:
                # fuse created `out` -> remove the node entirely. Best-effort
                # through the one tree removal: the host's `.git` was copied
                # with its read-only packfiles, which a bare rmtree leaves
                # behind on Windows (DEF-734) -- the partial fusion the
                # non-empty guard then refuses on retry.
                remove_tree(out, best_effort=True)
            else:
                # The operator pointed --out at a PRE-EXISTING empty dir, so
                # removing the node would delete one they own. But fuse DID
                # write into it, and leaving those writes poisons retry — the
                # non-empty guard above then refuses with FileExistsError.
                # Clear only the CONTENTS, restoring the empty dir
                # the operator handed us so a retry starts clean.
                try:
                    children = list(out.iterdir())
                except OSError:
                    children = []  # can't even list -> never mask the original fault
                for child in children:
                    try:
                        if child.is_dir() and not child.is_symlink():
                            remove_tree(child, best_effort=True)
                        else:
                            remove_file(child, best_effort=True)
                    except OSError:
                        pass  # best-effort rollback; never mask the original fault
        raise

    # 5. finish the "one command" bootstrap. The core fusion above is
    #    already valid, so these are ADDITIVE — a failure WARNs, never rolls back.
    #    Gate on init having actually wired the managed surface (harness_via_init>0),
    #    matching cmd_fuse's "is the fusion live?" check — never orchestrate onto a
    #    fusion init left unwired (init_rc==0 but zero managed files deployed).
    if run_init and report["init_rc"] == 0 and report["harness_via_init"] > 0:
        _orchestrate_bootstrap(out, report)

    return report


def _run_in_fusion(out: Path, argv: list[str], *, timeout: int = 180) -> int | None:
    """Run a child process against the FUSED repo's self-contained engine
    (zero-pip; PYTHONPATH=out, like the end-to-end test). Returns the rc, or
    None if the process could not be launched / timed out. Output is captured so
    it never spills into ``fuse``'s own report."""
    env = {**os.environ, "PYTHONPATH": str(out)}
    try:
        # subprocess-contract: ok dynamic-argv-runner; the only caller passes espalier's own in-tree `-m espalier fingerprint <out>` CLI, pinned end-to-end by tests/test_fuse.py::TestFuseEndToEnd::test_analyze_fingerprint_refreshed_post_overlay
        r = subprocess.run(argv, cwd=str(out), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.returncode


def _orchestrate_bootstrap(out: Path, report: dict) -> None:
    """The orchestration steps that finish the bootstrap. init wired the
    managed surface; these target the HOST + add the CI merge-gate.
    ``install-ci`` is load-bearing (the PR guarantee); ``fingerprint``
    is a best-effort host-targeting refresh (a fusion is usable without it).

    NOT here: ``bench --update-canonical``. Its corpus is espalier-self-referential
    (it attacks espalier's own self-host protected surface), so a FRESH fusion
    legitimately scores <100% and the canonical-update guard fail-closes — it
    refuses to write a regression into the credibility surface. Generating a
    meaningful scoreboard requires repurposing the corpus/baselines for the host,
    which is finish-up work (see ``fusion_manifest.FINISH_UP_STEPS``)."""
    from espalier.cli import _remedy_py  # lazy: fuse imports cli
    py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
    # install-ci — writes .github/workflows/harness-guard.yml (NOT in the manifest
    # nor the init set) so the fused repo's PR gate exists, and re-seeds integrity
    # to cover it. In-process (matches the cmd_init call above).
    try:
        from espalier.cli import cmd_install_ci
        report["install_ci_rc"] = cmd_install_ci(
            argparse.Namespace(repo=str(out)), report=report)
    except OSError as e:
        report["install_ci_rc"] = 1
        report["ci_gate_active"] = False
        print(f"[fuse] WARN: install-ci failed ({os_error_text(e)}); the fused repo's CI merge-gate "
              f"is not installed. Run `{py} -m espalier install-ci .` inside it.", file=sys.stderr)
    else:
        # cmd_install_ci handles AssetNotFound / missing-source
        # INTERNALLY (prints + `return 1`, never raises), so the `except OSError`
        # above cannot see that mode. Without this branch a non-zero rc is
        # SILENT: cmd_fuse merely omits the "CI gate installed" line and still
        # prints "the harness is live" + exit 0 — a fusion with no PR merge-gate
        # under a success banner. Surface it. (try/except/else, not a second
        # post-check, so the raised-fault path above never double-warns.)
        if report["install_ci_rc"] not in (0, None):
            print(f"[fuse] WARN: install-ci returned {report['install_ci_rc']}; the "
                  f"fused repo's CI merge-gate is not installed. Run "
                  f"`{py} -m espalier install-ci .` inside it.", file=sys.stderr)
        elif report.get("ci_gate_active") is False:
            # install-ci returned 0 but PARKED espalier's gate in
            # harness-guard.yml.new (the host shipped a differing workflow). rc==0
            # alone would let cmd_fuse print "CI gate installed (PR merge-gate)" —
            # a false claim, since the host's gate-less workflow stays active.
            print("[fuse] WARN: espalier's CI merge-gate was parked in "
                  ".github/workflows/harness-guard.yml.new because the host already "
                  "ships a differing harness-guard.yml -- the espalier PR merge-gate "
                  "is NOT active. Review and merge the .new file to arm it.",
                  file=sys.stderr)

    # analyze (fingerprint) — re-fingerprint AFTER the engine overlay so the census
    # is complete and stop_gate Gate 1 + the generated commands point at the HOST's
    # tests, not espalier's. Best-effort subprocess (captured; ~1s).
    report["fingerprint_rc"] = _run_in_fusion(
        out, [sys.executable, "-m", "espalier", "fingerprint", str(out)])
    if report["fingerprint_rc"] not in (0, None):
        print(f"[fuse] WARN: fingerprint returned {report['fingerprint_rc']}; the "
              f"fusion's test-targeting may be incomplete.", file=sys.stderr)


def cmd_fuse(args: argparse.Namespace) -> int:
    from espalier import surface_contract  # lazy, as every espalier import in this file is

    host = Path(args.host)
    out = Path(args.out)
    # The host's `.claude` is read before anything is copied; a host whose
    # `.claude` cannot be searched or listed gets the one sentence here, not
    # the bare errno line `fuse_repos`'s rollback would otherwise forward
    # (DEF-763). `init` and `upgrade` ask the same question at their own
    # pre-flight; every other command asks in `cli._resolve_repo_arg`.
    unreadable = surface_contract.unreadable_harness_root(host)
    if unreadable is not None:
        print(
            f"[fuse] FAIL: {surface_contract.unreadable_root_sentence(unreadable)}",
            file=sys.stderr,
        )
        return 1
    try:
        report = fuse_repos(
            host, out,
            preserve_history=not getattr(args, "fresh", False),
            dry_run=getattr(args, "dry_run", False),
            run_init=not getattr(args, "no_init", False),
            wire_hooks=getattr(args, "wire_hooks", False),
        )
    except (ValueError, RuntimeError, OSError) as e:
        # OSError covers FileNotFoundError / FileExistsError (bad inputs) AND a
        # mid-write I/O fault — fuse_repos has already rolled back
        # the half-built `out`, so the operator gets a clean message + retryable
        # state instead of a traceback over a poisoned directory.
        print(f"[fuse] FAIL: {os_error_text(e)}", file=sys.stderr)
        return 1

    tag = "DRY-RUN " if report["dry_run"] else ""
    print(f"[fuse] {tag}fusion {'planned' if report['dry_run'] else 'built'} at {report['out']}")
    if report["dry_run"]:
        print(f"       host files:    {report['host_files']}")
        print(f"       harness files: ~{report['harness_overlaid']} (overlay; init also deploys the managed surface)")
    else:
        hist = "history preserved" if report["history_preserved"] else "fresh git init"
        print(f"       host files:    {report['host_files']} ({hist})")
        # Categories DERIVED from what the copy loop actually wrote — see
        # _overlay_categories. The old hardcoded "(engine, bench, docs,
        # workflows)" named four no matter what contributed.
        cats = ", ".join(report.get("overlay_categories") or []) or "nothing"
        print(f"       harness:       {report['harness_via_init']} via init (managed/marked)"
              f" + {report['harness_overlaid']} overlaid ({cats})")
    if report["dry_run"]:
        return 0

    init_ran = report["init_rc"] is not None
    # A failed init = no settings.json = unwired governance. Do NOT
    # report "live." Gate the banner + exit 0 on init actually wiring the managed
    # surface; otherwise FAIL so the operator knows the fusion isn't governed.
    if init_ran and (report["init_rc"] != 0 or report["harness_via_init"] == 0):
        print(f"[fuse] FAIL: init did not wire the governance surface "
              f"(init_rc={report['init_rc']}, harness_via_init={report['harness_via_init']}). "
              f"The fusion at {report['out']} is NOT live -- inspect the init output above.",
              file=sys.stderr)
        return 1

    # Orchestration outcomes (present only when init succeeded).
    if init_ran:
        ci_rc = report.get("install_ci_rc")
        if ci_rc == 0 and report.get("ci_gate_active"):
            print("       CI gate:       harness-guard.yml installed (PR merge-gate)")
        elif ci_rc == 0 and report.get("ci_gate_active") is False:
            # install-ci parked espalier's gate in .new (the host ships
            # a differing harness-guard.yml). Don't claim an active merge-gate; the
            # _orchestrate_bootstrap WARN above carries the remediation.
            print("       CI gate:       PARKED in harness-guard.yml.new -- espalier "
                  "gate NOT active (host workflow kept; review + merge to arm)")
        if report.get("fingerprint_rc") == 0:
            # The fingerprint runs AFTER the engine overlay, so its
            # census covers the overlaid espalier/ too — not a clean "host-only"
            # picture. The finish-up `/analyze` re-fingerprints host-focused;
            # don't overclaim here.
            print("       analyze:       initial fingerprint written "
                  "(re-run /analyze for a host-focused census)")

    # init returns rc 0 even when it PRESERVED a host's own
    # .claude/settings.json (sovereignty) and therefore wired NO hooks. Don't let
    # this banner re-assert "live" over init's honest "NOT active" WARN — read the
    # fused settings.json and tell the truth. A read hiccup defaults to "not
    # wired" (the safe direction: never over-claim enforcement).
    hooks_wired = False
    # Whether the merge this banner is about to name would refuse the fused
    # file whole. A host's own settings.json is by construction the file the
    # harness did not write -- the population most likely to be malformed --
    # and the banner used to hand it "merge-settings" (and "--wire-hooks",
    # which runs the same merge) with no check (DEF-700 failure-mode review,
    # driven on a host file with a string event value: merge exits 1, writes
    # nothing, and the pre-push step reads as mandatory). Best-effort like the
    # read above: a failed check costs the caveat, not the fuse.
    merge_refused: str | None = None
    if init_ran:
        settings_file = Path(report["out"]) / ".claude" / "settings.json"
        # Two questions, two try blocks (DEF-732). Until 2026-09-12 one try
        # held both, parse first: on the one input the classifier exists to
        # describe -- a settings.json that does not parse -- the parse raised,
        # the shared except reset merge_refused to None, and the epilogue fell
        # to the plain merge-settings offer DEF-700 had withheld at every
        # other site (driven on the Windows host, W2-33: init's own narration
        # printed the withheld remedy and this banner the wrong offer fifty
        # lines later). The classifier runs first and on its own, so the
        # verdict survives whatever the wiring read does with the same bytes.
        try:
            from espalier.cli import merge_refusal_for_file
            merge_refused = merge_refusal_for_file(settings_file, Path(report["out"]))
        except Exception:  # noqa: BLE001 -- advisory banner; never fail fuse on a read hiccup
            merge_refused = None
        try:
            import json

            from espalier import surface_contract
            from espalier.cli import _settings_has_espalier_hooks
            if os.path.exists(settings_file):  # uniform on every interpreter (DEF-763)
                hooks_wired = _settings_has_espalier_hooks(
                    json.loads(surface_contract.decode_bom(settings_file.read_bytes()))
                )
        except Exception:  # noqa: BLE001 -- advisory banner; never fail fuse on a read hiccup
            hooks_wired = False

    from espalier.cli import (  # lazy: fuse imports cli
        _dead_reporters_line,
        _remedy_py,
        merge_refusal_step,
    )
    py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
    print()
    if init_ran and hooks_wired:
        print("Next: open the fusion in Claude Code and run the finish-up session.")
        print("The harness is live, but these still want a human/agent pass:")
        # DEF-619: "live" is a sentence about the gates; a reporter the host's
        # file left dead is named here, by the same line every other armed
        # claim carries. Best-effort like the read above.
        try:
            reporters_line = _dead_reporters_line(Path(report["out"]), py)
        except Exception:  # noqa: BLE001 -- advisory banner; never fail fuse on a read hiccup
            reporters_line = None
        if reporters_line:
            print("  - " + reporters_line)
    elif init_ran:
        print("Next: open the fusion in Claude Code and run the finish-up session.")
        print("The harness is overlaid but hooks are NOT yet wired -- the host's own")
        print(".claude/settings.json was preserved.")
        if report.get("ci_gate_active"):
            # harness-guard.yml is the active workflow, and its `verify` job
            # is NOT self-host-gated -- ci_guard reads the preserved-unwired
            # settings.json as dropping every governance gate and exits 2 on
            # the fusion's FIRST push/PR. merge-settings is NOT an optional
            # finish-up pass in this state; say so loudly rather than bury it
            # among the FINISH_UP polish (which reads as optional). Whether
            # the file is TRACKED is read from git, never assumed (DEF-807):
            # fuse commits nothing after install-ci writes it, so on both
            # paths it sits untracked until the adopter stages it, and GitHub
            # runs nothing it cannot see. The urgency holds, one `git add`
            # later, and the sentence says which state the tree is in.
            tracked = _workflow_tracked(Path(report["out"]))
            if tracked:
                print("  WARNING: harness-guard.yml is already in git and its `verify` job")
            elif tracked is False:
                print("  WARNING: harness-guard.yml is written but NOT yet committed; once you")
                print(f"  commit it (git add {_WORKFLOW_REL}), its `verify` job")
            else:
                print("  WARNING: harness-guard.yml is written and, once committed, its `verify` job")
            print("  WILL FAIL your first push/PR until the hooks are wired -- this is")
            print("  NOT optional while harness-guard.yml is present. Before you push:")
            if merge_refused:
                # The offer is WITHHELD, not reworded: merge-settings and
                # --wire-hooks both refuse this file whole.
                print(f"      {merge_refusal_step(merge_refused, py)}")
                print("      (re-fusing with --wire-hooks refuses the same file)")
            else:
                print(f"      {py} -m espalier merge-settings .   (or re-fuse with --wire-hooks)")
            print("  These also still want a pass:")
        elif merge_refused:
            print(f"Before enforcement can be armed: {merge_refusal_step(merge_refused, py)}.")
            print("These also still want a pass:")
        else:
            print(f"Run `{py} -m espalier merge-settings .` inside the fusion to arm")
            print("enforcement. These also still want a pass:")
    else:
        print("Overlay complete -- governance is NOT wired (--no-init).")
        print(f"Run `{py} -m espalier init .` inside the fusion to deploy settings.json + hooks, then:")
    for step in fusion_manifest.FINISH_UP_STEPS:
        print(f"  - {step}")
    print()
    # Some finish-up steps edit write_guard-PROTECTED paths (harness-guard.yml,
    # tools/cc/ci_guard.py); a plain `claude` session denies those edits. Surface
    # the maintenance-mode launch so the operator is not blocked mid-checklist.
    from espalier.cli import _maintenance_mode_invocation
    print("Some finish-up steps above edit protected paths (harness-guard.yml,")
    print("tools/cc/ci_guard.py) that a plain session denies. For those, exit and")
    print("relaunch Claude Code from your own terminal, in the FUSION, with:")
    # The same load-bearing `cd` as the start-here block below (DEF-382a leg
    # b): this relaunch was printed without it, so an operator who pasted it
    # started a maintenance-mode session in the UNGOVERNED ORIGINAL.
    print(f'    cd "{report["out"]}"')
    print(_maintenance_mode_invocation("claude"))
    print()
    # The start-here BLOCK is fuse's true last output. init's own epilogue was
    # suppressed above (suppress_epilogue=True) so this is the only one. The `cd`
    # is load-bearing: fuse's output tree is never cwd, so "start Claude Code"
    # without it lands the operator in the UNGOVERNED ORIGINAL with no in-session
    # signal -- observed on the 2026-08-18 Windows walk. Double quotes because
    # every path on that walk had spaces, `"` is not a legal NTFS filename
    # character, and the quoting is correct in both PowerShell and POSIX shells.
    # (A literal `$` in the path would still interpolate in both -- a stated
    # limit, not an oversight.) Pinned by tests/test_fuse.py so the anchor cannot
    # silently regress the way the un-anchored line did for the life of the verb.
    print("Start Claude Code in the FUSION (not the original):")
    print(f'    cd "{report["out"]}"')
    print("    claude")
    return 0
