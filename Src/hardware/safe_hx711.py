"""Crash-safe wrapper around the ``hx711`` library (mpibpc-mroose 1.1.2.3).

The upstream ``HX711.get_raw_data()`` uses an unbounded ``while`` loop that
only terminates once it has collected the requested number of *valid* samples.
If the chip stops responding (e.g. it slipped into power-down mode after a
>60 us clock glitch, so ``DOUT`` is stuck HIGH), no valid sample is ever
produced and the call loops forever.  Because that read runs inside a
non-cancellable thread-pool worker, repeated occurrences leak threads until the
sensor loop wedges permanently and only a restart recovers it.

``SafeHX711`` overrides the two unbounded entry points so every read is
guaranteed to return in bounded time:

* ``get_raw_data()`` - capped number of attempts; returns whatever it managed
  to collect (possibly an empty list) instead of spinning forever.  This also
  neutralises the re-entrant call the base class makes from
  ``_set_channel_gain()`` (it dispatches through ``self.get_raw_data``).
* ``reset()`` - performs a bounded power-down/power-up cycle with proper
  settling and never raises or hangs; returns ``True`` only if the chip
  produced at least one valid sample afterwards.
"""

import logging
import time

from hx711 import HX711

logger = logging.getLogger("ankleflex.safe_hx711")

# How many read attempts to allow per requested sample before giving up.
_MAX_ATTEMPT_MULTIPLIER = 5
# Number of samples reset() tries to read back to confirm the chip is alive.
_RESET_SAMPLES = 3
# Settling delays for the power cycle (datasheet: ~400 ms to valid data).
_POWER_DOWN_SETTLE_S = 0.06
_POWER_UP_SETTLE_S = 0.4


class SafeHX711(HX711):
    """``hx711.HX711`` with every internal loop bounded so reads cannot hang."""

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
                "(chip may be unresponsive)",
                len(data_list),
                times,
                attempts,
            )
        return data_list

    def reset(self) -> bool:
        """Bounded power-cycle. Returns True if the chip responds afterwards.

        Never raises and never hangs, so it is safe to call from a recovery
        path when the HX711 has slipped into power-down mode.
        """
        try:
            self.power_down()
            time.sleep(_POWER_DOWN_SETTLE_S)
            self.power_up()
            time.sleep(_POWER_UP_SETTLE_S)
            data = self.get_raw_data(_RESET_SAMPLES)
        except Exception as exc:  # noqa: BLE001 - recovery must not propagate
            logger.error("[SafeHX711] reset() failed: %s", exc)
            return False
        ok = len(data) > 0
        if ok:
            logger.info("[SafeHX711] reset() ok - chip responding")
        else:
            logger.warning("[SafeHX711] reset() completed but chip still unresponsive")
        return ok
