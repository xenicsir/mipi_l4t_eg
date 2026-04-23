#!/usr/bin/env python3
"""
Mock for /opt/eg/jetson-io/config-by-hardware.py

Environment variables (set by the test runner):
  TEST_CBH_LOG          Path to call log file (records selected overlays)
  TEST_L4T_MODE         "35x" or "36x"
  TEST_BASE_DTB         Path to compiled base DTB for merging
  TEST_BOOT_DIR         Path acting as /boot
  TEST_OVERLAYS_FILE    Path to file listing available overlays (-l output)
  TEST_OVERLAY_DTBO_JSON  JSON: {"overlay name": "/path/to.dtbo", ...}
"""
import sys, os, json, subprocess

LOG_FILE      = os.environ.get("TEST_CBH_LOG",           "/tmp/cbh_calls.log")
L4T_MODE      = os.environ.get("TEST_L4T_MODE",          "36x")
BASE_DTB      = os.environ.get("TEST_BASE_DTB",          "/boot/dtbs/base.dtb")
BOOT_DIR      = os.environ.get("TEST_BOOT_DIR",          "/boot")
OVERLAYS_FILE = os.environ.get("TEST_OVERLAYS_FILE",     "")
OVERLAY_DTBO  = json.loads(os.environ.get("TEST_OVERLAY_DTBO_JSON", "{}"))


def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


args = sys.argv[1:]

# -l : list available overlays
if "-l" in args:
    if OVERLAYS_FILE and os.path.isfile(OVERLAYS_FILE):
        sys.stdout.write(open(OVERLAYS_FILE).read())
    sys.exit(0)

# -n : apply overlays
if "-n" in args:
    selected = [a[2:] for a in args if a.startswith("2=")]
    log("OVERLAYS: " + "|".join(selected))

    # Resolve overlay names to DTBO file paths
    dtbos = [OVERLAY_DTBO[name] for name in selected if name in OVERLAY_DTBO]

    if L4T_MODE in ("35x", "32x"):
        # Merge base DTB + overlays into a single merged DTB (35.x behaviour).
        # Apply overlays sequentially so that phandle symbols introduced by one
        # overlay (e.g. cams-dione) are available to the next (e.g. cam0-ilumos).
        merged = os.path.join(BOOT_DIR, "kernel_merged.dtb")
        current = BASE_DTB
        tmp_files = []
        for i, dtbo in enumerate(dtbos):
            out = merged if i == len(dtbos) - 1 else f"{merged}.tmp{i}"
            r = subprocess.run(["fdtoverlay", "-i", current, "-o", out, dtbo],
                               capture_output=True)
            if r.returncode != 0:
                for f in tmp_files:
                    try: os.remove(f)
                    except OSError: pass
                sys.stderr.write(r.stderr.decode())
                sys.exit(r.returncode)
            if current != BASE_DTB:
                try: os.remove(current)
                except OSError: pass
            tmp_files.append(out)
            current = out
        # In 32.x/35.x, jetson-io also appends a LABEL JetsonIO to extlinux.conf
        # pointing at the merged (user-custom) DTB. Mirror that so postinst-level
        # tests can assert the label is present.
        import re as _re
        extlinux_dir = os.path.join(BOOT_DIR, "extlinux")
        os.makedirs(extlinux_dir, exist_ok=True)
        extlinux = os.path.join(extlinux_dir, "extlinux.conf")
        existing = open(extlinux).read() if os.path.isfile(extlinux) else ""
        # Strip any previous JetsonIO block (from this or prior runs)
        stripped = _re.sub(r"(?ms)^LABEL JetsonIO\b.*?(?=^LABEL |\Z)", "", existing)
        if not stripped.strip():
            stripped = "TIMEOUT 30\nDEFAULT primary\n\n"
        jio = (
            "\nLABEL JetsonIO\n"
            "    MENU LABEL Custom Config (EG Cameras)\n"
            "    LINUX /boot/Image\n"
            f"    FDT {merged}\n"
            "    APPEND ${cbootargs} quiet root=/dev/mmcblk0p1 rw rootwait\n"
        )
        with open(extlinux, "w") as f:
            f.write(stripped.rstrip() + "\n" + jio)
        print(f"Configuration saved to {merged}.")
    else:
        # Write extlinux.conf (36.x behaviour)
        extlinux_dir = os.path.join(BOOT_DIR, "extlinux")
        os.makedirs(extlinux_dir, exist_ok=True)
        extlinux = os.path.join(extlinux_dir, "extlinux.conf")
        with open(extlinux, "w") as f:
            f.write("TIMEOUT 30\nDEFAULT JetsonIO\n\n")
            f.write("LABEL JetsonIO\n")
            f.write(f"    FDT {BASE_DTB}\n")
            if dtbos:
                f.write(f"    OVERLAYS {','.join(dtbos)}\n")
        print("Modified /boot/extlinux/extlinux.conf to add following DTBO entries:")
        for d in dtbos:
            print(d)

    sys.exit(0)

sys.exit(0)
