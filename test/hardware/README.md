# Target camera regression


## Display contexts and framerate

`run_camera_regression.py` discovers a working local X11 session (or uses
`--display`/`--xauthority`). It checks the default, `--all-streaming-backends`
and JSON configuration outputs in local, forwarded-display selection and
no-DISPLAY contexts, then runs local and headless streaming tests.

A local X server is not proof that a monitor is connected. The runner checks
`xrandr --current` for a connected output with an active mode, and checks again
before each local rendering command. Without an active monitor or an accessible
local X server, local rendering is recorded as `not_run`, without a pass/fail
value; this does not fail the campaign. Raw capture, headless classic/NVMM,
register checks and pixel comparisons continue. Real forwarded X11 remains
independent and is tested when available.

The report includes `local_display`, `skipped_captures` and
`display_coverage_complete`; missing display tests make coverage incomplete.
Genuine capture failures, corrupted buffers and required headless NVMM failures
remain errors. `--no-local-display` explicitly selects this mode even with a
monitor attached, without changing display configuration. It cannot be combined
with `--display`.

For a complete real forwarded-X11 campaign, start it from an SSH session with
X11 forwarding and preserve the connection environment through sudo:

```sh
sudo --preserve-env=DISPLAY,XAUTHORITY,SSH_CONNECTION python3 run_camera_regression.py \
  --output /tmp/camera-regression --require-forwarded-x11
```

`--forwarded-display` and `--forwarded-xauthority` can specify the connection
explicitly. The runner verifies it with `xdpyinfo` before using it. Without a
working connection, the report records `not_run` and incomplete environment
coverage; `--require-forwarded-x11` makes that a failure. A synthetic DISPLAY
value is used only for selection/error checks, never as proof of remote rendering.

For EngineCore, `ECSwCtrl ... -c "rf 0x210"` supplies the reference framerate for
each format. Local/headless capture and processing rates must match within
`--fps-tolerance` (default3%). The first second is excluded and at least one
second of steady samples is required. `--frames` is a minimum, extended when
needed for this measurement. Rates come from buffer timestamps or the monitor's
measured cadence report, never from negotiated caps alone.

Forwarded rendering may be slower. Its rates and CPU usage remain recorded, but
lower cadence is not an error. `--forwarded-frames` defaults to60 to keep these
functional tests bounded. Failures to stream, wrong counts or failure to finish
remain errors. Both `v4l2src` and `egv4l2camerasrc` are exercised where applicable;
forced NVMM display on forwarded X11 must be rejected before device access.

## V4L2 utility versions and enumeration

The runner understands both the indexed format lists and compact buffer lines
from recent `v4l2-ctl` versions, and the `Pixel Format`/multiline buffer output
used on L4T 32.x. Timestamps and error flags are read in both presentations.
Duplicate formats or dimensions remain failed checks in `format_results` and
make the campaign unsuccessful; they do not prevent the remaining streaming
and camera tests from running.

## Temporary raw capture storage

Raw V4L2 checks keep complete frames to verify byte counts and sample integrity.
The runner prefers `/dev/shm` when both available filesystem space and physical
memory cover the estimated frame data plus 256 MiB of headroom. Otherwise it
uses the normal temporary directory. Each capture records the selected directory;
temporary frames are removed after validation.

This keeps slow eMMC writes out of the timed acquisition when memory permits.
The capture timeout, expected byte count, corruption checks and frame-rate limits
are unchanged.

## EngineCore format changes and recovery

EngineCore control commands are paced by at least 5 seconds by default
(`--ec-control-pause`). The general `--control-pause` remains 2 seconds for
other families; its larger values also apply to EngineCore. The runner waits
5 seconds after a camera reboot and another 5 seconds after driver probe,
in addition to the control pauses. Streaming commands retain their 3-second gap.

The runner reads the camera's `ru 0x260` value as well as the driver's cached
format before changing or restoring a format. A successful register write alone
does not prove that the camera has restarted with the requested output.

A reset can return `!-128` before its acknowledgement is received. The runner
records this as uncertain, waits for the camera, reloads `eg_ec_mipi`, and checks
both format values. It then validates actual streaming. A failed stream can
trigger bounded recovery; the original failure remains in the report. Other
control errors remain errors.

