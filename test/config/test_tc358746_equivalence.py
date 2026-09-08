#!/usr/bin/env python3
"""C ↔ Python equivalence for the TC358746 settings calculation.

We ship two implementations of the same arithmetic: the driver's
`tc358746_calculation.c`, and the standalone `tc358746_configure.py` given to
customers who do not run our driver. They must agree exactly, or a customer
following our own instructions gets a link that does not come up.

This compiles the driver's C for the host -- it needs only DIV_ROUND_UP,
DIV_ROUND_CLOSEST and BIT, so a few lines of shim replace the kernel headers --
runs both over a matrix of inputs, and compares every field.

The C relies on 32-bit wrap-around in two places (the FIFO search, and
tclk_zerocnt at low link rates). The Python reproduces it with explicit masking.
Those cases are in the matrix on purpose: they are what a naive port gets wrong.

    python3 test/config/test_tc358746_equivalence.py [-v]

Exit status is 0 when every vector matches.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DRV = os.path.join(ROOT, "sources", "common", "source", "nvidia-oot",
                   "drivers", "media", "i2c")
PY = os.path.join(ROOT, "sources", "common", "Linux_for_Tegra", "rootfs",
                  "usr", "bin", "tc358746_configure.py")

sys.path.insert(0, os.path.dirname(PY))
import importlib.util
_spec = importlib.util.spec_from_file_location("tc358746_configure", PY)
tcpy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tcpy)


SHIM_TYPES = """
#ifndef __SHIM_TYPES_H
#define __SHIM_TYPES_H
#include <stdint.h>
#include <stdbool.h>
typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#endif
"""

SHIM_MODULE = """
#ifndef __SHIM_MODULE_H
#define __SHIM_MODULE_H
#include <linux/types.h>
#include <stdio.h>
#define BIT(n)            (1UL << (n))
#define GENMASK(h, l)     (((~0UL) << (l)) & (~0UL >> (31 - (h))))
#define ARRAY_SIZE(a)     (sizeof(a) / sizeof((a)[0]))
#define DIV_ROUND_UP(n, d)      (((n) + (d) - 1) / (d))
#define DIV_ROUND_CLOSEST(x, d) (((x) + ((d) / 2)) / (d))
#define U32_MAX           (0xffffffffU)
#define EINVAL            22
#endif
"""

SHIM_MBUS = """
#ifndef __SHIM_MBUS_H
#define __SHIM_MBUS_H
#define MEDIA_BUS_FMT_RGB888_1X24   0x100a
#define MEDIA_BUS_FMT_GBR888_1X24   0x1014
#define MEDIA_BUS_FMT_UYVY8_2X8     0x2006
#define MEDIA_BUS_FMT_UYVY8_1X16    0x200f
#define MEDIA_BUS_FMT_YUYV8_1X16    0x2011
#define MEDIA_BUS_FMT_UYVY10_2X10   0x2018
#define MEDIA_BUS_FMT_Y14_1X14      0x202d
#endif
"""

HARNESS = """
#include <stdio.h>
#include <stdlib.h>
#include "tc358746_calculation.h"

