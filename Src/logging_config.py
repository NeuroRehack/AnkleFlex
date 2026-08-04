"""Logging configuration for AnkleFlex.

Provides two sinks so we always have a record to work off of when debugging
field issues (like the intermittent load-cell drop-outs):

* A console handler at ``ANKLEFLEX_LOG_LEVEL`` (default ``INFO``).
* A rotating file handler that always captures at least ``INFO`` (and full
  ``DEBUG`` when ``ANKLEFLEX_HX711_DEBUG`` is set), so a persistent log survives
  across a session and can be pulled off the Pi afterwards.

Environment variables
----------------------
ANKLEFLEX_LOG_LEVEL    Console log level (DEBUG/INFO/WARNING/...). Default INFO.
ANKLEFLEX_LOG_FILE     Path to the log file. Default: <repo>/logs/ankleflex.log.
                       Set to an empty string to disable file logging.
ANKLEFLEX_HX711_DEBUG  Raise the file handler and the hx711 library logger to
                       DEBUG so the library's own per-read failure reasons
                       ("not ready after 40 trials", "took longer than 60us",
                       "Invalid data detected") are recorded. Verbose, but the
                       rotating file keeps it size-bounded. DEFAULT: ON while we
                       are diagnosing the field drop-outs. Set to 0/false/no/off
                       to quiet it down.
ANKLEFLEX_LOG_MAX_BYTES  Max size of the active log file before it rolls over.
                         Default 5000000 (5 MB).
ANKLEFLEX_LOG_BACKUPS    How many rotated files to keep. Default 5. Total disk
                         use is bounded by MAX_BYTES * (BACKUPS + 1).
"""

import logging
import logging.handlers
import os
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

# Debug logging for the load cell defaults ON while we chase the field
# drop-outs, so a freshly-booted Pi captures the diagnostics without anyone
# having to remember to export an env var. Flip ANKLEFLEX_HX711_DEBUG=0 to
# quiet it once the issue is resolved.
_DEFAULT_HX711_DEBUG = True
_DEFAULT_MAX_BYTES = 5_000_000  # 5 MB per file
_DEFAULT_BACKUPS = 5  # -> ~30 MB total worst case


def _envflag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def _envint(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _default_log_file() -> str:
    # Src/logging_config.py -> repo root is two levels up.
    return str(Path(__file__).resolve().parent.parent / "logs" / "ankleflex.log")


def setup_logging() -> None:
    """Configure root logging with console + rotating file handlers."""
    console_level_name = os.environ.get("ANKLEFLEX_LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_name, logging.INFO)
    hx711_debug = _envflag("ANKLEFLEX_HX711_DEBUG", default=_DEFAULT_HX711_DEBUG)
    max_bytes = _envint("ANKLEFLEX_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES)
    backups = _envint("ANKLEFLEX_LOG_BACKUPS", _DEFAULT_BACKUPS)

    # ANKLEFLEX_LOG_FILE unset -> default path; set-but-empty -> disabled.
    log_file = os.environ.get("ANKLEFLEX_LOG_FILE")
    if log_file is None:
        log_file = _default_log_file()

    # Millisecond-precision timestamps matter here: the failure is a sub-second
    # timing glitch, so we want to see exactly when reads slow down / drop out.
    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    # Idempotent: clear any handlers a previous setup (or basicConfig) installed.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    # Let handlers do the filtering; the root passes everything through.
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_enabled = bool(log_file)
    if file_enabled:
        file_level = logging.DEBUG if hx711_debug else logging.INFO
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            file_handler.setLevel(file_level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            file_enabled = False
            logging.getLogger("ankleflex.logging").warning(
                "File logging disabled - could not open %s: %s", log_file, exc
            )

    # The hx711 library logs its per-read failure reasons via the root logger at
    # DEBUG. Keep those out of the way unless explicitly requested.
    logging.getLogger("hx711").setLevel(logging.DEBUG if hx711_debug else logging.INFO)

    log = logging.getLogger("ankleflex.logging")
    cap_mb = max_bytes * (backups + 1) / 1_000_000
    log.info(
        "Logging configured: console=%s, file=%s, hx711_debug=%s, "
        "rotation=%.1fMB x %d (max ~%.0fMB on disk)",
        console_level_name,
        log_file if file_enabled else "disabled",
        hx711_debug,
        max_bytes / 1_000_000,
        backups,
        cap_mb,
    )
