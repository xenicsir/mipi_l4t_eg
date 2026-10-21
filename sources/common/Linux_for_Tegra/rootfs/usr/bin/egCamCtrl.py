#!/usr/bin/env python3
"""Standalone ioctl client for iLumos, MicroLynx and Titan camera drivers.

The kernel driver owns the camera's wire protocol. Userspace sends the same
register/string structures to all three drivers, with a different ioctl magic.
Device selection is always explicit; camera type only selects that ioctl ABI.
"""

import argparse
import errno
import fcntl
from functools import partial
import operator
import os
import re
import struct
import sys


STR_MAX = 256
_REG_FMT = '<II'
_STR_FMT = '<II256s'
# family: (display name, ioctl magic, actual maximum string read)
# Each driver exposes the same 256-byte string ioctl buffer.
PROFILES = {
    'ilumos': ('iLumos', 'I', STR_MAX),
    'microlynx': ('MicroLynx', 'M', STR_MAX),
    'titan': ('Titan', 'T', STR_MAX),
}
_DEVICE_NAME = re.compile(r'^(ilumos|microlynx|titan)-[0-9]+-[0-9a-fA-F]{4}$')
_EXCLUDED_PREFIXES = ('dione', 'eg_ec', 'eg-ec', 'microcube', 'crius', 'smartir')


def _uint32(value):
    value = operator.index(value)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError('register addresses and integer values must fit in 32 unsigned bits')
    return value


def _parse_uint32(value):
    try:
        return _uint32(int(value, 0))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc))


def _parse_length(value):
    try:
        length = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected a decimal or hexadecimal length') from exc
    if not 1 <= length <= STR_MAX:
        raise argparse.ArgumentTypeError('string length must be between 1 and 256')
    return length


class Camera:
    """A specific camera chardev; creating this object does not open the device."""

    def __init__(self, device, camera_type=None):
        self.device = os.fsdecode(device)
        if not self.device:
            raise ValueError('an explicit camera device is required')
        # Follow an explicit symlink, but never scan /dev or choose a camera.
        families = set()
        for path in (self.device, os.path.realpath(self.device)):
            name = os.path.basename(path)
            if name.lower().startswith(_EXCLUDED_PREFIXES):
                raise ValueError('Dione and eg_ec_mipi cameras are not supported by this tool')
            match = _DEVICE_NAME.fullmatch(name)
            if match:
                families.add(match.group(1))
        if len(families) > 1:
            raise ValueError('device name and symlink target identify different camera types')
        if camera_type is not None:
            camera_type = camera_type.lower()
            if camera_type not in PROFILES:
                raise ValueError('supported camera types: ilumos, microlynx, titan')
            if families and camera_type not in families:
                raise ValueError('camera type does not match the specified device')
        elif families:
            camera_type = families.pop()
        else:
            raise ValueError('cannot determine camera type from device name; use --camera')
        self.camera_type = camera_type
        self.name, magic, self.string_limit = PROFILES[camera_type]
        self.ioctl_read_reg = self._ioc(3, magic, 1, struct.calcsize(_REG_FMT))
        self.ioctl_write_reg = self._ioc(1, magic, 2, struct.calcsize(_REG_FMT))
        self.ioctl_read_str = self._ioc(3, magic, 3, struct.calcsize(_STR_FMT))

    @staticmethod
    def _ioc(direction, magic, number, size):
        return (direction << 30) | (size << 16) | (ord(magic) << 8) | number

    def _transfer(self, request, fmt, *values):
        buf = bytearray(struct.pack(fmt, *values))
        with open(self.device, 'rb+', buffering=0) as device:
            result = fcntl.ioctl(device.fileno(), request, buf)
        # MicroLynx's driver can return a positive GenCP error status. Python's
        # ioctl only raises for negative errno, so check this explicitly too.
        if result != 0:
            raise OSError(errno.EIO, 'camera ioctl returned status 0x{:04X}'.format(result))
        return struct.unpack(fmt, buf)

    def read_reg32(self, addr):
        """Read a register as an unsigned 32-bit integer."""
        return self._transfer(self.ioctl_read_reg, _REG_FMT, _uint32(addr), 0)[1]

    def write_reg32(self, addr, value):
        """Write an unsigned 32-bit integer."""
        self._transfer(self.ioctl_write_reg, _REG_FMT, _uint32(addr), _uint32(value))

    def read_reg32f(self, addr):
        """Interpret the register's bits as an IEEE 754 binary32 value."""
        return struct.unpack('<f', struct.pack('<I', self.read_reg32(addr)))[0]

    def write_reg32f(self, addr, value):
        """Write IEEE 754 binary32 bits, without a numeric float-to-int cast."""
        bits = struct.unpack('<I', struct.pack('<f', float(value)))[0]
        self.write_reg32(addr, bits)

    def read_string(self, addr, length=64):
        """Read ASCII, stripping trailing NUL/0xff padding."""
        length = operator.index(length)
        if not 1 <= length <= self.string_limit:
            raise ValueError('{} string length must be between 1 and {}'.format(
                self.name, self.string_limit))
        _, _, raw = self._transfer(self.ioctl_read_str, _STR_FMT,
                                  _uint32(addr), length, b'\0' * STR_MAX)
        return raw[:length].rstrip(b'\xff\0').decode('ascii', errors='replace')


