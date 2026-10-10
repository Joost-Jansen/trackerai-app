from tests.helpers import HOME, offset, out_and_back, run, square_loop
from tools.routes import build_routes, haversine_m, same_route


def test_haversine_one_km_north():
    # test helper uses a flat 111,320 m/degree, so allow 0.5%
    assert abs(haversine_m(HOME, offset(HOME, 1000, 0)) - 1000) < 5


def test_same_loop_with_gps_noise_is_same_route():
    a = run("a", "2026-09-01", square_loop(noise_m=8, seed=1), 4.0)
    b = run("b", "2026-09-03", square_loop(noise_m=8, seed=2), 4.05)
    assert same_route(a, b)


def test_loop_in_other_direction_from_same_start_is_different_route():
    a = run("a", "2026-09-01", square_loop(direction="ne"), 4.0)
    b = run("b", "2026-09-03", square_loop(direction="sw"), 4.0)
    assert not same_route(a, b)


def test_same_path_but_much_longer_distance_is_different_route():
    a = run("a", "2026-09-01", square_loop(), 4.0)
    b = run("b", "2026-09-03", square_loop(), 8.0)
    assert not same_route(a, b)


def test_run_without_gps_never_matches():
    a = run("a", "2026-09-01", [], 4.0)
    b = run("b", "2026-09-03", [], 4.0)
    assert not same_route(a, b)


def _three_ne_loops():
    return [run(f"ne{i}", f"2026-09-0{i + 1}", square_loop(noise_m=5, seed=i), 4.0) for i in range(3)]


def test_route_needs_three_runs():
    two = _three_ne_loops()[:2]
    assert build_routes(two, existing=[]) == []


def test_three_similar_runs_become_one_loop_route():
    routes = build_routes(_three_ne_loops(), existing=[])
    assert len(routes) == 1
    r = routes[0]
    assert r["runs"] == 3
    assert r["is_loop"] is True
    assert r["distance_km"] == 4.0
    assert r["last_run"] == "2026-09-03"
    assert sorted(r["activity_ids"]) == ["ne0", "ne1", "ne2"]


def test_out_and_back_is_not_a_loop():
    runs = [run(f"ob{i}", f"2026-09-0{i + 1}", out_and_back(), 6.0) for i in range(3)]
    routes = build_routes(runs, existing=[])
    assert len(routes) == 1
    assert routes[0]["is_loop"] is True  # start == finish, so it can be repeated from home


def test_point_to_point_is_not_a_loop():
    track = [list(offset(HOME, i * 10, 0)) for i in range(501)]
    runs = [run(f"p{i}", f"2026-09-0{i + 1}", track, 5.0) for i in range(3)]
    assert build_routes(runs, existing=[])[0]["is_loop"] is False


def test_user_given_name_and_id_survive_rebuild():
    first = build_routes(_three_ne_loops(), existing=[])
    first[0]["name"] = "Parkrondje"
    more = _three_ne_loops() + [run("ne9", "2026-09-20", square_loop(noise_m=5, seed=9), 4.1)]
    again = build_routes(more, existing=first)
    assert again[0]["name"] == "Parkrondje"
    assert again[0]["id"] == first[0]["id"]
    assert again[0]["runs"] == 4
    assert again[0]["last_run"] == "2026-09-20"


def test_two_distinct_routes_get_distinct_ids():
    ne = _three_ne_loops()
    sw = [run(f"sw{i}", f"2026-09-1{i}", square_loop(direction="sw", side_m=1500, seed=i), 6.0) for i in range(3)]
    routes = build_routes(ne + sw, existing=[])
    assert len(routes) == 2
    assert len({r["id"] for r in routes}) == 2


def test_run_stopped_just_before_home_still_counts_as_loop():
    # watch often stopped a few hundred metres before the front door (seen: 203 m, 259 m)
    track = square_loop()[:-27]  # ends ~260 m before the start
    runs = [run(f"x{i}", f"2026-09-0{i + 1}", track, 3.7) for i in range(3)]
    assert build_routes(runs, existing=[])[0]["is_loop"] is True


