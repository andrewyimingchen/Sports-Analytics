"""Smoke tests for the Streamlit app, via streamlit.testing.AppTest.

These drive the real pages against the local SQLite cache, so they are
skipped when the cache (or trained model artifacts) are absent — e.g. in
CI — which keeps the suite network-free everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nba_insights.config import CACHE_DB, MODELS_DIR

APP = str(Path(__file__).parents[1] / "app" / "streamlit_app.py")

requires_cache = pytest.mark.skipif(
    not CACHE_DB.exists(), reason="no local data cache (would hit the network)"
)
requires_models = pytest.mark.skipif(
    not (MODELS_DIR / "outcome.joblib").exists(), reason="models not trained"
)


def _page_script(page_call: str) -> str:
    """Script that imports the app (runs main once) then renders one page."""
    return (
        "import sys\n"
        f"sys.path.insert(0, {str(Path(APP).parent)!r})\n"
        "import streamlit_app as A\n"
        f"A.{page_call}\n"
    )


@requires_cache
def test_home_page_opens_with_content():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    titles = [t.value for t in at.title] + [t.value for t in at.sidebar.title]
    assert "🏀 NBA Insights" in titles  # brand now lives in the sidebar
    assert any("League pulse" in t for t in titles)  # page headline names the page
    assert len(at.metric) >= 4  # leader tiles render from cache
    assert not at.error


@requires_cache
def test_profile_search_builds_a_profile():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(_page_script("profile_page(A.get_client())"), default_timeout=180)
    at.run()
    at.text_input[0].set_value("LeBron James").run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.metric) >= 3  # header stat tiles


@requires_cache
def test_compare_page_quick_pick():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(_page_script("compare_page(A.get_client())"), default_timeout=180)
    at.run()
    quick = [b for b in at.button if b.label.startswith("Try ")]
    assert quick, "expected a leader quick-pick button on the empty state"
    quick[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.dataframe, "expected the comparison table"


@requires_cache
def test_games_page_opens_with_selectable_scores():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(_page_script("games_page(A.get_client())"), default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.dataframe, "expected the schedule or final-scores table"
    assert any("full box score" in str(c.value) for c in at.caption)


@requires_cache
@requires_models
def test_predictions_page_renders_all_tabs():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(
        _page_script("predictions_page(A.get_client())"), default_timeout=300
    )
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    # outcome tab renders the win-probability duel bar
    assert any("duel-track" in str(md.value) for md in at.markdown)
    labels = [m.label for m in at.metric]
    assert any("10,000 sims" in label for label in labels)  # simulate tab


@requires_cache
def test_season_outlook_page_renders():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(
        _page_script("season_outlook_page(A.get_client())"), default_timeout=300
    )
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    # projected standings for both conferences + the postseason odds table
    assert len(at.dataframe) >= 2
    assert any("Projected standings" in str(sh.value) for sh in at.subheader)
    assert any("Postseason odds" in str(sh.value) for sh in at.subheader)
