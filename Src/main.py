# AnkleFlex — Dash/Plotly force-feedback visualiser
# Runs on Raspberry Pi (real hardware) or any desktop (emulation mode).
# Pages:
#   /         — Live View: real-time bar chart with flip/scale controls
#   /history  — History:   rolling line chart with threshold zones and tare button
import sys
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.express as px
import plotly.graph_objects as go
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
    return q.get()


# GPIO pin configuration
LOADCELL_DOUT_PIN = 2   # GPIO 2 Board pin 3
LOADCELL_SCK_PIN = 3    # GPIO 3 Board pin 5
BUTTON_PIN = 17         # GPIO 17 Board pin 11

# Calibration factor (obtained using the calibration script)
CALIBRATION_FACTOR = -1554

# Threshold constants for the history page
THRESHOLD_UP = 500
THRESHOLD_DOWN = -500
LIST_LENGTH = 60

# Running weight bounds (shared across pages, reset on tare)
maxWeight = 0.00000001
minWeight = -0.00000001

# History page state
timestamps: list = []
data_points: list = []
above_threshold_count = 0
below_threshold_count = 0

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

############################################################################################################
# Section for the LoadCell class
############################################################################################################

class LoadCell:
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
                gain=64,
            )
        self.offset = 0
        self.ready = False

    def initialize(self):
        print('Calibrating...')
        state = run_with_timeout(self.hx711.reset, 15)
        if state == -1:
            print('Error initializing HX711 (reset timed out)')
            led.turn_off_led()
            self.cleanup()
            if IS_PI:
                os.system('/home/ankleflex/venv/bin/python /home/ankleflex/main.py')
            sys.exit()

        self.offset = run_with_timeout(self._measure_offset, 15)
        if self.offset == -1:
            print('Error initializing HX711 (offset timed out)')
            led.turn_off_led()
            self.cleanup()
            if IS_PI:
                os.system('/home/ankleflex/venv/bin/python /home/ankleflex/main.py')
            sys.exit()

        self.ready = True
        print('HX711 ready.')

    def _measure_offset(self, times=5):
        measures = []
        while len(measures) < times:
            data = self.hx711._read()
            if data is not False and data != -1:
                measures.append(data)
                print('*' * len(measures))
        return sum(measures) / len(measures)

    def get_weight(self):
        if not self.ready:
            return 0
        try:
            raw = self.hx711._read()
            if raw is False or raw == -1:
                return 0
            return (raw - self.offset) / CALIBRATION_FACTOR
        except Exception as e:
            print(f'[ERROR] Could not read weight: {e}')
            return 0

    def tare(self):
        print('Taring...')
        new_offset = run_with_timeout(self._measure_offset, 15)
        if new_offset != -1:
            self.offset = new_offset
            global maxWeight, minWeight
            maxWeight = 0.00000001
            minWeight = -0.00000001
            print(f'Tare complete. New offset: {self.offset}')

    def cleanup(self):
        self.hx711.power_down()
        if IS_PI:
            GPIO.cleanup()
        
        
############################################################################################################
# Section for the button class (Pi only)
############################################################################################################

if IS_PI:
    class Button:
        def __init__(self, loadcell):
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print('Press the button!')
            GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=self.button_callback, bouncetime=100)
            self.state = GPIO.input(BUTTON_PIN)
            self.last_time_pressed = time.time()
            self.mode = -1
            self.modes = {0: 'tare', 1: 'reboot', -1: 'error'}
            self.last_mode = -1
            self.last_mode_change = time.time()
            self.loadcell = loadcell
            while True:
                if self.mode != self.last_mode:
                    print(f'Mode: {self.modes[self.mode]}')
                    self.last_mode = self.mode
                    if self.mode == 0:
                        ledBlinkThread = threading.Thread(target=led.blink_led)
                        ledBlinkThread.start()
                        self.loadcell.tare()
                        ledBlinkThread.join()
                    elif self.mode == 1:
                        led.turn_off_led()
                        os.system('sudo reboot')
                        print('Rebooting...')
                time.sleep(min(1, time.time() - self.last_mode_change))

        def button_callback(self, channel):
            dt = time.time() - self.last_time_pressed
            if dt < 0.1:
                pass
            elif dt < 1:
                self.mode = 1
            else:
                self.last_mode = -1
                self.mode = 0
            self.last_time_pressed = time.time()


############################################################################################################
# Section for the Dash app
############################################################################################################

# suppress_callback_exceptions allows callbacks referencing components that are
# rendered dynamically (only present on one page at a time).
app = dash.Dash(__name__, suppress_callback_exceptions=True)

