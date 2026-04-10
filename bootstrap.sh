#!/usr/bin/env bash
# AnkleFlex — one-shot bootstrap for a fresh Raspberry Pi OS install
#
# Run this immediately after first SSH login:
#
#   curl -fsSL https://raw.githubusercontent.com/SamiKaab/AnkleFlex/develop/bootstrap.sh | bash
#
# What it does:
#   1. Installs git and curl
#   2. Clones the repository into ~/AnkleFlex
#   3. Delegates to setup.sh (system deps, uv, Python deps, hotspot, autostart)
#   4. Reboots — on next boot the hotspot and app start automatically
#
# After reboot:
#   • Join the Wi-Fi hotspot  SSID: AnkleFlex  password: starseng
#   • Open http://10.42.0.1:8000/   (or http://ankleflex.local:8000/)

set -e

REPO_URL="https://github.com/SamiKaab/AnkleFlex.git"
BRANCH="develop"
INSTALL_DIR="$HOME/AnkleFlex"

echo "╔══════════════════════════════════════════╗"
echo "║         AnkleFlex — Bootstrap            ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. System prerequisites ───────────────────────────────────────────────────
echo "[1/4] Installing prerequisites..."
sudo apt-get update -q
sudo apt-get install -y -q git curl

# ── 2. Clone repository ───────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "[2/4] Repository already exists — pulling latest..."
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
else
    echo "[2/4] Cloning repository..."
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# ── 3. Run setup.sh ───────────────────────────────────────────────────────────
echo "[3/4] Running setup.sh..."
bash "$INSTALL_DIR/setup.sh"

# ── 4. Reboot ─────────────────────────────────────────────────────────────────
echo "[4/4] Bootstrap complete. Rebooting in 5 seconds..."
echo "      After reboot, join Wi-Fi:  AnkleFlex / starseng"
echo "      Then open:                 http://ankleflex.local:8000/"
sleep 5
sudo reboot
