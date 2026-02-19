/*
 * A V4L2 driver for Exosens ilumos MIPI IR cameras.
 *
 * Based on Sony imx219 NVIDIA camera driver
 * Copyright (C) 2026 Exosens
 *
 */

#include <linux/i2c.h>
#include <linux/i2c-mux.h>
#include <linux/of_device.h>
#include <linux/gpio.h>
#include <linux/of_gpio.h>
#include <linux/version.h>
#include <media/tegracam_core.h>

/* ilumos specific registers */
#define REG_ACQ_START_W   0x50000A00
#define REG_ACQ_STATUS_R  0x50000A20
#define REG_IMG_HEIGHT_RW 0x50000004
#define REG_IMG_WIDTH_RW  0x50000000
#define REG_FIRW_VER_R    0x10000000
#define REG_SERIAL_R      0x00144
#define REG_MODEL_NAME_R  0x00044

static const struct of_device_id ilumos_of_match[] = {
   { .compatible = "exosens,ilumos", },
   { },
};
MODULE_DEVICE_TABLE(of, ilumos_of_match);

enum {
   ILUMOS_MODE_2048x2048_RAW16,
   ILUMOS_MODE_2048x1088_RAW16,
};

static const int ilumos_60fps[] = {
   60,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
static const struct camera_common_frmfmt ilumos_frmfmt[] = {
   {{2048, 2048}, ilumos_60fps, 1, 0, ILUMOS_MODE_2048x2048_RAW16},
   {{2048, 1088}, ilumos_60fps, 1, 0, ILUMOS_MODE_2048x1088_RAW16},
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
   u32            native_width;
   u32            native_height;
};

static int ilumos_i2c_read(struct i2c_client *client, u32 reg, u8 *dst, u16 len)
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

static int ilumos_i2c_write32(struct i2c_client *client, u32 reg, u32 val)
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


static int ilumos_sensor_check(struct ilumos *priv)
{
   struct device *dev = &priv->i2c_client->dev;
   int status, mode, i;
   u8 buf[64];
   u32 width, height;

   /* FPGA firmware read */
   status = ilumos_i2c_read(priv->i2c_client, REG_FIRW_VER_R,
         buf, sizeof(buf));
   if (status < 0)
   {
      goto error_exit;
   }
   for (i = sizeof(buf) - 1; i >= 0 && buf[i] == (u8)0xff; i--)
      buf[i] = '\0';
   strncpy(priv->firmware_version, buf, sizeof(priv->firmware_version) - 1);
   priv->firmware_version[sizeof(priv->firmware_version) - 1] = '\0';

   status = ilumos_i2c_read(priv->i2c_client, REG_IMG_WIDTH_RW,
         (u8 *)&width, sizeof(width));
   if (status < 0)
   {
      goto error_exit;
   }

   status = ilumos_i2c_read(priv->i2c_client, REG_IMG_HEIGHT_RW,
         (u8 *)&height, sizeof(height));
   if (status < 0)
   {
      goto error_exit;
   }

   mode = ilumos_find_frmfmt(width, height);
   if (mode < 0) {
      goto error_exit;
   }

   priv->native_width = width;
   priv->native_height = height;

   /* Read model name */
   status = ilumos_i2c_read(priv->i2c_client, REG_MODEL_NAME_R,
         (u8 *)priv->model, sizeof(priv->model));
   if (status < 0) {
      priv->model[0] = '\0';
      dev_warn(dev, "failed to read model name\n");
   } else {
      for (i = sizeof(priv->model) - 1; i >= 0 &&
            (priv->model[i] == (char)0xff || priv->model[i] == '\0'); i--)
         priv->model[i] = '\0';
   }

   /* Read serial number */
   status = ilumos_i2c_read(priv->i2c_client, REG_SERIAL_R,
         (u8 *)priv->serial_number, sizeof(priv->serial_number));
   if (status < 0) {
      priv->serial_number[0] = '\0';
      dev_warn(dev, "failed to read serial number\n");
   } else {
      for (i = sizeof(priv->serial_number) - 1; i >= 0 &&
            (priv->serial_number[i] == (char)0xff || priv->serial_number[i] == '\0'); i--)
         priv->serial_number[i] = '\0';
   }

   return 0;

error_exit:
   dev_err(dev, "Probing failed");
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

   status = ilumos_i2c_read(priv->i2c_client, REG_ACQ_STATUS_R,
         (u8 *)&read_data, sizeof(read_data));
   if (status == 0) {
      if (read_data != 0x1) {
         status = ilumos_i2c_write32(priv->i2c_client, REG_ACQ_START_W, 1);
      }
   } else {
      dev_err(tc_dev->dev, "%s : Register read failed\n", __func__);
   }

   return 0;
}

static int ilumos_stop_streaming(struct tegracam_device *tc_dev)
{
   dev_dbg(tc_dev->dev, "%s\n", __func__);

   /* Note: We don't actually stop the camera, just acknowledge the call */
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
   return scnprintf(buf, PAGE_SIZE, "'Y16 ' (16-bit Greyscale)\n");
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

static int ilumos_probe(struct i2c_client *client,
      const struct i2c_device_id *id)
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
   tc_dev->dev_regmap_config = NULL;
   tc_dev->sensor_ops = &ilumos_common_ops;
   tc_dev->v4l2sd_internal_ops = &ilumos_subdev_internal_ops;
   tc_dev->tcctrl_ops = &ilumos_ctrl_ops;

   err = tegracam_device_register(tc_dev);
   if (err) {
      dev_err(dev, "tegra camera driver registration failed\n");
      return err;
   }

   tc_dev->s_data->i2c_client = client;
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
MODULE_DESCRIPTION("Exosens MIPI camera I2C driver for ilumos IR cameras");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");
