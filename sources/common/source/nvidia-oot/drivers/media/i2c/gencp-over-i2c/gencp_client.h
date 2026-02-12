/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "libtarget.h"

#include "libunio.h"

#ifndef RAYTRON_MINI2

#ifndef SRC_INTERFACE_GENCP_GENCP_CLIENT_H_
#define SRC_INTERFACE_GENCP_GENCP_CLIENT_H_

// #include "../../periphery/uart.h"

void GENCPCLIENT_Init(struct unio_handle *h);
void GENCPCLIENT_Cleanup(void);
uint16_t GENCPCLIENT_ReadRegister(uint32_t address, uint32_t* data);
// uint16_t GENCPCLIENT_ReadRegister64bit(uint32_t address, uint64_t* data);
uint16_t GENCPCLIENT_WriteRegister(uint32_t address, uint32_t data);
// uint16_t GENCPCLIENT_WriteBuffer(uint32_t address, uint8_t* pBuffer, uint32_t length);
bool GENCPCLIENT_isSuccesfullyInitialized(void);
uint16_t GENCPCLIENT_ReadString(uint32_t address, uint8_t* string, uint32_t length);

#endif /* SRC_INTERFACE_GENCP_GENCP_CLIENT_H_ */
#endif
