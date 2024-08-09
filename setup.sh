
# create variable for ankleflex path
echo "Setting up the environment"
python -m venv /home/ankleflex/AnkleFlex/venv 
source /home/ankleflex/AnkleFlex/venv/bin/activate 

echo "Installing requirements"
pip install -r /home/ankleflex/AnkleFlex/Src/requirements.txt

echo "Setting up the crontab command"
(crontab -l 2>/dev/null; echo "@reboot /home/ankleflex/AnkleFlex/venv/bin/python /home/ankleflex/AnkleFlex/Src/main.py") | crontab -

echo "Setting up the hotspot"
sudo nmcli device wifi hotspot con-name AnkleFlexHotspot ssid AnkleFlex password starseng
sudo nmcli connection modify AnkleFlexHotspot autoconnect yes
sudo nmcli connection up AnkleFlexHotspot

sudo reboot
