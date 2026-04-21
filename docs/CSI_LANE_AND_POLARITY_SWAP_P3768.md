# CSI Lane Swap on the Nvidia P3768 Devkit (Jetson Orin Nano/NX)

## Background

The P3768 carrier board (Nvidia Jetson Orin Nano/NX devkit) has a **lane swap**
on the CAM0 connector (J20). This document explains the issue, its consequences
on the device tree, and the differences with the Forecr DSBOARD-ORNXS carrier board.

Source: P3768-A04 schematics, page 18 "CSI CAM CONNECTORS".

## Lane swap on J20 (CAM0)

### Expected routing (normal order)

With standard routing, CSI lanes arrive in this order on the connector:

```
CSI0_D0, CSI0_D1, CSI0_CLK    <- Lane A (brick A, port-index=0)
CSI1_D0, CSI1_D1              <- Lane B (brick B, port-index=1)
```

### Actual routing on P3768 (annotated "LANE SWAP")

On the Nvidia devkit, lane groups A and B are **entirely swapped**:

```
CSI1_D0, CSI1_D1, CSI1_CLK    <- Lane B in upper position
CSI0_D0, CSI0_D1              <- Lane A in lower position
```

The schematic carries the **"LANE SWAP"** annotation at this location.

### Lane swap vs polarity swap

These are two **different** phenomena:

| Phenomenon | Description | Compensation |
|------------|-------------|--------------|
| **Lane swap** | CSI0 and CSI1 lane groups are swapped in position on the connector | `port-index` selection in the device tree |
| **Polarity swap (P/N)** | P and N wires of a differential pair are inverted | `lane_polarity` property in the device tree |

On the P3768, **both** phenomena coexist:

- The **lane swap** causes CSI1_CLK to be the "upper" clock on J20
- The **polarity swap** affects CSI0_D1 and CSI1_D0 (compensated by `lane_polarity = "6"`,
  i.e. binary `0110`). https://nvidia-jetson.piveral.com/jetson-orin-nano/csi-diff-pair-polarity-swap-on-nvidia-jetson-orin-nano-dev-board/

Note: `lane_polarity = "6"` and `tegra_sinterface = "serial_b"` are applied on **all
boards** (including Forecr) for CAM0 cameras, and work correctly in both cases.
Only the `port-index` differs between boards.

**Important**: the polarity swap originates from the **SoM module itself**, not from any
carrier board. The Nvidia Design Guide DG-10931-001 (Figure 10-1, Figure 10-2) explicitly
states:

> *"Note: CSI_0_D1 and CSI_1_D0 have P/N swapped on the module."*

This was first documented in Design Guide v1.0 (December 2022), where the changelog reads:
"Table 10-1 and Figure 10-1: Updated to show swapped P/N on two data lanes".

Since the swap is inherent to the Orin NX/Nano SoM (between the Tegra234 SoC and the
SODIMM edge connector), **all carrier boards** using this module must apply
`lane_polarity = "6"` for CSI0 and CSI1 — this is not specific to the Nvidia devkit
nor to Forecr.

## Consequence on x4 mode

The note on the P3768-A04 schematic page 18 states:

> *"x4 camera support in current software only works with the lower clock lane
> of the x4 clock interface. This means that CSI0_CLK or CSI2_CLK are supported
> for x4 configurations, but not CSI1_CLK or CSI3_CLK."*
>
> *"Since J20 has CSI1_CLK, only a x2 camera interface is supported."*
>
> *"J21 which uses CSI2_CLK can support both x2 or x4 camera interfaces."*

Summary:

| Connector | Nvidia P3768 Devkit | Forecr DSBOARD-ORNXS |
|-----------|---------------------|----------------------|
| **CAM0 (J20)** | x2 only (CSI1_CLK) — iLumos OK | x2 and x4 (CSI0_CLK) — iLumos OK |
| **CAM1 (J21)** | x2 and x4 (CSI2_CLK) | x2 and x4 (CSI2_CLK) |

**Direct consequence**: a 4-lane camera cannot work on CAM0 of the Nvidia devkit.
2-lane cameras (including iLumos) work on CAM0 of both boards.

## Driver behavior: what port-index actually controls

