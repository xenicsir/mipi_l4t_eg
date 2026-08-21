#!/usr/bin/env python3
"""
verify_dtsi_structure.py — Static verification of EG camera DTSIs.

For each DTSI platform defined in eg_config.yaml:
  1. Brace balance
  2. Presence of each sensor node (per camera × cam_id)
  3. Expected number of modes (taking platform restrictions into account)
  4. Comparison of DT fields per mode:
       mode_type, pixel_phase, csi_pixel_bit_depth,
       discontinuous_clk, line_length, pix_clk_hz, active_w, active_h
  5. For EC cameras (MicroCube, SmartIR640, Crius1280):
       bus-width verification in the cam0 overlay DTS

Usage:
  python3 tools/verify_dtsi_structure.py          # from repo root
  python3 tools/verify_dtsi_structure.py --quiet  # errors only
"""

import re
import sys
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES   = REPO_ROOT / "sources" / "common" / "source"
DB_PATH   = REPO_ROOT / "eg_config.yaml"


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

def load_db():
    with open(DB_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Parsing DTSI
# ---------------------------------------------------------------------------

def read_lines(path):
    with open(path) as f:
        return f.readlines()


def find_block_end(lines, start):
    """Returns the index of the line containing '}' closing the block opened at 'start'."""
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > start:
            return i
    return len(lines) - 1


def strip_comments(text):
    """Removes C comments (/* ... */ and // ...) from a block of text."""
    # Remove /* ... */ (including multi-line)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Remove // to end of line
    text = re.sub(r'//[^\n]*', '', text)
    return text


def extract_field(block_text, field):
    """
    Extracts the value of a DT field (excluding comments):
    field = "value";  or  field = <value>;
    """
    clean = strip_comments(block_text)
    m = re.search(rf'{re.escape(field)}\s*=\s*"([^"]+)"', clean)
    if m:
        return m.group(1)
    m = re.search(rf'{re.escape(field)}\s*=\s*<([^>]+)>', clean)
    if m:
        return m.group(1).strip()
    return None


# Preprocessor macros this static check treats as undefined by default,
# matching the generic/forecr build (only a PRISTINE_KERNEL vendor build,
# e.g. cti, ever defines these). resolve_conditionals() below fully drops
# the unreachable branch's lines up front so brace-balance and mode
# counting downstream see a plain, consistent line list — no per-check
# awareness of the conditional needed elsewhere.
ASSUMED_UNDEFINED_MACROS = {"PRISTINE_KERNEL", "HADRON_DM_CAM_I2C_MUX"}

_IFDEF_RE  = re.compile(r'^\s*#\s*ifdef\s+(\S+)')
_IFNDEF_RE = re.compile(r'^\s*#\s*ifndef\s+(\S+)')
_ELSE_RE   = re.compile(r'^\s*#\s*else\b')
_ENDIF_RE  = re.compile(r'^\s*#\s*endif\b')


def resolve_conditionals(lines):
    """
    Returns a new line list with #ifdef/#ifndef/#else/#endif blocks for
    ASSUMED_UNDEFINED_MACROS fully resolved (as if those macros are
    undefined): only the reachable branch's lines are kept, directives
    themselves dropped. This mirrors what a vendor overlay .dts that
    #defines PRISTINE_KERNEL before #include-ing this dtsi would NOT do
    (the default/generic build never defines it), so it lets a single
    #ifndef line pick between two different node names sharing one body
    (see eg_ec_camN modes) without duplicating the body.

    Blocks for any other macro (CAM0_LANE_SWAP, EG_CSI_22PIN...) are left
    completely untouched (directives and both branches kept as literal
    text) since their state isn't modeled here — matches prior behavior.
    """
    out = []
    stack = []  # each frame: {"tracked": bool, "keep": bool}
    for line in lines:
        m = _IFNDEF_RE.match(line)
        if m:
            tracked = m.group(1) in ASSUMED_UNDEFINED_MACROS
            if tracked:
                stack.append({"tracked": True, "keep": True})  # undefined -> ifndef branch active
            else:
                stack.append({"tracked": False, "keep": True})
                out.append(line)
            continue
        m = _IFDEF_RE.match(line)
        if m:
            tracked = m.group(1) in ASSUMED_UNDEFINED_MACROS
            if tracked:
                stack.append({"tracked": True, "keep": False})  # undefined -> ifdef branch inactive
            else:
                stack.append({"tracked": False, "keep": True})
                out.append(line)
            continue
        if _ELSE_RE.match(line):
            if stack and stack[-1]["tracked"]:
                stack[-1]["keep"] = not stack[-1]["keep"]
            else:
                out.append(line)
            continue
        if _ENDIF_RE.match(line):
            if stack:
                frame = stack.pop()
                if not frame["tracked"]:
                    out.append(line)
            else:
                out.append(line)
            continue
        if any(f["tracked"] and not f["keep"] for f in stack):
            continue
        out.append(line)
    return out


def parse_sensor_nodes(lines):
    """
    Returns dict: label → list of mode dicts (extracted DT fields).
    E.g.: {"microlynx_cam0": [{"active_w": "1024", ...}, ...], ...}

    `lines` is expected to already be resolve_conditionals()-ed.
    """
    LABEL_RE = re.compile(r'((?:dione_ir|eg_ec|ilumos|microlynx)_cam\d)\s*:')
    MODE_RE  = re.compile(r'\bmode\d+\s*\{')
    nodes = {}

    for i, line in enumerate(lines):
        m = LABEL_RE.search(line)
        if not m:
            continue
        label = m.group(1)
        end_node = find_block_end(lines, i)
        node_text = "".join(lines[i:end_node + 1])

        modes = []
        mode_idx = 0
        for j in range(i, end_node + 1):
            if MODE_RE.search(lines[j]):
                end_mode = find_block_end(lines, j)
                mode_text = "".join(lines[j:end_mode + 1])
                mode_comment = lines[j]  # contains the CAMERA_MODE_... comment
                fields = {
                    "_mode_idx":           mode_idx,
                    "_comment":            mode_comment.strip(),
                    "active_w":            extract_field(mode_text, "active_w"),
                    "active_h":            extract_field(mode_text, "active_h"),
                    "mode_type":           extract_field(mode_text, "mode_type"),
                    "pixel_phase":         extract_field(mode_text, "pixel_phase"),
                    "csi_pixel_bit_depth": extract_field(mode_text, "csi_pixel_bit_depth"),
                    "discontinuous_clk":   extract_field(mode_text, "discontinuous_clk"),
                    "line_length":         extract_field(mode_text, "line_length"),
                    "pix_clk_hz":          extract_field(mode_text, "pix_clk_hz"),
                    "num_lanes":           extract_field(mode_text, "num_lanes"),
                }
                modes.append(fields)
                mode_idx += 1

        nodes[label] = modes
    return nodes


# ---------------------------------------------------------------------------
# Parsing overlay DTS (bus-width)
# ---------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)


def _read_overlay_text(overlay_path):
    """
    Reads an overlay DTS, following one level of local #include "foo.dtsi"
    (thin-wrapper pattern: a per-vendor .dts #define's a macro then includes
    a shared .dtsi body — see tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dts
    and its common .dtsi). Concatenates the wrapper + included body so the
    regex-based parsers below can find fragments regardless of which file
    they actually live in.
    """
    text = overlay_path.read_text()
    for inc in _INCLUDE_RE.findall(text):
        inc_path = overlay_path.parent / inc
        if inc_path.exists():
            text += "\n" + inc_path.read_text()
    return text


def parse_overlay_bus_width(overlay_path):
    """
    Returns the bus-width found in the overlay DTS (sensor endpoint).
    Finds the last occurrence of bus-width=<N> in the file.
    """
    text = _read_overlay_text(overlay_path)
    matches = re.findall(r'bus-width\s*=\s*<(\d+)>', text)
    if not matches:
        return None
    # The last occurrence is the sensor endpoint
    return int(matches[-1])


def parse_overlay_mode_overrides(overlay_path):
    """
    Returns dict: mode_idx (int) → dict of fields overridden in the overlay DTS.
    Possible fields: pix_clk_hz, num_lanes.
    Searches for fragments targeting .../modeN.
    """
    text = _read_overlay_text(overlay_path)
    result = {}
    for frag in re.finditer(r'fragment@\d+\s*\{(.*?)\n\s*\}', text, re.DOTALL):
        frag_text = frag.group(1)
        mode_m = re.search(r'/mode(\d+)"', frag_text)
        if not mode_m:
            continue
        idx = int(mode_m.group(1))
        overrides = {}
        hz_m = re.search(r'pix_clk_hz\s*=\s*"([^"]+)"', frag_text)
        if hz_m:
            overrides["pix_clk_hz"] = hz_m.group(1)
        lanes_m = re.search(r'num_lanes\s*=\s*"([^"]+)"', frag_text)
        if lanes_m:
            overrides["num_lanes"] = lanes_m.group(1)
        if overrides:
            result[idx] = overrides
    return result


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------

def expected_modes_for_camera(cam_id, cam_data, db, platform_id):
    """
    Returns the list of expected modes for this camera on this platform.
    Each mode is a dict with the expected DT fields + display.
    """
    restricted_formats = set()
    for plat_key, restr in db.get("platform_restrictions", {}).items():
        if plat_key == platform_id:
            restricted_formats.update(restr.get("unsupported_formats", []))

    fmt_map = db["pixel_format_map"]
    modes = []
    for res_entry in cam_data.get("resolutions", []):
        for mode in res_entry["modes"]:
            pf = mode["pixel_format"]
            if pf in restricted_formats:
                continue
            dt_fields = fmt_map[pf]
            modes.append({
                "pixel_format":        pf,
                "active_w":            str(res_entry["active_w"]),
                "active_h":            str(res_entry["active_h"]),
                "mode_type":           dt_fields["mode_type"],
                "pixel_phase":         dt_fields["pixel_phase"],
                "csi_pixel_bit_depth": str(dt_fields["csi_pixel_bit_depth"]),
                "discontinuous_clk":   res_entry["discontinuous_clk"],
                "line_length":         str(mode["line_length"]),
                "pix_clk_hz":          str(mode["pix_clk_hz"]),
                "num_lanes":           str(res_entry["data_lanes"]),
            })
    return modes


def find_dtsi_mode(dtsi_modes, expected):
    """
    Searches dtsi_modes for a mode matching expected
    on the identification keys (active_w, active_h, pixel_phase, csi_pixel_bit_depth).
    """
    for m in dtsi_modes:
        if (m["active_w"]            == expected["active_w"] and
            m["active_h"]            == expected["active_h"] and
            m["pixel_phase"]         == expected["pixel_phase"] and
            m["csi_pixel_bit_depth"] == expected["csi_pixel_bit_depth"]):
            return m
    return None


def verify_mode_fields(dtsi_mode, expected, cam_name, plat_key, node_label, errors):
    """Compares DT fields of a DTSI mode against expected values."""
    CHECKED_FIELDS = [
        "mode_type", "discontinuous_clk", "line_length", "pix_clk_hz",
        "active_w", "active_h", "num_lanes",
    ]
    for field in CHECKED_FIELDS:
        got          = dtsi_mode.get(field)
        expected_val = expected.get(field)
        if expected_val is None or got is None:
            continue
        if got != expected_val:
            errors.append(
                f"[{plat_key}/{node_label}] {cam_name} {expected['active_w']}x{expected['active_h']}"
                f" {expected['pixel_format']}: {field} = {got!r} (expected {expected_val!r})"
                f"  — {dtsi_mode.get('_comment', '')}"
            )


def verify(quiet=False):
    db = load_db()
    errors = []
    total_ok = 0

    for plat_key, plat in db["dtsi_platforms"].items():
        dtsi_path = SOURCES / plat["dtsi"]
        if not dtsi_path.exists():
            errors.append(f"[{plat_key}] FILE NOT FOUND: {dtsi_path}")
            continue

        lines = resolve_conditionals(read_lines(dtsi_path))

        # 1. Accolades
        bal = sum(l.count("{") - l.count("}") for l in lines)
        if bal != 0:
            errors.append(f"[{plat_key}] Brace imbalance: {bal:+d}")

        nodes = parse_sensor_nodes(lines)
        platform_ids = plat.get("platform_ids", [])
        # For restrictions: use the first platform_id (or "none")
        primary_platform_id = platform_ids[0] if platform_ids else "__none__"

        plat_ok = 0
        plat_errors_before = len(errors)

        for cam_key, cam_data in db["cameras"].items():
            prefix = cam_data["dt_node_label_prefix"]
            expected_modes = expected_modes_for_camera(
                cam_key, cam_data, db, primary_platform_id
            )
            expected_count = len(expected_modes)

            # Every mode of this camera uses a format the platform cannot produce
            # (platform_restrictions): the camera is not supported there, so its
            # node must be ABSENT. Checked in that direction — a leftover node
            # would advertise a camera that can never stream.
            if expected_count == 0:
                for cam_idx in range(plat["num_cams"]):
                    node_label = f"{prefix}{cam_idx}"
                    if node_label in nodes:
                        errors.append(
                            f"[{plat_key}] node {node_label} present, but every "
                            f"{cam_key} format is unsupported on {primary_platform_id}"
                        )
                    else:
                        plat_ok += 1
                continue

            # Overlay for EC cameras
            overlay_path = None
            overlay_overrides = {}  # mode_idx → {pix_clk_hz, num_lanes, ...}
            if "ec_overlay_variant" in cam_data:
                variant = cam_data["ec_overlay_variant"]
                pattern = plat.get("ec_overlay_cam0_pattern", "")
                if pattern:
                    overlay_rel = pattern.replace("{variant}", variant)
                    overlay_path = SOURCES / overlay_rel
                    if overlay_path.exists():
                        overlay_overrides = parse_overlay_mode_overrides(overlay_path)

            for cam_idx in range(plat["num_cams"]):
                node_label = f"{prefix}{cam_idx}"
                if node_label not in nodes:
                    errors.append(f"[{plat_key}] MISSING node: {node_label}")
                    continue

                dtsi_modes = nodes[node_label]

                # 2. Mode count
                # For EC cameras, the eg_ec_cam node contains ALL modes
                # from all EC cameras. Only verify modes
                # matching this camera (via ec_dtsi_mode_labels).
                if "ec_dtsi_mode_labels" in cam_data:
                    # Filter DTSI modes by comment label
                    labels = cam_data["ec_dtsi_mode_labels"]
                    relevant_dtsi = [
                        m for m in dtsi_modes
                        if any(lbl in m["_comment"] for lbl in labels)
                    ]
                    # On porg, RAW16 labels don't exist → filter them out
                    expected_for_check = expected_modes
                    if len(relevant_dtsi) != expected_count:
                        errors.append(
                            f"[{plat_key}] {node_label} ({cam_data['name']}): "
                            f"{len(relevant_dtsi)} modes found "
                            f"(expected {expected_count})"
                        )
                    # Field verification per mode
                    for exp in expected_for_check:
                        dtsi_m = find_dtsi_mode(relevant_dtsi, exp)
                        if dtsi_m is None:
                            errors.append(
                                f"[{plat_key}] {node_label} ({cam_data['name']}): "
                                f"mode {exp['active_w']}x{exp['active_h']} "
                                f"{exp['pixel_format']} NOT FOUND"
                            )
                        else:
                            # For EC modes overridden by overlay,
                            # build an "effective dtsi" dict by applying
                            # overlay overrides on top of DTSI values.
                            mode_idx = dtsi_m["_mode_idx"]
                            effective = dict(dtsi_m)
                            if mode_idx in overlay_overrides:
                                effective.update(overlay_overrides[mode_idx])
                            verify_mode_fields(
                                effective, exp,
                                cam_data["name"], plat_key, node_label, errors
                            )
                else:
                    # Camera with dedicated section (Dione, iLumos, Microlynx)
                    if len(dtsi_modes) != expected_count:
                        errors.append(
                            f"[{plat_key}/{node_label}] {cam_data['name']}: "
                            f"{len(dtsi_modes)} modes "
                            f"(expected {expected_count})"
                        )
                    for exp in expected_modes:
                        dtsi_m = find_dtsi_mode(dtsi_modes, exp)
                        if dtsi_m is None:
                            errors.append(
                                f"[{plat_key}/{node_label}] {cam_data['name']}: "
                                f"mode {exp['active_w']}x{exp['active_h']} "
                                f"{exp['pixel_format']} NOT FOUND"
                            )
                        else:
                            verify_mode_fields(
                                dtsi_m, exp,
                                cam_data["name"], plat_key, node_label, errors
                            )

                # 3. Overlay DTS : bus-width (une seule fois pour cam0)
                if cam_idx == 0 and overlay_path and overlay_path.exists():
                    bw = parse_overlay_bus_width(overlay_path)
                    expected_lanes = int(cam_data["resolutions"][0]["data_lanes"])
                    if bw is None:
                        errors.append(
                            f"[{plat_key}] overlay {overlay_path.name}: "
                            f"bus-width NOT FOUND"
                        )
                    elif bw != expected_lanes:
                        errors.append(
                            f"[{plat_key}] overlay {overlay_path.name}: "
                            f"bus-width={bw} (expected {expected_lanes})"
                        )

                if not [e for e in errors[plat_errors_before:] if node_label in e]:
                    plat_ok += 1

        total_ok += plat_ok
        if not quiet:
            had_error = len(errors) > plat_errors_before
            status = "FAIL" if had_error else "OK"
            print(f"  [{status}] {plat_key}: {plat_ok} nodes correct")

    # -----------------------------------------------------------------------
    # Overlay wrapper consistency: verify #define presence in DTS wrappers
    # Each entry: (path, required_defines, label)
    # -----------------------------------------------------------------------
    OVERLAY_WRAPPERS = [
        (SOURCES / "hardware_36+/nvidia/t23x/nv-public/overlay"
                   "/tegra234-p3767-camera-eg-cams-dione-cam0-lane-swap.dts",
         ["CAM0_LANE_SWAP"],
         "cam0_lane_swap_36"),
        (SOURCES / "hardware_36+/nvidia/t23x/nv-public/overlay"
                   "/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dts",
         ["DSBOARD_ORNXS_CAM_I2C_MUX", "CAM0_LANE_SWAP"],
         "dsboard_ornxs_36"),
        (SOURCES / "hardware_32+/nvidia/platform/t23x/p3768/kernel-dts"
                   "/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dts",
         ["CAM0_LANE_SWAP"],
         "dsboard_ornxs_32"),
        (SOURCES / "hardware_32+/nvidia/platform/t23x/p3768/kernel-dts"
                   "/tegra234-p3767-camera-eg-cams-dione-cam0-lane-swap.dts",
         ["CAM0_LANE_SWAP"],
         "cam0_lane_swap_32"),
    ]
    for path, defines, label in OVERLAY_WRAPPERS:
        had_error_before = len(errors)
        if not path.exists():
            errors.append(f"[{label}] FILE NOT FOUND: {path}")
        else:
            content = path.read_text()
            for define in defines:
                if f"#define {define}" not in content:
                    errors.append(f"[{label}] Missing #define {define} in {path.name}")
        if not quiet:
            had_error = len(errors) > had_error_before
            print(f"  [{'FAIL' if had_error else 'OK'}] {label}: {path.name}")
        total_ok += 1

    return errors, total_ok


GENERIC_DOCS = [
    "README.md",
    "docs/MIPI_DRIVER_DEVELOPMENT_GUIDE.md",
    "docs/DEPLOYMENT_MATRIX_README.md",
]


def verify_generic_docs(cfg, repo_root):
    """No camera may be named in the generic docs unless it is a documented example.

    README.md and the development guide are written to survive a product
    shipping or being withdrawn: they illustrate with released cameras and let
    the reader generalise. Naming anything else there means the document now has
    to be edited every time a product decision changes — and, in practice, means
    a withdrawn product keeps being advertised because nobody remembered the
    mention. Checked here so it fails at build time rather than in a customer's
    hands.

    Deliberately independent of the `enabled` flag: a camera can be enabled,
    shipped and listed in the deployment matrix while still having no place in
    generic documentation.
    """
    allowed = {n.lower() for n in cfg.get("doc_example_cameras", [])}
    names = {c.get("name", cid) for cid, c in cfg.get("cameras", {}).items()}
    forbidden = sorted(n for n in names if n.lower() not in allowed)

    errors = []
    for rel in GENERIC_DOCS:
        path = Path(repo_root) / rel
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            low = line.lower()
            for name in forbidden:
                if name.lower() in low:
                    errors.append(
                        f"{rel}:{lineno}: names '{name}', which is not in "
                        f"doc_example_cameras — keep generic docs product-neutral"
                    )
    return errors


def main():
    quiet = "--quiet" in sys.argv
    if not quiet:
        print("=== DTSI structure verification ===")

    errors, total_ok = verify(quiet=quiet)

    doc_errors = verify_generic_docs(load_db(), REPO_ROOT)
    errors.extend(doc_errors)
    if not quiet and not doc_errors:
        print(f"  [OK] generic docs name no camera outside doc_example_cameras")

    if not quiet:
        print(f"\n{total_ok} nodes OK, {len(errors)} errors")

    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    if not quiet:
        print("All checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
