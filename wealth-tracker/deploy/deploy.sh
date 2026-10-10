#!/usr/bin/env bash
# Deploy the FastAPI/Next.js beta stack to the Pi — run this on your LAPTOP.
#
# Why not just rebuild on the Pi? The Pi has ~1.3Gi RAM and sits next to Immich
# and the live app; a Next.js build there risks the OOM-killer taking out
# running services. So we build the images on the Mac (also arm64) and ship
# them, then recreate the containers on the Pi *without* building.
#
# The Pi's GitHub deploy key is read-only, so this pushes from the laptop and
# the Pi only pulls (see deploy/update.sh, which this calls over SSH).
#
#   Usage (on the Mac):  ./deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Where it goes and where to look afterwards: override in the environment.
PI="${DEPLOY_HOST:?set DEPLOY_HOST to user@host of the Pi}"
SITE_URL="${SITE_URL:-https://stock-tracker.nl}"
TAG="${IMAGE_TAG:-local}"

echo "==> 1/4  Push code"
git push

echo "==> 2/4  Build images on the Mac (native arm64, matches the Pi)"
IMAGE_TAG="$TAG" APP_ENCRYPTION_KEY="${APP_ENCRYPTION_KEY:-build-only}" docker compose build api web

echo "==> 3/4  Ship images to the Pi (save | gzip | ssh 'docker load')"
docker save --platform linux/arm64 "stock-tracker-api:$TAG" "stock-tracker-web:$TAG" \
  | gzip -1 | ssh "$PI" 'gunzip | docker load'

echo "==> 4/4  Pull + recreate on the Pi (no build)"
ssh "$PI" "~/stock-tracker/deploy/update.sh"

echo "==> Done. Verify: $SITE_URL"
