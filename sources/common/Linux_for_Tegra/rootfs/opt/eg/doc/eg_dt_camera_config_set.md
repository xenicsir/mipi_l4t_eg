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
- ✅ **Simple Interface**: Specify port/camera pairs as arguments (`0/Dione 1/SmartIR640`)
- ✅ **Automatic Board Detection**: Uses `detect_jetson_board.sh` for reliable identification
- ✅ **Automatic Port Count**: Detects number of camera ports from device tree (2, 4, 6...)
- ✅ **Default Configuration**: Without arguments, configures all detected ports with Dione
- ✅ **Board-Specific Overlays**: Automatically selects correct overlays for your board
- ✅ **Validation**: Checks port numbers against actual board capabilities and camera types before applying

**Important**: Changes require a **reboot** to take effect!

---

## Usage

### Basic Syntax

```bash
eg_dt_camera_config_set.sh [<port/camera_type>] ...
```

### Arguments

Each argument is a **port/camera pair** separated by a `/`:

- **port_number**: Integer from 0 to N-1, where N is the number of camera ports detected on the board (e.g., 0-1 on DSBOARD-ORNXS, 0-3 on DSBOARD-ORNX, 0-5 on DSBOARD-XV2)
- **camera_type**: One of: `Dione`, `MicroCube640`, `SmartIR640`, `Crius1280`, `iLumos`

Example: `0/Dione`, `1/MicroCube640`, `2/SmartIR640`

**Without arguments**, all detected ports are configured with Dione (default camera).

### Options

| Option | Description |
|--------|-------------|
| (no args) | Configure all detected ports with Dione |
| `-h`, `--help` | Show usage help |

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
| **iLumos** | 4 | 0x30 | Exosens iLumos camera |

**Note**: `SmartIR640` and `Crius1280` use the same device tree configuration (2 MIPI lanes). `iLumos` is also accepted as `ilumos` (case-insensitive).

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
1. Detect board and camera ports
   ├─ Run detect_jetson_board.sh --short (board type)
   ├─ Run detect_jetson_board.sh --camera-ports (number of ports from device tree)
   └─ Determine base device tree overlay name

2. Parse port/camera pairs from command line arguments
   ├─ If no arguments: generate default pairs (all ports with Dione)
   └─ Validate: format port/camera, port within 0..N-1, valid camera type

3. Build overlay arguments (from CAMERA_LANES database)
   ├─ For Dione: No additional overlay needed (empty lane config)
   ├─ For MicroCube640: Add "CAM<port>:EC_1_lane" overlay
   ├─ For SmartIR640/Crius1280: Add "CAM<port>:EC_2_lanes" overlay
   └─ For iLumos: Add "CAM<port>:iLumos" overlay

4. Apply configuration
   ├─ Call /opt/eg/jetson-io/config-by-hardware.py
   ├─ Update /boot/extlinux/extlinux.conf with FDT overlays
   └─ Report success (reboot required)
```

### Camera Port Detection

The number of camera ports is detected automatically from the device tree by `detect_jetson_board.sh --camera-ports`. The detection reads the `num-channels` property from the NVCSI controller node in `/proc/device-tree/`.

| Board | Camera Ports | Valid port range |
|-------|-------------|-----------------|
| DSBOARD-ORNXS | 2 | 0-1 |
| DSBOARD-ORNX | 4 | 0-3 |
| DSBOARD-XV2 | 6 | 0-5 |
| Orin Nano/NX DevKit | 2 | 0-1 |
| AGX Orin DevKit | 4 | 0-3 |

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
  - CAM0:EC_1_lane, CAM0:EC_2_lanes, CAM0:iLumos
  - CAM1:EC_1_lane, CAM1:EC_2_lanes, CAM1:iLumos
  - ... up to CAM<N-1> (depending on detected port count)
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

### Default Configuration (no arguments)

Configure all detected ports with Dione (default camera). The number of ports is
automatically detected from the device tree:

```bash
# On a DSBOARD-ORNXS (2 ports)
$ sudo eg_dt_camera_config_set.sh
Forecr board detected: dsboard-ornxs
Port number : 0
Camera type : Dione
Port number : 1
Camera type : Dione

Configuration applied successfully.
Please reboot to activate changes.
```

```bash
# On a DSBOARD-ORNX (4 ports)
$ sudo eg_dt_camera_config_set.sh
Forecr board detected: dsboard-ornx
Port number : 0
Camera type : Dione
Port number : 1
Camera type : Dione
Port number : 2
Camera type : Dione
Port number : 3
Camera type : Dione

Configuration applied successfully.
Please reboot to activate changes.
```

### Single Camera Configuration

Configure a Dione camera on port 0:

```bash
$ sudo eg_dt_camera_config_set.sh 0/Dione
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
$ sudo eg_dt_camera_config_set.sh 0/MicroCube640 1/SmartIR640
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
$ sudo eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640 2/SmartIR640 3/Crius1280
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

echo "Configuring cameras..."
eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640

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
eg_dt_camera_config_set.sh 0/Dione 1/SmartIR640

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
# 1. Check current board and camera ports
$ detect_jetson_board.sh -v
=== Jetson Board Detection ===
Board Type: dsboard-ornxs
System on Module (SoM):
  Type: orin-nano
  Part: P3767-0003 (8GB)
  SoC:  t234
Carrier Board:
  Vendor: forecr
  Type:   dsboard-ornxs
  Desc:   DSBOARD-ORNXS (Orin Nano/NX compact)