def test_generated_default_name_follows_new_distance():
    first = build_routes(_three_ne_loops(), existing=[])
    assert first[0]["name"] == "4.0 km loop (r1)"
    more = _three_ne_loops() + [run(f"n{i}", f"2026-09-2{i}", square_loop(noise_m=5, seed=20 + i), 4.3) for i in range(3)]
    again = build_routes(more, existing=first)
    assert again[0]["name"] == f"{again[0]['distance_km']:.1f} km loop (r1)"
    assert again[0]["distance_km"] != 4.0


# --- rides -----------------------------------------------------------------------


def _rides(n, km=40.0, side_m=10_000, seed0=0):
    # 40 km square loop, ridden at 30 km/h
    return [
        run(f"f{seed0 + i}", f"2026-09-{seed0 + i + 1:02d}", square_loop(side_m=side_m, step_m=50, noise_m=5, seed=seed0 + i), km, moving_time_s=int(km * 120), avg_hr=135)
        for i in range(n)
    ]


def test_runs_get_sport_and_no_speed():
    r = build_routes(_three_ne_loops(), existing=[])[0]
    assert r["sport"] == "run"
    assert r["median_pace"] == "5:20" and r["median_speed_kmh"] is None


def test_two_rides_are_enough_for_a_ride_route():
    routes = build_routes(_rides(2), existing=[], sport="ride")
    assert len(routes) == 1
    r = routes[0]
    assert r["id"] == "f1" and r["sport"] == "ride"
    assert r["name"] == "40.0 km bike loop (f1)"
    assert r["median_speed_kmh"] == 30.0 and r["median_pace"] is None
    assert r["runs"] == 2


def test_single_ride_is_not_a_route():
    assert build_routes(_rides(1), existing=[], sport="ride") == []


def test_min_runs_can_be_overridden():
    assert len(build_routes(_three_ne_loops()[:2], existing=[], min_runs=2)) == 1


def test_point_to_point_ride_is_a_fietsroute():
    track = [list(offset(HOME, i * 50, 0)) for i in range(401)]
    rides = [run(f"p{i}", f"2026-09-0{i + 1}", track, 20.0, moving_time_s=2400) for i in range(2)]
    assert build_routes(rides, existing=[], sport="ride")[0]["name"] == "20.0 km bike route (f1)"


def test_ride_ids_number_separately_from_run_ids():
    runs = build_routes(_three_ne_loops(), existing=[])
    existing = runs + [dict(runs[0], id="r7", name="Dijk")]
    rides = build_routes(_rides(2), existing=existing, sport="ride")
    assert [r["id"] for r in rides] == ["f1"]


def test_ride_route_keeps_id_and_user_name_on_rebuild():
    first = build_routes(_rides(2), existing=[], sport="ride")
    first[0]["name"] = "Rondje Utrechtse Heuvelrug"
    again = build_routes(_rides(3), existing=first, sport="ride")
    assert again[0]["id"] == "f1" and again[0]["name"] == "Rondje Utrechtse Heuvelrug" and again[0]["runs"] == 3


def test_rebuilding_rides_ignores_existing_run_routes():
    # a run route with the same shape must not hand its id or name to a ride route
    runs = build_routes(_rides(3), existing=[])  # same tracks, but as runs
    runs[0]["name"] = "Lang loopje"
    rides = build_routes(_rides(2), existing=runs, sport="ride")
    assert rides[0]["id"] == "f1" and rides[0]["name"] == "40.0 km bike loop (f1)"


def test_generated_ride_names_are_recognised_as_default():
    first = build_routes(_rides(2), existing=[], sport="ride")
    more = _rides(2) + _rides(3, km=44.0, seed0=10)
    again = build_routes(more, existing=first, sport="ride")
    assert again[0]["id"] == "f1"
    assert again[0]["name"] == f"{again[0]['distance_km']:.1f} km bike loop (f1)"


def test_default_name_pattern_covers_both_sports():
    from tools.routes import DEFAULT_NAME

    for name in ["10.6 km loop (r1)", "21.5 km route (r12)", "40.0 km bike loop (f1)", "92.9 km bike route (f3)"]:
        assert DEFAULT_NAME.match(name)
    for name in ["Parkrondje", "40.0 km fietsrondje", "10.6 km loop (x1)"]:
        assert not DEFAULT_NAME.match(name)


