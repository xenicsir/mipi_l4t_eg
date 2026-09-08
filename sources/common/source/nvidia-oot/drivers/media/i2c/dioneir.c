/*
 * dione_ir.c - Dione IR sensor driver
 *
 * Copyright (c) 2021-2023, Xenics Infrared Solutions.  All rights reserved.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms and conditions of the GNU General Public License,
 * version 2, as published by the Free Software Foundation.
 *
 * This program is distributed in the hope it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
 * more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

//#define DEBUG

#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/gpio.h>
#include <linux/module.h>
#include <linux/seq_file.h>
#include <linux/of.h>
#include <linux/of_graph.h>
#include <linux/of_device.h>
#include <linux/of_gpio.h>

#include <media/tegra_v4l2_camera.h>
#include <media/tegracam_core.h>

#include "../platform/tegra/camera/camera_gpio.h"

#include "tc358746_regs.h"
#include "tc358746_calculation.h"

/*
 * gpio_cansleep() (legacy integer GPIO API) a été retiré du kernel en 6.x.
 * gpiod_cansleep()+gpio_to_desc() existent de 4.9 à 6.8 -> on garde les deux branches
 * pour que ce driver commun compile sur toutes les versions L4T (cf runbook §7.14).
 */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 0, 0)
#define EG_GPIO_CANSLEEP(g)	gpiod_cansleep(gpio_to_desc(g))
#else
#define EG_GPIO_CANSLEEP(g)	gpio_cansleep(g)
#endif

/* Bring-up aid: dumps every tc358746_calculate() input and result, plus each
 * bridge register write. Uncomment when bringing up a new format or link rate --
 * the link frequency and the video buffer size are both derived from bpp, and
 * that trace is the only place they are visible. */
//#define DBG_TC358746

#define MAX_I2C_CLIENTS_NUMBER 128

#define DIONE_IR_REG_WIDTH_MAX      0x0002f028
#define DIONE_IR_REG_HEIGHT_MAX     0x0002f02c
#define DIONE_IR_REG_MODEL_NAME     0x00000044
#define DIONE_IR_REG_FIRMWARE_VERSION  0x2000e000
#define DIONE_IR_REG_SERIAL_NUMBER      0x00000144
#define DIONE_IR_REG_ACQUISITION_STOP  0x00080104
#define DIONE_IR_REG_ACQUISITION_SRC   0x00080108
#define DIONE_IR_REG_ACQUISITION_STAT  0x0008010c
#define DIONE_IR_REG_PIXEL_FORMAT      0x00080194

/*
 * GenICam PixelFormat values the camera accepts. "Mono16" is a misnomer kept
 * from the vendor documentation: the camera only ever emits 14 significant
 * bits -- Y0 and Y1 never leave it, measured. See dione_mono_in_rgb_encoding.
 */
/* The two PixelFormat values the driver recognises. It never WRITES this
 * register -- the user sets the camera's output format by other means
 * (dioneCtrl.py) -- it only reads it once at probe to decide what to offer
 * userspace. */
#define DIONE_IR_PIXFMT_RGB8    0x02180014
#define DIONE_IR_PIXFMT_MONO16  0x01100007



/*
 * Status 0xFFFF means "packet being processed" -- read the answer again.
 *
 * Documented in the Dione family manual ENG-2021-UMN008 **R013** (the R0010 we
 * had before does not mention it): "While a request is being processed, the
 * status field in the output buffer will read 0xFFFF. Only a single in-flight
 * request at a time is supported. Sending a new request while the current
 * request is still being processed will result in undefined behaviour."
 *
 * ⚠️ So the retry is a RE-READ, never a re-sent request. The manual's own
 * example does exactly that: one write, then r6 answering 0xffff, then a second
 * r6 answering 0x0000 plus the value.
 *
 * This driver used to issue the request and the answer as ONE combined I2C
 * transfer (write, repeated START, read), which gives the camera no time at
 * all. Older firmware tolerated it; the Dione 320 firmware
 * FPGA 3.2.797 / ESW 18.255.72839-25 returns 0xFFFF, the status check rejected
 * it, and detect_dione_ir() ended with "no fpga found" on a healthy camera.
 *
 * Measured on that camera 2026-09-08: one to two re-reads are always enough.
 * dioneCtrl.py had already been taught to poll; the driver had not.
 */
#define DIONE_IR_STATUS_BUSY      0xFFFF

/*
 * ⚠️ Issue the request, WAIT, then read. Never glue the read to the request.
 *
 * This deliberately departs from the manual's own example, and the reason is
 * measured, not guessed.
 *
 * ENG-2021-UMN008 R013 section 2.8 documents status 0xFFFF ("packet being
 * processed") and shows a combined write+read followed by a bare re-read:
 *
 *      i2ctransfer -y -f 6 w6@0x5A 0x04 0xF0 0x02 0x00 0x04 0x00 r6
 *      >> 0xff 0xff ...                      (0xFFFF, in progress)
 *      i2ctransfer -y -f 6 r6@0x5A
 *      >> 0x00 0x00 0x53 0x05 0x0b 0x40      (success)
 *
 * That sequence is NOT reliable on a Dione 320 with firmware
 * FPGA 3.2.797 / ESW 18.255.72839-25. Measured 2026-09-08, reading WidthMax
 * twenty times in a row: 7 of 20 failed, in two shapes --
 *
 *   status 0x00FF                    the status field caught mid-update -- it
 *                                    clears high byte first, 0xFFFF -> 0x00FF
 *                                    -> 0x0000. 0x00FF is in no manual.
 *   torn payload                     the DATA is written while being read too:
 *                                    0x00000100 (256) instead of 0x00000140
 *                                    (320) on three glued reads out of nine
 *   status 0xFFFF, payload zeroed    never completes, not after 20 re-reads
 *                                    50 ms apart
 *
 * ⚠️ A glued read sometimes carries the RIGHT value with a not-ready status. So
 * the payload must be discarded until the status is exactly 0x0000 -- trusting
 * a plausible-looking value is right two times in three and silently wrong the
 * third.
 *
 * And nothing repairs it afterwards: re-reading (13/32 failures), spacing the
 * accesses 100 ms apart (8/32), or reopening /dev/i2c per access (18/32) all
 * still fail. Only not reading too early works: request, wait 50 ms, read
 * once -- 0/32 failures, and the answer is always ready on the first read, so
 * the polling loop below is a safety net rather than the mechanism.
 *
 * The camera reached us undetected because of this: detect_dione_ir() read
 * WidthMax, got 0xFFFF, and the probe ended with "no fpga found".
 *
 * Harmless on older firmware: a Dione 640 (FPGA 3.2.836 / ESW 16.5.65496)
 * never returns 0xFFFF at all -- 40/40 reads succeed immediately, the wait
 * simply costs 50 us of sleep it does not need.
 *
 * 50 ms and 10 attempts are dioneCtrl.py's POLL_INTERVAL / POLL_ATTEMPTS. That
 * script sleeps before its first read too, which is exactly why it never saw
 * any of this. Keep the two in step.
 */
#define DIONE_IR_READ_WAIT_US     50000
#define DIONE_IR_READ_POLLS       10
#define DIONE_IR_READ_TRIES       3
// #define DIONE_IR_STARTUP_TMO_MS     1500
// #define DIONE_IR_HAS_SYSFS_RESTART_MIPI

#define CSI_HSTXVREGCNT       5

/* Hand the bridge over to userspace. With this set, set_mode() computes and
 * selects the device-tree mode as usual but writes NOTHING to the TC358746 --
 * the caller must configure it beforehand, e.g. with tc358746_configure.py.
 * Used to validate that standalone script against the driver end to end. */
static int skip_bridge_cfg = 0;

static int test_mode = 0;
static int quick_mode = 1;
static int link_frequency = 0;
module_param(skip_bridge_cfg, int, 0644);
module_param(test_mode, int, 0644);
module_param(quick_mode, int, 0644);
module_param(link_frequency, int, 0644);

int dione_ir_chnod_open (struct inode * pInode, struct file * file);
int dione_ir_chnod_release (struct inode * pInode, struct file * file);

/*
 * Mode indices, in the order the device tree declares them. The RGB888 block
 * must stay first: dione_ir_find_frmfmt() matches on resolution only and
 * returns the first hit, which is what the probe stores as the detected
 * variant.
 *
 * Y14 is the same sensor data carried differently: the camera's pseudo-mono
 * output puts its 14 significant bits on the bridge's PD[13:0], which is
 * exactly the RAW14 pin usage, so the bridge packs them as CSI-2 RAW14
 * (dt 0x2D) instead of RGB888. See memory note dione_mono_in_rgb_encoding.
 *
 * Not declared on L4T 32.x platforms (Nano/t210, TX2/t186): their VI format
 * tables have no 14-bit greyscale entry at all. eg_config.yaml's
 * platform_restrictions carries that exclusion.
 */
/*
 * Number of RGB888 modes, which is also the index of the first Y14 mode: the
 * device tree declares the RGB888 modes first and the Y14 ones last, in this
 * same order. Keep in step if a resolution is added.
 */
#define DIONE_IR_NUM_RGB888_MODES  4

enum {
   DIONE_IR_MODE_640x480_60FPS_RGB888,
   DIONE_IR_MODE_1280x1024_60FPS_RGB888,
   DIONE_IR_MODE_320x240_60FPS_RGB888,
   DIONE_IR_MODE_1024x768_60FPS_RGB888,
   DIONE_IR_MODE_640x480_60FPS_Y14,
   DIONE_IR_MODE_1280x1024_60FPS_Y14,
   DIONE_IR_MODE_320x240_60FPS_Y14,
   DIONE_IR_MODE_1024x768_60FPS_Y14,
};
struct dione_ir_i2c_client {
   struct i2c_client *i2c_client;
   struct i2c_adapter *root_adap;
   char chnod_name[128];
   int i2c_locked ;
   int chnod_major_number;
   dev_t chnod_device_number;
   struct class *pClass_chnod;
};

struct dione_ir_i2c_client i2c_clients[MAX_I2C_CLIENTS_NUMBER];

