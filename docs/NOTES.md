# Phone VPS - design notes & changelog

> How the project is put together and why, written while building it. Hostnames, passwords, tokens and device
> identifiers are placeholders (`vps.example.com`, `<your-password>`, ...); see the README for how to configure the real ones.

## Device Information

| Field | Value |
|-------|-------|
| Device | Sony Xperia 5 II (SOG02) - its screen has a green line, so the whole setup is done over ADB / SSH |
| Processor | Snapdragon 865 (Kona), 8 cores, AArch64 |
| RAM | 7664 MB (~7.5 GB) |
| Storage | 103.9 GB total, ~94 GB free |
| Android | 12 (SDK 31) |
| Kernel | Linux 4.19.157 aarch64 |
| Termux Python | 3.13.12 |
| Local Network IP | 192.168.1.x (DHCP - may change) |

## Services

| Service | Port | Description |
|---------|------|-------------|
| Control Panel | 5000 | Flask web UI for managing VPS (password protected) |
| SSH | 8022 | Termux SSH server (password: <your-password>) |
| HTTP | 8080 | Python http.server for website hosting |
| Cloudflare Tunnel | - | Named tunnel with permanent URL via Cloudflare Zero Trust |
| Watchdog Daemon | - | Auto-restarts crashed services & tunnel on internet recovery (visible in dashboard services list) |

## ADB Port Forwards (only for initial setup via USB)

```
adb forward tcp:5000 tcp:5000    # Control Panel
adb forward tcp:8022 tcp:8022    # SSH
adb forward tcp:8080 tcp:8080    # HTTP Website
```

> **Note**: ADB forwards are NOT needed for normal operation. The phone runs autonomously via WiFi + Cloudflare Tunnel.

## Access Points

### Local Access (same WiFi / USB)
- **Control Panel**: http://127.0.0.1:5000 (via ADB) or http://192.168.1.x:5000 (via WiFi)
- **Website**: http://127.0.0.1:8080 (via ADB) or http://192.168.1.x:8080 (via WiFi)
- **SSH**: `ssh -4 -p 8022 localhost` (password: <your-password>)

### Remote Access (any device, any network, anywhere)
- **Permanent URL**: https://vps.example.com
- **How**: Cloudflare Named Tunnel (Zero Trust) routes `vps.example.com` to the phone's Flask panel.
- **No port forwarding or static IP needed** — works behind any NAT/firewall.
- URL is **permanent** — never changes, even after tunnel restart or phone reboot.
- Login with password `<your-password>`.

### Managing the Tunnel
- **From the panel**: Go to "Remote Access" page → Start/Stop Tunnel, see current URL.
- **From CLI**: `bash ~/panel/start.sh` auto-starts the tunnel if cloudflared is installed.
- **Note**: Quick tunnel URLs change on restart. Named tunnel URL is permanent: https://vps.example.com

## File Structure (PC - phone-vps\)

```
phone-vps\
  deploy.py             # Self-healing deploy: SFTP upload, auto-fix ADB/SSH, kill stale tunnels, verify services
  context.md            # This file - all context documentation
  _final_check.py       # Final verification script
  terminal.txt          # Terminal session log
  _archive/
    app.py              # [ARCHIVED] Tkinter desktop VPS Manager (no longer used)
  panel/
    web.py              # Flask control panel (with auth + tunnel + file locking)
    start.sh            # Start all services (SSH, HTTP, Panel, Tunnel, Watchdog)
    stop.sh             # Stop all services
    watchdog.sh         # Background daemon: auto-restarts services + tunnel
    templates/
      base.html         # Base layout (dark theme, sidebar with 5 nav items)
      dashboard.html    # Dashboard with stats + tunnel URL display
      files.html        # Google Photos-style file gallery (date-grouped grid, lightbox, upload progress with speed/ETA)
      login.html        # Login page (3D rounded profile image, mobile-responsive)
      remote.html       # Remote Access page (tunnel controls)
      trash.html        # Recycle Bin page (restore/permanent delete trashed items)
      asset/            # Static assets (profile.jpg served via /asset/ route without auth)
```

## File Structure (Phone - Termux)

