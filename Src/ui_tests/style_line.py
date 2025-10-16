# ui_test.py
# Simulated Dash app to test UI layout (line graph version)
# No hardware, uses dummy data

import dash
from dash import html, dcc
from dash.dependencies import Input, Output

import random
import time
import logging

import plotly.graph_objects as go # This needs to be added to main.py

# Simulated variables (keep names identical to main code)
maxWeight = 0.00000001
minWeight = -0.00000001
weight = 0

# Disable Flask logs for clean output
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Create Dash app
app = dash.Dash(__name__)

# Store last N readings to simulate streaming data
data_points = []
timestamps = []

app.layout = html.Div([
    dcc.Interval(id='interval', interval=500, n_intervals=0),
    dcc.Graph(id='graph', style={'height': '90vh', 'width': '98vw'})
], style={
    'height': '100vh',
    'width': '100vw',
    'display': 'flex',
    'justify-content': 'center',
    'align-items': 'center'
})

##########################################################
#this section needs to be replace in the main.py file to make these changes

@app.callback(
    Output('graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_graph(n):
    global weight, maxWeight, minWeight

    # Generate simulated weight values
    weight = round(random.uniform(-0.2, 2.5), 2)
    data_points.append(weight)
    timestamps.append(time.time())

    # Keep only the last 100 samples
    if len(data_points) > 60:
        data_points.pop(0)
        timestamps.pop(0)

    minWeight = min(minWeight, weight)
    maxWeight = max(maxWeight, weight)

    # Create line chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=data_points,
        mode='lines+markers',
        name='Weight (kg)',
        line=dict(width=2)
    ))

    fig.update_layout(
        title='Weight over Time',
        xaxis_title='Time',
        yaxis_title='Weight (kg)',
        template='plotly_white',
        margin=dict(l=0, r=0, t=40, b=0)
    )

    return fig
###############################################################

if __name__ == '__main__':
    print("Starting UI Test (Line Graph Mode)...")
    app.run_server(debug=True, host='0.0.0.0', port=8050)
