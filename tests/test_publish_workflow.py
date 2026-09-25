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
    here as a ``bash -c`` call: this repo already carries a cohort of
    bash-invoking tests that fail on Windows runners, and gating them is a
    known open problem (WSL puts a ``bash.exe`` on PATH, so ``which("bash")``
    is the wrong oracle). Adding another bash-dependent test would enlarge
    that cohort to re-prove logic these assertions already pin.
    """

    _STEP_NAME = "Verify tag matches the built version"

    def _publish_steps(self) -> list[dict]:
        doc = _load(PUBLISH_YML)
        (job,) = [j for j in doc["jobs"].values() if any(
            s.get("name") == self._STEP_NAME for s in j.get("steps", [])
        )] or [None]
        assert job is not None, (
            f"no job in publish.yml carries a {self._STEP_NAME!r} step — the "
            "tag/version guard is missing entirely"
        )
        return job["steps"]

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
        build_at = next(
            i for i, s in enumerate(steps)
            if "build" in str(s.get("run", "")) and "pip install" not in str(s.get("run", ""))
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
