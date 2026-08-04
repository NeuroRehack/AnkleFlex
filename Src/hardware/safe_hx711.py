"""Crash-safe, instrumented wrapper around ``hx711`` (mpibpc-mroose 1.1.2.3).

The upstream ``HX711.get_raw_data()`` uses an unbounded ``while`` loop that only
terminates once it has collected the requested number of *valid* samples.  If
the chip stops responding (e.g. it slipped into power-down mode after a >60 us
clock glitch, so ``DOUT`` is stuck HIGH), no valid sample is ever produced and
the call loops forever.  Because that read runs inside a non-cancellable
thread-pool worker, repeated occurrences leak threads until the sensor loop
wedges permanently and only a restart recovers it.

``SafeHX711`` (a) bounds every loop so reads always return, and (b) records
diagnostics (per-read outcome, failure reason, reset timing) so field
drop-outs leave a usable trail in the log.
"""

import logging
import time

from hx711 import HX711

try:  # hx711 already requires RPi.GPIO, so this normally succeeds on the Pi.
    import RPi.GPIO as GPIO
except Exception:  # noqa: BLE001 - never let import-time issues break the app
    GPIO = None

logger = logging.getLogger("ankleflex.safe_hx711")

# How many read attempts to allow per requested sample before giving up.
_MAX_ATTEMPT_MULTIPLIER = 5
# Number of samples reset() tries to read back to confirm the chip is alive.
_RESET_SAMPLES = 3
# Settling delays for the power cycle (datasheet: ~400 ms to valid data).
_POWER_DOWN_SETTLE_S = 0.06
_POWER_UP_SETTLE_S = 0.4


class SafeHX711(HX711):
    """``hx711.HX711`` with every internal loop bounded and reads instrumented."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialise diagnostics counters, then the underlying HX711.

        Counters are set up *before* ``super().__init__`` because the base
        constructor performs a read (via the channel/gain setters) that flows
        through our instrumented ``_read``.
        """
        self._reads_total = 0
        self._reads_ok = 0
        self._reads_failed = 0
        self._fail_streak = 0
        self._max_fail_streak = 0
        self._fail_reasons: dict[str, int] = {}
        self._last_fail_reason: str | None = None
        self._last_value = None
        self._resets = 0
        super().__init__(*args, **kwargs)

    def _read(self, max_tries: int = 40):
        """Instrumented read: delegates to the base, then records the outcome.

        Classification of a failed read is done *after* ``super()._read()``
        returns, so it never adds latency inside the timing-critical bit-bang
        window (which would itself risk the 60 us power-down glitch).
        """
        result = super()._read(max_tries=max_tries)
        self._reads_total += 1
        if result is False:
            self._reads_failed += 1
            self._fail_streak += 1
            self._max_fail_streak = max(self._max_fail_streak, self._fail_streak)
            reason = "unknown"
            if GPIO is not None:
                try:
                    # DOUT still HIGH => chip never signalled "data ready",
                    # which is the power-down / not-connected signature.  DOUT
                    # LOW at this point points at a timing glitch or invalid
                    # (saturated) sample instead.
                    reason = (
                        "dout_stuck_high"
                        if GPIO.input(self._dout) == 1
                        else "timing_or_invalid"
                    )
                except Exception:  # noqa: BLE001
                    reason = "probe_error"
            self._last_fail_reason = reason
            self._fail_reasons[reason] = self._fail_reasons.get(reason, 0) + 1
        else:
            self._reads_ok += 1
            self._fail_streak = 0
            self._last_value = result
        return result

    def get_raw_data(self, times: int = 5):
        """Read up to ``times`` valid samples with a hard attempt cap.

        Unlike the base implementation this never loops forever: after
        ``times * _MAX_ATTEMPT_MULTIPLIER`` attempts it returns whatever valid
        samples were collected, which may be fewer than ``times`` (or empty).
        """
        self._validate_measure_count(times)
        data_list = []
        attempts = 0
        max_attempts = max(times * _MAX_ATTEMPT_MULTIPLIER, times)
        while len(data_list) < times and attempts < max_attempts:
            attempts += 1
            data = self._read()
            if data not in [False, -1]:
                data_list.append(data)
        if len(data_list) < times:
            logger.warning(
                "[SafeHX711] get_raw_data collected %d/%d samples in %d attempts "
                "(last_fail=%s) - chip may be unresponsive",
                len(data_list),
                times,
                attempts,
                self._last_fail_reason,
            )
        return data_list

    def reset(self) -> bool:
        """Bounded power-cycle. Returns True if the chip responds afterwards.

        Never raises and never hangs, so it is safe to call from a recovery
        path when the HX711 has slipped into power-down mode.
        """
        self._resets += 1
        t0 = time.perf_counter()
        try:
            self.power_down()
            time.sleep(_POWER_DOWN_SETTLE_S)
            self.power_up()
            time.sleep(_POWER_UP_SETTLE_S)
            data = self.get_raw_data(_RESET_SAMPLES)
        except Exception as exc:  # noqa: BLE001 - recovery must not propagate
            logger.error(
                "[SafeHX711] reset() #%d raised after %.3fs: %s",
                self._resets,
                time.perf_counter() - t0,
                exc,
            )
            return False
        dur = time.perf_counter() - t0
        ok = len(data) > 0
        logger.log(
            logging.INFO if ok else logging.WARNING,
            "[SafeHX711] reset() #%d %s in %.3fs (got %d/%d samples, last_fail=%s)",
            self._resets,
            "OK - chip responding" if ok else "FAILED - still unresponsive",
            dur,
            len(data),
            _RESET_SAMPLES,
            self._last_fail_reason,
        )
        return ok

    def stats_snapshot(self) -> dict:
        """Return a copy of the running read/reset diagnostics counters."""
        return {
            "reads_total": self._reads_total,
            "reads_ok": self._reads_ok,
            "reads_failed": self._reads_failed,
            "fail_streak": self._fail_streak,
            "max_fail_streak": self._max_fail_streak,
            "fail_reasons": dict(self._fail_reasons),
            "last_fail_reason": self._last_fail_reason,
            "last_value": self._last_value,
            "resets": self._resets,
        }
