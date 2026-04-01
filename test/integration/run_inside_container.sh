#!/bin/bash
# Runs inside the Docker container.
# Sets up PATH with mocks, prepares /boot and /proc/device-tree stubs,
# then delegates to matrix.py which drives the full test matrix.
set -e

REPO_ROOT="/repo"
TEST_DIR="$REPO_ROOT/test"
INTEGRATION_DIR="$REPO_ROOT/test/integration"

echo "=== Setting up integration test environment ==="

# /boot: used directly (container runs as root, /boot is writable)
mkdir -p /boot /boot/extlinux /boot/dtbs

# /proc/device-tree: use a temp dir redirected via mock find/grep
export TEST_PROC_DT=/tmp/fake_proc_dt
mkdir -p "$TEST_PROC_DT"

# Install mock binaries (copy to writable /tmp first — /repo is mounted :ro)
mkdir -p /tmp/mocks
cp "$TEST_DIR/mocks/"* /tmp/mocks/
chmod +x /tmp/mocks/*
export PATH="/tmp/mocks:$PATH"
mkdir -p /opt/eg/jetson-io
cp /tmp/mocks/config-by-hardware.py /opt/eg/jetson-io/config-by-hardware.py

# python → python3 alias
ln -sf /usr/bin/python3 /usr/local/bin/python

echo "=== Running integration test matrix ==="
python3 "$INTEGRATION_DIR/matrix.py"
