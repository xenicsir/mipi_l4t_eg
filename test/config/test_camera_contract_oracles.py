#!/usr/bin/env python3
from pathlib import Path
import errno
import os
import struct
import sys
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import tempfile
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test/hardware'))
import v4l2_contract as V
from camera_pixel_oracles import check_frame,enginecore_rgb,execute_reference,Controls


def current(fmt='YUYV',w=640,h=480,bpp=2):
    return "Width/Height : %d/%d\nPixel Format : '%s'\nBytes per Line : %d\nSize Image : %d\n" % (w,h,fmt,w*bpp,w*h*bpp)


def enumeration(formats=('Y16','AR24','YUYV'),w=640,h=480):
    return '\n'.join("[%d]: '%s'\n Size: Discrete %dx%d\n Interval: Discrete 0.017s (60.000 fps)" % (i,f,w,h) for i,f in enumerate(formats))


class MetadataTests(unittest.TestCase):
    def validate(self,listing=None,active=None,**kw):
        return V.validate_metadata(listing or enumeration(),active or current(),640,480,'YUYV',
                                   expected_formats=['Y16','AR24','YUYV'],expected_fps=60,**kw)

    def test_capabilities_are_distinct_from_active_format(self):
        self.assertTrue(self.validate()['passed'])
        self.assertFalse(self.validate(enumeration(('YUYV',)))['passed'])

    def test_missing_rgb_size_and_other_camera_size_fail(self):
        self.assertFalse(self.validate(enumeration().replace('Size: Discrete 640x480','Size: Discrete 1280x1024',1))['passed'])
        self.assertFalse(self.validate(enumeration().replace(' Size: Discrete 640x480\n Interval: Discrete 0.017s (60.000 fps)','',1))['passed'])

    def test_duplicates_and_ab24_fail(self):
        self.assertFalse(self.validate(enumeration(('Y16','AR24','YUYV','AB24')))['passed'])
        self.assertFalse(self.validate(enumeration(('Y16','AR24','YUYV','YUYV')))['passed'])

    def test_active_geometry_layout_and_rate_failures(self):
        for text in [current(w=1280),current(fmt='AR24',bpp=4),current().replace('1280','640'),current().replace('614400','100')]:
            self.assertFalse(self.validate(active=text)['passed'])
        self.assertFalse(self.validate(enumeration().replace('60.000 fps','30.000 fps'))['passed'])

    def test_old_enumeration_and_be_name(self):
        text="Index : 0\nPixel Format: 'Y16 -BE'\n Size: Discrete 640x480\n Interval: Discrete 0.017s (60.000 fps)"
        r=V.validate_metadata(text,current('Y16 -BE'),640,480,'Y16 -BE')
        self.assertTrue(r['passed']);self.assertFalse(r['interval_accuracy_verified'])


class IoctlTests(unittest.TestCase):
    def fake_ioctl(self,strict):
        original=bytearray(V.SIZE);struct.pack_into('=I',original,0,1)
        struct.pack_into('=6I',original,V.OFFSET,640,480,int.from_bytes(b'YUYV','little'),1,1280,614400)
        state={'data':bytearray(original)}
        def ioctl(fd,number,data,mutate):
            if number==V.G_FMT:data[:]=state['data'];return 0
            requested=V.decode_format(data)
            is_native=(requested['width'],requested['height'],requested['format'])==(640,480,'YUYV')
            if not is_native and strict:raise OSError(errno.EINVAL,'unsupported')
            if number==V.S_FMT:state['data']=bytearray(data)
            return 0
        return original,state,ioctl

    def test_true_kernel_rejections_and_restoration(self):
        for strict in [True,False]:
            original,state,ioctl=self.fake_ioctl(strict)
            with patch.object(V.os,'open',return_value=7),patch.object(V.os,'close') as close,patch.object(V.fcntl,'ioctl',side_effect=ioctl):
                result=V.check_rejections('/dev/fake')
                self.assertEqual(result['passed'],strict)
                self.assertEqual(len(result['checks']),8)
                self.assertEqual(state['data'],original)
                close.assert_called_once_with(7)

    def test_valid_s_fmt_colorimetry_normalization_is_not_a_failed_rejection(self):
        original,state,base=self.fake_ioctl(True)
        def ioctl(fd,number,data,mutate):
            result=base(fd,number,data,mutate)
            if number==V.S_FMT:
                struct.pack_into('=I',state['data'],V.OFFSET+24,8)
            return result
        with patch.object(V.os,'open',return_value=7),patch.object(V.os,'close'),patch.object(V.fcntl,'ioctl',side_effect=ioctl):
            result=V.check_rejections('/dev/fake')
        self.assertTrue(result['passed'])
        self.assertEqual(result['native_set_metadata_changes']['colorspace'],[0,8])

    def test_runtime_pixel_formats_only_reject_other_geometry(self):
        original,state,ioctl=self.fake_ioctl(True)
        with patch.object(V.os,'open',return_value=7),patch.object(V.os,'close'),patch.object(V.fcntl,'ioctl',side_effect=ioctl):
            result=V.check_rejections('/dev/fake',['YUYV','AR24'],fixed_pixel_format=False)
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['checks']),4)
        self.assertEqual({c['case'] for c in result['checks']},{'other-width','other-height'})
        self.assertFalse(result['fixed_pixel_format'])
        self.assertEqual(state['data'],original)

    def test_other_sensor_models_are_rejected_even_if_the_dt_declares_them(self):
        original,state,ioctl=self.fake_ioctl(True)
        with patch.object(V.os,'open',return_value=7),patch.object(V.os,'close'),patch.object(V.fcntl,'ioctl',side_effect=ioctl):
            result=V.check_rejections('/dev/fake',fixed_pixel_format=False,
                other_sizes=[(640,480),(2048,1088),(2048,2048),(2048,1088)])
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['checks']),8)
        self.assertEqual({c['case'] for c in result['checks']},
                         {'other-width','other-height','other-model-2048x1088','other-model-2048x2048'})
        self.assertEqual(state['data'],original)

    def test_big_endian_fourcc_roundtrip(self):
        b=bytearray(V.SIZE);struct.pack_into('=I',b,V.OFFSET+8,int.from_bytes(b'Y16 ','little')|0x80000000)
        self.assertEqual(V.decode_format(b)['format'],'Y16 -BE')


