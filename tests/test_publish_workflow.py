"""TP-57 §1-B + §6 — supply-chain contract for publish.yml + release.yml.

Three contract classes:

- ``TestPublishWorkflowShape`` (§6 deliverables): publish.yml carries the
  `environment: pypi` key on its publish job, the workflow-level
  permissions block is `contents: read` only, the publish job's
  permissions add `id-token: write` (plus `attestations: write` for the
  build-provenance attestation step), and the checkout step pins to a
  minimum-scope configuration (fetch-depth 1, no submodules, no
  credentials).

- ``TestUsesAreSHAPinned`` (§6 deliverable (a)): every `uses:` field in
  publish.yml is SHA-pinned (40-char hex), with no exceptions. A
  commit-time placeholder escape hatch was carried here until every
  action -- including the release-critical pypa/gh-action-pypi-publish --
  was resolved to a real pin; it was then a live unused branch on the
  publishing action, so a revert to the placeholder would have passed
  the gate green.

- ``TestReleaseYmlPermissions`` (TP-57 round-4): release.yml self-
  declares `permissions: contents: read` at the workflow level so the
  publish-job's id-token: write cannot propagate into the gate jobs
  through reusable-workflow caller-context inheritance.
"""
from __future__ import annotations

# slow-exempt: the one subprocess call is a single `python -c` running the tag
# guard's own embedded version reader against a temp pyproject — milliseconds.
# This module is deliberately NOT moved into _SLOW_FILES: its other contracts
# (SHA-pinning, publish-job permissions, environment: pypi) are supply-chain
# gates whose whole value is running on every PR, and _SLOW_FILES would
# deselect them from the fast slice.

import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISH_YML = REPO_ROOT / ".github" / "workflows" / "publish.yml"
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"

