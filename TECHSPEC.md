# AnkleFlex — Technical Specification

> **Status:** Current — April 2026 · Branch: `develop`

---

## Architecture Overview

AnkleFlex is a real-time ankle-force biofeedback device for clinical rehabilitation. A Raspberry Pi 4B reads a TAL220B load cell via an HX711 ADC and serves a live bar-chart UI over a self-hosted WiFi hotspot. Clinicians and patients connect via browser — no app install, no internet required.

**Stack:**
- Backend: FastAPI + Uvicorn (ASGI, single worker)
- Real-time transport: Server-Sent Events (SSE) at 2 Hz
- Frontend: Vanilla HTML/CSS/JS + vendored Chart.js 4.x (no build step, works offline)
- Hardware abstraction: dependency injection — the real `LoadCell` class accepts an optional `hx711=` argument; in emulation mode an `EmulatedHX711` is injected instead of opening GPIO

**Top-level layout:**

```
Src/
  main.py            ← entry point / wiring
  led.py             ← platform-conditional LED module
  hardware/          ← Pi-specific peripherals
  emulation/         ← mock ADC for development
  server/            ← FastAPI app + static assets
docs/                ← architecture / requirements / contributing
Doc/                 ← original wiring diagrams (HTML)
pyproject.toml       ← uv-managed dependencies
```

---

## Module Responsibilities

| Module | Owns | Does NOT own |
|---|---|---|
| `main.py` | Process startup: mode selection, object construction, wiring, Uvicorn launch | No business logic; does not own the FastAPI app object |
| `server/app.py` | FastAPI app, all HTTP routes, background sensor loop, shared `_state` dict | Does not read hardware directly; delegates through the injected `LoadCell` |
| `hardware/loadcell.py` | HX711 communication, offset arithmetic, weight formula, tare | GPIO pin setup (done by `RPi.GPIO` internally); LED / button unaware |
| `hardware/button.py` | GPIO interrupt handling, tare-vs-reboot gesture detection, LED blink on tare | Does not update `_state`; calls `on_tare` callback (supplied by `main.py`) |
| `emulation/hx711.py` | Synthetic ADC: converts a kg slider value to raw counts using the same `CALIBRATION_FACTOR` | Does not emulate GPIO, LED, or button |
| `led.py` | Platform-conditional LED control: real GPIO on Pi, print-stubs in emulation | Not a class; module-level functions selected at import time via `EMULATE` flag |
| `server/static/app.js` | SSE client, Chart.js bar chart, DOM updates, tare + emulation-weight API calls | No server logic; does not persist state |
| `server/static/index.html` | Single-page shell, emulation panel (hidden until SSE `emulation=true`) | No inline JS beyond event handlers; all logic in `app.js` |

---

## Key Data Flows

### 1. Live weight → browser chart (primary path)

1. **`_sensor_loop()`** (`server/app.py`) runs as an asyncio Task from Uvicorn startup.
2. Every 0.5 s it calls `loop.run_in_executor(None, _loadcell.get_weight)` — blocking HX711 read is offloaded to a thread so the async event loop never blocks.
3. Result updates `_state` dict (weight, min, max). The dict is a plain Python `dict`; GIL protects concurrent reads/writes (single worker only).
4. Each SSE client in `/stream` reads `_state` and yields `json.dumps(_state)` every 0.5 s.
5. Browser `EventSource` receives the JSON, updates `appState`, re-draws the Chart.js bar and reference lines.

### 2. Tare — hardware button path

1. Physical button press held > 1 s triggers `Button._callback()` (GPIO interrupt, separate thread).
2. `Button.run()` poll detects mode change → calls `_do_tare()`.
3. `_do_tare()` starts LED blink in a daemon thread, calls `loadcell.tare()` (re-samples HX711 offset), then calls `on_tare` callback.
4. `on_tare` is `do_tare` from `server/app.py`, which zeroes `_state["weight/min/max"]`.

### 3. Tare — browser button path

1. `fetch("/tare", {method:"POST"})` in `app.js`.
2. `/tare` handler in `app.py` calls `loop.run_in_executor(None, _loadcell.tare)` (thread), then `do_tare()`.
3. Same `do_tare()` zeroes `_state`. No LED blink (browser-initiated tare does not trigger the LED).

---

## Dependencies

| Dependency | Purpose | Notes |
|---|---|---|
| `fastapi >=0.110.0` | HTTP framework + OpenAPI | Chosen for native async, first-class SSE, and low overhead on Pi |
| `uvicorn[standard] >=0.29.0` | ASGI server | `[standard]` pulls in `uvloop` + `httptools` for Pi performance. **Single worker only** — shared `_state` dict is not multiprocess-safe |
| `sse-starlette >=1.6.0` | `EventSourceResponse` helper | Handles SSE framing and client-disconnect detection; avoids hand-rolling chunked responses |
| `hx711 ==1.1.2.3` | HX711 ADC Python driver | Pinned — the `_read()` private method is called directly; the API is not stable across versions |
| `rpi-lgpio ==0.6` | GPIO backend for Pi 5 compatibility | Replaces `RPi.GPIO` package name; `import RPi.GPIO` still works but routes through `lgpio` |
| `Chart.js 4.4.3` (vendored) | Bar chart in browser | Vendored under `static/vendor/` because the Pi has no internet access at runtime |

---

## Conventions & Patterns

### Emulation via constructor injection
The emulation boundary is at the HX711 level, not the `LoadCell` level. `EmulatedHX711` exposes exactly `_read()` and `reset()` — the private interface used by `LoadCell`. All offset arithmetic, calibration, and tare logic run identically in both modes. Adding a new emulation path should follow the same pattern: inject a stub at the lowest possible level.

