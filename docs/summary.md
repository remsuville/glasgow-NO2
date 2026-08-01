# Sentinel-5P NO₂ dashboard — architecture and analysis notes

## 1. The shape of the whole thing

Eight Python files, ~600 lines. The data flows in one direction, and each file
has exactly one job:

```
config.py      BBOX, dates, cache dir          (constants — no logic)
    │
data.py        CDSE openEO ──► NetCDF ──► DataFrame ──► parquet cache
    │            (t, y, x, NO2 — one row per pixel per date)
    │
boundaries.py  shapefile ──► validate ──► reproject 27700→4326 ──► parquet cache
    │            (zone_id, zone_name, geometry)
    │
zonal.py       df + zones ──► area-weighted overlay ──► per-zone means
    │            (zone_id, zone_name, no2_mean, coverage, n_cells, n_dates, geometry)
    │
figures.py     any of the above ──► Plotly figures     (pure — no I/O, no state)
    │
layout.py      the widgets                             (static description)
callbacks.py   wires widgets ──► data ──► figures       (the only orchestration)
app.py         boots Dash, installs logging
```

The key structural property: `figures.py` never fetches anything and `data.py`
never draws anything. All the wiring lives in `callbacks.py`. That is what makes
the whole pipeline testable headlessly.

---

## 2. The data ("the database")

There is no database — it is a parquet cache directory plus downloaded
shapefiles. Both are gitignored (`.gitignore` keeps `boundaries/README.md` and
drops everything else).

### 2a. The NO₂ grid — `cache/Central Belt_2024-06-01_2024-06-28.parquet`

4,197 rows × 4 columns, 147 KB. One row = one pixel on one date.

| col | type | meaning |
|---|---|---|
| `t` | datetime64 | the date |
| `y` | float64 | latitude of the cell centre |
| `x` | float64 | longitude of the cell centre |
| `NO2` | float32 | tropospheric column density, mol/m² |

**The grid.** 42 unique longitudes × 18 unique latitudes = 756 possible cells.
Steps are 0.05456° lon and 0.03472° lat, which at 56°N works out to
3.40 km × 3.84 km ≈ 13 km² per cell.

**How the grid is anchored** — the "centre vs corner" trap, and it came out
right:

```
first x centre          -5.072718253968258
BBOX west + dx/2      = -5.072718253968258   ← exact match
last y centre + dy/2  = 56.2                 ← exactly BBOX north
```

So the grid origin is the top-left corner (west, north) and cells march east and
south — the standard raster convention. Because the bbox isn't an integer number
of cells wide, the grid overhangs slightly past the east and south edges. That
is not a bug, and it matters that `cell_polygons` reconstructs footprints as
centre ± half-step: it recovers the true extents exactly.

**The data is sparse**, and this drives real design decisions. Average 191 rows
per date out of 756 possible cells — about 25% coverage on a typical day:

- rows per date: min 2, median 116, max 724
- 22 dates present out of the 28 requested — 6 days have no data at all

Sentinel-5P is a polar orbiter; one overpass per day, and the swath edge, cloud,
and quality filtering knock out most cells. That sparsity is the direct reason
`make_map` does its "best day ± 4 days" window rather than plotting a single
date — a single date would frequently be nearly empty.

### 2b. The boundaries

Three shapefiles, all EPSG:27700 (British National Grid, metres), all from
Spatial Hub Scotland under OGL:

| set | file | features | median area | invalid geoms |
|---|---|---|---|---|
| `councils` | `councils/pub_las.shp` | 32 | 995 km² | 0 |
| `intzones` | `intzones_2022/…_MHW.shp` | 1,334 | 1.53 km² | 0 |
| `datazones` | `datazones_2022/…_2022.shp` | 7,392 | 0.21 km² | 1 |

That one invalid data-zone geometry is real, and it is why `_repair_geometry`
exists — `make_valid()` fixes it silently on load. Without that, the overlay
would throw.

The 2022 zone files also carry population columns (`TotPop2022`, `hhcnt2022`, …)
that are currently discarded. Those are the obvious route to population-weighted
exposure later.

### 2c. Cache layout

```
cache/Central Belt_<start>_<end>.parquet   NO2, keyed by region + date range
cache/zones_<kind>_whole.parquet           reprojected zones, keyed by kind + clip mode
```

Both are keyed by everything that affects their content, so a changed input
means a changed filename rather than a stale hit.
`boundaries.load_zones(use_cache=False)` is the escape hatch when `ZONE_SETS`
changes.

### 2d. The one number that defines this project

```
              median contributing pixels per zone
councils               40          ← genuinely oversampled
intzones                2          ← 64% of zones fed by ≤2 pixels
datazones               1          ← 63% fed by exactly ONE pixel
```

A pixel is 13 km². The median data zone is 0.21 km² — the pixel is ~62× larger
than the thing being aggregated onto. This is the single most important fact
about the project, and it is why area weighting rather than centre-in-polygon
was non-negotiable.

