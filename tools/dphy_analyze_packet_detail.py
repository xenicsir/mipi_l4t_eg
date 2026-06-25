#!/usr/bin/env python3
"""
D-PHY analyzer — packet detail and global recording analysis.

Usage:
  python3 dphy_analyze_packet_detail.py FILE.csv --packet 5
  python3 dphy_analyze_packet_detail.py FILE.csv --timestamp 16.670  # in ms
  python3 dphy_analyze_packet_detail.py FILE.csv --packet 5 --clock 340 --sample-rate 500

  python3 dphy_analyze_packet_detail.py FILE.csv --global
  python3 dphy_analyze_packet_detail.py FILE.csv --global --expected-lines 1024
  python3 dphy_analyze_packet_detail.py FILE.csv --global --interframe-gap 100
"""

import argparse
import numpy as np
import pandas as pd
import sys

# ─── Configuration ──────────────────────────────────────────────────────────

def spec_limits(ui_ns):
    return {
        'T_LPX_min':          50.0,
        'T_HS_PREPARE_min':   40.0 + 4 * ui_ns,
        'T_HS_PREPARE_max':   85.0 + 6 * ui_ns,
        'T_HS_PREP_ZERO_min': 145.0 + 10 * ui_ns,
        'T_HS_TRAIL_min':     max(8 * ui_ns, 60.0 + 4 * ui_ns),
        'T_HS_EXIT_min':      100.0,
        'T_HS_SYNC_ns':       8 * ui_ns,
    }

# ─── CSV loading ────────────────────────────────────────────────────────────

def load_csv(path, offset=0, count=0):
    kwargs = dict(sep=';', decimal=',', header=0, skiprows=1 + offset,
                  names=['t', 'A', 'B'], dtype=np.float64)
    if count > 0:
        kwargs['nrows'] = count
    return pd.read_csv(path, **kwargs)

def load_around_timestamp(path, t_ms, margin_samples=15000, dt_ms=0.000002):
    """Load samples around a given timestamp (ms)."""
    sample_idx = int(t_ms / dt_ms)
    start = max(0, sample_idx - margin_samples)
    count = margin_samples * 2
    return load_csv(path, offset=start, count=count), start

def load_samples(path, max_samples=20_000_000):
    return load_csv(path, count=max_samples)

# ─── Burst finder ───────────────────────────────────────────────────────────

def find_bursts(data, threshold=0.60, min_dur=500):
    below = (data < threshold).astype(np.int8)
    tr = np.diff(below)
    starts = np.where(tr == 1)[0] + 1
    ends = np.where(tr == -1)[0] + 1
    if len(ends) > 0 and (len(starts) == 0 or ends[0] < starts[0]):
        ends = ends[1:]
    if len(starts) > len(ends):
        starts = starts[:len(ends)]
    return [(s, e, e - s) for s, e in zip(starts, ends) if e - s >= min_dur]

# ─── Phase analysis ─────────────────────────────────────────────────────────

