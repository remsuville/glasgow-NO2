# Sentinel-5P NO₂ over Scotland

A Dash dashboard that pulls Sentinel-5P tropospheric NO₂ from the Copernicus
Data Space Ecosystem (CDSE) and aggregates it onto Scottish administrative
geographies using **area-weighted zonal statistics**

NEW! a Cesium globe showing satellite paths (more to come!)

![Zonal choropleth of mean NO₂ by Intermediate Zone](docs/screenshots/zonal-intzones.png)

---

## What it does

- **Fetches** NO₂ in mol/m² from CDSE openEO (`SENTINEL_5P_L2`) for a
  Scotland-wide bounding box (bbox), cached to parquet so repeated views never re-hit
  the API.
- **Renders the true pixel grid** — each observation is drawn as a rectangle
  covering its real ground footprint (~13 km²), not as a single point.
- **Aggregates onto administrative zones** — Council areas, Intermediate Zones
  2022, or Data Zones 2022 — by area-weighted overlap.
- **Reports its own uncertainty** — every zone carries a `coverage` fraction,
  and zones backed by too little of their area are drawn grey rather than
  confidently shaded. More reporting being developed.
- **Shows the satellites** — a Cesium globe propagating live TLEs for
  Sentinel-5P, Sentinel-2C, the ISS and Meteosat-12, with hover cards giving
  more information regarding the satellite.

## Methodology

**Area-weighted overlap using temporal average** A Sentinel-5P cell here
covers ~13 km²; the median Data Zone is 0.20 km², about 65x smaller. Most zones
contain no pixel centre at all, so a centre-in-polygon test would return nothing
for the majority of the map. Data is also averaged across a chosen time period.

**Areas measured in a projected CRS.** Intersection areas are computed in
EPSG:27700 (British National Grid, metres), never in degrees. A degree of
longitude shrinks ~10% between south and north edges of the study area, so
degree-area weighting would systematically over-weight the northern pixels.

**CRS is never implicit.** A CRS mismatch fails silently — no exception, just
every pixel assigned to the wrong zone -> `boundaries.py` refuses to guess a
missing CRS + logs every transform, and finally, asserts the reprojected bounds to land
inside Scotland, which turns that silent failure loud.

**Coverage travels with the mean.** A zone near the bbox edge can get confident bbox value
representing the tiniest coverage within the zone e.g. Orkney sits
0.055% inside the current box. Zones below a coverage threshold keep their
geometry but have their mean withheld, and withheld zones are *drawn in grey
rather than omitted*.

Worked examples and stuff for Nerds:
[`docs/methodology.md`](docs/methodology.md).

## Quickstart