Raw capture tests write complete frames to a temporary file. For large images,
slow storage can limit the measured rate. Set `TMPDIR` to sufficiently large
fast storage, for example `sudo env TMPDIR=/dev/shm python3 ...` when RAM permits.
At 1280×1024, 180 RGB frames need 900 MiB; 180 Y16/YUYV frames need 450 MiB.
The file is removed after each capture. CPU measurements for these tests include
the file write and must not be compared with capture-only pipelines as if their
workloads were identical.

The monitor's `corrupt` counter is checked for both classic and NVMM captures.
A nonzero counter fails the test even if all requested frames arrive and the
process exits successfully. GStreamer CORRUPTED flags and V4L2 dequeued ERROR
buffers also fail, including buffers discarded by v4l2-ctl before writing the raw
file. An initial corrupted buffer is retained as a failure;
the runner does not silently exclude startup frames from integrity checks.

When generated grayscale commands contain `--normalize`, the runner additionally
checks the fixed-range default: classic and NVMM local previews, hardware
GStreamer with `normalize=false`, and classic forwarded display when available.
Headless runs keep the requested option to verify that it is ignored safely.

## Alternating and concurrent cameras

Run `run_camera_endurance.py` after the functional runner. It performs paced
start/stop cycles, simultaneous raw V4L2 streaming for `--seconds`, and a finite
multi-source NVMM check when the selected cameras have generated hardware paths.

```sh
sudo python3 run_camera_endurance.py --output /tmp/camera-endurance \
  --cycles 3 --frames 60 --seconds 30 --require-nvmm
```

The NVMM check uses one GStreamer process with independent branches and fakesinks.
It checks source and delivered buffer counts, corruption flags and measured
cadences independently for each camera. EngineCore reference rates come from
`rf 0x210`, with 5-second control pauses. No camera format is changed by this
runner: it tests the effective formats left by the functional campaign.
Counts and timestamps come from direct pad probes in the worker process,
recorded in `nvmm-telemetry.json`. Asynchronous verbose property messages are
not used as buffer counters. No image pixels are mapped for these checks.
Kernel-log review accepts eviction of old records only when an exact timestamped
overlap proves that the entire test window remains present; otherwise it fails.

`--nvmm-frames` defaults to 180 per branch; `--nvmm-timeout` defaults to 30 seconds
and may be extended for a known slow reference rate. This finite check does not
claim long-duration NVMM endurance. CPU accounting covers the whole GStreamer
process, all branches and threads, including startup/shutdown.

Missing plugin/unsupported camera paths or fewer than two selected cameras are
recorded as **not applicable**, never as an NVMM pass. `--require-nvmm` makes
that a campaign failure. `--skip-nvmm` explicitly requests raw tests only.
The command-selection probe uses a local-looking DISPLAY to obtain the generated
NVMM pipelines; actual captures remove DISPLAY and render nowhere. This is not
an X11/display validation. The functional runner supplies that separate coverage.


## Static-pattern pixel comparisons

The regression runner checks pixels by default when an NVMM path and a verified
camera-pattern profile are available. Install the test kit next to the runner:
`camera_patterns.py`, `compare_camera_pixels.py`, and the BSP-specific
`egNvmmPixelCapture` executable. Build the executable with the same source/toolchain
as the installed plugin:

```sh
python3 tools/jetson-hw-pipeline/build_camera_plugin.py \
  --source-dir sources/<L4T>/Linux_for_Tegra/source/gst-egv4l2camera \
  --sysroot <BSP>/rootfs --cxx <toolchain>/bin/aarch64-buildroot-linux-gnu-g++ \
  --output /path/to/new-test-build --pixel-checker
```

The diagnostic executable refuses a plugin with a different SHA256: it inspects
private capture-buffer fields and must match the plugin build. The optional
`egNvmmYuyvSynthetic` exercises the CUDA colour conversion with synthetic YUV
samples; compare its RGBA output with the monitor's `to_display_bgr()` function.
These diagnostic tools map pixels on the CPU. Their CPU cost is not a streaming
performance measurement; normal monitor/GStreamer benchmarks remain separate.

