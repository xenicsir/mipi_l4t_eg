"""V4L2 metadata and rejection checks independent of streaming/display backends."""
import ctypes
import errno
import fcntl
import os
import re
import struct


BPP = {'AR24': 4, 'AB24': 4, 'RGB3': 3, 'BGR3': 3,
       'YUYV': 2, 'UYVY': 2, 'Y16': 2, 'Y16 -BE': 2, 'Y14': 2, 'GREY': 1}


def canonical(value):
    return value.strip() if value else value


def parse_current(text):
    pixel = re.search(r"Pixel Format\s*:\s*'([^']+)'", text)
    size = re.search(r'Width/Height\s*:\s*(\d+)\s*/\s*(\d+)', text)
    stride = re.search(r'Bytes per Line\s*:\s*(\d+)', text)
    image = re.search(r'Size Image\s*:\s*(\d+)', text)
    return dict(format=canonical(pixel[1]) if pixel else None,
                width=int(size[1]) if size else None, height=int(size[2]) if size else None,
                bytesperline=int(stride[1]) if stride else None,
                sizeimage=int(image[1]) if image else None)


def parse_details(text):
    headers = list(re.finditer(r"^\s*(?:\[\d+\]:\s*'([^']+)'|Pixel Format\s*:\s*'([^']+)')", text, re.M))
    entries = []
    for index, header in enumerate(headers):
        block = text[header.end():headers[index+1].start() if index+1 < len(headers) else len(text)]
        sizes = list(re.finditer(r'Size:\s*Discrete\s+(\d+)x(\d+)', block))
        dimensions = []
        for j, size in enumerate(sizes):
            part = block[size.end():sizes[j+1].start() if j+1 < len(sizes) else len(block)]
            rates = [float(x) for x in re.findall(r'Interval:\s*Discrete[^\n]*\(([0-9.]+)\s*fps\)', part)]
            dimensions.append(dict(width=int(size[1]), height=int(size[2]), fps=rates))
        entries.append(dict(format=canonical(header[1] or header[2]), sizes=dimensions))
    return entries


def validate_metadata(enumeration, current, width, height, expected_format=None,
                      active_only=False, expected_fps=None, fps_tolerance=0.03, expected_formats=None):
    entries, actual = parse_details(enumeration), parse_current(current)
    errors = []
    names = [x['format'] for x in entries]
    if not entries: errors.append('No enumerated formats')
    if len(names) != len(set(names)): errors.append('Duplicate pixel formats')
    if actual['format'] not in names: errors.append('Active format is not enumerated')
    if (actual['width'], actual['height']) != (width, height): errors.append('Active dimensions differ from camera dimensions')
    if expected_format and actual['format'] != canonical(expected_format): errors.append('Active pixel format differs from camera configuration')
    if active_only and names != [actual['format']]: errors.append('Unexpected alternative capture format')
    if expected_formats is not None and set(names) != {canonical(f) for f in expected_formats}:
        errors.append('Advertised formats differ from camera capabilities: expected '+repr(expected_formats))
    bpp = BPP.get(actual['format'])
    if not bpp:
        errors.append('Unknown memory layout for active fourcc')
    elif actual['bytesperline'] is None or actual['bytesperline'] < width*bpp:
        errors.append('Invalid or missing bytesperline')
    elif actual['sizeimage'] is None or actual['sizeimage'] < actual['bytesperline']*height:
        errors.append('Invalid or missing sizeimage')
    for entry in entries:
        sizes = [(s['width'], s['height']) for s in entry['sizes']]
        if sizes != [(width, height)]: errors.append('%s: expected only %dx%d, got %s' % (entry['format'], width, height, sizes))
        for size in entry['sizes']:
            rates = size['fps']
            if not rates or any(rate <= 0 for rate in rates): errors.append(entry['format']+': missing or invalid frame intervals')
            if expected_fps is not None and not any(abs(rate-expected_fps) <= expected_fps*fps_tolerance for rate in rates):
                errors.append(entry['format']+': frame intervals disagree with camera framerate')
    return dict(passed=not errors, errors=errors, entries=entries, active=actual,
                expected_dimensions=[width,height], expected_format=expected_format,
                interval_reference=expected_fps,
                interval_accuracy_verified=expected_fps is not None)


class _FormatUnion(ctypes.Union):
    _fields_ = [('raw', ctypes.c_ubyte*200), ('alignment', ctypes.c_void_p)]


class _Format(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('fmt', _FormatUnion)]


