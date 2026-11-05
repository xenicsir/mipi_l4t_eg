#!/usr/bin/env python3
"""Pattern restoration, capture precision and comparison acceptance boundaries."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hardware'))
from camera_patterns import PatternTransaction
from compare_camera_pixels import difference

class PixelTests(unittest.TestCase):
    def persistent_transaction(self, initial, reboot_failure=False, ignore_first_save=False,
                               restore_failure=False):
        live=dict(initial);bank=dict(initial);events=[];saves=0;boots=0
        def write(address,value):
            nonlocal saves
            events.append(('write',address,value))
            if address==0x2f0:
                saves+=1
                if restore_failure and saves==2:raise OSError('restore save failed')
                if not (ignore_first_save and saves==1):bank.clear();bank.update(live)
            else:live[address]=value
        def restart():
            nonlocal boots
            boots+=1;events.append(('boot',dict(bank)))
            if reboot_failure and boots==1:raise OSError('reboot failed')
            live.clear();live.update(bank)
        t=PatternTransaction('enginecore',live.__getitem__,write,2,restart=restart,
                             on_snapshot=lambda v:events.append(('snapshot',v)))
        return t,live,bank,events

    def test_persisted_pattern_and_original_survive_reboots_after_body_error(self):
        for initial in ({0x190:0,0x194:8},{0x190:1,0x194:9}):
            with self.subTest(initial=initial):
                t,live,bank,events=self.persistent_transaction(initial)
                with self.assertRaisesRegex(ValueError,'comparison failed'):
                    with t:
                        self.assertEqual(live,{0x190:1,0x194:2})
                        self.assertEqual(bank,live)
                        raise ValueError('comparison failed')
                self.assertTrue(t.restored)
                self.assertEqual(live,initial);self.assertEqual(bank,initial)
                self.assertEqual(events[0],('snapshot',initial))
                self.assertEqual([x[1] for x in events if x[0]=='boot'],
                                 [{0x190:1,0x194:2},initial])

    def test_failed_activation_reboot_restores_persistent_state(self):
        initial={0x190:0,0x194:8}
        t,live,bank,_=self.persistent_transaction(initial,reboot_failure=True)
        with self.assertRaisesRegex(OSError,'reboot failed'):
            with t:self.fail('Capture must not start after failed reboot')
        self.assertTrue(t.restored);self.assertEqual(live,initial);self.assertEqual(bank,initial)

    def test_missing_saved_pattern_is_detected_before_capture(self):
        initial={0x190:0,0x194:8}
        t,live,bank,_=self.persistent_transaction(initial,ignore_first_save=True)
        with self.assertRaisesRegex(RuntimeError,'did not load'):
            with t:self.fail('Capture must not start without the saved pattern')
        self.assertTrue(t.restored);self.assertEqual(live,initial);self.assertEqual(bank,initial)

    def test_failed_restore_save_is_not_reported_as_restored(self):
        t,live,bank,_=self.persistent_transaction({0x190:0,0x194:8},restore_failure=True)
        with self.assertRaisesRegex(OSError,'restore save failed'):
            with t:pass
        self.assertFalse(t.restored)
        self.assertEqual(bank,{0x190:1,0x194:2})

    def transaction(self,family,initial,pattern=9,body_failure=False,write_failure=None):
        values=dict(initial);writes=[];failed=False
        def write(address,value):
            nonlocal failed
            writes.append((address,value))
            if write_failure==(address,value) and not failed:
                failed=True;raise OSError('injected failure')
            values[address]=value
            if address==0x80104:values[0x8010c]=1 if value==1 else 0
            if address==0x50003008:values[0x50003004]=values[values[0x50003000]]
            if address==0x5000300c:values[values[0x50003000]]=values[0x50003004]
        t=PatternTransaction(family,values.__getitem__,write,pattern)
        try:
            with t:
                if body_failure:raise ValueError('comparison failed')
        except (ValueError,OSError):pass
        return t,values,writes

    def test_ec_restores_enable_and_selection_after_comparison_error(self):
        t,v,w=self.transaction('enginecore',{0x190:1,0x194:9},2,True)
        self.assertTrue(t.restored);self.assertEqual(v,{0x190:1,0x194:9})
        self.assertNotIn(0x2f0,[a for a,_ in w]);self.assertIn((0x194,2),w)

    def test_partial_activation_failure_also_restores(self):
        t,v,w=self.transaction('enginecore',{0x190:0,0x194:8},9,write_failure=(0x194,9))
        self.assertTrue(t.restored);self.assertEqual(v,{0x190:0,0x194:8})

    def test_ilumos_disable_enable_counter_and_restore_full_word(self):
        t,v,w=self.transaction('ilumos',{0x60010044:2,0x50003000:0x123,0x50003004:0x456,0x50000a1c:0,0x50000504:1,0x50000508:1,0x50000510:2,0x50000a20:0})
        self.assertTrue(t.restored);self.assertEqual(v[0x60010044],2)
        self.assertEqual(v[0x50003000],0x123);self.assertEqual(v[0x50003004],0x456)
        self.assertIn((0x50000504,4),w);self.assertIn((0x50000a1c,1),w)
        self.assertEqual(v[0x50000a1c],0);self.assertEqual(v[0x50000504],1)
        self.assertEqual(v[0x50000508],1);self.assertEqual(v[0x50000510],2)

    def test_dione_restores_source_pattern_and_acquisition(self):
        initial={0x80108:1,0x8012c:0x8073,0x8010c:1}
        t,v,w=self.transaction('dione',initial,body_failure=True)
        self.assertTrue(t.restored)
        for key,value in initial.items():self.assertEqual(v[key],value)
        self.assertIn((0x8012c,4),w);self.assertIn((0x80108,0),w)
        self.assertNotIn(0x1002000c,[a for a,_ in w])

    def test_raw_samples_reject_even_one_bit_but_normalization_allows_one_level(self):
        a=np.array([0,255,32768,65535],np.uint16);b=a.copy();b[2]^=1
        self.assertFalse(difference(a,b)['passed'])
        self.assertTrue(difference(np.array([0,127,255]),np.array([0,128,255]),1)['passed'])
        self.assertFalse(difference(np.array([0,127,255]),np.array([0,129,255]),1)['passed'])
        self.assertFalse(difference(np.zeros((2,3)),np.zeros((3,2)))['passed'])

    def test_color_channel_swap_is_detected(self):
        a=np.array([[[17,90,220]]],np.uint8)
        self.assertFalse(difference(a,a[:,:,::-1],3)['passed'])

if __name__=='__main__':unittest.main()
