# Camera capture in NVIDIA memory

`egv4l2camerasrc` provides V4L2 DMABUF capture into NVIDIA surfaces. The prepared
sources for L4T 36.4.4 add RGB and grayscale modes to the YUYV path. The original
NVIDIA factory remains unchanged. See [the client guide](../../docs/JETSON_HARDWARE_VIDEO_PIPELINE.md)
for format qualification, byte order, grayscale precision and generated commands.

Validated camera paths: SmartIR640, 640×480 YUYV, AB24/RGBA and Y16 on Orin Nano
L4T 36.4.4. Y14 and Y16-BE camera paths are tested with iLumos at 1280×1024.
VIC converts YUYV; RGB can be rendered directly. Grayscale preview and big-endian
normalization use CUDA, without mapping image pixels into CPU memory.

The source checks negotiated V4L2 format/dimensions and surface pitch/capacity.
`capture-format` preserves the actual grayscale V4L2 mode; `preview` selects
8-bit RGBA display output. Without preview, grayscale retains its 16-bit sample
values, in little-endian NVMM storage. No image data crosses the monitor's process
supervision channel.

## Build on the host or the Jetson

Use the plugin source archives from the **same BSP as the target**. The tested
archives are in the L4T 36.4.4 public sources:

- `gst-nvv4l2camera_src.tbz2`;
- `gst-nvvidconv_src.tbz2` (provides the matching `nvbufsurface.h`).

The builder needs Python 3, `patch`, `pkg-config` and an AArch64 C++ compiler.
GStreamer/GLib development headers and libraries must be available in the target
sysroot (or installed locally for a native build).
CUDA processing loads the BSP CUDA driver through its C ABI; the embedded PTX
kernel needs no CUDA Toolkit or nvcc during the plugin build. The EGL frame ABI
was checked against CUDA 12.6 headers, and Y16 conversion was tested on target.

The runtime needs the matching `nvidia-l4t-gstreamer` package and multimedia
libraries. Do not install a newer BSP package inadvertently: the test target
used `nvidia-l4t-gstreamer=36.4.4-20250616085344`.

For prepared sources, replace the archive arguments below with
`--source-dir /path/to/sources/36.4.4/Linux_for_Tegra/source/gst-egv4l2camera`.
Both input methods produce the same source files and ARM64 binary.

For a native target build:

```sh
python3 build_camera_plugin.py \
  --camera-archive /path/to/gst-nvv4l2camera_src.tbz2 \
  --converter-archive /path/to/gst-nvvidconv_src.tbz2 \
  --output "$HOME/nvv4l2-yuy2-build"
```

For host cross-compilation, add the BSP toolchain and its rootfs:

```sh
python3 build_camera_plugin.py \
  --camera-archive /path/to/BSP/source/gst-nvv4l2camera_src.tbz2 \
  --converter-archive /path/to/BSP/source/gst-nvvidconv_src.tbz2 \
  --cxx /path/to/toolchain/bin/aarch64-buildroot-linux-gnu-g++ \
  --sysroot /path/to/BSP/rootfs \
  --output /path/to/new-build
```

The host build was tested with the L4T36.4.4 GCC11.3 toolchain and rootfs. Its
ARM64 library was loaded and captured120 frames on the target. The builder
renames the factory, GTypes and allocator symbols so `egv4l2camerasrc` and the
original `nvv4l2camerasrc` can coexist in one process.

The output directory must be new. The builder extracts selected source files,
applies the patch without fuzzy matching, builds the ARM64 library and writes hashes to
`manifest.json`. NVIDIA's source license headers are preserved in extracted files.
The patch was tested against 36.4.4 only.

## Run without replacing the system plugin

```sh
export GST_PLUGIN_PATH="$HOME/nvv4l2-yuy2-build"
export GST_REGISTRY="$HOME/nvv4l2-yuy2-build/registry.bin"
gst-inspect-1.0 egv4l2camerasrc
```

Check that `Filename` points to this build and that the caps list both UYVY and
YUY2. Use the actual video device, resolution and frame rate of the connected
camera. For the tested SmartIR640:

