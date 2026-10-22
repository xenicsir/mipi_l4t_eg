/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (c) 2026 Xenics Exosens. */
#include "libunio.h"
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#endif

static void buffer_begin(struct unio_handle *h) { (void)h; }
static int buffer_packet(struct unio_handle *h, u8 *packet, size_t capacity)
{
    int ret;
    if (capacity < 1024) return -EMSGSIZE;
    ret = unio_read(h, packet, 1024);
    return ret ? ret : 1;
}

static bool decode_byte(struct gencp_fifo_state *s, u8 value, u8 *decoded)
{
    bool valid = false;
    if (value != s->last) {
        s->word_count++;
        if ((value ^ s->last) == 0xff && s->word_count > 1) {
            s->word_count = 0;
            *decoded = s->last;
            valid = true;
        }
    }
    s->last = value;
    return valid;
}
static void fifo_begin(struct unio_handle *h)
{
    struct gencp_fifo_state *s = &h->fifo;
    u8 ignored;
    /* Finish the decoder's pending raw bytes before discarding old payload. */
    while (s->index < s->length) decode_byte(s, s->bytes[s->index++], &ignored);
    s->used = s->index = s->length = 0;
}
static int fifo_packet(struct unio_handle *h, u8 *packet, size_t capacity)
{
    struct gencp_fifo_state *s = &h->fifo;
    bool progressed = false;
    if (s->index == s->length) {
        int ret = unio_read(h, s->bytes, sizeof(s->bytes));
        if (ret) return ret;
        s->index = 0;
        s->length = sizeof(s->bytes);
    }
    while (s->index < s->length) {
        u8 byte;
        unsigned int length;
        if (!decode_byte(s, s->bytes[s->index++], &byte)) continue;
        progressed = true;
        if (!s->used) {
            if (byte == 1) packet[s->used++] = byte;
            continue;
        }
        if (s->used == 1 && byte != 0) {
            s->used = byte == 1 ? 1 : 0;
            continue;
        }
        if (s->used >= capacity) { s->used = 0; return -EMSGSIZE; }
        packet[s->used++] = byte;
        if (s->used < 16) continue;
        length = 16 + ((unsigned int)packet[12] << 8) + packet[13];
        if (length > capacity) { s->used = 0; return -EMSGSIZE; }
        if (s->used == length) { s->used = 0; return 1; }
    }
    return progressed ? 2 : 0;
}
const struct gencp_transport_ops gencp_fifo16_transport = {
    .read_size = 16, .idle_us = 1000, .begin = fifo_begin,
    .send = unio_write, .read_packet = fifo_packet,
};
const struct gencp_transport_ops gencp_buffer1024_transport = {
    .read_size = 1024, .idle_us = 5000, .begin = buffer_begin,
    .send = unio_write, .read_packet = buffer_packet,
};
