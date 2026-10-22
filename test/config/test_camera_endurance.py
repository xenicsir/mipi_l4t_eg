#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'test/hardware'))
import run_camera_endurance as m
from run_camera_regression import Camera
class EnduranceTests(unittest.TestCase):
 def test_live_parallel_children_are_stopped_and_counted(self):
  code='import sys,time\nwhile True:\n print("<",end="",flush=True);time.sleep(.01)'
  with tempfile.TemporaryDirectory() as tmp:
   records=m.run_window([[sys.executable,'-c',code]]*2,.25,Path(tmp))
   self.assertEqual(len(records),2);self.assertTrue(all(x['passed'] and x['frames']>0 for x in records))
 def test_early_exit_is_failure_even_with_frames(self):
  with tempfile.TemporaryDirectory() as tmp:
   records=m.run_window([[sys.executable,'-c','print("<<<")']],.25,Path(tmp))
   self.assertFalse(records[0]['passed'])
 def test_process_error_is_not_hidden_by_nonempty_output(self):
  with tempfile.TemporaryDirectory() as tmp:
   records=m.run_window([[sys.executable,'-c','print("<<<");raise SystemExit(2)']],.15,Path(tmp))
   self.assertFalse(records[0]['passed']);self.assertEqual(records[0]['reason'],'unexpected-exit-status')
 def test_stalled_process_is_not_a_success_just_because_one_frame_arrived(self):
  with tempfile.TemporaryDirectory() as tmp:
   records=m.run_window([[sys.executable,'-c','import time;print("<",flush=True);time.sleep(5)']],.5,Path(tmp),stall_seconds=.1)
   self.assertFalse(records[0]['passed']);self.assertEqual(records[0]['reason'],'no-stream-progress')
 def test_kernel_ring_wrap_cannot_claim_clean_logs(self):
  self.assertEqual(m.kernel_delta('old\n','old\nnew\n'),['new'])
  self.assertIsNone(m.kernel_delta('old\n','different\n'))
 def test_only_unknown_descriptors_at_measured_stop_are_observations(self):
  line='[ 99.900] vi: corr_err: discarding frame 3840, status 0, flags: 0, err_data 0x00000000'
  errors,observations=m.classify_kernel_lines([line],[100.0])
  self.assertEqual(errors,[]);self.assertEqual(observations,[line])
  self.assertEqual(m.classify_kernel_lines([line],[150.0])[0],[line])
  error=line.replace('status 0','status 14')
  self.assertEqual(m.classify_kernel_lines([error],[100.0])[0],[error])
 def test_expected_visit_rejects_missing_camera_and_wrong_bsp(self):
  visit=dict(l4t='35.6.0',cameras=[dict(port=0,family='dione_ir',resolution='640x480')])
  self.assertEqual(len(m.validate_visit(visit,[],'36.4.4')),2)
if __name__=='__main__':unittest.main()
