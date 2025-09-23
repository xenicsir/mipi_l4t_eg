/**
 * ecctrl_i2c.h
 *
 * Copyright (c) 2023, Xenics Exosens, All Rights Reserved.
 *
 */

#ifndef __ECCTRL_I2C__
#define __ECCTRL_I2C__

#if (defined (LINUX) || defined (__linux__))
#if !defined(__KERNEL__)
#include <stdint.h>
#else // __KERNEL__
#include <linux/types.h>
#endif // __KERNEL__
#else // LINUX
// Windows
#include <stdint.h>
#endif // LINUX

#define FIFO_FLAG_START	(1 << 0)
#define FIFO_FLAG_END	(1 << 1)

#define ECCTRL_I2C_TYPE	   0
#define ECCTRL_UVC_TYPE	   1

#define I2C_TIMEOUT_DEFAULT   5000

#ifdef __cplusplus
extern "C"{
#endif 

typedef struct
{
   uint32_t data_address;  // Address of register or FIFO
   uint8_t *data;          // data
   uint32_t data_size;     // data size
   int i2c_timeout;        // I2C master timeout in ms. 0 for default driver value
   int i2c_tries_max;      // maximum number of tries on I2C if failure. 0 for default driver value
   void (*cb)(void);       // callback called after the transfer of a unitary FIFO packet. Could be NULL
   int fifo_flags;         // FIFO flags
   int deviceType;         // ECCTRL_XXX_TYPE
} ecctrl_i2c_t;

int ecctrl_i2c_write_reg(char* device_name, ecctrl_i2c_t *args);
int ecctrl_i2c_read_reg(char* device_name, ecctrl_i2c_t *args);
int ecctrl_i2c_write_fifo(char* device_name, ecctrl_i2c_t *args);
int ecctrl_i2c_read_fifo(char* device_name, ecctrl_i2c_t *args);

#ifdef __cplusplus
}
#endif


#endif  /* __ECCTRL_I2C__ */
