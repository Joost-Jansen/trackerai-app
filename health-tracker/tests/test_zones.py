from tools.zones import load_zones, zone_for, zone_seconds

ZONES = {"run": {"bounds": [149, 158, 166, 175]}, "ride": {"bounds": [136, 151, 158, 168]}}


def test_run_boundaries_use_own_lthr_zones():
    assert zone_for(ZONES, "run", 148) == "Z1"
    assert zone_for(ZONES, "run", 149) == "Z2"
    assert zone_for(ZONES, "run", 165) == "Z3"
    assert zone_for(ZONES, "run", 166) == "Z4"
    assert zone_for(ZONES, "run", 175) == "Z5"


def test_zones_are_sport_specific():
    assert zone_for(ZONES, "run", 140) == "Z1"
    assert zone_for(ZONES, "ride", 140) == "Z2"


def test_sport_without_zones_has_none():
    assert zone_for(ZONES, "walking", 140) is None
    assert zone_seconds(ZONES, "walking", [140, 141], [0, 1]) is None


def test_zone_seconds_counts_time_until_next_sample():
    got = zone_seconds(ZONES, "run", heartrate=[140, 150, 170], time=[0, 10, 20])
    assert got == {"Z1": 10, "Z2": 10, "Z3": 0, "Z4": 0, "Z5": 0}


def test_zone_seconds_caps_pauses():
    # a watch pause shows up as a big time gap; it is not time spent at that heart rate
    got = zone_seconds(ZONES, "run", heartrate=[150, 150], time=[0, 600])
    assert got["Z2"] == 30


def test_zone_seconds_skips_missing_samples():
    got = zone_seconds(ZONES, "run", heartrate=[None, 150, 150], time=[0, 5, 10])
    assert got["Z2"] == 5 and sum(got.values()) == 5


def test_default_zones_are_valid(tmp_path):
    zones = load_zones(tmp_path)  # no zones.json: the generic defaults
    for sport in ("run", "ride", "swim"):
        b = zones[sport]["bounds"]
        assert len(b) == 4 and b == sorted(b)
