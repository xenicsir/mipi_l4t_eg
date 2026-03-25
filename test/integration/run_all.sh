#!/bin/bash
# Entry point — builds the Docker image (if needed) and runs Level 2 integration tests.
# Usage: bash test/integration/run_all.sh [--no-build]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="eg-camera-test"

echo "=== Checking DTSI structure ==="
python3 "$REPO_ROOT/tools/verify_dtsi_structure.py"

echo "=== Checking package contents ==="
python3 "$SCRIPT_DIR/check_packages.py"

if [[ "$1" != "--no-build" ]]; then
    echo "=== Building test container ==="
    docker build -t "$IMAGE" "$REPO_ROOT/test"
fi

echo "=== Running Level 2 integration tests ==="
docker run --rm \
    --privileged \
    -v "$REPO_ROOT:/repo:ro" \
    -v "$SCRIPT_DIR:/repo/test/integration" \
    "$IMAGE" \
    bash /repo/test/integration/run_inside_container.sh
