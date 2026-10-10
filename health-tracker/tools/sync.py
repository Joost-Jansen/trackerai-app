"""Fetch new Garmin and Strava data into data/, then rebuild routes/ and summary/.

    python tools/sync.py                      # incremental, both sources
    python tools/sync.py --since 2025-06-01   # backfill
    python tools/sync.py --source strava

Credentials come only from the environment (Railway variables on the `sync` service):
    STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN, GARMINTOKENS
When TOKEN_OUT_DIR is set, refreshed tokens that changed are written there so the
workflow can update the secrets. Tokens are never printed or written into the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import db, store
from tools.derive import derive
from tools.fit import read_fit_streams
from tools.secretbox import WrongKey, decrypt, default_key, encrypt
from tools import wahoo
from tools.sports import garmin_sport
from tools.intraday import intraday_from_garmin, night_summary
from tools.store import from_garmin, from_strava, garmin_summary, wellness_from_garmin

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKFILL_DAYS = 90
# Intraday series (tools/intraday.py) the first time (new feature): two weeks back, so recent nights are there right
# away. Further back with an explicit backfill (--since, or a new user's first sync), but never more than
# INTRADAY_MAX_DAYS: one row is 25-30 kB and four extra Garmin calls per day.
INTRADAY_FIRST_DAYS = 14
INTRADAY_MAX_DAYS = 90
# The watch uploads through the phone, often hours late: the evening and night of yesterday can reach Garmin after
# a sync that already fetched yesterday. Every sync fetches this many days before today again.
REFETCH_DAYS = 1
STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_STREAM_KEYS = "time,latlng,heartrate,velocity_smooth,altitude,cadence,distance,watts"


class RateLimited(Exception):
    """The API asked us to slow down; progress so far is kept and the next run continues."""


def fetch_metric(stats: dict, name: str, fn, day: str):
    """Call one Garmin wellness endpoint; count ok / empty / errors so the log shows why a metric is missing."""
    counts = stats.setdefault(name, {})
    try:
        value = fn(day)
    except RateLimited:
        raise
    except Exception as err:  # a device may not support every metric
        key = f"fout {type(err).__name__}"
        counts[key] = counts.get(key, 0) + 1
        return None
    key = "ok" if value else "leeg"
    counts[key] = counts.get(key, 0) + 1
    return value


def today_report(values: dict, series: dict | None) -> str:
    """What today's sync brought in, for the log. Garmin answers a day the watch has not uploaded yet with empty
    responses (counted "ok" above), so without this the log cannot tell that apart from a day with data."""
    last = max((pts[-1][0] for k, pts in (series or {}).items() if k != "sleep" and isinstance(pts, list) and pts), default=None)
    if not values and last is None:
        return "nog niets bij Garmin (horloge nog niet gesynchroniseerd met Garmin Connect)"
    out = f"{len(values)} dagwaarden"
    if last is not None:
        out += f", laatste meting {last // 60:02d}:{last % 60:02d}"
    return out


class FileSink:
    """Legacy target: JSON files in the repo (data/)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def upsert_activity(self, record: dict) -> str:
        return str(store.upsert_activity(self.root, record))

    def delete_garmin_activity(self, garmin_id, day: str) -> None:
        store.delete_activity_by_source(self.root, "garmin", garmin_id, day)

    def write_wellness(self, day: str, values: dict) -> None:
        store.write_wellness(self.root, day, values)

    def write_intraday(self, day: str, values: dict) -> None:
        pass  # the file mode keeps only the daily summaries

    def get_fit(self, garmin_id, year: str) -> bytes | None:
        path = self.root / self.fit_key(garmin_id, year)
        return path.read_bytes() if path.exists() else None

    def put_fit(self, garmin_id, year: str, data: bytes) -> str:
        path = self.root / self.fit_key(garmin_id, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.fit_key(garmin_id, year)

    @staticmethod
    def fit_key(garmin_id, year: str) -> str:
        return f"data/raw/fit/{year}/{garmin_id}.zip"


class DbSink:
    """Target: one user's data in the training database (tools/db.py)."""

    def __init__(self, scope: db.Scope):
        self.engine = scope  # name kept for the methods below: every db call is scoped to this user

    def upsert_activity(self, record: dict) -> str:
        return db.upsert_activity(self.engine, record)

    def delete_garmin_activity(self, garmin_id, day: str) -> None:
        db.delete_activity_by_source(self.engine, "garmin", garmin_id, day)

    def write_wellness(self, day: str, values: dict) -> None:
        db.write_wellness(self.engine, day, values)

    def write_intraday(self, day: str, values: dict) -> None:
        db.write_intraday(self.engine, day, values)

    def get_fit(self, garmin_id, year: str) -> bytes | None:
        return db.get_fit(self.engine, self.fit_key(garmin_id, year))

    def put_fit(self, garmin_id, year: str, data: bytes) -> str:
        db.put_fit(self.engine, self.fit_key(garmin_id, year), data)
        return self.fit_key(garmin_id, year)

    @staticmethod
    def fit_key(garmin_id, year: str) -> str:
        return f"garmin-{garmin_id}"


def as_sink(target):
    return FileSink(target) if isinstance(target, (str, Path)) else target


def _epoch(iso_utc: str) -> int:
    return int(datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).timestamp())


