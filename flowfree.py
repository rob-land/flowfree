#!/usr/bin/env python3
"""Flow — a Flow Free work-alike for Linux (desktop + mobile/Phosh).

Connect matching pairs of dots with pipes. Pipes may not cross, and the
board must be completely filled to win. Levels are generated determin-
istically from seeds, so "set" level packs and daily puzzles are stable.
Solutions are always taut: no color ever fills a full 2x2 block.
"""

import json
import math
import os
import random
import sys
import zlib
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

APP_ID = "land.rob.flow"
STATE_DIR = os.path.join(GLib.get_user_data_dir(), "flowfree")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Classic bright palette on a dark board (16 colors, like the original).
COLORS = [
    "#e53935", "#43a047", "#1e88e5", "#fdd835",  # red green blue yellow
    "#fb8c00", "#00acc1", "#d81b60", "#8e24aa",  # orange cyan pink purple
    "#6d4c41", "#f5f5f5", "#9e9e9e", "#c0ca33",  # brown white gray lime
    "#00796b", "#283593", "#d2b48c", "#e040fb",  # teal indigo tan magenta
]

BG = (0.055, 0.055, 0.075)
CELL_BG = (0.082, 0.082, 0.11)
GRID = (0.17, 0.17, 0.21)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def adjacent(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def stable_seed(text):
    """Deterministic across runs (unlike hash())."""
    return zlib.crc32(text.encode()) & 0x7FFFFFFF


# -------------------------------------------------------------------- shapes

def shape_cells(spec):
    """Cell set for a board spec tuple. All shapes are checkerboard-parity
    balanced (a bipartite grid needs |black-white| <= 1 for a Hamiltonian
    path, which full coverage requires)."""
    kind = spec[0]
    if kind == "square":
        n = spec[1]
        return {(r, c) for r in range(n) for c in range(n)}
    if kind == "rect":
        w, h = spec[1], spec[2]
        return {(r, c) for r in range(h) for c in range(w)}
    if kind == "octo":  # square minus 2x2 corners
        n = spec[1]
        cells = {(r, c) for r in range(n) for c in range(n)}
        for r0 in (0, n - 2):
            for c0 in (0, n - 2):
                cells -= {(r0 + dr, c0 + dc) for dr in (0, 1) for dc in (0, 1)}
        return cells
    if kind == "court":  # square with a centered hole (h even keeps parity)
        n, h = spec[1], spec[2]
        cells = {(r, c) for r in range(n) for c in range(n)}
        o = (n - h) // 2
        return cells - {(o + dr, o + dc) for dr in range(h) for dc in range(h)}
    if kind == "plus":  # square minus kxk corners (k even keeps parity)
        n, k = spec[1], spec[2]
        cells = {(r, c) for r in range(n) for c in range(n)}
        for r0 in (0, n - k):
            for c0 in (0, n - k):
                cells -= {(r0 + dr, c0 + dc) for dr in range(k) for dc in range(k)}
        return cells
    raise ValueError(spec)


def shape_name(spec):
    kind = spec[0]
    if kind == "square":
        return f"{spec[1]}×{spec[1]}"
    if kind == "rect":
        return f"{spec[1]}×{spec[2]}"
    return {"octo": "octagon", "court": "courtyard", "plus": "cross"}[kind] + f" {spec[1]}"


# ---------------------------------------------------------------- generation

def build_adj(cells):
    adj = {}
    for r, c in sorted(cells):
        adj[(r, c)] = [
            p for p in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)) if p in cells
        ]
    return adj


def serpentine(cells):
    """Boustrophedon path if cells form a full rectangle, else None."""
    rows = sorted({r for r, _ in cells})
    cols = sorted({c for _, c in cells})
    if len(cells) != len(rows) * len(cols):
        return None
    if {(r, c) for r in rows for c in cols} != cells:
        return None
    path = []
    for i, r in enumerate(rows):
        for c in cols if i % 2 == 0 else reversed(cols):
            path.append((r, c))
    return path


