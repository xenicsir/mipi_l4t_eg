#!/usr/bin/env python3
"""Backend selection and pre-I/O CLI validation; no camera/GStreamer required."""
import contextlib
import fcntl
import os
import time
import csv
import importlib.util
import io
import json
from pathlib import Path
import runpy
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

PATH = Path(__file__).resolve().parents[2] / 'sources/common/Linux_for_Tegra/rootfs/usr/bin/rt_frame_monitor.py'
spec = importlib.util.spec_from_file_location('frame_monitor', PATH)
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


class BackendTests(unittest.TestCase):
    def test_gpu_load_is_cached_and_read_errors_remain_unknown(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(M.platform, 'system', return_value='Linux'):
            path = Path(tmp) / 'load'
            path.write_text('185\n')
            load = M.JetsonGpuLoad(True, path)
            with patch.object(M.time, 'monotonic', return_value=0):
                self.assertEqual(load.sample(), 18.5)
            path.write_text('900')
            with patch.object(M.time, 'monotonic', return_value=.5):
                self.assertEqual(load.sample(), 18.5)
            with patch.object(M.time, 'monotonic', return_value=1):
                self.assertEqual(load.sample(), 90)
            for now, value in [(2, '1001'), (3, '-1'), (4, 'bad')]:
                path.write_text(value)
                with patch.object(M.time, 'monotonic', return_value=now):
                    self.assertIsNone(load.sample())
            path.unlink()
            with patch.object(M.time, 'monotonic', return_value=5):
                self.assertIsNone(load.sample())

    def test_gpu_status_is_optional_and_windows_never_reads_sysfs(self):
        with patch.object(M.platform, 'system', return_value='Windows'), patch.object(M.Path, 'is_file') as access:
            self.assertIsNone(M.JetsonGpuLoad(True).sample())
            access.assert_not_called()
        line = M.format_status(1, 1, 16, 60, 20, gpu=18.5, show_gpu=True)
        self.assertIn('gpu= 18.5%', line)
        self.assertLess(line.index('cpu='), line.index('gpu='))
        self.assertNotIn('gpu=', M.format_status(1, 1, 16, 60, 20))
        self.assertIn('gpu=   --%', M.format_status(1, 1, 16, 60, 20, show_gpu=True))

    def test_grayscale_display_defaults_to_fixed_and_normalization_is_opt_in(self):
        import numpy as np
        values = np.array([[1000, 1500, 2000]], dtype=np.uint16)
        original = values.copy()
        self.assertFalse(M.Config().normalize)
        np.testing.assert_array_equal(M.grayscale_preview(values, 'Y14'), [[15, 23, 31]])
        np.testing.assert_array_equal(M.grayscale_preview(values, 'Y16'), [[3, 5, 7]])
        normalized = M.grayscale_preview(values, 'Y14', True).astype(int)
        self.assertLessEqual(np.abs(normalized - [[0, 128, 255]]).max(), 1)
        self.assertEqual((normalized.min(), normalized.max()), (0, 255))
        np.testing.assert_array_equal(M.grayscale_preview(values.astype(np.float32), 'Y14'), [[15, 23, 31]])
        np.testing.assert_array_equal(M.grayscale_preview(np.full((2, 2), 555, np.uint16), 'Y16', True), np.zeros((2, 2)))
        np.testing.assert_array_equal(values, original)

    def test_inapplicable_normalization_is_informational(self):
        for fmt, display, supported in [('AB24', True, True), ('Y14', False, True), ('Y16', True, False)]:
            with self.subTest(fmt=fmt, display=display, supported=supported), self.assertLogs(M.log, level='INFO') as logs:
                self.assertFalse(M.report_display_mapping(fmt, 'nvmm', display, True, supported))
            self.assertIn('Normalization not applied', '\n'.join(logs.output))
        self.assertNotIn('normalize', M._nvmm_plan('Y14', True)['properties'])
        self.assertTrue(M._nvmm_plan('Y14', True, True)['properties']['normalize'])
        self.assertNotIn('normalize', M._nvmm_plan('AB24', True, True)['properties'])

    def test_fixed_preview_matches_every_uint16_sample_and_saturates(self):
        import numpy as np
        values = np.arange(65536, dtype=np.uint16).reshape(256, 256)
        for fmt, shift in [('Y10', 2), ('Y14', 6), ('Y16', 8), ('Y16_BE', 8)]:
            expected = np.minimum(values >> shift, 255).astype(np.uint8)
            for dtype in (np.uint16, np.float32):
                with self.subTest(fmt=fmt, dtype=dtype):
                    np.testing.assert_array_equal(M.grayscale_preview(values.astype(dtype), fmt), expected)

    def test_module_and_nvmm_plan_do_not_load_pixel_processing_libraries(self):
        code = ("import importlib.util,sys; "
                "spec=importlib.util.spec_from_file_location('monitor_test',sys.argv[1]); "
                "m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; "
                "spec.loader.exec_module(m); "
                "assert m._nvmm_plan('Y16',True)['processing']=='cuda-preview'; "
                "assert 'cv2' not in sys.modules and 'numpy' not in sys.modules; "
                "assert m.np.zeros((1,1)).shape==(1,1); assert 'numpy' in sys.modules")
        subprocess.run([sys.executable, '-c', code, str(PATH)], check=True, timeout=10)

    def test_headless_cuda_ignores_forwarded_display(self):
        with patch.dict(M.os.environ, {'DISPLAY': 'localhost:10.0'}):
            M._prepare_nvmm_environment(False)
            self.assertNotIn('DISPLAY', M.os.environ)
        with patch.dict(M.os.environ, {'DISPLAY': ':0', '__GL_YIELD': 'NOTHING'}):
            M._prepare_nvmm_environment(True)
            self.assertEqual(M.os.environ['DISPLAY'], ':0')
            self.assertEqual(M.os.environ['__GL_YIELD'], 'NOTHING')

    def test_cadence_window_does_not_keep_startup_penalty(self):
        cadence=M.FrameCadence()
        cadence.add(0)
        for i in range(240): cadence.add(.15+i/60)
        result=cadence.summary()
        self.assertLess(result['overall_fps'],60)
        self.assertAlmostEqual(result['window_fps'],60,places=6)
        self.assertAlmostEqual(result['steady_fps'],60,places=6)
        self.assertEqual(cadence.summary(10)['window_fps'],0)
        slow=M.FrameCadence()
        for i in range(120):slow.add(i/30)
        self.assertAlmostEqual(slow.summary()['window_fps'],30,places=6)

    def test_status_layout_and_unavailable_values(self):
        line = M.format_status(168, 2.801, 16.8, 45, 47.3, 60, 0, 0, 0)
        keys = ['frame=', 'ts=', 'dt=', 'expected_fps=', 'actual_fps=', 'cpu=', 'gst_drop=', 'corrupt=', 'sequence_gaps=']
        positions = [line.index(key) for key in keys]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('backend=', line)
        self.assertRegex(line, r'expected_fps=\s*60.0')
        self.assertRegex(line, r'actual_fps=\s*45.0')
        self.assertIn('ts=   2.801s', line)
        self.assertIn('dt=  16.8ms', line)
        unknown = M.format_status(0, 0, 0, 0, None)
        self.assertRegex(unknown, r'expected_fps=\s*--')
        self.assertRegex(unknown, r'sequence_gaps=\s*--')

    def test_status_output_refreshes_one_line_and_logs_periodically(self):
        class Terminal(io.StringIO):
            def isatty(self): return True
        stream = Terminal()
        output = M.StatusOutput(stream)
        with patch.object(M.time, 'monotonic', side_effect=[0, .05, .2, .3]):
            output.write('frame=0 longer')
            output.write('frame=1')
            output.write('frame=2')
            output.finish()
        self.assertEqual(stream.getvalue().count('\n'), 1)
        self.assertIn('\rframe=2       ', stream.getvalue())
        self.assertNotIn('frame=1', stream.getvalue())
        stream = io.StringIO()
        output = M.StatusOutput(stream)
        with patch.object(M.time, 'monotonic', side_effect=[0, .2, 1.1, 1.2]):
            output.write('frame=0')
            output.write('frame=1')
            output.write('frame=2')
            output.finish()
        self.assertNotIn('\r', stream.getvalue())
        self.assertNotIn('frame=1', stream.getvalue())
        self.assertTrue(stream.getvalue().endswith('frame=2\n'))

    def test_counters_use_metadata_and_handle_sequence_wrap(self):
        counters = M.CaptureCounters()
        counters.add(None, False)
        self.assertFalse(counters.summary()['sequence_available'])
        counters.add(0xfffffffe, False)
        counters.add(1, True)
        counters.add(2, False)
        result = counters.summary()
        self.assertEqual(result['sequence_gaps'], 2)
        self.assertEqual(result['corrupt'], 1)
        cadence = M.FrameCadence()
        cadence.add(10); cadence.add(10.0168)
        self.assertAlmostEqual(cadence.summary()['elapsed_seconds'], .0168)
        self.assertAlmostEqual(cadence.summary()['interval_ms'], 16.8)

    def test_expected_rate_uses_enginecore_register_not_measurement(self):
        with patch.object(M.platform, 'system', return_value='Linux'), \
             patch.object(M, '_enginecore_control_device', return_value='/dev/eg-ec-mipi-42-0016'), \
             patch.object(M.shutil, 'which', return_value='/usr/bin/ECSwCtrl'), \
             patch.object(M.subprocess, 'run', return_value=Mock(stdout='30.000000')) as command:
            rate, origin = M._resolve_expected_fps(M.Config(target_fps=60, expected_fps=99))
            self.assertEqual(rate, 30)
            self.assertEqual(origin, 'EngineCore rf 0x210')
            self.assertEqual(command.call_args.args[0][-1], 'rf 0x210')
            command.return_value.stdout = '!-128'
            with self.assertLogs(M.log, level='WARNING'), patch.object(M.time, 'sleep'):
                self.assertIsNone(M._resolve_expected_fps(M.Config())[0])

    def test_missing_ecswctrl_does_not_start_a_command_or_abort_capture(self):
        with patch.object(M.platform, 'system', return_value='Linux'), \
             patch.object(M, '_enginecore_control_device', return_value='/dev/eg-ec-mipi-42-0016'), \
             patch.object(M.shutil, 'which', return_value=None), \
             patch.object(M.subprocess, 'run', side_effect=AssertionError('unexpected execution')), \
             self.assertLogs(M.log, level='WARNING'):
            rate, origin = M._resolve_expected_fps(M.Config())
            self.assertIsNone(rate)
            self.assertEqual(origin, 'ECSwCtrl unavailable')

    def test_windows_never_runs_linux_ecswctrl_even_if_exe_exists(self):
        with patch.object(M.platform, 'system', return_value='Windows'), \
             patch.object(M, '_enginecore_control_device', side_effect=AssertionError('Linux sysfs access')), \
             patch.object(M.shutil, 'which', side_effect=AssertionError('unexpected Linux tool lookup')), \
             patch.object(M.subprocess, 'run', side_effect=AssertionError('unexpected I2C execution')):
            self.assertIsNone(M._resolve_expected_fps(M.Config())[0])
            self.assertEqual(M._resolve_expected_fps(M.Config(expected_fps=25))[0],25)

    def test_other_cameras_do_not_invent_expected_rate(self):
        with patch.object(M, '_enginecore_control_device', return_value=None), \
             patch.object(M.subprocess, 'run', side_effect=AssertionError('unexpected I/O')):
            self.assertIsNone(M._resolve_expected_fps(M.Config(target_fps=60))[0])
            self.assertEqual(M._resolve_expected_fps(M.Config(expected_fps=29.97))[0], 29.97)
        with patch.object(M.platform, 'system', return_value='Windows'), \
             patch.object(M, '_enginecore_control_device', side_effect=AssertionError('Linux-only lookup')):
            self.assertIsNone(M._resolve_expected_fps(M.Config())[0])

    def test_enginecore_identification_matches_the_selected_video_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = root/'class/video4linux/video7/name'
            name.parent.mkdir(parents=True)
            name.write_text('vi-output, eg-ec-mipi 42-0016')
            node = root/'bus/i2c/devices/42-0016/driver'
            node.parent.mkdir(parents=True)
            driver = root/'bus/i2c/drivers/eg-ec-mipi'
            driver.mkdir(parents=True)
            node.symlink_to(driver)
            self.assertEqual(M._enginecore_control_device('/dev/video7', root), '/dev/eg-ec-mipi-42-0016')
            self.assertIsNone(M._enginecore_control_device('/dev/video8', root))
            name.write_text('vi-output, dione 42-000e')
            self.assertIsNone(M._enginecore_control_device('/dev/video7', root))

    def test_cpu_percentage_can_exceed_one_core(self):
        with patch.object(M.time, 'monotonic', side_effect=[10, 10.5, 11, 12]), \
             patch.object(M.time, 'process_time', side_effect=[5, 7, 8]):
            cpu = M.ProcessCpuLoad()
            self.assertIsNone(cpu.sample())
            self.assertEqual(cpu.sample(), 200.0)
            self.assertEqual(cpu.average(), 150.0)

    def test_classic_csv_keeps_pixel_columns_and_adds_cpu(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            frames = iter([(M.np.ones((4, 4), dtype=M.np.float32), 16.6)] * 3)
            M.camera_main_loop(M.Config(num_frames=3, log_enabled=True, base_dir=directory, fmt='Y16'),
                               _frame_iter=frames)
            files = list(Path(directory).rglob('rt_log_*.csv'))
            with files[0].open() as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0], ['timestamp_s', 'dt_ms', *M._STATS, 'cpu_percent_one_core'])
            self.assertTrue(all(len(row) == len(rows[0]) for row in rows))

    def reject(self, args, phrase, config=None):
        with tempfile.TemporaryDirectory() as directory:
            if config is not None:
                path = Path(directory) / 'config.json'
                path.write_text(json.dumps(config))
                args = ['--config', str(path)] + args
            stderr = io.StringIO()
            # Any format query or capture before rejecting is a test failure.
            with patch.object(sys, 'argv', [str(PATH), '--backend', 'nvmm'] + args), \
                 patch('subprocess.run', side_effect=AssertionError('unexpected device I/O')), \
                 patch('cv2.VideoCapture', side_effect=AssertionError('unexpected capture')), \
                 contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(PATH), run_name='__main__')
            self.assertEqual(raised.exception.code, 2)
            self.assertIn(phrase, stderr.getvalue())

    def test_pixel_options_rejected_before_device_access(self):
        for args in [['--stats'], ['--save-images'], ['--fpn-detect'], ['--fpn-window=11'],
                     ['--multicam-file=x.cam'], ['--no-resize'], ['--event-half=5'],
                     ['--freeze-recovery=5'], ['--image-format=raw']]:
            with self.subTest(args=args):
                self.reject(args, 'incompatible')

    def test_json_conflicts_are_not_silently_ignored(self):
        for data in [{'stats': True}, {'save_images': True}, {'fpn_enabled': True},
                     {'fpn_window': 55}, {'window_autosize': True}, {'reopen_interval_s': 9}]:
            with self.subTest(config=data):
                self.reject([], 'incompatible', data)

    def test_unsupported_format_and_invalid_limits(self):
        self.reject([], 'does not support', {'fmt': 'Y10'})
        self.reject(['--fps=0'], 'fps positive')
        self.reject(['--width=-1'], 'width and height')
        self.reject(['--max-log-lines=-1'], 'non-negative')

    def selection(self, backend='auto', available=True, fmt='YUYV', conflicts=(), error=None):
        cfg = M.Config(backend=backend)
        with patch.object(M, '_nvmm_available', return_value=(available, 'probe result')) as probe, \
             patch.object(M, '_v4l2_get_fmt', return_value=(640, 480, fmt)), \
             patch.object(M, '_run_nvmm_monitor', side_effect=error) as nvmm, \
             patch.object(M, 'camera_main_loop') as classic, self.assertLogs(M.log, level='INFO') as logs:
            try:
                M._run_selected_backend(cfg, conflicts)
            except RuntimeError:
                if not error:
                    raise
            return probe, nvmm, classic, '\n'.join(logs.output)

    def test_default_auto_selects_nvmm(self):
        _, nvmm, classic, logs = self.selection()
        nvmm.assert_called_once()
        classic.assert_not_called()
        self.assertIn('requested=auto selected=nvmm', logs)

    def test_auto_fallback_records_actual_backend(self):
        for values in [dict(available=False), dict(fmt='MJPG'), dict(conflicts=['--stats'])]:
            _, nvmm, classic, logs = self.selection(**values)
            classic.assert_called_once()
            nvmm.assert_not_called()
            self.assertIn('selected=classic reason=', logs)

    def test_explicit_classic_never_probes_nvmm(self):
        probe, nvmm, classic, _ = self.selection(backend='classic')
        probe.assert_not_called()
        nvmm.assert_not_called()
        classic.assert_called_once()

    def test_runtime_failure_is_not_hidden_by_fallback(self):
        _, nvmm, classic, _ = self.selection(error=RuntimeError('camera stalled'))
        nvmm.assert_called_once()
        classic.assert_not_called()

    def test_windows_auto_keeps_classic_without_linux_device_access(self):
        with patch.object(M.platform, 'system', return_value='Windows'), \
             patch.object(M, '_v4l2_get_fmt', side_effect=AssertionError('Linux-only call')), \
             patch.object(M, '_run_nvmm_monitor') as nvmm, \
             patch.object(M, 'camera_main_loop') as classic:
            M._run_selected_backend(M.Config(), [])
            classic.assert_called_once()
            nvmm.assert_not_called()

    def test_forced_nvmm_on_windows_fails_before_camera_access(self):
        with patch.object(M.platform, 'system', return_value='Windows'):
            self.reject([], 'requires Linux')

    def test_generic_linux_without_nvmm_retains_classic(self):
        # No requirement for Jetson files, NVIDIA utilities or GI on classic.
        with patch.object(M.platform, 'system', return_value='Linux'), \
             patch.object(M, '_nvmm_available', return_value=(False, 'missing plugin')), \
             patch.object(M, '_v4l2_get_fmt', side_effect=AssertionError('unneeded query')), \
             patch.object(M, 'camera_main_loop') as classic:
            M._run_selected_backend(M.Config(), [])
            classic.assert_called_once()

    def test_forwarded_or_missing_display_never_opens_nvmm(self):
        for display in ['localhost:10.0', '127.0.0.1:11.0', 'host:0', '']:
            with self.subTest(display=display), patch.dict(M.os.environ, {'DISPLAY': display}), \
                 patch.object(M, '_v4l2_get_fmt', side_effect=AssertionError('unexpected device query')), \
                 patch.object(M, 'camera_main_loop') as classic:
                M._run_selected_backend(M.Config(show_video=True), [])
                classic.assert_called_once()
                self.reject(['--display'], 'local X11')

    def test_local_display_and_headless_are_distinguished_from_ssh(self):
        for display in [':0', ':1.0', 'unix:0', 'unix/:2.1']:
            self.assertIsNone(M._nvmm_display_reason(True, {'DISPLAY': display, 'SSH_CONNECTION': 'ssh'}))
        self.assertIsNone(M._nvmm_display_reason(False, {'DISPLAY': 'localhost:10.0'}))

    def test_watchdog_releases_resources_when_worker_ignores_signals(self):
        # Model a blocked native renderer with an unresponsive process holding
        # an exclusive resource. The watchdog must kill it and release that FD.
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / 'capture.lock'
            read_fd, write_fd = os.pipe()
            program = ('import os,fcntl,signal,time; '
                       'f=open(%r,"w"); fcntl.flock(f,fcntl.LOCK_EX); '
                       'signal.signal(signal.SIGINT,signal.SIG_IGN); '
                       'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                       'os.write(%d,b"."); time.sleep(30)' % (str(lock_path), write_fd))
            start = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, 'stopped responding'):
                M._supervise_capture([sys.executable, '-c', program], read_fd, write_fd,
                                     startup_timeout=2, heartbeat_timeout=.2, stop_grace=.1)
            self.assertLess(time.monotonic() - start, 4)
            with lock_path.open() as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_grayscale_capture_mode_is_not_relabelled(self):
        for fmt, processing in [('Y16', 'none'), ('Y14', 'none'), ('Y16_BE', 'cuda-endian')]:
            plan = M._nvmm_plan(fmt, False)
            self.assertEqual(plan['format'], 'GRAY16_LE')
            self.assertEqual(plan['properties'], {'capture-format': fmt, 'preview': False})
            self.assertEqual(plan['processing'], processing)
            preview = M._nvmm_plan(fmt, True)
            self.assertEqual(preview['format'], 'RGBA')
            self.assertEqual(preview['processing'], 'cuda-preview')
            self.assertFalse(preview['vic'])

    def test_rgb_byte_order_and_conversion_plan(self):
        self.assertEqual(M._nvmm_plan('AB24', True)['format'], 'RGBA')
        self.assertFalse(M._nvmm_plan('AB24', True)['vic'])
        self.assertEqual(M._nvmm_plan('AR24', True)['format'], 'BGRx')
        self.assertTrue(M._nvmm_plan('AR24', True)['vic'])
        self.assertTrue(M._nvmm_plan('YUYV', True)['vic'])
        self.assertIsNone(M._nvmm_plan('MJPG', False))

    def test_forced_nvmm_missing_plugin_is_failure(self):
        with patch.object(M, '_nvmm_available', return_value=(False, 'plugin missing')), \
             patch.object(M, 'camera_main_loop') as classic:
            with self.assertRaisesRegex(RuntimeError, 'plugin missing'):
                M._run_selected_backend(M.Config(backend='nvmm'), [])
            classic.assert_not_called()


if __name__ == '__main__':
    unittest.main()
