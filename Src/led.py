import os
import time

EMULATE = os.environ.get("ANKLEFLEX_EMULATE_LOADCELL", "0") == "1"

if not EMULATE:
    import RPi.GPIO as GPIO
    # Set the GPIO mode
    GPIO.setmode(GPIO.BCM)
    LED_GPIO = 26

    def init_led():
        GPIO.setup(LED_GPIO, GPIO.OUT)
        GPIO.output(LED_GPIO, GPIO.LOW)

    def turn_on_led():
        GPIO.output(LED_GPIO, GPIO.HIGH)

    def turn_off_led():
        GPIO.output(LED_GPIO, GPIO.LOW)

    def blink_led():
        for i in range(10):
            turn_on_led()
            time.sleep(0.1)
            turn_off_led()
            time.sleep(0.1)
        turn_on_led()

    def cleanup():
        GPIO.cleanup()

else:
    def init_led():
        print("[EMULATION] LED init (noop)")

    def turn_on_led():
        print("[EMULATION] LED on (noop)")

    def turn_off_led():
        print("[EMULATION] LED off (noop)")

    def blink_led():
        print("[EMULATION] LED blink (noop)")

    def cleanup():
        print("[EMULATION] LED cleanup (noop)")

if __name__ == '__main__':
    init_led()
    blink_led()
    cleanup()
