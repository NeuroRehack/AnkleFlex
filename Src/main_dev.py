

import sys
import dash
from dash import html, dcc
from dash.dependencies import Input, Output
import plotly.express as px
import time
import threading
import queue
import os
import logging
from tqdm import tqdm
from flask import request
import plotly.graph_objects as go

# --- Emulation/Hardware detection ---
try:
    import RPi.GPIO as GPIO
    from hx711v0_5_1 import HX711
    IS_PI = True
except (ImportError, RuntimeError):
    IS_PI = False

# Emulated HX711 for non-Pi systems
if not IS_PI:
    from emulated_hx711 import EmulatedHX711

# Conditionally import led or stub
if IS_PI:
    import led
else:
    class led:
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
REFERENCE_UNIT = -1554   # adjust after calibration

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

class LoadCell:
    def __init__(self, hx711=None):
        print("[INFO] Initializing LoadCell...")
        if hx711 is not None:
            self.hx = hx711
        else:
            self.hx = HX711(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN)
        self.ready = False
        self.offset = 0
        self.reference_unit = REFERENCE_UNIT

    def initialize(self):
        print("[INFO] Calibrating and setting up HX711...")
        try:
            if IS_PI:
                self.hx.setReadingFormat("MSB", "MSB")
                print("[INFO] Automatically setting the offset.")
                self.hx.autosetOffset()
                self.offset = self.hx.getOffset()
                print(f"[INFO] Offset set to: {self.offset}")
                print(f"[INFO] Setting reference unit: {self.reference_unit}")
                self.hx.setReferenceUnit(self.reference_unit)
            else:
                # Emulated HX711: set up as needed
                self.offset = 0
            print("[INFO] HX711 ready. You can add weight now.")
            self.ready = True
        except Exception as e:
            print(f"[ERROR] Failed to initialize LoadCell: {e}")
            self.cleanup()
            led.turn_off_led()
            sys.exit()

    def get_weight(self):
        if not self.ready:
            print("[WARN] LoadCell not ready.")
            return 0
        try:
            if IS_PI:
                raw_bytes = self.hx.getRawBytes()
                weight_grams = self.hx.rawBytesToWeight(raw_bytes)
                return round(weight_grams, 2)
            else:
                # Emulated HX711: read raw ADC counts and apply the same
                # offset/calibration arithmetic as the hardware path.
                raw = self.hx._read()
                return round((raw - self.offset) / CALIBRATION_FACTOR, 2)
        except Exception as e:
            print(f"[ERROR] Could not read weight: {e}")
            return 0

    def get_offset(self):
        try:
            if IS_PI:
                return self.hx.getOffset()
            else:
                return 0
        except Exception as e:
            print(f"[ERROR] Could not get offset: {e}")
            return 0

    def tare(self):
        print("[INFO] Taring load cell...")
        try:
            if IS_PI:
                self.hx.autosetOffset()
                self.offset = self.hx.getOffset()
                print(f"[INFO] New offset: {self.offset}")
            else:
                self.offset = 0
        except Exception as e:
            print(f"[ERROR] Tare failed: {e}")

    def cleanup(self):
        print("[INFO] Cleaning up GPIO and HX711...")
        if IS_PI:
            GPIO.cleanup()
            try:
                self.hx.powerDown()
            except Exception:
                pass
############################################################################################################
# Section for the button class
############################################################################################################  
            
if IS_PI:
    class Button():
        def __init__(self,loadcell):
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
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

# Threshold constants
THRESHOLD_UP = 500
THRESHOLD_DOWN = -500

#Limit for list length 
listLength=60

# Counters
above_threshold_count = 0
below_threshold_count = 0

app.layout = html.Div([
    dcc.Interval(id='interval', interval=1000, n_intervals=0),
    html.Div([
        html.Button('Tare Load Cell', id='tare-button', n_clicks=0, style={
            'padding': '10px 20px',
            'font-size': '16px',
            'margin': '10px',
            'background-color': '#007BFF',
            'color': 'white',
            'border': 'none',
            'border-radius': '5px',
            'cursor': 'pointer'
        }),
        html.Div(id='tare-status', style={'font-size': '16px', 'margin': '10px', 'color': 'green'})
    ], style={'display': 'flex', 'justify-content': 'center'}),
    html.Div([
        html.Div(id='above-count', style={'font-size': '20px', 'margin': '10px'}),
        html.Div(id='below-count', style={'font-size': '20px', 'margin': '10px'})
    ], style={'display': 'flex', 'justify-content': 'center'}),
    dcc.Graph(id='graph', style={'height': '85vh', 'width': '98vw'}),
    # Emulator slider — always in DOM, hidden on Pi
    html.Div([
        html.Label('Simulated load (kg)', style={'fontSize': '13px', 'marginBottom': '4px'}),
        dcc.Slider(
            id='emulator-slider',
            min=-1000, max=1000, step=10, value=0,
            marks={i: f'{i}' for i in range(-1000, 1001, 100)},
            tooltip={'placement': 'bottom', 'always_visible': True},
        )
    ], style={
        'position': 'fixed', 'bottom': '8px', 'left': '5%', 'width': '90%',
        'background': 'rgba(255,255,0,0.15)', 'border': '1px dashed #aaa',
        'padding': '8px 12px', 'borderRadius': '6px', 'zIndex': 1000,
        'display': 'block' if _emulator_visible else 'none',
    }),
], style={
    'height': '100vh',
    'width': '100vw',
    'display': 'flex',
    'flex-direction': 'column',
    'align-items': 'center'
})

