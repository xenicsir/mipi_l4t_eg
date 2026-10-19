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
#define dev_warn(dev, ...) ((void)(dev))
#define dev_dbg(dev, ...) ((void)(dev))
struct device { int unused; };
struct i2c_client { struct device dev; };
struct unio_handle { int id; };
struct camera_common_colorfmt { u32 pix_fmt; };
struct camera_common_data {
    const struct camera_common_colorfmt *colorfmt;
    int sensor_mode_id, def_mode;
    u32 def_width, def_height, fmt_width, fmt_height;
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
    char pixel_format[64], model[64], serial_number[64], firmware_version[64];
    u32 native_width, native_height;
    bool gencp_initialized;
};
static bool allow_probe_failure = true;
static unsigned int titan_gencp_users;
static int titan_gencp_lock;
#define mutex_lock(lock) ((void)(lock))
#define mutex_unlock(lock) ((void)(lock))
static unsigned int last_sleep;
static void msleep(unsigned int ms) { last_sleep = ms; }
static void *tegracam_get_privdata(struct tegracam_device *tc) { return tc->priv; }
static struct unio_handle *selected;
static u16 fake_status;
static u32 fake_failure_reg = UINT32_MAX;
static bool fake_initialized = true, ignore_write;
static unsigned int reads, writes, cleanups;
static bool checking_probe;
static unsigned int probe_step;
/* Independent FW reference: fail on wrong address, order, string length or STOP. */
static void check_probe(u32 reg, bool string, u32 length, bool write, u32 value)
{
    static const u32 regs[] = {0x10000000, 0x500E0010, 0x500E0000,
                              0x500E0004, 0x44, 0x144, 0x500F0000};
    if (!checking_probe) return;
    assert(probe_step < ARRAY_SIZE(regs) && reg == regs[probe_step]);
    assert(string == (probe_step == 0 || probe_step == 4 || probe_step == 5));
    if (string) assert(length == 64);
    assert(write == (probe_step == 6));
    if (write) assert(value == 0);
    probe_step++;
}
static unsigned int titan_probe_attempts(struct device *dev) { (void)dev; return 1; }
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
    check_probe(reg, false, 0, false, 0);
    switch (reg) {
    case 0x500E0010: *value = formats[selected->id]; break;
    case 0x500E0000: *value = 1280; break;
    case 0x500E0004: *value = 1024; break;
    case 0x500F000C: *value = acquisition[selected->id]; break;
    default: assert(fake_status || !fake_initialized); break;
    }
    return reg == fake_failure_reg ? 0x8003 : fake_status;
}
static u16 GENCPCLIENT_WriteRegister(u32 reg, u32 value)
{
    assert(selected); writes++; last_reg = reg; last_value = value;
    check_probe(reg, false, 0, true, value);
    if (!fake_status && reg != fake_failure_reg && !ignore_write) {
        if (reg == 0x500F0000) {
            assert(value == 1 || value == 0);
            acquisition[selected->id] = value == 1;
        } else {
            assert(reg == 0x500E0010);
            formats[selected->id] = value;
        }
    }
    return reg == fake_failure_reg ? 0x8003 : fake_status;
}
static u16 GENCPCLIENT_ReadString(u32 reg, u8 *buf, u32 len)
{
    assert(selected); last_reg = reg; memset(buf, 'A' + selected->id, len);
    check_probe(reg, true, len, false, 0);
    return reg == fake_failure_reg ? 0x8003 : fake_status;
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
         .native_width = 1280, .native_height = 1024, .gencp_initialized = true},
        {.io_handle = {1}, .i2c_client = &client, .tc_dev = &tc[1], .s_data = &data[1],
         .native_width = 1280, .native_height = 1024, .gencp_initialized = true}
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
    assert(titan_find_frmfmt(1280, 1024) == 0);
    assert(titan_find_frmfmt(640, 480) == -1);
    assert(titan_find_frmfmt(1279, 1024) == -1); /* unsupported width */
    assert(titan_pixfmt_to_reg(V4L2_PIX_FMT_Y14, &value) == 0);
    assert(value == PIXEL_FORMAT_MONO14);
    assert(titan_pixfmt_to_reg(V4L2_PIX_FMT_RGB24, &value) == -EINVAL);
    fake_status = 0;
    checking_probe = true;
    acquisition[0] = 1;
    assert(titan_sensor_check(&cams[0]) == 0);
    assert(probe_step == 7 && acquisition[0] == 0);
    assert(data[0].fmt_width == 1280 && data[0].fmt_height == 1024);
    assert(data[0].colorfmt->pix_fmt == V4L2_PIX_FMT_Y16_BE);
    checking_probe = false;
    /* No response must preserve real register access and discard partial data. */
    fake_status = 0x8003;
    assert(titan_probe_sensor(&cams[0]) == 0);
    assert(cams[0].gencp_initialized);
    assert(cams[0].native_width == 1280 && cams[0].native_height == 1024);
    assert(cams[0].model[0] == 0 && cams[0].serial_number[0] == 0);
    assert(cams[0].firmware_version[0] == 0);
    assert(strcmp(cams[0].pixel_format, "unverified") == 0);
    assert(titan_read_register(&cams[0], REG_IMG_WIDTH_R, &value) == -EIO);
    fake_status = 0;
    assert(titan_read_register(&cams[0], REG_IMG_WIDTH_R, &value) == 0);
    assert(value == 1280); /* ioctl path can recover without another probe */
    const u32 failure_regs[] = {0x10000000, 0x500E0000, 0x500E0004, 0x500F0000};
    for (unsigned int i = 0; i < ARRAY_SIZE(failure_regs); i++) {
        fake_failure_reg = failure_regs[i];
        allow_probe_failure = true;
        assert(titan_probe_sensor(&cams[0]) == 0);
        assert(cams[0].gencp_initialized);
        assert(strcmp(cams[0].pixel_format, "unverified") == 0);
        allow_probe_failure = false;
        assert(titan_probe_sensor(&cams[0]) == -EIO);
    }
    fake_failure_reg = UINT32_MAX;
    allow_probe_failure = true;
    fake_initialized = false;
    assert(titan_probe_sensor(&cams[0]) == -ENOMEM);
    fake_initialized = true;
    allow_probe_failure = false;
    assert(titan_probe_sensor(&cams[0]) == 0);
    assert(strcmp(cams[0].pixel_format, "unverified") != 0);
    allow_probe_failure = true;
    reads = writes = 0;
    assert(titan_start_streaming(&tc[0]) == 0);
    assert(reads == 1 && writes == 1 && acquisition[0] == 1);
    assert(last_reg == 0x500F0000 && last_value == 1);
    assert(titan_start_streaming(&tc[0]) == 0);
    assert(reads == 2 && writes == 1); /* already acquiring: no second START */
    assert(last_reg == 0x500F000C);
    assert(titan_stop_streaming(&tc[0]) == 0);
    assert(acquisition[0] == 0 && writes == 2);
    assert(last_reg == 0x500F0000 && last_value == 0 && last_sleep == 50);
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
    puts("Titan C: selection, errors, format read-back, Titan acquisition and multi-camera cleanup OK");
    return 0;
}
'''


PROBE_SHIM = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define GFP_KERNEL 0
#define CONFIG_OF 1
#define IS_ENABLED(x) (x)
#define MISC_DYNAMIC_MINOR 255
#define dev_err(dev, ...) ((void)(dev))
#define dev_warn(dev, ...) ((void)(dev))
#define dev_info(dev, ...) ((void)(dev))
#define V4L2_PIX_FMT_Y16_BE 1
#define TITAN_MODE_1280x1024_RAW16_BE 0
struct device { void *of_node; };
struct adapter { int nr; };
struct i2c_client { struct device dev; int addr; struct adapter *adapter; };
struct camera_common_data {
    int subdev, sensor_mode_id, def_mode;
    unsigned int def_width, fmt_width, def_height, fmt_height;
    const void *colorfmt;
};
struct tegracam_device {
    struct i2c_client *client;
    struct device *dev;
    char name[16];
    const void *dev_regmap_config, *sensor_ops, *v4l2sd_internal_ops, *tcctrl_ops;
    struct camera_common_data *s_data;
};
struct miscdevice { int minor; char *name; const void *fops; struct device *parent; };
struct titan {
    int refcount;
    struct i2c_client *i2c_client;
    struct tegracam_device *tc_dev;
    struct camera_common_data *s_data;
    int *subdev;
    struct { struct i2c_client *client; } io_handle;
    bool gencp_initialized, misc_registered;
    struct miscdevice miscdev;
    char miscdev_name[32], model[64], serial_number[64], firmware_version[64], pixel_format[64];
    unsigned int native_width, native_height;
};
static int titan_dummy_regmap_config, titan_common_ops, titan_subdev_internal_ops;
static int titan_ctrl_ops, titan_cdev_fops, titan_gencp_lock;
static int dev_attr_model, dev_attr_serial_number, dev_attr_resolution;
static int dev_attr_pixel_format, dev_attr_pixel_formats, dev_attr_firmware_version;
#define mutex_lock(x) ((void)(x))
#define mutex_unlock(x) ((void)(x))
static bool allow_probe_failure = true, transport_ready = true;
static unsigned int titan_gencp_users;
static int sensor_error, framework_error, subdev_error, misc_error;
static unsigned int allocations, allocation_failure, cleanups, unregisters, chardevs;
static struct titan *registered_priv;
static struct tegracam_device *allocated_tc;
static struct camera_common_data data;
static void *kzalloc(size_t size, int flags) {
    (void)flags; allocations++;
    return allocations == allocation_failure ? NULL : calloc(1, size);
}
static void *devm_kzalloc(struct device *dev, size_t size, int flags) {
    (void)dev; return allocated_tc = kzalloc(size, flags);
}
static void kref_init(int *ref) { *ref = 1; }
static void titan_free(int *ref) { (void)ref; }
static void kref_put(int *ref, void (*release)(int *)) {
    release(ref); free(ref); registered_priv = NULL;
}
static int tegracam_device_register(struct tegracam_device *tc) {
    tc->s_data = &data; return framework_error;
}
static void tegracam_device_unregister(struct tegracam_device *tc) { (void)tc; unregisters++; }
static void tegracam_set_privdata(struct tegracam_device *tc, void *priv) {
    (void)tc; registered_priv = priv;
}
static void GENCPCLIENT_Init(void *handle) { (void)handle; }
static void GENCPCLIENT_Select(void *handle) { (void)handle; }
static bool GENCPCLIENT_isSuccesfullyInitialized(void) { return transport_ready; }
static int titan_sensor_check(struct titan *priv) { (void)priv; return sensor_error; }
static const void *camera_common_find_pixelfmt(int format) { (void)format; return &data; }
static void titan_gencp_put(struct titan *priv) {
    assert(priv->gencp_initialized && titan_gencp_users);
    priv->gencp_initialized = false; titan_gencp_users--; cleanups++;
}
static int tegracam_v4l2subdev_register(struct tegracam_device *tc, bool sensor) {
    (void)tc; assert(sensor); return subdev_error;
}
static void device_create_file(struct device *dev, void *attr) { (void)dev; (void)attr; }
static int misc_register(struct miscdevice *misc) {
    assert(misc->fops == &titan_cdev_fops);
    assert(strcmp(misc->name, "titan-9-0030") == 0);
    if (!misc_error) chardevs++;
    return misc_error;
}
"""

PROBE_CASES = r"""
int main(void) {
    struct adapter adapter = {.nr = 9};
    struct i2c_client client = {.dev = {.of_node = &data}, .addr = 0x30, .adapter = &adapter};
    /* Real probe + fallback policy, failed camera check: chardev stays usable. */
    sensor_error = -EIO;
    assert(titan_probe(&client) == 0);
    assert(chardevs == 1 && titan_gencp_users == 1 && cleanups == 0);
    assert(registered_priv->gencp_initialized && registered_priv->misc_registered);
    assert(strcmp(registered_priv->pixel_format, "unverified") == 0);
    titan_gencp_put(registered_priv); free(registered_priv); free(allocated_tc);
    /* Strict failure must clean up without registering another chardev. */
    allow_probe_failure = false;
    assert(titan_probe(&client) == -EIO);
    assert(chardevs == 1 && titan_gencp_users == 0 && unregisters == 1);
    free(allocated_tc);
    /* Diagnostic mode must still reject resource/framework failures. */
    allow_probe_failure = true; transport_ready = false;
    assert(titan_probe(&client) == -ENOMEM);
    assert(chardevs == 1 && titan_gencp_users == 0);
    free(allocated_tc);
    transport_ready = true; subdev_error = -EINVAL;
    assert(titan_probe(&client) == -EINVAL);
    assert(chardevs == 1 && titan_gencp_users == 0);
    free(allocated_tc);
    subdev_error = 0; framework_error = -EINVAL;
    assert(titan_probe(&client) == -EINVAL);
    assert(chardevs == 1 && titan_gencp_users == 0);
    free(allocated_tc);
    framework_error = 0; allocation_failure = allocations + 1;
    assert(titan_probe(&client) == -ENOMEM);
    allocation_failure = allocations + 2;
    assert(titan_probe(&client) == -ENOMEM);
    client.dev.of_node = NULL;
    assert(titan_probe(&client) == -EINVAL);
    assert(chardevs == 1 && titan_gencp_users == 0);
    puts("Titan probe: diagnostic chardev, strict rejection and resource cleanup OK");
    return 0;
}
"""


class TitanTests(unittest.TestCase):
    def test_probe_diagnostic_registration(self):
        source = DRIVER.read_text()
        # Select one of the two kernel API signatures before extracting the function.
        start = source.index("#if defined(NV_I2C_DRIVER_STRUCT_PROBE_WITHOUT_I2C_DEVICE_ID_ARG)")
        body = source.index("\n{", start)
        probe = "static int titan_probe(struct i2c_client *client)" + source[body:]
        code = PROBE_SHIM + function(source, "titan_probe_sensor")
        code += function(probe, "titan_probe") + PROBE_CASES
        with tempfile.TemporaryDirectory(prefix="titan-probe-test-") as temp:
            path = Path(temp)
            (path / "probe.c").write_text(code)
            subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                            str(path / "probe.c"), "-o", str(path / "probe")], check=True)
            subprocess.run([str(path / "probe")], check=True)

    def test_driver_transactions(self):
        source = DRIVER.read_text()
        macros = "\n".join(re.findall(r"^#define (?:REG_|PIXEL_FORMAT_|TITAN_STR_MAX|TITAN_PROBE_RETRY_MS)[^\n]+", source, re.M))
        enum = re.search(r"enum \{.*?\n\};", source, re.S)[0]
        tables = source[source.index("static const int titan_60fps"):source.index("static int titan_find_frmfmt")]
        names = ["titan_find_frmfmt", "titan_gencp_status", "titan_read_register",
                 "titan_write_register", "titan_read_string", "titan_gencp_put",
                 "titan_pixfmt_to_reg", "titan_pixfmt_name", "titan_apply_pixel_format",
                 "titan_sensor_check", "titan_probe_sensor", "titan_start_streaming", "titan_stop_streaming"]
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
