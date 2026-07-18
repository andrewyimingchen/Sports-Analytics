"""Dean Oliver's four factors as a team identity — offense and defense, with
league-rank context.

The four factors (shooting, turnovers, rebounding, free throws) explain most
of what separates good teams from bad ones. We compute the same eFG% / TOV% /
OREB% / FT-rate the prediction model uses, but here rolled up to a team-season
profile from box-score totals (the standard basis, not a mean of per-game
rates) and paired with each team's league rank on every factor.

Pure: a raw team-game DataFrame in, a per-team table out. No I/O.
"""

from __future__ import annotations

import pandas as pd

# box columns needed per team-game; the opponent's are joined on GAME_ID
_BOX = ["PTS", "FGM", "FGA", "FG3M", "FTM", "FTA", "TOV", "OREB", "DREB"]

# factor -> whether a higher value is better (for ranking, 1 = best)
_HIGHER_BETTER = {
    "off_efg": True,
    "off_tov_pct": False,  # turning it over less is better
    "off_oreb_pct": True,
    "off_ft_rate": True,
    "def_efg": False,  # holding opponents to a low eFG% is better
    "def_tov_pct": True,  # forcing more turnovers is better
    "def_dreb_pct": True,
    "def_ft_rate": False,
}

# human labels for display
FACTOR_LABELS = {
    "off_efg": "eFG%",
    "off_tov_pct": "TOV%",
    "off_oreb_pct": "OREB%",
    "off_ft_rate": "FT rate",
    "def_efg": "Opp eFG%",
    "def_tov_pct": "Opp TOV%",
    "def_dreb_pct": "DREB%",
    "def_ft_rate": "Opp FT rate",
}


def four_factors_table(team_games: pd.DataFrame) -> pd.DataFrame:
    """Per-team offense and defense four factors, with league ranks.

    *team_games* is raw team-game rows (one per team per game) carrying the box
    columns in ``_BOX`` plus GAME_ID, TEAM_ID and TEAM_ABBREVIATION. Returns one
    row per team tricode with the eight factor columns in ``_HIGHER_BETTER`` and
    a ``*_rank`` (1 = best in the league) for each. Raises KeyError if a required
    column is missing.

    Factors are computed from season box-score totals: eFG% = (FGM + ½·3PM)/FGA,
    TOV% = TOV/poss (poss = FGA + 0.44·FTA − OREB + TOV), OREB% = OREB/(OREB +
    opp DREB), FT rate = FTM/FGA. Defense mirrors these against the opponent's
    box, with DREB% = DREB/(DREB + opp OREB).
    """
    required = {"GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", *_BOX}
    missing = required - set(team_games.columns)
    if missing:
        raise KeyError(f"team_games missing columns: {sorted(missing)}")

    df = team_games[["GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", *_BOX]].copy()
    opp = df[["GAME_ID", "TEAM_ID", *_BOX]].rename(
        columns={"TEAM_ID": "OPP_TEAM_ID", **{c: f"OPP_{c}" for c in _BOX}}
    )
    df = df.merge(opp, on="GAME_ID")
    df = df[df["OPP_TEAM_ID"] != df["TEAM_ID"]]

    # season totals per team (box-score-total basis, the standard for factors)
    agg = df.groupby("TEAM_ABBREVIATION").sum(numeric_only=True)
    poss = agg["FGA"] + 0.44 * agg["FTA"] - agg["OREB"] + agg["TOV"]
    opp_poss = agg["OPP_FGA"] + 0.44 * agg["OPP_FTA"] - agg["OPP_OREB"] + agg["OPP_TOV"]

    out = pd.DataFrame(index=agg.index)
    out["off_efg"] = (agg["FGM"] + 0.5 * agg["FG3M"]) / agg["FGA"]
    out["off_tov_pct"] = agg["TOV"] / poss
    out["off_oreb_pct"] = agg["OREB"] / (agg["OREB"] + agg["OPP_DREB"])
    out["off_ft_rate"] = agg["FTM"] / agg["FGA"]
    out["def_efg"] = (agg["OPP_FGM"] + 0.5 * agg["OPP_FG3M"]) / agg["OPP_FGA"]
    out["def_tov_pct"] = agg["OPP_TOV"] / opp_poss
    out["def_dreb_pct"] = agg["DREB"] / (agg["DREB"] + agg["OPP_OREB"])
    out["def_ft_rate"] = agg["OPP_FTM"] / agg["OPP_FGA"]

    for factor, higher_better in _HIGHER_BETTER.items():
        out[f"{factor}_rank"] = (
            out[factor].rank(ascending=not higher_better, method="min").astype(int)
        )
    return out.sort_index()
