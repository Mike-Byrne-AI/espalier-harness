"""TP-28: ``detect_ml_surface`` must still fire on real ML repos.

Pins the recall side of the TP-28 multi-signal rewrite — the
tightening from single-substring matching to multi-signal scoring
must not over-tighten and silently miss real ML projects. Each
fixture mirrors a documented ML project shape (PyTorch trainer,
HF Transformers fine-tune, etc.) and asserts
``ml_surface=True``. Without this guard, a future scorer tweak
could regress recall to zero and adopters of ML repos would
silently get the generic Python profile instead of the ML-aware
agent roster.
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


def _write_binary(tmp_path: Path, rel: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\x01\x02")


class TestRealMLRepos:
    def test_pytorch_minimal(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "mymodel"\n'
                'dependencies = ["torch>=2.0", "transformers"]\n'
            ),
            "train.py": "import torch\n",
        })
        assert detect_ml_surface(tmp_path) is True

    def test_huggingface_with_notebooks(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "hf-fine"\n'
                'dependencies = ["transformers", "datasets", "accelerate"]\n'
            ),
            "notebooks/finetune.ipynb": '{"cells": []}',
        })
        assert detect_ml_surface(tmp_path) is True

    def test_tensorflow_with_checkpoint(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "tfmodel"\n'
                'dependencies = ["tensorflow"]\n'
            ),
        })
        _write_binary(tmp_path, "checkpoints/best.h5")
        assert detect_ml_surface(tmp_path) is True

    def test_pytorch_lightning_full_shape(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "lit"\n'
                'dependencies = ["pytorch-lightning", "torch"]\n'
            ),
            "train.py": "import lightning\n",
            "training_config.yaml": "lr: 1e-3\n",
        })
        # 4 signals hit; threshold is 2
        assert detect_ml_surface(tmp_path) is True

    def test_minimum_threshold_two_signals(self, tmp_path):
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "lit"\n'
                'dependencies = ["torch"]\n'
            ),
            "train.py": "import torch\n",
        })
        assert detect_ml_surface(tmp_path) is True

    def test_one_signal_does_not_fire(self, tmp_path):
        # `train.py` exists but no ML dep — single signal
        _write_repo(tmp_path, {
            "pyproject.toml": (
                '[project]\nname = "scripts"\n'
                'dependencies = ["click"]\n'
            ),
            "train.py": "# train a CLI tool\nimport click\n",
        })
        assert detect_ml_surface(tmp_path) is False
