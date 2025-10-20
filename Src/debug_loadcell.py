import time
from hx711v0_5_1 import HX711
import RPi.GPIO as GPIO

# GPIO pin configuration
LOADCELL_DOUT_PIN = 2  # GPIO 2 (Board pin 3)
LOADCELL_SCK_PIN = 3   # GPIO 3 (Board pin 5)

def main():
    hx = HX711(LOADCELL_DOUT_PIN,LOADCELL_SCK_PIN)
    
    hx.reset()
    print("Printing raw load cell readings every 0.5 seconds (Ctrl+C to stop):")
    count=0
    try:
        while True:
            if not(hx._ready()):
                print(hx._ready())    
            # if hx._ready():
            #     #raw_value = hx.get_raw_data()
            #     read_value = hx._read()
            #     count += 1
            #     print(f"[{count}]")
            #     #print(f"Raw value: {raw_value}")
            #     print(f"Read value: {read_value}")
            # time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nExiting...")
        hx.power_down()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
