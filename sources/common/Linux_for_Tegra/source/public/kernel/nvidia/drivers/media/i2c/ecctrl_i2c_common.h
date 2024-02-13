/**
 * ecctrl_i2c_i2c_common.h
 *
 * Copyright (c) 2023, Xenics Exosens, All Rights Reserved.
 *
 */

#ifndef __ECCTRL_I2C_COMMON__
#define __ECCTRL_I2C_COMMON__

#include "ecctrl_i2c.h"

#if (defined (LINUX) || defined (__linux__))
#if !defined(__KERNEL__)

#include <linux/i2c-dev.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <poll.h>

#else // __KERNEL__

#include <linux/types.h>
#include <linux/string.h>
#include <linux/ioctl.h>
#include <linux/i2c.h>

#endif // __KERNEL__
#else // LINUX
// Windows
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#endif // LINUX




#define LOG_DBG         0
#define LOG_INFO        1
#define LOG_WARNING     2
#define LOG_ERROR_DBG   3
#define LOG_ERROR       4
#define LOG_FATAL       5

#define LOG_LEVEL		LOG_ERROR


#define CMD_WRITE       0x01
#define ACK_WRITE       0x81
#define CMD_READ        0x02
#define ACK_READ        0x82
#define CMD_WRITE_FIFO  0x04
#define ACK_WRITE_FIFO  0x84
#define CMD_READ_FIFO   0x08
#define ACK_READ_FIFO   0x88
#define ACK_ERROR       0xC0

#define FIFO_OP_CONTINUE	0
#define FIFO_OP_START 		(1 << 0)
#define FIFO_OP_END			(1 << 1)
#define FIFO_OP_RETRY		(1 << 2)

#if (defined (LINUX) || defined (__linux__))

#define ECCTRL_I2C_TIMEOUT_SET     _IOW('d', 0x01, int)

#if defined(__KERNEL__)

#define __ecctrl_i2c_print(dbg_level, ...) \
   if (dbg_level >= LOG_LEVEL) \
   printk(__VA_ARGS__);

#define __ecctrl_i2c_malloc(size) kmalloc(size, GFP_KERNEL)
#define __ecctrl_i2c_free kfree
#define __ecctrl_i2c_usleep fsleep
#define __ecctrl_i2c_file_t struct i2c_client *

#define __ecctrl_i2c_write(file, buffer, size) i2c_master_send(file, buffer, size)
#define __ecctrl_i2c_read(file, buffer, size) i2c_master_recv(file, buffer, size)

#else	// __KERNEL__

#define __ecctrl_i2c_print(dbg_level, ...) \
   if (dbg_level >= LOG_LEVEL) \
   printf(__VA_ARGS__);

#define __ecctrl_i2c_malloc(size) malloc(size)
#define __ecctrl_i2c_free free
#define __ecctrl_i2c_usleep usleep
#define __ecctrl_i2c_file_t int

#define __ecctrl_i2c_write(file, buffer, size) write(file, buffer, size)
#define __ecctrl_i2c_read(file, buffer, size) read(file, buffer, size)

#endif	// __KERNEL__
#else // LINUX
// Windows
#define __ecctrl_i2c_print(dbg_level, ...) \
   if (dbg_level >= LOG_LEVEL) \
   printf(__VA_ARGS__);

#define __ecctrl_i2c_malloc(size) malloc(size)
#define __ecctrl_i2c_free free
#define __ecctrl_i2c_usleep usleep
#define __ecctrl_i2c_file_t HANDLE

#define __ecctrl_i2c_write(file, buffer, size) WriteFile(file, buffer, (DWORD)size, NULL, NULL)
#define __ecctrl_i2c_read(file, buffer, size)  ReadFile(file, buffer, (DWORD)size, NULL, NULL)

#endif // LINUX


int __ecctrl_i2c_write_reg(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args);
int __ecctrl_i2c_read_reg(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args);
int __ecctrl_i2c_write_fifo(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args);
int __ecctrl_i2c_read_fifo(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args);
int __ecctrl_i2c_timeout_set(__ecctrl_i2c_file_t file, int timeout);


#endif  /* __ECCTRL_I2C_COMMON__ */
