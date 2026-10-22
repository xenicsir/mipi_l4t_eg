# Linux GenCP control interface

`EgGenCPPort` connects a GenCP packet client to the existing camera character
device, for example `/dev/ilumos-10-0030`. The driver serializes each complete
command and ACK with its internal camera-control operations. Video acquisition
uses the separate V4L2 device.

The reference `egXenethMinimal` program builds with the SDK's unmodified
`GenCPPacketHandler` implementation. It exercises control transactions; it does
not implement discovery, a GenICam feature tree or image acquisition.

## Build and run

The SDK source tree must provide `Src/src_sdk/xccapi_gencp_cl_packet_handler.cpp`,
its header and `xccapi_gencp_cl_defs.h`. The SDK files are not included here.
A Linux C++11 compiler and Python 3 are required.

```sh
python3 build_minimal.py --xeneth-source /path/to/Xeneth --output ./egXenethMinimal
sudo ./egXenethMinimal /dev/ilumos-10-0030 probe
sudo ./egXenethMinimal /dev/ilumos-10-0030 read32 0x50000000 100
```

For a Jetson cross-build, pass `--cxx /path/to/aarch64-linux-gnu-g++` and copy the
result to the target. The adjacent `.build.json` records inputs and binary hashes.
The `compat/WinSock2.h` shim supplies Linux network byte-order definitions used by
the packet codec. Neither the codec nor the SDK source tree is modified.

Additional commands are `read ADDR LEN`, `write32 ADDR VALUE` and `write ADDR HEX`.
Integer arguments accept decimal or a `0x` prefix. Memory payloads retain their
original byte order; `read32`/`write32` interpret values as big endian.
Use a known writable register for write tests.

## SDK transport adaptation

Replace the serial send/read exchange with
`EgGenCPPort::Transaction(request, reply)`. Keep SDK command composition and ACK
parsing. One call submits one complete GenCP request and returns one complete
ACK; no termios setup or direct access to `/dev/i2c-*` is required. Camera status
errors remain in the ACK for the SDK parser. System and ABI errors throw
`std::system_error`. Open the device once and retain the port for the session.

The shared header is `eg_camera_gencp.h`, installed by driver packages under
`/usr/include/exosens/`. The source archive includes a copy beside the adapter.
See [GENCP_CONTROL_INTERFACE.md](../../docs/GENCP_CONTROL_INTERFACE.md) for the ioctl
contract and transport extension points.

Configure SDK memory transfers for at most 1008 read bytes or 1000 write bytes
per command. Split larger memory operations before packet composition; the
transport adapter does not fragment complete packets. Disable serial resend
requests. On a write timeout, report the uncertainty to the caller instead of
automatically repeating the write. Full SDK integration must also provide camera
discovery/bootstrap and the separate V4L2 acquisition path as required.

The reference program exits 0 on success, 1 on a failed transaction, 2 for a
missing command, and 3 for `EOPNOTSUPP`. On iLumos firmware using basic I2C, the
existing register ioctl interface remains usable and the new GenCP ioctl is not
applicable. A driver without the new API returns `ENOTTY`.

For automatic target validation, provide the binary to
`test/hardware/run_camera_regression.py --xeneth-minimal /path/to/egXenethMinimal`.
The runner tests this interface and the existing register scripts before and
after streaming on the applicable cameras.