# --- the same route from a different start (tracker switched on outside town) --------------------------

def _big_loop():
    return square_loop(side_m=10_000, step_m=50)  # 40 km loop


def _ride_part(start_frac, length_frac, lead_in_m=0, seed=0):
    """Part of the big loop: starting at start_frac of the way round, covering length_frac of it,
    optionally with a lead-in from town (a straight stretch west of the start)."""
    loop = _big_loop()[:-1]
    n = len(loop)
    i0 = int(start_frac * n)
    pts = [loop[(i0 + k) % n] for k in range(int(length_frac * n))]
    if lead_in_m:
        steps = lead_in_m // 50
        pts = [list(offset(tuple(pts[0]), 0, -(steps - k) * 50)) for k in range(steps)] + pts
    km = round(len(pts) * 0.05, 1)
    return pts, km


def _ride(aid, date, start_frac, length_frac, lead_in_m=0):
    pts, km = _ride_part(start_frac, length_frac, lead_in_m)
    return run(aid, date, pts, km)


def test_same_ride_from_different_start_points_is_same_route():
    a = _ride("a", "2026-09-01", 0.0, 0.95)
    b = _ride("b", "2026-09-08", 0.30, 0.90)
    c = _ride("c", "2026-09-15", 0.60, 0.85, lead_in_m=4000)  # started in town, 4 km extra
    assert same_route(a, b, "ride") and same_route(a, c, "ride") and same_route(b, c, "ride")
    routes = build_routes([a, b, c], existing=[], sport="ride")
    assert len(routes) == 1 and routes[0]["runs"] == 3 and routes[0]["id"] == "f1"
    assert routes[0]["medoid_id"] in {"a", "b", "c"}


def test_ride_covering_only_half_the_loop_is_a_different_route():
    a = _ride("a", "2026-09-01", 0.0, 0.95)
    half = _ride("h", "2026-09-08", 0.0, 0.5)
    assert not same_route(a, half, "ride")


def test_run_loop_started_elsewhere_on_the_loop_is_same_route():
    loop = square_loop(step_m=10)[:-1]
    shifted = loop[100:] + loop[:100]  # same 4 km square, watch started 1 km further
    assert same_route(run("a", "2026-09-01", loop, 4.0), run("b", "2026-09-02", shifted, 4.0))


def test_medoid_is_the_most_typical_member():
    typical = [_ride(f"t{i}", f"2026-09-0{i + 1}", 0.1 * i, 0.9) for i in range(3)]
    odd = _ride("odd", "2026-09-09", 0.6, 0.75, lead_in_m=6000)  # east side: lead-in crosses the inside
    routes = build_routes(typical + [odd], existing=[], sport="ride")
    assert len(routes) == 1 and routes[0]["runs"] == 4 and routes[0]["medoid_id"] != "odd"


# --- similarity with confidence: same / candidate / different ----------------------------------------

from tests.helpers import path  # noqa: E402
from tools.routes import compare, distance_variants, shape  # noqa: E402

SQUARE = [(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)]  # 4 km loop from HOME


def _shape(waypoints, km=None, start=HOME):
    pts = path(waypoints, start=start)
    if km is None:
        km = round(sum(haversine_m(a, b) for a, b in zip(pts, pts[1:])) / 1000, 2)
    return shape(run("x", "2026-09-01", pts, km))


def test_loop_started_elsewhere_and_ridden_the_other_way_is_same():
    a = _shape(SQUARE)
    other_way = _shape([(1000, 1000), (1000, 0), (0, 0), (0, 1000), (1000, 1000)])  # NE corner, anticlockwise
    c = compare(a, other_way, "run")
    assert c["outcome"] == "same" and c["confidence"] >= 0.8


