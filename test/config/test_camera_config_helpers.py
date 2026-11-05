#!/usr/bin/env python3
"""Exercise live DT availability checks, including stock nodes without status."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_set.sh'


class LiveNodeTests(unittest.TestCase):
    def test_status_defaults_and_multiple_nodes(self):
        source = SCRIPT.read_text()
        function = re.search(r'^_live_node_active\(\) \{.*?^\}', source, re.M | re.S).group()
        for values, expected in [([], 1), ([None], 0), ([b'okay\0'], 0),
                                 ([b'disabled\0'], 1), ([b'disabled\0', None], 0)]:
            with self.subTest(values=values), tempfile.TemporaryDirectory() as tmp:
                paths = []
                for i, value in enumerate(values):
                    node = Path(tmp) / ('sensor' + str(i))
                    node.mkdir()
                    if value is not None:
                        (node / 'status').write_bytes(value)
                    paths.append(str(node))
                # Only replace discovery; execute the production helper unchanged.
                body = 'find() { for node in "${nodes[@]}"; do printf "%s\\n" "$node"; done; }\n'
                body += 'nodes=("$@")\n' + function + '\n_live_node_active "sensor*"\n'
                result = subprocess.run(['bash', '-c', body, 'helper-test'] + paths,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
