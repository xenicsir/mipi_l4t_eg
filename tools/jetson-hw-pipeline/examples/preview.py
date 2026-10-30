#!/usr/bin/env python3
"""Display a camera through NVMM/VIC/CUDA; never map its pixel buffers to Python."""
import argparse
import sys
import os
import re
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/video0')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--fps', type=int, default=60)
    parser.add_argument('--frames', type=int, default=180, help='0 runs until Ctrl+C')
    parser.add_argument('--format', choices=['YUYV','AB24','AR24','Y16','Y14','Y16_BE'], default='YUYV')
    parser.add_argument('--headless', action='store_true', help='Test capture/conversion without rendering')
    args = parser.parse_args()
    if min(args.width, args.height, args.fps) <= 0 or args.frames < 0:
        parser.error('Width, height and fps must be positive; frames must be non-negative')
    if not args.headless and not re.fullmatch(r'(?:unix/?)?:[0-9]+(?:\.[0-9]+)?', os.environ.get('DISPLAY','')):
        parser.error('NVMM display requires local X11; use --headless for capture over SSH')
    if args.headless:
        os.environ.pop('DISPLAY', None)
    else:
        os.environ.setdefault("__GL_YIELD", "USLEEP")
    Gst.init(None)
    sink = 'fakesink sync=false' if args.headless else 'nv3dsink sync=false processing-deadline=0'
    gray = args.format in ('Y16', 'Y14', 'Y16_BE')
    fmt = {'YUYV': 'YUY2', 'AB24': 'RGBA', 'AR24': 'BGRx'}.get(args.format, 'RGBA')
    conversion = (' ! nvvidconv compute-hw=2 ! video/x-raw(memory:NVMM),format=NV12'
                  if args.format in ('YUYV', 'AR24') else '')
    pipeline = Gst.parse_launch(
        'egv4l2camerasrc name=camera ! '
        'video/x-raw(memory:NVMM),format=%s,width=%d,height=%d,framerate=%d/1%s ! %s'
        % (fmt, args.width, args.height, args.fps, conversion, sink))
    camera = pipeline.get_by_name('camera')
    if gray:
        camera.set_property('capture-format', args.format)
        camera.set_property('preview', True)
    camera.set_property('device', args.device)
    camera.set_property('num-buffers', args.frames if args.frames else -1)
    count = [0]

    def observe(_pad, _info):
        count[0] += 1  # Buffer metadata only: no map(), NumPy or OpenCV.
        return Gst.PadProbeReturn.OK

    camera.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, observe)
    bus = pipeline.get_bus()
    failed = False
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Cannot start pipeline')
        while True:
            message = bus.timed_pop_filtered(
                100 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if message is None:
                continue
            if message.type == Gst.MessageType.ERROR:
                error, details = message.parse_error()
                print('%s: %s\n%s' % (message.src.get_name(), error, details or ''), file=sys.stderr)
                failed = True
            break
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
    print('Captured %d buffers; pixel data remained outside Python.' % count[0])
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
