"""Salary context: join scraped contract rows onto league tables."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

_SEASON_RE = re.compile(r"\d{4}-\d{2}")


def normalize_name(name: str) -> str:
    """Fold a player name for cross-source matching.

    Strips accents (Jokić → jokic), case, punctuation, and generational
    suffixes — Basketball-Reference and stats.nba.com disagree on all of
    them for a handful of players.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    folded = re.sub(r"[.'’-]", "", folded.lower())
    return re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", folded.strip())


def salary_seasons(contracts: pd.DataFrame) -> list[str]:
    """The season salary columns present, in page order (nearest first)."""
    return [c for c in contracts.columns if _SEASON_RE.fullmatch(str(c))]


def attach_salary(league: pd.DataFrame, contracts: pd.DataFrame) -> pd.DataFrame:
    """League table plus SALARY (nearest season) and GUARANTEED columns.

    Joins on normalized player name — the contracts source has no NBA
    player IDs. Players without a listed contract get NaN, never dropped.
    Raises KeyError when either table lacks its name column.
    """
    for df, label in ((league, "league"), (contracts, "contracts")):
        if "PLAYER_NAME" not in df.columns:
            raise KeyError(f"{label} table has no PLAYER_NAME column")
    seasons = salary_seasons(contracts)
    if not seasons:
        return league
    cols = {"SALARY": contracts[seasons[0]]}
    if "GUARANTEED" in contracts.columns:
        cols["GUARANTEED"] = contracts["GUARANTEED"]
    right = pd.DataFrame(cols)
    right["_KEY"] = contracts["PLAYER_NAME"].map(normalize_name)
    # a traded player can appear once per team on the page; keep the first row
    right = right.drop_duplicates("_KEY")
    out = league.merge(
        right, how="left", left_on=league["PLAYER_NAME"].map(normalize_name), right_on="_KEY"
    )
    return out.drop(columns=["key_0", "_KEY"], errors="ignore")


def player_contract(contracts: pd.DataFrame, name: str) -> pd.Series:
    """One player's contract row: per-season salaries plus GUARANTEED.

    Looks up by normalized name (the contracts source has no NBA IDs); a
    traded player appearing under two teams keeps the first row. Raises
    KeyError when the player has no listed contract.
    """
    if "PLAYER_NAME" not in contracts.columns:
        raise KeyError("contracts table has no PLAYER_NAME column")
    key = normalize_name(name)
    rows = contracts[contracts["PLAYER_NAME"].map(normalize_name) == key]
    if rows.empty:
        raise KeyError(f"no contract listed for {name}")
    return rows.iloc[0]


def team_contracts(contracts: pd.DataFrame, team: str) -> pd.DataFrame:
    """One team's contract book: player rows × season salary columns.

    Sorted by nearest-season salary, largest first; GUARANTEED kept when
    present. Raises KeyError when the table lacks team or season columns.
    """
    seasons = salary_seasons(contracts)
    if not seasons or "TEAM_ABBREVIATION" not in contracts.columns:
        raise KeyError("contracts table lacks team or season columns")
    cols = ["PLAYER_NAME", *seasons]
    if "GUARANTEED" in contracts.columns:
        cols.append("GUARANTEED")
    rows = contracts.loc[contracts["TEAM_ABBREVIATION"] == team, cols]
    return rows.sort_values(seasons[0], ascending=False).reset_index(drop=True)


def team_payroll(contracts: pd.DataFrame) -> pd.Series:
    """Nearest-season committed payroll per team, largest first."""
    seasons = salary_seasons(contracts)
    if not seasons or "TEAM_ABBREVIATION" not in contracts.columns:
        raise KeyError("contracts table lacks team or season columns")
    return (
        contracts.groupby("TEAM_ABBREVIATION")[seasons[0]]
        .sum()
        .sort_values(ascending=False)
        .rename(seasons[0])
    )
