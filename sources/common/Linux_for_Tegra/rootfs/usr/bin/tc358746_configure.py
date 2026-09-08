#!/usr/bin/env python3
"""Configure a TC358746 parallel-to-CSI-2 bridge over I2C, without a driver.

This is a standalone port of what our Linux kernel driver does, for hosts that
do not run it -- another SoC, another OS, or a bring-up bench. It takes the same
inputs as the driver's tc358746_calculate(), derives the PLL, the D-PHY timings
and the FIFO size from them, and writes the resulting register sequence.

It needs nothing but Python 3 and a Linux i2c-dev node. No compiler, no kernel
headers, no libraries.

  tc358746_configure.py --bus 10 --mbus-format RGB888_1X24 \\
      --refclk 24000000 --link-frequency 498000000 --num-lanes 2 \\
      --pclk 83000000 --width 1280 --hblank 44

Add --dry-run to print the computed settings and the register writes without
touching the bus -- useful to compare against a working trace before committing
to it.

⚠️ This programs the BRIDGE only. Whatever feeds its parallel input -- a sensor,
an FPGA -- must be configured separately and must already produce the format
declared with --mbus-format, at --pclk, with --width/--hblank. The bridge does
not check, and a mismatch shows up as a silent absence of frames.

Equivalence with the C is not assumed: test/config/test_tc358746_equivalence.py
compiles the driver's own tc358746_calculation.c and compares its results with
this file's over a matrix of inputs. Run it after changing either side.
"""

import argparse
import fcntl
import os
import struct
import sys

# ---------------------------------------------------------------------------
# 32-bit integer semantics
#
# The C works in u32/int throughout, and it RELIES on wrap-around in places:
# tc358746_adjust_fifo_size() computes c_lp_active_ps as an unsigned difference
# that goes negative-as-huge and is then read back through a signed int, and
# tclk_zerocnt starts from an unsigned subtraction that can underflow. Python
# integers are unbounded, so every intermediate has to be masked to reproduce
# the C exactly. Do not "simplify" these away.
# ---------------------------------------------------------------------------

U32 = 0xFFFFFFFF


def u32(v):
    """Value as the C would hold it in an unsigned int."""
    return v & U32


def s32(v):
    """Reinterpret the low 32 bits as a signed int, as an assignment to int does."""
    v &= U32
    return v - (1 << 32) if v & 0x80000000 else v


def u16(v):
    return v & 0xFFFF


