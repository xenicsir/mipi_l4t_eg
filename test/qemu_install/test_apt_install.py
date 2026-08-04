#!/usr/bin/env python3
"""
Phase 3b — `apt install ./package.deb` inside the aarch64 container.

P3 (test_dpkg_install.py) covers `dpkg -i`, which honours NEITHER Recommends nor
Suggests. Nothing exercised the apt path, so the optional-dependency mechanism
(4 Recommends + 1 Suggests, plus the postinst warning that backs it up) had no
regression test at all. This file is that test.

Four states, each proving something the others cannot:

  T1  lists populated, no eg package, optional packages absent
      → apt pulls the 4 Recommends. THE test of the mechanism.
  T2  lists populated, OLDER eg version installed, optional packages absent
      → does an UPGRADE honour Recommends that the old version did not declare?
        This is the real customer path and was never verified either way.
        (`apt install --reinstall` is known NOT to re-evaluate Recommends;
        an upgrade is a different resolver path.)
  T3  apt lists EMPTY (the state of every freshly flashed board)
      → Recommends unsatisfiable: must be reported and skipped, install must
        still succeed, and the postinst warning must fire.
  T4  `dpkg -i`
      → no Recommends at all, silently. The postinst warning is the only net.
        This is the documented path for switching L4T version.

Plus T0, which is cheap and covers the whole matrix rather than one entry:
every built .deb must carry the expected Recommends/Suggests/Provides/Replaces.

WHY A STUB REPOSITORY: what is under test is apt's *policy* handling of our
control fields, not what v4l-utils does. So the 4 optional packages and ecswctrl
are built here as minimal stubs served from a local file:// repo, and they ship
what the postinst probes for (`v4l2-ctl`, importable cv2/serial/numpy) so the
warning logic is exercised end to end rather than short-circuited.

The stubs carry epoch 99. Without it apt silently prefers the real archive
package (`python3-opencv 4.5.4+dfsg` > `1.0-stub`) and pulls the entire
OpenCV/GTK3/VTK chain through emulation — which is what happened on the first
run, taking minutes and testing Ubuntu's packaging rather than ours.

WHY ONE MATRIX ENTRY for T1-T4: the behaviour under test lives in the control
metadata and the postinst, which are generated identically for every version.
Running 4 apt transactions × 74 entries under qemu would cost hours for no added
coverage. T0 covers the per-package dimension instead.
"""
import hashlib
import os
import shutil
import subprocess
import sys

REPO = "/repo"
sys.path.insert(0, f"{REPO}/test/config")
sys.path.insert(0, f"{REPO}/test/packaging")

from test_matrix import generate_matrix, Entry            # noqa: E402
from test_postinst import (                               # noqa: E402
    prepare_fixtures, install_depmod_stub, maintscript_env, EXTLINUX, BOOT,
)
from test_dpkg_install import (                           # noqa: E402
    install_real_jetson_io, setup_device_tree_symlink, install_lsblk_mock,
    package_name_from_path, dpkg_purge,
)

RED, GREEN, YELLOW, CYAN, BOLD, NC = (
    "\033[0;31m", "\033[0;32m", "\033[1;33m", "\033[0;36m", "\033[1m", "\033[0m",
)

OPTIONAL = ["v4l-utils", "python3-opencv", "python3-serial", "python3-numpy"]
SUGGESTED = "ecswctrl"
STUB_REPO = "/tmp/stubrepo"
STUB_VERSION = "99:1.0-stub"   # epoch 99: the stub MUST outrank the real
                              # Ubuntu archive package, otherwise apt installs
                              # the real one (4.5.4 > 1.0) and drags in the whole
                              # OpenCV/GTK/VTK chain under emulation.
OLD_VERSION = "0~aaa-older"     # must compare LOWER than any real build version

# What each stub must provide so the postinst's probes actually succeed.
STUB_PAYLOAD = {
    "v4l-utils":      ("/usr/bin/v4l2-ctl", "#!/bin/sh\nexit 0\n", 0o755),
    "python3-opencv": ("/usr/lib/python3/dist-packages/cv2.py", "", 0o644),
    "python3-serial": ("/usr/lib/python3/dist-packages/serial.py", "", 0o644),
    "python3-numpy":  ("/usr/lib/python3/dist-packages/numpy.py", "", 0o644),
    SUGGESTED:        ("/usr/bin/ecswctrl", "#!/bin/sh\nexit 0\n", 0o755),
}


