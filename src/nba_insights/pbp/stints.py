"""Stint-level lineup ratings from rotation intervals and play-by-play.

Pure pandas, no I/O. Rotation rows give exact on-court intervals per
player (IN/OUT_TIME_REAL in tenths of game seconds, IS_HOME flag); the
play-by-play supplies the score timeline and possession events. Slicing
the game at every substitution boundary yields stints — spans where all
ten players are fixed — and each lineup's plus-minus and estimated
possessions aggregate into a net rating comparable to the league lineup
dashboard.

Garbage time is stripped with the same rule as
:func:`nba_insights.pbp.parse.garbage_time_margin`: benches protecting a
20-point fourth-quarter lead say nothing about a lineup's quality.
"""

from __future__ import annotations

import re

import pandas as pd

REG_PERIOD_TENTHS = 7200  # 12 minutes
OT_PERIOD_TENTHS = 3000  # 5 minutes

_CLOCK_RE = re.compile(r"PT(\d+)M([\d.]+)S")


def clock_to_tenths(period: int, clock: str) -> float:
    """Elapsed game time in tenths of seconds for a period + countdown clock.

    Matches the rotation endpoint's IN/OUT_TIME_REAL scale (Q1 12:00 → 0,
    end of regulation → 28800; overtimes add 3000 each).
    """
    m = _CLOCK_RE.fullmatch(clock)
    if not m:
        raise ValueError(f"unparseable clock: {clock!r}")
    remaining = (int(m.group(1)) * 60 + float(m.group(2))) * 10
    length = REG_PERIOD_TENTHS if period <= 4 else OT_PERIOD_TENTHS
    start = min(period - 1, 4) * REG_PERIOD_TENTHS + max(period - 5, 0) * OT_PERIOD_TENTHS
    return start + (length - remaining)


def _timed_events(pbp: pd.DataFrame) -> pd.DataFrame:
    """Play-by-play in game order with an elapsed-tenths column T."""
    df = pbp.sort_values("actionNumber").copy()
    df["T"] = [clock_to_tenths(p, c) for p, c in zip(df["period"], df["clock"], strict=True)]
    return df


def _margin_timeline(events: pd.DataFrame) -> pd.DataFrame:
    """Rows where the score is known: T, period, margin (home minus away)."""
    df = events[["T", "period"]].copy()
    df["margin"] = pd.to_numeric(events["scoreHome"], errors="coerce") - pd.to_numeric(
        events["scoreAway"], errors="coerce"
    )
    return df.dropna(subset=["margin"])


def _margin_at(timeline: pd.DataFrame, t: float) -> float:
    """Score margin as of game time *t* (last known value at or before it)."""
    known = timeline[timeline["T"] <= t]
    return float(known["margin"].iloc[-1]) if len(known) else 0.0


def garbage_time_onset(
    pbp: pd.DataFrame, lead_threshold: int = 20, final_threshold: int = 15
) -> float | None:
    """Game time (tenths) where garbage time begins, or None.

    Same rule as :func:`nba_insights.pbp.parse.garbage_time_margin`: a
    fourth-quarter lead reaching *lead_threshold* in a game that ends as a
    *final_threshold*-plus blowout marks everything after as garbage time.
    Accepts raw play-by-play or an already-timed frame.
    """
    events = pbp if "T" in pbp.columns else _timed_events(pbp)
    timeline = _margin_timeline(events)
    if timeline.empty or abs(float(timeline["margin"].iloc[-1])) < final_threshold:
        return None
    q4 = timeline[(timeline["period"] == 4) & (timeline["margin"].abs() >= lead_threshold)]
    return float(q4["T"].iloc[0]) if len(q4) else None


def _possession_counts(events: pd.DataFrame) -> pd.DataFrame:
    """Per-event possession weights: T, teamId, POSS_W.

    Standard estimate per team: FGA − OREB + TOV + 0.44·FTA. An offensive
    rebound is a Rebound row credited to the team of the most recent
    missed shot (rebounds off missed free throws are not reclaimed — a
    small, documented undercount).
    """
    df = events[["T", "teamId", "actionType"]].copy()
    miss_team = df["teamId"].where(df["actionType"] == "Missed Shot").ffill()
    weights = pd.Series(0.0, index=df.index)
    weights[df["actionType"].isin(["Made Shot", "Missed Shot"])] = 1.0
    weights[df["actionType"] == "Turnover"] = 1.0
    weights[df["actionType"] == "Free Throw"] = 0.44
    oreb = (df["actionType"] == "Rebound") & (df["teamId"] == miss_team)
    weights[oreb] = -1.0
    df["POSS_W"] = weights
    return df[df["POSS_W"] != 0]


