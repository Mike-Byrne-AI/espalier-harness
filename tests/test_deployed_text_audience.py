"""What ``init`` deploys is addressed to the adopter, not to the maintainer.

This pins the audience of every deployed text because the bodies, docs and
headers ``init`` deploys are copies of this repository's own tree, so
maintainer procedure reached every adopter: ledger ids they cannot look up,
``scripts/`` and ``tests/`` paths they never receive, a named co-author trailer,
the dated timings of this repository's suite. The older hygiene gates read
narrower token sets (``tests/test_init_tier_split.py::TestCommonTierAssetHygiene``:
TP/BC ids and six phrases; ``tests/test_deployed_assets_home_path_shapes.py``:
home prefixes and five artefact shapes), and a planted ledger id, self-host
path, trailer and approval marker passed every one of them (TP-473 0-A).

The vocabulary is ``espalier.surface_hygiene.MAINTAINER_MARKER_PATTERNS`` plus
the self-host path family, calibrated hit by hand on a fresh ``init`` and
``install-ci`` of a Node tree (117 files, 868 marker hits under the authoring
scanner); the per-family false-positive counts and the family rejected on
measurement are recorded beside the patterns.

What is read, and the target each part holds:

- every packaged ``.claude`` body of the four kinds, rendered as ``init`` renders
  it for an adopter (its self-host blocks stripped): zero hits outside
  :data:`ALLOWLIST`, and a self-host fence grammar the strip can read;
- every text ``init`` renders once and keeps -- ``cc/LIVE_SURFACE.md``,
  ``cc/PACK_MANIFEST.txt``, the root ``CLAUDE.md`` (canonical and for a tree),
  ``ESPALIER_MEMORY.md``, the ``espalier.toml`` skeleton: zero;
- the string constants of every vendored ``tools/cc`` module that are not a bare
  string statement (a docstring, or the docstring of a constant): zero for the
  text families. The path family is not read there: all 78 such hits measured
  were path DATA -- mirror maps, scope lists, a fallback test list -- or rows a
  self-host scope keeps off an adopter's tree (``tests/test_reinject_sync.py``);
  an emitted path is the pointer gate's to judge
  (``tests/test_adopter_pointer_resolution.py``);
- the install-ci workflow: zero outside :data:`ALLOWLIST`;
- the seeded docs: at most :data:`SEED_BASELINE`.

A red names the source line to edit and the sync that regenerates the mirror,
read off ``espalier.mirror_registry``: every path this scan can name is one the
mirror rules forbid hand-editing.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from espalier import surface_hygiene, surface_impact
from espalier.cli import (
    _asset_transform,
    _build_claude_md,
    _canonical_template_build_plan,
    _canonical_template_fingerprint,
    _packaged_md_assets,
    render_canonical_template,
)
from espalier.managed_inventory import get_managed_public_prefixes
from espalier.mirror_registry import MIRROR_ROWS, glob_row_parts
from espalier.render_surface import render_live_surface, render_pack_manifest
from tests._live_tree import checkout_rglob

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_CC = "espalier/_vendor/cc"
WORKFLOW_ASSETS = "espalier/assets/github"
#: The seeded roots are ``surface_hygiene.SEED_ROOTS``: held to :data:`SEED_BASELINE`,
#: not to zero (``DEC-30`` decides which seeds ship at all; until then the floor keeps
#: the rest honest). One home: ``scripts/sync_asset_docs.py`` reads the same roots and
#: ceiling after every copy, so a fold is judged where it is written, and the landing
#: check selects this module's gate class before the push.
#: Each root exists and holds a floor of text files of its own (a missing root
#: makes a walk silent; a global floor would let one root carry a dead one).
FLOORS: dict[str, int] = {
    "espalier/assets/claude": 30,
    VENDOR_CC: 40,
    WORKFLOW_ASSETS: 0,  # one file today: the floor is "not empty"
    "espalier/assets/docs": 10,
    "espalier/assets/memory": 0,  # one file today: the floor is "not empty"
    "espalier/assets/seed": 4,
    "espalier/assets/task-packs": 0,  # one file today: the floor is "not empty"
}
TEXT_SUFFIXES = surface_hygiene.SEED_TEXT_SUFFIXES
#: The seeded docs' hit count on the date it was taken: a ceiling, not an exact
#: pin (why it is a ceiling, and how it is lowered, beside the value in
#: ``espalier.surface_hygiene``).
SEED_BASELINE: tuple[str, int] = surface_hygiene.SEED_BASELINE
#: A deployed file allowed to keep maintainer-addressed text: the number of hits
#: it holds today and a one-sentence judgment of why the text stays. The count
#: is exact, so a new hit in the file reds and a removed one asks for the count
#: to fall; a reason that quotes the body's own disclaimer is not a judgment.
ALLOWLIST: dict[str, tuple[int, str]] = {
    "espalier/assets/github/workflows/harness-guard.yml": (
        6,
        "one workflow is both this repository's CI and the adopter's: its self-host "
        "jobs run only where the harness's own files exist, and the packaged copy is "
        "the source of truth, so the jobs and the comments that maintain them cannot "
        "be stripped at deploy without forking the gate",
    ),
}
OPEN, CLOSE = surface_hygiene.SELF_HOST_BLOCK_OPEN, surface_hygiene.SELF_HOST_BLOCK_CLOSE


def _source_of(rel: str) -> str:
    """``rel`` (a mirror path) as ``source -- then <sync>``, derived from the
    mirror registry; a file no source-tree row mirrors is its own source."""
    for row in MIRROR_ROWS:
        if row.direction != "sot-is-source-tree":
            continue
        glob = glob_row_parts(row.sot)
        source_base = glob[0] if glob is not None else row.sot
        for mirror in row.mirrors:
            if mirror.endswith("/") and rel.startswith(mirror):
                return f"{source_base}{rel[len(mirror):]} -- then {row.sync}"
            if rel == mirror:
                return f"{row.sot} -- then {row.sync}"
    return f"{rel} (no mirror row: it is its own source)"


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _deployed_prefixes() -> tuple[str, ...]:
    return get_managed_public_prefixes()


def _hits(text: str, *, skip: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    return surface_hygiene.maintainer_marker_hits(
        text, deployed_prefixes=_deployed_prefixes(), skip=skip,
    )


def _line_hits(lines, rel: str, *, skip: tuple[str, ...] = ()) -> list[str]:
    out = []
    for n, line in lines:
        for family, match in _hits(line, skip=skip):
            out.append(f"{rel}:{n}: [{family}] {match} -- {line.strip()[:100]}")
    return out


def _adopter_body(rel: str, src: Path, adopter_root: Path) -> str:
    """The packaged body as ``init`` writes it on an adopter's tree."""
    body = src.read_text(encoding="utf-8")
    transform = _asset_transform(rel, [], adopter_root)
    return transform(body) if transform is not None else body


