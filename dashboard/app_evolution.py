#!/usr/bin/env python3
"""Multi-Tenant AI Bot Platform — Landing + Admin + Status + Upload + Chat"""
import subprocess
import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse
import ssl
import logging
import hmac
import zipfile
import tarfile
import datetime
import mimetypes
import requests
import threading
import tempfile
from functools import wraps
from collections import defaultdict
from flask import (Flask, render_template_string, request, redirect,
                   url_for, send_from_directory, jsonify)
from werkzeug.middleware.proxy_fix import ProxyFix

# ── Proposal Executor ────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposal_executor as pexec

# ── Config ──────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", uuid.uuid4().hex)

# Public-facing domain for file URLs (set via env var)
PUBLIC_DOMAIN = os.environ.get("PUBLIC_DOMAIN", "https://124.222.135.234")
MINERU_FILE_BASE = os.environ.get("MINERU_FILE_BASE", "http://124.222.135.234")

UPLOAD_DIR = "/root/uploads/files"
CONSTITUTION_FILE = "/root/constitution.md"
USER_PREFS_DIR = "/root/user_prefs"
SOUL_PATH = os.path.expanduser("~/.hermes/SOUL.md")
SYSTEM_DOC_PATH = "/root/.hermes/cache/system-doc.html"
SYSTEM_DOC_MD_PATH = "/root/.hermes/cache/system-doc.md"

ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml",
    ".c", ".h", ".cpp", ".hpp", ".py", ".java", ".js", ".ts",
    ".zip", ".gz", ".tar", ".7z", ".rar",
}
MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_FILE_SIZE = MAX_CONTENT_LENGTH
DEFAULT_MODEL_ID = "deepseek-v4-flash"

AVAILABLE_MODELS = [
    {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "desc": "快速响应，适合日常对话"},
    {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "desc": "更强推理能力，适合复杂问题"},
]

# ── QR Code (iLink WeChat Bot) ──────────────────────────────────────
ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0  # 131328
QR_CODE_CACHE = {"data": None, "ts": 0.0}
QR_CACHE_TTL = 90  # iLink QR码有效期2分钟，90秒缓存留余量
QR_FALLBACK_TARGET = "https://liteapp.weixin.qq.com/q/7GiQu1"
QR_FALLBACK_IMAGE = (
    "https://api.qrserver.com/v1/create-qr-code/"
    "?size=300x300&data=https://liteapp.weixin.qq.com/q/7GiQu1"
)


def _fetch_bot_qrcode():
    """Fetch current WeChat QR code from iLink backend.

    Returns dict with qr_target_url and qr_image_url.
    Falls back to static URL on any failure.
    """
    now = time.time()
    if QR_CODE_CACHE["data"] and (now - QR_CODE_CACHE["ts"]) < QR_CACHE_TTL:
        return QR_CODE_CACHE["data"]

    target_url = QR_FALLBACK_TARGET
    qrcode_value = ""
    try:
        url = f"{ILINK_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
        headers = {
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        qrcode_value = data.get("qrcode", "")
        candidate = data.get("qrcode_img_content", "")
        if candidate:
            target_url = candidate
    except Exception as e:
        logger.warning("Failed to fetch iLink QR code: %s", e)

    encoded = urllib.parse.quote(target_url, safe="")
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"
    result = {
        "qr_target_url": target_url,
        "qr_image_url": qr_image_url,
        "qr_value": qrcode_value,
    }
    QR_CODE_CACHE["data"] = result
    QR_CODE_CACHE["ts"] = now
    return result


class NoProxyHandler(urllib.request.HTTPSHandler):
    """HTTPS handler used with ProxyHandler({}) to bypass HTTP(S)_PROXY for iLink."""
    pass


def _ilink_get_json(path, timeout=15):
    """Call iLink with urllib while bypassing environment proxy settings."""
    url = f"{ILINK_BASE_URL}{path}"
    headers = {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoProxyHandler())
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_bot_qr(data):
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    qr_value = payload.get("qrcode") or payload.get("qr_value") or ""
    target_url = payload.get("qrcode_img_content") or payload.get("qr_target_url") or payload.get("url") or ""
    image_url = payload.get("qr_image_url") or payload.get("qrcode_img_url") or ""
    if not image_url and target_url:
        encoded = urllib.parse.quote(target_url, safe="")
        image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"
    return {"qr_target_url": target_url, "qr_image_url": image_url, "qr_value": qr_value}


def _normalize_bot_qr_status(data):
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    raw_status = payload.get("status") or payload.get("qrcode_status") or payload.get("state") or "wait"
    status_map = {
        0: "wait", 1: "scanned", 2: "confirmed", 3: "expired",
        "0": "wait", "1": "scanned", "2": "confirmed", "3": "expired",
        "waiting": "wait", "wait": "wait", "scan": "scanned", "scanned": "scanned",
        "confirm": "confirmed", "confirmed": "confirmed", "expired": "expired", "expire": "expired",
        "refused": "refused", "rejected": "refused", "already_bound": "refused",
    }
    status = status_map.get(raw_status, status_map.get(str(raw_status).lower(), "wait"))
    result = dict(payload)
    result["status"] = status
    # Check for already-bound indication
    raw_msg = str(payload.get("msg", "") or payload.get("message", "")).lower()
    if "already" in raw_msg or "registered" in raw_msg or status == "refused":
        result["status"] = "already_bound"
        result["hint"] = "该微信已注册过 Bot，请使用其他微信扫码"
    return result


# ── App setup ───────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(USER_PREFS_DIR, exist_ok=True)

# ── Rate limiter ─────────────────────────────────────────────────────
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 20     # max requests per window
_rate_lock = threading.Lock()
_rate_map = defaultdict(list)

# Bot registration concurrency guard
_register_lock = threading.Lock()
_active_registrations = set()

def rate_limit(ip_addr):
    """Simple sliding-window rate limiter. Returns True if allowed."""
    now = time.time()
    with _rate_lock:
        window = _rate_map[ip_addr]
        # Prune expired entries
        cutoff = now - RATE_LIMIT_WINDOW
        _rate_map[ip_addr] = [t for t in window if t > cutoff]
        entries = _rate_map[ip_addr]
        if len(entries) >= RATE_LIMIT_MAX:
            logger.warning("Rate limit exceeded for %s (%d in %ds)", ip_addr, len(entries), RATE_LIMIT_WINDOW)
            return False
        entries.append(now)
        return True


# ── Token Usage Tracking ──────────────────────────────────────────────
TOKEN_LOG_PATH = "/root/gateway-dashboard/token_usage.json"
_token_lock = threading.Lock()

def load_token_usage():
    """Load token usage log from JSON file."""
    try:
        with open(TOKEN_LOG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_token_usage(entries):
    """Save token usage log to JSON file."""
    tmp = TOKEN_LOG_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(entries, f)
        os.replace(tmp, TOKEN_LOG_PATH)
    except Exception as e:
        logger.warning("Failed to save token usage: %s", e)

def record_token_usage(model, prompt_tokens, completion_tokens, user_id="web"):
    """Record a token usage entry."""
    entry = {
        "ts": time.time(),
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "user": user_id,
    }
    with _token_lock:
        entries = load_token_usage()
        entries.append(entry)
        # Keep last 10000 entries
        if len(entries) > 10000:
            entries = entries[-10000:]
        save_token_usage(entries)

def get_token_summary(hours=None):
    """Get token usage summary.
    Default: today (Beijing time 00:00-23:59 calendar day).
    If hours is specified and > 0, use rolling window of last N hours."""
    if hours is not None and hours > 0:
        cutoff = time.time() - hours * 3600
        period = f"近{hours}小时"
    else:
        # Beijing time (UTC+8) calendar day start
        now = datetime.datetime.now(datetime.timezone.utc)
        beijing = now + datetime.timedelta(hours=8)
        today_start = beijing.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start - datetime.timedelta(hours=8)
        cutoff = today_start_utc.timestamp()
        period = "今日"
    with _token_lock:
        entries = load_token_usage()
        recent = [e for e in entries if e.get("ts", 0) > cutoff]
        total_prompt = sum(e.get("prompt_tokens", 0) for e in recent)
        total_completion = sum(e.get("completion_tokens", 0) for e in recent)
        total_all = total_prompt + total_completion
        all_prompt = sum(e.get("prompt_tokens", 0) for e in entries)
        all_completion = sum(e.get("completion_tokens", 0) for e in entries)
        all_total = all_prompt + all_completion
        all_calls = len(entries)
        model_breakdown = {}
        for e in recent:
            m = e.get("model", "unknown")
            model_breakdown.setdefault(m, {"prompt": 0, "completion": 0, "calls": 0})
            model_breakdown[m]["prompt"] += e.get("prompt_tokens", 0)
            model_breakdown[m]["completion"] += e.get("completion_tokens", 0)
            model_breakdown[m]["calls"] += 1
        all_model_breakdown = {}
        for e in entries:
            m = e.get("model", "unknown")
            all_model_breakdown.setdefault(m, {"prompt": 0, "completion": 0, "calls": 0})
            all_model_breakdown[m]["prompt"] += e.get("prompt_tokens", 0)
            all_model_breakdown[m]["completion"] += e.get("completion_tokens", 0)
            all_model_breakdown[m]["calls"] += 1
    return {
        "total_tokens": total_all,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "call_count": len(recent),
        "models": model_breakdown,
        "period": period,
        "all_total_tokens": all_total,
        "all_prompt_tokens": all_prompt,
        "all_completion_tokens": all_completion,
        "all_call_count": all_calls,
        "all_models": all_model_breakdown,
    }


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/root/gateway-dashboard/app.log"),
    ],
)
logger = logging.getLogger("app")

# ── Auth ────────────────────────────────────────────────────────────
def require_auth(f):
    """Simple Basic-Auth decorator for admin/bot routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ADMIN_PASSWORD:
            return jsonify({"error": "ADMIN_PASSWORD 未配置，API 不可用"}), 503
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.password or "", ADMIN_PASSWORD):
            return ("<h1>401 Unauthorized</h1><p>请提供管理员密码</p>", 401,
                    {"WWW-Authenticate": 'Basic realm="AI Bot Admin"'})
        return f(*args, **kwargs)
    return decorated

# ── Constitution ────────────────────────────────────────────────────
def load_constitution():
    if os.path.exists(CONSTITUTION_FILE):
        with open(CONSTITUTION_FILE, encoding="utf-8") as f:
            return f.read()
    return "# 宪法\n暂无内容"

def save_constitution(text):
    with open(CONSTITUTION_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    # Sync to SOUL.md — preserve any non-constitution content
    soul_content = ""
    marker = "\n\n# 📜 机器人宪法"
    if os.path.exists(SOUL_PATH):
        with open(SOUL_PATH, encoding="utf-8") as f:
            soul_content = f.read()
        idx = soul_content.find(marker)
        if idx >= 0:
            soul_content = soul_content[:idx].strip()
        # Only append constitution if the remaining content is non-empty
        tail = soul_content.strip()
        if tail:
            soul_content = tail + f"{marker}\n\n以下规则对所有人都适用，必须遵守：\n\n{text}"
        else:
            soul_content = f"{marker}\n\n以下规则对所有人都适用，必须遵守：\n\n{text}"
    else:
        soul_content = f"{marker}\n\n以下规则对所有人都适用，必须遵守：\n\n{text}"
    with open(SOUL_PATH, "w", encoding="utf-8") as f:
        f.write(soul_content)

# ── User Preferences ────────────────────────────────────────────────
def get_user_prefs(user_id):
    path = os.path.join(USER_PREFS_DIR, f"{user_id}.json")
    defaults = {"model": "deepseek-v4-flash", "name": user_id}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                defaults.update(json.load(f))
        except Exception as e:
            logger.error("Failed to load prefs for %s: %s", user_id, e)
    return defaults

def save_user_prefs(user_id, data):
    path = os.path.join(USER_PREFS_DIR, f"{user_id}.json")
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def get_user_token(user_id):
    prefs = get_user_prefs(user_id)
    if "token" not in prefs:
        prefs["token"] = uuid.uuid4().hex[:16]
        save_user_prefs(user_id, prefs)
        _rebuild_token_index()  # refresh index so resolve_token() works immediately
    return prefs["token"]

# ── Token → user_id reverse index ───────────────────────────────────
TOKEN_INDEX_FILE = os.path.join(USER_PREFS_DIR, "_token_index.json")

def _rebuild_token_index():
    """Scan all user prefs files and build token→user_id index."""
    index = {}
    if not os.path.isdir(USER_PREFS_DIR):
        return index
    for fn in os.listdir(USER_PREFS_DIR):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        user_id = fn.replace(".json", "")
        try:
            with open(os.path.join(USER_PREFS_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
            if "token" in data:
                index[data["token"]] = user_id
        except Exception as e:
            logger.error("Failed to index %s: %s", fn, e)
    # Atomically write to temp file then rename
    tmp_file = TOKEN_INDEX_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(index, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, TOKEN_INDEX_FILE)
    except Exception as e:
        logger.error("Failed to write token index: %s", e)
        try:
            os.remove(tmp_file)
        except OSError:
            pass
    return index

def resolve_token(token):
    """O(1) token resolution via reverse index."""
    try:
        if os.path.exists(TOKEN_INDEX_FILE):
            with open(TOKEN_INDEX_FILE, encoding="utf-8") as f:
                index = json.load(f)
            return index.get(token)
    except Exception as e:
        logger.error("Token index read failed, rebuilding: %s", e)
    # Fallback: rebuild on the fly
    index = _rebuild_token_index()
    return index.get(token)

# ── Gateway status ──────────────────────────────────────────────────
def get_gateway_status():
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    # Check actual Telegram gateway via systemd service status
    telegram_connected = False
    telegram_fields = [("平台", "Telegram Bot API"), ("状态", "未运行")]
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "hermes-gateway.service"],
            capture_output=True, text=True, timeout=5,
        )
        is_active = r.stdout.strip() == "active"
        if is_active:
            # Double-check: look for recent Telegram connection in the log
            log_check = subprocess.run(
                ["grep", "-q", "telegram connected", os.path.expanduser("~/.hermes/logs/gateway.log")],
                capture_output=True, timeout=3,
            )
            # Also check there's no recent disconnect after the last connect
            last_lines = subprocess.run(
                ["grep", "-E", "telegram (connected|Disconnected)", os.path.expanduser("~/.hermes/logs/gateway.log")],
                capture_output=True, text=True, timeout=3,
            )
            lines = [l for l in last_lines.stdout.strip().split("\n") if l]
            # If the last line is "connected", Telegram is actually up
            if lines and "connected" in lines[-1]:
                telegram_connected = True
                telegram_fields = [("平台", "Telegram Bot API"), ("状态", "活跃运行中")]
            else:
                telegram_fields = [("平台", "Telegram Bot API"), ("状态", "❌ 已断开")]
        else:
            telegram_fields = [("平台", "Telegram Bot API"), ("状态", "❌ 服务停止")]
    except Exception as e:
        logger.warning("Telegram gateway status check failed: %s", e)
        telegram_fields = [("平台", "Telegram Bot API"), ("状态", f"检查失败: {e}")]

    paired_users = []
    try:
        pairing_dir = os.path.expanduser("~/.hermes/pairing")
        if os.path.isdir(pairing_dir):
            for f in os.listdir(pairing_dir):
                if f.endswith("-approved.json"):
                    paired_users.append(f.replace("-approved.json", ""))
    except Exception as e:
        logger.warning("Failed to read paired users: %s", e)

    return [{
        "icon": "✈️", "name": "Telegram",
        "status": "connected" if telegram_connected else "offline",
        "fields": telegram_fields,
    }, {
        "icon": "💬", "name": "微信 (WeChat)",
        "status": "connected",
        "fields": [("平台", "iLink Bot"),
                   ("配对用户", f"{len(paired_users)} 人" if paired_users else "0 人"),
                   ("私信策略", "配对模式 (Pairing)")],
    }, {
        "icon": "🐧", "name": "QQ Bot",
        "status": "connected",
        "fields": [("平台", "QQ 机器人")],
    }, {
        "icon": "🔄", "name": "AI 引擎",
        "status": "connected",
        "fields": [("后端", "DeepSeek"),
                   ("宪法状态", "已生效" if os.path.exists(CONSTITUTION_FILE) else "未设置")],
    }], now

# ── Helpers ─────────────────────────────────────────────────────────
def format_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"

def allowed_file(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS

def _scan_all_users():
    """Scan all profile session DBs for unique user IDs across all gateways."""
    import sqlite3
    user_ids = set()
    hermes_home = os.path.expanduser("~/.hermes")
    # Scan default profile
    for db_path in [os.path.join(hermes_home, "state.db")]:
        try:
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                rows = conn.execute("SELECT DISTINCT user_id FROM sessions WHERE user_id IS NOT NULL AND user_id != ''").fetchall()
                conn.close()
                for (uid,) in rows:
                    user_ids.add(uid)
        except Exception:
            pass
    # Scan all named profiles
    profiles_dir = os.path.join(hermes_home, "profiles")
    if os.path.isdir(profiles_dir):
        for name in os.listdir(profiles_dir):
            db_path = os.path.join(profiles_dir, name, "state.db")
            if not os.path.exists(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                rows = conn.execute("SELECT DISTINCT user_id FROM sessions WHERE user_id IS NOT NULL AND user_id != ''").fetchall()
                conn.close()
                for (uid,) in rows:
                    user_ids.add(uid)
            except Exception:
                pass
    return sorted(user_ids)

def _is_safe_profile_name(name):
    if not name or len(name) > 64:
        return False
    return all(c.isalnum() or c in "_-" for c in name)

def _atomic_write(filepath, content):
    """Atomically write content to filepath using a secure same-dir temp file."""
    tmp = None
    try:
        dirpath = os.path.dirname(filepath) or "."
        prefix = os.path.basename(filepath) + "."
        fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=dirpath, text=True)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, filepath)
    except Exception:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise

def _sanitize_env_value(val):
    """Reject env values containing newlines or control characters (except space)."""
    if not isinstance(val, str):
        val = str(val)
    for ch in val:
        if ch == "\n" or ch == "\r" or (ord(ch) < 0x20 and ch != " "):
            raise ValueError("env value contains invalid character (0x{:02x})".format(ord(ch)))
    return val

def _get_admin_ids():
    """Return set of admin user IDs from env config."""
    ids = set()
    raw = ADMIN_IDS.strip()
    if raw:
        for uid in raw.split(","):
            uid = uid.strip()
            if uid:
                ids.add(uid)
    return ids

def normalize_model_id(model_id):
    valid_ids = {m["id"] for m in AVAILABLE_MODELS}
    return model_id if model_id in valid_ids else DEFAULT_MODEL_ID

def list_uploaded_files():
    """List files and directories in the upload dir, sorted by mtime desc."""
    items = []
    if not os.path.isdir(UPLOAD_DIR):
        return items
    for fn in sorted(os.listdir(UPLOAD_DIR),
                     key=lambda x: os.path.getmtime(os.path.join(UPLOAD_DIR, x)),
                     reverse=True):
        fp = os.path.join(UPLOAD_DIR, fn)
        if os.path.isdir(fp):
            # Count files inside directory (recursive)
            fcount = 0
            total_size = 0
            for root, dirs, files in os.walk(fp):
                fcount += len(files)
                for f in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            items.append({
                "name": fn,
                "size": total_size,
                "size_human": format_size(total_size),
                "is_dir": True,
                "file_count": fcount,
            })
        elif os.path.isfile(fp):
            sz = os.path.getsize(fp)
            mime, _ = mimetypes.guess_type(fn)
            items.append({
                "name": fn,
                "size": sz,
                "size_human": format_size(sz),
                "is_dir": False,
                "file_count": None,
                "type": mime or "",
            })
    return items


# ── MinerU OCR Helpers ──────────────────────────────────────────────
def get_mineru_jwt():
    """Get JWT token for MinerU API via OpenXLab credentials."""
    ak = os.environ.get("OPENXLAB_AK")
    sk = os.environ.get("OPENXLAB_SK")
    if not ak or not sk:
        logger.error("OPENXLAB_AK and OPENXLAB_SK must be set in environment")
        return None
    try:
        from openxlab import login as ox_login
        from openxlab.xlab.handler import user_token
        ox_login(ak, sk)
        return user_token.get_jwt()
    except Exception as e:
        logger.error("MinerU JWT generation failed: %s", e)
        return None


def submit_mineru_task(file_url, file_name):
    """Submit a PDF/Image to MinerU v4 API for OCR extraction."""
    jwt = get_mineru_jwt()
    if not jwt:
        return None, "无法获取 MinerU 认证"
    try:
        resp = requests.post(
            "https://mineru.net/api/v4/extract/task",
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json"
            },
            json={"url": file_url, "file_name": file_name},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["task_id"], None
        return None, data.get("msg", "提交失败")
    except Exception as e:
        logger.error("MinerU submit failed: %s", e)
        return None, f"提交异常: {e}"


def poll_mineru_task(task_id):
    """Poll MinerU task status. Returns (state, result_dict, error)."""
    jwt = get_mineru_jwt()
    if not jwt:
        return "error", None, "认证失败"
    try:
        resp = requests.get(
            f"https://mineru.net/api/v4/extract/task/{task_id}",
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=15,
        )
        data = resp.json()
        if data.get("code") != 0:
            return "error", None, data.get("msg", "查询失败")
        d = data["data"]
        state = d.get("state", "unknown")
        if state == "failed":
            return "error", None, d.get("err_msg", "MinerU 处理失败")
        if state == "done":
            # Fetch the markdown content
            md_url = d.get("full_md_link", "")
            md_content = ""
            if md_url:
                try:
                    md_resp = requests.get(md_url, timeout=15)
                    raw = md_resp.content  # raw bytes
                    # MinerU's markdown may be double-encoded: raw UTF-8 bytes
                    # interpreted as Latin-1. Fix by re-encoding.
                    try:
                        md_content = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            md_content = raw.decode("latin-1").encode("latin-1").decode("utf-8")
                        except Exception:
                            md_content = raw.decode("utf-8", errors="replace")
                except Exception as e:
                    logger.warning("Failed to fetch markdown: %s", e)
            result = {
                "task_id": task_id,
                "state": "done",
                "markdown": md_content,
                "full_md_link": md_url,
                "full_zip_url": d.get("full_zip_url", ""),
                "pages": d.get("file_info", {}).get("pages", 0),
                "file_name": d.get("file_name", ""),
                "file_size": d.get("file_info", {}).get("file_size", 0),
            }
            return "done", result, None
        return state, None, None
    except Exception as e:
        logger.error("MinerU poll failed: %s", e)
        return "error", None, f"查询异常: {e}"

# ═══════════════════════════════════════════════════════════════════
# HTML TEMPLATES
# ═══════════════════════════════════════════════════════════════════

LANDING_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Bot 平台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.hero{text-align:center;padding:60px 20px 40px;background:linear-gradient(180deg,#161b22 0%,#0d1117 100%)}
.hero h1{font-size:36px;color:#f0f6fc;margin-bottom:12px}
.hero p{color:#8b949e;font-size:16px;max-width:600px;margin:0 auto;line-height:1.6}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;max-width:1000px;margin:40px auto;padding:0 20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:30px;text-align:center;transition:border-color .2s}
.card:hover{border-color:#58a6ff}
.card .icon{font-size:40px;margin-bottom:12px}
.card h3{font-size:18px;color:#f0f6fc;margin-bottom:8px}
.card p{color:#8b949e;font-size:13px;line-height:1.5}
.qr-section{text-align:center;padding:40px 20px;max-width:400px;margin:0 auto}
.qr-section h2{font-size:20px;margin-bottom:8px;color:#f0f6fc}
.qr-section p{color:#8b949e;font-size:13px;margin-bottom:20px}
.qr-box{background:#fff;border-radius:16px;padding:20px;display:inline-block}
.qr-box img{width:260px;height:260px;display:block}
.qr-hint{color:#484f58;font-size:12px;margin-top:12px}
</style>
</head>
<body>
<div class="nav-bar" style="position:fixed;top:0;left:0;right:0;background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;justify-content:center;gap:20px;font-size:13px;z-index:10">
<a href="/" style="color:#8b949e;text-decoration:none">🏠 首页</a>
<a href="/gateway" style="color:#8b949e;text-decoration:none">📊 状态面板</a>

<a href="/upload" style="color:#8b949e;text-decoration:none">📁 文件上传</a>
<a href="/ocr" style="color:#58a6ff;text-decoration:none">📄 OCR 识别</a>
<a href="/pairing" style="color:#3fb950;text-decoration:none">📱 配对</a>
<a href="/admin" style="color:#8b949e;text-decoration:none">⚙️ 管理</a>
</div>
<div class="hero" style="margin-top:50px">
<h1>🤖 AI Bot 平台</h1>
<p>扫码添加专属 AI 助手，随时随地在微信上与我交流。<br>每个人的会话和数据都是独立隔离，互不干扰。</p>
</div>
<div class="features">
<div class="card"><div class="icon">💬</div><h3>微信对话</h3><p>扫描下方二维码，在微信中与 AI 助手实时对话</p></div>
<div class="card"><div class="icon">🔒</div><h3>数据隔离</h3><p>每位用户拥有独立的会话空间，隐私安全</p></div>
<div class="card"><div class="icon">📋</div><h3>合规管理</h3><p>管理员统一配置对话规则和行为规范</p></div>
</div>
<div class="qr-section">
<h2>📱 扫码添加 AI 助手</h2>
<p>打开微信扫描下方二维码添加好友，即可开始对话</p>
<div class="qr-box">
<img src="{{ qr_image_url }}" alt="微信二维码">
</div>
<p class="qr-hint">也可在微信搜索账号添加</p>
</div>
</body>
</html>"""

