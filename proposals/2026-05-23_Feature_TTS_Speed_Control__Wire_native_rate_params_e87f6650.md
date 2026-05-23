---
status: pending
risk: high
source_report: 2026-05-23
source_url: https://github.com/NousResearch/hermes-agent/issues/6926
score: 9
approved_at: ~
implemented_at: ~
verified_at: ~
---

# 📋 Feature: TTS Speed Control — Wire native rate params for Edge/OpenAI, add ffmpeg atempo fallback for NeuTTS/ElevenLabs

**来源**: GitHub | **日期**: 2026-05-23
**链接**: https://github.com/NousResearch/hermes-agent/issues/6926
**评分**: 9/10

## 摘要
> ## Overview

TTS speed/rate control is only wired up for MiniMax (`tts.minimax.speed`). The other four providers — Edge TTS, OpenAI TTS, ElevenLabs, and NeuTTS — all ignore any `speed` config. Users running local voice (especially via the TUI) have no way to speed up playback without manual post-pro

## 对 Hermes 的影响
- 🤖 Agent 架构与能力边界参考

## 建议行动
- **评估「Feature: TTS Speed Control — Wire native」中的工具/模式是否可集成到 Hermes** │ 收益: 扩展 Hermes 工具链与自动化能力 │ 工作量: 中 │ 分类: capability
- **检查 gateway 层缓存命中率，调整 cache TTL 策略** │ 收益: 减少重复 API 调用，降低延迟和成本 │ 工作量: 低 │ 分类: performance

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
