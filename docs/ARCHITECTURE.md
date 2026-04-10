# AnkleFlex — Architecture

> **Status:** Current — April 2026
> **Branch:** `develop`

See also: [REQUIREMENTS.md](REQUIREMENTS.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

---

## 1. Hardware

| Component | Model | Notes |
|---|---|---|
| SBC | Raspberry Pi 4B | Primary target; future upgrade to Pi 5 possible |
| Load cell | TAL220B 5 kg straight bar | Measures ankle dorsiflexion/plantarflexion force |
| ADC | HX711 | GPIO: DOUT = pin 2, SCK = pin 3 |
| LED | Generic + 330 Ω resistor | GPIO 26 — status indicator |
| Button | Tactile push button | GPIO 17, pull-up; tare / reboot modes |
| Network | Pi WiFi hotspot via `nmcli` | SSID: `AnkleFlex`, password: `starseng` |

### Network topology

```
Pi hotspot (10.42.0.1)
    │
    ├── Clinician laptop / tablet (browser → http://ankleflex.local:8000/)
    └── Patient tablet (browser, optional — same URL)
```

**Fallback:** If mDNS (`ankleflex.local`) fails on a client device, use `http://10.42.0.1:8000/` directly.

---

## 2. Software Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | **FastAPI** + **Uvicorn** (ASGI) | Async, lightweight, excellent Pi performance; native SSE + REST |
| Real-time transport | **Server-Sent Events (SSE)** | Pi pushes data at 2 Hz; browser auto-reconnects; standard HTTP |
| Frontend | **Vanilla HTML / CSS / JS** | No build toolchain; works offline; fast first load |
| Charts | **Chart.js 4.x** (~200 KB, vendored) | Lightweight; flexible; no external CDN required |
| Hardware | `hx711` + `rpi-lgpio` | Unchanged from original implementation |
| Emulation | `EmulatedHX711` in `Src/emulation/hx711.py` | Injected into real `LoadCell`; only the ADC read is mocked |
| Package manager | `uv` + `pyproject.toml` | Reproducible installs; replaces `requirements.txt` |

### Why FastAPI over Flask / Dash

- Native `async/await` — HX711 blocking reads run in a thread executor without blocking the server
- First-class SSE support via `sse-starlette`
- Auto-generated OpenAPI docs at `/docs`
- Significantly lighter than Dash (no Plotly, no React, no Werkzeug)

### Why SSE over WebSockets

SSE is one-directional (Pi → browser), which matches this use case exactly. Benefits:
- No handshake complexity; plain HTTP
- Browser auto-reconnects on disconnect (built-in)
- WebSockets would only be needed if the browser needed to stream data back to the Pi

---

## 3. File Structure

```
AnkleFlex/
├── Src/
│   ├── main.py                   # Entry point — wires hardware/emulation + starts server
│   ├── led.py                    # LED control (hardware GPIO + emulation no-op stubs)
│   ├── hardware/
│   │   ├── loadcell.py           # LoadCell class; accepts injected hx711= for emulation
│   │   └── button.py             # Physical button: long press → tare, quick → reboot
│   ├── emulation/
│   │   └── hx711.py              # EmulatedHX711 — mocks only _read() and reset()
│   └── server/
│       ├── app.py                # FastAPI app — SSE, tare, status, emulation endpoints
│       └── static/
│           ├── index.html        # Single-page UI
│           ├── style.css
│           ├── app.js            # Chart.js bar chart + EventSource SSE client
│           └── vendor/
│               └── chart.min.js # Vendored Chart.js 4.4.3 (no CDN)
├── docs/
│   ├── REQUIREMENTS.md
│   ├── ARCHITECTURE.md           # This file
│   └── CONTRIBUTING.md
├── Doc/                          # Hardware wiring diagrams (unchanged)
├── pyproject.toml
├── setup.sh                      # Pi deployment script (uv-based)
└── ReadMe.md
```

---

## 4. API Design

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves `index.html` |
| `GET` | `/static/*` | Serves static assets (CSS, JS, vendor) |
| `GET` | `/stream` | SSE endpoint — pushes state JSON at 2 Hz |
| `POST` | `/tare` | Recalibrates zero offset; resets session min/max |
| `GET` | `/status` | Returns current state as JSON (one-shot, no streaming) |
| `POST` | `/emulation/weight` | Sets simulated weight (emulation only; 403 otherwise) |
| `GET` | `/docs` | Auto-generated OpenAPI docs (FastAPI built-in) |
| *(v2)* `GET` | `/sessions` | List recorded sessions |
| *(v2)* `POST` | `/sessions/start` | Start recording a session |
| *(v2)* `POST` | `/sessions/stop` | Stop recording |
| *(v2)* `GET` | `/sessions/{id}/csv` | Download session as CSV |
| *(v2)* `GET/PUT` | `/settings` | Get / update settings |

### SSE payload format

```json
{
  "weight": 12.4,
  "min_weight": -3.1,
  "max_weight": 45.2,
  "emulation": false
}
```

Pushed at 2 Hz. `min_weight` may be negative (pull force). `emulation` controls whether the slider panel is shown in the browser.

---

## 5. Emulation Architecture

### Design principle: emulate at the lowest layer

Emulation replaces only the component that requires physical hardware — the HX711 ADC read. All application logic (offset arithmetic, tare, calibration, sensor loop) runs from the real `LoadCell` class unchanged. This guarantees that emulation exercises the same code paths as hardware.

### How it works

```
[hardware mode]                        [emulation mode]

LoadCell                               LoadCell
  └── hx711 = HX711(...)                 └── hx711 = EmulatedHX711(...)
        └── _read() → ADC int                  └── _read() → slider_kg × CALIBRATION_FACTOR
```

`EmulatedHX711._read()` inverts the weight formula:

```
# Hardware:   weight_kg = (raw - offset) / CALIBRATION_FACTOR
# Emulation:  raw       = weight_kg * CALIBRATION_FACTOR
```

`LoadCell.get_weight()` receives syntactically correct ADC counts and all arithmetic (including tare and calibration) produces identical results to hardware.

### Tare behaviour

**Tare sets the current load as the new zero reference.** The slider/physical reading is not altered — only the internal offset that `get_weight()` subtracts.

| Step | Slider (kg) | internal offset | `get_weight()` |
|---|---|---|---|
| Start | 0 | 0 | 0 kg |
| Slide to 5 | 5 | 0 | 5 kg |
| **Tare** | 5 | 5 × FACTOR (raw) | **0 kg** |
| Slide to 7 | 7 | unchanged | 2 kg |
| Slide to 3 | 3 | unchanged | −2 kg |

### Python gotcha: `0.0 == False`

The HX711 library returns `False` (not `None`, not `0`) on a failed read. Python evaluates `0.0 == False` as `True`, so `0.0 in (False, -1)` incorrectly rejects valid zero readings. All error checks in this codebase use `is not False` (identity) rather than `not in (False, -1)` (equality).
