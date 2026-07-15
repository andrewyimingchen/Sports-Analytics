"""Feature engineering for the ML models. Pure pandas, no I/O.

Inputs are LeagueGameFinder frames (team mode: two rows per game; player
mode: one row per player per game). Every rolling feature is shifted one
game so a row's features describe form *entering* that game — the models
never see the game they are predicting.

Beyond raw scoring form, each team-game row carries Dean Oliver's four
factors (eFG%, TOV%, OREB%, FT rate), possession estimates (pace) and
per-100 ratings (ORtg/DRtg), all derived from the box columns of the same
frame plus the opponent's row joined on GAME_ID — no extra endpoints.
"""

from __future__ import annotations

import pandas as pd

REST_CAP = 10  # days; longer breaks (injury, all-star) aren't "more rested"

# neutral fill values when opponent context is unavailable
_LEAGUE_AVG_DRTG = 112.0
_LEAGUE_AVG_PACE = 99.0

# rolling form columns produced by team_form_features / team_form_snapshot
TEAM_FORM_COLS = [
    "form_win_pct",
    "form_pts",
    "form_net",
    "form_efg",
    "form_tov_pct",
    "form_oreb_pct",
    "form_ft_rate",
    "form_pace",
    "form_ortg",
    "form_drtg",
]

OUTCOME_FEATURES = [f"{c}_diff" for c in TEAM_FORM_COLS] + [
    "rest_diff",
    "b2b_diff",
    "three_in_four_diff",
    "missing_min_diff",
]

POINTS_FEATURES = [
    "pts_r5",
    "pts_r10",
    "min_r5",
    "fga_r5",
    "home",
    "rest_days",
    "opp_form_net",
    "opp_form_drtg",
    "opp_form_pace",
]

_BOX_COLS = ["PTS", "FGM", "FGA", "FG3M", "FTM", "FTA", "TOV", "OREB", "DREB"]

_FORM_SOURCES = {
    "form_win_pct": "win",
    "form_pts": "PTS",
    "form_net": "PLUS_MINUS",
    "form_efg": "efg",
    "form_tov_pct": "tov_pct",
    "form_oreb_pct": "oreb_pct",
    "form_ft_rate": "ft_rate",
    "form_pace": "pace",
    "form_ortg": "ortg",
    "form_drtg": "drtg",
}


def _prepare(games: pd.DataFrame) -> pd.DataFrame:
    df = games.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    df["home"] = df["MATCHUP"].str.contains("vs.", regex=False).astype(int)
    df["win"] = (df["WL"] == "W").astype(int)
    return df


def _rest_days(dates: pd.Series) -> pd.Series:
    rest = dates.diff().dt.days
    return rest.clip(upper=REST_CAP).fillna(REST_CAP)


