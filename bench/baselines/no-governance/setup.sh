#!/usr/bin/env bash
# no-governance baseline — establishes the floor.
#
# Installs an empty .claude/settings.json with no hooks and no permissions.deny
# rules. This is what an unconfigured Claude Code project looks like.
#
# Usage: setup.sh <target_dir>

set -euo pipefail

TARGET="${1:?usage: setup.sh <target_dir>}"
mkdir -p "$TARGET/.claude"
cat > "$TARGET/.claude/settings.json" <<'JSON'
{}
JSON

echo "[no-governance] installed empty settings.json into $TARGET"
