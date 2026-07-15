# Architecture

One rule holds everywhere: **the network is touched in exactly one place**
(`ingest.NBAClient`), every fetch goes through the SQLite cache, and
everything downstream of the cache is pure pandas — which is why the whole
test suite runs offline.

```mermaid
flowchart TB
    NBA["stats.nba.com<br/>(via nba_api)"]

    subgraph INGEST["ingest/ — the only network code"]
        CLIENT["NBAClient<br/>rate-limited wrapper<br/><i>client.py</i>"]
    end

    subgraph STORE["store/"]
        CACHE[("SQLite DataFrame cache<br/>per-endpoint TTLs, empty responses never cached<br/><i>data/cache.sqlite3</i>")]
    end

    subgraph PURE["pure pandas — no I/O"]
        ANALYSIS["analysis/<br/>career, form trends,<br/>percentiles, comparisons"]
        PBP["pbp/<br/>play-by-play parsing,<br/>season backfill CLI"]
        FEATURES["ml/features.py<br/>team form, matchups,<br/>player stat-line features"]
        ELO["ml/elo.py<br/>margin-aware Elo,<br/>carried across seasons"]
    end

    subgraph MODELS["ml/ models"]
        OUTCOME["GameOutcomeModel<br/>logistic regression<br/><i>outcome.py</i>"]
        POINTS["PlayerPointsModel<br/>minutes × per-stat rates<br/><i>performance.py</i>"]
        LINEUP["WinCurve + lineup blend<br/><i>lineup.py</i>"]
    end

    TRAIN["ml/train.py — training CLI<br/>train on 3 prior seasons,<br/>evaluate on current (temporal holdout)"]
    ARTIFACTS[("data/models/*.joblib<br/>outcome · points · win_curve")]

    subgraph SERVE["serving"]
        STREAMLIT["app/streamlit_app.py — Streamlit UI<br/>Profile · Compare · Predictions · Methodology<br/>(+ app/methodology.py)"]
        API["api/app.py — FastAPI<br/>JSON endpoints + player cards"]
        PWA["api/static/ — installable PWA<br/>served by the API"]
    end

    NBA --> CLIENT --> CACHE
    CACHE --> ANALYSIS
    CACHE --> PBP
    CACHE --> FEATURES
    CACHE --> ELO
    FEATURES --> TRAIN
    ELO --> TRAIN
    TRAIN --> OUTCOME & POINTS & LINEUP
    OUTCOME & POINTS & LINEUP --> ARTIFACTS
    ARTIFACTS --> STREAMLIT
    ARTIFACTS --> API
    ANALYSIS --> STREAMLIT
    ANALYSIS --> API
    FEATURES --> STREAMLIT
    API --> PWA
```

## Layer contracts

| Layer | Contract |
|---|---|
| `ingest/` | The **only** code that touches the network. Rate-limited `nba_api` wrapper; never called directly by the app layer. |
| `store/` | `Cache.get_or_fetch` fronts every remote call. Per-endpoint TTLs (current-season data refreshes daily); empty responses are never cached. |
| `analysis/`, `ml/features.py`, `pbp/` | Pure functions: DataFrames in, DataFrames out; `KeyError` on missing players/columns. No I/O, so tests stay offline. |
| `ml/train.py` | The evaluation protocol lives here: train on the three seasons before the current one, score on the current season as a true temporal holdout. The shipped artifacts are the ones whose numbers were printed. |
| `app/`, `api/` | Read through the cache and the saved artifacts only. The Streamlit app is the analyst-facing UI; the FastAPI app serves JSON plus the installable PWA. |

## Supporting pieces

- `config.py` — seasons, cache/model paths.
- `viz.py` — plotly half-court trace for shot charts.
- `warm.py` — cache warming.
- Column names follow stats.nba.com conventions (`PTS`, `GP`, `SEASON_ID`, …).
- Model artifacts (`data/models/`) and the cache are never committed; retrain
  with `uv run python -m nba_insights.ml.train`.
