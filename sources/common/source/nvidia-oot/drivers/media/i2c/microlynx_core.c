/*
 * A V4L2 driver for Exosens Microlynx MIPI IR cameras.
 *
 * Based on Sony imx219 NVIDIA camera driver
 * Copyright (C) 2026 Exosens
 *
 */

#include <linux/i2c.h>
#include <linux/i2c-mux.h>
#include <linux/miscdevice.h>
#include <linux/mutex.h>
#include <linux/of_device.h>
#include <linux/gpio.h>
#include <linux/of_gpio.h>
#include <linux/uaccess.h>
#include <linux/version.h>
#include <media/tegracam_core.h>

#include "gencp-over-i2c/libunio.h"
#include "gencp-over-i2c/gencp_client.h"

#define PREFIX "microlynx"
#include "gencp-over-i2c/liblogger.h"

/* ---- GenCP userspace chardev (/dev/microlynx-<bus>-<addr>) ------------- */

/**
 * struct microlynx_reg_op - ioctl payload for 32-bit register read/write
 * @addr: GenCP register address
 * @val:  value written (WRITE_REG) or value returned (READ_REG)
 */
struct microlynx_reg_op {
	__u32 addr;
	__u32 val;
};

#define MICROLYNX_STR_MAX 256

/**
 * struct microlynx_str_op - ioctl payload for GenCP string read
 * @addr: GenCP register address of the string
 * @len:  number of bytes to read (clamped to MICROLYNX_STR_MAX)
 * @buf:  buffer filled with the string data on return
 */
struct microlynx_str_op {
	__u32 addr;
	__u32 len;
	__u8  buf[MICROLYNX_STR_MAX];
};

#define MICROLYNX_IOCTL_MAGIC    'M'
/* _IOWR('M', 1, struct microlynx_reg_op) */
#define MICROLYNX_IOCTL_READ_REG  _IOWR(MICROLYNX_IOCTL_MAGIC, 1, \
					struct microlynx_reg_op)
/* _IOW('M', 2, struct microlynx_reg_op) */
#define MICROLYNX_IOCTL_WRITE_REG _IOW(MICROLYNX_IOCTL_MAGIC,  2, \
					struct microlynx_reg_op)
/* _IOWR('M', 3, struct microlynx_str_op) */
#define MICROLYNX_IOCTL_READ_STR  _IOWR(MICROLYNX_IOCTL_MAGIC, 3, \
					struct microlynx_str_op)

/*
 * Module-level mutex: GENCPCLIENT uses process-global state (pRxBuffer,
 * pTxBuffer, unio_handle_ptr).  Serialise all GenCP calls behind this lock.
 *
 * Multi-camera workaround: GENCPCLIENT_Select() is called before every
 * GENCPCLIENT_ReadRegister / WriteRegister invocation (in cdev_ioctl and
 * start_streaming) to restore the global state to the correct camera's I2C
 * handle.  The long-term fix is to refactor gencp_client to per-instance
 * state.
 */
static DEFINE_MUTEX(microlynx_gencp_lock);

/* Microlynx specific registers */
#define REG_ACQ_START_W   0x500F0000
#define REG_ACQ_STOP_W    0x500F0004
#define REG_ACQ_STATUS_R  0x500F0008
#define REG_IMG_HEIGHT_RW 0x500E000C
#define REG_IMG_WIDTH_R   0x500E0008
#define REG_MIPI_ENA_R    0x50ff0010
#define REG_FIRW_VER_R    0xB0000000
#define REG_SERIAL_R      0x00000144
#define REG_MODEL_NAME_R  0x00000044
#define REG_PIX_ENDIAN_R  0x00040018  /* 0=LE (Y16), 1=BE (Y16_BE) */
#define REG_PIXEL_FORMAT  0x500e0018
#define PIXEL_FORMAT_MONO16 0x01100007u
#define PIXEL_FORMAT_MONO14 0x01100025u


static const struct of_device_id microlynx_of_match[] = {
   { .compatible = "exosens,microlynx", },
   { },
};
MODULE_DEVICE_TABLE(of, microlynx_of_match);