static const int dione_ir_60fps[] = {
   60,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
static const struct camera_common_frmfmt dione_ir_frmfmt[] = {
   {{640, 480},   dione_ir_60fps, 1, 0, DIONE_IR_MODE_640x480_60FPS_RGB888},
   {{1280, 1024}, dione_ir_60fps, 1, 0, DIONE_IR_MODE_1280x1024_60FPS_RGB888},
   {{320, 240},   dione_ir_60fps, 1, 0, DIONE_IR_MODE_320x240_60FPS_RGB888},
   {{1024, 768},  dione_ir_60fps, 1, 0, DIONE_IR_MODE_1024x768_60FPS_RGB888},
   {{640, 480},   dione_ir_60fps, 1, 0, DIONE_IR_MODE_640x480_60FPS_Y14},
   {{1280, 1024}, dione_ir_60fps, 1, 0, DIONE_IR_MODE_1280x1024_60FPS_Y14},
   {{320, 240},   dione_ir_60fps, 1, 0, DIONE_IR_MODE_320x240_60FPS_Y14},
   {{1024, 768},  dione_ir_60fps, 1, 0, DIONE_IR_MODE_1024x768_60FPS_Y14},
   /* Add modes with no device tree support after below */
};

static int dione_ir_find_frmfmt(u32 width, u32 height)
{
   u32 i;

   for (i = 0; i < ARRAY_SIZE(dione_ir_frmfmt); i++) {
      const struct camera_common_frmfmt *fmt = dione_ir_frmfmt + i;

      if (fmt->size.width == width && fmt->size.height == height)
         return i;
   }

   return -1;
}

static const struct regmap_range ctl_regmap_rw_ranges[] = {
   regmap_reg_range(0x0000, 0x00ff),
};

static const struct regmap_access_table ctl_regmap_access = {
   .yes_ranges = ctl_regmap_rw_ranges,
   .n_yes_ranges = ARRAY_SIZE(ctl_regmap_rw_ranges),
};

static const struct regmap_config ctl_regmap_config = {
   .reg_bits = 16,
   .reg_stride = 2,
   .val_bits = 16,
   .cache_type = REGCACHE_NONE,
   .max_register = 0x00ff,
   .reg_format_endian = REGMAP_ENDIAN_BIG,
   .val_format_endian = REGMAP_ENDIAN_BIG,
   .rd_table = &ctl_regmap_access,
   .wr_table = &ctl_regmap_access,
   .name = "tc358746-ctl",
};

static const struct regmap_range tx_regmap_rw_ranges[] = {
   regmap_reg_range(0x0100, 0x05ff),
};

static const struct regmap_access_table tx_regmap_access = {
   .yes_ranges = tx_regmap_rw_ranges,
   .n_yes_ranges = ARRAY_SIZE(tx_regmap_rw_ranges),
};

static const struct regmap_config tx_regmap_config = {
   .reg_bits = 16,
   .reg_stride = 4,
   .val_bits = 32,
   .cache_type = REGCACHE_NONE,
   .max_register = 0x05ff,
   .reg_format_endian = REGMAP_ENDIAN_BIG,
   .val_format_endian = REGMAP_ENDIAN_NATIVE,
   .rd_table = &tx_regmap_access,
   .wr_table = &tx_regmap_access,
   .name = "tc358746-tx",
};

static const struct of_device_id dione_ir_of_match[] = {
   { .compatible = "xenics,dioneir", },
   { .compatible = "exosens,dioneir", },
   { },
};
MODULE_DEVICE_TABLE(of, dione_ir_of_match);

static const u32 ctrl_cid_list[] = {
   TEGRA_CAMERA_CID_GAIN,
   TEGRA_CAMERA_CID_EXPOSURE,
   TEGRA_CAMERA_CID_FRAME_RATE,
   TEGRA_CAMERA_CID_SENSOR_MODE_ID,
};

struct dione_ir {
   struct i2c_client    *tc35_client;
   struct i2c_client    *fpga_client;
   struct v4l2_subdev      *subdev;
   struct regmap        *tx_regmap;
   struct camera_common_data  *s_data;
   struct tegracam_device     *tc_dev;

   int            quick_mode;
#ifdef DIONE_IR_STARTUP_TMO_MS
   ktime_t           start_up;
#endif
   bool           tc35_found;
   bool           fpga_found;
   bool           reva;
   int            mode;

   u32            *fpga_address;
   unsigned int         fpga_address_num;
   u32            cam_pixfmt;        /* PixelFormat read once at probe */

   u64            *link_frequencies;
   unsigned int         link_frequencies_num;

   char           model[64];
   char           serial_number[64];
   char           firmware_version[64];
   u32            native_width;
   u32            native_height;
};

static int dione_ir_i2c_read(struct i2c_client *client, u32 addr, u8 *buf, u16 len);
static int dione_ir_i2c_write32(struct i2c_client *client, u32 addr, u32 val);

static void dione_ir_regmap_format_32_ble(void *buf, unsigned int val)
{
   u8 *b = buf;
   int val_after;

   b[0] = val >> 8;
   b[1] = val;
   b[2] = val >> 24;
   b[3] = val >> 16;
   val_after = *(int*)buf;
}

static inline int dione_ir_read_reg(struct camera_common_data *s_data,
      u16 addr, u8 *val)
{
   int err = 0;
   u32 reg_val = 0;

   err = regmap_read(s_data->regmap, addr, &reg_val);
   *val = reg_val & 0xff;

   return err;
}

static inline int dione_ir_write_reg(struct camera_common_data *s_data,
      u16 addr, u8 val)
{
   int err = 0;

   err = regmap_write(s_data->regmap, addr, val);
   if (err)
      dev_err(s_data->dev, "%s: i2c write failed %#x = %#x\n",
            __func__, addr, val);

   return err;
}

static int dione_ir_set_group_hold(struct tegracam_device *tc_dev, bool val)
{
   dev_dbg(tc_dev->dev, "%s val=%d\n", __func__, val);
   return 0;
}

static int dione_ir_set_gain(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int dione_ir_set_frame_rate(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int dione_ir_set_exposure(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static struct tegracam_ctrl_ops dione_ir_ctrl_ops = {
   .numctrls = ARRAY_SIZE(ctrl_cid_list),
   .ctrl_cid_list = ctrl_cid_list,
   .set_gain = dione_ir_set_gain,
   .set_exposure = dione_ir_set_exposure,
   .set_frame_rate = dione_ir_set_frame_rate,
   .set_group_hold = dione_ir_set_group_hold,
};

static int dione_ir_power_on(struct camera_common_data *s_data)
{
   int err = 0;
   struct camera_common_power_rail *pw = s_data->power;
   struct camera_common_pdata *pdata = s_data->pdata;
   struct device *dev = s_data->dev;
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;
   bool reset = !priv->reva;

   dev_dbg(dev, "%s: power on\n", __func__);
   if (pdata && pdata->power_on) {
      err = pdata->power_on(pw);
      if (err)
         dev_err(dev, "%s failed.\n", __func__);
      else
         pw->state = SWITCH_ON;
      return err;
   }

   if (!priv->quick_mode) {
      if (pw->reset_gpio) {
         dev_info(dev, "%s camera power off.\n", __func__);
         if (EG_GPIO_CANSLEEP(pw->reset_gpio))
         {
            gpio_set_value_cansleep(pw->reset_gpio, reset);
         }
         else
         {
            gpio_set_value(pw->reset_gpio, reset);
         }
      }

      if (unlikely(!(pw->avdd || pw->iovdd || pw->dvdd)))
         goto skip_power_seqn;

      usleep_range(10, 20);

      if (pw->avdd) {
         err = regulator_enable(pw->avdd);
         if (err)
            goto dione_ir_avdd_fail;
      }

      if (pw->iovdd) {
         err = regulator_enable(pw->iovdd);
         if (err)
            goto dione_ir_iovdd_fail;
      }

      if (pw->dvdd) {
         err = regulator_enable(pw->dvdd);
         if (err)
            goto dione_ir_dvdd_fail;
      }

      usleep_range(10, 20);

skip_power_seqn:
      if (pw->reset_gpio) {
         dev_info(dev, "%s camera power on.\n", __func__);
         if (EG_GPIO_CANSLEEP(pw->reset_gpio))
            gpio_set_value_cansleep(pw->reset_gpio, !reset);
         else
            gpio_set_value(pw->reset_gpio, !reset);
      }

      usleep_range(23000, 23100);
      msleep(200);
   }

   pw->state = SWITCH_ON;

   return 0;

dione_ir_dvdd_fail:
   regulator_disable(pw->iovdd);

dione_ir_iovdd_fail:
   regulator_disable(pw->avdd);

dione_ir_avdd_fail:
   dev_err(dev, "%s failed: %d\n", __func__, err);

   return err;

   // return 0;
}

static int dione_ir_power_off(struct camera_common_data *s_data)
{
   int err = 0;
   struct camera_common_power_rail *pw = s_data->power;
   struct camera_common_pdata *pdata = s_data->pdata;
   struct device *dev = s_data->dev;
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;
   bool reset = !priv->reva;

   dev_dbg(dev, "%s: power off\n", __func__);

   if (pdata && pdata->power_off) {
      err = pdata->power_off(pw);
      if (err) {
         dev_err(dev, "%s failed\n", __func__);
         return err;
      }
   } else {
      if (!priv->quick_mode) {
         if (pw->reset_gpio) {
            dev_info(dev, "%s camera power off.\n", __func__);
            if (EG_GPIO_CANSLEEP(pw->reset_gpio))
               gpio_set_value_cansleep(pw->reset_gpio, reset);
            else
               gpio_set_value(pw->reset_gpio, reset);
         }

         usleep_range(10, 10);

         if (pw->dvdd)
            regulator_disable(pw->dvdd);
         if (pw->iovdd)
            regulator_disable(pw->iovdd);
         if (pw->avdd)
            regulator_disable(pw->avdd);
      }
   }

   pw->state = SWITCH_OFF;

   return 0;
}

static int dione_ir_power_put(struct tegracam_device *tc_dev)
{
   struct camera_common_data *s_data = tc_dev->s_data;
   struct camera_common_power_rail *pw = s_data->power;
   struct dione_ir *priv = (struct dione_ir *)tegracam_get_privdata(tc_dev);

   if (unlikely(!pw))
      return -EFAULT;

   /* really power off module when removing the driver */
   priv->quick_mode = 0;

   s_data->ops->power_off(s_data);

   if (likely(pw->dvdd))
      devm_regulator_put(pw->dvdd);

   if (likely(pw->avdd))
      devm_regulator_put(pw->avdd);

   if (likely(pw->iovdd))
      devm_regulator_put(pw->iovdd);

   pw->dvdd = NULL;
   pw->avdd = NULL;
   pw->iovdd = NULL;

   if (likely(pw->reset_gpio))
      gpio_free(pw->reset_gpio);

   if (priv->fpga_client != NULL) {
      i2c_unregister_device(priv->fpga_client);
      priv->fpga_client = NULL;
   }

   return 0;
}

static int dione_ir_power_get(struct tegracam_device *tc_dev)
{
   struct device *dev = tc_dev->dev;
   struct camera_common_data *s_data = tc_dev->s_data;
   struct camera_common_power_rail *pw = s_data->power;
   struct camera_common_pdata *pdata = s_data->pdata;
   struct clk *parent;
   int err = 0;

   if (!pdata) {
      dev_err(dev, "pdata missing\n");
      return -EFAULT;
   }

   /* Sensor MCLK (aka. INCK) */
   if (pdata->mclk_name) {
      pw->mclk = devm_clk_get(dev, pdata->mclk_name);
      if (IS_ERR(pw->mclk)) {
         dev_err(dev, "unable to get clock %s\n",
               pdata->mclk_name);
         return PTR_ERR(pw->mclk);
      }

      if (pdata->parentclk_name) {
         parent = devm_clk_get(dev, pdata->parentclk_name);
         if (IS_ERR(parent)) {
            dev_err(dev, "unable to get parent clock %s\n",
                  pdata->parentclk_name);
         } else
            clk_set_parent(pw->mclk, parent);
      }
   }

   /* analog 2.8v */
   if (pdata->regulators.avdd)
      err |= camera_common_regulator_get(dev,
            &pw->avdd, pdata->regulators.avdd);
   /* IO 1.8v */
   if (pdata->regulators.iovdd)
      err |= camera_common_regulator_get(dev,
            &pw->iovdd, pdata->regulators.iovdd);
   /* dig 1.2v */
   if (pdata->regulators.dvdd)
      err |= camera_common_regulator_get(dev,
            &pw->dvdd, pdata->regulators.dvdd);
   if (err) {
      dev_err(dev, "%s: unable to get regulator(s)\n", __func__);
      goto done;
   }

   /* Reset or ENABLE GPIO */
   pw->reset_gpio = pdata->reset_gpio;
   if (pw->reset_gpio)
   {
      err = gpio_request(pw->reset_gpio, "cam_reset_gpio");
      if (err < 0) {
         dev_err(dev, "%s: unable to request reset_gpio (%d)\n",
               __func__, err);
         goto done;
      }
   }

done:
   pw->state = SWITCH_OFF;

   return err;

   // return 0;
}

static struct camera_common_pdata *dione_ir_parse_dt(
      struct tegracam_device *tc_dev)
{
   struct device *dev = tc_dev->dev;
   struct device_node *np = dev->of_node;
   struct camera_common_pdata *board_priv_pdata;
   const struct of_device_id *match;
   struct camera_common_pdata *ret = NULL;
   int err = 0;
   int gpio;

   if (!np)
      return NULL;

   match = of_match_device(dione_ir_of_match, dev);
   if (!match) {
      dev_err(dev, "Failed to find matching dt id\n");
      return NULL;
   }

   board_priv_pdata = devm_kzalloc(dev, sizeof(*board_priv_pdata),
         GFP_KERNEL);
   if (!board_priv_pdata)
      return NULL;

   gpio = of_get_named_gpio(np, "reset-gpios", 0);
   if (gpio < 0) {
      board_priv_pdata->reset_gpio = 0;
   }
   else
   {
      board_priv_pdata->reset_gpio = gpio;
   }

   err = of_property_read_string(np, "mclk", &board_priv_pdata->mclk_name);
   if (err)
      dev_dbg(dev, "mclk name not present, "
            "assume sensor driven externally\n");

   err = of_property_read_string(np, "avdd-reg",
         &board_priv_pdata->regulators.avdd);
   err |= of_property_read_string(np, "iovdd-reg",
         &board_priv_pdata->regulators.iovdd);
   err |= of_property_read_string(np, "dvdd-reg",
         &board_priv_pdata->regulators.dvdd);
   if (err)
      dev_dbg(dev, "avdd, iovdd and/or dvdd reglrs. not present, "
            "assume sensor powered independently\n");

   board_priv_pdata->has_eeprom =
      of_property_read_bool(np, "has-eeprom");

   return board_priv_pdata;

   // error:
   // devm_kfree(dev, board_priv_pdata);

   return ret;
}

static inline int tc358746_sleep_mode(struct regmap *regmap, int enable)
{

   int bit = enable ? SYSCTL_SLEEP_MASK : 0;
   int err = regmap_update_bits(regmap, SYSCTL, SYSCTL_SLEEP_MASK,
         bit);

#ifdef DBG_TC358746
   printk("tc358746 write bits @0x%02x : mask 0x%lX, value = 0x%X\n", SYSCTL, SYSCTL_SLEEP_MASK, bit);
#endif

   return err;
}

static inline int tc358746_sreset(struct regmap *regmap)
{
   int err;

   err = regmap_write(regmap, SYSCTL, SYSCTL_SRESET_MASK);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%lX\n", SYSCTL, SYSCTL_SRESET_MASK);
#endif

   udelay(10);

   if (!err)
   {
      err = regmap_write(regmap, SYSCTL, 0);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", SYSCTL, 0);
#endif
   }

   return err;
}

static int tc358746_set_pll(struct regmap *regmap,
      const struct tc358746_pll *pll,
      const struct tc358746_csi *csi)
{
   u32 pllctl0, pllctl1, pllctl0_new;
   int err;

   err = regmap_read(regmap, PLLCTL0, &pllctl0);
   if (!err)
      err = regmap_read(regmap, PLLCTL1, &pllctl1);

   if (err)
      return err;

   pllctl0_new = PLLCTL0_PLL_PRD_SET(pll->pll_prd) |
      PLLCTL0_PLL_FBD_SET(pll->pll_fbd);

   /*
    * Only rewrite when needed (new value or disabled), since rewriting
    * triggers another format change event.
    */
   if (pllctl0 != pllctl0_new || (pllctl1 & PLLCTL1_PLL_EN_MASK) == 0) {
      u16 pllctl1_mask = PLLCTL1_PLL_FRS_MASK | PLLCTL1_RESETB_MASK |
         PLLCTL1_PLL_EN_MASK;
      u16 pllctl1_val = PLLCTL1_PLL_FRS_SET(csi->speed_range) |
         PLLCTL1_RESETB_MASK | PLLCTL1_PLL_EN_MASK;

      err = regmap_write(regmap, PLLCTL0, pllctl0_new);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", PLLCTL0, pllctl0_new);
#endif
      if (!err)
      {
         err = regmap_update_bits(regmap, PLLCTL1,
               pllctl1_mask, pllctl1_val);
#ifdef DBG_TC358746
         printk("tc358746 write bits @0x%X : mask 0x%X, value = 0x%X\n", PLLCTL1, pllctl1_mask, pllctl1_val);
#endif
      }

      udelay(1000);

      if (!err)
      {
         err = regmap_update_bits(regmap, PLLCTL1,
               PLLCTL1_CKEN_MASK,
               PLLCTL1_CKEN_MASK);
#ifdef DBG_TC358746
         printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%lX\n", PLLCTL1, PLLCTL1_CKEN_MASK, PLLCTL1_CKEN_MASK);
#endif
      }
   }

   return err;
}

static int tc358746_set_csi_color_space(struct regmap *regmap,
      const struct tc358746_mbus_fmt *format)
{
   int err;

   err = regmap_update_bits(regmap, DATAFMT,
         (DATAFMT_PDFMT_MASK | DATAFMT_UDT_EN_MASK),
         DATAFMT_PDFMT_SET(format->pdformat));
#ifdef DBG_TC358746
   printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%lX\n", DATAFMT, (DATAFMT_PDFMT_MASK | DATAFMT_UDT_EN_MASK), DATAFMT_PDFMT_SET(format->pdformat));
#endif

   if (!err)
   {
      err = regmap_update_bits(regmap, CONFCTL, CONFCTL_PDATAF_MASK,
            CONFCTL_PDATAF_SET(format->pdataf));
#ifdef DBG_TC358746
      printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%lX\n", CONFCTL, CONFCTL_PDATAF_MASK, CONFCTL_PDATAF_SET(format->pdataf));
#endif
   }

   return err;
}

static int tc358746_set_buffers(struct regmap *regmap,
      u32 width, u8 bpp, u16 vb_fifo)
{
   unsigned int byte_per_line = (width * bpp) / 8;
   int err;

   err = regmap_write(regmap, FIFOCTL, vb_fifo);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%X\n", FIFOCTL, vb_fifo);
#endif

   if (!err)
   {
      err = regmap_write(regmap, WORDCNT, byte_per_line);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", WORDCNT, byte_per_line);
#endif
   }

   return err;
}

static int tc358746_enable_csi_lanes(struct regmap *regmap,
      int lane_num, int enable)
{
   u32 val = 0;
   u32 bleVal = 0;
   int err = 0;

   if (lane_num < 1 || !enable) {
      if (!err)
      {
         dione_ir_regmap_format_32_ble((void *)&bleVal, CLW_CNTRL_CLW_LANEDISABLE_MASK);
         err = regmap_write(regmap, CLW_CNTRL, bleVal);
#ifdef DBG_TC358746
         printk("tc358746 write @0x%X = 0x%lX\n", CLW_CNTRL, CLW_CNTRL_CLW_LANEDISABLE_MASK);
#endif
      }
      if (!err)
      {
         dione_ir_regmap_format_32_ble((void *)&bleVal, D0W_CNTRL_D0W_LANEDISABLE_MASK);
         err = regmap_write(regmap, D0W_CNTRL, bleVal);
#ifdef DBG_TC358746
         printk("tc358746 write @0x%X = 0x%lX\n", D0W_CNTRL, D0W_CNTRL_D0W_LANEDISABLE_MASK);
#endif
      }
   }

   if (lane_num < 2 || !enable) {
      if (!err)
      {
         dione_ir_regmap_format_32_ble((void *)&bleVal, D1W_CNTRL_D1W_LANEDISABLE_MASK);
         err = regmap_write(regmap, D1W_CNTRL, bleVal);
#ifdef DBG_TC358746
         printk("tc358746 write @0x%X = 0x%lX\n", D1W_CNTRL, D1W_CNTRL_D1W_LANEDISABLE_MASK);
#endif
      }
   }

   if (lane_num < 3 || !enable) {
      if (!err)
      {
         dione_ir_regmap_format_32_ble((void *)&bleVal, D2W_CNTRL_D2W_LANEDISABLE_MASK);
         err = regmap_write(regmap, D2W_CNTRL, bleVal);
#ifdef DBG_TC358746
         printk("tc358746 write @0x%X = 0x%lX\n", D2W_CNTRL, D2W_CNTRL_D2W_LANEDISABLE_MASK);
#endif
      }
   }

   if (lane_num < 4 || !enable) {
      if (!err)
      {
         dione_ir_regmap_format_32_ble((void *)&bleVal, D2W_CNTRL_D3W_LANEDISABLE_MASK);
         err = regmap_write(regmap, D3W_CNTRL, bleVal);
#ifdef DBG_TC358746
         printk("tc358746 write @0x%X = 0x%lX\n", D3W_CNTRL, D2W_CNTRL_D3W_LANEDISABLE_MASK);
#endif
      }
   }

   if (lane_num > 0 && enable) {
      val |= HSTXVREGEN_CLM_HSTXVREGEN_MASK |
         HSTXVREGEN_D0M_HSTXVREGEN_MASK;
   }

   if (lane_num > 1 && enable)
      val |= HSTXVREGEN_D1M_HSTXVREGEN_MASK;

   if (lane_num > 2 && enable)
      val |= HSTXVREGEN_D2M_HSTXVREGEN_MASK;

   if (lane_num > 3 && enable)
      val |= HSTXVREGEN_D3M_HSTXVREGEN_MASK;

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, val);
      err = regmap_write(regmap, HSTXVREGEN, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", HSTXVREGEN, val);
#endif
   }

   return err;
}

static int tc358746_set_csi(struct regmap *regmap,
      const struct tc358746_csi *csi)
{
   u32 val, bleVal;
   int err;

   val = TCLK_HEADERCNT_TCLK_ZEROCNT_SET(csi->tclk_zerocnt) |
      TCLK_HEADERCNT_TCLK_PREPARECNT_SET(csi->tclk_preparecnt);
   dione_ir_regmap_format_32_ble((void *)&bleVal, val);
   err = regmap_write(regmap, TCLK_HEADERCNT, bleVal);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%X\n", TCLK_HEADERCNT, val);
#endif

   val = THS_HEADERCNT_THS_ZEROCNT_SET(csi->ths_zerocnt) |
      THS_HEADERCNT_THS_PREPARECNT_SET(csi->ths_preparecnt);
   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, val);
      err = regmap_write(regmap, THS_HEADERCNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", THS_HEADERCNT, val);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, csi->twakeupcnt);
      err = regmap_write(regmap, TWAKEUP, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", TWAKEUP, csi->twakeupcnt);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, csi->tclk_postcnt);
      err = regmap_write(regmap, TCLK_POSTCNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", TCLK_POSTCNT, csi->tclk_postcnt);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, csi->ths_trailcnt);
      err = regmap_write(regmap, THS_TRAILCNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", THS_TRAILCNT, csi->ths_trailcnt);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, csi->lineinitcnt);
      err = regmap_write(regmap, LINEINITCNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", LINEINITCNT, csi->lineinitcnt);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, csi->lptxtimecnt);
      err = regmap_write(regmap, LPTXTIMECNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", LPTXTIMECNT, csi->lptxtimecnt);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, csi->tclk_trailcnt);
      err = regmap_write(regmap, TCLK_TRAILCNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", TCLK_TRAILCNT, csi->tclk_trailcnt);
#endif
   }

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, CSI_HSTXVREGCNT);
      err = regmap_write(regmap, HSTXVREGCNT, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", HSTXVREGCNT, CSI_HSTXVREGCNT);
#endif
   }

   val = csi->is_continuous_clk ? TXOPTIONCNTRL_CONTCLKMODE_MASK : 0;
   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, val);
      err = regmap_write(regmap, TXOPTIONCNTRL, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", TXOPTIONCNTRL, val);
#endif
   }

   return err;
}

static int tc358746_wr_csi_control(struct regmap *regmap, u32 val)
{
   u32 bleVal;
   int err;
   val &= CSI_CONFW_DATA_MASK;
   val |= CSI_CONFW_MODE_SET_MASK | CSI_CONFW_ADDRESS_CSI_CONTROL_MASK;
   dione_ir_regmap_format_32_ble((void *)&bleVal, val);

   err = regmap_write(regmap, CSI_CONFW, bleVal);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%X\n", CSI_CONFW, val);
#endif
   return err;
}

static int tc358746_enable_csi_module(struct regmap *regmap, int lane_num)
{
   u32 val, bleVal;
   int err;

   dione_ir_regmap_format_32_ble((void *)&bleVal, STARTCNTRL_START_MASK);
   err = regmap_write(regmap, STARTCNTRL, bleVal);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%lX\n", STARTCNTRL, STARTCNTRL_START_MASK);
#endif

   if (!err)
   {
      dione_ir_regmap_format_32_ble((void *)&bleVal, CSI_START_STRT_MASK);
      err = regmap_write(regmap, CSI_START, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%lX\n", CSI_START, CSI_START_STRT_MASK);
#endif
   }

   val = CSI_CONTROL_NOL_1_MASK;
   if (lane_num == 2)
      val = CSI_CONTROL_NOL_2_MASK;
   else if (lane_num == 3)
      val = CSI_CONTROL_NOL_3_MASK;
   else if (lane_num == 4)
      val = CSI_CONTROL_NOL_4_MASK;

   val |= CSI_CONTROL_CSI_MODE_MASK | CSI_CONTROL_TXHSMD_MASK |
      CSI_CONTROL_EOTDIS_MASK; /* add, according to Excel */

   if (!err)
   {
      err = tc358746_wr_csi_control(regmap, val);
   }

   return err;
}

static int dione_ir_set_mode(struct tegracam_device *tc_dev)
{
   struct dione_ir *priv = (struct dione_ir *)tegracam_get_privdata(tc_dev);
   struct camera_common_data *s_data = priv->s_data;
   struct regmap *ctl_regmap = s_data->regmap;
   struct regmap *tx_regmap = priv->tx_regmap;
   const struct sensor_mode_properties *sensor_mode;
   const struct camera_common_colorfmt *colorfmt;
   struct tc358746_input input;
   struct tc358746 params;
   int i, err;

   if (s_data->mode != priv->mode) {
      /* Should be unreachable now that only the camera's own resolution is
       * advertised. Say so if it happens: refusing in silence here cost a
       * whole debugging session, the caller only ever sees the framework's
       * generic "Error writing mode". */
      dev_err(tc_dev->dev,
            "mode %d requested but this camera is mode %d (%ux%u) -- refusing\n",
            s_data->mode, priv->mode, s_data->fmt_width, s_data->fmt_height);
      return -EINVAL;
   }

   /*
    * Pick the device-tree mode node by resolution AND format, not by
    * s_data->mode_prop_idx.
    *
    * mode_prop_idx comes from camera_common_try_fmt(), which matches on width
    * and height only and breaks on the first hit. As soon as one resolution is
    * declared in two formats -- RGB888 and RAW14 for the same sensor -- it
    * always lands on the first of the two, so the format below would be the
    * device tree's rather than the one V4L2 negotiated. Measured on an Orin
    * Nano 2026-09-04: asking for AB24 while only a Y14 node existed at that
    * resolution reported AB24 to userspace and still programmed the bridge for
    * RAW14 (DATAFMT 0x80) -- silently wrong data, no error anywhere.
    *
    * s_data->colorfmt is what camera_common_s_fmt() resolved from the request,
    * so it is the authority here. Match on the media-bus code: it is the one
    * value both sides share -- the device tree gives a V4L2 fourcc that need
    * not equal the requested one (an rgb888 node yields RGB24 while userspace
    * asks for AB24/ABGR32), but both map to MEDIA_BUS_FMT_RGB888_1X24.
    *
    * Same reasoning, and the same trap, as vi5_pad0_en() on the VI side.
    */
   sensor_mode = NULL;
   if (s_data->colorfmt) {
      unsigned int m;

      for (m = 0; m < s_data->sensor_props.num_modes; m++) {
         const struct sensor_mode_properties *cand =
               s_data->sensor_props.sensor_modes + m;
         const struct camera_common_colorfmt *cand_fmt =
               camera_common_find_pixelfmt(
                     cand->image_properties.pixel_format);

         if (cand_fmt && cand_fmt->code == s_data->colorfmt->code &&
             cand->image_properties.width  == s_data->fmt_width &&
             cand->image_properties.height == s_data->fmt_height) {
            sensor_mode = cand;
            break;
         }
      }
   }

   if (!sensor_mode) {
      /* No node for this resolution/format pair. Fall back to the old
       * behaviour rather than refuse: a device tree with a single format per
       * resolution -- every shipped one today -- keeps working unchanged. */
      sensor_mode = s_data->sensor_props.sensor_modes + s_data->mode_prop_idx;
      dev_dbg(tc_dev->dev,
              "no DT mode for %ux%u code 0x%04x, using mode_prop_idx %u\n",
              s_data->fmt_width, s_data->fmt_height,
              s_data->colorfmt ? s_data->colorfmt->code : 0,
              s_data->mode_prop_idx);
   }

   colorfmt = camera_common_find_pixelfmt(sensor_mode->image_properties.pixel_format);

   if (!colorfmt) {
      dev_err(tc_dev->dev, "unsupported pixelformat\n");
      return -EINVAL;
   }

   dev_dbg(tc_dev->dev, "set_mode: %ux%u -> DT pixel_format 0x%08x, mbus 0x%04x\n",
           s_data->fmt_width, s_data->fmt_height,
           sensor_mode->image_properties.pixel_format, colorfmt->code);

   if (s_data->def_clk_freq != sensor_mode->signal_properties.mclk_freq * 1000) {
      dev_err(tc_dev->dev, "mclk_freq must be the same in every mode\n");
      return -EINVAL;
   }

   input.mbus_fmt = colorfmt->code;
   input.refclk = s_data->def_clk_freq;
   input.num_lanes = sensor_mode->signal_properties.num_lanes;
   input.discontinuous_clk = sensor_mode->signal_properties.discontinuous_clk;
   input.pclk = sensor_mode->signal_properties.pixel_clock.val;
   input.width = sensor_mode->image_properties.width;
   input.hblank = sensor_mode->image_properties.line_length - input.width;

   for (i = 0; i < priv->link_frequencies_num; i++) {
      input.link_frequency = priv->link_frequencies[i];
      if (tc358746_calculate(&params, &input) == 0)
         break;
   }

   if (i >= priv->link_frequencies_num) {
      dev_err(tc_dev->dev, "could not calculate parameters for tc358746\n");
      return -EINVAL;
   }

   err = 0;
   if (test_mode) {
#ifdef DIONE_IR_STARTUP_TMO_MS
      /* wait until FPGA in sensor finishes booting up */
      while (ktime_ms_delta(ktime_get(), priv->start_up)
            < DIONE_IR_STARTUP_TMO_MS)
         msleep(100);
#endif
      /* enable test pattern in the sensor module */
      err = dione_ir_i2c_write32(priv->fpga_client,
            DIONE_IR_REG_ACQUISITION_STOP, 2);
      if (!err) {
         msleep(300);
         err = dione_ir_i2c_write32(priv->fpga_client,
               DIONE_IR_REG_ACQUISITION_SRC, 0);
      }

      if (!err) {
         msleep(300);
         err = dione_ir_i2c_write32(priv->fpga_client,
               DIONE_IR_REG_ACQUISITION_STOP, 1);
      }
   }

#ifdef DBG_TC358746
   printk("tc358746_calculate input.link_frequency = %lld\n", input.link_frequency);
   printk("tc358746_calculate input.mbus_fmt = 0x%x\n", input.mbus_fmt);
   printk("tc358746_calculate input.refclk = %d\n", input.refclk);
   printk("tc358746_calculate input.num_lanes = %d\n", input.num_lanes);
   printk("tc358746_calculate input.discontinuous_clk = %d\n", input.discontinuous_clk);
   printk("tc358746_calculate input.pclk = %d\n", input.pclk);
   printk("tc358746_calculate input.width = %d\n", input.width);
   printk("tc358746_calculate input.hblank = %d\n", input.hblank);
   printk("tc358746_calculate params.format->code = %d\n", params.format->code);
   printk("tc358746_calculate params.format->bus_width = %d\n", params.format->bus_width);
   printk("tc358746_calculate params.format->bpp = %d\n", params.format->bpp);
   printk("tc358746_calculate params.format->pdformat = %d\n", params.format->pdformat);
   printk("tc358746_calculate params.format->pdataf = %d\n", params.format->pdataf);
   printk("tc358746_calculate params.format->ppp = %d\n", params.format->ppp);
   printk("tc358746_calculate params.format->csitx_only = %d\n", params.format->csitx_only);
   printk("tc358746_calculate params.pll.pllinclk_hz = %d\n", params.pll.pllinclk_hz);
   printk("tc358746_calculate params.pll.pll_prd = %d\n", params.pll.pll_prd);
   printk("tc358746_calculate params.pll.pll_fbd = %d\n", params.pll.pll_fbd);
   printk("tc358746_calculate params.csi.speed_range = %d\n", params.csi.speed_range);
   printk("tc358746_calculate params.csi.unit_clk_hz = %d\n", params.csi.unit_clk_hz);
   printk("tc358746_calculate params.csi.unit_clk_mul = %d\n", params.csi.unit_clk_mul);
   printk("tc358746_calculate params.csi.speed_per_lane = %d\n", params.csi.speed_per_lane);
   printk("tc358746_calculate params.csi.lane_num = %d\n", params.csi.lane_num);
   printk("tc358746_calculate params.csi.is_continuous_clk = %d\n", params.csi.is_continuous_clk);
   printk("tc358746_calculate params.csi.lineinitcnt = %d\n", params.csi.lineinitcnt);
   printk("tc358746_calculate params.csi.lptxtimecnt = %d\n", params.csi.lptxtimecnt);
   printk("tc358746_calculate params.csi.twakeupcnt = %d\n", params.csi.twakeupcnt);
   printk("tc358746_calculate params.csi.tclk_preparecnt = %d\n", params.csi.tclk_preparecnt);
   printk("tc358746_calculate params.csi.tclk_zerocnt = %d\n", params.csi.tclk_zerocnt);
   printk("tc358746_calculate params.csi.tclk_trailcnt = %d\n", params.csi.tclk_trailcnt);
   printk("tc358746_calculate params.csi.tclk_postcnt = %d\n", params.csi.tclk_postcnt);
   printk("tc358746_calculate params.csi.ths_preparecnt = %d\n", params.csi.ths_preparecnt);
   printk("tc358746_calculate params.csi.ths_zerocnt = %d\n", params.csi.ths_zerocnt);
   printk("tc358746_calculate params.csi.ths_trailcnt = %d\n", params.csi.ths_trailcnt);
   printk("tc358746_calculate params.csi.csi_hs_lp_hs_ps = %d\n", params.csi.csi_hs_lp_hs_ps);
   printk("tc358746_calculate params.vb_fifo = %d\n", params.vb_fifo);
#endif


   if (skip_bridge_cfg) {
      dev_info_once(tc_dev->dev,
            "skip_bridge_cfg=1: leaving the TC358746 alone, configure it "
            "externally before starting the stream\n");
      return 0;
   }

   regmap_write(ctl_regmap, DBG_ACT_LINE_CNT, 0);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%X\n", DBG_ACT_LINE_CNT, 0);
#endif

   if (!err)
      err = tc358746_sreset(ctl_regmap);
   if (err) {
      dev_err(tc_dev->dev, "Failed to reset chip\n");
      return err;
   }

   err = tc358746_set_pll(ctl_regmap, &params.pll, &params.csi);
   if (err) {
      dev_err(tc_dev->dev, "Failed to setup PLL\n");
      return err;
   }

   err = tc358746_set_csi_color_space(ctl_regmap, params.format);

   if (!err)
      err = tc358746_set_buffers(ctl_regmap, input.width,
            params.format->bpp, params.vb_fifo);

   if (!err)
      err = tc358746_enable_csi_lanes(tx_regmap,
            params.csi.lane_num, true);

   if (!err)
      err = tc358746_set_csi(tx_regmap, &params.csi);

   if (!err)
      err = tc358746_enable_csi_module(tx_regmap,
            params.csi.lane_num);

   if (err)
      dev_err(tc_dev->dev, "%s return code (%d)\n", __func__, err);

   return err;
}

static int dione_ir_start_streaming(struct tegracam_device *tc_dev)
{
   struct dione_ir *priv = (struct dione_ir *)tegracam_get_privdata(tc_dev);
   struct camera_common_data *s_data = priv->s_data;
   struct regmap *ctl_regmap = s_data->regmap;
   int err;

   err = regmap_write(ctl_regmap, PP_MISC, 0);
#ifdef DBG_TC358746
   printk("tc358746 write @0x%X = 0x%X\n", PP_MISC, 0);
#endif
   if (!err)
   {
      err = regmap_update_bits(ctl_regmap, CONFCTL,
            CONFCTL_PPEN_MASK, CONFCTL_PPEN_MASK);
#ifdef DBG_TC358746
      printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%lX\n", CONFCTL, CONFCTL_PPEN_MASK, CONFCTL_PPEN_MASK);
#endif
   }

   if (err)
      dev_err(tc_dev->dev, "%s return code (%d)\n", __func__, err);

   return err;
}

static int dione_ir_stop_streaming(struct tegracam_device *tc_dev)
{
   struct dione_ir *priv = (struct dione_ir *)tegracam_get_privdata(tc_dev);
   struct camera_common_data *s_data = priv->s_data;
   struct regmap *ctl_regmap = s_data->regmap;
   struct regmap *tx_regmap = priv->tx_regmap;
   int err;
   u32 bleVal;

   err = regmap_update_bits(ctl_regmap, PP_MISC, PP_MISC_FRMSTOP_MASK,
         PP_MISC_FRMSTOP_MASK);
#ifdef DBG_TC358746
   printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%lX\n", PP_MISC, PP_MISC_FRMSTOP_MASK, PP_MISC_FRMSTOP_MASK);
#endif

   if (!err)
   {
      err = regmap_update_bits(ctl_regmap, CONFCTL,
            CONFCTL_PPEN_MASK, 0);
#ifdef DBG_TC358746
      printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%X\n", CONFCTL, CONFCTL_PPEN_MASK, 0);
#endif
   }

   if (!err)
   {
      err = regmap_update_bits(ctl_regmap, PP_MISC,
            PP_MISC_RSTPTR_MASK,
            PP_MISC_RSTPTR_MASK);
#ifdef DBG_TC358746
      printk("tc358746 write bits @0x%X : mask 0x%lX, value = 0x%lX\n", PP_MISC, PP_MISC_RSTPTR_MASK, PP_MISC_RSTPTR_MASK);
#endif
   }

   if (!err)
   {
      /*
       * Both bits (0x3), RstMdl included.
       *
       * ⚠️ Datasheet Table 6.73 (p.102) says of RstMdl: "Do not set this bit to
       * 1. Perform a hardware reset when a CSI TX block reset is necessary."
       * TRIED on 2026-09-07: writing RstCnf alone (0x2), as the datasheet
       * prescribes, and the link produced NO frames at all -- 0/18 captures,
       * every tool, both formats. Restored to 0x3, which works.
       *
       * So the bit is required here in practice despite the warning. Do not
       * "fix" this against the datasheet again without measuring.
       */
      dione_ir_regmap_format_32_ble((void *)&bleVal, CSIRESET_RESET_CNF_MASK | CSIRESET_RESET_MODULE_MASK);
      err = regmap_write(tx_regmap, CSIRESET, bleVal);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%lX\n", CSIRESET, CSIRESET_RESET_CNF_MASK | CSIRESET_RESET_MODULE_MASK);
#endif
   }
   if (!err)
   {
      err = regmap_write(ctl_regmap, DBG_ACT_LINE_CNT, 0);
#ifdef DBG_TC358746
      printk("tc358746 write @0x%X = 0x%X\n", DBG_ACT_LINE_CNT, 0);
#endif
   }

   if (err)
      dev_err(tc_dev->dev, "%s return code (%d)\n", __func__, err);

   return err;
}

static struct camera_common_sensor_ops dione_ir_ops = {
   .numfrmfmts = ARRAY_SIZE(dione_ir_frmfmt),
   .frmfmt_table = dione_ir_frmfmt,
   .power_on = dione_ir_power_on,
   .power_off = dione_ir_power_off,
   .write_reg = dione_ir_write_reg,
   .read_reg = dione_ir_read_reg,
   .parse_dt = dione_ir_parse_dt,
   .power_get = dione_ir_power_get,
   .power_put = dione_ir_power_put,
   .set_mode = dione_ir_set_mode,
   .start_streaming = dione_ir_start_streaming,
   .stop_streaming = dione_ir_stop_streaming,
};

static int dione_ir_i2c_read(struct i2c_client *client, u32 reg, u8 *dst, u16 len)
{
   struct i2c_msg msgs[2];
   u8 tx_data[6];
   u8 rx_data[72];
   unsigned int attempt, try;
   u16 status = DIONE_IR_STATUS_BUSY;

   if (len > sizeof(rx_data) - 2)
      return -EINVAL;

   *(u32 *)tx_data = cpu_to_le32(reg);
   *(u16 *)(tx_data + 4) = cpu_to_le16(len);

   msgs[0].addr = client->addr;
   msgs[0].flags = 0;
   msgs[0].len = sizeof(tx_data);
   msgs[0].buf = tx_data;

   msgs[1].addr = client->addr;
   msgs[1].flags = I2C_M_RD;
   msgs[1].len = len + 2;
   msgs[1].buf = rx_data;

   for (try = 1; try <= DIONE_IR_READ_TRIES; try++) {
      /* One request, and one only while it is in flight. */
      if (i2c_transfer(client->adapter, &msgs[0], 1) != 1)
         return -EIO;

      /* Let the camera prepare the answer before touching the buffer. */
      usleep_range(DIONE_IR_READ_WAIT_US, 2 * DIONE_IR_READ_WAIT_US);

      for (attempt = 1; attempt <= DIONE_IR_READ_POLLS; attempt++) {
         if (i2c_transfer(client->adapter, &msgs[1], 1) != 1)
            return -EIO;

         status = le16_to_cpu(*(u16 *)rx_data);
         if (status != DIONE_IR_STATUS_BUSY)
            break;

         usleep_range(DIONE_IR_READ_WAIT_US, 2 * DIONE_IR_READ_WAIT_US);
      }

      if (status == 0)
         break;

      /*
       * A status other than 0xFFFF means the request COMPLETED, with an error.
       * Nothing is in flight any more, so re-sending it is allowed -- the
       * manual only forbids a second request while one is still processing.
       * Worth doing: this read is intermittently refused right after the three
       * 32-byte string reads of detect_dione_ir(), and succeeds on a retry
       * (measured on a Dione 320, 2026-09-08).
       */
      if (status == DIONE_IR_STATUS_BUSY)
         break;                  /* still busy after all the polls: give up */

      dev_dbg(&client->dev, "reg %#010x: status %#06x, retrying\n", reg, status);
      usleep_range(DIONE_IR_READ_WAIT_US, 2 * DIONE_IR_READ_WAIT_US);
   }

   if (status != 0) {
      dev_warn(&client->dev, "reg %#010x: status %#06x after %u try/tries\n",
            reg, status, try > DIONE_IR_READ_TRIES ? DIONE_IR_READ_TRIES : try);
      return status == DIONE_IR_STATUS_BUSY ? -ETIMEDOUT : -EINVAL;
   }

   switch (len) {
   case 1:
      dst[0] = rx_data[2];
      break;
   case 2:
      *(u16 *)dst = le16_to_cpu(*(u16 *)(rx_data + 2));
      break;
   case 4:
      *(u32 *)dst = le32_to_cpu(*(u32 *)(rx_data + 2));
      break;
   default:
      memcpy(dst, rx_data + 2, len);
   }

   return 0;
}

static int dione_ir_i2c_write32(struct i2c_client *client, u32 reg, u32 val)
{
   struct i2c_msg msgs;
   u8 tx_data[10];

   *(u32 *)tx_data = cpu_to_le32(reg);
   *(u16 *)(tx_data + 4) = cpu_to_le16(4);
   *(u32 *)(tx_data + 6) = cpu_to_le32(val);

   msgs.addr = client->addr;
   msgs.flags = 0;
   msgs.len = sizeof(tx_data);
   msgs.buf = tx_data;

   if (i2c_transfer(client->adapter, &msgs, 1) != 1)
      return -EIO;

   return 0;
}

static ssize_t dione_ir_chnod_read(
      struct file *file_ptr
      , char __user *user_buffer
      , size_t count
      , loff_t *position)
{
   int ret = -EINVAL;
   int i;
   u8 *buffer_i2c = NULL;

   // printk( KERN_NOTICE "chnod: Device file read at offset = %i, bytes count = %u\n"
   // , (int)*position
   // , (unsigned int)count );

   for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
   {
      if (strcmp(i2c_clients[i].chnod_name, file_ptr->f_path.dentry->d_name.name) == 0)
      {
         buffer_i2c =  kmalloc(count, GFP_KERNEL);
         if (buffer_i2c)
         {

            ret = i2c_master_recv(i2c_clients[i].i2c_client, buffer_i2c, count);
            if (ret <= 0)
            {
               printk(KERN_ERR "%s : Error sending read request, ret = %d\n", __func__, ret);
               kfree(buffer_i2c);
               return -1;
            }

            if( copy_to_user(user_buffer, buffer_i2c, count) != 0 )
            {
               printk(KERN_ERR "%s : Error, failed to copy from user\n", __func__);
               kfree(buffer_i2c);
               return -EFAULT;
            }

            kfree(buffer_i2c);
         }
         else
         {
            printk(KERN_ERR "%s : Error allocating memory\n", __func__);
            return -1;
         }
      }
   }

   return ret;
}

static ssize_t dione_ir_chnod_write(
      struct file *file_ptr
      , const char __user *user_buffer
      , size_t count
      , loff_t *position)
{
   int ret = -EINVAL;
   u8 *buffer_i2c = NULL;
   int i;

   for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
   {
      if (strcmp(i2c_clients[i].chnod_name, file_ptr->f_path.dentry->d_name.name) == 0)
      {
         // printk( KERN_NOTICE "chnod: Device file write at offset = %i, bytes count = %u\n"
         // , (int)*position
         // , (unsigned int)count );

         buffer_i2c =  kmalloc(count, GFP_KERNEL);
         if (buffer_i2c)
         {
            if( copy_from_user(buffer_i2c, user_buffer, count) != 0 )
            {
               printk(KERN_ERR "%s : Error, failed to copy from user\n", __func__);
               kfree(buffer_i2c);
               return -EFAULT;
            }

            ret = i2c_master_send(i2c_clients[i].i2c_client, buffer_i2c, count);
            if (ret <= 0)
            {
               printk(KERN_ERR "%s : Error sending Write request, ret = %d\n", __func__, ret);
               kfree(buffer_i2c);
               return -1;
            }
            kfree(buffer_i2c);
         }
         else
         {
            printk(KERN_ERR "%s : Error allocating memory\n", __func__);
            return -1;
         }
         break;
      }
   }

   return ret;
}

int dione_ir_chnod_open (struct inode * pInode, struct file * file)
{
   int i;
   for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
   {
      if (strcmp(i2c_clients[i].chnod_name, file->f_path.dentry->d_name.name) == 0)
      {
         if (i2c_clients[i].i2c_locked == 0)
         {
            i2c_clients[i].i2c_locked = 1;
            return 0;
         }
         else
         {
            return -EBUSY;
         }
         break;
      }
   }
   return -EINVAL;
}

int dione_ir_chnod_release (struct inode * pInode, struct file * file)
{
   int i;
   for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
   {
      if (strcmp(i2c_clients[i].chnod_name, file->f_path.dentry->d_name.name) == 0)
      {
         i2c_clients[i].i2c_locked = 0;
         return 0;
      }
   }
   return -EINVAL;
}

static struct file_operations dione_ir_chnod_register_fops = 
{
   .owner   = THIS_MODULE,
   .read    = dione_ir_chnod_read,
   .write   = dione_ir_chnod_write,
   .open    = dione_ir_chnod_open,
   .release = dione_ir_chnod_release,
};


static inline int dione_ir_chnod_register_device(int i2c_ind)
{
   struct device *pDev;
   int result = 0;
   result = register_chrdev( 0, i2c_clients[i2c_ind].chnod_name, &dione_ir_chnod_register_fops );
   if( result < 0 )
   {
      printk( KERN_WARNING "dal register chnod:  can\'t register character device with error code = %i\n", result );
      return result;
   }
   i2c_clients[i2c_ind].chnod_major_number = result;
   printk( KERN_DEBUG "dal register chnod: registered character device with major number = %i and minor numbers 0...255\n", i2c_clients[i2c_ind].chnod_major_number );

   i2c_clients[i2c_ind].chnod_device_number = MKDEV(i2c_clients[i2c_ind].chnod_major_number, 0);

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,4,0)
   i2c_clients[i2c_ind].pClass_chnod = class_create(THIS_MODULE, i2c_clients[i2c_ind].chnod_name);
#else
   i2c_clients[i2c_ind].pClass_chnod = class_create(i2c_clients[i2c_ind].chnod_name);
#endif
   if (IS_ERR(i2c_clients[i2c_ind].pClass_chnod)) {
      printk(KERN_WARNING "\ncan't create class");
      unregister_chrdev_region(i2c_clients[i2c_ind].chnod_device_number, 1);
      return -EIO;
   }

   if (IS_ERR(pDev = device_create(i2c_clients[i2c_ind].pClass_chnod, NULL, i2c_clients[i2c_ind].chnod_device_number, NULL, i2c_clients[i2c_ind].chnod_name))) {
      printk(KERN_WARNING "Can't create device /dev/%s\n", i2c_clients[i2c_ind].chnod_name);
      class_destroy(i2c_clients[i2c_ind].pClass_chnod);
      unregister_chrdev_region(i2c_clients[i2c_ind].chnod_device_number, 1);
      return -EIO;
   }
   return 0;
}

static int detect_dione_ir(struct dione_ir *priv, u32 fpga_addr)
{
   struct device *dev = priv->s_data->dev;
   u32 width, height;
   u8 buf[64];
   int i, mode, ret;
   int err = 0;

   msleep(200);

   dev_info(dev, "probing fpga at address %#02x%s\n",
         fpga_addr, priv->reva ? " reva" : "");

#if LINUX_VERSION_CODE < KERNEL_VERSION(5,5,0)
   priv->fpga_client = i2c_new_dummy(priv->tc35_client->adapter, fpga_addr);
#else
   priv->fpga_client = i2c_new_dummy_device(priv->tc35_client->adapter, fpga_addr);
#endif
   if (!priv->fpga_client)
      return -ENOMEM;

   ret = dione_ir_i2c_read(priv->fpga_client, DIONE_IR_REG_WIDTH_MAX,
         (u8 *)&width, sizeof(width));
   if (ret < 0)
      goto error;

   ret = dione_ir_i2c_read(priv->fpga_client, DIONE_IR_REG_HEIGHT_MAX,
         (u8 *)&height, sizeof(height));
   if (ret < 0)
      goto error;

   mode = dione_ir_find_frmfmt(width, height);
   if (mode < 0) {
      ret = -ENODEV;
      goto error;
   }

   priv->native_width = width;
   priv->native_height = height;

   dev_info(dev, "%s fpga_found\n", __func__);
   priv->fpga_found = true;

   ret = dione_ir_i2c_read(priv->fpga_client, DIONE_IR_REG_FIRMWARE_VERSION,
         buf, sizeof(buf));
   if (ret < 0)
      goto error;

   for (i = sizeof(buf) - 1; i >= 0 && buf[i] == 0xff; i--)
      buf[i] = '\0';
   strncpy(priv->firmware_version, buf, sizeof(priv->firmware_version) - 1);
   priv->firmware_version[sizeof(priv->firmware_version) - 1] = '\0';

   /* Read model name */
   ret = dione_ir_i2c_read(priv->fpga_client, DIONE_IR_REG_MODEL_NAME,
         (u8 *)priv->model, sizeof(priv->model));
   if (ret < 0) {
      priv->model[0] = '\0';
      dev_warn(dev, "failed to read model name\n");
   } else {
      for (i = sizeof(priv->model) - 1; i >= 0 &&
            (priv->model[i] == (char)0xff || priv->model[i] == '\0'); i--)
         priv->model[i] = '\0';
   }

   /* Read serial number */
   ret = dione_ir_i2c_read(priv->fpga_client, DIONE_IR_REG_SERIAL_NUMBER,
         (u8 *)priv->serial_number, sizeof(priv->serial_number));
   if (ret < 0) {
      priv->serial_number[0] = '\0';
      dev_warn(dev, "failed to read serial number\n");
   } else {
      for (i = sizeof(priv->serial_number) - 1; i >= 0 &&
            (priv->serial_number[i] == (char)0xff || priv->serial_number[i] == '\0'); i--)
         priv->serial_number[i] = '\0';
   }

   /*
    * Read the camera's output pixel format ONCE, here, while the camera's I2C
    * client still exists (probe releases it right after, so that dioneCtrl.py
    * can claim the address with a plain I2C_SLAVE ioctl).
    *
    * The driver never writes this register: the user selects the camera's
    * output format by other means. What the driver does is adapt to it --
    * dione_ir_probe() offers userspace only the formats that the current
    * camera state can actually produce. See the truncation there.
    */
   priv->cam_pixfmt = 0;
   ret = dione_ir_i2c_read(priv->fpga_client, DIONE_IR_REG_PIXEL_FORMAT,
         (u8 *)&priv->cam_pixfmt, sizeof(priv->cam_pixfmt));
   if (ret < 0) {
      priv->cam_pixfmt = 0;
      dev_warn(dev, "failed to read PixelFormat (%d), assuming RGB888 only\n",
            ret);
   }

   if (priv->fpga_found)
   {
      // Find the first i2c client available
      for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
      {
         if (i2c_clients[i].i2c_client == NULL)
         {
            i2c_clients[i].i2c_client = priv->fpga_client;
            sprintf(i2c_clients[i].chnod_name,  "%s-i2c-%s-%02x", dev_driver_string(dev), dev_name(dev), fpga_addr);
            dev_info(dev, "chnod: /dev/%s\n", i2c_clients[i].chnod_name);
            err = dione_ir_chnod_register_device(i);
            if (err)
            {
               dev_err(dev, "chnod register failed\n");
               i2c_clients[i].chnod_name[0] = 0;
               return err;
            }
            break;
         }
      }
   }
   dev_info(dev, "dione-ir %ux%u at address %#02x, PixelFormat 0x%08x (%s), "
         "firmware: %s, model: %s, serial: %s\n",
         width, height, fpga_addr, priv->cam_pixfmt,
         priv->cam_pixfmt == DIONE_IR_PIXFMT_MONO16 ? "pseudo-mono" :
         priv->cam_pixfmt == DIONE_IR_PIXFMT_RGB8 ? "colour" : "unknown",
         buf,
         priv->model[0] ? priv->model : "N/A",
         priv->serial_number[0] ? priv->serial_number : "N/A");

   return mode;

error:
   if (priv->fpga_client != NULL) {
      i2c_unregister_device(priv->fpga_client);
      priv->fpga_client = NULL;
   }

   return ret;
}

/*
 * How long to keep retrying the first I2C access while the camera boots.
 *
 * The camera needs more than a second after power-up before it answers. On the
 * usual Jetson carriers its rails are wired to the board supply, so it has been
 * running since t=0 and one attempt always suffices. On a carrier that switches
 * camera power or reset it does not: a customer's board releases camera reset
 * through an I2C GPIO expander at t=1.81 s and the driver probes ~40 ms later.
 *
 * The real figure depends on both the carrier and the camera, so it is a device
 * tree property on the camera node rather than a constant:
 *
 *     exosens,probe-timeout-ms = <2000>;
 *
 * Absent, or 0 -> a single attempt, the behaviour before this existed. The
 * default is deliberately "no retry": a device tree that says nothing about the
 * timeout gets no silent boot delay, and the shipped device trees carry an
 * explicit value. The first attempt is never delayed, so a carrier that powers
 * the camera early pays nothing whatever the value.
 *
 * Only the first of the two board_setup() passes waits -- see the loop.
 */
#define DIONE_IR_PROBE_TIMEOUT_MS_DEFAULT  0
#define DIONE_IR_PROBE_RETRY_MS            200

/* Attempts to make for a given timeout: always at least one. */
static unsigned int dione_ir_probe_attempts(struct device *dev)
{
   u32 ms = DIONE_IR_PROBE_TIMEOUT_MS_DEFAULT;

   if (dev->of_node)
      of_property_read_u32(dev->of_node, "exosens,probe-timeout-ms", &ms);

   return ms / DIONE_IR_PROBE_RETRY_MS + 1;
}

static int dione_ir_board_setup(struct dione_ir *priv)
{
   struct camera_common_data *s_data = priv->s_data;
   struct camera_common_pdata *pdata = s_data->pdata;
   struct device *dev = s_data->dev;
   struct regmap *ctl_regmap = s_data->regmap;
   u32 reg_val;
   int i, _quick_mode, err = 0;

   if (pdata->mclk_name) {
      err = camera_common_mclk_enable(s_data);
      if (err) {
         dev_err(dev, "error turning on mclk (%d)\n", err);
         goto done;
      }
   }

   _quick_mode = priv->quick_mode;
   priv->quick_mode = 0;
   err = s_data->ops->power_on(s_data);
   priv->quick_mode = _quick_mode;

#ifdef DIONE_IR_STARTUP_TMO_MS
   priv->start_up = ktime_get();
#endif
   /*
    * Probe sensor model id registers -- first access to the camera, retried
    * while it boots. See the budget above. A retry that was actually needed is
    * reported, so a late power rail or a late reset stays visible instead of
    * turning into a silent boot delay.
    */
   {
      /*
       * board_setup() is called twice by the caller: once per reset polarity,
       * the second time with priv->reva set. Waiting the full budget in both
       * would double it -- measured at 6 s with no camera attached. Only the
       * first pass waits; by the time the reva fallback runs we already know
       * nothing answers on this bus.
       *
       * Cost of that choice: a genuine revA board, whose first pass is
       * expected to fail, now pays the budget once before the polarity is
       * flipped. 2 s at probe, on that variant only.
       */
      unsigned int retries = priv->reva ? 1 : dione_ir_probe_attempts(dev);
      unsigned int attempt;

      for (attempt = 0; attempt < retries; attempt++) {
         err = regmap_read(ctl_regmap, CHIPID, &reg_val);
         if (!err)
            break;
         if (attempt + 1 < retries)
            msleep(DIONE_IR_PROBE_RETRY_MS);
      }
      if (err)
         goto err_reg_probe;
      if (attempt)
         dev_warn(dev, "camera answered only after %u ms (%u retries) -- "
               "it was still booting when the driver probed\n",
               attempt * DIONE_IR_PROBE_RETRY_MS, attempt);
   }

   if ((reg_val & CHIPID_CHIPID_MASK) != 0x4400) {
      dev_err(dev, "%s: invalid tc35 chip-id: %#x\n",
            __func__, reg_val);
      err = -ENODEV;
      goto err_reg_probe;
   }

   dev_info(dev, "%s tc35_found\n", __func__);
   priv->tc35_found = true;

   if (err) {
      dev_err(dev, "error during power on sensor (%d)\n", err);
      goto err_power_on;
   }

   for (i = 0; i < priv->fpga_address_num; i++) {
      u32 fpga_addr = priv->fpga_address[i];
      err = detect_dione_ir(priv, fpga_addr);
      if (err >= 0) {
         priv->mode = err;
         err = 0;
         break;
      }
   }

   if (err < 0)
   {
      goto err_reg_probe;
   }
   else
   {
      goto done;
   }

err_reg_probe:
   s_data->ops->power_off(s_data);

err_power_on:
   if (pdata->mclk_name)
      camera_common_mclk_disable(s_data);

done:
   return err;
}

static int dione_ir_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
   struct i2c_client *client = v4l2_get_subdevdata(sd);

   dev_dbg(&client->dev, "%s:\n", __func__);
   return 0;
}

static const struct v4l2_subdev_internal_ops dione_ir_subdev_internal_ops = {
   .open = dione_ir_open,
};

static struct tegracam_device *dione_ir_probe_sensor(struct dione_ir *priv)
{
   struct tegracam_device *tc_dev;
   struct device *dev = &priv->tc35_client->dev;
   int err;

   tc_dev = devm_kzalloc(dev, sizeof(struct tegracam_device), GFP_KERNEL);
   if (!tc_dev)
      return NULL;

   priv->quick_mode = quick_mode;
   tc_dev->client = priv->tc35_client;
   tc_dev->dev = dev;
   strncpy(tc_dev->name, "dioneir", sizeof(tc_dev->name));
   tc_dev->dev_regmap_config = &ctl_regmap_config;
   tc_dev->sensor_ops = &dione_ir_ops;
   tc_dev->v4l2sd_internal_ops = &dione_ir_subdev_internal_ops;
   tc_dev->tcctrl_ops = &dione_ir_ctrl_ops;

   err = tegracam_device_register(tc_dev);
   if (err) {
      devm_kfree(tc_dev->dev, tc_dev);
      tc_dev = NULL;
      dev_err(dev, "tegra camera driver registration failed\n");
   }

   if (!err) {
      priv->tc_dev = tc_dev;
      priv->s_data = tc_dev->s_data;
      priv->subdev = &tc_dev->s_data->subdev;
      tegracam_set_privdata(tc_dev, (void *)priv);

      /* Force s_data->colorfmt to the RGB24 entry instead of leaving it to
       * be derived later from userspace's S_FMT request. Dione only ever
       * declares mode_type="rgb"/pixel_phase="rgb888" in DT, which
       * sensor_common.c's extract_pixel_format() can only turn into
       * V4L2_PIX_FMT_RGB24 (see "rgb_rgb88824" case) — but ENUM_FMT on
       * /dev/videoX lists whatever vi5_formats.h offers for this mbus code
       * instead (RGBA32/XRGB32/RGBX32 on a PRISTINE_KERNEL vendor's
       * unpatched stock kernel), none of which camera_common_color_fmts[]
       * maps back to. Forcing the known-good RGB24 entry here — matching
       * the pattern already used in eg_ec_mipi_src.c for its own native
       * format — avoids relying on that mismatched round-trip.
       */
      {
         const struct camera_common_colorfmt *colorfmt =
               camera_common_find_pixelfmt(V4L2_PIX_FMT_RGB24);
         if (colorfmt)
            tc_dev->s_data->colorfmt = colorfmt;
      }

      priv->tx_regmap = devm_regmap_init_i2c(priv->tc35_client,
            &tx_regmap_config);
      if (IS_ERR(priv->tx_regmap)) {
         dev_err(dev, "tx_regmap init failed: %ld\n",
               PTR_ERR(priv->tx_regmap));
         err = -ENODEV;
      }
   }

   if (!err) {
      err = dione_ir_board_setup(priv);
      if (err && !priv->tc35_found && !priv->fpga_found) {
         priv->reva = true;
         err = dione_ir_board_setup(priv);
      }

      if (err && priv->tc35_found && priv->fpga_found)
         dev_err(dev, "dione_ir_board_setup error: %d\n", err);
   }

   /* After board_setup: detect_dione_ir() has read the camera's PixelFormat by
    * now, which is what the decision below needs. */
   if (!err) {
      /*
       * Offer userspace only the formats the camera can actually produce
       * right now.
       *
       * The parallel bus carries RGB888 either way; what changes is what the
       * camera puts in it. In colour mode the three bytes are a palette
       * rendering, and reading them as RAW14 would yield nonsense -- so Y14
       * must not even be advertised. In pseudo-mono mode the 14-bit value sits
       * in the low two bytes, and BOTH readings are legitimate: Y14 (the
       * bridge packs PD[13:0]) and RGB888 (the established mono-in-RGB
       * workflow, where userspace recombines the bytes).
       *
       * ENUM_FMT does not come from frmfmt_table: find_matching_color_fmt()
       * in camera_common.c walks sensor_props.num_modes, i.e. the device-tree
       * modes. The Y14 modes are declared LAST in every Dione DT node -- for
       * the PRISTINE_KERNEL guard -- so dropping the count to the RGB888 half
       * hides them with no renumbering and nothing else to touch. Both are
       * per-instance copies made by tegracam_device_register(), so two Dione
       * cameras in different states each get the right list.
       */
      if (tc_dev->s_data->sensor_props.num_modes >
                  DIONE_IR_NUM_RGB888_MODES &&
            priv->cam_pixfmt != DIONE_IR_PIXFMT_MONO16) {
         dev_info(dev, "camera is not in pseudo-mono: offering RGB888 only "
               "(%u of %u DT modes)\n", DIONE_IR_NUM_RGB888_MODES,
               tc_dev->s_data->sensor_props.num_modes);
         tc_dev->s_data->sensor_props.num_modes = DIONE_IR_NUM_RGB888_MODES;
      }
   }

   if (err) {
      if (tc_dev)
         tegracam_device_unregister(tc_dev);
      tc_dev = NULL;
   }

   if (!test_mode && priv->fpga_client != NULL) {
      i2c_unregister_device(priv->fpga_client);
      priv->fpga_client = NULL;
   }

   return tc_dev;
}

static ssize_t model_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->model);
}
static DEVICE_ATTR_RO(model);

static ssize_t serial_number_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->serial_number);
}
static DEVICE_ATTR_RO(serial_number);

static ssize_t resolution_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%ux%u\n",
         priv->native_width, priv->native_height);
}
static DEVICE_ATTR_RO(resolution);

