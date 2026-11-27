#!/usr/bin/env python3
"""Check the new BSP scope and execute its native pixel-format selection."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]


class L4T3922Tests(unittest.TestCase):
    def test_generic_only_configuration(self):
        config=yaml.safe_load((ROOT/'eg_config.yaml').read_text())['versions']['39.2.2']
        self.assertEqual(config['jetpack'],'7.2.2')
        self.assertEqual(config['vendors'],['generic'])
        self.assertNotIn('forecr_ornxs',config['platform_ids'])
        self.assertEqual(set(config['standalone']),{'generic'})
        self.assertFalse((ROOT/'sources/39.2.2/Linux_for_Tegra_forecr').exists())

    def test_actual_gray8_mapping_does_not_double_native_width(self):
        text=(ROOT/'sources/39.2.2/Linux_for_Tegra/source/gst-egv4l2camera/gstnvv4l2camerasrc.cpp').read_text()
        start=text.index('switch (src->pixel_format) {')
        end=text.index('{',start)+1;depth=1
        while depth:
            depth+=(text[end]=='{')-(text[end]=='}');end+=1
        block=text[start:end]
        width=re.search(r'param.params.width = ([^;]+);',text)[1]
        source=r'''
#include <assert.h>
#include <linux/videodev2.h>
#define FALSE 0
#define GST_ERROR_OBJECT(...) ((void)0)
enum {GST_VIDEO_FORMAT_GRAY8,GST_VIDEO_FORMAT_YUY2,GST_VIDEO_FORMAT_UYVY,GST_VIDEO_FORMAT_RGBA,GST_VIDEO_FORMAT_BGRA,GST_VIDEO_FORMAT_BGRx};
enum {NVBUF_COLOR_FORMAT_GRAY8,NVBUF_COLOR_FORMAT_YUYV,NVBUF_COLOR_FORMAT_UYVY,NVBUF_COLOR_FORMAT_RGBA,NVBUF_COLOR_FORMAT_BGRA,NVBUF_COLOR_FORMAT_BGRx};
struct Source {unsigned pixel_format,capture_fourcc,surface_format,bytes_per_pixel,capture_bits,width;};
static int select_format(struct Source *src) {
'''+block+r'''
return 1;
}
static unsigned surface_width(struct Source *self) {return '''+width+r''';}
int main(void) {
 struct Source s={.pixel_format=GST_VIDEO_FORMAT_GRAY8,.width=640};
 assert(select_format(&s));assert(s.capture_fourcc==V4L2_PIX_FMT_GREY && s.bytes_per_pixel==1 && s.capture_bits==8);
 assert(surface_width(&s)==640);
 /* EG's YUYV-to-CUDA preview still stores two bytes per pixel in GRAY8. */
 s.bytes_per_pixel=2;assert(surface_width(&s)==1280);
 s.pixel_format=GST_VIDEO_FORMAT_YUY2;assert(select_format(&s));
 assert(s.capture_fourcc==V4L2_PIX_FMT_YUYV && s.bytes_per_pixel==2 && surface_width(&s)==640);
 s.pixel_format=GST_VIDEO_FORMAT_BGRA;assert(select_format(&s));
 assert(s.capture_fourcc==V4L2_PIX_FMT_ABGR32 && s.bytes_per_pixel==4 && surface_width(&s)==640);
 s.pixel_format=999;assert(!select_format(&s));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'test.c').write_text(source)
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)

if __name__=='__main__':unittest.main()