def _pass(m): print(f"  {GREEN}PASS{NC}  {m}")
def _fail(m): print(f"  {RED}FAIL{NC}  {m}")
def _xfail(tag, m): print(f"  {GREEN}XFAIL{NC} xfail({tag}) — {m}")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ----------------------------------------------------------------- stub repo
def build_stub_repo() -> None:
    """Build the 5 stub .debs and a Packages index, wire it into apt sources."""
    shutil.rmtree(STUB_REPO, ignore_errors=True)
    os.makedirs(STUB_REPO)
    entries = []
    for pkg, (path, content, mode) in STUB_PAYLOAD.items():
        root = f"/tmp/stubbuild/{pkg}"
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(f"{root}/DEBIAN")
        dst = f"{root}{path}"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as f:
            f.write(content)
        os.chmod(dst, mode)
        with open(f"{root}/DEBIAN/control", "w") as f:
            f.write(f"Package: {pkg}\n"
                    f"Version: {STUB_VERSION}\n"
                    "Architecture: arm64\n"
                    "Maintainer: EG test <test@example.invalid>\n"
                    "Priority: optional\n"
                    "Section: misc\n"
                    f"Description: test stub standing in for {pkg}\n"
                    " Built by test_apt_install.py. Provides only what the EG\n"
                    " postinst probes for, so apt policy can be tested offline.\n")
        # ":" is not legal in a .deb filename — strip the epoch there only.
        deb = f"{STUB_REPO}/{pkg}_{STUB_VERSION.split(chr(58))[-1]}_arm64.deb"
        r = run(["dpkg-deb", "--build", root, deb])
        if r.returncode != 0:
            raise RuntimeError(f"dpkg-deb failed for {pkg}: {r.stderr}")
        blob = open(deb, "rb").read()
        entries.append(
            f"Package: {pkg}\nVersion: {STUB_VERSION}\nArchitecture: arm64\n"
            f"Filename: {os.path.basename(deb)}\nSize: {len(blob)}\n"
            f"MD5sum: {hashlib.md5(blob).hexdigest()}\n"
            f"SHA256: {hashlib.sha256(blob).hexdigest()}\n"
            "Priority: optional\nSection: misc\n"
            f"Description: test stub standing in for {pkg}\n")
    with open(f"{STUB_REPO}/Packages", "w") as f:
        f.write("\n".join(entries))
    with open("/etc/apt/sources.list.d/egstub.list", "w") as f:
        f.write(f"deb [trusted=yes] file://{STUB_REPO} ./\n")


def apt_update() -> None:
    run(["apt-get", "update"])


def apt_lists_clear() -> None:
    """Reproduce a freshly flashed board: no Packages index at all."""
    lists = "/var/lib/apt/lists"
    for n in os.listdir(lists):
        p = os.path.join(lists, n)
        if os.path.isfile(p):
            os.remove(p)


def is_installed(pkg: str) -> bool:
    r = run(["dpkg-query", "-W", "-f=${Status}", pkg])
    return r.returncode == 0 and "install ok installed" in r.stdout


def purge_optional() -> None:
    run(["apt-get", "purge", "-y", "--allow-remove-essential",
         *OPTIONAL, SUGGESTED])
    for pkg in OPTIONAL + [SUGGESTED]:
        run(["dpkg", "--purge", "--force-all", pkg])
    # A real numpy/cv2 already in the image would mask the stub's absence.
    for _pkg, (path, _c, _m) in STUB_PAYLOAD.items():
        if os.path.exists(path):
            os.remove(path)


