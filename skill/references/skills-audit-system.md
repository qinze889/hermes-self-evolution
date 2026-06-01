# Skills 审计系统

工程管理视角的 Skills 质量评估管道。用于定期审查所有已安装 Skill 的质量、实用性和维护状态。

## 两阶段审计模式

**不要只用单个模型审计**——单一模型审计存在系统性偏差（过于宽松、缺乏对比）。使用两阶段模式：

```
阶段 1: DeepSeek 初评 → 扫所有 skill → 评分 + 判定 + 问题标注
        │
        ▼
阶段 2: GPT 元审查 → 审阶段 1 结果 → 评分纠偏 + 漏判合并 + 漏判删除 + 系统性偏差诊断
        │
        ▼
最终审计报告 = 阶段1 基线 + 阶段2 修正
```

**GPT 调用方式**：使用 Beef API（`custom:beef-api`，模型 `gpt-5.4`），通过 curl 发送（Python urllib 在 Beef API 上返回 403，curl 正常）。Key 在 `~/.hermes/.env` 的 `BEEF_API_KEY`。

### GPT 元审查 Prompt 模板

```
你是 Hermes AI 系统的首席架构师。请以极度严谨的工程管理视角，对以下 DeepSeek 生成的 N 个 Skills 审计结果进行元审查。

从以下维度审查：
1. 评分偏差 — 明显偏高/偏低的技能（至少5个）
2. 漏判合并 — 功能重叠但未标注合并的技能组（至少3组）
3. 漏判删除 — 应标记 DELETE 的技能
4. IMPROVE 升级 — 质量够好应升为 KEEP
5. KEEP 降级 — 评分虚高应降为 IMPROVE
6. 整体评价 — 审计质量 + 系统性偏差
7. 改进建议

输出 JSON：
{
  "overall_audit_quality": "...",
  "systematic_biases": ["偏差1"],
  "scoring_errors": [{"name":"", "current_rating":0, "suggested_rating":0, "reason":""}],
  "missed_merges": [{"skills":["a","b"], "reason":""}],
  "missed_deletes": [{"name":"", "reason":""}],
  "should_upgrade_to_keep": [""],
  "should_downgrade_to_improve": [""],
  "improvement_suggestions": [""]
}
```

## 架构

```
Flask POST /api/skills-audit/refresh
        │
        ▼
扫描 ~/.hermes/skills/ → 收集元数据 (名称/分类/描述/大小/行数)
        │
        ▼
分批调用 DeepSeek API (8个/批) → 工程管理视角评分
        │
        ▼
缓存到 ~/.hermes/cache/skills-audit.json (24h)
        │
        ▼
[可选] GPT 元审查 → ~/.hermes/cache/skills-audit-gpt-review.json
        │
        ▼
Next.js /skills 页面 ← GET /api/skills-audit
```

## 评估维度（8 维度 Rubric）

**仅用 4 维度评分会导致系统性偏差**（2026-05-30 GPT 审查发现）。必须扩展到 8 维度：

| 维度 | 说明 | 硬性降级条件 |
|------|------|-------------|
| 完整性 | SKILL.md 是否完整，无截断/缺失 | **描述截断 → 直接降级，不给 KEEP** |
| 可执行性 | 步骤是否可直接执行，有无隐式依赖 | 依赖自动注入/隐式系统提示 → 降级 |
| 错误处理 | 是否覆盖异常路径和失败场景 | 无错误处理 + 依赖外部服务 → 降级 |
| 通用性 | 是否跨平台/跨场景可复用 | 特定项目/单人/单平台 → 降级 |
| 维护状态 | 是否过时、有错误、需确认更新 | **未验证更新状态 → 不给高分 KEEP** |
| 依赖稳定性 | 外部 API/CLI/服务的版本约束和降级方案 | 依赖不稳定外部服务 → 降级 |
| 边界清晰度 | 与同类技能的分工是否明确 | 与 ≥2 个技能重叠 → 标记 MERGE |
| 重复度 | 与现有技能的冗余程度 | 高度重叠 → 标记 MERGE |

