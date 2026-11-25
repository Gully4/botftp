#!/usr/bin/env python3
"""NEON OS V32 Gateway: single bot supervisor + Cloudflare tunnel + PHP URL sync."""
from __future__ import annotations
import hmac, json, os, re, signal, subprocess, sys, threading, time, urllib.request, urllib.error
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query
import uvicorn
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
# Replit Secrets/environment variables win; local .env is only a fallback.
load_dotenv(BASE / ".env", override=False)
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
BOT_LOG, GATEWAY_LOG, TUNNEL_LOG = (LOG_DIR / n for n in ("bot.log", "gateway.log", "cloudflared.log"))
BOT_FILE = Path(os.getenv("NEON_BOT_FILE", "bot.py"))
if not BOT_FILE.is_absolute(): BOT_FILE = BASE / BOT_FILE
HOST = os.getenv("NEON_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.getenv("NEON_GATEWAY_PORT", "8765"))
API_KEY = os.getenv("NEON_API_KEY", "").strip()
RESTART_DELAY = max(3, min(300, int(os.getenv("NEON_RESTART_DELAY", "8"))))
AUTO_START = os.getenv("NEON_AUTO_START_BOT", "1").lower() not in {"0", "false", "no"}
AUTO_TUNNEL = os.getenv("NEON_AUTO_TUNNEL", "1").lower() not in {"0", "false", "no"}
SYNC_URL = os.getenv("NEON_HOSTING_SYNC_URL", "").strip()
SYNC_TOKEN = os.getenv("NEON_HOSTING_SYNC_TOKEN", "").strip()

_lock = threading.RLock()
_bot: Optional[subprocess.Popen] = None
_tunnel: Optional[subprocess.Popen] = None
_bot_started_at: Optional[float] = None
_bot_enabled = AUTO_START
_shutdown = False
_tunnel_url: Optional[str] = None
_last_sync: Optional[dict] = None


def log(message: str) -> None:
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(message)
    print(line, flush=True)
    try:
        with GATEWAY_LOG.open("a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass


def tail(path: Path, lines: int = 100) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-max(1, min(lines, 500)):]
    except FileNotFoundError: return []
    except Exception as exc: return [f"[log read error] {type(exc).__name__}\n"]


def sync_url_to_hosting(url: str) -> None:
    """Push the current Quick Tunnel URL to the authenticated PHP receiver."""
    global _last_sync
    if not SYNC_URL or not SYNC_TOKEN:
        _last_sync = {"ok": False, "state": "not_configured", "checked_at": int(time.time())}
        log("HOSTING URL SYNC belum dikonfigurasi; set NEON_HOSTING_SYNC_URL dan NEON_HOSTING_SYNC_TOKEN di Secrets.")
        return
    if not SYNC_URL.startswith("https://"):
        _last_sync = {"ok": False, "state": "invalid_sync_url", "checked_at": int(time.time())}
        log("HOSTING URL SYNC ditolak: endpoint harus HTTPS.")
        return
    body = json.dumps({"url": url, "updated_at": int(time.time())}).encode()
    req = urllib.request.Request(SYNC_URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + SYNC_TOKEN,
        "User-Agent": "NEON-OS-V32-Gateway"
    })
    last_error = "unknown"
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read(4096).decode("utf-8", "replace"))
                if response.status == 200 and payload.get("ok"):
                    _last_sync = {"ok": True, "state": "synced", "checked_at": int(time.time())}
                    log("HOSTING URL SYNC berhasil: PHP menerima URL tunnel terbaru.")
                    return
                last_error = f"HTTP {response.status}; receiver menolak/mengembalikan respons gagal"
        except Exception as exc:
            last_error = type(exc).__name__
        if attempt < 3: time.sleep(attempt * 3)
    _last_sync = {"ok": False, "state": "failed", "checked_at": int(time.time()), "error": last_error}
    log(f"HOSTING URL SYNC gagal setelah 3 percobaan ({last_error}). URL tetap tersedia di status Gateway/log tunnel.")


