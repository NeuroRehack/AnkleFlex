# AnkleFlex -- Contributing

See also: [REQUIREMENTS.md](REQUIREMENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 1. Development Setup

```powershell
# Clone and install (Windows, no hardware)
git clone https://github.com/NeuroRehack/AnkleFlex
cd AnkleFlex
uv sync

# Run — emulation is automatic when hardware libraries are not present
.\.venv\Scripts\python.exe Src/main.py
# → open http://localhost:8000/
```

On Raspberry Pi with hardware:

```bash
uv sync --extra hardware
python Src/main.py
```

---

## 2. Testing Strategy

### Stage 1 · Development on Windows (no hardware) -- ✅ complete

- Run `python Src/main.py` — emulation is automatic on Windows (hardware libraries not present)
- Use the emulation slider (−100 to +100 kg) in the web UI to test weight changes
- Verify: SSE stream connects, chart updates, tare button recalibrates zero, min/max lines track
- Verify: moving slider to negative values shows bar below zero; MIN line appears
- Test with multiple browser tabs open simultaneously

### Stage 2 · Raspberry Pi without load cell hardware -- ⬜ pending

- SSH into Pi, clone repo, run `uv sync`
- Start the app — if no load cell is wired, emulation is detected automatically
- Connect via browser on the hotspot (`http://ankleflex.local:8000/` or `http://10.42.0.1:8000/`)
- Verify: SSE stream reaches remote browser, chart works, tare button works
- Verify: auto-start after `sudo reboot`

### Stage 3 · Raspberry Pi with full hardware -- ⬜ pending (requires physical device)

- Verify: load cell reads, LED status indicator, physical button tare, physical button reboot
- Verify: emulation panel does **not** appear in the UI

---

## 3. Known Pitfalls

### P-01 · HX711 is a blocking library

`hx711._read()` blocks the calling thread for up to ~100 ms. In an async FastAPI server this **must** be wrapped:

```python
raw = await asyncio.get_running_loop().run_in_executor(None, loadcell.get_weight)
```

Calling it directly in a coroutine will freeze the entire event loop and stall all SSE streams.

### P-02 · mDNS hostname resolution

`ankleflex.local` relies on mDNS (Bonjour on macOS/iOS, Avahi on Linux, built-in on Windows 10+). Some **Android devices and corporate-managed Windows machines block mDNS**. Always document the raw IP fallback (`http://10.42.0.1:8000/`).

### P-03 · SSE client disconnect handling

Browsers auto-reconnect SSE after ~3 seconds. The server's async generator **must** check `request.is_disconnected()` to clean up on client disconnect. Unhandled disconnects can silently accumulate tasks.

### P-04 · GPIO permissions on Pi

`rpi-lgpio` requires either root or membership in the `gpio` group. The autostart crontab entry **must** run as the correct user. Verify with `groups ankleflex` on the Pi.

### P-05 · Single Uvicorn worker only

Running `uvicorn --workers N` (N > 1) creates N separate processes, each spawning their own GPIO reader thread -- they will fight over the HX711 pins. Always run with a **single worker**.

### P-06 · Pi hotspot IP range

`nmcli` hotspot assigns clients IPs in `10.42.x.x` by default. The Pi itself is `10.42.0.1`. The app binds to `0.0.0.0:8000`. Access from clients: `http://10.42.0.1:8000/` (raw IP) or `http://ankleflex.local:8000/` (mDNS).

### P-07 · Chart.js must be vendored

The Pi hotspot has **no internet access**. `chart.min.js` is stored in `Src/server/static/vendor/` and served by FastAPI's `StaticFiles`. Do not add any CDN links.

### P-08 · Pi 3B/3B+ performance

On Pi 4B, a single Uvicorn worker handles this load easily. On Pi 3B/3B+ it should work but has not been tested. Avoid any synchronous operations in route handlers.

### P-09 · `0.0 == False` in Python

The HX711 library signals a failed read by returning `False`. Python's `==` operator considers `0.0 == False` to be `True`, so `if value in (False, -1)` will silently discard legitimate zero readings. Always use `if value is False` (identity check). See [ARCHITECTURE.md](ARCHITECTURE.md#python-gotcha-00--false) for detail. See also [../../TECHSPEC.md](../../TECHSPEC.md) for the full design rationale.

---

## 4. Migration History (Dash → FastAPI)

- [x] Design and document architecture
- [x] Add `fastapi`, `uvicorn[standard]`, `sse-starlette` to `pyproject.toml`; remove `dash`, `plotly`, `pandas`
- [x] Create `Src/hardware/` -- `LoadCell` with hx711 injection, `Button` with `on_tare` callback
- [x] Create `Src/emulation/hx711.py` -- `EmulatedHX711` mocks only `_read()` and `reset()`
- [x] Create `Src/server/app.py` -- FastAPI app with SSE, tare, status, emulation endpoints
- [x] Write `Src/server/static/` -- `index.html`, `style.css`, `app.js` (Chart.js + EventSource)
- [x] Vendor `chart.min.js` into `Src/server/static/vendor/`
- [x] Rewrite `Src/main.py` as slim entry point
- [x] Rewrite `setup.sh` for uv-based Pi deployment
- [x] Fix tare: recalibrate HX711 offset so current load becomes new zero
- [x] Fix emulation slider range: −100 to +100 kg (bidirectional force)
- [x] Fix chart Y-axis: handle negative values from initial render
- [x] Test Stage 1 (Windows emulation) ✅
- [ ] Test Stage 2 (Pi, emulation mode)
- [ ] Test Stage 3 (Pi, full hardware) -- requires physical device
