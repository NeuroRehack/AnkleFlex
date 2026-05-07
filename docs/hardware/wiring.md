# AnkleFlex -- Hardware Reference

> **Status:** Draft -- May 2026

---

## Wiring Table

| Component | Signal | Pi GPIO (BCM) | Pi Board Pin | Notes |
|---|---|---|---|---|
| HX711 DOUT | Data out | GPIO 2 | Pin 3 | Currently on I2C SDA pin -- move to GPIO 5 (Pin 29) per task D1 |
| HX711 SCK | Clock | GPIO 3 | Pin 5 | Currently on I2C SCL pin -- move to GPIO 6 (Pin 31) per task D1 |
| HX711 VCC | Power | 3.3 V | Pin 1 | |
| HX711 GND | Ground | GND | Pin 6 | |
| LED + (anode) | LED output | GPIO 26 | Pin 37 | 330 Ohm series resistor to GND |
| LED - (cathode) | GND | GND | Pin 39 | Via 330 Ohm resistor |
| Button | Input | GPIO 17 | Pin 11 | Pull-up enabled in software (`GPIO.PUD_UP`); press connects to GND |
| Button | GND | GND | Pin 9 | |
| TAL220B (red) | Excitation + | HX711 E+ | | |
| TAL220B (black) | Excitation - | HX711 E- | | |
| TAL220B (white) | Signal + | HX711 A+ | | |
| TAL220B (green) | Signal - | HX711 A- | | |

---

## Bill of Materials

| Part | Qty | Description | Notes |
|---|---|---|---|
| Raspberry Pi 4B | 1 | Main compute board | 2 GB RAM minimum |
| TAL220B 5 kg load cell | 1 | Straight bar, strain gauge | Rated to 5 kg; calibration factor `-1554` |
| HX711 module | 1 | 24-bit ADC breakout for load cells | Any standard breakout; pinout above |
| Tactile button | 1 | Momentary push button, normally open | |
| LED (green) | 1 | 5 mm through-hole | |
| 330 Ohm resistor | 1 | LED current limiter | |

---

## Protocol Details

| Interface | Parameters |
|---|---|
| HX711 | Bit-banged GPIO; `channel = A`, `gain = 64` |
| WiFi hotspot | SSID: `AnkleFlex` · Password: see setup output · mDNS: `ankleflex.local` |
| Web server | HTTP on port 8000 · SSE at `/stream` (20 Hz) |

---

## Original Wiring Diagrams

See `Doc/wiring_diagram_raspberry.html` and `Doc/raspberry_pi_settings.html` for the original visual wiring diagrams (HTML, unchanged from initial hardware design).
