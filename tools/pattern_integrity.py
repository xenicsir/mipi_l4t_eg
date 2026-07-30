#!/usr/bin/env python3
"""
pattern_integrity.py — measure CSI-2 link integrity from a camera test pattern.

Runs on the Jetson (capture) and anywhere with numpy (analyse).

Why this exists: with the NVCSI error masks in place (all 35.x, and the minimal
variant on 36.x/39.2) the kernel reports nothing -- no corr_err, no
V4L2_BUF_FLAG_ERROR, no RTCPU trace. A static test pattern is then the only way
left to tell whether the pixels actually arrived intact. See
ilumos_pattern_bit_corruption_35.6.0.md in the shared memory.

Method: the reference frame is the per-pixel MEDIAN over all captured frames.
That is robust as long as corruption stays well under 50% per pixel, and it
needs no knowledge of what the generator is supposed to emit -- which we do not
have. Deviations from that reference are the transmission errors.

Usage
  # on the board
  sudo ./pattern_integrity.py capture --frames 60 --out run1.raw
  ./pattern_integrity.py analyse run1.raw --report run1.txt

  # compare two series (any number)
  ./pattern_integrity.py compare run1.txt run2.txt
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

try:
    import numpy as np
except ImportError:
    sys.exit("numpy required: sudo apt install python3-numpy")

BYTES_PER_PX = 2


# ---------------------------------------------------------------- environment

def _run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return ""


def probe_format(device):
    """Read the device's currently active geometry and fourcc."""
    out = _run(f"v4l2-ctl -d {device} --get-fmt-video")
    m = re.search(r"Width/Height\s*:\s*(\d+)/(\d+)", out)
    p = re.search(r"Pixel Format\s*:\s*'([^']+)'", out)
    if not (m and p):
        sys.exit(f"could not read current format of {device}:\n{out}")
    return int(m.group(1)), int(m.group(2)), p.group(1)


def collect_metadata(device):
    """Everything needed to make a series comparable to another one."""
    md = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "hostname": _run("hostname"),
        "l4t": _run("head -1 /etc/nv_tegra_release"),
        "kernel": _run("uname -r"),
        "dt_compatible": _run("tr -d '\\0' < /proc/device-tree/compatible"),
        "device": device,
    }
    w, h, fourcc = probe_format(device)
    md.update(width=w, height=h, fourcc=fourcc)

    # DT parameters of the sensor nodes: num_lanes drives the lane-mapping
    # discussion, pix_clk_hz the CSI rate, discontinuous_clk the PHY mode.
    #
    # Two traps here, both of which silently produced EMPTY metadata before:
    #  * the node depth differs by L4T version -- 35.x has
    #    cam_i2cmux/i2c@N/<sensor>@AA, 36.x inserts a bus@0/ level -- so any
    #    fixed-depth glob returns nothing on one of the two;
    #  * /proc/device-tree is a SYMLINK to /sys/firmware/devicetree/base, and
    #    `find` does not follow symlinks without -L, so a find rooted there
    #    returns nothing at all on every version.
    # Hence: find -L, matched on the property rather than on the path shape.
    # Which sensor is actually bound comes from sysfs: each probed i2c device
    # has an of_node symlink pointing at its DT node.
    bound = set()
    for link in _run("ls -d /sys/bus/i2c/devices/*/of_node 2>/dev/null").split():
        tgt = os.path.realpath(link)
        if tgt:
            bound.add(tgt)
    nodes = _run("find -L /proc/device-tree -maxdepth 8 -name num_lanes "
                 "-path '*/mode0/*' 2>/dev/null").split()
    for prop in nodes:
        mode_dir = os.path.dirname(prop)
        node = os.path.dirname(mode_dir)
        name = os.path.basename(node)
        status = os.path.join(node, "status")
        if os.path.isfile(status) and "disabled" in _run(f"tr -d '\\0' < {status}"):
            continue
        entry = md.setdefault("dt", {}).setdefault(name, {})
        for key in ("num_lanes", "pix_clk_hz", "discontinuous_clk"):
            path = os.path.join(mode_dir, key)
            if os.path.isfile(path):
                entry[key] = _run(f"tr -d '\\0' < {path}")
        if os.path.realpath(node) in bound:
            entry["bound"] = True
    if "dt" not in md:
        # Be explicit rather than silently dropping the key -- a missing key
        # reads as "not collected" and that is how the 36.x captures lost it.
        md["dt"] = "no sensor node with mode0/num_lanes found under /proc/device-tree"

    md["camera_fw"] = _run("sudo -n /usr/bin/eg_dt_camera_config_get.sh 2>/dev/null "
                           "| grep -m1 'FW version'") or "(unavailable)"
    return md


