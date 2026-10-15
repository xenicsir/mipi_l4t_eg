/*
 * A V4L2 driver for Exosens titan MIPI IR cameras.
 *
 * Based on Sony imx219 NVIDIA camera driver
 * Copyright (C) 2026 Exosens
 *
 */

#include <linux/i2c.h>
#include <linux/mutex.h>
#include <linux/kref.h>
#include <linux/compat.h>
#include <linux/i2c-mux.h>
#include <linux/miscdevice.h>
#include <linux/of_device.h>
#include <linux/gpio.h>
#include <linux/of_gpio.h>
#include <linux/uaccess.h>
#include <linux/version.h>
#include <linux/delay.h>
#include <media/tegracam_core.h>

#include "gencp-over-i2c/libunio.h"
#include "gencp-over-i2c/gencp_client.h"
#define PREFIX "titan"
#include "gencp-over-i2c/liblogger.h"

/* Werner (Titan eSW) confirms I2C address 0x30 and a map closer to iLumos.
 * Use iLumos addresses and acquisition commands provisionally; refine with FW.
 * Timing and CSI byte order also await hardware confirmation.
 */
#define REG_ACQ_START_W   0x50000A00
#define REG_ACQ_STATUS_R  0x50000A20
#define REG_FIRW_VER_R    0x10000000
#define REG_SERIAL_R      0x00144
#define REG_MODEL_NAME_R  0x00044
#define REG_IMG_HEIGHT_R  0x50000004
#define REG_IMG_WIDTH_R   0x50000000
#define REG_PIXEL_FORMAT  0x50000008

#define PIXEL_FORMAT_MONO16 0x01100007u
#define PIXEL_FORMAT_MONO14 0x01100025u

#define TITAN_STR_MAX    256

/* Optional boot retry budget inherited from iLumos. Titan boot timing is
 * unknown: absent/zero exosens,probe-timeout-ms means a single attempt.
 * Set that DT property on carriers that release camera power/reset late.
 */
#define TITAN_PROBE_TIMEOUT_MS_DEFAULT  0
#define TITAN_PROBE_RETRY_MS            200

/* Attempts to make for a given timeout: always at least one. */
static unsigned int titan_probe_attempts(struct device *dev)
{
   u32 ms = TITAN_PROBE_TIMEOUT_MS_DEFAULT;

   if (dev->of_node)
      of_property_read_u32(dev->of_node, "exosens,probe-timeout-ms", &ms);

   return ms / TITAN_PROBE_RETRY_MS + 1;
}

/* The GenCP client has module-global buffers and a selected I2C handle.
 * Every transaction, probe, and teardown is serialized by this mutex.
 * The composite titan.ko embeds the library's 1024-byte I2C buffer transport;
 * MicroLynx is built separately with its existing 16-byte FIFO transport.
 */
static DEFINE_MUTEX(titan_gencp_lock);
static unsigned int titan_gencp_users;

/* ---- ioctl interface (/dev/titan-<bus>-<addr>) ------------------------- */

/**
 * struct titan_reg_op - ioctl payload for 32-bit register read/write
 * @addr: register address
 * @val:  value written (WRITE_REG) or value returned (READ_REG)
 */
struct titan_reg_op {
   __u32 addr;
   __u32 val;
};

/**
 * struct titan_str_op - ioctl payload for string read
 * @addr: register address of the string
 * @len:  number of bytes to read (1..TITAN_STR_MAX)
 * @buf:  buffer filled with the string data on return
 */
struct titan_str_op {
   __u32 addr;
   __u32 len;
   __u8  buf[TITAN_STR_MAX];
};

#define TITAN_IOCTL_MAGIC    'T'
#define TITAN_IOCTL_READ_REG  _IOWR(TITAN_IOCTL_MAGIC, 1, struct titan_reg_op)
#define TITAN_IOCTL_WRITE_REG _IOW (TITAN_IOCTL_MAGIC, 2, struct titan_reg_op)
#define TITAN_IOCTL_READ_STR  _IOWR(TITAN_IOCTL_MAGIC, 3, struct titan_str_op)

static const struct of_device_id titan_of_match[] = {
   { .compatible = "exosens,titan", },
   { },
};
MODULE_DEVICE_TABLE(of, titan_of_match);

enum {
   TITAN_MODE_1208x1024_RAW16_BE,
   TITAN_MODE_1208x1024_RAW14,
};