static ssize_t pixel_format_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);

   /* Follow what V4L2 actually negotiated rather than assuming RGB888: with a
    * RAW14 device-tree mode the bridge packs the camera's 14 bits as CSI-2
    * RAW14 (dt 0x2D) and the fourcc is Y14, not a 32-bit RGB one. */
   if (s_data && s_data->colorfmt &&
       s_data->colorfmt->pix_fmt == V4L2_PIX_FMT_Y14)
      return scnprintf(buf, PAGE_SIZE, "'Y14 ' (14-bit Greyscale)\n");

   /* Dione always transmits RGB888 over CSI-2 (see tc358746_calculation.c) —
    * what varies is which V4L2 fourcc gets used to report it: AB24 on L4T
    * versions where EG_RGB888_AB24 is defined (36.x+/39.x, see the i2c
    * Makefile), AR24 everywhere else — including L4T 35.4.1-35.6.4, where
    * NVIDIA's own vi5_formats.h natively moved to RGBA32-only but EG
    * re-adds ABGR32 because gst-plugins-good 1.16.3 (JetPack 5.x) doesn't
    * recognize the RGBA32 V4L2 fourcc at all (see vi5_formats_mbus_fix.md
    * in shared memory). */
#ifdef EG_RGB888_AB24
   return scnprintf(buf, PAGE_SIZE, "'AB24' (32-bit RGBA 8-8-8-8)\n");
