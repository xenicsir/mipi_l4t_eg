#!/usr/bin/env python3
"""
egcfg.py — CLI query helper for eg_config.yaml (replaces jq on l4t_versions.json)

Usage:
  python3 tools/egcfg.py <query> [eg_config.yaml]

Queries:
  versions                          space-separated list of all versions
  vendors                           space-separated list of all vendors
  carriers                          space-separated list of all carriers
  version.VERS.vendors              vendors for a specific version
  version.VERS.standalone.V.C       "true" or "false"
  version.VERS.sources.TYPE.FIELD   e.g. version.35.6.2.sources.public.url
  version.VERS.toolchain.FIELD      e.g. version.35.6.2.toolchain.prefix
  vendor.NAME.carriers              carriers for a vendor
  vendor.NAME.default_carrier       default carrier for a vendor
  carrier.NAME.defconfig            defconfig for a carrier
  carrier.NAME.dir_suffix           dir_suffix for a carrier

Exit codes: 0 = ok, 1 = key not found or error
"""

import sys
import yaml
from pathlib import Path

def load(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)

def query(cfg, q):
    parts = q.split('.')

    # versions
    if q == 'versions':
        vers = sorted(cfg['versions'].keys(),
                      key=lambda x: tuple(int(p) if p.isdigit() else p
                                          for p in x.split('.')))
        return ' '.join(vers)

    # vendors
    if q == 'vendors':
        return ' '.join(sorted(cfg['vendors'].keys()))

    # carriers
    if q == 'carriers':
        return ' '.join(sorted(cfg['carriers'].keys()))

    # version.VERS.*
    # Version keys may contain dots (e.g. "35.6.2") — try longest match first
    if parts[0] == 'version' and len(parts) >= 3:
        for end in range(len(parts), 1, -1):
            vers_key = '.'.join(parts[1:end])
            if vers_key not in cfg['versions']:
                continue
            rest = parts[end:]
            v = cfg['versions'][vers_key]
            # version.VERS.vendors
            if rest == ['vendors']:
                return ' '.join(v.get('vendors', []))
            # version.VERS.standalone.VENDOR.CARRIER
            if len(rest) == 3 and rest[0] == 'standalone':
                val = v.get('standalone', {}).get(rest[1], {}).get(rest[2], False)
                return 'true' if val else 'false'
            # version.VERS.sources.TYPE.FIELD
            if len(rest) == 3 and rest[0] == 'sources':
                return v.get('sources', {}).get(rest[1], {}).get(rest[2], '')
            # version.VERS.toolchain.FIELD
            if len(rest) == 2 and rest[0] == 'toolchain':
                return v.get('toolchain', {}).get(rest[1], '')
        return None

    # vendor.NAME.*
    if parts[0] == 'vendor' and len(parts) >= 3:
        name = parts[1]
        rest = parts[2:]
        v = cfg['vendors'].get(name, {})
        if rest == ['carriers']:
            return ' '.join(v.get('carriers', []))
        if rest == ['default_carrier']:
            return v.get('default_carrier', '')

    # carrier.NAME.*
    if parts[0] == 'carrier' and len(parts) == 3:
        name = parts[1]
        field = parts[2]
        return cfg['carriers'].get(name, {}).get(field, '')

    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    q = sys.argv[1]

    # Config file: optional 2nd arg, else look next to this script's parent
    if len(sys.argv) >= 3:
        config_path = Path(sys.argv[2])
    else:
        config_path = Path(__file__).resolve().parent.parent / 'eg_config.yaml'

    if not config_path.exists():
        print(f"Error: config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    cfg = load(config_path)
    result = query(cfg, q)

    if result is None:
        sys.exit(1)

    print(result, end='')


if __name__ == '__main__':
    main()
