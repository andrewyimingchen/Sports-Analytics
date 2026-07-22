"""Versioned, explainable roster and projected-minutes inputs for forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from nba_insights.analysis.salaries import normalize_name

ROSTER_INPUT_VERSION = "roster-minutes-v1"
ROSTER_INPUT_METHOD = (
    "Target-season contract team assignments define the roster. Returning-player "
    "minutes start from the latest season and are availability-regressed; players "
    "without NBA history receive a salary-rank role and replacement-level impact. "
    "Player impact is regressed plus-minus per 36 (DPM when available), followed by "
    "a transparent one-year age curve. Team minutes are normalized to 240."
)


@dataclass(frozen=True)
class RosterForecastInputs:
    """Player inputs, team adjustments, and immutable lineage metadata."""

    players: pd.DataFrame
    teams: pd.DataFrame
    metadata: dict


def _age_adjustment(age: pd.Series) -> pd.Series:
    values = pd.to_numeric(age, errors="coerce")
    return pd.Series(
        np.select(
            [values <= 22, values <= 25, values <= 29, values <= 32, values > 32],
            [0.50, 0.25, 0.0, -0.25 * (values - 29), -0.75 - 0.45 * (values - 32)],
            default=0.0,
        ),
        index=age.index,
    ).fillna(0.0)


def _player_impact(league: pd.DataFrame) -> pd.Series:
    minutes = pd.to_numeric(league.get("MIN"), errors="coerce").clip(lower=1)
    games = pd.to_numeric(league.get("GP"), errors="coerce").fillna(0)
    if "DPM" in league:
        raw = pd.to_numeric(league["DPM"], errors="coerce")
    else:
        plus_minus = pd.to_numeric(league.get("PLUS_MINUS"), errors="coerce")
        raw = plus_minus * 36 / minutes
    raw = raw.fillna(-1.5).clip(-8, 8)
    reliability = (games * minutes / 1_800).clip(0, 1)
    return raw * reliability + -1.5 * (1 - reliability)


def _normalize_team_minutes(players: pd.DataFrame) -> pd.DataFrame:
    players = players.copy()
    totals = players.groupby("TEAM")["PROJECTED_MIN"].transform("sum")
    players["PROJECTED_MIN"] = np.where(
        totals > 0,
        players["PROJECTED_MIN"] * 240 / totals,
        players["PROJECTED_MIN"],
    )
    return players


def build_roster_forecast_inputs(
    league: pd.DataFrame,
    contracts: pd.DataFrame,
    *,
    target_season: str,
    generated_on: str | None = None,
) -> RosterForecastInputs:
    """Build target roster/minutes and team strength deltas from cached sources."""
    league_required = {
        "PLAYER_NAME", "TEAM_ABBREVIATION", "MIN", "GP", "AGE", "PLUS_MINUS"
    }
    contract_required = {"PLAYER_NAME", "TEAM_ABBREVIATION", target_season}
    if missing := league_required - set(league):
        raise KeyError(f"league roster input missing columns: {sorted(missing)}")
    if missing := contract_required - set(contracts):
        raise KeyError(f"contract roster input missing columns: {sorted(missing)}")

    current = league.copy()
    current["_KEY"] = current["PLAYER_NAME"].map(normalize_name)
    current = current.sort_values("GP", ascending=False).drop_duplicates("_KEY")
    current["CURRENT_IMPACT"] = _player_impact(current)
    current["CURRENT_MIN_WEIGHT"] = (
        pd.to_numeric(current["MIN"], errors="coerce").fillna(0)
        * pd.to_numeric(current["GP"], errors="coerce").fillna(0)
    )

    target = contracts.copy()
    target["SALARY"] = pd.to_numeric(target[target_season], errors="coerce")
    target = target[
        target["SALARY"].gt(0) & target["TEAM_ABBREVIATION"].notna()
    ].copy()
    target["_KEY"] = target["PLAYER_NAME"].map(normalize_name)
    target = target.sort_values("SALARY", ascending=False).drop_duplicates("_KEY")
    lookup_columns = [
        "_KEY", "PLAYER_NAME", "TEAM_ABBREVIATION", "AGE", "GP", "MIN",
        "CURRENT_IMPACT",
    ]
    target = target.merge(
        current[lookup_columns],
        on="_KEY",
        how="left",
        suffixes=("", "_CURRENT"),
    )
    target = target.rename(
        columns={
            "TEAM_ABBREVIATION": "TEAM",
            "TEAM_ABBREVIATION_CURRENT": "SOURCE_TEAM",
            "PLAYER_NAME_CURRENT": "NBA_PLAYER_NAME",
        }
    )
    target["HAS_HISTORY"] = target["NBA_PLAYER_NAME"].notna()
    availability = np.sqrt(
        pd.to_numeric(target["GP"], errors="coerce").fillna(0).clip(0, 82) / 82
    )
    returning_minutes = (
        pd.to_numeric(target["MIN"], errors="coerce").fillna(0)
        * (0.78 + 0.22 * availability)
    ).clip(6, 38)
    salary_role = (
        10 + 4 * np.log(target["SALARY"].clip(lower=1_000_000) / 1_000_000)
    ).clip(8, 30)
    target["PROJECTED_MIN"] = np.where(
        target["HAS_HISTORY"], returning_minutes, salary_role
    )
    target["AGE_ADJUSTMENT"] = np.where(
        target["HAS_HISTORY"], _age_adjustment(target["AGE"]), 0.0
    )
    target["CURRENT_IMPACT"] = pd.to_numeric(
        target["CURRENT_IMPACT"], errors="coerce"
    ).fillna(-1.5)
    target["PROJECTED_IMPACT"] = (
        target["CURRENT_IMPACT"] + target["AGE_ADJUSTMENT"]
    ).clip(-8, 8)
    target["STATUS"] = np.select(
        [
            ~target["HAS_HISTORY"],
            target["SOURCE_TEAM"].notna() & target["SOURCE_TEAM"].ne(target["TEAM"]),
        ],
        ["new/no NBA history", "changed team"],
        default="returning",
    )
    target = _normalize_team_minutes(target)

    current_team = (
        current[current["TEAM_ABBREVIATION"].notna()]
        .assign(
            weighted=lambda frame: frame["CURRENT_IMPACT"]
            * frame["CURRENT_MIN_WEIGHT"]
        )
        .groupby("TEAM_ABBREVIATION")
        .agg(weighted=("weighted", "sum"), weight=("CURRENT_MIN_WEIGHT", "sum"))
    )
    current_team["CURRENT_IMPACT"] = current_team["weighted"] / current_team[
        "weight"
    ].replace(0, np.nan)

    rows = []
    target_teams = target.set_index("_KEY")["TEAM"].to_dict()
    for team, roster in target.groupby("TEAM", sort=True):
        roster_impact = float(
            (roster["PROJECTED_IMPACT"] * roster["PROJECTED_MIN"]).sum() / 240
        )
        baseline = float(current_team["CURRENT_IMPACT"].get(team, -1.5))
        delta = float(np.clip(roster_impact - baseline, -6, 6))
        returning_share = float(
            roster.loc[roster["SOURCE_TEAM"].eq(team), "PROJECTED_MIN"].sum() / 240
        )
        history_share = float(
            roster.loc[roster["HAS_HISTORY"], "PROJECTED_MIN"].sum() / 240
        )
        additions = roster[~roster["SOURCE_TEAM"].eq(team)].nlargest(
            4, "PROJECTED_MIN"
        )["PLAYER_NAME"].astype(str).tolist()
        lost_mask = current["_KEY"].map(target_teams).ne(team)
        lost = current[current["TEAM_ABBREVIATION"].eq(team) & lost_mask].nlargest(
            4, "CURRENT_MIN_WEIGHT"
        )["PLAYER_NAME"].astype(str).tolist()
        drivers = roster.assign(
            driver=(roster["PROJECTED_IMPACT"] - baseline).abs()
            * roster["PROJECTED_MIN"]
        ).nlargest(4, "driver")["PLAYER_NAME"].astype(str).tolist()
        injury_uncertainty = float(
            (
                (1 - pd.to_numeric(roster["GP"], errors="coerce").fillna(0) / 82)
                .clip(0, 1)
                * roster["PROJECTED_MIN"]
            ).sum()
            / 240
        )
        uncertainty = float(
            np.clip(
                0.16
                + 0.12 * (1 - returning_share)
                + 0.10 * (1 - history_share)
                + 0.07 * injury_uncertainty,
                0.16,
                0.42,
            )
        )
        rows.append(
            {
                "TEAM": str(team),
                "CURRENT_IMPACT": baseline,
                "ROSTER_IMPACT": roster_impact,
                "NET_ADJUSTMENT": delta,
                "STRENGTH_ADJUSTMENT": delta / 14,
                "UNCERTAINTY": uncertainty,
                "ROSTER_COVERAGE": history_share,
                "RETURNING_MIN_SHARE": returning_share,
                "PLAYER_COUNT": int(len(roster)),
                "ADDITIONS": additions,
                "DEPARTURES": lost,
                "KEY_DRIVERS": drivers,
            }
        )
    teams = pd.DataFrame(rows).set_index("TEAM")
    player_columns = [
        "TEAM", "PLAYER_NAME", "SOURCE_TEAM", "STATUS", "HAS_HISTORY", "AGE", "GP", "SALARY",
        "PROJECTED_MIN", "CURRENT_IMPACT", "AGE_ADJUSTMENT", "PROJECTED_IMPACT",
    ]
    players = target[player_columns].sort_values(
        ["TEAM", "PROJECTED_MIN"], ascending=[True, False]
    )
    metadata = {
        "version": ROSTER_INPUT_VERSION,
        "target_season": target_season,
        "generated_on": generated_on or date.today().isoformat(),
        "sources": ["stats.nba.com league player stats", "Basketball-Reference contracts"],
        "method": ROSTER_INPUT_METHOD,
        "limitations": (
            "Contract listings are a roster proxy, not an official depth chart. "
            "Unsigned players, two-way movement, injuries, and unreleased rookie roles "
            "increase the displayed uncertainty; no private injury feed is assumed."
        ),
    }
    return RosterForecastInputs(players=players, teams=teams, metadata=metadata)
