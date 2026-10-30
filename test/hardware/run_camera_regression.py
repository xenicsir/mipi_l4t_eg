#!/usr/bin/env python3
"""Run paced camera regression tests on a Jetson using its generated commands."""

import argparse
import array
import datetime
import hashlib
import json
import math
import pwd
from contextlib import contextmanager
import os
from pathlib import Path
import re
import resource
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
                                 ('gst-launch-1.0 ', 'gst'), ('env __GL_YIELD=USLEEP gst-launch-1.0 ', 'gst')]:
                if not line.startswith(prefix):
                    continue
                if tool == 'v4l2':
                    camera.groups.append({})
                if not camera.groups:
                    raise ValueError('Streaming command without a V4L2 command')
                # Keep the primary command when optional variants follow it
                # (for example the MicroLynx single-line crop).
                words = shlex.split(line)
                if tool == 'gst' and 'egv4l2camerasrc' in words:
                    tool = 'gst_nvmm'
                camera.groups[-1].setdefault(tool, words)
                if tool in ('gst', 'gst_nvmm') and 'videocrop' not in words:
                    camera.groups[-1].setdefault('_gst_commands', []).append(words)
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
        source = 'egv4l2camerasrc' if 'egv4l2camerasrc' in args else 'v4l2src'
        args.insert(args.index(source) + 1, 'num-buffers=' + str(frames))
        i = next(args.index(name) for name in ('videoconvert', 'nvvidconv', 'nv3dsink', 'fakesink') if name in args)
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


