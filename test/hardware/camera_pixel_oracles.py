"""Independent camera-generated pixel references (not backend-to-backend equality)."""
import json
from pathlib import Path
import re
import struct
import tempfile
import numpy as np


def enginecore_rgb(y, cb, cr):
    # Fixed-point coefficients and truncation from the supplied FPGA converter.
    a,b,c,d,e = [int(x,2) for x in ('001001010100001011','000011001000100101',
        '010000001000110100','001100110001001010','000110100000001111')]
    return [max(0,min(255,value//32768)) for value in
            (a*(y-16)+d*(cr-128),a*(y-16)-b*(cb-128)-e*(cr-128),a*(y-16)+c*(cb-128))]


def check_frame(payload, fmt, width, height, stride, reference):
    fmt=fmt.strip()
    bpp=4 if fmt in ('AR24','AB24') else 2
    if stride < width*bpp or len(payload) < stride*height:
        return dict(passed=False,reason='Short frame or invalid stride')
    rows=np.frombuffer(payload,dtype=np.uint8,count=stride*height).reshape(height,stride)
    data=rows[:,:width*bpp].copy()
    kind=reference['kind'];tolerance=reference.get('tolerance',0)
    alpha=None
    if kind=='rgb':
        if fmt not in ('AR24','AB24'):raise ValueError('RGB oracle requires AR24/AB24')
        data=data.reshape(height,width,4);alpha=[int(data[:,:,3].min()),int(data[:,:,3].max())]
        actual=data[:,:,:3] if fmt=='AB24' else data[:,:,:3][:,:,::-1]
        expected=np.asarray(reference['value'],dtype=np.int32)
        delta=np.abs(actual.astype(np.int32)-expected)
        bad=np.any(delta>tolerance,axis=2)
    elif kind=='yuyv':
        if fmt!='YUYV' or width%2:raise ValueError('YUYV oracle requires even width')
        actual=data.reshape(height,width//2,4)
        delta=np.abs(actual.astype(np.int32)-np.asarray(reference['value'],dtype=np.int32))
        bad=np.repeat(np.any(delta>tolerance,axis=2),2,axis=1)
    elif kind in ('counter16','gray','ilumos_vertical'):
        if fmt not in ('Y16','Y16 -BE','Y14'):raise ValueError('Gray oracle requires a gray format')
        actual=np.frombuffer(data.tobytes(),dtype='>u2' if fmt=='Y16 -BE' else '<u2').reshape(height,width)
        expected=((np.arange(width*height,dtype=np.uint32)&0xffff).reshape(height,width)
                  if kind=='counter16' else np.asarray(reference.get('value',0),dtype=np.uint32))
        if kind=='ilumos_vertical':
            expected=(np.arange(height,dtype=np.uint32)[:,None]&1023) << (6 if fmt=='Y16 -BE' else 4)
        delta=np.abs(actual.astype(np.int32)-expected.astype(np.int32))
        bad=delta>tolerance
    else:raise ValueError('Unknown oracle '+kind)
    return dict(passed=not bool(np.any(bad)),pixels=width*height,
                mismatch_pixels=int(np.count_nonzero(bad)),max_difference=int(delta.max()),
                tolerance=tolerance,alpha_range=alpha,
                sample=actual.reshape(-1,actual.shape[-1])[0].tolist() if kind in ('rgb','yuyv') else int(actual.flat[0]))


class Controls:
    def __init__(self, runner, camera, label):
        self.r,self.camera,self.label=runner,camera,label
        self.prefix=None
        self.ilumos=Path(camera.device).name.startswith('ilumos-')
        if self.ilumos:
            self.prefix=['egCamCtrl.py', camera.device]
        elif not camera.enginecore:
            m=re.fullmatch(r'dioneir-i2c-(\d+)-[0-9a-fA-F]{4}-([0-9a-fA-F]{2})',Path(camera.device).name)
            if not m:raise ValueError('No Dione control mapping')
            self.prefix=['dioneCtrl.py','--bus',m[1],'--dev-addr',hex(int(m[2],16))]

    def read(self,address):
        if self.camera.enginecore:
            command=['ECSwCtrl','-i','i2c','-d',self.camera.device,'-c','ru '+hex(address)]
            delay=self.r.enginecore_control_pause()
        else:
            command=self.prefix+['read_reg32',hex(address)];delay=self.r.options.control_pause
        attempts=getattr(self.r.options,'recoveries',2)+1 if self.camera.enginecore else 1
        for attempt in range(attempts):
            self.r.pause(delay,'before reference register read')
            row,text=self.r.run(self.label+'-read-'+hex(address),command)
            if self.camera.enginecore:
                value=re.fullmatch(r'\s*(0x[0-9a-fA-F]+)\s+(\d+)\s*',text)
                valid=value and int(value[1],16)==int(value[2])
            else:
                value=re.search(r'=\s*(0x[0-9a-fA-F]+)' if self.ilumos else r'^\s*(0x[0-9a-fA-F]+)',text,re.M)
                valid=bool(value)
            if row['returncode']==0 and valid:return int(value[1],16)
            self.r.event('Reference read failed',camera=self.camera.name,address=hex(address),
                         attempt=attempt+1,response=text.strip(),log=row.get('log'))
        raise RuntimeError('Invalid register reply after bounded retries: '+text)

    def write(self,address,value):
        self.r.pause(self.r.enginecore_control_pause() if self.camera.enginecore else self.r.options.control_pause,
                     'before reference register write')
        if self.camera.enginecore:
            self.r.ec_control(self.camera,hex(address),value)
        else:
            row,text=self.r.run(self.label+'-write-'+hex(address),self.prefix+['write_reg32',hex(address),hex(value)],check=True)
            acknowledged=(re.search(r'^Written 0x[0-9a-fA-F]+.* to 0x[0-9a-fA-F]+',text,re.M) if self.ilumos
                          else re.search(r'^\s*OK\s*$',text,re.M))
            if not acknowledged:raise RuntimeError('Write not acknowledged: '+text)

    def memory(self,operation,path):
        if operation not in ('rm','wm'):
            raise ValueError('Unsupported palette operation: '+operation)
        self.r.pause(self.r.enginecore_control_pause(),'before palette '+operation)
        # ECSwCtrl has its own command parser. Keep its filename independent of
        # shell quoting and of spaces in the user's report directory.
        with tempfile.TemporaryDirectory(prefix='eg-palette-',dir='/tmp') as temporary:
            transfer=Path(temporary)/'palette.bin'
            if operation=='wm':transfer.write_bytes(Path(path).read_bytes())
            command='%s 0x20000 %s%s' % (operation,transfer,' 3520' if operation=='rm' else '')
            row,text=self.r.run(self.label+'-palette-'+operation,
                ['ECSwCtrl','-i','i2c','-d',self.camera.device,'-c',command],timeout=30)
            statuses=[int(x) for x in re.findall(r'^\s*!(-?\d+)',text,re.M)]
            allowed=(0,1) if operation=='rm' else (0,2)
            if row['returncode'] or any(x not in allowed for x in statuses) or re.search(r'error|failed',text,re.I):
                raise RuntimeError('Palette transfer failed: '+text)
            if operation=='rm':
                if transfer.stat().st_size!=3520 or 1 not in statuses:
                    raise RuntimeError('Palette snapshot is incomplete or has an unknown size')
                Path(path).write_bytes(transfer.read_bytes())


def execute_reference(r, camera, fmt, label, folder, record):
    fmt=fmt.strip()
    record['checks']=[];record['restored']=True
    def save():
        (folder/'reference.json').write_text(json.dumps(record,indent=2,default=str)+'\n');r.save()
    def capture(name,reference):
        result=r.capture_reference(camera,fmt,label+'-'+name,folder,reference)
        record['checks'].append(dict(name=name,reference=reference,**result));save()
    supported = ((camera.enginecore and fmt in ('AR24','AB24','YUYV','Y16')) or
                 (Path(camera.device).name.startswith('dioneir-') and fmt in ('AR24','AB24')) or
                 (Path(camera.device).name.startswith('ilumos-') and fmt in ('Y14','Y16 -BE')))
    if not supported:
        record.update(status='not_run',reason='No independently qualified camera pattern profile for '+fmt)
        save();return False
    control=Controls(r,camera,label)
    if camera.enginecore and fmt in ('AR24','AB24','YUYV'):
        saved={a:control.read(a) for a in (0x700,0x800,0x1000,0x4000)}
        before=folder/'palette-before.bin';second=folder/'palette-second.bin'
        control.memory('rm',before);control.memory('rm',second)
        if before.read_bytes()!=second.read_bytes():raise RuntimeError('Unstable palette readback')
        record['snapshot']={hex(a):v for a,v in saved.items()};record['palette_snapshot']=str(before);save()
        record['restored']=False;save()
        try:
            for a in (0x800,0x1000,0x4000):
                if saved[a]:control.write(a,0)
            control.write(0x700,1)
            for name,yuv in [('red',(81,90,240)),('green',(145,54,34)),('blue',(41,240,110))]:
                y,u,v=yuv;table=folder/(name+'.lut')
                table.write_bytes(struct.pack('<I',((y*4)<<20)|((u*4)<<10)|(v*4))*880)
                control.memory('wm',table);readback=folder/(name+'-readback.bin');control.memory('rm',readback)
                if table.read_bytes()!=readback.read_bytes():raise RuntimeError('Palette readback differs')
                reference=(dict(kind='yuyv',value=[y,u,y,v]) if fmt=='YUYV'
                           else dict(kind='rgb',value=enginecore_rgb(y,u,v),tolerance=1))
                capture(name,reference)
        finally:
            errors=[]
            operations=[lambda:control.write(0x700,0),lambda:control.memory('wm',before)]
            operations += [lambda a=a:control.write(a,saved[a]) for a in saved]
            for operation in operations:
                try:operation()
                except Exception as exc:errors.append(str(exc))
            after=folder/'palette-restored.bin';control.memory('rm',after)
            record['restored']=(after.read_bytes()==before.read_bytes() and all(control.read(a)==v for a,v in saved.items()))
            record['restoration_errors']=errors;save()
    elif camera.enginecore and fmt=='Y16':
        from camera_patterns import PatternTransaction
        def restart():
            r.pause(r.enginecore_control_pause(),'pattern saved before reboot')
            r.ec_control(camera,'0x8',1,reboot=True)
            r.pause(r.options.boot_wait,'pattern boot settling')
            current=r.refresh(camera.key)
            if r.read_ec_format(current)!=20:raise RuntimeError('Y16 format changed during pattern reboot')
        def snapshot(values):
            record['snapshot']={hex(k):v for k,v in values.items()};save()
        transaction=PatternTransaction('enginecore',control.read,control.write,9,restart=restart,on_snapshot=snapshot)
        try:
            with transaction:
                record['restored']=False
                capture('counter16',dict(kind='counter16'))
        finally:
            record['restored']=transaction.restored;save()
    elif control.ilumos:
        from camera_patterns import PatternTransaction
        solid=control.read(0x5000050c)
        def snapshot(values):
            record['snapshot']={hex(k):v for k,v in values.items()}
            record['snapshot']['0x5000050c']=solid
            save()
        transaction=PatternTransaction('ilumos',control.read,control.write,on_snapshot=snapshot)
        record['notes']=['The first vertical-pattern frame can be displaced after changing the stimulus; report it, do not discard it.']
        try:
            with transaction:
                record['restored']=False
                try:
                    for value in (0,1,0x155,0x2aa,0x3ff):
                        control.write(0x50000504,0);control.write(0x5000050c,value)
                        if control.read(0x50000504)!=0 or control.read(0x5000050c)!=value:
                            raise RuntimeError('iLumos solid readback differs')
                        capture('solid-%04x'%value,dict(kind='gray',value=value << (6 if fmt=='Y16 -BE' else 4)))
                    control.write(0x50000504,2);control.write(0x5000050c,0)
                    if control.read(0x50000504)!=2 or control.read(0x5000050c)!=0:raise RuntimeError('iLumos gradient readback differs')
                    capture('vertical',dict(kind='ilumos_vertical'))
                finally:
                    control.write(0x5000050c,solid)
        finally:
            record['restored']=transaction.restored and control.read(0x5000050c)==solid
            save()
    elif Path(camera.device).name.startswith('dioneir-') and fmt in ('AR24','AB24'):
        registers=(0x80108,0x8012c,0x8010c,0x80194,0x81404,0x81004)
        saved={a:control.read(a) for a in registers}
        record['snapshot']={hex(a):v for a,v in saved.items()};save();record['restored']=False
        try:
            control.write(0x80104,2);control.write(0x80108,0);control.write(0x81404,0);control.write(0x81004,1)
            for name,pixel,solid,rgb in [('blue',0x01100007,0x03fc,[0,0,255]),
                                        ('green',0x01100007,0xfc00,[0,63,0]),
                                        ('red',0x01080001,0xf800,[248,0,0])]:
                control.write(0x80104,2);control.write(0x80194,pixel);control.write(0x8012c,solid<<16);control.write(0x80104,1)
                if control.read(0x80194)!=pixel or control.read(0x8012c)!=(solid<<16):raise RuntimeError('Pattern readback differs')
                capture(name,dict(kind='rgb',value=rgb))
        finally:
            errors=[]
            operations=[lambda:control.write(0x80104,2)]
            operations += [lambda a=a:control.write(a,saved[a]) for a in (0x80194,0x81404,0x8012c,0x80108,0x81004)]
            if saved[0x8010c]&1:operations.append(lambda:control.write(0x80104,1))
            for operation in operations:
                try:operation()
                except Exception as exc:errors.append(str(exc))
            record['restored']=all(control.read(a)==v for a,v in saved.items())
            record['restoration_errors']=errors;save()
    else:
        record.update(status='not_run',reason='No independently qualified camera pattern profile for '+fmt)
        save();return False
    record['passed']=bool(record['checks']) and all(x['passed'] for x in record['checks']) and record['restored'] and not record.get('restoration_errors')
    save();return record['passed']
