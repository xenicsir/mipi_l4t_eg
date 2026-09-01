/*
 * A V4L2 driver for Exosens ilumos MIPI IR cameras.
 *
 * Based on Sony imx219 NVIDIA camera driver
 * Copyright (C) 2026 Exosens
 *
 */

#include <linux/i2c.h>
#include <linux/i2c-mux.h>
#include <linux/miscdevice.h>
#include <linux/of_device.h>
#include <linux/gpio.h>
#include <linux/of_gpio.h>
#include <linux/uaccess.h>
#include <linux/version.h>
#include <linux/delay.h>
#include <media/tegracam_core.h>

/* ilumos GenCP registers */
#define REG_ACQ_START_W   0x50000A00
#define REG_ACQ_STATUS_R  0x50000A20
#define REG_FIRW_VER_R    0x10000000
#define REG_SERIAL_R      0x00144
#define REG_MODEL_NAME_R  0x00044
#define REG_IMG_HEIGHT_R  0x50000004
#define REG_IMG_WIDTH_R   0x50000000 
#
/* Crosslink bridge register interface */
#define REG_CROSSLINK_ADDR          0x50000C00
#define REG_CROSSLINK_DATA          0x50000C04
#define REG_CROSSLINK_R_WR_CMD      0x50000C08

#define REG_CROSSLINK_FW_VERSION    0x0
#define REG_CROSSLINK_DEBUG_ENABLE  0x1
#define REG_CROSSLINK_PIXEL_FORMAT  0x2
#define REG_CROSSLINK_LINE_LENGTH   0x3
#define REG_CROSSLINK_FIFO_STATUS   0x7
#define REG_CROSSLINK_FRAME_COUNTER 0x8
#define REG_CROSSLINK_FRAME_SIZE    0x9

#define READ_CROSSLINK      0x1
#define WRITE_CROSSLINK     0x0

#define PIXEL_FORMAT_MONO16 0x2E
#define PIXEL_FORMAT_MONO14 0x2D

#define ILUMOS_STR_MAX    256

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
 */
#define ILUMOS_PROBE_TIMEOUT_MS_DEFAULT  0
#define ILUMOS_PROBE_RETRY_MS            200

/* Attempts to make for a given timeout: always at least one. */
static unsigned int ilumos_probe_attempts(struct device *dev)
{
   u32 ms = ILUMOS_PROBE_TIMEOUT_MS_DEFAULT;

   if (dev->of_node)
      of_property_read_u32(dev->of_node, "exosens,probe-timeout-ms", &ms);

   return ms / ILUMOS_PROBE_RETRY_MS + 1;
}

/*
 * Every answer from the camera -- to a read as well as to a write -- starts
 * with a 2-byte status word, little endian. Zero means the request was
 * carried out; the error codes are the GenCP ones (0x8003 = address the
 * camera does not implement, and so on).
 */
#define ILUMOS_STATUS_OK  0x0000
#define ILUMOS_STATUS_BUSY   0xFFFF

/* ---- ioctl interface (/dev/ilumos-<bus>-<addr>) ------------------------- */

/**
 * struct ilumos_reg_op - ioctl payload for 32-bit register read/write
 * @addr: register address
 * @val:  value written (WRITE_REG) or value returned (READ_REG)
 */
struct ilumos_reg_op {
   __u32 addr;
   __u32 val;
};

/**
 * struct ilumos_str_op - ioctl payload for string read
 * @addr: register address of the string
 * @len:  number of bytes to read (clamped to ILUMOS_STR_MAX)
 * @buf:  buffer filled with the string data on return
 */
struct ilumos_str_op {
   __u32 addr;
   __u32 len;
   __u8  buf[ILUMOS_STR_MAX];
};