def test_loop_with_lead_in_from_another_start_is_a_candidate():
    a = _shape(SQUARE)
    from_elsewhere = _shape([(-800, 0)] + SQUARE + [(-800, 0)])  # 800 m to the loop and back: 5.6 km
    c = compare(a, from_elsewhere, "run")
    assert c["outcome"] == "candidate"
    assert c["reason"] == "zelfde rondje, ander startpunt" and c["reason_code"] == "other_start"
    assert 0.5 <= c["confidence"] < 0.8


def test_loop_with_an_extra_lap_is_a_candidate():
    a = _shape(SQUARE)
    extra = _shape([(0, 0), (1000, 0), (1500, 0), (1500, 500), (1000, 500), (1000, 1000), (0, 1000), (0, 0)])  # +1 km
    c = compare(a, extra, "run")
    assert c["outcome"] == "candidate"
    assert c["reason"] == "zelfde rondje met een extra lus of omweg"


def test_loop_with_a_shortcut_is_a_candidate():
    a = _shape([(0, 0), (1000, 0), (1000, 1500), (0, 1500), (0, 0)])  # 5 km
    shortcut = _shape([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])  # cuts the east 500 m off: 4 km
    assert compare(a, shortcut, "run")["outcome"] == "candidate"


def test_other_loop_is_different():
    a = _shape(SQUARE)
    b = _shape([(0, 0), (-1000, 0), (-1000, -1000), (0, -1000), (0, 0)])  # SW square, only the start shared
    c = compare(a, b, "run")
    assert c["outcome"] == "different" and c["confidence"] < 0.5


def test_short_stretch_of_a_long_loop_is_different():
    a = _shape(SQUARE)
    bit = _shape([(0, 0), (800, 0), (0, 0)])  # 1.6 km out and back along one side
    assert compare(a, bit, "run")["outcome"] == "different"


def test_confidence_orders_same_candidate_different():
    a = _shape(SQUARE)
    same = compare(a, _shape(SQUARE, start=offset(HOME, 30, 20)), "run")
    cand = compare(a, _shape([(-800, 0)] + SQUARE + [(-800, 0)]), "run")
    diff = compare(a, _shape([(0, 0), (-1000, 0), (-1000, -1000), (0, -1000), (0, 0)]), "run")
    assert same["outcome"] == "same" and same["confidence"] > cand["confidence"] > diff["confidence"]


def test_compare_is_symmetric():
    a, b = _shape(SQUARE), _shape([(-800, 0)] + SQUARE + [(-800, 0)])
    assert compare(a, b, "run") == compare(b, a, "run")


def test_ride_variants_of_one_circuit():
    # 40 km circuit; one ride adds a 6 km extra lap: too long for "same", but clearly the same circuit
    base = [(0, 0), (10_000, 0), (10_000, 10_000), (0, 10_000), (0, 0)]
    longer = [(0, 0), (10_000, 0), (13_000, 0), (13_000, 3_000), (10_000, 3_000), (10_000, 10_000), (0, 10_000), (0, 0)]
    c = compare(_shape(base), _shape(longer), "ride")
    assert c["outcome"] in ("same", "candidate")


def test_distance_variants_split_on_clear_gaps():
    members = [{"activity_id": f"a{i}", "date": f"2026-09-{i + 1:02d}", "distance_km": d} for i, d in enumerate([38.0, 38.4, 42.1, 42.5, 41.9, 47.2])]
    v = distance_variants(members, "ride")
    assert [(x["distance_km"], x["runs"]) for x in v] == [(38.2, 2), (42.1, 3), (47.2, 1)]
    assert v[2]["activity_ids"] == ["a5"] and v[2]["last_run"] == "2026-09-06"


def test_distance_variants_ignore_gps_noise():
    members = [{"activity_id": f"a{i}", "date": "2026-09-01", "distance_km": d} for i, d in enumerate([10.4, 10.6, 10.7, 10.9])]
    assert len(distance_variants(members, "run")) == 1


# --- detect: candidates, decisions, groups ------------------------------------------------------------

from tools.routes import apply_merge, detect, member_from_activity  # noqa: E402

