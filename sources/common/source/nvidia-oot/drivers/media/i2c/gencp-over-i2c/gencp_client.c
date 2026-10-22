/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (c) 2026 Xenics Exosens. */
#include "gencp_common.h"
#include "gencp_client.h"
#ifdef __KERNEL__
#include <linux/delay.h>
#include <linux/errno.h>
#include <linux/ktime.h>
#else
#include <errno.h>
#include <time.h>
#include <unistd.h>
#endif

/* Compatibility selector only; all protocol/decoder state lives in the handle.
 * Callers hold their camera-driver transaction mutex across selection and use.
 */
static struct unio_handle *selected;
#define GENCP_REQUEST_TIMEOUT_MS 2667

static u16 get16(const u8 *p) { return ((u16)p[0] << 8) | p[1]; }
static void put16(u8 *p, u16 n) { p[0] = n >> 8; p[1] = n; }
static u64 get64(const u8 *p)
{
    u64 n = 0;
    unsigned int i;
    for (i = 0; i < 8; i++) n = (n << 8) | p[i];
    return n;
}
static void put64(u8 *p, u64 n)
{
    unsigned int i;
    for (i = 0; i < 8; i++) p[7 - i] = n >> (i * 8);
}
static u64 now_ms(void)
{
#ifdef __KERNEL__
    return ktime_to_ms(ktime_get());
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (u64)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
#endif
}
static void poll_pause(struct unio_handle *h)
{
#ifdef __KERNEL__
    usleep_range(h->transport->idle_us, h->transport->idle_us + 1000);
#else
    usleep(h->transport->idle_us);
#endif
}
static void checksums(u8 *packet, u16 length)
{
    put16(packet + 2, GENCP_crc16(packet + 6, 10));
    put16(packet + 4, GENCP_crc16(packet + 6, length - 6));
}
static bool checksum_valid(u8 *bytes, unsigned int length, u16 checksum)
{
    u16 calculated = GENCP_crc16(bytes, length);
    return checksum == calculated || (!checksum && calculated == 0xffff);
}
static bool packet_valid(u8 *packet, unsigned int length)
{
    return length >= 16 && length <= EG_GENCP_PACKET_MAX &&
           get16(packet) == GENCP_PREAMBLE && get16(packet + 12) == length - 16 &&
           checksum_valid(packet + 6, 10, get16(packet + 2)) &&
           checksum_valid(packet + 6, length - 6, get16(packet + 4));
}
static void prepare(struct unio_handle *h)
{
    if (!h->response_timeout_ms) h->response_timeout_ms = GENCP_REQUEST_TIMEOUT_MS;
    if (!h->gencp.initialized) {
        if (!h->transport)
            h->transport = GENCP_I2C_BUFFER_SIZE == 16 ? &gencp_fifo16_transport : &gencp_buffer1024_transport;
        h->fifo.last = 0xaa;
        h->gencp.initialized = true;
    }
}
int GENCPCLIENT_SetTransport(struct unio_handle *h, const struct gencp_transport_ops *ops,
                             void *private_data)
{
    if (!h || !ops || !ops->begin || !ops->send || !ops->read_packet ||
        !ops->read_size || !ops->idle_us) return -EINVAL;
    h->transport = ops;
    h->transport_private = private_data;
    memset(&h->fifo, 0, sizeof(h->fifo));
    h->fifo.last = 0xaa;
    prepare(h);
    return 0;
}
void GENCPCLIENT_Configure(struct unio_handle *h, unsigned int read_size)
{
    if (read_size == 16 || read_size == 1024)
        GENCPCLIENT_SetTransport(h, read_size == 16 ? &gencp_fifo16_transport :
                                &gencp_buffer1024_transport, NULL);
}
void GENCPCLIENT_Select(struct unio_handle *h)
{
    selected = h;
    if (h) prepare(h);
}
bool GENCPCLIENT_isSuccesfullyInitialized(void)
{
    return selected && selected->gencp.initialized;
}
void GENCPCLIENT_Cleanup(void)
{
    /* Handles own their buffers. Open-file lifetime is managed by the driver. */
    selected = NULL;
}
void GENCPCLIENT_Init(struct unio_handle *h)
{
    u32 version;
    GENCPCLIENT_Select(h);
    if (h) {
        GENCPCLIENT_ReadRegister(GENCP_REG_GENCP_VERSION, &version);
        GENCPCLIENT_ReadRegister(GENCP_REG_GENCP_VERSION, &version);
    }
}

