"""
Self-healing deploy script for Phone VPS.
- Uploads panel files via SFTP
- Auto-fixes: ADB forwards, SSH access, stale processes, missing deps
- Restarts services and verifies everything is working
"""
import paramiko
import subprocess
import os
import sys
import time
import socket
import stat as stat_module

# ── Config: everything private comes from the environment - nothing secret lives in this file ──
def _env(name, default=""):
    return os.environ.get(name, default).strip()


SSH_HOST_ADB   = "127.0.0.1"                              # reached through `adb forward tcp:8022 tcp:8022`
SSH_HOST_WIFI  = _env("PHONE_SSH_HOST")                   # the phone's address on your Wi-Fi, e.g. 192.168.1.50
SSH_PORT       = int(_env("PHONE_SSH_PORT", "8022"))
SSH_USER       = _env("PHONE_SSH_USER")
SSH_PASS       = _env("PHONE_SSH_PASS")
ADB_SERIAL     = _env("PHONE_ADB_SERIAL")                 # serial from `adb devices`; empty = any connected device

LOCAL_PANEL    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel")
REMOTE_PANEL   = "/data/data/com.termux/files/home/panel"
REMOTE_VPS     = "/data/data/com.termux/files/home/vps"
REMOTE_BIN     = "/data/data/com.termux/files/usr/bin"

TUNNEL_TOKEN   = _env("CLOUDFLARE_TUNNEL_TOKEN")           # optional: from Cloudflare Zero Trust -> Tunnels
PERMANENT_URL  = _env("PANEL_PUBLIC_URL", "(no public URL configured)")

# ── Helpers ──
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_RED    = "\033[91m"
C_CYAN   = "\033[96m"
C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"

def ok(msg):   print(f"  {C_GREEN}[OK]{C_RESET} {msg}")
def warn(msg): print(f"  {C_YELLOW}[!!]{C_RESET} {msg}")
def fail(msg): print(f"  {C_RED}[FAIL]{C_RESET} {msg}")
def info(msg): print(f"  {C_CYAN}[>>]{C_RESET} {msg}")
def head(msg): print(f"\n{C_BOLD}{C_CYAN}{'='*50}\n  {msg}\n{'='*50}{C_RESET}")

def run_adb(args, timeout=15):
    """Run an ADB command, return (success, stdout)."""
    try:
        r = subprocess.run(["adb"] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)

def ssh_exec(ssh, cmd, timeout=30):
    """Execute SSH command, return (exit_code, stdout, stderr)."""
    try:
        si, so, se = ssh.exec_command(cmd, timeout=timeout)
        code = so.channel.recv_exit_status()
        return code, so.read().decode().strip(), se.read().decode().strip()
    except Exception as e:
        return -1, "", str(e)

