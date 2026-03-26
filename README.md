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
- [Camera Format Performance Benchmark](#camera-format-performance-benchmark)
- [Notes about Linux boot and device trees](#notes-about-linux-boot-and-device-trees)
  - [Linux boot configuration](#linux-boot-configuration)
  - [Orin NX/Nano CSI lanes issues](#orin-nxnano-csi-lanes-issues)
- [Shell completion](#shell-completion)
- [Appendix A: Integrating drivers on other L4T versions and carrier boards](#appendix-a-integrating-drivers-on-other-l4t-versions-and-carrier-boards)
- [Appendix B: Adding a new camera type](#appendix-b-adding-a-new-camera-type)
- [Appendix C: Supported cameras — MIPI lanes and video formats](#appendix-c-supported-cameras--mipi-lanes-and-video-formats)

---

## Prerequisites for cross-compiling

### Host PC requirements

**Recommended OS:** Ubuntu 20.04 LTS, 22.04 LTS or 24.04 LTS, depending on L4T version. Ubuntu 22.04 LTS is currently used.

**Git configuration:** A name and email must be set (used when generating package version strings):

```bash
git config user.email your@email.com
git config user.name "Your Name"
```

**Required packages:**

```bash
# For standalone builds (L4T 36.x): ARM64 emulation for initramfs generation
sudo apt install qemu-user-static binfmt-support

# For kernel/device tree build (parser generators)
sudo apt install flex bison

# For faster archive extraction (highly recommended)
sudo apt install lbzip2 pigz pbzip2

# For building Debian packages
sudo apt install ruby ruby-dev
sudo gem install fpm

# For JSON configuration processing
sudo apt install jq

# For kernel module build (OpenSSL headers)
sudo apt install libssl-dev
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

## Camera Format Performance Benchmark

For applications requiring specific video format support or optimization, refer to the **[Camera Format Performance Benchmark](tools/camera-format-benchmark/)** for comprehensive performance analysis and automation scripts.

This benchmark compares three camera formats (YUYV, Y16, AR24) across real-time display and H.264 encoding scenarios on NVIDIA Jetson Orin NX with JetPack 6.2.1 (L4T 36.4.4). It includes:

- **Performance metrics:** CPU load, GPU utilization, power consumption
- **Use case recommendations:** Display-only, recording, simultaneous display+recording
- **GStreamer command examples** for each scenario
- **Technical analysis** of format selection trade-offs

The benchmark provides objective performance data to guide format selection based on your specific application requirements.

---

## Appendix A: Integrating drivers on other L4T versions and carrier boards

This appendix provides a summary of the integration scenarios. For detailed step-by-step procedures with exact file paths, device tree format differences, and code examples, see the **[MIPI Driver Development Guide](docs/MIPI_DRIVER_DEVELOPMENT_GUIDE.md)**.

### Scenario C: Porting to a new hardware platform (SoM / carrier board)

1. Gather hardware info from schematics: CSI port mapping, I2C bus, GPIO, lane polarity
2. Create common DTSI and per-camera overlay DTS files adapted from an existing platform
3. Add dtbo targets to version-specific Makefiles
4. Register the new vendor/carrier board in `l4t_versions.json`
5. Regenerate patches with `./l4t_copy_sources.sh`

### Scenario D: Adding support for a new Nvidia BSP version

1. Add the new version to `l4t_versions.json` (BSP URLs, toolchain, vendors)
2. Copy the version-specific directory from the closest existing version
3. Adapt Makefiles, Kconfig, defconfig, and device tree bindings as needed
4. Build and fix compilation errors: `./l4t_make.sh -v <new_version> --prepare --copy-sources --build`
5. Regenerate patches with `./l4t_copy_sources.sh`

### Understanding the source copy and patch generation workflow

The build system uses a layered source organization with 3-way merging for vendor integration. See the [MIPI Driver Development Guide — Architecture Overview](docs/MIPI_DRIVER_DEVELOPMENT_GUIDE.md#architecture-overview) for details.

When running `./l4t_copy_sources.sh -v <version> [-V <vendor>]`, sources are copied in layers:

1. `sources/common/` — shared Exosens files (drivers, DT, scripts)
2. `sources/<version>/Linux_for_Tegra/` — version-specific generic files
3. *(vendor only)* `sources/<version>/Linux_for_Tegra_<vendor>/` — vendor-specific files

When Layers 2 and 3 both modify the same file (e.g., a Makefile), a **3-way merge** is performed using the original Nvidia BSP as the common ancestor. This means you only need to modify files in `Linux_for_Tegra/` (generic); vendor Makefiles will automatically inherit additions.

---

## Appendix B: Adding a new camera type

This appendix provides a summary of the files involved. For detailed step-by-step procedures with code examples and device tree format differences, see the **[MIPI Driver Development Guide — Scenario A](docs/MIPI_DRIVER_DEVELOPMENT_GUIDE.md#scenario-a-adding-a-new-camera-to-an-existing-bsp-version)**.

### Summary of files to create or modify

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

The driver must expose sysfs attributes (`model`, `serial_number`, `resolution`, `pixel_format`) for `eg_dt_camera_config_get.sh`. The overlay-name must follow: `"Exosens Cameras. CAM<N>:<DisplayName>"`.

After modifying all files, regenerate patches with `./l4t_copy_sources.sh` for each supported version.

---

## Appendix C: Supported cameras — MIPI lanes and video formats

### Summary table

| Camera | Driver | MIPI Lanes 
|--------|--------|:----------:|
| EngineCore (EC) | `eg-ec-mipi` | 1 or 2 |
| Dione IR | `dioneir` | 2 |
| iLumos | `ilumos` | 4 |
| Microlynx | `microlynx` | 2 |

---

### EngineCore (EC)

**Driver:** `eg-ec-mipi`
**Compatible models:** MicroCube, SmartIR640, Crius1280

**MIPI CSI-2 lanes:**

| Model | Lanes |
|-------|:-----:|
| MicroCube | 1 |
| SmartIR640, Crius1280 | 2 |

**Video modes:**

| Resolution | Pixel format | V4L2 format |
|------------|--------------|-------------|
| 640 × 480 | 16-bit raw greyscale | `Y16` |
| 640 × 480 | 32-bit BGRA | `AR24` |
| 640 × 480 | YUV 4:2:2 | `YUYV` |
| 1280 × 1024 | 16-bit raw greyscale | `Y16` |
| 1280 × 1024 | 32-bit BGRA | `AR24` |
| 1280 × 1024 | YUV 4:2:2 | `YUYV` |

The `Y16` format requires L4T kernel 5.0 or later (L4T 35.x+).

---

### Dione IR

**Driver:** `dioneir`
**Bridge chip:** Toshiba TC358746 (parallel-to-CSI-2)

**MIPI CSI-2 lanes:** 2

**Video modes:**

| Resolution | Pixel format | V4L2 format |
|------------|--------------|-------------|
| 320 × 240 | 32-bit BGRA | `AR24` |
| 640 × 480 | 32-bit BGRA | `AR24` |
| 1024 × 768 | 32-bit BGRA | `AR24` |
| 1280 × 1024 | 32-bit BGRA | `AR24` |

The active resolution depends on the camera model. The TC358746 bridge handles the parallel-to-MIPI conversion; the pixel format is fixed to 32-bit BGRA as delivered over CSI-2.

---

### iLumos

**Driver:** `ilumos`

**MIPI CSI-2 lanes:** 4

**Video modes:**

| Resolution | Pixel format | V4L2 format |
|------------|--------------|-------------|
| 2048 × 2048 | 16-bit raw greyscale | `Y16` |
| 2048 × 1088 | 16-bit raw greyscale | `Y16` |

---

### Microlynx

**Driver:** `microlynx`

**MIPI CSI-2 lanes:** 2

**Video modes:**

| Resolution | Pixel format | V4L2 format |
|------------|--------------|-------------|
| 1024 × 128 | 16-bit raw greyscale | `Y16` |


---

**For additional support or questions, contact the Exosens support team.**
