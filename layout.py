from dash import dcc, html

from config import CITIES


layout = html.Div([
    html.H1("Sentinel-5P NO₂ Dashboard — Scotland"),

    html.Div([
        html.Label("Select city:"),
        dcc.Dropdown(
            id="city-dropdown",
            options=[{"label": c, "value": c} for c in CITIES.keys()],
            value="Central Belt",
            clearable=False,
        ),
    ], style={"width": "300px", "marginBottom": "20px"}),

    dcc.Graph(id="no2-map"),
    dcc.Graph(id="no2-timeline"),
])