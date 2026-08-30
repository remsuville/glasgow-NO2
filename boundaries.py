"""The NO2 grid from openEO is EPSG:4326 (lat/lon degrees). Scottish vector data
is taken as EPSG:27700 (British National Grid, metres).

Vectors are reprojected to match the raster, not the other way round:
transforming a few thousand polygons is far cheaper than resampling a grid.
"""

import glob
import logging
import os

import geopandas as gpd
from shapely.geometry import box

from config import BBOX, BOUNDARY_DIR, CACHE_DIR, bbox_key

logger = logging.getLogger(__name__)

TARGET_CRS = "EPSG:4326"
SIMPLIFY_TOLERANCE = 0.001
SCOTLAND_BOUNDARY_CHECK = {"west": -9.0, "south": 54.5, "east": -0.5, "north": 61.0}

# Column names vary between publishers, so each zone set lists
# candidates and we resolve against whatever the downloaded file actually has
ZONE_SETS = {
    "councils": {
        "patterns": ["*ouncil*", "*pub_las*", "*_la_*", "*local_auth*", "*LAD*"],
        "id_candidates": ["code", "la_code", "LAD24CD", "LAD21CD", "CODE", "lad_code"],
        "name_candidates": ["name", "local_auth", "LAD24NM", "LAD21NM", "NAME", "la_name"],
    },
    "datazones": {
        "patterns": ["*ata*one*", "*DZ*", "*SG_DataZone*"],
        "id_candidates": ["dzcode", "DataZone", "datazone", "DZ_CODE", "code"],
        "name_candidates": ["dzname", "Name", "DZ_NAME", "name", "DataZone"],
    },

    # MHW is being used here to reduce the error due to zero-pop areas over water
    "intzones": {
        "patterns": ["*ntermediate*MHW", "*ntermediate*one*", "*IZ*"],
        "id_candidates": ["IZCode", "izcode", "IZ_CODE", "code"],
        "name_candidates": ["IZName", "izname", "IZ_NAME", "name"],
    },
}

VECTOR_EXTENSIONS = (".shp", ".gpkg", ".geojson", ".json", ".parquet")


def _find_source(kind):
    """Locate boundary file for `kind` under BOUNDARY_DIR."""
    spec = ZONE_SETS[kind]
    for pattern in spec["patterns"]:
        for ext in VECTOR_EXTENSIONS:
            hits = glob.glob(f"{BOUNDARY_DIR}/**/{pattern}{ext}", recursive=True)
            if hits:
                return sorted(hits)[0]

    available = glob.glob(f"{BOUNDARY_DIR}/**/*", recursive=True)
    raise FileNotFoundError(
        f"No '{kind}' boundary file found under {BOUNDARY_DIR}/. "
        f"Expected one of {spec['patterns']} with extension {VECTOR_EXTENSIONS}. "
        f"Present: {available or '(directory empty or missing)'}"
    )


def inspect_source(path):
    """Log everything we need to know about a boundary file first and
    Stands in for the QGIS pass: CRS, attribute columns, feature count,
    geometry types, validity and native bounds.
    """
    gdf = gpd.read_file(path)

    logger.info("--- inspecting %s ---", path)
    logger.info("features: %d", len(gdf))
    logger.info("declared CRS: %s", gdf.crs)
    if gdf.crs is not None:
        logger.info("  name: %s | axis units: %s", gdf.crs.name,
                    {ax.unit_name for ax in gdf.crs.axis_info})
    logger.info("columns: %s", dict(gdf.dtypes.astype(str)))
    logger.info("geometry types: %s", dict(gdf.geom_type.value_counts()))
    logger.info("native bounds: %s", [round(v, 3) for v in gdf.total_bounds])

    invalid = int((~gdf.geometry.is_valid).sum())
    empty = int(gdf.geometry.is_empty.sum())
    missing = int(gdf.geometry.isna().sum())
    logger.info("invalid: %d | empty: %d | missing: %d", invalid, empty, missing)

    return gdf


def _pick_column(gdf, candidates, role, kind):
    """Resolve an attribute column case-insensitively against candidates."""
    lookup = {c.lower(): c for c in gdf.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            resolved = lookup[candidate.lower()]
            logger.info("%s: using '%s' as %s", kind, resolved, role)
            return resolved
    raise KeyError(
        f"No {role} column for '{kind}'. Tried {candidates}; "
        f"file has {list(gdf.columns)}. Add the real name to ZONE_SETS."
    )


def _repair_geometry(gdf):
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        logger.warning("repairing %d invalid geometries with make_valid()",
                       int(invalid.sum()))
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].make_valid()
        still_bad = int((~gdf.geometry.is_valid).sum())
        if still_bad:
            raise ValueError(f"{still_bad} geometries still invalid after make_valid()")

    dropped = gdf.geometry.isna() | gdf.geometry.is_empty
    if dropped.any():
        logger.warning("dropping %d empty/missing geometries", int(dropped.sum()))
        gdf = gdf[~dropped]
    return gdf


