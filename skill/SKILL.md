---
name: hermes-self-evolution
description: "Hermes 自主学习与自我进化系统 V3 — 每日学习引擎 + 提案系统 + 管理面板 UI。How to set up and maintain the Hermes daily self-improvement pipeline, including learner script, proposal state machine, Flask API, and Next.js evolution dashboard."
version: 3.3.0
metadata:
  hermes:
    tags: [hermes, self-evolution, constitution, learning, systemd, aihot, dashboard, proposals]
    related_skills: [hermes-gateway-connectivity, session-workflow, external-web-services]
---

# Hermes Self-Evolution System V3

## Architecture

```
AI HOT (aihot.virxact.com) + GitHub热榜 + Arxiv
        │
        ▼
systemd timer (每日 03:00 CST)
        │
        ▼
learner v3 ──→ 评分 + 去重 + 提案生成
        │
        ├──→ ~/.hermes/learnings/YYYY-MM-DD.md
        ├──→ ~/.hermes/proposals/*.md (YAML frontmatter + 状态机)
        ├──→ ~/.hermes/proposals/INDEX.md
        ├──→ ~/.hermes/scripts/implement_proposal.py (V3.3)
        │         └──→ GPT-5.4 (Beef API) 子代理实施
        └──→ Flask API /api/evolution
              │
              ▼
Next.js /admin/evolution (三栏: 报告列表 | 内容 | 提案审批+自动实施)
```

## V3 Key Design Decisions

### Direction Filtering

- **AI HOT now generates proposals too** (score ≥7). `AIHOT_PROPOSAL_SCORE` removed in V3.1.
  - Previously hard-blocked (`AIHOT_PROPOSAL_SCORE = 999`). Changed in V3.1: removed the hard block AND the `actions=[]` clearing in `fetch_aihot()`. Items scoring ≥7 now call `generate_actions()` like GitHub/Arxiv items.
  - Most AI HOT items still score low (general news, no keyword hits), so few actual proposals emerge. The scoring system naturally filters.
- **GitHub Trending + Arxiv = proposal sources**. `PROPOSAL_SCORE = 7`.
  - GitHub trending repos and Arxiv papers generate proposals when they match improvement keywords (skills, tools, token optimization, context compression, memory management).
  - **The user directed**: "你去GitHub上可以进行广泛的搜索" (search GitHub broadly for improvements).
- **Action templates must be source-aware**: Use the finding's title, source type (GitHub/Arxiv/AI HOT), and description to generate actions that reference the actual project. See "V3.1 内容生成优化" section below for details and examples. Avoid generic templates like "评估xxx是否可集成到 Hermes" without referencing what xxx actually does.

## Constitution

File: `/root/constitution.md`

