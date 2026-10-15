/* GenCP I2C transport selected at build time, independently for each module. */
#ifndef GENCP_TRANSPORT_CONFIG_H
#define GENCP_TRANSPORT_CONFIG_H

/* Keep the deployed MicroLynx FIFO transport as the default. */
#ifndef GENCP_I2C_BUFFER_SIZE
#define GENCP_I2C_BUFFER_SIZE 16
#endif

#if GENCP_I2C_BUFFER_SIZE != 16 && GENCP_I2C_BUFFER_SIZE != 1024
#error "GenCP I2C transport must use a 16-byte FIFO or a 1024-byte buffer"
#endif

#endif
