#!/usr/bin/env bash
set -euo pipefail

# Install Claude Code Gemini advisory skills.
#
# This script copies slash commands into the project's .claude/commands/
# directory so they are available as /gemini-review, /gemini-error-analysis,
# /gemini-design-checkpoint, and /pitfall-notebook inside Claude Code.
#
# Usage:
#   ./scripts/install.sh [--project-dir <path>]
#
# If --project-dir is not provided, the script installs into the current
# working directory's .claude/commands/.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_CODE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMMANDS_SRC="$CLAUDE_CODE_DIR/commands"
SKILLS_DIR="$CLAUDE_CODE_DIR/skills"

# Parse arguments.
PROJECT_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$PROJECT_DIR" ]]; then
    PROJECT_DIR="$(pwd)"
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
TARGET_COMMANDS="$PROJECT_DIR/.claude/commands"

echo "Installing Claude Code Gemini skills..."
echo "  Source:  $COMMANDS_SRC"
echo "  Target:  $TARGET_COMMANDS"
echo "  Skills:  $SKILLS_DIR"
echo ""

# Create target directories.
mkdir -p "$TARGET_COMMANDS"

# Copy slash command files.
COMMANDS_INSTALLED=0
for cmd_file in "$COMMANDS_SRC"/*.md; do
    if [[ ! -f "$cmd_file" ]]; then
        continue
    fi
    cmd_name="$(basename "$cmd_file")"
    cp "$cmd_file" "$TARGET_COMMANDS/$cmd_name"
    echo "  Installed command: /$( echo "$cmd_name" | sed 's/\.md$//' )"
    COMMANDS_INSTALLED=$((COMMANDS_INSTALLED + 1))
done

if [[ $COMMANDS_INSTALLED -eq 0 ]]; then
    echo "  No command files found in $COMMANDS_SRC" >&2
    exit 1
fi

# Resolve the skills directory path for use in commands.
# Replace $AGENT_SKILLS_DIR placeholder in installed commands with the actual path.
AGENT_SKILLS_PARENT="$(cd "$CLAUDE_CODE_DIR/../.." && pwd)"
for installed_cmd in "$TARGET_COMMANDS"/*.md; do
    if [[ ! -f "$installed_cmd" ]]; then
        continue
    fi
    if grep -q '\$AGENT_SKILLS_DIR' "$installed_cmd" 2>/dev/null; then
        tmp_file="$(mktemp)"
        sed "s|\\\$AGENT_SKILLS_DIR|$AGENT_SKILLS_PARENT|g" "$installed_cmd" > "$tmp_file"
        mv "$tmp_file" "$installed_cmd"
    fi
done

echo ""
echo "Done. Installed $COMMANDS_INSTALLED slash commands."
echo ""
echo "Available commands:"
echo "  /gemini-review              - Advisory code review via Gemini CLI"
echo "  /gemini-error-analysis      - Debugging second opinion via Gemini CLI"
echo "  /gemini-design-checkpoint   - Design critique via Gemini CLI"
echo "  /codex-review               - Advisory code review via Codex CLI"
echo "  /codex-error-analysis       - Debugging second opinion via Codex CLI"
echo "  /codex-design-checkpoint    - Design critique via Codex CLI"
echo "  /pitfall-notebook           - Per-project pitfall memory"
echo ""
echo "Prerequisites:"
echo "  - Gemini CLI installed and available in PATH (for Gemini skills)"
echo "  - Codex CLI installed and available in PATH (for Codex skills)"
echo "  - Python 3.10+"
echo ""
echo "Environment variables (optional):"
echo "  CLAUDE_GEMINI_MODEL              Override Gemini model (default: gemini-3.1-pro-preview)"
echo "  CLAUDE_GEMINI_RUN_MODE           Runner mode: interactive or headless"
echo "  CLAUDE_GEMINI_SESSION_TTL_SECONDS  Session reuse TTL (default: 21600)"
echo "  CLAUDE_CODEX_MODEL               Override Codex model (default: gpt-5.4)"
