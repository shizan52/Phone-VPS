#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# Phone VPS - Watchdog Daemon
# Monitors services and auto-restarts them.
# Only restarts tunnel if process is truly dead.
# ============================================

export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
export HOME=/data/data/com.termux/files/home

LOGFILE="$HOME/vps/logs/watchdog.log"
HEARTBEAT="$HOME/vps/logs/.watchdog_heartbeat"
CHECK_INTERVAL=30   # seconds between checks
NET_CHECK_HOST="1.1.1.1"
LAST_NET_STATE="unknown"
TUNNEL_COOLDOWN=120  # don't restart tunnel within 2 minutes of last restart
LAST_TUNNEL_START=0
NET_FLAP_COUNT=0
NET_FLAP_SUPPRESS=5  # suppress repeated offline/online logs after this many flaps

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGFILE"
}

check_internet() {
    ping -c 1 -W 3 "$NET_CHECK_HOST" >/dev/null 2>&1
    return $?
}

is_running() {
    pgrep -f "$1" >/dev/null 2>&1
    return $?
}

now_epoch() {
    date +%s
}

start_sshd() {
    if ! is_running "sshd"; then
        sshd 2>/dev/null
        log "[RESTART] SSH started"
    fi
}

start_http() {
    if ! is_running "http.server 8080"; then
        cd ~/vps/www
        nohup python3 -m http.server 8080 >> ~/vps/logs/http.log 2>&1 &
        log "[RESTART] HTTP server started"
    fi
}

start_panel() {
    if ! is_running "python3 web.py"; then
        cd ~/panel
        nohup python3 web.py >> ~/vps/logs/panel.log 2>&1 &
        log "[RESTART] Panel started"
    fi
}

start_tunnel() {
    # Only restart if cloudflared is truly not running
    if is_running "cloudflared tunnel"; then
        return
    fi

    # Enforce cooldown to avoid rapid restarts
    local NOW=$(now_epoch)
    local ELAPSED=$((NOW - LAST_TUNNEL_START))
    if [ "$ELAPSED" -lt "$TUNNEL_COOLDOWN" ]; then
        return
    fi

    local TOKEN=$(cat ~/vps/config/tunnel_token.txt 2>/dev/null)
    if command -v cloudflared &>/dev/null && [ -n "$TOKEN" ]; then
        rm -f ~/vps/logs/tunnel.log
        nohup proot \
            -b $PREFIX/etc/resolv.conf:/etc/resolv.conf \
            -b $PREFIX/etc/tls/cert.pem:/etc/ssl/certs/ca-certificates.crt \
            cloudflared tunnel --protocol http2 --no-autoupdate \
            run --token "$TOKEN" \
            > ~/vps/logs/tunnel.log 2>&1 &
        LAST_TUNNEL_START=$(now_epoch)
        log "[RESTART] Named tunnel started (your public URL)"
    fi
}

# ---- Log Rotation ----

MAX_LOG_SIZE=524288  # 512 KB per log file
LOG_ROTATE_CHECK=0
LOG_ROTATE_INTERVAL=20  # check every 20 cycles (~10 min)

rotate_logs() {
    for logfile in "$HOME/vps/logs"/*.log; do
        [ -f "$logfile" ] || continue
        local size=$(wc -c < "$logfile" 2>/dev/null)
        if [ "${size:-0}" -gt "$MAX_LOG_SIZE" ]; then
            tail -500 "$logfile" > "${logfile}.tmp" && mv "${logfile}.tmp" "$logfile"
            log "[ROTATE] $(basename $logfile) trimmed (was ${size} bytes)"
        fi
    done
}

# ---- Main Loop ----

log "=========================================="
log "Watchdog started (PID $$, interval ${CHECK_INTERVAL}s)"
log "=========================================="

while true; do
    # Write heartbeat (so external tools can detect watchdog death)
    date +%s > "$HEARTBEAT" 2>/dev/null

    # Log rotation check
    LOG_ROTATE_CHECK=$((LOG_ROTATE_CHECK + 1))
    if [ "$LOG_ROTATE_CHECK" -ge "$LOG_ROTATE_INTERVAL" ]; then
        rotate_logs
        LOG_ROTATE_CHECK=0
    fi

    # Check internet
    if check_internet; then
        CURRENT_NET="up"
        if [ "$LAST_NET_STATE" != "up" ]; then
            NET_FLAP_COUNT=$((NET_FLAP_COUNT + 1))
            if [ "$NET_FLAP_COUNT" -le "$NET_FLAP_SUPPRESS" ]; then
                log "[NET] Internet is BACK online"
            elif [ "$NET_FLAP_COUNT" -eq $((NET_FLAP_SUPPRESS + 1)) ]; then
                log "[NET] Internet BACK (further flap logs suppressed)"
            fi
            # Internet just came back - DON'T kill the tunnel, let it reconnect
            # If cloudflared truly died, start_tunnel will handle it below
            sleep 5
        else
            # Stable - reset flap counter after 5 minutes of stability
            NET_FLAP_COUNT=0
        fi
    else
        CURRENT_NET="down"
        if [ "$LAST_NET_STATE" != "down" ]; then
            NET_FLAP_COUNT=$((NET_FLAP_COUNT + 1))
            if [ "$NET_FLAP_COUNT" -le "$NET_FLAP_SUPPRESS" ]; then
                log "[NET] Internet went OFFLINE"
            fi
        fi
    fi
    LAST_NET_STATE="$CURRENT_NET"

    # Always check services (even when offline for local services)
    start_sshd
    start_http
    start_panel

    # Only try tunnel when online
    if [ "$CURRENT_NET" = "up" ]; then
        start_tunnel
    fi

    sleep "$CHECK_INTERVAL"
done
