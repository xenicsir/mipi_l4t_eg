#!/usr/bin/env python3
"""Compile real framework enumeration functions and check their public results."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def function(source, name):
    start = source.index(name + '(')
    start = source.rfind('\n', 0, start) + 1
    if source[start:].startswith(name):
        start = source.rfind('\n', 0, start - 1) + 1
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define array_index_nospec(i,n) (i)
#define MAX_FORMAT_NUM 16
#define test_bit(i,p) (((*(p)) >> (i)) & 1UL)
#define for_each_set_bit(i,p,n) for ((i)=0; (i)<(n); (i)++) if (test_bit((i),(p)))
struct camera_common_colorfmt { u32 code, pix_fmt; };
static const struct camera_common_colorfmt camera_common_color_fmts[] = {
    {0x2011, 10}, {0x100a, 20}, {0x2008, 10}, {0x202e, 30}, {0x3001, 40}
};
struct sensor_image_properties { u32 pixel_format; };
struct sensor_mode { struct sensor_image_properties image_properties; };
struct sensor_properties { size_t num_modes; struct sensor_mode *sensor_modes; };
struct camera_common_frmfmt { struct { u32 width,height; } size; int mode; };
struct camera_common_data {
    struct sensor_properties sensor_props;
    struct camera_common_frmfmt *frmfmt;
    unsigned int numfmts;
};
struct v4l2_subdev { struct camera_common_data *dev; };
struct v4l2_subdev_state {};
struct v4l2_subdev_pad_config {};
struct v4l2_subdev_frame_size_enum { u32 index,code,min_width,max_width,min_height,max_height; };
#define to_camera_common_data(dev) (dev)
static int evaluate_result;
static int camera_common_evaluate_color_format(struct v4l2_subdev *sd, u32 code)
{ (void)sd; (void)code; return evaluate_result; }
struct tegra_channel { unsigned long fmts_bitmap[1]; u32 fourcc[MAX_FORMAT_NUM]; };
struct file { struct tegra_channel *chan; };
#define video_drvdata(f) ((f)->chan)
struct v4l2_fmtdesc { u32 index,pixelformat; };
static u32 tegra_core_get_fourcc_by_idx(struct tegra_channel *chan, unsigned int i)
{ assert(i<MAX_FORMAT_NUM); return chan->fourcc[i]; }
'''

CASES = r'''
int main(void)
{
    struct sensor_mode modes[] = {{{10}},{{20}},{{30}},{{10}},{{20}},{{30}}};
    struct camera_common_frmfmt sizes[] = {
        {{640,480},0},{{640,480},1},{{640,480},2},
        {{1280,1024},3},{{1280,1024},4},{{1280,1024},5}
    }, saved[6];
    struct camera_common_data data = {{6,modes},sizes,6};
    const u32 codes[] = {0x2011,0x100a,0x2008,0x202e};
    for (size_t i=0;i<4;i++) assert(find_matching_color_fmt(&data,i)->code==codes[i]);
    assert(!find_matching_color_fmt(&data,4));
    assert(!find_matching_color_fmt(&data,SIZE_MAX));
    data.sensor_props.num_modes=0;
    assert(!find_matching_color_fmt(&data,0));
    modes[0].image_properties.pixel_format=999; data.sensor_props.num_modes=1;
    assert(!find_matching_color_fmt(&data,0));
    modes[0].image_properties.pixel_format=10; data.sensor_props.num_modes=6;

    struct tegra_channel chan = {{0}, {0}};
    struct file file = {&chan};
    struct v4l2_fmtdesc fmt;
    chan.fourcc[1]=30; chan.fourcc[3]=20; chan.fourcc[4]=10; chan.fourcc[7]=10;
    chan.fourcc[12]=40;
    const u32 expected[] = {30,20,10,40};
    chan.fmts_bitmap[0]=(1UL<<1)|(1UL<<3)|(1UL<<4)|(1UL<<7)|(1UL<<12);
    unsigned long saved_bitmap=chan.fmts_bitmap[0];
    for (unsigned i=0;i<4;i++) {
        fmt.index=i; assert(!tegra_channel_enum_format(&file,NULL,&fmt));
        assert(fmt.pixelformat==expected[i]);
    }
    fmt.index=4; fmt.pixelformat=123;
    assert(tegra_channel_enum_format(&file,NULL,&fmt)==-EINVAL && fmt.pixelformat==123);
    fmt.index=UINT_MAX; assert(tegra_channel_enum_format(&file,NULL,&fmt)==-EINVAL);
    assert(chan.fmts_bitmap[0]==saved_bitmap);
    /* An unsupported earlier table entry must not hide a supported alias. */
    chan.fmts_bitmap[0]=1UL<<7; fmt.index=0;
    assert(!tegra_channel_enum_format(&file,NULL,&fmt) && fmt.pixelformat==10);
    chan.fmts_bitmap[0]=0;
    assert(tegra_channel_enum_format(&file,NULL,&fmt)==-EINVAL);

    struct v4l2_subdev sd={&data};
    struct v4l2_subdev_frame_size_enum fse={0};
    memcpy(saved,sizes,sizeof(saved));
    assert(!camera_common_enum_framesizes(&sd,NULL,&fse));
    assert(fse.min_width==640 && fse.max_width==640 && fse.max_height==480);
    fse.index=1;
    assert(!camera_common_enum_framesizes(&sd,NULL,&fse));
    assert(fse.min_width==1280 && fse.max_width==1280 && fse.min_height==1024);
    fse.index=2; assert(camera_common_enum_framesizes(&sd,NULL,&fse)==-EINVAL);
    fse.index=UINT_MAX; assert(camera_common_enum_framesizes(&sd,NULL,&fse)==-EINVAL);
    assert(!memcmp(saved,sizes,sizeof(saved)) && data.numfmts==6);
    fse.index=0; evaluate_result=-EINVAL;
    assert(camera_common_enum_framesizes(&sd,NULL,&fse)==-EINVAL);
    evaluate_result=0; data.numfmts=0;
    assert(camera_common_enum_framesizes(&sd,NULL,&fse)==-EINVAL);
    data.numfmts=6; data.frmfmt=NULL;
    assert(camera_common_enum_framesizes(&sd,NULL,&fse)==-EINVAL);
    sd.dev=NULL; assert(camera_common_enum_framesizes(&sd,NULL,&fse)==-EINVAL);
    return 0;
}
'''


class EnumerationTests(unittest.TestCase):
    def test_real_functions_all_supported_framework_versions(self):
        paths = subprocess.check_output(['git','ls-files','*camera_common.c'],cwd=ROOT,text=True).splitlines()
        self.assertEqual(len(paths),13)
        for name in paths:
            with self.subTest(version=Path(name).parts[1]), tempfile.TemporaryDirectory() as tmp:
                path=ROOT/name
                source=path.read_text()
                channel=(path.parent/'vi/channel.c').read_text()
                code=SHIM+'\n'+function(source,'find_matching_color_fmt')+'\n'
                code+=function(source,'camera_common_enum_framesizes')+'\n'
                code+=function(channel,'tegra_channel_enum_format')+'\n'+CASES
                src=Path(tmp)/'test.c'; binary=Path(tmp)/'test'
                src.write_text(code)
                subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                                '-Wno-unused-parameter','-fsanitize=address,undefined',
                                '-fno-omit-frame-pointer',str(src),'-o',str(binary)],check=True)
                subprocess.run([str(binary)],check=True)


if __name__=='__main__':
    unittest.main()