It also bounds what the zone sets can claim. Councils are the only set genuinely
coarser than the pixel grid. Intermediate Zones are better than Data Zones but
still mostly sub-pixel, so the choice between the two is closer to a
presentation preference than to a gain in spatial detail.

---

## 3. Script by script

### `config.py` — 12 lines

`BBOX` (Central Belt, ~2.25° × 0.6°), `REGION_NAME`, `CACHE_DIR`, `DATE_RANGE`
defaults. `BBOX` is a plain dict with west/south/east/north keys because that is
the shape openEO's `spatial_extent` wants — it gets passed straight through in
`data.py:34`.

### `data.py` — the only network I/O

```
get_no2(start, end)
  ├─ cache hit? return parquet                      ← the rate-limit guard
  ├─ openeo.connect + authenticate_oidc()
  ├─ load_collection("SENTINEL_5P_L2", bbox, dates, bands=["NO2"])
  ├─ download to a UNIQUE temp .nc
  ├─ xr.open_dataset → to_dataframe → dropna
  ├─ finally: unlink the .nc
  └─ filter NO2 > 0, write parquet
```

Three details that are deliberate:

- **Unique temp filename** (line 40) — a shared `{city}_temp.nc` previously
  cross-contaminated concurrent requests.
- **`with xr.open_dataset(...)` + `finally: os.remove`** — the context manager
  releases the handle before unlink, and `to_dataframe()` materialises inside
  the block so nothing lazily reads a deleted file. The `finally` means a failed
  conversion doesn't leave NetCDF litter.
- **`authenticate_oidc()`** does device-flow OAuth and caches the token to disk,
  which is why it doesn't prompt every run.

⚠️ `df = df[df['NO2'] > 0]` on line 56 is a genuine analytical problem. Negative
NO₂ column retrievals are legitimate Sentinel-5P output — in clean air the
retrieval noise straddles zero, and negative values are the low tail of that
distribution, not corrupt data. Dropping them biases every mean upward, and the
bias is worst exactly where concentrations are lowest (rural zones). ESA's own
guidance is to keep negatives and filter on `qa_value` instead. See §5.

### `boundaries.py` — the CRS-discipline file

This file's whole reason to exist is that a CRS mismatch fails silently. No
exception, no warning — just every pixel assigned to the wrong zone. So it
asserts instead of trusting.

```
load_zones(kind, bbox=None, clip=False, use_cache=True)
  ├─ _find_source(kind)      glob patterns → the actual file
  ├─ inspect_source(path)    the "QGIS pass", in code: CRS, columns,
  │                          geom types, validity, native bounds
  ├─ _pick_column ×2         resolve zone_id / zone_name case-insensitively
  ├─ _repair_geometry        make_valid(), drop empty/missing
  ├─ _reproject              27700 → 4326, with a hard envelope check
  ├─ intersect with bbox     (select, don't clip, by default)
  └─ cache to parquet
```

Four pieces worth understanding:

**`SCOTLAND_ENVELOPE`** (line 31) is the cleverest guard here. BNG coordinates
are eastings/northings in the hundreds of thousands; lat/lon is bounded by ±180.
So if a reprojection silently didn't happen, the bounds blow past -9.0 … 61.0
and `_reproject` raises. It turns the silent failure loud. Observed passing:
W-8.6500 S54.6332 E-0.7244 N60.8608.

**Refusing to guess a missing CRS** (line 140). If `gdf.crs` is None it raises
rather than calling `set_crs`. This is the right call — `set_crs` only labels
data, it doesn't transform it, so guessing is exactly how metres get stamped as
degrees.

**Select vs clip** (line 200). The default keeps whole geometries that intersect
the bbox. Clipping would silently redefine what a zone mean covers — "Fife"
would stop meaning Fife. The consequence is that edge zones have partial
coverage, which is precisely what `coverage` in `zonal.py` then quantifies.

**`ZONE_SETS` is the extension point.** Each entry is glob patterns plus
candidate column names. Spatial Hub ships councils as `pub_las.shp` with no
"council" or "LAD" in the name, so none of the original patterns matched and
`load_zones("councils")` raised `FileNotFoundError`.

### `zonal.py` — the analytical core

```
zonal_means(df, zones, dates=None, min_coverage=0.0)
  ├─ optional date filter
  ├─ groupby(x,y).mean()          collapse TIME first ← perf decision
  ├─ cell_frame()                 centres → shapely boxes
  ├─ both layers → EPSG:27700     ← correctness decision
  ├─ gpd.overlay(intersection)    every (cell, zone) overlap fragment
  ├─ weight = fragment area
  ├─ groupby(zone_id):
  │     no2_mean = Σ(weight·NO2) / Σ(weight)
  │     coverage = Σ(weight) / zone_area
  ├─ merge back onto ALL zones (left join)  ← keeps empty zones
  └─ withhold means below min_coverage
```

