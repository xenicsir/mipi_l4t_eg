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
    parser.add_argument('--library-dir', type=Path, help='NVIDIA library directory (detected in the target rootfs by default)')
    parser.add_argument('--sysroot', type=Path, help='BSP rootfs for host cross-compilation')
    parser.add_argument('--cxx', default='g++', help='Native or cross C++ compiler')
    parser.add_argument('--pixel-checker', action='store_true',
                        help='Also build the diagnostic capture tool for pixel-comparison tests')
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
    if args.pixel_checker and not prepared:
        parser.error('--pixel-checker requires --source-dir with the prepared sources')
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
        if library_dir is None:
            for name in ('nvidia', 'tegra'):
                candidate = Path('/usr/lib/aarch64-linux-gnu') / name
                if ((sysroot / str(candidate).lstrip('/') if sysroot else candidate) / 'libnvbufsurface.so').exists():
                    library_dir = candidate
                    break
            if library_dir is None:
                raise RuntimeError('Cannot locate target libnvbufsurface.so; specify --library-dir')
        link_dir = sysroot / str(library_dir).lstrip('/') if sysroot else library_dir
        common = [args.cxx, '-std=c++11', '-O2', '-fPIC', '-Wall',
                  '-DEXPLICITLY_ADDED=1', '-DGETTEXT_PACKAGE=1',
                  '-DHAVE_LIBV4L2=1', '-DUSE_V4L2_TARGET_NV=1', '-I.']
        if sysroot:
            common += ['--sysroot=' + str(sysroot),
                       '-isystem', str(sysroot / 'usr/include/aarch64-linux-gnu'),
                       '-B' + str(sysroot / 'usr/lib/aarch64-linux-gnu') + '/']
        # Some BSP sysroots contain absolute libdl/libpthread development links.
        # Resolve the runtime libraries within the target, never through host /lib
        # or a static libc archive selected by the cross compiler.
        dl_flags = ['-ldl']
        if sysroot:
            for name, soname in (('dl', 'libdl.so.2'), ('pthread', 'libpthread.so.0')):
                development_link = sysroot / 'usr/lib/aarch64-linux-gnu' / ('lib' + name + '.so')
                if not development_link.is_symlink() or development_link.exists():
                    continue
                target = next((sysroot / d / soname for d in
                               ('lib/aarch64-linux-gnu', 'usr/lib/aarch64-linux-gnu')
                               if (sysroot / d / soname).is_file()), None)
                if target:
                    if name == 'dl':
                        dl_flags = [str(target)]
                    else:
                        package_flags = [f for f in package_flags if f not in ('-pthread', '-lpthread')]
                        common += ['-D_REENTRANT']
                        package_flags += [str(target)]
        command = common + ['-shared'] + [name for name in sources if name.endswith('.cpp')] + [
                            '-o', 'libgstegv4l2camerasrc.so'] + package_flags
        link_flags = ['-L' + str(link_dir), '-lnvbufsurface'] + dl_flags + ['-Wl,--no-undefined',
                    '-Wl,-rpath,' + str(library_dir)]
        if sysroot:
            dependency_dirs = [link_dir, sysroot/'usr/lib/aarch64-linux-gnu',
                               sysroot/'lib/aarch64-linux-gnu']
            # L4T39 keeps GPU-provider libraries outside the multiarch directory.
            # These are link-time lookup paths only: the target selects its GPU
            # provider through its own loader configuration at runtime.
            dependency_dirs += [sysroot/'opt/nvidia/l4t-gpu-libs'/provider
                                for provider in ('nvgpu', 'openrm')
                                if (sysroot/'opt/nvidia/l4t-gpu-libs'/provider).is_dir()]
            for directory in dependency_dirs:
                link_flags += ['-Wl,-rpath-link,' + str(directory)]
        run(command + link_flags)
        if args.pixel_checker:
            checker_source = Path(__file__).resolve().parent / 'tests/capture_pixels.cpp'
            inputs[str(checker_source)] = sha(checker_source)
            run(common + ['-std=c++14', '-DEG_PIXEL_PLUGIN_SHA="' + sha(output / 'libgstegv4l2camerasrc.so') + '"',
                          str(checker_source), '-o', 'egNvmmPixelCapture'] + package_flags + link_flags)
            yuyv_source = checker_source.with_name('capture_yuyv_synthetic.cpp')
            inputs[str(yuyv_source)] = sha(yuyv_source)
            run(common + [str(yuyv_source), 'eg_cuda_gray.cpp', '-o', 'egNvmmYuyvSynthetic'] + link_flags)
    plugin = output / 'libgstegv4l2camerasrc.so'
    manifest = {'inputs_sha256': inputs, 'compiler_target': machine,
                'compiler': subprocess.check_output([args.cxx, '--version'], universal_newlines=True).splitlines()[0],
                'plugin_sha256': sha(plugin), 'library_dir': str(library_dir), 'sysroot': str(sysroot) if sysroot else None,
                'factory': 'egv4l2camerasrc',
                'source_sha256': {n: sha(output / n) for n in sources + ['nvbufsurface.h']}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Built:', plugin)
    print('Set GST_PLUGIN_PATH to this directory and use a separate GST_REGISTRY for testing.')


if __name__ == '__main__':
    main()
