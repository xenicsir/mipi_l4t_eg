#!/bin/bash
# Top-level test runner. Runs all 3 phases sequentially:
#
#   P0  Matrix coherence check (host)
#       Verifies eg_config.yaml ↔ hardware.yaml ↔ build outputs.
#       Output: test/config/test_matrix.py --check
#
#   P1  Script integration tests (Docker x86)
#       Runs eg_dt_camera_config_set.sh directly with mocked CBH, detect_jetson_board,
#       find, grep, sudo, against real DTBOs from the build tree, across all
#       (version, platform, camera, port, extlinux_state) combinations.
#       Output: test/integration/run_all.sh
#
#   P2  Package install via dpkg-deb -x + maintscripts (Docker x86)
#       For every built .deb, runs preinst/postinst in the same container. Validates
#       preinst version check, vendor detection, postinst default + upgrade paths.
#       Output: test/integration/run_inside_container.sh (chained after P1)
#
#   P3  Real dpkg -i inside aarch64 container (Docker arm64 via qemu)
#       Runs dpkg -i <pkg> natively under aarch64 emulation. Skipped on hosts
#       without qemu-user-static / binfmt_misc for aarch64.
#       Output: test/qemu_install/run_all.sh
#
# Usage:
#   bash test/run_all.sh               # all phases, rebuild containers
#   bash test/run_all.sh --no-build    # all phases, skip container rebuild
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  P0 — Matrix coherence (eg_config.yaml ↔ hardware.yaml ↔ .debs)"
echo "══════════════════════════════════════════════════════════════════════"
python3 "$SCRIPT_DIR/config/test_matrix.py" --check

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  DTSI structure verification"
echo "══════════════════════════════════════════════════════════════════════"
python3 "$REPO_ROOT/tools/verify_dtsi_structure.py"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  Package content verification (check_packages.py)"
echo "══════════════════════════════════════════════════════════════════════"
python3 "$SCRIPT_DIR/integration/check_packages.py"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  P1 + P2 — Script tests + package install (Docker x86_64)"
echo "══════════════════════════════════════════════════════════════════════"
bash "$SCRIPT_DIR/integration/run_all.sh" "$@"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  P3 — Real dpkg -i inside aarch64 container (Docker arm64 + qemu)"
echo "══════════════════════════════════════════════════════════════════════"
bash "$SCRIPT_DIR/qemu_install/run_all.sh" "$@"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  All phases passed."
echo "══════════════════════════════════════════════════════════════════════"
