/*
 * A V4L2 driver for Exosens Microlynx MIPI IR cameras.
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

#include "gencp-over-i2c/libunio.h"
#include "gencp-over-i2c/gencp_client.h"

#define PREFIX "microlynx"
#include "gencp-over-i2c/liblogger.h"

/* Microlynx specific registers */
#define REG_ACQ_START_W   0x500F0000
#define REG_ACQ_STOP_W    0x500F0004
#define REG_ACQ_STATUS_R  0x500F0008
#define REG_IMG_HEIGHT_RW 0x500E000C
#define REG_IMG_WIDTH_R   0x500E0008
#define REG_MIPI_ENA_R    0x50ff0010
#define REG_FIRW_VER_R    0x50FF0000

static const struct of_device_id microlynx_of_match[] = {
	{ .compatible = "exosens,microlynx", },
	{ },
};
MODULE_DEVICE_TABLE(of, microlynx_of_match);

enum {
	MICROLYNX_MODE_1024x128_RAW16,
};

static const int microlynx_60fps[] = {
	60,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
static const struct camera_common_frmfmt microlynx_frmfmt[] = {
	{{1024, 128},	microlynx_60fps, 1, 0, MICROLYNX_MODE_1024x128_RAW16},
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
	struct i2c_client		*i2c_client;
	struct v4l2_subdev		*subdev;
	struct camera_common_data	*s_data;
	struct tegracam_device		*tc_dev;
	struct unio_handle		io_handle;
	u32				line_height;
	u32				native_width;
	bool				gencp_initialized;
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
	status = GENCPCLIENT_ReadRegister(REG_FIRW_VER_R, &read_data);
	if (status == 0) {
		PRINT_INFO("FPGA firmware version = %#08x\n", read_data);
	} else {
		PRINT_INFO("FPGA firmware read failed\n");
		goto error_exit;
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

static int microlynx_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
	return 0;
}

static const struct v4l2_subdev_internal_ops microlynx_subdev_internal_ops = {
	.open = microlynx_open,
};

static int microlynx_probe(struct i2c_client *client,
	const struct i2c_device_id *id)
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
	tc_dev->dev_regmap_config = NULL;
	tc_dev->sensor_ops = &microlynx_common_ops;
	tc_dev->v4l2sd_internal_ops = &microlynx_subdev_internal_ops;
	tc_dev->tcctrl_ops = &microlynx_ctrl_ops;

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
MODULE_DESCRIPTION("Exosens MIPI camera I2C driver for Microlynx IR cameras");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");
