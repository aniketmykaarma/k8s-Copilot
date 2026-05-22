"""Entry point that invokes `streamlit run` on web_app.py.

Registered as `k8s-copilot-web` in pyproject.toml.
"""

import sys
from importlib import resources
from pathlib import Path


def launch() -> None:
    """Start Streamlit pointed at our web_app module."""
    try:
        from streamlit.web import cli as stcli
    except ImportError:
        print(
            "Streamlit not installed. Install the web extra:\n"
            "    pip install 'k8s-copilot[web]'"
        )
        sys.exit(1)

    # Locate the web_app.py file inside the installed package
    web_app_path = Path(__file__).parent / "web_app.py"

    sys.argv = ["streamlit", "run", str(web_app_path)]
    sys.exit(stcli.main())


if __name__ == "__main__":
    launch()
