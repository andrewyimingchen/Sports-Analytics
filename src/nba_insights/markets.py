"""Kalshi/Polymarket price tracker: snapshot NBA game prices, score the model.

    uv run python -m nba_insights.markets snapshot   # record current prices
    uv run python -m nba_insights.markets report     # model vs market scorecard

Each ``snapshot`` run records, for every game that hasn't tipped yet, each
exchange's home-win price next to the outcome model's home-win probability
(full-strength rosters, as served by ``/predict/game``) and, for games in
the latest official injury report, the model's probability with that
report's expected minutes out (see :mod:`nba_insights.injuries`, which each
snapshot also keeps up to date). Run it on a timer
(see deploy/systemd/possession-lab-markets.timer): a game's first snapshot is
its "opening" line, its last one before tip-off its "closing" line. The
nightly schedule refresh then supplies results for ``report``.

The log lives in the cache database under ``markets/snapshots/<season>`` so it
is backed up with everything else. Prices are personal research data: they
stay in this CLI and the internal console, never the public API/PWA.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from nba_insights.analysis.markets import (
    MODELS,
    SNAPSHOT_COLUMNS,
    market_scorecard,
    match_prices,
    opening_closing,
    schedule_games,
)
from nba_insights.config import calendar_season
from nba_insights.errors import EXPECTED_ERRORS, reason_for
from nba_insights.ingest import NBAClient, serving_client

logger = logging.getLogger(__name__)

# older than the client's 5-minute price cache allows for: a stale fallback
MAX_PRICE_AGE = pd.Timedelta(minutes=10)

# a missing/unreadable model artifact costs only the model column
_MODEL_ERRORS: tuple[type[BaseException], ...] = (*EXPECTED_ERRORS, OSError)


def snapshot_key(season: str) -> str:
    return f"markets/snapshots/{season}"


def load_snapshots(client: NBAClient, season: str | None = None) -> pd.DataFrame:
    """Every recorded snapshot row for *season* (empty frame if none yet)."""
    stored = client.cache.get(snapshot_key(season or calendar_season()))
    if stored is None:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    return stored


def model_probabilities(
    client: NBAClient,
    rows: pd.DataFrame,
    missing: dict[tuple[str, str, str], tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """Outcome-model home-win probabilities per row (NaN when unavailable).

    MODEL_HOME_PROB is the full-strength probability ``/predict/game``
    serves; MODEL_HOME_PROB_INJ adds the injury report's expected minutes
    out (*missing*, keyed by (GAME_DATE, AWAY, HOME)) and is NaN for games
    the latest report doesn't cover.
    """
    # Imported lazily: loading the model and team snapshot is the slow part,
    # and a missing artifact should only cost the model columns.
    from nba_insights.api.shared import snapshot_for_day, today
    from nba_insights.ml import GameOutcomeModel
    from nba_insights.ml.features import matchup_features
    from nba_insights.ml.train import OUTCOME_PATH

    missing = missing or {}
    probs = pd.DataFrame(
        float("nan"), index=rows.index, columns=["MODEL_HOME_PROB", "MODEL_HOME_PROB_INJ"]
    )
    try:
        model = GameOutcomeModel.load(OUTCOME_PATH)
        snapshot = snapshot_for_day(today(), client)
    except _MODEL_ERRORS as error:
        logger.warning("model probabilities unavailable: %s", reason_for(error))
        return probs

    def predict(home: str, away: str, home_min: float = 0.0, away_min: float = 0.0) -> float:
        features = matchup_features(
            snapshot, home, away, home_missing_min=home_min, away_missing_min=away_min
        )
        return round(float(model.predict_proba(features).iloc[0]), 4)

    for index, row in rows.iterrows():
        home, away = row["HOME"], row["AWAY"]
        if home not in snapshot.index or away not in snapshot.index:
            continue
        probs.loc[index, "MODEL_HOME_PROB"] = predict(home, away)
        out = missing.get((row["GAME_DATE"], away, home))
        if out is not None:
            probs.loc[index, "MODEL_HOME_PROB_INJ"] = predict(home, away, *out)
    return probs


def injury_minutes(client: NBAClient) -> dict[tuple[str, str, str], tuple[float, float]]:
    """Expected minutes out per reported game from the latest injury report.

    Any failure (report, game logs) degrades to {} -- no injury column --
    rather than costing the price snapshot.
    """
    from nba_insights.injuries import game_missing_minutes, players_out, update_injuries

    try:
        report = update_injuries(client)
        if report.empty:
            return {}
        return game_missing_minutes(report, players_out(client, report))
    except EXPECTED_ERRORS as error:
        logger.warning("injury adjustment unavailable: %s", reason_for(error))
        return {}


def is_fresh(prices: pd.DataFrame, now: pd.Timestamp) -> bool:
    """Whether *prices* came from a fetch within :data:`MAX_PRICE_AGE`."""
    if "FETCHED_AT" not in prices.columns or prices.empty:
        return False
    return bool(now - prices["FETCHED_AT"].max() <= MAX_PRICE_AGE)


def take_snapshot(client: NBAClient, now: pd.Timestamp | None = None) -> tuple[int, int]:
    """Append one snapshot of every upcoming game's prices to the log.

    Returns (rows recorded, sources that failed). A failed exchange is
    logged and skipped so the other one is still recorded.
    """
    now = now or pd.Timestamp.now("UTC")
    # the calendar season, not current_season(): that one stays on last
    # season until opening night has a result, which would miss the opener
    season = calendar_season()
    frames, failures = [], 0
    for name, fetch in (
        ("kalshi", client.kalshi_nba_games),
        ("polymarket", lambda: client.polymarket_nba_games(season)),
    ):
        try:
            prices = fetch()
        except EXPECTED_ERRORS as error:
            failures += 1
            logger.warning("%s prices unavailable: %s", name, reason_for(error))
            continue
        if not is_fresh(prices, now):
            # a failed refresh served the cache's last good copy
            failures += 1
            logger.warning("%s prices are stale; skipping this snapshot", name)
            continue
        frames.append(prices)
    if not frames:
        return 0, failures

    games = schedule_games(client.schedule(season))
    rows = match_prices(games, pd.concat(frames, ignore_index=True), now)
    if rows.empty:
        logger.info("no upcoming games with prices")
        return 0, failures
    rows[["MODEL_HOME_PROB", "MODEL_HOME_PROB_INJ"]] = model_probabilities(
        client, rows, injury_minutes(client)
    )
    rows = rows[SNAPSHOT_COLUMNS]

    log = load_snapshots(client, season)
    combined = rows if log.empty else pd.concat([log, rows], ignore_index=True)
    client.cache.put(snapshot_key(season), combined)
    logger.info("recorded %d prices (%d snapshot rows total)", len(rows), len(combined))
    return len(rows), failures


def report(client: NBAClient, season: str | None = None, edge: float = 0.03) -> pd.DataFrame:
    """Model-vs-market scorecard over every finished, tracked game.

    One row per (model column, exchange): MODEL is full strength, MODEL_INJ
    injury-adjusted (only games the injury report covered).
    """
    season = season or calendar_season()
    snapshots = load_snapshots(client, season)
    if snapshots.empty:
        return pd.DataFrame()
    games = schedule_games(client.schedule(season))
    lines = opening_closing(snapshots)
    cards = [market_scorecard(lines, games, edge=edge, model=model) for model in MODELS]
    scored = [card for card in cards if not card.empty]
    return pd.concat(scored, ignore_index=True) if scored else pd.DataFrame()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Kalshi/Polymarket NBA price tracker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot", help="record current prices for upcoming games")
    rep = sub.add_parser("report", help="score the model against closing prices")
    rep.add_argument("--season", default=None, metavar="YYYY-YY")
    rep.add_argument(
        "--edge", type=float, default=0.03, help="model-market gap that counts as a disagreement"
    )
    args = parser.parse_args()

    client = serving_client()
    if args.command == "snapshot":
        recorded, failures = take_snapshot(client)
        sys.exit(1 if failures and not recorded else 0)

    card = report(client, season=args.season, edge=args.edge)
    if card.empty:
        print("no finished games tracked yet")
        return
    with pd.option_context("display.width", 160, "display.float_format", "{:.3f}".format):
        print(card.to_string(index=False))


if __name__ == "__main__":
    main()
