#!/usr/bin/env python3
"""
Tegra NVCSI/VI diagnostic tool
Equivalent of read_unicam.py for Raspberry Pi, adapted for NVIDIA Jetson.

Decodes RTCPU tracing events, VI capture errors, and NVCSI interrupt status
into human-readable diagnostics.

Usage:
  sudo python3 read_nvcsi.py          # full diagnostic (enable traces, capture, decode)
  sudo python3 read_nvcsi.py --enable # enable tracing only (like old nvcsi_traces.sh)
  sudo python3 read_nvcsi.py --read   # read and decode current trace buffer (no new capture)

Run while streaming: sudo python3 read_nvcsi.py
Sources: camrtc-capture.h (L4T kernel headers)
"""

import os
import re
import subprocess
import sys
import time
from collections import defaultdict

# ---------------------------------------------------------------------------
# --enable mode: equivalent of former nvcsi_traces.sh
# ---------------------------------------------------------------------------
if "--enable" in sys.argv:
    if os.geteuid() != 0:
        sys.exit("Run as root: sudo python3 read_nvcsi.py --enable")
    TRACE = "/sys/kernel/debug/tracing"
    os.system("modprobe rtcpu_debug 2>/dev/null")
    for path, val in [
        (f"{TRACE}/tracing_on",                              "1"),
        (f"{TRACE}/buffer_size_kb",                          "30720"),
        (f"{TRACE}/events/tegra_rtcpu/enable",               "1"),
        (f"{TRACE}/events/freertos/enable",                  "1"),
        (f"/sys/kernel/debug/camrtc/log-level",              "3"),
        (f"{TRACE}/events/camera_common/enable",             "1"),
        (f"{TRACE}/trace",                                   ""),
    ]:
        try:
            with open(path, "w") as f:
                f.write(val)
        except Exception:
            pass
    print("Tracing enabled. Stream your camera, then read the trace:")
    print("  cat /sys/kernel/debug/tracing/trace | less")
    print("  # or in real time:")
    print("  cat /sys/kernel/debug/tracing/trace_pipe")
    print()
    print("Or run the full diagnostic:")
    print("  sudo python3 read_nvcsi.py")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Error bit tables  (from camrtc-capture.h)
# ---------------------------------------------------------------------------

# rtcpu_nvcsi_intr type:STREAM_VC  status field
NVCSI_VC_ERR_BITS = {
    0: ("PPFSM_TIMEOUT",        "Packet parser FSM timeout — no FS/FE received within timeout window"),
    1: ("PH_ECC_SINGLE_BIT",    "Packet header single-bit ECC error (corrected)"),
    2: ("PD_CRC_ERR",           "Payload data CRC error — data corruption in CSI-2 payload"),
    3: ("PD_WC_SHORT_ERR",      "Payload word count short — fewer bytes than header WC field"),
    4: ("PH_SINGLE_CRC_ERR",    "Packet header single CRC error"),
}

# rtcpu_nvcsi_intr type:STREAM  status field (stream-level, not VC-specific)
NVCSI_STREAM_ERR_BITS = {
    0: ("PH_ECC_MULTI_BIT",     "Packet header multi-bit ECC error — uncorrectable header"),
    1: ("PH_BOTH_CRC_ERR",      "Both CRC errors in packet header"),
}

# rtcpu_nvcsi_intr type:CIL  status field (D-PHY physical layer)
NVCSI_CIL_ERR_BITS = {
    0:  ("CLK_LANE_CTRL_ERR",     "Clock lane control error"),
    1:  ("SOT_SB_ERR0",           "Lane 0 start-of-transmission single-bit error"),
    2:  ("SOT_MB_ERR0",           "Lane 0 start-of-transmission multi-bit error"),
    3:  ("CTRL_ERR0",             "Lane 0 control error"),
    4:  ("RXFIFO_FULL_ERR0",      "Lane 0 RX FIFO overflow"),
    5:  ("SOT_SB_ERR1",           "Lane 1 start-of-transmission single-bit error"),
    6:  ("SOT_MB_ERR1",           "Lane 1 start-of-transmission multi-bit error"),
    7:  ("CTRL_ERR1",             "Lane 1 control error"),
    8:  ("RXFIFO_FULL_ERR1",      "Lane 1 RX FIFO overflow"),
    9:  ("DESKEW_CALIB_ERR0",     "Lane 0 deskew calibration error"),
    10: ("DESKEW_CALIB_ERR1",     "Lane 1 deskew calibration error"),
    11: ("DESKEW_CALIB_ERR_CTRL", "Clock lane deskew calibration error"),
    12: ("LANE_ALIGN_ERR",        "D-PHY lane alignment error"),
    13: ("ESC_SYNC_ERR0",         "Lane 0 escape mode sync error"),
    14: ("ESC_SYNC_ERR1",         "Lane 1 escape mode sync error"),
    15: ("SOT_2LSB_ERR0",         "Lane 0 start-of-transmission 2-LSB error"),
    16: ("SOT_2LSB_ERR1",         "Lane 1 start-of-transmission 2-LSB error"),
}

