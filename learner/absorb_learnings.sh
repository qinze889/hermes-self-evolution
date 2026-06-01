#!/usr/bin/env bash
# Output structured summary of new learnings since last run.
# Used by the absorb-learnings-to-soul cron job as data source.
# When run, outputs all learning reports newer than marker file.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LEARNINGS_DIR="$HERMES_HOME/learnings"
SOUL_FILE="$HERMES_HOME/SOUL.md"
PROPOSALS_DIR="$HERMES_HOME/proposals"
MARKER_FILE="$HERMES_HOME/scripts/.last_absorb"

echo "=== 新学习报告 ==="
if [ -f "$MARKER_FILE" ]; then
    find "$LEARNINGS_DIR" -name "20??-??-??.md" -newer "$MARKER_FILE" ! -name "INDEX.md" ! -name "seen_items.json" 2>/dev/null | sort || true
else
    find "$LEARNINGS_DIR" -name "20??-??-??.md" ! -name "INDEX.md" ! -name "seen_items.json" 2>/dev/null | sort | tail -5 || true
fi

echo ""
echo "=== 待审批提案 ==="
grep -rl "status: pending" "$PROPOSALS_DIR" 2>/dev/null | head -10 || true

echo ""
echo "=== 新近已通过提案 ==="
(grep -rl "status: approved" "$PROPOSALS_DIR" 2>/dev/null; grep -rl "status: verified" "$PROPOSALS_DIR" 2>/dev/null) | sort -u | head -5 || true

echo ""
echo "=== 当前 SOUL.md 摘要 ==="
head -20 "$SOUL_FILE" 2>/dev/null || true

touch "$MARKER_FILE"
