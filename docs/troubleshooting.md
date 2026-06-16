# Troubleshooting

## `Option 'z_offset' in section 'prtouch_v3' must be specified`

Klipper halts at startup because your printer's `[prtouch_v3]` probe has no
saved `z_offset`. This installer never writes to `[prtouch_v3]` — it only
adds `[screws_tilt_adjust]` — so the value was already missing or got lost
from the `#*#` SAVE_CONFIG block at the bottom of `printer.cfg` (a firmware
reset, a hand-edit, or restoring an older `printer.cfg` backup will do it).

**Fix** (any one):

1. Restore the auto-backup this installer made:
   ```
   python install_k2.py --host PRINTER_IP --revert
   ```
   It copies back the `printer.cfg` saved before the change.

2. Re-run probe Z calibration so Klipper re-saves `z_offset`, then
   `SAVE_CONFIG`.

3. As a stop-gap, add `z_offset: 0` under `[prtouch_v3]` to let Klipper
   boot, then calibrate properly.

> Note: installer versions before the SAVE_CONFIG-aware fix appended
> `[screws_tilt_adjust]` *after* the `#*#` autosave block; a later
> `SAVE_CONFIG` could then clobber the autosave region (including
> `z_offset`). Re-pull this repo and re-run the installer to get the fixed
> placement.

## `SCREWS_TILT_CALCULATE: 'list' object has no attribute 'bed_z'`

You're using upstream Klipper's `screws_tilt_adjust.py` instead of the K2-patched one. Upstream uses the modern 3-arg probe-helper callback (`phoming, offsets, positions`) with `.bed_z` attribute access; Creality's K2 fork still uses the older 2-arg form with list-based positions.

**Fix**: replace `/usr/share/klipper/klippy/extras/screws_tilt_adjust.py` with the patched version from this repo, or re-run the installer.

## `SCREWS_TILT_CALCULATE: Must have at least three screws`

The `[screws_tilt_adjust]` section in your `printer.cfg` has fewer than 3 `screw1` / `screw2` / `screw3` entries. Upstream requires minimum 3 to triangulate the bed plane.

**Fix**: the installer writes 4 by default. Check you didn't remove any.

## Klipper won't start after install

Common causes:

1. `printer.cfg` has a syntax error from the appended section. Check the last few lines:
   ```sh
   ssh root@PRINTER tail -30 /mnt/UDISK/printer_data/config/printer.cfg
   ```
   Look for unclosed sections or a missing blank line before `[screws_tilt_adjust]`.

2. The patched module itself has a parse error. Verify:
   ```sh
   ssh root@PRINTER 'python3 -c "import ast; \
     ast.parse(open(\"/usr/share/klipper/klippy/extras/screws_tilt_adjust.py\").read()); \
     print(\"OK\")"'
   ```

3. Revert and try again:
   ```
   python install_k2.py --host PRINTER_IP --revert
   ```

## "Turn screws" output makes the bed worse

Your `screw_thread` config value has the wrong rotation direction. Klipper calculates adjustment direction based on this: if it says `CW` and the screw tightens counter-clockwise, you'll move the bed the wrong way.

**Fix**: in `printer.cfg`, flip the `CW` ↔ `CCW` part:

```ini
screw_thread: CCW-M4    ; if it was CW-M4
```

Restart Klipper and re-test. Most Creality bed leveling screws are `CW-M4` (the installer default), but mods and refurbs vary.

## Probe fails / times out / crashes into bed

The probe is trying to reach a point it can't touch safely. Your screw coordinates may be:

1. **Outside the safe probe area** — too close to a wall or edge. Move them a few mm inward.
2. **On the wrong part of the bed** — probing the clamp instead of the bed surface. Measure more carefully.
3. **Above a raised feature** — avoid any stickers or bed accessories.

Edit `screw1` through `screw4` in `printer.cfg` to coordinates where the probe can physically reach the bed surface cleanly.

## Unknown gcode command: `SCREWS_TILT_CALCULATE`

The module didn't load.

**Check**:

```sh
ssh root@PRINTER grep -iE 'screws_tilt_adjust|SCREWS_TILT' /mnt/UDISK/printer_data/logs/klippy.log | tail
```

If nothing matches, `printer.cfg` doesn't have the section, or the extras module isn't at the right path. Verify both:

```sh
ssh root@PRINTER 'ls -la /usr/share/klipper/klippy/extras/screws_tilt_adjust.py'
ssh root@PRINTER 'grep "^\[screws_tilt_adjust\]" /mnt/UDISK/printer_data/config/printer.cfg'
```

Both should return something. If either is missing, re-run the installer.

## Results differ wildly between runs

Usually a thermal or mechanical issue, not the helper's fault:

- **Bed not heated** — probe on a cold bed vs hot bed gives different readings (textured PEI warps slightly with temperature). Heat the bed to your typical print temp before running.
- **Gantry not square** — on K2 Plus (dual Z), run `Z_TILT_ADJUST` first. `SCREWS_TILT_CALCULATE` assumes the gantry is already square to the bed.
- **Strain gauge needs warm-up** — first probe after power-on is sometimes noisy. Run `G28 Z` once and let it settle for 10 seconds before `SCREWS_TILT_CALCULATE`.

## Getting help

Open an issue at [github.com/grant0013/K2-Screws-Tilt/issues](https://github.com/grant0013/K2-Screws-Tilt/issues) with:

- Printer model + firmware version
- Full output of `SCREWS_TILT_CALCULATE`
- `tail -100 /mnt/UDISK/printer_data/logs/klippy.log` from just after the failing command
- Your `[screws_tilt_adjust]` section from `printer.cfg`