def analyze_phases(data, t, burst_start, burst_end, dt_ns):
    """
    Detailed phase analysis of a single packet.
    Returns dict with phase boundaries and sample-level data.
    """
    result = {}

    # ── 1. LP-11 end: scan backward from burst_start
    idx = burst_start
    while idx > 0 and data[idx] < 0.90:
        idx -= 1
    lp11_end = idx
    result['lp11_end'] = lp11_end

    # ── 2. LP-00 region: find where signal reaches near-0V
    idx = lp11_end
    while idx < burst_end and data[idx] > 0.10:
        idx += 1
    lp00_start = idx

    # Find end of LP-00 (where signal rises above ~0.15V heading to HS)
    idx = lp00_start
    while idx < burst_end and data[idx] < 0.15:
        idx += 1
    lp00_end = idx

    result['lp00_start'] = lp00_start
    result['lp00_end'] = lp00_end

    # ── 3. HS-ZERO: find where signal reaches stable ~0.4V+
    # Scan forward until signal is above 0.35V
    idx = lp00_end
    while idx < burst_end and data[idx] < 0.35:
        idx += 1
    hs_zero_start = idx
    result['hs_zero_start'] = hs_zero_start

    # ── 4. HS-ZERO end → SoT/DATA start: detect variance change
    # Use rolling window std
    win = 12
    segment = data[hs_zero_start:burst_end]
    rolling_std = np.array([
        np.std(segment[max(0, i - win):i + 1]) for i in range(len(segment))
    ])

    # HS-ZERO: std < 0.035 (very stable ~0.48V)
    # SoT/DATA: std > 0.05 (bits alternating)
    std_thresh = 0.04
    hs_zero_end = hs_zero_start + len(segment) - 1
    for i in range(win, len(rolling_std) - 2):
        if rolling_std[i] > std_thresh and rolling_std[i + 1] > std_thresh:
            hs_zero_end = hs_zero_start + i - win // 2  # back up half window
            break
    result['hs_zero_end'] = hs_zero_end
    result['hs_data_start'] = hs_zero_end

    # ── 5. HS DATA end / Trail start: scan backward from burst_end
    # Trail = constant HS level after data ends
    # Look for where variance drops near end of burst
    search_start = max(hs_zero_end + 100, burst_end - 300)
    seg_end = data[search_start:burst_end + 50]
    if len(seg_end) > win * 2:
        rstd_end = np.array([
            np.std(seg_end[max(0, i - win):i + 1]) for i in range(len(seg_end))
        ])
        # Find last point where std is high (= still in DATA), then transition to low
        in_data = rstd_end > std_thresh
        hs_data_end_rel = len(seg_end) - 1
        for i in range(len(in_data) - 1, 0, -1):
            if in_data[i]:
                hs_data_end_rel = i
                break
        result['hs_data_end'] = search_start + hs_data_end_rel
    else:
        result['hs_data_end'] = burst_end - 20

    result['trail_start'] = result['hs_data_end']

    # ── 6. Trail end / HS-EXIT start: where signal starts rising above 0.60V toward LP-11
    idx = burst_end  # burst_end is already the 0.6V crossing
    result['trail_end'] = burst_end

    # ── 7. LP-11 resume
    idx = burst_end
    limit = min(len(data), burst_end + 300)
    while idx < limit and data[idx] < 0.90:
        idx += 1
    result['lp11_resume'] = idx

    return result

# ─── Visual output ──────────────────────────────────────────────────────────

