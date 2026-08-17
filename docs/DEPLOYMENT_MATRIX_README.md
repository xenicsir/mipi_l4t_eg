# MIPI Camera Deployment Matrix

This document describes how to use, understand, and maintain the MIPI camera deployment matrix.

## 📋 Overview

The deployment matrix shows the compatibility of MIPI thermal cameras with different Jetson platforms and L4T versions.

### Available Formats

- **`MIPI_DEPLOYMENT_MATRIX.md`** — Markdown table (easy to integrate in documentation)
- **`MIPI_DEPLOYMENT_MATRIX.html`** — Standalone HTML (can be viewed in browser, good for sharing with clients)
- **`MIPI_DEPLOYMENT_MATRIX.pdf`** — PDF report (professional distribution format)

All three formats are **automatically generated** from a single source of truth: `deployment_matrix_data.yaml`

## 📊 Understanding the Matrix

### Status Legend

Each cell shows the support status:

| Icon | Status | Meaning |
|------|--------|---------|
| ✅ | **Tested** | Tested and verified on this platform + L4T version |
| ⚠️ | **Theoretically Supported** | Supported by the architecture but not yet tested |
| ❌ | **Not Supported** | Not supported due to hardware or firmware limitations |
| (empty) | **No Data** | Data not yet collected for this combination |

**Acronyms:** EG = Exosens Group

### Platforms

- **Jetson Nano (T210)** — Legacy T210 SoC, supports older cameras only (Dione, MicroCube, Crius, SmartIR)
- **Xavier NX** — T194 SoC, all cameras across 32.x and 35.x L4T versions
- **AGX Orin devkit** — T234 SoC, theoretically supported (not tested in MIPI portage project)
- **AGX Orin Auvidea X230D** — T234 SoC, fully tested with EG cameras
- **Orin NX / Nano devkit** — T234 SoC, fully tested across 35.x and 36.x L4T
- **Forecr DSBOARD ORNXS** — Custom Orin NX board, theoretically supported

### Cameras

- **Dione IR** — FLIR Dione thermal camera (reference implementation)
- **MicroCube640** — VGA thermal camera
- **Crius1280** — LWIR thermal camera
- **SmartIR640** — SmartIR thermal camera
- **iLumos** — Multi-object thermal (core + GenCP architecture)
- **Microlynx** — Multi-object thermal (core + GenCP architecture)

## 🔧 Maintaining the Matrix

### Source of Truth: `deployment_matrix_data.yaml`

The matrix is defined in **YAML format** — a human-readable, machine-parseable format.

**Structure:**

```yaml
platforms:
  - id: orin_nano_devkit
    name: "Orin NX / Nano devkit"
    description: "..."
    l4t_series: "35.x, 36.x"
    som: "Tegra234"
    csi_lanes: 2

cameras:
  dione_ir:
    name: "Dione IR"
    type: "Thermal IR"
    csi_lanes: 2
    i2c_addr: "0x40"

deployment_matrix:
  - platform: orin_nano_devkit
    cameras:
      dione_ir:
        35.3.1: tested
        35.4.1: tested
        36.4: tested
        36.4.3: tested
      ilumos:
        35.3.1: tested
        35.4.1: tested
```

### How to Update the Matrix

#### Scenario 1: Add support for a new L4T version

If you've ported cameras to a new L4T version (e.g., 36.5):

1. Open `deployment_matrix_data.yaml`
2. Find the relevant platform's section in `deployment_matrix:`
3. Add the new L4T version to each camera:

```yaml
deployment_matrix:
  - platform: agx_orin_x230d
    cameras:
      dione_ir:
        36.4.3: tested
        36.4.4: tested
        36.5: tested    # ← Add here
```

#### Scenario 2: Add a new camera model

1. Add the camera definition in `cameras:` section:

```yaml
cameras:
  my_new_camera:
    name: "My New Camera"
    type: "Thermal"
    csi_lanes: 2
    i2c_addr: "0x55"
    notes: "New model, GenCP v2"
```

2. Add to each platform in `deployment_matrix:`:

```yaml
deployment_matrix:
  - platform: xavier_nx
    cameras:
      my_new_camera:
        35.3.1: tested
        35.4.1: tested
        # ... for each L4T version
```

#### Scenario 3: Add a new platform

1. Add platform definition in `platforms:` section:

```yaml
platforms:
  - id: new_platform_id
    name: "New Platform Name"
    description: "Details about the platform"
    l4t_series: "35.x, 36.x"
    som: "SoC type"
    csi_lanes: number
```

2. Add to `deployment_matrix:`:

```yaml
deployment_matrix:
  - platform: new_platform_id
    cameras:
      dione_ir:
        35.3.1: tested
        # ... etc
```

### Regenerating the Matrices

