/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#define PREFIX "gencp client"
#include "liblogger.h"

#include "gencp_common.h"
#include "gencp_client.h"
#include "nb_timer.h"

#define TIMER_GENCPCLIENT_PTT 0
#define TIMER_GENCPCLIENT_HEARTBEAT 1
#define TIMER_GENCPCLIENT_ACK_READ 2

// WV [20201027] G L O B A L   V A R I A B L E   D E C L A R A T I O N S   A N D   T Y P E   D E F S ------------------
GENCP_MSG* pRxBuffer;
GENCP_MSG* pTxBuffer;

static const uint32_t gpBaudrate_u32[8]     = {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600};
static const uint32_t gDefaultBaudrate_u32  = 9600;
static bool gGencpInitWasSuccessfull        = false;

static struct unio_handle *unio_handle_ptr;

// --------------------------------------------------------------------------------------------------------------------

// WV [20201026] S T A T I C   F U N C T I O N   D E L C L A R A T I O N S --------------------------------------------
static uint32_t GENCPCLIENT_getNextRequestId(void);
static void     GENCPCLIENT_sendCommand(uint32_t size_bytes);
static uint32_t GENCPCLIENT_ComposeReadCommand(uint64_t address, uint16_t read_length_bytes);
static uint32_t GENCPCLIENT_ComposeWriteCommand(uint64_t address, uint16_t write_length_b, uint8_t* data);
static uint32_t GENCPCLIENT_IsAckMsgRdy(uint8_t startTimer, uint8_t* timerIsExpired);
static uint32_t GENCPCLIENT_GetPackageTransferTime(void);
static uint8_t  GENCPCLIENT_isNonSwapCase(uint32_t address);
// --------------------------------------------------------------------------------------------------------------------


/*_____       _ _      _____ ______ _   _  _____ _____         _ _            _
 |_   _|     (_) |    / ____|  ____| \ | |/ ____|  __ \       | (_)          | |
   | |  _ __  _| |_  | |  __| |__  |  \| | |    | |__) |   ___| |_  ___ _ __ | |_
   | | | '_ \| | __| | | |_ |  __| | . ` | |    |  ___/   / __| | |/ _ \ '_ \| __|
  _| |_| | | | | |_  | |__| | |____| |\  | |____| |      | (__| | |  __/ | | | |_
 |_____|_| |_|_|\__|  \_____|______|_| \_|\_____|_|       \___|_|_|\___|_| |_|\__|
 */
void GENCPCLIENT_Init(struct unio_handle *h)
{
    uint16_t status = GENCP_STATUS_SUCCESS;
    gGencpInitWasSuccessfull = true; // required for correct opperation of init functions, will be reset to false if needed...

    if(h) // if we have a valid pointer
    {
        PRINT_DEBUG("\n\rGENCP CLIENT     - GENCP Client Initialization");
        unio_handle_ptr = h; //Save unio handle ptr
        unio_read_buffer_init(unio_handle_ptr, 8); //initialize the ringbuffer and parsed gencp
        nb_timers_init(2); //Init timers

        // Two buffers for rx and tx for i2c send and capture
        pRxBuffer = (GENCP_MSG*)MEM_ALLOC(sizeof(GENCP_MSG));
        pTxBuffer = (GENCP_MSG*)MEM_ALLOC(sizeof(GENCP_MSG));

        PRINT_DEBUG("\n\rGENCP CLIENT     - Address of RxBuffer:             0x%p", pRxBuffer);
        PRINT_DEBUG("\n\rGENCP CLIENT     - Address of TxBuffer:             0x%p", pTxBuffer);

        // USE THIS REGISTER READ TO SEE IF THE COMMUNICATION WORKS, IF FAILURE DISABLE THE GENCP CIENT MODULE !!!
        uint32_t gencpVersion = 0;
        status = GENCP_STATUS_SUCCESS;
        // Read twice incase it fails
        status = GENCPCLIENT_ReadRegister(GENCP_REG_GENCP_VERSION, &gencpVersion);
        status = GENCPCLIENT_ReadRegister(GENCP_REG_GENCP_VERSION, &gencpVersion);
        if(status == GENCP_STATUS_SUCCESS)
        {
            gGencpInitWasSuccessfull = true;
            PRINT_INFO("GenCP version = %#08x\n", gencpVersion);
        }
        else
        {
            gGencpInitWasSuccessfull = false;

            PRINT_ERROR("\n\r\n\r");
            PRINT_ERROR("\n\r\033[91m       ^        \033[0m");
            PRINT_ERROR("\n\r\033[91m      / \\      \033[0m");
            PRINT_ERROR("\n\r\033[91m     / _ \\     \033[0m");
            PRINT_ERROR("\n\r\033[91m    / | | \\    \033[0m");
            PRINT_ERROR("\n\r\033[91m   /  |_|  \\   \033[0m");
            PRINT_ERROR("\n\r\033[91m  /   (_)   \\  \033[0m");
            PRINT_ERROR("\n\r\033[91m /___________\\ \033[0m");
            PRINT_ERROR("\n\r");
            PRINT_ERROR("\n\r \033[91m***ERROR***\033[0m GENCP CLIENT     - Failed to get a reliable connection to the sensor module -> DISABLE GENCP CLIENT !!!\n\r\n\r");
            return;
        }

        // uint32_t read_data = 0;
        // //FPGA firmware read
        // status = GENCPCLIENT_ReadRegister(0x50FF0000, &read_data);
        // if(status == GENCP_STATUS_SUCCESS)
        //     PRINT_INFO("FPGA firmware version = %#08x\n", read_data);
        // else
        //     PRINT_INFO("FPGA firmware read failed\n");
        //
        //
        // //FPGA test read
        // // mipi enable register to read 50ff0010
        // status = GENCPCLIENT_ReadRegister(0x50ff0010, &read_data);
        // if(status == GENCP_STATUS_SUCCESS)
        //     PRINT_INFO("MIPI Enable status = %#08x\n", read_data);
        // else
        //     PRINT_INFO("MIPI status read failed\n");
    }
    else
    {
        PRINT_ERROR("\n\r\n\r\033[91m***ERROR***\033[0m GENCP CLIENT     - Initialization Failed. Communication interface not set!\n\r");
    }
}

