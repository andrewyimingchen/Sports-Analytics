# Tracking and hustle availability audit

Audited against the official stats.nba.com dashboards through the installed
`nba_api` client on 2026-07-22, using the completed 2025-26 regular season and
player scope. Every category was available; each response is cached through the
same immutable-finished-season policy as the rest of POSSESSION LAB.

| Product category | Official measure / endpoint | Rows | Audited fields |
|---|---|---:|---|
| Drives | `LeagueDashPtStats` / `Drives` | 582 | drives, attempts, accuracy, points, passes, assists, turnovers, fouls |
| Touches | `LeagueDashPtStats` / `Possessions` | 582 | touches, frontcourt/paint/post/elbow touches, possession time, dribbles, points per touch |
| Passing | `LeagueDashPtStats` / `Passing` | 582 | passes made/received, assists, secondary/potential assists, points created |
| Rim defense | `LeagueDashPtStats` / `Defense` | 582 | defended rim makes, attempts, and FG% |
| Speed and distance | `LeagueDashPtStats` / `SpeedDistance` | 582 | total/offensive/defensive miles and average speed |
| Hustle | `LeagueHustleStatsPlayer` | 581 | contests, deflections, charges, screen assists, loose balls, box-outs |

Team scope was also verified: Drives and Hustle each returned all 30 teams.
The team Hustle response omits team tricode and games played; POSSESSION LAB
joins the tricode from the same-season team-game cache and leaves the games
sample explicitly unavailable, so the minimum-games filter is not falsely
applied to that category.

The API returns a schema audit on every request. If stats.nba.com removes a
field or blocks a category, that category returns an explicit `unavailable`
or `empty` source state while other categories continue to render. Tracking
metrics are descriptive and depend on the NBA's optical-tracking definitions;
they should not be interpreted as complete measures of player value or defense.
