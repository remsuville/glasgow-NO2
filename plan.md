# glasgow-NO2 — Current Work Plan

Repo: `remsuville/glasgow-NO2` · Local: `~/copernicus_project/` (Arch, fish, venv at `venv/`)

## Context

Dash dashboard showing Sentinel-5P NO₂ over Scotland. Core pipeline works: CDSE openEO
auth, data pull, xarray processing, parquet caching, modular app
(`config.py`, `data.py`, `figures.py`, `layout.py`, `callbacks.py`, `app.py`).

We are deliberately **narrowing scope** to one area and getting the spatial handling
correct before adding anything else. The end goal for this phase is zonal statistics
over Scottish administrative geographies, plus a boundary "what-if" scenario — this is
targeted at GIS/EO job applications, so the spatial correctness matters more than
feature count.

---

## Task 1 — Remove city selection

Strip multi-city support entirely. Central Belt only.

- Remove the city dropdown from `layout.py`
- Remove the city branch/argument from `callbacks.py`
- Reduce `config.py` to a single hardcoded Central Belt bbox
- Simplify `get_no2()` signature accordingly (no `city` param, or keep it defaulted)
- Keep the existing cache files working — don't invalidate the Central Belt parquet

**Rationale:** fewer moving parts while fixing the rendering. Multi-city returns later
only if useful.

---

## Task 2 — Render true grid cells, not a smoothed blob

Current problem: `figures.py` uses Plotly `density_map`, which does KDE-style
interpolation between points. The output looks like a soft blur. Sentinel-5P NO₂ has a
real underlying grid (~3.5 × 5.5 km native at nadir, resampled by openEO onto a regular
lat/lon grid), and that structure is currently being smoothed away.

- Inspect the dataframe going into the map trace: column names, one row per pixel per
  date?, spacing between adjacent lat/lon values (this reveals the actual grid resolution)
- Replace `density_map` with a rendering that draws **discrete cells with real lat/lon
  extents** — each pixel as a rectangle covering its true footprint, not an interpolated
  point. Options: Plotly `Heatmap`, `Choroplethmap` with per-cell polygons, or an
  `imshow`-style raster overlay on the basemap
- Verify cell edges align with the requested bbox — no off-by-one shift, no half-cell
  offset (centre vs corner coordinate convention is the usual culprit)

**This is a prerequisite for Task 4, not just a cosmetic fix.** Zonal statistics need
each pixel to have a real footprint so overlap with polygons can be computed.

---

## Task 3 — Load boundaries and reproject deliberately

- Source Scottish council area boundaries (and consider data zones — smaller polygons
  make the zonal stats more interesting) from data.gov.uk / Spatial Hub Scotland
- Inspect in QGIS first: check geometry validity, attribute columns, and CRS
- Load in Python with `geopandas`
- **Print/assert the CRS of both datasets explicitly in code.** Do not rely on
  defaults. NO₂ from openEO is EPSG:4326 (lat/lon degrees); Scottish vector data will
  almost certainly be EPSG:27700 (British National Grid, metres)
- Reproject the **vectors** to 4326 to match the raster (reprojecting vectors is far
  cheaper than reprojecting rasters)
- Reproject *before* any overlay. A CRS mismatch fails silently — no exception, just
  wrong answers with every pixel misassigned

---

## Task 4 — Zonal statistics

- Overlay the gridded NO₂ raster with the council/datazone polygons
- Compute a mean NO₂ value per zone (`rasterstats`, or `rioxarray` + geopandas)
- Decide and document the aggregation rule: pixel-centre-in-polygon vs
  area-weighted overlap. Area-weighted is more correct given the coarse pixel size
  relative to some zones — a single Sentinel-5P pixel can span multiple data zones
- Handle NaN pixels and zones with no valid data explicitly
- Render as a choropleth in the dashboard

---

## Task 5 — The "what if" scenario

- Recompute zonal means against a *different* boundary set: swap councils ↔ data zones,
  or merge/redraw polygons
- Show what changed — before/after comparison in the dashboard, or a diff table
- Keep the zonal stats function generic enough that this is just "call it again with
  different geometries," not a rewrite

**Why this matters:** the deliverable is being able to say "I built spatial aggregation
over administrative geographies and modelled the effect of altering the boundaries."
The code should make that claim true and demonstrable.

---

## Deferred (do not start yet)

- Incremental cache gap-detection + 2023–present backfill (`cache.py` / `backfill.py`
  drafts exist but are on hold until the spatial work is done)
- ML forecasting: daily-mean time series, lag features, chronological train/test split,
  persistence baseline → linear regression → random forest
- ERA5 weather features joined to the NO₂ series
- Gunicorn/Nginx deployment

---

## Known gotchas (carry forward)

- CDSE collection ID is `SENTINEL_5P_L2` — **not** `SENTINEL_5P_L2__NO2___`
- `pyarrow` is the parquet engine; the `parquet` pip package is a dummy
- Temp `.nc` filenames must be unique per request — a shared `{city}_temp.nc` previously
  caused cross-contamination between requests
- Hardcoded `temporal_extent` dates in `data.py` will silently override user-selected
  dates — always wire date inputs through to the API call
- fish shell: `source venv/bin/activate.fish`, not `activate`
- Python 3.14 on Arch: work inside the venv or hit `externally-managed-environment`
- GitHub over SSH (`arch-key`): `eval (ssh-agent -c)` then `ssh-add`
