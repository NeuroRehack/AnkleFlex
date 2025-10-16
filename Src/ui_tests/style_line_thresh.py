# ui_test_thresholds.py
# Dash app with threshold visualization and counters

import dash
from dash import html, dcc
from dash.dependencies import Input, Output
import random
import time
import logging
import plotly.graph_objects as go

# Simulated variables
maxWeight = 0.00000001
minWeight = -0.00000001
weight = 0
above_threshold_count = 0
below_threshold_count = 0

# Disable Flask logs for clean output
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Create Dash app
app = dash.Dash(__name__)

# Data storage
data_points = []
timestamps = []

THRESHOLD_UP = 500
THRESHOLD_DOWN = -500

app.layout = html.Div([
    dcc.Interval(id='interval', interval=500, n_intervals=0),
    html.Div([
        html.Div(id='above-count', style={'font-size': '20px', 'margin': '10px'}),
        html.Div(id='below-count', style={'font-size': '20px', 'margin': '10px'})
    ], style={'display': 'flex', 'justify-content': 'center'}),
    dcc.Graph(id='graph', style={'height': '85vh', 'width': '98vw'})
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
    Input('interval', 'n_intervals')
)
def update_graph(n):
    global weight, maxWeight, minWeight, above_threshold_count, below_threshold_count

    # Generate simulated weight values between -800 and 800
    weight = round(random.uniform(-800, 800), 2)
    data_points.append(weight)
    timestamps.append(time.time())

    # Keep only the last 60 samples
    if len(data_points) > 60:
        data_points.pop(0)
        timestamps.pop(0)

    minWeight = min(minWeight, weight)
    maxWeight = max(maxWeight, weight)

    # Update threshold counters
    if weight > THRESHOLD_UP:
        above_threshold_count += 1
    elif weight < THRESHOLD_DOWN:
        below_threshold_count += 1

    # Create line chart
    fig = go.Figure()

    # Line for weight over time
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=data_points,
        mode='lines+markers',
        name='Weight (kg)',
        line=dict(width=2)
    ))

    # Threshold lines
    fig.add_hline(y=THRESHOLD_UP, line_dash='dot', line_color='red',
                  annotation_text='+500 Threshold', annotation_position='top left')
    fig.add_hline(y=THRESHOLD_DOWN, line_dash='dot', line_color='blue',
                  annotation_text='-500 Threshold', annotation_position='bottom left')

    # Highlight zones
    fig.add_shape(type='rect',
                  xref='paper', yref='y',
                  x0=0, x1=1, y0=THRESHOLD_UP, y1=800,
                  fillcolor='red', opacity=0.1, line_width=0)
    fig.add_shape(type='rect',
                  xref='paper', yref='y',
                  x0=0, x1=1, y0=-800, y1=THRESHOLD_DOWN,
                  fillcolor='blue', opacity=0.1, line_width=0)

    fig.update_layout(
        title='Weight over Time with Threshold Zones',
        xaxis_title='Time',
        yaxis_title='Weight (kg)',
        template='plotly_white',
        margin=dict(l=0, r=0, t=40, b=0)
    )

    return (
        fig,
        f"Above +500 count: {above_threshold_count}",
        f"Below -500 count: {below_threshold_count}"
    )

if __name__ == '__main__':
    print("Starting UI Test (Threshold Visualization Mode)...")
    app.run_server(debug=True, host='0.0.0.0', port=8050)