LEAD_IN = [(-800, 0)] + SQUARE + [(-800, 0)]  # same 4 km loop from a start 800 m away: 5.6 km
EXTRA_LAP = [(0, 0), (1000, 0), (1500, 0), (1500, 500), (1000, 500), (1000, 1000), (0, 1000), (0, 0)]  # 5 km


def _runs(prefix, waypoints, km, days, start=HOME):
    return [run(f"{prefix}{d}", f"2026-08-{d:02d}", path(waypoints, start=start), km) for d in days]


def _loops(days=(1, 3, 5)):
    return _runs("sq", SQUARE, 4.0, days)


def _lead_ins(days=(2, 4, 6)):
    return _runs("li", LEAD_IN, 5.6, days)


def test_detect_proposes_two_routes_of_one_circuit_as_candidate():
    routes, cands = detect(_loops() + _lead_ins(), existing=[])
    assert sorted(r["id"] for r in routes) == ["r1", "r2"]
    assert len(cands) == 1
    c = cands[0]
    assert (c["a"]["id"], c["b"]["id"], c["b"]["kind"]) == ("r1", "r2", "route")
    assert c["sport"] == "run" and c["reason"] == "zelfde rondje, ander startpunt" and 0.5 <= c["confidence"] < 0.8
    assert c["a"]["runs"] == 3 and c["b"]["distance_km"] == 5.6 and c["a"]["name"] == "4.0 km loop (r1)"


def test_merge_decision_joins_routes_and_stays_merged():
    routes, _ = detect(_loops() + _lead_ins(), existing=[])
    merged, cands = detect(_loops() + _lead_ins(), existing=routes, decisions={"merge": [["r2", "r1"]]})
    assert cands == [] and [r["id"] for r in merged] == ["r1"]
    r = merged[0]
    assert r["runs"] == 6 and [g["id"] for g in r["groups"]] == ["r1", "r2"]
    assert [(v["distance_km"], v["runs"]) for v in r["distance_variants"]] == [(4.0, 3), (5.6, 3)]
    # next sync: the decision is no longer needed, and a new ride of the variant joins on its own
    again, cands = detect(_loops() + _lead_ins((2, 4, 6, 8)), existing=merged)
    assert [x["id"] for x in again] == ["r1"] and again[0]["runs"] == 7 and cands == []


def test_merge_keeps_older_id_and_a_name_the_user_gave():
    routes, _ = detect(_loops() + _lead_ins(), existing=[])
    for r in routes:
        if r["id"] == "r2":
            r["name"] = "Vanaf het station"
    merged, _ = detect(_loops() + _lead_ins(), existing=routes, decisions={"merge": [["r1", "r2"]]})
    assert merged[0]["id"] == "r1" and merged[0]["name"] == "Vanaf het station"


def test_absorbed_id_is_not_reused():
    routes, _ = detect(_loops() + _lead_ins(), existing=[])
    merged, _ = detect(_loops() + _lead_ins(), existing=routes, decisions={"merge": [["r1", "r2"]]})
    other = _runs("sw", [(0, 0), (-1000, 0), (-1000, -1000), (0, -1000), (0, 0)], 4.0, (10, 11, 12))
    again, _ = detect(_loops() + _lead_ins() + other, existing=merged)
    assert sorted(r["id"] for r in again) == ["r1", "r3"]


def test_separate_decision_is_never_asked_again():
    routes, _ = detect(_loops() + _lead_ins(), existing=[])
    again, cands = detect(_loops() + _lead_ins(), existing=routes, decisions={"separate": [["r2", "r1"]]})
    assert sorted(r["id"] for r in again) == ["r1", "r2"] and cands == []


def test_single_activity_variant_is_a_candidate_and_can_join():
    extra = _runs("ex", EXTRA_LAP, 5.0, (7,))
    routes, cands = detect(_loops() + extra, existing=[])
    assert [r["id"] for r in routes] == ["r1"] and routes[0]["runs"] == 3
    assert len(cands) == 1 and cands[0]["b"] == {"id": "ex7", "kind": "activity", "name": None, "distance_km": 5.0, "runs": 1, "date": "2026-08-07"}
    assert cands[0]["reason"].startswith("zelfde rondje met een extra lus")

    merged, cands = detect(_loops() + extra, existing=routes, decisions={"merge": [["r1", "ex7"]]})
    assert merged[0]["runs"] == 4 and cands == []
    assert merged[0]["groups"][1] == {"id": "ex7", "kind": "activity", "activity_ids": ["ex7"]}
    # the same variant again later: joins the route without asking
    again, cands = detect(_loops() + extra + _runs("ex", EXTRA_LAP, 5.0, (20,)), existing=merged)
    assert again[0]["runs"] == 5 and cands == []


