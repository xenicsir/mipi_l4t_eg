/*
 * An I2C library for Xenix Exosens cameras.
 *
 */

#include "ecctrl_i2c_common.h"

// #define I2C_DELAY_ENABLE
#define I2C_DELAY 10000

#define CRC8_POLYNOMIAL 	0x38
#define CRC8_INIT_VALUE    0xFF
#define CRC8_TABLE_SIZE    256

#define FRAME_SIZE_MAX	240
#define NB_RETRY_MAX	5

#define STATUS_INT_ERR -128
#define STATUS_FIFO_EMPTY 1


static uint8_t crc8_table[CRC8_TABLE_SIZE];

static inline void crc8_populate_msb(uint8_t table[CRC8_TABLE_SIZE], uint8_t polynomial)
{
   int i, j;
   const uint8_t msbit = 0x80;
   uint8_t t = msbit;

   table[0] = 0;

   for (i = 1; i < CRC8_TABLE_SIZE; i *= 2) {
      t = (t << 1) ^ (t & msbit ? polynomial : 0);
      for (j = 0; j < i; j++)
         table[i+j] = table[j] ^ t;
   }
}

static inline uint8_t fct_crc8(uint8_t *pdata, size_t nbytes, uint8_t crc)
{
   static int have_table = 0;

   /* This check is not thread safe; there is no mutex. */
   if (have_table == 0)
   {
      crc8_populate_msb(crc8_table, CRC8_POLYNOMIAL);
      have_table = 1;
   }

   /* loop over the buffer data */
   while (nbytes-- > 0)
      crc = crc8_table[(crc ^ *pdata++) & 0xff];

   return crc;
}

int __ecctrl_i2c_timeout_set(__ecctrl_i2c_file_t file, int timeout)
{
#if (defined (LINUX) || defined (__linux__))
#if defined(__KERNEL__)
   file->adapter->timeout = timeout;
#else // __KERNEL__
   ioctl(file, ECCTRL_I2C_TIMEOUT_SET, timeout);
#endif // __KERNEL__
#else
   // Windows
   COMMTIMEOUTS    commTimeouts;
   commTimeouts.ReadIntervalTimeout            = 0;
   commTimeouts.ReadTotalTimeoutMultiplier     = 0;
   commTimeouts.ReadTotalTimeoutConstant       = timeout;
   commTimeouts.WriteTotalTimeoutMultiplier    = 0;
   commTimeouts.WriteTotalTimeoutConstant      = timeout;
   if (!SetCommTimeouts(file, &commTimeouts))
   {
      printf("%s : Error SetCommTimeouts\n", __func__);
      return -1;
   }

#endif // LINUX
   return 0;
}


int _ecctrl_i2c_write(__ecctrl_i2c_file_t file, uint8_t *buffer_i2c, int buffer_size, int timeout)
{
   int ret = -1;

#if ((defined (LINUX) || defined (__linux__)) && !defined(__KERNEL__)) // Linux, but not kernel
   struct pollfd fds;
   fds.fd = file;
   fds.events = POLLOUT;
   if (timeout == 0)
   {
      timeout = I2C_TIMEOUT_DEFAULT;
   }
   if ((poll(&fds, 1, timeout) != 0) && (fds.revents & POLLOUT))
   {
      ret = __ecctrl_i2c_write(file, buffer_i2c, buffer_size);
   }
#else
   ret = __ecctrl_i2c_write(file, buffer_i2c, buffer_size);
#endif
   return ret;
}

int _ecctrl_i2c_read(__ecctrl_i2c_file_t file, uint8_t *buffer_i2c, int buffer_size, int timeout)
{
   int ret = -1;

#if ((defined (LINUX) || defined (__linux__)) && !defined(__KERNEL__)) // Linux, but not kernel
   struct pollfd fds;
   fds.fd = file;
   fds.events = POLLIN;
   if (timeout == 0)
   {
      timeout = I2C_TIMEOUT_DEFAULT;
   }
   if ((poll(&fds, 1, timeout) != 0) && (fds.revents & POLLIN))
   {
      ret = __ecctrl_i2c_read(file, buffer_i2c, buffer_size);
   }
#else
   ret = __ecctrl_i2c_read(file, buffer_i2c, buffer_size);
#endif
   return ret;
}


