# ── Stage 1: base ─────────────────────────────────────────────────────────────
# ── HuggingFace Spaces: runs API + dashboard together (port 7860) ─────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev supervisor && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY pyproject.toml .
COPY src/ src/
COPY scripts/ scripts/
COPY app.py .
COPY supervisord.conf /etc/supervisord.conf

RUN pip install --no-deps -e .

EXPOSE 7860

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
