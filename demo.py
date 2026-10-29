"""Phone VPS demo - the real control panel, running on your PC with made-up phone data.

No phone, no Termux and no Cloudflare account needed: the panel runs against a throw-away folder with sample photos,
documents and a recycle bin, and reports pretend phone statistics. Buttons that would start or stop real services only
answer "demo mode". Nothing outside the temporary folder is touched.

    pip install flask
    python demo.py                # then open http://127.0.0.1:5055  -  password: demo
    python demo.py --port 8000
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5055

# web.py keeps everything under ~/vps - point "home" at a temporary folder BEFORE it is imported.
HOME = Path(tempfile.mkdtemp(prefix="phonevps-demo-"))
os.environ["HOME"] = os.environ["USERPROFILE"] = str(HOME)
os.environ["PANEL_PASSWORD"] = "demo"
os.environ["PANEL_PUBLIC_URL"] = "https://vps.example.com"

VPS = HOME / "vps"
DAY = 86400


def touch(path, days_ago, data=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    t = time.time() - days_ago * DAY
    os.utime(path, (t, t))


def build_sample_data():
    photos = sorted((ROOT / "docs" / "demo-assets").glob("*.png"))
    ages = [2, 2, 2, 2, 40, 40, 40, 40]                        # two photo days in two different months, so the gallery shows its grouping
    for p, age in zip(photos, ages):
        touch(VPS / "files" / f"{p.stem}.png", age, p.read_bytes())
    touch(VPS / "files" / "notes.txt", 2, b"Phone VPS - things to remember\n- keep it plugged in\n- check the watchdog log on Sundays\n")
    touch(VPS / "files" / "todo.md", 40, b"# TODO\n- [x] named tunnel\n- [x] recycle bin\n- [ ] backups to a second phone\n")
    touch(VPS / "files" / "report-2026.pdf", 2, b"%PDF-1.4\n% placeholder for the demo\n")
    touch(VPS / "files" / "old-draft.txt", 40, b"an old draft that is about to be deleted\n")
    touch(VPS / "files" / "Documents" / "cv.pdf", 70, b"%PDF-1.4\n")
    touch(VPS / "files" / "Backups" / "panel-config.json", 8, b"{}\n")
    touch(VPS / "files" / "Private" / "secret-plans.txt", 15, b"nothing to see here\n")
    # a locked folder (password: demo) so the lock screen can be seen
    pw = "demo"
    (VPS / "config").mkdir(parents=True, exist_ok=True)
    (VPS / "config" / "locks.json").write_text(
        json.dumps({"files:Private": {"hash": hashlib.sha256(pw.encode()).hexdigest(), "pw": pw}}), encoding="utf-8")
    # the public website served from ~/vps/www
    touch(VPS / "www" / "index.html", 6, b"<!doctype html><title>My phone-hosted site</title><h1>Hello from an old phone</h1>\n")
    touch(VPS / "www" / "css" / "style.css", 6, b"body{font-family:sans-serif}\n")
    for name, text in {"panel.log": "[panel] first start: created panel.json\n", "tunnel.log": "INF Registered tunnel connection connIndex=0 protocol=http2\n",
                       "watchdog.log": "[NET] Internet is BACK online\n[RESTART] Named tunnel started\n"}.items():
        touch(VPS / "logs" / name, 0, text.encode())


build_sample_data()
sys.path.insert(0, str(ROOT / "panel"))
import web  # noqa: E402  (must come after the environment is prepared)

# two items already in the recycle bin
for rel in ("old-draft.txt",):
    web._move_to_trash(rel, "files")
touch(VPS / "www" / "old-page.html", 2, b"<h1>old</h1>")
web._move_to_trash("old-page.html", "websites")


def fake_status():
    cfg = web.load_config()
    svc = lambda port, pid: {"running": True, "port": port, "pid": str(pid)}  # noqa: E731
    return {
        "hostname": cfg["hostname"], "ip": "192.168.1.50", "os": "Android 12 / Termux", "python": "3.13.1",
        "cpu": {"cores": 8, "load": {"1min": 0.82, "5min": 0.64, "15min": 0.51}},
        "memory": {"total_mb": 7664, "available_mb": 4310, "used_mb": 3354, "percent": 43.8},
        "storage": {"total_gb": 103.9, "used_gb": 9.8, "free_gb": 94.1, "percent": 9.4},
        "uptime": "12 days, 4:31:07",
        "services": {"ssh": svc(8022, 2214), "http": svc(8080, 2231), "panel": svc(cfg["panel_port"], 2260),
                     "tunnel": svc("-", 2302), "watchdog": svc("-", 2188)},
        "ssh_port": cfg["ssh_port"], "ssh_user": "demo", "ssh_password": "demo", "status": "online",
        "tunnel": {"running": True, "url": web.PERMANENT_URL},
    }


web.get_all_status = fake_status
web.is_service_running = lambda name: True
web.get_tunnel_url = lambda: web.PERMANENT_URL


@web.app.before_request
def demo_guard():
    """In demo mode nothing may start, stop or reconfigure a real service."""
    p = web.request.path
    if web.request.method == "POST" and (p.startswith("/api/service/") or p in ("/api/start-all", "/api/stop-all", "/api/reboot", "/api/settings")
                                        or p.startswith("/api/tunnel/")):
        return web.jsonify({"ok": True, "msg": "demo mode - nothing was started, stopped or changed"})
    return None


if __name__ == "__main__":
    print(f"\n  Phone VPS demo  ->  http://127.0.0.1:{PORT}   (password: demo)\n  sample data lives in {HOME} and is deleted when you stop it\n")
    try:
        web.app.run(host="127.0.0.1", port=PORT, debug=False)
    finally:
        shutil.rmtree(HOME, ignore_errors=True)
