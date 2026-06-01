# Content Generation Patterns — 提案内容优化实战

## 根因：提案内容太空泛

**现象**：`generate_actions()` 基于关键词 if-else，如仓库 `MiaoDX/roboclaws`（可视化 HTML 报告框架）被生成了"设计回归测试基准"——跟仓库内容毫无关系。

**根因链**：
1. `generate_actions()` 只有 `if kw in title_keywords: return generic_action` 结构
2. 没有根据来源类型（repo / paper / news）做上下文感知
3. 没有引用项目名、论文标题或具体内容

## 解决模式

### 1. Source-type 感知

每个来源类型的 generate_actions 应当先判断类型，再根据 desc/content 生成：

```python
# 好示例：按来源类型分类
if source == "GitHub":
    repo_name = title  # 仓库全名
    if "MCP" in (desc or "") or "mcp" in (desc or ""):
        action = f"分析 {repo_name} 的 MCP 实现，评估注册为 Hermes 工具的可行性与工作量"
    elif "agent" in (desc or ""):
        action = f"评估 {repo_name} 的 agent 架构设计模式，提取可复用到 Hermes 核心循环的模块"
    else:
        action = f"阅读 {repo_name} 文档/README，提取其核心功能点并评估与 Hermes 的整合价值"

elif source == "Arxiv":
    paper_title = title
    action = f"阅读《{paper_title}》，提取其{描述核心贡献}到 Hermes 的对应模块中"

elif source == "AI HOT":
    if "price" in desc or "降价" in desc or "免费" in desc:
        action = f"关注 {title} 的价格变动，评估是否切换/补充该服务作为 Hermes provider"
    elif "安全" in desc or "攻击" in desc or "漏洞" in desc:
        action = f"评估 {title} 对 Hermes 供应链/依赖库的潜在影响，检查是否受影响"
    else:
        action = f"分析 {title} 的行业影响，评估是否需要在 Hermes 中适配/跟进"
```

### 2. Insight 提取

Insight 需要提取具体价值，不要用通用模板：

```python
# 坏示例
insight = "该仓库对 Hermes 有参考价值，建议关注"

# 好示例
repo_name = title
if source == "GitHub":
    insight = f"项目 {repo_name} 专注于 {提取核心功能}，其 {具体的模块/方法} 可直接参考或集成到 Hermes 的 {具体模块}"
```

### 3. Action 的格式要求

每个 action 必须满足：
- **引用了具体名称**（仓库名/论文标题/新闻来源）
- **建议内容基于实际描述**（不是关键词匹配）
- **对 Hermes 的价值明确**（不是通用"可参考"）

## 实战案例

| 项目 | 旧生成 | 新生成 |
|------|--------|--------|
| MiaoDX/roboclaws (可视化HTML报告) | "设计回归测试基准" (无关) | "分析 MCP 实现，评估注册为 Hermes 工具" (相关) |
| Arxiv 论文 (多Agent协作) | "调研主流Agent框架" (通用) | "提取多Agent编排模式到 Hermes deque 模块" (具体) |
| AI HOT 行业新闻 | (以前跳过) | "关注价格变动，评估切换服务" (有针对性) |

## 实现要点

- `generate_actions()` 放在脚本的 Python 函数中（不是 bash），便于处理字符串
- 对 GitHub 项目：必须提取 `repo_name` + `description[:100]` 作为 context
- 对 Arxiv 论文：必须提取 `title` + `summary[:150]` 作为 context  
- 无 desc/news 的项：用 `title` 本身作为内容源，至少给出具体名称
- 避免纯关键词 if-elif 链：采用 source-type 先分类，再基于 desc 做细粒度判断
