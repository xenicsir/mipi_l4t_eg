#!/usr/bin/env python3
"""Compare a static camera pattern through classic and NVMM capture/preview."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np


def difference(a,b,tolerance=0):
    if a.shape!=b.shape:return dict(passed=False,reason='shape mismatch',left=list(a.shape),right=list(b.shape))
    delta=np.abs(a.astype(np.int32)-b.astype(np.int32))
    return dict(passed=bool(np.all(delta<=tolerance)),max_difference=int(delta.max()),
                different_values=int(np.count_nonzero(delta)),out_of_tolerance=int(np.count_nonzero(delta>tolerance)),
                tolerance=tolerance,values=int(delta.size))


def native_frame(path,fmt,w,h):
    if fmt in ('Y16','Y14','Y16_BE'):
        return np.fromfile(str(path),dtype='>u2' if fmt=='Y16_BE' else '<u2').astype(np.uint16).reshape(h,w)
    return np.fromfile(str(path),dtype=np.uint8).reshape(h,w,2 if fmt=='YUYV' else 4)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device',required=True);p.add_argument('--format',required=True,choices=['Y16','Y16_BE','Y14','AR24','AB24','YUYV'])
    p.add_argument('--width',type=int,required=True);p.add_argument('--height',type=int,required=True)
    p.add_argument('--mode',choices=['fixed','normalized'],default='fixed')
    p.add_argument('--capture-tool',default='egNvmmPixelCapture');p.add_argument('--monitor',default='/usr/bin/rt_frame_monitor.py')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--gap',type=float,default=3)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('pixel_reference_monitor',a.monitor);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    env=os.environ.copy();env.pop('DISPLAY',None)
    fmt=a.format;gray=fmt in ('Y16','Y16_BE','Y14');baseline=[]
    cap=m.open_capture(a.device,a.device,fmt,a.width,a.height,60,None)
    try:
        for i in range(8):
            ok,frame=cap.read()
            if not ok:raise RuntimeError('Classic capture returned no image')
            if i>=5:baseline.append(frame.copy())
    finally:cap.release()
    # Alpha is padding in the camera's RGB888 transport, not a sensor component.
    samples=lambda f:f[:,:,:3] if fmt in ('AR24','AB24') else f
    informative = int(np.unique(samples(baseline[0])).size) >= 16
    checks=[dict(test='pattern_information',passed=informative,minimum=int(baseline[0].min()),maximum=int(baseline[0].max()))]
    checks += [dict(test='classic_pattern_stability',frame=i,**difference(samples(baseline[0]),samples(f))) for i,f in enumerate(baseline)]
    time.sleep(a.gap)
    import gi
    gi.require_version('Gst','1.0')
    from gi.repository import Gst
    Gst.init(None)
    factory=Gst.ElementFactory.find('egv4l2camerasrc')
    plan=m._nvmm_factory_plan(Gst,factory,fmt,True,a.mode=='normalized')
    conversion='CUDA' if plan['processing']=='cuda-yuyv-preview' else plan.get('vic_output','NV12')
    result=subprocess.run([a.capture_tool,a.device,fmt,str(a.width),str(a.height),a.mode,str(a.output),conversion],
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,env=env,timeout=12)
    (a.output/'nvmm-capture.log').write_text(result.stdout)
    result.check_returncode()
    meta=json.loads((a.output/'capture.json').read_text())
    for i in range(3):
        raw=native_frame(a.output/('frame-%d-capture.bin'%i),fmt,a.width,a.height)
        checks.append(dict(test='classic_vs_nvmm_capture',frame=i,**difference(samples(baseline[0]),samples(raw))))
        if i:
            checks.append(dict(test='nvmm_pattern_stability',frame=i,**difference(samples(first_raw),samples(raw))))
        else:first_raw=raw
        display=np.fromfile(str(a.output/('frame-%d-display.bin'%i)),dtype=np.uint8).reshape(a.height,a.width,4)
        if gray:
            expected=m.grayscale_preview(baseline[0],fmt,a.mode=='normalized')
            tolerance=1 if a.mode=='normalized' else 0
            for channel in range(3):checks.append(dict(test='classic_vs_cuda_gray_preview',frame=i,channel=channel,**difference(expected,display[:,:,channel],tolerance)))
            checks.append(dict(test='gray_alpha',frame=i,passed=bool(np.all(display[:,:,3]==255))))
        else:
            expected=m.to_display_bgr(baseline[0],fmt)
            checks.append(dict(test='classic_vs_nvmm_color_preview',frame=i,**difference(expected,display[:,:,:3][:,:,::-1],3)))
        if i==0:
            np.savez_compressed(str(a.output/'images.npz'),classic=baseline[0],nvmm_capture=raw,nvmm_rgba=display,classic_preview=expected)
    report=dict(passed=all(x['passed'] for x in checks),format=fmt,mode=a.mode,checks=checks,capture=meta,
                scope='Actual classic capture and display functions versus NVMM; static pattern required. RGBA readback follows any NV12/VIC stage.',
                classic_module=str(Path(a.monitor).resolve()))
    (a.output/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    for path in a.output.glob('frame-*.bin'):path.unlink()
    print(json.dumps(report));return 0 if report['passed'] else 1


if __name__=='__main__':
    sys.exit(main())
