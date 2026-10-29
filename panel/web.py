"""
Phone VPS Control Panel - Flask web application
Runs inside Termux on Sony Xperia 5 II
"""

import os
import json
import time
import re
import shutil
import subprocess
import signal
import platform
import multiprocessing
import secrets
import getpass
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, render_template, jsonify, request,
    send_from_directory, redirect, url_for, flash, session
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB per request

# Paths
HOME = os.path.expanduser("~")
VPS_DIR = os.path.join(HOME, "vps")
WWW_DIR = os.path.join(VPS_DIR, "www")
FILES_DIR = os.path.join(VPS_DIR, "files")
LOGS_DIR = os.path.join(VPS_DIR, "logs")
CONFIG_FILE = os.path.join(VPS_DIR, "config", "panel.json")
TUNNEL_LOG = os.path.join(LOGS_DIR, "tunnel.log")
TUNNEL_URL_FILE = os.path.join(VPS_DIR, "config", "tunnel_url.txt")
TUNNEL_TOKEN_FILE = os.path.join(VPS_DIR, "config", "tunnel_token.txt")
PERMANENT_URL = os.environ.get("PANEL_PUBLIC_URL", "").rstrip("/")   # e.g. https://vps.example.com (your named tunnel)
LOCKS_FILE = os.path.join(VPS_DIR, "config", "locks.json")
TRASH_DIR = os.path.join(VPS_DIR, ".trash")
TRASH_META = os.path.join(TRASH_DIR, ".meta.json")

# Ensure directories exist
for d in [WWW_DIR, FILES_DIR, LOGS_DIR, os.path.join(VPS_DIR, "config"), TRASH_DIR]:
    os.makedirs(d, exist_ok=True)