def print_detail(data, t, phases, dt_ns, clock_mhz, num_lanes):
    data_rate = clock_mhz * 2  # Mbps/lane
    ui_ns = 1000.0 / data_rate
    spec = spec_limits(ui_ns)

    p = phases
    labels = [
        ('LP-11 → fall',    p['lp11_end'],      p['lp00_start']),
        ('LP-00 flat',      p['lp00_start'],     p['lp00_end']),
        ('HS rise',         p['lp00_end'],       p['hs_zero_start']),
        ('HS-ZERO',         p['hs_zero_start'],  p['hs_zero_end']),
        ('HS DATA',         p['hs_data_start'],  p['hs_data_end']),
        ('Trail',           p['trail_start'],    p['trail_end']),
        ('HS-EXIT → LP-11', p['trail_end'],      p['lp11_resume']),
    ]

    # ─── Header ───
    print(f"\n{'═' * 90}")
    print(f"  D-PHY PACKET DETAIL")
    print(f"  Clock: {clock_mhz} MHz, {num_lanes} lanes, {data_rate} Mbps/lane, UI = {ui_ns:.3f} ns")
    print(f"  Sample rate: {1000/dt_ns:.0f} MSa/s, dt = {dt_ns:.1f} ns")
    print(f"{'═' * 90}")

    # ─── Phase summary ───
    print(f"\n  {'Phase':>17} │ {'Start':>7} │ {'End':>7} │ {'Samp':>6} │ {'Time (ns)':>10} │ "
          f"{'Bits/lane':>10} │ {'Spec check'}")
    print(f"  {'─' * 17}─┼{'─' * 9}┼{'─' * 9}┼{'─' * 8}┼{'─' * 12}┼{'─' * 12}┼{'─' * 30}")

    for name, s, e in labels:
        dur_s = e - s
        dur_ns = dur_s * dt_ns
        dur_bits = dur_ns / ui_ns
        check = ''
        if 'LP-00' in name:
            if dur_ns < spec['T_HS_PREPARE_min']:
                check = f'< min {spec["T_HS_PREPARE_min"]:.1f} ns'
            elif dur_ns > spec['T_HS_PREPARE_max']:
                check = f'> max {spec["T_HS_PREPARE_max"]:.1f} ns'
            else:
                check = 'OK'
        elif 'Trail' in name:
            if dur_ns >= spec['T_HS_TRAIL_min']:
                check = 'OK'
            else:
                check = f'< min {spec["T_HS_TRAIL_min"]:.1f} ns'
        elif 'EXIT' in name:
            if dur_ns >= spec['T_HS_EXIT_min']:
                check = 'OK'
            else:
                check = f'< min {spec["T_HS_EXIT_min"]:.1f} ns'
        print(f"  {name:>17} │ {s:7d} │ {e:7d} │ {dur_s:6d} │ {dur_ns:10.1f} │ "
              f"{dur_bits:10.1f} │ {check}")

    total_s = p['lp11_resume'] - p['lp11_end']
    total_ns = total_s * dt_ns
    print(f"  {'─' * 17}─┼{'─' * 9}┼{'─' * 9}┼{'─' * 8}┼{'─' * 12}┼{'─' * 12}┼{'─' * 30}")
    print(f"  {'TOTAL':>17} │ {p['lp11_end']:7d} │ {p['lp11_resume']:7d} │ {total_s:6d} │ {total_ns:10.1f} │ "
          f"{'':>10} │")

    # Combined check
    prep_ns = (p['lp00_end'] - p['lp00_start']) * dt_ns
    zero_ns = (p['hs_zero_end'] - p['lp00_end']) * dt_ns
    comb = prep_ns + zero_ns
    comb_ok = 'OK' if comb >= spec['T_HS_PREP_ZERO_min'] else 'BELOW MIN'
    print(f"\n  T_HS-PREPARE + T_HS-ZERO = {prep_ns:.1f} + {zero_ns:.1f} = {comb:.1f} ns "
          f"(spec ≥ {spec['T_HS_PREP_ZERO_min']:.1f} ns) [{comb_ok}]")

    # Payload estimate
    hs_data_samp = p['hs_data_end'] - p['hs_data_start']
    hs_data_ns = hs_data_samp * dt_ns
    bits_per_lane = hs_data_ns * data_rate / 1000.0
    sot_bits = 8
    overhead_bytes = 6  # header(4) + CRC(2)
    wc = (bits_per_lane - sot_bits) / 8.0 * num_lanes - overhead_bytes
    print(f"  Estimated WC payload: {wc:.1f} bytes ({wc/2:.0f} pixels RAW16)")

    # ─── Visual waveform with sample-level detail at key transitions ───
    print(f"\n  ─── Sample-level detail at transitions ───")

    transitions = [
        ('LP-11→fall',   p['lp11_end'] - 3,    p['lp00_start'] + 3, '▼ LP entry'),
        ('LP-00→HS',     p['lp00_end'] - 3,     p['hs_zero_start'] + 5, '▲ HS driver ON'),
        ('HS-ZERO→SoT',  p['hs_zero_end'] - 8,  p['hs_zero_end'] + 15, '◆ SoT 0xB8 onset'),
        ('DATA→Trail',   p['hs_data_end'] - 10, p['trail_end'] + 3, '▼ Trail'),
        ('Trail→LP-11',  p['trail_end'] - 3,    p['lp11_resume'] + 3, '▲ LP-11 resume'),
    ]

    for label, s, e, desc in transitions:
        s = max(0, s)
        e = min(len(data) - 1, e)
        if s >= e:
            continue
        print(f"\n  {desc}  ({label}, samples {s}–{e}):")
        print(f"  {'Sample':>7} │ {'t (ms)':>14} │ {'V':>7} │ {'Bar':>30}")
        print(f"  {'─' * 7}─┼{'─' * 16}┼{'─' * 9}┼{'─' * 30}")
        for i in range(s, e + 1):
            if i < 0 or i >= len(data):
                continue
            v = data[i]
            bar_len = int(v / 0.05)
            bar = '█' * min(bar_len, 25)
            # Mark phase boundaries
            marker = ''
            if i == p['lp11_end']:
                marker = ' ← LP-11 end'
            elif i == p['lp00_start']:
                marker = ' ← LP-00 start'
            elif i == p['lp00_end']:
                marker = ' ← LP-00 end'
            elif i == p['hs_zero_start']:
                marker = ' ← HS-ZERO start'
            elif i == p['hs_zero_end']:
                marker = ' ← HS-ZERO end'
            elif i == p['hs_data_end']:
                marker = ' ← DATA end'
            elif i == p['trail_end']:
                marker = ' ← Trail end'
            elif i == p['lp11_resume']:
                marker = ' ← LP-11 resume'
            print(f"  {i:7d} │ {t[i]:14.8f} │ {v:7.4f} │ {bar}{marker}")


