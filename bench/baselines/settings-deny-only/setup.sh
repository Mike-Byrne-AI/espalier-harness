#!/usr/bin/env bash
# settings-deny-only baseline — Claude Code's native permission system, alone.
#
# Installs a .claude/settings.json with permissions.deny patterns matching
# espalier's protected files, but no hook scripts. Shows what the native
# permission engine catches without behavioural code.
#
# Usage: setup.sh <target_dir>

set -euo pipefail

TARGET="${1:?usage: setup.sh <target_dir>}"
mkdir -p "$TARGET/.claude"
cat > "$TARGET/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "deny": [
      "Write(.espalier/integrity.json)",
      "Write(.espalier/freshness.json)",
      "Write(.claude/settings.json)",
      "Write(.claude/settings.local.json)",
      "Write(.github/workflows/harness-guard.yml)",
      "Write(tools/cc/hooks/config_guard.py)",
      "Write(tools/cc/hooks/plan_guard.py)",
      "Write(tools/cc/hooks/post_compact.py)",
      "Write(tools/cc/hooks/post_write_check.py)",
      "Write(tools/cc/hooks/reflect_trigger.py)",
      "Write(tools/cc/hooks/session_start.py)",
      "Write(tools/cc/hooks/stop_gate.py)",
      "Write(tools/cc/hooks/task_router.py)",
      "Write(tools/cc/hooks/write_guard.py)",
      "Edit(.espalier/integrity.json)",
      "Edit(.espalier/freshness.json)",
      "Edit(.claude/settings.json)",
      "Edit(.claude/settings.local.json)",
      "Edit(.github/workflows/harness-guard.yml)",
      "Edit(tools/cc/hooks/config_guard.py)",
      "Edit(tools/cc/hooks/plan_guard.py)",
      "Edit(tools/cc/hooks/post_compact.py)",
      "Edit(tools/cc/hooks/post_write_check.py)",
      "Edit(tools/cc/hooks/reflect_trigger.py)",
      "Edit(tools/cc/hooks/session_start.py)",
      "Edit(tools/cc/hooks/stop_gate.py)",
      "Edit(tools/cc/hooks/task_router.py)",
      "Edit(tools/cc/hooks/write_guard.py)"
    ]
  }
}
JSON

echo "[settings-deny-only] installed deny-only settings.json into $TARGET"
