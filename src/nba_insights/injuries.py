"""Official NBA injury report feed: log each report, derive minutes out.

    uv run python -m nba_insights.injuries          # fetch latest, show by team

Each check reads the league's index page and, if a newer report is out,
fetches and parses it (cached forever: a published report never changes) and
appends its rows to the season's injury log in the cache database
(``injuries/log/<season>``), so the log is backed up with the rest.

The market tracker calls :func:`update_injuries` on every snapshot, but it
only checks the index three times on game days: 10:00 ET, 15:00 ET, and 45
minutes before the first tip-off (about six requests a day). Between
checks, snapshots reuse the latest logged report. Running this CLI always
checks (reusing an index fetched in the last 30 minutes).

Scraped under the CLAUDE.md guardrails (owner decision 2026-11-19): personal
and educational use only; never served through the public API/PWA.
"""

from __future__ import annotations

import argparse
import logging
from datetime import timedelta

import pandas as pd

from nba_insights.analysis.injuries import (
    injured_minutes,
    injury_check_due,
    latest_report,
    team_missing_minutes,
)
from nba_insights.config import calendar_season, previous_season
from nba_insights.errors import EXPECTED_ERRORS, reason_for
from nba_insights.ingest import NBAClient, serving_client
from nba_insights.ingest.client import injury_index_key

logger = logging.getLogger(__name__)

# manual CLI runs reuse an index fetched in the last 30 minutes
INJURY_INDEX_TTL_MANUAL = timedelta(minutes=30)


def log_key(season: str) -> str:
    return f"injuries/log/{season}"


def load_injury_log(client: NBAClient, season: str | None = None) -> pd.DataFrame:
    """Every logged report row for *season* (empty frame if none yet)."""
    stored = client.cache.get(log_key(season or calendar_season()))
    return pd.DataFrame() if stored is None else stored


def last_checked(client: NBAClient, season: str) -> pd.Timestamp | None:
    """When the report index was last fetched (None if never)."""
    info = client.cache.entry_info(injury_index_key(season))
    return None if info is None else pd.Timestamp(info["fetched_at"]).tz_convert("UTC")


def update_injuries(
    client: NBAClient,
    season: str | None = None,
    *,
    force: bool = False,
    now: pd.Timestamp | None = None,
    first_tip: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Log the newest report if it isn't logged yet; return the latest report.

    Unless *force*, the index is only checked when a scheduled checkpoint
    (see :func:`~nba_insights.analysis.injuries.injury_check_due`; needs
    today's *first_tip*) has passed since the last check; otherwise the
    latest logged report is returned without touching the network.

    Returns an empty frame when no report is available (off days, or the
    index/report fetch failed -- logged, not raised, so callers degrade to
    no injury information).
    """
    season = season or calendar_season()
    log = load_injury_log(client, season)
    if force:
        max_age = INJURY_INDEX_TTL_MANUAL
    else:
        now = now or pd.Timestamp.now("UTC")
        if not injury_check_due(now, last_checked(client, season), first_tip):
            return latest_report(log)
        max_age = timedelta(0)  # a checkpoint passed: look now
    try:
        links = client.injury_report_index(season, max_age=max_age)
        newest = links.iloc[-1]
        if log.empty or newest["REPORT_AT"] > log["REPORT_AT"].max():
            report = client.injury_report(newest["URL"]).copy()
            report.insert(0, "REPORT_AT", newest["REPORT_AT"])
            log = report if log.empty else pd.concat([log, report], ignore_index=True)
            client.cache.put(log_key(season), log)
            logger.info("logged injury report %s (%d rows)", newest["REPORT_AT"], len(report))
    except EXPECTED_ERRORS as error:
        logger.warning("injury report unavailable: %s", reason_for(error))
    except IndexError:
        logger.info("no injury reports published today")
    return latest_report(log)


def players_out(client: NBAClient, report: pd.DataFrame) -> pd.DataFrame:
    """Per-player expected and missing minutes for *report* (see analysis)."""
    season = calendar_season()
    return injured_minutes(
        report,
        client.player_games(season),
        client.player_games(previous_season(season)),
    )


def game_missing_minutes(
    report: pd.DataFrame, players: pd.DataFrame
) -> dict[tuple[str, str, str], tuple[float, float]]:
    """(GAME_DATE, AWAY, HOME) -> (home, away) expected minutes out.

    Only games in the report with both teams submitted are included:
    a team whose report says NOT YET SUBMITTED has unknown availability,
    which is not the same as nobody out.
    """
    if report.empty:
        return {}
    missing = team_missing_minutes(players)
    pending = set(report.loc[report["STATUS"] == "Not Yet Submitted", "TEAM"])
    games = report[["GAME_DATE", "AWAY", "HOME"]].drop_duplicates()
    return {
        (g.GAME_DATE, g.AWAY, g.HOME): (
            float(missing.get(g.HOME, 0.0)),
            float(missing.get(g.AWAY, 0.0)),
        )
        for g in games.itertuples()
        if g.HOME not in pending and g.AWAY not in pending
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Official NBA injury report feed")
    parser.add_argument(
        "--min-minutes", type=float, default=5.0, help="hide players expected to play less"
    )
    args = parser.parse_args()

    client = serving_client()
    report = update_injuries(client, force=True)
    if report.empty:
        print("no injury report available")
        return
    players = players_out(client, report)
    print(f"Report {report['REPORT_AT'].iloc[0]:%Y-%m-%d %I:%M %p} ET")
    shown = players[(players["WEIGHT"] > 0) & (players["EXP_MIN"] >= args.min_minutes)]
    totals = team_missing_minutes(players)
    for team, rows in shown.groupby("TEAM"):
        print(f"\n{team}  expected minutes out: {totals.get(team, 0.0):.1f}")
        for row in rows.sort_values("EXP_MIN", ascending=False).itertuples():
            print(f"  {row.PLAYER_NAME:<24} {row.STATUS:<13} {row.EXP_MIN:5.1f}  {row.REASON}")
    pending = report.loc[report["STATUS"] == "Not Yet Submitted", "TEAM"].tolist()
    if pending:
        print(f"\nnot yet submitted: {', '.join(pending)}")


if __name__ == "__main__":
    main()
