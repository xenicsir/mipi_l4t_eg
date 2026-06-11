#!/usr/bin/env python3
"""
P2b — Preinst FORCE_INSTALL_EG_CAMS + postinst cleanup tests.

Tests the two mechanisms added to the install scripts:

  Preinst FORCE bypass (4 cases):
    1. L4T mismatch, no FORCE          → rejected, "Incompatible L4T version"
    2. L4T mismatch, FORCE, kernel OK  → accepted (rc=0)
    3. L4T mismatch, FORCE, kernel KO  → rejected, "Kernel version mismatch"
    4. L4T mismatch, FORCE, kernel with -eg suffix → accepted (-eg stripped)

  Postinst cleanup (1 case):
    5. Old package providing same CANONICAL_NAME is installed
       → postinst triggers background `dpkg --purge <old-pkg>`

Runs inside the same x86_64 Docker container as P2.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = "/repo"
sys.path.insert(0, f"{REPO}/test/config")
sys.path.insert(0, f"{REPO}/test/packaging")

from test_matrix import generate_matrix, Entry   # noqa: E402
from test_postinst import (                      # noqa: E402
    prepare_fixtures, maintscript_env,
    MOCKS, PROC_DT, ETC,
)

RED, GREEN, YELLOW, CYAN, BOLD, NC = (
    "\033[0;31m", "\033[0;32m", "\033[1;33m", "\033[0;36m", "\033[1m", "\033[0m",
)

DPKG_CALLS_LOG = "/tmp/test_dpkg_calls.log"
BOGUS_L4T = ("# R99 (release), REVISION: 99.0, GCID: 00000000, "
             "BOARD: generic, EABI: aarch64, DATE: 2025-01-01 00:00:00 UTC\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_entry() -> Entry | None:
    """First non-Forecr, non-32x .deb that was built with the current delivery
    script (preinst must contain EXPECTED_KERNEL_VERSION).  Returns None if no
    such package exists yet — caller will SKIP the whole P2b suite."""
    for e in generate_matrix():
        if not (not e.is_forecr and e.l4t_mode != "32x"
                and e.package_path and os.path.exists(e.package_path)):
            continue
        ctrl = tempfile.mkdtemp(prefix="egtest_pick_")
        try:
            r = subprocess.run(["dpkg-deb", "-e", e.package_path, ctrl],
                               capture_output=True)
            if r.returncode != 0:
                continue
            preinst = os.path.join(ctrl, "preinst")
            if os.path.exists(preinst) and "EXPECTED_KERNEL_VERSION" in open(preinst).read():
                return e
        finally:
            shutil.rmtree(ctrl, ignore_errors=True)
    return None


def _pick_forecr_entry() -> Entry | None:
    """First Forecr .deb built with the current delivery script."""
    for e in generate_matrix():
        if not (e.is_forecr and e.l4t_mode != "32x"
                and e.package_path and os.path.exists(e.package_path)):
            continue
        ctrl = tempfile.mkdtemp(prefix="egtest_forecr_")
        try:
            r = subprocess.run(["dpkg-deb", "-e", e.package_path, ctrl],
                               capture_output=True)
            if r.returncode != 0:
                continue
            preinst = os.path.join(ctrl, "preinst")
            if os.path.exists(preinst) and "EXPECTED_KERNEL_VERSION" in open(preinst).read():
                return e
        finally:
            shutil.rmtree(ctrl, ignore_errors=True)
    return None


def _extract_script_info(pkg_path: str) -> dict:
    """Extract build-time constants embedded in preinst and postinst."""
    ctrl_dir = tempfile.mkdtemp(prefix="egtest_ctrl_")
    try:
        subprocess.run(["dpkg-deb", "-e", pkg_path, ctrl_dir],
                       check=True, capture_output=True)
        info: dict = {}
        extractions = {
            "preinst":  [("expected_kernel_version", r'EXPECTED_KERNEL_VERSION="([^"]+)"')],
            "postinst": [("canonical_name",          r'CANONICAL_NAME="([^"]+)"'),
                         ("current_pkg",             r'CURRENT_PKG="([^"]+)"')],
        }
        for script_name, pairs in extractions.items():
            path = os.path.join(ctrl_dir, script_name)
            if not os.path.exists(path):
                continue
            content = open(path).read()
            for key, pattern in pairs:
                m = re.search(pattern, content)
                if m:
                    info[key] = m.group(1)
        return info
    finally:
        shutil.rmtree(ctrl_dir, ignore_errors=True)


def _run_script(pkg_path: str, script_name: str, args: list,
                env: dict) -> tuple[int, str]:
    ctrl_dir = tempfile.mkdtemp(prefix=f"egtest_{script_name}_")
    try:
        subprocess.run(["dpkg-deb", "-e", pkg_path, ctrl_dir],
                       check=True, capture_output=True)
        script = os.path.join(ctrl_dir, script_name)
        if not os.path.exists(script):
            return 127, f"{script_name} not found in package"
        os.chmod(script, 0o755)
        r = subprocess.run(["bash", script] + args,
                           env=env, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr
    finally:
        shutil.rmtree(ctrl_dir, ignore_errors=True)


def _preinst_env(entry: Entry, extra: dict | None = None) -> dict:
    env = maintscript_env(entry)
    if extra:
        env.update(extra)
    return env


def _setup_proc_dt(entry: Entry) -> None:
    """Write /tmp/fake_proc_dt/nvidia,dtsfilename for preinst vendor detection."""
    os.makedirs(PROC_DT, exist_ok=True)
    val = ("/path/tegra234-p3767-dsboard-ornxs.dts" if entry.is_forecr
           else f"/path/{os.path.basename(entry.base_dtb).replace('.dtb', '.dts')}")
    with open(f"{PROC_DT}/nvidia,dtsfilename", "w") as f:
        f.write(val)


def _write_bogus_l4t() -> None:
    with open(f"{ETC}/nv_tegra_release", "w") as f:
        f.write(BOGUS_L4T)


def _write_matching_l4t(entry: Entry) -> None:
    """Write /etc/nv_tegra_release matching the entry's L4T version (L4T check passes)."""
    major, *rest = entry.version.split(".", 1)
    revision = rest[0] if rest else "0"
    with open(f"{ETC}/nv_tegra_release", "w") as f:
        f.write(f"# R{major} (release), REVISION: {revision}, GCID: 00000000, "
                "BOARD: generic, EABI: aarch64, DATE: 2025-01-01 00:00:00 UTC\n")


