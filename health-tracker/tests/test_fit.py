import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from tools.fit import read_fit_streams, streams_from_records

T0 = datetime(2026, 9, 28, 7, 30, tzinfo=timezone.utc)
SEMI = 2**31 / 180  # semicircles per degree


def rec(sec, lat=None, lon=None, **fields):
    r = {"timestamp": T0 + timedelta(seconds=sec), **fields}
    if lat is not None:
        r["position_lat"] = round(lat * SEMI)
        r["position_long"] = round(lon * SEMI)
    return r


def test_semicircles_become_degrees_rounded_to_about_a_metre():
    s = streams_from_records([rec(0, 52.09, 5.12)])
    assert s["latlng"] == [[52.09, 5.12]]


def test_time_is_seconds_since_first_record():
    s = streams_from_records([rec(0, heart_rate=120), rec(5, heart_rate=125), rec(12, heart_rate=130)])
    assert s["time"] == [0, 5, 12]
    assert s["heartrate"] == [120, 125, 130]


def test_enhanced_fields_win_over_plain_ones():
    s = streams_from_records([rec(0, speed=1.0, enhanced_speed=3.1, altitude=1.0, enhanced_altitude=4.5)])
    assert s["velocity"] == [3.1]
    assert s["altitude"] == [4.5]


def test_records_without_position_are_left_out_of_the_track_only():
    s = streams_from_records([rec(0, 52.09, 5.12, heart_rate=120), rec(1, heart_rate=121), rec(2, 52.0901, 5.12, heart_rate=122)])
    assert len(s["latlng"]) == 2
    assert s["heartrate"] == [120, 121, 122]


def test_indoor_activity_has_no_track():
    s = streams_from_records([rec(0, heart_rate=120), rec(1, heart_rate=121)])
    assert "latlng" not in s


def test_records_without_timestamp_are_skipped():
    s = streams_from_records([{"heart_rate": 99}, rec(0, heart_rate=120)])
    assert s["heartrate"] == [120]


def test_empty_input_gives_no_streams():
    assert streams_from_records([]) == {}


def test_unreadable_zip_raises_value_error():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "no fit here")
    with pytest.raises(ValueError):
        read_fit_streams(buf.getvalue())


def test_a_window_keeps_one_leg_of_a_multisport_file():
    records = [rec(0, heart_rate=110), rec(60, heart_rate=150), rec(120, heart_rate=155), rec(180, heart_rate=160)]
    s = streams_from_records(records, T0 + timedelta(seconds=60), T0 + timedelta(seconds=120))
    assert s["time"] == [0, 60] and s["heartrate"] == [150, 155]