def write_rotated_token(out_dir: Path | None, name: str, old: str | None, new: str | None) -> None:
    if not out_dir or not new or new == old:
        return
    path = Path(out_dir) / name
    path.write_text(new)
    path.chmod(0o600)


# --- Strava -------------------------------------------------------------------------


class StravaClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        import requests

        self._http = requests.Session()
        r = self._http.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        self.refresh_token = body["refresh_token"]
        self._http.headers["Authorization"] = f"Bearer {body['access_token']}"

    def _get(self, path: str, **params):
        r = self._http.get(f"{STRAVA_API}{path}", params=params, timeout=60)
        if r.status_code == 429:
            raise RateLimited("Strava rate limit")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def list_activities(self, after_epoch: int) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._get("/athlete/activities", after=after_epoch, per_page=100, page=page) or []
            out += batch
            if len(batch) < 100:
                return out
            page += 1

    def streams(self, activity_id: int) -> dict | None:
        return self._get(f"/activities/{activity_id}/streams", keys=STRAVA_STREAM_KEYS, key_by_type="true")


def sync_strava(target, client, state: dict, since: date | None = None) -> int:
    sink = as_sink(target)
    s = state.setdefault("strava", {})
    if "last_start_epoch" not in s:
        start = since or date.today() - timedelta(days=DEFAULT_BACKFILL_DAYS)
        s["last_start_epoch"] = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    elif since:
        s["last_start_epoch"] = min(s["last_start_epoch"], int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp()))

    activities = sorted(client.list_activities(s["last_start_epoch"]), key=lambda a: a["start_date"])
    for activity in activities:
        streams = client.streams(activity["id"])  # may raise RateLimited; progress so far is kept
        sink.upsert_activity(from_strava(activity, streams))
        s["last_start_epoch"] = _epoch(activity["start_date"])
    return len(activities)


# --- Garmin -------------------------------------------------------------------------