## 判定标准

| 判定 | 条件 | 含义 |
|------|------|------|
| KEEP | 评分 ≥7 **且通过硬性降级检查** | 质量好，继续维护 |
| IMPROVE | 评分 4-6 或未通过硬性检查 | 有价值但需优化 |
| MERGE | 与同类技能高度重叠 | 应与同类技能合并 |
| DELETE | 评分 ≤3 或满足删除条件 | 无用/过时/高风险/个人化 |
| REVIEW | 信息不足 | 需人工判断 |

### DELETE 明确标准

满足**任一**即进入删除候选：
- 高风险（越狱/规避限制/安全违规）
- 强个人化（特定个人知识库、无法泛化）
- 特定项目私有知识（不具通用性）
- 不可复用（针对单一论文/事件）
- 严重不完整（描述截断 + 无错误处理 + 无示例）

## 系统性偏差（必须避免）

GPT 审查发现的 5 个偏差模式（2026-05-30）：

| 偏差 | 表现 | 修复 |
|------|------|------|
| 打分偏高 | "有用即 KEEP"，94/122 KEEP | 引入硬性降级条件 |
| 缺乏横向对比 | 相近技能未系统识别重复 | 同类技能必须一起评 |
| 未读实际文件 | 出现"描述截断仍 KEEP" | 必须先读文件再评分 |
| 容忍度偏高 | 通用性不足仍保留 | 通用性不足 → 降级 |
| DELETE 过严 | 只删 1 个 | 满足任一删除标准即标记 |

## API 端点

### GET /api/skills-audit
返回缓存的审计结果（24h 内）。首次访问返回 503，需 POST 触发。

### POST /api/skills-audit/refresh
触发完整审计。扫描所有 skills → 分批调 DeepSeek → 缓存 → 返回 JSON。

响应格式：
```json
{
  "generated_at": "2026-05-30 23:45 CST",
  "total": 122,
  "avg_rating": 6.8,
  "verdicts": {"KEEP": 80, "IMPROVE": 25, "DELETE": 8, "MERGE": 5, "REVIEW": 4},
  "skills": [
    {"name": "skill-name", "category": "media", "rating": 9, "verdict": "KEEP", "reason": "完整工作流，实用", "issues": []}
  ]
}
```

## 前端页面

路径: `/skills`（导航栏已添加 Wrench 图标入口）

功能：
- 概览卡片（总数/均分/KEEP数/需改进数/待删除数）
- 搜索过滤（技能名/理由/分类）
- 判定过滤（KEEP/IMPROVE/MERGE/DELETE/REVIEW）
- 评分条可视化（绿 ≥7 / 橙 4-6 / 红 ≤3）
- 问题标签展示
- 手动刷新按钮

## 相关文件

- Flask 端点: `/root/gateway-dashboard/app.py` → `_run_skills_audit()`, `_call_deepseek()`
- 前端页面: `/root/gateway-dashboard/next/src/app/skills/page.tsx`
- 导航入口: `/root/gateway-dashboard/next/src/components/Nav.tsx`
- 缓存文件: `/root/.hermes/cache/skills-audit.json`
- GPT 审查缓存: `/root/.hermes/cache/skills-audit-gpt-review.json`
- GPT 审查记录: `references/skills-audit-gpt-review-2026-05-30.md`

## 历史审查记录

- **2026-05-30**: 首次两阶段审计。DeepSeek 初评 122 skill（KEEP 94/IMPROVE 27/DELETE 1，均分 7.2）→ GPT-5.4 识别出 12 处评分偏差、8 组漏判合并、4 个漏判删除、5 项系统性偏差。详见 `references/skills-audit-gpt-review-2026-05-30.md`。

## 注意事项

- DeepSeek API key 从 `~/.hermes/.env` 的 `DEEPSEEK_API_KEY` 读取
- 批量评估约需 3-5 分钟（122 skill / 8 每批 ≈ 16 轮 API 调用）
- 缓存 24 小时有效，手动 POST refresh 可强制刷新
- 避免频繁刷新，DeepSeek API 有速率限制
