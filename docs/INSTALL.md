# Manual install — what `install_k2.py` does, step by step

If you want to understand what the installer is doing, or install by hand, the six steps below replicate it exactly. If you just want to get going, run `python install_k2.py --host 192.168.x.x` and skip this doc.

## Prerequisites

- SSH access to the printer as `root`. Stock Creality root password is `creality_2024`.
- Klipper running (you can reach Fluidd / Mainsail on the printer).
- You want manual bed-screw levelling, not automatic gantry levelling (`[z_tilt]`). K2 Plus is dual-Z and usually wants `[z_tilt]` instead — consult its manual.

## Step 1 — Back up `printer.cfg`

```sh
ssh root@PRINTER_IP
BACKUP=/mnt/exUDISK/.system/k2_screws_tilt_backup_$(date +%Y%m%d_%H%M%S)
# fall back to UDISK if no external SSD:
[ -d /mnt/exUDISK ] || BACKUP=/mnt/UDISK/printer_data/config/backups/k2_screws_tilt_backup_$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP"
cp /mnt/UDISK/printer_data/config/printer.cfg "$BACKUP/"
```

## Step 2 — Copy the patched `screws_tilt_adjust.py` to Klipper extras

From your cloned K2-Screws-Tilt repo:

```sh
scp extras/screws_tilt_adjust.py root@PRINTER_IP:/usr/share/klipper/klippy/extras/
```

Verify it parses on the printer:

```sh
ssh root@PRINTER_IP 'python3 -c "import ast; \
  ast.parse(open(\"/usr/share/klipper/klippy/extras/screws_tilt_adjust.py\").read()); \
  print(\"parse OK\")"'
```

## Step 3 — Add `[screws_tilt_adjust]` section to `printer.cfg`

Append to `/mnt/UDISK/printer_data/config/printer.cfg`:

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
screw_thread: CW-M4
```

### Tuning the screw coordinates

The coords above are for a K2 260mm bed with screws ~30mm inside each corner. If your bed differs, measure where the actual leveling screws are and set them accordingly. Coordinates are in bed space — same XY as any other move.

The probe doesn't touch the screw head itself; it touches the *bed surface directly above* the screw. So pick a point where the bed material is flat and the probe can reach safely.

### Tuning the thread

`screw_thread` tells Klipper which direction is "tighter":

- `CW-M4` — standard K2, M4 bolt, clockwise to tighten (the usual case)
- `CCW-M4` — M4 bolt, counter-clockwise to tighten (rare)
- `CW-M3`, `CCW-M3`, `CW-M5`, `CCW-M5`, `CW-M6`, `CCW-M6` — other bolt sizes

If your first `SCREWS_TILT_CALCULATE` run tells you to turn screws in a direction that makes the bed worse, the thread setting is wrong — flip CW ↔ CCW and retry.

## Step 4 — Restart Klippy

```sh
ssh root@PRINTER_IP '/etc/init.d/klipper restart'
# wait ~10 seconds
ssh root@PRINTER_IP 'tail -50 /mnt/UDISK/printer_data/logs/klippy.log | grep -iE "screws_tilt|error"'
```

You should see no errors and a reference to `screws_tilt_adjust` in the config section of the log.

## Step 5 — Run the helper

From Fluidd / Mainsail gcode console:

```
G28
SCREWS_TILT_CALCULATE
```

Expected output:

```
// front left : x=30.0, y=30.0, z=0.000
// front right: x=230.0, y=30.0, z=0.032, CW 00:03, Adjust
// back left  : x=30.0, y=230.0, z=-0.015, CCW 00:01, Adjust
// back right : x=230.0, y=230.0, z=0.021, CW 00:02, Adjust
```

The first screw is the reference (always `0.000`); the others are shown relative to it with the turn direction and amount to match.

## Step 6 — Iterate

Adjust your screws by hand to the amounts the helper suggested, then run `SCREWS_TILT_CALCULATE` again. After 2–3 rounds all four screws should report values close to zero or within your `MAX_DEVIATION`.

## Done

Bed is now level against the gantry. For the K2 this is a one-time setup per bed change — Creality's strain-gauge probe compensates for small bed variations automatically at probe time, but a gross tilt on the mechanical bed plate has to be fixed at the screws.

If you also want adaptive bed meshing for in-print flatness compensation, see the companion project [KAMP-K2](https://github.com/grant0013/KAMP-K2).
