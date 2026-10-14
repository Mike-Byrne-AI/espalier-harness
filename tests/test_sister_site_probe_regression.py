"""TP-107: regression test for sister-site probe against pre-pack-TP-104.

Pins the "earn the gate" calibration corpus mechanically. The probe was
authored against pre-pack-TP-104 state (9 copies of ``def _project_root``,
one per hook) and validated by reporting exit 2 with the 9-clique. That
validation was institutional memory until this test. If a future
contributor raises the threshold, broadens the DIVERGENT exemption, or
rewrites ``_hash_body``, the assertions here fail because the 9-clique on
``_project_root`` must remain detectable in the pre-pack hook tree.

The pre-pack hook tree is ``tests/fixtures/pre_pack_tp104/``: the nine hooks
as they stood at the ``pre-pack-TP-104`` tag (``8e138f6``), extracted byte for
byte with ``git show`` and kept as ``.py.txt`` so ruff and mypy never read
them. The tag is private-only history, so while this test read it from git it
skipped on every public clone, CI included (DEF-938); the fixture runs
everywhere, and its sha256 is the pin a rebuilt or edited copy fails, as the
tag SHA once was.

Prevents silent calibration drift on the probe's design target.

Test naming follows ``test_{specific_behavior}`` per docs/CONVENTIONS.md.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PROBE_PATH = REPO_ROOT / "tools" / "cc"
sys.path.insert(0, str(PROBE_PATH))
from sister_site_probe import probe_compression_debt  # noqa: E402

PRE_PACK_HOOKS = (
    "config_guard", "plan_guard", "post_compact", "post_write_check",
    "reflect_trigger", "session_start", "stop_gate", "subagent_stop",
    "write_guard",
)
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "pre_pack_tp104"
#: sha256 of the nine fixtures concatenated in PRE_PACK_HOOKS order: the bytes
#: the operator approved on 2026-10-12 (prefix 5846d53e86e8ddb4), read from
#: the pre-pack-TP-104 tag (8e138f6) with git show.
FIXTURE_SHA256 = "5846d53e86e8ddb46dc0d62294bb6e1acf2666d56cfd7c39aa67232ab94e055d"
#: Each fixture's own sha256, so a red names the file that changed.
FIXTURE_SHA256_BY_HOOK = {
    "config_guard": "1cdae0d809d69da35789c77b4cf6d58060b4b9f9bec978249afb3e9d68811b65",
    "plan_guard": "790e16570a185cb4b0d30b1d099ba526a31b49b95b61fde04e2971383f5f45c6",
    "post_compact": "aa836068fd489054961385d634fc7f96aa08958b0aeec9171f7a6b97aad26821",
    "post_write_check": "35fbf6387a0b8458d3d20c2d5b5785f2a77bffb365b67802104cc668067a35c4",
    "reflect_trigger": "04f72ea1c1ea6406bb2052d765e7dad7ec233a5e4e6045cad7ccaf75f7b0e04a",
    "session_start": "c1aa43df26fc0a96ed252791452ae29f21a675dd3f96c4ccb87c6181e98c2ed8",
    "stop_gate": "04a6defca2070f49c59b8d4cbdb51a610148156b00698afcdd1b65c270028cf5",
    "subagent_stop": "4f7c8f8a07e83af41df13a155eceee58fd28fc2d2108f29cd8176fb7650dafec",
    "write_guard": "d422e06bc5257266d4587dcb616cb8c995b8c6674cdfa9473387139fee273bdf",
}
_RESTORE = (
    "Do not re-pin: these are the bytes the operator approved, the calibration's whole "
    "point. Restore them with `git restore --source=origin/main -- tests/fixtures/pre_pack_tp104/` "
    "(or from the pre-pack-TP-104 tag where it exists, with git show). If `git status` is "
    "clean, a core.autocrlf checkout rewrote them: check the fixture's -text row in "
    "`.gitattributes`."
)


def _fixture(hook: str) -> Path:
    return FIXTURE_DIR / f"{hook}.py.txt"


@pytest.mark.security
class TestProbeAgainstPrePackTP104:
    def test_fixture_bytes_match_the_approved_pin(self):
        """The fixture must be the pre-pack-TP-104 hooks, byte for byte.

        A rebuilt, re-encoded or edited copy breaks the calibration corpus (a
        CRLF checkout among them, which the fixture's `-text` row in
        `.gitattributes` forecloses); the hash catches each one.
        """
        changed = sorted(h for h in PRE_PACK_HOOKS
                         if hashlib.sha256(_fixture(h).read_bytes()).hexdigest() != FIXTURE_SHA256_BY_HOOK[h])
        assert not changed, (
            f"tests/fixtures/pre_pack_tp104/: {[f'{h}.py.txt' for h in changed]} changed, so the "
            f"probe's 'earn the gate' validation receipt is broken. {_RESTORE}")
        digest = hashlib.sha256(b"".join(_fixture(h).read_bytes() for h in PRE_PACK_HOOKS)).hexdigest()
        assert digest == FIXTURE_SHA256, (
            f"the nine files hash to {digest} together, not the approved {FIXTURE_SHA256} "
            f"(a byte moved across a file boundary). {_RESTORE}")

    def test_the_fixture_keeps_its_bytes_on_every_checkout(self):
        """`*.py`'s `eol=lf` row does not match `.py.txt`, so only this row keeps a
        core.autocrlf=true checkout from rewriting the fixture. Dies to: the row
        dropped, which no Linux or macOS run could otherwise notice."""
        rows = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        assert "tests/fixtures/pre_pack_tp104/*.py.txt -text" in rows

    def test_probe_fires_9_clique_on_pre_pack_hooks(self, tmp_path):
        """Probe must surface the 9-clique on _project_root in pre-pack state.

        Earn-the-gate proof: if this stops firing, the probe has drifted
        from its design target. Materialize each hook from the fixture
        into tmp_path/tools/cc/hooks/ and run the probe against tmp_path.
        """
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True)
        # Unmarked hooks are the SOURCE tree only beside the engine package
        # (``probe_mode``); without it the pre-pack hooks would be read as an
        # adopter's and their 9-clique would land in the advisory sub-report.
        (tmp_path / "espalier").mkdir()
        for hook in PRE_PACK_HOOKS:
            (hooks_dir / f"{hook}.py").write_bytes(_fixture(hook).read_bytes())

        report = probe_compression_debt([tmp_path])
        project_root_cliques = [
            c for c in report.cliques if c.name == "_project_root"
        ]
        assert len(project_root_cliques) == 1, (
            f"Expected exactly one _project_root clique; got "
            f"{len(project_root_cliques)}. Probe scoping broke."
        )
        clique = project_root_cliques[0]
        assert clique.severity == "WARN", (
            f"_project_root clique severity downgraded: {clique.severity}; "
            f"expected WARN (>= 3 sites)."
        )
        assert not clique.divergent, (
            "_project_root clique reported as DIVERGENT — the body-hash "
            "function may have changed and no longer detects byte-identical "
            "bodies."
        )
        assert len(clique.sites) >= 9, (
            f"_project_root clique shrank: {len(clique.sites)} sites "
            f"(expected >= 9). Probe scope or hook discovery broke."
        )


@pytest.mark.security
class TestMemoryDocMatchesLiveVerdict:
    """Bind `memory/sister-site-compression.md`'s table to the probe's verdict.

    This test is the one `memory/sister-site-compression.md` asked for and
    never got. Its 2026-08-06 callout recorded that the `_load_json` and
    `_safe_text` rows had said "DIVERGENT -- never block" while the section
    below them said the opposite, that a retired pack designed a noise filter
    around the wrong half, and closed with: *"Nothing asserts a row's stated
    shape against the probe's live verdict."*

    On 2026-08-10 those same two rows went stale again, in the same direction
    -- they still read "blocking today" after the delegating carve-out made
    them advisory. Twice is a class, so the prose is now derived-checked
    rather than trusted: the live probe names which cliques are delegating,
    and the doc must agree about each one.
    """

    DOC = REPO_ROOT / "memory" / "sister-site-compression.md"

    #: Rows that say in their own words that the probe cannot see their site.
    #: The doc-to-probe direction below skips them, and nothing else does.
    _INVISIBLE_TO_THE_PROBE = ("scope-out", "doesn't cover", "cannot see")

    def test_every_open_debt_row_names_a_clique_the_probe_still_reports(self):
        """The other direction. The rows above may only fail when the probe
        reports a clique the doc mis-describes; a row that keeps listing a debt
        the probe no longer reports could never red. `_check_branch` was
        hoisted to `_hook_utils.check_branch` while its row still read as a
        tolerated two-site duplicate awaiting a third occurrence."""
        report = probe_compression_debt([REPO_ROOT])
        live = {c.name for c in report.cliques} | {c.name for c in report.constant_cliques}
        text = self.DOC.read_text(encoding="utf-8")
        table = text.split("## Running compression debts", 1)[1].split("\n## ", 1)[0]
        stale: list[str] = []
        checked = 0
        for line in table.splitlines():
            cells = line.split("|")
            if not line.startswith("|") or len(cells) < 3 or "CLOSED" in line:
                continue
            if any(p in line.lower() for p in self._INVISIBLE_TO_THE_PROBE):
                continue
            names = [n for n in re.findall(r"`([^`]+)`", cells[1]) if n.isidentifier()]
            if not names:
                continue
            checked += 1
            if names[0] not in live:
                stale.append(names[0])
        assert checked >= 2, f"read only {checked} open row(s) -- the table moved"
        assert not stale, (
            f"{self.DOC.name} lists {stale} as an open debt, but the live probe "
            "reports no clique of that name. Mark the row CLOSED with what "
            "closed it, or say in the row that the probe cannot see the site."
        )

    def _row_for(self, text: str, name: str) -> str:
        """The table row whose Site cell names ``name``, else ''."""
        for line in text.splitlines():
            if line.startswith("|") and f"`{name}`" in line:
                return line
        return ""

    def test_doc_names_every_delegating_clique_as_delegating(self):
        report = probe_compression_debt([REPO_ROOT])
        delegating = [
            c.name for c in report.cliques
            if c.delegating and c.severity == "WARN"
        ]
        assert delegating, (
            "no delegating WARN clique on the live tree — if the carve-out "
            "was removed, retire this test with it rather than letting it "
            "pass vacuously"
        )
        text = self.DOC.read_text(encoding="utf-8")
        for name in delegating:
            row = self._row_for(text, name)
            if not row:
                continue  # not every clique is documented; absence is not a lie
            assert "DELEGATING" in row.upper(), (
                f"`{name}` is DELEGATING (advisory) per the live probe, but "
                f"its row in {self.DOC.name} does not say so. The row reads:"
                f"\n  {row.strip()[:300]}"
            )

    def test_doc_claims_no_blocking_state_the_probe_denies(self):
        """No documented row may claim to block while the probe exits 0."""
        report = probe_compression_debt([REPO_ROOT])
        advisory = {
            c.name for c in report.cliques
            if c.delegating or c.divergent or c.severity == "INFO"
        }
        text = self.DOC.read_text(encoding="utf-8")
        for name in sorted(advisory):
            row = self._row_for(text, name)
            if not row:
                continue
            lowered = row.lower()
            for claim in ("blocking today", "contributing to the exit-2"):
                assert claim not in lowered, (
                    f"`{name}` is advisory per the live probe, but its row "
                    f"in {self.DOC.name} still claims {claim!r}. This is the "
                    f"exact drift the doc's 2026-08-06 callout recorded."
                )
