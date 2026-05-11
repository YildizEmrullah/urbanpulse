# ── Stage 1: base ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for asyncpg + numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── Stage 2: source ───────────────────────────────────────────────────────────
FROM base AS source

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-deps -e .

# ── Stage 3: api ──────────────────────────────────────────────────────────────
FROM source AS api

EXPOSE 8000
CMD ["uvicorn", "urbanpulse.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 4: worker ───────────────────────────────────────────────────────────
FROM source AS worker

CMD ["python", "-m", "urbanpulse.worker.run"]

# ── Stage 5: dashboard ────────────────────────────────────────────────────────
FROM source AS dashboard

EXPOSE 8501
CMD ["streamlit", "run", "src/urbanpulse/dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