void GENCPCLIENT_Cleanup(void)
{
    nb_timer_delete_all();
    MEM_FREE(pRxBuffer);
    MEM_FREE(pTxBuffer);
    PRINT_INFO("GENCP Client cleaned up\n");
}
/*_____                _                                                 _
 |  __ \              | |                                               | |
 | |__) |___  __ _  __| |   ___ ___  _ __ ___  _ __ ___   __ _ _ __   __| |
 |  _  // _ \/ _` |/ _` |  / __/ _ \| '_ ` _ \| '_ ` _ \ / _` | '_ \ / _` |
 | | \ \  __/ (_| | (_| | | (_| (_) | | | | | | | | | | | (_| | | | | (_| |
 |_|  \_\___|\__,_|\__,_|  \___\___/|_| |_| |_|_| |_| |_|\__,_|_| |_|\__,_|
 */

uint16_t GENCPCLIENT_ReadRegister(uint32_t address, uint32_t* data)
{
    uint16_t status = GENCP_STATUS_SUCCESS;

    if(gGencpInitWasSuccessfull)
    {
        PRINT_DEBUG("\n\r\n\rGENCP CLIENT     - Read register 0x%08x", address);
        uint32_t command_size_bytes = 0;
        uint32_t AckMsgRdyStatus = ACK_NOT_READY;
        uint8_t timerIsExpired = 0;
        uint32_t tempdata;

        // WV [20201026] C O M P O S E   T H E   R E A D   C O M M A N D
        PRINT_DEBUG("\n\rGENCP CLIENT     - Compose the GENCP Read command...");
        command_size_bytes = GENCPCLIENT_ComposeReadCommand((uint64_t) address, 4);
        PRINT_DEBUG(" DONE: GENCP package consists of %d bytes.", command_size_bytes);

        // WV [20201026] S E N D   T H E   C O M M A N D   T O   T H E   S E N S O R   M O D U L E  O V E R   U A R T
        PRINT_DEBUG("\n\rGENCP CLIENT     - Send the read command by UART...");
        GENCPCLIENT_sendCommand(command_size_bytes);

        // WV [20201026] R E A D   T H E   R E S P O N S E
        PRINT_DEBUG("\n\rGENCP CLIENT     - Waiting for GENCP ACK...");
        AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(1, &timerIsExpired);      // WV [20201104] Start timer
        do
        {
            AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(0, &timerIsExpired);
            PRINT_DEBUG("STATUS: %u", AckMsgRdyStatus);
        }while( (AckMsgRdyStatus == ACK_NOT_READY) && (!timerIsExpired) );

        if(timerIsExpired)
        {
            PRINT_ERROR("\n\r\n\r\033[91m***ERROR***\033[0m GENCP CLIENT     - Timeout occurred while reading address 0x%08x!\n\r",address);
            status = GENCP_STATUS_MSG_TIMEOUT;
        }
        else
        {
            tempdata = *((uint32_t*) &pRxBuffer->pScd_u16[0]);
            *data = __builtin_bswap32(tempdata);
            status = __builtin_bswap16(pRxBuffer->ccd.flags_status_u16);

            if(status == GENCP_STATUS_SUCCESS)
                PRINT_DEBUG("\n\rGENCP CLIENT     - Register 0x%08x content: 0x%08x", address, *data);
            else
                PRINT_DEBUG("\n\rGENCP CLIENT     - Register read 0x%08x GENCP status: 0x%08x", address, status);

        }
    }
    else
    {
        // The register read was not done, however a SUCCESS is reported as a GENERIC ERROR STATUS is interpreted as a timeout error by Xeneth at startup
        *data = 0;
        status = GENCP_STATUS_SUCCESS;
    }

    return status;
}

