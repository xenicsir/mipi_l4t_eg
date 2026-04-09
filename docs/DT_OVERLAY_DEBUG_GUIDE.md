# Step-by-Step Device Tree Overlay Debug Guide (Jetson L4T)

This guide describes the iterative method for debugging a camera DT overlay
that no longer applies correctly after a devicetree modification.
It is project-independent and reusable on any Jetson platform.

---

## Prerequisites

- SSH access to the Jetson target (password or key)
- `fdtoverlay` available on the target (`apt install device-tree-compiler`)
- `dtc` available on both host and target
- The base DTB for the carrier board (in `/boot/dtb/`)
- The camera overlay DTBO to test (in `/boot/`)

---

## Step 1: Compile the DTBO (host)

```bash
# Compile the DT sources (35.x / 36.x)
./l4t_make.sh -v <version> --copy-sources --build -V generic

# For 32.x (t210 SoM — Jetson Nano/porg):
./l4t_make.sh -v <version> -s t210 --copy-sources --build

# For 32.x (t186 SoM — TX2 / TX2i / TX2 NX):
./l4t_make.sh -v <version> -s t186 --copy-sources --build

# Locate the produced DTBO — path depends on SoM:
ls -lh ./<version>/Linux_for_Tegra/rootfs/boot/<overlay>.dtbo          # 35.x/36.x
ls -lh ./<version>/Linux_for_Tegra_t210/rootfs/boot/<overlay>.dtbo     # 32.x t210
ls -lh ./<version>/Linux_for_Tegra_t186/rootfs/boot/<overlay>.dtbo     # 32.x t186
```

**t186 overlay naming:** `tegra186-camera-eg-cams-dione.dtbo`, `tegra186-camera-eg-cam0-*.dtbo`, etc.
Compatible boards: TX2 (`p2597-0000+p3310-1000`), TX2i (`p2597-0000+p3489-0000/0888`), TX2 NX (`p3509-0000+p3636-0001`).

**Expected size:** a complete camera DTBO is typically 15-40 KB.
If the size is abnormally small (<5 KB) or large (>100 KB), check
includes and fragments.

---

## Step 2: Verify phandles in the DTBO (host)

```bash
# Decompile the DTBO and look for invalid phandles
dtc -I dtb -O dts ./<version>/Linux_for_Tegra/rootfs/boot/<overlay>.dtbo 2>/dev/null \
  | grep -E "0xffffffff|0x00000000|<0x00>"
```

**Expected result:** no output.

| Symptom | Probable cause |
|---------|----------------|
| `phandle = <0xffffffff>` | Unresolved label reference (label missing in the same compilation scope) |
| `remote-endpoint = <0x00>` | Cross-fragment phandle: the target label is in another overlay fragment |
| `remote-endpoint = <0xffffffff>` | Label does not exist anywhere in the DTSI/DTS |

**If invalid phandles are detected:** fix the DTSI BEFORE deploying.
See the "Advanced Diagnostics" section at the end.

---

## Step 3: Copy the DTBO to the target

```bash
scp ./<version>/Linux_for_Tegra/rootfs/boot/<overlay>.dtbo \
    <user>@<target_ip>:/tmp/

ssh <user>@<target_ip> \
    "sudo cp /tmp/<overlay>.dtbo /boot/"
```

---

## Step 4: MANDATORY fdtoverlay test (before reboot)

This is the most important step. It validates that the overlay can be
applied to the base DTB without errors, WITHOUT rebooting.

```bash
ssh <user>@<target_ip> \
    "sudo fdtoverlay -i /boot/dtb/<base_dtb>.dtb \
                      -o /tmp/merged.dtb \
                      /boot/<overlay>.dtbo"
```

**Expected result:** no errors, `/tmp/merged.dtb` created.

### Common fdtoverlay errors

