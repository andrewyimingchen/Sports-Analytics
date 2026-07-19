# NBA Insights 🏀

A Streamlit app in seven pages:

- **League pulse** — the landing page: per-game and net/clutch-rating leaders,
  Elo power rankings, best/worst net ratings, and the next slate with win
  probabilities; a season selector rewinds the leaders and team form to any
  season back to 1996-97 (Elo and the slate stay current — they're "now"
  widgets)
- **Player profile** — career trajectory, form trends, shot chart (raw or
  zone-efficiency-vs-league view, regular season or playoffs) with shot
  quality (xeFG%: selection vs making), team on/off splits, league
  percentile ranks incl. net rating, clutch rating, and DARKO DPM — with a
  season picker, so retired players rank against their own era (1996-97
  onward); the header carries draft pedigree and current salary
- **Compare players** — side-by-side stats, percentile bars, shot quality, and
  a downloadable share poster (the Predictions page has one per matchup too)
- **Teams** — record/ratings/Elo tiles, season margin trend, roster with
  ratings and salaries (plus committed payroll), per-player on/off impact,
  last ten games, and conference standings
- **Draft** — every draft class back to 1947 with combine measurements
  (wingspan, standing reach, athletic testing) from 2000 on; drafted players
  carry their pick pedigree on the profile header
- **Predictions** — game outcome probabilities, a 10,000-run Monte Carlo game
  simulator (margin/total distributions), player points projections with 80%
  intervals, and starting-five estimates
- **Season outlook** — a 5,000-run Monte Carlo of the coming season from
  offseason-regressed Elo: projected standings (win totals with 10–90%
  bands, playoff/top-6/#1-seed odds) and postseason odds (conference finals,
  Finals, championship)
- **Methodology** — how every model is built, judged, and what was rejected

Built on the official-ish [`nba_api`](https://github.com/swar/nba_api)
(stats.nba.com). Every response is cached locally in SQLite, so repeat views
never hit the network: finished seasons are cached forever, current-season data
refreshes daily.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```bash
uv sync
uv run python -m nba_insights.warm --top 20   # optional but recommended: prefetch
uv run streamlit run app/streamlit_app.py
```

Then open http://localhost:8501, search a player, and explore. The warm
step prefetches the league dashboards and top players so the first page
load is instant; skip it and the first views fetch live instead
(rate-limited, so the landing page can take a while on a cold cache).

## Architecture

```
src/nba_insights/
├── ingest/      # NBAClient: rate-limited, retrying nba_api wrapper
├── store/       # SQLite DataFrame cache with per-endpoint TTLs
├── analysis/    # pure pandas: trends, percentiles, comparisons, ratings, zones
├── ml/          # features, Elo, outcome/points/lineup models, game simulator
├── pbp/         # play-by-play corpus: backfill, garbage time, stint lineups
└── api/         # FastAPI JSON endpoints + PWA
app/             # Streamlit UI (seven pages; ui.py holds the CSS motion layer)
tests/           # unit + AppTest smoke tests — no network required
```

The layers are strictly separated: **ingest** is the only code that touches the
network, **store** decides freshness (and serves stale data if stats.nba.com is
unreachable, so the app degrades gracefully offline), and **analysis** is pure
functions over DataFrames — fully testable without a connection.

### Known upstream quirks handled

- stats.nba.com intermittently serves empty (G-League-tagged) career responses
  for some player IDs; the client falls back to `PlayerProfileV2`.
- Empty API responses are cached for only an hour, so a transient glitch can't
  get pinned for a whole TTL, while a legitimately empty response (a player
  with no playoff games) doesn't refetch on every view.
- A finished season's entry is only treated as immutable if it was fetched
  after the season actually ended; a mid-season snapshot refetches once the
  season rolls over.

## Predictions (ML)

Three models power the app's Predictions page. Train them once (fetches three
past seasons through the cache, ~a minute cold):

```bash
uv run python -m nba_insights.ml.train
```