// uint16_t GENCPCLIENT_ReadRegister64bit(uint32_t address, uint64_t* data)
// {
//     uint16_t status = GENCP_STATUS_SUCCESS;
//
//     if(gGencpInitWasSuccessfull)
//     {
//         PRINT_DEBUG("\n\r\n\rGENCP CLIENT     - Read register 0x%08x", address);
//
//         uint32_t command_size_bytes = 0;
//         uint32_t AckMsgRdyStatus = ACK_NOT_READY;
//         uint8_t timerIsExpired = 0;
//         uint64_t tempdata;
//
//         // WV [20201026] C O M P O S E   T H E   R E A D   C O M M A N D
//         PRINT_DEBUG("\n\rGENCP CLIENT     - Compose the GENCP Read command...");
//         command_size_bytes = GENCPCLIENT_ComposeReadCommand((uint64_t) address, 8);
//         PRINT_DEBUG(" DONE: GENCP package consists of %d bytes.", command_size_bytes);
//
//         // WV [20201026] S E N D   T H E   C O M M A N D   T O   T H E   S E N S O R   M O D U L E  O V E R   U A R T
//         PRINT_DEBUG("\n\rGENCP CLIENT     - Send the read command by UART...");
//         GENCPCLIENT_sendCommand(command_size_bytes);
//
//         // WV [20201026] R E A D   T H E   R E S P O N S E
//         PRINT_DEBUG("\n\rGENCP CLIENT     - Waiting for GENCP ACK...");
//
//         AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(1, &timerIsExpired);      // WV [20201104] Start timer
//         do
//         {
//             AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(0, &timerIsExpired);
//         }while( (AckMsgRdyStatus == ACK_NOT_READY) && (!timerIsExpired) );
//
//         if(timerIsExpired)
//         {
//             PRINT_ERROR("\n\r\n\r\033[91m***ERROR***\033[0m GENCP CLIENT     - Timeout occurred!\n\r");
//             status = GENCP_STATUS_MSG_TIMEOUT;
//         }
//         else
//         {
//             tempdata = *((uint64_t*) &pRxBuffer->pScd_u16[0]);
//             *data = __builtin_bswap64(tempdata);
//             status = __builtin_bswap16(pRxBuffer->ccd.flags_status_u16);
//
//             if(status == GENCP_STATUS_SUCCESS)
//                 PRINT_DEBUG("\n\rGENCP CLIENT     - Register 0x%08x content: 0x%016x", address, *data);
//             else
//                 PRINT_DEBUG("\n\rGENCP CLIENT     - Register read 0x%08x GENCP status: 0x%08x", address, status);
//         }
//     }
//     else
//     {
//         // The register read was not done, however a SUCCESS is reported as a GENERIC ERROR STATUS is interpreted as a timeout error by Xeneth at startup
//         *data = 0;
//         status = GENCP_STATUS_SUCCESS;
//     }
//     return status;
// }
//
static uint32_t GENCPCLIENT_ComposeReadCommand(uint64_t address, uint16_t read_length_bytes)
{
    uint32_t size = 0;
    uint32_t command_size_bytes;
    const uint16_t SCD_size = 12;

    /** Note:   The byte must be transmit in Big Endian mode, thus the MSB and LSB byte must be inverted in the transmission,
                the "__builtin_bswap16" function is used in order to swap the byte of each packet. */

    // P R E F I X
    pTxBuffer->prefix.preamble_u16      = __builtin_bswap16(GENCP_PREAMBLE);
    pTxBuffer->prefix.ccd_crc_16        = 0;                    // WV [20201023] will be overwritten later
    pTxBuffer->prefix.scd_crc_16        = 0;                    // WV [20201023] will be overwritten later
    pTxBuffer->prefix.channel_id_u16    = 0;

    // C O M M O N   C O M M A N D   D A T A
    pTxBuffer->ccd.flags_status_u16     = __builtin_bswap16(GENCP_CMD_FLAG_REQUEST_ACK);
    pTxBuffer->ccd.command_id_u16       = __builtin_bswap16(GENCP_READMEM_CMD);
    pTxBuffer->ccd.scd_length_u16       = __builtin_bswap16(SCD_size);              // SCD section consists of 12 bytes
    pTxBuffer->ccd.request_id_u16       = __builtin_bswap16(GENCPCLIENT_getNextRequestId());

    // S P E C I F I C   C O M M A N D   D A T A
    *((uint64_t*) &pTxBuffer->pScd_u16[0])  = __builtin_bswap64(address);               // 8 bytes
    pTxBuffer->pScd_u16[4]              = (uint16_t) 0;         // 2 bytes
    pTxBuffer->pScd_u16[5]              = __builtin_bswap16(read_length_bytes); // 2 bytes

    // C O M P L E T E   T H E   C H E C K S U M   F O R   C H A N N E L   I D   &   C C D
    size = 0;
    size += sizeof(pTxBuffer->prefix.channel_id_u16);
    size += sizeof(pTxBuffer->ccd);
    pTxBuffer->prefix.ccd_crc_16        = __builtin_bswap16(GENCP_crc16((uint8_t*) &pTxBuffer->prefix.channel_id_u16, size));

    // C O M P L E T E   T H E   C H E C K S U M   F O R   C H A N N E L   I D   &   C C D   &   S C D
    size += SCD_size;
    pTxBuffer->prefix.scd_crc_16        = __builtin_bswap16(GENCP_crc16((uint8_t*) &pTxBuffer->prefix.channel_id_u16, size));

    command_size_bytes = sizeof(pTxBuffer->prefix) + sizeof(pTxBuffer->ccd) + SCD_size;

    return command_size_bytes;
}

