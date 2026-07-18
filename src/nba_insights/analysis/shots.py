"""Shot-zone efficiency: a player's FG% per zone against the league."""

from __future__ import annotations

import math

import pandas as pd

ZONE_KEY = ["SHOT_ZONE_BASIC", "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE"]

# eFG weight: a made three is worth 1.5 made twos
_THREE_WEIGHT = 1.5

# stats.nba.com SHOT_ZONE_BASIC values collapsed into the five ranges a shot
# diet is usually read in, ordered from the rim out (Backcourt heaves dropped)
_ZONE_BUCKETS: list[tuple[str, list[str]]] = [
    ("At rim", ["Restricted Area"]),
    ("Paint", ["In The Paint (Non-RA)"]),
    ("Mid-range", ["Mid-Range"]),
    ("Corner 3", ["Left Corner 3", "Right Corner 3"]),
    ("Above-break 3", ["Above the Break 3"]),
]
_ZONE_ORDER = [name for name, _ in _ZONE_BUCKETS]


def shot_breakdown(
    shots: pd.DataFrame, league_averages: pd.DataFrame | None = None
) -> pd.DataFrame:
    """A player's shot diet by range: volume, accuracy, and value per zone.

    One row per occupied range bucket (rim → above-break 3), ordered by
    distance: FGA, FGM, FG_PCT, SHARE (of the player's shots), and PPS
    (points per shot, which bakes in the 3-point bonus). With
    *league_averages* (the LeagueAverages frame), LEAGUE_PCT and DIFF add
    how the player's accuracy in each range compares to the league. Raises
    KeyError on missing required columns.
    """
    for col in ["SHOT_ZONE_BASIC", "SHOT_MADE_FLAG", "SHOT_TYPE"]:
        if col not in shots.columns:
            raise KeyError(f"shots table missing column: {col}")
    zone_to_bucket = {z: name for name, zones in _ZONE_BUCKETS for z in zones}

    df = shots.copy()
    df["BUCKET"] = df["SHOT_ZONE_BASIC"].map(zone_to_bucket)
    df = df[df["BUCKET"].notna()]
    is_three = df["SHOT_TYPE"].str.contains("3")
    df["PTS"] = df["SHOT_MADE_FLAG"] * is_three.map({True: 3, False: 2})
    total = len(df)

    rows = []
    for name in _ZONE_ORDER:
        sub = df[df["BUCKET"] == name]
        if sub.empty:
            continue
        fga = len(sub)
        fgm = int(sub["SHOT_MADE_FLAG"].sum())
        rows.append(
            {
                "ZONE": name,
                "FGA": fga,
                "FGM": fgm,
                "FG_PCT": fgm / fga,
                "SHARE": fga / total if total else 0.0,
                "PPS": float(sub["PTS"].sum()) / fga,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out

    if league_averages is not None and {"FGA", "FGM", "SHOT_ZONE_BASIC"} <= set(
        league_averages.columns
    ):
        la = league_averages.copy()
        la["BUCKET"] = la["SHOT_ZONE_BASIC"].map(zone_to_bucket)
        la = la[la["BUCKET"].notna()]
        league_pct = la.groupby("BUCKET").apply(
            lambda d: d["FGM"].sum() / d["FGA"].sum() if d["FGA"].sum() else float("nan"),
            include_groups=False,
        )
        out["LEAGUE_PCT"] = out["ZONE"].map(league_pct)
        out["DIFF"] = out["FG_PCT"] - out["LEAGUE_PCT"]
    return out


def zone_efficiency(shots: pd.DataFrame, league_averages: pd.DataFrame) -> pd.DataFrame:
    """One row per zone the player shot from: volume, FG%, and league diff.

    *shots* is raw shot-chart rows (one per attempt, SHOT_MADE_FLAG 0/1);
    *league_averages* is the LeagueAverages frame from the same endpoint.
    DIFF is player FG% minus league FG% for that zone (NaN when the league
    table lacks the zone). Raises KeyError on missing required columns.
    """
    for col in [*ZONE_KEY, "SHOT_MADE_FLAG"]:
        if col not in shots.columns:
            raise KeyError(f"shots table missing column: {col}")
    zones = shots.groupby(ZONE_KEY, as_index=False).agg(
        FGA=("SHOT_MADE_FLAG", "size"), FGM=("SHOT_MADE_FLAG", "sum")
    )
    zones["PLAYER_PCT"] = zones["FGM"] / zones["FGA"]
    league = league_averages[[*ZONE_KEY, "FG_PCT"]].rename(columns={"FG_PCT": "LEAGUE_PCT"})
    zones = zones.merge(league, on=ZONE_KEY, how="left")
    zones["DIFF"] = zones["PLAYER_PCT"] - zones["LEAGUE_PCT"]
    return zones


def hex_bins(
    shots: pd.DataFrame,
    league_averages: pd.DataFrame,
    size: float = 22.0,
    min_fga: int = 2,
) -> pd.DataFrame:
    """Aggregate shots onto a hexagonal grid, colored-ready vs the league.

    One row per occupied hexagon (pointy-top axial grid, *size* = center-to-
    corner radius in shot-chart units, i.e. tenths of feet): hex center X/Y,
    FGA, FGM, PCT, and DIFF — the hex FG% minus the league's expected FG%
    for the shots that landed there (per-shot zone averages, so a hex
    straddling two zones gets a blended expectation). Hexes with fewer than
    *min_fga* attempts are dropped; DIFF is NaN where the league table lacks
    every zone in the hex. Raises KeyError on missing required columns.
    """
    for col in [*ZONE_KEY, "SHOT_MADE_FLAG", "LOC_X", "LOC_Y"]:
        if col not in shots.columns:
            raise KeyError(f"shots table missing column: {col}")
    league = league_averages[[*ZONE_KEY, "FG_PCT"]].rename(columns={"FG_PCT": "LEAGUE_PCT"})
    merged = shots.merge(league, on=ZONE_KEY, how="left")

    # axial hex coordinates (pointy-top), cube-rounded to the nearest cell
    fq = (math.sqrt(3) / 3 * merged["LOC_X"] - merged["LOC_Y"] / 3) / size
    fr = (2 / 3 * merged["LOC_Y"]) / size
    q, r = fq.round(), fr.round()
    dq, dr = (q - fq).abs(), (r - fr).abs()
    s = -fq - fr
    ds = (s.round() - s).abs()
    fix_q = (dq > dr) & (dq > ds)
    fix_r = ~fix_q & (dr > ds)
    q = q.where(~fix_q, -r - s.round())
    r = r.where(~fix_r, -q - s.round())

    merged["Q"], merged["R"] = q.astype(int), r.astype(int)
    bins = merged.groupby(["Q", "R"], as_index=False).agg(
        FGA=("SHOT_MADE_FLAG", "size"),
        FGM=("SHOT_MADE_FLAG", "sum"),
        LEAGUE_PCT=("LEAGUE_PCT", "mean"),
    )
    bins = bins[bins["FGA"] >= min_fga].copy()
    bins["PCT"] = bins["FGM"] / bins["FGA"]
    bins["DIFF"] = bins["PCT"] - bins["LEAGUE_PCT"]
    bins["X"] = size * math.sqrt(3) * (bins["Q"] + bins["R"] / 2)
    bins["Y"] = size * 1.5 * bins["R"]
    return bins.drop(columns=["Q", "R"])


def shot_quality(shots: pd.DataFrame, league_averages: pd.DataFrame) -> pd.Series:
    """Split a player's eFG% into shot selection and shot making.

    Each attempt's expected value is the league FG% for its zone, weighted
    :data:`_THREE_WEIGHT` for threes — so XEFG is the eFG% a league-average
    shooter would post on this player's shot diet (selection), and MAKING
    (= EFG − XEFG, in eFG points) is finishing above or below what the
    locations alone predict. Shots in zones the league table lacks (e.g.
    backcourt heaves) are dropped from both numbers so they stay
    comparable; FGA counts the shots actually scored. LEAGUE_EFG is the
    league-wide eFG% over the same zone table (NaN if it has no FGA/FGM).
    Raises KeyError on missing required columns.
    """
    for col in [*ZONE_KEY, "SHOT_MADE_FLAG", "SHOT_TYPE"]:
        if col not in shots.columns:
            raise KeyError(f"shots table missing column: {col}")
    league = league_averages[[*ZONE_KEY, "FG_PCT"]].rename(columns={"FG_PCT": "LEAGUE_PCT"})
    matched = shots.merge(league, on=ZONE_KEY, how="inner")

    if matched.empty:
        efg = xefg = float("nan")
    else:
        weight = matched["SHOT_TYPE"].str.contains("3PT").map({True: _THREE_WEIGHT, False: 1.0})
        xefg = float((matched["LEAGUE_PCT"] * weight).mean())
        efg = float((matched["SHOT_MADE_FLAG"] * weight).mean())

    league_efg = float("nan")
    if {"FGA", "FGM"} <= set(league_averages.columns):
        lg_weight = league_averages["SHOT_ZONE_BASIC"].str.contains("3").map(
            {True: _THREE_WEIGHT, False: 1.0}
        )
        lg_fga = league_averages["FGA"].sum()
        if lg_fga:
            league_efg = float((league_averages["FGM"] * lg_weight).sum() / lg_fga)

    return pd.Series(
        {
            "FGA": float(len(matched)),
            "EFG": efg,
            "XEFG": xefg,
            "MAKING": efg - xefg,
            "LEAGUE_EFG": league_efg,
        }
    )
