# Deployment

The FastAPI-served PWA is the official POSSESSION LAB product. Streamlit is an
internal analytics console and is not part of the production image.

The app is designed local-first, and one upstream fact dominates every
deployment decision: **stats.nba.com blocks most datacenter IPs.** A fresh
container on a typical cloud host cannot fetch data at all. The cache-first
architecture is the mitigation — everything the app shows comes from
`data/cache.sqlite3`, and finished-season entries never expire — so the
deployment problem reduces to *shipping a warmed cache*.

## The warmed-cache workflow

On a machine that can reach stats.nba.com (a residential connection works):

```bash
uv sync
uv run python -m nba_insights.warm --top 20          # league dashboards + top players
uv run python -m nba_insights.ml.train               # fetches + caches 4 seasons, trains models
uv run python -m nba_insights.ml.backtest --seasons 2024-25 2025-26   # season-forecast registry
uv run python -m nba_insights.pbp.backfill --seasons 2025-26          # optional: game stories
```

Then copy `data/` (cache + `models/`) to the deployment target, and commit
the updated `models/manifest.json` so the deployed record matches the
artifacts. The app serves everything from cache and degrades gracefully when
refresh fetches fail: current-season entries are served stale, and the
response's `degraded` list says which sections are missing and why.

During the season, re-warm nightly from the same machine (the README's cron
line runs `nba_insights.warm`) and sync the cache up. In WAL mode a plain
file copy can miss entries still in `cache.sqlite3-wal`, so ship a
consistent snapshot instead:

```bash
sqlite3 data/cache.sqlite3 ".backup data/cache-snapshot.sqlite3"
```