```sh
env __GL_YIELD=USLEEP gst-launch-1.0 -e -v \
  egv4l2camerasrc device=/dev/video0 num-buffers=180 ! \
  'video/x-raw(memory:NVMM),format=YUY2,width=640,height=480,framerate=60/1' ! \
  nvvidconv compute-hw=2 ! \
  'video/x-raw(memory:NVMM),format=NV12' ! \
  nv3dsink sync=false processing-deadline=0
```

`compute-hw=2` explicitly selects VIC on the tested plugin. The display needs an
active graphical session and an awake monitor. On this bench, both NVIDIA sinks
stalled while the display was DPMS-off, even with `videotestsrc`; waking it made
the 180-frame camera pipeline finish normally. Check `xset -q` from the correct
X11 session if this occurs; `xset dpms force on` wakes the display.

For a capture/conversion test without display, replace `nv3dsink ...` with
`fakesink sync=false`. This validates the upstream path, not the rendering stage.
The NVIDIA plugin remains installed under its original name. The L4T36.4.4
build compiles the prepared sources in `sources/36.4.4/Linux_for_Tegra/source/`
and includes the EG library in the driver package. GST_PLUGIN_PATH is only
needed for isolated builds. Other BSP versions are not enabled yet.

## Memory path and evidence

```text
YUYV camera → CSI/VI DMA → NvBufSurface YUYV / DMABUF / NVMM
                          → VIC → NV12 / NVMM → GPU display
```

The CPU still orchestrates buffers, ioctls and the application. The hardware
image path does not mean zero CPU usage or that every block is the GPU: the VI
captures, VIC converts, and the display sink renders using NVIDIA graphics.
Encoding is a separate downstream capability to check for the particular SoM.

The target tests established:

- 120 successful V4L2 DQBUF calls, all DMABUF, no V4L2 error flags;
- 120 NVMM surfaces at capture and 120 at conversion output, both
 `NVBUF_MEM_SURFACE_ARRAY`, with expected formats and dimensions;
- the allocator's 1280-byte capture pitch matches V4L2;
- one same-PTS diagnostic snapshot has all 307200 luma samples unchanged across
 conversion; the neutral chroma of the supplied grey test pattern also matches;
- 180 frames rendered with `nv3dsink` and clean EOS;
- three successive capture/conversion runs per benchmark variant.

Pixel mapping was enabled only for the one-frame diagnostic comparison, not in
the benchmark or display pipeline. Block-linear surfaces must not be dumped as
linear pixels: the snapshot test explicitly requested `bl-output=false` and
honoured the output pitch. This validation does not test arbitrary chroma,
all resolutions, physical end-to-end latency or prolonged reliability.

## Short benchmark on this setup (initial native prototype)

All variants requested 480 frames, YUY2→NV12, and ended in a fakesink. Three runs
per variant, order rotated, 3s between captures. CPU below is process CPU time /
wall time, where 100% is one CPU core; startup is included. Runtime power/clock
settings were not changed. These measurements exclude display and encoding.

| Capture and conversion | Mean process CPU |
| --- | ---: |
| v4l2src → videoconvert → NV12 in system memory |73.91% |
| v4l2src → nvvidconv/VIC → NV12 NVMM |13.57% |
| patched nvv4l2camerasrc → nvvidconv/VIC → NV12 NVMM |5.44% |

Each completed 480 frames in about 8.1–8.3s, including startup. This result supports
the benefit of the NVMM capture path on the tested board; it is not a claim
about every Jetson, camera, format or application. No end-to-end latency gain
has been measured.

The earlier `tools/camera-format-benchmark` used v4l2src for all its variants;
it did not compare this direct NVMM capture path.

NVIDIA's reference describes the DMABUF capture interface and the extension
needed for formats beyond UYVY:
https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/SD/Multimedia/AcceleratedGstreamer.html#progressive-capture-using-nvv4l2camerasrc


## Integration and remaining qualification

L4T36.4.4 builds and packages the plugin. `eg_dt_camera_config_get.sh` selects one
recommended GStreamer command for the format and display context; its optional
`--all-streaming-backends` mode supports regression comparisons. The monitor
selects `auto|classic|nvmm`, including a classic fallback for forwarded X11.

