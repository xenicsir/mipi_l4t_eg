# Hardware video pipelines on Jetson

## Availability

The L4T 36.4.4 package includes `egv4l2camerasrc`, a V4L2 DMABUF source using
NVIDIA surfaces. YUYV, RGB (AB24) and Y16 paths have been tested with SmartIR640
at 640×480 on Orin Nano. Crius1280 covers these formats at 1280×1024;
Y14 and Y16-BE paths have also been tested at 1280×1024. Other BSP ports are not enabled.

| V4L2 input | NVMM capture output | Display path | Qualification |
| --- | --- | --- | --- |
| YUYV | YUY2 | VIC → NV12 → GPU | Tested |
| AB24 (RGBA bytes) | RGBA | GPU display directly | Tested |
| AR24 (BGRA bytes) | BGRA or BGRx | BGRx → VIC → NV12 → GPU | Requires target qualification |
| Y16 | GRAY16_LE, 16 bits retained | CUDA → RGBA → GPU | Tested |
| Y14 | GRAY16_LE storage, 14 valid bits | CUDA → RGBA → GPU | Tested at 1280×1024 |
| Y16-BE | GRAY16_LE after GPU byte swap | CUDA → RGBA → GPU | Tested at 1280×1024 |
| UYVY | UYVY | VIC → NV12 → GPU | Requires target qualification |

The plugin requires the matching NVIDIA multimedia runtime. CUDA grayscale
processing uses the BSP's CUDA driver. No separate CUDA Toolkit, nvcc or NVRTC
dependency is needed: the installed driver JIT-compiles a small embedded PTX kernel.
Source and output surfaces remain in NVIDIA memory.

The plugin installs in the standard GStreamer directory and can coexist with
NVIDIA's original `nvv4l2camerasrc`. For isolated builds, use
[the plugin builder](../tools/jetson-hw-pipeline/README.md) and GST_PLUGIN_PATH.

## Capture, conversion and rendering

CSI/VI capture is already a hardware operation, including when using
`v4l2-ctl --stream-mmap`. MMAP makes capture buffers accessible to a process;
it does not mean that the CPU captures or converts the pixels.

A hardware processing pipeline also keeps compatible buffers across subsequent
stages:

```text
camera → CSI/VI DMA → NVMM surface → VIC conversion → NVMM surface → GPU display
```

`egv4l2camerasrc` allocates NVIDIA surfaces and supplies their DMABUF descriptors
to V4L2. `nvvidconv compute-hw=2` selects VIC conversion. `nv3dsink` renders the
NVMM output through NVIDIA graphics. The CPU still handles application logic,
buffer queues and driver calls. Hardware processing does not mean zero CPU use
or that every operation runs on the CUDA GPU; VIC is a separate accelerator.

The conventional `v4l2src ! videoconvert ! ...` path also captures through VI,
but `videoconvert` processes pixels on the CPU. Replacing it with `nvvidconv`
accelerates conversion; direct NVMM capture additionally avoids the initial
system-memory-to-NVIDIA-surface upload used by the tested hybrid path.

## Command-line streaming

Use the camera's actual device, format and dimensions. When caps omit the frame
rate, the source reads V4L2's capture interval instead of assuming 30fps (0/1 if
unknown). Explicit frame-rate caps describe the expected cadence; this source
does not reprogram the camera's frame rate. For 640×480 YUYV:

```sh
gst-inspect-1.0 egv4l2camerasrc

env __GL_YIELD=USLEEP gst-launch-1.0 -e -v \
  egv4l2camerasrc device=/dev/video0 ! \
  'video/x-raw(memory:NVMM),format=YUY2,width=640,height=480,framerate=60/1' ! \
  nvvidconv compute-hw=2 ! \
  'video/x-raw(memory:NVMM),format=NV12' ! \
  nv3dsink sync=false processing-deadline=0
```

