import dash
import logging

from layout import layout
from callbacks import register_callbacks
from flask import Flask, Response, abort, send_from_directory
from config import CESIUM_ION_TOKEN, GLOBE_DIR
from export_globe import ensure_czml

# Logger for issues
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# App and Server
server = Flask(__name__)
app = dash.Dash(__name__, server=server, url_base_pathname="/report/")
app.layout = layout
register_callbacks(app)

@server.route("/")
def globe():
    return send_from_directory(GLOBE_DIR, "index.html")

@server.route("/style.css")
def globe_style():
    return send_from_directory(GLOBE_DIR, "style.css")

@server.route("/config.js")
def globe_config():
    return Response(
        f'window.GLOBE_CONFIG = {{ cesiumToken: "{CESIUM_ION_TOKEN}"}};',
        mimetype="application/javascript"
    )

@server.route("/globe/data/<path:filename>")
def globe_data(filename):
    data_dir = GLOBE_DIR / "data"
    if filename == "satellites.czml":
        try:
            ensure_czml()   # Calls with no args - date range is baked elsewhere! FIX FIX FIX
        except (OSError, ValueError, IndexError, KeyError):
            logger.exception("could not regenerate %s", filename)
            if not (data_dir / filename).exists():
                abort(503)
    return send_from_directory(data_dir, filename)


if __name__ == "__main__":
    app.run(debug=True) # Keep true to see changes live rather than restarting server
