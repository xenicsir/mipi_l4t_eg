/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (c) 2026 Xenics Exosens. */
#ifndef LIB_UNIO_H
#define LIB_UNIO_H
#include "libtarget.h"
#include "transport_config.h"
#ifdef __KERNEL__
#include <linux/i2c.h>
#else
#include <unistd.h>
#endif

/* Transaction state belongs to the camera; no allocation in the polling path. */
struct gencp_camera_state {
    u8 tx[1024];
    u8 rx[1024];
    u16 request_id;
    bool initialized;
    u64 transactions;
    u64 polls;
    u64 tx_bytes;
    u64 rx_bytes;
};

struct unio_handle;
/* read_packet: 1=complete candidate, 2=progress, 0=idle, negative=I/O error.
 * Each call is bounded; the engine owns the request deadline and validation.
 */
struct gencp_transport_ops {
    unsigned int read_size;
    unsigned int idle_us;
    void (*begin)(struct unio_handle *);
    int (*send)(struct unio_handle *, const u8 *, size_t);
    int (*read_packet)(struct unio_handle *, u8 *, size_t);
};
extern const struct gencp_transport_ops gencp_fifo16_transport;
extern const struct gencp_transport_ops gencp_buffer1024_transport;
struct gencp_fifo_state {
    u8 bytes[16];
    unsigned int index, length, used, word_count;
    u8 last;
};

struct unio_handle {
#ifdef __KERNEL__
    struct i2c_client *client;
#else
    int fd;
#endif
    struct gencp_camera_state gencp;
    const struct gencp_transport_ops *transport;
    void *transport_private;
    unsigned int response_timeout_ms;
    struct gencp_fifo_state fifo;
};
int unio_write(struct unio_handle *h, const u8 *buf, size_t len);
int unio_read(struct unio_handle *h, u8 *buf, size_t len);
#endif