The command uses `__GL_YIELD=USLEEP` to reduce CPU time spent waiting in the
NVIDIA graphics driver, following [NVIDIA's graphics guidance](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/Graphics/GraphicsProgramming/OpenglEsProgrammingTips.html#graphics-driver-cpu-usage).
The NVMM monitor and client examples set this default for display while preserving
an existing environment value. It affects graphics waiting, not pixel conversion.

V4L2 YUYV is named YUY2 in GStreamer. UYVY uses a different byte order;
changing caps or the device tree alone does not convert the data.

For a bounded test, add `num-buffers=180` to the source. For capture/conversion
without display, replace the sink with `fakesink sync=false`. This does not
validate rendering. Display requires the correct graphical session and an awake
monitor; on X11 check `xset -q`, and wake it with `xset dpms force on` if needed.

`eg_dt_camera_config_get.sh` prints one recommended full-frame GStreamer command. It selects
the hardware path when YUY2/NVMM and the NVIDIA converter/sink are loadable and
DISPLAY names a local X11 session. Otherwise it selects the conventional command.
`--all-streaming-backends` includes both paths for comparison/regression tests.
JSON output does not probe GStreamer plugins.

## Remote execution through SSH

SSH can carry commands and logs while capture and processing remain on the
Jetson. A monitor run without `--display` needs no graphical session or awake
screen. For local rendering started over SSH, use the Jetson's display and its
matching Xauthority/session credentials; `DISPLAY=:0` alone does not grant access.
The automated target runner discovers the local X11 authority and wakes the
screen before display tests if DPMS has suspended it.

With X11 forwarding (`ssh -X`, for example `DISPLAY=localhost:10.0`), automatic
monitor selection and generated display commands use classic capture. Forced
NVMM display is rejected before capture: the remote OpenGL context cannot be
assumed compatible with local CUDA graphics interop. SSH controlling a local
`DISPLAY=:0` remains eligible for NVMM. Headless NVMM does not depend on DISPLAY: the monitor clears it in its capture
worker, and the client examples clear it with --headless. For a manual headless
CUDA pipeline, use `env -u DISPLAY gst-launch-1.0 ...` so EGL buffer import does
not select the forwarded X server. Sending video to a remote computer requires a separate
network streaming pipeline and its own format/encoder/transport validation.

## Python client

Use GStreamer through PyGObject. The example manages errors, EOS and Ctrl+C,
counts buffer metadata and never maps pixels into Python:

```sh
python3 tools/jetson-hw-pipeline/examples/preview.py \
  --device /dev/video0 --format YUYV --width 640 --height 480 --fps 60 --frames 180
```

Required Python bindings: `python3-gi`, `gir1.2-gstreamer-1.0` and the GStreamer
video typelibs. Set GST_PLUGIN_PATH as above when using an isolated build.
`--headless` disables rendering; `--frames 0` runs until Ctrl+C. `--format` accepts
YUYV, AB24, AR24, Y16, Y14 and Y16_BE. Grayscale uses the GPU preview path.
The C example accepts the same format selection. Hardware qualification follows
the table above; an accepted option is not evidence of a target test.

The application creates the pipeline with `Gst.parse_launch`, sets the source
properties and transitions it to PLAYING. It consumes bus messages and sets NULL
on exit. Python orchestration does not require CPU access to image pixels.

## C client

The C example uses the same GStreamer factory and pipeline:

```sh
cc -Wall -Wextra \
  tools/jetson-hw-pipeline/examples/preview.c \
  $(pkg-config --cflags --libs gstreamer-1.0) -o preview
./preview --device /dev/video0 --frames 180
```

It handles errors, EOS and termination signals, counts metadata and releases the
pipeline. An application may instead create elements individually with
`gst_element_factory_make("egv4l2camerasrc", ...)`.

For custom pixel processing, use a component that accepts NVMM surfaces and
performs the work on GPU/VIC. Pulling images into OpenCV or NumPy introduces CPU
pixel access; naming the source NVMM does not make such a downstream path fully
hardware-processed.

## rt_frame_monitor.py

The monitor remains portable: Windows uses its existing MSMF/CameraLink paths,
and generic Linux (including Raspberry Pi) retains V4L2/classic capture. NVIDIA
plugins are optional, checked only for NVMM selection. CPU monitoring uses
portable Python clocks, with no NVIDIA or Linux-specific utility dependency.

`--backend auto` is the default. It chooses NVMM for a compatible camera format
when the plugin is loadable and no pixel analysis is requested. Otherwise it
prints the reason and selects `classic`. `--backend classic` always uses the
CPU-accessible capture path; `--backend nvmm` requires the hardware path.

```sh
rt_frame_monitor.py -d /dev/video0 --display
rt_frame_monitor.py -d /dev/video0 --backend nvmm --num-frames 180 --log --base-dir /tmp/camera-run
rt_frame_monitor.py -d /dev/video0 --backend classic --stats --display
```

Both backends show `cpu=…%`, refreshed about once a second. It measures the
capture process, all threads, with 100% per occupied CPU core; values above
100% are valid. It excludes GPU/VIC utilization; in NVMM mode it also excludes
the lightweight supervisor. The external runner includes both processes. CSV logs
include `cpu_percent_one_core`; NVMM also records the run average in its JSON
summary. The first sample is blank until a measurement interval is available.
OpenCV and NumPy are loaded only by the classic path. The external regression
runner additionally measures command CPU time including
waited child processes, startup and shutdown. Compare equal frame counts and
display settings; short runs include a significant initialization cost.

Both backends use the same status layout and refresh policy: one terminal line
at about 10Hz, or one line per second in redirected output. The backend is printed
once at selection. CPU sampling remains at about 1Hz.

```text
frame=   168  ts=   2.801s  dt=  16.8ms  expected_fps= 60.0  actual_fps= 60.0  cpu= 16.2%  gst_drop=  --  corrupt=  0  sequence_gaps=   0
```

- `ts`: elapsed time from the first frame received for processing.
- `dt`: interval between the last two such frames, in milliseconds.
- `expected_fps`: the reference rate. For a Linux EngineCore I2C camera this is
  read once before capture with `ECSwCtrl ... -c "rf 0x210"`, using the device
  associated with the selected video node. It requires access to that device.
- `actual_fps`: measured processing/display reception rate over about one second.
  It is not a measurement of the physical screen refresh rate.

Other cameras have no verified automatic reference reader here. Their expected
rate is `--`, or an explicit value supplied with `--expected-fps 30` (also available
as `expected_fps` in JSON). This option is a reference, not a camera setting.
The package installs an EngineCore udev rule giving `/dev/eg-ec-mipi-*` mode
`0660`, owned by `root:i2c`. Installation reapplies it to existing nodes and udev
applies it on recreation. Members of `i2c` can use ECSwCtrl without sudo, for reads
and writes. No user is added to this group automatically. If access is needed,
an administrator can run `sudo usermod -aG i2c <user>`; a new login is then required.

The existing `--fps` capture parameter and its default are not silently treated
as a verified camera reference. The measured capture rate remains in `FPS_RESULT`
and the diagnostic reports; it is not used as `expected_fps`.

Windows does not use Linux sysfs or launch an I2C ECSwCtrl command. The explicit
reference/unknown behavior applies there too. Missing ECSwCtrl, access errors,
timeouts or invalid responses leave the reference unknown without preventing
capture. A rejected EngineCore read (`!-128`) is retried once after two seconds;
there is no polling while streaming and no automatic privilege elevation.

- `gst_drop`: the classic path's legacy estimate of the capture/processing gap;
  it can include queued frames as well as discarded ones. It is not a driver
  loss counter. NVMM has no classic appsink queue, so this field is `--`.
- `corrupt` and `sequence_gaps`: source-buffer error flags and missing sequence
  numbers where the capture backend exposes them. Unavailable values are `--`,
  including on capture APIs that provide pixels without this metadata.

The run report retains the overall rate and a separate measurement after the
first second, so display initialization is not confused with steady throughput.

In NVMM mode the monitor reads buffer metadata only: frame count, PTS, V4L2
sequence numbers and corruption flags. It checks NVMM caps and the source
allocator without mapping image pixels. `--display` adds the applicable VIC/CUDA processing and hardware rendering. Stop with Ctrl+C; ESC is available in the classic OpenCV
window only. `--log` writes metadata CSV and a JSON summary. `--max-log-lines`
rotates the CSV. `--drop-detect` enables timestamp gap estimates, recorded
separately from missing V4L2 sequence numbers. `corrupt` counts V4L2 error flags
propagated to buffers; `sequence_gaps` counts skipped sequence numbers reported
by V4L2 (e.g.10→13 adds2). They do not identify the physical cause or count every
possible loss upstream of the driver. Neither detects silent pixel
corruption; that requires a separate image integrity test.

Pixel statistics, FPN detection, image saving and their tuning options select
classic capture in auto mode. Forced NVMM rejects them before opening the
camera, including requests loaded from JSON. CameraLink and classic window or
recovery tuning are also incompatible with forced NVMM. Metadata logging does
not imply pixel statistics in NVMM; classic logging retains its pixel metrics.

NVMM capture runs in a supervised process within the same standalone script.
Ctrl+C requests shutdown, then escalates if native cleanup is blocked. A
heartbeat watchdog detects unresponsive native calls; killing the supervisor
also kills its capture process. No image pixels pass through this control link.
Ctrl+Z suspends a running job; it does not release a camera by itself.

Runtime errors, missing frames and driver corruption flags fail the NVMM run
without switching backend. The startup wait is bounded; `--freeze-threshold`
controls the allowed gap after capture starts (0 disables this gap check).

For automated target tests, `test/hardware/run_camera_regression.py` runs the
classic, NVMM and auto monitor selections separately, as well as both generated
GStreamer pipelines and raw V4L2 capture. `--require-nvmm` makes missing hardware
support a failure for supported test formats. `--current-format-only` avoids EngineCore format
cycling for a focused test. Unsupported NVMM formats are recorded as not
applicable, never as a successful hardware capture.

## Grayscale capture and preview

`capture-format=Y16`, `Y14` or `Y16_BE` selects the actual V4L2 input format.
`auto` retains the active grayscale input. Y14 uses its own V4L2 mode even though
its memory container and GStreamer representation are 16-bit. Y14 input must be
right-aligned, as specified by V4L2; the `capture-bits` property reports 14 or 16.

Without `preview`, output remains 16-bit grayscale. Y16-BE is converted to
little-endian on the GPU while retaining every bit of its sample values. Native
V4L2 capture outside this plugin retains its original byte order.

For raw Y16 capture without CPU pixel access:

```sh
env -u DISPLAY gst-launch-1.0 -e egv4l2camerasrc device=/dev/video0 capture-format=Y16 ! \
  'video/x-raw(memory:NVMM),format=GRAY16_LE,width=640,height=480,framerate=60/1' ! \
  fakesink sync=false
```

`preview=true` produces 8-bit RGBA on CUDA, leaving the capture surface unchanged.
It maps the full declared grayscale range to 8 bits: `value >> 8` for Y16,
`value >> 6` for right-aligned Y14. This fixed range is the default in both monitor backends. The image can look
nearly black when samples occupy only a small part of the declared range.

Use `rt_frame_monitor.py --display --normalize` for per-frame min/max
normalization: CPU in classic, GPU in NVMM. For GStreamer, use
`capture-format=Y14 preview=true normalize=true` (or Y16/Y16_BE).
The GPU finds the minimum/maximum and scales to 0..255 without returning pixels
or extrema to the CPU. A constant image maps to black. The original capture
surface and raw measurements are unchanged; displayed brightness is relative to
each frame's extrema and can vary with the scene.

The generated grayscale preview commands explicitly request normalization.
Remove `--normalize`, or use `normalize=false`, for the fixed range.
If the monitor cannot apply a requested normalization (color format, no display,
or missing plugin capability), it continues and prints an informational message.
The monitor and capture plugin describe their pixel processing at startup.
`rt_frame_monitor.py --help` also describes every live status field.

There is no native GStreamer Y14 format in the classic `v4l2src` path. The EG
source selects Y14 through V4L2 and outputs GRAY16_LE storage or GPU-converted
RGBA; downstream elements therefore do not need native Y14 support.
Use the raw path when preserving measurement precision.

```sh
env __GL_YIELD=USLEEP gst-launch-1.0 -e \
  egv4l2camerasrc device=/dev/video0 capture-format=Y16 preview=true ! \
  'video/x-raw(memory:NVMM),format=RGBA,width=640,height=480,framerate=60/1' ! \
  nv3dsink sync=false processing-deadline=0
```

For AB24/RGBA capture, omit `capture-format` and `preview` and keep RGBA caps.
No conversion stage is needed before the NVIDIA sink.

## Validation and limits

NVMM allocation pitch and capacity must match the negotiated V4L2 buffer. The
source fails on mismatches instead of treating padding as image pixels. Camera
firmware format, V4L2 fourcc, byte order and surface format must agree; selecting
caps alone does not reconfigure a fixed-format EngineCore camera.

The target runner tests classic, forced NVMM and automatic selection separately,
records actual backend, CPU usage and surface metadata, and retains register
checks for cameras with the supported control interfaces. `--require-nvmm`
requires the hardware path for the tested format. Unsupported paths are explicit
not-applicable cases when that option is absent. `--current-format-only` limits
EngineCore tests to its active format.

Qualification covers capture, processing and display on the configuration listed
above. Grayscale checks include per-pixel GPU byte-order normalization and preview
scaling against the same captured input buffers. Other cameras, resolutions,
end-to-end latency and long-duration reliability require separate qualification.


When an NVMM path uses GPU processing or display, the monitor shows `gpu=...%`
after `cpu`. This is board-wide NVIDIA GPU activity, including other applications;
it excludes VIC and is not a per-process counter. The monitor reads the Jetson
nvgpu sysfs value at most once per second, without invoking tegrastats. An
unavailable reading appears as `--`; paths that do not use GPU omit the field.
Other platforms retain their existing monitoring behavior.
