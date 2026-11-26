"""Bounded target stop tests. Never install, replace or compare driver packages."""
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from run_camera_regression import corruption_policy, format_spec, v4l2_buffers, raw_capture_directory
from v4l2_contract import parse_current


def integrity(camera, buffers):
    bad = [i for i, b in enumerate(buffers) if b.get('error', b.get('corrupt', False))]
    return corruption_policy(camera.name, len(bad), bad[0] if bad else None, bad[-1] if bad else None)


def inspect_pixels(path, layout, fmt, reference, folder, label, allow_partial=False):
    from camera_pixel_oracles import check_frame
    size = layout['sizeimage']
    if size <= 0:
        raise ValueError('Invalid frame size')
    count, tail = divmod(Path(path).stat().st_size, size)
    checks = []
    last_good = None
    digest = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for index in range(count):
            data = stream.read(size)
            digest.update(data)
            result = check_frame(data, fmt, layout['width'], layout['height'], layout['bytesperline'], reference)
            if reference['kind'] == 'rgb':
                result['alpha_passed'] = result['alpha_range'] == [255, 255]
                result['passed'] = result['passed'] and result['alpha_passed']
            result.update(ordinal=index+1, sha256=hashlib.sha256(data).hexdigest())
            if result['passed']:
                last_good = data
            # Retain first, last and the first failing frame, including padding.
            if index in (0, count-1) or (not result['passed'] and all(c['passed'] for c in checks)):
                artifact = folder/(label+'-frame-%d.raw.gz'%(index+1))
                with gzip.open(str(artifact), 'wb') as out:
                    out.write(data)
                result['artifact'] = artifact.name
            checks.append(result)
        partial = stream.read()
    prefix_ok = not tail or (last_good is not None and partial == last_good[:tail])
    return dict(frames=checks, complete_frames=count, partial_bytes=tail,
                partial_prefix_matches=prefix_ok, file_complete=tail == 0,
                strict_file_passed=tail == 0 and bool(checks) and all(c['passed'] for c in checks),
                sha256_complete_frames=digest.hexdigest(),
                first_frame_passed=checks[0]['passed'] if checks else False,
                last_frame_passed=checks[-1]['passed'] if checks else False,
                passed=bool(checks) and all(c['passed'] for c in checks) and prefix_ok and (allow_partial or not tail))


