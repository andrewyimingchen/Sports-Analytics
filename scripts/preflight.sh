#!/usr/bin/env bash
# Repository pre-PR / session-close gates for POSSESSION LAB.
#
#   scripts/preflight.sh          # run every gate
#   scripts/preflight.sh --quick  # skip the slow browser suite
#
# `bd preflight` (bd 1.1.0) only knows Beads' own Go repository (go test,
# golangci-lint, version.go, Nix), so it does not apply here; this script
# runs the gates CI enforces. Exits non-zero if any gate fails.
set -uo pipefail

cd "$(dirname "$0")/.."

quick=false
[[ "${1:-}" == "--quick" ]] && quick=true

results=()
failed=0

gate() {
  local name="$1"
  shift
  printf '\n== %s\n' "$name"
  if "$@"; then
    results+=("PASS  $name")
  else
    results+=("FAIL  $name")
    failed=1
  fi
}

skip() {
  results+=("SKIP  $1 ($2)")
}

gate "Lockfile current (uv lock --check)" uv lock --check
gate "Ruff lint" uv run --frozen ruff check .
gate "Ruff format" uv run --frozen ruff format --check .
gate "Mypy" uv run --frozen mypy
if $quick; then
  gate "Pytest (without browser suite)" uv run --frozen pytest -q --ignore=tests/test_pwa_browser.py
  skip "Browser suite" "--quick"
else
  # browser tests skip silently without Playwright; make that a failure here
  gate "Playwright available" uv run --frozen python -c "import playwright.sync_api"
  gate "Pytest (full, incl. browser suite)" uv run --frozen pytest -q
fi
gate "Service worker syntax" node --check src/nba_insights/api/static/sw.js
if [[ -d node_modules ]]; then
  gate "PWA lint (eslint)" npm run -s lint
  gate "PWA unit tests" npm test --silent
else
  skip "PWA lint and unit tests" "run npm ci first"
fi
gate "README metrics match models/manifest.json" \
  uv run --frozen python -m nba_insights.ml.manifest readme --check
gate "AGENTS.md / CLAUDE.md in sync" bash -c \
  '[[ -L CLAUDE.md && "$(readlink CLAUDE.md)" == "AGENTS.md" ]] || cmp -s AGENTS.md CLAUDE.md'

printf '\n== Git status\n'
git status --short --branch

printf '\n== Summary\n'
printf '%s\n' "${results[@]}"
exit "$failed"
