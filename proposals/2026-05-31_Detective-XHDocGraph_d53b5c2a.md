---
status: deferred
risk: high
source_report: 2026-05-31
source_url: https://github.com/Detective-XH/DocGraph
score: 11
category: GitHub 热榜
approved_at: ~
implemented_at: ~
verified_at: ~
failure_reason: ~
rollback_sha: ~
---

# 📋 Detective-XH/DocGraph

> 📦 **GitHub 热榜** | ⭐ 11/10 | https://github.com/Detective-XH/DocGraph

## 这是什么
Govern your documents like code. MCP server that indexes .md/.docx/.html/.pdf into a SQLite knowledge graph and runs drift audits — stale policies, conflicting research claims, superseded docs, undocumented code exports. 12 MCP tools incl. cross-reference graph, governance + provenance metadata, top

## 为什么对 Hermes 重要
- 📰 值得关注的行业动态

## 建议行动
- **分析 [Detective-XH/DocGraph](https://github.com/Detective-XH/DocGraph) 的 MCP 实现，评估注册为 Hermes 工具的可行性与工作量**
  - 📈 收益: 扩展 Hermes 工具链能力  ⏱ 工作量: 中  🏷️ tool

## 审批状态
- **状态**: `pending` → 待用户审批
- **风险等级**: `high`

### 状态流转
```
pending → approved → implementing → implemented → verified
pending → rejected
implemented → failed → rolled_back
```

### 失败回滚
失败时编辑 frontmatter，填写 `failure_reason` 和 `rollback_sha`。

### 审批操作
- 通过: 将 frontmatter 中 `status` 改为 `approved`
- 拒绝: 将 frontmatter 中 `status` 改为 `rejected`
- 实施后: 依次更新为 `implementing` → `implemented` → `verified`

---
> 由 Hermes Learner v3 自动生成 | 2026-05-31
