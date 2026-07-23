# Deployment

The FastAPI-served PWA is the official POSSESSION LAB product. Streamlit is an
internal analytics console and is not part of the production image.

The app is designed local-first, and one upstream fact dominates every
deployment decision: **stats.nba.com blocks most datacenter IPs.** A fresh
container on a typical cloud host cannot fetch data at all. The cache-first
architecture is the mitigation — everything the app shows comes from
`data/cache.sqlite3`, and finished-season entries never expire — so the
deployment problem reduces to *shipping a warmed cache*.

## The warmed-cache workflow

On a machine that can reach stats.nba.com (a residential connection works):

```bash
uv sync
uv run python -m nba_insights.ml.train   # fetches + caches 4 seasons, trains models
uv run streamlit run app/streamlit_app.py  # click through pages you care about
```

Then copy `data/` (cache + `models/*.joblib`) to the deployment target. The
app serves everything from cache and degrades gracefully when refresh
fetches fail: current-season entries are served stale rather than erroring.

During the season, re-warm on a schedule from the same machine (a nightly
cron running a small script that touches `team_games()`, `player_games()`,
`league_player_stats()`, `schedule()`) and sync `data/cache.sqlite3` up.

## Options

| Option | Verdict |
|---|---|
| **Self-host on a residential IP** (home server, Tailscale/Cloudflare Tunnel for access) | Best fit: the app can fetch for itself; zero cache choreography |
| **VPS / container platform + warmed cache volume** | Works; data is as fresh as your last cache sync (offseason: perfectly fine) |
| **Streamlit Community Cloud** | Expect first-fetch failures (blocked IPs) and an ephemeral filesystem — the cache resets on every reboot. Not recommended without the warmed-cache sync |

Run the official product directly with:

```bash
uv run uvicorn nba_insights.api:app --host 0.0.0.0 --port 8000
```

## Docker

A CI-built `Dockerfile` serves FastAPI and the installable PWA as a non-root
user. `/app/data` is a volume: mount your warmed cache and model artifacts into
it. The build context excludes local data, credentials, caches, internal
Streamlit code, and development tooling.

```bash
docker build -t possession-lab .
docker run --name possession-lab -p 8000:8000 \
  -v "$PWD/data:/app/data" possession-lab
```

Open `http://127.0.0.1:8000/app/`. Liveness and readiness probes are available
at `/healthz` and `/readyz`; readiness reports optional model availability but
does not fail when artifacts are absent because the product provides explicit
degraded states. Model artifacts are gitignored, so train them before mounting
the data volume. Without them prediction cards show a "models not trained"
notice and the rest of the product remains available.

## Remote API safeguards

Localhost callers can use all locally configured features without a POSSESSION
LAB API key. Remote AI and salary/contract access is denied unless
`POSSESSION_LAB_API_KEY` is configured and supplied through `X-API-Key` or an
`Authorization: Bearer` header. Remote simulations are weighted against a
per-client compute budget and can optionally require the same key.

| Variable | Default | Purpose |
|---|---:|---|
| `POSSESSION_LAB_API_KEY` | unset | Secret for remote AI/private-data access |
| `POSSESSION_LAB_REQUIRE_API_KEY` | `false` | Require the key for simulations |
| `POSSESSION_LAB_SIMULATION_BUDGET` | `100000` | Simulated games allowed per client/window |
| `POSSESSION_LAB_AI_REQUEST_BUDGET` | `5` | AI calls allowed per client/window |
| `POSSESSION_LAB_RATE_WINDOW_SECONDS` | `60` | Sliding budget window |
| `POSSESSION_LAB_TRUSTED_PROXY_IPS` | unset | Comma-separated immediate proxies whose forwarded client IP is trusted |

An untrusted forwarding header removes local-only privilege rather than
granting it. Configure trusted proxy IPs explicitly and separately restrict
which proxies Uvicorn accepts forwarding headers from. Do not put the API key
in PWA source code: a browser-facing reverse proxy or authenticated gateway
should add it after authorizing the user. The application limiter is
per-process; enforce a shared rate limit at that gateway when running multiple
workers.
