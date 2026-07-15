# Product Roadmap — from repo to product

An honest assessment of what stands between this codebase and a real product.
The code is the smallest gap; the existential issues are **data rights** and
**who the customer is**. Everything else is ordinary engineering that can be
sequenced after those two.

## 1. Data licensing (decides whether this can be a product at all)

Everything flows from `nba_api`, which uses stats.nba.com's unofficial
endpoints. That is fine for personal and educational use, but:

- The NBA's terms do not permit commercial redistribution of the data.
- Player headshots hotlink NBA's CDN.
- Team names and logos are trademarks — as is "NBA" itself, so a commercial
  version needs a rename ("NBA Insights" will not survive contact with a
  lawyer).

A real product needs a licensed feed:

| Provider | Notes |
|---|---|
| Sportradar | The NBA's official data distributor |
| SportsDataIO | Cheaper tier, common for indie products |
| Stats Perform | Enterprise-oriented |

Expect hundreds to low thousands of dollars per month. The architecture
already isolates ingestion behind `NBAClient` (the only code that touches the
network), so swapping providers is contained to one layer.

## 2. Product definition

Who pays — fantasy players, bettors, or fans? The answer changes everything
downstream.

Be clear-eyed about the models: 70.2% holdout accuracy is roughly *market*
level (closing lines hit ~70%). The sellable asset is not edge over Vegas —
it is:

- **Transparency** — the methodology page (protocol, negative results, live
  calibration) is genuinely unusual in this space.
- **The projections UX** — player points, lineups, daily slate.
- **The API** — developers paying for projections is a plausible first market.

Regulatory posture: if predictions are marketed toward betting, that inherits
responsible-gambling disclaimers and jurisdiction questions. "Analytics tool"
is a much lighter posture than "picks service."

## 3. Automated pipeline

Today: training is a manual CLI, the cache fills on demand, and there is no
injury feed at prediction time (the known open lever in DATA_ROADMAP.md).
A product needs a scheduled worker that:

- Ingests every night (schedule, game logs, play-by-play).
- Retrains / re-scores on a fixed cadence with versioned model artifacts.
- Tracks calibration drift over time — the curve is already computed for the
  methodology page; log it per week and alert on degradation.
- Pulls injury reports before tipoff instead of relying on the manual
  "who's out" picker.

Predictions are identical for every user: **precompute the daily slate once
and serve it statically.** That also slashes serving cost.

## 4. Serving infrastructure

The 630 MB SQLite cache and Streamlit are single-user by design. The product
path is the existing FastAPI + PWA:

- Postgres instead of SQLite for the cache/store.
- A Dockerfile and a deploy target (Fly/Render/Railway to start).
- CD on top of the existing CI.
- Keep Streamlit as the internal/analyst tool; grow the PWA into the
  consumer face.

## 5. Accounts, billing, API productization

Only if/when something is worth charging for:

- Auth + user accounts.
- Stripe, plans.
- API keys and rate limits if the API itself is the product.

## 6. The boring-but-mandatory list

- **LICENSE** — the repo has none; right now nobody can legally even fork it.
- Terms of service, privacy policy.
- "Not gambling advice" disclaimer.
- Error tracking (e.g. Sentry), uptime monitoring.
- Database backups.

## Suggested sequencing

1. Validate §2 with the free/personal version first: ship the PWA publicly as
   a portfolio-grade beta and measure whether anyone returns weekly.
2. Only pay for §1 (licensed data) once something suggests people would pay.
3. §3–§6 are each a week or two of work, not months — sequence them behind
   real demand.