_emulator_visible = not IS_PI

NAV_STYLE = {
    'display': 'flex', 'gap': '24px', 'padding': '8px 20px',
    'background': '#f0f0f0', 'borderBottom': '1px solid #ccc',
    'alignItems': 'center',
}
LINK_STYLE = {
    'textDecoration': 'none', 'color': '#007BFF',
    'fontWeight': 'bold', 'fontSize': '15px',
}

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Interval(id='interval', interval=500, n_intervals=0),

    # ── Navigation bar ───────────────────────────────────────────────────────
    html.Div([
        html.Span('AnkleFlex', style={'fontWeight': 'bold', 'fontSize': '16px', 'marginRight': '8px'}),
        dcc.Link('Live View', href='/', style=LINK_STYLE),
        dcc.Link('History', href='/history', style=LINK_STYLE),
    ], style=NAV_STYLE),

    # ── Persistent controls bar (shared across all pages) ───────────────────
    html.Div([
        html.Button('Tare Load Cell', id='tare-button', n_clicks=0, style={
            'padding': '8px 18px', 'fontSize': '14px',
            'backgroundColor': '#007BFF', 'color': 'white',
            'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer',
        }),
        html.Div(id='tare-status', style={'fontSize': '14px', 'color': 'green', 'minWidth': '180px'}),
        dcc.Checklist(
            id='invert-y',
            options=[{'label': ' Flip Y Axis', 'value': 'flip'}],
            value=[],
            style={'fontSize': '14px', 'cursor': 'pointer', 'whiteSpace': 'nowrap'},
        ),
    ], style={
        'display': 'flex', 'alignItems': 'center', 'gap': '20px',
        'padding': '6px 20px', 'background': '#e8e8e8',
        'borderBottom': '1px solid #ccc',
    }),

    # ── Page content (rendered dynamically by URL) ───────────────────────────
    html.Div(id='page-content', style={'flex': '1', 'position': 'relative', 'overflow': 'hidden'}),

    # ── Emulator slider — always in DOM, hidden on Pi ────────────────────────
    html.Div([
        html.Label('Simulated load (kg)', style={'fontSize': '13px', 'marginBottom': '4px'}),
        dcc.Slider(
            id='emulator-slider',
            min=-1000, max=1000, step=10, value=0,
            marks={i: f'{i}' for i in range(-1000, 1001, 100)},
            tooltip={'placement': 'top', 'always_visible': True},
        ),
    ], style={
        'position': 'fixed', 'bottom': '8px', 'left': '5%', 'width': '90%',
        'background': 'rgba(255,255,0,0.15)', 'border': '1px dashed #aaa',
        'padding': '8px 12px', 'borderRadius': '6px', 'zIndex': 1000,
        'display': 'block' if _emulator_visible else 'none',
    }),

], style={'display': 'flex', 'flexDirection': 'column', 'height': '100vh', 'width': '100vw'})


# ── Live View page layout ─────────────────────────────────────────────────────
def live_view_layout():
    return html.Div([
        dcc.Graph(id='bar-graph', style={'height': '100%', 'width': '98vw'}),
    ], style={'position': 'relative', 'height': '100%', 'display': 'flex', 'justifyContent': 'center'})


