
# create variable for ankleflex-venv path
echo "Setting up the environment"
python -m venv /home/ankleflex/ankleflex-venv
source /home/ankleflex/ankleflex-venv/bin/activate 

echo "Installing requirements"
pip install -r ./Src/requirements.txt  ##Need to test this

echo "Setting up the crontab command"
(crontab -l 2>/dev/null; echo "@reboot /home/ankleflex/AnkleFlex/venv/bin/python /home/ankleflex/AnkleFlex/Src/main.py") | crontab -

echo "Setting up the hotspot"
sudo nmcli device wifi hotspot con-name AnkleFlexHotspot ssid AnkleFlex password starseng
sudo nmcli connection modify AnkleFlexHotspot autoconnect yes
sudo nmcli connection up AnkleFlexHotspot

sudo reboot
