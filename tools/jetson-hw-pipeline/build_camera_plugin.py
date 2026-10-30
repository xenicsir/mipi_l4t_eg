#!/usr/bin/env python3
"""Build the egv4l2camerasrc plugin natively or against a Jetson BSP sysroot."""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
from pathlib import Path
import subprocess
import tarfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_file(archive, member, target):
    with tarfile.open(str(archive)) as tar:
        item = tar.getmember(member)
        if not item.isfile():
            raise ValueError('Expected regular archive member: ' + member)
        with tar.extractfile(item) as source:
            target.write_bytes(source.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera-archive', type=Path)
    parser.add_argument('--source-dir', type=Path, help='Prepared, namespaced sources from sources/<version>')
    parser.add_argument('--converter-archive', type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New output directory')
    parser.add_argument('--library-dir', type=Path, default=Path('/usr/lib/aarch64-linux-gnu/nvidia'))
    parser.add_argument('--sysroot', type=Path, help='BSP rootfs for host cross-compilation')
    parser.add_argument('--cxx', default='g++', help='Native or cross C++ compiler')
    args = parser.parse_args()
    compiler = shutil.which(args.cxx)
    if not compiler:
        parser.error("Compiler not found: " + args.cxx)
    # Keep the compiler symlink name: Buildroot dispatches through argv[0].
    args.cxx = os.path.abspath(compiler)
    machine = subprocess.check_output([args.cxx, '-dumpmachine'], universal_newlines=True).strip()
    if not machine.startswith('aarch64'):
        parser.error('The compiler must target aarch64; pass --cxx and --sysroot for a host build')
    patch = Path(__file__).resolve().with_name('nvv4l2camerasrc-yuy2.patch')
    prepared = args.source_dir.resolve() if args.source_dir else None
    if prepared and (args.camera_archive or args.converter_archive):
        parser.error('--source-dir and archive inputs are mutually exclusive')
    if not prepared and not (args.camera_archive and args.converter_archive):
        parser.error('Provide --source-dir or both source archives')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = ['gstnvv4l2camerasrc.cpp', 'gstnvv4l2camerasrc.hpp', 'gstnvv4l2camerabufferpool.h']
    if prepared:
        sources += [name for name in ('eg_cuda_gray.cpp', 'eg_cuda_gray.h') if (prepared / name).exists()]
    inputs = {str(Path(__file__).resolve()): sha(Path(__file__).resolve())}
    if prepared:
        for name in sources + ['nvbufsurface.h']:
            path = prepared / name
            inputs[str(path)] = sha(path)
            (output / name).write_bytes(path.read_bytes())
    else:
        camera = args.camera_archive.resolve()
        converter = args.converter_archive.resolve()
        for path in (camera, converter, patch):
            inputs[str(path)] = sha(path)
        for name in sources:
            extract_file(camera, 'gst-nvv4l2camera/' + name, output / name)
        extract_file(converter, 'gst-nvvidconv/nvbufsurface.h', output / 'nvbufsurface.h')
    environment = os.environ.copy()
    sysroot = args.sysroot.resolve() if args.sysroot else None
    if sysroot:
        environment['PKG_CONFIG_SYSROOT_DIR'] = str(sysroot)
        environment['PKG_CONFIG_PATH'] = ''
        environment['PKG_CONFIG_LIBDIR'] = ':'.join(str(sysroot / p) for p in (
            'usr/lib/aarch64-linux-gnu/pkgconfig', 'usr/share/pkgconfig'))
    packages = ['gstreamer-1.0', 'gstreamer-base-1.0', 'gstreamer-video-1.0',
                'gstreamer-allocators-1.0', 'glib-2.0']
    package_flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', '--libs'] + packages, env=environment,
        universal_newlines=True))
    with (output / 'build.log').open('w') as log:
        def run(command):
            result = subprocess.run(command, cwd=str(output), env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True)
            log.write(repr(command) + '\n' + result.stdout)
            log.flush()
            print(result.stdout, end='')
            result.check_returncode()
        if not prepared:
            run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-i', str(patch)])
            sources += [name for name in ('eg_cuda_gray.cpp', 'eg_cuda_gray.h') if (output / name).exists()]
        # Distinct factory, GTypes and exported functions coexist with NVIDIA's plugin.
        replacements = [('GstNvV4l2', 'GstEgV4l2'), ('GstNVV4l2', 'GstEGV4l2'),
                        ('gst_nv_v4l2_camera', 'gst_eg_v4l2_camera'),
                        ('gst_nvv4l2camera_buffer_pool', 'gst_egv4l2camera_buffer_pool'),
                        ('gst_nv_memory_allocator', 'gst_eg_memory_allocator'),
                        ('nvv4l2camerasrc_init', 'egv4l2camerasrc_init'),
                        ('nvV4l2Memory', 'egV4l2Memory')]
        for name in ([] if prepared else sources):
            path = output / name
            text = path.read_text()
            for old, new in replacements:
                text = text.replace(old, new)
            text = re.sub(r'\bnvv4l2camerasrc\b', 'egv4l2camerasrc', text)
            path.write_text(text)
        library_dir = args.library_dir
        link_dir = sysroot / str(library_dir).lstrip('/') if sysroot else library_dir
        common = [args.cxx, '-std=c++11', '-O2', '-fPIC', '-Wall',
                  '-DEXPLICITLY_ADDED=1', '-DGETTEXT_PACKAGE=1',
                  '-DHAVE_LIBV4L2=1', '-DUSE_V4L2_TARGET_NV=1', '-I.']
        if sysroot:
            common += ['--sysroot=' + str(sysroot),
                       '-B' + str(sysroot / 'usr/lib/aarch64-linux-gnu') + '/']
        command = common + ['-shared'] + [name for name in sources if name.endswith('.cpp')] + [
                            '-o', 'libgstegv4l2camerasrc.so'] + package_flags
        command += ['-L' + str(link_dir), '-lnvbufsurface', '-ldl', '-Wl,--no-undefined',
                    '-Wl,-rpath,' + str(library_dir)]
        if sysroot:
            for directory in (link_dir, sysroot/'usr/lib/aarch64-linux-gnu',
                              sysroot/'lib/aarch64-linux-gnu'):
                command += ['-Wl,-rpath-link,' + str(directory)]
        run(command)
    plugin = output / 'libgstegv4l2camerasrc.so'
    manifest = {'inputs_sha256': inputs, 'compiler_target': machine,
                'compiler': subprocess.check_output([args.cxx, '--version'], universal_newlines=True).splitlines()[0],
                'plugin_sha256': sha(plugin), 'library_dir': str(args.library_dir), 'sysroot': str(sysroot) if sysroot else None,
                'factory': 'egv4l2camerasrc',
                'source_sha256': {n: sha(output / n) for n in sources + ['nvbufsurface.h']}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Built:', plugin)
    print('Set GST_PLUGIN_PATH to this directory and use a separate GST_REGISTRY for testing.')


if __name__ == '__main__':
    main()
