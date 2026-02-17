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
| **CAM0 (J20)** | x2 only (CSI1_CLK) | x2 and x4 (CSI0_CLK) |
| **CAM1 (J21)** | x2 and x4 (CSI2_CLK) | x2 and x4 (CSI2_CLK) |

**Direct consequence**: a 4-lane camera such as iLumos cannot work on
CAM0 of the Nvidia devkit, but works on CAM0 of the Forecr board.

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

## Special case: iLumos (4-lane camera)

The iLumos requires 4 MIPI lanes (`bus-width = <4>`), therefore x4 mode.

### CAM1 (J21) - works on all boards

The `ilumos_c@30` node (CAM1) is defined unconditionally:

```
ilumos_c@30 {
    compatible = "exosens,ilumos";
    status = "disabled";    // enabled by cam1-ilumos overlay

    mode0 {
        num_lanes = "4";
        tegra_sinterface = "serial_c";
        // no lane_polarity
    };

    ports / port@0 / endpoint {
        port-index = <2>;   // Brick C (CSI2_CLK) - supports x4
        bus-width = <4>;
    };
};
```

### CAM0 - Forecr only

The `ilumos_b@30` node (CAM0) is protected by `#ifdef DSBOARD_ORNXS`:

```
#ifdef DSBOARD_ORNXS
ilumos_b@30 {
    compatible = "exosens,ilumos";
    status = "disabled";    // enabled by cam0-ilumos overlay

    mode0 {
        num_lanes = "4";
        tegra_sinterface = "serial_b";
        lane_polarity = "6";
    };

    ports / port@0 / endpoint {
        port-index = <0>;   // Brick A (CSI0_CLK) - x4 possible on Forecr
        bus-width = <4>;
    };
};
#endif
```

### Runtime protection

In addition to the compile-time guard (`#ifdef`), the
`eg_dt_camera_config_set.sh` script refuses to apply the iLumos overlay on port 0
if the board is not a Forecr:

```
Error: iLumos requires 4 MIPI lanes (x4) which is not supported on port 0 of nvidia-orin-nano.
On Nvidia devkit, CAM0 (J20) has a lane swap and uses CSI1_CLK, limiting it to x2.
Use port 1 (CAM1/J21) which supports x4 via CSI2_CLK.
```

## Device tree values summary by board

### Nvidia P3768 Devkit

| | CAM0 (J20) | CAM1 (J21) |
|--|------------|------------|
| `port-index` | **1** (brick B) | **2** (brick C) |
| `tegra_sinterface` | `serial_b` | `serial_c` |
| `lane_polarity` | `"6"` (0b0110) | _(none)_ |
| Max mode | **x2** | **x4** |
| iLumos | **Not supported** | Supported |

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