@app.callback(
    [Output('graph', 'figure'),
     Output('above-count', 'children'),
     Output('below-count', 'children')],
    Input('interval', 'n_intervals'),
    Input('emulator-slider', 'value'),
)
def update_graph(n, emulator_val):
    global loadcell, maxWeight, minWeight, above_threshold_count, below_threshold_count

    if not IS_PI:
        emulated_hx711.set_weight(emulator_val or 0.0)

    data = loadcell.get_weight()
    if data not in [False, -1]:
        weight = data
    else:
        weight = 0

    minWeight = min(minWeight, weight)
    maxWeight = max(maxWeight, weight)

    # Update counters
    if weight > THRESHOLD_UP:
        above_threshold_count += 1
    elif weight < THRESHOLD_DOWN:
        below_threshold_count += 1

    # Initialize lists the first time
    if 'timestamps' not in globals():
        global timestamps, data_points
        timestamps = []
        data_points = []

    timestamps.append(time.strftime('%H:%M:%S'))
    data_points.append(weight)

    # Limit list length
    timestamps[:] = timestamps[-listLength:]
    data_points[:] = data_points[-listLength:]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=data_points,
        mode='lines+markers',
        name='Weight',
        line=dict(width=2, color='green')
    ))

    # Threshold lines
    fig.add_hline(y=THRESHOLD_UP, line_dash='dot', line_color='blue',
                  annotation_text='+500 Threshold', annotation_position='top left')
    fig.add_hline(y=THRESHOLD_DOWN, line_dash='dot', line_color='blue',
                  annotation_text='-500 Threshold', annotation_position='bottom left')

    # Highlight zones
    fig.add_shape(type='rect',
                  xref='paper', yref='y',
                  x0=0, x1=1, y0=THRESHOLD_UP, y1=5000,
                  fillcolor='green', opacity=0.1, line_width=0)
    fig.add_shape(type='rect',
                  xref='paper', yref='y',
                  x0=0, x1=1, y0=-5000, y1=THRESHOLD_DOWN,
                  fillcolor='blue', opacity=0.1, line_width=0)

    # Dynamic Y-axis range
    y_min = min(minWeight*1.1, THRESHOLD_DOWN*1.5)
    y_max = max(maxWeight*1.1, THRESHOLD_UP*1.5)

    fig.update_layout(
        title='Weight with Threshold Zones',
        yaxis_title='Weight ',
        xaxis_title='',
        showlegend=False,
        template='plotly_white',
        margin=dict(l=0, r=0, t=30, b=0),
        yaxis=dict(range=[y_min, y_max])
    )
    #

    return (
        fig,
        f"Above +500 count: {above_threshold_count}",
        f"Below -500 count: {below_threshold_count}"
    )

@app.callback(
    Output('tare-status', 'children'),
    Input('tare-button', 'n_clicks')
)
def tare_load_cell(n_clicks):
    if n_clicks > 0:
        try:
            loadcell.tare()
            return f"Tare complete at {time.strftime('%H:%M:%S')}"
        except Exception as e:
            return f"Tare failed: {e}"
    return ""

############################################################################################################
# end of dash app   
############################################################################################################
        

if __name__ == '__main__':
    led.init_led()
    led.turn_on_led()
    try:
        print('Starting LoadCell...')
        if IS_PI:
            loadcell = LoadCell()
            print('Starting Button...')
            buttonThread = threading.Thread(target=Button, args=(loadcell,))
            loadcell.initialize()
            buttonThread.daemon = True
            buttonThread.start()
        else:
            print('Running in emulation mode — no hardware required')
            emulated_hx711 = EmulatedHX711()
            loadcell = LoadCell(hx711=emulated_hx711)
            loadcell.initialize()
        print('Starting app...')
        app.run_server(debug=False, host='0.0.0.0', port=8050)
    except Exception as e:
        if IS_PI:
            buttonThread.join()
        print('Exiting...')
        loadcell.cleanup()
        led.turn_off_led()
        shutdown_server()
        exit()