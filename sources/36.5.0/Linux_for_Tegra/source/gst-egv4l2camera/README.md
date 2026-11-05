# EG NVMM camera source for L4T 36.5.0

Uses the EG camera capture implementation with this BSP’s native
nvbufsurface.h from gst-nvvidconv_src.tbz2. Vendor notices are retained.
Separate factory/GTypes preserve coexistence with the original NVIDIA plugin.

Capture supports YUYV/UYVY, RGB and grayscale. `capture-format` selects Y16,
right-aligned Y14 or Y16_BE. NVMM grayscale output is little-endian; `preview`
produces full-range RGBA on CUDA. Source frames remain unchanged. The CUDA
helper uses the driver ABI and embedded PTX, with no CPU image mapping or
CUDA Toolkit build requirement.

The host builder stages libgstegv4l2camerasrc.so into the rootfs and the delivery
package. This overlay targets L4T36.5.0; other supported BSPs carry their own
source overlays. See docs/JETSON_HARDWARE_VIDEO_PIPELINE.md.

Grayscale preview uses the fixed declared range by default. `normalize=true`
with `preview=true` enables per-frame min/max normalization entirely on the GPU;
constant frames map to black. Raw capture values are unchanged. The source logs
the applied pixel processing at startup. GPU extrema remain on the device.

For a YUYV display matching the classic monitor, use `capture-format=YUYV
preview=true`: CUDA converts BT.601 limited-range samples directly to RGBA.
The read-only `yuyv-preview` capability advertises this path. Native YUY2 NVMM
capture remains available without preview. RGB/BGRx display conversion uses
RGBA rather than a subsampled NV12 intermediate.

Software availability and target qualification are recorded separately in the
deployment matrix. Use the binary built with the target BSP runtime.