```
~/panel/
  web.py                # Control panel Flask app (auth + tunnel + file locking)
  start.sh              # Service startup script (with tunnel + wake lock + watchdog)
  stop.sh               # Service shutdown script
  watchdog.sh           # Background daemon: checks every 30s, restarts crashed services
  templates/            # HTML templates (login, dashboard, files, remote)

~/vps/
  www/                  # Website root (served by HTTP on port 8080)
  files/                # File storage (documents, uploads)
  .trash/               # Recycle bin (deleted files moved here with metadata in .meta.json)
  logs/                 # Service logs (panel.log, http.log, tunnel.log, watchdog.log, boot.log)
  config/
    panel.json          # Panel configuration (includes secret_key)
    tunnel_token.txt      # Cloudflare named tunnel token (permanent URL)
    locks.json          # File/folder lock passwords ({hash, pw} dict format)

~/.termux/boot/
  start-vps.sh          # Auto-start script (requires Termux:Boot app)
```

## Control Panel Features

### Authentication
- Login required to access all pages and APIs
- Password-based authentication (password: <your-password>)
- Session persists for 7 days via secure cookie
- Logout button in sidebar

### Dashboard
- System status: IP, Memory, CPU cores, OS, Uptime
- RAM usage bar (live %)
- Storage usage bar (live %)
- SSH credentials display with copy button
- **Tunnel URL** display (when active) with copy button
- Service status: SSH, HTTP, Panel, Tunnel, Watchdog (with start/stop controls)
- Start/Stop/Reboot all services buttons (Stop also stops watchdog; Reboot restarts watchdog)
- `/api/stop-all` endpoint stops watchdog+tunnel+http+ssh (panel keeps running)
- `/api/start-all` starts any stopped services including watchdog
- Auto-refresh every 10 seconds

### File Manager (/files)
- Browse ~/vps/files/ directory
- **Google Photos-style gallery view** with justified photo grid (pure black background, 2px gaps)
- Date-grouped display: files sorted by **month** (e.g., "March 2026") with **day sub-headers** (e.g., "Mon, Mar 30, 2026")
- Featured items: first day group per month shows larger 200px thumbnails with date overlay
- Image thumbnails via `/api/files/raw/` endpoint (lazy loaded, object-fit cover)
- Video thumbnails with play button overlay (loads first frame via `<video preload="metadata">`)
- Audio, text, PDF, archive files shown as icon cards
- **Lock password prompt**: clicking a locked file/folder shows a password modal; correct password unlocks for the current page visit only (per-visit, not session-based)
- Password is sent via `X-Lock-Password` header (fetch) or `?lock_pw=` query param (media src)
- JS stores passwords in `_lockPasswords` memory — cleared on page reload, so every visit requires re-entering the password
- Locked files show a 🔒 card instead of loading thumbnails (avoids 403 errors)
- Locked folders show a lock overlay with unlock button; navigating into a locked folder prompts for password
- **Lightbox preview**: click any file to open full-screen viewer with left/right navigation (arrow keys + buttons)
  - Images: full resolution display
  - Videos: autoplay with controls
  - Audio: embedded player with file name
  - Text files: monospace code viewer (up to 100KB)
  - PDF: embedded iframe viewer
- Upload files with **detailed progress tracking**:
  - Per-file progress bars with percentage and checkmark on completion
  - Overall progress bar with total bytes uploaded / total size
  - Real-time **upload speed** (MB/s) with moving average
  - **ETA countdown** (seconds/minutes/hours remaining)
  - File count display with total upload size
  - Drag & drop anywhere on gallery to upload
- **Right-click context menu**: Open, Preview, Download, Rename, Delete
- Grid/List view toggle (persisted in localStorage)
- Folder navigation with breadcrumb and folder chips (dark tiles showing name + modified date)
- Create new folders
- Delete files/folders with confirmation
- Download files
- Breadcrumb navigation

### Website Space (/websites)
- Browse ~/vps/www/ directory (HTTP server root)
- **Same Google Photos-style gallery** as File Manager (date-grouped, lightbox, upload progress, context menu)
- Upload website files (HTML, CSS, JS, images)
- Create subdirectories for multiple sites
- HTTP server status & start/stop control
- Same upload/delete/download features as file manager

### Recycle Bin (/trash)
- All file/folder deletions (from File Manager and Website Space) go to trash instead of permanent delete
- Trash stored at `~/vps/.trash/` with metadata in `.meta.json`
- Each trashed item gets a unique ID (`timestamp_uuid8`) — original path and section recorded
- **Restore**: moves item back to original location; if conflict, appends `_restored_timestamp`
- **Permanent Delete**: removes item from trash forever
- **Empty Trash**: permanently deletes all trashed items
- Sidebar shows 🗑️ Recycle Bin link
- Trash page shows item name, section tag (files/websites), original path, size, delete timestamp
- Confirmation modal for permanent delete and empty trash actions

### Remote Access (/remote)
- Cloudflare Tunnel status with Start/Stop controls
- Public tunnel URL display with copy button
- Connection info (web panel URL, SSH command)
- Login credentials reference
- How-it-works explanation

