"""RELEASE_CHECKLIST procedure-contract guards.

Three invariants pinned forward:
1. Every release-creation invocation in the live-ritual section is
   preceded, IN THE SAME `##` SECTION AND IN A FENCED COMMAND, by a
   push that puts the tag on origin. Forgetting this step produces
   broken compare-URL rendering in GitHub release notes
   (TP-85 finding).

   Both qualifiers were added 2026-09-02 after the check was measured
   vacuous in two independent ways, and each was found by trying to
   break it rather than by reading it:
     - UNSCOPED: any qualifying push anywhere earlier in the document
       satisfied every later site. The dry-run section at ~:203 alone
       kept every subsequent site green forever.
     - UNFENCED: prose satisfied it. The first-publish section's site
       was held up for months by the sentence "so a stray
       `git push --tags` ... can never leak them" -- a warning telling
       the operator NOT to do it.
   Mutation-proved: deleting the real fenced push reds; re-adding the
   flag as prose does NOT clear the red.
2. The Recovery subsection exists for operators who run
   `gh release create` before pushing tags.
3. The Hotfix cadence section exists with a multi-tag push command
   (the v0.7.1.1 flow).
"""

from __future__ import annotations

import re
from pathlib import Path


CHECKLIST = Path(__file__).parent.parent / "docs" / "RELEASE_CHECKLIST.md"


# What actually satisfies invariant 1 is "the tag is on origin before the
# release-creation command runs" -- not one particular flag. `--tags` and
# `--follow-tags` are two ways to get there; an explicit single-tag
# `git push origin vX.Y.Z` is a third, and it is the one the first-publish
# sequence deliberately prescribes (a bulk tag push suppresses the `push`
# event that `publish.yml` triggers on, so `--tags` is the WRONG form there).
# The narrow original regex would have red-flagged the correct procedure.
# The optional quote matters: the first-publish step derives the version into
# $VER and pushes `git push origin "v$VER"`. Without it this check reds on a
# correctly-parameterised command -- measured 2026-09-02 when deriving the
# version (to stop a literal vX.Y.Z tag reaching the public repo) reddened it.
# `--dry-run` is excluded because it pushes nothing: accepting it would be the
# same shape as the two vacuities above -- the check crediting something that
# provably does not put a tag on origin. The Release-procedure section carries
# a real push too, so this is a tightening with no live site depending on it.
_PUSH_TAGS_RE = re.compile(
    r"git\s+push\s+(?!.*--dry-run)"
    r"(?:.*--(?:tags|follow-tags)|origin\s+[\"']?v\S+)"
)
_GH_RELEASE_RE = re.compile(r"gh\s+release\s+create")
# Round-2 revision: drop the `--follow-tags` branch -- it's
# single-tag-capable. `--follow-tags` pushes annotated tags reachable
# from the branch (could be 1, could be N); `--tags` pushes ALL local
# tags; explicit multi-arg `origin vA vB` names >=2 tags. Only the
# latter two are strictly multi-tag-capable.
_MULTI_TAG_PUSH_RE = re.compile(
    r"git\s+push\s+(?:--tags\b|origin\s+v\S+\s+v\S+)"
)


def _sections(text: str) -> list[tuple[str, str]]:
    """Split into `##` blocks as (heading, body) pairs.

    Invariant 1 is a claim about ONE procedure: the tag reaches origin
    before that same procedure creates its release. A whole-document
    "is there any earlier push" search cannot express that -- it lets an
    unrelated section three hundred lines up vouch for a procedure that
    never pushes anything.

    Split BEFORE `_fenced_commands_only`: headings live outside fences,
    so stripping first erases the very boundaries this needs.
    """
    out: list[tuple[str, str]] = []
    heading = "(preamble)"
    cur: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("## ") and cur:
            out.append((heading, "".join(cur)))
            heading, cur = line.strip(), [line]
        else:
            if line.startswith("## "):
                heading = line.strip()
            cur.append(line)
    if cur:
        out.append((heading, "".join(cur)))
    return out


