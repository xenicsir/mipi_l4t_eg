#!/usr/bin/env python3
"""Exercise real framework functions with RGB aliases and two fixed-size cameras."""
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
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define array_index_nospec(i,n) (i)
#define spec_bar() do {} while(0)
#define dev_dbg(...) do {} while(0)
#define dev_err(...) do {} while(0)
#define HDR_ENABLE 1
#define TEGRA_CAMERA_CID_HDR_EN 0
#define V4L2_FIELD_NONE 0
#define V4L2_COLORSPACE_SRGB 0
#define V4L2_XFER_FUNC_DEFAULT 0
#define V4L2_YCBCR_ENC_DEFAULT 0
#define V4L2_QUANTIZATION_DEFAULT 0
struct device_node { const char *compatible; };
struct device { struct device_node *of_node; };
static bool of_device_is_compatible(const struct device_node *n,const char *s)
{ return !strcmp(n->compatible,s); }
struct camera_common_colorfmt { u32 code,pix_fmt; };
static const struct camera_common_colorfmt camera_common_color_fmts[]={
 {0x100a,99}, {0x100a,98}, {0x100a,20}, {0x2011,10}, {0x202e,30}
};
struct sensor_image_properties {u32 pixel_format;};
struct sensor_mode {struct sensor_image_properties image_properties;};
struct sensor_properties {size_t num_modes;struct sensor_mode *sensor_modes;};
struct camera_common_frmfmt {struct {u32 width,height;}size;const int *framerates;int num_framerates,hdr_en,mode;};
struct camera_common_data {
 const struct camera_common_colorfmt *colorfmt;
 struct device *dev;struct sensor_properties sensor_props;
 const struct camera_common_frmfmt *frmfmt;int numfmts;
 int def_width,def_height,fmt_width,fmt_height;
 int def_mode,mode,mode_prop_idx,sensor_mode_id;
 bool use_sensor_mode_id;void *ctrl_handler;
};
struct v4l2_subdev {struct camera_common_data *dev;};
#define to_camera_common_data(d) (d)
struct v4l2_subdev_state {};
struct v4l2_subdev_pad_config {};
struct v4l2_subdev_frame_size_enum {u32 index,code,min_width,max_width,min_height,max_height;};
struct v4l2_subdev_frame_interval_enum {u32 index,code,width,height;struct {u32 numerator,denominator;}interval;};
struct v4l2_mbus_framefmt {u32 width,height,code,field,colorspace,xfer_func,ycbcr_enc,quantization;};
struct tegra_channel {};
static struct tegra_channel channel;
#define v4l2_get_subdev_hostdata(sd) (&channel)
struct v4l2_control {int id,value;};
static int switch_ctrl_qmenu[]={0,1};
static int v4l2_g_ctrl(void *handler,struct v4l2_control *ctrl) {return -EINVAL;}
static const struct camera_common_colorfmt *camera_common_find_datafmt(u32 code)
{ for(unsigned i=0;i<ARRAY_SIZE(camera_common_color_fmts);i++)if(camera_common_color_fmts[i].code==code)return &camera_common_color_fmts[i];return 0; }
static bool camera_common_verify_code(struct tegra_channel *c,u32 code) {return code==0x100a || code==0x2011 || code==0x202e;}
'''
CASES = r'''
int main(void) {
 const int rates[]={60};
 struct sensor_mode modes[]={{{10}},{{20}},{{30}},{{10}},{{20}},{{30}}};
 struct camera_common_frmfmt formats[]={
  {{640,480},rates,1,0,0},{{640,480},rates,1,0,1},{{640,480},rates,1,0,2},
  {{1280,1024},rates,1,0,3},{{1280,1024},rates,1,0,4},{{1280,1024},rates,1,0,5}
 }, before[6];
 struct device_node mcnode={"exosens,eg-ec-mipi"},crnode={"xenics,eg-ec-mipi"};
 struct device mcdev={&mcnode},crdev={&crnode};
 struct camera_common_data mc={.colorfmt=&camera_common_color_fmts[2],.dev=&mcdev,.sensor_props={6,modes},.frmfmt=formats,.numfmts=6,.def_width=640,.def_height=480,.def_mode=0};
 struct camera_common_data cr=mc;cr.dev=&crdev;cr.def_width=1280;cr.def_height=1024;cr.def_mode=3;
 struct v4l2_subdev msd={&mc},csd={&cr};
 struct v4l2_subdev_frame_size_enum size={.code=0x100a};
 struct v4l2_subdev_frame_interval_enum interval={.code=0x100a,.width=640,.height=480};
 struct v4l2_mbus_framefmt requested={.width=1280,.height=1024,.code=0x100a};
 memcpy(before,formats,sizeof(formats));
 /* Neither of the first two RGB aliases is a sensor-mode fourcc. */
 assert(!camera_common_evaluate_color_format(&msd,0x100a));
 assert(camera_common_evaluate_color_format(&msd,0xdead)==-EINVAL);
 assert(!camera_common_enum_framesizes(&msd,0,&size));
 assert(size.max_width==640 && size.max_height==480);
 size.index=1;assert(camera_common_enum_framesizes(&msd,0,&size)==-EINVAL);
 size.index=0;assert(!camera_common_enum_framesizes(&csd,0,&size));
 assert(size.max_width==1280 && size.max_height==1024);
 size.index=1;assert(camera_common_enum_framesizes(&csd,0,&size)==-EINVAL);
 assert(!camera_common_enum_frameintervals(&msd,0,&interval));
 assert(interval.interval.denominator==60);
 interval.width=1280;interval.height=1024;
 assert(camera_common_enum_frameintervals(&msd,0,&interval)==-EINVAL);
 assert(!camera_common_enum_frameintervals(&csd,0,&interval));
 assert(camera_common_try_fmt(&msd,&requested)==-EINVAL);
 assert(requested.width==1280 && mc.mode_prop_idx==0);
 requested.width=640;requested.height=480;
 assert(!camera_common_try_fmt(&msd,&requested));
 assert(mc.mode_prop_idx==0);
 requested.code=0x2011;
 const struct camera_common_colorfmt *old_color=mc.colorfmt;
 assert(camera_common_s_fmt(&msd,&requested)==-EINVAL);
 assert(mc.colorfmt==old_color && mc.fmt_width==640 && mc.fmt_height==480);
 assert(!camera_common_evaluate_color_format(&msd,0x2011));
 requested.code=0x100a;
 /* An incompatible forced mode must not select another model's CSI timing. */
 requested.width=1280;requested.height=1024;
 assert(!camera_common_try_fmt(&csd,&requested));
 assert(cr.mode_prop_idx==3 && cr.mode==3);
 cr.use_sensor_mode_id=true;cr.sensor_mode_id=0;
 assert(camera_common_try_fmt(&csd,&requested)==-EINVAL);
 assert(cr.mode_prop_idx==3 && cr.mode==3);
 cr.sensor_mode_id=4;
 assert(!camera_common_try_fmt(&csd,&requested));
 assert(cr.mode_prop_idx==4 && cr.mode==4);
 assert(mc.numfmts==6 && cr.numfmts==6 && !memcmp(formats,before,sizeof(formats)));
 /* Each iLumos sensor model exposes both gray formats at its own size. */
 struct camera_common_frmfmt ilumos_formats[]={
  {{2048,2048},rates,1,0,0},{{2048,1088},rates,1,0,1},{{1280,1024},rates,1,0,2},
  {{2048,2048},rates,1,0,3},{{2048,1088},rates,1,0,4},{{1280,1024},rates,1,0,5}
 };
 struct sensor_mode ilumos_modes[]={{{10}},{{10}},{{10}},{{30}},{{30}},{{30}}};
 struct device_node inode={"exosens,ilumos"};struct device idev={&inode};
 for(int model=0;model<3;model++) {
  struct camera_common_data data={.colorfmt=&camera_common_color_fmts[3],.dev=&idev,
   .sensor_props={6,ilumos_modes},.frmfmt=ilumos_formats,.numfmts=6,
   .def_width=ilumos_formats[model].size.width,.def_height=ilumos_formats[model].size.height,
   .def_mode=model,.sensor_mode_id=model};
  struct v4l2_subdev sd={&data};
  for(int gray=0;gray<2;gray++) {
   struct v4l2_subdev_frame_size_enum fs={.code=gray?0x202e:0x2011};
   struct v4l2_mbus_framefmt request={.width=data.def_width,.height=data.def_height,.code=fs.code};
   assert(!camera_common_enum_framesizes(&sd,0,&fs));
   assert(fs.max_width==(u32)data.def_width && fs.max_height==(u32)data.def_height);
   fs.index=1;assert(camera_common_enum_framesizes(&sd,0,&fs)==-EINVAL);
   assert(!camera_common_s_fmt(&sd,&request));
   assert(data.colorfmt->code==fs.code && data.mode_prop_idx==model);
   request.width=ilumos_formats[(model+1)%3].size.width;
   request.height=ilumos_formats[(model+1)%3].size.height;
   assert(camera_common_s_fmt(&sd,&request)==-EINVAL);
   assert(data.fmt_width==data.def_width && data.fmt_height==data.def_height && data.mode_prop_idx==model);
  }
 }
 /* Fixed sensor geometry must not lock runtime grayscale pixel selection. */
 const char *gray_cameras[]={"exosens,ilumos","exosens,microlynx","exosens,titan"};
 for(unsigned family=0;family<ARRAY_SIZE(gray_cameras);family++) {
  mcnode.compatible=gray_cameras[family];
  assert(eg_camera_native_resolution(&mcnode));
  assert(!eg_camera_fixed_capture(&mcnode));
  mc.colorfmt=&camera_common_color_fmts[2];
  requested.width=640;requested.height=480;requested.code=0x2011;
  assert(!camera_common_s_fmt(&msd,&requested));
  assert(mc.colorfmt->code==0x2011);
  requested.width=1280;requested.height=1024;
  assert(camera_common_s_fmt(&msd,&requested)==-EINVAL);
  assert(mc.fmt_width==640 && mc.fmt_height==480 && mc.colorfmt->code==0x2011);
  for(unsigned f=0;f<2;f++) {
   size.code=f?0x2011:0x100a;size.index=0;
   assert(!camera_common_enum_framesizes(&msd,0,&size));
   assert(size.max_width==640 && size.max_height==480);
   size.index=1;assert(camera_common_enum_framesizes(&msd,0,&size)==-EINVAL);
   interval.code=size.code;interval.width=1280;interval.height=1024;interval.index=0;
   assert(camera_common_enum_frameintervals(&msd,0,&interval)==-EINVAL);
  }
 }
 size.code=0x100a;
 /* Dione uses the same fixed-size rule; unrelated scalable sensors do not. */
 mcnode.compatible="xenics,dioneir";size.index=1;
 assert(camera_common_enum_framesizes(&msd,0,&size)==-EINVAL);
 mcnode.compatible="vendor,scalable";
 assert(!camera_common_enum_framesizes(&msd,0,&size));
 assert(size.max_width==1280);
 mc.sensor_props.num_modes=0;
 assert(camera_common_evaluate_color_format(&msd,0x100a)==-EINVAL);
 msd.dev=0;assert(camera_common_enum_framesizes(&msd,0,&size)==-EINVAL);
 return 0;
}
'''

class NativeGeometryTests(unittest.TestCase):
    def test_available_cti_resolution_preserves_native_and_vendor_modes(self):
        root=ROOT/'archives/CTI/merge-resolved/36.5.0/source/nvidia-oot/drivers/media/platform/tegra/camera'
        path=root/'camera_common.c'
        if not path.is_file():self.skipTest('Optional CTI resolved sources unavailable')
        source=path.read_text()
        shim=SHIM.replace('struct tegra_channel {};','struct tegra_channel {struct v4l2_subdev *subdev_on_csi;};')
        shim=shim.replace('struct camera_common_data {',r'''