### File/Folder Locking (web.py)
- Any file or folder can be password-locked via the web panel API
- Locks stored in `~/vps/config/locks.json` as `{"hash": "sha256...", "pw": "plaintext"}` (new dict format)
- Backward-compatible with old string-only hash format
- Locked items show a lock icon (🔒) in the web file manager
- Accessing locked files/folders requires entering the lock password
- Per-visit unlock: password required every time the page is loaded (no session persistence)
- Backend checks `X-Lock-Password` header or `lock_pw` query parameter against stored hash
- Parent lock inheritance: locking a folder locks all children
- Lock/Unlock API endpoints: `/api/lock`, `/api/unlock`, `/api/lock/remove`, `/api/locks/list`
- `/api/locks/list` returns plaintext passwords

## Desktop Manager (ARCHIVED)

> **app.py has been archived to `_archive/app.py`** — no longer used.
> Lock management is now done entirely through the web panel.

## Installed Packages (Termux)

### System Packages
python, nodejs, openssh, git, wget, curl, nano, vim, nmap, net-tools,
iproute2, termux-services, termux-api, jq, clang, make, pkg-config,
proot, ca-certificates, cloudflared

### Android Apps
- **Termux** (com.termux) — Linux terminal environment
- **Termux:Boot** (com.termux.boot) v0.8.1 — Auto-start on device boot

### Python Packages
flask, requests, beautifulsoup4, dill, numpy, werkzeug, jinja2,
markupsafe, click, blinker, itsdangerous

## Key Decisions

