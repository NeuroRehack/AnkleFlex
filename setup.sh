
# create variable for ankleflex path
export ANKLEFLEX_PATH=/home/AnkleFlex

echo "Setting up the environment"
python -m venv $ANKLEFLEX_PATH/venv || (echo "failed to create virtual environment" && exit 1)
source $ANKLEFLEX_PATH/venv/bin/activate || (echo "failed to activate virtual environment" && exit 1)

echo "Installing requirements"
pip install -r $ANKLEFLEX_PATH/requirements.txt || (echo "failed to install requirements" && exit 1)

echo "Setting up the crontab command"
(crontab -l 2>/dev/null; echo "@reboot /home/AnkleFlex/venv/bin/python /home/AnkleFlex/Src/main.py") | crontab -

echo "Setting up the hotspot"
sudo nmcli device wifi hotspot con-name AnkleFlexHotspot ssid AnkleFlex password starseng
sudo nmcli connection modify AnkleFlexHotspot autoconnect yes
sudo nmcli connection up AnkleFlexHotspot

sudo reboot
