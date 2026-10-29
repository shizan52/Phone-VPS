#!/data/data/com.termux/files/usr/bin/bash
echo "Stopping all services..."
pkill -f "watchdog.sh" 2>/dev/null && echo "[OK] Watchdog stopped" || echo "[--] Watchdog not running"
pkill -f "cloudflared" 2>/dev/null && echo "[OK] Tunnel stopped" || echo "[--] Tunnel not running"
pkill -f "python3 web.py" 2>/dev/null && echo "[OK] Panel stopped" || echo "[--] Panel not running"
pkill -f "http.server 8080" 2>/dev/null && echo "[OK] HTTP stopped" || echo "[--] HTTP not running"
pkill sshd 2>/dev/null && echo "[OK] SSH stopped" || echo "[--] SSH not running"
termux-wake-unlock 2>/dev/null
echo "All services stopped."