class OracleTests(unittest.TestCase):
    def test_rgb_order_is_an_independent_reference(self):
        expected=enginecore_rgb(81,90,240)
        self.assertEqual(expected,[254,0,0])
        payload=bytes([0,0,254,255])*8
        self.assertTrue(check_frame(payload,'AR24',4,2,16,dict(kind='rgb',value=expected))['passed'])
        bad=check_frame(payload,'AB24',4,2,16,dict(kind='rgb',value=expected))
        self.assertFalse(bad['passed']);self.assertEqual(bad['mismatch_pixels'],8)
        payload=bytes([254,0,0,255])*8
        self.assertTrue(check_frame(payload,'AB24',4,2,16,dict(kind='rgb',value=expected))['passed'])

    def test_yuyv_order_and_component_values(self):
        reference=dict(kind='yuyv',value=[81,90,81,240])
        self.assertTrue(check_frame(bytes(reference['value'])*4,'YUYV',4,2,8,reference)['passed'])
        self.assertFalse(check_frame(bytes([90,81,240,81])*4,'YUYV',4,2,8,reference)['passed'])

    def test_gray_endianness_bit_depth_and_counter(self):
        values=np.arange(640*2,dtype='<u2')
        self.assertTrue(check_frame(values.tobytes(),'Y16',640,2,1280,dict(kind='counter16'))['passed'])
        self.assertFalse(check_frame(values.byteswap().tobytes(),'Y16',640,2,1280,dict(kind='counter16'))['passed'])
        for fmt,dtype in [('Y16','<u2'),('Y16 -BE','>u2'),('Y14','<u2')]:
            raw=np.full((2,4),0x1234,dtype=dtype).tobytes()
            self.assertTrue(check_frame(raw,fmt,4,2,8,dict(kind='gray',value=0x1234))['passed'])
            self.assertFalse(check_frame(raw,fmt,4,2,8,dict(kind='gray',value=0x3412))['passed'])

    def test_stride_padding_does_not_become_pixels(self):
        row=bytes([0,0,254,255])*4+b'\xa5'*8
        self.assertTrue(check_frame(row*2,'AR24',4,2,24,dict(kind='rgb',value=[254,0,0]))['passed'])
        self.assertFalse(check_frame(row,'AR24',4,2,24,dict(kind='rgb',value=[254,0,0]))['passed'])