// /*__          __   _ _                                                       _
//   \ \        / /  (_) |                                                     | |
//    \ \  /\  / / __ _| |_ ___    ___ ___  _ __ ___  _ __ ___   __ _ _ __   __| |
//     \ \/  \/ / '__| | __/ _ \  / __/ _ \| '_ ` _ \| '_ ` _ \ / _` | '_ \ / _` |
//      \  /\  /| |  | | ||  __/ | (_| (_) | | | | | | | | | | | (_| | | | | (_| |
//       \/  \/ |_|  |_|\__\___|  \___\___/|_| |_| |_|_| |_| |_|\__,_|_| |_|\__,_|
// */

uint16_t GENCPCLIENT_WriteRegister(uint32_t address, uint32_t data)
{
    if(gGencpInitWasSuccessfull)
    {
        uint32_t command_size_bytes = 0;
        uint32_t AckMsgRdyStatus = ACK_NOT_READY;
        uint8_t timerIsExpired = 0;

        uint32_t dataword = data;

        PRINT_DEBUG("\n\r\n\rGENCP CLIENT     - Write 0x%08x to register 0x%08x", data, address);

        // WV [20201026] C O M P O S E   T H E   W R I T E   C O M M A N D
        PRINT_DEBUG("\n\rGENCP CLIENT     - Compose the GENCP Write command...");
        command_size_bytes = GENCPCLIENT_ComposeWriteCommand((uint64_t) address, 4, (uint8_t*) &dataword);
        PRINT_DEBUG(" DONE: GENCP package consists of %d bytes.", command_size_bytes);

        // WV [20201026] S E N D   T H E   C O M M A N D   T O   T H E   S E N S O R   M O D U L E   O V E R   U A R T
        PRINT_DEBUG("\n\rGENCP CLIENT     - Send the write command by UART...");
        GENCPCLIENT_sendCommand(command_size_bytes);

        // WV [20201026] R E A D   T H E   R E S P O N S E
        PRINT_DEBUG("\n\rGENCP CLIENT     - Waiting for GENCP ACK...");

        AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(1, &timerIsExpired);      // WV [20201104] Start timer
        do
        {
            AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(0, &timerIsExpired);
        }while( (AckMsgRdyStatus == ACK_NOT_READY) && (!timerIsExpired) );

        if(timerIsExpired)
        {
            PRINT_ERROR("\n\r\n\r\033[91m***ERROR***\033[0m GENCP CLIENT     - Timeout occurred while writing register 0x%08x!\n\r", address);
            return GENCP_STATUS_MSG_TIMEOUT;
        }
        else
        {
            PRINT_DEBUG("\n\rGENCP CLIENT     - Register 0x%x has been written - GENCP status: %d", address, pRxBuffer->ccd.flags_status_u16);
            return __builtin_bswap16(pRxBuffer->ccd.flags_status_u16);
        }
    }
    else
    {
        // The register write was not done, however a SUCCESS is reported for the time being (decided after discussion with Guy)
        return GENCP_STATUS_SUCCESS;
    }
}