class GarminClient:
    def __init__(self, tokens: str):
        from garminconnect import Garmin

        self._Garmin = Garmin
        self.api = Garmin()
        self.api.login(tokens)
        self.stats: dict = {}
        self._sleep: tuple[str, dict | None] = ("", None)  # the last day's sleep, shared by wellness() and intraday()

    def _call(self, fn, *args, **kwargs):
        from garminconnect import GarminConnectTooManyRequestsError

        try:
            return fn(*args, **kwargs)
        except GarminConnectTooManyRequestsError as err:
            raise RateLimited("Garmin rate limit") from err

    def activities(self, start: date, end: date) -> list[dict]:
        return self._call(self.api.get_activities_by_date, start.isoformat(), end.isoformat(), None, "asc")

    def splits(self, activity_id) -> dict:
        return self._call(self.api.get_activity_splits, str(activity_id))

    def activity(self, activity_id) -> dict:
        """One activity from the detail endpoint (summaryDTO, metadataDTO.childIds for a multisport)."""
        return self._call(self.api.get_activity, str(activity_id))

    def fit(self, activity_id) -> bytes:
        return self._call(self.api.download_activity, str(activity_id), dl_fmt=self._Garmin.ActivityDownloadFormat.ORIGINAL)

    def wellness(self, day: str) -> dict:
        def get(name, fn):
            return fetch_metric(self.stats, name, lambda d: self._call(fn, d), day)

        sleep = get("slaap", self.api.get_sleep_data)
        self._sleep = (day, sleep)
        return wellness_from_garmin(
            sleep=sleep,
            hrv=get("hrv", self.api.get_hrv_data),
            summary=get("dagoverzicht", self.api.get_user_summary),
            readiness=get("readiness", self.api.get_training_readiness),
        )

    def intraday(self, day: str) -> dict:
        """The day's series (heart rate, stress with Body Battery, respiration, SpO2; shapes in
        tools/intraday.py) and the sleep window and stages of that morning (get_sleep_data, reused from wellness()
        for the same day). Four calls; Body Battery comes with the stress response."""
        def get(name, fn):
            return fetch_metric(self.stats, name, lambda d: self._call(fn, d), day)

        sleep = self._sleep[1] if self._sleep[0] == day else get("slaap", self.api.get_sleep_data)
        return intraday_from_garmin(
            day,
            hr=get("hartslag", self.api.get_heart_rates),
            sleep=sleep,
            stress=get("stress", self.api.get_stress_data),
            respiration=get("ademhaling", self.api.get_respiration_data),
            spo2=get("spo2", self.api.get_spo2_data),
        )

    def tokens(self) -> str:
        return self.api.client.dumps()


def is_multisport(activity: dict) -> bool:
    return bool(activity.get("parent")) or (activity.get("activityType") or {}).get("typeKey") == "multi_sport"


def multisport_legs(client, activity: dict) -> list[dict]:
    """The legs of a multisport activity (triathlon, brick, swimrun, ...) as Garmin's activity list would give them,
    without the transitions. The list itself only has the parent; [] when Garmin gives no legs."""
    if not hasattr(client, "activity"):
        return []
    detail = client.activity(activity["activityId"])
    ids = (detail.get("metadataDTO") or {}).get("childIds") or activity.get("childIds") or []
    legs = [garmin_summary(client.activity(i)) for i in ids]
    return [leg for leg in legs if garmin_sport(leg.get("activityType")) != "transition" and leg.get("startTimeGMT")]


def _leg_window(leg: dict) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(leg["startTimeGMT"].replace(" ", "T")).replace(tzinfo=timezone.utc)
    return start, start + timedelta(seconds=leg.get("elapsedDuration") or leg.get("duration") or 0)


def _no_progress(step: str, done: int | None = None, total: int | None = None) -> None:
    pass