#else
   return scnprintf(buf, PAGE_SIZE, "'AR24' (32-bit BGRA 8-8-8-8)\n");
#endif
}
static DEVICE_ATTR_RO(pixel_format);

/*
 * Every pixel format this camera can be switched into without reloading the
 * module, one per line, in the same shape as pixel_format -- of which this is
 * the superset, pixel_format still meaning "the one it is in right now".
 *
 * Published only where the device tree actually declares a Y14 mode: on L4T
 * 32.x platforms it does not (no 14-bit greyscale in their VI format tables),
 * and a reader that finds no pixel_formats correctly concludes the camera has
 * a single fixed format. Same contract as ilumos.c.
 */
static ssize_t pixel_formats_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   unsigned int m;
   bool has_y14 = false;

   for (m = 0; s_data && m < s_data->sensor_props.num_modes; m++)
      if (s_data->sensor_props.sensor_modes[m].image_properties.pixel_format
            == V4L2_PIX_FMT_Y14) {
         has_y14 = true;
         break;
      }

   if (!has_y14)
      return 0;

#ifdef EG_RGB888_AB24
   return scnprintf(buf, PAGE_SIZE, "%s\n%s\n",
         "'AB24' (32-bit RGBA 8-8-8-8)", "'Y14 ' (14-bit Greyscale)");
