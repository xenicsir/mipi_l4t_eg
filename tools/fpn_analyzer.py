#!/usr/bin/env python3
"""
fpn_analyzer.py — Real-time FPN spike detector for MIPI camera streams.

Per-frame FPN = global std of the luma channel (float32).
A sliding window of W frames is maintained; the window std of FPN values is
computed continuously.  When it exceeds THRESHOLD and the center frame of the
window is the local maximum (argmax == W//2), the window is saved to disk and
the event is logged.  This ensures the spike is always centered in the saved
frames.  A cooldown of W//2 frames prevents re-triggering on the same spike.

Usage:
    python3 fpn_analyzer.py [options]

Options:
    --format    Pixel format: Y16 (default), AR24, YUYV
    --device    V4L2 device (default: /dev/video0)
    --width     Frame width  (default: 640)
    --height    Frame height (default: 480)
    --fps       Target FPS   (default: 60)
    --window    Sliding window size in frames (default: 60, i.e. 1 s at 60 fps)
    --threshold Window-std threshold for spike detection (default: 5.0)
    --out-dir   Directory for spike frame dumps (default: /tmp/fpn_spikes)
    --log       CSV log path (default: /tmp/fpn_log.csv)
    --duration  Run duration in seconds; 0 = until Ctrl-C (default: 0)
"""

import argparse
import csv
import queue
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

DEFAULT_DEVICE    = "/dev/video0"
DEFAULT_WIDTH     = 640
DEFAULT_HEIGHT    = 480
DEFAULT_FPS       = 60
DEFAULT_WINDOW    = 60
DEFAULT_THRESHOLD = 5.0
DEFAULT_OUT_DIR   = "/tmp/fpn_spikes"
DEFAULT_LOG       = "/tmp/fpn_log.csv"
QUEUE_MAXSIZE     = 8

# GStreamer format string and output file extension per format
FORMAT_GST = {"Y16": "GRAY16_LE", "AR24": "BGRA",  "YUYV": "YUY2"}
FORMAT_EXT = {"Y16": "y16",       "AR24": "ar24",   "YUYV": "yuyv"}


def to_luma(frame: np.ndarray, fmt: str) -> np.ndarray:
    """Return a float32 (H, W) luma array for FPN computation."""
    if fmt == "Y16":
        # (H, W) uint16
        return frame.astype(np.float32)
    elif fmt == "AR24":
        # GStreamer BGRA → (H, W, 4) uint8
        b = frame[:, :, 0].astype(np.float32)
        g = frame[:, :, 1].astype(np.float32)
        r = frame[:, :, 2].astype(np.float32)
        #        return 0.114 * b + 0.587 * g + 0.299 * r
        return 0.333 * b + 0.333 * g + 0.333 * r
    elif fmt == "YUYV":
        # GStreamer YUY2 → (H, W, 2) uint8; channel 0 = Y
        if frame.ndim == 3:
            return frame[:, :, 0].astype(np.float32)
        else:
            # packed as (H, W*2) uint8; Y at even columns
            return frame[:, ::2].astype(np.float32)
    raise ValueError(f"Unknown format: {fmt}")


def compute_fpn(frame: np.ndarray, fmt: str) -> float:
    """Global std of luma — single scalar FPN metric."""
    return float(np.std(to_luma(frame, fmt)))


def capture_thread(cap: cv2.VideoCapture, q: queue.Queue,
                   stop_event: threading.Event, stats: dict, lock: threading.Lock):
    t0 = None
    frame_idx = 0

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            continue

        ts = time.monotonic()
        if t0 is None:
            t0 = ts
            print(f"[capture] shape={frame.shape} dtype={frame.dtype}  "
                  f"min={frame.min()} max={frame.max()} std={frame.std():.1f}")
        ts -= t0

        with lock:
            stats["captured"] += 1

        try:
            q.put_nowait((frame_idx, ts, frame.copy()))
        except queue.Full:
            with lock:
                stats["dropped"] += 1

        frame_idx += 1


