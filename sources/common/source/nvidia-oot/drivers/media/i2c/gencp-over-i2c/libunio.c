/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (c) 2026 Xenics Exosens. */
#include "libunio.h"
#ifdef __KERNEL__
#include <linux/errno.h>

static int unio_transfer(struct unio_handle *h, u8 *buf, size_t len, bool read)
{
    struct i2c_msg msg = {
        .addr = h->client->addr,
        .flags = read ? I2C_M_RD : 0,
        .len = len,
        .buf = buf,
    };
    int ret;
    if (read) { h->gencp.polls++; h->gencp.rx_bytes += len; }
    else h->gencp.tx_bytes += len;
    ret = i2c_transfer(h->client->adapter, &msg, 1);

    return ret == 1 ? 0 : (ret < 0 ? ret : -EIO);
}
int unio_write(struct unio_handle *h, const u8 *buf, size_t len)
{
    return unio_transfer(h, (u8 *)buf, len, false);
}
int unio_read(struct unio_handle *h, u8 *buf, size_t len)
{
    return unio_transfer(h, buf, len, true);
}
#else
#include <errno.h>
int unio_write(struct unio_handle *h, const u8 *buf, size_t len)
{
    ssize_t ret;
    h->gencp.tx_bytes += len;
    ret = write(h->fd, buf, len);
    return ret == (ssize_t)len ? 0 : (ret < 0 ? -errno : -EIO);
}
int unio_read(struct unio_handle *h, u8 *buf, size_t len)
{
    ssize_t ret;
    h->gencp.polls++; h->gencp.rx_bytes += len;
    ret = read(h->fd, buf, len);
    return ret == (ssize_t)len ? 0 : (ret < 0 ? -errno : -EIO);
}
#endif
