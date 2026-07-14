import pandas as pd
import pytest
from fastapi.testclient import TestClient

from nba_insights.api import app
from nba_insights.api.app import get_client

ALICE = {"id": 1, "full_name": "Alice Hooper", "is_active": True}
BOB = {"id": 2, "full_name": "Bob Rimson", "is_active": True}


class FakeNBAClient:
    def __init__(self):
        self.career = pd.DataFrame(
            {
                "SEASON_ID": ["2024-25", "2025-26"],
                "GP": [80, 50],
                "PTS": [2000, 1500],
                "AST": [400, 250],
                "REB": [600, 400],
            }
        )
        self.league = pd.DataFrame(
            {
                "PLAYER_NAME": ["Alice Hooper", "Bob Rimson", "Carol", "Dan"],
                "GP": [60, 58, 61, 55],
                "MIN": [36.0, 34.0, 30.0, 28.0],
                "PTS": [30.0, 25.0, 20.0, 15.0],
                "AST": [8.0, 6.0, 4.0, 2.0],
                "REB": [7.0, 9.0, 5.0, 11.0],
            }
        )

    def search_players(self, name):
        return [p for p in (ALICE, BOB) if name.lower() in p["full_name"].lower()]

    def career_stats(self, player_id):
        return self.career if player_id == 1 else pd.DataFrame()

    def league_player_stats(self, season=None, per_mode="PerGame"):
        return self.league


@pytest.fixture
def api():
    app.dependency_overrides[get_client] = FakeNBAClient
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_search(api):
    r = api.get("/players/search", params={"q": "alice"})
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "full_name": "Alice Hooper", "is_active": True}]


def test_search_query_too_short(api):
    assert api.get("/players/search", params={"q": "al"}).status_code == 422


def test_career_per_game(api):
    r = api.get("/players/1/career")
    assert r.status_code == 200
    seasons = r.json()
    assert seasons[0]["PTS"] == 25.0 and seasons[1]["PTS"] == 30.0


def test_career_unknown_player_404(api):
    assert api.get("/players/2/career").status_code == 404


def test_percentiles(api):
    r = api.get("/players/1/percentiles")
    assert r.status_code == 200
    body = r.json()
    assert body["player"] == "Alice Hooper"
    assert body["percentiles"]["PTS"] == 100.0


def test_percentiles_unknown_id_404(api):
    assert api.get("/players/99/percentiles").status_code == 404


def test_compare(api):
    r = api.get("/compare", params={"names": ["Alice Hooper", "Bob Rimson"]})
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["Alice Hooper"]["PTS"] == 30.0
    assert stats["Bob Rimson"]["REB"] == 9.0


def test_compare_missing_player_404(api):
    r = api.get("/compare", params={"names": ["Alice Hooper", "Zelda"]})
    assert r.status_code == 404


def test_card_html(api):
    r = api.get("/players/1/card")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Alice Hooper" in r.text
    assert "PTS / game" in r.text
    assert "League percentile" in r.text
