from datetime import date, timedelta

from api.readiness import as_text, readiness

TODAY = date(2026, 9, 30)
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


def history(rhr=48, sleep=7.5, days=30):
    return {(TODAY - timedelta(days=i)).isoformat(): {"resting_hr": rhr, "sleep_h": sleep} for i in range(1, days + 1)}


def signal(r, key):
    return next(s for s in r["signals"] if s["key"] == key)


def test_normal_night_is_ready():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 48, "sleep_h": 7.4, "body_battery_high": 80}
    r = readiness(w, TODAY, tsb=-5)
    assert r["verdict"] == "ready" and r["date"] == TODAY.isoformat()
    assert {s["key"] for s in r["signals"]} == {"resting_hr", "sleep_h", "body_battery", "tsb"}


def test_high_resting_hr_and_short_sleep_means_recovery():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 55, "sleep_h": 4.5}
    assert readiness(w, TODAY)["verdict"] == "recover"


def test_one_signal_means_easy():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 51, "sleep_h": 7.5}
    assert readiness(w, TODAY)["verdict"] == "easy"


def test_stale_data_is_not_used_but_form_still_counts():
    w = {(TODAY - timedelta(days=5)).isoformat(): {"resting_hr": 60, "sleep_h": 4}}
    r = readiness(w, TODAY, tsb=-35)
    assert r["date"] is None and r["verdict"] == "easy" and r["no_night"] is True
    assert readiness({}, TODAY) is None


def test_without_night_data_the_verdict_is_unknown():
    r = readiness({TODAY.isoformat(): {"body_battery_high": 66}}, TODAY, tsb=-5)
    assert r["verdict"] == "unknown" and r["date"] is None and r["no_night"] is True


def test_no_sentences_only_codes_and_numbers():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 51, "sleep_h": 6.8, "sleep_score": 74, "body_battery_high": 70}
    r = readiness(w, TODAY, tsb=-12.4)
    assert "text" not in r and r["no_night"] is False
    assert all("label" not in s for s in r["signals"])
    rhr = signal(r, "resting_hr")
    assert rhr["value"] == 51 and rhr["note"] == {"code": "vs_baseline", "params": {"delta": 3, "baseline": 48}}
    sleep = signal(r, "sleep_h")
    assert sleep["value"] == 6.8 and sleep["note"] == {"code": "sleep", "params": {"score": 74, "baseline": 7.5}}
    assert signal(r, "tsb")["value"] == -12.4


def test_body_battery_from_today_says_today():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 48, "sleep_h": 7.5, "body_battery_high": 80}
    bb = signal(readiness(w, TODAY), "body_battery")
    assert bb["value"] == 80 and bb["note"] == {"code": "highest", "params": {"date": TODAY.isoformat(), "days_ago": 0}}


def test_body_battery_from_yesterday_does_not_say_today():
    w = history()
    w[YESTERDAY] = {"resting_hr": 48, "sleep_h": 7.5, "body_battery_high": 64}
    r = readiness(w, TODAY)
    assert r["date"] == YESTERDAY
    assert signal(r, "body_battery")["note"] == {"code": "highest", "params": {"date": YESTERDAY, "days_ago": 1}}


def test_form_note_says_yesterdays_fitness_minus_fatigue():
    r = readiness({}, TODAY, tsb=3)
    assert signal(r, "tsb")["note"] == {"code": "form_yesterday", "params": {}}


def test_as_text_for_agents_lists_verdict_and_signals():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 48, "sleep_h": 7.4, "body_battery_high": 80}
    text = as_text(readiness(w, TODAY, tsb=-5))
    assert text.startswith("klaar") and "rusthartslag 48 bpm" in text and "body battery 80" in text and "vorm -5" in text


def test_form_is_judged_as_a_share_of_fitness():
    w = history()
    w[TODAY.isoformat()] = {"resting_hr": 48, "sleep_h": 7.5}
    # -25 against a fitness of 90 (-28%) is training as usual; the same -25 against a fitness of 50 (-50%) is not
    assert signal(readiness(w, TODAY, tsb=-25, form_pct=-28), "tsb")["level"] == "ok"
    assert signal(readiness(w, TODAY, tsb=-25, form_pct=-50), "tsb")["level"] == "warn"
    assert "vorm -25 (-28%)" in as_text(readiness(w, TODAY, tsb=-25, form_pct=-28))


def test_normal_resting_hr_comes_from_60_days_then_the_last_7_nights_then_settings():
    from datetime import date

    from api.readiness import normal_resting_hr

    day = date(2026, 10, 6)
    recent = {f"2026-09-{d:02d}": {"resting_hr": 44 + d % 3} for d in range(10, 30)}
    assert normal_resting_hr(recent, day, 60) == (45, "60d")
    # fewer than 7 nights in the last 60 days: the median of the last 7 measured nights, however old
    old = {f"2026-0{m}-01": {"resting_hr": v} for m, v in [(1, 40), (2, 50), (3, 46), (4, 48), (5, 47), (6, 49), (7, 45), (8, 70)]}
    assert normal_resting_hr(old, day, 60) == (48, "recent")  # Feb..Aug, not January
    assert normal_resting_hr({}, day, 52) == (52.0, "profile")
    assert normal_resting_hr({}, day) == (None, None)