class RestorationTests(unittest.TestCase):
    def test_reference_reads_retry_errors_with_spacing_and_a_bound(self):
        r=SimpleNamespace(options=SimpleNamespace(recoveries=2),pause=Mock(),event=Mock(),
                          enginecore_control_pause=lambda:5)
        camera=SimpleNamespace(enginecore=True,device='/dev/eg-ec-mipi-10-0016',name='Crius1280')
        r.run=Mock(side_effect=[({'returncode':0},'!-128\n'),({'returncode':0},'0x00000009 9\n')])
        self.assertEqual(Controls(r,camera,'test').read(0x194),9)
        self.assertEqual(r.run.call_count,2)
        self.assertEqual(r.pause.call_count,2)
        self.assertTrue(all(c.args[0]==5 for c in r.pause.call_args_list))
        r.run=Mock(return_value=({'returncode':0},'0x9 8\n'))
        with self.assertRaisesRegex(RuntimeError,'bounded retries'):
            Controls(r,camera,'test').read(0x194)
        self.assertEqual(r.run.call_count,3)

    def test_reference_coverage_requires_every_camera_capability(self):
        from run_camera_regression import Runner
        r = Runner.__new__(Runner)
        r.reference_capabilities = {'camera': ['Y16 ', 'AR24', 'YUYV']}
        r.reference_results = [dict(key='camera', format='YUYV', passed=True)]
        report = r.reference_coverage()
        self.assertFalse(report['complete'])
        self.assertEqual({x['format'] for x in report['missing']}, {'Y16', 'AR24'})
        r.reference_results += [dict(key='camera', format=f, passed=True) for f in ('Y16 ', 'AR24')]
        self.assertTrue(r.reference_coverage()['complete'])
        r.reference_results.append(dict(key='camera', format='AR24', passed=False))
        self.assertFalse(r.reference_coverage()['complete'])

    def test_palette_restores_after_capture_exception(self):
        with tempfile.TemporaryDirectory(prefix='camera report ') as tmp:
            folder=Path(tmp)
            initial={0x700:1,0x800:1,0x1000:0,0x4000:2}
            registers=dict(initial);palette={'data':b'\x5a'*3520};before=palette['data']
            runner=SimpleNamespace(options=SimpleNamespace(control_pause=0),pause=Mock(),save=Mock(),
                enginecore_control_pause=lambda:0,capture_reference=Mock(side_effect=RuntimeError('capture failed')))
            def command(label,args,**kwargs):
                words=args[-1].split();op=words[0]
                if op=='ru':
                    v=registers[int(words[1],0)];return {'returncode':0},'%#x %d'%(v,v)
                if op=='rm':Path(words[2]).write_bytes(palette['data']);return {'returncode':0},'!1'
                if op=='wm':palette['data']=Path(words[2]).read_bytes();return {'returncode':0},'!2'
                raise AssertionError(args)
            runner.run=command
            runner.ec_control=lambda camera,address,value:registers.__setitem__(int(address,0),value)
            camera=SimpleNamespace(enginecore=True,device='/dev/eg-ec-mipi-10-0016')
            record={}
            with self.assertRaisesRegex(RuntimeError,'capture failed'):
                execute_reference(runner,camera,'AR24','test',folder,record)
            self.assertTrue(record['restored']);self.assertEqual(registers,initial)
            self.assertEqual(palette['data'],before)

    def test_dione_restores_on_capture_failure_and_reports_restore_failure(self):
        for fail_restore in (False, True):
            with self.subTest(fail_restore=fail_restore), tempfile.TemporaryDirectory() as tmp:
                initial={0x80108:2,0x8012c:7,0x8010c:1,0x80194:0x02180014,0x81404:1,0x81004:0}
                registers=dict(initial)
                runner=SimpleNamespace(options=SimpleNamespace(control_pause=0),pause=Mock(),save=Mock(),
                    capture_reference=Mock(side_effect=RuntimeError('capture failed')))
                def command(label,args,**kwargs):
                    op=args[5];address=int(args[6],0)
                    if op=='read_reg32':return {'returncode':0},hex(registers[address])
                    value=int(args[7],0)
                    if fail_restore and address==0x80194 and value==initial[address]:
                        raise RuntimeError('restore write failed')
                    if address==0x80104:registers[0x8010c]=int(value==1)
                    else:registers[address]=value
                    return {'returncode':0},'OK'
                runner.run=command
                camera=SimpleNamespace(enginecore=False,device='/dev/dioneir-i2c-9-000e-5d')
                record={}
                with self.assertRaisesRegex(RuntimeError,'capture failed'):
                    execute_reference(runner,camera,'AR24','test',Path(tmp),record)
                self.assertEqual(record['restored'],not fail_restore)
                if not fail_restore:self.assertEqual(registers,initial)
                else:self.assertTrue(record['restoration_errors'])

    def test_missing_profile_is_not_a_pass_and_does_no_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner=SimpleNamespace(save=Mock(),run=Mock(side_effect=AssertionError('unexpected I/O')))
            camera=SimpleNamespace(enginecore=False,device='/dev/titan-10-0010')
            record={}
            self.assertFalse(execute_reference(runner,camera,'Y14','test',Path(tmp),record))
            self.assertEqual(record['status'],'not_run')
            self.assertNotIn('passed',record)
            runner.run.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
