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

IOCTL_I2C_SLAVE=0x0703
IOCTL_I2C_TIMEOUT=0x0702

GencpStatus = {
               'GENCP_SUCCESS':0x0000,
               'GENCP_NOT_IMPLEMENTED':0x8001,
               'GENCP_INVALID_PARAMETER':0x8002,
               'GENCP_INVALID_ADDRESS':0x8003,
               'GENCP_WRITE_PROTECT':0x8004,
               'GENCP_BAD_ALIGNEMENT':0x8005,
               'GENCP_ACCESS_DENIED':0x8006,
               'GENCP_BUSY':0x8007,
               'GENCP_MSG TIMEOUT':0x800B,
               'GENCP_INVALID_HEADER':0x800E,
               'GENCP_WRONG_CONFIG':0x800F,
               'GENCP_ERROR':0x8FFF}

class dioneCtrl(object):

  def __init__(self, bus=6, dev_addr=0x5a, com_device="COM0", device_type="I2C", gencp_enable=False):

    self.device_type = device_type
    if (platform.system() == "Windows") :
        self.device_type = "USB"

    if (self.device_type == "I2C") :
        self.fr=io.open("/dev/i2c-"+str(bus), "rb", buffering=0)
        self.fw=io.open("/dev/i2c-"+str(bus), "wb", buffering=0)

        fcntl.ioctl(self.fr, IOCTL_I2C_SLAVE, dev_addr)
        fcntl.ioctl(self.fw, IOCTL_I2C_SLAVE, dev_addr)
        fcntl.ioctl(self.fr, IOCTL_I2C_TIMEOUT, 100)
        fcntl.ioctl(self.fw, IOCTL_I2C_TIMEOUT, 100)
    else :
        self.com_device = com_device

    self.last_file_op = -1
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

  def read_reg32(self, reg_addr):
    self.open_device()
    time.sleep(0.01)

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
        time.sleep(0.01)
        ret=self.read_device(6)

    self.close_device()
    #print(ret)
    if self.gencp_enable:
        val=struct.unpack('>L', ret[2:])
    else:
        val=struct.unpack('<L', ret[2:])
        
    return val[0]

  def read_reg32f(self, reg_addr):
    self.open_device()
    time.sleep(0.01)

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
        time.sleep(0.01)
        ret=self.read_device(6)

    self.close_device()
    #print(ret)
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
    time.sleep(0.01)

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
        time.sleep(0.01)
        ret=self.write_device(out)

    self.close_device()
    return ret

  def write_reg32f(self, reg_addr, val):
    self.open_device()
    time.sleep(0.01)

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
        time.sleep(0.01)
        ret=self.write_device(out)

    self.close_device()
    return ret


  def ack_stop(self):
    self.write_reg32(0x80104,2)
    print(hex(self.read_reg32(0x8010c)))


  def ack_start(self):
    self.write_reg32(0x80104,1)
    print(hex(self.read_reg32(0x8010c)))


  def test_solid_black(self):
    self.ack_stop()
    self.write_reg32(0x8012c,0)


  def test_solid_color(self, color):
    self.ack_stop()
    self.write_reg32(0x8012c,color << 16)


  def read_buf(self, reg_addr, length):
    """! reads <length> bytes from <reg_addr>
    """

    self.open_device()
    time.sleep(0.01)

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
        time.sleep(0.01)
        self.write_device(out)
        time.sleep(0.01)
        ret=self.read_device(2+length)

    self.close_device()
    return ret


  def write_buf(self, reg_addr, buf):
    """! writes <buf> to <reg_addr>
    """

    self.open_device()
    time.sleep(0.01)

    if self.gencp_enable:
        if self.device_type == "USB":
            write_dev = self.ser
            read_dev = self.ser
        else:  # I2C
            write_dev = self.fw
            read_dev = self.fr
        Status = self.WriteGencpReg(write_dev, read_dev, reg_addr, buf)
        # No need to read response for write operation
    else:
        out=bytearray(reg_addr.to_bytes(4, 'little')) \
            + bytearray(len(buf).to_bytes(2, 'little')) + buf
        time.sleep(0.01)
        self.write_device(out)
        time.sleep(0.01)
        # print(self.read_device(2))

    self.close_device()


  def exec_file_op(self, op):
    """! execute <op> file operation

    sets FileOperationSelector to <op>, sets FileOperationExecute to 1
    and awaits FileOperationStatus to become 0
    """

    if op != self.last_file_op :
      self.last_file_op = op
      self.write_reg32(0x10010008, op)  # FileOperationSelector
    self.write_reg32(0x1001000c, 1)     # FileOperationExecute
    ret = self.read_reg32(0x10010010)   # FileOperationStatus
    while ret == 2 :
      time.sleep(0.01)
      ret = self.read_reg32(0x10010010)
 
    if ret != 0 :
      print( "Failed to execute operation" )
      return False
    else :
      return True


  def open_file(self, idx, write_mode=False):
    """! open file no. <idx>

    @param write_mode  optional - if True, open file in WRITE mode
    """

    self.ack_stop()
    self.write_reg32(0x10010000, idx)  # FileSelector
    sel = self.read_reg32(0x10010000)
    if ( sel != idx ) :
      print( "Failed to select file" )
      return -1
    else :
      print( f'Selected file: {sel}' )

    if not write_mode:
      self.write_reg32(0x10010004, 0)  # FileOpenMode = read
    else:
      self.write_reg32(0x10010004, 1)  # FileOpenMode = write
    if not self.exec_file_op(0) :    # open
      return -1

    ret = self.read_reg32(0x10010018)
    print( f'File size: {ret}' )
    return ret


  def close_file(self):
    if not self.exec_file_op(1) :    # close
      print( "Failed to close file" )
      return False
    else:
      return True


  def read_file(self, offs, length):
    """! read current file into FileAccessBuffer

    sets FileAccessOffset to <offs>, FileAccessLength to <length> and
    executes the file read operation
    """

    retry = 4
    tmo = 0.5
    while retry > 0:
      try:
        self.write_reg32(0x1001001c, offs)    # FileAccessOffset
        self.write_reg32(0x10010020, length)  # FileAccessLength
        if not self.exec_file_op(2) :         # read
          print( "Failed to execute read" )
          return False
        else:
          return True
      except OSError:
        print( f'Retry: {retry}' )
        time.sleep(tmo)
        tmo *= 2
        retry -= 1

    print( "Failed to execute read" )
    return False


  def read_filebuf(self, length):
    """! reads contents of FileAccessBuffer

    According to documentation maximum 1000 bytes can be read
    with a single transaction. read_filebuf() breaks up the
    whole read process into 1000-byte chunks.
    It returns a bytearray.
    Maximum <length> is 4096.
    """

    buf = bytearray([])
    ofs = 0
    while length > 0 :
      read = length
      if read > 1000 :
        read = 1000

      retry = 4
      tmo = 0.5
      while retry > 0:
        try:
          ret = self.read_buf(0x10011000 + ofs, read)
          if ret[0:2] != bytearray([0,0]):
            print(f'read_buf() failed {ret[0:2]}')
            return -1
          buf += ret[2:]
          break
        except OSError:
          print( f'Retry: {retry}' )
          time.sleep(tmo)
          tmo *= 2
          retry -= 1

      if retry == 0:
        raise OSError

      length -= read
      ofs += read
    return buf


  def write_filebuf(self, buf):
    """!

    """

    length = len(buf)
    ofs = 0
    while length > 0:
      wrt = length
      if wrt > 1000:
        wrt = 1000

      retry = 4
      tmo = 0.5
      while retry > 0:
        try:
          self.write_buf(0x10011000 + ofs, buf[ofs:ofs+wrt])
          break
        except OSError:
          print( f'Retry: {retry}' )
          time.sleep(tmo)
          tmo *= 2
          retry -= 1

      if retry == 0:
        raise OSError

      length -= wrt
      ofs += wrt


  def verify_filebuf(self, buf):
    length = len(buf)
    buf2 = self.read_filebuf(length)
    return buf2==buf


  def save_file(self, idx, dst, max_len=-1, ofs=0):
    """! save contents of existing Dione file to filesystem

    @param idx      no. of Dione file to read
    @param dst      name of filesystem file to write to
    @param max_len  optional - no. of bytes to be written
    @param ofs      optional - start offset in Dione file

    it opens the Dione file with self.open_file() and reads it
    in 4096-byte chunks with self.read_filebuf()
    """

    f_dst = io.open(dst, "wb")

    length = self.open_file( idx ) - ofs

    if length > 0 :
      print( f'Length of file #{idx} : {length}' )
    else :
      print( "Failed to open file or invalid <ofs>" )
      return -1

    if max_len >= 0:
      length = max_len
      print( f'Limiting file length to {length} bytes' )

    total = 0
    read = 0
    col = 0

    while length > 0 :
      read = length
      if read > 4096 :
        read = 4096
      if not self.read_file(ofs, read) :
        print( f'Read error at offset {ofs}' )
        return -1

      f_dst.write(self.read_filebuf(read))
      total += read
      ofs += read
      length -= read
      col += 1
      print( ".", end="", flush=True)
      if col >= 64 :
        col = 0
        print()

    print()
    self.close_file()
    f_dst.close()
    print( f'Saved {total} bytes' )
    return total


  def update_file(self, idx, src):
    """! updates Dione file no. <idx>

    """

    length = os.path.getsize(src)
    print( f'Size of {src}: {length}' )

    orig_len = self.open_file(idx, 1)
    print( f'original length: {orig_len}' )
    if orig_len < 0:
      return -1

    f_src = io.open(src, "rb")

    ofs = 0
    total = 0
    col = 0
    while length > 0:
      read = length
      if read > 4096:
        read = 4096
      buf = f_src.read(read)

      retry = 4
      tmo = 0.5
      while retry > 0:
        try:
          self.last_file_op = 3
          self.write_reg32(0x10010008, 3)  # FileOperationSelector
          break
        except OSError:
          print( f'Retry: {retry}' )
          time.sleep(tmo)
          tmo *= 2
          retry -= 1

      if retry == 0:
        print( "Failed to set FileOperationSelector to 'write'" )
        self.close_file()
        f_src.close()
        return -1

      self.write_filebuf(buf)
      if not self.verify_filebuf(buf):
        print( f'Verify error at {ofs}' )
        self.close_file()
        f_src.close()
        return -1

      retry = 4
      tmo = 0.5
      while retry > 0:
        try:
          self.write_reg32(0x1001001c, ofs)     # FileAccessOffset
          self.write_reg32(0x10010020, read)    # FileAccessLength
          if not self.exec_file_op(3) :         # write
            print( "Failed to execute write" )
            self.close_file()
            f_src.close()
            return False
          else:
            break
        except OSError:
          print( f'Retry: {retry}' )
          time.sleep(tmo)
          tmo *= 2
          retry -= 1

      if retry == 0:
        print( "Failed to fill FileAccessBuffer" )
        self.close_file()
        f_src.close()
        return -1

      length -= read
      ofs += read
      total += read
      col += 1
      print( ".", end="", flush=True)
      if col >= 64 :
        col = 0
        print()

    print()
    self.close_file()
    f_src.close()
    print( f'Updated {total} bytes' )
    return total


  def hack_write_file(self, idx, buf_src):
    buf_len = len(buf_src)
    ofs = 0
    start_pad = bytearray([0] * 5)
    while buf_len > 0:
      if self.open_file(idx, 1) < 0:
        print(f'Failed to open file at offset {ofs}')
        return -1

      chunk = buf_len
      if chunk > 1024:
        chunk = 1024
      self.write_filebuf(start_pad + buf_src[ofs:ofs+chunk])

      retry = 4
      tmo = 0.5
      while retry > 0:
        try:
          self.write_reg32(0x1001001c, ofs)     # FileAccessOffset
          self.write_reg32(0x10010020, chunk)   # FileAccessLength
          if not self.exec_file_op(3) :         # write
            print(f'Failed to execute write at offset {ofs}')
            self.close_file()
            return False
          else:
            break
        except OSError:
          print( f'Retry: {retry}' )
          time.sleep(tmo)
          tmo *= 2
          retry -= 1

      if retry == 0:
        print( "Failed to execute write" )
        self.close_file()
        return -1

      if not self.close_file():
        print(f'Failed to close file at offset {ofs}')
        return -1

      ofs += chunk
      buf_len -= chunk

    self.close_file()
    print(f'Written {ofs} bytes')


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