# Preserve the existing importable function API, with an explicit device.
def read_reg32(dev_path, addr, camera_type=None):
    return Camera(dev_path, camera_type).read_reg32(addr)


def write_reg32(dev_path, addr, val, camera_type=None):
    Camera(dev_path, camera_type).write_reg32(addr, val)


def read_reg32f(dev_path, addr, camera_type=None):
    return Camera(dev_path, camera_type).read_reg32f(addr)


def write_reg32f(dev_path, addr, fval, camera_type=None):
    Camera(dev_path, camera_type).write_reg32f(addr, fval)


def read_string(dev_path, addr, length=64, camera_type=None):
    return Camera(dev_path, camera_type).read_string(addr, length)


def console(dev_path, camera_type=None):
    """Interactive console bound to the explicitly specified device."""
    import code
    try:
        import readline  # noqa: F401
    except ImportError:
        pass
    camera = Camera(dev_path, camera_type)
    scope = {'camera': camera, 'dev_path': camera.device}
    for name in ('read_reg32', 'write_reg32', 'read_reg32f', 'write_reg32f', 'read_string'):
        scope[name] = partial(globals()[name], camera_type=camera.camera_type)
    code.interact(banner='{} control: {}\nExample: camera.read_string(0x44)'.format(
        camera.name, camera.device), local=scope)


def main(argv=None, camera_type=None):
    parser = argparse.ArgumentParser(
        description='Register access for iLumos, MicroLynx and Titan through their kernel drivers.',
        epilog='No device autodetection. Omit COMMAND to open an interactive console. '
               'Dione and eg_ec_mipi cameras are excluded.')
    parser.add_argument('--camera', type=str.lower, choices=sorted(PROFILES),
                        help='camera type, needed only for a custom device name')
    parser.add_argument('device', help='explicit camera chardev, e.g. /dev/titan-9-0030')
    commands = parser.add_subparsers(dest='command', metavar='COMMAND')
    for name, help_text in (
            ('read_reg32', 'read a 32-bit integer register'),
            ('read_reg32f', 'read a register as IEEE 754 float'),
            ('write_reg32', 'write a 32-bit integer register'),
            ('write_reg32f', 'write an IEEE 754 float register'),
            ('read_string', 'read an ASCII string (default: 64 bytes)')):
        command = commands.add_parser(name, help=help_text)
        command.add_argument('addr', type=_parse_uint32, help='register address (decimal or 0x...)')
        if name == 'write_reg32':
            command.add_argument('value', type=_parse_uint32)
        elif name == 'write_reg32f':
            command.add_argument('value', type=float)
        elif name == 'read_string':
            command.add_argument('length', nargs='?', type=_parse_length, default=64)
    options = parser.parse_args(argv)
    if camera_type and options.camera and options.camera != camera_type:
        parser.error('this compatibility command only supports {}'.format(camera_type))
    try:
        camera = Camera(options.device, camera_type or options.camera)
        if options.command == 'read_string' and options.length > camera.string_limit:
            raise ValueError('{} supports string reads of at most {} bytes'.format(
                camera.name, camera.string_limit))
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if options.command is None:
            console(camera.device, camera.camera_type)
        elif options.command == 'read_reg32':
            value = camera.read_reg32(options.addr)
            print('0x{:08X} = 0x{:08X}  ({})'.format(options.addr, value, value))
        elif options.command == 'read_reg32f':
            print('0x{:08X} = {:.6g}'.format(options.addr, camera.read_reg32f(options.addr)))
        elif options.command == 'write_reg32':
            camera.write_reg32(options.addr, options.value)
            print('Written 0x{:08X}  ({}) to 0x{:08X}'.format(
                options.value, options.value, options.addr))
        elif options.command == 'write_reg32f':
            camera.write_reg32f(options.addr, options.value)
            print('Written {:.6g} to 0x{:08X}'.format(options.value, options.addr))
        else:
            print('0x{:08X} = {!r}'.format(options.addr,
                                         camera.read_string(options.addr, options.length)))
    except (OSError, ValueError, TypeError, OverflowError, struct.error) as exc:
        print('Error communicating with {}: {}'.format(camera.device, exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
