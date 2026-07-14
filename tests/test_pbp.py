import pandas as pd
import pytest

from nba_insights.pbp import garbage_time_margin, gt_margins_table


def make_pbp(events: list[tuple[int, int | None, int | None]]) -> pd.DataFrame:
    """Build a minimal PBP frame from (period, scoreHome, scoreAway) tuples.

    None scores model non-scoring events (PBPv3 leaves the fields empty).
    """
    return pd.DataFrame(
        {
            "period": [p for p, _, _ in events],
            "scoreHome": ["" if h is None else str(h) for _, h, _ in events],
            "scoreAway": ["" if a is None else str(a) for _, _, a in events],
        }
    )


def test_close_game_untouched():
    pbp = make_pbp([(1, 20, 18), (2, 50, 48), (3, 80, 75), (4, 100, 98), (4, 110, 105)])
    assert garbage_time_margin(pbp) == 5.0


def test_blowout_frozen_at_gt_start():
    # lead hits 20 in Q4 at 95-75; bench mops up to a 30-point final
    pbp = make_pbp([(3, 80, 70), (4, 95, 75), (4, 105, 78), (4, 120, 90)])
    assert garbage_time_margin(pbp) == 20.0


def test_comeback_cancels_garbage_time():
    # lead hit 20 in Q4 but the final margin came back under 15
    pbp = make_pbp([(4, 95, 75), (4, 100, 95), (4, 105, 100)])
    assert garbage_time_margin(pbp) == 5.0


def test_big_q3_lead_without_q4_threshold_uses_final():
    # 25-point Q3 lead, but Q4 margin never re-hits 20: keep the final
    pbp = make_pbp([(3, 90, 65), (4, 100, 84), (4, 110, 92)])
    assert garbage_time_margin(pbp) == 18.0


def test_road_blowout_negative_margin():
    pbp = make_pbp([(4, 75, 95), (4, 80, 110)])
    assert garbage_time_margin(pbp) == -20.0


def test_non_scoring_events_ignored():
    pbp = make_pbp([(4, None, None), (4, 95, 75), (4, None, None), (4, 120, 90)])
    assert garbage_time_margin(pbp) == 20.0


def test_empty_pbp_is_zero():
    assert garbage_time_margin(make_pbp([(1, None, None)])) == 0.0


def test_gt_margins_table_skips_bad_games():
    good = make_pbp([(4, 100, 90)])
    bad = pd.DataFrame({"nonsense": [1]})  # missing columns -> parse error
    table = gt_margins_table({"G1": good, "G2": bad})
    assert table["GAME_ID"].tolist() == ["G1"]
    assert table["gt_margin_home"].iloc[0] == pytest.approx(10.0)
