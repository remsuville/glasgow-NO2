import pandas as pd
import os
import xarray as xr
import openeo
import logging

from config import BBOX, CACHE_DIR, REGION_NAME


# Logger for issues
logger = logging.getLogger(__name__)

# OpenEO Connection
def get_connection():
    logger.info("Connecting to CDSE using openEO...")
    connection = openeo.connect("openeo.dataspace.copernicus.eu")
    connection.authenticate_oidc()
    logger.info("Connection and authentication successful.")
    return connection


os.makedirs(CACHE_DIR, exist_ok=True)


# Data request
def get_no2(start_date, end_date):
    cache_file = f"{CACHE_DIR}/{REGION_NAME}_{start_date}_{end_date}.parquet"
    if os.path.exists(cache_file):
        logger.info(f"Cache: {cache_file}")
        return pd.read_parquet(cache_file)

    datacube = get_connection().load_collection(
        "SENTINEL_5P_L2",
        spatial_extent=BBOX,
        temporal_extent=[start_date, end_date],
        bands=["NO2"]
    )

    # Unique per request — a shared temp name cross-contaminates concurrent pulls
    temp_file = f"{CACHE_DIR}/{REGION_NAME}_{start_date}_{end_date}_temp.nc"
    datacube.download(temp_file)

    try:
        # Context manager releases the file handle before we unlink it, and
        # to_dataframe() pulls everything into memory inside the block, so
        # nothing is left reading lazily from a deleted file.
        with xr.open_dataset(temp_file) as ds:
            df = ds['NO2'].to_dataframe(name='NO2').reset_index().dropna()
    finally:
        # finally, not a trailing call: a failed conversion should not leave
        # the NetCDF behind to accumulate one file per request.
        if os.path.exists(temp_file):
            os.remove(temp_file)
            logger.info(f"Removed temp file: {temp_file}")

    df = df[df['NO2'] > 0]

    df.to_parquet(cache_file)
    logger.info(f"Cached to {cache_file}")
    return df