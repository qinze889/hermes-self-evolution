# 自主实施 + 自动验证闭环补充（2026-05-31）

适用范围：`/root/gateway-dashboard` 的 Hermes 进化系统 `/admin/evolution`，用于让 approved 提案从“状态流转”升级为“后台执行 → 执行日志 → 自动验证 → verified/failed 写回”。

## 核心改动模式

- 后端新增/完善：
  - `proposal_executor.py`：后台执行器、执行日志、自动验证器。
  - `app.py`：`POST /api/proposal/<file>/exec`、`GET /api/proposal/<file>/exec-logs`、`POST /api/proposal/<file>/auto-verify`。
- 前端新增/完善：
  - `next/src/app/admin/evolution/page.tsx`：自动实施按钮、自动验证按钮、执行日志面板、实施中/已验证统计。
- 状态流：
  - `approved` → 自动实施 → `implementing` → 自动验证 → `verified` / `failed`
  - `failed` 允许重新“手动完成”或“自动验证”，避免终态卡死。

## 必须加的状态守卫

后端不能只依赖 UI disabled 状态，必须在 API 层校验：

- `/implement`：只允许 `approved` / `implementing` / `failed` → `implemented`。
- `/verify`：只允许 `implemented` → `verified` / `failed`。
- `/auto-verify`：只允许 `implementing` / `implemented` / `failed`。
- `proposal_executor.run_verify()` 内部也要重复校验状态，防止绕过 Flask API 直接调用。

## 安全要点

- 不要用 `shell=True` 执行提案动作；改用 `subprocess.run(args, cwd=...)`。
- 文件名必须走 `_hermes_proposal_path()` / safe filename 校验，避免路径穿越。
- 所有新增管理 API 必须带 `@require_auth`。
- 自动执行器当前更适合做受控动作：语法检查、构建、状态写回、日志记录；不要让提案正文直接变成任意 shell 命令。

## 验证清单

1. Python 语法：
   - `python3 -m py_compile /root/gateway-dashboard/app.py /root/gateway-dashboard/proposal_executor.py`
2. 前端构建：
   - `cd /root/gateway-dashboard/next && npm run build`
3. 重启服务：
   - `systemctl restart flask-backend.service next-frontend.service`
   - `systemctl is-active flask-backend.service next-frontend.service`
4. API smoke test：
   - Basic Auth 请求 `/api/evolution`，确认返回 `reports`、`proposals`，且提案项含 `exec_status`。
5. 浏览器验证：
   - 打开 `http://127.0.0.1:3000/admin/evolution`
   - 登录后点击“提案管理”
   - 确认顶部统计、提案列表、详情区、执行日志入口无空白/报错。

## 容易漏掉的点

- Next.js 生产模式必须 `npm run build && systemctl restart next-frontend.service`，只改 TSX 不重建页面不会变。
- 视觉验证失败时，如果截图已生成，可直接把 `MEDIA:/root/.hermes/cache/screenshots/...png` 发给用户，不必重复截图。
- API 返回的 `latest` 可能是 markdown 字符串，不要当 dict 访问；提案统计应从 `proposals` 数组计算。
- Codex/GPT 外部复审不可用时，至少做本地静态阻塞检查（鉴权、shell 注入、状态守卫、路径穿越）并用子 agent 独立审查。不要把临时 OAuth/网络失败固化为“工具不能用”。
