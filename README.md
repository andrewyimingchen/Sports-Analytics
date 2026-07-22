# NBA Insights 🏀

A Streamlit app in nine pages:

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
- **Explore stats** — a sortable, filterable league-wide player table with
  per-game/per-36 views and CSV export
- **Teams** — record/ratings/Elo tiles, season margin trend, roster with
  ratings and salaries (plus committed payroll), per-player on/off impact,
  last ten games, and conference standings
- **Games** — season scores and schedule with team filtering; finals open a
  cached game story with win-probability flow, turning points, shots, lineups,
  clutch context, advanced team stats, play-by-play, and the full player box
- **Ask (AI)** — optional natural-language questions over the cached league
  table, enabled with the `anthropic` extra and an API credential
- **Predictions** — game outcome probabilities, a 10,000-run Monte Carlo game
  simulator (margin/total distributions), player points projections with 80%
  intervals, and five-slot starting-lineup estimates
- **Season outlook** — a 5,000-run Monte Carlo with full East/West tables,
  projected records and pessimistic/median/optimistic bands, plus playoff,
  top-6, #1-seed, conference finals, Finals, championship, and NBA Cup odds.
  The upcoming season uses versioned contract rosters, projected 240-minute
  rotations, availability and age adjustments, and explainable team deltas.
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

Backtest the league-wide season simulation separately. Each target season uses
only the preceding completed regular season, and the resulting registry records
data cutoffs, record error, playoff calibration/Brier score, and title/Cup Brier
scores against simple baselines:

```bash
uv run python -m nba_insights.ml.backtest --seasons 2024-25 2025-26
```

The Methodology page labels trained, holdout-evaluated, heuristic, mechanistic,
and historically backtested outputs separately. A backtest does not imply that
an output beats its baseline; the registry exposes that comparison directly.

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

## Installable web app (PWA)

The full analytics product ships with the API as a responsive, installable
web app — no app store or native toolchain:

```bash
uv run uvicorn nba_insights.api:app --port 8000
```

Open `http://127.0.0.1:8000/app/` on a phone or desktop and choose "Add to
Home Screen". It includes League Pulse, deep player profiles (shot charts,
hot zones, league/position context, splits, on/off, and local contracts),
Explore with CSV export, two-to-four-player comparisons, Team Room, Game
Center with full box scores, shared-sample team matchup comparisons with
ranked model drivers and JSON export, an ephemeral roster/injury/trade scenario
lab with paired before/after simulations, outcome/simulation/player/lineup tools,
official tracking/hustle tables with definitions and cache freshness, browser-local
favorites and opt-in refresh alerts, optional structured AI Q&A, and methodology/model cards.

Salary data stays local-only. AI Q&A requires `uv sync --extra ai` plus a
server-side `ANTHROPIC_API_KEY`; prediction tools explain how to train missing
model artifacts. The service worker uses the network first for the app shell,
with its cache reserved as an offline fallback, so browser installations pick
up UI releases instead of remaining on an old shell.

## JSON API & share cards

The same FastAPI service exposes the data as JSON:

| Endpoint | Returns |
|---|---|
| `/players/search?q=jokic` | matching players with IDs |
| `/players/{id}/career` | per-game averages by season |
| `/players/{id}/percentiles` | current-season league percentile ranks |
| `/players/{id}/insights` | scouting take, league/position ranks, ratings, draft line |
| `/players/{id}/shots` | attempts, zones, hex hot zones, shot diet, xeFG quality |
| `/players/{id}/splits` | home/away, month, rest, and opponent splits |
| `/players/{id}/on-off` | current-team on/off impact |
| `/players/{id}/contract` | local-only career salary history and current/future contract detail |
| `/compare?names=A&names=B` | side-by-side per-game stats (2–4 players) |
| `/players/{id}/card` | self-contained HTML share card |
| `/posters/compare?names=A&names=B` | 1:1 share poster of a comparison (`&format=png` for an image) |
| `/posters/game?home=LAL&away=BOS` | 16:9 share poster of a game prediction (`&format=png`) |
| `/teams` | tricodes of all teams this season |
| `/teams/{team}/profile` | factors, roster, form, lineups, on/off, standings, local payroll |
| `/teams/compare?home=LAL&away=BOS&season=2026-27` | same-sample team metrics, rotations, bench/clutch/head-to-head context, probability drivers, limitations, and share/export metadata |
| `/tracking?category=drives&scope=player&min_games=10` | official drives/touches/passing/defense/speed/hustle rows with definitions, sample filters, schema audit, cache freshness, and share metadata |

The real-feed category/schema audit is recorded in
[`docs/TRACKING_AVAILABILITY.md`](docs/TRACKING_AVAILABILITY.md).
| `/games/{game_id}/box-score?season=2025-26` | cached player box score grouped by team, with traditional endpoint fallback |
| `/games/{game_id}/story?season=2025-26` | cached timeline, shots, lineups, win probability, turning points, clutch, and advanced team box |
| `/predict/game?home=LAL&away=BOS&season=2026-27` | home-team win probability and forecast data basis |
| `/predict/simulate?home=LAL&away=BOS&season=2026-27` | Monte Carlo score/margin/total distributions |
| `/predict/season?season=2026-27` | East/West projected standings with playoff, title, and NBA Cup odds |
| `/predict/season/roster-inputs?season=2026-27&team=LAL` | versioned projected minutes, roster changes, age/availability adjustments, and team forecast deltas |
| `POST /predict/season/scenario` | validated ephemeral minutes, games-missed, roster, and trade-package changes with paired before/after records, seeds, trophy odds, causal-player deltas, and advisory salary checks |
| `/predict/players?season=2026-27&team=LAL` | player minutes/box-stat ranges, trajectories, comparables, and field-normalized award outlook |
| `/predict/player/{id}?opponent=BOS` | points projection with empirical 80% interval |
| `/predict/lineup?team=LAL&player_ids=…` | five-man net and win estimate |
| `/methodology` | evaluation protocol, artifact metrics, journey, rejected ideas |
| `/methodology/registry` | model versions, validation status, data cutoffs, baselines, and calibration |
| `POST /ask` | optional structured natural-language league Q&A |
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
tab) and Game Center stories are built offline from play-by-play and rotation
data. New v4 play-by-play caches include shot coordinates; older v3 caches
still provide timelines and shot-type summaries with an explicit location-data
fallback in the website:

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
