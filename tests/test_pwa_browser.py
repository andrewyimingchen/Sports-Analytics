"""Browser checks for the PWA chart system (desktop and phone widths).

Runs the real FastAPI app against the offline fake client in a background
uvicorn server and drives it with Playwright Chromium. Skipped when
Playwright or its browser is not installed; CI runs it in the ``browser``
job (``uv sync --group browser`` + ``playwright install chromium``).
"""

from __future__ import annotations

import importlib
import socket
import threading
import time

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

import pandas as pd  # noqa: E402

from nba_insights.api import app  # noqa: E402
from nba_insights.api.app import (  # noqa: E402
    get_client,
    get_outcome_model,
    get_points_model,
    get_win_curve,
)
from nba_insights.ml import GameOutcomeModel  # noqa: E402
from nba_insights.ml.features import game_matchup_frame, team_form_features  # noqa: E402
from test_api import FakeCurve, FakeNBAClient, FakePointsModel  # noqa: E402
from test_ml import synthetic_team_games  # noqa: E402

# The module, not the FastAPI object the package re-exports as `app`.
api_module = importlib.import_module("nba_insights.api.app")

# Same shape as test_api's season-forecast fixture; replaces the simulator.
SEASON_TABLE = pd.DataFrame(
    {
        "TEAM": ["T1", "T2", "T3", "T4"],
        "CONFERENCE": ["East", "East", "West", "West"],
        "PROJECTED_SEED": [1.2, 2.1, 1.1, 2.4],
        "PROJECTED_WINS": [55.0, 48.0, 58.0, 45.0],
        "PROJECTED_LOSSES": [27.0, 34.0, 24.0, 37.0],
        "PLAYOFF_PROB": [0.95, 0.8, 0.97, 0.7],
        "CHAMP_PROB": [0.25, 0.1, 0.4, 0.05],
        "CUP_PROB": [0.2, 0.1, 0.3, 0.1],
        "CUP_GROUP": ["East A", "East A", "West A", "West A"],
        "CUP_PROJECTED_GROUP_RANK": [1.2, 2.0, 1.1, 2.4],
        "CUP_GROUP_WIN_PROB": [0.7, 0.3, 0.8, 0.2],
        "CUP_WILD_CARD_PROB": [0.1, 0.2, 0.1, 0.1],
        "CUP_KNOCKOUT_PROB": [0.8, 0.5, 0.9, 0.3],
        "CUP_FINAL_PROB": [0.4, 0.2, 0.5, 0.1],
    }
)

DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 390, "height": 844}

