from datetime import date

import pytest

from tools.analytics import fitness_series, trimp

MAXES = {"run": 189, "ride": 182}


def act(day, sport="run", minutes=60, hr=150):
    return {"start_local": f"{day}T08:00:00", "sport": sport, "moving_time_s": minutes * 60, "avg_hr": hr}


def test_trimp_grows_with_duration_and_intensity():
    easy = trimp(act("2026-09-01", hr=135), rhr=45, max_by_sport=MAXES)
    hard = trimp(act("2026-09-01", hr=170), rhr=45, max_by_sport=MAXES)
    long = trimp(act("2026-09-01", hr=135, minutes=120), rhr=45, max_by_sport=MAXES)
    assert 0 < easy < hard
    assert long == pytest.approx(2 * easy)


def test_trimp_uses_sport_specific_max():
    # same HR is relatively harder on the bike, whose max is lower
    run = trimp(act("2026-09-01", hr=150), rhr=45, max_by_sport=MAXES)
    ride = trimp(act("2026-09-01", sport="ride", hr=150), rhr=45, max_by_sport=MAXES)
    assert ride > run


def test_trimp_without_heart_rate_is_zero():
    assert trimp({"sport": "run", "moving_time_s": 3600}, rhr=45, max_by_sport=MAXES) == 0


def test_unknown_sport_falls_back_to_run_max():
    a = trimp(act("2026-09-01", sport="strength_training", hr=150), rhr=45, max_by_sport=MAXES)
    b = trimp(act("2026-09-01", hr=150), rhr=45, max_by_sport=MAXES)
    assert a == b


def test_fitness_series_covers_every_day_and_rises_with_training():
    acts = [act(f"2026-09-{d:02d}") for d in range(1, 15)]
    s = fitness_series(acts, rhr=45, max_by_sport=MAXES, end=date(2026, 9, 20))
    assert s[0]["date"] == "2026-09-01" and s[-1]["date"] == "2026-09-20"
    assert len(s) == 20
    assert s[13]["ctl"] > s[0]["ctl"]
    # after 6 rest days fatigue drops faster than fitness, so form turns positive
    assert s[-1]["atl"] < s[13]["atl"]
    assert s[-1]["tsb"] > s[13]["tsb"]


def test_fitness_series_sums_multiple_activities_per_day():
    one = fitness_series([act("2026-09-01")], rhr=45, max_by_sport=MAXES, end=date(2026, 9, 1))
    two = fitness_series([act("2026-09-01"), act("2026-09-01", sport="ride")], rhr=45, max_by_sport=MAXES, end=date(2026, 9, 1))
    assert two[0]["load"] > one[0]["load"]


def test_fitness_series_empty():
    assert fitness_series([], rhr=45, max_by_sport=MAXES, end=date(2026, 9, 1)) == []


def test_trimp_from_time_per_heart_rate_weighs_hard_minutes_more():
    from tools.zones import hr_histogram

    steady = hr_histogram([150] * 3601, list(range(3601)))
    mixed = hr_histogram([130] * 1800 + [170] * 1801, list(range(3601)))  # the same average, 150
    assert steady == {"150": 3600} and mixed == {"130": 1800, "170": 1800}
    base = {"sport": "run", "avg_hr": 150, "moving_time_s": 3600}
    maxes = {"run": 189}
    by_avg = trimp(base, 45, maxes)
    assert trimp({**base, "hr_hist_s": steady}, 45, maxes) == pytest.approx(by_avg)
    assert trimp({**base, "hr_hist_s": mixed}, 45, maxes) > by_avg * 1.05


def test_hr_histogram_caps_pauses_and_skips_missing_heart_rate():
    from tools.zones import hr_histogram

    assert hr_histogram([140, None, 141, 141], [0, 10, 20, 200]) == {"140": 10, "141": 30}  # 180 s gap capped at 30
    assert hr_histogram([None, None], [0, 1]) is None