struct camera_common_data;struct v4l2_mbus_framefmt;
struct camera_common_sensor_ops {
 int (*check_unsupported_mode)(struct camera_common_data *,struct v4l2_mbus_framefmt *);
 int (*after_set_pixel_format)(struct camera_common_data *);
};
struct camera_common_data {struct camera_common_sensor_ops *ops;int fse_index;struct device_node *of_node;
''')
        cases=CASES.replace(' mc.sensor_props.num_modes=0;',r'''
 const int thine_rates[]={15};
 struct device_node thine_node={"ridgerun,thp7312"};
 struct camera_common_data thine_data={.of_node=&thine_node};
 struct v4l2_subdev thine_sd={&thine_data};
 channel.subdev_on_csi=&thine_sd;mc.fse_index=1;formats[1].framerates=thine_rates;
 interval.width=640;interval.height=480;interval.index=0;
 assert(!camera_common_enum_frameintervals(&msd,0,&interval));
 assert(interval.interval.denominator==15);
 channel.subdev_on_csi=0;
 assert(!camera_common_enum_frameintervals(&msd,0,&interval));
 assert(interval.interval.denominator==60);
 mc.sensor_props.num_modes=0;
''')
        names=['camera_common_resolution_supported','select_mode','camera_common_try_fmt','camera_common_s_fmt',
               'camera_common_evaluate_color_format','camera_common_enum_framesizes','camera_common_enum_frameintervals']
        code=shim+''.join(function((ROOT/'sources/common/source/nvidia-oot/drivers/media/platform/tegra/camera/eg_rgb_capture.h').read_text(),n) for n in ('eg_camera_fixed_capture','eg_camera_native_resolution'))+'\n'.join(function(source,n) for n in names)+cases
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(code)
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-sign-compare','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)

    def test_dione_probe_initializes_active_mode_before_first_s_fmt(self):
        source=(ROOT/'sources/common/source/nvidia-oot/drivers/media/i2c/dioneir.c').read_text()
        start=source.index('   if (priv->mode >= 0 && priv->mode < ARRAY_SIZE(dione_ir_frmfmt))')
        block=source[start:source.index('\n   err = tegracam_v4l2subdev_register',start)]
        code=r'''
#include <assert.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
struct camera_common_data { int mode,def_mode,mode_prop_idx,sensor_mode_id,def_width,fmt_width,def_height,fmt_height; };
struct tegracam_device {struct camera_common_data *s_data;};
struct dione_ir {int mode;};
struct fmt {struct {int width,height;}size;int mode;};
static struct fmt dione_ir_frmfmt[]={{{640,480},0},{{1280,1024},1},{{320,240},2},{{1024,768},3}};
static void init(struct tegracam_device *tc_dev,struct dione_ir *priv) {
'''+block+r'''
}
int main(void) {
 for(int i=0;i<4;i++) {
  struct camera_common_data data={0};struct tegracam_device tc={&data};struct dione_ir priv={i};
  init(&tc,&priv);
  assert(data.def_mode==i && data.fmt_width==dione_ir_frmfmt[i].size.width && data.fmt_height==dione_ir_frmfmt[i].size.height);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5,10,0) && !defined(PRISTINE_KERNEL)
  assert(data.mode==i && data.mode_prop_idx==i && data.sensor_mode_id==i);
#else
  assert(data.mode==0 && data.mode_prop_idx==0 && data.sensor_mode_id==0);
#endif
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'probe.c').write_text(code)
            for flags in (['-DLINUX_VERSION_CODE=330240'],['-DLINUX_VERSION_CODE=264448'],['-DLINUX_VERSION_CODE=330240','-DPRISTINE_KERNEL']):
                subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-sign-compare']+flags+[str(path/'probe.c'),'-o',str(path/'probe')],check=True)
                subprocess.run([str(path/'probe')],check=True)

