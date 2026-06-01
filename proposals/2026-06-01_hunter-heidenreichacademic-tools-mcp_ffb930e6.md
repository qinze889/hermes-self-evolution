---
status: approved
risk: high
source_report: 2026-06-01
source_url: https://github.com/hunter-heidenreich/academic-tools-mcp
score: 10
category: GitHub 热榜
approved_at: ~
implemented_at: ~
verified_at: ~
failure_reason: ~
rollback_sha: ~
---

# 📋 hunter-heidenreich/academic-tools-mcp

> 📦 **GitHub 热榜** | ⭐ 10/10 | https://github.com/hunter-heidenreich/academic-tools-mcp

## 这是什么
MCP server giving LLM agents lean, identifier-routed tools to look up, read, and cross-reference academic papers across 7 providers (OpenAlex, arXiv, bioRxiv, ACL Anthology, Crossref, OpenCitations, Wikipedia).

## 为什么对 Hermes 重要
- 📦 **hunter-heidenreich/academic-tools-mcp**: MCP server giving LLM agents lean, identifier-routed tools to look up, read, and cross-reference academic papers across 7 providers (OpenAlex, arXiv, 
- 🔧 MCP 工具链：评估该实现是否可注册为 Hermes 原生工具

## 建议行动
- **分析 [hunter-heidenreich/academic-tools-mcp](https://github.com/hunter-heidenreich/academic-tools-mcp) 的 MCP 实现，评估注册为 Hermes 工具的可行性与工作量**
  - 📈 收益: 扩展 Hermes 工具链能力  ⏱ 工作量: 中  🏷️ tool
- **阅读 [hunter-heidenreich/academic-tools-mcp](https://github.com/hunter-heidenreich/academic-tools-mcp) 的 agent 架构设计，提取可复用模式**
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
