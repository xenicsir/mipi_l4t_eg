#!/bin/bash
# Entry point — delegates to integration tests.
# Usage: bash test/run_all.sh [--no-build]
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/integration/run_all.sh" "$@"
