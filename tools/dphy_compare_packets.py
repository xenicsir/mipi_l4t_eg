#!/usr/bin/env python3
"""
D-PHY CSI-2 Packet Analyzer — PicoScope CSV
Analyzes HS burst structure on a single-ended Dn probe.

D-PHY HS entry sequence (spec v3.0, Table 4):
  LP-11 → LP-01 (T_LPX) → LP-00 (T_HS-PREPARE) → HS-0 (T_HS-ZERO)
  → Sync 0xB8 LSB-first '00011101' (T_HS-SYNC) → HS DATA
  → HS-TRAIL → LP-11 (T_HS-EXIT)

On Dn probe:
  - LP-11: ~1.2V (Dn=1)
  - LP-01 (T_LPX): Dn stays high (~1.2V) — INVISIBLE on Dn probe
  - LP-00 (T_HS-PREPARE): Dn falls to ~0V
  - HS-ZERO: Dn rises to ~0.48V constant (all 0-bits → Dn high in differential)
  - Sync 0xB8: first 3 bits = 0 (still 0.48V), then 1,1,1 → Dn drops to ~0.13V
  - HS DATA: noisy ~0.13–0.48V (aliased at 500 MSa/s)
  - HS-TRAIL: toggled state held constant (0.13V or 0.48V depending on last data bit)
  - T_HS-EXIT: ramp from HS level back to LP-11 (~1.2V)

Usage:
  python3 analyze_dphy_packets.py --ko 20260324-KO.csv --ok 20260324-OK3.csv
"""

import argparse
import sys
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# ─── Configuration ──────────────────────────────────────────────────────────

@dataclass
class DphyConfig:
    """D-PHY link parameters — customize per setup."""
    clock_mhz: float = 340.0       # MIPI clock frequency
    num_lanes: int = 2             # Number of data lanes
    sample_rate_msa: float = 500.0 # PicoScope sample rate (MSa/s)

    @property
    def data_rate_mbps(self) -> float:
        """DDR: data rate = 2 × clock."""
        return self.clock_mhz * 2

    @property
    def ui_ns(self) -> float:
        """Unit Interval = 1 / data_rate."""
        return 1000.0 / self.data_rate_mbps

    @property
    def sample_interval_ns(self) -> float:
        return 1000.0 / self.sample_rate_msa

    @property
    def samples_per_ui(self) -> float:
        return self.ui_ns / self.sample_interval_ns

    def spec_limits(self) -> dict:
        """D-PHY v3.0 Table 18 timing limits (forward direction, n=1)."""
        ui = self.ui_ns
        return {
            'T_LPX_min_ns':          50.0,
            'T_HS_PREPARE_min_ns':   40.0 + 4 * ui,
            'T_HS_PREPARE_max_ns':   85.0 + 6 * ui,
            'T_HS_PREP_ZERO_min_ns': 145.0 + 10 * ui,
            'T_HS_TRAIL_min_ns':     max(8 * ui, 60.0 + 4 * ui),
            'T_HS_EXIT_min_ns':      100.0,
            'T_HS_SYNC_ui':          8,
            'T_HS_SYNC_ns':          8 * ui,
            'T_EOT_max_ns':          105.0 + 12 * ui,
        }


# ─── Voltage thresholds (single-ended Dn probe) ────────────────────────────

LP11_THRESHOLD = 0.90    # Above this = LP-11
LP00_THRESHOLD = 0.10    # Below this = LP-00 (or near-zero)
HS_LEVEL_LOW   = 0.10    # HS differential low (HS-1 bit on Dn)
HS_LEVEL_HIGH  = 0.55    # HS differential high (HS-0 bit on Dn)
HS_MID         = 0.30    # Midpoint for HS detection
BURST_THRESHOLD = 0.60   # Below this = inside HS burst region


# ─── Data structures ────────────────────────────────────────────────────────

