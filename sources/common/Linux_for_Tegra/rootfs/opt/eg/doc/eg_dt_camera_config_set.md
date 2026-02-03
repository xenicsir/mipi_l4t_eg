# eg_dt_camera_config_set.sh - Documentation

Configure Exosens camera device tree overlays on Jetson boards.

## Table of Contents

- [Overview](#overview)
- [Usage](#usage)
- [Supported Cameras](#supported-cameras)
- [Supported Boards](#supported-boards)
- [How It Works](#how-it-works)
- [Examples](#examples)
- [Workflow](#workflow)
- [Troubleshooting](#troubleshooting)

---

## Overview

`eg_dt_camera_config_set.sh` configures the Jetson device tree to enable specific Exosens cameras on designated ports. The script automatically detects the board type and applies the appropriate device tree overlays.

**Key Features**:
- ✅ **Simple Interface**: Specify port numbers and camera types as arguments
- ✅ **Automatic Board Detection**: Uses `detect_jetson_board.sh` for reliable identification
- ✅ **Multi-Camera Support**: Configure up to 8 cameras in a single command
- ✅ **Board-Specific Overlays**: Automatically selects correct overlays for your board
- ✅ **Validation**: Checks port numbers and camera types before applying

**Important**: Changes require a **reboot** to take effect!

---

## Usage

### Basic Syntax

```bash
eg_dt_camera_config_set.sh <port0> <camera_type0> [<port1> <camera_type1>] ...
```

### Arguments

Arguments are provided as **pairs** of port number and camera type:

- **port_number**: Integer from 0 to 7 (depending on board)
- **camera_type**: One of: `Dione`, `MicroCube640`, `SmartIR640`, `Crius1280`

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Configuration applied successfully (reboot required) |
| `1` | Error: Invalid arguments, unsupported board, or configuration failed |

---

## Supported Cameras

### Camera Types

| Camera | MIPI Lanes | I2C Address | Description |
|--------|-----------|-------------|-------------|
| **Dione** | N/A (custom interface) | 0x0E | Xenics Dione thermal camera |
| **MicroCube640** | 1 | 0x16 | Exosens EC camera (1 lane) |
| **SmartIR640** | 2 | 0x16 | Exosens EC camera (2 lanes) |
| **Crius1280** | 2 | 0x16 | Exosens EC camera (2 lanes) |

**Note**: `SmartIR640` and `Crius1280` use the same device tree configuration (2 MIPI lanes).

---

## Supported Boards

### Forecr/Exosens Boards

All DSBOARD, MILBOARD, and RAIBOARD series:
- DSBOARD-ORNXS (special overlay)
- DSBOARD-ORNX, DSBOARD-ORNXLAN
- DSBOARD-NX2, DSBOARD-XV, DSBOARD-XV2
- DSBOARD-AGX, DSBOARD-AGXMAX
- MILBOARD-ORNX, MILBOARD-AGX, MILBOARD-XV
- RAIBOARD-ORNX, RAIBOARD-AGX

### Nvidia Official Boards

- Jetson Orin Nano Developer Kit
- Jetson Orin NX Developer Kit
- Jetson AGX Orin Developer Kit
- Jetson Xavier NX Developer Kit
- Jetson AGX Xavier Developer Kit
- Jetson Nano Developer Kit

### Third-Party Boards

- Connect Tech: Photon, Rogue, Spacely, Orbitty
- Auvidea: X230D, JN30D, J120

---

## How It Works

### Configuration Process

```
1. Parse port/camera pairs from command line arguments
   └─ Validate: even number of arguments, valid ports (0-7), valid camera types

2. Detect board type
   ├─ Run detect_jetson_board.sh --short
   └─ Determine base device tree overlay name

3. Build overlay arguments
   ├─ For Dione: No additional overlay needed
   ├─ For MicroCube640: Add "CAM<port>:EC_1_lane" overlay
   └─ For SmartIR640/Crius1280: Add "CAM<port>:EC_2_lanes" overlay

4. Apply configuration
   ├─ Call /opt/eg/jetson-io/config-by-hardware.py
   ├─ Update /boot/extlinux/extlinux.conf with FDT overlays
   └─ Report success (reboot required)
```

### Device Tree Overlays

The script uses board-specific base overlays:

**DSBOARD-ORNXS**:
```
Base: "Exosens Cameras for DSBOARD-ORNXS"
Overlays:
  - CAM0:EC_1_lane (MicroCube640 on port 0)
  - CAM1:EC_2_lanes (SmartIR640/Crius1280 on port 1)
```

**Other boards**:
```
Base: "Exosens Cameras"
Overlays:
  - CAM0:EC_1_lane, CAM0:EC_2_lanes
  - CAM1:EC_1_lane, CAM1:EC_2_lanes
  - ... up to CAM7
```

### Configuration Storage

The configuration is stored in `/boot/extlinux/extlinux.conf`:

```
LABEL primary
      MENU LABEL primary kernel
      LINUX /boot/Image
      FDT /boot/dtb/kernel_tegra234-p3767-0003-p3768-0000-a0-dsboard-ornxs.dtb
      OVERLAYS /boot/dtb/Exosens_Cameras_for_DSBOARD-ORNXS.dtbo
      OVERLAYS /boot/dtb/CAM0_EC_1_lane.dtbo
      OVERLAYS /boot/dtb/CAM1_EC_2_lanes.dtbo
      INITRD /boot/initrd
      APPEND ${cbootargs} root=...
```

---

## Examples

### Single Camera Configuration

Configure a Dione camera on port 0:

```bash
$ sudo eg_dt_camera_config_set.sh 0 Dione
Forecr board detected: dsboard-ornxs
Port number : 0
Camera type : Dione

Configuration applied successfully.
Please reboot to activate changes:
  sudo reboot
```

### Two Cameras

Configure MicroCube640 on port 0 and SmartIR640 on port 1:

```bash
$ sudo eg_dt_camera_config_set.sh 0 MicroCube640 1 SmartIR640
Forecr board detected: dsboard-ornxs
Port number : 0
Camera type : MicroCube640
Port number : 1
Camera type : SmartIR640
overlay 2=Exosens Cameras for DSBOARD-ORNXS. CAM0:EC_1_lane
overlay 2=Exosens Cameras for DSBOARD-ORNXS. CAM1:EC_2_lanes

Configuration applied successfully.
Please reboot to activate changes.
```

### Four Cameras (AGX Orin)

```bash
$ sudo eg_dt_camera_config_set.sh 0 Dione 1 MicroCube640 2 SmartIR640 3 Crius1280
Nvidia official board
Port number : 0
Camera type : Dione
Port number : 1
Camera type : MicroCube640
Port number : 2
Camera type : SmartIR640
Port number : 3
Camera type : Crius1280
overlay 2=Exosens Cameras. CAM1:EC_1_lane
overlay 2=Exosens Cameras. CAM2:EC_2_lanes
overlay 2=Exosens Cameras. CAM3:EC_2_lanes

Configuration applied successfully.
Please reboot to activate changes.
```

### Automated Configuration Script

```bash
#!/bin/bash
# configure_cameras.sh - Automated camera configuration

# Define camera setup
PORT0_CAM="Dione"
PORT1_CAM="MicroCube640"

echo "Configuring cameras..."
eg_dt_camera_config_set.sh 0 "$PORT0_CAM" 1 "$PORT1_CAM"

if [[ $? -eq 0 ]]; then
    echo ""
    echo "Configuration successful!"
    read -p "Reboot now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo reboot
    fi
else
    echo "Configuration failed!"
    exit 1
fi
```

### Configuration with Validation

```bash
#!/bin/bash
# configure_and_verify.sh

# Apply configuration
echo "Applying camera configuration..."
eg_dt_camera_config_set.sh 0 Dione 1 SmartIR640

if [[ $? -ne 0 ]]; then
    echo "ERROR: Configuration failed"
    exit 1
fi

echo ""
echo "Configuration applied. Rebooting..."
sleep 2
sudo reboot

# After reboot, run this to verify:
# eg_dt_camera_config_get.sh -v
```

---

## Workflow

### Complete Configuration Workflow

```bash
# 1. Check current board
$ detect_jetson_board.sh -v
=== Jetson Board Detection ===
Board Type: dsboard-ornxs
System on Module (SoM):
  Type: orin-nano
  Part: P3767-0003 (8GB)

# 2. Apply camera configuration
$ sudo eg_dt_camera_config_set.sh 0 Dione 1 MicroCube640
Forecr board detected: dsboard-ornxs
Port number : 0
Camera type : Dione
Port number : 1
Camera type : MicroCube640
overlay 2=Exosens Cameras for DSBOARD-ORNXS. CAM1:EC_1_lane

# 3. Reboot
$ sudo reboot

# 4. Verify configuration after reboot
$ eg_dt_camera_config_get.sh
=== Exosens Camera Configuration ===

Board: dsboard-ornxs (orin-nano, t234)

Detected cameras:
  Port 0: Dione
  Port 1: MicroCube640

Total: 2 camera(s)

# 5. Start using cameras
$ v4l2-ctl --list-devices
```

### Changing Configuration

To change camera configuration:

```bash
# Old configuration: 0=Dione, 1=MicroCube640
$ eg_dt_camera_config_get.sh --json
{
  "cameras": {
    "port_0": "Dione",
    "port_1": "MicroCube640"
  }
}

# Apply new configuration
$ sudo eg_dt_camera_config_set.sh 0 SmartIR640 1 Crius1280
...

# Reboot
$ sudo reboot

# Verify new configuration
$ eg_dt_camera_config_get.sh --json
{
  "cameras": {
    "port_0": "SmartIR640 or Crius1280",
    "port_1": "SmartIR640 or Crius1280"
  }
}
```

---

## Troubleshooting

### "Error. Arguments number must be a multiple of 2"

You must provide pairs of port number and camera type:

```bash
# ✗ Wrong: odd number of arguments
$ eg_dt_camera_config_set.sh 0 Dione 1
Error. Arguments number must be a multiple of 2 : pairs port_number camera_type

# ✓ Correct: pairs of port and camera
$ eg_dt_camera_config_set.sh 0 Dione 1 MicroCube640
```

### "Error : invalid port number"

Port numbers must be 0-7:

```bash
# ✗ Wrong: port 9 doesn't exist
$ eg_dt_camera_config_set.sh 9 Dione
Error : invalid port number 9

# ✓ Correct: valid port numbers
$ eg_dt_camera_config_set.sh 0 Dione
```

### "Unknown camera type"

Supported types: `Dione`, `MicroCube640`, `SmartIR640`, `Crius1280`

```bash
# ✗ Wrong: typo in camera name
$ eg_dt_camera_config_set.sh 0 microcube640
Unknown camera type microcube640. Dione, MicroCube640, SmartIR640 or Crius1280 are supported

# ✓ Correct: exact camera name
$ eg_dt_camera_config_set.sh 0 MicroCube640
```

### "detect_jetson_board.sh: command not found"

Install the board detection script:

```bash
$ sudo cp detect_jetson_board.sh /usr/bin/
$ sudo chmod +x /usr/bin/detect_jetson_board.sh
```

### Configuration Not Applied After Reboot

1. **Check extlinux.conf**:
   ```bash
   cat /boot/extlinux/extlinux.conf | grep OVERLAYS
   ```

   You should see overlay entries like:
   ```
   OVERLAYS /boot/dtb/Exosens_Cameras.dtbo
   OVERLAYS /boot/dtb/CAM0_EC_1_lane.dtbo
   ```

2. **Verify overlay files exist**:
   ```bash
   ls -la /boot/dtb/*.dtbo | grep -E "Exosens|CAM"
   ```

3. **Check for boot errors**:
   ```bash
   dmesg | grep -i "device tree"
   dmesg | grep -i overlay
   ```

4. **Re-apply configuration**:
   ```bash
   sudo eg_dt_camera_config_set.sh 0 Dione 1 MicroCube640
   sudo reboot
   ```

### Cameras Not Detected After Configuration

1. **Verify device tree was loaded**:
   ```bash
   eg_dt_camera_config_get.sh -v
   ```

2. **Check I2C devices**:
   ```bash
   sudo i2cdetect -y -r 0  # Check I2C bus 0
   sudo i2cdetect -y -r 1  # Check I2C bus 1
   ```

3. **Check device tree nodes**:
   ```bash
   find /proc/device-tree -name "xenics_dione*" -o -name "eg_ec*" 2>/dev/null
   ```

4. **Check camera device nodes**:
   ```bash
   ls -la /dev/video*
   v4l2-ctl --list-devices
   ```

### Permission Denied

The script requires `sudo` to modify boot configuration:

```bash
# ✗ Wrong: no sudo
$ eg_dt_camera_config_set.sh 0 Dione
[sudo] password for user:

# ✓ Correct: run with sudo
$ sudo eg_dt_camera_config_set.sh 0 Dione
```

---

## Advanced Usage

### Scripted Deployment

```bash
#!/bin/bash
# deploy_camera_config.sh - Deploy camera configuration to multiple Jetson boards

BOARDS=(
    "192.168.1.101:0,Dione,1,MicroCube640"
    "192.168.1.102:0,SmartIR640,1,Crius1280"
    "192.168.1.103:0,Dione"
)

for board_config in "${BOARDS[@]}"; do
    IFS=':' read -r ip cameras <<< "$board_config"

    echo "Configuring board at $ip..."

    # Convert comma-separated camera list to space-separated arguments
    camera_args="${cameras//,/ }"

    # Apply configuration remotely
    ssh jetson@$ip "sudo eg_dt_camera_config_set.sh $camera_args && sudo reboot"

    echo "Board $ip configured and rebooting..."
done

echo "All boards configured!"
```

### Testing Different Configurations

```bash
#!/bin/bash
# test_configurations.sh - Test different camera configurations

CONFIGS=(
    "0 Dione"
    "0 MicroCube640"
    "0 SmartIR640"
    "0 Dione 1 MicroCube640"
    "0 MicroCube640 1 SmartIR640"
)

for config in "${CONFIGS[@]}"; do
    echo "Testing configuration: $config"

    # Apply configuration
    sudo eg_dt_camera_config_set.sh $config

    echo "Please reboot and test cameras, then press Enter to try next configuration..."
    read
done
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1 | 2026-02-03 | Improved command argument handling (dynamic array expansion), added board detection with detect_jetson_board.sh |
| 1.0 | 2025-02-02 | Initial version |

---

## Support

For issues or feature requests:
- **Forecr Boards**: support@forecr.io
- **Script Issues**: Check `/opt/eg/doc/` for updates

---

## See Also

- `detect_jetson_board.sh` - Board detection utility
- `eg_dt_camera_config_get.sh` - Get current camera configuration
- `/opt/eg/jetson-io/` - Jetson device tree configuration tools
- `/boot/extlinux/extlinux.conf` - Boot configuration file

---

## License

Copyright © 2026 Exosens
Part of Forecr/Exosens Jetson BSP distribution.