enum {
   MICROLYNX_MODE_1024x128_RAW16,
   MICROLYNX_MODE_1024x128_RAW14,
};

static const int microlynx_351fps[] = {
   351,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
static const struct camera_common_frmfmt microlynx_frmfmt[] = {
   {{1024, 128},  microlynx_351fps,  1, 0, MICROLYNX_MODE_1024x128_RAW16},
   {{1024, 128},  microlynx_351fps, 1, 0, MICROLYNX_MODE_1024x128_RAW14},
};

static const u32 ctrl_cid_list[] = {
#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
   TEGRA_CAMERA_CID_GAIN,
   TEGRA_CAMERA_CID_EXPOSURE,
   TEGRA_CAMERA_CID_FRAME_RATE,
#endif
   TEGRA_CAMERA_CID_SENSOR_MODE_ID,
};

struct microlynx {
   struct i2c_client    *i2c_client;
   struct v4l2_subdev      *subdev;
   struct camera_common_data  *s_data;
   struct tegracam_device     *tc_dev;
   struct unio_handle      io_handle;
   u32    line_height;
   u32    native_width;
   bool   gencp_initialized;
   char   model[64];
   char   serial_number[64];
   char   pixel_format[64];
   char   firmware_version[32];

   /* GenCP chardev — /dev/microlynx-<bus>-<addr> */
   struct miscdevice    miscdev;
   char                 miscdev_name[32];
};

static int microlynx_sensor_check(struct microlynx *priv)
{
   struct device *dev = &priv->i2c_client->dev;
   int status;
   u32 read_data = 0;
   priv->io_handle.client = priv->i2c_client;

   /* INIT the gencp client */
   GENCPCLIENT_Init(&priv->io_handle);

   /* FPGA test read - check if MIPI is enabled */
   status = GENCPCLIENT_ReadRegister(REG_MIPI_ENA_R, &read_data);
   if (status == 0) {
      if (read_data == 0x1) {
         PRINT_INFO("MIPI is enabled, status = %#08x\n", read_data);
      } else {
         PRINT_ERROR("MIPI is not enabled on this camera, license missing? Exiting...\n");
         goto error_exit;
      }
   } else {
      PRINT_INFO("MIPI status read failed\n");
      goto error_exit;
   }

   /* FPGA firmware read */
   status = GENCPCLIENT_ReadString(REG_FIRW_VER_R,
         (u8 *)priv->firmware_version, sizeof(priv->firmware_version));
   if (status == 0) {
      int i;
      for (i = sizeof(priv->firmware_version) - 1; i >= 0 &&
            (priv->firmware_version[i] == (char)0xff || priv->firmware_version[i] == '\0'); i--)
         priv->firmware_version[i] = '\0';
   } else {
      priv->firmware_version[0] = '\0';
      PRINT_INFO("FPGA firmware read failed\n");
   }

   /* Resolution - Set Height */
   device_property_read_u32(dev, "line-height", &priv->line_height);
   if (priv->line_height == 0)
      priv->line_height = 128; /* Default value */
   dev_info(dev, "line height read: %u\n", priv->line_height);

   /* Height check */
   status = GENCPCLIENT_ReadRegister(REG_IMG_HEIGHT_RW, &read_data);
   if (status == 0) {
      if (read_data == priv->line_height) {
         PRINT_INFO("Camera and driver line heights match, height = %#08x\n", read_data);
      } else {
         PRINT_ERROR("Camera and driver line heights don't match.\n");
         PRINT_ERROR("Camera = %u, Driver = %u\n", read_data, priv->line_height);
      }
   } else {
      PRINT_INFO("Register read failed\n");
      goto error_exit;
   }

   /* Set camera width */
   priv->native_width = 1024;
   status = GENCPCLIENT_ReadRegister(REG_IMG_WIDTH_R, &read_data);
   if (status == 0) {
      priv->native_width = read_data;
   } else {
      PRINT_INFO("Register read failed\n");
      goto error_exit;
   }

   /* Read model name */
   status = GENCPCLIENT_ReadString(REG_MODEL_NAME_R,
         (u8 *)priv->model, sizeof(priv->model));
   if (status == 0) {
      int i;
      for (i = sizeof(priv->model) - 1; i >= 0 &&
            (priv->model[i] == (char)0xff || priv->model[i] == '\0'); i--)
         priv->model[i] = '\0';
   } else {
      priv->model[0] = '\0';
      dev_warn(dev, "failed to read model name\n");
   }

   /* Read serial number */
   status = GENCPCLIENT_ReadString(REG_SERIAL_R,
         (u8 *)priv->serial_number, sizeof(priv->serial_number));
   if (status == 0) {
      int i;
      for (i = sizeof(priv->serial_number) - 1; i >= 0 &&
            (priv->serial_number[i] == (char)0xff || priv->serial_number[i] == '\0'); i--)
         priv->serial_number[i] = '\0';
   } else {
      priv->serial_number[0] = '\0';
      dev_warn(dev, "failed to read serial number\n");
   }

   // Default pixel format
   priv->tc_dev->s_data->sensor_mode_id = MICROLYNX_MODE_1024x128_RAW16;
   priv->tc_dev->s_data->def_mode       = MICROLYNX_MODE_1024x128_RAW16;
   strncpy(priv->pixel_format, "'Y16 ' (16-bit Greyscale)",
         sizeof(priv->pixel_format) - 1);

   status = GENCPCLIENT_ReadRegister(REG_PIXEL_FORMAT, &read_data);
   if (status == 0) {
      if (read_data == PIXEL_FORMAT_MONO14) {
         priv->tc_dev->s_data->sensor_mode_id = MICROLYNX_MODE_1024x128_RAW14;
         priv->tc_dev->s_data->def_mode       = MICROLYNX_MODE_1024x128_RAW14;
         strncpy(priv->pixel_format, "'Y14 ' (14-bit Greyscale)",
               sizeof(priv->pixel_format) - 1);
         PRINT_INFO("Pixel format: Y14\n");
      } else {
         PRINT_INFO("Pixel format: Y16 (CSI little-endian)\n");
      }
   }

   /* tegracam_device_register() already ran and set s_data->colorfmt from
    * microlynx_frmfmt[0] (RAW16) unconditionally — updating sensor_mode_id/
    * def_mode above doesn't re-resolve it, so V4L2 G_FMT would keep
    * reporting Y16 even after detecting Y14 here. Force it explicitly,
    * same pattern as eg_ec_mipi_src.c's probe. */
   {
      const struct camera_common_colorfmt *colorfmt;
      u32 v4l2_pixfmt = (priv->tc_dev->s_data->def_mode == MICROLYNX_MODE_1024x128_RAW14)
                        ? V4L2_PIX_FMT_Y14 : V4L2_PIX_FMT_Y16;

      colorfmt = camera_common_find_pixelfmt(v4l2_pixfmt);
      if (colorfmt)
         priv->tc_dev->s_data->colorfmt = colorfmt;
   }

   priv->pixel_format[sizeof(priv->pixel_format) - 1] = '\0';

   priv->gencp_initialized = true;
   return 0;

error_exit:
   dev_err(dev, "Probing failed");
   GENCPCLIENT_Cleanup();
   priv->gencp_initialized = false;
   return -EIO;
}

static int microlynx_set_group_hold(struct tegracam_device *tc_dev, bool val)
{
   /* group hold is not supported */
   dev_dbg(tc_dev->dev, "%s val=%d\n", __func__, val);
   return 0;
}

#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
static int microlynx_set_gain(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int microlynx_set_frame_rate(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}

static int microlynx_set_exposure(struct tegracam_device *tc_dev, s64 val)
{
   dev_dbg(tc_dev->dev, "%s val=%lld\n", __func__, val);
   return 0;
}
#endif

static struct tegracam_ctrl_ops microlynx_ctrl_ops = {
   .numctrls = ARRAY_SIZE(ctrl_cid_list),
   .ctrl_cid_list = ctrl_cid_list,
#if LINUX_VERSION_CODE > KERNEL_VERSION(5,15,0)
   .set_gain = microlynx_set_gain,
   .set_exposure = microlynx_set_exposure,
   .set_frame_rate = microlynx_set_frame_rate,
#endif
   .set_group_hold = microlynx_set_group_hold,
};

static int microlynx_power_on(struct camera_common_data *s_data)
{
   /* Power is not managed here */
   struct device *dev = s_data->dev;
   dev_dbg(dev, "%s\n", __func__);
   return 0;
}

static int microlynx_power_off(struct camera_common_data *s_data)
{
   /* Power is not managed here */
   struct device *dev = s_data->dev;
   dev_dbg(dev, "%s\n", __func__);
   return 0;
}

static int microlynx_power_put(struct tegracam_device *tc_dev)
{
   /* Power is not managed here */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static int microlynx_power_get(struct tegracam_device *tc_dev)
{
   /* Power is not managed here */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static struct camera_common_pdata *microlynx_parse_dt(
      struct tegracam_device *tc_dev)
{
   struct device *dev = tc_dev->dev;
   struct device_node *np = dev->of_node;
   struct camera_common_pdata *board_priv_pdata;
   const struct of_device_id *match;

   if (!np)
      return NULL;

   match = of_match_device(microlynx_of_match, dev);
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

static int microlynx_set_mode(struct tegracam_device *tc_dev)
{
   /* Configuration is done independently by a control application */
   dev_dbg(tc_dev->dev, "%s\n", __func__);
   return 0;
}

static int microlynx_start_streaming(struct tegracam_device *tc_dev)
{
   struct microlynx *priv = tegracam_get_privdata(tc_dev);
   int status = 0;
   u32 read_data;

   dev_dbg(tc_dev->dev, "%s\n", __func__);

   if (!priv->gencp_initialized) {
      dev_err(tc_dev->dev, "GenCP not initialized\n");
      return -EIO;
   }

   /* Restore global GenCP state to this camera's I2C handle.
    * Required when multiple Microlynx cameras are probed: the global
    * unio_handle_ptr / gGencpInitWasSuccessfull are overwritten during
    * probe of the last camera (which may have failed). */
   GENCPCLIENT_Select(&priv->io_handle);

   /* Camera should always be streaming. But we can check that. */
   status = GENCPCLIENT_ReadRegister(REG_ACQ_STATUS_R, &read_data);
   if (status == 0) {
      if (read_data != 0x1) {
         PRINT_INFO("Acquisition is off, re-enabling it.\n");
         status = GENCPCLIENT_WriteRegister(REG_ACQ_START_W, 0x1);
      }
   } else {
      PRINT_INFO("Register read failed\n");
   }

   return 0;
}

static int microlynx_stop_streaming(struct tegracam_device *tc_dev)
{
   struct microlynx *priv = tegracam_get_privdata(tc_dev);

   dev_dbg(tc_dev->dev, "%s\n", __func__);

   if (!priv->gencp_initialized) {
      dev_err(tc_dev->dev, "GenCP not initialized\n");
      return -EIO;
   }

   /* Note: We don't actually stop the camera, just acknowledge the call */
   return 0;
}

static struct camera_common_sensor_ops microlynx_common_ops = {
   .numfrmfmts = ARRAY_SIZE(microlynx_frmfmt),
   .frmfmt_table = microlynx_frmfmt,
   .power_on = microlynx_power_on,
   .power_off = microlynx_power_off,
   .parse_dt = microlynx_parse_dt,
   .power_get = microlynx_power_get,
   .power_put = microlynx_power_put,
   .set_mode = microlynx_set_mode,
   .start_streaming = microlynx_start_streaming,
   .stop_streaming = microlynx_stop_streaming,
};

static ssize_t model_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct microlynx *priv = (struct microlynx *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->model);
}
static DEVICE_ATTR_RO(model);

static ssize_t serial_number_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct microlynx *priv = (struct microlynx *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->serial_number);
}
static DEVICE_ATTR_RO(serial_number);

static ssize_t resolution_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct microlynx *priv = (struct microlynx *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%ux%u\n",
         priv->native_width, priv->line_height);
}
static DEVICE_ATTR_RO(resolution);

static ssize_t pixel_format_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct microlynx *priv = (struct microlynx *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->pixel_format);
}
static DEVICE_ATTR_RO(pixel_format);

static ssize_t firmware_version_show(struct device *dev,
      struct device_attribute *attr, char *buf)
{
   struct camera_common_data *s_data = to_camera_common_data(dev);
   struct microlynx *priv = (struct microlynx *)s_data->priv;

   return scnprintf(buf, PAGE_SIZE, "%s\n", priv->firmware_version);
}
static DEVICE_ATTR_RO(firmware_version);

static int microlynx_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
   return 0;
}

