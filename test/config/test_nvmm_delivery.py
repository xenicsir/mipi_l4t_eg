#!/usr/bin/env python3
"""Exercise the real plugin packaging block without building a kernel/package."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def staging_script():
    source = (ROOT/'l4t_gen_delivery_package.sh').read_text()
    start = source.index('copy_from_rootfs() {')
    end = source.index('\n}', start) + 3
    block = source.index('# Stage the optional plugin only')
    block_end = source.index('\n#******************************************************************************', block)
    # Packaging copies execute normally inside the test directory, without sudo.
    return ('set -e\nsudo() { "$@"; }\n' + source[start:end] + '\n' +
            source[block:block_end] + '\nprintf "%s\\n" "${EG_GST_RECOMMENDS[@]}"\n')


class PluginDeliveryTests(unittest.TestCase):
    def prepare(self, directory, version='36.5.0', plugin=True):
        base = Path(directory)
        source = base/'sources'/version/'Linux_for_Tegra/source/gst-egv4l2camera'
        source.mkdir(parents=True)
        (source/'LICENSE').write_text('Vendor notices\n')
        fs = base/'rootfs'
        library = fs/'usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstegv4l2camerasrc.so'
        library.parent.mkdir(parents=True)
        if plugin:
            library.write_bytes(b'plugin built for the target BSP')
        admin = fs/'var/lib/dpkg'; admin.mkdir(parents=True)
        (admin/'status').write_text('Package: nvidia-l4t-core\nStatus: install ok installed\n'
                                  'Architecture: arm64\nVersion: 36.5.0-12345\n'
                                  'Description: runtime fixture\n\n')
        env = dict(os.environ, ROOT_DIR=str(base), L4T_VERSION=version,
                   ROOTFS_DIR=str(fs), PACKAGE_NAME='package')
        return base, env

    def run_stage(self, env):
        return subprocess.run(['bash'], input=staging_script(), text=True,
                              env=env, cwd=env['ROOT_DIR'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_library_license_and_exact_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            base, env = self.prepare(directory)
            result = self.run_stage(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base/'package/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstegv4l2camerasrc.so').read_bytes(),
                             b'plugin built for the target BSP')
            self.assertEqual((base/'package/usr/share/doc'/Path(env['PACKAGE_NAME']).name/'copyright-egv4l2camerasrc').read_text(), 'Vendor notices\n')
            for name in ('gstreamer', 'cuda', '3d-core'):
                self.assertIn('nvidia-l4t-'+name+' (= 36.5.0-12345)', result.stdout)

    def test_declared_plugin_must_be_built(self):
        with tempfile.TemporaryDirectory() as directory:
            _, env = self.prepare(directory, plugin=False)
            result = self.run_stage(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('plugin missing', result.stderr)

    def test_legacy_without_overlay_stages_no_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            base, env = self.prepare(directory)
            env['L4T_VERSION'] = '32.7.1'
            result = self.run_stage(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((base/'package').exists())
            self.assertNotIn('nvidia-l4t-cuda', result.stdout)


if __name__ == '__main__':
    unittest.main()
