"""Request-independent helpers that more than one router needs."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import pandas as pd
from fastapi import HTTPException

from nba_insights.config import (
    current_season,
    past_seasons,
    prediction_seasons,
    previous_season,
)
from nba_insights.errors import EXPECTED_ERRORS, FAILURES, reason_for
from nba_insights.ingest import NBAClient
from nba_insights.ml import GameOutcomeModel
from nba_insights.ml.elo import current_elo
from nba_insights.ml.features import matchup_features, prior_team_form, team_form_snapshot

logger = logging.getLogger(__name__)


def today() -> str:
    """UTC calendar day, the cache key for daily snapshots and forecasts."""
    return pd.Timestamp.now("UTC").date().isoformat()


def team_tricodes(client: NBAClient, season: str | None = None) -> dict[int, str]:
    """TEAM_ID -> tricode for every team in *season* (default: current).

    Early in a season not every team has played, so last season's games
    fill in the rest; current-season rows win where both exist (relocations
    and renames). Returns {} if neither season's games are available.
    """
    season = season or current_season()
    codes: dict[int, str] = {}
    for source in (previous_season(season), season):
        try:
            games = client.team_games(source)
        except EXPECTED_ERRORS:
            logger.warning("team list unavailable for %s", source, exc_info=True)
            continue
        if {"TEAM_ID", "TEAM_ABBREVIATION"} <= set(games.columns):
            pairs = games[["TEAM_ID", "TEAM_ABBREVIATION"]].dropna()
            codes.update(zip(pairs["TEAM_ID"].astype(int), pairs["TEAM_ABBREVIATION"], strict=True))
    return codes


@lru_cache(maxsize=2)
def snapshot_for_day(day: str, client: NBAClient) -> pd.DataFrame:
    """Team form snapshot with Elo, cached per calendar day.

    Prior-seeded like the outcome model's training features, so
    early-season serving inputs match the training distribution.
    """
    try:
        priors = prior_team_form(client.team_games(past_seasons(1)[0]))
    except EXPECTED_ERRORS as error:
        FAILURES.record(reason_for(error))
        logger.warning("prior-season form unavailable; serving unseeded snapshot", exc_info=True)
        priors = None
    snapshot = team_form_snapshot(
        client.team_games(), form_priors=priors, team_codes=team_tricodes(client)
    )
    try:
        games = pd.concat(
            [client.team_games(s) for s in [*past_seasons(2), current_season()]],
            ignore_index=True,
        )
        snapshot["elo"] = current_elo(games).reindex(snapshot.index)
    except EXPECTED_ERRORS as error:
        FAILURES.record(reason_for(error))
        # matchup_features degrades to a neutral elo_diff
        logger.warning("Elo unavailable; predictions use a neutral elo_diff", exc_info=True)
    return snapshot


class Degradations:
    """The optional sections one response had to serve without, and why.

    Wrap each optional section in :meth:`section`: an expected failure
    (upstream, data, artifact) is logged with the endpoint and context,
    counted, and recorded as ``{"section", "reason"}`` for the response's
    ``degraded`` list; any other exception propagates as a defect.
    """

    def __init__(self, endpoint: str, **context: object) -> None:
        self.endpoint = endpoint
        self.context = " ".join(f"{key}={value}" for key, value in context.items())
        self.items: list[dict[str, str]] = []

    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        try:
            yield
        except EXPECTED_ERRORS as error:
            reason = reason_for(error)
            FAILURES.record(reason)
            logger.warning(
                "%s degraded: %s %s %s", self.endpoint, name, reason, self.context, exc_info=True
            )
            self.items.append({"section": name, "reason": reason})


def find_player(client: NBAClient, player_id: int) -> dict[str, Any]:
    match = client.find_player(player_id)
    if not match:
        raise HTTPException(404, f"no player with id {player_id}")
    return match


def prediction_context(season: str | None) -> tuple[str, str, str]:
    """Return requested season, source-data season, and projection mode."""
    available = prediction_seasons()
    selected = season or available[0]
    if selected not in available:
        raise HTTPException(
            422,
            f"prediction season must be one of {', '.join(available)}",
        )
    basis = available[0]
    mode = "season_to_date" if selected == basis else "preseason_carry_forward"
    return selected, basis, mode


def validate_matchup(snapshot: pd.DataFrame, home: str, away: str) -> None:
    """404 for a team missing from the snapshot, 422 for a self-matchup."""
    for team in (home, away):
        if team not in snapshot.index:
            raise HTTPException(404, f"unknown team {team!r}")
    if home == away:
        raise HTTPException(422, "home and away must differ")


def matchup_probability(
    client: NBAClient,
    model: GameOutcomeModel,
    home: str,
    away: str,
    season: str | None = None,
) -> float:
    """Home-team win probability, validating the matchup (404/422)."""
    prediction_context(season)
    snapshot = snapshot_for_day(today(), client)
    validate_matchup(snapshot, home, away)
    return float(model.predict_proba(matchup_features(snapshot, home, away)).iloc[0])


def finite_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-safe records: pandas NaN/NaT become null, timestamps become ISO strings."""
    clean = frame.astype(object).where(frame.notna(), None)
    for column in clean.columns:
        clean[column] = clean[column].map(
            lambda value: (
                value.isoformat() if isinstance(value, (pd.Timestamp, pd.Timedelta)) else value
            )
        )
    return clean.to_dict(orient="records")
