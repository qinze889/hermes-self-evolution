# Gateway Registration & User Management Fixes

## `hermes gateway install` hangs in subprocess

**Symptom**: Flask `/api/bot/register` fails with "网关服务安装失败，请检查 hermes 配置。" after 30s timeout.

**Root cause**: `hermes gateway install` has two interactive prompts:
1. "Start the gateway now after installing the service? [Y/n]"
2. "Start the gateway automatically on login/boot with systemd? [Y/n]"

When called via `subprocess.run()` without stdin, both prompts hang until timeout.

**Fix**: Pipe two "y" answers:
```python
subprocess.run(
    ["/root/.local/bin/hermes", "--profile", name, "gateway", "install"],
    input="y\ny\n", capture_output=True, text=True, timeout=30
)
```

## User counting was wrong (platform filenames, not user IDs)

**Symptom**: Admin panel showed wrong user count. Only counted users who went through pairing approval.

**Root cause**: Original code counted `pairing/*-approved.json` filenames ("weixin", "qqbot") instead of actual user IDs inside the JSON files. Also, open-mode bots (DM_POLICY=open) never create pairing files.

**Fix**: 
1. Use `_scan_all_users()` that queries `SELECT DISTINCT user_id FROM sessions` from all profile `state.db` files
2. Add `ADMIN_IDS` env var (comma-separated) to distinguish admins from regular users

```python
def _scan_all_users():
    import sqlite3
    user_ids = set()
    hermes_home = os.path.expanduser("~/.hermes")
    # Scan default + all profile state.db files
    for root, _, files in os.walk(hermes_home):
        for f in files:
            if f == "state.db":
                conn = sqlite3.connect(os.path.join(root, f))
                rows = conn.execute("SELECT DISTINCT user_id FROM sessions WHERE user_id IS NOT NULL AND user_id != ''").fetchall()
                conn.close()
                for (uid,) in rows:
                    user_ids.add(uid)
    return sorted(user_ids)
```

## Token index stale → personal panel 404

**Symptom**: User "个人面板" links return 404 even though tokens exist.

**Root cause**: `get_user_token()` creates token files but doesn't rebuild the reverse index `_token_index.json`. `resolve_token()` reads the stale index and returns None.

**Fix**: Call `_rebuild_token_index()` immediately after creating a new token:
```python
def get_user_token(user_id):
    prefs = get_user_prefs(user_id)
    if "token" not in prefs:
        prefs["token"] = uuid.uuid4().hex[:16]
        save_user_prefs(user_id, prefs)
        _rebuild_token_index()  # ← critical
    return prefs["token"]
```
