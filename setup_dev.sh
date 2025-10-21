
echo "Setting up the crontab command"
(crontab -l 2>/dev/null; echo "@reboot /home/ankleflex/ankleflex-venv/bin/python /home/ankleflex/AnkleFlex/Src/main_dev_tare.py") | crontab -

sudo reboot
