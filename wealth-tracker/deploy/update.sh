#!/usr/bin/env bash
# Pi-side half of a deploy: pull the code and recreate the beta containers from
# images that were ALREADY built on the Mac and shipped here (see deploy.sh).
#
# It deliberately does NOT build. The Pi cannot build the Next.js image without
# risking the OOM-killer next to Immich and the live app — so `--no-build`, and
# always the named services (a bare `docker compose --profile pi up` would also
# start a second `cloudflared`, a duplicate of the production tunnel).
#
# Run from the Mac via deploy/deploy.sh, or by hand once new images are loaded:
#   ssh <user>@<pi> "~/stock-tracker/deploy/update.sh"
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose --profile pi up -d --no-build api web beta-proxy
docker image prune -f
