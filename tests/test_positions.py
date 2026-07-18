"""Offline tests for position inference and positional percentiles."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import infer_positions, positional_percentile_ranks

_COLS = ["REB", "BLK", "AST", "FG3A", "FG_PCT", "PTS"]


def _p(name, min_, **stats):
    row = {"PLAYER_NAME": name, "MIN": min_, "GP": 60}
    row.update({c: stats.get(c, 0.0) for c in _COLS})
    return row


def _league() -> pd.DataFrame:
    # three clear guards, three clear bigs, three in-between wings
    rows = []
    for i in range(3):
        rows.append(_p(f"Guard{i}", 32, AST=8 + i, FG3A=8, REB=3, BLK=0.2,
                       FG_PCT=0.44, PTS=22))
        rows.append(_p(f"Big{i}", 30, REB=12 + i, BLK=2.2, AST=1.5, FG3A=0.3,
                       FG_PCT=0.62, PTS=16))
        rows.append(_p(f"Wing{i}", 31, REB=6, BLK=0.6, AST=4, FG3A=6,
                       FG_PCT=0.47, PTS=20))
    return pd.DataFrame(rows)


def test_infer_positions_separates_guards_and_bigs():
    pos = infer_positions(_league(), min_minutes=15)
    labelled = _league().assign(POS=pos.values).set_index("PLAYER_NAME")["POS"]
    assert labelled["Guard0"] == "Guard"
    assert labelled["Big0"] == "Big"
    assert labelled["Wing0"] == "Wing"
    assert set(pos.unique()) <= {"Guard", "Wing", "Big"}


def test_positional_percentiles_rank_within_group():
    league = _league()
    ranks, group = positional_percentile_ranks(
        league, "Big0", stats=["REB", "AST"], min_games=1
    )
    assert group == "Big"
    # Big0 has the fewest rebounds among the three bigs -> low REB pct in-group
    assert ranks["REB"] <= 40
    # but strong assists for a big
    assert ranks["AST"] >= 60


def test_missing_columns_and_player_raise():
    with pytest.raises(KeyError, match="FG_PCT"):
        infer_positions(_league().drop(columns=["FG_PCT"]))
    with pytest.raises(KeyError, match="Nobody"):
        positional_percentile_ranks(_league(), "Nobody", min_games=1)
