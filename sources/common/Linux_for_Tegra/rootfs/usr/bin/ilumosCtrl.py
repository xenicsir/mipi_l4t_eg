#!/usr/bin/env python3
"""ilumosCtrl.py — Userspace register access for iLumos MIPI cameras.

The ilumos kernel driver exposes a chardev at /dev/ilumos-<bus>-<addr>
(e.g. /dev/ilumos-9-0048).  This script uses ioctl on that device to call
ilumos_i2c_read_register, ilumos_i2c_write_register and ilumos_i2c_read_string
from userspace without any I2C_SLAVE_FORCE tricks.

Usage:
    ilumosCtrl.py [DEVICE] COMMAND [ARGS...]

DEVICE (optional):
    Path to the ilumos chardev.
    Default: first /dev/ilumos-* device found automatically.

Commands:
    read_reg32   ADDR              Read a 32-bit register (hex + decimal output)
    read_reg32f  ADDR              Read a 32-bit register (IEEE 754 float output)
    write_reg32  ADDR VAL          Write a 32-bit register (integer value)
    write_reg32f ADDR VAL          Write a 32-bit register (float value)
    read_string  ADDR [LENGTH]     Read a string register (default LENGTH=64)

    ADDR    register address, hex (0x...) or decimal
    VAL     value to write, hex (0x...) or decimal
    LENGTH  number of bytes to read (max 256)

Examples:
    # Auto-detect device, check MIPI enabled
    ilumosCtrl.py read_reg32 0x50FF0010

    # Explicit device path
    ilumosCtrl.py /dev/ilumos-9-0048 read_reg32 0x50FF0000

    # Read firmware version
    ilumosCtrl.py read_reg32 0x50FF0000

    # Read image height as float
    ilumosCtrl.py read_reg32f 0x500E000C

    # Start acquisition
    ilumosCtrl.py write_reg32 0x500F0000 1

    # Read model name string
    ilumosCtrl.py read_string 0x00000044

    # Read serial number
    ilumosCtrl.py read_string 0x00000144
"""

import fcntl
import glob
import os
import struct
import sys

# ---------------------------------------------------------------------------
# IOCTL constants  (must match kernel definitions in ilumos_kmod.c)
#
# Computed via the standard Linux _IOC macro on ARM64:
#   _IOC(dir, type, nr, size) = (dir<<30) | (size<<16) | (type<<8) | nr
#
#   dir:  _IOC_READ=2, _IOC_WRITE=1, _IOC_RW=3
#   type: 'I' = 0x49
#
#   struct ilumos_reg_op { u32 addr; u32 val; }              → sizeof = 8
#   struct ilumos_str_op { u32 addr; u32 len; u8 buf[256]; } → sizeof = 264
#
#   ILUMOS_IOCTL_READ_REG  = _IOWR('I', 1, 8)   = 0xC0084901
#   ILUMOS_IOCTL_WRITE_REG = _IOW ('I', 2, 8)   = 0x40084902
#   ILUMOS_IOCTL_READ_STR  = _IOWR('I', 3, 264) = 0xC1084903
# ---------------------------------------------------------------------------

_IOC_READ  = 2
_IOC_WRITE = 1


def _IOC(direction, type_, nr, size):
    return (direction << 30) | (size << 16) | (ord(type_) << 8) | nr


def _IOWR(type_, nr, size): return _IOC(_IOC_READ | _IOC_WRITE, type_, nr, size)
def _IOW(type_, nr, size):  return _IOC(_IOC_WRITE, type_, nr, size)


ILUMOS_STR_MAX = 256

ILUMOS_IOCTL_READ_REG  = _IOWR('I', 1, 8)
ILUMOS_IOCTL_WRITE_REG = _IOW ('I', 2, 8)
ILUMOS_IOCTL_READ_STR  = _IOWR('I', 3, 4 + 4 + ILUMOS_STR_MAX)

# struct formats (little-endian, matching kernel __u32 / __u8)
_REG_FMT = '<II'                       # addr, val
_STR_FMT = f'<II{ILUMOS_STR_MAX}s'    # addr, len, buf


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _auto_detect():
    devices = sorted(glob.glob('/dev/ilumos-*'))
    if not devices:
        raise FileNotFoundError(
            "No /dev/ilumos-* chardev found.\n"
            "Make sure the ilumos kernel module is loaded and the camera "
            "has been probed successfully (check: dmesg | grep ilumos)."
        )
    return devices[0]