// uint16_t GENCPCLIENT_WriteBuffer(uint32_t address, uint8_t* pBuffer, uint32_t length)
// {
//     if(gGencpInitWasSuccessfull)
//     {
//         uint32_t command_size_bytes = 0;
//         uint32_t AckMsgRdyStatus = ACK_NOT_READY;
//         uint8_t timerIsExpired = 0;
//
//         PRINT_DEBUG("\n\r\n\rGENCP CLIENT     - Write data to buffer at address 0x%x", address);
//
//         // WV [20201026] C O M P O S E   T H E   W R I T E   C O M M A N D
//         PRINT_DEBUG("\n\rGENCP CLIENT     - Compose the GENCP Write command...");
//         command_size_bytes = GENCPCLIENT_ComposeWriteCommand((uint64_t) address, length, pBuffer);
//
//         PRINT_DEBUG(" DONE: GENCP package consists of %d bytes.", command_size_bytes);
//
//
//         // WV [20201026] S E N D   T H E   C O M M A N D   T O   T H E   S E N S O R   M O D U L E   O V E R   U A R T
//         PRINT_DEBUG("\n\rGENCP CLIENT     - Send the write command by UART...");
//         GENCPCLIENT_sendCommand(command_size_bytes);
//
//         // WV [20201026] R E A D   T H E   R E S P O N S E
//         PRINT_DEBUG("\n\rGENCP CLIENT     - Waiting for GENCP ACK...");
//
//         AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(1, &timerIsExpired);      // WV [20201104] Start timer
//         do
//         {
//             AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(0, &timerIsExpired);
//         }while( (AckMsgRdyStatus == ACK_NOT_READY) && (!timerIsExpired) );
//
//         if(timerIsExpired)
//         {
//             PRINT_ERROR("\n\r\n\r\033[91m***ERROR***\033[0m GENCP CLIENT     - Timeout occurred while writing register 0x%08x!\n\r", address);
//             return GENCP_STATUS_MSG_TIMEOUT;
//         }
//         else
//         {
//             PRINT_DEBUG("\n\rGENCP CLIENT     - Buffer has been written - GENCP status: %d", pRxBuffer->ccd.flags_status_u16);
//             return __builtin_bswap16(pRxBuffer->ccd.flags_status_u16);
//         }
//     }
//     else
//     {
//         // The register write was not done, however a SUCCESS is reported for the time being (decided after discussion with Guy)
//         return GENCP_STATUS_SUCCESS;
//     }
// }

static uint32_t GENCPCLIENT_ComposeWriteCommand(uint64_t address, uint16_t write_length_b, uint8_t* data)
{
    uint32_t size = 0;
    uint32_t command_size_bytes;
    uint16_t SCD_size = 8 + write_length_b;

    /** Note:   The byte must be transmit in Big Endian mode, thus the MSB and LSB byte must be inverted in the transmission,
                the "__builtin_bswap16" function is used in order to swap the byte of each packet. */

    // WV [202010] 24 bytes used out of the 1024 byte TX buffer: 1000 bytes left for data
    const uint32_t overhead_b = sizeof(pTxBuffer->prefix) + sizeof(pTxBuffer->ccd) + sizeof(address);

    // P R E F I X
    pTxBuffer->prefix.preamble_u16      = __builtin_bswap16(GENCP_PREAMBLE);
    pTxBuffer->prefix.ccd_crc_16        = 0;                    // WV [20201023] will be overwritten later
    pTxBuffer->prefix.scd_crc_16        = 0;                    // WV [20201023] will be overwritten later
    pTxBuffer->prefix.channel_id_u16    = 0;

    // C O M M O N   C O M M A N D   D A T A
    pTxBuffer->ccd.flags_status_u16     = __builtin_bswap16(GENCP_CMD_FLAG_REQUEST_ACK);
    pTxBuffer->ccd.command_id_u16       = __builtin_bswap16(GENCP_WRITEMEM_CMD);
    pTxBuffer->ccd.scd_length_u16       = __builtin_bswap16(SCD_size);              // SCD section consists of 12 bytes
    pTxBuffer->ccd.request_id_u16       = __builtin_bswap16(GENCPCLIENT_getNextRequestId());

    // S P E C I F I C   C O M M A N D   D A T A
    *((uint64_t*) &pTxBuffer->pScd_u16[0])  = __builtin_bswap64(address);               // 8 bytes

    if(write_length_b <= (GENCP_TX_BUF_SIZE - overhead_b))
    {
        //if(GENCP_isNonSwapAddress((uint32_t) address))
        if(GENCPCLIENT_isNonSwapCase((uint32_t) address))
        {
            memcpy(((uint8_t*) &pTxBuffer->pScd_u16[0]) + 8, data, write_length_b);
            // if(address == SENSORMODULE_REMOTE_FAC_BUFFER_BASE_ADDRESS){
                PRINT_INFO("\n\rGENCP CLIENT     - First bytes: 0x%02x | 0x%02x | 0x%02x", (((uint8_t*) &pTxBuffer->pScd_u16[0]) + 8)[0], (((uint8_t*) &pTxBuffer->pScd_u16[0]) + 8)[1], (((uint8_t*) &pTxBuffer->pScd_u16[0]) + 8)[2]);
            // }
        }
        else
        {
            PRINT_DEBUG("\n\rGENCP CLIENT     - Compose Write: swap address range.");
            uint32_t i,j = 0;
            // Swapping of normal register data which are integer values
            for(i = 0; i < write_length_b/4; i++)
            {
                for(j = 0; j < 4; j++)
                {
                    *(((uint8_t*) &pTxBuffer->pScd_u16[0]) + 8 + write_length_b - 4*i - 1 - j) = *(data + 4*i + j);
                    PRINT_DEBUG(" 0x%02x", *(data + 4*i + j));
                }
            }
        }
    }

    // C O M P L E T E   T H E   C H E C K S U M   F O R   C H A N N E L   I D   &   C C D
    size = 0;
    size += sizeof(pTxBuffer->prefix.channel_id_u16);
    size += sizeof(pTxBuffer->ccd);
    pTxBuffer->prefix.ccd_crc_16        = __builtin_bswap16( GENCP_crc16((uint8_t*) &pTxBuffer->prefix.channel_id_u16, size) );

    // C O M P L E T E   T H E   C H E C K S U M   F O R   C H A N N E L   I D   &   C C D   &   S C D
    size += SCD_size;
    pTxBuffer->prefix.scd_crc_16        = __builtin_bswap16( GENCP_crc16((uint8_t*) &pTxBuffer->prefix.channel_id_u16, size) );

    command_size_bytes = sizeof(pTxBuffer->prefix) + sizeof(pTxBuffer->ccd) + SCD_size;

    return command_size_bytes;
}

