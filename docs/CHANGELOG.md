# Changelog

All notable changes to this project are documented here (As much as I remember to!).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

No git tags exist yet, so the versions below name states of `main` rather than
tagged releases. Tagging `v0.2.0` at this commit would make the links stable.

## [Unreleased]

Nothing yet.

## [0.2.0] - 2026-08-30

The globe, the Scotland-wide study area, and the corrections to how NO₂ values
are filtered and aggregated. Two changes break existing setups — see below.

### Added

- Interactive 3D Cesium globe as the landing page, with four satellites propagated from
  Celestrak TLEs via SGP4: Sentinel-5P, Sentinel-2C, the ISS, and Meteosat-12.
  with hover cards on the globe showing satellite name, altitude, orbital speed, and
  sub-satellite point, computed live against the viewer clock.
- `export_globe.py`, a standalone script producing `globe/data/satellites.czml`.
  TLEs are cached per satellite at `globe/data/{catnr}.tle`; SGP4 accuracy decays
  roughly 1 km/day from the element epoch, so a stale cache is quietly wrong.
- Flask now fronts Dash: the globe is served at `/`, the NO₂ dashboard at `/report/`,
  and `/config.js` hands the Cesium ion token to the browser. The token is
  client-visible by design — scope it in the ion dashboard before any public host.
- Geometry simplification of boundary data at `SIMPLIFY_TOLERANCE = 0.001`, applied
  after reprojection and therefore measured in degrees (~110 m at this latitude).
  Negligible for council areas, visible for Data Zones.
- Stylesheets extracted from inline markup: `globe/style.css` served by a `/style.css`
  route, `assets/report.css` picked up by Dash, and every inline `style={}` dict removed
  from `layout.py` in favour of `className` hooks.
- A digest of the study bbox (`config.bbox_key()`) in every cache filename, so changing
  the bbox invalidates the cache instead of silently reusing data from another area.
- `docs/methodology.md`: the estimator, grid geometry, the coverage threshold, and a
  script reproducing every figure in it.
- This changelog.

### Changed

- **Breaking.** The dashboard moved from `/` to `/report/`; `/` is now the globe.
  Existing bookmarks need updating.
- **Breaking.** Cache filenames now carry a bbox digest, so parquet files written by
  earlier versions are ignored rather than reused. Delete `cache/` or refetch.
- Widened the study area from the Central Belt to a Scotland-wide bbox.
- Split the map and timeline callbacks so that changing the map view no longer rebuilds
  the timeline.
- `ensure_czml()` regenerates from a signature of its own inputs rather than from mere
  file existence, so a stale CZML cannot survive an edit to `SATELLITES` or the window.
- Rewrote `README.md` around the two surfaces (globe and dashboard) and moved it to the
  repository root.

### Fixed

- Removed the `NO2 > 0` filter. Negative retrievals are genuine clean-air observations,
  not fill values, and discarding them inflated the regional mean.
- Dropped NaN pixels before the spatial overlay in zonal statistics. They previously
  contributed to the area weight sum without contributing a value, biasing zone means
  downward and overstating coverage.

### Removed

- `docs/summary.md`, `docs/plan.md`, `docs/zonal_explained.md` and `docs/final_plans.md`,
  superseded by `README.md` and `docs/methodology.md`. `summary.md` had also drifted into
  contradicting them on the sign of the `NO2 > 0` change.

### Known issues

- `app.run(debug=True)` still ships in `app.py`.
- No `qa_value` filtering. ESA recommends `qa_value > 0.75` for NO₂; whether the openEO
  `SENTINEL_5P_L2` collection applies any upstream cannot be told from the cached parquet.
- No tests around the weighting maths.

## [0.1.0] - 2026-08-17

The zonal statistics pipeline, as pushed to `origin/main` at `1b8b6de`.

### Added

- Zonal statistics: area-weighted mean NO₂ per administrative zone, with per-zone
  coverage and contributing cell counts.
- Choropleth views over Scottish Council Areas, Intermediate Zones 2022, and Data
  Zones 2022, selectable at runtime.
- Boundary loader with explicit, logged EPSG:27700 → EPSG:4326 reprojection and an
  envelope assertion that the reprojected bounds land inside Scotland.
- Parquet caching of fetched Sentinel-5P measurements, later extended to derived zone
  geometry.
- Modular split of the original single script into `config.py`, `data.py`, `figures.py`,
  `layout.py`, `callbacks.py` and `app.py`.
- User-selected date range behind a Submit button, so changing dates cannot trip CDSE
  rate limits mid-edit.
- Daily mean NO₂ timeline.

### Changed

- Replaced the Plotly `density_map` with discrete grid cells carrying their true lat/lon
  extents, so rendered cells match the resampled S5P footprint rather than approximating
  it with a heatmap.
- Narrowed the study area to a single `bbox` region (Central Belt), removing city
  selection.

[Unreleased]: https://github.com/remsuville/glasgow-NO2/commits/main
[0.2.0]: https://github.com/remsuville/glasgow-NO2/compare/1b8b6de...main
[0.1.0]: https://github.com/remsuville/glasgow-NO2/commits/1b8b6de
