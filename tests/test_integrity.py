"""Tests for Pack 5 Task 5-B: integrity manifest + kill-switch
scan + audit log.

Pins the three-pillar integrity surface: the manifest (SHA records
of every managed hook and engine file), the kill-switch scan
(detects committed disable-all-hooks markers), and the audit log
(out-of-tree record of every integrity action). The audit log
lives under ``$HOME/.espalier/audit/`` by design; tests override
``HOME`` to ``tmp_path`` so the real home directory is never
touched. Without this contract any one of the three pillars could
silently break — manifest drift would let tampered hooks pass
``espalier integrity verify``, kill-switch detection would miss
committed disable markers, or audit-log writes would fail-open and
lose the cross-session record of who refreshed when.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _legacy_pathlib import legacy_pathlib_probes, probes_raise_on_eacces

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "cc" / "hooks"

sys.path.insert(0, str(HOOKS_DIR))
import _integrity  # noqa: E402
sys.path.pop(0)


def _seed_minimal_repo(tmp_path: Path, ending: bytes = b"\n") -> None:
    """Create the manifest-covered files on disk so hashes are computable,
    ended as ``ending`` (``b"\\r\\n"`` stands in for a checkout git re-ended)."""
    for rel in _integrity.MANIFEST_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"# {rel}".encode("utf-8") + ending)


def _write_manifest_from_current(tmp_path: Path) -> None:
    _integrity.write_manifest(tmp_path)


def _traversal_denied(path: Path) -> bool:
    """True when the OS refuses to say whether ``path`` is there.

    The precondition probe for the chmod-000 tests below, and it deliberately
    does NOT use ``Path.exists()`` -- the exact primitive
    ``_integrity._manifest_absent`` was fixed to stop using, for the same
    reason it gives there: it collapses "cannot tell" into "not there".

    Worse in a test than in the product, because the collapse is
    VERSION-GATED. ``Path.exists()`` swallows the EACCES on CPython 3.14 and
    PROPAGATES it on 3.10--3.13, so a guard written with it answers correctly
    on a 3.14 dev host and raises on every other supported interpreter. That
    is not hypothetical: it reddened CI run 31731067158 on the 3.10 and 3.11
    legs while `pytest tests/test_integrity.py` stayed green locally
    (docs/FAILURE_MODES.md 9.7 version-gated stdlib semantics; 13.7 the
    earn-the-red platform ceiling). ``os.stat`` raises on every version, so
    the discrimination is explicit here and the answer is the same everywhere.
    """
    try:
        os.stat(path)
    except PermissionError:
        return True
    except OSError:
        return False  # absent, or some other refusal -- not a traversal denial
    return False


def _writable_dir(path: Path) -> bool:
    """True when a NEW file can be created in ``path``.

    Drives the create rather than asking ``os.access``: the degradation under
    test is triggered by ``open(..., "a+")`` failing, and only an attempt
    answers that question the same way the code under test asks it. Note an
    EXISTING lock file opens fine in a read-only directory -- the denial is on
    creation -- which is why the caller unlinks it first.
    """
    probe = path / ".write-probe"
    try:
        probe.touch()
    except OSError:
        return False
    probe.unlink(missing_ok=True)
    return True


def _readable(path: Path) -> bool:
    """True when the process can actually open ``path`` for reading.

    Sibling of ``_traversal_denied`` for the file-mode case: there the parent
    cannot be traversed, here the file itself cannot be opened. Driving
    ``open()`` rather than asking ``os.access`` because ``os.access`` answers
    from the permission BITS and can disagree with the kernel under ACLs, and
    because ``open()`` is exactly what the code under test does.
    """
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


class TestManifestVerification:
    def test_clean_manifest_verifies(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True
        assert mismatched == []

    def test_tampered_file_detected(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_text(victim.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert "tools/cc/hooks/write_guard.py" in mismatched

    # DEF-725 -- the manifest hashes the canonical text form. git's
    # core.autocrlf=true (the Git for Windows installer's system-scope default)
    # rewrites LF to CRLF on checkout, and a manifest written over raw bytes
    # then reported every managed file changed (28 of 28, driven 2026-09-09)
    # while `refresh` only moved the wrongness to the next LF checkout. Written
    # and run RED against HEAD before the source edit.

    def test_a_crlf_checkout_of_a_managed_file_is_not_drift(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_bytes(victim.read_bytes().replace(b"\n", b"\r\n"))
        assert b"\r\n" in victim.read_bytes()  # the fixture really re-ended the file
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched

    def test_a_utf8_bom_or_a_bare_cr_is_not_drift(self, tmp_path):
        # A Notepad or PowerShell round-trip adds a UTF-8 BOM; a bare CR is the
        # third ending the install-ci compare already folded.
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        bom_victim = tmp_path / "tools/cc/hooks/write_guard.py"
        bom_victim.write_bytes(b"\xef\xbb\xbf" + bom_victim.read_bytes())
        cr_victim = tmp_path / "tools/cc/hooks/plan_guard.py"
        cr_victim.write_bytes(cr_victim.read_bytes().replace(b"\n", b"\r"))
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched

    def test_a_content_change_under_the_same_endings_is_still_drift(self, tmp_path):
        # The control for the two above: the canon folds endings, not bytes.
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_bytes(victim.read_bytes().replace(b"# ", b"#  "))
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False and "tools/cc/hooks/write_guard.py" in mismatched

    def test_the_canon_folds_endings_and_a_utf8_bom_only(self):
        canon = _integrity.canonical_text_bytes
        assert canon(b"a\r\nb\rc\n") == b"a\nb\nc\n"
        assert canon(b"\xef\xbb\xbfx") == b"x"
        # a UTF-16 re-encoding is real drift: such a hook cannot run at all
        assert canon(b"\xff\xfex\x00") == b"\xff\xfex\x00"
        assert canon(b"") == b""

    def test_the_manifest_declares_the_canonical_algorithm(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        data = json.loads((tmp_path / ".espalier" / "integrity.json").read_text(encoding="utf-8"))
        assert data["algorithm"] == _integrity.MANIFEST_HASH_ALGORITHM == "sha256-lf"
        # the raw-bytes name is still understood, so a manifest written before
        # this change verifies until its next refresh
        assert "sha256" in _integrity.SUPPORTED_HASH_ALGORITHMS

    def test_a_legacy_raw_bytes_manifest_still_verifies_raw_until_refresh(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        legacy = {
            "schema_version": _integrity.MANIFEST_SCHEMA_VERSION,
            "generated_at": "2026-09-09T00:00:00+00:00",
            "algorithm": "sha256",
            "files": _integrity.compute_current_hashes(tmp_path, algorithm="sha256"),
        }
        manifest_path = tmp_path / ".espalier" / "integrity.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_bytes(victim.read_bytes().replace(b"\n", b"\r\n"))
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False and "tools/cc/hooks/write_guard.py" in mismatched  # raw stays raw
        _write_manifest_from_current(tmp_path)  # refresh re-pins under the canon
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched

    def test_a_manifest_without_an_algorithm_field_is_read_as_raw_bytes(self, tmp_path):
        # No espalier writer ever omitted the field (the code review grepped the
        # history), so the branch is a hand-edited manifest's; it must mean what
        # every such manifest meant, raw bytes, or a canonical compare against
        # raw-recorded hashes reproduces the 28-file storm.
        _seed_minimal_repo(tmp_path)
        unlabelled = {
            "schema_version": _integrity.MANIFEST_SCHEMA_VERSION,
            "generated_at": "2026-09-09T00:00:00+00:00",
            "files": _integrity.compute_current_hashes(tmp_path, "sha256"),
        }
        manifest_path = tmp_path / ".espalier" / "integrity.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(unlabelled, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_bytes(victim.read_bytes().replace(b"\n", b"\r\n"))
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False and "tools/cc/hooks/write_guard.py" in mismatched

    def test_a_manifest_refreshed_on_a_crlf_tree_verifies_after_an_lf_checkout(self, tmp_path):
        # DEF-725's second half: `refresh` used to re-pin the CRLF bytes, so the
        # next LF checkout flipped all 28 back. On an all-LF seed raw and canon
        # agree, so only a CRLF seed can tell which form the WRITER hashed (a
        # writer-only slip greened every other case; the failure-mode review
        # drove it).
        _seed_minimal_repo(tmp_path, ending=b"\r\n")
        _write_manifest_from_current(tmp_path)
        _seed_minimal_repo(tmp_path)  # the next checkout comes back LF
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched

    def test_the_algorithm_name_pins_the_canon(self):
        # Changing canonical_text_bytes REQUIRES a new name with the old one kept
        # in SUPPORTED_HASH_ALGORITHMS, or every manifest in the field silently
        # mismatches: this red names that obligation, and the supported set is
        # derived from the dispatch table so a name cannot be accepted and hashed
        # by the wrong rule.
        sample = b"\xef\xbb\xbfa\r\nb\rc\n"
        assert _integrity.MANIFEST_HASH_ALGORITHM == "sha256-lf"
        assert hashlib.sha256(_integrity.canonical_text_bytes(sample)).hexdigest() == (
            "880553fca8fcea94e325ee2cfb48e5a985cc797f39a14cc6d3cedecfeb2ae4d2"
        )
        assert set(_integrity.SUPPORTED_HASH_ALGORITHMS) == set(_integrity._CANON_BY_ALGORITHM)
        with pytest.raises(ValueError):
            _integrity.compute_current_hashes(Path("."), "blake3")

    def test_the_writer_follows_an_older_deployed_reader(self, tmp_path, capsys):
        # The engine writes with its own copy of _integrity and the session reads
        # with the DEPLOYED one; a name the deployed copy cannot read would strand
        # the session on one sentinel whose remedy rewrote the same name (both
        # reviews drove the loop). The deployed copy is read for its constant,
        # never imported.
        _seed_minimal_repo(tmp_path)
        deployed = tmp_path / "tools/cc/hooks/_integrity.py"
        deployed.write_text('MANIFEST_HASH_ALGORITHM = "sha256"\n', encoding="utf-8")
        _write_manifest_from_current(tmp_path)
        data = json.loads((tmp_path / ".espalier" / "integrity.json").read_text(encoding="utf-8"))
        assert data["algorithm"] == "sha256"
        assert "upgrade --execute" in capsys.readouterr().err
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True, mismatched  # raw against raw, as that reader would

    def test_the_writer_keeps_its_canon_for_a_current_newer_or_absent_reader(self, tmp_path, capsys):
        _seed_minimal_repo(tmp_path)
        deployed = tmp_path / "tools/cc/hooks/_integrity.py"
        manifest_path = tmp_path / ".espalier" / "integrity.json"
        deployed.write_text('MANIFEST_HASH_ALGORITHM = "sha256-lf"\n', encoding="utf-8")
        _write_manifest_from_current(tmp_path)
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["algorithm"] == "sha256-lf"
        # a NEWER reader keeps the older names by the widening rule
        deployed.write_text('MANIFEST_HASH_ALGORITHM = "sha256-future"\n', encoding="utf-8")
        _write_manifest_from_current(tmp_path)
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["algorithm"] == "sha256-lf"
        deployed.unlink()  # a fresh tree has no reader yet
        _write_manifest_from_current(tmp_path)
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["algorithm"] == "sha256-lf"
        assert "upgrade --execute" not in capsys.readouterr().err

    def test_missing_file_reported(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        (tmp_path / "tools/cc/hooks/write_guard.py").unlink()
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert any("missing on disk" in m for m in mismatched)

    def test_absent_manifest_reports_missing(self, tmp_path):
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert mismatched == [_integrity.MANIFEST_ABSENT]

    def test_truncated_manifest_reports_unreadable_not_missing(self, tmp_path):
        """LANEB-02 earn-the-red: a truncated manifest used to read as ABSENT.

        `_load_manifest_unlocked` returns None for both, so verify_integrity
        emitted one sentinel for two states — and every consumer exempts the
        absent one, because a fresh checkout legitimately has no manifest.
        Net effect: a repo whose manifest could not be parsed got ZERO
        integrity signal anywhere in the harness.
        """
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        path = tmp_path / _integrity.MANIFEST_PATH
        path.write_text(path.read_text(encoding="utf-8")[:40], encoding="utf-8")
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert mismatched == [_integrity.MANIFEST_UNREADABLE]

    def test_non_dict_manifest_reports_unreadable_not_missing(self, tmp_path):
        """The other unparseable shape: valid JSON, wrong top-level type."""
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        (tmp_path / _integrity.MANIFEST_PATH).write_text("[1, 2, 3]", encoding="utf-8")
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert mismatched == [_integrity.MANIFEST_UNREADABLE]

    def test_a_latin1_manifest_is_read_not_a_traceback(self, tmp_path):
        """Ledger DEF-829: the manifest re-saved in a Windows code page.
        ``UnicodeDecodeError`` is a ``ValueError``, so the ``except OSError``
        around the strict read let it past every hook that verifies
        integrity. The bytes now go to ``load_json_dict_safe``, which decodes
        tolerantly: the files still verify, the stray byte lands in a key
        nobody reads."""
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        path = tmp_path / _integrity.MANIFEST_PATH
        raw = path.read_bytes().rstrip()
        assert raw.endswith(b"}")
        path.write_bytes(raw[:-1] + b', "note": "caf\xe9"}\n')
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is True and mismatched == []

    def test_a_latin1_first_log_line_still_yields_its_timestamp(self, tmp_path):
        """The audit-log age reader in the same module: the first line's
        timestamp is read past a non-UTF-8 byte later in the record."""
        log = tmp_path / "audit.jsonl"
        log.write_bytes(b'{"timestamp": "2026-09-16T00:00:00+00:00", "note": "caf\xe9"}\n')
        assert isinstance(_integrity._parse_first_log_timestamp(log), float)

    def test_absent_and_unreadable_do_not_share_a_sentinel(self, tmp_path):
        """The seam itself, stated once: the two states must be tellable apart.

        Pinning each sentinel separately above would still pass if a later
        refactor collapsed both constants onto the same string. This is the
        assertion that actually holds the fix in place.
        """
        assert _integrity.MANIFEST_ABSENT != _integrity.MANIFEST_UNREADABLE
        _seed_minimal_repo(tmp_path)
        absent_verdict = _integrity.verify_integrity(tmp_path)[1]
        _write_manifest_from_current(tmp_path)
        (tmp_path / _integrity.MANIFEST_PATH).write_text("{", encoding="utf-8")
        corrupt_verdict = _integrity.verify_integrity(tmp_path)[1]
        assert absent_verdict != corrupt_verdict, (
            "absent and corrupt share a sentinel again — the downstream "
            "fresh-checkout exemption now forgives a blind tamper-detector"
        )

    def test_symlinked_manifest_refused(self, tmp_path):
        """C-3: a symlinked ``.espalier/integrity.json`` must be REFUSED —
        following it would ingest attacker-controlled JSON into the drift
        verdict (orientation-poison). The loader returns None and
        verify_integrity reports it UNREADABLE — a torn/hostile symlink must
        never verify as clean, and must not be reported as ABSENT either:
        it used to share the absent sentinel, so every downstream consumer's
        fresh-checkout exemption silently forgave a poisoning attempt."""
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        real_manifest = tmp_path / _integrity.MANIFEST_PATH
        stolen = tmp_path / "stolen_integrity.json"
        real_manifest.replace(stolen)  # move the genuine manifest aside
        try:
            real_manifest.symlink_to(stolen)  # .espalier/integrity.json -> stolen
        except (OSError, NotImplementedError):
            pytest.skip("platform does not support symlinks")
        assert real_manifest.is_symlink()
        assert _integrity._load_manifest_unlocked(tmp_path) is None, (
            "a symlinked manifest must be refused (returns None)"
        )
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert mismatched == [_integrity.MANIFEST_UNREADABLE]
        assert mismatched != [_integrity.MANIFEST_ABSENT], (
            "a symlinked manifest is PRESENT and refused, not absent — "
            "sharing the absent sentinel routes it into every consumer's "
            "fresh-checkout exemption"
        )

    def test_symlinked_espalier_parent_refused(self, tmp_path):
        """C-3 sibling: a symlinked ``.espalier/`` PARENT is refused even when
        the integrity.json inside it is a genuine file — the loader guards on
        ``path.parent.is_symlink()`` too, so a swapped-out parent dir can't
        smuggle a manifest past the read."""
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        espalier_dir = tmp_path / ".espalier"
        real_dir = tmp_path / "real_espalier"
        espalier_dir.replace(real_dir)  # move the whole dir aside
        try:
            espalier_dir.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("platform does not support symlinks")
        assert espalier_dir.is_symlink()
        assert (tmp_path / _integrity.MANIFEST_PATH).exists()  # real file within
        assert _integrity._load_manifest_unlocked(tmp_path) is None, (
            "a symlinked .espalier/ parent must be refused (returns None)"
        )
        # Sentinel-level assertion, matching the sibling test above. Without it
        # only the manifest-symlink flavour pinned WHICH verdict a refusal
        # produces, and a refusal reported as ABSENT is forgiven by every
        # consumer's fresh-checkout exemption.
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert ok is False
        assert mismatched == [_integrity.MANIFEST_UNREADABLE]

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_unreadable_parent_is_not_reported_as_absent(self, tmp_path):
        """A manifest under a `.espalier/` we cannot traverse is NOT absent.

        `Path.exists()` swallows every OSError, not just ENOENT, so an EACCES
        parent returned False and read as "never existed" — the same "cannot
        tell" collapsed into "nothing to tell" that this whole seam exists to
        separate, one level further down. `os.stat` discriminates: only
        ENOENT / ENOTDIR mean genuinely absent.

        This fix originally shipped with no test, which is the born-weak shape
        this pack is about; the assertion below is the red it never earned.
        """
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        espalier_dir = tmp_path / ".espalier"
        os.chmod(espalier_dir, 0o000)
        try:
            # Guard against a platform where chmod does not actually deny us
            # (Windows, root, some network filesystems). Asked through
            # _traversal_denied, never Path.exists() -- see its docstring.
            if not _traversal_denied(tmp_path / _integrity.MANIFEST_PATH):
                pytest.skip("chmod did not deny traversal on this platform")
            assert _integrity._manifest_absent(tmp_path) is False, (
                "a manifest we merely cannot SEE was reported as absent — "
                "every consumer's fresh-checkout exemption then forgives it"
            )
        finally:
            os.chmod(espalier_dir, 0o755)

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_unreadable_parent_survives_the_legacy_probe_bodies(self, tmp_path):
        """The 3.10--3.13 arm of the same seam, reproduced on a 3.14 host.

        The sibling above cannot fail here: 3.14's ``Path`` probes swallow the
        EACCES, so every EACCES-unsafe call inside ``_manifest_absent`` answers
        instead of raising and the test passes for the wrong reason. With the
        upstream 3.10--3.13 bodies substituted it raises -- which is precisely
        what CI run 31731067158 reported and what no local run could see.

        Earned red, in three rounds, each a frame further in:
        ``_integrity.py::_manifest_is_symlinked`` (``Path.is_symlink()``) --
        the frame the FIRST cut of this fix moved the exception into;
        ``::_load_manifest_unlocked`` (``Path.exists()``); then
        ``::_under_shared_lock``, whose bare ``open()`` on the lock file inside
        the denied directory raises on EVERY version, 3.14 included. The first
        two now go through ``os.path.*``; the third degrades to an unlocked
        read. Only the ``verify_integrity`` assertion below reaches the third.
        """
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        # Precondition, asserted while the directory is still readable: a
        # missing manifest would otherwise reach the guard below as ENOENT and
        # skip with a message naming the wrong cause.
        # eacces-probe-ok: runs BEFORE the chmod below, on a readable tree
        assert (tmp_path / _integrity.MANIFEST_PATH).is_file()
        espalier_dir = tmp_path / ".espalier"
        os.chmod(espalier_dir, 0o000)
        try:
            if not _traversal_denied(tmp_path / _integrity.MANIFEST_PATH):
                pytest.skip("chmod did not deny traversal on this platform")
            with legacy_pathlib_probes():
                # NEGATIVE CONTROL, and it is load-bearing. Without it this test
                # cannot distinguish "the emulation reproduced the legacy raise
                # and the product survived it" from "the emulation did nothing".
                # Measured: adding EACCES to `_legacy_pathlib._IGNORED_ERRNOS`
                # -- the one edit that file's own comment says not to make --
                # turned the emulation into a no-op and every assertion below
                # still passed. A comment saying "do not silence this" is not a
                # mechanism; this line is.
                assert probes_raise_on_eacces(tmp_path / _integrity.MANIFEST_PATH), (
                    "the legacy probe emulation is NOT re-raising EACCES, so it "
                    "is reproducing nothing and the assertions below prove nothing"
                )
                assert _integrity._manifest_absent(tmp_path) is False, (
                    "a manifest we merely cannot SEE was reported as absent"
                )
                # The user-visible contract, not just the helper: a denied
                # manifest must reach the operator as UNREADABLE. This is the
                # assertion that would have caught the product-side defect.
                ok, mismatched = _integrity.verify_integrity(tmp_path)
                assert ok is False
                assert mismatched == [_integrity.MANIFEST_UNREADABLE]
        finally:
            os.chmod(espalier_dir, 0o755)

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_unreadable_managed_file_reports_drift_not_agreement(self, tmp_path):
        """A managed file we cannot HASH must read as drift, never as clean.

        Found by the round-two review, and the worst of the set because the
        symptom is silence: `compute_current_hashes` raised out of
        `verify_integrity`, and `doctor.py`'s caller catches
        `(OSError, AttributeError)` and passes -- so `integrity_drift` stayed
        EMPTY and doctor printed no integrity line at all, byte-identical to a
        healthy tree. Tamper-detection was blind and said nothing, which is
        precisely the state `MANIFEST_ABSENT`/`MANIFEST_UNREADABLE` were split
        apart to prevent.

        Native on 3.14 -- `_sha256_file`'s `open()` raises on every version, so
        this arm needs no emulation. Earned red both ways: pre-fix
        `verify_integrity` raised PermissionError here.
        """
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/ci_guard.py"
        os.chmod(victim, 0o000)
        try:
            if _readable(victim):
                pytest.skip("chmod did not deny reads on this platform")
            ok, mismatched = _integrity.verify_integrity(tmp_path)
            assert ok is False
            assert any("ci_guard" in m for m in mismatched), (
                f"an unreadable managed file vanished from the verdict: {mismatched}"
            )
        finally:
            os.chmod(victim, 0o644)

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_write_through_a_symlink_is_refused_by_name_not_by_raising(self, tmp_path):
        """`write_manifest`'s symlink refusal must survive an unreadable target.

        The one changed site nothing else witnesses. With `Path.is_symlink()`
        the operator got a raw PermissionError; the refusal now names the
        problem and tells them what to do about it.
        """
        _seed_minimal_repo(tmp_path)
        target = tmp_path / "target"
        target.mkdir()
        try:
            (tmp_path / ".espalier").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("platform does not support symlinks")
        os.chmod(target, 0o000)
        try:
            if not _traversal_denied(tmp_path / _integrity.MANIFEST_PATH):
                pytest.skip("chmod did not deny traversal on this platform")
            with legacy_pathlib_probes():
                with pytest.raises(OSError, match="refusing to write"):
                    _integrity.write_manifest(tmp_path)
        finally:
            os.chmod(target, 0o755)

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_unlocked_read_announces_itself(self, tmp_path, capsys):
        """Degrading to an unlocked read must not be silent.

        The fresh-clone shape, which is the realistic one: `.espalier/integrity.
        json` is tracked, `.manifest.write.lock` is transient and absent, and the
        directory is READ-ONLY. The lock cannot be created, so `_under_shared_lock`
        degrades -- and here the read SUCCEEDS, so the verdict comes back a clean
        `(True, [])` with the BC-036 reader/writer race silently retired. Nothing
        downstream can infer that from the verdict, so the signal has to be the
        warning. (On an UNTRAVERSABLE `.espalier/` the read fails anyway and the
        operator hears about it through MANIFEST_UNREADABLE; this arm is the one
        that would otherwise pass for clean.)
        """
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        espalier_dir = tmp_path / ".espalier"
        (espalier_dir / ".manifest.write.lock").unlink(missing_ok=True)
        os.chmod(espalier_dir, 0o555)
        try:
            if _writable_dir(espalier_dir):
                pytest.skip("chmod did not make the directory read-only here")
            capsys.readouterr()
            ok, mismatched = _integrity.verify_integrity(tmp_path)
            err = capsys.readouterr().err
        finally:
            os.chmod(espalier_dir, 0o755)
        assert (ok, mismatched) == (True, []), (
            "the read itself should still succeed on a read-only dir"
        )
        assert "UNLOCKED" in err, (
            "the verdict was computed without the manifest lock and said so "
            f"nowhere -- stderr was {err!r}"
        )

    def test_genuinely_absent_is_still_absent(self, tmp_path):
        """Negative control for the EACCES fix.

        Discriminating unknowable-from-absent must not break the benign case
        the exemption exists for: a fresh checkout really has no manifest.
        """
        _seed_minimal_repo(tmp_path)
        assert _integrity._manifest_absent(tmp_path) is True
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        assert mismatched == [_integrity.MANIFEST_ABSENT]

    def test_write_manifest_refuses_to_write_through_a_symlink(self, tmp_path):
        """The WRITER must refuse the shape the READER refuses.

        Found by the failure-mode review: doctor tells the operator to rebuild
        an unreadable manifest, but `integrity refresh` on a symlinked
        `.espalier/` wrote THROUGH the link and left the verdict unchanged — an
        inescapable loop, with the manifest silently landing outside the repo.
        `_manifest_is_symlinked` claimed to be the single owner of the rule
        while a third participant ignored it.
        """
        _seed_minimal_repo(tmp_path)
        espalier_dir = tmp_path / ".espalier"
        espalier_dir.mkdir(exist_ok=True)
        real_dir = tmp_path / "real_espalier"
        espalier_dir.replace(real_dir)
        try:
            espalier_dir.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("platform does not support symlinks")
        with pytest.raises(OSError, match="symlink"):
            _integrity.write_manifest(tmp_path)


class TestIntegrityBridgeSentinelBackfill:
    """The sentinels are a WIRE VALUE between the hook module and the engine.

    `MANIFEST_ABSENT`'s VALUE was deliberately left unchanged when the states
    were split, precisely so a skewed pair interoperates. Nothing cashed that
    in until the review round: engine code read the names as attributes, so a
    pre-split module raised AttributeError instead. The bridge backfills on
    load — one owner, so no consumer needs a defensive getattr and none can
    forget one.
    """

    def test_backfill_supplies_both_names_on_a_pre_split_module(self):
        from espalier._integrity_bridge import _backfill_sentinels

        class _PreSplit:
            pass

        module = _PreSplit()
        _backfill_sentinels(module)
        assert module.MANIFEST_ABSENT == "<manifest missing>"
        # None, not a placeholder string: a pre-split producer never emits this
        # state, so every `mismatched == [MANIFEST_UNREADABLE]` test must simply
        # not match. A string default could collide with a real legacy verdict.
        assert module.MANIFEST_UNREADABLE is None

    def test_backfill_supplies_the_canon_and_the_protocol_predicate(self):
        # DEF-725 added engine-side reads across the wire: install-ci and
        # selfcheck read the canon, `integrity verify` reads the predicate. Both
        # reviews drove a pre-DEF-725 hook module under the new engine raising
        # AttributeError from install-ci mid-deploy; the backfill is the old
        # `_same_ignoring_eol` rule, so the compare behaves as it did at that sha.
        from espalier._integrity_bridge import _backfill_sentinels

        class _PreCanon:
            MANIFEST_ABSENT = "<manifest missing>"
            MANIFEST_UNREADABLE = "<manifest unreadable>"

        module = _PreCanon()
        _backfill_sentinels(module)
        assert module.canonical_text_bytes(b"\xef\xbb\xbfa\r\nb\rc") == b"a\nb\nc"
        assert module.PROTOCOL_MISMATCH_PREFIXES == (
            "<algorithm_unsupported:", "<schema_version_unsupported:",
        )
        assert module.is_protocol_mismatch(["<algorithm_unsupported: manifest='x' verifier='y'>"])
        assert not module.is_protocol_mismatch(["tools/cc/hooks/write_guard.py"])
        assert not module.is_protocol_mismatch([])

    def test_backfill_never_overwrites_a_real_value(self):
        """Negative control: a current module must pass through untouched."""
        from espalier._integrity_bridge import _backfill_sentinels

        class _Current:
            MANIFEST_ABSENT = "sentinel-A"
            MANIFEST_UNREADABLE = "sentinel-B"

        module = _Current()
        _backfill_sentinels(module)
        assert module.MANIFEST_ABSENT == "sentinel-A"
        assert module.MANIFEST_UNREADABLE == "sentinel-B"

    def test_loader_actually_runs_the_backfill(self, monkeypatch):
        """The LOADER must invoke it — the helper being correct is not enough.

        The three assertions around this one call `_backfill_sentinels`
        directly, so deleting the call from `load_integrity_module` leaves all
        of them green: they pin the helper, not the wiring. Verified by
        mutation. Loading a real module cannot show the difference either,
        because the live `_integrity.py` already defines both names, so the
        backfill is a no-op on it. Spying on the call is what closes that.
        """
        from espalier import _integrity_bridge as bridge

        called: list[object] = []
        monkeypatch.setattr(bridge, "_backfill_sentinels", called.append)
        bridge.load_integrity_module()
        assert called, (
            "load_integrity_module() returned a module without running the "
            "sentinel backfill — a version-skewed _integrity.py then reaches "
            "engine code that reads those names as attributes"
        )

    def test_backfilled_legacy_value_matches_the_live_constant(self):
        """The compat default must equal what the producer actually emits.

        If someone changes MANIFEST_ABSENT's value, the bridge's hardcoded
        legacy string silently stops matching a real absent verdict and every
        consumer's fresh-checkout exemption breaks. This is the assertion that
        makes "the value was deliberately kept stable" checkable.
        """
        from espalier._integrity_bridge import _LEGACY_MANIFEST_ABSENT

        assert _LEGACY_MANIFEST_ABSENT == _integrity.MANIFEST_ABSENT


class TestKillSwitchScan:
    def _claude_dir(self, tmp_path):
        d = tmp_path / ".claude"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_unparseable_settings_is_silent_for_blockers_by_default(self, tmp_path):
        """The default must stay fail-OPEN here, deliberately.

        `write_guard` denies EVERY tool call on any finding from this scan, and
        a settings.json is most likely to be unparseable while someone is
        mid-edit — so reporting by default would deny the very Edit needed to
        repair it. That self-inflicted lockout is strictly worse than the
        fail-open, which is why the surfacing is opt-in rather than the
        obvious "just report it".
        """
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            '{"disableAllHooks": true,}', encoding="utf-8"  # trailing comma
        )
        assert _integrity.scan_for_kill_switches(tmp_path) == []

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_untraversable_claude_dir_does_not_raise(self, tmp_path):
        """An unreadable `.claude/` must return a verdict, not raise.

        The blast radius is why this is worth a test of its own: both BLOCKING
        consumers -- `write_guard`, which denies every tool call on a finding,
        and `config_guard` -- wrap this call in `except Exception` and fail open
        to an empty list. So a raise here does not surface as an error anywhere;
        it silently switches kill-switch detection OFF on the one surface
        documented as the anti-self-disable floor.

        Version-gated, so it needs the emulation: `Path.exists()` re-raised
        EACCES on 3.10-3.13 and swallowed it on the 3.14 dev host. Nothing in
        this suite would have caught it locally.
        """
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
        os.chmod(claude, 0o000)
        try:
            if not _traversal_denied(claude / "settings.json"):
                pytest.skip("chmod did not deny traversal on this platform")
            with legacy_pathlib_probes():
                assert probes_raise_on_eacces(claude / "settings.json"), (
                    "emulation is not re-raising EACCES; this proves nothing"
                )
                # Both arms: the blocking default AND the reporter opt-in, which
                # reaches a different branch further down the same function.
                assert _integrity.scan_for_kill_switches(tmp_path) == []
                assert _integrity.scan_for_kill_switches(
                    tmp_path, include_unreadable=True
                ) is not None
        finally:
            os.chmod(claude, 0o755)

    def test_unparseable_settings_reported_when_opted_in(self, tmp_path):
        """Reporters opt in, and then the scan says it could not run.

        Pre-fix this returned [] for every caller — a settings file the scanner
        could not read scored identically to one it read and found clean. Same
        absent-vs-unusable collapse as the manifest sentinel, in the same file,
        ~150 lines below the one this pack fixed.
        """
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            '{"disableAllHooks": true,}', encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(
            tmp_path, include_unreadable=True
        )
        assert any("unreadable settings file" in f for f in findings)
        assert any("settings.json" in f for f in findings)

    def test_opt_in_does_not_change_the_readable_verdicts(self, tmp_path):
        """Negative control: opting in must add nothing on a parseable file."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8"
        )
        assert _integrity.scan_for_kill_switches(
            tmp_path
        ) == _integrity.scan_for_kill_switches(tmp_path, include_unreadable=True)

    def test_disable_all_hooks_detected(self, tmp_path):
        claude = self._claude_dir(tmp_path)
        (claude / "settings.local.json").write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert any("disableAllHooks" in f for f in findings)

    @pytest.mark.parametrize("payload", [
        {"disableAllHooks": True},
        {"permissions": {"defaultMode": "bypassPermissions"}},
    ])
    @pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
    def test_bom_kill_switch_still_detected(self, tmp_path, payload, encoding):
        # TP-169 §13 #8 rounds 6-7: the RUNTIME kill-switch reader must be
        # BOM-tolerant across UTF-8/16/32 (PowerShell Out-File defaults to
        # UTF-16) — a BOM'd settings.json must NOT evade the live write_guard
        # DENY. Round-6 fixed the runtime sister-site; round-7 made it handle
        # all BOM encodings via decode_bom.
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_bytes(
            json.dumps(payload).encode(encoding)  # codec emits the BOM
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert findings, (
            f"{encoding}-BOM'd {payload!r} evaded the runtime kill-switch scan"
        )

    def test_bypass_permissions_detected(self, tmp_path):
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert any("bypassPermissions" in f for f in findings)

    def test_empty_hook_array_detected(self, tmp_path):
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": []}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert any("PreToolUse" in f and "empty list" in f for f in findings)

    def test_clean_settings_no_findings(self, tmp_path):
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command"}]}]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert findings == []

    def test_absent_settings_no_findings(self, tmp_path):
        assert _integrity.scan_for_kill_switches(tmp_path) == []

    # ─── TP-3-A: inner-empty hooks ───────────────────────────────────────────

    def test_empty_inner_hooks_detected(self, tmp_path):
        """Single matcher whose inner `hooks` array is empty → kill switch."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "*", "hooks": []}
            ]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert any("PreToolUse" in f and "empty inner hooks" in f for f in findings), (
            f"inner-empty-hooks not detected. findings={findings}"
        )

    def test_empty_inner_hooks_all_matchers_detected(self, tmp_path):
        """Multiple matchers all inner-empty → kill switch."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "Write", "hooks": []},
                {"matcher": "Bash", "hooks": []},
            ]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert any("PreToolUse" in f and "empty inner" in f for f in findings)

    def test_mixed_empty_and_nonempty_inner_no_finding(self, tmp_path):
        """At least one matcher non-empty → not a kill switch."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "Write", "hooks": []},
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "x"}
                ]},
            ]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert findings == [], f"false positive on mixed-empty matchers: {findings}"

    # ─── TP-3-B: no-op command detection ─────────────────────────────────────

    @pytest.mark.parametrize("noop_cmd", [
        "true",
        ":",
        "/bin/true",
        "/usr/bin/true",
        "",
        "exit 0",
        "exit 1",
        "  exit 0  ",  # whitespace-tolerant
    ])
    def test_noop_command_detected(self, tmp_path, noop_cmd):
        """Hook command set to a literal no-op → kill switch."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "*", "hooks": [
                    {"type": "command", "command": noop_cmd}
                ]}
            ]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert any("PreToolUse" in f and "no-ops" in f for f in findings), (
            f"no-op command not detected for {noop_cmd!r}. findings={findings}"
        )

    @pytest.mark.parametrize("real_cmd", [
        "python tools/cc/hooks/write_guard.py",
        "node hook.js",
        "/usr/bin/python3 -m my_hook",
        "echo running > /tmp/log; python real_hook.py",
        "exit 0; do_something",  # has a side-effect after `;`, not a no-op
    ])
    def test_real_command_no_finding(self, tmp_path, real_cmd):
        """Real hook commands must not be flagged as no-ops."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "*", "hooks": [
                    {"type": "command", "command": real_cmd}
                ]}
            ]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert findings == [], f"false positive for {real_cmd!r}: {findings}"

    def test_mixed_noop_and_real_no_finding(self, tmp_path):
        """If even one command is real, the event still does work → no finding."""
        claude = self._claude_dir(tmp_path)
        (claude / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "Write", "hooks": [
                    {"type": "command", "command": "true"}
                ]},
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python real.py"}
                ]},
            ]}}), encoding="utf-8"
        )
        findings = _integrity.scan_for_kill_switches(tmp_path)
        assert findings == []


class TestAuditLog:
    def test_append_creates_file_under_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        # Path.home() reads USERPROFILE on Windows, HOME on POSIX.
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        repo = tmp_path / "myrepo"
        repo.mkdir()
        _integrity.append_audit(
            repo,
            {"event_type": "test_event", "details": {"k": "v"}},
        )
        audit_dir = tmp_path / "home" / ".espalier" / "audit"
        files = list(audit_dir.glob("*.log"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(content) == 1
        record = json.loads(content[0])
        assert record["event_type"] == "test_event"
        assert record["details"] == {"k": "v"}
        assert "myrepo" in record["repo_path"]

    def test_append_permissions_600(self, tmp_path, monkeypatch):
        if os.name == "nt":
            pytest.skip("POSIX-only permission semantics")
        monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        repo = tmp_path / "myrepo"
        repo.mkdir()
        _integrity.append_audit(repo, {"event_type": "x"})
        audit_dir = tmp_path / "home" / ".espalier" / "audit"
        log_file = next(audit_dir.glob("*.log"))
        assert (log_file.stat().st_mode & 0o777) == 0o600
        assert (audit_dir.stat().st_mode & 0o777) == 0o700

    def test_append_never_raises_on_failure(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("ESPALIER_AUDIT_DIR", raising=False)
        # Point HOME to a path we can't write to (file where dir is expected)
        blocker = tmp_path / "blocker"
        blocker.write_text("this is a file, not a dir", encoding="utf-8")
        monkeypatch.setenv("HOME", str(blocker))
        # Path.home() reads USERPROFILE on Windows, HOME on POSIX.
        monkeypatch.setenv("USERPROFILE", str(blocker))
        _integrity.append_audit(tmp_path, {"event_type": "x"})
        captured = capsys.readouterr()
        assert "[WARN] espalier" in captured.err


def _run_hook(script: str, payload: dict, env_overrides: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


class TestSessionStartIntegration:
    def test_session_start_warns_and_audits_kill_switch_without_claiming_block(
        self, tmp_path, monkeypatch
    ):
        """SessionStart cannot block per the hook protocol; it surfaces
        kill-switch findings via stderr + audit and exits 0."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.local.json").write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8"
        )
        result = _run_hook(
            "session_start.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "HOME": str(tmp_path / "home"),
                "ESPALIER_AUDIT_DIR": str(tmp_path / "home" / ".espalier" / "audit"),
            },
        )
        assert result.returncode == 0, (
            "SessionStart must never block (cannot block per protocol); "
            f"got rc={result.returncode} stderr={result.stderr!r}"
        )
        assert "kill-switch" in result.stderr.lower()
        assert "cannot block" in result.stderr.lower(), (
            "stderr must use visibility-only wording (no claim of blocking)"
        )
        assert "disableAllHooks" in result.stderr
        audit_files = list(
            (tmp_path / "home" / ".espalier" / "audit").glob("*.log")
        )
        assert audit_files, "expected audit log entry"
        assert "session_kill_switch_detected" in audit_files[0].read_text(encoding="utf-8"), (
            "audit log must record the visibility-only event"
        )

    def test_tampered_file_warns_but_proceeds(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_text(victim.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
        result = _run_hook(
            "session_start.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "HOME": str(tmp_path / "home"),
                "ESPALIER_AUDIT_DIR": str(tmp_path / "home" / ".espalier" / "audit"),
            },
        )
        assert result.returncode == 0
        assert "integrity drift" in result.stderr
        audit = (tmp_path / "home" / ".espalier" / "audit")
        audit_files = list(audit.glob("*.log"))
        assert audit_files
        assert "session_integrity_drift" in audit_files[0].read_text(encoding="utf-8")

    def test_a_crlf_checkout_does_not_warn_of_drift(self, tmp_path, monkeypatch):
        # DEF-725's user: the banner told a Windows adopter every managed file
        # had changed out of band after git re-ended the checkout.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_bytes(victim.read_bytes().replace(b"\n", b"\r\n"))
        result = _run_hook(
            "session_start.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "HOME": str(tmp_path / "home"),
                "ESPALIER_AUDIT_DIR": str(tmp_path / "home" / ".espalier" / "audit"),
            },
        )
        assert result.returncode == 0
        assert "integrity drift" not in result.stderr
        # the positive: the check RAN and said ok (a check that crashed prints
        # a different line and no drift either -- the code review drove it)
        assert "Integrity: ok" in result.stdout

    def test_a_manifest_the_hooks_cannot_read_sends_the_operator_to_redeploy(self, tmp_path, monkeypatch):
        # The engine's copy wrote a name this deployed copy does not know: not
        # drift, and `refresh` would rewrite the same manifest -- the loop both
        # reviews drove. The banner names the redeploy.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        manifest_path = tmp_path / ".espalier" / "integrity.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["algorithm"] = "sha256-future"
        manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _run_hook(
            "session_start.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "HOME": str(tmp_path / "home"),
                "ESPALIER_AUDIT_DIR": str(tmp_path / "home" / ".espalier" / "audit"),
            },
        )
        assert result.returncode == 0
        assert "newer espalier than the deployed hooks" in result.stderr
        assert "upgrade --execute" in result.stderr
        assert "integrity drift" not in result.stderr
        assert "MANIFEST NEWER THAN HOOKS" in result.stdout

    def test_clean_repo_no_warnings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        result = _run_hook(
            "session_start.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home")},
        )
        assert result.returncode == 0
        assert "integrity drift" not in result.stderr
        assert "kill-switch" not in result.stderr


