"""Every generic system fires off the self-host repo -- the class test.

This module pins the class rule: **an identity gate that withholds content the
tree has is a defect.** One init'd Node tree per module (``tests/_adopter_tree`` drives a real
``init``, whose deploy source is the vendored mirror of ``tools/cc/``), and each
un-gated feature is driven on it the way an adopter meets it -- the deployed hook
as a subprocess with ``ESPALIER_*`` stripped and ``CLAUDE_PROJECT_DIR`` set,
``cmd_scan`` on the tree, the deployed command bodies read back -- and fires;
and no self-host-scoped row reaches it.

Each assertion names its mutation, driven red at landing (2026-10-08): restore
the single gated registry call in ``post_write_check._check`` and the loosening
text vanishes; give ``NEW_TEST_FILE_RULE`` ``scope="any"`` and a harness path
reaches the tree; restore ``if self_host:`` around the banner index and the
titles vanish; put ``encoding_contracts`` back in ``SELF_HOST_ONLY_SCANNERS`` and
the report reads ``ran: false``; drop the exempt prefixes ``_gated`` hands it and
a ``tools/cc/`` finding appears; restore the fixed review list and the adopter
branch vanishes from the deployed bodies.
"""
# slow-exempt: one init'd tree per module (about 5 s) and seven deployed-hook subprocesses, measured 2026-10-08
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from espalier import cli

# Text an any-tree row must never carry: the paths and names only the harness's
# own tree has. The new-test-file pointer names the first two, and fires on the
# harness tree for the same payload the first test below sends.
_HARNESS_TOKENS = (
    "tests/conftest.py", "_MARKER_RULES", "tools/cc/", "espalier/",
    "examples/dogfooding", "scripts/sync_",
)


