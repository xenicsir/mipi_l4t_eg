/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef EG_CAMERA_GENCP_UAPI_H
#define EG_CAMERA_GENCP_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>

#define EG_GENCP_PACKET_MAX 1024
#define EG_GENCP_ABI_VERSION 1
/* Fixed-width, pointer-free layout, identical for 32/64-bit callers.
 * rx_capacity must cover the maximum ACK before any camera write is attempted.
 * One ioctl owns the complete request/ACK transaction, including polling.
 */
struct eg_gencp_xfer {
    __u32 version;
    __u32 tx_length;
    __u32 rx_capacity;
    __u32 rx_length;
    __u32 flags;
    __u32 reserved[3];
    __u8 tx[EG_GENCP_PACKET_MAX];
    __u8 rx[EG_GENCP_PACKET_MAX];
};
#define EG_IOCTL_GENCP_XFER _IOWR('G', 0x10, struct eg_gencp_xfer)
struct eg_gencp_stats {
    __u32 version;
    __u32 transport_bytes;
    __u64 transactions;
    __u64 polls;
    __u64 tx_requested_bytes;
    __u64 rx_requested_bytes;
};
#define EG_IOCTL_GENCP_STATS _IOR('G', 0x11, struct eg_gencp_stats)
#endif
