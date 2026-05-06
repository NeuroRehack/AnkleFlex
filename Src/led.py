"""LED control and emulation for AnkleFlex."""

import logging

import time

logger = logging.getLogger("ankleflex.led")

try:
    import RPi.GPIO as GPIO
    EMULATION = False
    # Set the GPIO mode
    GPIO.setmode(GPIO.BCM)
    LED_GPIO = 26

    def init_led():
        """Initialize the LED GPIO pin."""
        GPIO.setup(LED_GPIO, GPIO.OUT)
        GPIO.output(LED_GPIO, GPIO.LOW)

    def turn_on_led():
        """Turn on the LED."""
        GPIO.output(LED_GPIO, GPIO.HIGH)

    def turn_off_led():
        """Turn off the LED."""
        GPIO.output(LED_GPIO, GPIO.LOW)

    def blink_led():
        """Blink the LED 10 times."""
        for _ in range(10):
            turn_on_led()
            time.sleep(0.1)
            turn_off_led()
            time.sleep(0.1)
        turn_on_led()

    def cleanup():
        """Clean up the LED GPIO pin."""
        GPIO.cleanup()
except (ImportError, ModuleNotFoundError):
    EMULATION = True

    def init_led():
        """Emulated LED init (noop)."""
        logger.info("[EMULATION] LED init (noop)")

    def turn_on_led():
        """Emulated LED on (noop)."""
        logger.info("[EMULATION] LED on (noop)")

    def turn_off_led():
        """Emulated LED off (noop)."""
        logger.info("[EMULATION] LED off (noop)")

    def blink_led():
        """Emulated LED blink (noop)."""
        logger.info("[EMULATION] LED blink (noop)")

    def cleanup():
        """Emulated LED cleanup (noop)."""
        logger.info("[EMULATION] LED cleanup (noop)")


if __name__ == "__main__":
    init_led()
    blink_led()
    cleanup()
