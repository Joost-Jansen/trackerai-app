from tools.hrquality import assess, fit_relation, run_stats

STEP = 5  # seconds between samples
WOBBLE = [-1, 0, 1, 0]  # a real heart rate never stays exactly flat for minutes


def run_streams(minutes=40, speed=3.0, hr=150, start_hr=None, flat=None, gap=None):
    """Synthetic run at a steady speed. `start_hr` replaces the heart rate in the first km (after a 2 minute lag),
    `flat` = (from_s, to_s, bpm) holds the heart rate exactly constant, `gap` = (from_s, to_s) drops it."""
    n = minutes * 60 // STEP
    time = [i * STEP for i in range(n)]
    dist = [t * speed for t in time]
    heart = []
    for i, t in enumerate(time):
        v = (100 + (hr - 100) * t / 120 if t < 120 else hr) + WOBBLE[i % 4]
        if start_hr is not None and 120 <= t and dist[i] <= 1000:
            v = start_hr + WOBBLE[i % 4]
        if flat and flat[0] <= t < flat[1]:
            v = flat[2]
        if gap and gap[0] <= t < gap[1]:
            v = None
        heart.append(v)
    return {"time": time, "heartrate": heart, "velocity": [speed] * n, "distance": dist}


def reference(speeds=(2.6, 2.8, 3.0, 3.2, 3.4)):
    """The user's own pace-HR relation: 20 bpm more per extra m/s, 150 bpm at 3 m/s."""
    return fit_relation([run_stats(run_streams(speed=v, hr=round(150 + 20 * (v - 3.0)))) for v in speeds])


def test_normal_run_is_not_flagged():
    assert assess(run_stats(run_streams()), reference()) == []


def test_low_heart_rate_in_the_first_km_is_flagged():
    stats = run_stats(run_streams(start_hr=95))
    assert assess(stats, reference()) == ["low_start"]


def test_low_start_falls_back_to_the_run_itself_without_a_relation():
    assert assess(run_stats(run_streams(start_hr=95)), None) == ["low_start"]
    assert assess(run_stats(run_streams()), None) == []


def test_a_slow_warm_up_is_not_a_low_start():
    s = run_streams(start_hr=128)
    s["velocity"] = [2.0 if d <= 1000 else 3.0 for d in s["distance"]]
    assert assess(run_stats(s), reference()) == []


def test_flat_and_dropout_segments_are_flagged():
    assert assess(run_stats(run_streams(flat=(900, 1300, 141))), reference()) == ["flat"]
    assert assess(run_stats(run_streams(gap=(900, 1000))), reference()) == ["dropout"]
    assert assess(run_stats(run_streams(gap=(900, 930))), reference()) == []  # a short gap happens


def test_relation_needs_enough_runs_and_spread():
    assert reference(speeds=(3.0, 3.1)) is None
    rel = reference()
    assert rel is not None and abs(rel.slope - 20) < 1 and abs(rel.at(3.0) - 150) < 1


def test_run_without_heart_rate_or_streams_gives_nothing():
    s = run_streams()
    s["heartrate"] = [None] * len(s["time"])
    assert run_stats(s) is None
    assert run_stats({}) is None


def test_low_against_the_relation_but_close_to_the_run_itself_is_not_flagged():
    # an easy day: the whole run sits 30 bpm under the usual relation, the first km only 10 under the rest of the run
    assert assess(run_stats(run_streams(hr=120, start_hr=110)), reference()) == []
    assert assess(run_stats(run_streams(hr=150, start_hr=110)), reference()) == ["low_start"]