int main(int argc, char **argv)
{
   struct tc358746_input in;
   struct tc358746 out;

   if (argc != 9) return 2;
   in.mbus_fmt         = (int)strtoul(argv[1], NULL, 0);
   in.refclk           = (u32)strtoul(argv[2], NULL, 0);
   in.link_frequency   = (u64)strtoull(argv[3], NULL, 0);
   in.num_lanes        = atoi(argv[4]);
   in.discontinuous_clk= atoi(argv[5]) ? true : false;
   in.pclk             = (unsigned)strtoul(argv[6], NULL, 0);
   in.width            = (unsigned)strtoul(argv[7], NULL, 0);
   in.hblank           = (unsigned)strtoul(argv[8], NULL, 0);

   if (tc358746_calculate(&out, &in) < 0) {
      printf("ERROR\\n");
      return 0;
   }
   printf("pll_prd=%u pll_fbd=%u pllinclk_hz=%u "
          "speed_range=%u unit_clk_hz=%u unit_clk_mul=%u speed_per_lane=%u "
          "lane_num=%u is_continuous_clk=%u "
          "lineinitcnt=%u lptxtimecnt=%u twakeupcnt=%u tclk_preparecnt=%u "
          "tclk_zerocnt=%u tclk_trailcnt=%u tclk_postcnt=%u "
          "ths_preparecnt=%u ths_zerocnt=%u ths_trailcnt=%u "
          "csi_hs_lp_hs_ps=%u vb_fifo=%u bpp=%u pdformat=%u pdataf=%u ppp=%u\\n",
          out.pll.pll_prd, out.pll.pll_fbd, out.pll.pllinclk_hz,
          out.csi.speed_range, out.csi.unit_clk_hz, out.csi.unit_clk_mul,
          out.csi.speed_per_lane, out.csi.lane_num, out.csi.is_continuous_clk,
          out.csi.lineinitcnt, out.csi.lptxtimecnt, out.csi.twakeupcnt,
          out.csi.tclk_preparecnt, out.csi.tclk_zerocnt, out.csi.tclk_trailcnt,
          out.csi.tclk_postcnt, out.csi.ths_preparecnt, out.csi.ths_zerocnt,
          out.csi.ths_trailcnt, out.csi.csi_hs_lp_hs_ps, out.vb_fifo,
          out.format->bpp, out.format->pdformat, out.format->pdataf,
          out.format->ppp);
   return 0;
}
"""


def build_reference(tmp):
    """Compile the driver's own calculation for the host."""
    os.makedirs(os.path.join(tmp, "linux"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "uapi", "linux"), exist_ok=True)
    with open(os.path.join(tmp, "linux", "types.h"), "w") as f:
        f.write(SHIM_TYPES)
    with open(os.path.join(tmp, "linux", "module.h"), "w") as f:
        f.write(SHIM_MODULE)
    with open(os.path.join(tmp, "uapi", "linux", "media-bus-format.h"), "w") as f:
        f.write(SHIM_MBUS)
    with open(os.path.join(tmp, "harness.c"), "w") as f:
        f.write(HARNESS)

    exe = os.path.join(tmp, "ref")
    cmd = ["cc", "-O0", "-w", "-I", tmp, "-I", DRV,
           os.path.join(tmp, "harness.c"),
           os.path.join(DRV, "tc358746_calculation.c"), "-o", exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("Could not compile the reference C:\n" + r.stderr, file=sys.stderr)
        return None
    return exe


def run_reference(exe, v):
    r = subprocess.run([exe, str(v["code"]), str(v["refclk"]), str(v["link"]),
                        str(v["lanes"]), "1" if v["discont"] else "0",
                        str(v["pclk"]), str(v["width"]), str(v["hblank"])],
                       capture_output=True, text=True)
    out = r.stdout.strip()
    if out == "ERROR" or not out:
        return None
    return {k: int(val) for k, val in (tok.split("=") for tok in out.split())}


def run_python(v):
    try:
        s = tcpy.calculate(v["fmt"], v["refclk"], v["link"], v["lanes"],
                           v["discont"], v["pclk"], v["width"], v["hblank"])
    except tcpy.CalcError:
        return None
    return {
        "pll_prd": s.pll_prd, "pll_fbd": s.pll_fbd, "pllinclk_hz": s.pllinclk_hz,
        "speed_range": s.speed_range, "unit_clk_hz": s.unit_clk_hz,
        "unit_clk_mul": s.unit_clk_mul, "speed_per_lane": s.speed_per_lane,
        "lane_num": s.lane_num, "is_continuous_clk": int(s.is_continuous_clk),
        "lineinitcnt": s.lineinitcnt, "lptxtimecnt": s.lptxtimecnt,
        "twakeupcnt": s.twakeupcnt, "tclk_preparecnt": s.tclk_preparecnt,
        "tclk_zerocnt": s.tclk_zerocnt, "tclk_trailcnt": s.tclk_trailcnt,
        "tclk_postcnt": s.tclk_postcnt, "ths_preparecnt": s.ths_preparecnt,
        "ths_zerocnt": s.ths_zerocnt, "ths_trailcnt": s.ths_trailcnt,
        "csi_hs_lp_hs_ps": s.csi_hs_lp_hs_ps, "vb_fifo": s.vb_fifo,
        "bpp": s.format.bpp, "pdformat": s.format.pdformat,
        "pdataf": s.format.pdataf, "ppp": s.format.ppp,
    }


def vectors():
    """Real configurations first, then a sweep, then the edges."""
    out = []

    def add(fmt, refclk, link, lanes, discont, pclk, width, hblank, note=""):
        out.append({"fmt": fmt, "code": tcpy.FORMATS[fmt][0], "refclk": refclk,
                    "link": link, "lanes": lanes, "discont": discont,
                    "pclk": pclk, "width": width, "hblank": hblank, "note": note})

    # The two configurations we actually ship on Dione.
    add("RGB888_1X24", 24000000, 498000000, 2, False, 83000000, 1280, 44,
        "Dione 1280 RGB888")
    add("Y14_1X14", 24000000, 498000000, 2, False, 83000000, 1280, 44,
        "Dione 1280 RAW14")
    add("RGB888_1X24", 24000000, 120000000, 2, False, 20000000, 320, 20,
        "Dione 320 RGB888")
    add("Y14_1X14", 24000000, 120000000, 2, False, 20000000, 320, 20,
        "Dione 320 RAW14")
    # The exact configuration the driver picks on a Dione 640: it walks the DT
    # link-frequencies list <120000000 498000000> and takes the first that
    # converges, i.e. 120 MHz. ths_trailcnt underflows to 0xFFFFFFFF here --
    # kept as a vector on purpose, it is the case a naive port gets wrong.
    add("RGB888_1X24", 24000000, 120000000, 2, False, 20000000, 640, 54,
        "Dione 640 RGB888 (real)")
    add("Y14_1X14", 24000000, 120000000, 2, False, 20000000, 640, 54,
        "Dione 640 RAW14 (real)")
    add("RGB888_1X24", 24000000, 498000000, 2, False, 83000000, 1280, 54,
        "Dione 1280 RGB888 (real)")
    add("Y14_1X14", 24000000, 498000000, 2, False, 83000000, 1280, 54,
        "Dione 1280 RAW14 (real)")
    add("RGB888_1X24", 24000000, 297000000, 2, False, 49500000, 640, 30,
        "Dione 640 RGB888")
    add("RGB888_1X24", 24000000, 396000000, 2, False, 66000000, 1024, 36,
        "Dione 1024 RGB888")

    # Sweep: every format, both clock modes, several link rates and lane counts.
    #
    # pclk is derived from the link rate rather than fixed, otherwise almost
    # every combination is rejected for lack of CSI bandwidth and the sweep
    # only ever tests the rejection path. The bridge needs
    # link * 2 * lanes > pclk * bpp; aim at ~70% of that so the FIFO search has
    # room to converge.
    for fmt in sorted(tcpy.FORMATS):
        bpp = tcpy.FORMATS[fmt][2]
        for link in (62500000, 100000000, 250000000, 300000000, 498000000, 500000000):
            for lanes in (1, 2, 4):
                pclk = (link * 2 * lanes * 7) // (bpp * 10)
                if pclk < 1000000:
                    continue
                for discont in (False, True):
                    add(fmt, 24000000, link, lanes, discont,
                        pclk, 1280, 44, "sweep")

    # Reference clocks other than 24 MHz, to exercise the PRD search.
    for refclk in (6000000, 12000000, 25000000, 27000000, 40000000):
        for link in (150000000, 498000000):
            add("RGB888_1X24", refclk, link, 2, False,
                (link * 2 * 2 * 7) // (24 * 10), 1280, 44, "refclk sweep")

    # Geometries, including ones with no valid FIFO size.
    for width, hblank, pclk in ((320, 20, 20000000), (640, 30, 49500000),
                                (1024, 36, 66000000), (1920, 280, 148500000),
                                (1280, 4, 83000000), (1280, 4000, 83000000),
                                (1280, 44, 40000000), (640, 100, 25000000)):
        for fmt in ("RGB888_1X24", "Y14_1X14", "UYVY8_2X8"):
            for link in (250000000, 498000000):
                add(fmt, 24000000, link, 2, False, pclk, width, hblank,
                    "geometry")

    # Edges: rejected by both, and the low rates where the unsigned
    # subtractions in the timing code underflow.
    add("RGB888_1X24", 5000000, 498000000, 2, False, 83000000, 1280, 44, "refclk too low")
    add("RGB888_1X24", 48000000, 498000000, 2, False, 83000000, 1280, 44, "refclk too high")
    add("RGB888_1X24", 24000000, 30000000, 2, False, 83000000, 1280, 44, "link too low")
    add("RGB888_1X24", 24000000, 600000000, 2, False, 83000000, 1280, 44, "link too high")
    for link in (31250000, 40000000, 62500000, 70000000, 80000000):
        add("Y14_1X14", 24000000, link, 2, False, 20000000, 320, 20, "low-rate wrap")
    return out


def main():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    with tempfile.TemporaryDirectory(prefix="tc358746_eq_") as tmp:
        exe = build_reference(tmp)
        if exe is None:
            return 2

        vecs = vectors()
        bad = 0
        both_rejected = 0
        for v in vecs:
            ref = run_reference(exe, v)
            got = run_python(v)

            if ref is None and got is None:
                both_rejected += 1
                if verbose:
                    print("  both reject   %-13s link=%-9d lanes=%d  %s"
                          % (v["fmt"], v["link"], v["lanes"], v["note"]))
                continue
            if (ref is None) != (got is None):
                bad += 1
                print("  MISMATCH (one side rejects) %s link=%d lanes=%d discont=%d "
                      "%dx hblank=%d pclk=%d  [%s]\n    C=%s  Python=%s"
                      % (v["fmt"], v["link"], v["lanes"], v["discont"], v["width"],
                         v["hblank"], v["pclk"], v["note"],
                         "reject" if ref is None else "ok",
                         "reject" if got is None else "ok"))
                continue

            diffs = [(k, ref[k], got[k]) for k in ref if ref[k] != got.get(k)]
            if diffs:
                bad += 1
                print("  MISMATCH %s refclk=%d link=%d lanes=%d discont=%d %dx "
                      "hblank=%d pclk=%d  [%s]"
                      % (v["fmt"], v["refclk"], v["link"], v["lanes"], v["discont"],
                         v["width"], v["hblank"], v["pclk"], v["note"]))
                for k, c, p in diffs:
                    print("      %-18s C=%-12d Python=%d" % (k, c, p))
            elif verbose:
                print("  ok            %-13s refclk=%-9d link=%-9d lanes=%d  %s"
                      % (v["fmt"], v["refclk"], v["link"], v["lanes"], v["note"]))

        print()
        print("  %d vectors, %d identical, %d rejected by both, %d mismatched"
              % (len(vecs), len(vecs) - bad - both_rejected, both_rejected, bad))
        if bad:
            print("  FAILED — tc358746_configure.py has drifted from "
                  "tc358746_calculation.c")
            return 1
        print("  OK — the Python port matches the driver's C exactly")
        return 0


if __name__ == "__main__":
    sys.exit(main())