int __ecctrl_i2c_write_reg(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args)
{
   int ret = 0;
   uint8_t *buffer_i2c = NULL;
   int buffer_index = 0;
   int buffer_start = 0;
   int frame_size = 0;
   int buffer_size = 0;
   uint8_t crc8;
   int error = 0;
   int cpt_retry = 0;
   int cpt_retry_max = NB_RETRY_MAX;
   int status = 0;

   if (args)
   {
      __ecctrl_i2c_print(LOG_DBG, "%s 0x%x %u bytes\n", __func__, args->data_address, args->data_size);

      if (args->i2c_tries_max > 0)
      {
         cpt_retry_max = args->i2c_tries_max;
      }
      if (args->i2c_timeout == 0)
      {
         args->i2c_timeout = I2C_TIMEOUT_DEFAULT;
      }

      do
      {
         error = 0;
         frame_size = args->data_size + 5; 	// size of the frame without CRC = op code (1) + register address (4) + data (size)
         buffer_size = frame_size + 2; 		// buffer includes frame size byte (1) + frame (frame_size) + CRC (1)
         if (args->deviceType == ECCTRL_UVC_TYPE)  // I2C timeout is added at the beginning of the frame
         {
            buffer_size ++;
         }
         buffer_i2c =  __ecctrl_i2c_malloc(buffer_size);
         if (buffer_i2c)
         {
            /************** Send Write register request *****************/
            __ecctrl_i2c_print(LOG_DBG, "%s : Send Write register request\n", __func__);
            buffer_index = 0;
            buffer_start = 0;
            if (args->deviceType == ECCTRL_UVC_TYPE)
            {
               buffer_i2c[buffer_index++] = args->i2c_timeout / 1000;
               buffer_start = 1;
            }
            buffer_i2c[buffer_index++] = frame_size;
            buffer_i2c[buffer_index++] = CMD_WRITE;												      // OP code
            buffer_i2c[buffer_index++] = (uint8_t)(args->data_address & 0xFF); 					// Register addr byte 0
            buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 8) & 0xFF); 			// Register addr byte 1
            buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 16) & 0xFF); 		// Register addr byte 2
            buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 24) & 0xFF); 		// Register addr byte 3
            memcpy(&buffer_i2c[buffer_index++], args->data, args->data_size); 					// Register values
            buffer_i2c[buffer_size - 1] = fct_crc8(buffer_i2c + buffer_start, buffer_size-1-buffer_start, CRC8_INIT_VALUE);	// CRC
            ret = _ecctrl_i2c_write(file, buffer_i2c, buffer_size, args->i2c_timeout);
            if (ret <= 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error sending register Write request, ret = %d\n", __func__, ret);
               error = 1;
               goto continue_write_reg;
            }
#ifdef I2C_DELAY_ENABLE
            if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
            {
               __ecctrl_i2c_usleep(I2C_DELAY);
            }
#endif

            /************** Read status *****************/
            buffer_size = 7;
            memset(buffer_i2c, 0, buffer_size);
            ret = _ecctrl_i2c_read(file, buffer_i2c, buffer_size, args->i2c_timeout);
            if (ret <= 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error receiving register Write status, ret = %d\n", __func__, ret);
               error = 1;
               goto continue_write_reg;
            }
            if (buffer_i2c[0] == 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : null frame size\n", __func__);
               error = 1;
               goto continue_write_reg;
            }

            crc8 = fct_crc8(buffer_i2c, buffer_size-1, CRC8_INIT_VALUE);
            status = buffer_i2c[2] | (buffer_i2c[3] << 8) | (buffer_i2c[4] << 16) | (buffer_i2c[5] << 24);

            if (crc8 != buffer_i2c[buffer_size-1])
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : bad frame crc (received 0x%X, expected 0x%X)\n", __func__,  buffer_i2c[buffer_size-1], crc8);
               error = 1;
               goto continue_write_reg;
            }

            if (buffer_i2c[1] != ACK_WRITE)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : frame is not ACK_WRITE\n", __func__);
               error = 1;
               goto continue_write_reg;
            }

            if (status < 0)
            {
               error = 1;
               goto continue_write_reg;
            }
            if (status != 0)
            {
               __ecctrl_i2c_print(LOG_DBG, "%s : Warning, status is %d\n", __func__, status);
            }

