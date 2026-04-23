#!/bin/bash
# Phase 1+2 runner — builds the x86_64 Docker test image (if needed) and runs:
#   • Phase 1 — test/integration/matrix.py (script integration tests)
#   • Phase 2 — test/packaging/test_postinst.py (.deb preinst/postinst)
# inside the container.
#
# Invoked by test/run_all.sh after P0 coherence checks, or standalone for faster
# iteration. DTSI/package checks are run by the top-level script (not here).
#
# Usage: bash test/integration/run_all.sh [--no-build]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="eg-camera-test"

if [[ "$1" != "--no-build" ]]; then
    echo "=== Building test container ==="
    docker build -t "$IMAGE" "$REPO_ROOT/test"
fi

echo "=== Running Phase 1 + 2 integration tests ==="
docker run --rm \
    --privileged \
    -e RUN_PHASE \
    -v "$REPO_ROOT:/repo:ro" \
    -v "$SCRIPT_DIR:/repo/test/integration" \
    "$IMAGE" \
    bash /repo/test/integration/run_inside_container.sh