1. **Screen off**: `stay_on_while_plugged_in` set to 0 - phone screen will turn off normally while charging
2. **Source-based execution**: Functions sent as source code (not pickle/dill bytecode) due to Python version mismatch (PC 3.11 vs Phone 3.13)
3. **Flask control panel**: Runs on phone at port 5000, accessible via ADB port forward, local WiFi, or Cloudflare Tunnel
4. **Dual file spaces**: Separate directories for documents (~/vps/files/) and websites (~/vps/www/)
5. **Security**: Path traversal protection on all file operations using os.path.normpath + startswith checks
6. **Authentication**: Password-based login required for all panel access (important for public tunnel exposure)
7. **Cloudflare Tunnel**: Uses `cloudflared` with `proot` to fix DNS resolution and TLS certificate issues on Termux/Android
8. **proot DNS/TLS fix**: Go binaries on Termux can't read /etc/resolv.conf or CA certs natively; proot bind-mounts Termux's resolv.conf and cert.pem to expected Linux paths
9. **Wake lock**: `termux-wake-lock` prevents Android from killing Termux when phone is in background
10. **Boot script**: `~/.termux/boot/start-vps.sh` auto-starts services on device boot (requires Termux:Boot app from F-Droid)
11. **Watchdog daemon**: `watchdog.sh` runs in background checking every 30s — restarts any crashed service (SSH, HTTP, Panel) and restarts Cloudflare Tunnel when internet recovers after an outage
12. **Battery optimization disabled**: Termux is whitelisted from Android's Doze/battery optimization via `dumpsys deviceidle whitelist +com.termux` and `cmd appops set com.termux RUN_IN_BACKGROUND allow` — Android won't kill Termux in background
13. **Autonomous WiFi-only operation**: Phone no longer needs USB cable; runs independently on any WiFi network with Cloudflare Tunnel providing external access
14. **Auto-recovery**: Power loss → phone boots → Termux:Boot runs start-vps.sh → all services start → watchdog monitors → internet restored → tunnel restarts automatically
15. **Termux:Boot installed via ADB**: Phone has green line on screen making touch difficult, so Termux:Boot was installed via `adb install` with package verification disabled, then launched via `adb shell am start`
16. **Flask app renamed to web.py**: The Flask server is now `web.py` (was `app.py`).
17. **File/Folder locking**: Files and folders can be password-locked. Locks stored as `{"hash": sha256, "pw": plaintext}` in `locks.json`. Web UI checks locks before allowing access. Per-visit unlock via `X-Lock-Password` header or `lock_pw` query param — password required every page load.
18. **Tunnel stability**: Watchdog no longer kills tunnel on internet flicker. Uses `--protocol http2` for stability. Deploy script preserves running tunnel instead of killing it. 2-minute cooldown between tunnel restarts.
19. **Cloudflare Named Tunnel**: Migrated from Quick Tunnel (random URLs) to Named Tunnel with permanent URL `https://vps.example.com`. Token stored at `~/vps/config/tunnel_token.txt`. Domain `example.com` managed via Cloudflare DNS (Zero Trust). Tunnel ID: `f40533f8-6e36-4f42-adf5-4e29297c6dff`.
21. **Self-healing deploy**: `deploy.py` uses 5-phase pipeline (Connect → Upload → Fix → Restart → Verify). Tries ADB forward, WiFi, ADB setup, and sshd start. Kills stale Quick Tunnels. Verifies each service and auto-recovers failures. Prints color-coded status with process list.
22. **Desktop app archived**: `app.py` moved to `_archive/` — lock management done via web panel only.
24. **Button fixes**: ▶ Start now calls `/api/start-all` (only starts services not already running). ⏹ Stop now also stops the Cloudflare Tunnel. 🔄 Reboot now restarts SSH + HTTP + Tunnel (with 2s delay for clean shutdown).
26. **Dynamic IP in start.sh**: `start.sh` now auto-detects local IP via `ip route` instead of hardcoded address (DHCP IP changes).
27. **deploy.py WiFi IP**: Updated to `192.168.1.x` (current DHCP lease). Also deploy summary now fetches live IP from phone instead of hardcoding.
28. **Production audit (2026-03-31)**: Full verification pass — all 5 services (SSH, HTTP, Panel, Tunnel, Watchdog) running, API responses verified, buttons tested, IP/RAM/Storage/credentials all confirmed correct.
29. **Stop-All fix (2026-03-31)**: Added `/api/stop-all` endpoint that properly stops watchdog+tunnel+http+ssh (panel stays running). Before this fix, the Stop button didn't stop watchdog, so watchdog would restart everything within 30 seconds, making Stop ineffective.
30. **Reboot fix (2026-03-31)**: Reboot now kills and restarts watchdog too. Before, watchdog was not restarted after reboot, leaving auto-recovery broken until manual start.
31. **Watchdog in dashboard (2026-03-31)**: Watchdog now appears as a visible service in the dashboard with start/stop buttons, just like SSH/HTTP/Panel/Tunnel.
32. **CPU load fix (2026-03-31)**: `os.getloadavg()` and `/proc/loadavg` both fail on Android/Termux. Added fallback that parses `uptime` command output (e.g., "load average: 2.27, 2.24, 2.16"). Dashboard now shows real CPU load instead of zeros.
33. **Uptime format fix (2026-03-31)**: Improved uptime parsing to produce clean format like "2 days" instead of raw `uptime` command output with timestamps.
34. **Clean deploy — no stale files (2026-04-01)**: `deploy.py` now removes ALL stale remote files (including `templates/asset/`). Also cleans `__pycache__` before restart to prevent stale bytecode. Uses recursive `_sftp_makedirs` for arbitrary directory depth.
35. **Portfolio hosting (2026-03-31)**: Portfolio website hosted at `~/vps/www/` served by HTTP server on port 8080. Accessible at `http://192.168.1.x:8080` (local WiFi) or `http://127.0.0.1:8080` (ADB).
36. **Public portfolio via /site/ route (2026-03-31)**: Added `/site/` route in Flask panel (`web.py`) that serves files from `~/vps/www/` without authentication. Portfolio is publicly accessible at `https://vps.example.com/site/` through the Cloudflare tunnel. Images and all assets load correctly via `/site/image/` path.
38. **Recycle Bin (2026-04-06)**: All file/folder deletions from both File Manager and Website Space now move items to `~/vps/.trash/` instead of permanent deletion. Metadata stored in `.meta.json`. Recycle Bin page at `/trash` allows restore, permanent delete, and empty trash. Added after an important folder was accidentally deleted and couldn't be recovered. Sidebar updated with 🗑️ Recycle Bin nav item.

## How to Use

### Normal Operation (no USB, no PC needed)
The phone VPS runs fully autonomously. Once set up:
1. Keep the phone plugged into a charger and connected to WiFi
2. If power goes out and comes back — phone boots → Termux:Boot starts services automatically
3. If internet drops and recovers — watchdog restarts Cloudflare Tunnel automatically
4. Access from anywhere via **https://vps.example.com** (permanent URL, never changes)

