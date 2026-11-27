#!/usr/bin/env python3
"""Run real VI5 dequeue code against stop/wait and multi-port interleavings."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from test_v4l2_enumeration import function

ROOT = Path(__file__).resolve().parents[2]
SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef int64_t s64;
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define LINUX_VERSION_CODE KERNEL_VERSION(5,10,0)
#define CAPTURE_STATUS_UNKNOWN 0
#define CAPTURE_STATUS_SUCCESS 1
#define CAPTURE_STATUS_FLAG_CHANNEL_IN_ERROR 2
#define CAPTURE_IDLE 0
#define CAPTURE_GOOD 1
#define CAPTURE_ERROR 3
#define CAPTURE_TIMEOUT 2
#define CAPTURE_ERROR_TIMEOUT 8
#define CAPTURE_TIMEOUT_MS (-1)
#define MIPI_NO_TIMEOUT (-1)
#define VB2_BUF_STATE_ACTIVE 1
#define VB2_BUF_STATE_ERROR 2
#define VB2_BUF_STATE_DONE 3
#define VB2_BUF_STATE_QUEUED 4
struct timespec64 {s64 value;};
struct capture_descriptor {struct {u32 status,flags,frame_id,err_data;uint64_t sof_timestamp,eof_timestamp;}status;};
struct tegra_mc_vi {void *dev;};
struct vb2_v4l2_buffer {struct {uint64_t timestamp;}vb2_buf;};
struct list_head {struct list_head *next,*prev;};
static void INIT_LIST_HEAD(struct list_head *h) {h->next=h->prev=h;}
static void list_add_tail(struct list_head *n,struct list_head *h) {n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n;}
struct tegra_channel_buffer {struct list_head queue;struct vb2_v4l2_buffer buf;int vb2_state;int capture_descr_index[2];};
struct device {void *of_node;};
struct v4l2_subdev {struct device *dev;};
struct camera_common_data {};
struct tegra_channel {
 bool capture_stopping,queue_error,capture_timeout_recover; int capture_state,capture_state_lock,valid_ports,start_wait,start_lock;
 struct list_head capture;unsigned capture_queue_depth;
 unsigned capture_reqs_enqueued; struct tegra_mc_vi *vi;
 struct capture_descriptor *request[2]; int tegra_vi_channel[2];
 struct v4l2_subdev *subdev_on_csi;
};
static int warnings,errors,releases,wakes,traces,waits,wait_error;
static bool stop_inside_wait,avt;
static struct tegra_channel *waiting_chan;
#define spin_lock(lock) do {assert(!*(lock));*(lock)=1;} while(0)
#define spin_unlock(lock) do {assert(*(lock));*(lock)=0;} while(0)
#define spin_lock_irqsave(lock,flags) do {assert(!*(lock));*(lock)=1;(flags)=0;} while(0)
#define spin_unlock_irqrestore(lock,flags) do {assert(*(lock));*(lock)=0;(void)(flags);} while(0)
#define dev_err(...) (++errors)
#define dev_warn_ratelimited(...) (++warnings)
static struct timespec64 ns_to_timespec64(s64 value) {return (struct timespec64){value};}
static void trace_tegra_channel_capture_frame(const char *s, struct timespec64 *ts) {traces++;}
static void wake_up_interruptible(int *p) {wakes++;}
static void vi5_release_buffer(struct tegra_channel *c, struct tegra_channel_buffer *b) {releases++;}
static int vi_capture_status(int channel,int timeout) {
 assert(!waiting_chan->capture_state_lock); waits++;
 if(stop_inside_wait) waiting_chan->capture_stopping=true;
 return wait_error;
}
static int32_t vi5_capture_timeout(struct tegra_channel *c) {return 100;}
static bool of_device_is_compatible(void *n,const char *s) {return avt;}
#define to_camera_common_data(d) ((struct camera_common_data *)0)
'''
CASES = r'''
static struct tegra_mc_vi vi;
static struct device dev;
static struct v4l2_subdev sd={&dev};
static struct capture_descriptor desc[2];
static struct tegra_channel chan;
static struct tegra_channel_buffer buf;
static void setup(int ports) {
 warnings=errors=releases=wakes=traces=waits=wait_error=0;stop_inside_wait=avt=false;
 memset(desc,0,sizeof(desc)); memset(&buf,0,sizeof(buf));memset(&chan,0,sizeof(chan));
 chan.vi=&vi;chan.valid_ports=ports;chan.capture_state=CAPTURE_GOOD;
 chan.capture_reqs_enqueued=ports;chan.subdev_on_csi=&sd;
 for(int p=0;p<ports;p++) {
  chan.request[p]=&desc[p];chan.tegra_vi_channel[p]=p;
  desc[p].status.status=CAPTURE_STATUS_SUCCESS;desc[p].status.frame_id=17;
  desc[p].status.sof_timestamp=1234;desc[p].status.eof_timestamp=2345;
 }
 INIT_LIST_HEAD(&chan.capture);INIT_LIST_HEAD(&buf.queue);chan.capture_queue_depth=4;
 waiting_chan=&chan;buf.vb2_state=VB2_BUF_STATE_ACTIVE;buf.buf.vb2_buf.timestamp=999;
}
static void unknown(int p) {
 desc[p].status.status=CAPTURE_STATUS_UNKNOWN;
 /* Undefined fields must not cause a channel error or timestamp trace. */
 desc[p].status.flags=UINT32_MAX;desc[p].status.frame_id=2560;
 desc[p].status.sof_timestamp=UINT64_MAX;desc[p].status.eof_timestamp=UINT64_MAX;
}
int main(void) {
 /* No false cancellation of a completed final frame, even during stop. */
 for(int stopping=0;stopping<2;stopping++) {
  setup(1);chan.capture_stopping=stopping;vi5_capture_dequeue(&chan,&buf);
  assert(buf.vb2_state==VB2_BUF_STATE_DONE && releases==1 && chan.capture_reqs_enqueued==0);
  assert(!warnings && !errors && traces==2 && buf.buf.vb2_buf.timestamp==1234);
 }
 /* Most important race: the waiter entered while capture was active. */
 for(int ports=1;ports<=2;ports++) for(int mask=1;mask<(1<<ports);mask++) {
  setup(ports);stop_inside_wait=true;
  for(int p=0;p<ports;p++)if(mask&(1<<p))unknown(p);
  vi5_capture_dequeue(&chan,&buf);
  assert(buf.vb2_state==VB2_BUF_STATE_ERROR && releases==1 && waits==ports);
  assert(!warnings && !errors && !chan.queue_error && !traces);
  assert(chan.capture_reqs_enqueued==0 && wakes==1 && buf.buf.vb2_buf.timestamp==999);
 }
 /* UNKNOWN outside stop and genuine status 14 remain visible. */
 setup(1);unknown(0);desc[0].status.flags=0;vi5_capture_dequeue(&chan,&buf);
 assert(warnings==1 && buf.vb2_state==VB2_BUF_STATE_ERROR && releases==1);
 for(int stopping=0;stopping<2;stopping++) {
  setup(1);chan.capture_stopping=stopping;desc[0].status.status=14;desc[0].status.err_data=0x40;
  vi5_capture_dequeue(&chan,&buf);
  assert(warnings==1 && buf.vb2_state==VB2_BUF_STATE_ERROR && releases==1);
  setup(1);chan.capture_stopping=stopping;desc[0].status.status=14;desc[0].status.flags=2;
  vi5_capture_dequeue(&chan,&buf);assert(errors==1 && chan.queue_error && releases==1);
 }
 /* Gang desynchronisation is still an error for two completed ports. */
 setup(2);desc[1].status.frame_id=18;vi5_capture_dequeue(&chan,&buf);
 assert(errors==1 && buf.vb2_state==VB2_BUF_STATE_ERROR && releases==1);
 /* Existing interrupted/error and already-released recovery paths. */
 setup(1);wait_error=-EIO;vi5_capture_dequeue(&chan,&buf);
 assert(errors==1 && releases==1 && buf.vb2_state==VB2_BUF_STATE_ERROR);
 setup(1);buf.vb2_state=VB2_BUF_STATE_ERROR;vi5_capture_dequeue(&chan,&buf);
 assert(!waits && releases==1 && chan.capture_reqs_enqueued==1);
 return 0;
}
'''

class StopCancellation(unittest.TestCase):

    def test_real_dequeue_all_overlays(self):
        paths = sorted((ROOT/'sources').glob('*/Linux_for_Tegra/**/vi/vi5_fops.c'))
        expected={str(v) for v in yaml.safe_load((ROOT/'eg_config.yaml').read_text())['versions'] if int(str(v).split('.')[0])>=35}
        self.assertEqual({p.relative_to(ROOT/'sources').parts[0] for p in paths},expected)
        cache = ROOT/'archives/CTI/merge-resolved/36.5.0/source/nvidia-oot/drivers/media/platform/tegra/camera/vi/vi5_fops.c'
        if cache.exists():
            paths.append(cache)
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                source = path.read_text()
                start = function(source, 'vi5_channel_start_streaming')
                stop = function(source, 'vi5_channel_stop_streaming')
                self.assertIn('unsigned long flags;', stop)
                self.assertLess(start.index('capture_stopping = false'), start.index('vi5_channel_start_kthreads'))
                self.assertLess(stop.index('capture_stopping = true'), stop.index('complete_all'))
                self.assertLess(stop.index('complete_all'), stop.index('vi5_channel_stop_kthreads'))
                self.assertLess(stop.index('vi5_channel_stop_kthreads'), stop.index('tegra_channel_set_stream'))
                requeue = function(source, 'vi5_requeue_capture_buffer') if 'static void vi5_requeue_capture_buffer(' in source else ''
                text = SHIM + requeue + function(source, 'vi5_capture_cancelled') + function(source, 'vi5_capture_dequeue') + CASES
                with tempfile.TemporaryDirectory() as d:
                    c=Path(d)/'test.c'; binary=Path(d)/'test'
                    c.write_text(text)
                    subprocess.run(['gcc','-std=gnu11','-g','-fsanitize=undefined','-fno-sanitize-recover=all',str(c),'-o',str(binary)],check=True,capture_output=True)
                    subprocess.run([str(binary)],check=True,capture_output=True)

    def test_3922_retains_timeout_requeue_and_enqueue_gating(self):
        source=(ROOT/'sources/39.2.2/Linux_for_Tegra/source/nvidia-oot/drivers/media/platform/tegra/camera/vi/vi5_fops.c').read_text()
        # Select a finite wait only in this harness to exercise NVIDIA's retained
        # recovery branch; production keeps the existing infinite MIPI wait.
        code=SHIM.replace('#define MIPI_NO_TIMEOUT (-1)','#define MIPI_NO_TIMEOUT 200')
        for name in ('vi5_requeue_capture_buffer','vi5_capture_cancelled','vi5_capture_dequeue','vi5_capture_enqueue_ready'):
            code+=function(source,name)
        code+=CASES[:CASES.index('int main(void)')]+r"""
int main(void) {
 setup(1);wait_error=-ETIMEDOUT;vi5_capture_dequeue(&chan,&buf);
 assert(chan.capture_state==CAPTURE_ERROR && chan.capture_timeout_recover);
 assert(!releases && chan.capture.next==&buf.queue && chan.capture.prev==&buf.queue);
 assert(buf.vb2_state==VB2_BUF_STATE_ACTIVE && !chan.start_lock && !chan.capture_state_lock);
 assert(!vi5_capture_enqueue_ready(&chan));
 chan.capture_state=CAPTURE_IDLE;chan.capture_reqs_enqueued=0;
 assert(vi5_capture_enqueue_ready(&chan));
 chan.capture_reqs_enqueued=chan.capture_queue_depth*chan.valid_ports;
 assert(!vi5_capture_enqueue_ready(&chan));
 setup(1);wait_error=-EIO;vi5_capture_dequeue(&chan,&buf);
 assert(releases==1 && !chan.capture_timeout_recover && chan.capture.next==&chan.capture);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'test.c').write_text(code)
            subprocess.run(['gcc','-std=gnu11','-fsanitize=undefined','-fno-sanitize-recover=all',str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)

if __name__ == '__main__':
    unittest.main()
