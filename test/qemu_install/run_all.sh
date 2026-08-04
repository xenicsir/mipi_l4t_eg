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
CONTAINER_NAME="eg-camera-test-aarch64-run"

# A Ctrl-C that has to be repeated (client not responding fast enough under
# qemu) can kill the `docker run` client without ever signalling the
# container to stop — `--rm` then never fires and the container (plus its
# qemu-translated dpkg/postinst processes) keeps running and competing for
# CPU with the next attempt, making it look hung too. Clear any such leftover
# before starting, and make sure this run's own container can't survive an
# interrupt either.
if docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "⚠  Removing leftover '$CONTAINER_NAME' container from a previous interrupted run..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi
trap 'docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true' EXIT INT TERM

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

# --no-build : reuse the existing image. --apt-only : skip P3 (dpkg -i, 74 tests
# under qemu) and run only P3b, the apt-path tests. Order-independent.
DO_BUILD=1
APT_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --no-build) DO_BUILD=0 ;;
        --apt-only) APT_ONLY=1 ;;
    esac
done

if [[ $DO_BUILD -eq 1 ]]; then
    echo "=== Building aarch64 test container ==="
    docker build --platform=linux/arm64 -t "$IMAGE" "$SCRIPT_DIR"
fi

if [[ $APT_ONLY -eq 1 ]]; then
    echo "=== Running Phase 3b only — apt install ./pkg.deb (aarch64/qemu) ==="
else
    echo "=== Running Phase 3 dpkg -i integration tests (aarch64/qemu) ==="
fi
docker run --rm \
    --name "$CONTAINER_NAME" \
    --platform=linux/arm64 \
    --privileged \
    -e APT_ONLY="$APT_ONLY" \
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
        _RC_DPKG=0
        if [ "${APT_ONLY:-0}" != "1" ]; then
            python3 /repo/test/qemu_install/test_dpkg_install.py
            _RC_DPKG=$?
        fi
        # P3b — the apt path. dpkg -i honours neither Recommends nor Suggests, so
        # the optional-dependency mechanism needs its own transactions. Runs after
        # P3 and purges what it installs, but it does mutate apt state (stub repo
        # in sources.list.d, package lists) — hence last, and in a throwaway
        # container either way.
        python3 /repo/test/qemu_install/test_apt_install.py
        _RC_APT=$?
        [ $_RC_DPKG -ne 0 ] && exit $_RC_DPKG
        exit $_RC_APT
    '