static bool ack_valid(struct unio_handle *h, u16 command, u16 length)
{
    u8 *rx = h->gencp.rx;
    unsigned int size = get16(rx + 12);
    if (!packet_valid(rx, 16 + size) || get16(rx + 6) != 0 ||
        get16(rx + 10) != command + 1 || get16(rx + 14) != h->gencp.request_id)
        return false;
    return get16(rx + 8) || command != GENCP_READMEM_CMD || size == length;
}

static u16 memory_transaction(struct unio_handle *h, u16 command, u64 address,
                              u8 *data, u16 length)
{
    struct gencp_camera_state *s;
    unsigned int size;
    u64 deadline;
    u16 status;
    if (!h || !data || !length ||
        length > (command == GENCP_READMEM_CMD ? 1008 : 1000) ||
        address > (~(u64)0) - (length - 1))
        return GENCP_STATUS_INVALID_PARAMETER;
    prepare(h);
    s = &h->gencp;
    h->transport->begin(h);
    memset(s->rx, 0, sizeof(s->rx));
    memset(s->tx, 0, 28);
    if (!++s->request_id) s->request_id = 1;
    put16(s->tx, GENCP_PREAMBLE);
    put16(s->tx + 8, GENCP_CMD_FLAG_REQUEST_ACK);
    put16(s->tx + 10, command);
    put16(s->tx + 14, s->request_id);
    put64(s->tx + 16, address);
    if (command == GENCP_READMEM_CMD) {
        size = 28;
        put16(s->tx + 26, length);
    } else {
        size = 24 + length;
        memcpy(s->tx + 24, data, length);
    }
    put16(s->tx + 12, size - 16);
    checksums(s->tx, size);
    s->transactions++;
    deadline = now_ms() + h->response_timeout_ms;
    if (h->transport->send(h, s->tx, size)) return GENCP_STATUS_LOCAL_PROBLEM;
    while (now_ms() < deadline) {
        int received = h->transport->read_packet(h, s->rx, sizeof(s->rx));
        if (received != 1 || !ack_valid(h, command, length)) {
            if (received != 2) poll_pause(h);
            continue;
        }
        status = get16(s->rx + 8);
        if (!status && command == GENCP_READMEM_CMD)
            memcpy(data, s->rx + 16, length);
        return status;
    }
    return GENCP_STATUS_MSG_TIMEOUT;
}
u16 GENCPCLIENT_ReadMemory(struct unio_handle *h, u64 address, u8 *data, u16 length)
{
    return memory_transaction(h, GENCP_READMEM_CMD, address, data, length);
}
u16 GENCPCLIENT_WriteMemory(struct unio_handle *h, u64 address, const u8 *data, u16 length)
{
    return memory_transaction(h, GENCP_WRITEMEM_CMD, address, (u8 *)data, length);
}
u16 GENCPCLIENT_ReadRegister(u32 address, u32 *data)
{
    u8 bytes[4];
    u16 status;
    if (!data) return GENCP_STATUS_INVALID_PARAMETER;
    status = GENCPCLIENT_ReadMemory(selected, address, bytes, 4);
    if (!status) *data = ((u32)get16(bytes) << 16) | get16(bytes + 2);
    return status;
}
u16 GENCPCLIENT_WriteRegister(u32 address, u32 data)
{
    u8 bytes[4];
    put16(bytes, data >> 16);
    put16(bytes + 2, data);
    return GENCPCLIENT_WriteMemory(selected, address, bytes, 4);
}
u16 GENCPCLIENT_ReadString(u32 address, u8 *data, u32 length)
{
    if (length > 1008) return GENCP_STATUS_INVALID_PARAMETER;
    return GENCPCLIENT_ReadMemory(selected, address, data, length);
}

