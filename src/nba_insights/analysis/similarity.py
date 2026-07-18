"""Find a player's statistical comparables — "players like X".

Pure: the league per-game table in, a ranked comp table out. A player is
described by a style+production vector (per-36 box rates plus shooting
percentages), standardized across the qualified pool; comps are the
nearest neighbors by Euclidean distance in that standardized space.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# counting stats compared on a per-36 basis (style, minutes-independent) …
_PER36 = ["PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3A", "FTA"]
# … and shooting percentages compared as-is
_PCT = ["FG_PCT", "FG3_PCT", "FT_PCT"]

# exp(-dist/_SCALE) turns standardized distance into a 0-100 match; tuned so
# a strong comp reads in the 70s and a loose one in the 40s-50s (a genuinely
# unique player will still top out lower — that is honest, not a bug)
_SCALE = 6.0


def similar_players(
    league: pd.DataFrame,
    player_name: str,
    n: int = 8,
    min_minutes: float = 20.0,
) -> pd.DataFrame:
    """The *n* players most statistically similar to *player_name*.

    Only players averaging *min_minutes* are compared (bench scrubs make
    noisy neighbors). Returns PLAYER_NAME, TEAM_ABBREVIATION, SIMILARITY
    (0-100), and PTS/REB/AST for context, nearest first. Raises KeyError if
    the player isn't in the qualified pool.
    """
    need = ["PLAYER_NAME", "MIN", *_PER36, *_PCT]
    missing = [c for c in need if c not in league.columns]
    if missing:
        raise KeyError(f"league table missing columns: {missing}")

    pool = league[league["MIN"] >= min_minutes].copy()
    # always include the target even if just under the minutes floor
    if player_name not in set(pool["PLAYER_NAME"]):
        target_row = league[league["PLAYER_NAME"] == player_name]
        if target_row.empty:
            raise KeyError(f"player {player_name!r} not found")
        pool = pd.concat([pool, target_row], ignore_index=True)
    pool = pool.drop_duplicates("PLAYER_NAME").reset_index(drop=True)

    feats = pd.DataFrame(index=pool.index)
    minutes = pool["MIN"].where(pool["MIN"] > 0, np.nan)
    for col in _PER36:
        feats[col] = pool[col] * 36.0 / minutes
    for col in _PCT:
        feats[col] = pool[col]
    feats = feats.fillna(feats.mean())

    # standardize each feature, then Euclidean distance from the target
    std = feats.std(ddof=0).replace(0, 1.0)
    z = (feats - feats.mean()) / std
    target_idx = pool.index[pool["PLAYER_NAME"] == player_name][0]
    dist = np.sqrt(((z - z.loc[target_idx]) ** 2).sum(axis=1))

    out = pool[["PLAYER_NAME", "TEAM_ABBREVIATION", "PTS", "REB", "AST"]].copy()
    out["SIMILARITY"] = (100.0 * np.exp(-dist / _SCALE)).round(1)
    out = out[out["PLAYER_NAME"] != player_name]
    return out.sort_values("SIMILARITY", ascending=False).head(n).reset_index(drop=True)
