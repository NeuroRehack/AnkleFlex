# AnkleFlex — Setup & Test Guide


## Step 1 — Flash the SD Card

Follow the flashing instructions in the [Raspberry Pi set up](./ReadMe.md#raspberry-pi-set-up) section of the ReadMe, using `Doc/raspberry_pi_settings.png` as a reference.

> ⚠️ The WiFi credentials you enter in the Imager are your **existing** home/office/phone-hotspot

> ℹ️ If you are using an iPhone hotspot, enable **Maximise Compatibility** in the iPhone
> hotspot settings to allow the Pi to connect.


## Step 2 — First Boot and SSH

1. Insert the SD card into the Pi and power it on.
2. Wait approximately **60–90 seconds** for the first boot to complete.
3. Make sure your laptop is connected to **the same WiFi network** you entered in Step 1.
4. Open a terminal and SSH into the Pi:
   ```
   ssh ankleflex@ankleflex.local
   ```
   Password: `starseng`

   > If `ankleflex.local` does not resolve, find the Pi's IP address from your router's
   > device list and connect directly:
   > ```
   > ssh ankleflex@<pi-ip-address>
   > ```


## Step 3 — Install AnkleFlex

Run the one-line bootstrap script from your SSH session:

```sh
curl -fsSL https://raw.githubusercontent.com/NeuroRehack/AnkleFlex/feature/fastapi-migration/bootstrap.sh | bash
```

This installs all dependencies, creates the AnkleFlex WiFi hotspot profile, installs the
autostart services, and reboots the Pi. 


## Step 4 — Connect to the AnkleFlex Hotspot

After the reboot, the Pi broadcasts the AnkleFlex hotspot and the web app starts automatically. At this point, the Pi is no longer connected to your WiFi and instead creates its own WiFi network for you to connect to. If you need the Pi to be connected to the internet for any reason, connect the pi to internet via ethernet or USB tethering instead of WiFi.

1. Wait approximately **30–60 seconds** after the Pi powers back on.
2. On your laptop or tablet, connect to:
   - **SSID:** `AnkleFlex`
   - **Password:** `starseng`
3. Open a browser and navigate to:
   ```
   http://ankleflex.local:8000/
   ```
   If that does not load, use the raw IP:
   ```
   http://10.42.0.1:8000/
   ```
4. You should see the AnkleFlex force chart with a green connection indicator.

---

## Step 5 — Test on Windows Without Hardware (Emulation Mode)

1. Install `uv`:
   ```sh
   pip install uv
   ```
2. Clone the repo and install dependencies:
   ```sh
   git clone --branch feature/fastapi-migration https://github.com/NeuroRehack/AnkleFlex.git
   cd AnkleFlex
   uv venv
   uv pip install -e .
   ```
3. Run the app:
   ```sh
   python Src/main.py
   ```
   Emulation is automatic — on any machine without Raspberry Pi hardware libraries
   installed, the app detects this and starts in emulation mode.
4. Open `http://localhost:8000/` and use the slider to simulate force values.