class StopSuite:
    def __init__(self, runner):
        self.r = runner
        self.folder = runner.out/'stop-tests'
        self.folder.mkdir(exist_ok=False)
        self.report = dict(runs=[], references=[], no_image=[], formats=[], completed=False,
                           coverage_complete=False, passed=False)
        self.serial = 0
        self.binary = self.folder/'capture_stop_audit'

    def __getattr__(self, name):
        return getattr(self.r, name)

    def save(self):
        (self.folder/'results.json').write_text(json.dumps(self.report, indent=2, default=str)+'\n')
        self.r.save()

    def label(self, camera, mode):
        self.serial += 1
        return '%04d-%s-%s' % (self.serial, camera.key, mode)

    def layout(self, camera):
        _, text = self.r.run(camera.key+'-stop-layout', ['v4l2-ctl','-d',camera.video,'--get-fmt-video'], check=True)
        return parse_current(text)

    def set_format(self, camera, spec):
        self.r.run(camera.key+'-stop-format', ['v4l2-ctl','-d',camera.video,
            '--set-fmt-video=width=%d,height=%d,pixelformat=%s' % (spec['width'],spec['height'],spec['format'])], check=True)

    def audit(self, camera, count, hold, raw, label):
        row, text = self.r.run(label, [str(self.binary), camera.video, str(count), '4', str(hold), str(raw), '-', '1'],
                               timeout=max(20, self.options.timeout))
        events = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        summary = next((e for e in events if e.get('event') == 'summary'), {})
        buffers = [e for e in events if e.get('event') == 'dqbuf']
        policy = integrity(camera, buffers)
        self.r.qualify_kernel(row, camera, policy)
        after = next((e for e in events if e.get('event') == 'post_streamoff_dqbuf'), {})
        result = dict(mode='audit', camera=camera.name, key=camera.key, command=row, summary=summary,
                      buffers=buffers, integrity=policy, events=events,
                      passed=row['returncode'] in (0,2) and summary.get('valid_frames') == count
                      and policy['accepted'] and after.get('returncode') == -1)
        return result

    @staticmethod
    def reap(process):
        for sig, delay in ((signal.SIGINT, 2), (signal.SIGTERM, 1), (signal.SIGKILL, 2)):
            if process.poll() is not None:
                return
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=delay)
                return
            except subprocess.TimeoutExpired:
                pass
        raise RuntimeError('Capture process could not be reaped: pid=%d' % process.pid)

    def processes(self, cameras, mode, paths=None, hook=None):
        """A single kernel window for simultaneous captures; never guess attribution."""
        label = self.label(cameras[0], mode)
        kernel = self.r.kernel
        if kernel:
            kernel.collect(label+'-before')
        processes, files, records = [], [], []
        started = time.monotonic()
        interrupted_at = None
        try:
            for index, camera in enumerate(cameras):
                path = self.folder/(label+'-'+str(index)+'.log')
                out = path.open('w');files.append(out)
                raw = str(paths[index]) if paths else '/dev/null'
                args = ['v4l2-ctl','-d',camera.video,'--stream-mmap','--verbose','--stream-to='+raw]
                if mode == 'finite':
                    args += ['--stream-count='+str(self.options.stop_frames)]
                process = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, env=self.env, start_new_session=True)
                processes.append(process)
                records.append(dict(camera=camera.name, key=camera.key, pid=process.pid, command=args, log=str(path.relative_to(self.r.out))))
            if mode != 'finite':
                if hook:
                    hook(processes[0])
                else:
                    time.sleep(0.015 if mode == 'early-sigint' else 0.45)
                interrupted_at = time.monotonic()
                for process in processes:
                    if process.poll() is not None:
                        raise RuntimeError('Continuous capture exited before requested interruption')
                    os.killpg(process.pid, signal.SIGINT)
            deadline = time.monotonic()+self.options.timeout
            for process, row in zip(processes, records):
                row['returncode'] = process.wait(timeout=max(.01,deadline-time.monotonic()))
                if interrupted_at is not None:
                    row['signal_to_exit_seconds'] = time.monotonic()-interrupted_at
        except subprocess.TimeoutExpired:
            for row in records:
                row['timeout'] = True
        finally:
            try:
                for process in processes:
                    self.reap(process)
            finally:
                for out in files:
                    out.close()
                window = kernel.collect(label) if kernel else dict(complete=False,clean=False,errors=[],unqualified_messages=0,affects_test_result=False,reason='No kernel reader')
        for camera, row in zip(cameras, records):
            text = (self.r.out/row['log']).read_text()
            buffers = v4l2_buffers(text)
            row['buffers'] = buffers
            row['integrity'] = integrity(camera, buffers)
            row['passed'] = (not row.get('timeout') and row.get('returncode') in ((0,) if mode == 'finite' else (0,-signal.SIGINT,130))
                             and row['integrity']['accepted'])
            if mode == 'finite':
                row['passed'] = row['passed'] and sum(not b['corrupt'] for b in buffers) == self.options.stop_frames
            elif mode != 'early-sigint':
                row['passed'] = row['passed'] and bool(buffers)
        if len(cameras) == 1 and records:
            from kernel_capture_log import qualify
            qualify(window, cameras[0].name, records[0]['integrity'])
        result = dict(label=label, mode=mode, cameras=records, simultaneous=len(cameras)>1,
                      seconds=time.monotonic()-started, kernel=window,
                      passed=bool(records) and all(r['passed'] for r in records))
        self.report['runs'].append(result);self.save()
        return result

    def capture_reference(self, camera, fmt, label, folder, reference):
        layout = self.layout(camera)
        if layout['format'] != fmt.strip():
            raise RuntimeError('Reference format does not match active format')
        count = self.options.stop_frames
        captures = []
        for mode, hold in [('immediate',0), ('drained',1000)]:
            with tempfile.NamedTemporaryFile(prefix='eg-stop-', suffix='.raw', dir=raw_capture_directory(layout['sizeimage']*count)) as raw:
                row = self.audit(camera, count, hold, raw.name, label+'-'+mode)
                pixels = inspect_pixels(raw.name, layout, fmt, reference, folder, label+'-'+mode)
                pixels['passed'] = pixels['passed'] and pixels['complete_frames'] == count
                captures.append(dict(mode=mode, capture=row, pixels=pixels, passed=row['passed'] and pixels['passed']))
        with tempfile.NamedTemporaryFile(prefix='eg-stop-sigint-', suffix='.raw', dir=raw_capture_directory(layout['sizeimage']*60)) as raw:
            row = self.processes([camera], 'sigint', [raw.name])
            pixels = inspect_pixels(raw.name, layout, fmt, reference, folder, label+'-sigint', allow_partial=True)
            captures.append(dict(mode='sigint', capture=row, pixels=pixels, passed=row['passed'] and pixels['passed']))
        return dict(passed=all(c['passed'] for c in captures), captures=captures, layout=layout,
                    last_frames_passed=all(c['pixels']['last_frame_passed'] for c in captures),
                    note='A partial SIGINT file is recorded separately; complete pixels and partial prefix must still match')

    def no_images(self, camera):
        record = dict(camera=camera.name, key=camera.key)
        self.report['no_image'].append(record)
        if not Path(camera.device).name.startswith('ilumos-'):
            record.update(status='not_applicable', reason='No qualified volatile acquisition-stop control for this family')
            self.save();return
        from camera_pixel_oracles import Controls
        control = Controls(self, camera, camera.key+'-no-images')
        original = control.read(0x50000a20)
        record['original_acquisition'] = original
        record['restored'] = False
        try:
            with tempfile.NamedTemporaryFile(prefix='eg-no-images-', suffix='.raw') as raw:
                def hook(process):
                    time.sleep(.5)
                    control.write(0x50000a00,2)
                    time.sleep(.4);first=Path(raw.name).stat().st_size
                    time.sleep(.5);last=Path(raw.name).stat().st_size
                    record['stalled'] = dict(bytes_before=first,bytes_after=last,interval_seconds=.5)
                    if first != last or not first or process.poll() is not None:
                        raise RuntimeError('Could not establish an active capture waiting without images')
                stopped = self.processes([camera], 'no-images-sigint', [raw.name], hook=hook)
                restart = self.audit(camera, self.options.stop_frames, 0, '/dev/null', camera.key+'-no-images-restart')
                record.update(stop=stopped,restart=restart,passed=stopped['passed'] and restart['passed'])
        finally:
            control.write(0x50000a00,1 if original&1 else 2)
            record['restored'] = (control.read(0x50000a20)&1) == (original&1)
            self.save()
            if not record['restored']:
                raise RuntimeError('Acquisition state not restored')

    def execute(self, cameras):
        if self.l4t_major is not None and self.l4t_major < 35:
            self.report.update(status='not_run',reason='VI5 shutdown qualification requires L4T 35+; legacy findings are unchanged')
            self.save();return True
        source = Path(__file__).resolve().with_name('capture_stop_audit.c')
        self.r.run('compile-stop-audit', ['gcc','-std=gnu11','-O2','-Wall','-Wextra','-Werror',str(source),'-o',str(self.binary)], check=True)
        self.report['audit_source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.report['audit_binary_sha256'] = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        supported = [c for c in cameras if c.groups]
        self.report['selected'] = [dict(camera=c.name,key=c.key,video=c.video) for c in cameras]
        for camera in supported:
            original = self.layout(camera)
            specs = [original] if camera.enginecore or self.options.current_format_only else [dict(zip(('width','height','format'),format_spec(g))) for g in camera.groups]
            unique = []
            for spec in specs:
                if spec not in unique:
                    unique.append(spec)
            try:
                for spec in unique:
                    self.set_format(camera,spec)
                    prime = self.audit(camera,1,0,'/dev/null',camera.key+'-prime-'+spec['format'].strip())
                    self.report['formats'].append(dict(key=camera.key,requested=spec,prime=prime))
                    label = self.label(camera,re.sub(r'\W','_',spec['format']))
                    folder = self.folder/label;folder.mkdir()
                    reference = dict(camera=camera.name,key=camera.key,format=spec['format'])
                    self.report['references'].append(reference)
                    from camera_pixel_oracles import execute_reference
                    try:
                        execute_reference(self,camera,spec['format'],label,folder,reference)
                        self.r.event('Stop reference checked',camera=camera.name,format=spec['format'],
                                     passed=reference.get('passed'),status=reference.get('status'),restored=reference.get('restored'))
                    finally:
                        self.save()
                        if reference.get('restored') is False:
                            raise RuntimeError('Pattern restoration failed; abort stop suite')
            finally:
                self.set_format(camera,original)
                restored = self.audit(camera,1,0,'/dev/null',camera.key+'-restore-format')
                self.report['formats'].append(dict(key=camera.key,restoration=True,requested=original,prime=restored))
                if self.layout(camera)['format'] != original['format']:
                    raise RuntimeError('Original format not restored')
            self.no_images(camera)
        n = self.options.stop_cycles
        for camera in supported:
            for mode,count in [('finite',2*n),('sigint',n),('early-sigint',max(1,math.ceil(n/2)))]:
                for _ in range(count):
                    self.processes([camera],mode)
        if len(supported)>1:
            for _ in range(n):
                self.processes(supported,'finite')
        else:
            self.report['simultaneous'] = dict(status='not_applicable',reason='Only one supported selected camera')
        self.report['completed'] = True
        self.report['process_captures'] = sum(len(r['cameras']) for r in self.report['runs'])
        self.report['kernel_message_windows'] = sum(bool(r['kernel']['errors']) for r in self.report['runs'])
        self.report['coverage_complete'] = (len(supported)==len(cameras) and bool(supported)
            and all(r.get('passed') is True for r in self.report['references']))
        self.report['passed'] = (bool(supported) and len(supported)==len(cameras)
            and all(r['passed'] for r in self.report['runs'])
            and all(r['prime']['passed'] for r in self.report['formats'])
            and all(r.get('passed',r.get('status')=='not_applicable') for r in self.report['no_image'])
            and all(r.get('passed',r.get('status')=='not_run') for r in self.report['references']))
        self.save()
        self.r.event('Stop campaign completed',passed=self.report['passed'],
                     coverage_complete=self.report['coverage_complete'],process_captures=self.report['process_captures'],
                     kernel_message_windows=self.report['kernel_message_windows'])
        return self.report['passed']