#else
   return scnprintf(buf, PAGE_SIZE, "%s\n%s\n",
         "'AR24' (32-bit BGRA 8-8-8-8)", "'Y14 ' (14-bit Greyscale)");
#endif
}
static DEVICE_ATTR_RO(pixel_formats);

static ssize_t firmware_version_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->firmware_version);
}
static DEVICE_ATTR_RO(firmware_version);

#ifdef DIONE_IR_HAS_SYSFS_RESTART_MIPI
static ssize_t restart_mipi_store(struct device *dev,
      struct device_attribute *attr,
      const char *buf, size_t count)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;
   int cmd;

   if ((sscanf(buf, "%x", &cmd) == 1) && (cmd == 1)) {
      dione_ir_stop_streaming(priv->tc_dev);
      msleep(1000);
      dione_ir_set_mode(priv->tc_dev);
      dione_ir_start_streaming(priv->tc_dev);
   }

   return count;
}
static DEVICE_ATTR_WO(restart_mipi);
#endif

static int dione_ir_parse_fpga_address(struct i2c_client *client,
      struct dione_ir *priv)
{
   struct device_node *node = client->dev.of_node;
   int len;

   if (!of_get_property(node, "fpga-address", &len)) {
      dev_err(&client->dev,
            "fpga-address property not found or too many\n");
      return -EINVAL;
   }