/*_____                _            _____ _  __
 |  __ \              | |     /\   / ____| |/ /
 | |__) |___  __ _  __| |    /  \ | |    | ' /   _ __ ___   ___  ___ ___  __ _  __ _  ___
 |  _  // _ \/ _` |/ _` |   / /\ \| |    |  <   | '_ ` _ \ / _ \/ __/ __|/ _` |/ _` |/ _ \
 | | \ \  __/ (_| | (_| |  / ____ \ |____| . \  | | | | | |  __/\__ \__ \ (_| | (_| |  __/
 |_|  \_\___|\__,_|\__,_| /_/    \_\_____|_|\_\ |_| |_| |_|\___||___/___/\__,_|\__, |\___|
                                                                                __/ |
                                                                               |___/
 */
static uint32_t GENCPCLIENT_IsAckMsgRdy(uint8_t startTimer, uint8_t* timerIsExpired)
{
    uint32_t Status_u32 = ACK_NOT_READY;
    uint8_t* pAckStartPtr_u8 = (uint8_t*) pRxBuffer;

    static uint8_t AckMsgState = HUNTING_PREAMBLE_0;
    static uint32_t RxIndex = 0;

    if(startTimer)
    {
        nb_timer_start(TIMER_GENCPCLIENT_PTT, GENCPCLIENT_GetPackageTransferTime());
        AckMsgState = HUNTING_PREAMBLE_0;
    }
    else
    {
        // pr_info("Called from: %pS\n", __builtin_return_address(0));
        if(nb_timer_is_expired(TIMER_GENCPCLIENT_PTT))
        { // If received more data after a Packet Transfer Time (PTT) timeout
            *timerIsExpired = 1;                // Set the Timer expired flag HIGH!
            memset(pRxBuffer, 0, sizeof(GENCP_MSG));
            AckMsgState = HUNTING_PREAMBLE_0;
        }

        uint8_t byteReceived_u8 = 0xab;
        while (SUCCESS == unio_read_byte(unio_handle_ptr, &byteReceived_u8))
        {
            switch (AckMsgState)
            {
                case HUNTING_PREAMBLE_0:
                    PRINT_DEBUG(" 0x%02x", byteReceived_u8);
                    RxIndex = 0;
                    if (byteReceived_u8 == GENCP_PREAMBLE_BYTE_0)
                    {
                        AckMsgState = HUNTING_PREAMBLE_1;
                        PRINT_DEBUG(" PREAMBLE 0");
                        *timerIsExpired = 0;
                        nb_timer_start(TIMER_GENCPCLIENT_PTT, GENCPCLIENT_GetPackageTransferTime());
                        RxIndex++;
                    }
                    break;

                case HUNTING_PREAMBLE_1:
                    PRINT_DEBUG(" 0x%02x", byteReceived_u8);
                    if (byteReceived_u8 == GENCP_PREAMBLE_BYTE_1)
                    {
                        AckMsgState = WAIT_CCD;
                        PRINT_DEBUG(" PREAMBLE 1");
                        *timerIsExpired = 0;
                        nb_timer_start(TIMER_GENCPCLIENT_PTT, GENCPCLIENT_GetPackageTransferTime());
                        RxIndex++;
                    } else
                        AckMsgState = HUNTING_PREAMBLE_0;
                    break;

                case WAIT_CCD:
                    pAckStartPtr_u8[RxIndex++] = byteReceived_u8;
                    PRINT_DEBUG(" 0x%02x", byteReceived_u8);
                    PRINT_DEBUG(" CCD");
                    *timerIsExpired = 0;
                    nb_timer_start(TIMER_GENCPCLIENT_PTT, GENCPCLIENT_GetPackageTransferTime());
                    if (RxIndex == (PREFIXE_LENGTH_BYTES + CCD_LENGTH_BYTES))
                    {   // All of Prefix + CCD have been received -> check CCD checksum
                        //uint16_t Checksum_u16 = GENCPMSG_ComputeChecksum(&gpGencpMsgCfg_X[UartId_E].pRxBuf_X->ChannelId_u16, CCD_CRC_LENGTH_W, CRC_RX_STATE);
                        uint16_t Checksum_u16 = GENCP_crc16((uint8_t *) &pRxBuffer->prefix.channel_id_u16 , CCD_CRC_LENGTH_BYTES);

                        if(Checksum_u16 == __builtin_bswap16(pRxBuffer->prefix.ccd_crc_16))
                        {
                            if(__builtin_bswap16(pRxBuffer->ccd.scd_length_u16) == 0)
                            {
                                // S T O P   H E R E   A L R E A D Y  . . .
                                nb_timer_delete(TIMER_GENCPCLIENT_PTT);
                                Status_u32 = ACK_READY;
                                RxIndex = 0;
                                AckMsgState = HUNTING_PREAMBLE_0;
                            }
                            else
                                AckMsgState = WAIT_SCD;
                        }
                        else
                        {
                            AckMsgState = WAIT_FOR_PTT_TIMEOUT;
                            PRINT_DEBUG("\n\r\n\r*** ERROR *** GENCP CLIENT     - Checksum error in ACK message [0x%08x VS 0x%08x] - wait for timeout!\n\r", Checksum_u16, pRxBuffer->prefix.ccd_crc_16);
                        }

                    } else {
                        PRINT_DEBUG("CCD: Collecting bytes for CRC, currently at %d of %d", RxIndex, PREFIXE_LENGTH_BYTES + CCD_LENGTH_BYTES);
                    }
                    break;

                case WAIT_SCD:
                    PRINT_DEBUG(" 0x%02x", byteReceived_u8);
                    PRINT_DEBUG(" SCD");
                    pAckStartPtr_u8[RxIndex++] = byteReceived_u8;

                    // All of the data have been received
                    if (RxIndex == (PREFIXE_LENGTH_BYTES + CCD_LENGTH_BYTES + __builtin_bswap16(pRxBuffer->ccd.scd_length_u16)))
                    {
                        nb_timer_delete(TIMER_GENCPCLIENT_PTT);
                        Status_u32 = ACK_READY;
                        RxIndex = 0;
                        AckMsgState = HUNTING_PREAMBLE_0;
                    }
                    else {
                        *timerIsExpired = 0;
                        nb_timer_start(TIMER_GENCPCLIENT_PTT, GENCPCLIENT_GetPackageTransferTime());
                    }
                    break;

                case WAIT_FOR_PTT_TIMEOUT:  // Wait for PTT Timeout event (manage in upper if function)
                    PRINT_DEBUG(" --- WAIT_FOR_PTT_TIMEOUT ---");
                    // nb_timer_start(TIMER_GENCPCLIENT_PTT, GENCPCLIENT_GetPackageTransferTime());
                    break;
            }

            if (RxIndex > GENCP_RX_BUF_INDEX_MAX)
            {   // Exceed the end of GENCP RX Buf => Not receive all of the message
                RxIndex = 0;
                AckMsgState = HUNTING_PREAMBLE_0;
            }
        }
    }

    return Status_u32;
}

