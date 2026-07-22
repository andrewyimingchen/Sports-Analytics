"""Ephemeral roster/availability scenarios over immutable forecast inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nba_insights.analysis.roster_forecast import RosterForecastInputs
from nba_insights.analysis.salaries import normalize_name

SCENARIO_VERSION = "roster-scenario-v1"
REPLACEMENT_IMPACT = -1.5


@dataclass(frozen=True)
class RosterScenario:
    players: pd.DataFrame
    teams: pd.DataFrame
    changes: list[dict[str, Any]]
    salary_validation: list[dict[str, Any]]


def _normalize_minutes(players: pd.DataFrame, team: str) -> None:
    mask = players["TEAM"].eq(team)
    roster = players.loc[mask]
    if len(roster) < 5:
        raise ValueError(f"{team} must retain at least five players")
    locked = roster["MINUTES_LOCKED"]
    locked_total = float(roster.loc[locked, "PROJECTED_MIN"].sum())
    if locked_total > 240 + 1e-9:
        raise ValueError(f"{team} explicit minutes exceed the 240-minute team limit")
    remaining = 240 - locked_total
    open_mask = mask & ~players["MINUTES_LOCKED"]
    weights = players.loc[open_mask, "PROJECTED_MIN"].clip(lower=0)
    if remaining > 0 and (weights.empty or float(weights.sum()) <= 0):
        raise ValueError(f"{team} has no unlocked rotation minutes to allocate")
    if not weights.empty:
        players.loc[open_mask, "PROJECTED_MIN"] = weights * remaining / weights.sum()
    total = float(players.loc[mask, "PROJECTED_MIN"].sum())
    if not np.isclose(total, 240):
        raise ValueError(f"{team} rotation minutes total {total:.2f}, expected 240")
    if (players.loc[mask, "PROJECTED_MIN"] > 48).any():
        raise ValueError(f"{team} produces an impossible player average above 48 minutes")


def _salary_screen(
    original: pd.DataFrame, scenario: pd.DataFrame, affected: set[str]
) -> list[dict[str, Any]]:
    before = original.set_index("_KEY")
    after = scenario.set_index("_KEY")
    rows = []
    for team in sorted(affected):
        outgoing_keys = before.index[
            before["TEAM"].eq(team) & ~before.index.isin(after.index[after["TEAM"].eq(team)])
        ]
        incoming_keys = after.index[
            after["TEAM"].eq(team) & ~after.index.isin(before.index[before["TEAM"].eq(team)])
        ]
        outgoing = pd.to_numeric(before.loc[outgoing_keys, "SALARY"], errors="coerce")
        incoming = pd.to_numeric(after.loc[incoming_keys, "SALARY"], errors="coerce")
        missing = bool(outgoing.isna().any() or incoming.isna().any())
        outgoing_total = float(outgoing.sum()) if not outgoing.empty else 0.0
        incoming_total = float(incoming.sum()) if not incoming.empty else 0.0
        limit = outgoing_total * 1.25 + 7_500_000
        if missing:
            status = "unavailable"
            detail = "One or more moved players has no salary in the cached contract source."
        elif incoming_total <= limit and (outgoing_total > 0 or incoming_total == 0):
            status = "pass"
            detail = "Passes the simplified 125% plus $7.5M incoming-salary screen."
        else:
            status = "warning"
            detail = "Exceeds the simplified incoming-salary screen; CBA/apron review required."
        rows.append(
            {
                "team": team,
                "incoming_salary": incoming_total,
                "outgoing_salary": outgoing_total,
                "screen_limit": limit,
                "status": status,
                "detail": detail,
            }
        )
    return rows


def apply_roster_scenario(
    baseline: RosterForecastInputs,
    changes: list[dict[str, Any]],
) -> RosterScenario:
    """Apply validated changes without mutating the cached baseline frames."""
    if not changes:
        raise ValueError("scenario requires at least one player change")
    players = baseline.players.copy(deep=True).reset_index(drop=True)
    teams = baseline.teams.copy(deep=True)
    required = {"PLAYER_NAME", "TEAM", "PROJECTED_MIN", "PROJECTED_IMPACT", "SALARY"}
    if missing := required - set(players.columns):
        raise KeyError(f"roster scenario missing columns: {sorted(missing)}")
    players["_KEY"] = players["PLAYER_NAME"].map(normalize_name)
    players["PROJECTED_MIN"] = pd.to_numeric(
        players["PROJECTED_MIN"], errors="raise"
    ).astype(float)
    if players["_KEY"].duplicated().any():
        raise ValueError("baseline roster contains duplicate players")
    players["GAMES_MISSED"] = 0
    players["MINUTES_LOCKED"] = False
    known_teams = set(teams.index.astype(str))
    seen: set[str] = set()
    affected: set[str] = set()
    applied = []

    for change in changes:
        key = normalize_name(str(change.get("player", "")))
        if not key or key not in set(players["_KEY"]):
            raise ValueError(f"unknown scenario player {change.get('player')!r}")
        if key in seen:
            raise ValueError(f"player {change.get('player')!r} appears more than once")
        seen.add(key)
        index = players.index[players["_KEY"] == key][0]
        before_team = str(players.at[index, "TEAM"])
        after_team: str | None = before_team
        if change.get("remove"):
            after_team = None
        elif change.get("new_team") is not None:
            after_team = str(change["new_team"]).upper()
            if after_team not in known_teams:
                raise ValueError(f"unknown destination team {after_team!r}")
        if after_team == before_team and change.get("remove"):
            raise ValueError("removed player cannot remain on the same team")

        minutes = change.get("projected_minutes")
        if minutes is not None:
            minutes = float(minutes)
            if not 0 <= minutes <= 48:
                raise ValueError("projected minutes must be between 0 and 48")
            players.at[index, "PROJECTED_MIN"] = minutes
            players.at[index, "MINUTES_LOCKED"] = True
        missed = change.get("games_missed")
        if missed is not None:
            missed = int(missed)
            if not 0 <= missed <= 82:
                raise ValueError("games missed must be between 0 and 82")
            players.at[index, "GAMES_MISSED"] = missed

        affected.add(before_team)
        if after_team is not None:
            affected.add(after_team)
            players.at[index, "TEAM"] = after_team
        applied.append(
            {
                "player": str(players.at[index, "PLAYER_NAME"]),
                "from_team": before_team,
                "to_team": after_team,
                "projected_minutes": float(players.at[index, "PROJECTED_MIN"]),
                "games_missed": int(players.at[index, "GAMES_MISSED"]),
                "projected_impact": float(players.at[index, "PROJECTED_IMPACT"]),
            }
        )
        if after_team is None:
            players = players.drop(index=index).reset_index(drop=True)

    original = baseline.players.copy(deep=True)
    original["_KEY"] = original["PLAYER_NAME"].map(normalize_name)
    for team in affected:
        _normalize_minutes(players, team)

    scenario_teams = teams.copy(deep=True)
    for team in affected:
        roster = players[players["TEAM"] == team]
        availability = 1 - roster["GAMES_MISSED"] / 82
        available_minutes = roster["PROJECTED_MIN"] * availability
        replacement_minutes = max(0.0, 240 - float(available_minutes.sum()))
        impact = float(
            (
                (available_minutes * roster["PROJECTED_IMPACT"]).sum()
                + replacement_minutes * REPLACEMENT_IMPACT
            )
            / 240
        )
        current = float(scenario_teams.at[team, "CURRENT_IMPACT"])
        adjustment = float(np.clip(impact - current, -6, 6))
        availability_loss = replacement_minutes / 240
        moved = any(
            row["from_team"] != row["to_team"]
            and team in {row["from_team"], row["to_team"]}
            for row in applied
        )
        baseline_uncertainty = float(scenario_teams.at[team, "UNCERTAINTY"])
        scenario_teams.loc[team, [
            "ROSTER_IMPACT",
            "NET_ADJUSTMENT",
            "STRENGTH_ADJUSTMENT",
            "UNCERTAINTY",
            "PLAYER_COUNT",
        ]] = [
            impact,
            adjustment,
            adjustment / 14,
            float(
                np.clip(
                    baseline_uncertainty + 0.12 * availability_loss + 0.06 * moved,
                    0.08,
                    0.5,
                )
            ),
            int(len(roster)),
        ]
        scenario_teams.at[team, "KEY_DRIVERS"] = [
            row["player"] for row in applied if team in {row["from_team"], row["to_team"]}
        ][:4]

    return RosterScenario(
        players=players.drop(columns=["_KEY"]),
        teams=scenario_teams,
        changes=applied,
        salary_validation=_salary_screen(original, players, affected),
    )
