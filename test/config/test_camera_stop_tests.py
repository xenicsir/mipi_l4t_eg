#!/usr/bin/env python3
"""Exercise kernel verdicts, pixel tails, process cleanup and runner integration."""
import errno
import json
import os
from pathlib import Path
import signal
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test/hardware'))
from kernel_capture_log import classify, decode, qualify, KernelCaptureLog
from camera_stop_tests import inspect_pixels, StopSuite
from run_camera_regression import Runner, parser


class KernelTests(unittest.TestCase):
    def window(self, message):
        w=dict(complete=True,errors=[dict(message=message)])
        qualify(w)
        return w

    def test_errors_not_hidden_by_zero_status_or_successful_command(self):
        for text in ['tegra-capture-vi corr_err: discarding frame 18, status 0, flags: 0, err_data 0x00000000',
                     'tegra-capture-vi uncorr_err: request timed out', 'nvcsi: stream failed',
                     'BUG: unable to handle kernel NULL pointer', 'arm-smmu: context fault']:
            self.assertNotEqual(classify(text,6),'info')
        self.assertEqual(classify('bwmgr API not supported\n SUBSYSTEM=platform',3),'known_platform_message')
        self.assertEqual(classify('vi5_capture_dequeue: 19 callbacks suppressed',4),'log_loss')
        self.assertEqual(classify('another device: I/O error',3),'kernel_error')
        self.assertEqual(classify('VI capture setup complete',6),'info')

    def test_dione_exception_is_correlated_and_never_hides_other_errors(self):
        msg='corr_err: discarding frame 1, status 14, flags: 0, err_data 0x00000040'
        for name,policy,simultaneous,expected in [('Dione640',{'startup_exception':True},False,True),
                  ('iLumos',{'startup_exception':True},False,False),
                  ('Dione640',{'startup_exception':False},False,False),
                  ('Dione640',{'startup_exception':True},True,False)]:
            w=self.window(msg)
            qualify(w,name,policy,simultaneous)
            self.assertEqual(bool(w['errors'][0].get('qualification')),expected)
            self.assertFalse(w['clean']);self.assertFalse(w['affects_test_result'])
            self.assertEqual(len(w['errors']),1)
        w=self.window(msg);w['errors'].append(dict(message='uncorr_err: request error'))
        qualify(w,'Dione640',{'startup_exception':True})
        self.assertEqual(w['unqualified_messages'],2)
        w=qualify(self.window(msg.replace('status 14','status 0')),'Dione640',{'startup_exception':True})
        self.assertEqual(w['unqualified_messages'],1)

    def test_new_records_and_overrun_do_not_look_like_a_clean_kernel(self):
        with tempfile.TemporaryDirectory() as d, patch('kernel_capture_log.os.open',return_value=91), \
             patch('kernel_capture_log.os.lseek') as seek, patch('kernel_capture_log.os.close'):
            log=KernelCaptureLog(d);seek.assert_called_once_with(91,0,os.SEEK_END)
            entries=[b'6,50,123,-;VI capture setup complete\n',b'3,51,124,-;bwmgr API not supported\n',
                     b'4,53,125,-;corr_err: discarding frame 0, status 0, flags: 0, err_data 0x00000000\n',BlockingIOError()]
            with patch('kernel_capture_log.os.read',side_effect=entries):w=log.collect('capture')
            self.assertFalse(w['complete']);self.assertFalse(w['clean']);self.assertEqual(w['known_platform_messages'],1)
            self.assertEqual(w['errors'][0]['sequence'],53)
            self.assertEqual(len((Path(d)/'kernel.jsonl').read_text().splitlines()),3)
            with patch('kernel_capture_log.os.read',side_effect=[OSError(errno.EPIPE,'overrun'),BlockingIOError()]):
                self.assertFalse(log.collect('overrun')['clean'])
            log.close();self.assertTrue(log.summary()['available'])

    def test_smmu_fault_remains_visible_without_changing_verdict(self):
        with tempfile.TemporaryDirectory() as d, patch('kernel_capture_log.os.open',return_value=91), \
             patch('kernel_capture_log.os.lseek'), patch('kernel_capture_log.os.close'):
            log=KernelCaptureLog(d)
            with patch('kernel_capture_log.os.read',side_effect=[b'3,1,123,-;arm-smmu: Unhandled context fault\n',BlockingIOError()]):
                log.collect('sigint')
            self.assertTrue(log.summary()['has_kernel_fault'])
            self.assertFalse(log.summary()['clean'])
            self.assertFalse(log.summary()['affects_test_result'])

    def test_unavailable_kernel_access_reports_a_coverage_gap(self):
        with tempfile.TemporaryDirectory() as d,patch('kernel_capture_log.os.open',side_effect=PermissionError('denied')):
            log=KernelCaptureLog(d);w=log.collect('capture')
            self.assertFalse(w['clean']);self.assertFalse(log.summary()['complete'])