After modifying `deployment_matrix_data.yaml`, regenerate all output formats:

```bash
python3 generate_deployment_matrix.py
```

This creates:
- `MIPI_DEPLOYMENT_MATRIX.md` — Updated Markdown
- `MIPI_DEPLOYMENT_MATRIX.html` — Updated HTML
- `MIPI_DEPLOYMENT_MATRIX.pdf` — Updated PDF (if WeasyPrint is installed)

### Generating PDF (Optional)

To generate PDF reports, install WeasyPrint:

```bash
pip3 install weasyprint
python3 generate_deployment_matrix.py
```

This will automatically generate PDF alongside Markdown and HTML.

## 📝 Important Notes

### Blank Cells = No Data Available

A blank cell means:
- The combination hasn't been tested
- No data has been collected
- **It does NOT mean "not supported"**

`theoretically_supported` cells are **automatically generated** by `generate_deployment_matrix.py` for any (platform, camera, version) combination where the version's `platform_ids` in `eg_config.yaml` includes that platform. You only need to add explicit entries to `deployment_matrix_data.yaml` for `tested` results (or `not_supported` exceptions).

### Hardware and software constraints

Some combinations are impossible:

- **T210 (Nano) cannot support Y16** — *hardware*: the Tegra X1 video input has no 16-bit RAW format (TRM tables 184/185 stop at RAW14)
- **T210 and T186 do not support Y14 either** — *software*: the L4T 32.x kernel has no Y14 entry in its VI format table (`vi2_formats.h`, `vi4_formats.h`) and we deliberately do not add one (obsolete L4T, decision 2026-08-17). On T210 the hardware would handle RAW14; on T186 that is undetermined (no Parker TRM available)
- **iLumos and Microlynx therefore cannot stream on 32.x at all** — every one of their modes is Y14 or Y16. They are marked `not_supported` on `nano_t210` and `tx2_t186`, and their device-tree overlays are not built for those SoMs
- **32.x L4T cannot support 36.x cameras** — Different driver architecture (in-tree vs out-of-tree)

A combination ruled out by `platform_restrictions` needs an explicit `not_supported` entry in `deployment_matrix_data.yaml`: without it the generator would auto-fill `theoretically_supported` from `platform_ids`. Combinations that were simply never exercised stay as empty cells (no data).

### Testing vs. Theoretical Support

- **✅ Tested** = We've flashed, booted, and verified the camera works
- **⚠️ Theoretically Supported** = Architecture supports it, but we haven't tested it
- **❌ Not Supported** = Hardware or firmware makes it impossible

## 🔄 Workflow for Adding New Camera Support

When you add a new camera (e.g., "iLumos"):

1. **Add the version's `platform_ids`** in `eg_config.yaml` — all compatible platforms appear automatically as ⚠️
2. **Test on primary platforms** (e.g., Auvidea X230D, Orin NX devkit)
3. **Add `tested` entries** in `deployment_matrix_data.yaml` for tested combinations

Example progression:

```yaml
# eg_config.yaml — controls which platforms appear in the matrix
"36.4.3":
  platform_ids: [agx_orin_devkit, agx_orin_x230d, orin_nx_nano_devkit, forecr_ornxs]
  # → all cameras on all these platforms appear as ⚠️ automatically

# deployment_matrix_data.yaml — only tested results to add explicitly
- platform: orin_nx_nano_devkit
  cameras:
    ilumos:
      36.4.3: "tested|l4t-36.4.3|ilumos-ornx-l4t-36.4.3.deb"
      36.4.4: "tested|l4t-36.4.4|ilumos-ornx-l4t-36.4.4.deb"
```

## 🎯 For Clients

### Recommended Reading

1. **See which cameras are available for your platform** — Find your SoM row in the matrix
2. **Check the L4T version** — Match your JetPack/L4T version to see what's supported
3. **Contact support if you see ⚠️** — We can test on your specific platform if needed

### Example: "I have Orin NX DevKit with L4T 35.6.0"

Looking at the matrix:
- Platform: **Orin NX / Nano devkit**
- L4T version: **35.6.0**
- Available cameras: All ✅ Tested (Dione, MicroCube640, Crius1280, SmartIR640, iLumos, Microlynx)

## 📚 Related Documentation

- See `claude_porting_runbook.md` for detailed porting procedures
- See individual camera datasheets for specifications

## 🤝 Support

For issues or questions about the matrix:

1. Check if your platform/camera/L4T combination is documented
2. Review the notes for each platform (specific limitations or requirements)
3. Contact support with your exact hardware configuration (SoM, carrier board, L4T version)

---

**Last Updated:** 2026-02-20
**Maintained By:** MIPI Portage Team
**Generated From:** `deployment_matrix_data.yaml`