### Deferred GPIO imports
All `import RPi.GPIO` and `import hx711` statements are inside `__init__` methods or guarded by `if not EMULATE:`. This allows `hardware/loadcell.py`, `hardware/button.py`, and `led.py` to be imported on Windows/macOS without error.

### Single shared `_state` dict
`_state` in `app.py` is a module-level dict mutated by the sensor loop and read by SSE generators. This works because Uvicorn runs with one worker (GIL serialises dict access). Any move to multiple workers would break this.

### `is not False` error checks
The `hx711` library returns the boolean `False` (not `None`, not `0`) on a read failure. All error guards use `raw is not False` or `raw is False`. Using `== 0.0` or truthiness checks would silently drop real zero-force readings.

### Blocking calls in async context
Any call that touches hardware (HX711 read, tare, reset) is always wrapped in `loop.run_in_executor(None, ...)`. This is enforced for both hardware and emulation paths.

### LED module pattern
`led.py` is not a class. It defines a set of module-level functions and selects implementations at import time with `if not EMULATE:`. This was chosen for simplicity — the LED has no internal state that would benefit from encapsulation.

### No CDN usage
All browser assets are served from `/static/`. `chart.min.js` is vendored. The Pi hotspot has no WAN access.

---

## Non-Obvious Design Decisions

**`CALIBRATION_FACTOR = -1554` is negative.**
The TAL220B load cell is wired such that increasing force produces decreasing raw ADC counts. The negative factor corrects this inversion. Do not "fix" it to positive.

**`EmulatedHX711._read()` returns `weight_kg * CALIBRATION_FACTOR` with offset=0.**
At startup `LoadCell.initialize()` calls `get_offset()` which calls `_read()` several times with no weight applied. Because the slider starts at 0 kg, the synthetic offset is 0 and `get_weight()` later yields `(raw - 0) / CALIBRATION_FACTOR = weight_kg` exactly. If the slider were non-zero at startup, the emulation would behave like real hardware with a non-zero tare load.

**`_run_with_timeout` uses a daemon thread, not `asyncio.wait_for`.**
The HX711 library is synchronous and cannot be cancelled. If the chip hangs, the only safe recovery is to let the thread die with the process. The 15 s timeout causes `initialize()` to raise `RuntimeError` fast rather than hanging the boot sequence forever.

**Button gesture uses a mode integer (`-1 / 0 / 1`), not an event queue.**
The GPIO callback only sets `_mode`; `run()` polls for changes. This avoids race conditions between the interrupt thread and the action thread: the action is always executed synchronously inside `run()`, never from the interrupt context.

**`do_tare()` in `app.py` is separate from `loadcell.tare()`.**
`loadcell.tare()` recalibrates the ADC zero reference. `do_tare()` resets the session `min_weight`/`max_weight` displayed in the UI. The button path calls both; the browser path calls both via the `/tare` endpoint. Keeping them separate allows the ADC to be re-zeroed without resetting the session stats (not currently exposed, but the separation is intentional).

**Emulation slider range is −100 to 100 kg.**
The physical load cell is rated to 5 kg. The extended slider range exists so developers can test chart scaling, negative-force rendering, and edge-case min/max tracking without being constrained to realistic values.

**`app.py` creates the FastAPI `app` object at module import time, before `configure()` is called.**
Uvicorn needs the `app` object reference, but `_loadcell` is not yet known at import. `configure()` sets the module-level `_loadcell` and `_emulate` before `uvicorn.run()` is called. This is safe because only one worker is ever started.

**`led.py` re-reads `ANKLEFLEX_EMULATE_LOADCELL` independently from `main.py`.**
Both `main.py` and `led.py` check the env var at their own import time. This means `led.py` can be used standalone (e.g., `python led.py`) and still behave correctly without going through `main.py`.

---

## File Index

`Src/main.py` — entry point; reads env var, constructs all objects, wires them together, starts Uvicorn.

`Src/led.py` — platform-conditional LED control; emulation stubs are no-op print calls.

`Src/hardware/loadcell.py` — `LoadCell` class; owns HX711 communication, offset/calibration arithmetic, tare; accepts injected stub for emulation.

`Src/hardware/button.py` — `Button` class; owns GPIO interrupt setup and long-press/double-press gesture detection for tare and reboot.

`Src/emulation/hx711.py` — `EmulatedHX711`; drop-in ADC stub that converts a kg value to synthetic raw counts.

`Src/emulation/__init__.py` — package marker; no exports.

`Src/hardware/__init__.py` — package marker; no exports.

`Src/server/__init__.py` — package marker; no exports.

`Src/server/app.py` — FastAPI application; owns all HTTP routes, SSE sensor loop, shared `_state` dict, and `configure`/`do_tare` public functions called by `main.py`.

`Src/server/static/index.html` — single-page UI shell; emulation panel is hidden by default.

`Src/server/static/app.js` — SSE client, Chart.js bar chart with min/max reference lines, tare and emulation-weight API calls.

`Src/server/static/style.css` — UI styles.

`Src/server/static/vendor/chart.min.js` — vendored Chart.js 4.4.3; served offline from the Pi.

`pyproject.toml` — `uv`-managed project metadata; `hardware` optional extra installs Pi-only GPIO packages.

`setup.sh` — Pi deployment script (installs `uv`, syncs dependencies with `--extra hardware`, configures crontab autostart).

`docs/ARCHITECTURE.md` — narrative architecture documentation (hardware table, stack rationale, API table, network topology).

`docs/REQUIREMENTS.md` — functional and non-functional requirements.

`docs/CONTRIBUTING.md` — contributor guide including manual test stages.
