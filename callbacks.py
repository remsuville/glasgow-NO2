from dash import Input, Output, State, no_update
from dash.exceptions import PreventUpdate

from boundaries import ZONE_SETS, load_zones
from config import BBOX, REGION_NAME
from data import get_no2
from figures import make_map, make_timeseries, make_zonal_map
from zonal import zonal_means

import logging

logger = logging.getLogger(__name__)

# A zone whose mean rests on less than this fraction of its area is reported as
# "no data" rather than coloured in. Zones clipped by the study bbox are the
# usual case — Perth and Kinross sits 2% inside it, and a Central Belt sliver
# should not be presented as a value for the whole council.
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
        Output("no2-map", "figure"),
        Output("no2-timeline", "figure"),
        Input("submitted-range", "data"),
        Input("map-view", "value"),
        prevent_initial_call=True,
    )
    def update_charts(submitted, view):
        # No submitted range yet — a dropdown change on its own must not fetch.
        if not submitted:
            raise PreventUpdate
        if view != PIXEL_VIEW and view not in ZONE_SETS:
            raise PreventUpdate

        start_date, end_date = submitted["start"], submitted["end"]
        df = get_no2(start_date, end_date)

        logger.info(f"Rendering '{view}' for {REGION_NAME}: {len(df)} rows")

        if view == PIXEL_VIEW:
            map_fig = make_map(df, BBOX)
        else:
            stats = zonal_means(df, load_zones(view), min_coverage=MIN_COVERAGE)
            map_fig = make_zonal_map(stats, BBOX, ZONE_LABELS.get(view, view))

        return map_fig, make_timeseries(df)