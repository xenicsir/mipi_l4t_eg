# GenCP control over the camera character device

The iLumos, MicroLynx and Titan character devices expose complete GenCP memory
transactions through an atomic ioctl. Existing register and string ioctl calls
remain available on the same device. V4L2 remains the video interface.

## User ABI

Include `<exosens/eg_camera_gencp.h>`. The pointer-free fixed-width structures
have the same layout for 32-bit and 64-bit callers.

`EG_IOCTL_GENCP_XFER` accepts `struct eg_gencp_xfer` (2080 bytes):

| Field | Input |
| --- | --- |
| version | `EG_GENCP_ABI_VERSION` (1) |
| tx_length | Length of the complete request in `tx` |
| rx_capacity | Available space in `rx`, up to 1024 bytes |
| rx_length | Zero; replaced by the returned ACK length |
| flags, reserved | Zero |
| tx | Complete GenCP packet including its checksums |
| rx | ACK output |

Zero-initialize the structure. The maximum packet size is 1024 bytes. Supported
commands are ReadMem (`0x0800`, 1–1008 payload bytes) and WriteMem (`0x0802`,
1–1000 payload bytes), using channel zero and the ACK-request flag. Memory
addresses are 64-bit. The caller must split larger transfers into commands;
there is no automatic chunking or resend. Resend requests and other command
classes are rejected. Request framing, checksums, address overflow and response
capacity are validated before attempting the operation. Payload bytes are not
converted; register endianness belongs to the camera memory map.

The ioctl owns transmission and ACK polling under the driver's transaction
mutex. The driver uses a per-camera wire request ID, validates the camera ACK,
and constructs a response carrying the caller's request ID. Independent callers
therefore cannot consume each other's replies. A successful ReadMem ACK contains
the requested bytes. A successful WriteMem ACK has a 4-byte SCD (reserved field
and bytes written), for a total of 20 bytes. An error ACK contains the GenCP
status and no memory payload. The two GenCP checksums cover the header and data.

A zero ioctl return means an ACK is available: inspect its GenCP status. Negative
system errors report malformed requests, unsupported commands, ABI errors or
user-copy failures. A transport timeout is returned as a GenCP status. Failed
writes are never resent automatically: a timeout does not establish whether the
camera applied the write. `ENODEV` indicates device removal, `ENOTTY` an unknown
ioctl, and `EOPNOTSUPP` an unavailable operation. In particular, iLumos basic-I2C
mode supports the historical register API but not this GenCP packet API.

`EG_IOCTL_GENCP_STATS` returns `struct eg_gencp_stats` (40 bytes), with ABI version
1. Values are cumulative for the camera context: native command
attempts, I2C read calls (`polls`), and requested TX/RX bytes. They count requested
bytes even if I2C fails, rather than confirmed bytes transferred. Concurrent
clients and internal driver operations contribute to the same counters; a
before/after delta is not exclusive to one client. `transport_bytes` is the
adapter's read size (16 or 1024 for the built-in adapters).

## Kernel transport extension

`struct unio_handle` owns packet buffers, request ID, timeout, counters and FIFO
decoder state for one camera. Explicit-handle memory calls are
`GENCPCLIENT_ReadMemory` and `GENCPCLIENT_WriteMemory`. Callers serialize access
to a handle. Compatibility register calls additionally require the driver mutex
across `GENCPCLIENT_Select` and the complete operation.

`GENCPCLIENT_SetTransport` installs `struct gencp_transport_ops` and an optional
private context. Its lifetime must cover all transactions. Configure before
publishing the camera device, or hold the transaction mutex when changing it.

| Member | Contract |
| --- | --- |
| read_size | Adapter read size, reported in statistics |
| idle_us | Delay after an idle or rejected candidate |
| begin(handle) | Prepare bounded adapter state for a new transaction |
| send(handle, packet, length) | Zero on success, negative on failure |
| read_packet(handle, packet, capacity) | 1: complete candidate; 2: progress; 0: idle; negative: I/O failure |

Callbacks must be bounded and respect capacity. The engine owns the monotonic
response deadline (default 2667 ms, configurable per handle), header/data
checksums and ACK correlation. A callback's I2C operation may itself block up to
the adapter's timeout. An error or invalid candidate is polled again within the
remaining response budget; writes are sent once. A synchronous callback must
not wait indefinitely, even when reporting progress. Use `unio_read/write` for
the built-in I2C statistics, or explicitly account for custom transfers.

The FIFO16 adapter preserves the stream's repeat/complement decoding and pending
bytes between packet boundaries. It pauses 1–2 ms when no usable candidate is
available. The buffer1024 adapter reads complete snapshots and pauses 5–6 ms
between rejected snapshots. It never joins bytes from different snapshots.

`GENCPCLIENT_Exchange` also accepts explicit memory-operation callbacks for an
adapter requiring an alternate memory implementation. Such callbacks exchange
raw bytes; they must preserve status and endianness semantics. The current
camera drivers use the native GenCP memory engine.
