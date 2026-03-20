#!/usr/bin/env python3
"""
verify_dtsi_structure.py — Vérification statique des 6 DTSIs EG caméras.

Vérifie pour chaque DTSI :
  1. Équilibre des accolades
  2. Présence et nombre de modes pour chaque sensor node
  3. Chaque sensor node est bien imbriqué dans son canal i2c@X

Usage :
  python3 tools/verify_dtsi_structure.py          # depuis la racine du repo
  python3 tools/verify_dtsi_structure.py --quiet  # affiche seulement les erreurs
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

H32 = REPO_ROOT / "sources/common/source/hardware_32+"
H36 = REPO_ROOT / "sources/common/source/hardware_36+"

DTSI_FILES = {
    "porg":     H32 / "nvidia/platform/t210/porg/kernel-dts/tegra210-camera-common-eg-cams-dione.dtsi",
    "jakku":    H32 / "nvidia/platform/t19x/jakku/kernel-dts/tegra194-camera-common-eg-cams-dione.dtsi",
    "concord":  H32 / "nvidia/platform/t23x/concord/kernel-dts/tegra234-p3737-camera-common-eg-cams-dione.dtsi",
    "p3768":    H32 / "nvidia/platform/t23x/p3768/kernel-dts/tegra234-p3767-camera-common-eg-cams-dione.dtsi",
    "p3737-36": H36 / "nvidia/t23x/nv-public/overlay/tegra234-p3737-camera-common-eg-cams-dione.dtsi",
    "p3767-36": H36 / "nvidia/t23x/nv-public/overlay/tegra234-p3767-camera-common-eg-cams-dione.dtsi",
}

# (sensor_name, expected_modes) par cam_index (0=premier i2c, 1=deuxième, etc.)
# Règles :
#   porg (T210) : pas de RAW16 → ilumos 3 modes, microlynx 1 mode, eg_ec 4 modes
#   jakku/T234  : ilumos 6 modes, microlynx 3 modes (RAW16_BE+RAW16+RAW14), eg_ec 6 modes
EXPECTED = {
    "porg":     {0: [("dione_ir_cam0", 4), ("eg_ec_cam0", 4), ("ilumos_cam0", 3), ("microlynx_cam0", 1)],
                 1: [("dione_ir_cam1", 4), ("eg_ec_cam1", 4), ("ilumos_cam1", 3), ("microlynx_cam1", 1)]},
    "jakku":    {0: [("dione_ir_cam0", 4), ("eg_ec_cam0", 6), ("ilumos_cam0", 6), ("microlynx_cam0", 3)],
                 1: [("dione_ir_cam1", 4), ("eg_ec_cam1", 6), ("ilumos_cam1", 6), ("microlynx_cam1", 3)]},
    "concord":  {0: [("dione_ir_cam0", 4), ("eg_ec_cam0", 6), ("ilumos_cam0", 6), ("microlynx_cam0", 3)],
                 1: [("dione_ir_cam1", 4), ("eg_ec_cam1", 6), ("ilumos_cam1", 6), ("microlynx_cam1", 3)],
                 2: [("dione_ir_cam2", 4), ("eg_ec_cam2", 6), ("ilumos_cam2", 6), ("microlynx_cam2", 3)],
                 3: [("dione_ir_cam3", 4), ("eg_ec_cam3", 6), ("ilumos_cam3", 6), ("microlynx_cam3", 3)]},
    "p3768":    {0: [("dione_ir_cam0", 4), ("eg_ec_cam0", 6), ("ilumos_cam0", 6), ("microlynx_cam0", 3)],
                 1: [("dione_ir_cam1", 4), ("eg_ec_cam1", 6), ("ilumos_cam1", 6), ("microlynx_cam1", 3)]},
    "p3737-36": {0: [("dione_ir_cam0", 4), ("eg_ec_cam0", 6), ("ilumos_cam0", 6), ("microlynx_cam0", 3)],
                 1: [("dione_ir_cam1", 4), ("eg_ec_cam1", 6), ("ilumos_cam1", 6), ("microlynx_cam1", 3)],
                 2: [("dione_ir_cam2", 4), ("eg_ec_cam2", 6), ("ilumos_cam2", 6), ("microlynx_cam2", 3)],
                 3: [("dione_ir_cam3", 4), ("eg_ec_cam3", 6), ("ilumos_cam3", 6), ("microlynx_cam3", 3)]},
    "p3767-36": {0: [("dione_ir_cam0", 4), ("eg_ec_cam0", 6), ("ilumos_cam0", 6), ("microlynx_cam0", 3)],
                 1: [("dione_ir_cam1", 4), ("eg_ec_cam1", 6), ("ilumos_cam1", 6), ("microlynx_cam1", 3)]},
}

SENSOR_RE = re.compile(r"((?:dione_ir|eg_ec|ilumos|microlynx)_cam\d):")
I2C_RE    = re.compile(r"(i2c@\w+)\s*\{")


def find_block_end(lines, start):
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > start:
            return i
    return len(lines) - 1


def parse_dtsi(filepath):
    """Return dict of sensor nodes: name → {tabs, line, i2c_idx, modes}."""
    lines = filepath.read_text().splitlines(keepends=True)
    depth = 0
    i2c_order = []
    i2c_stack = []  # (label, open_depth)
    nodes = {}

    for i, line in enumerate(lines):
        s = line.rstrip()
        opens = s.count("{")
        closes = s.count("}")

        m_i2c = I2C_RE.search(s)
        if m_i2c:
            label = m_i2c.group(1)
            i2c_stack.append((label, depth + opens))
            if label not in i2c_order:
                i2c_order.append(label)

        current_i2c = i2c_stack[-1][0] if i2c_stack else None

        m_sensor = SENSOR_RE.search(s)
        if m_sensor:
            name = m_sensor.group(1)
            tabs = len(line) - len(line.lstrip("\t"))
            end = find_block_end(lines, i)
            block = lines[i : end + 1]
            mode_count = sum(1 for bl in block if re.search(r"\bmode\d+\s*\{", bl))
            i2c_idx = i2c_order.index(current_i2c) if current_i2c in i2c_order else -1
            nodes[name] = {
                "tabs": tabs,
                "line": i + 1,
                "inside_i2c": current_i2c or "NONE",
                "i2c_idx": i2c_idx,
                "modes": mode_count,
            }

        depth += opens - closes
        if i2c_stack and depth < i2c_stack[-1][1]:
            i2c_stack.pop()

    return lines, nodes


def verify(quiet=False):
    errors = []
    total_ok = 0

    for platform, filepath in DTSI_FILES.items():
        if not filepath.exists():
            errors.append(f"[{platform}] FILE NOT FOUND: {filepath}")
            continue

        lines, nodes = parse_dtsi(filepath)

        # 1. Brace balance
        bal = sum(l.count("{") - l.count("}") for l in lines)
        if bal != 0:
            errors.append(f"[{platform}] Brace imbalance: {bal:+d}")

        plat_ok = 0
        for cam_id, sensor_list in EXPECTED.get(platform, {}).items():
            for name, expected_modes in sensor_list:
                if name not in nodes:
                    errors.append(f"[{platform}] MISSING node: {name}")
                    continue
                info = nodes[name]

                # 2. Mode count
                if info["modes"] != expected_modes:
                    errors.append(
                        f"[{platform}] {name}: {info['modes']} modes "
                        f"(expected {expected_modes}) line {info['line']}"
                    )

                # 3. i2c placement
                if info["inside_i2c"] == "NONE":
                    errors.append(
                        f"[{platform}] {name}: NOT inside any i2c channel "
                        f"(line {info['line']})"
                    )
                elif info["i2c_idx"] != cam_id:
                    errors.append(
                        f"[{platform}] {name}: inside i2c channel #{info['i2c_idx']} "
                        f"({info['inside_i2c']}), expected channel #{cam_id} "
                        f"(line {info['line']})"
                    )
                else:
                    plat_ok += 1

        total_ok += plat_ok
        if not quiet:
            status = "OK" if not [e for e in errors if f"[{platform}]" in e] else "FAIL"
            print(f"  [{status}] {platform}: {plat_ok} nodes correct")

    return errors, total_ok


def main():
    quiet = "--quiet" in sys.argv
    if not quiet:
        print("=== DTSI structure verification ===")

    errors, total_ok = verify(quiet=quiet)

    if not quiet:
        print(f"\n{total_ok} nodes OK, {len(errors)} errors")

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    if not quiet:
        print("All checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
