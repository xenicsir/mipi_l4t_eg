#!/usr/bin/python3
import csv
import argparse
import json
import logging
import os
import platform
import queue
import re
import select
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict

import cv2  # requires to install python3-opencv Linux package (not libopencv-python)
import numpy as np

try:
    cv2.setLogLevel(0)   # silence OpenCV/GStreamer internal warnings (OpenCV ≥ 4.2)
except AttributeError:
    pass

log = logging.getLogger(__name__)

# Metric names written to CSV and used throughout the module (never loaded from JSON)
_STATS = ('mean', 'std', 'row_noise', 'col_noise')


# GStreamer / V4L2 format strings (Linux only — not user-configurable)
# Y10 is CameraLink/Euresys (Windows only) and has no Linux GStreamer mapping.
# Y14 has no entry in FORMAT_GST on purpose: GStreamer's GstVideoFormat has no
# 14-bit greyscale format at all (not a version gap like AR24/AB24 — verified
# absent in 1.20.3, and there's nothing to add it to). _open_capture_linux
# routes any fmt missing from FORMAT_GST to _V4L2RawStreamCapture instead of
# building a GStreamer pipeline for it.
FORMAT_GST  = {"Y16": "GRAY16_LE", "Y16_BE": "GRAY16_BE", "AR24": "BGRA", "AB24": "RGBA", "YUYV": "YUY2"}
FORMAT_V4L2 = {"Y16": "Y16 ",      "Y16_BE": "Y16 -BE",   "AR24": "AR24", "AB24": "AB24", "YUYV": "YUYV", "Y14": "Y14 "}
FORMAT_V4L2_REV = {v.strip(): k for k, v in FORMAT_V4L2.items()}  # actual V4L2 pixelformat -> our fmt name

# 16-bit single-channel raw formats: already fully decoded to native uint16 by
# capture time (see _GstAppSinkCapture._sample_to_array) — no color conversion,
# 2 bytes/pixel, display via straight normalization instead of clipping.
# Y14 is packed in the same 2-byte container (upper bits unused) — see
# _V4L2RawStreamCapture.
Y16_LIKE_FMTS = ("Y16", "Y16_BE", "Y10", "Y14")


class _NullWriter:
    def writerow(self, *args): pass


class _NullFile:
    closed = False
    def tell(self):   return 0
    def flush(self):  pass
    def close(self):  pass


class _MSMFY16FallbackCapture:
    """Captures Y16 frames via a YUYV MSMF stream with raw byte reinterpretation.

    MSMF rejects native Y16 UVC streams (MF_E_INVALIDMEDIATYPE) when the
    Windows UVC class driver cannot validate the sample format, even though
    the camera descriptor is correct. Opening as YUYV bypasses this check:
    MSMF delivers the raw Y16 bytes in a YUYV container and, with
    CONVERT_RGB=0, passes them through unmodified. We then view the buffer
    as uint16 to recover the 16-bit luminance values.
    """

    def __init__(self, cam_index: int, width: int, height: int, fps: int) -> None:
        cap = cv2.VideoCapture(cam_index, cv2.CAP_MSMF)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('Y', 'U', 'Y', 'V'))
        if not cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera {cam_index} via YUYV fallback for Y16 capture"
            )
        self._cap = cap
        # MSMF may silently negotiate a different size than requested (fixed-resolution
        # sensors) — query back what was actually granted, same as the Linux v4l2 path.
        self._width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or width
        self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
        log.info("Y16-via-YUYV fallback: camera %d  %dx%d @ %dfps", cam_index, self._width, self._height, fps)

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    def read(self):
        ret, frame = self._cap.read()
        if not ret:
            return False, None
        # Reinterpret raw bytes as little-endian uint16 Y16 data
        return True, np.frombuffer(frame.tobytes(), dtype='<u2').reshape(self._height, self._width)

    def release(self):
        self._cap.release()

    def isOpened(self):
        return self._cap.isOpened()


# ---------------------------------------------------------------------------
# _EuresysCLCapture  — CameraLink via Euresys GrabLink (camera_Euresys submodule)
# ---------------------------------------------------------------------------

class _EuresysCLCapture:
    """CameraLink frame grabber using GrabLink from the camera_Euresys submodule.

    Requires the submodule to be initialized:
        git submodule update --init --recursive

    Exposes self.pixel_fmt with the format string from the .cam file
    (e.g. "Y10", "Y8", "Y16", "RGB24").

    board_index   → board selection index (0 for the first/only board).
    multicam_file → path to the .cam file configuring the frame grabber.
    """

    _TIMEOUT_MS = 200

    def __init__(self, board_index: int, width: int, height: int,
                 multicam_file: Optional[str]) -> None:
        if not multicam_file:
            raise ValueError("multicam_file is required for CameraLink capture.")

        multicam_file = os.path.abspath(multicam_file)

        try:
            import sys as _sys
            from ctypes import byref as _byref
            _euresys_src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'camera_Euresys', 'src')
            if _euresys_src not in _sys.path:
                _sys.path.insert(0, _euresys_src)
            from EURESYS.Grablink import GrabLink as _GrabLink, SURFACE as _SURFACE
            from EURESYS import MultiCam as _MC
        except ImportError as exc:
            raise ImportError(
                "camera_Euresys submodule not found. "
                "Run: git submodule update --init --recursive"
            ) from exc

        self._width  = width
        self._height = height

        gbl = _GrabLink()
        # Set board instance directly to avoid linkBoard's open→close→reopen cycle,
        # which leaves the board in a state where ChannelState=ACTIVE blocks.
        gbl.Board.instance = _MC.BOARD + board_index
        gbl.createChannel(CamFile=multicam_file, channelName='ch0')
        self._gbl = gbl
        chan = gbl.ch['ch0']
        ch   = chan.instance

        self.pixel_fmt = _MC.GetParamStr(ch, 'ColorFormat').decode('ascii', errors='replace')

        _MC.SetParamStr(ch, 'GrabWindow',   'MAN')
        _MC.SetParamInt(ch, 'WindowX_Px',   width)
        _MC.SetParamInt(ch, 'WindowY_Ln',   height)
        _MC.SetParamInt(ch, 'SeqLength_Fr', _MC.INFINITE)
        _MC.SetParamStr(ch, _MC.SignalEnable + _MC.SIG_SURFACE_FILLED, 'ON')

        chan.ChannelState = 'READY'
        chan.ChannelState = 'ACTIVE'

        self._chan   = chan
        self._MC     = _MC
        self._SURFACE = _SURFACE
        self._byref  = _byref
        self._unpack = _GrabLink.UnpackImageBuffer
        self._no_frame_count = 0
        self._no_frame_since = 0.0
        log.info("Euresys CameraLink (GrabLink): board=%d  %dx%d  %s  cam=%s",
                 board_index, width, height, self.pixel_fmt, multicam_file)

    def read(self):
        MC   = self._MC
        info = MC.MCSIGNALINFO()
        st   = MC.McWaitSignal(self._chan.instance, MC.SIG_SURFACE_FILLED,
                               self._TIMEOUT_MS, self._byref(info))
        if st != 0:
            if self._no_frame_count == 0:
                self._no_frame_since = time.perf_counter()
            self._no_frame_count += 1
            elapsed = time.perf_counter() - self._no_frame_since
            if self._no_frame_count % 15 == 0:
                log.error(
                    "No frames from CameraLink for %.1fs (status=%d) — "
                    "board already in use by another process?",
                    elapsed, st,
                )
            time.sleep(0.01)
            return False, None
        self._no_frame_count = 0

        surf = self._SURFACE(info.SignalInfo)
        raw  = surf.get_DataNoUnpacking()
        return True, self._unpack(raw, self.pixel_fmt, self._width, self._height)

    def release(self):
        try:
            self._chan.ChannelState = 'IDLE'
            self._chan.delete()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ConfigFPN  — all FPN-related parameters in one place
# ---------------------------------------------------------------------------