| Error message | Cause | Solution |
|---------------|-------|----------|
| `FDT_ERR_NOTFOUND` | A `target-path` points to a node that does not exist in the base DTB | Check paths with `dtc -I dtb -O dts /boot/dtb/<base>.dtb \| grep <node>` |
| `FDT_ERR_EXISTS` | A node the overlay tries to create already exists | Use `__overlay__` to modify instead of create |
| `FDT_ERR_BADPHANDLE` | Corrupted or duplicate phandle | See step 2 |
| Segfault | Corrupted or incompatible DTBO | Recompile from source |

### Inspect the merged DTB

```bash
# On target: decompile the merged DTB to verify the result
ssh <user>@<target_ip> \
    "dtc -I dtb -O dts /tmp/merged.dtb 2>/dev/null" > /tmp/merged.dts

# Verify that camera nodes are present
grep -A5 "compatible.*exosens\|compatible.*xenics" /tmp/merged.dts

# Verify that remote-endpoints are resolved (no <0x00>)
grep -B2 -A2 "remote-endpoint" /tmp/merged.dts | grep -E "<0x00>|<0xffffffff>"
```

**If fdtoverlay fails:** do NOT reboot. Fix the DTBO and restart from step 1.

---

## Step 5: Reboot and wait

```bash
ssh <user>@<target_ip> "sudo reboot"
# Wait at least 60 seconds for a full boot
sleep 70
```

---

## Step 6: Post-boot diagnostics

### 6a. Check for video devices

```bash
ssh <user>@<target_ip> "ls -la /dev/video*"
```

**Expected result:** `/dev/video0`, `/dev/video1` (one per NVCSI channel
configured in the overlay).

If no `/dev/videoX` appears, proceed to dmesg diagnostics.

### 6b. Analyze dmesg

```bash
ssh <user>@<target_ip> \
    "sudo dmesg | grep -iE 'capture-vi|nvcsi|tegra-camera|video|v4l2|dione|ilumos|microlynx|eg.ec'"
```

### dmesg messages and diagnostics

| Message | Meaning | Action |
|---------|---------|--------|
| `tegra-camrtc-capture-vi: no devices found` | VI pipeline empty — no valid NVCSI channel | Check NVCSI nodes and remote-endpoints VI <-> NVCSI |
| `nvcsi: couldn't find channel@N` | NVCSI channel missing from DT | Verify the overlay adds channels under the correct target |
| `vi: port@N: no remote node found` | VI endpoint without NVCSI connection | Add bidirectional `remote-endpoint` VI -> NVCSI port@1 |
| `sensor: probe failed` or `deferred` | I2C communication failed (camera not plugged or wrong address) | Check I2C bus, address, physical wiring |
| `nvcsi: port@N: endpoint has no remote-endpoint property` | NVCSI endpoint without link back to sensor | Add `remote-endpoint` on the NVCSI channel port@0 |
| `overlay: ... failed to apply` | Overlay rejected by bootloader | See step 4 (fdtoverlay) |

### 6c. Verify the effective DT (proc device-tree)

```bash
# List camera nodes in the effective DT
ssh <user>@<target_ip> \
    "ls /proc/device-tree/bus@0/host1x@13e00000/nvcsi@15a00000/"

# Check a specific channel
ssh <user>@<target_ip> \
    "ls /proc/device-tree/bus@0/host1x@13e00000/nvcsi@15a00000/channel@0/"

# Check tegra-capture-vi
ssh <user>@<target_ip> \
    "ls /proc/device-tree/tegra-capture-vi/ports/"

# Read a specific property (e.g., compatible)
ssh <user>@<target_ip> \
    "cat /proc/device-tree/bus@0/i2c@31e0000/xenics_dione_ir_a@0e/compatible"
```

**Note:** Paths vary by platform. For p3767/p3768 (Orin NX/Nano), sensors
are under `/proc/device-tree/bus@0/cam_i2cmux/i2c@N/`.

### 6d. Verify node status

```bash
# The camera node must be "okay" (not "disabled")
ssh <user>@<target_ip> \
    "cat /proc/device-tree/bus@0/i2c@31e0000/<sensor_node>/status"
```

---

## Step 7: Video capture test

