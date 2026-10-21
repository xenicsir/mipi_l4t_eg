#!/usr/bin/env python3
"""Check the shared camera ioctl ABI, wire payloads, CLI and installed layout."""
import contextlib
import errno
import importlib.util
import io
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import mock_open, patch

ROOT = Path(__file__).resolve().parents[2]
ROOTFS = ROOT / 'sources/common/Linux_for_Tegra/rootfs'
LIB = ROOTFS / 'usr/bin/egCamCtrl.py'
DRIVERS = ROOT / 'sources/common/source/nvidia-oot/drivers/media/i2c'
spec = importlib.util.spec_from_file_location('egCamCtrl', LIB)
ctrl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctrl)


class CameraControlTests(unittest.TestCase):
    def test_abi_against_kernel_structs_and_macros(self):
        """Compile the real UAPI declarations, independently of Python's packing."""
        for family, filename in (('ilumos', 'ilumos_core.c'), ('microlynx', 'microlynx_core.c'),
                                 ('titan', 'titan_core.c')):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as temp:
                source = (DRIVERS / filename).read_text()
                prefix = family.upper()
                declarations = '\n'.join(re.search(
                    r'struct ' + family + '_' + kind + r'_op\s*\{.*?\n\};', source, re.S)[0]
                    for kind in ('reg', 'str'))
                macros = '\n'.join(re.findall(
                    r'^#define ' + prefix + r'_(?:STR_MAX|IOCTL_\w+)[^\n]*',
                    source.replace('\\\n', ''), re.M))
                program = '#include <linux/types.h>\n#include <sys/ioctl.h>\n#include <stdio.h>\n'
                program += macros + '\n' + declarations + '\n'
                program += ('int main(void) {{ printf("%lu %lu %lu %zu %zu\\n", '
                            '(unsigned long){p}_IOCTL_READ_REG, '
                            '(unsigned long){p}_IOCTL_WRITE_REG, '
                            '(unsigned long){p}_IOCTL_READ_STR, '
                            'sizeof(struct {f}_reg_op), sizeof(struct {f}_str_op)); }}'
                            ).format(p=prefix, f=family)
                path = Path(temp)
                (path / 'abi.c').write_text(program)
                subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(path / 'abi.c'),
                                '-o', str(path / 'abi')], check=True)
                actual = tuple(map(int, subprocess.check_output([str(path / 'abi')]).split()))
                camera = ctrl.Camera('/dev/{}-9-0030'.format(family))
                self.assertEqual(actual, (camera.ioctl_read_reg, camera.ioctl_write_reg,
                                          camera.ioctl_read_str, 8, 264))

    def test_register_wire_payloads_and_float_bits(self):
        vectors = (0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x3F800000, 0xC0200000)
        for family in ctrl.PROFILES:
            camera = ctrl.Camera('/dev/{}-9-0030'.format(family))
            for value in vectors:
                with self.subTest(family=family, value=value):
                    def fake_ioctl(fd, request, buf):
                        self.assertEqual(buf[:4], b'\x18\x00\x0e\x50')
                        if request == camera.ioctl_read_reg:
                            self.assertEqual(bytes(buf[4:]), b'\0' * 4)
                            buf[4:] = struct.pack('<I', value)
                        else:
                            self.assertEqual(request, camera.ioctl_write_reg)
                            self.assertEqual(bytes(buf[4:]), struct.pack('<I', value))
                        return 0
                    with patch('builtins.open', mock_open()), patch.object(
                            ctrl.fcntl, 'ioctl', side_effect=fake_ioctl):
                        self.assertEqual(camera.read_reg32(0x500E0018), value)
                        camera.write_reg32(0x500E0018, value)
            for value in (0.0, -0.0, 1.25, -2.5, 1e-30, 1e30):
                raw = struct.pack('<f', value)
                with patch.object(camera, 'write_reg32') as write:
                    camera.write_reg32f(0x44, value)
                    self.assertEqual(struct.pack('<I', write.call_args.args[1]), raw)
                with patch.object(camera, 'read_reg32', return_value=struct.unpack('<I', raw)[0]):
                    self.assertEqual(struct.pack('<f', camera.read_reg32f(0x44)), raw)

    def test_strings_and_profile_limits(self):
        for family in ctrl.PROFILES:
            camera = ctrl.Camera('/dev/{}-9-0030'.format(family))
            def fake_ioctl(fd, request, buf):
                self.assertEqual(request, camera.ioctl_read_str)
                addr, length, data = struct.unpack('<II256s', buf)
                self.assertEqual((addr, length, data), (0x44, 64, b'\0' * 256))
                buf[8:72] = b'Titan' + b'\xff\0' * 29 + b'\xff'
                return 0
            with patch('builtins.open', mock_open()), patch.object(
                    ctrl.fcntl, 'ioctl', side_effect=fake_ioctl):
                self.assertEqual(camera.read_string(0x44), 'Titan')
            with patch('builtins.open') as opened:
                for length in (0, -1, camera.string_limit + 1):
                    with self.assertRaises(ValueError):
                        camera.read_string(0x44, length)
                opened.assert_not_called()

    def test_ilumos_long_strings(self):
        camera = ctrl.Camera('/dev/ilumos-9-0030')
        for length in (71, 256):
            def fake_ioctl(fd, request, buf):
                self.assertEqual(request, camera.ioctl_read_str)
                self.assertEqual(struct.unpack_from('<II', buf), (0x44, length))
                buf[8:8 + length] = b'A' * length
                return 0
            with patch('builtins.open', mock_open()), patch.object(ctrl.fcntl, 'ioctl', side_effect=fake_ioctl):
                self.assertEqual(camera.read_string(0x44, length), 'A' * length)

    def test_protocol_and_system_errors(self):
        camera = ctrl.Camera('/dev/microlynx-9-0051')
        with patch('builtins.open', mock_open()), patch.object(ctrl.fcntl, 'ioctl', return_value=0x8003):
            with self.assertRaisesRegex(OSError, '8003') as error:
                camera.write_reg32(0x44, 1)
            self.assertEqual(error.exception.errno, errno.EIO)
        with patch('builtins.open', mock_open()), patch.object(
                ctrl.fcntl, 'ioctl', side_effect=OSError(errno.ETIMEDOUT, 'timeout')):
            with self.assertRaises(OSError) as error:
                camera.read_reg32(0x44)
            self.assertEqual(error.exception.errno, errno.ETIMEDOUT)

    def test_explicit_device_and_camera_type(self):
        for name in ('/dev/dione-9-000e', '/dev/eg_ec-9-0016', '/dev/eg-ec-mipi-9-0016'):
            with self.assertRaises(ValueError):
                ctrl.Camera(name, 'titan')
        with self.assertRaises(ValueError):
            ctrl.Camera('/dev/ilumos-9-0030', 'titan')
        with self.assertRaises(ValueError):
            ctrl.Camera('/dev/my-camera')
        self.assertEqual(ctrl.Camera('/dev/my-camera', 'titan').camera_type, 'titan')
        with tempfile.TemporaryDirectory() as temp:
            alias = Path(temp) / 'camera'
            alias.symlink_to('/dev/microlynx-9-0051')
            self.assertEqual(ctrl.Camera(alias).camera_type, 'microlynx')

    def test_cli_rejects_bad_arguments_without_io(self):
        cases = [[], ['read_reg32', '0x44'],
                 ['/dev/titan-9-0030', 'read_reg32', '-1'],
                 ['/dev/titan-9-0030', 'write_reg32', '0x44', '0x100000000'],
                 ['/dev/titan-9-0030', 'read_string', '0x44', '0'],
                 ['/dev/ilumos-9-0030', 'read_string', '0x44', '257'],
                 ['--camera', 'titan', '/dev/ilumos-9-0030', 'read_reg32', '0x44'],
                 ['/dev/titan-9-0030', 'read_reg32', '0x44', 'surplus']]
        for args in cases:
            with self.subTest(args=args), patch('builtins.open') as opened:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    ctrl.main(args)
                self.assertEqual(error.exception.code, 2)
                opened.assert_not_called()

    def test_cli_output_and_device_binding(self):
        with patch.object(ctrl.Camera, 'read_reg32', return_value=1208), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ctrl.main(['/dev/titan-9-0030', 'read_reg32', '0x500E0000']), 0)
            self.assertIn('0x000004B8  (1208)', output.getvalue())
        with patch.object(ctrl.Camera, 'read_reg32', side_effect=OSError('no camera')), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(ctrl.main(['/dev/titan-9-0030', 'read_reg32', '0x44']), 1)
            self.assertNotIn('Traceback', output.getvalue())
        with patch('code.interact') as interact:
            self.assertEqual(ctrl.main(['/dev/titan-9-0030']), 0)
            self.assertEqual(interact.call_args.kwargs['local']['camera'].device, '/dev/titan-9-0030')

    def test_installed_layout_and_compatibility_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            rootfs = Path(temp)
            (rootfs / 'usr/bin').mkdir(parents=True)
            for name in ('egCamCtrl', 'ilumosCtrl', 'microlynxCtrl'):
                script = rootfs / 'usr/bin' / (name + '.py')
                shutil.copy(ROOTFS / 'usr/bin' / script.name, script)
                result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([sys.executable, str(script)], capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
            # Copy ONLY the generic script, under another name, away from /opt/eg.
            standalone = rootfs / 'standalone-control.py'
            shutil.copy(LIB, standalone)
            result = subprocess.run([sys.executable, str(standalone), '--help'],
                                    cwd=temp, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            dummy = rootfs / 'not-a-camera'
            dummy.touch()
            result = subprocess.run([sys.executable, str(standalone), '--camera', 'titan',
                                     str(dummy), 'read_reg32', '0x44'],
                                    cwd=temp, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(b'Error communicating with', result.stderr)
            self.assertNotIn(b'Traceback', result.stderr)
            # Legacy importable helpers share the implementation but bind their ABI.
            spec = importlib.util.spec_from_file_location('ilumosCtrl', rootfs / 'usr/bin/ilumosCtrl.py')
            legacy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(legacy)
            with patch.object(legacy._ctrl.Camera, 'read_reg32', return_value=42):
                self.assertEqual(legacy.read_reg32('/dev/custom', 0x44), 42)
            with self.assertRaises(ValueError):
                legacy.read_reg32('/dev/titan-9-0030', 0x44)


if __name__ == '__main__':
    unittest.main()
