#!/usr/bin/env python3
"""
Level 2 integration tests for eg_dt_camera_config_set.sh.

Uses REAL DTBOs from the versioned Linux_for_Tegra packages and REAL base DTBs
(including the Auvidea X230D DTBs from test/dts/auvidea/).  For each
(version, board, camera, port) combination the script under test is executed
with the real overlays; the resulting merged DTB is verified by verify_dt.py.

Run from inside the Docker container via run_inside_container.sh.
"""
import os
import sys
import json
import re
import shutil
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT    = "/repo"
SCRIPT       = f"{REPO_ROOT}/sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_set.sh"
VERIFY_DT    = f"{REPO_ROOT}/test/integration/verify_dt.py"
AUVIDEA_DIR  = f"{REPO_ROOT}/test/dts/auvidea"
BOOT_DIR     = "/boot"
PROC_DT      = "/tmp/fake_proc_dt"

# ---------------------------------------------------------------------------
# Camera definitions (mirrors the script's CAMERA_LANES)
# One representative per unique lane group to avoid redundant tests.
# ---------------------------------------------------------------------------
# camera name  →  lane suffix used by the script  →  DTBO filename suffix
CAMERA_LANE_SUFFIX = {
    "Dione":        "",             # no lane overlay; base cams-dione.dtbo suffices
    "MicroCube":    "ec-1-lane",
    "MicroCube640": "ec-1-lane",    # same DTBO as MicroCube
    "SmartIR640":   "ec-2-lanes",
    "Crius1280":    "ec-2-lanes",   # same DTBO as SmartIR640
    "iLumos":       "ilumos",
    "Microlynx":    "microlynx",
}
# Matching script overlay name fragment  (CAM{N}:<fragment>)
CAMERA_LANE_NAME = {
    "MicroCube":    "EC_1_lane",
    "MicroCube640": "EC_1_lane",
    "SmartIR640":   "EC_2_lanes",
    "Crius1280":    "EC_2_lanes",
    "iLumos":       "iLumos",
    "Microlynx":    "Microlynx",
}
TEST_CAMERAS = list(CAMERA_LANE_SUFFIX.keys())

# ---------------------------------------------------------------------------
# Static board / version matrix
# ---------------------------------------------------------------------------
# Each entry is a dict:
#   version         : L4T version string, e.g. "36.4.4"
#   board_short     : value returned by detect_jetson_board.sh --short
#   l4t_mode        : "35x" or "36x"  (consumed by mock config-by-hardware.py)
#   base_dtb        : DTB filename
#   base_dtb_dir    : "versioned" → <version>/Linux_for_Tegra/rootfs/boot/
#                     "auvidea"   → test/dts/auvidea/
#   dtbo_base_prefix: prefix for base/disable-imx219 DTBOs
#   dtbo_lane_prefix: prefix for per-port lane DTBOs (may differ for Forecr)
#   ports           : number of camera ports
#   is_forecr       : True for Forecr DSBOARD-ORNXS (uses different base overlay name)
#   compatible      : string written to fake /proc/device-tree/compatible

def _entry(version, board_short, l4t_mode, base_dtb,
           dtbo_base_prefix, dtbo_lane_prefix,
           ports, is_forecr, compatible, base_dtb_dir="versioned"):
    return dict(
        version=version, board_short=board_short, l4t_mode=l4t_mode,
        base_dtb=base_dtb, base_dtb_dir=base_dtb_dir,
        dtbo_base_prefix=dtbo_base_prefix, dtbo_lane_prefix=dtbo_lane_prefix,
        ports=ports, is_forecr=is_forecr, compatible=compatible,
    )

MATRIX = []

# ── 32.x  Nano porg (tegra210) ──────────────────────────────────────────────
for _ver in ("32.7.1", "32.7.4", "32.7.5", "32.7.6"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3449", "32x",
        "tegra210-p3448-0000-p3449-0000-b00.dtb",
        "tegra210-camera-eg", "tegra210-camera-eg",
        2, False, "nvidia,tegra210",
    ))

# ── 35.x  Xavier AGX (p2822 carrier, tegra194) ──────────────────────────────
# Commented out: Xavier AGX not supported (board not in production use)
# for _ver in ("35.1", "35.3.1", "35.4.1", "35.5.0", "35.6.0", "35.6.1", "35.6.2"):
#     MATRIX.append(_entry(
#         _ver, "nvidia-p2822", "35x",
#         "tegra194-p2888-0001-p2822-0000.dtb",
#         "tegra194-camera-eg", "tegra194-camera-eg",
#         2, False, "nvidia,tegra194",
#     ))

