# K2-Screws-Tilt

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Klipper compatible](https://img.shields.io/badge/Klipper-compatible-5a9e5a.svg)](https://www.klipper3d.org/)
[![Tested on K2 Combo](https://img.shields.io/badge/tested-K2%20Combo-00a1ff.svg)](#compatibility)

**`SCREWS_TILT_CALCULATE` for Creality K2.**

Brings Klipper's manual bed-level helper — the one that probes each bed-screw position and tells you "front-left: turn 1/4 CW" — to the Creality K2 family. Uses your printer's existing strain-gauge probe. No additional hardware.

> ❤️ **Enjoying K2-Screws-Tilt?** Free forever (GPL v3) — if it saved you time, [buy me a coffee](https://buymeacoffee.com/harktron) or tip BTC: `bc1q4tlvaufnaefshdjjuxm5xkcrdazefhap52hdja`. No obligation, test reports on K2 variants help just as much.

## The problem

Upstream Klipper's [`screws_tilt_adjust.py`](https://www.klipper3d.org/Manual_Level.html#screws-tilt-adjust) uses the modern probe-helper API: the finalize callback receives `(phoming, offsets, positions)` with `positions` as objects that expose a `.bed_z` attribute.

Creality's Klipper fork on the K2 still uses the older 2-arg callback: `(offsets, positions)` with `positions` as plain `[x, y, z]` lists. Dropping upstream's file onto a K2 crashes with `AttributeError: 'list' object has no attribute 'bed_z'` the first time you run `SCREWS_TILT_CALCULATE`.

## What this fork does

- Swaps the finalize signature to the 2-arg form
- Swaps `pos.bed_z` → `pos[2]`
- Everything else is unchanged from upstream Klipper master

No other behaviour changes. The actual tilt calculation, thread math, and CW/CCW output are upstream code.

## Compatibility

| Printer | Board | Status |
|---|---|---|
| **K2 Combo** | `CR0CN200400C10` (F021) | **Confirmed working** — firmware V1.1.4.1 |
| K2 / K2 Pro | Same board (F021) | Should work, same binary — report results |
| K2 Plus | `CR0CN240319C13` (F008) | Untested — K2 Plus is dual-Z, you probably want `[z_tilt]` instead of this. Report if you try |
| K1 / K1C / K1 Max | CR4CU220812S* | Untested — may work if Creality uses the same probe-helper API there |

All untested variants will install and work structurally, but the actual math assumes a 4-screw layout at `(30,30)`, `(230,30)`, `(30,230)`, `(230,230)` — which is right for the K2 260mm bed. Other variants should edit the `[screws_tilt_adjust]` section after install with their own screw coordinates.

## Install

### Windows (one-liner, no git needed)

Open **PowerShell** (not cmd.exe) and paste:

```powershell
iwr -useb https://raw.githubusercontent.com/grant0013/K2-Screws-Tilt/main/bootstrap.ps1 | iex
```

The script checks for Python (installs via winget if missing), downloads the repo, installs `paramiko`, asks for your printer's IP, and runs the installer. No manual SSH.

### macOS / Linux / manual

```sh
git clone https://github.com/grant0013/K2-Screws-Tilt
cd K2-Screws-Tilt
pip install paramiko
python install_k2.py --host 192.168.x.x
```

Uses the Creality stock root password (`creality_2024`) by default; override with `--password MYPASS` if yours has been changed.

See [`docs/INSTALL.md`](docs/INSTALL.md) for the step-by-step the installer performs (useful if you want to do it manually, or understand what's being changed).

## Usage

After install, two-step workflow from the Fluidd / Mainsail gcode console:

```
G28
SCREWS_TILT_CALCULATE
```

Klipper probes each of the four screw positions and prints something like:

```
// front left : x=30.0, y=30.0, z=0.015
// front right: x=230.0, y=30.0, z=0.048, CW 00:04, Adjust
// back left  : x=30.0, y=230.0, z=-0.012, CCW 00:02, Adjust
// back right : x=230.0, y=230.0, z=0.031, CW 00:03, Adjust
```

Read the directions: `CW 00:04` means turn clockwise 4 minutes of an hour (so, 4/60 of a full turn). Adjust the screws by hand, re-run `SCREWS_TILT_CALCULATE`, repeat until all four report something near 0 or within your `MAX_DEVIATION` threshold.

For first-time levelling, loosening all screws first (bed sitting flat against the gantry) and then running the helper usually converges in 2–3 iterations.

### Optional parameters

```
SCREWS_TILT_CALCULATE MAX_DEVIATION=0.05   ; warn if any screw off by >0.05mm
SCREWS_TILT_CALCULATE DIRECTION=CW         ; force all adjustments to CW only
```

## Configuration

The installer appends a default `[screws_tilt_adjust]` section to `printer.cfg` sized for the K2 260mm bed:

```ini
[screws_tilt_adjust]
screw1: 30, 30
screw1_name: front left
screw2: 230, 30
screw2_name: front right
screw3: 30, 230
screw3_name: back left
screw4: 230, 230
screw4_name: back right
horizontal_move_z: 10
speed: 100
screw_thread: CW-M4   ; most K2 bed screws are M4 clockwise; check yours
```

If your printer has different screw positions (K2 Plus 350mm bed, custom mod, etc.), edit these values after install. Screw coordinates are the XY positions the probe should visit for each screw — typically 20–40mm inside each corner of the bed.

**Check your thread direction**: the `screw_thread` value tells Klipper which way is "tighter". Most Creality bed leveling screws are `CW-M4` (clockwise-to-tighten M4). If your screws tighten counter-clockwise or are a different size, change it (valid values: `CW-M3`, `CCW-M3`, `CW-M4`, `CCW-M4`, `CW-M5`, `CCW-M5`, `CW-M6`, `CCW-M6`).

## Revert

Windows: re-run the one-liner, pick option 2 at the menu. Or:

```powershell
.\install.ps1 -PrinterHost 192.168.x.x -Revert
```

Manual / Linux:

```sh
python install_k2.py --host 192.168.x.x --revert
```

Both methods restore `printer.cfg` from the on-printer backup (or the local PC backup under `%USERPROFILE%\K2-Screws-Tilt\backups\` as fallback) and remove the extras module.

## Backups

Every install automatically backs up `printer.cfg` (and the previous `screws_tilt_adjust.py` if any) to two places:

- **On printer**: `/mnt/exUDISK/.system/k2_screws_tilt_backup_<timestamp>/` (SSD, firmware-update-survivable) or `/mnt/UDISK/printer_data/config/backups/k2_screws_tilt_backup_<timestamp>/` on SSD-less printers.
- **On PC**: `%USERPROFILE%\K2-Screws-Tilt\backups\<ip>_<timestamp>\` — survives any printer-side wipe including Creality firmware updates.

Revert tries the on-printer backup first; if missing (e.g. after a firmware wipe), falls back to the local PC backup automatically.

## Companion project

[**KAMP-K2**](https://github.com/grant0013/KAMP-K2) — adaptive bed mesh + adaptive line purge for the same K2 family. Probes only the area your current print covers, scales proportionally from your `[bed_mesh] probe_count`. Same install UX as this project. If you'd like levelling *and* adaptive meshing, install both — they're designed to coexist.

## Credits

- [Klipper](https://www.klipper3d.org/) — Kevin O'Connor and contributors; `screws_tilt_adjust.py` originally written by Rui Caridade + Matthew Lloyd, GPL v3
- Companion to [KAMP-K2](https://github.com/grant0013/KAMP-K2) — adaptive mesh + line purge for the same K2 family

## Licence

GPL v3, matching upstream Klipper. See [`LICENSE.md`](LICENSE.md).
