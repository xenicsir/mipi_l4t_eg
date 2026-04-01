# Adding a New Camera Type to eg_dt_camera_config_get.sh

This guide explains how to add support for a new camera type in the `eg_dt_camera_config_get.sh` script.

## Overview

The script uses a centralized camera database that makes it easy to add new camera types. All camera definitions are in the `CAMERA_DATABASE` array at the top of the script.

## Camera Database Format

Each camera is defined as a single line with 5 colon-separated fields:

```
CATEGORY:I2C_ADDR:DT_NODE_PATTERN:DISPLAY_NAME:MIPI_LANES
```

### Fields Explanation

| Field | Description | Example |
|-------|-------------|---------|
| `CATEGORY` | Internal category name for grouping similar cameras | `dione`, `ec_1lane`, `ec_2lanes` |
| `I2C_ADDR` | I2C address in hex (without 0x prefix) | `0e` (for 0x0E), `16` (for 0x16) |
| `DT_NODE_PATTERN` | Device tree node regex pattern<br>Use `([a-h])` for port letter capture | `xenics_dione_ir_([a-h])@0e`<br>`eg_ec_([a-h])@16` |
| `DISPLAY_NAME` | Human-readable name shown in output | `Dione`, `MicroCube640` |
| `MIPI_LANES` | Number of MIPI CSI lanes<br>Use `0` for non-MIPI cameras | `0` (Dione), `1` (MicroCube640), `2` (SmartIR640) |

## Current Camera Database

```bash
CAMERA_DATABASE=(
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "ilumos:30:ilumos_([a-h])@30:iLumos:4"
)
```

## Adding a New Camera Type

### Step 1: Gather Camera Information

You need to know:

1. **I2C Address**: Find it in the camera driver or hardware documentation
2. **Device Tree Node Name**: Check your device tree overlay file (`.dts`)
3. **MIPI Lane Count**: From camera specifications (0 for non-MIPI cameras)
4. **Display Name**: Choose a user-friendly name

### Step 2: Add Entry to Database

Edit `/usr/bin/eg_dt_camera_config_get.sh` and add your camera to the `CAMERA_DATABASE` array.

### Example 1: Adding a New Camera with Different I2C Address

Let's add a hypothetical "ThermalPro" camera at I2C address 0x20:

```bash
CAMERA_DATABASE=(
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "thermalpro:20:thermal_pro_([a-h])@20:ThermalPro:2"
)
```

### Example 2: Real-World Example - iLumos Camera

The iLumos camera was added with its own I2C address (0x30) and 4 MIPI lanes:

```bash
CAMERA_DATABASE=(
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "ilumos:30:ilumos_([a-h])@30:iLumos:4"
)
```

**Note**: Since iLumos uses a unique I2C address (0x30), no MIPI lane disambiguation is needed.

### Example 3: Adding a Variant of Existing Camera

Let's add an EC camera with 4 MIPI lanes:

```bash
CAMERA_DATABASE=(
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "ec_4lanes:16:eg_ec_([a-h])@16:HighResEC:4"
)
```

**Note**: This camera shares the same I2C address and device tree pattern as other EC cameras. The script will differentiate them by checking the `mode0/num_lanes` value in the device tree.

### Example 4: Camera with Different Port Naming

If your camera uses a different naming convention (e.g., `mycam_port_X@1a`):

```bash
CAMERA_DATABASE=(
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "mycam:1a:mycam_port_([a-h])@1a:MyCameraModel:2"
)
```

### Step 3: Test the Changes

```bash
# Test with verbose output to see detection details
eg_dt_camera_config_get.sh -v

# Test JSON output
eg_dt_camera_config_get.sh --json
```

### Step 4: Verify Detection

The verbose output should show:

```
[DEBUG] Scanning I2C address 0xXX...
[DEBUG] Camera found at: /sys/firmware/devicetree/...
[DEBUG]   -> Port letter: X (YourCameraName)
```

And the final output should list your camera:

