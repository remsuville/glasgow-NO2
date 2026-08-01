from dash import dcc, html
from datetime import date

from config import DATE_RANGE, REGION_NAME


layout = html.Div([
    html.H1(f"Sentinel-5P NO2 Dashboard — {REGION_NAME}"),

    # Holds the *submitted* date range. The date picker alone must never drive
    # a fetch — that is what the Submit button exists to gate — but the map-view
    # dropdown does need to redraw live, so it reads the range from here rather
    # than from the picker's uncommitted value.
    dcc.Store(id="submitted-range"),

    # Select Date
    html.Div([
        html.Label("Select Date Range"),
        dcc.DatePickerRange(
            id="date-range",
            min_date_allowed=date(2018,7,1), #Earliest Sentinel-5P data
            max_date_allowed=date.today(),
            start_date=DATE_RANGE[0],
            end_date=DATE_RANGE[1],
            display_format="YYYY-MM-DD",
        ),
        html.Button("Submit", id="submit-button", n_clicks=0,
                    style={"marginLeft": "10px"}),
    ], style={"marginLeft": "30px"}),

    # One map, several views. The unaggregated grid is just another option here
    # rather than a second always-on figure — stacking both meant two nearly
    # identical maps competing for the same screen. Swapping views is live and
    # cheap, which is also the point of keeping zonal_means() generic.
    html.Div([
        html.Label("Map view"),
        dcc.Dropdown(
            id="map-view",
            options=[
                {"label": "Sentinel-5P grid cells (unaggregated)", "value": "pixels"},
                {"label": "Council areas (32)", "value": "councils"},
                {"label": "Intermediate Zones 2022 (1,334)", "value": "intzones"},
                {"label": "Data Zones 2022 (7,392)", "value": "datazones"},
            ],
            value="intzones",
            clearable=False,
            style={"width": "320px"},
        ),
    ], style={"marginLeft": "30px", "marginTop": "15px"}),

    dcc.Graph(id="no2-map", style={"height": "70vh"}),

    dcc.Graph(id="no2-timeline"),
])