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
    # Read image width and height
    width  = cam.read_reg32(0x20001000)
    height = cam.read_reg32(0x20001004)

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
    0x20001000   int     Image width
    0x20001004   int     Image height
    0x00080118   int     Integration time (us)
    0x0002F004   float   GSK (Gain Signal Knee)
    0x0002F030   float   Temperature

GenCP Status Codes
------------------
A failed read raises CameraError, quoting the status word below; a write
returns it (0 = success). The same codes are used by both protocols:

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
    width  = cam.read_reg32(0x20001000)
    height = cam.read_reg32(0x20001004)
    temp = cam.read_reg32f(0x2f030)

    print(f"Camera Serial: {serial}")
    print(f"Image size: {width}x{height}")
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


class CameraError(Exception):
  """The camera answered and refused the request.

  Distinct from OSError, which means the transport itself failed (no such bus,
  address rejected, permission denied). IOError is not usable here: in Python 3
  it is an alias of OSError, so the two cases could not be told apart."""


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

  def close(self):
    """Release the I2C file descriptors. Idempotent, and safe to call twice.

    open_device()/close_device() only ever acted on the serial port; in I2C mode
    the two descriptors opened by __init__ used to live until the process died,
    which leaks one pair per instance in a console or a loop."""
    for attr in ("fr", "fw"):
      f = getattr(self, attr, None)
      if f is not None and not f.closed:
        f.close()

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc, tb):
    self.close()
    return False

  def write_device(self, out):
    if (self.device_type == "USB") :
        ret = self.ser.write(out)
        self.ser.flush()
    else :
        ret = self.fw.write(out)
    return ret

  def read_device(self, nbytes):
    if (self.device_type == "USB") :
        ret = self.ser.read(nbytes)
        self.ser.flush()
    else :
        ret = self.fr.read(nbytes)
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

  # -------------------------------------------------------------------------
  # Transport -- one place where the GenCP / raw split and the endianness live.
  # The six public accessors below are thin wrappers over _read_raw/_write_raw;
  # keep it that way, a fix applied to one accessor only is a fix half made.
  # -------------------------------------------------------------------------

  def _gencp_endpoints(self):
    """The (write, read) endpoints the GenCP helpers expect."""
    if self.device_type == "USB":
      return self.ser, self.ser
    return self.fw, self.fr

  def _u32_fmt(self):
    """struct format for a 32-bit word: GenCP is big-endian on the wire, the
    raw protocol little-endian."""
    return '>I' if self.gencp_enable else '<I'

  def _f32_fmt(self):
    return '>f' if self.gencp_enable else '<f'

  def _check_status(self, status, what):
    """Raise on a camera error. Reads used to ignore this entirely and hand back
    whatever bytes came in, so a failed transfer was indistinguishable from a
    real value."""
    if status is None:
      raise CameraError(f"{what}: no answer from the camera")
    if status:
      name = next((k for k, v in GencpStatus.items() if v == status), None)
      raise CameraError(f"{what} failed with status 0x{status:04X}"
                    + (f" ({name})" if name else ""))

  def _read_raw(self, reg_addr, nbytes):
    """Read <nbytes> at <reg_addr> and return them in wire order. Raises
    CameraError if the camera reports an error."""
    self.open_device()
    try:
      if self.gencp_enable:
        write_dev, read_dev = self._gencp_endpoints()
        status, data = self.ReadGencpReg(write_dev, read_dev, reg_addr, nbytes)
      else:
        self.write_device(bytearray(reg_addr.to_bytes(4, 'little'))
                          + bytearray(nbytes.to_bytes(2, 'little')))
        raw = self._poll_read(2 + nbytes)
        # The raw protocol has no error packet: on a refused read the CX3
        # firmware NAKs the endpoint and sends nothing at all, so an empty or
        # truncated answer *is* the error report.
        status = struct.unpack_from('<H', raw)[0] if len(raw) >= 2 else None
        data = bytes(raw[2:])
    finally:
      self.close_device()

    self._check_status(status, f"read of 0x{reg_addr:08X}")
    if len(data) != nbytes:
      # A success status with the wrong byte count means the answer was cut
      # short. Say so, rather than letting struct.unpack raise about a buffer
      # length several frames away from the cause.
      raise CameraError(f"read of 0x{reg_addr:08X}: got {len(data)} bytes, "
                        f"expected {nbytes}")
    return bytes(data)

  def _write_raw(self, reg_addr, payload):
    """Write <payload> at <reg_addr>. Returns the camera status word, 0 = OK.
    Writes return their status rather than raising: upload_file() drives the
    camera through states where a non-zero status is expected and handled."""
    self.open_device()
    try:
      if self.gencp_enable:
        write_dev, read_dev = self._gencp_endpoints()
        status = self.WriteGencpReg(write_dev, read_dev, reg_addr, payload)
      else:
        self.write_device(bytearray(reg_addr.to_bytes(4, 'little'))
                          + bytearray(len(payload).to_bytes(2, 'little'))
                          + bytearray(payload))
        ack = self._poll_read(2)
        status = struct.unpack_from('<H', ack)[0] if len(ack) >= 2 else None
    finally:
      self.close_device()
    return status

  # -------------------------------------------------------------------------
  # Public API
  # -------------------------------------------------------------------------

  def read_reg32(self, reg_addr):
    return struct.unpack(self._u32_fmt(), self._read_raw(reg_addr, 4))[0]

  def read_reg32f(self, reg_addr):
    """Read a 32-bit IEEE-754 float.

    The previous implementation round-tripped through a hex string
    (bytes.fromhex(f'{val:x}')), which drops leading zeros and can yield an
    odd-length string: every value below 0x10000000 raised ValueError or
    struct.error instead of returning a number -- 6.2 % of all bit patterns,
    and every integer register read through this method by mistake."""
    return struct.unpack(self._f32_fmt(), self._read_raw(reg_addr, 4))[0]

  def read_buf(self, reg_addr, length):
    """Read <length> bytes from <reg_addr>.

    Returns a 2-byte status header followed by the payload, so callers keep
    slicing [2:] as they always have."""
    return b'\x00\x00' + self._read_raw(reg_addr, length)

  def write_reg32(self, reg_addr, val):
    return self._write_raw(reg_addr, val.to_bytes(4, 'big' if self.gencp_enable else 'little'))

  def write_reg32f(self, reg_addr, val):
    return self._write_raw(reg_addr, struct.pack(self._f32_fmt(), val))

  def write_buf(self, reg_addr, buf):
    """Write <buf> to <reg_addr>."""
    return self._write_raw(reg_addr, buf)

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
    """Return (status, data): the numeric GenCP status word -- 0 on success,
    None if no usable answer came back -- and the payload bytes.

    The status is a number, not a status name: the raw protocol returns one
    too, and the callers must not have to tell the two apart."""
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

    # read() already blocks until the whole answer arrives or the port timeout
    # expires; the busy-wait that used to sit here could not add a single byte.
    resp = read_device.read((NumberOfByte + 16))

    # GenCP ack layout (16-byte prefix + CCD, then the payload):
    #   0-1 preamble  2-3 CCD CRC  4-5 SCD CRC  6-7 channel id
    #   8-9 status    10-11 cmd id  12-13 SCD length  14-15 request id
    # On error the camera sets the SCD length to 0, so a bare 16-byte answer is
    # a valid (failed) reply, not a truncated one.
    if len(resp) not in (16, NumberOfByte + 16):
      return None, b''

    Status = (resp[8] << 8) + resp[9]
    Data = resp[16:(16 + NumberOfByte)] if len(resp) > 16 else b''

    return Status,Data


  def WriteGencpReg(self, write_device, read_device, Address, WrittenData):
    """Return the numeric GenCP status word, 0 on success, None if no usable
    answer came back. See ReadGencpReg for why it is a number."""
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

    resp = read_device.read(16)

    # Same ack layout as in ReadGencpReg; a write ack carries no payload.
    if len(resp) != 16:
      return None

    return (resp[8] << 8) + resp[9]