# VI corr_err / uncorr_err  err_data field  (CAPTURE_CHANNEL_ERROR_* bits)
VI_ERR_DATA_BITS = {
    5:  ("PIXEL_MISSING_LE",      "Pixel line end not received — line cut short by camera"),
    6:  ("PIXEL_RUNAWAY",         "Excessive pixel data (runaway) — camera sent too many pixels"),
    7:  ("PIXEL_SPURIOUS",        "Spurious pixel data outside a valid frame"),
    8:  ("PIXEL_LONG_LINE",       "Line longer than configured — camera sent more pixels than expected"),
    9:  ("PIXEL_SHORT_LINE",      "Line shorter than configured — camera sent fewer pixels than expected"),
    10: ("EMBED_MISSING_LE",      "Embedded data: line end not received"),
    11: ("EMBED_RUNAWAY",         "Embedded data: runaway"),
    12: ("EMBED_SPURIOUS",        "Embedded data: spurious"),
    13: ("EMBED_LONG_LINE",       "Embedded data: line too long"),
    14: ("EMBED_INFRINGE",        "Embedded data infringe"),
    15: ("DTYPE_MISMATCH",        "Data type mismatch — DT in header ≠ configured DT"),
    16: ("LOAD_FRAMED",           "Frame loaded out of expected order"),
    17: ("FORCE_FE",              "Frame end forced by CSIMUX stream reset or timeout"),
    18: ("COLLISION",             "Channel collision — two channels received the same VC/DT"),
    19: ("STALE_FRAME",           "Stale frame — buffer reused before frame completed"),
    20: ("INCOMPLETE",            "Incomplete frame"),
    21: ("ERROR_EMBED_INCOMPLETE","Embedded data incomplete"),
    22: ("VI_PFSD_FAULT",         "VI pixel format/stride detector fault"),
    23: ("VI_FRAME_START_TIMEOUT","VI frame start timeout — no SOF received"),
}

# ---------------------------------------------------------------------------
# RTCPU trace intr type → bit table mapping
# ---------------------------------------------------------------------------
INTR_TYPE_BITS = {
    "STREAM_VC": NVCSI_VC_ERR_BITS,
    "STREAM":    NVCSI_STREAM_ERR_BITS,
    "CIL":       NVCSI_CIL_ERR_BITS,
}

# ---------------------------------------------------------------------------
# VI notify (rtcpu_vinotify_*) tag tables
# ---------------------------------------------------------------------------

# Tags that always represent errors (appear in rtcpu_vinotify_error, and
# also in rtcpu_vinotify_event when forwarded as informational copies)
VINOTIFY_ERROR_TAGS = {
    "CHANSEL_NOMATCH":        "No capture channel matched this VC/DT — camera sends an "
                              "unconfigured data type or virtual channel",
    "CHANSEL_COLLISION":      "Two capture channels matched the same incoming VC/DT",
    "ATOMP_PACKER_OVERFLOW":  "ATOMP packer overflow — memory write rate exceeded",
    "ATOMP_FRAME_TRUNCATED":  "Frame truncated — not all lines were captured",
    "CSIMUX_FRAME":           "CSIMUX frame error forwarded from NVCSI (CRC/ECC/timeout)",
    "CSIMUX_STREAM":          "CSIMUX stream error forwarded from NVCSI",
    "PIXFMT_ERR":             "Pixel format detector error — format/stride mismatch",
    "PIXFMT_PXFMT_ERR":       "Pixel format detector error (pxfmt variant)",
    "CHANSEL_SHORT_FRAME":    "Frame ended before all configured lines were received",
    "CHANSEL_FAULT":          "Channel selector fault — VI hardware error in channel selection",
}

# Tags that are purely informational (normal per-frame events)
VINOTIFY_INFO_TAGS = {
    "FS", "FE", "LINE_START", "LINE_END",
    "CHANSEL_PXL_SOF", "CHANSEL_PXL_EOF",
    "ATOMP_FS", "ATOMP_FE", "ATOMP_FRAME_DONE",
    "VIFALC_ACTIONLST", "VIFALC_TDSTATE",
}

# V4L2 pixel format → (CSI-2 DT code, CSI-2 DT name)
PIXFMT_TO_CSI2DT = {
    'Y16 ': (0x2e, 'RAW16'),
    'Y16B': (0x2e, 'RAW16 BE'),
    'GREY': (0x2a, 'RAW8'),
    'BA81': (0x2a, 'RAW8'),
    'YUYV': (0x1e, 'YUV422-8'),
    'UYVY': (0x1e, 'YUV422-8'),
    'NV12': (0x1e, 'YUV422-8'),
    'RG10': (0x2b, 'RAW10'),
    'BG10': (0x2b, 'RAW10'),
    'RG12': (0x2c, 'RAW12'),
    'BG12': (0x2c, 'RAW12'),
    'RG16': (0x2e, 'RAW16'),
    'BG16': (0x2e, 'RAW16'),
    'RGB3': (0x24, 'RGB888'),
    'BGR3': (0x24, 'RGB888'),
}