#define ILUMOS_IOCTL_MAGIC    'I'
#define ILUMOS_IOCTL_READ_REG  _IOWR(ILUMOS_IOCTL_MAGIC, 1, struct ilumos_reg_op)
#define ILUMOS_IOCTL_WRITE_REG _IOW (ILUMOS_IOCTL_MAGIC, 2, struct ilumos_reg_op)
#define ILUMOS_IOCTL_READ_STR  _IOWR(ILUMOS_IOCTL_MAGIC, 3, struct ilumos_str_op)

static const struct of_device_id ilumos_of_match[] = {
   { .compatible = "exosens,ilumos", },
   { },
};
MODULE_DEVICE_TABLE(of, ilumos_of_match);

enum {
   ILUMOS_MODE_2048x2048_RAW16_BE,
   ILUMOS_MODE_2048x1088_RAW16_BE,
   ILUMOS_MODE_1280x1024_RAW16_BE,
   ILUMOS_MODE_2048x2048_RAW14,
   ILUMOS_MODE_2048x1088_RAW14,
   ILUMOS_MODE_1280x1024_RAW14,
};

static const int ilumos_60fps[] = {
   60,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
static const struct camera_common_frmfmt ilumos_frmfmt[] = {
   {{2048, 2048}, ilumos_60fps, 1, 0, ILUMOS_MODE_2048x2048_RAW16_BE},
   {{2048, 1088}, ilumos_60fps, 1, 0, ILUMOS_MODE_2048x1088_RAW16_BE},
   {{1280, 1024}, ilumos_60fps, 1, 0, ILUMOS_MODE_1280x1024_RAW16_BE},
   {{2048, 2048}, ilumos_60fps, 1, 0, ILUMOS_MODE_2048x2048_RAW14},
   {{2048, 1088}, ilumos_60fps, 1, 0, ILUMOS_MODE_2048x1088_RAW14},
   {{1280, 1024}, ilumos_60fps, 1, 0, ILUMOS_MODE_1280x1024_RAW14},
};

static int ilumos_find_frmfmt(u32 width, u32 height)
{
   u32 i;

   for (i = 0; i < ARRAY_SIZE(ilumos_frmfmt); i++) {
      const struct camera_common_frmfmt *fmt = ilumos_frmfmt + i;

      if (fmt->size.width == width && fmt->size.height == height)
         return i;
   }

   return -1;
}


static const u32 ctrl_cid_list[] = {
#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
   TEGRA_CAMERA_CID_GAIN,
   TEGRA_CAMERA_CID_EXPOSURE,
   TEGRA_CAMERA_CID_FRAME_RATE,
#endif
   TEGRA_CAMERA_CID_SENSOR_MODE_ID,
};

struct ilumos {
   struct i2c_client    *i2c_client;
   struct v4l2_subdev      *subdev;
   struct camera_common_data  *s_data;
   struct tegracam_device     *tc_dev;

   char        model[64];
   char        serial_number[64];
   char        firmware_version[64];
   char        pixel_format[64];
   u32         native_width;
   u32         native_height;

   /* chardev — /dev/ilumos-<bus>-<addr> */
   struct miscdevice miscdev;
   char              miscdev_name[32];
};

static int ilumos_i2c_read_register(struct i2c_client *client, u32 reg, u8 *dst, u16 len)
{
   struct i2c_msg msgs[2];
   u8 tx_data[6];
   u8 rx_data[72];
   int ret = 0;

   if (len > sizeof(rx_data) - 2)
      ret = -EINVAL;

   if (!ret) {
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

      if (i2c_transfer(client->adapter, msgs, ARRAY_SIZE(msgs)) != 2)
         ret = -EIO;
   }

   if (!ret) {
      if (rx_data[0] != 0 || rx_data[1] != 0) {
         ret = -EINVAL;
      } else {
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
      }
   }

   return ret;
}

static int ilumos_i2c_write_register(struct i2c_client *client, u32 reg, u32 val)
{
   struct i2c_msg msgs[2];
   u8 tx_data[10];
   u8 rx_data[2];
   u16 status;

   *(u32 *)tx_data = cpu_to_le32(reg);
   *(u16 *)(tx_data + 4) = cpu_to_le16(4);
   *(u32 *)(tx_data + 6) = cpu_to_le32(val);

   msgs[0].addr = client->addr;
   msgs[0].flags = 0;
   msgs[0].len = sizeof(tx_data);
   msgs[0].buf = tx_data;

   /*
    * Read the status back. It used to be left on the bus, so this function
    * returned success whatever the camera made of the request: a write to the
    * read-only width register and a write to an address the camera does not
    * implement both reported success, while the *read* of that same address
    * correctly failed.
    *
    * Fetched in the same combined transfer as the write, for two reasons
    * measured on 35.6.0 (2026-08-31, iLumos 10-0030): the status is ready
    * with no delay -- a separate immediate read already returns 0x8003 for a
    * bad address, never 0xFFFF -- and a combined transfer cannot be split by
    * another caller of this function, which matters because the chardev and
    * the streaming path share it without a lock.
    */
   msgs[1].addr = client->addr;
   msgs[1].flags = I2C_M_RD;
   msgs[1].len = sizeof(rx_data);
   msgs[1].buf = rx_data;

   if (i2c_transfer(client->adapter, msgs, ARRAY_SIZE(msgs)) != 2)
      return -EIO;

   status = rx_data[0] | (rx_data[1] << 8);
   if (status == ILUMOS_STATUS_BUSY)
      return -EBUSY;

   if (status != ILUMOS_STATUS_OK) {
      dev_err_ratelimited(&client->dev,
                          "write of 0x%08x to 0x%08x refused, status 0x%04x\n",
                          val, reg, status);
      return -EINVAL;
   }

   return 0;
}


static int ilumos_i2c_read_crosslink_register(struct i2c_client *client,
                                              u32 reg, u32 *val)
{
   int ret;

   ret = ilumos_i2c_write_register(client, REG_CROSSLINK_ADDR, reg);
   if (ret)
      return ret;

   ret = ilumos_i2c_write_register(client, REG_CROSSLINK_R_WR_CMD,
                                   READ_CROSSLINK);
   if (ret)
      return ret;

   return ilumos_i2c_read_register(client, REG_CROSSLINK_DATA,
                                   (u8 *)val, sizeof(*val));
}

/*
static int ilumos_i2c_write_crosslink_register(struct i2c_client *client, u32 reg, u32 val)
{
   int ret;

   ret = ilumos_i2c_write_register(client, REG_CROSSLINK_ADDR, reg);
   if (ret)
      return ret;

   ret = ilumos_i2c_write_register(client, REG_CROSSLINK_DATA, val);
   if (ret)
      return ret;

   return ilumos_i2c_write_register(client, REG_CROSSLINK_R_WR_CMD,
                                   WRITE_CROSSLINK);
}
*/
static int ilumos_i2c_read_string(struct i2c_client *client, u32 reg,
                                  u8 *buf, u16 len)
{
   if (len > ILUMOS_STR_MAX)
      return -EINVAL;
   return ilumos_i2c_read_register(client, reg, buf, len);
}

/* ---- chardev file operations ------------------------------------------ */

static int ilumos_cdev_open(struct inode *inode, struct file *file)
{
   struct ilumos *priv =
      container_of(file->private_data, struct ilumos, miscdev);
   file->private_data = priv;
   return 0;
}

static int ilumos_cdev_release(struct inode *inode, struct file *file)
{
   return 0;
}

static long ilumos_cdev_ioctl(struct file *file, unsigned int cmd,
                              unsigned long arg)
{
   struct ilumos *priv = file->private_data;
   int ret = 0;

   switch (cmd) {
   case ILUMOS_IOCTL_READ_REG: {
      struct ilumos_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = ilumos_i2c_read_register(priv->i2c_client, op.addr,
                                     (u8 *)&op.val, sizeof(op.val));
      if (ret == 0 && copy_to_user((void __user *)arg, &op, sizeof(op)))
         ret = -EFAULT;
      break;
   }
   case ILUMOS_IOCTL_WRITE_REG: {
      struct ilumos_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = ilumos_i2c_write_register(priv->i2c_client, op.addr, op.val);
      break;
   }
   case ILUMOS_IOCTL_READ_STR: {
      struct ilumos_str_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      op.len = min_t(u32, op.len, ILUMOS_STR_MAX);
      ret = ilumos_i2c_read_string(priv->i2c_client, op.addr,
                                   op.buf, op.len);
      if (ret == 0 && copy_to_user((void __user *)arg, &op, sizeof(op)))
         ret = -EFAULT;
      break;
   }
   default:
      ret = -ENOTTY;
      break;
   }

   return ret;
}

static const struct file_operations ilumos_cdev_fops = {
   .owner          = THIS_MODULE,
   .open           = ilumos_cdev_open,
   .release        = ilumos_cdev_release,
   .unlocked_ioctl = ilumos_cdev_ioctl,
};

static int ilumos_sensor_check(struct ilumos *priv)
{
   struct device *dev = &priv->i2c_client->dev;
   int i, mode;
   u8 buf[64];
   u32 read_data;
   u32 width, height;
   bool is_raw14 = false;

   /*
    * First access to the camera: retry while it boots. See the budget above.
    * A retry that was actually needed is reported, so a late power rail or a
    * late reset stays visible instead of turning into a silent boot delay.
    */
   {
      unsigned int attempts = ilumos_probe_attempts(dev);
      unsigned int attempt;
      int rc = -EIO;

      for (attempt = 0; attempt < attempts; attempt++) {
         rc = ilumos_i2c_read_string(priv->i2c_client, REG_FIRW_VER_R,
                                     buf, sizeof(buf));
         if (rc == 0)
            break;
         if (attempt + 1 < attempts)   /* no wait after the last try */
            msleep(ILUMOS_PROBE_RETRY_MS);
      }
      if (rc == 0 && attempt)
         dev_warn(dev, "camera answered only after %u ms (%u retries) -- "
                  "it was still booting when the driver probed\n",
                  attempt * ILUMOS_PROBE_RETRY_MS, attempt);
   }

   /* FPGA firmware version */
   if (ilumos_i2c_read_string(priv->i2c_client, REG_FIRW_VER_R,
                              buf, sizeof(buf)) == 0) {
      for (i = sizeof(buf) - 1; i >= 0 && buf[i] == (u8)0xff; i--)
         buf[i] = '\0';
      strncpy(priv->firmware_version, buf, sizeof(priv->firmware_version) - 1);
      priv->firmware_version[sizeof(priv->firmware_version) - 1] = '\0';
      dev_info(dev, "FPGA firmware version = %s\n", priv->firmware_version);
   } else {
      dev_err(dev, "FPGA firmware read failed\n");
      goto error_exit;
   }

   /* Pixel format via Crosslink */
   if (ilumos_i2c_read_crosslink_register(priv->i2c_client,
                                          REG_CROSSLINK_PIXEL_FORMAT,
                                          &read_data) == 0) {
      if (read_data == PIXEL_FORMAT_MONO14) {
         is_raw14 = true;
         dev_info(dev, "PIXEL_FORMAT = 0x%08x (RAW14)\n", read_data);
      } else {
         dev_info(dev, "PIXEL_FORMAT = 0x%08x (RAW16)\n", read_data);
      }
   } else {
      dev_warn(dev, "PIXEL_FORMAT read failed, assuming RAW16\n");
   }
   /* Read Width and Height via Crosslink FRAME_SIZE */
/*
   if (ilumos_i2c_read_crosslink_register(priv->i2c_client,
                                          REG_CROSSLINK_FRAME_SIZE,
                                          &read_data) != 0) {
      dev_err(dev, "Crosslink FRAME_SIZE read failed\n");
      
      if (ilumos_i2c_read_register(priv->i2c_client, REG_IMG_WIDTH_R,
                                   (u8 *)&width, sizeof(width)) == 0) {
         if (ilumos_i2c_read_register(priv->i2c_client, REG_IMG_HEIGHT_R,
                                      (u8 *)&height, sizeof(height)) == 0) {
         } else {
            dev_warn(dev, "failed to read height\n");
            goto error_exit;
         }
      } else {
         dev_warn(dev, "failed to read width\n");
         goto error_exit;
      }
   }
   else
   {
      width = read_data & 0xFFFF;
      height = read_data >> 16;
   }
*/

   if (ilumos_i2c_read_register(priv->i2c_client, REG_IMG_WIDTH_R,
                                (u8 *)&width, sizeof(width)) == 0) {
      if (ilumos_i2c_read_register(priv->i2c_client, REG_IMG_HEIGHT_R,
                                   (u8 *)&height, sizeof(height)) == 0) {
      } else {
         dev_err(dev, "Failed to read height\n");
         goto error_exit;
      }
   } else {
      dev_err(dev, "Failed to read width\n");
      goto error_exit;
   }

//   width  = 2048;
//   height = 2048;
   dev_info(dev, "Frame width = %u px\n", width);
   dev_info(dev, "Frame height = %u px\n", height);


   /* ilumos_frmfmt: indices 0-2 = RAW16, indices 3-5 = RAW14 (same resolutions) */
   mode = ilumos_find_frmfmt(width, height);
   if (mode < 0) {
      dev_err(dev, "unsupported resolution %ux%u\n", width, height);
      goto error_exit;
   }
   if (is_raw14)
      mode += 3;

   priv->tc_dev->s_data->sensor_mode_id = mode;
   priv->tc_dev->s_data->def_mode       = mode;
   /* Sync the V4L2 format to the camera's actual native resolution.
    * tegracam_device_register() always initialises fmt from frmfmt[0]
    * (2048x2048), so without this correction GStreamer probes 2048x2048
    * even when the camera reports 1280x1024 or 2048x1088. */
   priv->tc_dev->s_data->def_width  = width;
   priv->tc_dev->s_data->def_height = height;
   priv->tc_dev->s_data->fmt_width  = width;
   priv->tc_dev->s_data->fmt_height = height;
   /* tegracam_device_register() set colorfmt from frmfmt[0]; updating def_mode
    * does not re-resolve it. Same fix as microlynx_core.c. */
   {
      const struct camera_common_colorfmt *colorfmt;
      u32 v4l2_pixfmt = is_raw14 ? V4L2_PIX_FMT_Y14 : V4L2_PIX_FMT_Y16_BE;

      colorfmt = camera_common_find_pixelfmt(v4l2_pixfmt);
      if (colorfmt)
         priv->tc_dev->s_data->colorfmt = colorfmt;
      else
         dev_warn(dev, "no colorfmt entry for 0x%08x, V4L2 will report the default\n",
                  v4l2_pixfmt);
   }

   if (is_raw14)
      strncpy(priv->pixel_format, "'Y14 ' (14-bit Greyscale)",
              sizeof(priv->pixel_format) - 1);
   else
      strncpy(priv->pixel_format, "'Y16 -BE' (16-bit Greyscale Big Endian)",
              sizeof(priv->pixel_format) - 1);
   priv->pixel_format[sizeof(priv->pixel_format) - 1] = '\0';

   dev_info(dev, "mode=%d  pixel_format=%s\n", mode, priv->pixel_format);

   priv->native_width  = width;
   priv->native_height = height;

   /* Model name */
   if (ilumos_i2c_read_string(priv->i2c_client, REG_MODEL_NAME_R,
                                (u8 *)priv->model, sizeof(priv->model)) == 0) {
      for (i = sizeof(priv->model) - 1; i >= 0 &&
            (priv->model[i] == (char)0xff || priv->model[i] == '\0'); i--)
         priv->model[i] = '\0';
   } else {
      priv->model[0] = '\0';
      dev_warn(dev, "failed to read model name\n");
   }

   /* Serial number */
   if (ilumos_i2c_read_string(priv->i2c_client, REG_SERIAL_R,
                                (u8 *)priv->serial_number,
                                sizeof(priv->serial_number)) == 0) {
      for (i = sizeof(priv->serial_number) - 1; i >= 0 &&
            (priv->serial_number[i] == (char)0xff ||
             priv->serial_number[i] == '\0'); i--)
         priv->serial_number[i] = '\0';
   } else {
      priv->serial_number[0] = '\0';
      dev_warn(dev, "failed to read serial number\n");
   }

   // Stop the video streaming by default
   dev_dbg(dev, "%s Stop streaming\n", __func__);
   ilumos_i2c_write_register(priv->i2c_client, REG_ACQ_START_W, 2);

   return 0;

error_exit:
   dev_err(dev, "Probing failed\n");
   return -EIO;
}

static int ilumos_set_group_hold(struct tegracam_device *tc_dev, bool val)
{
   /* group hold is not supported */
   dev_dbg(tc_dev->dev, "%s val=%d\n", __func__, val);
   return 0;
}

#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
static int ilumos_set_gain(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int ilumos_set_frame_rate(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int ilumos_set_exposure(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}
#endif

static struct tegracam_ctrl_ops ilumos_ctrl_ops = {
   .numctrls = ARRAY_SIZE(ctrl_cid_list),
   .ctrl_cid_list = ctrl_cid_list,
#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
   .set_gain = ilumos_set_gain,
   .set_exposure = ilumos_set_exposure,
   .set_frame_rate = ilumos_set_frame_rate,
#endif
   .set_group_hold = ilumos_set_group_hold,
};

static int ilumos_power_on(struct camera_common_data *s_data)
{
   /* Power is not managed here */
   struct device *dev = s_data->dev;
   dev_dbg(dev, "%s\n", __func__);
   return 0;
}

static int ilumos_power_off(struct camera_common_data *s_data)
{
   /* Power is not managed here */
   struct device *dev = s_data->dev;
   dev_dbg(dev, "%s\n", __func__);
   return 0;
}

static int ilumos_power_put(struct tegracam_device *tc_dev)
{
   /* Power is not managed here */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static int ilumos_power_get(struct tegracam_device *tc_dev)
{
   /* Power is not managed here */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static struct camera_common_pdata *ilumos_parse_dt(
      struct tegracam_device *tc_dev)
{
   struct device *dev = tc_dev->dev;
   struct device_node *np = dev->of_node;
   struct camera_common_pdata *board_priv_pdata;
   const struct of_device_id *match;

   if (!np)
      return NULL;

   match = of_match_device(ilumos_of_match, dev);
   if (!match) {
      dev_err(dev, "Failed to find matching dt id\n");
      return NULL;
   }

   /* Just need to allocate data for tegra registration */
   board_priv_pdata = devm_kzalloc(dev,
         sizeof(*board_priv_pdata), GFP_KERNEL);
   if (!board_priv_pdata)
      return NULL;

   return board_priv_pdata;
}

static int ilumos_set_mode(struct tegracam_device *tc_dev)
{
   /* Configuration is done independently by a control application */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static int ilumos_start_streaming(struct tegracam_device *tc_dev)
{
   struct ilumos *priv = tegracam_get_privdata(tc_dev);
   int status = 0;
   u32 read_data;

   dev_dbg(tc_dev->dev, "%s\n", __func__);

   status = ilumos_i2c_read_register(priv->i2c_client, REG_ACQ_STATUS_R,
         (u8 *)&read_data, sizeof(read_data));
   dev_dbg(tc_dev->dev, "%s Lecture REG_ACQ_STATUS_R = %d\n", __func__, read_data);
   if (status == 0) {
      if (read_data != 0x1) {
         status = ilumos_i2c_write_register(priv->i2c_client, REG_ACQ_START_W, 1);
      }
   } else {
      dev_err(tc_dev->dev, "%s : Register read failed\n", __func__);
   }

   return 0;
}

static int ilumos_stop_streaming(struct tegracam_device *tc_dev)
{
   struct ilumos *priv = tegracam_get_privdata(tc_dev);
   dev_dbg(tc_dev->dev, "%s\n", __func__);

   ilumos_i2c_write_register(priv->i2c_client, REG_ACQ_START_W, 2);
   /* let VI finish its last DMA before teardown (avoids SMMU context fault at stop) */
   msleep(50);

   return 0;
}

static struct camera_common_sensor_ops ilumos_common_ops = {
   .numfrmfmts = ARRAY_SIZE(ilumos_frmfmt),
   .frmfmt_table = ilumos_frmfmt,
   .power_on = ilumos_power_on,
   .power_off = ilumos_power_off,
   .parse_dt = ilumos_parse_dt,
   .power_get = ilumos_power_get,
   .power_put = ilumos_power_put,
   .set_mode = ilumos_set_mode,
   .start_streaming = ilumos_start_streaming,
   .stop_streaming = ilumos_stop_streaming,
};

static ssize_t model_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct ilumos *priv = (struct ilumos *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->model);
}
static DEVICE_ATTR_RO(model);

static ssize_t serial_number_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct ilumos *priv = (struct ilumos *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->serial_number);
}
static DEVICE_ATTR_RO(serial_number);

static ssize_t resolution_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct ilumos *priv = (struct ilumos *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%ux%u\n",
         priv->native_width, priv->native_height);
}
static DEVICE_ATTR_RO(resolution);

static ssize_t pixel_format_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct ilumos *priv = (struct ilumos *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->pixel_format);
}
static DEVICE_ATTR_RO(pixel_format);

static ssize_t firmware_version_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct ilumos *priv = (struct ilumos *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->firmware_version);
}
static DEVICE_ATTR_RO(firmware_version);

static int ilumos_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
   return 0;
}

