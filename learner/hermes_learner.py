#!/usr/bin/env python3
"""Hermes 自主学习引擎 v3 — 系统级，每日执行。

数据源:
  1. AI HOT (aihot.virxact.com) — 中文 AI 行业动态
  2. GitHub (NousResearch/hermes-agent) — 社区技巧

结果写入 ~/.hermes/learnings/YYYY-MM-DD.md
包含: 来源状态、相关性评分、对 Hermes 影响分析、可行动建议

用法:
  python3 hermes_learner.py                # 正常执行
  python3 hermes_learner.py --dry-run       # 只输出，不写文件
  python3 hermes_learner.py --source aihot  # 只跑指定源
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import ssl
import logging
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
HERMES_HOME = os.path.expanduser("~/.hermes")
LEARNINGS_DIR = os.path.join(HERMES_HOME, "learnings")
LOGS_DIR = os.path.join(HERMES_HOME, "logs")
SEEN_FILE = os.path.join(LEARNINGS_DIR, "seen_items.json")
LEARNER_LOG = os.path.join(LOGS_DIR, "learner.log")

# ── Logging ──────────────────────────────────────
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LEARNER_LOG),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("hermes-learner")

# ── Config ───────────────────────────────────────
AIHOT_BASE = "https://aihot.virxact.com"
AIHOT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

GH_API = "https://api.github.com/repos/NousResearch/hermes-agent"
GH_HEADERS = {
    "User-Agent": "Hermes-Learner/3.0",
    "Accept": "application/vnd.github.v3+json",
}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
if GITHUB_TOKEN:
    GH_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# ── Relevance Scoring ────────────────────────────
# (keyword, score) tuples — higher score = more relevant to Hermes self-improvement
KW_SCORES = {
    # High-value: direct impact on Hermes capabilities
    "token": 3, "tokens": 3, "context": 3, "compression": 3,
    "prompt": 3, "cache": 3, "caching": 3, "memory": 3,
    "latency": 3, "cost": 3,
    # Medium-value: tool/framework improvements
    "agent": 2, "tool": 2, "skill": 2, "mcp": 2,
    "sandbox": 2, "permission": 2, "telemetry": 2,
    "eval": 2, "benchmark": 2, "routing": 2,
    "efficient": 2, "optimize": 2, "optimization": 2,
    "streaming": 2, "speed": 2,
    # Low-value: general AI ecosystem
    "hermes": 1, "代理": 1, "工具调用": 1,
    "进化": 1, "自我": 1, "autonomous": 1,
    "轻量": 1, "fast": 1, "lightweight": 1,
    "function call": 1, "structured output": 1,
}
# Deprioritize: PR/branding noise AND low-value chore/cleanup PRs
DEPRIORITIZE_KW = [
    "gartner", "融资", "funding", "排行", "排名", "榜单",
    "remove unused", "unused import", "dead code", "cleanup",
    "typo", "formatting", "lint", "linting",
    "chore", "refactor",
]

MIN_SCORE = 3         # items below this don't appear in main report
PROPOSAL_SCORE = 7    # GitHub items at or above this generate proposals
AIHOT_PROPOSAL_SCORE = 999  # AI HOT never generates proposals (info only)


def http_get_json(url, headers=None, timeout=30):
    """HTTP GET JSON with error handling. Returns (data_dict, status, error_msg)."""
    req = urllib.request.Request(url, headers=headers or {})
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        data = json.loads(resp.read())
        return data, "ok", None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        return None, "failed", f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, "failed", str(e)


def load_seen():
    """Load previously seen items for dedup."""
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_seen(seen):
    """Persist seen items."""
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(seen, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save seen items: %s", e)


def item_hash(item):
    """Generate dedup hash from source + url + title."""
    text = f'{item.get("source", "")}|{item.get("url", "")}|{item.get("title", "")}'
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def score_item(title, summary, source_name, category):
    """Calculate relevance score for a finding."""
    text = ((title or "") + " " + (summary or "")).lower()
    score = 0
    matched = []

    for kw, val in KW_SCORES.items():
        if kw in text:
            score += val
            matched.append(kw)

    # Bonus: title match
    title_lower = (title or "").lower()
    for kw, val in KW_SCORES.items():
        if kw in title_lower and kw not in matched:
            score += 1  # title bonus
            matched.append(kw)

    # Deprioritize
    for kw in DEPRIORITIZE_KW:
        if kw in (title or "").lower():
            score -= 3

    score = min(score, 10)  # cap at 10
    return max(score, 0), matched


def generate_insight(item):
    """Generate a brief insight about what this finding means for Hermes."""
    title = (item.get("title") or "").lower()
    summary = (item.get("summary") or "").lower()
    text = title + " " + summary

    insights = []
    if any(kw in text for kw in ["token", "tokens"]):
        insights.append("📊 关注 token 成本与效率优化")
    if any(kw in text for kw in ["agent", "代理"]):
        insights.append("🤖 Agent 架构与能力边界参考")
    if any(kw in text for kw in ["context", "上下文"]):
        insights.append("📝 上下文管理与压缩策略")
    if any(kw in text for kw in ["tool", "mcp", "tools"]):
        insights.append("🔧 工具链与扩展能力")
    if any(kw in text for kw in ["cost", "节省", "优化"]):
        insights.append("💰 成本控制与优化方向")
    if any(kw in text for kw in ["eval", "benchmark"]):
        insights.append("📏 评估与基准参考")

    return insights if insights else ["📰 行业动态参考"]


def generate_actions(item):
    """Generate specific, actionable suggestions for high-score findings."""
    title = (item.get("title") or "")
    summary = (item.get("summary") or "")
    text = (title + " " + summary).lower()
    score = item.get("score", 0)
    keywords = item.get("keywords", [])

    if score < PROPOSAL_SCORE:
        return []

    actions = []

    # Token/cost related → specific optimization suggestions
    if any(kw in keywords for kw in ["token", "tokens", "cost"]):
        actions.append({
            "action": "分析 DeepSeek 近 7 天 token 消耗分布，识别高成本任务模式",
            "benefit": "发现优化机会，预计可节省 15-30% 配额",
            "effort": "低",
            "category": "economy",
        })
        actions.append({
            "action": "审查 context compaction threshold 是否可进一步降低",
            "benefit": "减少长对话 token 膨胀",
            "effort": "低",
            "category": "economy",
        })

    # Agent/tool/skill/MCP related → check if it's a hermes-agent specific improvement
    if any(kw in keywords for kw in ["skill", "mcp", "tool"]) and item.get("source") == "GitHub":
        actions.append({
            "action": f"审查 hermes-agent PR「{title[:50]}」是否可直接应用到本地 Hermes",
            "benefit": "跟上社区更新，避免本地版本落后",
            "effort": "低" if "fix" in title.lower() else "中",
            "category": "capability",
        })

    # Context/compression → context management
    if any(kw in keywords for kw in ["context", "上下文", "compression"]):
        actions.append({
            "action": "审计当前 memory 条目冗余度，清理过期/stale 信息",
            "benefit": "提升上下文利用率，降低每轮 token 开销",
            "effort": "低",
            "category": "context",
        })

    # Prompt related → prompt engineering
    if any(kw in keywords for kw in ["prompt"]):
        actions.append({
            "action": "对比社区最新 prompt 策略与 Hermes 当前配置，标记差异点",
            "benefit": "跟上社区最佳实践，提升回复质量",
            "effort": "低",
            "category": "quality",
        })

    # Caching/speed → performance
    if any(kw in keywords for kw in ["cache", "caching", "speed", "latency"]):
        actions.append({
            "action": "检查 gateway 层缓存命中率，调整 cache TTL 策略",
            "benefit": "减少重复 API 调用，降低延迟和成本",
            "effort": "低",
            "category": "performance",
        })

    # Eval/benchmark → quality measurement
    if any(kw in keywords for kw in ["eval", "benchmark"]):
        actions.append({
            "action": "设计针对 Hermes 核心工作流的回归测试基准",
            "benefit": "每次模型/配置变更时有客观质量度量",
            "effort": "中",
            "category": "quality",
        })

    return actions


# ── Source 1: AI HOT ─────────────────────────────
def fetch_aihot(hours=24):
    """Fetch recent AI HOT items with scoring."""
    start = time.monotonic()
    try:
        since_utc = datetime.now(CST).astimezone(timezone.utc) - timedelta(hours=hours)
        since_str = since_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{AIHOT_BASE}/api/public/items?mode=selected&since={since_str}&take=50"
        data, ai_status, ai_err = http_get_json(url, headers={"User-Agent": AIHOT_UA})
        if ai_status != "ok":
            raise RuntimeError(ai_err or "unknown error")
        items = data.get("items", [])
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.warning("AI HOT fetch failed (%.1fs): %s", elapsed, e)
        return [], {"status": "failed", "error": str(e), "latency_ms": int(elapsed * 1000), "count": 0}

    seen = load_seen()
    findings = []

    for item in items:
        hid = item_hash(item)
        if hid in seen:
            continue

        title = item.get("title", "")
        summary = (item.get("summary") or "")[:300]
        score, matched = score_item(
            title, summary,
            item.get("source", ""),
            item.get("category", ""),
        )

        seen[hid] = {
            "first_seen": datetime.now(CST).isoformat(),
            "source": "aihot",
            "score": score,
        }
        if score >= MIN_SCORE:
            findings.append({
                "source": "AI HOT",
                "title": title,
                "url": item.get("url", ""),
                "source_name": item.get("source", ""),
                "summary": summary,
                "published": item.get("publishedAt", ""),
                "keywords": matched,
                "category": item.get("category", ""),
                "score": score,
                "insights": generate_insight({"title": title, "summary": summary}),
                "actions": [],
            })

    save_seen(seen)
    elapsed = time.monotonic() - start

    # Post-process: AI HOT items never generate proposals (info-only source)
    for f in findings:
        f["actions"] = []  # AI HOT is info-only, no proposals

    findings.sort(key=lambda x: x["score"], reverse=True)

    return findings, {
        "status": "ok",
        "count": len(findings),
        "total_fetched": len(items),
        "latency_ms": int(elapsed * 1000),
    }


# ── Source 2: GitHub ──────────────────────────────
def fetch_github(days=7):
    """Scan recent GitHub issues/PRs with scoring."""
    start = time.monotonic()
    try:
        issues_data, gh_status, gh_err = http_get_json(
            f"{GH_API}/issues?state=all&per_page=30&sort=updated&direction=desc",
            headers=GH_HEADERS,
        )
        if gh_status != "ok":
            raise RuntimeError(gh_err or "unknown error")
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.warning("GitHub fetch failed (%.1fs): %s", elapsed, e)
        return [], {"status": "failed", "error": str(e), "latency_ms": int(elapsed * 1000), "count": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen = load_seen()
    findings = []

    for item in issues_data:
        updated = item.get("updated_at", "")
        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except Exception:
            continue
        if updated_dt < cutoff:
            continue

        hid = item_hash({"source": "GitHub", "url": item.get("html_url", ""), "title": item.get("title", "")})
        if hid in seen:
            continue

        title = item.get("title", "")
        body = (item.get("body") or "")[:500]
        score, matched = score_item(title, body, "GitHub", "")

        seen[hid] = {
            "first_seen": datetime.now(CST).isoformat(),
            "source": "github",
            "score": score,
        }
        if score >= MIN_SCORE:
            findings.append({
                "source": "GitHub",
                "type": "PR" if "pull_request" in item else "Issue",
                "number": item["number"],
                "title": title,
                "url": item["html_url"],
                "keywords": matched,
                "state": item["state"],
                "updated": updated,
                "score": score,
                "summary": body[:300],
                "body": body,
                "insights": generate_insight({"title": title, "summary": body}),
                "actions": [],
            })

    save_seen(seen)
    elapsed = time.monotonic() - start

    for f in findings:
        f["actions"] = generate_actions(f)

    findings.sort(key=lambda x: x["score"], reverse=True)

    return findings, {
        "status": "ok",
        "count": len(findings),
        "total_fetched": len(issues_data),
        "latency_ms": int(elapsed * 1000),
    }


# ── Report Generation ─────────────────────────────
def format_report(aihot_findings, gh_findings, aihot_status, gh_status):
    """Generate markdown daily learning report."""
    now = datetime.now(CST)
    date_str = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M CST")

    lines = [
        f"# 🧠 Hermes 学习报告 — {date_str}",
        f"\n> 自动生成于 {now_str} | 数据源: AI HOT + GitHub\n",
    ]

    total = len(aihot_findings) + len(gh_findings)
    high_score = sum(1 for f in aihot_findings + gh_findings if f["score"] >= PROPOSAL_SCORE)

    lines.append("## 📊 概况\n")
    lines.append(f"| 来源 | 状态 | 获取 | 收录 |")
    lines.append(f"|---|---:|---:|---:|")
    lines.append(
        f"| 🔥 AI HOT | {_status_icon(aihot_status['status'])} "
        f"| {aihot_status.get('total_fetched', '-')} | {aihot_status['count']} |"
    )
    lines.append(
        f"| 💻 GitHub | {_status_icon(gh_status['status'])} "
        f"| {gh_status.get('total_fetched', '-')} | {gh_status['count']} |"
    )
    lines.append(f"\n总计: {total} 条 | 高价值 (≥{PROPOSAL_SCORE}分): {high_score} 条\n")

    if total == 0:
        lines.append("## 📭 今日无新发现\n")
        return "\n".join(lines)

    # AI HOT findings
    if aihot_findings:
        lines.append("## 🔥 AI HOT 发现\n")
        for i, f in enumerate(aihot_findings, 1):
            score_bar = "█" * min(f["score"], 10)
            lines.append(f"### {i}. [{f['title']}]({f['url']})")
            lines.append(f"📰 {f['source_name']} | ⭐ {f['score']}/10 {score_bar}")
            if f.get("summary"):
                lines.append(f"> {f['summary']}")
            if f.get("insights"):
                lines.append(f"💡 {' | '.join(f['insights'])}")
            if f.get("actions"):
                lines.append("📋 **建议行动:**")
                for a in f["actions"]:
                    lines.append(f"  - {a['action']}（收益: {a['benefit']}, 工作量: {a['effort']}）")
            lines.append("")

    # GitHub findings
    if gh_findings:
        lines.append("## 💻 GitHub 发现\n")
        for i, f in enumerate(gh_findings, 1):
            score_bar = "█" * min(f["score"], 10)
            lines.append(f"### {i}. [{f['state'].upper()}] [{f['title']}]({f['url']})")
            kw_str = " ".join(f"`{k}`" for k in f.get("keywords", []))
            lines.append(f"⭐ {f['score']}/10 {score_bar} | {kw_str}")
            if f.get("insights"):
                lines.append(f"💡 {' | '.join(f['insights'])}")
            if f.get("actions"):
                lines.append("📋 **建议行动:**")
                for a in f["actions"]:
                    lines.append(f"  - {a['action']}（收益: {a['benefit']}, 工作量: {a['effort']}）")
            lines.append("")

    # Source status section
    lines.append("---\n")
    lines.append("## 🔧 数据源状态\n")
    lines.append(
        f"| AI HOT | {_status_icon(aihot_status['status'])} "
        f"| {aihot_status.get('latency_ms', '-')}ms "
        f"| {aihot_status.get('error', '-')} |"
    )
    lines.append(
        f"| GitHub | {_status_icon(gh_status['status'])} "
        f"| {gh_status.get('latency_ms', '-')}ms "
        f"| {gh_status.get('error', '-')} |"
    )

    lines.append(f"\n---")
    lines.append(f"> ⚖️ v3 自动生成 | 评分阈值: {MIN_SCORE} | 提案阈值: {PROPOSAL_SCORE}\n")

    return "\n".join(lines)


def _status_icon(status):
    if status == "ok":
        return "✅"
    if status == "n/a":
        return "⏭️"
    return "❌"


def save_proposals(findings, date_str):
    """Save high-score findings as actionable proposal files."""
    proposals_dir = os.path.join(HERMES_HOME, "proposals")
    os.makedirs(proposals_dir, exist_ok=True)



def save_proposals(findings, date_str):
    """Save high-score findings as actionable proposal files."""
    proposals_dir = os.path.join(HERMES_HOME, "proposals")
    os.makedirs(proposals_dir, exist_ok=True)

    # Ensure template exists
    template_path = os.path.join(proposals_dir, "TEMPLATE.md")
    if not os.path.exists(template_path):
        template = (
            "# 📋 提案模板\n\n"
            "## 标题\n<!-- 提案标题 -->\n\n"
            "## 来源\n<!-- 学习报告日期 + 原始链接 -->\n\n"
            "## 现状\n<!-- 当前 Hermes 在这方面的状态 -->\n\n"
            "## 改进方案\n<!-- 具体怎么改 -->\n\n"
            "## 预期收益\n<!-- 改了会有什么好处 -->\n\n"
            "## 工作量评估\n<!-- 低/中/高 + 预估时间 -->\n\n"
            "## 审批\n<!-- 待审批 / 已通过 / 已拒绝 -->\n"
        )
        with open(template_path, "w") as f:
            f.write(template)

    saved = 0
    for f in findings:
        if not f.get("actions"):
            continue
        # Generate proposal filename from title + hash
        slug = (f.get("title", "proposal"))[:60].strip()
        slug = "".join(c if c.isalnum() or c in "._- " else "" for c in slug)
        slug = slug.strip().replace(" ", "_")[:50]
        fid = item_hash(f)[:8]
        prop_name = f"{date_str}_{slug}_{fid}.md"
        prop_path = os.path.join(proposals_dir, prop_name)

        risk = "high" if f.get("score", 0) >= 9 else "medium" if f.get("score", 0) >= 7 else "low"
        lines = [
            "---",
            f"status: pending",
            f"risk: {risk}",
            f"source_report: {date_str}",
            f"source_url: {f.get('url', '')}",
            f"score: {f.get('score', 0)}",
            f"approved_at: ~",
            f"implemented_at: ~",
            f"verified_at: ~",
            "---",
            "",
            f"# 📋 {f.get('title', '未命名提案')}",
            "",
            f"**来源**: {f.get('source', 'N/A')} | **日期**: {date_str}",
            f"**链接**: {f.get('url', 'N/A')}",
            f"**评分**: {f.get('score', 0)}/10",
            "",
            "## 摘要",
            f"> {f.get('summary', '（无摘要）')}",
            "",
        ]
        if f.get("insights"):
            lines.append("## 对 Hermes 的影响")
            for insight in f["insights"]:
                lines.append(f"- {insight}")
            lines.append("")

        if f.get("actions"):
            lines.append("## 建议行动")
            for a in f["actions"]:
                lines.append(f"- **{a.get('action', '')}** │ 收益: {a.get('benefit', '')} │ 工作量: {a.get('effort', '')} │ 分类: {a.get('category', '')}")
            lines.append("")

        lines.extend([
            "## 审批状态",
            f"- **状态**: `pending` → 待用户审批",
            f"- **风险等级**: `{risk}`",
            "",
            "### 状态流转",
            "```",
            "pending → approved → implementing → implemented → verified",
            "pending → rejected",
            "implemented → failed → rolled_back",
            "```",
            "",
            "### 审批操作",
            "- 通过: 将 frontmatter 中 `status` 改为 `approved`",
            "- 拒绝: 将 frontmatter 中 `status` 改为 `rejected`",
            "- 实施后: 依次更新为 `implementing` → `implemented` → `verified`",
            "",
            "---",
            f"> 由 Hermes Learner v3 自动生成 | {date_str}",
        ])

        try:
            with open(prop_path, "w") as pf:
                pf.write("\n".join(lines) + "\n")
            saved += 1
        except Exception as e:
            logger.warning("Failed to save proposal %s: %s", prop_name, e)

    if saved:
        logger.info("📋 已保存 %s 份提案到 %s", saved, proposals_dir)
    return saved


def update_proposal_index(proposals_dir):
    """Update proposals INDEX.md with status summary."""
    index_path = os.path.join(proposals_dir, "INDEX.md")
    items = []
    status_counts = {}
    try:
        for fname in sorted(os.listdir(proposals_dir), reverse=True):
            if fname in ("INDEX.md", "TEMPLATE.md") or not fname.endswith(".md"):
                continue
            fpath = os.path.join(proposals_dir, fname)
            with open(fpath) as f:
                content = f.read()
            # Extract YAML frontmatter
            status = "unknown"
            score = 0
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    for line in content[3:end].split("\n"):
                        line = line.strip()
                        if line.startswith("status:"):
                            status = line.split(":", 1)[1].strip()
                        elif line.startswith("score:"):
                            try:
                                score = int(line.split(":", 1)[1].strip())
                            except Exception:
                                pass
            # Count statuses directly
            status_counts[status] = status_counts.get(status, 0) + 1
            # Extract title (find "# 📋 TITLE" line)
            title = "未命名"
            for line in content.split("\n"):
                if line.startswith("# ") and "📋" in line:
                    # Strip "# " prefix then strip "📋 " prefix
                    title = line[2:].replace("📋 ", "").strip()[:60]
                    break
            icon = {"pending": "⏳", "approved": "✅", "rejected": "❌", "implementing": "🔧",
                    "implemented": "📦", "verified": "🎯", "failed": "💥", "rolled_back": "↩️"}.get(status, "❓")
            items.append(f"- [{icon} {status}] [{title}]({fname}) ⭐{score}")
    except Exception as e:
        logger.warning("Failed to build proposal index: %s", e)

    with open(index_path, "w") as f:
        f.write("# 📋 提案索引\n\n")
        f.write("| 状态 | 数量 |\n")
        f.write("|---|---|\n")
        for s in ["pending", "approved", "implementing", "implemented", "verified", "rejected", "failed", "rolled_back"]:
            cnt = status_counts.get(s, 0)
            if cnt:
                f.write(f"| {s} | {cnt} |\n")
        f.write("\n")
        f.write("\n".join(items) + "\n")


def update_index(date_str):
    """Update INDEX.md — dedup + sort newest first."""
    index_path = os.path.join(LEARNINGS_DIR, "INDEX.md")
    entry = f"- [{date_str}]({date_str}.md)"

    # Read existing index, split header from entries
    header_lines = []
    entry_lines = []
    try:
        with open(index_path) as f:
            for line in f:
                line = line.rstrip()
                if line.startswith("- ["):
                    entry_lines.append(line)
                else:
                    header_lines.append(line)
    except FileNotFoundError:
        header_lines = ["# 📚 Hermes 学习报告索引", ""]

    # Dedup: remove existing entry for same date, then add
    entry_lines = [l for l in entry_lines if date_str not in l]
    entry_lines.append(entry)
    # Sort by date descending (date is in the link text)
    entry_lines.sort(reverse=True)

    with open(index_path, "w") as f:
        f.write("\n".join(header_lines + entry_lines) + "\n")


# ── Main ──────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Hermes 自主学习引擎 v3")
    parser.add_argument("--dry-run", action="store_true", help="只输出，不写文件")
    parser.add_argument("--source", choices=["aihot", "github", "all"], default="all")
    args = parser.parse_args()

    logger.info("=== Hermes Learner v3 开始 ===")

    aihot_findings, aihot_status = [], {"status": "n/a", "count": 0}
    gh_findings, gh_status = [], {"status": "n/a", "count": 0}

    if args.source in ("aihot", "all"):
        logger.info("🔥 扫描 AI HOT...")
        aihot_findings, aihot_status = fetch_aihot(hours=24)
        logger.info("  AI HOT: 获取 %s 条, 收录 %s 条", aihot_status.get("total_fetched", "?"), aihot_status["count"])

    if args.source in ("github", "all"):
        logger.info("💻 扫描 GitHub...")
        gh_findings, gh_status = fetch_github(days=7)
        logger.info("  GitHub: 获取 %s 条, 收录 %s 条", gh_status.get("total_fetched", "?"), gh_status["count"])

    report = format_report(aihot_findings, gh_findings, aihot_status, gh_status)
    now = datetime.now(CST)
    date_str = now.strftime("%Y-%m-%d")
    report_path = os.path.join(LEARNINGS_DIR, f"{date_str}.md")

    if args.dry_run:
        print(report)
        # Preview what proposals would be generated
        prop_count = sum(1 for f in aihot_findings + gh_findings if f.get("actions"))
        if prop_count:
            print(f"\n---\n📋 将生成 {prop_count} 份提案")
        logger.info("=== 干跑完成 ===")
        return

    os.makedirs(LEARNINGS_DIR, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)

    update_index(date_str)
    saved = save_proposals(aihot_findings + gh_findings, date_str)
    proposals_dir = os.path.join(HERMES_HOME, "proposals")
    update_proposal_index(proposals_dir)
    logger.info("✅ 报告已保存: %s", report_path)
    logger.info("📊 总计: %s 条 | 高价值: %s 条 | 提案: %s 份",
                len(aihot_findings) + len(gh_findings),
                sum(1 for f in aihot_findings + gh_findings if f["score"] >= PROPOSAL_SCORE),
                saved)
    logger.info("=== Hermes Learner v3 完成 ===")


if __name__ == "__main__":
    main()
