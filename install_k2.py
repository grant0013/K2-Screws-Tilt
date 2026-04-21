#!/usr/bin/env python3
"""
K2-Screws-Tilt auto-installer.

Deploys a patched `screws_tilt_adjust.py` to a Creality K2 over SSH and
adds the corresponding `[screws_tilt_adjust]` section to printer.cfg so
the `SCREWS_TILT_CALCULATE` gcode command works. The patch swaps the
modern 2-arg / .bed_z probe-helper API for Creality's older list-based
one.

Usage:
    python install_k2.py --host 192.168.x.x
    python install_k2.py --host 192.168.x.x --revert
    python install_k2.py --host 192.168.x.x --dry-run
    python install_k2.py --host 192.168.x.x --detect

Defaults:
    user=root, password=creality_2024 (Creality stock credential)

What this does:
    1. Detects board (F021 confirmed working; F008/F012 require testing).
    2. Backs up /mnt/UDISK/printer_data/config/printer.cfg and
       /usr/share/klipper/klippy/extras/screws_tilt_adjust.py (if
       already present) to /mnt/exUDISK/.system/k2_screws_tilt_backup_<ts>/
       (or UDISK backups dir on SSD-less printers).
    3. Also mirrors the backup to a local PC directory so it survives
       Creality firmware updates that wipe /mnt/UDISK.
    4. Copies extras/screws_tilt_adjust.py -> /usr/share/klipper/klippy/extras/
    5. Adds `[screws_tilt_adjust]` section to printer.cfg with default
       corner coordinates for the K2 260mm bed (skips if already
       present).
    6. Restarts Klippy and verifies the module loaded.

Revert:
    Removes /usr/share/klipper/klippy/extras/screws_tilt_adjust.py and
    the `[screws_tilt_adjust]` section from printer.cfg. Falls back to
    the local PC backup if the on-printer backup is missing.

Requires: paramiko (`pip install paramiko`).
"""
from __future__ import annotations

import argparse
import os
import posixpath
import re
import socket
import sys
import time

try:
    import paramiko
except ImportError:
    sys.stderr.write(
        "error: paramiko is required. Install with: pip install paramiko\n")
    sys.exit(2)


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

PRINTER_CFG = "/mnt/UDISK/printer_data/config/printer.cfg"
EXTRAS_PATH = "/usr/share/klipper/klippy/extras/screws_tilt_adjust.py"
LOCAL_MODULE = os.path.join(REPO_ROOT, "extras", "screws_tilt_adjust.py")

# Default K2 260mm bed screw positions. Screws sit ~30mm inside each
# corner of the 260x260 bed. thread=CW-M4 matches most K2 leveling
# screws; the comment in the injected block reminds the user to verify.
SCREWS_SNIPPET = """
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
screw_thread: CW-M4   ; verify -- most K2 bed screws are M4 clockwise; check yours
"""


