/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "libunio.h"
#include "libunio_extras.h"

#define PREFIX "libunio"
#include "liblogger.h"

#if GENCP_I2C_BUFFER_SIZE == 16
static struct ring_buffer rb_fifo;
#else
/* Raw buffered GenCP bytes: never run the FIFO repeat/complement decoder. */
static u8 raw_rx[GENCP_I2C_BUFFER_SIZE];
static size_t raw_index, raw_length;
#endif

int unio_read_buffer_init(struct unio_handle *h, size_t depth)
{
#if GENCP_I2C_BUFFER_SIZE == 16
    rb_init(&rb_fifo);
#else
    raw_index = raw_length = 0;
#endif
    h->read_buffer_enable = true;
    return 0;
}

static enum return_status __unio_parsed_byte (struct unio_handle *h, u8 *buf)
{
#if GENCP_I2C_BUFFER_SIZE == 1024
    if (raw_index == raw_length) {
        if (raw_length) {
            /* Yield after each poll so the caller can check its timeout. */
            raw_index = raw_length = 0;
            return NO_DATA;
        }
        if (unio_read(h, raw_rx, sizeof(raw_rx)) != 0)
            return ERROR;
        raw_length = sizeof(raw_rx);
    }
    *buf = raw_rx[raw_index++];
    return SUCCESS;
#else
    int ret;
    u8 temp_buff[16];
    size_t temp_size = sizeof(temp_buff)/sizeof(temp_buff[0]);

    if (rb_fifo.count == 0) {
        PRINT_DEBUG("No data available, doing a read\n");

        // Read 16 bytes from i2c
        ret = unio_read(h, &temp_buff[0], temp_size);
        if (ret < 0) {return ERROR;}

        // Parse the 16 bytes read and save result to rb_fifo
        ret = parse_gencp_raw(&temp_buff[0], temp_size, &rb_fifo);
        if (ret < 0) {
            PRINT_ERROR("Error while parsing. Data might have been lost\n");
            return ERROR;
        } else {
            PRINT_DEBUG("rb count = %d\n", (int)rb_fifo.count);
            if (rb_fifo.count == 0) {
                PRINT_DEBUG("Parsed no valid data\n");
                return NO_DATA;
            } else {
                rb_pop(&rb_fifo,buf);
                return SUCCESS;
            }
        }
    } else {
        rb_pop(&rb_fifo,buf);
    }
    return 0;
#endif
}

int unio_read_byte (struct unio_handle *h, u8 *buf)
{
    // pr_info("Called from: %pS\n", __builtin_return_address(0));
    if (h->read_buffer_enable) {
        enum return_status ret;
        ret = __unio_parsed_byte(h,buf);
        return (int)ret;
    } else {
        int ret;
        ret = unio_read(h,buf,1);
        return ret;
    }
}

#ifdef __KERNEL__ /* Kernelspace implementation */
#include <linux/kernel.h>

int unio_write(struct unio_handle *h, const u8 *buf, size_t len)
{
    int ret;
    struct i2c_msg msg;

#if GENCP_I2C_BUFFER_SIZE == 1024
    /* Discard trailing bytes from the previous ACK before a new request. */
    if (len > GENCP_I2C_BUFFER_SIZE)
        return -EMSGSIZE;
    raw_index = raw_length = 0;
#endif

    PRINT_DEBUG("Writing to 0x%X, %lu bytes.\n", h->client->addr, len);
    msg.addr  = h->client->addr;
    msg.flags = 0;               /* write */
    msg.len   = len;
    msg.buf   = (u8 *)buf;

    ret = i2c_transfer(h->client->adapter, &msg, 1);
    PRINT_DEBUG("Write status: %d.\n", ret);
    return (ret == 1) ? 0 : (ret < 0 ? ret : -EIO);
}

int unio_read(struct unio_handle *h, u8 *buf, size_t len)
{
    int ret;
    int i;
    struct i2c_msg msg;

    PRINT_DEBUG("Reading from 0x%X, %lu bytes.\n", h->client->addr, len);
    msg.addr  = h->client->addr;
    msg.flags = I2C_M_RD;        /* read */
    msg.len   = len;
    msg.buf   = buf;

    ret = i2c_transfer(h->client->adapter, &msg, 1);

    /* This is required in kernel to print an array on one line. */
    PRINT_DEBUG("Read status: %d.\n Result: [", ret);
    for (i = 0; i < len; i++) {
        PRINT_DEBUG("0x%X", buf[i]);
        if (i < len-1) PRINT_DEBUG(", ");
    }
    PRINT_DEBUG("]\n");
    return (ret == 1) ? 0 : (ret < 0 ? ret : -EIO);
}

#else   /* Userspace implementation */
#include <errno.h>
#include <stdio.h>

int unio_write(struct unio_handle *h, const u8 *buf, size_t len)
{
    ssize_t ret;
#if GENCP_I2C_BUFFER_SIZE == 1024
    if (len > GENCP_I2C_BUFFER_SIZE)
        return -EMSGSIZE;
    raw_index = raw_length = 0;
#endif
    ret = write(h->fd, buf, len);
    return ret == (ssize_t)len ? 0 : (ret < 0 ? -errno : -EIO);
}

int unio_read(struct unio_handle *h, u8 *buf, size_t len)
{
    ssize_t ret = read(h->fd, buf, len);
    return ret == (ssize_t)len ? 0 : (ret < 0 ? -errno : -EIO);
}

#endif
