"""Pin the encoding-contracts scanner's behavioural contract (DEF-792).

Earn-the-gate (every documented shape detected in the positives fixture, with
the exact count, and the historically caught and historically missed shapes
named), must-NOT-trip (zero findings on the negatives corpus), parity with the
older subprocess-only contract on a synthetic tree (the scanner sees at least
what ``TestSubprocessEncodingPinned`` sees, aliases included), the walk's
prunes and its BOM and skipped-file accounting, the live tree at zero, and the
pragma registry pinned both ways: capped, and every honored pragma still
sitting above a site that would otherwise fire (a dead pragma reds). The last
is the "named self-expiring allow-list" the row asks for.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from espalier.scanners import encoding_contracts as ec

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_encoding_stealth_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_encoding_stealth_negatives.py"

_BAD = "from pathlib import Path\nx = Path('f').read_text()\n"


def _function_span(path: Path, name: str) -> range:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return range(node.lineno, (node.end_lineno or node.lineno) + 1)
    raise AssertionError(f"{path.name} has no function {name!r}")


def _hits_in(findings, path: Path, name: str) -> list[tuple[str, str]]:
    span = _function_span(path, name)
    return [(f.shape, f.severity) for f in findings if f.lineno in span]


class TestEarnTheGate:
    def test_earn_the_gate_detects_every_fixture_shape(self) -> None:
        """One finding per planted site, exactly: dropping any detection branch
        (a shape, a slot, a severity) goes red on the count, not silently."""
        findings = list(ec._scan_file(FIXTURE_PATH, REPO_ROOT))
        assert len(findings) == 23, [(f.lineno, f.shape, f.severity) for f in findings]
        shapes: dict[str, int] = {}
        for f in findings:
            shapes[f.shape] = shapes.get(f.shape, 0) + 1
        assert shapes == {
            "open": 7, "read_text": 4, "write_text": 2, "subprocess": 8,
            "tempfile": 1, "TextIOWrapper": 1,
        }, shapes
        severities: dict[str, int] = {}
        for f in findings:
            severities[f.severity] = severities.get(f.severity, 0) + 1
        # The severity is load-bearing: a relabel that keeps the count but
        # empties NOT_UTF8 defangs the value check (SOUND-3) and reds here.
        assert severities == {ec.SEVERITY_MISSING: 17, ec.SEVERITY_NOT_UTF8: 6}, severities
        assert all(f.path == FIXTURE_PATH.relative_to(REPO_ROOT) for f in findings)
        assert all("utf-8" in f.explanation for f in findings)

    def test_earn_the_gate_flags_the_historically_caught_and_missed_shapes(self) -> None:
        """The row's proof: before the net widens, it must catch the sites the
        two older gates already caught -- and the shapes the first cut of this
        scanner could not see, named by the two reviews of 2026-09-14."""
        findings = list(ec._scan_file(FIXTURE_PATH, REPO_ROOT))
        assert _hits_in(findings, FIXTURE_PATH, "historic_git_conventions") == [("subprocess", ec.SEVERITY_MISSING)]
        assert _hits_in(findings, FIXTURE_PATH, "historic_contract_offenders") == [
            ("subprocess", ec.SEVERITY_NOT_UTF8), ("subprocess", ec.SEVERITY_NOT_UTF8),
        ]
        assert _hits_in(findings, FIXTURE_PATH, "aliased_module") == [("subprocess", ec.SEVERITY_MISSING)]
        assert _hits_in(findings, FIXTURE_PATH, "aliased_function") == [("subprocess", ec.SEVERITY_MISSING)]
        assert _hits_in(findings, FIXTURE_PATH, "production_path_open") == [("open", ec.SEVERITY_MISSING)]
        assert _hits_in(findings, FIXTURE_PATH, "shape_read_text_positional_wrong") == [("read_text", ec.SEVERITY_NOT_UTF8)]
        assert _hits_in(findings, FIXTURE_PATH, "shape_write_text_positional_none") == [("write_text", ec.SEVERITY_NOT_UTF8)]


class TestDoesNotTrip:
    def test_does_not_trip_on_negatives(self) -> None:
        findings = list(ec._scan_file(NEG_FIXTURE_PATH, REPO_ROOT))
        assert findings == [], [(f.lineno, f.shape, f.severity) for f in findings]

    def test_the_negatives_corpus_is_not_vacuous(self) -> None:
        """The negatives file must actually carry the tempting shapes -- an
        emptied corpus would pass the silence test for free."""
        source = NEG_FIXTURE_PATH.read_text(encoding="utf-8")
        for token in ('"rb"', '"wb"', "utf-8-sig", "**kw", "os.open(", "tarfile.open(",
                      "gzip.open(", "import subprocess as sp", "from subprocess import run",
                      'p.open("rb")', 'read_text("utf-8")', "NamedTemporaryFile(suffix",
                      "encoding-locale-ok:"):
            assert token in source, token

    @pytest.mark.parametrize("spelling", ["utf-8", "UTF-8", "utf8", "UTF8", "utf_8", "utf-8-sig", "UTF-8-SIG"])
    def test_utf8_spellings_are_pinned(self, spelling: str) -> None:
        assert ec.pins_utf8(ast.Constant(value=spelling)) is True

    @pytest.mark.parametrize("spelling", ["latin-1", "cp1252", "ascii", "utf-16", ""])
    def test_other_codecs_are_not_utf8(self, spelling: str) -> None:
        assert ec.pins_utf8(ast.Constant(value=spelling)) is False

    def test_none_and_non_string_literals_are_not_utf8(self) -> None:
        assert ec.pins_utf8(ast.Constant(value=None)) is False
        assert ec.pins_utf8(ast.Constant(value=1)) is False
        assert ec.pins_utf8(None) is False

    def test_a_dynamic_encoding_is_unjudged(self) -> None:
        assert ec.pins_utf8(ast.Name(id="enc", ctx=ast.Load())) is None


class TestParityWithTheSubprocessContract:
    _SOURCE = (
        "import subprocess\n"
        "def a(argv):\n"
        "    subprocess.run(argv, text=True)\n"
        "    subprocess.run(argv, text=True, encoding='utf-8')\n"
        "    subprocess.check_output(argv, universal_newlines=True)\n"
        "    subprocess.Popen(argv, text=True, encoding=None)\n"
        "    subprocess.call(argv, text=True, encoding='latin-1')\n"
        "    subprocess.check_call(argv, text=True, encoding=codec)\n"
        "    subprocess.run(argv, capture_output=True)\n"
        "    subprocess.run(argv, text=False)\n"
    )

    def test_scanner_sees_every_site_the_older_contract_sees(self, tmp_path: Path) -> None:
        """``TestSubprocessEncodingPinned`` (tests/test_contracts.py) is the
        subprocess-shape net on production code. On a synthetic file carrying
        every subprocess shape it judges, the scanner's subprocess findings are
        the same line set -- so widening to files and tests lost nothing."""
        from tests.test_contracts import _text_subprocess_calls_missing_encoding

        target = tmp_path / "synthetic.py"
        target.write_text(self._SOURCE, encoding="utf-8")
        older = {lineno for lineno, _func in _text_subprocess_calls_missing_encoding("synthetic.py", self._SOURCE)}
        scanner = {f.lineno for f in ec._scan_file(target, tmp_path) if f.shape == "subprocess"}
        assert older == {3, 5, 6, 7}, older  # the older net's own verdict, pinned
        assert scanner == older, (scanner, older)

    def test_an_alias_the_older_contract_forbids_is_seen_here(self, tmp_path: Path) -> None:
        """The older net bans the alias in production; tests use it, so the
        scanner resolves it instead. The verdict per line is unchanged."""
        aliased = self._SOURCE.replace("import subprocess\n", "import subprocess as sp\n").replace("subprocess.", "sp.")
        target = tmp_path / "aliased.py"
        target.write_text(aliased, encoding="utf-8")
        scanner = {f.lineno for f in ec._scan_file(target, tmp_path) if f.shape == "subprocess"}
        assert scanner == {3, 5, 6, 7}, scanner
        by_name = (
            "from subprocess import run, check_output as co\n"
            "def a(argv):\n"
            "    run(argv, text=True)\n"
            "    co(argv, text=True, encoding='utf-8')\n"
            "    co(argv, universal_newlines=True)\n"
        )
        target.write_text(by_name, encoding="utf-8")
        assert {f.lineno for f in ec._scan_file(target, tmp_path)} == {3, 5}


class TestTheWalk:
    def test_live_tree_has_no_locale_following_io(self) -> None:
        """The class sweep pinned every site (DEF-792, 2026-09-14). A new one
        reds here with its path, line and shape; a file the scan could not
        read or parse reds too, because a silent skip is not a pass."""
        findings, skipped = ec.scan_repo_with_skips(REPO_ROOT)
        assert findings == [], "\n".join(
            f"{f.path}:{f.lineno} {f.shape} {f.severity}" for f in findings
        )
        assert skipped == [], skipped

    def test_walk_covers_the_hook_tree_tests_and_the_transformed_mirror_and_skips_the_rest(self) -> None:
        """The scanner exists for tools/cc/ and tests/: a prune that hid either
        (the family-1 ``cc`` prune, a widened exemption) would pass the zero
        test above for free. The selfcheck mirror is a shipped TRANSFORM, not a
        byte copy, so it is walked; the cc byte-mirror is not."""
        rels = {rel for _path, rel in ec._iter_scoped_files(REPO_ROOT)}
        assert any(r.startswith("tools/cc/hooks/") for r in rels), sorted(rels)[:5]
        assert any(r.startswith("tests/test_") for r in rels)
        assert any(r.startswith("espalier/_vendor/selfcheck_tests/") for r in rels)
        assert any(r.startswith("espalier/") and "/_vendor/" not in r for r in rels)
        assert not any(r.startswith(("tests/fixtures/", "espalier/_vendor/cc/", "espalier/assets/", "task-packs/")) for r in rels)
        assert not any("/.venv/" in r or r.startswith(".venv/") for r in rels)

    def test_exempt_prefixes_cover_own_fixtures_within_cap(self) -> None:
        assert "tests/fixtures/" in ec.EXEMPT_PREFIXES
        assert len(ec.EXEMPT_PREFIXES) <= ec.MAX_EXEMPT_PREFIXES

    def test_nested_repo_named_tool_dirs_and_any_venv_are_pruned(self, tmp_path: Path) -> None:
        """A venv is pruned by the ``pyvenv.cfg`` it carries, whatever it is
        named; the tool trees .gitignore anticipates are pruned by name."""
        (tmp_path / "own.py").write_text(_BAD, encoding="utf-8")
        for d in (".venv", "env", ".tox/py313/lib", "htmlcov", "site-packages"):
            (tmp_path / d).mkdir(parents=True)
            (tmp_path / d / "site.py").write_text(_BAD, encoding="utf-8")
        (tmp_path / "myvirtualenv311").mkdir()
        (tmp_path / "myvirtualenv311" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
        (tmp_path / "myvirtualenv311" / "third.py").write_text(_BAD, encoding="utf-8")
        (tmp_path / "vendored" / ".git").mkdir(parents=True)
        (tmp_path / "vendored" / "theirs.py").write_text(_BAD, encoding="utf-8")
        flagged = {str(f.path).replace("\\", "/") for f in ec.scan_repo(tmp_path)}
        assert flagged == {"own.py"}, flagged

    def test_a_bom_file_is_read_and_a_broken_file_is_reported_not_skipped(self, tmp_path: Path) -> None:
        """A UTF-8 BOM is what a Windows editor writes; CPython runs such a
        module, so it is live code and the scanner must see through the mark.
        A file it cannot parse is a reported gap, never a silent pass."""
        (tmp_path / "bommed.py").write_bytes(b"\xef\xbb\xbf" + _BAD.encode("utf-8"))
        (tmp_path / "broken.py").write_text("def f(:\n", encoding="utf-8")
        (tmp_path / "latin.py").write_bytes("x = '\xe9'\n".encode("latin-1"))
        findings, skipped = ec.scan_repo_with_skips(tmp_path)
        assert [(str(f.path), f.shape) for f in findings] == [("bommed.py", "read_text")]
        assert sorted(s["file"] for s in skipped) == ["broken.py", "latin.py"], skipped
        assert all(s["reason"].startswith(("unreadable", "unparseable")) for s in skipped)
        report = ec.build_report(tmp_path)
        assert report["count"] == 1 and len(report["skipped"]) == 2

    def test_build_report_shape(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("open('f').read()\n", encoding="utf-8")
        report = ec.build_report(tmp_path)
        assert report["count"] == 1 and report["skipped"] == []
        (finding,) = report["findings"]
        assert set(finding) == {"path", "line", "shape", "severity", "explanation"}
        assert finding["path"] == "m.py" and finding["line"] == 1 and finding["shape"] == "open"


class TestPragmaRegistryIsTheAllowList:
    def test_pragma_count_within_cap(self) -> None:
        actual = ec.count_pragmas(REPO_ROOT)
        assert actual <= ec.MAX_PRAGMA_COUNT, (
            f"{actual} encoding-locale-ok pragmas exceed MAX_PRAGMA_COUNT "
            f"({ec.MAX_PRAGMA_COUNT}). Pin encoding=\"utf-8\" at the site, or raise "
            "the cap in encoding_contracts.py with a written reason."
        )

    def test_collect_and_count_agree(self) -> None:
        assert len(ec.collect_pragmas(REPO_ROOT)) == ec.count_pragmas(REPO_ROOT)

    def test_every_pragma_is_live(self) -> None:
        """Self-expiry: a pragma must sit directly above a call that would fire
        without it. A site later pinned to UTF-8 leaves its pragma dead, and a
        dead entry reds here so the allow-list cannot outlive its reason."""
        dead: list[str] = []
        for rec in ec.collect_pragmas(REPO_ROOT):
            source = ec._read_source(REPO_ROOT / rec["path"])
            below = {lineno for lineno, _shape, _sev in ec.sites_in_source(source)}
            if rec["line"] + 1 not in below:
                dead.append(f"{rec['path']}:{rec['line']} ({rec['reason'][:60]})")
        assert not dead, "dead encoding-locale-ok pragma(s) -- remove them:\n  " + "\n  ".join(dead)

    def test_pragma_is_honored_only_on_the_line_above(self, tmp_path: Path) -> None:
        """An inline trailing comment is not a pragma (the ^# anchor), and a
        pragma two lines up exempts nothing."""
        src = (
            "from pathlib import Path\n"
            "p = Path('f')\n"
            "a = p.read_text()  # encoding-locale-ok: inline comments are not honored\n"
            "# encoding-locale-ok: this pragma is two lines above the call\n"
            "\n"
            "b = p.read_text()\n"
            "# encoding-locale-ok: directly above, so this one is honored\n"
            "c = p.read_text()\n"
        )
        target = tmp_path / "m.py"
        target.write_text(src, encoding="utf-8")
        flagged = sorted(f.lineno for f in ec._scan_file(target, tmp_path))
        assert flagged == [3, 6], flagged
        # The inline comment is not a pragma at all (the ^# anchor), so the cap
        # counter and the exemption reader agree: two pragmas, one honored.
        assert ec.count_pragmas(tmp_path) == 2

    def test_pragma_regex_needs_a_reason(self) -> None:
        assert ec._pragma_in_line("# encoding-locale-ok: a reason twelve chars long")
        assert not ec._pragma_in_line("# encoding-locale-ok:")
        assert not ec._pragma_in_line("# encoding-locale-ok: short")
        assert not ec._pragma_in_line("x = 1  # encoding-locale-ok: a reason twelve chars long")