/*_    _      _                   ______                _   _
 | |  | |    | |                 |  ____|              | | (_)
 | |__| | ___| |_ __   ___ _ __  | |__ _   _ _ __   ___| |_ _  ___  _ __  ___
 |  __  |/ _ \ | '_ \ / _ \ '__| |  __| | | | '_ \ / __| __| |/ _ \| '_ \/ __|
 | |  | |  __/ | |_) |  __/ |    | |  | |_| | | | | (__| |_| | (_) | | | \__ \
 |_|  |_|\___|_| .__/ \___|_|    |_|   \__,_|_| |_|\___|\__|_|\___/|_| |_|___/
               | |
               |_|
 */
static uint32_t GENCPCLIENT_getNextRequestId(void)
{
    static uint16_t requestId = 0;

    requestId++;
    if(requestId == 0)
        requestId = 1;

    return requestId;
}

static uint32_t GENCPCLIENT_GetPackageTransferTime()
{
    // PRINT_DEBUG("\n\rGENCP CLIENT     - Packet transfer time: %d", (uint32_t) (GENCP_RX_BUF_SIZE * 12500 / gpBaudrate_u32(gGencpClientUartId)));
    // //return (uint32_t) (GENCP_RX_BUF_SIZE * 12500 / UART_GetBaudrate(gGencpClientUartId));
    // // WV timeout issues for cameralink... increase margin...
    // return (uint32_t) (2 * GENCP_RX_BUF_SIZE * 12500 / gpBaudrate_u32(gGencpClientUartId));
    return (uint32_t) (2 * GENCP_RX_BUF_SIZE * 12500 / 9600); // FIX: change this
}

