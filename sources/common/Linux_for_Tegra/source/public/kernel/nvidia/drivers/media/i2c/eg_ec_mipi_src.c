/*
 * A V4L2 driver for Xenics Exosens MIPI EngineCore cameras.
 *
 * Based on Sony imx219 NVIDIA camera driver
 * Copyright Copyright (C) 2023 Xenics Exosens
 *
 */

//#define DEBUG
#include <linux/i2c.h>
#include <linux/i2c-mux.h>
#include <linux/of_device.h>
#include <linux/gpio.h>
#include <linux/of_gpio.h>
#include <media/tegracam_core.h>
#include "ecctrl_i2c_common.h"

#define MAX_I2C_CLIENTS_NUMBER 128

static const struct of_device_id eg_ec_mipi_of_match[] = {
	{ .compatible = "xenics,eg-ec-mipi", },
	{ },
};
MODULE_DEVICE_TABLE(of, eg_ec_mipi_of_match);

enum {
	EC_MIPI_MODE_640x480_RAW16,
	EC_MIPI_MODE_640x480_RGB888,
	EC_MIPI_MODE_640x480_YUYV,
	EC_MIPI_MODE_1280x1024_RAW16,
	EC_MIPI_MODE_1280x1024_RGB888,
	EC_MIPI_MODE_1280x1024_YUYV,
};

/*
 * WARNING: frmfmt ordering need to match mode definition in
 * device tree!
 */
static const struct camera_common_frmfmt eg_ec_mipi_frmfmt[] = {
	{{640, 480},	NULL, 0, 0, EC_MIPI_MODE_640x480_RAW16},
	{{640, 480},	NULL, 0, 0, EC_MIPI_MODE_640x480_RGB888},
	{{640, 480},	NULL, 0, 0, EC_MIPI_MODE_640x480_YUYV},
	{{1280, 1024},	NULL, 0, 0, EC_MIPI_MODE_1280x1024_RAW16},
	{{1280, 1024},	NULL, 0, 0, EC_MIPI_MODE_1280x1024_RGB888},
	{{1280, 1024},	NULL, 0, 0, EC_MIPI_MODE_1280x1024_YUYV},
};


static const u32 ctrl_cid_list[] = {
	TEGRA_CAMERA_CID_SENSOR_MODE_ID,
};

struct eg_ec_mipi {
	struct i2c_client		*i2c_client;
	struct v4l2_subdev		*subdev;
	struct camera_common_data	*s_data;
	struct tegracam_device		*tc_dev;
};

struct eg_ec_i2c_client {
	struct i2c_client *i2c_client;
	char chnod_name[128];
	int i2c_locked ;
	int chnod_major_number;
	dev_t chnod_device_number;
	struct class *pClass_chnod;
};

struct eg_ec_i2c_client i2c_clients[MAX_I2C_CLIENTS_NUMBER];