continue_write_reg:
            if (error == 1)
            {
               if (cpt_retry ++ > cpt_retry_max-2)
               {
                  break;
               }
            }
            __ecctrl_i2c_free(buffer_i2c);
            buffer_i2c = NULL;
         }
         else
         {
            __ecctrl_i2c_print(LOG_FATAL, "%s : Error allocating memory\n", __func__);
            return STATUS_INT_ERR;
         }
#ifdef I2C_DELAY_ENABLE
         if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
         {
            __ecctrl_i2c_usleep(I2C_DELAY);
         }
#endif

      } while (error > 0);

      if (buffer_i2c)
      {
         __ecctrl_i2c_free(buffer_i2c);
         buffer_i2c = NULL;
      }
      if (error > 0)
      {
         __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error after retries\n", __func__);
         if (status == 0)
         {
            return STATUS_INT_ERR;
         }
         else
         {
            return status;
         }
      }
      return status;
   }
   else
   {
      __ecctrl_i2c_print(LOG_FATAL, "%s : Error, parameters must not be NULL\n", __func__);
      return STATUS_INT_ERR;
   }
}

int __ecctrl_i2c_read_reg(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args)
{
   int ret = 0;
   uint8_t *buffer_i2c = NULL;
   int buffer_index = 0;
   int buffer_start = 0;
   int frame_size = 0;
   int buffer_size = 0;
   uint8_t crc8;
   int error = 0;
   int cpt_retry = 0;
   int cpt_retry_max = NB_RETRY_MAX;
   int status = 0;

   if (args)
   {
      __ecctrl_i2c_print(LOG_DBG, "%s 0x%x %u bytes\n", __func__, args->data_address, args->data_size);

      if (args->i2c_tries_max > 0)
      {
         cpt_retry_max = args->i2c_tries_max;
      }
      if (args->i2c_timeout == 0)
      {
         args->i2c_timeout = I2C_TIMEOUT_DEFAULT;
      }

      do
      {
         error = 0;
         /************** Send Read register request *****************/
         frame_size = 6; 				// size of the frame without CRC = op code (1) + register address (4) + register size (1)
         buffer_size = frame_size + 2; 	// buffer includes frame size byte (1) + frame (frame_size) + CRC (1)
         if (args->deviceType == ECCTRL_UVC_TYPE)  // I2C timeout is added at the beginning of the frame
         {
            buffer_size ++;
         }
         __ecctrl_i2c_print(LOG_DBG, "%s buffer_size %d bytes\n", __func__, buffer_size);
         buffer_i2c =  __ecctrl_i2c_malloc(buffer_size);
         if (buffer_i2c)
         {
            __ecctrl_i2c_print(LOG_DBG, "%s : Send Read register request\n", __func__);
            buffer_index = 0;
            buffer_start = 0;
            if (args->deviceType == ECCTRL_UVC_TYPE)
            {
               buffer_i2c[buffer_index++] = args->i2c_timeout / 1000;
               buffer_start = 1;
            }
            buffer_i2c[buffer_index++] = frame_size;
            buffer_i2c[buffer_index++] = CMD_READ;												         // OP code
            buffer_i2c[buffer_index++] = (uint8_t)(args->data_address & 0xFF); 					// Register addr byte 0
            buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 8) & 0xFF); 			// Register addr byte 1
            buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 16) & 0xFF); 		// Register addr byte 2
            buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 24) & 0xFF); 		// Register addr byte 3
            buffer_i2c[buffer_index++] = args->data_size;										// Register size
            buffer_i2c[buffer_size - 1] = fct_crc8(buffer_i2c + buffer_start, buffer_size-1-buffer_start, CRC8_INIT_VALUE);	// CRC

            ret = _ecctrl_i2c_write(file, buffer_i2c, buffer_size, args->i2c_timeout);
            if (ret <= 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error sending register Read request, ret = %d\n", __func__, ret);
               error = 1;
               goto continue_read_reg;
            }

            __ecctrl_i2c_free(buffer_i2c);
            buffer_i2c = NULL;
         }
         else
         {
            __ecctrl_i2c_print(LOG_FATAL, "%s : Error allocating memory\n", __func__);
            return STATUS_INT_ERR;
         }
