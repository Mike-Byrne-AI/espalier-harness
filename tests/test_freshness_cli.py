"""Tests for ``espalier freshness {check,pin,unpin}`` (TP-56-A).

End-to-end CLI behavior via build_parser dispatch. Each test
constructs an isolated tmp git repo with a doc fragment, exercises
the CLI, and asserts the manifest + stdout/stderr behavior.
"""
from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), *args],
        check=True, capture_output=True,
    )


def _init_with_fragment(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    doc = repo / "docs" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "# x\n\n"
        "<!-- espalier:fragment id=foo bound=a.py "
        "policy=numeric-contract -->\n"
        "claim line\n",
        encoding="utf-8",
    )
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True, capture_output=True,
    )
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _run_cli(*argv: str) -> tuple[int, str, str]:
    from espalier.cli import build_parser
    parser = build_parser()
    ns = parser.parse_args(list(argv))
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = ns.func(ns)
    return rc, out.getvalue(), err.getvalue()


class TestFreshnessCli:
    def test_check_emits_per_fragment_state_on_stdout(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, out, _ = _run_cli("freshness", "check", str(repo))
        assert rc == 0
        assert "foo" in out
        assert "unpinned" in out
        assert "Fragments:" in out

    def test_check_json_flag_emits_structured_output(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, out, _ = _run_cli("freshness", "check", str(repo), "--json")
        assert rc == 0
        payload = json.loads(out)
        assert "counts" in payload
        assert "fragments" in payload
        assert payload["fragments"][0]["id"] == "foo"

    def test_changed_files_without_critical_only_warns(
        self, tmp_path: Path
    ) -> None:
        """TP-176 W5-3: --changed-files only scopes the exit decision when
        paired with --critical-only; passed alone it is silently ignored and
        the gate stays repo-wide, so the command must warn."""
        repo = _init_with_fragment(tmp_path)
        _rc, _out, err = _run_cli(
            "freshness", "check", str(repo), "--changed-files", "a.py",
        )
        assert "--changed-files is only applied" in err

    def test_changed_files_with_critical_only_does_not_warn(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        _rc, _out, err = _run_cli(
            "freshness", "check", str(repo),
            "--changed-files", "a.py", "--critical-only",
        )
        assert "--changed-files is only applied" not in err

    def test_pin_records_current_bound_paths_with_sha(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, _, _ = _run_cli(
            "freshness", "pin", "foo", str(repo),
            "--expected-value", "10",
        )
        assert rc == 0
        manifest_path = repo / ".espalier" / "freshness.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["fragments"]["foo"]
        assert entry["bound"] == ["a.py"]
        assert entry["expected_value"] == 10
        assert entry["last_verified_sha"]
        assert entry["policy"] == "numeric-contract"

    def test_pin_over_a_latin1_manifest_is_refused_cleanly_and_leaves_it_intact(
        self, tmp_path: Path
    ) -> None:
        """Ledger DEF-829. The pin command reads the manifest twice: the write
        path (``freshness._load_manifest_for_write``) refuses a non-UTF-8 file
        with its typed error, and the cli's own read of the prior expected
        values sat under an ``(OSError, JSONDecodeError)`` tuple that could
        not catch ``UnicodeDecodeError`` (a ``ValueError``). The typed refusal
        comes first, so the reachable behavior is this: a code-page re-save
        is refused in one sentence and the file is left as it was. The cli
        handler now names ValueError so the belt matches the braces; its
        structural red is ``tests/test_contracts.py::TestTextReadsDecodeGuarded``."""
        repo = _init_with_fragment(tmp_path)
        manifest_path = repo / ".espalier" / "freshness.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        raw = b'{"fragments": {"old": {"note": "caf\xe9"}}}'
        manifest_path.write_bytes(raw)
        rc, _, err = _run_cli(
            "freshness", "pin", "foo", str(repo),
            "--expected-value", "10",
        )
        assert rc == 1
        assert "not readable UTF-8 JSON" in err
        assert manifest_path.read_bytes() == raw

    def test_pin_then_check_yields_fresh(
        self, tmp_path: Path
    ) -> None:
        """TP-324: assert the fragment actually reports ``fresh``.

        Pre-fix this asserted only ``rc == 0`` on both commands -- but an
        unpinned or stale fragment also exits 0 on a non-critical check, so
        stubbing ``cmd_freshness_pin`` to a no-op ``return 0`` left pin->fresh
        broken and this test green. The ``--json`` payload carries the state,
        so parse it.
        """
        repo = _init_with_fragment(tmp_path)
        # Fixture invariant: before the pin the fragment is NOT fresh, so the
        # post-pin assert below cannot pass on a pre-existing state.
        _rc0, out0, _ = _run_cli("freshness", "check", str(repo), "--json")
        assert json.loads(out0)["fragments"][0]["state"] == "unpinned"

        rc, _, _ = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 0
        rc2, out2, _ = _run_cli("freshness", "check", str(repo), "--json")
        assert rc2 == 0
        # THE named effect: the pin made the fragment fresh.
        payload = json.loads(out2)
        assert payload["counts"]["fresh"] == 1, (
            f"pin should yield exactly one fresh fragment; got {payload['counts']!r}"
        )
        assert payload["fragments"][0]["id"] == "foo"
        assert payload["fragments"][0]["state"] == "fresh"

    def test_unpin_removes_manifest_entry(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        _run_cli("freshness", "pin", "foo", str(repo))
        rc, _, _ = _run_cli("freshness", "unpin", "foo", str(repo))
        assert rc == 0
        manifest = json.loads(
            (repo / ".espalier" / "freshness.json").read_text(
                encoding="utf-8"
            )
        )
        assert "foo" not in manifest["fragments"]

    def test_unpin_missing_id_returns_nonzero(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, _, err = _run_cli("freshness", "unpin", "ghost", str(repo))
        assert rc == 1
        assert "No manifest entry" in err

    def test_critical_only_filters_output(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, out, _ = _run_cli(
            "freshness", "check", str(repo), "--critical-only", "--json",
        )
        payload = json.loads(out)
        assert payload["fragments"] == []
        assert rc == 0

    def test_check_returns_2_when_any_fragment_critical(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        doc = repo / "docs" / "x.md"
        doc.write_text(
            "# x\n\n"
            "<!-- espalier:fragment id=foo bound=a.py "
            "policy=not-a-real-policy -->\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "bad policy")
        rc, _, _ = _run_cli("freshness", "check", str(repo), "--json")
        assert rc == 2


class TestBulkPinAll:
    """TP-56-C Sub-task 1-E: ``espalier freshness pin --all``.

    The CLI's positional layout is ``fragment_id repo`` (both
    optional). When ``--all`` is set the operator typically runs
    inside the target repo and omits both positionals; these tests
    feed the args directly to ``cmd_freshness_pin`` to bypass the
    positional ambiguity.
    """

    def test_pin_all_writes_entries_for_every_discovered_fragment(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        doc = repo / "docs" / "x.md"
        doc.write_text(
            "# x\n\n"
            "<!-- espalier:fragment id=foo bound=a.py "
            "policy=numeric-contract -->\n"
            "<!-- espalier:fragment id=bar bound=a.py "
            "policy=verify-on-touch -->\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "two")
        ns = argparse.Namespace(
            fragment_id=None, repo=str(repo),
            all=True, expected_value=None,
        )
        with redirect_stdout(io.StringIO()) as out_buf, \
             redirect_stderr(io.StringIO()):
            rc = cmd_freshness_pin(ns)
        assert rc == 0
        payload = json.loads(out_buf.getvalue())
        assert payload["count"] == 2
        assert sorted(payload["pinned_all"]) == ["bar", "foo"]

    def test_pin_with_no_id_and_no_all_emits_usage(self, tmp_path: Path) -> None:
        """TP-174b R36: `freshness pin` with no fragment id and no --all must
        emit an actionable usage message and rc=1, not the confusing
        "pin failed: fragment id None not found ..." (which leaks the literal
        None into the error)."""
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns = argparse.Namespace(
            fragment_id=None, repo=str(repo),
            all=False, expected_value=None, force=False,
        )
        with redirect_stdout(io.StringIO()), \
             redirect_stderr(io.StringIO()) as err_buf:
            rc = cmd_freshness_pin(ns)
        assert rc == 1
        err = err_buf.getvalue().lower()
        assert "usage" in err and "no fragment id" in err
        assert "not found" not in err  # the leaked-None path must not be reached

    def test_pin_all_preserves_existing_expected_value(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns_first = argparse.Namespace(
            fragment_id="foo", repo=str(repo),
            all=False, expected_value="42",
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert cmd_freshness_pin(ns_first) == 0
        ns_all = argparse.Namespace(
            fragment_id=None, repo=str(repo),
            all=True, expected_value=None,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert cmd_freshness_pin(ns_all) == 0
        manifest = json.loads(
            (repo / ".espalier" / "freshness.json")
            .read_text(encoding="utf-8")
        )
        assert manifest["fragments"]["foo"]["expected_value"] == 42

    def test_pin_all_rejects_expected_value_combo(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns = argparse.Namespace(
            fragment_id=None, repo=str(repo),
            all=True, expected_value="10",
        )
        with redirect_stdout(io.StringIO()), \
             redirect_stderr(io.StringIO()) as err_buf:
            rc = cmd_freshness_pin(ns)
        assert rc == 1
        assert "mutually exclusive" in err_buf.getvalue()


class TestPinForceRebindingDefense:
    """BC-040 pin-time defense (TP-56-D follow-up).

    Mirrors the scan-side rebinding-attempt critical at the pin
    call site so an operator who runs ``pin`` or ``pin --all`` to
    clear a critical finding sees the bound diff first.
    """

    def _rebind_fragment(self, repo: Path, new_bound: str) -> None:
        doc = repo / "docs" / "x.md"
        doc.write_text(
            "# x\n\n"
            f"<!-- espalier:fragment id=foo bound={new_bound} "
            "policy=numeric-contract -->\n"
            "claim line\n",
            encoding="utf-8",
        )
        (repo / new_bound).write_text("y = 1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "redirect")

    def test_single_pin_without_force_returns_nonzero_on_rebind(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns_first = argparse.Namespace(
            fragment_id="foo", repo=str(repo),
            all=False, expected_value=None, force=False,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert cmd_freshness_pin(ns_first) == 0
        self._rebind_fragment(repo, "b.py")
        ns_retry = argparse.Namespace(
            fragment_id="foo", repo=str(repo),
            all=False, expected_value=None, force=False,
        )
        with redirect_stdout(io.StringIO()), \
             redirect_stderr(io.StringIO()) as err_buf:
            rc = cmd_freshness_pin(ns_retry)
        assert rc == 1
        err = err_buf.getvalue()
        assert "pin failed" in err
        assert "--force" in err

    def test_single_pin_with_force_consents_to_rebind(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns_first = argparse.Namespace(
            fragment_id="foo", repo=str(repo),
            all=False, expected_value=None, force=False,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert cmd_freshness_pin(ns_first) == 0
        self._rebind_fragment(repo, "b.py")
        ns_force = argparse.Namespace(
            fragment_id="foo", repo=str(repo),
            all=False, expected_value=None, force=True,
        )
        with redirect_stdout(io.StringIO()) as out_buf, \
             redirect_stderr(io.StringIO()):
            assert cmd_freshness_pin(ns_force) == 0
        payload = json.loads(out_buf.getvalue())
        assert payload["entry"]["bound"] == ["b.py"]

    def test_pin_all_skips_drift_and_returns_nonzero(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns_first = argparse.Namespace(
            fragment_id="foo", repo=str(repo),
            all=False, expected_value=None, force=False,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert cmd_freshness_pin(ns_first) == 0
        self._rebind_fragment(repo, "b.py")
        ns_all = argparse.Namespace(
            fragment_id=None, repo=str(repo),
            all=True, expected_value=None, force=False,
        )
        with redirect_stdout(io.StringIO()) as out_buf, \
             redirect_stderr(io.StringIO()):
            rc = cmd_freshness_pin(ns_all)
        assert rc == 1
        payload = json.loads(out_buf.getvalue())
        assert payload["skipped_count"] == 1
        assert payload["skipped"][0]["id"] == "foo"
        assert payload["count"] == 0

    def test_pin_all_with_force_is_rejected(
        self, tmp_path: Path
    ) -> None:
        import argparse
        from espalier.cli import cmd_freshness_pin
        repo = _init_with_fragment(tmp_path)
        ns = argparse.Namespace(
            fragment_id=None, repo=str(repo),
            all=True, expected_value=None, force=True,
        )
        with redirect_stdout(io.StringIO()), \
             redirect_stderr(io.StringIO()) as err_buf:
            rc = cmd_freshness_pin(ns)
        assert rc == 1
        assert "mutually exclusive" in err_buf.getvalue()
        assert "--force" in err_buf.getvalue()


class TestNoLiteralOnAVerifyOnTouchPin:
    def test_expected_value_is_refused_for_a_verify_on_touch_fragment(
        self, tmp_path: Path
    ) -> None:
        """A recorded literal on a verify-on-touch pin is the fourth copy of a
        number a test derives, and `pin --all` carried it forever once written.
        The pin refuses it and names the policy."""
        repo = _init_with_fragment(tmp_path)
        doc = repo / "docs" / "x.md"
        doc.write_text(
            doc.read_text(encoding="utf-8").replace("policy=numeric-contract", "policy=verify-on-touch"),
            encoding="utf-8",
        )
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "5")
        assert rc == 1
        assert "expected_value" in err and "verify-on-touch" in err
        manifest = repo / ".espalier" / "freshness.json"
        assert not manifest.is_file() or "foo" not in json.loads(
            manifest.read_text(encoding="utf-8")
        ).get("fragments", {})
        rc, _out, _err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 0


class TestCohortAdvisoryReachesTheJsonPath:
    def test_check_json_carries_the_advisory_key(self, tmp_path: Path) -> None:
        """The machine readers (state cache, audit) consume `--json`; a cohort
        advisory that only the text path printed was invisible to them."""
        repo = _init_with_fragment(tmp_path)
        rc, _out, _err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0
        rc, out, _err = _run_cli("freshness", "check", str(repo), "--json")
        assert rc == 0
        payload = json.loads(out)
        assert "advisory" in payload
        assert payload["advisory"] is None  # one fragment cannot be a cohort


class TestPinRefusesABoundWithUncommittedChanges:
    """Ledger row DEF-702. A pin records HEAD as the point where the claim was
    verified; when a bound path carries uncommitted changes, HEAD is not the
    tree the operator looked at, and the manifest would vouch for a
    verification that never happened (driven 2026-09-06: a count fragment
    pinned at 47 against a HEAD where the answer was 46, and ``check`` read
    ``fresh`` because drift is counted in commits). The pin refuses without
    ``--force`` and names the paths; ``--all`` skips such fragments the way it
    skips a rebind."""

    def test_a_pin_over_a_modified_bound_is_refused_and_names_the_path(self, tmp_path: Path) -> None:
        repo = _init_with_fragment(tmp_path)
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "2")
        assert rc == 1, err
        assert "uncommitted" in err and "a.py" in err and "--force" in err, err
        manifest = repo / ".espalier" / "freshness.json"
        assert not manifest.is_file() or "foo" not in json.loads(
            manifest.read_text(encoding="utf-8")
        ).get("fragments", {})

    def test_force_records_the_pin_over_a_modified_bound(self, tmp_path: Path) -> None:
        repo = _init_with_fragment(tmp_path)
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        rc, out, err = _run_cli(
            "freshness", "pin", "foo", str(repo), "--expected-value", "2", "--force",
        )
        assert rc == 0, err
        assert json.loads(out)["entry"]["expected_value"] == 2

    def test_a_clean_bound_pins_without_force(self, tmp_path: Path) -> None:
        repo = _init_with_fragment(tmp_path)
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "bump")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "2")
        assert rc == 0, err

    def test_pin_all_skips_a_modified_bound_and_reports_it(self, tmp_path: Path) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        rc, out, _err = _run_cli("freshness", "pin", "--all", str(repo))
        assert rc == 1, out
        payload = json.loads(out)
        assert payload["pinned_all"] == []
        assert [s["id"] for s in payload["skipped"]] == ["foo"]
        assert "uncommitted" in payload["skipped"][0]["reason"]

    def test_pin_all_with_a_repo_path_pins_that_repo_not_the_cwd(self, tmp_path: Path) -> None:
        # The optional fragment-id positional swallows the repo path after
        # ``--all``; the bulk pass used to run on the current directory (this
        # test's first cut re-pinned the self-host manifest).
        repo = _init_with_fragment(tmp_path)
        rc, out, err = _run_cli("freshness", "pin", "--all", str(repo))
        assert rc == 0, err
        assert json.loads(out)["pinned_all"] == ["foo"]
        assert (repo / ".espalier" / "freshness.json").is_file()

    def test_pin_all_with_a_fragment_id_is_a_usage_error(self, tmp_path: Path) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "--all", "foo", str(repo))
        assert rc == 1
        assert "--all takes no fragment id" in err, err

    def test_pin_all_refuses_a_literal_edited_by_hand_on_a_tree_that_commits_its_manifest(
        self, tmp_path: Path
    ) -> None:
        # The bulk pass read the on-disk literal and pinned it at a new HEAD as
        # verified -- laundering a hand edit the scan had just flagged.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        manifest = repo / ".espalier" / "freshness.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["fragments"]["foo"]["expected_value"] = 2
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rc, out, err = _run_cli("freshness", "pin", "--all", str(repo))
        assert rc == 1, out
        payload = json.loads(out)
        assert payload["pinned_all"] == [] and payload["count"] == 0
        assert [s["id"] for s in payload["skipped"]] == ["foo"]
        assert "edited by hand" in payload["skipped"][0]["reason"]
        assert "--expected-value" in payload["skipped"][0]["reason"]
        assert "nothing was pinned" in err
        assert json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]["expected_value"] == 2

    def test_pin_all_refuses_before_pinning_so_a_cohort_keeps_one_clock(self, tmp_path: Path) -> None:
        # Two fragments, one dirty bound: neither is pinned (a partial pass
        # would split the cohort's clock), and the remedy is one --all can take.
        repo = _init_with_fragment(tmp_path)
        doc = repo / "docs" / "x.md"
        doc.write_text(
            doc.read_text(encoding="utf-8")
            + "\n<!-- espalier:fragment id=bar bound=b.py policy=verify-on-touch -->\nclaim two\n",
            encoding="utf-8",
        )
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "two fragments")
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        rc, out, err = _run_cli("freshness", "pin", "--all", str(repo))
        assert rc == 1, out
        payload = json.loads(out)
        assert payload["pinned_all"] == []
        assert [s["id"] for s in payload["skipped"]] == ["foo"]
        assert "--force" not in payload["skipped"][0]["reason"].replace("on its own with --force", "")
        assert "commit the bound first" in payload["skipped"][0]["reason"]
        assert not (repo / ".espalier" / "freshness.json").exists()

    def test_the_hand_edit_check_stands_down_and_says_so_where_the_manifest_is_ignored(
        self, tmp_path: Path
    ) -> None:
        # The adopter shape: init gitignores .espalier/, so the manifest is
        # never at HEAD and a hand-edited literal cannot be told from a pin.
        # The scan reads it fresh (honestly: it cannot know) and check says
        # the check is off.
        repo = _init_with_fragment(tmp_path)
        (repo / ".gitignore").write_text(".espalier/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "ignore the manifest")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        manifest = repo / ".espalier" / "freshness.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["fragments"]["foo"]["expected_value"] = 2
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rc, out, _err = _run_cli("freshness", "check", str(repo), "--json")
        assert rc == 0
        payload = json.loads(out)
        assert payload["fragments"][0]["state"] == "fresh"
        assert "not tracked at HEAD" in (payload["literal_check"] or "")
        rc, out, _err = _run_cli("freshness", "check", str(repo))
        assert "not tracked at HEAD" in out

    def test_pin_all_with_an_empty_path_is_a_usage_error_not_the_cwd(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # ``pin --all "$UNSET"``: an empty string is a directory to ``Path``
        # (it resolves to the cwd), the shape the REPO positional's own type
        # refuses. The cwd is a scratch repo here so a regression re-pins
        # that, never the tree this test file sits in.
        repo = _init_with_fragment(tmp_path)
        monkeypatch.chdir(repo)
        rc, _out, err = _run_cli("freshness", "pin", "--all", "")
        assert rc == 1, err
        assert "--all takes no fragment id" in err, err
        assert not (repo / ".espalier" / "freshness.json").exists()

    def test_an_edit_outside_a_bound_symbol_does_not_refuse_the_pin(self, tmp_path: Path) -> None:
        repo = _init_with_fragment(tmp_path)
        doc = repo / "docs" / "x.md"
        doc.write_text(
            doc.read_text(encoding="utf-8").replace("bound=a.py ", "bound=a.py::x "),
            encoding="utf-8",
        )
        (repo / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "symbol bound")
        (repo / "a.py").write_text("x = 1\ny = 3\n", encoding="utf-8")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err


class TestASingleRePinCarriesTheLiteral:
    """A re-pin without ``--expected-value`` refreshes the clock, not the
    number. ``pin --all`` harvested the on-disk literal back into the entry;
    the single-fragment path passed ``None`` and the engine, rebuilding the
    entry, wrote none -- ff9eaff (2026-09-19) re-pinned ``hook-count`` one
    fragment at a time and dropped its ``12``, and the tree's one
    numeric-contract fragment read ``fresh`` with no literal to hold it to
    (the pre-cut review's D1). The carry now lives in ``pin_fragment`` under
    ``carried_literal``'s rules, and these rows drive them through the CLI:
    the literal is carried across a bound nothing touched since the pin that
    verified it; a literal edited by hand (where the manifest is committed),
    a bound that moved, or a marker rebound under ``--force`` is refused and
    the number restated; a policy that no longer takes a literal retires it;
    an explicit flag still wins; and the first pin, which has nothing to
    carry, says so.
    """

    def test_a_re_pin_without_the_flag_carries_the_existing_literal(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "42")
        assert rc == 0, err
        manifest = repo / ".espalier" / "freshness.json"
        first = json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]
        # A commit off the bound moves HEAD, so the re-pin has a new SHA to
        # record and the manifest it re-reads is the committed one.
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "move HEAD off the bound")
        rc, out, err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 0, err
        entry = json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]
        assert entry["expected_value"] == 42
        assert entry["last_verified_sha"] != first["last_verified_sha"]
        assert json.loads(out)["entry"]["expected_value"] == 42

    def test_a_re_pin_refuses_to_carry_a_literal_edited_by_hand(
        self, tmp_path: Path
    ) -> None:
        # The same refusal --all runs (:538): a literal that differs from
        # HEAD's beside an unchanged pin is a hand edit, and carrying it
        # would stamp it verified at a new SHA. The remedy names the flag.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        manifest = repo / ".espalier" / "freshness.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["fragments"]["foo"]["expected_value"] = 2
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rc, out, err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 1, out
        assert "edited by hand" in err, err
        assert "--expected-value" in err, err
        after = json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]
        assert after["expected_value"] == 2
        assert after["last_verified_sha"] == data["fragments"]["foo"]["last_verified_sha"]

    def test_force_does_not_launder_a_hand_edited_literal(
        self, tmp_path: Path
    ) -> None:
        # --force consents to a rebind or a dirty bound; a hand-edited number
        # is restated on the command line or not stamped at all.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        manifest = repo / ".espalier" / "freshness.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["fragments"]["foo"]["expected_value"] = 2
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--force")
        assert rc == 1, err
        assert "edited by hand" in err, err
        assert json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]["expected_value"] == 2

    def test_an_explicit_flag_still_replaces_the_carried_literal(
        self, tmp_path: Path
    ) -> None:
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "42")
        assert rc == 0, err
        rc, out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "43")
        assert rc == 0, err
        manifest = repo / ".espalier" / "freshness.json"
        assert json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]["expected_value"] == 43
        assert json.loads(out)["entry"]["expected_value"] == 43

    def test_the_carry_reads_the_on_disk_literal_where_the_manifest_is_ignored(
        self, tmp_path: Path
    ) -> None:
        # The adopter shape: init gitignores .espalier/, so there is no HEAD
        # copy to tell a hand edit from a pin. The check stands down (as it
        # does for check and for --all) and the carry takes the on-disk value.
        repo = _init_with_fragment(tmp_path)
        (repo / ".gitignore").write_text(".espalier/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "ignore the manifest")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        manifest = repo / ".espalier" / "freshness.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["fragments"]["foo"]["expected_value"] = 2
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 0, err
        assert json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]["expected_value"] == 2

    def test_a_re_pin_refuses_to_carry_across_a_bound_that_moved(
        self, tmp_path: Path
    ) -> None:
        # The literal was verified against the bound at the pin's SHA. A
        # commit that touched the bound since may have moved the number, and
        # carrying it would stamp an unread number verified at a new SHA --
        # the shape the dirty-bound refusal exists for, reached by a re-pin
        # (the red team's finding on the first cut of this fix).
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        manifest = repo / ".espalier" / "freshness.json"
        before = json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "the bound moved")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 1, err
        assert "touched its bound" in err, err
        assert "--expected-value" in err, err
        assert json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"] == before
        rc, out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "2")
        assert rc == 0, err
        assert json.loads(out)["entry"]["expected_value"] == 2

    def test_a_forced_rebind_without_the_flag_refuses_to_carry(
        self, tmp_path: Path
    ) -> None:
        # --force consents to the rebind; it does not consent to carrying a
        # number verified against the OLD bound onto the new one.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        doc = repo / "docs" / "x.md"
        doc.write_text(
            doc.read_text(encoding="utf-8").replace("bound=a.py ", "bound=b.py "),
            encoding="utf-8",
        )
        (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "rebound")
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--force")
        assert rc == 1, err
        assert "marker now claims" in err, err
        assert "--expected-value" in err, err
        manifest = repo / ".espalier" / "freshness.json"
        assert json.loads(manifest.read_text(encoding="utf-8"))["fragments"]["foo"]["bound"] == ["a.py"]
        rc, out, err = _run_cli(
            "freshness", "pin", "foo", str(repo), "--force", "--expected-value", "1",
        )
        assert rc == 0, err
        entry = json.loads(out)["entry"]
        assert entry["bound"] == ["b.py"] and entry["expected_value"] == 1

    def test_a_policy_flip_retires_the_literal_on_the_next_bare_pin(
        self, tmp_path: Path
    ) -> None:
        # docs/FRESHNESS.md prescribes the flip (a count a test derives belongs
        # under verify-on-touch). The stale literal retires with the policy;
        # the first cut of this fix carried it into the engine's "takes no
        # expected_value" refusal, a dead end for an operator who passed none.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        doc = repo / "docs" / "x.md"
        doc.write_text(
            doc.read_text(encoding="utf-8").replace("policy=numeric-contract", "policy=verify-on-touch"),
            encoding="utf-8",
        )
        _git(repo, "commit", "-q", "-am", "the count is derived by a test now")
        rc, out, err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 0, err
        entry = json.loads(out)["entry"]
        assert entry["policy"] == "verify-on-touch"
        assert "expected_value" not in entry

    def test_a_first_numeric_pin_without_a_literal_says_so(
        self, tmp_path: Path
    ) -> None:
        # Nothing to carry on a first pin, and the policy then holds no
        # number: allowed (every numeric-contract fragment on the harness's
        # own tree was seeded this way), but no longer silent.
        repo = _init_with_fragment(tmp_path)
        rc, out, err = _run_cli("freshness", "pin", "foo", str(repo))
        assert rc == 0, err
        assert "expected_value" not in json.loads(out)["entry"]
        assert "no expected_value" in err, err
        assert "--expected-value" in err, err

    def test_unpin_names_the_literal_it_discards(self, tmp_path: Path) -> None:
        # The rebind refusal's own remedy is unpin-then-pin; the next pin has
        # nothing to carry, so unpin says what went with the entry.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "7")
        assert rc == 0, err
        rc, out, err = _run_cli("freshness", "unpin", "foo", str(repo))
        assert rc == 0, err
        assert "Removed manifest entry for foo" in out
        assert "expected_value 7" in out, out
        assert "--expected-value" in out, out

    def test_pin_all_refuses_before_pinning_a_literal_whose_bound_moved(
        self, tmp_path: Path
    ) -> None:
        # The bulk pass shares carried_literal with the single pin: a literal
        # it cannot carry is refused in the pre-flight, nothing is pinned,
        # and the remedy is the one fragment pinned on its own with the flag.
        repo = _init_with_fragment(tmp_path)
        rc, _out, err = _run_cli("freshness", "pin", "foo", str(repo), "--expected-value", "1")
        assert rc == 0, err
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        _git(repo, "commit", "-q", "-m", "pin")
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "the bound moved")
        rc, out, err = _run_cli("freshness", "pin", "--all", str(repo))
        assert rc == 1, out
        payload = json.loads(out)
        assert payload["pinned_all"] == [] and payload["count"] == 0
        assert [s["id"] for s in payload["skipped"]] == ["foo"]
        assert "touched its bound" in payload["skipped"][0]["reason"]
        assert "--expected-value" in payload["skipped"][0]["reason"]
        assert "nothing was pinned" in err
