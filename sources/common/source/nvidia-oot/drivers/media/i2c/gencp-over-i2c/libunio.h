/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#ifndef LIB_UNIO_H
#define LIB_UNIO_H

#include "libtarget.h"
#ifdef __KERNEL__
    #include <linux/i2c.h>
#else
    #include <unistd.h> // For close(), read(), write() functions
#endif

struct unio_handle {
#ifdef __KERNEL__
    struct i2c_client *client;
#else
    int fd; // file descriptor for userspace device
#endif
    bool    read_buffer_enable;
};

int unio_write(struct unio_handle *h, const u8 *buf, size_t len);
int unio_read (struct unio_handle *h,       u8 *buf, size_t len);
int unio_read_buffer_init(struct unio_handle *h, size_t depth);
int unio_read_byte (struct unio_handle *h, u8 *buf);

#endif /* LIB_UNIO_H */


// /* Kernel */
// struct unio_handle h = {
//     .client = client,   // inside i2c driver's probe()
// };
//
// uint8_t cmd[] = { 0x01, 0x02, 0x03 };
// unio_write(&h, cmd, sizeof(cmd));
//
// uint8_t response[4];
// unio_read(&h, response, sizeof(response));

// /* user space */
// #include "unio.h"
// #include <fcntl.h>
//
// struct unio_handle h;
//
// h.fd = open("/dev/i2c-1", O_RDWR);
//
// /* Write */
// uint8_t data[] = { 0x10, 0x20 };
// unio_write(&h, data, sizeof(data));
//
// /* Read */
// uint8_t inbuf[4];
// unio_read(&h, inbuf, sizeof(inbuf));
