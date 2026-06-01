# 技能内化优先队列与提案影响说明（2026-05-31）

## 背景
用户指出：已验证/已实施提案在 UI 上看不出“具体改善了 Hermes 和技能哪些东西”；同时“提案是系统之外的输入”，进化系统应优先把当前已有技能纳入内化、提升、验证闭环。

## 设计原则
- 默认重点从“外部提案/学习报告”前移到“当前已有技能”。
- 外部提案是补充来源，不是唯一进化对象。
- 每条提案必须展示“这条提案改善什么”：范围、目标技能、可读 bullet。
- 无法识别明确 Hermes/技能改善点时，应显式提示：先补齐目标与验证标准，而不是只显示状态为 verified/implemented。

## 后端实现模式
在 `/root/gateway-dashboard/app.py` 中扩展 `/api/evolution`：

1. 实时扫描 `~/.hermes/skills/`（递归 `os.walk` 查找所有 SKILL.md，含嵌套子目录），合并 `skills-audit.json` 审计判决。不再依赖 `user-skills.json` 缓存。
2. 规范化技能字段：`name/category/file/rating/composite/verdict/reason/issues/size_kb/body_lines/description`。
3. 生成 `skill_focus`：
   - `total`: 技能总数
   - `needs_work`: `IMPROVE/MERGE/DELETE/REVIEW` 数量
   - `keep`: `KEEP` 数量
   - `priorities`: 优先内化队列，先排非 KEEP，再按评分和 issue 数排序
4. 对每个 proposal 生成 impact：
   - `impact_scope`: `系统提案` / `技能内化` / `Hermes 系统改进` / `Hermes + 技能内化`
   - `target_skills`: 正文中匹配到的当前技能名
   - `impact_bullets`: 从正文抽取含“技能/skill/Hermes/内化/改进/验证/闭环/执行”等关键词的可读行

返回 JSON 需包含：
```json
{
  "skills": {"total": 15, "skills": []},
  "skill_focus": {"total": 15, "needs_work": 2, "keep": 13, "priorities": []},
  "proposals": [{"impact_scope": "Hermes + 技能内化", "target_skills": [], "impact_bullets": []}]
}
```

## 前端实现模式
在 `/root/gateway-dashboard/next/src/app/admin/evolution/page.tsx`：

1. 新增默认 tab：`skills`，标签为“技能内化”。
2. 顶部统计改成：
   - 我的技能
   - 待内化
   - 外部提案
   - 已验证
3. 中间区域新增“技能内化优先队列”：
   - 显示技能名、分类、verdict、评分、reason、issues
   - 文案明确：“外部提案只作为补充来源”
   - 每个技能显示内化动作：补齐触发条件、步骤、坑点与验证方式；完成后重新审计并写回技能质量分
4. 提案卡片显示 `impact_scope`，副标题优先显示第一条 `impact_bullets`。
5. 提案详情右侧新增“这条提案改善什么”：
   - 范围
   - 目标技能 chips
   - impact bullets
   - 如果无 bullets：显示“未识别到明确的 Hermes/技能改善点，建议先转入‘技能内化’队列补齐目标与验证标准。”

## 验证步骤
- `python3 -m py_compile /root/gateway-dashboard/app.py /root/gateway-dashboard/proposal_executor.py`
- `cd /root/gateway-dashboard/next && npm run build`
- `systemctl restart flask-backend.service next-frontend.service`
- 用 Basic Auth 请求 `/api/evolution`，确认 `skill_focus` 非空且 proposals 有 `impact_scope`。
- 浏览器打开 `http://127.0.0.1:3000/admin/evolution`，登录后确认默认展示“技能内化优先队列”。
- 用截图验证 UI，不只口头说明。

## 更新记录

### 2026-06-01 更新
- 删除 stale `user-skills.json`，改为实时递归扫描 skills 目录（122 个技能）
- 面板布局改为条件渲染：左栏仅 reports tab、右栏仅 proposals tab
- 新增 `POST /api/skill/internalize` 端点，技能卡片增加「⚡开始内化」按钮
- 详见 SKILL.md 的「Evolution Dashboard (V3.4 — 技能内化优先)」和「Pitfalls」部分