def _with_derived_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-game four factors, possessions, pace, and ratings.

    Requires the opponent's box columns, joined on GAME_ID.
    """
    opp = df[["GAME_ID", "TEAM_ID", *_BOX_COLS]].rename(
        columns={"TEAM_ID": "OPP_TEAM_ID", **{c: f"OPP_{c}" for c in _BOX_COLS}}
    )
    df = df.merge(opp, on="GAME_ID")
    df = df[df["OPP_TEAM_ID"] != df["TEAM_ID"]].copy()

    poss = df["FGA"] + 0.44 * df["FTA"] - df["OREB"] + df["TOV"]
    opp_poss = df["OPP_FGA"] + 0.44 * df["OPP_FTA"] - df["OPP_OREB"] + df["OPP_TOV"]

    df["efg"] = (df["FGM"] + 0.5 * df["FG3M"]) / df["FGA"]
    df["tov_pct"] = df["TOV"] / poss
    df["oreb_pct"] = df["OREB"] / (df["OREB"] + df["OPP_DREB"])
    df["ft_rate"] = df["FTM"] / df["FGA"]
    df["pace"] = (poss + opp_poss) / 2
    df["ortg"] = 100 * df["PTS"] / poss
    df["drtg"] = 100 * df["OPP_PTS"] / opp_poss
    return df


def prior_minute_rates(prior_player_games: pd.DataFrame) -> pd.Series:
    """Per player: previous-season minutes per team game (82-game basis).

    Used to seed availability expectations at the start of a season, when a
    player has no current-season history yet. Indexed by PLAYER_ID.
    """
    pg = prior_player_games.copy()
    pg["MIN"] = pd.to_numeric(pg["MIN"], errors="coerce").fillna(0)
    return pg.groupby("PLAYER_ID")["MIN"].sum() / 82


def availability_features(
    team_games: pd.DataFrame,
    player_games: pd.DataFrame,
    prior_rates: pd.Series | None = None,
    prior_weight: float = 20.0,
) -> pd.DataFrame:
    """Expected minutes missing per team-game, derived from absences.

    A player with no player-game row for one of their team's games didn't
    play (injury, rest, DNP — indistinguishable, and mostly irrelevant for
    prediction). Each absentee is weighted by the minutes they were expected
    to play: current-season cumulative minutes per team game (shifted —
    pre-game knowledge only), blended with *prior_rates* (last season's
    minutes per game) counting as *prior_weight* pseudo-games, so a star
    missing the season opener still registers. Returns one row per
    (GAME_ID, TEAM_ID) with missing_min.
    """
    tg = _prepare(team_games)[["GAME_ID", "TEAM_ID", "GAME_DATE"]]
    pg = player_games[["GAME_ID", "TEAM_ID", "PLAYER_ID", "MIN"]].copy()
    pg["MIN"] = pd.to_numeric(pg["MIN"], errors="coerce").fillna(0)

    out = []
    for team_id, games in tg.groupby("TEAM_ID"):
        games = games.sort_values("GAME_DATE")
        # games × players minutes matrix; NaN = did not play
        matrix = (
            pg[pg["TEAM_ID"] == team_id]
            .pivot_table(index="GAME_ID", columns="PLAYER_ID", values="MIN")
            .reindex(games["GAME_ID"])
        )
        seed = pd.Series(0.0, index=matrix.columns)
        if prior_rates is not None:
            seed = prior_rates.reindex(matrix.columns).fillna(0.0)
        n_prior = pd.Series(range(len(matrix)), index=matrix.index, dtype=float)
        cum = matrix.fillna(0).cumsum().shift(1).fillna(0.0)
        expected = (cum + seed * prior_weight).div(n_prior + prior_weight, axis=0)
        missing = expected.where(matrix.isna()).sum(axis=1)
        out.append(
            pd.DataFrame(
                {"GAME_ID": matrix.index, "TEAM_ID": team_id, "missing_min": missing.values}
            )
        )
    return pd.concat(out, ignore_index=True)


def team_form_features(
    team_games: pd.DataFrame,
    window: int | None = 10,
    player_games: pd.DataFrame | None = None,
    prior_rates: pd.Series | None = None,
) -> pd.DataFrame:
    """Per team-game rolling form, shifted so each row is pre-game knowledge.

    One row per team per game: fatigue flags (rest_days, b2b, three_in_four
    — known pre-game, unshifted), rolling form over the previous *window*
    games (or season-to-date when ``window=None``, minimum 10 games) for
    every column in TEAM_FORM_COLS, and win (the label). Early games
    without enough history are NaN and dropped by callers.

    With *player_games*, each row also carries missing_min — the expected
    minutes absent from that game's roster (see availability_features);
    without it the column is 0.
    """
    df = _with_derived_stats(_prepare(team_games))
    if player_games is not None:
        df = df.merge(
            availability_features(team_games, player_games, prior_rates=prior_rates),
            on=["GAME_ID", "TEAM_ID"],
        )
    else:
        df["missing_min"] = 0.0
    df = df.sort_values(["TEAM_ID", "GAME_DATE"]).reset_index(drop=True)
    grouped = df.groupby("TEAM_ID", sort=False)

    df["rest_days"] = grouped["GAME_DATE"].transform(_rest_days)
    # pre-game fatigue flags: back-to-back, and third game in four days
    gap1 = grouped["GAME_DATE"].transform(lambda s: (s - s.shift(1)).dt.days)
    gap2 = grouped["GAME_DATE"].transform(lambda s: (s - s.shift(2)).dt.days)
    df["b2b"] = (gap1 == 1).astype(int)
    df["three_in_four"] = ((gap2 <= 3) & gap2.notna()).astype(int)

    for col, source in _FORM_SOURCES.items():
        if window is None:
            df[col] = grouped[source].transform(
                lambda s: s.shift(1).expanding(min_periods=10).mean()
            )
        else:
            df[col] = grouped[source].transform(lambda s, w=window: s.shift(1).rolling(w).mean())

    keep = [
        "GAME_ID",
        "GAME_DATE",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "home",
        "rest_days",
        "b2b",
        "three_in_four",
        "missing_min",
        *TEAM_FORM_COLS,
        "win",
    ]
    return df[keep]


def game_matchup_frame(team_form: pd.DataFrame) -> pd.DataFrame:
    """One row per game: home-minus-away differentials + home_win label.

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
            "rest_diff": merged["rest_days_h"] - merged["rest_days_a"],
            "b2b_diff": merged["b2b_h"] - merged["b2b_a"],
            "three_in_four_diff": merged["three_in_four_h"] - merged["three_in_four_a"],
            "missing_min_diff": merged["missing_min_h"] - merged["missing_min_a"],
            "home_win": merged["win_h"],
        }
    )
    for col in TEAM_FORM_COLS:
        out[f"{col}_diff"] = merged[f"{col}_h"] - merged[f"{col}_a"]
    return out.dropna().reset_index(drop=True)