System-level, user-edited only. Contains:
- Identity definition (user's personal AI assistant)
- Token discipline (DeepSeek priority, GPT quota protection)
- Self-evolution laws (daily learning, record everything, propose→review→apply)
- Service quality standards (verify before act, commander mode, visible results)
- Boundary constraints (no self-modification, no self-permission escalation)

## Daily Learner Setup

### Systemd Timer (system-level, survives reboots)

```bash
# /etc/systemd/system/hermes-learner.service
[Unit]
Description=Hermes Autonomous Learner
After=network.target network-online.target

[Service]
Type=oneshot
User=root
Environment="HERMES_HOME=/root/.hermes"
Environment="HOME=/root"
Environment="HTTP_PROXY=http://127.0.0.1:7890"   # needed if behind GFW
Environment="HTTPS_PROXY=http://127.0.0.1:7890"
ExecStart=/root/.hermes/hermes-agent/venv/bin/python /root/.hermes/scripts/hermes_learner.py
StandardOutput=journal
```

```bash
# /etc/systemd/system/hermes-learner.timer
[Unit]
Description=Daily Hermes self-improvement scan

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable hermes-learner.timer
systemctl start hermes-learner.timer
```

### Learner Script (v3.1 — learn_eval_propose.sh)

Script: `~/.hermes/scripts/learn_eval_propose.sh` (bash + Python 混合，已替代旧的 `hermes_learner.py`)

**Data sources:**
1. **AI HOT** — Fetches `mode=selected&since=24h` items. Uses browser User-Agent header. Timezone-aware CST→UTC conversion. **Now generates proposals** (score ≥7) since V3.1 removed `AIHOT_PROPOSAL_SCORE`. Previously hard-blocked per user direction (info-only). Most items score 2-6 (general news) so few proposals emerge naturally. See `references/data-source-quirks.md` for API details.
2. **GitHub 热榜 (proposal source)** — Searches GitHub via Search API for trending repos in AI agent ecosystem. **5 queries** (V3.1 reduced from 9 to reduce API calls and dedup waste): `topic:ai-agent`, `topic:mcp-server`, `topic:agent-framework`, `AI agent framework tool`, `MCP server tools LLM`. Each fetches up to 5 repos sorted by updated. Star bonus (+1 for >1000 stars) and agent/MCP keyword bonus (+1). Proposal threshold: `PROPOSAL_SCORE = 7`. Requires `GITHUB_TOKEN` (auto-loaded from `.env` if not in env).
3. **Arxiv 论文 (proposal source)** — Searches recent Arxiv papers via XML API. 4 queries: `AI agent tool`, `large language model agent framework`, `MCP model context protocol`, `autonomous agent LLM`. Each fetches up to 5 papers sorted by submission date. Public API, no auth needed. Same scoring and proposal generation. ⚠️ API quirks documented in `references/data-source-quirks.md`.

**Scoring system (`KW_SCORES`):**
- High (3pts): token, tokens, context, compression, prompt, cache, caching, memory, latency, cost
- Medium (2pts): agent, tool, skill, mcp, sandbox, permission, telemetry, eval, benchmark, routing, efficient, optimize, optimization, streaming, speed
- Low (1pt): hermes, 代理, 工具调用, 进化, 自我, autonomous, structured output, function call, 融资, 发布, 开源, 工作流, 框架
- Chinese keywords (2pt each): 模型, ai, 降价, 折扣, 供应链, 攻击, 安全, gpt, claude, deepseek, gemini
- Deprioritize (-3pts): gartner, 融资, funding, 排行, 排名, 榜单, remove unused, unused import, dead code, cleanup, typo, formatting, lint, linting, chore, refactor
- Items ≥3 appear in report; items ≥7 generate proposals automatically.

**V3 capabilities (beyond V1):**
- `generate_insight()` — per-item impact analysis (token cost, agent architecture, context management, tool chain, etc.)
- `generate_actions()` — specific suggestions with benefit/effort/category for high-score items
- `save_proposals()` — auto-creates structured proposal files with summary, Hermes impact, actions, approval checkbox
- `update_index()` — INDEX.md with dedup + sort newest first, preserves header content
- `http_get_json()` — returns (data, status, error_msg) tuple; catches HTTPError with status code + body

**Output files:**
- `~/.hermes/learnings/YYYY-MM-DD.md` — daily markdown report
- `~/.hermes/learnings/INDEX.md` — date-sorted index
- `~/.hermes/learnings/seen_items.json` — dedup across runs
- `~/.hermes/proposals/<date>_<slug>.md` — auto-generated proposals for ≥7 score items
- `~/.hermes/proposals/TEMPLATE.md` — proposal template (auto-created on first run)

**Usage:**
```bash
# Normal run (all sources: AI HOT + GitHub热榜 + Arxiv)
bash learn_eval_propose.sh

# Dry-run (print report only, don't write files)
bash learn_eval_propose.sh --dry-run

# Single source
bash learn_eval_propose.sh --source aihot
bash learn_eval_propose.sh --source trending
bash learn_eval_propose.sh --source arxiv
```

**Running with GitHub token:**
```bash
GITHUB_TOKEN=$(grep '^GITHUB_TOKEN=' ~/.hermes/.env | head -1 | cut -d= -f2-) bash learn_eval_propose.sh
```

### GitHub Token Setup

GitHub scanning hits 403 rate limit without authentication. **GitHub 热榜 (trending search) requires `GITHUB_TOKEN`.** Create a fine-grained personal access token:
1. Go to https://github.com/settings/tokens
2. Create fine-grained token with **no scopes** (read-only public repos is default)
3. Add to `~/.hermes/.env`: `GITHUB_TOKEN=github_pat_xxxx`
4. The learner script auto-loads `.env` if `GITHUB_TOKEN` is missing from the environment (parses `^GITHUB_TOKEN=` lines, skips `***` placeholders)
5. Systemd service can use `EnvironmentFile=/root/.hermes/.env` in the `[Service]` section for automatic injection

## Dashboard Integration

### Evolution Dashboard (V3.4 — 技能内化优先)

管理面板 `/admin/evolution` 现在必须把“当前已有技能的内化提升”放在第一优先级，而不是只展示外部学习提案。详见 `references/skill-internalization-evolution-ui-2026-05-31.md`。

**核心要求：**
- 默认 tab 是"技能内化"，顶部统计显示"我的技能 / 待内化 / 外部提案 / 已验证"。
- 技能数据来源：**实时扫描 `~/.hermes/skills/` 目录**（递归 `os.walk` 查找所有 SKILL.md，含嵌套子目录如 `autonomous-ai-agents/claude-code`），合并 `skills-audit.json` 中的审计判决（verdict/rating/composite）。不再依赖 `user-skills.json` 缓存文件。
- 面板布局：**条件显示**——左栏「报告列表」只出现在 reports tab，右栏「提案详情+执行日志」只出现在 proposals tab，skills/constitution/analytics tab 时干净的单栏布局。grid 列宽动态切换：`220px_1fr`, `1fr_350px`, 或 `1fr`。
- 每个技能卡片底部有 **「⚡开始内化」按钮**，点击调用 `POST /api/skill/internalize` 创建内化提案。

### Evolution Dashboard (V3.3 — 实施管道已集成)

管理面板 `/admin/evolution` — Next.js 三栏布局页面。

**功能（V3.3）：**
- **学习报告**：Markdown → HTML 渲染（标题/链接/表格/代码块）
- **提案管理**：状态筛选 + 关键词搜索，支持 9 种状态（含 `implementing`）
- **宪法编辑**：实时编辑 `SOUL.md`
- **分析面板**：状态分布图 + 风险分布 + 平均评分
- **实施管道**（V3.3 新增）：自动执行已批准提案，GPT-5.4 子代理完成

**提案操作（7 按钮）：**
| 按钮 | 触发条件 | API |
|------|----------|-----|
| 批准 | pending | POST `/api/proposal/<f>/approve` |
| 拒绝 | pending | POST `/api/proposal/<f>/approve` |
| 搁置 | pending | POST `/api/proposal/<f>/defer` |
| **自动实施** | **approved** | **POST `/api/proposal/<f>/exec` (V3.3)** |
| 手动完成 | approved | POST `/api/proposal/<f>/implement` |
| 验证通过 | implemented | POST `/api/proposal/<f>/verify` |
| 验证失败 | implemented | POST `/api/proposal/<f>/verify` |

**Flask API 端点：**
- `GET /api/evolution` — 报告列表+内容+提案列表
- `GET /api/evolution/stats` — 聚合统计
- `GET /api/proposal/<file>` — 单个提案内容
- `POST /api/proposal/<file>/approve` — 批准/拒绝
- `POST /api/proposal/<file>/defer` — 搁置
- `POST /api/proposal/<file>/implement` — 标记实施完成
- `POST /api/proposal/<file>/verify` — 验证通过/失败
- `POST /api/proposal/<file>/exec` — **自动实施（V3.3 新增）**
- `POST /api/skill/internalize` — **技能内化（V3.4 新增）**：接收 `{"name": "skill-name"}`，读取对应 SKILL.md 元数据，在 `~/.hermes/proposals/` 创建内化提案（含当前文件大小、行数、内化四项目标和实施路径）。

文件：`/root/gateway-dashboard/next/src/app/admin/evolution/page.tsx`，Flask 端在 `/root/gateway-dashboard/app.py`。

### Skills 审计仪表盘

独立的 Skills 质量管理页面（`/skills`），通过 DeepSeek API 对所有 Skill 进行工程管理视角评分。

**两阶段审计模式**（2026-05-30 引入）：DeepSeek 初评 → GPT (Beef API) 元审查。单一模型审计存在系统性偏差（过于宽松、缺乏横向对比），GPT 作为严格审查者能识别评分偏差、漏判合并、漏判删除。详见 `references/skills-audit-system.md`。

审计结果缓存 24 小时，支持手动刷新。导航栏已添加 Wrench 图标入口。

**GPT 审查调用**: 使用 Beef API (`custom:beef-api`, 模型 `gpt-5.4`)，**必须用 curl 发送**（Python urllib 在 Beef API 返回 403）。Key: `BEEF_API_KEY` in `.env`。分批发（每批≤15个技能），避免 prompt 过大导致超时。

**完整审计工作流**: 详见 `references/skills-audit-workflow.md`。核心：DeepSeek 初筛 → GPT-5.4 8维度严格审查 → 按审查结果合并/改造 → **验证网站展示**。用户个人技能在 `/skills` 页有独立"我的技能"卡片视图。

**改动后必须验证网站**: 改动 skills 后要重建缓存 + 重启前端，否则用户看不到变化。`/api/user-skills` 端点提供用户个人技能数据。

### Architecture

```
Browser → Nginx :443 → Next.js :3000 → /admin/evolution (page.tsx)
                                          ↓ fetches
                                     /api/evolution → Flask :5000
                                     /api/proposal/<file> → Flask :5000
```

### Next.js Page

File: `/root/gateway-dashboard/next/src/app/admin/evolution/page.tsx`

Three-column layout:
- **Left**: Date-sorted report list, click to switch
- **Center**: Report content rendered as HTML from markdown
- **Right**: Proposal panel with status icons, risk colors, click for detail modal

Built with `var(--color-*)` CSS variables matching the admin dashboard theme. Basic Auth via sessionStorage.

### Flask API Endpoints

**GET `/api/evolution`** — Returns:
```json
{
  "reports": [{"date": "2026-05-23", "size": 8738, "size_kb": 8.5}],
  "total": 1,
  "latest": "# 🧠 Hermes 学习报告 — 2026-05-23\n...",
  "constitution_exists": true,
  "proposals": [{"file": "...", "status": "pending", "risk": "high", "score": 9, "title": "...", "source": "2026-05-23", "url": "https://..."}]
}
```

Supports `?date=YYYY-MM-DD` to load a specific day's report.

**GET `/api/proposal/<filename>`** — Returns:
```json
{
  "file": "2026-05-23_feat_xxx_hash.md",
  "content": "---\nstatus: pending\n..."
}
```

**POST `/api/proposal/<filename>/approve`** — Approve or reject a proposal:
```json
// Request
{ "status": "approved", "comment": "P0, implement immediately" }

// Response
{ "ok": true, "status": "approved" }
```
Updates YAML frontmatter `status` field, appends `## ✅ 已通过 (2026-05-23 19:00 CST)` with comment blockquote. Returns 400 if status is not "approved" or "rejected".

### Navigation Update

Add link to all nav bars:
```html
<a href="/admin/evolution">🧠 进化日志</a>
```

## Verification

```bash
# Manual trigger
systemctl start hermes-learner.service

# Check output
journalctl -u hermes-learner.service --no-pager

# Check API
curl -u admin:$PASS http://localhost:5000/api/evolution | jq '.total'

# Check page
curl -u admin:$PASS -s http://localhost:5000/admin/evolution | grep -c 'evolution'
```

## Pitfalls

### Setup
- **GH API 403**: Missing GITHUB_TOKEN. Fine-grained token needs zero scopes (public repo read is default).
- **AI HOT 403**: Missing or wrong User-Agent. Must use browser UA string exactly.
- **Arxiv API 2026年变更**: API 已从 HTTP→HTTPS 重定向。必须用 `https://export.arxiv.org/`。Arxiv 返回 XML (Atom feed)，不是 JSON。**切勿使用 `http_get_json()`**。直接用 `urllib.request.urlopen()` + `xml.etree.ElementTree` 解析。突发请求触发 429，需加退避重试（3次, sleep 5s/10s）。详见 `references/data-source-quirks.md`。
- **Mihomo 重启端口被占**: learner 走 proxy 时如果 mihomo 刚重启，旧进程可能仍占 :7890。新 mihomo 报 `bind: address already in use`，所有 proxy 请求返回 `Connection refused`。修复: mihomo systemd service 加 `ExecStartPre=/bin/bash -c 'kill $(lsof -ti:7890) 2>/dev/null || true'`。
- **Log noise**: The learner is Type=oneshot — runs once and exits. Don't expect it to stay running.

### Scoring
- **评分可超 10 (V3已修复)**: `score = min(score, 10)` 已 cap。`score_bar` = `"█" * min(score, 10)`。
- **关键词误判 (V3已修复)**: chore/remove unused/imports/dead code/cleanup/typo/formatting/lint/refactor 已加入 `DEPRIORITIZE_KW`，每题 -3 分。`chore: remove four unused stdlib imports` 评分从 7 降至 4，不再生成提案。
- **标题不能替代 body (V3已修复)**: GitHub findings 已保存 `summary: body[:300]` 和 `body: body` 字段。
- **低分项不写 seen (V3已修复)**: `seen[hid]` 写入已移至 `if score >= MIN_SCORE` 之外，所有扫描项均去重。

### Code
- **item_hash 脆弱 (V3已修复)**: 已改为 `f'{source}|{url}|{title}'` 联合 hash。
- **Markdown 表格列数不匹配 (V3已修复)**: `|---|---:|---:|---:|` 已对齐 4 列。
- **单 source 运行时另一个显示 ❌ (V3已修复)**: `_status_icon('n/a')` 返回 `⏭️`。
- **Proposal 文件名冲突 (V3已修复)**: 文件名加 8 位 hash suffix：`{date}_{slug}_{hash}.md`。
- **Proposal 无索引 (V3已修复)**: `update_proposal_index()` 自动生成 `proposals/INDEX.md`，按状态统计。
- **GITHUB_TOKEN 提取**: `.env` 中可能有注释行 `# GITHUB_TOKEN=`，提取时用 `grep '^GITHUB_TOKEN='` 而非 `grep GITHUB_TOKEN`。
- **单模型审计偏差 (CRITICAL)**: DeepSeek 审计存在系统性偏差——打分偏高（均分 7.2，94/122 KEEP）、缺乏横向对比、主要依据描述而非文件内容。**必须用 GPT (Beef API, gpt-5.4) 做第二阶段元审查**纠正评分偏差和漏判合并/删除。详见 `references/skills-audit-system.md`。
- **Beef API urllib 403**: Python `urllib` 访问 Beef API 返回 403。改用 `curl -sk https://beefapi.com/v1/chat/completions -d @payload.json`。Provider: `custom:beef-api`，模型: `gpt-5.4`/`gpt-5.5`。
- **iLink Bot 配对限制**: 已注册微信号无法二次配对新 Bot。iLink 平台返回 refused 状态，微信端报"网关服务安装失败"。已在 `/register` 页加黄色警告提示用户使用未注册微信扫码。后端 `_normalize_bot_qr_status()` 检测已添加 "already_bound" 状态。
- **execute_code + read_file 文件污染 (CRITICAL)**: `execute_code` 内调用 `read_file()` 返回的行内容带 `     N|` 前缀。如果直接用 `write_file()` 写回，文件每一行都会多出 `N|` 前缀导致语法错误。正确做法：在 execute_code 中用 `terminal("cat /path")` 获取原始内容，或写 fix 脚本到 `/tmp` 再用 `terminal` 执行。已污染文件用 `re.match(r'^\s*\d+\|(.*)', line)` 剥离前缀修复。
- **Next.js build 冲突**: 如果 "Another next build process is already running"，先 `pkill -f "next build"` 再重试。
- **browser_navigate 走 127.0.0.1**: 外网 IP 可能超时，用 `http://127.0.0.1:3000` 直连。
- **cache 文件源变更时必须清理旧缓存**: 改 `_load_user_skills_snapshot()` 从 `user-skills.json` 切换为实时扫描后，旧缓存文件 `/root/.hermes/cache/user-skills.json` 会 stale 且干扰诊断。必须 `rm -v /root/.hermes/cache/user-skills.json`。
- **添加新 UI 面板/API 后检查所有遗留组件**: 添加技能内化 tab 时容易遗留不相关面板（左栏报告列表、右栏提案详情在所有 tab 显示）。正确做法：面板按 active tab 条件渲染 + grid 列宽动态调整。
- **TSX 改动必须 rebuild**: Next.js 生产模式 (`next start`) 使用预构建产物，编辑 page.tsx 后必须 `npm run build && systemctl restart next-frontend` 才能生效。
- **Skills 改动必须验证网站**: 合并/改造 skill 后，用户看不到变化会不满。流程：重新扫描缓存 → 确认 API → rebuild Next.js → 验证页面 HTTP 200。详见 `references/skills-audit-workflow.md`。
- **patch escape-drift**: 如果 `patch()` 报 "Escape-drift detected"，不要重试不同转义。直接改用 `terminal()` 的 Python heredoc 或 `/tmp` 脚本修复。
- **GitHub search OR on qualifiers**: GitHub Search API **does not** support `OR` between qualifiers. `topic:ai-agent+OR+topic:mcp-server` returns a 422. Use separate queries or text search instead.
- **Auto .env loading**: The `GITHUB_TOKEN=***` placeholder in `.env` is NOT a valid token. The auto-loader skips lines where value is exactly `***`. Script still works without a token but hits rate limits quickly.
- **AIHOT_PROPOSAL_SCORE is removed**: After removing, verify that AI HOT items actually get scored ≥7 before expecting proposals. Most score 2-6 due to general-industry news keywords.
- **Testing rate limits**: Running `--dry-run` multiple times in a row exhausts GitHub API rate limits. Wait 60+ seconds between tests on unauthenticated requests.
- **自动实施/验证闭环补充（2026-05-31）**: `/admin/evolution` 已补齐后台执行器、执行日志、自动验证器和状态守卫。后续维护时参考 `references/autonomous-execution-verification-2026-05-31.md`，重点确认：所有管理 API 带 `@require_auth`、状态流不能只靠 UI disabled、自动执行器禁止 `shell=True`、failed 状态必须可重试、TSX 改动后必须 rebuild+重启 Next 服务。
- **Learner 代码改动后必须走 writer-critic-loop**: 用 GPT-5.4 (Beef API, curl 直连) 做 8 维度审查，迭代到 PASS。单次改动可能引入 regression（如 generate_insight source 缺失、dedup 格式不匹配等隐性 bug），DeepSeek 单模型审查存在系统性偏差。详见 `references/learner-code-review-2026-05-31.md`。

### Learner Code Quality (2026-05-31 GPT-5.4审查)

- `save_proposals()` 去重必须用 URL 标准化（scheme+netloc+path），不能解析 Markdown 行文本
- 所有文件写入必须原子化（tmp + os.replace），见 `references/learner-code-review-2026-05-31.md` 完整列表
- Shell 脚本禁止硬编码年份，用 `20??-??-??.md` 匹配

### V3.2 核心修复 (2026-05-31 GPT-5.4 审查驱动)

经过 GPT-5.4 三轮严格代码审查（30,581 tokens），修复了 12 个严重问题 + 15 个中等问题：

**严重修复：**
1. `generate_insight()` 三源 source 参数缺失 → 分析内容系统性失真。修复：统一传完整 item dict。
2. Arxiv 429 重试 `root` 未初始化 → `UnboundLocalError`。修复：`root=None` + 空值检查。
3. `save_proposals()` dedup 解析格式与写入格式不匹配 → 去重完全失效。修复：改为 URL 标准化去重（`source_url` 去 query/fragment）。
4. `seen` 在三源函数中各自 `load/save` → 竞态覆盖风险。修复：`main()` 集中管理，传 `seen` 参数给各源，最后原子写回。
5. 所有文件写入非原子 → 中断产生损坏文件。修复：`tmp + os.replace()` 原子替换。
6. Shell 脚本 `2026-*.md` 硬编码 → 跨年静默失效。修复：`20??-??-??.md` 通配 + `nullglob`。
7. `score_item()` 未使用参数清理 + GitHub 评分 bonus 未 cap。
8. 报告表格缺少表头 → Markdown 渲染不稳定。
9. `format_report()` 异常完全吞没 → 健康面板静默失效。
10. 提案状态机文档与实现不一致（`deferred`/`rolled_back`）。

**中等问题：**
- 关键词匹配子串误判、标题 bonus 几乎不触发、Arxiv `days` 参数未使用
- `.env` 文件未用 context manager、多处 `except: pass` 吞异常
- 多个 `open()` 未指定 `encoding="utf-8"`
- `update_index()` 用子串去重可能误删

**审查方法论**：采用 writer-critic-loop 流程——DeepSeek 写代码 → GPT-5.4(Beef API) 三轮审查 → 迭代至 PASS。每轮记录 `BEEF_USAGE` token 消耗。

### 提案审核日志 (`proposals/REVIEWED.md`)

Created to track what happened to each proposal beyond the YAML frontmatter status field. Manually maintained decision log with columns: date, proposal name, decision, reason.

```markdown
# 📋 提案审核日志

## 审核记录

| 日期 | 提案 | 决策 | 理由 |
|------|------|------|------|
| 2026-05-25 | feat(prompt-builder)... | verified | 用户审核后实施，已通过测试 |
```

### 学习吸收管道 (weekly agent-mode cron)

Script: `~/.hermes/scripts/absorb_learnings.sh`

An **agent-mode** cron job (`absorb-learnings-to-soul`) running every Monday 05:00 (`0 5 * * 1`). The script outputs structured data (new learning files, pending proposals, recently approved proposals, current SOUL.md summary). The agent reads this and decides what to absorb into `SOUL.md`:

1. Finds learning files newer than last absorb run
2. Extracts high-value suggestions (score ≥ 8) and actionable recommendations
3. Reads `SOUL.md` current content
4. Writes new `## 每周吸收：YYYY-MM-DD` or `## 已实施改进` sections at the bottom (append only, no overwrite)
5. Updates a marker file to avoid re-processing

**This closes the "not a complete closed loop" gap** — learnings now have a path back into the system's permanent knowledge (SOUL.md), linking the intake→propose→review→absorb cycle.

### 提案审查 Agent (weekly agent-mode cron)

Script: `~/.hermes/scripts/list_pending_proposals.sh`

An **agent-mode** cron job (`review-proposals`) running every Monday 06:00 (`0 6 * * 1`). The script outputs:
- Last 3 learning reports (head only)
- All pending proposals with score/risk/source URL  
- Last 5 review history entries from REVIEWED.md

The agent:
1. Reads each pending proposal's full content
2. Makes a decision: **approved** (implementable, relevant), **rejected** (noise, dupe), **deferred** (too vague, needs prerequisites)
3. Edits the proposal frontmatter `status` field
4. Appends a decision record to `proposals/REVIEWED.md`

Review rules:
- **Approved if**: directly optimizes token/performance, adds new capability, fixes observed issue, improves stability/security
- **Rejected if**: no concrete action, dupe with existing, irrelevant to Hermes (pure academic), high effort + low benefit
- **Default when uncertain**: deferred (conservative)

#### Review execution steps (batch mode):

1. **Read all pending proposals** — Use `terminal("cat /path/*.md | head -35")` for full content, not `read_file()` which truncates at ~80 lines. The learner script may add Chinese characters in filenames that trigger read-dedup blocks.
2. **Categorize** — Approved (directly integrable code/MCP/tools), Rejected (unrelated content), Deferred (everything else).
3. **Update frontmatter** — Use shell loop with proper quoting: `find /root/.hermes/proposals/ -name '*.md' | while read f; do sed -i 's/^status: pending$/status: approved/' "$f"; done`. **Do NOT iterate filenames via Python or an unquoted bash array** — filenames containing Chinese characters (e.g. `HarnessScaffold_与_AI_智能体术语辨析...md`) will break string iteration and silently skip files.
4. **Regenerate INDEX.md** — After all fronts are updated, the INDEX.md top counts (`| pending | N |`) become stale. Rebuild with: `grep -l '^status: approved$' *.md | wc -l` per status. Rewrite the full INDEX.md using the revised counts.
5. **Update REVIEWED.md** — Append decision log. For large batches (50+ proposals), write individual entries for approved/rejected items and a summary line for deferred: e.g. `| 2026-05-26 | [其余 N 份提案](—) | deferred | 理由概述 |`. This keeps REVIEWED.md readable while preserving full categorization.

#### Pitfalls specific to batch review:
- **Non-ASCII filenames in sed/for loops**: Chinese characters (`与`, `_`, `AI` in filename) cause `for f in *.md` in bash or Python's `os.listdir()` + string concatenation to fail. Always use `find ... -exec` or quoted `while read` loops with `"$f"`.
- **Triggering read-dedup on `read_file`**: The system blocks re-reading files you've already read. Use `terminal("cat PROPOSAL.md | head -N")` to bypass dedup and get raw content without line-number prefix.
- **Deferred bloat**: Many proposals from the V3 learner are vague ("阅读 XXX 的 agent 架构设计" — no concrete integration plan). These are valid to defer, but if deferred count exceeds 50% of total, the learner's content generation needs attention (proposals too generic).
- **INDEX.md stale after status change**: The INDEX.md stores status counts in a markdown table that is NOT auto-regenerated. After any frontmatter status edit, you MUST regenerate INDEX.md or the dashboard API (`GET /api/evolution`) will show wrong counts.
- **REVIEWED.md format**: Keep entries one-line-per-decision. For large batches, a deferred summary line is acceptable — future reviews can promote individual items from deferred to approved if conditions change.
- **REVIEWED.md literal `\n` from Python/awk insertion**: When building review records in Python and inserting into REVIEWED.md via `awk`, `"\\n".join(records)` produces literal `\n` in the file (not actual newlines). Fix: after insertion, run `python3 -c "open('REVIEWED.md','w').write(open('REVIEWED.md').read().replace('\\\\n','\n'))"`. Better: avoid awk insertion entirely; use Python to read the file, splice the new lines before the footer, and write back.
- **Heredoc 引号陷阱**: Shell heredocs with quoted delimiters (`<< 'EOF'`) suppress all variable expansion. When building INDEX.md with embedded `$(grep ... | wc -l)` commands, the unquoted form `<< EOF` is required. Always verify the written file contains resolved values, not raw `$(...)` literals.
- **批量提案读取策略**: For 20–30 pending proposals, read in batches of ~9 via `execute_code` calling `terminal("cat <path>")` per file. Each `execute_code` block handles one batch. Avoid `cat *.md` which can hit the 50KB stdout cap on large sets. Check `grep -rl '^status: pending$' *.md` first to get the exact file list.

### 提案去重 (V3.1)

`save_proposals()` now scans existing proposals before writing:
1. Loads all existing proposal files with `status: pending/approved/verified`
2. Extracts action texts (lines matching `- **{action}** │ benefit: ...`)
3. If ALL actions in a new finding already exist in the set, the proposal is skipped
4. New actions are added to the set as they're written (prevents same-run duplicates)

This prevents "审计 memory 条目冗余度" from being proposed daily for every GitHub repo.

### 健康仪表盘 (V3.1)

`format_report()` now injects a `## 📊 系统健康` table after the daily overview section. Shows:
- Proposal counts by status (pending/approved/rejected/deferred/implemented/verified/failed)
- Total proposals
- Warning if pending > 50

### 失败/回滚路径 (V3.1)

Proposal frontmatter now includes:
- `failure_reason: ~` — filled when implementation fails
- `rollback_sha: ~` — git SHA rolled back to

TEMPLATE.md and status flow diagram updated to document failure handling.

## Scheduled Tasks Summary (V3.1)

| Time | Task | Mode | Purpose |
|------|------|------|---------|
| 03:00 | `hermes-learner` | systemd timer | Collect, score, propose |
| 05:00 | `absorb-learnings-to-soul` | agent cron | Absorb into SOUL.md |
| 06:00 | `review-proposals` | agent cron | Review pending proposals |

> **V3.1 默认每日执行**：吸收和审查 cron 初始配置为每天运行（`0 5 * * *` 和 `0 6 * * *`），待流程稳定后可根据数据量调为每周。三个环节正好接力：学习报告生成后 2h 吸收、3h 审查，互不打架。

### Design (V3.1 gaps)
- **🔄 已接近完整闭环**: V3.1→V3.3 已构建 intake + 提案 + 审查 + 吸收 + **实施管道**的完整闭环。
- **实施管道（V3.3 已实现）**: 新增 `/api/proposal/<file>/exec` 端点 +「自动实施」UI 按钮 + `implement_proposal.py` 脚本。GPT-5.4 (Beef API) 子代理自动执行已批准提案中的行动项，生成实施报告并回写提案状态。
- **仍需**: 验证器自动执行（当前仍需手动点"验证通过"）。
- **提案内容必须具体**: V3.1 的 `generate_actions()` 已从纯关键词 if-else 重写为来源感知的上下文生成。每个 action 引用项目名和链接，建议内容基于来源类型（repo/论文/新闻）和实际描述（MCP工具链/agent架构/价格变动）。不再生成"审计 memory 条目冗余度"这种与 repo 无关的万能建议。详见 `references/content-generation-patterns.md`。
- **提案太空泛的根因链**: (1) generate_actions 只看关键词不看来源类型 → (2) 把不同类内容混用同一套 if-else → (3) 万能建议脱离原文。修复方法：先按 source type 分支（GitHub/Arxiv/AIHOT），再基于 desc 做细粒度判断。每种 source type 的 action 必须引用具体项目名/论文标题。详见 `references/content-generation-patterns.md`。
- **提案格式**: 从"摘要 + 影响 + 建议"改为"这是什么 + 为什么对 Hermes 重要 + 建议行动"三栏结构。frontmatter 新增 `category` 字段。
- **宪法未真正联动**: 宪法是纯文档，learner 不读取它，proposal 不标注是否触犯"不能自己加工具权限"等约束。

### Workflow
- **开发流程**: 用户要求 GPT-5.5/Codex 负责审阅代码，Hermes Commander 负责实施改动。改后交付 GPT 复审。Do NOT ask for permission — just execute what GPT recommends.
- **批准提案的手动闭环执行（第一优先级）**:
  1. 从 `~/.hermes/proposals/*.md` 选择 `status: approved` 且低风险/高收益的提案，先把 frontmatter 改为 `status: implementing`。
  2. 派 Claude Code/DeepSeek 执行实现；HC 不亲自写代码，只做范围控制、审查和返工调度。
  3. 运行最小相关测试，优先用项目自带 `./scripts/run_tests.sh <test-file>`，不要直接假设 venv 已安装 pytest。
  4. 交给 Codex/GPT 做代码质量和安全复审；有问题必须立即返工并复审，直到 PASS。
  5. 通过后把提案回写为 `status: verified`，填写 `implemented_at` / `verified_at`，并追加实施记录；同步更新 `/root/pending_tasks.md`。
- **测试 reload/env 变量坑**: 如果测试通过 `importlib.reload(module)` 验证导入期环境变量（如 `HERMES_CONTEXT_FILE_MAX_CHARS`），必须在修改 env 前保存原始值，并在 `finally` 中先恢复 `os.environ` 到原始状态，再 reload 模块；仅依赖 `monkeypatch` 自动恢复会发生在 `finally` 之后，仍可能留下 stale 模块常量/默认参数。
- **引用**: 详见 `references/gpt-review-v3.md` 获取完整 GPT-5.5 审阅报告；详见 `references/closed-loop-iteration-2026-05-24.md` 获取首轮 verified 提案闭环记录。

### Gateway / Registration
- **`hermes gateway install` 交互式卡死**: 命令有两个连续提示 "Start the gateway now?" 和 "Auto-start on boot?"。Flask/shell 后台调用时用 `subprocess.run(..., input="y\ny\n")` 自动回复，否则 30s 超时返回非零退出码。
- **用户统计必须扫 state.db**: 不要只读 `pairing/*-approved.json`（仅覆盖审批模式用户）。open 模式 Bot（小黑、新注册）的用户需要扫描所有 profile 的 `state.db` 中 `SELECT DISTINCT user_id FROM sessions`，结合 `ADMIN_IDS` 环境变量区分管理员/普通用户。
- **Token index 需即时重建**: `get_user_token()` 创建新 token 后必须调用 `_rebuild_token_index()`，否则 `resolve_token()` 返回 None → 个人面板 404。
- 详见 `references/registration-fixes.md`。

### execute_code 文件污染坑 (CRITICAL)
- **症状**: `execute_code` 内调用 `read_file()` 返回的内容带行号前缀（如 `     1|content`）。直接用 `write_file()` 写回会污染文件，导致每行开头多出 `N|` 前缀。
- **正确做法**: 在 `execute_code` 中读写文件时，用 `terminal("cat /path")` 获取原始内容（无行号），或用 `terminal("python3 -c '...'")` 直读直写。
- **修复已污染文件**: 用正则 `re.match(r'^\s*\d+\|(.*)', line)` 剥离行号前缀。
