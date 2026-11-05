"""Restore camera patterns, including persisted EngineCore settings when requested."""
class PatternTransaction:
    def __init__(self, family, read, write, pattern=9, restart=None, on_snapshot=None):
        self.family,self.read,self.write,self.pattern=family,read,write,pattern
        # The runner supplies restart for EngineCore. A missing callback keeps
        # volatile operation available to diagnostic tools investigating hot changes.
        self.restart,self.on_snapshot=restart,on_snapshot
        self.saved={};self.restored=False

    def __enter__(self):
        registers={'enginecore':(0x190,0x194),'ilumos':(0x50003000,0x50003004,0x50000a1c,0x50000504,0x50000508,0x50000510,0x50000a20),
                   'dione':(0x80108,0x8012c,0x8010c)}[self.family]
        self.saved={address:self.read(address) for address in registers}
        if self.on_snapshot:
            self.on_snapshot(dict(self.saved))
        try:
            if self.family=='enginecore':
                if self.saved[0x190] not in (0,1):raise ValueError('Invalid pattern enable state')
                self.write(0x190,0);self.write(0x194,self.pattern);self.write(0x190,1)
                self.enginecore_commit({0x190:1,0x194:self.pattern})
            elif self.family=='ilumos':
                # Use the input generator, before pixel-format packing. The late
                # Camera Link output emulator is not a reliable RAW14 reference.
                self.saved[0x60010044]=self.fpga_read()
                self.write(0x50000a00,2)
                if self.saved[0x60010044]&1:self.fpga_write(self.saved[0x60010044]&~1)
                self.write(0x50000504,4);self.write(0x50000508,0);self.write(0x50000510,0)
                # This setter updates SettingsShadow, not flash; never SaveUserSet.
                self.write(0x50000a1c,1)
                if self.read(0x50000a1c)!=1 or self.read(0x50000504)!=4 or self.read(0x50000508)!=0:
                    raise RuntimeError('Input generator readback mismatch')
            else:
                self.write(0x80104,2)
                # Selector4: row/column counter; clear moving(bit15) and shift(7:4).
                mode=(self.saved[0x8012c]&~0x80ff)|4
                self.write(0x8012c,mode);self.write(0x80108,self.saved[0x80108]&~1)
                self.write(0x80104,1)
                if self.read(0x80108)&1 or self.read(0x8012c)!=mode:raise RuntimeError('Dione pattern readback mismatch')
        except BaseException:
            self.restore();raise
        return self

    def enginecore_commit(self, expected):
        if any(self.read(a)!=v for a,v in expected.items()):
            raise RuntimeError('Pattern readback mismatch before saving')
        if self.restart:
            self.write(0x2f0,0)
            self.restart()
            if any(self.read(a)!=v for a,v in expected.items()):
                raise RuntimeError('Saved pattern did not load after camera reboot')

    def fpga_read(self):
        # GenCP DebugControl exposes FPGA physical registers indirectly.
        self.write(0x50003000,0x60010044);self.write(0x50003008,1)
        return self.read(0x50003004)

    def fpga_write(self,value):
        self.write(0x50003000,0x60010044);self.write(0x50003004,value);self.write(0x5000300c,1)

    def restore(self):
        if not self.saved:return
        if self.family=='enginecore':
            self.write(0x190,0);self.write(0x194,self.saved[0x194]);self.write(0x190,self.saved[0x190])
            self.enginecore_commit(self.saved)
            verify=()
        elif self.family=='ilumos':
            self.write(0x50000a00,2)
            for address in (0x50000504,0x50000508,0x50000510,0x50000a1c):
                self.write(address,self.saved[address])
            if 0x60010044 in self.saved:
                if self.fpga_read()!=self.saved[0x60010044]:self.fpga_write(self.saved[0x60010044])
                if self.fpga_read()!=self.saved[0x60010044]:raise RuntimeError('Output generator restoration failed')
            self.write(0x50003000,self.saved[0x50003000]);self.write(0x50003004,self.saved[0x50003004])
            if self.saved[0x50000a20]&1:self.write(0x50000a00,1)
            verify=(0x50003000,0x50003004,0x50000504,0x50000508,0x50000510,0x50000a1c)
        else:
            self.write(0x80104,2);self.write(0x8012c,self.saved[0x8012c]);self.write(0x80108,self.saved[0x80108])
            if self.saved[0x8010c]&1:self.write(0x80104,1)
            verify=(0x80108,0x8012c)
        if any(self.read(a)!=self.saved[a] for a in verify):raise RuntimeError('Test pattern restoration did not match the original registers')
        self.restored=True

    def __exit__(self, kind, value, traceback):
        self.restore()
