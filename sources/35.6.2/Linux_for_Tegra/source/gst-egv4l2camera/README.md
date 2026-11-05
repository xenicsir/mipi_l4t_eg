# EG NVMM camera source for L4T 35.6.2

Separate factory/GTypes preserve coexistence with the NVIDIA plugin.
The source uses the BSP's native nvbufsurface.h and retains vendor notices.

YUYV/UYVY and RGB capture use native NVMM surfaces. Grayscale capture requires
`preview=true`: Y16, Y16_BE or right-aligned Y14 camera bytes are captured into
an internal GRAY8 allocation with twice the pixel width. CUDA reads the 16-bit
samples and produces RGBA at the original resolution. This internal byte storage
is never advertised as a GRAY8 or GRAY16 camera output. Standard raw GRAY16_LE
NVMM export is unavailable on this BSP; V4L2 raw capture remains available.

`normalize=true` enables per-frame GPU min/max normalization. The default is
fixed-range scaling. Camera data remains unchanged and no pixels are mapped to
the CPU in the production pipeline. The CUDA helper uses the driver ABI and
embedded PTX without a CUDA Toolkit build dependency.

See docs/JETSON_HARDWARE_VIDEO_PIPELINE.md for installation and usage.

For a YUYV display matching the classic monitor, use `capture-format=YUYV
preview=true`: CUDA converts BT.601 limited-range samples directly to RGBA.
The read-only `yuyv-preview` capability advertises this path. Native YUY2 NVMM
capture remains available without preview. RGB/BGRx display conversion uses
RGBA rather than a subsampled NV12 intermediate.

Software availability and target qualification are recorded separately in the
deployment matrix. Use the binary built with the target BSP runtime.
