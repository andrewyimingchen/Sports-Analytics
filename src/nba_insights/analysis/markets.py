"""Model-vs-market scoring for NBA game-winner prices (pure, no I/O).

The tracker (:mod:`nba_insights.markets`) appends one row per game per
exchange each time it runs: the exchange's home-win price and the outcome
model's home-win probability at that moment. From that log:

- :func:`opening_closing` keeps each game's first and last pre-tip snapshot
  (the "opening" and "closing" lines, as far as our snapshots saw them);
- :func:`market_scorecard` scores the model and each exchange's closing
  price against results, and asks the two questions that decide whether
  the model has an edge: does the line move toward the model between open
  and close (closing-line value), and would flat bets where the model
  disagreed with the close have made money at the quoted ask?
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SNAPSHOT_COLUMNS = [
    "SNAPSHOT_AT",
    "SOURCE",
    "MARKET_ID",
    "GAME_ID",
    "GAME_DATE",
    "TIP_UTC",
    "AWAY",
    "HOME",
    "HOME_PRICE",
    "HOME_BID",
    "HOME_ASK",
    "VOLUME",
    "MODEL_HOME_PROB",
    "MODEL_HOME_PROB_INJ",
]

MODELS = {"MODEL": "MODEL_HOME_PROB", "MODEL_INJ": "MODEL_HOME_PROB_INJ"}


def schedule_games(schedule: pd.DataFrame) -> pd.DataFrame:
    """One row per game from the stats.nba.com season schedule.

    GAME_DATE is the US Eastern calendar date (how both exchanges date a
    game); HOME_WIN is 1/0 for finished games and NaN otherwise.
    """
    games = pd.DataFrame(
        {
            "GAME_ID": schedule["gameId"].astype(str),
            "GAME_DATE": schedule["gameDateEst"].astype(str).str[:10],
            "TIP_UTC": pd.to_datetime(schedule["gameDateTimeUTC"], utc=True),
            "AWAY": schedule["awayTeam_teamTricode"],
            "HOME": schedule["homeTeam_teamTricode"],
        }
    )
    final = schedule["gameStatus"] == 3
    home_won = (schedule["homeTeam_score"] > schedule["awayTeam_score"]).astype(float)
    games["HOME_WIN"] = home_won.where(final)
    return games


def match_prices(games: pd.DataFrame, prices: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Exchange prices for games that haven't tipped yet, keyed to GAME_ID.

    Matches on (GAME_DATE, AWAY, HOME). Prices for games already under way
    are dropped: in-game prices aren't comparable with a pre-game model.
    """
    upcoming = games[games["TIP_UTC"] > now][["GAME_ID", "GAME_DATE", "TIP_UTC", "AWAY", "HOME"]]
    matched = prices.merge(upcoming, on=["GAME_DATE", "AWAY", "HOME"], how="inner")
    matched.insert(0, "SNAPSHOT_AT", now)
    return matched


def opening_closing(snapshots: pd.DataFrame) -> pd.DataFrame:
    """First and last pre-tip snapshot per (SOURCE, GAME_ID).

    Returns OPEN_/CLOSE_ prefixed price and model columns (MODEL: full
    strength, MODEL_INJ: injury-adjusted) plus HOME_BID / HOME_ASK from the
    closing snapshot (what a bet at the close would pay). Snapshots logged
    before a column existed read it as NaN.
    """
    pre = snapshots.reindex(columns=SNAPSHOT_COLUMNS)
    pre = pre[pre["SNAPSHOT_AT"] < pre["TIP_UTC"]].sort_values("SNAPSHOT_AT")
    keys = ["SOURCE", "GAME_ID"]
    # head/tail, not first/last: those skip NaNs and would mix snapshots
    first = pre.groupby(keys).head(1)
    last = pre.groupby(keys).tail(1)
    renames = {"HOME_PRICE": "PRICE", **{src: name for name, src in MODELS.items()}}
    lines = first[[*keys, "GAME_DATE", "AWAY", "HOME", "SNAPSHOT_AT", *renames]].rename(
        columns={"SNAPSHOT_AT": "OPEN_AT", **{k: f"OPEN_{v}" for k, v in renames.items()}}
    )
    closing = last[[*keys, "SNAPSHOT_AT", "HOME_BID", "HOME_ASK", *renames]].rename(
        columns={"SNAPSHOT_AT": "CLOSE_AT", **{k: f"CLOSE_{v}" for k, v in renames.items()}}
    )
    return lines.merge(closing, on=keys).reset_index(drop=True)