   priv->fpga_address = devm_kzalloc(&client->dev, len, GFP_KERNEL);
   if (!priv->fpga_address)
      return -ENOMEM;

   priv->fpga_address_num = len / sizeof(*priv->fpga_address);

   return of_property_read_u32_array(node, "fpga-address",
         priv->fpga_address,
         priv->fpga_address_num);
}

static int dione_ir_parse_link_frequencies(struct i2c_client *client,
      struct dione_ir *priv)
{
   struct device_node *node;
   int len;

   node = of_graph_get_next_endpoint(client->dev.of_node, NULL);
   if (!node)
      return -EINVAL;

   if (!of_get_property(node, "link-frequencies", &len)) {
      dev_err(&client->dev,
            "link-frequencies property not found or too many\n");
      of_node_put(node);
      return -ENODATA;
   }

   priv->link_frequencies = devm_kzalloc(&client->dev, len, GFP_KERNEL);
   if (!priv->link_frequencies) {
      of_node_put(node);
      return -ENOMEM;
   }

   if (link_frequency == 0)
   {
      priv->link_frequencies_num = len / sizeof(*priv->link_frequencies);
      return of_property_read_u64_array(node, "link-frequencies",
            priv->link_frequencies,
            priv->link_frequencies_num);
   }
   else
   {
      priv->link_frequencies_num = 1;
      priv->link_frequencies[0] = link_frequency;
      return 0;
   }
}

