# detect_jetson_board.sh - Documentation

Comprehensive Jetson board detection utility for identifying System on Module (SoM) and carrier boards.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Usage](#usage)
- [Output Modes](#output-modes)
- [Supported Boards](#supported-boards)
- [Examples](#examples)
- [Integration](#integration)
- [Technical Details](#technical-details)

---

## Overview

`detect_jetson_board.sh` is a bash script that automatically detects:
- **Jetson SoM (System on Module)**: Nano, TX1/TX2, Xavier, Orin families
- **Carrier boards**: Nvidia official, Forecr/Exosens, Connect Tech, Auvidea, Antmicro
- **Hardware details**: Part numbers, Tegra SoC version, memory configuration

The script analyzes device tree information from `/proc/device-tree/` to provide accurate board identification.

**Key Features**:
- ✅ **Reliable Detection**: Prioritizes device tree compatible strings for accurate part number identification
- ✅ **Handles Edge Cases**: Works correctly even when DTB filename is unavailable or model string is misleading
- ✅ **Multiple Output Formats**: Default (short name), verbose, and JSON for easy integration
- ✅ **Comprehensive Support**: 20+ SoM types and 40+ carrier boards

---

## Installation

The script is automatically installed in `/usr/bin/` on Exosens/Forecr Jetson systems.

**Manual installation:**
```bash
# Copy to system path
sudo cp detect_jetson_board.sh /usr/bin/
sudo chmod +x /usr/bin/detect_jetson_board.sh

# Or run from current directory
chmod +x detect_jetson_board.sh
./detect_jetson_board.sh
```

---

## Usage

### Basic Syntax

```bash
detect_jetson_board.sh [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| *(none)* | Print board type (short name) |
| `-v`, `--verbose` | Print detailed board information |
| `--json` | Output in JSON format |
| `--short` | Print short board name only (same as default) |
| `-h`, `--help` | Show help message |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Board detected successfully |
| `1` | Unable to detect board |

---

## Output Modes

### 1. Default Mode (Short Name)

Returns a simple board identifier:

```bash
$ detect_jetson_board.sh
dsboard-ornxs
```

### 2. Verbose Mode

Displays complete board information:

```bash
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

Device Tree:
  Model: NVIDIA Orin Nano Developer Kit - DSBOARD-ORNXS
  DTB:   tegra234-p3767-0000-p3768-0000-a0-dsboard-ornxs.dtb
  Compatible: nvidia,p3768-0000+p3767-0003 nvidia,p3767-0003 nvidia,tegra234

Forecr Indicators:
  ✓ /opt/eg (Forecr tools)
  ✓ dioneCtrl.py
```

**Note**: The `Compatible` line shows the device tree compatible strings, which are the most reliable source for identifying the exact SoM part number, especially when the DTB filename is not available.

### 3. JSON Mode

Machine-readable structured output:

```bash
$ detect_jetson_board.sh --json
{
  "board_type": "dsboard-ornxs",
  "vendor": "forecr",
  "som": {
    "type": "orin-nano",
    "part_number": "P3767-0003 (8GB)",
    "tegra": "t234"
  },
  "carrier": {
    "type": "dsboard-ornxs",
    "description": "DSBOARD-ORNXS (Orin Nano/NX compact)"
  },
  "model": "NVIDIA Orin Nano Developer Kit - DSBOARD-ORNXS",
  "dtb": "tegra234-p3767-0000-p3768-0000-a0-dsboard-ornxs.dtb"
}
```

---

## Supported Boards

### Jetson SoM (System on Module)

#### Orin Family (Tegra T234)
- **AGX Orin**: P3701-0000 (32GB), P3701-0004 (32GB), P3701-0005 (64GB), P3701-0008
- **Orin NX**: P3767-0000 (16GB), P3767-0001 (8GB)
- **Orin Nano**: P3767-0003 (8GB), P3767-0004 (4GB), P3767-0005 (8GB)

#### Xavier Family (Tegra T194)
- **AGX Xavier**: P2888-0001 (16GB), P2888-0004 (32GB), P2888-0005 (64GB), P2888-0008 (Industrial)
- **Xavier NX**: P3668-0000 (8GB, SD), P3668-0001 (8GB, eMMC), P3668-0003 (16GB)

#### TX Family (Tegra T186/T210)
- **TX2**: P3310 (8GB), P3489 (TX2i Industrial)
- **TX1**: P2180

#### Nano (Tegra T210)
- **Jetson Nano**: P3448-0000 (4GB, SD), P3448-0002 (4GB, eMMC), P3448-0003 (2GB)

### Carrier Boards

#### Forecr/Exosens Carrier Boards

**DSBOARD Series** (Industrial Grade):
- `dsboard-ornxs` - Compact carrier for Orin Nano/NX
- `dsboard-ornx` - Standard Orin Nano/NX carrier
- `dsboard-ornxlan` - Orin Nano/NX with enhanced networking
- `dsboard-nx2` - Xavier NX carrier
- `dsboard-xv` - AGX Xavier Industrial carrier
- `dsboard-xv2` - AGX Xavier/Orin carrier
- `dsboard-agx` - AGX Orin carrier
- `dsboard-agxmax` - AGX Orin high-performance variant
- `dsboard-thrmax` - Jetson Thor carrier

**MILBOARD Series** (Military/Defense Grade):
- `milboard-agx` - Military/Defense AGX Xavier/Orin
- `milboard-agxmax` - Military high-performance variant
- `milboard-ornx` - Military Orin Nano/NX
- `milboard-xv` - Military AGX Xavier

**RAIBOARD Series** (Railway Grade - EN50155):
- `raiboard-agx` - Railway-certified AGX Orin (IP67, EN50155)
- `raiboard-ornx` - Railway-certified Orin Nano/NX

#### Nvidia Official Carrier Boards

- `nvidia-p3768` - Orin Nano/NX Developer Kit
- `nvidia-p3509` - Xavier NX/Orin NX carrier
- `nvidia-p3737` - AGX Orin Developer Kit
- `nvidia-p2822` - AGX Xavier Developer Kit
- `nvidia-p3449` - Jetson Nano Developer Kit
- `nvidia-p2597` - TX1/TX2 Developer Kit
- `nvidia-e3900` - AGX Xavier Industrial carrier
- `nvidia-e3366` - AGX Xavier Industrial carrier
- `nvidia-devkit` - Generic Developer Kit

#### Third-Party Carrier Boards

**Connect Tech:**
- `connecttech-photon` - Photon NGX003 (Orin/Xavier NX, Nano)
- `connecttech-photon-poe` - Photon NGX002 (with PoE)
- `connecttech-rogue-agx-orin` - Rogue AGX202
- `connecttech-rogue-agx-xavier` - Rogue AGX111
- `connecttech-spacely` - Spacely (TX2/TX1)
- `connecttech-orbitty` - Orbitty compact (TX2/TX1)

**Auvidea:**
- `auvidea-x230d` - X230D (AGX Orin)
- `auvidea-jn30d` - JN30D compact (Nano/TX2 NX)
- `auvidea-j120` - J120 Industrial

---

## Examples

### Basic Board Detection

```bash
# Get board type
BOARD=$(detect_jetson_board.sh)
echo "Running on: $BOARD"

# Check if it's a Forecr board
if [[ "$BOARD" == dsboard-* ]] || [[ "$BOARD" == milboard-* ]] || [[ "$BOARD" == raiboard-* ]]; then
    echo "Forecr/Exosens board detected"
fi
```

### Conditional Configuration

```bash
#!/bin/bash

BOARD=$(detect_jetson_board.sh --short)

case "$BOARD" in
    dsboard-ornxs|dsboard-ornx|dsboard-ornxlan)
        echo "Configuring for DSBOARD Orin..."
        # DSBOARD-specific configuration
        MAX_CAMERAS=4
        ENABLE_MIPI=true
        ;;

    milboard-*)
        echo "Configuring for MILBOARD (Military grade)..."
        # MILBOARD-specific configuration
        MAX_CAMERAS=8
        ENABLE_UART=8
        ENABLE_CAN=2
        ;;

    raiboard-*)
        echo "Configuring for RAIBOARD (Railway grade)..."
        # RAIBOARD-specific configuration
        POWER_RANGE="12-30V"
        TEMP_RANGE="-25C to 85C"
        ;;

    nvidia-*)
        echo "Configuring for Nvidia official board..."
        # Standard configuration
        ;;

    *)
        echo "Unknown board: $BOARD"
        exit 1
        ;;
esac
```

### Extract Specific Information with JSON

```bash
#!/bin/bash

# Get JSON output
BOARD_INFO=$(detect_jetson_board.sh --json)

# Extract specific fields using jq
SOM_TYPE=$(echo "$BOARD_INFO" | jq -r '.som.type')
VENDOR=$(echo "$BOARD_INFO" | jq -r '.vendor')
TEGRA=$(echo "$BOARD_INFO" | jq -r '.som.tegra')

echo "SoM: $SOM_TYPE"
echo "Vendor: $VENDOR"
echo "Tegra: $TEGRA"

# Conditional logic based on SoM
case "$SOM_TYPE" in
    orin-nano|orin-nx)
        echo "Orin family detected - enabling NVDLA"
        ;;
    agx-orin)
        echo "AGX Orin detected - enabling all compute units"
        ;;
    xavier-nx)
        echo "Xavier NX detected"
        ;;
