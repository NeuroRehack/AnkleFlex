
echo "Setting up the crontab command"
(crontab -l 2>/dev/null; echo "@reboot /home/ankleflex/ankleflex-venv/bin/python /home/ankleflex/AnkleFlex/Src/main_dev.py") | crontab -

echo "Setting up the hotspot" 
sudo nmcli device wifi hotspot con-name AnkleFlexHotspot ssid AnkleFlex password starseng
sudo nmcli connection modify AnkleFlexHotspot autoconnect yes
sudo nmcli connection up AnkleFlexHotspot

sudo reboot