# CSI-2 data type names (for CHANSEL_NOMATCH data decode)
CSI2_DT = {
    0x00: "FS",          0x01: "FE",       0x02: "LS",         0x03: "LE",
    0x08: "Generic8",    0x09: "Generic9",  0x0a: "Generic10",  0x0b: "Generic11",
    0x0c: "Generic12",   0x0d: "Generic13", 0x0e: "Generic14",  0x0f: "Generic15",
    0x10: "Null",        0x11: "Blanking",  0x12: "Embedded",
    0x18: "YUV420-8",    0x19: "YUV420-10", 0x1a: "YUV420-8CS",
    0x1c: "YUV420-8L",   0x1d: "YUV420-10L",
    0x1e: "YUV422-8",    0x1f: "YUV422-10",
    0x20: "RGB444",      0x21: "RGB555",    0x22: "RGB565",
    0x23: "RGB666",      0x24: "RGB888",
    0x28: "RAW6",        0x29: "RAW7",      0x2a: "RAW8",
    0x2b: "RAW10",       0x2c: "RAW12",     0x2d: "RAW14",
    0x2e: "RAW16",       0x2f: "RAW20",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sep(title=""):
    w = 60
    if title:
        print(f"\n{'─'*20} {title} {'─'*(w - 22 - len(title))}")
    else:
        print("─" * w)

def run(cmd, check=False):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return "", str(e)

def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None

def decode_bits(value, bit_table, prefix="  "):
    lines = []
    for bit, (name, desc) in sorted(bit_table.items()):
        if value & (1 << bit):
            lines.append(f"{prefix}[bit{bit:2d}] {name:<28s}  {desc}")
    return lines

# ---------------------------------------------------------------------------
# Check root
# ---------------------------------------------------------------------------
if os.geteuid() != 0:
    sys.exit("Run as root: sudo python3 read_nvcsi.py")

# ---------------------------------------------------------------------------
# Mount debugfs if needed
# ---------------------------------------------------------------------------
if not os.path.exists("/sys/kernel/debug/tracing"):
    os.system("mount -t debugfs none /sys/kernel/debug 2>/dev/null")

# ---------------------------------------------------------------------------
sep()
print("  Tegra NVCSI/VI diagnostic tool")
sep()

# ---------------------------------------------------------------------------
sep("PLATFORM")
# ---------------------------------------------------------------------------
compatible = read_file("/proc/device-tree/compatible")
if compatible:
    parts = [p for p in compatible.split("\x00") if p]
    print(f"  compatible        : {', '.join(parts)}")

uname, _ = run("uname -r")
print(f"  kernel            : {uname}")

nv_release = read_file("/etc/nv_tegra_release")
if nv_release:
    print(f"  L4T release       : {nv_release.split(chr(10))[0]}")

# ---------------------------------------------------------------------------
sep("CLOCKS  (BPMP debugfs)")
# ---------------------------------------------------------------------------
CLK_BASE = "/sys/kernel/debug/bpmp/debug/clk"
clk_rates = {}
# Read nvcsilp first so we can use it when annotating nvcsi
for clk_name in ("nvcsilp", "nvcsi", "vi", "nafll_vi"):
    rate = read_file(f"{CLK_BASE}/{clk_name}/rate")
    state = read_file(f"{CLK_BASE}/{clk_name}/state") or "?"
    if rate is not None:
        clk_rates[clk_name] = int(rate)
        mhz = int(rate) / 1e6
        tag = ""
        # nvcsi = control/reference clock (T234: typically low, ~28 MHz)
        # nvcsilp = data path clock (T234: typically 204–408 MHz during stream)
        if clk_name == "nvcsilp" and int(rate) < 50_000_000:
            tag = "  ← LOW (expected ~204–408 MHz during stream)"
        elif clk_name == "nvcsi":
            nvcsilp = clk_rates.get("nvcsilp", 0)
            if nvcsilp < 50_000_000 and int(rate) < 50_000_000:
                tag = "  ← LOW (expected ~204–408 MHz during stream)"
            elif nvcsilp >= 50_000_000:
                tag = "  (reference/ctrl clock; nvcsilp is the data path clock)"
        elif clk_name == "vi" and int(rate) < 50_000_000:
            tag = "  ← LOW (expected ≥100 MHz during stream)"
        print(f"  {clk_name:<16s}  {mhz:8.3f} MHz  (state={state}){tag}")

# ---------------------------------------------------------------------------
sep("CAMRTC")
# ---------------------------------------------------------------------------
camrtc_ver = read_file("/sys/kernel/debug/camrtc/version")
camrtc_log = read_file("/sys/kernel/debug/camrtc/log-level")
if camrtc_ver:
    print(f"  version     : {camrtc_ver}")
if camrtc_log is not None:
    print(f"  log-level   : {camrtc_log}")

# ---------------------------------------------------------------------------
sep("KERNEL MODULES")
# ---------------------------------------------------------------------------
lsmod, _ = run("lsmod")
cam_mods = [l for l in lsmod.splitlines() if re.search(r"nvcsi|tegra_vi|tegra_camera|vi5|vi4", l, re.I)]
if cam_mods:
    for l in cam_mods:
        print(f"  {l}")
else:
    print("  (no camera-related modules found)")

# ---------------------------------------------------------------------------
sep("DEVICE TOPOLOGY  (media-ctl)")
# ---------------------------------------------------------------------------
topology, err = run("media-ctl -d /dev/media0 -p 2>/dev/null")
if topology:
    # Print abbreviated topology
    for line in topology.splitlines():
        if re.match(r"\s*[-]", line) or "entity" in line or "pad" in line or "link" in line:
            print(f"  {line.rstrip()}")
else:
    print(f"  (no media controller: {err})")

# ---------------------------------------------------------------------------
sep("V4L2 FORMAT")
# ---------------------------------------------------------------------------
fmt, _ = run("v4l2-ctl -d /dev/video0 --get-fmt-video 2>/dev/null")
v4l2_width = v4l2_height = v4l2_bpl = v4l2_size = 0
v4l2_pixfmt = ""
if fmt:
    for line in fmt.splitlines():
        print(f"  {line.rstrip()}")
        m = re.search(r'Width/Height\s*:\s*(\d+)/(\d+)', line)
        if m:
            v4l2_width, v4l2_height = int(m.group(1)), int(m.group(2))
        m = re.search(r"Pixel Format\s*:\s*'(.{4})'", line)
        if m:
            v4l2_pixfmt = m.group(1)
        m = re.search(r'Bytes per Line\s*:\s*(\d+)', line)
        if m:
            v4l2_bpl = int(m.group(1))
        m = re.search(r'Size Image\s*:\s*(\d+)', line)
        if m:
            v4l2_size = int(m.group(1))

# ---------------------------------------------------------------------------
# Streaming detection (used by DMESG and TRACE sections)
# Find the process that has /dev/video0 open and use its start time as cutoff.
# /proc/PID/stat field 22 = starttime in USER_HZ (100 ticks/s) since boot.
def find_stream_start_time():
    try:
        video_devs = set()
        # Resolve major:minor of /dev/video* to find which one is open
        for vdev in ("/dev/video0", "/dev/video1", "/dev/video2"):
            try:
                st = os.stat(vdev)
                video_devs.add((os.major(st.st_rdev), os.minor(st.st_rdev)))
            except Exception:
                pass
        if not video_devs:
            return None, "no /dev/video* found"

        earliest = None
        found_pids = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                fd_dir = f"/proc/{pid}/fd"
                for fd in os.listdir(fd_dir):
                    try:
                        link = os.readlink(f"{fd_dir}/{fd}")
                        if not link.startswith("/dev/video"):
                            continue
                        st = os.stat(f"{fd_dir}/{fd}")
                        if (os.major(st.st_rdev), os.minor(st.st_rdev)) not in video_devs:
                            continue
                        # Read starttime from /proc/PID/stat
                        stat = open(f"/proc/{pid}/stat").read().split()
                        starttime_ticks = int(stat[21])   # field 22, 0-indexed = 21
                        start_s = starttime_ticks / 100.0  # USER_HZ = 100
                        cmdline = open(f"/proc/{pid}/cmdline").read().replace("\x00", " ").strip()
                        found_pids.append((pid, start_s, cmdline[:40]))
                        if earliest is None or start_s < earliest:
                            earliest = start_s
                    except Exception:
                        pass
            except Exception:
                pass

        if earliest is not None:
            seen = set()
            unique = [(p, s, c) for p, s, c in found_pids if not (p in seen or seen.add(p))]
            desc = ", ".join(f"pid={p} ({c})" for p, s, c in unique)
            return earliest, desc
        return None, "no process has /dev/video* open"
    except Exception as e:
        return None, str(e)

stream_start, stream_info = find_stream_start_time()
no_streaming = (stream_start is None and stream_info == "no process has /dev/video* open")

# ---------------------------------------------------------------------------
sep("STREAMING STATUS")
# ---------------------------------------------------------------------------
if no_streaming:
    print("  No streaming process detected (no /dev/video* open).")
    print("  Run this script while the camera is streaming.")
    sep()
    sys.exit(0)
else:
    print(f"  Active stream     : {stream_info}")

# ---------------------------------------------------------------------------
sep("DMESG — CAPTURE ERRORS (since stream start)")
# ---------------------------------------------------------------------------
if stream_start is not None:
    cutoff = stream_start
    cutoff_label = f"stream start (pid: {stream_info})"
else:
    # Fallback: scan dmesg for beginning of current corr_err burst
    # Find the first corr_err that belongs to the latest uninterrupted sequence
    # by looking for a gap > 5 s before the most recent errors.
    cutoff = 0.0
    cutoff_label = "boot (no streaming process found)"
    try:
        dmesg_pre, _ = run("dmesg")
        ts_re = re.compile(r"^\[\s*([\d.]+)\]")
        err_re = re.compile(r"corr_err:|uncorr_err:")
        err_timestamps = []
        for line in dmesg_pre.splitlines():
            if err_re.search(line):
                m = ts_re.match(line)
                if m:
                    err_timestamps.append(float(m.group(1)))
        if err_timestamps:
            # Walk backward to find the start of the current burst (gap > 5 s)
            burst_start = err_timestamps[-1]
            for i in range(len(err_timestamps) - 2, -1, -1):
                if err_timestamps[i + 1] - err_timestamps[i] > 5.0:
                    burst_start = err_timestamps[i + 1]
                    break
                burst_start = err_timestamps[i]
            cutoff = burst_start
            cutoff_label = f"first error in current burst (t={cutoff:.1f} s)"
    except Exception:
        pass

print(f"  Filtering from : {cutoff_label}")

dmesg, _ = run("dmesg")
DMESG_TS_RE = re.compile(r"^\[\s*([\d.]+)\]")
CORR_RE     = re.compile(r"corr_err: discarding frame (\d+), flags: (\d+), err_data (\d+)")
UNCORR_RE   = re.compile(r"uncorr_err: discarding frame (\d+), flags: (\d+), err_data (\d+)")

corr_counter   = defaultdict(int)  # err_data → count
uncorr_counter = defaultdict(int)
all_corr_lines = []
all_uncorr_lines = []

for line in dmesg.splitlines():
    ts_m = DMESG_TS_RE.match(line)
    if ts_m and float(ts_m.group(1)) < cutoff:
        continue
    m = CORR_RE.search(line)
    if m:
        corr_counter[int(m.group(3))] += 1
        all_corr_lines.append(line)
    m = UNCORR_RE.search(line)
    if m:
        uncorr_counter[int(m.group(3))] += 1
        all_uncorr_lines.append(line)

if not corr_counter and not uncorr_counter:
    print(f"  No capture errors since stream start.")
else:
    if corr_counter:
        total = sum(corr_counter.values())
        print(f"  corr_err (correctable):   {total} frames discarded")
        for err_data, cnt in sorted(corr_counter.items()):
            bits = decode_bits(err_data, VI_ERR_DATA_BITS, prefix="      ")
            label = " | ".join(VI_ERR_DATA_BITS[b][0] for b in range(32)
                               if (err_data & (1<<b)) and b in VI_ERR_DATA_BITS)
            print(f"    err_data=0x{err_data:04x} ({err_data}): {cnt}× [{label or 'unknown'}]")
            for b in bits:
                print(b)
        if all_corr_lines:
            print(f"    last seen: {all_corr_lines[-1].split(']')[0].strip()}]")

    if uncorr_counter:
        total = sum(uncorr_counter.values())
        print(f"  uncorr_err (unrecoverable): {total} frames discarded")
        for err_data, cnt in sorted(uncorr_counter.items()):
            bits = decode_bits(err_data, VI_ERR_DATA_BITS, prefix="      ")
            label = " | ".join(VI_ERR_DATA_BITS[b][0] for b in range(32)
                               if (err_data & (1<<b)) and b in VI_ERR_DATA_BITS)
            print(f"    err_data=0x{err_data:04x} ({err_data}): {cnt}× [{label or 'unknown'}]")
            for b in bits:
                print(b)

# ---------------------------------------------------------------------------
TRACE_BASE = "/sys/kernel/debug/tracing"

def write_trace(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except Exception:
        pass

read_only = "--read" in sys.argv

if read_only:
    sep("RTCPU NVCSI TRACE  (existing buffer)")
    trace_raw = read_file(f"{TRACE_BASE}/trace") or ""
else:
    sep("RTCPU NVCSI TRACE  (1 s capture)")
    # Load rtcpu_debug module (optional, provides more detail)
    os.system("modprobe rtcpu_debug 2>/dev/null")

    # Setup tracing
    write_trace(f"{TRACE_BASE}/tracing_on", 1)
    write_trace(f"{TRACE_BASE}/buffer_size_kb", 4096)
    write_trace(f"{TRACE_BASE}/events/tegra_rtcpu/enable", 1)
    write_trace(f"{TRACE_BASE}/events/camera_common/enable", 1)

    # Clear buffer then capture
    write_trace(f"{TRACE_BASE}/trace", "")
    time.sleep(1.0)
    trace_raw = read_file(f"{TRACE_BASE}/trace") or ""

    # Stop tracing to avoid filling buffer
    write_trace(f"{TRACE_BASE}/events/tegra_rtcpu/enable", 0)
    write_trace(f"{TRACE_BASE}/events/camera_common/enable", 0)

# --- Parse rtcpu_nvcsi_intr lines ---
# Example: rtcpu_nvcsi_intr: tstamp:... class:CORRECTABLE_ERR type:STREAM_VC phy:0 cil:0 st:1 vc:0 status:0x00000004
INTR_RE = re.compile(
    r"rtcpu_nvcsi_intr: tstamp:(\d+) class:(\S+) type:(\S+) phy:(\d+) cil:(\d+) st:(\d+) vc:(\d+) status:(0x[0-9a-f]+)")

# Aggregate: (class, type, phy, cil, st, vc, status) → count
intr_counter = defaultdict(int)
for m in INTR_RE.finditer(trace_raw):
    key = (m.group(2), m.group(3), int(m.group(4)), int(m.group(5)),
           int(m.group(6)), int(m.group(7)), int(m.group(8), 16))
    intr_counter[key] += 1

# --- Parse camera_common capture events ---
FRAME_RE  = re.compile(r"tegra_channel_capture_frame: (sof|eof):([\d.]+)")
SETUP_RE  = re.compile(r"tegra_channel_capture_setup: (.+)")
DONE_RE   = re.compile(r"tegra_channel_capture_done: (.+)")

frame_events = FRAME_RE.findall(trace_raw)
setup_events = SETUP_RE.findall(trace_raw)
done_events  = DONE_RE.findall(trace_raw)

frame_count = sum(1 for e, _ in frame_events if e == "sof")

if not intr_counter:
    print("  No NVCSI interrupts captured in trace.")
else:
    print(f"  NVCSI interrupt events     :")
    for (cls, typ, phy, cil, st, vc, status), cnt in sorted(intr_counter.items(),
                                                              key=lambda x: -x[1]):
        bit_table = INTR_TYPE_BITS.get(typ, {})
        labels = [bit_table[b][0] for b in range(32)
                  if (status & (1 << b)) and b in bit_table]
        label_str = " | ".join(labels) if labels else "unknown"
        print(f"\n    [{cls}] type={typ} phy={phy} cil={cil} stream={st} vc={vc}"
              f"  status=0x{status:08x}  ×{cnt}")
        for bit, (name, desc) in sorted(bit_table.items()):
            if status & (1 << bit):
                print(f"      [bit{bit}] {name:<28s}  {desc}")

# --- Parse rtcpu_vinotify_error and rtcpu_vinotify_event ---
# Example:
#   rtcpu_vinotify_error: tstamp:... cch:0 vi:0 tag:CHANSEL_NOMATCH channel:0x02 frame:2048 vi_tstamp:... data:0x5c9
#   rtcpu_vinotify_event: tstamp:... cch:0 vi:0 tag:CHANSEL_PXL_EOF channel:0x23 frame:2048 vi_tstamp:... data:0x7f0002
VINOTIFY_RE = re.compile(
    r"rtcpu_vinotify_(error|event): tstamp:(\d+) cch:(\d+) vi:(\d+) "
    r"tag:(\S+) channel:(0x[0-9a-f]+) frame:(\d+) vi_tstamp:\d+ data:(0x[0-9a-f]+)")

# Aggregate: (kind, tag, cch, vi, channel) → count
vinotify_err_counter  = defaultdict(int)   # error-class events
vinotify_info_counter = defaultdict(int)   # informational events
vinotify_unk_counter  = defaultdict(int)   # unknown tags

for m in VINOTIFY_RE.finditer(trace_raw):
    kind    = m.group(1)          # "error" or "event"
    tag     = m.group(5)
    cch     = int(m.group(3))
    vi      = int(m.group(4))
    channel = int(m.group(6), 16)
    data    = int(m.group(8), 16)
    key = (kind, tag, cch, vi, channel, data)
    if tag in VINOTIFY_ERROR_TAGS:
        vinotify_err_counter[key] += 1
    elif tag in VINOTIFY_INFO_TAGS:
        vinotify_info_counter[key] += 1
    else:
        vinotify_unk_counter[key] += 1

def decode_chansel_data(data):
    """Decode CHANSEL_NOMATCH data field: bits[5:0]=DT, [7:6]=VC, [12:8]=stream."""
    dt     = data & 0x3f
    vc     = (data >> 6) & 0x3
    stream = (data >> 8) & 0x1f
    dt_name = CSI2_DT.get(dt, f"0x{dt:02x}")
    return f"stream={stream} VC={vc} DT={dt_name}(0x{dt:02x})"

def decode_pxl_eof_data(data):
    """CHANSEL_PXL_EOF data: bits[23:16]=last_line (0-indexed)."""
    last_line = (data >> 16) & 0xff
    return f"last_line={last_line} → {last_line + 1} lines"

# --- Merge error events (CHANSEL_NOMATCH fires as both error+event → deduplicate) ---
merged_err = defaultdict(int)
merged_err_data = {}
for (kind, tag, cch, vi, channel, data), cnt in vinotify_err_counter.items():
    key2 = (tag, cch, vi, channel, data)
    merged_err[key2] += cnt
    merged_err_data[key2] = data

# --- Aggregate info tag counts ---
info_counts = defaultdict(int)
for (kind, tag, cch, vi, ch, data), cnt in vinotify_info_counter.items():
    info_counts[tag] += cnt

# CHANSEL_PXL_EOF: decode captured height (bits[31:16] = last line, 0-indexed)
pxl_eof_heights = set()
for (kind, tag, cch, vi, ch, data), cnt in vinotify_info_counter.items():
    if tag == "CHANSEL_PXL_EOF":
        last_line = (data >> 16) & 0xffff
        pxl_eof_heights.add(last_line + 1)

fs_hw      = info_counts.get("FS", 0)
fe_hw      = info_counts.get("FE", 0)
pxl_sof    = info_counts.get("CHANSEL_PXL_SOF", 0)
pxl_eof    = info_counts.get("CHANSEL_PXL_EOF", 0)
atomp_fs   = info_counts.get("ATOMP_FS", 0)
atomp_fe   = info_counts.get("ATOMP_FE", 0)
atomp_done = info_counts.get("ATOMP_FRAME_DONE", 0)
line_start = info_counts.get("LINE_START", 0)

# --- Pipeline view ---
def prow(label, val, note=""):
    val_s = f"{val:5d}" if isinstance(val, int) else f"{'—':>5}"
    note_s = f"  ← {note}" if note else ""
    print(f"  {label:<46}: {val_s}{note_s}")

window = "buffer" if read_only else "1 s"
print(f"\n  ── Video pipeline ({window}) ────────────────────────────────────")

print(f"  [Camera / NVCSI]")
if fs_hw:
    trunc = fs_hw - fe_hw
    prow("    frames seen by VI         (FS )", fs_hw,
         f"{trunc} truncated (FE missing)" if trunc > 0 else "")
    prow("    frames ended              (FE )", fe_hw)
else:
    print(f"  {'    frames seen by VI         (FS )':<46}: {'—':>5}  (no FS events in trace)")

cap_ref = pxl_sof if pxl_sof else frame_count
dropped  = (fs_hw - cap_ref) if fs_hw > 0 and cap_ref > 0 else None

print(f"  [VI channel selector]")
prow("    captures started  (CHANSEL_PXL_SOF)", cap_ref,
     f"{dropped} dropped (no buffer)" if dropped and dropped > 0 else "")
if pxl_eof:
    heights_s = "/".join(str(h) for h in sorted(pxl_eof_heights)) if pxl_eof_heights else "?"
    prow("    captures ended    (CHANSEL_PXL_EOF)", pxl_eof,
         f"height={heights_s} lines")
if line_start:
    lines_per_frame = line_start // cap_ref if cap_ref else 0
    prow("    line-start events (LINE_START)", line_start,
         f"~{lines_per_frame} lines/frame" if lines_per_frame else "")

print(f"  [ATOMP DMA writer]")
if atomp_fs:
    prow("    DMA started       (ATOMP_FS  )", atomp_fs)
if atomp_fe:
    inc = atomp_fs - atomp_fe
    prow("    DMA ended         (ATOMP_FE  )", atomp_fe,
         f"{inc} DMA incomplete" if inc > 0 else "")
ref = atomp_fe or atomp_fs or cap_ref
nd = ref - atomp_done if ref and atomp_done and ref > atomp_done else 0
prow("    frames complete   (ATOMP_FRAME_DONE)", atomp_done,
     f"{nd} not delivered to app" if nd > 0 else "")

print(f"  [Driver]")
prow("    frames reported   (capture_frame SOF)", frame_count)

if setup_events:
    print(f"  capture_setup : {setup_events[0]}")

# Unknown vinotify tags
if vinotify_unk_counter:
    unk_tags = set(tag for (_, tag, *_) in vinotify_unk_counter)
    print(f"\n  Unknown vinotify tags (unclassified): {', '.join(sorted(unk_tags))}")

# --- Vinotify errors ---
if merged_err:
    collapsed = {}
    for (tag, cch, vi, channel, data), cnt in merged_err.items():
        key3 = (tag, channel)
        if key3 not in collapsed:
            collapsed[key3] = [cnt, data]
        else:
            collapsed[key3][0] += cnt

    print(f"\n  VI notify errors:")
    for (tag, channel), (cnt, data) in sorted(collapsed.items(), key=lambda x: -x[1][0]):
        desc = VINOTIFY_ERROR_TAGS.get(tag, "?")
        extra = f"  [{decode_chansel_data(data)}]" if tag == "CHANSEL_NOMATCH" else ""
        display_cnt = cnt // 2 if cnt % 2 == 0 else cnt
        print(f"\n    [WARN] {tag}  channel=0x{channel:02x}  ×{display_cnt}{extra}")
        print(f"           {desc}")
elif not intr_counter:
    print("  No vinotify errors captured in trace.")

# ---------------------------------------------------------------------------
sep("STREAM PARAMETERS")
# ---------------------------------------------------------------------------
# Note: on T234, NVCSI/VI registers are owned exclusively by the RTCPU;
# /dev/mem access is blocked by SMMU even as root, and /sys/kernel/debug/nvcsi
# is empty. DT/WC below are derived from V4L2 format (configured values).
# Actual received DT is only available for unmatched packets (CHANSEL_NOMATCH).
if v4l2_width and v4l2_size:
    csi2_dt_code, csi2_dt_name = PIXFMT_TO_CSI2DT.get(v4l2_pixfmt, (None, "unknown"))
    dt_str = (f"{csi2_dt_name} (DT=0x{csi2_dt_code:02x})" if csi2_dt_code
              else f"unknown (pixfmt='{v4l2_pixfmt}')")
    bpp = v4l2_bpl / v4l2_width if v4l2_width else 0

    print(f"  CSI-2 data type   : {dt_str}")
    print(f"  Frame geometry    : {v4l2_width} × {v4l2_height} px")
    print(f"  Word Count (WC)   : {v4l2_bpl} B/line  ({bpp:.2g} B/px)")
    print(f"  Bytes per frame   : {v4l2_size}  ({v4l2_size/1024:.1f} KB)")

    # Extra DT seen via CHANSEL_NOMATCH = packets the camera sends on top of the
    # main image stream (e.g. embedded data, metadata lines) with no configured
    # capture channel → ignored by VI, does not affect image quality.
    nomatch_dts = set()
    for (tag, cch, vi, channel, data) in merged_err:
        if tag == "CHANSEL_NOMATCH":
            dt = data & 0x3f
            vc = (data >> 6) & 0x3
            nomatch_dts.add((vc, dt, CSI2_DT.get(dt, f"0x{dt:02x}")))
    if nomatch_dts:
        for vc, dt, dt_name in sorted(nomatch_dts):
            print(f"  Extra camera pkts : VC={vc} DT=0x{dt:02x} ({dt_name})"
                  f"  (metadata/embedded — no capture channel configured, ignored by VI)")

    # Throughput: use FS (physical camera rate) if available, else driver SOF
    fps_hw = fs_hw if fs_hw > 0 else frame_count
    if fps_hw > 0:
        throughput_mbs = fps_hw * v4l2_size / 1e6
        fps_src = "camera FS events" if fs_hw else "driver SOF"
        print(f"  Camera frame rate : {fps_hw} fps  ({fps_src})")
        print(f"  Data throughput   : {throughput_mbs:.1f} MB/s  "
              f"({fps_hw} fps × {v4l2_size//1024} KB/frame)")
        # Note: D-PHY link rate = pix_clk_hz × bpp / num_lanes / 2 (DDR).
        # pix_clk_hz and num_lanes are DT properties, not read here.
        # nvcsilp is an internal NVCSI processing clock, not the D-PHY clock.

    # Height discrepancy: configured vs actually captured by VI
    if pxl_eof_heights:
        captured_h = max(pxl_eof_heights)
        if captured_h != v4l2_height:
            print(f"  [WARN] Height mismatch: configured={v4l2_height} px, "
                  f"captured={captured_h} px  (from CHANSEL_PXL_EOF)")
        else:
            print(f"  Captured height   : {captured_h} px  ✓ matches configured"
                  f"  (CHANSEL_PXL_EOF)")

# ---------------------------------------------------------------------------
sep("ERROR SUMMARY")
# ---------------------------------------------------------------------------
all_nvcsi_errors = list(intr_counter.keys())
corr_total   = sum(corr_counter.values())
uncorr_total = sum(uncorr_counter.values())
vinotify_total = sum(merged_err.values())

has_pd_crc       = any(k[1] == "STREAM_VC" and (k[6] & 0x4) for k in all_nvcsi_errors)
has_ppfsm        = any(k[1] == "STREAM_VC" and (k[6] & 0x1) for k in all_nvcsi_errors)
has_ph_ecc       = any(k[1] in ("STREAM_VC","STREAM") and (k[6] & 0x3) for k in all_nvcsi_errors)
has_cil_sot      = any(k[1] == "CIL" and (k[6] & 0x66) for k in all_nvcsi_errors)
has_cil_align    = any(k[1] == "CIL" and (k[6] & 0x1000) for k in all_nvcsi_errors)
has_short_line   = any((err_data & 0x200) for err_data in corr_counter)
has_long_line    = any((err_data & 0x100) for err_data in corr_counter)
has_dtype_mm     = any((err_data & 0x8000) for err_data in corr_counter)
has_chansel_nom   = any(tag == "CHANSEL_NOMATCH" for (tag, *_) in merged_err)
has_chansel_fault = any(tag == "CHANSEL_FAULT" for (tag, *_) in merged_err)
has_frame_trunc   = any(tag == "ATOMP_FRAME_TRUNCATED" for (tag, *_) in merged_err)
has_csimux_fwd    = any(tag in ("CSIMUX_FRAME","CSIMUX_STREAM") for (tag, *_) in merged_err)

if not any([corr_total, uncorr_total, all_nvcsi_errors, vinotify_total]):
    print("  OK — no errors detected during the observation window.")
else:
    if has_pd_crc:
        print("  [ERR] PD_CRC_ERR — CSI-2 payload data CRC mismatch")
    if has_ppfsm:
        print("  [ERR] PPFSM_TIMEOUT — no frame start/end within timeout")
    if has_ph_ecc:
        print("  [ERR] PH_ECC error — packet header bit error")
    if has_cil_sot:
        print("  [ERR] CIL SOT error — D-PHY start-of-transmission problem")
    if has_cil_align:
        print("  [ERR] CIL lane alignment error — D-PHY lanes not aligned")
    if has_short_line:
        print("  [ERR] PIXEL_SHORT_LINE — VI received fewer pixels than configured")
    if has_long_line:
        print("  [ERR] PIXEL_LONG_LINE — VI received more pixels than configured")
    if has_dtype_mm:
        print("  [ERR] DTYPE_MISMATCH — data type in packet ≠ configured type")
    if uncorr_total:
        print(f"  [ERR] {uncorr_total} unrecoverable frame(s) lost")
    if has_chansel_nom:
        # Find the decoded VC/DT for display
        for (tag, cch, vi, channel, data) in merged_err:
            if tag == "CHANSEL_NOMATCH":
                print(f"  [WARN] CHANSEL_NOMATCH — {decode_chansel_data(data)}"
                      f" has no capture channel")
                break
    if has_frame_trunc:
        print("  [WARN] ATOMP_FRAME_TRUNCATED — frames captured with fewer lines than configured")
    if has_chansel_fault:
        print("  [WARN] CHANSEL_FAULT — VI channel selector hardware fault")
    if has_csimux_fwd:
        print("  [WARN] CSIMUX error forwarded to VI (see NVCSI section above)")

# ---------------------------------------------------------------------------
sep("DIAGNOSIS")
# ---------------------------------------------------------------------------
diag = []

if has_pd_crc and not has_cil_sot and not has_cil_align:
    diag.append(
        "[!] PD_CRC_ERR with no D-PHY SOT/alignment errors\n"
        "    → Signal integrity issue at CSI-2 protocol level (not D-PHY level).\n"
        "    Likely causes:\n"
        "      1. Marginal MIPI signal: cable too long, poor connector, bad impedance\n"
        "      2. Wrong D-PHY settling time (mipi_cal, tclk_settle, ths_settle in DT)\n"
        "      3. MIPI clock too high for this cable length — try reducing pix_clk_hz\n"
        "      4. Wrong num-lanes in DT (e.g. 1 lane configured, camera sends 2)"
    )

if has_cil_sot:
    diag.append(
        "[!] CIL SOT errors — D-PHY physical layer problem\n"
        "    → Start-of-transmission sequence not recognized.\n"
        "    Likely causes:\n"
        "      1. Damaged or loose MIPI CSI-2 cable\n"
        "      2. Very long cable causing high capacitance\n"
        "      3. Wrong termination impedance\n"
        "      4. LP→HS transition timing mismatch (adjust tclk_settle/ths_settle)"
    )

if has_cil_align:
    diag.append(
        "[!] Lane alignment error — multi-lane cameras only\n"
        "    → Lanes arrive at different times exceeding alignment window.\n"
        "    Likely causes:\n"
        "      1. Skew between MIPI lanes (unequal PCB trace lengths)\n"
        "      2. Different cable lengths per lane\n"
        "      3. Deskew calibration needs retry (transient, may recover)"
    )

if has_ppfsm:
    diag.append(
        "[!] PPFSM timeout — no frame received within timeout window\n"
        "    → Camera may not be streaming or frame rate < PPFSM threshold.\n"
        "    Likely causes:\n"
        "      1. Camera not started / power issue\n"
        "      2. Frame rate set too low (increase or check frame_length_lines in DT)\n"
        "      3. I2C configuration issue (camera not fully initialized)"
    )

if has_short_line and not has_pd_crc:
    diag.append(
        "[!] PIXEL_SHORT_LINE without CRC errors\n"
        "    → Line width mismatch between camera and DT configuration.\n"
        "    Likely causes:\n"
        "      1. Wrong active_w in DT (camera sends narrower lines)\n"
        "      2. Wrong num-lanes (extra bytes consumed by incorrect lane interleaving)\n"
        "      3. Camera in a different mode than configured (check sensor_mode_id)"
    )

if has_dtype_mm:
    diag.append(
        "[!] DTYPE_MISMATCH — pixel format mismatch\n"
        "    → Camera sends a different CSI-2 data type than VI expects.\n"
        "    Check: pixel_phase in DT vs actual camera output format\n"
        "           (RAW16=0x2e, RAW8=0x2a, YUV422=0x1e, GREY16=0x2e)"
    )

if has_chansel_nom:
    # Retrieve the nomatch info for diagnosis
    nom_entries = [(tag, cch, vi, channel, data) for (tag, cch, vi, channel, data)
                   in merged_err if tag == "CHANSEL_NOMATCH"]
    for (tag, cch, vi, channel, data) in nom_entries:
        dt     = data & 0x3f
        vc     = (data >> 6) & 0x3
        stream = (data >> 8) & 0x1f
        dt_name = CSI2_DT.get(dt, f"0x{dt:02x}")
        diag.append(
            f"[WARN] CHANSEL_NOMATCH — stream={stream} VC={vc} DT={dt_name}(0x{dt:02x})\n"
            f"    → VI receives CSI-2 packets for which no capture channel is open.\n"
            f"    This does NOT prevent the main image capture from working.\n"
            f"    Likely causes:\n"
            f"      1. Camera sends embedded/metadata lines (DT=0x12) or extra VC\n"
            f"         not configured in the device tree → harmless if image is correct\n"
            f"      2. Camera sends line-end short packets (DT=0x03) which VI ignores\n"
            f"      3. Wrong virtual channel in DT (vc-id mismatch between camera and DT)\n"
            f"    If the image looks correct, this warning can be ignored."
        )

if has_frame_trunc:
    diag.append(
        "[!] ATOMP_FRAME_TRUNCATED — frame capture ended before all lines received\n"
        "    → VI stopped writing before the full frame height was captured.\n"
        "    Likely causes:\n"
        "      1. active_h in DT > actual lines sent by camera\n"
        "      2. FE (frame end) packet received before all line data"
    )

if not diag:
    if not any([corr_total, uncorr_total, all_nvcsi_errors, vinotify_total]):
        diag.append("  OK — no errors detected.")
    else:
        diag.append("  Errors detected — see error summary above.")

for d in diag:
    print()
    print(d)

sep()
