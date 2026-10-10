"""Make a synthetic Apple Health export (export.zip) for testing the Apple import without an Apple Watch.

    python scripts/make_apple_export.py out/export.zip            # 120 days up to today
    python scripts/make_apple_export.py out/export.zip --days 400 --end 2026-10-05

Shaped like a real export of an iPhone with an Apple Watch (iOS 17), with the quirks the importer has to handle:

* the DTD Apple puts at the top of export.xml, the <Me> element, <ActivitySummary> rows;
* samples in local time with the offset of that moment (summer and winter time in Europe/Amsterdam);
* two sources writing the same things: steps from the iPhone and the Watch, "in bed" from the iPhone next to the
  Watch's sleep stages;
* sleep with stages (core, deep, REM, awake) and, for the oldest month, the pre-iOS 16 "asleep" without stages;
* workouts in the iOS 16+ form (<WorkoutStatistics>, routes as workout-routes/route_*.gpx) and, for the oldest
  month, the old form (totalDistance in miles on the <Workout>, the route as <Location>s inside it);
* outdoor runs and rides with GPS, a treadmill run, pool swims, strength training; heart rate every 5 s in a workout,
  every few minutes otherwise; resting HR, HRV (SDNN), breathing rate and SpO2 at night, VO2max after runs.
"""

from __future__ import annotations

import argparse
import io
import math
import random
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")
WATCH = "Alex’s Apple Watch"
PHONE = "Alex’s iPhone"
WATCH_DEVICE = "&lt;&lt;HKDevice: 0x28308c0f0&gt;, name:Apple Watch, manufacturer:Apple Inc., model:Watch, hardware:Watch6,1, software:10.1&gt;"
HOME = (52.3579, 4.8686)  # Vondelpark, Amsterdam

DTD = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!-- HealthKit Export Version: 13 -->
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout|ActivitySummary|ClinicalRecord|Audiogram|VisionPrescription)*)>
<!ATTLIST HealthData
  locale CDATA #REQUIRED
>
<!ELEMENT ExportDate EMPTY>
<!ATTLIST ExportDate
  value CDATA #REQUIRED
>
<!ELEMENT Record ((MetadataEntry|HeartRateVariabilityMetadataList)*)>
<!ATTLIST Record
  type          CDATA #REQUIRED
  unit          CDATA #IMPLIED
  value         CDATA #IMPLIED
  sourceName    CDATA #REQUIRED
  sourceVersion CDATA #IMPLIED
  device        CDATA #IMPLIED
  creationDate  CDATA #IMPLIED
  startDate     CDATA #REQUIRED
  endDate       CDATA #REQUIRED
>
<!ELEMENT Workout ((MetadataEntry|WorkoutEvent|WorkoutRoute|WorkoutStatistics)*)>
<!ELEMENT WorkoutRoute ((MetadataEntry|FileReference|Location)*)>
<!ELEMENT FileReference EMPTY>
<!ATTLIST FileReference
  path CDATA #REQUIRED
>
]>
"""


def stamp(dt: datetime) -> str:
    """Apple's "2026-10-05 07:12:03 +0200"."""
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S %z")


class Writer:
    def __init__(self, rnd: random.Random):
        self.rnd = rnd
        self.lines: list[str] = []
        self.routes: dict[str, str] = {}

    def record(self, kind: str, start: datetime, end: datetime | None, value, unit: str | None, source: str = WATCH, device: bool = True) -> None:
        end = end or start
        attrs = f'type="{kind}" sourceName="{source}" sourceVersion="10.1"'
        if device and source == WATCH:
            attrs += f' device="{WATCH_DEVICE}"'
        if unit:
            attrs += f' unit="{unit}"'
        attrs += f' creationDate="{stamp(end + timedelta(minutes=2))}" startDate="{stamp(start)}" endDate="{stamp(end)}"'
        if value is not None:
            attrs += f' value="{value}"'
        self.lines.append(f" <Record {attrs}/>")

    def hr(self, at: datetime, bpm: float, motion: int | None = None) -> None:
        if motion is None:
            self.record("HKQuantityTypeIdentifierHeartRate", at, at, round(bpm), "count/min")
        else:
            self.lines.append(
                f' <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="{WATCH}" sourceVersion="10.1" device="{WATCH_DEVICE}" '
                f'unit="count/min" creationDate="{stamp(at)}" startDate="{stamp(at)}" endDate="{stamp(at)}" value="{round(bpm)}">\n'
                f'  <MetadataEntry key="HKMetadataKeyHeartRateMotionContext" value="{motion}"/>\n </Record>'
            )


