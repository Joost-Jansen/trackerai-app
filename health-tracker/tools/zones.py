"""Heart-rate zones per sport, used for every zone calculation.

In the app the zones come from each user's `zones` setting. File mode (tools/build.py) reads `zones.json` from the data
folder; without one it uses DEFAULT_ZONES: the standard % of max HR (70 / 77 / 85 / 92.5) on a generic max of 190.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("Z1", "Z2", "Z3", "Z4", "Z5")
MAX_SAMPLE_GAP_S = 30  # larger gaps are pauses, not time at that heart rate


DEFAULT_ZONES = {
    "run": {"max_hr": 190, "bounds": [133, 147, 163, 177]},
    "ride": {"max_hr": 183, "bounds": [128, 142, 157, 170], "estimate": True},
    "swim": {"max_hr": 178, "bounds": [125, 138, 152, 166], "estimate": True},
}


def load_zones(root: Path = ROOT) -> dict:
    path = Path(root) / "zones.json"
    if not path.exists():
        return {k: dict(v) for k, v in DEFAULT_ZONES.items()}
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def zone_for(zones: dict, sport: str, hr: float) -> str | None:
    if sport not in zones:
        return None
    for name, lower_next in zip(NAMES, zones[sport]["bounds"]):
        if hr < lower_next:
            return name
    return NAMES[-1]


def hr_histogram(heartrate: list, time: list) -> dict[str, int] | None:
    """Seconds per heart rate (bpm as a string key), with pauses capped like zone_seconds. From this the load of an
    activity follows for any resting and max heart rate (tools/analytics.py trimp), without reading the streams again."""
    out: dict[str, int] = {}
    for i in range(len(heartrate) - 1):
        if heartrate[i]:
            key = str(round(heartrate[i]))
            out[key] = out.get(key, 0) + min(time[i + 1] - time[i], MAX_SAMPLE_GAP_S)
    return {k: v for k, v in out.items() if v} or None


def zone_seconds(zones: dict, sport: str, heartrate: list, time: list) -> dict[str, int] | None:
    if sport not in zones:
        return None
    out = {name: 0 for name in NAMES}
    for i in range(len(heartrate) - 1):
        if heartrate[i]:
            out[zone_for(zones, sport, heartrate[i])] += min(time[i + 1] - time[i], MAX_SAMPLE_GAP_S)
    return out
