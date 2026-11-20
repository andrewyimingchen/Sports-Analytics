"""Offline tests for the Kalshi/Polymarket price tracker."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from nba_insights import markets as tracker
from nba_insights.analysis.markets import (
    market_scorecard,
    match_prices,
    opening_closing,
    schedule_games,
)
from nba_insights.ingest.markets import decode_kalshi, decode_polymarket
from nba_insights.store import Cache


def kalshi_market(team: str, bid: str, ask: str, last: str = "0.5") -> dict:
    return {
        "event_ticker": "KXNBAGAME-26NOV19GSWMEM",
        "ticker": f"KXNBAGAME-26NOV19GSWMEM-{team}",
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "last_price_dollars": last,
        "volume_fp": "1000.00",
    }


def polymarket_event(outcomes: list[str], best_bid: float, best_ask: float) -> dict:
    return {
        "slug": "nba-gsw-mem-2026-11-19",
        "eventDate": "2026-11-19",
        "teams": [
            {"name": "Warriors", "abbreviation": "gsw", "ordering": "away"},
            {"name": "Grizzlies", "abbreviation": "mem", "ordering": "home"},
        ],
        "markets": [
            {"sportsMarketType": "spreads", "outcomes": '["Grizzlies", "Warriors"]'},
            {
                "sportsMarketType": "moneyline",
                "outcomes": str(outcomes).replace("'", '"'),
                "outcomePrices": '["0.335", "0.665"]',
                "bestBid": best_bid,
                "bestAsk": best_ask,
                "volumeNum": 1500.0,
            },
        ],
    }


def test_decode_kalshi_keeps_home_market_and_parses_ticker():
    df = decode_kalshi([kalshi_market("GSW", "0.33", "0.34"), kalshi_market("MEM", "0.66", "0.67")])
    assert len(df) == 1
    row = df.iloc[0]
    assert (row["GAME_DATE"], row["AWAY"], row["HOME"]) == ("2026-11-19", "GSW", "MEM")
    assert row["HOME_PRICE"] == pytest.approx(0.665)
    assert (row["HOME_BID"], row["HOME_ASK"]) == (0.66, 0.67)


def test_decode_kalshi_one_sided_book_falls_back_to_last_trade():
    df = decode_kalshi([kalshi_market("MEM", "0.0000", "1.0000", last="0.61")])
    assert df.iloc[0]["HOME_PRICE"] == pytest.approx(0.61)
    assert pd.isna(df.iloc[0]["HOME_BID"]) and pd.isna(df.iloc[0]["HOME_ASK"])


def test_decode_kalshi_rejects_payload_with_no_parseable_game():
    with pytest.raises(ValueError):
        decode_kalshi([{"event_ticker": "SOMETHING-ELSE", "ticker": "X"}])
    assert decode_kalshi([]).empty


def test_decode_polymarket_mirrors_quote_when_home_listed_second():
    # bestBid/bestAsk quote the first outcome (Warriors, away)
    df = decode_polymarket([polymarket_event(["Warriors", "Grizzlies"], 0.33, 0.34)])
    row = df.iloc[0]
    assert (row["AWAY"], row["HOME"]) == ("GSW", "MEM")
    assert row["HOME_BID"] == pytest.approx(0.66)
    assert row["HOME_ASK"] == pytest.approx(0.67)
    assert row["HOME_PRICE"] == pytest.approx(0.665)


def test_decode_polymarket_home_listed_first_uses_quote_directly():
    event = polymarket_event(["Grizzlies", "Warriors"], 0.66, 0.67)
    event["markets"][1]["outcomePrices"] = '["0.665", "0.335"]'
    row = decode_polymarket([event]).iloc[0]
    assert (row["HOME_BID"], row["HOME_ASK"]) == (0.66, 0.67)


def test_decode_polymarket_skips_events_without_moneyline_or_teams():
    event = polymarket_event(["Warriors", "Grizzlies"], 0.33, 0.34)
    no_teams = {**event, "teams": []}
    no_moneyline = {**event, "markets": event["markets"][:1]}
    assert decode_polymarket([no_teams, no_moneyline]).empty


def make_schedule() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameId": ["0022600270", "0022600271"],
            "gameDateEst": ["2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"],
            "gameDateTimeUTC": ["2026-11-20T01:00:00Z", "2026-11-20T01:00:00Z"],
            "awayTeam_teamTricode": ["GSW", "NYK"],
            "homeTeam_teamTricode": ["MEM", "MIN"],
            "gameStatus": [3, 1],
            "homeTeam_score": [120, 0],
            "awayTeam_score": [110, 0],
        }
    )


def test_schedule_games_marks_results_only_for_finished_games():
    games = schedule_games(make_schedule()).set_index("GAME_ID")
    assert games.loc["0022600270", "HOME_WIN"] == 1.0
    assert math.isnan(games.loc["0022600271", "HOME_WIN"])
    assert games.loc["0022600270", "GAME_DATE"] == "2026-11-19"


def test_match_prices_drops_games_already_under_way():
    games = schedule_games(make_schedule())
    prices = decode_kalshi([kalshi_market("MEM", "0.66", "0.67")])
    before = match_prices(games, prices, pd.Timestamp("2026-11-20T00:30Z"))
    after = match_prices(games, prices, pd.Timestamp("2026-11-20T01:30Z"))
    assert list(before["GAME_ID"]) == ["0022600270"]
    assert after.empty


def snapshot_row(
    at: str, price: float, model: float, bid: float, ask: float, injured: float | None = None
) -> dict:
    return {
        "SNAPSHOT_AT": pd.Timestamp(at),
        "SOURCE": "kalshi",
        "MARKET_ID": "KXNBAGAME-26NOV19GSWMEM",
        "GAME_ID": "0022600270",
        "GAME_DATE": "2026-11-19",
        "TIP_UTC": pd.Timestamp("2026-11-20T01:00Z"),
        "AWAY": "GSW",
        "HOME": "MEM",
        "HOME_PRICE": price,
        "HOME_BID": bid,
        "HOME_ASK": ask,
        "VOLUME": 1.0,
        "MODEL_HOME_PROB": model,
        "MODEL_HOME_PROB_INJ": injured,
    }


def test_opening_closing_ignores_snapshots_after_tip():
    snaps = pd.DataFrame(
        [
            snapshot_row("2026-11-19T12:00Z", 0.60, 0.70, 0.59, 0.61),
            snapshot_row("2026-11-20T00:50Z", 0.64, 0.70, 0.63, 0.65),
            snapshot_row("2026-11-20T02:00Z", 0.90, 0.70, 0.89, 0.91),  # in-game
        ]
    )
    line = opening_closing(snaps).iloc[0]
    assert line["OPEN_PRICE"] == 0.60
    assert line["CLOSE_PRICE"] == 0.64
    assert line["HOME_ASK"] == 0.65


def test_market_scorecard_clv_and_roi_on_model_side():
    snaps = pd.DataFrame(
        [
            snapshot_row("2026-11-19T12:00Z", 0.60, 0.70, 0.59, 0.61),
            snapshot_row("2026-11-20T00:50Z", 0.64, 0.70, 0.63, 0.65),
        ]
    )
    card = market_scorecard(opening_closing(snaps), schedule_games(make_schedule())).iloc[0]
    assert card["GAMES"] == 1
    # model liked home at open (0.70 vs 0.60); the line moved 4 points its way
    assert card["CLV_MEAN"] == pytest.approx(0.04)
    # home bet at the 0.65 ask won: profit 1/0.65 - 1
    assert card["BETS"] == 1
    assert card["ROI"] == pytest.approx(1 / 0.65 - 1)
    assert card["MODEL_LOG_LOSS"] == pytest.approx(-math.log(0.70))
    assert card["MARKET_LOG_LOSS"] == pytest.approx(-math.log(0.64))


class FakeClient:
    def __init__(self, cache: Cache, kalshi_fails: bool = False) -> None:
        self.cache = cache
        self.kalshi_fails = kalshi_fails

    def kalshi_nba_games(self) -> pd.DataFrame:
        if self.kalshi_fails:
            from nba_insights.errors import UpstreamError

            raise UpstreamError("kalshi down")
        return decode_kalshi([kalshi_market("MEM", "0.66", "0.67")])

    def polymarket_nba_games(self, season: str | None = None) -> pd.DataFrame:
        return decode_polymarket([polymarket_event(["Warriors", "Grizzlies"], 0.33, 0.34)])

    def schedule(self, season: str | None = None) -> pd.DataFrame:
        return make_schedule()


def test_take_snapshot_appends_and_survives_one_exchange_failing(tmp_path, monkeypatch):
    seen_missing = []

    def fake_probabilities(client, rows, missing=None):
        seen_missing.append(missing)
        return pd.DataFrame({"MODEL_HOME_PROB": 0.6, "MODEL_HOME_PROB_INJ": 0.55}, index=rows.index)

    monkeypatch.setattr(tracker, "model_probabilities", fake_probabilities)
    injuries = {("2026-11-19", "GSW", "MEM"): (10.0, 40.0)}
    monkeypatch.setattr(tracker, "injury_minutes", lambda client: injuries)
    cache = Cache(tmp_path / "cache.sqlite3")
    now = pd.Timestamp("2026-11-20T00:30Z")

    recorded, failures = tracker.take_snapshot(FakeClient(cache), now=now)
    assert (recorded, failures) == (2, 0)

    later = pd.Timestamp("2026-11-20T00:45Z")
    recorded, failures = tracker.take_snapshot(FakeClient(cache, kalshi_fails=True), now=later)
    assert (recorded, failures) == (1, 1)

    log = tracker.load_snapshots(FakeClient(cache))
    assert len(log) == 3
    assert sorted(log["SOURCE"]) == ["kalshi", "polymarket", "polymarket"]
    assert (log["MODEL_HOME_PROB"] == 0.6).all()
    assert (log["MODEL_HOME_PROB_INJ"] == 0.55).all()
    assert seen_missing == [injuries, injuries]


def test_opening_closing_takes_whole_rows_not_last_non_null_values():
    # the closing snapshot has no bid (one-sided book): must stay NaN, not
    # borrow the earlier snapshot's bid
    snaps = pd.DataFrame(
        [
            snapshot_row("2026-11-19T12:00Z", 0.60, 0.70, 0.59, 0.61),
            snapshot_row("2026-11-20T00:50Z", 0.64, 0.70, float("nan"), 0.65),
        ]
    )
    line = opening_closing(snaps).iloc[0]
    assert math.isnan(line["HOME_BID"])


def test_opening_closing_reads_old_snapshots_without_injury_column():
    snaps = pd.DataFrame([snapshot_row("2026-11-19T12:00Z", 0.60, 0.70, 0.59, 0.61)])
    line = opening_closing(snaps.drop(columns="MODEL_HOME_PROB_INJ")).iloc[0]
    assert math.isnan(line["CLOSE_MODEL_INJ"])


def test_market_scorecard_injury_model_scores_only_covered_games():
    snaps = pd.DataFrame(
        [
            snapshot_row("2026-11-19T12:00Z", 0.60, 0.70, 0.59, 0.61),
            snapshot_row("2026-11-20T00:50Z", 0.64, 0.70, 0.63, 0.65, injured=0.80),
        ]
    )
    lines = opening_closing(snaps)
    games = schedule_games(make_schedule())
    card = market_scorecard(lines, games, model="MODEL_INJ").iloc[0]
    assert card["MODEL"] == "MODEL_INJ"
    assert card["MODEL_LOG_LOSS"] == pytest.approx(-math.log(0.80))
    # no injury-adjusted probability at the open: no CLV sample
    assert card["CLV_GAMES"] == 0

    uncovered = lines.assign(CLOSE_MODEL_INJ=float("nan"))
    assert market_scorecard(uncovered, games, model="MODEL_INJ").empty
