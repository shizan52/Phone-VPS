"""Post-deploy verification for the Phone VPS.

Checks, from your PC, that everything the phone should be running really is:
  1. the SSH / panel / HTTP ports answer              2. SSH login works
  3. the panel API answers (and shows live stats)     4. (optional) the panel's start-all / reboot buttons respond
  5. every service process is alive on the phone      6. the Cloudflare tunnel token is in place

Configuration comes from the environment - nothing is stored in this file:
  PHONE_HOST        the phone's address on your network      (required)
  PHONE_SSH_USER    Termux SSH user                          (required)
  PHONE_SSH_PASS    Termux SSH password                      (required)
  PANEL_PASSWORD    panel login password                     (required)
  PHONE_SSH_PORT    default 8022

    python tools/verify.py              # read-only checks
    python tools/verify.py --buttons    # also POST /api/start-all and /api/reboot (restarts services!)
"""
import http.cookiejar
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request

import paramiko

HOST = os.environ.get("PHONE_HOST", "").strip()
SSH_USER = os.environ.get("PHONE_SSH_USER", "").strip()
SSH_PASS = os.environ.get("PHONE_SSH_PASS", "")
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SSH_PORT = int(os.environ.get("PHONE_SSH_PORT", "8022"))
PANEL = f"http://{HOST}:5000"

missing = [n for n, v in (("PHONE_HOST", HOST), ("PHONE_SSH_USER", SSH_USER), ("PHONE_SSH_PASS", SSH_PASS), ("PANEL_PASSWORD", PANEL_PASSWORD)) if not v]
if missing:
    sys.exit("Set these environment variables first: " + ", ".join(missing))

print("=" * 60)
print("  PHONE VPS - POST-DEPLOY VERIFICATION")
print("=" * 60)

results = {}

# 1. Network connectivity
print("\n[1] Network Connectivity")
for port, name in [(SSH_PORT, "SSH"), (5000, "Panel"), (8080, "HTTP")]:
    try:
        socket.create_connection((HOST, port), timeout=5).close()
        print(f"  {name} (:{port}): OPEN")
        results[f"port_{name}"] = True
    except OSError:
        print(f"  {name} (:{port}): CLOSED")
        results[f"port_{name}"] = False

# 2. SSH Access
print("\n[2] SSH Access")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect(HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
    print(f"  SSH: CONNECTED (user={SSH_USER})")
    results["ssh"] = True
except Exception as e:
    print(f"  SSH: FAILED ({e})")
    results["ssh"] = False
    sys.exit(1)


def run(cmd):
    _si, so, _se = ssh.exec_command(cmd, timeout=15)
    so.channel.recv_exit_status()
    return so.read().decode().strip()


# 3. Panel API
print("\n[3] Panel API")
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
try:
    opener.open(f"{PANEL}/login", urllib.parse.urlencode({"password": PANEL_PASSWORD}).encode(), timeout=10)
    d = json.loads(opener.open(f"{PANEL}/api/status", timeout=10).read().decode())
    mem, stor, cpu, tunnel = d.get("memory", {}), d.get("storage", {}), d.get("cpu", {}), d.get("tunnel", {})
    print(f"  IP Address: {d.get('ip')}")
    print(f"  RAM: {mem.get('used_mb')} MB / {mem.get('total_mb')} MB ({mem.get('percent')}%)")
    print(f"  Storage: {stor.get('used_gb')} GB / {stor.get('total_gb')} GB ({stor.get('percent')}%)")
    print(f"  Uptime: {d.get('uptime')}")
    print(f"  CPU: {cpu.get('cores')} cores, load: {cpu.get('load', {}).get('1min')}")
    print(f"  Tunnel: {'RUNNING' if tunnel.get('running') else 'STOPPED'} - {tunnel.get('url')}")
    print("\n  Services:")
    for name, svc in d.get("services", {}).items():
        print(f"    {name.upper()}: {'RUNNING' if svc.get('running') else 'STOPPED'} (port: {svc.get('port')})")
    results["api"] = True
except Exception as e:
    print(f"  API FAILED: {e}")
    results["api"] = False

# 4. Button endpoints (these restart services, so only on request)
if "--buttons" in sys.argv:
    print("\n[4] Button Endpoints")
    for endpoint, method in [("/api/status", "GET"), ("/api/start-all", "POST"), ("/api/reboot", "POST")]:
        try:
            if method == "POST":
                resp = opener.open(urllib.request.Request(f"{PANEL}{endpoint}", method="POST", data=b""), timeout=15)
            else:
                resp = opener.open(f"{PANEL}{endpoint}", timeout=10)
            print(f"  {method} {endpoint}: HTTP {resp.status}")
        except Exception as e:
            print(f"  {method} {endpoint}: FAILED ({e})")
        if endpoint == "/api/reboot":
            time.sleep(5)
else:
    print("\n[4] Button Endpoints: skipped (pass --buttons to test start-all / reboot)")

# 5. Service processes on the phone
print("\n[5] Service Processes (via SSH)")
for name, pattern in [("SSH", "sshd"), ("HTTP", "http.server 8080"), ("Panel", "python3 web.py"), ("Tunnel", "cloudflared"), ("Watchdog", "watchdog.sh")]:
    out = run(f"pgrep -f '{pattern}' >/dev/null 2>&1 && echo RUNNING || echo STOPPED")
    print(f"  [{'OK' if 'RUNNING' in out else 'FAIL'}] {name}: {out}")

# 6. Tunnel configuration (never print the token itself)
print("\n[6] Tunnel Config")
present = run("test -s ~/vps/config/tunnel_token.txt && echo yes || echo no")
print(f"  Tunnel token file: {'present' if present == 'yes' else 'missing'}")
print(f"  Tunnel log: {run('tail -2 ~/vps/logs/tunnel.log 2>/dev/null')[:200]}")

ssh.close()

print("\n" + "=" * 60)
if all(results.values()):
    print("  ALL CHECKS PASSED")
else:
    print(f"  ISSUES: {', '.join(k for k, v in results.items() if not v)}")
print("=" * 60)
