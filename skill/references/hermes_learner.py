#!/usr/bin/env python3
"""Hermes 自主学习引擎 v3 — 系统级，每日执行。

数据源:
  1. AI HOT (aihot.virxact.com) — 中文 AI 行业动态
  2. GitHub Trending — 热门 AI Agent/MCP 仓库
  3. Arxiv — 最新 AI 论文

注意：hermes-agent 自身 PR 来源已被用户要求移除。
仅保留外部信息源：AI HOT（资讯）+ GitHub热榜（生态）+ Arxiv（论文）。

结果写入 ~/.hermes/learnings/YYYY-MM-DD.md

用法:
  python3 hermes_learner.py                # 正常执行
  python3 hermes_learner.py --dry-run       # 只输出，不写文件
  python3 hermes_learner.py --source aihot  # 只跑指定源
  python3 hermes_learner.py --source trending
  python3 hermes_learner.py --source arxiv

--source 选项: aihot, trending, arxiv, all
（已移除 github，不再扫描 hermes-agent 自身 PR/Issue）
"""
