# AnkleFlex -- User Guide

> **Status:** Draft -- May 2026

---

## What is AnkleFlex?

AnkleFlex measures ankle push and pull force in real time. The device creates its own WiFi network -- you connect to it and open a browser to see a live force chart. No app to install, no internet required.

---

## Setup (First Time)

1. Power on the AnkleFlex device (Raspberry Pi).
2. Wait 30 seconds for the device to boot and create its WiFi hotspot.
3. On your laptop or tablet, connect to the WiFi network named **AnkleFlex**.
   - Password: see the label on the device (or the setup sheet from your administrator).
4. Open a browser and go to: **http://ankleflex.local:8000/**
   - If that does not load, try: **http://10.42.0.1:8000/**

---

## Daily Use

### Start a session

1. Connect to the AnkleFlex WiFi and open the browser UI.
2. Secure the load cell under the patient's foot or against the ankle.
3. Press **Tare / Reset** in the browser (or hold the physical button on the device for 1 second) to zero the reading with no force applied.
4. Ask the patient to push or pull -- the bar chart updates in real time.

### Tare (re-zero)

Press **Tare / Reset** any time to set the current load as the new zero reference and clear the session min/max lines. This is useful between trials.

### Reading the chart

| Element | Meaning |
|---|---|
| Blue bar | Current force reading |
| Red dashed line (MAX) | Peak positive force since last tare |
| Orange dashed line (MIN) | Peak negative force since last tare |
| Zero line | Reference baseline |
| Large number below chart | Current force in kg |

Positive values are push force; negative values are pull force.

### Connection status

A green indicator shows the live SSE connection is active. If it turns red, refresh the page or check the WiFi connection.

---

## Troubleshooting

| Problem | Try this |
|---|---|
| Browser shows "Connecting..." indefinitely | Check you are connected to the **AnkleFlex** WiFi |
| `ankleflex.local` does not load | Use the IP address `http://10.42.0.1:8000/` instead |
| Force reading does not change | Re-tare, then check the load cell cables are seated correctly |
| Device does not create a hotspot after boot | Hold the physical button for 2 quick presses to reboot |
| Page loads but chart is frozen | Refresh the browser tab |

---

## Physical Button Reference

| Gesture | Action |
|---|---|
| Hold > 1 second (long press) | Tare -- sets current load as new zero; LED blinks to confirm |
| Quick second press (< 1 s after release) | Reboot the device |

---

## For Administrators

See [../dev/CONTRIBUTING.md](../dev/CONTRIBUTING.md) for developer setup and [../hardware/wiring.md](../hardware/wiring.md) for pin assignments and BOM.