GATEWAY_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>状态面板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.nav-bar{background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;justify-content:center;gap:20px;font-size:13px}
.nav-bar a{color:#8b949e;text-decoration:none}
.nav-bar a:hover{color:#58a6ff}
.container{max-width:800px;margin:0 auto;padding:40px 20px}
h1{font-size:24px;margin-bottom:8px;color:#f0f6fc}
.subtitle{color:#8b949e;margin-bottom:32px;font-size:14px}
.grid{display:grid;gap:16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;transition:border-color .2s}
.card:hover{border-color:#58a6ff}
.card-header{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.card-header h2{font-size:16px;color:#f0f6fc;flex:1}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}
.badge-on{background:#1b4924;color:#3fb950}
.badge-off{background:#49241b;color:#f85149}
.card-body{font-size:13px;color:#8b949e;line-height:1.8}
.card-body .label{color:#c9d1d9;display:inline-block;min-width:80px}
.card-body .mono{font-family:"SF Mono","Cascadia Code",monospace;font-size:12px;color:#58a6ff}
.updated{text-align:center;color:#484f58;font-size:12px;margin-top:32px}
</style>
</head>
<body>
<div class="nav-bar">
<a href="/">🏠 首页</a>

<a href="/upload">📁 文件上传</a>
<a href="/ocr">📄 OCR</a>
<a href="/admin">⚙️ 管理</a>
<a href="/admin/evolution">🧠 进化日志</a>
</div>
<div class="container">
<h1>🔌 网关状态面板</h1>
<p class="subtitle">AI Bot 平台 · 多平台消息通道状态</p>
<div class="grid">
{% for g in gateways %}
<div class="card">
<div class="card-header">
<span>{{ g.icon }}</span>
<h2>{{ g.name }}</h2>
<span class="badge badge-{{ 'on' if g.status == 'connected' else 'off' }}">
{{ '● 已连接' if g.status == 'connected' else '○ 离线' }}
</span>
</div>
<div class="card-body">
{% for k, v in g.fields %}
<div><span class="label">{{ k }}</span>{{ v }}</div>
{% endfor %}
</div>
</div>
{% endfor %}
</div>
<div class="updated">最后更新：{{ updated }}</div>
</div>
</body>
</html>"""

ADMIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>管理面板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.nav-bar{background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;justify-content:center;gap:20px;font-size:13px}
.nav-bar a{color:#8b949e;text-decoration:none}
.nav-bar a:hover{color:#58a6ff}
.container{max-width:900px;margin:0 auto;padding:40px 20px}
h1{font-size:24px;color:#f0f6fc;margin-bottom:8px}
.sub{color:#8b949e;font-size:14px;margin-bottom:32px}
.tabs{display:flex;gap:0;margin-bottom:30px;border-bottom:1px solid #30363d}
.tab{padding:10px 24px;cursor:pointer;font-size:14px;color:#8b949e;border-bottom:2px solid transparent;background:none;border-top:none;border-left:none;border-right:none}
.tab.active{color:#f0f6fc;border-bottom-color:#58a6ff}
.tab:hover{color:#c9d1d9}
.panel{display:none}
.panel.active{display:block}
label{display:block;font-size:13px;color:#8b949e;margin-bottom:6px}
textarea{width:100%;min-height:400px;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:14px;color:#c9d1d9;font-size:13px;font-family:"SF Mono","Cascadia Code",monospace;line-height:1.5;resize:vertical;outline:none}
textarea:focus{border-color:#58a6ff}
.submit-row{display:flex;gap:12px;margin-top:16px;align-items:center}
.btn{background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 24px;font-size:14px;font-weight:600;cursor:pointer}
.btn:hover{background:#2ea043}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-secondary{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:10px 24px;font-size:14px;cursor:pointer;text-decoration:none;display:inline-block}
.btn-secondary:hover{background:#30363d}
.success{background:#1b4924;color:#3fb950;border:1px solid #238636;border-radius:8px;padding:10px 16px;font-size:13px;margin-bottom:16px}
.error{background:#49241b;color:#f85149;border:1px solid #da3633;border-radius:8px;padding:10px 16px;font-size:13px;margin-bottom:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:30px}
.stat-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;text-align:center}
.stat-card .num{font-size:28px;color:#58a6ff;font-weight:700}
.stat-card .label{font-size:12px;color:#8b949e;margin-top:4px}
.token-section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:20px}
.token-row{display:flex;justify-content:space-between;padding:8px 0;font-size:13px;border-bottom:1px solid #0d1117}
.token-row:last-child{border-bottom:none}
.token-row .lbl{color:#8b949e}
.token-row .val{color:#58a6ff;font-weight:600}
.token-bar{height:8px;background:#0d1117;border-radius:4px;margin:8px 0;overflow:hidden}
.token-bar-inner{height:100%;border-radius:4px;transition:width 1s}
.token-model{margin-bottom:16px}
</style>
</head>
<body>
<div class="nav-bar">
<a href="/">🏠 首页</a>
<a href="/gateway">📊 状态面板</a>

<a href="/upload">📁 文件上传</a>
<a href="/ocr">📄 OCR</a>
<a href="/admin/evolution">🧠 进化日志</a>
</div>
<div class="container">
<h1>⚙️ 管理面板</h1>
<p class="sub">配置机器人宪法、管理用户和数据 <span style="color:#484f58;font-size:12px">(Basic Auth 保护)</span></p>

<div class="stats">
<div class="stat-card"><div class="num">{{ stats.users }}</div><div class="label">已配对用户</div></div>
<div class="stat-card"><div class="num">{{ stats.tokens }}</div><div class="label">今日 Token 消耗</div></div>
<div class="stat-card"><div class="num">{{ stats.codex_tokens }}</div><div class="label">Codex 累计</div></div>
<div class="stat-card"><div class="num">{{ stats.uptime }}</div><div class="label">运行时长</div></div>
</div>

<div class="tabs">
<button class="tab active" onclick="switchTab('constitution')">📜 宪法</button>
<button class="tab" onclick="switchTab('users')">👥 用户</button>
<button class="tab" onclick="switchTab('tokens')">📊 Token</button>
</div>

<div id="panel-constitution" class="panel active">
{% if msg %}<div class="success">{{ msg }}</div>{% endif %}
{% if err %}<div class="error">{{ err }}</div>{% endif %}
<form method="post" action="/admin/save">
<label>机器人宪法（Markdown 格式，所有机器人统一遵守）</label>
<textarea name="content">{{ constitution }}</textarea>
<div class="submit-row">
<button type="submit" class="btn">💾 保存并生效</button>
<a href="/gateway" class="btn-secondary">📊 查看状态</a>
</div>
</form>
</div>

<div id="panel-users" class="panel">
{% if paired_users %}
{% for uid in paired_users %}
<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;gap:12px">
<span>👤</span>
<span style="flex:1;font-size:13px;font-family:monospace;color:#58a6ff">{{ uid }}</span>
{% set token = user_tokens[uid] %}
<a href="/my/{{ token }}" target="_blank" class="btn-secondary" style="padding:4px 12px;font-size:12px">🔗 个人面板</a>
</div>
{% endfor %}
{% else %}
<div style="text-align:center;color:#484f58;padding:40px;font-size:14px">暂无已配对的微信用户</div>
{% endif %}
</div>

<div id="panel-tokens" class="panel">
<h2 style="font-size:16px;color:#f0f6fc;margin-bottom:16px">📊 Token 用量</h2>
<div id="token-content">
<div style="text-align:center;color:#484f58;padding:40px;font-size:14px">加载中...</div>
</div>
</div>
</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.querySelector(`.tab[onclick*="'${name}'"]`).classList.add('active');
  if (name === 'tokens') fetchTokens();
}

function fetchTokens() {
  var el = document.getElementById('token-content');
  if (!el) return;
  
  Promise.all([
    fetch('/api/tokens?_=' + Date.now()).then(function(r) { return r.json(); }),
    fetch('/api/codex-tokens?_=' + Date.now()).then(function(r) { return r.json(); })
  ])
    .then(function(results) {
      var d = results[0];
      var c = results[1];
      var html = '';
      // — Today section (AI Models) —
      html += '<div style="font-size:13px;color:#f0f6fc;font-weight:600;margin:8px 0 4px">今日 · AI 模型</div>';
      html += '<div class="token-section">' +
        '<div class="token-row"><span class="lbl">Token 消耗</span><span class="val">' + fmtNum(d.total_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">Prompt</span><span class="val">' + fmtNum(d.prompt_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">Completion</span><span class="val">' + fmtNum(d.completion_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">API 调用</span><span class="val">' + d.call_count + '</span></div>' +
        '</div>';
      // Today per-model
      var models = d.models || {};
      var modelKeys = Object.keys(models);
      if (modelKeys.length > 0) {
        var maxTotal = 0;
        modelKeys.forEach(function(m) { maxTotal = Math.max(maxTotal, models[m].prompt + models[m].completion); });
        html += '<div class="token-section"><div style="font-size:13px;color:#f0f6fc;margin-bottom:12px">今日各模型</div>';
        modelKeys.forEach(function(m) {
          var info = models[m];
          var total = info.prompt + info.completion;
          var pct = maxTotal > 0 ? (total / maxTotal * 100).toFixed(0) : 0;
          var barColor = '#58a6ff';
          if (m.indexOf('pro') >= 0) barColor = '#d2a8ff';
          else if (m.indexOf('flash') >= 0) barColor = '#58a6ff';
          html += '<div class="token-model">' +
            '<div class="token-row"><span class="lbl" style="font-family:monospace;font-size:12px">' + m + '</span><span class="val">' + fmtNum(total) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">Prompt</span><span class="val" style="font-size:12px">' + fmtNum(info.prompt) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">Completion</span><span class="val" style="font-size:12px">' + fmtNum(info.completion) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">调用次数</span><span class="val" style="font-size:12px">' + info.calls + '</span></div>' +
            '<div class="token-bar"><div class="token-bar-inner" style="width:' + pct + '%;background:' + barColor + '"></div></div>' +
            '</div>';
        });
        html += '</div>';
      }
      // — All-time section —
      html += '<div style="font-size:13px;color:#f0f6fc;font-weight:600;margin:16px 0 4px">历史总计</div>';
      html += '<div class="token-section">' +
        '<div class="token-row"><span class="lbl">Token 消耗</span><span class="val">' + fmtNum(d.all_total_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">Prompt</span><span class="val">' + fmtNum(d.all_prompt_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">Completion</span><span class="val">' + fmtNum(d.all_completion_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">API 调用</span><span class="val">' + d.all_call_count + '</span></div>' +
        '</div>';
      // All-time per-model
      var allModels = d.all_models || {};
      var allModelKeys = Object.keys(allModels);
      if (allModelKeys.length > 0) {
        var maxAll = 0;
        allModelKeys.forEach(function(m) { maxAll = Math.max(maxAll, allModels[m].prompt + allModels[m].completion); });
        html += '<div class="token-section"><div style="font-size:13px;color:#f0f6fc;margin-bottom:12px">总计各模型</div>';
        allModelKeys.forEach(function(m) {
          var info = allModels[m];
          var total = info.prompt + info.completion;
          var pct = maxAll > 0 ? (total / maxAll * 100).toFixed(0) : 0;
          var barColor = '#58a6ff';
          if (m.indexOf('pro') >= 0) barColor = '#d2a8ff';
          else if (m.indexOf('flash') >= 0) barColor = '#58a6ff';
          html += '<div class="token-model">' +
            '<div class="token-row"><span class="lbl" style="font-family:monospace;font-size:12px">' + m + '</span><span class="val">' + fmtNum(total) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">Prompt</span><span class="val" style="font-size:12px">' + fmtNum(info.prompt) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">Completion</span><span class="val" style="font-size:12px">' + fmtNum(info.completion) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">调用次数</span><span class="val" style="font-size:12px">' + info.calls + '</span></div>' +
            '<div class="token-bar"><div class="token-bar-inner" style="width:' + pct + '%;background:' + barColor + '"></div></div>' +
            '</div>';
        });
        html += '</div>';
      }
      // — Codex section —
      html += '<div style="font-size:13px;color:#f0f6fc;font-weight:600;margin:16px 0 4px">🤖 Codex CLI</div>';
      html += '<div class="token-section">' +
        '<div class="token-row"><span class="lbl">今日 Token</span><span class="val">' + fmtNum(c.today_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">今日调用</span><span class="val">' + c.today_calls + '</span></div>' +
        '<div class="token-row"><span class="lbl">历史累计</span><span class="val">' + fmtNum(c.total_tokens) + '</span></div>' +
        '<div class="token-row"><span class="lbl">总调用次数</span><span class="val">' + c.total_calls + '</span></div>' +
        '</div>';
      // Codex per-model
      var cModels = c.today_models || {};
      var cModelKeys = Object.keys(cModels);
      if (cModelKeys.length > 0) {
        html += '<div class="token-section"><div style="font-size:13px;color:#f0f6fc;margin-bottom:12px">今日各模型</div>';
        cModelKeys.forEach(function(m) {
          var info = cModels[m];
          html += '<div class="token-model">' +
            '<div class="token-row"><span class="lbl" style="font-family:monospace;font-size:12px">' + m + '</span><span class="val">' + fmtNum(info.tokens) + '</span></div>' +
            '<div class="token-row" style="font-size:12px;padding:2px 0"><span class="lbl">调用次数</span><span class="val" style="font-size:12px">' + info.calls + '</span></div>' +
            '</div>';
        });
        html += '</div>';
      }
      el.innerHTML = html;
    })
    .catch(function() {
      el.innerHTML = '<div style="text-align:center;color:#f85149;padding:20px;font-size:13px">加载失败</div>';
    });
}

function fmtNum(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

setInterval(fetchTokens, 10000);
</script>
</body>
</html>"""

UPLOAD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>文件上传</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.nav-bar{position:fixed;top:0;left:0;right:0;background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;justify-content:center;gap:20px;font-size:13px;z-index:10}
.nav-bar a{color:#8b949e;text-decoration:none}
.nav-bar a:hover{color:#58a6ff}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:40px;width:100%;max-width:560px;margin:20px;margin-top:80px}
h1{font-size:22px;margin-bottom:8px;color:#f0f6fc;text-align:center}
.sub{color:#8b949e;font-size:13px;margin-bottom:24px;text-align:center}
.mode-tabs{display:flex;gap:0;margin-bottom:20px;border-bottom:1px solid #30363d}
.mode-tab{padding:8px 20px;cursor:pointer;font-size:13px;color:#8b949e;border-bottom:2px solid transparent;background:none;border-top:none;border-left:none;border-right:none}
.mode-tab.active{color:#f0f6fc;border-bottom-color:#58a6ff}
.mode-tab:hover{color:#c9d1d9}
.mode-panel{display:none}
.mode-panel.active{display:block}
.upload-area{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:12px}
.upload-area input[type=file]{width:100%}
input[type=file]::file-selector-button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:13px}
input[type=file]::file-selector-button:hover{background:#30363d}
.folder-hint{font-size:12px;color:#484f58;text-align:center;margin-top:-8px;margin-bottom:12px}
.btn{background:#238636;color:#fff;border:none;border-radius:8px;padding:12px;font-size:15px;font-weight:600;cursor:pointer;width:100%}
.btn:hover{background:#2ea043}
.btn:disabled{opacity:.5;cursor:not-allowed}
.msg{background:#1b4924;color:#3fb950;border:1px solid #238636;border-radius:8px;padding:12px;text-align:center;font-size:14px;margin-bottom:16px}
.err{background:#49241b;color:#f85149;border:1px solid #da3633;border-radius:8px;padding:12px;text-align:center;font-size:14px;margin-bottom:16px}
#progress-wrap{margin-top:12px;display:none}
#progress-label{font-size:13px;color:#8b949e;margin-bottom:6px}
#progress-bar{width:100%;height:20px;background:#0d1117;border-radius:10px;overflow:hidden;border:1px solid #30363d}
#progress-fill{height:100%;width:0%;background:linear-gradient(90deg,#238636,#2ea043);border-radius:10px;transition:width .3s}
#progress-pct{font-size:12px;color:#8b949e;text-align:right;margin-top:4px}
.files{margin-top:20px;border-top:1px solid #30363d;padding-top:12px}
.files .file-row{display:flex;align-items:center;gap:8px;padding:6px 0}
.files a{color:#58a6ff;text-decoration:none;font-size:13px;flex:1}
.files a:hover{text-decoration:underline}
.files .size{color:#484f58;font-size:11px}
.files .del-btn{color:#f85149;font-size:12px;cursor:pointer;background:none;border:none;padding:2px 6px;border-radius:4px}
.files .del-btn:hover{background:#49241b}
#result-box{display:none;margin-top:12px;padding:10px;border-radius:8px;font-size:13px}
.folder-batch{font-size:12px;color:#8b949e;margin-bottom:8px}
.folder-batch span{color:#58a6ff;font-weight:600}
</style>
</head>
<body>
<div class="nav-bar">
<a href="/">🏠 首页</a>
<a href="/gateway">📊 状态面板</a>

<a href="/ocr">📄 OCR</a>
<a href="/admin">⚙️ 管理</a>
</div>
<div class="card">
<h1>📁 文件上传</h1>
<p class="sub" id="subtitle">支持单个文件、整个文件夹、多文件夹批量上传、压缩包 (最大 2GB)</p>
{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
{% if err %}<div class="err">{{ err }}</div>{% endif %}

<div class="mode-tabs" id="modeTabs">
<button class="mode-tab active" data-mode="file">📄 单个文件</button>
<button class="mode-tab" data-mode="folder">📁 单文件夹</button>
<button class="mode-tab" data-mode="multifolder">📂 多文件夹</button>
<button class="mode-tab" data-mode="archive">📦 压缩包</button>
</div>

<div id="panel-file" class="mode-panel active">
<div class="upload-area">
<input type="file" id="fileInput" required>
</div>
<button class="btn" id="fileBtn" onclick="uploadFile('file')">上传</button>
</div>

<div id="panel-folder" class="mode-panel">
<div class="upload-area">
<input type="file" id="folderInput" webkitdirectory multiple>
</div>
<p class="folder-hint">选择整个文件夹，文件将按原目录结构保存</p>
<button class="btn" id="folderBtn" onclick="uploadFolder()">上传文件夹</button>
<div id="folderStatus" class="folder-batch" style="display:none"></div>
</div>

<div id="panel-multifolder" class="mode-panel">
<div class="upload-area">
<input type="file" id="multiFolderInput" webkitdirectory style="display:none">
<button class="btn" id="addFolderBtn" style="background:#1f6feb;margin-bottom:8px" onclick="addFolder()">➕ 添加文件夹</button>
</div>
<div id="multiFolderList" class="folder-batch" style="display:none"></div>
<p class="folder-hint">多次点击「添加文件夹」选择不同文件夹，全部添加后点击上传</p>
<button class="btn" id="multiFolderBtn" onclick="uploadMultiFolder()">📂 批量上传全部文件夹</button>
</div>

<div id="panel-archive" class="mode-panel">
<div class="upload-area">
<input type="file" id="archiveInput" accept=".zip,.tar,.gz,.tar.gz,.tgz">
</div>
<p class="folder-hint">压缩包上传后将自动解压到独立目录</p>
<button class="btn" id="archiveBtn" onclick="uploadFile('archive')">上传并解压</button>
</div>

<div id="progress-wrap">
<div id="progress-label">准备上传...</div>
<div id="progress-bar"><div id="progress-fill"></div></div>
<div id="progress-pct">0%</div>
</div>

<div id="result-box"></div>

{% if files %}
<div class="files" id="fileList">
{% for f in files %}
<div class="file-row">
{% if f.is_dir %}
<span style="color:#8b949e;font-size:13px">📁 {{ f.name }}/</span>
<span class="size">{{ f.file_count }} 个文件 · {{ f.size_human }}</span>
<button class="del-btn" data-name="{{ f.name }}" onclick="deleteFile(this.dataset.name)">✕</button>
{% else %}
<a href="/f/{{ f.name }}" download>{{ f.name }}</a>
<span class="size">{{ f.size_human }}</span>
<button class="del-btn" data-name="{{ f.name }}" onclick="deleteFile(this.dataset.name)">✕</button>
{% endif %}
</div>
{% endfor %}
</div>
{% endif %}
</div>

<script>
// ── Tab switching ──
document.querySelectorAll('.mode-tab').forEach(function(tab) {
  tab.addEventListener('click', function() {
    document.querySelectorAll('.mode-tab').forEach(function(t) { t.classList.remove('active'); });
    document.querySelectorAll('.mode-panel').forEach(function(p) { p.classList.remove('active'); });
    this.classList.add('active');
    document.getElementById('panel-' + this.dataset.mode).classList.add('active');
    hideProgress();
  });
});

// ── Progress helpers ──
function showProgress(label) {
  var w = document.getElementById('progress-wrap');
  document.getElementById('progress-label').textContent = label;
  document.getElementById('progress-fill').style.width = '0%';
  document.getElementById('progress-pct').textContent = '0%';
  w.style.display = 'block';
}
function updateProgress(pct, label) {
  document.getElementById('progress-fill').style.width = Math.min(pct, 100) + '%';
  document.getElementById('progress-pct').textContent = Math.round(pct) + '%';
  if (label) document.getElementById('progress-label').textContent = label;
}
function hideProgress() {
  document.getElementById('progress-wrap').style.display = 'none';
}
function showResult(ok, text) {
  var box = document.getElementById('result-box');
  box.style.display = 'block';
  box.className = ok ? 'msg' : 'err';
  box.textContent = text;
  setTimeout(function() { box.style.display = 'none'; }, 8000);
}
function disableBtns(v) {
  document.getElementById('fileBtn').disabled = v;
  document.getElementById('folderBtn').disabled = v;
  document.getElementById('archiveBtn').disabled = v;
  document.getElementById('multiFolderBtn').disabled = v;
  document.getElementById('addFolderBtn').disabled = v;
}

// ── Single file / archive upload ──
function uploadFile(mode) {
  var inputId = mode === 'archive' ? 'archiveInput' : 'fileInput';
  var input = document.getElementById(inputId);
  var file = input.files && input.files[0];
  if (!file) { showResult(false, '请先选择文件'); return; }

  disableBtns(true);
  showProgress('正在上传 ' + file.name + '...');

  var fd = new FormData();
  fd.append('file', file);

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload/api', true);

  xhr.upload.onprogress = function(e) {
    if (e.lengthComputable) {
      var pct = (e.loaded / e.total) * 100;
      var size = (e.loaded / 1048576).toFixed(1);
      var total = (e.total / 1048576).toFixed(1);
      updateProgress(pct, '上传中 ' + file.name + ' (' + size + '/' + total + ' MB)');
    }
  };

  xhr.onload = function() {
    disableBtns(false);
    hideProgress();
    if (xhr.status === 200) {
      var d = JSON.parse(xhr.responseText);
      var text = '✅ ' + d.original + ' 上传成功 (' + d.size_human + ')';
      if (d.extracted) text += '，已解压到 ' + d.extracted.dir + ' (' + d.extracted.files + ' 个文件)';
      showResult(true, text);
      input.value = '';
      reloadFileList();
    } else {
      try {
        var d = JSON.parse(xhr.responseText);
        showResult(false, '❌ ' + (d.error || '上传失败'));
      } catch(e) {
        showResult(false, '❌ 上传失败 (' + xhr.status + ')');
      }
    }
  };

  xhr.onerror = function() {
    disableBtns(false);
    hideProgress();
    showResult(false, '❌ 网络错误，上传中断');
  };

  xhr.send(fd);
}

// ── Folder upload (sequential) ──
function uploadFolder() {
  var input = document.getElementById('folderInput');
  var files = input.files;
  if (!files || files.length === 0) { showResult(false, '请选择文件夹'); return; }

  var total = files.length;
  var idx = 0;
  var ok = 0, fail = 0;

  disableBtns(true);
  document.getElementById('folderStatus').style.display = 'block';
  showProgress('准备上传 ' + total + ' 个文件...');

  function uploadNext() {
    if (idx >= total) {
      disableBtns(false);
      hideProgress();
      document.getElementById('folderStatus').style.display = 'none';
      showResult(true, '✅ 文件夹上传完成：成功 ' + ok + ' 个' + (fail ? '，失败 ' + fail + ' 个' : ''));
      input.value = '';
      reloadFileList();
      return;
    }

    var file = files[idx];
    var relPath = file.webkitRelativePath || file.name;
    document.getElementById('folderStatus').innerHTML =
      '📁 文件 <span>' + (idx+1) + '/' + total + '</span>：' + relPath;

    var fd = new FormData();
    fd.append('file', file);
    // Add folder mode marker
    fd.append('path', relPath);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload/api', true);

    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable) {
        var pct = (e.loaded / e.total) * 100;
        var overall = ((idx + pct/100) / total) * 100;
        updateProgress(overall, '文件 ' + (idx+1) + '/' + total + '：' + relPath + ' (' + (e.loaded/1048576).toFixed(1) + ' MB)');
      }
    };

    xhr.onload = function() {
      if (xhr.status === 200) {
        ok++;
      } else {
        fail++;
      }
      idx++;
      uploadNext();
    };

    xhr.onerror = function() {
      fail++;
      idx++;
      uploadNext();
    };

    xhr.send(fd);
  }

  uploadNext();
}

// ── Multi-folder upload (accumulate then batch) ──
var _mfFolders = [];  // Array of {name: string, files: FileList}

function addFolder() {
  var input = document.getElementById('multiFolderInput');
  input.value = '';
  input.click();
}

document.getElementById('multiFolderInput').addEventListener('change', function() {
  var files = this.files;
  if (!files || files.length === 0) return;
  // Extract folder name from first file's webkitRelativePath
  var firstPath = files[0].webkitRelativePath || files[0].name;
  var folderName = firstPath.split('/')[0];
  _mfFolders.push({name: folderName, files: files});
  renderMultiFolderList();
  this.value = '';
});

function renderMultiFolderList() {
  var el = document.getElementById('multiFolderList');
  if (_mfFolders.length === 0) {
    el.style.display = 'none';
    return;
  }
  var totalFiles = 0;
  var html = '';
  _mfFolders.forEach(function(f, i) {
    var count = f.files.length;
    totalFiles += count;
    html += '<div style="display:flex;align-items:center;gap:8px;padding:4px 0">' +
      '📂 <strong>' + f.name + '</strong>' +
      '<span style="color:#484f58;font-size:12px">' + count + ' 个文件</span>' +
      '<button onclick="removeFolder(' + i + ')" style="background:none;border:none;color:#f85149;cursor:pointer;font-size:12px">✕</button>' +
      '</div>';
  });
  html += '<div style="border-top:1px solid #30363d;margin-top:4px;padding-top:4px;color:#8b949e;font-size:12px">共 <span style="color:#58a6ff">' + _mfFolders.length + '</span> 个文件夹，<span style="color:#58a6ff">' + totalFiles + '</span> 个文件</div>';
  el.innerHTML = html;
  el.style.display = 'block';
}

function removeFolder(idx) {
  _mfFolders.splice(idx, 1);
  renderMultiFolderList();
}

function uploadMultiFolder() {
  if (_mfFolders.length === 0) { showResult(false, '请先添加文件夹'); return; }

  // Flatten all files into a list with their folder path
  var allFiles = [];
  _mfFolders.forEach(function(folder) {
    for (var i = 0; i < folder.files.length; i++) {
      allFiles.push({
        file: folder.files[i],
        path: folder.files[i].webkitRelativePath || folder.files[i].name,
      });
    }
  });

  var total = allFiles.length;
  var idx = 0;
  var ok = 0, fail = 0;

  disableBtns(true);
  showProgress('准备上传 ' + total + ' 个文件...');

  function uploadNext() {
    if (idx >= total) {
      disableBtns(false);
      hideProgress();
      showResult(true, '✅ 多文件夹上传完成：成功 ' + ok + ' 个' + (fail ? '，失败 ' + fail + ' 个' : ''));
      _mfFolders = [];
      renderMultiFolderList();
      reloadFileList();
      return;
    }

    var item = allFiles[idx];
    var relPath = item.path;

    var fd = new FormData();
    fd.append('file', item.file);
    fd.append('path', relPath);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload/api', true);

    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable) {
        var pct = (e.loaded / e.total) * 100;
        var overall = ((idx + pct/100) / total) * 100;
        updateProgress(overall, '文件 ' + (idx+1) + '/' + total + '：' + relPath + ' (' + (e.loaded/1048576).toFixed(1) + ' MB)');
      }
    };

    xhr.onload = function() {
      if (xhr.status === 200) ok++; else fail++;
      idx++;
      uploadNext();
    };

    xhr.onerror = function() {
      fail++;
      idx++;
      uploadNext();
    };

    xhr.send(fd);
  }

  uploadNext();
}

// ── Delete file / directory ──
async function deleteFile(name) {
  if (!confirm('确定删除 ' + name + ' 吗？')) return;
  try {
    var r = await fetch('/upload/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filename: name}),
    });
    if (r.ok) location.reload();
    else alert('删除失败');
  } catch(e) { alert('删除失败: ' + e.message); }
}

// ── Reload file list ──
async function reloadFileList() {
  try {
    var r = await fetch('/upload/reload', {method:'POST'});
    if (r.ok) location.reload();
  } catch(e) {}
}

// ── Initial show ──
var activeTab = document.querySelector('.mode-tab.active');
if (activeTab) {
  document.getElementById('panel-' + activeTab.dataset.mode).classList.add('active');
}
</script>
</body>
</html>"""

MY_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>我的 AI Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 20px;display:flex;align-items:center;gap:10px}
.header h1{font-size:18px;color:#f0f6fc;flex:1}
.container{max-width:600px;margin:0 auto;padding:40px 20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:30px;margin-bottom:20px}
.card h2{font-size:16px;color:#f0f6fc;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:13px;color:#8b949e;margin-bottom:6px}
.form-group select{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 12px;color:#c9d1d9;font-size:14px;outline:none}
.form-group select:focus{border-color:#58a6ff}
.form-group .desc{font-size:12px;color:#484f58;margin-top:4px}
.btn{background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 24px;font-size:14px;font-weight:600;cursor:pointer}
.btn:hover{background:#2ea043}
.success{background:#1b4924;color:#3fb950;border:1px solid #238636;border-radius:8px;padding:10px 16px;font-size:13px;margin-bottom:16px}
.error{background:#49241b;color:#f85149;border:1px solid #da3633;border-radius:8px;padding:10px 16px;font-size:13px;margin-bottom:16px}
.info{color:#8b949e;font-size:13px;line-height:1.6}
.info span{color:#58a6ff}
.footer{text-align:center;color:#484f58;font-size:11px;margin-top:40px}
.model-card{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;gap:12px}
.model-card input[type=radio]{accent-color:#58a6ff}
.model-card label{flex:1;cursor:pointer}
.model-card .mname{font-size:14px;color:#f0f6fc}
.model-card .mdesc{font-size:12px;color:#484f58}
.not-found{text-align:center;padding:80px 20px}
.not-found h1{font-size:48px;color:#484f58;margin-bottom:16px}
.not-found p{color:#8b949e;font-size:14px}
.not-found a{color:#58a6ff;text-decoration:none}
</style>
</head>
<body>
<div class="header">
<h1>🤖 我的 AI Bot</h1>
<span style="font-size:12px;color:#8b949e">{{ name }}</span>
</div>
<div class="container">
{% if msg %}<div class="success">{{ msg }}</div>{% endif %}
{% if err %}<div class="error">{{ err }}</div>{% endif %}
<div class="card">
<h2>🧠 选择 AI 模型</h2>
<p class="info" style="margin-bottom:16px">选择你希望 AI 助手使用的模型，不同的模型在速度和能力上有所差异。</p>
<form method="post" action="/my/{{ token }}/save">
{% for m in models %}
<div class="model-card">
<input type="radio" name="model" value="{{ m.id }}" id="m_{{ m.id }}" {% if m.id == current_model %}checked{% endif %}>
<label for="m_{{ m.id }}">
<div class="mname">{{ m.name }}</div>
<div class="mdesc">{{ m.desc }}</div>
</label>
</div>
{% endfor %}
<div style="margin-top:16px">
<button type="submit" class="btn">💾 保存设置</button>
</div>
</form>
</div>
<div class="card">
<h2>📋 使用说明</h2>
<div class="info">
<p>1. 打开微信即可与 AI 助手开始对话</p>
<p>2. 选择模型后将在下次对话时生效</p>
<p>3. 可随时在本页面切换模型</p>
<p style="margin-top:8px;color:#484f58">ID: <span>{{ user_id }}</span></p>
</div>
</div>
</div>
<div class="footer">AI Bot Platform</div>
</body>
</html>"""

NOT_FOUND_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>404 - 页面未找到</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;display:flex;align-items:center;justify-content:center}
.not-found{text-align:center;padding:40px}
.not-found h1{font-size:64px;color:#30363d;margin-bottom:12px;font-weight:800}
.not-found h2{font-size:20px;color:#8b949e;margin-bottom:8px}
.not-found p{color:#484f58;font-size:14px;margin-bottom:24px}
.not-found a{color:#58a6ff;text-decoration:none;font-size:14px}
.not-found a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="not-found">
<h1>404</h1>
<h2>页面未找到</h2>
<p>无效的访问链接，请确认地址正确</p>
<a href="/">← 返回首页</a>
</div>
</body>
</html>"""

OCR_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OCR 文档识别</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.nav-bar{position:fixed;top:0;left:0;right:0;background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;justify-content:center;gap:20px;font-size:13px;z-index:10}
.nav-bar a{color:#8b949e;text-decoration:none}
.nav-bar a:hover{color:#58a6ff}
.container{max-width:900px;margin:0 auto;padding:20px;margin-top:60px}
h1{font-size:22px;color:#f0f6fc;margin-bottom:8px;text-align:center}
.sub{color:#8b949e;font-size:13px;margin-bottom:24px;text-align:center}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:30px;margin-bottom:20px}
form{display:flex;flex-direction:column;gap:16px}
input[type=file]{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px;color:#c9d1d9;font-size:14px}
input[type=file]::file-selector-button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:13px}
input[type=file]::file-selector-button:hover{background:#30363d}
.btn{background:#238636;color:#fff;border:none;border-radius:8px;padding:12px 24px;font-size:15px;font-weight:600;cursor:pointer;display:inline-block;text-align:center}
.btn:hover{background:#2ea043}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-secondary{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:8px 16px;font-size:13px;cursor:pointer;text-decoration:none;display:inline-block}
.btn-secondary:hover{background:#30363d}
.success{background:#1b4924;color:#3fb950;border:1px solid #238636;border-radius:8px;padding:12px;text-align:center;font-size:14px;margin-bottom:16px}
.error{background:#49241b;color:#f85149;border:1px solid #da3633;border-radius:8px;padding:12px;text-align:center;font-size:14px;margin-bottom:16px}
.progress{text-align:center;padding:30px}
.progress .spinner{display:inline-block;width:40px;height:40px;border:4px solid #30363d;border-top-color:#58a6ff;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.progress p{color:#8b949e;font-size:14px;margin-top:12px}
.progress .state{color:#58a6ff;font-size:12px;margin-top:4px}
.result-card{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;margin-top:16px;max-height:600px;overflow:auto}
.result-card pre{font-size:13px;line-height:1.6;color:#c9d1d9;white-space:pre-wrap;word-break:break-word;font-family:"SF Mono","Cascadia Code",monospace}
.result-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.file-info{color:#484f58;font-size:12px;text-align:center;margin-top:8px}
.copy-toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#238636;color:#fff;padding:8px 20px;border-radius:8px;font-size:13px;z-index:100;opacity:0;transition:opacity .3s}
.copy-toast.show{opacity:1}
.analysis-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-top:16px}
.analysis-card h3{font-size:14px;color:#f0f6fc;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.analysis-card .loading{color:#8b949e;font-size:13px;padding:10px 0}
.analysis-card .loading .spin{display:inline-block;width:14px;height:14px;border:2px solid #30363d;border-top-color:#58a6ff;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:8px}
.analysis-card ul{margin:0;padding:0;list-style:none}
.analysis-card li{padding:6px 0;font-size:13px;line-height:1.5;border-bottom:1px solid #0d1117}
.analysis-card li:last-child{border-bottom:none}
.analysis-card .severity{font-size:12px;margin-right:4px}
.analysis-card p{font-size:13px;color:#8b949e;line-height:1.5}
</style>
</head>
<body>
<div class="nav-bar">
<a href="/">🏠 首页</a>
<a href="/gateway">📊 状态面板</a>

<a href="/upload">📁 文件上传</a>
<a href="/admin">⚙️ 管理</a>
</div>
<div class="container">
<h1>📄 OCR 文档识别</h1>
<p class="sub">上传 PDF、图片等文档，自动提取文字内容（支持中英文）</p>

{% if err %}<div class="error">{{ err }}</div>{% endif %}
{% if msg %}<div class="success">{{ msg }}</div>{% endif %}

<div id="upload-card" class="card">
<form method="post" enctype="multipart/form-data" action="/ocr">
<input type="file" name="files" accept=".pdf,.jpg,.jpeg,.png,.webp,.bmp,.tiff" multiple required>
<button type="submit" class="btn">📤 上传并识别</button>
</form>
{% if errors %}
<div style="margin-top:16px">
{% for e in errors %}
<div class="error">{{ e }}</div>
{% endfor %}
</div>
{% endif %}
</div>

<div id="progress-card" class="card" style="{% if not tasks or result %}display:none{% endif %}">
<div class="progress">
<div class="spinner"></div>
<p>⏳ 正在处理 {{ tasks|length }} 个文件...</p>
<div id="batch-status" style="margin-top:16px;text-align:left">
{% for t in tasks %}
<div id="task-{{ t.task_id }}" style="padding:6px 0;font-size:13px;color:#8b949e">
<span>📄 {% if t.file_name %}{{ t.file_name }}{% else %}文档 {{ loop.index }}{% endif %}</span>
<span id="state-{{ t.task_id }}" style="float:right;color:#58a6ff">⏳ 排队中</span>
</div>
{% endfor %}
</div>
</div>
</div>

<div id="result-card" class="card" style="{% if not result %}display:none{% endif %}">
<h2 style="color:#f0f6fc;font-size:16px;margin-bottom:8px">✅ 识别结果</h2>
<div id="result-body">
{% if result %}
<div class="file-info">{{ result.file_name or '文档' }} · {{ result.pages or '?' }} 页 · {{ "%.1f"|format((result.file_size or 0)/1024) }} KB · {{ (result.markdown or '')|length }} 字符</div>
<div class="result-card"><pre id="ocr-text">{{ result.markdown }}</pre></div>
<div class="result-actions">
<button class="btn-secondary" onclick="copyResult()">📋 复制全文</button>
<a class="btn-secondary" href="{{ result.full_md_link or '#' }}" target="_blank">🔗 原始 Markdown</a>
<a class="btn-secondary" href="/ocr">🔄 识别另一个</a>
</div>
{% endif %}
</div>
</div>
</div>

<div id="analysis-card" class="card" style="{% if not result %}display:none{% endif %}">
<h2 style="color:#f0f6fc;font-size:16px;margin-bottom:8px">🔍 识别质量分析</h2>
<div id="analysis-body">
{% if result %}
<div class="analysis-card">
<div class="loading"><span class="spin"></span>AI 正在分析识别质量...</div>
</div>
{% endif %}
</div>
</div>

<div id="copy-toast" class="copy-toast">已复制到剪贴板</div>

<script>
{% if tasks %}
var taskIds = [{% for t in tasks %}{{ t.task_id|tojson }}{% if not loop.last %},{% endif %}{% endfor %}];
var taskNames = [{% for t in tasks %}{{ t.file_name|tojson }}{% if not loop.last %},{% endif %}{% endfor %}];
var pollCount = 0;
var maxPolls = 180;
var results = {};
var completed = 0;
var resultShown = false;

function showResult(taskId, data) {
    if (resultShown) return;
    resultShown = true;
    var card = document.getElementById('result-card');
    var body = document.getElementById('result-body');
    card.style.display = '';
    // Find the file name for this task
    var idx = taskIds.indexOf(taskId);
    var fname = idx >= 0 ? taskNames[idx] : (data.file_name || '文档');
    var pages = data.pages || '?';
    var sizeKB = data.file_size ? (data.file_size / 1024).toFixed(1) : '?';
    var md = data.markdown || '(无内容)';
    // Truncate for preview
    var preview = md.length > 5000 ? md.substring(0, 5000) + '\n\n...（共 ' + md.length + ' 字符，展示前 5000 字符）' : md;
    body.innerHTML =
        '<div class="file-info">' + fname + ' · ' + pages + ' 页 · ' + sizeKB + ' KB · ' + md.length + ' 字符</div>' +
        '<div class="result-card"><pre id="ocr-text">' + escapeHtml(preview) + '</pre></div>' +
        '<div class="result-actions">' +
        '<button class="btn-secondary" onclick="copyResult()">📋 复制全文</button>' +
        '<a class="btn-secondary" href="' + (data.full_md_link || '#') + '" target="_blank">🔗 原始 Markdown</a>' +
        '<a class="btn-secondary" href="/ocr">🔄 识别另一个</a>' +
        '</div>';
    // Save to localStorage so result survives page re-visits
    try {
        var saveData = {data: data, fname: fname, ts: Date.now()};
        localStorage.setItem('ocr_last_result', JSON.stringify(saveData));
    } catch(e) {}
    // Start AI quality analysis
    startAnalysis(data.markdown || '', data.file_name || fname, data.pages || 1);
}

function startAnalysis(md, name, pages) {
    var card = document.getElementById('analysis-card');
    var body = document.getElementById('analysis-body');
    if (!card || !body) return;
    card.style.display = '';
    body.innerHTML = '<div class="analysis-card"><div class="loading"><span class="spin"></span>AI 正在逐页分析识别质量...</div></div>';

    fetch('/ocr/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({markdown: md, file_name: name, pages: pages || 1}),
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        body.innerHTML = '<div class="analysis-card">' + d.html + '</div>';
    })
    .catch(function() {
        body.innerHTML = '<div class="analysis-card"><p style="color:#8b949e">分析请求失败</p></div>';
    });
}

function escapeHtml(s) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(s));
    return div.innerHTML;
}

function pollAll() {
    if (pollCount >= maxPolls) {
        document.getElementById('batch-status').innerHTML = '<p style="color:#f85149">⏰ 部分任务超时</p>';
        document.querySelector('.spinner').style.display = 'none';
        return;
    }
    pollCount++;
    var stillRunning = 0;
    taskIds.forEach(function(tid) {
        fetch('/ocr/status/' + tid + '?_=' + Date.now())
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var stateEl = document.getElementById('state-' + tid);
                if (!stateEl) return;
                if (d.state === 'done') {
                    stateEl.textContent = '✅ 完成';
                    stateEl.style.color = '#3fb950';
                    results[tid] = d;
                    completed++;
                    // Show result for the first completed task
                    if (completed === 1) {
                        showResult(tid, d);
                    }
                } else if (d.state === 'failed' || d.state === 'error') {
                    stateEl.textContent = '❌ ' + (d.error || '失败');
                    stateEl.style.color = '#f85149';
                    completed++;
                } else {
                    stateEl.textContent = '⏳ ' + d.state;
                    stillRunning++;
                }
            })
            .catch(function(err) {
                var stateEl = document.getElementById('state-' + tid);
                if (stateEl) {
                    stateEl.textContent = '❌ 请求失败';
                    stateEl.style.color = '#f85149';
                }
                completed++;
            });
    });
    // Schedule next poll if not all tasks are done yet
    // (checked asynchronously in the next poll cycle)
    if (completed < taskIds.length) {
        setTimeout(pollAll, 3000);
    } else {
        document.querySelector('.spinner').style.display = 'none';
        document.getElementById('batch-status').innerHTML = '<p style="color:#3fb950">✅ 全部处理完成！<a href="/ocr" style="color:#58a6ff;margin-left:12px">上传更多</a></p>';
    }
}
setTimeout(pollAll, 2000);
{% endif %}

function copyResult() {
    var text = document.getElementById('ocr-text');
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text.textContent).then(function() {
            var toast = document.getElementById('copy-toast');
            toast.classList.add('show');
            setTimeout(function() { toast.classList.remove('show'); }, 2000);
        });
    } else {
        var ta = document.createElement('textarea');
        ta.value = text.textContent;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        var toast = document.getElementById('copy-toast');
        toast.classList.add('show');
        setTimeout(function() { toast.classList.remove('show'); }, 2000);
    }
}
// Restore last OCR result from localStorage on fresh page load
(function() {
    var tasksParam = document.querySelector('[name=tasks]');
    if (!document.querySelector('#result-card') || document.getElementById('result-body').children.length > 0) return;
    try {
        var saved = localStorage.getItem('ocr_last_result');
        if (!saved) return;
        var obj = JSON.parse(saved);
        if (!obj || !obj.data) return;
        // Only restore if the page has no active task polling (no taskIds)
        if (typeof taskIds === 'undefined' || taskIds.length === 0) {
            var data = obj.data;
            var fname = obj.fname || data.file_name || '文档';
            var card = document.getElementById('result-card');
            var body = document.getElementById('result-body');
            card.style.display = '';
            var pages = data.pages || '?';
            var sizeKB = data.file_size ? (data.file_size / 1024).toFixed(1) : '?';
            var md = data.markdown || '(无内容)';
            var preview = md.length > 5000 ? md.substring(0, 5000) + '\n\n...（共 ' + md.length + ' 字符，展示前 5000 字符）' : md;
            body.innerHTML =
                '<div class="file-info">' + escapeHtml(fname) + ' · ' + pages + ' 页 · ' + sizeKB + ' KB · ' + md.length + ' 字符</div>' +
                '<div class="result-card"><pre id="ocr-text">' + escapeHtml(preview) + '</pre></div>' +
                '<div class="result-actions">' +
                '<button class="btn-secondary" onclick="copyResult()">📋 复制全文</button>' +
                '<a class="btn-secondary" href="' + (data.full_md_link || '#') + '" target="_blank">🔗 原始 Markdown</a>' +
                '<a class="btn-secondary" href="/ocr">🔄 识别另一个</a>' +
                '</div>';
        }
    } catch(e) {}
})();
// Start analysis if the page was rendered with a result from the server (no JS polling)
(function() {
    var analysisCard = document.getElementById('analysis-card');
    var resultBody = document.getElementById('result-body');
    if (!analysisCard || !resultBody) return;
    // If analysis card is visible and result is server-rendered (has file-info div)
    if (analysisCard.style.display !== 'none' && resultBody.querySelector('.file-info')) {
        var mdEl = document.getElementById('ocr-text');
        var md = mdEl ? mdEl.textContent : '';
        var fi = resultBody.querySelector('.file-info');
        var name = fi ? fi.textContent.split('·')[0].trim() : '文档';
        // Extract page count from file-info
        var pages = 1;
        if (fi) {
            var m = fi.textContent.match(/(\d+)\s*页/);
            if (m) pages = parseInt(m[1]);
        }
        startAnalysis(md, name, pages);
    }
})();
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════

@app.route("/")
def landing():
    qr = _fetch_bot_qrcode()
    return render_template_string(LANDING_HTML, qr_image_url=qr["qr_image_url"], qr_target_url=qr["qr_target_url"])


@app.route("/f/register-bot")
def register_bot():
    return render_template_string("""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>注册 iLink 微信 Bot</title>
  <style>
    body{margin:0;background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}
    .card{width:min(520px,92vw);background:#161b22;border:1px solid #30363d;border-radius:18px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.35);text-align:center}
    h1{margin:0 0 18px;color:#f0f6fc;font-size:24px}.accent{color:#3fb950}.steps{display:flex;justify-content:center;gap:8px;margin:10px 0 24px;flex-wrap:wrap}.step{border:1px solid #30363d;border-radius:999px;padding:7px 12px;color:#8b949e}.step.active{border-color:#3fb950;color:#3fb950;background:rgba(63,185,80,.08)}
    .qrbox{background:#fff;border-radius:14px;padding:14px;width:300px;height:300px;margin:0 auto 18px;display:flex;align-items:center;justify-content:center}.qrbox img{max-width:300px;max-height:300px}.muted{color:#8b949e}.status{font-size:18px;margin:12px 0;color:#f0f6fc}.btn{display:inline-block;margin-top:16px;background:#238636;color:white;border:0;border-radius:8px;padding:10px 16px;cursor:pointer}.btn:hover{background:#2ea043}code{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:2px 6px;color:#3fb950}
  </style>
</head>
<body>
  <div class="card">
    <h1><span class="accent">iLink</span> 微信 Bot 注册</h1>
    <div class="steps">
      <span id="step-wait" class="step active">等待扫码</span><span class="step">→</span>
      <span id="step-scanned" class="step">已扫码</span><span class="step">→</span>
      <span id="step-confirmed" class="step">已确认</span>
    </div>
    <div class="qrbox"><img id="qr-img" alt="Bot 注册二维码"></div>
    <div id="status" class="status">正在获取二维码...</div>
    <div class="muted">二维码将在 <span id="countdown">100</span> 秒后自动刷新</div>
    <button class="btn" onclick="loadQr()">立即刷新</button>
  </div>
<script>
let qrValue='', countdown=100, countdownTimer=null, pollTimer=null;
function setStep(status){
  ['wait','scanned','confirmed'].forEach(s=>document.getElementById('step-'+s).classList.toggle('active', s===status || (status==='confirmed'&&s==='scanned')));
}
function setStatus(text){document.getElementById('status').innerHTML=text;}
async function loadQr(){
  clearInterval(countdownTimer); clearInterval(pollTimer); countdown=100; document.getElementById('countdown').textContent=countdown; setStep('wait'); setStatus('正在获取二维码...');
  try{
    const r=await fetch('/f/api/bot-qr'); const data=await r.json(); if(!r.ok) throw new Error(data.error||'获取失败');
    qrValue=data.qr_value; document.getElementById('qr-img').src=data.qr_image_url; setStatus('等待扫码...');
    countdownTimer=setInterval(()=>{countdown--; document.getElementById('countdown').textContent=countdown; if(countdown<=0) loadQr();},1000);
    pollTimer=setInterval(checkStatus,3000); checkStatus();
  }catch(e){setStatus('获取二维码失败：'+e.message);}
}
async function checkStatus(){
  if(!qrValue) return;
  try{
    const r=await fetch('/f/api/bot-qr-status?qrcode='+encodeURIComponent(qrValue)); const data=await r.json(); if(!r.ok) throw new Error(data.error||'状态检查失败');
    if(data.status==='wait'){setStep('wait'); setStatus('等待扫码...');}
    else if(data.status==='scanned'){setStep('scanned'); setStatus('已扫码，请在手机上确认');}
    else if(data.status==='confirmed'){setStep('confirmed'); clearInterval(pollTimer); clearInterval(countdownTimer); setStatus('✅ 注册成功！Bot ID: <code>'+(data.ilink_bot_id||'未知')+'</code>');}
    else if(data.status==='expired'){setStatus('二维码已过期，正在刷新...'); loadQr();}
  }catch(e){console.warn(e);}
}
loadQr();
</script>
</body>
</html>
""")


@app.route("/f/api/bot-qr")
def api_bot_qr():
    try:
        data = _ilink_get_json("/ilink/bot/get_bot_qrcode?bot_type=3")
        qr = _normalize_bot_qr(data)
        if not qr["qr_value"] or not qr["qr_target_url"]:
            return jsonify({"error": "invalid iLink QR response", "raw": data}), 502
        return jsonify(qr)
    except Exception as e:
        logger.warning("Failed to fetch bot registration QR: %s", e)
        return jsonify({"error": str(e)}), 502


@app.route("/gateway")
def gateway():
    gateways, updated = get_gateway_status()
    return render_template_string(GATEWAY_HTML, gateways=gateways, updated=updated)


@app.route("/admin")
@require_auth
def admin():
    constitution = load_constitution()
    paired_users = []
    try:
        pairing_dir = os.path.expanduser("~/.hermes/pairing")
        if os.path.isdir(pairing_dir):
            for f in os.listdir(pairing_dir):
                if f.endswith("-approved.json"):
                    paired_users.append(f.replace("-approved.json", ""))
    except Exception as e:
        logger.error("Failed to list paired users: %s", e)
    uptime = "?"
    try:
        r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=3)
        uptime = r.stdout.strip()
    except Exception as e:
        logger.warning("uptime check failed: %s", e)
    token_summary = get_token_summary()
    stats = {"users": len(paired_users), "tokens": token_summary["total_tokens"], "codex_tokens": 0, "uptime": uptime}
    msg = request.args.get("msg", "")
    err = request.args.get("err", "")
    # Precompute token URLs for template (don't pass function to Jinja2)
    user_tokens = {uid: get_user_token(uid) for uid in paired_users}
    return render_template_string(
        ADMIN_HTML, constitution=constitution, paired_users=paired_users, user_tokens=user_tokens,
        stats=stats, msg=msg, err=err,
    )


@app.route("/admin/save", methods=["POST"])
@require_auth
def admin_save():
    # Simple CSRF protection: verify Origin or Referer header
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if origin and "127.0.0.1" not in origin and "localhost" not in origin and "124.222.135.234" not in origin:
        logger.warning("CSRF check failed: suspicious origin %s", origin)
        return redirect(url_for("admin", err="请求来源无效"))
    content = request.form.get("content", "")
    if not content.strip():
        return redirect(url_for("admin", err="内容不能为空"))
    save_constitution(content)
    logger.info("Constitution updated")
    return redirect(url_for("admin", msg="✅ 宪法已保存并生效！"))


@app.route("/api/admin/stats")
@require_auth
def api_admin_stats():
    """Return admin stats as JSON."""
    admin_ids = _get_admin_ids()
    all_user_ids = _scan_all_users()
    regular_users = [u for u in all_user_ids if u not in admin_ids]
    admins = [u for u in all_user_ids if u in admin_ids]
    uptime = "?"
    try:
        r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=3)
        uptime = r.stdout.strip()
    except Exception:
        pass
    token_summary = get_token_summary()
    return jsonify({
        "users": len(regular_users),
        "admins": len(admins),
        "tokens": token_summary["total_tokens"],
        "uptime": uptime,
    })


@app.route("/api/admin/users")
@require_auth
def api_admin_users():
    """Return paired users list with tokens and admin flag."""
    admin_ids = _get_admin_ids()
    all_user_ids = _scan_all_users()
    user_tokens = {uid: get_user_token(uid) for uid in all_user_ids}
    return jsonify({
        "users": all_user_ids,
        "tokens": user_tokens,
        "admins": list(admin_ids),
    })


@app.route("/api/admin/save-constitution", methods=["POST"])
@require_auth
def api_admin_save_constitution():
    """Save constitution via JSON API."""
    data = request.get_json(silent=True)
    if not data or not data.get("content", "").strip():
        return jsonify({"ok": False, "error": "内容不能为空"}), 400
    save_constitution(data["content"])
    return jsonify({"ok": True, "message": "宪法已保存并生效！"})


@app.route("/api/admin/constitution")
@require_auth
def api_admin_constitution():
    """Return constitution as JSON."""
    return jsonify({"content": load_constitution()})


@app.route("/api/admin/check", methods=["GET", "POST"])
@require_auth
def api_admin_check():
    """Auth check for Next.js admin login."""
    return jsonify({"ok": True, "admin": True})


@app.route("/api/tokens")
def api_tokens():
    """Return token usage summary as JSON."""
    hours = request.args.get("hours", None, type=int)
    return jsonify(get_token_summary(hours))



@app.route("/api/my/<token>")
def api_my_dashboard(token):
    """Return user dashboard data as JSON."""
    user_id = resolve_token(token)
    if not user_id:
        return jsonify({"ok": False, "error": "无效的访问链接"}), 404
    prefs = get_user_prefs(user_id)
    return jsonify({
        "ok": True,
        "name": prefs.get("name", user_id),
        "user_id": user_id,
        "models": AVAILABLE_MODELS,
        "current_model": normalize_model_id(prefs.get("model", DEFAULT_MODEL_ID)),
    })


@app.route("/api/my/<token>/stats")
def api_my_stats(token):
    """Return personal token usage stats."""
    user_id = resolve_token(token)
    if not user_id:
        return jsonify({"ok": False, "error": "无效的访问链接"}), 404
    token_summary = get_token_summary()
    return jsonify({
        "ok": True,
        "total_tokens": token_summary["total_tokens"],
        "models": token_summary["models"],
    })


@app.route("/api/my/<token>/save", methods=["POST"])
def api_my_save(token):
    """Save user model preference via JSON API."""
    user_id = resolve_token(token)
    if not user_id:
        return jsonify({"ok": False, "error": "无效的访问链接"}), 404
    data = request.get_json(silent=True)
    if not data or not data.get("model"):
        return jsonify({"ok": False, "error": "请选择模型"}), 400
    model = data["model"]
    valid_ids = [m["id"] for m in AVAILABLE_MODELS]
    if model not in valid_ids:
        return jsonify({"ok": False, "error": "无效的模型 ID"}), 400
    prefs = get_user_prefs(user_id)
    prefs["model"] = model
    try:
        save_user_prefs(user_id, prefs)
        return jsonify({"ok": True, "message": f"模型已切换为 {model}"})
    except Exception as e:
        logger.error("Failed to save prefs for %s: %s", user_id, e)
        return jsonify({"ok": False, "error": "保存失败"}), 500


@app.route("/upload", methods=["GET", "POST"])
@require_auth
def upload_page():
    if request.method == "POST":
        mode = request.form.get("mode", "file")
        # ── Folder upload mode (webkitdirectory) ──
        if mode == "folder":
            files = request.files.getlist("files[]")
            if not files or not files[0].filename:
                return redirect(url_for("upload_page", err="❌ 请选择文件夹"))
            saved = 0
            errors = []
            for f in files:
                # webkitdirectory sends relative paths like "subdir/file.txt"
                rel_path = f.filename.replace("\\", "/")
                if not rel_path or rel_path.endswith("/"):
                    continue
                safe_name = f"{uuid.uuid4().hex}_{rel_path.replace('/', '_')}"
                # Preserve folder structure: use relative-dir-based subfolders
                rel_dir = os.path.dirname(rel_path)
                target_dir = UPLOAD_DIR
                if rel_dir:
                    target_dir = os.path.join(UPLOAD_DIR, rel_dir.replace("/", "_"))
                    os.makedirs(target_dir, exist_ok=True)
                save_path = os.path.join(target_dir, safe_name)
                try:
                    f.save(save_path)
                    saved += 1
                except Exception as e:
                    errors.append(f"{rel_path}: {e}")
            parts = [f"✅ 已保存 {saved} 个文件"]
            if errors:
                parts.append(f"⚠️ {len(errors)} 个失败")
            return redirect(url_for("upload_page", msg="；".join(parts)))
        # ── Single file upload (existing) ──
        f = request.files.get("file")
        if not f or not f.filename:
            return redirect(url_for("upload_page", err="❌ 请选择文件"))
        if not allowed_file(f.filename):
            return redirect(url_for("upload_page", err="❌ 不支持的文件类型"))
        _, ext = os.path.splitext(f.filename.lower())
        safe_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, safe_name)
        try:
            f.save(save_path)
            if os.path.getsize(save_path) > MAX_FILE_SIZE:
                os.remove(save_path)
                return redirect(url_for("upload_page", err="❌ 文件超过 200MB 限制"))
            logger.info("File uploaded: %s (%s)", safe_name, f.filename)
        except Exception as e:
            logger.error("Upload failed: %s", e)
            return redirect(url_for("upload_page", err=f"❌ 上传失败: {e}"))
        # ── Auto-extract supported archives ──
        extract_dir = None
        if ext in (".zip",):
            try:
                extract_dir = safe_name.rsplit(".", 1)[0]
                target = os.path.join(UPLOAD_DIR, extract_dir)
                os.makedirs(target, exist_ok=True)
                with zipfile.ZipFile(save_path, "r") as zf:
                    zf.extractall(target)
                count = len(os.listdir(target))
                msg = f"✅ {f.filename} 上传并解压完成（{count} 个文件）"
                logger.info("Extracted zip %s -> %s (%d files)", safe_name, extract_dir, count)
            except Exception as e:
                logger.error("Zip extraction failed for %s: %s", safe_name, e)
                extract_dir = None
                msg = f"✅ {f.filename} 上传成功（解压失败: {e}）"
        elif ext in (".tar", ".gz") and (f.filename.endswith(".tar.gz") or f.filename.endswith(".tgz") or ext == ".tar"):
            try:
                extract_dir = safe_name.rsplit(".", 1)[0]
                if extract_dir.endswith(".tar"):
                    extract_dir = extract_dir[:-4]
                target = os.path.join(UPLOAD_DIR, extract_dir)
                os.makedirs(target, exist_ok=True)
                mode = "r:gz" if f.filename.endswith(".gz") or f.filename.endswith(".tgz") else "r:"
                with tarfile.open(save_path, mode) as tf:
                    tf.extractall(target, filter="data")  # safe extract
                count = len(os.listdir(target))
                msg = f"✅ {f.filename} 上传并解压完成（{count} 个文件）"
                logger.info("Extracted tar %s -> %s (%d files)", safe_name, extract_dir, count)
            except Exception as e:
                logger.error("Tar extraction failed for %s: %s", safe_name, e)
                extract_dir = None
                msg = f"✅ {f.filename} 上传成功（解压失败: {e}）"
        else:
            msg = f"✅ {f.filename} 上传成功！"
        return redirect(url_for("upload_page", msg=msg))
    msg = request.args.get("msg", "")
    err = request.args.get("err", "")
    files = []
    try:
        files = [{"name": f["name"], "size": f["size_human"]} for f in list_uploaded_files()]
    except Exception as e:
        logger.error("Failed to list uploads: %s", e)
    return render_template_string(UPLOAD_HTML, msg=msg, err=err, files=files)


def _safe_extract_zip(zf: zipfile.ZipFile, target: str) -> int:
    """Extract zip safely: reject symlinks and path traversal."""
    count = 0
    for info in zf.infolist():
        # Skip directories
        if info.filename.endswith("/"):
            continue
        # Reject symlinks
        if info.external_attr >> 16 & 0o120000:  # S_ISLNK
            logger.warning("Skipping symlink in zip: %s", info.filename)
            continue
        # Reject path traversal
        safe_path = os.path.normpath(os.path.join(target, info.filename))
        if not safe_path.startswith(os.path.normpath(target)):
            logger.warning("Skipping path traversal in zip: %s", info.filename)
            continue
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with zf.open(info) as src, open(safe_path, "wb") as dst:
            dst.write(src.read())
        count += 1
    return count


@app.route("/upload/api", methods=["POST"])
@require_auth
def upload_api():
    """AJAX upload endpoint - returns JSON with progress info."""
    # 支持 "files" (多文件) 和 "file" (单文件) 字段名
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f and f.filename:
            files = [f]
    if not files or not any(f.filename for f in files):
        return jsonify({"error": "请选择文件"}), 400

    # 文件夹模式：前端会传 path 字段，保留目录结构
    folder_path = (request.form.get("path") or "").strip()
    is_folder_upload = bool(folder_path)

    results = []
    errors = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            errors.append(f"{f.filename}: 不支持的文件类型")
            continue

        # ── 文件夹模式：保留目录结构 ──
        if is_folder_upload:
            # folder_path 是文件的相对路径（如 "17/subdir/file.txt"）
            rel_path = folder_path.replace("\\", "/")
            rel_dir = os.path.dirname(rel_path)
            orig_name = os.path.basename(rel_path)
            _, ext = os.path.splitext(orig_name.lower())
            safe_name = f"{uuid.uuid4().hex}_{orig_name}"
            target_dir = UPLOAD_DIR
            if rel_dir:
                target_dir = os.path.join(UPLOAD_DIR, rel_dir)
            # 防止路径穿越
            target_dir = os.path.normpath(target_dir)
            if not target_dir.startswith(os.path.normpath(UPLOAD_DIR)):
                errors.append(f"{orig_name}: 路径穿越拒绝")
                continue
            os.makedirs(target_dir, exist_ok=True)
            save_path = os.path.join(target_dir, safe_name)
        else:
            _, ext = os.path.splitext(f.filename.lower())
            safe_name = f"{uuid.uuid4().hex}{ext}"
            save_path = os.path.join(UPLOAD_DIR, safe_name)

        try:
            f.save(save_path)
            fsiz = os.path.getsize(save_path)
            if fsiz > MAX_FILE_SIZE:
                os.remove(save_path)
                errors.append(f"{f.filename}: 文件超过 2GB 限制")
                continue
            logger.info("File uploaded via API: %s (%s) %d bytes", safe_name, f.filename, fsiz)
        except Exception as e:
            logger.error("Upload API failed for %s: %s", f.filename, e)
            errors.append(f"{f.filename}: 上传失败")
            continue

        # Auto-extract archives (only for non-folder uploads)
        extracted_info = None
        if not is_folder_upload:
            if ext in (".zip",):
                try:
                    extract_dir = safe_name.rsplit(".", 1)[0]
                    target = os.path.join(UPLOAD_DIR, extract_dir)
                    os.makedirs(target, exist_ok=True)
                    with zipfile.ZipFile(save_path, "r") as zf:
                        count = _safe_extract_zip(zf, target)
                    extracted_info = {"dir": extract_dir, "files": count}
                except Exception as e:
                    logger.warning("Zip extraction failed: %s", e)
            elif ext in (".tar", ".gz") and (f.filename.endswith(".tar.gz") or f.filename.endswith(".tgz") or ext == ".tar"):
                try:
                    extract_dir = safe_name.rsplit(".", 1)[0]
                    if extract_dir.endswith(".tar"):
                        extract_dir = extract_dir[:-4]
                    target = os.path.join(UPLOAD_DIR, extract_dir)
                    os.makedirs(target, exist_ok=True)
                    mode = "r:gz" if f.filename.endswith(".gz") or f.filename.endswith(".tgz") else "r:"
                    with tarfile.open(save_path, mode) as tf:
                        tf.extractall(target, filter="data")
                    count = len([x for x in os.listdir(target) if os.path.isfile(os.path.join(target, x))])
                    extracted_info = {"dir": extract_dir, "files": count}
                except Exception as e:
                    logger.warning("Tar extraction failed: %s", e)

        results.append({
            "name": safe_name,
            "original": f.filename,
            "size": fsiz,
            "size_human": format_size(fsiz),
            "extracted": extracted_info,
        })
    if not results:
        status = 413 if any("2GB" in e for e in errors) else 400
        return jsonify({"error": "；".join(errors) or "上传失败", "errors": errors}), status
    response = {"ok": True, "files": results, "errors": errors}
    response.update(results[-1])
    return jsonify(response)


@app.route("/upload/delete", methods=["POST"])
@require_auth
def upload_delete():
    data = request.get_json(silent=True)
    filename = (data.get("filename") or data.get("name") or "") if data else ""
    if not filename or not isinstance(filename, str):
        return jsonify({"error": "no filename"}), 400
    safe_name = os.path.basename(filename)
    filepath = os.path.join(UPLOAD_DIR, safe_name)
    if os.path.isfile(filepath):
        try:
            os.remove(filepath)
            logger.info("File deleted: %s", safe_name)
            return jsonify({"ok": True})
        except Exception as e:
            logger.error("Failed to delete %s: %s", safe_name, e)
            return jsonify({"error": str(e)}), 500
    if os.path.isdir(filepath):
        try:
            import shutil
            shutil.rmtree(filepath)
            logger.info("Directory deleted: %s", safe_name)
            return jsonify({"ok": True})
        except Exception as e:
            logger.error("Failed to delete directory %s: %s", safe_name, e)
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "not found"}), 404


@app.route("/upload/reload", methods=["POST"])
@require_auth
def upload_reload():
    try:
        files = list_uploaded_files()
    except Exception as e:
        logger.error("Failed to reload upload list: %s", e)
        return jsonify({"ok": False, "error": "文件列表读取失败"}), 500
    return jsonify({"ok": True, "count": len(files), "files": files})


@app.route("/f/<path:name>")
def download_file(name):
    safe_name = os.path.basename(name)
    response = send_from_directory(UPLOAD_DIR, safe_name)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return response


# Rate limit for qrcode endpoint
_qrcode_rate: dict[str, list[float]] = {}
QRCODE_RATE_LIMIT = 5   # max requests
QRCODE_RATE_WINDOW = 60  # per minute

@app.route("/api/qrcode")
def api_qrcode():
    """Return current WeChat QR code data (JSON). Rate-limited per IP."""
    ip = request.remote_addr or "unknown"
    now = time.time()
    window = [_ for _ in _qrcode_rate.get(ip, []) if now - _ < QRCODE_RATE_WINDOW]
    if len(window) >= QRCODE_RATE_LIMIT:
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429
    window.append(now)
    _qrcode_rate[ip] = window
    return jsonify(_fetch_bot_qrcode())


PAIRING_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>微信配对 - AI Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px}
h1{font-size:24px;color:#f0f6fc;margin-bottom:8px}
.sub{color:#8b949e;font-size:14px;margin-bottom:24px}
.qr-box{background:#fff;border-radius:16px;padding:20px;display:inline-block;margin-bottom:16px}
.qr-box img{width:260px;height:260px;display:block}
.timer{color:#58a6ff;font-size:13px;margin-bottom:8px}
.expiry{color:#f85149;font-size:12px}
.expiry.ok{color:#3fb950}
.hint{color:#484f58;font-size:12px;margin-top:16px;text-align:center;max-width:360px;line-height:1.6}
.back{color:#8b949e;font-size:13px;text-decoration:none;margin-top:24px}
.back:hover{color:#58a6ff}
</style>
</head>
<body>
<h1>📱 扫码配对 AI 助手</h1>
<p class="sub">打开微信扫一扫，添加 AI Bot</p>
<div class="qr-box">
<img id="qr-img" src="" alt="微信配对二维码">
</div>
<p class="timer">⏱ 自动刷新倒计时：<span id="countdown">--</span></p>
<p class="expiry ok" id="status">等待加载…</p>
<p class="hint">二维码每 100 秒自动刷新，<br>扫码后发一条消息给 Bot 即可完成配对。</p>
<a href="/" class="back">← 返回首页</a>

<script>
const REFRESH_INTERVAL = 100; // seconds
let remaining = REFRESH_INTERVAL;
let img = document.getElementById('qr-img');
let cd = document.getElementById('countdown');
let st = document.getElementById('status');

async function loadQR() {
  try {
    let resp = await fetch('/api/qrcode');
    let data = await resp.json();
    img.src = data.qr_image_url + '&t=' + Date.now();
    remaining = REFRESH_INTERVAL;
    st.textContent = '✅ 二维码有效';
    st.className = 'expiry ok';
  } catch(e) {
    st.textContent = '❌ 加载失败，请刷新页面';
    st.className = 'expiry';
  }
}

function tick() {
  cd.textContent = remaining + ' 秒';
  if (remaining <= 20) st.className = 'expiry';
  remaining--;
  if (remaining < 0) loadQR();
}

loadQR();
setInterval(tick, 1000);
</script>
</body>
</html>"""

@app.route("/pairing")
@app.route("/f/pairing")
def pairing_page():
    return render_template_string(PAIRING_HTML)


@app.route("/api/models")
def api_models():
    """Return available models."""
    return jsonify(AVAILABLE_MODELS)


@app.route("/api/status")
def api_status():
    gateways, _ = get_gateway_status()
    return jsonify(gateways)


@app.route("/api/system-doc")
def api_system_doc():
    """Return the system document — dynamically generated from skills + SOUL + system state."""
    try:
        html = _build_system_doc()
        if html:
            return jsonify({"html": html})
        # fallback: try cached version
        if os.path.exists(SYSTEM_DOC_PATH):
            with open(SYSTEM_DOC_PATH, encoding="utf-8") as f:
                return jsonify({"html": f.read()})
        return jsonify({"error": "系统文档生成失败"}), 503
    except Exception as e:
        logger.exception("Failed to build system document")
        return jsonify({"error": str(e)}), 500


def _build_system_doc():
    """Dynamically generate system documentation markdown, convert to HTML, cache it."""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CST")

    sections = []

    # ── Section 1: 系统说明（避免与首页能力介绍重复） ──
    sections.append("# 📋 系统说明")
    sections.append(f"> 自动生成 · {now}")
    sections.append("")
    sections.append("我是 **泰乐**（Telegram 的泰 + Hermes 的乐），基于 DeepSeek V4 Pro 的智能 AI 助手。")
    sections.append("")
    sections.append("**平台能力与技能请查看首页和 [Skills 仓库](/skills)，本页聚焦系统架构与运维。**")
    sections.append("")

    # ── Section 2: 系统架构 ──
    sections.append("---")
    sections.append("## 🏗️ 系统架构")
    sections.append("")
    sections.append("| 组件 | 说明 |")
    sections.append("|------|------|")
    sections.append("| 服务器 | 腾讯云 Lighthouse · Ubuntu 24.04 · 2C/1.9G/40G |")
    sections.append("| 主网关 | `hermes-gateway` · `default` profile · DeepSeek V4 Pro |")
    sections.append("| 小黑网关 | `hermes-gateway-xiaohei` · `xiaohei` profile · DeepSeek V4 Flash |")
    sections.append("| Web 管理 | Nginx :443 → Next.js :3000 + Flask :5000 |")
    sections.append("| Hermes 面板 | `hermes-dashboard` · 端口 9119 |")
    sections.append("| 代理 | mihomo :7890 · CN 直连 |")
    sections.append("")

    # ── Section 3: Profiles ──
    sections.append("## 👤 Profiles")
    sections.append("")
    sections.append("| Profile | 模型 | 说明 |")
    sections.append("|---------|------|------|")
    sections.append("| `default` | deepseek-v4-pro | 主网关，全功能 |")
    sections.append("| `xiaohei` | deepseek-v4-flash | 小狗人设，仅中文 |")
    sections.append("")

    # ── Section 4: 每日更新 ──
    sections.append("---")
    sections.append("## 🆕 每日更新")
    sections.append("")
    sections.append("> 每天自动吸收新知识，以下是最新更新内容。")
    sections.append("")

    soul = ""
    if os.path.exists(SOUL_PATH):
        try:
            with open(SOUL_PATH, encoding="utf-8") as f:
                soul = f.read()
        except Exception:
            pass

    daily_updates = []
    in_daily = False
    current_date = ""
    current_block = []
    if soul:
        for line in soul.split("\n"):
            if line.startswith("## 九、每日吸收") or line.startswith("### 每日吸收"):
                in_daily = True
                continue
            if in_daily:
                if line.startswith("## ") and not line.startswith("### "):
                    # save previous block
                    if current_block and current_date:
                        daily_updates.append((current_date, "\n".join(current_block)))
                    current_block = []
                    if not line.startswith("### "):
                        in_daily = False
                        continue
                if line.startswith("### "):
                    if current_block and current_date:
                        daily_updates.append((current_date, "\n".join(current_block)))
                    current_date = line.strip("# ").strip()
                    current_block = []
                else:
                    current_block.append(line)
        # last block
        if current_block and current_date:
            daily_updates.append((current_date, "\n".join(current_block)))

    if daily_updates:
        for date, content in daily_updates[-5:]:  # show last 5
            sections.append(f"### 📅 {date}")
            sections.append("")
            # mark content as new with emoji prefix
            for line in content.split("\n"):
                if line.strip():
                    sections.append(f"✨ {line.strip()}")
                else:
                    sections.append("")
            sections.append("")
    else:
        sections.append("> 暂无每日更新记录")
    sections.append("")

    # ── 组装并渲染 ──
    md = "\n".join(sections)

    # Cache the markdown
    os.makedirs(os.path.dirname(SYSTEM_DOC_MD_PATH), exist_ok=True)
    with open(SYSTEM_DOC_MD_PATH, "w", encoding="utf-8") as f:
        f.write(md)

    # Render to HTML
    try:
        import markdown
        html = markdown.markdown(md, extensions=["extra", "toc", "sane_lists"], output_format="html5")
    except ImportError:
        from markdown_it import MarkdownIt
        html = MarkdownIt("gfm-like", {"html": True, "linkify": False}).render(md)

    # Cache the HTML
    with open(SYSTEM_DOC_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    return html


def _scan_skills(skills_dir):
    """Scan skills directory and extract name, category, description."""
    import yaml
    entries = []
    for root, dirs, files in os.walk(skills_dir):
        for fname in files:
            if fname == "SKILL.md":
                full = os.path.join(root, fname)
                try:
                    with open(full, encoding="utf-8") as f:
                        content = f.read()
                    # Extract frontmatter
                    if content.startswith("---"):
                        end = content.find("---", 3)
                        if end > 0:
                            fm_text = content[3:end]
                            fm = yaml.safe_load(fm_text) or {}
                        else:
                            fm = {}
                    else:
                        fm = {}

                    name = fm.get("name", os.path.basename(os.path.dirname(full)))
                    desc = fm.get("description", "—")
                    # Truncate long descriptions
                    if len(desc) > 80:
                        desc = desc[:77] + "..."
                    # Determine category — use top-level only (collapse subdirectories)
                    rel = os.path.relpath(os.path.dirname(full), skills_dir)
                    cat = rel.split("/")[0]

                    entries.append((name, cat, desc))
                except Exception:
                    pass

    # Sort by category then name
    entries.sort(key=lambda x: (x[1], x[0]))
    return entries


# ── Skills Audit API ─────────────────────────────────────────────────

SKILLS_AUDIT_CACHE = "/root/.hermes/cache/skills-audit.json"

@app.route("/api/skills-audit")
def api_skills_audit():
    """Return GPT-evaluated skills audit from engineering management perspective."""
    import datetime, hashlib

    # Serve cache if fresh (< 24h)
    if os.path.exists(SKILLS_AUDIT_CACHE):
        mtime = os.path.getmtime(SKILLS_AUDIT_CACHE)
        if time.time() - mtime < 86400:
            with open(SKILLS_AUDIT_CACHE, encoding="utf-8") as f:
                return jsonify(json.load(f))

    # Force refresh
    refresh = request.args.get("refresh", "")
    if refresh:
        try:
            result = _run_skills_audit()
            return jsonify(result)
        except Exception as e:
            logger.exception("Skills audit failed")
            return jsonify({"error": str(e)}), 500

    # Return cached even if stale
    if os.path.exists(SKILLS_AUDIT_CACHE):
        with open(SKILLS_AUDIT_CACHE, encoding="utf-8") as f:
            return jsonify(json.load(f))

    return jsonify({"error": "审计数据未生成，请加 ?refresh=1 触发"}), 503


@app.route("/api/skills-audit/refresh", methods=["POST"])
def api_skills_audit_refresh():
    """Force refresh skills audit."""
    try:
        result = _run_skills_audit()
        return jsonify(result)
    except Exception as e:
        logger.exception("Skills audit refresh failed")
        return jsonify({"error": str(e)}), 500


def _run_skills_audit():
    """Run full skills audit via DeepSeek evaluation."""
    import urllib.request

    skills_dir = os.path.expanduser("~/.hermes/skills")
    all_skills = []

    for root, dirs, files in os.walk(skills_dir):
        for fname in files:
            if fname == "SKILL.md":
                full = os.path.join(root, fname)
                try:
                    stat = os.stat(full)
                    with open(full, encoding="utf-8") as f:
                        content = f.read()
                    fm = {}
                    if content.startswith("---"):
                        end = content.find("---", 3)
                        if end > 0:
                            import yaml
                            fm = yaml.safe_load(content[3:end]) or {}

                    name = fm.get("name", os.path.basename(os.path.dirname(full)))
                    desc = fm.get("description", "")
                    rel = os.path.relpath(os.path.dirname(full), skills_dir)
                    cat = rel.split("/")[0]

                    # Count body lines (after frontmatter)
                    body = content[end+3:] if content.startswith("---") and end > 0 else content
                    body_lines = len([l for l in body.split("\n") if l.strip()])

                    all_skills.append({
                        "name": name,
                        "category": cat,
                        "description": desc[:200],
                        "size_kb": round(stat.st_size / 1024, 1),
                        "body_lines": body_lines,
                        "file": os.path.relpath(full, skills_dir),
                    })
                except Exception:
                    pass

    # Evaluate in batches of 8
    BATCH_SIZE = 8
    evaluated = []

    for i in range(0, len(all_skills), BATCH_SIZE):
        batch = all_skills[i:i+BATCH_SIZE]
        prompt = _build_eval_prompt(batch, i+1, len(all_skills))
        result = _call_deepseek(prompt)
        if result:
            evaluated.extend(result)

    # Sort by rating desc
    evaluated.sort(key=lambda x: x.get("rating", 0), reverse=True)

    # Build summary stats
    ratings = [s["rating"] for s in evaluated if s.get("rating")]
    verdicts = {}
    for s in evaluated:
        v = s.get("verdict", "UNKNOWN")
        verdicts[v] = verdicts.get(v, 0) + 1

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M CST"),
        "total": len(evaluated),
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else 0,
        "verdicts": verdicts,
        "skills": evaluated,
    }

    # Cache
    os.makedirs(os.path.dirname(SKILLS_AUDIT_CACHE), exist_ok=True)
    with open(SKILLS_AUDIT_CACHE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# ── User Skills API ─────────────────────────────────────────────────

def _scan_skill_metadata(skills_dir, audit_map):
    """Merge audit data with live file metadata for every skill on disk (recursive)."""
    results = []
    seen = set()
    for root, dirs, files in os.walk(skills_dir):
        if "SKILL.md" not in files:
            continue
        rel_path = os.path.relpath(root, skills_dir)
        # Skip intermediate dirs that aren't skill dirs (e.g. a subdir named "creative" is not a skill name)
        # Skill name is the last component of rel_path
        skill_name = os.path.basename(root)
        if skill_name in seen or not skill_name:
            continue
        seen.add(skill_name)

        skill_file = os.path.join(root, "SKILL.md")
        try:
            fsize = os.path.getsize(skill_file)
            fsize_kb = round(fsize / 1024, 1)
            with open(skill_file, encoding="utf-8") as fp:
                content = fp.read()
            body_lines = content.count("\n") + 1
            desc = ""
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    fm_lines = content[3:end].strip().split("\n")
                    for line in fm_lines:
                        if line.startswith("description:"):
                            desc = line[len("description:"):].strip().strip("\"' ")
        except Exception:
            continue
        audit = audit_map.get(skill_name, {})
        results.append({
            "name": skill_name,
            "category": audit.get("category", ""),
            "file": rel_path,
            "rating": audit.get("rating", 0),
            "composite": audit.get("composite", audit.get("rating", 0)),
            "verdict": audit.get("verdict", "REVIEW"),
            "reason": audit.get("reason", ""),
            "issues": audit.get("issues", []) or [],
            "size_kb": fsize_kb,
            "body_lines": body_lines,
            "description": desc,
        })
    return results


def _load_user_skills_snapshot():
    """
    Live-scan ~/.hermes/skills/ for skill metadata, enriched by audit verdicts
    from skills-audit.json. Falls back to pure live scan if audit cache absent.
    """
    skills_dir = os.path.expanduser("~/.hermes/skills")
    if not os.path.isdir(skills_dir):
        return {"total": 0, "skills": []}

    # Build audit lookup map
    audit_map = {}
    if os.path.exists(SKILLS_AUDIT_CACHE):
        try:
            with open(SKILLS_AUDIT_CACHE, encoding="utf-8") as f:
                audit_data = json.load(f)
            for s in audit_data.get("skills", []):
                name = (s.get("name") or "").lower().replace(" ", "-")
                audit_map[name] = s
        except Exception:
            pass

    skills = _scan_skill_metadata(skills_dir, audit_map)
    return {"total": len(skills), "skills": skills}


def _skill_evolution_focus(skills_snapshot):
    """Return prioritized current-skill improvement focus for the evolution system."""
    skills = skills_snapshot.get("skills", [])
    verdicts = {}
    for s in skills:
        v = s.get("verdict", "REVIEW")
        verdicts[v] = verdicts.get(v, 0) + 1
    priority = sorted(
        skills,
        key=lambda s: (
            0 if s.get("verdict") in ("IMPROVE", "MERGE", "DELETE", "REVIEW") else 1,
            float(s.get("composite") or s.get("rating") or 0),
            -len(s.get("issues") or []),
        ),
    )[:8]
    return {
        "total": len(skills),
        "verdicts": verdicts,
        "needs_work": sum(verdicts.get(v, 0) for v in ("IMPROVE", "MERGE", "DELETE", "REVIEW")),
        "keep": verdicts.get("KEEP", 0),
        "priorities": priority,
    }


def _proposal_skill_impact(body, skill_names):
    """Extract a visible, human-readable impact summary: what this proposal changes in Hermes/skills."""
    lower_body = body.lower()
    matched = []
    for name in skill_names:
        if name and name.lower() in lower_body:
            matched.append(name)
    bullets = []
    keywords = ("技能", "skill", "hermes", "内化", "改进", "改善", "验证", "收益", "落地", "提案", "闭环", "执行")
    for raw in body.split("\n"):
        line = raw.strip().lstrip("-*0123456789. ").strip()
        if not line or line.startswith("#") or len(line) < 8:
            continue
        if any(k in line.lower() for k in keywords):
            bullets.append(line[:160])
        if len(bullets) >= 5:
            break
    scope = "技能内化" if matched or any("技能" in b or "skill" in b.lower() for b in bullets) else "系统提案"
    if "hermes" in lower_body or "进化" in body:
        scope = "Hermes 系统改进" if scope == "系统提案" else "Hermes + 技能内化"
    return {"scope": scope, "target_skills": matched[:6], "bullets": bullets}


@app.route("/api/user-skills")
def api_user_skills():
    """Return user's personal skills with metadata."""
    if not os.path.exists(USER_SKILLS_CACHE):
        return jsonify({"error": "用户技能数据未生成"}), 503
    with open(USER_SKILLS_CACHE, encoding="utf-8") as f:
        data = json.load(f)
    
    # 注入技能文件大小、行数信息
    skills_dir = os.path.expanduser("~/.hermes/skills")
    for s in data.get("skills", []):
        name = s.get("name", "")
        # 查找 SKILL.md
        for root, dirs, files in os.walk(skills_dir):
            if "SKILL.md" in files:
                full = os.path.join(root, "SKILL.md")
                try:
                    with open(full) as f2:
                        content = f2.read()
                    fm = {}
                    if content.startswith("---"):
                        end = content.find("---", 3)
                        if end > 0:
                            fm = yaml.safe_load(content[3:end]) or {}
                    if fm.get("name") == name:
                        stat = os.stat(full)
                        s["size_kb"] = round(stat.st_size / 1024, 1)
                        s["body_lines"] = len([l for l in content.split("\n") if l.strip()])
                        s["category"] = fm.get("category", "")
                        s["version"] = fm.get("version", "")
                        s["file_path"] = os.path.relpath(root, skills_dir)
                        break
                except:
                    pass
    
    return jsonify(data)


VERDICT_LABELS = {
    "KEEP": "✅ 保留 — 质量好，继续维护",
    "IMPROVE": "🔧 需改进 — 有价值但内容/结构需优化",
    "MERGE": "🔀 合并 — 与其他技能重复，应合并",
    "DELETE": "❌ 删除 — 无用/过时/质量差",
    "REVIEW": "🔍 待审查 — 信息不足，需人工判断",
}


def _build_eval_prompt(batch, start_idx, total):
    lines = [
        "你是 Hermes AI 系统的工程经理。请审计以下 Skills（#%d-%d / %d），从工程管理视角评分。"
        % (start_idx, start_idx + len(batch) - 1, total),
        "",
        "评估维度：",
        "1. 内容质量 — SKILL.md 是否完整、清晰、可执行",
        "2. 实用性 — 对系统/用户是否有实际价值",
        "3. 维护状态 — 是否过时、是否有明显错误",
        "4. 工程规范 — 命名、结构、分类是否合理",
        "",
        "判定标准：",
        "- KEEP: 评分 ≥7，质量好",
        "- IMPROVE: 评分 4-6，有价值但需优化",
        "- MERGE: 与同分类其他技能高度重复",
        "- DELETE: 评分 ≤3，无用或过时",
        "- REVIEW: 信息不足",
        "",
        "只输出JSON数组，不要其他文字：",
        "[",
        '  {"name":"skill-name","rating":8,"verdict":"KEEP","reason":"一句话理由(中文)","issues":[]},',
        "]",
        "",
        "--- Skills 列表 ---",
    ]
    for s in batch:
        lines.append(f"名称: {s['name']}")
        lines.append(f"分类: {s['category']}")
        lines.append(f"描述: {s['description'][:150]}")
        lines.append(f"大小: {s['size_kb']}KB · {s['body_lines']}行")
        lines.append("")

    return "\n".join(lines)


def _call_deepseek(prompt):
    """Call DeepSeek API for evaluation."""
    import urllib.request
    # Ensure API key is loaded (reload from .env)
    key = DEEPSEEK_API_KEY
    if not key or key == "***" or len(key) < 20:
        env_file = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_file):
            for line in open(env_file):
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    try:
        data = json.dumps({
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是工程经理。只输出JSON数组，不要markdown包裹。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }).encode()
        req = urllib.request.Request(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
        content = body["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences
        if content.startswith("```"):
            content = content[content.find("\n")+1:]
            if content.endswith("```"):
                content = content[:-3]
        return json.loads(content)
    except Exception as e:
        logger.error(f"DeepSeek eval failed: {e}")
        return None


@app.route("/my/<token>")
def my_dashboard(token):
    user_id = resolve_token(token)
    if not user_id:
        return render_template_string(NOT_FOUND_HTML), 404
    prefs = get_user_prefs(user_id)
    return render_template_string(
        MY_HTML,
        name=prefs.get("name", user_id),
        user_id=user_id,
        token=token,
        models=AVAILABLE_MODELS,
        current_model=normalize_model_id(prefs.get("model", DEFAULT_MODEL_ID)),
        msg=request.args.get("msg", ""),
        err=request.args.get("err", ""),
    )


@app.route("/my/<token>/save", methods=["POST"])
def my_save(token):
    user_id = resolve_token(token)
    if not user_id:
        return render_template_string(NOT_FOUND_HTML), 404
    model = request.form.get("model", DEFAULT_MODEL_ID)
    valid_ids = [m["id"] for m in AVAILABLE_MODELS]
    if model not in valid_ids:
        return redirect(f"/my/{token}?err=❌ 无效的模型 ID")
    prefs = get_user_prefs(user_id)
    prefs["model"] = model
    try:
        save_user_prefs(user_id, prefs)
        logger.info("User %s switched model to %s", user_id, model)
        msg = urllib.parse.quote(f"✅ 模型已切换为 {model}")
        return redirect(f"/my/{token}?msg={msg}")
    except Exception as e:
        logger.error("Failed to save prefs for %s: %s", user_id, e)
        err = urllib.parse.quote(f"❌ 保存失败")
        return redirect(f"/my/{token}?err={err}")


@app.errorhandler(404)
def not_found(e):
    return render_template_string(NOT_FOUND_HTML), 404


@app.errorhandler(413)
def too_large(e):
    return """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>文件太大</title>
<style>
body{font-family:sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{text-align:center}.box h1{font-size:48px;color:#30363d}.box p{color:#8b949e}
</style></head>
<body><div class="box"><h1>413</h1><p>文件大小超过 200MB 限制</p></div></body>
</html>""", 413


# ═══════════════════════════════════════════════════════════════════
# OCR JSON API (no auth required — proxied via Next.js)
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/ocr/upload", methods=["POST"])
def api_ocr_upload():
    """JSON API: upload file(s) for OCR, return task_id(s). Accepts single or multiple files."""
    files = request.files.getlist("files")
    if not files or not files[0].filename:
        return jsonify({"ok": False, "error": "请选择文件"}), 400
    allowed_exts = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    tasks = []
    errors = []
    for f in files:
        if not f.filename:
            continue
        _, ext = os.path.splitext(f.filename.lower())
        if ext not in allowed_exts:
            errors.append(f"{f.filename}: 不支持的格式")
            continue
        safe_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, safe_name)
        try:
            f.save(save_path)
            if os.path.getsize(save_path) > MAX_FILE_SIZE:
                os.remove(save_path)
                errors.append(f"{f.filename}: 文件超过 200MB 限制")
                continue
            logger.info("API OCR upload: %s (%s)", safe_name, f.filename)
        except Exception as e:
            logger.error("API OCR upload failed %s: %s", f.filename, e)
            errors.append(f"{f.filename}: 上传失败")
            continue
        public_url = f"{PUBLIC_DOMAIN}/f/{safe_name}"
        mineru_url = f"{MINERU_FILE_BASE}/f/{safe_name}"
        task_id, error = submit_mineru_task(mineru_url, f.filename)
        if error:
            errors.append(f"{f.filename}: {error}")
        else:
            tasks.append({"task_id": task_id, "file_name": f.filename})
    if not tasks:
        err_msg = "; ".join(errors) if errors else "没有可处理的文件"
        return jsonify({"ok": False, "error": err_msg}), 400
    # Return first task for single-file, or list for multi-file
    result = {"ok": True, "tasks": tasks, "errors": errors if errors else None}
    if len(tasks) == 1:
        result["task_id"] = tasks[0]["task_id"]
        result["file_name"] = tasks[0]["file_name"]
    return jsonify(result)


@app.route("/api/ocr/status/<task_id>")
def api_ocr_status(task_id):
    """JSON API: poll OCR task status (no auth required)."""
    if not task_id or not all(c.isalnum() or c in "-_" for c in task_id):
        return jsonify({"status": "failed", "error": "无效的任务 ID"}), 400
    state, result, error = poll_mineru_task(task_id)
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    if state == "done" and result:
        return jsonify({
            "status": "completed",
            "result": {
                "markdown": result.get("markdown", ""),
                "pages": result.get("pages", 0),
                "file_name": result.get("file_name", ""),
                "file_size": result.get("file_size", 0),
                "char_count": len(result.get("markdown", "")),
                "full_md_link": result.get("full_md_link", ""),
                "full_zip_url": result.get("full_zip_url", ""),
            }
        }), 200, headers
    elif error:
        return jsonify({"status": "failed", "error": error}), 200, headers
    else:
        # Map MinerU states to our normalized states
        normalized = state
        if state in ("submitted", "queued", "waiting"):
            normalized = "pending"
        elif state in ("running", "processing"):
            normalized = "processing"
        return jsonify({"status": normalized}), 200, headers


# ── OCR History ──────────────────────────────────────────────────────
OCR_HISTORY_PATH = "/root/gateway-dashboard/ocr_history.json"
_ocr_history_lock = threading.Lock()


def load_ocr_history():
    try:
        with open(OCR_HISTORY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_ocr_history(entries):
    tmp = OCR_HISTORY_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, OCR_HISTORY_PATH)
    except Exception as e:
        logger.warning("Failed to save OCR history: %s", e)


@app.route("/api/ocr/save", methods=["POST"])
def api_ocr_save():
    """Save an OCR result to history."""
    data = request.get_json(silent=True)
    if not data or "result" not in data:
        return jsonify({"ok": False, "error": "缺少 result 字段"}), 400
    r = data["result"]
    record_id = uuid.uuid4().hex
    ts = time.time()
    created_at = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "id": record_id,
        "file_name": r.get("file_name", ""),
        "file_size": r.get("file_size", 0),
        "pages": r.get("pages", 0),
        "char_count": r.get("char_count", 0),
        "markdown": r.get("markdown", ""),
        "full_md_link": r.get("full_md_link", ""),
        "full_zip_url": r.get("full_zip_url", ""),
        "ts": ts,
        "created_at": created_at,
    }
    with _ocr_history_lock:
        entries = load_ocr_history()
        entries.append(record)
        if len(entries) > 500:
            entries = entries[-500:]
        save_ocr_history(entries)
    logger.info("OCR history saved: %s (%s)", record_id, record["file_name"])
    return jsonify({"ok": True, "id": record_id})


@app.route("/api/ocr/history")
def api_ocr_history():
    """List OCR history (metadata only, max 50, reverse chronological)."""
    with _ocr_history_lock:
        entries = load_ocr_history()
    entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    result = []
    for e in entries[:50]:
        result.append({
            "id": e["id"],
            "file_name": e.get("file_name", ""),
            "file_size": e.get("file_size", 0),
            "pages": e.get("pages", 0),
            "char_count": e.get("char_count", 0),
            "full_md_link": e.get("full_md_link", ""),
            "full_zip_url": e.get("full_zip_url", ""),
            "ts": e.get("ts", 0),
            "created_at": e.get("created_at", ""),
        })
    return jsonify({"ok": True, "data": result})


@app.route("/api/ocr/history/<record_id>")
def api_ocr_history_detail(record_id):
    """Get a single OCR history record with full content."""
    with _ocr_history_lock:
        entries = load_ocr_history()
    for e in entries:
        if e.get("id") == record_id:
            return jsonify({"ok": True, "data": e})
    return jsonify({"ok": False, "error": "记录未找到"}), 404


# ═══════════════════════════════════════════════════════════════════
# OCR ROUTES (HTML pages — require auth)
# ═══════════════════════════════════════════════════════════════════

@app.route("/ocr", methods=["GET", "POST"])
def ocr_page():
    """OCR document recognition page with MinerU API."""
    if request.method == "POST":
        files = request.files.getlist("files")
        if not files or not files[0].filename:
            return render_template_string(OCR_HTML, err="❌ 请选择文件")
        allowed_exts = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
        tasks = []
        errors = []
        for f in files:
            if not f.filename:
                continue
            _, ext = os.path.splitext(f.filename.lower())
            if ext not in allowed_exts:
                errors.append(f"❌ {f.filename}: 不支持的格式")
                continue
            safe_name = f"{uuid.uuid4().hex}{ext}"
            save_path = os.path.join(UPLOAD_DIR, safe_name)
            try:
                f.save(save_path)
                # Check saved file size
                if os.path.getsize(save_path) > MAX_FILE_SIZE:
                    os.remove(save_path)
                    errors.append(f"❌ {f.filename}: 文件超过 200MB 限制")
                    continue
                logger.info("OCR file uploaded: %s (%s)", safe_name, f.filename)
            except Exception as e:
                logger.error("OCR upload failed %s: %s", f.filename, e)
                errors.append(f"❌ {f.filename}: 上传失败")
                continue
            public_url = f"{PUBLIC_DOMAIN}/f/{safe_name}"
            # Use HTTP for MinerU to pull the file (self-signed cert issue)
            mineru_url = f"{MINERU_FILE_BASE}/f/{safe_name}"
            task_id, error = submit_mineru_task(mineru_url, f.filename)
            if error:
                errors.append(f"❌ {f.filename}: {error}")
            else:
                tasks.append({"task_id": task_id, "file_name": f.filename, "state": "submitted"})
        if not tasks:
            err_msg = "; ".join(errors) if errors else "❌ 没有可处理的文件"
            return redirect(url_for("ocr_page", err=err_msg))
        # PRG: redirect to GET with task IDs so page state survives refresh
        tids = ",".join(t["task_id"] for t in tasks)
        return redirect(url_for("ocr_page", tasks=tids, err="; ".join(errors) if errors else ""))
    # GET request
    tasks_param = request.args.get("tasks", "")
    task_id = request.args.get("task_id", "")
    err = request.args.get("err", "")
    msg = request.args.get("msg", "")
    tasks = []
    result_data = None
    if tasks_param:
        for tid in tasks_param.split(","):
            if not tid.strip():
                continue
            tasks.append({"task_id": tid, "file_name": "", "state": "submitted"})
            # Server-side check: if task is done, include result directly in page
            if not result_data:
                state, res, _ = poll_mineru_task(tid.strip())
                if state == "done" and res:
                    result_data = res
    return render_template_string(OCR_HTML, tasks=tasks, result=result_data, err=err, msg=msg)


@app.route("/ocr/status/<task_id>")
def ocr_status(task_id):
    """Poll MinerU task status (JSON endpoint)."""
    # Validate task_id: only allow alphanumeric, hyphens, underscores
    if not task_id or not all(c.isalnum() or c in "-_" for c in task_id):
        return jsonify({"state": "failed", "error": "无效的任务 ID"}), 400
    state, result, error = poll_mineru_task(task_id)
    # Prevent browser caching of polling responses
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    if state == "done" and result:
        return jsonify(result), 200, headers
    elif error:
        return jsonify({"state": "failed", "error": error}), 200, headers
    else:
        return jsonify({"state": state}), 200, headers


@app.route("/ocr/analyze", methods=["POST"])
def ocr_analyze():
    """Analyze OCR markdown for shortcomings - single call with full context."""
    data = request.get_json()
    full_md = (data or {}).get("markdown", "")
    file_name = (data or {}).get("file_name", "文档")
    total_pages = (data or {}).get("pages", 1)
    if not full_md or len(full_md) < 10:
        return jsonify({"html": "<p style='color:#8b949e'>缺少识别内容，无法分析。</p>"})

    # Send full content (truncate reasonably for token limits)
    md_for_analysis = full_md[:12000]
    if len(full_md) > 12000:
        md_for_analysis += "\n\n...（过长截断）"

    prompt = f"""你是一个专业的 OCR 识别质量评估专家。请分析以下 OCR 识别结果。

文件：{file_name}，共 {total_pages} 页。
{'' if total_pages <= 1 else f'请按页分别评估，每页列出 2-4 个具体问题。'}

OCR 识别结果：
```
{md_for_analysis}
```

分析维度：
1. **字符识别错误**：乱码、错别字、数字符号错误
2. **遗漏内容**：缺失的文字、段落、数据
3. **格式/结构**：标题层级、段落完整性
4. **图片/表格**：图片说明、公式、表格数据可读性
5. **整体可信度**：综合评分

输出纯 HTML（不要 ``` 包裹），用 <ul><li> 列表，严重程度用 🔴 🟡 🟢 标注。
{'每页用 <li style="list-style:none"><strong style="color:#58a6ff">📄 第X页</strong></li> 作为页分隔。' if total_pages > 1 else ''}
如果某页质量好，也如实写"无明显问题"。"""

    body = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 4000,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        )
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        reply = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})
        record_token_usage("deepseek-v4-flash",
                           usage.get("prompt_tokens", 0),
                           usage.get("completion_tokens", 0),
                           "ocr_analyze")
        if reply.startswith("```"):
            reply = reply.split("\n", 1)[-1]
        if reply.endswith("```"):
            reply = reply.rsplit("```", 1)[0]
        reply = reply.strip()
        if not reply.startswith("<"):
            reply = f"<ul>{reply}</ul>"
        return jsonify({"html": reply})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")[:200]
        logger.error("DeepSeek analyze error %d: %s", e.code, err_body)
        return jsonify({"html": f"<p style='color:#f85149'>分析失败: {e.code}</p>"})
    except Exception as e:
        logger.error("OCR analyze failed: %s", e)
        return jsonify({"html": f"<p style='color:#8b949e'>分析异常: {e}</p>"})


# ═══════════════════════════════════════════════════════════════════
# EVOLUTION LOG — Hermes 自主学习报告
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/evolution")
@require_auth
def api_evolution():
    """Return learning report list + latest report content + proposals."""
    learn_dir = os.path.expanduser("~/.hermes/learnings")
    skills_snapshot = _load_user_skills_snapshot()
    skill_focus = _skill_evolution_focus(skills_snapshot)
    skill_names = [s.get("name", "") for s in skills_snapshot.get("skills", [])]
    reports = []
    if os.path.isdir(learn_dir):
        for f in sorted(os.listdir(learn_dir), reverse=True):
            if f.endswith(".md") and f != "INDEX.md":
                path = os.path.join(learn_dir, f)
                size = os.path.getsize(path)
                reports.append({
                    "date": f.replace(".md", ""),
                    "size": size,
                    "size_kb": round(size / 1024, 1),
                })

    # Load latest report content
    latest_content = ""
    if reports:
        latest_path = os.path.join(learn_dir, reports[0]["date"] + ".md")
        try:
            with open(latest_path) as fp:
                latest_content = fp.read()
        except Exception:
            pass

    # Load specific date if requested (safe: only allow YYYY-MM-DD format)
    req_date = request.args.get("date", "")
    if req_date:
        import re
        if re.match(r'^\d{4}-\d{2}-\d{2}$', req_date):
            date_path = os.path.join(learn_dir, req_date + ".md")
            if os.path.isfile(date_path):
                try:
                    with open(date_path, encoding="utf-8") as fp:
                        latest_content = fp.read()
                except Exception:
                    pass

    # Load proposals
    proposals = []
    proposals_dir = os.path.expanduser("~/.hermes/proposals")
    if os.path.isdir(proposals_dir):
        for fname in sorted(os.listdir(proposals_dir), reverse=True):
            if fname in ("INDEX.md", "TEMPLATE.md") or not fname.endswith(".md"):
                continue
            fpath = os.path.join(proposals_dir, fname)
            try:
                with open(fpath) as fp:
                    pcontent = fp.read()
            except Exception:
                continue
            meta, body = _parse_proposal_frontmatter(pcontent)
            pstatus = meta.get("status", "unknown")
            prisk = meta.get("risk", "unknown")
            try:
                pscore = int(meta.get("score", "0"))
            except Exception:
                pscore = 0
            psource = meta.get("source_report", "")
            purl = meta.get("source_url", "")
            actions = _extract_proposal_actions(body)
            impact = _proposal_skill_impact(body, skill_names)
            # Extract title
            ptitle = "未命名"
            for line in pcontent.split("\n"):
                if line.startswith("# "):
                    ptitle = line[2:].replace("📋 ", "").strip()[:80]
                    break
            proposals.append({
                "file": fname,
                "status": pstatus,
                "risk": prisk,
                "score": pscore,
                "title": ptitle,
                "source": psource,
                "url": purl,
                "action_count": len(actions),
                "impact": impact,
                "impact_scope": impact.get("scope", "系统提案"),
                "target_skills": impact.get("target_skills", []),
                "impact_bullets": impact.get("bullets", []),
                "last_event": _proposal_last_event(pcontent),
                "approved_at": meta.get("approved_at", ""),
                "implemented_at": meta.get("implemented_at", ""),
                "verified_at": meta.get("verified_at", ""),
                "exec_status": pexec.get_running_status(fname),
            })

    return jsonify({
        "reports": reports[:30],
        "total": len(reports),
        "latest": latest_content,
        "constitution_exists": os.path.exists(os.path.expanduser("~/.hermes/CONSTITUTION.md")),
        "proposals": proposals,
        "skills": skills_snapshot,
        "skill_focus": skill_focus,
    })


def _hermes_proposal_path(filename):
    """Return safe proposal path under ~/.hermes/proposals."""
    safe = os.path.basename(filename)
    if not safe.endswith(".md"):
        safe += ".md"
    proposals_dir = os.path.expanduser("~/.hermes/proposals")
    return safe, os.path.join(proposals_dir, safe)


def _update_proposal_frontmatter(content, updates):
    """Update or create simple YAML frontmatter keys in a proposal file."""
    body = content
    values = {}
    order = []
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            frontmatter = content[3:end]
            body = content[end + 3:]
            for line in frontmatter.split("\n"):
                if not line.strip():
                    continue
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    values[key] = value.strip()
                    order.append(key)
    for key, value in updates.items():
        if key not in order:
            order.append(key)
        values[key] = value
    fm = "\n".join(f"{key}: {values.get(key, '')}" for key in order)
    return f"---\n{fm}\n---{body}"


def _append_proposal_event(content, title, note=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M CST")
    content = content.rstrip() + f"\n\n## {title} ({now})\n"
    if note:
        content += f"\n> {note}\n"
    return content


def _atomic_write_text(path, content):
    """Atomically write UTF-8 text so proposal state never becomes half-written."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        fp.write(content)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)


def _parse_proposal_frontmatter(content):
    """Parse the simple proposal YAML frontmatter used by the learner."""
    values = {}
    body = content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            body = content[end + 3:]
            for line in content[3:end].split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    values[key.strip()] = value.strip()
    return values, body


def _extract_proposal_actions(body):
    """Extract actionable bullets from historical and current proposal formats."""
    actions = []
    in_action_section = False
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            in_action_section = any(token in line for token in ("行动", "实施", "建议", "落地", "Action"))
            continue
        if not line.startswith(("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ")):
            continue
        text = line[2:].strip() if line[:2] in ("- ", "* ") else line[3:].strip()
        if text.startswith("**") and "**" in text[2:]:
            text = text[2:].split("**", 1)[0].strip()
        actionable_hint = any(token in line for token in ("收益", "工作量", "验证", "实施", "改造", "新增", "修复", "接入", "落地"))
        if in_action_section or actionable_hint:
            text = text[:140]
            if text and text not in actions:
                actions.append(text)
    return actions


def _proposal_last_event(content):
    last = ""
    for line in content.split("\n"):
        if line.startswith("## ") and any(icon in line for icon in ("✅", "❌", "⚡", "🚀", "⏭")):
            last = line[3:].strip()
    return last


@app.route("/admin/evolution")
@require_auth
def admin_evolution():
    return redirect("http://127.0.0.1:3000/admin/evolution", code=302)


@app.route("/api/proposal/<filename>/approve", methods=["POST"])
@require_auth
def api_proposal_approve(filename):
    """Approve/reject a proposal — updates YAML frontmatter status."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "")
    comment = data.get("comment", "").strip()
    if new_status not in ("approved", "rejected"):
        return jsonify({"error": "status must be approved or rejected"}), 400

    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        updates = {"status": new_status}
        if new_status == "approved":
            updates["approved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        content = _update_proposal_frontmatter(content, updates)
        status_label = {"approved": "✅ 已通过", "rejected": "❌ 已拒绝"}[new_status]
        content = _append_proposal_event(content, status_label, comment)
        _atomic_write_text(fpath, content)
        logger.info("Proposal %s %s", safe, new_status)
        return jsonify({"ok": True, "status": new_status})
    except Exception as e:
        logger.error("Failed to approve proposal %s: %s", safe, e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/proposal/<filename>/implement", methods=["POST"])
@require_auth
def api_proposal_implement(filename):
    """Mark an approved proposal as implemented (implementation is tracked in file history)."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    note = data.get("note", "").strip()
    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        meta, _body = _parse_proposal_frontmatter(content)
        current_status = meta.get("status", "unknown")
        if current_status not in ("approved", "implementing", "failed"):
            return jsonify({
                "ok": False,
                "error": f"proposal status is '{current_status}', must be approved/implementing/failed before marking implemented",
            }), 400
        content = _update_proposal_frontmatter(content, {
            "status": "implemented",
            "implemented_at": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        content = _append_proposal_event(content, "🚀 已实施", note or "提案已进入实施完成状态，等待验证。")
        _atomic_write_text(fpath, content)
        logger.info("Proposal %s implemented", safe)
        return jsonify({"ok": True, "status": "implemented"})
    except Exception as e:
        logger.error("Failed to implement proposal %s: %s", safe, e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/proposal/<filename>/verify", methods=["POST"])
@require_auth
def api_proposal_verify(filename):
    """Mark an implemented proposal as verified or failed."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    ok = bool(data.get("ok", True))
    note = data.get("note", "").strip()
    new_status = "verified" if ok else "failed"
    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        meta, _body = _parse_proposal_frontmatter(content)
        current_status = meta.get("status", "unknown")
        if current_status != "implemented":
            return jsonify({
                "ok": False,
                "error": f"proposal status is '{current_status}', must be implemented before manual verify/fail",
            }), 400
        content = _update_proposal_frontmatter(content, {
            "status": new_status,
            "verified_at": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        content = _append_proposal_event(content, "✅ 验证通过" if ok else "❌ 验证失败", note)
        _atomic_write_text(fpath, content)
        logger.info("Proposal %s verified as %s", safe, new_status)
        return jsonify({"ok": True, "status": new_status})
    except Exception as e:
        logger.error("Failed to verify proposal %s: %s", safe, e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/proposal/<filename>/exec", methods=["POST"])
@require_auth
def api_proposal_exec(filename):
    """Auto-execute an approved proposal using the background executor.
    Spawns a real background thread that runs all actions + auto-validator.
    """
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "not found"}), 404

    ok, message = pexec.start_execution(safe)
    if not ok:
        return jsonify({"ok": False, "error": message}), 400

    # Re-read to get latest status
    try:
        with open(fpath, encoding="utf-8") as fp:
            updated_content = fp.read()
        meta, body = _parse_proposal_frontmatter(updated_content)
        actions = _extract_proposal_actions(body)
        return jsonify({
            "ok": True,
            "status": "implementing",
            "actions": actions,
            "count": len(actions),
            "message": message,
        })
    except Exception as e:
        return jsonify({"ok": True, "status": "implementing", "message": message})


@app.route("/api/proposal/<filename>/exec-logs", methods=["GET"])
@require_auth
def api_proposal_exec_logs(filename):
    """Return execution logs for a proposal."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "not found"}), 404
    logs = pexec.read_exec_logs(safe)
    summary = pexec.get_exec_summary(safe)
    running_raw = pexec.get_running_status(safe)
    return jsonify({
        "logs": logs,
        "summary": summary,
        "running": running_raw,
        "is_running": running_raw == "running",
    })


@app.route("/api/proposal/<filename>/auto-verify", methods=["POST"])
@require_auth
def api_proposal_auto_verify(filename):
    """Manually trigger auto-validator on an implemented proposal."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "not found"}), 404

    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        meta, _body = _parse_proposal_frontmatter(content)
        current_status = meta.get("status", "unknown")
        if current_status not in ("implementing", "implemented", "failed"):
            return jsonify({
                "ok": False,
                "error": f"proposal status is '{current_status}', must be implementing/implemented/failed before auto-verify",
            }), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    ok, all_passed, checks = pexec.run_verify(safe)
    if not ok:
        return jsonify({"ok": False, "error": "验证执行失败"}), 500

    return jsonify({
        "ok": True,
        "passed": all_passed,
        "status": "verified" if all_passed else "failed",
        "checks": checks,
    })


@app.route("/api/proposal/<filename>/impact", methods=["GET"])
@require_auth
def api_proposal_impact(filename):
    """Get feedback-loop impact assessment for a proposal."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": "not found"}), 404

    # Load impact from executor
    impact = pexec.feedback_get_impact(safe)
    if impact is None:
        return jsonify({"ok": True, "has_data": False, "impact": None})

    # Load before/after snapshots for UI display
    log_dir = os.path.expanduser(f"~/.hermes/proposal_executor/{safe.replace('.md', '')}")
    before = {}
    after = {}
    try:
        bpath = os.path.join(log_dir, "before_snapshot.json")
        if os.path.isfile(bpath):
            with open(bpath) as fp:
                before = json.load(fp)
    except Exception:
        pass
    try:
        apath = os.path.join(log_dir, "after_snapshot.json")
        if os.path.isfile(apath):
            with open(apath) as fp:
                after = json.load(fp)
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "has_data": True,
        "impact": impact,
        "before": before,
        "after": after,
    })


@app.route("/api/constitution", methods=["GET", "POST"])
@require_auth
def api_constitution():
    """Read or update Hermes constitution."""
    cpath = os.path.expanduser("~/.hermes/CONSTITUTION.md")
    if request.method == "GET":
        if not os.path.isfile(cpath):
            return jsonify({"exists": False, "content": ""})
        try:
            with open(cpath, encoding="utf-8") as fp:
                return jsonify({"exists": True, "content": fp.read()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    try:
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        with open(cpath, "w", encoding="utf-8") as fp:
            fp.write(content)
        logger.info("Hermes constitution updated (%d bytes)", len(content))
        return jsonify({"ok": True, "exists": True, "size": len(content)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/proposal/<filename>/defer", methods=["POST"])
@require_auth
def api_proposal_defer(filename):
    """Defer a pending proposal."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    note = data.get("comment", data.get("note", "")).strip()
    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        content = _update_proposal_frontmatter(content, {"status": "deferred"})
        content = _append_proposal_event(content, "⏭️ 已搁置", note or "提案暂时搁置，等待条件成熟后再审。")
        _atomic_write_text(fpath, content)
        return jsonify({"ok": True, "status": "deferred"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/skill/internalize", methods=["POST"])
@require_auth
def api_skill_internalize():
    """Create a proposal for internalizing a skill (improving its SKILL.md)."""
    try:
        data = request.get_json(force=True) or {}
        skill_name = (data.get("name") or "").strip()
        if not skill_name:
            return jsonify({"error": "缺少技能名称"}), 400

        # Read current SKILL.md
        skill_path = os.path.expanduser(f"~/.hermes/skills/{skill_name}/SKILL.md")
        if not os.path.exists(skill_path):
            return jsonify({"error": f"技能 {skill_name} 不存在"}), 404

        with open(skill_path, encoding="utf-8") as f:
            current_content = f.read()

        fsize_kb = round(os.path.getsize(skill_path) / 1024, 1)
        body_lines = current_content.count("\n") + 1

        # Create proposal
        proposals_dir = os.path.expanduser("~/.hermes/proposals")
        os.makedirs(proposals_dir, exist_ok=True)

        now = datetime.datetime.now()
        fname = f"skill-internalize-{skill_name}-{now.strftime('%Y%m%d-%H%M%S')}.md"
        fpath = os.path.join(proposals_dir, fname)

        proposal_body = f"""---
status: pending
risk: medium
score: 7
skill: {skill_name}
current_size: {fsize_kb}KB
current_lines: {body_lines}
created_at: {now.isoformat()}
---

# 📋 技能内化：{skill_name}

## 当前状态

- 技能：{skill_name}
- 文件大小：{fsize_kb}KB，{body_lines} 行

## 内化目标

1. **补齐触发条件** — 确保技能在相关场景下能被正确触发
2. **完善步骤** — 补充缺失的操作步骤和细节
3. **添加坑点** — 记录使用中可能遇到的问题和解决方案
4. **增加验证方式** — 添加执行后的验证/检查步骤

## 实施路径

- [ ] 审查当前 SKILL.md，识别缺失部分
- [ ] 按内化目标逐一补全
- [ ] 写回技能质量分（重新审计）
- [ ] 验证技能文档完整性
"""
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(proposal_body)

        return jsonify({"ok": True, "proposal": fname, "skill": skill_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/evolution/stats")
@require_auth
def api_evolution_stats():
    """Return aggregated evolution system statistics."""
    learn_dir = os.path.expanduser("~/.hermes/learnings")
    proposals_dir = os.path.expanduser("~/.hermes/proposals")
    stats = {
        "reports": 0,
        "proposals": 0,
        "constitution_exists": os.path.exists(os.path.expanduser("~/.hermes/CONSTITUTION.md")),
        "status": {},
        "risk": {},
        "score_avg": 0,
        "actionable": 0,
        "blocked": 0,
        "last_verified": "",
    }
    if os.path.isdir(learn_dir):
        stats["reports"] = len([f for f in os.listdir(learn_dir) if f.endswith(".md") and f != "INDEX.md"])
    scores = []
    last_verified = []
    if os.path.isdir(proposals_dir):
        for fname in os.listdir(proposals_dir):
            if fname in ("INDEX.md", "TEMPLATE.md") or not fname.endswith(".md"):
                continue
            stats["proposals"] += 1
            try:
                with open(os.path.join(proposals_dir, fname), encoding="utf-8") as fp:
                    content = fp.read()
                meta, body = _parse_proposal_frontmatter(content)
                status = meta.get("status", "unknown")
                risk = meta.get("risk", "unknown")
                stats["status"][status] = stats["status"].get(status, 0) + 1
                stats["risk"][risk] = stats["risk"].get(risk, 0) + 1
                try:
                    scores.append(int(meta.get("score", "0")))
                except Exception:
                    pass
                action_count = len(_extract_proposal_actions(body))
                if status == "approved" and action_count:
                    stats["actionable"] += 1
                if status == "approved" and not action_count:
                    stats["blocked"] += 1
                if meta.get("verified_at") and meta.get("verified_at") != "~":
                    last_verified.append(meta.get("verified_at"))
            except Exception:
                continue
    stats["score_avg"] = round(sum(scores) / len(scores), 1) if scores else 0
    stats["last_verified"] = sorted(last_verified)[-1] if last_verified else ""
    return jsonify(stats)


@app.route("/api/proposal/<filename>")
@require_auth
def api_proposal(filename):
    """Return single proposal markdown content plus parsed metadata."""
    safe, fpath = _hermes_proposal_path(filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "not found"}), 404
    try:
        with open(fpath, encoding="utf-8") as fp:
            content = fp.read()
        meta, body = _parse_proposal_frontmatter(content)
        exec_status = pexec.get_running_status(safe)
        exec_summary = pexec.get_exec_summary(safe)
        return jsonify({
            "file": safe,
            "content": content,
            "meta": meta,
            "actions": _extract_proposal_actions(body),
            "last_event": _proposal_last_event(content),
            "exec_status": exec_status,
            "exec_summary": exec_summary,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


EVOLUTION_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>进化日志 — Hermes</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}
.nav-bar{position:fixed;top:0;left:0;right:0;background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;justify-content:center;gap:20px;font-size:13px;z-index:10}
.nav-bar a{color:#8b949e;text-decoration:none}
.nav-bar a:hover{color:#58a6ff}
.nav-bar a.active{color:#58a6ff;font-weight:600}
.container{max-width:900px;margin:0 auto;padding:70px 20px 40px}
h1{color:#f0f6fc;font-size:22px;margin-bottom:8px}
.sub{color:#8b949e;font-size:13px;margin-bottom:24px}
.report-list{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px}
.report-btn{background:#161b22;border:1px solid #30363d;color:#8b949e;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;transition:all .15s}
.report-btn:hover{border-color:#58a6ff;color:#58a6ff}
.report-btn.active{background:rgba(88,166,255,.1);border-color:#58a6ff;color:#58a6ff}
.report-content{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;line-height:1.7;font-size:14px;white-space:pre-wrap;word-break:break-word}
.report-content h1{font-size:20px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #30363d}
.report-content h2{font-size:16px;color:#58a6ff;margin:20px 0 12px}
.report-content h3{font-size:14px;color:#f0f6fc;margin:16px 0 8px}
.report-content a{color:#58a6ff}
.report-content blockquote{color:#8b949e;border-left:3px solid #30363d;padding-left:12px;margin:8px 0}
.report-content code{background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:1px 5px;font-size:13px;color:#d2a8ff}
.report-content hr{border:0;border-top:1px solid #30363d;margin:16px 0}
.loading{text-align:center;color:#484f58;padding:60px;font-size:14px}
.empty{text-align:center;color:#484f58;padding:60px}
.empty-icon{font-size:48px;margin-bottom:12px}
.meta{display:flex;gap:16px;color:#484f58;font-size:12px;margin-bottom:4px}
.sidebar{display:flex;gap:24px;margin-top:8px}
.main-col{flex:1}
.info-col{width:200px;flex-shrink:0}
.info-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:12px;font-size:12px}
.info-card h3{font-size:13px;color:#f0f6fc;margin-bottom:8px}
.info-card .stat{color:#58a6ff;font-size:18px;font-weight:600}
</style>
</head>
<body>
<div class="nav-bar">
<a href="/">🏠 首页</a>
<a href="/gateway">📊 状态面板</a>

<a href="/upload">📁 文件上传</a>
<a href="/ocr">📄 OCR</a>
<a href="/admin">⚙️ 管理</a>
<a href="/admin/evolution" class="active">🧠 进化日志</a>
</div>
<div class="container">
<h1>🧠 进化日志</h1>
<p class="sub">Hermes 自主学习引擎 · 每日 AI HOT + GitHub 扫描</p>

<div class="sidebar">
<div class="main-col">
  <div class="report-list" id="reportList"></div>
  <div class="report-content" id="reportContent">
    <div class="loading">加载中...</div>
  </div>
</div>
<div class="info-col">
  <div class="info-card">
    <h3>📊 数据源</h3>
    <p style="color:#8b949e;line-height:1.6">
      🔥 <a href="https://aihot.virxact.com" style="color:#58a6ff">AI HOT</a><br>
      💻 GitHub Hermes<br>
      <span style="color:#484f58;font-size:11px">每日 08:30 自动执行</span>
    </p>
  </div>
  <div class="info-card">
    <h3>📜 宪法</h3>
    <p style="color:#8b949e" id="constitutionStatus">检查中...</p>
  </div>
  <div class="info-card">
    <h3>📈 累计</h3>
    <div class="stat" id="totalReports">-</div>
    <p style="color:#484f58">份报告</p>
  </div>
</div>
</div>
</div>

<script>
var currentDate = null;

function loadReports() {
  fetch('/api/evolution?_=' + Date.now())
    .then(function(r) { return r.json(); })
    .then(function(data) {
      // Update report list
      var list = document.getElementById('reportList');
      list.innerHTML = '';
      if (!data.reports.length) {
        document.getElementById('reportContent').innerHTML =
          '<div class="empty"><div class="empty-icon">📭</div>暂无学习报告<br><span style="font-size:12px;color:#484f58">首次扫描将在明天 08:30 自动执行</span></div>';
      } else {
        data.reports.forEach(function(r, i) {
          var btn = document.createElement('button');
          btn.className = 'report-btn' + (i === 0 ? ' active' : '');
          btn.textContent = r.date;
          btn.onclick = function() { showReport(r.date); };
          list.appendChild(btn);
        });
        // Show latest
        if (data.latest && data.reports.length) {
          showReportContent(data.latest);
          currentDate = data.reports[0].date;
        }
      }

      // Update stats
      document.getElementById('totalReports').textContent = data.total;
      document.getElementById('constitutionStatus').innerHTML =
        data.constitution_exists ? '✅ 已启用' : '⚠️ 未配置';
    })
    .catch(function() {
      document.getElementById('reportContent').innerHTML =
        '<div class="empty"><div class="empty-icon">⚠️</div>加载失败</div>';
    });
}

function showReport(date) {
  if (date === currentDate) return;
  // Fetch specific report
  fetch('/api/evolution?date=' + date + '&_=' + Date.now())
    .then(function(r) { return r.json(); })
    .then(function(data) {
      showReportContent(data.latest);
      currentDate = date;
      // Update active button
      document.querySelectorAll('.report-btn').forEach(function(b) {
        b.classList.toggle('active', b.textContent === date);
      });
    });
}

function showReportContent(md) {
  var el = document.getElementById('reportContent');
  // Simple markdown → HTML
  var html = md
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/---/g, '<hr>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');
  el.innerHTML = '<p>' + html + '</p>';
}

loadReports();
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/bot/qrcode")
@require_auth
def api_bot_qrcode():
    """Get a fresh bot registration QR code from iLink."""
    try:
        data = _ilink_get_json("/ilink/bot/get_bot_qrcode?bot_type=3")
        qr = _normalize_bot_qr(data)
        if not qr.get("qr_value") or not qr.get("qr_target_url"):
            return jsonify({"error": "invalid iLink QR response", "raw": data}), 502
        return jsonify(qr)
    except Exception as e:
        logger.warning("Failed to fetch bot registration QR: %s", e)
        return jsonify({"error": str(e)}), 502
@app.route("/api/bot/qr-status")
@require_auth
def api_bot_qr_status():
    """Poll QR code scan status."""
    qrcode = request.args.get("qrcode", "").strip()
    if not qrcode:
        return jsonify({"error": "missing qrcode"}), 400
    try:
        path = "/ilink/bot/get_qrcode_status?qrcode=" + urllib.parse.quote(qrcode, safe="")
        data = _ilink_get_json(path)
        return jsonify(_normalize_bot_qr_status(data))
    except Exception as e:
        logger.warning("Failed to check bot QR status: %s", e)
        return jsonify({"error": str(e)}), 502
@app.route("/api/bot/register", methods=["POST"])
@require_auth
def api_bot_register():
    """Complete bot registration: create Hermes profile + install/start gateway."""
    body = request.get_json(silent=True) or {}
    qrcode = (body.get("qrcode") or "").strip()
    if not qrcode:
        return jsonify({"error": "missing qrcode"}), 400

    with _register_lock:
        if qrcode in _active_registrations:
            return jsonify({"ok": False, "error": "注册正在进行中，请勿重复提交"}), 409
        _active_registrations.add(qrcode)

    try:
        path = "/ilink/bot/get_qrcode_status?qrcode=" + urllib.parse.quote(qrcode, safe="")
        data = _ilink_get_json(path)
        normalized = _normalize_bot_qr_status(data)

        if normalized.get("status") != "confirmed":
            return jsonify({
                "ok": False,
                "error": "请先在手机上确认扫码",
                "status": normalized.get("status", "wait"),
            })

        ilink_bot_id = normalized.get("ilink_bot_id", "")
        bot_token = normalized.get("bot_token", "")
        baseurl = normalized.get("baseurl", "")
        ilink_user_id = normalized.get("ilink_user_id", "")

        if not ilink_bot_id or not bot_token:
            return jsonify({"ok": False, "error": "iLink 未返回 bot 凭证"}), 502

        # Create unique profile name
        short_id = ilink_bot_id.replace("@im.bot", "").replace("@", "").split(":")[0][:16]
        profile_name = "wx_" + short_id

        if not _is_safe_profile_name(profile_name):
            return jsonify({"ok": False, "error": "无效的 profile 名称: " + profile_name}), 400

        # Get default DeepSeek key from current env
        ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not ds_key:
            try:
                with open(os.path.expanduser("~/.hermes/.env")) as f:
                    for line in f:
                        if line.startswith("DEEPSEEK_API_KEY="):
                            ds_key = line.strip().split("=", 1)[1].strip()
                            break
            except Exception:
                pass

        # Check if profile already exists — exact match (not substring)
        existing = subprocess.run(
            ["/root/.local/bin/hermes", "profile", "list"],
            capture_output=True, text=True, timeout=10
        )
        existing_profiles = set()
        for line in existing.stdout.strip().split("\n"):
            parts = line.split()
            if parts:
                existing_profiles.add(parts[0])

        profile_exists = profile_name in existing_profiles

        profile_dir = os.path.expanduser(f"~/.hermes/profiles/{profile_name}")

        if profile_exists:
            # Read existing .env, compare WEIXIN_ACCOUNT_ID
            env_path = os.path.join(profile_dir, ".env")
            existing_account_id = ""
            existing_home = ""
            if os.path.exists(env_path):
                try:
                    with open(env_path) as f:
                        for line in f:
                            if line.startswith("WEIXIN_ACCOUNT_ID="):
                                existing_account_id = line.strip().split("=", 1)[1].strip()
                            elif line.startswith("WEIXIN_HOME_CHANNEL="):
                                existing_home = line.strip().split("=", 1)[1].strip()
                except Exception:
                    pass

            if not existing_account_id:
                return jsonify({
                    "ok": False,
                    "error": "profile " + profile_name + " 已存在，但缺少 WEIXIN_ACCOUNT_ID，拒绝覆盖以避免误绑其他 profile",
                }), 409

            if existing_account_id and existing_account_id != ilink_bot_id:
                return jsonify({
                    "ok": False,
                    "error": "profile " + profile_name + " 已绑定其他 bot (" + existing_account_id + ")，拒绝覆盖",
                }), 409

            logger.info("Profile %s already exists with same WEIXIN_ACCOUNT_ID, reusing", profile_name)
            # Preserve existing home channel
            if existing_home:
                ilink_user_id = existing_home
        else:
            logger.info("Creating profile: %s", profile_name)
            r = subprocess.run(
                ["/root/.local/bin/hermes", "profile", "create", profile_name, "--clone-from", "default"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode != 0:
                logger.error("Profile create failed: %s", r.stderr)
                return jsonify({"ok": False, "error": "创建 profile 失败: " + r.stderr.strip()}), 500

        # Sanitize all env values
        _sanitize_env_value(ilink_bot_id)
        _sanitize_env_value(bot_token)
        _sanitize_env_value(baseurl)
        _sanitize_env_value(ilink_user_id)
        _sanitize_env_value(ds_key)

        # Write .env atomically
        env_content = (
            "# Auto-generated bot profile for " + ilink_bot_id + "\n"
            "WEIXIN_ACCOUNT_ID=" + ilink_bot_id + "\n"
            "WEIXIN_TOKEN=" + bot_token + "\n"
            "WEIXIN_BASE_URL=" + baseurl + "\n"
            "WEIXIN_DM_POLICY=open\n"
            "WEIXIN_ALLOW_ALL_USERS=true\n"
            "WEIXIN_ALLOWED_USERS=\n"
            "DEEPSEEK_API_KEY=" + ds_key + "\n"
            "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
            "HTTP_PROXY=http://127.0.0.1:7890\n"
            "HTTPS_PROXY=http://127.0.0.1:7890\n"
            "NO_PROXY=localhost,127.0.0.1,api.deepseek.com,ilinkai.weixin.qq.com\n"
            "WEIXIN_HOME_CHANNEL=" + ilink_user_id + "\n"
            "WEIXIN_HOME_CHANNEL_NAME=Home\n"
        )
        os.makedirs(profile_dir, exist_ok=True)
        _atomic_write(os.path.join(profile_dir, ".env"), env_content)

        # Merge config.yaml — don't overwrite telegram/qqbot/model wholesale
        config_path = os.path.join(profile_dir, "config.yaml")
        existing_cfg = {}
        if os.path.exists(config_path):
            try:
                import yaml as _yaml
                with open(config_path) as f:
                    existing_cfg = _yaml.safe_load(f) or {}
            except Exception:
                pass

        existing_cfg.setdefault("display", {})
        existing_cfg["display"]["personality"] = (
            "你是ty的智能助手，通过微信为用户提供服务。\n"
            "**必须始终用中文回复。**\n"
            "保持友好、简洁、专业。\n"
            "\n"
            "当首次与一个新用户对话时：\n"
            "1. 主动打招呼并自我介绍：「你好！我是ty的智能助手 🤖」\n"
            "2. 引导用户定义个人偏好（Profile）：\n"
            "   - 怎么称呼你？\n"
            "   - 主要用途是什么？（学习/工作/生活/娱乐）\n"
            "   - 偏好什么回答风格？（简洁/详细/幽默）\n"
            "3. 将用户偏好保存到记忆中，后续对话据此提供个性化服务。"
        )
        existing_cfg["display"]["busy_ack_enabled"] = False
        # Merge model config instead of overwriting
        existing_cfg.setdefault("model", {})
        existing_cfg["model"].setdefault("default", "deepseek-v4-flash")
        existing_cfg["model"].setdefault("provider", "deepseek")
        # Merge telegram/qqbot — disable for WeChat-only profiles
        existing_cfg.setdefault("telegram", {})
        existing_cfg["telegram"]["enabled"] = False
        existing_cfg.setdefault("qqbot", {})
        existing_cfg["qqbot"]["enabled"] = False

        import yaml as _yaml
        yaml_content = _yaml.dump(existing_cfg, allow_unicode=True, default_flow_style=False)
        _atomic_write(config_path, yaml_content)

        # Install gateway service for this specific profile (NOT globally)
        logger.info("Installing gateway service for profile: %s", profile_name)
        r = subprocess.run(
            ["/root/.local/bin/hermes", "--profile", profile_name, "gateway", "install"],
            input="y\ny\n", capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            logger.error("Gateway install failed for profile %s: stdout=%s stderr=%s",
                         profile_name, r.stdout.strip()[-300:], r.stderr.strip()[-300:])
            return jsonify({
                "ok": False,
                "error": "网关服务安装失败，请检查 hermes 配置。",
                "status": "confirmed",
                "profile": profile_name,
                "ilink_bot_id": ilink_bot_id,
                "ilink_user_id": ilink_user_id,
                "gateway_started": False,
            })

        # Start gateway for this specific profile only (NOT restart --all)
        logger.info("Starting gateway for profile: %s", profile_name)
        r = subprocess.run(
            ["/root/.local/bin/hermes", "--profile", profile_name, "gateway", "start"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            logger.error("Gateway start failed for profile %s: %s", profile_name, r.stderr.strip()[:200])
            return jsonify({
                "ok": False,
                "error": "网关启动失败，请稍后重试或检查 hermes gateway status。",
                "status": "confirmed",
                "profile": profile_name,
                "ilink_bot_id": ilink_bot_id,
                "ilink_user_id": ilink_user_id,
                "gateway_started": False,
            })

        # Verify gateway is actually running for this specific profile
        time.sleep(3)
        gateway_running = False
        try:
            # Primary: check via hermes --profile <name> gateway status
            status_r = subprocess.run(
                ["/root/.local/bin/hermes", "--profile", profile_name, "gateway", "status"],
                capture_output=True, text=True, timeout=15
            )
            if status_r.returncode == 0 and profile_name in status_r.stdout:
                if "running" in status_r.stdout.lower() or "active" in status_r.stdout.lower() or "✓" in status_r.stdout:
                    gateway_running = True

            # Fallback: check systemd user service file + is-active
            if not gateway_running:
                svc_name = "hermes-gateway-" + profile_name
                svc_path = os.path.expanduser("~/.config/systemd/user/" + svc_name + ".service")
                if os.path.exists(svc_path):
                    sysctl_r = subprocess.run(
                        ["systemctl", "--user", "is-active", svc_name],
                        capture_output=True, text=True, timeout=10
                    )
                    if sysctl_r.returncode == 0 and sysctl_r.stdout.strip() == "active":
                        gateway_running = True
        except Exception as e:
            logger.warning("Gateway status verification failed: %s", e)

        if gateway_running:
            message = "Bot 已创建！\n注册完成后可直接在微信开聊。"
        else:
            message = "Bot 配置已写入，但网关启动验证失败。请稍后重试或检查 hermes gateway status。"

        return jsonify({
            "ok": gateway_running,
            "status": "confirmed",
            "profile": profile_name,
            "ilink_bot_id": ilink_bot_id,
            "ilink_user_id": ilink_user_id,
            "gateway_started": gateway_running,
            "message": message,
        })
    except Exception as e:
        logger.exception("Bot register failed")
        return jsonify({"ok": False, "error": str(e)}), 502
    finally:
        with _register_lock:
            _active_registrations.discard(qrcode)
# ── Task1: GET /api/codex-usage ──
@app.route('/api/codex-usage')
def api_codex_usage():
    try:
        import json as _json, os as _os, urllib.request as _ur
        with open(_os.path.expanduser('~/.codex/auth.json')) as f:
            auth = _json.load(f)
        access_token = auth['tokens']['access_token']
        account_id = auth['tokens']['account_id']
        url = 'https://chatgpt.com/backend-api/wham/usage?account_id=' + account_id
        req = _ur.Request(url, headers={'Authorization': 'Bearer ' + access_token})
        proxy_url = _os.environ.get('HTTP_PROXY', '') or _os.environ.get('HTTPS_PROXY', 'http://127.0.0.1:7890')
        data = None
        # Retry: first with proxy, then without if SSL error
        for attempt, use_proxy in [(1, proxy_url), (2, None)]:
            try:
                if use_proxy:
                    proxy = _ur.ProxyHandler({'https': use_proxy, 'http': use_proxy})
                    opener = _ur.build_opener(proxy)
                else:
                    opener = _ur.build_opener()
                with opener.open(req, timeout=30) as resp:
                    data = _json.loads(resp.read().decode())
                break
            except Exception as proxy_err:
                err_str = str(proxy_err)
                if attempt == 1 and ('SSL' in err_str or 'EOF' in err_str or 'Connection refused' in err_str):
                    import time as _time
                    _time.sleep(1)
                    continue
                raise  # re-raise if second attempt or non-SSL error
        plan_type = data.get('plan_type', '未知')
        rate_limit = data.get('rate_limit', {})
        pw = rate_limit.get('primary_window', {})
        sw = rate_limit.get('secondary_window', {})
        return jsonify({
            'plan_type': plan_type,
            'primary_window': {
                'used_percent': pw.get('used_percent', 0),
                'remaining_percent': 100 - pw.get('used_percent', 0),
                'label': '当前session(5小时)',
            },
            'secondary_window': {
                'used_percent': sw.get('used_percent', 0),
                'remaining_percent': 100 - sw.get('used_percent', 0),
                'label': '本周',
            },
        })
    except Exception as e:
        logger.warning('Codex usage fetch failed: %s', e)
        return jsonify({'error': str(e)}), 502

# ── Task2: GET /api/codex-daily-usage ──
@app.route('/api/codex-daily-usage')
def api_codex_daily_usage():
    try:
        import json as _json
        with open('/root/gateway-dashboard/token_usage.json') as f:
            entries = _json.load(f)
        codex_entries = [e for e in entries if e.get('provider') == 'openai-codex']
        by_day = {}
        for e in codex_entries:
            ts = e.get('ts', 0)
            dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) + datetime.timedelta(hours=8)
            day_key = dt.strftime('%Y-%m-%d')
            by_day.setdefault(day_key, {'total_tokens': 0, 'calls': 0})
            by_day[day_key]['total_tokens'] += e.get('total_tokens', 0)
            by_day[day_key]['calls'] += 1
        result = [{'date': k, 'total_tokens': v['total_tokens'], 'calls': v['calls']} for k, v in sorted(by_day.items())]
        return jsonify(result)
    except Exception as e:
        logger.warning('Codex daily usage fetch failed: %s', e)
        return jsonify({'error': str(e)}), 502
if __name__ == "__main__":
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY 未设置！请通过环境变量或 .env 文件配置。")
        sys.exit(1)

    if not ADMIN_PASSWORD:
        logger.error("ADMIN_PASSWORD 未设置！请通过环境变量设置安全的密码: export ADMIN_PASSWORD=your_secure_password")
        logger.error("若不设置，管理员面板将无法登录。")
        sys.exit(1)

    # Build token index on startup
    _rebuild_token_index()
    logger.info("Token index rebuilt")

    port_str = os.environ.get("PORT", "5000")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning("PORT 环境变量 '%s' 无效，使用默认值 5000", port_str)
        port = 5000
    logger.info("AI Bot Platform starting on http://0.0.0.0:%d", port)
    logger.info("Admin panel: http://0.0.0.0:%d/admin", port)
    app.run(host="0.0.0.0", port=port, debug=False)