def sync_garmin(target, client, state: dict, today: date, since: date | None = None, read_streams=read_fit_streams,
                progress=_no_progress) -> int:
    """`progress(step, done, total)` reports how far it is, for the Connections page."""
    sink = as_sink(target)
    g = state.setdefault("garmin", {})
    default_start = since or today - timedelta(days=DEFAULT_BACKFILL_DAYS)

    act_start = date.fromisoformat(g["last_activity_day"]) if "last_activity_day" in g else default_start
    if since:
        act_start = min(act_start, since)
    count = 0
    progress("garmin_activities")
    activities = sorted(client.activities(act_start, today), key=lambda a: a["startTimeLocal"])
    for activity in activities:
        progress("garmin_activities", count, len(activities))
        activity_id = activity["activityId"]
        year = activity["startTimeLocal"][:4]
        fit = sink.get_fit(activity_id, year)
        if fit is None:
            fit = client.fit(activity_id)
            sink.put_fit(activity_id, year, fit)
        fit_rel = sink.fit_key(activity_id, year)
        legs = []
        if is_multisport(activity):
            try:
                legs = multisport_legs(client, activity)
            except RateLimited:
                raise
            except Exception as err:  # noqa: BLE001  no legs: stored as one multi_sport activity, like before
                print(f"garmin: onderdelen van multisport {activity_id} niet opgehaald ({err})")
        if legs:
            # each leg its own activity, so a triathlon counts as a swim, a ride and a run; the legs share the
            # parent's FIT file. Before this the parent was stored as one multi_sport activity: that one goes.
            sink.delete_garmin_activity(activity_id, activity["startTimeLocal"][:10])
            for leg in legs:
                try:
                    streams = read_streams(fit, *_leg_window(leg))
                except ValueError as err:
                    print(f"garmin: geen streams voor {leg['activityId']} ({err})")
                    streams = None
                sink.upsert_activity(from_garmin(leg, client.splits(leg["activityId"]), fit_file=fit_rel, streams=streams))
        else:
            try:
                streams = read_streams(fit)
            except ValueError as err:
                print(f"garmin: geen streams voor {activity_id} ({err})")
                streams = None
            sink.upsert_activity(from_garmin(activity, client.splits(activity_id), fit_file=fit_rel, streams=streams))
        g["last_activity_day"] = activity["startTimeLocal"][:10]
        count += 1
    g["last_activity_day"] = today.isoformat()

    well_start = date.fromisoformat(g["last_wellness_day"]) if "last_wellness_day" in g else default_start
    if since:
        well_start = min(well_start, since)
    # The intraday series keep their own place: they came later than wellness, so the first sync with them goes back
    # INTRADAY_FIRST_DAYS even when wellness is up to date, and wellness is fetched again for those days too (it
    # gained fields along with them). Clients without intraday() (tests, old fakes) skip it.
    with_intraday = hasattr(client, "intraday")
    day_start = date.fromisoformat(g["last_intraday_day"]) if "last_intraday_day" in g else today - timedelta(days=INTRADAY_FIRST_DAYS)
    if since:
        day_start = min(day_start, since)
    day_start = max(day_start, today - timedelta(days=INTRADAY_MAX_DAYS))
    recent = today - timedelta(days=REFETCH_DAYS)  # yesterday again: what the watch uploaded late
    well_start, day_start = min(well_start, recent), min(day_start, recent)
    first = min(well_start, day_start) if with_intraday else well_start
    day = first
    while day <= today:
        progress("garmin_wellness", (day - first).days, (today - first).days + 1)
        iso = day.isoformat()
        values = client.wellness(iso)
        if with_intraday and day >= day_start:
            series = client.intraday(iso)
            sink.write_intraday(iso, series)
            night = night_summary(series.get("hr") or [], series.get("sleep"))
            if night and values:
                values["sleep_hr"] = night["avg"]  # average heart rate while asleep, for readiness and trends
            g["last_intraday_day"] = iso
        sink.write_wellness(iso, values)
        g["last_wellness_day"] = iso
        if day == today:
            print(f"garmin vandaag: {today_report(values, series if with_intraday and day >= day_start else None)}")
        day += timedelta(days=1)
    return count


# --- database mode (Railway cron) ----------------------------------------------------


class _NoGarmin(Exception):
    pass


