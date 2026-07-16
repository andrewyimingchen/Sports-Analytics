# Deployment

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

## Docker

A `Dockerfile` is provided (not yet CI-built — verify the first build
locally). `/app/data` is a volume: mount your warmed cache into it.

```bash
docker build -t nba-insights .
docker run -p 8501:8501 -v "$PWD/data:/app/data" nba-insights
```

Model artifacts are gitignored; train them before building or mount them
with the cache volume. Without them the Predictions page shows a
"models not trained" notice and everything else works.