if __name__ == "__main__":
  import argparse
  import code
  import sys

  try:
    import readline  # noqa: F401 - enables arrow keys / history in the console
  except ImportError:
    pass

  hex_int = lambda x: int(x, 0)

  parser = argparse.ArgumentParser(
      description='Dione camera control',
      formatter_class=argparse.RawDescriptionHelpFormatter,
  )

  # Connection options -- exactly one per dioneCtrl() constructor parameter, and
  # named the same, so that a command line and an interactive call read alike:
  #     dioneCtrl(bus=7, dev_addr=0x5d, device_type="I2C", gencp_enable=False)
  #     dioneCtrl.py --bus 7 --dev-addr 0x5d --device-type I2C
  # Keep that mapping when adding a parameter on either side.
  #
  # The address option must NOT be called --addr: every subcommand takes a
  # positional 'addr' (a register address), both would land on the same
  # namespace attribute, and the positional -- parsed second -- would win. The
  # register address then reached the I2C_SLAVE ioctl, which rejected it with
  # EINVAL. That was the state of the CLI until this was fixed.
  conn = parser.add_argument_group('connection')
  conn.add_argument('--device-type', choices=['I2C', 'USB'], default='I2C',
                    help='Communication type (default: I2C)')
  conn.add_argument('--bus', type=int, default=6,
                    help='I2C bus number (default: 6)')
  conn.add_argument('--dev-addr', type=hex_int, default=0x5A,
                    help='I2C device address (default: 0x5A)')
  conn.add_argument('--com-device', default='COM0',
                    help='Serial port for USB mode (default: COM0)')
  conn.add_argument('--gencp-enable', action='store_true',
                    help='Use GenCP framing (default: off)')
  conn.add_argument('--force-slave', action='store_true',
                    help='Claim the I2C address even if a kernel driver holds it '
                         '(I2C_SLAVE_FORCE)')

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
    # Every failure path below must exit non-zero: a caller in a shell script
    # has no other way to tell a written register from a refused one. Errors are
    # reported as one line on stderr rather than as a Python traceback -- an
    # unreachable bus or a wrong address is a user mistake, not a crash.
    def fail(msg):
      print(f'Error: {msg}', file=sys.stderr)
      sys.exit(1)

    try:
      with dioneCtrl(
          bus=args.bus,
          dev_addr=args.dev_addr,
          com_device=args.com_device,
          device_type=args.device_type,
          gencp_enable=args.gencp_enable,
          force_slave=args.force_slave,
      ) as cam:

        if args.command == 'upload':
          if cam.upload_file(args.file, args.type):
            print('\nUpload complete. Power cycle the camera to apply the update.')
          else:
            fail('upload failed.')

        elif args.command == 'read_reg32':
          val = cam.read_reg32(args.addr)
          print(f'0x{val:08X}  ({val})')

        elif args.command == 'read_reg32f':
          print(cam.read_reg32f(args.addr))

        elif args.command in ('write_reg32', 'write_reg32f'):
          writer = cam.write_reg32 if args.command == 'write_reg32' else cam.write_reg32f
          status = writer(args.addr, args.val)
          if status:
            fail(f'write to 0x{args.addr:08X} refused, status 0x{status:04X}')
          print('OK')

        elif args.command == 'read_buf':
          data = cam.read_buf(args.addr, args.length)
          print(' '.join(f'{b:02X}' for b in data[2:]))   # skip 2-byte status header

        elif args.command == 'read_string':
          data = cam.read_buf(args.addr, args.length)
          print(data[2:].decode('utf-8', errors='replace').rstrip('\x00'))

    except CameraError as e:
      fail(str(e))
    except FileNotFoundError as e:
      fail(f'{e.filename}: no such device -- check --bus (I2C) or --com-device (USB).')
    except PermissionError as e:
      fail(f'{e.filename}: permission denied -- run as root or join the i2c group.')
    except OSError as e:
      fail(f'{e.strerror or e} -- check --dev-addr, and whether a kernel driver '
           f'already holds the address (--force-slave).')

  else:
    banner = (
        "Xenics Dione camera control console\n"
        "  print(__doc__)    full documentation\n"
        "  help(dioneCtrl)   class and method reference\n"
        "\n"
        "Example: cam = dioneCtrl(dev_addr=0x5b, bus=9, device_type=\"I2C\", gencp_enable=False)\n"
        "\n"
        "CLI commands (run outside this console):\n"
        "  python dioneCtrl.py [connection options] <command>\n"
        "\n"
        "  Connection options carry the same names as the constructor arguments above:\n"
        "  --bus N  --dev-addr 0xNN  --device-type I2C|USB  --com-device COMx\n"
        "  --gencp-enable  --force-slave\n"
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