# Every visible chart must name itself, say what to take away, expose an
# accessible SVG label, keep its exact data one action away, and never tell
# legend entries apart by colour alone (distinct dot shapes or direct labels).
FIGURE_AUDIT = """() => [...document.querySelectorAll('figure.data-figure')]
  .filter((figure) => figure.offsetParent !== null)
  .map((figure) => {
    const legend = [...figure.querySelectorAll('[class*="-swatch"]:not([class*="-swatches"])')]
      .map((swatch) => swatch.textContent.trim()).filter(Boolean);
    const plots = [...figure.querySelectorAll('.plot-host svg[aria-label]')];
    const shapes = new Set(plots.flatMap((svg) =>
      [...svg.querySelectorAll('g[aria-label="dot"] path')].map((path) => path.getAttribute('d'))));
    const text = plots.map((svg) => svg.textContent).join(' ');
    return {
    legend,
    colourOnly: legend.length >= 2 && shapes.size < legend.length
      && !legend.every((label) => text.includes(label)),
    title: figure.querySelector('.figure-heading h4')?.textContent.trim() || '',
    takeaway: figure.querySelector('.figure-heading p')?.textContent.trim() || '',
    svgs: figure.querySelectorAll('.plot-host svg[aria-label]').length,
    unlabeled: [...figure.querySelectorAll('.plot-host svg')]
      .filter((svg) => !svg.getAttribute('aria-label') && !svg.closest('[class*="-swatch"]')
        && !svg.closest('[class*="-legend"]')).length,
    tables: figure.querySelectorAll(
      'details.viz-data table, details.viz-data [role="table"]').length,
    summaries: figure.querySelectorAll('details.viz-data > summary').length,
    width: figure.getBoundingClientRect().width,
  }; })"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    app.dependency_overrides[get_client] = FakeNBAClient
    matchups = game_matchup_frame(team_form_features(synthetic_team_games(60), window=5))
    outcome = GameOutcomeModel().fit(matchups)
    app.dependency_overrides[get_outcome_model] = lambda: outcome
    app.dependency_overrides[get_points_model] = FakePointsModel
    app.dependency_overrides[get_win_curve] = FakeCurve
    patches = pytest.MonkeyPatch()
    patches.setattr(api_module, "_season_forecast_table", lambda *args: SEASON_TABLE)
    patches.setattr(api_module, "get_player_season_metrics", lambda: {"metrics": {"players": 241}})
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            pytest.fail("test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/app/"
    server.should_exit = True
    thread.join(timeout=10)
    patches.undo()
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch()
        except Exception as error:  # browser binary not installed
            pytest.skip(f"Chromium unavailable: {error}")
        yield chromium
        chromium.close()


@pytest.fixture(params=[DESKTOP, PHONE], ids=["desktop", "phone"])
def page(request, browser):
    context = browser.new_context(viewport=request.param, reduced_motion="reduce")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_default_timeout(20_000)
    yield page
    context.close()
    assert not errors, errors


def _open(page, base_url: str, view: str) -> None:
    page.goto(f"{base_url}?view={view}#{view}")


def _audit(page, minimum: int) -> list[dict]:
    labeled = "figure.data-figure .plot-host svg[aria-label]"
    page.wait_for_function(f"document.querySelectorAll('{labeled}').length >= {minimum}")
    figures = page.evaluate(FIGURE_AUDIT)
    assert len(figures) >= minimum, figures
    for figure in figures:
        assert figure["title"] and figure["takeaway"], figure
        assert figure["svgs"] >= 1 and figure["unlabeled"] == 0, figure
        assert figure["tables"] >= 1 and figure["summaries"] == 1, figure
        assert not figure["colourOnly"], figure
    assert page.evaluate(OVERFLOW) <= 0, "page scrolls horizontally"
    return figures


def _pick(page, field: str, query: str) -> None:
    page.fill(f"#{field}", query)
    page.click(f"#{field}-results button")


def test_player_profile_charts(page, base_url):
    _open(page, base_url, "players")
    page.fill("#search", "Alice")
    page.click("#results button")
    page.wait_for_selector("#split-viz figure")
    titles = {figure["title"] for figure in _audit(page, 4)}
    assert {"Career arc", "League standing"} <= titles
    assert any(title.startswith("Splits by") for title in titles)
    assert "octagon" not in page.content().lower()


def test_compare_charts(page, base_url):
    _open(page, base_url, "compare")
    _pick(page, "compare-a", "Alice")
    _pick(page, "compare-b", "Bob")
    page.click("#compare-go")
    # the career chart needs two players with career seasons; the fake has one
    titles = {figure["title"] for figure in _audit(page, 1)}
    assert "At-a-glance skill profile" in titles
    assert "radar" not in page.content().lower()


def test_team_room_charts(page, base_url):
    _open(page, base_url, "teams")
    page.wait_for_selector("#team-pick option[value='T1']", state="attached")
    page.select_option("#team-pick", "T1")
    titles = {figure["title"] for figure in _audit(page, 2)}
    assert {"Where they win", "Four factors"} <= titles


def test_tracking_charts_follow_metric_selector(page, base_url):
    _open(page, base_url, "tracking")
    page.wait_for_selector("#tracking-leader-chart figure")
    _audit(page, 1)
    options = page.eval_on_selector_all("#tracking-metric option", "els => els.map(e => e.value)")
    if len(options) > 1:
        page.select_option("#tracking-metric", options[1])
        heading = page.text_content("#tracking-leader-chart h4")
        assert options[1].replace("_", " ") in heading


def test_game_story_charts(page, base_url):
    _open(page, base_url, "games")
    page.click(".game-row[data-game-id='001']")  # the fake's final game with a timeline
    titles = {figure["title"] for figure in _audit(page, 2)}
    assert {"Game flow", "How the game was won"} <= titles


def test_methodology_charts(page, base_url):
    _open(page, base_url, "methodology")
    titles = {figure["title"] for figure in _audit(page, 1)}
    assert "Modeling journey" in titles


def test_exact_data_is_keyboard_reachable(page, base_url):
    _open(page, base_url, "players")
    page.fill("#search", "Alice")
    page.click("#results button")
    summary = page.locator("#profile-trend-chart details.viz-data > summary")
    summary.focus()
    assert page.evaluate("document.activeElement.tagName") == "SUMMARY"
    page.keyboard.press("Enter")
    table = page.locator("#profile-trend-chart details.viz-data table")
    assert table.is_visible()
    assert table.locator("caption").inner_text()
    assert table.locator("thead th[scope='col']").count() >= 2


def test_chart_libraries_are_served_locally(page, base_url):
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    _open(page, base_url, "pulse")
    page.wait_for_function("Boolean(window.Plot && window.d3)")
    external = [url for url in requests if not url.startswith(base_url.rsplit("/app/", 1)[0])]
    assert not external, external
    # web fonts resolve from the stylesheets' own location and all load
    page.evaluate("document.fonts.ready.then(() => true)")
    fonts = [url for url in requests if url.endswith(".ttf")]
    assert fonts, "no web fonts were requested"
    assert all("/app/fonts/" in url for url in fonts), fonts
    statuses = page.evaluate(
        "[...document.fonts].map((face) => `${face.family} ${face.weight} ${face.status}`)"
    )
    assert any(status.endswith("loaded") for status in statuses), statuses
    assert not [status for status in statuses if status.endswith("error")], statuses


def test_shell_and_charts_load_offline_after_first_visit(browser, base_url):
    context = browser.new_context(viewport=DESKTOP)
    page = context.new_page()
    page.goto(f"{base_url}?view=offline#pulse")
    # wait for the worker to install (precaching the shell), then let it take control
    assert page.evaluate("navigator.serviceWorker.ready.then(() => true)")
    page.reload()
    page.wait_for_function("navigator.serviceWorker.controller !== null")
    context.set_offline(True)
    page.reload()
    page.wait_for_function("Boolean(window.Plot && window.d3)")
    assert "POSSESSION LAB" in page.title()
    assert page.locator("#page-pulse").count() == 1
    context.close()


def test_explore_chart(page, base_url):
    _open(page, base_url, "explore")
    titles = {figure["title"] for figure in _audit(page, 1)}
    assert any(" by " in title for title in titles)


def test_season_outlook_charts(page, base_url):
    _open(page, base_url, "outlook")
    titles = {figure["title"] for figure in _audit(page, 4)}
    assert {"East projected wins", "Playoff probability", "Championship probability"} <= titles


def test_matchup_charts(page, base_url):
    _open(page, base_url, "matchup")
    page.wait_for_selector("#home option[value='T2']", state="attached")
    page.select_option("#away", "T1")
    page.select_option("#home", "T2")
    page.click("#go")
    titles = {figure["title"] for figure in _audit(page, 2)}
    assert {"Same-sample league ranks", "Why the prediction moved"} <= titles


def test_tapping_a_point_shows_its_tooltip_on_touch_phones(browser, base_url):
    context = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    page = context.new_page()
    _open(page, base_url, "players")
    page.fill("#search", "Alice")
    page.click("#results button")
    chart = "#profile-pct-chart .plot-host svg[aria-label]"
    page.wait_for_selector(chart)
    dot = page.locator(f'{chart} g[aria-label="dot"] circle').first
    dot.scroll_into_view_if_needed()
    tip = page.locator(f'{chart} g[aria-label="tip"]')
    assert "percentile" not in (tip.text_content() or "")  # nothing shown before the tap
    box = dot.bounding_box()
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_function(
        "(sel) => document.querySelector(sel)?.textContent.includes('percentile')",
        arg=f'{chart} g[aria-label="tip"]',
    )
    assert _tip_contrast(page, f'{chart} g[aria-label="tip"]') >= 4.5
    context.close()


def _tip_contrast(page, selector: str) -> float:
    """WCAG contrast between a Plot tip's text and the box drawn behind it."""
    return page.evaluate(
        """(sel) => {
          const tip = document.querySelector(sel);
          const rgb = (value) => {
            const probe = document.createElement('div');
            probe.style.color = value;
            document.body.append(probe);
            const parts = getComputedStyle(probe).color.match(/[\\d.]+/g).slice(0, 3).map(Number);
            probe.remove();
            return parts;
          };
          const luminance = (color) => {
            const [r, g, b] = color.map((channel) => {
              const c = channel / 255;
              return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * r + 0.7152 * g + 0.0722 * b;
          };
          const box = rgb(getComputedStyle(tip.querySelector('path')).fill);
          const text = rgb(getComputedStyle(tip.querySelector('text')).fill);
          const [hi, lo] = [luminance(box), luminance(text)].sort((a, b) => b - a);
          return (hi + 0.05) / (lo + 0.05);
        }""",
        selector,
    )


