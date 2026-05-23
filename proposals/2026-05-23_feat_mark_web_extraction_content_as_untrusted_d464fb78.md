---
status: pending
risk: high
source_report: 2026-05-23
source_url: https://github.com/NousResearch/hermes-agent/pull/30899
score: 10
approved_at: ~
implemented_at: ~
verified_at: ~
---

# 📋 feat: mark web extraction content as untrusted

**来源**: GitHub | **日期**: 2026-05-23
**链接**: https://github.com/NousResearch/hermes-agent/pull/30899
**评分**: 10/10

## 摘要
> ## Summary
- Mark successful `web_extract` page content as `BEGIN_UNTRUSTED_WEB_CONTENT` / `END_UNTRUSTED_WEB_CONTENT` before it reaches the main agent.
- Add lightweight prompt-injection warning metadata for suspicious webpage instructions such as “ignore previous instructions”, secret/config file 

## 对 Hermes 的影响
- 🤖 Agent 架构与能力边界参考
- 🔧 工具链与扩展能力

## 建议行动
- **评估「feat: mark web extraction content as unt」中的工具/模式是否可集成到 Hermes** │ 收益: 扩展 Hermes 工具链与自动化能力 │ 工作量: 中 │ 分类: capability
- **对比社区最新 prompt 策略与 Hermes 当前配置，标记差异点** │ 收益: 跟上社区最佳实践，提升回复质量 │ 工作量: 低 │ 分类: quality

## 审批状态
- **状态**: `pending` → 待用户审批
- **风险等级**: `high`

### 状态流转
```
pending → approved → implementing → implemented → verified
pending → rejected
implemented → failed → rolled_back
```

### 审批操作
- 通过: 将 frontmatter 中 `status` 改为 `approved`
- 拒绝: 将 frontmatter 中 `status` 改为 `rejected`
- 实施后: 依次更新为 `implementing` → `implemented` → `verified`

---
> 由 Hermes Learner v3 自动生成 | 2026-05-23
