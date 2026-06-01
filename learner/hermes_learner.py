#!/usr/bin/env python3
"""Hermes 自主学习引擎 v3 — 系统级，每日执行。

数据源:
  1. AI HOT (aihot.virxact.com) — 中文 AI 行业动态
  2. GitHub Trending — 热门 AI Agent/MCP 仓库
  3. Arxiv — 最新 AI 论文

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

GH_SEARCH_API = "https://api.github.com/search/repositories"
GH_HEADERS = {
    "User-Agent": "Hermes-Learner/3.0",
    "Accept": "application/vnd.github.v3+json",
}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
if not GITHUB_TOKEN:
    # Try loading from .env for standalone runs
    env_path = os.path.join(HERMES_HOME, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as ef:
            for line in ef:
                line = line.strip()
                if line.startswith("GITHUB_TOKEN="):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val and val != "***":
                        GITHUB_TOKEN = val
                        break
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
    # Chinese keywords for AI HOT (中文 AI 资讯)
    "模型": 2, "ai": 2, "降价": 2, "折扣": 2,
    "供应链": 2, "攻击": 2, "安全": 2,
    "融资": 1, "发布": 1, "开源": 1,
    "工作流": 1, "框架": 1, "gpt": 2,
    "claude": 2, "deepseek": 2, "gemini": 2,
}
# Deprioritize: PR/branding noise AND low-value chore/cleanup PRs
DEPRIORITIZE_KW = [
    "gartner", "融资", "funding", "排行", "排名", "榜单",
    "remove unused", "unused import", "dead code", "cleanup",
    "typo", "formatting", "lint", "linting",
    "chore", "refactor",
]

MIN_SCORE = 3         # items below this don't appear in main report
PROPOSAL_SCORE = 7    # items at or above this generate proposals


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


def score_item(title, summary):
    """Calculate relevance score for a finding. Returns (score, matched_keywords)."""
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
    """Generate specific insight referencing the actual finding content."""
    title = (item.get("title") or "")
    summary = (item.get("summary") or "")
    source = item.get("source", "")
    text = (title + " " + summary).lower()

    insights = []
    short_title = title[:80]

    if source == "GitHub 热榜":
        # Extract description from summary format "[lang] ★N — desc"
        desc = summary.split("—", 1)[-1].strip() if "—" in summary else summary
        insights.append(f"📦 **{short_title}**: {desc[:150]}")

        if "mcp" in text:
            insights.append("🔧 MCP 工具链：评估该实现是否可注册为 Hermes 原生工具")
        elif "agent" in text:
            insights.append("🤖 Agent 设计：该项目的架构思路可参考用于改进 Hermes agent 层")
        elif "memory" in text or "context" in text:
            insights.append("🧠 上下文管理：对比 Hermes 当前 memory/context 策略")
        elif "tool" in text:
            insights.append("🔧 工具链参考：评估该项目功能是否能以 skill 形式集成")
        else:
            insights.append("📋 社区新项目，值得关注其技术方向")

    elif source == "Arxiv":
        insights.append(f"📄 **{short_title}**")
        if "agent" in text:
            insights.append("📚 agent 方向论文建议通读，评估方法论是否适用")
        elif "tool" in text or "mcp" in text:
            insights.append("📚 工具/协议方向论文，关注其设计思路的可移植性")
        else:
            insights.append("📚 建议通读摘要，评估与 Hermes 的相关性")

    elif source == "AI HOT":
        insights.append(f"🔥 {short_title}")
        if any(kw in text for kw in ("降价", "折扣", "价格")):
            insights.append("💰 provider 价格变动，评估是否调整当前模型选型")
        elif any(kw in text for kw in ("攻击", "安全", "泄露", "漏洞")):
            insights.append("🛡️ 安全事件，需检查 Hermes 基础设施是否受影响")
        elif any(kw in text for kw in ("融资", "收购")):
            insights.append("🏭 行业资本动态，关注对 API 服务稳定性的影响")
        else:
            insights.append("📡 行业动态，关注对 AI 生态的潜在影响")

    return insights if insights else ["📰 值得关注的行业动态"]


def generate_actions(item):
    """Generate actionable suggestions that reference the actual finding."""
    title = (item.get("title") or "")
    summary = (item.get("summary") or "")
    source = item.get("source", "")
    score = item.get("score", 0)
    text = (title + " " + summary).lower()

    if score < PROPOSAL_SCORE:
        return []

    short = title[:60]
    actions = []

    if source == "GitHub 热榜":
        desc = summary.split("—", 1)[-1].strip() if "—" in summary else summary

        if "mcp" in text:
            actions.append({
                "action": f"分析 [{short}]({item.get('url','')}) 的 MCP 实现，评估注册为 Hermes 工具的可行性与工作量",
                "benefit": "扩展 Hermes 工具链能力",
                "effort": "中",
                "category": "tool",
            })
        if "agent" in text:
            actions.append({
                "action": f"阅读 [{short}]({item.get('url','')}) 的 agent 架构设计，提取可复用模式",
                "benefit": "改进 Hermes agent 层设计",
                "effort": "低",
                "category": "agent",
            })
        if not actions:
            # Fallback: generic but still references the repo
            actions.append({
                "action": f"调研 [{short}]({item.get('url','')})：{desc[:100]}",
                "benefit": "评估是否值得集成进 Hermes 生态",
                "effort": "低",
                "category": "research",
            })

    elif source == "Arxiv":
        actions.append({
            "action": f"通读 [{short}]({item.get('url','')}) 论文摘要与结论，标注与 Hermes 相关的技术点",
            "benefit": "跟踪学术前沿，发现可落地的技术方案",
            "effort": "低",
            "category": "research",
        })

    elif source == "AI HOT":
        if any(kw in text for kw in ("降价", "折扣", "价格")):
            actions.append({
                "action": "对比该价格变动对当前 Hermes provider 选型的影响，更新成本对比表",
                "benefit": "优化 API 调用成本",
                "effort": "低",
                "category": "economy",
            })
        elif any(kw in text for kw in ("攻击", "安全", "泄露")):
            actions.append({
                "action": "检查 Hermes 是否使用了受影响的库/服务，评估是否需要应急更新",
                "benefit": "保障系统安全",
                "effort": "中",
                "category": "security",
            })
        else:
            actions.append({
                "action": f"记录 [{short}]({item.get('url','')}) 的关键信息至行业动态知识库",
                "benefit": "保持对 AI 行业趋势的跟踪",
                "effort": "低",
                "category": "research",
            })

    return actions


# ── Source 1: AI HOT ─────────────────────────────
def fetch_aihot(hours=24, seen=None):
    """Fetch recent AI HOT items with scoring."""
    if seen is None:
        seen = load_seen()
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

    findings = []

    for item in items:
        hid = item_hash(item)
        if hid in seen:
            continue

        title = item.get("title", "")
        summary = (item.get("summary") or "")[:300]
        score, matched = score_item(
            title, summary,
        )

        seen[hid] = {
            "first_seen": datetime.now(CST).isoformat(),
            "source": "aihot",
            "score": score,
        }
        if score >= MIN_SCORE:
            fe = {
                "source": "AI HOT",
                "title": title,
                "url": item.get("url", ""),
                "source_name": item.get("source", ""),
                "summary": summary,
                "published": item.get("publishedAt", ""),
                "keywords": matched,
                "category": item.get("category", ""),
                "score": score,
            }
            fe["insights"] = generate_insight(fe)
            fe["actions"] = generate_actions(fe)
            findings.append(fe)

    elapsed = time.monotonic() - start

    findings.sort(key=lambda x: x["score"], reverse=True)

    return findings, {
        "status": "ok",
        "count": len(findings),
        "total_fetched": len(items),
        "latency_ms": int(elapsed * 1000),
    }


# ── Source 2: GitHub Trending Search ──────────────
def fetch_github_trending(days=7, seen=None):
    """Search GitHub for trending AI agent repos beyond hermes-agent."""
    if seen is None:
        seen = load_seen()
    start = time.monotonic()
    queries = [
        # Key topics (most distinct, was 6 → kept 3 most distinct)
        "topic:ai-agent",
        "topic:mcp-server",
        "topic:agent-framework",
        # Broader text fallback (catches repos not explicitly tagged)
        "AI agent framework tool",
        "MCP server tools LLM",
    ]
    all_findings = []
    seen_titles = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for query in queries:
        try:
            q = query.replace(" ", "+")
            url = f"{GH_SEARCH_API}?q={q}&sort=updated&per_page=5&order=desc"
            data, gh_status, gh_err = http_get_json(url, headers=GH_HEADERS)
            if gh_status != "ok":
                logger.warning("GitHub trending search '%s' failed: %s", query, gh_err or "unknown")
                continue
            items = data.get("items", [])
        except Exception as e:
            logger.warning("GitHub trending search '%s' error: %s", query, e)
            continue

        for item in items:
            full_name = item.get("full_name", "")
            title = item.get("description", "") or item.get("name", "")
            html_url = item.get("html_url", "")

            hid = item_hash({"source": "GitHubTrending", "url": html_url, "title": full_name})
            if hid in seen or full_name in seen_titles:
                continue

            updated = item.get("updated_at", "")
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except Exception:
                continue
            if updated_dt < cutoff:
                continue

            description = (item.get("description") or "")[:300]
            lang = item.get("language") or ""
            stars = item.get("stargazers_count", 0)
            topics = item.get("topics", [])
            search_text = f"{full_name} {description} {' '.join(topics)}"
            score, matched = score_item(search_text, description)

            # Star bonus: trending repos get extra relevance
            if stars > 1000:
                score += 1
            if "agent" in search_text.lower() or "mcp" in search_text.lower():
                score += 1
            score = min(score, 10)  # cap after bonuses

            seen[hid] = {
                "first_seen": datetime.now(CST).isoformat(),
                "source": "github_trending",
                "score": score,
            }
            if score >= MIN_SCORE:
                summary = f"[{lang}] ★{stars} — {description}" if lang else f"★{stars} — {description}"
                findings_entry = {
                    "source": "GitHub 热榜",
                    "title": full_name,
                    "url": html_url,
                    "source_name": query,
                    "summary": summary,
                    "published": updated,
                    "keywords": matched,
                    "category": f"github/{lang}" if lang else "github",
                    "score": score,
                    "actions": [],
                }
                findings_entry["insights"] = generate_insight(findings_entry)
                findings_entry["actions"] = generate_actions(findings_entry)
                all_findings.append(findings_entry)
            seen_titles.add(full_name)

    all_findings.sort(key=lambda x: x["score"], reverse=True)
    elapsed = time.monotonic() - start
    return all_findings, {
        "status": "ok",
        "count": len(all_findings),
        "queries": len(queries),
        "latency_ms": int(elapsed * 1000),
    }


# ── Source 3: Arxiv Search ────────────────────────
def fetch_arxiv(days=3, seen=None):
    """Search recent Arxiv papers on AI agents and LLM tools."""
    if seen is None:
        seen = load_seen()
    start = time.monotonic()
    import urllib.parse as _up
    queries = [
        "all:AI agent tool",
        "all:large language model agent framework",
        "all:MCP model context protocol",
        "all:autonomous agent LLM",
    ]
    all_findings = []
    seen_ids = set()

    for query in queries:
        try:
            safe_q = _up.quote(query)
            url = f"https://export.arxiv.org/api/query?search_query={safe_q}&max_results=5&sortBy=submittedDate&sortOrder=descending"
            # 429 retry with backoff
            root = None
            for attempt in range(3):
                try:
                    import xml.etree.ElementTree as ET
                    req = urllib.request.Request(url, headers={"User-Agent": "Hermes-Learner/3.0"})
                    ctx = ssl.create_default_context()
                    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
                    xml_text = resp.read()
                    root = ET.fromstring(xml_text)
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt < 2:
                        wait = 5 * (attempt + 1)
                        logger.warning("Arxiv 429, retrying in %ds...", wait)
                        time.sleep(wait)
                        continue
                    logger.warning("Arxiv search '%s' failed: HTTP %d", query, e.code)
                    break
                except ET.ParseError as e:
                    logger.warning("Arxiv XML parse failed for '%s': %s", query, e)
                    break
            if root is None:
                continue
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                entry_id = entry.find("atom:id", ns)
                entry_title = entry.find("atom:title", ns)
                entry_summary = entry.find("atom:summary", ns)
                entry_published = entry.find("atom:published", ns)
                entry_link = entry.find("atom:link", ns)
                if entry_id is None:
                    continue
                eid = entry_id.text or ""
                etitle = (entry_title.text or "").strip().replace("\n", " ")[:200] if entry_title is not None else ""
                esummary = (entry_summary.text or "").strip().replace("\n", " ")[:500] if entry_summary is not None else ""
                epub = (entry_published.text or "")[:10] if entry_published is not None else ""
                elink = entry_link.get("href", eid) if entry_link is not None else eid
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)

                hid = item_hash({"source": "Arxiv", "url": elink, "title": etitle})
                if hid in seen:
                    continue

                score, matched = score_item(etitle, esummary)
                seen[hid] = {
                    "first_seen": datetime.now(CST).isoformat(),
                    "source": "arxiv",
                    "score": score,
                }
                if score >= MIN_SCORE:
                    fe = {
                        "source": "Arxiv",
                        "title": etitle,
                        "url": elink,
                        "source_name": query,
                        "summary": esummary[:300],
                        "published": epub,
                        "keywords": matched,
                        "category": "学术论文",
                        "score": score,
                        "actions": [],
                    }
                    fe["insights"] = generate_insight(fe)
                    fe["actions"] = generate_actions(fe)
                    all_findings.append(fe)
        except Exception as e:
            logger.warning("Arxiv XML parse error for '%s': %s", query, e)

    all_findings.sort(key=lambda x: x["score"], reverse=True)
    elapsed = time.monotonic() - start
    return all_findings, {
        "status": "ok",
        "count": len(all_findings),
        "latency_ms": int(elapsed * 1000),
    }


# ── Report Generation ─────────────────────────────
def format_report(aihot_findings, trending_findings, arxiv_findings,
                  aihot_status, trending_status, arxiv_status):
    """Generate markdown daily learning report."""
    now = datetime.now(CST)
    date_str = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M CST")

    lines = [
        f"# 🧠 Hermes 学习报告 — {date_str}",
        f"\n> 自动生成于 {now_str} | 数据源: AI HOT + GitHub热榜 + Arxiv\n",
    ]

    total = len(aihot_findings) + len(trending_findings) + len(arxiv_findings)
    high_score = sum(1 for f in aihot_findings + trending_findings + arxiv_findings if f["score"] >= PROPOSAL_SCORE)

    lines.append("## 📊 概况\n")
    lines.append(f"| 来源 | 状态 | 获取 | 收录 |")
    lines.append(f"|---|---:|---:|---:|")
    lines.append(
        f"| 🔥 AI HOT | {_status_icon(aihot_status['status'])} "
        f"| {aihot_status.get('total_fetched', '-')} | {aihot_status['count']} |"
    )
    lines.append(
        f"| 🌟 GitHub 热榜 | {_status_icon(trending_status['status'])} "
        f"| {trending_status.get('queries', '-')} 组 | {trending_status['count']} |"
    )
    lines.append(
        f"| 📄 Arxiv 论文 | {_status_icon(arxiv_status['status'])} "
        f"| - | {arxiv_status['count']} |"
    )
    lines.append(f"\n总计: {total} 条 | 高价值 (≥{PROPOSAL_SCORE}分): {high_score} 条\n")

    # System health dashboard (always shown)
    try:
        proposals_dir = os.path.join(HERMES_HOME, "proposals")
        if not os.path.isdir(proposals_dir):
            logger.debug("Proposals directory not found, skipping health dashboard")
        else:
            counts = {"pending": 0, "approved": 0, "rejected": 0, "deferred": 0,
                      "implementing": 0, "implemented": 0, "verified": 0, "failed": 0}
            for fname in os.listdir(proposals_dir):
                if not fname.endswith(".md") or fname in ("INDEX.md", "TEMPLATE.md", "REVIEWED.md"):
                    continue
                fp = os.path.join(proposals_dir, fname)
                with open(fp, encoding="utf-8") as pf:
                    content = pf.read()
                for line in content.split("\n"):
                    if line.startswith("status:"):
                        s = line.split(":", 1)[1].strip()
                        if s in counts:
                            counts[s] += 1
                        break
            total_proposals = sum(counts.values())
            if total_proposals:
                lines.append("")
                lines.append("## 📊 系统健康\n")
                lines.append("| 状态 | 数量 |")
                lines.append("|:---|---:|")
                for s in ("pending", "approved", "rejected", "deferred", "implementing", "implemented", "verified", "failed"):
                    cnt = counts.get(s, 0)
                    if cnt:
                        icon = {"pending": "⏳", "approved": "✅", "rejected": "❌", "deferred": "⏭️",
                                "implementing": "🔧", "implemented": "📦", "verified": "🎯", "failed": "💥"}.get(s, "❓")
                        lines.append(f"| {icon} {s} | {cnt} |")
                lines.append(f"| **总计** | **{total_proposals}** |")
                lines.append("")
                if counts.get("pending", 0) > 50:
                    lines.append("⚠️ **待审提案超过 50 份，建议触发批量审查。**\n")
    except Exception as e:
        logger.warning("Failed to build system health dashboard: %s", e)
        # Don't fail the whole report — just skip this section

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

    # GitHub trending findings
    if trending_findings:
        lines.append("## 🌟 GitHub 热榜\n")
        for i, f in enumerate(trending_findings, 1):
            score_bar = "█" * min(f["score"], 10)
            lines.append(f"### {i}. [{f['title']}]({f['url']})")
            lines.append(f"📁 {f['source_name']} | ⭐ {f['score']}/10 {score_bar} | {f['summary']}")
            if f.get("insights"):
                lines.append(f"💡 {' | '.join(f['insights'])}")
            if f.get("actions"):
                lines.append("📋 **建议行动:**")
                for a in f["actions"]:
                    lines.append(f"  - {a['action']}（收益: {a['benefit']}, 工作量: {a['effort']}）")
            lines.append("")

    # Arxiv findings
    if arxiv_findings:
        lines.append("## 📄 Arxiv 论文\n")
        for i, f in enumerate(arxiv_findings, 1):
            score_bar = "█" * min(f["score"], 10)
            lines.append(f"### {i}. [{f['title']}]({f['url']})")
            lines.append(f"📅 {f.get('published', '')} | ⭐ {f['score']}/10 {score_bar} | {f.get('summary', '')[:100]}")
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
    lines.append("| 来源 | 状态 | 延迟 | 信息 |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| AI HOT | {_status_icon(aihot_status['status'])} "
        f"| {aihot_status.get('latency_ms', '-')}ms "
        f"| {aihot_status.get('error', '-')} |"
    )
    lines.append(
        f"| GitHub 热榜 | {_status_icon(trending_status['status'])} "
        f"| {trending_status.get('latency_ms', '-')}ms "
        f"| {trending_status.get('error', '-')} |"
    )
    lines.append(
        f"| Arxiv 论文 | {_status_icon(arxiv_status['status'])} "
        f"| {arxiv_status.get('latency_ms', '-')}ms "
        f"| {arxiv_status.get('error', '-')} |"
    )

    lines.append(f"\n---")
    lines.append(f"> ⚖️ v3 自动生成 | 评分阈值: {MIN_SCORE} | 提案阈值: {PROPOSAL_SCORE}")

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
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(template)

    saved = 0

    # Load existing proposal URLs for dedup (source + normalized URL as key)
    from urllib.parse import urlparse, urlunparse
    existing_keys = set()
    try:
        for fname in os.listdir(proposals_dir):
            if not fname.endswith(".md") or fname in ("INDEX.md", "TEMPLATE.md", "REVIEWED.md"):
                continue
            fpath = os.path.join(proposals_dir, fname)
            with open(fpath, encoding="utf-8") as pf:
                content = pf.read()
            if "status: pending" in content or "status: approved" in content or "status: verified" in content:
                for line in content.split("\n"):
                    if line.startswith("source_url:"):
                        url = line.split(":", 1)[1].strip()
                        if url and url != "~":
                            # Normalize: strip query/fragment for stable dedup
                            parsed = urlparse(url)
                            normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                            existing_keys.add(normalized)
                        break
    except Exception as e:
        logger.warning("Failed to scan existing proposals for dedup: %s", e)

    from urllib.parse import urlparse, urlunparse as _urlunparse
    
    for f in findings:
        if not f.get("actions"):
            continue
        # Dedup by normalized source URL
        source_url = f.get("url", "")
        if source_url:
            try:
                parsed = urlparse(source_url)
                norm_url = _urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                if norm_url in existing_keys:
                    logger.debug("Skipping duplicate proposal by URL: %s", source_url)
                    continue
                existing_keys.add(norm_url)
            except Exception:
                pass
        # Generate proposal filename from title + hash
        slug = (f.get("title", "proposal"))[:60].strip()
        slug = "".join(c if c.isalnum() or c in "._- " else "" for c in slug)
        slug = slug.strip().replace(" ", "_")[:50] or "proposal"
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
            f"category: {f.get('source', 'N/A')}",
            f"approved_at: ~",
            f"implemented_at: ~",
            f"verified_at: ~",
            f"failure_reason: ~",
            f"rollback_sha: ~",
            "---",
            "",
            f"# 📋 {f.get('title', '未命名提案')}",
            "",
        ]

        # One-line summary of what this is
        raw_summary = f.get("summary", "（无摘要）")
        desc = raw_summary.split("—", 1)[-1].strip() if "—" in raw_summary else raw_summary
        source_icon = {"GitHub 热榜": "📦", "Arxiv": "📄", "AI HOT": "🔥"}.get(f.get("source", ""), "📌")
        lines.append(f"> {source_icon} **{f.get('source', 'N/A')}** | ⭐ {f.get('score', 0)}/10 | {f.get('url', 'N/A')}")
        lines.append("")
        lines.append("## 这是什么")
        lines.append(f"{desc[:300]}")
        lines.append("")

        if f.get("insights"):
            lines.append("## 为什么对 Hermes 重要")
            for insight in f["insights"]:
                lines.append(f"- {insight}")
            lines.append("")

        if f.get("actions"):
            lines.append("## 建议行动")
            for a in f["actions"]:
                lines.append(f"- **{a.get('action', '')}**")
                lines.append(f"  - 📈 收益: {a.get('benefit', '')}  ⏱ 工作量: {a.get('effort', '')}  🏷️ {a.get('category', '')}")
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
            "pending → deferred",
            "implemented → failed → rolled_back",
            "```",
            "",
            "### 失败回滚",
            "失败时编辑 frontmatter，填写 `failure_reason` 和 `rollback_sha`。",
            "",
            "### 审批操作",
            "- 通过: 将 frontmatter 中 `status` 改为 `approved`",
            "- 拒绝: 将 frontmatter 中 `status` 改为 `rejected`",
            "- 搁置: 将 frontmatter 中 `status` 改为 `deferred`",
            "- 实施后: 依次更新为 `implementing` → `implemented` → `verified`",
            "",
            "---",
            f"> 由 Hermes Learner v3 自动生成 | {date_str}",
        ])

        try:
            # Atomic write: temp file + rename
            tmp_path = prop_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as pf:
                pf.write("\n".join(lines) + "\n")
            os.replace(tmp_path, prop_path)
            saved += 1
        except Exception as e:
            logger.warning("Failed to save proposal %s: %s", prop_name, e)
            try:
                os.remove(tmp_path)
            except Exception:
                pass

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
    parser.add_argument("--source", choices=["aihot", "trending", "arxiv", "all"], default="all")
    args = parser.parse_args()

    # Centralized seen loading — once at start, write once at end
    seen = load_seen()
    
    logger.info("=== Hermes Learner v3 开始 === (数据源: AI HOT + GitHub热榜 + Arxiv)")

    aihot_findings, aihot_status = [], {"status": "n/a", "count": 0}
    trending_findings, trending_status = [], {"status": "n/a", "count": 0}
    arxiv_findings, arxiv_status = [], {"status": "n/a", "count": 0}

    if args.source in ("aihot", "all"):
        logger.info("🔥 扫描 AI HOT...")
        aihot_findings, aihot_status = fetch_aihot(hours=24, seen=seen)
        logger.info("  AI HOT: 获取 %s 条, 收录 %s 条", aihot_status.get("total_fetched", "?"), aihot_status["count"])

    if args.source in ("trending", "all"):
        logger.info("🌟 扫描 GitHub 热榜...")
        trending_findings, trending_status = fetch_github_trending(days=7, seen=seen)
        logger.info("  GitHub热榜: 收录 %s 条", trending_status["count"])

    if args.source in ("arxiv", "all"):
        logger.info("📄 扫描 Arxiv 论文...")
        arxiv_findings, arxiv_status = fetch_arxiv(days=3, seen=seen)
        logger.info("  Arxiv: 收录 %s 条", arxiv_status["count"])

    report = format_report(aihot_findings, trending_findings, arxiv_findings,
                           aihot_status, trending_status, arxiv_status)
    now = datetime.now(CST)
    date_str = now.strftime("%Y-%m-%d")
    report_path = os.path.join(LEARNINGS_DIR, f"{date_str}.md")

    if args.dry_run:
        print(report)
        # Preview what proposals would be generated
        prop_count = sum(1 for f in aihot_findings + trending_findings + arxiv_findings if f.get("actions"))
        if prop_count:
            print(f"\n---\n📋 将生成 {prop_count} 份提案")
        logger.info("=== 干跑完成 ===")
        return

    os.makedirs(LEARNINGS_DIR, exist_ok=True)
    # Atomic write: temp + rename
    tmp_path = report_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(report)
    os.replace(tmp_path, report_path)

    # Save seen items once — after all sources have completed
    save_seen(seen)
    
    update_index(date_str)
    saved = save_proposals(aihot_findings + trending_findings + arxiv_findings, date_str)
    proposals_dir = os.path.join(HERMES_HOME, "proposals")
    update_proposal_index(proposals_dir)
    logger.info("✅ 报告已保存: %s", report_path)
    logger.info("📊 总计: %s 条 (AI HOT %s + 热榜 %s + Arxiv %s) | 高价值: %s 条 | 提案: %s 份",
                len(aihot_findings) + len(trending_findings) + len(arxiv_findings),
                len(aihot_findings), len(trending_findings), len(arxiv_findings),
                sum(1 for f in aihot_findings + trending_findings + arxiv_findings if f["score"] >= PROPOSAL_SCORE),
                saved)
    logger.info("=== Hermes Learner v3 完成 ===")


if __name__ == "__main__":
    main()
