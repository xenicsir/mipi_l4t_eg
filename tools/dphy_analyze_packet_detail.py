#!/usr/bin/env python3
"""
D-PHY single-packet detail analyzer — visual output.

Usage:
  python3 analyze_dphy_packet_detail.py FILE.csv --packet 5
  python3 analyze_dphy_packet_detail.py FILE.csv --timestamp 16.670  # in ms
  python3 analyze_dphy_packet_detail.py FILE.csv --packet 5 --clock 340 --sample-rate 500
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


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='D-PHY single-packet detail analyzer')
    parser.add_argument('csv', help='Path to PicoScope CSV file')
    parser.add_argument('--packet', type=int, default=1, help='Packet number (1-based, default: 1)')
    parser.add_argument('--timestamp', type=float, default=None, help='Timestamp in ms (overrides --packet)')
    parser.add_argument('--clock', type=float, default=340.0, help='MIPI clock MHz (default: 340)')
    parser.add_argument('--lanes', type=int, default=2, help='Number of data lanes (default: 2)')
    parser.add_argument('--sample-rate', type=float, default=500.0, help='Sample rate MSa/s (default: 500)')
    parser.add_argument('--max-samples', type=int, default=20_000_000, help='Max samples to load')
    args = parser.parse_args()

    dt_ns = 1000.0 / args.sample_rate
    dt_ms = dt_ns / 1e6

    if args.timestamp is not None:
        # Load around timestamp
        df, offset = load_around_timestamp(args.csv, args.timestamp, margin_samples=15000, dt_ms=dt_ms)
        data = df['A'].values
        t = df['t'].values
        print(f"Loaded {len(data)} samples around t={args.timestamp} ms (offset={offset})")
        bursts = find_bursts(data)
        if not bursts:
            print("No bursts found in this region!")
            sys.exit(1)
        # Find burst closest to timestamp
        target_sample = int(args.timestamp / dt_ms) - offset
        best = min(bursts, key=lambda b: abs(b[0] - target_sample))
        bs, be, bdur = best
        print(f"Nearest burst at sample {bs} (t={t[bs]:.8f} ms), duration={bdur} samp")
    else:
        # Load and find N-th burst
        df = load_samples(args.csv, max_samples=args.max_samples)
        data = df['A'].values
        t = df['t'].values
        print(f"Loaded {len(data):,} samples")
        bursts = find_bursts(data)
        print(f"Found {len(bursts)} HS bursts")
        pkt_idx = args.packet - 1  # 0-based
        if pkt_idx < 0 or pkt_idx >= len(bursts):
            print(f"Packet {args.packet} out of range (1–{len(bursts)})")
            sys.exit(1)
        bs, be, bdur = bursts[pkt_idx]
        print(f"Packet {args.packet}: burst at samples {bs}–{be}, duration={bdur} samp, "
              f"t={t[bs]:.8f} ms")

    # Analyze phases
    phases = analyze_phases(data, t, bs, be, dt_ns)

    # Print detail
    print_detail(data, t, phases, dt_ns, args.clock, args.lanes)


if __name__ == '__main__':
    main()
