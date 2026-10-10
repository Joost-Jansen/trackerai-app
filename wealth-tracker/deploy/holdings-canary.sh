#!/usr/bin/env bash
# Weekly canary over the ETF holdings sources -- pushes to ntfy when one of
# the issuer sites has changed shape and stopped delivering holdings.
#
# Why: a dead source does not raise. issuer_holdings returns None, the ETF
# analysis silently falls back to a Yahoo top-10 estimate, and the app keeps
# working with worse numbers. The iShares UK rebuild sat there unnoticed
# exactly like that. This is the thing that notices.
#
# Runs the check inside the api container: it holds the app's own code and
# dependencies, so the canary exercises the very fetchers the app uses rather
# than a copy that could drift. It calls the low-level fetchers, bypassing the
# 7-day SQLite cache that would otherwise mask a fresh break for a week.
#
# Silent when everything is fine (same rule as watchtower's notifications --
# an alert that fires every run is an alert you stop reading), with one
# exception: the first successful run of each calendar month also pushes a
# quiet "still alive". Without it, "no notification" and "the cron entry is
# gone / the Pi is off" look identical from the phone. It rides along with a
# run that was going to happen anyway, so it costs no extra requests.
#
# Install: 0 6 */2 * * /path/to/stock-tracker/deploy/holdings-canary.sh
# (STOCK_TRACKER_DIR overrides where the checkout is; default: this script's repo.)
set -uo pipefail

REPO="${STOCK_TRACKER_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG="$REPO/holdings-canary.log"
HEARTBEAT_STATE="$REPO/.holdings-canary-month"
ts() { date "+%Y-%m-%d %H:%M:%S"; }

# NTFY_TOPIC_URL lives in the gitignored .env next to the tunnel token -- the
# topic is the only access control on a public ntfy.sh topic, so it is never
# committed. Unset simply means "log only, don't push".
NTFY_TOPIC_URL=""
# shellcheck disable=SC1091
[ -f "$REPO/.env" ] && . "$REPO/.env"

cd "$REPO" || exit 1

OUTPUT=$(docker compose exec -T api sh -c \
  'cd /app && PYTHONPATH=/app/backend python deploy/check_holdings_sources.py' 2>&1)
RC=$?

echo "$(ts) canary rc=$RC" >> "$LOG"
echo "$OUTPUT" >> "$LOG"

notify() {   # notify <title> <priority> <tags> <body>
  if [ -z "$NTFY_TOPIC_URL" ]; then
    echo "$(ts) NTFY_TOPIC_URL not set in .env -- no push sent" >> "$LOG"
    return
  fi
  curl -sS -H "Title: $1" -H "Priority: $2" -H "Tags: $3" -d "$4" \
    "$NTFY_TOPIC_URL" >> "$LOG" 2>&1
  echo "" >> "$LOG"
}

if [ "$RC" -eq 0 ]; then
  # Monthly "still alive". Recorded only after the push is attempted, so a
  # month is never marked done by a run that failed to report.
  THIS_MONTH=$(date "+%Y-%m")
  if [ "$THIS_MONTH" != "$(cat "$HEARTBEAT_STATE" 2>/dev/null)" ]; then
    notify "ETF-holdings canary" "low" "white_check_mark" \
      "$(echo "$OUTPUT" | tail -n 1)
Monthly sign of life -- the canary is still running."
    echo "$THIS_MONTH" > "$HEARTBEAT_STATE"
  fi
  exit 0
fi

# Failure. Push the "N of M ... broken" block, starting at the summary line --
# that count is the first thing you want to read on a phone, and a plain
# tail would push it off the top as soon as more than ~14 sources are down
# (which is precisely the interesting case: one site takes out many funds).
# Falls back to the tail when the report never got that far, e.g. because
# docker itself failed and the output is an error message instead.
BODY=$(echo "$OUTPUT" | sed -n '/broken:/,$p' | head -n 14)
[ -z "$BODY" ] && BODY=$(echo "$OUTPUT" | tail -n 15)
notify "ETF-holdings canary" "high" "warning,chart_with_downwards_trend" "$BODY"

exit "$RC"
