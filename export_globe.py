"""Export static assets for the Cesium globe."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from skyfield.api import load

OUT_DIR = Path(__file__).parent / "globe" / "data"
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={}&FORMAT=tle"
SAMPLE_SECONDS = 120

# name, NORAD catalog number, rgba, one-line note shown on hover
SATELLITES = [
    ("Sentinel-5P", 42969, [255, 200, 0, 200], "TROPOMI — NO2, 5 km, daily global"),
    ("Sentinel-2C", 60989, [90, 220, 130, 200], "MSI — optical, 10 m, 5-day revisit"),
    ("ISS", 25544, [200, 210, 255, 200], "Good 'ole classic, 51.6 deg inclination"),
    ("Meteosat-12", 54743, [255, 120, 120, 200], "Geostationary imager over Europe"),
]


def _span(start, end):
    """CZML epoch and availability interval for a date range"""
    return f"{start.isoformat()}Z", f"{start.isoformat()}Z/{end.isoformat()}Z"


def _load_sat(catnr):
    """Fetch a satellite's TLE cached by skyfield"""
    path = OUT_DIR / f"{catnr}.tle"
    return load.tle_file(TLE_URL.format(catnr), filename=str(path), reload=False)[0]


def _packet(entry, start, end, ts):
    """Build a CZML entity tracing a satellite between two dates."""
    name, catnr, colour, note = entry
    epoch, interval = _span(start, end)
    sat = _load_sat(catnr)
    marker = colour[:3] + [255]

    positions = []
    t = start
    while t <= end:
        p = sat.at(ts.utc(t.year, t.month, t.day, t.hour, t.minute, t.second))
        x, y, z = p.position.m
        positions += [(t - start).total_seconds(), round(x, 1), round(y, 1), round(z, 1)]
        t += timedelta(seconds=SAMPLE_SECONDS)

    return {
        "id": str(catnr),
        "name": name,
        "availability": interval,
        "properties": {"note": note},
        "position": {
            "epoch": epoch,
            "referenceFrame": "INERTIAL",
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 5,
            "cartesian": positions,
        },
        "path": {
            "material": {"solidColor": {"color": {"rgba": colour}}},
            "width": 2,
            "leadTime": 2700,
            "trailTime": 2700,
            "resolution": 60,
        },
        "point": {"pixelSize": 8, "color": {"rgba": marker}},
        "label": {
            "text": name,
            "font": "12px sans-serif",
            "pixelOffset": {"cartesian2": [0, -16]},
            "fillColor": {"rgba": marker},
        },
    }


def write_satellites_czml(start, end):
    """Write a CZML document tracing every satellite in SATELLITES"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = load.timescale()
    epoch, interval = _span(start, end)

    czml = [
        {
            "id": "document",
            "name": "satellites",
            "version": "1.0",
            "clock": {"interval": interval, "currentTime": epoch, "multiplier": 60},
        }
    ] + [_packet(entry, start, end, ts) for entry in SATELLITES]

    path = OUT_DIR / "satellites.czml"
    path.write_text(json.dumps(czml))
    return path
    
def ensure_czml(start, end):
    """Write the CZML if it isn't already on disk. Returns the path."""
    path = OUT_DIR / "satellites.czml"
    if path.exists():
        return path
    return write_satellites_czml(start, end)


if __name__ == "__main__":
    start = datetime(2026, 8, 20, 0, 0, 0)
    end = start + timedelta(days=1)
    path = write_satellites_czml(start, end)
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")
