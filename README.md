# Flow

A from-scratch Flow Free work-alike for Linux desktop and Linux mobile
(Phosh / Plasma Mobile). Single-file Python + GTK4/libadwaita app. For
personal use; no assets or code from the original game.

## Play

- Drag from a colored dot to draw a pipe; connect it to its matching dot.
- Drawing across another pipe cuts it; drag backwards to undo your own pipe.
- Win by connecting every pair **and** filling every cell.
- Solved boards: tap anywhere for the next puzzle.
- **Hint** fills in one flow; ⟳ / ⤺ gives a new puzzle or restarts a set level.

## Modes

- **Quick Play** — endless random squares, 5×5 to 10×10 (size picker on the row).
- **Level Packs** — 10 packs, 165 fixed levels: Starter, Classic 6×6/7×7,
  Big, Jumbo, Rectangles, Courtyards (holes), Crosses, Octagons, Expert
  (long-pipe hard mode). Progress is remembered per pack.
- **Daily Puzzles** — 3–10 puzzles seeded from the date, ramping small to
  large with mixed shapes. Finish the whole set to extend your 🔥 streak;
  miss a day and it resets.

Every level is generated deterministically from a seed: full-coverage
solvable by construction, and taut Flow Free style — no color's solution
ever fills a 2×2 block. Shaped boards (crosses, octagons, courtyards,
rectangles) are checkerboard-parity balanced so full coverage stays
possible. Up to 16 colors.

## Run from source

```sh
python3 flowfree.py
```

Dependencies: `gtk4`, `libadwaita`, `python3-gobject` — preinstalled on
GNOME/Phosh systems. On Debian/Mobian: `apt install python3-gi gir1.2-adw-1`.

## Flatpak

CI builds bundles on version tags (`v*`); grab `flowfree-x86_64.flatpak` /
`flowfree-aarch64.flatpak` from the workflow artifacts, or build locally:

```sh
./build-all.sh              # both arches (aarch64 needs qemu binfmt)
./build-all.sh --install    # also install the host-arch bundle
```

Install a bundle on the device:

```sh
flatpak install --user flowfree-aarch64.flatpak
```

Runtime: `org.gnome.Platform//50` (install from Flathub for the matching
arch). Tests: `pytest tests/`.

All progress (quick-play size, pack completion, daily streak) lives in
`~/.local/share/flowfree/state.json` (under `~/.var/app/land.rob.Flow/`
for the flatpak).
