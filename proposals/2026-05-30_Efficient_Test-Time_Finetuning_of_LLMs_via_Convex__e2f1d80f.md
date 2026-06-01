---
status: rejected
risk: high
source_report: 2026-05-30
source_url: https://arxiv.org/abs/2605.30337v1
score: 10
category: Arxiv
approved_at: ~
implemented_at: ~
verified_at: ~
failure_reason: ~
rollback_sha: ~
---

# 📋 Efficient Test-Time Finetuning of LLMs via Convex Reconstruction and Gradient Caching

> 📄 **Arxiv** | ⭐ 10/10 | https://arxiv.org/abs/2605.30337v1

## 这是什么
Test-time finetuning (TTFT) is a rapidly evolving paradigm that adapts a language model to each prompt by retrieving related sequences, updating the model on them, and then evaluating the prompt. However, TTFT is only practical if it is fast: selection and finetuning both happen per query, making ea

## 为什么对 Hermes 重要
- 📰 值得关注的行业动态

## 建议行动
- **通读 [Efficient Test-Time Finetuning of LLMs via Convex Reconstruc](https://arxiv.org/abs/2605.30337v1) 论文摘要与结论，标注与 Hermes 相关的技术点**
  - 📈 收益: 跟踪学术前沿，发现可落地的技术方案  ⏱ 工作量: 低  🏷️ research

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
> 由 Hermes Learner v3 自动生成 | 2026-05-30
