import time
from hx711 import HX711
import RPi.GPIO as GPIO

# GPIO pin configuration
LOADCELL_DOUT_PIN = 2  # GPIO 2 (Board pin 3)
LOADCELL_SCK_PIN = 3   # GPIO 3 (Board pin 5)

def main():
    hx = HX711(
        dout_pin=LOADCELL_DOUT_PIN,
        pd_sck_pin=LOADCELL_SCK_PIN,
        channel='A',
        gain=64
    )
    hx.reset()
    print("Printing raw load cell readings every 0.5 seconds (Ctrl+C to stop):")
    try:
        while True:
            value = hx._read()
            print(f"Raw value: {value}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nExiting...")
        hx.power_down()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
