#!/usr/bin/env bash
# Espalier-Harness session launcher with interactive mode prompts.
#
# Dev-only maintainer tool. Not installed by adopters (scripts/ is not
# packaged in the wheel/sdist); kept in-tree for harness self-maintenance.
#
# Four yes/no prompts (defaults in brackets) configure how Claude Code
# starts for this repo. The first asks whether you are a self-host
# operator and EXITS on its default; the next three each default to off:
#
#   ESPALIER_MAINTENANCE_MODE=1      → write_guard skips protected-zone
#                                      checks; plan_guard short-circuits;
#                                      stop_gate skips Gates 2 and 3.
#   ESPALIER_STOP_GATE=full          → stop_gate runs Gate 1 (pytest)
#                                      before the hygiene gates.
#   --dangerously-skip-permissions   → Claude Code skips per-tool
#                                      permission prompts.
#
# Notes
#   - Env vars MUST be set before launch - hook subprocesses inherit
#     env at Claude Code launch time, not mid-session.
#   - This script is for self-host operators editing the harness itself.
#     Consumers running `espalier init` in their own repos rarely need
#     maintenance mode.
#   - Answer y to the first prompt (Enter there exits, by design). Every
#     later default is off, so Enter through the rest launches a PLAIN
#     session; the self-edit profile is y to prompts 1, 2 and 4. The full
#     stop gate (prompt 3) stays opt-in, as CLAUDE.md pins it.

set -euo pipefail

prompt_yn() {
    # $1: question, $2: default ("y" or "n")
    local question="$1"
    local default="$2"
    local hint ans
    if [ "$default" = "y" ]; then
        hint="[Y/n]"
    else
        hint="[y/N]"
    fi
    read -r -p "$question $hint " ans
    [ -z "$ans" ] && ans="$default"
    case "$ans" in
        [yY]*) return 0 ;;
        *) return 1 ;;
    esac
}

env_args=()
cli_args=()

if ! prompt_yn "This script is for self-host operators editing the harness itself. Are you a self-host operator?" n; then
    echo
    echo "Adopters: run 'claude' directly. This launcher is not for you." >&2
    echo "It offers two settings that weaken governance (maintenance mode +" >&2
    echo "skip permission prompts) - appropriate only when editing Espalier" >&2
    echo "itself, never when applying it to your own repo." >&2
    exit 1
fi

if prompt_yn "Maintenance mode (skip protected-zone + plan gates)?" n; then
    env_args+=("ESPALIER_MAINTENANCE_MODE=1")
fi

if prompt_yn "Full stop gate (run pytest on Stop)?" n; then
    env_args+=("ESPALIER_STOP_GATE=full")
fi

if prompt_yn "Skip permission prompts (--dangerously-skip-permissions)?" n; then
    cli_args+=("--dangerously-skip-permissions")
fi

echo
echo "Launching: ${env_args[*]:+${env_args[*]} }claude${cli_args[*]:+ ${cli_args[*]}}"
echo

if [ ${#env_args[@]} -gt 0 ]; then
    exec env "${env_args[@]}" claude ${cli_args[@]+"${cli_args[@]}"}
else
    exec claude ${cli_args[@]+"${cli_args[@]}"}
fi