static ssize_t eg_ec_chnod_read(
                        struct file *file_ptr
                       , char __user *user_buffer
                       , size_t count
                       , loff_t *position)
{
	int ret = -EINVAL;
	int i;
	u8 *buffer_i2c = NULL;

    // printk( KERN_NOTICE "eg-ec chnod: Device file read at offset = %i, bytes count = %u\n"
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

static ssize_t eg_ec_chnod_write(
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
			// printk( KERN_NOTICE "eg-ec chnod: Device file write at offset = %i, bytes count = %u\n"
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

int eg_ec_chnod_open (struct inode * pInode, struct file * file)
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

int eg_ec_chnod_release (struct inode * pInode, struct file * file)
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

static long eg_ec_chnod_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	int i;
	switch (cmd) {
		case ECCTRL_I2C_TIMEOUT_SET:
		{
			for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
			{
				if (strcmp(i2c_clients[i].chnod_name, file->f_path.dentry->d_name.name) == 0)
				{
					i2c_clients[i].i2c_client->adapter->timeout = (int)arg;
					return 0;
				}
			}
			return -EINVAL;
		}
		default:
		{
			return -EINVAL;
		}
	}
}


static struct file_operations eg_ec_chnod_register_fops = 
{
   .owner   = THIS_MODULE,
   .read    = eg_ec_chnod_read,
   .write   = eg_ec_chnod_write,
   .open    = eg_ec_chnod_open,
   .release = eg_ec_chnod_release,
	.unlocked_ioctl = eg_ec_chnod_ioctl,
};
static inline int eg_ec_chnod_register_device(int i2c_ind)
{
	struct device *pDev;
    int result = 0;
    result = register_chrdev( 0, i2c_clients[i2c_ind].chnod_name, &eg_ec_chnod_register_fops );
    if( result < 0 )
    {
            printk( KERN_WARNING "eg-ec register chnod:  can\'t register character device with error code = %i\n", result );
            return result;
    }
    i2c_clients[i2c_ind].chnod_major_number = result;
    printk( KERN_DEBUG "eg-ec register chnod: registered character device with major number = %i and minor numbers 0...255\n", i2c_clients[i2c_ind].chnod_major_number );

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


static inline int eg_ec_mipi_write_reg(struct i2c_client * i2c_client, uint16_t address, uint8_t *data, int size)
{
	ecctrl_i2c_t args;
	int i;
	int err;
	for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
	{
		if (i2c_clients[i].i2c_client == i2c_client)
		{
			if (i2c_clients[i].i2c_locked == 0)
			{
				i2c_clients[i].i2c_locked = 1;
				__ecctrl_i2c_timeout_set(i2c_client, 0);
				args.data_address = address;
				args.data = data;
				args.data_size = size;
				args.i2c_timeout = 0;
				args.i2c_tries_max = -1;
				args.cb = NULL;
				err = __ecctrl_i2c_write_reg(i2c_client, &args);
				i2c_clients[i].i2c_locked = 0;
				return err;
			}
			else
			{
				return -EBUSY;
			}
		}
	}
	return -EINVAL;
}

static inline int eg_ec_mipi_read_reg(struct i2c_client * i2c_client, uint16_t address, uint8_t *data, uint8_t size)
{
	ecctrl_i2c_t args;
	int i;
	int err;
	for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
	{
		if (i2c_clients[i].i2c_client == i2c_client)
		{
			if (i2c_clients[i].i2c_locked == 0)
			{
				i2c_clients[i].i2c_locked = 1;
				__ecctrl_i2c_timeout_set(i2c_client, 0);
				args.data_address = address;
				args.data = data;
				args.data_size = size;
				args.i2c_timeout = 0;
				args.i2c_tries_max = -1;
				args.cb = NULL;
				err = __ecctrl_i2c_read_reg(i2c_client, &args);
				i2c_clients[i].i2c_locked = 0;
				return err;
			}
			else
			{
				return -EBUSY;
			}
		}
	}
	return -EINVAL;
}

static inline int eg_ec_mipi_write_fifo(struct i2c_client * i2c_client, uint16_t address, uint8_t *data, uint32_t size)
{
	ecctrl_i2c_t args;
	int i;
	int err;
	for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
	{
		if (i2c_clients[i].i2c_client == i2c_client)
		{
			if (i2c_clients[i].i2c_locked == 0)
			{
				i2c_clients[i].i2c_locked = 1;
				__ecctrl_i2c_timeout_set(i2c_client, 0);
				args.data_address = address;
				args.data = data;
				args.data_size = size;
				args.i2c_timeout = 0;
				args.i2c_tries_max = 0;
				args.cb = NULL;
				args.fifo_flags = FIFO_FLAG_START | FIFO_FLAG_END;
				err = __ecctrl_i2c_write_fifo(i2c_client, &args);
				i2c_clients[i].i2c_locked = 0;
				return err;
			}
			else
			{
				return -EBUSY;
			}
		}
	}
	return -EINVAL;

}

static inline int eg_ec_mipi_read_fifo(struct i2c_client * i2c_client, uint16_t address, uint8_t *data, uint32_t size)
{
	ecctrl_i2c_t args;
	int i;
	int err;
	for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
	{
		if (i2c_clients[i].i2c_client == i2c_client)
		{
			if (i2c_clients[i].i2c_locked == 0)
			{
				i2c_clients[i].i2c_locked = 1;
				__ecctrl_i2c_timeout_set(i2c_client, 0);
				args.data_address = address;
				args.data = data;
				args.data_size = size;
				args.i2c_timeout = 0;
				args.i2c_tries_max = -1;
				args.cb = NULL;
				args.fifo_flags = FIFO_FLAG_START | FIFO_FLAG_END;
				err = __ecctrl_i2c_read_fifo(i2c_client, &args);
				i2c_clients[i].i2c_locked = 0;
				return err;
			}
			else
			{
				return -EBUSY;
			}
		}
	}
	return -EINVAL;
}

static int eg_ec_mipi_set_group_hold(struct tegracam_device *tc_dev, bool val)
{
	// group hold is not supported
	return 0;
}

static struct tegracam_ctrl_ops eg_ec_mipi_ctrl_ops = {
	.numctrls = ARRAY_SIZE(ctrl_cid_list),
	.ctrl_cid_list = ctrl_cid_list,
	.set_group_hold = eg_ec_mipi_set_group_hold,
};

static int eg_ec_mipi_power_on(struct camera_common_data *s_data)
{
	// Power is not managed here
	return 0;
}

static int eg_ec_mipi_power_off(struct camera_common_data *s_data)
{
	// Power is not managed here
	return 0;
}

static int eg_ec_mipi_power_put(struct tegracam_device *tc_dev)
{
	// Power is not managed here
	return 0;
}

static int eg_ec_mipi_power_get(struct tegracam_device *tc_dev)
{
	// Power is not managed here
	return 0;
}

static struct camera_common_pdata *eg_ec_mipi_parse_dt(
	struct tegracam_device *tc_dev)
{
	struct device *dev = tc_dev->dev;
	struct device_node *np = dev->of_node;
	struct camera_common_pdata *board_priv_pdata;
	const struct of_device_id *match;

	if (!np)
		return NULL;

	match = of_match_device(eg_ec_mipi_of_match, dev);
	if (!match) {
		dev_err(dev, "Failed to find matching dt id\n");
		return NULL;
	}

	// Just need to allocate data for tegra registration
	board_priv_pdata = devm_kzalloc(dev,
		sizeof(*board_priv_pdata), GFP_KERNEL);
	if (!board_priv_pdata)
		return NULL;

	return board_priv_pdata;
}

static int eg_ec_mipi_set_mode(struct tegracam_device *tc_dev)
{
	// Configuration is done independently by a control application
	return 0;
}

static int eg_ec_mipi_start_streaming(struct tegracam_device *tc_dev)
{
	// Configuration is done independently by a control application
	return 0;
}

static int eg_ec_mipi_stop_streaming(struct tegracam_device *tc_dev)
{
	// Configuration is done independently by a control application
	return 0;
}

static struct camera_common_sensor_ops eg_ec_mipi_common_ops = {
	.numfrmfmts = ARRAY_SIZE(eg_ec_mipi_frmfmt),
	.frmfmt_table = eg_ec_mipi_frmfmt,
	.power_on = eg_ec_mipi_power_on,
	.power_off = eg_ec_mipi_power_off,
	.parse_dt = eg_ec_mipi_parse_dt,
	.power_get = eg_ec_mipi_power_get,
	.power_put = eg_ec_mipi_power_put,
	.set_mode = eg_ec_mipi_set_mode,
	.start_streaming = eg_ec_mipi_start_streaming,
	.stop_streaming = eg_ec_mipi_stop_streaming,
};

static int eg_ec_mipi_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
	return 0;
}

static const struct v4l2_subdev_internal_ops eg_ec_mipi_subdev_internal_ops = {
	.open = eg_ec_mipi_open,
};

static int eg_ec_mipi_probe(struct i2c_client *client,
	const struct i2c_device_id *id)
{
	struct device *dev = &client->dev;
	struct tegracam_device *tc_dev;
	struct eg_ec_mipi *priv;
	int err;
	int i;
	uint32_t upgradeMode;

	dev_dbg(dev, "probing v4l2 eg_ec_mipi sensor at addr 0x%0x\n", client->addr);

	// Find the first i2c client available
	for (i = 0; i < MAX_I2C_CLIENTS_NUMBER; i++)
	{
		if (i2c_clients[i].i2c_client == NULL)
		{
			i2c_clients[i].i2c_client = client;
			sprintf(i2c_clients[i].chnod_name,  "%s-%s", dev_driver_string(dev), dev_name(dev));
			err = eg_ec_chnod_register_device(i);
			if (err)
			{
				dev_err(dev, "chnod register failed\n");
				i2c_clients[i].chnod_name[0] = 0;
				return err;
			}

			// Try to communicate with the camera
			err = eg_ec_mipi_read_reg(i2c_clients[i].i2c_client, 0, (uint8_t*)&upgradeMode, sizeof(upgradeMode));
			if (err)
			{
				dev_err(dev, "Failed to communicate with the camera\n");
				goto err_camera_register;
			}

			break;

		}
	}

	if (!IS_ENABLED(CONFIG_OF) || !client->dev.of_node)
		goto err_camera_register;

	priv = devm_kzalloc(dev,
			sizeof(struct eg_ec_mipi), GFP_KERNEL);
	if (!priv)
		goto err_camera_register;

	tc_dev = devm_kzalloc(dev,
			sizeof(struct tegracam_device), GFP_KERNEL);
	if (!tc_dev)
		goto err_camera_register;

	priv->i2c_client = tc_dev->client = client;
	tc_dev->dev = dev;
	strncpy(tc_dev->name, "eg_ec_mipi", sizeof(tc_dev->name));
	tc_dev->dev_regmap_config = NULL;
	tc_dev->sensor_ops = &eg_ec_mipi_common_ops;
	tc_dev->v4l2sd_internal_ops = &eg_ec_mipi_subdev_internal_ops;
	tc_dev->tcctrl_ops = &eg_ec_mipi_ctrl_ops;

	err = tegracam_device_register(tc_dev);
	if (err) {
		dev_err(dev, "tegra camera driver registration failed\n");
		goto err_camera_register;
	}
	tc_dev->s_data->i2c_client = client;
	priv->tc_dev = tc_dev;
	priv->s_data = tc_dev->s_data;
	priv->subdev = &tc_dev->s_data->subdev;
	tegracam_set_privdata(tc_dev, (void *)priv);
	err = tegracam_v4l2subdev_register(tc_dev, true);
	if (err) {
		dev_err(dev, "tegra camera subdev registration failed\n");
		goto err_camera_register;
	}

	dev_info(dev, "Registered %s device\n", i2c_clients[i].chnod_name);
	return 0;

err_camera_register:
	device_destroy(i2c_clients[i].pClass_chnod, i2c_clients[i].chnod_device_number);
	class_destroy(i2c_clients[i].pClass_chnod);
	unregister_chrdev(i2c_clients[i].chnod_major_number, i2c_clients[i].chnod_name);
	i2c_clients[i].chnod_name[0] = 0;
	return -EIO;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6,1,1)
static int eg_ec_mipi_remove(struct i2c_client *client)
#else
static void eg_ec_mipi_remove(struct i2c_client *client)
#endif
{
	struct device *dev = &client->dev;
	struct camera_common_data *s_data = to_camera_common_data(&client->dev);
	struct eg_ec_mipi *priv = (struct eg_ec_mipi *)s_data->priv;
	char tmp[128];
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
			sprintf(tmp,  "%s-%s", dev_driver_string(dev), dev_name(dev));
			dev_info(dev, "Removed %s device\n", i2c_clients[i].chnod_name);
			i2c_clients[i].i2c_client = NULL;
			i2c_clients[i].chnod_name[0] = 0;
			break;
		}
	}

#if LINUX_VERSION_CODE <= KERNEL_VERSION(6,1,1)
   return 0;
#endif
}

static const struct i2c_device_id eg_ec_mipi_id[] = {
	{ "eg_ec_mipi_i2c", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, eg_ec_mipi_id);

static struct i2c_driver eg_ec_mipi_i2c_driver = {
	.driver = {
		.name = "eg_ec_mipi_i2c",
		.owner = THIS_MODULE,
		.of_match_table = of_match_ptr(eg_ec_mipi_of_match),
	},
	.probe = eg_ec_mipi_probe,
	.remove = eg_ec_mipi_remove,
	.id_table = eg_ec_mipi_id,
};
module_i2c_driver(eg_ec_mipi_i2c_driver);

MODULE_AUTHOR("Xenics Exosens");
MODULE_DESCRIPTION("Xenics Exosens MIPI camera I2C driver for EngineCore cameras");
MODULE_LICENSE("GPL v2");
