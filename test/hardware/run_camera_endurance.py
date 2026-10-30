#!/usr/bin/env python3
"""Paced start/stop and concurrent stream endurance, with bounded cleanup."""
import argparse
import fcntl
import hashlib
import json
import math
import resource
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from run_camera_regression import parse_configuration, parse_negotiated_format, format_spec, register_read_plan, validate_register_read, streaming_command, stream_cadence, parse_frame_rate, rate_matches

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

def build_nvmm_command(cameras, configuration, frames):
    """Reuse generated hardware commands; replace rendering with headless probes."""
    if len(cameras) < 2:
        return None, {}, 'At least two connected cameras are required'
    generated={c.key:c for c in parse_configuration(configuration) if c.connected}
    command=['gst-launch-1.0','-e','-v'];probes={}
    for camera in cameras:
        current=format_spec({'v4l2':[camera.stream_spec]})
        candidate=generated.get(camera.key)
        group=next((g for g in candidate.groups if format_spec(g)==current),None) if candidate else None
        if not group or 'gst_nvmm' not in group:
            return None, {}, 'No generated NVMM path for '+camera.key+' '+current[2]
        group=dict(group)
        group['gst_nvmm']=['fakesink' if x in ('nv3dsink','autovideosink','ximagesink') else x for x in group['gst_nvmm']]
        args=streaming_command('gst_nvmm',group,frames,Path('.'))
        branch=args[args.index('egv4l2camerasrc'):]
        suffix=re.sub(r'\W','_',camera.key)
        names={'capture':'capture_'+suffix,'delivery':'delivery_'+suffix}
        branch=['name='+names['capture'] if x=='name=regression_probe' else x for x in branch]
        sink=branch.index('fakesink')
        branch[sink:sink]=['identity','name='+names['delivery'],'silent=false','!']
        command.extend(branch);probes[camera.key]=names
    return command,probes,None


def inspect_nvmm_streams(text, probes, frames, references, min_fps=0):
    checks={}
    for key,names in probes.items():
        entry={}
        for stage,name in names.items():
            lines='\n'.join(line for line in text.splitlines() if '/GstIdentity:'+name+':' in line)
            count=lines.count('last-message = chain')
            corrupt=sum('corrupted' in line for line in lines.splitlines() if 'last-message = chain' in line)
            cadence=stream_cadence('gst_nvmm',lines)['capture'];fps=cadence.get('steady_fps')
            passed=count==frames and corrupt==0 and fps is not None
            if key in references:passed=passed and rate_matches(cadence,references[key],.03)
            if min_fps:passed=passed and fps is not None and fps>=min_fps
            entry[stage]=dict(frames=count,corrupt=corrupt,cadence=cadence,passed=bool(passed))
        entry['passed']=all(x['passed'] for x in entry.values())
        checks[key]=entry
    return checks


def nvmm_accepted(result, required):
    return result['status']=='passed' or (not required and result['status'] in ('not_applicable','skipped'))


