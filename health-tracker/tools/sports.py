"""Sport codes: which sport an activity from Garmin or Strava is.

Running, cycling and swimming have one code each (run, ride, swim), whatever the variant: the zones, records, routes
and plans compare them with each other. E-bikes and hand cycling stay apart, because heart rate and speed there say
something else than on a normal bike. Every other sport keeps Garmin's own type key, without its version suffix
(`tennis_v2` -> `tennis`), so a sport Garmin adds later works without a change here. The site has a name and an icon
per code (web/lib/sports.ts).

Garmin's types and their groups (parentTypeId) are listed at
https://github.com/pe-st/garmin-connect-export/blob/master/json/activityTypes.json.
"""

from __future__ import annotations

import re

# Garmin parentTypeId -> our code, for every type in that group (also types Garmin adds later)
GARMIN_FAMILIES = {1: "run", 2: "ride", 26: "swim"}
GARMIN_FAMILY_KEYS = {"running": 1, "cycling": 2, "swimming": 26}
# exceptions and merges by type key
GARMIN_KEYS = {
    "e_bike_fitness": "e_bike",
    "e_bike_mountain": "e_bike",
    "e_enduro_mtb": "e_bike",
    "hand_cycling": "hand_cycling",
    "indoor_hand_cycling": "hand_cycling",
    "casual_walking": "walking",
    "speed_walking": "walking",
    "resort_skiing_snowboarding_ws": "resort_skiing",
    "backcountry_skiing_snowboarding_ws": "backcountry_skiing",
    "whitewater_rafting_kayaking": "whitewater_rafting",
    "paddelball": "padel",
    "transition": "transition",
}
# keys from before this module (store.py's old table), so an activity without its raw Garmin type still maps
OLD_GARMIN_KEYS = {
    "running": "run", "trail_running": "run", "treadmill_running": "run", "track_running": "run", "virtual_run": "run",
    "cycling": "ride", "road_biking": "ride", "indoor_cycling": "ride", "virtual_ride": "ride",
    "gravel_cycling": "ride", "mountain_biking": "ride",
    "lap_swimming": "swim", "open_water_swimming": "swim", "swimming": "swim",
}
_SUFFIX = re.compile(r"_(v2|ws)$")


def garmin_sport(activity_type: dict | None) -> str:
    """Our code for Garmin's `activityType` (list) or `activityTypeDTO` (detail): {typeKey, parentTypeId, ...}."""
    activity_type = activity_type or {}
    key = activity_type.get("typeKey") or "other"
    if key in GARMIN_KEYS:
        return GARMIN_KEYS[key]
    if "transition" in key.lower():  # transition_v2, swimToBikeTransition_v2, ...: the change-over in a multisport
        return "transition"
    family = GARMIN_FAMILY_KEYS.get(key) or activity_type.get("parentTypeId")
    if family in GARMIN_FAMILIES:
        return GARMIN_FAMILIES[family]
    return OLD_GARMIN_KEYS.get(key) or _SUFFIX.sub("", key)


# How effort reads (the same rule as web/lib/sports.ts effortKind): pace on foot, per 100 m swimming, per 500 m
# rowing, speed for everything else.
PACE_SPORTS = {"run", "walking", "hiking", "rucking", "steps", "wheelchair_push_run", "wheelchair_push_walk", "para_sports"}


def effort_kind(code: str) -> str:
    if code in PACE_SPORTS:
        return "pace"
    if code == "swim":
        return "swim"
    if code in ("rowing", "indoor_rowing"):
        return "row"
    return "speed"