def div_round_up(n, d):
    """Kernel DIV_ROUND_UP on unsigned operands."""
    return u32((u32(n) + d - 1) // d)


def div_round_closest(n, d):
    """Kernel DIV_ROUND_CLOSEST on unsigned operands."""
    return u32((u32(n) + d // 2) // d)


# ---------------------------------------------------------------------------
# Formats -- mirrors tc358746_formats[] in tc358746_calculation.c
# ---------------------------------------------------------------------------

DATAFMT_PDFMT_RAW8 = 0
DATAFMT_PDFMT_RAW10 = 1
DATAFMT_PDFMT_RAW12 = 2
DATAFMT_PDFMT_RGB888 = 3
DATAFMT_PDFMT_YCBCRFMT_422_8_BIT = 6
DATAFMT_PDFMT_RAW14 = 8
DATAFMT_PDFMT_YCBCRFMT_422_10_BIT = 9
DATAFMT_PDFMT_YCBCRFMT_444 = 10

CONFCTL_PDATAF_MODE0 = 0
CONFCTL_PDATAF_MODE1 = 1
CONFCTL_PDATAF_MODE2 = 2

# name -> (mbus code, bus_width, bpp, pdformat, pdataf, ppp, csitx_only)
FORMATS = {
    "UYVY8_2X8":    (0x2006,  8, 16, DATAFMT_PDFMT_YCBCRFMT_422_8_BIT,  CONFCTL_PDATAF_MODE0, 2, False),
    "UYVY8_1X16":   (0x200F, 16, 16, DATAFMT_PDFMT_YCBCRFMT_422_8_BIT,  CONFCTL_PDATAF_MODE1, 1, False),
    "YUYV8_1X16":   (0x2011, 16, 16, DATAFMT_PDFMT_YCBCRFMT_422_8_BIT,  CONFCTL_PDATAF_MODE2, 1, False),
    "UYVY10_2X10":  (0x2018, 10, 20, DATAFMT_PDFMT_YCBCRFMT_422_10_BIT, CONFCTL_PDATAF_MODE0, 2, False),
    "GBR888_1X24":  (0x1014, 24, 24, DATAFMT_PDFMT_YCBCRFMT_444,        CONFCTL_PDATAF_MODE0, 2, True),
    "RGB888_1X24":  (0x100A, 24, 24, DATAFMT_PDFMT_RGB888,              CONFCTL_PDATAF_MODE0, 1, False),
    # RAW14: datasheet Table 4.3 gives the parallel pin usage as {10'b0,
    # P[13:0]}, the 14 bits right-aligned on PD[13:0].
    "Y14_1X14":     (0x202D, 14, 14, DATAFMT_PDFMT_RAW14,               CONFCTL_PDATAF_MODE0, 1, False),
}

FMT_FIELDS = ("code", "bus_width", "bpp", "pdformat", "pdataf", "ppp", "csitx_only")


class Fmt:
    def __init__(self, name):
        vals = FORMATS[name]
        self.name = name
        for k, v in zip(FMT_FIELDS, vals):
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# Calculation -- port of tc358746_calculation.c
# ---------------------------------------------------------------------------

TC358746_MAX_FIFO_SIZE = 512
TC358746_LINEINIT_MIN_US = 110
TC358746_TWAKEUP_MIN_US = 1200
TC358746_LPTXTIME_MIN_NS = 55
TC358746_TCLKZERO_MIN_NS = 305
TC358746_TCLKTRAIL_MIN_NS = 65
TC358746_TCLKPOST_MIN_NS = 65
TC358746_THSZERO_MIN_NS = 150
TC358746_THSTRAIL_MIN_NS = 65
TC358746_THSPREPARE_MIN_NS = 45


class Settings:
    """Mirrors struct tc358746: format + pll + csi + vb_fifo."""

    def __init__(self):
        self.format = None
        self.pll_prd = 0
        self.pll_fbd = 0
        self.pllinclk_hz = 0
        self.speed_range = 0
        self.unit_clk_hz = 0
        self.unit_clk_mul = 0
        self.speed_per_lane = 0
        self.lane_num = 0
        self.is_continuous_clk = True
        self.lineinitcnt = 0
        self.lptxtimecnt = 0
        self.twakeupcnt = 0
        self.tclk_preparecnt = 0
        self.tclk_zerocnt = 0
        self.tclk_trailcnt = 0
        self.tclk_postcnt = 0
        self.ths_preparecnt = 0
        self.ths_zerocnt = 0
        self.ths_trailcnt = 0
        self.csi_hs_lp_hs_ps = 0
        self.vb_fifo = 0


class CalcError(Exception):
    pass


def _setup_pll(s, refclk, link_frequency):
    """tc358746_setup_pll(): pick the PRD giving the smallest VCO error."""
    if refclk < 6000000 or refclk > 40000000:
        raise CalcError("refclk must be between 6 MHz and 40 MHz")

    target_vco = u32(2 * link_frequency)
    best_prd, best_error, best_pllinclk = 1, U32, 0

    for trial_prd in range(1, 17):
        trial_pllinclk = refclk // trial_prd
        if trial_pllinclk < 4000000 or trial_pllinclk > 40000000:
            continue
        trial_fbd = div_round_closest(target_vco, trial_pllinclk)
        trial_vco = u32(trial_pllinclk * trial_fbd)
        error = trial_vco - target_vco if trial_vco > target_vco else target_vco - trial_vco
        if error < best_error or (error == best_error and trial_pllinclk > best_pllinclk):
            best_error, best_prd, best_pllinclk = error, trial_prd, trial_pllinclk
            if error == 0:
                break

    s.pll_prd = best_prd
    s.pllinclk_hz = refclk // best_prd
    s._pll_error = best_error
    s._target_vco = target_vco


def _set_lane_settings(s, link_frequency, num_lanes, discontinuous_clk):
    """tc358746_set_lane_settings()."""
    bps_pr_lane = u32(2 * link_frequency)
    if bps_pr_lane < 62500000 or bps_pr_lane > 1000000000:
        raise CalcError("unsupported bps per lane: %u bps "
                        "(link frequency must be 31.25 MHz .. 500 MHz)" % bps_pr_lane)

    if bps_pr_lane > 500000000:
        s.speed_range = 0
    elif bps_pr_lane > 250000000:
        s.speed_range = 1
    elif bps_pr_lane > 125000000:
        s.speed_range = 2
    else:
        s.speed_range = 3

    s.unit_clk_hz = s.pllinclk_hz >> s.speed_range
    s.unit_clk_mul = bps_pr_lane // s.unit_clk_hz
    s.speed_per_lane = bps_pr_lane
    s.lane_num = num_lanes
    s.is_continuous_clk = not discontinuous_clk


def _setup_pll_post(s):
    """tc358746_setup_pll_post(): FBD is the multiplier M, u16."""
    s.pll_fbd = u16(u32(div_round_closest(s.speed_per_lane, s.pllinclk_hz)) << s.speed_range)


def _calculate_csi_txtimings(s):
    """tc358746_calculate_csi_txtimings()."""
    spl = s.speed_per_lane
    hsclk = spl >> 3
    hfclk = hsclk >> 1

    if hsclk > 125000000:
        raise CalcError("unsupported HS byte clock %d, must be <= 125 MHz" % hsclk)

    hfclk_p_ns = div_round_closest(1000000000, hfclk)
    hsclk_p_ps = 1000000000 // (hsclk // 1000)
    spl_p_ps = 1000000000 // (spl // 1000)

    s.lineinitcnt = div_round_up(TC358746_LINEINIT_MIN_US * 1000, hfclk_p_ns)

    s.lptxtimecnt = s.tclk_preparecnt = u32(
        div_round_up(TC358746_LPTXTIME_MIN_NS * 1000, hsclk_p_ps) - 1)

    # Unsigned subtraction: underflows on purpose at very low link rates, and
    # the C keeps the wrapped value. Reproduced with u32().
    tmp = u32(TC358746_TCLKZERO_MIN_NS * 1000 - 3 * spl_p_ps)
    tmp = div_round_up(tmp, hsclk_p_ps)
    s.tclk_zerocnt = u32(tmp - 2)

    tmp = u32(TC358746_THSPREPARE_MIN_NS * 1000 + 4 * spl_p_ps)
    tmp = div_round_up(tmp, hsclk_p_ps)
    s.ths_preparecnt = u32(tmp - 1)

    tmp = u32(TC358746_THSZERO_MIN_NS * 1000 - spl_p_ps)
    tmp = div_round_up(tmp, hsclk_p_ps)
    s.ths_zerocnt = 0 if tmp < 11 else u32(tmp - 11)

    tmp = hsclk_p_ps // 1000
    s.twakeupcnt = u32(div_round_up(TC358746_TWAKEUP_MIN_US * 1000,
                                    tmp * (s.lptxtimecnt + 1)) - 1)

    tmp = u32(TC358746_THSTRAIL_MIN_NS * 1000 + 15 * spl_p_ps)
    tmp = div_round_up(tmp, hsclk_p_ps)
    s.ths_trailcnt = u32(tmp - 5)

    tmp = u32(TC358746_TCLKTRAIL_MIN_NS * 1000 + 3 * spl_p_ps)
    tmp = div_round_up(tmp, hsclk_p_ps)
    s.tclk_trailcnt = 0 if tmp < 5 else u32(tmp - 5)

    tmp = u32(TC358746_TCLKPOST_MIN_NS * 1000 + 49 * spl_p_ps)
    tmp = div_round_up(tmp, hsclk_p_ps)
    s.tclk_postcnt = u32(tmp - 3)

    lptxtime_ps = u32((s.lptxtimecnt + 1) * hsclk_p_ps)
    tclk_post_ps = u32((4 + s.tclk_postcnt) * hsclk_p_ps + 3 * spl_p_ps)
    tclk_trail_ps = u32((5 + s.tclk_trailcnt) * hsclk_p_ps - 3 * spl_p_ps)
    tclk_zero_ps = u32((2 + s.tclk_zerocnt) * hsclk_p_ps + 3 * spl_p_ps)
    ths_trail_ps = u32((5 + s.ths_trailcnt) * hsclk_p_ps - 11 * spl_p_ps)
    ths_zero_ps = u32((7 + s.ths_zerocnt) * hsclk_p_ps + 4 * hsclk_p_ps
                      + 11 * spl_p_ps)

    if s.is_continuous_clk:
        tmp = u32(2 * lptxtime_ps)
        tmp = u32(tmp + 25 * hsclk_p_ps)
        tmp = u32(tmp + ths_trail_ps)
        tmp = u32(tmp + ths_zero_ps)
    else:
        tmp = u32(4 * lptxtime_ps)
        tmp = u32(tmp + ths_trail_ps + tclk_post_ps + tclk_trail_ps
                  + tclk_zero_ps + ths_zero_ps)
        tmp = u32(tmp + (13 + s.lptxtimecnt * 8) * hsclk_p_ps)
        tmp = u32(tmp + 22 * hsclk_p_ps)
        tmp = u32(tmp * 3)
        tmp = div_round_closest(tmp, 2)
    s.csi_hs_lp_hs_ps = tmp


def _adjust_fifo_size(s, fmt, pclk, width, hblank):
    """tc358746_adjust_fifo_size(): smallest FIFO where the two sides fit."""
    pclk_period_ps = 1000000000 // (pclk // 1000)
    csi_bps = u32(s.speed_per_lane * s.lane_num)
    csi_bps_period_ps = 1000000000 // (csi_bps // 1000)
    csi_hsclk = s.speed_per_lane >> 3
    csi_hsclk_period_ps = 1000000000 // (csi_hsclk // 1000)

    p_hactive_ps = u32(pclk_period_ps * fmt.ppp * width)
    p_hblank_ps = u32(pclk_period_ps * hblank)
    p_htotal_ps = u32(p_hblank_ps + p_hactive_ps)

    fifo_size = TC358746_MAX_FIFO_SIZE
    for trial in range(1, TC358746_MAX_FIFO_SIZE):
        c_fifo_delay_ps = u32(trial * 32 * pclk_period_ps)
        c_fifo_delay_ps = u32(c_fifo_delay_ps // fmt.bus_width)
        c_fifo_delay_ps = u32(c_fifo_delay_ps + 4 * csi_hsclk_period_ps)

        c_hactive_ps = u32(csi_bps_period_ps * fmt.bpp * width)
        c_hactive_ps = u32(c_hactive_ps + c_fifo_delay_ps)

        # Unsigned difference, then read through a signed int: this is where
        # the C relies on wrap-around to reject a too-small FIFO.
        c_lp_active_ps = u32(p_htotal_ps - c_hactive_ps)

        c_hactive_ps_diff = s32(c_hactive_ps - p_hactive_ps)
        c_fifo_delay_ps_diff = s32(p_htotal_ps - c_hactive_ps)
        c_lp_active_ps_diff = s32(c_lp_active_ps - s.csi_hs_lp_hs_ps)

        if c_hactive_ps_diff > 0 and c_fifo_delay_ps_diff > 0 and c_lp_active_ps_diff > 0:
            fifo_size = trial
            break

    s.vb_fifo = fifo_size
    if fifo_size == TC358746_MAX_FIFO_SIZE:
        raise CalcError("no FIFO size fits these timings -- try another link frequency")


def calculate(mbus_format, refclk, link_frequency, num_lanes,
              discontinuous_clk, pclk, width, hblank):
    """Port of tc358746_calculate(). Raises CalcError instead of returning -EINVAL."""
    s = Settings()
    s.format = Fmt(mbus_format)
    _setup_pll(s, refclk, link_frequency)
    _set_lane_settings(s, link_frequency, num_lanes, discontinuous_clk)
    _setup_pll_post(s)
    _calculate_csi_txtimings(s)
    _adjust_fifo_size(s, s.format, pclk, width, hblank)
    return s


# ---------------------------------------------------------------------------
# Registers -- values from tc358746_regs.h
# ---------------------------------------------------------------------------

SYSCTL = 0x0002
SYSCTL_SRESET_MASK = 1 << 0
CONFCTL = 0x0004
CONFCTL_PDATAF_MASK = 0x0300
CONFCTL_PPEN_MASK = 1 << 6
FIFOCTL = 0x0006
DATAFMT = 0x0008
DATAFMT_PDFMT_MASK = 0x00F0
DATAFMT_UDT_EN_MASK = 1 << 0
PLLCTL0 = 0x0016
PLLCTL0_PLL_PRD_MASK = 0xF000
PLLCTL0_PLL_FBD_MASK = 0x01FF
PLLCTL1 = 0x0018
PLLCTL1_PLL_FRS_MASK = 0x0C00
PLLCTL1_CKEN_MASK = 1 << 4
PLLCTL1_RESETB_MASK = 1 << 1
PLLCTL1_PLL_EN_MASK = 1 << 0
WORDCNT = 0x0022
PP_MISC = 0x0032
DBG_ACT_LINE_CNT = 0x00E0
CLW_CNTRL = 0x0140
D0W_CNTRL = 0x0144
D1W_CNTRL = 0x0148
D2W_CNTRL = 0x014C
D3W_CNTRL = 0x0150
LANEDISABLE_MASK = 1 << 0
STARTCNTRL = 0x0204
STARTCNTRL_START_MASK = 1 << 0
LINEINITCNT = 0x0210
LPTXTIMECNT = 0x0214
TCLK_HEADERCNT = 0x0218
TCLK_TRAILCNT = 0x021C
THS_HEADERCNT = 0x0220
TWAKEUP = 0x0224
TCLK_POSTCNT = 0x0228
THS_TRAILCNT = 0x022C
HSTXVREGCNT = 0x0230
HSTXVREGEN = 0x0234
TXOPTIONCNTRL = 0x0238
TXOPTIONCNTRL_CONTCLKMODE_MASK = 1 << 0
CSI_CONTROL_CSI_MODE_MASK = 1 << 15
CSI_CONTROL_TXHSMD_MASK = 1 << 7
CSI_CONTROL_EOTDIS_MASK = 1 << 0
CSI_CONFW = 0x0500
CSI_CONFW_MODE_SET_MASK = (1 << 31) | (1 << 29)
CSI_CONFW_ADDRESS_CSI_CONTROL_MASK = (1 << 24) | (1 << 25)
CSI_CONFW_DATA_MASK = 0x0000FFFF
CSIRESET = 0x0504
CSIRESET_RESET_CNF_MASK = 1 << 1
CSIRESET_RESET_MODULE_MASK = 1 << 0
CSI_START = 0x0518
CSI_START_STRT_MASK = 1 << 0

CSI_HSTXVREGCNT = 5     # constant used by the driver


def build_sequence(s, width, start_stream=True):
    """The register writes the driver performs, in order.

    Returns a list of (address, value, comment). Values are LOGICAL: the byte
    order for the 32-bit range is applied at write time, see Bus.write().
    """
    fmt = s.format
    seq = []

    seq.append((DBG_ACT_LINE_CNT, 0, "clear the debug line counter"))
    seq.append((SYSCTL, SYSCTL_SRESET_MASK, "assert software reset"))
    seq.append((SYSCTL, 0, "release software reset"))

    pllctl0 = (((s.pll_prd - 1) << 12) & PLLCTL0_PLL_PRD_MASK) | \
              ((s.pll_fbd - 1) & PLLCTL0_PLL_FBD_MASK)
    seq.append((PLLCTL0, pllctl0,
                "PRD=%d FBD=%d (both stored as value-1)" % (s.pll_prd, s.pll_fbd)))
    pllctl1 = ((s.speed_range << 10) & PLLCTL1_PLL_FRS_MASK) | \
        PLLCTL1_RESETB_MASK | PLLCTL1_PLL_EN_MASK
    seq.append(("bits", PLLCTL1,
                PLLCTL1_PLL_FRS_MASK | PLLCTL1_RESETB_MASK | PLLCTL1_PLL_EN_MASK,
                pllctl1, "FRS=%d, release reset, enable PLL" % s.speed_range))
    seq.append(("delay", 1000, "wait for PLL lock -- the one delay that matters"))
    seq.append(("bits", PLLCTL1, PLLCTL1_CKEN_MASK, PLLCTL1_CKEN_MASK,
                "enable the PLL output"))

    seq.append(("bits", DATAFMT, DATAFMT_PDFMT_MASK | DATAFMT_UDT_EN_MASK,
                (fmt.pdformat << 4) & DATAFMT_PDFMT_MASK,
                "PDFMT=%d (%s), UDT_EN=0" % (fmt.pdformat, fmt.name)))
    seq.append(("bits", CONFCTL, CONFCTL_PDATAF_MASK,
                (fmt.pdataf << 8) & CONFCTL_PDATAF_MASK,
                "parallel data format option %d" % fmt.pdataf))

    seq.append((FIFOCTL, s.vb_fifo, "video buffer fill level"))
    seq.append((WORDCNT, (width * fmt.bpp) // 8,
                "CSI-2 payload = %d bytes/line" % ((width * fmt.bpp) // 8)))

    for idx, reg in ((1, CLW_CNTRL), (1, D0W_CNTRL), (2, D1W_CNTRL),
                     (3, D2W_CNTRL), (4, D3W_CNTRL)):
        if s.lane_num < idx:
            seq.append((reg, LANEDISABLE_MASK, "disable this lane"))

    vreg = 0
    if s.lane_num > 0:
        vreg |= (1 << 0) | (1 << 1)     # clock lane + data lane 0
    if s.lane_num > 1:
        vreg |= 1 << 2
    if s.lane_num > 2:
        vreg |= 1 << 3
    if s.lane_num > 3:
        vreg |= 1 << 4
    seq.append((HSTXVREGEN, vreg, "enable HS transmit regulators"))

    seq.append((TCLK_HEADERCNT,
                ((s.tclk_zerocnt << 8) & 0xFF00) | (s.tclk_preparecnt & 0x7F),
                "TCLK_ZEROCNT=%d TCLK_PREPARECNT=%d" % (s.tclk_zerocnt, s.tclk_preparecnt)))
    seq.append((THS_HEADERCNT,
                ((s.ths_zerocnt << 8) & 0x7F00) | (s.ths_preparecnt & 0x7F),
                "THS_ZEROCNT=%d THS_PREPARECNT=%d" % (s.ths_zerocnt, s.ths_preparecnt)))
    seq.append((TWAKEUP, s.twakeupcnt, "TWAKEUP"))
    seq.append((TCLK_POSTCNT, s.tclk_postcnt, "TCLK_POSTCNT"))
    seq.append((THS_TRAILCNT, s.ths_trailcnt, "THS_TRAILCNT"))
    seq.append((LINEINITCNT, s.lineinitcnt, "LINEINITCNT"))
    seq.append((LPTXTIMECNT, s.lptxtimecnt, "LPTXTIMECNT"))
    seq.append((TCLK_TRAILCNT, s.tclk_trailcnt, "TCLK_TRAILCNT"))
    seq.append((HSTXVREGCNT, CSI_HSTXVREGCNT, "HSTXVREGCNT"))
    seq.append((TXOPTIONCNTRL,
                TXOPTIONCNTRL_CONTCLKMODE_MASK if s.is_continuous_clk else 0,
                "continuous clock" if s.is_continuous_clk else "discontinuous clock"))

    seq.append((STARTCNTRL, STARTCNTRL_START_MASK, "start the D-PHY"))
    seq.append((CSI_START, CSI_START_STRT_MASK, "start the CSI transmitter"))

    nol = {1: 0, 2: 1 << 1, 3: 1 << 2, 4: (1 << 1) | (1 << 2)}[s.lane_num]
    ctrl = nol | CSI_CONTROL_CSI_MODE_MASK | CSI_CONTROL_TXHSMD_MASK | \
        CSI_CONTROL_EOTDIS_MASK
    seq.append((CSI_CONFW,
                (ctrl & CSI_CONFW_DATA_MASK) | CSI_CONFW_MODE_SET_MASK
                | CSI_CONFW_ADDRESS_CSI_CONTROL_MASK,
                "CSI_CONTROL via CONFW: %d lanes, CSI mode, HS, EoT disabled" % s.lane_num))

    if start_stream:
        seq.append((PP_MISC, 0, "release the parallel port"))
        seq.append(("bits", CONFCTL, CONFCTL_PPEN_MASK, CONFCTL_PPEN_MASK,
                    "enable the parallel input -- video starts here"))
    return seq


def build_stop_sequence():
    """What the driver does at stop: freeze, reset pointers, reset the CSI config."""
    return [
        ("bits", CONFCTL, CONFCTL_PPEN_MASK, 0, "disable the parallel input"),
        ("bits", PP_MISC, 1 << 15, 1 << 15, "FrmStop"),
        ("bits", PP_MISC, 1 << 14, 1 << 14, "RstPtr"),
        # ⚠️ Both bits, RstMdl included. The datasheet (Table 6.73) says not to
        # set RstMdl and to use a hardware reset instead -- but writing RstCnf
        # alone produced no frames at all on our hardware (measured 2026-09-07).
        (CSIRESET, CSIRESET_RESET_CNF_MASK | CSIRESET_RESET_MODULE_MASK,
         "reset the CSI configuration"),
    ]


# ---------------------------------------------------------------------------
# I2C
# ---------------------------------------------------------------------------

I2C_SLAVE = 0x0703
I2C_SLAVE_FORCE = 0x0706


class Bus:
    """TC358746 register access.

    Byte order, datasheet §4.10.2 / Figure 4.21: registers are 16-bit aligned,
    and a 32-bit register is two consecutive 16-bit registers written LOW HALF
    FIRST. As a byte permutation of the logical value that is
    DATA[15:8] DATA[7:0] DATA[31:24] DATA[23:16]. Getting this wrong writes
    every PLL and timing register askew, and the symptom is a mute link with no
    error reported anywhere.
    """

    def __init__(self, bus, addr, force=True, dry_run=False):
        self.dry_run = dry_run
        self.fd = None
        if not dry_run:
            self.fd = os.open("/dev/i2c-%d" % bus, os.O_RDWR)
            fcntl.ioctl(self.fd, I2C_SLAVE_FORCE if force else I2C_SLAVE, addr)

    @staticmethod
    def is32(reg):
        return reg >= 0x0100

    def read(self, reg):
        if self.dry_run:
            return 0
        os.write(self.fd, struct.pack(">H", reg))
        n = 4 if self.is32(reg) else 2
        b = os.read(self.fd, n)
        if n == 2:
            return struct.unpack(">H", b)[0]
        return (b[2] << 24) | (b[3] << 16) | (b[0] << 8) | b[1]

    def write(self, reg, val):
        if self.dry_run:
            return
        if self.is32(reg):
            d = bytes([(val >> 8) & 0xFF, val & 0xFF,
                       (val >> 24) & 0xFF, (val >> 16) & 0xFF])
        else:
            d = struct.pack(">H", val & 0xFFFF)
        os.write(self.fd, struct.pack(">H", reg) + d)

    def update_bits(self, reg, mask, val):
        cur = self.read(reg)
        self.write(reg, (cur & ~mask) | (val & mask))

    def close(self):
        if self.fd is not None:
            os.close(self.fd)


def apply_sequence(bus, seq, verbose):
    import time
    for item in seq:
        if item[0] == "delay":
            _, usec, comment = item
            if verbose:
                print("  wait %d us            %s" % (usec, comment))
            time.sleep(usec / 1e6)
        elif item[0] == "bits":
            _, reg, mask, val, comment = item
            if verbose:
                print("  bits @0x%04X mask 0x%X = 0x%X   %s" % (reg, mask, val, comment))
            bus.update_bits(reg, mask, val)
        else:
            reg, val, comment = item
            if verbose:
                w = 8 if Bus.is32(reg) else 4
                print("  write @0x%04X = 0x%0*X   %s" % (reg, w, val, comment))
            bus.write(reg, val)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_settings(s, pclk, width, hblank):
    f = s.format
    print("Computed settings")
    print("  format            %s (code 0x%04X), %d bpp on a %d-bit bus, %d pclk/pixel"
          % (f.name, f.code, f.bpp, f.bus_width, f.ppp))
    print("  PLL               PRD=%d FBD=%d, PLLinclk=%d Hz (VCO target %d Hz, error %d Hz)"
          % (s.pll_prd, s.pll_fbd, s.pllinclk_hz, s._target_vco, s._pll_error))
    print("  CSI               %d lane(s), %d bps/lane, speed range %d, %s clock"
          % (s.lane_num, s.speed_per_lane, s.speed_range,
             "continuous" if s.is_continuous_clk else "discontinuous"))
    print("  D-PHY counters    lineinit=%d lptxtime=%d twakeup=%d" %
          (s.lineinitcnt, s.lptxtimecnt, s.twakeupcnt))
    print("                    tclk prepare=%d zero=%d trail=%d post=%d" %
          (s.tclk_preparecnt, s.tclk_zerocnt, s.tclk_trailcnt, s.tclk_postcnt))
    print("                    ths  prepare=%d zero=%d trail=%d" %
          (s.ths_preparecnt, s.ths_zerocnt, s.ths_trailcnt))
    print("  FIFO              %d   (line = %d bytes)"
          % (s.vb_fifo, (width * f.bpp) // 8))


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Configure a TC358746 parallel-to-CSI-2 bridge over I2C.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The --mbus-format, --refclk, --link-frequency, --num-lanes,\n"
               "--discontinuous-clk, --pclk, --width and --hblank options are the\n"
               "same inputs the kernel driver feeds to tc358746_calculate().")
    p.add_argument("--bus", type=int, default=None,
                   help="I2C bus number, e.g. 10 for /dev/i2c-10")
    p.add_argument("--addr", type=lambda x: int(x, 0), default=0x0E,
                   help="bridge I2C address (default 0x0E)")
    p.add_argument("--no-force", action="store_true",
                   help="use I2C_SLAVE instead of I2C_SLAVE_FORCE; the default is "
                        "FORCE because a kernel driver usually holds this address")
    p.add_argument("--mbus-format", required=True, choices=sorted(FORMATS),
                   help="parallel input format")
    p.add_argument("--refclk", type=int, required=True, help="REFCLK in Hz")
    p.add_argument("--link-frequency", type=int, required=True,
                   help="CSI-2 link frequency in Hz (half the bit rate per lane)")
    p.add_argument("--num-lanes", type=int, required=True, choices=(1, 2, 3, 4))
    p.add_argument("--discontinuous-clk", action="store_true",
                   help="CSI clock is not continuous")
    p.add_argument("--pclk", type=int, required=True,
                   help="parallel pixel clock in Hz")
    p.add_argument("--width", type=int, required=True, help="active pixels per line")
    p.add_argument("--hblank", type=int, required=True,
                   help="horizontal blanking in pixels (line_length - width)")
    p.add_argument("--no-start", action="store_true",
                   help="configure but do not enable the parallel input")
    p.add_argument("--stop", action="store_true",
                   help="issue the stop sequence instead of configuring")
    p.add_argument("--dry-run", action="store_true",
                   help="compute and print, touch no hardware")
    p.add_argument("-q", "--quiet", action="store_true")
    a = p.parse_args(argv)

    if a.bus is None and not a.dry_run:
        p.error("--bus is required unless --dry-run is given")

    try:
        s = calculate(a.mbus_format, a.refclk, a.link_frequency, a.num_lanes,
                      a.discontinuous_clk, a.pclk, a.width, a.hblank)
    except CalcError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1

    if not a.quiet:
        print_settings(s, a.pclk, a.width, a.hblank)
        print()

    bus = Bus(a.bus or 0, a.addr, force=not a.no_force, dry_run=a.dry_run)
    try:
        if not a.dry_run:
            chip = bus.read(0x0000)
            if chip != 0x4401 and not a.quiet:
                print("warning: chip ID reads 0x%04X, expected 0x4401 -- wrong "
                      "address or bus?" % chip, file=sys.stderr)
        seq = build_stop_sequence() if a.stop else \
            build_sequence(s, a.width, start_stream=not a.no_start)
        if not a.quiet:
            print("Register sequence%s" % (" (dry run, nothing written)" if a.dry_run else ""))
        apply_sequence(bus, seq, verbose=not a.quiet)
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
