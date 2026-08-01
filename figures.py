import json

import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from config import REGION_NAME


def _zoom_for_bbox(bbox):
    max_range = max(bbox["north"] - bbox["south"], bbox["east"] - bbox["west"])
    if max_range > 2:
        return 7
    if max_range > 1:
        return 8
    if max_range > 0.5:
        return 9
    return 10


def grid_step(values):
    """Spacing between adjacent grid coordinates.

    openEO resamples S5P onto a regular lat/lon grid, so every gap between
    *adjacent* unique coordinates is identical. The median is taken because
    the grid is sparse — a date with no swath coverage leaves holes, and
    those gaps are multiples of the true step, never smaller than it.
    """
    unique = np.unique(np.asarray(values))
    if unique.size < 2:
        raise ValueError("need at least two distinct coordinates to infer grid step")
    return float(np.median(np.diff(unique)))


def cell_polygons(cells, dx=None, dy=None):
    """GeoJSON FeatureCollection of one rectangle per pixel footprint.

    `cells` has columns x, y holding cell *centres* (EPSG:4326). Each feature
    is the cell's true extent, centre +/- half a step. Feature ids are the
    positional index of `cells`, so `locations` can index straight into it.

    This is the geometry area-weighted zonal statistics need — the map is just
    the first consumer of it.
    """
    dx = grid_step(cells["x"]) if dx is None else dx
    dy = grid_step(cells["y"]) if dy is None else dy
    hx, hy = dx / 2, dy / 2

    features = []
    for i, (x, y) in enumerate(zip(cells["x"], cells["y"])):
        w, e, s, n = x - hx, x + hx, y - hy, y + hy
        features.append({
            "type": "Feature",
            "id": i,
            "geometry": {
                "type": "Polygon",
                # closed ring, counter-clockwise
                "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
            },
            "properties": {},
        })
    return {"type": "FeatureCollection", "features": features}


def make_map(df, bbox):
    valid_counts = df.groupby("t")["NO2"].count()
    best_day = valid_counts.idxmax()
    all_dates = sorted(df["t"].unique())
    best_idx = list(all_dates).index(best_day)
    t_start = max(0, best_idx - 4)
    t_end = min(len(all_dates) - 1, best_idx + 4)
    window_dates = all_dates[t_start : t_end + 1]
    window_df = df[df["t"].isin(window_dates)]
    no2_mean = window_df.groupby(["x", "y"])["NO2"].mean().reset_index()

    # Step comes from the full frame, not the windowed subset: a sparse window
    # can miss whole rows/columns and overestimate the spacing.
    dx, dy = grid_step(df["x"]), grid_step(df["y"])
    geojson = cell_polygons(no2_mean, dx=dx, dy=dy)

    fig = go.Figure(go.Choroplethmap(
        geojson=geojson,
        locations=np.arange(len(no2_mean)),
        z=no2_mean["NO2"],
        colorscale="Reds",
        marker_opacity=0.75,
        marker_line_width=0.5,
        marker_line_color="rgba(255,255,255,0.35)",
        colorbar_title="NO2<br>(mol/m2)",
        customdata=no2_mean[["x", "y"]],
        hovertemplate=(
            "NO2: %{z:.3e} mol/m2<br>"
            "cell centre: %{customdata[1]:.4f}, %{customdata[0]:.4f}"
            "<extra></extra>"
        ),
    ))
    fig.update_layout(
        map_style="open-street-map",
        map_center={
            "lat": (bbox["north"] + bbox["south"]) / 2,
            "lon": (bbox["west"] + bbox["east"]) / 2,
        },
        map_zoom=_zoom_for_bbox(bbox),
        title=(
            f"NO2 over {REGION_NAME} — {len(no2_mean)} cells, "
            f"{window_dates[0]:%Y-%m-%d} to {window_dates[-1]:%Y-%m-%d}"
        ),
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
    )
    return fig


def make_zonal_map(zonal, bbox, kind_label=""):
    """Choropleth of area-weighted mean NO2 per administrative zone.

    `zonal` comes from `zonal.zonal_means`. Zones whose mean was withheld (no
    overlapping valid pixel, or coverage below the threshold) are drawn in flat
    grey rather than omitted — a hole in the map reads as "no zone here", which
    is a different and wrong claim.

    Shares the `Reds` scale with `make_map` on purpose: both show the same
    quantity in the same units, so the pixel map and the zonal map stay
    visually comparable.
    """
    valued = zonal[zonal["no2_mean"].notna()]
    missing = zonal[zonal["no2_mean"].isna()]

    fig = go.Figure()

    if not missing.empty:
        fig.add_trace(go.Choroplethmap(
            geojson=json.loads(missing.to_json()),
            locations=missing["zone_id"],
            featureidkey="properties.zone_id",
            z=np.zeros(len(missing)),
            colorscale=[[0, "rgba(150,150,150,0.35)"], [1, "rgba(150,150,150,0.35)"]],
            showscale=False,
            marker_line_width=0.4,
            marker_line_color="rgba(255,255,255,0.5)",
            customdata=missing[["zone_name"]],
            hovertemplate="%{customdata[0]}<br>no NO2 coverage<extra></extra>",
        ))

    fig.add_trace(go.Choroplethmap(
        geojson=json.loads(valued.to_json()),
        locations=valued["zone_id"],
        featureidkey="properties.zone_id",
        z=valued["no2_mean"],
        colorscale="Reds",
        marker_opacity=0.8,
        marker_line_width=0.4,
        marker_line_color="rgba(255,255,255,0.5)",
        colorbar_title="NO2<br>(mol/m2)",
        colorbar_tickformat=".1e",
        customdata=valued[["zone_name", "coverage", "n_cells"]],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "mean NO2: %{z:.3e} mol/m2<br>"
            "area coverage: %{customdata[1]:.0%}<br>"
            "contributing cells: %{customdata[2]}"
            "<extra></extra>"
        ),
    ))

    label = f" — {kind_label}" if kind_label else ""
    fig.update_layout(
        map_style="open-street-map",
        map_center={
            "lat": (bbox["north"] + bbox["south"]) / 2,
            "lon": (bbox["west"] + bbox["east"]) / 2,
        },
        map_zoom=_zoom_for_bbox(bbox),
        title=(
            f"Area-weighted mean NO2 by zone{label} — "
            f"{len(valued)} of {len(zonal)} zones with data"
        ),
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
    )
    return fig


def make_timeseries(df):
    daily_mean = df.groupby("t")["NO2"].mean().reset_index()
    return px.line(
        daily_mean,
        x="t", y="NO2",
        title=f"Daily Mean NO2 — {REGION_NAME}",
        labels={"t": "Date", "NO2": "NO2 (mol/m2)"},
    )