@dataclass
class PacketPhases:
    """Measured phases of a single D-PHY HS packet."""
    # Sample indices (absolute in the loaded data)
    lp11_end: int = 0          # Last LP-11 sample before fall
    lp00_start: int = 0        # First sample near 0V (LP-00 / bridge)
    lp00_end: int = 0          # Last sample near 0V before HS rise
    hs_zero_start: int = 0     # First sample at HS-ZERO level
    hs_zero_end: int = 0       # Last sample of constant HS-ZERO (before variance rises)
    hs_data_start: int = 0     # First sample of noisy HS data (includes SoT transition)
    hs_data_end: int = 0       # Last sample of HS data (before Trail)
    trail_start: int = 0       # First sample of Trail
    trail_end: int = 0         # Last sample of Trail (before EXIT ramp)
    lp11_resume: int = 0       # First sample back at LP-11 level

    def durations_samp(self) -> dict:
        return {
            'lp_fall':     self.lp00_start - self.lp11_end,
            'lp00_flat':   self.lp00_end - self.lp00_start,
            'hs_rise':     self.hs_zero_start - self.lp00_end,
            'hs_zero':     self.hs_zero_end - self.hs_zero_start,
            'hs_data':     self.hs_data_end - self.hs_data_start,
            'trail':       self.trail_end - self.trail_start,
            'hs_exit':     self.lp11_resume - self.trail_end,
            'total_burst': self.lp11_resume - self.lp11_end,
            'hs_payload':  self.hs_data_end - self.hs_zero_start,  # HS-ZERO + SoT + DATA
        }

    def durations_ns(self, dt_ns: float) -> dict:
        return {k: v * dt_ns for k, v in self.durations_samp().items()}


@dataclass
class PacketAnalysis:
    """Complete analysis of one packet."""
    index: int
    phases: PacketPhases
    durations_samp: dict = field(default_factory=dict)
    durations_ns: dict = field(default_factory=dict)
    spec_check: dict = field(default_factory=dict)


# ─── CSV loading ────────────────────────────────────────────────────────────

