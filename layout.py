from dash import dcc, html
from datetime import date

from config import DATE_RANGE, REGION_NAME


layout = html.Div([
    html.H1(f"Sentinel-5P NO2 Dashboard — {REGION_NAME}"),

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

    dcc.Graph(id="no2-map"),
    
    dcc.Graph(id="no2-timeline"),
])