def ham_search(cells, adj, rng):
    """Hamiltonian path on an arbitrary region: Warnsdorff-ordered DFS with
    backtracking, capped expansions, random restarts. None on failure."""
    n = len(cells)
    cell_list = sorted(cells)
    for _ in range(60):
        start = min(rng.sample(cell_list, min(6, n)), key=lambda c: len(adj[c]))
        path, visited = [start], {start}

        def successors(cell):
            opts = [nb for nb in adj[cell] if nb not in visited]
            rng.shuffle(opts)
            opts.sort(key=lambda nb: sum(1 for x in adj[nb] if x not in visited))
            return opts

        iters = [iter(successors(start))]
        expansions = 0
        while iters and expansions < 30000:
            if len(path) == n:
                return path
            nxt = next(iters[-1], None)
            expansions += 1
            if nxt is None:
                iters.pop()
                visited.discard(path.pop())
            else:
                path.append(nxt)
                visited.add(nxt)
                iters.append(iter(successors(nxt)))
    return None


def backbite(path, adj, rng, iters):
    """Randomize a Hamiltonian path in place (backbite moves)."""
    for _ in range(iters):
        if rng.random() < 0.5:
            path.reverse()
        head = path[0]
        options = [p for p in adj[head] if p != path[1]]
        if not options:
            continue
        pivot = rng.choice(options)
        i = path.index(pivot)
        path[:i] = reversed(path[:i])


def ham_path(cells, adj, rng):
    path = serpentine(cells) or ham_search(cells, adj, rng)
    if path is not None:
        backbite(path, adj, rng, len(path) * 30)
    return path


def taut(segs, cells):
    for seg in segs:
        s = set(seg)
        for r, c in seg:
            if (r + 1, c) in s and (r, c + 1) in s and (r + 1, c + 1) in s:
                return False
    return True


def block_intervals(path, cells):
    """For each full 2x2 block in the region, the cut range [lo, hi] that
    splits its cells into different flows. A cut at c separates path[c-1]
    and path[c]; the block stays one color unless a cut lands in
    [min_pos+1, max_pos]. Sorted by hi for greedy stabbing."""
    pos = {cell: i for i, cell in enumerate(path)}
    ivals = []
    for r, c in sorted(cells):
        block = [(r, c), (r + 1, c), (r, c + 1), (r + 1, c + 1)]
        if all(b in cells for b in block):
            ps = sorted(pos[b] for b in block)
            ivals.append((ps[0] + 1, ps[3]))
    ivals.sort(key=lambda iv: iv[1])
    return ivals


def cut_taut(path, ivals, target_flows, rng):
    """Cut positions stabbing every 2x2 interval, all gaps >= 3. Greedy over
    intervals by right end, cutting near each right end (with a little
    randomness). None if the path needs more than len(COLORS) flows."""
    total = len(path)
    cuts = []
    for lo, hi in ivals:
        if cuts and cuts[-1] >= lo:
            continue
        low = max(lo, 3, cuts[-1] + 3 if cuts else 3)
        high = min(hi, total - 3)
        if low > high:
            return None
        cuts.append(rng.randint(max(low, high - 2), high))
    if len(cuts) + 1 > len(COLORS):
        return None
    for _ in range(60):  # pad with extra cuts up to the target flow count
        if len(cuts) + 1 >= target_flows:
            break
        c = rng.randint(3, total - 3)
        if all(abs(c - b) >= 3 for b in [0] + cuts + [total]):
            cuts.append(c)
            cuts.sort()
    segs, prev = [], 0
    for c in cuts + [total]:
        segs.append(path[prev:c])
        prev = c
    return segs


DIFF_DIVISOR = {"easy": 4.5, "normal": 5.5, "hard": 7.5}


