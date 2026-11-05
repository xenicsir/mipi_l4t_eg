#!/usr/bin/env python3
"""Ensure new BSP ports retain vendor behavior alongside EG camera extensions."""
from pathlib import Path
import subprocess,tempfile,unittest
from test_v4l2_enumeration import function
ROOT=Path(__file__).resolve().parents[2]

class VendorFeatureTests(unittest.TestCase):
    def test_sensor_parser_keeps_bayer_and_wdr_formats(self):
        for version in ('36.5.2','39.2.1'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as directory:
                source=(ROOT/'sources'/version/'Linux_for_Tegra/source/nvidia-oot/drivers/media/platform/tegra/camera/sensor_common.c').read_text()
                code=r'''
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#include <linux/videodev2.h>
typedef uint32_t u32;
#define OF_MAX_STR_LEN 256
#define pr_err(...) ((void)0)
'''+function(source,'extract_pixel_format')+r'''
int main(void) {
    struct { const char *name; u32 expected; } cases[]={
        {"bayer_bggr14",V4L2_PIX_FMT_SBGGR14},
        {"bayer_rggb14",V4L2_PIX_FMT_SRGGB14},
        {"bayer_gbrg14",V4L2_PIX_FMT_SGBRG14},
        {"bayer_grbg14",V4L2_PIX_FMT_SGRBG14},
        {"bayer_wdr_dol_gbrg10",V4L2_PIX_FMT_SGBRG10},
        {"bayer_wdr_dol_grbg10",V4L2_PIX_FMT_SGRBG10},
        {"bayer_wdr_dol_rggb12",V4L2_PIX_FMT_SRGGB12},
        {"bayer_wdr_dol_gbrg12",V4L2_PIX_FMT_SGBRG12},
        {"bayer_wdr_dol_grbg12",V4L2_PIX_FMT_SGRBG12},
        {"raw_grey16",V4L2_PIX_FMT_Y16},
        {"raw_grey_be16",V4L2_PIX_FMT_Y16_BE},
        {"raw_grey14",V4L2_PIX_FMT_Y14},
    };
    for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++) {
        u32 format=0;
        assert(extract_pixel_format(cases[i].name,&format)==0);
        assert(format==cases[i].expected);
    }
    u32 format=0; assert(extract_pixel_format("unsupported_format",&format)==-EINVAL);
    return 0;
}
'''
                path=Path(directory);(path/'test.c').write_text(code)
                subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(path/'test.c'),'-o',str(path/'test')],check=True)
                subprocess.run([str(path/'test')],check=True)

    def test_native_bayer_tables_and_conftest_are_retained(self):
        for version in ('36.5.2','39.2.1'):
            root=ROOT/'sources'/version/'Linux_for_Tegra/source/nvidia-oot/drivers/media/platform/tegra/camera'
            common=(root/'camera_common.c').read_text();formats=(root/'vi/vi5_formats.h').read_text()
            self.assertIn('#include <nvidia/conftest.h>',common)
            for pattern in ('SBGGR14','SRGGB14','SGRBG14','SGBRG14'):
                self.assertIn('V4L2_PIX_FMT_'+pattern,common)
                self.assertIn(pattern+'_1X14',formats)

    def test_3652_keeps_smbus_and_runtime_pm_safeguards(self):
        text=(ROOT/'sources/36.5.2/Linux_for_Tegra/source/kernel/kernel-jammy-src/drivers/i2c/busses/i2c-tegra.c').read_text()
        for anchor in ('I2C_M_RECV_LEN','I2C_FUNC_SMBUS_READ_BLOCK_DATA',
                       'msg->buf + 1','if (!i2c_dev->multimaster_mode)',
                       '!has_acpi_companion(i2c_dev->dev)','!IS_ENABLED(CONFIG_PREEMPT_RT)',
                       'I2C_ADAPTER_TIMEOUT_INIT'):
            self.assertIn(anchor,text)

if __name__=='__main__':unittest.main()