/* A complete user transaction shares the driver's lock with probe/streaming.
 * Wire request IDs are generated by the camera context. The caller's ID is
 * echoed only in its returned ACK, so independent clients cannot reuse a stale
 * camera response by choosing the same ID as an internal driver operation.
 */
int GENCPCLIENT_Exchange(struct unio_handle *h, struct eg_gencp_xfer *x,
                        void *opaque, gencp_memory_read read,
                        gencp_memory_write write)
{
    u16 command, size, length, status, request_id, channel;
    u64 address;
    u8 *request = x->tx, *reply = x->rx;
    unsigned int i;
    if (x->version != EG_GENCP_ABI_VERSION || x->flags || x->rx_length ||
        x->tx_length > EG_GENCP_PACKET_MAX || x->rx_capacity > EG_GENCP_PACKET_MAX)
        return -EINVAL;
    for (i = 0; i < 3; i++) if (x->reserved[i]) return -EINVAL;
    if (!packet_valid(request, x->tx_length)) return -EBADMSG;
    if (get16(request + 6) || (get16(request + 8) & ~GENCP_CMD_FLAG_REQUEST_ACK))
        return -EOPNOTSUPP;
    command = get16(request + 10);
    size = get16(request + 12);
    request_id = get16(request + 14);
    channel = get16(request + 6);
    if (command == GENCP_READMEM_CMD) {
        if (size != 12 || get16(request + 24)) return -EINVAL;
        length = get16(request + 26);
        if (!length || length > 1008) return -EMSGSIZE;
        if (x->rx_capacity < 16u + length) return -ENOSPC;
    } else if (command == GENCP_WRITEMEM_CMD) {
        if (size <= 8 || size > 1008) return -EINVAL;
        length = size - 8;
        /* Always return the compact, length-bearing WriteMem ACK. */
        if (x->rx_capacity < 20) return -ENOSPC;
    } else return -EOPNOTSUPP;
    address = get64(request + 16);
    if (address > (~(u64)0) - (length - 1)) return -EINVAL;
    memset(reply, 0, EG_GENCP_PACKET_MAX);
    if (command == GENCP_READMEM_CMD)
        status = read ? read(opaque, address, reply + 16, length) :
                        GENCPCLIENT_ReadMemory(h, address, reply + 16, length);
    else
        status = write ? write(opaque, address, request + 24, length) :
                         GENCPCLIENT_WriteMemory(h, address, request + 24, length);
    size = status ? 0 : (command == GENCP_READMEM_CMD ? length : 4);
    if (!status && command == GENCP_WRITEMEM_CMD) put16(reply + 18, length);
    if (status) memset(reply + 16, 0, EG_GENCP_PACKET_MAX - 16);
    put16(reply, GENCP_PREAMBLE);
    put16(reply + 6, channel);
    put16(reply + 8, status);
    put16(reply + 10, command + 1);
    put16(reply + 12, size);
    put16(reply + 14, request_id);
    x->rx_length = size + 16;
    checksums(reply, x->rx_length);
    return 0;
}

#ifdef __KERNEL__
#include <linux/uaccess.h>
#include <linux/err.h>
long GENCPCLIENT_UserExchange(struct unio_handle *h, unsigned long arg)
{
    struct eg_gencp_xfer *x;
    int ret;
    x = memdup_user((void __user *)arg, sizeof(*x));
    if (IS_ERR(x)) return PTR_ERR(x);
    ret = GENCPCLIENT_Exchange(h, x, NULL, NULL, NULL);
    if (!ret && copy_to_user((void __user *)arg, x, sizeof(*x))) ret = -EFAULT;
    kfree(x);
    return ret;
}
long GENCPCLIENT_UserStats(struct unio_handle *h, unsigned long arg)
{
    struct eg_gencp_stats stats = {
        .version = EG_GENCP_ABI_VERSION,
        .transport_bytes = h->transport->read_size,
        .transactions = h->gencp.transactions,
        .polls = h->gencp.polls,
        .tx_requested_bytes = h->gencp.tx_bytes,
        .rx_requested_bytes = h->gencp.rx_bytes,
    };
    return copy_to_user((void __user *)arg, &stats, sizeof(stats)) ? -EFAULT : 0;
}
#endif