# ─── Streaming burst scanner (global analysis of large files) ────────────────

def scan_bursts_streaming(path, dt_ns=2.0, enter_hs=0.50, enter_lp=1.00, debounce=3):
    """
    Full-file streaming burst detector using LP/HS hysteresis.
    LP→HS : VA drops below enter_hs (catches LP-00 entry + HS data)
    HS→LP : VA rises above enter_lp (LP-11 return)
    Returns (bursts, total_ns) where bursts = list of (start_ns, dur_ns).
    """
    state = 'LP'
    consec = 0
    candidate = 'LP'
    hs_start = 0
    sample_idx = 0
    bursts = []

    with open(path, 'r') as f:
        for line in f:
            if not line.strip() or ';' not in line:
                continue
            parts = line.split(';')
            if len(parts) < 2:
                continue
            try:
                v = float(parts[1].replace(',', '.'))
            except ValueError:
                continue

            sample_idx += 1
            if sample_idx % 5_000_000 == 0:
                print(f"  {sample_idx // 1_000_000}M samples...", flush=True)

            if state == 'LP' and v < enter_hs:
                cand = 'HS'
            elif state == 'HS' and v > enter_lp:
                cand = 'LP'
            else:
                cand = state

            if cand != state:
                if cand == candidate:
                    consec += 1
                else:
                    candidate = cand
                    consec = 1
                if consec >= debounce:
                    if state == 'LP':
                        hs_start = sample_idx
                    else:
                        bursts.append((int(hs_start * dt_ns), int((sample_idx - hs_start) * dt_ns)))
                    state = cand
                    consec = 0
                    candidate = cand
            else:
                candidate = cand
                consec = 0

    return bursts, sample_idx * dt_ns


# ─── Global analysis ─────────────────────────────────────────────────────────

_SHORT_MAX_NS = 1_000   # < 1 µs → short packet (SoF/EoF)
_LONG_MIN_NS  = 3_000   # ≥ 3 µs → long packet (line data)


