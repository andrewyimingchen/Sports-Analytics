# NBA Insights 🏀

Type any NBA player's name and get a live profile: career trajectory, recent
form, shot chart, and league percentile ranks — plus side-by-side player
comparisons.

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
└── analysis/    # pure pandas: trends, percentiles, comparisons
app/             # Streamlit UI (profile + compare pages)
tests/           # unit tests — no network required
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