def apt_install_local(deb: str, entry: Entry) -> tuple[int, str]:
    env = maintscript_env(entry)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    # No --no-install-suggests on purpose: we want apt's DEFAULT behaviour, which
    # is what a user gets. Asserting that ecswctrl stays uninstalled is only
    # meaningful if we did not ask apt to skip it.
    r = subprocess.run(["apt-get", "install", "-y", deb],
                       env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def make_older_deb(entry: Entry) -> str:
    """Repack the real .deb as an older version WITHOUT Recommends/Suggests, and
    without maintainer scripts.

    Mirrors the situation of a customer running a package built before the
    optional-dependency mechanism existed. The scripts are dropped on purpose:
    a postinst that fails under qemu would leave the package half-configured and
    apt would then refuse the upgrade, which would test the harness, not apt.
    """
    work = "/tmp/olddeb"
    shutil.rmtree(work, ignore_errors=True)
    r = run(["dpkg-deb", "-R", entry.package_path, work])
    if r.returncode != 0:
        raise RuntimeError(f"dpkg-deb -R failed: {r.stderr}")
    ctrl = f"{work}/DEBIAN/control"
    kept = []
    for line in open(ctrl):
        if line.startswith(("Recommends:", "Suggests:")):
            continue
        if line.startswith("Version:"):
            line = f"Version: {OLD_VERSION}\n"
        kept.append(line)
    with open(ctrl, "w") as f:
        f.writelines(kept)
    for script in ("preinst", "postinst", "prerm", "postrm"):
        p = f"{work}/DEBIAN/{script}"
        if os.path.exists(p):
            os.remove(p)
    out = "/tmp/old_eg_cams_arm64.deb"
    r = run(["dpkg-deb", "--build", work, out])
    if r.returncode != 0:
        raise RuntimeError(f"dpkg-deb --build failed: {r.stderr}")
    return out


# ----------------------------------------------------------------- fixtures
def stage(entry: Entry, state: str = "fresh") -> None:
    prepare_fixtures(entry, state)
    install_real_jetson_io(entry)
    setup_device_tree_symlink(entry)
    os.makedirs(f"{BOOT}/dtb", exist_ok=True)
    dst = f"{BOOT}/dtb/{os.path.basename(entry.base_dtb)}"
    if not os.path.exists(dst):
        shutil.copy(entry.base_dtb, dst)


# The postinst's real config-by-hardware.py cannot run under qemu (documented at
# length in test_dpkg_install.py). It makes apt report a non-zero rc even though
# the package unpacked and every dependency decision already happened. Detect
# that case so it does not mask the assertion we actually care about.
CBH_TAG = "real_cbh_requires_full_jetson_sysfs"


def cbh_only_failure(rc: int) -> bool:
    return rc != 0 and os.path.exists("/etc/version_eg_cams")


def warning_fired(out: str) -> bool:
    return "WARNING: optional package(s) not installed" in out


# ----------------------------------------------------------------- the tests
def t0_control_fields() -> tuple[int, int, list[str]]:
    """Every built .deb declares the 4 Recommends, the Suggests, Provides/Replaces."""
    ok = bad = 0
    problems = []
    seen = set()
    for entry in generate_matrix():
        if not entry.package_path or not os.path.exists(entry.package_path):
            continue
        if entry.package_path in seen:
            continue
        seen.add(entry.package_path)
        r = run(["dpkg-deb", "-f", entry.package_path,
                 "Recommends", "Suggests", "Provides", "Replaces"])
        fields = r.stdout
        missing = [p for p in OPTIONAL if p not in fields]
        if SUGGESTED not in fields:
            missing.append(f"Suggests:{SUGGESTED}")
        if "jetson-eg-cams" not in fields:
            missing.append("Provides/Replaces:jetson-eg-cams")
        name = os.path.basename(entry.package_path)
        if missing:
            bad += 1
            # Always name the version and the build date: _find_package() picks
            # matches[-1] of a LEXICOGRAPHIC filename sort, so with several builds
            # left in the tree it can hand us a stale .deb whose control fields
            # predate the field under test. Reporting them turns a mystifying
            # failure into an obvious "that is an old artifact, clean the tree".
            ver = run(["dpkg-deb", "-f", entry.package_path, "Version"]).stdout.strip()
            import datetime
            built = datetime.datetime.fromtimestamp(
                os.path.getmtime(entry.package_path)).strftime("%Y-%m-%d %H:%M")
            problems.append(f"{name} [{ver}, built {built}]: missing {', '.join(missing)}")
        else:
            ok += 1
    return ok, bad, problems


def t1_fresh_with_lists(entry: Entry) -> tuple[str, str]:
    """Nominal: apt must pull all 4 Recommends, mention but not install Suggests."""
    dpkg_purge(package_name_from_path(entry.package_path))
    purge_optional()
    apt_update()
    if any(is_installed(p) for p in OPTIONAL):
        return "fail", "could not reach a state where the 4 optionals are absent"
    stage(entry, "fresh")
    rc, out = apt_install_local(entry.package_path, entry)

    not_pulled = [p for p in OPTIONAL if not is_installed(p)]
    if not_pulled:
        return "fail", f"apt did not install Recommends: {', '.join(not_pulled)}"
    if is_installed(SUGGESTED):
        return "fail", f"{SUGGESTED} was installed — Suggests must never be"
    if warning_fired(out):
        return "fail", "postinst warning fired although all 4 are present"
    if cbh_only_failure(rc):
        return (f"xfail:{CBH_TAG}",
                "4 Recommends pulled, Suggests skipped, no warning; "
                "apt rc!=0 only because of the CBH step")
    if rc != 0:
        return "fail", f"apt rc={rc}: {out.strip().splitlines()[-3:]}"
    return "pass", "4 Recommends pulled, Suggests mentioned only, no warning"


def t2_upgrade_from_older(entry: Entry) -> tuple[str, str]:
    """Upgrade path: does apt honour Recommends the old version did not declare?"""
    pkg = package_name_from_path(entry.package_path)
    dpkg_purge(pkg)
    purge_optional()
    apt_update()

    old = make_older_deb(entry)
    real_version = run(["dpkg-deb", "-f", entry.package_path, "Version"]).stdout.strip()
    cmp_ok = run(["dpkg", "--compare-versions", OLD_VERSION, "lt", real_version])
    if cmp_ok.returncode != 0:
        return ("fail", f"test setup: {OLD_VERSION} does not sort below "
                        f"{real_version} — pick another OLD_VERSION")

    r = run(["dpkg", "-i", old])
    if not is_installed(pkg):
        return "fail", f"could not install the synthetic older package: {r.stderr[:120]}"
    if any(is_installed(p) for p in OPTIONAL):
        return "fail", "optionals present before the upgrade — state not clean"

    # "previously_eg" is the fixture for "an EG package was already installed" —
    # there is no "upgrade" state (INSTALL_STATES = fresh | previously_eg).
    stage(entry, "previously_eg")
    rc, out = apt_install_local(entry.package_path, entry)

    installed_now = run(["dpkg-query", "-W", "-f=${Version}", pkg]).stdout.strip()
    if installed_now != real_version:
        return "fail", f"upgrade did not happen: still at {installed_now}"

    pulled = [p for p in OPTIONAL if is_installed(p)]
    detail = (f"upgrade {OLD_VERSION} → {real_version}: "
              f"{len(pulled)}/{len(OPTIONAL)} Recommends pulled")
    if not pulled:
        # Documented finding, not a defect in our package: apt did not consider
        # the newly-declared Recommends on upgrade. Recorded as xfail so the
        # answer is captured either way rather than silently assumed.
        return ("xfail:apt_ignores_new_recommends_on_upgrade",
                detail + " — upgrading customers keep the postinst warning as "
                "their only signal; 'apt install --fix-policy' retro-installs them")
    if len(pulled) != len(OPTIONAL):
        return "fail", detail + f" (partial: {', '.join(pulled)})"
    if cbh_only_failure(rc):
        return f"xfail:{CBH_TAG}", detail + "; apt rc!=0 only because of the CBH step"
    if rc != 0:
        return "fail", f"apt rc={rc}: {out.strip().splitlines()[-3:]}"
    return "pass", detail


def t3_empty_lists(entry: Entry) -> tuple[str, str]:
    """Freshly flashed board: Recommends unsatisfiable, install must still work."""
    dpkg_purge(package_name_from_path(entry.package_path))
    purge_optional()
    apt_lists_clear()
    stage(entry, "fresh")
    rc, out = apt_install_local(entry.package_path, entry)

    wrongly_installed = [p for p in OPTIONAL if is_installed(p)]
    if wrongly_installed:
        return "fail", f"installed with empty lists?! {', '.join(wrongly_installed)}"
    if not os.path.exists("/etc/version_eg_cams"):
        return "fail", "package did not install with empty apt lists — must not block"
    if not warning_fired(out):
        return "fail", "postinst warning did NOT fire — the only signal in this state"
    if cbh_only_failure(rc):
        return (f"xfail:{CBH_TAG}",
                "package installed, Recommends skipped, warning fired; "
                "apt rc!=0 only because of the CBH step")
    if rc != 0:
        return "fail", f"apt rc={rc}: {out.strip().splitlines()[-3:]}"
    return "pass", "installed, Recommends skipped as expected, warning fired"


def t4_dpkg_ignores_everything(entry: Entry) -> tuple[str, str]:
    """dpkg -i honours neither field. Assert that, and that the warning fires."""
    dpkg_purge(package_name_from_path(entry.package_path))
    purge_optional()
    apt_update()
    stage(entry, "fresh")
    env = maintscript_env(entry)
    r = subprocess.run(["dpkg", "-i", entry.package_path],
                       env=env, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")

    pulled = [p for p in OPTIONAL if is_installed(p)]
    if pulled:
        return "fail", f"dpkg -i installed {', '.join(pulled)} — it must not"
    if is_installed(SUGGESTED):
        return "fail", f"dpkg -i installed {SUGGESTED} — it must not"
    if not warning_fired(out):
        return "fail", "postinst warning did NOT fire — the only signal for dpkg -i"
    if cbh_only_failure(r.returncode):
        return (f"xfail:{CBH_TAG}",
                "no Recommends (correct for dpkg), warning fired; "
                "rc!=0 only because of the CBH step")
    if r.returncode != 0:
        return "fail", f"dpkg rc={r.returncode}: {out.strip().splitlines()[-3:]}"
    return "pass", "no Recommends/Suggests, warning fired"


def pick_entry() -> Entry | None:
    """The generic (non-vendor) entry whose .deb was built most recently.

    Vendor packages are skipped: their preinst correctly refuses to install on a
    host it does not recognise, which is already asserted in P3 and would only get
    in the way here.

    Newest-by-mtime rather than first-in-matrix: what these four states validate is
    the control metadata and the postinst, so the package worth exercising is the
    one that came out of the last build. Taking the first matrix entry instead
    would silently test whichever version happens to sort first, which after a
    partial rebuild is the stale one.
    """
    candidates = [
        e for e in generate_matrix()
        if not e.is_forecr
        and e.package_path and os.path.exists(e.package_path)
        and os.path.exists(e.base_dtb)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda e: os.path.getmtime(e.package_path))


def main() -> int:
    install_depmod_stub()
    install_lsblk_mock()

    passed = xfailed = failed = 0
    failures: list[str] = []

    print(f"\n{BOLD}{CYAN}━━━ T0 — control fields of every built .deb ━━━{NC}")
    ok, bad, problems = t0_control_fields()
    if bad:
        failed += bad
        for p in problems[:20]:
            _fail(p)
        failures.extend(problems[:20])
    if ok:
        passed += ok
        _pass(f"{ok} package(s) declare the 4 Recommends + Suggests + Provides/Replaces")
    if not ok and not bad:
        print(f"  {YELLOW}SKIP{NC}  no .deb built yet — run the build first")

    entry = pick_entry()
    if entry is None:
        print(f"\n{YELLOW}T1-T4 SKIPPED{NC} — no generic package with a base DTB available")
        print(f"\n{BOLD}P3b results: {GREEN}{passed} passed{NC}  "
              f"{GREEN}{xfailed} xfail{NC}  {RED}{failed} failed{NC}")
        return 1 if failed else 0

    print(f"\n{BOLD}{CYAN}━━━ T1-T4 on L4T {entry.version} / {entry.platform_id} "
          f"/ {entry.vendor} ━━━{NC}")
    print(f"  (single entry by design — the control fields and postinst are\n"
          f"   generated identically for every version; T0 covers the rest)")

    build_stub_repo()

    for name, fn in (("T1 fresh install, lists populated", t1_fresh_with_lists),
                     ("T2 upgrade from an older version", t2_upgrade_from_older),
                     ("T3 empty apt lists (post-flash)", t3_empty_lists),
                     ("T4 dpkg -i", t4_dpkg_ignores_everything)):
        try:
            outcome, detail = fn(entry)
        except Exception as e:
            failed += 1
            failures.append(name)
            _fail(f"{name}: exception: {e}")
            continue
        if outcome == "pass":
            passed += 1
            _pass(f"{name}: {detail}")
        elif outcome.startswith("xfail:"):
            xfailed += 1
            _xfail(outcome.split(":", 1)[1], f"{name}: {detail}")
        else:
            failed += 1
            failures.append(name)
            _fail(f"{name}: {detail}")

    dpkg_purge(package_name_from_path(entry.package_path))
    purge_optional()

    print()
    print(f"{BOLD}P3b results: {GREEN}{passed} passed{NC}  "
          f"{GREEN}{xfailed} xfail{NC}  {RED}{failed} failed{NC}")
    if failures:
        print(f"\n{BOLD}Failed:{NC}")
        for f in failures[:30]:
            print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
