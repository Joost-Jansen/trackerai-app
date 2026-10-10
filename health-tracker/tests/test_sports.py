from tools.sports import garmin_sport, sport_of, strava_sport
from tools.store import from_garmin, garmin_summary
from tests.test_store import GARMIN_ACTIVITY


def t(key, parent=None):
    return garmin_sport({"typeKey": key, "parentTypeId": parent})


def test_running_cycling_and_swimming_variants_share_one_code():
    assert {t(k, 1) for k in ("trail_running", "street_running", "treadmill_running", "indoor_running", "ultra_run")} == {"run"}
    assert {t(k, 2) for k in ("road_biking", "cyclocross", "gravel_cycling", "indoor_cycling", "bmx", "enduro_mtb")} == {"ride"}
    assert {t(k, 26) for k in ("lap_swimming", "open_water_swimming")} == {"swim"}
    assert (t("running", 17), t("cycling", 17), t("swimming", 17)) == ("run", "ride", "swim")


def test_a_new_garmin_type_in_a_known_family_still_counts():
    assert t("moon_running", 1) == "run" and t("cargo_biking", 2) == "ride"


def test_e_bikes_and_hand_cycling_stay_apart_from_cycling():
    assert (t("e_bike_fitness", 2), t("e_bike_mountain", 2), t("indoor_hand_cycling", 2)) == ("e_bike", "e_bike", "hand_cycling")


def test_other_sports_keep_their_key_without_version_suffix():
    assert (t("tennis_v2", 219), t("cross_country_skiing_ws", 165), t("yoga", 29), t("paddelball", 219)) == ("tennis", "cross_country_skiing", "yoga", "padel")
    assert (t("casual_walking", 9), t("resort_skiing_snowboarding_ws", 165)) == ("walking", "resort_skiing")
    assert t("swimToBikeTransition_v2", 4) == "transition" and garmin_sport(None) == "other"


def test_strava_types():
    assert (strava_sport("TrailRun"), strava_sport("Walk"), strava_sport("EBikeRide"), strava_sport("WeightTraining")) == ("run", "walking", "e_bike", "strength_training")
    assert strava_sport("Snowkite") == "snowkite" and strava_sport("BackcountryBlading") == "backcountry_blading"


def test_sport_of_reads_the_raw_source_type():
    assert sport_of({"sources": {"garmin": {"raw": {"activityType": {"typeKey": "hiking", "parentTypeId": 17}}}}}) == "hiking"
    assert sport_of({"sources": {"strava": {"raw": {"sport_type": "Hike"}}}}) == "hiking"
    assert sport_of({"sources": {}}) is None


def test_elapsed_time_in_milliseconds_from_the_list_is_read_as_seconds():
    a = from_garmin({**GARMIN_ACTIVITY, "duration": 3459.3, "elapsedDuration": 4677150.9}, None)
    assert a["elapsed_time_s"] == 4677
    assert from_garmin({**GARMIN_ACTIVITY, "duration": 3459.3, "elapsedDuration": 3600.0}, None)["elapsed_time_s"] == 3600


def test_a_leg_from_the_detail_endpoint_reads_like_a_list_activity():
    leg = garmin_summary({
        "activityId": 6588349076, "activityName": "Bike-Walk-Bike - Gehen", "parentId": 6588349056,
        "activityTypeDTO": {"typeKey": "walking", "parentTypeId": 17},
        "summaryDTO": {"startTimeLocal": "2021-04-11T12:36:16.0", "startTimeGMT": "2021-04-11T10:36:16.0", "distance": 4036.26,
                       "duration": 4375.461, "movingDuration": 4020.0, "elapsedDuration": 5332.783, "averageHR": 125.0, "maxHR": 152.0, "averageRunCadence": 67.6},
    })
    a = from_garmin(leg, None)
    assert (a["sport"], a["start_local"], a["start_utc"], a["distance_km"], a["moving_time_s"], a["elapsed_time_s"], a["avg_hr"]) == (
        "walking", "2021-04-11T12:36:16", "2021-04-11T10:36:16Z", 4.04, 4020, 5333, 125)


def test_every_garmin_type_has_a_name_and_icon_on_the_site():
    # Garmin's types (typeKey, parentTypeId) from https://github.com/pe-st/garmin-connect-export/blob/master/json/activityTypes.json
    import json
    import re
    from pathlib import Path

    from api.plans import SPORTS as PLAN_SPORTS
    from tools.sports import FIT_SPORTS, FIT_SUB_SPORTS, STRAVA_SPORTS

    here = Path(__file__).resolve().parent
    types = json.loads((here / "garmin_activity_types.json").read_text())
    assert len(types) > 150
    codes = {garmin_sport(x) for x in types} | set(STRAVA_SPORTS.values()) | set(FIT_SPORTS.values()) | set(FIT_SUB_SPORTS.values()) | set(PLAN_SPORTS)
    web = set(re.findall(r"^  ([a-z_]+): s\(", (here.parent / "web" / "lib" / "sports.ts").read_text(), re.M))
    assert codes <= web, sorted(codes - web)


def test_fit_files_from_other_devices_use_the_same_codes():
    from tools.sports import fit_sport

    assert [fit_sport(*x) for x in [("cycling", "road"), ("cycling", "e_bike_mountain"), ("running", "treadmill"), ("training", "yoga"),
            ("training", "generic"), ("fitness_equipment", "indoor_rowing"), ("walking", None), ("generic", None), (None, None)]] == [
        "ride", "e_bike", "run", "yoga", "strength_training", "indoor_rowing", "walking", "other", "other"]