def _sync_wahoo_part(s: db.Scope, key: str, stored: str, state: dict, today: date, since: date | None, factory=None,
                     progress=_no_progress) -> bool:
    """The Wahoo half of a user's sync. False when it failed. Access revoked at Wahoo ends the connection and removes
    what came in through it, as the privacy statement promises."""
    creds = wahoo.credentials()
    if not creds or not key:
        print("wahoo: overgeslagen, WAHOO_CLIENT_ID/SECRET of TOKEN_ENCRYPTION_KEY ontbreekt")
        return False
    client = None
    try:
        tokens = wahoo.load_tokens(stored, key)
        client = (factory or wahoo.WahooClient)(tokens, creds)
        print(f"wahoo: {wahoo.sync_wahoo(s, client, state, today, since, progress=progress)} workouts")
        return True
    except WrongKey:
        print("wahoo: opgeslagen koppeling is met een andere sleutel versleuteld; koppel Wahoo opnieuw op de site")
        return False
    except wahoo.WahooRevoked as err:
        removed = end_wahoo(s)
        client = None
        print(f"wahoo: toegang ingetrokken bij Wahoo, koppeling beëindigd en Wahoo-data verwijderd ({err}; {removed})")
        state.pop("wahoo", None)
        return True
    except Exception as err:
        print(f"wahoo: MISLUKT ({type(err).__name__}: {err})")
        return False
    finally:
        if client is not None:
            wahoo.save_tokens(s, client.tokens(), key)  # Wahoo revokes the old pair once the new one is used


def end_wahoo(s: db.Scope) -> dict:
    """Forget the Wahoo connection and everything that came in through it (not the files the user uploaded)."""
    db.delete_setting(s, wahoo.TOKENS_KEY)
    db.delete_setting(s, "wahoo_meta")
    return db.remove_source(s, wahoo.SOURCE)