# ── 35.x  Xavier NX (p3509 carrier, tegra194) ───────────────────────────────
for _ver in ("35.1", "35.3.1", "35.4.1", "35.5.0", "35.6.0", "35.6.1", "35.6.2", "35.6.4"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3509", "35x",
        "tegra194-p3668-0001-p3509-0000.dtb",
        "tegra194-camera-eg", "tegra194-camera-eg",
        2, False, "nvidia,tegra194",
    ))

# ── 35.x  AGX Orin (p3737 carrier, tegra234) ────────────────────────────────
for _ver in ("35.3.1", "35.4.1", "35.5.0", "35.6.0", "35.6.1", "35.6.2", "35.6.4"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3737", "35x",
        "tegra234-p3701-0004-p3737-0000.dtb",
        "tegra234-p3737-camera-eg", "tegra234-p3737-camera-eg",
        4, False, "nvidia,tegra234",
    ))

# ── 35.x  Orin NX (p3768 carrier, tegra234) ─────────────────────────────────
# Before 35.6.0: base DTB lives in Linux_for_Tegra/kernel/dtb/ (SoM variant p3767-0003).
for _ver in ("35.3.1", "35.4.1", "35.5.0"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3768", "35x",
        "tegra234-p3767-0003-p3768-0000-a0.dtb",
        "tegra234-p3767-camera-p3768-eg", "tegra234-p3767-camera-p3768-eg",
        2, False, "nvidia,tegra234",
        base_dtb_dir="versioned_kernel_dtb",
    ))
# From 35.6.0: base DTB is in rootfs/boot/ (SoM variant p3767-0000).
for _ver in ("35.6.0", "35.6.1", "35.6.2", "35.6.4"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3768", "35x",
        "tegra234-p3767-0000-p3768-0000-a0.dtb",
        "tegra234-p3767-camera-p3768-eg", "tegra234-p3767-camera-p3768-eg",
        2, False, "nvidia,tegra234",
    ))

# ── 35.x  Forecr DSBOARD-ORNXS (p3768 carrier, Forecr board) ────────────────
# Base DTBO is ornxs-specific; lane DTBOs are shared with p3768.
# Before 35.6.0: same kernel/dtb/ path as p3768 above.
for _ver in ("35.3.1", "35.4.1", "35.5.0"):
    MATRIX.append(_entry(
        _ver, "dsboard-ornxs", "35x",
        "tegra234-p3767-0003-p3768-0000-a0.dtb",
        "tegra234-p3767-camera-dsboard-ornxs-eg",
        "tegra234-p3767-camera-p3768-eg",
        2, True, "nvidia,tegra234",
        base_dtb_dir="versioned_kernel_dtb",
    ))
for _ver in ("35.6.0", "35.6.1", "35.6.2", "35.6.4"):
    MATRIX.append(_entry(
        _ver, "dsboard-ornxs", "35x",
        "tegra234-p3767-0000-p3768-0000-a0.dtb",
        "tegra234-p3767-camera-dsboard-ornxs-eg",
        "tegra234-p3767-camera-p3768-eg",
        2, True, "nvidia,tegra234",
    ))

# ── 36.x  AGX Orin (p3737 carrier) ──────────────────────────────────────────
for _ver in ("36.4", "36.4.3", "36.4.4", "36.5.0"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3737", "36x",
        "tegra234-p3737-0000+p3701-0004-nv.dtb",
        "tegra234-p3737-camera-eg", "tegra234-p3737-camera-eg",
        4, False, "nvidia,tegra234",
    ))

# ── 36.x  Orin NX (p3768 carrier) ───────────────────────────────────────────
for _ver in ("36.4", "36.4.3", "36.4.4", "36.5.0"):
    MATRIX.append(_entry(
        _ver, "nvidia-p3768", "36x",
        "tegra234-p3768-0000+p3767-0000-nv.dtb",
        "tegra234-p3767-camera-p3768-eg", "tegra234-p3767-camera-p3768-eg",
        2, False, "nvidia,tegra234",
    ))

# ── 36.x  Forecr DSBOARD-ORNXS (p3768 carrier, Forecr board) ────────────────
# Base DTBO is ornxs-specific; lane DTBOs are shared with p3768.
for _ver in ("36.4", "36.4.3", "36.4.4", "36.5.0"):
    MATRIX.append(_entry(
        _ver, "dsboard-ornxs", "36x",
        "tegra234-p3768-0000+p3767-0000-nv.dtb",
        "tegra234-p3767-camera-dsboard-ornxs-eg",
        "tegra234-p3767-camera-p3768-eg",
        2, True, "nvidia,tegra234",
    ))

