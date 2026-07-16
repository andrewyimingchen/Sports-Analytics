# NBA Insights 🏀

A Streamlit app in six pages:

- **League pulse** — the landing page: per-game and net/clutch-rating leaders,
  Elo power rankings, best/worst net ratings, and the next slate with win
  probabilities
- **Player profile** — career trajectory, form trends, shot chart (raw or
  zone-efficiency-vs-league view, regular season or playoffs), league
  percentile ranks incl. net and clutch rating
- **Compare players** — side-by-side stats and percentile bars
- **Teams** — record/ratings/Elo tiles, season margin trend, roster with
  ratings, last ten games, and conference standings
- **Predictions** — game outcome probabilities, a 10,000-run Monte Carlo game
  simulator (margin/total distributions), player points projections with 80%
  intervals, and starting-five estimates
- **Methodology** — how every model is built, judged, and what was rejected

Built on the official-ish [`nba_api`](https://github.com/swar/nba_api)
(stats.nba.com). Every response is cached locally in SQLite, so repeat views
never hit the network: finished seasons are cached forever, current-season data
refreshes daily.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```bash
uv sync
uv run streamlit run app/streamlit_app.py
```

Then open http://localhost:8501, search a player, and explore.

## Architecture

```
src/nba_insights/
├── ingest/      # NBAClient: rate-limited, retrying nba_api wrapper
├── store/       # SQLite DataFrame cache with per-endpoint TTLs
├── analysis/    # pure pandas: trends, percentiles, comparisons, ratings, zones
├── ml/          # features, Elo, outcome/points/lineup models, game simulator
├── pbp/         # play-by-play corpus utilities
└── api/         # FastAPI JSON endpoints + PWA
app/             # Streamlit UI (six pages; ui.py holds the CSS motion layer)
tests/           # unit + AppTest smoke tests — no network required
```

The layers are strictly separated: **ingest** is the only code that touches the
network, **store** decides freshness (and serves stale data if stats.nba.com is
unreachable, so the app degrades gracefully offline), and **analysis** is pure
functions over DataFrames — fully testable without a connection.

### Known upstream quirks handled

- stats.nba.com intermittently serves empty (G-League-tagged) career responses
  for some player IDs; the client falls back to `PlayerProfileV2`.
- Empty API responses are never cached, so a transient glitch can't get pinned
  for a whole TTL.

## Predictions (ML)

Three models power the app's Predictions page. Train them once (fetches three
past seasons through the cache, ~a minute cold):

```bash
uv run python -m nba_insights.ml.train
```

| Model | Approach | Holdout result (2025-26) |
|---|---|---|
| Game outcome | Logistic regression on prior-seeded season-to-date form differentials (win%, net rating, four factors, pace, ORtg/DRtg), rest/back-to-backs, expected minutes out (derived absences), carried-over Elo + home court | 70.2% accuracy, log loss 0.589 over the **full season** incl. opening weeks (55% baseline: always pick home) |
| Player points | Two-stage: minutes model (rotation trend, rest, roster availability) × per-minute rate model (EWMA form, opponent context, teammate absences); ships an empirical 80% interval from training residual quantiles | MAE 4.58 (4.72 baseline: 10-game average) |
| Starting five | Observed lineup net rating (weighted by minutes together) blended with a per-36 plus-minus proxy, through a fitted win curve | blend; pure proxy when the five never played together |
| Game simulator | Monte Carlo over pace and ratings (10,000 sims: shared possessions, per-100 scoring vs opponent defense, home court, minutes out, overtime); parameters fitted on the training seasons | log loss 0.601 / 68.6% — the logistic model keeps the headline number; the simulator supplies margin/total distributions |

Evaluation is a true temporal holdout: trained on 2022-25, scored on the
current season. Retrain whenever you want fresher form; artifacts live in
`data/models/` (never committed).

## Phone app (PWA)

A minimal installable mobile app ships with the API — no app store, no
native toolchain:

```bash
uv run uvicorn nba_insights.api:app --port 8000
```

Open `http://<your-host>:8000/app/` on a phone (or desktop) and "Add to
Home Screen". Two tabs: player search → profile (headshot, stat tiles,
league percentiles) and game prediction (team pickers → win probability
from the 70%-accuracy model). Vanilla HTML/JS, ~300 lines, served from
`src/nba_insights/api/static/`.

## JSON API & share cards

The same FastAPI service exposes the data as JSON:

| Endpoint | Returns |
|---|---|
| `/players/search?q=jokic` | matching players with IDs |
| `/players/{id}/career` | per-game averages by season |
| `/players/{id}/percentiles` | current-season league percentile ranks |
| `/compare?names=A&names=B` | side-by-side per-game stats (2–4 players) |
| `/players/{id}/card` | self-contained HTML share card |
| `/teams` | tricodes of all teams this season |
| `/predict/game?home=LAL&away=BOS` | home-team win probability |
| `/players/{id}/headshot` | headshot proxy (CDN blocks hotlinking) |

Interactive docs at `/docs`. The API reads through the same cache as the app,
so each warms the other.

## Warming the cache

First views fetch live from stats.nba.com; to make them instant, prefetch the
league dashboard, standings, and the top players by minutes:

```bash
uv run python -m nba_insights.warm --top 20
```

Schedule it nightly with cron (run from the repo root so it fills the same
`data/` directory the app reads):

```cron
0 6 * * * cd /path/to/Sports-Analytics && uv run python -m nba_insights.warm --top 20
```

## Deployment

Local-first by design — stats.nba.com blocks most datacenter IPs, so remote
deployments ship a warmed cache. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
for the workflow, options, and the provided Dockerfile.

## Development

```bash
uv run pytest        # tests
uv run ruff check .  # lint
```

CI runs both on every push and pull request. Issue tracking uses
[beads](https://github.com/gastownhall/beads) (`bd ready` to see open work).

## Data source & legal

This project uses **only** `nba_api` against stats.nba.com. It deliberately
does **not** scrape Basketball-Reference.com — their terms of service prohibit
scraping and commercial reuse (the previous incarnation of this repo did; that
code has been removed). For a commercial deployment at scale, budget for a
licensed provider such as SportsDataIO or Sportradar.

Data is the property of NBA Media Ventures, LLC. This tool is for personal and
educational use.
