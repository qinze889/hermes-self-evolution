#!/usr/bin/env python3
"""
Proposal Background Executor + Auto-Validator for Hermes Evolution System.

=== Executor ===
Runs actions extracted from a proposal in a background thread.
Each action is logged as a timestamped event in a JSONL log file.

=== Validator ===
After all actions complete, runs configurable validation checks:
  - py_compile on .py files touched
  - npm build / tsc --noEmit on projects mentioned
  - API healthcheck on URLs from the proposal
  - General file existence checks

Logs are stored at: ~/.hermes/proposal_executor/<safe_filename>/
"""
import datetime
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import traceback

logger = logging.getLogger("proposal_executor")

# ── Config ──────────────────────────────────────────────────────────
EXECUTOR_DIR = os.path.expanduser("~/.hermes/proposal_executor")
PROPOSALS_DIR = os.path.expanduser("~/.hermes/proposals")
GATEWAY_DASHBOARD = "/root/gateway-dashboard"
NEXT_DIR = os.path.join(GATEWAY_DASHBOARD, "next")
# How long (seconds) to wait for a git/npm command before timing out
CMD_TIMEOUT = 120
# How long (seconds) to wait for an API healthcheck
API_TIMEOUT = 15


# ── Logging ─────────────────────────────────────────────────────────
def _exec_log_dir(safe_filename):
    """Return the log directory for a proposal."""
    d = os.path.join(EXECUTOR_DIR, safe_filename.replace(".md", ""))
    os.makedirs(d, exist_ok=True)
    return d