# ── Auvidea X230D  ───────────────────────────────────────────────────────────
# Uses the same EG overlays as nvidia-p3737 for the same L4T version,
# but a different base DTB (real Auvidea hardware DTB).
_AUVIDEA = [
    ("35.3.1", "nvidia-p3737", "35x", "auvidea_X230_35.3.1.dtb"),
    ("35.4.1", "nvidia-p3737", "35x", "auvidea_X230_35.4.1.dtb"),
    ("36.4",   "auvidea-x230d", "36x", "auvidea_X230_36.4.dtb"),
    ("36.4.3", "auvidea-x230d", "36x", "auvidea_X230_36.4.3.dtb"),
    ("36.4.4", "auvidea-x230d", "36x", "auvidea_X230_36.4.4.dtb"),
]
for _ver, _brd, _mode, _dtb in _AUVIDEA:
    MATRIX.append(_entry(
        _ver, _brd, _mode, _dtb,
        "tegra234-p3737-camera-eg", "tegra234-p3737-camera-eg",
        4, False, "nvidia,tegra234",
        base_dtb_dir="auvidea",
    ))

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def dtbo_boot_dir(entry):
    return f"{REPO_ROOT}/{entry['version']}/Linux_for_Tegra/rootfs/boot"


def base_dtb_path(entry):
    if entry["base_dtb_dir"] == "auvidea":
        return f"{AUVIDEA_DIR}/{entry['base_dtb']}"
    if entry["base_dtb_dir"] == "versioned_kernel_dtb":
        return f"{REPO_ROOT}/{entry['version']}/Linux_for_Tegra/kernel/dtb/{entry['base_dtb']}"
    return f"{dtbo_boot_dir(entry)}/{entry['base_dtb']}"


# ---------------------------------------------------------------------------
# Overlay map builder
# ---------------------------------------------------------------------------

def build_overlay_map(entry):
    """
    Scan the versioned boot dir for DTBOs that exist and return a dict mapping
    overlay names (as the script receives them) to absolute DTBO paths.
    """
    boot   = dtbo_boot_dir(entry)
    bpfx   = entry["dtbo_base_prefix"]
    lpfx   = entry["dtbo_lane_prefix"]
    ports  = entry["ports"]
    forecr = entry["is_forecr"]

    m = {}

    # Base overlay (enables Dione + sets up tegra-camera-platform)
    base_key = "Exosens Cameras for DSBOARD-ORNXS" if forecr else "Exosens Cameras"
    base_dtbo = f"{boot}/{bpfx}-cams-dione.dtbo"
    if os.path.exists(base_dtbo):
        m[base_key] = base_dtbo

    # Disable-IMX219 overlay (only exists for some versions/boards)
    disable_dtbo = f"{boot}/{bpfx}-cams-disable-imx219.dtbo"
    if os.path.exists(disable_dtbo):
        m["Exosens Cameras. Disable imx219"] = disable_dtbo

    # Per-port lane overlays
    lane_suffixes = {
        "ec-1-lane":  "EC_1_lane",
        "ec-2-lanes": "EC_2_lanes",
        "ilumos":     "iLumos",
        "microlynx":  "Microlynx",
    }
    for port in range(ports):
        for suffix, lane in lane_suffixes.items():
            dtbo = f"{boot}/{lpfx}-cam{port}-{suffix}.dtbo"
            if os.path.exists(dtbo):
                m[f"Exosens Cameras. CAM{port}:{lane}"] = dtbo

    return m


# ---------------------------------------------------------------------------
# /proc/device-tree simulation
# ---------------------------------------------------------------------------

