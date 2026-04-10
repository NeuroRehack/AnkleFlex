
#!/usr/bin/env bash
# AnkleFlex — Raspberry Pi setup script
# Run once as the 'ankleflex' user after cloning the repository.
#
# Usage:
#   cd /home/ankleflex/AnkleFlex
#   bash setup.sh
#
# After running, the app will start automatically on every boot.
# Access it at:  http://ankleflex.local:8000/   (or http://10.42.0.1:8000/)

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== AnkleFlex setup ==="
echo "Repository: $REPO_DIR"

# ── 1. System dependencies ──────────────────────────────────────────────────
echo "[1/5] Updating system packages..."
sudo apt-get update -q
sudo apt-get install -y -q python3-pip python3-venv git

# Install uv (fast Python package manager)
if ! command -v uv &>/dev/null; then
    echo "[1/5] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# ── 2. Python environment ───────────────────────────────────────────────────
echo "[2/5] Installing Python dependencies (hardware extras)..."
cd "$REPO_DIR"
uv sync --extra hardware

# ── 3. WiFi hotspot ─────────────────────────────────────────────────────────
echo "[3/5] Configuring WiFi hotspot..."
sudo nmcli device wifi hotspot \
    con-name AnkleFlexHotspot \
    ssid AnkleFlex \
    password starseng 2>/dev/null || true
sudo nmcli connection modify AnkleFlexHotspot autoconnect yes 2>/dev/null || true
sudo nmcli connection up AnkleFlexHotspot 2>/dev/null || true

# ── 4. Auto-start on boot (crontab) ─────────────────────────────────────────
echo "[4/5] Setting up auto-start..."
PYTHON="$REPO_DIR/.venv/bin/python"
MAIN="$REPO_DIR/Src/main.py"
LOG="/home/ankleflex/ankleflex.log"
CRON_CMD="@reboot $PYTHON $MAIN >> $LOG 2>&1"

# Remove any existing AnkleFlex crontab entry then add the new one
(crontab -l 2>/dev/null | grep -v "AnkleFlex\|ankleflex\|main\.py" ; echo "$CRON_CMD") | crontab -

echo "    Auto-start registered: $CRON_CMD"

# ── 5. Done ──────────────────────────────────────────────────────────────────
echo "[5/5] Setup complete."
echo ""
echo "Next steps:"
echo "  • Reboot the Pi:          sudo reboot"
echo "  • Check the log after:    tail -f $LOG"
echo "  • Open in browser:        http://ankleflex.local:8000/"
echo "  • Fallback IP:            http://10.42.0.1:8000/"
echo ""
echo "To run manually (hardware mode):"
echo "  $PYTHON $MAIN"
echo ""
echo "To run in emulation mode (no hardware):"
echo "  ANKLEFLEX_EMULATE_LOADCELL=1 $PYTHON $MAIN"