# ── History page layout ───────────────────────────────────────────────────────
def history_layout():
    return html.Div([
        html.Div([
            html.Div(id='above-count', style={'fontSize': '18px', 'margin': '6px 14px'}),
            html.Div(id='below-count', style={'fontSize': '18px', 'margin': '6px 14px'}),
            html.Span('Y Range ±:', style={'fontSize': '13px', 'whiteSpace': 'nowrap', 'marginLeft': '20px'}),
            html.Div([
                dcc.Slider(
                    id='scale-slider',
                    min=100, max=3000, step=100, value=1000,
                    marks={100: '100', 500: '500', 1000: '1k', 2000: '2k', 3000: '3k'},
                    tooltip={'placement': 'top', 'always_visible': True},
                ),
            ], style={'width': '280px', 'paddingTop': '4px'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap',
                  'padding': '6px 16px', 'gap': '4px'}),
        dcc.Graph(id='line-graph', style={'height': '82vh', 'width': '98vw'}),
    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center'})


############################################################################################################
# Callbacks
############################################################################################################

def _record_history(weight: float) -> None:
    """Append a weight sample to the history buffers. Called on every interval tick
    regardless of which page is active, so the history is continuous."""
    global above_threshold_count, below_threshold_count, timestamps, data_points, maxWeight, minWeight
    minWeight = min(minWeight, weight)
    maxWeight = max(maxWeight, weight)
    if weight > THRESHOLD_UP:
        above_threshold_count += 1
    elif weight < THRESHOLD_DOWN:
        below_threshold_count += 1
    timestamps.append(time.strftime('%H:%M:%S'))
    data_points.append(weight)
    timestamps[:] = timestamps[-LIST_LENGTH:]
    data_points[:] = data_points[-LIST_LENGTH:]


@app.callback(Output('page-content', 'children'), Input('url', 'pathname'))
def render_page(pathname):
    if pathname == '/history':
        return history_layout()
    return live_view_layout()


@app.callback(
    Output('bar-graph', 'figure'),
    Input('interval', 'n_intervals'),
    Input('emulator-slider', 'value'),
    State('invert-y', 'value'),
    State('url', 'pathname'),
)
def update_bar(n, emulator_val, invert_y, pathname):
    if pathname != '/' and pathname is not None:
        raise PreventUpdate
    global loadcell, maxWeight, minWeight
    if not IS_PI:
        emulated_hx711.set_weight(emulator_val or 0.0)
    raw = loadcell.get_weight()
    _record_history(raw)

    fig = px.bar(x=['Weight'], y=[raw], title='', labels={'y': 'Weight (kg)'})
    fig.add_shape(type='line', x0=-0.5, y0=maxWeight, x1=0.5, y1=maxWeight, line=dict(color='Red', width=3))
    fig.add_shape(type='line', x0=-0.5, y0=minWeight, x1=0.5, y1=minWeight, line=dict(color='red', width=3))
    fig.add_shape(type='line', x0=-0.5, y0=0, x1=0.5, y1=0, line=dict(color='black', width=3))
    if 'flip' in (invert_y or []):
        fig.update_yaxes(range=[maxWeight * 1.1, minWeight * 1.1])
    else:
        fig.update_yaxes(range=[minWeight * 1.1, maxWeight * 1.1])
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    return fig


@app.callback(
    [Output('line-graph', 'figure'),
     Output('above-count', 'children'),
     Output('below-count', 'children')],
    Input('interval', 'n_intervals'),
    Input('emulator-slider', 'value'),
    State('scale-slider', 'value'),
    State('invert-y', 'value'),
    State('url', 'pathname'),
)
def update_history(n, emulator_val, y_range, invert_y, pathname):
    if pathname != '/history':
        raise PreventUpdate
    global loadcell, above_threshold_count, below_threshold_count
    if not IS_PI:
        emulated_hx711.set_weight(emulator_val or 0.0)
    weight = loadcell.get_weight()
    _record_history(weight)

    y_range = y_range or 1000
    y_max = y_range
    y_min = -y_range
    if 'flip' in (invert_y or []):
        y_min, y_max = y_max, y_min

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=data_points,
        mode='lines+markers', name='Weight',
        line=dict(width=2, color='green'),
    ))
    fig.add_hline(y=THRESHOLD_UP, line_dash='dot', line_color='blue',
                  annotation_text='+500 Threshold', annotation_position='top left')
    fig.add_hline(y=THRESHOLD_DOWN, line_dash='dot', line_color='blue',
                  annotation_text='-500 Threshold', annotation_position='bottom left')
    fig.add_shape(type='rect', xref='paper', yref='y',
                  x0=0, x1=1, y0=THRESHOLD_UP, y1=abs(y_range), fillcolor='green', opacity=0.1, line_width=0)
    fig.add_shape(type='rect', xref='paper', yref='y',
                  x0=0, x1=1, y0=-abs(y_range), y1=THRESHOLD_DOWN, fillcolor='blue', opacity=0.1, line_width=0)
    fig.update_layout(
        title='Weight with Threshold Zones',
        yaxis_title='Weight',
        xaxis_title='',
        showlegend=False,
        template='plotly_white',
        margin=dict(l=0, r=0, t=30, b=0),
        yaxis=dict(range=[y_min, y_max]),
    )
    return fig, f'Above +500 count: {above_threshold_count}', f'Below -500 count: {below_threshold_count}'


@app.callback(
    Output('tare-status', 'children'),
    Input('tare-button', 'n_clicks'),
    prevent_initial_call=True,
)
def tare_load_cell(n_clicks):
    try:
        loadcell.tare()
        return f'Tare complete at {time.strftime("%H:%M:%S")}'
    except Exception as e:
        return f'Tare failed: {e}'


############################################################################################################
# Entry point
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