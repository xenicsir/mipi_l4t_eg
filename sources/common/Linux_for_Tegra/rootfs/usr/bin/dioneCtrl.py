#!/usr/bin/python3
"""
dioneCtrl.py - Xenics Dione Camera Control Module
==================================================

Overview
--------
Python module for controlling Xenics Dione thermal cameras via I2C (Linux)
or USB/Serial (Windows). Supports both direct register access and the
GenCP (Generic Camera Protocol) standard.

Requirements
------------
- Python 3
- Dependencies: pyserial, numpy

    pip install pyserial numpy
or  sudo apt install python3-serial

Installation
------------
Ensure dioneCtrl.py is in your Python path or the same directory as your script.

Quick Start
-----------
    import dioneCtrl

    # Windows (USB/Serial with GenCP)
    cam = dioneCtrl.dioneCtrl(com_device="COM20", device_type="USB", gencp_enable=True)

    # Linux (I2C without GenCP)
    cam = dioneCtrl.dioneCtrl(dev_addr=0x5b, bus=9, device_type="I2C", gencp_enable=False)

Constructor Parameters
----------------------
    bus          : int   (default: 6)      - I2C bus number (Linux only)
    dev_addr     : int   (default: 0x5a)   - I2C device address (depends on camera model)
    com_device   : str   (default: "COM0") - Serial port (Windows only, e.g., "COM20")
    device_type  : str   (default: "I2C")  - Communication type: "I2C" or "USB"
    gencp_enable : bool  (default: False)  - Enable GenCP protocol
    force_slave  : bool  (default: False)  - Use I2C_SLAVE_FORCE (0x0706) instead of
                                             I2C_SLAVE (0x0703). Required when a kernel
                                             driver (e.g. microlynx) already holds the
                                             I2C address; otherwise ioctl returns EBUSY.

Note: On Windows, device_type is automatically set to "USB".

Register Access Methods
-----------------------

Reading Registers:

    read_reg32(reg_addr)        Read a 32-bit integer
    read_reg32f(reg_addr)       Read a 32-bit float
    read_buf(reg_addr, length)  Read a byte buffer

Writing Registers:

    write_reg32(reg_addr, val)  Write a 32-bit integer
    write_reg32f(reg_addr, val) Write a 32-bit float
    write_buf(reg_addr, buf)    Write a byte buffer

Firmware Upload (command line)
------------------------------

    python dioneCtrl.py upload <file.bin> firmware   [--bus BUS] [--addr ADDR]
    python dioneCtrl.py upload <file.bin> application [--bus BUS] [--addr ADDR]

    file type choices:
        firmware      Upload as FAC_SEL.FIRMWARE    (selector = 1)
        application   Upload as FAC_SEL.APPLICATION (selector = 2)

    Defaults: --bus 6, --addr 0x5A

Firmware Upload (programmatic)
-------------------------------

    from dioneCtrl import dioneCtrl

    cam = dioneCtrl(bus=10, dev_addr=0x5A, device_type="I2C")
    cam.upload_file("myfile.bin", "application")

Examples
--------
    # Read image width
    width = cam.read_reg32(0x20001004)

    # Read temperature
    temp = cam.read_reg32f(0x2f030)

    # Read 64-byte serial number
    data = cam.read_buf(0x00000144, 64)
    serial = data[2:].decode('utf-8').rstrip('\\x00')  # Skip 2-byte header

    # Set integration time to 33333 us
    cam.write_reg32(0x00080118, 33333)

    # Set GSK (Gain Signal Knee) to 1.8
    cam.write_reg32f(0x0002F004, 1.8)

    # Write a byte buffer
    cam.write_buf(0x10011000, bytearray([0x01, 0x02, 0x03, 0x04]))

Some Register Addresses
-----------------------
    Address      Type    Description
    0x00000144   buffer  Serial number (64 bytes)
    0x20001004   int     Image width
    0x00080118   int     Integration time (us)
    0x0002F004   float   GSK (Gain Signal Knee)
    0x0002F030   float   Temperature

GenCP Status Codes
------------------
When using GenCP protocol, operations return a status string:

    GENCP_SUCCESS           Operation successful
    GENCP_NOT_IMPLEMENTED   Feature not implemented
    GENCP_INVALID_PARAMETER Invalid parameter
    GENCP_INVALID_ADDRESS   Invalid register address
    GENCP_WRITE_PROTECT     Write-protected register
    GENCP_BAD_ALIGNEMENT    Bad alignment
    GENCP_ACCESS_DENIED     Access denied
    GENCP_BUSY              Device busy
    GENCP_MSG TIMEOUT       Communication timeout
    GENCP_ERROR             Generic error

Complete Example
----------------
    import dioneCtrl

    # Initialize camera (Linux I2C example)
    cam = dioneCtrl.dioneCtrl(dev_addr=0x5b, bus=9, device_type="I2C", gencp_enable=False)

    # Read camera information
    serial = cam.read_buf(0x00000144, 64)[2:].decode('utf-8').rstrip('\\x00')
    width = cam.read_reg32(0x20001004)
    temp = cam.read_reg32f(0x2f030)

    print(f"Camera Serial: {serial}")
    print(f"Image Width: {width}")
    print(f"Temperature: {temp:.2f} C")

    # Configure camera
    cam.write_reg32(0x00080118, 33333)    # Set integration time
    cam.write_reg32f(0x0002F004, 1.8)     # Set GSK

Platform Notes
--------------
- Linux: Requires access to /dev/i2c-* devices. Run with appropriate
  permissions or add user to i2c group.
- Windows: Requires COM port access. Install appropriate USB-Serial drivers.
- I2C Address: Typical values are 0x5a or 0x5b depending on camera model.
- I2C Bus: Depends on the camera port on Jetson/RPi (check with i2cdetect).
"""

