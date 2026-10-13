#!/usr/bin/env bash
# Compare (default) or regenerate (--update) the PWA chart pixel baselines
# inside the pinned Playwright container, so local runs and CI render with
# the same Chromium, fonts, and rasterizer. Requires Docker.
#
#   scripts/visual-baselines.sh            # compare; diffs land in test-results/visual/
#   scripts/visual-baselines.sh --update   # rewrite tests/visual_baselines/*.png
set -euo pipefail
cd "$(dirname "$0")/.."

mode=check
[[ "${1:-}" == "--update" ]] && mode=update

# Keep the image tag in step with the playwright version in uv.lock.
version=$(awk '/^name = "playwright"$/{getline; gsub(/[^0-9.]/, ""); print; exit}' uv.lock)
image="mcr.microsoft.com/playwright/python:v${version}-noble"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --ipc=host \
  -e HOME=/tmp \
  -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -e POSSESSION_LAB_VISUAL="$mode" \
  -v "$PWD:/work" -w /work \
  "$image" \
  bash -c 'pip install --quiet --user uv \
    && ~/.local/bin/uv sync --frozen --quiet --group browser \
    && ~/.local/bin/uv run --frozen pytest -q -p no:cacheprovider tests/test_pwa_visual.py'