```bash
# List supported formats
ssh <user>@<target_ip> "v4l2-ctl -d /dev/video0 --list-formats-ext"

# Capture a single frame
ssh <user>@<target_ip> \
    "v4l2-ctl -d /dev/video0 --set-fmt-video=width=640,height=480,pixelformat=Y16 \
     --stream-mmap --stream-count=1 --stream-to=/tmp/frame.raw"

# GStreamer pipeline (display or file)
ssh <user>@<target_ip> \
    "gst-launch-1.0 v4l2src device=/dev/video0 ! 'video/x-raw,format=GRAY16_LE' ! videoconvert ! autovideosink"
```

---

## Advanced Diagnostics

### Problem: cross-fragment phandle resolution

**Symptom:** `remote-endpoint = <0x00>` in the decompiled DTBO.

**Cause:** In a multi-fragment overlay, labels defined in one `fragment@N`
are NOT visible from another `fragment@M`. The DT compiler (`dtc`) cannot
resolve cross-fragment references.

**Solution: group related nodes in the same fragment.**

Example — correct multi-fragment architecture:

```
Fragment@0: target = /bus@0/host1x@13e00000/nvcsi@15a00000
  -> NVCSI channels (0-3) + sensor nodes in THE SAME fragment
  -> labels (rbpcv2_csi_inX, sensor_outX) resolve locally
  -> bidirectional remote-endpoints within fragment = OK

Fragment@1: target = /
  -> tegra-capture-vi + tegra-camera-platform
  -> NO remote-endpoint towards Fragment@0 (avoids cross-fragment refs)
  -> proc-device-tree paths = strings (not phandles)
```

### Problem: new labels assigned to existing vi/nvcsi endpoints

**Symptom:** Camera probe fails or DT graph validation errors, even though the overlay compiles and applies cleanly.

