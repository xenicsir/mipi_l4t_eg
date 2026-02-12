/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "libtarget.h"

#define GENCP_RX_BUF_SIZE                               (1024)
#define GENCP_TX_BUF_SIZE                               (1024)

#define ACK_NOT_READY                                   (1)
#define ACK_READY                                       (0)
#define SUCCESS                                         (0)
#define DEFAULT_GENCPCLIENT_HEARTBEAT_TIMEOUT_MS (3000)

// GenICam Control Protocol Command Identifiers
#define GENCP_READMEM_CMD                       (0x0800)
#define GENCP_READMEM_ACK                       (0x0801)
#define GENCP_WRITEMEM_CMD                      (0x0802)
#define GENCP_WRITEMEM_ACK                      (0x0803)
#define GENCP_PENDING_ACK                       (0x0805)
#define GENCP_EVENT_CMD                         (0x0C00)
#define GENCP_EVENT_ACK                         (0x0C01)

// GenICam CP Status Codes
#define GENCP_STATUS_SUCCESS            (0x0000)
#define GENCP_STATUS_NOT_IMPLEMENTED    (0x8001)
#define GENCP_STATUS_INVALID_PARAMETER  (0x8002)
#define GENCP_STATUS_INVALID_ADDRESS    (0x8003)
#define GENCP_STATUS_WRITE_PROTECT      (0x8004)
#define GENCP_STATUS_BAD_ALIGNMENT      (0x8005)
#define GENCP_STATUS_ACCESS_DENIED      (0x8006)
#define GENCP_STATUS_BUSY               (0x8007)
#define GENCP_STATUS_LOCAL_PROBLEM      (0x8008)
#define GENCP_STATUS_MISMATCH           (0x8009)
#define GENCP_STATUS_INVALID_PROTOCOL   (0x800A)
#define GENCP_STATUS_MSG_TIMEOUT        (0x800B)
#define GENCP_STATUS_INVALID_HEADER     (0x800E)
#define GENCP_STATUS_WRONG_CONFIG       (0x800F)
#define GENCP_STATUS_GENERIC_ERROR      (0x8FFF)

//GenICam CP command protocol flags
#define GENCP_CMD_FLAG_REQUEST_ACK      (0x4000)
#define GENCP_CMD_FLAG_RESEND           (0x8000)

//GenCP Device capability
#define GENCP_CAP_USERS_DEFINED_NAME    (0x1 << 0)
#define GENCP_CAP_ACCESS_PRIVILEGE      (0x1 << 1)
#define GENCP_CAP_MESSAGE_CHANNEL       (0x1 << 2)
#define GENCP_CAP_TIMESTAMP             (0x1 << 3)
#define GENCP_CAP_STRING_ENCODING       (0xF << 4)
#define GENCP_CAP_FAMILY_NAME           (0x1 << 8)
#define GENCP_CAP_USERS_SBRM            (0x1 << 9)
#define GENCP_CAP_ENDIANESS             (0x1 << 10)
#define GENCP_CAP_WRITEN_LENGTH_FIELD   (0x1 << 11)
#define GENCP_CAP_MULTI_EVENT           (0x1 << 12)

// Baudrate definition
enum {
   BAUDRATE_9600   = 0x00000001,
   BAUDRATE_19200  = 0x00000002,
   BAUDRATE_38400  = 0x00000004,
   BAUDRATE_57600  = 0x00000008,
   BAUDRATE_115200 = 0x00000010,
   BAUDRATE_230400 = 0x00000020,
   BAUDRATE_460800 = 0x00000040,
   BAUDRATE_921600 = 0x00000080,
};

