echo "Switching AnkleFlex device to development Wi-Fi setup"

# Stop the hotspot if it is active
if nmcli connection show --active | grep -q "AnkleFlexHotspot"; then
    echo "Stopping hotspot..."
    sudo nmcli connection down AnkleFlexHotspot
    sudo nmcli connection modify AnkleFlexHotspot autoconnect no
fi

# Connect to development Wi-Fi
DEV_SSID="Amir"
DEV_PASS="amiramirr"

echo "Connecting to $DEV_SSID"
sudo nmcli device wifi connect "$DEV_SSID" password "$DEV_PASS"

if [ $? -eq 0 ]; then
    echo "Connected to $DEV_SSID successfully"
else
    echo "Failed to connect to $DEV_SSID"
    exit 1
fi

# Activate the virtual environment and run the development script
echo "Activating AnkleFlex development environment"
source /home/ankleflex/AnkleFlex/venv/bin/activate


# Kill all active Python processes
echo "Stopping all running Python processes..."
sudo pkill -f python || true