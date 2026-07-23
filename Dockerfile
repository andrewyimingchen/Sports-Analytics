# POSSESSION LAB — production FastAPI/PWA image.
#
# Mount a warmed cache and model artifacts at /app/data. The image never copies
# local data into its build context; see .dockerignore and docs/DEPLOYMENT.md.

FROM ghcr.io/astral-sh/uv:0.9.5 AS uv
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NBA_INSIGHTS_DATA_DIR=/app/data

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Resolve the locked runtime first so source edits preserve the dependency layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN addgroup --system possession-lab \
    && adduser --system --ingroup possession-lab --home /app possession-lab \
    && mkdir -p /app/data \
    && chown -R possession-lab:possession-lab /app

USER possession-lab

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"]

CMD ["/app/.venv/bin/uvicorn", "nba_insights.api:app", \
     "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
