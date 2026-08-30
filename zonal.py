"""Area-weighted zonal statistics: NO2 pixel footprints onto admin polygons.

Each Sentinel-5P cell is ~5.5 km across, which is coarser than most of the
zones it is being aggregated onto. Therefore:

- Aggregation is area-weighted overlap, not pixel-centre-in-polygon
- Every zone carries a `coverage` fraction alongside its mean. A zone can be
  handed a confident-looking number backed by a sliver of its area (sparse
  swath days, or a zone around the bbox edge); coverage is what makes that
  visible instead of letting the choropleth imply full support.
- Zones with no overlapping valid pixel are kept, with a NaN mean. Dropping
  them would silently shrink the study area between one date range and the next.
- Pixels without a value are dropped before the overlay. Carrying a NaN pixel
  through would put its area in the weight sum but nothing in the weighted sum,
  diluting the zone mean and inflating its coverage by the same area.
"""

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from figures import grid_step

logger = logging.getLogger(__name__)

# Intersection areas must be measured in a projected CRS. A "square degree" in
# EPSG:4326 is not a constant area — at 56 N a degree of longitude spans only
# ~56% of a degree of latitude — so weighting by degree-area would tilt every
# mean toward whichever pixels sit furthest north. British National Grid is
# metre-based and is the CRS the Scottish source data ships in.
AREA_CRS = "EPSG:27700"


# from cell (x,y) makes a 'box' with one step in each direction
def cell_frame(cells, dx=None, dy=None, crs="EPSG:4326"):
    dx = grid_step(cells["x"]) if dx is None else dx
    dy = grid_step(cells["y"]) if dy is None else dy
    hx, hy = dx / 2, dy / 2

    geometry = [
        box(x - hx, y - hy, x + hx, y + hy)
        for x, y in zip(cells["x"], cells["y"])
    ]
    return gpd.GeoDataFrame(cells.copy(), geometry=geometry, crs=crs)

# Calculates means
def zonal_means(df, zones, dates=None, min_coverage=0.0):
    if zones.crs is None:
        raise ValueError("zones has no CRS — load them via boundaries.load_zones()")

    if dates is not None:
        df = df[df["t"].isin(dates)]

    if df.empty:
        raise ValueError("no NO2 rows to aggregate (empty frame or date filter)")

    # Measured before the NaN drop: an unvalued pixel still marks where the
    # grid lines are, and dropping it first can only overestimate the spacing.
    dx, dy = grid_step(df["x"]), grid_step(df["y"])

    unvalued = df["NO2"].isna()
    if unvalued.any():
        logger.info("zonal: dropping %d rows with no NO2 value", int(unvalued.sum()))
        df = df[~unvalued]

    if df.empty:
        raise ValueError("no NO2 rows to aggregate (every pixel in range is unvalued)")

    # Collapse time first: one value per cell, so the overlay runs once rather than once per date
    per_cell = (
        df.groupby(["x", "y"])
        .agg(NO2=("NO2", "mean"), n_dates=("t", "nunique"))
        .reset_index()
    )
    per_cell["cell_id"] = np.arange(len(per_cell))

    cells = cell_frame(per_cell, dx=dx, dy=dy)

    logger.info(
        "zonal: %d cells x %d zones, area-weighted in %s",
        len(cells), len(zones), AREA_CRS,
    )

    cells_proj = cells.to_crs(AREA_CRS)
    zones_proj = zones.to_crs(AREA_CRS)

    parts = gpd.overlay(
        cells_proj[["cell_id", "NO2", "n_dates", "geometry"]],
        zones_proj[["zone_id", "geometry"]],
        how="intersection",
        keep_geom_type=True,
    )

    if parts.empty:
        raise ValueError(
            "no pixel/zone intersections. Both layers reprojected without error, "
            "so check the study bbox and the zone extent actually overlap."
        )

    # The weight is the same as intersected area
    parts["weight"] = parts.geometry.area
    parts["weighted"] = parts["weight"] * parts["NO2"]

    grouped = parts.groupby("zone_id").agg(
        weighted_sum=("weighted", "sum"),
        weight_sum=("weight", "sum"),
        n_cells=("cell_id", "nunique"),
        n_dates=("n_dates", "max"),
    )
    grouped["no2_mean"] = grouped["weighted_sum"] / grouped["weight_sum"]

    zone_area = pd.Series(zones_proj.geometry.area.values, index=zones_proj["zone_id"])
    grouped["coverage"] = grouped["weight_sum"] / zone_area.reindex(grouped.index)

    out = zones.merge(
        grouped[["no2_mean", "coverage", "n_cells", "n_dates"]],
        left_on="zone_id", right_index=True, how="left",
    )
    out["coverage"] = out["coverage"].fillna(0.0)
    out["n_cells"] = out["n_cells"].fillna(0).astype(int)
    out["n_dates"] = out["n_dates"].fillna(0).astype(int)

    thin = out["coverage"] < min_coverage
    if thin.any():
        logger.info(
            "zonal: %d zones below %.0f%% coverage — mean withheld",
            int(thin.sum()), min_coverage * 100,
        )
        out.loc[thin, "no2_mean"] = np.nan

    missing = int(out["no2_mean"].isna().sum())
    if missing:
        logger.info("zonal: %d of %d zones have no usable value", missing, len(out))
    logger.info(
        "zonal: median coverage %.2f | mean NO2 range %.3e to %.3e mol/m2",
        out["coverage"].median(),
        out["no2_mean"].min(), out["no2_mean"].max(),
    )

    return out.reset_index(drop=True)


if __name__ == "__main__":
    import sys

    import pandas as pd

    from boundaries import load_zones
    from config import BBOX, CACHE_DIR, DATE_RANGE, REGION_NAME, bbox_key

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    kind = sys.argv[1] if len(sys.argv) > 1 else "councils"
    start, end = (d.replace("-", "") for d in DATE_RANGE)
    df = pd.read_parquet(
        f"{CACHE_DIR}/{REGION_NAME}_{start}_{end}_{bbox_key(BBOX)}.parquet"
    )
    stats = zonal_means(df, load_zones(kind))
    ranked = stats.sort_values("no2_mean", ascending=False)
    print(ranked[["zone_name", "no2_mean", "coverage", "n_cells"]].head(12).to_string())
