#!/usr/bin/env python3
"""Check VI RGB packing against the V4L2 byte-order contract across BSPs."""
from pathlib import Path
import re
import subprocess
import tempfile
from test_v4l2_enumeration import function
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


def rgb_entries(text):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    return [tuple(field.strip() for field in entry.split(','))
            for entry in re.findall(r'TEGRA_VIDEO_FORMAT\(([^()]*)\)', text)
            if entry.split(',')[0].strip() == 'RGB888']


def packed_bytes(hardware_format, channels):
    """VI packed-word components are listed MSB first; Jetson memory is LE."""
    suffix = hardware_format[2:] if hardware_format.startswith('T_') else hardware_format
    components = re.findall(r'([ARGB])8', suffix)
    if len(components) != 4 or ''.join(c + '8' for c in components) != suffix:
        raise ValueError(hardware_format)
    return bytes(channels[c] for c in reversed(components))


class RgbMemoryFormatTests(unittest.TestCase):
    def test_legacy_and_pristine_labels_do_not_require_patched_framework(self):
        header = ROOT / 'sources/common/source/nvidia-oot/drivers/media/i2c/eg_rgb_capture_name.h'
        for version, defines, expected in [(0x040900, '', 'AR24'),
                                          (0x050f00, '#define PRISTINE_KERNEL\n#define EG_RGB888_AB24\n', 'AB24')]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                tmp=Path(tmp);(tmp/'linux').mkdir()
                (tmp/'linux/version.h').write_text(
                    '#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))\n'
                    '#define LINUX_VERSION_CODE %d\n' % version)
                (tmp/'eg_rgb_capture_name.h').write_text(header.read_text())
                (tmp/'test.c').write_text('#include <string.h>\n#include <assert.h>\n'
                    'struct device { void *of_node; };\n'+defines+
                    '#include "eg_rgb_capture_name.h"\n'
                    'int main(void) { struct device d={0}; '
                    'assert(strstr(eg_rgb_capture_name(&d), "%s")); return 0; }' % expected)
                result=subprocess.run(['cc','-I',str(tmp),str(tmp/'test.c'),'-o',str(tmp/'test')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                subprocess.run([str(tmp/'test')],check=True)

    def test_camera_policy_and_initial_format(self):
        header = ROOT / 'sources/common/source/nvidia-oot/drivers/media/platform/tegra/camera/eg_rgb_capture.h'
        shim = r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stddef.h>
#include <time.h>
#include <linux/videodev2.h>
typedef uint32_t u32;
#include "eg_rgb_capture.h"
#define MEDIA_BUS_FMT_RGB888_1X24 0x100a
struct device { struct device_node *of_node; struct camera_common_data *data; };
struct v4l2_subdev { struct device *dev; };
struct tegra_channel { struct v4l2_subdev *subdev_on_csi; };
struct tegra_video_format { u32 code, fourcc; };
struct camera_common_data { const struct tegra_video_format *colorfmt; };
#define to_camera_common_data(d) ((d)->data)
static const struct tegra_video_format formats[] = {
 {0x100a,V4L2_PIX_FMT_RGBA32}, {0x100a,V4L2_PIX_FMT_ABGR32},
 {0x2011,V4L2_PIX_FMT_YUYV}
};
static const struct tegra_video_format *tegra_core_get_format_by_fourcc(struct tegra_channel *c,u32 f)
{ for (unsigned i=0;i<3;i++) if(formats[i].fourcc==f)return &formats[i]; return 0; }
static int tegra_core_get_idx_by_code(struct tegra_channel *c,u32 code,int start)
{ for(int i=start;i<3;i++)if(formats[i].code==code)return i;return -1; }
static u32 tegra_core_get_fourcc_by_idx(struct tegra_channel *c,unsigned i)
{ assert(i<3);return formats[i].fourcc; }
"""
        cases = r"""
int main(void) {
 struct device_node node={"exosens,dioneir",0};
 struct camera_common_data data={&formats[0]};
 struct device dev={&node,&data};struct v4l2_subdev sd={&dev};
 struct tegra_channel chan={&sd};
 const char *known[]={"exosens,dioneir","xenics,dioneir","exosens,eg-ec-mipi","xenics,eg-ec-mipi"};
 for(unsigned i=0;i<4;i++) {
  node.compatible=known[i];
  assert(!tegra_channel_capture_format(&chan,V4L2_PIX_FMT_RGBA32));
  assert(tegra_channel_capture_format(&chan,V4L2_PIX_FMT_ABGR32));
  assert(tegra_channel_capture_format_by_code(&chan,0x100a)->fourcc==V4L2_PIX_FMT_ABGR32);
  assert(tegra_channel_capture_format(&chan,V4L2_PIX_FMT_YUYV));
 }
 data.colorfmt=&formats[2];
 assert(tegra_channel_capture_format(&chan,V4L2_PIX_FMT_YUYV));
 assert(tegra_channel_capture_format_by_code(&chan,0x100a)->fourcc==V4L2_PIX_FMT_ABGR32);
 data.colorfmt=&formats[0];
 node.compatible="vendor,rgba-camera";node.format="AB24";
 assert(tegra_channel_capture_format_by_code(&chan,0x100a)->fourcc==V4L2_PIX_FMT_RGBA32);
 assert(!tegra_channel_capture_format(&chan,V4L2_PIX_FMT_ABGR32));
 node.format="AR24";
 assert(tegra_channel_capture_format_by_code(&chan,0x100a)->fourcc==V4L2_PIX_FMT_ABGR32);
 node.format=0;
 assert(tegra_channel_capture_format(&chan,V4L2_PIX_FMT_ABGR32));
 assert(tegra_channel_capture_format(&chan,V4L2_PIX_FMT_RGBA32));
 assert(!tegra_channel_capture_format(&chan,0xdead));
 assert(!tegra_channel_capture_format_by_code(&chan,0xbeef));
 chan.subdev_on_csi=0;
 assert(tegra_channel_capture_format(&chan,V4L2_PIX_FMT_RGBA32));
 return 0;
}
"""
        for channel in (ROOT/'sources').glob('*/Linux_for_Tegra/**/vi/channel.c'):
            if int(channel.relative_to(ROOT/'sources').parts[0].split('.')[0]) < 35:
                continue
            with self.subTest(channel=str(channel)), tempfile.TemporaryDirectory() as tmp:
                tmp=Path(tmp);(tmp/'linux').mkdir()
                (tmp/'eg_rgb_capture.h').write_text(header.read_text())
                (tmp/'linux/string.h').write_text('#include <string.h>\n')
                (tmp/'linux/of.h').write_text(r"""
struct device_node { const char *compatible,*format; };
static int of_property_read_string(const struct device_node *n,const char *p,const char **v)
{ if(!n->format)return -1;*v=n->format;return 0; }
static bool of_device_is_compatible(const struct device_node *n,const char *c)
{ return n->compatible && !strcmp(n->compatible,c); }
""")
                source=channel.read_text()
                functions='\n'.join(function(source,n) for n in [
                    'tegra_channel_rgb_format_allowed','tegra_channel_capture_format',
                    'tegra_channel_capture_format_by_code'])
                (tmp/'test.c').write_text(shim+functions+cases)
                compiled = subprocess.run(['cc','-std=c11','-I',str(tmp),str(tmp/'test.c'),'-o',str(tmp/'test')],capture_output=True,text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                subprocess.run([str(tmp/'test')],check=True,capture_output=True)

    def test_supported_bsp_tables_match_v4l2_byte_order(self):
        versions = yaml.safe_load((ROOT / 'eg_config.yaml').read_text())['versions']
        expected_orders = {'ABGR32': 'BGRA', 'RGBA32': 'RGBA'}
        # Independent asymmetric channel references, including the Dione pin oracle.
        samples = [dict(R=0, G=0, B=255, A=255),
                   dict(R=248, G=0, B=0, A=255),
                   dict(R=17, G=93, B=205, A=255)]
        for version in map(str, versions):
            if int(version.split('.')[0]) < 35:
                continue
            with self.subTest(version=version):
                headers = list((ROOT / 'sources' / version /
                                'Linux_for_Tegra').rglob('vi5_formats.h'))
                self.assertEqual(len(headers), 1)
                entries = [e for e in rgb_entries(headers[0].read_text())
                           if e[2] == 'RGB888_1X24' and e[7] in expected_orders]
                expected = {'ABGR32', 'RGBA32'}
                self.assertEqual({e[7] for e in entries}, expected)
                self.assertEqual(len(entries), len(expected))
                for entry in entries:
                    self.assertEqual(entry[1:5], ('24', 'RGB888_1X24', '4', '1'))
                    for channels in samples:
                        actual = packed_bytes(entry[5], channels)
                        wanted = bytes(channels[c] for c in expected_orders[entry[7]])
                        self.assertEqual(actual, wanted, (version, entry[7], entry[5]))
                if version.startswith('35.'):
                    # Preserve the default compatible with GStreamer 1.16.
                    self.assertEqual(entries[0][7], 'ABGR32')


if __name__ == '__main__':
    unittest.main(verbosity=2)
