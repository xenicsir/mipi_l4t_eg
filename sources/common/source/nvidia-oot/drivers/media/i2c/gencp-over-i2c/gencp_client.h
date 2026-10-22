/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (c) 2026 Xenics Exosens. */
#ifndef SRC_INTERFACE_GENCP_GENCP_CLIENT_H_
#define SRC_INTERFACE_GENCP_GENCP_CLIENT_H_
#include "libunio.h"
#include "eg_camera_gencp.h"

/* Existing driver calls are serialized by the driver's transaction mutex. */
int GENCPCLIENT_SetTransport(struct unio_handle *h, const struct gencp_transport_ops *ops, void *private_data);
void GENCPCLIENT_Configure(struct unio_handle *h, unsigned int read_size);
void GENCPCLIENT_Init(struct unio_handle *h);
void GENCPCLIENT_Cleanup(void);
void GENCPCLIENT_Select(struct unio_handle *h);
bool GENCPCLIENT_isSuccesfullyInitialized(void);
uint16_t GENCPCLIENT_ReadRegister(uint32_t address, uint32_t *data);
uint16_t GENCPCLIENT_WriteRegister(uint32_t address, uint32_t data);
uint16_t GENCPCLIENT_ReadString(uint32_t address, uint8_t *data, uint32_t length);

uint16_t GENCPCLIENT_ReadMemory(struct unio_handle *h, uint64_t address,
                              uint8_t *data, uint16_t length);
uint16_t GENCPCLIENT_WriteMemory(struct unio_handle *h, uint64_t address,
                               const uint8_t *data, uint16_t length);
/* Basic-mode callbacks operate on raw, unconverted memory bytes. */
typedef uint16_t (*gencp_memory_read)(void *, uint64_t, uint8_t *, uint16_t);
typedef uint16_t (*gencp_memory_write)(void *, uint64_t, const uint8_t *, uint16_t);
int GENCPCLIENT_Exchange(struct unio_handle *h, struct eg_gencp_xfer *xfer,
                        void *opaque, gencp_memory_read read,
                        gencp_memory_write write);
#ifdef __KERNEL__
long GENCPCLIENT_UserExchange(struct unio_handle *h, unsigned long arg);
long GENCPCLIENT_UserStats(struct unio_handle *h, unsigned long arg);
#endif
#endif
