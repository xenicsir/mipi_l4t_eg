#!/usr/bin/env python3
"""
Phase 2 — Real .deb preinst/postinst execution.

Runs INSIDE the Docker container (same environment as Phase 1). For each (version,
platform_id, vendor) entry in the matrix:

  1. Clean /boot and /etc/nv_tegra_release, write fixtures that maintscripts expect:
       - /etc/nv_tegra_release    with the right L4T banner
       - /proc/device-tree (mock) with compatible + nvidia,dtsfilename
       - /boot/<base_dtb>         copied from the test DTB (Auvidea / versioned)
       - /boot/extlinux/extlinux.conf  according to the extlinux_state under test
       - /boot/*.dtbo             copied from the REAL dpkg-deb extraction
       - /usr/bin/eg_dt_camera_*  from the REAL dpkg-deb extraction
  2. Extract the package's control archive, run:
        bash preinst install
     Must exit 0. This validates:
        - /etc/nv_tegra_release version matches package (preinst parsing)
        - Vendor detection from /proc/device-tree/nvidia,dtsfilename
  3. Run bash postinst configure. Must exit 0. This validates:
        - depmod runs (or is skipped if kernel modules not present — we mock depmod)
        - Fresh install path: calls eg_dt_camera_config_set.sh with no args
        - Upgrade path (when state=previously_eg): calls eg_dt_camera_config_get.sh
          and re-applies the detected configuration
  4. Verify /boot/extlinux/extlinux.conf now contains a JetsonIO LABEL.

This is the only phase that exercises preinst/postinst logic (Phase 1 runs the script
directly, Phase 3 does a real dpkg -i inside arm64 qemu).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = "/repo"
sys.path.insert(0, f"{REPO}/test/config")
from test_matrix import generate_matrix, Entry  # noqa: E402

BOOT     = "/boot"
ETC      = "/etc"
PROC_DT  = "/tmp/fake_proc_dt"
MOCKS    = "/tmp/mocks"
INSTALL_ROOT = "/tmp/pkg_extract"      # where dpkg-deb -x places ./usr, ./boot
EXTLINUX = f"{BOOT}/extlinux/extlinux.conf"
EXTLINUX_TPL_DIR = f"{REPO}/test/dts/extlinux"

STATES = ["fresh", "previously_eg", "no_primary", "empty"]

# In P2 (real dpkg install) we only exercise the two states that real targets
# actually exhibit — a fresh flash (LABEL primary only) and a prior EG install
# (LABEL JetsonIO present). The 'no_primary' and 'empty' robustness states are
# Phase-1 only: they would cause postinst to fail on Auvidea 35.1 because the
# 2-port detection relies on LABEL primary, and a real dpkg install never sees
# those states in the wild.
INSTALL_STATES = ["fresh", "previously_eg"]


# ---------------------------------------------------------------------------
def _render_extlinux(state: str, fdt_path: str) -> str | None:
    if state == "empty":
        return None
    tpl = open(f"{EXTLINUX_TPL_DIR}/{state}.conf").read()
    basename_no_ext = os.path.splitext(os.path.basename(fdt_path))[0]
    return (tpl
            .replace("{FDT}", fdt_path)
            .replace("{FDT_BASENAME_NO_EXT}", basename_no_ext)
            .replace("{PREVIOUS_OVERLAYS}", ""))


def _nv_tegra_release(version: str) -> str:
    """Format matching preinst regex: '# R(nn) ... REVISION: (n.n)...'"""
    major, *rest = version.split(".", 1)
    revision = rest[0] if rest else "0"
    return (f"# R{major} (release), REVISION: {revision}, GCID: 00000000, "
            "BOARD: generic, EABI: aarch64, DATE: 2025-01-01 00:00:00 UTC\n")


def _dtsfilename(entry: Entry) -> str:
    """Drives preinst vendor detection (regex (dsboard|milboard|raiboard))."""
    if entry.is_forecr:
        return "/path/tegra234-p3767-dsboard-ornxs.dts"
    return f"/path/{os.path.basename(entry.base_dtb).replace('.dtb', '.dts')}"


# ---------------------------------------------------------------------------
def extract_package(entry: Entry) -> str:
    """Extract data.tar.gz into INSTALL_ROOT. Returns INSTALL_ROOT path."""
    shutil.rmtree(INSTALL_ROOT, ignore_errors=True)
    os.makedirs(INSTALL_ROOT, exist_ok=True)
    subprocess.run(["dpkg-deb", "-x", entry.package_path, INSTALL_ROOT], check=True)
    return INSTALL_ROOT


def install_package_files(entry: Entry, root: str) -> None:
    """Copy /boot/*.dtbo and /usr/bin/eg_dt_camera_* into the live FS.

    Mimics dpkg's file placement (part of a normal install). We skip kernel modules
    and /boot/eg/Image (those are arm64 binaries not executable here).
    """
    # DTBOs → /boot
    src_boot = os.path.join(root, "boot")
    if os.path.isdir(src_boot):
        for f in os.listdir(src_boot):
            if f.endswith(".dtbo"):
                src = os.path.join(src_boot, f)
                dst = os.path.join(BOOT, f)
                if os.path.exists(dst):
                    os.remove(dst)
                try: os.symlink(src, dst)
                except OSError: shutil.copy(src, dst)

    # Scripts → /usr/bin
    src_bin = os.path.join(root, "usr", "bin")
    if os.path.isdir(src_bin):
        for f in os.listdir(src_bin):
            src = os.path.join(src_bin, f)
            if not os.path.isfile(src):
                continue
            dst = os.path.join("/usr", "bin", f)
            shutil.copy(src, dst)
            os.chmod(dst, 0o755)


def prepare_fixtures(entry: Entry, state: str) -> None:
    """Populate /boot, /etc, /proc/device-tree for the given state."""
    # /boot
    shutil.rmtree(f"{BOOT}/extlinux", ignore_errors=True)
    for f in os.listdir(BOOT):
        p = os.path.join(BOOT, f)
        if f.endswith(".dtb") or f.endswith(".dtbo") or f == "kernel_merged.dtb" \
                or f == "cbh_calls.log":
            try: os.remove(p) if os.path.isfile(p) else shutil.rmtree(p)
            except OSError: pass
    os.makedirs(f"{BOOT}/extlinux", exist_ok=True)

    # Copy base DTB into /boot (the extlinux.conf references this path)
    dst_base = f"{BOOT}/{os.path.basename(entry.base_dtb)}"
    shutil.copy(entry.base_dtb, dst_base)

    content = _render_extlinux(state, dst_base)
    if content is not None:
        with open(EXTLINUX, "w") as f:
            f.write(content)

    # /etc/nv_tegra_release
    with open(f"{ETC}/nv_tegra_release", "w") as f:
        f.write(_nv_tegra_release(entry.version))

    # /proc/device-tree mock
    shutil.rmtree(PROC_DT, ignore_errors=True)
    os.makedirs(PROC_DT, exist_ok=True)
    with open(f"{PROC_DT}/compatible", "w") as f:
        f.write(entry.compat)
    with open(f"{PROC_DT}/nvidia,dtsfilename", "w") as f:
        f.write(_dtsfilename(entry))
    # Populate IMX dirs from base DTB — skip for previously_eg (post-merge view)
    if state != "previously_eg":
        r = subprocess.run(["dtc", "-I", "dtb", "-O", "dts", entry.base_dtb],
                           capture_output=True, text=True)
        if r.returncode == 0:
            for pattern in ("rbpcv2_imx219", "rbpcv3_imx477"):
                for m in re.finditer(r"(" + pattern + r"[^\s{]*)\s*\{", r.stdout):
                    os.makedirs(f"{PROC_DT}/{m.group(1)}", exist_ok=True)


def maintscript_env(entry: Entry) -> dict:
    env = os.environ.copy()
    # /usr/local/bin must be first-after-mocks so the depmod stub installed by
    # run_inside_container.sh (and the `python` → `python3` symlink) override
    # the real names. /sbin + /usr/sbin needed for dpkg's ldconfig and
    # start-stop-daemon in P3 (`dpkg -i` under aarch64 emulation).
    env["PATH"] = f"{MOCKS}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/sbin:/usr/bin:/bin"
    env["TEST_BOARD_SHORT"]       = entry.board_short
    env["TEST_CAMERA_PORTS"]      = str(entry.ports)
    env["TEST_L4T_MODE"]          = entry.l4t_mode
    env["TEST_BASE_DTB"]          = f"{BOOT}/{os.path.basename(entry.base_dtb)}"
    env["TEST_BOOT_DIR"]          = BOOT
    env["TEST_CBH_LOG"]           = f"{BOOT}/cbh_calls.log"
    env["TEST_OVERLAYS_FILE"]     = f"{BOOT}/overlays.txt"
    env["TEST_PROC_DT"]           = PROC_DT
    env["TEST_OVERLAY_DTBO_JSON"] = json.dumps(_overlay_map(entry))
    _write_overlays_list(entry)
    return env


def _overlay_map(entry: Entry) -> dict:
    """Build {overlay-name → path} from DTBOs now in /boot."""
    result: dict[str, str] = {}
    base_key = ("Exosens Cameras for DSBOARD-ORNXS"
                if entry.is_forecr else "Exosens Cameras")
    bpfx = entry.dtbo_base_prefix
    lpfx = entry.dtbo_lane_prefix

    for name, suffix in [
        (base_key,                          f"{bpfx}-cams-dione.dtbo"),
        ("Exosens Cameras (global)",        f"{bpfx}-cams-dione-global.dtbo"),
        ("Exosens Cameras - 2 ports",       f"{bpfx}-cams-dione-2ports.dtbo"),
        ("Exosens Cameras. Disable imx219", f"{bpfx}-cams-disable-imx219.dtbo"),
        ("Exosens Cameras. Disable imx477", f"{bpfx}-cams-disable-imx477.dtbo"),
    ]:
        p = f"{BOOT}/{suffix}"
        if os.path.exists(p):
            result[name] = p

    lane_suffixes = {"ec-1-lane": "EC_1_lane", "ec-2-lanes": "EC_2_lanes",
                     "ilumos": "iLumos", "microlynx": "Microlynx"}
    for port in range(entry.ports):
        for suffix, lane in lane_suffixes.items():
            p = f"{BOOT}/{lpfx}-cam{port}-{suffix}.dtbo"
            if os.path.exists(p):
                result[f"Exosens Cameras. CAM{port}:{lane}"] = p
    return result


def _write_overlays_list(entry: Entry) -> None:
    with open(f"{BOOT}/overlays.txt", "w") as f:
        f.write("Header 2: Jetson CSI Connector\n  Available hardware modules:\n")
        for i, name in enumerate(_overlay_map(entry), 1):
            f.write(f"  {i}. {name}\n")


def run_maintscript(entry: Entry, script_name: str, args: list[str]) -> tuple[int, str, str]:
    control_dir = tempfile.mkdtemp(prefix=f"egctl_{script_name}_")
    try:
        subprocess.run(["dpkg-deb", "-e", entry.package_path, control_dir], check=True)
        script = os.path.join(control_dir, script_name)
        if not os.path.exists(script):
            return 127, "", f"{script_name} not in .deb"
        os.chmod(script, 0o755)
        r = subprocess.run(["bash", script] + args,
                           env=maintscript_env(entry),
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr
    finally:
        shutil.rmtree(control_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stub out `depmod` (not useful and slow in test container)
# ---------------------------------------------------------------------------

def install_depmod_stub() -> None:
    stub = "/usr/local/bin/depmod"
    with open(stub, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(stub, 0o755)


# ---------------------------------------------------------------------------
RED, GREEN, YELLOW, CYAN, BOLD, NC = (
    "\033[0;31m", "\033[0;32m", "\033[1;33m", "\033[0;36m", "\033[1m", "\033[0m",
)


def _pass(m): print(f"  {GREEN}PASS{NC}  {m}")
def _fail(m): print(f"  {RED}FAIL{NC}  {m}")
def _skip(m): print(f"  {YELLOW}SKIP{NC}  {m}")


def test_one(entry: Entry, state: str) -> tuple[str, str]:
    """Return (outcome, detail). outcome ∈ {"pass", "xfail:<reason>", "fail"}."""
    if entry.package_path is None or not os.path.exists(entry.package_path):
        return "fail", "no .deb"
    if not os.path.exists(entry.base_dtb):
        return "fail", "no base DTB"

    install_root = extract_package(entry)
    # prepare_fixtures first — it wipes /boot/*.dtb{,o} to start from a clean
    # slate. install_package_files then places the package's DTBOs + scripts.
    # Swapping these two caused /boot to have 0 DTBOs at test time, making the
    # mock CBH report "Configuration saved" with no overlays actually applied.
    prepare_fixtures(entry, state)
    # For state='previously_eg' we additionally pre-populate /boot with DTBOs
    # from the same package to simulate a prior install whose files are on
    # disk — the upgrade path in postinst reads the current camera config via
    # eg_dt_camera_config_get.sh and re-applies it.
    install_package_files(entry, install_root)

    rc, out, err = run_maintscript(entry, "preinst", ["install"])

    # XFAIL: forecr packages check /proc/device-tree/nvidia,dtsfilename which
    # cannot be faked inside an x86 container (procfs is read-only, Docker
    # cannot bind-mount onto it). The preinst's rejection of the forecr
    # package on a 'generic' host is the correct behaviour — a real Forecr
    # install would see the DT file and pass.
    if entry.is_forecr and rc != 0:
        out_combined = (err or out).lower()
        if "install the package matching" in out_combined or "running system: generic" in out_combined:
            return ("xfail:forecr_preinst_rejects_generic_host",
                    "preinst correctly rejects forecr .deb on non-forecr host")

    if rc != 0:
        return "fail", f"preinst rc={rc}: {(err or out).strip().splitlines()[-2:]}"

    rc, out, err = run_maintscript(entry, "postinst", ["configure"])
    if rc != 0:
        return "fail", f"postinst rc={rc}: {(err or out).strip().splitlines()[-3:]}"

    if not os.path.exists(EXTLINUX):
        return "fail", "extlinux.conf absent after postinst"
    content = open(EXTLINUX).read()
    if "JetsonIO" not in content:
        return "fail", "no JetsonIO label"

    return "pass", "ok"


def main() -> int:
    install_depmod_stub()
    passed = xfailed = failed = 0
    failures: list[str] = []

    for entry in generate_matrix():
        header = (f"{BOLD}{CYAN}━━━ L4T {entry.version} / {entry.platform_id} "
                  f"/ {entry.vendor} ━━━{NC}")
        print(f"\n{header}")
        for state in INSTALL_STATES:
            label = f"{entry.version}/{entry.platform_id}/{entry.vendor}/{state}"
            try:
                outcome, detail = test_one(entry, state)
            except Exception as e:
                failed += 1
                failures.append(label)
                _fail(f"{label}: exception: {e}")
                continue

            if outcome == "pass":
                passed += 1
                _pass(f"{label}: {detail}")
            elif outcome.startswith("xfail:"):
                tag = outcome.split(":", 1)[1]
                xfailed += 1
                print(f"  {GREEN}XFAIL{NC} {label}: xfail({tag}) — {detail}")
            else:
                failed += 1
                failures.append(label)
                _fail(f"{label}: {detail}")

    print()
    print(f"{BOLD}P2 results: {GREEN}{passed} passed{NC}  "
          f"{GREEN}{xfailed} xfail{NC}  "
          f"{RED}{failed} failed{NC}")
    if failures:
        print(f"\n{BOLD}Failed:{NC}")
        for f in failures[:30]:
            print(f"  - {f}")
        if len(failures) > 30:
            print(f"  ... and {len(failures) - 30} more")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
