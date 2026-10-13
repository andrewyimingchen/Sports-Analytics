# Testing

All suites run offline against fixtures; none of them touch stats.nba.com.

| Suite | Command | Notes |
|---|---|---|
| Unit, API, and Streamlit smoke tests | `uv run pytest` | The default run; includes the browser suite when Playwright is installed (`uv sync --all-groups && uv run playwright install chromium`) |
| PWA browser checks | `uv run pytest tests/test_pwa_browser.py` | Chart semantics and accessible labels, phone layout, keyboard and touch interaction, tooltip contrast, offline shell |
| PWA chart pixel baselines | `scripts/visual-baselines.sh` | Needs Docker; see below |
| PWA lint and unit tests | `npm ci && npm run lint && npm test` | ESLint and `node --test` over `tests/js/` |

## Chart pixel baselines

`tests/test_pwa_visual.py` screenshots representative charts (player league
standing, modeling journey, season outlook, matchup drivers) at 1280px and
390px and compares them with the PNGs in `tests/visual_baselines/`.

Pixels depend on Chromium, fonts, and the rasterizer, so baselines are only
produced and compared inside the official Playwright container whose version
matches `playwright` in `uv.lock`. `scripts/visual-baselines.sh` runs that
container for you; outside it the visual tests skip, so a plain `uv run
pytest` never flakes on rendering differences. CI runs the same script in the
`visual` job.

```bash
scripts/visual-baselines.sh            # compare against the committed baselines
scripts/visual-baselines.sh --update   # regenerate after an intended visual change
```

A comparison fails when more than 0.2% of an image's pixels differ by more
than 24 levels in any channel. On failure the actual screenshot and a
difference mask are written to `test-results/visual/` (uploaded as the
`visual-diffs` artifact in CI). Review them, and if the change is intended,
run `--update` and commit the new PNGs together with the change that caused
them.

When `playwright` is upgraded in `uv.lock`, the container tag follows it
automatically; regenerate the baselines in the same change, because a new
Chromium can shift anti-aliasing.
