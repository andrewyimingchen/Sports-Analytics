"""Definitions and display shaping for official tracking and hustle dashboards."""

from __future__ import annotations

from typing import Any

import pandas as pd

TRACKING_CATEGORIES: dict[str, dict[str, Any]] = {
    "drives": {
        "label": "Drives",
        "measure": "Drives",
        "metrics": {
            "DRIVES": "Drives per game",
            "DRIVE_PTS": "Points scored from drives per game",
            "DRIVE_FG_PCT": "Field-goal percentage on drive attempts",
            "DRIVE_PASSES": "Passes made from drives per game",
            "DRIVE_AST": "Assists created from drives per game",
            "DRIVE_TOV": "Turnovers committed on drives per game",
        },
    },
    "touches": {
        "label": "Touches and possession",
        "measure": "Possessions",
        "metrics": {
            "TOUCHES": "Touches per game",
            "FRONT_CT_TOUCHES": "Frontcourt touches per game",
            "TIME_OF_POSS": "Minutes of possession per game",
            "AVG_SEC_PER_TOUCH": "Average seconds per touch",
            "AVG_DRIB_PER_TOUCH": "Average dribbles per touch",
            "PTS_PER_TOUCH": "Points per touch",
            "PAINT_TOUCHES": "Paint touches per game",
            "POST_TOUCHES": "Post touches per game",
        },
    },
    "passing": {
        "label": "Passing creation",
        "measure": "Passing",
        "metrics": {
            "PASSES_MADE": "Passes made per game",
            "PASSES_RECEIVED": "Passes received per game",
            "AST": "Assists per game in the tracking feed",
            "SECONDARY_AST": "Secondary assists per game",
            "POTENTIAL_AST": "Potential assists per game",
            "AST_POINTS_CREATED": "Points created by assists per game",
            "AST_TO_PASS_PCT": "Share of passes producing assists",
        },
    },
    "defense": {
        "label": "Rim shot defense",
        "measure": "Defense",
        "metrics": {
            "DEF_RIM_FGM": "Opponent rim field goals made while defended per game",
            "DEF_RIM_FGA": "Opponent rim field-goal attempts while defended per game",
            "DEF_RIM_FG_PCT": "Opponent rim field-goal percentage while defended",
        },
    },
    "speed": {
        "label": "Speed and distance",
        "measure": "SpeedDistance",
        "metrics": {
            "DIST_MILES": "Miles traveled per game",
            "DIST_MILES_OFF": "Offensive miles traveled per game",
            "DIST_MILES_DEF": "Defensive miles traveled per game",
            "AVG_SPEED": "Average speed in miles per hour",
            "AVG_SPEED_OFF": "Average offensive speed in miles per hour",
            "AVG_SPEED_DEF": "Average defensive speed in miles per hour",
        },
    },
    "hustle": {
        "label": "Hustle",
        "measure": None,
        "metrics": {
            "CONTESTED_SHOTS": "Contested shots per game",
            "DEFLECTIONS": "Deflections per game",
            "CHARGES_DRAWN": "Charges drawn per game",
            "SCREEN_ASSISTS": "Screen assists per game",
            "LOOSE_BALLS_RECOVERED": "Loose balls recovered per game",
            "BOX_OUTS": "Box-outs per game",
        },
    },
}

PERCENTAGE_METRICS = {
    "DRIVE_FG_PCT",
    "AST_TO_PASS_PCT",
    "DEF_RIM_FG_PCT",
}


def tracking_table(
    frame: pd.DataFrame,
    category: str,
    *,
    scope: str = "Player",
    min_games: int = 10,
    team: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    limit: int = 100,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter one upstream tracking category and report schema availability."""
    if category not in TRACKING_CATEGORIES:
        raise ValueError(f"unknown tracking category {category!r}")
    if scope not in {"Player", "Team"}:
        raise ValueError("tracking scope must be Player or Team")
    config = TRACKING_CATEGORIES[category]
    games_column = "GP" if "GP" in frame else "G" if "G" in frame else None
    name_column = "PLAYER_NAME" if scope == "Player" else "TEAM_NAME"
    id_columns = (
        ["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"]
        if scope == "Player"
        else ["TEAM_ID", "TEAM_NAME", "TEAM_ABBREVIATION"]
    )
    available = [metric for metric in config["metrics"] if metric in frame.columns]
    missing = [metric for metric in config["metrics"] if metric not in frame.columns]
    result = frame.copy()
    if games_column:
        result = result[pd.to_numeric(result[games_column], errors="coerce") >= min_games]
    if team and "TEAM_ABBREVIATION" in result:
        result = result[result["TEAM_ABBREVIATION"] == team.upper()]
    if query and name_column in result:
        result = result[
            result[name_column].astype(str).str.contains(query, case=False, regex=False)
        ]
    selected_sort = sort if sort in available else available[0] if available else None
    if selected_sort:
        ascending = selected_sort in {"DEF_RIM_FG_PCT", "DRIVE_TOV"}
        result = result.sort_values(selected_sort, ascending=ascending)
    columns = [column for column in [*id_columns, games_column, "MIN", *available] if column]
    columns = list(dict.fromkeys(column for column in columns if column in result.columns))
    metadata = {
        "category": category,
        "label": config["label"],
        "scope": scope.lower(),
        "definitions": {metric: config["metrics"][metric] for metric in available},
        "percentage_metrics": [metric for metric in available if metric in PERCENTAGE_METRICS],
        "available_metrics": available,
        "missing_metrics": missing,
        "games_column": games_column,
        "minimum_games": min_games,
    }
    return result[columns].head(limit).reset_index(drop=True), metadata
