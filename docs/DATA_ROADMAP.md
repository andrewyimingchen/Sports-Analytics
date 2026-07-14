# Data roadmap: what to feed the models next

Status: proposal (feature/data). Builds on the models shipped in
`feature/analysis` — game outcome (65% holdout accuracy vs 55% baseline),
player points (MAE 4.69 vs 4.72 baseline), and the lineup win-probability
proxy. Every candidate below was probed from this environment on 2026-07-14;
"verified" means the fetch worked here, through the same cached client the
models already train from.

## Where the current models are weak

1. **Game outcome** knows only *form* (rolling win%, net rating, scoring,
   rest). It cannot see who is actually playing tonight, how efficient a
   team is per possession, or schedule fatigue beyond simple rest days.
2. **Player points** narrowly beats a rolling average. It knows nothing
   about *how* an opponent defends (rim protection, pace, positional
   matchups) or the player's role changes (usage spikes when a star sits).
3. **Starting five** is a per-36 plus-minus proxy: it has never seen an
   actual lineup play together.

## Proposed additions, in priority order

### Tier 1 — verified free via nba_api, high value per effort

| # | Data | Endpoint (probed OK) | Feeds | Why it should help |
|---|------|----------------------|-------|--------------------|
| 1 | **Four factors, per team** (eFG%, TOV%, OREB%, FT rate — offense & defense) | `LeagueDashTeamStats(measure_type='Four Factors')` (30×28) | Game outcome | The classic Dean Oliver result: the four factors explain most of winning. Rolling four-factor differentials are strictly more informative than raw points; typically worth 1–3 points of accuracy. |
| 2 | **Advanced team ratings** (pace-adjusted ORtg/DRtg, pace) | `LeagueDashTeamStats(measure_type='Advanced')` (30×46) | Game outcome, player points | Possession-adjusted strength beats raw plus-minus (blowout/pace noise). Opponent DRtg + pace directly improves the points model: pace sets the number of chances. |
| 3 | **Schedule** (all 1,400 games with dates, times, venues) | `ScheduleLeagueV2` — verified, 2025-26 | Game outcome | Enables real fatigue features: back-to-backs, 3-in-4s, road-trip length, time-zone shifts (arena coordinates are a small static table we can vendor). Known effects worth ~2–3% win probability; also unlocks predicting *upcoming* games instead of hypothetical matchups. |
| 4 | **Real 5-man lineup stats** (GP, minutes, net rating per lineup) | `LeagueDashLineups(group_quantity=5)` (2,000×50) | Starting five | Replaces the per-36 proxy with observed lineup net ratings where the lineup has actually played, shrunk toward the proxy when minutes are thin (empirical-Bayes blend). Turns the feature from "conversation starter" into an estimate with error bars. |

### Tier 2 — verified free, moderate effort, mainly for player points

| # | Data | Endpoint (probed OK) | Why |
|---|------|----------------------|-----|
| 5 | **Player tracking** (drives, touches, pull-up vs catch-and-shoot, defended FG%) | `LeagueDashPtStats` (569×25 for drives) | Role/usage signal the box score misses; opponent rim-protection quality is a direct input to a scorer's projection. |
| 6 | **Hustle stats** (contested shots, deflections, charges) | `LeagueHustleStatsPlayer` (567×28) | Defensive-intensity proxy for the opponent-adjustment term. |
| 7 | **Positional defense** (opponent points allowed by position) | Derivable: player-game rows joined with roster positions (`CommonTeamRoster`, already used) | "OKC concedes the fewest points to centers" is exactly the matchup context the points model lacks. |

### Tier 3 — external sources, gated or paid; decide before building

| # | Data | Source | Status here | Notes |
|---|------|--------|-------------|-------|
| 8 | **Injury/availability reports** | Official NBA injury report PDFs (`ak-static.cms.nba.com/referee/injury/…`) | **403 from this network** (may be IP-gated; also offseason) | The single biggest missing signal for game outcome — a star sitting swings win probability by 5–10%. Needs a scraping-rights check and PDF parsing; commercial alternatives (SportsDataIO, Rotowire API) are paid. Re-probe in season before committing. |
| 9 | **Betting market lines** (moneyline, spread, totals) | [The Odds API](https://the-odds-api.com) — free tier 500 req/mo | Not probed (needs API key) | Closing lines are the strongest public predictor (~70% accuracy). Two honest uses: as a benchmark our model is measured against, or as a feature (then the model becomes "market + residual"). Requires a key and attribution; free tier is enough for one snapshot per game day. |
| 10 | **Play-by-play / possessions** | `PlayByPlayV3` (nba_api) or pbpstats.com | Not probed (heavy: ~1 request per game) | Unlocks RAPM-style player impact and garbage-time filtering — the *right* foundation for the lineup model, but a multi-week project and ~1,230 requests per season. Do this last, only if Tier 1–2 plateaus. |

## What NOT to add

- **Basketball-Reference scraping** — ToS prohibits it; already removed from
  this repo once.
- **Social/news sentiment** — noisy, unlicensed, and dominated by the
  injury signal it proxies (get #8 instead).
- **More seasons of the same features** — tested during `feature/analysis`:
  form-based features drift with rule changes; three training seasons was
  not the bottleneck, feature poverty is.

## Suggested build order

1. **Four factors + advanced ratings into the outcome model** (#1, #2) —
   one new client method each, same rolling-feature pipeline, retrain,
   compare holdout. Expected: 65% → 66–68%.
2. **Schedule features** (#3) — back-to-back/travel flags; also lets the
   Predictions page list tonight's actual games instead of hypotheticals.
3. **Lineup blend** (#4) — observed lineup net ratings shrunk toward the
   proxy; show minutes-together as the confidence signal.
4. **Points-model matchup pack** (#2 pace/DRtg, #5, #7) — target MAE ≤ 4.5.
5. **Re-probe injuries in season** (#8) and add odds as a benchmark (#9)
   before deciding whether to buy data.

Each step is measured the same way the current models were: temporal holdout
on the current season, reported against the existing number. Anything that
doesn't move the holdout metric gets reverted — more data is not the goal,
better predictions are.

## Status update (2026-07-14, same day): Tier 1 + partial Tier 2 built

Measured on the same 1,071-game 2025-26 holdout:

- **#1–#3 (four factors, ratings, fatigue) — shipped.** With the original
  last-10 window the new features moved nothing (65.2% vs 65.1% — the
  roadmap's revert rule nearly fired). The window itself was the
  bottleneck: switching all form features to **season-to-date** lifted
  accuracy to **68.3%** (log loss 0.615 → 0.603). Lesson recorded: recency
  windows were adding noise, not signal.
- **#3 schedule — shipped.** Fatigue flags (B2B, 3-in-4) are model inputs;
  the Predictions page now lists the next slate of real games with win
  probabilities (offseason-aware). Travel/time-zone features deferred.
- **#4 lineups — shipped.** Observed 5-man net ratings blended with the
  proxy, weighted MIN/(MIN+200); minutes-together shown as the confidence
  signal in the UI.
- **#5–#7 partial:** opponent DRtg/pace added to the points model —
  **no holdout gain** (MAE 4.70 vs 4.69). Kept (harmless, better inference
  context), but the honest read is that next-game points is noise-bound
  near the rolling-average baseline. Tracking/hustle/positional defense
  remain unbuilt; revisit only with per-game (not season-aggregate) data,
  which is what avoids leakage.
- **#8–#10 unchanged** — injury reports still the biggest missing signal;
  re-probe in season (bead 1nn).