def _fenced_commands_only(text: str) -> str:
    """Blank out everything outside ``` fences, preserving offsets.

    Invariant 1 is about what the operator is *instructed to run*, and an
    instruction lives in a fenced block. Prose is not.

    MEASURED 2026-09-02, and the reason this helper exists: the first-publish
    section's release-creation step was satisfied for months by the sentence
    *"so a stray `git push --tags` -- which pushes everything regardless of
    annotation status -- can never leak them"*, i.e. by a warning telling the
    operator NOT to push tags that way. Rewording that prose during the DEC-25
    rewrite reddened this test while the procedure was getting *more* correct --
    which is how the vacuity surfaced. A gate that a prohibition can satisfy is
    not reading commands.

    Offsets are preserved (each non-fence line becomes a bare newline) so
    failure messages still point into the real file.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("\n")
            continue
        out.append(line if in_fence else "\n")
    return "".join(out)


#: Release-creation sites the live document carries, measured 2026-09-02. A
#: FLOOR, not a ceiling: both ordering checks pass trivially when they see
#: nothing, so "how many did you look at?" is the only question that separates
#: "correct" from "blind". Lower it only with a measurement in the diff.
_MIN_RELEASE_SITES = 4


def _live_ritual_section(text: str) -> str:
    """Return the live-ritual section body, excluding the `Historical:`
    subsection (where alpha-cadence ordering is intentionally different)
    AND excluding the Recovery subsection (which documents the bad-order
    case so its example block doesn't satisfy the push-tags-before-
    gh-release invariant by accident)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_excluded = False
    for line in lines:
        if line.startswith("## Historical:") or line.startswith("### Recovery:"):
            in_excluded = True
            continue
        # ⚠ A `### ` heading ends the excluded subsection too. Clearing only on
        # `## ` meant one `### Recovery:` swallowed the REST of its section:
        # driven, injecting one after `## Release procedure` took the sites the
        # ordering invariant inspects from 4 to 2 with both tests still green.
        # The doc already carries two `### Recovery:` headings, so a third is
        # house idiom, not a hypothetical.
        if in_excluded and (
            line.startswith("## ")
            or (line.startswith("### ") and not line.startswith("### Recovery:"))
        ):
            in_excluded = False
        if not in_excluded:
            out.append(line)
    return "".join(out)


def test_release_checklist_pushes_tags_before_gh_release_create() -> None:
    """Every release-creation command must be preceded by a tag push.

    Three qualifiers, each load-bearing (see the module docstring):
    the push must be in a FENCED command (prose does not count), in the
    SAME `##` section, and it may be `--tags`, `--follow-tags`, or an
    explicit single-tag `git push origin vX.Y.Z`.
    """
    sections = _sections(
        _live_ritual_section(CHECKLIST.read_text(encoding="utf-8"))
    )
    failures: list[str] = []
    inspected = 0
    for heading, body in sections:
        commands = _fenced_commands_only(body)
        inspected += len(_GH_RELEASE_RE.findall(commands))
        for match in _GH_RELEASE_RE.finditer(commands):
            if not _PUSH_TAGS_RE.search(commands[: match.start()]):
                failures.append(
                    f"{heading}: a release-creation command has no "
                    f"preceding tag push in a fenced block in the SAME "
                    f"section. The tag must reach origin first, or the "
                    f"release notes render broken compare URLs (TP-85). "
                    f"A prose mention does not count."
                )
    assert not failures, "\n".join(failures)
    assert inspected >= _MIN_RELEASE_SITES, (
        f"the ordering invariant inspected only {inspected} release-creation "
        f"site(s), below the live floor of {_MIN_RELEASE_SITES}. Zero sites and "
        f"all-sites-correct are the same green, so this check needs a floor: a "
        f"section heading that `_live_ritual_section` mishandles silently "
        f"removes coverage instead of failing."
    )


def test_release_creation_commands_are_fenced() -> None:
    """No release-creation command may be written as inline code.

    `test_release_checklist_pushes_tags_before_gh_release_create` reads
    only fenced commands, so an invocation written as single-backtick
    inline code is not checked -- it is invisible, which reads identically
    to "correct". MEASURED 2026-09-02: tightening that check to fenced-only
    fixed the first-publish site and simultaneously opened this gap on the
    Hotfix cadence section, whose step 8 was inline. One section's repair
    silently uncovered another.

    This guard turns that blind spot into a red. It is the cheap half of
    the pair: the ordering check proves the commands it can see are right,
    and this proves it can see all of them.
    """
    text = _live_ritual_section(CHECKLIST.read_text(encoding="utf-8"))
    failures: list[str] = []
    seen = 0
    for heading, body in _sections(text):
        total = len(_GH_RELEASE_RE.findall(body))
        seen += total
        checked = len(_GH_RELEASE_RE.findall(_fenced_commands_only(body)))
        if total != checked:
            failures.append(
                f"{heading}: {total - checked} of {total} release-creation "
                f"command(s) are inline code, not fenced, so the ordering "
                f"invariant cannot see them. Put the command in a ```bash "
                f"fence like its sibling sections."
            )
    assert not failures, "\n".join(failures)
    assert seen >= _MIN_RELEASE_SITES, (
        f"only {seen} release-creation site(s) reached this check, below the "
        f"live floor of {_MIN_RELEASE_SITES} -- see the sibling test."
    )


