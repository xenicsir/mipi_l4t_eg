#!/usr/bin/env python3
"""Exercise Titan's actual C transaction/format functions with a fake GenCP camera.

No hardware is required. Compile selected driver functions with host shims, then
check multi-camera selection, error propagation, format read-back and cleanup.
The shared control tool's ABI tests live in test_exosens_cam_ctrl.py.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "sources/common/source/nvidia-oot/drivers/media/i2c/titan_core.c"


def function(source, name):
    match = re.search(r"static [^\n]+\b" + name + r"\([^;]+?\)\n\{", source)
    if not match:
        raise AssertionError(f"function {name} not found")
    end = source.index("\n}\n", match.end()) + 3
    return source[match.start():end]


SHIM = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <linux/videodev2.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define dev_err(dev, ...) ((void)(dev))
#define dev_info(dev, ...) ((void)(dev))
struct device { int unused; };
struct i2c_client { struct device dev; };
struct unio_handle { int id; };
struct camera_common_colorfmt { u32 pix_fmt; };
struct camera_common_data {
    const struct camera_common_colorfmt *colorfmt;
    int sensor_mode_id, def_mode;
};
struct tegracam_device { struct camera_common_data *s_data; void *priv; };
struct camera_common_frmfmt {
    struct { u32 width, height; } size;
    const int *rates;
    int nrates, hdr, mode;
};
struct titan {
    struct unio_handle io_handle;
    struct i2c_client *i2c_client;
    struct tegracam_device *tc_dev;
    struct camera_common_data *s_data;
    char pixel_format[64];
    u32 native_width, native_height;
    bool gencp_initialized;
};
static unsigned int titan_gencp_users;
static int titan_gencp_lock;
#define mutex_lock(lock) ((void)(lock))
#define mutex_unlock(lock) ((void)(lock))
static unsigned int last_sleep;
static void msleep(unsigned int ms) { last_sleep = ms; }
static void *tegracam_get_privdata(struct tegracam_device *tc) { return tc->priv; }
static struct unio_handle *selected;
static u16 fake_status;
static bool fake_initialized = true, ignore_write;
static unsigned int reads, writes, cleanups;
static u32 formats[2], acquisition[2], last_reg, last_value;
static const struct camera_common_colorfmt colorfmts[] = {
    { V4L2_PIX_FMT_Y16_BE }, { V4L2_PIX_FMT_Y14 }
};
static const struct camera_common_colorfmt *camera_common_find_pixelfmt(u32 fmt)
{
    for (unsigned int i = 0; i < ARRAY_SIZE(colorfmts); i++)
        if (colorfmts[i].pix_fmt == fmt) return &colorfmts[i];
    return NULL;
}
static void GENCPCLIENT_Select(struct unio_handle *h) { selected = h; }
static bool GENCPCLIENT_isSuccesfullyInitialized(void) { return fake_initialized; }
static u16 GENCPCLIENT_ReadRegister(u32 reg, u32 *value)
{
    assert(selected); reads++; last_reg = reg;
    *value = reg == REG_ACQ_STATUS_R ? acquisition[selected->id] : formats[selected->id];
    return fake_status;
}
static u16 GENCPCLIENT_WriteRegister(u32 reg, u32 value)
{
    assert(selected); writes++; last_reg = reg; last_value = value;
    if (!fake_status && !ignore_write) {
        if (reg == REG_ACQ_START_W) {
            assert(value == 1 || value == 2);
            acquisition[selected->id] = value == 1;
        } else {
            formats[selected->id] = value;
        }
    }
    return fake_status;
}
static u16 GENCPCLIENT_ReadString(u32 reg, u8 *buf, u32 len)
{
    assert(selected); last_reg = reg; memset(buf, 'A' + selected->id, len);
    return fake_status;
}
static void GENCPCLIENT_Cleanup(void) { cleanups++; }
'''

CASES = r'''
int main(void)
{
    struct i2c_client client = {0};
    struct camera_common_data data[2] = {{0}};
    struct tegracam_device tc[2] = {{.s_data = &data[0]}, {.s_data = &data[1]}};
    struct titan cams[2] = {
        {.io_handle = {0}, .i2c_client = &client, .tc_dev = &tc[0], .s_data = &data[0],
         .native_width = 1208, .native_height = 1024, .gencp_initialized = true},
        {.io_handle = {1}, .i2c_client = &client, .tc_dev = &tc[1], .s_data = &data[1],
         .native_width = 1208, .native_height = 1024, .gencp_initialized = true}
    };
    u32 value = 0;
    u8 buf[8];
    tc[0].priv = &cams[0]; tc[1].priv = &cams[1];
    formats[0] = PIXEL_FORMAT_MONO16;
    formats[1] = PIXEL_FORMAT_MONO14;
    assert(titan_read_register(&cams[0], REG_PIXEL_FORMAT, &value) == 0);
    assert(value == PIXEL_FORMAT_MONO16 && selected == &cams[0].io_handle);
    assert(titan_read_register(&cams[1], REG_PIXEL_FORMAT, &value) == 0);
    assert(value == PIXEL_FORMAT_MONO14 && selected == &cams[1].io_handle);
    assert(titan_read_string(&cams[0], REG_MODEL_NAME_R, buf, sizeof(buf)) == 0);
    assert(buf[0] == 'A');
    assert(titan_read_string(&cams[1], REG_MODEL_NAME_R, buf, sizeof(buf)) == 0);
    assert(buf[0] == 'B');
    assert(titan_read_string(&cams[0], 0, buf, 0) == -EINVAL);
    assert(titan_read_string(&cams[0], 0, buf, TITAN_STR_MAX + 1) == -EINVAL);
    fake_status = 0x8003;
    assert(titan_read_register(&cams[0], 0, &value) == -EIO);
    assert(titan_write_register(&cams[1], 0, 0) == -EIO);
    assert(titan_read_string(&cams[0], 0, buf, sizeof(buf)) == -EIO);
    fake_initialized = false;
    assert(titan_read_register(&cams[0], 0, &value) == -ENOMEM);
    fake_initialized = true; fake_status = 0;
    reads = writes = 0;
    assert(titan_apply_pixel_format(&cams[0], PIXEL_FORMAT_MONO16) == 0);
    assert(reads == 1 && writes == 0); /* no needless camera write */
    assert(data[0].def_mode == 0 && data[0].colorfmt->pix_fmt == V4L2_PIX_FMT_Y16_BE);
    assert(titan_apply_pixel_format(&cams[0], PIXEL_FORMAT_MONO14) == 0);
    assert(writes == 1 && reads == 3); /* read, write, read-back */
    assert(data[0].def_mode == 1 && data[0].sensor_mode_id == 1);
    assert(data[0].colorfmt->pix_fmt == V4L2_PIX_FMT_Y14);
    assert(strstr(cams[0].pixel_format, "Y14"));
    assert(titan_apply_pixel_format(&cams[0], PIXEL_FORMAT_MONO16) == 0);
    assert(data[0].def_mode == 0 && data[0].colorfmt->pix_fmt == V4L2_PIX_FMT_Y16_BE);
    ignore_write = true;
    assert(titan_apply_pixel_format(&cams[0], PIXEL_FORMAT_MONO14) == -EIO);
    assert(data[0].def_mode == 0); /* don't claim a rejected mode */
    ignore_write = false; fake_status = 0x800B;
    assert(titan_apply_pixel_format(&cams[0], PIXEL_FORMAT_MONO14) == -EIO);
    assert(titan_find_frmfmt(1208, 1024) == 0);
    assert(titan_find_frmfmt(640, 480) == -1);
    assert(titan_find_frmfmt(1280, 1024) == -1); /* superseded placeholder */
    assert(titan_pixfmt_to_reg(V4L2_PIX_FMT_Y14, &value) == 0);
    assert(value == PIXEL_FORMAT_MONO14);
    assert(titan_pixfmt_to_reg(V4L2_PIX_FMT_RGB24, &value) == -EINVAL);
    fake_status = 0;
    reads = writes = 0;
    assert(titan_start_streaming(&tc[0]) == 0);
    assert(reads == 1 && writes == 1 && acquisition[0] == 1);
    assert(last_reg == 0x50000A00 && last_value == 1);
    assert(titan_start_streaming(&tc[0]) == 0);
    assert(reads == 2 && writes == 1); /* already acquiring: no second START */
    assert(last_reg == 0x50000A20);
    assert(titan_stop_streaming(&tc[0]) == 0);
    assert(acquisition[0] == 0 && writes == 2);
    assert(last_reg == 0x50000A00 && last_value == 2 && last_sleep == 50);
    fake_status = 0x8003;
    assert(titan_start_streaming(&tc[0]) == -EIO);
    assert(writes == 2); /* failed status read must not send START */
    assert(titan_stop_streaming(&tc[0]) == -EIO);
    cams[1].gencp_initialized = false;
    assert(titan_start_streaming(&tc[1]) == -ENODEV);
    assert(titan_stop_streaming(&tc[1]) == -ENODEV);
    cams[1].gencp_initialized = true;
    titan_gencp_users = 2;
    titan_gencp_put(&cams[1]);
    assert(!cams[1].gencp_initialized && cleanups == 0 && titan_gencp_users == 1);
    titan_gencp_put(&cams[1]); /* idempotent failed-probe/unbind cleanup */
    assert(titan_gencp_users == 1);
    fake_status = 0;
    assert(titan_read_register(&cams[0], REG_PIXEL_FORMAT, &value) == 0);
    assert(value == PIXEL_FORMAT_MONO16);
    titan_gencp_put(&cams[0]);
    assert(cleanups == 1 && titan_gencp_users == 0);
    puts("Titan C: selection, errors, format read-back, iLumos acquisition and multi-camera cleanup OK");
    return 0;
}
'''


class TitanTests(unittest.TestCase):
    def test_driver_transactions(self):
        source = DRIVER.read_text()
        macros = "\n".join(re.findall(r"^#define (?:REG_|PIXEL_FORMAT_|TITAN_STR_MAX)[^\n]+", source, re.M))
        enum = re.search(r"enum \{.*?\n\};", source, re.S)[0]
        tables = source[source.index("static const int titan_60fps"):source.index("static int titan_find_frmfmt")]
        names = ["titan_find_frmfmt", "titan_gencp_status", "titan_read_register",
                 "titan_write_register", "titan_read_string", "titan_gencp_put",
                 "titan_pixfmt_to_reg", "titan_pixfmt_name", "titan_apply_pixel_format",
                 "titan_start_streaming", "titan_stop_streaming"]
        code = macros + "\n" + SHIM + "\n" + enum + "\n" + tables
        code += "\n".join(function(source, name) for name in names) + CASES
        with tempfile.TemporaryDirectory(prefix="titan-test-") as temp:
            path = Path(temp)
            (path / "test.c").write_text(code)
            subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                            str(path / "test.c"), "-o", str(path / "test")], check=True)
            subprocess.run([str(path / "test")], check=True)



if __name__ == "__main__":
    unittest.main()
