# REVIEW.md

Guidance for AI reviewers (`/code-review`, `/security-review`, Codex, PR
bots). Project context lives in AGENTS.md; this file says what matters when
reviewing a diff here.

## What failure looks like here

- **The API lies.** An endpoint returns NaN/Infinity (invalid JSON), drops a
  column the PWA reads, or serves stale data as fresh. Responses must go
  through `finite_records` (or equivalent) so missing values become `null`.
- **The cache poisons itself.** An empty or error response gets cached, a
  fetch bypasses `Cache.get_or_fetch`, or a TTL change makes a hot endpoint
  hit the network on every request.
- **Analysis does I/O.** Anything under `src/nba_insights/analysis/` that
  touches the network, disk, or clock. Those functions are pure and raise
  `KeyError` on missing players/columns.
- **Scraped data leaks.** Anything from `ingest/salaries.py` (or any other
  scraped source) reachable from `api/` or the PWA. Owner decision
  2026-07-16: scraped data is never exposed publicly or redistributed.
- **The PWA goes stale.** A change to shell files in `api/static/` without
  bumping `SHELL_CACHE` in `sw.js`, so installed clients keep old code.
- **Docs drift.** README metrics no longer match `models/manifest.json`, or
  AGENTS.md/README describe behaviour the code no longer has.
- **Tests stop being offline.** A test that needs the network, or a browser
  test that silently skips instead of failing.

## Priorities

1. Correctness bugs and wrong numbers shown to users
2. Security (`api/security.py`, request validation, anything echoing input)
3. The failure modes above
4. Missing tests for a behaviour change

## Limits

- Report at most 3 nits per review. Do not comment on formatting or import
  order; ruff handles it. Do not comment on types mypy already checks.
- Tag every finding **important**, **nit**, or **pre-existing** (a bug the
  diff did not introduce).
- After two review rounds on the same PR, review only the new diff.

## Skip

- `uv.lock`, `package-lock.json`, `mobile/package-lock.json`
- `models/`, `data/`, `tests/visual_baselines/`
- `src/nba_insights/api/static/vendor/`, `src/nba_insights/api/static/fonts/`
- `.beads/`

## Evidence

Every finding cites a file and line and quotes the code. Do not infer a bug
from a name alone; trace the call. If unsure, say so instead of asserting.

## Summary format

Start with the count, e.g. "1 important, 2 nits". If there is nothing to
fix, say "No issues found" and stop.