@dataclass
class ConfigFPN:
    """All parameters that control FPN spike detection.

    Separation rationale
    --------------------
    Grouping FPN parameters here keeps ``Config`` focused on camera / I-O
    concerns and makes it easy to pass *only* the FPN configuration to
    ``FpnDetector`` without threading unrelated fields through.

    Fixed vs. adaptive threshold
    ----------------------------
    When ``adaptive=False`` the per-metric fixed thresholds
    (``threshold_std``, ``threshold_row``, ``threshold_col``) are used
    directly as the detection floor.

    When ``adaptive=True`` the effective threshold becomes::

        max(fixed_threshold,  baseline_median + adaptive_k × baseline_MAD)

    where median and MAD are computed over a rolling window of past
    ``window``-std values (``baseline_window`` samples).  The fixed
    threshold therefore always acts as a *minimum sensitivity floor* —
    the adaptive value can only make detection *stricter*, never more
    permissive than the hand-tuned floor.

    Until ``baseline_min_frames`` samples have been collected the fixed
    threshold is used as a fallback so detection is operational from the
    very first frame.
    """

    enabled:             bool           = False  # master switch (replaces fpn_detect param)

    # Detection window
    window:              int            = 60     # sliding window size in frames

    # Fixed per-metric window-std thresholds
    # Calibrated at 5× worst-case steady-state σ across three cameras.
    threshold_std:       float          = 1.0
    threshold_row:       float          = 2.0
    threshold_col:       float          = 2.5

    # Event capture width
    event_half:          int            = 5      # frames each side of spike centre (11 total)

    # Adaptive threshold
    adaptive:            bool           = False  # enable adaptive threshold
    adaptive_k:          float          = 10.0   # multiplier: median + k × MAD
    baseline_window:     int            = 300    # rolling baseline length (frames)
    baseline_min_frames: int            = 60     # min samples before adaptive activates

    @classmethod
    def from_dict(cls, data: dict) -> "ConfigFPN":
        """Build a ConfigFPN from a flat dict (e.g. from a JSON config file).

        Accepted keys use the ``fpn_`` prefix that the JSON config files use::

            fpn_window, fpn_threshold_std, fpn_threshold_row, fpn_threshold_col,
            fpn_event_half, fpn_adaptive, fpn_adaptive_k,
            fpn_baseline_window, fpn_baseline_min_frames, fpn_enabled
        """
        _MAP = {
            "fpn_enabled":             "enabled",
            "fpn_window":              "window",
            "fpn_threshold_std":       "threshold_std",
            "fpn_threshold_row":       "threshold_row",
            "fpn_threshold_col":       "threshold_col",
            "fpn_event_half":          "event_half",
            "fpn_adaptive":            "adaptive",
            "fpn_adaptive_k":          "adaptive_k",
            "fpn_baseline_window":     "baseline_window",
            "fpn_baseline_min_frames": "baseline_min_frames",
        }
        valid  = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {}
        for json_key, field_name in _MAP.items():
            if json_key in data and field_name in valid:
                kwargs[field_name] = data[json_key]
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# FpnDetector  — mutable runtime state + core algorithm
# ---------------------------------------------------------------------------

# Internal keys for the three monitored metrics
_FPN_KEYS  = ('std', 'row_noise', 'col_noise')
_FPN_SHORT = {'std': 'std', 'row_noise': 'row', 'col_noise': 'col'}

@dataclass
class FpnTrigger:
    """Result returned by FpnDetector.update() for one triggered metric."""
    key:        str    # 'std' | 'row_noise' | 'col_noise'
    center_ts:  float  # timestamp_s of the spike frame
    center_val: float  # metric value at the spike frame
    wstd:       float  # window std that crossed the threshold
    eff_thresh: float  # effective threshold that was used
    thresh_tag: str    # 'fixed' | 'fixed(warmup)' | 'adaptive'


