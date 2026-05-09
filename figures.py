import plotly.express as px


def _zoom_for_bbox(bbox):
    max_range = max(bbox["north"] - bbox["south"], bbox["east"] - bbox["west"])
    if max_range > 2:
        return 7
    if max_range > 1:
        return 8
    if max_range > 0.5:
        return 9
    return 10


def make_map(df, city, bbox):
    valid_counts = df.groupby("t")["NO2"].count()
    best_day = valid_counts.idxmax()
    all_dates = sorted(df["t"].unique())
    best_idx = list(all_dates).index(best_day)
    t_start = max(0, best_idx - 4)
    t_end = min(len(all_dates) - 1, best_idx + 4)
    window_dates = all_dates[t_start : t_end + 1]
    window_df = df[df["t"].isin(window_dates)]
    no2_mean = window_df.groupby(["x", "y"])["NO2"].mean().reset_index()

    return px.density_map(
        no2_mean,
        lat="y", lon="x", z="NO2",
        radius=20,
        center={
            "lat": (bbox["north"] + bbox["south"]) / 2,
            "lon": (bbox["west"] + bbox["east"]) / 2,
        },
        zoom=_zoom_for_bbox(bbox),
        map_style="open-street-map",
        title=f"NO₂ over {city} — 9-day mean (June 2024)",
        color_continuous_scale="Reds",
    )


def make_timeseries(df, city):
    daily_mean = df.groupby("t")["NO2"].mean().reset_index()
    return px.line(
        daily_mean,
        x="t", y="NO2",
        title=f"Daily Mean NO2 — {city} (June 2024)",
        labels={"t": "Date", "NO2": "NO2 (mol/m2)"},
    )