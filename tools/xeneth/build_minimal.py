#!/usr/bin/env python3
"""Compile the reference client with the actual Xeneth SDK packet codec."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--xeneth-source', required=True, type=Path)
p.add_argument('--cxx', default='g++')
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
here = Path(__file__).resolve().parent
sdk = a.xeneth_source.resolve() / 'Src/src_sdk'
header = here / 'eg_camera_gencp.h'
if not header.exists():
    header = here.parents[1] / 'sources/common/source/nvidia-oot/drivers/media/i2c/gencp-over-i2c/eg_camera_gencp.h'
inputs = [sdk / name for name in ('xccapi_gencp_cl_packet_handler.cpp', 'xccapi_gencp_cl_packet_handler.h', 'xccapi_gencp_cl_defs.h')]
for path in inputs + [header]:
    if not path.is_file(): p.error('Missing source: ' + str(path))
a.output.parent.mkdir(parents=True, exist_ok=True)
cmd = [a.cxx, '-std=c++11', '-O2', '-Wall', '-Wextra', '-Wno-endif-labels', '-Wno-sign-compare',
       '-include', 'cstring', '-I' + str(here), '-I' + str(header.parent),
       '-I' + str(here/'compat'), '-I' + str(sdk), str(here/'xeneth_minimal.cpp'),
       str(inputs[0]), '-o', str(a.output)]
subprocess.run(cmd, check=True)
manifest = {'command': cmd, 'sources': {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in inputs + [header, here/'xeneth_minimal.cpp', here/'eg_gencp_port.hpp']},
            'binary_sha256': hashlib.sha256(a.output.read_bytes()).hexdigest()}
a.output.with_suffix(a.output.suffix + '.build.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(a.output)