#ifdef I2C_DELAY_ENABLE
         if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
         {
            __ecctrl_i2c_usleep(I2C_DELAY);
         }
#endif

         /************** Read data *****************/
         buffer_size = args->data_size + 7; 	// buffer includes frame size byte (1) + ACK (1) + status (4) + data (size) + CRC (1)
         buffer_i2c =  __ecctrl_i2c_malloc(buffer_size);
         if (buffer_i2c)
         {
            __ecctrl_i2c_print(LOG_DBG, "%s : _ecctrl_i2c_read %d data bytes\n", __func__, buffer_size);
            memset(buffer_i2c, 0, buffer_size);

            ret = _ecctrl_i2c_read(file, buffer_i2c, buffer_size, args->i2c_timeout);
            if (ret <= 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error receiving register data, ret = %d\n", __func__, ret);
               error = 1;
               goto continue_read_reg;
            }
            if (buffer_i2c[0] == 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : null frame size\n", __func__);
               error = 1;
               goto continue_read_reg;
            }

            // for (i = 0; i < buffer_size; i++)
            // {
            // printf("%s : buffer_i2c[%d] = 0x%x\n", __func__, i, buffer_i2c[i]);
            // }

            crc8 = fct_crc8(buffer_i2c, buffer_size-1, CRC8_INIT_VALUE);
            status = buffer_i2c[2] | (buffer_i2c[3] << 8) | (buffer_i2c[4] << 16) | (buffer_i2c[5] << 24);

            if (crc8 != buffer_i2c[buffer_size-1])
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : bad frame crc (received 0x%X, expected 0x%X)\n", __func__,  buffer_i2c[buffer_size-1], crc8);
               error = 1;
               goto continue_read_reg;
            }

            if (buffer_i2c[1] != ACK_READ)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : frame is not ACK_READ\n", __func__);
               error = 1;
               goto continue_read_reg;
            }

            if (status < 0)
            {
               error = 1;
               goto continue_read_reg;
            }
            if (status != 0)
            {
               __ecctrl_i2c_print(LOG_DBG, "%s : Warning, status is %d\n", __func__, status);
            }

            if (args->data)
            {
               memcpy(args->data, &buffer_i2c[6], args->data_size);
            }
            else
            {
               __ecctrl_i2c_print(LOG_FATAL, "%s : Error : memory corruption\n", __func__);
               status = 0;
               error = 1;
               goto continue_read_reg;
            }

continue_read_reg:
            if (error == 1)
            {
               if (cpt_retry ++ > cpt_retry_max-2)
               {
                  break;
               }
            }

            __ecctrl_i2c_free(buffer_i2c);
            buffer_i2c = NULL;
         }
         else
         {
            __ecctrl_i2c_print(LOG_FATAL, "%s : Error allocating memory\n", __func__);
            return STATUS_INT_ERR;
         }
#ifdef I2C_DELAY_ENABLE
         if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
         {
            __ecctrl_i2c_usleep(I2C_DELAY);
         }
#endif
      } while (error > 0);

      if (buffer_i2c)
      {
         __ecctrl_i2c_free(buffer_i2c);
         buffer_i2c = NULL;
      }
      if (error > 0)
      {
         __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error after retries (status = %d)\n", __func__, status);
         if (status == 0)
         {
            return STATUS_INT_ERR;
         }
         else
         {
            return status;
         }
      }
      return status;
   }
   else
   {
      __ecctrl_i2c_print(LOG_FATAL, "%s : Error, parameters must not be NULL\n", __func__);
      return STATUS_INT_ERR;
   }
}


