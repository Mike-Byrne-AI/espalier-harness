#!/usr/bin/env bash
# espalier baseline — full friction layer.
#
# Runs `python3 -m espalier.cli init <target>` from the repo root, which
# deploys the twelve hook scripts and a wired-up settings.json. Then
# `espalier integrity refresh` so kill-switch detection is active.
#
# Usage: setup.sh <target_dir>

set -euo pipefail

TARGET="${1:?usage: setup.sh <target_dir>}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

mkdir -p "$TARGET"
cd "$REPO_ROOT"
# `espalier init` requires a git repo; the bench tempdir is fresh, so
# initialize it here before init runs.
git init -q "$TARGET"
python3 -m espalier.cli init "$TARGET" >/dev/null
python3 -m espalier.cli integrity refresh "$TARGET" >/dev/null

echo "[espalier] init + integrity refresh completed in $TARGET"
