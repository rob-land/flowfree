"""Logic tests for Flow: generation, packs, daily sets, streaks, gameplay.

These import the GTK module but never open a display; only pure logic runs.
"""

import importlib.util
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ff", os.path.join(HERE, "..", "flowfree.py"))
ff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ff)


def check_level(cells, sol, ctx):
    got = [c for seg in sol.values() for c in seg]
    assert len(got) == len(cells) and set(got) == set(cells), (ctx, "coverage")
    for seg in sol.values():
        assert len(seg) >= 3, (ctx, "short segment")
        assert all(ff.adjacent(seg[i], seg[i + 1]) for i in range(len(seg) - 1)), (ctx, "contiguity")
        s = set(seg)
        for r, c in seg:
            assert not ((r + 1, c) in s and (r, c + 1) in s and (r + 1, c + 1) in s), (ctx, "2x2 block")


ALL_SHAPES = [
    ("square", 5), ("square", 10), ("rect", 10, 7), ("octo", 7), ("octo", 10),
    ("court", 6, 2), ("court", 10, 4), ("plus", 7, 2), ("plus", 9, 2), ("plus", 11, 4),
]


def test_shapes_parity_and_connectivity():
    for spec_ in ALL_SHAPES:
        cells = ff.shape_cells(spec_)
        black = sum(1 for r, c in cells if (r + c) % 2 == 0)
        assert abs(black - (len(cells) - black)) <= 1, (spec_, "parity")
        adj = ff.build_adj(cells)
        seen, todo = set(), [next(iter(cells))]
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            todo += [p for p in adj[x] if p not in seen]
        assert seen == cells, (spec_, "connectivity")


def test_all_pack_levels():
    for pack in ff.PACKS:
        for i, (spec_, diff) in enumerate(pack["levels"]):
            cells = ff.shape_cells(spec_)
            sol = ff.generate_level(cells, ff.pack_level_seed(pack["id"], i), diff)
            check_level(cells, sol, (pack["id"], i))


def test_daily_deterministic_and_valid():
    for k in range(10):
        ds = (date(2026, 7, 1) + timedelta(days=k)).isoformat()
        lv = ff.daily_levels(ds)
        assert lv == ff.daily_levels(ds)
        assert 3 <= len(lv) <= 10
        for i, (spec_, seed, diff) in enumerate(lv):
            cells = ff.shape_cells(spec_)
            check_level(cells, ff.generate_level(cells, seed, diff), ("daily", ds, i))


def test_streaks():
    st = {}
    assert ff.record_daily_win(st, "2026-07-15", 0, 1)["streak"] == 1
    assert ff.record_daily_win(st, "2026-07-16", 0, 1)["streak"] == 2
    assert ff.record_daily_win(st, "2026-07-18", 0, 1)["streak"] == 1  # gap resets
    st2 = {"daily": {"date": "x", "done": [], "streak": 5, "last": "2026-07-16"}}
    assert ff.current_streak(st2, "2026-07-17") == 5  # alive via yesterday
    assert ff.current_streak(st2, "2026-07-19") == 0  # broken
    st3 = {}
    d = ff.record_daily_win(st3, "2026-07-15", 0, 3)
    assert d["streak"] == 0 and d["last"] is None  # partial day: no award
    ff.record_daily_win(st3, "2026-07-15", 1, 3)
    d = ff.record_daily_win(st3, "2026-07-15", 2, 3)
    assert d["streak"] == 1 and d["last"] == "2026-07-15"
    assert ff.record_daily_win(st3, "2026-07-15", 2, 3)["streak"] == 1  # no double count


def test_replay_solution_wins():
    for spec_ in [("plus", 9, 2), ("court", 8, 4), ("octo", 10), ("rect", 8, 6), ("square", 7)]:
        b = ff.Board(spec_, 12345, "normal")
        for c, seg in b.solution.items():
            b.grab(seg[0])
            for cell in seg[1:]:
                assert b.try_step(cell), (spec_, c, cell)
            b.release()
        assert b.solved, spec_


def test_pipes_blocked_by_holes_and_dots():
    b = ff.Board(("court", 8, 4), 7, "normal")
    holes = {(r, c) for r in range(8) for c in range(8)} - b.cells
    color = next(iter(b.solution))
    start = b.endpoints[color][0]
    b.grab(start)
    for hole in holes:
        if ff.adjacent(start, hole):
            assert not b.try_step(hole)
    other = [c for c in b.endpoints if c != color][0]
    for ep in b.endpoints[other]:
        if ff.adjacent(start, ep):
            assert not b.try_step(ep)