RGB and Y16 target tests complement the YUYV tests. Y14/Y16-BE capture and
GPU conversion are tested with iLumos at 1280×1024. Other BSP ports remain deferred. Group future
L4T versions by multimedia API, GStreamer, DMABUF/kernel and SoC differences;
keep target tests distinct from compile-only or inferred coverage.


## Repeatable grayscale GPU check

On the target, from a source checkout, this checks synthetic Y16_LE data without
opening a camera. It does not qualify Y14 or Y16-BE camera paths.

```sh
EG_CAMERA_SRC=sources/36.4.4/Linux_for_Tegra/source/gst-egv4l2camera
c++ -std=c++11 -I"$EG_CAMERA_SRC" \
  tools/jetson-hw-pipeline/tests/check_gray16.cpp "$EG_CAMERA_SRC/eg_cuda_gray.cpp" \
  -L/usr/lib/aarch64-linux-gnu/nvidia -Wl,-rpath,/usr/lib/aarch64-linux-gnu/nvidia \
  -lnvbufsurface -ldl -o /tmp/check-gray16
env -u DISPLAY /tmp/check-gray16
```

Expected: 131841 pixels checked, zero errors. The checker maps pixels on the CPU
only to create the diagnostic input and validate the GPU result; the production
capture/preview path does not perform these CPU mappings.

## Grayscale conversion verification on a camera

`tests/check_gray_camera.cpp` compares camera input bytes with GPU output from
that same buffer. It checks Y16-BE to native little-endian normalization, Y14
range, grayscale-to-RGBA scaling and alpha. Each invocation captures two cycles
of 30 frames and fails on corrupted buffers or mismatched pixels.

This diagnostic maps pixels on the CPU. It does not measure production pipeline
performance. It uses private buffer structures, so compile it against the headers
matching the installed plugin. On L4T36.4.4, with these headers in `$PLUGIN_SOURCE`:

```sh
g++ -std=c++17 -O2 -Wall -Wextra tests/check_gray_camera.cpp \
  -I"$PLUGIN_SOURCE" $(pkg-config --cflags --libs gstreamer-1.0 gstreamer-video-1.0 gstreamer-base-1.0) \
  -L/usr/lib/aarch64-linux-gnu/nvidia -Wl,-rpath,/usr/lib/aarch64-linux-gnu/nvidia \
  -lnvbufsurface -o check_gray_camera

env -u DISPLAY ./check_gray_camera /dev/video0 Y16_BE 1280 1024 raw
env -u DISPLAY ./check_gray_camera /dev/video0 Y16_BE 1280 1024 preview
env -u DISPLAY ./check_gray_camera /dev/video0 Y14 1280 1024 raw
env -u DISPLAY ./check_gray_camera /dev/video0 Y14 1280 1024 preview
```

Use the actual video node and dimensions. The source must support switching to
the requested capture format. These checks validate numeric conversion, not the
camera sensor's radiometric accuracy or all possible input patterns.


## Optional GPU display normalization

Grayscale preview is fixed-range by default. Add `normalize=true` alongside
`preview=true` to stretch each frame's min/max to RGBA0..255 on the GPU.
`rt_frame_monitor.py --normalize --display` requests the same treatment (CPU
with classic, GPU with NVMM). Generated grayscale preview commands include the
option explicitly. Captured values remain unchanged. Inapplicable monitor
requests produce an informational message and continue without normalization.

`tests/check_gray_normalization.cpp` checks synthetic fixed/normalized and raw
paths, constant and low-contrast frames, both byte orders and pitched odd sizes.
Compile it with `eg_cuda_gray.cpp`, `-lnvbufsurface -ldl`, and run without DISPLAY.
For real-camera checks, `check_gray_camera ... preview normalized` compares GPU
min/max mapping with an independent CPU reference from the same input frame;
`preview fixed` checks full-range scaling. Normalized rounding tolerance is one
8-bit level; raw and fixed comparisons remain exact.
