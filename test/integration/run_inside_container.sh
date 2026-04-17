#!/bin/bash
# Runs INSIDE the x86_64 Docker container. Performs P1 (script matrix) then
# P2 (real .deb extract + preinst/postinst execution).
#
# /repo is mounted read-only; /tmp, /boot, /etc, /usr/bin are writable.
set -e

REPO_ROOT="/repo"
TEST_DIR="$REPO_ROOT/test"
INTEGRATION_DIR="$REPO_ROOT/test/integration"
PACKAGING_DIR="$REPO_ROOT/test/packaging"

echo "=== Setting up container environment ==="
mkdir -p /boot /boot/extlinux /boot/dtbs

# /proc/device-tree: Phase 1 mock find/grep redirect to TEST_PROC_DT, but
# Phase 2 maintscripts read /proc/device-tree/nvidia,dtsfilename via cat and
# `[[ -f ]]` which cannot be hijacked via PATH. Create a real path at
# /proc/device-tree that maps to our fake tree. The container runs
# --privileged, so either mkdir (x86 typically has /proc writable for missing
# entries) or a bind mount works.
export TEST_PROC_DT=/tmp/fake_proc_dt
mkdir -p "$TEST_PROC_DT"
if [[ ! -e /proc/device-tree ]]; then
    mkdir -p /proc/device-tree 2>/dev/null \
        || ln -s "$TEST_PROC_DT" /proc/device-tree 2>/dev/null \
        || true
fi
# Bind mount is the most transparent: reads/writes see the fake tree.
mount --bind "$TEST_PROC_DT" /proc/device-tree 2>/dev/null || true

# Install mocks onto writable /tmp and put them first in PATH
mkdir -p /tmp/mocks
cp "$TEST_DIR/mocks/"* /tmp/mocks/
chmod +x /tmp/mocks/*
export PATH="/tmp/mocks:$PATH"
mkdir -p /opt/eg/jetson-io
cp /tmp/mocks/config-by-hardware.py /opt/eg/jetson-io/config-by-hardware.py

# python → python3 alias (some scripts call `python`)
ln -sf /usr/bin/python3 /usr/local/bin/python

# depmod stub (postinst runs it; unneeded in container)
cat >/usr/local/bin/depmod <<'SH'
#!/bin/sh
exit 0
SH
chmod +x /usr/local/bin/depmod

# Disable set -e so we can capture both phase exit codes and run P2 even if P1 fails
set +e

p1_rc=0
p2_rc=0

# RUN_PHASE=1|2|all selects which sub-phase(s) to execute. Default: all.
# Useful for fast iteration after a fix affecting only one phase.
RUN_PHASE="${RUN_PHASE:-all}"

if [[ "$RUN_PHASE" == "all" || "$RUN_PHASE" == "1" ]]; then
    echo ""
    echo "=== P1 — Script integration matrix ==="
    python3 "$INTEGRATION_DIR/matrix.py"
    p1_rc=$?
fi

if [[ "$RUN_PHASE" == "all" || "$RUN_PHASE" == "2" ]]; then
    echo ""
    echo "=== P2 — .deb preinst/postinst execution ==="
    python3 "$PACKAGING_DIR/test_postinst.py"
    p2_rc=$?
fi

if [[ $p1_rc -ne 0 || $p2_rc -ne 0 ]]; then
    echo ""
    echo "P1=${p1_rc} P2=${p2_rc}"
    exit 1
fi
