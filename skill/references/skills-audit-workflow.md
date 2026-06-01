# Skills 审计工作流 (2026-05-30 提炼)

## 两阶段审计模式

阶段1: DeepSeek 初筛（快速，但偏差大）
阶段2: GPT-5.4 严格审查（Beef API，8维度评分）

## GPT 审查调用

- Provider: `custom:beef-api`, 模型: `gpt-5.4`
- **必须用 curl**，Python urllib 返回 403
- Key: `BEEF_API_KEY` in `.env`
- 分批发，每批 ~15 个技能减少超时风险
- curl 命令: `curl -sk https://beefapi.com/v1/chat/completions -H "Authorization: Bearer $KEY" -d @payload.json`

## 8维度评分标准

1. 完整性 2. 可执行性 3. 错误处理 4. 通用性
5. 维护状态 6. 依赖稳定性 7. 边界清晰度 8. 安全合规

判定: KEEP(≥7无硬伤) IMPROVE(4-6) MERGE(高度重叠) DELETE(≤3或高风险/个人化)

## 典型偏差

- DeepSeek 审计过于宽松（均分7.2，94/122 KEEP）
- GPT 审查后：均分6.4，34 KEEP，36 MERGE，4 DELETE
- 关键发现：缺乏横向对比、未读实际文件、通用性不足仍给高分

## 执行后验证

**改动 skills 后必须验证网站展示**：
1. 重新扫描 skills 目录更新缓存: `python3 scan_and_update_cache.py`
2. 确认 API 返回正确: `curl -sk https://127.0.0.1/api/user-skills`
3. 重建 Next.js: `cd /root/gateway-dashboard/next && npm run build`
4. 重启: `systemctl restart next-frontend`
5. 验证页面: `curl -so /dev/null -w "%{http_code}" http://127.0.0.1:3000/skills`

不改动网站展示用户会觉得"什么都没变"。

## 用户技能三层架构

1. 通用能力 skill（如 unified-contract-party-extraction, 验证式学习教练）
2. 领域增强包（如光伏合同知识库）
3. 个人素材/档案（如毕业论文资产包, 幕布笔记）
