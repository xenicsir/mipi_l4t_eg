#!/usr/bin/env python3
"""
Phase 1a — Base overlay coherence matrix.

For every (version, platform_id) in the test matrix, apply ONLY the base DTBO
("Exosens Cameras", "Exosens Cameras (global)", or "Exosens Cameras - 2 ports")
to the ORIGINAL NVIDIA / Auvidea base DTB — no per-port camera overlay.

The merged DTB is then validated by dt_lib.checks in BASE_ONLY mode.  Purpose:
prove that each base overlay yields a self-coherent DT before piling on
per-port permutations in the main matrix.

The flow mirrors production: eg_dt_camera_config_set.sh is invoked with
camera=Dione on every port (Dione has no lane-specific per-port DTBO, so only
the base + Disable-IMX overlays get applied).

Run inside Docker via test/integration/run_inside_container.sh.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

# Reuse matrix.py's path constants and helpers to avoid duplication
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from matrix import (
    REPO_ROOT, SCRIPT, BOOT_DIR, PROC_DT,
    build_overlay_map, populate_boot, populate_boot_dtbos, setup_proc_dt,
    write_overlays_file,
    _get_merged_dtb, _base_from_cbh,
    RED, GREEN, YELLOW, CYAN, BOLD, NC,
)
sys.path.insert(0, f"{REPO_ROOT}/test/config")
from test_matrix import generate_matrix, Entry  # noqa: E402

from dt_lib import DeviceTree
from dt_lib.checks import CheckMode, run_checks, summarize


# ---------------------------------------------------------------------------
# Base-only run: camera=Dione on all ports → no per-port DTBOs triggered
# ---------------------------------------------------------------------------

def run_script_base_only(entry: Entry, overlay_map: dict[str, str]) -> tuple[int, str, str]:
    """Invoke eg_dt_camera_config_set.sh with NO args. The script then expands
    to Dione on every port it auto-detects (handles 2-port vs 4-port boards
    automatically via extlinux LABEL primary / kernel DTB inspection).
    Dione has no lane suffix → only the base DTBO + Disable-IMX get applied,
    no per-port lane DTBO."""
    cbh_log = f"{BOOT_DIR}/cbh_calls.log"
    overlays_file = f"{BOOT_DIR}/overlays.txt"
    write_overlays_file(overlay_map, overlays_file)

    env = os.environ.copy()
    env.update({
        "TEST_BOARD_SHORT":      entry.board_short,
        "TEST_CAMERA_PORTS":     str(entry.ports),
        "TEST_L4T_MODE":         entry.l4t_mode,
        "TEST_BASE_DTB":         entry.base_dtb,
        "TEST_BOOT_DIR":         BOOT_DIR,
        "TEST_OVERLAY_DTBO_JSON": json.dumps(overlay_map),
        "TEST_CBH_LOG":          cbh_log,
        "TEST_OVERLAYS_FILE":    overlays_file,
        "TEST_PROC_DT":          PROC_DT,
    })
    r = subprocess.run(["bash", SCRIPT],  # no args → default all-ports
                       env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------------------
# Per-entry execution
# ---------------------------------------------------------------------------

@dataclass
class Result:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list = None


def _run_entry(entry: Entry, result: Result) -> None:
    label = f"{entry.version}/{entry.platform_id}/base-only"

    # Prereqs
    if not os.path.exists(entry.base_dtb):
        print(f"  {RED}FAIL {NC} {label}: base DTB missing: {entry.base_dtb}")
        result.failed += 1
        result.failures.append(label)
        return

    overlay_map = build_overlay_map(entry)
    if entry.is_forecr:
        base_key = "Exosens Cameras for DSBOARD-ORNXS"
    elif entry.cam0_lane_swap:
        base_key = "Exosens Cameras - CAM0 lane swap"
    else:
        base_key = "Exosens Cameras"
    if base_key not in overlay_map:
        print(f"  {RED}FAIL {NC} {label}: base DTBO {base_key!r} missing")
        result.failed += 1
        result.failures.append(label)
        return

    populate_boot_dtbos(entry)
    # Use 'fresh' extlinux state (LABEL primary present — needed for 2-port detection)
    populate_boot(entry, "fresh")
    setup_proc_dt(entry, entry.base_dtb, "fresh")

    rc, out, err = run_script_base_only(entry, overlay_map)
    if rc != 0:
        snippet = (err or out).strip().splitlines()[-3:]
        print(f"  {RED}FAIL {NC} {label}: script rc={rc}: {snippet}")
        result.failed += 1
        result.failures.append(label)
        return

    # Find the merged DTB produced by the script
    merged_dtb, merged_err = _get_merged_dtb(entry)
    if merged_dtb is None:
        print(f"  {RED}FAIL {NC} {label}: cannot locate merged DTB: {merged_err}")
        result.failed += 1
        result.failures.append(label)
        return

    # Validate via dt_lib checks in BASE_ONLY mode
    try:
        dt = DeviceTree.from_dtb(merged_dtb)
    except Exception as e:
        print(f"  {RED}FAIL {NC} {label}: DTB not parseable: {e}")
        result.failed += 1
        result.failures.append(label)
        return

    total_ports = entry.ports
    # If the script switched to 2-port mode, MAX_PORT is enforced by extlinux;
    # we see the same kernel_merged.dtb regardless and must match total_ports.
    cbh_log = f"{BOOT_DIR}/cbh_calls.log"
    cbh_line = open(cbh_log).read().strip() if os.path.exists(cbh_log) else ""
    if "Exosens Cameras - 2 ports" in cbh_line:
        total_ports = 2

    results = run_checks(dt, CheckMode.BASE_ONLY, total_ports=total_ports)
    ok, sk, fl = summarize(results)

    if merged_dtb != f"{BOOT_DIR}/kernel_merged.dtb":
        try: os.remove(merged_dtb)
        except OSError: pass

    base_tag = _base_from_cbh(cbh_line) or "?"
    if fl == 0:
        print(f"  {GREEN}PASS {NC} {label}: {ok} ok, {sk} skip — base={base_tag}")
        result.passed += 1
    else:
        print(f"  {RED}FAIL {NC} {label}: {ok} ok, {sk} skip, {fl} FAIL — base={base_tag}")
        for r in results:
            if r.status == "FAIL":
                print(f"    ✗ {r}")
        result.failed += 1
        result.failures.append(label)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    result = Result(failures=[])
    entries = list(generate_matrix())
    if not entries:
        print("ERROR: empty test matrix")
        return 2

    for entry in entries:
        header = (f"{BOLD}{CYAN}━━━ L4T {entry.version} / {entry.platform_id} "
                  f"/ {entry.board_short} / {entry.l4t_mode} (base-only) ━━━{NC}")
        print(f"\n{header}")
        _run_entry(entry, result)

    print()
    print(f"{BOLD}Base-overlay results:{NC}  "
          f"{GREEN}{result.passed} pass{NC}  "
          f"{RED}{result.failed} fail{NC}  "
          f"{YELLOW}{result.skipped} skip{NC}")

    if result.failures:
        print(f"\n{BOLD}Failed:{NC}")
        for f in result.failures[:40]:
            print(f"  - {f}")
        if len(result.failures) > 40:
            print(f"  ... and {len(result.failures) - 40} more")

    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