class TestPostWriteCheckIntegration:
    def test_drift_after_write_warns(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        victim = tmp_path / "tools/cc/hooks/write_guard.py"
        victim.write_text(victim.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")
        result = _run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(victim)},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home")},
        )
        assert result.returncode == 0
        assert "integrity drift" in result.stderr

    def test_allowlisted_write_skips_integrity_check(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        # Tamper, but write to an allowlisted path — should not trigger spot-check
        (tmp_path / "tools/cc/hooks/write_guard.py").write_text("drift\n", encoding="utf-8")
        memory = tmp_path / "ESPALIER_MEMORY.md"
        memory.write_text("# Memory\nok\n", encoding="utf-8")
        result = _run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(memory)},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home")},
        )
        assert result.returncode == 0
        assert "integrity drift" not in result.stderr


class TestCLI:
    def _cli(self, *args, env=None) -> subprocess.CompletedProcess:
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "espalier.cli", *args],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
            env=cmd_env, encoding="utf-8",
        )

    def test_refresh_writes_manifest(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        result = self._cli("integrity", "refresh", str(tmp_path))
        assert result.returncode == 0
        assert (tmp_path / ".espalier" / "integrity.json").exists()

    def test_verify_clean_exits_zero(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        self._cli("integrity", "refresh", str(tmp_path))
        result = self._cli("integrity", "verify", str(tmp_path))
        assert result.returncode == 0

    def test_verify_reports_the_algorithm_and_nudges_a_legacy_manifest_once(self, tmp_path):
        # DEF-725: a raw-bytes manifest verifies clean on the tree it was
        # written over and storms on the next checkout git re-ends; the one
        # sentence its holder needs is that a single refresh ends that.
        _seed_minimal_repo(tmp_path)
        legacy = {
            "schema_version": _integrity.MANIFEST_SCHEMA_VERSION,
            "generated_at": "2026-09-09T00:00:00+00:00",
            "algorithm": "sha256",
            "files": _integrity.compute_current_hashes(tmp_path, "sha256"),
        }
        manifest_path = tmp_path / ".espalier" / "integrity.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = self._cli("integrity", "verify", str(tmp_path))
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["integrity_ok"] is True and data["algorithm"] == "sha256"
        assert "refresh" in result.stderr and "sha256-lf" in result.stderr
        self._cli("integrity", "refresh", str(tmp_path))
        result = self._cli("integrity", "verify", str(tmp_path))
        assert json.loads(result.stdout)["algorithm"] == "sha256-lf"
        assert "predates" not in result.stderr  # the nudge is spent once adopted

    def test_verify_sends_a_manifest_the_hooks_cannot_read_to_the_redeploy(self, tmp_path):
        # A protocol sentinel is not drift: the remedy is to redeploy the hooks,
        # and a refresh would rewrite the same manifest (both reviews drove the
        # loop the old wording produced).
        _seed_minimal_repo(tmp_path)
        self._cli("integrity", "refresh", str(tmp_path))
        manifest_path = tmp_path / ".espalier" / "integrity.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["algorithm"] = "sha256-future"
        manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = self._cli("integrity", "verify", str(tmp_path))
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["algorithm"] == "sha256-future"
        assert data["mismatched"][0].startswith("<algorithm_unsupported:")
        assert "upgrade --execute" in result.stderr
        assert "revert the unintended edits" not in result.stderr

    def test_verify_drift_exits_one(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        self._cli("integrity", "refresh", str(tmp_path))
        (tmp_path / "tools/cc/hooks/write_guard.py").write_text("drift\n", encoding="utf-8")
        result = self._cli("integrity", "verify", str(tmp_path))
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["integrity_ok"] is False

    def test_verify_kill_switch_exits_two(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        self._cli("integrity", "refresh", str(tmp_path))
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / "settings.local.json").write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8"
        )
        result = self._cli("integrity", "verify", str(tmp_path))
        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["kill_switches"]


class TestInitAutoRefresh:
    def test_init_produces_valid_manifest(self, tmp_path):
        # Minimal target: init creates everything else itself
        # TP-73: cmd_init pre-flight requires .git/; mark the tmp dir
        # as a git directory (existence-only check).
        (tmp_path / ".git").mkdir(exist_ok=True)
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0, f"init failed: {result.stderr}"
        manifest = tmp_path / ".espalier" / "integrity.json"
        assert manifest.exists(), "init should seed integrity.json"
        # Verify against itself should be clean (ignoring kill-switch stanza)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["algorithm"] == _integrity.MANIFEST_HASH_ALGORITHM
        assert data["files"], "manifest must record at least one file hash"


class TestIntegrityManifestRace:
    """M1 (TP-49) — ``write_manifest`` wraps the read-modify-write window
    in fcntl.flock so two concurrent ``espalier integrity refresh``
    invocations don't race. Without the lock, both compute hashes against
    a moving filesystem and last-writer-wins; with the lock, one waits
    for the other to finish.

    The torn-JSON window is closed independently by ``atomic_write_text``
    (R9 B4); this lock closes the compute-then-write race.
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_parallel_writes_produce_valid_manifest(self, tmp_path):
        """N parallel write_manifest calls. All must exit 0 and the
        resulting manifest must be a single, well-formed JSON document."""
        import concurrent.futures
        _seed_minimal_repo(tmp_path)

        cmd = [
            sys.executable, "-c",
            f"import sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(HOOKS_DIR)!r}); "
            f"import _integrity; "
            f"_integrity.write_manifest(Path({str(tmp_path)!r}))",
        ]

        def _refresh(_):
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=20, encoding="utf-8",
            )

        N = 8
        with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
            results = list(pool.map(_refresh, range(N)))

        for i, r in enumerate(results):
            assert r.returncode == 0, (
                f"worker {i} failed: stdout={r.stdout!r} stderr={r.stderr!r}"
            )

        manifest = tmp_path / ".espalier" / "integrity.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["algorithm"] == _integrity.MANIFEST_HASH_ALGORITHM
        assert data["files"], "manifest must record file hashes"

    def test_lock_file_created_under_espalier_dir(self, tmp_path):
        """The flock uses ``.espalier/.manifest.write.lock`` (sibling of
        the manifest). Verify the lock file path is correct so a future
        refactor doesn't move it outside the integrity-managed dir."""
        _seed_minimal_repo(tmp_path)
        _integrity.write_manifest(tmp_path)
        lock_file = tmp_path / ".espalier" / ".manifest.write.lock"
        if sys.platform != "win32":
            assert lock_file.exists(), (
                f"flock sentinel must exist after write_manifest; "
                f"contents of .espalier/: {list((tmp_path / '.espalier').iterdir())}"
            )


class TestVerifyReadLock:
    """TP-59 BC-036: ``load_manifest`` and ``verify_integrity`` acquire
    ``fcntl.LOCK_SH`` on ``.espalier/.manifest.write.lock`` so they
    serialize with the writer's ``LOCK_EX`` (TP-49 M1). Pre-fix, a verifier
    could read the OLD manifest, then iterate the filesystem after a
    writer's atomic rename landed -- every refreshed hash reported as a
    spurious mismatch.

    The closure here is observable rather than racy: holding LOCK_EX in
    the test must block a verify_integrity call until the lock releases.
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_read_lock_blocks_until_writer_releases(self, tmp_path):
        import fcntl
        import threading
        import time

        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)

        lock_path = tmp_path / ".espalier" / ".manifest.write.lock"
        assert lock_path.exists(), "writer should have created the lock sentinel"

        # Hold LOCK_EX from a background thread; release after a short
        # delay. The foreground verify_integrity should block for at
        # least that delay.
        hold_seconds = 0.5
        acquired = threading.Event()
        released = threading.Event()

        def _hold_exclusive():
            with open(lock_path, "a+", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                acquired.set()  # signal AFTER the lock is actually held
                time.sleep(hold_seconds)
                fcntl.flock(fh, fcntl.LOCK_UN)
                released.set()

        holder = threading.Thread(target=_hold_exclusive, daemon=True)
        holder.start()
        # Gate the timer on the writer ACTUALLY holding the lock, not a fixed
        # sleep: a bare sleep raced with thread scheduling and could start t0
        # mid-hold, undercounting the block and flaking under CI load.
        assert acquired.wait(timeout=2.0), "writer never acquired the lock"
        t0 = time.monotonic()
        ok, mismatched = _integrity.verify_integrity(tmp_path)
        elapsed = time.monotonic() - t0
        holder.join(timeout=2.0)
        assert released.is_set(), "writer thread did not release the lock"
        assert ok, f"verify should still succeed after lock acquired: {mismatched}"
        assert elapsed >= hold_seconds * 0.5, (
            f"verify_integrity returned in {elapsed:.3f}s; expected to "
            f"block ~{hold_seconds}s waiting for LOCK_SH"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_load_manifest_blocks_until_writer_releases(self, tmp_path):
        import fcntl
        import threading
        import time

        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        lock_path = tmp_path / ".espalier" / ".manifest.write.lock"

        hold_seconds = 0.4
        acquired = threading.Event()

        def _hold_exclusive():
            with open(lock_path, "a+", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                acquired.set()  # signal AFTER the lock is actually held
                time.sleep(hold_seconds)
                fcntl.flock(fh, fcntl.LOCK_UN)

        holder = threading.Thread(target=_hold_exclusive, daemon=True)
        holder.start()
        # Gate the timer on the writer ACTUALLY holding the lock (see sibling
        # test): a fixed sleep raced with scheduling and undercounted the block.
        assert acquired.wait(timeout=2.0), "writer never acquired the lock"
        t0 = time.monotonic()
        manifest = _integrity.load_manifest(tmp_path)
        elapsed = time.monotonic() - t0
        holder.join(timeout=2.0)
        assert manifest is not None
        assert elapsed >= hold_seconds * 0.5, (
            f"load_manifest returned in {elapsed:.3f}s; expected to "
            f"block ~{hold_seconds}s waiting for LOCK_SH"
        )


class TestSummarize:
    def test_summary_clean(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        state = _integrity.summarize_state(tmp_path)
        assert state["integrity_ok"] is True
        assert state["mismatched_paths"] == []
        assert state["kill_switches"] == []

    def test_summary_dirty(self, tmp_path):
        _seed_minimal_repo(tmp_path)
        _write_manifest_from_current(tmp_path)
        (tmp_path / "tools/cc/hooks/write_guard.py").write_text("changed\n", encoding="utf-8")
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.local.json").write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8"
        )
        state = _integrity.summarize_state(tmp_path)
        assert state["integrity_ok"] is False
        assert state["mismatched_paths"] != []
        assert any("disableAllHooks" in f for f in state["kill_switches"])


class TestKillSwitchScanUnreadableSettings:
    """An unreadable `.claude/` must not read as "nothing to see".

    The regression this pins was self-inflicted and subtle: fixing the
    version-gated `Path.exists()` raise by swapping in `os.path.exists` traded
    a raise for a silent `False`, which on CPython 3.10-3.13 REMOVED a signal --
    `config_guard` had been logging "config_guard: scan failed" and went quiet.
    Absent and unreadable are different answers, which is the same distinction
    `MANIFEST_ABSENT`/`MANIFEST_UNREADABLE` draws one layer down.
    """

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses the permission bit this test depends on",
    )
    def test_unreadable_settings_surface_to_reporters_but_not_to_blockers(self, tmp_path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
        os.chmod(claude, 0o000)
        try:
            if not _traversal_denied(claude / "settings.json"):
                pytest.skip("chmod did not deny traversal on this platform")
            # The two BLOCKING callers stay quiet: denying every tool call over
            # an unreadable settings file would wedge the session that repairs it.
            assert _integrity.scan_for_kill_switches(tmp_path) == []
            # Reporters opted in, so the scan must SAY it could not answer.
            opted = _integrity.scan_for_kill_switches(tmp_path, include_unreadable=True)
            assert any("unreadable" in f for f in opted), (
                "an unreadable .claude/ reported as nothing-to-see; the "
                "anti-self-disable floor lost its only signal on that path"
            )
        finally:
            os.chmod(claude, 0o755)

    def test_a_genuinely_absent_settings_file_stays_silent(self, tmp_path):
        """Negative control: the discrimination must not turn absence into noise."""
        assert _integrity.scan_for_kill_switches(tmp_path, include_unreadable=True) == []
