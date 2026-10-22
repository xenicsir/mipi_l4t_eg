#!/usr/bin/env python3
"""Run real iLumos driver functions with simulated GenCP/basic I2C and framework."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import test_titan_driver as common

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'sources/common/source/nvidia-oot/drivers/media/i2c/ilumos_core.c'

BASIC_SHIM = r'''
typedef uint16_t __le16;
typedef uint32_t __le32;
#define cpu_to_le16(x) (x)
#define cpu_to_le32(x) (x)
#define le32_to_cpu(x) (x)
#define I2C_M_RD 1
struct i2c_adapter { int id; };
struct i2c_msg { uint16_t addr, flags, len; uint8_t *buf; };
static int basic_calls, basic_result = 2;
static uint16_t basic_status;
static bool basic_sensor_mode;
static uint32_t last_basic_reg, last_basic_value;
static uint16_t last_basic_length;
static int i2c_transfer(void *adapter, struct i2c_msg *msg, int count)
{
    (void)adapter; basic_calls++;
    assert(count == 2 && msg[0].addr == 0x30 && msg[1].addr == 0x30);
    assert(msg[0].flags == 0 && msg[1].flags == I2C_M_RD);
    last_basic_reg = msg[0].buf[0] | ((uint32_t)msg[0].buf[1] << 8) |
                     ((uint32_t)msg[0].buf[2] << 16) | ((uint32_t)msg[0].buf[3] << 24);
    last_basic_length = msg[0].buf[4] | ((uint16_t)msg[0].buf[5] << 8);
    assert(last_basic_length && !(last_basic_length % 4) && last_basic_length <= 256);
    assert(msg[0].len == 6 || msg[0].len == 10);
    if (basic_result != 2) return basic_result;
    memset(msg[1].buf, 0, msg[1].len);
    msg[1].buf[0] = basic_status & 0xff;
    msg[1].buf[1] = basic_status >> 8;
    if (msg[0].len == 6) {
        assert(msg[1].len == last_basic_length + 2);
        if (basic_sensor_mode && (last_basic_reg == 0x50000000 ||
                                  last_basic_reg == 0x50000004 ||
                                  last_basic_reg == 0x50000008)) {
            uint32_t value = last_basic_reg == 0x50000000 ? 1280 :
                             last_basic_reg == 0x50000004 ? 1024 : 0x01100007;
            memcpy(msg[1].buf + 2, &value, 4);
        } else if (last_basic_reg == 0x50000000) {
            const uint8_t value[] = {0x78, 0x56, 0x34, 0x12};
            memcpy(msg[1].buf + 2, value, 4);
        } else {
            memset(msg[1].buf + 2, 'L', last_basic_length);
        }
    } else {
        assert(last_basic_length == 4 && msg[1].len == 2);
        memcpy(&last_basic_value, msg[0].buf + 6, 4);
    }
    return 2;
}
'''


def protocol_enum(source):
    return re.search(r'enum ilumos_i2c_protocol \{.*?\n\};', source, re.S)[0]


def camera_shim():
    shim = ilumos(common.SHIM).replace('static bool allow_probe_failure = true;\n', '')
    shim = shim.replace('struct i2c_client { struct device dev; };',
                        'struct i2c_client { struct device dev; int addr; void *adapter; };')
    shim = shim.replace('struct unio_handle { int id; };', 'struct unio_handle { int id; };')
    shim = shim.replace('struct unio_handle io_handle;', 'struct unio_handle io_handle; enum ilumos_i2c_protocol i2c_protocol;')
    shim = shim.replace('static u16 fake_status;', 'static u16 fake_status; static int gencp_strings;')
    shim = shim.replace("assert(selected); last_reg = reg; memset(buf, 'A' + selected->id, len);",
                        "assert(selected); gencp_strings++; last_reg = reg; memset(buf, 'A' + selected->id, len);")
    return shim + BASIC_SHIM



def ilumos(text):
    text = text.replace('assert(titan_find_frmfmt(1280, 1024) == -1); /* superseded placeholder */',
                        'assert(titan_find_frmfmt(1279, 1024) == -1); /* unsupported width */')
    text = text.replace('1208', '1280')
    text = text.replace('TITAN', 'ILUMOS').replace('Titan', 'iLumos').replace('titan', 'ilumos')
    for old, new in [('0x500E0010', '0x50000008'), ('0x500E0000', '0x50000000'),
                     ('0x500E0004', '0x50000004'), ('0x500F000C', '0x50000A20'),
                     ('0x500F0000', '0x50000A00')]:
        text = text.replace(old, new)
    return text


def compile_run(code, extra_flags=()):
    with tempfile.TemporaryDirectory(prefix='ilumos-test-') as tmp:
        path = Path(tmp)
        (path / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', *extra_flags,
                        str(path / 'test.c'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


class IlumosTests(unittest.TestCase):
    def test_transactions_formats_probe_and_acquisition(self):
        source = DRIVER.read_text()
        shim = camera_shim()
        shim = shim.replace('assert(value == 1 || value == 0);', 'assert(value == 1 || value == 2);')
        shim = shim.replace('if (write) assert(value == 0);', 'if (write) assert(value == 2);')
        cases = ilumos(common.CASES).replace('.gencp_initialized = true}', '.gencp_initialized = true, .i2c_protocol = ILUMOS_I2C_GENCP}')
        start = cases.index('    /* No response must preserve')
        end = cases.index('    reads = writes = 0;', start)
        cases = cases[:start] + '''    u8 long_string[ILUMOS_STR_MAX];
    assert(ilumos_read_string(&cams[0], REG_MODEL_NAME_R, long_string, sizeof(long_string)) == 0);
    assert(long_string[255] == 'A');
''' + cases[end:]
        cases = cases.replace('assert(ilumos_find_frmfmt(1280, 1024) == 0);',
                              'assert(ilumos_find_frmfmt(1280, 1024) == 2);')
        cases = cases.replace('assert(data[0].def_mode == 0 && data[0].colorfmt->pix_fmt == V4L2_PIX_FMT_Y16_BE);',
                              'assert(data[0].def_mode == 2);')
        cases = cases.replace('def_mode == 0', 'def_mode == 2').replace('def_mode == 1', 'def_mode == 5')
        cases = cases.replace('sensor_mode_id == 1', 'sensor_mode_id == 5')
        cases = cases.replace('    assert(data[0].colorfmt->pix_fmt == V4L2_PIX_FMT_Y14);\n', '')
        cases = cases.replace('last_value == 0 && last_sleep', 'last_value == 2 && last_sleep')
        cases = cases.replace('struct i2c_client client = {0};',
                              'struct i2c_client client = {.addr = 0x30};')
        cases = cases.replace('    ilumos_gencp_users = 2;', r"""
    /* The entire sensor probe also works with a basic-protocol camera. */
    cams[1].i2c_protocol = ILUMOS_I2C_UNSELECTED;
    fake_status = 0x8003;
    basic_sensor_mode = true;
    int previous_gencp_strings = gencp_strings;
    assert(ilumos_sensor_check(&cams[1]) == 0);
    assert(cams[1].i2c_protocol == ILUMOS_I2C_BASIC);
    assert(gencp_strings == previous_gencp_strings + 1);
    assert(basic_calls == 7 && last_basic_reg == 0x50000A00 && last_basic_value == 2);
    assert(data[1].fmt_width == 1280 && data[1].fmt_height == 1024);
    basic_sensor_mode = false;
    ilumos_gencp_users = 2;""")
        macros = '\n'.join(re.findall(r'^#define (?:REG_|PIXEL_FORMAT_|ILUMOS_STR_MAX|ILUMOS_PROBE_RETRY_MS)[^\n]+', source, re.M))
        modes = re.search(r'enum \{.*?\n\};', source, re.S)[0]
        tables = source[source.index('static const int ilumos_60fps'):source.index('static int ilumos_find_frmfmt')]
        names = ['ilumos_find_frmfmt', 'ilumos_basic_status', 'ilumos_basic_read', 'ilumos_basic_write', 'ilumos_gencp_status', 'ilumos_read_register',
                 'ilumos_write_register', 'ilumos_read_string', 'ilumos_read_firmware', 'ilumos_gencp_put',
                 'ilumos_pixfmt_to_reg', 'ilumos_pixfmt_name', 'ilumos_apply_pixel_format',
                 'ilumos_sensor_check', 'ilumos_start_streaming', 'ilumos_stop_streaming']
        compile_run(macros + '\n' + protocol_enum(source) + shim + modes + tables + '\n'.join(common.function(source, n) for n in names) + cases)

    def test_protocol_selection_basic_frames_and_mixed_cameras(self):
        source = DRIVER.read_text()
        macros = '\n'.join(re.findall(r'^#define (?:REG_|PIXEL_FORMAT_|ILUMOS_STR_MAX)[^\n]+', source, re.M))
        names = ['ilumos_basic_status', 'ilumos_basic_read', 'ilumos_basic_write',
                 'ilumos_gencp_status', 'ilumos_read_register', 'ilumos_write_register',
                 'ilumos_read_string', 'ilumos_read_firmware', 'ilumos_gencp_put']
        cases = r"""