int __ecctrl_i2c_write_fifo(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args)
{
   int ret = 0;
   uint8_t *buffer_i2c = NULL;
   int buffer_index = 0;
   int buffer_start = 0;
   int frame_size = 0;
   int packet_size_max = 0;
   int buffer_size = 0;
   int data_index = 0;
   int payload_size = 0;
   uint8_t crc8;
   uint8_t fifoOp = FIFO_OP_CONTINUE;
   uint32_t size = args->data_size;
   int cpt_retry = 0;
   int cpt_retry_max = NB_RETRY_MAX;
   int status = 0;
   int control_size = 2; // frame size (1) + CRC (1)
   int header_size = 6; // op code (1) - fifo op (1) - fifo addr(4)
   int noerror = 0;

   if (args)
   {
      __ecctrl_i2c_print(LOG_DBG, "%s 0x%x %u bytes\n", __func__, args->data_address, size);

      if (args->i2c_tries_max > 0)
      {
         cpt_retry_max = args->i2c_tries_max;
      }
      if (args->i2c_tries_max < 0)
      {
         noerror = 1;
      }
      if (args->i2c_timeout == 0)
      {
         args->i2c_timeout = I2C_TIMEOUT_DEFAULT;
      }

      /************** Send data Write FIFO requests *****************/
      if (args->deviceType == ECCTRL_UVC_TYPE)  // I2C timeout is added at the beginning of the frame
      {
         control_size ++;
      }
      packet_size_max = FRAME_SIZE_MAX + control_size; // FRAME_SIZE_MAX + control bytes
      buffer_i2c =  __ecctrl_i2c_malloc(packet_size_max);
      if (buffer_i2c)
      {
         data_index = 0;
         if (args->fifo_flags & FIFO_FLAG_START)
         {
            fifoOp |= FIFO_OP_START;
         }
         while (size > 0)
         {
            int error = 0;
            cpt_retry = 0;
            do
            {
               error = 0;
               payload_size = packet_size_max - control_size - header_size;	// actual transmited data size = max packet size - control bytes size - header size
               payload_size = payload_size/4*4;	// payload_size better be a multiple of 4 for memory access
               if (size < payload_size)			// last packet
               {
                  payload_size = size;
                  if (args->fifo_flags & FIFO_FLAG_END)
                  {
                     fifoOp |= FIFO_OP_END;
                  }
               }
               frame_size = payload_size + header_size;
               buffer_size = frame_size + control_size; 	// buffer includes frame size byte (1) + control bytes size
               __ecctrl_i2c_print(LOG_DBG, "%s : Send Data Write FIFO request index %d, size %d (packet size %d)\n", __func__, data_index, payload_size, buffer_size);
               buffer_index = 0;
               buffer_start = 0;
               if (args->deviceType == ECCTRL_UVC_TYPE)
               {
                  buffer_i2c[buffer_index++] = args->i2c_timeout / 1000;
                  buffer_start = 1;
               }
               buffer_i2c[buffer_index++] = frame_size;
               buffer_i2c[buffer_index++] = CMD_WRITE_FIFO;										      // OP code
               buffer_i2c[buffer_index++] = fifoOp;					 							      // FIFO OP
               buffer_i2c[buffer_index++] = (uint8_t)(args->data_address & 0xFF); 				// FIFO addr byte 0
               buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 8) & 0xFF); 		// FIFO addr byte 1
               buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 16) & 0xFF); 	// FIFO addr byte 2
               buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 24) & 0xFF); 	// FIFO addr byte 3
               memcpy(&buffer_i2c[buffer_index++], args->data + data_index, payload_size); 	// Data values
               buffer_i2c[buffer_size - 1] = fct_crc8(buffer_i2c + buffer_start, buffer_size-1-buffer_start, CRC8_INIT_VALUE);	// CRC
               ret = _ecctrl_i2c_write(file, buffer_i2c, buffer_size, args->i2c_timeout);
               if (ret <= 0)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error sending Data Write FIFO request, ret = %d\n", __func__, ret);
                  error = 1;
                  goto continue_write_fifo;
               }
#ifdef I2C_DELAY_ENABLE
               if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
               {
                  __ecctrl_i2c_usleep(I2C_DELAY);
               }