There are **two independent** `port-index` values in the device tree, read by
two different parts of the driver stack.

### port-index in the sensor node (cam_i2cmux endpoint)

Read by `camera_common_parse_ports()` in `camera_common.c` (line 310):

```c
of_property_read_u32(ep, "port-index", &port);
s_data->csi_port = port;
```

Used **only** in `camera_common_dpd_disable/enable()`:

```c
io_idx = s_data->csi_port + i;
tegra_io_pad_power_enable(TEGRA_IO_PAD_CSIA + io_idx);
```

**Role:** selects which CSI IO pad (CSIA, CSIB, CSIC…) to take out of Deep
Power Down when the camera is opened. Does **not** control the NVCSI data path.

### port-index in the NVCSI input endpoint

The NVCSI input endpoint (under `nvcsi@.../channel@N/ports/port@0/endpoint`) uses
`port-index` as the **raw NVCSI port number** (0 = port A, 1 = B, …, 6 = port G,
7 = port H, range 0–7 per `NVCSI_PORT_H`). This is read by the CSI driver and
passed to `csi5_stream_open()`.

### port-index in the VI node (tegra-capture-vi endpoint)

Read by `tegra_vi_get_port_info()` in `vi/channel.c`:

```c
of_property_read_u32(ep, "port-index", &value);
chan->port[0] = value;
```

Then used directly as `setup.csi_stream_id = chan->port[0]` in `vi5_fops.c`.
This is validated in `fusa-capture/capture-vi.c`:

```c
#define MAX_NVCSI_STREAM_IDS  U32_C(0x6)  // valid range: 0–5
if (csi_stream_id >= MAX_NVCSI_STREAM_IDS) {
    dev_err(..., "Invalid NVCSI stream Id\n");  // → NULL deref crash
```

The VI port-index is therefore a **stream ID (0–5)**, not a raw port number.
For T234, `csi5_port_to_stream()` maps raw port → stream:

| NVCSI port | port-index (NVCSI) | port-index (VI) = stream_id |
|---|---|---|
| A | 0 | 0 |
| B | 1 | 1 |
| C | 2 | 2 |
| D | 3 | 3 |
| E | 4 | 4 |
| F | 5 | 4 |
| **G** | **6** | **5** |
| H | 7 | 5 |

> **Key rule for AGX Orin CAM1 (serial_g, CSI 6/7 = NVCSI port G):**
> NVCSI endpoint: `port-index = <6>` — VI endpoint: `port-index = <5>`

### Practical consequence

A wrong `port-index` in the **sensor node** powers the wrong IO pad but does
not prevent capture — the data path is determined by the VI/NVCSI `port-index`.
A wrong `port-index` in the **NVCSI node** (raw port) breaks the CSI data path.
A wrong `port-index` in the **VI node** (stream ID) causes a kernel crash at
stream time with "Invalid NVCSI stream Id" if the value ≥ 6.

Both values must still be correct for clean operation (proper pad power
management), but only the VI/NVCSI values are critical for functionality.

## Device tree impact

### port-index (NVCSI routing)

The `port-index` designates the NVCSI brick used by the CSI hardware.
Due to the lane swap, the active clock on CAM0 is CSI1's clock (brick B).

```
// tegra234-p3767-camera-common-eg-cams-dione.dtsi

// CAM0 - VI capture
port@0 / endpoint {
#ifdef DSBOARD_ORNXS
    port-index = <0>;    // Brick A (CSI0_CLK) - Forecr
#else
    port-index = <1>;    // Brick B (CSI1_CLK) - Nvidia devkit
#endif
    bus-width = <2>;
};

// CAM0 - NVCSI
channel@0 / port@0 / endpoint@0 {
#ifdef DSBOARD_ORNXS
    port-index = <0>;    // Brick A - Forecr
#else
    port-index = <1>;    // Brick B - Nvidia devkit
#endif
    bus-width = <2>;
};

// CAM1 - identical on both boards
port@1 / endpoint {
    port-index = <2>;    // Brick C (CSI2_CLK)
    bus-width = <2>;
};
```

### lane_polarity (P/N inversion)

The `lane_polarity` property compensates for differential pair polarity
inversion. It is defined in each camera's modes:

```
// CAM0 - all boards (no #ifdef, same values for Nvidia devkit and Forecr)
mode0 {
    lane_polarity = "6";        // binary 0110: CSI0_D1 and CSI1_D0 inverted
    tegra_sinterface = "serial_b";
};

// CAM1 - all boards (no polarity swap needed)
mode0 {
    // no lane_polarity (or "0")
    tegra_sinterface = "serial_c";
};
```

`lane_polarity = "6"` is applied on **all boards** for CAM0 (including Forecr)
because the P/N swap is inherent to the SoM module (see Design Guide DG-10931,
Figure 10-1: "CSI_0_D1 and CSI_1_D0 have P/N swapped on the module").

### tegra_sinterface

| Port | All boards |
|------|------------|
| CAM0 | `serial_b` |
| CAM1 | `serial_c` |

Note: `tegra_sinterface` is **not** conditionally compiled. Both Nvidia devkit
and Forecr use `serial_b` for CAM0. The only board-specific difference is `port-index`.

## Special case: iLumos (2-lane camera)

The iLumos uses 2 MIPI lanes (`bus-width = <2>`), therefore x2 mode.
It works on CAM0 of all boards (devkit and Forecr) and on CAM1.

### CAM1 (J21) - works on all boards

The `ilumos_c@30` node (CAM1) is defined unconditionally:

```
ilumos_c@30 {
    compatible = "exosens,ilumos";
    status = "disabled";    // enabled by cam1-ilumos overlay

    mode0 {
        num_lanes = "2";
        tegra_sinterface = "serial_c";
        // no lane_polarity
    };

    ports / port@0 / endpoint {
        port-index = <2>;   // Brick C (CSI2_CLK)
        bus-width = <2>;
    };
};
```

### CAM0 - all boards

The `ilumos_b@30` node (CAM0) is present on all boards. Like other 2-lane
cameras, only `port-index` differs due to the devkit lane swap:

```
ilumos_b@30 {
    compatible = "exosens,ilumos";
    status = "disabled";    // enabled by cam0-ilumos overlay

    mode0 {
        num_lanes = "2";
        tegra_sinterface = "serial_b";
        lane_polarity = "6";    // P/N swap on SoM, all boards
    };

    ports / port@0 / endpoint {
#ifdef DSBOARD_ORNXS
        port-index = <0>;   // Brick A (CSI0_CLK) - Forecr
#else
        port-index = <1>;   // Brick B (CSI1_CLK) - Nvidia devkit (lane swap)
#endif
        bus-width = <2>;
    };
};
```

## Device tree values summary by board

### Nvidia P3768 Devkit

| | CAM0 (J20) | CAM1 (J21) |
|--|------------|------------|
| `port-index` | **1** (brick B) | **2** (brick C) |
| `tegra_sinterface` | `serial_b` | `serial_c` |
| `lane_polarity` | `"6"` (0b0110) | _(none)_ |
| Max mode | **x2** | **x4** |
| iLumos | Supported (x2) | Supported (x2) |

### Forecr DSBOARD-ORNXS

| | CAM0 | CAM1 |
|--|------|------|
| `port-index` | **0** (brick A) | **2** (brick C) |
| `tegra_sinterface` | `serial_b` | `serial_c` |
| `lane_polarity` | `"6"` (0b0110) | _(none)_ |
| Max mode | **x4** | **x4** |
| iLumos | Supported | Supported |

## Related files

- `sources/common/source/hardware_32+/nvidia/platform/t23x/p3768/kernel-dts/tegra234-p3767-camera-common-eg-cams-dione.dtsi`
  Common base with `#ifdef DSBOARD_ORNXS` for `port-index` and `ilumos_b@30`
- `sources/common/source/hardware_32+/nvidia/platform/t23x/p3768/kernel-dts/tegra234-p3767-camera-p3768-eg-cam0-ilumos.dts`
  CAM0 iLumos overlay (compiled for Forecr, blocked at runtime on Nvidia)
- `sources/common/source/hardware_32+/nvidia/platform/t23x/p3768/kernel-dts/tegra234-p3767-camera-p3768-eg-cam1-ilumos.dts`
  CAM1 iLumos overlay (works on all boards)
- `sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_set.sh`
  Runtime script with x4/port 0 validation