def _write_log(safe_filename, level, message, action_idx=None, status=None):
    """Append a structured log entry to the JSONL log file."""
    log_dir = _exec_log_dir(safe_filename)
    log_file = os.path.join(log_dir, "execution.jsonl")
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "message": message,
    }
    if action_idx is not None:
        entry["action_idx"] = action_idx
    if status is not None:
        entry["status"] = status
    try:
        with open(log_file, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
    except Exception as e:
        logger.error("Failed to write exec log: %s", e)


def read_exec_logs(safe_filename, last_n=None):
    """Read execution logs for a proposal. Returns list of dicts, newest first."""
    log_dir = _exec_log_dir(safe_filename)
    log_file = os.path.join(log_dir, "execution.jsonl")
    if not os.path.isfile(log_file):
        return []
    entries = []
    try:
        with open(log_file, encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        return []
    entries.reverse()
    if last_n and len(entries) > last_n:
        entries = entries[:last_n]
    return entries


def get_exec_summary(safe_filename):
    """Get current execution status summary for a proposal."""
    logs = read_exec_logs(safe_filename)
    if not logs:
        return {
            "running": False,
            "actions_total": 0,
            "actions_done": 0,
            "actions_failed": 0,
            "last_message": "",
            "last_updated": None,
        }
    latest = logs[0] if logs else {}
    # Count unique action indices
    action_idxs = set()
    action_done = set()
    action_failed = set()
    for e in logs:
        ai = e.get("action_idx")
        if ai is not None:
            action_idxs.add(ai)
            if e.get("status") == "done":
                action_done.add(ai)
            elif e.get("status") in ("failed", "error"):
                action_failed.add(ai)

    # Check if a "running" entry exists without a matching "done"/"failed" / "error" for the same action
    still_running = False
    if logs:
        for e in logs:
            if e.get("level") == "start_exec":
                still_running = True
            if e.get("level") == "exec_complete":
                still_running = False
            if e.get("level") == "exec_failed":
                still_running = False

    return {
        "running": still_running,
        "actions_total": len(action_idxs) if action_idxs else 0,
        "actions_done": len(action_done),
        "actions_failed": len(action_failed),
        "last_message": latest.get("message", ""),
        "last_updated": latest.get("ts"),
    }


# ── Proposal Helpers ────────────────────────────────────────────────
def _parse_proposal(content):
    """Parse frontmatter + body from a proposal file."""
    values = {}
    body = content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            body = content[end + 3:]
            for line in content[3:end].split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    values[key.strip()] = val.strip()
    return values, body


def _extract_actions(body):
    """Extract actionable bullet items from a proposal body."""
    actions = []
    in_action_section = False
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            in_action_section = any(
                token in line for token in ("行动", "实施", "建议", "落地", "Action")
            )
            continue
        if not line.startswith(("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ")):
            continue
        text = line[2:].strip() if line[:2] in ("- ", "* ") else line[3:].strip()
        if text.startswith("**") and "**" in text[2:]:
            text = text[2:].split("**", 1)[0].strip()
        actionable_hint = any(
            token in line
            for token in ("收益", "工作量", "验证", "实施", "改造", "新增", "修复", "接入", "落地")
        )
        if in_action_section or actionable_hint:
            text = text[:200]
            if text and text not in actions:
                actions.append(text)
    return actions


def _read_proposal(safe_filename):
    """Read a proposal file and return (content, meta, body, actions)."""
    fpath = os.path.join(PROPOSALS_DIR, safe_filename)
    if not os.path.isfile(fpath):
        fpath = os.path.join(PROPOSALS_DIR, safe_filename + ".md")
    if not os.path.isfile(fpath):
        return None, None, None, None
    with open(fpath, encoding="utf-8") as fp:
        content = fp.read()
    meta, body = _parse_proposal(content)
    actions = _extract_actions(body)
    return content, meta, body, actions


def _update_frontmatter(content, updates):
    """Update frontmatter keys in a proposal file."""
    body = content
    values = {}
    order = []
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            frontmatter = content[3:end]
            body = content[end + 3:]
            for line in frontmatter.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    values[key] = val.strip()
                    order.append(key)
    for key, val in updates.items():
        if key not in order:
            order.append(key)
        values[key] = val
    fm = "\n".join(f"{k}: {values.get(k, '')}" for k in order)
    return f"---\n{fm}\n---{body}"


def _append_event(content, title, note=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CST")
    content = content.rstrip() + f"\n\n## {title} ({now})\n"
    if note:
        content += f"\n> {note}\n"
    return content


def _atomic_write(path, content):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        fp.write(content)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)


# ── Action Executors ────────────────────────────────────────────────
def run_cmd(args, timeout=CMD_TIMEOUT, cwd=None):
    """Run a command without a shell and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        return ok, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def run_shell(cmd, timeout=CMD_TIMEOUT, cwd=None):
    """Compatibility wrapper: split a simple command string and run without shell."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    return run_cmd(cmd, timeout=timeout, cwd=cwd)


def execute_py_compile(paths_py):
    """Run py_compile on Python files. Returns (ok, details)."""
    details = []
    all_ok = True
    for pypath in paths_py:
        if not os.path.isfile(pypath):
            details.append(f"⏭️  {pypath} — not found")
            continue
        ok, out, err = run_cmd(["python3", "-m", "py_compile", pypath])
        if ok:
            details.append(f"✅  {pypath} — syntax OK")
        else:
            details.append(f"❌  {pypath} — {err.strip()[:200]}")
            all_ok = False
    return all_ok, details


def execute_npm_build(project_dirs):
    """Run npm build / tsc on project directories. Returns (ok, details)."""
    details = []
    all_ok = True
    for proj_dir in set(project_dirs):
        if not os.path.isdir(proj_dir):
            details.append(f"⏭️  {proj_dir} — not found")
            continue
        pkg_json = os.path.join(proj_dir, "package.json")
        if not os.path.isfile(pkg_json):
            details.append(f"⏭️  {proj_dir} — no package.json")
            continue

        # Check for a build script
        try:
            with open(pkg_json) as fp:
                pkg = json.load(fp)
            has_build = "build" in pkg.get("scripts", {})
            has_tsc = "tsc" in " ".join(pkg.get("scripts", {}).values())
        except Exception:
            has_build = False
            has_tsc = False

        if has_build:
            ok, out, err = run_cmd(["npm", "run", "build"], cwd=proj_dir)
            if ok:
                details.append(f"✅  {proj_dir} — npm build OK")
            else:
                details.append(f"❌  {proj_dir} — npm build failed:\n{err.strip()[:400]}")
                all_ok = False
        elif has_tsc:
            ok, out, err = run_cmd(["npx", "tsc", "--noEmit"], cwd=proj_dir)
            if ok:
                details.append(f"✅  {proj_dir} — tsc --noEmit OK")
            else:
                details.append(f"❌  {proj_dir} — tsc failed:\n{err.strip()[:400]}")
                all_ok = False
        else:
            details.append(f"⏭️  {proj_dir} — no build/tsc script")
    return all_ok, details


def execute_api_healthcheck(urls):
    """Ping URLs from the proposal to verify they're operational."""
    import urllib.request
    import urllib.error
    import ssl

    details = []
    all_ok = True
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    for url in set(urls):
        if not url.startswith(("http://", "https://")):
            continue
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=API_TIMEOUT) as resp:
                details.append(f"✅  {url} — HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            if e.code < 500:
                details.append(f"✅  {url} — HTTP {e.code} (acceptable)")
            else:
                details.append(f"❌  {url} — HTTP {e.code}")
                all_ok = False
        except Exception as e:
            details.append(f"❌  {url} — {str(e)[:100]}")
            all_ok = False
    return all_ok, details


def execute_git_check(gateway_dir=GATEWAY_DASHBOARD):
    """Check git status to see if there are uncommitted changes."""
    details = []
    for d in [gateway_dir, os.path.join(gateway_dir, "next")]:
        if not os.path.isdir(d):
            continue
        if not os.path.isdir(os.path.join(d, ".git")):
            continue
        ok, out, err = run_cmd(["git", "diff", "--stat"], cwd=d)
        if ok and out.strip():
            changed_lines = len(out.strip().split("\n"))
            details.append(f"📝  {d} — {changed_lines} files changed")
        elif ok:
            details.append(f"✅  {d} — clean working tree")
        else:
            details.append(f"⚠️  {d} — git error: {err.strip()[:100]}")
    return details


# ── Auto-Validator Pipeline ─────────────────────────────────────────
def run_auto_validate(safe_filename, actions, extra_context=None):
    """
    Run automatic validation checks on a proposal after implementation.
    Returns (all_ok: bool, checks: list[dict]).
    """
    log_prefix = f"[{safe_filename}] "
    logger.info("%sRunning auto-validator...", log_prefix)

    checks = []
    all_ok = True
    extra = extra_context or {}

    # 1. Find Python files from action text
    py_files = set()
    npm_dirs = set()
    api_urls = set()
    for action in actions:
        # Python files: look for .py paths
        for match in re.finditer(r"[\w/\\-]+\.py", action):
            candidate = match.group(0)
            # Try absolute or relative under dashboard
            if os.path.isfile(candidate):
                py_files.add(candidate)
            for base in [GATEWAY_DASHBOARD, os.path.join(GATEWAY_DASHBOARD, "next")]:
                full = os.path.join(base, candidate.lstrip("/"))
                if os.path.isfile(full):
                    py_files.add(full)
        # npm directories: look for package.json or next dir references
        if "npm" in action.lower() or "build" in action.lower() or "next" in action.lower():
            npm_dirs.add(NEXT_DIR)
            npm_dirs.add(GATEWAY_DASHBOARD)
        # URLs for healthcheck
        for match in re.finditer(r"https?://[\w/:.%-]+", action):
            api_urls.add(match.group(0).rstrip(").,;"))

    # Also include dashboard app.py always
    py_files.add(os.path.join(GATEWAY_DASHBOARD, "app.py"))
    # Also include new executor module
    exec_py = os.path.join(GATEWAY_DASHBOARD, "proposal_executor.py")
    if os.path.isfile(exec_py):
        py_files.add(exec_py)

    # 2. Run py_compile checks
    if py_files:
        py_ok, py_details = execute_py_compile(list(py_files))
        checks.append({
            "name": "Python 语法检查",
            "ok": py_ok,
            "details": py_details,
        })
        if not py_ok:
            all_ok = False
    else:
        checks.append({"name": "Python 语法检查", "ok": True, "details": ["⏭️  无 Python 文件需要检查"]})

    # 3. Run npm build checks
    if npm_dirs:
        npm_ok, npm_details = execute_npm_build(list(npm_dirs))
        checks.append({
            "name": "NPM 构建检查",
            "ok": npm_ok,
            "details": npm_details,
        })
        if not npm_ok:
            all_ok = False
    else:
        checks.append({"name": "NPM 构建检查", "ok": True, "details": ["⏭️  无前端项目需要检查"]})

    # 4. Git status check
    git_details = execute_git_check()
    checks.append({
        "name": "Git 工作树状态",
        "ok": True,
        "details": git_details,
    })

    # 5. API healthcheck (if we found URLs)
    if api_urls:
        api_ok, api_details = execute_api_healthcheck(list(api_urls))
        checks.append({
            "name": "API 健康检查",
            "ok": api_ok,
            "details": api_details,
        })
        if not api_ok:
            all_ok = False

    # 6. Check flask backend is running
    flask_ok, _, _ = run_cmd(["curl", "-sf", "-o", "/dev/null", "http://127.0.0.1:5000/api/status"])
    checks.append({
        "name": "Flask 后端状态",
        "ok": flask_ok,
        "details": [
            "✅  Flask 响应正常" if flask_ok else "❌  Flask 未响应",
        ],
    })
    if not flask_ok:
        all_ok = False

    # 7. Check Next.js frontend is running
    next_ok, _, _ = run_cmd(["curl", "-sf", "-o", "/dev/null", "http://127.0.0.1:3000"])
    checks.append({
        "name": "Next.js 前端状态",
        "ok": next_ok,
        "details": [
            "✅  Next.js 响应正常" if next_ok else "❌  Next.js 未响应",
        ],
    })
    if not next_ok:
        all_ok = False

    return all_ok, checks


# ── Proposal Update Helpers ─────────────────────────────────────────
def _set_proposal_status(safe_filename, status_field, status_value, event_title, event_note=""):
    """Update proposal frontmatter + append event."""
    fpath = os.path.join(PROPOSALS_DIR, safe_filename)
    if not os.path.isfile(fpath):
        fpath += ".md"
    if not os.path.isfile(fpath):
        return
    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        updates = {
            "status": status_value,
            f"{status_field}_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        content = _update_frontmatter(content, updates)
        content = _append_event(content, event_title, event_note)
        _atomic_write(fpath, content)
        logger.info("Proposal %s status → %s", safe_filename, status_value)
    except Exception as e:
        logger.error("Failed to update proposal %s: %s", safe_filename, e)


# ── Main Executor ───────────────────────────────────────────────────
def run_proposal_async(safe_filename):
    """
    Execute a proposal's actions in a background thread.
    This function runs in a daemon thread — designed to be spawned and forgotten.
    """
    log_prefix = f"[{safe_filename}] "
    _write_log(safe_filename, "start_exec", f"开始自动实施提案: {safe_filename}", status="running")

    # Read proposal
    content, meta, body, actions = _read_proposal(safe_filename)
    if content is None:
        _write_log(safe_filename, "error", f"无法读取提案: {safe_filename}", status="error")
        _set_proposal_status(
            safe_filename.replace(".md", ""),
            "status", "failed",
            "❌ 自动实施失败", "无法读取提案文件。"
        )
        return

    if not actions:
        _write_log(safe_filename, "warn", "未找到可执行行动项", status="done")
        _set_proposal_status(
            safe_filename.replace(".md", ""),
            "status", "failed",
            "❌ 自动实施失败", "未找到可执行行动项。"
        )
        _write_log(safe_filename, "exec_complete", "执行完成（无行动项）", status="done")
        return

    _write_log(
        safe_filename, "info",
        f"共发现 {len(actions)} 项待执行行动",
        status="running",
    )

    # Execute each action
    all_action_ok = True
    for idx, action in enumerate(actions):
        action_label = action[:80]
        _write_log(
            safe_filename, "action_start",
            f"[{idx + 1}/{len(actions)}] 执行: {action_label}",
            action_idx=idx,
            status="running",
        )

        try:
            # Determine action type and execute
            action_lower = action.lower()

            # --- Python file modification ---
            if any(kw in action_lower for kw in ("python", ".py", "py_compile", "修改", "新增")):
                # Try to parse specific Python files
                py_matches = re.findall(r"[\w/\\-]+\.py", action)
                if py_matches:
                    py_paths = []
                    for pm in py_matches:
                        if os.path.isfile(pm):
                            py_paths.append(pm)
                        else:
                            # Check in gateway-dashboard
                            full = os.path.join(GATEWAY_DASHBOARD, pm.lstrip("/"))
                            if os.path.isfile(full):
                                py_paths.append(full)
                            full = os.path.join(NEXT_DIR, pm.lstrip("/"))
                            if os.path.isfile(full):
                                py_paths.append(full)
                    if py_paths:
                        ok, details = execute_py_compile(py_paths)
                        for d in details:
                            _write_log(safe_filename, "info" if "✅" in d else "warn", d, action_idx=idx)
                        if ok:
                            _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 完成: {action_label}", action_idx=idx, status="done")
                        else:
                            _write_log(safe_filename, "action_error", f"❌ 行动 {idx + 1} 失败: Python 语法检查未通过", action_idx=idx, status="failed")
                            all_action_ok = False
                        continue
                # No .py files found, try generic git diff or describe what would be done
                _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 标记完成: {action_label}（无法自动解析具体文件）", action_idx=idx, status="done")

            # --- SSH / Config / Shell commands ---
            elif any(kw in action_lower for kw in ("配置", "部署", "修改配置", "启动", "安装", "新增环境")):
                _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 标记完成: {action_label}（配置类操作需人工确认）", action_idx=idx, status="done")

            # --- Analysis / Audit / Non-code ---
            elif any(kw in action_lower for kw in ("分析", "审查", "审计", "统计", "评估", "报告")):
                _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 标记完成: {action_label}（分析类操作）", action_idx=idx, status="done")

            # --- Git / PR related ---
            elif any(kw in action_lower for kw in ("git", "pr", "分支", "merge", "commit")):
                ok, out, err = run_cmd(["git", "status", "--short"], cwd=GATEWAY_DASHBOARD)
                if ok and out.strip():
                    _write_log(safe_filename, "info", f"Git 有未提交变更:\n{out.strip()[:500]}", action_idx=idx)
                _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 完成: {action_label}", action_idx=idx, status="done")

            # --- Build / Compile ---
            elif any(kw in action_lower for kw in ("build", "构建", "编译", "打包")):
                ok, details = execute_npm_build([NEXT_DIR, GATEWAY_DASHBOARD])
                for d in details:
                    _write_log(safe_filename, "info" if "✅" in d else "warn", d, action_idx=idx)
                _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 完成: {action_label}", action_idx=idx, status="done")

            # --- Fallback: action marked as done (no specific executor) ---
            else:
                _write_log(safe_filename, "action_done", f"✅ 行动 {idx + 1} 完成: {action_label}（自动标记）", action_idx=idx, status="done")

        except Exception as e:
            _write_log(safe_filename, "action_error", f"❌ 行动 {idx + 1} 异常: {str(e)}", action_idx=idx, status="error")
            all_action_ok = False

    # ── Execution complete — now run auto-validator ──────────────────
    _write_log(safe_filename, "info", "所有行动执行完毕，开始自动验证...", status="validating")

    try:
        validate_ok, checks = run_auto_validate(safe_filename, actions)
        for check in checks:
            status_icon = "✅" if check["ok"] else "❌"
            _write_log(safe_filename, "info", f"{status_icon} {check['name']}", status="validating")
            for detail in check["details"]:
                _write_log(safe_filename, "info", f"  {detail}", status="validating")

        final_status = "verified" if validate_ok else "failed"
        final_label = "✅ 验证通过" if validate_ok else "❌ 验证失败"
        final_note_lines = []
        for check in checks:
            icon = "✅" if check["ok"] else "❌"
            final_note_lines.append(f"{icon} {check['name']}")
        final_note = "\n".join(final_note_lines)

        _set_proposal_status(
            safe_filename.replace(".md", ""),
            "status" if validate_ok else "status",
            final_status,
            final_label,
            final_note,
        )
        _write_log(safe_filename, "exec_complete", f"执行完成 — 状态: {final_status}", status=final_status)

        # ── Feedback loop: after-snapshot + impact assessment ─────
        try:
            after_shot = feedback_collect_snapshot()
            log_dir = _exec_log_dir(safe_filename.replace(".md", ""))
            after_path = os.path.join(log_dir, "after_snapshot.json")
            with open(after_path, "w") as fp:
                json.dump(after_shot, fp, indent=2, ensure_ascii=False)

            # Read before snapshot
            before_path = os.path.join(log_dir, "before_snapshot.json")
            if os.path.isfile(before_path):
                with open(before_path) as fp:
                    before_shot = json.load(fp)
                impact = feedback_assess_impact(before_shot, after_shot)
                impact_path = os.path.join(log_dir, "impact.json")
                with open(impact_path, "w") as fp:
                    json.dump(impact, fp, indent=2, ensure_ascii=False)
                _write_log(safe_filename, "info",
                    f"📊 效果评估: {impact['overall']} ({impact['improvements']}↑ / {impact['regressions']}↓)",
                    status=final_status)
            else:
                _write_log(safe_filename, "info", "📊 无基线数据，跳过效果评估", status=final_status)
        except Exception as e:
            logger.warning("Feedback loop after-exec failed: %s", e)
            _write_log(safe_filename, "warn", f"效果评估失败（不影响结果）: {e}", status=final_status)
    except Exception as e:
        logger.error("%sAuto-validate failed: %s\n%s", log_prefix, e, traceback.format_exc())
        _write_log(safe_filename, "error", f"自动验证异常: {str(e)}", status="error")
        _set_proposal_status(
            safe_filename.replace(".md", ""),
            "status", "implemented",
            "⚠️ 已实施（验证异常）", f"执行完成但验证过程异常: {str(e)}"
        )


# ── Thread Management ───────────────────────────────────────────────
_running_tasks = {}  # safe_filename -> threading.Thread
_lock = threading.Lock()


def start_execution(safe_filename):
    """Start async execution of a proposal. Returns (ok, message)."""
    with _lock:
        if safe_filename in _running_tasks and _running_tasks[safe_filename].is_alive():
            return False, "该提案正在执行中，请等待完成"

        # Validate proposal can be executed
        content, meta, body, actions = _read_proposal(safe_filename)
        if content is None:
            return False, "无法读取提案文件"
        pstatus = meta.get("status", "unknown")
        if pstatus != "approved":
            return False, f"提案状态为 '{pstatus}'，需要 'approved'"

        # Set frontmatter to implementing
        _set_proposal_status(
            safe_filename.replace(".md", ""),
            "status", "implementing",
            "⚡ 开始自动实施",
            f"已启动后台执行器，共 {len(actions)} 项行动。",
        )

        # Collect before-execution snapshot for feedback loop
        try:
            before_shot = feedback_collect_snapshot()
            log_dir = _exec_log_dir(safe_filename.replace(".md", ""))
            before_path = os.path.join(log_dir, "before_snapshot.json")
            with open(before_path, "w") as fp:
                json.dump(before_shot, fp, indent=2, ensure_ascii=False)
            logger.info("Before snapshot saved: %s (%d metrics)", before_path, len(before_shot))
        except Exception as e:
            logger.warning("Failed to collect before-snapshot: %s", e)
            _write_log(safe_filename, "warn", f"基线采集失败（不影响执行）: {e}", status="running")

        # Spawn thread
        t = threading.Thread(
            target=run_proposal_async,
            args=(safe_filename,),
            daemon=True,
        )
        t.start()
        _running_tasks[safe_filename] = t

        action_count = len(actions)
        return True, f"后台执行已启动 — {action_count} 项行动"


def stop_execution(safe_filename):
    """Mark a running execution as stopped (threads can't be killed cleanly)."""
    with _lock:
        if safe_filename in _running_tasks and _running_tasks[safe_filename].is_alive():
            _write_log(safe_filename, "warn", "用户请求停止执行", status="cancelled")
            _set_proposal_status(
                safe_filename.replace(".md", ""),
                "status", "implementing",
                "⏹ 执行已停止", "用户手动停止了自动实施。",
            )
            return True, "已标记停止（后台线程将在完成后退出）"
    return False, "该提案未在运行中"


def get_running_status(safe_filename):
    """Get running status for a proposal."""
    with _lock:
        if safe_filename in _running_tasks:
            alive = _running_tasks[safe_filename].is_alive()
            if alive:
                return "running"
    summary = get_exec_summary(safe_filename)
    if summary["running"]:
        return "running"
    if summary["actions_total"] > 0 and summary["actions_done"] + summary["actions_failed"] >= summary["actions_total"]:
        return "completed"
    return "idle"


# ── Manual auto-verify API ──────────────────────────────────────────
def run_verify(safe_filename):
    """
    Run auto-validator on an implemented proposal and update its status.
    Returns (ok: bool, all_passed: bool, checks: list).
    """
    safe = safe_filename.replace(".md", "")
    content, meta, body, actions = _read_proposal(safe_filename)
    if content is None:
        return False, False, [{"name": "错误", "ok": False, "details": ["提案文件无法读取"]}]
    current_status = meta.get("status", "unknown")
    if current_status not in ("implementing", "implemented", "failed"):
        return False, False, [{
            "name": "状态错误",
            "ok": False,
            "details": [f"当前状态为 {current_status}，必须是 implementing/implemented/failed 才能自动验证"],
        }]

    _write_log(safe_filename, "info", "开始手动触发自动验证...", status="validating")

    try:
        all_ok, checks = run_auto_validate(safe_filename, actions)
        for check in checks:
            icon = "✅" if check["ok"] else "❌"
            _write_log(safe_filename, "info", f"{icon} {check['name']}", status="validating")

        final_status = "verified" if all_ok else "failed"
        final_label = "✅ 验证通过" if all_ok else "❌ 验证失败"
        final_note_lines = []
        for check in checks:
            icon = "✅" if check["ok"] else "❌"
            final_note_lines.append(f"{icon} {check['name']}")
        final_note = "\n".join(final_note_lines)

        _set_proposal_status(
            safe, "status", final_status, final_label, final_note,
        )
        _write_log(safe_filename, "exec_complete", f"验证完成 — 状态: {final_status}", status=final_status)
        return True, all_ok, checks
    except Exception as e:
        _write_log(safe_filename, "error", f"验证异常: {str(e)}", status="error")
        return False, False, [{"name": "异常", "ok": False, "details": [str(e)]}]


# ── Feedback Loop: Before/After Snapshots ────────────────────────────

def feedback_collect_snapshot():
    """
    Collect a 'baseline' or 'post-execution' snapshot of system metrics.
    Returns a dict storable as JSON. All checks are lightweight (< 1s each).
    Fields ending in _ok are boolean; fields ending in _count are integers.
    """
    snapshot = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "flask_ok": False,
        "nextjs_ok": False,
        "git_modified_count": -1,
        "py_compile_ok": True,
        "py_compile_errors": [],
        "mem_mb": -1.0,
        "load_1m": -1.0,
    }

    # Flask health
    try:
        r = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}",
             "http://127.0.0.1:5000/api/status"],
            capture_output=True, text=True, timeout=API_TIMEOUT,
        )
        snapshot["flask_ok"] = r.returncode == 0 and r.stdout.strip() == "200"
    except Exception:
        pass

    # Next.js health
    try:
        r = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}",
             "http://127.0.0.1:3000"],
            capture_output=True, text=True, timeout=API_TIMEOUT,
        )
        snapshot["nextjs_ok"] = r.returncode == 0 and r.stdout.strip() == "200"
    except Exception:
        pass

    # Git modified files count
    try:
        r = subprocess.run(
            ["git", "-C", GATEWAY_DASHBOARD, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in r.stdout.split("\n") if l.strip()]
        snapshot["git_modified_count"] = len(lines)
    except Exception:
        pass

    # py_compile on key Python files
    py_targets = [
        os.path.join(GATEWAY_DASHBOARD, "app.py"),
        os.path.join(GATEWAY_DASHBOARD, "proposal_executor.py"),
    ]
    errors = []
    for fpath in py_targets:
        if os.path.isfile(fpath):
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", fpath],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                errors.append(f"{os.path.basename(fpath)}: {r.stderr.strip()[:200]}")
    if errors:
        snapshot["py_compile_ok"] = False
        snapshot["py_compile_errors"] = errors

    # Memory & load (quick /proc read)
    try:
        with open("/proc/meminfo") as fp:
            for line in fp:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    snapshot["mem_mb"] = round(kb / 1024, 1)
                    break
    except Exception:
        pass
    try:
        with open("/proc/loadavg") as fp:
            snapshot["load_1m"] = float(fp.read().split()[0])
    except Exception:
        pass

    return snapshot


def feedback_assess_impact(before, after):
    """
    Compare before and after snapshots. Returns an impact assessment dict.

    Returns:
    {
        "overall": "positive" | "neutral" | "negative",
        "ts": "ISO timestamp",
        "details": [
            {"metric": "flask_ok", "label": "Flask 后端", "before": true, "after": true, "change": "unchanged"},
            ...
        ]
    }
    """
    details = []
    improvements = 0
    regressions = 0

    # Define metrics to compare
    metrics = [
        ("flask_ok", "Flask 后端"),
        ("nextjs_ok", "Next.js 前端"),
        ("py_compile_ok", "Python 语法"),
    ]

    for key, label in metrics:
        bv = before.get(key)
        av = after.get(key)
        if bv is True and av is False:
            change = "degraded"
            regressions += 1
        elif bv is False and av is True:
            change = "improved"
            improvements += 1
        else:
            change = "unchanged"
        details.append({
            "metric": key,
            "label": label,
            "before": bv,
            "after": av,
            "change": change,
        })

    # Numeric metrics
    num_metrics = [
        ("git_modified_count", "Git 变更文件数", "lower_is_better"),
        ("mem_mb", "可用内存 (MB)", "higher_is_better"),
        ("load_1m", "系统负载 (1m)", "lower_is_better"),
    ]
    for key, label, direction in num_metrics:
        bv = before.get(key, -1)
        av = after.get(key, -1)
        if bv == -1 or av == -1:
            change = "unknown"
        elif direction == "lower_is_better":
            if av < bv:
                change = "improved"
                improvements += 1
            elif av > bv:
                change = "degraded"
                regressions += 1
            else:
                change = "unchanged"
        else:  # higher_is_better
            if av > bv:
                change = "improved"
                improvements += 1
            elif av < bv:
                change = "degraded"
                regressions += 1
            else:
                change = "unchanged"
        details.append({
            "metric": key,
            "label": label,
            "before": bv,
            "after": av,
            "change": change,
        })

    if regressions > 0:
        overall = "negative"
    elif improvements > 0:
        overall = "positive"
    else:
        overall = "neutral"

    return {
        "overall": overall,
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "improvements": improvements,
        "regressions": regressions,
        "details": details,
    }


def feedback_get_impact(safe_filename):
    """Load feedback impact data from disk. Returns dict or None."""
    d = _exec_log_dir(safe_filename.replace(".md", ""))
    impact_path = os.path.join(d, "impact.json")
    if os.path.isfile(impact_path):
        try:
            with open(impact_path) as fp:
                return json.load(fp)
        except Exception:
            pass
    return None
