# EG NVMM camera source for L4T 39.2.2

Port of the EG capture implementation using the NvBufSurface header shipped
with L4T 39.2.2. Allocations explicitly use NVBUF_MEM_SURFACE_ARRAY and the CAMERA
memory tag, as in the matching NVIDIA source. The header must not be replaced
with the 36.x ABI. Vendor notices are preserved.

Capture supports YUYV/UYVY, RGB, Y16, right-aligned Y14 and Y16-BE. CUDA provides
RGBA previews, optional per-frame normalization, and byte swapping for Y16-BE.
YUYV preview uses BT.601 limited-range conversion. Raw samples remain unchanged.
The source validates the allocated pitch/size against V4L2 before queuing DMA
buffers; it does not silently reinterpret padded rows or copy pixels on the CPU.

The BSP CUDA driver loads the embedded PTX; no CUDA Toolkit or NVRTC is required.
The host builder stages the plugin into the package. Runtime qualification is
tracked separately in the deployment matrix and hardware test reports.

This BSP port requires target qualification; compilation alone is not hardware validation.

The 39.2.2 supplier changes are retained: native GRAY8 caps and allocation guards,
alongside EG colour/RAW/CUDA modes. Native GRAY8 uses one byte per pixel; the
opaque GRAY8 surface used by EG YUYV preview still stores two bytes per pixel.
This does not declare a new GRAY8 mode for an Exosens camera.