static const struct v4l2_subdev_internal_ops microlynx_subdev_internal_ops = {
   .open = microlynx_open,
};

/*
 * microlynx does raw i2c_master_send/recv (GenCP-over-I2C) via
 * priv->i2c_client, never regmap_read/write. This config only exists so
 * tegracam_core's devm_regmap_init_i2c() has a non-NULL config to work
 * with on stock NVIDIA/vendor kernels that don't carry the EG NULL-config
 * guard.
 */
static const struct regmap_config microlynx_dummy_regmap_config = {
   .reg_bits = 8,
   .val_bits = 8,
};

/* ---- GenCP chardev file operations ------------------------------------ */

static int microlynx_cdev_open(struct inode *inode, struct file *file)
{
   /*
    * The misc layer sets file->private_data to the struct miscdevice *.
    * Use container_of to reach the enclosing struct microlynx.
    */
   struct microlynx *priv =
      container_of(file->private_data, struct microlynx, miscdev);
   file->private_data = priv;
   return 0;
}

static int microlynx_cdev_release(struct inode *inode, struct file *file)
{
   return 0;
}

static long microlynx_cdev_ioctl(struct file *file, unsigned int cmd,
               unsigned long arg)
{
   struct microlynx *priv = file->private_data;
   int ret = 0;

   if (!priv->gencp_initialized)
      return -ENODEV;

   mutex_lock(&microlynx_gencp_lock);
   /* Restore global GenCP state to this camera's I2C handle (multi-camera). */
   GENCPCLIENT_Select(&priv->io_handle);

   switch (cmd) {
   case MICROLYNX_IOCTL_READ_REG: {
      struct microlynx_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = GENCPCLIENT_ReadRegister(op.addr, &op.val);
      if (ret == 0 && copy_to_user((void __user *)arg, &op, sizeof(op)))
         ret = -EFAULT;
      break;
   }
   case MICROLYNX_IOCTL_WRITE_REG: {
      struct microlynx_reg_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      ret = GENCPCLIENT_WriteRegister(op.addr, op.val);
      break;
   }
   case MICROLYNX_IOCTL_READ_STR: {
      struct microlynx_str_op op;

      if (copy_from_user(&op, (void __user *)arg, sizeof(op))) {
         ret = -EFAULT;
         break;
      }
      op.len = min_t(u32, op.len, MICROLYNX_STR_MAX);
      ret = GENCPCLIENT_ReadString(op.addr, op.buf, op.len);
      if (ret == 0 && copy_to_user((void __user *)arg, &op, sizeof(op)))
         ret = -EFAULT;
      break;
   }
   default:
      ret = -ENOTTY;
      break;
   }

   mutex_unlock(&microlynx_gencp_lock);
   return ret;
}

