---
status: rejected
risk: high
source_report: 2026-06-01
source_url: https://github.com/ahmed5bdelaal/luffa-agent-skills
score: 9
category: GitHub 热榜
approved_at: ~
implemented_at: ~
verified_at: ~
failure_reason: ~
rollback_sha: ~
---

# 📋 ahmed5bdelaal/luffa-agent-skills

> 📦 **GitHub 热榜** | ⭐ 9/10 | https://github.com/ahmed5bdelaal/luffa-agent-skills

## 这是什么
Provide AI agents with tools to interact with Luffa's platform, enabling automated workflows for service, management, and distribution tasks.

## 为什么对 Hermes 重要
- 📦 **ahmed5bdelaal/luffa-agent-skills**: Provide AI agents with tools to interact with Luffa's platform, enabling automated workflows for service, management, and distribution tasks.
- 🤖 Agent 设计：该项目的架构思路可参考用于改进 Hermes agent 层

## 建议行动
- **阅读 [ahmed5bdelaal/luffa-agent-skills](https://github.com/ahmed5bdelaal/luffa-agent-skills) 的 agent 架构设计，提取可复用模式**
  - 📈 收益: 改进 Hermes agent 层设计  ⏱ 工作量: 低  🏷️ agent

## 审批状态
- **状态**: `pending` → 待用户审批
- **风险等级**: `high`

### 状态流转
```
pending → approved → implementing → implemented → verified
pending → rejected
pending → deferred
implemented → failed → rolled_back
```

### 失败回滚
失败时编辑 frontmatter，填写 `failure_reason` 和 `rollback_sha`。

### 审批操作
- 通过: 将 frontmatter 中 `status` 改为 `approved`
- 拒绝: 将 frontmatter 中 `status` 改为 `rejected`
- 搁置: 将 frontmatter 中 `status` 改为 `deferred`
- 实施后: 依次更新为 `implementing` → `implemented` → `verified`

---
> 由 Hermes Learner v3 自动生成 | 2026-06-01
