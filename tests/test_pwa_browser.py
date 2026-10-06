"""Browser checks for the PWA chart system (desktop and phone widths).

Runs the real FastAPI app against the offline fake client in a background
uvicorn server and drives it with Playwright Chromium. Skipped when
Playwright or its browser is not installed; CI runs it in the ``browser``
job (``uv sync --group browser`` + ``playwright install chromium``).
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from nba_insights.api import app  # noqa: E402
from nba_insights.api.app import get_client  # noqa: E402
from test_api import FakeNBAClient  # noqa: E402

DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 390, "height": 844}

# Every visible chart must name itself, say what to take away, expose an
# accessible SVG label, and (when it has one) keep its data one action away.
FIGURE_AUDIT = """() => [...document.querySelectorAll('figure.data-figure')]
  .filter((figure) => figure.offsetParent !== null)
  .map((figure) => ({
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
  }))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    app.dependency_overrides[get_client] = FakeNBAClient
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
        assert figure["summaries"] == (1 if figure["tables"] else 0), figure
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
