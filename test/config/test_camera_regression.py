#!/usr/bin/env python3
"""Check hardware test discovery, command construction and recovery bounds."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('camera_regression', ROOT/'test/hardware/run_camera_regression.py')
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CONFIG = '''  Port 0: MicroCube (connected)
    Video device: /dev/video7
    I2C device: /dev/eg-ec-mipi-42-0016
    Sysfs: /sys/bus/i2c/devices/42-0016
v4l2-ctl -d /dev/video7 --stream-mmap --set-fmt-video=width=640,height=480,pixelformat="Y16 "
rt_frame_monitor.py -d /dev/video7 --display
gst-launch-1.0 -v v4l2src device=/dev/video7 ! "video/x-raw, format=(string)GRAY16_LE, width=640, height=480" ! videoconvert ! autovideosink sync=false
  Port 1: Dione (not connected)
'''


class RegressionTests(unittest.TestCase):
    def test_discovery_uses_generated_devices_and_skips_disconnected(self):
        cameras = MODULE.parse_configuration(CONFIG.replace('connected)', '\x1b[32mconnected\x1b[0m)'))
        self.assertEqual(len(cameras), 2)
        self.assertTrue(cameras[0].connected)
        self.assertTrue(cameras[0].enginecore)
        self.assertEqual(cameras[0].key, '42-0016')
        self.assertEqual(cameras[0].video, '/dev/video7')
        self.assertFalse(cameras[1].connected)
        self.assertEqual(MODULE.format_spec(cameras[0].groups[0]), (640, 480, 'Y16 '))
        self.assertEqual(MODULE.ec_code("'AR24' (BGRA)"), 21)
        self.assertEqual(MODULE.ec_code("'AB24' (RGBA)"), 21)
        with self.assertRaises(ValueError):
            MODULE.ec_code('unverified')

    def test_y14_range_check_follows_the_reported_layout(self):
        self.assertFalse(MODULE.parse_configuration(CONFIG)[0].conformant_y14)
        text = CONFIG.replace('v4l2-ctl -d', '    Y14 layout:   14 bits right-aligned, high bits 0\nv4l2-ctl -d', 1)
        self.assertTrue(MODULE.parse_configuration(text)[0].conformant_y14)

    def test_optional_gstreamer_variant_keeps_the_primary_full_frame_command(self):
        primary = MODULE.parse_configuration(CONFIG)[0].groups[0]['gst']
        text = CONFIG.replace('  Port 1:',
                              'gst-launch-1.0 v4l2src ! videocrop bottom=127 ! autovideosink\n  Port 1:')
        self.assertEqual(MODULE.parse_configuration(text)[0].groups[0]['gst'], primary)

    def test_effective_format_keeps_dimensions_and_byte_order(self):
        value = MODULE.parse_negotiated_format("Width/Height : 1280/1024\nPixel Format : 'Y16 -BE'\nSize Image : 2621440\n")
        self.assertEqual(value, dict(format='Y16 -BE', width=1280, height=1024, image_size=2621440))
        self.assertEqual(MODULE.parse_negotiated_format('')['image_size'], 0)

    def test_commands_preserve_caps_and_display(self):
        group = MODULE.parse_configuration(CONFIG)[0].groups[0]
        command = MODULE.streaming_command('gst', group, 60, Path('/tmp/logs'))
        self.assertIn('num-buffers=60', command)
        self.assertIn('video/x-raw, format=(string)GRAY16_LE, width=640, height=480', command)
        self.assertIn('autovideosink', command)
        self.assertNotIn('fakesink', command)
        raw = MODULE.streaming_command('v4l2', group, 60, Path('/tmp/logs'), '/tmp/raw')
        self.assertIn('--set-fmt-video=width=640,height=480,pixelformat=Y16 ', raw)
        self.assertIn('--stream-count=60', raw)

    def runner(self, path):
        options = MODULE.parser().parse_args(['--output', str(Path(path)/'logs'), '--recoveries', '2'])
        runner = MODULE.Runner(options)
        runner.refresh = Mock(return_value=MODULE.parse_configuration(CONFIG)[0])
        runner.enumerate_formats = Mock(return_value=['Y16 ', 'AR24', 'AB24', 'YUYV'])
        runner.run = Mock(return_value=({}, ''))
        runner.event = Mock()
        runner.set_ec_format = Mock()
        return runner

    def test_failed_capture_is_not_hidden_and_recovery_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.capture = Mock(return_value={'pass': False})
            self.assertFalse(runner.test_group('42-0016', 'Y16 ', code=20))
            self.assertEqual(runner.set_ec_format.call_count, 2)
            self.assertEqual(runner.capture.call_count, 3)
            self.assertTrue(all(call.args[2] == 'v4l2' for call in runner.capture.call_args_list))
            self.assertEqual(len(runner.results[0]['attempts']), 3)

    def test_successful_recovery_retains_first_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.capture = Mock(side_effect=[{'pass': False}, {'pass': True}, {'pass': True}, {'pass': True}])
            self.assertTrue(runner.test_group('42-0016', 'Y16 ', code=20))
            self.assertEqual(runner.set_ec_format.call_count, 1)
            self.assertFalse(runner.results[0]['attempts'][0]['tools']['v4l2']['pass'])
            self.assertTrue(runner.results[0]['passed'])

    def test_control_commands_are_paced_and_only_reload_enginecore(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            camera.sysfs = str(Path(tmp)/'sysfs')
            Path(camera.sysfs).mkdir()
            pixel_format = Path(camera.sysfs)/'pixel_format'
            pixel_format.write_text("'Y16 ' (greyscale)")
            runner.discover = Mock(return_value=[camera])
            runner.idle = Mock()
            runner.pause = Mock()
            def run(label, args, **kwargs):
                if args == ['modprobe', 'eg_ec_mipi']:
                    pixel_format.write_text("'AR24' (BGRA)")
                return {}, 'OK'
            runner.run = Mock(side_effect=run)
            MODULE.Runner.set_ec_format(runner, camera.key, 21)
            commands = [call.args[1] for call in runner.run.call_args_list]
            writes = [command[-1] for command in commands if command[0] == 'ECSwCtrl']
            self.assertEqual(writes, ['wu 0x260 21', 'wu 0x2F0 0', 'wu 0x8 1'])
            self.assertEqual([c for c in commands if c[0] in ('rmmod', 'modprobe')],
                             [['rmmod', 'eg_ec_mipi'], ['modprobe', 'eg_ec_mipi']])
            self.assertIn(5, [call.args[0] for call in runner.pause.call_args_list])

    def test_recovery_does_not_rewrite_persistent_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            camera.sysfs = tmp
            (Path(tmp)/'pixel_format').write_text("'Y16 ' (greyscale)")
            runner.discover = Mock(return_value=[camera])
            runner.idle = Mock()
            runner.pause = Mock()
            runner.run = Mock(return_value=({}, 'OK'))
            MODULE.Runner.set_ec_format(runner, camera.key, 20, reboot=True)
            commands = [call.args[1] for call in runner.run.call_args_list]
            self.assertEqual([c[-1] for c in commands if c[0] == 'ECSwCtrl'], ['wu 0x8 1'])

    def test_timeout_stops_capture_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            code = ('import subprocess,sys,time; '
                    'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                    'print("CHILD",p.pid,flush=True); time.sleep(30)')
            record, output = MODULE.Runner.run(runner, 'timeout', [sys.executable, '-c', code], timeout=.2)
            self.assertEqual(record['returncode'], 124)
            import re
            child = int(re.search(r'CHILD (\d+)', output)[1])
            stat = Path('/proc')/str(child)/'stat'
            if stat.exists():
                self.assertIn(stat.read_text().split()[2], ('Z', 'X'))

    def test_control_profiles_keep_camera_specific_register_maps(self):
        group = MODULE.parse_configuration(CONFIG)[0].groups[0]
        for family, addresses in [('ilumos', ['0x50000000', '0x50000004', '0x50000008']),
                                  ('titan', ['0x500e0000', '0x500e0004', '0x500e0010']),
                                  ('microlynx', ['0x500e0008', '0x500e000c', '0x500e0018'])]:
            camera = MODULE.Camera(0, family, True, device='/dev/' + family + '-42-0030', groups=[group])
            plan = MODULE.register_read_plan(camera)
            self.assertEqual([c['command'][-1] for c in plan[:3]], addresses)
            self.assertTrue(all(c['command'][0] == 'egCamCtrl.py' for c in plan))
            self.assertEqual([c['command'][-3:] for c in plan[3:]],
                             [['read_string', '0x44', '64'], ['read_string', '0x144', '64']])
        self.assertEqual(MODULE.register_read_plan(MODULE.parse_configuration(CONFIG)[0]), [])

    def test_dione_reads_use_discovered_fpga_address_without_forcing(self):
        group = MODULE.parse_configuration(CONFIG)[0].groups[0]
        camera = MODULE.Camera(0, 'Dione', True, device='/dev/dioneir-i2c-12-000e-5b', groups=[group])
        plan = MODULE.register_read_plan(camera)
        self.assertEqual(plan[0]['command'], ['dioneCtrl.py', '--device-type', 'I2C', '--bus', '12',
                                             '--dev-addr', '0x5b', 'read_reg32', '0x2f028'])
        self.assertFalse(any('--force-slave' in c['command'] or '--gencp-enable' in c['command'] for c in plan))
        camera.device = '/dev/dioneir-invalid'
        with self.assertRaises(ValueError):
            MODULE.register_read_plan(camera)

    def test_register_values_are_checked_in_addition_to_exit_status(self):
        check = dict(kind='integer', expected=1280)
        self.assertEqual(MODULE.validate_register_read(check, 0, '0x50000000 = 0x00000500 (1280)'), (True, 1280))
        self.assertEqual(MODULE.validate_register_read(check, 0, '0x00000500 (1280)'), (True, 1280))
        self.assertFalse(MODULE.validate_register_read(check, 0, '0x50000000 = 0x00000400 (1024)')[0])
        self.assertFalse(MODULE.validate_register_read(check, 1, '0x00000500 (1280)')[0])
        self.assertFalse(MODULE.validate_register_read(dict(kind='string'), 0, '0x44 = ')[0])
        self.assertTrue(MODULE.validate_register_read(dict(kind='string'), 0, '0x44 = iLumos')[0])

    def test_control_failure_is_recorded_and_stops_remaining_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            camera.device = '/dev/ilumos-42-0030'
            runner.pause = Mock()
            runner.run = Mock(return_value=({'returncode': 0, 'log': 'bad.log'}, '0x50000000 = 0xFFFFFFFF'))
            self.assertFalse(runner.test_registers(camera, 'before-video'))
            self.assertFalse(runner.register_results[0]['passed'])
            self.assertEqual(runner.run.call_count, 1)

    def test_registers_only_failure_sets_exit_status_without_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            camera.device = '/dev/ilumos-42-0030'
            runner.options.registers_only = True
            runner.setup = Mock()
            runner.discover = Mock(return_value=[camera])
            runner.idle = Mock()
            runner.pause = Mock()
            runner.run = Mock(return_value=({'returncode': 1, 'log': 'failed.log'}, 'Error: I/O'))
            runner.capture = Mock()
            self.assertEqual(runner.execute(), 1)
            runner.capture.assert_not_called()
            runner.set_ec_format.assert_not_called()

    def test_non_enginecore_failure_does_not_reboot_camera(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.capture = Mock(return_value={'pass': False})
            self.assertFalse(runner.test_group('42-0016', 'Y16 '))
            runner.set_ec_format.assert_not_called()

    def test_xeneth_checks_width_and_read_count(self):
        for output, expected in [('reads=20 value=00000280', True),
                                 ('reads=19 value=00000280', False),
                                 ('reads=20 value=00000400', False)]:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as tmp:
                runner = self.runner(tmp)
                camera = runner.refresh.return_value
                camera.device = '/dev/microlynx-42-0030'
                runner.pause = Mock()
                runner.run = Mock(side_effect=[({'returncode': 0}, 'model=MicroLynx'),
                                               ({'returncode': 0, 'log': 'reads.log'}, output)])
                with patch.object(MODULE.shutil, 'which', return_value='/tmp/egXenethMinimal'):
                    self.assertEqual(runner.test_xeneth(camera, 'before-video'), expected)
                self.assertEqual(runner.xeneth_results[0]['passed'], expected)

    def test_xeneth_basic_not_applicable_is_specific_to_ilumos(self):
        for family, expected in [('ilumos', True), ('microlynx', False), ('titan', False)]:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                runner = self.runner(tmp)
                camera = runner.refresh.return_value
                camera.device = '/dev/' + family + '-42-0030'
                runner.pause = Mock()
                runner.run = Mock(return_value=({'returncode': 3, 'log': 'probe.log'}, 'not supported'))
                with patch.object(MODULE.shutil, 'which', return_value='/tmp/egXenethMinimal'):
                    self.assertEqual(runner.test_xeneth(camera, 'before-video'), expected)
                self.assertEqual(runner.run.call_count, 1)

    def test_xeneth_missing_client_fails_and_excluded_families_do_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            self.assertTrue(runner.test_xeneth(camera, 'before-video'))
            camera.device = '/dev/dioneir-i2c-42-000e-5d'
            self.assertTrue(runner.test_xeneth(camera, 'before-video'))
            self.assertEqual(runner.xeneth_results, [])
            camera.device = '/dev/ilumos-42-0030'
            with patch.object(MODULE.shutil, 'which', return_value=None):
                self.assertFalse(runner.test_xeneth(camera, 'before-video'))
            runner.run.assert_not_called()

    def test_registers_only_keeps_xeneth_failure_in_exit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.options.registers_only = True
            runner.setup = Mock()
            runner.discover = Mock(return_value=[runner.refresh.return_value])
            runner.idle = Mock()
            runner.test_registers = Mock(return_value=True)
            def failure(camera, phase):
                runner.xeneth_results.append({'passed': False})
                return False
            runner.test_xeneth = Mock(side_effect=failure)
            self.assertEqual(runner.execute(), 1)


if __name__ == '__main__':
    unittest.main()