static const struct v4l2_subdev_internal_ops ilumos_subdev_internal_ops = {
   .open = ilumos_open,
};

/*
 * ilumos does raw i2c_master_send/recv via priv->i2c_client, never
 * regmap_read/write. This config only exists so tegracam_core's
 * devm_regmap_init_i2c() has a non-NULL config to work with on stock
 * NVIDIA/vendor kernels that don't carry the EG NULL-config guard.
 */
static const struct regmap_config ilumos_dummy_regmap_config = {
   .reg_bits = 8,
   .val_bits = 8,
};

#if defined(NV_I2C_DRIVER_STRUCT_PROBE_WITHOUT_I2C_DEVICE_ID_ARG) /* Linux 6.3 */
static int ilumos_probe(struct i2c_client *client)
#else
static int ilumos_probe(struct i2c_client *client,
      const struct i2c_device_id *id)
#endif
{
   struct device *dev = &client->dev;
   struct tegracam_device *tc_dev;
   struct ilumos *priv;
   int err;

   dev_info(dev, "probing v4l2 ilumos sensor at addr 0x%0x\n", client->addr);

   if (!IS_ENABLED(CONFIG_OF) || !client->dev.of_node)
      return -EINVAL;

   priv = devm_kzalloc(dev, sizeof(struct ilumos), GFP_KERNEL);
   if (!priv)
      return -ENOMEM;

   tc_dev = devm_kzalloc(dev, sizeof(struct tegracam_device), GFP_KERNEL);
   if (!tc_dev)
      return -ENOMEM;

   priv->i2c_client = tc_dev->client = client;
   tc_dev->dev = dev;
   strncpy(tc_dev->name, "ilumos", sizeof(tc_dev->name));
   tc_dev->dev_regmap_config = &ilumos_dummy_regmap_config;
   tc_dev->sensor_ops = &ilumos_common_ops;
   tc_dev->v4l2sd_internal_ops = &ilumos_subdev_internal_ops;
   tc_dev->tcctrl_ops = &ilumos_ctrl_ops;

   err = tegracam_device_register(tc_dev);
   if (err) {
      dev_err(dev, "tegra camera driver registration failed\n");
      return err;
   }

   priv->tc_dev = tc_dev;
   priv->s_data = tc_dev->s_data;
   priv->subdev = &tc_dev->s_data->subdev;
   tegracam_set_privdata(tc_dev, (void *)priv);

   /* Initialize sensor and check GenCP communication */
   err = ilumos_sensor_check(priv);
   if (err) {
      dev_err(dev, "sensor check failed\n");
      tegracam_device_unregister(tc_dev);
      return err;
   }

   err = tegracam_v4l2subdev_register(tc_dev, true);
   if (err) {
      dev_err(dev, "tegra camera subdev registration failed\n");
      tegracam_device_unregister(tc_dev);
      return err;
   }

   device_create_file(dev, &dev_attr_model);
   device_create_file(dev, &dev_attr_serial_number);
   device_create_file(dev, &dev_attr_resolution);
   device_create_file(dev, &dev_attr_pixel_format);
   device_create_file(dev, &dev_attr_firmware_version);

   /* Register chardev for userspace register access */
   snprintf(priv->miscdev_name, sizeof(priv->miscdev_name),
            "ilumos-%d-%04x", client->adapter->nr, client->addr);
   priv->miscdev.minor  = MISC_DYNAMIC_MINOR;
   priv->miscdev.name   = priv->miscdev_name;
   priv->miscdev.fops   = &ilumos_cdev_fops;
   priv->miscdev.parent = dev;
   if (misc_register(&priv->miscdev))
      dev_warn(dev, "failed to register chardev; ilumosCtrl will not work\n");
   else
      dev_info(dev, "chardev registered at /dev/%s\n", priv->miscdev_name);

   return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
static int ilumos_remove(struct i2c_client *client)
#else
static void ilumos_remove(struct i2c_client *client)
#endif
{
   struct device *dev = &client->dev;
   struct camera_common_data *s_data = to_camera_common_data(&client->dev);
   struct ilumos *priv = (struct ilumos *)s_data->priv;

   misc_deregister(&priv->miscdev);

   device_remove_file(dev, &dev_attr_firmware_version);
   device_remove_file(dev, &dev_attr_pixel_format);
   device_remove_file(dev, &dev_attr_resolution);
   device_remove_file(dev, &dev_attr_serial_number);
   device_remove_file(dev, &dev_attr_model);

   tegracam_v4l2subdev_unregister(priv->tc_dev);
   tegracam_device_unregister(priv->tc_dev);

   dev_info(dev, "Removed ilumos device\n");

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
   return 0;
#endif
}

static const struct i2c_device_id ilumos_id[] = {
   { "ilumos", 0 },
   { }
};
MODULE_DEVICE_TABLE(i2c, ilumos_id);

static struct i2c_driver ilumos_i2c_driver = {
   .driver = {
      .name = "ilumos",
      .owner = THIS_MODULE,
      .of_match_table = of_match_ptr(ilumos_of_match),
   },
   .probe = ilumos_probe,
   .remove = ilumos_remove,
   .id_table = ilumos_id,
};
module_i2c_driver(ilumos_i2c_driver);

MODULE_AUTHOR("Exosens");
MODULE_DESCRIPTION("Exosens MIPI camera I2C driver for iLumos cameras");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");
