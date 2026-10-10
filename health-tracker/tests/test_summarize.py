from datetime import date

from tools.summarize import last_90_days_md, this_week_md

ZONES = {"run": {"bounds": [149, 158, 166, 175]}, "ride": {"bounds": [136, 151, 158, 168]}}

TODAY = date(2026, 9, 30)  # Wednesday; ISO week runs Mon 2026-09-28 .. Sun 2026-10-04


def act(day, sport="run", km=10.0, secs=3200, hr=150, name="Loop", **extra):
    return {
        "start_local": f"{day}T08:00:00",
        "sport": sport,
        "name": name,
        "distance_km": km,
        "moving_time_s": secs,
        "avg_hr": hr,
        **extra,
    }


def test_this_week_counts_only_current_iso_week():
    acts = [act("2026-09-27", km=20), act("2026-09-28", km=10), act("2026-09-30", km=8, secs=2560)]
    md = this_week_md(acts, {}, TODAY, last_sync="2026-09-30 06:02", zones=ZONES)
    assert "Laatste sync: 2026-09-30 06:02 (Europe/Amsterdam)" in md
    assert "| run | 2 | 18.0 | 1:36 |" in md
    assert "2026-09-27" not in md


def test_this_week_lists_activity_with_pace():
    md = this_week_md([act("2026-09-29", km=10, secs=3200, hr=149, name="Duurloop")], {}, TODAY, last_sync="x", zones=ZONES)
    assert "| 2026-09-29 | run | Duurloop | 10.0 | 5:20 | 149 |" in md


def test_this_week_shows_last_7_days_wellness():
    wellness = {"2026-09-22": {"sleep_h": 6.0}, "2026-09-29": {"sleep_h": 7.5, "hrv_last_night": 58, "resting_hr": 48}}
    md = this_week_md([], wellness, TODAY, last_sync="x", zones=ZONES)
    assert "| 2026-09-29 | 7.5 |" in md
    assert "2026-09-22" not in md


def test_90_days_has_weekly_run_volume_and_long_run():
    acts = [act("2026-09-29", km=10), act("2026-09-20", km=30, secs=10200), act("2026-06-01", km=50)]
    md = last_90_days_md(acts, {}, TODAY, zones=ZONES)
    assert "| 2026-09-28 | 10.0 |" in md
    assert "| 2026-09-14 | 30.0 |" in md
    assert "Langste run: 30.0 km op 2026-09-20" in md
    assert "50.0" not in md


def test_90_days_tracks_pace_at_aerobic_heart_rate():
    acts = [act("2026-09-29", km=10, secs=3200, hr=150), act("2026-09-25", km=10, secs=3300, hr=152), act("2026-09-26", km=5, secs=1300, hr=170)]
    md = last_90_days_md(acts, {}, TODAY, zones=ZONES)
    assert "Tempo in Z2 hardlopen (149-157 bpm)" in md
    assert "5:25" in md  # median of 5:20 and 5:30; the 170 bpm run is excluded


def test_split_run_counts_as_one_session_for_longest_run_and_count():
    # a long run saved as pieces with short stops (seen: 29 km in 5 parts on 2026-01-25)
    parts = [
        dict(act("2026-09-20", km=10, secs=3000), start_local="2026-09-20T08:00:00", elapsed_time_s=3000),
        dict(act("2026-09-20", km=12, secs=3600), start_local="2026-09-20T08:52:00", elapsed_time_s=3600),
    ]
    md = last_90_days_md(parts, {}, TODAY, zones=ZONES)
    assert "Langste run: 22.0 km op 2026-09-20" in md
    assert "| 2026-09-14 | 22.0 | 1 |" in md


def test_runs_hours_apart_stay_separate_sessions():
    runs = [
        dict(act("2026-09-20", km=10), start_local="2026-09-20T08:00:00", elapsed_time_s=3200),
        dict(act("2026-09-20", km=5), start_local="2026-09-20T18:00:00", elapsed_time_s=1600),
    ]
    assert "| 2026-09-14 | 15.0 | 2 |" in last_90_days_md(runs, {}, TODAY, zones=ZONES)


def test_this_week_shows_own_zones_per_sport():
    acts = [
        act("2026-09-29", hr_zones_s={"Z1": 1800, "Z2": 600, "Z3": 0, "Z4": 0, "Z5": 0}),
        act("2026-09-30", sport="ride", hr_zones_s={"Z1": 0, "Z2": 3600, "Z3": 0, "Z4": 0, "Z5": 0}),
    ]
    md = this_week_md(acts, {}, TODAY, last_sync="x", zones=ZONES)
    assert "## Hartslagzones (eigen zones, zie zones.json)" in md
    assert "| Z1 | 0:30 | 0:00 |" in md
    assert "| Z2 | 0:10 | 1:00 |" in md


def test_90_days_shows_weekly_run_zone_split():
    acts = [act("2026-09-29", hr_zones_s={"Z1": 3000, "Z2": 600, "Z3": 300, "Z4": 100, "Z5": 0})]
    md = last_90_days_md(acts, {}, TODAY, zones=ZONES)
    assert "| 2026-09-28 | 75% | 15% | 8% | 2% |" in md