Camera:
  Ports: 2

# 2. Apply camera configuration
$ sudo eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640
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

# 5. Start using cameras
$ v4l2-ctl --list-devices
```

### Changing Configuration

To change camera configuration:

```bash
# Old configuration: 0=Dione, 1=MicroCube640
$ eg_dt_camera_config_get.sh --json
{
  "board": {"type": "dsboard-ornxs", "som": "orin-nano", "tegra": "t234"},
  "cameras": {
    "port_0": {"type": "Dione", "status": "connected", "model": "Dione 640", ...},
    "port_1": {"type": "MicroCube640", "status": "connected", "model": "MicroCube", ...}
  },
  "camera_count": 2
}

# Apply new configuration
$ sudo eg_dt_camera_config_set.sh 0/SmartIR640 1/Crius1280
...

# Reboot
$ sudo reboot

# Verify new configuration
$ eg_dt_camera_config_get.sh --json
{
  "board": {"type": "dsboard-ornxs", "som": "orin-nano", "tegra": "t234"},
  "cameras": {
    "port_0": {"type": "SmartIR640 or Crius1280", "status": "connected", "model": "SmartIR640", ...},
    "port_1": {"type": "SmartIR640 or Crius1280", "status": "connected", "model": "Crius1280", ...}
  },
  "camera_count": 2
}
```

---

## Troubleshooting

### "Error: invalid argument ... Expected format: port_number/camera_type"

Each argument must be a port/camera pair separated by `/`:

```bash
# ✗ Wrong: missing slash separator
$ eg_dt_camera_config_set.sh 0 Dione
Error: invalid argument '0'. Expected format: port_number/camera_type

# ✓ Correct: port/camera pairs
$ eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640
```

### "Error: invalid port number"

Port numbers must be within the range detected for your board:

```bash
# ✗ Wrong: port 2 doesn't exist on a 2-port board (DSBOARD-ORNXS)
$ eg_dt_camera_config_set.sh 2/Dione
Error: invalid port number '2' (from argument '2/Dione'). Must be 0-1.

# ✓ Correct: valid port numbers for this board
$ eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640
```

The valid port range is automatically detected from the device tree. Use
`detect_jetson_board.sh --camera-ports` to check how many ports your board has.

### "Error: unknown camera type"

Supported types: `Dione`, `MicroCube640`, `SmartIR640`, `Crius1280`, `iLumos`

```bash
# ✗ Wrong: typo in camera name
$ eg_dt_camera_config_set.sh 0/microcube640
Error: unknown camera type 'microcube640' (from argument '0/microcube640').
Supported cameras: Crius1280, Dione, MicroCube, MicroCube640, SmartIR640, iLumos

# ✓ Correct: exact camera name
$ eg_dt_camera_config_set.sh 0/MicroCube640
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
   sudo eg_dt_camera_config_set.sh 0/Dione 1/MicroCube640
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
   find /proc/device-tree -name "xenics_dione*" -o -name "eg_ec*" -o -name "ilumos*" 2>/dev/null
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
$ eg_dt_camera_config_set.sh 0/Dione
[sudo] password for user:

# ✓ Correct: run with sudo
$ sudo eg_dt_camera_config_set.sh 0/Dione
```

---

## Advanced Usage

### Scripted Deployment

```bash
#!/bin/bash
# deploy_camera_config.sh - Deploy camera configuration to multiple Jetson boards

BOARDS=(
    "192.168.1.101:0/Dione 1/MicroCube640"
    "192.168.1.102:0/SmartIR640 1/Crius1280"
    "192.168.1.103:0/Dione"
)

for board_config in "${BOARDS[@]}"; do
    IFS=':' read -r ip cameras <<< "$board_config"

    echo "Configuring board at $ip..."

    # Apply configuration remotely
    ssh jetson@$ip "sudo eg_dt_camera_config_set.sh $cameras && sudo reboot"

    echo "Board $ip configured and rebooting..."
done

echo "All boards configured!"
```

### Testing Different Configurations

```bash
#!/bin/bash
# test_configurations.sh - Test different camera configurations

CONFIGS=(
    "0/Dione"
    "0/MicroCube640"
    "0/SmartIR640"
    "0/Dione 1/MicroCube640"
    "0/MicroCube640 1/SmartIR640"
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
| 1.3 | 2026-02-11 | Automatic camera port count detection from device tree, dynamic port validation, default configuration (no args = all ports with Dione), factorized camera database (CAMERA_LANES) |
| 1.2 | 2026-02-11 | New argument format: `port/camera_type` pairs, usage help, improved error messages |
| 1.1 | 2026-02-03 | Improved command argument handling (dynamic array expansion), added board detection with detect_jetson_board.sh |
| 1.0 | 2025-02-02 | Initial version |

---

## Support

For issues or feature requests:
- **Forecr Boards**: support@forecr.io
- **Script Issues**: Check `/opt/eg/doc/` for updates

---

## See Also

- `detect_jetson_board.sh` - Board detection utility (use `--camera-ports` for port count, `-v` for details)
- `eg_dt_camera_config_get.sh` - Get current camera configuration
- `/opt/eg/jetson-io/` - Jetson device tree configuration tools
- `/boot/extlinux/extlinux.conf` - Boot configuration file

---

## License

Copyright © 2026 Exosens
Part of Forecr/Exosens Jetson BSP distribution.