def team_form_snapshot(team_games: pd.DataFrame, window: int | None = None) -> pd.DataFrame:
    """Current form per team (season-to-date, or the most recent *window* games).

    Unlike :func:`team_form_features` this is not shifted — it summarises
    everything played so far, i.e. form entering each team's *next* game.
    The default (``window=None``, season-to-date) matches how the shipped
    outcome model is trained. One row per team, indexed by
    TEAM_ABBREVIATION, columns TEAM_FORM_COLS plus last_game_date.
    """
    df = _with_derived_stats(_prepare(team_games))
    df = df.sort_values(["TEAM_ID", "GAME_DATE"])
    tail = df.groupby("TEAM_ABBREVIATION", sort=False)
    scoped = tail.tail(window) if window is not None else df
    snap = scoped.groupby("TEAM_ABBREVIATION").agg(
        **{form: (source, "mean") for form, source in _FORM_SOURCES.items()},
        last_game_date=("GAME_DATE", "max"),
    )
    return snap


def matchup_features(
    snapshot: pd.DataFrame,
    home_team: str,
    away_team: str,
    rest_diff: float = 0.0,
    b2b_diff: float = 0.0,
    three_in_four_diff: float = 0.0,
    home_missing_min: float = 0.0,
    away_missing_min: float = 0.0,
) -> pd.DataFrame:
    """Single-row outcome-model input for a matchup between two teams."""
    h, a = snapshot.loc[home_team], snapshot.loc[away_team]
    row = {f"{col}_diff": h[col] - a[col] for col in TEAM_FORM_COLS}
    row.update(
        rest_diff=rest_diff,
        b2b_diff=b2b_diff,
        three_in_four_diff=three_in_four_diff,
        missing_min_diff=home_missing_min - away_missing_min,
    )
    return pd.DataFrame([row])


def upcoming_games(schedule: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """The next slate of unplayed games: one row per game, tricodes + tipoff.

    Uses gameStatus 1 (scheduled). Returns the earliest upcoming date's
    games only; empty frame in the offseason.
    """
    df = schedule.copy()
    df["tipoff"] = pd.to_datetime(df["gameDateTimeEst"], format="ISO8601", utc=True)
    today = today or pd.Timestamp.now(tz="UTC")
    pending = df[(df["gameStatus"] == 1) & (df["tipoff"] >= today)].sort_values("tipoff")
    if pending.empty:
        return pd.DataFrame(columns=["home", "away", "tipoff"])
    next_date = pending["tipoff"].dt.date.iloc[0]
    slate = pending[pending["tipoff"].dt.date == next_date]
    return pd.DataFrame(
        {
            "home": slate["homeTeam_teamTricode"].to_numpy(),
            "away": slate["awayTeam_teamTricode"].to_numpy(),
            "tipoff": slate["tipoff"].to_numpy(),
        }
    )


def player_game_features(
    player_games: pd.DataFrame, team_form: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Per player-game features (pre-game knowledge only) with PTS target.

    *team_form* (from :func:`team_form_features`) supplies the opponent's
    rolling net rating, defensive rating, and pace; without it those
    features sit at league-neutral values, which keeps the function usable
    on a lone player log.
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
    df["opp_form_drtg"] = _LEAGUE_AVG_DRTG
    df["opp_form_pace"] = _LEAGUE_AVG_PACE
    if team_form is not None:
        opp = team_form[["GAME_ID", "TEAM_ID", "form_net", "form_drtg", "form_pace"]].rename(
            columns={
                "TEAM_ID": "OPP_TEAM_ID",
                "form_net": "j_net",
                "form_drtg": "j_drtg",
                "form_pace": "j_pace",
            }
        )
        df = df.merge(opp, on="GAME_ID", how="left")
        df = df[df["OPP_TEAM_ID"] != df["TEAM_ID"]]
        df["opp_form_net"] = df["j_net"].fillna(0.0)
        df["opp_form_drtg"] = df["j_drtg"].fillna(_LEAGUE_AVG_DRTG)
        df["opp_form_pace"] = df["j_pace"].fillna(_LEAGUE_AVG_PACE)
        df = df.drop(columns=["OPP_TEAM_ID", "j_net", "j_drtg", "j_pace"])

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
    player_rows: pd.DataFrame,
    home: bool,
    opp_form_net: float,
    rest_days: float = 2.0,
    opp_form_drtg: float = _LEAGUE_AVG_DRTG,
    opp_form_pace: float = _LEAGUE_AVG_PACE,
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
                "opp_form_drtg": opp_form_drtg,
                "opp_form_pace": opp_form_pace,
            }
        ]
    )
