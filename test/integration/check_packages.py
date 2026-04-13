#!/usr/bin/env python3
"""
check_packages.py — Verify .deb package contents for all L4T versions.

For each (version_dir, variant) pair, picks the .deb built from the most recent
git commit, extracts it to a temp directory, and verifies:
  - usr/bin/eg_dt_camera_config_set.sh present + executable
  - etc/version_eg_cams present
  - All boot/*.dtbo parseable by dtc
  - At least one *-cams-dione.dtbo present
  - At least one *-cam*-ilumos.dtbo present
  - At least one *-cam*-microlynx.dtbo present
  - Expected .ko camera drivers (35.x/36.x: ilumos + microlynx; 32.x: ec + dione only)

Runs on host. Requires: dpkg-deb, dtc, git.
"""

import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

GREEN = "\033[92m"
RED   = "\033[91m"
NC    = "\033[0m"

PASS = f"{GREEN}PASS{NC}"
FAIL = f"{RED}FAIL{NC}"


# ---------------------------------------------------------------------------
# Git commit ordering
# ---------------------------------------------------------------------------

def get_commit_order():
    """Return list of short hashes, index 0 = most recent."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "--format=%h"],
        capture_output=True, text=True, check=True,
    )
    return [h.strip() for h in result.stdout.strip().splitlines() if h.strip()]


def commit_rank(short_hash, commit_order):
    """Lower rank = more recent. Unknown hash → oldest."""
    for i, h in enumerate(commit_order):
        if h.startswith(short_hash) or short_hash.startswith(h):
            return i
    return len(commit_order)


def pick_latest_deb(debs, commit_order):
    """From a list of .deb paths containing +g<hash>, return the most recent."""
    def rank(p):
        m = re.search(r"\+g([0-9a-f]+)_arm64", p)
        return commit_rank(m.group(1), commit_order) if m else len(commit_order)
    return min(debs, key=rank)


# ---------------------------------------------------------------------------
# Package checks
# ---------------------------------------------------------------------------

def version_family(version_dir):
    """'32', '35', or '36' from version directory name like '35.6.2'."""
    return version_dir.split(".")[0]


def find_ko(extract_dir, name):
    """Find <name>.ko anywhere under lib/modules/**/drivers/media/i2c/."""
    pattern = str(extract_dir / "lib" / "modules" / "**" / "drivers" / "media" / "i2c" / name)
    return bool(glob.glob(pattern, recursive=True))


def check_package(deb_path, version_dir, label, som=""):
    """
    Extract deb_path and run all checks.
    Returns (passed, failed, errors) where errors is a list of strings.
    """
    passed = 0
    errors = []

    family = version_family(version_dir)
    has_dtbos = (som != "t186")  # t186 has no device tree overlays

    with tempfile.TemporaryDirectory(prefix="eg_pkg_") as tmpdir:
        extract_dir = Path(tmpdir) / "pkg"
        extract_dir.mkdir()

        # Extract
        r = subprocess.run(
            ["dpkg-deb", "--extract", str(deb_path), str(extract_dir)],
            capture_output=True,
        )
        if r.returncode != 0:
            return 0, 1, [f"dpkg-deb extract failed: {r.stderr.decode().strip()}"]

        # --- Script present and executable ---
        script = extract_dir / "usr" / "bin" / "eg_dt_camera_config_set.sh"
        if script.exists() and os.access(script, os.X_OK):
            passed += 1
        else:
            errors.append("usr/bin/eg_dt_camera_config_set.sh missing or not executable")

        # --- Version file present ---
        ver_file = extract_dir / "etc" / "version_eg_cams"
        if ver_file.exists():
            passed += 1
        else:
            errors.append("etc/version_eg_cams missing")

        # --- DTBOs: collect all ---
        boot_dir = extract_dir / "boot"
        dtbos = sorted(boot_dir.glob("*.dtbo")) if boot_dir.exists() else []

        if not has_dtbos:
            pass  # t186: no DTBOs expected, skip all DTBO checks
        elif not dtbos:
            errors.append("No .dtbo files found in boot/")
        else:
            # All DTBOs parseable
            bad_dtbos = []
            for dtbo in dtbos:
                r = subprocess.run(
                    ["dtc", "-I", "dtb", "-O", "dts", "-q", str(dtbo)],
                    capture_output=True,
                )
                if r.returncode != 0:
                    bad_dtbos.append(dtbo.name)
            if bad_dtbos:
                errors.append(f"DTBOs not parseable by dtc: {', '.join(bad_dtbos)}")
            else:
                passed += 1  # all DTBOs OK

            dtbo_names = {d.name for d in dtbos}

            # cams-dione.dtbo present
            if any("cams-dione" in n for n in dtbo_names):
                passed += 1
            else:
                errors.append("No *-cams-dione.dtbo found in boot/")

            # cam*-ilumos.dtbo present
            if any(re.search(r"cam\d+-ilumos", n) for n in dtbo_names):
                passed += 1
            else:
                errors.append("No *-cam*-ilumos.dtbo found in boot/")

            # cam*-microlynx.dtbo present
            if any(re.search(r"cam\d+-microlynx", n) for n in dtbo_names):
                passed += 1
            else:
                errors.append("No *-cam*-microlynx.dtbo found in boot/")

        # --- Kernel modules ---
        # All families: eg-ec-mipi.ko and dione_ir.ko
        for ko in ("eg-ec-mipi.ko", "dione_ir.ko"):
            if find_ko(extract_dir, ko):
                passed += 1
            else:
                errors.append(f"{ko} missing from lib/modules/")

        # 35.x and 36.x only: ilumos.ko, microlynx.ko
        if family in ("35", "36"):
            for ko in ("ilumos.ko", "microlynx.ko"):
                if find_ko(extract_dir, ko):
                    passed += 1
                else:
                    errors.append(f"{ko} missing from lib/modules/")

    failed = len(errors)
    return passed, failed, errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract_som(deb_name):
    """Return the SoM name (e.g. 't210', 't186') from a .deb filename, or ''.

    Handles both old format (jetson-l4t-32.7.1-t210-eg-cams) and new format
    with JetPack infix (jetson-l4t-32.7.1-jp4.6.1-t210-eg-cams).
    """
    m = re.search(r"jetson-l4t-[\d.]+(?:-jp[\d.]+)?-(t\d+)-eg-cams", deb_name)
    return m.group(1) if m else ""


def main():
    commit_order = get_commit_order()

    # Discover all .deb files: REPO_ROOT/<version_dir>/*.deb
    # version_dirs start with digits (32.*, 35.*, 36.*)
    all_debs = sorted(REPO_ROOT.glob("[0-9]*/*.deb"))

    # Group by (version_dir, som, is_forecr)
    groups = {}
    for deb in all_debs:
        version_dir = deb.parent.name
        som = extract_som(deb.name)
        is_forecr = bool(re.search(r"forecr-dsboard-ornx", deb.name))
        key = (version_dir, som, is_forecr)
        groups.setdefault(key, []).append(str(deb))

    total_passed = 0
    total_failed = 0
    fail_details = []

    print(f"\n{'Label':<45} {'Result'}")
    print("-" * 60)

    for (version_dir, som, is_forecr), debs in sorted(groups.items()):
        variant = "forecr" if is_forecr else "nvidia"
        som_str = f"-{som}" if som else ""
        label = f"{version_dir}{som_str} | {variant}"

        deb_path = Path(pick_latest_deb(debs, commit_order))
        commit_m = re.search(r"\+g([0-9a-f]+)_arm64", deb_path.name)
        commit_str = commit_m.group(1) if commit_m else "?"

        passed, failed, errors = check_package(deb_path, version_dir, label, som=som)
        total_passed += passed
        total_failed += failed

        status = PASS if failed == 0 else FAIL
        print(f"  {label:<43} {status}  (commit {commit_str}, {passed}p/{failed}f)")

        for err in errors:
            print(f"      {RED}✗{NC} {err}")
            fail_details.append(f"{label}: {err}")

    print("-" * 60)
    total = total_passed + total_failed
    print(f"\nPackage checks: {total_passed}/{total} passed", end="")
    if total_failed:
        print(f", {RED}{total_failed} FAILED{NC}")
    else:
        print(f"  {GREEN}ALL OK{NC}")

    if fail_details:
        sys.exit(1)


if __name__ == "__main__":
    main()
