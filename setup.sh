
echo "Setting up the environment"
python -m venv venv || echo "failed to create virtual environment"
source venv/bin/activate || echo "failed to activate virtual environment"

echo "Installing requirements"
pip install -r requirements.txt || echo "failed to install requirements"

echo "Setting up the crontab command"
(crontab -l 2>/dev/null; echo "@reboot /home/ankleflex/venv/bin/python /home/ankleflex/main.py") | crontab -

echo "Setting up the hotspot"
sudo nmcli device wifi hotspot con-name AnkleFlexHotspot ssid AnkleFlex password starseng
sudo nmcli connection modify AnkleFlexHotspot autoconnect yes
sudo nmcli connection up AnkleFlexHotspot

sudo reboot
