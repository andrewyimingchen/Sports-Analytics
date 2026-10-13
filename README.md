# POSSESSION LAB 🏀

POSSESSION LAB is an installable progressive web app backed by FastAPI. The
product lives at `/app/`; the JSON API is its backend contract. The Streamlit
app in `app/` is an internal research and diagnostics console, not a second
customer-facing product (see [Product surfaces](docs/PRODUCT_SURFACES.md)).

The PWA's primary navigation:

- **League pulse** — the landing page: per-game and net/clutch-rating leaders,
  Elo power rankings, team form, and the next slate with win probabilities; a
  season selector rewinds leaders and team form to any season back to 1996-97
- **Players** — search, then a deep profile: career trajectory, form trends,
  shot chart with hot zones and shot quality (xeFG%), league and position
  percentile ranks incl. net rating, clutch rating, and DARKO DPM, splits,
  on/off impact, comparables, game log, and draft pedigree (contract detail
  for local or API-key callers only)
- **Games** — season scores and schedule; finals open a cached game story with
  win-probability flow, turning points, shots, lineups, clutch context,
  advanced team stats, play-by-play, and the full box score
- **Matchup lab** — game outcome probabilities with ranked model drivers,
  same-sample team comparison, a 10,000-run Monte Carlo score simulator,
  player points projections with 80% intervals, starting-five estimates, and
  a share poster
- **More**, which holds:
  - **Season outlook** — 5,000-run season forecasts (seeds, playoff, title,
    and NBA Cup odds), next-season roster inputs and player projections, and a
    roster/injury/trade scenario lab with paired before/after simulations
  - **Team room** — record, ratings, four factors, roster, lineups, on/off,
    standings, and (local only) payroll
  - **Explore stats** — the filterable, sortable league table with CSV export
  - **Compare** — two to four players side by side, with a share poster
  - **Tracking + hustle** — official tracking tables with definitions and
    cache freshness
  - **Ask the league** — optional AI questions over the cached league table
    (needs the `ai` extra and a server-side credential)
  - **How models work** — methodology, model registry, backtests, and the
    reproducibility manifest