def concurrent_nvmm(cameras, args, folder):
    if args.skip_nvmm:return dict(status='skipped',reason='Explicit --skip-nvmm')
    if len(cameras)<2:return dict(status='not_applicable',reason='At least two connected cameras are required')
    # This DISPLAY is for command selection only, not proof of a display test.
    # The real pipelines below remove DISPLAY and use fakesink.
    selection=os.environ.copy();selection['DISPLAY']=':0'
    config=subprocess.check_output(['eg_dt_camera_config_get.sh','--all-streaming-backends'],
        env=selection,universal_newlines=True,stderr=subprocess.STDOUT,timeout=15)
    (folder/'nvmm-generated-commands.log').write_text(config)
    command,probes,reason=build_nvmm_command(cameras,config,args.nvmm_frames)
    if reason:return dict(status='not_applicable',reason=reason)
    references={}
    for camera in cameras:
        if camera.enginecore:
            time.sleep(args.ec_control_pause)
            output=subprocess.check_output(['ECSwCtrl','-i','i2c','-d',camera.device,'-c','rf 0x210'],
                universal_newlines=True,stderr=subprocess.STDOUT,timeout=15)
            (folder/(camera.key+'-nvmm-framerate.log')).write_text(output)
            references[camera.key]=parse_frame_rate(output)
    frames=max(args.nvmm_frames,math.ceil(max(references.values())*2.25)+1) if references else args.nvmm_frames
    command,probes,_=build_nvmm_command(cameras,config,frames)
    timeout=max(args.nvmm_timeout,frames/min(references.values())+6) if references else args.nvmm_timeout
    environment=os.environ.copy();environment.pop('DISPLAY',None);environment.pop('WAYLAND_DISPLAY',None)
    time.sleep(args.gap)
    usage=resource.getrusage(resource.RUSAGE_CHILDREN);started=time.monotonic();timed_out=False
    path=folder/'nvmm-concurrent.log'
    with path.open('w') as log:
        process=subprocess.Popen(command,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            try:process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:timed_out=True
        finally:
            stopped=boot_seconds();stop_process(process)
    elapsed=time.monotonic()-started;after=resource.getrusage(resource.RUSAGE_CHILDREN)
    text=path.read_text(errors='replace');checks=inspect_nvmm_streams(text,probes,frames,references,args.min_fps)
    passed=not timed_out and process.returncode==0 and 'Got EOS' in text and all(x['passed'] for x in checks.values())
    return dict(status='passed' if passed else 'failed',command=command,returncode=process.returncode,
        frames=frames,reference_fps=references,checks=checks,seconds=round(elapsed,3),timed_out=timed_out,
        cpu_percent_one_core=round(100*((after.ru_utime-usage.ru_utime)+(after.ru_stime-usage.ru_stime))/elapsed,3),
        cpu_scope='one GStreamer process, all source branches and threads; startup/shutdown included',
        stop_time=stopped,log=path.name)


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
    p.add_argument('--require-nvmm',action='store_true',help='Require the multi-source NVMM check; missing/unsupported paths fail')
    p.add_argument('--skip-nvmm',action='store_true',help='Explicitly skip the multi-source NVMM check')
    p.add_argument('--nvmm-frames',type=int,default=180,help='Frames per NVMM branch in the finite concurrent check')
    p.add_argument('--nvmm-timeout',type=float,default=30,help='Minimum timeout for the finite NVMM check')
    p.add_argument('--ec-control-pause',type=float,default=5,help='Pause before EngineCore reference-framerate reads')
    a=p.parse_args()
    if a.require_nvmm and a.skip_nvmm:p.error('--require-nvmm conflicts with --skip-nvmm')
    if min(a.nvmm_frames,a.nvmm_timeout)<=0 or a.ec_control_pause<0:p.error('Invalid NVMM count/timeout or control pause')
    if os.geteuid()!=0:p.error('Run as root on the target')
    if min(a.seconds,a.frames)<=0 or min(a.cycles,a.gap,a.min_fps)<0:p.error('Invalid time/count')
    if bool(a.plan)!=bool(a.visit):p.error('--plan and --visit must be used together')
    a.output.mkdir(parents=True,exist_ok=False)
    report=dict(status='running',nvmm=dict(status='not_run',reason='Raw tests have not completed'),cycles=[],streams=[],controls=[],errors=[],script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
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
        report['nvmm']=dict(status='running',reason='Concurrent NVMM check in progress');save()
        report['nvmm']=concurrent_nvmm(cameras,a,a.output);save()
        for camera in cameras:
            for check in register_read_plan(camera):
                time.sleep(2);text=output(check['command']);passed,value=validate_register_read(check,0,text)
                report['controls'].append(dict(camera=camera.key,name=check['name'],value=value,passed=passed))
        after=output(['dmesg']);(a.output/'dmesg-after.log').write_text(after)
        delta=kernel_delta(before,after)
        if delta is None:report['errors'].append('Kernel log wrapped/cleared: error review is incomplete')
        else:
            stops=[x['stop_time'] for key in ('cycles','streams') for x in report[key]]
            if 'stop_time' in report['nvmm']:stops.append(report['nvmm']['stop_time'])
            errors,observations=classify_kernel_lines(delta,stops)
            report['errors'] += errors;report['kernel_stop_observations']=observations
        report['status']='passed' if not report['errors'] and nvmm_accepted(report['nvmm'],a.require_nvmm) and all(x['passed'] for key in ('cycles','streams','controls') for x in report[key]) else 'failed'
    except (Exception,KeyboardInterrupt) as error:
        if report['nvmm']['status']=='running':report['nvmm']=dict(status='failed',reason=repr(error))
        report['status']='failed';report['errors'].append(repr(error))
    finally:
        if (a.output/'dmesg-before.log').exists() and not (a.output/'dmesg-after.log').exists():
            try:(a.output/'dmesg-after.log').write_text(output(['dmesg'],timeout=3))
            except Exception as error:report['errors'].append('Cannot collect final kernel log: '+repr(error))
        save();lock.close()
    print(json.dumps(dict(status=report['status'],errors=report['errors'],nvmm=report['nvmm']),indent=2))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    raise SystemExit(main())
