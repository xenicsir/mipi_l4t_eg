#!/usr/bin/env python3
"""Run real MicroLynx chardev operations through open/unbind/close."""
from pathlib import Path
import subprocess,tempfile,unittest
from test_titan_driver import function
ROOT=Path(__file__).resolve().parents[2]
LIB=ROOT/'sources/common/source/nvidia-oot/drivers/media/i2c/gencp-over-i2c'
DRIVER=LIB.parent/'microlynx_core.c'
SHIM=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <linux/types.h>
#include <sys/ioctl.h>
#include "eg_camera_gencp.h"
typedef uint32_t u32;
#define __user
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define mutex_lock(p) (assert(!*(p)), *(p)=1)
#define mutex_unlock(p) (assert(*(p)), *(p)=0)
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define copy_from_user(d,s,n) (memcpy(d,s,n),0)
#define copy_to_user(d,s,n) (memcpy(d,s,n),0)
struct inode {int unused;};struct file {void *private_data;};
struct kref {int count;};struct unio_handle {int id;};
struct microlynx {int miscdev;bool gencp_initialized;struct kref refcount;struct unio_handle io_handle;};
static int microlynx_gencp_lock,reads;static bool freed;
static struct unio_handle *selected;
static void kfree(void *p){(void)p;freed=true;}
static void kref_get(struct kref *r){r->count++;}
static void kref_put(struct kref *r,void(*release)(struct kref *)){assert(r->count);if(!--r->count)release(r);}
static void GENCPCLIENT_Select(struct unio_handle *h){assert(microlynx_gencp_lock);selected=h;}
static int GENCPCLIENT_ReadRegister(u32 a,u32 *v){assert(selected && microlynx_gencp_lock);(void)a;reads++;*v=0x12345678;return 0;}
static int GENCPCLIENT_WriteRegister(u32 a,u32 v){assert(selected && microlynx_gencp_lock);(void)a;(void)v;return 0x8003;}
static int GENCPCLIENT_ReadString(u32 a,unsigned char *v,u32 n){assert(selected && microlynx_gencp_lock);(void)a;memset(v,'Z',n);return 0;}
static long GENCPCLIENT_UserExchange(struct unio_handle *h,unsigned long arg){assert(h==selected);(void)arg;return 42;}
static long GENCPCLIENT_UserStats(struct unio_handle *h,unsigned long arg){assert(h==selected);(void)arg;return 43;}
'''
STREAM_SHIM=r'''
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
#define PRINT_INFO(...) ((void)0)
#define REG_ACQ_STATUS_R 0x500f000c
#define REG_ACQ_START_W 0x500f0000
struct tegracam_device {struct microlynx *priv;};
#define tegracam_get_privdata(d) ((d)->priv)
'''
CASES=r'''
int main(void){
 struct microlynx c={.gencp_initialized=true,.refcount={1}};
 struct file f={.private_data=&c.miscdev};
 struct tegracam_device tc={.priv=&c};
 assert(!microlynx_start_streaming(&tc));assert(!microlynx_gencp_lock);reads=0;
 struct microlynx_reg_op r={.addr=0x44};struct microlynx_str_op s={.addr=0x44,.len=257};
 assert(!microlynx_cdev_open(0,&f)&&c.refcount.count==2);
 assert(!microlynx_cdev_ioctl(&f,MICROLYNX_IOCTL_READ_REG,(unsigned long)&r)&&r.val==0x12345678);
 assert(microlynx_cdev_ioctl(&f,MICROLYNX_IOCTL_WRITE_REG,(unsigned long)&r)==0x8003);
 assert(!microlynx_cdev_ioctl(&f,MICROLYNX_IOCTL_READ_STR,(unsigned long)&s)&&s.len==256&&s.buf[255]=='Z');
 assert(microlynx_cdev_ioctl(&f,EG_IOCTL_GENCP_XFER,0)==42);
 assert(microlynx_cdev_ioctl(&f,EG_IOCTL_GENCP_STATS,0)==43);
 c.gencp_initialized=false;
 assert(microlynx_start_streaming(&tc)==-EIO);assert(!microlynx_gencp_lock);
 kref_put(&c.refcount,microlynx_free);
 assert(!freed&&c.refcount.count==1);
 assert(microlynx_cdev_ioctl(&f,EG_IOCTL_GENCP_XFER,0)==-ENODEV&&reads==1);
 assert(!microlynx_cdev_release(0,&f)&&freed);
 f.private_data=&c.miscdev;assert(microlynx_cdev_open(0,&f)==-ENODEV);
 return 0;
}
'''
class ChardevTests(unittest.TestCase):
 def test_real_operations_and_unbind(self):
  source=DRIVER.read_text()
  declarations=source[source.index('struct microlynx_reg_op {'):source.index('/* Serialize legacy')]
  code=SHIM+STREAM_SHIM+declarations+'\n'+'\n'.join(function(source,n) for n in ('microlynx_start_streaming','microlynx_free','microlynx_cdev_open','microlynx_cdev_release','microlynx_cdev_ioctl'))+CASES
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'test.c').write_text(code)
   subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined','-fno-pie','-no-pie','-I'+str(LIB),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)
if __name__=='__main__':unittest.main()
