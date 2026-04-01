#!/usr/bin/env python3
"""
Camera Format Benchmark Analysis Tool
Analyzes tegrastats output from benchmark tests and generates summary tables
"""

import re
import sys
from pathlib import Path

def parse_tegrastats_file(filepath):
    """Parse a tegrastats output file and extract metrics"""
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return None

    cpu_values = []
    vdd_values = []
    temp_values = []
    gr3d_values = []

    for line in lines:
        if 'CPU [' in line:
            # Extract CPU [a%,b%,c%,d%]
            match = re.search(r'CPU \[(\d+)%@[\d]+,(\d+)%@[\d]+,(\d+)%@[\d]+,(\d+)%@[\d]+', line)
            if match:
                cores = [int(match.group(i)) for i in range(1, 5)]
                cpu_values.extend(cores)

            # Extract VDD_CPU_GPU_CV
            match = re.search(r'VDD_CPU_GPU_CV (\d+)mW', line)
            if match:
                vdd_values.append(int(match.group(1)))

            # Extract GR3D_FREQ
            match = re.search(r'GR3D_FREQ (\d+)%', line)
            if match:
                gr3d_values.append(int(match.group(1)))

            # Extract temperature
            match = re.search(r'cpu@([\d.]+)C', line)
            if match:
                temp_values.append(float(match.group(1)))

    if not cpu_values:
        return None

    return {
        'cpu_min': min(cpu_values),
        'cpu_max': max(cpu_values),
        'cpu_avg': sum(cpu_values) / len(cpu_values),
        'vdd_min': min(vdd_values) if vdd_values else 0,
        'vdd_max': max(vdd_values) if vdd_values else 0,
        'vdd_avg': sum(vdd_values) / len(vdd_values) if vdd_values else 0,
        'gr3d_min': min(gr3d_values) if gr3d_values else 0,
        'gr3d_max': max(gr3d_values) if gr3d_values else 0,
        'gr3d_avg': sum(gr3d_values) / len(gr3d_values) if gr3d_values else 0,
        'temp_min': min(temp_values) if temp_values else 0,
        'temp_max': max(temp_values) if temp_values else 0,
        'temp_avg': sum(temp_values) / len(temp_values) if temp_values else 0,
    }

def analyze_directory(directory):
    """Analyze all benchmark files in a directory"""
    results = {}
    baseline = None

    print(f"\nAnalyzing benchmark files in: {directory}\n")

    # First, process baseline
    baseline_file = Path(directory) / "baseline.txt"
    if baseline_file.exists():
        baseline = parse_tegrastats_file(str(baseline_file))
        if baseline:
            print("=" * 70)
            print("BASELINE (System at Rest)")
            print("=" * 70)
            print(f"CPU:  {baseline['cpu_min']}-{baseline['cpu_max']}% avg={baseline['cpu_avg']:.1f}%")
            print(f"GPU:  {baseline['gr3d_min']}-{baseline['gr3d_max']}% avg={baseline['gr3d_avg']:.1f}%")
            print(f"PWR:  {baseline['vdd_min']}-{baseline['vdd_max']}mW avg={baseline['vdd_avg']:.0f}mW")
            print(f"TMP:  {baseline['temp_min']:.2f}-{baseline['temp_max']:.2f}°C avg={baseline['temp_avg']:.2f}°C")
            print()

    # Process test files
    for test_file in sorted(Path(directory).glob("test*.txt")):
        data = parse_tegrastats_file(str(test_file))
        if data:
            # Extract test and format from filename (e.g., test1_YUYV.txt)
            name = test_file.stem
            results[name] = data

            print(f"{name}:")
            print(f"  CPU:  {data['cpu_min']}-{data['cpu_max']}% (avg={data['cpu_avg']:.1f}%)")
            print(f"  GPU:  {data['gr3d_min']}-{data['gr3d_max']}% (avg={data['gr3d_avg']:.1f}%)")
            print(f"  PWR:  {data['vdd_min']}-{data['vdd_max']}mW (avg={data['vdd_avg']:.0f}mW)")
            print(f"  TMP:  {data['temp_min']:.2f}-{data['temp_max']:.2f}°C (avg={data['temp_avg']:.2f}°C)")

            # Calculate overhead vs baseline
            if baseline:
                cpu_overhead = data['cpu_avg'] - baseline['cpu_avg']
                pwr_overhead = data['vdd_avg'] - baseline['vdd_avg']
                print(f"  Overhead: CPU +{cpu_overhead:.1f}% PWR +{pwr_overhead:.0f}mW")
            print()

    # Generate markdown table
    print("\n" + "=" * 70)
    print("MARKDOWN TABLE FORMAT")
    print("=" * 70)
    print("\n| Test | Format | CPU Min-Max | CPU Avg | PWR | GPU |\n")
    print("|------|--------|-------------|---------|-----|-----|\n")

    for test_name in sorted(results.keys()):
        data = results[test_name]
        # Parse test name
        parts = test_name.split('_')
        test_id = parts[0] if len(parts) > 0 else "?"
        fmt = parts[1] if len(parts) > 1 else "?"

        print(f"| {test_id} | {fmt} | {data['cpu_min']}-{data['cpu_max']}% | ~{data['cpu_avg']:.0f}% | {data['vdd_avg']:.0f}mW | {data['gr3d_avg']:.0f}% |")

def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_benchmark.py <results_directory>")
        print("\nExample:")
        print("  python3 analyze_benchmark.py /tmp/benchmark_results")
        sys.exit(1)

    results_dir = sys.argv[1]
    if not Path(results_dir).is_dir():
        print(f"Error: {results_dir} is not a directory")
        sys.exit(1)

    analyze_directory(results_dir)

if __name__ == '__main__':
    main()