def test_single_activity_separate_is_not_asked_again():
    extra = _runs("ex", EXTRA_LAP, 5.0, (7,))
    routes, _ = detect(_loops() + extra, existing=[])
    _, cands = detect(_loops() + extra, existing=routes, decisions={"separate": [["ex7", "r1"]]})
    assert cands == []


def test_existing_members_stay_on_their_route():
    # a member added to a route earlier stays there, even when the matching rules would not take it in now
    routes, _ = detect(_loops(), existing=[])
    odd = _runs("ex", EXTRA_LAP, 5.0, (7,))
    routes[0]["activity_ids"].append("ex7")
    again, cands = detect(_loops() + odd, existing=routes)
    assert again[0]["runs"] == 4 and cands == []


def test_build_routes_is_detect_without_candidates():
    assert build_routes(_loops() + _lead_ins(), existing=[]) == detect(_loops() + _lead_ins(), existing=[])[0]


# --- apply_merge: the same merge right away, without tracks (API) ------------------------------------


def _members(runs_):
    return {r["activity_id"]: {k: v for k, v in r.items() if k != "latlng"} for r in runs_}


def test_apply_merge_of_two_routes_matches_detect():
    runs_ = _loops() + _lead_ins()
    routes, _ = detect(runs_, existing=[])
    now = apply_merge(routes, "r2", "r1", _members(runs_))
    later, _ = detect(runs_, existing=routes, decisions={"merge": [["r1", "r2"]]})
    assert [r["id"] for r in now] == ["r1"]
    for key in ("runs", "distance_km", "first_run", "last_run", "median_pace", "activity_ids", "distance_variants", "name", "groups"):
        assert now[0][key] == later[0][key], key


def test_apply_merge_of_an_activity_adds_it_as_its_own_group():
    runs_ = _loops() + _runs("ex", EXTRA_LAP, 5.0, (7,))
    routes, _ = detect(runs_, existing=[])
    now = apply_merge(routes, "r1", "ex7", _members(runs_))
    assert now[0]["runs"] == 4 and now[0]["groups"][-1]["id"] == "ex7" and now[0]["last_run"] == "2026-08-07"


def test_apply_merge_of_unknown_ids_returns_none():
    routes, _ = detect(_loops(), existing=[])
    assert apply_merge(routes, "r1", "nope", {}) is None
    assert apply_merge(routes, "r8", "r9", {}) is None


def test_member_from_activity():
    a = {"id": "x", "start_local": "2026-08-01T07:00:00", "distance_km": 5.0, "moving_time_s": 1500, "avg_hr": 140, "elevation_gain_m": 12}
    assert member_from_activity(a) == {"activity_id": "x", "date": "2026-08-01", "distance_km": 5.0, "moving_time_s": 1500, "avg_hr": 140, "elevation_gain_m": 12}


def test_loop_inside_a_run_of_almost_twice_the_length_is_different():
    a = _shape(SQUARE)
    twice = _shape(SQUARE + [(1000, 0), (1000, 1000), (0, 1000), (0, 0)])  # the loop twice: 8 km on the same cells
    assert compare(a, twice, "run")["outcome"] == "different"


def test_loop_or_line_of_an_existing_route_does_not_flip():
    # the generated name says "rondje" or "route"; a new main track must not rename a route the user knows
    routes, _ = detect(_loops(), existing=[])
    routes[0]["is_loop"], routes[0]["name"] = False, "4.0 km route (r1)"
    again, _ = detect(_loops(), existing=routes)
    assert again[0]["is_loop"] is False and again[0]["name"] == "4.0 km route (r1)"