#endif


               /************** Read status frame *****************/
               buffer_size = 7;
               memset(buffer_i2c, 0, buffer_size);
               ret = _ecctrl_i2c_read(file, buffer_i2c, buffer_size, args->i2c_timeout);
               if (ret <= 0)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error receiving frame status, ret = %d\n", __func__, ret);
                  error = 1;
                  goto continue_write_fifo;
               }
               if (buffer_i2c[0] == 0)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : null frame size\n", __func__);
                  error = 1;
                  goto continue_write_fifo;
               }
               crc8 = fct_crc8(buffer_i2c, buffer_size-1, CRC8_INIT_VALUE);
               status = buffer_i2c[2] | (buffer_i2c[3] << 8) | (buffer_i2c[4] << 16) | (buffer_i2c[5] << 24);
               if (crc8 != buffer_i2c[buffer_size-1])
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : bad frame crc (received 0x%X, expected 0x%X)\n", __func__,  buffer_i2c[buffer_size-1], crc8);
                  error = 1;
                  goto continue_write_fifo;
               }
               if (buffer_i2c[1] != ACK_WRITE_FIFO)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : frame is not ACK_WRITE_FIFO\n", __func__);
                  error = 1;
                  goto continue_write_fifo;
               }

               if (status < 0)
               {
                  error = 1;
                  goto continue_write_fifo;
               }
               if (status != 0)
               {
                  __ecctrl_i2c_print(LOG_DBG, "%s : Warning, status is %d\n", __func__, status);
               }

continue_write_fifo:
               if (noerror)
               {
                  error = 0;
                  status = 0;
                  break;
               }
               if (error > 0)
               {
                  if (args->fifo_flags & FIFO_OP_RETRY)
                  {
                     fifoOp |= FIFO_OP_RETRY;
                  }
                  if (cpt_retry ++ > cpt_retry_max-2)
                  {
                     break;
                  }
               }
#ifdef I2C_DELAY_ENABLE
               if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
               {
                  __ecctrl_i2c_usleep(I2C_DELAY);
               }
#endif
            } while (error > 0);

            if (error > 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error after retries\n", __func__);
               __ecctrl_i2c_free(buffer_i2c);
               buffer_i2c = NULL;
               if (status == 0)
               {
                  return STATUS_INT_ERR;
               }
               else
               {
                  return status;
               }
            }

            fifoOp = FIFO_OP_CONTINUE;
            size -= payload_size;
            data_index += payload_size;
            if (args->cb)
            {
               args->cb();
            }
#ifdef I2C_DELAY_ENABLE
            if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
            {
               __ecctrl_i2c_usleep(I2C_DELAY);
            }
#endif
         }
         __ecctrl_i2c_free(buffer_i2c);
         buffer_i2c = NULL;
      }
      else
      {
         __ecctrl_i2c_print(LOG_FATAL, "%s : Error allocating memory\n", __func__);
         return STATUS_INT_ERR;
      }

      __ecctrl_i2c_print(LOG_DBG, "%s : returned status %d\n", __func__, status);
      return status;
   }
   else
   {
      __ecctrl_i2c_print(LOG_FATAL, "%s : Error, parameters must not be NULL\n", __func__);
      return STATUS_INT_ERR;
   }
}

