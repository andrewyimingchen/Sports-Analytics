"""JSON API over the same ingest/analysis layers the Streamlit app uses.

Run with: uv run uvicorn nba_insights.api:app --reload

The NBAClient is provided by a FastAPI dependency so tests can substitute a
fake; all endpoints read through the shared cache, so the API and the app
warm each other.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from nba_insights.analysis import career_per_game, comparison_table, percentile_ranks
from nba_insights.api.cards import render_player_card
from nba_insights.config import current_season, past_seasons
from nba_insights.ingest import NBAClient
from nba_insights.ml import GameOutcomeModel
from nba_insights.ml.elo import current_elo
from nba_insights.ml.features import matchup_features, team_form_snapshot
from nba_insights.ml.train import OUTCOME_PATH

app = FastAPI(title="NBA Insights API", version="0.1.0")

_STATIC = Path(__file__).parent / "static"
app.mount("/app", StaticFiles(directory=_STATIC, html=True), name="mobile")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@lru_cache(maxsize=1)
def get_client() -> NBAClient:
    return NBAClient()


Client = Annotated[NBAClient, Depends(get_client)]


@lru_cache(maxsize=1)
def get_outcome_model() -> GameOutcomeModel:
    if not OUTCOME_PATH.exists():
        raise HTTPException(
            503, "models not trained: run `uv run python -m nba_insights.ml.train`"
        )
    return GameOutcomeModel.load(OUTCOME_PATH)


OutcomeModel = Annotated[GameOutcomeModel, Depends(get_outcome_model)]


@lru_cache(maxsize=2)
def _snapshot_for_day(day: str, client: NBAClient) -> pd.DataFrame:
    """Team form snapshot with Elo, cached per calendar day."""
    snapshot = team_form_snapshot(client.team_games())
    try:
        games = pd.concat(
            [client.team_games(s) for s in [*past_seasons(2), current_season()]],
            ignore_index=True,
        )
        snapshot["elo"] = current_elo(games).reindex(snapshot.index)
    except Exception:
        pass  # matchup_features degrades to a neutral elo_diff
    return snapshot


def _find_player(client: NBAClient, player_id: int) -> dict:
    match = [p for p in client.search_players("") if p["id"] == player_id]
    if not match:
        raise HTTPException(404, f"no player with id {player_id}")
    return match[0]


@app.get("/teams")
def teams(client: Client) -> list[str]:
    """Tricodes of all teams with games this season."""
    day = pd.Timestamp.utcnow().date().isoformat()
    return sorted(_snapshot_for_day(day, client).index)


@app.get("/predict/game")
def predict_game(home: str, away: str, client: Client, model: OutcomeModel) -> dict:
    """Home-team win probability for a matchup, both sides at full strength."""
    day = pd.Timestamp.utcnow().date().isoformat()
    snapshot = _snapshot_for_day(day, client)
    for team in (home, away):
        if team not in snapshot.index:
            raise HTTPException(404, f"unknown team {team!r}")
    if home == away:
        raise HTTPException(422, "home and away must differ")
    prob = float(model.predict_proba(matchup_features(snapshot, home, away)).iloc[0])
    return {"home": home, "away": away, "home_win_prob": round(prob, 3)}


_HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"


@lru_cache(maxsize=256)
def _fetch_headshot(player_id: int) -> bytes | None:
    import requests

    try:
        r = requests.get(
            _HEADSHOT_URL.format(player_id=player_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        return r.content
    except Exception:
        return None


@app.get("/players/{player_id}/headshot")
def player_headshot(player_id: int) -> Response:
    """Proxy the NBA CDN headshot (it rejects browser hotlinking)."""
    content = _fetch_headshot(player_id)
    if content is None:
        raise HTTPException(404, "no headshot available")
    return Response(content=content, media_type="image/png")


@app.get("/players/search")
def search_players(q: Annotated[str, Query(min_length=3)], client: Client) -> list[dict]:
    return [
        {"id": p["id"], "full_name": p["full_name"], "is_active": p["is_active"]}
        for p in client.search_players(q)
    ]


@app.get("/players/{player_id}/career")
def player_career(player_id: int, client: Client) -> list[dict]:
    """Per-game career averages, one record per season."""
    totals = client.career_stats(player_id)
    if totals.empty:
        raise HTTPException(404, f"no career data for player {player_id}")
    return career_per_game(totals).to_dict(orient="records")


@app.get("/players/{player_id}/percentiles")
def player_percentiles(player_id: int, client: Client) -> dict:
    """League percentile ranks (0-100) for the current season."""
    player = _find_player(client, player_id)
    league = client.league_player_stats()
    try:
        ranks = percentile_ranks(league, player["full_name"])
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "player": player["full_name"],
        "season": current_season(),
        "percentiles": ranks.to_dict(),
    }


@app.get("/compare")
def compare(
    names: Annotated[list[str], Query(min_length=2, max_length=4)], client: Client
) -> dict:
    """Side-by-side per-game stats for 2-4 players in the current season."""
    league = client.league_player_stats()
    try:
        table = comparison_table(league, names)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"season": current_season(), "stats": table.to_dict()}


@app.get("/players/{player_id}/card", response_class=HTMLResponse)
def player_card(player_id: int, client: Client) -> str:
    """Self-contained HTML share card: headline per-game stats + percentiles."""
    player = _find_player(client, player_id)
    totals = client.career_stats(player_id)
    if totals.empty:
        raise HTTPException(404, f"no career data for player {player_id}")
    latest = career_per_game(totals).iloc[-1]

    ranks = None
    if player["is_active"]:
        try:
            ranks = percentile_ranks(client.league_player_stats(), player["full_name"])
        except Exception:  # card degrades to stats-only rather than 500ing
            ranks = None

    return render_player_card(player["full_name"], latest, ranks)