esac
```

### Handling Misleading Model Strings

Some boards may have generic or misleading model strings but accurate compatible strings. The script automatically handles this:

```bash
#!/bin/bash
# Example: Board with "Orin NX" model string but actually P3767-0003 (Orin Nano)

# Run detection with verbose output
detect_jetson_board.sh -v

# Output shows:
# System on Module (SoM):
#   Type: orin-nano          <- Correctly identified from P3767-0003
#   Part: P3767-0003 (8GB)
#   SoC:  t234
# Device Tree:
#   Model: NVIDIA Jetson Orin NX Engineering Reference Developer Kit  <- Misleading
#   Compatible: nvidia,p3768-0000+p3767-0003 nvidia,p3767-0003 nvidia,tegra234  <- Accurate

# The script prioritizes compatible strings, so it correctly returns "orin-nano"
SOM_TYPE=$(detect_jetson_board.sh --json | jq -r '.som.type')
echo "Detected SoM: $SOM_TYPE"  # Output: orin-nano

# This ensures your scripts work correctly regardless of model string accuracy
if [[ "$SOM_TYPE" == "orin-nano" ]]; then
    # Configure for Orin Nano (6 CPU cores, 1024 CUDA cores)
    MAX_FREQ="1.5GHz"
    CUDA_CORES=1024