class FpnDetector:
    """Encapsulates all mutable state and the core algorithm for FPN spike detection.

    Usage
    -----
    ::

        detector = FpnDetector(cfg_fpn)

        # once per frame:
        triggers = detector.update(results, ts)
        # triggers is a list of FpnTrigger (empty when no spike detected)

        # on camera freeze / reopen:
        detector.reset()

    The detector is intentionally **free of I/O** — it only computes and
    returns trigger information.  All logging, frame saving, and event
    dispatching remain in ``camera_main_loop``.
    """

    def __init__(self, cfg: ConfigFPN) -> None:
        self.cfg         = cfg
        self._half       = cfg.window // 2
        self.spike_count = 0

        self._thresholds: Dict[str, float] = {
            'std':       cfg.threshold_std,
            'row_noise': cfg.threshold_row,
            'col_noise': cfg.threshold_col,
        }

        # Detection sliding windows (values + timestamps)
        self._val_bufs: Dict[str, deque] = {
            k: deque(maxlen=cfg.window) for k in _FPN_KEYS
        }
        self._ts_bufs: Dict[str, deque] = {
            k: deque(maxlen=cfg.window) for k in _FPN_KEYS
        }

        # Per-metric cooldown counters (frames remaining before re-detection allowed)
        self._cooldowns: Dict[str, int] = {k: 0 for k in _FPN_KEYS}

        # Adaptive baseline buffers (one scalar _wstd per frame, not images)
        self._baseline_bufs: Dict[str, deque] = (
            {k: deque(maxlen=cfg.baseline_window) for k in _FPN_KEYS}
            if cfg.adaptive else {}
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def half(self) -> int:
        """Half-window size — needed by the main loop to size ``frame_buf``."""
        return self._half

    def reset(self) -> None:
        """Clear all sliding windows and cooldowns (call on camera freeze / reopen)."""
        for buf in self._val_bufs.values():
            buf.clear()
        for buf in self._ts_bufs.values():
            buf.clear()
        for k in self._cooldowns:
            self._cooldowns[k] = 0
        for buf in self._baseline_bufs.values():
            buf.clear()

    def update(self, results: dict, ts: float) -> List[FpnTrigger]:
        """Feed one frame of metric results and return any triggered spikes.

        Parameters
        ----------
        results:
            Dict with keys ``'std'``, ``'row_noise'``, ``'col_noise'``
            (and optionally ``'mean'`` — ignored here).
        ts:
            Timestamp in seconds of the current frame.

        Returns
        -------
        List of :class:`FpnTrigger`, one per triggered metric.
        Empty list when no spike is detected this frame.
        """
        cfg  = self.cfg
        half = self._half

        # Step 1 — append to detection windows
        for k in _FPN_KEYS:
            self._val_bufs[k].append(results[k])
            self._ts_bufs[k].append(ts)

        triggers: List[FpnTrigger] = []

        for k in _FPN_KEYS:
            vbuf = self._val_bufs[k]
            if len(vbuf) < cfg.window:
                continue  # window not yet full

            # np.fromiter pre-allocates — faster than list+array conversion
            vals = np.fromiter(vbuf, dtype=np.float64, count=cfg.window)
            wstd = float(vals.std())

            # Step 2 — always feed baseline (even during cooldown, so it warms up)
            if cfg.adaptive:
                self._baseline_bufs[k].append(wstd)

            # Step 3 — cooldown gate
            if self._cooldowns[k] > 0:
                self._cooldowns[k] -= 1
                continue

            # Step 4 — resolve effective threshold
            fixed = self._thresholds[k]
            if cfg.adaptive:
                bbuf = self._baseline_bufs[k]
                if len(bbuf) >= cfg.baseline_min_frames:
                    base      = np.fromiter(bbuf, dtype=np.float64, count=len(bbuf))
                    med       = float(np.median(base))
                    mad       = float(np.median(np.abs(base - med)))
                    adaptive  = med + cfg.adaptive_k * mad
                    # fixed threshold is always the minimum floor
                    eff_thresh = max(fixed, adaptive)
                    thresh_tag = "adaptive"
                else:
                    eff_thresh = fixed
                    thresh_tag = "fixed(warmup)"
            else:
                eff_thresh = fixed
                thresh_tag = "fixed"

            # Step 5 — spike condition: window-std exceeds threshold AND
            #           the maximum value sits exactly at the window centre
            peak = int(vals.argmax())
            if wstd > eff_thresh and peak == half:
                triggers.append(FpnTrigger(
                    key        = k,
                    center_ts  = self._ts_bufs[k][half],
                    center_val = float(vbuf[half]),
                    wstd       = wstd,
                    eff_thresh = eff_thresh,
                    thresh_tag = thresh_tag,
                ))

        if triggers:
            self.spike_count += 1
            for t in triggers:
                self._cooldowns[t.key] = half  # lock out re-detection for fpn_half frames

        return triggers


# ---------------------------------------------------------------------------
# Config  (camera / I-O level — FPN delegated to ConfigFPN)
# ---------------------------------------------------------------------------

@dataclass
class Config:
    # Camera
    cam_index:              int            = 0
    device:                 str            = "/dev/video0"  # V4L2 device path (Linux) or ignored on Windows
    target_fps:             int            = 60
    height:                 int            = 480
    width:                  int            = 640
    num_frames:             Optional[int]  = None    # None / <=0 = infinite

    # Image saving
    save_images:            bool           = False
    image_format:           str            = "tif"   # "tif" | "raw"

    # FPN spike detection — all parameters delegated to ConfigFPN
    fpn:                    ConfigFPN      = field(default_factory=ConfigFPN)

    # event capture width (shared by drop detection and FPN)
    event_half:             int            = 5

    # Queue / storage limits
    save_queue_maxsize:     int            = 10      # max pending save tasks in FIFO
    max_save_mb:            float          = 0       # global session dir limit in MiB (0 = unlimited)
    max_frames_mb:          Optional[float]= None    # event frames only; None = same as max_save_mb
    max_log_lines:          int            = 0       # max rows per rt_log CSV segment (0 = unlimited)

    # Freeze / reopen
    freeze_threshold_s:     float          = 1.0    # gap > this (s) → camera_freeze event
    freeze_recovery_frames: int            = 5      # consecutive normal frames to exit freeze state
    reopen_interval_s:      float          = 2.0    # how often (s) to retry reopening after grab failure

    # Optional base directory for run outputs
    base_dir:               Optional[str]  = None

    # Pixel format
    fmt:                    Optional[str]  = None    # Pixel format ("Y16", "Y16_BE", "Y14", "AR24", "AB24", "YUYV", "Y10");
                                                      # None (Linux only) = don't force one, read the device's current format

    # CameraLink — path to the Euresys .cam configuration file (triggers CL mode)
    multicam_file:          Optional[str]  = None

    # Drop detection
    drop_detect:            bool           = False   # count and log dropped frames

    # CSV logging
    log_enabled:            bool           = False   # write rt_log + events_log to disk

    # Live display
    show_video:             bool           = False   # show live video window (ignored in test mode)
    # Resizable by default (WINDOW_NORMAL + resizeWindow). On this platform's
    # GTK/X11 backend this costs ~2x the display fps (60->26 at 1280x1024) —
    # pass --no-resize (window_autosize=True) for a fixed-size WINDOW_AUTOSIZE
    # window and the full capture framerate when that trade-off matters more
    # than mouse-resizing the preview.
    window_autosize:         bool           = False

    # Stats (mean/std/row_noise/col_noise) are OFF by default: computing and
    # printing them on the status line is the main cost of the display loop
    # (see compte-rendu §12). Only frame/ts/dt/fps (+ cam_fps, image if
    # --display) are produced by default. Pass --stats to force them on, or
    # just pass --log / --fpn-detect / --drop-detect, which need the stats
    # (or the gray buffer) internally and enable them automatically.
    stats:                  bool           = False

    @classmethod
    def from_json(cls, path: str) -> "Config":
        """Load a Config from *path*, filling any missing keys with class defaults."""
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            log.info("Config loaded from %s", path)
        except FileNotFoundError:
            log.warning("Config file not found: %s — using defaults", path)
            data = {}
        except json.JSONDecodeError as exc:
            log.warning("Config file parse error (%s): %s — using defaults", path, exc)
            data = {}

        # Keys that belong to ConfigFPN (prefixed with fpn_)
        fpn_obj = ConfigFPN.from_dict(data)

        # Keys that belong directly to Config (exclude fpn_ prefixed ones)
        _FPN_JSON_KEYS = {
            "fpn_enabled", "fpn_window",
            "fpn_threshold_std", "fpn_threshold_row", "fpn_threshold_col",
            "fpn_event_half", "fpn_adaptive", "fpn_adaptive_k",
            "fpn_baseline_window", "fpn_baseline_min_frames",
        }
        valid   = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        valid  -= {"fpn"}   # handled separately above
        filtered = {k: v for k, v in data.items()
                    if k in valid and k not in _FPN_JSON_KEYS}
        unknown  = set(data) - valid - _FPN_JSON_KEYS
        if unknown:
            log.warning("Unknown config keys (ignored): %s", sorted(unknown))
        return cls(fpn=fpn_obj, **filtered)


# Module-level defaults instance — pure dataclass defaults, no JSON loaded
default_cfg = Config()


# ---------------------------------------------------------------------------
# Capture backends
# ---------------------------------------------------------------------------

class _GstAppSinkCapture:
    """Direct GStreamer capture via PyGObject, bypassing cv2.VideoCapture.

    OpenCV 4.2.0's GStreamer backend (cap_gstreamer.cpp) hardcodes the caps
    it will accept on its internal appsink to
    {UYVY, YUY2, YVYU, NV12, NV21, YV12, I420}, regardless of the caps string
    passed to cv2.VideoCapture. A sensor that only ever declares Y16/Y16-BE/
    Y14 to V4L2 (no YUYV) can therefore never negotiate through OpenCV — the
    caps intersection is always empty ("Internal data stream error") — even
    though the identical pipeline opens fine with gst-launch-1.0 or any other
    appsink consumer, since those have no such restriction. This class talks
    to GStreamer directly so the restriction does not apply.
    """

    # gst_fmt -> (read dtype, channels). Assumes packed, unpadded rows
    # (bytesperline == width * itemsize * channels), true for v4l2src with
    # these formats. Read dtype carries the wire byte order for 16-bit
    # formats; _sample_to_array() converts to native order right after, so
    # everything downstream sees plain native uint16 regardless of source.
    _GST_FMT_NP = {
        "GRAY16_LE": (np.dtype("<u2"), 1),
        "GRAY16_BE": (np.dtype(">u2"), 1),
        "YUY2":      (np.dtype("u1"), 2),
        "BGRA":      (np.dtype("u1"), 4),
        "RGBA":      (np.dtype("u1"), 4),
    }

    def __init__(self, device, gst_fmt, width, height, pull_timeout_s=3.0, pixel_fmt=None):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise RuntimeError(
                "PyGObject GStreamer bindings not found — install with: "
                "sudo apt-get install python3-gi gir1.2-gst-plugins-base-1.0"
            ) from exc
        if gst_fmt not in self._GST_FMT_NP:
            raise ValueError(f"Unsupported GStreamer format for direct capture: {gst_fmt}")

        self._Gst = Gst
        self._dtype, self._channels = self._GST_FMT_NP[gst_fmt]
        self._width, self._height = width, height
        # App-level format name (e.g. "Y16_BE"), as opposed to gst_fmt which is
        # only the GStreamer caps string used to pick the read dtype above —
        # they differ for the YUYV-reinterpretation quirk paths in
        # _open_capture_linux, where gst_fmt=="YUY2" but pixel_fmt stays "Y16"
        # so to_luma()/Y16_LIKE_FMTS still treat the frame as 16-bit luma.
        self.pixel_fmt = pixel_fmt if pixel_fmt is not None else gst_fmt
        self._pull_timeout = int(pull_timeout_s * Gst.SECOND)
        self._opened = False
        self._first_sample = None

        # Frames leaving v4l2src, i.e. the true camera/hardware capture rate —
        # counted upstream of the "queue ... leaky=downstream" + "appsink
        # drop=true", so it stays accurate even when the app can't drain the
        # appsink fast enough and frames get silently dropped before read().
        self._capture_times = deque(maxlen=120)
        self._capture_total = 0
        self._capture_lock = threading.Lock()

        Gst.init(None)
        pipeline_str = (
            f"v4l2src name=src device={device} ! "
            f"video/x-raw,format={gst_fmt},width={width},height={height} ! "
            f"queue max-size-buffers=2 leaky=downstream ! "
            f"appsink name=sink max-buffers=2 drop=true sync=false"
        )
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._sink = self._pipeline.get_by_name("sink")
        self._bus = self._pipeline.get_bus()
        self._pipeline.get_by_name("src").get_static_pad("src").add_probe(
            Gst.PadProbeType.BUFFER, self._on_src_buffer
        )

        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self._pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(f"Cannot start GStreamer pipeline for {device} ({gst_fmt})")

        # Prime the pipeline with an actual pull — this is the only reliable way to
        # observe a downstream negotiation failure, which GStreamer reports
        # asynchronously via the bus shortly after the state reaches PLAYING.
        sample = self._sink.emit("try-pull-sample", self._pull_timeout)
        if sample is None:
            detail = ""
            err_msg = self._bus.timed_pop_filtered(0, Gst.MessageType.ERROR)
            if err_msg is not None:
                gerr, _debug = err_msg.parse_error()
                detail = f": {gerr.message}"
            self._pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(f"Cannot open {device} via GStreamer ({gst_fmt}){detail}")

        self._first_sample = sample
        self._opened = True
        log.info("Direct GStreamer capture: %s  %dx%d  format=%s", device, width, height, gst_fmt)

    def _on_src_buffer(self, pad, info):
        # Runs on the GStreamer streaming thread, not the caller's thread.
        with self._capture_lock:
            self._capture_times.append(time.monotonic())
            self._capture_total += 1
        return self._Gst.PadProbeReturn.OK

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    @property
    def capture_fps(self):
        """True camera capture rate (frames/s leaving v4l2src), independent
        of how fast the caller drains read() — see _on_src_buffer."""
        with self._capture_lock:
            times = list(self._capture_times)
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return (len(times) - 1) / span if span > 0 else 0.0

    @property
    def capture_total(self):
        with self._capture_lock:
            return self._capture_total

    def _sample_to_array(self, sample):
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(self._Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            # astype() to the native byte order both copies (detaching from
            # mapinfo.data, which is invalid after unmap()) and normalizes
            # away any non-native byte order (e.g. GRAY16_BE) in one step —
            # downstream code and OpenCV calls can then assume plain
            # native-order uint16/uint8, never a foreign byte order.
            arr = np.frombuffer(mapinfo.data, dtype=self._dtype).astype(self._dtype.newbyteorder("="))
        finally:
            buf.unmap(mapinfo)
        expected = self._height * self._width * self._channels
        if arr.size != expected:
            raise RuntimeError(
                f"Unexpected GStreamer buffer size: got {arr.size} {self._dtype.name} "
                f"samples, expected {expected} ({self._height}x{self._width}x{self._channels})"
            )
        shape = (self._height, self._width) if self._channels == 1 \
            else (self._height, self._width, self._channels)
        return arr.reshape(shape)

    def read(self):
        if not self._opened:
            return False, None
        if self._first_sample is not None:
            sample, self._first_sample = self._first_sample, None
        else:
            sample = self._sink.emit("try-pull-sample", self._pull_timeout)
        if sample is None:
            return False, None
        arr = self._sample_to_array(sample)
        return (arr is not None), arr

    def release(self):
        if self._opened:
            self._pipeline.set_state(self._Gst.State.NULL)
            self._opened = False

    def isOpened(self):
        return self._opened


class _V4L2RawStreamCapture:
    """Raw V4L2 capture via a piped `v4l2-ctl --stream-mmap --stream-to=-`
    subprocess, for pixel formats GStreamer has no video/x-raw representation
    for at all — currently just Y14 (GstVideoFormat has no 14-bit greyscale
    entry in any version, and spoofing GRAY16_LE while the camera is actually
    in Y14 corrupts the capture: the Y14/Y16 DT modes use different
    pix_clk_hz, and the driver never reprograms the physical sensor to match
    a V4L2-side format switch).

    stdout carries nothing but concatenated raw frames back-to-back — no
    per-frame header (verified empirically: N frames = exactly N *
    width*height*2 bytes on stdout; v4l2-ctl's progress dots go to stderr).
    2 bytes/pixel, uint16 LE, same physical container as Y16 — to_luma()
    handles it via Y16_LIKE_FMTS, no reinterpretation needed here.

    Assumes the device is already configured for this format/resolution:
    the caller in _open_capture_linux always does VIDIOC_S_FMT + read-back
    before constructing this, so no --set-fmt-video is passed here — just
    stream whatever is currently active.
    """

    def __init__(self, device, width, height, pixel_fmt, pull_timeout_s=3.0):
        self._width, self._height = width, height
        self.pixel_fmt = pixel_fmt
        self._frame_bytes = width * height * 2
        self._pull_timeout = pull_timeout_s

        self._proc = subprocess.Popen(
            ["v4l2-ctl", f"--device={device}", "--stream-mmap", "--stream-to=-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._opened = True
        self._capture_times = deque(maxlen=120)
        self._capture_total = 0

        # Prime with an actual read so a device that can't stream this format
        # fails fast at construction, like _GstAppSinkCapture's try-pull-sample.
        ok, _ = self._read_frame()
        if not ok:
            stderr = self._proc.stderr.read().decode(errors="replace").strip()
            self.release()
            detail = f": {stderr}" if stderr else ""
            raise RuntimeError(f"Cannot stream {device} via v4l2-ctl ({pixel_fmt}){detail}")

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    @property
    def capture_fps(self):
        times = list(self._capture_times)
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return (len(times) - 1) / span if span > 0 else 0.0

    @property
    def capture_total(self):
        return self._capture_total

    def _read_frame(self):
        buf = bytearray()
        deadline = time.monotonic() + self._pull_timeout
        while len(buf) < self._frame_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, None
            ready, _, _ = select.select([self._proc.stdout], [], [], remaining)
            if not ready:
                return False, None
            chunk = self._proc.stdout.read(self._frame_bytes - len(buf))
            if not chunk:   # subprocess exited / pipe closed
                return False, None
            buf.extend(chunk)
        self._capture_times.append(time.monotonic())
        self._capture_total += 1
        arr = np.frombuffer(bytes(buf), dtype="<u2").reshape(self._height, self._width)
        return True, arr

    def read(self):
        if not self._opened:
            return False, None
        return self._read_frame()

    def release(self):
        if self._opened:
            self._opened = False
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

    def isOpened(self):
        return self._opened


def _v4l2_get_fmt(device):
    """Parse `v4l2-ctl --get-fmt-video` for the currently active width/height/pixelformat.
    Any of the three is None if its line couldn't be parsed."""
    out = subprocess.run(
        ["v4l2-ctl", f"--device={device}", "--get-fmt-video"],
        capture_output=True, text=True, check=True
    ).stdout
    m = re.search(r"Width/Height\s*:\s*(\d+)/(\d+)", out)
    width, height = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    m = re.search(r"Pixel Format\s*:\s*'([^']*)'", out)
    pixelformat = m.group(1) if m else None
    return width, height, pixelformat


def _open_capture_linux(device, fmt, width, height, fps, multicam_file=None):
    """Set V4L2 format with v4l2-ctl, then open a direct GStreamer pipeline
    (see _GstAppSinkCapture — cv2.VideoCapture's GStreamer backend can't be
    used here since it never negotiates Y16/GRAY16_LE).

    fmt=None: don't force anything via VIDIOC_S_FMT at all — just read back
    whatever the device is currently configured for (both resolution and
    pixel format) and use that as-is. Survives a driver/framework change to
    the camera's declared native format with no --fmt update needed, at the
    cost of depending on whatever a previous process (or the driver's power-on
    default) left the device in.

    fmt=<explicit>: fixed-resolution/fixed-format sensors (e.g. iLumos, MIPI)
    silently ignore parts of VIDIOC_S_FMT that don't match what they actually
    support — v4l2-ctl reports "invalid" on stderr but still exits 0, leaving
    the device wherever it already was, rather than raising. --get-fmt-video
    right after --set-fmt-video reports what's actually active (size *and*
    pixel format), so an unhonoured request self-corrects to reality instead
    of building a GStreamer pipeline for a format the device isn't producing
    (caps mismatch -> "Internal data stream error"). A --fmt that the device
    *does* accept is never touched — this only fires when the request
    silently failed.

    Either way the caller picks up the (possibly corrected) resolution and
    pixel format via cap.width/cap.height/cap.pixel_fmt.

    For Y16/Y16_BE: detects the UVC driver quirk where VIDIOC_S_FMT always
    returns YUYV regardless of the requested format (camera firmware bug —
    the camera correctly declares the 16-bit format in USB descriptors but
    responds with YUYV after format COMMIT). In that case, captures as raw
    YUY2 (accepted by the driver); to_luma() reinterprets the (H, W, 2)
    uint8 buffer as uint16 — the actual Y16 bytes from the camera. This is
    checked *before* the generic pixel-format correction above, since that
    generic path would otherwise treat the YUYV bytes as real YUYV color
    instead of raw reinterpreted 16-bit luma.
    """
    if multicam_file:
        raise RuntimeError("CameraLink via Euresys MultiCam is only supported on Windows")

    # v4l2-ctl accepts a bare number as shorthand for /dev/video<N> (e.g. -d 1),
    # but GStreamer's v4l2src "device" property does not: it treats "1" as a
    # literal (relative) path and fails with "Cannot identify device '1'" /
    # "No such file or directory". Normalize once, up front, so both the
    # v4l2-ctl calls below and the GStreamer pipeline agree on the same device.
    if device.isdigit():
        device = f"/dev/video{device}"

    if fmt is None:
        actual_width, actual_height, actual_pf = _v4l2_get_fmt(device)
        if actual_width is None:
            raise RuntimeError(f"Could not read the current V4L2 format for {device}")
        fmt = FORMAT_V4L2_REV.get((actual_pf or "").strip())
        if fmt is None:
            raise RuntimeError(
                f"{device} is currently set to pixel format {actual_pf!r}, which "
                f"rt_frame_monitor has no decoder for. Pass --fmt explicitly."
            )
        log.info("%s: no --fmt given — using currently active %s (%dx%d)",
                  device, fmt, actual_width, actual_height)
        if fmt not in FORMAT_GST:
            return _V4L2RawStreamCapture(device, actual_width, actual_height, pixel_fmt=fmt)
        return _GstAppSinkCapture(device, FORMAT_GST[fmt], actual_width, actual_height, pixel_fmt=fmt)

    pf = FORMAT_V4L2[fmt]      # module-level dict (not in Config)
    subprocess.run(
        ["v4l2-ctl", f"--device={device}",
         f"--set-fmt-video=width={width},height={height},pixelformat={pf}"],
        check=True
    )

    actual_width, actual_height, actual_pf = _v4l2_get_fmt(device)
    if actual_width is not None:
        if (actual_width, actual_height) != (width, height):
            log.info("%s negotiated %dx%d (requested %dx%d) — using actual size",
                      device, actual_width, actual_height, width, height)
        width, height = actual_width, actual_height
    else:
        log.warning("Could not parse negotiated resolution for %s — using requested %dx%d",
                    device, width, height)

    if actual_pf is not None and actual_pf.strip() != pf.strip():
        if fmt in Y16_LIKE_FMTS and actual_pf.strip() == FORMAT_V4L2["YUYV"].strip():
            log.info("UVC %s driver quirk detected — capturing raw YUY2 bytes for %s", fmt, device)
            return _GstAppSinkCapture(device, "YUY2", width, height, pixel_fmt=fmt)
        actual_fmt = FORMAT_V4L2_REV.get(actual_pf.strip())
        if actual_fmt is None:
            raise RuntimeError(
                f"{device} did not accept the requested pixel format {pf!r} "
                f"(--fmt {fmt}) and is instead delivering {actual_pf!r}, which "
                f"rt_frame_monitor has no decoder for. Pass a matching --fmt, or "
                f"check the camera framework's pixel format declaration."
            )
        log.info("%s did not accept %r (--fmt %s) — delivering %r instead, using --fmt %s",
                  device, pf, fmt, actual_pf, actual_fmt)
        fmt = actual_fmt
    elif actual_pf is None:
        log.warning("Could not parse negotiated pixel format for %s — using requested %s",
                    device, fmt)

    if fmt not in FORMAT_GST:
        return _V4L2RawStreamCapture(device, width, height, pixel_fmt=fmt)

    gst_fmt = FORMAT_GST[fmt]
    try:
        return _GstAppSinkCapture(device, gst_fmt, width, height, pixel_fmt=fmt)
    except RuntimeError:
        if fmt not in Y16_LIKE_FMTS:
            raise
        log.info("%s unavailable — falling back to YUY2 reinterpretation for %s", gst_fmt, device)
        return _GstAppSinkCapture(device, "YUY2", width, height, pixel_fmt=fmt)


def _open_capture_windows(cam_index, fmt, width, height, fps, multicam_file=None):
    """Open capture via MSMF (Y16/YUYV/AR24) or Euresys MultiCam (CameraLink)."""
    if fmt is None:
        raise RuntimeError(
            "--fmt is required on Windows (MSMF has no equivalent of reading back "
            "the device's current V4L2 format without first requesting one)."
        )
    if multicam_file:
        # Run init in a thread: MultiCam ChannelState=ACTIVE can block indefinitely
        # if the board is already held by another process, with no error returned.
        _cap_holder   = [None]
        _error_holder = [None]
        _done         = threading.Event()

        def _try_open():
            try:
                _cap_holder[0] = _EuresysCLCapture(cam_index, width, height, multicam_file)
            except Exception as exc:
                _error_holder[0] = exc
            finally:
                _done.set()

        t = threading.Thread(target=_try_open, daemon=True)
        t.start()
        if not _done.wait(timeout=3.0):
            log.error(
                "CameraLink init timed out (3 s) — board already in use by another "
                "process. Kill the other instance via Task Manager then retry."
            )
            os._exit(1)
        if _error_holder[0] is not None:
            raise _error_holder[0]
        return _cap_holder[0]
    cap = cv2.VideoCapture(cam_index, cv2.CAP_MSMF)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    if fmt == "Y16":
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('Y', '1', '6', ' '))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera index {cam_index}")
        ret, _ = cap.read()
        if not ret:
            # MSMF accepts Y16 media type but fails to deliver samples
            # (MF_E_INVALIDMEDIATYPE on OnReadSample). Fall back to opening
            # as YUYV and reinterpreting raw bytes as uint16 Y16 data.
            log.warning(
                "MSMF cannot stream Y16 natively — switching to YUYV-as-Y16 fallback."
            )
            cap.release()
            time.sleep(0.5)   # let MSMF fully release before reopening
            return _MSMFY16FallbackCapture(cam_index, width, height, fps)
    elif fmt == "YUYV":
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('Y', 'U', 'Y', 'V'))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {cam_index}")
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join(chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4))
    note = (
        "  [Y16 bytes in non-native container — Windows UVC driver cannot stream Y16 directly]"
        if fmt == "Y16" and not fourcc_str.startswith("Y16")
        else ""
    )
    # MSMF may silently negotiate a different size than requested (fixed-resolution
    # sensors) — query back what was actually granted, same as the Linux v4l2 path.
    cap.width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or width
    cap.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
    log.info("%dx%d @ %dfps  FOURCC=%r%s",
             cap.width, cap.height,
             int(cap.get(cv2.CAP_PROP_FPS)),
             fourcc_str, note)
    return cap


def open_capture(cam_index, device, fmt, width, height, fps, multicam_file=None):
    if platform.system() == "Linux":
        return _open_capture_linux(device, fmt, width, height, fps, multicam_file)
    else:
        return _open_capture_windows(cam_index, fmt, width, height, fps, multicam_file)


# ---------------------------------------------------------------------------
# Frame conversion
# ---------------------------------------------------------------------------

def to_luma(frame, fmt):
    """Extract float32 luma from a GStreamer frame (Linux)."""
    if fmt in Y16_LIKE_FMTS:
        if frame.ndim == 3 and frame.shape[2] == 2:
            # UVC Y16 workaround: OpenCV yields (H, W, 2) uint8 raw bytes — reinterpret as uint16 LE
            return frame.view(np.uint16).reshape(frame.shape[0], frame.shape[1]).astype(np.float32)
        return frame.astype(np.float32)
    elif fmt in ("AR24", "AB24"):
        # AR24 (BGRA) and AB24 (RGBA) differ only in channel order — an equal-
        # weight average of the 3 color channels is order-independent.
        c0 = frame[:, :, 0].astype(np.float32)
        c1 = frame[:, :, 1].astype(np.float32)
        c2 = frame[:, :, 2].astype(np.float32)
        return 0.333 * c0 + 0.333 * c1 + 0.333 * c2
    elif fmt == "YUYV":
        if frame.ndim == 3:
            return frame[:, :, 0].astype(np.float32)
        else:
            return frame[:, ::2].astype(np.float32)
    raise ValueError(f"Unknown format: {fmt}")


def frame_to_gray(frame, fmt, width, height):
    """Return a float32 2D grayscale array for metric computation."""
    if platform.system() == "Linux":
        return to_luma(frame, fmt)

    if fmt == "Y16":
        if frame.ndim == 2 and frame.shape[0] == 1:
            # Flat buffer from MSMF: (1, H*W*2) uint8 → uint16 → (H, W)
            return frame.reshape(height * width * 2).view('<u2').reshape(height, width).astype(np.float32)
        elif frame.ndim == 2:
            return frame.astype(np.float32)
        elif frame.ndim == 3 and frame.shape[2] == 2:
            # Y16 as (H, W, 2) uint8 little-endian bytes
            return (frame[:, :, 0].astype(np.uint16) +
                    frame[:, :, 1].astype(np.uint16) * 256).astype(np.float32)
        else:
            log.warning("Y16 frame received as BGR, depth information lost")
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    elif fmt == "Y10":
        # Euresys buffer: (H, W) uint16, values 0-1023
        return frame.astype(np.float32)
    elif fmt == "YUYV":
        if frame.ndim == 2 and frame.shape[0] == 1:
            # Flat buffer from MSMF: (1, H*W*2) uint8 → extract Y channel
            return frame.reshape(height, width, 2)[:, :, 0].astype(np.float32)
        elif frame.ndim == 3 and frame.shape[2] == 2:
            return frame[:, :, 0].astype(np.float32)
        elif frame.ndim == 3 and frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            return frame.astype(np.float32)
    elif len(frame.shape) == 3 and frame.shape[2] == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    else:
        return frame.astype(np.float32)


# ---------------------------------------------------------------------------
# Background event frame saver
# ---------------------------------------------------------------------------

def _save_worker(save_queue):
    """Saves event frame batches to disk in a background thread."""
    while True:
        task = save_queue.get()
        if task is None:
            break
        event_dir = task['event_dir']
        frames    = task['frames']
        fmt       = task['image_fmt']
        pixel_fmt = task['pixel_fmt']
        os.makedirs(event_dir, exist_ok=True)
        for i, (fts, gray) in enumerate(frames):
            fname = f"frame_{i:02d}_{fts:.3f}s.{fmt}"
            fpath = os.path.join(event_dir, fname)
            if fmt == 'tif':
                arr = gray.astype(np.uint16) if pixel_fmt in Y16_LIKE_FMTS else gray.astype(np.uint8)
                cv2.imwrite(fpath, arr)
            else:
                gray.astype(np.float32).tofile(fpath)
        save_queue.task_done()


def _dispatch_event_frames(save_queue, committed_bytes, committed_lock, max_bytes,
                           run_dir, event_type, event_ts, frames, image_format, pixel_fmt,
                           height, width, events_writer, fevents, extra_details="",
                           frames_full_flag=None, rt_log=""):
    """
    Try to dispatch a set of event frames to the background save queue.
    Writes exactly one row to events_log: with dir name on success, or failure reason.
    frames_full_flag: mutable [bool] set to True on the first frames-quota overflow.
    rt_log: filename of the active rt_log_*.csv segment at the time of the event.
    """
    if not frames:
        return

    bpp = 4 if image_format == 'raw' else (2 if pixel_fmt in Y16_LIKE_FMTS else 1)
    estimated = len(frames) * height * width * bpp
    event_dir_name = f"{event_type}_{event_ts:09.3f}s"
    event_dir = os.path.join(run_dir, event_dir_name)

    with committed_lock:
        if max_bytes > 0 and committed_bytes[0] + estimated > max_bytes:
            if frames_full_flag is not None and not frames_full_flag[0]:
                frames_full_flag[0] = True   # signal first hit to the caller
            events_writer.writerow([f"{event_ts:.6f}", event_type,
                                    f"{extra_details} save_skipped=disk_full", rt_log])
            fevents.flush()
            return
        committed_bytes[0] += estimated

    try:
        save_queue.put_nowait({
            'event_dir': event_dir,
            'frames': frames,
            'image_fmt': image_format,
            'pixel_fmt': pixel_fmt,
        })
    except queue.Full:
        with committed_lock:
            committed_bytes[0] -= estimated
        events_writer.writerow([f"{event_ts:.6f}", event_type,
                                f"{extra_details} save_skipped=queue_full", rt_log])
        fevents.flush()
        return

    details = f"{extra_details} dir={event_dir_name}" if extra_details else f"dir={event_dir_name}"
    events_writer.writerow([f"{event_ts:.6f}", event_type, details, rt_log])
    fevents.flush()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def camera_main_loop(cfg=default_cfg, _frame_iter=None):
    """
    cfg        : Config instance — all tunable parameters.
                 FPN detection is controlled by cfg.fpn (ConfigFPN).
                 Set cfg.fpn.enabled = True to activate FPN spike detection.
    _frame_iter: optional iterator yielding (gray_float32_2d, dt_ms) tuples.
                 When provided, the camera is not opened and timing is driven
                 by dt_ms values.  Used exclusively for testing.
    """
    # Unpack top-level config fields
    cam_index             = cfg.cam_index
    device                = cfg.device
    target_fps            = cfg.target_fps
    width                 = cfg.width
    height                = cfg.height
    num_frames            = cfg.num_frames
    save_images           = cfg.save_images
    image_format          = cfg.image_format
    event_half            = cfg.event_half
    max_save_mb           = cfg.max_save_mb
    max_frames_mb         = cfg.max_frames_mb
    max_log_lines         = cfg.max_log_lines
    freeze_threshold_s    = cfg.freeze_threshold_s
    freeze_recovery_frames= cfg.freeze_recovery_frames
    base_dir              = cfg.base_dir
    fmt                   = cfg.fmt
    multicam_file         = cfg.multicam_file
    drop_detect           = cfg.drop_detect
    log_enabled           = cfg.log_enabled
    show_video            = cfg.show_video and (_frame_iter is None)
    stats_enabled         = cfg.stats

    if max_frames_mb is not None and max_save_mb > 0 and max_save_mb < max_frames_mb:
        raise ValueError(
            f"max_save_mb ({max_save_mb}) must be >= max_frames_mb ({max_frames_mb})"
        )

    # FPN detector (instantiated once; inactive when cfg.fpn.enabled is False)
    fpn_detect = cfg.fpn.enabled
    detector   = FpnDetector(cfg.fpn) if fpn_detect else None

    # Stats (mean/std/row_noise/col_noise) cost a full pass over the frame —
    # off by default (see compte-rendu §12), and only computed when something
    # actually consumes them: CSV logging, FPN detection, or an explicit
    # --stats (to print them on the status line with no other flag).
    need_stats     = stats_enabled or log_enabled or fpn_detect
    need_frame_buf = drop_detect or fpn_detect
    # frame_to_gray()/to_luma() casts to float32 (a full-frame copy) — needed
    # for stats/frame_buf/save_images, but the live preview alone can work
    # straight off the raw uint16 capture (see the show_video fast path
    # below), so skip the cast entirely when nothing else needs it.
    need_gray      = need_stats or need_frame_buf or save_images or fmt not in Y16_LIKE_FMTS

    cap = None if _frame_iter is not None else open_capture(cam_index, device, fmt, width, height, target_fps, multicam_file)
    if cap is not None and hasattr(cap, 'pixel_fmt'):
        fmt = cap.pixel_fmt
    if cap is not None and hasattr(cap, 'width'):
        width, height = cap.width, cap.height

    if _frame_iter is not None:
        device_tag = ""
    elif platform.system() == "Linux":
        device_tag = "_" + os.path.basename(device)   # e.g. "video0"
    else:
        device_tag = f"_cam{cam_index}"

    if show_video:
        _win_title = f"rt_frame_monitor — {device_tag.lstrip('_') or f'cam{cam_index}'}"
        if cfg.window_autosize:
            # WINDOW_AUTOSIZE sizes the window to match the image on every
            # imshow() natively, with no separate resizeWindow call — avoids
            # the slow redraw path below entirely, at the cost of a
            # non-resizable window (see compte-rendu §12.7).
            cv2.namedWindow(_win_title, cv2.WINDOW_AUTOSIZE)
        else:
            # Resizable window (default). On this platform's GTK/X11 backend,
            # WINDOW_NORMAL alone defaults to a fixed 320x240 window (no
            # auto-fit to the image), so resizeWindow is needed to get the
            # right initial size — but that combination makes every
            # subsequent cv2.imshow() go through a much slower resize/redraw
            # path (~26 fps instead of 60 at 1280x1024). Pass --no-resize if
            # you want the full framerate instead of mouse-resizing.
            cv2.namedWindow(_win_title, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(_win_title, width, height)

    start_ts     = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    run_dir_name = start_ts + device_tag
    run_dir = os.path.join(base_dir, run_dir_name) if base_dir else run_dir_name
    if log_enabled or save_images:
        os.makedirs(run_dir, exist_ok=True)
    if log_enabled:
        log.info("Log directory: %s", run_dir)

    image_folder = None
    if save_images:
        image_folder = os.path.join(run_dir, start_ts)
        os.makedirs(image_folder, exist_ok=True)

    def _open_log_file(ts=None):
        if ts is None:
            ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S.%f')
        fname = f"rt_log_{ts}.csv"
        f = open(os.path.join(run_dir, fname), "w", newline="")
        w = csv.writer(f)
        w.writerow(["timestamp_s", "dt_ms", *_STATS])
        return f, w, fname

    if log_enabled:
        flog, writer, current_log_name = _open_log_file(start_ts)
    else:
        flog, writer, current_log_name = _NullFile(), _NullWriter(), ""
    log_line_count = 0

    def _total_bytes():
        current_csv = flog.tell() if not flog.closed else 0
        return closed_csv_bytes[0] + current_csv + committed_bytes[0]

    def _trigger_storage_full(ts_val):
        if storage_full[0]:
            return
        storage_full[0] = True
        total_mb = _total_bytes() / 1024 ** 2
        limit_mb = max_global_bytes / 1024 ** 2
        msg = f"total_mb={total_mb:.2f} limit_mb={limit_mb:.2f}"
        events_writer.writerow([f"{ts_val:.6f}", "storage_full", msg, current_log_name])
        fevents.flush()
        writer.writerow([f"{ts_val:.6f}", "STORAGE FULL", *("" for _ in _STATS)])
        flog.flush()
        sys.stdout.write(
            f"\n  [STORAGE FULL] Recording stopped"
            f" ({total_mb:.2f}/{limit_mb:.2f} MiB) — live monitoring continues\n"
        )
        sys.stdout.flush()

    def _trigger_frames_full(ts_val):
        """Called once when the event-frames quota is first exceeded.
        Logs a 'frames_full' event and prints a persistent display line.
        CSV logging is unaffected."""
        # frames_full[0] was already set by _dispatch_event_frames; this adds notifications.
        limit_mb = max_frames_bytes / 1024 ** 2
        events_writer.writerow([f"{ts_val:.6f}", "frames_full",
                                 f"limit_mb={limit_mb:.2f}", current_log_name])
        fevents.flush()
        writer.writerow([f"{ts_val:.6f}", "FRAMES FULL", *("" for _ in _STATS)])
        flog.flush()
        sys.stdout.write(
            f"\n  [FRAMES FULL] Event frame recording stopped"
            f" (limit: {limit_mb:.2f} MiB) — CSV logging continues\n"
        )
        sys.stdout.flush()

    if log_enabled:
        fevents = open(os.path.join(run_dir, "events_log.csv"), "w", newline="")
        events_writer = csv.writer(fevents)
        events_writer.writerow(["timestamp_s", "event", "details", "rt_log"])
    else:
        fevents, events_writer = _NullFile(), _NullWriter()
    # Resolve the two disk limits.
    # max_save_mb  : global (CSV logs + event frames); 0 = unlimited
    # max_frames_mb: event frame images only; None = same as global
    if max_frames_mb is None:
        # frames limit mirrors the global limit
        max_global_bytes = int(max_save_mb * 1024 ** 2)
        max_frames_bytes = max_global_bytes
    elif max_save_mb == 0:
        # only frames limit specified → global adopts the same value
        max_global_bytes = int(max_frames_mb * 1024 ** 2)
        max_frames_bytes = max_global_bytes
    else:
        # both specified, already validated above
        max_global_bytes = int(max_save_mb * 1024 ** 2)
        max_frames_bytes = int(max_frames_mb * 1024 ** 2)

    # Background saver
    committed_bytes  = [0]   # event frame bytes committed to the save queue
    committed_lock   = threading.Lock()
    storage_full     = [False]
    frames_full      = [False]
    closed_csv_bytes = [0]
    save_queue  = queue.Queue(maxsize=cfg.save_queue_maxsize)
    save_thread = threading.Thread(target=_save_worker, args=(save_queue,), daemon=True)
    save_thread.start()

    # Rolling image buffer — sized so the spike frame is always retrievable.
    # FPN mode : fpn_half + event_half + 1  (spike is fpn_half frames in the past)
    # Drop mode: event_half + 1             (pending collects the future frames)
    fpn_half         = detector.half if fpn_detect else 0
    frame_buf_maxlen = (fpn_half + event_half + 1) if fpn_detect else (event_half + 1)
    frame_buf        = deque(maxlen=frame_buf_maxlen)

    expected_period_ms  = 1000.0 / target_fps
    drop_threshold_ms   = 1.5 * expected_period_ms
    lower_normal_ms     = 0.5 * expected_period_ms
    freeze_threshold_ms = freeze_threshold_s * 1000.0
    t0 = None
    prev_time = None
    frame_count = 0
    dropped_total = 0
    in_freeze          = False
    consecutive_normal = 0
    freeze_start_ts    = None
    grab_fail_since    = None
    freeze_count       = 0
    spike_count        = 0   # local mirror of detector.spike_count for the display line
    fps_smooth         = float(target_fps)

    pending_event = None

    def dispatch_pending():
        nonlocal pending_event
        if pending_event is None or storage_full[0]:
            return
        was_frames_full = frames_full[0]
        ev_ts = pending_event['event_ts']
        _dispatch_event_frames(
            save_queue, committed_bytes, committed_lock, max_frames_bytes,
            run_dir, pending_event['event_type'], ev_ts,
            pending_event['frames'], image_format, fmt, height, width,
            events_writer, fevents, pending_event['extra_details'],
            frames_full_flag=frames_full,
            rt_log=current_log_name,
        )
        if not was_frames_full and frames_full[0]:
            _trigger_frames_full(ev_ts)
        pending_event = None

    try:
        if log_enabled:
            applied_config = {**cfg.__dict__, "fpn": cfg.fpn.__dict__}
            with open(os.path.join(run_dir, "applied_config.json"), "w") as fcfg:
                json.dump(applied_config, fcfg, indent=2)

        while True:
            if isinstance(num_frames, int) and num_frames > 0 and frame_count >= num_frames:
                break

            if _frame_iter is not None:
                try:
                    gray, dt_override = next(_frame_iter)
                except StopIteration:
                    break
                if t0 is None:
                    t0 = 0.0
                    ts = 0.0
                    dt = 0.0
                else:
                    dt = float(dt_override)
                    ts += dt / 1000.0
            else:
                ret, frame = cap.read()
                now = time.perf_counter()

                if not ret:
                    if grab_fail_since is None:
                        # First failure: log camera_freeze immediately (pipeline is broken)
                        grab_fail_since = now
                        if frame_count > 0 and not in_freeze:
                            dispatch_pending()
                            freeze_start_ts = ts
                            if not storage_full[0]:
                                events_writer.writerow([f"{freeze_start_ts:.6f}", "camera_freeze", "", current_log_name])
                                fevents.flush()
                            in_freeze = True
                            consecutive_normal = 0
                            freeze_count += 1
                            if fpn_detect:
                                detector.reset()
                    elif now - grab_fail_since >= cfg.reopen_interval_s:
                        grab_fail_since = now
                        try:
                            cap.release()
                            cap = open_capture(cam_index, device, fmt, width, height, target_fps, multicam_file)
                            if hasattr(cap, 'pixel_fmt'):
                                fmt = cap.pixel_fmt
                        except Exception as exc:
                            log.warning("Reopen failed: %s", exc)
                    continue

                # Successful grab: clear failure state (in_freeze cleared by normal dt logic)
                if grab_fail_since is not None:
                    grab_fail_since = None

                gray = frame_to_gray(frame, fmt, width, height) if need_gray else None
                if t0 is None:
                    t0 = now
                    prev_time = now
                ts = now - t0
                dt = (now - prev_time) * 1000  # ms
                prev_time = now
                if dt > 0:
                    fps_smooth = 0.9 * fps_smooth + 0.1 * (1000.0 / dt)

            if need_stats:
                row_means = gray.mean(axis=1)
                col_means = gray.mean(axis=0)
                results = {
                    'mean':      float(row_means.mean()),
                    'std':       float(gray.std()),
                    'row_noise': float(row_means.std()),
                    'col_noise': float(col_means.std()),
                }
            else:
                results = None

            if need_frame_buf:
                frame_buf.append((ts, gray))

            # Collect future frames for an in-progress drop event
            if pending_event is not None:
                pending_event['frames'].append((ts, gray))
                pending_event['remaining'] -= 1
                if pending_event['remaining'] == 0:
                    dispatch_pending()

            # ── Freeze detection ──────────────────────────────────────────
            if frame_count > 0 and freeze_threshold_ms > 0 and dt > freeze_threshold_ms:
                consecutive_normal = 0
                if not in_freeze:
                    dispatch_pending()
                    freeze_start_ts = ts - dt / 1000.0   # timestamp of last good frame
                    if not storage_full[0]:
                        events_writer.writerow([f"{freeze_start_ts:.6f}", "camera_freeze", "", current_log_name])
                        fevents.flush()
                    in_freeze = True
                    freeze_count += 1
                    if fpn_detect:
                        detector.reset()

            elif in_freeze:
                # Inside a freeze: check for return to normal cadence
                if lower_normal_ms <= dt <= drop_threshold_ms:
                    consecutive_normal += 1
                    if consecutive_normal >= freeze_recovery_frames:
                        in_freeze = False
                        consecutive_normal = 0
                        duration_s = ts - freeze_start_ts
                        if not storage_full[0]:
                            events_writer.writerow([f"{ts:.6f}", "camera_resume",
                                                    f"freeze_started={freeze_start_ts:.3f}s"
                                                    f" duration_s={duration_s:.1f}",
                                                    current_log_name])
                            fevents.flush()
                else:
                    consecutive_normal = 0

            # ── Drop detection ────────────────────────────────────────────
            elif drop_detect and frame_count > 0 and dt > drop_threshold_ms:
                n_dropped = round(dt / expected_period_ms) - 1
                if n_dropped > 0:
                    dropped_total += n_dropped
                    # Flush any in-progress pending before starting a new one
                    dispatch_pending()
                    # Snapshot past frames from rolling buffer (includes current frame)
                    buf_snap = list(frame_buf)
                    pending_event = {
                        'frames':       buf_snap[-(event_half + 1):],
                        'remaining':    event_half,
                        'event_type':   'dropped_frames',
                        'event_ts':     ts,
                        'extra_details': f"count={n_dropped} dt_ms={dt:.1f}",
                    }

            # ── CSV logging ───────────────────────────────────────────────
            if log_enabled and not storage_full[0]:
                writer.writerow([f"{ts:.6f}", f"{dt:.3f}", *(results[s] for s in _STATS)])
                log_line_count += 1
                if max_global_bytes > 0 and _total_bytes() >= max_global_bytes:
                    _trigger_storage_full(ts)
                elif max_log_lines > 0 and log_line_count >= max_log_lines:
                    # Emit close event for the outgoing segment, then rotate.
                    # Open the new segment BEFORE closing the old one to minimise
                    # the window where no writer is active.
                    old_log_name = current_log_name
                    closed_csv_bytes[0] += flog.tell()
                    new_flog, new_writer, new_log_name = _open_log_file()
                    flog.close()
                    flog, writer = new_flog, new_writer
                    current_log_name = new_log_name
                    log_line_count = 0
                    # Announce the transition in events_log
                    events_writer.writerow([f"{ts:.6f}", "log_segment_close",
                                            old_log_name, old_log_name])
                    events_writer.writerow([f"{ts:.6f}", "log_segment_open",
                                            current_log_name, current_log_name])
                    fevents.flush()

            # ── FPN spike detection ───────────────────────────────────────
            if fpn_detect:
                triggers = detector.update(results, ts)
                spike_count = detector.spike_count

                if triggers and not storage_full[0]:
                    center_ts   = triggers[0].center_ts
                    tag         = '_'.join(_FPN_SHORT[t.key] for t in triggers)
                    event_type  = f"fpn_spike_{tag}"

                    parts = [f"spike={spike_count}"]
                    for t in triggers:
                        s = _FPN_SHORT[t.key]
                        parts.append(
                            f"{s}_val={t.center_val:.2f} {s}_wstd={t.wstd:.2f}"
                            f" {s}_thresh={t.eff_thresh:.2f}({t.thresh_tag})"
                        )

                    buf_list     = list(frame_buf)
                    peak_buf_idx = len(buf_list) - fpn_half - 1
                    start = max(0, peak_buf_idx - event_half)
                    end   = min(len(buf_list), peak_buf_idx + event_half + 1)
                    was_frames_full = frames_full[0]
                    _dispatch_event_frames(
                        save_queue, committed_bytes, committed_lock, max_frames_bytes,
                        run_dir, event_type, center_ts,
                        buf_list[start:end], image_format, fmt,
                        height, width, events_writer, fevents,
                        ' '.join(parts),
                        frames_full_flag=frames_full,
                        rt_log=current_log_name,
                    )
                    if not was_frames_full and frames_full[0]:
                        _trigger_frames_full(center_ts)

            # ── Per-frame image save (optional) ───────────────────────────
            if save_images:
                fname = f"frame_{frame_count + 1:04d}.{image_format}"
                fpath = os.path.join(image_folder, fname)
                if image_format == "tif":
                    save_arr = gray.astype(np.uint16) if fmt in Y16_LIKE_FMTS else gray.astype(np.uint8)
                    cv2.imwrite(fpath, save_arr)
                elif image_format == "raw":
                    gray.astype(np.float32).tofile(fpath)

            # ── Live display (optional) ───────────────────────────────────
            if show_video:
                if gray is not None:
                    if fmt in Y16_LIKE_FMTS or gray.dtype == np.uint16:
                        _disp = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                    else:
                        _disp = gray.clip(0, 255).astype(np.uint8)
                else:
                    # Fast path: gray was skipped (need_gray False — Y16/Y10,
                    # nothing else needs the float32 cast). Feed cv2.normalize
                    # the raw capture directly, same reinterpretation as
                    # to_luma() but without the astype(float32) copy.
                    if frame.ndim == 3 and frame.shape[2] == 2:
                        _raw = frame.view(np.uint16).reshape(height, width)
                    else:
                        _raw = frame
                    _disp = cv2.normalize(_raw, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                cv2.imshow(_win_title, _disp)
                if cv2.waitKey(1) == 27:   # ESC → stop
                    break

            # cam_fps = true camera/hardware capture rate (from GStreamer, upstream
            # of appsink drop=true); gst_drop = frames the camera delivered but this
            # loop never got to (dropped because it wasn't calling read() fast enough).
            cam_part = ""
            if cap is not None and hasattr(cap, "capture_fps"):
                gst_dropped = cap.capture_total - (frame_count + 1)
                cam_part = f"  cam_fps={cap.capture_fps:5.1f}"
                if gst_dropped > 0:
                    cam_part += f"  gst_drop={gst_dropped:4d}"

            dropped_part = f"  dropped={dropped_total:4d}" if drop_detect and dropped_total else ""
            fpn_part     = f"  spikes={spike_count:3d}" if fpn_detect and spike_count else ""
            freeze_part  = f"  freeze={freeze_count:3d}" if freeze_count or in_freeze else ""
            frames_part  = "  [FRAMES FULL]" if frames_full[0] and not storage_full[0] else ""
            storage_part = "  [STORAGE FULL]" if storage_full[0] else ""
            stats_part   = ("  " + "  ".join(f"{s}={results[s]:8.2f}" for s in _STATS)) if (stats_enabled and results is not None) else ""
            sys.stdout.write(
                f"\r  frame={frame_count:6d}  ts={ts:8.3f}s  dt={dt:6.1f}ms  fps={fps_smooth:5.1f}"
                f"{cam_part}{dropped_part}{fpn_part}{freeze_part}{frames_part}{storage_part}{stats_part}"
            )
            sys.stdout.flush()
            frame_count += 1

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        dispatch_pending()      # flush any in-progress drop event collection
        save_queue.put(None)    # signal save thread to stop
        save_thread.join()      # wait for all frames to be written to disk
        if cap is not None:
            cap.release()
        if show_video:
            cv2.destroyAllWindows()
        flog.close()
        fevents.close()

    return run_dir


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    # ── Step 1: pre-parse only --config so we can load the right JSON first ──
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None,
                     help="Path to a JSON config file (overrides the built-in default)")
    pre_args, _ = pre.parse_known_args()

    # ── Step 2: load config — from JSON if --config given, else pure defaults ──
    run_cfg = Config.from_json(pre_args.config) if pre_args.config else Config()

    # ── Step 3: full argument parser — defaults come from the loaded config ──
    parser = argparse.ArgumentParser(
        description="Real-time camera frame monitor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Config file
    parser.add_argument("--config", default=None, metavar="PATH",
                        help="Path to a JSON config file; if omitted, uses the built-in default")

    # Camera / capture  — likely to override per run
    parser.add_argument("--fmt", "-f", default=run_cfg.fmt, choices=["Y16", "Y16_BE", "Y14", "AR24", "AB24", "YUYV"],
                        help="Pixel format for MSMF/V4L2 capture (ignored when --multicam-file is used). "
                             "Y16_BE is Linux/MIPI-only (e.g. iLumos, which only offers GRAY16_BE to V4L2). "
                             "Omit (Linux only) to not force a format at all and use whatever the device "
                             "is currently set to.")
    parser.add_argument("--device", "-d", default=run_cfg.device,
                        help="V4L2 device path (Linux)")
    parser.add_argument("--cam-index", "-c", type=int, default=run_cfg.cam_index,
                        help="Camera index for MSMF (Windows)")
    parser.add_argument("--width",  "-W", type=int, default=run_cfg.width,
                        help="Frame width in pixels")
    parser.add_argument("--height", "-H", type=int, default=run_cfg.height,
                        help="Frame height in pixels")
    parser.add_argument("--fps", type=int, default=run_cfg.target_fps,
                        help="Target capture frame rate")
    parser.add_argument("--num-frames", type=int, default=0,
                        help="Frames to capture; 0 = infinite")

    # Display
    parser.add_argument("--display", action="store_true", default=run_cfg.show_video,
                        help="Show live video window (ESC to quit); Y16/Y10 auto-normalized to 8-bit")
    parser.add_argument("--no-resize", action="store_true", default=run_cfg.window_autosize,
                        help="Fixed-size, non-resizable display window (WINDOW_AUTOSIZE) instead of "
                             "the default resizable one — restores the full capture framerate on "
                             "platforms where a resizable window halves the display fps (see README/"
                             "compte-rendu). No effect without --display.")

    # CameraLink
    parser.add_argument("--multicam-file", default=run_cfg.multicam_file, metavar="PATH",
                        help="Path to the Euresys .cam file; activates CameraLink capture mode (Windows only)")

    # Output
    parser.add_argument("--base-dir",      default=run_cfg.base_dir, metavar="DIR")
    parser.add_argument("--save-images",   action="store_true", default=run_cfg.save_images)
    parser.add_argument("--image-format",  default=run_cfg.image_format, choices=["tif", "raw"])
    parser.add_argument("--max-log-lines", type=int,   default=run_cfg.max_log_lines)
    parser.add_argument("--max-save-mb",   type=float, default=run_cfg.max_save_mb)
    parser.add_argument("--max-frames-mb", type=float, default=run_cfg.max_frames_mb)
    parser.add_argument("--event-half",    type=int,   default=run_cfg.event_half,
                        help="Frames each side of event centre to save")

    # FPN detection (maps to ConfigFPN fields)
    parser.add_argument("--fpn-detect", action="store_true", default=run_cfg.fpn.enabled,
                        help="Enable FPN spike detection")
    parser.add_argument("--fpn-window",          type=int,   default=run_cfg.fpn.window)
    parser.add_argument("--fpn-threshold-std",   type=float, default=run_cfg.fpn.threshold_std)
    parser.add_argument("--fpn-threshold-row",   type=float, default=run_cfg.fpn.threshold_row)
    parser.add_argument("--fpn-threshold-col",   type=float, default=run_cfg.fpn.threshold_col)
    parser.add_argument("--fpn-adaptive",        action="store_true", default=run_cfg.fpn.adaptive)
    parser.add_argument("--fpn-adaptive-k",      type=float, default=run_cfg.fpn.adaptive_k)
    parser.add_argument("--fpn-baseline-window", type=int,   default=run_cfg.fpn.baseline_window)
    parser.add_argument("--fpn-baseline-min-frames", type=int,
                        default=run_cfg.fpn.baseline_min_frames)

    # Freeze detection
    parser.add_argument("--freeze-threshold", type=float, default=run_cfg.freeze_threshold_s,
                        help="Gap in seconds that triggers a camera_freeze event; 0 = disabled")
    parser.add_argument("--freeze-recovery", type=int, default=run_cfg.freeze_recovery_frames,
                        help="Consecutive normal frames required to exit freeze state")

    # Drop detection
    parser.add_argument("--drop-detect", action="store_true", default=run_cfg.drop_detect,
                        help="Count and log dropped frames (compares dt against 1.5× expected period)")

    # Logging
    parser.add_argument("--log", action="store_true", default=run_cfg.log_enabled,
                        help="Write rt_log CSV and events_log to disk (creates a dated run directory)")

    # Stats
    parser.add_argument("--stats", action="store_true", default=run_cfg.stats,
                        help="Compute mean/std/row_noise/col_noise and print them on the status "
                             "line. Off by default (this is the main cost of the display loop — "
                             "see compte-rendu §12); automatically enabled by --log or "
                             "--fpn-detect regardless of this flag, though only --stats prints "
                             "them on the status line.")

    args = parser.parse_args()

    # ── Step 4: validate cross-parameter constraints ──
    if (args.max_frames_mb is not None and args.max_save_mb > 0
            and args.max_save_mb < args.max_frames_mb):
        parser.error(
            f"--max-save-mb ({args.max_save_mb}) must be >= --max-frames-mb ({args.max_frames_mb})"
        )

    # ── Step 5: Apply CLI overrides onto run_cfg
    run_cfg.fmt                    = args.fmt
    run_cfg.cam_index              = args.cam_index
    run_cfg.device                 = args.device
    run_cfg.target_fps             = args.fps
    run_cfg.width                  = args.width
    run_cfg.height                 = args.height
    run_cfg.num_frames             = args.num_frames if args.num_frames > 0 else None
    run_cfg.base_dir               = args.base_dir
    run_cfg.save_images            = args.save_images
    run_cfg.image_format           = args.image_format
    run_cfg.max_log_lines          = args.max_log_lines
    run_cfg.max_save_mb            = args.max_save_mb
    run_cfg.max_frames_mb          = args.max_frames_mb
    run_cfg.event_half             = args.event_half
    run_cfg.freeze_threshold_s     = args.freeze_threshold
    run_cfg.freeze_recovery_frames = args.freeze_recovery
    run_cfg.drop_detect            = args.drop_detect
    run_cfg.log_enabled            = args.log
    run_cfg.show_video             = args.display
    run_cfg.window_autosize        = args.no_resize
    run_cfg.multicam_file          = args.multicam_file
    run_cfg.stats                   = args.stats

    # Apply CLI overrides onto the nested ConfigFPN
    run_cfg.fpn.enabled              = args.fpn_detect
    run_cfg.fpn.window               = args.fpn_window
    run_cfg.fpn.threshold_std        = args.fpn_threshold_std
    run_cfg.fpn.threshold_row        = args.fpn_threshold_row
    run_cfg.fpn.threshold_col        = args.fpn_threshold_col
    run_cfg.fpn.adaptive             = args.fpn_adaptive
    run_cfg.fpn.adaptive_k           = args.fpn_adaptive_k
    run_cfg.fpn.baseline_window      = args.fpn_baseline_window
    run_cfg.fpn.baseline_min_frames  = args.fpn_baseline_min_frames

    camera_main_loop(cfg=run_cfg)
