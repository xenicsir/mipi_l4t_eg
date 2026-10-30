#!/usr/bin/env python3
"""Check hardware test discovery, command construction and recovery bounds."""
from pathlib import Path
import importlib.util
import sys
import json
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

    def test_hardware_pipeline_is_kept_separately(self):
        text = CONFIG.replace('  Port 1:', 'env __GL_YIELD=USLEEP gst-launch-1.0 -e -v egv4l2camerasrc device=/dev/video7 ! "video/x-raw(memory:NVMM),format=YUY2,width=640,height=480" ! nvvidconv compute-hw=2 ! nv3dsink sync=false\n  Port 1:')
        group = MODULE.parse_configuration(text)[0].groups[0]
        self.assertIn('v4l2src', group['gst'])
        self.assertIn('egv4l2camerasrc', group['gst_nvmm'])
        command = MODULE.streaming_command('gst_nvmm', group, 60, Path('/tmp/logs'))
        self.assertIn('num-buffers=60', command)
        self.assertLess(command.index('identity'), command.index('nvvidconv'))
        self.assertIn('video/x-raw(memory:NVMM),format=YUY2,width=640,height=480', command)

    def test_nvmm_not_applicable_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.capture = Mock(return_value={'pass': True})
            self.assertTrue(runner.test_group('42-0016', 'Y16 ', code=20))
            tools = runner.results[0]['attempts'][0]['tools']
            self.assertEqual(tools['monitor-nvmm']['status'], 'not applicable')
            self.assertNotIn('pass', tools['monitor-nvmm'])
            self.assertEqual([c.args[4] for c in runner.capture.call_args_list if c.args[2] == 'monitor'], ['classic', 'auto'])

    def test_camera_rate_requires_a_real_positive_float(self):
        self.assertEqual(MODULE.parse_frame_rate('60.000000\n'), 60)
        self.assertEqual(MODULE.parse_frame_rate('29.97'), 29.97)
        for value in ['!-128', 'OK', 'nan', 'inf', '0', '-1', '0x3c 60']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.parse_frame_rate(value)

    def test_rate_comparison_excludes_startup_but_rejects_slow_streams(self):
        times = [0] + [0.15+i/60 for i in range(240)]
        measured = MODULE.timestamp_cadence(times)
        self.assertTrue(MODULE.rate_matches(measured,60,.03))
        slow = MODULE.timestamp_cadence([i/30 for i in range(180)])
        self.assertFalse(MODULE.rate_matches(slow,60,.03))
        self.assertFalse(MODULE.rate_matches(MODULE.timestamp_cadence([0,.1]),60,.03))
        self.assertFalse(MODULE.rate_matches(MODULE.timestamp_cadence([0,0,1]),60,.03))

    def test_real_timestamp_formats_are_parsed(self):
        raw='\n'.join('cap dqbuf: 0 seq: %d bytesused: 10 ts: %.6f delta: 16.667 ms' % (i,100+i/60) for i in range(180))
        self.assertTrue(MODULE.rate_matches(MODULE.stream_cadence('v4l2',raw)['capture'],60,.03))
        gst='\n'.join('last-message = chain   pts: 0:00:%.9f, duration: 0:00:00.016666666' % (i/60) for i in range(180))
        self.assertTrue(MODULE.rate_matches(MODULE.stream_cadence('gst_nvmm',gst)['capture'],60,.03))
        self.assertEqual(MODULE.stream_cadence('monitor','no measured rates'),{})

    def test_environment_scope_restores_local_display_even_after_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner=self.runner(tmp); previous=runner.env
            with self.assertRaises(RuntimeError):
                with runner.environment({'DISPLAY':'localhost:11.0'}):
                    self.assertEqual(runner.env['DISPLAY'],'localhost:11.0')
                    raise RuntimeError('failure')
            self.assertIs(runner.env,previous)

    def test_enginecore_reference_uses_rf_feature_and_rejects_exit_zero_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.pause = Mock()
            camera = runner.refresh.return_value
            runner.run = Mock(return_value=({'returncode': 0}, '60.000000'))
            self.assertEqual(MODULE.Runner.read_frame_rate(runner, camera), 60)
            self.assertEqual(runner.run.call_args.args[1][-1], 'rf 0x210')
            runner.run = Mock(return_value=({'returncode': 0}, '!-128'))
            with self.assertRaises(RuntimeError):
                MODULE.Runner.read_frame_rate(runner, camera)
            self.assertFalse(runner.fps_reads[-1]['passed'])

    def test_configuration_matrix_checks_defaults_all_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.capture = Mock(return_value={'pass': True})
            camera = runner.refresh.return_value
            payload = dict(camera_count=2, cameras={'port_0': {'video_device':camera.video, 'status':'connected'}, 'port_1':{'status':'not connected'}})
            def run(label, args, **kwargs):
                if args[0] == 'rt_frame_monitor.py':
                    return {'returncode': 2}, 'NVMM rendering requires local X11'
                return {'returncode': 0}, json.dumps(payload) if '--json' in args else CONFIG
            runner.run = Mock(side_effect=run)
            self.assertTrue(MODULE.Runner.test_environments(runner, camera, camera.groups[0], 'selection'))
            config_results = [r for r in runner.environment_results if r['test'].startswith('config-')]
            self.assertEqual(len(config_results), 9)
            self.assertEqual({r['context'] for r in config_results}, {'local','forwarded-selection','no-display'})
            self.assertEqual(runner.env['DISPLAY'], ':0')
            # A duplicate full-frame command must not be hidden by setdefault parsing.
            runner.run = Mock(side_effect=lambda label,args,**kwargs: ({'returncode':2},'local X11') if args[0]=='rt_frame_monitor.py' else ({'returncode':0},json.dumps(payload) if '--json' in args else CONFIG.replace('  Port 1:', 'gst-launch-1.0 v4l2src ! videoconvert ! autovideosink\n  Port 1:')))
            self.assertFalse(MODULE.Runner.test_environments(runner, camera, camera.groups[0], 'duplicate'))

    def test_direct_nvmm_headless_pipeline_has_a_counting_probe(self):
        group = {'gst_nvmm': ['gst-launch-1.0', '-v', 'egv4l2camerasrc',
                 'device=/dev/video0', '!', 'video/x-raw(memory:NVMM),format=RGBA',
                 '!', 'fakesink', 'sync=false']}
        command = MODULE.streaming_command('gst_nvmm', group, 60, Path('/tmp/data'))
        self.assertIn('num-buffers=60', command)
        self.assertLess(command.index('identity'), command.index('fakesink'))

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
        runner.read_ec_format = Mock(return_value=20)
        runner.read_frame_rate = Mock(return_value=None)
        runner.test_environments = Mock(return_value=True)
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

    def test_classic_monitor_corruption_fails_even_with_zero_exit_and_all_frames(self):
        for corrupt in (0, 1):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                runner = self.runner(tmp)
                runner.pause = Mock()
                camera = runner.refresh.return_value
                text = ('BACKEND requested=classic selected=classic reason=test\n'
                        'frame=59 corrupt=%d sequence_gaps=0\n' % corrupt)
                runner.run = Mock(return_value=({'returncode': 0, 'seconds': 2,
                                                'log': 'monitor.log'}, text))
                record = runner.capture(camera, camera.groups[0], 'monitor',
                                        'classic', 'classic', display_context='headless')
                self.assertEqual(record['corrupt_buffers'], corrupt)
                self.assertEqual(record['functional_pass'], corrupt == 0)
                self.assertEqual(record['pass'], corrupt == 0)

    def test_gstreamer_corruption_fails_even_with_eos_and_all_buffers(self):
        for corrupt in (0, 1):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                runner = self.runner(tmp)
                runner.pause = Mock()
                camera = runner.refresh.return_value
                text = '\n'.join('last-message = chain (bytes, flags: %s , meta: GstVideoMeta)' %
                                 ('00000140 discont corrupted' if corrupt and i == 0 else '00000000')
                                 for i in range(60)) + '\nGot EOS from element pipeline0\n'
                runner.run = Mock(return_value=({'returncode': 0, 'seconds': 2,
                                                'log': 'gst.log'}, text))
                record = runner.capture(camera, camera.groups[0], 'gst', 'gst',
                                        display_context='headless')
                self.assertEqual(record['corrupt_buffers'], corrupt)
                self.assertEqual(record['buffers_reported'], 60)
                self.assertEqual(record['pass'], corrupt == 0)

    def test_v4l2_discarded_error_buffer_fails_even_with_complete_raw_file(self):
        for corrupt in (0, 1):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                runner = self.runner(tmp)
                runner.pause = Mock()
                camera = MODULE.parse_configuration(CONFIG.replace('640', '2').replace('480', '1'))[0]
                def run(label, args, **kwargs):
                    if '--get-fmt-video' in args:
                        return {}, "Width/Height : 2/1\nPixel Format : 'Y16 '\nSize Image : 4\n"
                    raw_path = next(a.split('=', 1)[1] for a in args if a.startswith('--stream-to='))
                    Path(raw_path).write_bytes(b'\x00\x00\x01\x00' * 60)
                    text = 'cap dqbuf: 0 seq: 0 bytesused: 4 ts: 1.0 (%sts-monotonic)\n' % (
                        'error, ' if corrupt else '')
                    return {'returncode': 0, 'seconds': 2, 'log': 'raw.log'}, text
                runner.run = Mock(side_effect=run)
                record = runner.capture(camera, camera.groups[0], 'v4l2', 'raw')
                self.assertEqual(record['bytes'], record['expected_bytes'])
                self.assertEqual(record['corrupt_buffers'], corrupt)
                self.assertEqual(record['pass'], corrupt == 0)

    def test_successful_recovery_retains_first_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.capture = Mock(side_effect=[{'pass': False}] + [{'pass': True}] * 4)
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
            runner.read_ec_format = Mock(side_effect=[20,21])
            MODULE.Runner.set_ec_format(runner, camera.key, 21)
            commands = [call.args[1] for call in runner.run.call_args_list]
            writes = [command[-1] for command in commands if command[0] == 'ECSwCtrl']
            self.assertEqual(writes, ['wu 0x260 21', 'wu 0x2F0 0', 'wu 0x8 1'])
            self.assertEqual([c for c in commands if c[0] in ('rmmod', 'modprobe')],
                             [['rmmod', 'eg_ec_mipi'], ['modprobe', 'eg_ec_mipi']])
            self.assertEqual([call.args[0] for call in runner.pause.call_args_list], [5, 5, 5, 5, 5])

    def test_enginecore_delay_does_not_slow_other_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            self.assertEqual(runner.options.control_pause, 2)
            self.assertEqual(runner.enginecore_control_pause(), 5)
            runner.pause = Mock()
            runner.run = Mock(return_value=({'returncode': 0}, '0x14 20'))
            MODULE.Runner.read_ec_format(runner, runner.refresh.return_value)
            self.assertEqual(runner.pause.call_args.args[0], 5)
            runner.options.control_pause = 7
            self.assertEqual(runner.enginecore_control_pause(), 7)
            runner.options.ec_control_pause = 9
            self.assertEqual(runner.enginecore_control_pause(), 9)

    def test_enginecore_zero_exit_with_protocol_error_is_retried_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.pause = Mock()
            runner.run = Mock(side_effect=[({'returncode': 0}, '!-128'), ({'returncode': 0}, 'OK')])
            runner.ec_control(runner.refresh.return_value, '0x260', 20)
            self.assertEqual(runner.run.call_count, 2)
            self.assertEqual(runner.event.call_args.args[0], 'EngineCore control failed')
            self.assertEqual(runner.pause.call_count, 1)

    def test_enginecore_failure_is_bounded_and_reboot_not_blindly_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            runner.pause = Mock()
            for reboot, count in [(False, 3), (True, 1)]:
                runner.run = Mock(return_value=({'returncode': 0}, '!-128'))
                if reboot:
                    self.assertFalse(runner.ec_control(runner.refresh.return_value, '0x8', 1, True))
                else:
                    with self.assertRaisesRegex(RuntimeError, 'control error'):
                        runner.ec_control(runner.refresh.return_value, '0x260', 1)
                self.assertEqual(runner.run.call_count, count)

    def test_stale_driver_format_cannot_skip_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner=self.runner(tmp);camera=runner.refresh.return_value;camera.sysfs=tmp
            (Path(tmp)/'pixel_format').write_text("'AB24' (RGBA)")
            runner.read_ec_format=Mock(side_effect=[20,21])
            runner.discover=Mock(return_value=[camera]);runner.idle=Mock();runner.pause=Mock()
            runner.run=Mock(return_value=({'returncode':0},'OK'))
            MODULE.Runner.set_ec_format(runner,camera.key,21)
            commands=[c.args[1] for c in runner.run.call_args_list]
            self.assertIn('wu 0x260 21',[c[-1] for c in commands if c[0]=='ECSwCtrl'])

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

    def test_cpu_accounting_measures_the_stream_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            command = [sys.executable, '-c', 'import time; end=time.process_time()+0.12; exec("while time.process_time()<end: pass")']
            record, _ = MODULE.Runner.run(runner, 'cpu', command)
            self.assertEqual(record['returncode'], 0)
            self.assertGreater(record['cpu_user_seconds'] + record['cpu_system_seconds'], 0.1)
            self.assertGreater(record['cpu_percent_one_core'], 0)
            self.assertIn('startup/shutdown included', record['cpu_scope'])

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

    def test_generated_normalization_is_also_tested_without_the_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            group = dict(camera.groups[0])
            group['monitor'] = group['monitor'] + ['--normalize']
            group['gst_nvmm'] = ['gst-launch-1.0', 'egv4l2camerasrc', 'preview=true', 'normalize=true']
            runner.capture = Mock(return_value={'pass': True})
            self.assertTrue(runner.test_fixed_preview(camera, group, 'preview'))
            self.assertEqual(runner.capture.call_count, 3)
            for call in runner.capture.call_args_list:
                self.assertNotIn('--normalize', call.args[1]['monitor'])
                self.assertIn('normalize=false', call.args[1]['gst_nvmm'])
                self.assertEqual(MODULE.format_spec(call.args[1]), MODULE.format_spec(group))
            self.assertIn('--normalize', group['monitor'])
            self.assertIn('normalize=true', group['gst_nvmm'])

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


    def test_target_without_raw16_never_commands_enginecore_format20(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.runner(tmp)
            camera = runner.refresh.return_value
            camera.sysfs = tmp
            (Path(tmp)/'pixel_format').write_text("'AR24'")
            runner.setup = Mock()
            runner.discover = Mock(return_value=[camera])
            runner.idle = Mock()
            runner.test_registers = Mock(return_value=True)
            runner.test_xeneth = Mock(return_value=True)
            runner.test_group = Mock(return_value=True)
            runner.enumerate_formats = Mock(return_value=['AR24', 'YUYV'])
            runner.run = Mock(return_value=({'returncode': 0}, "Pixel Format : 'AR24'"))
            runner.read_ec_format = Mock(return_value=21)
            runner.execute()
            self.assertEqual([c.args[1] for c in runner.set_ec_format.call_args_list], [21, 22, 21])
            runner.set_ec_format.reset_mock()
            (Path(tmp)/'pixel_format').write_text("'Y16 '")
            runner.read_ec_format = Mock(return_value=20)
            with self.assertRaisesRegex(RuntimeError, 'unsupported'):
                runner.execute()
            runner.set_ec_format.assert_not_called()

    def test_target_scripts_parse_with_legacy_python_syntax(self):
        import ast
        for name in ('run_camera_regression.py', 'run_camera_endurance.py'):
            source = (ROOT/'test/hardware'/name).read_text()
            ast.parse(source, feature_version=(3, 6))
            self.assertNotIn('import dataclasses', source)


if __name__ == '__main__':
    unittest.main()