def _adopter_lines(rel: str, src: Path, adopter_root: Path) -> list[tuple[int, str]]:
    """The adopter's body as ``(source line, text)``: the strip removes whole
    lines, so each kept line keeps the number the source gives it, and a red
    sends the reader to the line they will edit, not to the rendered copy's."""
    raw = src.read_text(encoding="utf-8")
    lines = _adopter_body(rel, src, adopter_root).splitlines()
    removed: set[int] = set()
    for m in surface_hygiene.SELF_HOST_BLOCK_RE.finditer(raw):
        first = raw.count("\n", 0, m.start()) + 1
        last = raw.count("\n", 0, max(m.start(), m.end() - 1)) + 1
        removed.update(range(first, last + 1))
    kept = [n for n in range(1, len(raw.splitlines()) + 1) if n not in removed]
    return list(zip(kept, lines)) if len(kept) == len(lines) else list(enumerate(lines, 1))


def _claude_body_hits(adopter_root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rel, src in _packaged_md_assets(REPO_ROOT):
        hits = _line_hits(_adopter_lines(rel, src, adopter_root), _rel(src))
        if hits:
            out[_rel(src)] = hits
    return out


def _emitted_strings(source: str) -> list[tuple[int, str]]:
    """Every string constant in ``source`` that is not a bare string statement,
    as ``(line, text)`` per line of the constant. A bare string statement -- a
    docstring, or the docstring of a constant -- is never emitted."""
    tree = ast.parse(source)
    bare = {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in bare:
            for offset, line in enumerate(node.value.splitlines()):
                out.append((node.lineno + offset, line))
    return out


def _vendored_python() -> list[Path]:
    return sorted(
        p for p in checkout_rglob(REPO_ROOT / VENDOR_CC, "*.py") if "__pycache__" not in p.parts
    )


def _python_hits() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in _vendored_python():
        lines = _emitted_strings(path.read_text(encoding="utf-8"))
        hits = _line_hits(lines, _rel(path), skip=(surface_hygiene.SELF_HOST_PATH_FAMILY,))
        if hits:
            out[_rel(path)] = hits
    return out


def _text_files(root: str) -> list[Path]:
    return sorted(
        p for p in checkout_rglob(REPO_ROOT / root, "*")
        if p.is_file() and p.suffix in TEXT_SUFFIXES and "__pycache__" not in p.parts
    )


def _workflow_hits() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in _text_files(WORKFLOW_ASSETS):
        hits = _line_hits(enumerate(path.read_text(encoding="utf-8").splitlines(), 1), _rel(path))
        if hits:
            out[_rel(path)] = hits
    return out


def _seed_hits_by_file() -> dict[str, int]:
    """The sync script's read, over git's view of the checkout."""
    by_file = surface_hygiene.seeded_marker_hits(
        REPO_ROOT, deployed_prefixes=_deployed_prefixes(),
        walk=lambda base: checkout_rglob(base, "*"),
    )
    return {rel: len(hits) for rel, hits in by_file.items()}


def _report(found: dict[str, list[str]]) -> str:
    lines = []
    for rel, hits in sorted(found.items()):
        lines.append(f"{rel}  (fix at {_source_of(rel)})")
        lines.extend(f"    {h}" for h in hits)
    return "\n  ".join(lines)


def _unallowlisted(found: dict[str, list[str]]) -> dict[str, list[str]]:
    return {rel: hits for rel, hits in found.items() if rel not in ALLOWLIST}


def _fence_problems(text: str) -> list[str]:
    """Where ``text`` breaks the self-host fence grammar the strip relies on:
    each marker alone on its line (a ``//``, ``#`` or ``>`` comment prefix
    allowed), openers and closers alternating and never nested, every block
    closed, and both ends at the same code-fence depth."""
    out: list[str] = []
    open_at: int | None = None
    open_in_code = False
    fence: str | None = None  # the run that opened the current code block
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        run = re.match(r"(`{3,}|~{3,})", stripped)
        if run and (fence is None or (run.group(1)[0] == fence[0] and len(run.group(1)) >= len(fence)
                                      and stripped == run.group(1))):
            fence = run.group(1) if fence is None else None
        has_open, has_close = OPEN in line, CLOSE in line
        if not (has_open or has_close):
            continue
        rest = line.replace(OPEN, "").replace(CLOSE, "").strip()
        if rest not in ("", "//", "#", ">"):
            out.append(f"{n}: a marker shares its line with text")
        if has_open and has_close:
            out.append(f"{n}: an opener and a closer on one line")
            continue
        if has_open:
            if open_at is not None:
                out.append(f"{n}: an opener inside the block opened at line {open_at}")
            open_at, open_in_code = n, fence is not None
        else:
            if open_at is None:
                out.append(f"{n}: a closer with no opener")
            elif open_in_code != (fence is not None):
                out.append(f"{n}: the block opened at line {open_at} closes at another code-fence depth")
            open_at = None
    if open_at is not None:
        out.append(f"{open_at}: an opener never closed")
    return out


_STEP_HEAD_RE = re.compile(r"(?m)^(?:## (\d+[a-z]?)\. |(\d+[a-z]?)\. \*\*)")
_STEP_REF_RE = re.compile(r"\b[Ss]teps? (\d+[a-z]?)\b")


def _step_heads(text: str) -> set[str]:
    return {a or b for a, b in _STEP_HEAD_RE.findall(text)}


_ADVICE = (
    "\n  Say it to the adopter instead: a placeholder for an id (`DEF-NNN`), the "
    "adopter's own runner for a self-host script, no named trailer, no dated timing "
    "of this repository's suite. A proof line that must stay a self-host example carries "
    f"{surface_hygiene.SELF_HOST_EXAMPLE_LABEL!r} on it; whole self-host steps sit "
    f"between {OPEN} and {CLOSE}, each alone on its line. Edit the SOURCE named above, "
    "never the mirror."
)


class TestDeployedTextIsAddressedToTheAdopter:
    def test_no_deployed_claude_body_is_addressed_to_the_maintainer(self, tmp_path):
        found = _unallowlisted(_claude_body_hits(tmp_path))
        assert not found, "maintainer-addressed text in a deployed .claude body:\n  " + _report(found) + _ADVICE

    def test_the_texts_init_renders_once_are_addressed_to_the_adopter(self, tmp_path):
        """These are written once and kept (``upgrade`` never rewrites the root
        CLAUDE.md), so a leak here is permanent on every new tree."""
        fp, plan = _canonical_template_fingerprint(), _canonical_template_build_plan()
        rendered = {
            "cc/LIVE_SURFACE.md": render_live_surface(tmp_path),
            "cc/PACK_MANIFEST.txt": render_pack_manifest(tmp_path),
            "CLAUDE.md (canonical)": render_canonical_template("claude"),
            "CLAUDE.md (for a tree)": _build_claude_md(fp, plan, root=tmp_path),
            "ESPALIER_MEMORY.md": render_canonical_template("memory"),
            "espalier.toml": render_canonical_template("toml"),
        }
        found = [h for name, text in rendered.items()
                 for h in _line_hits(enumerate(text.splitlines(), 1), name)]
        assert not found, (
            "maintainer-addressed text in a file init renders (espalier/cli.py, "
            "espalier/render_surface.py):\n  " + "\n  ".join(found)
        )

    def test_no_vendored_python_string_is_addressed_to_the_maintainer(self):
        found = _unallowlisted(_python_hits())
        assert not found, "maintainer-addressed text in a deployed tools/cc string:\n  " + _report(found) + _ADVICE

    def test_the_install_ci_workflow_keeps_only_its_allowlisted_hits(self):
        found = _unallowlisted(_workflow_hits())
        assert not found, "maintainer-addressed text in the deployed workflow:\n  " + _report(found) + _ADVICE

    def test_the_seeded_docs_stay_under_their_ceiling(self):
        date, baseline = SEED_BASELINE
        by_file = _seed_hits_by_file()
        count = sum(by_file.values())
        assert count <= baseline, (
            f"the seeded docs carry {count} maintainer-addressed hits, over the ceiling of "
            f"{baseline} taken {date}. Per file, highest first (compare your diff's files):\n  "
            + "\n  ".join(f"{n:4d}  {rel}  (fix at {_source_of(rel)})"
                          for rel, n in sorted(by_file.items(), key=lambda kv: -kv[1]))
            + "\n  Reword the new text in the source under docs/; never raise the ceiling."
        )


class TestTheSelfHostFenceGrammar:
    """The strip removes a block from its opener's line to its closer's. A
    malformed fence deletes adopter text silently -- the deleted text carries no
    marker, so nothing downstream sees it -- so the grammar is held here, at the
    source, before a body ships (review)."""

    def test_every_packaged_body_keeps_the_grammar(self):
        problems = [f"{_rel(src)}:{p}" for _rel_, src in _packaged_md_assets(REPO_ROOT)
                    for p in _fence_problems(src.read_text(encoding="utf-8"))]
        assert not problems, "self-host fence grammar broken:\n  " + "\n  ".join(problems)

    def test_no_marker_survives_on_an_adopters_copy(self, tmp_path):
        left = [_rel(src) for rel, src in _packaged_md_assets(REPO_ROOT)
                if OPEN in (body := _adopter_body(rel, src, tmp_path)) or CLOSE in body]
        assert not left, f"a self-host marker reaches an adopter: {left}"

    def test_the_grammar_check_sees_each_way_a_fence_breaks(self):
        good = f"a\n{OPEN}\nself\n{CLOSE}\nb\n```bash\n# {OPEN}\nx\n# {CLOSE}\n```\n"
        assert _fence_problems(good) == []
        for broken, why in (
            (f"a\n{OPEN}\nb\n", "never closed"),
            (f"a\n{CLOSE}\n", "no opener"),
            (f"{OPEN}\n{OPEN}\nx\n{CLOSE}\n", "inside the block"),
            (f"1. Run your tests. {OPEN}\nx\n{CLOSE}\n", "shares its line"),
            (f"fence with `{OPEN}` around it\n", "shares its line"),
            (f"{OPEN}\n```bash\nx\n{CLOSE}\n```\n", "another code-fence depth"),
        ):
            assert any(why in p for p in _fence_problems(broken)), (broken, _fence_problems(broken))

    def test_no_stripped_step_is_still_referenced(self, tmp_path):
        """A step fenced out of a command leaves its mentions behind: the adopter
        is told a step will catch something their copy no longer has (review:
        /handoff pointed at 7b and 7c from three places)."""
        dangling = []
        for rel, src in _packaged_md_assets(REPO_ROOT):
            if not rel.startswith(".claude/commands/"):
                continue
            raw, body = src.read_text(encoding="utf-8"), _adopter_body(rel, src, tmp_path)
            gone = _step_heads(raw) - _step_heads(body)
            dangling += [f"{_rel(src)}: {m.group(0)!r}" for m in _STEP_REF_RE.finditer(body)
                         if m.group(1) in gone]
        assert not dangling, "an adopter's command names a step its copy no longer has:\n  " + "\n  ".join(dangling)


class TestTheAllowlistIsAJudgmentThatStillHolds:
    def test_every_entry_names_a_deployed_file_holding_exactly_its_count(self, tmp_path):
        current = {**_claude_body_hits(tmp_path), **_python_hits(), **_workflow_hits()}
        for rel, (count, reason) in ALLOWLIST.items():
            assert (REPO_ROOT / rel).is_file(), f"{rel}: allowlisted, but no such deployed file"
            held = len(current.get(rel, []))
            assert held == count, (
                f"{rel}: allowlisted for {count} hits, holds {held}. "
                + (f"Its reason: {reason}. If the new hit is what that reason covers, raise the "
                   "count and name the change in the PR; otherwise reword it."
                   if held > count else "Lower the count, or drop the entry at zero.")
            )

    def test_every_reason_is_a_sentence_of_judgment(self):
        for rel, (_count, reason) in ALLOWLIST.items():
            assert len(reason.split()) >= 8, f"{rel}: a reason is a sentence of judgment, not a tag"
            lowered = reason.lower()
            for disclaimer in ("self-host only", "not deployed", "espalier source repo"):
                assert disclaimer not in lowered, (
                    f"{rel}: the reason quotes a disclaimer ({disclaimer!r}); say why the text stays"
                )


class TestTheVocabulary:
    def test_the_path_family_is_derived_from_the_deploy_inventory(self):
        deployed = _deployed_prefixes()
        for root in surface_hygiene.SELF_HOST_PATH_ROOTS:
            assert (REPO_ROOT / root).is_dir(), f"{root}/ is no directory of this repository"
            assert root in surface_hygiene.self_host_path_roots(deployed), (
                f"{root}/ is covered by a deployed prefix; a path there may be the adopter's"
            )
        # The derivation is live: a root that starts shipping drops out by itself.
        widened = (*deployed, "scripts/")
        assert "scripts" not in surface_hygiene.self_host_path_roots(widened)
        assert not surface_hygiene.maintainer_marker_hits(
            "run scripts/planted.py", deployed_prefixes=widened,
        )
        assert surface_hygiene.maintainer_marker_hits(
            "run scripts/planted.py", deployed_prefixes=deployed,
        ) == [("self-host-path", "scripts/planted.py")]

    def test_each_family_sees_its_shape_and_not_the_placeholders(self):
        deployed = _deployed_prefixes()
        seen = {
            "see DEF-1075": "ledger-id", "DEF-371a": "ledger-id", "LG-6": "ledger-id",
            "DEC-30": "ledger-id", "INV-8": "ledger-id", "EI-34": "ledger-id",
            "python scripts/proof_tier.py": "self-host-path",
            "tests/test_hooks.py::TestX": "self-host-path",
            "bench/run_benchmark.py": "self-host-path", "espalier/cli.py::f": "self-host-path",
            "mv x task-packs/Done/": "retired-pack-folder",
            "Co-Authored-By: Claude, Scion <x>": "co-author-trailer",
            "(measured 2026-09-06: two runs)": "dated-measurement",
            "measured on 2026-09-06": "dated-measurement",
            "Measured 2026-09-06: three runs": "dated-measurement",
            "(measured twice, 2026-09-06)": "dated-measurement",
            "the leg measured 2,711 s on 2026-09-23": "dated-measurement",
        }
        for sample, family in seen.items():
            hits = surface_hygiene.maintainer_marker_hits(sample, deployed_prefixes=deployed)
            assert [f for f, _ in hits] == [family], (sample, hits)
        for inert in ("DEF-NNN", "`DEF-<n>`", "TP-473", "tests/test_{module}.py",
                      "tests/test_<module>.py", "tools/cc/ledger_row.py", "src/scripts/x.py",
                      "./scripts/x.sh", "task-packs/done/", "Co-Authored-By: Your Name",
                      "measured on your tree", "2026-09-06", "measured twice"):
            assert not surface_hygiene.maintainer_marker_hits(inert, deployed_prefixes=deployed), inert

    def test_a_labelled_example_line_carries_no_path_hit_but_keeps_its_id(self):
        label = surface_hygiene.SELF_HOST_EXAMPLE_LABEL
        deployed = _deployed_prefixes()
        assert not surface_hygiene.maintainer_marker_hits(
            f"pytest tests/test_x.py -q   {label} the targeted file", deployed_prefixes=deployed,
        )
        assert surface_hygiene.maintainer_marker_hits(
            f"pytest tests/test_x.py -q   {label} DEF-717's lane", deployed_prefixes=deployed,
        ) == [("ledger-id", "DEF-717")]
        # Unlabelled, the same proof line is a hit: the label is the whole exemption.
        assert surface_hygiene.maintainer_marker_hits(
            "pytest tests/test_x.py -q", deployed_prefixes=deployed,
        ) == [("self-host-path", "tests/test_x.py")]

    def test_a_bare_string_statement_is_not_an_emitted_string(self):
        source = (
            '"""Module docstring DEF-1."""\n'
            'X = "kept"\n'
            '"""The constant\'s docstring, DEF-2."""\n'
            'def f():\n'
            '    """DEF-3"""\n'
            '    return "emitted DEF-4"\n'
        )
        texts = [t for _, t in _emitted_strings(source)]
        assert texts == ["kept", "emitted DEF-4"]


class TestThePreflightReadsTheSameVocabulary:
    def test_surface_impact_reports_a_marker_in_a_declared_body(self, tmp_path, monkeypatch):
        body = tmp_path / ".claude" / "commands" / "x.md"
        body.parent.mkdir(parents=True)
        body.write_bytes(
            f"Run scripts/proof_tier.py; see DEF-123.\n{OPEN}\nDEF-456 stays here\n{CLOSE}\n".encode())
        docs = tmp_path / "docs" / "x.md"
        docs.parent.mkdir(parents=True)
        docs.write_bytes(b"see DEF-123\n")
        # The scan stands down off the self-host tree; this tmp tree stands in for it.
        monkeypatch.setattr(surface_impact, "off_self_host", lambda _root: False)
        report = surface_impact.SurfaceImpactReport(pack_id="TP-0")
        surface_impact._scan_existing(tmp_path, ".claude/commands/x.md", report)
        surface_impact._scan_existing(tmp_path, "docs/x.md", report)
        markers = [h for h in report.content_hits if h.kind == "maintainer-marker"]
        # The fenced id is stripped at deploy, so the pre-flight does not report it.
        assert [(h.path, h.hits) for h in markers] == [(
            ".claude/commands/x.md", ["ledger-id: DEF-123", "self-host-path: scripts/proof_tier.py"],
        )], report.content_hits


class TestThePopulation:
    def test_each_root_holds_its_floor(self):
        for root, floor in FLOORS.items():
            directory = REPO_ROOT / root
            assert directory.is_dir(), root
            files = list(checkout_rglob(directory, "*.py")) if root == VENDOR_CC else _text_files(root)
            assert len(files) > floor, (root, len(files), floor)

    def test_every_seeded_root_holds_a_floor(self):
        """A root added to ``surface_hygiene.SEED_ROOTS`` is walked by the ceiling
        and by the sync; this names the floor it must hold here too."""
        missing = set(surface_hygiene.SEED_ROOTS) - set(FLOORS)
        assert not missing, missing

    def test_the_claude_population_is_the_deploy_set(self):
        rels = [rel for rel, _ in _packaged_md_assets(REPO_ROOT)]
        kinds = {rel.split("/")[1] for rel in rels}
        assert kinds == {"agents", "commands", "skills", "workflows"}, kinds
        assert len(rels) > FLOORS["espalier/assets/claude"]

    def test_the_red_names_the_source_and_its_sync(self):
        assert _source_of("espalier/_vendor/cc/hooks/session_start.py") == (
            "tools/cc/hooks/session_start.py -- then python3 scripts/sync_vendor_cc.py")
        assert _source_of("espalier/assets/claude/commands/handoff.md") == (
            ".claude/commands/handoff.md -- then python3 scripts/sync_claude_mirrors.py")
        assert _source_of("espalier/assets/docs/HOOKS.md") == (
            "docs/HOOKS.md -- then python3 scripts/sync_asset_docs.py")
        assert _source_of("espalier/assets/seed/SHARP_EDGES.md").endswith("its own source)")

    def test_a_red_names_the_source_line_not_the_rendered_one(self, tmp_path):
        src = tmp_path / "x.md"
        src.write_bytes(f"a\n{OPEN}\nself\n{CLOSE}\nsee DEF-9\n".encode())
        assert _adopter_lines(".claude/commands/x.md", src, tmp_path) == [(1, "a"), (5, "see DEF-9")]
