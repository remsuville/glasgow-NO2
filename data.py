import pandas as pd
import os
import xarray as xr
import openeo

from config import CITIES, CACHE_DIR


# OpenEO Connection
def get_connection():
    connection = openeo.connect("openeo.dataspace.copernicus.eu")
    connection.authenticate_oidc()
    return connection


os.makedirs(CACHE_DIR, exist_ok=True)


# Data request
def get_no2(city, start_date, end_date):
    cache_file = f"{CACHE_DIR}/{city}_{start_date}_{end_date}.parquet"
    if os.path.exists(cache_file):
        return pd.read_parquet(cache_file)


    bbox = CITIES[city]
    datacube = get_connection().load_collection(
        "SENTINEL_5P_L2",
        spatial_extent=bbox,
        temporal_extent=[start_date, end_date],
        bands=["NO2"]
    )
    
    datacube.download(f"{CACHE_DIR}/{city}_temp.nc")
    
    ds = xr.open_dataset(f"{CACHE_DIR}/{city}_temp.nc")
    df = ds['NO2'].to_dataframe(name='NO2').reset_index().dropna()
    df = df[df['NO2'] > 0]
    
    df.to_parquet(cache_file)
    print(f"Cached to {cache_file}")
    return df