Requires Python 3.12+ (developed on 3.14) and a free
[Copernicus Data Space](https://dataspace.copernicus.eu/) account.

```bash
python -m venv venv
source venv/bin/activate        # fish: source venv/bin/activate.fish
pip install -r requirements.txt
python app.py
```

Then:

| URL | what it is |
|---|---|
| <http://127.0.0.1:8050/> | Cesium globe with live satellite tracks |
| <http://127.0.0.1:8050/report/> | the NO₂ dashboard |

The first data request triggers OAuth prompt in default browser, but the
token is cached to disk afterwards.

Pick a date range, press **Submit**, then switch map views freely — the view
selector only ever reads already-fetched data, so it cannot trigger a new API
call.

### Configuration

`.env`, read by `config.py`:

```
CESIUM_ION_TOKEN=...     # optional; without it the globe falls back to
                         # offline imagery and no terrain
```

The ion token is **client-visible by design** — it is served to the browser by
the `/config.js` route. BE CAREFUL with this!

Study area and default dates live in `config.py`:

```python
BBOX = {"west": -7.70, "south": 54.6, "east": -1.70, "north": 58.70}
DATE_RANGE = ("2024-06-01", "2024-06-28")
```

The bbox is hashed into every cache filename, so changing it invalidates the
cache rather than silently reusing data from a different area.

### Boundary data

Download from [Spatial Hub Scotland](https://spatialdata.gov.scot) into
`boundaries/`:

| key in `ZONE_SETS` | dataset | national | in bbox | median area | median cells/zone |
|---|---|---|---|---|---|
| `councils` | Council areas | 32 | 31 | 903.77 km² | 80 |
| `intzones` | Intermediate Zones 2022 | 1,334 | 1,322 | 1.53 km² | 2 |
| `datazones` | Data Zones 2022 | 7,392 | 7,330 | 0.20 km² | 1 |

That last column is the one to read before choosing a set. 57% of Data Zones are
fed by a single pixel — the finer sets are a *presentation* choice, not extra
spatial detail :)

**Intermediate Zones ship in two coastal variants.** Use `_MHW` (cut at mean
high water), not `_EoR` (extent of realm, which runs out to sea and would
average NO₂ over open water). `ZONE_SETS["intzones"]` pins MHW so an
alphabetically-sorted glob cannot quietly hand back the wrong one.

All three sets are British National Grid (EPSG:27700) and are reprojected on
load. `boundaries.py` resolves files by glob, so `.shp` (with its sidecars —
the `.prj` especially), `.gpkg`, `.geojson` and `.parquet` all work. If a
filename doesn't match the patterns in `ZONE_SETS`, either rename it or add the
pattern.

To inspect a newly downloaded file — CRS, attribute columns, geometry validity,
native bounds — without wiring anything up:

```bash
python boundaries.py intzones
```

If that reports the wrong column for `zone_id` or `zone_name`, add the real name
to the relevant `*_candidates` list in `ZONE_SETS`.

### Satellite globe

`export_globe.py` fetches .TLE files from CelesTrak, propagates each satellite with
SGP4 through Skyfield, and writes one .CZML document sampled every 120s:

```bash
python export_globe.py        # writes globe/data/satellites.czml (120 KB/day)
```

`app.py` also calls `ensure_czml()` when the file is requested, regenerating it
only when the satellite list or window changes — the CZML carries a signature of
its own inputs, so a stale file cannot survive an edit to `SATELLITES`.

TLEs are cached per satellite at `globe/data/{catnr}.tle`. SGP4 accuracy
degrades roughly 1 km/day from the element epoch, so older cache will inherently show incorrect data.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    PRESENTATION   (browser)                    │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │
│  │ Cesium globe   │  │ Dash controls  │  │ Plotly figures   │  │
│  │ index.html     │  │ layout.py      │  │ figures.py       │  │
│  │ style.css      │  │ report.css     │  │ pixels · zones   │  │
│  │ hover cards    │  │ date · view    │  │ daily timeline   │  │
│  └────────────────┘  └────────────────┘  └──────────────────┘  │
├────────────────────────────────────────────────────────────────┤
│            HTTP LAYER   —   app.py  (Flask + Dash)             │
│                                                                │
│    /                  globe page  (globe/index.html)           │
│    /style.css         globe stylesheet                         │
│    /config.js         Cesium ion token → client                │
│    /globe/data/*      satellites.czml · *.tle                  │
│    /report/           Dash app  →  callbacks.py                │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│                 PROCESSING   &   PARQUET CACHE                 │
│                                                                │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │
│  │ data.py        │  │ boundaries.py  │  │ zonal.py         │  │
│  │ openEO fetch   │  │ find + repair  │  │ cell footprints  │  │
│  │ NetCDF → df    │  │ 27700 → 4326   │  │ overlay in 27700 │  │
│  └────────────────┘  └────────────────┘  └──────────────────┘  │
│                                                                │
│   config.py         BBOX · dates · ion token · bbox digest     │
│   export_globe.py   TLE → SGP4 (skyfield) → CZML               │
│   cache/*.parquet   NO2 grid · zone sets, keyed by bbox hash   │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│                     EXTERNAL DATA SOURCES                      │
│                                                                │
│   CDSE openEO     ·  device-flow OAuth    			         │
│   Spatial Hub Scotland shapefiles 					         │
│   CelesTrak TLEs  ·  Cesium ion terrain  ·  OSM basemap        │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

Data flows one way and each module has exactly one job. `figures.py` never
fetches and `data.py` never draws — all wiring lives in `callbacks.py`, which is
what makes the whole pipeline testable headlessly. `export_globe.py` shares only
`config.py` with the NO₂ side, so the globe and the dashboard can break
independently.

Everything crossing a layer boundary downwards is cached to parquet (or to CZML,
for orbits), keyed by a digest of the inputs it was built from — so changing the
bbox, the date range or the satellite list invalidates the file rather than
silently reusing it.

## Documentation

[`docs/methodology.md`](docs/methodology.md) — the maths in full: grid geometry,
the temporal collapse, the area-weighted estimator with a worked example, the
coverage threshold, and a script that reproduces every number in it.

## Limitations

How the numbers should and should not be read:

- **Tropospheric column IS NOT ground concentration.** Output is mol/m² through the
  atmospheric column, not the µg/m³ at 2 m used by air-quality regulation.
  Requires bunch of assumptions and comparisons that are in works.
- **Negative retrievals are retained** (7.5% of rows in the reference window,
  and a handful of zone means come out slightly negative). This is deliberate:
  over clean air the retrieval noise straddles zero, and filtering the negative
  tail would bias means upward, worst where concentrations are lowest.
- **Sub-pixel zones.** Council areas are the only set larger than the
  pixel grid. 56% of Intermediate Zones and 84% of Data Zones are fed by two
  pixels or fewer, so neighbouring zones return near-identical means. (Again, things
  are in works to reduce error here as well.)
- **Sparse coverage.** Sentinel-5P is a polar orbiter: limited overpass per day, and
  swath edges and cloud remove most cells, which is why time is removed from the equation.
- **Unweighted temporal mean.** A cell contributing 1 clear day counts the same
  as one contributing 18. `n_dates` is carried through so this is at least
  visible.
- **Boundary simplification** at `SIMPLIFY_TOLERANCE = 0.001°` (~110 m) to make calculations
  a tad faster: negligible for councils, visible for Data Zones.

## Data sources

- **NO₂** — Copernicus Sentinel-5P TROPOMI via the
  [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) openEO
  API. Contains modified Copernicus Sentinel data.
- **Boundaries** — [Spatial Hub Scotland](https://spatialdata.gov.scot), Open
  Government Licence v3.0. Attribution required for published output.
- **Orbits** — [CelesTrak](https://celestrak.org) .TLE files, propagated with
  [Skyfield](https://rhodesmill.org/skyfield/).

## Roadmap

- [ ] Retention curve — `1 − ECDF` of the qa column, so the cost of the
      threshold is visible alongside it
- [ ] Population-weighted exposure (the 2022 zone files already carry population
      columns)
- [ ] Multi-year timelapse (also day-night cycles for the globe)
- [ ] Tests around the weighting maths
- [ ] Plotly `template` in `figures.py` — figure internals are unreachable from
      .CSS
- [ ] Make globe more informative, as it servers much an aesthetic purpose-only
	  right now :)
- [ ] More data!! CO / HCHO / Aerosols
- [ ] Validate data, R² of S5P against Scottish Air Quality reports

