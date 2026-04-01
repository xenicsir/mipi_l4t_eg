#!/usr/bin/env python3
"""
Verify a merged device tree DTB after applying camera overlays.

Usage: verify_dt.py <dtb_path> <camera> <port> [l4t_mode]

Checks performed:
  1. DTB is parseable by dtc
  2. Camera node (matched by node-name pattern) is active (not disabled)
  3. No active rbpcv2_imx219 nodes
  4. No active rbpcv3_imx477 nodes
  5. NVCSI channel@{port}/endpoint@0 has expected bus-width

Exits 0 with "PASS: ..." if all checks pass.
Exits 1 with "FAIL: ..." on first failure.
"""
import sys
import re
import subprocess

# Camera -> node name search pattern in merged DTS
CAMERA_NODE = {
    "Dione":        "xenics_dione",
    "MicroCube":    "eg_ec",
    "MicroCube640": "eg_ec",
    "SmartIR640":   "eg_ec",
    "Crius1280":    "eg_ec",
    "iLumos":       "ilumos",
    "Microlynx":    "microlynx",
}

# Expected bus-width value (NVCSI channel endpoint, 0-indexed port)
CAMERA_BUS_WIDTH = {
    "Dione":        2,
    "MicroCube":    1,
    "MicroCube640": 1,
    "SmartIR640":   2,
    "Crius1280":    2,
    "iLumos":       2,
    "Microlynx":    2,
}


