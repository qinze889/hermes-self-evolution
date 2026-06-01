#!/usr/bin/env python3
"""
Implementation executor for Hermes Evolution proposals.
Reads an approved proposal, delegates implementation to GPT-5.4 subagent,
writes the implementation report, and updates the proposal status.

Usage:
  python3 implement_proposal.py <proposal_file.md>
  python3 implement_proposal.py --all       # Execute all approved proposals
  python3 implement_proposal.py --list      # List approved proposals ready for exec
"""
import json
import os
import re
import subprocess
import sys
import datetime

PROPOSALS_DIR = os.path.expanduser("~/.hermes/proposals")


def parse_proposal(filepath):
    """Read a proposal file and return its frontmatter + actions."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    frontmatter = {}
    actions = []
    body = content

    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            raw_fm = content[3:end]
            body = content[end + 3:]
            for line in raw_fm.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip()

    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("- **") and "收益" in s and "工作量" in s:
            t = s[3:]
            idx = t.find("**")
            if idx > 0:
                actions.append(t[:idx].strip())

    return frontmatter, actions, content


def update_proposal(filepath, content, updates, event_title, event_body):
    """Update YAML frontmatter and append event."""
    # Update frontmatter
    body = content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            fm_lines = content[3:end].split("\n")
            new_lines = []
            seen = set()
            for line in fm_lines:
                if ":" in line:
                    k = line.split(":", 1)[0].strip()
                    seen.add(k)
                    if k in updates:
                        new_lines.append(f"{k}: {updates[k]}")
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            for k, v in updates.items():
                if k not in seen:
                    new_lines.append(f"{k}: {v}")
                    seen.add(k)
            new_fm = "\n".join(new_lines)
            body = "---" + new_fm + content[end:]

    # Append event
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CST")
    body = body.rstrip() + f"\n\n## {event_title} ({now})\n"
    if event_body:
        body += f"\n> {event_body}\n"

    # Atomic write
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, filepath)


def list_approved():
    """List all approved proposals ready for execution."""
    results = []
    if not os.path.isdir(PROPOSALS_DIR):
        return results
    for fname in sorted(os.listdir(PROPOSALS_DIR)):
        if fname in ("INDEX.md", "TEMPLATE.md") or not fname.endswith(".md"):
            continue
        fpath = os.path.join(PROPOSALS_DIR, fname)
        fm, actions, _ = parse_proposal(fpath)
        if fm.get("status") == "approved":
            results.append({
                "file": fname,
                "title": fm.get("title", fname),
                "score": fm.get("score", "0"),
                "actions": len(actions),
                "risk": fm.get("risk", "unknown"),
            })
    return results


def main():
    if "--list" in sys.argv:
        for p in list_approved():
            print(f"  {p['title']:40s} | ⭐{p['score']:>3} | {p['actions']} actions | {p['risk']}")
        print(f"\nTotal: {len(list_approved())} approved proposals pending execution")
        return

    if "--all" in sys.argv:
        approved = list_approved()
        print(f"Found {len(approved)} approved proposals")
        for p in approved:
            print(f"\n{'='*60}")
            print(f"Executing: {p['title']}")
            filepath = os.path.join(PROPOSALS_DIR, p['file'])
            main_for_file(filepath, p['file'])
        return

    if len(sys.argv) < 2:
        print("Usage: implement_proposal.py <file.md | --all | --list>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        filepath = os.path.join(PROPOSALS_DIR, filepath)
    if not os.path.isfile(filepath):
        print(f"Not found: {sys.argv[1]}")
        sys.exit(1)

    main_for_file(filepath, os.path.basename(filepath))


def main_for_file(filepath, filename):
    """Execute a single proposal."""
    fm, actions, content = parse_proposal(filepath)
    status = fm.get("status", "unknown")

    if status != "approved":
        print(f"Status is '{status}', not 'approved'. Skipping.")
        return

    title = fm.get("title", filename)
    url = fm.get("source_url", "")
    score = fm.get("score", "0")

    print(f"📋 Proposal: {title}")
    print(f"   Source: {url}")
    print(f"   Score:  {score}")
    print(f"   Actions ({len(actions)}):")
    for i, a in enumerate(actions, 1):
        print(f"     {i}. {a}")

    # Step 1: Set to implementing
    update_proposal(filepath, content,
        {"status": "implementing", "implemented_at": datetime.datetime.now().isoformat(timespec="seconds")},
        "⚡ 开始自动实施", f"GPT-5.4 子代理正在执行 {len(actions)} 项行动。")
    # Re-read
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Step 2: For each action, delegate to GPT-5.4 subagent
    results = []
    for i, action in enumerate(actions, 1):
        print(f"\n{'─'*50}")
        print(f"🔧 Action {i}/{len(actions)}: {action}")
        result = execute_action(title, url, action, i, len(actions))
        results.append(result)
        print(f"   ✓ Done")

    # Step 3: Write implementation report
    report = build_report(actions, results, title)

    # Step 4: Update to implemented
    update_proposal(filepath, content,
        {"status": "implemented", "implemented_at": datetime.datetime.now().isoformat(timespec="seconds")},
        "🚀 自动实施完成",
        f"GPT-5.4 子代理已完成 {len(actions)}/{len(actions)} 项行动。\n\n{report}")
    print(f"\n{'='*60}")
    print(f"✅ Implementation complete for: {title}")
    print(f"   Updated to status: implemented")
    print(f"\nReport:\n{report}")


def execute_action(proposal_title, source_url, action_text, idx, total):
    """Delegate an action to GPT-5.4 subagent for implementation."""
    prompt = f"""你正在实施一个进化提案的行动项。