import platform
import io, os
if (platform.system() == "Linux") :
    import fcntl
import struct
import time
import serial
import numpy as np
import ctypes
from enum import IntEnum, unique

IOCTL_I2C_SLAVE       = 0x0703
IOCTL_I2C_SLAVE_FORCE = 0x0706   # use when kernel driver holds the I2C address
IOCTL_I2C_TIMEOUT     = 0x0702

GencpStatus = {
               'GENCP_SUCCESS':           0x0000,
               'GENCP_NOT_IMPLEMENTED':   0x8001,
               'GENCP_INVALID_PARAMETER': 0x8002,
               'GENCP_INVALID_ADDRESS':   0x8003,
               'GENCP_WRITE_PROTECT':     0x8004,
               'GENCP_BAD_ALIGNEMENT':    0x8005,
               'GENCP_ACCESS_DENIED':     0x8006,
               'GENCP_BUSY':              0x8007,
               'GENCP_MSG TIMEOUT':       0x800B,
               'GENCP_INVALID_HEADER':    0x800E,
               'GENCP_WRONG_CONFIG':      0x800F,
               'GENCP_ERROR':             0x8FFF}

@unique
class FAC_SEL(IntEnum):
    RECOVERY    = 0
    FIRMWARE    = 1
    APPLICATION = 2
    CORRECTION  = 3

    def __str__(self):
        return self.name


