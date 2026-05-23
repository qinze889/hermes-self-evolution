---
status: pending
risk: high
source_report: 2026-05-23
source_url: https://github.com/NousResearch/hermes-agent/pull/30885
score: 9
approved_at: ~
implemented_at: ~
verified_at: ~
---

# 📋 fix: support GitHub webhook body mention metadata

**来源**: GitHub | **日期**: 2026-05-23
**链接**: https://github.com/NousResearch/hermes-agent/pull/30885
**评分**: 9/10

## 摘要
> ## Summary
- Add {__event__} and {__route__} webhook prompt tokens so GitHub body mention prompts can distinguish issue, issue_comment, and pull_request events
- Use gh issue comment for GitHub comment delivery so one delivery path works for both issues and PR conversations
- Update webhook tests fo

## 对 Hermes 的影响
- 📊 关注 token 成本与效率优化

## 建议行动
- **分析 DeepSeek 近 7 天 token 消耗分布，识别高成本任务模式** │ 收益: 发现优化机会，预计可节省 15-30% 配额 │ 工作量: 低 │ 分类: economy
- **审查 context compaction threshold 是否可进一步降低** │ 收益: 减少长对话 token 膨胀 │ 工作量: 低 │ 分类: economy
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
