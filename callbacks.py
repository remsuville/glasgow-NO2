from dash import Input, Output, State, no_update
from dash.exceptions import PreventUpdate

from config import CITIES
from data import get_no2
from figures import make_map, make_timeseries


def register_callbacks(app):
    @app.callback(
        Output("no2-map", "figure"),
        Output("no2-timeline", "figure"),
        Input("submit-button", "n_clicks"),
        State("city-dropdown", "value"),
        State("date-range", "start_date"),
        State("date-range", "end_date"),
        prevent_initial_call=True,
    )
    
    def update_charts(n_clicks, city, start_date, end_date):     
        # Prevention for when one of the days is not chosen yet
        if not start_date or not end_date:
            raise PreventUpdate
        
        df = get_no2(city, start_date, end_date)
        
        return make_map(df, city, CITIES[city]), make_timeseries(df, city)