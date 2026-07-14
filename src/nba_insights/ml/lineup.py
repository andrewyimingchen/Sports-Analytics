"""Lineup win probability — a calibrated proxy, not a lineup-level model.

Two pieces:

1. :class:`WinCurve` — win% as a function of per-game point differential
   (net rating proxy), fitted on team-season aggregates. One net point has
   been worth roughly +3 win-percentage points historically; we fit the
   slope from data instead of assuming it.
2. :func:`lineup_net_estimate` — a 5-man lineup's expected net rating,
   proxied by the mean of the players' per-36 plus-minus. This ignores fit
   and lineup synergy entirely; surface that caveat wherever it's shown.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from nba_insights.ml.features import _prepare


class WinCurve:
    """win% ≈ clip(0.5 + slope · net_per_game), slope fitted by least squares."""

    def __init__(self, slope: float = 0.032):
        self.slope = slope

    def fit(self, team_games: pd.DataFrame) -> WinCurve:
        """Fit on per-team-season aggregates of a team-games frame."""
        df = _prepare(team_games)
        agg = df.groupby(["SEASON_ID", "TEAM_ID"]).agg(
            win_pct=("win", "mean"), net=("PLUS_MINUS", "mean")
        )
        # least squares through (net, win_pct - 0.5): forces 0 net -> 50%
        x, y = agg["net"].to_numpy(), agg["win_pct"].to_numpy() - 0.5
        self.slope = float((x @ y) / (x @ x))
        return self

    def win_probability(self, net_per_game: float) -> float:
        return float(np.clip(0.5 + self.slope * net_per_game, 0.01, 0.99))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"slope": self.slope}, path)

    @classmethod
    def load(cls, path: str | Path) -> WinCurve:
        return cls(slope=joblib.load(path)["slope"])


def lineup_net_estimate(league_stats: pd.DataFrame, player_names: list[str]) -> float:
    """Proxy net rating for a 5-man lineup: mean per-36 plus-minus.

    *league_stats* is the per-game league dashboard (PLAYER_NAME, MIN,
    PLUS_MINUS columns). Raises KeyError for unknown players and ValueError
    unless exactly five are given.
    """
    if len(player_names) != 5:
        raise ValueError(f"a lineup is 5 players, got {len(player_names)}")
    rows = league_stats[league_stats["PLAYER_NAME"].isin(player_names)]
    missing = set(player_names) - set(rows["PLAYER_NAME"])
    if missing:
        raise KeyError(f"players not found in league stats: {sorted(missing)}")
    per36 = rows["PLUS_MINUS"] / rows["MIN"].clip(lower=1) * 36
    return float(per36.mean())
