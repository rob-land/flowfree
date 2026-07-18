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

Install from the shared signed repo (x86_64 and aarch64):

```sh
flatpak remote-add --user rob-land \
  https://rob-land.github.io/flatpak-repo/rob-land.flatpakrepo
flatpak install --user rob-land land.rob.flow
```

CI builds both arches natively on every push to main and uploads bundles
plus OSTree repo tars to the rolling `continuous` release, which the
[flatpak-repo](https://github.com/rob-land/flatpak-repo) aggregator
merges, signs, and publishes. Direct-install bundles
(`flowfree-<arch>.flatpak`) are on the continuous release; or build
locally:

```sh
./build-all.sh              # both arches (aarch64 needs qemu binfmt)
./build-all.sh --install    # also install the host-arch bundle
```

Runtime: `org.gnome.Platform//50`. Tests: `pytest tests/`.

All progress (quick-play size, pack completion, daily streak) lives in
`~/.local/share/flowfree/state.json` (under `~/.var/app/land.rob.flow/`
for the flatpak).