class TestTheCheckIsNotVacuous:
    """Synthetic fixtures for the two ways this check has already shipped vacuous.

    Every other assertion in this module reads the LIVE document, so a future
    edit that quietly re-breaks the helpers -- a heading depth change, an
    unbalanced fence inverting `in_fence` for the rest of a section -- makes the
    whole module vacuous and green. These four pin the behaviour against
    literals instead, so the repair itself is regression-tested.
    """

    def test_prose_does_not_satisfy_the_invariant(self):
        """Vacuity #1: a sentence saying NOT to push tags held a real site up."""
        body = (
            "## S\n"
            "Never run `git push --tags` here.\n"
            "```bash\ngh release create v1\n```\n"
        )
        commands = _fenced_commands_only(body)
        assert _GH_RELEASE_RE.search(commands), "the fenced release command is visible"
        assert not _PUSH_TAGS_RE.search(commands), (
            "a prose mention of --tags must NOT count as a push"
        )

    def test_a_push_in_an_earlier_section_does_not_vouch_for_a_later_one(self):
        """Vacuity #2: one push vouched for every later section in the document."""
        doc = (
            "## A\n```bash\ngit push origin v1\n```\n"
            "## B\n```bash\ngh release create v1\n```\n"
        )
        blocks = _sections(doc)
        assert len(blocks) == 2, f"expected 2 sections, got {[h for h, _ in blocks]}"
        _, section_b = blocks[1]
        commands = _fenced_commands_only(section_b)
        assert _GH_RELEASE_RE.search(commands)
        assert not _PUSH_TAGS_RE.search(commands), (
            "section A's push must not satisfy section B"
        )

    def test_a_dry_run_push_does_not_satisfy_the_invariant(self):
        """A dry run puts no tag on origin."""
        assert not _PUSH_TAGS_RE.search("git push --dry-run --follow-tags origin main")
        assert _PUSH_TAGS_RE.search("git push origin main --follow-tags")

    def test_a_quoted_or_bare_tag_ref_both_count(self):
        """The first-publish step derives the version, so the ref is quoted."""
        assert _PUSH_TAGS_RE.search('git push origin "v$VER"')
        assert _PUSH_TAGS_RE.search("git push origin v0.8.0a13")
        assert not _PUSH_TAGS_RE.search("git push -u origin main")


def test_release_checklist_has_recovery_subsection() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    assert re.search(
        r"### Recovery: `?gh release create`? ran before tags", text
    ), (
        "RELEASE_CHECKLIST.md must have a 'Recovery: gh release "
        "create ran before tags pushed' subsection (TP-85). Future "
        "operators who hit this need the recovery procedure."
    )


