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

Simple, clear output showing configured cameras and their connection status:

```bash
$ eg_dt_camera_config_get.sh
=== Exosens Camera Configuration ===

Board: dsboard-ornxs (orin-nano, t234)

Camera ports:
  Port 0: Dione (connected)
  Port 1: Dione (not connected)

Total configured: 2 camera(s)
```

**Connection Status Indicators**:
- `(connected)` - Camera is physically present and detected by V4L2
- `(not connected)` - Camera is configured in device tree but not physically connected

### 2. Verbose Mode

Includes debug information about device tree paths and V4L2 detection:

```bash
$ eg_dt_camera_config_get.sh -v
Board Type: dsboard-ornxs
SoM Type: orin-nano
Tegra SoC: t234

[DEBUG] Port 0 (letter: b): Dione
[DEBUG]   Dione: /proc/device-tree/cam_i2cmux/i2c@0/xenics_dione_ir_b@0e
[DEBUG]   EC: /proc/device-tree/cam_i2cmux/i2c@0/eg_ec_b@16
[DEBUG]   I2C path: /proc/device-tree/cam_i2cmux/i2c@0
[DEBUG] Port 1 (letter: c): Dione
[DEBUG]   Dione: /proc/device-tree/cam_i2cmux/i2c@1/xenics_dione_ir_c@0e
[DEBUG]   EC: /proc/device-tree/cam_i2cmux/i2c@1/eg_ec_c@16
[DEBUG]   I2C path: /proc/device-tree/cam_i2cmux/i2c@1
[DEBUG] Detected Dione camera: 9-000e

=== Exosens Camera Configuration ===

Board: dsboard-ornxs (orin-nano, t234)

Camera ports:
  Port 0: Dione (connected)
  Port 1: Dione (not connected)

Total configured: 2 camera(s)
```

### 3. JSON Mode

Machine-readable structured output with connection status:

```bash
$ eg_dt_camera_config_get.sh --json
{
  "board": {
    "type": "dsboard-ornxs",
    "som": "orin-nano",
    "tegra": "t234"
  },
  "cameras": {
    "port_0": {"type": "Dione", "status": "connected"},
    "port_1": {"type": "Dione", "status": "not connected"}
  },
  "camera_count": 2
}
```

---

## Supported Cameras

### Camera Types Detected

| Camera Type | MIPI Lanes | Detection Method |
|-------------|-----------|-----------------|
| **Dione** | N/A | Presence of `xenics_dione_ir_*@0e` device with status "okay" |
| **MicroCube640** | 1 | `eg_ec_*@16` device with `num_lanes=1` |
| **SmartIR640 or Crius1280** | 2 | `eg_ec_*@16` device with `num_lanes=2` |

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

2. Auto-discover configured cameras in device tree
   ├─ Search known I2C bus locations (cam_i2cmux, direct i2c@*)
   ├─ Find all xenics_dione_ir_*@0e devices
   ├─ Find all eg_ec_*@16 devices
   └─ Extract port letters (a, b, c, etc.)

3. For each camera port:
   ├─ Check Dione device status (okay/disabled)
   ├─ If no Dione or disabled, check EC device
   ├─ Determine camera type from num_lanes
   └─ Map port letter to port number (0-7)

4. Detect physically connected cameras
   ├─ Run v4l2-ctl --list-devices
   ├─ Parse vi-output entries (dioneir X-000e, eg_ec X-0016)
   ├─ Count /dev/video* devices
   └─ Match connected cameras to configured ports

5. Combine configuration + connection status
   ├─ Port X: CameraType (connected)
   └─ Port Y: CameraType (not connected)

6. Output results in requested format
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

The script detects physically connected cameras using the V4L2 subsystem:

**V4L2 Detection**:
```bash
$ v4l2-ctl --list-devices
NVIDIA Tegra Video Input Device (platform:tegra-camrtc-ca):
	/dev/media0

vi-output, dioneir 9-000e (platform:tegra-capture-vi:0):
	/dev/video0
```

**Detection Logic**:
1. Parse `v4l2-ctl --list-devices` output
2. Look for camera entries: `vi-output, dioneir <bus>-<address>` or `vi-output, eg_ec <bus>-<address>`
3. Count number of `/dev/video*` devices created
4. Match video device count to configured ports
5. First N configured ports are marked as "connected"

**Example**:
- 2 ports configured (Port 0: Dione, Port 1: Dione)
- 1 video device found (`/dev/video0`)
- Result: Port 0 = connected, Port 1 = not connected

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
  Port 0: Dione (connected)
  Port 1: MicroCube640 (not connected)

Total configured: 2 camera(s)
```

### Verify Camera Setup After Configuration

```bash
#!/bin/bash
# After configuring cameras with eg_dt_camera_config_set.sh,
# verify the configuration was applied correctly and cameras are connected

echo "Configuring cameras..."
eg_dt_camera_config_set.sh 0 Dione 1 MicroCube640

echo ""
echo "Verifying configuration..."
eg_dt_camera_config_get.sh

# Expected output:
#   Camera ports:
#     Port 0: Dione (connected)
#     Port 1: MicroCube640 (connected/not connected)
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

# List all cameras with connection status
echo "$CAM_JSON" | jq -r '.cameras | to_entries[] | "\(.key): \(.value.type) (\(.value.status))"'

# Example output:
# Board: dsboard-ornxs (orin-nano)
# Cameras: 2
# port_0: Dione (connected)
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

    for port, cam_type in config['cameras'].items():
        port_num = port.split('_')[1]
        print(f"  Camera {port_num}: {cam_type}")
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

        for (auto& [port, type] : config["cameras"].items()) {
            std::cout << "  " << port << ": " << type << std::endl;
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