// Bootstrap register map
#define GENCP_REG_GENCP_VERSION                                 (0x00000000)
#define GENCP_REG_MANUFACTURER_NAME                             (0x00000004)
#define GENCP_REG_MODEL_NAME                                    (0x00000044)
#define GENCP_REG_FAMILY_NAME                                   (0x00000084)
#define GENCP_REG_DEVICE_VERSION                                (0x000000C4)
#define GENCP_REG_MANUFACTURER_INFO                             (0x00000104)
#define GENCP_REG_SERIAL_NUMBER                                 (0x00000144)
#define GENCP_REG_USER_DEFINED_NAME                             (0x00000184)
#define GENCP_REG_DEVICE_CAPABILITY                             (0x000001C4)
#define GENCP_REG_MAX_DEVICE_RESPONSE_TIME                      (0x000001CC)
#define GENCP_REG_MANIFEST_TABLE_ADDRESS                        (0x000001D0)
#define GENCP_REG_SBRM_ADDRESS                                  (0x000001D8)
#define GENCP_REG_DEVICE_CONFIGURATION                          (0x000001E0)
#define GENCP_REG_HEARTBEAT_TIMEOUT                             (0x000001E8)
#define GENCP_REG_MESSAGE_CHANNEL_ID                            (0x000001EC)
#define GENCP_REG_TIMESTAMP                                     (0x000001F0)
#define GENCP_REG_TIMESTAMP_LATCH                               (0x000001F8)
#define GENCP_REG_TIMESTAMP_INCREMENT                           (0x000001FC)
#define GENCP_REG_ACCESS_PRIVILEGE                              (0x00000204)
#define GENCP_REG_ENDIANESS                                     (0x0000020C)

//Specific bootstrap registers
#define GENCP_REG_SUPPORTED_BAUDRATES                           (0x00000000)
#define GENCP_REG_CURRENT_BAUDRATE                              (0x00000004)

//Timing
#define GENCP_REG_MAX_DEVICE_RESPONSE_INIT_TIME (50)
#define GENCP_MAX_DEVICE_RESPONSE_TIME                  (300)   //GenCP section 5.4.10: should not exceed 300ms
#define GENCP_MAX_RESPONSE_TIME_THRESHOLD               (1000)
#define GENCP_HEARTBEAT_TIMEOUT                         (3000)
//#define CHANGE_BAUDRATE_TIMEOUT_MS 250   //In case the device does not receive the confirming write command with the new parameters within
                                            //  250 ms after sending the acknowledge it falls back to the original parameter set

#define CHANGE_BAUDRATE_TIMEOUT_MS      (500)


// WV [20201023] DEFS, TYPEDEFS & STRUCTS
#define GENCP_RX_BUF_INDEX_MAX                          (GENCP_RX_BUF_SIZE - 1)
#define PREFIXE_LENGTH_W                                (4)
#define PREFIXE_LENGTH_BYTES                            (PREFIXE_LENGTH_W * 2)
#define CCD_LENGTH_W                                    (4)
#define CCD_LENGTH_BYTES                                (CCD_LENGTH_W * 2)
#define SCD_DATA_OFFSET_BYTES                           (PREFIXE_LENGTH_BYTES + CCD_LENGTH_BYTES)
#define CCD_CRC_LENGTH_W                                (5)
#define CCD_CRC_LENGTH_BYTES                            (CCD_CRC_LENGTH_W * 2)
#define SCD_REG_ADDR_LENGTH_W                           (4)
#define WRITE_MEM_ACK_MSG_SCD_LENGTH_BYTES      (4)


#define READMEM_REQ_SCD_LENGTH_BYTES            (12)
#define WRITEMEM_REGADDR_LENGTH_BYTES           (8)

#define  GENCP_PREAMBLE                                         (0x0100)
#define  GENCP_PREAMBLE_BYTE_0                          (0x01)
#define  GENCP_PREAMBLE_BYTE_1                          (0x00)


/* _____ ______ _   _  _____ _____    __  __  _____  _____       _                   _
  / ____|  ____| \ | |/ ____|  __ \  |  \/  |/ ____|/ ____|     | |                 | |
 | |  __| |__  |  \| | |    | |__) | | \  / | (___ | |  __   ___| |_ _ __ _   _  ___| |_ ___
 | | |_ |  __| | . ` | |    |  ___/  | |\/| |\___ \| | |_ | / __| __| '__| | | |/ __| __/ __|
 | |__| | |____| |\  | |____| |      | |  | |____) | |__| | \__ \ |_| |  | |_| | (__| |_\__ \
  \_____|______|_| \_|\_____|_|      |_|  |_|_____/ \_____| |___/\__|_|   \__,_|\___|\__|___/
 */
