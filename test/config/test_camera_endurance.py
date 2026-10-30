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
 def cameras_and_config(self):
  text='';cameras=[]
  for port,key,video,fmt,gstfmt in [(0,'10-0016','/dev/video1','Y16 ','RGBA'),(1,'9-0016','/dev/video0','YUYV','YUY2')]:
   spec='--set-fmt-video=width=640,height=480,pixelformat='+fmt
   c=Camera(port,'EngineCore',True,sysfs='/sys/'+key,device='/dev/eg-ec-mipi-'+key,video=video);c.stream_spec=spec;cameras.append(c)
   text+=f'  Port {port}: EngineCore (connected)\n    Video device: {video}\n    I2C device: {c.device}\n    Sysfs: {c.sysfs}\n'
   text+=f'v4l2-ctl -d {video} --stream-mmap --set-fmt-video=width=640,height=480,pixelformat="{fmt}"\n'
   text+=f'rt_frame_monitor.py -d {video} --display\n'
   text+=f'gst-launch-1.0 -e -v egv4l2camerasrc device={video} ! "video/x-raw(memory:NVMM),format={gstfmt},width=640,height=480" ! nvvidconv compute-hw=2 ! nv3dsink sync=false\n'
  return cameras,text
 def test_nvmm_branches_keep_devices_and_have_source_and_delivery_probes(self):
  cameras,text=self.cameras_and_config();command,probes,reason=m.build_nvmm_command(cameras,text,180)
  self.assertIsNone(reason);self.assertEqual(command.count('egv4l2camerasrc'),2)
  self.assertEqual(command.count('fakesink'),2);self.assertNotIn('nv3dsink',command)
  self.assertIn('device=/dev/video0',command);self.assertIn('device=/dev/video1',command)
  self.assertEqual(len({v for names in probes.values() for v in names.values()}),4)
  for name in [v for names in probes.values() for v in names.values()]:self.assertIn('name='+name,command)
 def test_nvmm_unavailable_and_required_skip_are_not_success(self):
  cameras,text=self.cameras_and_config()
  self.assertIsNone(m.build_nvmm_command(cameras[:1],text,180)[0])
  text='\n'.join(l for l in text.splitlines() if not l.startswith('gst-launch'))
  self.assertIsNone(m.build_nvmm_command(cameras,text,180)[0])
  self.assertFalse(m.nvmm_accepted({'status':'not_applicable'},True))
  self.assertFalse(m.nvmm_accepted({'status':'failed'},False))
  self.assertTrue(m.nvmm_accepted({'status':'not_applicable'},False))
 def test_nvmm_checks_delivered_frames_and_corruption_independently(self):
  probes={'cam':{'capture':'input','delivery':'output'}}
  def trace(name,count=180,corrupt=False):
   return '\n'.join('/GstPipeline:p/GstIdentity:%s: last-message = chain pts: 0:00:%.9f flags: %s' % (name,i/60,'corrupted' if corrupt and i==0 else '') for i in range(count))
  self.assertTrue(m.inspect_nvmm_streams(trace('input')+'\n'+trace('output'),probes,180,{'cam':60})['cam']['passed'])
  self.assertFalse(m.inspect_nvmm_streams(trace('input')+'\n'+trace('output',179),probes,180,{'cam':60})['cam']['passed'])
  self.assertFalse(m.inspect_nvmm_streams(trace('input')+'\n'+trace('output',180,True),probes,180,{'cam':60})['cam']['passed'])
if __name__=='__main__':unittest.main()
