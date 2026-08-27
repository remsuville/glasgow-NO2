from dash import Input, Output, State, no_update
from dash.exceptions import PreventUpdate
from boundaries import ZONE_SETS, load_zones
from config import BBOX, REGION_NAME
from data import get_no2
from figures import make_map, make_timeseries, make_zonal_map
from zonal import zonal_means

import logging

logger = logging.getLogger(__name__)


MIN_COVERAGE = 0.10

ZONE_LABELS = {
    "councils": "Council areas",
    "intzones": "Intermediate Zones 2022",
    "datazones": "Data Zones 2022",
}

# The unaggregated grid is a map *view*, not a zone set — it deliberately isn't
# a key of ZONE_SETS, so it can never be handed to load_zones().
PIXEL_VIEW = "pixels"


def register_callbacks(app):
    @app.callback(
        Output("submitted-range", "data"),
        Input("submit-button", "n_clicks"),
        State("date-range", "start_date"),
        State("date-range", "end_date"),
        prevent_initial_call=True,
    )
    def commit_range(n_clicks, start_date, end_date):
        # Prevention for when one of the days is not chosen yet
        if not start_date or not end_date:
            raise PreventUpdate
        return {"start": start_date, "end": end_date}

    @app.callback(
        Output("no2-timeline", "figure"),
        Input("submitted-range", "data"),
        prevent_initial_call=True,
    )
    def update_timeline(submitted):
        if not submitted:
            raise PreventUpdate
        df = get_no2(submitted["start"], submitted["end"])
        return make_timeseries(df)

    @app.callback(
        Output("no2-map", "figure"),
        Input("submitted-range", "data"),
        Input("map-view", "value"),
        prevent_initial_call=True,
    )
    def update_map(submitted, view):
        # No submitted range yet — a dropdown change on its own must not fetch.
        if not submitted:
            raise PreventUpdate
        if view != PIXEL_VIEW and view not in ZONE_SETS:
            raise PreventUpdate

        df = get_no2(submitted["start"], submitted["end"])
        logger.info(f"Rendering '{view}' for {REGION_NAME}: {len(df)} rows")

        if view == PIXEL_VIEW:
            return make_map(df, BBOX)

        stats = zonal_means(df, load_zones(view), min_coverage=MIN_COVERAGE)
        return make_zonal_map(stats, BBOX, ZONE_LABELS.get(view, view))