static const int titan_60fps[] = {
   60,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
/* Native resolution confirmed by Werner (Titan eSW), 2026-10-15.
 * TODO: confirm frame rate. */
static const struct camera_common_frmfmt titan_frmfmt[] = {
   {{1208, 1024}, titan_60fps, 1, 0, TITAN_MODE_1208x1024_RAW16_BE},
   {{1208, 1024}, titan_60fps, 1, 0, TITAN_MODE_1208x1024_RAW14},
};

static int titan_find_frmfmt(u32 width, u32 height)
{
   u32 i;

   for (i = 0; i < ARRAY_SIZE(titan_frmfmt); i++) {
      const struct camera_common_frmfmt *fmt = titan_frmfmt + i;

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

struct titan {
   struct i2c_client    *i2c_client;
   struct v4l2_subdev      *subdev;
   struct camera_common_data  *s_data;
   struct tegracam_device     *tc_dev;

   struct unio_handle io_handle;
   bool gencp_initialized;
   bool misc_registered;
   struct kref refcount; /* open chardev files can outlive I2C unbind */

   char        model[64];
   char        serial_number[64];
   char        firmware_version[64];
   char        pixel_format[64];
   u32         native_width;
   u32         native_height;

   /* chardev — /dev/titan-<bus>-<addr> */
   struct miscdevice miscdev;
   char              miscdev_name[32];
};

/* Caller holds titan_gencp_lock. Translate GenCP status to Linux errno:
 * ioctl must never return a positive protocol error as apparent success.
 */
static int titan_gencp_status(u16 status)
{
   return status ? -EIO : 0;
}

static int titan_read_register(struct titan *priv, u32 reg, u32 *value)
{
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   return titan_gencp_status(GENCPCLIENT_ReadRegister(reg, value));
}

static int titan_write_register(struct titan *priv, u32 reg, u32 value)
{
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   return titan_gencp_status(GENCPCLIENT_WriteRegister(reg, value));
}

static int titan_read_string(struct titan *priv, u32 reg, u8 *buf, u16 len)
{
   if (!len || len > TITAN_STR_MAX)
      return -EINVAL;
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   return titan_gencp_status(GENCPCLIENT_ReadString(reg, buf, len));
}

static void titan_free(struct kref *ref)
{
   struct titan *priv = container_of(ref, struct titan, refcount);

   kfree(priv);
}

/* Caller holds titan_gencp_lock. Do not free buffers used by another camera. */
static void titan_gencp_put(struct titan *priv)
{
   if (priv->gencp_initialized) {
      priv->gencp_initialized = false;
      if (!--titan_gencp_users)
         GENCPCLIENT_Cleanup();
   }
}

/* ---- chardev file operations ------------------------------------------ */

static int titan_cdev_open(struct inode *inode, struct file *file)
{
   struct titan *priv =
      container_of(file->private_data, struct titan, miscdev);
   mutex_lock(&titan_gencp_lock);
   if (!priv->gencp_initialized) {
      mutex_unlock(&titan_gencp_lock);
      return -ENODEV;
   }
   kref_get(&priv->refcount);
   file->private_data = priv;
   mutex_unlock(&titan_gencp_lock);
   return 0;
}

static int titan_cdev_release(struct inode *inode, struct file *file)
{
   struct titan *priv = file->private_data;

   kref_put(&priv->refcount, titan_free);
   return 0;
}

static long titan_cdev_ioctl(struct file *file, unsigned int cmd,
                              unsigned long arg)
{
   struct titan *priv = file->private_data;
   int ret = 0;

   mutex_lock(&titan_gencp_lock);
   if (!priv->gencp_initialized) {
      ret = -ENODEV;
      goto out;
   }

   switch (cmd) {
   case TITAN_IOCTL_READ_REG: {
      struct titan_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = titan_read_register(priv, op.addr, &op.val);
      if (ret == 0 && copy_to_user((void __user *)arg, &op, sizeof(op)))
         ret = -EFAULT;
      break;
   }
   case TITAN_IOCTL_WRITE_REG: {
      struct titan_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = titan_write_register(priv, op.addr, op.val);
      break;
   }
   case TITAN_IOCTL_READ_STR: {
      struct titan_str_op op = { 0 };

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      if (!op.len || op.len > TITAN_STR_MAX) {
         ret = -EINVAL;
         break;
      }
      memset(op.buf, 0, sizeof(op.buf));
      ret = titan_read_string(priv, op.addr,
                                   op.buf, op.len);
      if (ret == 0 && copy_to_user((void __user *)arg, &op, sizeof(op)))
         ret = -EFAULT;
      break;
   }
   default:
      ret = -ENOTTY;
      break;
   }

out:
   mutex_unlock(&titan_gencp_lock);
   return ret;
}

static const struct file_operations titan_cdev_fops = {
   .owner          = THIS_MODULE,
   .open           = titan_cdev_open,
   .release        = titan_cdev_release,
   .unlocked_ioctl = titan_cdev_ioctl,
#ifdef CONFIG_COMPAT
   .compat_ioctl   = compat_ptr_ioctl,
#endif
};

/* Pixel format is applied at stream start, with read-back verification.
 * TODO: confirm Titan supports writing PixelFormat while acquisition is off.
 */
static int titan_pixfmt_to_reg(u32 v4l2_pixfmt, u32 *reg)
{
   switch (v4l2_pixfmt) {
   case V4L2_PIX_FMT_Y16_BE:
      *reg = PIXEL_FORMAT_MONO16;
      return 0;
   case V4L2_PIX_FMT_Y14:
      *reg = PIXEL_FORMAT_MONO14;
      return 0;
   }

   return -EINVAL;
}

static const char *titan_pixfmt_name(u32 reg)
{
   switch (reg) {
   case PIXEL_FORMAT_MONO14:
      return "'Y14 ' (14-bit Greyscale)";
   case PIXEL_FORMAT_MONO16:
      return "'Y16 -BE' (16-bit Greyscale Big Endian)";
   }

   return "unknown";
}

/*
 * Bring the camera to the requested format and keep the driver's own view of it
 * in sync: the sysfs pixel_format attribute, and the mode index the DT numbers
 * from (0 RAW16_BE, 1 RAW14).
 *
 * Writing is skipped when the camera is already there, so a stream start that
 * changes nothing costs one read and leaves the camera untouched.
 */
static int titan_apply_pixel_format(struct titan *priv, u32 want)
{
   struct device *dev = &priv->i2c_client->dev;
   u32 current_fmt;
   int mode;
   int rc;

   rc = titan_read_register(priv, REG_PIXEL_FORMAT, &current_fmt);
   if (rc) {
      dev_err(dev, "PIXEL_FORMAT read failed (%d)\n", rc);
      return rc;
   }

   if (current_fmt != want) {
      rc = titan_write_register(priv, REG_PIXEL_FORMAT, want);
      if (rc) {
         dev_err(dev, "camera refused PIXEL_FORMAT 0x%08x %s (%d)\n",
                 want, titan_pixfmt_name(want), rc);
         return rc;
      }

      /* Read back rather than trust the write: the status word says the camera
       * accepted the transfer, not that it settled on the value we asked for. */
      rc = titan_read_register(priv, REG_PIXEL_FORMAT, &current_fmt);
      if (rc) {
         dev_err(dev, "PIXEL_FORMAT read-back failed (%d)\n", rc);
         return rc;
      }
      if (current_fmt != want) {
         dev_err(dev, "PIXEL_FORMAT stayed at 0x%08x after writing 0x%08x\n",
                 current_fmt, want);
         return -EIO;
      }

      dev_info(dev, "PIXEL_FORMAT set to 0x%08x %s\n",
               current_fmt, titan_pixfmt_name(current_fmt));
   }

   strncpy(priv->pixel_format, titan_pixfmt_name(current_fmt),
           sizeof(priv->pixel_format) - 1);
   priv->pixel_format[sizeof(priv->pixel_format) - 1] = '\0';

   priv->s_data->colorfmt = camera_common_find_pixelfmt(
         current_fmt == PIXEL_FORMAT_MONO14 ? V4L2_PIX_FMT_Y14 : V4L2_PIX_FMT_Y16_BE);
   if (!priv->s_data->colorfmt)
      return -EINVAL;

   mode = titan_find_frmfmt(priv->native_width, priv->native_height);
   if (mode >= 0) {
      if (current_fmt == PIXEL_FORMAT_MONO14)
         mode += TITAN_MODE_1208x1024_RAW14;
      priv->tc_dev->s_data->sensor_mode_id = mode;
      priv->tc_dev->s_data->def_mode       = mode;
   }

   return 0;
}

static int titan_sensor_check(struct titan *priv)
{
   struct device *dev = &priv->i2c_client->dev;
   int i, mode, rc;
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
      unsigned int attempts = titan_probe_attempts(dev);
      unsigned int attempt;
      rc = -EIO;

      for (attempt = 0; attempt < attempts; attempt++) {
         rc = titan_read_string(priv, REG_FIRW_VER_R,
                                     buf, sizeof(buf));
         if (rc == 0)
            break;
         if (attempt + 1 < attempts)   /* no wait after the last try */
            msleep(TITAN_PROBE_RETRY_MS);
      }
      if (rc == 0 && attempt)
         dev_warn(dev, "camera answered only after %u ms (%u retries) -- "
                  "it was still booting when the driver probed\n",
                  attempt * TITAN_PROBE_RETRY_MS, attempt);
   }

   /* FPGA firmware version */
   if (rc == 0) {
      for (i = sizeof(buf) - 1; i >= 0 && buf[i] == (u8)0xff; i--)
         buf[i] = '\0';
      strncpy(priv->firmware_version, buf, sizeof(priv->firmware_version) - 1);
      priv->firmware_version[sizeof(priv->firmware_version) - 1] = '\0';
      dev_info(dev, "FPGA firmware version = %s\n", priv->firmware_version);
   } else {
      dev_err(dev, "FPGA firmware read failed\n");
      goto error_exit;
   }

   /* Pixel format the camera is currently in. It is only a starting point now:
    * VIDIOC_S_FMT can change it later, see titan_set_mode(). */
   if (titan_read_register(priv, REG_PIXEL_FORMAT, &read_data) == 0) {
      if (read_data == PIXEL_FORMAT_MONO14)
         is_raw14 = true;
      else if (read_data != PIXEL_FORMAT_MONO16)
         dev_warn(dev, "unknown PIXEL_FORMAT 0x%08x, assuming RAW16\n",
                  read_data);
      dev_info(dev, "PIXEL_FORMAT = 0x%08x %s\n", read_data,
               titan_pixfmt_name(read_data));
   } else {
      dev_warn(dev, "PIXEL_FORMAT read failed, assuming RAW16\n");
   }

   if (titan_read_register(priv, REG_IMG_WIDTH_R, &width) == 0) {
      if (titan_read_register(priv, REG_IMG_HEIGHT_R, &height) == 0) {
      } else {
         dev_err(dev, "Failed to read height\n");
         goto error_exit;
      }
   } else {
      dev_err(dev, "Failed to read width\n");
      goto error_exit;
   }

   dev_info(dev, "Frame width = %u px\n", width);
   dev_info(dev, "Frame height = %u px\n", height);


   /* titan_frmfmt: index 0 = RAW16_BE, index 1 = RAW14 */
   mode = titan_find_frmfmt(width, height);
   if (mode < 0) {
      dev_err(dev, "unsupported resolution %ux%u\n", width, height);
      goto error_exit;
   }
   if (is_raw14)
      mode += TITAN_MODE_1208x1024_RAW14;

   priv->tc_dev->s_data->sensor_mode_id = mode;
   priv->tc_dev->s_data->def_mode       = mode;
   /* Sync the V4L2 format to the camera's actual native resolution.
    * tegracam_device_register() always initialises fmt from frmfmt[0]
    * (1208x1024). Keep this fixup for future native sensor resolutions. */
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

   strncpy(priv->pixel_format,
           titan_pixfmt_name(is_raw14 ? PIXEL_FORMAT_MONO14
                                       : PIXEL_FORMAT_MONO16),
           sizeof(priv->pixel_format) - 1);
   priv->pixel_format[sizeof(priv->pixel_format) - 1] = '\0';

   dev_info(dev, "mode=%d  pixel_format=%s\n", mode, priv->pixel_format);

   priv->native_width  = width;
   priv->native_height = height;

   /* Model name */
   if (titan_read_string(priv, REG_MODEL_NAME_R,
                                (u8 *)priv->model, sizeof(priv->model)) == 0) {
      for (i = sizeof(priv->model) - 1; i >= 0 &&
            (priv->model[i] == (char)0xff || priv->model[i] == '\0'); i--)
         priv->model[i] = '\0';
   } else {
      priv->model[0] = '\0';
      dev_warn(dev, "failed to read model name\n");
   }

   priv->model[sizeof(priv->model) - 1] = '\0';

   /* Serial number */
   if (titan_read_string(priv, REG_SERIAL_R,
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

   priv->serial_number[sizeof(priv->serial_number) - 1] = '\0';

   // Stop the video streaming by default
   dev_dbg(dev, "%s Stop streaming\n", __func__);
   return titan_write_register(priv, REG_ACQ_START_W, 2);

error_exit:
   dev_err(dev, "Probing failed\n");
   return -EIO;
}

static int titan_set_group_hold(struct tegracam_device *tc_dev, bool val)
{
   /* group hold is not supported */
   dev_dbg(tc_dev->dev, "%s val=%d\n", __func__, val);
   return 0;
}

#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
static int titan_set_gain(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int titan_set_frame_rate(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int titan_set_exposure(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}
#endif

static struct tegracam_ctrl_ops titan_ctrl_ops = {
   .numctrls = ARRAY_SIZE(ctrl_cid_list),
   .ctrl_cid_list = ctrl_cid_list,
#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
   .set_gain = titan_set_gain,
   .set_exposure = titan_set_exposure,
   .set_frame_rate = titan_set_frame_rate,
#endif
   .set_group_hold = titan_set_group_hold,
};

static int titan_power_on(struct camera_common_data *s_data)
{
   /* Power is not managed here */
   struct device *dev = s_data->dev;
   dev_dbg(dev, "%s\n", __func__);
   return 0;
}

static int titan_power_off(struct camera_common_data *s_data)
{
   /* Power is not managed here */
   struct device *dev = s_data->dev;
   dev_dbg(dev, "%s\n", __func__);
   return 0;
}

static int titan_power_put(struct tegracam_device *tc_dev)
{
   /* Power is not managed here */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static int titan_power_get(struct tegracam_device *tc_dev)
{
   /* Power is not managed here */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static struct camera_common_pdata *titan_parse_dt(
      struct tegracam_device *tc_dev)
{
   struct device *dev = tc_dev->dev;
   struct device_node *np = dev->of_node;
   struct camera_common_pdata *board_priv_pdata;
   const struct of_device_id *match;

   if (!np)
      return NULL;

   match = of_match_device(titan_of_match, dev);
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

/*
 * Called by tegracam at stream start, before start_streaming -- the same hook
 * imx219 uses to push its mode register table. Everything but the pixel format
 * is still configured out of band by a control application.
 *
 * The camera is stopped at this point, which is when it accepts a format change.
 * That is also why the change lands here and not in VIDIOC_S_FMT: tegracam gives
 * the sensor no callback on set_fmt, and its pad ops are a single static shared
 * by every tegracam driver on the system.
 *
 * s_data->colorfmt is what V4L2 negotiated (camera_common_s_fmt() resolves it
 * from the mbus code), so it is the request, not the camera's current state.
 */
static int titan_set_mode(struct tegracam_device *tc_dev)
{
   struct titan *priv = tegracam_get_privdata(tc_dev);
   struct camera_common_data *s_data = tc_dev->s_data;
   u32 want;

   dev_dbg(tc_dev->dev, "%s\n", __func__);

   if (!s_data->colorfmt)
      return 0;

   if (titan_pixfmt_to_reg(s_data->colorfmt->pix_fmt, &want)) {
      /* Not reachable through V4L2: ENUM_FMT only offers what the DT modes
       * declare, and those are Y16-BE and Y14. Leave the camera alone rather
       * than guess. */
      dev_warn(tc_dev->dev,
               "no camera pixel format for V4L2 0x%08x, leaving it unchanged\n",
               s_data->colorfmt->pix_fmt);
      return 0;
   }

   {
      int rc;

      mutex_lock(&titan_gencp_lock);
      rc = priv->gencp_initialized ? titan_apply_pixel_format(priv, want) : -ENODEV;
      mutex_unlock(&titan_gencp_lock);
      return rc;
   }
}

static int titan_start_streaming(struct tegracam_device *tc_dev)
{
   struct titan *priv = tegracam_get_privdata(tc_dev);
   u32 status;
   int rc;

   mutex_lock(&titan_gencp_lock);
   if (!priv->gencp_initialized) {
      rc = -ENODEV;
   } else {
      rc = titan_read_register(priv, REG_ACQ_STATUS_R, &status);
      if (!rc && status != 1)
         rc = titan_write_register(priv, REG_ACQ_START_W, 1);
   }
   mutex_unlock(&titan_gencp_lock);
   return rc;
}

static int titan_stop_streaming(struct tegracam_device *tc_dev)
{
   struct titan *priv = tegracam_get_privdata(tc_dev);
   int rc;

   mutex_lock(&titan_gencp_lock);
   rc = priv->gencp_initialized ? titan_write_register(priv, REG_ACQ_START_W, 2)
                              : -ENODEV;
   mutex_unlock(&titan_gencp_lock);
   /* Let VI finish the last DMA before teardown, as in iLumos. */
   msleep(50);
   return rc;
}

static struct camera_common_sensor_ops titan_common_ops = {
   .numfrmfmts = ARRAY_SIZE(titan_frmfmt),
   .frmfmt_table = titan_frmfmt,
   .power_on = titan_power_on,
   .power_off = titan_power_off,
   .parse_dt = titan_parse_dt,
   .power_get = titan_power_get,
   .power_put = titan_power_put,
   .set_mode = titan_set_mode,
   .start_streaming = titan_start_streaming,
   .stop_streaming = titan_stop_streaming,
};

static ssize_t model_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct titan *priv = (struct titan *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->model);
}
static DEVICE_ATTR_RO(model);

static ssize_t serial_number_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct titan *priv = (struct titan *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->serial_number);
}
static DEVICE_ATTR_RO(serial_number);

static ssize_t resolution_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct titan *priv = (struct titan *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%ux%u\n",
         priv->native_width, priv->native_height);
}
static DEVICE_ATTR_RO(resolution);

static ssize_t pixel_format_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct titan *priv = (struct titan *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->pixel_format);
}
static DEVICE_ATTR_RO(pixel_format);

/* Formats switchable at stream start, using the provisional register map. */
static ssize_t pixel_formats_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   return scnprintf(buf, PAGE_SIZE, "%s\n%s\n",
         titan_pixfmt_name(PIXEL_FORMAT_MONO16),
         titan_pixfmt_name(PIXEL_FORMAT_MONO14));
}
static DEVICE_ATTR_RO(pixel_formats);

static ssize_t firmware_version_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct titan *priv = (struct titan *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->firmware_version);
}
static DEVICE_ATTR_RO(firmware_version);

static int titan_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
   return 0;
}

static const struct v4l2_subdev_internal_ops titan_subdev_internal_ops = {
   .open = titan_open,
};

/*
 * Titan uses GenCP-over-I2C through priv->io_handle, never
 * regmap_read/write. This config only exists so tegracam_core's
 * devm_regmap_init_i2c() has a non-NULL config to work with on stock
 * NVIDIA/vendor kernels that don't carry the EG NULL-config guard.
 */
static const struct regmap_config titan_dummy_regmap_config = {
   .reg_bits = 8,
   .val_bits = 8,
};

#if defined(NV_I2C_DRIVER_STRUCT_PROBE_WITHOUT_I2C_DEVICE_ID_ARG) /* Linux 6.3 */
static int titan_probe(struct i2c_client *client)
#else
static int titan_probe(struct i2c_client *client,
      const struct i2c_device_id *id)
#endif
{
   struct device *dev = &client->dev;
   struct tegracam_device *tc_dev;
   struct titan *priv;
   int err;

   dev_info(dev, "probing v4l2 titan sensor at addr 0x%0x\n", client->addr);

   if (!IS_ENABLED(CONFIG_OF) || !client->dev.of_node)
      return -EINVAL;

   priv = kzalloc(sizeof(struct titan), GFP_KERNEL);
   if (!priv)
      return -ENOMEM;

   kref_init(&priv->refcount);

   tc_dev = devm_kzalloc(dev, sizeof(struct tegracam_device), GFP_KERNEL);
   if (!tc_dev) {
      kref_put(&priv->refcount, titan_free);
      return -ENOMEM;
   }

   priv->i2c_client = tc_dev->client = client;
   tc_dev->dev = dev;
   strncpy(tc_dev->name, "titan", sizeof(tc_dev->name));
   tc_dev->dev_regmap_config = &titan_dummy_regmap_config;
   tc_dev->sensor_ops = &titan_common_ops;
   tc_dev->v4l2sd_internal_ops = &titan_subdev_internal_ops;
   tc_dev->tcctrl_ops = &titan_ctrl_ops;

   err = tegracam_device_register(tc_dev);
   if (err) {
      dev_err(dev, "tegra camera driver registration failed\n");
      kref_put(&priv->refcount, titan_free);
      return err;
   }

   priv->tc_dev = tc_dev;
   priv->s_data = tc_dev->s_data;
   priv->subdev = &tc_dev->s_data->subdev;
   tegracam_set_privdata(tc_dev, (void *)priv);

   /* Initialize sensor and check GenCP communication */
   priv->io_handle.client = client;
   mutex_lock(&titan_gencp_lock);
   /* Init allocates global buffers: only once while at least one Titan exists.
    * Select restores the handle before each subsequent transaction.
    */
   if (!titan_gencp_users)
      GENCPCLIENT_Init(&priv->io_handle);
   priv->gencp_initialized = true;
   titan_gencp_users++;
   err = titan_sensor_check(priv);
   if (err)
      titan_gencp_put(priv);
   mutex_unlock(&titan_gencp_lock);
   if (err) {
      dev_err(dev, "sensor check failed\n");
      tegracam_device_unregister(tc_dev);
      kref_put(&priv->refcount, titan_free);
      return err;
   }

   err = tegracam_v4l2subdev_register(tc_dev, true);
   if (err) {
      dev_err(dev, "tegra camera subdev registration failed\n");
      mutex_lock(&titan_gencp_lock);
      titan_gencp_put(priv);
      mutex_unlock(&titan_gencp_lock);
      tegracam_device_unregister(tc_dev);
      kref_put(&priv->refcount, titan_free);
      return err;
   }

   device_create_file(dev, &dev_attr_model);
   device_create_file(dev, &dev_attr_serial_number);
   device_create_file(dev, &dev_attr_resolution);
   device_create_file(dev, &dev_attr_pixel_format);
   device_create_file(dev, &dev_attr_pixel_formats);
   device_create_file(dev, &dev_attr_firmware_version);

   /* Register chardev for userspace register access */
   snprintf(priv->miscdev_name, sizeof(priv->miscdev_name),
            "titan-%d-%04x", client->adapter->nr, client->addr);
   priv->miscdev.minor  = MISC_DYNAMIC_MINOR;
   priv->miscdev.name   = priv->miscdev_name;
   priv->miscdev.fops   = &titan_cdev_fops;
   priv->miscdev.parent = dev;
   if (misc_register(&priv->miscdev)) {
      dev_warn(dev, "failed to register chardev; exosensCamCtrl.py will not work\n");
   } else {
      priv->misc_registered = true;
      dev_info(dev, "chardev registered at /dev/%s\n", priv->miscdev_name);
   }

   return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
static int titan_remove(struct i2c_client *client)
#else
static void titan_remove(struct i2c_client *client)
#endif
{
   struct device *dev = &client->dev;
   struct camera_common_data *s_data = to_camera_common_data(&client->dev);
   struct titan *priv = (struct titan *)s_data->priv;

   if (priv->misc_registered)
      misc_deregister(&priv->miscdev);

   device_remove_file(dev, &dev_attr_firmware_version);
   device_remove_file(dev, &dev_attr_pixel_formats);
   device_remove_file(dev, &dev_attr_pixel_format);
   device_remove_file(dev, &dev_attr_resolution);
   device_remove_file(dev, &dev_attr_serial_number);
   device_remove_file(dev, &dev_attr_model);

   tegracam_v4l2subdev_unregister(priv->tc_dev);
   tegracam_device_unregister(priv->tc_dev);

   mutex_lock(&titan_gencp_lock);
   titan_gencp_put(priv);
   mutex_unlock(&titan_gencp_lock);
   kref_put(&priv->refcount, titan_free);

   dev_info(dev, "Removed titan device\n");

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
   return 0;
#endif
}

static const struct i2c_device_id titan_id[] = {
   { "titan", 0 },
   { }
};
MODULE_DEVICE_TABLE(i2c, titan_id);

static struct i2c_driver titan_i2c_driver = {
   .driver = {
      .name = "titan",
      .owner = THIS_MODULE,
      .of_match_table = of_match_ptr(titan_of_match),
   },
   .probe = titan_probe,
   .remove = titan_remove,
   .id_table = titan_id,
};
module_i2c_driver(titan_i2c_driver);

MODULE_AUTHOR("Exosens");
MODULE_DESCRIPTION("Exosens MIPI camera I2C driver for Titan cameras");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");
