"""Following bars through a video of any layout (generic.py), on made-up bars: each bar has its own content."""
import numpy as np

from tabreader.generic import SIG, Bar, View, as_pages, link_views, play_order, track


def bar(content: int, slot: int = 0, x0: int = 0, w: int = 400) -> Bar:
    rng = np.random.default_rng(content)
    return Bar(slot, x0, x0 + w, (rng.random(SIG[::-1]) > 0.7).astype(np.float32))


def line(contents, slot=0):
    return [bar(c, slot, 100 + 400 * i) for i, c in enumerate(contents)]


def test_a_strip_that_scrolls_keeps_its_bars_and_adds_new_ones():
    views = [View(0, 99, line([1, 2, 3, 4])), View(100, 199, line([3, 4, 5, 6]))]
    assert link_views(views) == 6
    assert views[1].ids[:2] == views[0].ids[2:]  # bars 3 and 4 scrolled left: the same bars


def test_lines_that_move_up_one_at_a_time_are_not_doubled():
    # two lines on screen; the second moves up when it is played (17-20 + 21-24, then 21-24 + 25-28)
    views = [View(0, 99, line([17, 18, 19, 20], 0) + line([21, 22, 23, 24], 1)),
             View(100, 199, line([21, 22, 23, 24], 0) + line([25, 26, 27, 28], 1))]
    assert link_views(views) == 12


def test_a_page_flip_and_a_repeat_played_again_are_new_bars():
    views = [View(0, 99, line([1, 2, 3, 4])), View(100, 199, line([5, 6, 7, 8])), View(200, 299, line([1, 2, 3, 4]))]
    assert link_views(views) == 12  # the second time round is played again, so written out again


def test_the_cursor_orders_the_bars_and_without_one_pages_do():
    views = [View(0, 99, line([1, 2])), View(100, 199, line([3, 4]))]
    link_views(views)
    fps = 10.0
    cursor = [(f, 0, 150 + (f % 100) * 4) for f in range(0, 200)]  # left to right over each page
    order, samples, covered = play_order(views, cursor, fps)
    assert covered and order == [0, 1, 2, 3] and samples
    order, samples, covered = play_order(views, [], fps)
    assert not covered and order == [0, 1, 2, 3]
    spans = [(p * 400, p * 400 + 400) for p in range(len(order))]
    ts, xs = track(order, spans, {}, [], views, fps, False)
    # page 1 from 0 s, page 2 from 10 s: each page's two bars share its time on screen
    assert np.interp([0, 5, 10, 15], ts, xs).round().tolist() == [0, 400, 800, 1200]


def test_without_a_cursor_a_page_that_comes_back_with_a_second_ending_is_played_again():
    pages = [[1, 2, 3, 4], [1, 2, 3, 5], [6, 7, 8, 9], [10, 11, 12, 13], [14, 15, 16, 17], [18, 19, 20, 21]]
    views = [View(100 * i, 100 * i + 99, line(p)) for i, p in enumerate(pages)]
    views.append(View(600, 602, line([21])))  # a moment between pages: no page of its own
    link_views(views)
    played = as_pages(views)
    assert len(played) == 6 and sum(len(v.ids) for v in played) == 24


def test_a_bar_the_cursor_comes_back_to_is_played_again():
    views = [View(0, 399, line([1, 2]))]
    link_views(views)
    fps = 10.0
    # bar 1, bar 2, back to bar 1 (a repeat), bar 2 again; a 2-frame blip into bar 1 at the edge is jitter
    xs = [150] * 50 + [550] * 48 + [150] * 2 + [550] * 50 + [150] * 100 + [550] * 100
    order, samples, covered = play_order(views, [(f, 0, x) for f, x in enumerate(xs)], fps)
    assert covered and order == [0, 1, 0, 1]