def stint_table(
    rotation: pd.DataFrame,
    pbp: pd.DataFrame,
    lead_threshold: int = 20,
    final_threshold: int = 15,
) -> pd.DataFrame:
    """One row per stint: fixed ten-player spans with margin and possessions.

    Columns: START, END, MIN, HOME_LINEUP, AWAY_LINEUP (sorted id tuples),
    MARGIN (home minus away over the span), POSS (average of the two
    teams' estimated possessions). Garbage time is cut: stints beyond the
    onset are dropped, the one spanning it is truncated. Intervals where
    either side doesn't resolve to exactly five players (rare upstream
    glitches) are skipped. Raises KeyError on missing columns.
    """
    for col in ("TEAM_ID", "PERSON_ID", "IN_TIME_REAL", "OUT_TIME_REAL", "IS_HOME"):
        if col not in rotation.columns:
            raise KeyError(f"rotation table missing column: {col}")
    events = _timed_events(pbp)
    timeline = _margin_timeline(events)
    poss = _possession_counts(events)
    onset = garbage_time_onset(events, lead_threshold, final_threshold)

    bounds = sorted(set(rotation["IN_TIME_REAL"]) | set(rotation["OUT_TIME_REAL"]))
    rows = []
    for start, end in zip(bounds, bounds[1:], strict=False):
        if onset is not None:
            if start >= onset:
                break
            end = min(end, onset)
        if end <= start:
            continue
        on = rotation[(rotation["IN_TIME_REAL"] <= start) & (rotation["OUT_TIME_REAL"] >= end)]
        home = tuple(sorted(on.loc[on["IS_HOME"], "PERSON_ID"].astype(int)))
        away = tuple(sorted(on.loc[~on["IS_HOME"], "PERSON_ID"].astype(int)))
        if len(home) != 5 or len(away) != 5:
            continue
        window = poss[(poss["T"] > start) & (poss["T"] <= end)]
        rows.append(
            {
                "START": start,
                "END": end,
                "MIN": (end - start) / 600,
                "HOME_LINEUP": home,
                "AWAY_LINEUP": away,
                "MARGIN": _margin_at(timeline, end) - _margin_at(timeline, start),
                # per-team average; sum/2 also counts a team with no events
                # in a short window as zero possessions
                "POSS": float(window["POSS_W"].sum()) / 2,
            }
        )
    return pd.DataFrame(
        rows, columns=["START", "END", "MIN", "HOME_LINEUP", "AWAY_LINEUP", "MARGIN", "POSS"]
    )


def lineup_ratings(stints: pd.DataFrame, min_minutes: float = 0.0) -> pd.DataFrame:
    """Aggregate stints into one row per five-man lineup.

    Home and away sides contribute symmetrically (away plus-minus is the
    negated margin). GROUP_ID matches the league lineup dashboard format
    ("-id1-id2-...-", ids ascending) so existing lookups work unchanged.
    NET_RATING is aggregate plus-minus per 100 estimated possessions.
    """
    sides = []
    for lineup_col, sign in (("HOME_LINEUP", 1.0), ("AWAY_LINEUP", -1.0)):
        side = stints[[lineup_col, "MIN", "MARGIN", "POSS"]].rename(
            columns={lineup_col: "LINEUP"}
        )
        side["PLUS_MINUS"] = side.pop("MARGIN") * sign
        sides.append(side)
    both = pd.concat(sides, ignore_index=True)
    agg = both.groupby("LINEUP").agg(
        MIN=("MIN", "sum"),
        PLUS_MINUS=("PLUS_MINUS", "sum"),
        POSS=("POSS", "sum"),
        STINTS=("MIN", "size"),
    )
    agg["NET_RATING"] = agg["PLUS_MINUS"] / agg["POSS"].clip(lower=1.0) * 100
    agg = agg[agg["MIN"] >= min_minutes].reset_index()
    agg["GROUP_ID"] = agg["LINEUP"].map(lambda ids: "-" + "-".join(map(str, ids)) + "-")
    return agg.sort_values("MIN", ascending=False, ignore_index=True)
