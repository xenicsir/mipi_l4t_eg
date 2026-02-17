# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SoM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also provides guidance for integrating the drivers on other L4T versions and carrier boards.

The [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet presents an overview of the supported cameras/SoM/carrier boards/L4T versions.

---

## Table of Contents

- [Prerequisites for cross-compiling](#prerequisites-for-cross-compiling)
  - [Host PC requirements](#host-pc-requirements)
- [Building and installing MIPI drivers](#building-and-installing-mipi-drivers)
  - [Supported L4T versions, SOM and carrier boards](#supported-l4t-versions-som-and-carrier-boards)
  - [Building the L4T environment](#building-the-l4t-environment)
    - [Source code organization](#source-code-organization)
    - [Building workflow](#building-workflow)
    - [Client workflow (patches only)](#client-workflow-patches-only)
  - [Building MIPI drivers for specific carrier boards](#building-mipi-drivers-for-specific-carrier-boards)
  - [Installing and configuring the MIPI drivers on the board](#installing-and-configuring-the-mipi-drivers-on-the-board)
    - [Package installation](#package-installation)
    - [Configuring camera ports](#configuring-camera-ports)
  - [Quick start - Testing the camera](#quick-start---testing-the-camera)
- [Notes about Linux boot and device trees](#notes-about-linux-boot-and-device-trees)
  - [Linux boot configuration](#linux-boot-configuration)
  - [Orin NX/Nano CSI lanes issues](#orin-nxnano-csi-lanes-issues)
- [Shell completion](#shell-completion)
- [Appendix A: Integrating drivers on other L4T versions and carrier boards](#appendix-a-integrating-drivers-on-other-l4t-versions-and-carrier-boards)
  - [Adding a new L4T version, vendor, or carrier board](#adding-a-new-l4t-version-vendor-or-carrier-board)
  - [Creating device trees for a new SoM / carrier board](#creating-device-trees-for-a-new-som--carrier-board)
  - [Understanding the source copy and patch generation workflow](#understanding-the-source-copy-and-patch-generation-workflow)
- [Appendix B: Adding a new camera type](#appendix-b-adding-a-new-camera-type)

---

## Prerequisites for cross-compiling

### Host PC requirements

**Recommended OS:** Ubuntu 20.04 LTS, 22.04 LTS or 24.04 LTS, depending on L4T version. Ubuntu 22.04 LTS is currently used.

**Required packages:**

```bash
# For standalone builds (L4T 36.x): ARM64 emulation for initramfs generation
sudo apt install qemu-user-static binfmt-support

# For faster archive extraction (highly recommended)
sudo apt install lbzip2 pigz pbzip2

# For building Debian packages
sudo apt install ruby ruby-dev
sudo gem install fpm

# For JSON configuration processing
sudo apt install jq
```

---

## Building and installing MIPI drivers

### Supported L4T versions, SOM and carrier boards

Refer to the [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet for the complete list of supported configurations.

For the rest of this document:
- `<l4t_version>` refers to the L4T version (e.g., `35.5.0`, `36.4.4`)
- `<vendor>` refers to the carrier board vendor (`generic` for Nvidia boards, or vendor-specific like `forecr`)

### Building the L4T environment

This section describes the build process using the unified `l4t_make.sh` orchestration script.

#### Source code organization

The Exosens camera driver modifications are available in two formats:
- **sources/**: Complete source files organized by L4T version and vendor
- **patches/**: Automatically generated patch files for distribution

#### Building workflow

The `l4t_make.sh` script orchestrates the entire build process. Use `./l4t_make.sh --help` for complete documentation.
It uses individual scripts for build steps.

**Step 1: Prepare the L4T environment**

Download and extract the BSP, toolchain, and sources for a specific L4T version:

```bash
./l4t_make.sh -v <l4t_version> --prepare
```
or use the individual script for more logs : 
```bash
./l4t_prepare.sh -v <l4t_version>
```


To start from scratch (delete existing build directory):

```bash
./l4t_make.sh -v <l4t_version> --prepare --from-scratch
```

This step:
- Downloads BSP archives (jetson_linux, sample rootfs, toolchain, public sources)
- Extracts archives using parallel decompression when available
- Prepares the Linux_for_Tegra directory structure

**Step 2: Copy sources and generate patches**

Copy Exosens sources to the build environment and generate distribution patches:

```bash
./l4t_make.sh -v <l4t_version> --copy-sources
```
or use the individual script for more logs : 
```bash
./l4t_copy_sources.sh -v <l4t_version>
```

This step:
- Copies source files from `sources/` to the build environment
- Creates a git repository to track modifications
- Generates patch files in `patches/<l4t_version>/` for distribution

**Step 3: Build kernel and drivers**

Compile the kernel, device trees, and kernel modules:

```bash
./l4t_make.sh -v <l4t_version> --build
```
or use the individual script for more logs : 
```bash
./l4t_build.sh -v <l4t_version>
```

This step:
- Configures and builds the kernel Image
- Builds device tree blobs (.dtb) and overlays (.dtbo)
- Compiles and installs kernel modules
- For L4T 36.x standalone builds, generates initramfs with the `-eg` suffix

**Step 4: Generate the Debian package**

Create the deliverable `.deb` package:

```bash
./l4t_make.sh -v <l4t_version> --gen-package [-p <debian_version>]
```
or use the individual script for more logs : 
```bash
./l4t_gen_delivery_package.sh -v <l4t_version> [-p <debian_version>]
```

The `-p` option is optional. The package version is determined as follows:

| Scenario | Command | Debian version |
|---|---|---|
| Release (on git tag `3.1.0`) | `--gen-package` | `3.1.0` |
| Development build | `--gen-package -p 3.2.0` | `3.2.0+g84920ea` |
| Branch build | `--gen-package -p feature/foo` | `0~feature-foo+g84920ea` |
| No `-p`, no tag | `--gen-package` | `0~branch-name+g84920ea` |

Where `g84920ea` is the short git commit hash for traceability.

Version strings are sanitized for Debian compatibility (invalid characters replaced, `0~` prefix added when the version doesn't start with a digit). The `0~` prefix ensures development builds sort before any release version.

The generated package: `jetson-l4t-<l4t_version>-eg-cams_<debian_version>_arm64.deb`

**Running all steps at once:**

```bash
./l4t_make.sh -v <l4t_version>
```

This runs all four steps (prepare, copy-sources, build, gen-package) sequentially.

```bash
./l4t_make.sh
```

This runs all four steps (prepare, copy-sources, build, gen-package) sequentially for all L4T versions.

**Parallel execution:**

To build multiple L4T versions simultaneously:

```bash
# Auto-detect number of CPU cores (default)
./l4t_make.sh

# Specify number of parallel jobs
./l4t_make.sh -j 4

# Build specific versions in parallel
./l4t_make.sh -v "36.*" -j 8
```

The parallel mode displays live status for each configuration showing version, vendor, carrier board, and current build step.

**Note about L4T 36.x standalone builds:**

Because for Nvidia SDK version from L4T 36.x some kernel modules are built "out of tree", Linux is built in **standalone mode** with the `-eg` suffix. This means:
- The kernel version becomes `X.Y.Z-tegra-eg` instead of `X.Y.Z-tegra`
- ALL kernel modules are included in the package (not just camera modules)
- A dedicated initramfs (`/boot/eg/initrd-eg`) is generated
- The Debian package is larger (~150MB) due to all modules and initramfs being included

#### Client workflow (patches only)

If you are a client who only needs to rebuild without modifying the code, you can use the patch-based workflow.

The patches are available in the `patches/` directory and can be applied to a clean L4T environment using the `l4t_patch_sources.sh` script as a reference:

```bash
./l4t_make.sh -v <l4t_version> --prepare
# Apply patches manually (refer to l4t_patch_sources.sh for the method)
./l4t_make.sh -v <l4t_version> --build --gen-package
```

The `l4t_patch_sources.sh` script demonstrates how to apply patches to your own Linux_for_Tegra environment. Clients can adapt this script to their specific needs.

### Building MIPI drivers for specific carrier boards

Some carrier boards require specific device trees and/or kernel configurations. The boards needing specific builds are tagged "Specific build" in the [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet.

**Example: Building for Forecr carrier board with dsboard_ornx:**

```bash
# Build all steps for forecr/dsboard_ornx
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornx

# Or step by step:
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornx --prepare
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornx --copy-sources
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornx --build
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornx --gen-package

# Or step by step with individual scripts :
./l4t_prepare.sh -v <l4t_version> -V forecr -c dsboard_ornx
./l4t_copy_sources.sh -v <l4t_version> -V forecr -c dsboard_ornx
./l4t_build.sh -v <l4t_version> -V forecr -c dsboard_ornx
./l4t_gen_delivery_package.sh -v <l4t_version> -V forecr -c dsboard_ornx

```

This generates: `jetson-l4t-<l4t_version>-forecr-dsboard-ornx-eg-cams_<debian_version>_arm64.deb`

### Installing and configuring the MIPI drivers on the board

#### Package installation

**Important:** If you have driver version 2.x.x or lower already installed, you must **uninstall** it first (not just update) :

```bash
# Uninstall old version if present
sudo dpkg -r jetson-l4t-mipi-eg-cam  # or similar package name

# Install new version
sudo dpkg -i jetson-l4t-<l4t_version>-eg-cams_<debian_version>_arm64.deb
```

The package was either delivered (see [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx)) or built locally following the previous steps.

#### Configuring camera ports

**Note on port numbers:**
- Jetson carrier boards typically include 2 camera ports: "CAM0" and "CAM1"
- For the AGX Orin Auvidea X230D carrier board, port 0 is "CD" and port 1 is "AB" on the PCB
- The `/dev/videoX` device number is NOT the camera port number, but the registration order. Carefully check with the eg_dt_camera_config_get script.

**Default configuration:**

After first installation, both ports are configured for Dione cameras.

**Changing the configuration:**

```bash
eg_dt_camera_config_set.sh <port>/<cam_type> [<port>/<cam_type>] ...
```

Where:
- `<port>` = `0` or `1` (camera port number)
- `<cam_type>` = `Dione`, `MicroCube`, `SmartIR640`, `Crius1280`, `iLumos`, or `Microlynx`

Example :
```bash
eg_dt_camera_config_set.sh 1/SmartIR640 0/Dione
```

**Note:** Ports not specified in the command are configured for Dione by default. So the above command is equivalent to this one :
```bash
eg_dt_camera_config_set.sh 1/SmartIR640
```

**After changing configuration, reboot is required:**

```bash
sudo reboot
```

**Getting the current configuration:**

After a configuration change and reboot, check the current status:

```bash
eg_dt_camera_config_get.sh
```

This displays:
- **Board:** The detected board, SoM and SoC
- **Camera ports:** For each port, the camera model (from sysfs), connection status (color-coded), video device, I2C device, serial number, native resolution, and pixel format
- **Total configured:** Number of configured cameras

**Example output:**
```
=== Exosens Camera Configuration ===

Board: nvidia-devkit (orin-nx, t234)

Camera ports:
  Port 0: SmartIR640 (connected)
    Video device: /dev/video0
    I2C device:   /dev/eg-ec-mipi-10-0016
    Serial:       21456
    Resolution:   640x480
    Pixel format: 'Y16 ' (16-bit Greyscale)
  Port 1: Dione 640 (connected)
    Video device: /dev/video1
    I2C device:   /dev/dioneir-i2c-9-000e-5a
    Serial:       20823
    Resolution:   640x480
    Pixel format: 'AR24' (32-bit BGRA 8-8-8-8)

Total configured: 2 camera(s)
```

**Note:** For some boards with multiple camera ports, it is possible to mix Exosens cameras with sensors originally supported by Jetson boards (IMX219, IMX477). Consult the support team if needed.

### Quick start - Testing the camera

After installing the package and rebooting, verify camera detection:

```bash
ls /dev/video*
```

A `/dev/videoX` device should appear for each connected camera.

**Check camera information:**

```bash
v4l2-ctl -d /dev/video0 --all
```

**Capture a single frame:**

- **MicroCube/SmartIR640** (YCbCr format, 640x480):
```bash
v4l2-ctl -d /dev/video0 --stream-mmap \
  --set-fmt-video=width=640,height=480,pixelformat="YUYV" \
  --set-ctrl=sensor_mode=2 --stream-count=1 --stream-to=frame.raw
```

- **Crius1280** (YCbCr format, 1280x1024):
```bash
v4l2-ctl -d /dev/video0 --stream-mmap \
  --set-fmt-video=width=1280,height=1024,pixelformat="YUYV" \
  --set-ctrl=sensor_mode=5 --stream-count=1 --stream-to=frame.raw
```

- **Dione** (ARGB format, 640x480):
```bash
v4l2-ctl -d /dev/video0 --stream-mmap \
  --set-fmt-video=width=640,height=480,pixelformat="AR24" \
  --stream-count=1 --stream-to=frame.raw
```

- **iLumos** (RAW16 format, 2048x2048):
```bash
v4l2-ctl -d /dev/video0 --stream-mmap \
  --set-fmt-video=width=2048,height=2048,pixelformat="RG16" \
  --set-ctrl=sensor_mode=0 --stream-count=1 --stream-to=frame.raw
```

For more streaming examples, see `/opt/eg/doc/streaming_examples.txt` on the target after package installation.

---

## Notes about Linux boot and device trees

### Linux boot configuration

The `/boot/extlinux/extlinux.conf` file contains Linux boot configuration. A "JetsonIO" entry is added at first package installation and set as default.

**Example from Orin NX:**

```
DEFAULT JetsonIO
[...]
LABEL JetsonIO
    MENU LABEL Custom Header Config: <CSI Exosens Cameras. CAM0:EC_1_lane> <CSI Exosens Cameras. CAM1:EC_1_lane>
    LINUX /boot/eg/Image
    FDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0000-nv.dtb
    INITRD /boot/initrd
    APPEND [...]
    OVERLAYS /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo
    [...]
```

**Description:**
- **LINUX:** Path to the kernel Image
  - `/boot/eg/Image` - The Exosens kernel
- **FDT:** Base device tree file
- **INITRD:** Initial ramdisk
  - `/boot/initrd` for L4T 32.x/35.x
  - **`/boot/eg/initrd-eg` for L4T 36.x standalone builds**
- **OVERLAYS:** Comma-separated list of device tree overlay files to apply

**Important note for L4T 36.x:**

For standalone builds (L4T 36.x), the INITRD line must use the standalone initramfs:

```
INITRD /boot/eg/initrd-eg
```

The package post-install script automatically updates this when installing on a system with JetsonIO configuration.

**Custom kernel patches:**

Customers can add their own kernel patches in:
- `sources/<l4t_version>/Linux_for_Tegra/` (full sources)
- `patches/<l4t_version>/` (patch files)

Consult the support team for assistance with custom modifications.

### Orin NX/Nano CSI lanes issues

The Orin SoM has a CSI differential pair swap issue, and the Orin NX/Nano devkit carrier board has a CSI data lane swap issue. 
More information is avalaible in the docs/CSI_LANE_AND_POLARITY_SWAP_P3768.md document.

---

## Shell completion

The build system includes bash completion for `l4t_make.sh` commands and arguments.

**To enable completion on your host PC:**

```bash
# Add to your ~/.bashrc
source /path/to/mipi_l4t_eg-forecr-5.x/tools/l4t_completion.bash

# Or install system-wide
sudo cp tools/l4t_completion.bash /etc/bash_completion.d/l4t_make
```

This provides tab-completion for:
- Command options (`--prepare`, `--build`, etc.)
- L4T versions (`-v 36.4.4`)
- Vendors (`-V forecr`)
- Carrier boards (`-c dsboard_ornx`)

---

## Appendix A: Integrating drivers on other L4T versions and carrier boards

This section provides guidance for creating MIPI drivers for new L4T versions, vendors, and carrier boards.

### Adding a new L4T version, vendor, or carrier board

The build system uses `l4t_versions.json` to define supported configurations.

**Step 1: Update l4t_versions.json**

Add configuration for the new L4T version:

```json
{
  "versions": {
    "36.5.0": {
      "vendors": ["generic", "forecr"],
      "sources": {
        "public": {
          "filename": "public_sources.tbz2",
          "url": "https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/sources/public_sources.tbz2"
        },
        "release": {
          "filename": "jetson_linux_r36.5.0_aarch64.tbz2",
          "url": "https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/jetson_linux_r36.5.0_aarch64.tbz2"
        },
        "sample_fs": {
          "filename": "tegra_linux_sample-root-filesystem_r36.5.0_aarch64.tbz2",
          "url": "https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/tegra_linux_sample-root-filesystem_r36.5.0_aarch64.tbz2"
        }
      },
      "toolchain": {
        "archive": "aarch64--glibc--stable-2022.08-1.tar.bz2",
        "url": "https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v3.0/toolchain/aarch64--glibc--stable-2022.08-1.tar.bz2",
        "dir": "aarch64--glibc--stable-2022.08-1",
        "prefix": "aarch64--glibc--stable-2022.08-1/bin/aarch64-buildroot-linux-gnu-"
      },
      "standalone": {
        "forecr": {
          "dsboard_ornx": true
        }
      }
    }
  },
  "vendors": {
    "generic": {
      "carriers": ["generic"],
      "default_carrier": "generic"
    },
    "forecr": {
      "carriers": ["dsboard_ornx"],
      "default_carrier": "dsboard_ornx"
    }
  },
  "carriers": {
    "generic": {},
    "dsboard_ornx": {
      "defconfig": "forecr_defconfig",
      "dir_suffix": "dsboard_ornx"
    }
  }
}
```

**Step 2: Create source directory structure**

Create the source directory for the new L4T version:

```bash
# For generic (Nvidia) boards
mkdir -p sources/<l4t_version>_NEW/Linux_for_Tegra/

# For vendor-specific boards (if applicable)
mkdir -p sources/<l4t_version>_NEW/Linux_for_Tegra_<vendor_new>/
```

**Step 3: Port source files**

Copy and adapt source files from a similar L4T version:

```bash
# Start with the closest L4T version as a template
cp -r sources/<l4t_version>_SIMILAR/Linux_for_Tegra/* \
      sources/<l4t_version>_NEW/Linux_for_Tegra/

# Review and adapt:
# - Kernel defconfig files
# - Device tree overlays
# - Scripts in rootfs/opt/eg/ and rootfs/usr/bin/
# - Any version-specific patches
```

**Step 4: Create device trees**

See next section for detailed device tree creation.

**Step 5: Test the build**

```bash
./l4t_make.sh -v <l4t_version>_NEW --all
```

### Creating device trees for a new SoM / carrier board

Device tree source files location depends on L4T version:
- **L4T 36.x:** `sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay/`
- **L4T 32.x/35.x:** `sources/common/source/hardware_32+/nvidia/soc/t19x/kernel-dts/`

**Steps for creating device trees (example for Orin with tegra234-pXXXX SoM ID):**

1. **Create common base device tree:**

```bash
cd sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay/

# Create the common camera definitions
# Based on Nvidia's native tegra234-pXXXX-camera files and existing examples
cp tegra234-p3767-camera-common-eg-cams-dione.dtsi \
   tegra234-pXXXX-camera-common-eg-cams-dione.dtsi

# Edit to match your hardware:
# - CSI port mappings
# - I2C bus numbers
# - GPIO assignments
# - Clock configurations
```

2. **Create overlay files for each camera configuration:**

```bash
# Dione camera overlay (base)
cp tegra234-p3767-camera-p3768-eg-cams-dione.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cams-dione.dts

# Port 0 overlays (1-lane and 2-lanes EngineCore)
cp tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-1-lane.dts

cp tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-2-lanes.dts

# Port 1 overlays
cp tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-1-lane.dts

cp tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-2-lanes.dts
```

3. **Update the Makefile to build the new overlays:**

```makefile
# In sources/<l4t_version>/Linux_for_Tegra/source/hardware/nvidia/t23x/nv-public/overlay/Makefile
# (for L4T 36.x)

dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cams-dione.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-1-lane.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-2-lanes.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-1-lane.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-2-lanes.dtbo
```

4. **For vendor-specific carrier boards with special requirements:**

If the carrier board has hardware differences (e.g., different GPIO for cam_i2c_mux), create a vendor-specific variant:

```bash
# Example for a Forecr board with special configuration
cp tegra234-p3767-camera-common-eg-cams-dione.dtsi \
   tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dts

# Modify for the specific board's hardware
```

### Understanding the source copy and patch generation workflow

The build system uses a layered source organization with 3-way merging for vendor integration.

**Source organization**

```
sources/
├── common/                         # Shared across all L4T versions
│   ├── Linux_for_Tegra/           # Target scripts and documentation
│   │   ├── rootfs/opt/eg/         # Exosens tools (jetson-io, docs)
│   │   └── rootfs/usr/bin/        # User scripts (config_set, config_get, detect_board)
│   └── source/                    # Common driver and device tree sources
│       ├── hardware_36+/          # DT overlays for L4T 36.x+
│       ├── hardware_32+/          # DT overlays for L4T 32.x-35.x
│       └── nvidia-oot/            # Camera kernel drivers (.c, .h)
│
├── 35.6.0/                        # Version-specific files
│   ├── Linux_for_Tegra/           # Generic (Nvidia) boards
│   │   └── source/public/kernel/  # Kconfig, Makefile for this version
│   └── Linux_for_Tegra_forecr/    # Forecr vendor additions
│       └── source/public/         # Forecr defconfigs, device trees, Makefiles
│
└── 36.4.4/
    ├── Linux_for_Tegra/           # Generic boards
    └── Linux_for_Tegra_forecr/    # Forecr vendor additions
```

**Layered copy with 3-way merge**

When running `./l4t_copy_sources.sh -v <version> [-V <vendor>]`:

1. **Initialize git** in the build directory, commit the original Nvidia BSP state.

2. **Copy sources in layers** (each layer can override or extend the previous):
   - Layer 1: `sources/common/` — shared Exosens files (drivers, DT, scripts)
   - Layer 2: `sources/<version>/Linux_for_Tegra/` — version-specific files
   - Layer 3 *(vendor builds only)*: `sources/<version>/Linux_for_Tegra_<vendor>/` — vendor files

3. **3-way merge for overlapping files**: When a file modified by Layer 2 (generic) is also modified by Layer 3 (vendor), a simple overwrite would lose the generic changes. Instead, the script performs a 3-way merge:
   - **Base**: the original BSP file (common ancestor)
   - **Ours**: the file after Layer 2 (generic Exosens modifications)
   - **Theirs**: the vendor source file (Layer 3)

   This preserves changes from both sides. If the merge conflicts (both sides insert at the same location), a `--union` fallback includes both sets of changes.

   Typical merged files: `Makefile` (both Exosens and Forecr add dtbo/dtb entries), `Kconfig` (both add config options).

4. **Generate patches**: Git diffs between BSP and modified state produce patch files in `patches/<version>[_<vendor>]/`, organized by directory.

5. **Verify patches**: Re-applies patches on clean BSP and checks the result matches the source tree.

**Example: Forecr vendor build**

```bash
./l4t_copy_sources.sh -v 35.6.0 -V forecr

# Layer 1: sources/common/                          → Exosens drivers, DT, scripts
# Layer 2: sources/35.6.0/Linux_for_Tegra/          → Exosens Kconfig, Makefile, defconfig
# Layer 3: sources/35.6.0/Linux_for_Tegra_forecr/   → Forecr defconfigs, Makefiles, DT
#
# p3768/kernel-dts/Makefile → 3-way merge:
#   BSP Makefile + Exosens dtbo entries + Forecr dtb entries = merged Makefile
#
# Result: Combined Nvidia BSP + Exosens + Forecr
# Patches generated in: patches/35.6.0_forecr/
```

---

## Appendix B: Adding a new camera type

This section describes all the files to create or modify when adding support for a new Exosens camera. The iLumos camera is used as a concrete example.

### 1. Kernel driver

**Add the driver source file:**

`sources/common/source/nvidia-oot/drivers/media/i2c/<camera>.c`

This is a V4L2 sensor driver that handles I2C communication, MIPI CSI-2 streaming, and device tree integration. Use an existing driver (e.g., `dioneir.c`, `eg_ec_mipi_src.c`) as a template.

The driver must:
- Register as an I2C driver with a unique compatible string (e.g., `"exosens,ilumos"`)
- Implement V4L2 subdev operations (get_fmt, set_fmt, enum_mbus_code, stream on/off)
- Expose sysfs attributes (`model`, `serial_number`, `resolution`, `pixel_format`) for `eg_dt_camera_config_get.sh`

**Add Kconfig and Makefile entries (per L4T version):**

For L4T 32.x/35.x (in-tree build), modify version-specific files:
- `sources/<version>/Linux_for_Tegra/source/public/kernel/nvidia/drivers/media/i2c/Kconfig` — add `config VIDEO_<CAMERA>` entry
- `sources/<version>/Linux_for_Tegra/source/public/kernel/nvidia/drivers/media/i2c/Makefile` — add `obj-$(CONFIG_VIDEO_<CAMERA>) += <camera>.o`

For L4T 36.x (out-of-tree build), the nvidia-oot Makefile uses `obj-m += <camera>.o`.

**Enable in defconfig** (L4T 32.x/35.x only):

Add `CONFIG_VIDEO_<CAMERA>=m` to the relevant kernel defconfigs.

### 2. Device tree

**Add camera nodes to the common DTS include:**

For each SoC family, add the camera sensor nodes to the common include file:

| SoC family | File |
|-----------|------|
| T23x (Orin) | `sources/common/source/hardware_32+/nvidia/platform/t23x/p3768/kernel-dts/tegra234-p3767-camera-common-eg-cams-dione.dtsi` |
| T23x (AGX Orin) | `sources/common/source/hardware_32+/nvidia/platform/t23x/concord/kernel-dts/tegra234-p3737-camera-common-eg-cams-dione.dtsi` |
| T19x (Xavier) | `sources/common/source/hardware_32+/nvidia/platform/t19x/jakku/kernel-dts/tegra194-camera-common-eg-cams-dione.dtsi` |
| T210 (Nano) | `sources/common/source/hardware_32+/nvidia/platform/t210/porg/kernel-dts/tegra210-camera-common-eg-cams-dione.dtsi` |
| T23x L4T 36+ | `sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay/tegra234-p3767-camera-common-eg-cams-dione.dtsi` |

Each camera node defines: I2C address, MIPI lane configuration, CSI port binding, video modes, and compatible string.

**Create per-port overlay DTS files:**

For each camera port, create an overlay that configures the MIPI lanes and disables the other camera types on that port:

```
tegra234-p3767-camera-p3768-eg-cam0-<camera>.dts   # Port 0
tegra234-p3767-camera-p3768-eg-cam1-<camera>.dts   # Port 1
```

The overlay-name must follow the convention: `"Exosens Cameras. CAM<N>:<DisplayName>"` (e.g., `"Exosens Cameras. CAM0:iLumos"`).

**Add dtbo build targets to version-specific Makefiles:**

Add `dtbo-y += tegra234-p3767-camera-p3768-eg-cam<N>-<camera>.dtbo` entries.

For L4T 32.x/35.x: `sources/<version>/Linux_for_Tegra/source/public/hardware/nvidia/platform/t23x/p3768/kernel-dts/Makefile`

For L4T 36.x: `sources/<version>/Linux_for_Tegra/source/hardware/nvidia/t23x/nv-public/overlay/Makefile`

### 3. Target scripts

**`eg_dt_camera_config_set.sh`** — add to the `CAMERA_LANES` associative array:

```bash
declare -A CAMERA_LANES=(
    ...
    [iLumos]="iLumos"     # overlay suffix matching DTS overlay-name
    [ilumos]="iLumos"     # case-insensitive alias
)
```

The value is the suffix used in `"Exosens Cameras. CAM<N>:<suffix>"`. For Dione, the value is empty (no per-port overlay needed).

**`eg_dt_camera_config_get.sh`** — add to the `CAMERA_DATABASE` array:

```bash
CAMERA_DATABASE=(
    ...
    "ilumos:30:ilumos_([a-h])@30:iLumos:4"
)
```

Format: `CATEGORY:I2C_ADDR:DT_NODE_PATTERN:DISPLAY_NAME:MIPI_LANES`. See `doc/eg_dt_camera_config_get_add_camera.md` for details.

### 4. Build scripts (host)

**`l4t_gen_delivery_package.sh`** — add to the camera type normalization `case` in the postinst script:

```bash
case "$cam_type" in
    ...
    *iLumos*|*ilumos*) cam_type="iLumos" ;;
    ...
esac
```

This ensures the postinst correctly re-applies the camera configuration during package upgrades.

**`l4t_verify_packages.sh`** — no change needed. Module detection is automatic from patch files.

### 5. Patches

After modifying all the above files, run `./l4t_copy_sources.sh` for each supported version to regenerate the patches. Verify with `./tools/verify_patches.sh`.

### Summary

| Step | Files | Purpose |
|------|-------|---------|
| Kernel driver | `sources/common/source/nvidia-oot/drivers/media/i2c/<camera>.c` | V4L2 sensor driver |
| Kconfig/Makefile | `sources/<version>/.../drivers/media/i2c/{Kconfig,Makefile}` | Build integration |
| DT common | `sources/common/source/hardware_*/.../*-camera-common-eg-cams-dione.dtsi` | Camera nodes per SoC |
| DT overlays | `sources/common/source/hardware_*/.../*-eg-cam<N>-<camera>.dts` | Per-port MIPI config |
| DT Makefiles | `sources/<version>/.../<platform>/kernel-dts/Makefile` | Build dtbo targets |
| config_set.sh | `sources/common/.../rootfs/usr/bin/eg_dt_camera_config_set.sh` | CAMERA_LANES entry |
| config_get.sh | `sources/common/.../rootfs/usr/bin/eg_dt_camera_config_get.sh` | CAMERA_DATABASE entry |
| postinst | `l4t_gen_delivery_package.sh` | Camera type normalization |
| Documentation | `README.md`, `doc/eg_dt_camera_config_*.md` | User-facing docs |

---

**For additional support or questions, contact the Exosens support team.**