class dioneCtrl(object):

  # Maximum I2C status read attempts when the camera returns 0xFFFF (request in progress)
  POLL_ATTEMPTS = 10
  POLL_INTERVAL = 0.05   # seconds between retry attempts

  UPLOAD_BLOCKSIZE = 4096
  UPLOAD_PACKSIZE  = 1000

  def __init__(self, bus=6, dev_addr=0x5a, com_device="COM0", device_type="I2C", gencp_enable=False, force_slave=False):

    self.device_type = device_type
    if (platform.system() == "Windows") :
        self.device_type = "USB"

    if (self.device_type == "I2C") :
        self.fr=io.open("/dev/i2c-"+str(bus), "rb", buffering=0)
        self.fw=io.open("/dev/i2c-"+str(bus), "wb", buffering=0)

        _slave_ioctl = IOCTL_I2C_SLAVE_FORCE if force_slave else IOCTL_I2C_SLAVE
        fcntl.ioctl(self.fr, _slave_ioctl, dev_addr)
        fcntl.ioctl(self.fw, _slave_ioctl, dev_addr)
        fcntl.ioctl(self.fr, IOCTL_I2C_TIMEOUT, 100)
        fcntl.ioctl(self.fw, IOCTL_I2C_TIMEOUT, 100)
    else :
        self.com_device = com_device

    self.gencp_enable = gencp_enable
    self.RequestId = 0x0000

  def open_device(self):
    if (self.device_type == "USB") :
        self.ser = serial.Serial(self.com_device, timeout = 1)

  def close_device(self):
    if (self.device_type == "USB") :
        self.ser.close()

  def write_device(self, out):
    if (self.device_type == "USB") :
        ret = self.ser.write(out)
        self.ser.flush()
    else :
        ret = self.fw.write(out)
    return ret

  def read_device(self, len):
    if (self.device_type == "USB") :
        ret = self.ser.read(len)
        self.ser.flush()
    else :
        ret = self.fr.read(len)
    return ret

  def _poll_read(self, nbytes):
    """Read nbytes after a request, retrying up to POLL_ATTEMPTS times on status 0xFFFF."""
    time.sleep(self.POLL_INTERVAL)
    data = self.read_device(nbytes)
    for _ in range(1, self.POLL_ATTEMPTS):
      if len(data) < 2 or struct.unpack_from('<H', data)[0] != 0xFFFF:
        break
      time.sleep(self.POLL_INTERVAL)
      data = self.read_device(nbytes)
    return data

  def read_reg32(self, reg_addr):
    self.open_device()

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        Status, Data = self.ReadGencpReg(write_dev, read_dev, reg_addr, 4)
        ret = b'\x00\x00' + Data  # Add 2-byte prefix for compatibility
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little'))+bytearray([0x04, 0x00])
        self.write_device(out)
        ret = self._poll_read(6)

    self.close_device()
    if self.gencp_enable:
        val=struct.unpack('>L', ret[2:])
    else:
        val=struct.unpack('<L', ret[2:])

    return val[0]

  def read_reg32f(self, reg_addr):
    self.open_device()

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        Status, Data = self.ReadGencpReg(write_dev, read_dev, reg_addr, 4)
        ret = b'\x00\x00' + Data  # Add 2-byte prefix for compatibility
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little'))+bytearray([0x04, 0x00])
        self.write_device(out)
        ret = self._poll_read(6)

    self.close_device()
    if self.gencp_enable:
        val=struct.unpack('>L', ret[2:])
    else:
        val=struct.unpack('<L', ret[2:])

    if (val[0] == 0):
       return  0.0
    else :
       return struct.unpack('!f', bytes.fromhex(f'{val[0]:x}'))[0]

  def write_reg32(self, reg_addr, val):
    self.open_device()

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        data = bytearray(val.to_bytes(4, 'big'))
        Status = self.WriteGencpReg(write_dev, read_dev, reg_addr, data)
        ret = Status
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little')) \
            +bytearray([0x04, 0x00]) \
            +bytearray(val.to_bytes(4, 'little'))
        self.write_device(out)
        raw = self._poll_read(2)
        ret = struct.unpack_from('<H', raw)[0]

    self.close_device()
    return ret

  def write_reg32f(self, reg_addr, val):
    self.open_device()

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        data = bytearray(struct.pack('>f', val))
        Status = self.WriteGencpReg(write_dev, read_dev, reg_addr, data)
        ret = Status
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little')) \
            +bytearray([0x04, 0x00]) \
            +bytearray(struct.pack('<f', val))
        self.write_device(out)
        raw = self._poll_read(2)
        ret = struct.unpack_from('<H', raw)[0]

    self.close_device()
    return ret

  def read_buf(self, reg_addr, length):
    """Read <length> bytes from <reg_addr>."""

    self.open_device()

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        Status, Data = self.ReadGencpReg(write_dev, read_dev, reg_addr, length)
        ret = b'\x00\x00' + Data  # Add 2-byte prefix for compatibility
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little')) \
            + bytearray(length.to_bytes(2, 'little'))
        self.write_device(out)
        ret = self._poll_read(2 + length)

    self.close_device()
    return ret

  def write_buf(self, reg_addr, buf):
    """Write <buf> to <reg_addr>."""

    self.open_device()

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        Status = self.WriteGencpReg(write_dev, read_dev, reg_addr, buf)
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little')) \
            + bytearray(len(buf).to_bytes(2, 'little')) + buf
        self.write_device(out)
        raw = self._poll_read(2)
        Status = struct.unpack_from('<H', raw)[0]

    self.close_device()
    return Status

  # -------------------------------------------------------------------------
  # Firmware upload
  # -------------------------------------------------------------------------

  def _fac_execute_operation(self, file_op):
    """Set FileOperationSelector to <file_op>, trigger execution, and wait for completion."""
    WAIT_ATTEMPTS = 20
    WAIT_INTERVAL = 0.5

    self.write_reg32(0x10010008, file_op)       # FileOperationSelector
    result = self.write_reg32(0x1001000C, 1)    # FileOperationExecute
    if result:
      print(f"\nFile op {file_op}: status 0x{result:04X}")

    for attempt in range(WAIT_ATTEMPTS):
      time.sleep(WAIT_INTERVAL)
      result = self.read_reg32(0x10010010)      # FileOperationStatus

      if result == 2:
        continue    # BUSY, keep waiting

      if result == 1:
        print(f'\nFile operation {file_op} failed (status=0x{result:08X})')
        if attempt:
          print(f'Remained BUSY for {attempt} attempts ({WAIT_INTERVAL * attempt:.1f}s)')
        return False

      return True   # SUCCESS

    print(f'\nFile operation {file_op} timed out after {WAIT_ATTEMPTS * WAIT_INTERVAL:.1f}s')
    return False

  def _fac_write_chunk(self, chunk_data, chunk_offset):
    self.write_reg32(0x1001001C, chunk_offset)
    self.write_reg32(0x10010020, len(chunk_data))

    chunk_size = len(chunk_data)
    packets = chunk_size // self.UPLOAD_PACKSIZE

    for i in range(packets):
      self.write_buf(0x10011000 + i * self.UPLOAD_PACKSIZE, chunk_data[:self.UPLOAD_PACKSIZE])
      chunk_data = chunk_data[self.UPLOAD_PACKSIZE:]

    if chunk_size % self.UPLOAD_PACKSIZE:
      self.write_buf(0x10011000 + packets * self.UPLOAD_PACKSIZE, chunk_data)

    return self._fac_execute_operation(3)   # WRITE

  def upload_file(self, filepath, selector):
    """Upload a firmware or application binary to the camera.

    @param filepath  path to the binary package file
    @param selector  "firmware", "application", or a FAC_SEL enum value
    @return True on success, False on failure
    """
    if isinstance(selector, str):
      selector = FAC_SEL[selector.upper()]

    if selector not in (FAC_SEL.FIRMWARE, FAC_SEL.APPLICATION):
      print(f'Invalid selector {selector}: only FIRMWARE and APPLICATION are supported.')
      return False

    if not os.path.isfile(filepath):
      print(f'File not found: {filepath}')
      return False

    with open(filepath, 'rb') as f:
      blob = f.read()
    print(f'Uploading {filepath} ({len(blob)} bytes) as {selector}')

    self.write_reg32(0x80104, 0x202)    # stop acquisition
    time.sleep(1)

    self.write_reg32(0x10010000, int(selector))  # FileSelector
    self.write_reg32(0x10010004, 1)              # FileOpenMode = write
    if not self._fac_execute_operation(0):       # OPEN
      print('Failed to open file for writing.')
      return False

    filesize   = len(blob)
    blockcount = filesize // self.UPLOAD_BLOCKSIZE
    remainder  = filesize % self.UPLOAD_BLOCKSIZE
    total_chunks = blockcount + (1 if remainder else 0)

    for i in range(blockcount):
      blockdata = blob[i * self.UPLOAD_BLOCKSIZE:(i + 1) * self.UPLOAD_BLOCKSIZE]
      print(f'\rSending chunk {i + 1}/{total_chunks}', end='')
      if not self._fac_write_chunk(blockdata, i * self.UPLOAD_BLOCKSIZE):
        print(f'\nFailed at offset 0x{i * self.UPLOAD_BLOCKSIZE:08X}, aborting.')
        return False

    if remainder:
      blockdata = blob[blockcount * self.UPLOAD_BLOCKSIZE:]
      print(f'\rSending chunk {total_chunks}/{total_chunks}', end='')
      if not self._fac_write_chunk(blockdata, blockcount * self.UPLOAD_BLOCKSIZE):
        print(f'\nFailed at offset 0x{blockcount * self.UPLOAD_BLOCKSIZE:08X}, aborting.')
        return False

    if not self._fac_execute_operation(1):  # CLOSE
      print('Failed to close file.')
      return False

    return True

  # -------------------------------------------------------------------------
  # GenCP protocol
  # -------------------------------------------------------------------------

  def ComputeCrc(self, Data, ScdDataNumber):
    ComputedCrc_u32 = np.uint32(0)
    test = 0
    i = 0
    for element in Data:
      if(ScdDataNumber%2 != 0 and i == (len(Data) - 1)):
        test = ctypes.c_uint16(~(element<<8)).value
      else:
        test = ctypes.c_uint16(~element).value
      ComputedCrc_u32 = ComputedCrc_u32 + test
      i+=1

      if ComputedCrc_u32 > 0xFFFF:
        ComputedCrc_u32 = (ComputedCrc_u32 & 0xffff) + 1
    return ctypes.c_uint16(ComputedCrc_u32).value


  def ReadGencpReg(self, write_device, read_device, Address, NumberOfByte):
    MAX_RETRIES = 3
    SERIAL_TIMEOUT = 300
    NoRetries = 0
    ErrFound = 'None'

    DataToWrite_u16 = [0]*14
    DataToWrite_u16[0] = 0x0100 # Preamble
    DataToWrite_u16[3] = 0x0000 # Channel ID
    DataToWrite_u16[4] = 0x4000 # Flag
    DataToWrite_u16[5] = 0x0800 # Command ID
    DataToWrite_u16[6] = 0x000C # Length of SCD (12 Bytes for read)
    DataToWrite_u16[7] = self.RequestId
    DataToWrite_u16[8] = 0x0000 # RegAddr 3
    DataToWrite_u16[9] = 0x0000 # RegAddr 2
    DataToWrite_u16[10] = (Address >> 16) & 0xffff # RegAddr 1
    DataToWrite_u16[11] = Address & 0xffff # RegAddr 0
    DataToWrite_u16[12] = 0x0000 # Reserved
    DataToWrite_u16[13] = NumberOfByte & 0xffff # Rd Length

    CcdCrcArray = [0]*5
    for x in range(0, 5):
      CcdCrcArray[x] = DataToWrite_u16[3+x]

    ScdCrcArray = [0]*11
    for x in range(0, 11):
      ScdCrcArray[x] = DataToWrite_u16[3+x]

    DataToWrite_u16[1] = self.ComputeCrc(CcdCrcArray,0) # CCD-CRC
    DataToWrite_u16[2] = self.ComputeCrc(ScdCrcArray,4) # SCD-CRC

    ByteArray = [0]*28
    i=0;
    for element in DataToWrite_u16:
      ByteArray[i*2 + 1] = element & 0xff
      ByteArray[i*2] = (element >> 8) & 0xff
      i=i+1

    write_device.write(ByteArray)

    self.RequestId +=1
    # get current time in ms
    start = int(round(time.time() * 1000))

    i = 0
    resp = read_device.read((NumberOfByte + 16))
    while (((round(time.time() * 1000) - start) < SERIAL_TIMEOUT) and len(resp) < (NumberOfByte + 16)):
      pass

    Status = 'Error'
    Data = b'\xFF'

    if(len(resp) == (NumberOfByte + 16) or len(resp) == 16):
      for key,val in GencpStatus.items():
        if val == ((resp[8] << 8) + resp[9]):
          Status = key

      if len(resp) == (NumberOfByte + 16):
        for x in range(NumberOfByte):
          Data = resp[16:(16+NumberOfByte)]
      else:
        Data = b'\x00'

    return Status,Data


  def WriteGencpReg(self, write_device, read_device, Address, WrittenData):
    MAX_RETRIES = 3
    SERIAL_TIMEOUT = 300
    NoRetries = 0
    ErrFound = 'None'
    Data = 0

    WrittenDataArray = WrittenData

    try:
      NbrOfWord = int((len(WrittenDataArray)+1)/2)
    except:
      print('Use Vector')
      return

    DataToWrite_u16 = [0]*int(12 + NbrOfWord)
    DataToWrite_u16[0] = 0x0100 # Preamble
    DataToWrite_u16[3] = 0x0000 # Channel ID
    DataToWrite_u16[4] = 0x4000 # Flag
    DataToWrite_u16[5] = 0x0802 # Command ID
    DataToWrite_u16[6] = 8 + len(WrittenDataArray) # Length of SCD
    DataToWrite_u16[7] = self.RequestId
    DataToWrite_u16[8] = 0x0000 # RegAddr 3
    DataToWrite_u16[9] = 0x0000 # RegAddr 2
    DataToWrite_u16[10] = (Address >> 16) & 0xffff # RegAddr 1
    DataToWrite_u16[11] = Address & 0xffff # RegAddr 0

    for x in range(0,NbrOfWord):
      if ((x*2+1) == len(WrittenDataArray)) and ((len(WrittenDataArray)%2) != 0) :
        try:
          DataToWrite_u16[12+x] = ord(WrittenDataArray[x*2])
        except:
          DataToWrite_u16[12+x] = WrittenDataArray[x*2]
      else:
        try:
          DataToWrite_u16[12+x] = (ord(WrittenDataArray[x*2])<< 8) + ord(WrittenDataArray[x*2+1])
        except:
          DataToWrite_u16[12+x] = (WrittenDataArray[x*2]<< 8) + WrittenDataArray[x*2+1]

    CcdCrcArray = [0]*5
    for x in range(0, 5):
      CcdCrcArray[x] = DataToWrite_u16[3+x]

    ScdCrcArray = [0]*(9+NbrOfWord)
    for x in range(0, (9+NbrOfWord)):
      ScdCrcArray[x] = DataToWrite_u16[3+x]

    DataToWrite_u16[1] = self.ComputeCrc(CcdCrcArray,0) # CCD-CRC
    DataToWrite_u16[2] = self.ComputeCrc(ScdCrcArray,len(WrittenDataArray)) # SCD-CRC

    ByteArray = [0]*(24 + len(WrittenDataArray))
    i=0;
    for element in DataToWrite_u16:
      try:
        ByteArray[i*2 + 1] = element & 0xff
        ByteArray[i*2] = (element >> 8) & 0xff
      except:
        ByteArray[i*2] = element & 0xff
      i=i+1

    write_device.write(ByteArray)

    self.RequestId +=1
    # get current time in ms
    start = int(round(time.time() * 1000))

    i = 0
    resp = read_device.read(16)
    while (((round(time.time() * 1000) - start) < SERIAL_TIMEOUT) and len(resp) < 16):
      pass

    Status = 'Error'

    if(len(resp) == 16):
      for key,val in GencpStatus.items():
        if val == ((resp[8] << 8) + resp[9]):
          Status = key

    return Status


