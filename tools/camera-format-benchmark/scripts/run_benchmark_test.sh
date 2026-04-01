#!/bin/bash
#
# Camera Format Benchmark Test Runner
# Runs a single benchmark test and captures tegrastats output
#
# Usage: ./run_benchmark_test.sh <test_name> <format> <gst_pipeline> <output_dir>
#

set -e

if [ $# -lt 4 ]; then
    echo "Usage: $0 <test_name> <format> <gst_pipeline> <output_dir>"
    echo ""
    echo "Examples:"
    echo "  $0 test1 YUYV \"gst-launch-1.0 v4l2src device=/dev/video0 ! autovideosink\" /tmp/results"
    echo "  $0 test3 Y16 \"gst-launch-1.0 v4l2src device=/dev/video0 ! nvvidconv ! 'video/x-raw,format=NV12' ! nvv4l2h264enc ! fakesink\" /tmp/results"
    exit 1
fi

TEST_NAME=$1
FORMAT=$2
GST_PIPELINE=$3
OUTPUT_DIR=$4
TEST_DURATION=8  # seconds

echo "=========================================="
echo "Running: $TEST_NAME for $FORMAT"
echo "=========================================="
echo "GStreamer pipeline:"
echo "  $GST_PIPELINE"
echo ""

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Output file
OUTPUT_FILE="$OUTPUT_DIR/${TEST_NAME}_${FORMAT}.txt"

echo "Capturing metrics to: $OUTPUT_FILE"
echo ""

# Kill any existing tegrastats
pkill -f tegrastats 2>/dev/null || true
sleep 1

# Start tegrastats in background with output redirection
tegrastats > "$OUTPUT_FILE" 2>&1 &
TEGRA_PID=$!

# Wait for tegrastats to start
sleep 1

# Launch GStreamer pipeline
echo "Starting GStreamer pipeline ($TEST_DURATION seconds)..."
timeout $TEST_DURATION bash -c "$GST_PIPELINE" >/dev/null 2>&1 || true

# Wait a bit more to capture final stats
sleep 1

# Kill tegrastats
echo "Stopping measurement..."
kill $TEGRA_PID 2>/dev/null || true
wait $TEGRA_PID 2>/dev/null || true

echo "Test completed: $OUTPUT_FILE"
echo ""

# Print summary
if [ -f "$OUTPUT_FILE" ]; then
    lines=$(wc -l < "$OUTPUT_FILE")
    echo "Captured $lines lines of telemetry data"
fi
