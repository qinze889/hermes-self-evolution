# GPT-5.4 元审查结果 — 2026-05-30

两阶段审计的第二个阶段：GPT 审查 DeepSeek 对 122 个 Skills 的初评结果。

## 审查结论

**总体评价：中等偏上，但明显偏宽松且证据不足**

### 系统性偏差（5 项）

1. **整体打分偏高** — "有用即 KEEP"的宽松倾向，94/122 KEEP，缺少硬约束
2. **缺乏横向对比** — 相近技能未系统识别重复，合并建议不足
3. **疑似未读实际文件** — 出现"描述截断仍 KEEP"信号（document-generation-workflow、cron-digest）
4. **通用性容忍度偏高** — 强依赖个人环境/特定项目的技能仍保留
5. **DELETE 标准过严** — 只删 1 个，应淘汰的个人化/高风险/不可复用技能留在 IMPROVE

### 评分错误（12 处）

| 技能 | DeepSeek | GPT | 偏差原因 |
|------|----------|-----|----------|
| pv-contract-knowledge | 7 KEEP | 4 IMPROVE | 项目私有知识，不具通用性 |
| document-generation-workflow | 7 KEEP | 5 IMPROVE | 描述截断未达标仍 KEEP |
| popular-web-designs | 8 KEEP | 6 IMPROVE | 未验证更新状态就给高分 |
| kanban-worker | 8 KEEP | 6 IMPROVE | 依赖隐式系统提示未验证 |
| findmy | 7 KEEP | 5 IMPROVE | 强依赖 macOS，跨平台性差 |
| thesis-writing-guide | 7 KEEP | 5 IMPROVE | 与 ai-academic-writing 重叠 |
| touchdesigner-mcp | 8 KEEP | 6 IMPROVE | 未完成冗余检查就给高分 |
| huggingface-hub | 6 IMPROVE | 7 KEEP | 基础完整被低估 |
| webhook-subscriptions | 6 IMPROVE | 7 KEEP | 实用性高被低估 |
| architecture-diagram | 6 IMPROVE | 7 KEEP | 高频能力被低估 |
| apple-notes | 5 IMPROVE | 4 IMPROVE | 功能过于简单 |
| cron-digest | 7 KEEP | 5 IMPROVE | 描述截断未达标 |

### 漏判合并（8 组）

1. 合同/OCR: `contract-party-extraction` + `mineru-contract-extraction` + `ocr-and-documents`
2. 视频工作流: `python-video-pipeline` + `video-generation-workflow` + `manim-video`
3. 代码代理: `codex` + `claude-code` + `opencode`
4. GitHub 系列: `github-pr-workflow` + `github-code-review` + `github-issues` + `github-repo-management` + `github-auth`
5. 学术写作: `research-paper-writing` + `thesis-writing-guide` + `ai-academic-writing`
6. 知识管理: `notion` + `obsidian` + `mubu-knowledge-base` + `llm-wiki`
7. 规划/探索: `writing-plans` + `plan` + `spike`
8. 代码审查: `github-code-review` + `requesting-code-review` + `github-pr-workflow`

### 漏判删除（4 个）

| 技能 | 原因 |
|------|------|
| obliteratus | 伦理风险高，应直接 DELETE |
| mubu-knowledge-base | 个人化内容，不具通用性 |
| sor-thesis-short-video | 针对单一论文，不可复用 |
| pv-contract-knowledge | 项目私有知识，无法泛化 |

### KEEP ↔ IMPROVE 调整

**应升为 KEEP**: huggingface-hub, webhook-subscriptions, architecture-diagram, ideation, sketch
**应降为 IMPROVE**: document-generation-workflow, cron-digest, kanban-worker, findmy, thesis-writing-guide, touchdesigner-mcp, popular-web-designs, pv-contract-knowledge, github-code-review

### 10 条改进建议

1. 先做基于文件实内容的逐项核查，再给分；禁止仅凭描述判断
2. 建立 8 维度评分 rubric（完整性/可执行性/错误处理/通用性/维护/依赖/边界/重复度）
3. "描述截断/未验证更新/需检查冗余"设为硬性降级条件
4. 增加横向对比审查：同类技能必须一起评
5. DELETE 明确标准：高风险/强个人化/特定项目私有/不可复用/严重不完整
6. 依赖外部服务的技能要求提供失败路径和降级方案
7. 每个 KEEP 至少一个可复现示例 + 一个错误处理说明 + 一个适用边界说明
8. 平台专属技能单独打适用范围系数
9. 引入合并矩阵，按主题聚类后检查重复
10. 使用配额约束防止系统性高分

## 审计方法论启示

- **单模型审计不可靠**: DeepSeek 倾向于正面评价（\"有用\"即 KEEP），缺少批评性思维
- **GPT 作为审查者有效**: GPT 更能识别逻辑矛盾（描述截断仍 KEEP）、系统性模式（8 组漏判合并）
- **交叉验证必要**: 两阶段审计比单阶段更严谨，应固化为标准流程

---

## 阶段 3: GPT-5.4 严格重新审计（2026-05-30）

基于 GPT 元审查中发现的系统性偏差，对全部 122 个 skills 进行重新审计。

### 审计方法

- 读取所有 SKILL.md 实际指标（而非仅描述）：行数、大小、有无示例、有无错误处理、有无步骤化
- 使用 8 维度严格 rubric
- 通过已知 10 个重叠组进行横向对比
- 通过 `curl + subprocess` 调用 Beef API（`python urllib` 返回 403）
- 分 9 批发送，每批 15 个技能

### 重新审计结果

| 指标 | DeepSeek 初评 | GPT-5.4 严格审计 |
|------|:---:|:---:|
| 均分 | 7.2 | **6.4** |
| KEEP | 94 (77%) | **34 (28%)** |
| IMPROVE | 27 (22%) | **48 (39%)** |
| MERGE | 0 | **36 (30%)** |
| DELETE | 1 | **4** |

### 重新审计后的 TOP 10

| 评分 | 技能 |
|------|------|
| 8.6 KEEP | external-web-services |
| 8.3 KEEP | p5js |
| 8.2 MERGE | research-paper-writing |
| 8.1 KEEP | low-memory-server-ops |
| 8.1 MERGE | manim-video |
| 8.0 KEEP | video-asr-pipeline |
| 8.0 MERGE | mineru-contract-extraction |
| 8.0 MERGE | contract-party-extraction |

### 确认 DELETE (4个)

- **godmode**: 越狱 LLM，安全违规
- **obliteratus**: 移除模型安全拒答，高风险
- **verification-based-teaching**: 强依赖特定本地路径和个人课程配置
- **sor-thesis-short-video**: 特定个人论文，不可复用，含个人身份信息

### 关键发现

- **60 个 DeepSeek 给 KEEP 的被降级** — 之前过于宽松
- **36 个纳入合并计划** — 合同/视频/代码代理/GitHub/学术写作等 10 大重叠组
- **curl vs urllib 代理陷阱**: Python urllib 继承系统 HTTP_PROXY 导致 Beef API 403，curl 直连正常