**Cause:** The author created new labels (e.g., `eg_cams_csi_in0`) inside an `__overlay__` block for nodes that already exist in the base DTB (the nvcsi `endpoint@0`, vi `endpoint`, etc.). This gives the node two phandles — the original one from the base DTB and a new one from the overlay. Other nodes that already referenced the original phandle (e.g., the disabled stock camera's back-pointer to nvcsi) are not updated, creating an asymmetric graph.

**Rule:** Never assign labels to nodes that already exist in the base DTB inside an `__overlay__` block. Instead:

1. Check `__symbols__` in the base DTB for existing labels:
   ```bash
   dtc -I dtb -O dts /boot/dtb/<base>.dtb 2>/dev/null | \
     awk '/__symbols__/{p=1} p{print} /^\t\}/{if(p)exit}' | \
     grep -E "csi_in|csi_out|vi_in"
   ```

2. Use those existing labels directly from the overlay:
   - In `remote-endpoint` of the sensor endpoint: `<&csi_in0>` instead of a new overlay-local label
   - To update the nvcsi endpoint: use `target = <&csi_in0>` in a separate fragment (or modify by path in `target-path = "/"`, without assigning a new label)

3. The nvcsi→vi output connection (`csi_out0 ↔ vi_in0`) is **already bidirectionally wired** in the base DTB. Do not override it — only update the nvcsi input side (`csi_in0.remote-endpoint` → sensor).

**t186 (quill) label map** — these labels exist in `__symbols__` of the base DTB:

| Node | `__symbols__` label |
|------|---------------------|
| `nvcsi@150c0000/channel@0/ports/port@0/endpoint@0` | `csi_in0` |
| `nvcsi@150c0000/channel@0/ports/port@1/endpoint@1` | `csi_out0` |
| `nvcsi@150c0000/channel@1/ports/port@0/endpoint@2` | `csi_in1` |
| `nvcsi@150c0000/channel@1/ports/port@1/endpoint@3` | `csi_out1` |
| `vi@15700000/ports/port@0/endpoint` | `vi_in0` |
| `vi@15700000/ports/port@1/endpoint` | `vi_in1` |

---

### Problem: overlay applied but no /dev/videoX

**Diagnostic procedure:**

1. Verify the overlay is loaded:
   ```bash
   # List applied overlay symbols
   cat /proc/device-tree/__symbols__/* 2>/dev/null | strings | grep <camera>
   ```

2. Verify the complete pipeline Sensor -> NVCSI -> VI:
   ```bash
   # NVCSI channels present?
   ls /proc/device-tree/bus@0/host1x@13e00000/nvcsi@15a00000/channel@*/

   # VI ports present?
   ls /proc/device-tree/tegra-capture-vi/ports/port@*/

   # Remote-endpoints resolved? (binary file, 4 bytes = phandle)
   xxd /proc/device-tree/tegra-capture-vi/ports/port@0/endpoint/remote-endpoint
   # If all zeros -> broken link
   ```

3. Verify bidirectional connections:
   ```
   Required pipeline (L4T 36.x):

   Sensor endpoint ──remote-endpoint──> NVCSI channel port@0 endpoint (input)
   NVCSI channel port@0 endpoint ──remote-endpoint──> Sensor endpoint
   NVCSI channel port@1 endpoint ──remote-endpoint──> VI port endpoint (output)
   VI port endpoint ──remote-endpoint──> NVCSI channel port@1 endpoint

   All 4 links must be present. If even one is missing: no /dev/videoX.
   ```

### Problem: target-path not found

```bash
# List the base DT to find the correct path
dtc -I dtb -O dts /boot/dtb/<base>.dtb 2>/dev/null | grep -n "<node_to_find>"

# Compare with the target-path in the overlay DTS
grep "target-path" sources/.../overlay/<overlay>.dts
```

**Common pitfalls:**
- L4T 36.x: `/bus@0/` prefix required on `host1x`, `i2c@`, `cam_i2cmux`
- L4T 36.x: NO `/bus@0/` on `tegra-capture-vi` and `tegra-camera-platform`
- L4T 35.x: NEVER use `/bus@0/`
- Auvidea vs NVIDIA DevKit: different base DTB = different nodes present

### Tool: comparative decompilation

```bash
# Compare the DT before and after overlay
dtc -I dtb -O dts /boot/dtb/<base>.dtb 2>/dev/null > /tmp/before.dts
dtc -I dtb -O dts /tmp/merged.dtb 2>/dev/null > /tmp/after.dts
diff /tmp/before.dts /tmp/after.dts | head -200
```

---

## Iterative Cycle Summary

```
 +---------------------------+
 | 1. Modify the DTSI/DTS    |
 +------------+--------------+
              |
              v
 +---------------------------+
 | 2. Compile (l4t_build)    |
 +------------+--------------+
              |
              v
 +---------------------------+
 | 3. Verify phandles        |<--- If invalid phandles: go back to 1
 |    (dtc -I dtb -O dts)    |
 +------------+--------------+
              |  OK
              v
 +---------------------------+
 | 4. Copy to the target     |
 +------------+--------------+
              |
              v
 +---------------------------+
 | 5. fdtoverlay (WITHOUT    |<--- If failure: go back to 1
 |    rebooting!)            |     (DO NOT reboot)
 +------------+--------------+
              |  OK
              v
 +---------------------------+
 | 6. Inspect merged.dtb     |<--- If nodes missing: go back to 1
 |    (optional but          |
 |     recommended)          |
 +------------+--------------+
              |  OK
              v
 +---------------------------+
 | 7. Reboot + wait 60s      |
 +------------+--------------+
              |
              v
 +---------------------------+
 | 8. Diagnostics:           |
 |    - /dev/video*          |
 |    - dmesg                |<--- If problem: analyze, go back to 1
 |    - /proc/device-tree    |
 +------------+--------------+
              |  OK
              v
 +---------------------------+
 | 9. Video capture test     |
 |    (v4l2-ctl, gstreamer)  |
 +---------------------------+
```

**Golden rule: NEVER reboot until fdtoverlay succeeds.**
Rebooting with a broken overlay can make the board unreachable
(boot loop if the overlay is applied by the bootloader).
