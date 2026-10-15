#!/usr/bin/env python3
"""Compile the real GenCP client/transports and emulate the I2C peer in both modes."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'sources/common/source/nvidia-oot/drivers/media/i2c/gencp-over-i2c'

PEER = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "gencp_common.h"
#include "gencp_client.h"

static unsigned char ack[1024], fifo[4096];
static size_t fifo_len, fifo_pos;
static unsigned char wire_last = 0xaa;
static unsigned int polls, reads, writes, busy;
static const char *fault = "none";
static unsigned char string_value[1008];

/* Independent wire checksum, not a call back into the code being tested. */
static unsigned short checksum(const unsigned char *data, size_t size)
{
    unsigned int sum = 0;
    for (size_t i = 0; i < size; i++) sum += data[i] << ((i & 1) ? 0 : 8);
    while (sum >> 16) sum = (sum & 65535) + (sum >> 16);
    if (sum == 65535) sum = 0;
    return (unsigned short)~sum;
}
static void put16(unsigned char *p, unsigned int n) { p[0] = n >> 8; p[1] = n; }
static unsigned int get16(const unsigned char *p) { return (p[0] << 8) | p[1]; }
static void fifo_encode(size_t length)
{
    fifo_len = fifo_pos = 0;
    for (size_t i = 0; i < length; i++) {
        unsigned char value = ack[i];
        if (value == wire_last) {
            unsigned char separator = 0;
            while (separator == value || separator == (unsigned char)~value) separator++;
            fifo[fifo_len++] = separator;
        }
        fifo[fifo_len++] = value;
        fifo[fifo_len++] = (unsigned char)~value;
        wire_last = (unsigned char)~value;
    }
}

ssize_t __wrap_write(int fd, const void *buffer, size_t length)
{
    const unsigned char *request = buffer;
    unsigned int command, size, request_id, status = 0;
    (void)fd;
    writes++;
    assert(length == 28); /* Current public API: ReadMem / 32-bit WriteMem. */
    assert(request[0] == 1 && request[1] == 0);
    assert(get16(request + 2) == checksum(request + 6, 10));
    assert(get16(request + 4) == checksum(request + 6, 22));
    assert(get16(request + 8) == 0x4000 && get16(request + 12) == 12);
    command = get16(request + 10);
    request_id = get16(request + 14);
    assert(request_id);
    if (!strcmp(fault, "write_io")) { errno = EIO; return -1; }
    if (!strcmp(fault, "write_short")) return length - 1;
    memset(ack, 0, sizeof(ack));
    ack[0] = 1;
    put16(ack + 10, command + 1);
    put16(ack + 14, request_id);
    if (command == 0x0800) {
        size = get16(request + 26);
        assert(size && size <= 1008);
        if (size == 4) {
            ack[16] = 0x01; ack[17] = 0x23; ack[18] = 0x45; ack[19] = 0x67;
        } else memcpy(ack + 16, string_value, size);
    } else {
        assert(command == 0x0802);
        /* Compact historical layout, plus alternate payload lengths: the
         * working client returns status without requiring an address echo. */
        size = 4;
        put16(ack + 18, 4);
        if (!strcmp(fault, "write_extended")) {
            size = 12;
            memset(ack + 16, 0x5a, size); /* No assumed address/length semantics. */
        }
        if (!strcmp(fault, "write_empty")) size = 0;
    }
    if (!strcmp(fault, "status")) { status = 0x8003; size = 0; }
    put16(ack + 8, status);
    put16(ack + 12, size);
    if (!strcmp(fault, "request_id")) put16(ack + 14, request_id + 1);
    if (!strcmp(fault, "command")) put16(ack + 10, 0x0805);
    if (!strcmp(fault, "oversize")) put16(ack + 12, 1009);
    if (!strcmp(fault, "short_payload")) put16(ack + 12, 2);
    put16(ack + 2, checksum(ack + 6, 10));
    put16(ack + 4, checksum(ack + 6, 10 + size));
    if (!strcmp(fault, "ccd_crc")) ack[2] ^= 1;
    if (!strcmp(fault, "scd_crc")) ack[4] ^= 1;
    fifo_encode(16 + size);
    /* Padding must not be parsed after a complete ACK. */
    if (size < 1008) {
        ack[16 + size] = 1; ack[17 + size] = 0;
        if (size < 1000) memset(ack + 18 + size, 0xff, 6);
    }
    return length;
}

ssize_t __wrap_read(int fd, void *buffer, size_t length)
{
    unsigned char *data = buffer;
    (void)fd;
    reads++;
    assert(length == GENCP_I2C_BUFFER_SIZE);
    if (!strcmp(fault, "read_io")) { errno = EIO; return -1; }
    if (!strcmp(fault, "read_short")) return length - 1;
    if (busy || !strcmp(fault, "timeout") || !strcmp(fault, "write_io") || !strcmp(fault, "write_short")) {
        if (busy) busy--;
        memset(data, GENCP_I2C_BUFFER_SIZE == 16 ? wire_last : 0, length);
        return length;
    }
#if GENCP_I2C_BUFFER_SIZE == 1024
    memcpy(data, ack, length);
#else
    for (size_t i = 0; i < length; i++)
        data[i] = fifo_pos < fifo_len ? fifo[fifo_pos++] : wire_last;
#endif
    return length;
}

/* Deterministic finite poll budget instead of waiting for real wall time. */
int nb_timers_init(int n) { (void)n; polls = 0; return 0; }
int nb_timer_start(int id, int ms) { (void)id; (void)ms; polls = 0; return 0; }
int nb_timer_is_expired(int id) { (void)id; return ++polls > 8; }
int nb_timer_delete(int id) { (void)id; return 0; }
int nb_timer_delete_all(void) { return 0; }

int main(int argc, char **argv)
{
    struct unio_handle camera = {.fd = 7};
    unsigned int value = 0xdeadbeef, before;
    unsigned short status;
    unsigned char text[1009];
    assert(argc == 2);
    for (size_t i = 0; i < sizeof(string_value); i++)
        string_value[i] = (unsigned char)(i / 2); /* repeats, complements, preambles */
    GENCPCLIENT_Init(&camera);
    assert(GENCPCLIENT_isSuccesfullyInitialized());
    fault = argv[1];
    if (!strcmp(fault, "busy")) busy = 2;
    if (!strcmp(fault, "write") || !strcmp(fault, "write_extended") || !strcmp(fault, "write_empty")) {
        status = GENCPCLIENT_WriteRegister(0x50000a00, 0x12345678);
        assert(status == 0);
    } else if (!strcmp(fault, "string")) {
        memset(text, 0xee, sizeof(text));
        assert(GENCPCLIENT_ReadString(0x44, text, 256) == 0);
        assert(!memcmp(text, string_value, 256) && text[256] == 0xee);
#if GENCP_I2C_BUFFER_SIZE == 1024
        assert(GENCPCLIENT_ReadString(0x44, text, 1008) == 0);
        assert(!memcmp(text, string_value, 1008));
        before = writes;
        assert(GENCPCLIENT_ReadString(0x44, text, 1009) == 0x8002);
        assert(GENCPCLIENT_ReadString(0x44, text, 0) == 0x8002);
        assert(writes == before);
#else
        (void)before;
#endif
    } else {
        status = GENCPCLIENT_ReadRegister(0x50000000, &value);
        if (!strcmp(fault, "none") || !strcmp(fault, "busy"))
            assert(status == 0 && value == 0x01234567);
        else {
            assert(status == (!strcmp(fault, "status") ? 0x8003 : 0x800b));
#if GENCP_I2C_BUFFER_SIZE == 1024
            assert(value == 0xdeadbeef);
#endif
        }
    }
    GENCPCLIENT_Cleanup();
    printf("mode=%d case=%s reads=%u writes=%u OK\n", GENCP_I2C_BUFFER_SIZE, fault, reads, writes);
    return 0;
}
'''


class GenCPTransportTests(unittest.TestCase):
    def test_real_sources_in_both_transport_modes(self):
        with tempfile.TemporaryDirectory(prefix='gencp-transport-') as temp:
            path = Path(temp)
            (path / 'peer.c').write_text(PEER)
            for mode in (16, 1024):
                executable = path / ('peer-' + str(mode))
                command = ['cc', '-std=gnu11', '-g', '-Wall', '-Wextra', '-Werror',
                           '-Wno-unused-parameter', '-Wno-unused-const-variable',
                           '-Wno-unused-variable', '-fsanitize=address,undefined',
                           '-fno-pie', '-no-pie', '-DGENCP_I2C_BUFFER_SIZE=' + str(mode),
                           '-I', str(LIB), str(path / 'peer.c')]
                command += [str(LIB / name) for name in
                            ('libunio.c', 'libunio_extras.c', 'gencp_common.c', 'gencp_client.c')]
                command += ['-Wl,--wrap=read', '-Wl,--wrap=write', '-o', str(executable)]
                subprocess.run(command, check=True)
                cases = ['none', 'busy', 'write', 'string', 'timeout', 'status',
                         'read_io', 'read_short', 'write_io', 'write_short', 'write_extended', 'write_empty']
                if mode == 1024:
                    cases += ['ccd_crc', 'scd_crc', 'request_id', 'command', 'oversize',
                              'short_payload']
                for case in cases:
                    with self.subTest(mode=mode, case=case):
                        result = subprocess.run([str(executable), case], capture_output=True,
                                                text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        print(result.stdout.splitlines()[-1])


if __name__ == '__main__':
    unittest.main()
