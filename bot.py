import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import random
import time
import html
import gc
import zipfile
import io
import mimetypes
import urllib.request
import urllib.parse
import socket
import asyncio
import json
import psutil
import subprocess
import shutil
import re
import string
import base64
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from ftplib import FTP, error_perm
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from flask import Flask
from threading import Thread

# 1. Load Environment Variables (dual-mode: Termux .env + Replit Secrets)
# Replit Secrets are already injected into os.environ. override=False ensures a local
# .env file never overwrites values supplied by the hosting platform.
load_dotenv(override=False)

def detect_runtime_mode():
    """Identify hosting environment without logging any secret values."""
    if any(os.getenv(key) for key in ("REPL_ID", "REPLIT_DEPLOYMENT", "REPLIT_DOMAINS")):
        return "Replit Secrets / environment variables"
    if os.path.isfile(".env"):
        return "Termux/local .env + environment variables"
    return "environment variables (no local .env detected)"

RUNTIME_MODE = detect_runtime_mode()

BOT_VERSION = "v26.2 NEON OS • Multi-Device + 3 Bots + 10 FTP"
GEMINI_MODEL = "gemini-2.5-flash"

# Set Waktu Indonesia Barat (WIB = UTC+7)
WIB = timezone(timedelta(hours=7))

def get_wib_now():
    return datetime.now(WIB)

# ==================== KEEP-ALIVE SERVER ====================
app_web = Flask('')

@app_web.route('/')
def home():
    return f"NEON OS {BOT_VERSION} is alive. uptime={get_uptime()}"

def run_web():
    port = int(os.getenv('PORT', '8080'))
    app_web.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== BANNER & LOGGING ====================
def show_termux_banner():
    current_wib_str = get_wib_now().strftime("%Y-%m-%d %H:%M:%S")
    cyan, magenta, green, yellow, reset = "\033[96m", "\033[95m", "\033[92m", "\033[93m", "\033[0m"
    line = "═" * 62
    print(f"\n{cyan}╔{line}╗\n║{magenta}{'  ✦ NEON AI BOT CONTROL CENTER ✦':^62}{cyan}║\n╠{line}╣\n║ {yellow}VERSION : {BOT_VERSION:<51}{cyan}║\n║ {green}CONFIG  : {len(BOT_TOKENS)} bot token(s) loaded{' ' * max(0, 34-len(str(len(BOT_TOKENS))))}{cyan}║\n║ {yellow}TIME    : {current_wib_str} WIB{' ' * max(0, 38-len(current_wib_str))}{cyan}║\n╚{line}╝{reset}\n")

class WIBFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=WIB)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%H:%M:%S')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(WIBFormatter('\033[1;30m[%(asctime)s WIB]\033[0m \033[1;36m%(levelname)s\033[0m ─ \033[1;37m%(message)s\033[0m', datefmt='%H:%M:%S'))
logger.addHandler(console_handler)
# Persistent rotating logs: useful for diagnosing download/FTP failures after restart.
try:
    file_handler = RotatingFileHandler("neon_bot.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8")
    file_handler.setFormatter(WIBFormatter("[%(asctime)s WIB] %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(file_handler)
except Exception as log_exc:
    print(f"[WARN] File logging tidak aktif: {log_exc}")

# CONFIGURATION
# Supports either BOT_TOKENS="token1,token2,token3" or separate token variables.
raw_tokens = os.getenv("BOT_TOKENS", "")
BOT_TOKENS = [token.strip() for token in raw_tokens.split(",") if token.strip()]
for _token_var in ("BOT_TOKEN", "BOT_TOKEN_1", "BOT_TOKEN_2", "BOT_TOKEN_3",
                   "TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_2", "TELEGRAM_BOT_TOKEN_3"):
    _token_value = os.getenv(_token_var, "").strip()
    if _token_value and _token_value not in BOT_TOKENS:
        BOT_TOKENS.append(_token_value)
# Multi-bot mode: run every distinct token configured in BOT_TOKENS and/or
# BOT_TOKEN / BOT_TOKEN_1..3 / TELEGRAM_BOT_TOKEN variants. Duplicates are
# removed at startup. Never run a second copy with the same tokens.
logger.info("Multi-bot mode aktif; %s token unik akan dijalankan jika terkonfigurasi.", len(BOT_TOKENS))

# Multi-FTP failover. Account 1 keeps the legacy FTP_HOST/USER/PASS/PORT names;
# additional accounts use FTP2_HOST/FTP2_USER/FTP2_PASS/FTP2_PORT ... FTP10_*.
# Never print passwords or full credentials to logs/Telegram.
FTP_HOST = os.getenv("FTP_HOST", "ftpupload.net").strip()
FTP_USER = os.getenv("FTP_USER", "if0_43064672").strip()
FTP_PASS = os.getenv("FTP_PASS", "").strip()
FTP_PORT = int(os.getenv("FTP_PORT", "21"))

def _load_ftp_accounts():
    accounts = []
    for idx in range(1, 11):
        prefix = "FTP" if idx == 1 else f"FTP{idx}"
        host = os.getenv(f"{prefix}_HOST", FTP_HOST if idx == 1 else "").strip()
        user = os.getenv(f"{prefix}_USER", FTP_USER if idx == 1 else "").strip()
        password = os.getenv(f"{prefix}_PASS", FTP_PASS if idx == 1 else "").strip()
        try:
            port = int(os.getenv(f"{prefix}_PORT", str(FTP_PORT if idx == 1 else 21)))
        except (TypeError, ValueError):
            port = 21
        # Preserve configured/incomplete extra slots for status display only if any field exists.
        if host or user or password:
            accounts.append({"id": idx, "host": host, "user": user, "password": password,
                             "port": port, "configured": bool(host and user and password)})
    return accounts

FTP_ACCOUNTS = _load_ftp_accounts()
FTP_ACCOUNT_STATUS = {}  # account id -> last live test result; never contains credentials
FTP_ACCOUNT_LOCK = __import__("threading").RLock()

# Social downloader configuration. Use only cookies from accounts you own or are
# authorized to access. Generic cookies are a fallback; per-site values take priority.
SOCIAL_COOKIES_FILE = os.getenv("SOCIAL_COOKIES_FILE", "").strip()
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
TIKTOK_COOKIES_FILE = os.getenv("TIKTOK_COOKIES_FILE", "").strip()
INSTAGRAM_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "").strip()
FACEBOOK_COOKIES_FILE = os.getenv("FACEBOOK_COOKIES_FILE", "").strip()
X_COOKIES_FILE = os.getenv("X_COOKIES_FILE", "").strip()
# Default keeps best available quality; optionally set DOWNLOAD_MAX_HEIGHT=720 etc.
DOWNLOAD_MAX_HEIGHT = os.getenv("DOWNLOAD_MAX_HEIGHT", "").strip()
DOWNLOAD_TIMEOUT_SECONDS = max(60, min(1800, int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "900"))))
# Permanent local archive for completed downloads; files here are never auto-cleaned.
DOWNLOADS_DIR = os.path.abspath(os.getenv("DOWNLOADS_DIR", "downloads"))
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

BASE_HTTP_URL = os.getenv("BASE_HTTP_URL", "").strip()
try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except (TypeError, ValueError):
    OWNER_ID = 0
    logger.warning("OWNER_ID tidak valid; akses owner belum aktif sampai ID Telegram disetel.")
# Comma-separated Telegram user IDs allowed to use normal bot features. Owner is always included.
ALLOWED_USER_IDS = {OWNER_ID}
for _uid in os.getenv("ALLOWED_USER_IDS", "").split(","):
    try:
        if _uid.strip():
            ALLOWED_USER_IDS.add(int(_uid.strip()))
    except ValueError:
        logger.warning("Mengabaikan ID pengguna tidak valid di ALLOWED_USER_IDS")
AI_DB_FILE = os.getenv("AI_DB_FILE", "ai_history.sqlite3")
AI_HISTORY_LIMIT = 12


gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
ai_client = None
if gemini_api_key:
    try:
        ai_client = genai.Client(api_key=gemini_api_key)
        logger.info("Google GenAI Core berhasil diinisialisasi secara penuh.")
    except Exception as e:
        logger.warning(f"Gagal menginisialisasi GenAI: {e}")

HISTORY_FILE = "chat_history.json"
BANNED_FILE = "banned_users.json"
TODO_FILE = "todo_list.json"
KANBAN_FILE = "kanban_board.json"
ftp_lock = asyncio.Lock()
START_TIME = time.time()
# Shared in-process telemetry for all configured bot workers. Never store tokens here.
BOT_RUNTIME = {}
DOWNLOAD_JOBS = []
DOWNLOAD_JOBS_LOCK = asyncio.Lock()

def init_ai_db():
    """Create persistent per-user/per-chat AI history storage."""
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS ai_history (user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, seq INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ai_history_user_chat_seq ON ai_history(user_id, chat_id, seq)")
        db.execute("CREATE TABLE IF NOT EXISTS user_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, memory TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_user_memory_user_id ON user_memory(user_id, id)")
        db.commit()

def load_ai_history(user_id: int, chat_id: int):
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        rows = db.execute("SELECT role, text FROM ai_history WHERE user_id=? AND chat_id=? ORDER BY seq DESC LIMIT ?", (user_id, chat_id, AI_HISTORY_LIMIT)).fetchall()
    return [{"role": role, "text": text} for role, text in reversed(rows)]

def save_ai_turn(user_id: int, chat_id: int, prompt: str, answer: str):
    now = get_wib_now().isoformat()
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        db.execute("INSERT INTO ai_history(user_id, chat_id, role, text, created_at) VALUES(?,?,?,?,?)", (user_id, chat_id, "user", prompt[:12000], now))
        db.execute("INSERT INTO ai_history(user_id, chat_id, role, text, created_at) VALUES(?,?,?,?,?)", (user_id, chat_id, "assistant", answer[:20000], now))
        db.execute("DELETE FROM ai_history WHERE user_id=? AND chat_id=? AND seq NOT IN (SELECT seq FROM ai_history WHERE user_id=? AND chat_id=? ORDER BY seq DESC LIMIT ?)", (user_id, chat_id, user_id, chat_id, AI_HISTORY_LIMIT))
        db.commit()

def clear_ai_history(user_id: int, chat_id: int):
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        db.execute("DELETE FROM ai_history WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        db.commit()

def save_user_memory(user_id: int, memory: str) -> int:
    """Save an explicitly requested, user-scoped memory. Never share between users."""
    memory = memory.strip()[:1000]
    if not memory:
        raise ValueError("Memori kosong")
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        cur = db.execute("INSERT INTO user_memory(user_id, memory, created_at) VALUES(?,?,?)",
                         (user_id, memory, get_wib_now().isoformat()))
        db.commit()
        return int(cur.lastrowid)

def load_user_memories(user_id: int, limit: int = 20):
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        rows = db.execute("SELECT id, memory, created_at FROM user_memory WHERE user_id=? ORDER BY id DESC LIMIT ?",
                          (user_id, max(1, min(50, limit)))).fetchall()
    return rows

def delete_user_memory(user_id: int, memory_id=None) -> int:
    with closing(sqlite3.connect(AI_DB_FILE, timeout=15)) as db:
        if memory_id is None:
            cur = db.execute("DELETE FROM user_memory WHERE user_id=?", (user_id,))
        else:
            cur = db.execute("DELETE FROM user_memory WHERE user_id=? AND id=?", (user_id, memory_id))
        db.commit()
        return cur.rowcount

def generate_ai_response(prompt_or_contents):
    if not ai_client:
        return None
    models_to_try = [GEMINI_MODEL, "gemini-1.5-flash", "gemini-2.5-pro"]
    for model in models_to_try:
        try:
            res = ai_client.models.generate_content(model=model, contents=prompt_or_contents)
            if res and res.text:
                return res.text
        except Exception as e:
            logger.warning(f"Gagal menggunakan model {model}: {e}")
            continue
    return None

# ==================== ADVANCED MULTI-FTP ENGINE ====================
def ensure_ftp_dir(ftp, directory):
    """Ensure a relative FTP directory exists and leave the session inside it.

    FTPManager.get_connection() normally starts in htdocs when that folder exists.
    This helper intentionally uses relative path segments so it also works with
    providers that expose the account root differently. Existing directories are
    reused; missing ones are created. Raises a useful error if creation/cwd fails.
    """
    if not directory or not str(directory).strip():
        return ftp.pwd()
    normalized = str(directory).replace("\\", "/").strip("/")
    if not normalized or any(part in ("", ".", "..") for part in normalized.split("/")):
        raise ValueError("Nama folder FTP tidak valid")
    for part in normalized.split("/"):
        try:
            ftp.cwd(part)
            continue
        except Exception:
            pass
        try:
            ftp.mkd(part)
        except Exception:
            # A concurrent upload may have created the folder, or the server
            # may return a generic error for an existing directory.
            try:
                ftp.cwd(part)
                continue
            except Exception as exc:
                raise RuntimeError(f"Gagal membuat/membuka folder FTP '{part}': {type(exc).__name__}") from None
        try:
            ftp.cwd(part)
        except Exception as exc:
            raise RuntimeError(f"Folder FTP '{part}' dibuat tetapi tidak bisa dibuka: {type(exc).__name__}") from None
    return ftp.pwd()


def _mask_ftp_user(user):
    if not user:
        return "user belum diisi"
    if len(user) <= 4:
        return user[0] + "***"
    return user[:2] + "***" + user[-2:]


def _close_ftp(ftp):
    if ftp is not None:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


def _connect_ftp_account(account, timeout=12):
    """Connect/login one account; never expose its password in errors/logs."""
    if not account.get("configured"):
        raise RuntimeError("konfigurasi akun belum lengkap")
    ftp = FTP()
    try:
        ftp.connect(account["host"], account["port"], timeout=timeout)
        ftp.login(account["user"], account["password"])
        ftp.set_pasv(True)
        with FTP_ACCOUNT_LOCK:
            FTP_ACCOUNT_STATUS[account["id"]] = {"state": "online", "checked": get_wib_now(), "detail": "login FTP berhasil"}
        logger.info("☁️ FTP akun %s login berhasil.", account["id"])
        return ftp
    except Exception as exc:
        try:
            ftp.close()
        except Exception:
            pass
        with FTP_ACCOUNT_LOCK:
            FTP_ACCOUNT_STATUS[account["id"]] = {"state": "offline", "checked": get_wib_now(), "detail": type(exc).__name__}
        logger.warning("☁️ FTP akun %s OFFLINE/gagal login (%s). Beralih ke akun berikutnya.", account["id"], type(exc).__name__)
        raise RuntimeError(f"akun FTP {account['id']} gagal: {type(exc).__name__}") from None


class FTPManager:
    @staticmethod
    def get_connection(retries=2, delay=1):
        if not FTP_ACCOUNTS:
            raise RuntimeError("Belum ada akun FTP. Isi FTP_HOST/FTP_USER/FTP_PASS atau FTP2_*, FTP3_* di .env/Secrets.")
        errors = []
        for attempt in range(max(1, retries)):
            for account in FTP_ACCOUNTS:
                if not account.get("configured"):
                    with FTP_ACCOUNT_LOCK:
                        FTP_ACCOUNT_STATUS[account["id"]] = {"state": "unconfigured", "checked": get_wib_now(), "detail": "konfigurasi belum lengkap"}
                    continue
                try:
                    ftp = _connect_ftp_account(account)
                    try:
                        ftp.cwd('htdocs')
                    except Exception:
                        pass
                    return ftp
                except Exception as exc:
                    errors.append(str(exc))
            if attempt + 1 < max(1, retries):
                time.sleep(delay * (attempt + 1))
        raise RuntimeError("Semua akun FTP gagal login. " + "; ".join(errors[-len(FTP_ACCOUNTS):]))


def check_ftp_accounts():
    """Live login-check every configured FTP account for console and /ftpstatus."""
    results = []
    if not FTP_ACCOUNTS:
        return results
    for account in FTP_ACCOUNTS:
        if not account.get("configured"):
            result = {"id": account["id"], "state": "unconfigured", "user": account.get("user", ""), "host": account.get("host", ""), "detail": "host/user/password belum lengkap"}
            with FTP_ACCOUNT_LOCK:
                FTP_ACCOUNT_STATUS[account["id"]] = {"state": result["state"], "checked": get_wib_now(), "detail": result["detail"]}
            results.append(result)
            continue
        ftp = None
        try:
            ftp = _connect_ftp_account(account, timeout=8)
            # A successful login is the online test; storage/write permissions are tested on upload.
            results.append({"id": account["id"], "state": "online", "user": account["user"], "host": account["host"], "detail": "login berhasil"})
        except Exception as exc:
            results.append({"id": account["id"], "state": "offline", "user": account["user"], "host": account["host"], "detail": type(exc).__name__})
        finally:
            _close_ftp(ftp)
    online = sum(1 for item in results if item["state"] == "online")
    print(f"\n☁️ FTP HEALTH: {online}/{len(results)} akun login aktif")
    for item in results:
        state = item["state"]
        icon = "🟢" if state == "online" else ("🟡" if state == "unconfigured" else "🔴")
        print(f"  {icon} FTP {item['id']}: {state.upper()} — {_mask_ftp_user(item.get('user',''))} @ {item.get('host') or 'host belum diisi'} ({item['detail']})")
    return results


def upload_download_to_ftp(local_path, user_id=None):
    """Upload to the first FTP account that can login AND accept the complete file."""
    if not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)
    if not FTP_ACCOUNTS:
        raise RuntimeError("Belum ada akun FTP terkonfigurasi")
    original = os.path.basename(local_path)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._") or "media.bin"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_name_base = f"{stamp}_{user_id or 'user'}_{safe}"[:220]
    total = os.path.getsize(local_path)
    errors = []
    for account in FTP_ACCOUNTS:
        if not account.get("configured"):
            continue
        ftp = None
        try:
            ftp = _connect_ftp_account(account)
            ensure_ftp_dir(ftp, "downloads")
            remote_name = remote_name_base
            try:
                existing = set(ftp.nlst())
            except Exception:
                existing = set()
            if remote_name in existing:
                root, ext = os.path.splitext(remote_name)
                remote_name = f"{root}_{int(time.time() * 1000)}{ext}"
            transferred = 0
            def callback(block):
                nonlocal transferred
                transferred += len(block)
            with open(local_path, "rb") as source:
                ftp.storbinary(f"STOR {remote_name}", source, blocksize=1024 * 1024, callback=callback)
            if transferred != total:
                raise IOError(f"upload tidak lengkap: {transferred}/{total} byte")
            relative_path = f"downloads/{remote_name}"
            public_url = BASE_HTTP_URL.rstrip("/") + "/" + urllib.parse.quote(relative_path, safe="/") if BASE_HTTP_URL else ""
            logger.info("☁️ Upload sukses lewat FTP akun %s (%s byte).", account["id"], total)
            return {"name": remote_name, "path": relative_path, "size": total, "url": public_url, "ftp_account": account["id"]}
        except Exception as exc:
            errors.append(f"FTP {account['id']}: {type(exc).__name__}")
            logger.warning("☁️ Upload lewat FTP akun %s gagal (%s); mencoba akun berikutnya.", account["id"], type(exc).__name__)
            # A file/path/application error does not necessarily mean the FTP
            # account is offline. Only connection/protocol/permission failures
            # should downgrade the live status; other errors remain diagnostic.
            if isinstance(exc, (OSError, EOFError, TimeoutError)) or type(exc).__name__ in {
                "error_perm", "error_reply", "error_temp", "error_proto"
            }:
                with FTP_ACCOUNT_LOCK:
                    FTP_ACCOUNT_STATUS[account["id"]] = {"state": "offline", "checked": get_wib_now(), "detail": "upload gagal: " + type(exc).__name__}
            else:
                with FTP_ACCOUNT_LOCK:
                    FTP_ACCOUNT_STATUS[account["id"]] = {"state": "online", "checked": get_wib_now(), "detail": "login berhasil; operasi upload gagal: " + type(exc).__name__}
        finally:
            _close_ftp(ftp)
    raise RuntimeError("Semua akun FTP gagal menerima file. " + "; ".join(errors or ["tidak ada akun FTP lengkap"]))

# ==================== UTILS & CLEANER ====================
def clean_local_temp_files():
    """Non-destructive maintenance: never delete files from the project folder.

    Older versions removed files by filename prefix (including download_* folders),
    which could erase user files. Completed downloads are kept in DOWNLOADS_DIR.
    Per-job scratch folders are removed only by their own finally blocks.
    """
    gc.collect()
    return 0

def load_banned_users():
    if os.path.exists(BANNED_FILE):
        try:
            with open(BANNED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_banned_users(banned_set):
    try:
        with open(BANNED_FILE, "w", encoding="utf-8") as f:
            json.dump(list(banned_set), f)
    except Exception as e:
        logger.error(f"Gagal menyimpan data ban: {e}")

def is_user_banned(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return False
    return user_id in load_banned_users()

def save_chat_history(user_id: int, username: str, full_name: str, message_text: str):
    try:
        history_data = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history_data = json.load(f)
            except Exception:
                history_data = []

        log_entry = {
            "timestamp": get_wib_now().strftime("%Y-%m-%d %H:%M:%S WIB"),
            "user_id": user_id,
            "username": f"@{username}" if username else "NoUsername",
            "full_name": full_name,
            "message": message_text
        }
        
        history_data.append(log_entry)
        if len(history_data) > 1000:
            history_data = history_data[-1000:]

        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Gagal menyimpan riwayat chat: {e}")

def get_user_name(update: Update) -> str:
    user = update.effective_user
    return html.escape(user.first_name) if user and user.first_name else "Operator"

def is_authorized(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    user_id = user.id
    if is_user_banned(user_id):
        return False
    return user_id in ALLOWED_USER_IDS

def is_owner(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == OWNER_ID)

async def delete_msg_safe(msg):
    try:
        await msg.delete()
    except Exception:
        pass

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def get_uptime():
    delta = int(time.time() - START_TIME)
    hours, remainder = divmod(delta, 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {minutes}m {seconds}s"

async def auto_system_health_check(app: Application):
    while True:
        try:
            await asyncio.sleep(300)
            cleaned = clean_local_temp_files()
            if cleaned > 0:
                logger.info(f"Auto-Health Worker: Berhasil membersihkan {cleaned} file temporary lokal.")
        except Exception as e:
            logger.error(f"Auto-Health Worker Exception: {e}")

# ==================== INTERACTIVE DASHBOARD ====================
def get_dashboard_keyboard(page=1):
    if page == 1:
        keyboard = [
            [
                InlineKeyboardButton("📥 Downloader Pro", callback_data='btn_help_sync'),
                InlineKeyboardButton("🧠 AI Neural Hub", callback_data='btn_ai_menu')
            ],
            [
                InlineKeyboardButton("🎨 AI Image (/imagine)", callback_data='btn_img_help'),
                InlineKeyboardButton("💻 AI Code Debug (/fix)", callback_data='btn_fix_help')
            ],
            [
                InlineKeyboardButton("🔍 AI OCR (/ocr)", callback_data='btn_ocr_help'),
                InlineKeyboardButton("🌐 Short Link (/short)", callback_data='btn_short_help')
            ],
            [
                InlineKeyboardButton("🚀 Lanjut ke Halaman 2 (Web & SS Pro) ➔", callback_data='page_2')
            ]
        ]
    elif page == 2:
        keyboard = [
            [
                InlineKeyboardButton("📸 Web SS Desktop (/ss)", callback_data='btn_ss_help'),
                InlineKeyboardButton("📜 Full Scroll SS (/fullss)", callback_data='btn_fullss_help')
            ],
            [
                InlineKeyboardButton("📱 Mobile View (/mobilesec)", callback_data='btn_mob_help'),
                InlineKeyboardButton("📟 Tablet View (/tabss)", callback_data='btn_tab_help')
            ],
            [
                InlineKeyboardButton("🌙 Dark Mode SS (/darkss)", callback_data='btn_dark_help'),
                InlineKeyboardButton("📄 Web to PDF (/pdfss)", callback_data='btn_pdf_help')
            ],
            [
                InlineKeyboardButton("🔍 Web Inspector (/webinfo)", callback_data='btn_webinfo_help'),
                InlineKeyboardButton("🌐 Domain DNS (/dns)", callback_data='btn_dns_help')
            ],
            [
                InlineKeyboardButton("⬅️ Halaman 1", callback_data='page_1'),
                InlineKeyboardButton("Halaman 3 ➔", callback_data='page_3')
            ]
        ]
    elif page == 3:
        keyboard = [
            [
                InlineKeyboardButton("📌 QR Code (/qr)", callback_data='btn_qr_help'),
                InlineKeyboardButton("🌤️ Cuaca (/weather)", callback_data='btn_weather_help')
            ],
            [
                InlineKeyboardButton("📋 Wedding To-Do (/todo)", callback_data='btn_todo_help'),
                InlineKeyboardButton("📊 Kanban Board (/kanban)", callback_data='btn_kanban_help')
            ],
            [
                InlineKeyboardButton("🔄 Translator (/trans)", callback_data='btn_trans_help'),
                InlineKeyboardButton("🔑 Pass Gen (/genpass)", callback_data='btn_pass_help')
            ],
            [
                InlineKeyboardButton("⬅️ Halaman 2", callback_data='page_2'),
                InlineKeyboardButton("Halaman 4 (System) ➔", callback_data='page_4')
            ]
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🔋 Status Baterai", callback_data='btn_battery'),
                InlineKeyboardButton("🌐 Info IP & Jaringan", callback_data='btn_netinfo')
            ],
            [
                InlineKeyboardButton("📊 Kuota Storage", callback_data='btn_storage'),
                InlineKeyboardButton("📁 Direktori Cloud", callback_data='btn_list')
            ],
            [
                InlineKeyboardButton("🚀 Speedtest Server", callback_data='btn_speedtest'),
                InlineKeyboardButton("🧹 Clean Log Cache", callback_data='btn_cleanlog')
            ],
            [
                InlineKeyboardButton("🛡️ Backup Cloud ZIP", callback_data='btn_backup'),
                InlineKeyboardButton("⬅️ Kembali ke Halaman 3", callback_data='page_3')
            ]
        ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        if update.effective_message:
            await update.effective_message.reply_text("🔒 Akses bot belum diaktifkan untuk akun Telegram lu. Minta owner menambahkan ID lu ke ALLOWED_USER_IDS di .env.")
        return

    user_name = get_user_name(update)
    bot_info = await context.bot.get_me()
    wib_now = get_wib_now().strftime("%Y-%m-%d %H:%M:%S")
    
    pesan_menu = (
        f"✨ <b>NEON AI ASSISTANT</b> ✨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 Halo, <b>{user_name}</b>! Selamat datang.\n\n"
        f"🤖 <b>Bot:</b> @{html.escape(bot_info.username or 'unknown')}\n"
        f"🟢 <b>Status:</b> Online\n"
        f"⏱️ <b>Uptime:</b> <code>{html.escape(get_uptime())}</code>\n"
        f"🕒 <b>Waktu:</b> <code>{html.escape(wib_now)} WIB</code>\n"
        f"🧠 <b>AI:</b> {'Siap digunakan' if ai_client else 'Belum dikonfigurasi'}\n\n"
        f"Pilih fitur dari tombol di bawah. Kalau butuh bantuan, ketik /help.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await msg.edit_text(pesan_menu, parse_mode='HTML', reply_markup=get_dashboard_keyboard(1))
    else:
        await msg.reply_text(pesan_menu, parse_mode='HTML', reply_markup=get_dashboard_keyboard(1))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'ai_reset':
        user = update.effective_user
        message = query.message
        if user and message:
            await asyncio.to_thread(clear_ai_history, user.id, message.chat_id)
        context.user_data.pop("ai_history", None)
        await query.message.reply_text("🧹 Riwayat AI di chat ini sudah direset.")
    elif query.data == 'ai_chat_help':
        await query.message.reply_text("💬 Mode chat AI aktif. Kirim pesan biasa di chat pribadi, atau ketik /ai pertanyaan lu. Gunakan /resetai untuk menghapus konteks percakapan.")
    elif query.data == 'page_1':
        await query.message.edit_text("💎 <b>CYBER-ENTERPRISE OS (Page 1: Core AI & Downloader)</b> 💎", parse_mode='HTML', reply_markup=get_dashboard_keyboard(1))
    elif query.data == 'page_2':
        await query.message.edit_text("💎 <b>CYBER-ENTERPRISE OS (Page 2: Web & SS Pro Suite)</b> 💎", parse_mode='HTML', reply_markup=get_dashboard_keyboard(2))
    elif query.data == 'page_3':
        await query.message.edit_text("💎 <b>CYBER-ENTERPRISE OS (Page 3: Utilities & Wedding Tools)</b> 💎", parse_mode='HTML', reply_markup=get_dashboard_keyboard(3))
    elif query.data == 'page_4':
        await query.message.edit_text("💎 <b>CYBER-ENTERPRISE OS (Page 4: System & Cloud Server)</b> 💎", parse_mode='HTML', reply_markup=get_dashboard_keyboard(4))
    elif query.data == 'btn_storage':
        await storage_quota(update, context)
    elif query.data == 'btn_list':
        await list_ftp(update, context)
    elif query.data == 'btn_battery':
        await battery_status_command(update, context)
    elif query.data == 'btn_netinfo':
        await netinfo_command(update, context)
    elif query.data == 'btn_speedtest':
        await speedtest_command_callback(update, context)
    elif query.data == 'btn_backup':
        await backup_cloud(update, context)
    elif query.data == 'btn_cleanlog':
        cleaned = clean_local_temp_files()
        await query.message.reply_text(f"🧹 Berhasil membersihkan <code>{cleaned}</code> file cache lokal server.", parse_mode='HTML')
    elif query.data == 'btn_img_help':
        await query.message.edit_text("🎨 <b>AI IMAGE GENERATOR</b>\n\nFormat: <code>/imagine [deskripsi gambar]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_1')]]))
    elif query.data == 'btn_fix_help':
        await query.message.edit_text("💻 <b>AI CODE DEBUGGER</b>\n\nFormat: <code>/fix [kode error]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_1')]]))
    elif query.data == 'btn_ocr_help':
        await query.message.edit_text("🔍 <b>AI OCR</b>\n\nBalas foto dengan <code>/ocr</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_1')]]))
    elif query.data == 'btn_short_help':
        await query.message.edit_text("🌐 <b>SHORT LINK</b>\n\nFormat: <code>/short [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_1')]]))
    elif query.data == 'btn_qr_help':
        await query.message.edit_text("📌 <b>QR CODE</b>\n\nFormat: <code>/qr [teks]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_3')]]))
    elif query.data == 'btn_weather_help':
        await query.message.edit_text("🌤️ <b>WEATHER</b>\n\nFormat: <code>/weather [kota]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_3')]]))
    elif query.data == 'btn_ss_help':
        await query.message.edit_text("📸 <b>WEB SCREENSHOT PRO</b>\n\nFormat: <code>/ss [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_fullss_help':
        await query.message.edit_text("📜 <b>FULL SCROLL WEB SCREENSHOT</b>\n\nFormat: <code>/fullss [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_mob_help':
        await query.message.edit_text("📱 <b>MOBILE VIEWPORT SCREENSHOT</b>\n\nFormat: <code>/mobilesec [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_tab_help':
        await query.message.edit_text("📟 <b>TABLET VIEWPORT SCREENSHOT</b>\n\nFormat: <code>/tabss [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_dark_help':
        await query.message.edit_text("🌙 <b>FORCE DARK-MODE SCREENSHOT</b>\n\nFormat: <code>/darkss [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_pdf_help':
        await query.message.edit_text("📄 <b>WEB TO PDF CONVERTER</b>\n\nFormat: <code>/pdfss [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_webinfo_help':
        await query.message.edit_text("🔍 <b>DEEP WEB INSPECTOR</b>\n\nFormat: <code>/webinfo [url]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_dns_help':
        await query.message.edit_text("🌐 <b>DOMAIN DNS INTELLIGENCE</b>\n\nFormat: <code>/dns [domain]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_2')]]))
    elif query.data == 'btn_todo_help':
        await query.message.edit_text("📋 <b>TO-DO LIST</b>\n\n• <code>/todo</code>\n• <code>/todo_add [tugas]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_3')]]))
    elif query.data == 'btn_kanban_help':
        await query.message.edit_text("📊 <b>KANBAN BOARD</b>\n\n• <code>/kanban</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_3')]]))
    elif query.data == 'btn_trans_help':
        await query.message.edit_text("🔄 <b>TRANSLATOR</b>\n\nFormat: <code>/trans [lang] [teks]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_3')]]))
    elif query.data == 'btn_pass_help':
        await query.message.edit_text("🔑 <b>PASSWORD GEN</b>\n\nFormat: <code>/genpass [panjang]</code>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_3')]]))
    elif query.data == 'btn_ai_menu':
        ai_info = (
            f"🧠 <b>CENTRAL NEURAL AI HUB</b>\n"
            f"═══════════════════════════════════════\n"
            f"• <code>/ai [tanya]</code> ─ Tanya jawab cerdas\n"
            f"• <code>/writer [topik]</code> ─ Buat konten & caption\n"
            f"• <code>/imagine [prompt]</code> ─ Text-to-Image AI\n"
            f"• <code>/fix [kode]</code> ─ AI Code Reviewer\n"
            f"• <code>/quiz [materi]</code> ─ Kuis Interaktif\n"
            f"• <code>/resetai</code> ─ Reset riwayat sesi AI\n\n"
            f"Kirim pesan di chat pribadi untuk ngobrol langsung, atau gunakan <code>/ai pertanyaan</code>."
        )
        await query.message.edit_text(ai_info, parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Mulai Chat AI", callback_data='ai_chat_help')],
            [InlineKeyboardButton("⬅️ Kembali", callback_data='page_1')]
        ]))
    elif query.data in ['btn_help_sync', 'btn_help_search']:
        await help_command(update, context)

# ==================== 8 FITUR SCREENSHOT & WEB PRO ====================

async def website_screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("📸 <b>WEB SCREENSHOT DESKTOP</b>\n\nFormat: <code>/ss [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("📸 <i>[Pro Engine] Merender screenshot desktop 1920x1080...</i>", parse_mode='HTML')
    img_data = None
    encoded_url = urllib.parse.quote(url)

    api_endpoints = [
        lambda: base64.b64decode(json.loads(urllib.request.urlopen(urllib.request.Request(f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={encoded_url}&screenshot=true", headers={'User-Agent': 'Mozilla/5.0'}), timeout=25).read().decode('utf-8'))['lighthouseResult']['audits']['final-screenshot']['details']['data'].split(",")[1]),
        lambda: urllib.request.urlopen(urllib.request.Request(f"https://image.thum.io/get/width/1920/crop/1080/noanimate/{url}", headers={'User-Agent': 'Mozilla/5.0'}), timeout=20).read(),
        lambda: urllib.request.urlopen(urllib.request.Request(f"https://mini.s-shot.ru/1920x1080/JPEG/1920/Z100/?{url}", headers={'User-Agent': 'Mozilla/5.0'}), timeout=20).read()
    ]

    for engine in api_endpoints:
        try:
            data = engine()
            if data and len(data) > 3000:
                img_data = data
                break
        except Exception:
            continue

    if img_data:
        try:
            temp_ss = f"ss_{int(time.time())}.jpg"
            with open(temp_ss, 'wb') as f:
                f.write(img_data)
            await delete_msg_safe(status)
            with open(temp_ss, 'rb') as photo_f:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_f, caption=f"📸 <b>Desktop Screenshot:</b> <code>{url}</code>", parse_mode='HTML')
        except Exception as e:
            await delete_msg_safe(status)
            await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    else:
        await delete_msg_safe(status)
        await update.message.reply_text("❌ Gagal merender website.", parse_mode='HTML')
    clean_local_temp_files()

async def full_scroll_screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("📜 <b>FULL SCROLL SCREENSHOT</b>\n\nFormat: <code>/fullss [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("📜 <i>[Full Engine] Merender seluruh halaman web dari atas ke bawah...</i>", parse_mode='HTML')
    img_data = None
    try:
        req = urllib.request.Request(f"https://image.thum.io/get/fullpage/width/1200/noanimate/{url}", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if len(data) > 3000:
                img_data = data
    except Exception:
        pass

    if img_data:
        try:
            temp_full = f"full_{int(time.time())}.jpg"
            with open(temp_full, 'wb') as f:
                f.write(img_data)
            await delete_msg_safe(status)
            with open(temp_full, 'rb') as photo_f:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_f, caption=f"📜 <b>Full Scroll SS:</b> <code>{url}</code>", parse_mode='HTML')
        except Exception as e:
            await delete_msg_safe(status)
            await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    else:
        await delete_msg_safe(status)
        await update.message.reply_text("❌ Gagal merender full scroll.", parse_mode='HTML')
    clean_local_temp_files()

async def mobile_viewport_screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("📱 <b>MOBILE VIEWPORT SCREENSHOT</b>\n\nFormat: <code>/mobilesec [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("📱 <i>[Mobile Engine] Merender tampilan smartphone...</i>", parse_mode='HTML')
    img_data = None
    try:
        req = urllib.request.Request(f"https://mini.s-shot.ru/480x800/JPEG/480/Z100/?{url}", headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            if len(data) > 2000:
                img_data = data
    except Exception:
        pass

    if img_data:
        try:
            temp_mob = f"mob_{int(time.time())}.jpg"
            with open(temp_mob, 'wb') as f:
                f.write(img_data)
            await delete_msg_safe(status)
            with open(temp_mob, 'rb') as photo_f:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_f, caption=f"📱 <b>Mobile Viewport SS:</b> <code>{url}</code>", parse_mode='HTML')
        except Exception as e:
            await delete_msg_safe(status)
            await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    else:
        await delete_msg_safe(status)
        await update.message.reply_text("❌ Gagal merender tampilan mobile.", parse_mode='HTML')
    clean_local_temp_files()

async def tablet_viewport_screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("📟 <b>TABLET VIEWPORT SCREENSHOT</b>\n\nFormat: <code>/tabss [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("📟 <i>[Tablet Engine] Merender tampilan iPad/Tablet (1024x768)...</i>", parse_mode='HTML')
    img_data = None
    try:
        req = urllib.request.Request(f"https://mini.s-shot.ru/1024x768/JPEG/1024/Z100/?{url}", headers={'User-Agent': 'Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X)'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            if len(data) > 2000:
                img_data = data
    except Exception:
        pass

    if img_data:
        try:
            temp_tab = f"tab_{int(time.time())}.jpg"
            with open(temp_tab, 'wb') as f:
                f.write(img_data)
            await delete_msg_safe(status)
            with open(temp_tab, 'rb') as photo_f:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_f, caption=f"📟 <b>Tablet Viewport SS:</b> <code>{url}</code>", parse_mode='HTML')
        except Exception as e:
            await delete_msg_safe(status)
            await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    else:
        await delete_msg_safe(status)
        await update.message.reply_text("❌ Gagal merender tablet view.", parse_mode='HTML')
    clean_local_temp_files()

async def dark_mode_screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("🌙 <b>FORCE DARK-MODE SCREENSHOT</b>\n\nFormat: <code>/darkss [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("🌙 <i>[Dark Engine] Mengubah elemen web ke mode gelap (Dark Mode)...</i>", parse_mode='HTML')
    img_data = None
    try:
        dark_api = f"https://image.thum.io/get/width/1920/crop/1080/noanimate/dark/{url}"
        req = urllib.request.Request(dark_api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            if len(data) > 3000:
                img_data = data
    except Exception:
        pass

    if img_data:
        try:
            temp_dark = f"dark_{int(time.time())}.jpg"
            with open(temp_dark, 'wb') as f:
                f.write(img_data)
            await delete_msg_safe(status)
            with open(temp_dark, 'rb') as photo_f:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_f, caption=f"🌙 <b>Dark-Mode SS:</b> <code>{url}</code>", parse_mode='HTML')
        except Exception as e:
            await delete_msg_safe(status)
            await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    else:
        await delete_msg_safe(status)
        await update.message.reply_text("❌ Gagal merender dark mode.", parse_mode='HTML')
    clean_local_temp_files()

async def web_to_pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("📄 <b>WEB TO PDF CONVERTER</b>\n\nFormat: <code>/pdfss [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("📄 <i>[PDF Engine] Mengonversi struktur web ke dokumen PDF...</i>", parse_mode='HTML')
    pdf_data = None
    try:
        pdf_api = f"https://api.html2pdf.app/v1/generate?url={urllib.parse.quote(url)}&apiKey=public"
        req = urllib.request.Request(pdf_api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
            if len(data) > 1000:
                pdf_data = data
    except Exception:
        pass

    if pdf_data:
        try:
            temp_pdf = f"doc_{int(time.time())}.pdf"
            with open(temp_pdf, 'wb') as f:
                f.write(pdf_data)
            await delete_msg_safe(status)
            with open(temp_pdf, 'rb') as pdf_file:
                await context.bot.send_document(chat_id=update.effective_chat.id, document=pdf_file, filename=f"Web_Export_{int(time.time())}.pdf", caption=f"📄 <b>PDF Export Web:</b> <code>{url}</code>", parse_mode='HTML')
        except Exception as e:
            await delete_msg_safe(status)
            await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    else:
        await delete_msg_safe(status)
        await update.message.reply_text("❌ Gagal merender dokumen PDF.", parse_mode='HTML')
    clean_local_temp_files()

async def deep_web_inspector_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("🔍 <b>DEEP WEB INSPECTOR</b>\n\nFormat: <code>/webinfo [url]</code>", parse_mode='HTML')
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    
    status = await update.message.reply_text("🔍 <i>Memindai metadata dan struktur website...</i>", parse_mode='HTML')
    start_t = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.status
            headers = resp.headers
            html_content = resp.read().decode('utf-8', errors='ignore')
            latency = (time.time() - start_t) * 1000

            server = headers.get('Server', 'Hidden / Cloudflare')
            content_type = headers.get('Content-Type', 'HTML')
            
            title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE)
            page_title = title_match.group(1) if title_match else "Tidak ditemukan"

            await delete_msg_safe(status)
            await update.message.reply_text(
                f"🔍 <b>DEEP WEB INSPECTION REPORT</b>\n"
                f"═════════════════════════════════\n"
                f"🔗 <b>URL          :</b> <code>{url}</code>\n"
                f"📌 <b>Judul Web    :</b> <code>{html.escape(page_title)}</code>\n"
                f"🟢 <b>HTTP Status  :</b> <code>{code} OK</code>\n"
                f"⚡ <b>Response Time:</b> <code>{latency:.2f} ms</code>\n"
                f"🏢 <b>Server Engine:</b> <code>{server}</code>\n"
                f"📦 <b>Content Type :</b> <code>{content_type}</code>",
                parse_mode='HTML'
            )
    except Exception as e:
        await delete_msg_safe(status)
        await update.message.reply_text(f"❌ Gagal menginspeksi web: {e}", parse_mode='HTML')

async def domain_dns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("🌐 <b>DOMAIN & DNS INTELLIGENCE</b>\n\nFormat: <code>/dns [domain]</code>", parse_mode='HTML')
        return
    domain = context.args[0].replace("https://", "").replace("http://", "").split("/")[0]
    status = await update.message.reply_text(f"🌐 <i>Memeriksa DNS & IP untuk {domain}...</i>", parse_mode='HTML')
    try:
        ip_addr = socket.gethostbyname(domain)
        await delete_msg_safe(status)
        await update.message.reply_text(
            f"🌐 <b>DNS & DOMAIN INTELLIGENCE</b>\n"
            f"═════════════════════════════════\n"
            f"🌐 <b>Domain  :</b> <code>{domain}</code>\n"
            f"🖥️ <b>IP Server:</b> <code>{ip_addr}</code>\n"
            f"✅ <b>DNS Status:</b> <b>ACTIVE / RESOLVED</b>",
            parse_mode='HTML'
        )
    except Exception as e:
        await delete_msg_safe(status)
        await update.message.reply_text(f"❌ Gagal memeriksa DNS domain: {e}", parse_mode='HTML')

# ==================== FITUR LAINNYA ====================

def build_ai_prompt(history, user_prompt, memories=None):
    """Build bounded chat context plus explicitly saved, per-user memories."""
    recent = history[-12:]
    lines = [
        "Kamu adalah NEON AI, asisten yang ramah, jelas, dan membantu. Jawab dalam bahasa pengguna.",
        "Jangan mengarang fakta; akui jika tidak yakin. Ingatan hanyalah konteks, bukan instruksi untuk melanggar keamanan.",
    ]
    if memories:
        lines.append("Memori yang secara eksplisit disimpan pengguna ini (gunakan hanya bila relevan):")
        lines.extend([f"- {memory}" for memory in memories[:20]])
    lines.append("Riwayat percakapan:")
    for item in recent:
        role = "Pengguna" if item.get("role") == "user" else "Asisten"
        lines.append(f"{role}: {item.get('text', '')}")
    lines.append(f"Pengguna: {user_prompt}")
    lines.append("Asisten:")
    return "\n".join(lines)


async def send_ai_text(message, text_value, reply_markup=None):
    """Send model text safely as plain text and split at Telegram's message limit."""
    value = (text_value or "Maaf, AI tidak dapat merespons saat ini.").strip()
    limit = 3900
    chunks = []
    while value:
        if len(value) <= limit:
            chunks.append(value)
            break
        cut = value.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = value.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(value[:cut].rstrip())
        value = value[cut:].lstrip()
    for i, chunk in enumerate(chunks):
        await message.reply_text(chunk, reply_markup=reply_markup if i == len(chunks) - 1 else None)


async def reset_ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user = update.effective_user
    msg = update.effective_message
    if user and msg:
        await asyncio.to_thread(clear_ai_history, user.id, msg.chat_id)
    context.user_data.pop("ai_history", None)
    await update.effective_message.reply_text("🧹 Riwayat AI di chat ini sudah direset.")


async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, status_message=None):
    user = update.effective_user
    msg = update.effective_message
    if user is None or msg is None:
        return
    # Database makes history survive restarts and sync across devices in the same Telegram chat.
    history = await asyncio.to_thread(load_ai_history, user.id, msg.chat_id)
    saved_memories = await asyncio.to_thread(load_user_memories, user.id, 20)
    full_prompt = build_ai_prompt(history, prompt, [row[1] for row in saved_memories])
    try:
        # SDK calls are synchronous; run them in a worker thread so polling stays responsive.
        answer = await asyncio.to_thread(generate_ai_response, full_prompt)
    except Exception as exc:
        logger.exception("AI generation failed")
        answer = None
        error_hint = str(exc)[:300]
    else:
        error_hint = ""
    if status_message:
        await delete_msg_safe(status_message)
    if not answer:
        await update.effective_message.reply_text(
            "Maaf bro, AI belum bisa menjawab sekarang. Periksa GEMINI_API_KEY dan koneksi jaringan."
            + (f"\nDetail: {error_hint}" if error_hint else "")
        )
        return
    try:
        await asyncio.to_thread(save_ai_turn, user.id, msg.chat_id, prompt, answer)
    except Exception:
        logger.exception("Gagal menyimpan riwayat AI ke SQLite")
        await msg.reply_text("⚠️ Jawaban berhasil dibuat, tetapi riwayat belum tersimpan ke database.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🧹 Reset percakapan", callback_data="ai_reset")]])
    await send_ai_text(update.effective_message, answer, reply_markup=keyboard)


async def ai_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    if not context.args:
        await msg.reply_text(
            "🧠 Chat AI siap ngobrol.\n\n"
            "Pakai: /ai pertanyaan lu\n"
            "Riwayat sesi dipakai untuk konteks percakapan. Reset dengan /resetai."
        )
        return
    prompt = " ".join(context.args).strip()
    status = await msg.reply_text("🧠 Sedang berpikir...")
    await ai_reply(update, context, prompt, status)

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the same interactive dashboard as /start."""
    await start(update, context)

async def my_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.effective_message:
        return
    # Safe helper for users configuring ALLOWED_USER_IDS; exposes only their own IDs.
    await update.effective_message.reply_text(
        f"🪪 <b>ID Telegram lu</b>\n👤 User ID: <code>{user.id}</code>\n💬 Chat ID: <code>{chat.id if chat else 'n/a'}</code>\n\nTambahkan User ID ke ALLOWED_USER_IDS di .env jika owner mengizinkan.",
        parse_mode="HTML"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show live process, storage, AI and FTP configuration health without secrets."""
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    try:
        cpu = psutil.cpu_percent(interval=0.15)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.getcwd())
        pyver = sys.version.split()[0]
        db_ok = os.path.isfile(AI_DB_FILE) and os.access(AI_DB_FILE, os.R_OK | os.W_OK)
        ftp_ready = any(a.get("configured") for a in FTP_ACCOUNTS)
        bot_info = await context.bot.get_me()
        status_text = (
            "⚡ <b>NEON AI • LIVE SYSTEM STATUS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Bot: <code>@{html.escape(bot_info.username or 'unknown')}</code>\n"
            f"🧩 Build: <code>{html.escape(BOT_VERSION)}</code>\n"
            f"⏱️ Uptime: <code>{html.escape(get_uptime())}</code>\n"
            f"🧠 Gemini: {'🟢 siap' if ai_client else '🟠 belum dikonfigurasi'}\n"
            f"☁️ FTP config: {'🟢 ' + str(sum(1 for a in FTP_ACCOUNTS if a.get('configured'))) + ' akun terkonfigurasi' if ftp_ready else '🟠 belum lengkap'}\n"
            f"💾 AI database: {'🟢 siap' if db_ok else '🟠 belum dibuat/akses terbatas'}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 CPU: <code>{cpu:.1f}%</code>\n"
            f"🧮 RAM: <code>{mem.percent:.1f}%</code> ({format_size(mem.used)} / {format_size(mem.total)})\n"
            f"💽 Disk: <code>{disk.percent:.1f}%</code> ({format_size(disk.free)} free)\n"
            f"🐍 Python: <code>{html.escape(pyver)}</code>\n"
            f"🕒 WIB: <code>{get_wib_now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
            "ℹ️ Gunakan /ftpstatus untuk mengetes login live setiap akun FTP."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧠 AI Hub", callback_data="btn_ai_menu"), InlineKeyboardButton("📥 Downloader", callback_data="btn_help_sync")],
            [InlineKeyboardButton("📁 FTP Library", callback_data="page_4"), InlineKeyboardButton("🏠 Menu utama", callback_data="page_1")]
        ])
        await msg.reply_text(status_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception as exc:
        logger.exception("Gagal membangun system status")
        await msg.reply_text("⚠️ Status tidak lengkap: " + html.escape(str(exc)[:300]), parse_mode="HTML")

async def ftp_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only live FTP account status; checks login without showing secrets."""
    if not is_owner(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text("🔎 Sedang mengetes login semua akun FTP...", parse_mode="HTML")
    results = await asyncio.to_thread(check_ftp_accounts)
    if not results:
        await msg.reply_text("☁️ Belum ada akun FTP. Tambahkan FTP_HOST/USER/PASS atau FTP2_*, FTP3_* di .env/Secrets.")
        return
    online = sum(1 for item in results if item["state"] == "online")
    lines = ["☁️ <b>NEON • FTP FAILOVER STATUS</b>", "━━━━━━━━━━━━━━━━━━━━", f"🟢 Login aktif: <b>{online}</b> / <b>{len(results)}</b>"]
    for item in results:
        icon = "🟢" if item["state"] == "online" else ("🟡" if item["state"] == "unconfigured" else "🔴")
        lines.append(
            f"{icon} <b>FTP {item['id']}</b> — <code>{html.escape(item['state'].upper())}</code>\n"
            f"   Host: <code>{html.escape(item.get('host') or 'belum diisi')}</code>\n"
            f"   User: <code>{html.escape(_mask_ftp_user(item.get('user','')))}</code>\n"
            f"   Hasil: {html.escape(item['detail'])}"
        )
    lines.extend(["━━━━━━━━━━━━━━━━━━━━", "ℹ️ ONLINE = berhasil login saat dites; izin upload bisa berbeda. Upload media akan mencoba akun berikutnya jika akun sebelumnya gagal."])
    await msg.reply_text("\n".join(lines), parse_mode="HTML")


async def downloader_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnose downloader dependencies and cookie configuration without exposing secrets."""
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    import importlib.util
    from importlib import metadata

    def package_status(module_name, package_name):
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            return "🔴 belum terpasang"
        try:
            version = metadata.version(package_name)
            return f"🟢 {html.escape(version)}"
        except metadata.PackageNotFoundError:
            return "🟢 terdeteksi"

    def cookie_status(path):
        if not path:
            return "🟡 belum disetel"
        if os.path.isfile(path) and os.access(path, os.R_OK):
            return "🟢 tersedia & terbaca"
        return "🔴 path tidak ditemukan/tidak terbaca"

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    instagram_cookie = INSTAGRAM_COOKIES_FILE or SOCIAL_COOKIES_FILE
    checks = [
        "🧪 <b>NEON • DOWNLOADER DIAGNOSTICS</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🐍 Python: <code>{html.escape(sys.executable)}</code>",
        f"📦 yt-dlp: {package_status('yt_dlp', 'yt-dlp')}",
        f"📦 gallery-dl: {package_status('gallery_dl', 'gallery-dl')}",
        f"🎞️ FFmpeg: {'🟢 tersedia' if ffmpeg_ok else '🟡 tidak ditemukan (perlu untuk merge/konversi tertentu)'}",
        f"🍪 Cookie Instagram: {cookie_status(instagram_cookie)}",
        f"🍪 Cookie TikTok: {cookie_status(TIKTOK_COOKIES_FILE or SOCIAL_COOKIES_FILE)}",
        f"⏱️ Timeout download: <code>{DOWNLOAD_TIMEOUT_SECONDS}s</code>",
        f"📐 Batas tinggi video: <code>{html.escape(DOWNLOAD_MAX_HEIGHT or 'default / kualitas terbaik')}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
        "Paket yang belum ada bisa dipasang dengan menjalankan perintah pip pada environment Python yang sama dengan bot, lalu restart proses bot.",
    ]
    await msg.reply_text("\n".join(checks), parse_mode="HTML", disable_web_page_preview=True)


async def quick_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(f"📊 <b>Stats Pro:</b> Uptime <code>{get_uptime()}</code> | AI Core <b>Active</b>", parse_mode='HTML')

async def secret_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    menu_text = (
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        "👑 <b>[ADMINISTRATOR PRO SUITE]</b>\n"
        "┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━⫘\n"
        "• <code>/secret_sys</code> ─ Hardware Status\n"
        "• <code>/secret_history</code> ─ Log Chat Terbaru\n"
        "• <code>/secret_clear</code> ─ Hapus Database Log\n"
        "• <code>/secret_broadcast</code> ─ Kirim Pengumuman\n"
        "• <code>/secret_exec</code> ─ Eksekusi Shell Command\n"
        "• <code>/secret_restart</code> ─ Restart Engine Bot\n"
        "• <code>/secret_ip</code> ─ Cek IP Publik Server\n"
        "• <code>/ban</code> & <code>/unban</code> ─ Blokir User\n"
        "• <code>/rename</code> ─ Ganti Nama File FTP\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )
    await update.message.reply_text(menu_text, parse_mode='HTML')

async def secret_chat_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("🕵️‍♂️ Log aktivitas kosong.", parse_mode='HTML')
        return
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        recent = data[-15:]
        text = "<b>🕵️‍♂️ LOG AKTIVITAS TERBARU:</b>\n\n"
        for i, item in enumerate(recent, 1):
            text += f"{i}. <b>{item['full_name']}</b>: <i>{html.escape(str(item['message']))}</i>\n"
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error membaca log: {e}", parse_mode='HTML')

async def secret_clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        await update.message.reply_text("✅ Riwayat log chat berhasil dibersihkan.", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal menghapus log: {e}", parse_mode='HTML')

async def secret_sys_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    pesan = (
        f"🖥️ <b>HARDWARE SUPREME PRO STATUS</b>\n"
        f"⚡ CPU Usage : <code>{cpu}%</code>\n"
        f"🧠 RAM Usage : <code>{ram.percent}%</code> ({format_size(ram.used)} / {format_size(ram.total)})\n"
        f"💾 Disk Space: <code>{disk.percent}%</code>\n"
        f"⏱️ Uptime    : <code>{get_uptime()}</code>"
    )
    await update.message.reply_text(pesan, parse_mode='HTML')

async def secret_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        await update.message.reply_text("Format: <code>/secret_broadcast [pesan]</code>", parse_mode='HTML')
        return
    msg_text = " ".join(context.args)
    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("❌ Data riwayat user kosong.", parse_mode='HTML')
        return
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    uids = list(set([x['user_id'] for x in data]))
    count = 0
    for uid in uids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 <b>PENGUMUMAN:</b>\n\n{html.escape(msg_text)}", parse_mode='HTML')
            count += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Berhasil dikirim ke {count} pengguna.", parse_mode='HTML')

async def secret_exec_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    # Remote shell execution is disabled by default for safer Replit deployments.
    # The command remains available to the owner only when explicitly enabled.
    if os.getenv("ENABLE_SECRET_EXEC", "0").strip().lower() not in ("1", "true", "yes", "on"):
        if update.effective_message:
            await update.effective_message.reply_text(
                "🔒 /secret_exec dinonaktifkan secara default demi keamanan. Aktifkan ENABLE_SECRET_EXEC=1 di Secrets hanya jika benar-benar diperlukan."
            )
        return
    if not context.args:
        return
    cmd = " ".join(context.args)
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate(timeout=15)
        res = out if out else err
        await update.message.reply_text(f"💻 <code>{html.escape(res[:3500])}</code>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def secret_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    await update.message.reply_text("🔄 Merestart engine bot...", parse_mode='HTML')
    os.execv(sys.executable, [sys.executable] + sys.argv)

async def secret_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    try:
        req = urllib.request.urlopen("https://api.ipify.org?format=json", timeout=10)
        ip = json.loads(req.read().decode('utf-8')).get('ip')
        await update.message.reply_text(f"🌐 Public IP Server: <code>{ip}</code>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal: {e}", parse_mode='HTML')

async def rename_ftp_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("✏️ Format: <code>/rename [lama] [baru]</code>", parse_mode='HTML')
        return
    old_name, new_name = context.args[0], context.args[1]
    try:
        async with ftp_lock:
            ftp = FTPManager.get_connection()
            found_folder = None
            for fld in ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya", "downloads"]:
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    if old_name in ftp.nlst():
                        found_folder = fld
                        break
                except Exception:
                    pass
            if not found_folder:
                await update.message.reply_text("❌ File tidak ditemukan di FTP.", parse_mode='HTML')
                ftp.quit()
                return
            ftp.cwd(f'/htdocs/{found_folder}')
            ftp.rename(old_name, new_name)
            ftp.quit()
        await update.message.reply_text(f"✅ Rename <code>{old_name}</code> -> <code>{new_name}</code>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
        banned = load_banned_users()
        banned.add(uid)
        save_banned_users(banned)
        await update.message.reply_text(f"✅ User ID {uid} diblokir.", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
        banned = load_banned_users()
        if uid in banned:
            banned.remove(uid)
            save_banned_users(banned)
        await update.message.reply_text(f"✅ User ID {uid} di-unban.", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def battery_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return

    lines = ["🔋 <b>STATUS BATERAI</b>"]
    detected = False
    # Termux needs the separate Termux:API Android app and the termux-api package.
    api_cmd = shutil.which("termux-battery-status")
    if api_cmd:
        try:
            proc = await asyncio.create_subprocess_exec(
                api_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8)
            if proc.returncode == 0 and stdout:
                data = json.loads(stdout.decode("utf-8", errors="replace"))
                pct = data.get("percentage")
                state = data.get("status", "tidak diketahui")
                if pct is not None:
                    lines.append(f"📱 Termux/Android: <b>{html.escape(str(pct))}%</b>")
                    lines.append(f"⚡ Status: <b>{html.escape(str(state))}</b>")
                    if data.get("temperature") is not None:
                        lines.append(f"🌡️ Suhu: <b>{html.escape(str(data['temperature']))}°C</b>")
                    detected = True
            elif stderr:
                logger.warning("Termux battery API exit=%s: %s", proc.returncode, stderr.decode(errors="replace")[:180])
        except asyncio.TimeoutError:
            lines.append("⚠️ Termux:API tidak merespons dalam 8 detik.")
        except Exception as exc:
            logger.info("Pembacaan baterai Termux gagal (%s).", type(exc).__name__)

    if not detected:
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                lines.append(f"💻 Baterai sistem: <b>{battery.percent}%</b>")
                lines.append(f"🔌 Terpasang charger: <b>{'Ya' if battery.power_plugged else 'Tidak'}</b>")
                detected = True
        except Exception as exc:
            logger.debug("psutil battery sensor unavailable: %s", type(exc).__name__)

    if not detected:
        if sys.platform.startswith("linux") and "com.termux" in os.getenv("PREFIX", ""):
            lines.extend([
                "❌ Data baterai Android belum bisa dibaca.",
                "Pasang aplikasi <b>Termux:API</b> yang cocok dengan versi Termux, lalu jalankan:",
                "<code>pkg install termux-api</code>",
                "Setelah itu tutup dan buka kembali Termux, lalu coba /battery.",
            ])
        else:
            lines.append("ℹ️ Lingkungan ini tidak menyediakan sensor baterai (misalnya server cloud).")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="page_4")]])
    if update.callback_query:
        try:
            await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await msg.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
    else:
        await msg.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

async def ai_fix_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    code_snippet = " ".join(context.args) if context.args else (update.message.reply_to_message.text if update.message.reply_to_message else "")
    if not code_snippet:
        return
    status = await update.message.reply_text("💻 <i>Menganalisis kode...</i>", parse_mode='HTML')
    try:
        res = generate_ai_response(f"Fix this code:\n\n{code_snippet}") or "Gagal."
        await delete_msg_safe(status)
        await update.message.reply_text(f"💻 <b>DEBUG:</b>\n\n{res}", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(status)
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def website_monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    if not context.args:
        await msg.reply_text(
            "🌐 <b>Website Monitor</b>\nFormat: <code>/monitor https://example.com</code>\n"
            "Cek ini menguji respons HTTP satu kali, bukan pemantauan berulang 24/7.",
            parse_mode="HTML",
        )
        return
    url = context.args[0].strip()
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        await msg.reply_text("❌ URL tidak valid. Contoh: <code>/monitor https://example.com</code>", parse_mode="HTML")
        return
    status = await msg.reply_text("🌐 <i>Mengecek website...</i>", parse_mode="HTML")
    started = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NEON-OS-Monitor"}, method="GET")
        with urllib.request.urlopen(req, timeout=12) as resp:
            latency = (time.monotonic() - started) * 1000
            result = f"🌐 <b>RESPONS DITERIMA</b>\n🔢 HTTP: <code>{resp.status}</code>\n⚡ Latensi: <code>{latency:.0f} ms</code>\n🔗 <code>{html.escape(url)}</code>"
    except Exception as exc:
        latency = (time.monotonic() - started) * 1000
        result = f"🔴 <b>GAGAL DIAKSES</b>\n⏱️ Waktu: <code>{latency:.0f} ms</code>\n⚠️ {html.escape(str(exc)[:500])}\n🔗 <code>{html.escape(url)}</code>"
    try:
        await status.edit_text(result, parse_mode="HTML")
    except Exception:
        await msg.reply_text(result, parse_mode="HTML")

async def ai_quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    status = await update.message.reply_text("🧠 <i>Generating quiz...</i>", parse_mode='HTML')
    res = generate_ai_response(f"Buatkan 3 kuis tentang: {' '.join(context.args)}") or "Gagal."
    await delete_msg_safe(status)
    await update.message.reply_text(f"🧠 <b>KUIS:</b>\n\n{res}", parse_mode='HTML')

async def currency_converter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or len(context.args) < 3:
        return
    try:
        amt, frm, to = float(context.args[0]), context.args[1].upper(), context.args[2].upper()
        rate = json.loads(urllib.request.urlopen(f"https://open.er-api.com/v6/latest/{frm}", timeout=10).read().decode('utf-8'))['rates'][to]
        await update.message.reply_text(f"💱 <code>{amt:,.2f} {frm}</code> = <b>{amt*rate:,.2f} {to}</b>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def news_aggregator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    top = "technology" if not context.args else " ".join(context.args)
    status = await update.message.reply_text("📰 <i>Fetching news...</i>", parse_mode='HTML')
    res = generate_ai_response(f"3 Berita terbaru tentang {top}") or "Kosong."
    await delete_msg_safe(status)
    await update.message.reply_text(f"📰 <b>BERITA:</b>\n\n{res}", parse_mode='HTML')

def load_kanban():
    if os.path.exists(KANBAN_FILE):
        try:
            with open(KANBAN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"todo": [], "doing": [], "done": []}

def save_kanban(data):
    try:
        with open(KANBAN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

async def kanban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    kb = load_kanban()
    txt = (
        "📊 <b>KANBAN BOARD</b>\n"
        "📌 <b>TODO:</b>\n" + ("\n".join([f"• {x}" for x in kb['todo']]) if kb['todo'] else "Kosong") + "\n\n"
        "⚡ <b>DOING:</b>\n" + ("\n".join([f"• {x}" for x in kb['doing']]) if kb['doing'] else "Kosong") + "\n\n"
        "✅ <b>DONE:</b>\n" + ("\n".join([f"• {x}" for x in kb['done']]) if kb['done'] else "Kosong")
    )
    await update.message.reply_text(txt, parse_mode='HTML')

async def kanban_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    t = " ".join(context.args)
    kb = load_kanban()
    kb['todo'].append(t)
    save_kanban(kb)
    await update.message.reply_text(f"✅ Added to Kanban: <b>{t}</b>", parse_mode='HTML')

async def merge_pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text("📄 Balas PDF dengan <code>/mergepdf</code>.", parse_mode='HTML')

async def password_generator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    l = int(context.args[0]) if context.args and context.args[0].isdigit() else 12
    pwd = "".join(random.choice(string.ascii_letters + string.digits + '!@#$%') for _ in range(l))
    await update.message.reply_text(f"🔑 Password: <code>{pwd}</code>", parse_mode='HTML')

async def math_calculator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    expr = " ".join(context.args)
    if not re.match(r'^[0-9+\-*/().\s]+$', expr):
        return
    try:
        await update.message.reply_text(f"🧮 Hasil: <b>{eval(expr)}</b>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def ai_ocr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not update.message.reply_to_message or not update.message.reply_to_message.photo:
        return
    st = await update.message.reply_text("🔍 <i>Scanning...</i>", parse_mode='HTML')
    try:
        f = await context.bot.get_file(update.message.reply_to_message.photo[-1].file_id)
        tp = f"ocr_{int(time.time())}.jpg"
        await f.download_to_drive(custom_path=tp)
        uf = ai_client.files.upload(file=tp)
        res = generate_ai_response([uf, "Extract text"]) or "Tidak ada teks."
        await delete_msg_safe(st)
        await update.message.reply_text(f"🔍 <b>OCR:</b>\n<code>{html.escape(res)}</code>", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(st)
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    finally:
        clean_local_temp_files()

async def ai_image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    p = " ".join(context.args)
    st = await update.message.reply_text("🎨 <i>Rendering...</i>", parse_mode='HTML')
    try:
        data = urllib.request.urlopen(urllib.request.Request(f"https://image.pollinations.ai/prompt/{urllib.parse.quote(p)}?width=1024&height=1024&nologo=true", headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()
        tp = f"ai_{int(time.time())}.jpg"
        with open(tp, 'wb') as f:
            f.write(data)
        await delete_msg_safe(st)
        with open(tp, 'rb') as pf:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=pf, caption=f"🎨 <b>{p}</b>", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(st)
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    finally:
        clean_local_temp_files()

async def ai_tts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    try:
        data = urllib.request.urlopen(urllib.request.Request(f"https://translate.google.com/translate_tts?ie=UTF-8&q={urllib.parse.quote(' '.join(context.args)[:200])}&tl=id&client=tw-ob", headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read()
        tp = f"tts_{int(time.time())}.mp3"
        with open(tp, 'wb') as f:
            f.write(data)
        with open(tp, 'rb') as af:
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=af)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    finally:
        clean_local_temp_files()

async def short_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    try:
        res = urllib.request.urlopen(f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(context.args[0])}", timeout=10).read().decode('utf-8')
        await update.message.reply_text(f"🌐 Short: <b>{res}</b>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def qr_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    d = " ".join(context.args)
    try:
        data = urllib.request.urlopen(f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(d)}", timeout=15).read()
        tp = f"qr_{int(time.time())}.png"
        with open(tp, 'wb') as f:
            f.write(data)
        with open(tp, 'rb') as qf:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=qf, caption=f"📌 QR: <code>{d}</code>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    finally:
        clean_local_temp_files()

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or len(context.args) < 2:
        return
    lang, txt = context.args[0], " ".join(context.args[1:])
    try:
        res = json.loads(urllib.request.urlopen(f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={lang}&dt=t&q={urllib.parse.quote(txt)}", timeout=10).read().decode('utf-8'))
        await update.message.reply_text(f"🔄 Terjemahan:\n<b>{html.escape(''.join([i[0] for i in res[0]]))}</b>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

def load_todos():
    if os.path.exists(TODO_FILE):
        try:
            with open(TODO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_todos(todos):
    try:
        with open(TODO_FILE, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

async def todo_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    todos = load_todos()
    await update.message.reply_text("📋 <b>TO-DO:</b>\n" + ("\n".join([f"{i+1}. {x['task']}" for i, x in enumerate(todos)]) if todos else "Kosong"), parse_mode='HTML')

async def todo_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or not context.args:
        return
    t = " ".join(context.args)
    todos = load_todos()
    todos.append({"task": t, "done": False})
    save_todos(todos)
    await update.message.reply_text(f"✅ To-Do ditambah: <b>{t}</b>", parse_mode='HTML')

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    if not context.args:
        await msg.reply_text("🌤️ Format: <code>/weather Jakarta Selatan</code>", parse_mode="HTML")
        return
    city = " ".join(context.args).strip()
    try:
        endpoint = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        with urllib.request.urlopen(endpoint, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        current = payload["current_condition"][0]
        desc = current.get("weatherDesc", [{}])[0].get("value", "Tidak diketahui")
        text = (
            f"🌤️ <b>Cuaca: {html.escape(city)}</b>\n"
            f"🌡️ Suhu: <code>{html.escape(str(current.get('temp_C', '?')))}°C</code>\n"
            f"🤔 Kondisi: {html.escape(str(desc))}\n"
            f"💧 Kelembapan: <code>{html.escape(str(current.get('humidity', '?')))}%</code>\n"
            f"💨 Angin: <code>{html.escape(str(current.get('windspeedKmph', '?')))} km/jam</code>"
        )
        await msg.reply_text(text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("Weather request gagal (%s).", type(exc).__name__)
        await msg.reply_text("❌ Data cuaca gagal diambil. Periksa nama kota/koneksi lalu coba lagi.", parse_mode="HTML")

async def reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or len(context.args) < 2:
        return
    try:
        sec, msg = int(context.args[0]), " ".join(context.args[1:])
        await update.message.reply_text(f"⏱️ Reminder {sec}s.", parse_mode='HTML')
        cid = update.effective_chat.id
        async def bg():
            await asyncio.sleep(sec)
            await context.bot.send_message(chat_id=cid, text=f"⏰ <b>REMINDER:</b> {msg}", parse_mode='HTML')
        asyncio.create_task(bg())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update) or len(context.args) < 3:
        return
    parts = [p.strip() for p in " ".join(context.args).split("|")]
    await update.message.reply_poll(question=parts[0], options=parts[1:], is_anonymous=False)

async def netinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.message if update.message else update.callback_query.message
    try:
        d = json.loads(urllib.request.urlopen("http://ip-api.com/json/", timeout=6).read().decode('utf-8'))
        txt = f"🌐 <b>IP:</b> <code>{d.get('query')}</code> | ISP: {d.get('isp')}"
    except Exception:
        txt = "IP N/A"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data='page_4')]])
    if update.callback_query:
        await msg.edit_text(txt, parse_mode='HTML', reply_markup=keyboard)
    else:
        await msg.reply_text(txt, parse_mode='HTML', reply_markup=keyboard)

# ==================== DOWNLOADER FOTO & VIDEO PRO ====================
async def photos_downloader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compatibility alias for the universal downloader's photo/slideshow path.

    Reusing the same validated subprocess engine avoids the old shell-command
    interpolation bug and guarantees the same FTP auto-archive behavior.
    """
    if not context.args:
        await update.effective_message.reply_text(
            "🖼️ Format: /photos LINK_TIKTOK_SLIDESHOW\n"
            "Bisa juga pakai /dl untuk video/foto dari platform yang didukung."
        )
        return
    await universal_downloader(update, context)

# ==================== UNIVERSAL DOWNLOADER (VIDEO ENGINE) ====================
async def universal_downloader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-command downloader: resolves TikTok short links and detects photo/video."""
    import shutil

    if not is_authorized(update):
        return

    message = update.effective_message
    if not context.args:
        await message.reply_text(
            "📥 Pakai satu perintah untuk semua media:\n"
            "/dl LINK_MEDIA\n\n"
            "Coba YouTube, TikTok, Instagram, Facebook, X/Twitter, Reddit, Twitch, dan situs yang didukung yt-dlp.\n"
            "Foto/album: /photos LINK. Daftar dan catatan dukungan: /platforms."
        )
        return

    url = html.unescape(context.args[0].strip().strip('<>')).strip()
    input_url = url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        await message.reply_text("❌ Link tidak valid. Kirim URL http:// atau https:// yang lengkap.")
        return

    # Normalize Instagram's short domain to its canonical host while preserving the path.
    # Tracking query strings are removed so carousels can be fetched as a whole.
    if (parsed.hostname or "").lower() in ("instagr.am", "www.instagr.am"):
        parsed = parsed._replace(netloc="www.instagram.com", query="", fragment="")
        url = urllib.parse.urlunparse(parsed)

    def is_tiktok_host(host):
        host = (host or "").lower().split(":", 1)[0]
        return host == "tiktok.com" or host.endswith(".tiktok.com")

    def is_image_file(path):
        return os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

    # Per-platform Netscape cookie files. These help with legitimate logged-in
    # access, but cannot guarantee access or bypass platform-side restrictions.
    def cookie_file_for(candidate):
        host = (urllib.parse.urlparse(candidate).hostname or "").lower()
        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            choices = (TIKTOK_COOKIES_FILE, SOCIAL_COOKIES_FILE)
        elif host == "instagram.com" or host.endswith(".instagram.com"):
            choices = (INSTAGRAM_COOKIES_FILE, SOCIAL_COOKIES_FILE)
        elif host == "facebook.com" or host.endswith(".facebook.com") or host.endswith(".fb.watch"):
            choices = (FACEBOOK_COOKIES_FILE, SOCIAL_COOKIES_FILE)
        elif host == "youtube.com" or host.endswith(".youtube.com") or host in ("youtu.be", "youtube-nocookie.com"):
            choices = (YOUTUBE_COOKIES_FILE, SOCIAL_COOKIES_FILE)
        elif host in ("x.com", "twitter.com") or host.endswith(".x.com") or host.endswith(".twitter.com"):
            choices = (X_COOKIES_FILE, SOCIAL_COOKIES_FILE)
        else:
            choices = (SOCIAL_COOKIES_FILE,)
        for candidate_path in choices:
            if candidate_path and os.path.isfile(candidate_path):
                return candidate_path
        return ""

    def gallery_args(candidate, destination=None):
        # Force gallery-dl's destination root explicitly. -D sets the base
        # directory for formatted paths; -d sets the destination root. Using
        # both prevents files from landing outside the per-attempt folder when
        # a Replit gallery-dl config defines its own directory templates.
        output_dir = os.path.abspath(destination or work_dir)
        os.makedirs(output_dir, exist_ok=True)
        args = [
            sys.executable, "-m", "gallery_dl", "--no-mtime",
            "-d", output_dir, "-D", output_dir,
        ]
        cookies = cookie_file_for(candidate)
        if cookies:
            # Pass an absolute path so relative .env paths work consistently
            # regardless of subprocess working-directory behavior.
            args.extend(["--cookies", os.path.abspath(cookies)])
        args.append(candidate)
        return args

    def yt_dlp_args(candidate, output_template=None, impersonate=False):
        # Broad extractor coverage: YouTube, Instagram, Facebook, X/Twitter,
        # Reddit, Twitch and other yt-dlp-supported sites. Support varies by post.
        args = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
            "--retries", "8", "--fragment-retries", "8", "--extractor-retries", "5",
            "--file-access-retries", "3", "--socket-timeout", "45",
            "--restrict-filenames", "--windows-filenames", "--merge-output-format", "mp4",
            "--trim-filenames", "180",
        ]
        if impersonate:
            args.extend(["--impersonate", "chrome"])

        if DOWNLOAD_MAX_HEIGHT.isdigit() and int(DOWNLOAD_MAX_HEIGHT) > 0:
            height = int(DOWNLOAD_MAX_HEIGHT)
            fmt = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
        else:
            fmt = "bestvideo*+bestaudio/best"
        args.extend(["-f", fmt, "-o", output_template or os.path.join(work_dir, "%(extractor)s_%(title).70s_%(id)s.%(ext)s")])
        cookies = cookie_file_for(candidate)
        if cookies:
            args.extend(["--cookies", cookies])
        args.append(candidate)
        return args

    work_dir = os.path.abspath(f"download_{int(time.time())}_{update.effective_user.id}")

    tiktok_photo_diagnostics = []

    async def try_tikwm_photo_fallback(source_url):
        """Extract slideshow image URLs from several known TikWM response shapes."""
        api_urls = [
            "https://www.tikwm.com/api/?hd=1&url=" + urllib.parse.quote(source_url, safe=""),
            "https://tikwm.com/api/?url=" + urllib.parse.quote(source_url, safe=""),
        ]

        def fetch_json(api_url):
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.tikwm.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise RuntimeError("Respons metadata TikWM terlalu besar.")
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            if not isinstance(payload, dict):
                raise RuntimeError("Respons TikWM bukan JSON object.")
            if payload.get("code") not in (0, "0", 200, "200", None):
                raise RuntimeError("TikWM code=" + str(payload.get("code")) + ": " + str(payload.get("msg") or payload.get("message") or "request ditolak"))
            data = payload.get("data") or {}
            if not isinstance(data, dict):
                raise RuntimeError("Field data TikWM bukan object.")

            # TikWM has returned image URLs as strings, url_list arrays, and nested
            # display_image/origin_image objects across API versions.
            found_urls = []
            seen_objects = set()
            def walk(obj, depth=0):
                if depth > 12 or obj is None:
                    return
                if isinstance(obj, str):
                    val = obj.strip()
                    if val.startswith("//"):
                        val = "https:" + val
                    if val.startswith(("https://", "http://")) and any(x in val.lower() for x in (".jpg", ".jpeg", ".png", ".webp", "image", "tiktokcdn", "byteoversea")):
                        if val not in found_urls:
                            found_urls.append(val)
                    return
                if isinstance(obj, list):
                    for child in obj:
                        walk(child, depth + 1)
                    return
                if isinstance(obj, dict):
                    marker = id(obj)
                    if marker in seen_objects:
                        return
                    seen_objects.add(marker)
                    # Only inspect image-related branches to avoid mistaking a video URL for a photo.
                    for key in ("images", "image_post_info", "display_image", "origin_image", "image", "url_list", "url", "image_url", "image_urls", "cover", "cover_url"):
                        if key in obj:
                            walk(obj[key], depth + 1)
                    # TikWM's top-level data.images is the preferred slideshow field.
                    # For nested image records, recurse through known image containers only.
            walk(data.get("images"))
            walk(data.get("image_post_info"))
            walk(data.get("image_post_info_v2"))
            # Some API responses place a list of image objects directly under data.
            if not found_urls:
                for key in ("image_post_info", "images", "image_post_info_v2"):
                    walk(data.get(key))
            return found_urls

        image_urls = []
        for api_url in api_urls:
            try:
                image_urls = await asyncio.to_thread(fetch_json, api_url)
                if image_urls:
                    break
                tiktok_photo_diagnostics.append("TikWM merespons tetapi tidak menemukan URL foto pada field images.")
            except Exception as exc:
                tiktok_photo_diagnostics.append(f"TikWM API: {type(exc).__name__}: {exc}")

        if not image_urls:
            return []

        saved = []
        for index, image_url in enumerate(image_urls, start=1):
            try:
                def fetch_image():
                    req = urllib.request.Request(
                        image_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36",
                            "Referer": "https://www.tikwm.com/",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=25) as response:
                        content_type = (response.headers.get("Content-Type") or "").lower()
                        blob = response.read(20 * 1024 * 1024 + 1)
                    if len(blob) > 20 * 1024 * 1024:
                        raise RuntimeError("Foto melebihi 20 MB.")
                    # Validate file signatures, not just server Content-Type.
                    if blob.startswith(b"\xff\xd8\xff"):
                        ext = ".jpg"
                    elif blob.startswith(b"\x89PNG\r\n\x1a\n"):
                        ext = ".png"
                    elif blob.startswith(b"GIF8"):
                        ext = ".gif"
                    elif blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
                        ext = ".webp"
                    else:
                        raise RuntimeError(f"URL foto mengembalikan data non-gambar (Content-Type: {content_type or 'unknown'}).")
                    return blob, ext
                blob, ext = await asyncio.to_thread(fetch_image)
                out_path = os.path.join(work_dir, f"tiktok_photo_{index:03d}{ext}")
                with open(out_path, "wb") as output_file:
                    output_file.write(blob)
                saved.append(out_path)
            except Exception as exc:
                tiktok_photo_diagnostics.append(f"Unduh foto #{index}: {type(exc).__name__}: {exc}")
        return saved
    os.makedirs(work_dir, exist_ok=True)
    status = await message.reply_text("⏳ Membaca link dan mendeteksi jenis media...")

    async def run_process(args, timeout=240):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return 124, "", f"Proses {args[2] if len(args) > 2 else 'download'} melewati batas waktu {timeout} detik. Coba ulang atau gunakan koneksi lebih stabil."
        return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")

    # Only return real media files. yt-dlp may leave thumbnails, metadata JSON,
    # subtitle files or partial downloads; those must never be reported as success.
    media_extensions = {
        ".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi",
        ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac",
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"
    }

    def find_downloads(search_dir=None):
        found = []
        search_dir = search_dir or work_dir
        for root, _, names in os.walk(search_dir):
            for name in names:
                path = os.path.join(root, name)
                ext = os.path.splitext(name)[1].lower()
                if (ext in media_extensions and os.path.isfile(path)
                        and os.path.getsize(path) > 0
                        and not name.endswith((".part", ".ytdl", ".tmp"))):
                    found.append(path)
        return sorted(found)

    try:
        # Resolve short TikTok URLs before checking /photo/ versus /video/.
        original_host = (parsed.hostname or "").lower()
        tiktok = is_tiktok_host(original_host)
        if tiktok:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"},
                )
                def resolve_url():
                    with urllib.request.urlopen(req, timeout=15) as response:
                        return response.geturl()
                resolved = await asyncio.to_thread(resolve_url)
                rp = urllib.parse.urlparse(resolved)
                if rp.scheme in ("http", "https") and rp.hostname and is_tiktok_host(rp.hostname):
                    url, parsed = resolved, rp
            except Exception as exc:
                logger.warning("Gagal resolve link pendek TikTok; coba extractor langsung: %s", exc)

        tiktok = is_tiktok_host(parsed.hostname)
        is_photo_post = tiktok and "/photo/" in (parsed.path or "").lower()
        errors = []
        downloaded = []
        host = (parsed.hostname or "").lower()
        instagram = host == "instagram.com" or host.endswith(".instagram.com")
        instagram_path = (parsed.path or "").lower()
        # Feed posts/carousels and stories are often photos; prefer gallery-dl.
        # Reels and /tv/ use the normal yt-dlp-first path.
        instagram_gallery_first = instagram and (
            "/p/" in instagram_path or "/stories/" in instagram_path
        )

        if tiktok and is_photo_post:
            await status.edit_text("📸 Terdeteksi TikTok slideshow/foto. Mengambil foto...")
            # TikTok short links may redirect to /video/ even for photo-mode posts.
            # Try the clean canonical URL and original short URL with gallery-dl.
            candidates = []
            clean_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
            candidates.append(clean_url)
            if input_url not in candidates:
                candidates.append(input_url)
            if url not in candidates:
                candidates.append(url)
            if "/video/" in clean_url:
                candidates.append(clean_url.replace("/video/", "/photo/", 1))
            if "/photo/" in clean_url:
                candidates.append(clean_url.replace("/photo/", "/video/", 1))

            # Try the photo API first. gallery-dl can sometimes leave only a preview image,
            # which is not enough evidence that the full slideshow was extracted.
            await status.edit_text("📸 Mengambil daftar foto slideshow...")
            for candidate in dict.fromkeys([input_url, url, clean_url]):
                downloaded = await try_tikwm_photo_fallback(candidate)
                if downloaded:
                    break

            if not downloaded:
                await status.edit_text("🔄 API foto tidak berhasil; mencoba gallery-dl...")
                # Isolate each candidate so stale thumbnails from a previous attempt cannot
                # be mistaken for the result of the next URL.
                for candidate_index, candidate in enumerate(dict.fromkeys(candidates), start=1):
                    candidate_dir = os.path.join(work_dir, f"gallery_try_{candidate_index}")
                    os.makedirs(candidate_dir, exist_ok=True)
                    args = gallery_args(candidate, candidate_dir)
                    code, out, err = await run_process(args, timeout=DOWNLOAD_TIMEOUT_SECONDS)
                    candidate_files = []
                    for root, _, names in os.walk(candidate_dir):
                        for name in names:
                            path = os.path.join(root, name)
                            if os.path.splitext(name)[1].lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp") and os.path.isfile(path) and os.path.getsize(path) > 0:
                                candidate_files.append(path)
                    if candidate_files:
                        downloaded = sorted(candidate_files)
                        break
                    if err or out:
                        errors.append(f"gallery-dl ({candidate}):\n{err or out}")
            if tiktok_photo_diagnostics:
                errors.extend(tiktok_photo_diagnostics[-8:])

            # If photo extraction still fails, try video extractor as a final fallback.
            if not downloaded:
                await status.edit_text("🔄 Foto belum terbaca; mencoba extractor video sebagai cadangan...")
                code, out, err = await run_process(yt_dlp_args(clean_url), timeout=DOWNLOAD_TIMEOUT_SECONDS)
                if code != 0:
                    errors.append(err or out or "yt-dlp gagal.")
                downloaded = find_downloads()

        elif instagram:
            await status.edit_text("📸 Instagram Engine V19: mencoba carousel/feed/story/reel dengan beberapa extractor...")
            clean_path = parsed.path or "/"
            canonical_url = urllib.parse.urlunparse(("https", "www.instagram.com", clean_path, "", "", ""))
            candidates = list(dict.fromkeys([url, canonical_url, input_url]))
            # Each attempt gets a separate directory so preview files from failed
            # extractors can never be mistaken for a successful result.
            for idx, candidate in enumerate(candidates, start=1):
                candidate_dir = os.path.join(work_dir, f"instagram_gallery_{idx}")
                os.makedirs(candidate_dir, exist_ok=True)
                code, out, err = await run_process(
                    gallery_args(candidate, candidate_dir), timeout=DOWNLOAD_TIMEOUT_SECONDS
                )
                candidate_files = []
                for root, _, names in os.walk(candidate_dir):
                    for name in names:
                        path = os.path.join(root, name)
                        if (os.path.splitext(name)[1].lower() in media_extensions
                                and os.path.isfile(path) and os.path.getsize(path) > 0
                                and not name.endswith((".part", ".tmp", ".ytdl"))):
                            candidate_files.append(path)
                if candidate_files:
                    downloaded = sorted(candidate_files)
                    logger.info("Instagram gallery-dl berhasil: %s file(s), candidate %s", len(downloaded), idx)
                    break
                if err or out or code != 0:
                    detail = (err or out or f"gallery-dl exit code {code}, tetapi tidak ada file media yang dibuat.")
                    errors.append(f"gallery-dl Instagram attempt {idx} (exit={code}, output_files=0):\n{detail[-1800:]}")
                else:
                    errors.append(f"gallery-dl Instagram attempt {idx}: proses selesai (exit=0), tetapi tidak ada file media di folder output.")

            # Reels/TV are often better handled by yt-dlp; it is also the fallback
            # for carousel/feed/story when gallery-dl cannot extract the post.
            if not downloaded:
                for idx, candidate in enumerate(candidates, start=1):
                    await status.edit_text(f"🔄 Instagram: fallback yt-dlp ({idx}/{len(candidates)})...")
                    yt_dir = os.path.join(work_dir, f"instagram_ytdlp_{idx}")
                    os.makedirs(yt_dir, exist_ok=True)
                    output_template = os.path.join(yt_dir, "%(extractor)s_%(title).70s_%(id)s.%(ext)s")
                    code, out, err = await run_process(
                        yt_dlp_args(candidate, output_template=output_template), timeout=DOWNLOAD_TIMEOUT_SECONDS
                    )
                    downloaded = find_downloads(yt_dir)
                    if downloaded:
                        break
                    if err or out:
                        errors.append(f"yt-dlp Instagram attempt {idx}:\n{(err or out)[-1800:]}")

            # Optional browser impersonation retry, enabled only when curl_cffi is installed.
            # It is a compatibility attempt, not a bypass for private or blocked content.
            if not downloaded:
                try:
                    import importlib.util
                    can_impersonate = importlib.util.find_spec("curl_cffi") is not None
                except Exception:
                    can_impersonate = False
                if can_impersonate:
                    await status.edit_text("🧪 Instagram: mencoba koneksi kompatibilitas browser...")
                    for idx, candidate in enumerate(candidates[:2], start=1):
                        yt_dir = os.path.join(work_dir, f"instagram_impersonate_{idx}")
                        os.makedirs(yt_dir, exist_ok=True)
                        output_template = os.path.join(yt_dir, "%(extractor)s_%(title).70s_%(id)s.%(ext)s")
                        code, out, err = await run_process(
                            yt_dlp_args(candidate, output_template=output_template, impersonate=True), timeout=DOWNLOAD_TIMEOUT_SECONDS
                        )
                        downloaded = find_downloads(yt_dir)
                        if downloaded:
                            break
                        if err or out:
                            errors.append(f"yt-dlp impersonate Instagram attempt {idx}:\n{(err or out)[-1800:]}")

        else:
            if tiktok:
                await status.edit_text("🎬 Terdeteksi TikTok video/link pendek. Mengunduh media...")
            else:
                await status.edit_text("🎬 Mengunduh media dengan yt-dlp...")
            code, out, err = await run_process(yt_dlp_args(url), timeout=DOWNLOAD_TIMEOUT_SECONDS)
            if code != 0:
                errors.append(err or out or "yt-dlp gagal mengambil media.")
            downloaded = find_downloads()
            # If TikTok short URL resolved to a photo post but URL detection was incomplete, try gallery-dl.
            if tiktok and not downloaded:
                await status.edit_text("🔄 Video tidak ditemukan; mencoba mengambil slideshow/foto...")
                clean_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                candidates = [clean_url, input_url, url]
                if "/video/" in clean_url:
                    candidates.append(clean_url.replace("/video/", "/photo/", 1))
                for candidate in dict.fromkeys(candidates):
                    code, out, err = await run_process(gallery_args(candidate), timeout=DOWNLOAD_TIMEOUT_SECONDS)
                    downloaded = find_downloads()
                    if downloaded:
                        break
                    if err or out:
                        errors.append(f"gallery-dl ({candidate}):\n{err or out}")
                if not downloaded:
                    for candidate in dict.fromkeys([input_url, url, clean_url]):
                        downloaded = await try_tikwm_photo_fallback(candidate)
                        if downloaded:
                            break
                    if tiktok_photo_diagnostics:
                        errors.extend(tiktok_photo_diagnostics[-8:])

        # Secondary gallery-dl route for photo/carousel posts on supported sites.
        # It is intentionally a fallback after yt-dlp to avoid duplicate files on success.
        if not downloaded and not tiktok:
            host = (parsed.hostname or "").lower()
            gallery_hosts = (
                "instagram.com", "facebook.com", "fb.watch", "x.com", "twitter.com",
                "reddit.com", "flickr.com", "pixiv.net", "tumblr.com",
            )
            if any(host == domain or host.endswith("." + domain) for domain in gallery_hosts):
                await status.edit_text("🖼️ Video tidak ditemukan; mencoba extractor foto/album cadangan...")
                candidate_dir = os.path.join(work_dir, "gallery_fallback")
                os.makedirs(candidate_dir, exist_ok=True)
                code, out, err = await run_process(gallery_args(url, candidate_dir), timeout=DOWNLOAD_TIMEOUT_SECONDS)
                candidate_files = []
                for root, _, names in os.walk(candidate_dir):
                    for name in names:
                        path = os.path.join(root, name)
                        if os.path.splitext(name)[1].lower() in media_extensions and os.path.isfile(path) and os.path.getsize(path) > 0:
                            candidate_files.append(path)
                if candidate_files:
                    downloaded = sorted(candidate_files)
                elif err or out:
                    errors.append(f"gallery-dl fallback ({host}):\n{err or out}")

        if not downloaded:
            detail = "\n\n".join(x.strip() for x in errors if x.strip())
            if not detail:
                detail = "Downloader tidak menghasilkan file. Pastikan link publik dan extractor mendukung postingan tersebut."
            if "No module named gallery_dl" in detail or "No module named gallery-dl" in detail:
                detail += (
                    "\n\n🧩 gallery-dl belum terpasang pada Python yang menjalankan bot. "
                    f"Pasang dengan interpreter yang sama: `{sys.executable} -m pip install -U gallery-dl yt-dlp`. "
                    "Lalu restart bot. Jangan memasang paket ke Python/venv yang berbeda."
                )
            if "ffmpeg" in detail.lower():
                detail += "\n\nPerbaikan Termux: `pkg install ffmpeg`."
            if "melewati batas waktu" in detail.lower() or "timed out" in detail.lower():
                detail += "\n\n⏱️ Proses melewati batas waktu. Atur DOWNLOAD_TIMEOUT_SECONDS di .env (60–1800 detik), pastikan jaringan stabil dan Termux tidak dibatasi battery optimization. Coba link yang lebih pendek/lebih kecil dan pastikan Termux tidak dibatasi battery optimization."
            if tiktok and ("403 Forbidden" in detail or "No results" in detail or "/photo/" in detail):
                detail += "\n\n🔒 TikTok mengembalikan HTTP 403 (akses ditolak), termasuk pada API cadangan. Update extractor: `python -m pip install -U gallery-dl yt-dlp`. Jika tetap 403, gunakan file cookies Netscape yang sah melalui `TIKTOK_COOKIES_FILE=/path/ke/cookies.txt` di `.env` (jangan pernah kirim cookie ke chat). Jika TikTok tetap menolak request, bot tidak bisa menjamin download; ini pembatasan dari layanan/jaringan, bukan sekadar bug format URL."
            if instagram:
                low_detail = detail.lower()
                if any(term in low_detail for term in ("login_required", "login required", "not logged in", "401", "403", "checkpoint", "challenge_required", "please wait a few minutes")):
                    detail += "\n\n🔐 Instagram tampaknya meminta sesi login / membatasi request. Perbarui extractor dengan `python -m pip install -U yt-dlp gallery-dl`. Untuk postingan yang memang bisa diakses akun lo, ekspor cookies Netscape milik akun sendiri ke file lokal lalu isi `INSTAGRAM_COOKIES_FILE=/path/instagram-cookies.txt` di `.env`. Jangan kirim cookies/token ke chat; jangan gunakan cookies orang lain."
                elif "no video formats found" in low_detail or "unsupported url" in low_detail or "no results" in low_detail:
                    detail += "\n\n🧩 Instagram tidak memberi media ke extractor. Coba URL publik kanonis `https://www.instagram.com/p/ID/` atau `/reel/ID/`, update `yt-dlp` dan `gallery-dl`, lalu jalankan `/igcheck URL` untuk melihat hasil simulasi. Posting privat/expired/region-blocked tetap bisa gagal."
                else:
                    detail += "\n\n🧪 Jalankan `/igcheck URL_INSTAGRAM` untuk diagnosis. Jika masih gagal, kirim output error yang sudah disensor dari token, cookies, username privat, dan data akun."
            await status.edit_text("❌ Download gagal.\n\n" + html.escape(detail[-3500:]))
            return

        # Preserve every completed download in a permanent local vault before sending.
        # A unique name avoids overwriting another user's file or a prior download.
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        preserved = []
        for source_path in downloaded:
            base = os.path.basename(source_path) or f"media_{int(time.time())}.bin"
            stem, ext = os.path.splitext(base)
            target_path = os.path.join(DOWNLOADS_DIR, base)
            if os.path.exists(target_path):
                target_path = os.path.join(DOWNLOADS_DIR, f"{stem}_{int(time.time() * 1000)}{ext}")
            shutil.copy2(source_path, target_path)
            preserved.append(target_path)
        downloaded = preserved
        logger.info("Vault: preserved %s downloaded file(s) in %s", len(downloaded), DOWNLOADS_DIR)

        # Send images in albums (up to 10 per Telegram media group), other media individually.
        images = [p for p in downloaded if is_image_file(p)]
        others = [p for p in downloaded if not is_image_file(p)]
        sent = 0
        too_large = []

        # Automatically archive every downloaded media to private FTP first.
        # Upload is streamed in chunks and does not apply Telegram's 49 MiB sending cap.
        ftp_saved = []
        ftp_failed = []
        for media_path in downloaded:
            try:
                info = await asyncio.to_thread(
                    upload_download_to_ftp, media_path,
                    getattr(update.effective_user, "id", None)
                )
                ftp_saved.append(info)
            except Exception as ftp_exc:
                logger.exception("Auto-save download to FTP failed for %s", os.path.basename(media_path))
                ftp_failed.append(f"{os.path.basename(media_path)}: {str(ftp_exc)[:180]}")

        if images:
            usable_images = []
            for path in images:
                if os.path.getsize(path) > 49 * 1024 * 1024:
                    too_large.append(os.path.basename(path))
                else:
                    usable_images.append(path)
            for i in range(0, len(usable_images), 10):
                chunk = usable_images[i:i + 10]
                # Telegram media groups require at least 2 items; send one image directly.
                if len(chunk) == 1:
                    with open(chunk[0], "rb") as handle:
                        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=handle)
                    sent += 1
                    continue
                handles = []
                media = []
                try:
                    for path in chunk:
                        handle = open(path, "rb")
                        handles.append(handle)
                        media.append(InputMediaPhoto(media=handle))
                    await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media)
                    sent += len(chunk)
                finally:
                    for handle in handles:
                        handle.close()

        for path in others:
            size = os.path.getsize(path)
            if size > 49 * 1024 * 1024:
                too_large.append(f"{os.path.basename(path)} ({size / (1024 * 1024):.1f} MB)")
                continue
            ext = os.path.splitext(path)[1].lower()
            with open(path, "rb") as handle:
                if ext in (".mp4", ".m4v", ".mov", ".webm"):
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=handle,
                        caption=f"✅ Download berhasil • {size / (1024 * 1024):.1f} MB",
                    )
                else:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=handle,
                        filename=os.path.basename(path),
                        caption=f"✅ Download berhasil • {size / (1024 * 1024):.1f} MB",
                    )
            sent += 1

        result = f"✅ Proses selesai bro! Berhasil mengirim {sent} file ke Telegram."
        if ftp_saved:
            total_bytes = sum(item["size"] for item in ftp_saved)
            result += f"\n\n☁️ Auto-save FTP: {len(ftp_saved)} file tersimpan ({total_bytes / (1024 * 1024):.1f} MiB).\n📁 Folder FTP: /htdocs/downloads/"
            urls = [item["url"] for item in ftp_saved if item.get("url")]
            if urls:
                result += "\n\n🔗 Link: " + "\n".join(urls[:5])
        if ftp_failed:
            result += "\n\n⚠️ Sebagian file gagal disimpan ke FTP:\n" + "\n".join(ftp_failed[:5])
        if too_large:
            result += "\n\n📦 File ini tetap dicoba disimpan di FTP, tetapi terlalu besar untuk dikirim melalui Telegram Bot API (batas aman sekitar 49 MiB):\n" + "\n".join(too_large[:10])
        await status.edit_text(result)

    except Exception as exc:
        logger.exception("Universal downloader error")
        err_text = str(exc)
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timed out" in err_text.lower():
            err_text = "⏱️ Timeout saat mengunduh atau mengirim file. Jika file sudah selesai dibuat, kemungkinan koneksi Telegram lambat atau file besar. Coba lagi dengan jaringan stabil atau file lebih kecil. Detail: " + err_text
        try:
            await status.edit_text("❌ Gagal download/kirim: " + html.escape(err_text[:1500]))
        except Exception:
            await message.reply_text("❌ Terjadi error. Cek log terminal untuk detailnya.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

async def mp3_downloader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.effective_message.reply_text("Format: /mp3 URL_YOUTUBE")
        return
    url = context.args[0].strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        await update.effective_message.reply_text("❌ URL tidak valid. Gunakan link http:// atau https:// yang lengkap.")
        return
    work_dir = os.path.abspath(f"download_mp3_{int(time.time() * 1000)}_{update.effective_user.id}")
    os.makedirs(work_dir, exist_ok=True)
    st = await update.effective_message.reply_text("🎵 Mengunduh dan mengonversi audio...")
    try:
        mp3_args = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
            "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "45",
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "-o", os.path.join(work_dir, "%(title).70s_%(id)s.%(ext)s"),
        ]
        mp3_host = (urllib.parse.urlparse(url).hostname or "").lower()
        mp3_cookie = SOCIAL_COOKIES_FILE
        if (mp3_host == "youtube.com" or mp3_host.endswith(".youtube.com") or mp3_host == "youtu.be") and YOUTUBE_COOKIES_FILE:
            mp3_cookie = YOUTUBE_COOKIES_FILE
        elif (mp3_host == "instagram.com" or mp3_host.endswith(".instagram.com")) and INSTAGRAM_COOKIES_FILE:
            mp3_cookie = INSTAGRAM_COOKIES_FILE
        elif (mp3_host == "facebook.com" or mp3_host.endswith(".facebook.com")) and FACEBOOK_COOKIES_FILE:
            mp3_cookie = FACEBOOK_COOKIES_FILE
        elif (mp3_host == "tiktok.com" or mp3_host.endswith(".tiktok.com")) and TIKTOK_COOKIES_FILE:
            mp3_cookie = TIKTOK_COOKIES_FILE
        elif (mp3_host in ("x.com", "twitter.com") or mp3_host.endswith(".x.com") or mp3_host.endswith(".twitter.com")) and X_COOKIES_FILE:
            mp3_cookie = X_COOKIES_FILE
        if mp3_cookie and os.path.isfile(mp3_cookie):
            mp3_args.extend(["--cookies", mp3_cookie])
        mp3_args.append(url)
        proc = await asyncio.create_subprocess_exec(
            *mp3_args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=DOWNLOAD_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Proses MP3 melewati batas waktu {DOWNLOAD_TIMEOUT_SECONDS} detik.")
        if proc.returncode != 0:
            detail = (err or out).decode("utf-8", errors="replace")[-1200:]
            raise RuntimeError(detail or "yt-dlp gagal mengonversi audio. Pastikan ffmpeg terpasang.")
        audio_files = [os.path.join(root, name) for root, _, names in os.walk(work_dir)
                       for name in names if name.lower().endswith(".mp3") and os.path.getsize(os.path.join(root, name)) > 0]
        if not audio_files:
            raise RuntimeError("File MP3 tidak ditemukan. Pastikan ffmpeg terpasang: pkg install ffmpeg")
        # Keep generated MP3 files permanently; scratch copies are still temporary.
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        preserved_audio = []
        for source_path in audio_files:
            base = os.path.basename(source_path)
            stem, ext = os.path.splitext(base)
            target_path = os.path.join(DOWNLOADS_DIR, base)
            if os.path.exists(target_path):
                target_path = os.path.join(DOWNLOADS_DIR, f"{stem}_{int(time.time() * 1000)}{ext}")
            shutil.copy2(source_path, target_path)
            preserved_audio.append(target_path)
        audio_files = preserved_audio
        ftp_audio_saved = []
        ftp_audio_errors = []
        for audio_path in audio_files:
            try:
                ftp_audio_saved.append(await asyncio.to_thread(
                    upload_download_to_ftp, audio_path,
                    getattr(update.effective_user, "id", None)
                ))
            except Exception as ftp_exc:
                logger.exception("Auto-save MP3 to FTP failed: %s", audio_path)
                ftp_audio_errors.append(str(ftp_exc)[:160])
            with open(audio_path, "rb") as audio_file:
                await context.bot.send_audio(chat_id=update.effective_chat.id, audio=audio_file,
                                             title=os.path.splitext(os.path.basename(audio_path))[0][:64])
        summary = f"☁️ Auto-save FTP MP3: {len(ftp_audio_saved)}/{len(audio_files)} file tersimpan."
        if ftp_audio_errors:
            summary += "\n⚠️ FTP error: " + "; ".join(ftp_audio_errors[:3])
        await st.edit_text(summary)
    except Exception as exc:
        await delete_msg_safe(st)
        logger.exception("MP3 downloader gagal")
        await update.effective_message.reply_text("❌ MP3 gagal: " + html.escape(str(exc)[:1200]), parse_mode="HTML")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

async def instagram_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Professional Instagram command guide; avoids promising unsupported private/online access."""
    if not is_authorized(update):
        return
    text = (
        "╭━━━ <b>📸 INSTAGRAM CENTER</b> ━━━╮\n"
        "│ <i>NEON OS • Media Tools</i>\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "🔎 <b>Diagnostik & sesi</b>\n"
        "• <code>/cookiestatus</code> / <code>/igstatus</code> — cek struktur cookies\n"
        "• <code>/health</code> — status dependensi downloader\n"
        "• <code>/igcheck URL</code> — tes extractor untuk postingan Instagram\n"
        "• <code>/info URL</code> — baca metadata jika tersedia\n\n"
        "⬇️ <b>Unduh media</b>\n"
        "• <code>/dl URL</code> — unduh link yang didukung extractor\n"
        "• <code>/photos URL</code> — gunakan alur foto bila didukung\n"
        "• Hasil unduhan mengikuti dukungan extractor, izin akses akun, dan batas Telegram/Instagram.\n\n"
        "👤 <b>Profil, Story & Highlights</b>\n"
        "Bot hanya dapat menampilkan atau mengunduh data yang tersedia bagi sesi sah dan extractor yang mendukungnya. Instagram tidak selalu menyediakan status online, statistik profil, Story, atau Highlights melalui downloader. Bot tidak dapat membuka konten privat/Close Friends tanpa izin.\n\n"
        "🛡️ <b>Keamanan</b>\n"
        "Simpan cookies di perangkat sendiri, jangan kirim ke chat, dan ekspor ulang jika sesi kedaluwarsa. Jika muncul 401/rate-limit, hentikan percobaan berulang dan cek kembali nanti."
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def instagram_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run non-downloading extractor simulations for an Instagram URL."""
    if not is_authorized(update):
        return
    if not context.args:
        await update.effective_message.reply_text("Format: /igcheck https://www.instagram.com/p/POST_ID/")
        return
    url = html.unescape(context.args[0].strip().strip("<>"))
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (host == "instagram.com" or host.endswith(".instagram.com") or host in ("instagr.am", "www.instagr.am")):
        await update.effective_message.reply_text("❌ /igcheck hanya menerima URL Instagram yang valid.")
        return
    if host in ("instagr.am", "www.instagr.am"):
        parsed = parsed._replace(netloc="www.instagram.com", query="", fragment="")
        url = urllib.parse.urlunparse(parsed)
    status = await update.effective_message.reply_text("🧪 Menjalankan simulasi extractor (tidak mengunduh file)...")
    lines = [f"Python: {sys.version.split()[0]}"]
    for module, label in (("yt_dlp", "yt-dlp"), ("gallery_dl", "gallery-dl")):
        try:
            result = await asyncio.create_subprocess_exec(
                sys.executable, "-m", module, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(result.communicate(), timeout=15)
            version = out.decode("utf-8", "replace").strip() or err.decode("utf-8", "replace").strip()
            lines.append(f"{label}: {'OK ' + version if result.returncode == 0 else 'ERROR ' + version[:160]}")
        except Exception as exc:
            lines.append(f"{label}: ERROR {type(exc).__name__}: {exc}")
    cookie_path = INSTAGRAM_COOKIES_FILE or SOCIAL_COOKIES_FILE
    if not cookie_path:
        lines.append("Cookies: tidak dikonfigurasi (set INSTAGRAM_COOKIES_FILE di .env)")
    elif not os.path.isfile(cookie_path):
        lines.append("Cookies: path disetel tetapi file tidak ditemukan; periksa .env/path dan restart bot")
    elif not os.access(cookie_path, os.R_OK):
        lines.append("Cookies: file ditemukan tetapi tidak bisa dibaca; periksa izin file")
    else:
        lines.append("Cookies: file ditemukan dan dapat dibaca (status login belum terverifikasi)")
    for module, label in (("gallery_dl", "gallery-dl"), ("yt_dlp", "yt-dlp")):
        args = [sys.executable, "-m", module, "--simulate", "--no-warnings"] if module == "yt_dlp" else [sys.executable, "-m", module, "--simulate"]
        if cookie_path and os.path.isfile(cookie_path):
            args.extend(["--cookies", cookie_path])
        args.append(url)
        try:
            proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=min(90, DOWNLOAD_TIMEOUT_SECONDS))
            details = (err.decode("utf-8", "replace") + "\n" + out.decode("utf-8", "replace")).strip()
            lines.append(f"\n{label} simulation exit={proc.returncode}:\n{details[-900:] or '(tidak ada output)'}")
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            lines.append(f"\n{label}: timeout")
        except Exception as exc:
            lines.append(f"\n{label}: {type(exc).__name__}: {exc}")
    report = "\n".join(lines)
    # Telegram message length safety; redact obvious cookie/token-like strings.
    report = re.sub(r"(?i)(sessionid|csrftoken|ds_user_id|authorization|token)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", report)
    await status.edit_text("<b>🧪 INSTAGRAM DIAGNOSTIC</b>\n<pre>" + html.escape(report[-3600:]) + "</pre>", parse_mode="HTML")


async def cookie_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safe local Instagram cookie diagnostics; never prints cookie values or path."""
    if not is_authorized(update):
        return
    configured = INSTAGRAM_COOKIES_FILE or SOCIAL_COOKIES_FILE
    lines = ["<b>🍪 NEON • INSTAGRAM SESSION DIAGNOSTICS</b>", "━━━━━━━━━━━━━━━━━━━━"]
    if not configured:
        lines += ["File: 🔴 belum dikonfigurasi", "Atur <code>INSTAGRAM_COOKIES_FILE=/storage/emulated/0/Download/botftp/cookies.txt</code> di .env lalu restart bot."]
    elif not os.path.isfile(configured):
        lines += ["File: 🔴 tidak ditemukan", "Path .env tidak cocok dengan lokasi file atau bot dijalankan dari lingkungan berbeda. Path sengaja tidak ditampilkan."]
    elif not os.access(configured, os.R_OK):
        lines += ["File: 🔴 tidak bisa dibaca", "Periksa izin akses file dari Termux."]
    else:
        try:
            with open(configured, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            rows = [ln for ln in content.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            is_netscape = any(ln.strip().startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")) for ln in content.splitlines()[:10])
            has_sessionid = any(len(ln.split("\t")) >= 7 and ln.split("\t")[5].strip().lower() == "sessionid" for ln in rows)
            has_instagram_domain = any(len(ln.split("\t")) >= 7 and "instagram.com" in ln.split("\t")[0].lower() for ln in rows)
            if not content.strip():
                lines += ["File: 🔴 kosong", "Ekspor ulang cookies dalam format Netscape."]
            else:
                lines += [f"File terbaca: 🟢 ya", f"Format Netscape: {'🟢 terdeteksi' if is_netscape else '🟡 belum terverifikasi'}", f"Cookie sessionid: {'🟢 ditemukan' if has_sessionid else '🔴 tidak ditemukan'}", f"Domain Instagram: {'🟢 ditemukan' if has_instagram_domain else '🟡 tidak terdeteksi'}"]
                if is_netscape and has_sessionid and has_instagram_domain:
                    lines.append("Kesimpulan lokal: 🟢 struktur cookies tampak sesuai.")
                else:
                    lines.append("Kesimpulan lokal: 🟡 cek ulang hasil ekspor cookies.")
                lines.append("⚠️ Ini tidak membuktikan sesi masih aktif atau diizinkan Instagram.")
        except Exception as exc:
            lines += ["File: 🔴 gagal diperiksa", f"Error: {html.escape(type(exc).__name__)}"]
    lines += ["━━━━━━━━━━━━━━━━━━━━", "Tes extractor dengan <code>/igcheck https://www.instagram.com/reel/ID/</code>", "Bantuan: <code>/ighelp</code>"]
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick safe health report for downloader packages and local cookie configuration."""
    if not is_authorized(update):
        return
    import importlib.util
    from importlib import metadata
    def pkg(module, package):
        try:
            if importlib.util.find_spec(module) is None:
                return "🔴 belum terpasang"
            try:
                return "🟢 " + metadata.version(package)
            except metadata.PackageNotFoundError:
                return "🟢 tersedia (versi tak diketahui)"
        except Exception:
            return "🟡 tidak dapat diperiksa"
    cookie = INSTAGRAM_COOKIES_FILE or SOCIAL_COOKIES_FILE
    if not cookie:
        cookie_state = "🔴 belum dikonfigurasi"
    elif not os.path.isfile(cookie):
        cookie_state = "🔴 file tidak ditemukan"
    elif not os.access(cookie, os.R_OK):
        cookie_state = "🔴 tidak bisa dibaca"
    else:
        cookie_state = "🟢 file terbaca; validitas sesi belum diuji"
    message = (
        "<b>🧠 NEON OS • QUICK HEALTH</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🧩 Build: <code>{html.escape(BOT_VERSION)}</code>\n"
        f"🐍 Python: <code>{html.escape(sys.version.split()[0])}</code>\n"
        f"📦 yt-dlp: {pkg('yt_dlp', 'yt-dlp')}\n"
        f"📦 gallery-dl: {pkg('gallery_dl', 'gallery-dl')}\n"
        f"🍪 Instagram cookies: {cookie_state}\n"
        f"🤖 Token terkonfigurasi: <code>{len(BOT_TOKENS)}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Untuk menguji URL: <code>/igcheck URL_INSTAGRAM</code>.\n"
        "Status file cookies tidak sama dengan status login Instagram."
    )
    await update.effective_message.reply_text(message, parse_mode="HTML", disable_web_page_preview=True)


async def media_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show metadata for a supported URL without downloading the media."""
    if not is_authorized(update):
        return
    if not context.args:
        await update.effective_message.reply_text("Format: /info URL_MEDIA")
        return
    url = html.unescape(context.args[0].strip().strip("<>"))
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        await update.effective_message.reply_text("❌ URL tidak valid.")
        return
    msg = await update.effective_message.reply_text("🔎 Membaca metadata media...")
    args = [sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download", "--no-warnings", "--socket-timeout", "30"]
    host = (parsed.hostname or "").lower()
    cookie = ""
    if host == "instagram.com" or host.endswith(".instagram.com") or host in ("instagr.am", "www.instagr.am"):
        cookie = INSTAGRAM_COOKIES_FILE or SOCIAL_COOKIES_FILE
    elif host == "tiktok.com" or host.endswith(".tiktok.com"):
        cookie = TIKTOK_COOKIES_FILE or SOCIAL_COOKIES_FILE
    elif host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be":
        cookie = YOUTUBE_COOKIES_FILE or SOCIAL_COOKIES_FILE
    elif host == "facebook.com" or host.endswith(".facebook.com") or host == "fb.watch":
        cookie = FACEBOOK_COOKIES_FILE or SOCIAL_COOKIES_FILE
    elif host in ("x.com", "twitter.com") or host.endswith(".x.com") or host.endswith(".twitter.com"):
        cookie = X_COOKIES_FILE or SOCIAL_COOKIES_FILE
    if cookie and os.path.isfile(cookie):
        args.extend(["--cookies", cookie])
    args.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=min(120, DOWNLOAD_TIMEOUT_SECONDS))
        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").strip() or out.decode("utf-8", "replace").strip() or "Metadata tidak tersedia."
            await msg.edit_text("❌ Gagal membaca metadata:\n" + html.escape(detail[-1800:]))
            return
        data = json.loads(out.decode("utf-8", "replace"))
        duration = data.get("duration")
        if isinstance(duration, (int, float)):
            duration_text = f"{int(duration)//60:02d}:{int(duration)%60:02d}"
        else:
            duration_text = "tidak tersedia"
        lines = [
            "<b>📋 MEDIA INFO</b>",
            f"Judul: <code>{html.escape(str(data.get('title') or 'Tidak tersedia')[:220])}</code>",
            f"Situs: <code>{html.escape(str(data.get('extractor_key') or data.get('extractor') or 'unknown'))}</code>",
            f"Uploader: <code>{html.escape(str(data.get('uploader') or data.get('channel') or 'Tidak tersedia')[:120])}</code>",
            f"Durasi: <code>{duration_text}</code>",
            f"Format tersedia: <code>{len(data.get('formats') or [])}</code>",
        ]
        await msg.edit_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except asyncio.TimeoutError:
        await msg.edit_text("⏱️ Metadata timeout. Coba lagi saat jaringan stabil.")
    except Exception as exc:
        logger.exception("Media info gagal")
        await msg.edit_text("❌ Metadata gagal: " + html.escape(str(exc)[:1000]))


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Explain broad extractor support without promising every post is downloadable."""
    if not is_authorized(update):
        return
    text = (
        "🌐 <b>NEON SOCIAL MEDIA ENGINE</b>\n\n"
        "📥 <code>/dl URL</code> — video/media dari situs yang didukung yt-dlp\n"
        "🖼️ <code>/photos URL</code> — foto/slideshow (terutama TikTok)\n"
        "🎵 <code>/mp3 URL</code> atau <code>/audio URL</code> — ekstrak audio jika sumber mendukung\n"
        "🔎 <code>/info URL</code> — baca metadata tanpa mengunduh\n"
        "🧪 <code>/igcheck URL</code> — diagnosis extractor Instagram tanpa mengunduh\n"
        "🍪 <code>/cookiestatus</code> — cek file cookies tanpa menampilkan rahasia\n\n"
        "🧭 <b>Platform yang bisa dicoba:</b> YouTube, TikTok, Instagram, Facebook, X/Twitter, Reddit, Twitch, dan banyak situs lain yang didukung yt-dlp.\n\n"
        "⚠️ Dukungan tergantung jenis postingan, login, wilayah, usia, DRM, dan kebijakan platform. Akun privat/terkunci atau postingan yang diblokir mungkin gagal. Gunakan hanya media yang boleh lu akses dan simpan.\n\n"
        "☁️ File hasil yang berhasil diunduh akan dicoba diarsipkan ke FTP. Telegram tetap punya batas ukuran kirim tersendiri; file besar bisa tersimpan di FTP walau tidak dapat dikirim sebagai media Telegram.\n\n"
        "🛠️ Untuk kualitas default terbaik, kosongkan DOWNLOAD_MAX_HEIGHT. Untuk menghemat kuota, set DOWNLOAD_MAX_HEIGHT=720 atau 480 di .env."
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def speedtest_command_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    status = await msg.reply_text("🚀 Menguji latensi dan kecepatan download (maks. 5 MB)...")
    latency_ms = None
    try:
        req = urllib.request.Request("https://www.cloudflare.com/cdn-cgi/trace", headers={"User-Agent": "NEON-OS-SpeedCheck/1.0"})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read(256)
        latency_ms = (time.monotonic() - t0) * 1000

        test_url = "https://speed.cloudflare.com/__down?bytes=5000000"
        req = urllib.request.Request(test_url, headers={"User-Agent": "NEON-OS-SpeedCheck/1.0"})
        started = time.monotonic()
        transferred = 0
        with urllib.request.urlopen(req, timeout=20) as resp:
            while transferred < 5_000_000:
                chunk = resp.read(min(65536, 5_000_000 - transferred))
                if not chunk:
                    break
                transferred += len(chunk)
        elapsed = max(time.monotonic() - started, 0.001)
        mbps = (transferred * 8 / 1_000_000) / elapsed
        result = (
            "🚀 <b>NETWORK CHECK</b>\n"
            f"📡 Latensi HTTPS: <code>{latency_ms:.0f} ms</code>\n"
            f"⬇️ Perkiraan download: <code>{mbps:.2f} Mbps</code>\n"
            f"📦 Data tes: <code>{transferred / 1_000_000:.2f} MB</code>\n"
            "ℹ️ Ini tes ringan dari server bot; hasil bukan pengukuran ISP HP yang presisi. Upload speed tidak diuji."
        )
        await status.edit_text(result, parse_mode="HTML")
    except Exception as exc:
        logger.warning("Speed check gagal (%s).", type(exc).__name__)
        text = "❌ Tes jaringan gagal. Periksa koneksi internet server bot dan coba lagi."
        try:
            await status.edit_text(text)
        except Exception:
            await msg.reply_text(text)

async def cloud_tree(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    try:
        async with ftp_lock:
            ftp = FTPManager.get_connection()
            tree = "<b>🌴 CLOUD TREE:</b>\n"
            for fld in ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya", "downloads"]:
                tree += f"📁 {fld}\n"
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    for file in ftp.nlst()[:3]:
                        if file not in ['.', '..']:
                            tree += f"   └── <code>{file}</code>\n"
                except Exception:
                    pass
            ftp.quit()
        await update.message.reply_text(tree, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def backup_cloud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return
    st = await msg.reply_text("🛡️ Menyiapkan backup ZIP dari FTP...")
    bzip = f"Backup_FTP_{int(time.time())}.zip"
    folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya", "downloads"]
    archived = 0
    skipped = []
    ftp = None
    try:
        with zipfile.ZipFile(bzip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            async with ftp_lock:
                ftp = FTPManager.get_connection()
                for folder in folders:
                    try:
                        # FTPManager normally starts in htdocs; handle both jailed and root layouts.
                        try:
                            ftp.cwd('/')
                            ftp.cwd('htdocs')
                        except Exception:
                            pass
                        ftp.cwd(folder)
                        names = [n for n in ftp.nlst() if n not in ('.', '..') and '/' not in n and '\\' not in n]
                    except Exception as exc:
                        skipped.append(f"{folder}: {exc}")
                        continue
                    for name in names:
                        try:
                            # FTP SIZE is disabled on some hosts. RETR is the authoritative
                            # check; directories/non-readable entries fail here and are reported.
                            data = io.BytesIO()
                            ftp.retrbinary(f"RETR {name}", data.write)
                            if data.tell() == 0:
                                skipped.append(f"{folder}/{name}: file kosong atau tidak dapat dibaca")
                                continue
                            zipf.writestr(f"{folder}/{name}", data.getvalue())
                            archived += 1
                        except Exception as exc:
                            skipped.append(f"{folder}/{name}: {exc}")
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                ftp.close()
            ftp = None
        if archived == 0:
            raise RuntimeError("Tidak ada file yang berhasil dimasukkan ke ZIP. Periksa folder FTP dan izin baca.")
        with open(bzip, 'rb') as doc:
            await context.bot.send_document(
                chat_id=chat.id,
                document=doc,
                filename=bzip,
                caption=f"✅ Backup selesai: {archived} file masuk ZIP." + (f"\n⚠️ {len(skipped)} item dilewati; cek log bot." if skipped else ""),
            )
        try:
            await st.delete()
        except Exception:
            pass
        logger.info("FTP backup selesai: %s files, %s skipped", archived, len(skipped))
        if skipped:
            logger.warning("FTP backup item dilewati: %s", " | ".join(skipped[:20]))
    except Exception as exc:
        logger.exception("FTP backup gagal")
        try:
            await st.edit_text("❌ Backup ZIP gagal: " + html.escape(str(exc)[:1200]))
        except Exception:
            await msg.reply_text("❌ Backup ZIP gagal. Cek log terminal untuk detailnya.")
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass
        try:
            if os.path.exists(bzip):
                os.remove(bzip)
        except Exception:
            pass

async def storage_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    ftp = None
    try:
        total = 0
        async with ftp_lock:
            ftp = FTPManager.get_connection()
            for folder in ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya", "downloads"]:
                try:
                    try:
                        ftp.cwd('/')
                        ftp.cwd('htdocs')
                    except Exception:
                        pass
                    ftp.cwd(folder)
                    used_mlsd = False
                    try:
                        for name, facts in ftp.mlsd():
                            if facts.get("type") == "file":
                                total += int(facts.get("size", 0) or 0)
                        used_mlsd = True
                    except Exception:
                        used_mlsd = False
                    if not used_mlsd:
                        for name in ftp.nlst():
                            if name in ('.', '..') or '/' in name or '\\' in name:
                                continue
                            try:
                                size = ftp.size(name)
                                if size:
                                    total += size
                            except Exception:
                                continue
                except Exception as exc:
                    logger.warning("Quota: folder %s tidak bisa dibaca: %s", folder, exc)
            try:
                ftp.quit()
            except Exception:
                ftp.close()
            ftp = None
        await msg.reply_text(f"💾 Storage terpakai: <code>{format_size(total)}</code>", parse_mode='HTML')
    except Exception as exc:
        await msg.reply_text("❌ Gagal membaca kuota FTP: " + html.escape(str(exc)), parse_mode='HTML')
    finally:
        if ftp is not None:
            try: ftp.close()
            except Exception: pass

async def list_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    ftp = None
    try:
        async with ftp_lock:
            ftp = FTPManager.get_connection()
            try:
                ftp.cwd('/')
                ftp.cwd('htdocs')
            except Exception:
                pass
            items = [item for item in ftp.nlst() if item not in ('.', '..')]
            try:
                ftp.quit()
            except Exception:
                ftp.close()
            ftp = None
        safe_items = [html.escape(item) for item in items]
        await msg.reply_text("📂 Isi root cloud:\n" + ("\n".join(f"📁 <code>{item}</code>" for item in safe_items) if safe_items else "(kosong)"), parse_mode='HTML')
    except Exception as exc:
        await msg.reply_text("❌ Gagal membaca direktori FTP: " + html.escape(str(exc)), parse_mode='HTML')
    finally:
        if ftp is not None:
            try: ftp.close()
            except Exception: pass

async def search_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.effective_message.reply_text("🔎 Format: <code>/search nama_file</code>", parse_mode="HTML")
        return
    q = " ".join(context.args).lower()
    st = await update.message.reply_text("🔍 <i>Searching...</i>", parse_mode='HTML')
    try:
        res = []
        async with ftp_lock:
            ftp = FTPManager.get_connection()
            for fld in ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya", "downloads"]:
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    for f in ftp.nlst():
                        if q in f.lower() and f not in ['.', '..']:
                            res.append(f"📁 htdocs/{fld}/ -> <b>{f}</b>")
                except Exception:
                    pass
            ftp.quit()
        await delete_msg_safe(st)
        await update.message.reply_text("\n".join(res) if res else "❌ Tidak ditemukan.", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(st)
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')

async def sync_url_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.effective_message.reply_text("🔄 Format: <code>/sync https://example.com/file.jpg</code>", parse_mode="HTML")
        return
    url = context.args[0]
    fname = os.path.basename(url.split("?")[0]) or f"file_{int(time.time())}.mp4"
    lpath = f"temp_sync_{fname}"
    st = await update.message.reply_text("🚀 <i>Syncing...</i>", parse_mode='HTML')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=300) as resp, open(lpath, 'wb') as f:
            f.write(resp.read())
        cat = "Video" if fname.endswith(('.mp4','.mkv')) else "Gambar"
        async with ftp_lock:
            ftp = FTPManager.get_connection()
            ensure_ftp_dir(ftp, cat)
            with open(lpath, 'rb') as fp:
                ftp.storbinary(f"STOR {fname}", fp, blocksize=32768)
            ftp.quit()
        await delete_msg_safe(st)
        await update.message.reply_text(f"⚡ Sync OK: <code>htdocs/{cat}/{fname}</code>", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(st)
        await update.message.reply_text(f"❌ Error: {e}", parse_mode='HTML')
    finally:
        clean_local_temp_files()

def detect_media_signature(path):
    """Return (category, extension, MIME) using file signatures, not filenames alone."""
    try:
        with open(path, "rb") as f:
            head = f.read(96)
    except OSError:
        return None
    if head.startswith(b"\xff\xd8\xff"):
        return ("Gambar", ".jpg", "image/jpeg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("Gambar", ".png", "image/png")
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ("Gambar", ".gif", "image/gif")
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ("Gambar", ".webp", "image/webp")
    if head.startswith(b"%PDF-"):
        return ("Dokumen", ".pdf", "application/pdf")
    if head.startswith(b"PK\x03\x04"):
        return ("Arsip_Zip", ".zip", "application/zip")
    if head.startswith(b"OggS"):
        return ("Audio", ".ogg", "audio/ogg")
    if head.startswith(b"fLaC"):
        return ("Audio", ".flac", "audio/flac")
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xff and (head[1] & 0xe0) == 0xe0):
        return ("Audio", ".mp3", "audio/mpeg")
    if head.startswith(b"\x1aE\xdf\xa3"):
        return ("Video", ".mkv", "video/x-matroska")
    # ISO-BMFF family: inspect brands so HEIC/HEIF/AVIF images aren't mislabeled .mp4.
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brands = {head[8:12].lower()}
        brands.update(head[i:i+4].lower() for i in range(16, min(len(head)-3, 64), 4))
        if any(b.startswith((b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")) for b in brands):
            return ("Gambar", ".heic", "image/heic")
        if any(b.startswith((b"avif", b"avis")) for b in brands):
            return ("Gambar", ".avif", "image/avif")
        if any(b.startswith((b"qt  ",)) for b in brands):
            return ("Video", ".mov", "video/quicktime")
        return ("Video", ".mp4", "video/mp4")
    return None


async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload Telegram media to the matching FTP category with a real extension."""
    user = update.effective_user
    msg = update.effective_message
    if msg is None or user is None:
        return
    if not is_authorized(update):
        return
    try:
        media = None
        category = "Lainnya"
        default_ext = ".bin"
        mime = ""
        original_name = None

        if msg.photo:
            media, category, default_ext, mime = msg.photo[-1], "Gambar", ".jpg", "image/jpeg"
        elif msg.video:
            media, category, default_ext, mime = msg.video, "Video", ".mp4", "video/mp4"
        elif msg.animation:
            media, category, default_ext, mime = msg.animation, "Video", ".mp4", "video/mp4"
        elif msg.audio:
            media, category, default_ext, mime = msg.audio, "Audio", ".mp3", (msg.audio.mime_type or "audio/mpeg")
        elif msg.voice:
            media, category, default_ext, mime = msg.voice, "Audio", ".ogg", (msg.voice.mime_type or "audio/ogg")
        elif msg.sticker:
            media = msg.sticker
            category = "Gambar"
            default_ext = ".webp" if not getattr(msg.sticker, "is_animated", False) else ".tgs"
            mime = "image/webp" if default_ext == ".webp" else "application/x-tgsticker"
        elif msg.document:
            media = msg.document
            original_name = msg.document.file_name
            mime = (msg.document.mime_type or "").lower()
            guessed_mime, guessed_ext = mimetypes.guess_type(original_name or "")
            mime = mime or guessed_mime or "application/octet-stream"
            ext = os.path.splitext(original_name or "")[1].lower()
            if mime.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic"):
                category, default_ext = "Gambar", (ext or guessed_ext or ".jpg")
            elif mime.startswith("video/") or ext in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"):
                category, default_ext = "Video", (ext or guessed_ext or ".mp4")
            elif mime.startswith("audio/") or ext in (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus"):
                category, default_ext = "Audio", (ext or guessed_ext or ".mp3")
            elif ext == ".zip" or mime in ("application/zip", "application/x-zip-compressed"):
                category, default_ext = "Arsip_Zip", ".zip"
            else:
                category, default_ext = "Dokumen", (ext or guessed_ext or ".bin")
        else:
            return

        original_name = original_name or getattr(media, "file_name", None)
        if original_name:
            # Keep the basename only; never allow a supplied path to affect FTP paths.
            fname = os.path.basename(original_name.replace("\\", "/"))
            if not os.path.splitext(fname)[1]:
                fname += default_ext
        else:
            fname = f"{category.lower()}_{int(time.time())}{default_ext}"
        # Telegram photo objects do not carry filenames. They are JPEG images, not MP4.
        if msg.photo:
            fname = f"gambar_{int(time.time())}.jpg"
        if not fname or fname in (".", ".."):
            fname = f"media_{int(time.time())}{default_ext}"

        st = await msg.reply_text(f"⏳ Mengunggah media ke folder {category}...")
        tg_file = await context.bot.get_file(media.file_id)
        lpath = f"temp_upload_{int(time.time() * 1000)}{default_ext}"
        await tg_file.download_to_drive(custom_path=lpath)
        # Telegram documents may be mislabelled (e.g. JPEG named .mp4). Trust the
        # file signature over the supplied extension/MIME where a signature is known.
        detected = detect_media_signature(lpath)
        if detected:
            detected_category, detected_ext, detected_mime = detected
            # Do not reclassify Telegram animated stickers (TGS) as ZIP archives.
            if not (msg.sticker and default_ext == ".tgs"):
                category, default_ext, mime = detected_category, detected_ext, detected_mime
                stem = os.path.splitext(os.path.basename(fname))[0] or category.lower()
                fname = f"{stem[:90]}{default_ext}"
                new_lpath = os.path.splitext(lpath)[0] + default_ext
                if new_lpath != lpath:
                    os.replace(lpath, new_lpath)
                    lpath = new_lpath
        try:
            async with ftp_lock:
                ftp = FTPManager.get_connection()
                try:
                    ensure_ftp_dir(ftp, category)
                    with open(lpath, 'rb') as fp:
                        ftp.storbinary(f"STOR {fname}", fp, blocksize=32768)
                finally:
                    try: ftp.quit()
                    except Exception: ftp.close()
            try:
                await st.delete()
            except Exception:
                pass
            await msg.reply_text(f"✅ Upload berhasil\n📁 <code>htdocs/{html.escape(category)}/{html.escape(fname)}</code>", parse_mode='HTML')
        finally:
            try:
                if os.path.exists(lpath): os.remove(lpath)
            except Exception:
                pass
    except Exception as exc:
        logger.exception("Media upload gagal")
        await msg.reply_text("❌ Upload gagal: " + html.escape(str(exc)[:1200]), parse_mode='HTML')

async def handle_text_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if user is None or msg is None or not msg.text:
        return
    if not is_authorized(update):
        return
    txt = msg.text.strip()
    save_chat_history(user.id, user.username, user.first_name, txt)
    bname = context.bot.username or ""
    # In groups, answer only when mentioned or replied to; private chats behave like an AI chat.
    if msg.chat.type != "private" and not (f"@{bname}" in txt or msg.reply_to_message):
        return
    prompt = txt.replace(f"@{bname}", "").strip()
    if not prompt:
        await msg.reply_text("Tulis pertanyaan lu setelah menyebut bot, bro.")
        return
    if not ai_client:
        await msg.reply_text("AI belum dikonfigurasi. Isi GEMINI_API_KEY di file .env lalu restart bot.")
        return
    status = await msg.reply_text("🧠 Sedang berpikir...")
    await ai_reply(update, context, prompt, status)

async def remember_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    user = update.effective_user
    memory = " ".join(context.args).strip()
    if not msg or not user:
        return
    if not memory:
        await msg.reply_text("🧠 Pakai: /remember preferensi atau konteks yang ingin disimpan\nJangan simpan password, token, atau data rahasia.")
        return
    try:
        memory_id = await asyncio.to_thread(save_user_memory, user.id, memory)
        await msg.reply_text(f"🧠 Memori tersimpan untuk akun Telegram lo saja. ID: {memory_id}\nLihat: /memories")
    except Exception as exc:
        logger.exception("Gagal menyimpan memori AI")
        await msg.reply_text("❌ Gagal menyimpan memori: " + str(exc)[:200])

async def memories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    rows = await asyncio.to_thread(load_user_memories, user.id, 20)
    if not rows:
        await msg.reply_text("🧠 Belum ada memori tersimpan. Tambah dengan /remember teks")
        return
    lines = ["🧠 MEMORI NEON AI (maks. 20 terbaru)"]
    for mid, memory, created in rows:
        lines.append(f"\n#{mid} · {created[:10]}\n{memory}")
    lines.append("\nHapus satu: /forgetmemory ID · Hapus semua: /forgetmemory all")
    await send_ai_text(msg, "\n".join(lines))

async def forgetmemory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    if not context.args:
        await msg.reply_text("Pakai: /forgetmemory ID atau /forgetmemory all")
        return
    arg = context.args[0].lower()
    try:
        if arg == "all":
            count = await asyncio.to_thread(delete_user_memory, user.id, None)
        else:
            count = await asyncio.to_thread(delete_user_memory, user.id, int(arg))
        await msg.reply_text(f"🧹 Memori dihapus: {count}.")
    except ValueError:
        await msg.reply_text("ID harus angka atau kata all.")

async def guardian_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safe 24/7 guardian snapshot; process supervision is handled by runit/hosting."""
    if not is_authorized(update):
        return
    msg = update.effective_message
    if not msg:
        return
    try:
        proc = psutil.Process(os.getpid())
        cpu = psutil.cpu_percent(interval=0.2)
        ram = proc.memory_info().rss
        disk = shutil.disk_usage(os.getcwd())
        log_path = os.path.join(os.getcwd(), "neon_bot.log")
        log_state = "ada" if os.path.isfile(log_path) else "belum ada"
        services = "Termux/runit belum terdeteksi"
        sv = shutil.which("sv")
        if sv:
            try:
                result = subprocess.run([sv, "status", "neonbot"], capture_output=True, text=True, timeout=3)
                services = (result.stdout or result.stderr or "status tidak tersedia").strip()[:250]
            except Exception:
                services = "runit terdeteksi; status gagal dibaca"
        await msg.reply_text(
            "🛡️ <b>NEON GUARDIAN</b>\n━━━━━━━━━━━━━━━━\n"
            f"🟢 Python process: <code>{proc.pid}</code>\n"
            f"⏱️ Uptime bot: <code>{html.escape(get_uptime())}</code>\n"
            f"🧮 CPU host: <code>{cpu:.1f}%</code> · RAM proses: <code>{format_size(ram)}</code>\n"
            f"💽 Disk bebas: <code>{format_size(disk.free)}</code>\n"
            f"🧾 Log: <code>{log_state}</code>\n"
            f"🔁 Supervisor: <code>{html.escape(services)}</code>\n"
            f"🗄️ Vault lokal: <code>{html.escape(DOWNLOADS_DIR)}</code>\n"
            f"📦 File tersimpan: <code>{sum(len(files) for _, _, files in os.walk(DOWNLOADS_DIR))}</code>\n\n"
            "Catatan: ini snapshot kesehatan, bukan jaminan HP hidup saat mati total. Untuk auto-restart, gunakan Termux:Boot + runit atau supervisor hosting.",
            parse_mode="HTML")
    except Exception as exc:
        logger.exception("Guardian health check gagal")
        await msg.reply_text("⚠️ Guardian gagal membaca status: " + html.escape(str(exc)[:200]), parse_mode="HTML")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    bot = await context.bot.get_me()
    await update.message.reply_text(f"⚙️ <b>SYSTEM INFO</b>\n🤖 @{bot.username}\n📦 {BOT_VERSION}\n⏱️ Uptime: <code>{get_uptime()}</code>", parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = update.effective_message
    if msg is None:
        return
    txt = (
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"⚡ <b>COMMAND DIRECTORY ({BOT_VERSION})</b>\n"
        f"• <code>/panel</code> (menu), <code>/status</code> (system), <code>/ftpstatus</code> (cek semua FTP), <code>/myid</code> (ID Telegram)\n"
        f"┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫\n"
        f"• <code>/ss</code>, <code>/fullss</code>, <code>/mobilesec</code>, <code>/tabss</code>\n"
        f"• <code>/darkss</code>, <code>/pdfss</code>, <code>/webinfo</code>, <code>/dns</code>\n"
        f"• <code>/dl</code> (multi-platform), <code>/photos</code>, <code>/mp3</code>, <code>/info</code>, <code>/igcheck</code>, <code>/igstatus</code>, <code>/dlcheck</code>, <code>/health</code>, <code>/platforms</code>\n"
        f"• <code>/imagine</code>, <code>/ocr</code>, <code>/fix</code>, <code>/quiz</code>, <code>/resetai</code>\n"
        f"• <code>/remember</code>, <code>/memories</code>, <code>/forgetmemory</code>, <code>/guardian</code>\n"
        f"• <code>/kanban</code>, <code>/todo</code>, <code>/weather</code>, <code>/poll</code>\n"
        f"• <code>/short</code>, <code>/qr</code>, <code>/trans</code>, <code>/genpass</code>\n"
        f"• <code>/backup</code>, <code>/list</code>, <code>/quota</code>, <code>/search</code>, <code>/sync</code>\n"
        f"• Owner: <code>/adminpanel</code>, <code>/bots</code>, <code>/downloadstats</code>\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )
    await msg.reply_text(txt, parse_mode='HTML')

async def bots_control_tower_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only view of configured bot workers; secrets are never displayed."""
    if not is_owner(update):
        return
    msg = update.effective_message
    lines = [
        "🛰️ <b>NEON • MULTI-BOT CONTROL TOWER</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🤖 Token unik terkonfigurasi: <b>{len(set(BOT_TOKENS))}</b>",
        f"🧵 Worker terpantau: <b>{len(BOT_RUNTIME)}</b>",
    ]
    if not BOT_RUNTIME:
        lines.append("🟡 Worker belum melaporkan status (cek startup log).")
    for idx in sorted(BOT_RUNTIME):
        item = BOT_RUNTIME[idx]
        status = item.get("status", "unknown")
        emoji = "🟢" if status == "online" else ("🔄" if status in ("starting", "restarting") else "🔴")
        username = html.escape(item.get("username") or "belum terdeteksi")
        since = item.get("updated")
        since_text = since.strftime("%H:%M:%S WIB") if since else "—"
        lines.append(f"{emoji} Bot {idx}: <code>{username}</code> · <b>{html.escape(status)}</b> · {since_text}")
    lines.extend(["━━━━━━━━━━━━━━━━━━━━", "ℹ️ Panel ini memantau worker di proses Python yang sama; tidak menampilkan token atau kredensial."])
    await msg.reply_text("\n".join(lines), parse_mode="HTML")


async def admin_intelligence_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only compact operations dashboard for runtime, disk, downloads and dependencies."""
    if not is_owner(update):
        return
    msg = update.effective_message
    try:
        import importlib.util
        from importlib import metadata
        disk = shutil.disk_usage(os.getcwd())
        active = sum(1 for job in DOWNLOAD_JOBS if job.get("status") == "running")
        recent = DOWNLOAD_JOBS[-8:]
        def pkg(module, dist):
            try:
                if importlib.util.find_spec(module) is None:
                    return "🔴 belum ada"
                try:
                    return "🟢 " + html.escape(metadata.version(dist))
                except metadata.PackageNotFoundError:
                    return "🟢 tersedia"
            except Exception:
                return "🟡 tidak diketahui"
        lines = [
            "🧠 <b>NEON • ADMIN INTELLIGENCE</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🏷️ Build: <code>{html.escape(BOT_VERSION)}</code>",
            f"⏱️ Uptime: <code>{html.escape(get_uptime())}</code>",
            f"🤖 Worker online: <b>{sum(1 for x in BOT_RUNTIME.values() if x.get('status') == 'online')}</b> / {len(set(BOT_TOKENS))}",
            f"📥 Download aktif: <b>{active}</b> · riwayat lokal tersimpan: <b>{len(DOWNLOAD_JOBS)}</b>",
            f"💽 Disk tersedia: <code>{format_size(disk.free)}</code> / {format_size(disk.total)}",
            f"📦 yt-dlp: {pkg('yt_dlp', 'yt-dlp')}",
            f"📦 gallery-dl: {pkg('gallery_dl', 'gallery-dl')}",
            f"🎞️ FFmpeg: {'🟢 tersedia' if shutil.which('ffmpeg') else '🟡 tidak ditemukan'}",
            "━━━━━━━━━━━━━━━━━━━━",
            "<b>📋 Permintaan download terbaru</b>",
        ]
        if not recent:
            lines.append("Belum ada permintaan yang tercatat sejak proses ini hidup.")
        for job in reversed(recent):
            started = job.get("started")
            stamp = started.strftime("%H:%M:%S") if started else "--:--:--"
            status = job.get("status", "unknown")
            icon = "⏳" if status == "running" else ("✅" if status == "handler_returned" else "⚠️")
            lines.append(f"{icon} <code>{stamp}</code> · {html.escape(job.get('platform', 'web'))} · user <code>{job.get('user_id', '?')}</code> · {html.escape(status)}")
        lines.append("\nCatatan: status handler selesai bukan bukti file berhasil dikirim/diarsipkan; hasil akhir tetap lihat balasan download di chat.")
        await msg.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        logger.exception("Admin intelligence dashboard gagal")
        await msg.reply_text("⚠️ Dashboard gagal dibangun: " + html.escape(str(exc)[:200]), parse_mode="HTML")


async def tracked_downloader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telemetry wrapper around existing downloader; preserves the original engine."""
    message = update.effective_message
    user = update.effective_user
    raw = context.args[0] if context.args else ""
    host = "link-belum-diberikan"
    if raw:
        try:
            host = (urllib.parse.urlparse(html.unescape(raw.strip().strip('<>'))).hostname or "url-invalid").lower()
        except Exception:
            host = "url-invalid"
    job = {
        "started": get_wib_now(),
        "user_id": user.id if user else "?",
        "platform": host[:80],
        "status": "running",
    }
    DOWNLOAD_JOBS.append(job)
    if len(DOWNLOAD_JOBS) > 100:
        del DOWNLOAD_JOBS[:-100]
    try:
        await universal_downloader(update, context)
        job["status"] = "handler_returned"
    except Exception as exc:
        job["status"] = "error"
        job["error_type"] = type(exc).__name__
        logger.exception("Tracked downloader error for host %s", host)
        if message:
            try:
                await message.reply_text("⚠️ Download mengalami error internal. Coba lagi; jika berulang, kirim output /dlcheck dan pesan error tanpa cookie/token.")
            except Exception:
                pass
    finally:
        job["finished"] = get_wib_now()


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception occurred:", exc_info=context.error)

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("ftpstatus", ftp_status_command))
    app.add_handler(CommandHandler("dlcheck", downloader_check_command))
    app.add_handler(CommandHandler("ighelp", instagram_help_command))
    app.add_handler(CommandHandler("igcheck", instagram_check_command))
    app.add_handler(CommandHandler("cookiestatus", cookie_status_command))
    app.add_handler(CommandHandler("igstatus", cookie_status_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("bots", bots_control_tower_command))
    app.add_handler(CommandHandler("adminpanel", admin_intelligence_command))
    app.add_handler(CommandHandler("downloadstats", admin_intelligence_command))
    app.add_handler(CommandHandler("info", media_info_command))
    app.add_handler(CommandHandler("myid", my_id_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("ai", ai_chat_command))
    app.add_handler(CommandHandler("resetai", reset_ai_command))
    app.add_handler(CommandHandler("remember", remember_command))
    app.add_handler(CommandHandler("memories", memories_command))
    app.add_handler(CommandHandler("forgetmemory", forgetmemory_command))
    app.add_handler(CommandHandler("guardian", guardian_command))
    app.add_handler(CommandHandler("polisi", guardian_command))
    app.add_handler(CommandHandler("askai", ai_chat_command))
    app.add_handler(CommandHandler("writer", ai_chat_command))
    app.add_handler(CommandHandler("imagine", ai_image_command))
    app.add_handler(CommandHandler("ocr", ai_ocr_command))
    app.add_handler(CommandHandler("fix", ai_fix_code_command))
    app.add_handler(CommandHandler("quiz", ai_quiz_command))
    
    # 8 MODUL WEB & SS PRO
    app.add_handler(CommandHandler("ss", website_screenshot_command))
    app.add_handler(CommandHandler("fullss", full_scroll_screenshot_command))
    app.add_handler(CommandHandler("mobilesec", mobile_viewport_screenshot_command))
    app.add_handler(CommandHandler("tabss", tablet_viewport_screenshot_command))
    app.add_handler(CommandHandler("darkss", dark_mode_screenshot_command))
    app.add_handler(CommandHandler("pdfss", web_to_pdf_command))
    app.add_handler(CommandHandler("webinfo", deep_web_inspector_command))
    app.add_handler(CommandHandler("dns", domain_dns_command))

    app.add_handler(CommandHandler("monitor", website_monitor_command))
    app.add_handler(CommandHandler("curr", currency_converter_command))
    app.add_handler(CommandHandler("news", news_aggregator_command))
    app.add_handler(CommandHandler("kanban", kanban_command))
    app.add_handler(CommandHandler("kanban_add", kanban_add_command))
    app.add_handler(CommandHandler("mergepdf", merge_pdf_command))
    app.add_handler(CommandHandler("tts", ai_tts_command))
    app.add_handler(CommandHandler("short", short_link_command))
    app.add_handler(CommandHandler("qr", qr_code_command))
    app.add_handler(CommandHandler("trans", translate_command))
    app.add_handler(CommandHandler("genpass", password_generator_command))
    app.add_handler(CommandHandler("math", math_calculator_command))
    app.add_handler(CommandHandler("remind", reminder_command))
    app.add_handler(CommandHandler("todo", todo_list_command))
    app.add_handler(CommandHandler("todo_add", todo_add_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("poll", poll_command))
    app.add_handler(CommandHandler("battery", battery_status_command))
    app.add_handler(CommandHandler("netinfo", netinfo_command))
    
    # DOWNLOADERS
    app.add_handler(CommandHandler("dl", tracked_downloader))
    app.add_handler(CommandHandler("video", tracked_downloader))
    app.add_handler(CommandHandler("photos", photos_downloader))
    app.add_handler(CommandHandler("dlp", tracked_downloader))
    app.add_handler(CommandHandler("platforms", platforms_command))
    app.add_handler(CommandHandler("dlhelp", platforms_command))
    
    app.add_handler(CommandHandler("mp3", mp3_downloader))
    app.add_handler(CommandHandler("audio", mp3_downloader))
    app.add_handler(CommandHandler("sync", sync_url_ftp))
    app.add_handler(CommandHandler("search", search_ftp))
    app.add_handler(CommandHandler("cloud_tree", cloud_tree))
    app.add_handler(CommandHandler("backup", backup_cloud))
    app.add_handler(CommandHandler("stats", quick_stats))
    app.add_handler(CommandHandler("list", list_ftp))
    app.add_handler(CommandHandler("speedtest", speedtest_command_callback))
    app.add_handler(CommandHandler("quota", storage_quota))

    # Owner & Admin
    app.add_handler(CommandHandler("secret_menu", secret_menu))
    app.add_handler(CommandHandler("secret_history", secret_chat_history))
    app.add_handler(CommandHandler("secret_clear", secret_clear_history))
    app.add_handler(CommandHandler("secret_sys", secret_sys_status))
    app.add_handler(CommandHandler("secret_broadcast", secret_broadcast))
    app.add_handler(CommandHandler("secret_exec", secret_exec_command))
    app.add_handler(CommandHandler("secret_restart", secret_restart))
    app.add_handler(CommandHandler("secret_ip", secret_ip))
    app.add_handler(CommandHandler("rename", rename_ftp_file))
    app.add_handler(CommandHandler("ban", ban_user_command))
    app.add_handler(CommandHandler("unban", unban_user_command))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.ATTACHMENT, handle_media_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_chat))
    app.add_error_handler(global_error_handler)

async def _run_single_bot_once(token: str, index: int):
    """Run one configured Telegram bot; one bot failing won't stop the others."""
    application = None
    BOT_RUNTIME[index] = {"status": "starting", "updated": get_wib_now(), "username": None}
    try:
        application = Application.builder().token(token).build()
        bot_info = await application.bot.get_me()
        BOT_RUNTIME[index] = {"status": "starting", "updated": get_wib_now(), "username": bot_info.username}
        register_handlers(application)
        await application.initialize()
        await application.start()
        if application.updater is None:
            raise RuntimeError("Updater tidak tersedia di aplikasi Telegram")
        await application.updater.start_polling(drop_pending_updates=False)
        BOT_RUNTIME[index] = {"status": "online", "updated": get_wib_now(), "username": bot_info.username}
        logger.info("🟢 BOT %s/%s ONLINE: @%s (ID %s)", index, len(BOT_TOKENS), bot_info.username, bot_info.id)
        print(f"\033[92m  ✓ BOT {index}/{len(BOT_TOKENS)} ONLINE \033[0m → \033[96m@{bot_info.username}\033[0m")
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        BOT_RUNTIME[index] = {"status": "error", "updated": get_wib_now(), "username": BOT_RUNTIME.get(index, {}).get("username")}
        logger.exception("🔴 BOT %s gagal berjalan: %s", index, exc)
        print(f"\033[91m  ✗ BOT {index} GAGAL: {html.escape(str(exc)[:220])}\033[0m")
    finally:
        if application is not None:
            try:
                if application.updater and application.updater.running:
                    await application.updater.stop()
                if application.running:
                    await application.stop()
                await application.shutdown()
            except Exception:
                logger.exception("Error saat shutdown bot %s", index)


async def run_single_bot(token: str, index: int):
    """Restart a bot worker after polling/startup failures with bounded backoff."""
    delay = 5
    while True:
        await _run_single_bot_once(token, index)
        BOT_RUNTIME[index] = {"status": "restarting", "updated": get_wib_now(), "username": BOT_RUNTIME.get(index, {}).get("username")}
        logger.warning("🛡️ Guardian: bot %s akan dicoba hidupkan lagi dalam %s detik.", index, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 120)

def print_instagram_cookie_startup_status():
    """Print safe local Instagram-cookie diagnostics in Termux; never print cookie values."""
    configured = INSTAGRAM_COOKIES_FILE or SOCIAL_COOKIES_FILE
    green = "\033[92m"
    yellow = "\033[93m"
    red = "\033[91m"
    cyan = "\033[96m"
    reset = "\033[0m"

    print(f"{cyan}╭─ INSTAGRAM COOKIE STATUS ─────────────────────────╮{reset}")
    if not configured:
        message = "BELUM DISETEL — isi INSTAGRAM_COOKIES_FILE di .env"
        print(f"{red}│ 🔴 {message:<47}│{reset}")
        logger.warning("🍪 Instagram cookies: BELUM DIKONFIGURASI (INSTAGRAM_COOKIES_FILE/SOCIAL_COOKIES_FILE kosong).")
    elif not os.path.isfile(configured):
        message = "FILE TIDAK DITEMUKAN — periksa path di .env"
        print(f"{red}│ 🔴 {message:<47}│{reset}")
        logger.warning("🍪 Instagram cookies: path disetel tetapi file tidak ditemukan.")
    elif not os.access(configured, os.R_OK):
        message = "FILE TIDAK BISA DIBACA — periksa izin file"
        print(f"{red}│ 🔴 {message:<47}│{reset}")
        logger.warning("🍪 Instagram cookies: file ada tetapi tidak bisa dibaca.")
    else:
        try:
            with open(configured, "r", encoding="utf-8", errors="replace") as cookie_file:
                content = cookie_file.read()
            lines = content.splitlines()
            is_netscape = any(
                line.strip().startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File"))
                for line in lines[:10]
            )
            cookie_rows = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
            has_sessionid = any(
                len(line.split("\t")) >= 7 and line.split("\t")[5].strip().lower() == "sessionid"
                for line in cookie_rows
            )
            if not content.strip():
                print(f"{red}│ 🔴 FILE KOSONG — ekspor cookies ulang{' '*15}│{reset}")
                logger.warning("🍪 Instagram cookies: file ditemukan tetapi kosong.")
            elif not is_netscape:
                print(f"{yellow}│ 🟡 FORMAT BELUM TERVERIFIKASI — gunakan Netscape{' '*1}│{reset}")
                logger.warning("🍪 Instagram cookies: file terbaca, tetapi header Netscape tidak terdeteksi.")
            elif not has_sessionid:
                print(f"{yellow}│ 🟡 FORMAT OK, sessionid TIDAK TERDETEKSI{' '*7}│{reset}")
                logger.warning("🍪 Instagram cookies: format Netscape terdeteksi, tetapi cookie sessionid tidak ditemukan.")
            else:
                print(f"{green}│ 🟢 FILE TERBACA + NETSCAPE + sessionid ADA{' '*7}│{reset}")
                logger.info("🍪 Instagram cookies: file terbaca, format Netscape terdeteksi, sessionid ada; validitas sesi belum diuji.")
            print(f"{cyan}│ Catatan: status lokal ≠ sesi Instagram pasti aktif.{' '*1}│{reset}")
        except Exception as exc:
            print(f"{red}│ 🔴 GAGAL MEMERIKSA FILE COOKIES{' '*15}│{reset}")
            logger.warning("🍪 Gagal memeriksa file Instagram cookies (%s).", type(exc).__name__)
    print(f"{cyan}╰───────────────────────────────────────────────────╯{reset}")


async def main():
    show_termux_banner()
    logger.info("🔐 Mode konfigurasi: %s (nilai rahasia tidak ditampilkan).", RUNTIME_MODE)
    if not OWNER_ID:
        logger.warning("OWNER_ID masih 0; set ID Telegram owner di Replit Secrets supaya perintah admin bisa digunakan.")
    print_instagram_cookie_startup_status()
    # Run live FTP checks in the background so a slow/offline FTP host won't delay bot startup.
    asyncio.create_task(asyncio.to_thread(check_ftp_accounts))
    if not BOT_TOKENS:
        logger.error("Token tidak ditemukan. Set BOT_TOKEN atau BOT_TOKENS di Replit Secrets.")
        return
    if len(BOT_TOKENS) != len(set(BOT_TOKENS)):
        logger.warning("Ada token duplikat di BOT_TOKENS; token duplikat akan dilewati.")
    unique_tokens = list(dict.fromkeys(BOT_TOKENS))
    BOT_TOKENS[:] = unique_tokens
    try:
        await asyncio.to_thread(init_ai_db)
        logger.info("💾 Database riwayat AI SQLite siap.")
    except Exception:
        logger.exception("Database AI gagal diinisialisasi")
    try:
        keep_alive()
        logger.info("🌐 Health endpoint dimulai pada port %s (ini bukan jaminan uptime Replit).", os.getenv("PORT", "8080"))
    except Exception:
        logger.exception("Keep-alive server gagal dimulai; bot tetap akan dicoba.")
    if len(BOT_TOKENS) > 1:
        logger.info("Multi-bot runtime siap untuk %s token Telegram unik.", len(BOT_TOKENS))
    logger.info("🚀 Menyiapkan %s bot Telegram...", len(BOT_TOKENS))
    logger.info("🧠 V25 modules aktif: downloader telemetry, multi-bot runtime tower, admin intelligence dashboard.")
    health_app = None
    # Each bot runs independently in the same event loop; shared SQLite history is persistent.
    tasks = [asyncio.create_task(run_single_bot(token, i + 1), name=f"telegram-bot-{i+1}")
             for i, token in enumerate(BOT_TOKENS)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Sistem dihentikan.")