if __name__ == "__main__":
  import argparse
  import code

  try:
    import readline  # noqa: F401 - enables arrow keys / history in the console
  except ImportError:
    pass

  hex_int = lambda x: int(x, 0)

  parser = argparse.ArgumentParser(
      description='Dione camera control',
      formatter_class=argparse.RawDescriptionHelpFormatter,
  )

  # Connection options
  conn = parser.add_argument_group('connection')
  conn.add_argument('--device-type', choices=['I2C', 'USB'], default='I2C',
                    help='Communication type (default: I2C)')
  conn.add_argument('--bus',  type=int,     default=6,      help='I2C bus number (default: 6)')
  conn.add_argument('--addr', type=hex_int, default=0x5A,   help='I2C device address (default: 0x5A)')
  conn.add_argument('--com',  default='COM0',               help='Serial port for USB mode (default: COM0)')

  subparsers = parser.add_subparsers(dest='command')

  # upload
  p = subparsers.add_parser('upload', help='Upload a firmware or application file')
  p.add_argument('file', help='Path to the binary package file')
  p.add_argument('type', choices=['firmware', 'application'],
                 help='"firmware" (FAC_SEL=1) or "application" (FAC_SEL=2)')

  # read_reg32
  p = subparsers.add_parser('read_reg32', help='Read a 32-bit integer register')
  p.add_argument('addr', type=hex_int, help='Register address (e.g. 0x20001004)')

  # read_reg32f
  p = subparsers.add_parser('read_reg32f', help='Read a 32-bit float register')
  p.add_argument('addr', type=hex_int, help='Register address')

  # write_reg32
  p = subparsers.add_parser('write_reg32', help='Write a 32-bit integer register')
  p.add_argument('addr', type=hex_int, help='Register address')
  p.add_argument('val',  type=hex_int, help='Value to write (decimal or 0x hex)')

  # write_reg32f
  p = subparsers.add_parser('write_reg32f', help='Write a 32-bit float register')
  p.add_argument('addr', type=hex_int, help='Register address')
  p.add_argument('val',  type=float,   help='Float value to write')

  # read_buf
  p = subparsers.add_parser('read_buf', help='Read a byte buffer (hex output)')
  p.add_argument('addr',   type=hex_int, help='Register address')
  p.add_argument('length', type=int,     help='Number of bytes to read')

  # read_string
  p = subparsers.add_parser('read_string', help='Read a byte buffer and print as string')
  p.add_argument('addr',   type=hex_int, help='Register address')
  p.add_argument('length', type=int,     help='Number of bytes to read')

  args = parser.parse_args()

  if args.command:
    cam = dioneCtrl(
        bus=args.bus,
        dev_addr=args.addr,
        com_device=args.com,
        device_type=args.device_type,
    )

    if args.command == 'upload':
      if cam.upload_file(args.file, args.type):
        print('\nUpload complete. Power cycle the camera to apply the update.')
      else:
        print('\nUpload failed.')
        exit(1)

    elif args.command == 'read_reg32':
      val = cam.read_reg32(args.addr)
      print(f'0x{val:08X}  ({val})')

    elif args.command == 'read_reg32f':
      val = cam.read_reg32f(args.addr)
      print(val)

    elif args.command == 'write_reg32':
      status = cam.write_reg32(args.addr, args.val)
      print('OK' if not status else f'Error: 0x{status:04X}')

    elif args.command == 'write_reg32f':
      status = cam.write_reg32f(args.addr, args.val)
      print('OK' if not status else f'Error: 0x{status:04X}')

    elif args.command == 'read_buf':
      data = cam.read_buf(args.addr, args.length)
      print(' '.join(f'{b:02X}' for b in data[2:]))   # skip 2-byte status header

    elif args.command == 'read_string':
      data = cam.read_buf(args.addr, args.length)
      print(data[2:].decode('utf-8', errors='replace').rstrip('\x00'))

  else:
    banner = (
        "Xenics Dione camera control console\n"
        "  print(__doc__)    full documentation\n"
        "  help(dioneCtrl)   class and method reference\n"
        "\n"
        "Example: cam = dioneCtrl(dev_addr=0x5b, bus=9, device_type=\"I2C\", gencp_enable=False)\n"
        "\n"
        "CLI commands (run outside this console):\n"
        "  python dioneCtrl.py [--device-type I2C|USB] [--bus N] [--addr 0xNN] [--com COMx] <command>\n"
        "\n"
        "  read_reg32   <addr>              Read 32-bit integer\n"
        "  read_reg32f  <addr>              Read 32-bit float\n"
        "  write_reg32  <addr> <val>        Write 32-bit integer\n"
        "  write_reg32f <addr> <val>        Write 32-bit float\n"
        "  read_buf     <addr> <length>     Read byte buffer (hex output)\n"
        "  read_string  <addr> <length>     Read byte buffer (string output)\n"
        "  upload       <file> firmware|application\n"
    )
    code.interact(banner=banner, local=dict(globals(), **locals()))