static void GENCPCLIENT_sendCommand(uint32_t size_bytes)
{
    // Call to write command
    unio_write(unio_handle_ptr, (uint8_t*) &pTxBuffer->prefix.preamble_u16, size_bytes);

    PRINT_DEBUG("\n\rGENCP REQUEST: ");
    for(uint32_t i=0; i<size_bytes; i++)
        PRINT_DEBUG("[%02xh] ", *(((uint8_t*) &pTxBuffer->prefix.preamble_u16)+i) );
}

static uint8_t GENCPCLIENT_isNonSwapCase(uint32_t address)
{
    uint8_t isNonSwapCase = 0;
    // uint8_t isInRemoteFileAccessBufferRange = 0;

    // FIX: Verify this

    // isInRemoteFileAccessBufferRange = ((SENSORMODULE_REMOTE_FAC_BUFFER_BASE_ADDRESS <= address) && (address < (SENSORMODULE_REMOTE_FAC_BUFFER_BASE_ADDRESS + 0x1000))) ? 1:0;
    //
    // isNonSwapCase = (isInRemoteFileAccessBufferRange) ? 1:0;

    //if(address == SENSORMODULE_REMOTE_FAC_BUFFER_BASE_ADDRESS)
    //      PRINT_DEBUG("\n\rGENCP CLIENT     -----------------      isNonSwapCase: %d", isNonSwapCase);

    return isNonSwapCase;
}

bool GENCPCLIENT_isSuccesfullyInitialized(void) {return gGencpInitWasSuccessfull;}


// uint16_t GENCPCLIENT_ReadString(uint32_t address, uint8_t* my_string, uint32_t lenght)
// {
//     PRINT_DEBUG("\n\r\n\rGENCP CLIENT     - Read register 0x%08x", address);
//     uint32_t command_size_bytes = 0;
//     uint32_t AckMsgRdyStatus = ACK_NOT_READY;
//     uint8_t timerIsExpired = 0;
//     uint16_t status = GENCP_STATUS_SUCCESS;
//     //uint32_t tempdata;
//
//     // WV [20201026] C O M P O S E   T H E   R E A D   C O M M A N D
//     PRINT_DEBUG("\n\rGENCP CLIENT     - Compose the GENCP Read command...");
//     command_size_bytes = GENCPCLIENT_ComposeReadCommand((uint64_t) address, lenght);
//     PRINT_DEBUG(" DONE: GENCP package consists of %d bytes.", command_size_bytes);
//
//     // WV [20201026] S E N D   T H E   C O M M A N D   T O   T H E   S E N S O R   M O D U L E  O V E R   U A R T
//     PRINT_DEBUG("\n\rGENCP CLIENT     - Send the read command by UART...");
//     //PRINT_DEBUG("\n\rSEND");
//     GENCPCLIENT_sendCommand(command_size_bytes);
//
//     // WV [20201026] R E A D   T H E   R E S P O N S E
//     PRINT_DEBUG("\n\rGENCP CLIENT     - Waiting for GENCP ACK...");
//     AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(1, &timerIsExpired);      // WV [20201104] Start timer
//     do
//     {
//         //PRINT_DEBUG(" >");
//         AckMsgRdyStatus = GENCPCLIENT_IsAckMsgRdy(0, &timerIsExpired);
//     }while( (AckMsgRdyStatus == ACK_NOT_READY) && (!timerIsExpired) );
//
//     if(timerIsExpired)
//     {
//         PRINT_ERROR("\n\r\n\r\033[91m***ERROR***\033[0m GENCP CLIENT     - Timeout occurred!\n\r");
//         status = GENCP_STATUS_MSG_TIMEOUT;
//     }
//     else
//     {
//         //tempdata = *((uint32_t*) &pRxBuffer->pScd_u16[0]);
//         memcpy((void *) my_string, (void *) &pRxBuffer->pScd_u16[0], lenght);
//         status = __builtin_bswap16(pRxBuffer->ccd.flags_status_u16);
//     }
//
//     return status;
// }
