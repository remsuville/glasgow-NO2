import dash
import logging

from layout import layout
from callbacks import register_callbacks


# Logger for issues
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# App to display the dashboard
app = dash.Dash(__name__)
app.layout = layout
register_callbacks(app)


if __name__ == "__main__":
    app.run(debug=True)