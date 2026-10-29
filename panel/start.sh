#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# Phone VPS - Start Control Panel & Services
# ============================================

export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
export HOME=/data/data/com.termux/files/home

echo "======================================"
echo "  Phone VPS - Starting..."
echo "======================================"

# Kill any leftover watchdog first
pkill -f 'watchdog.sh' 2>/dev/null

# Acquire wake lock to keep Termux alive
termux-wake-lock 2>/dev/null
echo "[OK] Wake lock acquired"

# Ensure battery optimization is disabled (in case user reset it)
# This is a reminder - must be set via Settings > Apps > Termux > Battery > Unrestricted
echo "[--] Ensure Termux battery optimization = Unrestricted in Android Settings"

# Ensure DNS is set
echo 'nameserver 1.1.1.1' > $PREFIX/etc/resolv.conf
echo 'nameserver 8.8.8.8' >> $PREFIX/etc/resolv.conf

# Create dirs if missing
mkdir -p ~/vps/www ~/vps/files ~/vps/logs ~/vps/config

# Start SSH
sshd 2>/dev/null
echo "[OK] SSH (port 8022)"

# Start HTTP server for websites
if ! pgrep -f "http.server 8080" >/dev/null 2>&1; then
    cd ~/vps/www
    nohup python3 -m http.server 8080 > ~/vps/logs/http.log 2>&1 &
fi
echo "[OK] HTTP (port 8080)"

# Start Control Panel
if ! pgrep -f "python3 web.py" >/dev/null 2>&1; then
    cd ~/panel
    nohup python3 web.py > ~/vps/logs/panel.log 2>&1 &
fi
echo "[OK] Panel (port 5000)"

# Start Cloudflare Named Tunnel (permanent public URL)
TUNNEL_TOKEN=$(cat ~/vps/config/tunnel_token.txt 2>/dev/null)
if command -v cloudflared &>/dev/null && [ -n "$TUNNEL_TOKEN" ]; then
    if ! pgrep -f "cloudflared tunnel" >/dev/null 2>&1; then
        rm -f ~/vps/logs/tunnel.log
        nohup proot \
            -b $PREFIX/etc/resolv.conf:/etc/resolv.conf \
            -b $PREFIX/etc/tls/cert.pem:/etc/ssl/certs/ca-certificates.crt \
            cloudflared tunnel --protocol http2 --no-autoupdate \
            run --token "$TUNNEL_TOKEN" \
            > ~/vps/logs/tunnel.log 2>&1 &
        echo "[OK] Tunnel starting (your public URL)"
    else
        echo "[OK] Tunnel already running (your public URL)"
    fi
else
    echo "[--] Tunnel (cloudflared or token not found)"
fi

# Start Watchdog daemon
nohup bash ~/panel/watchdog.sh > /dev/null 2>&1 &
echo "[OK] Watchdog daemon (PID $!)"

echo "======================================"
echo "  All services started!"
LOCAL_IP=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+' || echo '?.?.?.?')
echo "  Local:  http://${LOCAL_IP}:5000"
URL=$(cat ~/vps/config/tunnel_url.txt 2>/dev/null)
if [ -n "$URL" ]; then
    echo "  Public: $URL"
fi
echo "======================================"