def _reproject(gdf, kind):
    """Reproject to TARGET_CRS, ensuring the transform actually happened."""
    if gdf.crs is None:
        # set_crs would only *label* the data; it does not transform anything.
        # Guessing here is how metres get stamped as degrees, so refuse.
        raise ValueError(
            f"'{kind}' has no CRS (missing or malformed .prj). Refusing to guess — "
            "identify the true CRS and apply set_crs() explicitly at the call site."
        )

    logger.info("%s: reprojecting %s -> %s", kind, gdf.crs.to_string(), TARGET_CRS)
    if gdf.crs.to_string() == TARGET_CRS:
        logger.info("%s: already in target CRS, no transform needed", kind)
    else:
        gdf = gdf.to_crs(TARGET_CRS)

    west, south, east, north = gdf.total_bounds
    logger.info("%s: reprojected bounds W%.4f S%.4f E%.4f N%.4f",
                kind, west, south, east, north)

    env = SCOTLAND_BOUNDARY_CHECK
    if not (env["west"] <= west and east <= env["east"]
            and env["south"] <= south and north <= env["north"]):
        raise ValueError(
            f"'{kind}' bounds {[round(v, 3) for v in gdf.total_bounds]} fall outside "
            f"Scotland's lat/lon envelope {env}. Coordinates are probably still in "
            "the source projection — check the CRS the file declares."
        )
    return gdf


def load_zones(kind, bbox=None, clip=False, use_cache=True):
    """Load admin boundaries as a GeoDataFrame in EPSG:4326.

    Returns columns `zone_id`, `zone_name`, `geometry`. Zones are selected by
    *intersection* with `bbox`, keeping whole geometries by default — clipping
    would silently redefine what a zone mean covers. Pass clip=True to cut
    geometries at the bbox edge instead.

    `kind` is a key of ZONE_SETS. Keeping it a parameter is what makes swapping
    one boundary set for another a re-call rather than a rewrite.
    """
    if kind not in ZONE_SETS:
        raise KeyError(f"Unknown zone set '{kind}'. Known: {list(ZONE_SETS)}")

    bbox = BBOX if bbox is None else bbox
    extent = "clip" if clip else "whole"
    cache_file = f"{CACHE_DIR}/zones_{kind}_{extent}_{bbox_key(bbox)}.parquet"
    if use_cache and os.path.exists(cache_file):
        logger.info("zones cache: %s", cache_file)
        return gpd.read_parquet(cache_file)

    path = _find_source(kind)
    gdf = inspect_source(path)

    spec = ZONE_SETS[kind]
    id_col = _pick_column(gdf, spec["id_candidates"], "zone_id", kind)
    name_col = _pick_column(gdf, spec["name_candidates"], "zone_name", kind)

    gdf = _repair_geometry(gdf)
    gdf = _reproject(gdf, kind)

    before_pts = int(gdf.geometry.count_coordinates().sum())
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE)
    after_pts = int(gdf.geometry.count_coordinates().sum())
    logger.info("%s: simplified %d -> %d vertices (%.0f%% removed)",
                kind, before_pts, after_pts,
                100 * (1 - after_pts / before_pts))
        
    # Selection happens only after reprojection — bbox is in degrees.
    window = box(bbox["west"], bbox["south"], bbox["east"], bbox["north"])

    before = len(gdf)
    gdf = gdf[gdf.geometry.intersects(window)].copy()
    logger.info("%s: %d of %d zones intersect the study bbox", kind, len(gdf), before)
    if gdf.empty:
        raise ValueError(
            f"No '{kind}' zones intersect {bbox}. An empty intersection after a "
            "successful reprojection usually means the bbox and the boundaries "
            "still disagree — verify both extents before continuing."
        )

    partial = int((~gdf.geometry.within(window)).sum())
    if partial:
        logger.info("%s: %d zones extend beyond the bbox — their means will cover "
                    "only the portion with NO2 coverage", kind, partial)

    if clip:
        gdf = gdf.clip(window)
        logger.info("%s: geometries clipped to bbox", kind)

    zones = gdf[[id_col, name_col, "geometry"]].rename(
        columns={id_col: "zone_id", name_col: "zone_name"}
    ).reset_index(drop=True)

    duplicates = int(zones["zone_id"].duplicated().sum())
    if duplicates:
        logger.warning("%s: %d duplicate zone_id values (multipart features?)",
                       kind, duplicates)

    os.makedirs(CACHE_DIR, exist_ok=True)
    zones.to_parquet(cache_file)
    logger.info("%s: cached %d zones to %s", kind, len(zones), cache_file)
    return zones


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    kind = sys.argv[1] if len(sys.argv) > 1 else "councils"
    zones = load_zones(kind, use_cache=False)
    print(zones.head(12).to_string())
    print(f"\n{len(zones)} zones | CRS {zones.crs}")