elif [[ "$SOM_TYPE" == "orin-nx" ]]; then
    # Configure for Orin NX (8 CPU cores, 1024 CUDA cores, different SKUs)
    MAX_FREQ="2.0GHz"
    CUDA_CORES=1024
fi
```

### Hardware-Specific Script

```bash
#!/bin/bash
# Example: Configure camera count based on board

BOARD=$(detect_jetson_board.sh --short)

# Default configuration
CAMERA_COUNT=2

# Board-specific overrides
case "$BOARD" in
    dsboard-ornxs)
        CAMERA_COUNT=4
        CAMERA_INTERFACE="MIPI CSI-2"
        ;;
    milboard-agx)
        CAMERA_COUNT=8
        CAMERA_INTERFACE="MIPI CSI-2"
        VIDEO_OUT="4K HDMI"
        ;;
    raiboard-*)
        CAMERA_COUNT=4
        CAMERA_INTERFACE="MIPI CSI-2"
        CONNECTORS="IP67 rated"
        ;;
esac

echo "Configuring $CAMERA_COUNT cameras on $BOARD"
```

### Systemd Service Integration

```bash
#!/bin/bash
# /usr/local/bin/board-specific-startup.sh

# Detect board at boot
BOARD=$(detect_jetson_board.sh --short)
BOARD_JSON=$(detect_jetson_board.sh --json)

# Log board information
logger "Detected board: $BOARD"
logger "Board details: $BOARD_JSON"

# Load board-specific configuration
if [[ -f "/etc/board-config/$BOARD.conf" ]]; then
    source "/etc/board-config/$BOARD.conf"
    logger "Loaded configuration for $BOARD"
fi

# Start board-specific services
case "$BOARD" in
    dsboard-*|milboard-*|raiboard-*)
        systemctl start forecr-camera-manager.service
        systemctl start dione-controller.service
        ;;
    nvidia-*)
        # Standard Nvidia services
        ;;
esac
```

---

## Integration

### Shell Scripts

```bash
#!/bin/bash
source <(detect_jetson_board.sh --json | jq -r 'to_entries | .[] | "BOARD_" + (.key | ascii_upcase) + "=\"" + (.value | tostring) + "\""')

echo "Board type: $BOARD_BOARD_TYPE"
echo "Vendor: $BOARD_VENDOR"
```

### Python Integration

```python
#!/usr/bin/env python3
import subprocess
import json