def parse_frame_rate(text):
    value = text.strip()
    if not re.fullmatch(r'[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
        raise ValueError('Invalid ECSwCtrl framerate response: ' + repr(value))
    rate = float(value)
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError('Camera framerate must be finite and positive')
    return rate


def timestamp_cadence(values, warmup=1.0):
    if not values or any(b <= a for a, b in zip(values, values[1:])):
        return dict(steady_fps=None, steady_seconds=0, steady_frames=0)
    kept = [v for v in values if v >= values[0] + warmup]
    span = kept[-1] - kept[0] if len(kept) > 1 else 0
    return dict(steady_fps=(len(kept)-1)/span if span else None,
                steady_seconds=span, steady_frames=len(kept))


def stream_cadence(tool, text):
    if tool == 'monitor':
        rows = re.findall(r'FPS_RESULT (\{[^\r\n]+\})', text)
        return json.loads(rows[-1]) if rows else {}
    if tool == 'v4l2':
        values = [float(x) for x in re.findall(r'cap dqbuf:.*?\bts:\s*([0-9]+\.[0-9]+)', text)]
    else:
        values = [int(h)*3600+int(m)*60+float(s) for h,m,s in
                  re.findall(r'last-message = chain.*?\bpts:\s*(\d+):(\d+):(\d+\.\d+)', text)]
    measured = timestamp_cadence(values)
    return dict(capture=measured, processing=measured)


def rate_matches(measured, expected, tolerance):
    return bool(measured and measured.get('steady_fps') is not None
                and measured.get('steady_seconds', 0) >= 1.0
                and abs(measured['steady_fps'] - expected) <= expected*tolerance)


def local_x11(display):
    return bool(re.fullmatch(r'(?:unix/?)?:[0-9]+(?:\.[0-9]+)?', display or ''))


class Runner:
    def __init__(self, options):
        self.options = options
        self.out = options.output.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        self.incoming_env = os.environ.copy()
        self.forwarded_env = None
        self.env = os.environ.copy()
        self.env.update(DISPLAY=options.display or ":0", QT_X11_NO_MITSHM='1', PYTHONUNBUFFERED='1')
        self.results = []
        self.register_results = []
        self.xeneth_results = []
        self.events = []
        self.environment_results = []
        self.fps_reads = []
        self.fps_targets = {}
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
                                       events=self.events, environment_results=self.environment_results,
                                       environment_coverage_complete=not any(x.get("status")=="not_run" for x in self.environment_results),
                                       fps_reads=self.fps_reads), indent=2, default=str) + '\n')
        tmp.replace(self.out / 'results.json')

    def pause(self, seconds, reason):
        if seconds:
            self.event('Waiting', seconds=seconds, reason=reason)
            time.sleep(seconds)

    def enginecore_control_pause(self):
        # Keep --control-pause as a common minimum, including existing overrides.
        return max(self.options.control_pause, self.options.ec_control_pause)

    def run(self, label, args, check=False, timeout=None):
        self.counter += 1
        path = self.out / ('%04d-' % self.counter + re.sub(r'[^\w.-]', '_', label) + '.log')
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
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
        elapsed = time.monotonic() - start
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_user = usage_after.ru_utime - usage_before.ru_utime
        cpu_system = usage_after.ru_stime - usage_before.ru_stime
        text = data.decode(errors='replace')
        path.write_text(text)
        record = dict(command=args, returncode=rc, seconds=round(elapsed, 3),
                      cpu_user_seconds=round(cpu_user, 6), cpu_system_seconds=round(cpu_system, 6),
                      cpu_percent_one_core=round(100 * (cpu_user + cpu_system) / elapsed, 3),
                      cpu_scope='process and waited children; startup/shutdown included', log=path.name)
        if check and rc:
            raise RuntimeError(str(record))
        return record, text

    def discover(self):
        _, text = self.run('generated-commands', ['eg_dt_camera_config_get.sh', '--all-streaming-backends'], check=True)
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
            authorities = ([self.options.xauthority] if self.options.xauthority else [])
            authorities += re.findall(r'-auth\s+(\S+)', text)
            authorities += [str(Path.home() / '.Xauthority'), '/home/jetson/.Xauthority']
            displays = ([self.options.display] if self.options.display else
                        [':' + path.name[1:] for path in sorted(Path('/tmp/.X11-unix').glob('X[0-9]*'))])
            found = False
            for display in displays:
                for authority in authorities:
                    if not Path(authority).is_file():
                        continue
                    self.env.update(DISPLAY=display, XAUTHORITY=authority)
                    record, _ = self.run('check-local-display', ['xdpyinfo'], timeout=3)
                    if record['returncode'] == 0:
                        self.event('Display available', display=display, authority=authority)
                        found = True
                        break
                if found: break
            if not found:
                raise RuntimeError('Cannot open a local display; set --display/--xauthority')
            forwarded = self.options.forwarded_display or self.incoming_env.get('DISPLAY')
            if forwarded and not local_x11(forwarded):
                candidates = [self.options.forwarded_xauthority, self.incoming_env.get('XAUTHORITY')]
                sudo_user = self.incoming_env.get('SUDO_USER')
                if sudo_user:
                    candidates.append(str(Path(pwd.getpwnam(sudo_user).pw_dir)/'.Xauthority'))
                candidates += [str(Path.home()/'.Xauthority'), '/home/jetson/.Xauthority']
                for authority in candidates:
                    if not authority or not Path(authority).is_file(): continue
                    environment = dict(self.env, DISPLAY=forwarded, XAUTHORITY=authority)
                    with self.environment(environment):
                        record, _ = self.run('check-forwarded-display', ['xdpyinfo'], timeout=3)
                    if record['returncode'] == 0:
                        self.forwarded_env = environment
                        self.event('Forwarded X11 available', display=forwarded, authority=authority)
                        break
            if self.forwarded_env is None:
                self.environment_results.append(dict(context='forwarded-streams', status='not_run',
                    reason='No working forwarded X11 connection; use ssh -X and preserve DISPLAY/XAUTHORITY',
                    **({'passed': False} if self.options.require_forwarded_x11 else {})))
                self.event('Forwarded X11 unavailable', required=self.options.require_forwarded_x11)
                if self.options.require_forwarded_x11:
                    raise RuntimeError('A working SSH X11 connection is required; preserve DISPLAY and XAUTHORITY through sudo')
        if shutil.which('gst-inspect-1.0'):
            plugin_record, plugin_text = self.run('nvmm-plugin', ['gst-inspect-1.0', 'egv4l2camerasrc'])
            plugin_path = re.search(r'^\s*Filename\s+(.+)$', plugin_text, re.M)
            if plugin_record['returncode'] == 0 and plugin_path and Path(plugin_path[1]).is_file():
                self.event('NVMM plugin identity', path=plugin_path[1],
                           sha256=hashlib.sha256(Path(plugin_path[1]).read_bytes()).hexdigest())
        self.event('Test script', sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.run('dmesg-before', ['dmesg'])

    @contextmanager
    def environment(self, environment):
        previous = self.env
        self.env = environment
        try:
            yield
        finally:
            self.env = previous

    def read_frame_rate(self, camera):
        if not camera.enginecore:
            return None
        self.pause(self.enginecore_control_pause(), 'before EngineCore framerate read')
        record, text = self.run('framerate-' + camera.key,
            ['ECSwCtrl', '-i', 'i2c', '-d', camera.device, '-c', 'rf 0x210'])
        result = dict(key=camera.key, command=record, passed=False)
        self.fps_reads.append(result)
        try:
            if record['returncode']: raise ValueError('ECSwCtrl failed')
            value = parse_frame_rate(text)
        except ValueError as error:
            self.save()
            raise RuntimeError(str(error))
        result.update(passed=True, fps=value)
        self.fps_targets[camera.key] = value
        self.event('Camera framerate reference', camera=camera.name, fps=value, feature='rf 0x210')
        return value

    def test_environments(self, camera, group, label):
        expected_format = format_spec(group)
        headless = dict(self.env)
        headless.pop('DISPLAY', None)
        headless.pop('WAYLAND_DISPLAY', None)
        simulated = dict(self.env, DISPLAY='localhost:65530.0')
        contexts = [('local', self.env), ('forwarded-selection', simulated), ('no-display', headless)]
        reference_json = None
        passed = True
        for context, environment in contexts:
            for args in ([], ['--all-streaming-backends'], ['--json']):
                variant = 'json' if '--json' in args else 'all' if args else 'default'
                with self.environment(environment):
                    record, text = self.run(label+'-config-'+context+'-'+variant,
                                            ['eg_dt_camera_config_get.sh']+args)
                okay = record['returncode'] == 0
                reason = None
                try:
                    if variant == 'json':
                        data = json.loads(text)
                        entry = data['cameras']['port_'+str(camera.port)]
                        assert entry['video_device'] == camera.video and entry['status'] == 'connected'
                        assert data['camera_count'] == len(data['cameras'])
                        if reference_json is None: reference_json = data
                        assert data == reference_json
                    else:
                        current = next(c for c in parse_configuration(text) if c.key == camera.key)
                        candidate = next(g for g in current.groups if format_spec(g) == expected_format)
                        expected = set()
                        if context == 'local' and 'gst_nvmm' in group:
                            expected.add('gst_nvmm')
                        if 'gst' in group and (variant == 'all' or not expected): expected.add('gst')
                        actual = {key for key in ('gst', 'gst_nvmm') if key in candidate}
                        assert actual == expected, (actual, expected)
                        assert len(candidate.get('_gst_commands', [])) == len(expected)
                        assert candidate['monitor'] == group['monitor']
                except (ValueError, KeyError, StopIteration, AssertionError) as error:
                    okay, reason = False, str(error)
                self.environment_results.append(dict(key=camera.key, format=expected_format[2], context=context,
                    test='config-'+variant, passed=okay, reason=reason, record=record))
                passed = passed and okay
        # This rejection must occur before any attempt to access a camera.
        with self.environment(simulated):
            record, text = self.run(label+'-reject-forwarded-nvmm', ['rt_frame_monitor.py',
                '-d', '/dev/eg-regression-nonexistent', '--backend', 'nvmm', '--display'])
        okay = record['returncode'] == 2 and 'local X11' in text
        self.environment_results.append(dict(key=camera.key, format=expected_format[2],
            context='forwarded-selection', test='forced-nvmm-rejected', passed=okay, record=record))
        passed = passed and okay
        stream_contexts = [('headless', headless, group)]
        if self.forwarded_env is not None:
            with self.environment(self.forwarded_env):
                record, text = self.run(label+'-forwarded-config', ['eg_dt_camera_config_get.sh'])
            forwarded_camera = next(c for c in parse_configuration(text) if c.key == camera.key)
            remote_group = next(g for g in forwarded_camera.groups if format_spec(g) == expected_format)
            stream_contexts.append(('forwarded', self.forwarded_env, remote_group))
        for context, environment, selected_group in stream_contexts:
            selected_group = {k: list(v) if isinstance(v, list) else v for k,v in selected_group.items()}
            if context == 'headless':
                selected_group['monitor'] = [v for v in selected_group['monitor'] if v != '--display']
                for tool in ('gst', 'gst_nvmm'):
                    if tool not in selected_group: continue
                    selected_group[tool] = ['fakesink' if v in ('nv3dsink','autovideosink','ximagesink') else v
                                           for v in selected_group[tool]]
            for backend in ('classic', 'auto', 'nvmm'):
                if backend == 'nvmm' and 'gst_nvmm' not in selected_group: continue
                with self.environment(environment):
                    record = self.capture(camera, selected_group, 'monitor', label+'-'+context+'-'+backend,
                                          backend, display_context=context)
                self.environment_results.append(dict(key=camera.key, format=expected_format[2], context=context,
                    test='monitor-'+backend, passed=record['pass'], record=record))
                passed = passed and record['pass']
            for tool in ('gst','gst_nvmm'):
                if tool not in selected_group: continue
                with self.environment(environment):
                    record = self.capture(camera, selected_group, tool, label+'-'+context, display_context=context)
                self.environment_results.append(dict(key=camera.key, format=expected_format[2], context=context,
                    test=tool, passed=record['pass'], record=record))
                passed = passed and record['pass']
        self.event('Environment cases complete', camera=camera.name, format=expected_format[2], passed=passed)
        return passed

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

    def test_fixed_preview(self, camera, group, label):
        """Also cover the default mapping when generated commands request normalization."""
        if '--normalize' not in group.get('monitor', []):
            return True
        fixed = dict(group)
        fixed['monitor'] = [arg for arg in group['monitor'] if arg != '--normalize']
        if 'gst_nvmm' in group:
            fixed['gst_nvmm'] = ['normalize=false' if arg == 'normalize=true' else arg
                                 for arg in group['gst_nvmm']]
        cases = [('local', self.env, 'monitor', 'classic')]
        if 'gst_nvmm' in group:
            cases += [('local', self.env, 'monitor', 'nvmm'), ('local', self.env, 'gst_nvmm', None)]
        if self.forwarded_env is not None:
            cases.append(('forwarded', self.forwarded_env, 'monitor', 'classic'))
        passed = True
        for context, environment, tool, backend in cases:
            with self.environment(environment):
                record = self.capture(camera, fixed, tool,
                    label + '-fixed-' + context + '-' + (backend or tool), backend, display_context=context)
            self.environment_results.append(dict(key=camera.key, format=format_spec(group)[2],
                context=context, test='fixed-' + tool + '-' + (backend or 'default'),
                passed=record['pass'], record=record))
            passed = passed and record['pass']
            self.save()
        return passed

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

    def ec_control(self, camera, address, value, reboot=False):
        # ECSwCtrl can report a device error (!-128, etc.) with exit status 0.
        # Reboot is not retried here: the device may already be restarting.
        attempts = 1 if reboot else self.options.recoveries + 1
        for attempt in range(attempts):
            label = 'ec-reboot' if reboot else 'ec-write-' + address
            record, text = self.run(label, ['ECSwCtrl', '-i', 'i2c', '-d', camera.device,
                                           '-c', 'wu %s %d' % (address, value)])
            failed = (record.get('returncode', 0) != 0
                      or re.search(r'^\s*!\s*-?\d+', text, re.M)
                      or re.search(r'\b(?:error|failed)\b', text, re.I)
                      or not re.search(r'^\s*OK\s*$', text, re.M))
            if not failed:
                return True
            self.event('EngineCore control failed', camera=camera.name, address=address,
                       value=value, attempt=attempt + 1, response=text.strip(), log=record.get('log'))
            if reboot and record.get('returncode', 0) == 0 and text.strip() == '!-128':
                self.event('EngineCore reboot acknowledgement uncertain', camera=camera.name,
                           reason='Do not repeat reset; validate readback and subsequent capture')
                return False
            if attempt + 1 == attempts:
                raise RuntimeError('EngineCore control error: ' + text)
            self.pause(self.enginecore_control_pause(), 'before retrying rejected EngineCore control')

    def read_ec_format(self, camera):
        for attempt in range(self.options.recoveries + 1):
            record, text = self.run('ec-read-format', ['ECSwCtrl', '-i', 'i2c', '-d', camera.device, '-c', 'ru 0x260'])
            value = re.fullmatch(r'\s*(0x[0-9a-fA-F]+)\s+(\d+)\s*', text)
            if record.get('returncode', 0) == 0 and value and int(value[1], 16) == int(value[2]) and int(value[2]) in (20,21,22):
                self.pause(self.enginecore_control_pause(), 'EngineCore format read completed')
                return int(value[2])
            self.event('EngineCore format read failed', response=text.strip(), attempt=attempt+1)
            if attempt < self.options.recoveries:
                self.pause(self.enginecore_control_pause(), 'before retrying format read')
        raise RuntimeError('Cannot read actual EngineCore format: ' + text)

    def set_ec_format(self, key, code, reboot=False):
        camera = self.refresh(key)
        if not camera.enginecore:
            raise ValueError('Reboot is only supported for EngineCore cameras')
        cached = ec_code(Path(camera.sysfs, 'pixel_format').read_text())
        actual = self.read_ec_format(camera)
        if actual == code and cached == code and not reboot:
            return
        self.idle([c for c in self.discover() if c.connected and c.enginecore])
        if actual != code:
            for address, value in (('0x260', code), ('0x2F0', 0)):
                self.ec_control(camera, address, value)
                self.pause(self.enginecore_control_pause(), 'EngineCore control command completed')
        reboot_ack = self.ec_control(camera, '0x8', 1, reboot=True)
        self.pause(self.options.boot_wait, 'camera reboot')
        self.run('ec-unload', ['rmmod', 'eg_ec_mipi'], check=True)
        self.pause(self.enginecore_control_pause(), 'EngineCore module unloaded')
        self.run('ec-load', ['modprobe', 'eg_ec_mipi'], check=True)
        self.pause(self.options.probe_wait, 'camera and driver settling after probe')
        camera = self.refresh(key)
        actual = ec_code(Path(camera.sysfs, 'pixel_format').read_text())
        live = self.read_ec_format(camera)
        if actual != code or live != code:
            raise RuntimeError('Camera format mismatch: driver=%s camera=%s requested=%s' % (actual, live, code))
        self.event('EngineCore ready', camera=camera.name, key=key, code=code, recovery=reboot, reboot_acknowledged=reboot_ack)

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

    def capture(self, camera, group, tool, label, backend=None, display_context="local"):
        expected_width, expected_height, expected_format = format_spec(group)
        self.pause(self.options.stream_gap, 'before ' + tool + ' stream')
        if display_context == 'local' and tool != 'v4l2' and shutil.which('xset'):
            _, display_state = self.run(label + '-display-state', ['xset', '-q'], timeout=3)
            if 'Monitor is Off' in display_state or 'Monitor is Standby' in display_state or 'Monitor is Suspend' in display_state:
                self.run(label + '-wake-display', ['xset', 'dpms', 'force', 'on'], check=True, timeout=3)
                self.event('Display woken for capture', camera=camera.name)
        expected_fps = self.fps_targets.get(camera.key)
        fps_required = expected_fps is not None and display_context != 'forwarded'
        frames = (self.options.forwarded_frames if display_context == 'forwarded' else
                  max(self.options.frames, math.ceil(expected_fps * 2.25) + 1) if expected_fps else self.options.frames)
        timeout = (max(self.options.timeout, 15) if display_context == 'forwarded' else
                   max(self.options.timeout, frames / expected_fps + 6) if expected_fps else self.options.timeout)
        with tempfile.NamedTemporaryFile(prefix='eg-camera-test-', suffix='.raw') as raw:
            args = streaming_command(tool, group, frames,
                                     self.out / (label + '-monitor-data'), raw.name)
            if tool == 'monitor' and backend:
                args += ['--backend=' + backend]
            if tool == 'v4l2': args.append('--verbose')
            record, text = self.run(label + '-' + tool, args, timeout=timeout)
            passed = record['returncode'] == 0
            if tool == 'v4l2':
                record['corrupt_buffers'] = len(re.findall(
                    r'cap dqbuf:[^\r\n]*\([^\r\n)]*\berror\b', text))
                passed = passed and record['corrupt_buffers'] == 0
                _, actual = self.run(label + '-effective-format',
                                    ['v4l2-ctl', '-d', camera.video, '--get-fmt-video'])
                negotiated = parse_negotiated_format(actual)
                image_size = negotiated['image_size']
                length = Path(raw.name).stat().st_size
                record.update(bytes=length, expected_bytes=image_size * frames,
                              effective_format=negotiated['format'],
                              effective_width=negotiated['width'], effective_height=negotiated['height'])
                passed = passed and image_size > 0 and length == image_size * frames
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
                reported_frames = [int(x) for x in re.findall(r'frame=\s*(\d+)', text)]
                record['frames_reported'] = max(reported_frames) + 1 if reported_frames else 0
                passed = passed and record['frames_reported'] >= frames
                corrupt_counts = [int(x) for x in re.findall(r'\bcorrupt=\s*(\d+)', text)]
                record['corrupt_buffers'] = max(corrupt_counts) if corrupt_counts else None
                if record['corrupt_buffers'] is not None:
                    passed = passed and record['corrupt_buffers'] == 0
                selected = re.search(r'BACKEND requested=(\w+) selected=(\w+) reason=(.*)', text)
                record['requested_backend'] = backend or 'auto'
                record['actual_backend'] = selected[2] if selected else None
                record['backend_reason'] = selected[3] if selected else None
                if record['actual_backend'] == 'nvmm':
                    summaries = sorted((self.out / (label + '-monitor-data')).glob('nvmm-*/summary.json'))
                    if len(summaries) != 1:
                        passed = False
                        record['metadata_error'] = 'Missing or ambiguous NVMM summary'
                    else:
                        metadata = json.loads(summaries[0].read_text())
                        record['nvmm_metadata'] = metadata
                        passed = (passed and metadata.get('nvmm_caps') is True
                                  and metadata.get('nvmm_allocator') is True
                                  and metadata.get('pixel_analysis') is False
                                  and metadata.get('frames') == frames
                                  and metadata.get('failure') is None)
                if backend:
                    expected_backend = backend if backend != 'auto' else ('nvmm' if 'gst_nvmm' in group else 'classic')
                    passed = passed and record['actual_backend'] == expected_backend

            else:
                record['buffers_reported'] = len(re.findall(r'last-message = chain', text))
                passed = passed and 'Got EOS' in text and record['buffers_reported'] >= frames
                record['corrupt_buffers'] = len(re.findall(
                    r'last-message = chain[^\r\n]*\bflags:[^,\r\n]*\bcorrupted\b', text))
                passed = passed and record['corrupt_buffers'] == 0
        record['functional_pass'] = bool(passed)
        record.update(requested_frames=frames, display_context=display_context)
        measured = stream_cadence(tool, text)
        record['cadence'] = measured
        if expected_fps is not None:
            rate_ok = all(rate_matches(measured.get(key), expected_fps, self.options.fps_tolerance)
                          for key in ('capture', 'processing'))
            record.update(reference_fps=expected_fps, fps_tolerance=self.options.fps_tolerance, fps_match=rate_ok,
                          fps_required=fps_required, fps_policy='strict' if fps_required else 'observational: forwarded X11 rendering')
            if fps_required:
                passed = passed and rate_ok
        record['pass'] = bool(passed)
        self.event('Capture complete', camera=camera.name, format=expected_format,
                   tool=tool, backend=record.get('actual_backend'), context=display_context, passed=bool(passed),
                   reference_fps=expected_fps, fps_required=fps_required,
                   capture_fps=measured.get('capture', {}).get('steady_fps'),
                   processing_fps=measured.get('processing', {}).get('steady_fps'),
                   cpu_percent_one_core=record.get('cpu_percent_one_core'), seconds=record['seconds'], log=record['log'])
        return record

    def test_group(self, key, expected_format, code=None, tools=('v4l2', 'monitor', 'gst', 'gst_nvmm')):
        attempts = []
        result = dict(key=key, format=expected_format, attempts=attempts, passed=False)
        self.results.append(result)
        for attempt in range(self.options.recoveries + 1):
            camera = self.refresh(key)
            group = next(g for g in camera.groups if format_spec(g)[2] == expected_format)
            self.read_frame_rate(camera)
            label = '%s-%s-attempt%d' % (key, re.sub(r'\W', '_', expected_format), attempt)
            entry = dict(number=attempt, camera=camera.name, enumeration=self.enumerate_formats(camera), tools={})
            attempts.append(entry)
            for tool in tools:
                if tool == 'monitor':
                    if tool not in group:
                        entry['tools'][tool] = {'pass': False, 'reason': 'Missing monitor command'}
                        break
                    for backend in ('classic', 'nvmm', 'auto'):
                        name = 'monitor-' + backend
                        if backend == 'nvmm' and 'gst_nvmm' not in group:
                            required = getattr(self.options, 'require_nvmm', False) and expected_format.strip() in ('YUYV', 'Y16', 'Y14', 'Y16 -BE', 'AR24', 'AB24')
                            entry['tools'][name] = dict(status='failed' if required else 'not applicable',
                                reason='NVMM plugin/format/display path unavailable', **({'pass': False} if required else {}))
                            continue
                        entry['tools'][name] = self.capture(camera, group, 'monitor', label + '-' + backend, backend)
                        self.save()
                        if not entry['tools'][name].get('functional_pass', entry['tools'][name]['pass']):
                            break
                    if any(not x.get('functional_pass', x.get('pass', x.get('status') == 'not applicable')) for x in entry['tools'].values()):
                        break
                    continue
                if tool == 'gst_nvmm' and tool not in group:
                    required = getattr(self.options, 'require_nvmm', False) and expected_format.strip() in ('YUYV', 'Y16', 'Y14', 'Y16 -BE', 'AR24', 'AB24')
                    entry['tools'][tool] = dict(status='failed' if required else 'not applicable',
                        reason='NVMM plugin/format/display path unavailable', **({'pass': False} if required else {}))
                    continue
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
                if not entry['tools'][tool].get('functional_pass', entry['tools'][tool]['pass']):
                    break
            passed = all(x.get('pass', x.get('status') == 'not applicable')
                         for x in entry['tools'].values())
            functional = all(x.get('functional_pass', x.get('pass', x.get('status') == 'not applicable'))
                             for x in entry['tools'].values())
            if functional:
                environments_ok = self.test_environments(camera, group, label) if len(tools) > 1 else True
                if len(tools) > 1:
                    fixed_ok = self.test_fixed_preview(camera, group, label)
                    environments_ok = environments_ok and fixed_ok
                result['passed'] = bool(passed and environments_ok)
                self.save()
                return result['passed']
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
                self.read_frame_rate(current)
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
            original_code = self.read_ec_format(camera) if camera.enginecore else None
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
                    codes = [original_code] if getattr(self.options, 'current_format_only', False) else [original_code] + [x for x in available_codes if x != original_code]
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
        self.event('Finished', passed=sum(x['passed'] for x in self.results), total=len(self.results),
                   environment_checks=len(self.environment_results),
                   coverage_complete=not any(x.get('status') == 'not_run' for x in self.environment_results))
        return 0 if all(x['passed'] for x in self.results + self.register_results + self.xeneth_results +
                           [x for x in self.environment_results if 'passed' in x]) else 1


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True, help='New directory for all logs and JSON results')
    p.add_argument('--only', action='append', default=[], help='Camera name or sysfs ID; repeat to select several')
    p.add_argument('--registers-only', action='store_true', help='Only read control registers; no video, format changes or GUI')
    p.add_argument('--xeneth-minimal', default='egXenethMinimal', help='ARM64 reference client built with the Xeneth SDK packet codec')
    p.add_argument('--xeneth-reads', type=int, default=20)
    p.add_argument('--skip-xeneth', action='store_true', help='Explicitly omit the new GenCP interface tests for legacy driver packages')
    p.add_argument('--frames', type=int, default=60, help='Minimum frames; extended if needed for steady framerate measurement')
    p.add_argument('--forwarded-frames', type=int, default=60, help='Frames per forwarded X11 functional stream; cadence is observational')
    p.add_argument('--require-nvmm', action='store_true', help='Fail if a supported camera format lacks the NVMM pipeline')
    p.add_argument('--current-format-only', action='store_true', help='Test only the connected camera format; do not cycle EC formats')
    p.add_argument('--timeout', type=float, default=10)
    p.add_argument('--control-pause', type=float, default=2,
                   help='Minimum control-command pause in seconds for all cameras')
    p.add_argument('--ec-control-pause', type=float, default=5,
                   help='EngineCore control-command pause; the larger of this and --control-pause is used')
    p.add_argument('--boot-wait', type=float, default=5)
    p.add_argument('--probe-wait', type=float, default=5)
    p.add_argument('--stream-gap', type=float, default=3)
    p.add_argument('--recoveries', type=int, default=2, help='Maximum camera reboots per failed EngineCore format')
    p.add_argument('--display', help='Local X11 display; otherwise discover a working local session')
    p.add_argument('--forwarded-display', help='Forwarded X11 DISPLAY; otherwise use the incoming environment')
    p.add_argument('--forwarded-xauthority', help='Authority file for the forwarded X11 connection')
    p.add_argument('--require-forwarded-x11', action='store_true', help='Fail if real forwarded-X11 streams cannot be tested')
    p.add_argument('--fps-tolerance', type=float, default=0.03, help='Allowed relative deviation from EngineCore rf 0x210 (default 3%%)')
    p.add_argument('--xauthority')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.frames <= 0 or args.forwarded_frames <= 0 or args.timeout <= 0 or args.recoveries < 0 or not 1 <= args.xeneth_reads <= 1000000:
        p.error('frames/timeout must be positive; recoveries must be nonnegative')
    if min(args.control_pause, args.ec_control_pause, args.boot_wait, args.probe_wait, args.stream_gap) < 0:
        p.error('Delays must be nonnegative')
    if not 0 <= args.fps_tolerance < 1:
        p.error('fps-tolerance must be in [0, 1)')
    if args.display and not local_x11(args.display):
        p.error('--display must be local; use --forwarded-display for SSH X11')
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
