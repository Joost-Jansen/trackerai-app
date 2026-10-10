#!/usr/bin/env bash
# Nightly backup of both apps on the home server (cron, e.g. `0 3 * * * /srv/backup/backup.sh >> /var/log/backup.log 2>&1`):
#   health-tracker  pg_dump -Fc of its Postgres (run inside the postgres container: no port is published)
#   stock-tracker   a consistent sqlite3 .backup of every user database and feedback.db (WAL-safe, while it runs),
#                   plus auth_config.yaml, admin_audit.log and the users' uploads
# then `restic backup` of that staging folder, `restic forget --prune` (7 daily, 4 weekly, 12 monthly) and `restic check`.
#
# Configuration: /srv/backup/backup.env (or BACKUP_ENV=<file>), see backup.env.example. Needs on the host: bash,
# docker, sqlite3, restic. Exits non-zero on any failure, so cron mails it / a monitor sees it.
set -Eeuo pipefail
umask 077

ENV_FILE="${BACKUP_ENV:-/srv/backup/backup.env}"
[[ -f "$ENV_FILE" ]] && set -a && . "$ENV_FILE" && set +a

: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY (e.g. b2:bucket:/home-server)}"
: "${RESTIC_PASSWORD_FILE:=${RESTIC_PASSWORD:+}}"
HEALTH_PG_CONTAINER="${HEALTH_PG_CONTAINER:-health-postgres}"
HEALTH_PG_USER="${HEALTH_PG_USER:-health}"
HEALTH_PG_DB="${HEALTH_PG_DB:-health}"
STOCK_DATA_DIR="${STOCK_DATA_DIR:-/srv/stock/data}"            # holds users/<name>/portfolio.db, feedback.db, ...
STOCK_AUTH_CONFIG="${STOCK_AUTH_CONFIG:-$STOCK_DATA_DIR/auth_config.yaml}"
STAGING="${BACKUP_STAGING:-/srv/backup/staging}"
KEEP="${RESTIC_KEEP:---keep-daily 7 --keep-weekly 4 --keep-monthly 12}"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }
trap 'log "FAILED at line $LINENO"' ERR

rm -rf "$STAGING"
mkdir -p "$STAGING/health" "$STAGING/stock"

# --- health-tracker ---------------------------------------------------------------------------------------------
if [[ "${SKIP_HEALTH:-}" != "1" ]]; then
  log "health-tracker: pg_dump"
  docker exec "$HEALTH_PG_CONTAINER" pg_dump -U "$HEALTH_PG_USER" -d "$HEALTH_PG_DB" -Fc --no-owner > "$STAGING/health/health.dump"
  # a dump that pg_restore cannot list is no backup
  docker exec -i "$HEALTH_PG_CONTAINER" pg_restore --list > /dev/null < "$STAGING/health/health.dump"
fi

# --- stock-tracker ----------------------------------------------------------------------------------------------
if [[ "${SKIP_STOCK:-}" != "1" ]]; then
  log "stock-tracker: sqlite backups from $STOCK_DATA_DIR"
  shopt -s nullglob
  for db in "$STOCK_DATA_DIR"/users/*/portfolio.db "$STOCK_DATA_DIR"/feedback.db; do
    rel="${db#"$STOCK_DATA_DIR"/}"
    mkdir -p "$STAGING/stock/$(dirname "$rel")"
    sqlite3 "$db" ".backup '$STAGING/stock/$rel'"
    [[ "$(sqlite3 "$STAGING/stock/$rel" 'PRAGMA integrity_check;')" == "ok" ]] || { log "integrity check failed: $rel"; exit 1; }
  done
  for f in "$STOCK_AUTH_CONFIG" "$STOCK_DATA_DIR/admin_audit.log"; do
    [[ -f "$f" ]] && cp -p "$f" "$STAGING/stock/"
  done
  for up in "$STOCK_DATA_DIR"/users/*/uploads; do
    rel="${up#"$STOCK_DATA_DIR"/}"
    mkdir -p "$STAGING/stock/$rel"
    cp -a "$up/." "$STAGING/stock/$rel/"
  done
fi

# --- restic -----------------------------------------------------------------------------------------------------
log "restic backup"
restic backup --host home-server --tag nightly "$STAGING"
log "restic forget --prune"
# shellcheck disable=SC2086  # KEEP is a list of flags
restic forget --host home-server --tag nightly --prune $KEEP
log "restic check"
restic check --read-data-subset=5%

rm -rf "$STAGING"
log "done"
