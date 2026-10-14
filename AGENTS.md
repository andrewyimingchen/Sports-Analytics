# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
uv sync --all-groups                         # deps, dev tools, browser-test group
uv run pytest                                # tests (no network needed)
uv run ruff check .                          # lint
uv run uvicorn nba_insights.api:app --port 8000   # the product (PWA at /app/)
uv run streamlit run app/streamlit_app.py    # internal console only
scripts/preflight.sh                         # every CI gate; run before handoff
```

For the session-close "run quality gates" step, use `scripts/preflight.sh`
(`--quick` skips the browser suite). `bd preflight` in bd 1.1.0 only checks
Beads' own Go repository (go test, golangci-lint, version.go, Nix), so it
does not apply to this project.

## Architecture Overview

`src/nba_insights/` is a layered package: `ingest/` (NBAClient — the only code
that touches the network; rate-limited nba_api wrapper), `store/` (SQLite
DataFrame cache with per-endpoint TTLs; empty responses never cached), and
`analysis/` (pure pandas functions — no I/O). The FastAPI-served PWA (`api/`) is
the product; `app/streamlit_app.py` is an internal research console.
See README.md for details.

## Conventions & Patterns

- Analysis functions are pure: DataFrames in, DataFrames out, raise KeyError on
  missing players/columns. Keep them network-free so tests stay offline.
- All remote fetches go through `Cache.get_or_fetch`; never call nba_api
  endpoints directly from the app layer.
- Column names follow stats.nba.com conventions (PTS, GP, SEASON_ID, ...).
- Scraping public reference pages (e.g. Basketball-Reference contracts) is
  permitted by owner decision (2026-07-16), accepting the ToS tension, under
  these guardrails: minimal volume (single pages, long TTLs, always through
  `Cache.get_or_fetch`), personal/educational use only, and scraped data must
  never be exposed through the public API/PWA or redistributed. Licensed
  providers (e.g. BALLDONTLIE) remain the path for anything commercial.

## Codex Harness

Read by the global Claude+Codex harness: the `codex-review` skill
(`~/.claude/skills/codex-review`) and `codex-worker` (`~/.local/bin`), via
`codex-harness-config`. Keep one `- Key:` line per setting, with
the value in backticks.

- Base: `main`
- Setup: `uv sync --all-groups --frozen`
- Check: `scripts/preflight.sh --quick`
- Review focus:
  - Network access outside `ingest/` (NBAClient), or remote fetches that bypass `Cache.get_or_fetch`
  - I/O or network calls inside `analysis/` functions, which must stay pure and offline-testable
  - Empty or error responses being cached, or wrong per-endpoint TTLs in `store/`
  - Scraped data (e.g. Basketball-Reference) reaching the public API/PWA
  - Column names that break stats.nba.com conventions (PTS, GP, SEASON_ID, ...)
  - PWA/service-worker changes that serve stale data without saying so in the UI

Workflow: Claude plans and integrates; Codex reviews and takes clearly specified
tickets. Run `codex-review` before opening any PR. Only label a beads issue
`agent:codex` when it has acceptance criteria and needs no product decisions;
`codex-worker .` claims those in isolated worktrees and labels the results
`codex:review` (green) or `codex:failed`.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