static const struct file_operations microlynx_cdev_fops = {
   .owner          = THIS_MODULE,
   .open           = microlynx_cdev_open,
   .release        = microlynx_cdev_release,
   .unlocked_ioctl = microlynx_cdev_ioctl,
};

/* ----------------------------------------------------------------------- */

#if defined(NV_I2C_DRIVER_STRUCT_PROBE_WITHOUT_I2C_DEVICE_ID_ARG) /* Linux 6.3 */
static int microlynx_probe(struct i2c_client *client)
#else
static int microlynx_probe(struct i2c_client *client,
      const struct i2c_device_id *id)
#endif
{
   struct device *dev = &client->dev;
   struct tegracam_device *tc_dev;
   struct microlynx *priv;
   int err;

   dev_info(dev, "probing v4l2 microlynx sensor at addr 0x%0x\n", client->addr);

   if (!IS_ENABLED(CONFIG_OF) || !client->dev.of_node)
      return -EINVAL;

   priv = devm_kzalloc(dev, sizeof(struct microlynx), GFP_KERNEL);
   if (!priv)
      return -ENOMEM;

   tc_dev = devm_kzalloc(dev, sizeof(struct tegracam_device), GFP_KERNEL);
   if (!tc_dev)
      return -ENOMEM;

   priv->i2c_client = tc_dev->client = client;
   tc_dev->dev = dev;
   strncpy(tc_dev->name, "microlynx", sizeof(tc_dev->name));
   tc_dev->dev_regmap_config = &microlynx_dummy_regmap_config;
   tc_dev->sensor_ops = &microlynx_common_ops;
   tc_dev->v4l2sd_internal_ops = &microlynx_subdev_internal_ops;
   tc_dev->tcctrl_ops = &microlynx_ctrl_ops;

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
   err = microlynx_sensor_check(priv);
   if (err) {
      dev_err(dev, "sensor check failed\n");
      tegracam_device_unregister(tc_dev);
      return err;
   }

   err = tegracam_v4l2subdev_register(tc_dev, true);
   if (err) {
      dev_err(dev, "tegra camera subdev registration failed\n");
      GENCPCLIENT_Cleanup();
      tegracam_device_unregister(tc_dev);
      return err;
   }

   device_create_file(dev, &dev_attr_model);
   device_create_file(dev, &dev_attr_serial_number);
   device_create_file(dev, &dev_attr_resolution);
   device_create_file(dev, &dev_attr_pixel_format);
   device_create_file(dev, &dev_attr_firmware_version);

   /* Register GenCP chardev for userspace access */
   snprintf(priv->miscdev_name, sizeof(priv->miscdev_name),
         "microlynx-%d-%04x", client->adapter->nr, client->addr);
   priv->miscdev.minor  = MISC_DYNAMIC_MINOR;
   priv->miscdev.name   = priv->miscdev_name;
   priv->miscdev.fops   = &microlynx_cdev_fops;
   priv->miscdev.parent = dev;
   if (misc_register(&priv->miscdev))
      dev_warn(dev, "failed to register GenCP chardev; userspace access via microlynxCtrl.py will not work\n");
   else
      dev_info(dev, "GenCP chardev registered at /dev/%s\n",
            priv->miscdev_name);

   dev_info(dev, "Registered microlynx device (width=%u, height=%u)\n",
         priv->native_width, priv->line_height);
   return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
static int microlynx_remove(struct i2c_client *client)
#else
static void microlynx_remove(struct i2c_client *client)
#endif
{
   struct device *dev = &client->dev;
   struct camera_common_data *s_data = to_camera_common_data(&client->dev);
   struct microlynx *priv = (struct microlynx *)s_data->priv;

   device_remove_file(dev, &dev_attr_firmware_version);
   device_remove_file(dev, &dev_attr_model);
   device_remove_file(dev, &dev_attr_serial_number);
   device_remove_file(dev, &dev_attr_resolution);
   device_remove_file(dev, &dev_attr_pixel_format);

   misc_deregister(&priv->miscdev);

   tegracam_v4l2subdev_unregister(priv->tc_dev);
   tegracam_device_unregister(priv->tc_dev);

   if (priv->gencp_initialized)
      GENCPCLIENT_Cleanup();

   dev_info(dev, "Removed microlynx device\n");

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
   return 0;
#endif
}

static const struct i2c_device_id microlynx_id[] = {
   { "microlynx", 0 },
   { }
};
MODULE_DEVICE_TABLE(i2c, microlynx_id);

static struct i2c_driver microlynx_i2c_driver = {
   .driver = {
      .name = "microlynx",
      .owner = THIS_MODULE,
      .of_match_table = of_match_ptr(microlynx_of_match),
   },
   .probe = microlynx_probe,
   .remove = microlynx_remove,
   .id_table = microlynx_id,
};
module_i2c_driver(microlynx_i2c_driver);

MODULE_AUTHOR("Exosens");
MODULE_DESCRIPTION("Exosens MIPI camera I2C driver for Microlynx cameras");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");
