# NBA Insights — Streamlit app image.
#
# The cache and model artifacts live in /app/data: mount it as a volume and
# warm it before exposing the app (see docs/DEPLOYMENT.md — stats.nba.com
# blocks most datacenter IPs, so the container usually cannot fetch for
# itself).

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# dependency layer first so code edits don't bust it
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

VOLUME /app/data
EXPOSE 8501

CMD ["uv", "run", "streamlit", "run", "app/streamlit_app.py", \
     "--server.headless=true", "--server.address=0.0.0.0"]
