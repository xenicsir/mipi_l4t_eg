# Target camera regression


## Display contexts and framerate

`run_camera_regression.py` discovers a working local X11 session (or uses
`--display`/`--xauthority`). It checks the default, `--all-streaming-backends`
and JSON configuration outputs in local, forwarded-display selection and
no-DISPLAY contexts, then runs local and headless streaming tests.

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