class PixelTests(unittest.TestCase):
    def test_all_frames_last_frame_and_partial_sigint_prefix(self):
        layout=dict(width=2,height=2,bytesperline=4,sizeimage=8)
        good=struct.pack('<4H',64,64,64,64)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);raw=folder/'test.raw';raw.write_bytes(good*2+good[:3])
            r=inspect_pixels(raw,layout,'Y14',dict(kind='gray',value=64),folder,'partial',True)
            self.assertTrue(r['passed']);self.assertFalse(r['file_complete']);self.assertTrue(r['last_frame_passed'])
            self.assertEqual(r['complete_frames'],2)
            self.assertFalse(inspect_pixels(raw,layout,'Y14',dict(kind='gray',value=64),folder,'finite')['passed'])
            raw.write_bytes(good+struct.pack('<4H',64,64,64,0))
            r=inspect_pixels(raw,layout,'Y14',dict(kind='gray',value=64),folder,'corrupt')
            self.assertFalse(r['passed']);self.assertFalse(r['last_frame_passed']);self.assertTrue(r['first_frame_passed'])
            raw.write_bytes(good+b'\xff')
            self.assertFalse(inspect_pixels(raw,layout,'Y14',dict(kind='gray',value=64),folder,'bad-tail',True)['passed'])

    def test_ilumos_vertical_clears_solid_offset_and_restores_on_failure(self):
        import camera_pixel_oracles as oracle
        for fail in (False,True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as d:
                state={a:0 for a in (0x50003000,0x50003004,0x50000a1c,0x50000504,0x50000508,0x50000510,0x50000a20)}
                state[0x5000050c]=37
                before=dict(state)
                def write(a,v):
                    if a==0x50000a00:state[0x50000a20]=int(v==1)
                    elif a==0x50003008:state[0x50003004]=0
                    else:state[a]=v
                control=SimpleNamespace(ilumos=True,read=lambda a:state[a],write=write)
                def capture(camera,fmt,label,folder,reference):
                    if reference['kind']=='ilumos_vertical':
                        self.assertEqual(state[0x5000050c],0)
                        if fail:raise RuntimeError('capture failed')
                    return dict(passed=True)
                runner=SimpleNamespace(save=Mock(),capture_reference=Mock(side_effect=capture))
                camera=SimpleNamespace(enginecore=False,device='/dev/ilumos-42-0030')
                record={}
                with patch.object(oracle,'Controls',return_value=control):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'capture failed'):
                            oracle.execute_reference(runner,camera,'Y14','test',Path(d),record)
                    else:self.assertTrue(oracle.execute_reference(runner,camera,'Y14','test',Path(d),record))
                self.assertTrue(record['restored'])
                self.assertEqual({k:state[k] for k in before},before)

    def test_vertical_displacement_is_recorded_not_ignored(self):
        layout=dict(width=2,height=2,bytesperline=4,sizeimage=8)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);raw=folder/'test.raw';raw.write_bytes(struct.pack('>4H',64,64,0,0)+struct.pack('>4H',0,0,64,64))
            r=inspect_pixels(raw,layout,'Y16 -BE',dict(kind='ilumos_vertical'),folder,'gradient')
            self.assertFalse(r['passed']);self.assertTrue(r['last_frame_passed']);self.assertFalse(r['first_frame_passed'])


