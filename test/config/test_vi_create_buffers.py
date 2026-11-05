#!/usr/bin/env python3
"""Exercise the VI queue callback without resetting an active descriptor ring."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = [str(v) for v in yaml.safe_load((ROOT/'eg_config.yaml').read_text())['versions']
            if int(str(v).split('.')[0]) >= 35]

SHIM = r'''
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#define dev_info(...) ((void)0)
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
struct device { int unused; };
struct tegra_channel;
struct ops {int (*vi_setup_queue)(struct tegra_channel *, unsigned int *);};
struct tegra_mc_vi {struct ops *fops;};
struct tegra_channel {
    struct tegra_mc_vi *vi;
    struct {unsigned int sizeimage;} format;
    unsigned int depth, outstanding;
};
struct vb2_queue {unsigned int num_buffers; struct tegra_channel *chan;};
static struct device dev;
static struct tegra_channel *vb2_get_drv_priv(struct vb2_queue *q) {return q->chan;}
static struct device *tegra_channel_get_vi_unit(struct tegra_channel *c) {(void)c; return &dev;}
static int calls;
static int setup(struct tegra_channel *c, unsigned int *n) {
    calls++; c->depth=*n; c->outstanding=0; return 0;
}
'''

TEST = r'''
int main(void) {
    struct ops ops={setup}; struct tegra_mc_vi vi={&ops};
    struct tegra_channel c={.vi=&vi,.format={2621440}};
    struct vb2_queue q={.chan=&c};
    unsigned int n=4, planes=0, sizes[2]={0,0}; struct device *devs[2]={0,0};
    assert(tegra_channel_queue_setup(&q,&n,&planes,sizes,devs)==0);
    assert(calls==1 && c.depth==4 && planes==1 && sizes[0]==2621440 && devs[0]==&dev);
    q.num_buffers=4; c.outstanding=3;
    for(int i=0;i<5;i++) {
        n=1; planes=1; sizes[0]=2621440+i*4096; devs[0]=NULL;
        assert(tegra_channel_queue_setup(&q,&n,&planes,sizes,devs)==0);
        assert(calls==1 && c.depth==4 && c.outstanding==3 && n==1 && devs[0]==&dev);
        q.num_buffers++;
    }
    sizes[0]=1;
    assert(tegra_channel_queue_setup(&q,&n,&planes,sizes,devs)==-EINVAL);
    sizes[0]=2621440; planes=2;
    assert(tegra_channel_queue_setup(&q,&n,&planes,sizes,devs)==-EINVAL);
    assert(calls==1 && c.depth==4 && c.outstanding==3);
    q.num_buffers=0; planes=0; n=8;
    assert(tegra_channel_queue_setup(&q,&n,&planes,sizes,devs)==0);
    assert(calls==2 && c.depth==8 && c.outstanding==0);
    return 0;
}
'''

class ViCreateBuffersTests(unittest.TestCase):
    def test_append_preserves_descriptor_ring_and_validates_layout(self):
        for version in VERSIONS:
            paths = sorted((ROOT/'sources'/version/'Linux_for_Tegra').rglob(
                'drivers/media/platform/tegra/camera/vi/channel.c'))
            self.assertTrue(paths, 'Missing VI source for ' + version)
            for source_path in paths:
                with self.subTest(source=str(source_path.relative_to(ROOT))):
                    source = source_path.read_text()
                    start = source.index('static int\ntegra_channel_queue_setup(')
                    end = source.index('\n}\n', start) + 3
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory)
                        (path/'test.c').write_text(SHIM + source[start:end] + TEST)
                        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                                        str(path/'test.c'), '-o', str(path/'test')], check=True)
                        subprocess.run([str(path/'test')], check=True)

if __name__ == '__main__':
    unittest.main()