def _spawn_bot() -> dict:
    global _bot, _bot_started_at
    with _lock:
        if not BOT_FILE.is_file():
            log(f"BOT FILE NOT FOUND: {BOT_FILE.name}")
            return {"ok": False, "error": f"File bot tidak ditemukan: {BOT_FILE.name}"}
        if _bot is not None and _bot.poll() is None:
            return {"ok": True, "message": "Bot sudah berjalan", "pid": _bot.pid}
        env = os.environ.copy(); env["PYTHONUNBUFFERED"] = "1"
        try:
            out = BOT_LOG.open("a", encoding="utf-8")
            _bot = subprocess.Popen([sys.executable, "-u", str(BOT_FILE)], cwd=str(BASE), env=env,
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
            _bot_started_at = time.time()
            log(f"BOT STARTED pid={_bot.pid} file={BOT_FILE.name}")
            return {"ok": True, "pid": _bot.pid}
        except Exception as exc:
            log(f"BOT START ERROR: {type(exc).__name__}")
            return {"ok": False, "error": type(exc).__name__}


def _stop_bot(grace: int = 12) -> dict:
    global _bot, _bot_started_at
    with _lock:
        proc = _bot
        if proc is None or proc.poll() is not None:
            _bot = None; _bot_started_at = None
            return {"ok": True, "message": "Bot sudah berhenti"}
        pid = proc.pid
        try:
            proc.terminate()
            try: proc.wait(timeout=grace)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
            log(f"BOT STOPPED pid={pid}"); _bot = None; _bot_started_at = None
            return {"ok": True, "pid": pid}
        except Exception as exc:
            log(f"BOT STOP ERROR: {type(exc).__name__}")
            return {"ok": False, "error": type(exc).__name__}


def _supervisor() -> None:
    global _bot
    while not _shutdown:
        time.sleep(2)
        with _lock: enabled, proc = _bot_enabled, _bot
        if not enabled or _shutdown: continue
        if proc is None or proc.poll() is not None:
            if proc is not None:
                log(f"BOT EXITED code={proc.returncode}; restart in {RESTART_DELAY}s")
                with _lock:
                    if _bot is proc: _bot = None
            time.sleep(RESTART_DELAY)
            if _bot_enabled and not _shutdown: _spawn_bot()


def _find_cloudflared() -> Optional[str]:
    import shutil
    for item in (os.getenv("CLOUDFLARED_BIN", ""), str(Path.home()/".local/bin/cloudflared"), "cloudflared"):
        if not item: continue
        found = shutil.which(item) if os.path.sep not in item else (item if Path(item).is_file() else None)
        if found: return found
    return None


def _read_tunnel(pipe) -> None:
    global _tunnel_url
    pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
    for raw in iter(pipe.readline, ""):
        line = raw.rstrip()
        if not line: continue
        try:
            with TUNNEL_LOG.open("a", encoding="utf-8") as f: f.write(line + "\n")
        except Exception: pass
        match = pattern.search(line)
        if match:
            url = match.group(0)
            if url != _tunnel_url:
                _tunnel_url = url
                log(f"CLOUDFLARE QUICK TUNNEL READY: {url}")
                threading.Thread(target=sync_url_to_hosting, args=(url,), daemon=True).start()
        if "ERR" in line.upper() or "ERROR" in line.upper(): log(f"CLOUDFLARED: {line[:400]}")


def _start_tunnel() -> None:
    global _tunnel
    if not AUTO_TUNNEL: log("AUTO TUNNEL disabled by NEON_AUTO_TUNNEL=0"); return
    binary = _find_cloudflared()
    if not binary:
        log("CLOUDFLARED NOT FOUND. Pastikan paket cloudflared tersedia pada Replit Nix.")
        return
    if _tunnel is not None and _tunnel.poll() is None: return
    try:
        _tunnel = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
            cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
        threading.Thread(target=_read_tunnel, args=(_tunnel.stdout,), daemon=True).start()
        log(f"CLOUDFLARED STARTED pid={_tunnel.pid}")
    except Exception as exc: log(f"CLOUDFLARED START ERROR: {type(exc).__name__}")


def _tunnel_supervisor() -> None:
    while not _shutdown:
        time.sleep(5)
        if AUTO_TUNNEL and (_tunnel is None or _tunnel.poll() is not None):
            if _tunnel is not None: log("CLOUDFLARED EXITED; mencoba membuat tunnel baru dalam 5 detik.")
            time.sleep(5)
            if not _shutdown: _start_tunnel()


def require_key(x_api_key: str = Header(default="")) -> None:
    if not API_KEY or len(API_KEY) < 24:
        raise HTTPException(status_code=503, detail="NEON_API_KEY belum disetel atau minimal 24 karakter")
    if not hmac.compare_digest(x_api_key.strip(), API_KEY):
        raise HTTPException(status_code=401, detail="API key tidak cocok")

app = FastAPI(title="NEON OS Gateway", version="32.0")

@app.on_event("startup")
def on_startup():
    threading.Thread(target=_supervisor, daemon=True).start()
    threading.Thread(target=_tunnel_supervisor, daemon=True).start()
    if _bot_enabled: _spawn_bot()
    _start_tunnel()
    log(f"NEON GATEWAY V32 READY host={HOST} port={PORT}")

@app.on_event("shutdown")
def on_shutdown():
    global _shutdown
    _shutdown = True; _stop_bot()
    if _tunnel is not None and _tunnel.poll() is None:
        try: _tunnel.terminate()
        except Exception: pass
    log("GATEWAY SHUTDOWN")

@app.get("/health")
def health(): return {"ok": True, "service": "neon-gateway", "version": "32.0", "port": PORT}

@app.get("/api/status", dependencies=[Depends(require_key)])
def status():
    with _lock:
        proc = _bot; running = proc is not None and proc.poll() is None
        return {"ok": True, "gateway": "online", "version": "32.0", "bot_file": BOT_FILE.name,
            "bot_exists": BOT_FILE.is_file(), "bot_running": running, "bot_pid": proc.pid if running else None,
            "bot_exit_code": proc.returncode if proc is not None and not running else None,
            "bot_uptime_seconds": int(time.time()-_bot_started_at) if running and _bot_started_at else 0,
            "auto_restart": _bot_enabled, "tunnel_url": _tunnel_url,
            "tunnel_running": _tunnel is not None and _tunnel.poll() is None,
            "hosting_sync": _last_sync or {"state": "waiting_for_tunnel"}, "gateway_port": PORT}

@app.get("/api/logs", dependencies=[Depends(require_key)])
def logs(lines: int = Query(default=80, ge=1, le=500), target: str = Query(default="bot")):
    paths = {"bot": BOT_LOG, "gateway": GATEWAY_LOG, "tunnel": TUNNEL_LOG}
    if target not in paths: raise HTTPException(status_code=400, detail="target harus bot, gateway, atau tunnel")
    return {"ok": True, "target": target, "lines": tail(paths[target], lines)}

@app.post("/api/start", dependencies=[Depends(require_key)])
def start():
    global _bot_enabled
    _bot_enabled = True; return _spawn_bot()

@app.post("/api/stop", dependencies=[Depends(require_key)])
def stop():
    global _bot_enabled
    _bot_enabled = False; return _stop_bot()

@app.post("/api/restart", dependencies=[Depends(require_key)])
def restart():
    global _bot_enabled
    _bot_enabled = True; stopped = _stop_bot(); time.sleep(1); started = _spawn_bot()
    return {"ok": bool(started.get("ok")), "stopped": stopped, "started": started}

if __name__ == "__main__":
    if not API_KEY or len(API_KEY) < 24: log("WARNING: NEON_API_KEY kosong/pendek; endpoint kontrol akan menolak request.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
