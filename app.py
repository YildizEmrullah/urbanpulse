"""HuggingFace Spaces / Streamlit Cloud entry point.

Seeds demo data on first run, then delegates to the main dashboard.
"""
import sqlite3
import subprocess
import sys
from pathlib import Path


def _seed_if_empty() -> None:
    db = Path("urbanpulse.db")
    try:
        if db.exists():
            conn = sqlite3.connect(str(db))
            count = conn.execute("SELECT COUNT(*) FROM fact_measurement").fetchone()[0]
            conn.close()
            if count > 0:
                return
    except Exception:
        pass
    subprocess.run([sys.executable, "scripts/seed_demo_data.py"], check=False)


_seed_if_empty()

# Delegate to the real dashboard (st.set_page_config must be first Streamlit call)
exec(open(Path(__file__).parent / "src/urbanpulse/dashboard/app.py").read())  # noqa: S102
