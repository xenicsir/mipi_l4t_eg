#!/usr/bin/env python3
"""Exercise the actual Dione basic-I2C codec without opening hardware."""
import importlib.util
import io
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
for name in ('serial','numpy'):
 if importlib.util.find_spec(name) is None:sys.modules[name]=types.ModuleType(name)
spec=importlib.util.spec_from_file_location('dione_control',ROOT/'sources/common/Linux_for_Tegra/rootfs/usr/bin/dioneCtrl.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DioneTests(unittest.TestCase):
 def camera(self,replies):
  c=object.__new__(m.dioneCtrl);c.device_type='I2C';c.gencp_enable=False
  c.open_device=Mock();c.close_device=Mock();c.write_device=Mock();c.read_device=Mock(side_effect=replies)
  return c
 def test_basic_request_endianness_and_delay_precede_first_read(self):
  c=self.camera([b'\0\0'+struct.pack('<I',0x12345678)]);order=[]
  c.read_device.side_effect=lambda n:(order.append('read') or b'\0\0'+struct.pack('<I',0x12345678))
  with patch.object(m.time,'sleep',side_effect=lambda t:order.append(t)):
   self.assertEqual(c.read_reg32(0x2f028),0x12345678)
  c.write_device.assert_called_once_with(bytes.fromhex('28f002000400'))
  self.assertEqual(order,[.05,'read']);c.close_device.assert_called_once()
 def test_busy_is_bounded_and_status_or_short_data_never_become_values(self):
  for replies in [[b'\xff\xff']*10,[b'\x03\x80'+b'\0'*4],[b'\0\0\x01'],[b'']]:
   c=self.camera(replies)
   with patch.object(m.time,'sleep'),self.assertRaises(m.CameraError):c.read_reg32(0x44)
   self.assertLessEqual(c.read_device.call_count,10);c.write_device.assert_called_once();c.close_device.assert_called_once()
 def test_busy_then_success_does_not_resend_the_command(self):
  c=self.camera([b'\xff\xff',b'\0\0'+struct.pack('<I',640)])
  with patch.object(m.time,'sleep') as sleep:self.assertEqual(c.read_reg32(0x2f028),640)
  self.assertEqual(sleep.call_count,2);c.write_device.assert_called_once()
 def test_write_and_float_zero_preserve_wire_bits(self):
  c=self.camera([b'\0\0'])
  with patch.object(m.time,'sleep'):self.assertEqual(c.write_reg32(0x1234,0x01020304),0)
  c.write_device.assert_called_once_with(bytes.fromhex('34120000040004030201'))
  c=self.camera([b'\0'*6])
  with patch.object(m.time,'sleep'):self.assertEqual(c.read_reg32f(0x44),0.0)
 def test_constructor_does_not_force_i2c_and_close_releases_both_fds(self):
  files=[io.BytesIO(),io.BytesIO()]
  with patch.object(m.platform,'system',return_value='Linux'),patch.object(m.io,'open',side_effect=files),patch.object(m.fcntl,'ioctl') as ioctl:
   c=m.dioneCtrl(bus=9,dev_addr=0x5d)
  self.assertEqual([x.args[1] for x in ioctl.call_args_list],[0x703,0x703,0x702,0x702])
  c.close();c.close();self.assertTrue(all(f.closed for f in files))
if __name__=='__main__':unittest.main()
