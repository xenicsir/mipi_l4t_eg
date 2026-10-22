/*
 * A V4L2 driver for Exosens ilumos MIPI IR cameras.
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
#define PREFIX "ilumos"
#include "gencp-over-i2c/liblogger.h"

/* Serialize complete GenCP transactions and camera mode changes. */
static DEFINE_MUTEX(ilumos_gencp_lock);
static unsigned int ilumos_gencp_users;

/* iLumos GenCP registers */
#define REG_ACQ_START_W   0x50000A00
#define REG_ACQ_STATUS_R  0x50000A20
#define REG_FIRW_VER_R    0x10000000
#define REG_SERIAL_R      0x00144
#define REG_MODEL_NAME_R  0x00044
#define REG_IMG_HEIGHT_R  0x50000004
#define REG_IMG_WIDTH_R   0x50000000 
#define REG_PIXEL_FORMAT   0x50000008 

#define PIXEL_FORMAT_MONO16 0x01100007u
#define PIXEL_FORMAT_MONO14 0x01100025u

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

#define CROSSLINK_PIXEL_FORMAT_MONO16 0x2E
#define CROSSLINK_PIXEL_FORMAT_MONO14 0x2D

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
 * @len:  number of bytes to read (1..ILUMOS_STR_MAX)
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

enum ilumos_i2c_protocol {
   ILUMOS_I2C_UNSELECTED,
   ILUMOS_I2C_GENCP,
   ILUMOS_I2C_BASIC,
};

struct ilumos {
   struct i2c_client    *i2c_client;
   struct v4l2_subdev      *subdev;
   struct camera_common_data  *s_data;
   struct tegracam_device     *tc_dev;