int main(void) {
    struct i2c_adapter adapter = {0};
    struct i2c_client client = {.addr = 0x30, .adapter = &adapter};
    struct ilumos cams[4] = {
        {.i2c_client = &client, .io_handle = {0}},
        {.i2c_client = &client, .io_handle = {1}},
        {.i2c_client = &client, .io_handle = {0}},
        {.i2c_client = &client, .io_handle = {1}}
    };
    u8 buf[257];
    u32 value = 0;
    (void)ilumos_gencp_lock; (void)ilumos_gencp_users;
    formats[0] = PIXEL_FORMAT_MONO16;
    assert(ilumos_read_register(&cams[0], REG_PIXEL_FORMAT, &value) == -EAGAIN);
    assert(ilumos_write_register(&cams[0], REG_PIXEL_FORMAT, 0) == -EAGAIN);
    assert(basic_calls == 0 && gencp_strings == 0);
    assert(ilumos_read_firmware(&cams[0], buf, 64) == 0);
    assert(cams[0].i2c_protocol == ILUMOS_I2C_GENCP);
    assert(gencp_strings == 1 && basic_calls == 0 && buf[0] == 'A');
    fake_status = 0x8003;
    assert(ilumos_read_register(&cams[0], REG_PIXEL_FORMAT, &value) == -EIO);
    assert(cams[0].i2c_protocol == ILUMOS_I2C_GENCP && basic_calls == 0);
    assert(ilumos_read_firmware(&cams[1], buf, 64) == 0);
    assert(cams[1].i2c_protocol == ILUMOS_I2C_BASIC && basic_calls == 1);
    assert(gencp_strings == 2 && buf[0] == 'L');
    fake_status = 0;
    assert(ilumos_read_firmware(&cams[1], buf, 64) == 0);
    assert(gencp_strings == 2 && basic_calls == 2);
    assert(ilumos_read_register(&cams[1], REG_IMG_WIDTH_R, &value) == 0);
    assert(last_basic_reg == 0x50000000 && last_basic_length == 4);
    assert(value == 0x12345678);
    assert(ilumos_write_register(&cams[1], 0x50000A00, 0x89abcdef) == 0);
    assert(last_basic_reg == 0x50000A00 && last_basic_value == 0x89abcdef);
    for (unsigned int len = 1; len <= 256; len++) {
        memset(buf, '!', sizeof(buf));
        assert(ilumos_read_string(&cams[1], 0x44, buf, len) == 0);
        assert(last_basic_length == ((len + 3) & ~3));
        assert(buf[0] == 'L' && buf[len - 1] == 'L' && buf[len] == '!');
    }
    int before = basic_calls;
    assert(ilumos_read_string(&cams[1], 0x44, buf, 0) == -EINVAL);
    assert(ilumos_read_string(&cams[1], 0x44, buf, 257) == -EINVAL);
    assert(basic_calls == before);
    basic_status = 0x8003; value = 0xdeadbeef;
    assert(ilumos_read_register(&cams[1], REG_IMG_WIDTH_R, &value) == -EIO);
    assert(value == 0xdeadbeef && cams[1].i2c_protocol == ILUMOS_I2C_BASIC);
    assert(ilumos_write_register(&cams[1], REG_PIXEL_FORMAT, 0) == -EIO);
    basic_status = 0xffff;
    assert(ilumos_read_string(&cams[1], 0x44, buf, 64) == -EBUSY);
    basic_status = 0;
    basic_result = 1;
    assert(ilumos_write_register(&cams[1], REG_PIXEL_FORMAT, 0) == -EIO);
    basic_result = -EREMOTEIO;
    assert(ilumos_read_string(&cams[1], 0x44, buf, 64) == -EREMOTEIO);
    assert(cams[1].i2c_protocol == ILUMOS_I2C_BASIC && gencp_strings == 2);
    /* Even if both first reads fail, subsequent attempts stay basic. */
    fake_status = 0x8003;
    assert(ilumos_read_firmware(&cams[2], buf, 64) == -EREMOTEIO);
    assert(cams[2].i2c_protocol == ILUMOS_I2C_BASIC && gencp_strings == 3);
    fake_status = 0; basic_result = 2;
    assert(ilumos_read_firmware(&cams[2], buf, 64) == 0);
    assert(gencp_strings == 3);
    before = basic_calls;
    fake_initialized = false;
    assert(ilumos_read_firmware(&cams[3], buf, 64) == -ENOMEM);
    assert(cams[3].i2c_protocol == ILUMOS_I2C_UNSELECTED && basic_calls == before);
    fake_initialized = true;
    /* Interleaving camera requests preserves each camera's selected mode. */
    assert(ilumos_read_register(&cams[0], REG_PIXEL_FORMAT, &value) == 0);
    assert(value == PIXEL_FORMAT_MONO16 && selected == &cams[0].io_handle);
    assert(ilumos_read_register(&cams[1], REG_IMG_WIDTH_R, &value) == 0);
    assert(value == 0x12345678 && cams[0].i2c_protocol == ILUMOS_I2C_GENCP);
    return 0;
}
"""
        code = macros + '\n' + protocol_enum(source) + camera_shim()
        code += '\n'.join(common.function(source, name) for name in names) + cases
        compile_run(code, ['-Wno-unused-function'])

    def test_chardev_lifetime_and_unbind(self):
        source = DRIVER.read_text()
        declarations = '\n'.join(re.search(r'struct ilumos_' + kind + r'_op\s*\{.*?\n\};', source, re.S)[0]
                                  for kind in ('reg', 'str'))
        macros = '\n'.join(re.findall(r'^#define ILUMOS_(?:STR_MAX|IOCTL_\w+)[^\n]*', source, re.M))
        shim = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <linux/types.h>
#define __user
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define copy_from_user(dst, src, n) (memcpy(dst, src, n), 0)
#define copy_to_user(dst, src, n) (memcpy(dst, src, n), 0)
struct inode { int unused; };
struct file { void *private_data; };
struct kref { int count; };
#define EG_IOCTL_GENCP_XFER 0xdead1001
#define EG_IOCTL_GENCP_STATS 0xdead1002
#define ILUMOS_I2C_GENCP 1
struct ilumos { int miscdev; bool gencp_initialized; struct kref refcount; int i2c_protocol; int io_handle; };
static int GENCPCLIENT_UserExchange(int *handle, unsigned long arg) { (void)handle; (void)arg; return 0; }
static int GENCPCLIENT_UserStats(int *handle, unsigned long arg) { (void)handle; (void)arg; return 0; }
static int ilumos_gencp_lock, reads;
static bool freed;
static void kref_get(struct kref *ref) { ref->count++; }
static void ilumos_free(struct kref *ref) { (void)ref; freed = true; }
static void kref_put(struct kref *ref, void (*release)(struct kref *)) {
    assert(ref->count > 0); if (!--ref->count) release(ref);
}
static int ilumos_read_register(struct ilumos *cam, uint32_t reg, uint32_t *value) {
    assert(cam->gencp_initialized); (void)reg; reads++; *value = 0x12345678; return 0;
}
static int ilumos_write_register(struct ilumos *cam, uint32_t reg, uint32_t value) {
    assert(cam->gencp_initialized); (void)reg; (void)value; return -EIO;
}
static int ilumos_read_string(struct ilumos *cam, uint32_t reg, uint8_t *buf, uint16_t len) {
    assert(cam->gencp_initialized); (void)reg; memset(buf, 'X', len); return 0;
}
"""
        cases = r"""
int main(void) {
    struct ilumos cam = {.gencp_initialized = true, .refcount = {1}};
    struct file file = {.private_data = &cam.miscdev};
    struct ilumos_reg_op reg = {.addr = 0x50000000};
    struct ilumos_str_op str = {.addr = 0x44, .len = 256};
    assert(ilumos_cdev_open(NULL, &file) == 0);
    assert(file.private_data == &cam && cam.refcount.count == 2);
    assert(ilumos_cdev_ioctl(&file, ILUMOS_IOCTL_READ_REG, (unsigned long)&reg) == 0);
    assert(reg.val == 0x12345678 && reads == 1);
    assert(ilumos_cdev_ioctl(&file, EG_IOCTL_GENCP_XFER, 0) == -EOPNOTSUPP);
    cam.i2c_protocol = ILUMOS_I2C_GENCP;
    assert(ilumos_cdev_ioctl(&file, EG_IOCTL_GENCP_XFER, 0) == 0);
    assert(ilumos_cdev_ioctl(&file, EG_IOCTL_GENCP_STATS, 0) == 0);
    assert(ilumos_cdev_ioctl(&file, ILUMOS_IOCTL_WRITE_REG, (unsigned long)&reg) == -EIO);
    assert(ilumos_cdev_ioctl(&file, ILUMOS_IOCTL_READ_STR, (unsigned long)&str) == 0);
    assert(str.buf[255] == 'X');
    str.len = 257;
    assert(ilumos_cdev_ioctl(&file, ILUMOS_IOCTL_READ_STR, (unsigned long)&str) == -EINVAL);
    assert(ilumos_cdev_ioctl(&file, 0, (unsigned long)&reg) == -ENOTTY);
    /* The binding releases its reference; an open fd still keeps priv alive. */
    cam.gencp_initialized = false;
    kref_put(&cam.refcount, ilumos_free);
    assert(cam.refcount.count == 1 && !freed);
    assert(ilumos_cdev_ioctl(&file, ILUMOS_IOCTL_READ_REG, (unsigned long)&reg) == -ENODEV);
    assert(reads == 1);
    assert(ilumos_cdev_release(NULL, &file) == 0);
    assert(cam.refcount.count == 0 && freed);
    file.private_data = &cam.miscdev;
    assert(ilumos_cdev_open(NULL, &file) == -ENODEV);
    return 0;
}
"""
        code = shim + macros + '\n' + declarations + '\n'
        code += '\n'.join(common.function(source, name) for name in
                          ['ilumos_cdev_open', 'ilumos_cdev_release', 'ilumos_cdev_ioctl'])
        # Kernel callbacks have intentionally unused arguments.
        with tempfile.TemporaryDirectory(prefix='ilumos-cdev-test-') as tmp:
            path = Path(tmp)
            (path / 'test.c').write_text(code + cases)
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-Wno-unused-parameter', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True)

    def test_strict_probe_registration_and_cleanup(self):
        source = DRIVER.read_text()
        shim = ilumos(common.PROBE_SHIM)
        shim = shim.replace('static bool allow_probe_failure = true, transport_ready = true;', '')
        shim = shim.replace('static void GENCPCLIENT_Init(void *handle) { (void)handle; }\n', '')
        shim = shim.replace('static bool GENCPCLIENT_isSuccesfullyInitialized(void) { return transport_ready; }\n', '')
        shim = shim.replace('static const void *camera_common_find_pixelfmt(int format) { (void)format; return &data; }\n', '')
        start = source.index('#if defined(NV_I2C_DRIVER_STRUCT_PROBE_WITHOUT_I2C_DEVICE_ID_ARG)')
        body = source.index('\n{', start)
        probe = 'static int ilumos_probe(struct i2c_client *client)' + source[body:]
        cases = r'''
int main(void) {
    struct adapter adapter = {.nr = 9};
    struct i2c_client client = {.dev = {.of_node = &data}, .addr = 0x30, .adapter = &adapter};
    sensor_error = -EIO;
    assert(ilumos_probe(&client) == -EIO);
    assert(chardevs == 0 && ilumos_gencp_users == 0 && cleanups == 1);
    free(allocated_tc);
    sensor_error = 0;
    assert(ilumos_probe(&client) == 0);
    assert(chardevs == 1 && ilumos_gencp_users == 1 && registered_priv->misc_registered);
    ilumos_gencp_put(registered_priv); free(registered_priv); free(allocated_tc);
    subdev_error = -EINVAL;
    assert(ilumos_probe(&client) == -EINVAL);
    assert(ilumos_gencp_users == 0 && cleanups == 3);
    free(allocated_tc);
    subdev_error = 0; framework_error = -EINVAL;
    assert(ilumos_probe(&client) == -EINVAL);
    assert(ilumos_gencp_users == 0);
    free(allocated_tc);
    framework_error = 0; allocation_failure = allocations + 1;
    assert(ilumos_probe(&client) == -ENOMEM);
    allocation_failure = allocations + 2;
    assert(ilumos_probe(&client) == -ENOMEM);
    assert(chardevs == 1 && ilumos_gencp_users == 0);
    puts("iLumos probe: strict sensor checks, registration and cleanup OK");
    return 0;
}
'''
        compile_run(shim + common.function(probe, 'ilumos_probe') + cases)


if __name__ == '__main__':
    unittest.main()