    def test_real_framework_functions_all_versions(self):
        versions=yaml.safe_load((ROOT/'eg_config.yaml').read_text())['versions']
        for version in map(str,versions):
            if int(version.split('.')[0])<35:continue
            paths=list((ROOT/'sources'/version/'Linux_for_Tegra').rglob('camera_common.c'))
            self.assertEqual(len(paths),1)
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp:
                source=paths[0].read_text()
                names=['camera_common_resolution_supported','select_mode','camera_common_try_fmt',
                       'camera_common_s_fmt','camera_common_evaluate_color_format','camera_common_enum_framesizes','camera_common_enum_frameintervals']
                path=Path(tmp);(path/'test.c').write_text(SHIM+''.join(function((ROOT/'sources/common/source/nvidia-oot/drivers/media/platform/tegra/camera/eg_rgb_capture.h').read_text(),n) for n in ('eg_camera_fixed_capture','eg_camera_native_resolution'))+'\n'.join(function(source,n) for n in names)+CASES)
                cmd=['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-sign-compare',
                     '-fsanitize=address,undefined','-fno-omit-frame-pointer',str(path/'test.c'),'-o',str(path/'test')]
                r=subprocess.run(cmd,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)
                subprocess.run([str(path/'test')],check=True)

if __name__=='__main__':unittest.main(verbosity=2)
