#!/bin/bash
# Phase 3 — real dpkg -i install inside an aarch64 Ubuntu container under qemu.
#
# Builds the arm64 test image once, then for every (version, platform_id, vendor)
# in the generated matrix, runs test/qemu_install/test_dpkg_install.py inside the
# container with the package+fixtures mounted.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="eg-camera-test-aarch64"

# Check that the kernel can run aarch64 binaries (binfmt_misc + qemu-aarch64-static)
if ! docker run --rm --platform=linux/arm64 arm64v8/ubuntu:22.04 /bin/true >/dev/null 2>&1; then
    echo ""
    echo "===================================================================="
    echo "⚠  Phase 3 SKIPPED — host cannot run aarch64 containers."
    echo "   Install qemu-user-static on the host and register binfmt_misc:"
    echo "     sudo apt install qemu-user-static binfmt-support"
    echo "     docker run --rm --privileged multiarch/qemu-user-static \\"
    echo "         --reset -p yes"
    echo "===================================================================="
    exit 0
fi

if [[ "$1" != "--no-build" ]]; then
    echo "=== Building aarch64 test container ==="
    docker build --platform=linux/arm64 -t "$IMAGE" "$SCRIPT_DIR"
fi

echo "=== Running Phase 3 dpkg -i integration tests (aarch64/qemu) ==="
docker run --rm \
    --platform=linux/arm64 \
    --privileged \
    -v "$REPO_ROOT:/repo:ro" \
    -v "$SCRIPT_DIR:/repo/test/qemu_install" \
    -v "$REPO_ROOT/test/mocks:/tmp/mocks:ro" \
    "$IMAGE" \
    bash -c '
        # Prepare runtime: writable /boot, /etc, /proc/device-tree mock, mocks on PATH
        mkdir -p /boot/extlinux /tmp/fake_proc_dt
        # Install mocks (copy to writable dir first — repo is :ro)
        mkdir -p /usr/local/egmocks
        cp -a /tmp/mocks/. /usr/local/egmocks/
        chmod +x /usr/local/egmocks/*
        mkdir -p /opt/eg/jetson-io
        cp /usr/local/egmocks/config-by-hardware.py /opt/eg/jetson-io/config-by-hardware.py
        # Replace /sys/firmware with a writable tmpfs so we can stage a fake
        # /sys/firmware/devicetree/base (the real jetson-io Linux/dt.py reads
        # from that path). Privileged container → mount works.
        mkdir -p /sys/firmware 2>/dev/null || true
        mount -t tmpfs tmpfs /sys/firmware 2>/dev/null || true
        # python → python3 alias (eg_dt_camera_config_set.sh invokes `python`)
        ln -sf /usr/bin/python3 /usr/local/bin/python
        # depmod stub (postinst runs it; unneeded under qemu)
        printf "#!/bin/sh\nexit 0\n" >/usr/local/bin/depmod
        chmod +x /usr/local/bin/depmod
        # Full PATH: /sbin + /usr/sbin for dpkg (ldconfig, start-stop-daemon).
        export PATH=/usr/local/egmocks:/usr/local/sbin:/usr/local/bin:/usr/sbin:/sbin:/usr/bin:/bin
        python3 /repo/test/qemu_install/test_dpkg_install.py
    '