def get_board_info():
    """Get Jetson board information"""
    try:
        result = subprocess.run(
            ['detect_jetson_board.sh', '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error detecting board: {e}")
        return None

# Usage
board = get_board_info()
if board:
    print(f"Board: {board['board_type']}")
    print(f"SoM: {board['som']['type']}")
    print(f"Vendor: {board['vendor']}")

    if board['vendor'] == 'forecr':
        print("Forecr board detected - enabling Exosens features")
```

### C/C++ Integration

```c
#include <stdio.h>
#include <stdlib.h>

char* detect_board() {
    FILE *fp;
    static char board[256];

    fp = popen("detect_jetson_board.sh --short", "r");
    if (fp == NULL) {
        return "unknown";
    }

    if (fgets(board, sizeof(board), fp) != NULL) {
        // Remove newline
        board[strcspn(board, "\n")] = 0;
    }

    pclose(fp);
    return board;
}

int main() {
    char *board = detect_board();
    printf("Running on: %s\n", board);

    if (strncmp(board, "dsboard-", 8) == 0) {
        printf("DSBOARD detected\n");
    }

    return 0;
}
```

---

## Technical Details

### Detection Method

The script analyzes the following sources in order of reliability:

1. **Compatible Strings**: `/proc/device-tree/compatible` ⭐ **Most Reliable**
   - Contains actual part numbers (e.g., `nvidia,p3767-0003`)
   - Always available on all Jetson systems
   - Most accurate source for SoM identification
   - **Example**: `nvidia,p3768-0000+p3767-0003 nvidia,p3767-0003 nvidia,tegra234`

2. **DTB Filename**: `/proc/device-tree/nvidia,dtsfilename`
   - Device tree binary filename with board identifiers
   - May not be available on all systems (especially older L4T versions)
   - **Example**: `tegra234-p3767-0003-p3768-0000-a0-dsboard-ornxs.dtb`

3. **Device Tree Model**: `/proc/device-tree/model`
   - Human-readable board description
   - Less reliable (can be generic or misleading)
   - Used as fallback when other sources are unavailable
   - **Example**: `NVIDIA Jetson Orin Nano Developer Kit`

### Detection Logic

```
1. Read device tree information (model, DTB filename, compatible strings)
2. Parse compatible strings to extract part numbers (P-numbers)
3. Detect Tegra SoC (t210, t186, t194, t234) from compatible strings
4. Identify SoM based on part numbers with priority:
   a. Check compatible strings for exact part number (P3767-0003, etc.)
   b. Check DTB filename for part number patterns
   c. Fallback to model string matching
5. Identify carrier board from DTB filename or model patterns
6. Match against known board database
7. Return structured board information
```

### Why Compatible Strings Are Most Reliable

The compatible strings contain the actual hardware part numbers and are guaranteed to be present on all Jetson systems. Some boards (especially with older L4T versions or custom builds) may have:
- Missing DTB filename (`nvidia,dtsfilename` not available)
- Generic model strings that don't match the actual hardware
- Model strings from reference boards (e.g., "Orin NX" string on Orin Nano hardware)

By prioritizing compatible strings, the script correctly identifies boards even in these edge cases.

**Example case**: A board with P3767-0003 (Orin Nano 8GB) may have a model string saying "Orin NX Engineering Reference Developer Kit", but the compatible string `nvidia,p3767-0003` reveals the true hardware.

### Part Number Mapping

| Prefix | Component Type |
|--------|---------------|
| P2xxx | Early Jetson modules/carriers |
| P3xxx | Modern Jetson modules/carriers |
| E3xxx | Industrial carriers |
| NGX | Connect Tech products |

### Tegra SoC Generations

| Tegra | Architecture | Jetson Modules |
|-------|-------------|---------------|
| T210 | Maxwell GPU | TX1, Nano |
| T186 | Pascal GPU | TX2, TX2 NX |
| T194 | Volta GPU | AGX Xavier, Xavier NX |
| T234 | Ampere GPU | Orin family |

---

## Troubleshooting

### Unknown Board Detected

If the script returns "unknown":

1. Check device tree files exist:
   ```bash
   ls -la /proc/device-tree/
   cat /proc/device-tree/model
   cat /proc/device-tree/compatible | tr '\0' '\n'
   cat /proc/device-tree/nvidia,dtsfilename 2>/dev/null || echo "DTB filename not available"
   ```

2. Run in verbose mode to see what was detected:
   ```bash
   detect_jetson_board.sh -v
   ```

   This will show the compatible strings, which are the most reliable source for identification.

3. Check for custom device tree:
   ```bash
   dmesg | grep "Device Tree"
   ```

4. Verify compatible strings contain expected part numbers:
   ```bash
   cat /proc/device-tree/compatible | tr '\0' '\n' | grep -E 'p[0-9]{4}'
   ```

   Look for part numbers like `p3767-0003` (Orin Nano), `p3701-0000` (AGX Orin), etc.

### Script Not Found

```bash
# Check if installed
which detect_jetson_board.sh

# Check permissions
ls -l /usr/bin/detect_jetson_board.sh

# Reinstall if needed
sudo cp detect_jetson_board.sh /usr/bin/
sudo chmod +x /usr/bin/detect_jetson_board.sh
```

### JSON Parsing Errors

Ensure `jq` is installed for JSON processing:

```bash
sudo apt-get install jq
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1 | 2026-02-02 | Enhanced detection using compatible strings for improved reliability. Now correctly identifies boards even when DTB filename is unavailable or model string is misleading. Added compatible strings to verbose output. |
| 1.0 | 2025-02-02 | Initial release with comprehensive board support |

---

## Support

For issues or feature requests:
- **Forecr Boards**: support@forecr.io
- **Script Issues**: Check `/opt/eg/doc/` for updates

---

## License

Copyright © 2025 Exosens
Part of Forecr/Exosens Jetson BSP distribution.