def _hook_env(tree: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER_")}
    env["CLAUDE_PROJECT_DIR"] = str(tree)
    env.pop("FORCE_COLOR", None)
    return env


def _run_hook(tree: Path, script: str, payload: dict) -> str:
    """The deployed hook as Claude Code runs it; its additionalContext, or ''."""
    proc = subprocess.run(
        [sys.executable, str(tree / "tools" / "cc" / "hooks" / script)],
        input=json.dumps(payload).encode("utf-8"), capture_output=True,
        cwd=str(tree), env=_hook_env(tree), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")[-400:]
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def _post_tool_use(tree: Path, tool_name: str, tool_input: dict) -> dict:
    return {
        "session_id": "class-test", "hook_event_name": "PostToolUse", "cwd": str(tree),
        "tool_name": tool_name, "tool_input": tool_input,
        "tool_response": {"success": True},
    }


def _edit(tree: Path, rel: str, new: str) -> dict:
    return _post_tool_use(tree, "Edit", {
        "file_path": str(tree / rel), "old_string": "x", "new_string": new,
    })


def _deployed_probe(tree: Path, body: str) -> str:
    """Run ``body`` in a child interpreter with the DEPLOYED hooks on its path:
    the deployed modules share their names with the live ones other tests
    import, so they are never imported into this process."""
    hooks = tree / "tools" / "cc" / "hooks"
    proc = subprocess.run(
        [sys.executable, "-c", f"import sys\nsys.path.insert(0, {str(hooks)!r})\n" + body],
        capture_output=True, text=True, encoding="utf-8", cwd=str(tree), env=_hook_env(tree),
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    return proc.stdout


@pytest.fixture(scope="module")
def node_tree(tmp_path_factory) -> Path:
    tree = build_adopter_tree(tmp_path_factory.mktemp("generic-systems"), stack="node")
    (tree / "tests").mkdir(exist_ok=True)
    (tree / "tests" / "test_widget.py").write_text(
        "def test_widget():\n    assert True\n", encoding="utf-8",
    )
    return tree


class TestTheAdvisoryRowsFireOffSelfHost:
    """1-A: the two ``scope="any"`` rows reach the adopter; no self-host row does."""

    def test_a_pytest_skip_edit_yields_the_loosening_text_and_no_harness_path(self, node_tree):
        text = _run_hook(node_tree, "post_write_check.py", _edit(
            node_tree, "tests/test_widget.py",
            "@pytest.mark.skip\ndef test_widget():\n    assert True\n",
        ))
        assert "skip/xfail marker" in text, text
        # The new-test-file pointer fires for this same payload on the harness tree
        # (an untracked tests/ file) and names tests/conftest.py::_MARKER_RULES. It
        # keeps the default scope and must not reach here.
        assert not any(token in text for token in _HARNESS_TOKENS), text

    def test_a_git_archive_command_yields_the_artifact_proxy_text(self, node_tree):
        text = _run_hook(node_tree, "post_write_check.py", _post_tool_use(
            node_tree, "Bash", {"command": "git archive --format=tar HEAD | tar -t"},
        ))
        assert "`git archive` reads the git INDEX" in text, text
        assert not any(token in text for token in _HARNESS_TOKENS), text

    def test_the_adopters_own_command_body_write_yields_nothing(self, node_tree):
        body = node_tree / ".claude" / "commands" / "deploy.md"
        body.write_text(
            "---\ndescription: deploy the site\n---\n\nRun `npm run deploy`.\n", encoding="utf-8",
        )
        text = _run_hook(node_tree, "post_write_check.py", _post_tool_use(
            node_tree, "Write",
            {"file_path": str(body), "content": body.read_text(encoding="utf-8")},
        ))
        assert text == "", text   # the command-sync rows name mirrors this tree lacks

    def test_no_any_row_names_a_harness_path(self, node_tree):
        """The negative half of the class rule, on the deployed registry: a row
        offered on every tree carries no text about the harness's own tree."""
        out = _deployed_probe(node_tree, (
            "import inspect, json\n"
            "import _reinject\n"
            "print(json.dumps({r.id: inspect.getsource(r.render) for r in _reinject.REINJECTS_ANY}))\n"
        ))
        sources = json.loads(out)
        assert sources, "no any-tree row in the deployed registry"
        for rid, src in sources.items():
            assert not any(token in src for token in _HARNESS_TOKENS), rid

    def test_the_bridge_carries_no_content_row(self, node_tree):
        """A Bash heredoc that wrote a skip marker into tests/: nothing through the
        hook on this tree, and no loosening text from the bridge even when it is
        offered the whole registry -- its synthesized payload carries no content,
        which is why its invocation keeps the tree-identity gate."""
        target = node_tree / "tests" / "test_bridge.py"
        target.write_text(
            "import pytest\n\n@pytest.mark.skip\ndef test_b():\n    assert True\n", encoding="utf-8",
        )
        cmd = (
            "cat <<'EOF' > tests/test_bridge.py\nimport pytest\n\n"
            "@pytest.mark.skip\ndef test_b():\n    assert True\nEOF"
        )
        text = _run_hook(node_tree, "post_write_check.py", _post_tool_use(node_tree, "Bash", {"command": cmd}))
        assert text == "", text
        out = _deployed_probe(node_tree, (
            "import json, pathlib\n"
            "import post_write_check as pwc, _reinject\n"
            f"root = pathlib.Path({str(node_tree)!r})\n"
            f"rows = pwc._bash_derived_payloads({{'command': {cmd!r}}}, root, already=0,\n"
            "                                  rules=_reinject.REINJECTS)\n"
            f"any_rows = pwc._bash_derived_payloads({{'command': {cmd!r}}}, root, already=0,\n"
            "                                      rules=_reinject.REINJECTS_ANY)\n"
            "print(json.dumps([rows, any_rows]))\n"
        ))
        rows, any_rows = json.loads(out)
        assert not any("skip/xfail marker" in row for row in rows), rows
        # Registry-derived, not one string: offered every any-tree row, the
        # bridge yields nothing. A future any-row that reads the written file
        # from disk (`_reinject._written_text`) reds here and revisits the gate.
        assert any_rows == [], any_rows


class TestTheBannerCarriesTheAdoptersPrinciples:
    """1-B: the standing-principles index gates on the file, as /recall does."""

    def test_the_startup_banner_lists_the_adopters_titles(self, node_tree):
        docs = node_tree / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "STANDING_PRINCIPLES.md").write_text(
            "# Standing principles\n\n## 1. One writer per file\n\nbody\n\n"
            "## 2. Measure before you tune\n\nbody\n",
            encoding="utf-8",
        )
        banner = _run_hook(node_tree, "session_start.py", {
            "session_id": "class-test-banner", "hook_event_name": "SessionStart",
            "source": "startup", "cwd": str(node_tree),
        })
        assert "STANDING PRINCIPLES" in banner, banner[:800]
        assert "- 1. One writer per file" in banner and "- 2. Measure before you tune" in banner


class TestTheEncodingScannerRunsBounded:
    """2-A: encoding_contracts runs on the adopter's tree and leaves the deployed hooks out."""

    def test_scan_reports_the_adopters_locale_read_and_not_the_hooks(self, node_tree):
        (node_tree / "src" / "tool.py").write_text(
            "def load(p):\n    return open(p).read()\n", encoding="utf-8",
        )
        # A locale read planted under the deployed prefix: the walk's boundary,
        # not a claim about what init deploys (the hooks are encoding-clean).
        planted = node_tree / "tools" / "cc" / "hooks" / "zz_boundary_probe.py"
        planted.write_text(
            "from pathlib import Path\n"
            "# encoding-locale-ok: a deployed hook's own pragma, never the adopter's corpus\n"
            "y = Path('g').read_text(encoding='ascii')\n"
            "def load(p):\n    return open(p).read()\n",
            encoding="utf-8",
        )
        try:
            assert cli.cmd_scan(argparse.Namespace(repo=str(node_tree))) == 0
        finally:
            planted.unlink()
        reports = node_tree / "reports"
        ec = json.loads((reports / "scan_encoding_contracts.json").read_text(encoding="utf-8"))
        assert ec.get("ran", True) is True and ec["count"] >= 1, ec
        paths = [f["path"] for f in ec["findings"]]
        assert "src/tool.py" in paths, paths
        assert not [p for p in paths if p.startswith("tools/cc/")], paths
        summary = json.loads((reports / "scan_summary.json").read_text(encoding="utf-8"))
        assert "encoding_contracts" not in summary["not_run"], summary["not_run"]
        overrides = json.loads((reports / "scan_overrides.json").read_text(encoding="utf-8"))
        corpus = [o["path"] for o in overrides["overrides"] if o["scanner"] == "encoding_contracts"]
        assert not [p for p in corpus if p.startswith("tools/cc/")], corpus


class TestTheReviewSurfaceNamesTheAdoptersSource:
    """3-A: the deployed ship-boundary bodies carry the adopter branch."""

    @pytest.mark.parametrize("name", ["implement-task.md", "preflight.md", "implement-pack.md"])
    def test_each_deployed_ship_boundary_body_names_the_adopter_branch(self, node_tree, name):
        text = (node_tree / ".claude" / "commands" / name).read_text(encoding="utf-8")
        assert "primary_paths" in text and "harness_config.json" in text, name
        # The self-host branch stays beside it.
        assert "`bench/`, `scripts/`," in " ".join(text.split()), name
