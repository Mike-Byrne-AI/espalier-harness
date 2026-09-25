"""TP-28: detect_ml_surface must not fire on non-ML repos.

The v0.6.0 detector fired on three classes of framework-shaped repo:
1. Django/SQLAlchemy/FastAPI: a `models/` directory by name alone
2. Documentation repos: a `notebooks/` directory without any `.ipynb`
3. Prose substring: the word "model" or "dataset" in pyproject prose

This test parametrizes on all three so they can't drift back.
"""
from __future__ import annotations

from pathlib import Path

from espalier.analyze import detect_ml_surface


def _write_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


class TestDjangoShape:
    def test_models_directory_alone_does_not_fire(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": '[project]\nname = "shop"\n'
                              'dependencies = ["django>=4", "fastapi"]\n',
            "models/__init__.py": "",
            "models/user.py": "from django.db import models\n"
                              "class User(models.Model):\n    pass\n",
            "models/order.py": "class Order: pass\n",
        })
        assert detect_ml_surface(tmp_path) is False

    def test_sqlalchemy_models_with_dataset_fixture(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": '[project]\nname = "api"\n'
                              'dependencies = ["sqlalchemy", "alembic"]\n',
            "models/__init__.py": "",
            "tests/dataset.py": "FIXTURE_USERS = [...]\n",
        })
        assert detect_ml_surface(tmp_path) is False


class TestNotebooksEmpty:
    def test_notebooks_dir_without_ipynb(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": '[project]\nname = "docs"\n',
            "notebooks/README.md": "# Tutorial notebooks\n",
            "notebooks/intro.md": "...\n",
        })
        assert detect_ml_surface(tmp_path) is False


class TestProseSubstring:
    def test_pyproject_marker_description_with_model(self, tmp_path):
        # Mirrors the espalier-harness self-host case: "model" in a
        # pytest marker description string fired the v0.6.0 detector.
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "myproj"\n'
                'dependencies = ["pytest", "click"]\n'
                "\n"
                '[tool.pytest.ini_options]\n'
                'markers = [\n'
                '  "unit: pure function/model tests; no subprocess",\n'
                '  "training: hardpack loop integration tests",\n'
                ']\n'
            ),
        })
        assert detect_ml_surface(tmp_path) is False

    def test_fastapi_user_model_description(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "shop"\n'
                'description = "FastAPI app with a User model and dataset endpoints"\n'
                'dependencies = ["fastapi", "pydantic"]\n'
            ),
        })
        assert detect_ml_surface(tmp_path) is False