def _install_mock(name: str, content: str) -> None:
    p = f"{MOCKS}/{name}"
    with open(p, "w") as f:
        f.write(content)
    os.chmod(p, 0o755)


def _remove_mock(name: str) -> None:
    p = f"{MOCKS}/{name}"
    if os.path.exists(p):
        os.remove(p)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_l4t_mismatch_rejected(entry: Entry) -> tuple[str, str]:
    """preinst: L4T mismatch, no FORCE → rc=1, 'Incompatible L4T version'."""
    _write_bogus_l4t()
    _setup_proc_dt(entry)
    rc, out = _run_script(entry.package_path, "preinst", ["install"],
                          env=_preinst_env(entry))
    if rc == 0:
        return "fail", "preinst accepted L4T mismatch without FORCE (expected rejection)"
    if "Incompatible L4T version" not in out:
        return "fail", f"unexpected error message: {out.strip()[-200:]}"
    return "pass", "rc=1, 'Incompatible L4T version'"


def test_force_kernel_match(entry: Entry, expected_kernel: str) -> tuple[str, str]:
    """preinst: L4T mismatch + FORCE + correct kernel → rc=0."""
    _write_bogus_l4t()
    _setup_proc_dt(entry)
    _install_mock("uname", f"#!/bin/sh\necho '{expected_kernel}'\n")
    try:
        rc, out = _run_script(entry.package_path, "preinst", ["install"],
                              env=_preinst_env(entry, {"FORCE_INSTALL_EG_CAMS": "1"}))
        if rc != 0:
            return "fail", f"preinst rejected correct kernel (rc={rc}): {out.strip()[-200:]}"
        return "pass", f"rc=0, kernel '{expected_kernel}' accepted"
    finally:
        _remove_mock("uname")


