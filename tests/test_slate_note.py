"""Offline tests for the Obsidian game-day slate note."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights import markets as tracker
from nba_insights.analysis.slate_note import (
    NOTE_END,
    NOTE_START,
    merge_note,
    note_frontmatter,
    parlay_legs,
    render_note,
    slate_table,
    track_record,
)


def games_frame(home_win=(float("nan"), float("nan"))) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "GAME_ID": ["1", "2", "3"],
            "GAME_DATE": ["2026-11-20", "2026-11-20", "2026-11-21"],
            "TIP_UTC": pd.to_datetime(
                ["2026-11-21T00:30Z", "2026-11-21T00:00Z", "2026-11-22T00:00Z"], utc=True
            ),
            "AWAY": ["ORL", "CHA", "MIL"],
            "HOME": ["BKN", "ATL", "PHI"],
            "HOME_WIN": [*home_win, float("nan")],
        }
    )


def lines_frame() -> pd.DataFrame:
    # opening_closing output: two exchanges for game 1, one for game 2
    return pd.DataFrame(
        {
            "SOURCE": ["kalshi", "polymarket", "kalshi"],
            "GAME_ID": ["1", "1", "2"],
            "OPEN_PRICE": [0.35, 0.35, 0.65],
            "CLOSE_PRICE": [0.30, 0.31, 0.70],
            "HOME_BID": [0.29, 0.30, 0.69],
            "HOME_ASK": [0.31, 0.32, 0.71],
            "CLOSE_MODEL": [0.35, 0.35, 0.66],
            "CLOSE_MODEL_INJ": [0.385, 0.385, float("nan")],
        }
    )


def test_slate_table_averages_exchanges_and_prefers_injury_model():
    slate = slate_table(lines_frame(), games_frame(), "2026-11-20")
    assert list(slate["HOME"]) == ["ATL", "BKN"]  # by tip time
    bkn = slate.iloc[1]
    assert bkn["PRICE"] == pytest.approx(0.305)
    assert (bkn["BID"], bkn["ASK"]) == (0.30, 0.31)
    assert bkn["PROB"] == pytest.approx(0.385)
    assert bkn["GAP"] == pytest.approx(0.08)
    atl = slate.iloc[0]
    assert atl["PROB"] == pytest.approx(0.66)  # no injury column: full strength
    assert atl["GAP"] == pytest.approx(-0.04)


def test_slate_table_keeps_unpriced_games():
    slate = slate_table(lines_frame().iloc[0:0], games_frame(), "2026-11-20")
    assert len(slate) == 2 and slate["PRICE"].isna().all()


def test_parlay_legs_take_the_model_side_and_skip_small_gaps():
    slate = slate_table(lines_frame(), games_frame((1.0, 1.0)), "2026-11-20")
    legs = parlay_legs(slate, min_gap=0.03)
    assert list(legs["TEAM"]) == ["BKN", "CHA"]
    cha = legs.iloc[1]  # model likes the away side: probabilities flip
    assert cha["PROB"] == pytest.approx(0.34) and cha["PRICE"] == pytest.approx(0.30)
    assert cha["WON"] == 0  # ATL (home) won
    assert legs.iloc[0]["WON"] == 1
    assert parlay_legs(slate, min_gap=0.05)["TEAM"].tolist() == ["BKN"]


def scorecard(games: int, model_loss: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "MODEL": ["MODEL", "MODEL"],
            "SOURCE": ["kalshi", "polymarket"],
            "GAMES": [games, games],
            "MODEL_LOG_LOSS": [model_loss, model_loss],
            "MARKET_LOG_LOSS": [0.60, 0.61],
        }
    )


def test_track_record_needs_volume_and_a_better_log_loss():
    assert track_record(pd.DataFrame())[0] is False
    assert track_record(scorecard(40, 0.55))[0] is False  # too few games
    assert track_record(scorecard(150, 0.65))[0] is False  # worse than market
    earned, summary = track_record(scorecard(150, 0.55))
    assert earned and "150 finished games" in summary


def render(home_win=(float("nan"), float("nan"))) -> tuple[str, str]:
    slate = slate_table(lines_frame(), games_frame(home_win), "2026-11-20")
    return render_note(
        "2026-11-20",
        slate,
        players=pd.DataFrame(),
        report_at=pd.Timestamp("2026-11-20 17:00"),
        scorecard=pd.DataFrame(),
        updated=pd.Timestamp("2026-11-20T22:06Z"),
        previous="2026-11-19",
        following="2026-11-21",
    )


def test_render_note_marks_parlays_unearned_and_links_neighbours():
    frontmatter, block = render()
    meta = note_frontmatter(frontmatter + "\n")
    assert meta["final"] == "false" and meta["games"] == "2"
    assert meta["injury_report"] == "2026-11-20 17:00 ET"
    assert "[[2026-11-19 NBA Slate]]" in block and "[[2026-11-21 NBA Slate]]" in block
    assert "Skip parlays" in block
    assert "| 7:30 PM | ORL @ **BKN** | .350 | .305 |" in block
    assert "Result" not in block


def test_render_note_adds_results_once_final():
    frontmatter, block = render((1.0, 0.0))
    assert note_frontmatter(frontmatter + "\n")["final"] == "true"
    assert "BKN won ✅" in block  # model liked BKN
    assert "CHA won ✅" in block  # model liked CHA over ATL


def test_merge_note_keeps_owner_text_and_replaces_generated_block():
    first = merge_note(None, "---\nupdated: a\n---", "old block")
    edited = first + "Bet CHI singles only.\n"
    merged = merge_note(edited, "---\nupdated: b\n---", "new block")
    assert "new block" in merged and "old block" not in merged
    assert merged.count(NOTE_START) == 1 and merged.count(NOTE_END) == 1
    assert merged.endswith("Bet CHI singles only.\n")
    assert note_frontmatter(merged)["updated"] == "b"


def test_merge_note_puts_generated_block_above_a_hand_written_note():
    merged = merge_note("# My own slate notes\n", "---\nupdated: b\n---", "block")
    assert merged.index(NOTE_END) < merged.index("# My own slate notes")


def write(vault, date: str, **meta: str) -> None:
    path = tracker.note_path(vault, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{key}: {value}\n" for key, value in meta.items())
    path.write_text(f"---\n{lines}---\nbody\n", encoding="utf-8")


def test_notes_due_follows_checkpoints_and_finalizes_previous_day(tmp_path):
    games = games_frame()
    # 2026-11-21 09:00 ET: yesterday's games have no results yet, today has none
    morning = pd.Timestamp("2026-11-21T14:00Z")
    assert tracker.notes_due(tmp_path, games, morning) == ["2026-11-21"]  # missing
    write(tmp_path, "2026-11-21", updated="2026-11-21T14:00:00+00:00")
    assert tracker.notes_due(tmp_path, games, morning) == []
    # 10:00 ET checkpoint passed since the last write
    assert tracker.notes_due(tmp_path, games, pd.Timestamp("2026-11-21T15:05Z")) == ["2026-11-21"]

    final = games_frame((1.0, 0.0))
    assert tracker.notes_due(tmp_path, final, morning) == ["2026-11-20"]
    write(tmp_path, "2026-11-20", final="true")
    assert tracker.notes_due(tmp_path, final, morning) == []