def test_release_checklist_has_hotfix_cadence_section() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    assert re.search(r"^## Hotfix cadence", text, re.MULTILINE), (
        "RELEASE_CHECKLIST.md must have a '## Hotfix cadence' section "
        "(TP-85). v0.7.1.1 demonstrated the gap; the next hotfix "
        "should not reinvent the procedure."
    )

    # The hotfix section must include a multi-tag push command.
    hotfix_match = re.search(
        r"^## Hotfix cadence.*?(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert hotfix_match is not None
    assert _MULTI_TAG_PUSH_RE.search(hotfix_match.group(0)), (
        "Hotfix cadence section must document a multi-tag push "
        "(`git push --tags` or `git push origin vA vB`) -- "
        "push-pending accumulation is the v0.7.1.1 failure mode."
    )


# ---------------------------------------------------------------------------
# First publish, step 5: the ordering check is the check it means (DEF-878)
# ---------------------------------------------------------------------------

_STEP5_START = "5. **Seed the new repo from the built artifact.**"
_STEP6_START = "6. **Claim the PyPI namespace"


def _first_publish_step5(text: str) -> str:
    start = text.index(_STEP5_START)
    return text[start:text.index(_STEP6_START, start)]


def _bare_status_porcelain(line: str) -> bool:
    return line.split("#")[0].split() == ["git", "status", "--porcelain"]


def _first_publish_ordering_violations(step5: str) -> list[str]:
    """What is wrong with step 5's ordering checks, or nothing.

    Until 2026-09-22 the block staged everything, annotated a bare
    ``git status --porcelain`` with "expect: NO output at all" and committed
    later -- in a just-initialised repo that read prints one ``A`` line per
    file on a CORRECT run (1098 at HEAD), so the check trained the operator to
    ignore the one worktree-modified line it existed to catch. The check that
    needs no commit is ``git diff --name-only`` (nothing edited after staging);
    the porcelain read belongs AFTER the commit and the suite, where it says
    the suite left nothing behind.
    """
    lines = step5.splitlines()
    problems: list[str] = []
    commit_at = next((i for i, ln in enumerate(lines) if ln.strip().startswith("git commit ")), None)
    if commit_at is None:
        return ["step 5 has no `git commit` line"]
    suite_at = next((i for i, ln in enumerate(lines) if "python3 -m pytest" in ln), None)
    add_at = next((i for i, ln in enumerate(lines) if ln.split("#")[0].split() == ["git", "add", "-A"]), None)
    if add_at is None or add_at > commit_at:
        problems.append("step 5 has no `git add -A` before the commit")
        add_at = -1
    diff_checks = [i for i, ln in enumerate(lines)
                   if ln.split("#")[0].split()[:3] == ["git", "diff", "--name-only"]
                   and "expect: NO output" in ln and "--cached" not in ln]
    # BETWEEN the staging and the commit: before `git add -A` in a fresh repo
    # nothing is tracked, so the read is always empty and checks nothing (the
    # DEF-878 shape displaced by one line; the 2026-09-22 review drove it).
    if not any(add_at < i < commit_at for i in diff_checks):
        problems.append("no `git diff --name-only  # expect: NO output` between the staging and the commit")
    porcelain = [i for i, ln in enumerate(lines) if _bare_status_porcelain(ln)]
    if any("NO output at all" in lines[i] for i in porcelain):
        problems.append("a bare `git status --porcelain` still expects `NO output at all` (the pre-commit read that always has output)")
    if any(i < commit_at for i in porcelain):
        problems.append("a bare `git status --porcelain` sits before the commit")
    if suite_at is None or suite_at < commit_at:
        problems.append("the suite does not run after the commit")
    else:
        after = [i for i in porcelain if i > suite_at and "expect: NO output" in lines[i]]
        if not after:
            problems.append("no `git status --porcelain  # expect: NO output` after the suite")
        else:
            # The disposition at the one-way door: the comment lines under the
            # read must tell the operator what NOT to do when it prints.
            tail = " ".join(ln.strip() for ln in lines[after[0] + 1:after[0] + 5] if ln.strip().startswith("#"))
            if "do NOT stage" not in tail or "do NOT push" not in tail:
                problems.append("the post-suite porcelain read has no disposition (do NOT stage / do NOT push) under it")
    return problems


def test_first_publish_ordering_check_is_a_diff_before_the_commit_and_a_porcelain_read_after_the_suite() -> None:
    step5 = _first_publish_step5(CHECKLIST.read_text(encoding="utf-8"))
    assert not _first_publish_ordering_violations(step5), _first_publish_ordering_violations(step5)


def test_the_prior_ordering_check_is_reported() -> None:
    """Earn the red: the block as it stood before 2026-09-22 -- stage, bare
    porcelain expecting nothing, commit, suite before the commit -- is named."""
    prior = """5. **Seed the new repo from the built artifact.**
   ```bash
   python3 -m pytest -q -m "not slow"    # expect: 0 failed
   git add -A
   git status --porcelain                            # expect: NO output at all
   git diff --cached --name-only | wc -l             # expect: the step-2 count
   git commit -qm "espalier-harness v$VER"
   ```
6. **Claim the PyPI namespace"""
    problems = _first_publish_ordering_violations(_first_publish_step5(prior))
    assert "no `git diff --name-only  # expect: NO output` between the staging and the commit" in problems, problems
    assert any("NO output at all" in p for p in problems), problems
    assert "the suite does not run after the commit" in problems, problems


def test_a_diff_check_placed_before_the_staging_is_reported() -> None:
    """The displaced form: the right command one line too early reads an empty
    index and passes vacuously; and a porcelain read with no disposition."""
    displaced = """5. **Seed the new repo from the built artifact.**
   ```bash
   git diff --name-only                              # expect: NO output
   git add -A
   git commit -qm "espalier-harness v$VER"
   python3 -m pytest -q -m "not slow" -p no:cacheprovider
   git status --porcelain                            # expect: NO output
   ```
6. **Claim the PyPI namespace"""
    problems = _first_publish_ordering_violations(_first_publish_step5(displaced))
    assert "no `git diff --name-only  # expect: NO output` between the staging and the commit" in problems, problems
    assert any("no disposition" in p for p in problems), problems


# ── Tier 3: the fresh-clone gate runs before the matrix ─────────────────────
#
# The matrix (`final_release_matrix.py`) proves the ARTIFACT; the gate
# (`fresh_clone_gate.py`) proves the TREE the artifact is built from, on a
# checkout the suite was not written on and on the floor interpreter. Both
# release-gating defects of the 2026-09-19 review sat in the commits meant to
# finish the work, and the one instrument that would have caught them was the
# one never wired. This pins the wiring: a fenced gate line inside the Tier 3
# section, ABOVE the fenced matrix line. Fenced, for the same reason as
# invariant 1 -- prose is not an instruction.

_TIER3_HEADING = "## Tier 3"
_GATE_LINE_RE = re.compile(r"^\s*python3?\s+scripts/fresh_clone_gate\.py\b.*$", re.MULTILINE)
_MATRIX_LINE_RE = re.compile(r"^\s*python3?\s+scripts/final_release_matrix\.py\b", re.MULTILINE)
_PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"
_REQUIRES_PYTHON_RE = re.compile(r'^requires-python\s*=\s*"\s*>=\s*(\d+\.\d+)', re.MULTILINE)


def _python_floor(pyproject_text: str) -> str:
    """The declared floor, from canon: `requires-python = ">=X.Y"`."""
    m = _REQUIRES_PYTHON_RE.search(pyproject_text)
    assert m, "pyproject.toml declares no `requires-python = \">=X.Y\"` -- re-point _REQUIRES_PYTHON_RE"
    return m.group(1)


def _tier3_section(text: str) -> str:
    for heading, body in _sections(text):
        if heading.startswith(_TIER3_HEADING):
            return body
    raise AssertionError(f"no `{_TIER3_HEADING}` section in the checklist -- re-point _TIER3_HEADING")


def _tier3_gate_violations(section: str, floor: str) -> list[str]:
    """What is wrong with Tier 3's gate wiring, or nothing. The gate's default
    is ONE leg on the running interpreter; the leg that earns its keep is the
    floor's (two of the three reds the gate found at authoring were 3.10-only),
    so the fenced line must name `--python <floor>` -- derived from
    `pyproject.toml`, never typed here."""
    fenced = _fenced_commands_only(section)
    gate = _GATE_LINE_RE.search(fenced)
    matrix = _MATRIX_LINE_RE.search(fenced)
    problems: list[str] = []
    if gate is None:
        problems.append("no fenced `python scripts/fresh_clone_gate.py` line in the Tier 3 section")
    if matrix is None:
        problems.append("no fenced `python scripts/final_release_matrix.py` line in the Tier 3 section")
    if gate is not None and matrix is not None and gate.start() > matrix.start():
        problems.append("the fenced gate line sits BELOW the fenced matrix line -- the gate runs first")
    if gate is not None and f"--python {floor}" not in gate.group(0):
        problems.append(f"the fenced gate line does not run the floor interpreter (`--python {floor}`)")
    return problems


def test_tier_3_runs_the_fresh_clone_gate_before_the_matrix_on_the_floor() -> None:
    section = _tier3_section(CHECKLIST.read_text(encoding="utf-8"))
    floor = _python_floor(_PYPROJECT.read_text(encoding="utf-8"))
    assert not _tier3_gate_violations(section, floor), _tier3_gate_violations(section, floor)


def test_a_gate_line_below_the_matrix_or_in_prose_or_off_the_floor_is_reported() -> None:
    """Earn the red: the line moved below the matrix; the line as prose; the
    line without the floor interpreter."""
    below = """## Tier 3 — Publish gate
```bash
python scripts/final_release_matrix.py
python scripts/fresh_clone_gate.py --python 3.10
```
"""
    assert _tier3_gate_violations(below, "3.10") == [
        "the fenced gate line sits BELOW the fenced matrix line -- the gate runs first"
    ]
    prose = """## Tier 3 — Publish gate
Run python scripts/fresh_clone_gate.py first.
```bash
python scripts/final_release_matrix.py
```
"""
    assert _tier3_gate_violations(prose, "3.10") == [
        "no fenced `python scripts/fresh_clone_gate.py` line in the Tier 3 section"
    ]
    off_floor = """## Tier 3 — Publish gate
```bash
python scripts/fresh_clone_gate.py
python scripts/final_release_matrix.py
```
"""
    assert _tier3_gate_violations(off_floor, "3.10") == [
        "the fenced gate line does not run the floor interpreter (`--python 3.10`)"
    ]


def test_the_floor_is_read_from_pyproject() -> None:
    assert _python_floor('requires-python = ">=3.10"\n') == "3.10"
    assert _python_floor('[project]\nrequires-python = ">= 3.12"\n') == "3.12"