SIZE = ctypes.sizeof(_Format)
OFFSET = _Format.fmt.offset
G_FMT = (3 << 30) | (SIZE << 16) | (ord('V') << 8) | 4
S_FMT = (3 << 30) | (SIZE << 16) | (ord('V') << 8) | 5
TRY_FMT = (3 << 30) | (SIZE << 16) | (ord('V') << 8) | 64


def decode_format(data):
    values = struct.unpack_from('=12I', data, OFFSET)
    fourcc = values[2]
    name = (fourcc & 0x7fffffff).to_bytes(4, 'little').decode('ascii', 'replace')
    if fourcc & 0x80000000: name += '-BE'
    return dict(width=values[0], height=values[1], format=canonical(name), fourcc=fourcc,
                field=values[3], bytesperline=values[4], sizeimage=values[5],
                colorspace=values[6], flags=values[8], encoding=values[9],
                quantization=values[10], transfer=values[11])


def get_format(fd):
    data = bytearray(SIZE);struct.pack_into('=I', data, 0, 1)
    fcntl.ioctl(fd, G_FMT, data, True)
    return data


def encode_fourcc(name):
    name=name.strip();big_endian=name.endswith('-BE')
    if big_endian:name=name[:-3]
    value=name.ljust(4).encode('ascii')
    if len(value)!=4:raise ValueError('Invalid fourcc '+name)
    return int.from_bytes(value,'little') | (0x80000000 if big_endian else 0)


def format_core(value):
    return tuple(value[k] for k in ('width','height','fourcc','bytesperline','sizeimage'))


def check_rejections(device, advertised=None, fixed_pixel_format=True, other_sizes=None):
    """Issue real ioctls; compare each rejected request with its immediate state.

    A successful native S_FMT may normalize default colorimetry. That is recorded
    separately and must not be mistaken for mutation caused by a rejected call.
    """
    fd=os.open(device,os.O_RDWR|os.O_NONBLOCK)
    original=None;needs_restore=False
    try:
        original=get_format(fd);native=decode_format(original);checks=[]
        alternatives={canonical(f) for f in (advertised or [])}
        alternatives.add('AR24' if native['format']!='AR24' else 'AB24')
        alternatives.discard(native['format'])
        requests=[('other-width',native['width']+16,native['height'],native['fourcc']),
                  ('other-height',native['width'],native['height']+1,native['fourcc'])]
        requests += [('other-model-%dx%d' % (width,height),width,height,native['fourcc'])
                     for width,height in sorted(set(other_sizes or []))
                     if (width,height)!=(native['width'],native['height'])]
        if fixed_pixel_format:
            requests += [('other-format-'+f,native['width'],native['height'],encode_fourcc(f)) for f in sorted(alternatives)]
            requests += [('unknown-format',native['width'],native['height'],encode_fourcc('ZZZZ'))]
        for operation,number in [('TRY_FMT',TRY_FMT),('S_FMT',S_FMT)]:
            for label,width,height,fourcc in requests:
                before_raw=get_format(fd);before=decode_format(before_raw)
                data=bytearray(before_raw);struct.pack_into('=3I',data,OFFSET,width,height,fourcc)
                error=0;needs_restore=True
                try:fcntl.ioctl(fd,number,data,True)
                except OSError as exc:error=exc.errno
                active=decode_format(get_format(fd))
                checks.append(dict(operation=operation,case=label,errno=error,
                    requested=dict(width=width,height=height,fourcc=fourcc),returned=decode_format(data),
                    active_before=before,active_after=active,passed=error==errno.EINVAL and active==before))
                if error!=errno.EINVAL or active!=before:
                    fcntl.ioctl(fd,S_FMT,bytearray(original),True)
                    if format_core(decode_format(get_format(fd)))!=format_core(native):
                        raise RuntimeError('Unable to restore active capture layout')
                needs_restore=False
        before_native=decode_format(get_format(fd))
        needs_restore=True
        fcntl.ioctl(fd,S_FMT,bytearray(original),True)
        final=decode_format(get_format(fd));same=format_core(final)==format_core(native)
        if not same:raise RuntimeError('Native S_FMT changed the capture layout')
        needs_restore=False
        return dict(passed=all(c['passed'] for c in checks) and same,checks=checks,
                    native=native,native_set_accepted=same,restored=same,
                    fixed_pixel_format=fixed_pixel_format,
                    native_set_metadata_changes={k:[before_native[k],final[k]] for k in final if before_native[k]!=final[k]})
    finally:
        try:
            if original is not None and needs_restore:fcntl.ioctl(fd,S_FMT,bytearray(original),True)
        finally:os.close(fd)
