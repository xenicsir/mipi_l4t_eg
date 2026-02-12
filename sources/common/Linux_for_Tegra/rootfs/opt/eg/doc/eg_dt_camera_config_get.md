# eg_dt_camera_config_get.sh - Documentation

Automatic Exosens camera configuration detection from device tree.

## Table of Contents

- [Overview](#overview)
- [Usage](#usage)
- [Output Modes](#output-modes)
- [Supported Cameras](#supported-cameras)
- [How It Works](#how-it-works)
- [Examples](#examples)
- [Integration](#integration)
- [Troubleshooting](#troubleshooting)

---

## Overview

`eg_dt_camera_config_get.sh` automatically detects which Exosens cameras are **configured** in the device tree and which are **actually connected** (physically present). It reports camera types, port assignments, and connection status.

**Key Features**:
- ✅ **Auto-Discovery**: Scans device tree to find all camera devices (no hardcoded paths)
- ✅ **Connection Detection**: Identifies which cameras are physically connected vs just configured
- ✅ **Generic**: Works on all Jetson boards (Nano, TX2, Xavier, Orin families)
- ✅ **Smart Detection**: Uses `detect_jetson_board.sh` for reliable board identification
- ✅ **Multiple Output Formats**: Human-readable, verbose, and JSON
- ✅ **No Manual Configuration**: Automatically adapts to different SoM and carrier boards

**Important Distinction**:
- **Configured**: Camera is defined in device tree overlays (boot configuration)
- **Connected**: Camera is physically present and detected by V4L2 subsystem

---

## Usage

### Basic Syntax

```bash
eg_dt_camera_config_get.sh [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| *(none)* | Human-readable output |
| `-v`, `--verbose` | Print detailed debug information |
| `--json` | Output in JSON format |
| `-h`, `--help` | Show help message |

### Exit Codes

| Code | Meaning |
|------| --------|
| `0` | Success |
| `1` | Error or unsupported board |

---

## Output Modes

### 1. Default Mode (Human-Readable)

Simple, clear output showing configured cameras and their connection status.
When a camera is connected, additional details are displayed: video device, I2C device,
model name, serial number, native resolution, and pixel format.

The connection status is color-coded in terminal: **green** for connected, **red** for not connected.

When the camera driver exposes a `model` sysfs attribute, the model name replaces the
device tree type name in the output (e.g., "MicroCube" instead of "SmartIR640 or Crius1280").

```bash
$ eg_dt_camera_config_get.sh
=== Exosens Camera Configuration ===

Board: nvidia-p3509 (xavier-nx, t194)

Camera ports:
  Port 0: MicroCube (connected)        # model from sysfs
    Video device: /dev/video0
    I2C device:   /dev/eg-ec-mipi-9-0016
    Serial:       21971
    Resolution:   640x480
    Pixel format: 'Y16 ' (16-bit Greyscale)
  Port 1: Dione 1280 (connected)       # model from sysfs
    Video device: /dev/video1
    I2C device:   /dev/dioneir-i2c-10-000e-5b
    Serial:       20823
    Resolution:   1280x1024
    Pixel format: 'AR24' (32-bit BGRA 8-8-8-8)

Total configured: 2 camera(s)
```

**Connection Status Indicators**:
- `(connected)` (green) - Camera is physically present and detected
- `(not connected)` (red) - Camera is configured in device tree but not physically connected

**Camera Details** (shown only for connected cameras):
- **Video device**: `/dev/videoN` V4L2 device path
- **I2C device**: `/dev/<driver>-<bus>-<addr>` character device for direct I2C communication
- **Model**: Camera model name read from driver sysfs (if available)
- **Serial**: Camera serial number read from driver sysfs (if available)
- **Resolution**: Native camera resolution from driver sysfs (preferred), fallback to V4L2 current format
- **Pixel format**: Native pixel format from driver sysfs (preferred), fallback to V4L2 current format

### 2. Verbose Mode

Includes debug information about device tree paths, sysfs and V4L2 detection:

```bash
$ eg_dt_camera_config_get.sh -v
Board Type: dsboard-ornxs
SoM Type: orin-nano
Tegra SoC: t234

[DEBUG] Scanning I2C address 0x0e...
[DEBUG] Found device: 9-000e (bus=9, driver=dioneir)
[DEBUG] Camera found at: /proc/device-tree/.../xenics_dione_ir_b@0e
[DEBUG]   -> Port letter: b (Dione, bus=9, driver=dioneir)
[DEBUG] Scanning I2C address 0x16...
[DEBUG] Found device: 10-0016 (bus=10, driver=eg_ec_mipi)
[DEBUG] Camera found at: /proc/device-tree/.../eg_ec_c@16
[DEBUG]   -> Port letter: c (MicroCube640, bus=10, driver=eg_ec_mipi)
[DEBUG] Port 0: video=/dev/video0 i2c_chardev=/dev/dioneir-i2c-9-000e-5b model=Dione 640 serial=20823 res=640x480 fmt='AR24' (32-bit BGRA 8-8-8-8)
[DEBUG] Port 0 (letter: b): Dione connected (exact match)
[DEBUG] Port 1: video=/dev/video1 i2c_chardev=/dev/eg-ec-mipi-10-0016 model=MicroCube serial=21971 res=640x480 fmt='Y16 ' (16-bit Greyscale)
[DEBUG] Port 1 (letter: c): MicroCube640 connected (compatible with MicroCube640)

=== Exosens Camera Configuration ===

Board: dsboard-ornxs (orin-nano, t234)

Camera ports:
  Port 0: Dione 640 (connected)
    Video device: /dev/video0
    I2C device:   /dev/dioneir-i2c-9-000e-5b
    Serial:       20823
    Resolution:   640x480
    Pixel format: 'AR24' (32-bit BGRA 8-8-8-8)
  Port 1: MicroCube (connected)
    Video device: /dev/video1
    I2C device:   /dev/eg-ec-mipi-10-0016
    Serial:       21971
    Resolution:   640x480
    Pixel format: 'Y16 ' (16-bit Greyscale)

Total configured: 2 camera(s)
```

### 3. JSON Mode

Machine-readable structured output with connection status and camera details:

```bash
$ eg_dt_camera_config_get.sh --json
{
  "board": {
    "type": "dsboard-ornxs",
    "som": "orin-nano",
    "tegra": "t234"
  },
  "cameras": {
    "port_0": {"type": "Dione", "status": "connected", "video_device": "/dev/video0", "i2c_device": "/dev/dioneir-i2c-9-000e-5b", "model": "Dione 640", "serial_number": "20823", "width/height": "640x480", "pixel_format": "'AR24' (32-bit BGRA 8-8-8-8)"},
    "port_1": {"type": "MicroCube640", "status": "not connected"}
  },
  "camera_count": 2
}
```

Connected cameras include additional fields: `video_device`, `i2c_device`, `model`, `serial_number`, `width/height`, and `pixel_format` (when available from driver sysfs or V4L2).

---

## Supported Cameras

### Camera Types Detected

| DT Type (configured) | MIPI Lanes | Detection Method | Sysfs Models |
|----------------------|-----------|-----------------|--------------|
| **Dione** | N/A | Presence of `xenics_dione_ir_*@0e` device with status "okay" | Dione 640, Dione 1280 |
| **MicroCube640** | 1 | `eg_ec_*@16` device with `num_lanes=1` | MicroCube |
| **SmartIR640 or Crius1280** | 2 | `eg_ec_*@16` device with `num_lanes=2` | SmartIR640, Crius640, Crius1280, Aion640 |

**Note:** The "DT Type" column shows the name from the device tree configuration. When a camera is connected, the driver reads the actual model from the camera hardware via sysfs, and the output displays the real model name instead (e.g., "MicroCube" instead of "MicroCube640").

### Device Tree Node Patterns

The script searches for these device patterns in `/proc/device-tree/`:

- **Dione cameras**: `xenics_dione_ir_[a-h]@0e`
- **EC cameras**: `eg_ec_[a-h]@16`

Port letters (a-h) are automatically mapped to port numbers (0-7).

---

## How It Works

### Detection Flow

```
1. Detect board type using detect_jetson_board.sh
   ├─ Get board type, SoM type, Tegra SoC
   └─ Verify board is supported

2. Detect physically connected cameras via sysfs
   ├─ Scan /sys/bus/i2c/devices/ for known I2C addresses (0x0e, 0x16)
   ├─ Check driver is bound (driver/ symlink exists)
   ├─ Follow of_node symlink to get device tree path
   └─ Extract port letter from device tree node name

3. Auto-discover configured cameras in device tree
   ├─ Search known I2C bus locations (cam_i2cmux, direct i2c@*)
   ├─ Find all xenics_dione_ir_*@0e devices
   ├─ Find all eg_ec_*@16 devices
   └─ Extract port letters (a, b, c, etc.)

4. For each camera port:
   ├─ Check Dione device status (okay/disabled)
   ├─ If no Dione or disabled, check EC device
   ├─ Determine camera type from num_lanes
   └─ Map port letter to port number (0-7)

5. For each connected camera, read details:
   ├─ Find /dev/videoN via /sys/class/video4linux/
   ├─ Find I2C character device in /dev/
   ├─ Read model, serial_number, resolution, pixel_format from driver sysfs
   └─ Fallback to v4l2-ctl for resolution/pixel_format if sysfs unavailable

6. Combine configuration + connection status
   ├─ Port X: ModelName (connected) + details
   └─ Port Y: CameraType (not connected)

7. Output results in requested format
```

### Device Tree Structure

Different Tegra SoCs have different I2C bus layouts:

**Tegra T210 (Nano, TX1)**:
```
/proc/device-tree/
└── bus@0/cam_i2cmux/
    ├── i2c@0/
    │   ├── xenics_dione_ir_a@0e
    │   └── eg_ec_a@16
    └── i2c@1/
        ├── xenics_dione_ir_e@0e
        └── eg_ec_e@16
```

**Tegra T194 (Xavier NX)**:
```
/proc/device-tree/
└── bus@0/cam_i2cmux/
    ├── i2c@0/
    │   ├── xenics_dione_ir_a@0e
    │   └── eg_ec_a@16
    └── i2c@1/
        ├── xenics_dione_ir_c@0e
        └── eg_ec_c@16
```

**Tegra T234 (Orin family)**:
```
/proc/device-tree/
└── bus@0/
    ├── i2c@31e0000/
    │   ├── xenics_dione_ir_a@0e
    │   └── eg_ec_a@16
    ├── i2c@c240000/
    │   ├── xenics_dione_ir_g@0e
    │   └── eg_ec_g@16
    └── cam_i2cmux/
        ├── i2c@0/
        │   ├── xenics_dione_ir_b@0e
        │   └── eg_ec_b@16
        └── i2c@1/
            ├── xenics_dione_ir_c@0e
            └── eg_ec_c@16
```

The script automatically handles all these variants by searching known I2C bus locations.

### Connection Detection

The script detects physically connected cameras using the **sysfs I2C subsystem**:

**Sysfs Detection**:
```bash
# The script scans /sys/bus/i2c/devices/ for known camera I2C addresses
$ ls /sys/bus/i2c/devices/9-000e/
driver/  model  serial_number  resolution  pixel_format  of_node  ...

$ cat /sys/bus/i2c/devices/9-000e/model
Dione 640
```

**Detection Logic**:
1. Scan `/sys/bus/i2c/devices/` for devices at known I2C addresses (0x0e for Dione, 0x16 for EngineCore)
2. Check if a driver is bound (`driver/` symlink exists)
3. Follow `of_node` symlink to match the device tree node and extract port letter
4. Read camera details from driver sysfs attributes:
   - `model` - Camera model name (e.g., "MicroCube", "Dione 1280")
   - `serial_number` - Camera serial number
   - `resolution` - Native resolution (e.g., "640x480", "1280x1024")
   - `pixel_format` - Native pixel format (e.g., "'AR24' (32-bit BGRA 8-8-8-8)")
5. Find corresponding `/dev/videoN` and `/dev/<driver>-*` devices
6. Fallback to `v4l2-ctl` for resolution/pixel format if sysfs attributes are not available

**Why sysfs over v4l2-ctl**:
- **Sysfs resolution** shows the **native camera resolution** (read from hardware registers)
- **v4l2-ctl resolution** shows the **currently selected V4L2 mode** (which may differ, e.g., sensor_mode=0 = 640x480 even on a 1280x1024 camera)

**Why This Matters**:
- **Configured but not connected**: Camera overlay is in device tree, but camera is not physically present or not detected
- **Connection issues**: If camera is connected but not detected, check:
  - Camera power supply
  - CSI cable connection
  - I2C communication (`i2cdetect -y -r <bus>`)
  - Kernel logs (`dmesg | grep camera`)

---

## Examples

### Basic Usage

```bash
# Quick check of camera configuration and connection status
$ eg_dt_camera_config_get.sh
=== Exosens Camera Configuration ===

Board: dsboard-ornxs (orin-nano, t234)

Camera ports:
  Port 0: Dione 640 (connected)          # model from sysfs
    Video device: /dev/video0
    I2C device:   /dev/dioneir-i2c-9-000e-5b
    Serial:       20823
    Resolution:   640x480
    Pixel format: 'AR24' (32-bit BGRA 8-8-8-8)
  Port 1: MicroCube640 (not connected)    # DT type (no camera connected)

Total configured: 2 camera(s)
```

### Verify Camera Setup After Configuration

```bash
#!/bin/bash
# After configuring cameras with eg_dt_camera_config_set.sh,
# verify the configuration was applied correctly and cameras are connected

echo "Configuring cameras..."
eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640

echo ""
echo "Verifying configuration..."
eg_dt_camera_config_get.sh

# Expected output:
#   Camera ports:
#     Port 0: Dione 640 (connected)
#       Video device: /dev/video0
#       ...
#     Port 1: MicroCube (connected)
#       Video device: /dev/video1
#       ...
```

### Conditional Logic Based on Camera Count

```bash
#!/bin/bash

# Get camera configuration as JSON
CAM_INFO=$(eg_dt_camera_config_get.sh --json)

# Extract camera count
CAM_COUNT=$(echo "$CAM_INFO" | grep -oP '"camera_count":\s*\K\d+')

echo "Detected $CAM_COUNT camera(s)"

if [[ $CAM_COUNT -eq 0 ]]; then
    echo "Error: No cameras configured!"
    echo "Please run: eg_dt_camera_config_set.sh <port> <type> ..."
    exit 1
elif [[ $CAM_COUNT -eq 1 ]]; then
    echo "Single camera configuration"
    # Single camera application settings
elif [[ $CAM_COUNT -ge 2 ]]; then
    echo "Multi-camera configuration"
    # Multi-camera application settings
fi
```

### Parse JSON Output with jq

```bash
#!/bin/bash

# Get JSON output
CAM_JSON=$(eg_dt_camera_config_get.sh --json)

# Extract specific fields
BOARD=$(echo "$CAM_JSON" | jq -r '.board.type')
SOM=$(echo "$CAM_JSON" | jq -r '.board.som')
CAM_COUNT=$(echo "$CAM_JSON" | jq -r '.camera_count')

echo "Board: $BOARD ($SOM)"
echo "Cameras: $CAM_COUNT"

# List all cameras with connection status and model
echo "$CAM_JSON" | jq -r '.cameras | to_entries[] | "\(.key): \(.value.type) (\(.value.status))\(if .value.model then " [" + .value.model + "]" else "" end)"'

# Example output:
# Board: dsboard-ornxs (orin-nano)
# Cameras: 2
# port_0: Dione (connected) [Dione 640]
# port_1: SmartIR640 or Crius1280 (not connected)
```

### Validate Camera Configuration and Connection

```bash
#!/bin/bash
# Validate that expected cameras are configured AND connected

EXPECTED_CAMERAS=2
EXPECTED_PORT0="Dione"
EXPECTED_PORT1="MicroCube640"

CAM_JSON=$(eg_dt_camera_config_get.sh --json)

CAM_COUNT=$(echo "$CAM_JSON" | jq -r '.camera_count')
PORT0_TYPE=$(echo "$CAM_JSON" | jq -r '.cameras.port_0.type // "None"')
PORT0_STATUS=$(echo "$CAM_JSON" | jq -r '.cameras.port_0.status // "unknown"')
PORT1_TYPE=$(echo "$CAM_JSON" | jq -r '.cameras.port_1.type // "None"')
PORT1_STATUS=$(echo "$CAM_JSON" | jq -r '.cameras.port_1.status // "unknown"')

if [[ $CAM_COUNT -ne $EXPECTED_CAMERAS ]]; then
    echo "ERROR: Expected $EXPECTED_CAMERAS cameras, found $CAM_COUNT"
    exit 1
fi

if [[ "$PORT0_TYPE" != "$EXPECTED_PORT0" ]]; then
    echo "ERROR: Port 0 should be $EXPECTED_PORT0, found $PORT0_TYPE"
    exit 1
fi

if [[ "$PORT0_STATUS" != "connected" ]]; then
    echo "WARNING: Port 0 camera not connected"
fi

if [[ "$PORT1_TYPE" != "$EXPECTED_PORT1" ]]; then
    echo "ERROR: Port 1 should be $EXPECTED_PORT1, found $PORT1_TYPE"
    exit 1
fi

if [[ "$PORT1_STATUS" != "connected" ]]; then
    echo "WARNING: Port 1 camera not connected"
fi

echo "✓ Camera configuration validated successfully"
echo "✓ Port 0: $PORT0_STATUS"
echo "✓ Port 1: $PORT1_STATUS"
```

### Check Only Connected Cameras

```bash
#!/bin/bash
# Count and list only physically connected cameras

CAM_JSON=$(eg_dt_camera_config_get.sh --json)

# Count connected cameras
CONNECTED=$(echo "$CAM_JSON" | jq '[.cameras[] | select(.status == "connected")] | length')

echo "Connected cameras: $CONNECTED"

# List connected cameras
echo "$CAM_JSON" | jq -r '.cameras | to_entries[] | select(.value.status == "connected") | "  \(.key): \(.value.type)"'

# Example output:
# Connected cameras: 1
#   port_0: Dione
```

---

## Integration

### Shell Scripts

```bash
#!/bin/bash
# Automatic camera application launcher

# Detect cameras
CAM_JSON=$(eg_dt_camera_config_get.sh --json)
CAM_COUNT=$(echo "$CAM_JSON" | jq -r '.camera_count')

if [[ $CAM_COUNT -eq 0 ]]; then
    echo "No cameras detected. Exiting."
    exit 1
fi

# Launch camera application with detected configuration
echo "Launching application with $CAM_COUNT camera(s)..."
./camera_app --num-cameras=$CAM_COUNT
```

### Python Integration

```python
#!/usr/bin/env python3
import subprocess
import json

def get_camera_config():
    """Get camera configuration from device tree"""
    try:
        result = subprocess.run(
            ['eg_dt_camera_config_get.sh', '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error getting camera config: {e}")
        return None

# Usage
config = get_camera_config()
if config:
    print(f"Board: {config['board']['type']}")
    print(f"Camera count: {config['camera_count']}")

    for port, cam_info in config['cameras'].items():
        port_num = port.split('_')[1]
        model = cam_info.get('model', cam_info['type'])
        status = cam_info['status']
        print(f"  Camera {port_num}: {model} ({status})")
```

### C++ Integration

```cpp
#include <iostream>
#include <cstdlib>
#include <fstream>
#include <nlohmann/json.hpp>  // JSON library

using json = nlohmann::json;

json getCameraConfig() {
    std::string cmd = "eg_dt_camera_config_get.sh --json";
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) {
        throw std::runtime_error("Failed to run command");
    }

    std::string result;
    char buffer[128];
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result += buffer;
    }
    pclose(pipe);

    return json::parse(result);
}

int main() {
    try {
        auto config = getCameraConfig();

        std::cout << "Board: " << config["board"]["type"] << std::endl;
        std::cout << "Cameras: " << config["camera_count"] << std::endl;

        for (auto& [port, info] : config["cameras"].items()) {
            std::string model = info.value("model", info["type"].get<std::string>());
            std::string status = info["status"];
            std::cout << "  " << port << ": " << model << " (" << status << ")" << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
```

### Systemd Service

```bash
#!/bin/bash
# /usr/local/bin/camera-service-start.sh

# Get camera configuration
CAM_CONFIG=$(eg_dt_camera_config_get.sh --json)
CAM_COUNT=$(echo "$CAM_CONFIG" | jq -r '.camera_count')

# Log configuration
logger "Camera service starting with $CAM_COUNT camera(s)"
logger "Camera config: $CAM_CONFIG"

# Set environment variables for application
export CAMERA_COUNT=$CAM_COUNT
export CAMERA_CONFIG="$CAM_CONFIG"

# Start camera application
exec /opt/exosens/camera_app
```

---

## Troubleshooting

### No Cameras Detected

If the script reports "No cameras detected":

1. **Check device tree is loaded**:
   ```bash
   ls -la /proc/device-tree/
   ```

2. **Search for camera devices manually**:
   ```bash
   find /proc/device-tree -name "xenics_dione*" -o -name "eg_ec*" 2>/dev/null
   ```

3. **Run in verbose mode**:
   ```bash
   eg_dt_camera_config_get.sh -v
   ```

4. **Verify camera configuration was applied**:
   ```bash
   # Check if device tree overlays are loaded
   ls /boot/*.dtb

   # Reboot if configuration was just changed
   sudo reboot
   ```

### Script Not Found

```bash
# Check if installed
which eg_dt_camera_config_get.sh

# Check permissions
ls -l /usr/bin/eg_dt_camera_config_get.sh

# Reinstall if needed
sudo cp eg_dt_camera_config_get.sh /usr/bin/
sudo chmod +x /usr/bin/eg_dt_camera_config_get.sh
```

### Camera Shows "not connected" But Is Physically Connected

If a camera is configured but shows "not connected" status:

1. **Check V4L2 devices**:
   ```bash
   v4l2-ctl --list-devices
   ls -la /dev/video*
   ```

   You should see entries like:
   ```
   vi-output, dioneir X-000e (platform:tegra-capture-vi:0):
       /dev/video0
   ```

2. **Check I2C communication**:
   ```bash
   # List I2C buses
   i2cdetect -l

   # Scan I2C bus (replace X with bus number)
   sudo i2cdetect -y -r X
   ```

   Dione cameras should appear at address 0x0e, EC cameras at 0x16.

3. **Check kernel logs**:
   ```bash
   dmesg | grep -i camera
   dmesg | grep -i v4l2
   dmesg | grep -i "dioneir\|eg_ec"
   ```

   Look for errors like:
   - "probe failed"
   - "i2c transfer failed"
   - "No such device"

4. **Verify CSI connections**:
   - Check physical CSI cable connection
   - Ensure camera is powered
   - Try a different CSI port

5. **Check media controller**:
   ```bash
   media-ctl -p -d 0
   ```

   This shows the media graph. Connected cameras should appear as entities.

### Camera Shows "connected" But Doesn't Work

If status is "connected" but camera doesn't produce images:

1. **Test camera capture**:
   ```bash
   v4l2-ctl --list-formats-ext -d /dev/video0
   v4l2-ctl --stream-mmap --stream-count=1 -d /dev/video0
   ```

2. **Check camera permissions**:
   ```bash
   ls -la /dev/video*
   # Should show: crw-rw----+ 1 root video

   # Add user to video group if needed
   sudo usermod -a -G video $USER
   ```

3. **Verify device tree overlay**:
   ```bash
   cat /boot/extlinux/extlinux.conf | grep OVERLAYS
   ```

### Board Detection Fails

If you see "Error: Failed to detect board type":

1. **Check detect_jetson_board.sh is installed**:
   ```bash
   which detect_jetson_board.sh
   detect_jetson_board.sh -v
   ```

2. **Install if missing**:
   ```bash
   sudo cp detect_jetson_board.sh /usr/bin/
   sudo chmod +x /usr/bin/detect_jetson_board.sh
   ```

### Incorrect Camera Types

If camera types are incorrect:

1. **Check num_lanes in device tree**:
   ```bash
   find /proc/device-tree -name "eg_ec*" -type d | while read dev; do
       echo "$dev:"
       cat "$dev/mode0/num_lanes" 2>/dev/null | od -A n -t u1
   done
   ```

2. **Verify device tree configuration**:
   ```bash
   # Check which overlay is loaded
   cat /boot/extlinux/extlinux.conf | grep FDT
   ```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.2 | 2026-02-12 | Read camera details from driver sysfs (model, serial, resolution, pixel format), color-coded connection status, display actual model name from sysfs instead of DT type name, sysfs-first resolution/pixel format with v4l2-ctl fallback, JSON output includes camera details |
| 2.1 | 2026-02-03 | Added connection detection: distinguishes configured vs physically connected cameras using V4L2 |
| 2.0 | 2026-02-03 | Complete rewrite: auto-discovery, generic board support, JSON output, uses detect_jetson_board.sh |
| 1.0 | 2025-02-02 | Initial version with hardcoded board types |

---

## Support

For issues or feature requests:
- **Forecr Boards**: support@forecr.io
- **Script Issues**: Check `/opt/eg/doc/` for updates

---

## See Also

- `detect_jetson_board.sh` - Board detection utility
- `eg_dt_camera_config_set.sh` - Configure camera device tree overlays
- `/opt/eg/jetson-io/` - Jetson device tree configuration tools

---

## License

Copyright © 2026 Exosens
Part of Forecr/Exosens Jetson BSP distribution.
