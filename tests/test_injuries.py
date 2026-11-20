"""Offline tests for the official injury report feed."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights import injuries as feed
from nba_insights.analysis.injuries import (
    injured_minutes,
    latest_report,
    team_missing_minutes,
)
from nba_insights.ingest.injuries import parse_injury_words, report_links
from nba_insights.store import Cache

# column x positions from the real report's header row
X = {"date": 23, "time": 120, "matchup": 200, "team": 264, "player": 425, "status": 586}
X_REASON = 666


def header() -> list[dict]:
    words = [("Injury Report: 11/19/26 07:00 PM", 289, 46)]
    words += [
        ("Game Date", 23, 108),
        ("Game Time", 120, 108),
        ("Matchup", 200, 108),
        ("Team", 264, 108),
        ("Player Name", 425, 108),
        ("Current Status", 586, 108),
        ("Reason", 666, 108),
    ]
    return [{"page": 1, "text": t, "x0": x, "top": top} for t, x, top in words]


def w(page: int, text: str, column: str, top: float) -> dict:
    x = X_REASON if column == "reason" else X[column]
    return {"page": page, "text": text, "x0": x + 1, "top": top}


def make_report_words() -> list[dict]:
    return [
        *header(),
        # Butler: two-line reason centered on his row (129 / 143 around 136)
        w(1, "Injury/Illness - Right ACL Repair /", "reason", 129),
        w(1, "11/19/2026", "date", 136),
        w(1, "08:00 (ET)", "time", 136),
        w(1, "GSW@MEM", "matchup", 136),
        w(1, "Golden State Warriors", "team", 136),
        w(1, "Butler III, Jimmy", "player", 136),
        w(1, "Out", "status", 136),
        w(1, "Surgery", "reason", 143),
        # Curry: one-line reason on his row; team/matchup carry forward
        w(1, "Curry, Stephen", "player", 165),
        w(1, "Out", "status", 165),
        w(1, "Injury/Illness - Right Oblique Tear", "reason", 165),
        # Edey: new team, reason split across the page break
        w(1, "Memphis Grizzlies", "team", 194),
        w(1, "Edey, Zach", "player", 194),
        w(1, "Questionable", "status", 194),
        w(1, "Injury/Illness - Left Ankle Injury", "reason", 194),
        w(1, "Page 1 of 2", "matchup", 538),
        w(2, "Injury Report: 11/19/26 07:00 PM", "matchup", 46),
        w(2, "Management", "reason", 81),
        # Phoenix hasn't submitted
        w(2, "09:30 (ET)", "time", 111),
        w(2, "PHX@UTA", "matchup", 111),
        w(2, "Phoenix Suns", "team", 111),
        w(2, "NOT YET SUBMITTED", "reason", 111),
    ]


def test_parse_injury_words_rebuilds_rows_and_reasons():
    df = parse_injury_words(make_report_words()).set_index("PLAYER_NAME")
    assert df.loc["Jimmy Butler III", "REASON"] == "Injury/Illness - Right ACL Repair/Surgery"
    assert df.loc["Jimmy Butler III", "TEAM"] == "GSW"
    assert df.loc["Stephen Curry", "MATCHUP"] == "GSW@MEM"
    assert df.loc["Stephen Curry", "REASON"] == "Injury/Illness - Right Oblique Tear"
    # page-split reason tail joins the last row of the previous page
    assert df.loc["Zach Edey", "REASON"] == "Injury/Illness - Left Ankle Injury Management"
    assert df.loc["Zach Edey", "TEAM"] == "MEM"
    assert df.loc["Zach Edey", "STATUS"] == "Questionable"
    assert (df.loc["Zach Edey", "AWAY"], df.loc["Zach Edey", "HOME"]) == ("GSW", "MEM")
    assert df.loc["Zach Edey", "GAME_DATE"] == "2026-11-19"


def test_parse_injury_words_keeps_not_yet_submitted_teams():
    df = parse_injury_words(make_report_words())
    pending = df[df["STATUS"] == "Not Yet Submitted"]
    assert pending["TEAM"].tolist() == ["PHX"]
    assert pending["PLAYER"].tolist() == [""]


def test_parse_injury_words_rejects_unrecognized_layout():
    with pytest.raises(ValueError):
        parse_injury_words([])
    with pytest.raises(ValueError):
        parse_injury_words([{"page": 1, "text": "Reason", "x0": 666, "top": 108}])


def test_report_links_parses_eastern_timestamps_in_order():
    html = (
        '<a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-19_12_15PM.pdf">'
        '<a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-19_01_00AM.pdf">'
        '<a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-19_07_00PM.pdf">'
    )
    links = report_links(html)
    assert [t.strftime("%H:%M") for t in links["REPORT_AT"]] == ["01:00", "12:15", "19:00"]
    with pytest.raises(ValueError):
        report_links("<html>no reports</html>")


def make_games() -> tuple[pd.DataFrame, pd.DataFrame]:
    # GSW has played 10 games; Curry 30 min in each, Green missed all 10
    current = pd.DataFrame(
        {
            "PLAYER_ID": [1] * 10 + [3] * 10,
            "PLAYER_NAME": ["Stephen Curry"] * 10 + ["Brandon Podziemski"] * 10,
            "TEAM_ABBREVIATION": ["GSW"] * 20,
            "GAME_ID": [f"g{i}" for i in range(10)] * 2,
            "MIN": [30.0] * 10 + [25.0] * 10,
        }
    )
    prior = pd.DataFrame(
        {
            "PLAYER_ID": [1, 2],
            "PLAYER_NAME": ["Stephen Curry", "Draymond Green"],
            "TEAM_ABBREVIATION": ["GSW", "GSW"],
            "GAME_ID": ["p1", "p1"],
            "MIN": [82 * 32.0, 82 * 28.0],  # 32 and 28 minutes per team game
        }
    )
    return current, prior


def report_rows(*rows: tuple[str, str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "GAME_DATE": "2026-11-19",
                "AWAY": "GSW",
                "HOME": "MEM",
                "TEAM": team,
                "PLAYER": name,
                "PLAYER_NAME": name,
                "STATUS": status,
                "REASON": "",
            }
            for team, name, status in rows
        ]
    )


def test_injured_minutes_blends_season_and_prior_like_training():
    current, prior = make_games()
    report = report_rows(
        ("GSW", "Stephen Curry", "Out"),
        ("GSW", "Draymond Green", "Questionable"),
        ("GSW", "Two Way Guy", "Out"),
        ("GSW", "Brandon Podziemski", "Probable"),
    )
    players = injured_minutes(report, current, prior).set_index("PLAYER_NAME")
    # (10 games * 30 + 32 * 20) / (10 + 20)
    assert players.loc["Stephen Curry", "EXP_MIN"] == pytest.approx(31.3, abs=0.05)
    # missed every game: only the prior counts, (0 + 28 * 20) / 30
    assert players.loc["Draymond Green", "EXP_MIN"] == pytest.approx(18.7, abs=0.05)
    assert players.loc["Draymond Green", "MISSING_MIN"] == pytest.approx(9.3, abs=0.1)
    assert players.loc["Two Way Guy", "EXP_MIN"] == 0.0
    assert players.loc["Brandon Podziemski", "MISSING_MIN"] == 0.0
    assert team_missing_minutes(players)["GSW"] == pytest.approx(
        (300 + 640) / 30 + 0.5 * 560 / 30, abs=0.02
    )


def test_game_missing_minutes_skips_games_with_pending_teams():
    report = pd.concat(
        [
            report_rows(("GSW", "Stephen Curry", "Out")),
            pd.DataFrame(
                [
                    {
                        "GAME_DATE": "2026-11-19",
                        "AWAY": "PHX",
                        "HOME": "UTA",
                        "TEAM": "PHX",
                        "PLAYER": "",
                        "PLAYER_NAME": "",
                        "STATUS": "Not Yet Submitted",
                        "REASON": "",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    players = pd.DataFrame({"TEAM": ["GSW"], "MISSING_MIN": [30.0]})
    missing = feed.game_missing_minutes(report, players)
    assert missing == {("2026-11-19", "GSW", "MEM"): (0.0, 30.0)}


class FakeClient:
    def __init__(self, cache: Cache, links: pd.DataFrame) -> None:
        self.cache = cache
        self.links = links
        self.fetched: list[str] = []

    def injury_report_index(self, season: str | None = None) -> pd.DataFrame:
        return self.links

    def injury_report(self, url: str) -> pd.DataFrame:
        self.fetched.append(url)
        return report_rows(("GSW", "Stephen Curry", "Out"))


def test_update_injuries_logs_each_report_once(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")
    links = pd.DataFrame({"URL": ["a.pdf"], "REPORT_AT": [pd.Timestamp("2026-11-19 19:00")]})
    client = FakeClient(cache, links)

    first = feed.update_injuries(client)
    again = feed.update_injuries(client)
    assert client.fetched == ["a.pdf"]
    assert len(first) == len(again) == 1

    client.links = pd.concat(
        [links, pd.DataFrame({"URL": ["b.pdf"], "REPORT_AT": [pd.Timestamp("2026-11-19 19:15")]})],
        ignore_index=True,
    )
    latest = feed.update_injuries(client)
    assert client.fetched == ["a.pdf", "b.pdf"]
    assert (latest["REPORT_AT"] == pd.Timestamp("2026-11-19 19:15")).all()
    assert len(feed.load_injury_log(client)) == 2
    assert latest_report(feed.load_injury_log(client)).equals(latest)


def test_injured_minutes_with_no_listed_players_is_empty():
    current, prior = make_games()
    pending = report_rows(("PHX", "", "Not Yet Submitted"))
    players = injured_minutes(pending, current, prior)
    assert players.empty
    assert team_missing_minutes(players).empty


def test_injured_minutes_on_opening_night_uses_prior_only():
    _, prior = make_games()
    report = report_rows(("GSW", "Stephen Curry", "Out"))
    players = injured_minutes(report, pd.DataFrame(), prior).set_index("PLAYER_NAME")
    # no games yet: (0 + 32 * 20) / (0 + 20)
    assert players.loc["Stephen Curry", "EXP_MIN"] == pytest.approx(32.0)