**Why collapse time first.** The weighting is purely spatial, so the temporal
mean commutes with it. Doing it up front means the expensive overlay runs once
instead of once per date — the difference between 1.5s and ~30s on data zones.

**Why EPSG:27700 for the areas.** A "square degree" isn't a constant area. At
56°N a degree of longitude spans only ~56% of a degree of latitude. Weighting by
degree-area would systematically over-weight whatever sits furthest north. This
is the subtlest correctness point in the codebase and the one most worth being
able to explain out loud.

**Why area-weighted at all.** With 63% of data zones containing no pixel centre,
a centre-in-polygon test would return nothing for most of the map.

**Why `coverage` exists.** A zone can get a confident-looking mean backed by a
sliver of its area. Perth and Kinross sits 0.9% inside the bbox — without
coverage it would render as a fully-coloured council implying a Perth-wide
measurement. `MIN_COVERAGE = 0.10` in `callbacks.py` withholds those.

**Why empty zones are kept.** The `how="left"` merge means zones with no data
survive with NaN. Dropping them would make the study area silently shrink and
grow between date ranges.

**Verification worth remembering:** weighted means differ from naive unweighted
means by up to 10.3%, so the weighting demonstrably does work; and no zone's
coverage exceeds 1.0, which proves the overlay isn't double-counting.

### `figures.py` — pure functions, no I/O

- **`grid_step`** — median of `diff(unique(coords))`. The median matters: the
  grid is sparse, so some gaps are multiples of the true step (a missing row),
  never smaller. Mean would be wrong; median is robust.
- **`cell_polygons`** — centres → GeoJSON rectangles for Plotly.
- **`cell_frame`** (in `zonal.py`) — same footprints as shapely boxes for the
  overlay. Two forms of one idea, deliberately.
- **`make_map`** — the "best day ± 4" window, existing purely because of
  sparsity. Note line 78: `grid_step` is computed from the full frame, not the
  window, because a sparse window can miss whole rows and overestimate spacing.
- **`make_zonal_map`** — two traces: grey for withheld zones, `Reds` for valued.
  Withheld zones are drawn, not omitted, because a hole in a choropleth reads as
  "no zone here" — a different and false claim. Shares the `Reds` scale with
  `make_map` so the two views stay comparable.

### `layout.py` / `callbacks.py` / `app.py`

`layout.py` is a static widget tree. `app.py` is 25 lines: configure logging,
instantiate Dash, register callbacks, run.

`callbacks.py` has two callbacks, and the split is the important part:

```
commit_range:  Submit ──► dcc.Store("submitted-range")
update_charts: Store + map-view ──► both figures
```

The `dcc.Store` is the rate-limit gate. If the charts read dates directly from
the picker, changing the map view after editing dates-but-not-submitting would
fire a fresh CDSE pull. Routing through the store means the view dropdown can
only ever hit already-fetched data. That preserves the guarantee the Submit
button was added for.

---

## 4. The three ideas that make this a GIS project rather than a plotting project

1. **CRS is never implicit.** Every transform is logged, and an envelope
   assertion catches the silent failure.
2. **Pixels have footprints, not positions.** A satellite pixel is a 13 km²
   area. Once it is modelled as a rectangle rather than a point, correct
   aggregation becomes possible.
3. **Aggregation carries its own uncertainty.** `coverage` and `n_cells` travel
   alongside `no2_mean`, so the map can decline to make claims it can't support.

---

## 5. Honest weaknesses — what to expect to be challenged on

1. **The `NO2 > 0` filter biases means upward** (`data.py:56`). Real fix: keep
   negatives, filter on `qa_value` instead. Highest-value change in the
   codebase.
2. **No `qa_value` filtering at all.** Standard S5P practice is
   `qa_value > 0.75` to drop cloud, snow/ice, and problematic retrievals.
   Whether openEO's `SENTINEL_5P_L2` applies this upstream can't be told from
   the cached parquet — it needs checking against the collection metadata.
3. **Sub-pixel zones.** Data zones are 62× smaller than a pixel; the "mean" for
   63% of them is one pixel value. Defensible only if stated explicitly.
4. **Unweighted temporal mean.** A date with 2 valid cells counts as much as one
   with 724. Should probably weight by valid-cell count, or at least report
   `n_dates` (it is computed — nothing consumes it yet).
5. **Tropospheric column ≠ ground concentration.** Column density in mol/m² is
   not what an air-quality regulator measures (µg/m³ at 2 m). Converting needs
   boundary-layer height assumptions. Don't overclaim.
6. **No tests.** Nothing prevents a regression in the weighting maths.
7. **Legacy files** — `glasgow_NO2.nc`, `first_NO2_data.ipynb`,
   `connection_list.txt` are from early exploration and no longer feed anything.