def generate_level(cells, seed, difficulty="normal"):
    """Solution segments {color_index: [cells...]} for a board region.

    The region is covered by a random Hamiltonian path cut into flows of
    >= 3 cells so that the solution is taut (no color fills a 2x2 block).
    Difficulty tunes the target flow count: harder = fewer, longer pipes.
    Deterministic for a given (cells, seed, difficulty).
    """
    rng = random.Random(seed)
    adj = build_adj(cells)
    n = len(cells)
    target = max(3, min(round(n / DIFF_DIVISOR[difficulty]), len(COLORS)))
    best, best_score = None, None
    for _ in range(30):
        path = ham_path(cells, adj, rng)
        if path is None:
            continue
        ivals = block_intervals(path, cells)
        for _ in range(25):
            segs = cut_taut(path, ivals, target, rng)
            if segs is None:
                continue
            adj_pairs = sum(1 for s in segs if adjacent(s[0], s[-1]))
            score = (adj_pairs, abs(len(segs) - target))
            if best is None or score < best_score:
                best, best_score = segs, score
            if score == (0, 0):
                return {ci: seg for ci, seg in enumerate(segs)}
        if best is not None and best_score[0] == 0:
            break
    if best is None:  # astronomically unlikely; reroll deterministically
        return generate_level(cells, seed + 1, difficulty)
    return {ci: seg for ci, seg in enumerate(best)}


# --------------------------------------------------------------------- packs