int __ecctrl_i2c_read_fifo(__ecctrl_i2c_file_t file, ecctrl_i2c_t *args)
{
   int ret = 0;
   uint8_t *buffer_i2c = NULL;
   int buffer_index = 0;
   int buffer_start = 0;
   int frame_size = 0;
   int buffer_size = 0;
   int buffer_size_max = 0;
   int data_index = 0;
   int payload_size = 0;
   uint8_t crc8;
   uint8_t fifoOp = FIFO_OP_CONTINUE;
   uint64_t size = args->data_size;
   int cpt_retry = 0;
   int cpt_retry_max = NB_RETRY_MAX;
   int status = 0;
   int control_size = 2; // frame size (1) + CRC (1)
   uint8_t overhead_rx = 8; // frame size byte (1) + op code (1) + status (4) + data read size (1) + crc (1)
   int noerror = 0;

   if (args)
   {
      __ecctrl_i2c_print(LOG_DBG, "%s 0x%x %llu bytes\n", __func__, args->data_address, size);

      if (args->i2c_tries_max > 0)
      {
         cpt_retry_max = args->i2c_tries_max;
      }
      if (args->i2c_tries_max < 0)
      {
         noerror = 1;
      }
      if (args->i2c_timeout == 0)
      {
         args->i2c_timeout = I2C_TIMEOUT_DEFAULT;
      }

      /************** Send data Read FIFO requests *****************/
      buffer_size_max = FRAME_SIZE_MAX + control_size; 	// FRAME_SIZE_MAX + control bytes
      buffer_i2c =  __ecctrl_i2c_malloc(buffer_size_max); // allocate the buffer with size for the received packet, which is bigger than the transmitted packet
      if (buffer_i2c)
      {
         data_index = 0;
         if (args->fifo_flags & FIFO_FLAG_START)
         {
            fifoOp |= FIFO_OP_START;
         }
         while (size > 0)
         {
            int error = 0;
            cpt_retry = 0;
            do
            {
               error = 0;
               /************** Send data Read FIFO OP code *****************/
               frame_size = 7;  					// frame_size = OP code(1) + fifo op(1) + fifo addr(4) + expected data size to be received (1)
               payload_size = buffer_size_max - overhead_rx;	// actual transmited data size = buffer size max - overhead rx size
               // if (args->deviceType == ECCTRL_UVC_TYPE)  // I2C timeout is added at the beginning of the frame
               // {
                  // payload_size --;
               // }
               payload_size = payload_size/4*4;	// payload_size'd better be a multiple of 4 for memory access
               if (size < payload_size)			// last packet
               {
                  payload_size = size;
                  if (args->fifo_flags & FIFO_FLAG_END)
                  {
                     fifoOp |= FIFO_OP_END;
                  }
               }
               buffer_size = frame_size + control_size; 	// buffer includes frame (frame_size) + control bytes
               if (args->deviceType == ECCTRL_UVC_TYPE)  // I2C timeout is added at the beginning of the frame
               {
                  buffer_size ++;
               }
               __ecctrl_i2c_print(LOG_DBG, "%s : Send Data Read FIFO data request index %d, size %d\n", __func__, data_index, payload_size);
               buffer_index = 0;
               buffer_start = 0;
               if (args->deviceType == ECCTRL_UVC_TYPE)
               {
                  buffer_i2c[buffer_index++] = args->i2c_timeout / 1000;
                  buffer_start = 1;
               }
               buffer_i2c[buffer_index++] = frame_size;
               buffer_i2c[buffer_index++] = CMD_READ_FIFO;											      // OP code
               buffer_i2c[buffer_index++] = fifoOp;					 							         // FIFO OP
               buffer_i2c[buffer_index++] = (uint8_t)(args->data_address & 0xFF); 					// FIFO addr byte 0
               buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 8) & 0xFF); 			// FIFO addr byte 1
               buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 16) & 0xFF); 		// FIFO addr byte 2
               buffer_i2c[buffer_index++] = (uint8_t)((args->data_address >> 24) & 0xFF); 		// FIFO addr byte 3
               buffer_i2c[buffer_index++] = payload_size;											      // expected data size to be received
               buffer_i2c[buffer_size - 1] = fct_crc8(buffer_i2c + buffer_start, buffer_size-1-buffer_start, CRC8_INIT_VALUE);	// CRC
               ret = _ecctrl_i2c_write(file, buffer_i2c, buffer_size, args->i2c_timeout);
               if (ret <= 0)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error sending Data Read FIFO request, ret = %d\n", __func__, ret);
                  error = 1;
                  goto continue_read_fifo;
               }
#ifdef I2C_DELAY_ENABLE
               if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
               {
                  __ecctrl_i2c_usleep(I2C_DELAY);
               }
