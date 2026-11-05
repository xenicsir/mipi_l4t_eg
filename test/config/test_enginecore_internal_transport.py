#!/usr/bin/env python3
"""Exercise the real internal helpers' native-I2C contract and lock cleanup."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'sources/common/source/nvidia-oot/drivers/media/i2c/eg_ec_mipi_src.c'
HEADERS = SOURCE.parent


def helper(source, name):
    start = source.index('static inline int ' + name + '(')
    brace = source.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


SHIM = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include "ecctrl_i2c.h"
#define MAX_I2C_CLIENTS_NUMBER 1
struct i2c_client { int unused; };
struct {struct i2c_client *i2c_client; int i2c_locked;} i2c_clients[1];
static int calls, backend_result;
static int fifo_call, expected_timeout;
static uint8_t payload[32];
static void __ecctrl_i2c_timeout_set(struct i2c_client *client, int timeout) {
    assert(client==i2c_clients[0].i2c_client && timeout==0);
}
static int transfer(struct i2c_client *client, ecctrl_i2c_t *args) {
    assert(client==i2c_clients[0].i2c_client);
    assert(i2c_clients[0].i2c_locked==1);
    assert(args->deviceType==ECCTRL_I2C_TYPE);
    assert(args->data_address==0x184 && args->data==payload && args->data_size==sizeof(payload));
    assert(args->cb==NULL && args->i2c_timeout==expected_timeout);
    assert(args->fifo_flags==(fifo_call ? FIFO_FLAG_START|FIFO_FLAG_END : 0));
    calls++;
    return backend_result;
}
#define __ecctrl_i2c_read_reg transfer
#define __ecctrl_i2c_write_reg transfer
#define __ecctrl_i2c_read_fifo transfer
#define __ecctrl_i2c_write_fifo transfer
'''


class EngineCoreInternalTransportTests(unittest.TestCase):
    def test_native_framing_and_error_paths_for_all_helpers(self):
        source = SOURCE.read_text()
        names = ['eg_ec_mipi_' + action for action in ('read_reg','write_reg','read_fifo','write_fifo')]
        code = SHIM + '\n'.join(helper(source, name) for name in names)
        code += '\nint main(void) { struct i2c_client present={0}, absent={0}; i2c_clients[0].i2c_client=&present;\n'
        for name in names:
            code += 'fifo_call=%d; expected_timeout=%d;\n' % ('fifo' in name, 100 if name.endswith('write_reg') else 0)
            for result in (0, -5):
                code += ('backend_result=%d; calls=0; assert(%s(&present,0x184,payload,sizeof(payload))==%d); '
                         'assert(calls==1 && i2c_clients[0].i2c_locked==0);\n') % (result,name,result)
            code += ('calls=0; i2c_clients[0].i2c_locked=1; '
                     'assert(%s(&present,0x184,payload,sizeof(payload))==-EBUSY); '
                     'assert(calls==0 && i2c_clients[0].i2c_locked==1); i2c_clients[0].i2c_locked=0; '
                     'assert(%s(&absent,0x184,payload,sizeof(payload))==-EINVAL); assert(calls==0);\n') % (name,name)
        code += 'return 0;}\n'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'test.c').write_text(code)
            # Poison uninitialized locals when the host compiler supports it.
            flag = '-ftrivial-auto-var-init=pattern'
            probe = subprocess.run(['cc',flag,'-x','c','-c','-o',str(path/'probe.o'),'-'],
                                   input='int probe;\n',universal_newlines=True,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            flags = [flag] if probe.returncode == 0 else []
            subprocess.run(['cc','-std=gnu11','-O0','-Wall','-Wextra','-Werror'] + flags +
                           ['-I'+str(HEADERS),str(path/'test.c'),'-o',str(path/'test')],check=True)
            subprocess.run([str(path/'test')],check=True)


if __name__=='__main__':
    unittest.main()