typedef enum
{
   HUNTING_PREAMBLE_0 = 0,
   HUNTING_PREAMBLE_1,
   WAIT_CCD,
   WAIT_SCD,
   WAIT_FOR_PTT_TIMEOUT
}FSM_STATE;

typedef struct GenCPPrefixLayout {
        // WV [20201023] P R E F I X :   4 x uint16
    uint16_t preamble_u16;                              // preamble (= 0x0100 = SOH NULL)
    uint16_t ccd_crc_16;                                // crc-16 build form the channel_id and CCD
    uint16_t scd_crc_16;                                // crc-16 build form the channel_id, CCD, SCD (and Postfix, which is not present)
    uint16_t channel_id_u16;                    // = 0 (reserved for the default comms channel)
}GenCPPrefixLayout;

typedef struct GenCPCCDLayout {
        // WV [20201023] C O M M O N   C O M M A N D   D A T A :   4 x uint16
    uint16_t flags_status_u16;          // flags for command - request ack bit is set 0b 0100 0000 0000 0000 | status for ACK;
    uint16_t command_id_u16;                    // command_id = 0x0800 READMEM_CMD
    uint16_t scd_length_u16;                    // always 12 bytes for this cmd
    uint16_t request_id_u16;                    // reserved, set to 0
}GenCPCCDLayout;

typedef struct ReadMemCmdLayout {
    GenCPPrefixLayout prefix;
    GenCPCCDLayout ccd;

    // Specific Command Data fields
    uint64_t reg_addr;
    uint16_t reserved;
    uint16_t read_length;
}ReadMemCmdLayout;

typedef struct ReadMemAckLayout {
    GenCPPrefixLayout prefix;
    GenCPCCDLayout ccd;

    // Specific Command Data fields
    uint8_t  pData[GENCP_RX_BUF_SIZE - SCD_DATA_OFFSET_BYTES];
}ReadMemAckLayout;

typedef struct WriteMemCmdLayout {
    GenCPPrefixLayout prefix;
    GenCPCCDLayout ccd;

    // Specific Command Data fields
    uint64_t reg_addr;
    uint8_t  pData[GENCP_RX_BUF_SIZE - SCD_DATA_OFFSET_BYTES - WRITEMEM_REGADDR_LENGTH_BYTES];
}WriteMemCmdLayout;

typedef struct WriteMemAckLayout {
    GenCPPrefixLayout prefix;
    GenCPCCDLayout ccd;

    // Specific Command Data fields
    uint16_t reserved;
    uint16_t length_written;
}WriteMemAckLayout;

typedef struct
{
        GenCPPrefixLayout prefix;
        GenCPCCDLayout ccd;

        // WV [20201023] S P E C I F I C   C O M M A N D    D A T A
        uint16_t pScd_u16[(GENCP_RX_BUF_SIZE/2) - PREFIXE_LENGTH_W - CCD_LENGTH_W];  //  512 - 4 - 4 = 504 x uint16

}GENCP_MSG;

/* _____                                        ______                _   _
  / ____|                                      |  ____|              | | (_)
 | |     ___  _ __ ___  _ __ ___   ___  _ __   | |__ _   _ _ __   ___| |_ _  ___  _ __  ___
 | |    / _ \| '_ ` _ \| '_ ` _ \ / _ \| '_ \  |  __| | | | '_ \ / __| __| |/ _ \| '_ \/ __|
 | |___| (_) | | | | | | | | | | | (_) | | | | | |  | |_| | | | | (__| |_| | (_) | | | \__ \
  \_____\___/|_| |_| |_|_| |_| |_|\___/|_| |_| |_|   \__,_|_| |_|\___|\__|_|\___/|_| |_|___/
 */
// WV [20201023] F U N C T I O N   D E C L A R A T I O N S
uint16_t GENCP_crc16(uint8_t *buf, uint32_t len);
uint8_t GENCP_isNonSwapAddress(uint32_t addr);
