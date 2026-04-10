
#!/usr/bin/env bash
# AnkleFlex — Raspberry Pi setup script
# Run once after cloning the repository.
#
# Usage:
#   bash ~/AnkleFlex/setup.sh
#
# After running, reboot the Pi. On next boot:
#   • The AnkleFlex Wi-Fi hotspot starts automatically (SSID: AnkleFlex  pw: starseng)
#   • The web app starts automatically
#   • Access at: http://10.42.0.1:8000/  (or http://ankleflex.local:8000/)

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== AnkleFlex setup ==="
echo "Repository: $REPO_DIR"

# ── 1. System dependencies ──────────────────────────────────────────────────
echo "[1/4] Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y -q \
    python3-pip python3-venv python3-dev \
    git curl swig liblgpio-dev

# Install uv if not already present
if ! command -v uv &>/dev/null; then
    echo "    Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# Always ensure uv is on PATH for this session
export PATH="$HOME/.local/bin:$PATH"

# ── 2. Python environment ───────────────────────────────────────────────────
echo "[2/4] Installing Python dependencies (hardware extras)..."
cd "$REPO_DIR"
uv sync --extra hardware

# ── 3. WiFi hotspot ─────────────────────────────────────────────────────────
# IMPORTANT: We only CREATE the connection profile here — we do NOT run
# 'nmcli con up', because activating a hotspot resets the network stack
# and drops the SSH session. The profile has autoconnect=yes so
# NetworkManager will start the hotspot automatically on next reboot.
echo "[3/4] Configuring WiFi hotspot profile..."

# Auto-detect the Ethernet connection name and set it as the preferred route
ETH_CON=$(nmcli -t -f NAME,TYPE connection show 2>/dev/null \
    | grep ':ethernet' | head -1 | cut -d: -f1)
if [ -n "$ETH_CON" ]; then
    echo "    Pinning Ethernet ('$ETH_CON') as preferred route (metric 100)..."
    sudo nmcli connection modify "$ETH_CON" ipv4.route-metric 100 2>/dev/null || true
else
    echo "    Warning: could not detect Ethernet connection name — skipping metric pin"
fi

# Remove any existing hotspot profile then create a fresh one
sudo nmcli connection delete AnkleFlexHotspot 2>/dev/null || true
sudo nmcli connection add \
    type wifi \
    ifname wlan0 \
    con-name AnkleFlexHotspot \
    autoconnect yes \
    ssid AnkleFlex \
    802-11-wireless.mode ap \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk starseng \
    ipv4.method shared \
    ipv4.route-metric 200 \
    ipv6.method disabled
echo "    Hotspot profile created — will activate automatically on reboot"

# ── 4. Auto-start on boot (systemd service) ─────────────────────────────────
echo "[4/4] Installing systemd service..."
PYTHON="$REPO_DIR/.venv/bin/python"
LOG="$HOME/ankleflex.log"
SERVICE_FILE="/etc/systemd/system/ankleflex.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=AnkleFlex force feedback app
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON Src/main.py
Restart=always
RestartSec=5
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ankleflex.service
echo "    systemd service enabled: ankleflex.service"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "✓ Setup complete. Now reboot:"
echo "    sudo reboot"
echo ""
echo "After reboot:"
echo "  • Join Wi-Fi:   SSID=AnkleFlex  password=starseng"
echo "  • Open browser: http://10.42.0.1:8000/"
echo "  • mDNS URL:     http://ankleflex.local:8000/"
echo "  • View logs:    tail -f $LOG"
echo "  • App status:   sudo systemctl status ankleflex"

