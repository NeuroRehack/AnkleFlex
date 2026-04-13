# AnkleFlex — Dash/Plotly force-feedback visualiser
# Runs on Raspberry Pi (real hardware) or any desktop (emulation mode).
import sys
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import plotly.express as px
import time
import threading
import queue
import os
import logging
from flask import request

# Detect whether we are running on a Raspberry Pi.
try:
    import RPi.GPIO as GPIO
    from hx711 import HX711
    IS_PI = True
except (ImportError, RuntimeError):
    IS_PI = False

from emulated_hx711 import EmulatedHX711

# Conditionally import led — only available on Pi.
if IS_PI:
    import led
else:
    class led:  # noqa: N801 — stub so call-sites don't need guards
        @staticmethod
        def init_led(): pass
        @staticmethod
        def turn_on_led(): pass
        @staticmethod
        def turn_off_led(): pass
        @staticmethod
        def blink_led(): pass

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

maxWeight = 0.00000001
minWeight = -0.00000001
weight = 0

# set log level for webapp
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

############################################################################################################
# Section for the LoadCell class
############################################################################################################

class LoadCell():
    def __init__(self, hx711=None):
        if hx711 is not None:
            # Emulation path: caller supplies a pre-built stub.
            self.hx711 = hx711
        else:
            # Hardware path: only reached on a real Pi.
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
        state = run_with_timeout(self.hx711.reset, 15)
        if state == -1:
            print('Error initializing')
            led.turn_off_led()
            self.cleanup()
            if IS_PI:
                os.system('/home/ankleflex/venv/bin/python /home/ankleflex/main.py')
            exit()
            return

        self.offset = run_with_timeout(self.get_offset, 15)
        if self.offset == -1:
            print('Error initializing')
            led.turn_off_led()
            self.cleanup()
            if IS_PI:
                os.system('/home/ankleflex/venv/bin/python /home/ankleflex/main.py')
            exit()
            return
        

    def get_offset(self, times=5):
        measures = []
        while len(measures) < times:
            data = self.hx711._read()
            if data is not False and data != -1:
                measures.append(data)
                print('*'*len(measures))
        return sum(measures) / len(measures)

    def get_weight(self):
        measures = self.hx711._read()
        return (measures - self.offset) / CALIBRATION_FACTOR

    def cleanup(self):
        self.hx711.power_down()
        if IS_PI:
            GPIO.cleanup()
        
        
############################################################################################################
# Section for the button class
############################################################################################################  
            
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
                    global maxWeight, minWeight
                    maxWeight = 0.00000001
                    minWeight = -0.00000001
                    
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
        
        
############################################################################################################
# section for the dash app
############################################################################################################


app = dash.Dash(__name__)

_emulator_visible = not IS_PI

app.layout = html.Div([
    dcc.Interval(id='interval', interval=500, n_intervals=0),
    # ── Controls row ────────────────────────────────────────────────────────
    html.Div([
        dcc.Checklist(
            id='invert-y',
            options=[{'label': ' Flip Y Axis', 'value': 'flip'}],
            value=[],
            style={'fontSize': '14px', 'cursor': 'pointer', 'whiteSpace': 'nowrap'}
        ),
        html.Span('Scale:', style={'fontSize': '13px', 'whiteSpace': 'nowrap'}),
        html.Div([
            dcc.Slider(
                id='scale-slider',
                min=0.1, max=10, step=0.1, value=1.0,
                marks={1: '1×', 2: '2×', 5: '5×', 10: '10×'},
                tooltip={'placement': 'top', 'always_visible': True},
            ),
        ], style={'width': '300px', 'paddingTop': '4px'}),
    ], style={
        'position': 'absolute', 'bottom': '90px', 'left': '50%',
        'transform': 'translateX(-50%)',
        'zIndex': 1000,
        'display': 'flex', 'alignItems': 'center', 'gap': '16px',
        'background': 'rgba(255,255,255,0.9)', 'padding': '8px 16px',
        'borderRadius': '8px', 'fontSize': '14px',
        'boxShadow': '0 1px 4px rgba(0,0,0,0.15)',
    }),
    dcc.Graph(id='graph', style={'height': '90vh', 'width': '98vw'}),
    # Emulator slider — always in DOM, hidden on Pi
    html.Div([
        html.Label('Simulated load (kg)', style={'fontSize': '13px', 'marginBottom': '4px'}),
        dcc.Slider(
            id='emulator-slider',
            min=-50, max=50, step=0.5, value=0,
            marks={i: f'{i}' for i in range(-50, 51, 10)},
            tooltip={'placement': 'bottom', 'always_visible': True},
        )
    ], style={
        'position': 'absolute', 'bottom': '8px', 'left': '5%', 'width': '90%',
        'background': 'rgba(255,255,0,0.15)', 'border': '1px dashed #aaa',
        'padding': '8px 12px', 'borderRadius': '6px', 'zIndex': 1000,
        'display': 'block' if _emulator_visible else 'none',
    }),
], style={'height': '100vh', 'width': '100vw', 'display': 'flex', 'justify-content': 'center',
          'align-items': 'center', 'position': 'relative'})

@app.callback(
    Output('graph', 'figure'),
    Input('interval', 'n_intervals'),
    Input('invert-y', 'value'),
    Input('scale-slider', 'value'),
    Input('emulator-slider', 'value'),
)
def update_graph(n, invert_y, scale, emulator_val):
    global loadcell, maxWeight, minWeight
    scale = scale or 1.0
    if not IS_PI:
        emulated_hx711.set_weight(emulator_val or 0.0)
    data = loadcell.get_weight()
    raw = data if data not in (False, -1) else 0.0

    # Apply scale and track running min/max on the scaled value
    weight = raw * scale
    minWeight = min(minWeight, weight)
    maxWeight = max(maxWeight, weight)

    # Build the figure; range_y will be overridden below based on the flip state
    fig = px.bar(x=['Weight'], y=[weight], title='Weight (kg)', range_y=[minWeight*1.1, maxWeight*1.1])

    # add horizontal line  max weight
    fig.add_shape(
        type="line",
        x0=-0.5, y0=maxWeight, x1=0.5, y1=maxWeight,
        line=dict(color="Red", width=3)
    )
    # add horizontal line  min weight
    fig.add_shape(
        type="line",
        x0=-0.5, y0=minWeight, x1=0.5, y1=minWeight,
        line=dict(color="red", width=3)
    )
    # Apply Y axis range; invert when the checkbox is checked.
    if 'flip' in invert_y:
        fig.update_yaxes(range=[maxWeight * 1.1, minWeight * 1.1])
    else:
        fig.update_yaxes(range=[minWeight * 1.1, maxWeight * 1.1])

    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    return fig

############################################################################################################
# end of dash app   
############################################################################################################
        

if __name__ == '__main__':
    led.init_led()
    led.turn_on_led()

    if IS_PI:
        print('Running on Raspberry Pi — using real hardware')
        loadcell = LoadCell()
        loadcell.initialize()
        buttonThread = threading.Thread(target=Button, args=(loadcell,), daemon=True)
        buttonThread.start()
    else:
        print('Running in emulation mode — no hardware required')
        emulated_hx711 = EmulatedHX711()
        loadcell = LoadCell(hx711=emulated_hx711)
        loadcell.initialize()

    print('Starting app on http://0.0.0.0:8050 ...')
    app.run_server(debug=False, host='0.0.0.0', port=8050)