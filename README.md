# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SoM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also provides guidance for integrating the drivers on other L4T versions and carrier boards.

The [MIPI deployment matrix](MIPI_DEPLOYMENT_MATRIX.md) presents an overview of the supported cameras/SoM/carrier boards/L4T versions.

---

## Table of Contents

- [Acronyms](#acronyms)
- [Flashing JetPack on Jetson Orin NX/Nano](#flashing-jetpack-on-jetson-orin-nxnano)
- [Prerequisites for cross-compiling](#prerequisites-for-cross-compiling)
  - [Host PC requirements](#host-pc-requirements)
- [Building, installing, configuring and testing MIPI drivers](#building-installing-configuring-and-testing-mipi-drivers)
  - [Supported L4T versions, SoMs, vendors and carrier boards](#supported-l4t-versions-soms-vendors-and-carrier-boards)
  - [Building the L4T environment](#building-the-l4t-environment)
    - [Source code organization](#source-code-organization)
    - [Building workflow](#building-workflow)
  - [Building MIPI drivers for specific SoMs or carrier boards](#building-mipi-drivers-for-specific-soms-or-carrier-boards)
  - [Installing and configuring the MIPI drivers on the board](#installing-and-configuring-the-mipi-drivers-on-the-board)
    - [Package installation](#package-installation)
    - [Configuring camera ports](#configuring-camera-ports)
  - [Quick start - Testing the camera](#quick-start---testing-the-camera)
- [Notes about Linux boot and device trees](#notes-about-linux-boot-and-device-trees)
  - [Linux boot configuration](#linux-boot-configuration)
  - [Orin NX/Nano CSI lanes issues](#orin-nxnano-csi-lanes-issues)
- [Shell completion](#shell-completion)
- [Camera Format Performance Benchmark](#camera-format-performance-benchmark)
- [Appendix A: Integrating drivers on other L4T versions and carrier boards](#appendix-a-integrating-drivers-on-other-l4t-versions-and-carrier-boards)
- [Appendix B: Adding a new camera type](#appendix-b-adding-a-new-camera-type)
- [Appendix C: Configuring camera ports manually with config-by-hardware.py](#appendix-c-configuring-camera-ports-manually-with-config-by-hardwarepy)
- [Appendix D: Integrating with Vision Components (VC) MIPI patches](#appendix-d-integrating-with-vision-components-vc-mipi-patches)
- [Appendix E: Device tree adaptation for the Forecr DSADDON-MIPI-AGX-6CH](#appendix-e-device-tree-adaptation-for-the-forecr-dsaddon-mipi-agx-6ch)

---

## Acronyms

| Acronym | Full form | Description |
|---------|-----------|-------------|
| **AR24** | — | 32-bit BGRA pixel format code in V4L2 (Blue, Green, Red, Alpha — 8 bits each) |
| **BSP** | Board Support Package | Nvidia's software bundle for a given hardware platform (kernel, bootloader, device trees, tools) |
| **CSI / CSI-2** | Camera Serial Interface (version 2) | MIPI standard defining the electrical and protocol interface between image sensors and host processors |
| **DT** | Device Tree | Hardware description mechanism used by the Linux kernel to enumerate peripherals |
| **DTB** | Device Tree Blob | Compiled binary form of a Device Tree source file |
| **DTBO** | Device Tree Blob Overlay | Partial DTB applied at boot to enable or configure optional hardware (e.g., a camera) |
| **DTS** | Device Tree Source | Human-readable source file describing hardware, compiled into a DTB |
| **DTSI** | Device Tree Source Include | Reusable device tree fragment included by one or more DTS files |
| **EG** | Exosens Group | Exosens — the manufacturer of the cameras referenced in this project |
| **FDT** | Flattened Device Tree | Binary format for device trees passed by the bootloader to the Linux kernel |
| **GPIO** | General Purpose Input/Output | Configurable digital pin used to control or sense external hardware signals |
| **I2C** | Inter-Integrated Circuit | Two-wire serial protocol used to communicate with camera control registers |
| **INITRD** | Initial RAM Disk | Compressed root filesystem image loaded by the bootloader before the real root is mounted |
| **initramfs** | Initial RAM Filesystem | Compressed archive used as an early root filesystem during kernel boot (successor to INITRD) |
| **L4T** | Linux for Tegra | Nvidia's BSP distribution for Jetson platforms, versioned as e.g. 35.5.0 or 36.4.4 |
| **LTS** | Long-Term Support | Ubuntu release designation with an extended security update period (5 years) |
| **MIPI** | Mobile Industry Processor Interface | Industry consortium defining hardware interfaces including CSI-2, D-PHY, and others |
| **PCB** | Printed Circuit Board | The physical board carrying electronic components |
| **PTY** | Pseudo-Terminal | Software interface that emulates a hardware terminal; allocated by `sudo` for each invocation |
| **SoC** | System on Chip | Integrated circuit combining CPU, GPU, memory controllers, and peripheral interfaces |
| **SoM** | System on Module | Compact board embedding a SoC and memory, plugged into a carrier board |
| **V4L2** | Video for Linux 2 | Linux kernel API for video capture and output devices (controls formats, modes, streaming) |
| **Y16** | — | 16-bit greyscale pixel format code in V4L2; used by infrared cameras |
| **YUYV** | — | YUV 4:2:2 packed pixel format (alternating Y, U, Y, V bytes); also written YCbCr 4:2:2 |

---

## Flashing JetPack on Jetson Orin NX/Nano

Before building and installing the MIPI drivers, the board must be flashed with a
supported L4T version (35.6.0 or 36.4.4). Flashing, upgrading and **downgrading** Orin
NX/Nano boards — on NVIDIA devkits and Forecr DSBOARD-ORNXS carriers, SD card or NVMe —
each needs a specific command sequence (downgrading from 36.x to 35.x in particular).

See **[docs/JETSON_FLASHING_GUIDE.md](docs/JETSON_FLASHING_GUIDE.md)** for the per-board
command reference, host prerequisites, and flashing troubleshooting.

---

## Prerequisites for cross-compiling

### Host PC requirements

**Recommended OS:** Ubuntu 22.04 LTS. This version is used for development and compiles all supported L4T versions (32.x, 35.x, 36.x).

**Disk space:** Building a single driver package requires **15–25 GB** of free disk space (L4T BSP sources, toolchain, and build artifacts). As of 2026-04-13, the repository supports 16 Nvidia SDK versions with 2 variants each (32 packages total); compiling the full matrix requires **> 600 GB** of disk space.

**sudo PTY allocation:** The build system calls `sudo` from non-interactive scripts. By default, recent versions of sudo allocate a PTY for each invocation, which can exhaust the system's PTY pool during parallel builds. Disable this for your user:

```bash
echo 'Defaults:$USER !use_pty' | sudo tee /etc/sudoers.d/$USER-notty
sudo chmod 440 /etc/sudoers.d/$USER-notty
```

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

# For kernel module build (OpenSSL headers)
sudo apt install libssl-dev

# For PDF generation of the deployment matrix (optional)
sudo apt install weasyprint

# For DT integration tests (host-side DTB parsing via libfdt)
sudo apt install python3-libfdt
```

---

## Building, installing, configuring and testing MIPI drivers

### Supported L4T versions, SoMs, vendors and carrier boards

Refer to the [MIPI deployment matrix](MIPI_DEPLOYMENT_MATRIX.md) for the complete list of supported configurations.
Also use the `l4t_make.sh --help` command to display this list.

For the rest of this document:
- `<l4t_version>` refers to the L4T version (e.g., `35.5.0`, `36.4.4`)
- `<jp_version>` refers to the JetPack version (e.g., `5.1.3`, `6.2.1`). It is related to the L4T version, and is only mentionned for convenience in the debian package name.
- `<vendor>` refers to the carrier board vendor (`generic` for Nvidia boards, or vendor-specific like `forecr`)

### Building the L4T environment

This section describes the build process using the unified `l4t_make.sh` orchestration script.

#### Source code organization

The Exosens camera driver modifications are organized under `sources/`, split into a shared layer and per-version layers:

```
sources/
├── common/                          # Shared across ALL L4T versions
│   ├── Linux_for_Tegra/
│   │   └── rootfs/usr/bin/          # Target scripts (eg_dt_camera_config_set/get, …)
│   └── source/
│       ├── hardware_36+/            # Device tree overlays for L4T 36.x+
│       ├── hardware_32+/            # Device tree overlays for L4T 32.x–35.x
│       └── nvidia-oot/drivers/media/i2c/   # V4L2 camera kernel drivers (.c, .h)
│
└── <version>/                       # Version-specific files (one directory per L4T version)
    ├── Linux_for_Tegra/             # Generic (Nvidia) boards — Kconfig, Makefile, defconfig
    ├── Linux_for_Tegra_t210/        # SoM-specific, 32.x only — Jetson Nano/porg (T210)
    ├── Linux_for_Tegra_t186/        # SoM-specific, 32.x only — Jetson TX2 (T186)
    └── Linux_for_Tegra_<vendor>/    # Vendor-specific additions (defconfigs, device trees)
```

When `l4t_copy_sources.sh` copies files to the build environment, it applies these layers in order: `common/` first, then version-specific generic, then SoM-specific (32.x only), then vendor-specific. When two layers modify the same file (typically a Makefile), a **3-way merge** is performed against the original Nvidia BSP, so generic changes propagate automatically to vendor variants.

#### Building workflow

The `l4t_make.sh` script orchestrates the entire build process. It uses individual scripts for each build step.

**Before building, use `--help` and `--list`:**

```bash
./l4t_make.sh --help    # full option reference + table of all supported configurations
./l4t_make.sh --list    # show every (version, vendor, SoM, carrier) combination with its exact build arguments
```

**Configuration selection (`-v`, `-V`, `-s`, `-c`):**

Each argument acts as a filter. When an argument is omitted, `l4t_make.sh` iterates over **all** valid values for that dimension:

| Flag | Selects | Default (omitted) |
|------|---------|-------------------|
| `-v / --l4t-version` | L4T version: exact (`35.5.0`), `.x` shorthand (`36.x`, `35.6.x`), or quoted wildcard (`"36.*"`) | all versions |
| `-V / --vendor` | Vendor (`generic`, `forecr`) | all vendors for the matched versions |
| `-s / --som` | SoM (`t210`, `t186`) — 32.x only | all SoMs for the matched version+vendor |
| `-c / --carrier-board` | Carrier board (`dsboard_ornxs`, …) | all carriers for the matched vendor |

For example, `-v 35.3.1` alone would build **both** `generic` and `forecr` for that version. To target a single configuration, specify all four filters explicitly (use the arguments shown by `--list` as a safe starting point).

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

**Step 2: Copy sources**

Copy Exosens sources to the build environment:

```bash
./l4t_make.sh -v <l4t_version> --copy-sources
```
or use the individual script for more logs : 
```bash
./l4t_copy_sources.sh -v <l4t_version>
```

This step:
- Copies source files from `sources/` to the build environment
- Creates a git repository to track modifications against the original Nvidia BSP

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

The generated package: `jetson-l4t-<l4t_version>-jp<jp_version>-eg-cams_<debian_version>_arm64.deb`

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

### Building MIPI drivers for specific SoMs or carrier boards

Some hardware variants require a `-s/--som` or `-V/--vendor` flag to select the correct BSP and device trees.

**Building for Jetson TX2 (t186 SoM) — L4T 32.x only:**

```bash
# Build all steps for t186
./l4t_make.sh -v 32.7.1 -s t186

# Or step by step:
./l4t_make.sh -v 32.7.1 -s t186 --prepare
./l4t_make.sh -v 32.7.1 -s t186 --copy-sources
./l4t_make.sh -v 32.7.1 -s t186 --build
./l4t_make.sh -v 32.7.1 -s t186 --gen-package
```

This generates: `jetson-l4t-32.7.1-jp4.6.1-t186-eg-cams_<debian_version>_arm64.deb`

**Building for Jetson Nano/porg (t210 SoM) — L4T 32.x only:**

```bash
./l4t_make.sh -v 32.7.1 -s t210
```

This generates: `jetson-l4t-32.7.1-jp4.6.1-t210-eg-cams_<debian_version>_arm64.deb`

**Note:** For L4T 35.x and 36.x, the `-s/--som` flag is not needed — those versions target Orin-family SoMs and the SoM is implicit.

Both t186 and t210 packages include kernel modules (dione_ir, eg-ec-mipi, ilumos, microlynx) and device tree overlays (`tegra186-camera-eg-*` / `tegra210-camera-eg-*`).

**The `-c/--carrier-board` option** selects a specific carrier board within a vendor. It has three effects compared to a generic build:

- Uses the carrier's specific kernel defconfig (e.g., `dsboard_ornx_defconfig` instead of the generic `defconfig`), which enables carrier-specific hardware options
- Applies an additional carrier-specific source layer (`sources/<version>/Linux_for_Tegra_<vendor>_<carrier>/`) on top of the vendor layer, using the same 3-way merge mechanism
- Reflects the carrier name in the generated package filename

When a vendor has a single carrier (e.g., `forecr` has only `dsboard_ornxs`), that carrier is used by default and `-c` can be omitted.

**Example: Building for Forecr carrier board with dsboard_ornxs:**

```bash
# Build all steps for forecr/dsboard_ornxs
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornxs

# Or step by step:
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornxs --prepare
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornxs --copy-sources
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornxs --build
./l4t_make.sh -v <l4t_version> -V forecr -c dsboard_ornxs --gen-package

# Or step by step with individual scripts :
./l4t_prepare.sh -v <l4t_version> -V forecr -c dsboard_ornxs
./l4t_copy_sources.sh -v <l4t_version> -V forecr -c dsboard_ornxs
./l4t_build.sh -v <l4t_version> -V forecr -c dsboard_ornxs
./l4t_gen_delivery_package.sh -v <l4t_version> -V forecr -c dsboard_ornxs

```

This generates: `jetson-l4t-<l4t_version>-jp<jp_version>-forecr-dsboard-ornxs-eg-cams_<debian_version>_arm64.deb`

### Installing and configuring the MIPI drivers on the board

#### Package installation

The package was either delivered (see [MIPI deployment matrix](MIPI_DEPLOYMENT_MATRIX.md)) or built locally following the previous steps.

**Standard install** (matching L4T version, no previous package or same-version reinstall):

```bash
sudo dpkg -i jetson-l4t-<l4t_version>-jp<jp_version>-eg-cams_<version>_arm64.deb
```

**Cross-L4T-version install** (e.g. installing a 35.6.1 package on a 35.6.0 board):

> ⚠️ **This must remain exceptional.** Installing a package built for a different L4T version than the one running on the target is not a supported upgrade path. It is only justified in specific situations — for example, when two L4T patch releases share the exact same kernel (e.g. 35.6.0 and 35.6.1 both use `5.10.216-tegra`) and no matching package is yet available. In all other cases, **use the package that matches the target's L4T version**.

The package contains kernel modules compiled for a specific kernel. Two safety checks are enforced:

- **Without `FORCE_INSTALL_EG_CAMS`**: the L4T version must match exactly (strict check).
- **With `FORCE_INSTALL_EG_CAMS=1`**: the L4T check is bypassed, but the kernel version (`uname -r`, stripping any `-eg` suffix) must match the kernel the package was built for. This prevents loading modules built for an incompatible kernel.

When the L4T version differs from the running system and the kernel version matches, use:

```bash
sudo FORCE_INSTALL_EG_CAMS=1 dpkg -i --force-overwrite \
    jetson-l4t-<l4t_version>-jp<jp_version>-eg-cams_<version>_arm64.deb
```

- `FORCE_INSTALL_EG_CAMS=1` — bypasses the L4T version check (verified against kernel instead)
- `--force-overwrite` — allows dpkg to overwrite files from the previously installed package

The previously installed package is automatically removed from the dpkg database a few seconds after installation completes.

**If a package with version ≤ 2.0.0 is already installed**, it does not carry the package-family metadata (`Provides`) needed for automatic cleanup. You must uninstall it manually first:

```bash
# Find and remove the old package (check exact name with: dpkg -l | grep eg-cams)
sudo dpkg --purge <old-package-name>

# Then install normally (or with FORCE if L4T version differs)
sudo dpkg -i jetson-l4t-<l4t_version>-jp<jp_version>-eg-cams_<version>_arm64.deb
```

#### Configuring camera ports

**Note on port numbers:**
- Jetson carrier boards typically include 2 camera ports: "CAM0" and "CAM1"
- For the AGX Orin Auvidea X230D carrier board, port 0 is "CD" and port 1 is "AB" on the PCB
- The `/dev/videoX` device number is NOT the camera port number, but the registration order. Carefully check with the eg_dt_camera_config_get script.

**Note on CAM0 lane swap (Orin NX/Nano):**

Some Orin NX/Nano carrier boards have a CSI data lane swap on the CAM0 connector.
See [docs/CSI_LANE_AND_POLARITY_SWAP_P3768.md](docs/CSI_LANE_AND_POLARITY_SWAP_P3768.md) for technical background.

- **Nvidia Orin NX/Nano devkit**: the lane swap affects CAM0 — handled automatically by `eg_dt_camera_config_set.sh`.
- **Forecr DSBOARD-ORNXS**: the lane swap is corrected on the carrier board — handled automatically by `eg_dt_camera_config_set.sh`.
- **Seeed Studio reComputer J4012**: the lane swap is corrected on the carrier board but **not** detected automatically by `eg_dt_camera_config_set.sh`. Additionally, the silkscreen labeling differs from the Nvidia devkit: the J4012 "CAM0" connector corresponds to "CAM1" on the devkit, and vice-versa.

  To apply the lane-swap fix (support not tested), edit `/boot/extlinux/extlinux.conf` and replace:

  > **Warning: this must be repeated after every use of `eg_dt_camera_config_set.sh`**, as the script overwrites the overlay line.
  ```
  OVERLAYS /boot/tegra234-p3767-camera-eg-cams-dione.dtbo
  ```
  with:
  ```
  OVERLAYS /boot/tegra234-p3767-camera-eg-cams-dione-cam0-lane-swap.dtbo
  ```
  Then reboot.

- **Other carrier boards with corrected lane swap**: if CAM0 produces no video while CAM1 works normally, the carrier board likely corrects the lane swap without automatic detection. Apply the same manual procedure as for the reComputer J4012.

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
  - The **I2C device** is the character device used to send read/write commands to the camera's control registers (firmware updates, configuration, diagnostics)
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

**Advanced / manual configuration:**

`eg_dt_camera_config_set.sh` calls `config-by-hardware.py` internally. For cases not handled automatically (e.g. the Seeed Studio reComputer J4012 CAM0 lane swap) or for manual control over individual overlays, you can invoke `config-by-hardware.py` directly. See [Appendix C](#appendix-c-configuring-camera-ports-manually-with-config-by-hardwarepy) for the full list of available overlays and examples.

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

Consult the support team for assistance with custom modifications.

### Orin NX/Nano CSI lanes issues

The Orin NX/Nano SoM has a CSI differential pair swap (P/N inversion) inherent to the module, and the Nvidia devkit carrier board has an additional CSI data lane swap on CAM0. Some third-party carrier boards correct the lane swap, which requires a different device tree overlay.

See [docs/CSI_LANE_AND_POLARITY_SWAP_P3768.md](docs/CSI_LANE_AND_POLARITY_SWAP_P3768.md) for technical details, and the [Configuring camera ports](#configuring-camera-ports) section for the practical workaround for boards not handled automatically.

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
- SoMs (`-s t186`, `-s t210`) — 32.x builds only
- Vendors (`-V forecr`)
- Carrier boards (`-c dsboard_ornxs`)

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
4. Register the new vendor/carrier board in `eg_config.yaml`

### Scenario D: Adding support for a new Nvidia BSP version

1. Add the new version to `eg_config.yaml` (BSP URLs, toolchain, vendors)
2. Copy the version-specific directory from the closest existing version
3. Adapt Makefiles, Kconfig, defconfig, and device tree bindings as needed
4. Build and fix compilation errors: `./l4t_make.sh -v <new_version> --prepare --copy-sources --build`

### Understanding the source copy workflow

The build system uses a layered source organization with 3-way merging for vendor integration. See the [MIPI Driver Development Guide — Architecture Overview](docs/MIPI_DRIVER_DEVELOPMENT_GUIDE.md#architecture-overview) for details.

When running `./l4t_copy_sources.sh -v <version> [-s <som>] [-V <vendor>]`, sources are copied in layers:

1. `sources/common/` — shared Exosens files (drivers, DT, scripts)
2. `sources/<version>/Linux_for_Tegra/` — version-specific generic files
3. *(32.x only, when `-s <som>` is given)* `sources/<version>/Linux_for_Tegra_<som>/` — SoM-specific files (e.g., `Linux_for_Tegra_t186/`)
4. *(vendor only)* `sources/<version>/Linux_for_Tegra_<vendor>/` — vendor-specific files

When Layers 2, 3, and 4 modify the same file (e.g., a Makefile), a **3-way merge** is performed using the original Nvidia BSP as the common ancestor. This means you only need to modify files in `Linux_for_Tegra/` (generic); SoM- and vendor-specific Makefiles will automatically inherit additions.

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

---

## Appendix C: Configuring camera ports manually with `config-by-hardware.py`

`eg_dt_camera_config_set.sh` (see [Configuring camera ports](#configuring-camera-ports)) is the recommended way to configure camera overlays. It automatically detects the board, selects the appropriate base overlay, handles IMX219/IMX477 conflicts, and validates the result before reboot.

For cases not handled automatically (e.g. the Seeed Studio reComputer J4012 CAM0 lane swap correction, or advanced manual control), configuration can be done directly using the jetson-io tool patched by the Exosens package:

```bash
sudo python /opt/eg/jetson-io/config-by-hardware.py -n <args>
```

Followed by a reboot.

### Listing available Exosens overlays

```bash
sudo python /opt/eg/jetson-io/config-by-hardware.py -l
```

This lists all overlays registered for the current hardware, including Exosens-specific ones.

### Principle

The `-n` command takes one or more `N="overlay-name"` arguments, where `N=2` refers to the CSI camera connector (Jetson 24-pin CSI header). The tool writes the corresponding DTBO paths to the `OVERLAYS` line in `/boot/extlinux/extlinux.conf`.

A correct configuration always consists of:

1. **One base overlay** — mandatory; selects board variant and configures all ports for Dione by default
2. **Zero or more per-port camera overlays** — one for each port that uses a non-Dione camera
3. **Zero or more disable overlays** — required on boards where IMX219/IMX477 sensors are active in the base device tree (handled automatically by `eg_dt_camera_config_set.sh`)

Dione cameras do not require a per-port overlay — they are fully covered by the base overlay.

### Available overlays — Orin NX / Nano (p3768)

**Base overlays — choose exactly one:**

| Overlay name | Use case |
|---|---|
| `"Exosens Cameras"` | Nvidia Orin NX/Nano devkit and compatible boards |
| `"Exosens Cameras for DSBOARD-ORNXS"` | Forecr DSBOARD-ORNXS (Forecr-specific I2C mux GPIO + corrected CAM0 lane swap) |
| `"Exosens Cameras - CAM0 lane swap"` | Boards with corrected CAM0 lane swap but standard devkit I2C mux (e.g. Seeed Studio reComputer J4012) |

**Per-port camera overlays — stack on top of base (0, 1, or 2):**

| Overlay name | Camera(s) | Port |
|---|---|---|
| `"Exosens Cameras. CAM0:EC_1_lane"` | MicroCube, MicroCube640 | CAM0 |
| `"Exosens Cameras. CAM0:EC_2_lanes"` | SmartIR640, Crius1280 | CAM0 |
| `"Exosens Cameras. CAM0:iLumos"` | iLumos | CAM0 |
| `"Exosens Cameras. CAM0:Microlynx"` | Microlynx | CAM0 |
| `"Exosens Cameras. CAM1:EC_1_lane"` | MicroCube, MicroCube640 | CAM1 |
| `"Exosens Cameras. CAM1:EC_2_lanes"` | SmartIR640, Crius1280 | CAM1 |
| `"Exosens Cameras. CAM1:iLumos"` | iLumos | CAM1 |
| `"Exosens Cameras. CAM1:Microlynx"` | Microlynx | CAM1 |

**Disable overlays — add when the base DTB has active IMX nodes:**

| Overlay name | Purpose |
|---|---|
| `"Exosens Cameras. Disable imx219"` | Disable Sony IMX219 nodes (RPi Camera Module v2 reference design) |

### Available overlays — AGX Orin (p3737)

**Base overlays — choose exactly one:**

| Overlay name | Use case |
|---|---|
| `"Exosens Cameras"` | Standard configuration (up to 4 ports) |
| `"Exosens Cameras (global)"` | Dione-only on 35.x base DTBs using NVIDIA global NVCSI endpoint numbering — selected automatically by `eg_dt_camera_config_set.sh` when applicable |
| `"Exosens Cameras - 2 ports"` | AGX Orin boards with only 2 active CSI channels (e.g. Auvidea X230D on L4T 35.1) |

**Per-port camera overlays:** same principle as above; ports go from CAM0 to CAM3 — e.g. `"Exosens Cameras. CAM2:EC_1_lane"`, `"Exosens Cameras. CAM3:EC_2_lanes"`.

**Disable overlays:** `"Exosens Cameras. Disable imx219"` (same as above).

### Examples

Configure all ports for Dione on a standard devkit:

```bash
sudo python /opt/eg/jetson-io/config-by-hardware.py -n 2="Exosens Cameras"
sudo reboot
```

Configure Dione on CAM0 and MicroCube640 on CAM1 (devkit):

```bash
sudo python /opt/eg/jetson-io/config-by-hardware.py -n 2="Exosens Cameras" 2="Exosens Cameras. CAM1:EC_1_lane"
sudo reboot
```

Configure Dione on CAM0 and SmartIR640 on CAM1 (DSBOARD-ORNXS):

```bash
sudo python /opt/eg/jetson-io/config-by-hardware.py -n 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:EC_2_lanes"
sudo reboot
```

Configure Dione on both ports (Seeed Studio reComputer J4012, with CAM0 lane swap correction):

```bash
sudo python /opt/eg/jetson-io/config-by-hardware.py -n 2="Exosens Cameras - CAM0 lane swap"
sudo reboot
```

---

## Appendix D: Integrating with Vision Components (VC) MIPI patches

This appendix describes the changes required to make Exosens camera drivers coexist with the
[VC MIPI kernel patches](https://github.com/VC-MIPI-modules/vc_mipi_nvidia/tree/184-Orin-AGX-DSADDON/patch/kernel_Xavier_36.4.4)
for L4T 36.x (nvidia-oot). These patches modify the Tegra camera framework in ways that are
incompatible with Exosens drivers in their unmodified form.

The patches concerned are:

| Patch file | Framework change | Impact on Exosens drivers |
|---|---|---|
| `0001-Handler-function-ready_to_stream-introduced.patch` | Adds `ready_to_stream` op to sensor ops struct; STREAMON fails with `-ENODEV` if NULL | All `media/i2c` drivers |
| `0001-Added-cropping-position-left-top-to-sensor-image-pro.patch` | Adds `active_l`/`active_t` to `sensor_image_properties`; parsing fails if absent in DT | All camera device tree nodes |
| `0001-Added-implementation-to-set-image-position-and-size-.patch` | `VIDIOC_S_FMT` writes back to `frmfmt` table via a `const`-cast; crashes on `.rodata` | All `media/i2c` drivers |

### Changes required in `media/i2c` drivers

Apply the following two modifications to each Exosens driver source file
(`eg_ec_mipi_src.c`, `dione_ir_src.c`, `ilumos.c`, `microlynx_src.c`).

#### 1 — Remove `const` from the `frmfmt` table

The VC patch `__tegra_channel_set_frame_size()` casts away `const` from `s_data->frmfmt`
and writes to it on every `VIDIOC_S_FMT` call (triggered by GStreamer and `v4l2-ctl`).
Exosens drivers declare their format table as `static const`, placing it in read-only memory
(`.rodata`). The write causes a kernel page fault on ARM64 with `CONFIG_STRICT_MODULE_RWX=y`.

```c
// BEFORE — in every driver, e.g. eg_ec_mipi_src.c:
static const struct camera_common_frmfmt eg_ec_mipi_frmfmt[] = { ... };

// AFTER — remove const:
static struct camera_common_frmfmt eg_ec_mipi_frmfmt[] = { ... };
```

The `frmfmt_table` pointer type (`const struct camera_common_frmfmt *`) does not need to change —
a non-`const` array is safely assigned to a `const` pointer.

#### 2 — Add a `ready_to_stream` no-op

The VC patch adds `int (*ready_to_stream)(struct tegracam_device *tc_dev)` to
`camera_common_sensor_ops` and calls it before STREAMON. A `NULL` pointer results in
`-ENODEV` being returned (preventing streaming) or a NULL dereference in some call paths.

Add a no-op implementation and register it in the sensor ops struct:

```c
static int eg_ec_mipi_ready_to_stream(struct tegracam_device *tc_dev)
{
    return 0;
}

static struct camera_common_sensor_ops eg_ec_mipi_common_ops = {
    /* ... existing fields ... */
    .ready_to_stream = eg_ec_mipi_ready_to_stream,
};
```

Apply the same pattern (`<driver>_ready_to_stream`) to every other Exosens driver.

### Changes required in device tree overlays

The VC patch `0001-Added-cropping-position-left-top-to-sensor-image-pro.patch` modifies
`sensor_common_parse_image_props()` to read two new mandatory properties from each `mode*`
node. The function returns an error (camera probe fails) if either property is absent.

Add `active_l` and `active_t` to **every mode node** in every Exosens camera DTSI/DTS:

```dts
mode0 {
    /* ... existing properties ... */
    active_l = "0";   /* left crop offset — must be present */
    active_t = "0";   /* top crop offset  — must be present */
};
```

These properties are required for all formats and all resolutions. The value `"0"` disables
cropping, which is the correct setting for Exosens cameras (no hardware cropping support).

> **Note:** The VC DT also contains sensor-level properties specific to VC cameras
> (`trigger_mode`, `io_mode`, `reset-gpios`, `physical_w`, `physical_h`,
> `set_mode_delay_ms`). These are **not** required for Exosens drivers and should not be
> added to Exosens device tree nodes.

---

## Appendix E: Device tree adaptation for the Forecr DSADDON-MIPI-AGX-6CH

The [Forecr DSADDON-MIPI-AGX-6CH](https://www.forecr.io/products/dsaddon-mipi-agx-6ch) is a
MIPI CSI expansion board for AGX Orin that provides 6 simultaneous camera slots (up to 4×2-lane
and 2×4-lane, or 6×2-lane). All cameras share a single AGX Orin I2C root bus and are
multiplexed through a TCA9548 I2C switch. Each camera slot is wired to a dedicated CSI serial
interface on the T234 SoC.

This appendix describes the device tree modifications required to replace the standard
`tegra234-p3737-camera-*` Exosens overlays with a DSADDON-compatible configuration.

### Hardware topology

```
AGX Orin (T234)
 └─ i2c@3180000  ─────────────────────────────────── TCA9548 @ 0x70
                                                       ├─ i2c@0  → Slot 0 sensor    → NVCSI serial_a
                                                       ├─ i2c@1  → Slot 1 sensor    → NVCSI serial_b
                                                       ├─ i2c@2  → Slot 2 sensor    → NVCSI serial_c
                                                       ├─ i2c@3  → Slot 3 sensor    → NVCSI serial_d
                                                       ├─ i2c@4  → Slot 4 sensor    → NVCSI serial_e
                                                       ├─ i2c@5  → Slot 5 sensor    → NVCSI serial_g
                                                       └─ i2c@6  → PCF8574A @ 0x38 (GPIO reset controller)
```

### Slot → I2C / NVCSI mapping

| Slot | TCA9548 channel | Linux I2C bus | NVCSI channel | `tegra_sinterface` | `port-index` |
|------|-----------------|---------------|---------------|--------------------|-------------|
| 0    | `i2c@0`         | 9             | `channel@0`   | `serial_a`         | 0           |
| 1    | `i2c@1`         | 10            | `channel@1`   | `serial_b`         | 1           |
| 2    | `i2c@2`         | 11            | `channel@2`   | `serial_c`         | 2           |
| 3    | `i2c@3`         | 12            | `channel@3`   | `serial_d`         | 3           |
| 4    | `i2c@4`         | 13            | `channel@4`   | `serial_e`         | 4           |
| 5    | `i2c@5`         | 14            | `channel@5`   | `serial_g`         | 6           |

> **Slot 5 note:** `serial_g` maps to `port-index = 6` (skipping `serial_f`/port-index 5, which
> is unavailable on the DSADDON for standard camera use).

### Changes to the common DTSI

The standard `tegra234-p3737-camera-common-eg-cams-dione.dtsi` places sensors directly on
`i2c@31e0000` (CAM0) and `i2c@c240000` (CAM1). For the DSADDON, all sensors move under
`i2c@3180000` through the TCA9548 mux. The NVCSI `channel@N` assignments remain the same
provided you map slots to the same `port-index` as the standard Exosens overlays.

**Add the following infrastructure nodes under `i2c@3180000` in the common DTSI:**

```dts
i2c@3180000 {

    tca9548@70 {
        compatible = "nxp,pca9548";
        reg = <0x70>;
        status = "okay";
        #address-cells = <1>;
        #size-cells = <0>;
        vcc-supply  = <&p3737_vdd_1v8_sys>;
        vif-supply  = <&p3737_vdd_1v8_sys>;
        skip_mux_detect;

        /* GPIO reset controller for camera power-down lines */
        i2c@6 {
            #address-cells = <1>;
            #size-cells = <0>;
            i2c-mux,deselect-on-exit;
            status = "okay";
            reg = <6>;

            pcf8574a_38: pcf8574a@38 {
                compatible = "nxp,pcf8574a";
                reg = <0x38>;
                status = "okay";
                gpio-controller;
                #gpio-cells = <2>;

                pcf8574a_38_outlow {
                    gpio-hog;
                    gpios = <0 0>, <1 0>, <2 0>, <3 0>,
                            <4 0>, <5 0>, <6 0>, <7 0>;
                    output-low;
                };
            };
        };

        /* Slot 0 — serial_a — place your sensor here */
        i2c@0 {
            #address-cells = <1>;
            #size-cells = <0>;
            i2c-mux,deselect-on-exit;
            status = "okay";
            reg = <0>;

            eg_ec_cam0: eg_ec_a@16 {
                /* same node as standard CAM0, except:        */
                /*   tegra_sinterface = "serial_a" (unchanged) */
                /*   add active_l / active_t to all modes      */
                /*   (see Appendix D)                          */
            };
        };

        /* Slot 1 — serial_b */
        i2c@1 { ... };

        /* Slots 2-5 follow the same pattern */
    };
};
```

**Sensor mode nodes** must also contain `active_l = "0"` and `active_t = "0"` when the
system runs VC MIPI patches (see [Appendix D](#appendix-d-integrating-with-vision-components-vc-mipi-patches)).

For **slot 0**, the NVCSI channel configuration (`channel@0`, `port-index = 0`,
`tegra_sinterface = "serial_a"`) is **identical** to the standard Exosens AGX Orin CAM0
configuration. No changes are needed in the NVCSI section of the DTSI for this slot.

For **slots 1–5**, update `port-index` and `tegra_sinterface` in both the sensor `mode*`
nodes and the corresponding `nvcsi@15a00000/channel@N/ports/port@0/endpoint@{2*N}` node:

```dts
/* Example: slot 2 (serial_c, port-index = 2) */
nvcsi@15a00000 {
    channel@2 {
        status = "okay";
        ports {
            port@0 {
                endpoint@4 {                   /* @{port-index * 2} */
                    bus-width    = <2>;        /* adjust per camera */
                    port-index   = <2>;
                    remote-endpoint = <&eg_ec_out2>;
                    status = "okay";
                };
            };
        };
    };
};
```

### Changes to per-camera overlay DTS

The per-camera overlay DTS files (`tegra234-p3737-camera-eg-camN-*.dts`) reference sensor
nodes via `target-path`. Update these paths and the `devname`/`proc-device-tree` strings to
reflect the mux hierarchy:

**Standard path (direct bus):**
```dts
/* CAM0 standard: sensor on i2c@31e0000 — bus 8 */
target-path = "/bus@0/i2c@31e0000/eg_ec_a@16";
devname     = "eg_ec 8-0016";
proc-device-tree = "/proc/device-tree/bus@0/i2c@31e0000/eg_ec_a@16";
```

**DSADDON path (through TCA9548 mux):**
```dts
/* Slot 0: sensor on i2c@3180000 → tca9548@70 → i2c@0 — bus 9 */
target-path = "/bus@0/i2c@3180000/tca9548@70/i2c@0/eg_ec_a@16";
devname     = "eg_ec 9-0016";
proc-device-tree = "/proc/device-tree/bus@0/i2c@3180000/tca9548@70/i2c@0/eg_ec_a@16";
```

The NVCSI `target-path` fragments (`endpoint@0` for slot 0) do **not** need to change,
since the NVCSI channel assignment is identical to the standard CAM0 overlay.

### PCF8574A and reset GPIOs

The PCF8574A node is required to register the GPIO controller that VC camera drivers
reference for their `reset-gpios` property. Exosens drivers do not use reset GPIOs; the
`pcf8574a_38_outlow` hog keeps all lines low (cameras active) at boot. No additional
changes are needed in Exosens sensor nodes for GPIO handling.

---

**For additional support or questions, contact the Exosens support team.**
