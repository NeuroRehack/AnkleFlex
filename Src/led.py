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
        try:
            GPIO.setup(LED_GPIO, GPIO.OUT)
            GPIO.output(LED_GPIO, GPIO.LOW)
            # Runtime hardware presence check: try to set pin high/low
            GPIO.output(LED_GPIO, GPIO.HIGH)
            GPIO.output(LED_GPIO, GPIO.LOW)
        except Exception as e:
            global EMULATION
            logger.warning(
                f"[LED] GPIO not detected or unresponsive: {e}. Falling back to emulation."
            )
            EMULATION = True

            # Redefine all functions to emulation versions
            def emu_init_led():
                logger.info("[EMULATION] LED init (noop)")

            def emu_turn_on_led():
                logger.info("[EMULATION] LED on (noop)")

            def emu_turn_off_led():
                logger.info("[EMULATION] LED off (noop)")

            def emu_blink_led():
                logger.info("[EMULATION] LED blink (noop)")

            def emu_cleanup():
                logger.info("[EMULATION] LED cleanup (noop)")

            globals()["init_led"] = emu_init_led
            globals()["turn_on_led"] = emu_turn_on_led
            globals()["turn_off_led"] = emu_turn_off_led
            globals()["blink_led"] = emu_blink_led
            globals()["cleanup"] = emu_cleanup

    def turn_on_led():
        GPIO.output(LED_GPIO, GPIO.HIGH)

    def turn_off_led():
        GPIO.output(LED_GPIO, GPIO.LOW)

    def blink_led():
        for _ in range(10):
            turn_on_led()
            time.sleep(0.1)
            turn_off_led()
            time.sleep(0.1)
        turn_on_led()

    def cleanup():
        GPIO.cleanup()
except (ImportError, ModuleNotFoundError):
    EMULATION = True

    def init_led():
        logger.info("[EMULATION] LED init (noop)")

    def turn_on_led():
        logger.info("[EMULATION] LED on (noop)")

    def turn_off_led():
        logger.info("[EMULATION] LED off (noop)")

    def blink_led():
        logger.info("[EMULATION] LED blink (noop)")

    def cleanup():
        logger.info("[EMULATION] LED cleanup (noop)")


if __name__ == "__main__":
    init_led()
    blink_led()
    cleanup()
