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

        self.platforms_by_id = {p['id']: p for p in self.data['platforms']}
        self.cameras_by_id = {c: self.data['cameras'][c] for c in self.data['cameras']}
        self.matrix_data = self.data['deployment_matrix']
        self.github_repo = self.data.get('github_repo', '')
        self.package_repo_base = self.data.get('package_repo_base', '')

        # Load camera technical details from eg_config.yaml
        camera_db_path = Path(yaml_file).parent / 'eg_config.yaml'
        with open(camera_db_path, 'r') as f:
            self.camera_db = yaml.safe_load(f)

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
        return sorted(versions, key=lambda x: tuple(int(p) if p.isdigit() else p
                                                     for p in str(x).split('.')))

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

            # For each platform
            for platform in self.data['platforms']:
                platform_id = platform['id']
                f.write(f"## {platform['name']}\n\n")

                if 'description' in platform:
                    f.write(f"**{platform['description']}**\n\n")

                if 'notes' in platform:
                    f.write(f"> **Note:** {platform['notes']}\n\n")

                # Build table header
                f.write("| L4T Version |")
                for cam_id in camera_ids:
                    cam_name = self.data['cameras'][cam_id]['name']
                    f.write(f" {cam_name} | Git | Package |")
                f.write("\n")

                # Header separator
                f.write("|" + " --- |" * (1 + len(camera_ids) * 3))
                f.write("\n")

                # Data rows
                for version in l4t_versions:
                    f.write(f"| `{version}` |")
                    for cam_id in camera_ids:
                        status, git_branch, deb_pkg = self.get_status(platform_id, cam_id, version)

                        if status:
                            icon = self.STATUS_ICONS.get(status, '❓')
                            label = self.STATUS_LABELS.get(status, status)
                            f.write(f" {icon} {label} |")

                            # Git link
                            if git_branch:
                                git_url = f"{self.github_repo}/tree/{git_branch}"
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
                    f.write("| Pixel Format | Pixel Clock | CSI Clock |\n")
                    f.write("| --- | --- | --- |\n")
                    for mode in res_entry['modes']:
                        pix_mhz = mode['pix_clk_hz'] / 1e6
                        pix_str = f"{pix_mhz:.1f}".rstrip('0').rstrip('.')
                        f.write(f"| {mode['pixel_format']} | {pix_str} MHz | {mode['csi_clock_mhz']} MHz |\n")
                f.write("\n")

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

            if 'notes' in platform:
                html_content += f'        <div class="platform-notes">📌 <strong>Note:</strong> {platform["notes"]}</div>\n'

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
                    <th>L4T Version</th>
"""
            for cam_id in camera_ids:
                cam_name = self.data['cameras'][cam_id]['name']
                html_content += f"                    <th colspan='3'>{cam_name}</th>\n"

            html_content += """                </tr>
                <tr>
                    <th></th>
"""
            for _ in camera_ids:
                html_content += "                    <th style='font-size: 0.85em;'>Status</th>\n"
                html_content += "                    <th style='font-size: 0.85em;'>Git</th>\n"
                html_content += "                    <th style='font-size: 0.85em;'>Package</th>\n"

            html_content += """                </tr>
            </thead>
            <tbody>
"""

            for version in l4t_versions:
                html_content += f'                <tr>\n                    <td class="version-cell">{version}</td>\n'

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
                        if git_branch and self.github_repo:
                            git_url = f"{self.github_repo}/tree/{git_branch}"
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
                resolutions_html += '<table><thead><tr><th>Pixel Format</th><th>Pixel Clock</th><th>CSI Clock</th></tr></thead><tbody>\n'
                for mode in res_entry['modes']:
                    pix_mhz = mode['pix_clk_hz'] / 1e6
                    pix_str = f"{pix_mhz:.1f}".rstrip('0').rstrip('.')
                    resolutions_html += f'<tr><td>{mode["pixel_format"]}</td><td>{pix_str} MHz</td><td>{mode["csi_clock_mhz"]} MHz</td></tr>\n'
                resolutions_html += '</tbody></table>\n'

            html_content += f"""            <div class="camera-card">
                <h4>{cam['name']}</h4>
                {notes_html}
                {resolutions_html}
            </div>
"""

        html_content += """        </div>
    </div>
</body>
</html>
"""

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
        td.ver { font-family: monospace; font-size: 7pt; text-align: left;
                 color: #1a3a5c; white-space: nowrap; }
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

            lines.append("<table><thead><tr>")
            lines.append("<th class='ver-col'>L4T</th>")
            for cam_id in camera_ids:
                cam_name = self.data['cameras'][cam_id]['name']
                lines.append(f"<th>{cam_name}</th>")
            lines.append("</tr></thead><tbody>")

            for version in l4t_versions:
                row_has_data = any(
                    self.get_status(pid, cid, version)[0] is not None
                    for cid in camera_ids
                )
                if not row_has_data:
                    continue

                lines.append(f"<tr><td class='ver'>{version}</td>")
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
                lines.append("</tr></thead><tbody>")
                for mode in res_entry['modes']:
                    pix_mhz = mode['pix_clk_hz'] / 1e6
                    pix_str = f"{pix_mhz:.1f}".rstrip('0').rstrip('.')
                    lines.append(f"<tr><td style='font-size:6.5pt;'>{mode['pixel_format']}</td>"
                                 f"<td style='font-size:6.5pt;'>{pix_str} MHz</td>"
                                 f"<td style='font-size:6.5pt;'>{mode['csi_clock_mhz']} MHz</td></tr>")
                lines.append("</tbody></table>")

            lines.append("</div>")

        lines.append("</div></div>")
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
    docs_dir = Path(__file__).parent
    yaml_file = docs_dir / 'deployment_matrix_data.yaml'
    markdown_file = docs_dir / 'MIPI_DEPLOYMENT_MATRIX.md'
    html_file = docs_dir / 'MIPI_DEPLOYMENT_MATRIX.html'
    pdf_file = docs_dir / 'MIPI_DEPLOYMENT_MATRIX.pdf'

    if not yaml_file.exists():
        print(f"❌ Error: {yaml_file} not found")
        sys.exit(1)

    try:
        generator = DeploymentMatrixGenerator(yaml_file)

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