def load_csv(path: str, max_samples: int = 0) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Load PicoScope CSV. Returns (channel_A, channel_B, dt_ns).
    Format: Temps;Canal A;Canal B with (ms);(V);(V), decimal=','
    """
    kwargs = dict(sep=';', decimal=',', header=0, skiprows=1,
                  names=['t', 'A', 'B'], dtype=np.float64)
    if max_samples > 0:
        kwargs['nrows'] = max_samples
    df = pd.read_csv(path, **kwargs)
    dt_ms = df['t'].iloc[1] - df['t'].iloc[0]
    dt_ns = dt_ms * 1e6  # ms → ns
    return df['A'].values, df['B'].values, dt_ns


# ─── Burst finder ───────────────────────────────────────────────────────────

def find_hs_bursts(data: np.ndarray, threshold: float = BURST_THRESHOLD,
                   min_duration: int = 500) -> List[Tuple[int, int, int]]:
    """
    Find HS burst regions where signal < threshold.
    Returns list of (start, end, duration) tuples.
    min_duration filters out short LP glitches.
    """
    below = (data < threshold).astype(np.int8)
    tr = np.diff(below)
    starts = np.where(tr == 1)[0] + 1
    ends = np.where(tr == -1)[0] + 1

    # Align starts/ends
    if len(ends) > 0 and (len(starts) == 0 or ends[0] < starts[0]):
        ends = ends[1:]
    if len(starts) > len(ends):
        starts = starts[:len(ends)]

    bursts = [(s, e, e - s) for s, e in zip(starts, ends) if e - s >= min_duration]
    return bursts


# ─── Phase detection for a single packet ────────────────────────────────────

def analyze_packet(data: np.ndarray, burst_start: int, burst_end: int,
                   dt_ns: float, cfg: DphyConfig) -> PacketPhases:
    """
    Identify all D-PHY phases around a single HS burst.
    burst_start/burst_end are from the 0.6V-threshold burst finder.
    """
    phases = PacketPhases()

    # --- LP-11 end: scan backward from burst_start to find last sample > LP11_THRESHOLD
    idx = burst_start
    while idx > 0 and data[idx] < LP11_THRESHOLD:
        idx -= 1
    phases.lp11_end = idx

    # --- LP-00 start: first sample below LP00_THRESHOLD after lp11_end
    idx = phases.lp11_end
    while idx < burst_end and data[idx] > LP00_THRESHOLD:
        idx += 1
    phases.lp00_start = idx

    # --- LP-00 end: last sample below LP00_THRESHOLD before signal rises to HS level
    idx = phases.lp00_start
    while idx < burst_end and data[idx] < LP00_THRESHOLD:
        idx += 1
    # Back up to last sample that was below threshold
    phases.lp00_end = idx

    # --- HS-ZERO start: first sample above HS_MID after LP-00
    idx = phases.lp00_end
    while idx < burst_end and data[idx] < HS_MID:
        idx += 1
    phases.hs_zero_start = idx

    # --- HS-ZERO end / HS DATA start: detect where variance increases
    # Use a sliding window std over ~16 samples (~32 ns ≈ 22 bits)
    win = 16
    if phases.hs_zero_start + win * 3 < burst_end:
        # Compute rolling std
        segment = data[phases.hs_zero_start:burst_end]
        if len(segment) > win * 2:
            rolling_std = np.array([
                np.std(segment[i:i + win])
                for i in range(len(segment) - win)
            ])
            # HS-ZERO has very low std (constant ~0.48V, std < 0.03V)
            # HS DATA has high std (oscillating 0.13–0.48V, std > 0.06V)
            std_threshold = 0.04
            # Find first index where std exceeds threshold for at least 3 consecutive samples
            above = rolling_std > std_threshold
            for i in range(len(above) - 3):
                if above[i] and above[i + 1] and above[i + 2]:
                    phases.hs_zero_end = phases.hs_zero_start + i
                    # SoT is ~6 samples before the variance spike (first 3 bits of 0xB8 are 0)
                    # The visible transition is at bit 3 of SoT (first '1' bit)
                    # So hs_data_start ≈ hs_zero_end (the variance detects SoT onset)
                    phases.hs_data_start = phases.hs_zero_start + i
                    break
            else:
                # Fallback: no variance spike found (unlikely for real data)
                phases.hs_zero_end = burst_end - 100
                phases.hs_data_start = phases.hs_zero_end
        else:
            phases.hs_zero_end = burst_end - 100
            phases.hs_data_start = phases.hs_zero_end
    else:
        phases.hs_zero_end = burst_end - 50
        phases.hs_data_start = phases.hs_zero_end

    # --- HS DATA end / Trail start: detect where variance drops near burst end
    # Scan backward from burst_end
    trail_search_start = max(phases.hs_data_start, burst_end - 200)
    segment_end = data[trail_search_start:burst_end]
    if len(segment_end) > win * 2:
        rolling_std_end = np.array([
            np.std(segment_end[i:i + win])
            for i in range(len(segment_end) - win)
        ])
        std_threshold = 0.04
        # Find LAST position where std drops below threshold
        below_thresh = rolling_std_end < std_threshold
        # Scan from end backward to find where Trail begins
        trail_found = False
        for i in range(len(below_thresh) - 1, 2, -1):
            if not below_thresh[i] and below_thresh[i - 1]:
                # Transition from low-std to high-std going backward = end of Trail
                phases.trail_end = trail_search_start + i
                trail_found = True
                break
        if not trail_found:
            phases.trail_end = burst_end

        # Find where Trail starts (std drops below threshold after DATA)
        for i in range(len(below_thresh) - 1):
            if not below_thresh[i] and below_thresh[i + 1] and below_thresh[i + 2]:
                trail_candidate = trail_search_start + i + 1
                if trail_candidate > phases.hs_data_start + 100:
                    phases.trail_start = trail_candidate
                    phases.hs_data_end = trail_candidate
                    break
        else:
            phases.trail_start = burst_end - 50
            phases.hs_data_end = phases.trail_start
    else:
        phases.hs_data_end = burst_end - 30
        phases.trail_start = phases.hs_data_end
        phases.trail_end = burst_end

    # --- LP-11 resume: first sample above LP11_THRESHOLD after burst_end
    idx = burst_end
    limit = min(len(data), burst_end + 200)
    while idx < limit and data[idx] < LP11_THRESHOLD:
        idx += 1
    phases.lp11_resume = idx

    return phases


# ─── Spec compliance check ──────────────────────────────────────────────────

def check_spec(durations_ns: dict, cfg: DphyConfig) -> dict:
    """Check measured durations against D-PHY v3.0 Table 18 limits."""
    spec = cfg.spec_limits()
    checks = {}

    # Note: on Dn probe, we can't separate T_LPX from T_HS-PREPARE
    # lp_fall + lp00_flat = transition time + LP-00 hold = related to T_HS-PREPARE
    # T_LPX is invisible on Dn probe (it's on Dp during LP-01)

    # T_HS-PREPARE (lp00_flat approximation — but this is just the LP-00 hold visible on Dn)
    t_prep = durations_ns.get('lp00_flat', 0)
    checks['T_HS-PREPARE (LP-00 flat)'] = {
        'measured_ns': t_prep,
        'spec_min': spec['T_HS_PREPARE_min_ns'],
        'spec_max': spec['T_HS_PREPARE_max_ns'],
        'status': 'OK' if spec['T_HS_PREPARE_min_ns'] <= t_prep <= spec['T_HS_PREPARE_max_ns']
                  else 'BELOW_MIN' if t_prep < spec['T_HS_PREPARE_min_ns']
                  else 'ABOVE_MAX'
    }

    # T_HS-PREPARE + T_HS-ZERO combined
    t_prep_zero = t_prep + durations_ns.get('hs_zero', 0) + durations_ns.get('hs_rise', 0)
    checks['T_HS-PREPARE + T_HS-ZERO'] = {
        'measured_ns': t_prep_zero,
        'spec_min': spec['T_HS_PREP_ZERO_min_ns'],
        'status': 'OK' if t_prep_zero >= spec['T_HS_PREP_ZERO_min_ns'] else 'BELOW_MIN'
    }

    # T_HS-TRAIL
    t_trail = durations_ns.get('trail', 0)
    checks['T_HS-TRAIL'] = {
        'measured_ns': t_trail,
        'spec_min': spec['T_HS_TRAIL_min_ns'],
        'status': 'OK' if t_trail >= spec['T_HS_TRAIL_min_ns'] else 'BELOW_MIN'
    }

    # T_HS-EXIT
    t_exit = durations_ns.get('hs_exit', 0)
    checks['T_HS-EXIT'] = {
        'measured_ns': t_exit,
        'spec_min': spec['T_HS_EXIT_min_ns'],
        'status': 'OK' if t_exit >= spec['T_HS_EXIT_min_ns'] else 'BELOW_MIN'
    }

    # HS-ZERO (standalone)
    t_zero = durations_ns.get('hs_zero', 0)
    t_zero_min = spec['T_HS_PREP_ZERO_min_ns'] - spec['T_HS_PREPARE_max_ns']
    checks['T_HS-ZERO (standalone)'] = {
        'measured_ns': t_zero,
        'spec_min_approx': max(0, t_zero_min),
        'note': 'Combined constraint only; standalone min depends on T_HS-PREPARE'
    }

    return checks


# ─── Payload size estimation ────────────────────────────────────────────────

def estimate_payload_bytes(hs_data_samp: int, dt_ns: float, cfg: DphyConfig) -> float:
    """
    Estimate CSI-2 payload bytes from HS DATA duration.
    HS DATA includes SoT (8 UI) + header (4 B) + payload (WC B) + CRC (2 B).
    """
    data_ns = hs_data_samp * dt_ns
    # Total bits on this lane during HS DATA
    bits_per_lane = data_ns * cfg.data_rate_mbps / 1000.0
    # Total bytes across all lanes, minus SoT + header + CRC overhead
    sot_bits = 8  # per lane
    header_bytes = 4
    crc_bytes = 2
    overhead_bytes = header_bytes + crc_bytes
    total_bytes = (bits_per_lane - sot_bits) / 8.0 * cfg.num_lanes - overhead_bytes
    return max(0, total_bytes)


# ─── Analyze a set of packets ───────────────────────────────────────────────

def analyze_file(path: str, cfg: DphyConfig, n_packets: int = 10,
                 max_samples: int = 10_000_000, label: str = "FILE") -> List[PacketAnalysis]:
    """Load a CSV file and analyze the first n_packets complete HS bursts."""
    print(f"\n{'=' * 80}")
    print(f"  Analyzing: {path}  ({label})")
    print(f"  Config: {cfg.clock_mhz} MHz clock, {cfg.num_lanes} lanes, "
          f"{cfg.data_rate_mbps} Mbps/lane, UI = {cfg.ui_ns:.3f} ns")
    print(f"  Sample rate: {cfg.sample_rate_msa} MSa/s, dt = {1000/cfg.sample_rate_msa:.1f} ns")
    print(f"{'=' * 80}")

    data_a, data_b, dt_ns = load_csv(path, max_samples=max_samples)
    print(f"  Loaded {len(data_a):,} samples ({len(data_a) * dt_ns / 1e6:.1f} ms)")

    bursts = find_hs_bursts(data_a, threshold=BURST_THRESHOLD, min_duration=500)
    print(f"  Found {len(bursts)} HS bursts (>{500} samples)")

    if len(bursts) < n_packets:
        print(f"  WARNING: only {len(bursts)} bursts found, requested {n_packets}")
        n_packets = len(bursts)

    # Skip first burst (may be partial)
    start_idx = 1 if len(bursts) > n_packets else 0
    results = []

    for i in range(start_idx, start_idx + n_packets):
        bs, be, bdur = bursts[i]
        phases = analyze_packet(data_a, bs, be, dt_ns, cfg)
        dur_samp = phases.durations_samp()
        dur_ns = phases.durations_ns(dt_ns)
        spec = check_spec(dur_ns, cfg)

        pa = PacketAnalysis(
            index=i,
            phases=phases,
            durations_samp=dur_samp,
            durations_ns=dur_ns,
            spec_check=spec,
        )
        results.append(pa)

    # ─── Print per-packet results ───
    print(f"\n  {'Pkt':>3} │ {'LP fall':>8} │ {'LP-00':>8} │ {'HS rise':>8} │ "
          f"{'HS-ZERO':>8} │ {'HS DATA':>8} │ {'Trail':>8} │ {'HS-EXIT':>8} │ "
          f"{'Total':>8} │ {'WC est':>8}")
    print(f"  {'':>3} │ {'(samp)':>8} │ {'(samp)':>8} │ {'(samp)':>8} │ "
          f"{'(samp)':>8} │ {'(samp)':>8} │ {'(samp)':>8} │ {'(samp)':>8} │ "
          f"{'(samp)':>8} │ {'(bytes)':>8}")
    print(f"  {'─' * 3}─┼{'─' * 10}┼{'─' * 10}┼{'─' * 10}┼"
          f"{'─' * 10}┼{'─' * 10}┼{'─' * 10}┼{'─' * 10}┼"
          f"{'─' * 10}┼{'─' * 10}")

    for pa in results:
        d = pa.durations_samp
        wc = estimate_payload_bytes(d['hs_data'], dt_ns, cfg)
        print(f"  {pa.index:3d} │ {d['lp_fall']:8d} │ {d['lp00_flat']:8d} │ "
              f"{d['hs_rise']:8d} │ {d['hs_zero']:8d} │ {d['hs_data']:8d} │ "
              f"{d['trail']:8d} │ {d['hs_exit']:8d} │ {d['total_burst']:8d} │ "
              f"{wc:8.1f}")

    # ─── Print durations in ns ───
    print(f"\n  {'Pkt':>3} │ {'LP fall':>9} │ {'LP-00':>9} │ {'HS rise':>9} │ "
          f"{'HS-ZERO':>9} │ {'HS DATA':>9} │ {'Trail':>9} │ {'HS-EXIT':>9} │ "
          f"{'Total':>9}")
    print(f"  {'':>3} │ {'(ns)':>9} │ {'(ns)':>9} │ {'(ns)':>9} │ "
          f"{'(ns)':>9} │ {'(ns)':>9} │ {'(ns)':>9} │ {'(ns)':>9} │ "
          f"{'(ns)':>9}")
    print(f"  {'─' * 3}─┼{'─' * 11}┼{'─' * 11}┼{'─' * 11}┼"
          f"{'─' * 11}┼{'─' * 11}┼{'─' * 11}┼{'─' * 11}┼{'─' * 11}")

    for pa in results:
        d = pa.durations_ns
        print(f"  {pa.index:3d} │ {d['lp_fall']:9.1f} │ {d['lp00_flat']:9.1f} │ "
              f"{d['hs_rise']:9.1f} │ {d['hs_zero']:9.1f} │ {d['hs_data']:9.1f} │ "
              f"{d['trail']:9.1f} │ {d['hs_exit']:9.1f} │ {d['total_burst']:9.1f}")

    # ─── Aggregate stats ───
    print(f"\n  Aggregate statistics ({label}, {len(results)} packets):")
    keys = ['lp_fall', 'lp00_flat', 'hs_rise', 'hs_zero', 'hs_data', 'trail', 'hs_exit',
            'total_burst', 'hs_payload']
    print(f"  {'Phase':>15} │ {'Mean(samp)':>11} │ {'Std(samp)':>10} │ "
          f"{'Mean(ns)':>10} │ {'Std(ns)':>9}")
    print(f"  {'─' * 15}─┼{'─' * 13}┼{'─' * 12}┼{'─' * 12}┼{'─' * 11}")
    for k in keys:
        vals_s = [pa.durations_samp[k] for pa in results]
        vals_ns = [pa.durations_ns[k] for pa in results]
        print(f"  {k:>15} │ {np.mean(vals_s):11.1f} │ {np.std(vals_s):10.2f} │ "
              f"{np.mean(vals_ns):10.1f} │ {np.std(vals_ns):9.2f}")

    # ─── Spec compliance ───
    print(f"\n  D-PHY v3.0 spec compliance ({label}):")
    spec = cfg.spec_limits()
    avg_ns = {k: np.mean([pa.durations_ns[k] for pa in results]) for k in keys}
    print(f"    T_LPX (on Dp):             INVISIBLE on Dn probe — cannot verify")
    prep = avg_ns['lp00_flat']
    prep_ok = "OK" if spec['T_HS_PREPARE_min_ns'] <= prep <= spec['T_HS_PREPARE_max_ns'] else "OUT OF SPEC"
    print(f"    T_HS-PREPARE (LP-00 flat):  {prep:.1f} ns  "
          f"(spec: {spec['T_HS_PREPARE_min_ns']:.1f}–{spec['T_HS_PREPARE_max_ns']:.1f} ns)  [{prep_ok}]")
    pz = avg_ns['lp00_flat'] + avg_ns['hs_rise'] + avg_ns['hs_zero']
    pz_ok = "OK" if pz >= spec['T_HS_PREP_ZERO_min_ns'] else "BELOW MIN"
    print(f"    T_HS-PREP + T_HS-ZERO:      {pz:.1f} ns  "
          f"(spec: ≥ {spec['T_HS_PREP_ZERO_min_ns']:.1f} ns)  [{pz_ok}]")
    trail = avg_ns['trail']
    trail_ok = "OK" if trail >= spec['T_HS_TRAIL_min_ns'] else "BELOW MIN"
    print(f"    T_HS-TRAIL:                 {trail:.1f} ns  "
          f"(spec: ≥ {spec['T_HS_TRAIL_min_ns']:.1f} ns)  [{trail_ok}]")
    exit_ns = avg_ns['hs_exit']
    exit_ok = "OK" if exit_ns >= spec['T_HS_EXIT_min_ns'] else "BELOW MIN"
    print(f"    T_HS-EXIT:                  {exit_ns:.1f} ns  "
          f"(spec: ≥ {spec['T_HS_EXIT_min_ns']:.1f} ns)  [{exit_ok}]")

    return results


# ─── Visual packet description ──────────────────────────────────────────────

def print_visual(results: List[PacketAnalysis], dt_ns: float, cfg: DphyConfig, label: str):
    """Print a visual description of the average packet."""
    keys = ['lp_fall', 'lp00_flat', 'hs_rise', 'hs_zero', 'hs_data', 'trail', 'hs_exit']
    avg_s = {k: np.mean([pa.durations_samp[k] for pa in results]) for k in keys}
    avg_ns_d = {k: v * dt_ns for k, v in avg_s.items()}

    ui = cfg.ui_ns
    avg_bits = {k: avg_ns_d[k] / ui for k in keys}

    print(f"\n  ┌─────────────────────────────────────────────────────────────────────┐")
    print(f"  │  Visual packet structure — {label} (mean of {len(results)} packets)         │")
    print(f"  └─────────────────────────────────────────────────────────────────────┘")
    print()
    print(f"    Dn probe  (LP-01/T_LPX invisible — Dn stays at 1.2V during LP-01)")
    print()
    print(f"    V")
    print(f"    1.2V ──┐                                                       ┌───── LP-11")
    print(f"           │ LP fall                                        HS-EXIT│")
    print(f"    0.6V   │    ┌─────────────────────────────────────────┐       │")
    print(f"    0.48V  │    │     HS-ZERO (const)  │ HS DATA (noisy) │Trail  │")
    print(f"    0.13V  │    │                      │~~~~~~~~~~~~~~~~~│       │")
    print(f"    0.0V   └────┘ LP-00                │                 │───────┘")
    print()
    print(f"           ├────┤├────┤├──┤├────────────┤├────────────────┤├────┤├────┤")
    print(f"           fall  LP-00 rise   HS-ZERO     SoT + HS DATA   Trail EXIT")
    print()
    print(f"    Phase       │  Samples │     Time │ Bits/lane │ Description")
    print(f"    ────────────┼──────────┼──────────┼───────────┼──────────────────────────────")
    print(f"    LP fall     │ {avg_s['lp_fall']:8.1f} │ {avg_ns_d['lp_fall']:7.1f} ns │ {avg_bits['lp_fall']:9.1f} │ "
          f"Dn: 1.2V → 0V (LP-01→LP-00 transition)")
    print(f"    LP-00 flat  │ {avg_s['lp00_flat']:8.1f} │ {avg_ns_d['lp00_flat']:7.1f} ns │ {avg_bits['lp00_flat']:9.1f} │ "
          f"T_HS-PREPARE hold (both lines at 0V)")
    print(f"    HS rise     │ {avg_s['hs_rise']:8.1f} │ {avg_ns_d['hs_rise']:7.1f} ns │ {avg_bits['hs_rise']:9.1f} │ "
          f"HS driver enables, Dn rises to HS level")
    print(f"    HS-ZERO     │ {avg_s['hs_zero']:8.1f} │ {avg_ns_d['hs_zero']:7.1f} ns │ {avg_bits['hs_zero']:9.1f} │ "
          f"Constant ~0.48V (all 0-bits, Dn high)")
    print(f"    HS DATA     │ {avg_s['hs_data']:8.1f} │ {avg_ns_d['hs_data']:7.1f} ns │ {avg_bits['hs_data']:9.1f} │ "
          f"SoT 0xB8 + header + payload + CRC")
    print(f"    Trail       │ {avg_s['trail']:8.1f} │ {avg_ns_d['trail']:7.1f} ns │ {avg_bits['trail']:9.1f} │ "
          f"Toggled diff state held constant")
    print(f"    HS-EXIT     │ {avg_s['hs_exit']:8.1f} │ {avg_ns_d['hs_exit']:7.1f} ns │ {avg_bits['hs_exit']:9.1f} │ "
          f"Ramp HS → LP-11 (1.2V)")

    total_s = sum(avg_s[k] for k in keys)
    total_ns = total_s * dt_ns
    print(f"    ────────────┼──────────┼──────────┼───────────┼──────────────────────────────")
    print(f"    TOTAL       │ {total_s:8.1f} │ {total_ns:7.1f} ns │           │")

    wc = estimate_payload_bytes(int(avg_s['hs_data']), dt_ns, cfg)
    print(f"\n    Estimated WC (payload bytes): {wc:.1f}")
    print(f"    Estimated pixels (RAW16):     {wc / 2:.0f}")


# ─── Comparison ─────────────────────────────────────────────────────────────

def compare(results_ok: List[PacketAnalysis], results_ko: List[PacketAnalysis],
            dt_ns: float, cfg: DphyConfig):
    """Compare OK vs KO packets."""
    print(f"\n{'=' * 80}")
    print(f"  COMPARISON: OK vs KO")
    print(f"{'=' * 80}")

    keys = ['lp_fall', 'lp00_flat', 'hs_rise', 'hs_zero', 'hs_data', 'trail', 'hs_exit',
            'total_burst', 'hs_payload']

    print(f"\n  {'Phase':>15} │ {'OK mean':>9} │ {'KO mean':>9} │ {'Δ (samp)':>9} │ "
          f"{'Δ (ns)':>8} │ {'Δ (bytes)':>9} │ Note")
    print(f"  {'─' * 15}─┼{'─' * 11}┼{'─' * 11}┼{'─' * 11}┼"
          f"{'─' * 10}┼{'─' * 11}┼{'─' * 20}")

    for k in keys:
        ok_mean = np.mean([pa.durations_samp[k] for pa in results_ok])
        ko_mean = np.mean([pa.durations_samp[k] for pa in results_ko])
        delta_s = ko_mean - ok_mean
        delta_ns = delta_s * dt_ns
        # Convert delta to bytes: Δns × data_rate × num_lanes / 8
        delta_bytes = delta_ns * 1e-9 * cfg.data_rate_mbps * 1e6 * cfg.num_lanes / 8.0
        note = ""
        if abs(delta_s) > 2 and k in ('hs_data', 'total_burst', 'hs_payload'):
            note = f"← {'KO longer' if delta_s > 0 else 'OK longer'}"
        print(f"  {k:>15} │ {ok_mean:9.1f} │ {ko_mean:9.1f} │ {delta_s:+9.1f} │ "
              f"{delta_ns:+8.1f} │ {delta_bytes:+9.1f} │ {note}")

    # Key metric: hs_data difference
    ok_data = np.mean([pa.durations_samp['hs_data'] for pa in results_ok])
    ko_data = np.mean([pa.durations_samp['hs_data'] for pa in results_ko])
    delta = ko_data - ok_data
    delta_ns_val = delta * dt_ns
    delta_bytes_val = delta_ns_val * 1e-9 * cfg.data_rate_mbps * 1e6 * cfg.num_lanes / 8.0

    print(f"\n  ┌─────────────────────────────────────────────────────────────┐")
    print(f"  │  KEY RESULT                                                 │")
    print(f"  │  HS DATA: KO − OK = {delta:+.1f} samp = {delta_ns_val:+.1f} ns = {delta_bytes_val:+.1f} bytes    │")
    wc_ok = estimate_payload_bytes(int(ok_data), dt_ns, cfg)
    wc_ko = estimate_payload_bytes(int(ko_data), dt_ns, cfg)
    print(f"  │  WC_payload(OK) ≈ {wc_ok:.0f} B,  WC_payload(KO) ≈ {wc_ko:.0f} B          │")
    if delta_bytes_val > 1:
        print(f"  │  → KO sends ~{delta_bytes_val:.1f} extra bytes/packet → PIXEL_LONG_LINE  │")
    print(f"  └─────────────────────────────────────────────────────────────┘")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='D-PHY CSI-2 packet analyzer')
    parser.add_argument('--ko', required=True, help='Path to KO CSV file')
    parser.add_argument('--ok', required=True, help='Path to OK CSV file')
    parser.add_argument('--clock', type=float, default=340.0, help='MIPI clock MHz (default: 340)')
    parser.add_argument('--lanes', type=int, default=2, help='Number of data lanes (default: 2)')
    parser.add_argument('--sample-rate', type=float, default=500.0, help='Sample rate MSa/s (default: 500)')
    parser.add_argument('--packets', type=int, default=10, help='Number of packets to analyze (default: 10)')
    parser.add_argument('--max-samples', type=int, default=10_000_000,
                        help='Max CSV samples to load (default: 10M)')
    args = parser.parse_args()

    cfg = DphyConfig(
        clock_mhz=args.clock,
        num_lanes=args.lanes,
        sample_rate_msa=args.sample_rate,
    )

    # Print D-PHY spec limits
    spec = cfg.spec_limits()
    print(f"\nD-PHY v3.0 spec limits at {cfg.data_rate_mbps} Mbps/lane (UI = {cfg.ui_ns:.3f} ns):")
    for k, v in spec.items():
        print(f"  {k:30s} = {v:.1f}")

    # Analyze OK
    results_ok = analyze_file(args.ok, cfg, n_packets=args.packets,
                              max_samples=args.max_samples, label="OK")
    dt_ns = 1000.0 / cfg.sample_rate_msa
    print_visual(results_ok, dt_ns, cfg, "OK")

    # Analyze KO
    results_ko = analyze_file(args.ko, cfg, n_packets=args.packets,
                              max_samples=args.max_samples, label="KO")
    print_visual(results_ko, dt_ns, cfg, "KO")

    # Compare
    compare(results_ok, results_ko, dt_ns, cfg)


if __name__ == '__main__':
    main()