def _ioctl_rw(dev_path, ioctl_code, fmt, *pack_args):
    """Pack args into a bytearray, call ioctl (mutates buf in-place), unpack result."""
    buf = bytearray(struct.pack(fmt, *pack_args))
    with open(dev_path, 'rb+', buffering=0) as f:
        fcntl.ioctl(f.fileno(), ioctl_code, buf)
    return struct.unpack(fmt, buf)


def _ioctl_w(dev_path, ioctl_code, fmt, *pack_args):
    """Pack args into a bytearray and call a write-only ioctl (no result needed)."""
    buf = bytearray(struct.pack(fmt, *pack_args))
    with open(dev_path, 'rb+', buffering=0) as f:
        fcntl.ioctl(f.fileno(), ioctl_code, buf)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_reg32(dev_path, addr):
    """Read a 32-bit register.  Returns the integer value."""
    _, val = _ioctl_rw(dev_path, ILUMOS_IOCTL_READ_REG, _REG_FMT, addr, 0)
    return val


def read_reg32f(dev_path, addr):
    """Read a 32-bit register and interpret as IEEE 754 float."""
    val = read_reg32(dev_path, addr)
    return struct.unpack('<f', struct.pack('<I', val))[0]


def write_reg32(dev_path, addr, val):
    """Write a 32-bit integer value to a register."""
    _ioctl_w(dev_path, ILUMOS_IOCTL_WRITE_REG, _REG_FMT, addr, val & 0xFFFFFFFF)


def write_reg32f(dev_path, addr, fval):
    """Write a float value (IEEE 754) to a register."""
    ival = struct.unpack('<I', struct.pack('<f', float(fval)))[0]
    write_reg32(dev_path, addr, ival)


def read_string(dev_path, addr, length=64):
    """Read a string register.  Returns a decoded ASCII string."""
    length = min(int(length), ILUMOS_STR_MAX)
    _, _, raw = _ioctl_rw(
        dev_path, ILUMOS_IOCTL_READ_STR, _STR_FMT,
        addr, length, b'\x00' * ILUMOS_STR_MAX
    )
    s = raw[:length].rstrip(b'\xff').rstrip(b'\x00')
    return s.decode('ascii', errors='replace')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    # First argument may be an explicit device path
    if args and (args[0].startswith('/dev/') or args[0].startswith('ilumos')):
        dev_path = args[0]
        args = args[1:]
    else:
        try:
            dev_path = _auto_detect()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    cmd_args = args[1:]

    try:
        if cmd == 'read_reg32':
            if len(cmd_args) < 1:
                raise ValueError("read_reg32 requires ADDR")
            addr = int(cmd_args[0], 0)
            val = read_reg32(dev_path, addr)
            print(f"0x{addr:08X} = 0x{val:08X}  ({val})")

        elif cmd == 'read_reg32f':
            if len(cmd_args) < 1:
                raise ValueError("read_reg32f requires ADDR")
            addr = int(cmd_args[0], 0)
            fval = read_reg32f(dev_path, addr)
            print(f"0x{addr:08X} = {fval:.6g}")

        elif cmd == 'write_reg32':
            if len(cmd_args) < 2:
                raise ValueError("write_reg32 requires ADDR VAL")
            addr = int(cmd_args[0], 0)
            val  = int(cmd_args[1], 0)
            write_reg32(dev_path, addr, val)
            print(f"Written 0x{val:08X}  ({val}) to 0x{addr:08X}")

        elif cmd == 'write_reg32f':
            if len(cmd_args) < 2:
                raise ValueError("write_reg32f requires ADDR VAL")
            addr = int(cmd_args[0], 0)
            fval = float(cmd_args[1])
            write_reg32f(dev_path, addr, fval)
            print(f"Written {fval:.6g} to 0x{addr:08X}")

        elif cmd == 'read_string':
            if len(cmd_args) < 1:
                raise ValueError("read_string requires ADDR")
            addr   = int(cmd_args[0], 0)
            length = int(cmd_args[1], 0) if len(cmd_args) > 1 else 64
            s = read_string(dev_path, addr, length)
            print(f"0x{addr:08X} = '{s}'")

        else:
            print(f"Unknown command: {cmd!r}", file=sys.stderr)
            print(__doc__)
            sys.exit(1)

    except OSError as e:
        print(f"Error communicating with {dev_path}: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