def _autodetect_interframe_gap(classified):
    """
    Detect the EoF→SoF inter-frame gap from consecutive short-packet pairs.

    Scans for adjacent short bursts with no long burst between them.
    These represent EoF (end of frame N) followed by SoF (start of frame N+1).
    Returns half the minimum gap found, to be used as the frame split threshold.
    Returns None if no such pairs found.
    """
    eof_sof_gaps_ns = []
    for i in range(len(classified) - 1):
        a, b = classified[i], classified[i + 1]
        if a['kind'] == 'short' and b['kind'] == 'short':
            gap_ns = b['start_ns'] - a['end_ns']
            if gap_ns > 0:
                eof_sof_gaps_ns.append(gap_ns)
    if not eof_sof_gaps_ns:
        return None
    min_gap_ns = min(eof_sof_gaps_ns)
    # Split threshold = midpoint between 0 and EoF→SoF gap
    return min_gap_ns // 2


def _classify_and_group(bursts, short_max_ns=_SHORT_MAX_NS, long_min_ns=_LONG_MIN_NS,
                        interframe_gap_us=None):
    """
    Classify bursts and group them into frame groups by inter-frame gap.

    If interframe_gap_us is None (default), the EoF→SoF gap is auto-detected
    from consecutive short-packet pairs, so SoF and its lines are correctly
    grouped even when the inter-frame blanking is only a few µs.
    """
    classified = []
    for start_ns, dur_ns in bursts:
        if dur_ns < short_max_ns:
            kind = 'short'
        elif dur_ns >= long_min_ns:
            kind = 'long'
        else:
            kind = 'mid'
        classified.append({'start_ns': start_ns, 'end_ns': start_ns + dur_ns,
                            'dur_ns': dur_ns, 'kind': kind})

    if interframe_gap_us is None:
        auto_ns = _autodetect_interframe_gap(classified)
        if auto_ns is not None:
            interframe_gap_ns = auto_ns
            print(f"  Auto-detected EoF→SoF gap: ~{auto_ns*2/1000:.1f} µs  "
                  f"→ using split threshold {auto_ns/1000:.1f} µs")
        else:
            interframe_gap_ns = 50_000   # 50 µs fallback
            print(f"  No EoF→SoF pair found, using fallback threshold 50 µs")
    else:
        interframe_gap_ns = interframe_gap_us * 1_000

    frames = []
    if classified:
        cur = [classified[0]]
        for b in classified[1:]:
            if b['start_ns'] - cur[-1]['end_ns'] >= interframe_gap_ns:
                frames.append(cur)
                cur = [b]
            else:
                cur.append(b)
        frames.append(cur)

    return classified, frames


def _frame_stats(frame_bursts):
    n_long  = sum(1 for b in frame_bursts if b['kind'] == 'long')
    n_short = sum(1 for b in frame_bursts if b['kind'] == 'short')
    n_mid   = sum(1 for b in frame_bursts if b['kind'] == 'mid')
    has_sof = bool(frame_bursts) and frame_bursts[0]['kind'] == 'short'
    has_eof = (len(frame_bursts) > 1 and frame_bursts[-1]['kind'] == 'short')
    return dict(n_long=n_long, n_short=n_short, n_mid=n_mid,
                has_sof=has_sof, has_eof=has_eof,
                start_ns=frame_bursts[0]['start_ns'],
                end_ns=frame_bursts[-1]['end_ns'])


