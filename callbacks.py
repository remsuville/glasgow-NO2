from dash import Input, Output

from config import CITIES, DATE_RANGE
from data import get_no2
from figures import make_map, make_timeseries


def register_callbacks(app):
    @app.callback(
        Output("no2-map", "figure"),
        Output("no2-timeline", "figure"),
        Input("city-dropdown", "value"),
    )
    def update_charts(city):
        df = get_no2(city, *DATE_RANGE)
        return make_map(df, city, CITIES[city]), make_timeseries(df, city)