def test_force_kernel_mismatch(entry: Entry) -> tuple[str, str]:
    """preinst: L4T mismatch + FORCE + wrong kernel → rc=1, 'Kernel version mismatch'."""
    _write_bogus_l4t()
    _setup_proc_dt(entry)
    _install_mock("uname", "#!/bin/sh\necho '5.10.000-tegra'\n")
    try:
        rc, out = _run_script(entry.package_path, "preinst", ["install"],
                              env=_preinst_env(entry, {"FORCE_INSTALL_EG_CAMS": "1"}))
        if rc == 0:
            return "fail", "preinst accepted wrong kernel (expected rejection)"
        if "Kernel version mismatch" not in out:
            return "fail", f"unexpected error message: {out.strip()[-200:]}"
        return "pass", "rc=1, 'Kernel version mismatch'"
    finally:
        _remove_mock("uname")


def test_force_kernel_eg_suffix(entry: Entry, expected_kernel: str) -> tuple[str, str]:
    """preinst: L4T mismatch + FORCE + uname returns kernel with -eg suffix → rc=0."""
    _write_bogus_l4t()
    _setup_proc_dt(entry)
    # Build the -eg variant: strip any existing -eg then append -eg
    base = expected_kernel[:-3] if expected_kernel.endswith("-eg") else expected_kernel
    kernel_with_eg = base + "-eg"
    _install_mock("uname", f"#!/bin/sh\necho '{kernel_with_eg}'\n")
    try:
        rc, out = _run_script(entry.package_path, "preinst", ["install"],
                              env=_preinst_env(entry, {"FORCE_INSTALL_EG_CAMS": "1"}))
        if rc != 0:
            return "fail", (f"preinst rejected '{kernel_with_eg}' "
                            f"(expected -eg suffix to be stripped): {out.strip()[-200:]}")
        return "pass", f"rc=0, '{kernel_with_eg}' → -eg stripped, matched '{expected_kernel}'"
    finally:
        _remove_mock("uname")


def test_postinst_cleanup(entry: Entry, info: dict) -> tuple[str, str]:
    """postinst: old package in same family → dpkg --purge called asynchronously."""
    canonical = info.get("canonical_name")
    current_pkg = info.get("current_pkg")
    if not canonical or not current_pkg:
        return "fail", "CANONICAL_NAME / CURRENT_PKG not found in postinst"

    old_pkg = "jetson-l4t-99.0.0-jp9.0.0-eg-cams"

    if os.path.exists(DPKG_CALLS_LOG):
        os.remove(DPKG_CALLS_LOG)

    _install_mock(
        "dpkg-query",
        "#!/bin/sh\n"
        f"printf '%s\\t%s\\t%s\\n' '{old_pkg}' 'install ok installed' '{canonical}'\n"
        "exit 0\n",
    )
    _install_mock(
        "dpkg",
        f"#!/bin/sh\necho \"$@\" >> {DPKG_CALLS_LOG}\nexit 0\n",
    )
    _install_mock("sleep", "#!/bin/sh\nexit 0\n")

    try:
        prepare_fixtures(entry, "previously_eg")
        rc, out = _run_script(entry.package_path, "postinst", ["configure"],
                              env=maintscript_env(entry))
        # Give background subshell time to complete (sleep mock is instant)
        time.sleep(0.5)

        if rc != 0:
            return "fail", f"postinst failed rc={rc}: {out.strip()[-200:]}"

        if not os.path.exists(DPKG_CALLS_LOG):
            return "fail", "dpkg was never called — cleanup did not trigger"

        calls = open(DPKG_CALLS_LOG).read()
        if "--purge" not in calls or old_pkg not in calls:
            return "fail", f"expected 'dpkg --purge {old_pkg}', got: {calls.strip()}"

        return "pass", f"dpkg --purge {old_pkg} called correctly"
    finally:
        _remove_mock("dpkg-query")
        _remove_mock("dpkg")
        _remove_mock("sleep")
        if os.path.exists(DPKG_CALLS_LOG):
            os.remove(DPKG_CALLS_LOG)


# ---------------------------------------------------------------------------
# Vendor detection tests
# ---------------------------------------------------------------------------
# Note: Method 1 (DTB /proc/device-tree) cannot be faked on x86 Docker (procfs
# is read-only).  Only method 2 (dpkg -l) is testable here via a mock binary in
# MOCKS.  When no mock is installed, real dpkg -l returns no jetson forecr
# package in the container → RUNNING_VENDOR stays "generic" → first-install path.

_FORECR_DPKG_MOCK = (
    "#!/bin/sh\n"
    "[ \"$1\" = '-l' ] && "
    "echo 'ii  jetson-l4t-36.4.4-forecr-dsboard-ornx-eg-cams 1.0 arm64 -'\n"
)


