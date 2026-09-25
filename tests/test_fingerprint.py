"""Tests for ``espalier.analyze.fingerprint_repo`` — the
language/framework/convention classifier that drives profile
selection and downstream harness configuration.

Pins per-language detection invariants (Python API surface, Node +
npm, ML stack, garbage-file filtering) plus the non-Python
repo widening. Without this contract a regex tweak in the
fingerprint scanner could silently mis-classify a repo's primary
language, cascading into wrong test-command suggestions, wrong
conventions detection, and a profile mismatch the user only notices
when something obviously visible breaks downstream.
"""
from __future__ import annotations


class TestFingerprint:
    def test_python_detection(self, python_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(python_repo)
        assert set(fp.languages) == {"python"}
        assert fp.api_surface is True
        assert "pytest -q" in fp.test_commands

    def test_node_detection(self, node_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(node_repo)
        assert set(fp.languages) == {"javascript"}
        assert set(fp.package_systems) == {"node"}
        assert "npm test" in fp.test_commands

    def test_ml_detection(self, ml_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(ml_repo)
        assert fp.ml_surface is True
        assert set(fp.languages) == {"python"}

    def test_garbage_detection(self, tmp_path):
        from espalier.analyze import fingerprint_repo
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / "junk.txt").write_text("SUMMARY OF LESS COMMANDS\nmore junk\n", encoding="utf-8")
        fp = fingerprint_repo(tmp_path)
        assert "junk.txt" in fp.garbage_files

    def test_conventions_detected(self, python_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(python_repo)
        # assert each signal independently. The previous OR
        # was permanently satisfied by 'layout' (the src/ fixture always
        # populates it), so a regression in tests/ or commands detection
        # stayed invisible. All three are populated by the python_repo
        # fixture (src/, tests/, [tool.ruff]).
        assert "layout" in fp.conventions, fp.conventions.keys()
        assert "tests" in fp.conventions, fp.conventions.keys()
        assert "commands" in fp.conventions, fp.conventions.keys()


class TestNonPythonFingerprints:
    """confirm non-Python repos detect correct primary language + test_cmd."""

    def test_typescript_primary_detection(self, typescript_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(typescript_repo)
        assert fp.languages[0] == "typescript"
        assert "node" in fp.package_systems
        assert "npm test" in fp.test_commands

    def test_go_primary_detection(self, go_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(go_repo)
        assert fp.languages[0] == "go"
        assert "go" in fp.package_systems
        assert any("go test" in cmd for cmd in fp.test_commands)

    def test_polyglot_primary_selection(self, polyglot_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(polyglot_repo)
        assert fp.languages[0] == "python"
        assert "typescript" in fp.languages
        assert "pytest -q" in fp.test_commands


class TestProfiles:
    def test_python_api_classified(self, python_repo):
        from espalier.analyze import fingerprint_repo
        from espalier.profiles import classify_repo
        fp = fingerprint_repo(python_repo)
        profiles, scores = classify_repo(fp)
        assert any("python" in p for p in profiles)

    def test_ml_classified(self, ml_repo):
        from espalier.analyze import fingerprint_repo
        from espalier.profiles import classify_repo
        fp = fingerprint_repo(ml_repo)
        profiles, scores = classify_repo(fp)
        assert "ml_repo" in profiles


class TestFingerprintArchitectureAndProfiles:
    def test_fingerprint_includes_architecture_field(self, tmp_path):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(tmp_path)
        assert isinstance(fp.architecture, dict)
        assert "pattern" in fp.architecture
        assert "layers" in fp.architecture

    def test_fingerprint_includes_profiles_field(self, tmp_path):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(tmp_path)
        assert isinstance(fp.profiles, list)
        assert len(fp.profiles) >= 1

    def test_harness_layered_detected_in_fingerprint(self, tmp_path):
        from espalier.analyze import fingerprint_repo
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "espalier" / "scanners").mkdir()
        fp = fingerprint_repo(tmp_path)
        assert fp.architecture["pattern"] == "harness_layered"

    def test_to_dict_includes_architecture_and_profiles(self, tmp_path):
        import json
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(tmp_path)
        data = fp.to_dict()
        assert "architecture" in data
        assert "profiles" in data
        json.dumps(data)  # must be serialisable

    def test_profiles_non_empty_for_python_repo(self, python_repo):
        from espalier.analyze import fingerprint_repo
        fp = fingerprint_repo(python_repo)
        assert len(fp.profiles) >= 1
        assert any("python" in p for p in fp.profiles)
