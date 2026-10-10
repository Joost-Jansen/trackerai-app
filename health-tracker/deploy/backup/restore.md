# Restore

How to get the data back from the restic repository that `backup.sh` fills. Practise it into scratch containers once
after setting up, then twice a year (docs/SELF_HOSTING_PLAN.md section 6): a backup you never restored is a hope.

You need: the restic repository URL and password (password manager), the B2 keys, and for health-tracker the same
`APP_ENCRYPTION_KEY` and `TRAINING_JWT_SECRET` as before (otherwise users reconnect Garmin/Wahoo and set up two-step
login again, or log in again).

## 1. Fetch a snapshot

```bash
set -a; . /srv/backup/backup.env; set +a
restic snapshots --tag nightly                 # pick one; `latest` is the newest
mkdir -p /srv/restore && restic restore latest --target /srv/restore
ls /srv/restore/srv/backup/staging             # health/health.dump, stock/...
```

## 2. health-tracker (Postgres)

A test restore goes into a scratch container, never into the running database:

```bash
docker run -d --name pg-restore-test -e POSTGRES_PASSWORD=test postgres:16.15
sleep 5
docker exec -i pg-restore-test createdb -U postgres health
docker exec -i pg-restore-test pg_restore -U postgres -d health --no-owner < /srv/restore/srv/backup/staging/health/health.dump
docker exec pg-restore-test psql -U postgres -d health -c "select count(*) from users; select count(*) from activities;"
docker rm -f pg-restore-test
```

For real (the server died, or the database is damaged):

```bash
cd /srv/health
docker compose stop web
docker compose exec -T postgres dropdb -U health health
docker compose exec -T postgres createdb -U health health
docker compose exec -T postgres pg_restore -U health -d health --no-owner < /srv/restore/srv/backup/staging/health/health.dump
docker compose start web
curl -fsS http://127.0.0.1:8081/api/health      # through the edge's Tailscale listener; then log in and open Today
```

The app migrates an older schema itself at start-up, so a dump from an older version restores into a newer image.

## 3. stock-tracker (SQLite files)

```bash
cd /srv/stock
docker compose stop api
cp -a /srv/stock/data /srv/stock/data.before-restore          # keep what was there
cp -a /srv/restore/srv/backup/staging/stock/users/.            /srv/stock/data/users/
cp -a /srv/restore/srv/backup/staging/stock/feedback.db        /srv/stock/data/
cp -a /srv/restore/srv/backup/staging/stock/auth_config.yaml   /srv/stock/data/
cp -a /srv/restore/srv/backup/staging/stock/admin_audit.log    /srv/stock/data/ 2>/dev/null || true
rm -f /srv/stock/data/users/*/portfolio.db-wal /srv/stock/data/users/*/portfolio.db-shm   # the backups are complete files
chown -R 1000:1000 /srv/stock/data      # the user the api container runs as
docker compose start api
```

Check: log in, the portfolio and the bank transactions are there, one MCP read works. Then `rm -rf /srv/restore`.

## 4. After a restore

- Restore test passed: write the date in docs/SELF_HOSTING_PLAN.md (section 6).
- A real restore loses what happened after the snapshot (at most a day): users re-import what they uploaded since, and
  the Garmin sync fetches the missing days by itself.