STRAVA_SPORTS = {
    "Run": "run", "TrailRun": "run", "VirtualRun": "run",
    "Ride": "ride", "VirtualRide": "ride", "GravelRide": "ride", "MountainBikeRide": "ride",
    "EBikeRide": "e_bike", "EMountainBikeRide": "e_bike", "Handcycle": "hand_cycling", "Velomobile": "ride",
    "Swim": "swim",
    "Walk": "walking", "Hike": "hiking", "Wheelchair": "wheelchair_push_walk",
    "WeightTraining": "strength_training", "Workout": "indoor_cardio", "Crossfit": "hiit", "HighIntensityIntervalTraining": "hiit",
    "Elliptical": "elliptical", "StairStepper": "stair_climbing", "Rowing": "rowing", "VirtualRow": "indoor_rowing",
    "Yoga": "yoga", "Pilates": "pilates",
    "AlpineSki": "resort_skiing", "BackcountrySki": "backcountry_skiing", "NordicSki": "cross_country_skiing",
    "Snowboard": "resort_snowboarding", "Snowshoe": "snow_shoe", "IceSkate": "skating", "InlineSkate": "inline_skating",
    "RollerSki": "skate_skiing", "Skateboard": "skateboarding",
    "Canoeing": "paddling", "Kayaking": "kayaking", "StandUpPaddling": "stand_up_paddleboarding", "Surfing": "surfing",
    "Kitesurf": "kiteboarding", "Windsurf": "windsurfing", "Sail": "sailing",
    "RockClimbing": "rock_climbing", "Golf": "golf", "Soccer": "soccer", "Tennis": "tennis", "Badminton": "badminton",
    "Pickleball": "pickleball", "Padel": "padel", "Racquetball": "racquetball", "Squash": "squash", "TableTennis": "table_tennis",
}


def strava_sport(sport_type: str | None) -> str:
    """Our code for Strava's `sport_type` (or the older `type`); unknown ones in snake_case."""
    if not sport_type:
        return "other"
    return STRAVA_SPORTS.get(sport_type) or re.sub(r"(?<!^)(?=[A-Z])", "_", sport_type).lower()


def sport_of(record: dict) -> str | None:
    """The code for a stored activity from its raw source data (Garmin first), or None without one."""
    sources = record.get("sources") or {}
    garmin = (sources.get("garmin") or {}).get("raw") or {}
    if garmin.get("activityType") or garmin.get("activityTypeDTO"):
        return garmin_sport(garmin.get("activityType") or garmin.get("activityTypeDTO"))
    strava = (sources.get("strava") or {}).get("raw") or {}
    if strava.get("sport_type") or strava.get("type"):
        return strava_sport(strava.get("sport_type") or strava.get("type"))
    return None


# A FIT file's session.sport and sub_sport (the FIT profile's names, e.g. from a Wahoo) -> our code.
FIT_SPORTS = {
    "running": "run", "cycling": "ride", "swimming": "swim", "transition": "transition", "multisport": "multi_sport",
    "generic": "other", "training": "strength_training", "fitness_equipment": "fitness_equipment",
    "walking": "walking", "hiking": "hiking", "e_biking": "e_bike", "rowing": "rowing", "cross_country_skiing": "cross_country_skiing",
    "alpine_skiing": "resort_skiing", "snowboarding": "resort_snowboarding", "snowshoeing": "snow_shoe", "ice_skating": "skating",
    "inline_skating": "inline_skating", "paddling": "paddling", "kayaking": "kayaking", "stand_up_paddleboarding": "stand_up_paddleboarding",
    "surfing": "surfing", "kitesurfing": "kiteboarding", "windsurfing": "windsurfing", "sailing": "sailing", "wakeboarding": "wakeboarding",
    "water_skiing": "waterskiing", "rafting": "whitewater_rafting", "rock_climbing": "rock_climbing", "mountaineering": "mountaineering",
    "golf": "golf", "disc_golf": "disc_golf", "tennis": "tennis", "padel": "padel", "pickleball": "pickleball", "racket": "racket_sports",
    "soccer": "soccer", "basketball": "basketball", "volleyball": "volleyball", "american_football": "american_football",
    "baseball": "baseball", "cricket": "cricket", "rugby": "rugby", "hockey": "field_hockey", "ice_hockey": "ice_hockey",
    "lacrosse": "lacrosse", "boxing": "boxing", "mixed_martial_arts": "mixed_martial_arts", "dance": "dance", "jumpmaster": "sky_diving",
    "diving": "diving", "horseback_riding": "horseback_riding", "hunting": "hunting", "fishing": "fishing", "flying": "flying",
    "hang_gliding": "hang_gliding", "driving": "driving_general", "motorcycling": "motorcycling", "wheelchair_push_run": "wheelchair_push_run",
    "wheelchair_push_walk": "wheelchair_push_walk", "meditation": "meditation", "jump_rope": "jump_rope",
}
FIT_SUB_SPORTS = {
    "e_bike_fitness": "e_bike", "e_bike_mountain": "e_bike", "hand_cycling": "hand_cycling", "indoor_hand_cycling": "hand_cycling",
    "strength_training": "strength_training", "cardio_training": "indoor_cardio", "yoga": "yoga", "pilates": "pilates", "hiit": "hiit",
    "breathing": "breathwork", "flexibility_training": "mobility", "indoor_rowing": "indoor_rowing", "elliptical": "elliptical",
    "stair_climbing": "stair_climbing", "indoor_climbing": "indoor_climbing", "bouldering": "bouldering", "backcountry": "backcountry_skiing",
    "skate_skiing": "skate_skiing",
}


