# 🧠 Hermes Self-Evolution System V3

自主学习与自我进化系统 — 每日 AI 资讯扫描 → 评分筛选 → 提案生成 → 审批执行。

## 架构

```
AI HOT / GitHub → learner.py → learnings/YYYY-MM-DD.md (每日报告)
                            → proposals/*.md (高分提案)
                            → dashboard/page.tsx (Web 进化日志)
```

## 目录

- `learner/` — 学习引擎核心脚本（systemd timer 每日执行）
- `constitution/` — Hermes 宪法（最高准则）
- `learnings/` — 每日学习报告归档
- `proposals/` — 自动生成的改进提案（YAML 状态机）
- `dashboard/` — Next.js 进化日志 Web 页面 + Flask API 路由

## 部署

1. `learner/hermes_learner.py` → `~/.hermes/scripts/`
2. `constitution/CONSTITUTION.md` → `~/.hermes/`
3. `dashboard/page.tsx` → `gateway-dashboard/next/src/app/admin/evolution/`
4. `dashboard/app_evolution.py` → 合并到 `gateway-dashboard/app.py`
5. 设置 systemd timer 每日执行 learner

## 提案状态机

```
pending → approved → implementing → implemented → verified
pending → rejected
implemented → failed → rolled_back
```
