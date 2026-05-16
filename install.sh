#!/usr/bin/env bash
set -euo pipefail

SKILL_SRC="src/py_summarizer"
SKILL_DST="$HOME/.claude/skills/py_summarizer"

mkdir -p ~/.claude/skills/
rm -rf "$SKILL_DST"
cp -r "$SKILL_SRC" "$SKILL_DST"

echo "Installed: $SKILL_DST"
echo "Restart Claude Code to load the skill."