class ProcessTests(unittest.TestCase):
    def test_timeout_is_failure_and_child_is_reaped(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);binpath=root/'v4l2-ctl'
            binpath.write_text('#!'+sys.executable+'\nimport time,signal\nsignal.signal(signal.SIGINT,signal.SIG_IGN)\ntime.sleep(30)\n');binpath.chmod(0o755)
            r=Runner(parser().parse_args(['--output',str(root/'out'),'--timeout','.05']))
            r.env['PATH']=d+':'+r.env['PATH']
            r.kernel=Mock();r.kernel.collect.side_effect=lambda label:dict(label=label,complete=True,errors=[],clean=True,unqualified_messages=0,affects_test_result=False)
            r.kernel.summary.return_value={'complete':True}
            suite=StopSuite(r);r.stop_results.append(suite.report)
            camera=SimpleNamespace(name='iLumos',key='42-0030',video='/dev/nonexistent')
            row=suite.processes([camera],'finite')
            self.assertFalse(row['passed']);self.assertTrue(row['cameras'][0]['timeout'])
            with self.assertRaises(ProcessLookupError):os.kill(row['cameras'][0]['pid'],0)

    def test_successful_capture_with_smmu_message_still_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);binary=root/'v4l2-ctl'
            binary.write_text('#!'+sys.executable+'\nfor i in range(10): print("cap dqbuf: 0 seq: %d bytesused: 16 ts: %.6f (ts-monotonic)" % (i,1+i/60))\n')
            binary.chmod(0o755)
            r=Runner(parser().parse_args(['--output',str(root/'out')]))
            r.env['PATH']=d+':'+r.env['PATH'];r.kernel=Mock()
            r.kernel.collect.side_effect=lambda label:dict(label=label,complete=True,errors=[dict(message='arm-smmu: Unhandled context fault')],clean=False,unqualified_messages=1,affects_test_result=False)
            r.kernel.summary.return_value={'complete':True,'clean':False,'has_kernel_fault':True}
            suite=StopSuite(r);r.stop_results.append(suite.report)
            camera=SimpleNamespace(name='iLumos',key='42-0030',video='/dev/nonexistent')
            row=suite.processes([camera],'finite')
            self.assertTrue(row['passed']);self.assertFalse(row['kernel']['clean'])
            self.assertEqual(len(row['kernel']['errors']),1)
            self.assertFalse(row['kernel']['affects_test_result'])

    def test_late_kernel_error_is_reported_without_changing_main_exit_status(self):
        import run_camera_regression as module
        runner=Mock()
        runner.execute.return_value=0
        runner.kernel.summary.return_value={'clean':False,'has_kernel_fault':True,'affects_test_result':False}
        with patch.object(module,'Runner',return_value=runner), patch.object(module.os,'geteuid',return_value=0), \
             patch.object(module.signal,'signal'), patch.object(module.time,'sleep'):
            self.assertEqual(module.main(['--output','unused','--stop-tests-only']),0)
            runner.kernel.collect.assert_called_with('runner-exit')
            runner.kernel.close.assert_called_once()

    def test_stop_only_executes_suite_with_informational_kernel_checks(self):
        with tempfile.TemporaryDirectory() as d:
            r=Runner(parser().parse_args(['--output',str(Path(d)/'out'),'--stop-tests-only']))
            c=SimpleNamespace(connected=True,key='42',name='camera')
            r.setup=Mock();r.discover=Mock(return_value=[c]);r.idle=Mock();r.event=Mock()
            r.test_stop_suite=Mock(return_value=True);r.finish_kernel=Mock()
            self.assertEqual(r.execute(),0);r.test_stop_suite.assert_called_once_with([c]);r.finish_kernel.assert_called_once()

if __name__=='__main__':unittest.main()