def _log_loss(prob: pd.Series, outcome: pd.Series) -> float:
    p = prob.clip(1e-6, 1 - 1e-6)
    return float(-(outcome * np.log(p) + (1 - outcome) * np.log(1 - p)).mean())


def _brier(prob: pd.Series, outcome: pd.Series) -> float:
    return float(((prob - outcome) ** 2).mean())


def market_scorecard(
    lines: pd.DataFrame, games: pd.DataFrame, edge: float = 0.03, model: str = "MODEL"
) -> pd.DataFrame:
    """Score a model column against each exchange's closing price.

    *model* is "MODEL" (full strength) or "MODEL_INJ" (injury-adjusted).
    One row per SOURCE over its finished games with that probability:

    - GAMES, and log loss / Brier for the model (CLOSE_<model>) and the
      market (CLOSE_PRICE). Lower is better; the model beating the
      closing price on these is the bar for a real edge.
    - CLV_GAMES / CLV_MEAN: over games where the model disagreed with the
      opening price by more than *edge*, the mean line move toward the
      model's side (in probability points; positive = the market moved
      toward the model before tip-off).
    - BETS / ROI: flat 1-unit bets on the model's side wherever it
      disagreed with the closing price by more than *edge*, bought at the
      closing ask (home: HOME_ASK; away: 1 - HOME_BID). Exchange fees are
      not included, so this overstates real returns slightly.
    """
    scored = lines.merge(games[["GAME_ID", "HOME_WIN"]], on="GAME_ID")
    close_model, open_model = f"CLOSE_{model}", f"OPEN_{model}"
    scored = scored.dropna(subset=["HOME_WIN", close_model, "CLOSE_PRICE"])
    rows = []
    for source, df in scored.groupby("SOURCE"):
        row = {
            "MODEL": model,
            "SOURCE": source,
            "GAMES": len(df),
            "MODEL_LOG_LOSS": _log_loss(df[close_model], df["HOME_WIN"]),
            "MARKET_LOG_LOSS": _log_loss(df["CLOSE_PRICE"], df["HOME_WIN"]),
            "MODEL_BRIER": _brier(df[close_model], df["HOME_WIN"]),
            "MARKET_BRIER": _brier(df["CLOSE_PRICE"], df["HOME_WIN"]),
        }

        open_gap = df[open_model] - df["OPEN_PRICE"]
        moved = df[open_gap.abs() > edge]
        toward = (moved["CLOSE_PRICE"] - moved["OPEN_PRICE"]) * np.sign(
            moved[open_model] - moved["OPEN_PRICE"]
        )
        row["CLV_GAMES"] = len(moved)
        row["CLV_MEAN"] = float(toward.mean()) if len(moved) else np.nan

        gap = df[close_model] - df["CLOSE_PRICE"]
        home_bets = df[(gap > edge) & df["HOME_ASK"].notna()]
        away_bets = df[(gap < -edge) & df["HOME_BID"].notna()]
        home_profit = np.where(home_bets["HOME_WIN"] == 1, 1 / home_bets["HOME_ASK"] - 1, -1.0)
        away_profit = np.where(
            away_bets["HOME_WIN"] == 0, 1 / (1 - away_bets["HOME_BID"]) - 1, -1.0
        )
        profit = np.concatenate([home_profit, away_profit])
        row["BETS"] = len(profit)
        row["ROI"] = float(profit.mean()) if len(profit) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)