def setup_proc_dt(entry, base_dtb):
    """
    Populate the fake /proc/device-tree from the real base DTB.

    - Writes entry['compatible'] to $PROC_DT/compatible
    - Parses the DTB for rbpcv2_imx219* and rbpcv3_imx477* nodes, creates
      a directory per node (reflecting what the real /proc/device-tree shows).
    """
    shutil.rmtree(PROC_DT, ignore_errors=True)
    os.makedirs(PROC_DT, exist_ok=True)

    # Compatible string (grep mock redirects /proc/device-tree → PROC_DT)
    with open(f"{PROC_DT}/compatible", "w") as f:
        f.write(entry["compatible"])

    # Parse base DTB for camera-conflict nodes
    r = subprocess.run(
        ["dtc", "-I", "dtb", "-O", "dts", base_dtb],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return  # can't parse — skip IMX simulation (no nodes → no conflict)

    dts = r.stdout
    for pattern in ("rbpcv2_imx219", "rbpcv3_imx477"):
        for m in re.finditer(r"(" + pattern + r"[^\s{]*)\s*\{", dts):
            node_name = m.group(1)
            node_dir = f"{PROC_DT}/{node_name}"
            os.makedirs(node_dir, exist_ok=True)
            # Replicate disabled status inside the dir (purely informational;
            # the script's `find -type d` still finds the directory itself)
            pos = m.start()
            block = dts[pos:pos + 300]
            if '"disabled"' in block[:block.find('{', 1) + 200] if '{' in block[1:] else '"disabled"' in block:
                with open(f"{node_dir}/status", "w") as f:
                    f.write("disabled")


# ---------------------------------------------------------------------------
# Running a single test case
# ---------------------------------------------------------------------------

def clean_boot():
    """Remove per-test state from /boot between test cases."""
    shutil.rmtree(f"{BOOT_DIR}/extlinux", ignore_errors=True)
    merged = f"{BOOT_DIR}/kernel_merged.dtb"
    if os.path.exists(merged):
        os.remove(merged)
    cbh_log = f"{BOOT_DIR}/cbh_calls.log"
    if os.path.exists(cbh_log):
        os.remove(cbh_log)


def write_overlays_file(overlay_map, path):
    """Write the jetson-io -l output format consumed by mock CBH."""
    with open(path, "w") as f:
        f.write("Header 2: Jetson CSI Connector\n")
        f.write("  Available hardware modules:\n")
        for i, name in enumerate(overlay_map, 1):
            f.write(f"  {i}. {name}\n")


def run_test(entry, port, camera, overlay_map, dtb_path):
    """
    Run eg_dt_camera_config_set.sh with the given environment.
    Returns (exit_code, stdout, stderr).
    """
    clean_boot()

    cbh_log      = f"{BOOT_DIR}/cbh_calls.log"
    overlays_file = f"{BOOT_DIR}/overlays.txt"
    write_overlays_file(overlay_map, overlays_file)

    env = os.environ.copy()
    env.update({
        "TEST_BOARD_SHORT":      entry["board_short"],
        "TEST_CAMERA_PORTS":     str(entry["ports"]),
        "TEST_L4T_MODE":         entry["l4t_mode"],
        "TEST_BASE_DTB":         dtb_path,
        "TEST_BOOT_DIR":         BOOT_DIR,
        "TEST_OVERLAY_DTBO_JSON": json.dumps(overlay_map),
        "TEST_CBH_LOG":          cbh_log,
        "TEST_OVERLAYS_FILE":    overlays_file,
        "TEST_PROC_DT":          PROC_DT,
    })

    r = subprocess.run(
        ["bash", SCRIPT, f"{port}/{camera}"],
        env=env, capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


def get_merged_dtb_36x():
    """
    For 36.x: read /boot/extlinux/extlinux.conf and apply fdtoverlay manually
    to produce a merged DTB for verification.  Returns the path to the temp file,
    or None on failure.  Caller is responsible for deleting the file.
    """
    extlinux = f"{BOOT_DIR}/extlinux/extlinux.conf"
    if not os.path.exists(extlinux):
        return None

    content = open(extlinux).read()
    fdt_m = re.search(r"^\s*FDT\s+(\S+)", content, re.MULTILINE)
    ovl_m = re.search(r"^\s*OVERLAYS\s+(\S+)", content, re.MULTILINE)

    if not fdt_m:
        return None

    fdt   = fdt_m.group(1)
    dtbos = ovl_m.group(1).split(",") if ovl_m else []

    # Apply overlays sequentially so phandle symbols from one overlay
    # (e.g. cams-dione) are visible to the next (e.g. cam0-ilumos).
    current = fdt
    tmp_files = []
    for i, dtbo in enumerate(dtbos):
        out = tempfile.mktemp(suffix=f".{i}.dtb", dir="/tmp")
        r = subprocess.run(["fdtoverlay", "-i", current, "-o", out, dtbo],
                           capture_output=True, text=True)
        if r.returncode != 0:
            for f in tmp_files:
                try: os.remove(f)
                except OSError: pass
            return None, r.stderr
        if current != fdt:
            try: os.remove(current)
            except OSError: pass
        tmp_files.append(out)
        current = out

    return current, ""


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
NC     = "\033[0m"


def _pass(msg):  print(f"  {GREEN}PASS{NC}  {msg}")
def _fail(msg):  print(f"  {RED}FAIL{NC}  {msg}")
def _skip(msg):  print(f"  {YELLOW}SKIP{NC}  {msg}")
def _warn(msg):  print(f"  {YELLOW}WARN{NC}  {msg}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pass_count = 0
    fail_count = 0
    skip_count = 0
    failures   = []

    for entry in MATRIX:
        version = entry["version"]
        board   = entry["board_short"]
        dtb     = base_dtb_path(entry)
        boot    = dtbo_boot_dir(entry)

        # ── Prerequisite: base DTB must exist ──────────────────────────────
        if not os.path.exists(dtb):
            _warn(f"L4T {version} | {board}: base DTB not found — SKIP")
            skip_count += 1
            continue

        # ── Build overlay map from actual DTBO files ────────────────────────
        overlay_map = build_overlay_map(entry)
        base_key = (
            "Exosens Cameras for DSBOARD-ORNXS"
            if entry["is_forecr"]
            else "Exosens Cameras"
        )
        if base_key not in overlay_map:
            _warn(f"L4T {version} | {board}: no base DTBO ({base_key}) — SKIP")
            skip_count += 1
            continue

        print(f"\n{BOLD}{CYAN}=== L4T {version} | {board} ==={NC}")

        # ── Set up /proc/device-tree simulation (once per board/version) ────
        setup_proc_dt(entry, dtb)

        # ── Iterate cameras × ports ─────────────────────────────────────────
        for port in range(entry["ports"]):
            for camera in TEST_CAMERAS:
                label = f"L4T {version} | {board} | {camera} port {port}"

                # Does a DTBO exist for this camera/port combination?
                lane_suffix = CAMERA_LANE_SUFFIX[camera]
                if lane_suffix:
                    lane_name = CAMERA_LANE_NAME[camera]
                    dtbo_key  = f"Exosens Cameras. CAM{port}:{lane_name}"
                    if dtbo_key not in overlay_map:
                        _skip(f"{camera} port {port}: no DTBO")
                        skip_count += 1
                        continue

                expected_exit = 0

                # ── Run the script ──────────────────────────────────────────
                exit_code, stdout, stderr = run_test(
                    entry, port, camera, overlay_map, dtb
                )

                if exit_code != expected_exit:
                    combined = stdout + stderr
                    msg = (
                        f"{camera} port {port}: exit={exit_code} "
                        f"(expected {expected_exit})"
                    )
                    _fail(msg)
                    # Print first 3 lines of output to aid diagnosis
                    for line in combined.splitlines()[:3]:
                        print(f"         {line}")
                    fail_count += 1
                    failures.append(label)
                    continue

                # ── Obtain merged DTB for verification ──────────────────────
                merged = None
                tmp_to_delete = None

                if entry["l4t_mode"] in ("35x", "32x"):
                    merged = f"{BOOT_DIR}/kernel_merged.dtb"
                    if not os.path.exists(merged):
                        _fail(f"{camera} port {port}: kernel_merged.dtb missing")
                        fail_count += 1
                        failures.append(label + " (no merged DTB)")
                        continue
                else:
                    merged, merge_err = get_merged_dtb_36x()
                    tmp_to_delete = merged
                    if not merged:
                        _fail(
                            f"{camera} port {port}: "
                            "could not rebuild merged DTB from extlinux.conf"
                        )
                        fail_count += 1
                        failures.append(label + " (no merged DTB)")
                        continue

                # ── Verify DT structure ─────────────────────────────────────
                vr = subprocess.run(
                    [
                        "python3", VERIFY_DT,
                        merged, camera, str(port), entry["l4t_mode"],
                    ],
                    capture_output=True, text=True,
                )

                if tmp_to_delete and os.path.exists(tmp_to_delete):
                    os.remove(tmp_to_delete)

                detail = vr.stdout.strip()
                if vr.returncode == 0:
                    _pass(f"{camera} port {port}: {detail}")
                    pass_count += 1
                else:
                    _fail(f"{camera} port {port}: {detail}")
                    fail_count += 1
                    failures.append(label)

    # ── Summary ─────────────────────────────────────────────────────────────
    print()
    print(
        f"{BOLD}Results: "
        f"{GREEN}{pass_count} passed{NC}  "
        f"{RED}{fail_count} failed{NC}  "
        f"{YELLOW}{skip_count} skipped{NC}"
    )

    if failures:
        print()
        print(f"{BOLD}Failed tests:{NC}")
        for f in failures:
            print(f"  - {f}")

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
