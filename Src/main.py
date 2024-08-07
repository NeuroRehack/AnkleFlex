# create a dashplotly app to visualize the data as a bar chart
# pip install dash pandas RPi.GPIO hx711 
import dash 
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.express as px
import time
import RPi.GPIO as GPIO # pip
from hx711 import HX711  # Make sure to install the hx711 library
import threading
import queue
import os
import logging
from tqdm import tqdm
from flask import request
import led

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()


def run_with_timeout(func, timeout):
    q = queue.Queue()

    def wrapper():
        result = func()
        q.put(result)

    thread = threading.Thread(target=wrapper)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        return -1
    else:
        return q.get()


# GPIO pin configuration
LOADCELL_DOUT_PIN = 2  # GPIO 2 Board pin 3
LOADCELL_SCK_PIN = 3  # GPIO 3 Board pin 5
BUTTON_PIN = 17  # GPIO 17 Board pin 11

# Calibration factor
CALIBRATION_FACTOR = -1554  # This value is obtained using the calibration script

# GPIO.setwarnings(False)

# set log level for webapp
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

class LoadCell():
    def __init__(self):
        print('Initializing LoadCell...')
        self.hx711 = HX711(
            dout_pin=LOADCELL_DOUT_PIN,
            pd_sck_pin=LOADCELL_SCK_PIN,
            channel='A',
            gain=64
        )
        self.ready = False
        
    def initialize(self):
        print('Calibrating...')
        state = run_with_timeout(self.hx711.reset,15)
        if state == -1:
            print('Error initializing')
            led.turn_off_led()
            self.cleanup()
            os.system('/home/ankleflex/venv/bin/python /home/ankleflex/main.py')
            exit()
            return
        
        self.offset = run_with_timeout(self.get_offset, 15)
        if self.offset == -1:
            print('Error initializing')
            led.turn_off_led()
            self.cleanup()
            os.system('/home/ankleflex/venv/bin/python /home/ankleflex/main.py')
            exit()
            return
        

    def get_offset(self, times=5):
        measures = []
        while len(measures) < times:
            data = self.hx711._read()
            if data not in [False, -1]:
                measures.append(data)
                print('*'*len(measures))
        return sum(measures) / len(measures)

    def get_weight(self):
        measures = self.hx711._read()
        return (measures - self.offset) / CALIBRATION_FACTOR

    def cleanup(self):
        self.hx711.power_down()
        GPIO.cleanup()
            
            
class Button():
    def __init__(self,loadcell):
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Wait for button press
        print("Press the button!")
        GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=self.button_callback, bouncetime=100)
        self.state = GPIO.input(BUTTON_PIN)
        self.last_time_pressed = time.time()
        self.mode = -1
        self.modes = {0: "tare", 1 :"reboot",-1:"error"}
        self.last_mode = -1
        self.last_mode_change = time.time()
        self.loadcell = loadcell
        while True:
            if self.mode != self.last_mode:
                print(f"Mode: {self.modes[self.mode]}")
                self.last_mode = self.mode
                if self.mode == 0:
                    ledBlinkThread = threading.Thread(target=led.blink_led)
                    ledBlinkThread.start()
                    self.loadcell.offset = self.loadcell.get_offset()
                    ledBlinkThread.join()
                elif self.mode == 1:
                    led.turn_off_led()
                    os.system("sudo reboot")
                    print('Rebooting...')
            time.sleep(min(1, time.time() - self.last_mode_change))

    def button_callback(self, channel):
        print(".")
        dt = time.time() - self.last_time_pressed
        print(f"dt: {dt}")  
        if dt < 0.1:
            pass
        elif (dt < 1):
            self.mode = 1
        elif (dt > 1):
            self.last_mode = -1
            self.mode = 0
        self.last_time_pressed = time.time()

maxWeight = 0.00000001
minWeight = -0.00000001
weight = 0

app = dash.Dash(__name__)

app.layout = html.Div([
    dcc.Interval(id='interval', interval=500, n_intervals=0),
    dcc.Graph(id='graph', style={'height': '90vh', 'width': '98vw'})  # Adjust the graph size here
], style={'height': '100vh', 'width': '100vw', 'display': 'flex', 'justify-content': 'center', 'align-items': 'center'})  # This makes the div fill the window

@app.callback(
    Output('graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_graph(n):
    global loadcell, maxWeight, minWeight
    data = loadcell.get_weight()
    if data not in [False, -1]:
        weight = data
    minWeight = min(minWeight, weight)
    maxWeight = max(maxWeight, weight)

    fig = px.bar(x=['Weight'], y=[weight], title='Weight (kg)', range_y=[minWeight, maxWeight])
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))  # Remove margins to fill the graph area
    return fig

        

if __name__ == '__main__':
    led.init_led()
    led.turn_on_led()
    try:
        print('Starting LoadCell...')
        loadcell = LoadCell()
        print('Starting Button...')
        buttonThread = threading.Thread(target=Button, args=(loadcell,))
        loadcell.initialize()
        buttonThread.daemon = True
        buttonThread.start()
        
        print('Starting app...')
        app.run_server(debug=False, host='0.0.0.0', port=8050)
    except :
        buttonThread.join()
        print('Exiting...')
        loadcell.cleanup()
        led.turn_off_led()
        shutdown_server()
        exit()