def test_vendor_mismatch_blocked(entry: Entry) -> tuple[str, str]:
    """preinst: dpkg shows forecr board, but package is generic → blocked."""
    _write_matching_l4t(entry)
    _install_mock("dpkg", _FORECR_DPKG_MOCK)
    try:
        rc, out = _run_script(entry.package_path, "preinst", ["install"],
                              env=_preinst_env(entry))
        if rc == 0:
            return "fail", "preinst accepted generic package on identified forecr board (expected rejection)"
        if "Board vendor mismatch" not in out:
            return "fail", f"unexpected error: {out.strip()[-200:]}"
        return "pass", "rc=1, 'Board vendor mismatch'"
    finally:
        _remove_mock("dpkg")


def test_vendor_forecr_unconditional(entry: Entry) -> tuple[str, str]:
    """preinst: forecr package → vendor check skipped, installs unconditionally.

    The dpkg mock is active (would block a generic package) to prove the forecr
    package bypasses vendor detection entirely, not just via first-install logic.
    """
    _write_matching_l4t(entry)
    _install_mock("dpkg", _FORECR_DPKG_MOCK)
    try:
        rc, out = _run_script(entry.package_path, "preinst", ["install"],
                              env=_preinst_env(entry))
        if rc != 0:
            return "fail", f"preinst rejected forecr package (rc={rc}): {out.strip()[-200:]}"
        return "pass", "rc=0, forecr package installs unconditionally"
    finally:
        _remove_mock("dpkg")


# ---------------------------------------------------------------------------

def _pass(m): print(f"  {GREEN}PASS{NC}  {m}")
def _fail(m): print(f"  {RED}FAIL{NC}  {m}")


def main() -> int:
    entry = _pick_entry()
    if entry is None:
        print(f"{YELLOW}SKIP{NC}  No package with EXPECTED_KERNEL_VERSION found — "
              f"rebuild packages with the current l4t_gen_delivery_package.sh first")
        return 0

    info = _extract_script_info(entry.package_path)
    expected_kernel = info.get("expected_kernel_version")

    forecr_entry = _pick_forecr_entry()

    print(f"\n{BOLD}{CYAN}━━━ P2b — Preinst FORCE + vendor detection + postinst cleanup "
          f"(L4T {entry.version} / {entry.vendor}) ━━━{NC}")

    if not expected_kernel:
        print(f"  {RED}FAIL{NC}  EXPECTED_KERNEL_VERSION not found in preinst "
              f"— was the package built with the current script?")
        return 1

    tests = [
        ("l4t_mismatch_rejected",
         lambda: test_l4t_mismatch_rejected(entry)),
        ("force_kernel_match",
         lambda: test_force_kernel_match(entry, expected_kernel)),
        ("force_kernel_mismatch",
         lambda: test_force_kernel_mismatch(entry)),
        ("force_kernel_eg_suffix",
         lambda: test_force_kernel_eg_suffix(entry, expected_kernel)),
        ("postinst_cleanup",
         lambda: test_postinst_cleanup(entry, info)),
        # Vendor detection tests (method 2: dpkg -l, mockable on x86)
        ("vendor_mismatch_blocked",
         lambda: test_vendor_mismatch_blocked(entry)),
        ("vendor_forecr_unconditional",
         lambda: (test_vendor_forecr_unconditional(forecr_entry) if forecr_entry
                  else ("skip", "no forecr .deb available"))),
    ]

    passed = failed = skipped = 0
    failures: list[str] = []

    for name, fn in tests:
        label = f"preinst_force/{name}"
        try:
            outcome, detail = fn()
        except Exception as e:
            outcome, detail = "fail", f"exception: {e}"

        if outcome == "pass":
            passed += 1
            _pass(f"{label}: {detail}")
        elif outcome == "skip":
            skipped += 1
            print(f"  {YELLOW}SKIP{NC}  {label}: {detail}")
        else:
            failed += 1
            failures.append(label)
            _fail(f"{label}: {detail}")

    print()
    skip_str = f"  {YELLOW}{skipped} skipped{NC}" if skipped else ""
    print(f"{BOLD}P2b results: {GREEN}{passed} passed{NC}{skip_str}  {RED}{failed} failed{NC}")
    if failures:
        print(f"\n{BOLD}Failed:{NC}")
        for f in failures:
            print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
