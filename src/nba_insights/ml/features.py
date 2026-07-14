"""Feature engineering for the ML models. Pure pandas, no I/O.

Inputs are LeagueGameFinder frames (team mode: two rows per game; player
mode: one row per player per game). Every rolling feature is shifted one
game so a row's features describe form *entering* that game — the models
never see the game they are predicting.
"""

from __future__ import annotations

import pandas as pd

REST_CAP = 10  # days; longer breaks (injury, all-star) aren't "more rested"

OUTCOME_FEATURES = ["form_win_pct_diff", "form_net_diff", "form_pts_diff", "rest_diff"]
POINTS_FEATURES = ["pts_r5", "pts_r10", "min_r5", "fga_r5", "home", "rest_days", "opp_form_net"]


def _prepare(games: pd.DataFrame) -> pd.DataFrame:
    df = games.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    df["home"] = df["MATCHUP"].str.contains("vs.", regex=False).astype(int)
    df["win"] = (df["WL"] == "W").astype(int)
    return df


def _rest_days(dates: pd.Series) -> pd.Series:
    rest = dates.diff().dt.days
    return rest.clip(upper=REST_CAP).fillna(REST_CAP)


def team_form_features(team_games: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Per team-game rolling form, shifted so each row is pre-game knowledge.

    Returns one row per team per game with: home, rest_days, form_win_pct,
    form_pts, form_net (rolling avg point differential), win (the label).
    Early games without a full window are NaN and dropped by callers.
    """
    df = _prepare(team_games).sort_values(["TEAM_ID", "GAME_DATE"]).reset_index(drop=True)
    grouped = df.groupby("TEAM_ID", sort=False)

    df["rest_days"] = grouped["GAME_DATE"].transform(_rest_days)
    for col, source in [("form_win_pct", "win"), ("form_pts", "PTS"), ("form_net", "PLUS_MINUS")]:
        rolled = grouped[source].transform(lambda s: s.shift(1).rolling(window).mean())
        df[col] = rolled

    keep = [
        "GAME_ID",
        "GAME_DATE",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "home",
        "rest_days",
        "form_win_pct",
        "form_pts",
        "form_net",
        "win",
    ]
    return df[keep]


def game_matchup_frame(team_form: pd.DataFrame) -> pd.DataFrame:
    """One row per game: home-minus-away form differentials + home_win label.

    Games where either side lacks a full form window are dropped.
    """
    home = team_form[team_form["home"] == 1]
    away = team_form[team_form["home"] == 0]
    merged = home.merge(away, on="GAME_ID", suffixes=("_h", "_a"))

    out = pd.DataFrame(
        {
            "GAME_ID": merged["GAME_ID"],
            "GAME_DATE": merged["GAME_DATE_h"],
            "home_team": merged["TEAM_ABBREVIATION_h"],
            "away_team": merged["TEAM_ABBREVIATION_a"],
            "form_win_pct_diff": merged["form_win_pct_h"] - merged["form_win_pct_a"],
            "form_net_diff": merged["form_net_h"] - merged["form_net_a"],
            "form_pts_diff": merged["form_pts_h"] - merged["form_pts_a"],
            "rest_diff": merged["rest_days_h"] - merged["rest_days_a"],
            "home_win": merged["win_h"],
        }
    )
    return out.dropna().reset_index(drop=True)


def team_form_snapshot(team_games: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Current form per team (over each team's most recent *window* games).

    Unlike :func:`team_form_features` this is not shifted — it summarises
    everything played so far, i.e. form entering each team's *next* game.
    Returns one row per team indexed by TEAM_ABBREVIATION.
    """
    df = _prepare(team_games).sort_values(["TEAM_ID", "GAME_DATE"])
    tail = df.groupby("TEAM_ABBREVIATION", sort=False).tail(window)
    snap = tail.groupby("TEAM_ABBREVIATION").agg(
        form_win_pct=("win", "mean"),
        form_pts=("PTS", "mean"),
        form_net=("PLUS_MINUS", "mean"),
    )
    return snap


def matchup_features(
    snapshot: pd.DataFrame, home_team: str, away_team: str, rest_diff: float = 0.0
) -> pd.DataFrame:
    """Single-row outcome-model input for a hypothetical matchup today."""
    h, a = snapshot.loc[home_team], snapshot.loc[away_team]
    return pd.DataFrame(
        [
            {
                "form_win_pct_diff": h["form_win_pct"] - a["form_win_pct"],
                "form_net_diff": h["form_net"] - a["form_net"],
                "form_pts_diff": h["form_pts"] - a["form_pts"],
                "rest_diff": rest_diff,
            }
        ]
    )


def player_game_features(
    player_games: pd.DataFrame, team_form: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Per player-game features (pre-game knowledge only) with PTS target.

    *team_form* (from :func:`team_form_features`) supplies the opponent's
    rolling net rating; without it the opponent feature is 0 (league
    average), which keeps the function usable on a lone player log.
    """
    df = _prepare(player_games)
    df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce").fillna(0)
    df = df.sort_values(["PLAYER_ID", "GAME_DATE"]).reset_index(drop=True)
    grouped = df.groupby("PLAYER_ID", sort=False)

    df["rest_days"] = grouped["GAME_DATE"].transform(_rest_days)
    for col, source, window in [
        ("pts_r5", "PTS", 5),
        ("pts_r10", "PTS", 10),
        ("min_r5", "MIN", 5),
        ("fga_r5", "FGA", 5),
    ]:
        df[col] = grouped[source].transform(lambda s, w=window: s.shift(1).rolling(w).mean())

    df["opp_form_net"] = 0.0
    if team_form is not None:
        # the opponent's row for this game is the other team's row
        opp = team_form[["GAME_ID", "TEAM_ID", "form_net"]].rename(
            columns={"TEAM_ID": "OPP_TEAM_ID", "form_net": "opp_form_net_joined"}
        )
        df = df.merge(opp, on="GAME_ID", how="left")
        df = df[df["OPP_TEAM_ID"] != df["TEAM_ID"]]
        df["opp_form_net"] = df["opp_form_net_joined"].fillna(0.0)
        df = df.drop(columns=["OPP_TEAM_ID", "opp_form_net_joined"])

    keep = [
        "PLAYER_ID",
        "PLAYER_NAME",
        "GAME_ID",
        "GAME_DATE",
        *POINTS_FEATURES,
        "PTS",
    ]
    return df[keep].dropna().reset_index(drop=True)


def player_next_game_features(
    player_rows: pd.DataFrame, home: bool, opp_form_net: float, rest_days: float = 2.0
) -> pd.DataFrame:
    """Single-row points-model input for a player's *next* game.

    *player_rows* is that player's slice of a player-games frame; rolling
    stats use their most recent games (unshifted — the next game hasn't
    happened yet).
    """
    df = player_rows.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce").fillna(0)
    df = df.sort_values("GAME_DATE")
    return pd.DataFrame(
        [
            {
                "pts_r5": df["PTS"].tail(5).mean(),
                "pts_r10": df["PTS"].tail(10).mean(),
                "min_r5": df["MIN"].tail(5).mean(),
                "fga_r5": df["FGA"].tail(5).mean(),
                "home": int(home),
                "rest_days": rest_days,
                "opp_form_net": opp_form_net,
            }
        ]
    )
