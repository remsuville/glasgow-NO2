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

@server.route("/config.js")
def globe_config():
    return Response(
        f'window.GLOBE_CONFIG = {{ cesiumToken: "{CESIUM_ION_TOKEN}"}};',
        mimetype="application/javascript"
    )

@server.route("/globe/data/<path:filename>")
def globe_data(filename):
    data_dir = GLOBE_DIR / "data"
    if filename == "s5p.czml" and not (data_dir / filename).exists():
        try:
            ensure_czml()
        except Exception:
            logger.exception("could not generate %s", filename)
            abort(503)
    return send_from_directory(data_dir, filename)


if __name__ == "__main__":
    app.run(debug=True)