def port_open(host, port, timeout=3):
    """Check if a TCP port is reachable."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════
#  Phase 1: Establish Connection
# ══════════════════════════════════════════════════
def connect_ssh():
    """Try multiple methods to get SSH connection. Returns (ssh, host_used) or dies."""
    head("Phase 1: Establishing Connection")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Method 1: Try existing ADB forward
    if port_open(SSH_HOST_ADB, SSH_PORT):
        try:
            ssh.connect(SSH_HOST_ADB, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
            ok(f"Connected via ADB forward ({SSH_HOST_ADB}:{SSH_PORT})")
            return ssh, SSH_HOST_ADB
        except Exception as e:
            warn(f"ADB port open but SSH failed: {e}")

    # Method 2: Try WiFi direct
    if SSH_HOST_WIFI and port_open(SSH_HOST_WIFI, SSH_PORT):
        try:
            ssh.connect(SSH_HOST_WIFI, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
            ok(f"Connected via WiFi ({SSH_HOST_WIFI}:{SSH_PORT})")
            return ssh, SSH_HOST_WIFI
        except Exception as e:
            warn(f"WiFi port open but SSH failed: {e}")

    # Method 3: Set up ADB forwards
    info("No SSH access. Trying ADB port forward...")
    succ, out = run_adb(["devices"])
    if (ADB_SERIAL or "\tdevice") not in out:
        fail("Phone not connected via USB (ADB). Connect USB cable and retry.")
        sys.exit(1)

    for local_port, remote_port in [(5000,5000),(8022,8022),(8080,8080)]:
        run_adb(["forward", f"tcp:{local_port}", f"tcp:{remote_port}"])
    info("ADB port forwards set (5000, 8022, 8080)")
    time.sleep(1)

    if not port_open(SSH_HOST_ADB, SSH_PORT):
        # Method 4: Start sshd via ADB shell
        warn("SSH port not responding. Starting sshd via ADB shell...")
        run_adb(["shell", "run-as", "com.termux", "files/usr/bin/bash", "-c",
                  "export PATH=/data/data/com.termux/files/usr/bin:$PATH; sshd"])
        time.sleep(2)

    if not port_open(SSH_HOST_ADB, SSH_PORT):
        fail("Cannot reach SSH even after ADB forward + sshd start. Is Termux running?")
        sys.exit(1)

    try:
        ssh.connect(SSH_HOST_ADB, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
        ok(f"Connected via ADB forward (after setup)")
        return ssh, SSH_HOST_ADB
    except Exception as e:
        fail(f"SSH connection failed: {e}")
        sys.exit(1)


# ══════════════════════════════════════════════════
#  Phase 2: Upload Files
# ══════════════════════════════════════════════════
def _sftp_listdir_r(sftp, remote_dir, base=""):
    """Recursively list all files in a remote directory (relative paths)."""
    files = []
    try:
        for entry in sftp.listdir_attr(remote_dir):
            rel = f"{base}/{entry.filename}" if base else entry.filename
            full = f"{remote_dir}/{entry.filename}"
            if stat_module.S_ISDIR(entry.st_mode):
                files.extend(_sftp_listdir_r(sftp, full, rel))
            else:
                files.append(rel)
    except Exception:
        pass
    return files


def _sftp_makedirs(sftp, remote_dir):
    """Recursively create remote directories (like os.makedirs)."""
    dirs_to_create = []
    current = remote_dir
    while True:
        try:
            sftp.stat(current)
            break  # exists
        except FileNotFoundError:
            dirs_to_create.append(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    for d in reversed(dirs_to_create):
        try:
            sftp.mkdir(d)
        except Exception:
            pass


def _sftp_rmtree(sftp, remote_dir):
    """Recursively remove a remote directory."""
    try:
        for entry in sftp.listdir_attr(remote_dir):
            full = f"{remote_dir}/{entry.filename}"
            if stat_module.S_ISDIR(entry.st_mode):
                _sftp_rmtree(sftp, full)
            else:
                sftp.remove(full)
        sftp.rmdir(remote_dir)
    except Exception:
        pass


def upload_files(ssh):
    head("Phase 2: Uploading Files (clean deploy)")
    sftp = ssh.open_sftp()

    # Ensure base directories exist
    for d in [REMOTE_PANEL, REMOTE_VPS,
              f"{REMOTE_VPS}/www", f"{REMOTE_VPS}/files",
              f"{REMOTE_VPS}/logs", f"{REMOTE_VPS}/config"]:
        _sftp_makedirs(sftp, d)

    # Collect local panel files (relative paths)
    local_files = set()
    for root, _dirs, files in os.walk(LOCAL_PANEL):
        for fname in files:
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, LOCAL_PANEL).replace("\\", "/")
            local_files.add(rel)

    # Find and remove stale remote files (exist on phone but not locally)
    remote_files = _sftp_listdir_r(sftp, REMOTE_PANEL)
    stale = [f for f in remote_files if f not in local_files and not f.startswith("__pycache__")]
    if stale:
        info(f"Removing {len(stale)} stale file(s)...")
        for rel in stale:
            remote_path = f"{REMOTE_PANEL}/{rel}"
            try:
                sftp.remove(remote_path)
                print(f"    [DEL] {rel}")
            except Exception:
                pass
        # Remove empty directories left behind (recursively up to REMOTE_PANEL)
        cleaned_dirs = set()
        for rel in sorted(stale, key=len, reverse=True):
            remote_dir = os.path.dirname(f"{REMOTE_PANEL}/{rel}")
            while remote_dir != REMOTE_PANEL and remote_dir not in cleaned_dirs:
                cleaned_dirs.add(remote_dir)
                try:
                    if not sftp.listdir(remote_dir):
                        sftp.rmdir(remote_dir)
                        print(f"    [RMDIR] {os.path.relpath(remote_dir, REMOTE_PANEL)}")
                    else:
                        break  # directory not empty, stop going up
                except Exception:
                    break
                remote_dir = os.path.dirname(remote_dir)
        ok(f"Removed {len(stale)} stale file(s)")
    else:
        ok("No stale files to clean")

    # Upload panel files (skip unchanged files based on size)
    count = 0
    skipped = 0
    for root, _dirs, files in os.walk(LOCAL_PANEL):
        for fname in files:
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, LOCAL_PANEL).replace("\\", "/")
            remote_path = f"{REMOTE_PANEL}/{rel}"
            remote_dir = os.path.dirname(remote_path)
            _sftp_makedirs(sftp, remote_dir)

            # Skip upload if remote file exists with same size (except scripts — always upload)
            local_size = os.path.getsize(local_path)
            is_code = rel.endswith(('.py', '.sh', '.html'))
            try:
                remote_stat = sftp.stat(remote_path)
                if remote_stat.st_size == local_size and not is_code:
                    skipped += 1
                    continue
            except FileNotFoundError:
                pass

            sftp.put(local_path, remote_path)
            count += 1
            print(f"    [UP] {rel}")

    # Make scripts executable
    for script in ["start.sh", "stop.sh", "watchdog.sh"]:
        path = f"{REMOTE_PANEL}/{script}"
        try:
            sftp.chmod(path, 0o755)
        except Exception:
            pass

    # Write the Cloudflare tunnel token (only when one was provided)
    if TUNNEL_TOKEN:
        token_path = f"{REMOTE_VPS}/config/tunnel_token.txt"
        with sftp.open(token_path, "w") as f:
            f.write(TUNNEL_TOKEN)

    sftp.close()
    msg = f"Uploaded {count} file(s)"
    if skipped:
        msg += f", skipped {skipped} unchanged"
    msg += " + tunnel token" if TUNNEL_TOKEN else " (no tunnel token set)"
    msg += " (clean deploy)"
    ok(msg)


# ══════════════════════════════════════════════════
#  Phase 3: Fix & Clean
# ══════════════════════════════════════════════════
def fix_and_clean(ssh):
    head("Phase 3: Fixing Issues")

    # Clean __pycache__ to prevent stale bytecode
    info("Cleaning __pycache__...")
    ssh_exec(ssh, f"find {REMOTE_PANEL} -type d -name '__pycache__' -exec rm -rf {{}} + 2>/dev/null")
    ok("__pycache__ cleaned")

    # Kill old Quick Tunnel for panel (port 5000 only, not other services)
    code, out, _ = ssh_exec(ssh, "pgrep -f 'cloudflared tunnel --url http://localhost:5000' 2>/dev/null")
    if out.strip():
        info("Killing old Quick Tunnel for panel (leftover)...")
        ssh_exec(ssh, "pkill -f 'cloudflared tunnel --url http://localhost:5000'")
        time.sleep(1)
        ok("Old Quick Tunnel killed")
    else:
        ok("No stale panel Quick Tunnel")

    # Kill old app.py references (renamed to web.py)
    ssh_exec(ssh, "pkill -f 'python3 app.py' 2>/dev/null; rm -f ~/panel/app.py 2>/dev/null")

    # Ensure cloudflared is installed
    code, out, _ = ssh_exec(ssh, f"ls {REMOTE_BIN}/cloudflared 2>/dev/null")
    if not out.strip():
        info("Installing cloudflared...")
        ssh_exec(ssh, f"curl -sL -o {REMOTE_BIN}/cloudflared "
                 "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 "
                 f"&& chmod +x {REMOTE_BIN}/cloudflared", timeout=120)
        code, ver, _ = ssh_exec(ssh, f"{REMOTE_BIN}/cloudflared --version 2>&1")
        if ver:
            ok(f"Installed cloudflared: {ver}")
        else:
            warn("cloudflared install may have failed")
    else:
        code, ver, _ = ssh_exec(ssh, f"{REMOTE_BIN}/cloudflared --version 2>&1")
        ok(f"cloudflared present: {ver}")

    # Ensure proot is installed (needed for cloudflared DNS/TLS)
    code, out, _ = ssh_exec(ssh, f"ls {REMOTE_BIN}/proot 2>/dev/null")
    if not out.strip():
        info("Installing proot (needed for cloudflared)...")
        ssh_exec(ssh, "pkg install -y proot 2>/dev/null || apt install -y proot 2>/dev/null", timeout=60)

    # Setup boot script
    ssh_exec(ssh, (
        "mkdir -p ~/.termux/boot && "
        "cat > ~/.termux/boot/start-vps.sh << 'BOOTEOF'\n"
        "#!/data/data/com.termux/files/usr/bin/bash\n"
        "sleep 10\n"
        "cd ~/panel && bash start.sh\n"
        "BOOTEOF\n"
        "chmod +x ~/.termux/boot/start-vps.sh"
    ))
    ok("Boot script updated")


# ══════════════════════════════════════════════════
#  Phase 4: Restart Services
# ══════════════════════════════════════════════════
def restart_services(ssh):
    head("Phase 4: Restarting Services")

    # Stop old services (keep named tunnel alive if possible)
    info("Stopping old services...")
    ssh_exec(ssh, (
        "pkill -f 'watchdog.sh' 2>/dev/null; "
        "pkill -9 -f 'python3 web.py' 2>/dev/null; "
        "pkill -f 'http.server 8080' 2>/dev/null; "
        "sleep 1"
    ))

    # Clean __pycache__ AFTER kill to prevent stale bytecode on restart
    ssh_exec(ssh, f"find {REMOTE_PANEL} -type d -name '__pycache__' -exec rm -rf {{}} + 2>/dev/null")

    # Start everything via start.sh
    info("Starting services via start.sh...")
    ssh_exec(ssh, (
        "export PATH=/data/data/com.termux/files/usr/bin:$PATH; "
        "export HOME=/data/data/com.termux/files/home; "
        "cd ~/panel && nohup bash start.sh > /dev/null 2>&1 &"
    ))

    # Wait for services to boot
    info("Waiting for services to start (8s)...")
    time.sleep(8)


# ══════════════════════════════════════════════════
#  Phase 5: Verify Everything
# ══════════════════════════════════════════════════
def verify(ssh, host):
    head("Phase 5: Verification")
    all_ok = True

    # 1. Flask panel
    code, out, _ = ssh_exec(ssh, "pgrep -f 'python3 web.py' >/dev/null 2>&1 && echo UP || echo DOWN")
    if "UP" in out:
        ok("Flask panel (web.py) running")
    else:
        fail("Flask panel NOT running")
        info("Attempting manual start...")
        ssh_exec(ssh, (
            "export PATH=/data/data/com.termux/files/usr/bin:$PATH; "
            "export HOME=/data/data/com.termux/files/home; "
            "cd ~/panel && nohup python3 web.py >> ~/vps/logs/panel.log 2>&1 &"
        ))
        time.sleep(3)
        code, out, _ = ssh_exec(ssh, "pgrep -f 'python3 web.py' >/dev/null 2>&1 && echo UP || echo DOWN")
        if "UP" in out:
            ok("Flask panel started (manual recovery)")
        else:
            fail("Flask panel STILL not running!")
            # Check for errors
            code, out, _ = ssh_exec(ssh, "tail -10 ~/vps/logs/panel.log 2>/dev/null")
            if out:
                warn(f"Log tail:\n{out}")
            all_ok = False

    # 2. HTTP server
    code, out, _ = ssh_exec(ssh, "pgrep -f 'http.server 8080' >/dev/null 2>&1 && echo UP || echo DOWN")
    if "UP" in out:
        ok("HTTP server (port 8080) running")
    else:
        warn("HTTP server not running, starting...")
        ssh_exec(ssh, (
            "export PATH=/data/data/com.termux/files/usr/bin:$PATH; "
            "export HOME=/data/data/com.termux/files/home; "
            "cd ~/vps/www && nohup python3 -m http.server 8080 >> ~/vps/logs/http.log 2>&1 &"
        ))
        time.sleep(2)
        code, out, _ = ssh_exec(ssh, "pgrep -f 'http.server 8080' >/dev/null 2>&1 && echo UP || echo DOWN")
        if "UP" in out:
            ok("HTTP server started (recovery)")
        else:
            warn("HTTP server failed to start")

    # 3. SSH
    code, out, _ = ssh_exec(ssh, "pgrep -f sshd >/dev/null 2>&1 && echo UP || echo DOWN")
    if "UP" in out:
        ok("SSH server running")
    else:
        ssh_exec(ssh, "sshd")
        ok("SSH server started")

    # 4. Named tunnel
    code, out, _ = ssh_exec(ssh, "pgrep -f 'cloudflared tunnel.*run.*--token' >/dev/null 2>&1 && echo UP || echo DOWN")
    if "UP" in out:
        ok("Named tunnel running")
    else:
        warn("Named tunnel not running, starting...")
        ssh_exec(ssh, (
            "export PATH=/data/data/com.termux/files/usr/bin:$PATH; "
            "export HOME=/data/data/com.termux/files/home; "
            "TUNNEL_TOKEN=$(cat ~/vps/config/tunnel_token.txt 2>/dev/null); "
            "[ -n \"$TUNNEL_TOKEN\" ] && nohup proot "
            "-b $PREFIX/etc/resolv.conf:/etc/resolv.conf "
            "-b $PREFIX/etc/tls/cert.pem:/etc/ssl/certs/ca-certificates.crt "
            "cloudflared tunnel --protocol http2 --no-autoupdate run --token \"$TUNNEL_TOKEN\" "
            ">> ~/vps/logs/tunnel.log 2>&1 &"
        ))
        time.sleep(5)
        code, out, _ = ssh_exec(ssh, "pgrep -f 'cloudflared tunnel.*run.*--token' >/dev/null 2>&1 && echo UP || echo DOWN")
        if "UP" in out:
            ok("Named tunnel started (recovery)")
        else:
            fail("Named tunnel FAILED to start")
            code, out, _ = ssh_exec(ssh, "tail -5 ~/vps/logs/tunnel.log 2>/dev/null")
            if out:
                warn(f"Tunnel log:\n{out}")
            all_ok = False

    # 5. Verify no old Quick Tunnel for panel (port 5000)
    code, out, _ = ssh_exec(ssh, "pgrep -f 'cloudflared tunnel --url http://localhost:5000' >/dev/null 2>&1 && echo FOUND || echo CLEAN")
    if "CLEAN" in out:
        ok("No stale panel Quick Tunnel")
    else:
        ssh_exec(ssh, "pkill -f 'cloudflared tunnel --url http://localhost:5000'")
        ok("Killed stale panel Quick Tunnel")

    # 6. Watchdog
    code, out, _ = ssh_exec(ssh, "pgrep -f 'watchdog.sh' >/dev/null 2>&1 && echo UP || echo DOWN")
    if "UP" in out:
        ok("Watchdog daemon running")
    else:
        warn("Watchdog not running, starting...")
        ssh_exec(ssh, (
            "export PATH=/data/data/com.termux/files/usr/bin:$PATH; "
            "export HOME=/data/data/com.termux/files/home; "
            "cd ~/panel && nohup bash watchdog.sh >> ~/vps/logs/watchdog.log 2>&1 &"
        ))
        time.sleep(2)
        code, out, _ = ssh_exec(ssh, "pgrep -f 'watchdog.sh' >/dev/null 2>&1 && echo UP || echo DOWN")
        if "UP" in out:
            ok("Watchdog started (recovery)")
        else:
            warn("Watchdog failed to start")

    # 7. HTTP check on panel
    try:
        import urllib.request
        url = f"http://{host}:5000/"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                ok(f"Panel HTTP 200 at {url}")
            else:
                warn(f"Panel returned HTTP {resp.status}")
    except Exception as e:
        warn(f"Panel HTTP check failed: {e}")

    return all_ok


# ══════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════
def deploy():
    if not (SSH_USER and SSH_PASS):
        sys.exit("Set PHONE_SSH_USER and PHONE_SSH_PASS (see README) before deploying.")
    print(f"\n{C_BOLD}Phone VPS - Self-Healing Deploy{C_RESET}")
    print(f"Target: {PERMANENT_URL}\n")

    ssh, host = connect_ssh()
    upload_files(ssh)
    fix_and_clean(ssh)
    restart_services(ssh)
    all_ok = verify(ssh, host)

    # Final summary
    code, procs, _ = ssh_exec(ssh, "pgrep -a python3 2>/dev/null; pgrep -a cloudflared 2>/dev/null; pgrep -a watchdog 2>/dev/null")

    head("Deploy Complete!" if all_ok else "Deploy Complete (with warnings)")
    # Get actual local IP
    _, local_ip, _ = ssh_exec(ssh, "ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K\\S+'")
    local_ip = local_ip.strip() or host
    print(f"  {C_CYAN}Local:{C_RESET}     http://{local_ip}:5000")
    print(f"  {C_CYAN}Public:{C_RESET}    {PERMANENT_URL}")
    print(f"  {C_CYAN}Panel login:{C_RESET} the password in ~/vps/config/panel.json (printed once in ~/vps/logs/panel.log)")
    print(f"\n  {C_BOLD}Running processes:{C_RESET}")
    for line in procs.split("\n"):
        if line.strip():
            print(f"    {line.strip()}")
    print()

    if all_ok:
        print(f"  {C_GREEN}{C_BOLD}ALL SERVICES HEALTHY{C_RESET}\n")
    else:
        print(f"  {C_YELLOW}{C_BOLD}Some issues detected - check warnings above{C_RESET}\n")

    ssh.close()


if __name__ == "__main__":
    deploy()
