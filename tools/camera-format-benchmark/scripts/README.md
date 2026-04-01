# Camera Format Benchmark Scripts

This directory contains scripts to run the camera format benchmark suite on Jetson Orin NX.

## Quick Start

### ⚠️ IMPORTANT: Manual Format Selection

The benchmark requires **manual format configuration** on the camera. Change the format BEFORE running the scripts:

```bash
# Set camera to YUYV
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480

# Then run benchmark for that format
./run_format_benchmark.sh /tmp/benchmark_results YUYV
```

### Run full benchmark for a specific format:
```bash
# 1. Set camera format (manual)
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480

# 2. Run all 4 tests for that format
./run_format_benchmark.sh /tmp/benchmark_results YUYV

# Repeat for Y16 and AR24
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat="Y16 ",width=640,height=480
./run_format_benchmark.sh /tmp/benchmark_results Y16

v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=AR24,width=640,height=480
./run_format_benchmark.sh /tmp/benchmark_results AR24
```

### Analyze results:
```bash
python3 analyze_benchmark.py /tmp/benchmark_results
```

---

## Scripts Overview

### 1. `run_format_benchmark.sh` - Single Format Benchmark
Runs complete benchmark for a **single camera format** across all 4 test scenarios.
**Camera format must be configured manually before running this script.**

**Usage:**
```bash
./run_format_benchmark.sh <output_dir> <camera_format>
```

**Parameters:**
- `output_dir` (required): Where to save results
- `camera_format` (required): Format currently set on camera (YUYV, Y16, or AR24)

⚠️ **IMPORTANT:** Camera format must be set **MANUALLY** before running this script.

**What it does:**
1. Runs baseline test (system at rest, no pipelines)
2. Tests 4 scenarios for the specified format:
   - Test 1: Native display
   - Test 2: Format conversion + display
   - Test 3: Format conversion + H.264 encoding
   - Test 4: Direct H.264 encoding (YUYV only; will fail for Y16/AR24)
3. Captures tegrastats metrics for all tests

**Output:**
- `baseline.txt` - System metrics at rest
- `test1_<format>.txt`, `test2_<format>.txt`, etc. - Results for each test

**Duration:** ~2-3 minutes per format

**Example:**
```bash
# First, set camera format manually
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480

# Then run benchmark for that format
./run_format_benchmark.sh ~/results YUYV

# Results: ~/results/test1_YUYV.txt, ~/results/test2_YUYV.txt, etc.
```

---

### 2. `run_benchmark_test.sh` - Single Test Runner
Runs a single benchmark test with custom GStreamer pipeline.

**Usage:**
```bash
./run_benchmark_test.sh <test_name> <format> <gst_pipeline> <output_dir>
```

**Parameters:**
- `test_name`: Identifier for test (e.g., "test1", "custom_test")
- `format`: Camera format (YUYV, Y16, AR24, etc.)
- `gst_pipeline`: GStreamer command to execute
- `output_dir`: Directory to save results

**Example - Test custom pipeline:**
```bash
./run_benchmark_test.sh custom_display Y16 \
  "gst-launch-1.0 v4l2src device=/dev/video0 ! autovideosink" \
  /tmp/results

# Results saved to: /tmp/results/custom_display_Y16.txt
```

**Example - Test H.265 encoding (if available):**
```bash
./run_benchmark_test.sh h265_encoding AR24 \
  "gst-launch-1.0 v4l2src device=/dev/video0 ! nvv4l2h265enc bitrate=5000 ! fakesink" \
  /tmp/results
```

---

### 3. `analyze_benchmark.py` - Results Analysis
Parses tegrastats output and generates summary tables.

**Usage:**
```bash
python3 analyze_benchmark.py <results_directory>
```

**Parameters:**
- `results_directory`: Directory containing benchmark output files

**Output:**
- Text summary with metrics for each test
- Overhead calculation vs baseline
- Markdown table format for documentation

**Example:**
```bash
python3 analyze_benchmark.py /tmp/benchmark_results

# Output:
# ======================================================================
# BASELINE (System at Rest)
# ======================================================================
# CPU:  0-0% avg=0.0%
# GPU:  0-0% avg=0.0%
# PWR:  460-460mW avg=460mW
# TMP:  46.67-46.67°C avg=46.67°C
#
# test1_YUYV:
#   CPU:  0-33% (avg=9.5%)
#   GPU:  1-11% (avg=5.5%)
#   PWR:  614-767mW (avg=750mW)
#   TMP:  47.16-47.91°C (avg=47.53°C)
#   Overhead: CPU +9.5% PWR +290mW
# ...
```

---

## Workflow Example

### Complete benchmark run with analysis for all formats:

```bash
# 1. SSH into Jetson target
ssh jetson@192.168.38.116

# 2. Navigate to benchmark directory
cd /home/jetson/benchmark
chmod +x scripts/*.sh scripts/*.py

# 3. Run baseline test
./scripts/run_format_benchmark.sh ./results_yuyv YUYV

# 4. Switch camera format and test next format
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat="Y16 ",width=640,height=480
./scripts/run_format_benchmark.sh ./results_y16 Y16

# 5. Test third format
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=AR24,width=640,height=480
./scripts/run_format_benchmark.sh ./results_ar24 AR24

# 6. Analyze results (combine all results)
mkdir -p ./all_results
cp ./results_yuyv/*.txt ./all_results/
cp ./results_y16/*.txt ./all_results/
cp ./results_ar24/*.txt ./all_results/

python3 scripts/analyze_benchmark.py ./all_results

# 7. Copy results back to host
exit
scp -r jetson@192.168.38.116:/home/jetson/benchmark/all_results ~/benchmark_results
```