# Default config. The panel password is random on first start (printed once in the panel log) unless PANEL_PASSWORD is set.
DEFAULT_CONFIG = {
    "hostname": "Phone-VPS",
    "ssh_port": 8022,
    "http_port": 8080,
    "panel_port": 5000,
    "password": os.environ.get("PANEL_PASSWORD") or secrets.token_urlsafe(12),
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    cfg = dict(DEFAULT_CONFIG)
    save_config(cfg)
    print(f"[panel] first start: created {CONFIG_FILE} - panel password: {cfg['password']}", flush=True)
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ──────────── File Lock Helpers ────────────

def load_locks():
    if os.path.exists(LOCKS_FILE):
        with open(LOCKS_FILE) as f:
            return json.load(f)
    return {}


def save_locks(locks):
    with open(LOCKS_FILE, "w") as f:
        json.dump(locks, f, indent=2)


def _get_lock_hash(entry):
    """Get hash from lock entry (old string format or new dict format)."""
    if isinstance(entry, dict):
        return entry.get("hash", "")
    return entry


def is_path_locked(section, rel_path):
    """Check if a path or any of its parents is locked."""
    locks = load_locks()
    parts = rel_path.replace("\\", "/").split("/")
    for i in range(len(parts), 0, -1):
        check = "/".join(parts[:i])
        key = f"{section}:{check}"
        if key in locks:
            return True
    return False


def is_path_unlocked(section, rel_path):
    """Check if the request carries a valid lock password via header or query param."""
    pw = request.headers.get("X-Lock-Password", "") or request.args.get("lock_pw", "")
    if not pw:
        return False
    import hashlib
    pw_hash = hashlib.sha256(pw.encode()).hexdigest()
    lock_hash = get_lock_password(section, rel_path)
    return lock_hash and pw_hash == lock_hash


def get_lock_password(section, rel_path):
    """Get the lock password hash for a path or its parent."""
    locks = load_locks()
    parts = rel_path.replace("\\", "/").split("/")
    for i in range(len(parts), 0, -1):
        check = "/".join(parts[:i])
        key = f"{section}:{check}"
        if key in locks:
            return _get_lock_hash(locks[key])


def get_locked_ancestor(section, rel_path):
    """Get the actual locked ancestor path."""
    locks = load_locks()
    parts = rel_path.replace("\\", "/").split("/")
    for i in range(len(parts), 0, -1):
        check = "/".join(parts[:i])
        key = f"{section}:{check}"
        if key in locks:
            return check
    return None


# ──────────── Trash / Recycle Bin Helpers ────────────

def _load_trash_meta():
    if os.path.exists(TRASH_META):
        with open(TRASH_META) as f:
            return json.load(f)
    return []


def _save_trash_meta(meta):
    with open(TRASH_META, "w") as f:
        json.dump(meta, f, indent=2)


def _move_to_trash(rel_path, section):
    """Move a file or folder to the trash directory instead of permanent delete."""
    import uuid
    base_dir = FILES_DIR if section == "files" else WWW_DIR
    full_path = os.path.normpath(os.path.join(base_dir, rel_path))
    if not full_path.startswith(os.path.normpath(base_dir)):
        raise ValueError("Access denied")
    trash_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    trash_dest = os.path.join(TRASH_DIR, trash_id)
    is_dir = os.path.isdir(full_path)
    shutil.move(full_path, trash_dest)
    meta = _load_trash_meta()
    meta.append({
        "id": trash_id,
        "original_name": os.path.basename(full_path),
        "original_path": rel_path.replace("\\", "/"),
        "section": section,
        "is_dir": is_dir,
        "deleted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "size": _get_size(trash_dest),
    })
    _save_trash_meta(meta)


def _get_size(path):
    """Get total size of a file or directory in bytes."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
    return total


# Persistent secret key
_cfg = load_config()
if "secret_key" not in _cfg:
    _cfg["secret_key"] = os.urandom(24).hex()
    save_config(_cfg)
app.secret_key = _cfg["secret_key"]
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


# ──────────── Authentication ────────────

@app.before_request
def require_login():
    if request.endpoint in ("login", "static", "login_asset", "public_site", "public_site_root"):
        return
    if request.path.startswith("/site"):
        return
    if not session.get("authenticated"):
        if request.is_json or request.path.startswith("/api/"):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for("login"))


@app.route("/asset/<path:filename>")
def login_asset(filename):
    asset_dir = os.path.join(os.path.dirname(__file__), "templates", "asset")
    return send_from_directory(asset_dir, filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        config = load_config()
        if password == config["password"]:
            session.permanent = True
            session["authenticated"] = True
            return redirect(url_for("dashboard"))
        error = "Invalid password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ──────────── System Info Helpers ────────────

def get_cpu_info():
    try:
        count = multiprocessing.cpu_count()
    except Exception:
        count = 0
    load = {"1min": 0, "5min": 0, "15min": 0}
    try:
        avg = os.getloadavg()
        load = {"1min": round(avg[0], 2), "5min": round(avg[1], 2), "15min": round(avg[2], 2)}
    except Exception:
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                load = {"1min": round(float(parts[0]), 2), "5min": round(float(parts[1]), 2), "15min": round(float(parts[2]), 2)}
        except Exception:
            try:
                out = subprocess.check_output(["uptime"], stderr=subprocess.DEVNULL, timeout=5).decode()
                # Parse "load average: 2.27, 2.24, 2.16"
                if "load average:" in out:
                    avg_str = out.split("load average:")[1].strip()
                    vals = [float(x.strip().rstrip(',')) for x in avg_str.split(",")]
                    if len(vals) >= 3:
                        load = {"1min": round(vals[0], 2), "5min": round(vals[1], 2), "15min": round(vals[2], 2)}
            except Exception:
                pass
    return {"cores": count, "load": load}


def get_memory_info():
    info = {"total_mb": 0, "available_mb": 0, "used_mb": 0, "percent": 0}
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])
            total = mem.get("MemTotal", 0) // 1024
            available = mem.get("MemAvailable", 0) // 1024
            used = total - available
            info = {
                "total_mb": total,
                "available_mb": available,
                "used_mb": used,
                "percent": round(used / total * 100, 1) if total else 0,
            }
    except Exception:
        pass
    return info


def get_storage_info():
    try:
        stat = shutil.disk_usage(HOME)
        total_gb = round(stat.total / (1024**3), 1)
        used_gb = round(stat.used / (1024**3), 1)
        free_gb = round(stat.free / (1024**3), 1)
        percent = round(stat.used / stat.total * 100, 1) if stat.total else 0
        return {
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "percent": percent,
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
            return str(timedelta(seconds=int(secs)))
    except Exception:
        pass
    try:
        out = subprocess.check_output(["uptime"], stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        # Parse "HH:MM:SS up X days, ..." format
        if "up" in out:
            up_part = out.split("up", 1)[1].split(",")
            parts = [p.strip() for p in up_part if p.strip()]
            result = []
            for p in parts:
                if "day" in p or "min" in p or "hour" in p:
                    result.append(p.strip())
                    break
                elif ":" in p:
                    result.append(p.strip())
                    break
                else:
                    result.append(p.strip())
            return ", ".join(result) if result else out
        return out
    except Exception:
        return "N/A"


def get_network_info():
    ip = "127.0.0.1"
    try:
        out = subprocess.check_output(["ip", "route", "get", "1.1.1.1"],
                                      stderr=subprocess.DEVNULL, timeout=5).decode()
        for part in out.split():
            idx = out.find("src ")
            if idx != -1:
                ip = out[idx+4:].split()[0]
                break
    except Exception:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
    return {"ip": ip}


def is_service_running(name):
    """Check if a service process is running."""
    try:
        result = subprocess.run(["pgrep", "-f", name],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def get_service_pid(name):
    try:
        result = subprocess.run(["pgrep", "-f", name],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def get_all_status():
    config = load_config()
    cpu = get_cpu_info()
    mem = get_memory_info()
    storage = get_storage_info()
    net = get_network_info()

    services = {
        "ssh": {
            "running": is_service_running("sshd"),
            "port": config["ssh_port"],
            "pid": get_service_pid("sshd"),
        },
        "http": {
            "running": is_service_running("http.server"),
            "port": config["http_port"],
            "pid": get_service_pid("http.server"),
        },
        "panel": {
            "running": True,
            "port": config["panel_port"],
            "pid": str(os.getpid()),
        },
        "tunnel": {
            "running": is_service_running("cloudflared"),
            "port": "-",
            "pid": get_service_pid("cloudflared"),
        },
        "watchdog": {
            "running": is_service_running("watchdog.sh"),
            "port": "-",
            "pid": get_service_pid("watchdog.sh"),
        },
    }

    return {
        "hostname": config["hostname"],
        "ip": net["ip"],
        "os": f"Android / Termux",
        "python": platform.python_version(),
        "cpu": cpu,
        "memory": mem,
        "storage": storage,
        "uptime": get_uptime(),
        "services": services,
        "ssh_port": config["ssh_port"],
        "ssh_user": config.get("ssh_user") or getpass.getuser(),
        "ssh_password": config["password"],
        "status": "online",
        "tunnel": {
            "running": is_service_running("cloudflared"),
            "url": get_tunnel_url(),
        },
    }


# ──────────── Tunnel Helpers ────────────

def get_tunnel_url():
    """Get the permanent tunnel URL if cloudflared is running."""
    if PERMANENT_URL and is_service_running("cloudflared"):
        return PERMANENT_URL
    return None


# ──────────── File Manager Helpers ────────────

def get_dir_listing(base_dir, rel_path=""):
    full_path = os.path.normpath(os.path.join(base_dir, rel_path))
    # Prevent directory traversal
    if not full_path.startswith(os.path.normpath(base_dir)):
        return None, "Access denied"

    if not os.path.exists(full_path):
        os.makedirs(full_path, exist_ok=True)

    items = []
    try:
        for entry in sorted(os.scandir(full_path), key=lambda e: (not e.is_dir(), e.name.lower())):
            stat = entry.stat()
            ext = entry.name.rsplit(".", 1)[-1].lower() if "." in entry.name else ""
            file_type = "folder" if entry.is_dir() else classify_file(ext)
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": stat.st_size if entry.is_file() else 0,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "date_group": datetime.fromtimestamp(stat.st_mtime).strftime("%B %Y"),
                "date_day": datetime.fromtimestamp(stat.st_mtime).strftime("%a, %b %d, %Y"),
                "date_sort": stat.st_mtime,
                "path": os.path.join(rel_path, entry.name) if rel_path else entry.name,
                "ext": ext,
                "type": file_type,
            })
    except PermissionError:
        return None, "Permission denied"

    return items, None


MEDIA_EXTS = {
    "image": {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "ico", "tiff", "tif", "heic", "heif"},
    "video": {"mp4", "mkv", "avi", "mov", "webm", "3gp", "flv", "wmv", "m4v"},
    "audio": {"mp3", "wav", "ogg", "flac", "aac", "m4a", "wma"},
    "text": {"txt", "md", "log", "csv", "json", "xml", "html", "htm", "css", "js", "py", "sh", "yaml", "yml", "cfg", "conf", "ini", "toml"},
    "pdf": {"pdf"},
    "archive": {"zip", "tar", "gz", "bz2", "7z", "rar", "xz"},
}


def classify_file(ext):
    for ftype, exts in MEDIA_EXTS.items():
        if ext in exts:
            return ftype
    return "other"


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"


# ──────────── Routes: Dashboard ────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(get_all_status())


# ──────────── Routes: Service Control ────────────

@app.route("/api/service/<name>/<action>", methods=["POST"])
def api_service_control(name, action):
    config = load_config()

    if name == "ssh":
        if action == "start":
            subprocess.Popen(["sshd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return jsonify({"ok": True, "msg": "SSH started"})
        elif action == "stop":
            subprocess.run(["pkill", "sshd"], capture_output=True)
            return jsonify({"ok": True, "msg": "SSH stopped"})

    elif name == "http":
        if action == "start":
            subprocess.Popen(
                ["python3", "-m", "http.server", str(config["http_port"])],
                cwd=WWW_DIR,
                stdout=open(os.path.join(LOGS_DIR, "http.log"), "a"),
                stderr=subprocess.STDOUT,
            )
            return jsonify({"ok": True, "msg": "HTTP server started"})
        elif action == "stop":
            subprocess.run(["pkill", "-f", "http.server"], capture_output=True)
            return jsonify({"ok": True, "msg": "HTTP server stopped"})

    elif name == "tunnel":
        if action == "start":
            return api_tunnel_start()
        elif action == "stop":
            return api_tunnel_stop()

    elif name == "watchdog":
        if action == "start":
            subprocess.Popen(
                ["bash", os.path.join(HOME, "panel", "watchdog.sh")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return jsonify({"ok": True, "msg": "Watchdog started"})
        elif action == "stop":
            subprocess.run(["pkill", "-f", "watchdog.sh"], capture_output=True)
            return jsonify({"ok": True, "msg": "Watchdog stopped"})

    elif action == "restart":
        # Generic restart: stop then start
        api_service_control(name, "stop")
        time.sleep(1)
        return api_service_control(name, "start")

    return jsonify({"ok": False, "msg": "Unknown service/action"}), 400


@app.route("/api/start-all", methods=["POST"])
def api_start_all():
    """Start all services that are not already running."""
    started = []
    config = load_config()
    if not is_service_running("sshd"):
        subprocess.Popen(["sshd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started.append("SSH")
    if not is_service_running("http.server"):
        subprocess.Popen(
            ["python3", "-m", "http.server", str(config["http_port"])],
            cwd=WWW_DIR,
            stdout=open(os.path.join(LOGS_DIR, "http.log"), "a"),
            stderr=subprocess.STDOUT,
        )
        started.append("HTTP")
    if not is_service_running("cloudflared"):
        result = api_tunnel_start()
        started.append("Tunnel")
    if not is_service_running("watchdog.sh"):
        subprocess.Popen(
            ["bash", os.path.join(HOME, "panel", "watchdog.sh")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        started.append("Watchdog")
    msg = f"Started: {', '.join(started)}" if started else "All services already running"
    return jsonify({"ok": True, "msg": msg})


@app.route("/api/stop-all", methods=["POST"])
def api_stop_all():
    """Stop all services except panel."""
    stopped = []
    subprocess.run(["pkill", "-f", "watchdog.sh"], capture_output=True)
    stopped.append("Watchdog")
    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
    stopped.append("Tunnel")
    subprocess.run(["pkill", "-f", "http.server"], capture_output=True)
    stopped.append("HTTP")
    subprocess.run(["pkill", "sshd"], capture_output=True)
    stopped.append("SSH")
    return jsonify({"ok": True, "msg": f"Stopped: {', '.join(stopped)}"})


@app.route("/api/reboot", methods=["POST"])
def api_reboot():
    """Restart all services."""
    subprocess.run(["pkill", "-f", "watchdog.sh"], capture_output=True)
    subprocess.run(["pkill", "sshd"], capture_output=True)
    subprocess.run(["pkill", "-f", "http.server"], capture_output=True)
    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
    time.sleep(2)
    subprocess.Popen(["sshd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    config = load_config()
    subprocess.Popen(
        ["python3", "-m", "http.server", str(config["http_port"])],
        cwd=WWW_DIR,
        stdout=open(os.path.join(LOGS_DIR, "http.log"), "a"),
        stderr=subprocess.STDOUT,
    )
    # Restart tunnel
    token = ""
    if os.path.exists(TUNNEL_TOKEN_FILE):
        with open(TUNNEL_TOKEN_FILE) as f:
            token = f.read().strip()
    if token:
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        resolv = os.path.join(prefix, "etc/resolv.conf")
        cacert = os.path.join(prefix, "etc/tls/cert.pem")
        with open(TUNNEL_LOG, "w") as log:
            subprocess.Popen(
                ["proot",
                 "-b", f"{resolv}:/etc/resolv.conf",
                 "-b", f"{cacert}:/etc/ssl/certs/ca-certificates.crt",
                 "cloudflared", "tunnel", "--protocol", "http2", "--no-autoupdate",
                 "run", "--token", token],
                stdout=log, stderr=log,
            )
    # Restart watchdog
    subprocess.Popen(
        ["bash", os.path.join(HOME, "panel", "watchdog.sh")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return jsonify({"ok": True, "msg": "All services restarted"})


# ──────────── Routes: File Manager ────────────

@app.route("/files")
@app.route("/files/<path:subpath>")
def file_manager(subpath=""):
    return render_template("files.html", current_path=subpath, section="files")


@app.route("/api/files/list")
@app.route("/api/files/list/<path:subpath>")
def api_files_list(subpath=""):
    # Check if current directory is locked
    if subpath and is_path_locked("files", subpath):
        lock_key = get_lock_password("files", subpath)
        if lock_key and not is_path_unlocked("files", subpath):
            return jsonify({"locked": True, "path": subpath, "items": [], "parent": os.path.dirname(subpath) if subpath else None})
    items, err = get_dir_listing(FILES_DIR, subpath)
    if err:
        return jsonify({"error": err}), 403
    locks = load_locks()
    for item in items:
        item["size_fmt"] = format_size(item["size"])
        rel_key = f"files:{item['path']}"
        raw_locked = rel_key in locks or is_path_locked("files", item["path"])
        item["locked"] = raw_locked and not is_path_unlocked("files", item["path"])
    parent = os.path.dirname(subpath) if subpath else None
    return jsonify({"items": items, "path": subpath, "parent": parent})


@app.route("/api/files/upload", methods=["POST"])
def api_files_upload():
    subpath = request.form.get("path", "")
    target_dir = os.path.normpath(os.path.join(FILES_DIR, subpath))
    if not target_dir.startswith(os.path.normpath(FILES_DIR)):
        return jsonify({"error": "Access denied"}), 403

    os.makedirs(target_dir, exist_ok=True)
    uploaded = []
    for f in request.files.getlist("files"):
        if f.filename:
            filename = secure_filename(f.filename)
            f.save(os.path.join(target_dir, filename))
            uploaded.append(filename)
    return jsonify({"ok": True, "uploaded": uploaded})


@app.route("/api/files/mkdir", methods=["POST"])
def api_files_mkdir():
    data = request.get_json()
    subpath = data.get("path", "")
    name = secure_filename(data.get("name", ""))
    if not name:
        return jsonify({"error": "Invalid name"}), 400
    target = os.path.normpath(os.path.join(FILES_DIR, subpath, name))
    if not target.startswith(os.path.normpath(FILES_DIR)):
        return jsonify({"error": "Access denied"}), 403
    os.makedirs(target, exist_ok=True)
    return jsonify({"ok": True})


@app.route("/api/files/delete", methods=["POST"])
def api_files_delete():
    data = request.get_json()
    filepath = data.get("path", "")
    target = os.path.normpath(os.path.join(FILES_DIR, filepath))
    if not target.startswith(os.path.normpath(FILES_DIR)):
        return jsonify({"error": "Access denied"}), 403
    if not os.path.exists(target):
        return jsonify({"error": "Not found"}), 404
    _move_to_trash(filepath, "files")
    return jsonify({"ok": True})


@app.route("/api/files/bulk-delete", methods=["POST"])
def api_files_bulk_delete():
    data = request.get_json()
    paths = data.get("paths", [])
    if not isinstance(paths, list):
        return jsonify({"error": "Invalid paths"}), 400
    deleted = []
    errors = []
    for filepath in paths:
        target = os.path.normpath(os.path.join(FILES_DIR, filepath))
        if not target.startswith(os.path.normpath(FILES_DIR)):
            errors.append({"path": filepath, "error": "Access denied"})
            continue
        if not os.path.exists(target):
            errors.append({"path": filepath, "error": "Not found"})
            continue
        try:
            _move_to_trash(filepath, "files")
            deleted.append(filepath)
        except Exception as e:
            errors.append({"path": filepath, "error": str(e)})
    return jsonify({"ok": True, "deleted": deleted, "errors": errors})


@app.route("/api/files/rename", methods=["POST"])
def api_files_rename():
    data = request.get_json()
    filepath = data.get("path", "")
    new_name = secure_filename(data.get("name", ""))
    if not new_name:
        return jsonify({"error": "Invalid name"}), 400
    old_full = os.path.normpath(os.path.join(FILES_DIR, filepath))
    if not old_full.startswith(os.path.normpath(FILES_DIR)):
        return jsonify({"error": "Access denied"}), 403
    if not os.path.exists(old_full):
        return jsonify({"error": "Not found"}), 404
    new_full = os.path.join(os.path.dirname(old_full), new_name)
    if os.path.exists(new_full):
        return jsonify({"error": "Name already exists"}), 400
    os.rename(old_full, new_full)
    return jsonify({"ok": True})


@app.route("/api/files/download/<path:filepath>")
def api_files_download(filepath):
    # Check lock
    if is_path_locked("files", filepath) and not is_path_unlocked("files", filepath):
        return "Locked", 403
    full = os.path.normpath(os.path.join(FILES_DIR, filepath))
    if not full.startswith(os.path.normpath(FILES_DIR)):
        return "Access denied", 403
    if not os.path.isfile(full):
        return "Not found", 404
    directory = os.path.dirname(full)
    filename = os.path.basename(full)
    return send_from_directory(directory, filename, as_attachment=True)


def _serve_heic_as_jpeg(full_path):
    """Convert HEIC/HEIF to JPEG on-the-fly and return as response."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        from PIL import Image
        from io import BytesIO
        from flask import Response
        img = Image.open(full_path)
        img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return Response(buf.getvalue(), mimetype="image/jpeg")
    except Exception as e:
        return f"Failed to convert HEIC: {e}", 500


@app.route("/api/files/raw/<path:filepath>")
def api_files_raw(filepath):
    if is_path_locked("files", filepath) and not is_path_unlocked("files", filepath):
        return "Locked", 403
    full = os.path.normpath(os.path.join(FILES_DIR, filepath))
    if not full.startswith(os.path.normpath(FILES_DIR)):
        return "Access denied", 403
    if not os.path.isfile(full):
        return "Not found", 404
    # Convert HEIC/HEIF to JPEG on-the-fly for browser compatibility
    ext = os.path.splitext(full)[1].lower()
    if ext in ('.heic', '.heif'):
        return _serve_heic_as_jpeg(full)
    directory = os.path.dirname(full)
    filename = os.path.basename(full)
    return send_from_directory(directory, filename, as_attachment=False)


@app.route("/api/websites/raw/<path:filepath>")
def api_websites_raw(filepath):
    if is_path_locked("websites", filepath) and not is_path_unlocked("websites", filepath):
        return "Locked", 403
    full = os.path.normpath(os.path.join(WWW_DIR, filepath))
    if not full.startswith(os.path.normpath(WWW_DIR)):
        return "Access denied", 403
    if not os.path.isfile(full):
        return "Not found", 404
    ext = os.path.splitext(full)[1].lower()
    if ext in ('.heic', '.heif'):
        return _serve_heic_as_jpeg(full)
    directory = os.path.dirname(full)
    filename = os.path.basename(full)
    return send_from_directory(directory, filename, as_attachment=False)


# ──────────── Routes: File/Folder Locking ────────────

@app.route("/api/lock", methods=["POST"])
def api_lock():
    data = request.get_json()
    section = data.get("section", "files")
    path = data.get("path", "")
    password = data.get("password", "")
    if not path or not password or len(password) < 1:
        return jsonify({"error": "Path and password required"}), 400
    locks = load_locks()
    key = f"{section}:{path}"
    import hashlib
    locks[key] = {"hash": hashlib.sha256(password.encode()).hexdigest(), "pw": password}
    save_locks(locks)
    return jsonify({"ok": True, "msg": f"Locked: {path}"})


@app.route("/api/unlock", methods=["POST"])
def api_unlock_path():
    data = request.get_json()
    section = data.get("section", "files")
    path = data.get("path", "")
    password = data.get("password", "")
    if not path or not password:
        return jsonify({"error": "Path and password required"}), 400
    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    lock_hash = get_lock_password(section, path)
    if lock_hash and pw_hash == lock_hash:
        return jsonify({"ok": True, "msg": "Unlocked"})
    return jsonify({"error": "Wrong password"}), 403


@app.route("/api/lock/remove", methods=["POST"])
def api_lock_remove():
    data = request.get_json()
    section = data.get("section", "files")
    path = data.get("path", "")
    password = data.get("password", "")
    if not path or not password:
        return jsonify({"error": "Path and password required"}), 400
    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    locks = load_locks()
    key = f"{section}:{path}"
    if key in locks and _get_lock_hash(locks[key]) == pw_hash:
        del locks[key]
        save_locks(locks)
        return jsonify({"ok": True, "msg": f"Lock removed: {path}"})
    return jsonify({"error": "Wrong password"}), 403


@app.route("/api/locks/list")
def api_locks_list():
    locks = load_locks()
    result = []
    for key in locks:
        section, path = key.split(":", 1)
        result.append({"section": section, "path": path, "has_lock": True})
    return jsonify({"locks": result})


# ──────────── Routes: Website Space ────────────

@app.route("/websites")
@app.route("/websites/<path:subpath>")
def website_space(subpath=""):
    return render_template("files.html", current_path=subpath, section="websites")


@app.route("/api/websites/list")
@app.route("/api/websites/list/<path:subpath>")
def api_websites_list(subpath=""):
    items, err = get_dir_listing(WWW_DIR, subpath)
    if err:
        return jsonify({"error": err}), 403
    for item in items:
        item["size_fmt"] = format_size(item["size"])
    parent = os.path.dirname(subpath) if subpath else None
    config = load_config()
    return jsonify({
        "items": items,
        "path": subpath,
        "parent": parent,
        "http_port": config["http_port"],
        "http_running": is_service_running("http.server"),
    })


@app.route("/api/websites/upload", methods=["POST"])
def api_websites_upload():
    subpath = request.form.get("path", "")
    target_dir = os.path.normpath(os.path.join(WWW_DIR, subpath))
    if not target_dir.startswith(os.path.normpath(WWW_DIR)):
        return jsonify({"error": "Access denied"}), 403

    os.makedirs(target_dir, exist_ok=True)
    uploaded = []
    for f in request.files.getlist("files"):
        if f.filename:
            filename = secure_filename(f.filename)
            f.save(os.path.join(target_dir, filename))
            uploaded.append(filename)
    return jsonify({"ok": True, "uploaded": uploaded})


@app.route("/api/websites/mkdir", methods=["POST"])
def api_websites_mkdir():
    data = request.get_json()
    subpath = data.get("path", "")
    name = secure_filename(data.get("name", ""))
    if not name:
        return jsonify({"error": "Invalid name"}), 400
    target = os.path.normpath(os.path.join(WWW_DIR, subpath, name))
    if not target.startswith(os.path.normpath(WWW_DIR)):
        return jsonify({"error": "Access denied"}), 403
    os.makedirs(target, exist_ok=True)
    return jsonify({"ok": True})


@app.route("/api/websites/delete", methods=["POST"])
def api_websites_delete():
    data = request.get_json()
    filepath = data.get("path", "")
    target = os.path.normpath(os.path.join(WWW_DIR, filepath))
    if not target.startswith(os.path.normpath(WWW_DIR)):
        return jsonify({"error": "Access denied"}), 403
    if not os.path.exists(target):
        return jsonify({"error": "Not found"}), 404
    _move_to_trash(filepath, "websites")
    return jsonify({"ok": True})


@app.route("/api/websites/bulk-delete", methods=["POST"])
def api_websites_bulk_delete():
    data = request.get_json()
    paths = data.get("paths", [])
    if not isinstance(paths, list):
        return jsonify({"error": "Invalid paths"}), 400
    deleted = []
    errors = []
    for filepath in paths:
        target = os.path.normpath(os.path.join(WWW_DIR, filepath))
        if not target.startswith(os.path.normpath(WWW_DIR)):
            errors.append({"path": filepath, "error": "Access denied"})
            continue
        if not os.path.exists(target):
            errors.append({"path": filepath, "error": "Not found"})
            continue
        try:
            _move_to_trash(filepath, "websites")
            deleted.append(filepath)
        except Exception as e:
            errors.append({"path": filepath, "error": str(e)})
    return jsonify({"ok": True, "deleted": deleted, "errors": errors})


@app.route("/api/websites/rename", methods=["POST"])
def api_websites_rename():
    data = request.get_json()
    filepath = data.get("path", "")
    new_name = secure_filename(data.get("name", ""))
    if not new_name:
        return jsonify({"error": "Invalid name"}), 400
    old_full = os.path.normpath(os.path.join(WWW_DIR, filepath))
    if not old_full.startswith(os.path.normpath(WWW_DIR)):
        return jsonify({"error": "Access denied"}), 403
    if not os.path.exists(old_full):
        return jsonify({"error": "Not found"}), 404
    new_full = os.path.join(os.path.dirname(old_full), new_name)
    if os.path.exists(new_full):
        return jsonify({"error": "Name already exists"}), 400
    os.rename(old_full, new_full)
    return jsonify({"ok": True})


@app.route("/api/websites/download/<path:filepath>")
def api_websites_download(filepath):
    full = os.path.normpath(os.path.join(WWW_DIR, filepath))
    if not full.startswith(os.path.normpath(WWW_DIR)):
        return "Access denied", 403
    if not os.path.isfile(full):
        return "Not found", 404
    directory = os.path.dirname(full)
    filename = os.path.basename(full)
    return send_from_directory(directory, filename, as_attachment=True)


# ──────────── Routes: Logs ────────────

@app.route("/api/logs/<name>")
def api_logs(name):
    allowed = {"http": "http.log", "panel": "panel.log"}
    if name not in allowed:
        return jsonify({"error": "Unknown log"}), 404
    logfile = os.path.join(LOGS_DIR, allowed[name])
    if not os.path.exists(logfile):
        return jsonify({"content": "(empty)"})
    with open(logfile) as f:
        lines = f.readlines()
    return jsonify({"content": "".join(lines[-100:])})


# ──────────── Routes: Settings ────────────

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(load_config())


@app.route("/api/settings", methods=["POST"])
def api_settings_save():
    data = request.get_json()
    config = load_config()
    if "hostname" in data:
        config["hostname"] = str(data["hostname"])[:50]
    if "password" in data and len(data["password"]) >= 4:
        config["password"] = data["password"]
        # Also update Termux password
        try:
            proc = subprocess.Popen(["passwd"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc.communicate(f"{data['password']}\n{data['password']}\n".encode())
        except Exception:
            pass
    save_config(config)
    return jsonify({"ok": True})


# ──────────── Routes: Tunnel / Remote Access ────────────

@app.route("/remote")
def remote_access():
    return render_template("remote.html")


@app.route("/api/tunnel")
def api_tunnel_status():
    running = is_service_running("cloudflared")
    url = get_tunnel_url() if running else None
    return jsonify({"running": running, "url": url})


@app.route("/api/tunnel/start", methods=["POST"])
def api_tunnel_start():
    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
    time.sleep(1)
    token = ""
    if os.path.exists(TUNNEL_TOKEN_FILE):
        with open(TUNNEL_TOKEN_FILE) as f:
            token = f.read().strip()
    if not token:
        return jsonify({"ok": False, "error": "No tunnel token configured"}), 400
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    resolv = os.path.join(prefix, "etc/resolv.conf")
    cacert = os.path.join(prefix, "etc/tls/cert.pem")
    with open(TUNNEL_LOG, "w") as log:
        subprocess.Popen(
            ["proot",
             "-b", f"{resolv}:/etc/resolv.conf",
             "-b", f"{cacert}:/etc/ssl/certs/ca-certificates.crt",
             "cloudflared", "tunnel", "--protocol", "http2", "--no-autoupdate",
             "run", "--token", token],
            stdout=log, stderr=log,
        )
    for _ in range(15):
        time.sleep(1)
        if is_service_running("cloudflared"):
            return jsonify({"ok": True, "msg": "Tunnel started", "url": PERMANENT_URL})
    return jsonify({"ok": True, "msg": "Tunnel starting...", "url": PERMANENT_URL})


@app.route("/api/tunnel/stop", methods=["POST"])
def api_tunnel_stop():
    subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
    return jsonify({"ok": True, "msg": "Tunnel stopped"})


# ──────────── Routes: Recycle Bin ────────────

@app.route("/trash")
def trash_page():
    return render_template("trash.html")


@app.route("/api/trash/list")
def api_trash_list():
    meta = _load_trash_meta()
    # Filter out entries whose trash file is missing
    valid = []
    for item in meta:
        trash_path = os.path.join(TRASH_DIR, item["id"])
        if os.path.exists(trash_path):
            valid.append(item)
    if len(valid) != len(meta):
        _save_trash_meta(valid)
    return jsonify({"items": valid})


@app.route("/api/trash/restore", methods=["POST"])
def api_trash_restore():
    data = request.get_json()
    trash_id = data.get("id", "")
    if not trash_id:
        return jsonify({"error": "Missing id"}), 400
    meta = _load_trash_meta()
    entry = next((m for m in meta if m["id"] == trash_id), None)
    if not entry:
        return jsonify({"error": "Not found in trash"}), 404
    trash_path = os.path.join(TRASH_DIR, trash_id)
    if not os.path.exists(trash_path):
        meta = [m for m in meta if m["id"] != trash_id]
        _save_trash_meta(meta)
        return jsonify({"error": "Trash file missing"}), 404
    base_dir = FILES_DIR if entry["section"] == "files" else WWW_DIR
    restore_path = os.path.normpath(os.path.join(base_dir, entry["original_path"]))
    if not restore_path.startswith(os.path.normpath(base_dir)):
        return jsonify({"error": "Invalid path"}), 403
    # Ensure parent directory exists
    os.makedirs(os.path.dirname(restore_path), exist_ok=True)
    # If something already exists at the target, rename with suffix
    if os.path.exists(restore_path):
        name, ext = os.path.splitext(restore_path)
        restore_path = f"{name}_restored_{int(time.time())}{ext}"
    shutil.move(trash_path, restore_path)
    meta = [m for m in meta if m["id"] != trash_id]
    _save_trash_meta(meta)
    return jsonify({"ok": True, "restored_to": entry["original_path"]})


@app.route("/api/trash/delete", methods=["POST"])
def api_trash_delete():
    data = request.get_json()
    trash_id = data.get("id", "")
    if not trash_id:
        return jsonify({"error": "Missing id"}), 400
    trash_path = os.path.join(TRASH_DIR, trash_id)
    if os.path.exists(trash_path):
        if os.path.isdir(trash_path):
            shutil.rmtree(trash_path)
        else:
            os.remove(trash_path)
    meta = _load_trash_meta()
    meta = [m for m in meta if m["id"] != trash_id]
    _save_trash_meta(meta)
    return jsonify({"ok": True})


@app.route("/api/trash/empty", methods=["POST"])
def api_trash_empty():
    meta = _load_trash_meta()
    for item in meta:
        trash_path = os.path.join(TRASH_DIR, item["id"])
        if os.path.exists(trash_path):
            if os.path.isdir(trash_path):
                shutil.rmtree(trash_path)
            else:
                os.remove(trash_path)
    _save_trash_meta([])
    return jsonify({"ok": True})


# ──────────── Public Site (no auth) ────────────

@app.route("/site/")
@app.route("/site")
def public_site_root():
    index = os.path.join(WWW_DIR, "index.html")
    if os.path.isfile(index):
        return send_from_directory(WWW_DIR, "index.html")
    return "No site deployed", 404


@app.route("/site/<path:filepath>")
def public_site(filepath):
    full = os.path.normpath(os.path.join(WWW_DIR, filepath))
    if not full.startswith(os.path.normpath(WWW_DIR)):
        return "Access denied", 403
    if os.path.isdir(full):
        index = os.path.join(full, "index.html")
        if os.path.isfile(index):
            return send_from_directory(full, "index.html")
        return "Not found", 404
    if not os.path.isfile(full):
        return "Not found", 404
    return send_from_directory(os.path.dirname(full), os.path.basename(full))


if __name__ == "__main__":
    config = load_config()
    print("=" * 50)
    print("  Phone VPS Control Panel")
    print("=" * 50)
    print(f"  URL: http://0.0.0.0:{config['panel_port']}")
    print(f"  SSH: port {config['ssh_port']}")
    print(f"  HTTP: port {config['http_port']}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=config["panel_port"], debug=False)
