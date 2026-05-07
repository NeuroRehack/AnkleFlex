# AnkleFlex -- Software Requirements

> **Status:** Approved -- April 2026
> **Branch:** `develop`

See also: [ARCHITECTURE.md](ARCHITECTURE.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

---

## 1. Project Context

AnkleFlex is a portable biofeedback device for ankle rehabilitation in clinical and research settings. A load cell (TAL220B via HX711 ADC) is connected to a Raspberry Pi 4B. The Pi reads force data continuously and serves a web interface accessible to any device on the same local network.

There is **no physical screen** on the Pi -- all interaction is through a browser on an external device.

### Key constraints

| Constraint | Detail |
|---|---|
| Portable | Pi hosts its own WiFi hotspot -- no hospital/external network |
| No internet | Hospital environment; no CDN links anywhere in the stack |
| No screen | Web-only UI; must be usable on a tablet at arm's length |
| No hardware during dev | All development done on Windows; emulation mode required |
| Clinical environment | Simple, reliable, patient-safe UI -- no developer tools visible |

---

## 2. Functional Requirements

### FR-01 · Real-time weight display

- The web UI **must** display the current weight reading from the load cell
- Updates **must** occur at ≥ 2 Hz (every 500 ms or faster)
- The display **must** show a vertical bar proportional to the current weight value
- The display **must** show persistent max and min reference lines from the current session
- The current weight value (number + unit) **must** be displayed in large text (≥ 48 px)
- The display **must** handle both positive (push) and negative (pull) force values

### FR-02 · Tare / reset

- The operator **must** be able to tare the device (set current load as new zero reference) via:
  - Physical button (long press > 1 s) on the Pi
  - A "Tare / Reset" button in the web UI
- Tare **must** recalibrate the zero reference so the current load reads as 0 kg
- Tare **must** reset the session min/max tracking
- Both methods **must** produce identical results

### FR-03 · Connection status

- The web UI **must** show a visible indicator of whether the SSE connection to the Pi is active

### FR-04 · Emulation mode *(development use only)*

- The full application **must** run on a Windows development machine with no hardware
- Emulation is activated by setting `ANKLEFLEX_EMULATE_LOADCELL=1`
- In emulation mode, the web UI **must** include a slider (range −100 to +100 kg) to manually set the simulated weight value
- The emulation slider **must not** appear in hardware (production) mode
- All other behaviour **must** be identical to hardware mode, including tare semantics

### FR-05 · Auto-start on Pi boot

- The application **must** start automatically when the Pi boots
- Implementation: `crontab @reboot` (current) or systemd service (preferred for v2)

### FR-06 · Session recording *(v2 -- future)*

- The system **should** be able to record a session of timestamped weight readings
- A session record **must** include: start time, end time, configured sample rate, raw readings array
- Sessions **must** persist to disk (survive Pi reboot)
- Sessions **must** be downloadable as CSV from the web UI

### FR-07 · Settings *(v2 -- future)*

- Target weight goal line (kg) -- displayed as a horizontal line on the chart
- Sample rate (Hz)
- Session / patient label (no PII stored on device)

---

## 3. Non-Functional Requirements

### NFR-01 · Reliability

- The application **must** recover from individual load cell read errors without crashing
- SSE disconnections **must** auto-reconnect (browser handles this natively)
- A Pi reboot **must** restore full operation without manual intervention

### NFR-02 · Performance

- First page load **must** complete in < 3 seconds on the local WiFi hotspot
- Weight update latency (sensor → screen) **must** be < 1 second at 2 Hz update rate
- The server **must** handle at least 5 simultaneous browser connections without degradation

### NFR-03 · Clinical safety / simplicity

- The patient-facing display **must not** expose developer tools, debug panels, or raw data controls
- The emulation panel **must not** appear in production (hardware) mode
- Primary weight value font size **must** be ≥ 48 px for tablet readability at arm's length
- No external URLs or links **must** be present in the patient UI

### NFR-04 · Portability

- The application **must** run identically on Raspberry Pi 4B and Raspberry Pi 5
- The application **must** run on Windows for development (emulation mode)
- Python version: **3.11** minimum; 3.12+ compatibility should be maintained

### NFR-05 · Maintainability

- Hardware interface (LoadCell, LED, Button) **must** be cleanly separated from server/UI logic
- Adding a new hardware component **must not** require changes to the web server code
- Switching between emulation and hardware mode **must** require only an environment variable change