def run_db_sync(s: db.Scope, key: str, env_tokens: str | None, client_factory=None, today: date | None = None,
                read_streams=read_fit_streams, since: date | None = None, wahoo_factory=None, progress=_no_progress) -> int:
    """One user: Garmin -> database, then derived data. `s` is that user's Scope. Tokens: the encrypted copy in the
    database wins over GARMINTOKENS, because Garmin rotates the refresh token and only the database copy is kept up to date.
    GARMINTOKENS (env) is only offered for the first admin (the account that existed before multi-user)."""
    client_factory = client_factory or GarminClient
    tz = ZoneInfo("Europe/Amsterdam")
    today = today or datetime.now(tz).date()
    state = db.get_setting(s, "sync_state") or {}
    stored = db.get_setting(s, "garmin_tokens")
    stored_tokens = None
    if stored and key:
        try:
            stored_tokens = decrypt(stored, key)
        except WrongKey:
            print("garmin: opgeslagen sessie is met een andere sleutel versleuteld; koppel Garmin opnieuw op de site")
    candidates = [t for t in (stored_tokens, env_tokens) if t]
    wahoo_stored = db.get_setting(s, wahoo.TOKENS_KEY)
    failed, client = [], None
    try:
        if not candidates:
            if wahoo_stored or stored:  # only Wahoo connected (or a Garmin session this key cannot read): no Garmin run
                raise _NoGarmin()
            raise RuntimeError("geen koppeling: koppel Garmin of Wahoo op de site (Instellingen)")
        for i, tokens in enumerate(dict.fromkeys(candidates)):
            try:
                client = client_factory(tokens)
                break
            except RateLimited:
                raise
            except Exception as err:
                # stale database copy: fall back to a fresh GARMINTOKENS from setup_garmin.py
                if i == len(dict.fromkeys(candidates)) - 1:
                    raise
                print(f"garmin: opgeslagen sessie werkt niet meer ({type(err).__name__}), probeer GARMINTOKENS")
        print(f"garmin: {sync_garmin(DbSink(s), client, state, today, since, read_streams, progress)} activiteiten")
    except _NoGarmin:
        if stored:
            failed.append("garmin")
    except RateLimited:
        print("garmin: rate limit bereikt, volgende run gaat verder")
    except Exception as err:
        print(f"garmin: MISLUKT ({type(err).__name__}: {err})")
        failed.append("garmin")
    finally:
        if client is not None:
            for metric, counts in getattr(client, "stats", {}).items():
                print(f"garmin {metric}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
            if key:
                db.set_setting(s, "garmin_tokens", encrypt(client.tokens(), key))
        if wahoo_stored and not _sync_wahoo_part(s, key, wahoo_stored, state, today, since, wahoo_factory, progress):
            failed.append("wahoo")
        state["last_sync_local"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        if failed:
            state["last_failed"] = failed
        else:
            state.pop("last_failed", None)
        db.set_setting(s, "sync_state", state)
    progress("derive")
    print(f"derive: {derive(s)}")
    return 1 if failed else 0


def run_all_users(engine, key: str, env_tokens: str | None = None, **kw) -> int:
    """Sync every user with a Garmin connection (and the first admin, who may still rely on GARMINTOKENS).
    Suspended users are skipped. Returns 1 when any user failed."""
    first_admin = next((u["id"] for u in db.list_users(engine) if u["is_admin"]), None)
    connected = set(db.user_ids_with_setting(engine, "garmin_tokens")) | set(db.user_ids_with_setting(engine, wahoo.TOKENS_KEY))
    if env_tokens and first_admin:
        connected.add(first_admin)
    status = 0
    for user in db.list_users(engine):
        if user["id"] not in connected or user["suspended"]:
            continue
        print(f"--- {user['username']}")
        tokens = env_tokens if user["id"] == first_admin else None
        status |= run_db_sync(db.Scope(engine, user["id"]), key, tokens, **kw)
    return status


# --- CLI ----------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", type=date.fromisoformat, help="backfill vanaf deze datum (YYYY-MM-DD)")
    parser.add_argument("--source", choices=["all", "strava", "garmin"], default="all")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--files", action="store_true", help="schrijf naar de bestanden in data/ (oude modus) ook als DATABASE_URL gezet is")
    args = parser.parse_args(argv)

    if os.environ.get("DATABASE_URL") and not args.files:
        engine = db.connect(os.environ["DATABASE_URL"])
        db.create_schema(engine)
        return run_all_users(engine, default_key(), os.environ.get("GARMINTOKENS"), since=args.since)

    root = args.root
    token_out = os.environ.get("TOKEN_OUT_DIR")
    state_path = root / "data" / "sync_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    tz = ZoneInfo("Europe/Amsterdam")
    today = datetime.now(tz).date()
    failed = []

    def save():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=1))

    if args.source in ("all", "strava"):
        env = [os.environ.get(k) for k in ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")]
        if not all(env):
            print("strava: overgeslagen, secrets ontbreken")
        else:
            try:
                client = StravaClient(*env)
                write_rotated_token(token_out, "STRAVA_REFRESH_TOKEN", env[2], client.refresh_token)
                print(f"strava: {sync_strava(root, client, state, args.since)} activiteiten")
            except RateLimited:
                print("strava: rate limit bereikt, volgende run gaat verder")
            except Exception as err:
                print(f"strava: MISLUKT ({type(err).__name__}: {err})")
                failed.append("strava")
            finally:
                save()

    if args.source in ("all", "garmin"):
        tokens = os.environ.get("GARMINTOKENS")
        if not tokens:
            print("garmin: overgeslagen, secret GARMINTOKENS ontbreekt")
        else:
            client = None
            try:
                client = GarminClient(tokens)
                print(f"garmin: {sync_garmin(root, client, state, today, args.since)} activiteiten")
            except RateLimited:
                print("garmin: rate limit bereikt, volgende run gaat verder")
            except Exception as err:
                print(f"garmin: MISLUKT ({type(err).__name__}: {err})")
                failed.append("garmin")
            finally:
                if client is not None:
                    for metric, counts in client.stats.items():
                        print(f"garmin {metric}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
                    write_rotated_token(token_out, "GARMINTOKENS", tokens, client.tokens())
                save()

    state["last_sync_local"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    if failed:
        state["last_failed"] = failed
    else:
        state.pop("last_failed", None)
    save()

    from tools.build import build

    build(root, today)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