Built on the official-ish [`nba_api`](https://github.com/swar/nba_api)
(stats.nba.com). Every response is cached locally in SQLite, so repeat views
never hit the network: finished seasons are cached forever, current-season data
refreshes daily.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```bash
uv sync
uv run python -m nba_insights.warm --top 20   # optional but recommended: prefetch
uv run uvicorn nba_insights.api:app --port 8000
```

Then open http://127.0.0.1:8000/app/, search a player, and explore. The warm
step prefetches the league dashboards and top players so the first page
load is instant; skip it and the first views fetch live instead
(rate-limited, so the landing page can take a while on a cold cache).

For internal research and data diagnostics only:

```bash
uv run streamlit run app/streamlit_app.py
```

### iOS and Android app

The native mobile client lives in [`mobile/`](mobile/). It is an Expo/React
Native app with League Pulse, player profiles, team rooms, matchup forecasts,
device-local favorites, offline response fallback, and secure API-key storage.
Start the FastAPI backend and then Expo:

```bash
uv run uvicorn nba_insights.api:app --host 0.0.0.0 --port 8000
cd mobile
npm install
npm start
```

See [`mobile/README.md`](mobile/README.md) for emulator, physical-device, EAS,
and store-build instructions.

## Architecture

```
src/nba_insights/
├── ingest/      # NBAClient: rate-limited, retrying nba_api wrapper
├── store/       # SQLite DataFrame cache with per-endpoint TTLs
├── analysis/    # pure pandas: trends, percentiles, comparisons, ratings, zones
├── ml/          # features, Elo, outcome/points/lineup models, game simulator
├── pbp/         # play-by-play corpus: backfill, garbage time, stint lineups
└── api/         # FastAPI JSON endpoints + PWA
app/             # internal Streamlit research and diagnostics console
tests/           # unit + AppTest smoke tests — no network required
```

The layers are strictly separated: **ingest** is the only code that touches the
network, **store** decides freshness (and serves stale data if stats.nba.com is
unreachable, so the app degrades gracefully offline), and **analysis** is pure
functions over DataFrames — fully testable without a connection.

The PWA is the official product surface; Streamlit has no public feature-parity
obligation. See [`docs/PRODUCT_SURFACES.md`](docs/PRODUCT_SURFACES.md) for the
development and retirement policy, and [`docs/PRODUCT_ROADMAP.md`](docs/PRODUCT_ROADMAP.md)
for what stands between this repository and a product.

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

Three trained models power the Matchup lab. Train them once (fetches three
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

| Model | Approach |
|---|---|
| Game outcome | Logistic regression on prior-seeded season-to-date form differentials (win%, net rating, four factors, pace, ORtg/DRtg), rest/back-to-backs, expected minutes out (derived absences), carried-over Elo + home court |
| Player points | Two-stage: minutes model (rotation trend, rest, roster availability) × per-minute rate model (EWMA form, opponent context, teammate absences); ships an empirical 80% interval from training residual quantiles, binned by projection level |
| Starting five | Observed lineup net rating blended with a per-36 plus-minus proxy through a fitted win curve; the observed side prefers our stint table (exact rotation intervals, garbage time stripped, estimated possessions) over the season-aggregate dashboard; pure proxy when the five never played together |
| Game simulator | Monte Carlo over pace and ratings (10,000 sims: shared possessions, per-100 scoring vs opponent defense, home court, minutes out, overtime); parameters fitted on the training seasons. The logistic model keeps the headline probability; the simulator supplies margin/total distributions |

Evaluation is a temporal holdout: trained on the three seasons before the
holdout season and scored on it, with hyperparameters tuned on a dev season
(the most recent training season) so the holdout is only touched once. The
holdout is the current season once it has 300 games (about early December);
before that it is the last completed season, so opening-week retrains
reproduce the previous models instead of evaluating on a handful of games. Artifacts live in `data/models/` (never committed).

### Recorded results

Every training and backtest run records itself in the tracked
[`models/manifest.json`](models/manifest.json): command and configuration,
code revision, data cutoffs, feature schema, fingerprints of the cached source
snapshots it read, SHA-256 hashes of the artifacts it wrote, and its metrics
with their baselines. The API serves it at `/methodology/manifest` and checks
the hashes against the artifacts it actually loads, so drift or a missing
artifact is reported rather than hidden. The table below is generated from
that record (`uv run python -m nba_insights.ml.manifest readme`), and a test
fails if it falls out of date.

<!-- model-metrics:start (generated by `uv run python -m nba_insights.ml.manifest readme`) -->
| Model | Version | Evaluation | Result | Baseline |
|---|---|---|---|---|
| Game outcome | `logistic-outcome-v1` | temporal holdout 2025-26 (1225 games) | 70.2% accuracy, log loss 0.589 | 55.4% / 0.687 (always pick home) |
| Player points | `player-points-v2-statline` | temporal holdout 2025-26 (21204 player-games) | MAE 4.58; 80% interval covered 80.4% | MAE 4.72 (10-game average) |
| Player stat line | `player-points-v2-statline` | temporal holdout 2025-26 (same player-games) | REB 1.90, AST 1.36, STL 0.72, FG3M 0.92 MAE | REB 1.95, AST 1.39, STL 0.75, FG3M 0.92 (10-game averages) |
| Season forecast | `season-forecast-v2-roster` | backtest 2024-25, 2025-26 (60 team-seasons) | win MAE 8.93; playoff Brier 0.246 | MAE 11.10; Brier 0.249 |
| Player season | `player-season-v1` | stable-roster holdout 2025-26 (241 players) | PTS MAE 2.68; interval covered 82.6% | none recorded |
| Starting five / game simulator | `lineup-blend-v1` / `matchup-simulator-v1` | no holdout recorded | heuristic blend / distribution diagnostic | — |

Recorded in [`models/manifest.json`](models/manifest.json) (updated 2026-10-13T16:41:42+00:00), including code revision, data cutoffs, source fingerprints, and artifact hashes.
<!-- model-metrics:end -->

After retraining or re-running a backtest, commit the updated manifest and
regenerated table together. Artifacts that predate manifest tracking were
recorded with `uv run python -m nba_insights.ml.manifest backfill`; their
source snapshots are marked `not_recorded` until the command is re-run.

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
league-rank dumbbells, cumulative model-driver waterfalls, and JSON export, an
ephemeral roster/injury/trade scenario lab with paired before/after simulations,
outcome/simulation/player/lineup tools, official tracking/hustle tables with
definitions and cache freshness, browser-local favorites and opt-in refresh
alerts, optional structured AI Q&A, and methodology/model cards. Dense analytical
views lead with responsive charts and answer-led captions; exact values remain
available in collapsed, accessible data tables.

The browser client is split into a small HTML shell, shared styles, application
orchestration, reusable utilities, and visualization factories. D3 and
Observable Plot are vendored under `/app/vendor/`, so charts work with the same
offline app-shell behavior as the rest of the PWA and do not rely on a public
CDN at runtime.

Salary data stays private: direct-local callers can access it, while remote
callers need the deployment API key described below. AI Q&A requires
`uv sync --extra ai` plus a server-side `ANTHROPIC_API_KEY`; prediction tools
explain how to train missing model artifacts. The service worker uses the
network first for the app shell, with its cache reserved as an offline
fallback, so browser installations pick up UI releases instead of remaining
on an old shell. It also retains last-known copies of explicitly public
metadata, League Pulse, and schedule responses; authenticated, salary,
simulation, and AI responses are never stored by the service worker.

### Protecting remote deployments

Direct localhost use needs no POSSESSION LAB API key. For remote deployments,
`POST /ask` and salary/contract data require `POSSESSION_LAB_API_KEY` via an
`X-API-Key` or Bearer header. Simulation routes have a weighted per-client
budget (100,000 simulated games per 60 seconds by default); set
`POSSESSION_LAB_REQUIRE_API_KEY=true` to authenticate those routes too.

```bash
export POSSESSION_LAB_API_KEY="replace-with-a-long-random-secret"
export POSSESSION_LAB_SIMULATION_BUDGET=100000
export POSSESSION_LAB_AI_REQUEST_BUDGET=5
export POSSESSION_LAB_RATE_WINDOW_SECONDS=60
```

Forwarding headers are ignored unless the immediate proxy IP is listed in
`POSSESSION_LAB_TRUSTED_PROXY_IPS`. If a browser-facing gateway protects the
app, have it inject the API key server-side; never embed the secret in PWA
JavaScript. The built-in budget is per process, so multi-worker deployments
should additionally enforce a shared limit at the gateway.

## JSON API & share cards

The same FastAPI service exposes the data as JSON:

| Endpoint | Returns |
|---|---|
| `/meta` | seasons, prediction seasons, and which optional capabilities are enabled |
| `/league/pulse?season=2025-26` | leaders, team form, and the next slate |
| `/league/explore?rate=per_36&teams=LAL` | the filterable, sortable league player table |
| `/players/search?q=jokic` | matching players with IDs |
| `/players/{id}` | one player's identity, for deep links |
| `/players/{id}/career` | per-game averages by season |
| `/players/{id}/percentiles` | current-season league percentile ranks |
| `/players/{id}/insights` | scouting take, league/position ranks, ratings, draft line |
| `/players/{id}/shots` | attempts, zones, hex hot zones, shot diet, xeFG quality |
| `/players/{id}/splits` | home/away, month, rest, and opponent splits |
| `/players/{id}/on-off` | current-team on/off impact |
| `/players/{id}/games?limit=12` | recent game log |
| `/players/{id}/similar` | current-season statistical comparables |
| `/players/{id}/contract` | career salary history and current/future contract detail (local or API-key callers only) |
| `/compare?names=A&names=B` | side-by-side per-game stats (2–4 players) |
| `/players/{id}/card` | self-contained HTML share card |
| `/posters/compare?names=A&names=B` | 1:1 share poster of a comparison (`&format=png` for an image) |
| `/posters/game?home=LAL&away=BOS` | 16:9 share poster of a game prediction (`&format=png`) |
| `/teams` | tricodes of all teams this season |
| `/teams/{team}/profile` | factors, roster, form, lineups, on/off, standings, local payroll |
| `/teams/compare?home=LAL&away=BOS&season=2026-27` | same-sample team metrics, rotations, bench/clutch/head-to-head context, probability drivers, limitations, and share/export metadata |
| `/tracking?category=drives&scope=player&min_games=10` | official drives/touches/passing/defense/speed/hustle rows with definitions, sample filters, schema audit, cache freshness, and share metadata |

| `/games?season=2025-26` | full-season schedule and results |
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
| `/methodology/registry` | model versions, validation status, data cutoffs, baselines, calibration, and a manifest summary |
| `/methodology/manifest` | the tracked reproducibility manifest, verified against the loaded artifacts |
| `POST /ask` | optional structured natural-language league Q&A |
| `/players/{id}/headshot` | headshot proxy (CDN blocks hotlinking) |
| `/healthz`, `/readyz` | liveness, and readiness with model availability and failure counts |

Every JSON route declares a typed response schema; interactive docs are at
`/docs`. Errors carry a stable `reason` code (`upstream_unavailable`,
`data_unavailable`, `artifact_unavailable`, `provider_failed`,
`internal_error`), and responses that had to omit an optional section list it
under `degraded`. The tracking feed's category/schema audit is recorded in
[`docs/TRACKING_AVAILABILITY.md`](docs/TRACKING_AVAILABILITY.md). The API reads
through the same cache as the Streamlit console, so each warms the other.

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

The stint-level lineup table (used by the Matchup lab's starting-five
estimate) and Games-page stories are built offline from play-by-play and rotation
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

In production, run the nightly pipeline instead of `warm` alone. It warms the
cache, optionally extends the play-by-play corpus (`--pbp`), retrains weekly
(re-scoring the holdout and recording the run in the manifest), and scores the
shipped outcome model on the current season's completed games. That live
calibration is served at `/methodology/drift` and alerts when recent log loss
drifts more than two standard errors above the holdout. Run it from the repo
root so it fills the same `data/` directory the app reads:

```cron
0 6 * * * cd /path/to/Sports-Analytics && uv run python -m nba_insights.pipeline --pbp
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#scheduling-the-nightly-pipeline)
for a systemd timer, alert webhooks, and the run log.

## Deployment

Local-first by design — stats.nba.com blocks most datacenter IPs, so remote
deployments ship a warmed cache. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
for the workflow, options, and the provided Dockerfile.

## Development

```bash
uv sync --all-groups          # deps, dev tools, and the browser-test group
uv run playwright install chromium   # once, for the browser suite
uv run pytest                 # tests (offline; browser tests skip without Playwright)
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy                   # types
npm ci && npm run lint && npm test   # PWA lint and unit tests
uv run streamlit run app/streamlit_app.py   # internal console only
```

CI runs the Python checks on 3.11–3.13 with a coverage floor, plus PWA lint,
browser and accessibility tests, a container smoke test, and weekly
dependency audits. Issue tracking uses
[beads](https://github.com/gastownhall/beads) (`bd ready` to see open work).

## Names

**POSSESSION LAB** is the product: the PWA title and manifest, the API title,
and the mobile app. Several internal identifiers keep the project's original
name on purpose, because renaming them would break existing installs or
deployments without changing anything a user sees:

| Identifier | Why it stays |
|---|---|
| `nba-insights` distribution and `nba_insights` import package | every module path, entry point (`python -m nba_insights.*`), and the `nba_insights.api:app` server target |
| `NBA_INSIGHTS_DATA_DIR`, `NBA_INSIGHTS_MANIFEST` | environment variables already set in deployments and containers |
| `nba-insights-shell-*` / `nba-insights-public-data-*` service-worker caches | renaming would orphan the caches of already-installed PWAs |

New user-facing text uses POSSESSION LAB; new environment variables use the
`POSSESSION_LAB_` prefix (see the API safeguards above).

## License and data terms

**Code.** Copyright (c) 2025-2026 Andrew Chen. All rights reserved; see
[`LICENSE`](LICENSE). No open-source license is granted, and the package is
marked `Private :: Do Not Upload`.

**Data.** Third-party data keeps its own terms. This project is for personal
and educational use, and commercial use needs licensed data:

| Source | Used for | Terms in this project |
|---|---|---|
| stats.nba.com via [`nba_api`](https://github.com/swar/nba_api) | all game, player, team, tracking, and play-by-play data | Property of NBA Media Ventures, LLC. Cached locally at rate-limited volume; personal and educational use only |
| [DARKO](https://darko.app) DPM (Kostya Medvedovsky & Andrew Patton) | displayed alongside player ratings, with attribution | Free public site with no published license. Shown as-is and never used as a model feature; remove `NBAClient.darko_dpm` (one cache key) if the creators object, and license it before any commercial use |
| Basketball-Reference contract pages | salary and contract context | Scraped at minimal volume (single pages, long TTLs, always through the cache), knowingly accepting the site's terms-of-service tension for local use. Served only to direct-local or API-key callers, never to anonymous remote users, and never redistributed or used commercially |

For a commercial deployment, license the data instead: BALLDONTLIE's GOAT
tier carries contracts, injuries, and odds; SportsDataIO and Sportradar are
the heavier options.