---

## Advanced Usage

### Custom Pipeline Testing

Test a camera format with custom GStreamer pipelines:

```bash
# 1. Set camera format manually
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat="Y16 ",width=640,height=480

# 2. Run custom test
./run_benchmark_test.sh custom_h264_y16 Y16 \
  "gst-launch-1.0 v4l2src device=/dev/video0 ! nvvidconv ! 'video/x-raw,format=NV12' ! nvv4l2h264enc ! fakesink" \
  ./custom_results
```

### Different Resolution Benchmarking

Test the same format at different resolutions:

```bash
# Format set to YUYV already
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480
./run_format_benchmark.sh ./results_640x480 YUYV

# Change resolution
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=1280,height=1024
./run_format_benchmark.sh ./results_1280x1024 YUYV
```

### Stress Test with Longer Duration

Edit `run_benchmark_test.sh` to increase duration:

```bash
# Modify the script
sed -i 's/TEST_DURATION=8/TEST_DURATION=60/' scripts/run_benchmark_test.sh

# Set format
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480

# Run 60-second stress test
./scripts/run_format_benchmark.sh ./stress_results YUYV
```

---

## Troubleshooting

### Script requires camera format argument:
```bash
# Error: "Camera format must be specified"
# Solution: Set format FIRST, then pass it as argument

v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480
./run_format_benchmark.sh /tmp/results YUYV
```

### Camera format not changed:
```bash
# Verify current format
v4l2-ctl -d /dev/video0 --get-fmt-video

# Some cameras may require a small delay after format change
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=AR24,width=640,height=480
sleep 2
./run_format_benchmark.sh /tmp/results AR24
```

### Script permission denied:
```bash
chmod +x scripts/run_format_benchmark.sh scripts/run_benchmark_test.sh scripts/analyze_benchmark.py
```

### Camera format not supported:
```bash
# List supported formats
v4l2-ctl -d /dev/video0 --list-formats-ext

# The benchmark requires: YUYV, Y16, or AR24
# If camera doesn't support these, modify pipelines in run_format_benchmark.sh
```

### GStreamer pipeline fails:
- Verify GStreamer elements are available: `gst-inspect-1.0 nvv4l2h264enc`
- Check camera is connected: `ls -la /dev/video*`
- Verify permissions: `sudo usermod -aG video $USER`

### tegrastats unavailable:
- Part of JetPack Tools
- Install: `sudo apt install nvidia-jetpack`
- Or run as root: `sudo ./run_format_benchmark.sh ...`

---

## Output File Format

Each test generates a file with tegrastats output. Example:
```
02-24-2026 11:29:16 RAM 796/15656MB (lfb 7x4MB) SWAP 0/7828MB (cached 0MB) CPU [2%@1344,1%@1344,1%@1344,4%@1344,off,off,off,off] GR3D_FREQ 0% cv0@44.718C cpu@47.406C ...
02-24-2026 11:29:17 RAM 809/15656MB (lfb 7x4MB) SWAP 0/7828MB (cached 0MB) CPU [13%@729,17%@729,13%@729,5%@729,off,off,off,off] GR3D_FREQ 11% cv0@44.906C cpu@47.156C ...
```

Parse with `analyze_benchmark.py` for human-readable summaries.

---

## Requirements

- **Target:** NVIDIA Jetson Orin NX (or similar with tegrastats)
- **Software:**
  - JetPack 6.2.1+
  - L4T 36.4+
  - GStreamer 1.0 with NVIDIA plugins
  - Python 3.6+
- **Camera:** MIPI CSI camera supporting YUYV, Y16, or AR24 formats

---

## Pre-Test Configuration

⚠️ **IMPORTANT:** Camera format must be set **MANUALLY** before running benchmark scripts.

### Set camera format:
```bash
# List available formats
v4l2-ctl -d /dev/video0 --list-formats-ext

# Set YUYV format (640×480)
v4l2-ctl -d /dev/video0 --set-fmt-video=pixelformat=YUYV,width=640,height=480

# Verify format was set correctly
v4l2-ctl -d /dev/video0 --get-fmt-video
```

### Verify GStreamer plugins are available:
```bash
# Check NVIDIA plugins
gst-inspect-1.0 nvv4l2h264enc    # H.264 encoder
gst-inspect-1.0 nvvidconv        # Color space converter
gst-inspect-1.0 nvv4l2camerasrc  # Camera source (optional)
```

### Verify tegrastats is accessible:
```bash
# Check if available
which tegrastats

# Or run as root if permission denied
sudo tegrastats --help
```

---

## Integration with Documentation

Results from these scripts are automatically compatible with the benchmark report:
- Markdown tables from `analyze_benchmark.py` can be copied into README.md
- Metrics update the performance tables
- Overhead data supports recommendations

See parent directory `README.md` for full benchmark report and interpretation.
