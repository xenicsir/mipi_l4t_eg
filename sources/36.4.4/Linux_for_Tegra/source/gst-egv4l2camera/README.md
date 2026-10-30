# EG NVMM camera source for L4T 36.4.4

Derived from NVIDIA gst-nvv4l2camera_src.tbz2 for this BSP, with matching
nvbufsurface.h from gst-nvvidconv_src.tbz2. Vendor notices are retained.
Separate factory/GTypes preserve coexistence with the original NVIDIA plugin.

Capture supports YUYV/UYVY, RGB and grayscale. `capture-format` selects Y16,
right-aligned Y14 or Y16_BE. NVMM grayscale output is little-endian; `preview`
produces full-range RGBA on CUDA. Source frames remain unchanged. The CUDA
helper uses the driver ABI and embedded PTX, with no CPU image mapping or
CUDA Toolkit build requirement. Y14/Y16-BE capture and GPU conversion have
been tested with iLumos at 1280×1024 on Orin Nano with L4T36.4.4.

The host builder stages libgstegv4l2camerasrc.so into the rootfs and the delivery
package. Only L4T36.4.4 is enabled. See docs/JETSON_HARDWARE_VIDEO_PIPELINE.md.

Grayscale preview uses the fixed declared range by default. `normalize=true`
with `preview=true` enables per-frame min/max normalization entirely on the GPU;
constant frames map to black. Raw capture values are unchanged. The source logs
the applied pixel processing at startup. GPU extrema remain on the device.
