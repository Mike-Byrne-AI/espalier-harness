#!/usr/bin/env bash
# espalier baseline — full friction layer.
#
# Runs `espalier.cli init <target>` from the repo root, which deploys the
# twelve hook scripts and a wired-up settings.json. Then
# `espalier integrity refresh` so kill-switch detection is active. The
# interpreter is the one the runner hands over (ESPALIER_BENCH_PYTHON,
# bench/run_benchmark.py::setup_baseline), else `python3` for a run by hand:
# a python-only Windows install has no `python3`.
#
# Usage: setup.sh <target_dir>

set -euo pipefail

TARGET="${1:?usage: setup.sh <target_dir>}"
PYTHON="${ESPALIER_BENCH_PYTHON:-python3}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

mkdir -p "$TARGET"
cd "$REPO_ROOT"
# `espalier init` requires a git repo; the bench tempdir is fresh, so
# initialize it here before init runs.
git init -q "$TARGET"
"$PYTHON" -m espalier.cli init "$TARGET" >/dev/null
"$PYTHON" -m espalier.cli integrity refresh "$TARGET" >/dev/null

echo "[espalier] init + integrity refresh completed in $TARGET"
