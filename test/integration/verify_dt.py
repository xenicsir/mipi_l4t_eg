#!/usr/bin/env python3
"""
Verify a merged device tree DTB after applying camera overlays.

Usage:
  verify_dt.py <dtb_path> <camera> <port> [l4t_mode] [--ports N] [--base-only]

Arguments:
  dtb_path     path to the merged DTB (or a .dts — auto-detected)
  camera       camera name (Dione, iLumos, MicroCube, ...) — ignored in --base-only
  port         0-based port index where the camera is connected — ignored in --base-only
  l4t_mode     "35x" | "36x" | "32x" (default: "36x")
  --ports N    total ports the platform exposes (default: 4)
  --base-only  do not run per-port checks (no sensor active, no bus-width on endpoint)

Exits 0 with "PASS: ..." if every check passes.
Exits 1 with "FAIL: ..." listing the failed labels.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# dt_lib is a sibling package — ensure it's importable when launched standalone
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from dt_lib import DeviceTree
from dt_lib.checks import CheckMode, run_checks, summarize


def _parse_args(argv: list[str]) -> dict:
    if len(argv) < 3:
        print("Usage: verify_dt.py <dtb_path> <camera> <port> [l4t_mode] [--ports N] [--base-only]",
              file=sys.stderr)
        sys.exit(2)

    args = {
        "dtb_path": argv[0],
        "camera":   argv[1],
        "port":     int(argv[2]),
        "l4t_mode": "36x",
        "ports":    4,
        "base_only": False,
    }
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--ports" and i + 1 < len(argv):
            args["ports"] = int(argv[i + 1]); i += 2
        elif a == "--base-only":
            args["base_only"] = True; i += 1
        else:
            args["l4t_mode"] = a; i += 1
    return args


def _load_dt(path: str) -> DeviceTree:
    """Load a DT from DTB or DTS (auto-detect via magic bytes)."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head == b"\xd0\x0d\xfe\xed":       # FDT magic
        return DeviceTree.from_dtb(path)
    # Assume DTS; compile with dtc
    return DeviceTree.from_dts(path)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        dt = _load_dt(args["dtb_path"])
    except Exception as e:
        print(f"FAIL: DTB not parseable: {e}")
        return 1

    mode = CheckMode.BASE_ONLY if args["base_only"] else CheckMode.PER_PORT
    results = run_checks(
        dt, mode,
        camera=args["camera"],
        port=args["port"],
        l4t_mode=args["l4t_mode"],
        total_ports=args["ports"],
    )
    ok, sk, fl = summarize(results)

    failures = [r for r in results if r.status == "FAIL"]
    # One-line summary for quick scanning (matrix.py greps stderr for details)
    summary = f"{ok} ok, {sk} skip, {fl} FAIL"
    if failures:
        print(f"FAIL: {summary}")
        for r in failures:
            print(f"  ✗ {r}")
        return 1

    print(f"PASS: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
