import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent

# Globe token
CESIUM_ION_TOKEN = os.environ.get("CESIUM_ION_TOKEN", "")

# Study area
REGION_NAME = "Scotland"
BBOX = {
    "west": -7.70,
    "south": 54.6,
    "east": -1.70,
    "north": 58.70,
}


def bbox_key(bbox=None, digits=6):
    """Short stable digest of a bbox, for keying cache filenames."""
    bbox = BBOX if bbox is None else bbox
    canonical = ",".join(
        f"{float(bbox[edge]):.{digits}f}"
        for edge in ("west", "south", "east", "north")
    )
    return hashlib.sha1(canonical.encode()).hexdigest()[:8]


# Location Cache
CACHE_DIR = str(PROJECT_DIR / "cache")
BOUNDARY_DIR = str(PROJECT_DIR / "boundaries")
GLOBE_DIR = PROJECT_DIR / "globe"
DATE_RANGE = ("2024-06-01", "2024-06-28")