#endif

               /************** Read data *****************/
               memset(buffer_i2c, 0, buffer_size_max);
               buffer_size = payload_size + overhead_rx;
               ret = _ecctrl_i2c_read(file, buffer_i2c, buffer_size, args->i2c_timeout);
               if (ret <= 0)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error reading FIFO data, ret = %d\n", __func__, ret);
                  error = 1;
                  goto continue_read_fifo;
               }
               if (buffer_i2c[0] == 0)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : null frame size\n", __func__);
                  error = 1;
                  goto continue_read_fifo;
               }

               __ecctrl_i2c_print(LOG_DBG, "%s : crc8 received = 0x%x\n", __func__, buffer_i2c[buffer_size-1]);
               crc8 = fct_crc8(buffer_i2c, buffer_size-1, CRC8_INIT_VALUE);
               status = buffer_i2c[2] | (buffer_i2c[3] << 8) | (buffer_i2c[4] << 16) | (buffer_i2c[5] << 24);
               if (crc8 != buffer_i2c[buffer_size-1])
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : bad frame crc (received 0x%X, expected 0x%X)\n", __func__,  buffer_i2c[buffer_size-1], crc8);
                  error = 1;
                  goto continue_read_fifo;
               }

               if (buffer_i2c[1] != ACK_READ_FIFO)
               {
                  __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error : frame is not ACK_READ_FIFO\n", __func__);
                  error = 1;
                  goto continue_read_fifo;
               }

               if (status < 0)
               {
                  error = 1;
                  goto continue_read_fifo;
               }
               if (status != 0)
               {
                  __ecctrl_i2c_print(LOG_DBG, "%s : Warning, status is %d\n", __func__, status);
               }

               payload_size = buffer_i2c[6];
               __ecctrl_i2c_print(LOG_DBG, "%s : size read = %d\n", __func__, payload_size);
               if (args->data)
               {
                  memcpy(args->data+data_index, &buffer_i2c[7], payload_size);
                  if (payload_size == 0 || status == STATUS_FIFO_EMPTY)	// FIFO not empty
                  {
                     // FIFO empty. Stop.
                     size = 0;
                     __ecctrl_i2c_print(LOG_DBG, "%s : FIFO empty\n", __func__);
                     break;
                  }
               }
               else
               {
                  __ecctrl_i2c_print(LOG_FATAL, "%s : Error : memory corruption\n", __func__);
                  status = 0;
                  error = 1;
                  goto continue_read_fifo;
               }

               // for (int i = 0; i < payload_size; i++)
               // {
               // __ecctrl_i2c_print(LOG_FATAL, "%s : args->data[%d] = 0x%X\n", __func__, data_index+i, args->data[data_index+i]);
               // }

continue_read_fifo:
               if (noerror)
               {
                  error = 0;
                  status = 0;
                  break;
               }
               if (error > 0)
               {
                  if (args->fifo_flags & FIFO_OP_RETRY)
                  {
                     fifoOp |= FIFO_OP_RETRY;
                  }
                  if (cpt_retry ++ > cpt_retry_max-2)
                  {
                     break;
                  }
               }
#ifdef I2C_DELAY_ENABLE
               if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
               {
                  __ecctrl_i2c_usleep(I2C_DELAY);
               }
#endif
            } while (error > 0);

            if (error > 0)
            {
               __ecctrl_i2c_print(LOG_ERROR_DBG, "%s : Error after retries\n", __func__);
               __ecctrl_i2c_free(buffer_i2c);
               buffer_i2c = NULL;
               if (status == 0)
               {
                  return STATUS_INT_ERR;
               }
               else
               {
                  return status;
               }
            }

            fifoOp = FIFO_OP_CONTINUE;
            if (args->cb)
            {
               args->cb();
            }
            __ecctrl_i2c_print(LOG_DBG, "%s : size remaining to read = %llu\n", __func__, size);
            data_index += payload_size;
            if (size == 0)
            {
               break;
            }
            size -= payload_size;
#ifdef I2C_DELAY_ENABLE
            if (args->i2c_tries_max >= 0)	// if i2c_tries_max < 0, disable sleep between i2c request. It allows to go faster (in updrade mode)
            {
               __ecctrl_i2c_usleep(I2C_DELAY);
            }
#endif
         }
         __ecctrl_i2c_free(buffer_i2c);
         buffer_i2c = NULL;
      }
      else
      {
         __ecctrl_i2c_print(LOG_FATAL, "%s : Error allocating memory\n", __func__);
         return STATUS_INT_ERR;
      }

      args->data_size = data_index;
      return status;
   }
   else
   {
      __ecctrl_i2c_print(LOG_FATAL, "%s : Error, parameters must not be NULL\n", __func__);
      return STATUS_INT_ERR;
   }
}

#if defined(__KERNEL__)
MODULE_AUTHOR("Cyril GERMAINE <c.germaine@exosens.com");
MODULE_DESCRIPTION("Xenics Exosens camera I2C library");
MODULE_LICENSE("GPL v2");
#endif