then replace the target's cache with the snapshot while its server is
stopped (see [Processes and the shared cache](#processes-and-the-shared-cache)).

## Options

| Option | Verdict |
|---|---|
| **Self-host on a residential IP** (home server, Tailscale/Cloudflare Tunnel for access) | Best fit: the app can fetch for itself; zero cache choreography |
| **VPS / container platform + warmed cache volume** | Works; data is as fresh as your last cache sync (offseason: perfectly fine) |
| **Free PaaS with an ephemeral filesystem** | Expect first-fetch failures (blocked IPs) and a cache that resets on every reboot. Not recommended without a persistent volume and the warmed-cache sync |

The official product is the FastAPI-served PWA. Run it directly with:

```bash
uv run uvicorn nba_insights.api:app --host 0.0.0.0 --port 8000
```

## Docker

A CI-built `Dockerfile` serves FastAPI and the installable PWA as a non-root
user. `/app/data` is a volume: mount your warmed cache and model artifacts into
it. The build context excludes local data, credentials, caches, internal
Streamlit code, and development tooling.

```bash
docker build -t possession-lab .
docker run --name possession-lab -p 8000:8000 \
  -v "$PWD/data:/app/data" possession-lab
```

Open `http://127.0.0.1:8000/app/`. Liveness and readiness probes are available
at `/healthz` and `/readyz`; readiness reports optional model availability but
does not fail when artifacts are absent because the product provides explicit
degraded states. Model artifacts are gitignored, so train them before mounting
the data volume. Without them prediction cards show a "models not trained"
notice and the rest of the product remains available.

The image ships the tracked `models/manifest.json`. `/methodology/manifest`
compares its recorded SHA-256 hashes with the mounted artifacts and reports
`verified`, or `drift` with each artifact marked `match`, `mismatch`, or
`missing`. After retraining, commit the updated manifest so the deployed
record describes the artifacts you mount.

## Scheduling the nightly pipeline

`python -m nba_insights.pipeline` is the scheduled job. It must run where
stats.nba.com is reachable (usually the machine that warms the cache, not a
cloud CI runner). Each run executes these steps:

| Step | What it does | Status |
|---|---|---|
| `warm` | Refreshes league dashboards and the top players | `degraded` if any fetch failed |
| `pbp` (`--pbp`) | Extends the current season's play-by-play corpus (game stories, stint lineups) | `degraded` if any game failed |
| `retrain` | Retrains when the last training run is `--retrain-days` old (default 7): re-scores the holdout and records the run in `models/manifest.json` | `skipped` until due |
| `drift` | Scores the shipped outcome model on the current season's completed games (pre-game features only) and writes `data/models/drift.json`, served at `/methodology/drift` | `degraded` on drift |

Models are fit on completed seasons only, so retraining does not change them
within a season; live calibration is what watches the shipped model.

**Alerts.** A run exits 1 and logs `ALERT` when:
- a step fails;
- the drift verdict fires (recent 28-day log loss above the holdout's by more than two standard errors, once 100+ games are in);
- a step has been degraded or failed three runs in a row.

Set `POSSESSION_LAB_ALERT_WEBHOOK` to a Slack-compatible incoming-webhook URL
to also post the alert text. Every run appends one JSON line to
`data/pipeline.jsonl` (steps, statuses, durations, alerts).

**Run it from a dedicated checkout, never a development one.** A scheduled
job executes whatever is checked out when it fires, and a plain `uv run`
installs whatever the lockfile on that branch asks for, unattended. Keep a
clean "runner" checkout of `main`, run it with `--frozen --no-sync`, and point
it at the data the API serves through `NBA_INSIGHTS_DATA_DIR` and
`NBA_INSIGHTS_MANIFEST`:

```bash
git worktree add --detach ~/possession-lab-runner origin/main   # once
uv --directory ~/possession-lab-runner sync --frozen
```

To update the runner later, a deliberate step after reviewing what changed:

```bash
git -C ~/possession-lab-runner fetch origin
git -C ~/possession-lab-runner checkout --detach origin/main
uv --directory ~/possession-lab-runner sync --frozen
```

**systemd user timer (recommended; no root).** Templates live in
[`deploy/systemd/`](../deploy/systemd/); edit the two `NBA_INSIGHTS_*` paths
in the service to your API checkout, then:

```bash
mkdir -p ~/.config/systemd/user ~/.config/possession-lab ~/possession-lab-backups
cp deploy/systemd/possession-lab-pipeline.{service,timer} ~/.config/systemd/user/
chmod 700 ~/.config/possession-lab ~/possession-lab-backups
install -m 600 /dev/null ~/.config/possession-lab/env   # optional webhook goes here
systemctl --user daemon-reload
systemctl --user enable --now possession-lab-pipeline.timer
loginctl enable-linger "$USER"     # run while logged out
systemctl --user start --no-block possession-lab-pipeline   # first run now; follow it:
journalctl --user -u possession-lab-pipeline -f
```

Notes:
- `ExecStart` uses the absolute path to `uv`: systemd does not read your
  shell profile, so `~/.local/bin` is not on its `PATH`.
- Put `POSSESSION_LAB_ALERT_WEBHOOK=...` in `~/.config/possession-lab/env`
  (mode 600), never in the unit file or the repository; anyone holding the
  URL can post to the channel.
- Keep backups on a private Linux path. They include the cache, which holds
  scraped pages that must not be redistributed; under WSL, `/mnt/c` ignores
  Linux permissions and may be synced by OneDrive.
- **WSL:** the timer only fires while the WSL VM is running, and Windows stops
  it when idle. `Persistent=true` runs a missed job at the next start, and
  the freshness check (below) flags anything over 36 hours.
- A weekly retrain rewrites the tracked `models/manifest.json` in the API
  checkout; commit that change through a PR.

Or with cron, using the same runner and flags (non-zero exits are mailed by
most cron setups):

```cron
0 6 * * * cd ~/possession-lab-runner && NBA_INSIGHTS_DATA_DIR=/srv/Sports-Analytics/data NBA_INSIGHTS_MANIFEST=/srv/Sports-Analytics/models/manifest.json ~/.local/bin/uv run --frozen --no-sync python -m nba_insights.pipeline --pbp
```

If the API runs on another host, sync the cache afterwards (see the warmed-cache
workflow above) and copy `data/models/` so `/methodology/drift` stays current.

## Monitoring and backups

**Error tracking (optional).** Set `SENTRY_DSN` and the API reports
unexpected 500s (`internal_error`) to Sentry; the production image includes
the `monitoring` extra (`uv sync --extra monitoring` elsewhere). Events carry
no personal data: query strings, cookies, and `X-API-Key`/`Authorization`
headers are stripped. Optional: `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`,
`SENTRY_TRACES_SAMPLE_RATE` (default 0, errors only).

**Uptime and freshness.** `/healthz` is liveness. `/readyz` adds model
availability, failure counts by reason, and `data_freshness`: when the
nightly pipeline last finished and whether that is `stale` (over 36 hours;
readiness itself stays `ready`). Point any uptime monitor at `/readyz`, or
run the bundled check from a different machine:

```bash
uv run python -m nba_insights.ops check https://lab.example.com --max-stale-hours 36
```

It exits 1 (and posts to `POSSESSION_LAB_ALERT_WEBHOOK` when set) if the
service is unreachable, not ready, or its data is stale.

**Backups.** Add `--backup DIR` to the nightly pipeline, or run it alone:

```bash
uv run python -m nba_insights.ops backup --dest /backups/possession-lab --keep 14
```

Each backup is a timestamped directory with an online SQLite copy of the
cache (consistent while the API and pipeline run, unlike a file copy in WAL
mode, and checked with `PRAGMA quick_check`), the model artifacts,
`models/manifest.json`, the pipeline run log, and `backup.json` with SHA-256
hashes. Only complete backups are kept; the newest `--keep` survive.

To restore: stop every process using the cache, copy the backup's
`cache.sqlite3` to `data/` (delete any leftover `cache.sqlite3-wal` and
`-shm` first), copy `models/` to `data/models/`, start the API, and confirm
`/methodology/manifest` reports `verified`.

## Processes and the shared cache

The supported model is **one host, one local cache file, any number of
processes**: several Uvicorn workers (`--workers N`), the Streamlit console,
and warm/backfill jobs may all share `data/cache.sqlite3`.

- The cache runs in SQLite WAL mode, so readers never block the writer, and
  every connection waits up to 30 seconds for a lock instead of failing with
  "database is locked".
- A cache miss is fetched once across processes. A per-key POSIX lock on
  `data/cache.sqlite3.lock` makes other processes wait for the first
  fetch and then read its result, instead of each calling stats.nba.com.
  On Windows (no `fcntl`) the guarantee is per process only, so expect up
  to one duplicate fetch per process on a cold key.
- Keep the file on a **local filesystem**. NFS/SMB and most container
  volume drivers backed by network storage break both WAL and POSIX locks.
  The cache logs a warning when WAL cannot be enabled.
- Multiple hosts must not share one cache file; give each host its own
  warmed copy.

**Recovering from lock or corruption problems.** The cache is rebuildable
and never the source of truth:

1. Stop every process using it (API workers, Streamlit, warm jobs).
2. If startup or reads report `database disk image is malformed`, move
   `cache.sqlite3`, `cache.sqlite3-wal`, and `cache.sqlite3-shm` aside.
   Do not delete only the `-wal` file: it may hold committed entries.
3. Re-run `uv run python -m nba_insights.warm` (and the play-by-play
   backfill if you use game stories) to rebuild it.

`cache.sqlite3.lock` holds no data and can be deleted while nothing is running.

## Remote API safeguards

Localhost callers can use all locally configured features without a POSSESSION
LAB API key. Remote AI and salary/contract access is denied unless
`POSSESSION_LAB_API_KEY` is configured and supplied through `X-API-Key` or an
`Authorization: Bearer` header. Remote simulations are weighted against a
per-client compute budget and can optionally require the same key.

| Variable | Default | Purpose |
|---|---:|---|
| `POSSESSION_LAB_API_KEY` | unset | Secret for remote AI/private-data access |
| `POSSESSION_LAB_REQUIRE_API_KEY` | `false` | Require the key for simulations |
| `POSSESSION_LAB_SIMULATION_BUDGET` | `100000` | Simulated games allowed per client/window |
| `POSSESSION_LAB_AI_REQUEST_BUDGET` | `5` | AI calls allowed per client/window |
| `POSSESSION_LAB_RATE_WINDOW_SECONDS` | `60` | Sliding budget window |
| `POSSESSION_LAB_TRUSTED_PROXY_IPS` | unset | Comma-separated immediate proxies whose forwarded client IP is trusted |

An untrusted forwarding header removes local-only privilege rather than
granting it. Configure trusted proxy IPs explicitly and separately restrict
which proxies Uvicorn accepts forwarding headers from. Do not put the API key
in PWA source code: a browser-facing reverse proxy or authenticated gateway
should add it after authorizing the user. The application limiter is
per-process; enforce a shared rate limit at that gateway when running multiple
workers.
