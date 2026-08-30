from dash import dcc, html
from datetime import date

from config import DATE_RANGE, REGION_NAME


layout = html.Div([
    html.Header([
        html.H1(f"Sentinel-5P NO2 Dashboard — {REGION_NAME}"),
        html.A("Globe →", href="/", className="nav-link"),
    ], className="page-header"),

    # Holds the submitted date range. The date picker never fetches - only the Submit button does
    dcc.Store(id="submitted-range"),

    html.Div([
        html.Div([
            html.Label("Date range", className="control-label"),
            dcc.DatePickerRange(
                id="date-range",
                min_date_allowed=date(2018, 7, 1),  # Earliest Sentinel-5P data
                max_date_allowed=date.today(),
                start_date=DATE_RANGE[0],
                end_date=DATE_RANGE[1],
                display_format="YYYY-MM-DD",
            ),
            html.Button("Submit", id="submit-button", n_clicks=0),
        ], className="control"),

        # One map, several views which can be changed live
        html.Div([
            html.Label("Map view", className="control-label"),
            dcc.Dropdown(
                id="map-view",
                options=[
                    {"label": "Sentinel-5P grid cells (unaggregated)", "value": "pixels"},
                    {"label": "Council areas", "value": "councils"},
                    {"label": "Intermediate Zones 2022", "value": "intzones"},
                    {"label": "Data Zones 2022", "value": "datazones"},
                ],
                value="intzones",
                clearable=False,
            ),
        ], className="control"),
    ], className="controls"),

    dcc.Graph(id="no2-map", className="map-graph"),
    dcc.Graph(id="no2-timeline", className="timeline-graph"),
], className="page")