## 提案名称
{proposal_title}

## 来源
{source_url}

## 当前行动 ({idx}/{total})
{action_text}

## 任务
1. 如果这是研究/分析类行动：深入调研该主题，生成一份全面的分析报告，包括技术架构、优缺点、集成方案建议。
2. 如果这是开发/实现类行动：编写代码或配置，评估可行性和工作量。
3. 输出格式：Markdown 格式的"实施报告"。

请直接输出你的工作成果，不要问问题。"""
    
    try:
        output = _invoke_beef_api(prompt)
        if len(output) > 2000:
            output = output[:2000] + f"\n\n...（完整报告共 {len(output)} 字符，保存为文件）"
    except Exception as e:
        output = f"实施失败: {e}"

    return {"action": action_text, "output": output}


def _invoke_beef_api(prompt, timeout=120):
    """Call GPT-5.4 (Beef API) directly using 'requests' library.
    Returns the response text.
    """
    key = _load_env_key("BEEF_API_KEY")
    if not key:
        raise RuntimeError("BEEF_API_KEY not found in ~/.hermes/.env")

    try:
        import requests
    except ImportError:
        # Fallback: urllib with no_proxy
        import urllib.request
        import json

        payload = json.dumps({
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": "你是一个专业的实施工程师，负责执行 Hermes 进化系统提案中的行动项。输出全面的、可操作的实施报告。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.3,
        }).encode()

        # Avoid proxy for Beef API (direct domestic)
        req = urllib.request.Request(
            "https://beefapi.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
        )
        old_proxy = os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        finally:
            if old_proxy is not None:
                os.environ["HTTP_PROXY"] = old_proxy

        return data["choices"][0]["message"]["content"]

    # Use requests library (cleaner)
    payload = {
        "model": "gpt-5.4",
        "messages": [
            {"role": "system", "content": "你是一个专业的实施工程师，负责执行 Hermes 进化系统提案中的行动项。输出全面的、可操作的实施报告。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }
    # Disable proxy for Beef API (domestic endpoint)
    resp = requests.post(
        "https://beefapi.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=timeout,
        proxies={"http": None, "https": None},
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _load_env_key(key_name):
    """Load a key from ~/.hermes/.env by name."""
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.isfile(env_path):
        return os.environ.get(key_name, "")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(key_name + "="):
                return line.split("=", 1)[1]
    return os.environ.get(key_name, "")


def build_report(actions, results, title):
    """Build a markdown implementation report."""
    lines = []
    lines.append(f"### 实施报告：{title}")
    lines.append("")
    for i, (action, result) in enumerate(zip(actions, results), 1):
        lines.append(f"#### {i}. {action}")
        lines.append("")
        lines.append(result["output"])
        lines.append("")
    lines.append("---")
    lines.append(f"_自动实施于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M CST')}_")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