```
Camera ports:
  Port 0: YourCameraName (connected)
```

## Device Tree Node Pattern Guidelines

### Pattern Requirements

1. **Must include `([a-h])` capture group** for port letter extraction
2. **Must end with `@XX`** where XX is the hex I2C address
3. **Must match the actual device tree node name** exactly (case-sensitive)

### Valid Patterns

```bash
# Single camera type per I2C address
"camera_model_([a-h])@address"

# With manufacturer prefix
"exosens_mycam_([a-h])@address"

# With underscores
"my_camera_sensor_([a-h])@address"
```

### Invalid Patterns

```bash
# ❌ Missing capture group
"camera_model_*@address"

# ❌ Wrong capture group
"camera_model_([0-9])@address"

# ❌ Missing @ symbol
"camera_model_([a-h])address"
```

## Troubleshooting

### Camera Not Detected

1. **Check device tree node exists**:
   ```bash
   find /proc/device-tree -name "*your_camera*"
   ```

2. **Verify I2C address**:
   ```bash
   ls /sys/bus/i2c/devices/*-00XX/  # Replace XX with your address
   ```

3. **Check node status**:
   ```bash
   cat /proc/device-tree/path/to/camera/status
   # Should output "okay"
   ```

4. **Test pattern matching**:
   ```bash
   node_name="your_camera_b@20"
   pattern="your_camera_([a-h])@20"
   if [[ "$node_name" =~ $pattern ]]; then
       echo "Pattern matches: ${BASH_REMATCH[1]}"
   fi
   ```

### Wrong Camera Type Detected

For cameras sharing the same I2C address (like EC cameras):

1. **Check MIPI lane count in device tree**:
   ```bash
   cat /proc/device-tree/path/to/camera/mode0/num_lanes
   ```

2. **Ensure database entry has correct MIPI_LANES value**

3. **Order matters**: The script checks database entries in order. Put more specific patterns before generic ones.

## Advanced: Multiple Cameras at Same Address

If you have multiple camera models at the same I2C address (like the EC family), the script will:

1. First check if the device tree pattern matches
2. Then check if `mode0/num_lanes` exists and matches the specified lane count
3. Return the first matching camera

Example for EC cameras:

```bash
# All use I2C address 0x16, differentiated by MIPI lanes
"ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
"ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
"ec_4lanes:16:eg_ec_([a-h])@16:HighResEC:4"
```

## Complete Example: Adding Support for New Camera Family

Let's add a complete new camera family called "VisionCam" with 3 variants:

```bash
CAMERA_DATABASE=(
    # Existing cameras
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube640:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "ilumos:30:ilumos_([a-h])@30:iLumos:4"

    # New VisionCam family
    # - All use I2C address 0x25
    # - Device tree nodes: visioncam_X@25
    # - Differentiated by MIPI lanes
    "vision_2lane:25:visioncam_([a-h])@25:VisionCam-2M:2"
    "vision_4lane:25:visioncam_([a-h])@25:VisionCam-4M:4"
    "vision_8lane:25:visioncam_([a-h])@25:VisionCam-8M:8"
)
```

With corresponding device tree nodes at:
- `/proc/device-tree/bus@0/cam_i2cmux/i2c@0/visioncam_b@25`
- `/proc/device-tree/bus@0/cam_i2cmux/i2c@1/visioncam_c@25`

## Summary

Adding a new camera type requires:

1. ✅ One line in the `CAMERA_DATABASE` array
2. ✅ Know the I2C address
3. ✅ Know the device tree node naming pattern
4. ✅ Know the MIPI lane count (if applicable)

No changes needed to:
- ❌ Detection logic
- ❌ Connection checking
- ❌ Output formatting

The script automatically handles:
- ✅ Scanning for the new camera's I2C address
- ✅ Matching device tree nodes
- ✅ Detecting physical connections
- ✅ Mapping to port numbers

---

**Last Updated**: 2026-02-03
**Script Version**: 2.0 (Data-driven architecture)