class Installer:
    def __init__(self, host: str, user: str, password: str,
                 dry_run: bool = False, verbose: bool = False,
                 local_backup_dir: str | None = None) -> None:
        self.host = host
        self.user = user
        self.password = password
        self.dry_run = dry_run
        self.verbose = verbose
        self.local_backup_dir = local_backup_dir
        self.ssh: paramiko.SSHClient | None = None

    # ---- logging ----
    def log(self, msg: str, level: str = "info") -> None:
        prefix = {"info": " ", "ok": "+", "warn": "!", "err": "x",
                  "step": "*", "dry": "~"}.get(level, " ")
        print(f"[{prefix}] {msg}")

    # ---- ssh plumbing ----
    def connect(self) -> None:
        self.log(f"Connecting to {self.user}@{self.host}...", "step")
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh.connect(self.host, username=self.user,
                             password=self.password, timeout=10,
                             allow_agent=False, look_for_keys=False)
        except paramiko.AuthenticationException:
            self.log(f"SSH auth failed for {self.user}@{self.host}", "err")
            self.log("If you changed root's password, pass it with --password",
                     "err")
            sys.exit(1)
        except (socket.timeout, socket.error) as e:
            self.log(f"Cannot reach {self.host}: {e}", "err")
            sys.exit(1)
        self.log("Connected.", "ok")

    def close(self) -> None:
        if self.ssh:
            self.ssh.close()

    def run(self, cmd: str) -> tuple[int, str, str]:
        assert self.ssh is not None
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if self.verbose:
            self.log(f"  $ {cmd}  (rc={rc})", "info")
            if out.strip():
                self.log(f"    out: {out.strip()[:300]}", "info")
            if err.strip():
                self.log(f"    err: {err.strip()[:300]}", "info")
        return rc, out, err

    def remote_exists(self, path: str) -> bool:
        _, out, _ = self.run(f"test -e '{path}' && echo YES || echo NO")
        return "YES" in out

    def read_remote(self, path: str) -> str:
        assert self.ssh is not None
        stdin, stdout, stderr = self.ssh.exec_command(f"cat '{path}'")
        data = stdout.read()
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            raise FileNotFoundError(
                f"read_remote {path} failed: {err.strip()}")
        return data.decode("utf-8", errors="replace")

    def write_remote(self, path: str, content: str, mode: int = 0o644) -> None:
        if self.dry_run:
            self.log(f"[dry-run] would write {path} ({len(content)} bytes)",
                     "dry")
            return
        assert self.ssh is not None
        parent = posixpath.dirname(path)
        if parent:
            self.run(f"mkdir -p '{parent}'")
        octal_mode = oct(mode)[2:]
        raw = content.encode() if isinstance(content, str) else content
        # Dropbear has no SFTP. `cat > path` + piped stdin is the portable way.
        stdin, stdout, stderr = self.ssh.exec_command(
            f"cat > '{path}' && chmod {octal_mode} '{path}'")
        stdin.write(raw)
        stdin.channel.shutdown_write()
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            self.log(f"write_remote {path} failed: {err.strip()}", "err")
            raise RuntimeError(f"write_remote failed for {path}")

    # ---- checks ----
    def sanity_check(self) -> None:
        checks = [
            ("klipper config dir",
             "test -d /mnt/UDISK/printer_data/config && echo yes"),
            ("klipper extras dir",
             "test -d /usr/share/klipper/klippy/extras && echo yes"),
            ("prtouch_v3 wrapper (K2 indicator)",
             "test -f /usr/share/klipper/klippy/extras/"
             "prtouch_v3_wrapper.cpython-39.so && echo yes"),
        ]
        fails = []
        for label, cmd in checks:
            _, out, _ = self.run(cmd)
            if "yes" not in out:
                fails.append(label)
                self.log(f"  check failed: {label}", "err")
            else:
                self.log(f"  check ok: {label}", "ok")
        if fails:
            self.log("This does not look like a stock Creality K2. Aborting.",
                     "err")
            sys.exit(1)

    def detect_board(self) -> str:
        """Return F021 / F008 / F012 / unknown. F021 is confirmed working."""
        try:
            cfg = self.read_remote(PRINTER_CFG)
        except FileNotFoundError:
            return "unknown"
        header = cfg[:500]
        for tag in ("F008", "F012", "F021", "F025", "F037"):
            if re.search(rf"^#\s*{tag}\b", header, re.MULTILINE):
                return tag
        # Fall back to structural check
        if re.search(r"^\[stepper_z1\]", cfg, re.MULTILINE):
            return "F008"
        return "unknown"

    def detect(self) -> None:
        """Print machine-readable install state + board. Used by install.ps1."""
        self.sanity_check()
        installed = (self.remote_exists(EXTRAS_PATH)
                     or self._section_present(PRINTER_CFG))
        board = self.detect_board()
        print(f"K2ST_STATUS={'installed' if installed else 'fresh'}")
        print(f"K2ST_BOARD={board}")
        print(f"K2ST_HOST={self.host}")

    def _section_present(self, path: str) -> bool:
        try:
            cfg = self.read_remote(path)
        except FileNotFoundError:
            return False
        return bool(re.search(r"^\[screws_tilt_adjust\]",
                              cfg, re.MULTILINE))

    # ---- install flow ----
    def backup(self) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        if "yes" in self.run("test -d /mnt/exUDISK && echo yes")[1]:
            base = f"/mnt/exUDISK/.system/k2_screws_tilt_backup_{ts}"
        else:
            base = (f"/mnt/UDISK/printer_data/config/backups/"
                    f"k2_screws_tilt_backup_{ts}")
        self.log(f"Backing up to {base}/", "step")
        if self.dry_run:
            self.log(f"[dry-run] would create {base} and copy files", "dry")
            return
        self.run(f"mkdir -p '{base}'")
        self.run(f"cp {PRINTER_CFG} '{base}/printer.cfg'")
        self.run(f"[ -f {EXTRAS_PATH} ] && "
                 f"cp {EXTRAS_PATH} '{base}/screws_tilt_adjust.py' || true")
        self.log(f"On-printer backup saved: {base}", "ok")

        # Mirror to PC
        if self.local_backup_dir:
            safe_host = re.sub(r"[^0-9A-Za-z_.-]", "_", self.host)
            local_dir = os.path.join(self.local_backup_dir,
                                     f"{safe_host}_{ts}")
            try:
                os.makedirs(local_dir, exist_ok=True)
                with open(os.path.join(local_dir, "printer.cfg"), "w",
                          encoding="utf-8", newline="") as f:
                    f.write(self.read_remote(PRINTER_CFG))
                if self.remote_exists(EXTRAS_PATH):
                    with open(os.path.join(
                            local_dir, "screws_tilt_adjust.py"), "w",
                            encoding="utf-8", newline="") as f:
                        f.write(self.read_remote(EXTRAS_PATH))
                self.log(f"Local PC backup saved: {local_dir} "
                         "(survives printer firmware updates)", "ok")
            except Exception as e:
                self.log(f"Local backup failed: {e} (on-printer backup "
                         "still saved)", "warn")

    def copy_module(self) -> None:
        self.log("Copying patched screws_tilt_adjust.py...", "step")
        if not os.path.isfile(LOCAL_MODULE):
            self.log(f"Missing local file: {LOCAL_MODULE}", "err")
            sys.exit(1)
        with open(LOCAL_MODULE, "r", encoding="utf-8") as f:
            content = f.read()
        self.write_remote(EXTRAS_PATH, content, 0o644)
        self.log(f"  extras/screws_tilt_adjust.py -> {EXTRAS_PATH}", "ok")

    def patch_printer_cfg(self) -> None:
        cfg = self.read_remote(PRINTER_CFG)
        if re.search(r"^\[screws_tilt_adjust\]", cfg, re.MULTILINE):
            self.log("printer.cfg: [screws_tilt_adjust] already present, "
                     "skipping", "ok")
            return
        new_cfg = cfg.rstrip() + "\n" + SCREWS_SNIPPET + "\n"
        self.write_remote(PRINTER_CFG, new_cfg)
        self.log("printer.cfg: appended [screws_tilt_adjust] section "
                 "with K2 260mm bed defaults", "ok")

    def verify_parse(self) -> None:
        _, out, err = self.run(
            f"python3 -c 'import ast; "
            f"ast.parse(open(\"{EXTRAS_PATH}\").read()); print(\"ok\")'"
        )
        if "ok" not in out:
            self.log(f"screws_tilt_adjust.py parse FAILED: {err}", "err")
            sys.exit(1)
        self.log("screws_tilt_adjust.py parse ok", "ok")

    def restart_klippy(self) -> None:
        if self.dry_run:
            self.log("[dry-run] would FIRMWARE_RESTART Klippy", "dry")
            return
        self.log("Restarting Klippy...", "step")
        script = (
            "import socket, json, time\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "s.connect('/tmp/klippy_uds')\n"
            "s.send((json.dumps({'id':1,'method':'gcode/script',"
            "'params':{'script':'FIRMWARE_RESTART'}})+chr(3)).encode())\n"
            "time.sleep(0.3)\n"
        )
        self.run(f"python3 -c \"{script}\"")
        self.log("Waiting for Klippy ready (up to 60s)...", "info")
        deadline = time.time() + 60
        while time.time() < deadline:
            _, out, _ = self.run(
                "python3 -c \"import socket,json,time\n"
                "s=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
                "try: s.connect('/tmp/klippy_uds')\n"
                "except: exit(1)\n"
                "s.send((json.dumps({'id':1,'method':'info'})+chr(3)).encode())\n"
                "time.sleep(0.5); buf=b''\n"
                "s.settimeout(2)\n"
                "try:\n"
                "  while True:\n"
                "    c=s.recv(65536)\n"
                "    if not c: break\n"
                "    buf+=c\n"
                "except: pass\n"
                "for fr in buf.split(chr(3).encode()):\n"
                "  if fr.strip():\n"
                "    try:\n"
                "      r=json.loads(fr)\n"
                "      print(r['result'].get('state','?'))\n"
                "      break\n"
                "    except: pass\""
            )
            state = out.strip().splitlines()[-1] if out.strip() else ""
            if state == "ready":
                self.log("Klippy ready.", "ok")
                return
            if state == "error":
                self.log("Klippy entered error state -- check log:", "err")
                _, out, _ = self.run(
                    "tail -40 /mnt/UDISK/printer_data/logs/klippy.log "
                    "| grep -iE 'error|exception' | tail -10")
                self.log(out, "err")
                sys.exit(1)
            time.sleep(2)
        self.log("Klippy did not become ready in 60s -- check logs", "warn")

    def verify_loaded(self) -> None:
        _, out, _ = self.run(
            "grep -iE 'screws_tilt_adjust|SCREWS_TILT' "
            "/mnt/UDISK/printer_data/logs/klippy.log | tail -5")
        if "screws_tilt_adjust" in out.lower() or "SCREWS_TILT" in out:
            self.log("Module loaded (log has screws_tilt_adjust reference)",
                     "ok")
        else:
            self.log("Override log message not found -- probably a timing "
                     "false-negative. Verify manually with:\n"
                     "  ssh root@PRINTER 'printer_objects.py | grep "
                     "screws_tilt_adjust'", "warn")

    # ---- revert flow ----
    def find_latest_backup(self) -> str | None:
        for base in ["/mnt/exUDISK/.system",
                     "/mnt/UDISK/printer_data/config/backups"]:
            _, out, _ = self.run(
                f"(ls -1dt '{base}'/k2_screws_tilt_backup_* 2>/dev/null) "
                "| head -1")
            path = out.strip()
            if path:
                return path
        return None

    def find_local_backup(self) -> str | None:
        if not self.local_backup_dir or not os.path.isdir(
                self.local_backup_dir):
            return None
        safe_host = re.sub(r"[^0-9A-Za-z_.-]", "_", self.host)
        candidates = []
        for name in os.listdir(self.local_backup_dir):
            full = os.path.join(self.local_backup_dir, name)
            if (os.path.isdir(full)
                    and name.startswith(f"{safe_host}_")
                    and os.path.isfile(os.path.join(full, "printer.cfg"))):
                candidates.append((os.path.getmtime(full), full))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def revert(self) -> None:
        self.log("=== Sanity checks ===", "step")
        self.sanity_check()

        self.log("=== Finding backup ===", "step")
        backup = self.find_latest_backup()
        local_backup = self.find_local_backup()
        use_local = False
        if not backup:
            self.log("No on-printer k2_screws_tilt_backup_* directory.",
                     "warn")
            if local_backup:
                self.log(f"Using local PC backup: {local_backup}", "ok")
                backup = local_backup
                use_local = True
            else:
                self.log("No local PC backup either -- falling back to "
                         "section-removal only.", "warn")

        if self.dry_run:
            self.log(f"[dry-run] would remove {EXTRAS_PATH}", "dry")
            self.log(f"[dry-run] would strip [screws_tilt_adjust] from "
                     "printer.cfg (or restore from backup)", "dry")
            self.log("[dry-run] would FIRMWARE_RESTART", "dry")
            return

        self.log("=== Restoring configs ===", "step")
        if backup:
            if use_local:
                with open(os.path.join(backup, "printer.cfg"), "r",
                          encoding="utf-8") as f:
                    self.write_remote(PRINTER_CFG, f.read())
            else:
                self.run(f"cp '{backup}/printer.cfg' {PRINTER_CFG}")
            self.log("printer.cfg restored from backup", "ok")
        else:
            # No backup -- just strip the section we added.
            cfg = self.read_remote(PRINTER_CFG)
            new_cfg = re.sub(
                r"\n*\[screws_tilt_adjust\].*?(?=^\[|\Z)",
                "\n",
                cfg, count=1,
                flags=re.MULTILINE | re.DOTALL)
            if new_cfg != cfg:
                self.write_remote(PRINTER_CFG, new_cfg)
                self.log("printer.cfg: stripped [screws_tilt_adjust] section",
                         "ok")

        self.log("=== Removing installed module ===", "step")
        self.run(f"rm -f {EXTRAS_PATH}")
        self.log("Removed screws_tilt_adjust.py from extras", "ok")

        self.log("=== Restart ===", "step")
        self.restart_klippy()
        self.log("Revert complete.", "ok")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Install SCREWS_TILT_CALCULATE on a Creality K2.")
    ap.add_argument("--host", required=True, help="Printer IP address")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="creality_2024")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--revert", action="store_true",
                    help="Remove screws_tilt_adjust.py + config section, "
                         "restore from backup if present.")
    ap.add_argument("--detect", action="store_true",
                    help="Report install state + board, exit.")
    ap.add_argument("--local-backup-dir", default=None,
                    help="Mirror printer.cfg + module to this directory on "
                         "the PC. Survives printer firmware updates.")
    args = ap.parse_args()

    inst = Installer(args.host, args.user, args.password,
                     dry_run=args.dry_run, verbose=args.verbose,
                     local_backup_dir=args.local_backup_dir)
    try:
        inst.connect()

        if args.detect:
            inst.detect()
            return

        if args.revert:
            inst.revert()
            return

        inst.log("=== Sanity checks ===", "step")
        inst.sanity_check()

        inst.log("=== Board detection ===", "step")
        board = inst.detect_board()
        if board == "F021":
            inst.log(f"Board: {board} (K2 / K2 Combo / K2 Pro) -- confirmed "
                     "working", "ok")
        elif board in ("F008", "F012", "F025"):
            inst.log(f"Board: {board} -- UNTESTED. Install will proceed "
                     "but behaviour is not confirmed. Report results to "
                     "https://github.com/grant0013/K2-Screws-Tilt/issues",
                     "warn")
        else:
            inst.log("Board: unknown -- proceeding anyway", "warn")

        inst.log("=== Backup ===", "step")
        inst.backup()

        inst.log("=== Install ===", "step")
        inst.copy_module()
        inst.verify_parse()
        inst.patch_printer_cfg()

        inst.log("=== Restart & verify ===", "step")
        inst.restart_klippy()
        inst.verify_loaded()

        inst.log("Done. Level your nozzle near each bed screw "
                 "(M84 -> hand-move toolhead), then run "
                 "SCREWS_TILT_CALCULATE from the gcode console. "
                 "The result tells you how many turns to adjust each "
                 "screw by.", "ok")
    finally:
        inst.close()


if __name__ == "__main__":
    main()
