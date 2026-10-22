#!/usr/bin/env python3
"""Run paced camera regression tests on a Jetson using its generated commands."""

import argparse
import array
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import subprocess
import sys
import tempfile
import time


class Camera:
    """Plain record, compatible with the Python 3.6 runtime on legacy targets."""
    def __init__(self, port, name, connected, sysfs='', device='', video='',
                 conformant_y14=False, groups=None):
        self.port = port
        self.name = name
        self.connected = connected
        self.sysfs = sysfs
        self.device = device
        self.video = video
        self.conformant_y14 = conformant_y14
        self.groups = [] if groups is None else groups

    @property
    def enginecore(self):
        return Path(self.device).name.startswith('eg-ec-mipi-')

    @property
    def key(self):
        return Path(self.sysfs).name


def parse_configuration(text):
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    headers = list(re.finditer(
        r'^\s*Port (\d+): (.*?) \((connected|not connected)\)\s*$', text, re.M))
    cameras = []
    for i, match in enumerate(headers):
        block = text[match.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        camera = Camera(int(match[1]), match[2], match[3] == 'connected')
        camera.conformant_y14 = bool(re.search(r'Y14 layout:\s*14 bits right-aligned', block))
        for field, label in [('sysfs', 'Sysfs'), ('device', 'I2C device'), ('video', 'Video device')]:
            value = re.search(r'^\s*' + label + r':\s*(\S+)', block, re.M)
            if value:
                setattr(camera, field, value[1])
        for line in block.splitlines():
            line = line.strip()
            for prefix, tool in [('v4l2-ctl ', 'v4l2'), ('rt_frame_monitor.py ', 'monitor'),
                                 ('gst-launch-1.0 ', 'gst')]:
                if not line.startswith(prefix):
                    continue
                if tool == 'v4l2':
                    camera.groups.append({})
                if not camera.groups:
                    raise ValueError('Streaming command without a V4L2 command')
                # Keep the primary command when optional variants follow it
                # (for example the MicroLynx single-line crop).
                camera.groups[-1].setdefault(tool, shlex.split(line))
        if camera.connected and not all((camera.sysfs, camera.device, camera.video, camera.groups)):
            raise ValueError('Incomplete connected camera description: ' + camera.name)
        cameras.append(camera)
    return cameras


def format_spec(group):
    spec = next(x for x in group['v4l2'] if x.startswith('--set-fmt-video='))
    dimensions = re.search(r'width=(\d+),height=(\d+)', spec)
    if not dimensions or 'pixelformat=' not in spec:
        raise ValueError('Missing format or dimensions')
    return int(dimensions[1]), int(dimensions[2]), spec.split('pixelformat=', 1)[1]


def parse_negotiated_format(text):
    fmt = re.search(r"Pixel Format\s*:\s*'([^']+)'", text)
    dimensions = re.search(r'Width/Height\s*:\s*(\d+)\s*/\s*(\d+)', text)
    size = re.search(r'Size Image\s*:\s*(\d+)', text)
    return dict(format=fmt[1] if fmt else None,
                width=int(dimensions[1]) if dimensions else None,
                height=int(dimensions[2]) if dimensions else None,
                image_size=int(size[1]) if size else 0)


def ec_code(pixel_format):
    match = re.search(r"'([^']+)'", pixel_format)
    fmt = (match[1] if match else pixel_format).strip()
    if fmt == 'Y16':
        return 20
    if fmt in ('AR24', 'AB24'):
        return 21
    if fmt == 'YUYV':
        return 22
    raise ValueError('Unsupported EngineCore pixel format: ' + pixel_format)


def streaming_command(tool, group, frames, folder, raw=None):
    args = list(group[tool])
    if tool == 'v4l2':
        args += ['--stream-count=' + str(frames), '--stream-to=' + str(raw)]
    elif tool == 'monitor':
        args += ['--num-frames=' + str(frames), '--base-dir=' + str(folder)]
    else:
        args.insert(args.index('v4l2src') + 1, 'num-buffers=' + str(frames))
        i = args.index('videoconvert')
        args[i:i] = ['identity', 'name=regression_probe', 'silent=false', '!']
    return args


def register_read_plan(camera):
    """Build read-only control checks from the discovered camera, not its port."""
    family = Path(camera.device).name.split('-', 1)[0]
    if family == 'dioneir':
        match = re.fullmatch(r'dioneir-i2c-(\d+)-[0-9a-fA-F]{4}-([0-9a-fA-F]{2})',
                             Path(camera.device).name)
        if not match:
            raise ValueError('Cannot determine Dione bus and FPGA address: ' + camera.device)
        prefix = ['dioneCtrl.py', '--device-type', 'I2C', '--bus', match[1],
                  '--dev-addr', hex(int(match[2], 16))]
        registers = (0x2f028, 0x2f02c, 0x80194)
        pixel_formats = [0x01080001, 0x01100007, 0x02180014]
    elif family in ('ilumos', 'titan', 'microlynx'):
        prefix = ['egCamCtrl.py', camera.device]
        registers = {'ilumos': (0x50000000, 0x50000004, 0x50000008),
                     'titan': (0x500e0000, 0x500e0004, 0x500e0010),
                     'microlynx': (0x500e0008, 0x500e000c, 0x500e0018)}[family]
        pixel_formats = [0x01100007, 0x01100025]
    else:
        return []
    width, height, _ = format_spec(camera.groups[0])
    checks = []
    for name, address, expected in [('width', registers[0], width),
                                    ('height', registers[1], height),
                                    ('pixel-format', registers[2], pixel_formats)]:
        checks.append(dict(name=name, command=prefix + ['read_reg32', hex(address)],
                           kind='integer', expected=expected))
    for name, address in [('model', 0x44), ('serial', 0x144)]:
        checks.append(dict(name=name, command=prefix + ['read_string', hex(address), '64'],
                           kind='string'))
    return checks


def validate_register_read(check, returncode, text):
    if returncode:
        return False, None
    if check['kind'] == 'integer':
        # egCamCtrl prints address = value; dioneCtrl prints just value.
        match = re.search(r'=\s*(0x[0-9a-fA-F]+)', text)
        if not match:
            match = re.search(r'^\s*(0x[0-9a-fA-F]+)', text, re.M)
        if not match:
            return False, None
        value = int(match[1], 16)
        expected = check['expected']
        return (value in expected if isinstance(expected, list) else value == expected), value
    value = text.split(' = ', 1)[-1].strip().strip("'\"\x00\xff\ufffd")
    # An empty string can be printed as "address =" without a trailing space.
    if re.fullmatch(r'0x[0-9a-fA-F]+\s*=', value):
        value = ''
    return bool(value), value


class Runner:
    def __init__(self, options):
        self.options = options
        self.out = options.output.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        self.env = os.environ.copy()
        self.env.update(DISPLAY=options.display, QT_X11_NO_MITSHM='1', PYTHONUNBUFFERED='1')
        self.results = []
        self.register_results = []
        self.xeneth_results = []
        self.events = []
        self.counter = 0
        self.cancelled = False
        self.lock = None

    def event(self, message, **fields):
        record = dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      message=message, **fields)
        self.events.append(record)
        print(record['time'], message, json.dumps(fields), flush=True)
        self.save()

    def save(self):
        tmp = self.out / 'results.json.new'
        tmp.write_text(json.dumps(dict(options=vars(self.options), results=self.results, register_results=self.register_results, xeneth_results=self.xeneth_results,
                                       events=self.events), indent=2, default=str) + '\n')
        tmp.replace(self.out / 'results.json')

    def pause(self, seconds, reason):
        if seconds:
            self.event('Waiting', seconds=seconds, reason=reason)
            time.sleep(seconds)

    def run(self, label, args, check=False, timeout=None):
        self.counter += 1
        path = self.out / ('%04d-' % self.counter + re.sub(r'[^\w.-]', '_', label) + '.log')
        start = time.monotonic()
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=self.env, start_new_session=True)
        data = b''
        try:
            data, _ = process.communicate(timeout=timeout or self.options.timeout)
            rc = process.returncode
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            # Kill the entire capture pipeline, including children of the monitor.
            for sig, delay in ((signal.SIGINT, 2), (signal.SIGTERM, 1), (signal.SIGKILL, 1)):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    data, _ = process.communicate()
                    break
                try:
                    data, _ = process.communicate(timeout=delay)
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:
                data, _ = process.communicate()
            rc = 124
            if isinstance(error, KeyboardInterrupt):
                path.write_bytes(data)
                raise
        text = data.decode(errors='replace')
        path.write_text(text)
        record = dict(command=args, returncode=rc, seconds=round(time.monotonic() - start, 3),
                      log=path.name)
        if check and rc:
            raise RuntimeError(str(record))
        return record, text

    def discover(self):
        _, text = self.run('generated-commands', ['eg_dt_camera_config_get.sh'], check=True)
        return parse_configuration(text)

    def refresh(self, key):
        for camera in self.discover():
            if camera.key == key and camera.connected:
                return camera
        raise RuntimeError('Camera no longer detected: ' + key)

    def idle(self, cameras):
        for camera in cameras:
            if camera.video:
                record, text = self.run('check-camera-idle', ['fuser', camera.video])
                if record['returncode'] == 0:
                    raise RuntimeError('Camera already in use: ' + camera.video + ' ' + text)
                if record['returncode'] != 1:
                    raise RuntimeError('Cannot verify camera is idle: ' + camera.video)

    def setup(self):
        import fcntl
        self.lock = open('/run/lock/eg-camera-regression.lock', 'w')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.run('inventory', ['sh', '-c', '''uname -a
cat /etc/nv_tegra_release
dpkg-query -W 'jetson-l4t-*eg*'
gst-launch-1.0 --version
media-ctl -p
for m in eg_ec_mipi dione_ir ilumos microlynx titan tegra_camera; do
 if test -d /sys/module/$m; then
  echo MODULE=$m
  cat /sys/module/$m/srcversion 2>/dev/null
  modinfo -F srcversion $m
  modinfo -n $m | xargs sha256sum
  if test -f /sys/module/$m/notes/.note.gnu.build-id; then od -An -tx1 /sys/module/$m/notes/.note.gnu.build-id; fi
 fi
done
sha256sum /usr/bin/eg_dt_camera_config_get.sh /usr/bin/rt_frame_monitor.py
cat /proc/sys/kernel/random/boot_id
'''], check=True)
        if not self.options.registers_only:
            _, text = self.run('xorg-process', ['pgrep', '-a', 'Xorg'])
            candidates = ([self.options.xauthority] if self.options.xauthority else [])
            candidates += re.findall(r'-auth\s+(\S+)', text)
            candidates += [str(Path.home() / '.Xauthority'), '/home/jetson/.Xauthority']
            for path in candidates:
                if not Path(path).is_file():
                    continue
                self.env['XAUTHORITY'] = path
                record, _ = self.run('check-display', ['xdpyinfo'], timeout=3)
                if record['returncode'] == 0:
                    self.event('Display available', display=self.options.display, authority=path)
                    break
            else:
                raise RuntimeError('Cannot open the display; set --display/--xauthority')
        self.event('Test script', sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.run('dmesg-before', ['dmesg'])

    def test_registers(self, camera, phase):
        checks = register_read_plan(camera)
        if not checks:
            self.event('Register checks not applicable', camera=camera.name,
                       reason='No dioneCtrl/egCamCtrl interface for this family')
            return True
        result = dict(key=camera.key, camera=camera.name, phase=phase, reads=[], passed=False)
        self.register_results.append(result)
        for check in checks:
            self.pause(self.options.control_pause, 'before register read')
            record, text = self.run('%s-%s-register-%s' % (camera.key, phase, check['name']),
                                    check['command'])
            passed, value = validate_register_read(check, record['returncode'], text)
            result['reads'].append(dict(record, name=check['name'], value=value,
                                        expected=check.get('expected'), passed=passed))
            self.save()
            if not passed:
                self.event('Register read failed', camera=camera.name, phase=phase,
                           register=check['name'], log=record['log'])
                return False
        result['passed'] = True
        self.event('Register reads complete', camera=camera.name, phase=phase, count=len(checks))
        return True

    def test_xeneth(self, camera, phase):
        family = Path(camera.device).name.split('-', 1)[0]
        if self.options.skip_xeneth or family not in ('ilumos', 'microlynx', 'titan'):
            return True
        result = dict(key=camera.key, camera=camera.name, phase=phase, commands=[], passed=False)
        self.xeneth_results.append(result)
        binary = self.options.xeneth_minimal
        if not shutil.which(binary):
            result['error'] = 'Build egXenethMinimal or provide --xeneth-minimal PATH'
            self.event('Xeneth test unavailable', camera=camera.name, error=result['error'])
            return False
        width = register_read_plan(camera)[0]
        commands = [['probe'], ['read32', width['command'][-1], str(self.options.xeneth_reads)]]
        for args in commands:
            self.pause(self.options.control_pause, 'before Xeneth minimal control test')
            record, text = self.run('%s-%s-xeneth-%s' % (camera.key, phase, args[0]),
                                    [binary, camera.device] + args)
            result['commands'].append(record)
            if record['returncode'] == 3 and args[0] == 'probe' and family == 'ilumos':
                result.update(status='not applicable', reason='Firmware uses basic I2C, not GenCP', passed=True)
                self.event('Xeneth not applicable', camera=camera.name, reason=result['reason'])
                return True
            passed = record['returncode'] == 0
            if args[0] == 'read32':
                value = re.search(r'reads=(\d+) value=([0-9a-fA-F]{8})', text)
                passed = passed and value is not None and int(value[1]) == self.options.xeneth_reads
                passed = passed and value is not None and int(value[2], 16) == width['expected']
            record['passed'] = bool(passed)
            self.save()
            if not passed:
                self.event('Xeneth test failed', camera=camera.name, phase=phase, log=record['log'])
                return False
        result['passed'] = True
        self.event('Xeneth tests complete', camera=camera.name, phase=phase)
        return True

    def set_ec_format(self, key, code, reboot=False):
        camera = self.refresh(key)
        if not camera.enginecore:
            raise ValueError('Reboot is only supported for EngineCore cameras')
        actual = ec_code(Path(camera.sysfs, 'pixel_format').read_text())
        if actual == code and not reboot:
            return
        self.idle([c for c in self.discover() if c.connected and c.enginecore])
        if actual != code:
            for address, value in (('0x260', code), ('0x2F0', 0)):
                record, text = self.run('ec-write-' + address,
                    ['ECSwCtrl', '-i', 'i2c', '-d', camera.device, '-c', 'wu %s %d' % (address, value)], check=True)
                if re.search(r'\b(?:error|failed)\b', text, re.I):
                    raise RuntimeError('EngineCore control error: ' + text)
                self.pause(self.options.control_pause, 'EngineCore control command completed')
        self.run('ec-reboot', ['ECSwCtrl', '-i', 'i2c', '-d', camera.device,
                              '-c', 'wu 0x8 1'], check=True)
        self.pause(self.options.boot_wait, 'camera reboot')
        self.run('ec-unload', ['rmmod', 'eg_ec_mipi'], check=True)
        self.pause(self.options.control_pause, 'EngineCore module unloaded')
        self.run('ec-load', ['modprobe', 'eg_ec_mipi'], check=True)
        self.pause(self.options.probe_wait, 'camera and driver settling after probe')
        camera = self.refresh(key)
        actual = ec_code(Path(camera.sysfs, 'pixel_format').read_text())
        if actual != code:
            raise RuntimeError('Camera did not retain requested format: %s != %s' % (actual, code))
        self.event('EngineCore ready', camera=camera.name, key=key, code=code, recovery=reboot)

    def enumerate_formats(self, camera):
        record, text = self.run('enumeration-' + camera.key,
                                ['v4l2-ctl', '-d', camera.video, '--list-formats-ext'], check=True)
        formats = re.findall(r"\[\d+\]: '([^']+)'", text)
        if not formats or len(formats) != len(set(formats)):
            raise RuntimeError('Empty or duplicate fourcc: ' + text)
        for block in re.split(r'\[\d+\]:', text)[1:]:
            sizes = re.findall(r'Size: Discrete (\d+x\d+)', block)
            if len(sizes) != len(set(sizes)):
                raise RuntimeError('Duplicate dimensions: ' + text)
        return formats

    def capture(self, camera, group, tool, label):
        expected_width, expected_height, expected_format = format_spec(group)
        self.pause(self.options.stream_gap, 'before ' + tool + ' stream')
        with tempfile.NamedTemporaryFile(prefix='eg-camera-test-', suffix='.raw') as raw:
            args = streaming_command(tool, group, self.options.frames,
                                     self.out / (label + '-monitor-data'), raw.name)
            record, text = self.run(label + '-' + tool, args)
            passed = record['returncode'] == 0
            if tool == 'v4l2':
                _, actual = self.run(label + '-effective-format',
                                    ['v4l2-ctl', '-d', camera.video, '--get-fmt-video'])
                negotiated = parse_negotiated_format(actual)
                image_size = negotiated['image_size']
                length = Path(raw.name).stat().st_size
                record.update(bytes=length, expected_bytes=image_size * self.options.frames,
                              effective_format=negotiated['format'],
                              effective_width=negotiated['width'], effective_height=negotiated['height'])
                passed = passed and image_size > 0 and length == image_size * self.options.frames
                passed = passed and negotiated['format'] == expected_format
                passed = passed and (negotiated['width'], negotiated['height']) == (expected_width, expected_height)
                if length:
                    digest = hashlib.sha256()
                    low, high = 65535, 0
                    while True:
                        data = raw.read(1024 * 1024)
                        if not data:
                            break
                        digest.update(data)
                        if expected_format.strip() in ('Y14', 'Y16', 'Y16 -BE'):
                            values = array.array('H')
                            values.frombytes(data)
                            if expected_format == 'Y16 -BE' and sys.byteorder == 'little':
                                values.byteswap()
                            low, high = min(low, min(values)), max(high, max(values))
                    record['sha256'] = digest.hexdigest()
                    if expected_format.strip() in ('Y14', 'Y16', 'Y16 -BE'):
                        record.update(pixel_min=low, pixel_max=high)
                    if expected_format.strip() == 'Y14' and camera.conformant_y14:
                        passed = passed and high < 16384
            elif tool == 'monitor':
                frames = [int(x) for x in re.findall(r'frame=\s*(\d+)', text)]
                record['frames_reported'] = max(frames) + 1 if frames else 0
                passed = passed and record['frames_reported'] >= self.options.frames
            else:
                record['buffers_reported'] = len(re.findall(r'last-message = chain', text))
                passed = passed and 'Got EOS' in text and record['buffers_reported'] >= self.options.frames
        record['pass'] = bool(passed)
        self.event('Capture complete', camera=camera.name, format=expected_format,
                   tool=tool, passed=bool(passed), log=record['log'])
        return record

    def test_group(self, key, expected_format, code=None, tools=('v4l2', 'monitor', 'gst')):
        attempts = []
        result = dict(key=key, format=expected_format, attempts=attempts, passed=False)
        self.results.append(result)
        for attempt in range(self.options.recoveries + 1):
            camera = self.refresh(key)
            group = next(g for g in camera.groups if format_spec(g)[2] == expected_format)
            label = '%s-%s-attempt%d' % (key, re.sub(r'\W', '_', expected_format), attempt)
            entry = dict(number=attempt, camera=camera.name, enumeration=self.enumerate_formats(camera), tools={})
            attempts.append(entry)
            for tool in tools:
                if tool not in group:
                    if tool == 'gst' and expected_format.strip() == 'Y14':
                        entry['tools'][tool] = dict(status='not applicable', reason='No GStreamer Y14 command')
                        continue
                    entry['tools'][tool] = dict(reason='Missing generated command')
                    entry['tools'][tool]['pass'] = False
                    break
                entry['tools'][tool] = self.capture(camera, group, tool, label)
                self.save()
                # A display consuming buffers must not hide a failed raw capture.
                if not entry['tools'][tool]['pass']:
                    break
            passed = all(x.get('pass', x.get('status') == 'not applicable')
                         for x in entry['tools'].values())
            if passed:
                result['passed'] = True
                self.save()
                return True
            self.run(label + '-dmesg-failure', ['dmesg'])
            self.save()
            if code is None or attempt == self.options.recoveries:
                break
            self.event('Recovering EngineCore camera', camera=camera.name, attempt=attempt + 1)
            self.set_ec_format(key, code, reboot=True)
        self.save()
        return False

    def execute(self):
        self.setup()
        discovered = self.discover()
        self.idle([c for c in discovered if c.connected])
        self.event('Discovery', cameras=[vars(c) for c in discovered])
        cameras = [c for c in discovered if c.connected and
                   (not self.options.only or c.key in self.options.only or c.name in self.options.only)]
        if not cameras:
            raise RuntimeError('No matching connected cameras')
        if self.options.registers_only:
            for camera in cameras:
                current = self.refresh(camera.key)
                if self.test_registers(current, 'registers-only'):
                    self.test_xeneth(current, 'registers-only')
            self.event('Register-only tests finished', passed=sum(x['passed'] for x in self.register_results),
                       total=len(self.register_results))
            return 0 if all(x['passed'] for x in self.register_results + self.xeneth_results) else 1
        for initial in cameras:
            camera = self.refresh(initial.key)
            if not self.test_registers(camera, 'before-video'):
                continue
            if not self.test_xeneth(camera, 'before-video'):
                continue
            original_code = ec_code(Path(camera.sysfs, 'pixel_format').read_text()) if camera.enginecore else None
            _, current = self.run('original-format-' + camera.key,
                                  ['v4l2-ctl', '-d', camera.video, '--get-fmt-video'], check=True)
            match = re.search(r"Pixel Format\s*:\s*'([^']+)'", current)
            original_format = match[1] if match else format_spec(camera.groups[0])[2]
            if camera.enginecore:
                supported = self.enumerate_formats(camera)
                # Nano/TX2 cannot capture RAW16. Reject an unusable initial
                # setup before entering a block that restores camera settings.
                available_codes = [21, 22]
                if any(fmt.strip() == 'Y16' for fmt in supported):
                    available_codes.insert(0, 20)
                if original_code not in available_codes:
                    raise RuntimeError('Initial camera format is unsupported by this target')
            try:
                if camera.enginecore:
                    codes = [original_code] + [x for x in available_codes if x != original_code]
                    for code in codes:
                        self.set_ec_format(camera.key, code)
                        current = self.refresh(camera.key)
                        for group in current.groups:
                            self.test_group(camera.key, format_spec(group)[2], code)
                else:
                    for group in camera.groups:
                        self.test_group(camera.key, format_spec(group)[2])
            finally:
                if not self.cancelled:
                    if camera.enginecore:
                        self.set_ec_format(camera.key, original_code)
                    # Confirm a valid raw stream after restoring the camera's
                    # initial format. For GenCP cameras this happens at STREAMON.
                    current = self.refresh(camera.key)
                    target = format_spec(current.groups[0])[2] if camera.enginecore else original_format
                    self.test_group(current.key, target, original_code, tools=('v4l2',))
                    current = self.refresh(camera.key)
                    if self.test_registers(current, 'after-video'):
                        self.test_xeneth(current, 'after-video')
        self.run('dmesg-after', ['dmesg'])
        self.event('Finished', passed=sum(x['passed'] for x in self.results), total=len(self.results))
        return 0 if all(x['passed'] for x in self.results + self.register_results + self.xeneth_results) else 1


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True, help='New directory for all logs and JSON results')
    p.add_argument('--only', action='append', default=[], help='Camera name or sysfs ID; repeat to select several')
    p.add_argument('--registers-only', action='store_true', help='Only read control registers; no video, format changes or GUI')
    p.add_argument('--xeneth-minimal', default='egXenethMinimal', help='ARM64 reference client built with the Xeneth SDK packet codec')
    p.add_argument('--xeneth-reads', type=int, default=20)
    p.add_argument('--skip-xeneth', action='store_true', help='Explicitly omit the new GenCP interface tests for legacy driver packages')
    p.add_argument('--frames', type=int, default=60)
    p.add_argument('--timeout', type=float, default=10)
    p.add_argument('--control-pause', type=float, default=2)
    p.add_argument('--boot-wait', type=float, default=5)
    p.add_argument('--probe-wait', type=float, default=5)
    p.add_argument('--stream-gap', type=float, default=3)
    p.add_argument('--recoveries', type=int, default=2, help='Maximum camera reboots per failed EngineCore format')
    p.add_argument('--display', default=':0')
    p.add_argument('--xauthority')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.frames <= 0 or args.timeout <= 0 or args.recoveries < 0 or not 1 <= args.xeneth_reads <= 1000000:
        p.error('frames/timeout must be positive; recoveries must be nonnegative')
    if min(args.control_pause, args.boot_wait, args.probe_wait, args.stream_gap) < 0:
        p.error('Delays must be nonnegative')
    if os.geteuid() != 0:
        p.error('Run as root on the Jetson')
    runner = Runner(args)
    def stop(signum, frame):
        runner.cancelled = True
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return runner.execute()
    except KeyboardInterrupt:
        runner.cancelled = True
        runner.event('Interrupted; no further camera changes')
        return 130
    except Exception as error:
        runner.event('Error', error=repr(error))
        return 1
    finally:
        runner.save()


if __name__ == '__main__':
    sys.exit(main())