SHA_PIN_RE = re.compile(r"^[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestPublishWorkflowShape:
    def test_workflow_level_permissions_is_contents_read_only(self) -> None:
        doc = _load(PUBLISH_YML)
        assert doc.get("permissions") == {"contents": "read"}

    def test_publish_job_permissions_add_id_token_write(self) -> None:
        doc = _load(PUBLISH_YML)
        publish = doc["jobs"]["publish"]
        perms = publish["permissions"]
        assert perms.get("id-token") == "write"
        assert perms.get("contents") == "read"
        # attestations: write is required by actions/attest-build-provenance
        # to record the signed SLSA provenance for the built wheel/sdist.
        assert perms.get("attestations") == "write"
        # Closed set on purpose: any scope beyond these three is permission
        # creep on the one job that holds id-token: write, and must be an
        # explicit, reviewed decision rather than an incidental addition.
        assert set(perms.keys()) == {"id-token", "contents", "attestations"}

    def test_publish_job_uses_pypi_environment(self) -> None:
        doc = _load(PUBLISH_YML)
        assert doc["jobs"]["publish"]["environment"] == "pypi"

    def test_gate_job_invokes_release_yml_as_reusable_workflow(self) -> None:
        doc = _load(PUBLISH_YML)
        gate = doc["jobs"]["gate"]
        assert gate["uses"] == "./.github/workflows/release.yml"

    def test_checkout_step_pins_minimum_scope(self) -> None:
        doc = _load(PUBLISH_YML)
        steps = doc["jobs"]["publish"]["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
        with_block = checkout["with"]
        assert with_block["fetch-depth"] == 1
        assert with_block["submodules"] is False
        assert with_block["persist-credentials"] is False


class TestUsesAreSHAPinned:
    def _collect_uses(self, doc: dict) -> list[str]:
        results: list[str] = []
        for job in doc.get("jobs", {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []) or []:
                if isinstance(step, dict) and "uses" in step:
                    results.append(step["uses"])
        return results

    # A prose sentence naming the pinned release ("<action> is SHA-pinned below
    # to vX.Y.Z.") ages the moment Dependabot moves the pin and the trailing
    # `# vX.Y.Z` comment: v4.1.1 sat beside a v4.2.2 pin for two days after the
    # 2026-09-27 bump, and the 40-hex assertion below cannot see prose.
    _NARRATIVE_PIN_RE = re.compile(
        r"(?P<action>[\w./-]+) is SHA-pinned below to (?P<tag>v[\d.]+)\."
    )

    def test_every_narrative_pin_mention_matches_its_uses_tag_comment(self) -> None:
        checked = 0
        for wf in sorted(PUBLISH_YML.parent.glob("*.yml")):
            text = wf.read_text(encoding="utf-8")
            for m in self._NARRATIVE_PIN_RE.finditer(text):
                uses = re.search(
                    r"uses:[ \t]*" + re.escape(m.group("action"))
                    + r"@[0-9a-f]{40}[ \t]*#[ \t]*(?P<tag>v[\d.]+)",
                    text[m.end():],
                )
                assert uses, (
                    f"{wf.name}: the sentence pinning {m.group('action')} to "
                    f"{m.group('tag')} has no SHA-pinned `uses:` line with a tag "
                    "comment after it"
                )
                assert uses.group("tag") == m.group("tag"), (
                    f"{wf.name}: prose says {m.group('action')} is pinned to "
                    f"{m.group('tag')} but the uses: line's comment says "
                    f"{uses.group('tag')}; move the sentence with the pin"
                )
                checked += 1
        # publish.yml carries three such sentences today; zero would mean the
        # regex stopped matching, not that the prose went away.
        assert checked >= 3, f"only {checked} narrative pin sentence(s) matched"

    def test_every_uses_is_sha_pinned(self) -> None:
        doc = _load(PUBLISH_YML)
        uses = self._collect_uses(doc)
        assert uses, "publish.yml has no steps with uses:"
        for ref in uses:
            _action, _, version = ref.partition("@")
            assert SHA_PIN_RE.match(version), (
                f"uses field {ref!r} is not SHA-pinned (40-char hex)"
            )


class TestTagVersionGuard:
    """publish.yml must verify the pushed tag matches the version it builds.

    ``python -m build`` reads ``version`` from pyproject.toml and ignores the
    tag entirely, and PyPI uploads are IMMUTABLE — so pushing ``v0.8.0b1`` at a
    commit still carrying ``0.8.0a13`` publishes ``0.8.0a13`` permanently, and
    the correct version can never afterwards be published under that filename.
    Nothing else in the publish path compares the two.

    **Why these assertions and not a text match.** An earlier form of this
    contract drove only the FAILURE direction, and it passes on a step that
    would break every publish: when the body was driven under a shell with no
    bare ``python``, ``built`` came back EMPTY, so ``[ "$tag" != "$built" ]``
    was true for a correct tag too — the guard rejected everything, and a
    one-direction check cannot see it. So the version-reading half is
    EXECUTED here, against a mutated pyproject as well as the live one, which
    is what proves it reads rather than hardcodes.

    **Deliberately shell-free.** The both-directions shell drive was performed
    at execution time and recorded in the pack's Landing. It is not reproduced
    here as a ``bash -c`` call: as of 2026-10-01 every bash-invoking test in
    this repo gates itself off Windows (on the platform, or on ``/bin/bash``
    being present -- ``which("bash")`` alone is the wrong oracle, since a
    Windows subprocess resolves a bare ``bash`` to the WSL shim in System32
    before it reads PATH). That is a reading, not a pin; the last ungated
    cohort reddened the Windows portability cell on every run until then.
    Adding another bash-dependent test would re-prove logic these assertions
    already pin.
    """

    _STEP_NAME = "Verify tag matches the built version"
    _BUILD_STEP_NAME = "Build wheel and sdist"

    def _publish_job(self) -> dict:
        doc = _load(PUBLISH_YML)
        (job,) = [j for j in doc["jobs"].values() if any(
            s.get("name") == self._STEP_NAME for s in j.get("steps", [])
        )] or [None]
        assert job is not None, (
            f"no job in publish.yml carries a {self._STEP_NAME!r} step — the "
            "tag/version guard is missing entirely"
        )
        return job

    def _publish_steps(self) -> list[dict]:
        return self._publish_job()["steps"]

    def _guard_body(self) -> str:
        for step in self._publish_steps():
            if step.get("name") == self._STEP_NAME:
                return step["run"]
        raise AssertionError("unreachable — _publish_steps asserts presence")

    def test_guard_step_exists_and_precedes_the_build(self) -> None:
        """Ordering is the whole point: after the build it proves nothing."""
        steps = self._publish_steps()
        names = [s.get("name") or s.get("uses", "") for s in steps]
        guard_at = names.index(self._STEP_NAME)
        # Keyed on the step NAME, then its command. A word match on `build`
        # named the guard step the day its comment said "build" (2026-10-07),
        # and a command match would do the same the day the step-level comment
        # above the guard, which already says `python -m build`, is folded into
        # its `run:`. A rename or a build migration reds here with its own
        # message instead of a bare StopIteration.
        build_at = next(
            (i for i, s in enumerate(steps) if s.get("name") == self._BUILD_STEP_NAME),
            None,
        )
        assert build_at is not None, (
            f"no step named {self._BUILD_STEP_NAME!r} in publish.yml; if the build "
            "step was renamed or moved into an action, update this contract deliberately"
        )
        assert re.search(r"python -m build\b", str(steps[build_at].get("run", ""))), (
            f"the {self._BUILD_STEP_NAME!r} step no longer runs `python -m build`; "
            "if the build mechanism changed, update this contract deliberately"
        )
        assert guard_at < build_at, (
            f"tag/version guard runs at step {guard_at} but the build is at "
            f"{build_at} — a guard after the build cannot prevent the upload"
        )

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason=(
            "the guard's payload imports tomllib, which is stdlib only from "
            "3.11. publish.yml pins python-version: '3.12' for the job that "
            "runs it, so executing the payload under an older matrix "
            "interpreter measures this runner, not the guard"
        ),
    )
    def test_guard_reads_the_version_rather_than_hardcoding_it(self, tmp_path) -> None:
        """Execute the embedded reader against a MUTATED pyproject.

        This is the arm that makes the contract non-trivially satisfiable: a
        step that echoed a fixed string would satisfy every text assertion and
        fail here.

        Skipped below 3.11 -- see the marker. This does NOT weaken the contract
        on the interpreter that matters: the guard only ever runs on the pinned
        3.12 runner, and the text assertions in the sibling tests still pin the
        payload's shape on every version.
        """
        import subprocess

        body = self._guard_body()
        payload = re.search(r"python -c '([^']+)'", body)
        assert payload is not None, (
            "the guard no longer embeds a `python -c '...'` version reader; "
            "if the mechanism changed, update this contract deliberately"
        )
        code = payload.group(1)

        live = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        mutated = re.sub(
            r'^version = "[^"]+"', 'version = "9.9.9rc7"', live, count=1, flags=re.MULTILINE
        )
        assert 'version = "9.9.9rc7"' in mutated, "probe failed to mutate the fixture"
        (tmp_path / "pyproject.toml").write_text(mutated, encoding="utf-8")

        got = subprocess.run(
            [sys.executable, "-c", code], cwd=tmp_path,
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout.strip()
        assert got == "9.9.9rc7", (
            f"the guard's version reader returned {got!r} against a pyproject "
            f'declaring 9.9.9rc7 — it is not reading the file'
        )

    def test_guard_fails_closed_on_mismatch_and_on_an_unreadable_version(self) -> None:
        """Both failure modes must exit non-zero — including the empty case.

        The empty-``built`` arm is not hypothetical: it is the measured way this
        guard can silently invert into rejecting every correct tag.
        """
        body = self._guard_body()
        assert 'GITHUB_REF_NAME#v' in body, (
            "the guard must strip the leading `v` from the tag before comparing"
        )
        assert re.search(r'\[\s*-z\s*"\$built"\s*\]', body), (
            "the guard must fail loudly when it cannot read a version; without "
            "this, an empty `built` makes the comparison true for EVERY tag and "
            "the guard rejects correct publishes instead of wrong ones"
        )
        assert re.search(r'\[\s*"\$tag"\s*!=\s*"\$built"\s*\]', body), (
            "the guard must compare the stripped tag against the built version"
        )
        assert body.count("exit 1") >= 2, (
            "both the unreadable-version and the mismatch branch must exit 1"
        )

    def test_guard_refuses_a_dispatch_against_a_branch(self) -> None:
        """The dispatch path must fail on a ref that is not a tag (DEF-893).

        ``push: tags: ['v*']`` constrains the ref on the push path only. The
        ``workflow_dispatch`` ref selector takes a branch as readily as a tag,
        and a branch named ``v<pyproject version>`` passes the tag/version
        comparison with the same build -- so without this arm the recovery
        trigger publishes that branch's tip to PyPI, immutably. The arm reads
        ``GITHUB_REF_TYPE`` (``branch`` or ``tag``; the runner sets it for every
        event) and sits BEFORE the version comparison, so the operator who
        picked the wrong ref is told that, not shown a version mismatch.

        Text-only on purpose, like its siblings (see the class docstring); the
        both-directions shell drive of the arm was performed at landing and is
        recorded in the lane's commit body.
        """
        body = self._guard_body()
        ref_type_check = re.search(r'\[\s*"\$GITHUB_REF_TYPE"\s*!=\s*"tag"\s*\]', body)
        assert ref_type_check is not None, (
            "the guard never tests GITHUB_REF_TYPE against `tag`: a "
            "workflow_dispatch against a branch named v<version> passes the "
            "version comparison and publishes that branch's tip (DEF-893)"
        )
        version_compare = re.search(r'\[\s*"\$tag"\s*!=\s*"\$built"\s*\]', body)
        assert version_compare is not None, "the sibling test pins this comparison"
        assert ref_type_check.start() < version_compare.start(), (
            "the ref-type arm must precede the version comparison, so a branch "
            "dispatch is diagnosed as a branch and not as a version mismatch"
        )
        # Scoped to the arm's own block. A count over the whole body has slack
        # (the `|| true` comment says ::error:: too), so an arm that lost its
        # echo, or its exit, would still count three of each.
        after = body[ref_type_check.end():]
        block_end = re.search(r"\n\s*fi\b", after)
        assert block_end is not None, "the ref-type `if` has no closing `fi`"
        block = after[: block_end.start()]
        assert re.search(r"(^|\n)\s*if\s+\[", block) is None, (
            "another `if` opened inside the ref-type arm's block; this slice "
            "would read that branch, not the arm's"
        )
        assert "::error::" in block and "exit 1" in block, (
            "the ref-type arm must exit 1 behind its own ::error:: annotation, "
            "inside its block -- an arm that echoes and falls through publishes "
            "anyway, and one that exits silently strands the operator"
        )

    def test_guard_step_and_publish_job_are_unconditional(self) -> None:
        """No `if:` on the step or the job: a skip condition skips the guard.

        Every other assertion in this class reads the step's ``run`` text, so
        an ``if: github.event_name == 'push'`` (the natural "skip the guard on
        a re-run" edit) would skip the ref-type arm AND the version comparison
        with the class green. The ledger row (DEF-893) measured the publish
        job carrying no ``if:``; this pins it.
        """
        job = self._publish_job()
        assert "if" not in job, (
            "the publish job carries an `if:`; a condition here skips the "
            "tag/version guard with every text assertion in this class green"
        )
        (step,) = [s for s in job["steps"] if s.get("name") == self._STEP_NAME]
        assert "if" not in step, (
            "the tag/version guard step carries an `if:`; a condition here skips "
            "the ref-type arm and the version comparison together"
        )

    def test_dispatch_trigger_takes_no_inputs_and_push_fires_on_v_tags_only(self) -> None:
        """The ``on:`` block is the arm's premise, and nothing else read it.

        The dispatch trigger deliberately takes no inputs: an input would be
        interpolated into the guard, and the ref selector already carries the
        one value it needs. An ``inputs:`` block whose tag name the guard read
        through ``${{ inputs.tag }}`` would satisfy every other assertion here
        and void the arm, since ``GITHUB_REF_TYPE`` would no longer describe
        the ref that was built. PyYAML reads the bare ``on`` key as the
        boolean True, hence the double lookup.
        """
        doc = _load(PUBLISH_YML)
        on = doc.get("on", doc.get(True))
        assert set(on) == {"push", "workflow_dispatch"}, on
        assert on["push"] == {"tags": ["v*"]}, on["push"]
        assert on["workflow_dispatch"] is None, (
            "workflow_dispatch gained a body (inputs?); the guard reads the ref "
            "selector only, by design -- see the `on:` comment in publish.yml"
        )


class TestReleaseYmlPermissions:
    def test_release_yml_workflow_permissions_is_contents_read_only(self) -> None:
        doc = _load(RELEASE_YML)
        assert doc.get("permissions") == {"contents": "read"}

    def test_release_yml_declares_workflow_call_trigger(self) -> None:
        doc = _load(RELEASE_YML)
        # PyYAML parses `on:` -> bool True at the top level when the
        # block has no scalar; safe_load returns dict for our shape.
        on_block = doc.get("on") if "on" in doc else doc.get(True)
        assert isinstance(on_block, dict), (
            "release.yml `on:` block must be a mapping (workflow_call "
            "requires a structured trigger)"
        )
        assert "workflow_call" in on_block, (
            "release.yml must declare `workflow_call:` so publish.yml "
            "can invoke it as a reusable workflow"
        )