```sh
sudo python3 run_camera_regression.py --output /path/to/new-results \
  --pixel-checker /path/to/egNvmmPixelCapture --require-nvmm
# Repeat just the pixel/control checks, format changes and restoration:
sudo python3 run_camera_regression.py --output /path/to/new-pixel-results \
  --pixel-checker /path/to/egNvmmPixelCapture --pixels-only
```

`--skip-pixel-comparison` is an explicit opt-out, recorded as not run. Missing
checker files fail an applicable pixel check. Unsupported pattern profiles are
reported as not applicable; they are not claimed as tested.

The test obtains three classic frames and three NVMM frames of a static pattern,
after five warm-up buffers. It checks temporal stability and exact native sample
equality, excluding the unused alpha byte of RGB888 capture. It then compares the
actual classic monitor preview with GPU output: zero tolerance for fixed grayscale,
one 8-bit level for normalized grayscale, three levels for colour conversion.
Warm-up corruption is counted separately; corruption in compared frames fails.
Normal streaming tests continue to reject corrupted buffers from startup.
Reports include a compressed paired image archive and per-check mismatch counts.

### Pattern register profiles

| Camera | Registers used | Selection |
| --- | --- | --- |
| EngineCore | enable `0x190`, selector `0x194`, save `0x2F0`, reboot `0x8` via ECSwCtrl | `9` static pixel counter for Y16; `2` coarse horizontal gradient for RGB/YUYV |
| iLumos | selector `0x50000504`, moving `0x50000508`, shift `0x50000510`, source `0x50000A1C` | `4`, `0`, `0`, `1`: static input row/column counter |
| Dione | source `0x80108`, pattern control `0x8012C` | source `0`; selector `4` in bits3:0, moving bit15 cleared, shift bits7:4 cleared |

EngineCore input patterns0/1 are fine horizontal/vertical gradients,2/3 coarse
gradients,4 embedded coordinates,8 a static bordered gradient,9 a static counter.
Patterns5–7 vary with time and are unsuitable for independent capture comparisons.
The proxy patterns50–60 are camera-specific and are not selected automatically.

For every EngineCore pattern test, the runner records the original enable and
selector values, selects and enables the pattern, saves user settings bank0
(`wu 0x2F0 0`), and reboots the camera (`wu 0x8 1`). After the boot delay it
verifies the pixel format and both pattern registers before capturing. The driver
stays loaded because the video format is unchanged during this operation.

MicroCube firmware1.19.7 can produce an incomplete last line when a Y16 pattern
is activated while the camera is running. Loading the saved pattern at reboot
avoids this known issue, which is non-blocking with this procedure. Corruption
after reboot still fails validation; no EngineCore error flags are ignored.

For iLumos, the late output emulator at physical address`0x60010044` is kept
disabled during the test. Bit0 enables it; bit1 selects its pixel counter.
It is distinct from the input generator and is not a reliable independent RAW14
reference on the tested firmware. Physical registers are reached through GenCP
DebugControl: address`0x50003000`, value`0x50003004`, read trigger`0x50003008`,
write trigger`0x5000300C`. The debug latches are also restored.
The virtual acquisition-source setter updates the RAM settings shadow; this test
never saves a user set. Select and prime the pixel format before activating a pattern.

Original register values are recorded before modification and restored in a finally
path. For EngineCore, restoration also saves bank0, reboots, and verifies readback
so the original pattern state survives another restart. These tests therefore
write user settings; iLumos and Dione pattern transactions remain volatile.
A restoration failure stops the campaign before another format change/save and
is reported as a failure. EngineCore controls retain their five-second pauses.
Transient EngineCore read failures are logged and retried within the configured
recovery limit, with the same pause. An incorrect readback value still fails.
Pattern configuration is restored **before** changing/saving a video format.
Dione source and pattern-control fields are documented in the family ICD;
hardware qualification of a particular firmware still requires a target run.


### Temporary Dione startup policy

One corrupted **first** dequeued/source buffer on a Dione is recorded as a warning,
not a failed capture. Counts and positions remain in the report. A later corrupted
buffer, multiple corrupted buffers, or unknown error positions still fail. This
exception applies to V4L2, GStreamer and monitor checks; the monitor's general
exit policy remains strict, and the runner only accepts its specific corruption
exit after verifying the first-buffer telemetry and complete output counts.
The underlying startup issue remains open for investigation.