#if defined(NV_I2C_DRIVER_STRUCT_PROBE_WITHOUT_I2C_DEVICE_ID_ARG) /* Linux 6.3 */
static int dione_ir_probe(struct i2c_client *client)
#else
static int dione_ir_probe(struct i2c_client *client,
      const struct i2c_device_id *id)
#endif
{
   struct device *dev = &client->dev;
   struct tegracam_device *tc_dev;
   struct dione_ir *priv;
   int err;

   dev_dbg(dev, "probing v4l2 sensor at addr %#02x\n", client->addr);

   /* Hiding the Y14 modes assumes they come after the RGB888 ones and that the
    * count is right. Break the build rather than mis-truncate if a resolution
    * is ever added without updating the constant. */
   BUILD_BUG_ON(DIONE_IR_MODE_640x480_60FPS_Y14 != DIONE_IR_NUM_RGB888_MODES);

   if (!IS_ENABLED(CONFIG_OF) || !dev->of_node)
      return -EINVAL;

   priv = devm_kzalloc(dev, sizeof(struct dione_ir), GFP_KERNEL);
   if (!priv)
      return -ENOMEM;

   err = dione_ir_parse_fpga_address(client, priv);
   if (err < 0)
      return err;

   err = dione_ir_parse_link_frequencies(client, priv);
   if (err < 0)
      return err;

   priv->tc35_client = client;
   if (test_mode)
      quick_mode = 1;

   tc_dev = dione_ir_probe_sensor(priv);
   if (!tc_dev) {
      if (!priv->tc35_found && !priv->fpga_found)
         dev_err(dev, "no dione-ir sensor found\n");
      else if (priv->tc35_found && !priv->fpga_found)
         dev_err(dev, "no fpga found, please install it\n");
      else
         dev_err(dev, "dione-ir probe error\n");
      return -ENODEV;
   }

   /* tegracam_device_register() hard-codes mode_idx=0 (640x480) as the
    * default. dione_ir_probe_sensor() -> dione_ir_board_setup() ->
    * detect_dione_ir() has already detected the ACTUAL connected variant
    * into priv->mode (e.g. 1 for a 1280x1024 "Dione 1280" module) — but
    * nothing before this point ever propagates that into s_data's
    * def_mode/def_width/def_height/fmt_width/fmt_height. Left unset, the
    * bind-time s_fmt in camera_common_try_fmt() stays on mode0 regardless
    * of what width/height userspace later requests via S_FMT (confirmed:
    * dione_ir_set_mode() sees s_data->mode=0/fmt_width=640/fmt_height=480
    * even after requesting 1280x1024, silently failing the s_data->mode
    * != priv->mode check). Same fix already applied in eg_ec_mipi_src.c
    * for the same reason — set it here too, before v4l2 registration.
    */
   if (priv->mode >= 0 && priv->mode < ARRAY_SIZE(dione_ir_frmfmt)) {
      tc_dev->s_data->def_mode = dione_ir_frmfmt[priv->mode].mode;
      tc_dev->s_data->def_width = tc_dev->s_data->fmt_width =
            dione_ir_frmfmt[priv->mode].size.width;
      tc_dev->s_data->def_height = tc_dev->s_data->fmt_height =
            dione_ir_frmfmt[priv->mode].size.height;

      /*
       * ⚠️ This camera's resolution is the only one it can produce, but we
       * CANNOT restrict what is advertised by trimming s_data->frmfmt /
       * numfmts. Tried on 2026-09-07: streaming stopped completely, both
       * formats, 0 frames.
       *
       * Reason: the framework sets s_data->mode_prop_idx to the INDEX in
       * frmfmt where the resolution matched, and then uses that same number to
       * index the device-tree modes -- csi.c:320 reads
       * sensor_modes[mode_prop_idx].signal_properties.pixel_clock to program
       * the NVCSI link rate, and csi.c:149 reads mipi_clock the same way. With
       * a one-entry table the index collapses to 0, i.e. device-tree mode0
       * (640x480), so the CSI is set up for the wrong link frequency and every
       * frame is discarded. frmfmt[i] must stay aligned with mode i.
       *
       * Consequence to know: the driver advertises every Dione model's
       * resolution, so an application that asks for one this camera does not
       * have gets it accepted and then fails at stream start. Tools we ship
       * must not hardcode a resolution -- rt_frame_monitor.py defaulted to
       * 640x480 and failed on every Dione but the 640 for exactly this reason.
       */
   }

   err = tegracam_v4l2subdev_register(tc_dev, true);
   if (err) {
      dev_err(dev, "tegra camera subdev registration failed\n");
      tegracam_device_unregister(tc_dev);
      return err;
   }

   dev_info(dev, "detected dione-ir sensor%s%s%s%s\n",
         priv->reva ? " (reva)" : "",
         test_mode || quick_mode ? ", mode:" : "",
         test_mode ? " test" : "",
         quick_mode ? " quick" : "");

   device_create_file(dev, &dev_attr_model);
   device_create_file(dev, &dev_attr_serial_number);
   device_create_file(dev, &dev_attr_resolution);
   device_create_file(dev, &dev_attr_pixel_format);
   device_create_file(dev, &dev_attr_pixel_formats);
   device_create_file(dev, &dev_attr_firmware_version);
#ifdef DIONE_IR_HAS_SYSFS_RESTART_MIPI
   device_create_file(dev, &dev_attr_restart_mipi);
#endif

   return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
static int dione_ir_remove(struct i2c_client *client)
#else
static void dione_ir_remove(struct i2c_client *client)
#endif
{
   struct device *dev = &client->dev;
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct dione_ir *priv = (struct dione_ir *)s_data->priv;
   int i;

   tegracam_v4l2subdev_unregister(priv->tc_dev);
   tegracam_device_unregister(priv->tc_dev);

   for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
   {
      if (i2c_clients[i].chnod_name[0] != 0)
      {
         if(i2c_clients[i].chnod_major_number != 0)
         {
            device_destroy(i2c_clients[i].pClass_chnod, i2c_clients[i].chnod_device_number);
            class_destroy(i2c_clients[i].pClass_chnod);
            unregister_chrdev(i2c_clients[i].chnod_major_number, i2c_clients[i].chnod_name);
         }
         dev_info(dev, "Removed %s device\n", i2c_clients[i].chnod_name);
         i2c_clients[i].i2c_client = NULL;
         i2c_clients[i].chnod_name[0] = 0;
         break;
      }
   }

#ifdef DIONE_IR_HAS_SYSFS_RESTART_MIPI
   device_remove_file(dev, &dev_attr_restart_mipi);
#endif
   device_remove_file(dev, &dev_attr_firmware_version);
   device_remove_file(dev, &dev_attr_pixel_formats);
   device_remove_file(dev, &dev_attr_pixel_format);
   device_remove_file(dev, &dev_attr_resolution);
   device_remove_file(dev, &dev_attr_serial_number);
   device_remove_file(dev, &dev_attr_model);

#if LINUX_VERSION_CODE <= KERNEL_VERSION(6,1,1)
   return 0;
#endif
}

static const struct i2c_device_id dione_ir_id[] = {
   { "dioneir", 0 },
   { }
};
MODULE_DEVICE_TABLE(i2c, dione_ir_id);

static struct i2c_driver dione_ir_i2c_driver = {
   .driver = {
      .name = "dioneir",
      .owner = THIS_MODULE,
      .of_match_table = of_match_ptr(dione_ir_of_match),
   },
   .probe = dione_ir_probe,
   .remove = dione_ir_remove,
   .id_table = dione_ir_id,
};
module_i2c_driver(dione_ir_i2c_driver);

MODULE_DESCRIPTION("Media Controller driver for Xenics Dione IR sensors");
MODULE_AUTHOR("Exosens");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");