def loop_points(start: datetime, seconds: int, speed: float, rnd: random.Random, radius_km: float) -> list[tuple]:
    """A loop around HOME at `speed` m/s, one point a second: (datetime, lat, lon, ele, speed)."""
    pts = []
    circ = 2 * math.pi * radius_km * 1000
    for s in range(0, seconds, 1):
        angle = 2 * math.pi * (speed * s) / circ
        lat = HOME[0] + (radius_km / 111.0) * math.sin(angle)
        lon = HOME[1] + (radius_km / (111.0 * math.cos(math.radians(HOME[0])))) * (1 - math.cos(angle))
        v = max(0.5, speed + rnd.gauss(0, 0.15))
        pts.append((start + timedelta(seconds=s), lat, lon, 2 + 3 * math.sin(angle * 3), v))
    return pts


def gpx(points: list[tuple]) -> str:
    rows = [
        f'<trkpt lon="{lon:.6f}" lat="{lat:.6f}"><ele>{ele:.2f}</ele><time>{t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>'
        f"<extensions><speed>{v:.2f}</speed><course>-1.0</course><hAcc>2.9</hAcc><vAcc>1.8</vAcc></extensions></trkpt>"
        for t, lat, lon, ele, v in points
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Apple Health Export" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"<metadata><time>{points[0][0].astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')}</time></metadata>\n"
        "<trk><name>Route</name><trkseg>\n" + "\n".join(rows) + "\n</trkseg></trk>\n</gpx>\n"
    )


def make(end: date, days: int, seed: int = 7) -> bytes:
    rnd = random.Random(seed)
    w = Writer(rnd)
    first = end - timedelta(days=days - 1)
    old_until = first + timedelta(days=min(30, days // 3))  # the oldest month: pre-iOS 16 shapes
    rhr = 52.0
    for n in range(days):
        day = first + timedelta(days=n)
        old = day < old_until
        rhr = max(44, min(60, rhr + rnd.gauss(0, 0.6)))
        # --- the night that ends this morning -------------------------------------------------------------------
        bed = datetime.combine(day - timedelta(days=1), time(22, 45), TZ) + timedelta(minutes=rnd.randint(-40, 50))
        wake = datetime.combine(day, time(6, 50), TZ) + timedelta(minutes=rnd.randint(-30, 45))
        w.record("HKCategoryTypeIdentifierSleepAnalysis", bed - timedelta(minutes=10), wake + timedelta(minutes=8), "HKCategoryValueSleepAnalysisInBed", None, PHONE)
        if old:
            w.record("HKCategoryTypeIdentifierSleepAnalysis", bed, wake, "HKCategoryValueSleepAnalysisAsleep", None)
        else:
            t = bed
            cycle = 0
            while t < wake:
                for stage, minutes in (("Core", rnd.randint(25, 45)), ("Deep", rnd.randint(10, 35) if cycle < 3 else rnd.randint(0, 8)),
                                       ("Core", rnd.randint(10, 25)), ("REM", rnd.randint(10, 20) + 6 * cycle), ("Awake", rnd.choice((0, 0, 1, 2, 4)))):
                    if minutes <= 0 or t >= wake:
                        continue
                    seg_end = min(wake, t + timedelta(minutes=minutes))
                    w.record("HKCategoryTypeIdentifierSleepAnalysis", t, seg_end, f"HKCategoryValueSleepAnalysis{'Asleep' + stage if stage != 'Awake' else 'Awake'}", None)
                    t = seg_end
                cycle += 1
        t = bed
        while t < wake:  # heart rate, breathing and SpO2 while asleep
            frac = (t - bed) / (wake - bed)
            w.hr(t, rhr - 4 + 6 * frac + rnd.gauss(0, 1.5))
            if rnd.random() < 0.8:
                w.record("HKQuantityTypeIdentifierRespiratoryRate", t, t, round(13.5 + rnd.gauss(0, 0.8), 1), "count/min")
            if rnd.random() < 0.08:
                w.record("HKQuantityTypeIdentifierOxygenSaturation", t, t, round(min(1.0, 0.96 + rnd.gauss(0, 0.01)), 2), "%")
            if rnd.random() < 0.03:
                w.record("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", t, t + timedelta(minutes=1), round(max(15, 58 + rnd.gauss(0, 9)), 3), "ms")
            t += timedelta(minutes=rnd.randint(4, 7))
        w.record("HKQuantityTypeIdentifierRestingHeartRate", datetime.combine(day, time(0, 2), TZ), datetime.combine(day, time(23, 58), TZ), round(rhr), "count/min")

        # the day's workout, decided first: during a workout the Watch records workout heart rate only
        kind = ["run", "rest", "swim", "run", "strength", "ride", "run"][n % 7]
        if n % 23 == 11:
            kind = "treadmill"
        start = datetime.combine(day, time(17, 30), TZ) + timedelta(minutes=rnd.randint(-60, 60))
        minutes = {"run": rnd.randint(30, 65), "treadmill": 35, "swim": rnd.randint(35, 50), "strength": 40, "ride": rnd.randint(60, 120), "rest": 0}[kind]

        # --- the day: heart rate, steps from both devices, energy, flights -----------------------------------------
        t = wake + timedelta(minutes=5)
        evening = datetime.combine(day, time(22, 30), TZ)
        while t < evening:
            if not (start - timedelta(minutes=2) <= t <= start + timedelta(minutes=minutes + 2)):
                w.hr(t, rhr + 18 + rnd.gauss(0, 8), motion=1 if rnd.random() < 0.3 else 0)
            t += timedelta(minutes=rnd.randint(3, 9))
        for hour in range(7, 22):
            at = datetime.combine(day, time(hour, rnd.randint(0, 40)), TZ)
            steps = max(0, int(rnd.gauss(650, 300)))
            w.record("HKQuantityTypeIdentifierStepCount", at, at + timedelta(minutes=15), steps, "count", PHONE, device=False)
            w.record("HKQuantityTypeIdentifierStepCount", at, at + timedelta(minutes=15), int(steps * 1.06), "count")
            w.record("HKQuantityTypeIdentifierActiveEnergyBurned", at, at + timedelta(minutes=60), round(rnd.uniform(15, 35), 3), "kcal")
            if rnd.random() < 0.2:
                w.record("HKQuantityTypeIdentifierFlightsClimbed", at, at + timedelta(minutes=2), rnd.randint(1, 3), "count", PHONE, device=False)

        # --- workouts ----------------------------------------------------------------------------------------------
        if kind != "rest":
            seconds = minutes * 60
            stop = start + timedelta(seconds=seconds)
            effort = {"run": 148, "treadmill": 145, "swim": 125, "strength": 110, "ride": 128}[kind]
            hrs = []
            t = start
            while t < stop:  # heart rate every 5 s during a workout
                ramp = min(1.0, (t - start).total_seconds() / 120)  # a body warms up in a minute or two
                bpm = rhr + 35 + (effort - rhr - 35) * ramp + rnd.gauss(0, 3)
                hrs.append(bpm)
                w.hr(t, bpm, motion=2)
                t += timedelta(seconds=5)
            speed = {"run": rnd.uniform(2.7, 3.2), "treadmill": 2.8, "swim": 0.75, "ride": rnd.uniform(7.0, 8.2)}.get(kind)
            km = speed * seconds / 1000 if speed else None
            hk = {"run": "Running", "treadmill": "Running", "swim": "Swimming", "strength": "TraditionalStrengthTraining", "ride": "Cycling"}[kind]
            kcal = round(seconds / 60 * {"run": 11, "treadmill": 10, "swim": 9, "strength": 6, "ride": 10}[kind], 2)
            points = loop_points(start, seconds, speed, rnd, 1.6 if kind == "run" else 5.0) if kind in ("run", "ride") else []
            for minute in range(0, minutes, 5):
                at = start + timedelta(minutes=minute)
                w.record("HKQuantityTypeIdentifierAppleExerciseTime", at, at + timedelta(minutes=5), 5, "min")
            if old:
                attrs = (f'workoutActivityType="HKWorkoutActivityType{hk}" duration="{seconds / 60:.4f}" durationUnit="min"'
                         + (f' totalDistance="{km / 1.609344:.4f}" totalDistanceUnit="mi"' if km else "")
                         + f' totalEnergyBurned="{kcal}" totalEnergyBurnedUnit="kcal" sourceName="{WATCH}" sourceVersion="7.4"'
                         + f' creationDate="{stamp(stop)}" startDate="{stamp(start)}" endDate="{stamp(stop)}"')
                body = [' <MetadataEntry key="HKTimeZone" value="Europe/Amsterdam"/>']
                if kind == "swim":
                    body += [' <MetadataEntry key="HKSwimmingLocationType" value="1"/>', ' <MetadataEntry key="HKLapLength" value="25 m"/>']
                if points:
                    body.append(f' <WorkoutRoute sourceName="{PHONE}" sourceVersion="12.4" creationDate="{stamp(stop)}" startDate="{stamp(start)}" endDate="{stamp(stop)}">')
                    body += [f'  <Location date="{stamp(p[0])}" latitude="{p[1]:.6f}" longitude="{p[2]:.6f}" altitude="{p[3]:.2f}" horizontalAccuracy="3" verticalAccuracy="2" course="-1" speed="{p[4]:.2f}"/>'
                             for p in points[::3]]
                    body.append(" </WorkoutRoute>")
            else:
                attrs = (f'workoutActivityType="HKWorkoutActivityType{hk}" duration="{seconds / 60:.4f}" durationUnit="min"'
                         f' sourceName="{WATCH}" sourceVersion="10.1" device="{WATCH_DEVICE}"'
                         f' creationDate="{stamp(stop)}" startDate="{stamp(start)}" endDate="{stamp(stop)}"')
                body = [' <MetadataEntry key="HKTimeZone" value="Europe/Amsterdam"/>']
                if kind == "treadmill":
                    body.append(' <MetadataEntry key="HKIndoorWorkout" value="1"/>')
                if kind in ("run", "ride"):
                    body += [' <MetadataEntry key="HKIndoorWorkout" value="0"/>', f' <MetadataEntry key="HKElevationAscended" value="{rnd.randint(800, 4000)} cm"/>']
                if kind == "swim":
                    body += [' <MetadataEntry key="HKSwimmingLocationType" value="1"/>', ' <MetadataEntry key="HKLapLength" value="25 m"/>']
                body.append(f' <WorkoutEvent type="HKWorkoutEventTypeSegment" date="{stamp(start)}" duration="{seconds / 60:.4f}" durationUnit="min"/>')
                body.append(f' <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" startDate="{stamp(start)}" endDate="{stamp(stop)}" sum="{kcal}" unit="kcal"/>')
                body.append(f' <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" startDate="{stamp(start)}" endDate="{stamp(stop)}"'
                            f' average="{sum(hrs) / len(hrs):.4f}" minimum="{min(hrs):.0f}" maximum="{max(hrs):.0f}" unit="count/min"/>')
                if km:
                    dist_type = {"swim": "DistanceSwimming", "ride": "DistanceCycling"}.get(kind, "DistanceWalkingRunning")
                    km_value, unit = (km * 1000, "m") if kind == "swim" else (km, "km")
                    body.append(f' <WorkoutStatistics type="HKQuantityTypeIdentifier{dist_type}" startDate="{stamp(start)}" endDate="{stamp(stop)}" sum="{km_value:.4f}" unit="{unit}"/>')
                if points:
                    name = f"route_{start.strftime('%Y-%m-%d_%-I.%M%p').lower()}.gpx"
                    w.routes[f"workout-routes/{name}"] = gpx(points)
                    body.append(f' <WorkoutRoute sourceName="{WATCH}" sourceVersion="10.1" creationDate="{stamp(stop)}" startDate="{stamp(start)}" endDate="{stamp(stop)}">')
                    body.append(f'  <FileReference path="/workout-routes/{name}"/>')
                    body.append(" </WorkoutRoute>")
            w.lines.append(f" <Workout {attrs}>")
            w.lines += [" " + b for b in body]
            w.lines.append(" </Workout>")
            if kind == "run" and n % 14 == 0:
                w.record("HKQuantityTypeIdentifierVO2Max", stop, stop, round(48 + n / 60 + rnd.gauss(0, 0.6), 2), "mL/min·kg")
        w.lines.append(f' <ActivitySummary dateComponents="{day.isoformat()}" activeEnergyBurned="{rnd.randint(350, 800)}" activeEnergyBurnedGoal="600" activeEnergyBurnedUnit="Cal" appleMoveTime="0" appleMoveTimeGoal="0" appleExerciseTime="{rnd.randint(10, 90)}" appleExerciseTimeGoal="30" appleStandHours="{rnd.randint(6, 14)}" appleStandHoursGoal="12"/>')

    xml = (
        DTD
        + '<HealthData locale="en_NL">\n'
        + f' <ExportDate value="{stamp(datetime.combine(end, time(21, 0), TZ))}"/>\n'
        + ' <Me HKCharacteristicTypeIdentifierDateOfBirth="1994-05-17" HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"'
        + ' HKCharacteristicTypeIdentifierBloodType="HKBloodTypeNotSet" HKCharacteristicTypeIdentifierFitzpatrickSkinType="HKFitzpatrickSkinTypeNotSet"'
        + ' HKCharacteristicTypeIdentifierCardioFitnessMedicationsUse="None"/>\n'
        + "\n".join(w.lines)
        + "\n</HealthData>\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("apple_health_export/export.xml", xml)
        z.writestr("apple_health_export/export_cda.xml", '<?xml version="1.0"?><ClinicalDocument/>')
        for name, body in w.routes.items():
            z.writestr(f"apple_health_export/{name}", body)
    return buf.getvalue()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("out", type=Path)
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args(argv)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(make(a.end, a.days, a.seed))
    print(f"{a.out}: {a.out.stat().st_size / 1e6:.1f} MB, {a.days} days up to {a.end}")


if __name__ == "__main__":
    main()
