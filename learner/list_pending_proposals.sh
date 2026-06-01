#!/usr/bin/env bash
# List pending proposals for the review agent.
set -euo pipefail
shopt -s nullglob

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LEARNINGS_DIR="$HERMES_HOME/learnings"
PROPOSALS_DIR="$HERMES_HOME/proposals"
REVIEWED_FILE="$PROPOSALS_DIR/REVIEWED.md"

echo "=== 今日学习报告 (最新3份) ==="
find "$LEARNINGS_DIR" -name "20??-??-??.md" ! -name "INDEX.md" ! -name "seen_items.json" 2>/dev/null | sort -r | head -3 | while IFS= read -r f; do
    echo "--- $(basename "$f") ---"
    head -5 "$f" 2>/dev/null || true
    echo ""
done

echo ""
echo "=== 待审批提案 (frontmatter 摘要) ==="
for f in "$PROPOSALS_DIR"/*.md; do
    [ ! -f "$f" ] && continue
    name=$(basename "$f")
    [ "$name" = "INDEX.md" ] || [ "$name" = "TEMPLATE.md" ] || [ "$name" = "REVIEWED.md" ] && continue
    status=$(grep "^status:" "$f" 2>/dev/null | head -1 | sed 's/.*: //' || echo "unknown")
    score=$(grep "^score:" "$f" 2>/dev/null | head -1 | sed 's/.*: //' || echo "?")
    risk=$(grep "^risk:" "$f" 2>/dev/null | head -1 | sed 's/.*: //' || echo "?")
    title_line=$(grep "^# 📋" "$f" 2>/dev/null | head -1 | sed 's/# 📋 //' || echo "未命名")
    source_url=$(grep "^source_url:" "$f" 2>/dev/null | head -1 | sed 's/.*: //' || echo "?")
    if [ "$status" = "pending" ]; then
        echo "- [$status] ⭐$score ⚠️$risk $title_line ($name)"
        echo "  URL: $source_url"
    fi
done

echo ""
echo "=== 审核历史 (最新5条) ==="
tail -10 "$REVIEWED_FILE" 2>/dev/null || true
