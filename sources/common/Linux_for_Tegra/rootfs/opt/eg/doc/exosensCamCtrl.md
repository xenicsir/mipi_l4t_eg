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
python3 exosensCamCtrl.py /dev/titan-9-0030 read_reg32 0x50000000
```

The type is inferred from the **specified device's name**, or the target of
an explicit symlink. For a custom name with no identifiable target, specify
the type before the command:

```sh
python3 exosensCamCtrl.py --camera titan /dev/my-camera read_string 0x44
```

Titan's I2C address `0x30` and native sensor resolution 1208x1024 are confirmed
by Werner (Titan eSW). Its register map provisionally follows iLumos and still
requires refinement, including acquisition commands.

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
camera.read_reg32(0x50000000)
```

Addresses and integer values accept decimal and `0x` notation and must fit in
an unsigned 32-bit register. Float operations reinterpret IEEE 754 binary32
bits. String length defaults to 64 bytes; the current maximum per read is
70 bytes for iLumos and 256 for MicroLynx/Titan. Trailing NUL and `0xff` padding
is removed. Register addresses remain camera-specific; the script does not
translate them between camera types.

`--help` and command-specific help work without a connected camera. Successful
operations return exit code 0; device/protocol errors return 1; invalid CLI
arguments return 2. Positive GenCP error statuses returned by the MicroLynx
driver are reported as errors as well.

## Compatibility entry points

`ilumosCtrl.py` and `microlynxCtrl.py` are thin wrappers around
the same implementation. Their existing `read_reg32`, `write_reg32`, float
and string functions remain importable. They also require an explicit device:

```sh
ilumosCtrl.py /dev/ilumos-9-0030 read_string 0x44
microlynxCtrl.py /dev/microlynx-9-0051 read_string 0x44
```

Old invocations that omitted DEVICE must be updated. To use a wrapper on a
different target, copy `exosensCamCtrl.py` alongside it; copying only the generic
script is sufficient when using the new command directly.

Titan uses `exosensCamCtrl.py` directly; there is no Titan-specific wrapper.
