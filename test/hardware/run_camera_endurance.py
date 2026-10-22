#!/usr/bin/env python3
"""Paced start/stop and concurrent stream endurance, with bounded cleanup."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from run_camera_regression import parse_configuration, parse_negotiated_format, format_spec, register_read_plan, validate_register_read

KERNEL_ERRORS=re.compile(r'BUG:|Oops:|Kernel panic|uncorr_err|corr_err|CHANSEL_(?:NOMATCH|SHORT_FRAME)|CSIMUX_STREAM|uncorrectable|capture.*timed out',re.I)

def boot_seconds():
    return time.clock_gettime(getattr(time, 'CLOCK_BOOTTIME', time.CLOCK_MONOTONIC))

def classify_kernel_lines(lines, controlled_stops):
    errors=[];observations=[]
    for line in lines:
        if not KERNEL_ERRORS.search(line):continue
        stamp=re.match(r'\[\s*([0-9.]+)\]',line)
        unknown=re.search(r'corr_err: discarding frame \d+, status 0, flags: 0, err_data 0x0+\b',line)
        # camrtc-capture.h defines status 0 as not executed/still in progress;
        # its other fields are undefined. Keep these traces as observations only
        # at a measured, controlled stop. Mid-stream/other statuses still fail.
        boundary=stamp and any(abs(float(stamp[1])-stop)<=.5 for stop in controlled_stops)
        (observations if unknown and boundary else errors).append(line)
    return errors,observations

def stop_process(process):
    for sig,delay in ((signal.SIGINT,2),(signal.SIGTERM,1),(signal.SIGKILL,1)):
        if process.poll() is not None:return
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:return
        try:process.wait(timeout=delay);return
        except subprocess.TimeoutExpired:pass
    raise RuntimeError('Capture process did not stop')

def stream_command(camera,frames):
    # Reapply the read-back format on every open, as in the generated functional
    # command. No assumption that sensor setup survives a previous stream close.
    return ['v4l2-ctl','-d',camera.video,camera.stream_spec,'--stream-mmap',
            '--stream-count='+str(frames),'--stream-to=/dev/null']

def run_window(commands,seconds,folder,stall_seconds=15):
    """Launch streams together, require them to stay alive, then stop all children."""
    children=[];started=time.monotonic();reached=False;activity={};sizes={};reason='duration-completed';stops=[]
    try:
        for i,command in enumerate(commands):
            path=folder/('stream-%02d.log'%i);handle=path.open('w')
            try:process=subprocess.Popen(command,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
            except BaseException:
                handle.close();raise
            children.append((process,handle,path))
        while time.monotonic()-started < seconds:
            if any(p.poll() is not None for p,_,_ in children):
                reason='process-exited-before-deadline';break
            stalled=False
            for p,_,path in children:
                size=path.stat().st_size
                if size!=sizes.get(p.pid,0):activity[p.pid]=time.monotonic()
                sizes[p.pid]=size
                if time.monotonic()-activity.get(p.pid,started)>stall_seconds:stalled=True
            if stalled:
                reason='no-stream-progress';break
            time.sleep(min(.1,max(0,seconds-(time.monotonic()-started))))
        reached=time.monotonic()-started>=seconds
    finally:
        cleanup_errors=[]
        for p,handle,_ in children:
            stops.append(boot_seconds())
            try:stop_process(p)
            except RuntimeError as error:cleanup_errors.append(str(error))
            finally:handle.close()
        if cleanup_errors:raise RuntimeError('; '.join(cleanup_errors))
    elapsed=time.monotonic()-started
    records=[]
    for index,(command,(p,_,path)) in enumerate(zip(commands,children)):
        text=path.read_text(errors='replace');frames=text.count('<')
        clean_exit=p.returncode in (0,-signal.SIGINT)
        records.append(dict(command=command,seconds=round(elapsed,3),frames=frames,
                            measured_fps=round(frames/elapsed,3),returncode=p.returncode,
                            log=path.name,stop_time=stops[index],
                            reason='unexpected-exit-status' if not clean_exit else reason if frames else 'no-frames',
                            passed=bool(reached and frames and clean_exit and reason=='duration-completed')))
    return records

def kernel_delta(before,after):
    before=before.splitlines();after=after.splitlines()
    if after[:len(before)]!=before:
        return None # Wrapped/cleared ring: no unqualified "no new errors" claim.
    return after[len(before):]

def validate_visit(visit,cameras,l4t):
    errors=[]
    if visit['l4t']!=l4t:errors.append('Unexpected L4T: '+l4t)
    for expected in visit['cameras']:
        matches=[c for c in cameras if c.port==expected['port'] and c.connected]
        if len(matches)!=1:errors.append('Expected camera missing at port '+str(expected['port']));continue
        camera=matches[0];w,h,_=format_spec(camera.groups[0])
        if f'{w}x{h}'!=expected['resolution']:errors.append('Resolution mismatch at port '+str(camera.port))
        name=camera.name.lower()
        family=expected['family']
        if family=='dione_ir':ok='dione' in name
        else:ok=family in name
        if not ok:errors.append('Camera family mismatch at port '+str(camera.port))
    return errors

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=900)
    p.add_argument('--cycles',type=int,default=20)
    p.add_argument('--frames',type=int,default=30)
    p.add_argument('--gap',type=float,default=3)
    p.add_argument('--only',action='append',default=[])
    p.add_argument('--plan',type=Path);p.add_argument('--visit')
    p.add_argument('--min-fps',type=float,default=0,help='Explicit measured-rate acceptance threshold, not inferred from DT')
    a=p.parse_args()
    if os.geteuid()!=0:p.error('Run as root on the target')
    if min(a.seconds,a.frames)<=0 or min(a.cycles,a.gap,a.min_fps)<0:p.error('Invalid time/count')
    if bool(a.plan)!=bool(a.visit):p.error('--plan and --visit must be used together')
    a.output.mkdir(parents=True,exist_ok=False)
    report=dict(status='running',cycles=[],streams=[],controls=[],errors=[],script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    def save():
        temporary=a.output/'results.json.tmp';temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(a.output/'results.json')
    def output(args,timeout=15):return subprocess.check_output(args,universal_newlines=True,stderr=subprocess.STDOUT,timeout=timeout)
    lock=open('/run/lock/eg-camera-regression.lock','w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        config=output(['eg_dt_camera_config_get.sh']);(a.output/'inventory.log').write_text(config)
        cameras=[c for c in parse_configuration(config) if c.connected and (not a.only or c.key in a.only or c.name in a.only)]
        if not cameras:raise RuntimeError('No selected camera')
        if any('ilumos' in c.device for c in cameras) and any('microlynx' in c.device for c in cameras):raise RuntimeError('Shared iLumos/MicroLynx supply: use separate sessions')
        if a.plan:
            plan=json.loads(a.plan.read_text());visit=next(v for v in plan['visits'] if v['id']==a.visit)
            release=Path('/etc/nv_tegra_release').read_text();match=re.search(r'R(\d+).*REVISION:\s*([\d.]+)',release)
            if not match:raise RuntimeError('Unrecognized L4T banner')
            l4t=match[1]+'.'+match[2]
            if l4t.endswith('.0') and l4t[:-2]==visit['l4t']:l4t=l4t[:-2]
            errors=validate_visit(visit,cameras,l4t)
            if errors:raise RuntimeError('; '.join(errors))
            cameras=[c for c in cameras if c.port in {x['port'] for x in visit['cameras']}]
            report['visit']=visit
        report['cameras']=[vars(c) for c in cameras]
        for camera in cameras:
            busy=subprocess.run(['fuser',camera.video],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
            if busy.returncode!=1:raise RuntimeError('Camera busy or idle state unknown: '+camera.video)
            text=output(['v4l2-ctl','-d',camera.video,'--get-fmt-video','--list-formats-ext'])
            (a.output/(camera.key+'-format.log')).write_text(text)
            current=parse_negotiated_format(text)
            if not all(current[k] for k in ('width','height','format')):raise RuntimeError('Cannot determine effective format')
            camera.stream_spec='--set-fmt-video=width=%d,height=%d,pixelformat=%s' % (current['width'],current['height'],current['format'])
        before=output(['dmesg']);(a.output/'dmesg-before.log').write_text(before)
        for cycle in range(a.cycles):
            for camera in cameras:
                time.sleep(a.gap);command=stream_command(camera,a.frames)
                name=f'cycle-{cycle:02d}-{camera.key}.log';timed_out=False
                with (a.output/name).open('w') as log:
                    pcap=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    try:
                        try:pcap.wait(timeout=15)
                        except subprocess.TimeoutExpired:timed_out=True
                    finally:
                        stopped=boot_seconds();stop_process(pcap)
                text=(a.output/name).read_text(errors='replace');passed=not timed_out and pcap.returncode==0 and text.count('<')==a.frames
                report['cycles'].append(dict(camera=camera.key,cycle=cycle,passed=passed,log=name,timed_out=timed_out,stop_time=stopped));save()
                if not passed:raise RuntimeError('Start/stop capture failed: '+camera.key)
        time.sleep(a.gap)
        report['streams']=run_window([stream_command(c,0) for c in cameras],a.seconds,a.output)
        for record in report['streams']:record['passed'] &= record['measured_fps']>=a.min_fps
        for camera in cameras:
            for check in register_read_plan(camera):
                time.sleep(2);text=output(check['command']);passed,value=validate_register_read(check,0,text)
                report['controls'].append(dict(camera=camera.key,name=check['name'],value=value,passed=passed))
        after=output(['dmesg']);(a.output/'dmesg-after.log').write_text(after)
        delta=kernel_delta(before,after)
        if delta is None:report['errors'].append('Kernel log wrapped/cleared: error review is incomplete')
        else:
            errors,observations=classify_kernel_lines(delta,[x['stop_time'] for key in ('cycles','streams') for x in report[key]])
            report['errors'] += errors;report['kernel_stop_observations']=observations
        report['status']='passed' if not report['errors'] and all(x['passed'] for key in ('cycles','streams','controls') for x in report[key]) else 'failed'
    except (Exception,KeyboardInterrupt) as error:
        report['status']='failed';report['errors'].append(repr(error))
    finally:
        if (a.output/'dmesg-before.log').exists() and not (a.output/'dmesg-after.log').exists():
            try:(a.output/'dmesg-after.log').write_text(output(['dmesg'],timeout=3))
            except Exception as error:report['errors'].append('Cannot collect final kernel log: '+repr(error))
        save();lock.close()
    print(json.dumps(dict(status=report['status'],errors=report['errors']),indent=2))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    raise SystemExit(main())
