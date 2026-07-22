# Streamlit → PWA parity

The FastAPI PWA mirrors every user-visible Streamlit surface. The two clients
share pure analysis functions, the cached `NBAClient`, and trained artifacts;
the PWA receives JSON rather than duplicating calculations in JavaScript.

| Streamlit surface | PWA equivalent |
|---|---|
| League Pulse: seasons, leaders, Elo/form, offense-defense landscape, slate | League Pulse with historical selector, leader cards, form/Elo index, SVG landscape, and rest-aware next slate |
| Player: career, ratings, scouting, position context | Player Lab profile and season-aware deep analytics |
| Player shots: raw, zone-vs-league, hex hot zones, xeFG, shot diet | Three selectable SVG court modes plus quality tiles and range table |
| Player on/off, splits, games, similar players | Player Lab impact, situation table, recent form, and comps |
| Player/team salary and contracts | Local-request-only contract and payroll sections |
| Explore filters, per-game/per-36, CSV | Explore page and browser-generated CSV |
| Compare 2–4: career, seasons, percentiles, shot quality, poster | Four search slots and all comparison sections with PNG poster link |
| Teams: identity, factors, roster, games, standings, lineups, on/off | Team Room consolidated profile |
| Games: seasons, filters, full box score | Game Center; every row opens a summary and finals use cached team-grouped player rows with a traditional endpoint fallback |
| Predictions: outcome, absences, simulator, points, starting five | Matchup Lab with roster-aware current/upcoming-season forecasts, East/West record ranges, playoff/title/Cup odds, auditable roster/minutes deltas, an accessible five-slot lineup picker, and three advanced prediction cards |
| Team-vs-team explanation | Shared-cutoff comparison of results, efficiency, four factors, shooting, rotations, bench, clutch, and head-to-head context with ranked local model contributions, caveats, share links, and JSON export |
| Roster/injury/trade scenarios | Ephemeral Scenario Lab with duplicate/minute/roster validation, multi-player trade packages, advisory cached-salary checks, and paired before/after wins, seeds, playoff/title/Cup odds without changing the baseline |
| Tracking, hustle, defense, personalization | Player/team Drives, Touches, Passing, Shot Defense, Speed/Distance, and Hustle views with explicit definitions, season/team/games filters, upstream schema and cache freshness, shareable URLs, browser-local favorites, and permission-gated local refresh notifications |
| Methodology | Methodology page backed by recorded artifact metrics |
| Ask (AI) | Ask the League page; credential remains server-side |

The Draft implementation remains intentionally hidden in Streamlit at the
owner's request, so it is not part of visible-feature parity. Salary data is
for local personal use and is never returned to non-loopback callers. Missing
optional AI credentials or trained model files produce explanatory states.
