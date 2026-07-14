"""Score-timeline analysis of play-by-play logs. Pure pandas, no I/O.

The first use is garbage-time filtering: blowout minutes are played by
benches under no competitive pressure, so counting them in a team's point
differential adds noise to form features.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _score_timeline(pbp: pd.DataFrame) -> pd.DataFrame:
    """Rows where the score is known, with an integer home-minus-away margin."""
    df = pbp[["period", "scoreHome", "scoreAway"]].copy()
    df["scoreHome"] = pd.to_numeric(df["scoreHome"], errors="coerce")
    df["scoreAway"] = pd.to_numeric(df["scoreAway"], errors="coerce")
    df = df.dropna(subset=["scoreHome", "scoreAway"])
    df["margin"] = df["scoreHome"] - df["scoreAway"]
    return df


def garbage_time_margin(
    pbp: pd.DataFrame, lead_threshold: int = 20, final_threshold: int = 15
) -> float:
    """The game's home-minus-away margin with garbage time stripped.

    Rule: if a fourth-quarter lead reaches *lead_threshold* and the game
    still ends as a *final_threshold*-plus blowout, everything after the
    lead first hit the threshold is garbage time — the margin is frozen at
    that moment. If the trailing team made it a game again (final margin
    under the threshold), nothing is stripped. Overtime is never garbage
    time by construction (an OT game was close in the fourth).
    """
    timeline = _score_timeline(pbp)
    if timeline.empty:
        return 0.0
    final = float(timeline["margin"].iloc[-1])
    if abs(final) < final_threshold:
        return final
    q4 = timeline[(timeline["period"] == 4) & (timeline["margin"].abs() >= lead_threshold)]
    if q4.empty:
        return final
    return float(q4["margin"].iloc[0])


def gt_margins_table(pbp_by_game: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Garbage-time-filtered margins for many games.

    Returns one row per game: GAME_ID, gt_margin_home. Games whose logs
    fail to parse are skipped with a warning rather than aborting the run.
    """
    rows = []
    for game_id, pbp in pbp_by_game.items():
        try:
            rows.append({"GAME_ID": game_id, "gt_margin_home": garbage_time_margin(pbp)})
        except Exception as e:
            logger.warning("skipping PBP for %s: %s", game_id, e)
    return pd.DataFrame(rows, columns=["GAME_ID", "gt_margin_home"])
