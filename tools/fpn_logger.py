#!/usr/bin/env python3
"""
Real-time FPN logger at 60 fps from /dev/video0 (AR24, 640x480).
Captures frames, computes Fixed-Pattern Noise, logs to /tmp/fpn_log.csv,
saves each frame momentarily to /tmp, then deletes it.

Usage:
    python3 fpn_logger.py [--device /dev/video0] [--duration 60]
"""
import argparse
import csv
import os
import queue
import signal
import sys
import threading
import time

import cv2
import numpy as np

# -- Configuration -------------------------------------------------------------
WIDTH  = 640
HEIGHT = 480
FPS    = 60
FOURCC = cv2.VideoWriter_fourcc(*"AR24")   # BGRA 32-bit
LOG_PATH   = "/tmp/fpn_log.csv"
FRAME_DIR  = "/tmp"
MAX_QUEUE  = 4   # frames; if exceeded -> captured but processing can't keep up

# -- Shared state --------------------------------------------------------------
frame_queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
stop_event  = threading.Event()

stats = {
    "captured":  0,
    "processed": 0,
    "dropped":   0,
}
stats_lock = threading.Lock()


# -- FPN computation -----------------------------------------------------------
def compute_fpn(bgra: np.ndarray) -> dict:
    """
    Fixed-Pattern Noise metrics from a single frame.

    - column_fpn : std of per-column means (vertical stripes)
    - row_fpn    : std of per-row means    (horizontal stripes)
    - global_std : overall pixel std (FPN + shot noise)

    All computed on the luma channel (Y = 0.299R + 0.587G + 0.114B)
    to avoid colour-channel artefacts.
    """
    b = bgra[:, :, 0].astype(np.float32)
    g = bgra[:, :, 1].astype(np.float32)
    r = bgra[:, :, 2].astype(np.float32)
    luma = 0.114 * b + 0.587 * g + 0.299 * r  # shape (480, 640)

    col_means  = luma.mean(axis=0)   # (640,)
    row_means  = luma.mean(axis=1)   # (480,)

    return {
        "column_fpn": float(col_means.std()),
        "row_fpn":    float(row_means.std()),
        "global_std": float(luma.std()),
        "mean_luma":  float(luma.mean()),
    }


# -- Capture thread ------------------------------------------------------------
def capture_thread(device: str):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open {device}", file=sys.stderr)
        stop_event.set()
        return

    cap.set(cv2.CAP_PROP_FOURCC,         FOURCC)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,    WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,   HEIGHT)
    cap.set(cv2.CAP_PROP_FPS,            FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,     2)

    actual_fps    = cap.get(cv2.CAP_PROP_FPS)
    actual_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[capture] {actual_width}x{actual_height} @ {actual_fps} fps")

    while not stop_event.is_set():
        ret, frame = cap.read()
        ts = time.time()
        if not ret:
            print("[capture] grab failed", file=sys.stderr)
            continue

        with stats_lock:
            stats["captured"] += 1

        try:
            frame_queue.put_nowait((ts, frame.copy()))
        except queue.Full:
            with stats_lock:
                stats["dropped"] += 1

    cap.release()
    print("[capture] stopped")


# -- Processing thread ---------------------------------------------------------
def processing_thread():
    with open(LOG_PATH, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "timestamp_s",
            "frame_index",
            "column_fpn",
            "row_fpn",
            "global_std",
            "mean_luma",
        ])
        csvfile.flush()

        frame_index = 0
        t0 = None

        while not stop_event.is_set() or not frame_queue.empty():
            try:
                ts, frame = frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if t0 is None:
                t0 = ts

            frame_path = os.path.join(FRAME_DIR, f"frame_{frame_index:06d}.png")
            cv2.imwrite(frame_path, frame)

            fpn = compute_fpn(frame)

            writer.writerow([
                f"{ts - t0:.6f}",
                frame_index,
                f"{fpn['column_fpn']:.4f}",
                f"{fpn['row_fpn']:.4f}",
                f"{fpn['global_std']:.4f}",
                f"{fpn['mean_luma']:.4f}",
            ])
            csvfile.flush()

            os.unlink(frame_path)

            frame_index += 1
            with stats_lock:
                stats["processed"] += 1

    print("[processing] stopped")


# -- Statistics printer --------------------------------------------------------
def stats_thread(interval: float = 5.0):
    while not stop_event.is_set():
        time.sleep(interval)
        with stats_lock:
            c = stats["captured"]
            p = stats["processed"]
            d = stats["dropped"]
        queue_depth = frame_queue.qsize()
        print(f"[stats] captured={c}  processed={p}  dropped={d}  "
              f"queue={queue_depth}/{MAX_QUEUE}")


# -- Main ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device",   default="/dev/video0")
    parser.add_argument("--duration", type=float, default=0,
                        help="Run duration in seconds (0 = run until Ctrl+C)")
    args = parser.parse_args()

    def _signal_handler(sig, frame):
        print("\n[main] stopping...")
        stop_event.set()

    signal.signal(signal.SIGINT,  _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    threads = [
        threading.Thread(target=capture_thread,    args=(args.device,), daemon=False),
        threading.Thread(target=processing_thread, daemon=False),
        threading.Thread(target=stats_thread,      daemon=True),
    ]
    for t in threads:
        t.start()

    if args.duration > 0:
        time.sleep(args.duration)
        stop_event.set()

    for t in threads:
        t.join()

    with stats_lock:
        c = stats["captured"]
        p = stats["processed"]
        d = stats["dropped"]

    print(f"\n[done] captured={c}  processed={p}  dropped={d}")
    if d > 0:
        print(f"[WARN] {d} frames dropped")
    print(f"[done] log -> {LOG_PATH}")


if __name__ == "__main__":
    main()