def _levels(shapes, diff, count):
    return [(shapes[i * len(shapes) // count], diff) for i in range(count)]


PACKS = [
    {"id": "starter", "name": "Starter", "desc": "Gentle 5×5 warm-ups",
     "levels": _levels([("square", 5)], "easy", 20)},
    {"id": "classic6", "name": "Classic 6×6", "desc": "The standard grind",
     "levels": _levels([("square", 6)], "normal", 20)},
    {"id": "classic7", "name": "Classic 7×7", "desc": "A step up",
     "levels": _levels([("square", 7)], "normal", 20)},
    {"id": "big", "name": "Big Boards", "desc": "8×8 squares",
     "levels": _levels([("square", 8)], "normal", 15)},
    {"id": "jumbo", "name": "Jumbo", "desc": "9×9 and 10×10 squares",
     "levels": _levels([("square", 9), ("square", 10)], "normal", 15)},
    {"id": "rect", "name": "Rectangles", "desc": "Wide boards",
     "levels": _levels([("rect", 7, 5), ("rect", 8, 5), ("rect", 8, 6),
                        ("rect", 9, 6), ("rect", 10, 7)], "normal", 15)},
    {"id": "court", "name": "Courtyards", "desc": "Boards with a hole in the middle",
     "levels": _levels([("court", 6, 2), ("court", 8, 2), ("court", 8, 4),
                        ("court", 10, 2), ("court", 10, 4)], "normal", 15)},
    {"id": "cross", "name": "Crosses", "desc": "Plus-shaped boards",
     "levels": _levels([("plus", 7, 2), ("plus", 9, 2), ("plus", 11, 4)],
                       "normal", 15)},
    {"id": "octo", "name": "Octagons", "desc": "Squares with the corners cut off",
     "levels": _levels([("octo", 7), ("octo", 8), ("octo", 9), ("octo", 10)],
                       "normal", 15)},
    {"id": "expert", "name": "Expert", "desc": "Big boards, long pipes",
     "levels": _levels([("square", 9), ("square", 10)], "hard", 15)},
]


def pack_level_seed(pack_id, idx):
    return stable_seed(f"pack:{pack_id}:{idx}")


# --------------------------------------------------------------------- daily

def daily_levels(date_str):
    """The day's puzzle list: [(spec, seed, difficulty)], 3-10 of them,
    ramping from small to large. Deterministic per date."""
    rng = random.Random(stable_seed("daily:" + date_str))
    count = rng.randint(3, 10)
    max_n = rng.choice([8, 9, 10])
    levels = []
    for i in range(count):
        t = i / max(count - 1, 1)
        n = round(5 + t * (max_n - 5))
        options = [("square", n), ("square", n)]
        if n >= 6:
            options.append(("rect", n + 1, n - 1))
        if n >= 7:
            options.append(("octo", n))
        if n >= 6 and n % 2 == 0:
            options.append(("court", n, 2))
        if n >= 7 and n % 2 == 1:
            options.append(("plus", n, 2))
        spec = rng.choice(options)
        diff = "hard" if i == count - 1 and rng.random() < 0.5 else "normal"
        levels.append((spec, stable_seed(f"daily:{date_str}:{i}"), diff))
    return levels


def normalize_daily(state, today):
    d = state.setdefault("daily", {})
    if d.get("date") != today:
        d["date"] = today
        d["done"] = []
    d.setdefault("streak", 0)
    d.setdefault("last", None)
    d.setdefault("done", [])
    return d


def record_daily_win(state, today, idx, total):
    d = normalize_daily(state, today)
    if idx not in d["done"]:
        d["done"].append(idx)
    if len(d["done"]) >= total and d["last"] != today:
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        d["streak"] = d["streak"] + 1 if d["last"] == yesterday else 1
        d["last"] = today
    return d


def current_streak(state, today):
    d = normalize_daily(state, today)
    if d["last"] is None:
        return 0
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    return d["streak"] if d["last"] in (today, yesterday) else 0


# --------------------------------------------------------------------- board

class Board:
    def __init__(self, spec, seed, difficulty="normal"):
        self.spec = spec
        self.seed = seed
        self.cells = frozenset(shape_cells(spec))
        self.rows = max(r for r, _ in self.cells) + 1
        self.cols = max(c for _, c in self.cells) + 1
        self.solution = generate_level(self.cells, seed, difficulty)
        self.endpoints = {c: (s[0], s[-1]) for c, s in self.solution.items()}
        self.reset()

    def reset(self):
        self.paths = {c: [] for c in self.endpoints}
        self.active = None
        self.moves = 0
        self.last_moved = None
        self.solved = False

    def endpoint_at(self, cell):
        for c, (a, b) in self.endpoints.items():
            if cell == a or cell == b:
                return c
        return None

    def path_at(self, cell):
        for c, p in self.paths.items():
            if cell in p:
                return c
        return None

    def flow_done(self, c):
        p = self.paths[c]
        a, b = self.endpoints[c]
        return len(p) > 1 and {p[0], p[-1]} == {a, b}

    def covered(self):
        return sum(len(p) for p in self.paths.values())

    def flows_done(self):
        return sum(1 for c in self.paths if self.flow_done(c))

    def check_win(self):
        self.solved = (
            self.flows_done() == len(self.endpoints)
            and self.covered() == len(self.cells)
        )
        return self.solved

    # -- interaction ---------------------------------------------------------

    def grab(self, cell):
        c = self.endpoint_at(cell)
        if c is not None:
            self.paths[c] = [cell]
            self.active = c
        else:
            c = self.path_at(cell)
            if c is None:
                return False
            p = self.paths[c]
            del p[p.index(cell) + 1 :]
            self.active = c
        if self.last_moved != c:
            self.moves += 1
            self.last_moved = c
        return True

    def try_step(self, nxt):
        c = self.active
        if c is None or nxt not in self.cells:
            return False
        p = self.paths[c]
        last = p[-1]
        if nxt == last or not adjacent(last, nxt):
            return False
        if len(p) >= 2 and nxt == p[-2]:  # backtrack
            p.pop()
            return True
        if self.flow_done(c):  # complete pipes only shrink
            return False
        owner = self.endpoint_at(nxt)
        if owner is not None and owner != c:  # other colors' dots block
            return False
        if nxt in p:  # looped into itself: cut back
            del p[p.index(nxt) + 1 :]
            return True
        for c2, p2 in self.paths.items():  # cut through other pipes
            if c2 != c and nxt in p2:
                del p2[p2.index(nxt) :]
        p.append(nxt)
        return True

    def release(self):
        self.active = None
        self.check_win()

    def hint(self):
        todo = [c for c in self.paths if not self.flow_done(c)]
        if not todo:
            return False
        c = min(todo, key=lambda c: len(self.paths[c]))
        seg = list(self.solution[c])
        cells = set(seg)
        for c2, p2 in self.paths.items():
            if c2 == c:
                continue
            for i, cell in enumerate(p2):
                if cell in cells:
                    del p2[i:]
                    break
        self.paths[c] = seg
        self.moves += 1
        self.last_moved = c
        self.check_win()
        return True


# ----------------------------------------------------------------- game page

class GamePage(Adw.NavigationPage):
    """A playable board, parameterized by mode:
    {"kind": "quick"} |
    {"kind": "pack", "pack": pack_dict, "idx": int} |
    {"kind": "daily", "idx": int, "levels": [...], "date": str}
    """

    def __init__(self, win, mode):
        super().__init__(title="Flow")
        self.win = win
        self.mode = mode

        header = Adw.HeaderBar()
        hint_btn = Gtk.Button(label="Hint", tooltip_text="Solve one flow")
        hint_btn.connect("clicked", self.on_hint)
        header.pack_end(hint_btn)
        if mode["kind"] == "quick":
            btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="New puzzle")
            btn.connect("clicked", lambda *_: self.next_level())
        else:
            btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Restart level")
            btn.connect("clicked", self.on_restart)
        header.pack_end(btn)

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self.on_draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.area.add_controller(drag)

        self.status = Gtk.Label(margin_top=8, margin_bottom=12)
        self.status.add_css_class("dim-label")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.area)
        content.append(self.status)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        self.set_child(view)
        self.load_level()

    # -- level management ----------------------------------------------------

    def level_params(self):
        m = self.mode
        if m["kind"] == "quick":
            n = self.win.state["size"]
            seed = self.win.state.get("seed") or random.randrange(1 << 30)
            return ("square", n), seed, "normal", f"Quick Play {n}×{n}"
        if m["kind"] == "pack":
            pack, i = m["pack"], m["idx"]
            spec, diff = pack["levels"][i]
            return (spec, pack_level_seed(pack["id"], i), diff,
                    f"{pack['name']} · {i + 1}/{len(pack['levels'])}")
        spec, seed, diff = m["levels"][m["idx"]]
        return (spec, seed, diff,
                f"Daily · {m['idx'] + 1}/{len(m['levels'])}")

    def load_level(self):
        spec, seed, diff, title = self.level_params()
        self.board = Board(spec, seed, diff)
        self.set_title(title)
        if self.mode["kind"] == "quick":
            self.win.state["seed"] = seed
            self.win.save_state()
        self.refresh()

    def next_level(self):
        m = self.mode
        if m["kind"] == "quick":
            self.win.state["seed"] = None
            self.win.save_state()
            self.load_level()
            return
        if m["kind"] == "pack":
            total = len(m["pack"]["levels"])
            done = set(self.win.state["packs"].get(m["pack"]["id"], []))
        else:
            total = len(m["levels"])
            done = set(normalize_daily(self.win.state, m["date"])["done"])
        for step in range(1, total + 1):
            i = (m["idx"] + step) % total
            if i not in done:
                m["idx"] = i
                self.load_level()
                return
        self.win.toast("All solved — nice!")
        self.win.nav.pop()

    def on_restart(self, _btn):
        self.board.reset()
        self.refresh()

    def on_hint(self, _btn):
        if not self.board.solved and self.board.hint():
            self.after_change()

    def after_change(self):
        if self.board.solved:
            self.win.on_level_solved(self)
        self.refresh()

    def refresh(self):
        b = self.board
        pct = round(100 * b.covered() / len(b.cells))
        extra = ""
        if self.mode["kind"] == "daily":
            extra = f"  •  🔥 {current_streak(self.win.state, self.mode['date'])}"
        self.status.set_text(
            f"Flows {b.flows_done()}/{len(b.endpoints)}  •  Pipe {pct}%"
            f"  •  Moves {b.moves}{extra}"
        )
        self.area.queue_draw()

    # -- geometry ------------------------------------------------------------

    def metrics(self):
        w, h = self.area.get_width(), self.area.get_height()
        b = self.board
        cell = min((w - 16) / b.cols, (h - 16) / b.rows)
        ox = (w - cell * b.cols) / 2
        oy = (h - cell * b.rows) / 2
        return ox, oy, cell

    def cell_at(self, x, y):
        ox, oy, cell = self.metrics()
        c = int((x - ox) // cell)
        r = int((y - oy) // cell)
        if (r, c) in self.board.cells:
            return (r, c)
        return None

    # -- input ---------------------------------------------------------------

    def on_drag_begin(self, g, x, y):
        self.drag_origin = (x, y)
        if self.board.solved:
            self.next_level()
            return
        cell = self.cell_at(x, y)
        if cell and self.board.grab(cell):
            self.refresh()

    def on_drag_update(self, g, dx, dy):
        if self.board.active is None:
            return
        x, y = self.drag_origin[0] + dx, self.drag_origin[1] + dy
        target = self.cell_at(x, y)
        if target is None:
            return
        changed = False
        for _ in range((self.board.rows + self.board.cols) * 2):
            last = self.board.paths[self.board.active][-1]
            if last == target:
                break
            dr, dc = target[0] - last[0], target[1] - last[1]
            if abs(dr) >= abs(dc):
                step = (last[0] + (1 if dr > 0 else -1), last[1])
            else:
                step = (last[0], last[1] + (1 if dc > 0 else -1))
            if not self.board.try_step(step):
                if dc != 0 and abs(dr) >= abs(dc):
                    step = (last[0], last[1] + (1 if dc > 0 else -1))
                elif dr != 0:
                    step = (last[0] + (1 if dr > 0 else -1), last[1])
                else:
                    break
                if not self.board.try_step(step):
                    break
            changed = True
        if changed:
            self.refresh()

    def on_drag_end(self, g, dx, dy):
        if self.board.active is not None:
            self.board.release()
            self.after_change()

    # -- drawing -------------------------------------------------------------

    def on_draw(self, area, cr, w, h):
        b = self.board
        ox, oy, cell = self.metrics()

        cr.set_source_rgb(*BG)
        cr.paint()

        # board cells (holes stay background-dark)
        for r, c in b.cells:
            cr.set_source_rgb(*CELL_BG)
            cr.rectangle(ox + c * cell, oy + r * cell, cell, cell)
            cr.fill()
            cr.set_source_rgb(*GRID)
            cr.set_line_width(1)
            cr.rectangle(ox + c * cell + 0.5, oy + r * cell + 0.5, cell - 1, cell - 1)
            cr.stroke()

        def center(c):
            return ox + (c[1] + 0.5) * cell, oy + (c[0] + 0.5) * cell

        for c, p in b.paths.items():
            rgb = hex_rgb(COLORS[c])
            cr.set_source_rgba(*rgb, 0.16)
            for r, col in p:
                cr.rectangle(ox + col * cell + 1, oy + r * cell + 1, cell - 2, cell - 2)
            cr.fill()

        cr.set_line_cap(1)
        cr.set_line_join(1)
        for c, p in b.paths.items():
            if len(p) < 2:
                continue
            cr.set_source_rgb(*hex_rgb(COLORS[c]))
            cr.set_line_width(cell * 0.32)
            cr.move_to(*center(p[0]))
            for cellpos in p[1:]:
                cr.line_to(*center(cellpos))
            cr.stroke()

        for c, (a, e) in b.endpoints.items():
            rgb = hex_rgb(COLORS[c])
            done = b.flow_done(c)
            for dot in (a, e):
                x, y = center(dot)
                cr.set_source_rgb(*rgb)
                cr.arc(x, y, cell * 0.31, 0, 2 * math.pi)
                cr.fill()
                if done:
                    cr.set_source_rgba(1, 1, 1, 0.85)
                    cr.set_line_width(2)
                    cr.arc(x, y, cell * 0.31 + 2.5, 0, 2 * math.pi)
                    cr.stroke()

        if b.active is not None and b.paths[b.active]:
            rgb = hex_rgb(COLORS[b.active])
            x, y = center(b.paths[b.active][-1])
            cr.set_source_rgba(*rgb, 0.35)
            cr.arc(x, y, cell * 0.55, 0, 2 * math.pi)
            cr.fill()

        if b.solved:
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.rectangle(0, h / 2 - 40, w, 80)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(22)
            text = "Solved!  Tap for next"
            ext = cr.text_extents(text)
            cr.move_to((w - ext.width) / 2, h / 2 + 8)
            cr.show_text(text)


# ---------------------------------------------------------------- list pages

def action_row(title, subtitle, on_activate):
    row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
    row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    row.connect("activated", on_activate)
    return row


class PackPage(Adw.NavigationPage):
    def __init__(self, win, pack):
        super().__init__(title=pack["name"])
        self.win, self.pack = win, pack
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.flow = Gtk.FlowBox(
            max_children_per_line=5, min_children_per_line=3,
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
            row_spacing=8, column_spacing=8, valign=Gtk.Align.START,
        )
        sw = Gtk.ScrolledWindow(child=Adw.Clamp(child=self.flow))
        view.set_content(sw)
        self.set_child(view)
        self.refresh()

    def refresh(self):
        while (child := self.flow.get_first_child()) is not None:
            self.flow.remove(child)
        done = set(self.win.state["packs"].get(self.pack["id"], []))
        for i, (spec, diff) in enumerate(self.pack["levels"]):
            solved = i in done
            btn = Gtk.Button()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            num = Gtk.Label(label=f"{'✓ ' if solved else ''}{i + 1}")
            sub = Gtk.Label(label=shape_name(spec))
            sub.add_css_class("caption")
            sub.add_css_class("dim-label")
            box.append(num)
            box.append(sub)
            btn.set_child(box)
            if solved:
                btn.add_css_class("success")
            btn.connect("clicked", self.on_level, i)
            self.flow.append(btn)

    def on_level(self, _btn, idx):
        self.win.push_game({"kind": "pack", "pack": self.pack, "idx": idx})


class DailyPage(Adw.NavigationPage):
    def __init__(self, win):
        super().__init__(title="Daily Puzzles")
        self.win = win
        self.date = date.today().isoformat()
        self.levels = daily_levels(self.date)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.head = Gtk.Label()
        self.head.add_css_class("title-2")
        box.append(self.head)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        box.append(self.list)
        view.set_content(Gtk.ScrolledWindow(child=Adw.Clamp(child=box)))
        self.set_child(view)
        self.refresh()

    def refresh(self):
        d = normalize_daily(self.win.state, self.date)
        streak = current_streak(self.win.state, self.date)
        nice = date.fromisoformat(self.date).strftime("%a %b %d")
        self.head.set_text(f"{nice}  —  {len(d['done'])}/{len(self.levels)} solved  •  🔥 {streak}")
        while (row := self.list.get_first_child()) is not None:
            self.list.remove(row)
        for i, (spec, _seed, diff) in enumerate(self.levels):
            solved = i in d["done"]
            title = f"{'✓ ' if solved else ''}Puzzle {i + 1}"
            sub = shape_name(spec) + (" · hard" if diff == "hard" else "")
            self.list.append(action_row(title, sub, lambda _r, i=i: self.on_level(i)))

    def on_level(self, idx):
        self.win.push_game({"kind": "daily", "idx": idx,
                            "levels": self.levels, "date": self.date})


class HomePage(Adw.NavigationPage):
    def __init__(self, win):
        super().__init__(title="Flow")
        self.win = win
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=12, margin_bottom=24, margin_start=12, margin_end=12)

        top = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        top.add_css_class("boxed-list")
        self.quick_row = Adw.ActionRow(title="Quick Play", activatable=True)
        dd = Gtk.DropDown.new_from_strings([f"{n}×{n}" for n in range(5, 11)])
        dd.set_selected(win.state["size"] - 5)
        dd.set_valign(Gtk.Align.CENTER)
        dd.connect("notify::selected", self.on_size)
        self.quick_row.add_suffix(dd)
        self.quick_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.quick_row.connect("activated",
                               lambda *_: win.push_game({"kind": "quick"}))
        top.append(self.quick_row)
        self.daily_row = action_row("Daily Puzzles", "",
                                    lambda *_: win.nav.push(DailyPage(win)))
        top.append(self.daily_row)
        box.append(top)

        lbl = Gtk.Label(label="Level Packs", xalign=0)
        lbl.add_css_class("title-4")
        box.append(lbl)
        self.pack_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.pack_list.add_css_class("boxed-list")
        self.pack_rows = {}
        for pack in PACKS:
            row = action_row(pack["name"], pack["desc"],
                             lambda _r, p=pack: win.nav.push(PackPage(win, p)))
            self.pack_rows[pack["id"]] = row
            self.pack_list.append(row)
        box.append(self.pack_list)

        view.set_content(Gtk.ScrolledWindow(child=Adw.Clamp(child=box)))
        self.set_child(view)
        self.refresh()

    def on_size(self, dd, _p):
        self.win.state["size"] = dd.get_selected() + 5
        self.win.state["seed"] = None
        self.win.save_state()

    def refresh(self):
        st = self.win.state
        today = date.today().isoformat()
        d = normalize_daily(st, today)
        n = len(daily_levels(today))
        streak = current_streak(st, today)
        self.quick_row.set_subtitle(f"Endless random puzzles · {st.get('wins', 0)} solved")
        self.daily_row.set_subtitle(
            f"{len(d['done'])}/{n} solved today · 🔥 {streak}-day streak")
        for pack in PACKS:
            done = len(set(st["packs"].get(pack["id"], [])))
            self.pack_rows[pack["id"]].set_subtitle(
                f"{pack['desc']} · {done}/{len(pack['levels'])}")


# ------------------------------------------------------------------- window

class FlowWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Flow")
        self.set_default_size(420, 680)
        self.state = self.load_state()

        self.nav = Adw.NavigationView()
        self.home = HomePage(self)
        self.nav.add(self.home)
        self.nav.connect("popped", self.on_popped)
        self.toasts = Adw.ToastOverlay(child=self.nav)
        self.set_content(self.toasts)

    def load_state(self):
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
        except Exception:
            s = {}
        s["size"] = min(max(int(s.get("size", 6)), 5), 10)
        s.setdefault("wins", 0)
        s.setdefault("seed", None)
        s.setdefault("packs", {})
        return s

    def save_state(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f)
        except OSError:
            pass

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def push_game(self, mode):
        self.nav.push(GamePage(self, mode))

    def on_popped(self, _nav, _page):
        page = self.nav.get_visible_page()
        if hasattr(page, "refresh"):
            page.refresh()

    def on_level_solved(self, game):
        self.state["wins"] = self.state.get("wins", 0) + 1
        m = game.mode
        if m["kind"] == "quick":
            self.state["seed"] = None
            self.toast("Solved! Tap the board for another")
        elif m["kind"] == "pack":
            done = self.state["packs"].setdefault(m["pack"]["id"], [])
            if m["idx"] not in done:
                done.append(m["idx"])
            total = len(m["pack"]["levels"])
            if len(done) >= total:
                self.toast(f"{m['pack']['name']} pack complete! 🎉")
            else:
                self.toast(f"Solved! {len(done)}/{total} in this pack")
        else:
            total = len(m["levels"])
            d = record_daily_win(self.state, m["date"], m["idx"], total)
            if len(d["done"]) >= total:
                self.toast(f"Daily set complete! 🔥 {d['streak']}-day streak")
            else:
                self.toast(f"Solved! {len(d['done'])}/{total} today")
        self.save_state()
        self.home.refresh()


class FlowApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or FlowWindow(self)
        win.present()


if __name__ == "__main__":
    sys.exit(FlowApp().run(sys.argv))
