"""HuggingFace Spaces entry point — adds src to path, seeds data, runs dashboard."""
import os
import sys
from pathlib import Path

# Add src/ to Python path so urbanpulse package is importable
# (needed when pip install -e . was not run by the host Dockerfile)
src_path = str(Path(__file__).parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Now run the dashboard directly (it handles its own seeding)
import streamlit.web.cli as stcli

if __name__ == "__main__":
    dashboard_path = str(Path(__file__).parent / "src/urbanpulse/dashboard/app.py")
    sys.argv = ["streamlit", "run", dashboard_path,
                "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
    sys.exit(stcli.main())
else:
    # When Streamlit runs app.py as a script (not __main__), just exec the dashboard
    _dashboard = Path(__file__).parent / "src/urbanpulse/dashboard/app.py"
    exec(open(_dashboard).read())  # noqa: S102