   struct unio_handle io_handle;
   enum ilumos_i2c_protocol i2c_protocol;
   bool gencp_initialized;
   bool misc_registered;
   struct kref refcount; /* open chardev files may outlive I2C unbind */

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

/* Basic requests and responses use little-endian fields and a status word.
 * The firmware reads complete 32-bit registers; round string reads up and copy
 * only the requested bytes. Caller holds ilumos_gencp_lock.
 */
static int ilumos_basic_status(const u8 *response)
{
   u16 status = response[0] | ((u16)response[1] << 8);

   if (status == 0xffff)
      return -EBUSY;
   return status ? -EIO : 0;
}

static int ilumos_basic_read(struct ilumos *priv, u32 reg, u8 *dst, u16 len)
{
   u8 tx[6], rx[ILUMOS_STR_MAX + 2];
   u16 wire_len;
   __le32 address;
   __le16 length;
   struct i2c_msg msgs[2];
   int rc;

   if (!len || len > ILUMOS_STR_MAX)
      return -EINVAL;
   wire_len = (len + 3) & ~3;
   address = cpu_to_le32(reg);
   length = cpu_to_le16(wire_len);
   memcpy(tx, &address, sizeof(address));
   memcpy(tx + 4, &length, sizeof(length));
   msgs[0].addr = priv->i2c_client->addr;
   msgs[0].flags = 0;
   msgs[0].len = sizeof(tx);
   msgs[0].buf = tx;
   msgs[1].addr = priv->i2c_client->addr;
   msgs[1].flags = I2C_M_RD;
   msgs[1].len = wire_len + 2;
   msgs[1].buf = rx;
   rc = i2c_transfer(priv->i2c_client->adapter, msgs, ARRAY_SIZE(msgs));
   if (rc != 2)
      return rc < 0 ? rc : -EIO;
   rc = ilumos_basic_status(rx);
   if (!rc)
      memcpy(dst, rx + 2, len);
   return rc;
}

static int ilumos_basic_write(struct ilumos *priv, u32 reg, u32 value)
{
   u8 tx[10], rx[2];
   __le32 address = cpu_to_le32(reg);
   __le16 length = cpu_to_le16(sizeof(value));
   __le32 data = cpu_to_le32(value);
   struct i2c_msg msgs[2];
   int rc;

   memcpy(tx, &address, sizeof(address));
   memcpy(tx + 4, &length, sizeof(length));
   memcpy(tx + 6, &data, sizeof(data));
   msgs[0].addr = priv->i2c_client->addr;
   msgs[0].flags = 0;
   msgs[0].len = sizeof(tx);
   msgs[0].buf = tx;
   msgs[1].addr = priv->i2c_client->addr;
   msgs[1].flags = I2C_M_RD;
   msgs[1].len = sizeof(rx);
   msgs[1].buf = rx;
   rc = i2c_transfer(priv->i2c_client->adapter, msgs, ARRAY_SIZE(msgs));
   if (rc != 2)
      return rc < 0 ? rc : -EIO;
   return ilumos_basic_status(rx);
}

static int ilumos_gencp_status(u16 status)
{
   return status ? -EIO : 0;
}

static int ilumos_read_register(struct ilumos *priv, u32 reg, u32 *value)
{
   if (priv->i2c_protocol == ILUMOS_I2C_BASIC) {
      __le32 data;
      int rc = ilumos_basic_read(priv, reg, (u8 *)&data, sizeof(data));

      if (!rc)
         *value = le32_to_cpu(data);
      return rc;
   }
   if (priv->i2c_protocol != ILUMOS_I2C_GENCP)
      return -EAGAIN;
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   return ilumos_gencp_status(GENCPCLIENT_ReadRegister(reg, value));
}

static int ilumos_write_register(struct ilumos *priv, u32 reg, u32 value)
{
   if (priv->i2c_protocol == ILUMOS_I2C_BASIC)
      return ilumos_basic_write(priv, reg, value);
   if (priv->i2c_protocol != ILUMOS_I2C_GENCP)
      return -EAGAIN;
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   return ilumos_gencp_status(GENCPCLIENT_WriteRegister(reg, value));
}

static int ilumos_read_string(struct ilumos *priv, u32 reg, u8 *buf, u16 len)
{
   if (!len || len > ILUMOS_STR_MAX)
      return -EINVAL;
   if (priv->i2c_protocol == ILUMOS_I2C_BASIC)
      return ilumos_basic_read(priv, reg, buf, len);
   if (priv->i2c_protocol != ILUMOS_I2C_GENCP)
      return -EAGAIN;
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   return ilumos_gencp_status(GENCPCLIENT_ReadString(reg, buf, len));
}

/* Select once per binding, using the first firmware-version read. The valid
 * GenCP response is reused by the probe; later errors never change protocols.
 */
static int ilumos_read_firmware(struct ilumos *priv, u8 *buf, u16 len)
{
   int rc;

   if (priv->i2c_protocol != ILUMOS_I2C_UNSELECTED)
      return ilumos_read_string(priv, REG_FIRW_VER_R, buf, len);
   GENCPCLIENT_Select(&priv->io_handle);
   if (!GENCPCLIENT_isSuccesfullyInitialized())
      return -ENOMEM;
   rc = ilumos_gencp_status(GENCPCLIENT_ReadString(REG_FIRW_VER_R, buf, len));
   if (!rc) {
      priv->i2c_protocol = ILUMOS_I2C_GENCP;
      dev_info(&priv->i2c_client->dev, "I2C protocol selected: GenCP\n");
      return 0;
   }
   priv->i2c_protocol = ILUMOS_I2C_BASIC;
   dev_info(&priv->i2c_client->dev,
            "I2C protocol selected: basic (GenCP firmware read failed: %d)\n", rc);
   return ilumos_basic_read(priv, REG_FIRW_VER_R, buf, len);
}

static void ilumos_free(struct kref *ref)
{
   struct ilumos *priv = container_of(ref, struct ilumos, refcount);

   kfree(priv);
}

static void ilumos_gencp_put(struct ilumos *priv)
{
   if (priv->gencp_initialized) {
      priv->gencp_initialized = false;
      if (!--ilumos_gencp_users)
         GENCPCLIENT_Cleanup();
   }
}


/* ---- chardev file operations ------------------------------------------ */

static int ilumos_cdev_open(struct inode *inode, struct file *file)
{
   struct ilumos *priv =
      container_of(file->private_data, struct ilumos, miscdev);
   mutex_lock(&ilumos_gencp_lock);
   if (!priv->gencp_initialized) {
      mutex_unlock(&ilumos_gencp_lock);
      return -ENODEV;
   }
   kref_get(&priv->refcount);
   file->private_data = priv;
   mutex_unlock(&ilumos_gencp_lock);
   return 0;
}

static int ilumos_cdev_release(struct inode *inode, struct file *file)
{
   struct ilumos *priv = file->private_data;

   kref_put(&priv->refcount, ilumos_free);
   return 0;
}

static long ilumos_cdev_ioctl(struct file *file, unsigned int cmd,
                              unsigned long arg)
{
   struct ilumos *priv = file->private_data;
   int ret = 0;

   mutex_lock(&ilumos_gencp_lock);
   if (!priv->gencp_initialized) {
      ret = -ENODEV;
      goto out;
   }

   switch (cmd) {
   case EG_IOCTL_GENCP_STATS:
      if (priv->i2c_protocol != ILUMOS_I2C_GENCP) {
         ret = -EOPNOTSUPP;
         break;
      }
      ret = GENCPCLIENT_UserStats(&priv->io_handle, arg);
      break;
   case EG_IOCTL_GENCP_XFER:
      if (priv->i2c_protocol != ILUMOS_I2C_GENCP) {
         ret = -EOPNOTSUPP;
         break;
      }
      ret = GENCPCLIENT_UserExchange(&priv->io_handle, arg);
      break;
   case ILUMOS_IOCTL_READ_REG: {
      struct ilumos_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = ilumos_read_register(priv, op.addr, &op.val);
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
      ret = ilumos_write_register(priv, op.addr, op.val);
      break;
   }
   case ILUMOS_IOCTL_READ_STR: {
      struct ilumos_str_op op = { 0 };

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      if (!op.len || op.len > ILUMOS_STR_MAX) {
         ret = -EINVAL;
         break;
      }
      memset(op.buf, 0, sizeof(op.buf));
      ret = ilumos_read_string(priv, op.addr,
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
   mutex_unlock(&ilumos_gencp_lock);
   return ret;
}

static const struct file_operations ilumos_cdev_fops = {
   .owner          = THIS_MODULE,
   .open           = ilumos_cdev_open,
   .release        = ilumos_cdev_release,
   .unlocked_ioctl = ilumos_cdev_ioctl,
#ifdef CONFIG_COMPAT
   .compat_ioctl   = compat_ptr_ioctl,
#endif
};


/*
 * Pixel format, as a GenICam PixelFormat value in REG_PIXEL_FORMAT.
 *
 * iLumos is the only camera we ship whose format can be switched while it is
 * powered: the register is writable and the change takes effect on the next
 * acquisition. Every other one needs the module reloaded, which is why they only
 * ever read their format at probe. So here the format follows VIDIOC_S_FMT.
 *
 * The resolution does NOT follow: it is a property of the sensor, fixed per
 * camera model. Only the format axis moves.
 */
static int ilumos_pixfmt_to_reg(u32 v4l2_pixfmt, u32 *reg)
{
   switch (v4l2_pixfmt) {
   case V4L2_PIX_FMT_Y16_BE:
   case V4L2_PIX_FMT_Y16:
      *reg = PIXEL_FORMAT_MONO16;
      return 0;
   case V4L2_PIX_FMT_Y14:
      *reg = PIXEL_FORMAT_MONO14;
      return 0;
   }

   return -EINVAL;
}

static const char *ilumos_pixfmt_name(u32 reg)
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
 * from (0-2 RAW16, 3-5 RAW14, same three resolutions in the same order).
 *
 * Writing is skipped when the camera is already there, so a stream start that
 * changes nothing costs one read and leaves the camera untouched.
 */
static int ilumos_apply_pixel_format(struct ilumos *priv, u32 want)
{
   struct device *dev = &priv->i2c_client->dev;
   u32 current_fmt;
   int mode;
   int rc;

   rc = ilumos_read_register(priv, REG_PIXEL_FORMAT, &current_fmt);
   if (rc) {
      dev_err(dev, "PIXEL_FORMAT read failed (%d)\n", rc);
      return rc;
   }

   if (current_fmt != want) {
      rc = ilumos_write_register(priv, REG_PIXEL_FORMAT, want);
      if (rc) {
         dev_err(dev, "camera refused PIXEL_FORMAT 0x%08x %s (%d)\n",
                 want, ilumos_pixfmt_name(want), rc);
         return rc;
      }

      /* Read back rather than trust the write: the status word says the camera
       * accepted the transfer, not that it settled on the value we asked for. */
      rc = ilumos_read_register(priv, REG_PIXEL_FORMAT, &current_fmt);
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
               current_fmt, ilumos_pixfmt_name(current_fmt));
   }

   strncpy(priv->pixel_format, ilumos_pixfmt_name(current_fmt),
           sizeof(priv->pixel_format) - 1);
   priv->pixel_format[sizeof(priv->pixel_format) - 1] = '\0';

   mode = ilumos_find_frmfmt(priv->native_width, priv->native_height);
   if (mode >= 0) {
      if (current_fmt == PIXEL_FORMAT_MONO14)
         mode += 3;
      priv->tc_dev->s_data->sensor_mode_id = mode;
      priv->tc_dev->s_data->def_mode       = mode;
   }

   return 0;
}

static int ilumos_sensor_check(struct ilumos *priv)
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
      unsigned int attempts = ilumos_probe_attempts(dev);
      unsigned int attempt;
      rc = -EIO;

      for (attempt = 0; attempt < attempts; attempt++) {
         rc = ilumos_read_firmware(priv, buf, sizeof(buf));
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
   if (rc == 0) {
      for (i = sizeof(buf) - 1; i >= 0 && buf[i] == (u8)0xff; i--)
         buf[i] = '\0';
      strncpy(priv->firmware_version, (const char *)buf, sizeof(priv->firmware_version) - 1);
      priv->firmware_version[sizeof(priv->firmware_version) - 1] = '\0';
      dev_info(dev, "FPGA firmware version = %s\n", priv->firmware_version);
   } else {
      dev_err(dev, "FPGA firmware read failed\n");
      goto error_exit;
   }

   /* Pixel format the camera is currently in. It is only a starting point now:
    * VIDIOC_S_FMT can change it later, see ilumos_set_mode(). */
   if (ilumos_read_register(priv, REG_PIXEL_FORMAT, &read_data) == 0) {
      if (read_data == PIXEL_FORMAT_MONO14)
         is_raw14 = true;
      else if (read_data != PIXEL_FORMAT_MONO16)
         dev_warn(dev, "unknown PIXEL_FORMAT 0x%08x, assuming RAW16\n",
                  read_data);
      dev_info(dev, "PIXEL_FORMAT = 0x%08x %s\n", read_data,
               ilumos_pixfmt_name(read_data));
   } else {
      dev_warn(dev, "PIXEL_FORMAT read failed, assuming RAW16\n");
   }


   if (ilumos_read_register(priv, REG_IMG_WIDTH_R, &width) == 0) {
      if (ilumos_read_register(priv, REG_IMG_HEIGHT_R, &height) == 0) {
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

   strncpy(priv->pixel_format,
           ilumos_pixfmt_name(is_raw14 ? PIXEL_FORMAT_MONO14
                                       : PIXEL_FORMAT_MONO16),
           sizeof(priv->pixel_format) - 1);
   priv->pixel_format[sizeof(priv->pixel_format) - 1] = '\0';

   dev_info(dev, "mode=%d  pixel_format=%s\n", mode, priv->pixel_format);

   priv->native_width  = width;
   priv->native_height = height;

   /* Model name */
   if (ilumos_read_string(priv, REG_MODEL_NAME_R,
                                (u8 *)priv->model, sizeof(priv->model)) == 0) {
      for (i = sizeof(priv->model) - 1; i >= 0 &&
            (priv->model[i] == (char)0xff || priv->model[i] == '\0'); i--)
         priv->model[i] = '\0';
   } else {
      priv->model[0] = '\0';
      dev_warn(dev, "failed to read model name\n");
   }

   /* Serial number */
   if (ilumos_read_string(priv, REG_SERIAL_R,
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
   return ilumos_write_register(priv, REG_ACQ_START_W, 2);

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
static int ilumos_set_mode(struct tegracam_device *tc_dev)
{
   struct ilumos *priv = tegracam_get_privdata(tc_dev);
   struct camera_common_data *s_data = tc_dev->s_data;
   u32 want;
   int rc;

   dev_dbg(tc_dev->dev, "%s\n", __func__);

   if (!s_data->colorfmt)
      return 0;

   if (ilumos_pixfmt_to_reg(s_data->colorfmt->pix_fmt, &want)) {
      /* Not reachable through V4L2: ENUM_FMT only offers what the DT modes
       * declare, and those are Y16-BE and Y14. Leave the camera alone rather
       * than guess. */
      dev_warn(tc_dev->dev,
               "no camera pixel format for V4L2 0x%08x, leaving it unchanged\n",
               s_data->colorfmt->pix_fmt);
      return 0;
   }

   mutex_lock(&ilumos_gencp_lock);
   rc = priv->gencp_initialized ? ilumos_apply_pixel_format(priv, want) : -ENODEV;
   mutex_unlock(&ilumos_gencp_lock);
   return rc;
}

static int ilumos_start_streaming(struct tegracam_device *tc_dev)
{
   struct ilumos *priv = tegracam_get_privdata(tc_dev);
   u32 status;
   int rc;

   mutex_lock(&ilumos_gencp_lock);
   if (!priv->gencp_initialized) {
      rc = -ENODEV;
   } else {
      rc = ilumos_read_register(priv, REG_ACQ_STATUS_R, &status);
      if (!rc && status != 1)
         rc = ilumos_write_register(priv, REG_ACQ_START_W, 1);
   }
   mutex_unlock(&ilumos_gencp_lock);
   return rc;
}

static int ilumos_stop_streaming(struct tegracam_device *tc_dev)
{
   struct ilumos *priv = tegracam_get_privdata(tc_dev);
   int rc;

   mutex_lock(&ilumos_gencp_lock);
   rc = priv->gencp_initialized ? ilumos_write_register(priv, REG_ACQ_START_W, 2)
                              : -ENODEV;
   mutex_unlock(&ilumos_gencp_lock);
   /* Let VI finish the last DMA before teardown, as in iLumos. */
   msleep(50);
   return rc;
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

/*
 * Every pixel format this camera can be switched into without reloading the
 * module, one per line, in the same "'FOURCC' (description)" shape as
 * pixel_format -- of which this is the superset, and which keeps meaning "the
 * one the camera is in right now".
 *
 * Only iLumos has this attribute. On the other cameras the format is fixed once
 * the module is loaded, and its absence is what says so: a reader that finds no
 * pixel_formats has exactly one choice, the one in pixel_format. That is why
 * this is a separate attribute rather than a list inside pixel_format -- the
 * existing meaning stays the same on all four drivers.
 *
 * It cannot be derived from v4l2-ctl --list-formats: that lists what the device
 * tree modes declare, which is a superset (all our cameras declare several) and
 * says nothing about whether the camera can be told to switch.
 */
static ssize_t pixel_formats_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   return scnprintf(buf, PAGE_SIZE, "%s\n%s\n",
         ilumos_pixfmt_name(PIXEL_FORMAT_MONO16),
         ilumos_pixfmt_name(PIXEL_FORMAT_MONO14));
}
static DEVICE_ATTR_RO(pixel_formats);

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
 * iLumos uses GenCP-over-I2C through priv->io_handle, never
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

   priv = kzalloc(sizeof(struct ilumos), GFP_KERNEL);
   if (!priv)
      return -ENOMEM;

   kref_init(&priv->refcount);

   tc_dev = devm_kzalloc(dev, sizeof(struct tegracam_device), GFP_KERNEL);
   if (!tc_dev) {
      kref_put(&priv->refcount, ilumos_free);
      return -ENOMEM;
   }

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
      kref_put(&priv->refcount, ilumos_free);
      return err;
   }

   priv->tc_dev = tc_dev;
   priv->s_data = tc_dev->s_data;
   priv->subdev = &tc_dev->s_data->subdev;
   tegracam_set_privdata(tc_dev, (void *)priv);

   /* Initialize sensor and check GenCP communication */
   priv->io_handle.client = client;
   GENCPCLIENT_Configure(&priv->io_handle, 1024);
   mutex_lock(&ilumos_gencp_lock);
   /* Select the camera context without sending a preliminary request. */
   GENCPCLIENT_Select(&priv->io_handle);
   priv->gencp_initialized = true;
   ilumos_gencp_users++;
   err = ilumos_sensor_check(priv);
   if (err)
      ilumos_gencp_put(priv);
   mutex_unlock(&ilumos_gencp_lock);
   if (err) {
      dev_err(dev, "sensor check failed\n");
      tegracam_device_unregister(tc_dev);
      kref_put(&priv->refcount, ilumos_free);
      return err;
   }

   err = tegracam_v4l2subdev_register(tc_dev, true);
   if (err) {
      dev_err(dev, "tegra camera subdev registration failed\n");
      mutex_lock(&ilumos_gencp_lock);
      ilumos_gencp_put(priv);
      mutex_unlock(&ilumos_gencp_lock);
      tegracam_device_unregister(tc_dev);
      kref_put(&priv->refcount, ilumos_free);
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
            "ilumos-%d-%04x", client->adapter->nr, client->addr);
   priv->miscdev.minor  = MISC_DYNAMIC_MINOR;
   priv->miscdev.name   = priv->miscdev_name;
   priv->miscdev.fops   = &ilumos_cdev_fops;
   priv->miscdev.parent = dev;
   if (misc_register(&priv->miscdev)) {
      dev_warn(dev, "failed to register chardev; egCamCtrl.py will not work\n");
   } else {
      priv->misc_registered = true;
      dev_info(dev, "chardev registered at /dev/%s\n", priv->miscdev_name);
   }

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

   if (priv->misc_registered)
      misc_deregister(&priv->miscdev);

   mutex_lock(&ilumos_gencp_lock);
   ilumos_gencp_put(priv);
   mutex_unlock(&ilumos_gencp_lock);

   device_remove_file(dev, &dev_attr_firmware_version);
   device_remove_file(dev, &dev_attr_pixel_formats);
   device_remove_file(dev, &dev_attr_pixel_format);
   device_remove_file(dev, &dev_attr_resolution);
   device_remove_file(dev, &dev_attr_serial_number);
   device_remove_file(dev, &dev_attr_model);

   tegracam_v4l2subdev_unregister(priv->tc_dev);
   tegracam_device_unregister(priv->tc_dev);

   kref_put(&priv->refcount, ilumos_free);
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
