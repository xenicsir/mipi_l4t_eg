#!/bin/bash
#
# Camera Format Benchmark Suite
# Tests a single camera format across 4 test scenarios
# Requires manual camera format configuration before running
#
# Usage: ./run_format_benchmark.sh <output_dir> <camera_format>
#
# Examples:
#   ./run_format_benchmark.sh /tmp/benchmark_results YUYV
#   ./run_format_benchmark.sh /tmp/benchmark_results Y16
#   ./run_format_benchmark.sh /tmp/benchmark_results AR24
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${1:-.}"
CAMERA_FORMAT="${2:-}"  # REQUIRED: format currently set on camera

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Check if format was specified
if [ -z "$CAMERA_FORMAT" ]; then
    echo -e "${RED}Error: Camera format must be specified${NC}"
    echo ""
    echo "Usage: $0 <output_dir> <camera_format>"
    echo ""
    echo "Examples:"
    echo "  $0 /tmp/results YUYV"
    echo "  $0 /tmp/results Y16"
    echo "  $0 /tmp/results AR24"
    echo ""
    echo -e "${YELLOW}IMPORTANT: Set camera format MANUALLY before running this script:${NC}"
    echo "  v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480"
    exit 1
fi

echo "=========================================="
echo "Camera Format Benchmark Suite"
echo "=========================================="
echo "Output directory: $OUTPUT_DIR"
echo -e "${BLUE}Camera Format: $CAMERA_FORMAT (must be already configured)${NC}"
echo ""

# Verify script exists
if [ ! -f "$SCRIPT_DIR/run_benchmark_test.sh" ]; then
    echo -e "${RED}Error: run_benchmark_test.sh not found in $SCRIPT_DIR${NC}"
    exit 1
fi

chmod +x "$SCRIPT_DIR/run_benchmark_test.sh"

# Define tests
declare -A TESTS=(
    ["test1"]="Test 1: Native Display"
    ["test2"]="Test 2: Conversion + Display"
    ["test3"]="Test 3: Conversion + H.264"
    ["test4"]="Test 4: Direct H.264"
)

# GStreamer pipelines for each test (independent of format)
declare -A PIPELINES=(
    # Test 1: Native display
    ["test1"]="gst-launch-1.0 v4l2src device=/dev/video0 ! autovideosink"

    # Test 2: Conversion + display
    ["test2"]="gst-launch-1.0 v4l2src device=/dev/video0 ! nvvidconv ! autovideosink"

    # Test 3: Conversion + H.264
    ["test3"]="gst-launch-1.0 v4l2src device=/dev/video0 ! nvvidconv ! nvv4l2h264enc bitrate=5000 ! fakesink"

    # Test 4: Direct H.264 (YUYV only; will fail for Y16/AR24)
    ["test4"]="gst-launch-1.0 v4l2src device=/dev/video0 ! nvv4l2h264enc bitrate=5000 ! fakesink"
)

run_test() {
    local test_id=$1
    local format=$2

    echo -e "${YELLOW}${TESTS[$test_id]} - $format${NC}"

    # Get pipeline (format-independent)
    local pipeline="${PIPELINES[$test_id]}"

    if [ -z "$pipeline" ]; then
        echo -e "${RED}  No pipeline defined for $test_id${NC}"
        return 1
    fi

    # Run test
    "$SCRIPT_DIR/run_benchmark_test.sh" "$test_id" "$format" "$pipeline" "$OUTPUT_DIR"

    sleep 2
}

# Run baseline test first
echo ""
echo -e "${GREEN}=== BASELINE TEST ===${NC}"
echo "Measuring system at rest (no pipelines)..."

# Kill any pipelines
pkill -f gst-launch 2>/dev/null || true
sleep 3

mkdir -p "$OUTPUT_DIR"
output_file="$OUTPUT_DIR/baseline.txt"

pkill -f tegrastats 2>/dev/null || true
sleep 1

echo "Capturing baseline metrics..."
tegrastats > "$output_file" 2>&1 &
TEGRA_PID=$!

sleep 1
sleep 10

kill $TEGRA_PID 2>/dev/null || true
wait $TEGRA_PID 2>/dev/null || true

echo "Baseline test completed: $output_file"
sleep 2

# Run all tests for the specified format
echo ""
echo -e "${GREEN}=== RUNNING BENCHMARK TESTS FOR FORMAT: $CAMERA_FORMAT ===${NC}"

test_count=0
passed_count=0

for test_id in "${!TESTS[@]}"; do
    echo ""
    echo -e "${YELLOW}${TESTS[$test_id]}${NC}"
    echo "=========================================="

    test_count=$((test_count + 1))

    if run_test "$test_id" "$CAMERA_FORMAT"; then
        passed_count=$((passed_count + 1))
        echo -e "${GREEN}✓ Passed${NC}"
    else
        echo -e "${RED}✗ Failed (may be expected for unsupported formats in Test 4)${NC}"
    fi

    echo ""
done

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}BENCHMARK COMPLETE${NC}"
echo "=========================================="
echo "Tests passed: $passed_count / $test_count"
echo "Results saved to: $OUTPUT_DIR"
echo ""
echo "Files generated:"
ls -lh "$OUTPUT_DIR"/*.txt 2>/dev/null || echo "  (no files)"
echo ""
echo "To analyze results, use:"
echo "  python3 scripts/analyze_benchmark.py $OUTPUT_DIR"