def fit_sport(sport: str | None, sub_sport: str | None = None) -> str:
    """Our code for a FIT file's sport and sub_sport ("cycling"/"e_bike_mountain", "training"/"yoga", ...)."""
    sport, sub = (sport or "").lower(), (sub_sport or "").lower()
    if sub in FIT_SUB_SPORTS and sport in ("cycling", "training", "fitness_equipment", "rowing", "rock_climbing", "cross_country_skiing", "alpine_skiing", "e_biking"):
        return FIT_SUB_SPORTS[sub]
    if sport in FIT_SPORTS:
        return FIT_SPORTS[sport]
    return sport or "other"


# Apple Health's HKWorkoutActivityType<Name> -> our code. Indoor variants are a metadata flag (HKIndoorWorkout), not
# a type of their own. Unknown ones in snake_case, like Strava's.
APPLE_SPORTS = {
    "Running": "run", "Cycling": "ride", "HandCycling": "hand_cycling", "Swimming": "swim",
    "Walking": "walking", "Hiking": "hiking", "WheelchairWalkPace": "wheelchair_push_walk", "WheelchairRunPace": "wheelchair_push_run",
    "TraditionalStrengthTraining": "strength_training", "FunctionalStrengthTraining": "strength_training",
    "CrossTraining": "indoor_cardio", "MixedCardio": "indoor_cardio", "MixedMetabolicCardioTraining": "indoor_cardio",
    "HighIntensityIntervalTraining": "hiit", "Elliptical": "elliptical", "StairClimbing": "stair_climbing", "Stairs": "stair_climbing",
    "StepTraining": "stair_climbing", "Rowing": "rowing", "Yoga": "yoga", "Pilates": "pilates", "Flexibility": "mobility",
    "MindAndBody": "yoga", "Barre": "pilates", "CoreTraining": "strength_training", "Cooldown": "mobility",
    "DownhillSkiing": "resort_skiing", "CrossCountrySkiing": "cross_country_skiing", "Snowboarding": "resort_snowboarding",
    "SnowSports": "resort_skiing", "SkatingSports": "skating", "PaddleSports": "paddling", "Sailing": "sailing",
    "SurfingSports": "surfing", "WaterSports": "water_sports", "Climbing": "rock_climbing", "Golf": "golf",
    "Soccer": "soccer", "Tennis": "tennis", "Badminton": "badminton", "Pickleball": "pickleball", "Squash": "squash",
    "TableTennis": "table_tennis", "Racquetball": "racquetball", "Basketball": "basketball", "Volleyball": "volleyball",
    "Boxing": "boxing", "Kickboxing": "kickboxing", "MartialArts": "mixed_martial_arts", "Dance": "dance",
    "SocialDance": "dance", "CardioDance": "dance", "JumpRope": "jump_rope", "Hockey": "field_hockey",
    "Rugby": "rugby", "Cricket": "cricket", "Baseball": "baseball", "AmericanFootball": "american_football",
    "Equestrian": "horseback_riding", "Fishing": "fishing", "Hunting": "hunting", "Archery": "archery",
    "Swimbikerun": "multi_sport", "Transition": "transition", "Other": "other",
}


def apple_sport(activity_type: str | None) -> str:
    """Our code for Apple Health's workoutActivityType ("HKWorkoutActivityTypeRunning")."""
    name = (activity_type or "").removeprefix("HKWorkoutActivityType")
    if not name:
        return "other"
    return APPLE_SPORTS.get(name) or re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