def processing_thread(q: queue.Queue, stop_event: threading.Event,
                      stats: dict, lock: threading.Lock, args: argparse.Namespace):

    half = args.window // 2
    window: deque = deque(maxlen=args.window)
    cooldown = 0
    spike_count = 0
    ext = FORMAT_EXT[args.format]

    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["timestamp_s", "frame_index", "fpn_std"])
        csvfile.flush()

        while not stop_event.is_set() or not q.empty():
            try:
                frame_idx, ts, frame = q.get(timeout=0.1)
            except queue.Empty:
                continue

            fpn = compute_fpn(frame, args.format)
            window.append((frame_idx, ts, frame, fpn))

            writer.writerow([f"{ts:.6f}", frame_idx, f"{fpn:.4f}"])
            csvfile.flush()

            sys.stdout.write(
                f"\r  frame={frame_idx:6d}  ts={ts:8.3f}s  "
                f"fpn={fpn:8.2f}  spikes={spike_count}"
            )
            sys.stdout.flush()

            with lock:
                stats["processed"] += 1

            if len(window) < args.window:
                continue

            if cooldown > 0:
                cooldown -= 1
                continue

            fpn_values = np.array([item[3] for item in window])
            window_std = float(fpn_values.std())
            peak_pos   = int(fpn_values.argmax())

            if window_std > args.threshold and peak_pos == half:
                spike_count += 1
                _, center_ts, _, center_fpn = window[half]

                spike_dir = Path(args.out_dir) / f"spike_{spike_count:04d}_{center_ts:.3f}s"
                spike_dir.mkdir(parents=True, exist_ok=True)

                print(f"\n  [SPIKE #{spike_count}]  ts={center_ts:.3f}s  "
                      f"center_fpn={center_fpn:.2f}  window_std={window_std:.2f}")

                for i, (fidx, fts, frm, ffpn) in enumerate(window):
                    offset = i - half
                    fname  = (spike_dir /
                              f"frame_{i:02d}_{offset:+03d}_{fidx:06d}_{fts:.3f}s_fpn{ffpn:.1f}.{ext}")
                    frm.tofile(str(fname))

                cooldown = half

    print(f"\n[done] {spike_count} spike(s) saved to {args.out_dir}")


def main():
    ap = argparse.ArgumentParser(
        description="Real-time FPN spike detector for MIPI camera streams"
    )
    ap.add_argument("--format",    default="Y16", choices=["Y16", "AR24", "YUYV"],
                    help="Pixel format (default: Y16)")
    ap.add_argument("--device",    default=DEFAULT_DEVICE)
    ap.add_argument("--width",     type=int,   default=DEFAULT_WIDTH)
    ap.add_argument("--height",    type=int,   default=DEFAULT_HEIGHT)
    ap.add_argument("--fps",       type=int,   default=DEFAULT_FPS)
    ap.add_argument("--window",    type=int,   default=DEFAULT_WINDOW,
                    help=f"Sliding window size in frames (default: {DEFAULT_WINDOW})")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"Window-std spike threshold (default: {DEFAULT_THRESHOLD})")
    ap.add_argument("--out-dir",   default=DEFAULT_OUT_DIR,
                    help="Output directory for spike frame dumps")
    ap.add_argument("--log",       default=DEFAULT_LOG,
                    help="CSV log path")
    ap.add_argument("--duration",  type=float, default=0,
                    help="Run duration in seconds (0 = until Ctrl-C)")
    args = ap.parse_args()

    gst_fmt = FORMAT_GST[args.format]
    gst = (
        f"v4l2src device={args.device} ! "
        f"video/x-raw,format={gst_fmt},width={args.width},height={args.height} ! "
        f"queue max-size-buffers=2 leaky=downstream ! "
        f"appsink max-buffers=2 drop=true sync=false"
    )
    cap = cv2.VideoCapture(gst, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open {args.device} in {args.format} mode", file=sys.stderr)
        sys.exit(1)

    actual_fps    = cap.get(cv2.CAP_PROP_FPS)
    actual_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Device:    {args.device}  ({actual_width}x{actual_height} @ {actual_fps} fps)"
          f"  format={args.format}")
    print(f"Window:    {args.window} frames  (half = {args.window // 2})")
    print(f"Threshold: {args.threshold}")
    print(f"Out dir:   {args.out_dir}")
    print(f"Log:       {args.log}")
    print("Press Ctrl-C to stop.\n")

    q          = queue.Queue(maxsize=QUEUE_MAXSIZE)
    stop_event = threading.Event()
    stats      = {"captured": 0, "processed": 0, "dropped": 0}
    lock       = threading.Lock()

    def _stop(sig, frame):
        print("\n[main] stopping...")
        stop_event.set()
        cap.release()  # unblocks cap.read() in capture_thread

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    ct = threading.Thread(target=capture_thread,
                          args=(cap, q, stop_event, stats, lock), daemon=False)
    pt = threading.Thread(target=processing_thread,
                          args=(q, stop_event, stats, lock, args), daemon=False)

    ct.start()
    pt.start()

    if args.duration > 0:
        time.sleep(args.duration)
        stop_event.set()
        cap.release()  # unblocks cap.read() in capture_thread

    ct.join()
    pt.join()

    with lock:
        c, p, d = stats["captured"], stats["processed"], stats["dropped"]
    print(f"[done] captured={c}  processed={p}  dropped={d}")
    if d:
        print(f"[WARN] {d} frame(s) dropped")


if __name__ == "__main__":
    main()