| Model | Approach | Holdout result (2025-26) |
|---|---|---|
| Game outcome | Logistic regression on prior-seeded season-to-date form differentials (win%, net rating, four factors, pace, ORtg/DRtg), rest/back-to-backs, expected minutes out (derived absences), carried-over Elo + home court | 70.2% accuracy, log loss 0.589 over the **full season** incl. opening weeks (55% baseline: always pick home) |
| Player points | Two-stage: minutes model (rotation trend, rest, roster availability) × per-minute rate model (EWMA form, opponent context, teammate absences); ships an empirical 80% interval from training residual quantiles, binned by projection level | MAE 4.58 (4.72 baseline: 10-game average); the 80% interval covered 80.4% of holdout games |
| Starting five | Observed lineup net rating blended with a per-36 plus-minus proxy through a fitted win curve; the observed side prefers our stint table (exact rotation intervals, garbage time stripped, estimated possessions) over the season-aggregate dashboard | blend; pure proxy when the five never played together |
| Game simulator | Monte Carlo over pace and ratings (10,000 sims: shared possessions, per-100 scoring vs opponent defense, home court, minutes out, overtime); parameters fitted on the training seasons | log loss 0.601 / 68.6% — the logistic model keeps the headline number; the simulator supplies margin/total distributions |

Evaluation is a temporal holdout: trained on 2022-25, scored on the current
season, with hyperparameters tuned on a dev season (the most recent training
season) so the holdout is only touched once. Retraining writes the holdout
numbers to `data/models/metrics.json`, which is what the app's captions
quote — the table above is the record from the last full evaluation.
Retrain whenever you want fresher form; artifacts live in `data/models/`
(never committed).

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
| `/posters/compare?names=A&names=B` | 1:1 share poster of a comparison (`&format=png` for an image) |
| `/posters/game?home=LAL&away=BOS` | 16:9 share poster of a game prediction (`&format=png`) |
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

Historical seasons load live the first time someone selects them; to
pre-seed the era features instead (finished seasons cache forever, so this
is a one-time cost per season):

```bash
uv run python -m nba_insights.warm --seasons 1996-97 1997-98 2015-16
```

The stint-level lineup table (used by the Predictions page's starting-five
tab) is built offline from play-by-play and rotation data:

```bash
uv run python -m nba_insights.pbp.backfill --seasons 2025-26  # fetch corpus
uv run python -m nba_insights.pbp.lineups --season 2025-26    # aggregate
```

The build is cache-only and instant, but it refuses to store a table
below 90% game coverage (a partial corpus would understate every
lineup's minutes; `--min-coverage` overrides). All the patience lives in
the backfill: stats.nba.com tar-pits the rotation endpoint (~20 seconds
per response, and empty responses when hit faster — hence the gentle
`--delay 3` default), so **backfilling a historical season is an
overnight run**. It's fully resumable — cached games are skipped, so
interrupted runs just continue where they stopped. During the season the
nightly increment is a handful of games (~5 minutes), which is the
intended steady state. Quirks handled: a few games per season have no
rotation rows at all (skipped), and a whole season can lag upstream (as
of July 2026, 2025-26 returns nothing — a failure-rate breaker gives up
cleanly and the app falls back to the season-aggregate lineup dashboard
until the data appears).

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

Game and player statistics come from `nba_api` against stats.nba.com.
Salary/contract context is scraped at minimal volume from public reference
pages (a single summary page, cached long-term) for **personal, educational
use only** — those sites' terms of service discourage scraping, a tension
the project owner has knowingly accepted for local use. Scraped data is
never served through the public API/PWA and must not be redistributed or
used commercially. For a commercial deployment, license the data instead
(BALLDONTLIE's GOAT tier carries contracts, injuries, and odds;
SportsDataIO and Sportradar are the heavier options).

One external dataset is displayed with attribution: **DARKO** daily
plus-minus projections (DPM) by Kostya Medvedovsky and Andrew Patton, from
[darko.app](https://darko.app) — a free public site with data export and no
formal license published. The numbers are shown as-is for personal and
educational use and are never used as model features; remove
`NBAClient.darko_dpm` (one cache key) if the creators ever object, or
license the data before any commercial use.

Data is the property of NBA Media Ventures, LLC. This tool is for personal and
educational use.
