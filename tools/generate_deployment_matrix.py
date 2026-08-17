#!/usr/bin/env python3
"""
Generate MIPI Camera Deployment Matrix in multiple formats
(Markdown, HTML, PDF)

Usage:
    python3 generate_deployment_matrix.py
"""

import yaml
import sys
import re
import base64
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

# Try to import optional dependencies
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


class DeploymentMatrixGenerator:
    """Generate deployment matrix in multiple formats"""

    FLEX_CABLE_DATA = {
        "cable_types": [
            {"label": "A", "desc": "22-pin → 15-pin, connectors on same side, not shielded."},
            {"label": "B", "desc": "15-pin → 15-pin, connectors on opposite sides, not shielded."},
            {"label": "C", "desc": "22-pin → 22-pin, connectors on opposite sides, not shielded."},
            {"label": "D", "desc": "22-pin → 22-pin, connectors on same side, not shielded."},
            {
                "label": "E",
                "desc": "Auvidea 38237 adapter (22-pin → 15-pin)",
                "warning": (
                    "Bare pads are exposed on both sides of the adapter. "
                    "Pay close attention to the equipment connected on each side — "
                    "risk of short circuit."
                ),
                "img": "tools/images/auvidea_38237.png",
            },
            {
                "label": "F",
                "desc": "22-pin → 15-pin, connectors on opposite sides, shielded. Reference : Vision Components EK003261.",
                "note": (
                    'Shielded cable — connect with "CPU Side" facing the host board '
                    'and "MIPI Module Side" facing the camera.'
                ),
                "img": "tools/images/flex_cable_opposite-side_shielded_22-15_F.png",
            },
            {
                "label": "G",
                "desc": "22-pin → 22-pin, connectors on same side, shielded. Reference : Vision Components EK003260.",
                "note": (
                    'Shielded cable — connect with "CPU Side" facing the host board '
                    'and "MIPI Module Side" facing the camera.'
                ),
                "img": "tools/images/flex_cable_same-side_shielded_22-22_G.png",
            },
        ],
        "table": [
            {"board": "Jetson Nano devkit",              "csi": "15-pin", "dione": "A", "microcube": "B", "ilumos": "F"},
            {"board": "Jetson Xavier NX devkit",         "csi": "15-pin", "dione": "A", "microcube": "B", "ilumos": "F"},
            {"board": "Jetson AGX Orin / Auvidea X230D", "csi": "22-pin", "dione": "C", "microcube": "A", "ilumos": "D or G"},
            {"board": "Jetson Orin NX devkit",           "csi": "22-pin", "dione": "C", "microcube": "A", "ilumos": "D or G"},
        ],
        "img_cables": "tools/images/flex_cables.png",
    }

    STATUS_ICONS = {
        "tested": "✅",
        "theoretically_supported": "⚠️",
        "not_supported": "❌",
    }

    STATUS_LABELS = {
        "tested": "Tested",
        "theoretically_supported": "Theoretically Supported",
        "not_supported": "Not Supported",
    }

    STATUS_COLORS = {
        "tested": "#28a745",
        "theoretically_supported": "#ffc107",
        "not_supported": "#dc3545",
    }

    def __init__(self, yaml_file):
        """Load deployment matrix from YAML file"""
        with open(yaml_file, 'r') as f:
            self.data = yaml.safe_load(f)

        # YAML parses single-dot numbers (35.1, 36.4) as float — normalize all keys to str
        if 'l4t_versions' in self.data:
            self.data['l4t_versions'] = {
                str(k): v for k, v in self.data['l4t_versions'].items()
            }

        self.platforms_by_id = {p['id']: p for p in self.data['platforms']}
        self.cameras_by_id = {c: self.data['cameras'][c] for c in self.data['cameras']}
        self.matrix_data = self.data['deployment_matrix']
        self.github_repo = self.data.get('github_repo', '')
        self.package_repo_base = self.data.get('package_repo_base', '')

        # Load camera technical details from eg_config.yaml
        camera_db_path = Path(yaml_file).parent.parent / 'eg_config.yaml'
        with open(camera_db_path, 'r') as f:
            self.camera_db = yaml.safe_load(f)

    def _csi_clock_mhz(self, pixel_format, pix_clk_hz, lanes):
        """MIPI D-PHY HS clock (MHz): pix_clk_hz × bits/pixel / lanes, halved for DDR."""
        bpp = self.camera_db['pixel_format_map'][pixel_format]['csi_pixel_bit_depth']
        return pix_clk_hz * bpp / lanes / 2 / 1e6

    def _data_rates_mbps(self, csi_mhz, lanes):
        """Data rate per lane and aggregate (Mbps): DDR clock × 2, then × lanes."""
        per_lane = csi_mhz * 2
        return per_lane, per_lane * lanes

    def parse_entry(self, entry_str):
        """Parse 'status|git_branch|deb_package' format"""
        if not entry_str or isinstance(entry_str, dict):
            return None, None, None

        parts = str(entry_str).split('|')
        status = parts[0] if len(parts) > 0 else None
        git_branch = parts[1].strip() if len(parts) > 1 else None
        deb_package = parts[2].strip() if len(parts) > 2 else None

        return status, git_branch, deb_package

    def get_status(self, platform_id, camera_id, l4t_version):
        """Get full entry for a platform/camera/L4T combination.

        Priority:
          1. Explicit entry in deployment_matrix_data.yaml
          2. Auto-generated theoretically_supported from eg_config.yaml platform_ids
          3. Empty (None, None, None)
        """
        l4t_version = str(l4t_version)

        # 1. Explicit entry
        for entry in self.matrix_data:
            if entry['platform'] == platform_id:
                if camera_id in entry['cameras']:
                    versions = entry['cameras'][camera_id]
                    for key, value in versions.items():
                        if str(key) == l4t_version:
                            return self.parse_entry(value)
                    # Platform/camera block exists but version not listed — fall through
                    break

        # 2. Auto-generate from eg_config.yaml platform_ids
        version_cfg = self.camera_db.get('versions', {}).get(l4t_version, {})
        if platform_id in version_cfg.get('platform_ids', []):
            return 'theoretically_supported', None, None

        return None, None, None

    def get_all_l4t_versions(self):
        """Get all unique L4T versions: union of eg_config.yaml and deployment_matrix_data.yaml."""
        versions = set()
        # From eg_config.yaml (authoritative list of supported versions)
        versions.update(self.camera_db.get('versions', {}).keys())
        # From deployment_matrix_data.yaml (may include historical versions not in eg_config)
        for entry in self.matrix_data:
            for camera_id, version_dict in entry['cameras'].items():
                versions.update(str(v) for v in version_dict.keys())
        def version_sort_key(x):
            parts = []
            for p in str(x).split('.'):
                seg = p.split('-', 1)
                num = int(seg[0]) if seg[0].isdigit() else 0
                suffix = seg[1] if len(seg) > 1 else ''
                # suffixed variants (e.g. "1-yocto") sort before bare numbers (e.g. "1")
                parts.append((num, 0 if suffix else 1, suffix))
            return parts
        return sorted(versions, key=version_sort_key)

    def get_versions_for_platform(self, platform):
        """Return l4t_versions filtered to those matching the platform's l4t_series.

        e.g. l4t_series="32.x, 35.x" → only versions whose major number is 32 or 35.
        Yocto versions are only included when the platform has explicit data for them.
        """
        all_versions = self.get_all_l4t_versions()
        l4t_series_str = platform.get('l4t_series', '')
        if not l4t_series_str:
            return all_versions
        # Parse "32.x, 35.x" → {"32", "35"}
        prefixes = {s.strip().split('.')[0] for s in l4t_series_str.split(',') if s.strip()}

        # Collect versions that have at least one explicit entry for this platform
        platform_id = platform['id']
        explicit_versions: set = set()
        for entry in self.matrix_data:
            if entry['platform'] == platform_id:
                for cam_data in entry['cameras'].values():
                    explicit_versions.update(str(k) for k in cam_data.keys())
                break

        filtered = []
        for v in all_versions:
            if str(v).split('.')[0] not in prefixes:
                continue
            ver_data = self.data.get('l4t_versions', {}).get(str(v), {})
            # Skip Yocto versions that have no explicit entry for this platform
            if ver_data.get('yocto') and str(v) not in explicit_versions:
                continue
            filtered.append(v)
        return filtered

    def get_os_label(self, version):
        """Derive the OS label for a given L4T version.

        - Yocto entries (yocto: true in l4t_versions) → "Yocto (obsolete)"
        - JetPack entries → "JetPack X.Y.Z" from eg_config.yaml jetpack field
        - Unknown versions → empty string
        """
        version = str(version)
        ver_data = self.data.get('l4t_versions', {}).get(version, {})
        if ver_data.get('yocto'):
            return "Yocto (obsolete)"
        # Strip suffix for eg_config lookup (e.g. "32.7.1-yocto" → "32.7.1")
        base_version = version.split('-')[0]
        jp = self.camera_db.get('versions', {}).get(base_version, {}).get('jetpack', '')
        return f"JetPack {jp}" if jp else ''

    def get_version_display(self, version):
        """Return a human-readable label for a version key.

        '32.7.1-yocto' → '32.7.1'  (suffix stripped; OS column carries the info)
        '32.7.1'        → '32.7.1'
        """
        version = str(version)
        if '-' in version:
            return version.split('-', 1)[0]
        return version

    def get_git_link(self, version, git_branch):
        """Return a full git URL.

        Uses git_branch (→ github_repo/tree/branch) when set; otherwise falls back
        to git_url from l4t_versions (used for Yocto builds pointing to a different repo).
        """
        if git_branch:
            return f"{self.github_repo}/tree/{git_branch}"
        ver_data = self.data.get('l4t_versions', {}).get(str(version), {})
        return ver_data.get('git_url', '')

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def validate(self):
        """Cross-check deployment_matrix_data.yaml against eg_config.yaml.

        Returns a list of issue strings (empty = all good).
        Checks:
          1. Versions in eg_config with no l4t_versions entry → no git metadata
          2. Platforms in deployment_matrix not referenced by any eg_config platform_ids
          3. Explicit matrix entries for (platform, version) where eg_config doesn't
             list that platform in platform_ids
          4. (Informational) platform+version combos covered only by auto-generation
        """
        issues = []
        eg_versions = self.camera_db.get('versions', {})
        matrix_l4t = self.data.get('l4t_versions', {})
        matrix_platform_ids = {p['id'] for p in self.data['platforms']}
        camera_ids = list(self.data['cameras'].keys())

        # 1. Versions in eg_config missing from l4t_versions
        for ver in eg_versions:
            if ver not in matrix_l4t:
                issues.append(
                    f"⚠️  L4T {ver}: present in eg_config but missing from l4t_versions "
                    f"(no git_branch → no links in matrix)"
                )

        # 2. Platforms in deployment_matrix not referenced in any eg_config version
        all_eg_platform_ids = set()
        for vcfg in eg_versions.values():
            all_eg_platform_ids.update(vcfg.get('platform_ids', []))
        for pid in sorted(matrix_platform_ids):
            if pid not in all_eg_platform_ids:
                issues.append(
                    f"⚠️  Platform '{pid}': in deployment_matrix platforms but not in "
                    f"any eg_config version's platform_ids"
                )

        # 3. Explicit matrix entries conflicting with eg_config platform_ids
        for entry in self.matrix_data:
            pid = entry['platform']
            for cam_id, version_dict in entry['cameras'].items():
                for ver in version_dict:
                    ver_str = str(ver)
                    base_ver = ver_str.split('-')[0]
                    vcfg = eg_versions.get(base_ver)
                    if vcfg and pid not in vcfg.get('platform_ids', []):
                        issues.append(
                            f"⚠️  {pid} / {cam_id} / {ver_str}: explicit entry in matrix "
                            f"but '{pid}' not in eg_config platform_ids for {base_ver}"
                        )

        # 4. Informational: platform+version in eg_config with no explicit matrix entry
        implicit = []
        for ver, vcfg in eg_versions.items():
            for pid in vcfg.get('platform_ids', []):
                if pid not in matrix_platform_ids:
                    continue
                has_explicit = any(
                    ver in [str(k) for k in cam_data.keys()]
                    for entry in self.matrix_data
                    if entry['platform'] == pid
                    for cam_data in entry['cameras'].values()
                )
                if not has_explicit:
                    implicit.append(f"      {pid:<28} L4T {ver}")

        if implicit:
            issues.append(
                "ℹ️  Platform+version combos with no explicit entry "
                "(auto-generated as theoretically_supported from eg_config):"
            )
            issues.extend(implicit)

        return issues

    # ------------------------------------------------------------------ #
    # Flex cable appendix helpers
    # ------------------------------------------------------------------ #

    def _img_data_uri(self, rel_path):
        """Return a base64 data URI for an image file (relative to repo root)."""
        img_path = Path(__file__).parent.parent / rel_path
        data = base64.b64encode(img_path.read_bytes()).decode('ascii')
        suffix = img_path.suffix.lower().lstrip('.')
        mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
        return f"data:{mime};base64,{data}"

    def _flex_cable_appendix_md(self):
        """Return Markdown string for the CSI flex cable appendix."""
        d = self.FLEX_CABLE_DATA
        lines = [
            "## Appendix — CSI Flex Cable Selection Guide\n",
            "Select the correct flex cable based on the Jetson board's CSI connector pitch "
            "and the camera connector pitch.\n",
            "| Board | CSI connector | Dione (22-pin) | MicroCube / Crius1280 / SmartIR640 / Microlynx (15-pin) | iLumos (22-pin) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in d["table"]:
            lines.append(
                f"| {row['board']} | {row['csi']} | **{row['dione']}** "
                f"| **{row['microcube']}** | **{row['ilumos']}** |"
            )
        lines.append("")
        cables_uri = self._img_data_uri(d['img_cables'])
        lines.append(f"![CSI flex cables A–D]({cables_uri})\n")
        lines.append("**Cable types:**\n")
        for ct in d["cable_types"]:
            lines.append(f"- **{ct['label']}**: {ct['desc']}")
            if "warning" in ct:
                lines.append(f"\n  > ⚠️ **WARNING:** {ct['warning']}\n")
            if "note" in ct:
                lines.append(f"\n  > ℹ️ {ct['note']}\n")
            if "img" in ct:
                uri = self._img_data_uri(ct['img'])
                lines.append(f"\n  ![Cable {ct['label']}]({uri})\n")
        return "\n".join(lines)

    def _flex_cable_appendix_html(self):
        """Return an HTML <div> string for the CSI flex cable appendix."""
        d = self.FLEX_CABLE_DATA

        rows_html = ""
        for row in d["table"]:
            rows_html += (
                f"<tr><td>{row['board']}</td><td>{row['csi']}</td>"
                f"<td><strong>{row['dione']}</strong></td>"
                f"<td><strong>{row['microcube']}</strong></td>"
                f"<td><strong>{row['ilumos']}</strong></td></tr>\n"
            )

        cable_types_html = ""
        for ct in d["cable_types"]:
            extras = ""
            if "warning" in ct:
                extras += (
                    f'<div style="background:#fff3cd;border:1px solid #ffc107;'
                    f'border-left:4px solid #e65c00;border-radius:4px;padding:8px 12px;'
                    f'margin:6px 0;font-size:0.9em;">'
                    f'⚠️ <strong>WARNING:</strong> {ct["warning"]}</div>'
                )
            if "note" in ct:
                extras += (
                    f'<div style="background:#e8f4fd;border-left:4px solid #3498db;'
                    f'padding:6px 10px;margin:6px 0;font-size:0.9em;">'
                    f'ℹ️ {ct["note"]}</div>'
                )
            if "img" in ct:
                uri = self._img_data_uri(ct["img"])
                extras += (
                    f'<div style="margin:6px 0;">'
                    f'<img src="{uri}" alt="Cable {ct["label"]}" '
                    f'style="max-height:80px;border:1px solid #ddd;border-radius:4px;"></div>'
                )
            cable_types_html += (
                f'<li style="margin-bottom:8px;">'
                f'<strong>{ct["label"]}</strong>: {ct["desc"]}'
                f'{extras}</li>\n'
            )

        cables_uri = self._img_data_uri(d['img_cables'])
        return f"""    <div class="platform-section">
        <h2>🔌 CSI Flex Cable Selection Guide</h2>
        <p>Select the correct flex cable based on the Jetson board's CSI connector pitch and the camera connector pitch.</p>
        <table>
            <thead><tr>
                <th>Board</th>
                <th>CSI connector</th>
                <th>Dione (22-pin)</th>
                <th>MicroCube / Crius1280 / SmartIR640 / Microlynx (15-pin)</th>
                <th>iLumos (22-pin)</th>
            </tr></thead>
            <tbody>
{rows_html}            </tbody>
        </table>
        <div style="margin-top:16px;">
            <img src="{cables_uri}" alt="CSI flex cables A–D"
                 style="max-height:220px; border:1px solid #ddd; border-radius:4px;">
            <p style="font-size:0.85em;color:#666;margin-top:4px;">Cables A–D</p>
        </div>
        <p><strong>Cable types:</strong></p>
        <ul style="list-style:none;padding-left:0;">
{cable_types_html}        </ul>
    </div>
"""

    def generate_markdown(self, output_file):
        """Generate Markdown table"""
        l4t_versions = self.get_all_l4t_versions()
        camera_ids = list(self.data['cameras'].keys())

        with open(output_file, 'w') as f:
            f.write("# MIPI Camera Deployment Matrix\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("## Legend\n")
            f.write("- ✅ **Tested** - Tested and verified on this platform\n")
            f.write("- ⚠️ **Theoretically Supported** - Supported but not tested\n")
            f.write("- ❌ **Not Supported** - Not supported on this platform\n")
            f.write("- (empty) - Data not available\n\n")
            f.write("**Acronyms:** EG = Exosens Group\n\n")

            # For each platform
            for platform in self.data['platforms']:
                platform_id = platform['id']
                f.write(f"## {platform['name']}\n\n")

                if 'description' in platform:
                    f.write(f"**{platform['description']}**\n\n")

                if 'variants' in platform:
                    variants = platform['variants']
                    if not isinstance(variants, list):
                        variants = [variants]
                    f.write("**Carrier boards:**\n\n")
                    for variant in variants:
                        f.write(f"- {variant}\n")
                    f.write("\n")

                if 'notes' in platform:
                    notes = platform['notes']
                    if isinstance(notes, list):
                        f.write("> **Notes:**\n>\n")
                        for note in notes:
                            f.write(f"> {note}\n>\n")
                        f.write("\n")
                    else:
                        f.write(f"> **Note:** {notes}\n\n")

                # Build table header
                f.write("| OS | L4T Version |")
                for cam_id in camera_ids:
                    cam_name = self.data['cameras'][cam_id]['name']
                    f.write(f" {cam_name} | Git | Package |")
                f.write("\n")

                # Header separator
                f.write("|" + " --- |" * (2 + len(camera_ids) * 3))
                f.write("\n")

                # Data rows — filtered to this platform's L4T series
                platform_versions = self.get_versions_for_platform(platform)
                for version in platform_versions:
                    ver_display = self.get_version_display(version)
                    ver_data = self.data.get('l4t_versions', {}).get(str(version), {})
                    os_label = self.get_os_label(version)
                    is_yocto = ver_data.get('yocto', False)
                    f.write(f"| {os_label} | `{ver_display}` |")
                    for cam_id in camera_ids:
                        status, git_branch, deb_pkg = self.get_status(platform_id, cam_id, version)

                        if status:
                            icon = self.STATUS_ICONS.get(status, '❓')
                            label = self.STATUS_LABELS.get(status, status)
                            f.write(f" {icon} {label} |")

                            # Git link
                            git_url = self.get_git_link(version, git_branch)
                            if git_url:
                                f.write(f" [🔗]({git_url}) |")
                            else:
                                f.write(" |")

                            # Package link
                            if deb_pkg:
                                pkg_url = f"{self.package_repo_base}/{deb_pkg}"
                                f.write(f" [📦]({pkg_url}) |")
                            else:
                                f.write(" |")
                        else:
                            f.write(" | | |")
                    f.write("\n")

                f.write("\n")

            # Camera details section
            f.write("## Camera Details\n\n")
            for cam_id in camera_ids:
                cam = self.data['cameras'][cam_id]
                db_cam = self.camera_db['cameras'].get(cam_id, {})
                f.write(f"### {cam['name']}\n")
                if 'notes' in cam:
                    f.write(f"- **Notes**: {cam['notes']}\n")
                for res_entry in db_cam.get('resolutions', []):
                    lanes = res_entry['data_lanes']
                    f.write(f"\n**{res_entry['res']}** — {lanes} CSI lane(s)\n\n")
                    f.write("| Pixel Format | Pixel Clock | CSI Clock | Data Rate / Lane | Data Rate Total |\n")
                    f.write("| --- | --- | --- | --- | --- |\n")
                    for mode in res_entry['modes']:
                        pix_mhz = mode['pix_clk_hz'] / 1e6
                        pix_str = f"{pix_mhz:.1f}".rstrip('0').rstrip('.')
                        csi_mhz = self._csi_clock_mhz(mode['pixel_format'], mode['pix_clk_hz'], lanes)
                        lane_mbps, total_mbps = self._data_rates_mbps(csi_mhz, lanes)
                        f.write(f"| {mode['pixel_format']} | {pix_str} MHz | {csi_mhz:.0f} MHz "
                                f"| {lane_mbps:.0f} Mbps | {total_mbps:.0f} Mbps |\n")
                f.write("\n")

            # Flex cable appendix
            f.write(self._flex_cable_appendix_md())

        print(f"✅ Markdown matrix generated: {output_file}")

    def generate_html(self, output_file):
        """Generate HTML table"""
        l4t_versions = self.get_all_l4t_versions()
        camera_ids = list(self.data['cameras'].keys())

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MIPI Camera Deployment Matrix</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 1600px;
            margin: 20px auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }}

        h1, h2, h3 {{
            color: #2c3e50;
        }}

        .timestamp {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}

        .legend {{
            background: white;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .legend-item {{
            display: inline-block;
            margin-right: 30px;
            margin-bottom: 10px;
        }}

        .platform-section {{
            background: white;
            margin-bottom: 30px;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow-x: auto;
        }}

        .platform-name {{
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}

        .platform-notes {{
            background: #e3f2fd;
            padding: 10px;
            border-left: 4px solid #3498db;
            margin: 10px 0;
            border-radius: 3px;
        }}

        .platform-variants {{
            background: #f1f8e9;
            padding: 10px;
            border-left: 4px solid #7cb342;
            margin: 10px 0;
            border-radius: 3px;
        }}

        .platform-variants ul {{
            margin: 5px 0 0 20px;
            padding: 0;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 0.85em;
        }}

        th, td {{
            padding: 10px;
            text-align: left;
            border: 1px solid #ddd;
        }}

        th {{
            background: #34495e;
            color: white;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}

        tr:hover {{
            background: #f9f9f9;
        }}

        .version-cell {{
            font-family: 'Courier New', monospace;
            font-weight: 500;
            color: #2c3e50;
        }}

        .status-tested {{
            background: #d4edda;
            color: #155724;
        }}

        .status-theoretical {{
            background: #fff3cd;
            color: #856404;
        }}

        .status-unsupported {{
            background: #f8d7da;
            color: #721c24;
        }}

        .status-empty {{
            background: #f0f0f0;
            color: #999;
            text-align: center;
        }}

        tr.row-yocto td {{
            background: #f2f2f2 !important;
            color: #aaa !important;
            font-style: italic;
        }}

        tr.row-yocto td.link-cell a {{
            opacity: 0.4;
        }}

        .link-cell {{
            text-align: center;
            padding: 8px;
        }}

        .link-cell a {{
            display: inline-block;
            text-decoration: none;
            font-size: 1.2em;
            margin: 0 3px;
        }}

        .link-cell a:hover {{
            opacity: 0.7;
        }}

        .camera-details {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }}

        .camera-card {{
            background: white;
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-left: 4px solid #3498db;
        }}

        .camera-card h4 {{
            margin-top: 0;
            color: #2c3e50;
        }}

        .camera-card p {{
            margin: 8px 0;
            font-size: 0.9em;
        }}

        .camera-card table {{
            width: 100%;
            border-collapse: collapse;
            margin: 6px 0 10px 0;
            font-size: 0.85em;
        }}

        .camera-card th, .camera-card td {{
            padding: 4px 8px;
            border: 1px solid #ddd;
            text-align: left;
        }}

        .camera-card th {{
            background: #ecf0f1;
            color: #2c3e50;
            font-size: 0.85em;
        }}

        .res-title {{
            font-weight: 600;
            margin: 10px 0 4px 0;
            font-size: 0.9em;
            color: #34495e;
        }}

        .icon {{
            font-size: 1.2em;
            margin-right: 5px;
        }}
    </style>
</head>
<body>
    <h1>MIPI Camera Deployment Matrix</h1>
    <div class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>

    <div class="legend">
        <h3>Legend</h3>
        <div class="legend-item"><span class="icon">✅</span> <strong>Tested</strong> - Tested and verified</div>
        <div class="legend-item"><span class="icon">⚠️</span> <strong>Theoretically Supported</strong> - Not tested</div>
        <div class="legend-item"><span class="icon">🔗</span> <strong>Git</strong> - Branch link</div>
        <div class="legend-item"><span class="icon">📦</span> <strong>Package</strong> - .deb download</div>
        <div class="legend-item"><strong>EG</strong> = Exosens Group</div>
    </div>
"""

        # Generate platform sections
        for platform in self.data['platforms']:
            platform_id = platform['id']
            html_content += f"""
    <div class="platform-section">
        <h2 class="platform-name">{platform['name']}</h2>
"""

            if 'description' in platform:
                html_content += f"        <p><strong>{platform['description']}</strong></p>\n"

            if 'variants' in platform:
                variants = platform['variants']
                if not isinstance(variants, list):
                    variants = [variants]
                variants_html = ''.join(f'<li>{v}</li>' for v in variants)
                html_content += f'        <div class="platform-variants">🔌 <strong>Carrier boards:</strong><ul>{variants_html}</ul></div>\n'

            if 'notes' in platform:
                notes = platform['notes']
                if isinstance(notes, list):
                    notes_html = '<br>'.join(notes)
                    html_content += f'        <div class="platform-notes">📌 <strong>Notes:</strong><br>{notes_html}</div>\n'
                else:
                    html_content += f'        <div class="platform-notes">📌 <strong>Note:</strong> {notes}</div>\n'

            html_content += f"""        <p style="color: #666; font-size: 0.9em;">
            <strong>L4T Series:</strong> {platform.get('l4t_series', 'N/A')} |
            <strong>SoM:</strong> {platform.get('som', 'N/A')} |
            <strong>CSI Lanes:</strong> {platform.get('csi_lanes', 'N/A')}
        </p>
"""

            # Table
            html_content += """        <table>
            <thead>
                <tr>
                    <th rowspan='2'>OS</th>
                    <th rowspan='2'>L4T Version</th>
"""
            for cam_id in camera_ids:
                cam_name = self.data['cameras'][cam_id]['name']
                html_content += f"                    <th colspan='3'>{cam_name}</th>\n"

            html_content += """                </tr>
                <tr>
"""
            for _ in camera_ids:
                html_content += "                    <th style='font-size: 0.85em;'>Status</th>\n"
                html_content += "                    <th style='font-size: 0.85em;'>Git</th>\n"
                html_content += "                    <th style='font-size: 0.85em;'>Package</th>\n"

            html_content += """                </tr>
            </thead>
            <tbody>
"""

            platform_versions = self.get_versions_for_platform(platform)
            for version in platform_versions:
                ver_display = self.get_version_display(version)
                ver_data = self.data.get('l4t_versions', {}).get(str(version), {})
                os_label = self.get_os_label(version)
                os_html = os_label.replace('JetPack ', 'JetPack<br>', 1) if os_label.startswith('JetPack ') else os_label
                is_yocto = ver_data.get('yocto', False)
                row_class = ' class="row-yocto"' if is_yocto else ''
                html_content += (
                    f'                <tr{row_class}>\n'
                    f'                    <td style="font-size:0.8em;color:#666;text-align:center;">{os_html}</td>\n'
                    f'                    <td class="version-cell">{ver_display}</td>\n'
                )

                for cam_id in camera_ids:
                    status, git_branch, deb_pkg = self.get_status(platform_id, cam_id, version)

                    if status:
                        if status == 'tested':
                            css_class = 'status-tested'
                            icon = '✅'
                            label = 'Tested'
                        elif status == 'theoretically_supported':
                            css_class = 'status-theoretical'
                            icon = '⚠️'
                            label = 'Theoretically Supported'
                        else:
                            css_class = 'status-unsupported'
                            icon = '❌'
                            label = 'Not Supported'

                        html_content += f'                    <td class="{css_class}"><span class="icon">{icon}</span> {label}</td>\n'

                        # Git link
                        git_url = self.get_git_link(version, git_branch)
                        if git_url:
                            html_content += f'                    <td class="link-cell"><a href="{git_url}" target="_blank" title="Git branch">🔗</a></td>\n'
                        else:
                            html_content += '                    <td class="link-cell">—</td>\n'

                        # Package link
                        if deb_pkg and self.package_repo_base:
                            pkg_url = f"{self.package_repo_base}/{deb_pkg}"
                            html_content += f'                    <td class="link-cell"><a href="{pkg_url}" target="_blank" title="Download package">📦</a></td>\n'
                        else:
                            html_content += '                    <td class="link-cell">—</td>\n'
                    else:
                        html_content += '                    <td class="status-empty" colspan="3">—</td>\n'

                html_content += '                </tr>\n'

            html_content += """            </tbody>
        </table>
    </div>
"""

        # Camera details
        html_content += """
    <div class="platform-section">
        <h2>📸 Camera Details</h2>
        <div class="camera-details">
"""

        for cam_id in camera_ids:
            cam = self.data['cameras'][cam_id]
            db_cam = self.camera_db['cameras'].get(cam_id, {})
            notes_html = f"<p><strong>Notes:</strong> {cam.get('notes', 'N/A')}</p>" if 'notes' in cam else ""

            resolutions_html = ""
            for res_entry in db_cam.get('resolutions', []):
                lanes = res_entry['data_lanes']
                resolutions_html += f'<p class="res-title">{res_entry["res"]} — {lanes} CSI lane(s)</p>\n'
                resolutions_html += ('<table><thead><tr><th>Pixel Format</th><th>Pixel Clock</th>'
                                    '<th>CSI Clock</th><th>Data Rate / Lane</th>'
                                    '<th>Data Rate Total</th></tr></thead><tbody>\n')
                for mode in res_entry['modes']:
                    pix_mhz = mode['pix_clk_hz'] / 1e6
                    pix_str = f"{pix_mhz:.1f}".rstrip('0').rstrip('.')
                    csi_mhz = self._csi_clock_mhz(mode['pixel_format'], mode['pix_clk_hz'], lanes)
                    lane_mbps, total_mbps = self._data_rates_mbps(csi_mhz, lanes)
                    resolutions_html += (f'<tr><td>{mode["pixel_format"]}</td><td>{pix_str} MHz</td>'
                                         f'<td>{csi_mhz:.0f} MHz</td><td>{lane_mbps:.0f} Mbps</td>'
                                         f'<td>{total_mbps:.0f} Mbps</td></tr>\n')
                resolutions_html += '</tbody></table>\n'

            html_content += f"""            <div class="camera-card">
                <h4>{cam['name']}</h4>
                {notes_html}
                {resolutions_html}
            </div>
"""

        html_content += """        </div>
    </div>
"""
        html_content += self._flex_cable_appendix_html()
        html_content += "</body>\n</html>\n"

        with open(output_file, 'w') as f:
            f.write(html_content)

        print(f"✅ HTML matrix generated: {output_file}")

    def _generate_pdf_html(self):
        """Generate a compact HTML string optimised for PDF rendering.

        Differences from the web HTML:
        - A4 landscape, 1 cm margins
        - Status column only (no Git / Package links)
        - Icon + short label to save horizontal space
        - Tighter font and padding
        - One table per platform (platform name as caption)
        """
        l4t_versions = self.get_all_l4t_versions()
        camera_ids   = list(self.data['cameras'].keys())

        SHORT_LABEL = {
            "tested":                 "Tested",
            "theoretically_supported":"Theoretical",
            "not_supported":          "N/A",
        }

        css = """
        @page {
            size: A4 landscape;
            margin: 1cm;
        }
        body {
            font-family: Arial, Helvetica, sans-serif;
            font-size: 7.5pt;
            color: #222;
            margin: 0;
            padding: 0;
        }
        h1 { font-size: 13pt; margin: 0 0 4px 0; }
        .meta { font-size: 7pt; color: #666; margin-bottom: 10px; }
        .legend { font-size: 7pt; margin-bottom: 10px; }
        .legend span { margin-right: 14px; }
        .platform-block { margin-bottom: 16px; page-break-inside: avoid; }
        h2 { font-size: 9pt; margin: 0 0 4px 0; color: #1a3a5c;
             border-bottom: 1px solid #3498db; padding-bottom: 2px; }
        .plat-meta { font-size: 7pt; color: #555; margin-bottom: 4px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #bbb; padding: 2px 4px; text-align: center; }
        th { background: #2c3e50; color: white; font-size: 7pt; }
        th.ver-col { width: 52px; }
        th.os-col  { width: 60px; }
        td.ver { font-family: monospace; font-size: 7pt; text-align: left;
                 color: #1a3a5c; white-space: nowrap; }
        td.os  { font-size: 6.5pt; color: #555; text-align: left; white-space: nowrap; }
        .tested       { background: #d4edda; color: #155724; }
        .theoretical  { background: #fff3cd; color: #856404; }
        .unsupported  { background: #f8d7da; color: #721c24; }
        .empty        { background: #f4f4f4; color: #bbb; }
        """

        lines = [
            "<!DOCTYPE html><html><head><meta charset='UTF-8'>",
            f"<style>{css}</style></head><body>",
            "<h1>MIPI Camera Deployment Matrix</h1>",
            f"<div class='meta'>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>",
            "<div class='legend'>",
            "<span>✅ Tested</span>",
            "<span>⚠️ Theoretical (not yet tested)</span>",
            "<span>❌ Not supported</span>",
            "<span>— No data</span>",
            "<span><strong>EG</strong> = Exosens Group</span>",
            "</div>",
        ]

        for platform in self.data['platforms']:
            pid  = platform['id']
            lines.append("<div class='platform-block'>")
            lines.append(f"<h2>{platform['name']}</h2>")
            meta = []
            if 'som' in platform:         meta.append(f"SoM: {platform['som']}")
            if 'l4t_series' in platform:  meta.append(f"L4T: {platform['l4t_series']}")
            if 'csi_lanes' in platform:   meta.append(f"CSI lanes: {platform['csi_lanes']}")
            if meta:
                lines.append(f"<div class='plat-meta'>{' | '.join(meta)}</div>")
            if 'variants' in platform:
                variants = platform['variants']
                if not isinstance(variants, list):
                    variants = [variants]
                lines.append(f"<div class='plat-meta'>🔌 <b>Carrier boards:</b> {' | '.join(variants)}</div>")
            if 'notes' in platform:
                notes = platform['notes']
                if isinstance(notes, list):
                    label = 'Notes'
                    notes_text = ' — '.join(notes)
                else:
                    label = 'Note'
                    notes_text = notes
                lines.append(f"<div class='plat-meta' style='color:#8a6d00;'>📌 <b>{label}:</b> {notes_text}</div>")

            lines.append("<table><thead><tr>")
            lines.append("<th class='os-col'>OS</th>")
            lines.append("<th class='ver-col'>L4T</th>")
            for cam_id in camera_ids:
                cam_name = self.data['cameras'][cam_id]['name']
                lines.append(f"<th>{cam_name}</th>")
            lines.append("</tr></thead><tbody>")

            platform_versions = self.get_versions_for_platform(platform)
            for version in platform_versions:
                ver_display = self.get_version_display(version)
                ver_data = self.data.get('l4t_versions', {}).get(str(version), {})
                os_label = self.get_os_label(version)
                is_yocto = ver_data.get('yocto', False)
                row_style = " style='background:#f2f2f2;color:#aaa;font-style:italic;'" if is_yocto else ""
                lines.append(f"<tr{row_style}><td class='os'>{os_label}</td><td class='ver'>{ver_display}</td>")
                for cam_id in camera_ids:
                    status, _, _ = self.get_status(pid, cam_id, version)
                    if status == 'tested':
                        lines.append(f"<td class='tested'>✅ {SHORT_LABEL['tested']}</td>")
                    elif status == 'theoretically_supported':
                        lines.append(f"<td class='theoretical'>⚠️ {SHORT_LABEL['theoretically_supported']}</td>")
                    elif status == 'not_supported':
                        lines.append(f"<td class='unsupported'>❌</td>")
                    else:
                        lines.append("<td class='empty'>—</td>")
                lines.append("</tr>")

            lines.append("</tbody></table></div>")

        # Camera details
        lines.append("<div style='page-break-before: always;'>")
        lines.append("<h1 style='font-size:11pt; margin-bottom:8px;'>Camera Details</h1>")
        lines.append("<div style='display:grid; grid-template-columns: repeat(3, 1fr); gap: 10px;'>")

        for cam_id in camera_ids:
            cam    = self.data['cameras'][cam_id]
            db_cam = self.camera_db['cameras'].get(cam_id, {})

            lines.append("<div style='border:1px solid #bbb; border-left:3px solid #3498db; padding:6px; border-radius:3px;'>")
            lines.append(f"<div style='font-weight:bold; font-size:8.5pt; color:#1a3a5c; margin-bottom:4px;'>{cam['name']}</div>")

            if 'notes' in cam:
                lines.append(f"<div style='font-size:7pt; color:#555; margin-bottom:4px;'>{cam['notes']}</div>")

            for res_entry in db_cam.get('resolutions', []):
                lanes = res_entry['data_lanes']
                lines.append(f"<div style='font-size:7pt; font-weight:bold; margin-top:5px; color:#34495e;'>{res_entry['res']} — {lanes} lane(s)</div>")
                lines.append("<table style='width:100%; margin-top:2px;'>")
                lines.append("<thead><tr>")
                lines.append("<th style='font-size:6.5pt;'>Format</th>")
                lines.append("<th style='font-size:6.5pt;'>Pix clock</th>")
                lines.append("<th style='font-size:6.5pt;'>CSI clock</th>")
                lines.append("<th style='font-size:6.5pt;'>Rate/lane</th>")
                lines.append("<th style='font-size:6.5pt;'>Rate total</th>")
                lines.append("</tr></thead><tbody>")
                for mode in res_entry['modes']:
                    pix_mhz = mode['pix_clk_hz'] / 1e6
                    pix_str = f"{pix_mhz:.1f}".rstrip('0').rstrip('.')
                    csi_mhz = self._csi_clock_mhz(mode['pixel_format'], mode['pix_clk_hz'], lanes)
                    lane_mbps, total_mbps = self._data_rates_mbps(csi_mhz, lanes)
                    lines.append(f"<tr><td style='font-size:6.5pt;'>{mode['pixel_format']}</td>"
                                 f"<td style='font-size:6.5pt;'>{pix_str} MHz</td>"
                                 f"<td style='font-size:6.5pt;'>{csi_mhz:.0f} MHz</td>"
                                 f"<td style='font-size:6.5pt;'>{lane_mbps:.0f} Mbps</td>"
                                 f"<td style='font-size:6.5pt;'>{total_mbps:.0f} Mbps</td></tr>")
                lines.append("</tbody></table>")

            lines.append("</div>")

        lines.append("</div></div>")

        # Flex cable appendix
        d = self.FLEX_CABLE_DATA
        rows_html = "".join(
            f"<tr><td>{r['board']}</td><td>{r['csi']}</td>"
            f"<td style='text-align:center;font-weight:bold'>{r['dione']}</td>"
            f"<td style='text-align:center;font-weight:bold'>{r['microcube']}</td>"
            f"<td style='text-align:center;font-weight:bold'>{r['ilumos']}</td></tr>"
            for r in d["table"]
        )
        cable_list_html = ""
        for ct in d["cable_types"]:
            extras = ""
            if "warning" in ct:
                extras += (
                    f"<span style='display:block;background:#fff3cd;border-left:3px solid #e65c00;"
                    f"padding:2px 5px;margin:2px 0;font-size:6.5pt;'>"
                    f"⚠️ <b>WARNING:</b> {ct['warning']}</span>"
                )
            if "note" in ct:
                extras += (
                    f"<span style='display:block;background:#e8f4fd;border-left:3px solid #3498db;"
                    f"padding:2px 5px;margin:2px 0;font-size:6.5pt;'>"
                    f"ℹ️ {ct['note']}</span>"
                )
            if "img" in ct:
                uri = self._img_data_uri(ct['img'])
                extras += (
                    f"<img src='{uri}' alt='Cable {ct['label']}' "
                    f"style='max-height:55px;display:block;margin:3px 0;'>"
                )
            cable_list_html += (
                f"<li style='margin-bottom:4px;'>"
                f"<b>{ct['label']}</b>: {ct['desc']}{extras}</li>"
            )

        cables_uri = self._img_data_uri(d['img_cables'])
        lines.append("<div style='page-break-before: always;'>")
        lines.append("<h1 style='font-size:11pt; margin-bottom:8px;'>CSI Flex Cable Selection Guide</h1>")
        lines.append("<p style='font-size:7.5pt; margin-bottom:6px;'>"
                     "Select the correct flex cable based on the Jetson board's CSI connector pitch "
                     "and the camera connector pitch.</p>")
        lines.append("<table style='width:auto; margin-bottom:10px;'><thead><tr>")
        lines.append("<th>Board</th><th>CSI connector</th>"
                     "<th>Dione (22-pin)</th>"
                     "<th>MicroCube / Crius1280 / SmartIR640 / Microlynx (15-pin)</th>"
                     "<th>iLumos (22-pin)</th>")
        lines.append(f"</tr></thead><tbody>{rows_html}</tbody></table>")
        lines.append(f"<div style='margin-bottom:8px;'>"
                     f"<img src='{cables_uri}' alt='CSI flex cables A–D' style='max-height:120px;'>"
                     f"<p style='font-size:6.5pt;color:#666;margin:2px 0;'>Cables A–D</p></div>")
        lines.append(f"<ul style='list-style:none;padding:0;margin:0;font-size:7pt;'>"
                     f"{cable_list_html}</ul>")
        lines.append("</div>")
        lines.append("</body></html>")
        return "\n".join(lines)

    def generate_pdf(self, html_file, pdf_file):
        """Generate PDF from a compact landscape HTML (no Git/Package columns)."""
        if not WEASYPRINT_AVAILABLE:
            print(f"⚠️  WeasyPrint not available - skipping PDF generation")
            print(f"   Install with: pip3 install weasyprint")
            return False

        try:
            pdf_html = self._generate_pdf_html()
            HTML(string=pdf_html, base_url=str(Path(html_file).parent)).write_pdf(pdf_file)
            print(f"✅ PDF matrix generated: {pdf_file}")
            return True
        except Exception as e:
            print(f"❌ PDF generation failed: {e}")
            return False


def main():
    """Main entry point"""
    tools_dir = Path(__file__).parent
    root_dir = tools_dir.parent
    yaml_file = tools_dir / 'deployment_matrix_data.yaml'
    markdown_file = root_dir / 'MIPI_DEPLOYMENT_MATRIX.md'
    html_file = root_dir / 'MIPI_DEPLOYMENT_MATRIX.html'
    pdf_file = root_dir / 'MIPI_DEPLOYMENT_MATRIX.pdf'

    if not yaml_file.exists():
        print(f"❌ Error: {yaml_file} not found")
        sys.exit(1)

    try:
        generator = DeploymentMatrixGenerator(yaml_file)

        if '--check' in sys.argv:
            print("🔍 Validating deployment matrix against eg_config.yaml...\n")
            issues = generator.validate()
            if issues:
                for issue in issues:
                    print(issue)
                warnings = [i for i in issues if i.startswith('⚠️')]
                print(f"\n{'❌' if warnings else '✅'} {len(warnings)} warning(s) found.")
            else:
                print("✅ No issues found.")
            sys.exit(1 if any(i.startswith('⚠️') for i in issues) else 0)

        print("🔄 Generating deployment matrix...")
        generator.generate_markdown(markdown_file)
        generator.generate_html(html_file)
        generator.generate_pdf(html_file, pdf_file)

        print(f"\n✅ All matrices generated successfully!")
        print(f"\nOutput files:")
        print(f"  - {markdown_file}")
        print(f"  - {html_file}")
        print(f"  - {pdf_file}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
