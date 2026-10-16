# Exosens camera register control

`exosensCamCtrl.py` controls **iLumos, MicroLynx and Titan** through their
kernel-driver chardevs. Dione and the `eg_ec_mipi` cameras (MicroCube,
Crius1280, SmartIR640) are outside its scope.

The tool is a **single standalone Python 3 file**, using only the Python
standard library. Copy `exosensCamCtrl.py` to another Linux target and run it
with `python3`; no `/opt/eg/lib`, pip dependency or separate package is needed.
The target must have the appropriate camera driver and a successfully probed
camera. The global Exosens Debian package also installs the script in `/usr/bin`.

## Device selection

Always specify the device. The tool never scans `/dev` or picks the first
camera, including when several cameras of the same type are connected.

```sh
python3 exosensCamCtrl.py /dev/ilumos-9-0030 read_string 0x10000000
python3 exosensCamCtrl.py /dev/microlynx-9-0051 read_string 0xB0000000
python3 exosensCamCtrl.py /dev/titan-9-0030 read_reg32 0x500E0000
```

The type is inferred from the **specified device's name**, or the target of
an explicit symlink. For a custom name with no identifiable target, specify
the type before the command:

```sh
python3 exosensCamCtrl.py --camera titan /dev/my-camera read_string 0x44
```

Titan uses I2C address `0x30` and has a native sensor resolution of 1208x1024.
Its register map is:

| Register | Address | Access / expected value |
| --- | --- | --- |
| Firmware version | `0x10000000` | Read, 64-byte string |
| Pixel format | `0x500E0010` | Read/write, 32 bits; Mono16 `0x01100007`, Mono14 `0x01100025` (to be confirmed) |
| Image width | `0x500E0000` | Read, 32 bits; native width 1208 |
| Image height | `0x500E0004` | Read, 32 bits; native height 1024 |
| Model name | `0x00000044` | Read, 64-byte string |
| Serial number | `0x00000144` | Read, 64-byte string |
| Acquisition command | `0x500F0000` | Write, 32 bits; 0 = STOP, 1 = START |
| Acquisition status | `0x500F000C` | Read, 32 bits; 1 when active |

For example, stop and start acquisition with:

```sh
python3 exosensCamCtrl.py /dev/titan-9-0030 write_reg32 0x500F0000 0
python3 exosensCamCtrl.py /dev/titan-9-0030 write_reg32 0x500F0000 1
```

Titan hardware probe/streaming, CSI byte order and timing are not validated.

## Titan diagnostic probe mode

The `titan` module parameter `allow_probe_failure` defaults to `1`.
When sensor checks fail, the driver keeps `/dev/titan-<bus>-0030` available
for register access. The Titan device tree node must be enabled, and driver
resource allocation and framework registration must succeed.

This mode does not establish camera presence or streaming capability. The
reported 1208x1024 geometry is a fallback, sensor identity strings are empty,
and `pixel_format` is `unverified`. Register operations still report I2C and
GenCP errors; reads and writes are not simulated.

```sh
cat /sys/module/titan/parameters/allow_probe_failure
python3 exosensCamCtrl.py /dev/titan-9-0030 read_string 0x10000000 64
python3 exosensCamCtrl.py /dev/titan-9-0030 read_reg32 0x500E0000
```

To require successful sensor checks, unload the module after closing camera
applications, then load it with strict probing:

```sh
sudo modprobe -r titan
sudo modprobe titan allow_probe_failure=0
```

## Commands

```text
exosensCamCtrl.py DEVICE read_reg32 ADDR
exosensCamCtrl.py DEVICE read_reg32f ADDR
exosensCamCtrl.py DEVICE write_reg32 ADDR VALUE
exosensCamCtrl.py DEVICE write_reg32f ADDR VALUE
exosensCamCtrl.py DEVICE read_string ADDR [LENGTH]
exosensCamCtrl.py DEVICE
```

The last form opens an interactive console bound to that device:

```python
camera.read_string(0x44)
camera.read_reg32(0x500E0000)
```

Addresses and integer values accept decimal and `0x` notation and must fit in
an unsigned 32-bit register. Float operations reinterpret IEEE 754 binary32
bits. String length defaults to 64 bytes; the maximum per read is
70 bytes for iLumos and 256 for MicroLynx/Titan. Trailing NUL and `0xff` padding
is removed. Register addresses remain camera-specific; the script does not
translate them between camera types.

`--help` and command-specific help work without a connected camera. Successful
operations return exit code 0; device/protocol errors return 1; invalid CLI
arguments return 2. Positive GenCP error statuses returned by the MicroLynx
driver are reported as errors as well.

## Compatibility entry points

`ilumosCtrl.py` and `microlynxCtrl.py` are thin wrappers around
the same implementation. Their `read_reg32`, `write_reg32`, float
and string functions remain importable. They also require an explicit device:

```sh
ilumosCtrl.py /dev/ilumos-9-0030 read_string 0x44
microlynxCtrl.py /dev/microlynx-9-0051 read_string 0x44
```

To use a wrapper on another target, copy `exosensCamCtrl.py` alongside it.
To invoke `exosensCamCtrl.py` directly, copy only that file.

Titan uses `exosensCamCtrl.py` directly; there is no Titan-specific wrapper.
