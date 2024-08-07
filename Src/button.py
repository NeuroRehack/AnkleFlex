"""
Script : button.py
Author : Sami Kaab
Date : 2024-07-23
Description : This script uses GPIO pins of the raspberry pi to detect a button press and print a message to the console.
The button should be connected to GPIO pin 4 and GND.
"""

import RPi.GPIO as GPIO
import time

GPIO.cleanup()
# Pin Definitions
button_pin = 17  # BOARD pin 11, BCM pin 17

class button:
    def __init__(self):
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Wait for button press
        print("Press the button!")
        GPIO.add_event_detect(button_pin, GPIO.BOTH, callback=self.button_callback, bouncetime=100)
        self.state = GPIO.input(button_pin)
        self.last_time_pressed = time.time()
        self.mode = -1
        self.modes = {0: "tare", 1 :"restart program", 2: "reboot",-1:"error"}
        self.last_mode = -1
        while True:
            if self.mode != self.last_mode:
                print(f"Mode: {self.modes[self.mode]}")
                self.last_mode = self.mode
            time.sleep(1)

    def button_callback(self, channel):
        print(".")
        dt = time.time() - self.last_time_pressed
        print(f"dt: {dt}")  
        if dt < 0.1:
            pass
        elif (dt < 1) and (self.mode == 1):
            self.mode = 2
        elif (dt < 1) and (self.mode == 0):
            self.mode = 1
        elif (dt > 1):
            self.mode = 0
        self.last_time_pressed = time.time()
        
        
            
            
if __name__ == "__main__":
    try:
        button()
    except KeyboardInterrupt:
        GPIO.cleanup()
        print("\nExiting program")
        exit()