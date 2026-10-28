"""Rhythm from cursor timing: grid choice per beat, swing detection and the GP5 durations."""
from tabreader.assemble import TICKS_PER_QUARTER as Q, detect_swing, quantise_positions, unswing
from tabreader.export import DURATIONS, split_ticks


def test_straight_16ths_stay_on_the_16th_grid():
    pos = [0, 0.25, 0.5, 0.75, 1.0, 1.52, 2.01]
    assert quantise_positions(pos) == [0, Q // 4, Q // 2, 3 * Q // 4, Q, 3 * Q // 2, 2 * Q]


def test_16th_triplets_are_recognised_without_collisions():
    # 0 1 0 played as a 16th triplet on beat 4, then an 8th (measure 29 of Mr. Blue Sky)
    pos = [3.0, 3.165, 3.33, 3.5]
    ticks = quantise_positions(pos)
    assert ticks == [3 * Q, 3 * Q + Q // 6, 3 * Q + Q // 3, 3 * Q + Q // 2]
    assert len(set(ticks)) == len(ticks)


def test_eighth_triplets():
    assert quantise_positions([1.0, 1.335, 1.665]) == [Q, Q + Q // 3, Q + 2 * Q // 3]


def test_swing_detected_and_removed():
    # off-beat 16ths land at 0.62 of the 8th: Guitar Pro's 16th triplet feel
    swung = [b / 2 + u / 2 for b in range(16) for u in (0.0, 0.62)]
    feel, ratio = detect_swing(swung)
    assert feel == "16th" and abs(ratio - 0.62) < 0.01
    straight = [unswing(p, ratio, 0.5) for p in swung]
    assert quantise_positions(straight) == [round(p * 4) * Q // 4 for p in straight]


def test_straight_music_has_no_swing():
    assert detect_swing([b / 4 for b in range(64)])[0] is None


def test_every_tick_count_splits_into_written_durations():
    allowed = {d[0] for d in DURATIONS}
    for ticks in range(1, 4 * Q + 1):
        parts = split_ticks(ticks)
        assert sum(p[0] for p in parts) == ticks
        assert all(p[0] in allowed for p in parts)
