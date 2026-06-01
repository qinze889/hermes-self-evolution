# 🧠 Hermes Self-Evolution System V3.3

自主学习与自我进化系统 — 每日 AI 资讯扫描 → 评分筛选 → 提案生成 → 审批→执行→验证完整闭环。

## 架构

```
AI HOT + GitHub热榜 + Arxiv
        │
        ▼
learner v3 ──→ 评分 + 去重 + 提案生成
        │
        ├──→ learnings/YYYY-MM-DD.md (每日报告)
        ├──→ proposals/*.md (YAML 状态机)
        ├──→ constitution/CONSTITUTION.md (每周吸收到 SOUL)
        └──→ dashboard/ (Web 进化日志 + 提案管理 + 自动实施)
```

## 目录

- `learner/` — 学习引擎核心脚本（systemd timer 每日 03:00 执行）
  - `hermes_learner.py` — V3.2 主引擎（AI HOT + GitHub + Arxiv 三源）
  - `absorb_learnings.sh` — 学习吸收管道（每周一 05:00 吸收到 SOUL.md）
  - `list_pending_proposals.sh` — 提案审查（每周一 06:00 批量审核）
  - `implement_proposal.py` — 提案自动执行器（GPT-5.4 子代理）
- `constitution/` — Hermes 宪法（最高准则，用户编辑）
- `learnings/` — 每日学习报告归档（评分 ≥3 分入选）
- `proposals/` — 自动生成的改进提案（评分 ≥7 分，9 种状态）
- `dashboard/` — Flask API + Next.js 进化日志 Web 面板 + 提案审批 UI
- `skill/` — SKILL.md + 完整参考文档（审查报告、数据源说明、实施记录等）

## 部署

1. `learner/hermes_learner.py` → `~/.hermes/scripts/`
2. `constitution/CONSTITUTION.md` → `~/.hermes/`
3. `dashboard/app_evolution.py` → `gateway-dashboard/app.py`
4. `dashboard/page.tsx` → `gateway-dashboard/next/src/app/admin/evolution/`
5. 设置 systemd timer 每日执行 learner

## 提案状态机

```
pending → approved → implementing → implemented → verified
pending → rejected
pending → deferred
implemented → failed → (可重试)
```

## V3.3 新特性

- 完整闭环：intake → 提案 → 审查 → 吸收 → 实施 → 验证
- 自动实施管道：已批准提案自动调度 GPT-5.4 子代理执行
- 技能内化面板：UI 直接发起 skill 内化提案
- 三源提案生成：GitHub + Arxiv + AI HOT 均可达 ≥7 分
- 提案去重 + 原子写入 + 竞态覆盖修复
