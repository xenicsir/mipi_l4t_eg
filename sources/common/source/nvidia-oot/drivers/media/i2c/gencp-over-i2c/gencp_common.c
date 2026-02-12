/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "gencp_common.h"

uint16_t GENCP_crc16(uint8_t *buf, uint32_t len)
{
    uint32_t sum = 0;

    for (uint32_t i = 0; i < len; i++)
    {
        if (i & 1)
            sum += (uint32_t)buf[i];
        else
            sum += (uint32_t)buf[i] << 8;
    }

    while (sum >> 16)
        sum = (sum & 0xFFFF) + (sum >> 16);

    if (sum == 0xFFFF)  // special case in RFC768 (as referred in GenCP spec, tested on JAI GO-2400M camera)
        sum = 0;

    // printf("CRC_CALC: : [");
    // for (int i = 0; i < len; i++) {
    //     printf("%#02x", buf[i]);
    //     if (i < len-1) printf(", ");
    // }
    // printf("]\n");
    // printf("CRC Result: %#04x, or len: %u", ~sum & 0xffff, len);

    // printk(KERN_INFO "CRC_CALC: Array [");
    // for (int i = 0; i < len; i++) {
    //     printk(KERN_CONT "%#02x", buf[i]);
    //     if (i < len-1) printk(KERN_CONT ", ");
    // }
    // printk(KERN_CONT "]\n");
    //
    // printf("CRC Result: %#04x, or len: %u", ~sum & 0xffff, len);
    return ~sum;
}

uint8_t GENCP_isNonSwapAddress(uint32_t addr)
{
	uint8_t addrIsInFileAccessBufferRange = 0;
	#ifdef FILEACCESS_IMPLEMENTED
		addrIsInFileAccessBufferRange = ((FILEACCESS_REG_BUFFER_BASE <= addr) && (addr <= FILEACCESS_REG_BUFFER_END)) ? 1:0;
	#endif
	//uint8_t addrIsInCalSetSourceDescr 	  = ((CSC_STRING_SOURCEDESCRIPTION_OFFSET <= addr)  && (addr <= CSC_STRING_SOURCEDESCRIPTION_END)) ? 1:0;
	//uint8_t addrIsInCalSetUserDefName	  = ((CSC_STRING_USERDEFINEDNAME_OFFSET <= addr)    && (addr <= CSC_STRING_USERDEFINEDNAME_END)) ? 1:0;
	uint8_t addrIsInCalSetSourceDescr 	  = 0;
	uint8_t addrIsInCalSetUserDefName	  = 0;

	uint8_t result = (addrIsInFileAccessBufferRange || addrIsInCalSetSourceDescr || addrIsInCalSetUserDefName) ? 1:0;

	return result;
}