def print_global_analysis(classified, frames, total_ns, expected_lines=None):
    from collections import Counter

    n_short = sum(1 for b in classified if b['kind'] == 'short')
    n_long  = sum(1 for b in classified if b['kind'] == 'long')
    n_mid   = sum(1 for b in classified if b['kind'] == 'mid')
    W = 82

    print(f"\n{'═' * W}")
    print(f"  GLOBAL RECORDING ANALYSIS")
    print(f"{'═' * W}")
    print(f"  Total duration : {total_ns / 1e6:.3f} ms")
    print(f"  Total bursts   : {len(classified):,}"
          f"  ({n_long:,} long, {n_short} short"
          + (f", {n_mid} mid" if n_mid else "") + ")")

    if n_short:
        sd = [b['dur_ns'] for b in classified if b['kind'] == 'short']
        print(f"  Short packets  : {n_short}  —  duration {min(sd):.0f}–{max(sd):.0f} ns"
              f"  (avg {sum(sd)/len(sd):.0f} ns)")
    if n_long:
        ld = [b['dur_ns'] for b in classified if b['kind'] == 'long']
        print(f"  Long packets   : {n_long:,}  —  duration"
              f" {min(ld)/1000:.2f}–{max(ld)/1000:.2f} µs"
              f"  (avg {sum(ld)/len(ld)/1000:.2f} µs)")

    stats = [_frame_stats(f) for f in frames]
    print(f"\n  Frames detected : {len(frames)}")

    sof_times_ns = [s['start_ns'] for s in stats if s['has_sof']]
    if len(sof_times_ns) >= 2:
        period_ns = (sof_times_ns[-1] - sof_times_ns[0]) / (len(sof_times_ns) - 1)
        fps = 1e9 / period_ns
        print(f"  FPS (SoF→SoF)  : {fps:.1f}  ({period_ns / 1e6:.3f} ms/frame)")

    # Auto-detect expected line count from inner complete frames
    if expected_lines is None:
        inner_counts = [
            s['n_long'] for i, s in enumerate(stats)
            if s['has_sof'] and 0 < i < len(stats) - 1
        ]
        if inner_counts:
            expected_lines = Counter(inner_counts).most_common(1)[0][0]

    # Per-frame table
    print(f"\n  {'#':>4} │ {'Start (ms)':>10} │ {'Long pkts':>9} │ {'SoF':>4} │ {'EoF':>4} │ Status")
    print(f"  {'─' * 4}─┼{'─' * 12}┼{'─' * 11}┼{'─' * 6}┼{'─' * 6}┼{'─' * 36}")

    for i, (s, frame) in enumerate(zip(stats, frames)):
        sof_mark = '✓' if s['has_sof'] else '✗'
        eof_mark = '✓' if s['has_eof'] else '✗'
        issues = []

        is_first = (i == 0 and not s['has_sof'])
        is_last  = (i == len(stats) - 1)

        if is_first:
            issues.append('truncated (capture start)')
        elif not s['has_sof']:
            issues.append('SoF MISSING')

        if not s['has_eof']:
            if is_last:
                issues.append('truncated (capture end)')
            else:
                issues.append('EoF MISSING')

        if expected_lines and not is_first:
            ref = expected_lines
            if s['n_long'] != ref and not (is_last and s['n_long'] < ref):
                issues.append(f'lines={s["n_long"]} expected {ref}')

        if s['n_mid']:
            issues.append(f'{s["n_mid"]} intermediate-duration burst(s)')

        if not issues:
            issues.append('OK')

        print(f"  {i:4d} │ {s['start_ns']/1e6:10.3f} │ {s['n_long']:9d} │"
              f" {sof_mark:>4} │ {eof_mark:>4} │ {', '.join(issues)}")

    # Summary
    n_with_sof = sum(1 for s in stats if s['has_sof'])
    n_with_eof = sum(1 for s in stats if s['has_eof'])
    n_total    = len(stats)

    inner = stats[1:-1] if len(stats) > 2 else []
    lines_ok = (
        all(s['n_long'] == expected_lines for s in inner)
        if inner and expected_lines else None
    )

    print(f"\n  ─── Summary ─────────────────────────────────────────────────")
    print(f"  SoF present      : {n_with_sof}/{n_total} frames")
    print(f"  EoF present      : {n_with_eof}/{n_total} frames")
    if expected_lines and inner:
        ok = '✓ consistent' if lines_ok else '⚠ inconsistent'
        print(f"  Long pkts/frame  : {expected_lines} (auto-detected)  {ok}")

    problems = []
    inner_no_eof = sum(1 for i, s in enumerate(stats) if not s['has_eof'] and 0 < i < n_total - 1)
    if inner_no_eof:
        problems.append(
            f"EoF missing in {inner_no_eof} complete frame(s) out of {n_total - 2}"
            f" — CSI-2 spec violation: transmitter does not send EoF short packet"
        )
    inner_no_sof = sum(1 for i, s in enumerate(stats) if not s['has_sof'] and i > 0)
    if inner_no_sof:
        problems.append(f"SoF missing in {inner_no_sof} non-truncated frame(s)")
    if lines_ok is False:
        bad = [s['n_long'] for s in inner if s['n_long'] != expected_lines]
        problems.append(f"Inconsistent line count: {Counter(bad).most_common()}")

    if problems:
        print(f"\n  ⚠ ISSUES DETECTED:")
        for p in problems:
            print(f"    • {p}")
    else:
        print(f"\n  ✓ Frame structure is consistent")

    print(f"{'═' * W}\n")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='D-PHY analyzer — packet detail and global recording analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('csv', help='Path to PicoScope CSV file')
    parser.add_argument('--packet', type=int, default=1, help='Packet number (1-based, default: 1)')
    parser.add_argument('--timestamp', type=float, default=None, help='Timestamp in ms (overrides --packet)')
    parser.add_argument('--clock', type=float, default=340.0, help='MIPI clock MHz (default: 340)')
    parser.add_argument('--lanes', type=int, default=2, help='Number of data lanes (default: 2)')
    parser.add_argument('--sample-rate', type=float, default=500.0, help='Sample rate MSa/s (default: 500)')
    parser.add_argument('--max-samples', type=int, default=20_000_000, help='Max samples to load (packet mode)')
    parser.add_argument('--global', dest='global_mode', action='store_true',
                        help='Global recording analysis: frames, SoF/EoF, consistency (full file scan)')
    parser.add_argument('--expected-lines', type=int, default=None,
                        help='Expected long packets per frame (auto-detected if omitted)')
    parser.add_argument('--interframe-gap', type=float, default=None,
                        help='Inter-frame gap threshold in µs (default: auto-detect from EoF→SoF short-packet pairs)')
    args = parser.parse_args()

    dt_ns = 1000.0 / args.sample_rate

    if args.global_mode:
        print(f"Scanning {args.csv} (streaming)...")
        bursts_raw, total_ns = scan_bursts_streaming(args.csv, dt_ns=dt_ns)
        classified, frames = _classify_and_group(
            bursts_raw,
            interframe_gap_us=args.interframe_gap,
        )
        print_global_analysis(classified, frames, total_ns,
                              expected_lines=args.expected_lines)
        return

    dt_ms = dt_ns / 1e6

    if args.timestamp is not None:
        df, offset = load_around_timestamp(args.csv, args.timestamp, margin_samples=15000, dt_ms=dt_ms)
        data = df['A'].values
        t = df['t'].values
        print(f"Loaded {len(data)} samples around t={args.timestamp} ms (offset={offset})")
        bursts = find_bursts(data)
        if not bursts:
            print("No bursts found in this region!")
            sys.exit(1)
        target_sample = int(args.timestamp / dt_ms) - offset
        best = min(bursts, key=lambda b: abs(b[0] - target_sample))
        bs, be, bdur = best
        print(f"Nearest burst at sample {bs} (t={t[bs]:.8f} ms), duration={bdur} samp")
    else:
        df = load_samples(args.csv, max_samples=args.max_samples)
        data = df['A'].values
        t = df['t'].values
        print(f"Loaded {len(data):,} samples")
        bursts = find_bursts(data)
        print(f"Found {len(bursts)} HS bursts")
        pkt_idx = args.packet - 1
        if pkt_idx < 0 or pkt_idx >= len(bursts):
            print(f"Packet {args.packet} out of range (1–{len(bursts)})")
            sys.exit(1)
        bs, be, bdur = bursts[pkt_idx]
        print(f"Packet {args.packet}: burst at samples {bs}–{be}, duration={bdur} samp, "
              f"t={t[bs]:.8f} ms")

    phases = analyze_phases(data, t, bs, be, dt_ns)
    print_detail(data, t, phases, dt_ns, args.clock, args.lanes)


if __name__ == '__main__':
    main()