# ------------------------------------------------------------------- capture

def cmd_capture(a):
    w, h, fourcc = probe_format(a.device)
    frame_bytes = w * h * BYTES_PER_PX
    print(f"{a.device}: {w}x{h} '{fourcc}' -> {frame_bytes} B/frame, {a.frames} frames")

    md = collect_metadata(a.device)
    md["frames"] = a.frames

    # timeout on the *capture* side: a timeout wrapped around ssh kills the
    # client without signalling v4l2-ctl, which then keeps holding the device.
    budget = max(30, a.frames // 2 + 30)
    cmd = (f"timeout -k 3 {budget} v4l2-ctl -d {a.device} "
           f"--set-fmt-video=width={w},height={h},pixelformat='{fourcc}' "
           f"--stream-mmap --stream-count={a.frames} --stream-to={a.out}")
    rc = subprocess.run(cmd, shell=True, capture_output=True).returncode
    got = os.path.getsize(a.out) if os.path.exists(a.out) else 0
    print(f"rc={rc}  captured {got} B (expected {frame_bytes * a.frames})")
    if got != frame_bytes * a.frames:
        sys.exit("short capture -- refusing to write metadata")

    with open(a.out + ".meta.json", "w") as f:
        json.dump(md, f, indent=2)
    print(f"metadata -> {a.out}.meta.json")


# ------------------------------------------------------------------ analysis

def _median_ref(frames, h, w, chunk_rows=128):
    """Per-pixel median, computed in row chunks to bound peak memory."""
    ref = np.empty((h, w), dtype=np.uint16)
    for r0 in range(0, h, chunk_rows):
        r1 = min(h, r0 + chunk_rows)
        ref[r0:r1] = np.median(frames[:, r0:r1, :].astype(np.float32), axis=0).astype(np.uint16)
    return ref


def _ramp_compliance(ref, step):
    """Compare a frame against the ramp its generator is supposed to emit.

    Why this is NOT redundant with the median-reference check: the median
    reference is built FROM the capture, so any corruption that is identical in
    every frame is baked into it and reports as zero error. Two of the three
    iLumos defects are exactly like that. Without an expected-value model, a
    perfectly stable stream of wrong pixels reads as "CLEAN".

    The model is per LINE, not per frame: expected start of a line is the most
    common value of (v - step*col), which survives up to ~50% corruption inside
    the line. A whole-frame model would be defeated by a single lost increment,
    because everything after it is shifted -- and that lost increment is itself
    one of the defects we want to see.

    Returns (expected_frame, per_line_start, per_line_bad).
    """
    h, w = ref.shape
    col = np.arange(w, dtype=np.int64)
    exp = np.empty_like(ref)
    starts = np.empty(h, dtype=np.int64)
    for r in range(h):
        cand = (ref[r].astype(np.int64) - step * col) % 65536
        starts[r] = np.bincount(cand, minlength=65536).argmax()
        exp[r] = ((starts[r] + step * col) % 65536).astype(np.uint16)
    return exp, starts, (ref != exp).sum(axis=1)


def _trailing_ones(v):
    """Length of the run of 1-bits at the bottom of each value (first bits on
    the wire: MIPI serialises LSB-first)."""
    x = v.astype(np.int64)
    run = np.zeros(x.shape, dtype=np.int64)
    active = np.ones(x.shape, dtype=bool)
    for k in range(16):
        bit = ((x >> k) & 1) == 1
        run += bit & active
        active &= bit
    return run


def cmd_analyse(a):
    meta = {}
    if os.path.exists(a.raw + ".meta.json"):
        meta = json.load(open(a.raw + ".meta.json"))
    w = a.width or meta.get("width")
    h = a.height or meta.get("height")
    if not (w and h):
        sys.exit("geometry unknown: pass --width/--height or provide a .meta.json")
    endian = ">u2" if a.big_endian or "BE" in meta.get("fourcc", "") else "<u2"

    total = os.path.getsize(a.raw)
    n = total // (w * h * BYTES_PER_PX)
    if n < 3:
        sys.exit(f"need >= 3 frames for a median reference, got {n}")
    frames = np.fromfile(a.raw, dtype=endian, count=n * h * w).reshape(n, h, w)

    out = open(a.report, "w") if a.report else sys.stdout
    def p(s=""):
        print(s, file=out)

    p("=" * 78)
    p(f"pattern integrity report — {os.path.basename(a.raw)}")
    p("=" * 78)
    for k in ("timestamp", "hostname", "l4t", "kernel", "dt_compatible",
              "device", "fourcc", "camera_fw"):
        if meta.get(k):
            p(f"{k:16s}: {meta[k]}")
    for node, kv in (meta.get("dt") or {}).items():
        p(f"{'dt':16s}: {node}  {kv}")
    p(f"{'geometry':16s}: {w}x{h}  {endian}  {n} frames")
    p()

    ref = _median_ref(frames, h, w)
    bad = frames != ref
    per_frame = bad.sum(axis=(1, 2))
    nbad = int(per_frame.sum())

    p("-- 1. do frames differ from each other? " + "-" * 36)
    uniq = len({frames[i].tobytes() for i in range(n)})
    p(f"distinct frame contents      : {uniq} / {n}")
    p(f"pixels != median reference   : {nbad} / {frames.size}  ({100*nbad/frames.size:.4f} %)")
    p(f"per frame                    : min={per_frame.min()} max={per_frame.max()} "
      f"mean={per_frame.mean():.0f} std={per_frame.std():.0f}")

    # Always describe the pattern itself: it is what makes two cameras (or two
    # firmware revisions) comparable, and a clean capture still needs it -- a
    # zero error count is only meaningful if the pattern actually exercises the
    # bits. Printed before the early return for that reason.
    p()
    p("-- 2. reference pattern structure " + "-" * 42)
    p(f"value range                  : min={ref.min()} max={ref.max()} mean={ref.mean():.1f}")
    p(f"distinct values              : {np.unique(ref).size}")
    p("row 0, cols 0..15            : " + " ".join(f"{v:04X}" for v in ref[0, :16]))
    p("row 0, cols 16..31           : " + " ".join(f"{v:04X}" for v in ref[0, 16:32]))
    p("row 1, cols 0..15            : " + " ".join(f"{v:04X}" for v in ref[1, :16]))
    p("col 0, rows 0..7             : " + " ".join(f"{v:04X}" for v in ref[:8, 0]))
    dx = np.diff(ref[0].astype(np.int32))
    vx, cx = np.unique(dx, return_counts=True)
    p("row 0 horizontal deltas      : " +
      ", ".join(f"{vx[i]}({100*cx[i]/len(dx):.0f}%)" for i in np.argsort(-cx)[:4]))
    dy = np.diff(ref[:, 0].astype(np.int32))
    vy, cy = np.unique(dy, return_counts=True)
    p("col 0 vertical deltas        : " +
      ", ".join(f"{vy[i]}({100*cy[i]/len(dy):.0f}%)" for i in np.argsort(-cy)[:4]))
    p("bit exercise (fraction of values with the bit set), by column parity:")
    for lbl, sub in (("even cols", ref[:, 0::2]), ("odd cols ", ref[:, 1::2])):
        p(f"   {lbl} : " + " ".join(f"b{b}:{100*((sub>>b&1).mean()):4.0f}%" for b in range(16)))
    p("trailing 1-bit run (first bits on the wire, MIPI is LSB-first):")
    for lbl, sub in (("even cols", ref[:, 0::2]), ("odd cols ", ref[:, 1::2])):
        t = _trailing_ones(sub)
        v, c = np.unique(t, return_counts=True)
        p(f"   {lbl} : " + "  ".join(f"len{a_}:{100*b/t.size:.1f}%"
                                     for a_, b in zip(v[:5], c[:5])))
    p("A linear ramp sets bit0 on half its values. A parity that never does has")
    p("lost its low bits before we ever saw them (model: read == exp & (exp+1)).")

    # Compliance against the EXPECTED pattern. Must run before the nbad==0
    # early return: a defect that is identical in every frame gives nbad==0.
    comp = None
    if a.expect == "ramp":
        exp, starts, line_bad = _ramp_compliance(ref, a.expect_step)
        nc = int(line_bad.sum())
        d = np.diff(starts) % 65536
        dv, dc = np.unique(d, return_counts=True)
        dup = int((np.diff(ref.astype(np.int64), axis=1) == 0).sum()) if a.expect_step else 0
        comp = dict(n=nc, rate=100 * nc / ref.size, dup=dup,
                    step_mode=int(dv[np.argmax(dc)]), expected_step=a.expect_step * w)
        p()
        p("-- 2bis. COMPLIANCE against the expected ramp " + "-" * 30)
        p(f"model                        : value = line_start + {a.expect_step} x column")
        p(f"                               (line start inferred per line, robust to")
        p(f"                                up to ~50%% corruption inside the line)")
        p(f"pixels != expected           : {nc} / {ref.size}  ({comp['rate']:.4f} %)")
        p(f"lines not fully compliant    : {int((line_bad>0).sum())} / {h}")
        p(f"  per line                   : min={line_bad.min()} max={line_bad.max()} "
          f"mean={line_bad.mean():.1f}")
        ep, od = int((ref[:, 0::2] != exp[:, 0::2]).sum()), \
                 int((ref[:, 1::2] != exp[:, 1::2]).sum())
        p(f"  even / odd columns         : {ep} / {od}")
        p(f"repeated pixels (step lost)  : {dup}   "
          f"({dup/h:.2f} per line — a ramp must never repeat)")
        p(f"line-to-line start step      : expected {comp['expected_step']}, "
          f"most common {comp['step_mode']}")
        p("  distribution               : " +
          ", ".join(f"{dv[i]}({100*dc[i]/len(d):.0f}%)" for i in np.argsort(-dc)[:4]))
        p("NOTE: this section is the only one that can see corruption which is")
        p("identical in every frame. The median reference cannot — it contains it.")

    if nbad == 0:
        p()
        p("=" * 78)
        p("SUMMARY")
        p(f"  frames                    {n}")
        p(f"  distinct frames           {uniq}/{n}")
        p(f"  error rate                0.0000 %")
        p(f"  errors even/odd columns    0 / 0")
        p(f"  bits affected             []")
        p(f"  isolated pixels only      n/a")
        if comp is None:
            p("  VERDICT                   frames stable — pattern NOT checked")
            p("                            (pass --expect ramp to check compliance)")
        elif comp["n"] == 0 and comp["step_mode"] == comp["expected_step"]:
            p(f"  pattern compliance        0 mismatch, step {comp['step_mode']} OK")
            p("  VERDICT                   CLEAN — stable AND matches the pattern")
        else:
            p(f"  pattern compliance        {comp['n']} mismatches "
              f"({comp['rate']:.4f} %), {comp['dup']} repeated px")
            p("  VERDICT                   NOT CLEAN — frames are stable but the")
            p("                            pattern is wrong (deterministic defect)")
        p("=" * 78)
        if a.report:
            out.close(); print(f"report -> {a.report}")
        return

    p()
    p("-- 3. drift across the capture " + "-" * 45)
    for i in range(0, n, 10):
        p("   f%03d+ : %s" % (i, " ".join(f"{v:6d}" for v in per_frame[i:i+10])))

    p()
    p("-- 4. column parity " + "-" * 56)
    even = int(bad[:, :, 0::2].sum()); odd = int(bad[:, :, 1::2].sum())
    p(f"errors on EVEN columns       : {even}")
    p(f"errors on ODD  columns       : {odd}")
    p("CONTROL — are the affected bits exercised on both parities?")

    p()
    p("-- 5. which bits flip " + "-" * 54)
    r = ref.ravel()
    xs = []
    for i in range(n):
        f = frames[i].ravel(); m = f != r
        xs.append(r[m].astype(np.int64) ^ f[m].astype(np.int64))
    xor = np.concatenate(xs)
    vals, cnts = np.unique(xor, return_counts=True)
    for i in np.argsort(-cnts)[:10]:
        bits = [b for b in range(16) if vals[i] >> b & 1]
        p(f"   XOR=0x{vals[i]:04X}  bits={str(bits):12s} n={cnts[i]:8d} "
          f"({100*cnts[i]/len(xor):6.2f} %)")
    affected = sorted({b for v in vals for b in range(16) if v >> b & 1})
    p(f"bits ever affected           : {affected}")
    for b in affected:
        e = ref[:, 0::2]; o = ref[:, 1::2]
        p(f"   bit {b:2d} set in reference : even cols {100*((e>>b&1).mean()):5.1f} %"
          f"   odd cols {100*((o>>b&1).mean()):5.1f} %")

    ones_lost = ones_gained = 0
    for i in range(n):
        f = frames[i].ravel(); m = f != r
        d = r[m].astype(np.int64) ^ f[m].astype(np.int64)
        for b in affected:
            fl = (d >> b) & 1
            got = (f[m].astype(np.int64) >> b) & 1
            ones_gained += int(((fl == 1) & (got == 1)).sum())
            ones_lost   += int(((fl == 1) & (got == 0)).sum())
    p(f"bits 1->0 (pulses lost)      : {ones_lost}")
    p(f"bits 0->1 (spurious pulses)  : {ones_gained}")

    p()
    p("-- 6. clustering (runs of consecutive bad pixels, frame 0) " + "-" * 17)
    idx = np.where(bad[0].ravel())[0]
    if len(idx):
        brk = np.where(np.diff(idx) != 1)[0]
        runs = np.diff(np.concatenate(([-1], brk, [len(idx) - 1]))).astype(int)
        v, c = np.unique(runs, return_counts=True)
        p(f"runs: n={len(runs)} min={runs.min()} max={runs.max()} mean={runs.mean():.2f}")
        p("length histogram            : " + str(dict(zip(v[:8].tolist(), c[:8].tolist()))))
        p("(max=1 => isolated pixels: no dropped line, no shift)")

    p()
    p("-- 7. value dependence (low byte of the reference value) " + "-" * 19)
    ever = bad.any(0)
    lo = (ref & 0xFF).ravel()
    tot = np.bincount(lo, minlength=256)
    hit = np.bincount(lo, weights=ever.ravel().astype(float), minlength=256)
    rows = [(v, int(tot[v]), int(hit[v])) for v in range(256) if tot[v]]
    rows.sort(key=lambda t: -(t[2] / t[1]))
    p(f"{'low byte':>10} {'positions':>10} {'ever bad':>9} {'%':>7}   bits")
    for v, t, b in rows[:10]:
        p(f"      0x{v:02X} {t:10d} {b:9d} {100*b/t:7.2f}   "
          f"{[i for i in range(8) if v >> i & 1]}")
    nz = sum(1 for _, t, b in rows if b)
    p(f"low-byte values ever affected: {nz} / {len(rows)} present")

    p()
    p("-- 8. are the same positions hit repeatedly? " + "-" * 31)
    cnt = bad.sum(0)[ever]
    p(f"positions bad at least once  : {int(ever.sum())} ({100*ever.mean():.3f} % of pixels)")
    p(f"positions bad in ALL frames  : {int(bad.all(0).sum())}")
    p(f"frames bad per affected px   : mean={cnt.mean():.2f} max={cnt.max()} of {n}")
    p("(mean >> 1 => value/position dependent, not random hits)")

    p()
    p("-- 9. spatial spread " + "-" * 55)
    pc = ever.sum(0); pr = ever.sum(1)
    p(f"columns touched              : {int((pc>0).sum())}/{w}  "
      f"(min={pc.min()} max={pc.max()} mean={pc.mean():.1f})")
    p(f"rows touched                 : {int((pr>0).sum())}/{h}  "
      f"(min={pr.min()} max={pr.max()} mean={pr.mean():.1f})")

    p()

    p()
    p("=" * 78)
    p("SUMMARY")
    p(f"  frames                    {n}")
    p(f"  distinct frames           {uniq}/{n}")
    p(f"  error rate                {100*nbad/frames.size:.4f} %")
    p(f"  errors even/odd columns    {even} / {odd}")
    p(f"  bits affected             {affected}")
    p(f"  isolated pixels only      {'yes' if len(idx) and runs.max()==1 else 'no'}")
    if comp is None:
        p("  pattern compliance        NOT CHECKED (pass --expect ramp)")
    else:
        p(f"  pattern compliance        {comp['n']} mismatches "
          f"({comp['rate']:.4f} %), {comp['dup']} repeated px,")
        p(f"                            line step {comp['step_mode']} "
          f"(expected {comp['expected_step']})")
    p("=" * 78)

    if a.report:
        out.close()
        print(f"report -> {a.report}")


# ------------------------------------------------------------------- compare

def cmd_compare(a):
    def grab(path):
        d = {}
        for line in open(path):
            m = re.match(r"\s{2}(\S.*?)\s{2,}(\S.*)$", line)
            if m:
                d[m.group(1).strip()] = m.group(2).strip()
            for k in ("l4t", "camera_fw", "timestamp", "geometry"):
                if line.startswith(k):
                    d[k] = line.split(":", 1)[1].strip()
        return d
    series = [(os.path.basename(p), grab(p)) for p in a.reports]
    keys = ["timestamp", "l4t", "geometry", "camera_fw", "frames", "distinct frames",
            "error rate", "errors even/odd columns", "bits affected",
            "isolated pixels only"]
    wid = max(len(n) for n, _ in series) + 2
    print(f"{'':30s}" + "".join(n.ljust(wid) for n, _ in series))
    for k in keys:
        print(f"{k:30s}" + "".join(str(d.get(k, '-')).ljust(wid) for _, d in series))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="grab N raw frames + environment metadata")
    c.add_argument("--device", default="/dev/video0")
    c.add_argument("--frames", type=int, default=60)
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_capture)

    an = sub.add_parser("analyse", help="analyse a raw capture")
    an.add_argument("raw")
    an.add_argument("--report", default=None, help="write to file instead of stdout")
    an.add_argument("--width", type=int, default=None)
    an.add_argument("--height", type=int, default=None)
    an.add_argument("--big-endian", action="store_true")
    an.add_argument("--expect", choices=["ramp"], default=None,
                    help="check the frame against the pattern the generator is "
                         "supposed to emit. Without this, corruption that is "
                         "identical in every frame is invisible (it ends up in "
                         "the median reference) and the report says CLEAN.")
    an.add_argument("--expect-step", type=int, default=1, metavar="N",
                    help="ramp increment per pixel (default 1)")
    an.set_defaults(func=cmd_analyse)

    cp = sub.add_parser("compare", help="side-by-side summary of several reports")
    cp.add_argument("reports", nargs="+")
    cp.set_defaults(func=cmd_compare)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
