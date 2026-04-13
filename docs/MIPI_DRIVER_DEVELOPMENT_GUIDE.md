# MIPI Driver Development Guide

This guide covers the common development scenarios for Exosens MIPI camera drivers on NVIDIA Jetson platforms. It provides step-by-step procedures with the exact files to modify.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Scenario A: Adding a new camera to an existing BSP version](#scenario-a-adding-a-new-camera-to-an-existing-bsp-version)
- [Scenario B: Porting a camera to another existing BSP version](#scenario-b-porting-a-camera-to-another-existing-bsp-version)
- [Scenario C: Porting to a new hardware platform](#scenario-c-porting-to-a-new-hardware-platform)
- [Scenario D: Adding support for a new Nvidia BSP version](#scenario-d-adding-support-for-a-new-nvidia-bsp-version)
- [Reference: Device tree differences between L4T 32+/35.x and 36.x](#reference-device-tree-differences-between-l4t-3235x-and-36x)

---

## Architecture Overview

### Source organization

```
sources/
├── common/                             # Shared across ALL L4T versions
│   ├── Linux_for_Tegra/               # Target scripts (config_set, config_get, etc.)
│   │   ├── rootfs/opt/eg/             # Exosens tools (jetson-io, docs)
│   │   └── rootfs/usr/bin/            # User scripts
│   └── source/
│       ├── hardware_36+/              # Device tree overlays for L4T 36.x+
│       ├── hardware_32+/              # Device tree overlays for L4T 32.x-35.x
│       │   ├── nvidia/platform/t210/porg/kernel-dts/    # Jetson Nano overlays
│       │   ├── nvidia/platform/t19x/jakku/kernel-dts/   # Xavier NX overlays
│       │   ├── nvidia/platform/t23x/concord/kernel-dts/ # AGX Orin 35.x overlays
│       │   ├── nvidia/platform/t23x/p3768/kernel-dts/   # Orin NX/Nano overlays
│       │   └── nvidia/platform/t18x/quill/kernel-dts/   # TX2/TX2i/TX2 NX overlays
│       └── nvidia-oot/               # Camera kernel drivers (.c, .h)
│           └── drivers/media/i2c/     # V4L2 sensor drivers
│
├── <version>/                          # Version-specific files
│   ├── Linux_for_Tegra/               # Generic (Nvidia) boards
│   │   └── source/                    # Kconfig, Makefile, defconfig
│   ├── Linux_for_Tegra_t210/          # SoM-specific (32.x only) — Jetson Nano/porg
│   ├── Linux_for_Tegra_t186/          # SoM-specific (32.x only) — Jetson TX2/quill
│   └── Linux_for_Tegra_<vendor>/      # Vendor-specific additions
│       └── source/                    # Vendor defconfigs, Makefiles, DT
```

### Build system layering and 3-way merge

When running `./l4t_copy_sources.sh -v <version> [-s <som>] [-V <vendor>]`, sources are copied in layers:

1. **Layer 1**: `sources/common/` — shared Exosens files
2. **Layer 2**: `sources/<version>/Linux_for_Tegra/` — version-specific generic files
3. **Layer 3** *(32.x only, when `-s <som>` is given)*: `sources/<version>/Linux_for_Tegra_<som>/` — SoM-specific files (e.g., `Linux_for_Tegra_t186/`, `Linux_for_Tegra_t210/`)
4. **Layer 4** *(vendor only)*: `sources/<version>/Linux_for_Tegra_<vendor>/` — vendor-specific files

When multiple layers modify the same file (e.g., a Makefile), a **3-way merge** is performed using the original Nvidia BSP as the common ancestor. This means:
- **You only need to modify files in `Linux_for_Tegra/` (generic)**. SoM- and vendor-specific Makefiles will automatically inherit additions via the merge.
- Only add files to `Linux_for_Tegra_<som>/` or `Linux_for_Tegra_<vendor>/` when the SoM or vendor needs **different** content (e.g., SoM-specific BSP archives, vendor defconfigs, device trees).

**SoM support (32.x only):** L4T 32.x targets two SoMs via the `-s/--som` flag:
- `t210` — Jetson Nano / porg (tegra210): has device tree overlays, supports all cameras except Y16
- `t186` — Jetson TX2 / TX2i / TX2 NX (tegra186): has device tree overlays (`tegra186-camera-eg-*`) and kernel modules (ilumos, microlynx, dione_ir, eg-ec-mipi)

For L4T 35.x and 36.x, the SoM is always Orin-family and no `-s` flag is needed.

### eg_config.yaml structure

`eg_config.yaml` is the single source of truth for the build system. It contains the following top-level sections:

| Section | Purpose |
|---------|---------|
| `versions` | L4T version registry: `jetpack` version, BSP download URLs, toolchain, vendor list, `platform_ids`, `vendor_soms`, `sources_by_som` |
| `soms` | SoM definitions: display name, supported L4T version families (e.g. `32.x only`) |
| `vendors` | Vendor definitions: list of carriers, default carrier |
| `carriers` | Carrier board definitions: defconfig name, directory suffix |
| `pixel_format_map` | Maps pixel format names (`Y16`, `RGB888`, …) to DT field values (`mode_type`, `pixel_phase`, `csi_pixel_bit_depth`) |
| `platform_restrictions` | Per-platform unsupported formats (e.g. `nano_t210` cannot do `Y16`) |
| `dtsi_platforms` | DTSI files to verify: path relative to `sources/common/source/`, `num_cams`, associated `platform_ids`, EC overlay pattern |
| `cameras` | Camera specifications: resolutions, data lanes, modes, DT timing fields (`line_length`, `pix_clk_hz`, …) |

Within a `versions` entry:
- `jetpack` — corresponding JetPack SDK version (e.g. `"6.2.1"`); included in the generated Debian package name as `jp<version>`
- `vendor_soms` — maps each vendor to its list of SoMs (used to enumerate packages for 32.x)
- `sources_by_som` — maps each SoM to its source archive subdirectory (used by `l4t_prepare.sh` to download the correct BSP)

The last four sections feed `tools/verify_dtsi_structure.py`, which cross-checks every DTSI file against the expected modes and DT field values on every build.

`pixel_format_map` and `platform_restrictions` are global and version-independent. `dtsi_platforms` and `cameras` are also global — they describe the shared DTSI files in `sources/common/source/`, not per-version files.

After any scenario that adds or validates camera support, update `deployment_matrix_data.yaml` to record `tested` entries for the verified (platform, camera, L4T version) combinations. Until then, the deployment matrix shows ⚠️ `theoretically_supported` for combinations derived from `platform_ids`.

### Device tree file conventions

| Element | L4T 32.x/35.x | L4T 36.x |
|---------|---------------|----------|
| Common source | `sources/common/source/hardware_32+/` | `sources/common/source/hardware_36+/` |
| DT path (Orin NX/Nano) | `.../platform/t23x/p3768/kernel-dts/` | `.../t23x/nv-public/overlay/` |
| Common DTSI | `tegra234-p3767-camera-common-eg-cams-dione.dtsi` | Same filename |
| Per-camera overlays | `tegra234-p3767-camera-p3768-eg-cam<N>-<camera>.dts` | Same naming convention |
| Forecr variant DTS | `tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dts` | Same naming convention |

The Forecr variant DTS defines `DSBOARD_ORNXS` before including the common DTSI, enabling conditional sections for Forecr hardware.

---

## Scenario A: Adding a new camera to an existing BSP version

This scenario covers adding an entirely new camera type (e.g., "Microlynx") that has never been supported.

### Step 1: Kernel driver

Create the V4L2 sensor driver in `sources/common/source/nvidia-oot/drivers/media/i2c/<camera>.c`.

The driver must:
- Register with a unique compatible string (e.g., `"exosens,microlynx"`)
- Implement V4L2 subdev operations via the tegracam framework
- Expose sysfs attributes for `eg_dt_camera_config_get.sh`:
  - `model` — camera model name
  - `serial_number` — camera serial number
  - `resolution` — native resolution (e.g., "1024x128")
  - `pixel_format` — pixel format string (e.g., "'Y16 ' (16-bit Greyscale)")

Use an existing driver as template: `ilumos.c` (simple I2C), `microlynx_core.c` (GenCP protocol), `eg_ec_mipi_src.c` (EngineCore).

### Step 2: Driver build integration (per version)

**For L4T 36.x (out-of-tree build):**

Modify `sources/<version>/Linux_for_Tegra/source/nvidia-oot/drivers/media/i2c/Makefile`:

```makefile
# Single-file driver:
obj-m += <camera>.o

# Multi-file driver (e.g., with GenCP library):
<camera>-objs := <camera>_core.o gencp-over-i2c/libunio.o gencp-over-i2c/libunio_extras.o gencp-over-i2c/nb_timer.o gencp-over-i2c/gencp_common.o gencp-over-i2c/gencp_client.o
obj-m += <camera>.o
```

Add inside the `ifdef CONFIG_MEDIA_SUPPORT` block, alongside existing drivers (dione_ir, eg-ec-mipi).

**For L4T 32.x/35.x (in-tree build):**

Three files to modify in `sources/<version>/Linux_for_Tegra/source/public/kernel/nvidia/drivers/media/i2c/`:

1. **Kconfig** — add config entry:
   ```
   config VIDEO_<CAMERA>
       tristate "<Camera> MIPI camera support"
       depends on I2C && VIDEO_V4L2 && VIDEO_V4L2_SUBDEV_API
       select V4L2_FWNODE
       help
           V4L2 sensor driver for Exosens <Camera> MIPI cameras.
   ```

2. **Makefile** — add build rule:
   ```makefile
   obj-$(CONFIG_VIDEO_<CAMERA>) += <camera>.o
   # or for multi-file:
   <camera>-objs := <camera>_core.o gencp-over-i2c/libunio.o ...
   obj-$(CONFIG_VIDEO_<CAMERA>) += <camera>.o
   ```

3. **defconfig** — enable the module in `sources/<version>/Linux_for_Tegra/source/public/kernel/kernel-5.10/arch/arm64/configs/defconfig`:
   ```
   CONFIG_VIDEO_<CAMERA>=m
   ```
   Also enable in all vendor-specific defconfigs (e.g., `dsboard_ornx_defconfig`, `milboard_ornx_defconfig`, etc.) in `Linux_for_Tegra_<vendor>/`.

> **Kernel API compatibility (32.x — kernel 4.9):** The 32.x kernel (4.9) does not have `timer_setup()` / `from_timer()` (added in kernel 4.15). If the driver or a library it uses (e.g., `gencp-over-i2c/nb_timer.c`) uses these APIs, guard them with:
> ```c
> #include <linux/version.h>
> #if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 15, 0)
>     timer_setup(&t, cb, 0);
> #else
>     setup_timer(&t, cb, (unsigned long)data);
> #endif
> ```
> The callback signature also differs: `void cb(struct timer_list *t)` for 4.15+, `void cb(unsigned long data)` for older kernels.

### Step 3: Device tree — common DTSI

Add camera sensor nodes to the common DTSI file for each supported hardware family.

For Orin NX/Nano (T23x), the common DTSI files are:
- **L4T 36.x**: `sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay/tegra234-p3767-camera-common-eg-cams-dione.dtsi`
- **L4T 32.x/35.x**: `sources/common/source/hardware_32+/nvidia/platform/t23x/p3768/kernel-dts/tegra234-p3767-camera-common-eg-cams-dione.dtsi`

Add nodes for **each camera port** (CAM0 and CAM1), inside the `cam_i2cmux` block:
- Under `i2c@0` (CAM0): `<camera>_b@<i2c_addr>` — after existing camera nodes
- Under `i2c@1` (CAM1): `<camera>_c@<i2c_addr>` — after existing camera nodes

Each camera node must define:
- `compatible`, `reg` (I2C address), `status = "disabled"` (enabled by overlay)
- `sensor_model` (for identification)
- One or more `mode` sub-nodes with MIPI configuration
- A `ports/port@0/endpoint` with `port-index`, `bus-width`, and `remote-endpoint`

**Port-index rules:**
- CAM0 on Forecr boards (`#ifdef DSBOARD_ORNXS`): `port-index = <0>`
- CAM0 on Nvidia devkit: `port-index = <1>`
- CAM1 (all boards): `port-index = <2>`

**Special case for x4 cameras on CAM0:** If the camera requires 4 MIPI lanes, the entire CAM0 node must be guarded by `#ifdef DSBOARD_ORNXS`, because the Nvidia devkit CAM0 only supports x2 (due to the CSI lane swap). See [CSI_LANE_AND_POLARITY_SWAP_P3768.md](CSI_LANE_AND_POLARITY_SWAP_P3768.md).

**Endpoint remote-endpoint references:**
- CAM0: `remote-endpoint = <&eg_cams_csi_in0>` (36.x) or `<&csi_in0>` (32.x t186/quill) or `<&rbpcv2_imx219_csi_in0>` (32+/35.x t210/porg)
- CAM1: `remote-endpoint = <&eg_cams_csi_in1>` (36.x) or `<&csi_in1>` (32.x t186/quill) or `<&rbpcv2_imx219_csi_in1>` (32+/35.x t210/porg)

> **Note t186 (quill):** `csi_in0`/`csi_in1` are labels already present in the base DTB `__symbols__` (see [below](#csi-endpoint-remote-endpoint-labels)). Do NOT create new labels for these existing nodes — use the base DTB labels directly.

### Step 4: Device tree — per-port overlays

Create two overlay DTS files per camera, one for each port:

```
tegra234-p3767-camera-p3768-eg-cam0-<camera>.dts   # Port 0
tegra234-p3767-camera-p3768-eg-cam1-<camera>.dts   # Port 1
```

Place them in the same directory as the common DTSI.

The `overlay-name` must follow: `"Exosens Cameras. CAM<N>:<DisplayName>"` (e.g., `"Exosens Cameras. CAM0:Microlynx"`).

Each overlay must:
1. Set `bus-width` on the VI capture endpoint
2. Set `bus-width` and `remote-endpoint` on the NVCSI channel endpoint
3. Disable Dione cameras on the same port
4. Enable the new camera node on the same port
5. Update `tegra-camera-platform` module drivernode (devname, proc-device-tree)
6. *(36.x only)* Disable IMX477 and IMX219 on the same port

See the [DT differences reference](#reference-device-tree-differences-between-l4t-3235x-and-36x) for exact target-path formats.

### Step 5: Device tree Makefile (per version)

Add dtbo build targets to the version-specific overlay Makefile:

**L4T 36.x:** `sources/<version>/Linux_for_Tegra/source/hardware/nvidia/t23x/nv-public/overlay/Makefile`

**L4T 32.x/35.x:** `sources/<version>/Linux_for_Tegra/source/public/hardware/nvidia/platform/t23x/p3768/kernel-dts/Makefile`

```makefile
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-<camera>.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-<camera>.dtbo
```

### Step 6: Target scripts

**`sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_set.sh`:**

Add to `CAMERA_LANES`:
```bash
[<Camera>]="<Camera>"
[<camera>]="<Camera>"    # case-insensitive alias
```

If the camera requires x4 MIPI lanes, add to `CAMERA_X4`:
```bash
[<Camera>]=1
[<camera>]=1
```

**`sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_get.sh`:**

Add to `CAMERA_DATABASE`:
```bash
"<camera>:<i2c_addr>:<camera>_([a-h])@<i2c_addr>:<DisplayName>:<mipi_lanes>"
```

### Step 7: Build scripts (host)

**`l4t_gen_delivery_package.sh`** — add camera type normalization in postinst:
```bash
*<Camera>*|*<camera>*) cam_type="<Camera>" ;;
```

### Step 8: Update eg_config.yaml

The DTSI verification tool (`verify_dtsi_structure.py`) and the deployment matrix both derive their data from `eg_config.yaml`. Three sections may need updating:

**`pixel_format_map`** — only if the camera uses a pixel format not already listed (e.g., a new raw depth). Add an entry mapping the format name to its DT fields:

```yaml
pixel_format_map:
  <FORMAT>: {mode_type: "raw", pixel_phase: "<phase>", csi_pixel_bit_depth: <N>}
```

**`cameras`** — add a complete entry describing every resolution and mode the camera exposes:

```yaml
cameras:
  <camera_id>:
    name: "<Display Name>"
    dt_node_label_prefix: "<camera>_cam"   # matches label in DTSI: <camera>_cam0, _cam1, …
    resolutions:
      - res: "<W>x<H>"
        active_w: <W>
        active_h: <H>
        data_lanes: <N>
        discontinuous_clk: "no"            # or "yes"
        modes:
          - pixel_format: "<FORMAT>"       # must exist in pixel_format_map
            line_length: <value>
            pix_clk_hz: <value>
            csi_clock_mhz: <value>
```

For EC-based cameras (EngineCore), also add:
```yaml
    ec_overlay_variant: "1-lane"           # or "2-lanes"
    ec_dtsi_mode_labels: [EC_MODE_WxH_FORMAT, …]   # comment labels in the eg_ec node
```

**`dtsi_platforms`** — only if a new DTSI file was created for a new hardware family (Scenario C). For an existing platform, no change is needed here.

Once updated, the next build will run `verify_dtsi_structure.py` automatically and report any mismatch between the DTSI and `eg_config.yaml`. Use `--no-verify-dtsi` to skip this check during active DT development.

### Step 9: Build

```bash
./l4t_make.sh -v <BSP version>

# For 32.x, build once per SoM:
./l4t_make.sh -v 32.7.x -s t210
./l4t_make.sh -v 32.7.x -s t186
```

---

## Scenario B: Porting a camera to another existing BSP version

This is the most common scenario: a camera already works on one L4T version family (e.g., 32+/35.x) and needs to be added to another (e.g., 36.x).

### Prerequisites

- The camera driver exists in `sources/common/source/nvidia-oot/drivers/media/i2c/`
- The camera nodes exist in the common DTSI for the source version
- The camera overlays exist for the source version
- The target scripts already support the camera

### Step 1: Identify what exists and what's missing

Check which files already exist for the camera:

```bash
# Check common DTSI for target version family
grep -l "<camera>" sources/common/source/hardware_36+/.../*.dtsi
grep -l "<camera>" sources/common/source/hardware_32+/.../*.dtsi

# Check overlay DTS files
ls sources/common/source/hardware_36+/.../*<camera>*.dts
ls sources/common/source/hardware_32+/.../*<camera>*.dts

# Check driver Makefile for target version
grep "<camera>" sources/<target_version>/Linux_for_Tegra/source/.../i2c/Makefile
```

### Step 2: Add camera nodes to the target DTSI

Copy the camera node definitions from the source DTSI and adapt them for the target format. See the [DT differences reference](#reference-device-tree-differences-between-l4t-3235x-and-36x) for the exact changes.

Key adaptations when porting from 32+/35.x to 36.x:
- `remote-endpoint`: change from `<&rbpcv2_imx219_csi_in0>` (t210/porg) or `<&csi_in0>` (t186/quill) to `<&eg_cams_csi_in0>` (CAM0); same pattern for CAM1
- The rest of the node properties (modes, lanes, polarity, etc.) remain identical

Insert the new nodes in the `cam_i2cmux` block:
- After `eg_ec_b@16` in `i2c@0` (CAM0)
- After `eg_ec_c@16` in `i2c@1` (CAM1)

### Step 3: Create overlay DTS files for the target version

Copy existing overlays from the source version and adapt target-paths.

Key adaptations when porting from 32+/35.x to 36.x:

| Element | L4T 32+/35.x | L4T 36.x |
|---------|-------------|----------|
| Include | `#include <dt-common/jetson/tegra234-p3767-0000-common.h>` | `#include <dt-bindings/tegra234-p3767-0000-common.h>` |
| CSI target-path | `/host1x@13e00000/nvcsi@...` | `/bus@0/host1x@13e00000/nvcsi@...` |
| I2C target-path | `/cam_i2cmux/i2c@<N>/...` | `/bus@0/cam_i2cmux/i2c@<N>/...` |
| VI target-path | `/tegra-capture-vi/...` | `/tegra-capture-vi/...` *(unchanged)* |
| Camera platform | `/tegra-camera-platform/...` | `/tegra-camera-platform/...` *(unchanged)* |
| devname bus | bus `8` (CAM0), `9` (CAM1) | bus `9` (CAM0), `10` (CAM1) |
| proc-device-tree | `/proc/device-tree/i2c@31e0000/<node>` | `/proc/device-tree/cam_i2cmux/i2c@<N>/<node>` |
| Disable others | Only Dione | Dione + IMX477 + IMX219 |

### Step 4: Add dtbo targets to the Makefile

Add entries to the version-specific overlay Makefile (see [Scenario A Step 5](#step-5-device-tree-makefile-per-version)).

Only modify `Linux_for_Tegra/` (generic). The vendor Makefile entries will be merged automatically.

### Step 5: Add driver to the Makefile

If the driver is not already in the target version's Makefile, add it (see [Scenario A Step 2](#step-2-driver-build-integration-per-version)).

### Step 6: Update Kconfig and defconfig (L4T 32+/35.x only)

This step is required for in-tree kernel builds (32+/35.x). For 36.x (out-of-tree `nvidia-oot`), skip it.

**Kconfig** — add the `config VIDEO_<CAMERA>` entry in:
```
sources/<version>/Linux_for_Tegra/source/public/kernel/nvidia/drivers/media/i2c/Kconfig
```
Insert after the `config VIDEO_DIONE_IR` block:
```kconfig
config VIDEO_<CAMERA>
	tristate "<Camera> MIPI camera support"
	depends on I2C && VIDEO_V4L2 && VIDEO_V4L2_SUBDEV_API
	select V4L2_FWNODE
	help
		This driver supports <Camera> from Exosens.
		To compile this driver as a module, choose M here: the
		module will be called <camera>.
```

**defconfig** — enable the module in:
```
sources/<version>/Linux_for_Tegra/source/public/kernel/kernel-5.10/arch/arm64/configs/defconfig
```
Add after `CONFIG_VIDEO_EG_EC_MIPI=m`:
```
CONFIG_VIDEO_<CAMERA>=m
```

Also add to all vendor defconfigs in `Linux_for_Tegra_<vendor>/source/public/kernel/kernel-5.10/arch/arm64/configs/`:
```
CONFIG_VIDEO_<CAMERA>=m
```

### Step 7: Build

```bash
./l4t_make.sh -v <BSP version>
```

Note: `eg_config.yaml` does not need to be modified for this scenario — the camera is already in `cameras:`, the target DTSI platform is already in `dtsi_platforms:`, and the target version's `platform_ids` already lists the relevant platforms.

---

## Scenario C: Porting to a new hardware platform

This covers adding support for a new SoM / carrier board combination (e.g., a new Forecr board, or a completely new vendor).

### Step 1: Identify hardware differences

Gather from the carrier board schematics:
- **CSI port mapping**: Which NVCSI bricks are connected to which camera connectors
- **I2C bus**: Which I2C controller connects to the camera, and if there's a MUX (GPIO-controlled)
- **GPIO assignments**: Camera reset, power-down, I2C MUX control pins
- **CSI lane polarity**: Check if there are P/N swaps on the SoM or carrier board (see [CSI_LANE_AND_POLARITY_SWAP_P3768.md](CSI_LANE_AND_POLARITY_SWAP_P3768.md))

### Step 2: Create common device tree files

Copy from an existing platform and adapt to your hardware:

```bash
cd sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay/
# (or hardware_32+/nvidia/platform/t23x/p3768/kernel-dts/ for L4T 32+/35.x)

# 1. Common DTSI — camera sensor node definitions
cp tegra234-p3767-camera-common-eg-cams-dione.dtsi \
   tegra234-pXXXX-camera-common-eg-cams-dione.dtsi

# Edit to match your hardware:
# - CSI port mappings (port-index)
# - I2C bus numbers in cam_i2cmux
# - GPIO assignments (reset, power-down, I2C MUX control)
# - Clock configurations
```

2. **Per-camera overlay DTS files**: Copy existing overlays and adapt target-paths for the new hardware:

```bash
# Dione base overlay
cp tegra234-p3767-camera-p3768-eg-cams-dione.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cams-dione.dts

# Per-port overlays for each camera type
cp tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-1-lane.dts
cp tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-2-lanes.dts
cp tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dts \
   tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-1-lane.dts
# ... repeat for all camera types (iLumos, Microlynx, etc.)
```

3. **Vendor variant DTS** (if needed): Create a file that defines a preprocessor macro before including the common DTSI:

```bash
# Example for a Forecr board
cp tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dts \
   tegra234-pXXXX-camera-<board>-eg-cams-dione.dts

# The file defines e.g. DSBOARD_ORNXS before #include of the common DTSI,
# enabling conditional sections (x4 on CAM0, different GPIO, etc.)
```

### Step 3: Create version-specific build files

1. **Add dtbo targets** to the overlay Makefile:

```makefile
# In sources/<version>/Linux_for_Tegra/source/hardware/.../overlay/Makefile
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cams-dione.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-1-lane.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-2-lanes.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-1-lane.dtbo
dtbo-y += tegra234-pXXXX-camera-pYYYY-eg-cam1-ec-2-lanes.dtbo
# ... all camera type overlays
```

2. **For vendor boards**: add vendor-specific defconfigs if kernel config differs

3. **Update `eg_config.yaml`** to register the new vendor/carrier board and its DTSI:

```yaml
vendors:
  <vendor>:
    carriers: [<carrier_board>]
    default_carrier: <carrier_board>

carriers:
  <carrier_board>:
    defconfig: <vendor>_defconfig
    dir_suffix: <carrier_board>
```

Add the new platform to `dtsi_platforms` so that `verify_dtsi_structure.py` checks the new DTSI on every build:

```yaml
dtsi_platforms:
  <platform_key>:
    dtsi: "hardware_36+/nvidia/t23x/nv-public/overlay/<common-dtsi-file>.dtsi"
    num_cams: <N>                             # number of camera ports
    platform_ids: [<platform_id>, …]          # links to versions.*.platform_ids
    ec_overlay_cam0_pattern: "hardware_36+/.../tegra234-pXXXX-camera-pYYYY-eg-cam0-ec-{variant}.dts"
```

If the new hardware has format restrictions (e.g., no Y16 support), add an entry to `platform_restrictions`:

```yaml
platform_restrictions:
  <platform_id>:
    unsupported_formats: [Y16]
```

Finally, add the new `platform_id` to the `platform_ids` list of each supported L4T version in `versions:`. This automatically populates `theoretically_supported` cells in the deployment matrix for all cameras on this platform.

### Step 4: Update target scripts

- **`eg_dt_camera_config_set.sh`**: If the board uses different x4 lane constraints, update the validation logic
- **`eg_dt_camera_config_get.sh`**: No change needed (camera database is board-independent)

### Step 5: Build

```bash
./l4t_make.sh
```

---

## Scenario D: Adding support for a new Nvidia BSP version

This covers adding support for an entirely new L4T version (e.g., 36.5.0) that is not yet in the build system.

### Step 1: Update eg_config.yaml

Add the new version entry with BSP download URLs, toolchain info, vendor list, and supported platforms:

```yaml
versions:
  "36.5.0":
    jetpack: "6.2.2"
    platform_ids: [agx_orin_devkit, orin_nx_nano_devkit, forecr_ornxs]  # platforms supported by this version
    vendors: [generic, forecr]
    standalone:
      forecr: {dsboard_ornx: true}
      generic: {generic: true}
    sources:
      public:
        filename: public_sources.tbz2
        url: https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/sources/public_sources.tbz2
      release:
        filename: jetson_linux_r36.5.0_aarch64.tbz2
        url: https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/jetson_linux_r36.5.0_aarch64.tbz2
      sample_fs:
        filename: tegra_linux_sample-root-filesystem_r36.5.0_aarch64.tbz2
        url: https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/tegra_linux_sample-root-filesystem_r36.5.0_aarch64.tbz2
    toolchain:
      archive: aarch64--glibc--stable-2022.08-1.tar.bz2
      url: https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v3.0/toolchain/aarch64--glibc--stable-2022.08-1.tar.bz2
      dir: aarch64--glibc--stable-2022.08-1
      prefix: aarch64--glibc--stable-2022.08-1/bin/aarch64-buildroot-linux-gnu-
```

Once `platform_ids` is set, `generate_deployment_matrix.py` automatically populates `theoretically_supported` cells for all cameras on those platforms.

No changes are needed to `dtsi_platforms`, `cameras`, `pixel_format_map`, or `platform_restrictions` — those sections describe the shared DTSI files in `sources/common/source/`, which are version-independent.

Download URLs can be found on the [NVIDIA L4T Archive](https://developer.nvidia.com/embedded/jetson-linux-archive).

### Step 2: Create version-specific directory

```bash
# Start from the closest existing version
cp -r sources/<closest_version>/Linux_for_Tegra sources/<new_version>/Linux_for_Tegra
cp -r sources/<closest_version>/Linux_for_Tegra_<vendor> sources/<new_version>/Linux_for_Tegra_<vendor>
```

The version-specific directory contains only files that differ from `sources/common/`:

```
sources/<new_version>/
├── Linux_for_Tegra/               # Generic (Nvidia) boards
│   └── source/
│       ├── hardware/.../overlay/Makefile    # dtbo-y entries (36.x)
│       ├── nvidia-oot/.../i2c/Makefile      # obj-m entries (36.x)
│       └── public/kernel/.../i2c/           # Kconfig, Makefile, defconfig (32+/35.x)
└── Linux_for_Tegra_<vendor>/      # Vendor-specific additions
    └── source/
        └── ...                    # Vendor defconfigs, Makefiles, DT
```

### Step 3: Adapt version-specific files

Review and update:
- **Makefiles**: Check for any path or target changes in the new BSP
- **Kconfig** (32+/35.x only): Verify config options still exist
- **defconfig** (32+/35.x only): Verify config options
- **Camera platform files**: Check if `camera_common.c`, `sensor_common.c` have API changes
- **Device tree bindings**: Check if new required properties were added

### Step 4: Test the build

```bash
./l4t_make.sh -v <new_version> --prepare --copy-sources --build

# For 32.x, test each SoM separately:
./l4t_make.sh -v <new_version> -s t210 --prepare --copy-sources --build
./l4t_make.sh -v <new_version> -s t186 --prepare --copy-sources --build
```

Fix any compilation errors. Common issues:
- Kernel API changes (function signatures, struct fields)
- Device tree binding changes (new required properties)
- Makefile structure changes (new directories, renamed targets)

### Step 5: Build

```bash
./l4t_make.sh -v <BSP version>

# For 32.x, build once per SoM:
./l4t_make.sh -v <BSP version> -s t210
./l4t_make.sh -v <BSP version> -s t186
```

---

## Reference: Device tree differences between L4T 32+/35.x and 36.x

### Include header

```c
// L4T 32+/35.x:
#include <dt-common/jetson/tegra234-p3767-0000-common.h>

// L4T 36.x:
#include <dt-bindings/tegra234-p3767-0000-common.h>
```

### Target-path prefixes in overlay DTS

| Node type | L4T 32+/35.x | L4T 36.x |
|-----------|-------------|----------|
| VI capture | `/tegra-capture-vi/ports/port@<N>/endpoint` | `/tegra-capture-vi/ports/port@<N>/endpoint` |
| NVCSI (CAM0) | `/host1x@13e00000/nvcsi@15a00000/channel@0/ports/port@0/endpoint@0` | `/bus@0/host1x@13e00000/nvcsi@15a00000/channel@0/ports/port@0/endpoint@0` |
| NVCSI (CAM1) | `/host1x@13e00000/nvcsi@15a00000/channel@1/ports/port@0/endpoint@2` | `/bus@0/host1x@13e00000/nvcsi@15a00000/channel@1/ports/port@0/endpoint@2` |
| I2C MUX (CAM0) | `/cam_i2cmux/i2c@0/<node>` | `/bus@0/cam_i2cmux/i2c@0/<node>` |
| I2C MUX (CAM1) | `/cam_i2cmux/i2c@1/<node>` | `/bus@0/cam_i2cmux/i2c@1/<node>` |
| Camera platform | `/tegra-camera-platform/modules/module<N>/drivernode0` | `/tegra-camera-platform/modules/module<N>/drivernode0` |

### Module drivernode0 properties

```c
// L4T 32+/35.x (CAM0):
devname = "<driver> 8-00<addr>";
proc-device-tree = "/proc/device-tree/i2c@31e0000/<node>";

// L4T 36.x (CAM0):
devname = "<driver> 9-00<addr>";
proc-device-tree = "/proc/device-tree/cam_i2cmux/i2c@0/<node>";

// L4T 32+/35.x (CAM1):
devname = "<driver> 9-00<addr>";
proc-device-tree = "/proc/device-tree/i2c@31e0000/<node>";

// L4T 36.x (CAM1):
devname = "<driver> 10-00<addr>";
proc-device-tree = "/proc/device-tree/cam_i2cmux/i2c@1/<node>";
```

### CSI endpoint remote-endpoint labels

| Endpoint | L4T 32.x t186 (quill) | L4T 32+/35.x t210 (porg) | L4T 36.x |
|----------|-----------------------|--------------------------|----------|
| CSI input CAM0 | `csi_in0` | `rbpcv2_imx219_csi_in0` | `eg_cams_csi_in0` |
| CSI input CAM1 | `csi_in1` | `rbpcv2_imx219_csi_in1` | `eg_cams_csi_in1` |

These are the labels used in `remote-endpoint` references in the camera sensor endpoint.

**Critical — t186:** `csi_in0` and `csi_in1` are labels defined in the base DTB's `__symbols__` node, pointing to the existing `nvcsi@150c0000` endpoints. Multiple stock camera overlays share these same labels (e.g., `imx390_csi_in0`, `liimx274_csi_in0` all alias the same node). When writing an overlay, reference these labels directly — do NOT define new labels for these existing nodes inside an `__overlay__` block, as this creates duplicate phandles on the same node and produces an incorrect DT graph topology.

The nvcsi↔vi output connection (`csi_out0` → `vi_in0`) is already bidirectionally wired in the base DTB and must not be overridden. Only the nvcsi input side (`csi_in0.remote-endpoint` → sensor) needs to be set by the EG overlay.

### Driver Makefile

```makefile
// L4T 32.x/35.x (in-tree, Kconfig-controlled):
obj-$(CONFIG_VIDEO_<CAMERA>) += <camera>.o

// L4T 36.x (out-of-tree, always built):
obj-m += <camera>.o
```

### Overlay: disabling other cameras

L4T 36.x overlays should disable IMX477 and IMX219 nodes in addition to Dione, because these sensors are present in the 36.x common DTSI:

```dts
// Disable IMX477 on same port
fragment@30 {
    target-path = "/bus@0/cam_i2cmux/i2c@<N>/rbpcv3_imx477_<x>@1a";
    __overlay__ { status = "disabled"; };
};
// Disable IMX219 on same port
fragment@31 {
    target-path = "/bus@0/cam_i2cmux/i2c@<N>/rbpcv2_imx219_<x>@10";
    __overlay__ { status = "disabled"; };
};
```

Where `<N>` is `0` (CAM0) or `1` (CAM1), and `<x>` is `a` (CAM0) or `c` (CAM1).

---

**For additional support or questions, contact the Exosens support team.**
