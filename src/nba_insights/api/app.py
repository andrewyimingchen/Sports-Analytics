"""JSON API over the same ingest/analysis layers the Streamlit app uses.

Run with: uv run uvicorn nba_insights.api:app --reload

The NBAClient is provided by a FastAPI dependency so tests can substitute a
fake; all endpoints read through the shared cache, so the API and the app
warm each other.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from nba_insights.analysis import career_per_game, comparison_table, percentile_ranks
from nba_insights.api.cards import render_player_card
from nba_insights.config import current_season
from nba_insights.ingest import NBAClient

app = FastAPI(title="NBA Insights API", version="0.1.0")


@lru_cache(maxsize=1)
def get_client() -> NBAClient:
    return NBAClient()


Client = Annotated[NBAClient, Depends(get_client)]


def _find_player(client: NBAClient, player_id: int) -> dict:
    match = [p for p in client.search_players("") if p["id"] == player_id]
    if not match:
        raise HTTPException(404, f"no player with id {player_id}")
    return match[0]


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
