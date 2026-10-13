"""Pixel baselines for representative PWA charts.

Rendering depends on Chromium, fonts, and the rasterizer, so baselines are
only produced and compared inside the pinned Playwright container:

    scripts/visual-baselines.sh           # compare against tests/visual_baselines/
    scripts/visual-baselines.sh --update  # regenerate after an intended change

Outside the container (POSSESSION_LAB_VISUAL unset) these tests skip; the
structural chart checks in test_pwa_browser.py still run everywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

MODE = os.environ.get("POSSESSION_LAB_VISUAL", "")
if MODE not in {"check", "update"}:
    pytest.skip(
        "visual baselines run in the pinned container (scripts/visual-baselines.sh)",
        allow_module_level=True,
    )

from PIL import Image, ImageChops  # noqa: E402

from test_pwa_browser import (  # noqa: E402, F401  (fixtures are used by name)
    DESKTOP,
    PHONE,
    _open,
    base_url,
    browser,
)

BASELINES = Path(__file__).parent / "visual_baselines"
RESULTS = Path(__file__).resolve().parent.parent / "test-results" / "visual"
# A pixel "differs" when any channel moves by more than CHANNEL_TOLERANCE;
# the image fails when more than PIXEL_TOLERANCE of its pixels differ.
CHANNEL_TOLERANCE = 24
PIXEL_TOLERANCE = 0.002


def _open_profile(page, url):
    _open(page, url, "players")
    page.fill("#search", "Alice")
    page.click("#results button")


def _open_matchup(page, url):
    _open(page, url, "matchup")
    page.wait_for_selector("#home option[value='T2']", state="attached")
    page.select_option("#away", "T1")
    page.select_option("#home", "T2")
    page.click("#go")


SCENES = {
    "profile-league-standing": (_open_profile, "League standing"),
    "methodology-journey": (lambda page, url: _open(page, url, "methodology"), "Modeling journey"),
    "outlook-east-wins": (lambda page, url: _open(page, url, "outlook"), "East projected wins"),
    "matchup-drivers": (_open_matchup, "Why the prediction moved"),
}


def _difference(actual: Image.Image, expected: Image.Image) -> tuple[float, Image.Image]:
    delta = ImageChops.difference(actual.convert("RGB"), expected.convert("RGB"))
    mask = delta.convert("L").point(lambda value: 255 if value > CHANNEL_TOLERANCE else 0)
    changed = mask.histogram()[255]
    return changed / (mask.width * mask.height), mask


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("scene", sorted(SCENES))
def test_chart_matches_baseline(browser, base_url, scene, viewport):  # noqa: F811
    navigate, title = SCENES[scene]
    context = browser.new_context(viewport=viewport, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(20_000)
    navigate(page, base_url)
    figure = page.locator("figure.data-figure").filter(has_text=title).first
    figure.locator(".plot-host svg[aria-label]").first.wait_for()
    page.evaluate("document.fonts.ready.then(() => true)")
    figure.scroll_into_view_if_needed()
    page.mouse.move(1, viewport["height"] // 2)  # no hover tooltip in the shot
    shot = figure.screenshot(animations="disabled", caret="hide", scale="css")
    context.close()

    name = f"{scene}-{'desktop' if viewport is DESKTOP else 'phone'}.png"
    baseline = BASELINES / name
    if MODE == "update":
        BASELINES.mkdir(exist_ok=True)
        baseline.write_bytes(shot)
        return
    assert baseline.exists(), f"missing baseline {name}: run scripts/visual-baselines.sh --update"
    RESULTS.mkdir(parents=True, exist_ok=True)
    actual = Image.open(_bytes_path(RESULTS / name, shot))
    expected = Image.open(baseline)
    if actual.size != expected.size:
        pytest.fail(f"{name}: size {actual.size} != baseline {expected.size}")
    ratio, mask = _difference(actual, expected)
    if ratio > PIXEL_TOLERANCE:
        mask.save(RESULTS / name.replace(".png", "-diff.png"))
        pytest.fail(f"{name}: {ratio:.2%} of pixels differ (limit {PIXEL_TOLERANCE:.2%})")
    (RESULTS / name).unlink()


def _bytes_path(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path
