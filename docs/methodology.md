# Methodology

How a Sentinel-5P retrieval becomes a number on a Scottish
administrative zone, with examples :)

Every figure in this document was computed from parquet covering
2024-06-01 to 2024-06-28 using the reproduction script in
[§9](#9-reproducing-these-numbers).

---

## 1. The pipeline

```
CDSE openEO  ──►  NetCDF  ──►  DataFrame (t, y, x, NO2)  ──►  parquet     data.py
Shapefile    ──►  validate ──► reproject ──► simplify ──► select          boundaries.py
                                    │
        pixel centres ──► cell footprints ──► overlay ──► area weights    zonal.py
                                    │
                            per-zone mean + coverage  ──► choropleth      figures.py
```

Each stage is a pure function of its inputs and is cached to parquet, so the
whole chain can be re-run offline once a date range has been fetched once.

---

## 2. What is in source data?

`data.py` requests the `SENTINEL_5P_L2` collection, band `NO2`, from the
Copernicus Data Space openEO backend:

```python
datacube = get_connection().load_collection(
    "SENTINEL_5P_L2",
    spatial_extent=BBOX,
    temporal_extent=[start_date, end_date],
    bands=["NO2"]
)
```

The band is **tropospheric NO₂ vertical column density**, in **mol/m²**
-> The number of moles of NO₂ in a column of air of unit cross-section, integrated from
the ground to the tropopause. It is not a concentration at breathing height.
See [§8](#8-what-these-numbers-do-not-mean).

openEO delivers the L2 data re-sampled onto a lat/lon grid,
which is what makes the rectangular-footprint model in [§3](#3-grid-geometry).
The NetCDF is flattened to one row per (date, cell) and cached:

```python
with xr.open_dataset(temp_file) as ds:
    df = ds['NO2'].to_dataframe(name='NO2').reset_index().dropna()
```

`.dropna()` removes cells with no retrieval at all. For the reference window,
that leaves **76,824 rows** across **27 dates**.

| quantity | value |
|---|---|
| rows (date × cell observations) | 76,824 |
| distinct dates | 27 |
| distinct cells observed | 13,068 |
| NO₂ median | 1.5 × 10⁻⁵ mol/m² |
| NO₂ range | −4.5 × 10⁻⁵ … 1.02 × 10⁻⁴ mol/m² |
| rows with NO₂ < 0 | 5,767 (7.5%) |

Negative values are **retained**, deliberately — see
[§8](#8-what-these-numbers-do-not-mean).

---

## 3. Grid geometry

Each row carries a cell *centre*, not a footprint. The footprint has to be
reconstructed from the data rather than be hard-coded, so that a change
in the backend's resampling cannot silently go unnoticed.

`figures.grid_step` derives the spacing:

```python
def grid_step(values):
    unique = np.unique(np.asarray(values))
    if unique.size < 2:
        raise ValueError("need at least two distinct coordinates to infer grid step")
    return float(np.median(np.diff(unique)))
```

The **median** of the gaps, not the mean or the minimum. The grid is relatively
sparse, so date with no swath coverage leaves whole columns empty. Therefore, some
gaps between *observed* coordinates are integer multiples of the true step.
A multiple can never be smaller than the step, so the median of a mostly-complete axis
lands on the true value, while the mean would be pulled upward.

For the reference window:

```
x (longitude): 110 distinct values, −7.6727 … −1.7253,  every diff = 0.05456349°
y (latitude):  119 distinct values,  54.5854 …  58.6826, every diff = 0.03472222°
```

Every difference is equal to the median, which confirms that the grid is regular.

**Footprint in metres.** At 56 °N:

```
dx = 0.05456349° × 111.320 km/° × cos(56°)  =  3.40 km
dy = 0.03472222° × 110.574 km/°             =  3.84 km
area ≈ 3.40 × 3.84                          =  13.1 km²
```

Measured properly by reprojecting the rectangles to EPSG:27700, the cell areas
run **12.23 – 13.67 km², median 12.95 km²** — the spread is the latitude
dependence of a degree of longitude across a 4° tall study area, and this is
why weights are done in metres rather than degrees.
(See [§5](#5-why-epsg27700))

`zonal.cell_frame` turns centres into footprints by adding a step around the centre:

```python
def cell_frame(cells, dx=None, dy=None, crs="EPSG:4326"):
    dx = grid_step(cells["x"]) if dx is None else dx
    dy = grid_step(cells["y"]) if dy is None else dy
    hx, hy = dx / 2, dy / 2

    geometry = [
        box(x - hx, y - hy, x + hx, y + hy)
        for x, y in zip(cells["x"], cells["y"])
    ]
    return gpd.GeoDataFrame(cells.copy(), geometry=geometry, crs=crs)
```

`figures.cell_polygons` does the same thing as raw GeoJSON for the unaggregated
map view, so the pixel layer on screen and the pixel layer in the maths are the
same rectangles.

---

## 4. Temporal collapse

Time is collapsed **before** the geometry, not after:

```python
per_cell = (
    df.groupby(["x", "y"])
    .agg(NO2=("NO2", "mean"), n_dates=("t", "nunique"))
    .reset_index()
)
```

76,824 date×cell rows combine to **13,068 cells** for the given time period.

*Performance:* The polygon overlay is the compute-heavy step. Running it once on
13,068 rectangles instead of once per date on 27 partial grids is roughly a
6x saving, and results in temporal mean.

*Consequence:* the per-cell mean is **unweighted in time**. Sentinel-5P is a
polar orbiter with limited overpasses a day, and cloud and swath edges remove most
of the grid on most days:

| | value |
|---|---|
| observations on the fullest day | 10,762 cells (82.2% of the grid) |
| observations on the emptiest day | 212 cells (1.6%) |
| median day | 2,449 cells (18.7%) |
| dates contributing per cell | median 5, mean 5.9, max 18, min 1 |

So a cell's value is the mean of however many clear overpasses it did over the given
time period. `n_dates` is also carried through the whole pipeline just in case.

---

### 4.1 The pixel view uses a shorter window

The unaggregated grid view is not the whole date range. `figures.make_map`
centres a nine-day window on the best-covered day, because a full month of
overlapping partial swaths averages the spatial structure away:

```python
valid_counts = df.groupby("t")["NO2"].count()
best_day = valid_counts.idxmax()
...
t_start = max(0, best_idx - 4)
t_end = min(len(all_dates) - 1, best_idx + 4)
window_dates = all_dates[t_start : t_end + 1]
```

The grid step is still taken from the **full** frame, not the window.
Thus, a short time window can miss whole rows and overestimate the spacing:

```python
dx, dy = grid_step(df["x"]), grid_step(df["y"])
```

The zonal views use the entire submitted range. The two map views answer
slightly different questions, and the pixel map's title states the window
it actually drew.

---

## 5. Why EPSG:27700

The overlay and every area in it are computed in **British National Grid**, not
in degrees:

```python
AREA_CRS = "EPSG:27700"
...
cells_proj = cells.to_crs(AREA_CRS)
zones_proj = zones.to_crs(AREA_CRS)
```

An area in degrees squared is not really a unit of area.

At 54.6 °N, a degree of longitude equals 64.5 km
At 58.7 °N, a degree of longitude equals 57.8 km
-> ~10% shrink across the study area!

Therefore, a 11% difference in every weight would happen if degree-area were used and
zones in the far north would be weighted as if their pixels were larger than they are.
EPSG:27700 is metre-based and is the CRS the Scottish boundary data comes as,
which ultimately why this method is being used.

The raster is *not* reprojected to 27700 for display, and the vectors *are*
reprojected to 4326 on load, because transforming a few thousand polygons is
far cheaper than resampling a full grid:

```python
TARGET_CRS = "EPSG:4326"
```

In a nutshell: 4326 is used for storage and drawing, 27700 for
measurement, and the conversion happens inside `zonal_means` where the areas
are needed.

**CRS is never presumed.** A missing `.prj` is a hard error, not a guess:

```python
if gdf.crs is None:
    raise ValueError(
        f"'{kind}' has no CRS (missing or malformed .prj). Refusing to guess — "
        "identify the true CRS and apply set_crs() explicitly at the call site."
    )
```

and the reprojected bounds are asserted to land inside Scotland's lat/lon
envelope, which turns the classic silent CRS failure (every pixel assigned to
the wrong zone, no exception raised) into a loud error.

---

## 6. Area-weighted zonal statistics

### 6.1 The estimator

For zone *Z* and the set of pixel/zone intersection fragments *f* ∈ *Z*:

```
                 Σ_f  area(f) · NO₂(f)
mean NO₂(Z)  =  ─────────────────────
                    Σ_f  area(f)


                    Σ_f  area(f)
coverage(Z)  =  ─────────────────────
                       area(Z)
```

where `area(f)` is the area **of the intersection**, in m², and `NO₂(f)` is the
temporally-collapsed value of the pixel found earlier. In code:

```python
parts = gpd.overlay(
    cells_proj[["cell_id", "NO2", "n_dates", "geometry"]],
    zones_proj[["zone_id", "geometry"]],
    how="intersection",
    keep_geom_type=True,
)

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
```

`gpd.overlay(..., how="intersection")` is the whole geometric engine: it emits
one row per (cell, zone) pair that overlaps, carrying the attributes of both and
the geometry of the overlap. `keep_geom_type=True` discards the degenerate
line- and point-shaped intersections produced by edges that merely touch, which
would otherwise enter the sum with zero area but a real NO₂ value.

### 6.2 A worked example:

Intermediate Zone **S02003355 — Port Glasgow Upper East**. Area in EPSG:27700:
**772,965.7 m²** (0.773 km²), e.g. ~1/17 of a single Sentinel-5P cell.

Four fragments overlap it:

| cell | centre (lon, lat) | NO₂ (mol/m²) | n_dates | fragment area (m²) | share of zone |
|---|---|---|---|---|---|
| 6562 | −4.6717, 55.9049 | 1.326077 × 10⁻⁵ | 6 | 481,870.0 | 62.34% |
| 6563 | −4.6717, 55.9396 | 9.550583 × 10⁻⁶ | 6 | 282,663.0 | 36.57% |
| 6681 | −4.6172, 55.9049 | 1.673690 × 10⁻⁵ | 6 | 2,208.1 | 0.29% |
| 6682 | −4.6172, 55.9396 | 1.684967 × 10⁻⁵ | 7 | 6,224.6 | 0.81% |

Numerator:

```
481,870.0 × 1.326077e-05  =  6.38997
282,663.0 × 9.550583e-06  =  2.69954
    2,208.1 × 1.673690e-05  =  0.03696
    6,224.6 × 1.684967e-05  =  0.10488
                            ───────────
              weighted_sum  =  9.231404      (mol/m² · m²)
```

Denominator:

```
481,870.0 + 282,663.0 + 2,208.1 + 6,224.6  =  772,965.7 m²  (=  weight_sum)
```

Result:

```
no2_mean  =  9.231404 / 772,965.7   =  1.194284e-05 mol/m²
coverage  =  772,965.7 / 772,965.7  =  1.000000
```

The unweighted mean of those same four pixel values is **1.409948 × 10⁻⁵**
(or 18.1% higher). Two of the four cells contribute 1% of the zone's area
between them, and both happen to be the high ones. With zones smaller
than the pixels, *which* pixels touch a zone is far less informative
compared to *how much* of the zone each one covers.

### 6.3 Why not centre-in-polygon

The conventional zonal-statistics shortcut is to assign a pixel to whichever
polygon contains its centre, and it fails outright at scales used here.
A Sentinel-5P cell is ~13 km², median Data Zone is 0.20 km², or about **65× smaller**.
Most zones contain no pixel centre at all, so a centre-in-polygon pass returns nothing for
the majority of the map. Area weighting instead gives every zone the mixture of
the pixels physically above it.

### 6.4 Zones without data are kept, not dropped

```python
out = zones.merge(
    grouped[["no2_mean", "coverage", "n_cells", "n_dates"]],
    left_on="zone_id", right_index=True, how="left",
)
out["coverage"] = out["coverage"].fillna(0.0)
```

A left join, so a zone with no overlapping pixel survives with `no2_mean = NaN`
and `coverage = 0`. Dropping it would make the study area quietly change shape
between one date range and the next, and `figures.make_zonal_map` draws these
zones in grey rather than omitting them.

---

## 7. Coverage and withholding Mean

Coverage is the fraction of a zone's area that any valid pixel sat over. It
travels with the mean into the hover card and into the decision of
whether the mean is shown at all:

```python
thin = out["coverage"] < min_coverage
if thin.any():
    logger.info(
        "zonal: %d zones below %.0f%% coverage — mean withheld",
        int(thin.sum()), min_coverage * 100,
    )
    out.loc[thin, "no2_mean"] = np.nan
```

`callbacks.py` sets the threshold:

```python
MIN_COVERAGE = 0.10
```

**For example, the Orkney Islands:** The study bbox stops at 58.70 °N, which
clips the very southern tip of the council area. Orkney's fragments total
**0.055%** of its area and is therefore shown as grey.

Without the check, Orkney would be shaded from just two pixels overlapping the zone
and the choropleth would imply a measured value for the whole zone.

(This is the same failure that once affected Perth and Kinross under
the older Central Belt bbox, which sat ~1% inside the box)

Under the current Scotland-wide bbox, coverage is near-total almost everywhere —
only 4 councils, 9 Intermediate Zones and 15 Data Zones fall below 99.9%, and
only one zone in each set is withheld (e.g. Shetlands).

---

## 8. What these numbers DO NOT mean

**Tropospheric column IS NOT ground concentration.** The output is mol/m² through the
whole troposphere. Air-quality regulation uses µg/m³ at ~2 m. Converting between
them requires a boundary-layer assumptions, neither of which is made here (YET!).
A high column can mean a polluted surface or a deep, well-mixed layer.

**Negative retrievals are retained.** 7.5% of rows in the reference window are
negative, and after aggregation the minimum zone mean is −7.3 x 10⁻⁸ mol/m²
(Intermediate Zones) and −3.0 x 10⁻⁶ (Data Zones). This is intentional: over
clean air the retrieval's noise approach zero, and negative values are
legitimate low end of that distribution. Discarding them would bias every mean
upward, and could cause severe errors where concentrations are lowest.
**Something that a pollution map should never get wrong!** The correct filter is
`qa_value` for statistically more relevant measurements.

**The finer zone sets do not add spatial detail.** Council areas are the only
set genuinely coarser than the pixel grid:

| zone set | national | in bbox | median area | median cells/zone | ≤ 1 cell | ≤ 2 cells |
|---|---|---|---|---|---|---|
| Council areas | 32 | 31 | 903.77 km² | 80 | 0% | 3% |
| Intermediate Zones 2022 | 1,334 | 1,322 | 1.53 km² | 2 | 21% | 56% |
| Data Zones 2022 | 7,392 | 7,330 | 0.20 km² | 1 | 57% | 84% |

57% of Data Zones are fed by a single pixel, so whole neighbourhoods return
byte-identical means. The Data Zone map is a *presentation* of the pixel grid at
administrative boundaries, not a "better" measurement.

**Boundary simplification.** Geometry is simplified at
`SIMPLIFY_TOLERANCE = 0.001` degrees (~110 m at this latitude) before the
overlay, which makes areas at the sub-pixel scale more rough. Against a 3.4km
pixel this is negligible; against a 0.20 km² Data Zone it is not nothing, and it
should probably be recalculated in different manner if Data Zone output is ever used
quantitatively.

**Intermediate Zones ship in two coastal variants.** `ZONE_SETS["intzones"]`
pins `_MHW` (mean high water) rather than `_EoR` (extent of realm). `_EoR`
polygons run out to sea, so a zone mean would average NO₂ over open water and
dilute the land signal.

---

## 9. Reproducing these numbers

Every figure above comes out of the cached parquet with no network access.
The cache is not committed — run the dashboard once over `DATE_RANGE` to
fetch it, and the filename below is what `data.py` writes:

```python
import pandas as pd, numpy as np, geopandas as gpd
from boundaries import load_zones
from figures import grid_step
from zonal import cell_frame, zonal_means, AREA_CRS

df = pd.read_parquet("cache/Scotland_20240601_20240628_2e525b00.parquet")

# 3. grid geometry
dx, dy = grid_step(df["x"]), grid_step(df["y"])          # 0.05456349, 0.03472222

# 4. temporal collapse
per_cell = (df.groupby(["x", "y"])
              .agg(NO2=("NO2", "mean"), n_dates=("t", "nunique"))
              .reset_index())
per_cell["cell_id"] = np.arange(len(per_cell))           # 13,068 cells

# 6.2 the worked example, fragment by fragment
cells = cell_frame(per_cell, dx=dx, dy=dy).to_crs(AREA_CRS)
zones = load_zones("intzones").to_crs(AREA_CRS)
zone = zones[zones["zone_id"] == "S02003355"]

parts = gpd.overlay(cells[["cell_id", "NO2", "geometry"]],
                    zone[["zone_id", "geometry"]],
                    how="intersection", keep_geom_type=True)
parts["weight"] = parts.geometry.area
parts["weighted"] = parts["weight"] * parts["NO2"]

print(parts[["cell_id", "NO2", "weight"]].to_string())
print(parts["weighted"].sum() / parts["weight"].sum())   # 1.194284e-05
print(parts["NO2"].mean())                               # 1.409948e-05
print(parts["weight"].sum() / zone.geometry.area.iloc[0])# 1.000000

# 7. the withheld zone
councils = zonal_means(df, load_zones("councils"), min_coverage=0.10)
print(councils.loc[councils["zone_name"] == "Orkney Islands",
                   ["coverage", "n_cells", "no2_mean"]])
```

`python zonal.py intzones` prints the ranked table for a whole zone set the same
way.

---

## 10. Sources and attribution

- **NO₂** — Copernicus Sentinel-5P TROPOMI L2, via the
  [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) openEO
  API. Contains modified Copernicus Sentinel data.
- **Boundaries** — [Spatial Hub Scotland](https://spatialdata.gov.scot), Open
  Government Licence v3.0. Attribution required on published output.
- **Orbits** — TLE elements from [CelesTrak](https://celestrak.org),
  propagated with SGP4 via [Skyfield](https://rhodesmill.org/skyfield/). TLE
  accuracy degrades roughly 1 km/day from epoch, so cached elements in
  `globe/data/*.tle` go quietly stale; delete them to force a refetch.
