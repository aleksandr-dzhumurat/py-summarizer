#!/usr/bin/env bash
set -euo pipefail

SKILL_SRC="src/py_summarizer"
SKILL_DST="$HOME/.claude/skills/py-summarizer"

mkdir -p ~/.claude/skills/
cp -r "$SKILL_SRC" "$SKILL_DST"

echo "Installed: $SKILL_DST"
echo "Restart Claude Code to load the skill."
