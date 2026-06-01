# 首轮自我进化闭环记录（2026-05-24）

## 背景
用户明确授权“可以开始迭代”。当时 learner v3 已能生成报告和提案，但自动执行器/验证器尚未实现，因此采用手动闭环执行 approved 提案。

## 选择的提案
- 文件：`~/.hermes/proposals/2026-05-23_featprompt-builder_make_CONTEXT_FILE_MAX_CHARS_con_bf1f930d.md`
- 目标：让 `agent/prompt_builder.py` 的 `CONTEXT_FILE_MAX_CHARS` 支持环境变量 `HERMES_CONTEXT_FILE_MAX_CHARS`，默认仍为 `20000`。

## 执行流程
1. 将提案状态从 `approved` 改为 `implementing`。
2. 派 Claude Code/DeepSeek 修改实现和测试。
3. 运行相关测试：`./scripts/run_tests.sh tests/agent/test_prompt_builder.py`。
4. 派 Codex/GPT 审查当前 diff。
5. 根据 Codex 反馈返工，直到第三轮 PASS。
6. 将提案状态回写为 `verified`，填写 `implemented_at` / `verified_at`，追加实施记录。
7. 同步更新 `/root/pending_tasks.md`。

## 关键审查发现
Codex 两轮指出新增测试存在模块状态污染：测试中通过 `importlib.reload(agent.prompt_builder)` 让模块级常量读取临时 env，但 `monkeypatch` 的自动恢复发生在测试 `finally` 之后，导致模块可能保留 stale 常量或函数默认参数。

正确模式：
```python
orig = os.environ.get("HERMES_CONTEXT_FILE_MAX_CHARS")
monkeypatch.setenv("HERMES_CONTEXT_FILE_MAX_CHARS", "100")
import agent.prompt_builder as pb
importlib.reload(pb)
try:
    ...
finally:
    if orig is not None:
        os.environ["HERMES_CONTEXT_FILE_MAX_CHARS"] = orig
    else:
        os.environ.pop("HERMES_CONTEXT_FILE_MAX_CHARS", None)
    importlib.reload(pb)
```

## 验证结果
- `./scripts/run_tests.sh tests/agent/test_prompt_builder.py`：133/133 通过。
- Codex 第三轮复审：PASS。

## 可复用教训
- 自我进化闭环不要停在“生成提案”；approved 提案至少应走：implementing → 实施 → 测试 → Codex 复审 → verified。
- 测试导入期 env 配置时，必须显式恢复 env 并 reload，不能只依赖 monkeypatch。
- 相关测试优先跑项目自带 `scripts/run_tests.sh`，它会处理仓库自己的测试入口；直接 `python -m pytest` 可能因环境未装 dev 依赖失败。