@pytest.mark.parametrize("nav", [".desktop-nav", ".mobile-nav"])
def test_primary_navigation_updates_page_url_and_current_item(browser, base_url, nav):
    viewport = DESKTOP if nav == ".desktop-nav" else PHONE
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    page.goto(base_url)
    for target in ("players", "games", "matchup", "more", "pulse"):
        page.click(f'{nav} [data-page="{target}"]')
        assert page.locator(f"#page-{target}").get_attribute("class").split().count("active") == 1
        assert page.locator(f'{nav} [data-page="{target}"]').get_attribute("aria-current") == "page"
        assert page.evaluate("location.hash") == ("" if target == "pulse" else f"#{target}")
        assert page.locator(".page.active").count() == 1
    # secondary pages open from the More hub and keep More current
    page.click(f'{nav} [data-page="more"]')
    page.click('#page-more [data-page="outlook"]')
    assert page.evaluate("location.hash") == "#outlook"
    assert page.locator(f'{nav} [data-page="more"]').get_attribute("aria-current") == "page"
    context.close()


def test_player_deep_link_opens_profile_and_stays_shareable(page, base_url):
    page.goto(f"{base_url}#players/1")
    page.wait_for_selector("#profile .profile-identity h2")
    assert page.text_content("#profile .profile-identity h2") == "Alice Hooper"
    assert page.locator("#page-players").get_attribute("class").split().count("active") == 1
    assert page.evaluate("location.hash") == "#players/1"
    # a link pasted into the open tab routes without a reload
    page.evaluate("location.hash = '#players/999'")
    page.wait_for_selector("#profile >> text=Player not found")
    # opening a profile from search rewrites the URL to that profile
    page.fill("#search", "Alice")
    page.click("#results button")
    page.wait_for_function("location.hash === '#players/1'")