### First Time Setup (USB required once)
1. Connect phone via USB
2. Run: `adb forward tcp:5000 tcp:5000; adb forward tcp:8022 tcp:8022; adb forward tcp:8080 tcp:8080`
3. Run: `cd phone-vps && python deploy.py`
4. Open Termux on phone and run: `bash ~/panel/start.sh`
5. Open browser: http://127.0.0.1:5000
6. Login with password: `<your-password>`
7. Verify tunnel URL on Dashboard (should show https://vps.example.com)
8. **Disconnect USB** — phone is now autonomous

### After Power Loss Recovery
1. Phone boots and connects to WiFi
2. Termux:Boot auto-runs `~/.termux/boot/start-vps.sh`
3. All services start: SSH, HTTP, Panel, Tunnel, Watchdog
4. Same permanent URL works: https://vps.example.com
5. If you can't access, connect to same WiFi and go to http://PHONE_IP:5000

### After Internet Outage
1. Watchdog detects internet is down (logs: `[NET] Internet went OFFLINE`)
2. Core services (SSH, HTTP, Panel) keep running locally
3. When internet returns, watchdog detects it (logs: `[NET] Internet is BACK online`)
4. Watchdog automatically restarts Cloudflare Tunnel
5. Same permanent URL works: https://vps.example.com

### Access from Another Device / Location
1. Go to **https://vps.example.com**
2. Login with password: `<your-password>`
3. Full panel access: dashboard, file manager, website space, tunnel controls
4. No VPN, no port forwarding, no special software needed — just a browser

### Deploy Updated Panel
```bash
cd phone-vps
python deploy.py
```
The deploy script is **self-healing** — it will:
1. Auto-detect connection method (ADB forward → WiFi → ADB setup → start sshd)
2. Upload all panel files and tunnel token
3. Kill stale Quick Tunnel and `app.py` leftovers
4. Verify/install cloudflared and proot
5. Restart all services via `start.sh`
6. Verify every service individually (Flask, HTTP, SSH, Named Tunnel, Watchdog)
7. Auto-recover any failed service (manual start as fallback)
8. HTTP health check on panel (expect 200)
9. Print color-coded status report with running process list

```bash
python deploy.py
```
The bot deploy script will:
1. Auto-detect connection (ADB forward → WiFi → ADB setup → start sshd)
2. Upload bot files (clean deploy — removes stale files, preserves expenses.db)
4. Kill old bot process, clean __pycache__, start new bot (setsid detached)
5. Verify bot process running + check logs for "Application started"
6. matplotlib installs in background — /stats unavailable until done, all other features work

### Access via WiFi (no USB needed, same network)
If phone and PC are on same WiFi:
- Panel: http://192.168.1.x:5000
- Website: http://192.168.1.x:8080
- SSH: `ssh -p 8022 <user>@192.168.1.x` (password: <your-password>)
- **Note**: WiFi IP (192.168.1.x) is DHCP-assigned and may change if router restarts

### Auto-Start on Phone Boot
- **Termux:Boot** app installed (v0.8.1 from F-Droid, installed via ADB)
- Boot receiver registered and `BOOT_COMPLETED` permission granted
- Boot script at `~/.termux/boot/start-vps.sh` — waits 10 seconds for system to settle, then starts all services
- Phone boot → Termux:Boot triggers → all services start automatically

## Auto-Recovery Architecture

```
Phone Boot → Termux:Boot → start-vps.sh
                              ├── termux-wake-lock (prevent kill)
                              ├── sshd (port 8022)
                              ├── http.server (port 8080)
                              ├── panel web.py (port 5000)
                              ├── cloudflared tunnel (HTTPS)
                              └── watchdog.sh (monitor daemon)
                                    ↓ every 30 seconds
                              ├── Check SSH → restart if dead
                              ├── Check HTTP → restart if dead
                              ├── Check Panel → restart if dead
                              ├── Check Internet → if recovered:
                              │     └── Restart Cloudflare Tunnel
                              └── Check Tunnel → restart if dead
```

## Android Configuration Applied

| Setting | Value | Purpose |
|---------|-------|---------|
| Battery optimization | Whitelisted | Prevents Android from killing Termux |
| RUN_IN_BACKGROUND | allow | Allows Termux to run in background |
| RUN_ANY_IN_BACKGROUND | allow | Allows any Termux process in background |
| stay_on_while_plugged_in | 0 | Screen turns off normally |
| always_finish_activities | 0 | Don't kill background activities |
| Termux wake-lock | Active | Keeps CPU alive for background work |

## Uptime Info
- Phone runs autonomously — no USB cable or PC needed
- `termux-wake-lock` keeps Termux alive in background
- Watchdog daemon checks every 30 seconds and auto-restarts dead services
- Cloudflare tunnel provides access from any device/network/location
- **Permanent URL: https://vps.example.com** (never changes)
- Tunnel auto-restarts when internet recovers after an outage
- Power loss → auto-recovery on boot (with Termux:Boot app)
- For best uptime: keep phone always plugged in to power and connected to WiFi
