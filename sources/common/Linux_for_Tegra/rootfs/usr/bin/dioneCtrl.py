#!/usr/bin/python3
"""
dioneCtrl.py - Xenics Dione Camera Control Module
==================================================

Overview
--------
Python module for controlling Xenics Dione thermal cameras via I2C (Linux)
or USB/Serial (Windows).

Two wire protocols are implemented. The plain register protocol (4-byte
address, 2-byte length, both little endian) is what the Dione speaks on
I2C -- it is the default, and it is all that is needed, upload included.
GenCP framing is available on the USB/Serial path, where the CX3
converter acts as a GenCP server; the Dione itself does not serve GenCP
over I2C, so gencp_enable is for the serial path only.

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
    gencp_enable : bool  (default: False)  - Use GenCP framing. USB/Serial only: the
                                             Dione does not serve GenCP over I2C.
    force_slave  : bool  (default: False)  - Use I2C_SLAVE_FORCE (0x0706) instead of
                                             I2C_SLAVE (0x0703). Required when a kernel
                                             driver (e.g. dione_ir) already holds the
                                             I2C address; otherwise ioctl returns EBUSY.
                                             Prefer unbinding the driver for an upload:
                                             the camera handles one request at a time,
                                             and the driver would be polling in parallel.

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

Command line
------------
Running the script with no command opens an interactive console. With a
command, it runs it and exits:

    python dioneCtrl.py [connection options] <command> [connection options]

    upload       <file> firmware|application|correction
    download     <file> firmware|application|correction
    read_reg32   <addr>              Read 32-bit integer
    read_reg32f  <addr>              Read 32-bit float
    write_reg32  <addr> <val>        Write 32-bit integer
    write_reg32f <addr> <val>        Write 32-bit float
    read_buf     <addr> <length>     Read byte buffer (hex + ASCII)
    read_string  <addr> <length>     Read byte buffer as text

    Connection options carry the same names as the constructor parameters
    above, and may be given before or after the command:

        --bus N            (default: 6)
        --dev-addr 0xNN    (default: 0x5A)   -- not --addr, see below
        --device-type I2C|USB               --com-device COMx
        --gencp-enable                      --force-slave

    upload file type choices:
        firmware      Upload as FAC_SEL.FIRMWARE    (selector = 1)
        application   Upload as FAC_SEL.APPLICATION (selector = 2)
        correction    Upload shutterless .xca (converted automatically) or prepared Dione binary (selector = 3)

    Use download for backup/readback when supported by the device. Some Dione
    firmware reports zero-length Correction on export; that is not a backup. Close Xeneth; the COM port is held exclusively during transfer.

    Upload works over plain I2C; do not pass --gencp-enable for it.

        python dioneCtrl.py upload app.bin application \\
                            --device-type I2C --bus 9 --dev-addr 0x5a

    The camera address option is --dev-addr, never --addr: every register
    subcommand takes a positional 'addr', both would land on the same
    namespace attribute, and the register address would reach the
    I2C_SLAVE ioctl. Passing --addr reports this instead of failing.

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

    # Cap the frame period at 33333 us -> at most 30 fps
    cam.write_reg32(0x00080118, 33333)

    # Set the exposure time to 60 us
    cam.write_reg32f(0x0002F00C, 60.0)

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
    0x00080118   int     AcquisitionFrameTime (us) -- an upper bound on the
                         frame period, not the exposure. 0 = free-running.
    0x0002F00C   float   ExposureTime (us) -- this is the integration time
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
    cam.write_reg32(0x00080118, 33333)    # Cap the frame period (30 fps)
    cam.write_reg32f(0x0002F004, 1.8)     # Set GSK

Platform Notes
--------------
- Linux: Requires access to /dev/i2c-* devices. Run with appropriate
  permissions or add user to i2c group.
- Windows: Requires COM port access. Install appropriate USB-Serial drivers.
- I2C Address: one per model -- Dione 320 = 0x5c, 640 = 0x5a, 1024 = 0x5d,
  1280 = 0x5b (user manual ENG-2021-UMN008-R013). The default here is 0x5a.
- I2C Bus: Depends on the camera port on Jetson/RPi (check with i2cdetect).
  If the dione_ir driver is loaded, the bus and address are both in the name
  of the node it creates: /dev/dioneir-i2c-<bus>-000e-<address>.
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
import zipfile
from contextlib import contextmanager
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


def convert_dione_xca(blob, version=1):
    """Return (Dione binary, metadata) for a shutterless XCA, version 1 or 3.

    Reference: F128/interface_ext.lua, xc_lua_snuc_data.cpp,
    xc_snuc_from_scene.cpp, xc_replace_pixels.cpp, xc_dione_calibration_data.cpp.
    Firmware/application packages never pass through this conversion.
    """
    import io
    import math
    import struct
    import zipfile
    import xml.etree.ElementTree as ET
    import numpy as np
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError('XCA conversion requires Pillow (pip install Pillow)') from error
    if version not in (1, 3):
        raise ValueError('Shutterless Dione correction version must be 1 or 3')

    def sequential_sum(values):
        flat = np.asarray(values, dtype=np.float64).ravel()
        return float(np.cumsum(flat, dtype=np.float64)[-1]) if flat.size else 0.0

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if archive.read('nuctype.csv').strip() != b'3':
            raise ValueError('Only shutterless XCA (nuctype 3) is supported')
        def mask(name):
            with Image.open(io.BytesIO(archive.read(name))) as image:
                if image.mode not in ('1', 'L', 'P', 'RGB', 'RGBA'):
                    raise ValueError('Unsupported rejection mask format: ' + image.mode)
                return np.any(np.asarray(image.convert('RGB')) != 255, axis=2)
        bad = mask('rej1_unsaturated.png')
        noise = mask('rej2_noisy.png')
        height, width = bad.shape
        if bad.shape != noise.shape:
            raise ValueError('XCA rejection mask dimensions differ')
        models = {(320, 240): 0x100, (640, 480): 1,
                  (1024, 768): 0x1000, (1280, 1024): 0x10}
        if (width, height) not in models:
            raise ValueError('Unsupported Dione geometry: %dx%d' % (width, height))
        bad |= noise
        count = width * height
        def image_data(name):
            raw = archive.read(name)
            if len(raw) != count * 8:
                raise ValueError('Incorrect float64 image size: ' + name)
            image = np.frombuffer(raw, dtype='<f8').copy().reshape(height, width)
            if not np.isfinite(image).all():
                raise ValueError('Non-finite XCA image values: ' + name)
            return image
        cold = image_data('rej2_average.bin')
        gain = image_data('rej3_gainfactors.bin')
        ambient = image_data('rej4_ambient_d.bin')
        startup = image_data('rej5_startup.bin') if 'rej5_startup.bin' in archive.namelist() else None
        # BIN_START_UP has varied in old Xeneth releases: only the exact reference
        # member is used; absent startup data falls back to C in version 3.
        if 'rej_startup.bin' in archive.namelist():
            raise ValueError('Unrecognised startup-image name; verify the XCA format')
        grey = archive.read('rej3_greylevel.bin')
        if len(grey) != 20:
            raise ValueError('XCA grey-level data must contain five uint32 values')
        nominal_gain = struct.unpack('<5I', grey)[0]
        if nominal_gain <= 0:
            raise ValueError('Invalid nominal gain level')
        settings_xml = archive.read('camerapack.xcf')
        # Xeneth XCF files can declare XML version="2.0.0.0". ElementTree rejects
        # that declaration; its body is ordinary UTF-8 XML.
        if settings_xml.startswith(b'<?xml'):
            settings_xml = settings_xml[settings_xml.index(b'?>')+2:]
        settings_root = ET.fromstring(settings_xml)
        if settings_root.attrib.get('productid') != 'F128':
            raise ValueError('XCA camera settings are not for Dione F128')
        settings = {}
        for node in settings_root:
            name = node.attrib.get('brief')
            if name in ('ExposureTime', 'DeviceGain', 'DeviceGSKVoltage', 'DeviceGFIDVoltage'):
                if name in settings:
                    raise ValueError('Duplicate calibration setting: ' + name)
                value = float(node.attrib['value'])
                if not math.isfinite(value):
                    raise ValueError('Non-finite calibration setting: ' + name)
                settings[name] = value

    # XSNucFromSceneModel::CorrectDataImages uses Vertical replacement on rounded
    # uint16 frames, then changes only the bad elements of the float64 image.
    bad_y, bad_x = np.nonzero(bad)
    for image in (cold, gain, ambient, startup):
        if image is None:
            continue
        rounded = np.floor(np.clip(image, 0, 65535)+.5).astype(np.uint16)
        for y, x in zip(bad_y, bad_x):
            rounded[y, x] = rounded[y-1, x] if y else rounded[0, x-1 if x else 1]
        image[bad] = rounded[bad]

    def column_average(image):
        result = np.zeros(width, dtype=np.float64)
        for row in image:
            result += row / height
        return result

    cold_columns = column_average(cold)
    cold_dispersion = cold - cold_columns
    kernel = (.045635881557, -.028771763114, -.295635881557,
              .557543526229, -.295635881557, -.028771763114, .045635881557)
    def high_pass(row):
        result = np.zeros(width, dtype=np.float64)
        for j, coefficient in enumerate(kernel):
            indices = np.arange(width) + j - 3
            indices = np.where(indices < 0, -indices, indices)
            indices = np.where(indices >= width, 2*(width-1)-indices, indices)
            result += row[indices] * coefficient
        return result
    cold_hp = high_pass(cold_columns)
    ambient_hp = high_pass(column_average(ambient))
    denominator = sequential_sum(cold_hp*cold_hp)
    if denominator <= 0:
        raise ValueError('Degenerate cold-image column data')
    alpha = sequential_sum(ambient_hp*cold_hp) / denominator
    residual = ambient - alpha*cold_columns
    def gradients(image):
        dx, dy = np.empty_like(image), np.empty_like(image)
        dx[:, 0], dx[:, -1] = image[:, 1]-image[:, 0], image[:, -1]-image[:, -2]
        dx[:, 1:-1] = .5*(image[:, 2:]-image[:, :-2])
        dy[0], dy[-1] = image[1]-image[0], image[-1]-image[-2]
        dy[1:-1] = .5*(image[2:]-image[:-2])
        return dx, dy
    rx, ry = gradients(residual)
    cx, cy = gradients(cold_dispersion)
    denominator = sequential_sum(cx*cx+cy*cy)
    if denominator <= 0:
        raise ValueError('Degenerate cold-image spatial data')
    beta = sequential_sum(rx*cx+ry*cy) / denominator
    if not math.isfinite(alpha) or not math.isfinite(beta):
        raise ValueError('Invalid SNUC coefficients')

    def is_bad(x, y):
        return not (0 <= x < width and 0 <= y < height) or bool(bad[y, x])
    bad_records = bytearray()
    neighbours = ((0, -1, 1), (0, 1, 6), (-1, -1, 0), (1, -1, 2),
                  (-1, 0, 3), (1, 0, 4), (-1, 1, 5), (1, 1, 7))
    for y, x in zip(bad_y, bad_x):
        flag = 0 if x == 0 and y == 0 else (1 << 3 if y == 0 else 1 << 1)
        for dx, dy, bit in neighbours:
            if not is_bad(x+dx, y+dy):
                flag = 1 << bit
                break
        bad_records.extend(struct.pack('<HHH', int(x), int(y), flag | 0x100))
    bad_capacity = 65536 if width <= 640 else 262144
    if len(bad_records) > bad_capacity:
        raise ValueError('Bad-pixel list exceeds Dione storage capacity')
    bad_records.extend(b'\xff'*(bad_capacity-len(bad_records)))

    mapping = {'ExposureTime': 0x2f00c, 'DeviceGain': 0x2f000,
               'DeviceGSKVoltage': 0x2f004, 'DeviceGFIDVoltage': 0x2f008}
    settings_blob = bytearray()
    for name in sorted(settings, key=lambda n: mapping[n]):
        value = settings[name]
        if name == 'DeviceGain':
            if value != int(value) or not 0 <= int(value) <= 5:
                raise ValueError('Unsupported Dione gain enumeration index')
            raw = struct.pack('<I', (5, 4, 3, 2, 1, 0)[int(value)])
        else:
            raw = struct.pack('<f', value)
        settings_blob.extend(struct.pack('<I', mapping[name])+raw)
    settings_blob.extend(b'\xff'*(4096-len(settings_blob)))

    def binary_image(image):
        raw = np.floor(np.clip(image.ravel(), 0, 65535)+.5).astype('<u2').tobytes()
        return raw + b'\xff'*((-len(raw)) % 4096)
    nominal_c = sequential_sum(cold.ravel()/count)
    nominal_s = sequential_sum((cold if startup is None else startup).ravel()/count)
    type_code = models[width, height] * (3 if version == 3 else 1)
    misc = struct.pack('<IIffff', 0xfeedbeef, type_code, alpha, beta, nominal_c, nominal_gain)
    if version == 3:
        misc += struct.pack('<f', nominal_s)
    misc += b'\xff'*(4096-len(misc))
    result = binary_image(cold)+binary_image(gain)+binary_image(ambient)+bytes(bad_records)+misc+bytes(settings_blob)
    if version == 3:
        # Match ToBinaryImage<uint32_t>(..., 10), including its retained final
        # lane when the sample count is not divisible by three.
        image = cold if startup is None else startup
        values = np.floor(np.clip(image.ravel(), 0, 65535)+.5).astype(np.uint32)
        target = ((count+1023)//1024)*1024
        padded = np.empty(((target+2)//3)*3, dtype=np.uint32)
        padded[:count] = values
        for i in range(count, len(padded)):
            padded[i] = padded[i-3]
        lanes = padded.reshape(-1, 3)
        packed = ((lanes[:, 0] >> 6) & 0x3ff) | ((lanes[:, 1] << 4) & 0xffc00) | ((lanes[:, 2] << 14) & 0x3ff00000)
        result += packed.astype('<u4').tobytes()
    return result, dict(width=width, height=height, version=version, type_code=type_code,
                        bad_pixels=len(bad_y), alpha=alpha, beta=beta, nominal_c=nominal_c,
                        nominal_gain=nominal_gain, settings=settings,
                        productid=settings_root.attrib.get('productid'), bytes=len(result))


class dioneCtrl(object):

  # Maximum I2C status read attempts when the camera returns 0xFFFF (request in progress)
  POLL_ATTEMPTS = 10
  POLL_INTERVAL = 0.05   # seconds between retry attempts

  UPLOAD_BLOCKSIZE = 4096
  UPLOAD_PACKSIZE  = 1000
  FILE_TRANSFER_GAP = 0.02  # one completed request at a time, including on USB
  FILE_POLL_INTERVAL = 0.05
  FILE_OPERATION_TIMEOUT = 10.0

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
      if getattr(self, '_transfer_depth', 0) and getattr(self, 'ser', None) is not None and self.ser.is_open:
        return
      self.ser = serial.Serial(self.com_device, timeout=1, write_timeout=1)

  def close_device(self):
    if (self.device_type == "USB") :
      if not getattr(self, '_transfer_depth', 0):
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
      if getattr(self, '_transfer_depth', 0):
        time.sleep(self.FILE_TRANSFER_GAP)

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
      if getattr(self, '_transfer_depth', 0):
        time.sleep(self.FILE_TRANSFER_GAP)
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
  # File access (ENG-2021-ICD001-R004, p12; Dione manual R005, p45)
  # -------------------------------------------------------------------------

  @contextmanager
  def _file_session(self):
    """Keep exclusive ownership of the COM port for the entire file transfer."""
    outer = not getattr(self, '_transfer_depth', 0)
    if outer:
      self.open_device()
    self._transfer_depth = getattr(self, '_transfer_depth', 0) + 1
    try:
      yield
    finally:
      self._transfer_depth -= 1
      if outer:
        self.close_device()

  def _fac_write_checked(self, address, value):
    self._check_status(self.write_reg32(address, value), f'file register 0x{address:08X}')

  def _fac_execute_operation(self, file_op):
    self._fac_write_checked(0x10010008, file_op)
    # FileOperationExecute can report BUSY while starting the asynchronous op.
    # Do not resend it: only poll FileOperationStatus to determine completion.
    status = self.write_reg32(0x1001000C, 1)
    if status not in (0, GencpStatus['GENCP_BUSY']):
      self._check_status(status, 'FileOperationExecute')
    # Same 10 s deadline as before; poll completion instead of a fixed 500 ms wait.
    deadline = time.monotonic() + self.FILE_OPERATION_TIMEOUT
    while time.monotonic() < deadline:
      time.sleep(self.FILE_POLL_INTERVAL)
      status = self.read_reg32(0x10010010)
      if status == 0:
        return True
      if status != 2:
        raise CameraError(f'File operation {file_op} failed: status 0x{status:08X}')
    raise CameraError(f'File operation {file_op} timed out')

  @staticmethod
  def _fac_selector(selector):
    value = FAC_SEL[selector.upper()] if isinstance(selector, str) else FAC_SEL(selector)
    if value not in (FAC_SEL.FIRMWARE, FAC_SEL.APPLICATION, FAC_SEL.CORRECTION):
      raise ValueError('Recovery image transfers are not supported')
    return value

  def _fac_write_chunk(self, chunk_data, chunk_offset):
    self._fac_write_checked(0x1001001C, chunk_offset)
    self._fac_write_checked(0x10010020, len(chunk_data))
    for offset in range(0, len(chunk_data), self.UPLOAD_PACKSIZE):
      part = chunk_data[offset:offset+self.UPLOAD_PACKSIZE]
      # The CX3 treats every <=4-byte GenCP transfer as a scalar and swaps it.
      wire = part[::-1] if self.gencp_enable and len(part) <= 4 else part
      self._check_status(self.write_buf(0x10011000+offset, wire), 'file buffer write')
    self._fac_execute_operation(3)
    count = self.read_reg32(0x10010014)
    if count != len(chunk_data):
      raise CameraError(f'Short file write at {chunk_offset}: {count}/{len(chunk_data)}')
    return True

  def _fac_read_chunk(self, chunk_offset, length):
    self._fac_write_checked(0x1001001C, chunk_offset)
    self._fac_write_checked(0x10010020, length)
    self._fac_execute_operation(2)
    count = self.read_reg32(0x10010014)
    if count != length:
      raise CameraError(f'Short file read at {chunk_offset}: {count}/{length}')
    data = bytearray()
    for offset in range(0, length, self.UPLOAD_PACKSIZE):
      size = min(self.UPLOAD_PACKSIZE, length-offset)
      part = self.read_buf(0x10011000+offset, size)[2:]
      data.extend(part[::-1] if self.gencp_enable and size <= 4 else part)
    return bytes(data)

  def download_file(self, filepath, selector='correction'):
    """Save the selected device file without overwriting an existing host file.

    A failed download leaves a .partial file, never a completed-looking backup.
    """
    selector = self._fac_selector(selector)
    filepath = os.fspath(filepath)
    partial = filepath + '.partial'
    if os.path.exists(filepath) or os.path.exists(partial):
      raise FileExistsError(filepath)
    with self._file_session():
      self._fac_write_checked(0x10010000, int(selector))
      self._fac_write_checked(0x10010004, 0)
      self._fac_execute_operation(0)
      size = self.read_reg32(0x10010018)
      if size == 0 and selector == FAC_SEL.CORRECTION:
        self._fac_execute_operation(1)
        raise CameraError('Correction export returned no data; readback may be unsupported. No calibration backup created.')
      if not 0 <= size <= 32*1024*1024:
        raise CameraError(f'Unexpected file size {size}')
      print(f'Downloading {selector}: {size} bytes', flush=True)
      with open(partial, 'xb') as target:
        for offset in range(0, size, self.UPLOAD_BLOCKSIZE):
          data = self._fac_read_chunk(offset, min(self.UPLOAD_BLOCKSIZE, size-offset))
          target.write(data)
          target.flush()
          print(f'\rReceived {offset+len(data)}/{size}', end='', flush=True)
      self._fac_execute_operation(1)
      os.rename(partial, filepath)
    print()
    return True

  def upload_file(self, filepath, selector):
    """Upload firmware, application, shutterless XCA or prepared Dione binary.

    XCA conversion follows Xeneth F128; the source file is never changed.
    Pillow is required only for XCA rejection masks. Correction version and
    sensor geometry are read before any camera setting or file is written.

    This overwrites the selected device file. Use download_file() for backup
    and comparison where supported; a zero-length Correction export cannot
    verify the stored calibration. Successful upload means accepted file writes,
    not a readback or an optical calibration qualification.
    Any failed request stops the transfer; no blind retry or forced CLOSE.
    """
    try:
      selector = self._fac_selector(selector)
    except (KeyError, ValueError) as error:
      print(f'Invalid selector: {error}')
      return False
    if not os.path.isfile(filepath):
      print(f'File not found: {filepath}')
      return False
    with open(filepath, 'rb') as source:
      blob = source.read()
    if not blob:
      print('Refusing an empty upload')
      return False
    xca_source = None
    if selector == FAC_SEL.CORRECTION and (zipfile.is_zipfile(io.BytesIO(blob)) or os.fspath(filepath).lower().endswith('.xca')):
      xca_source = blob
      try:
        # Validate the archive before taking the port or writing any setting.
        blob, calibration = convert_dione_xca(xca_source, version=1)
      except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        print(f'Invalid or unsupported XCA: {error}')
        return False
    print(f'Uploading {filepath} ({len(blob)} bytes) as {selector}', flush=True)
    try:
      with self._file_session():
        if xca_source is not None:
          version = self.read_reg32(0x10000018)  # ImageCorrectionVersion
          if version not in (1, 3):
            raise CameraError(f'Unsupported shutterless correction version {version}')
          width = self.read_reg32(0x2F028)  # SensorWidth, independent of ROI
          height = self.read_reg32(0x2F02C)  # SensorHeight
          if (width, height) != (calibration['width'], calibration['height']):
            raise CameraError(f'XCA geometry {calibration["width"]}x{calibration["height"]} differs from sensor {width}x{height}')
          if version != 1:
            blob, calibration = convert_dione_xca(xca_source, version)
          print(f'Converted XCA to Dione v{version}: {len(blob)} bytes, {calibration["bad_pixels"]} bad pixels', flush=True)
        was_running = selector == FAC_SEL.CORRECTION and bool(self.read_reg32(0x8010C) & 1)
        self._fac_write_checked(0x80104, 0x202)  # existing acquisition-stop sequence
        time.sleep(1)
        self._fac_write_checked(0x10010000, int(selector))
        self._fac_write_checked(0x10010004, 1)
        if not self._fac_execute_operation(0):
          return False
        for offset in range(0, len(blob), self.UPLOAD_BLOCKSIZE):
          data = blob[offset:offset+self.UPLOAD_BLOCKSIZE]
          if not self._fac_write_chunk(data, offset):
            return False
          print(f'\rSent {offset+len(data)}/{len(blob)}', end='', flush=True)
        if selector == FAC_SEL.CORRECTION:
          # Observed in the successful Xeneth 2.8 Dione upload: final size is
          # written before CLOSE, although the supplied camera XML labels it RO.
          self._fac_write_checked(0x10010018, len(blob))
        if not self._fac_execute_operation(1):
          return False
        if was_running:
          self._fac_write_checked(0x80104, 0x101)  # restore acquisition after Correction
    except CameraError as error:
      print(f'Upload failed: {error}')
      return False
    print()
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


  @staticmethod
  def _gencp_checksum(data):
    if len(data) % 2:
      data += b'\0'
    total = sum(struct.unpack('>%dH' % (len(data)//2), data))
    while total > 0xffff:
      total = (total & 0xffff) + (total >> 16)
    return 0xffff if total == 0xffff else (~total & 0xffff)

  def _gencp_ack(self, device, request_id, command, expected_length):
    header = bytes(device.read(16))
    if len(header) != 16:
      raise CameraError('GenCP header missing or incomplete; transfer stopped')
    length = int.from_bytes(header[12:14], 'big')
    status = int.from_bytes(header[8:10], 'big')
    if header[:2] != b'\x01\0' or header[6:8] != b'\0\0' or int.from_bytes(header[10:12], 'big') != command or int.from_bytes(header[14:16], 'big') != request_id:
      raise CameraError('GenCP ACK preamble/channel/command/request ID mismatch')
    if length != (expected_length if status == 0 else 0):
      raise CameraError('GenCP ACK length mismatch')
    raw = header + (bytes(device.read(length)) if length else b'')
    if len(raw) != 16+length or int.from_bytes(header[2:4], 'big') != self._gencp_checksum(raw[6:16]) or int.from_bytes(header[4:6], 'big') != self._gencp_checksum(raw[6:]):
      raise CameraError('GenCP ACK checksum or payload mismatch')
    return status, raw[16:]

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

    if write_device.write(bytes(ByteArray)) != len(ByteArray):
      raise CameraError('Incomplete GenCP request write')
    request_id = self.RequestId
    self.RequestId = (self.RequestId + 1) & 0xffff
    return self._gencp_ack(read_device, request_id, 0x0801, NumberOfByte)


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

    if write_device.write(bytes(ByteArray)) != len(ByteArray):
      raise CameraError('Incomplete GenCP request write')
    request_id = self.RequestId
    self.RequestId = (self.RequestId + 1) & 0xffff
    status, _ = self._gencp_ack(read_device, request_id, 0x0803, 0)
    return status



def hexdump(data, base_addr=0, width=16):
  """Render <data> as address / hex / ASCII lines, hexdump -C style.

  Most of what read_buf() returns is text -- firmware version strings, model
  names, serial numbers -- padded with 0x00 or 0xFF. A bare run of hex bytes
  hides that; the ASCII column makes it readable without decoding by hand.

  base_addr is the register address of data[0], so the left column names where
  each byte actually lives instead of numbering an offset into the answer."""
  lines = []
  for off in range(0, len(data), width):
    chunk = data[off:off + width]
    cells = [f'{b:02X}' for b in chunk] + ['  '] * (width - len(chunk))
    # Gap in the middle of the row, and padded cells on a short last row, so
    # the ASCII column stays aligned whatever the length read.
    hexa = ' '.join(cells[:width // 2]) + '  ' + ' '.join(cells[width // 2:])
    text = ''.join(chr(b) if 0x20 <= b < 0x7F else '.' for b in chunk)
    lines.append(f'{base_addr + off:08X}  {hexa}  |{text}|')
  return '\n'.join(lines)


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
  #
  # These options are added twice: on the main parser with their real defaults,
  # and again on every subcommand with default=argparse.SUPPRESS, so that both
  # orders work --
  #     dioneCtrl.py --bus 9 --dev-addr 0x5a upload pkg.bin application
  #     dioneCtrl.py upload pkg.bin application --bus 9 --dev-addr 0x5a
  # The second is the order people actually type (the command first, then how to
  # reach the camera), and with the options declared only on the main parser
  # argparse hands everything after the subcommand name to the subparser, which
  # knows nothing about them: they come back as "unrecognized arguments".
  #
  # SUPPRESS on the subcommand copies is what makes the duplication safe. A
  # subparser parses into a namespace of its own and then copies every attribute
  # that namespace holds onto the main one (CPython's
  # _SubParsersAction.__call__), so a real default there would silently
  # overwrite an option given *before* the subcommand with that default --
  # `--bus 9 upload ...` would go back to bus 6. SUPPRESS leaves the attribute
  # unset unless the user typed it, so the main parser's value survives.
  def add_conn_options(p, suppress=False):
    default = (lambda v: argparse.SUPPRESS) if suppress else (lambda v: v)
    conn = p.add_argument_group('connection')
    conn.add_argument('--device-type', choices=['I2C', 'USB'], default=default('I2C'),
                      help='Communication type (default: I2C)')
    conn.add_argument('--bus', type=int, default=default(6),
                      help='I2C bus number (default: 6)')
    conn.add_argument('--dev-addr', type=hex_int, default=default(0x5A),
                      help='I2C device address (default: 0x5A)')
    conn.add_argument('--com-device', default=default('COM0'),
                      help='Serial port for USB mode (default: COM0)')
    conn.add_argument('--gencp-enable', action='store_true', default=default(False),
                      help='Use GenCP framing (default: off). The Dione does not '
                           'serve GenCP over I2C -- leave this off in I2C mode.')
    conn.add_argument('--force-slave', action='store_true', default=default(False),
                      help='Claim the I2C address even if a kernel driver holds it '
                           '(I2C_SLAVE_FORCE)')

  add_conn_options(parser)

  subparsers = parser.add_subparsers(dest='command')

  p = subparsers.add_parser('download', help='Download a device file (for backup/readback)')
  p.add_argument('file', help='New output file path')
  p.add_argument('type', choices=['firmware', 'application', 'correction'])

  # upload
  p = subparsers.add_parser('upload', help='Upload firmware, application or calibration')
  p.add_argument('file', help='Path to firmware/application package, shutterless .xca or prepared Dione calibration binary')
  p.add_argument('type', choices=['firmware', 'application', 'correction'],
                 help='"firmware" (FAC_SEL=1) or "application" (FAC_SEL=2), "correction" (FAC_SEL=3)')

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
  p = subparsers.add_parser('read_buf', help='Read a byte buffer (hex + ASCII)')
  p.add_argument('addr',   type=hex_int, help='Register address')
  p.add_argument('length', type=int,     help='Number of bytes to read')

  # read_string
  p = subparsers.add_parser('read_string', help='Read a byte buffer and print as string')
  p.add_argument('addr',   type=hex_int, help='Register address')
  p.add_argument('length', type=int,     help='Number of bytes to read')

  # Applied to every subcommand in one loop rather than at each add_parser()
  # call, so a subcommand added later cannot be forgotten -- the failure mode is
  # a confusing "unrecognized arguments" on that one command only.
  for sub in subparsers.choices.values():
    add_conn_options(sub, suppress=True)

  # --addr was renamed --dev-addr to break the collision described above, but it
  # is the name still in shell histories and in older notes. argparse would only
  # say "unrecognized arguments", which does not point at the new name.
  for arg in sys.argv[1:]:
    if arg == '--addr' or arg.startswith('--addr='):
      parser.error("--addr no longer exists: use --dev-addr for the camera's I2C "
                   "address. It was renamed because it collided with the 'addr' "
                   "register argument taken by every subcommand.")

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

        if args.command == 'download':
          if cam.download_file(args.file, args.type):
            print('Download complete.')
          else:
            fail('download failed.')

        elif args.command == 'upload':
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
          print(hexdump(data[2:], args.addr))            # skip 2-byte status header

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
      # pyserial raises SerialException, a subclass of OSError, so a missing
      # port used to be answered with I2C advice about --dev-addr.
      if args.device_type == 'USB':
        fail(f'{e.strerror or e} -- check --com-device.')
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
        "  python dioneCtrl.py [connection options] <command> [connection options]\n"
        "\n"
        "  Connection options carry the same names as the constructor arguments above,\n"
        "  and may be given before or after the command:\n"
        "  --bus N  --dev-addr 0xNN  --device-type I2C|USB  --com-device COMx\n"
        "  --gencp-enable  --force-slave\n"
        "\n"
        "  In I2C mode the Dione speaks the plain register protocol, not GenCP:\n"
        "  leave --gencp-enable off. Upload works over plain I2C.\n"
        "\n"
        "  read_reg32   <addr>              Read 32-bit integer\n"
        "  read_reg32f  <addr>              Read 32-bit float\n"
        "  write_reg32  <addr> <val>        Write 32-bit integer\n"
        "  write_reg32f <addr> <val>        Write 32-bit float\n"
        "  read_buf     <addr> <length>     Read byte buffer (hex output)\n"
        "  read_string  <addr> <length>     Read byte buffer (string output)\n"
        "  upload       <file> firmware|application|correction\n"
    )
    code.interact(banner=banner, local=dict(globals(), **locals()))