def decompile_dtb(dtb_path):
    """Run dtc to decompile DTB → DTS text. Returns (dts_text, error_msg)."""
    r = subprocess.run(
        ["dtc", "-I", "dtb", "-O", "dts", dtb_path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None, r.stderr.strip()
    return r.stdout, None


def _extract_block(text, open_pos):
    """
    Extract a node body starting from open_pos (the '{').
    Returns the content between '{' and the matching '}', exclusive.
    """
    depth = 0
    i = open_pos
    while i < len(text):
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[open_pos + 1:i]
        i += 1
    return text[open_pos + 1:]  # unterminated block (shouldn't happen)


def node_active_in_dts(dts, node_pattern):
    """
    Returns True if any DT node whose name starts with node_pattern is active.

    A node is active when it does NOT have `status = "disabled"` in its body.
    Absent status property is treated as "okay" per the DT spec.

    This mirrors the awk logic in `_camera_node_active_in_dtb` in the script.
    The regex requires `{` immediately after the node name (preventing matches
    inside string property values which end with `"` not `{`).
    """
    pat = re.escape(node_pattern)
    for m in re.finditer(pat + r'[^{;\n]*\{', dts):
        # m.end()-1 is the position of the opening '{' of the node body
        open_brace = m.end() - 1
        body = _extract_block(dts, open_brace)
        # Check for explicit status = "disabled" anywhere in the (immediate) body.
        # Only look at depth-1 (not nested sub-nodes) to avoid mismatches.
        # Simple approach: search for the pattern at depth 1 within the body.
        if not _is_body_disabled(body):
            return True
    return False


def _is_body_disabled(body):
    """
    Returns True if the node body (string) contains `status = "disabled"` at
    depth 1 (immediate property, not inside a nested sub-node).
    """
    depth = 0
    i = 0
    while i < len(body):
        c = body[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif depth == 0 and body[i:i+6] == 'status':
            line_end = body.find('\n', i)
            line = body[i:line_end] if line_end != -1 else body[i:]
            if '"disabled"' in line:
                return True
        i += 1
    return False


def get_nvcsi_bus_width(dts, port, l4t_mode="36x"):
    """
    Find the bus-width value in NVCSI channel@{port}/ports/port@0/endpoint@N.

    Endpoint numbering convention differs by L4T generation:
      - 36.x: endpoint@{port*2} (overlays override existing endpoints)
      - 35.x: endpoint@0 for all channels (overlays create new endpoints)

    Returns the integer bus-width, or None if the node can't be found.
    """
    nvcsi_m = re.search(r'nvcsi@15a00000\s*\{', dts)
    if not nvcsi_m:
        return None

    nvcsi_body = _extract_block(dts, nvcsi_m.end() - 1)

    # Find channel@{port} within nvcsi body
    ch_m = re.search(r'channel@' + str(port) + r'\s*\{', nvcsi_body)
    if not ch_m:
        return None

    ch_body = _extract_block(nvcsi_body, ch_m.end() - 1)

    # Select endpoint index based on L4T convention
    ep_idx = port * 2 if l4t_mode == "36x" else 0

    port0_m = re.search(r'port@0\s*\{', ch_body)
    if port0_m:
        port0_body = _extract_block(ch_body, port0_m.end() - 1)
        # Try the canonical endpoint first
        ep_m = re.search(r'endpoint@' + str(ep_idx) + r'\s*\{', port0_body)
        if ep_m:
            ep_body = _extract_block(port0_body, ep_m.end() - 1)
            bw_m = re.search(r'bus-width\s*=\s*<(0x[0-9a-fA-F]+|\d+)>', ep_body)
            if bw_m:
                val = bw_m.group(1)
                return int(val, 16) if val.startswith('0x') else int(val)
        # Fallback: first endpoint with a bus-width property
        for ep_m in re.finditer(r'endpoint@\d+\s*\{', port0_body):
            ep_body = _extract_block(port0_body, ep_m.end() - 1)
            bw_m = re.search(r'bus-width\s*=\s*<(0x[0-9a-fA-F]+|\d+)>', ep_body)
            if bw_m:
                val = bw_m.group(1)
                return int(val, 16) if val.startswith('0x') else int(val)

    return None


def main():
    if len(sys.argv) < 4:
        print("Usage: verify_dt.py <dtb_path> <camera> <port> [l4t_mode]")
        sys.exit(2)

    dtb_path = sys.argv[1]
    camera   = sys.argv[2]
    port     = int(sys.argv[3])
    l4t_mode = sys.argv[4] if len(sys.argv) > 4 else "36x"

    checks = []

    # --- Check 1: DTB parseable ---
    dts, err = decompile_dtb(dtb_path)
    if dts is None:
        print(f"FAIL: DTB not parseable: {err}")
        sys.exit(1)
    checks.append("parseable=ok")

    # --- Check 2: Camera node active ---
    node_pat = CAMERA_NODE.get(camera)
    if node_pat:
        if node_active_in_dts(dts, node_pat):
            checks.append("camera_node=ok")
        else:
            checks.append(f"camera_node=FAIL (no active '{node_pat}' node)")
            print("FAIL: " + ", ".join(checks))
            sys.exit(1)
    else:
        checks.append("camera_node=skip (unknown camera)")

    # --- Check 3: No active IMX219 ---
    if node_active_in_dts(dts, "rbpcv2_imx219"):
        checks.append("no_imx219=FAIL (active IMX219 node found)")
        print("FAIL: " + ", ".join(checks))
        sys.exit(1)
    checks.append("no_imx219=ok")

    # --- Check 4: No active IMX477 ---
    if node_active_in_dts(dts, "rbpcv3_imx477"):
        checks.append("no_imx477=FAIL (active IMX477 node found)")
        print("FAIL: " + ", ".join(checks))
        sys.exit(1)
    checks.append("no_imx477=ok")

    # --- Check 5: Correct bus-width in NVCSI channel ---
    expected_bw = CAMERA_BUS_WIDTH.get(camera)
    if expected_bw is not None:
        actual_bw = get_nvcsi_bus_width(dts, port, l4t_mode)
        if actual_bw is None:
            checks.append(f"bus_width=skip (channel@{port} not found in nvcsi)")
        elif actual_bw == expected_bw:
            checks.append(f"bus_width={actual_bw}ok")
        else:
            checks.append(
                f"bus_width=FAIL (expected {expected_bw} got {actual_bw})"
            )
            print("FAIL: " + ", ".join(checks))
            sys.exit(1)

    print("PASS: " + ", ".join(checks))
    sys.exit(0)


if __name__ == "__main__":
    main()