def test_unknown_hash_falls_back_to_league_pulse(page, base_url):
    page.goto(f"{base_url}#not-a-page/7")
    assert page.locator("#page-pulse").get_attribute("class").split().count("active") == 1


def test_forecast_tables_expose_every_team_in_order(page, base_url):
    _open(page, base_url, "outlook")
    _audit(page, 4)
    east = page.locator("#outlook-east-chart details.viz-data")
    east.locator("summary").click()
    rows = east.locator('[role="row"]:not(.header)')
    assert rows.count() == 2  # T1 and T2 play in the East
    assert "T1" in rows.first.text_content()
    title = page.locator("#outlook-title-chart details.viz-data")
    title.locator("summary").click()
    teams = title.locator("tbody th").all_text_contents()
    assert teams == ["T3", "T1", "T2", "T4"]  # sorted by title probability


def _flow_pulse(page, base_url):
    _open(page, base_url, "pulse")
    page.wait_for_selector("#pulse-content .leader-card")


def _flow_profile(page, base_url):
    _open(page, base_url, "players")
    page.fill("#search", "Alice")
    page.click("#results button")
    page.wait_for_selector("#split-viz figure")


def _flow_compare(page, base_url):
    _open(page, base_url, "compare")
    _pick(page, "compare-a", "Alice")
    _pick(page, "compare-b", "Bob")
    page.click("#compare-go")
    page.wait_for_selector("#compare-skill-chart figure")


def _flow_team(page, base_url):
    _open(page, base_url, "teams")
    page.wait_for_selector("#team-pick option[value='T1']", state="attached")
    page.select_option("#team-pick", "T1")
    page.wait_for_selector("#team-factor-chart figure")


def _flow_game(page, base_url):
    _open(page, base_url, "games")
    page.click(".game-row[data-game-id='001']")
    page.wait_for_selector("#game-flow-chart figure")


def _flow_matchup(page, base_url):
    _open(page, base_url, "matchup")
    page.wait_for_selector("#home option[value='T2']", state="attached")
    page.select_option("#away", "T1")
    page.select_option("#home", "T2")
    page.click("#go")
    page.wait_for_selector("#matchup-rank-chart figure")


def _flow_outlook(page, base_url):
    _open(page, base_url, "outlook")
    page.wait_for_selector("#outlook-title-chart figure")


PRIMARY_FLOWS = {
    "pulse": _flow_pulse,
    "profile": _flow_profile,
    "compare": _flow_compare,
    "team": _flow_team,
    "game": _flow_game,
    "matchup": _flow_matchup,
    "outlook": _flow_outlook,
}


@pytest.mark.parametrize("flow", PRIMARY_FLOWS)
def test_primary_flows_have_no_serious_accessibility_violations(page, base_url, flow):
    axe_sync = pytest.importorskip("axe_playwright_python.sync_playwright")
    PRIMARY_FLOWS[flow](page, base_url)
    violations = axe_sync.Axe().run(page).response["violations"]
    # Moderate issues (heading levels) are tracked separately; these block.
    blocking = [
        f"{v['id']} ({v['impact']}): {[node['target'] for node in v['nodes'][:3]]}"
        for v in violations
        if v["impact"] in ("serious", "critical")
    ]
    assert not blocking, blocking
