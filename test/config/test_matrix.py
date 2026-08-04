#!/usr/bin/env python3
"""
Generate the full test matrix from eg_config.yaml + test/config/hardware.yaml.

Single source of truth for all 3 phases of the test suite:
  - Phase 1 (script tests): test/integration/matrix.py
  - Phase 2 (dpkg-deb postinst): test/packaging/test_postinst.py
  - Phase 3 (qemu-aarch64 dpkg -i): test/qemu_install/test_dpkg.py

For each (version, platform_id) supported by eg_config.yaml, produces an Entry with:
  - version, jetpack, platform_id, board_short, som, compat
  - l4t_mode ("32x" | "35x" | "36x")
  - base_dtb (absolute path)
  - dtbo_boot_dir (where built DTBOs live for this version)
  - package_path (absolute path to the .deb, if it exists)
  - dtbo_base_prefix / dtbo_lane_prefix / ports / is_forecr

Run this module directly to print the matrix in a human-readable form.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Iterator

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required: pip install pyyaml\n")
    sys.exit(2)


# ---------------------------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EG_CONFIG = os.path.join(REPO_ROOT, "eg_config.yaml")
HW_CONFIG = os.path.join(REPO_ROOT, "test", "config", "hardware.yaml")


@dataclass
class Entry:
    version: str                # L4T version, e.g. "35.6.1"
    jetpack: str                # JetPack version, e.g. "5.1.5"
    platform_id: str            # e.g. "agx_orin_x230d"
    l4t_mode: str               # "32x" | "35x" | "36x"
    board_short: str            # value returned by detect_jetson_board.sh --short
    som: str | None             # t210, t186, or None (Linux_for_Tegra plain)
    compat: str                 # /proc/device-tree/compatible
    base_dtb: str               # absolute path to base DTB
    base_dtb_dir: str           # "versioned" | "versioned_kernel_dtb" | "auvidea"
    dtbo_boot_dir: str          # absolute path to rootfs/boot/ (where DTBOs live)
    dtbo_base_prefix: str
    dtbo_lane_prefix: str
    ports: int
    is_forecr: bool
    cam0_lane_swap: bool        # True when carrier corrects the p3768 SoM lane swap on CAM0
    vendor: str                 # "generic" | "forecr"
    package_path: str | None    # absolute path to built .deb, or None if missing


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _lft_dir(hw: dict) -> str:
    """Linux_for_Tegra_* directory name for this platform (t210/t186 variants)."""
    som = hw.get("som")
    return f"Linux_for_Tegra_{som}" if som else "Linux_for_Tegra"


def _pick_base_dtb(hw: dict, version: str, l4t_mode: str) -> tuple[str, str]:
    """Return (dtb_filename, base_dtb_dir) for this (platform, version)."""
    base_dtb = hw["base_dtb"]
    # 1. Exact version key wins.
    if version in base_dtb:
        val = base_dtb[version]
        if isinstance(val, dict):
            return val["name"], val.get("dir", hw.get("base_dtb_dir", "versioned"))
        return val, hw.get("base_dtb_dir", "versioned")
    # 2. Mode key (35.x / 36.x).
    if l4t_mode in base_dtb:
        val = base_dtb[l4t_mode]
        if isinstance(val, dict):
            return val["name"], val.get("dir", hw.get("base_dtb_dir", "versioned"))
        return val, hw.get("base_dtb_dir", "versioned")
    # 3. Default.
    if "default" in base_dtb:
        return base_dtb["default"], hw.get("base_dtb_dir", "versioned")
    raise KeyError(f"No base_dtb mapping for {version} / {l4t_mode}")


def _board_short(hw: dict, l4t_mode: str) -> str:
    if "board_short" in hw:
        return hw["board_short"]
    return hw["board_short_by_mode"][l4t_mode]


def _find_package(version: str, platform_id: str, vendor: str) -> str | None:
    """Find the .deb produced for this (version, vendor, platform).

    Naming patterns (observed):
      - generic generic:      jetson-l4t-<ver>-jp<jp>-eg-cams_*_arm64.deb
      - generic t210:         jetson-l4t-<ver>-jp<jp>-t210-eg-cams_*_arm64.deb
      - generic t186:         jetson-l4t-<ver>-jp<jp>-t186-eg-cams_*_arm64.deb
      - forecr:               jetson-l4t-<ver>-jp<jp>-forecr-dsboard-ornxs-eg-cams_*_arm64.deb
      - cti / cti_pristine:   jetson-l4t-<ver>-jp<jp>-cti[-pristine]-<carrier>-eg-cams_*_arm64.deb

    The vendor is DEDUCED from the filename and must equal the caller's, rather
    than being matched by a per-vendor glob. Until 2026-08-04 cti and cti_pristine
    had no branch at all and fell through to the generic one, whose exclusion list
    only knew about forecr/t210/t186 — so on 36.5.0 nine of the ten matrix entries
    resolved to the SAME cti-pristine .deb regardless of vendor, and every generic
    and cti entry was being validated against a package that was not theirs. P0
    reported "Coherence OK" throughout, because it only checks that a file exists.

    When several builds of the same vendor are left in a version directory, the
    NEWEST BY mtime wins.
    Sorting by filename would not: the version is `0~develop+g<short-sha>`, and a
    SHA orders arbitrarily with respect to build chronology (`gfb6e6ee` sorts
    above a later `g1abcdef`). A lexicographic pick therefore silently hands the
    whole test suite a stale .deb whose control fields predate what is under
    test — how a real build with the correct fields got mistaken for a
    regression on 2026-08-04. Same root cause as the open issue on the
    non-monotonic `+g<sha>` Debian versioning.
    """
    import glob

    version_dir = os.path.join(REPO_ROOT, version)
    if not os.path.isdir(version_dir):
        return None

    som_frag = {"nano_t210": "t210", "tx2_t186": "t186"}.get(platform_id)
    frags = _vendor_frags()

    candidates = []
    for p in glob.glob(os.path.join(version_dir, "jetson-l4t-*-eg-cams_*.deb")):
        b = os.path.basename(p)
        if som_frag:
            if f"-{som_frag}-" not in b:
                continue
        elif "-t210-" in b or "-t186-" in b:
            continue
        if _vendor_of_package(b, frags) != vendor:
            continue
        candidates.append(p)
    return max(candidates, key=os.path.getmtime) if candidates else None


def _vendor_frags() -> list[str]:
    """Vendor fragments as they appear in package filenames, LONGEST FIRST.

    Read from eg_config.yaml so adding a vendor needs no change here. Longest
    first is not cosmetic: "-cti-" is a prefix of "-cti-pristine-", so a plain
    substring test attributes the cti_pristine package to vendor cti.
    """
    eg = _load_yaml(EG_CONFIG)
    return sorted((v.replace("_", "-") for v in (eg.get("vendors") or {}) if v != "generic"),
                  key=len, reverse=True)


def _vendor_of_package(basename: str, frags: list[str]) -> str:
    """Which vendor a .deb filename belongs to; "generic" when no fragment matches."""
    for f in frags:
        if f"-{f}-" in basename:
            return f.replace("-", "_")
    return "generic"


def generate_matrix() -> Iterator[Entry]:
    """Yield one Entry per (version, platform_id[, vendor])."""
    eg = _load_yaml(EG_CONFIG)
    hw_cfg = _load_yaml(HW_CONFIG)

    mode_fallback = hw_cfg["mode_fallback"]
    platforms = hw_cfg["platforms"]

    for version, vcfg in eg["versions"].items():
        default_mode = mode_fallback.get(version)
        if not default_mode:
            sys.stderr.write(f"WARN: unknown mode for version {version}, skipping\n")
            continue
        jetpack = vcfg.get("jetpack", "?")
        vendors = vcfg.get("vendors", ["generic"])
        platform_ids = vcfg.get("platform_ids", [])

        for pid in platform_ids:
            if pid not in platforms:
                sys.stderr.write(f"WARN: platform_id '{pid}' in eg_config "
                                 f"(version {version}) has no hardware.yaml entry\n")
                continue

            hw = platforms[pid]

            # Version-level skip (e.g. xavier_nx skipped for 32.7.x)
            if version in hw.get("skip_versions", []):
                continue

            l4t_mode = hw.get("l4t_mode", default_mode)
            board_short = _board_short(hw, l4t_mode)
            som = hw.get("som")
            compat = hw["compat"]
            dtbo_base_prefix = hw["dtbo_base_prefix"]
            dtbo_lane_prefix = hw["dtbo_lane_prefix"]
            ports = hw["ports"]
            is_forecr = hw.get("is_forecr", False)
            cam0_lane_swap = hw.get("cam0_lane_swap", False)

            try:
                dtb_name, dtb_dir = _pick_base_dtb(hw, version, l4t_mode)
            except KeyError as e:
                sys.stderr.write(f"WARN: {version}/{pid}: {e}\n")
                continue

            # Resolve absolute paths
            if dtb_dir == "auvidea":
                base_dtb_path = os.path.join(REPO_ROOT, hw_cfg["auvidea_dtb_dir"], dtb_name)
            elif dtb_dir == "versioned_kernel_dtb":
                base_dtb_path = os.path.join(REPO_ROOT, version, _lft_dir(hw),
                                             "kernel", "dtb", dtb_name)
            else:
                base_dtb_path = os.path.join(REPO_ROOT, version, _lft_dir(hw),
                                             "rootfs", "boot", dtb_name)

            dtbo_boot_dir = os.path.join(REPO_ROOT, version, _lft_dir(hw), "rootfs", "boot")

            # Per-vendor entries: forecr is only valid when this platform is_forecr
            for vendor in vendors:
                if is_forecr and vendor != "forecr":
                    continue
                if not is_forecr and vendor == "forecr":
                    continue

                package_path = _find_package(version, pid, vendor)

                yield Entry(
                    version=version, jetpack=jetpack,
                    platform_id=pid, l4t_mode=l4t_mode,
                    board_short=board_short, som=som, compat=compat,
                    base_dtb=base_dtb_path, base_dtb_dir=dtb_dir,
                    dtbo_boot_dir=dtbo_boot_dir,
                    dtbo_base_prefix=dtbo_base_prefix,
                    dtbo_lane_prefix=dtbo_lane_prefix,
                    ports=ports, is_forecr=is_forecr,
                    cam0_lane_swap=cam0_lane_swap,
                    vendor=vendor, package_path=package_path,
                )


# ---------------------------------------------------------------------------

def _fmt_present(path: str | None) -> str:
    if path is None:
        return "∅"
    return "✓" if os.path.exists(path) else "✗"


def _check_coherence(entries: list[Entry]) -> list[str]:
    """Return list of fatal errors (empty = all OK)."""
    errors = []
    for e in entries:
        if not os.path.exists(e.base_dtb):
            errors.append(f"{e.version}/{e.platform_id}: base DTB missing: {e.base_dtb}")
        if not os.path.isdir(e.dtbo_boot_dir):
            errors.append(f"{e.version}/{e.platform_id}: DTBO build dir missing: {e.dtbo_boot_dir}")
        if e.package_path is None:
            errors.append(f"{e.version}/{e.platform_id} [{e.vendor}]: no .deb found — "
                          f"run l4t_make.sh --package first")
        elif not os.path.exists(e.package_path):
            errors.append(f"{e.version}/{e.platform_id} [{e.vendor}]: .deb path does not exist: "
                          f"{e.package_path}")
    return errors


def main() -> int:
    check_mode = "--check" in sys.argv
    print(f"{'Version':8} {'JP':7} {'Platform':22} {'Board':18} {'Mode':5} "
          f"{'Ports':5} {'DTB':3} {'DTBOs':5} {'.deb':4}")
    print("─" * 110)

    entries = list(generate_matrix())
    count = 0
    warn = 0
    for e in entries:
        count += 1
        dtb_ok = _fmt_present(e.base_dtb)
        dtbo_ok = _fmt_present(e.dtbo_boot_dir)
        deb_ok = _fmt_present(e.package_path)
        if "✗" in (dtb_ok, dtbo_ok) or deb_ok in ("∅", "✗"):
            warn += 1
        vendor_tag = f" [{e.vendor}]" if e.vendor != "generic" else ""
        print(f"{e.version:8} {e.jetpack:7} {e.platform_id + vendor_tag:22} "
              f"{e.board_short:18} {e.l4t_mode:5} {e.ports:5} "
              f"{dtb_ok:3} {dtbo_ok:5} {deb_ok:4}")

    print("─" * 110)
    print(f"Total entries: {count}  (warn: {warn})")

    if check_mode:
        errors = _check_coherence(entries)
        if errors:
            print()
            print("COHERENCE ERRORS:")
            for err in errors:
                print(f"  ✗ {err}")
            return 1
        print("Coherence OK — all DTBs, DTBOs, .debs are present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
