# Boundary data

Drop downloaded Scottish administrative boundaries in here. The files themselves
are not committed — only this note.

Source: https://spatialdata.gov.scot (Spatial Hub Scotland), OGL licensed.
Attribution is required if any output is published.

| kind in `ZONE_SETS` | dataset | count |
|---|---|---|
| `councils` | Council areas | 32 nationally |
| `datazones` | Data Zones 2011 | ~6,976 nationally |

`boundaries.py` finds files by glob, so any of `.shp` (with its sidecars — the
`.prj` especially), `.gpkg`, `.geojson` or `.parquet` works. If the filename
doesn't match the patterns in `ZONE_SETS`, either rename it or add the pattern.

To inspect a newly downloaded file — CRS, attribute columns, geometry validity,
native bounds — without wiring anything up:

    source venv/bin/activate.fish
    python boundaries.py councils

If it reports the wrong column for `zone_id` / `zone_name`, add the real name to
the relevant `*_candidates` list in `ZONE_SETS`.
