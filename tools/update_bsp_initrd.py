#!/usr/bin/env python3
"""Run NVIDIA's initrd updater with manifests adapted to built-in drivers.

Only missing module files listed in the matching image's modules.builtin are
omitted. Loadable modules and unknown missing files retain NVIDIA's normal
checks. Original manifests are restored after success, failure or interruption.
"""
import argparse
import contextlib
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import signal
import subprocess
import tempfile


TOKEN = '<KERNEL_VERSION>'
MODULE = re.compile(r'^/(?:usr/)?lib/modules/([^/]+)/(.+\.ko)$')
VERSION = re.compile(rb'Linux version ([0-9a-zA-Z.\-]+\+*) ')


def kernel_versions(rootfs):
    """Read the same image list and version banners as the vendor updater."""
    updater = rootfs / 'usr/sbin/nv-update-initrd'
    if not updater.is_file():
        return []
    match = re.search(r'^\s*IMAGES_PATH=\(([^)]*)\)', updater.read_text(), re.M)
    if not match:
        return []
    images = shlex.split(match[1])
    if any(not name.startswith('/boot/') or '$' in name or '`' in name
           or '..' in PurePosixPath(name).parts for name in images):
        return []
    versions = []
    for name in images:
        image = rootfs / name.lstrip('/')
        if not image.is_file():
            continue
        # Do not resolve an absolute rootfs symlink against the host filesystem.
        if not image.resolve().is_relative_to(rootfs.resolve()):
            return []
        banner = VERSION.search(image.read_bytes())
        if not banner:
            return []
        version = banner[1].decode('ascii')
        if version not in versions:
            versions.append(version)
    return versions


def missing_builtin(rootfs, source, version, cache):
    match = MODULE.fullmatch(source)
    if not match or match[1] != version or '..' in PurePosixPath(match[2]).parts:
        return False
    module = rootfs / source.lstrip('/')
    if not module.resolve().is_relative_to(rootfs.resolve()) or module.exists():
        return False
    if version not in cache:
        builtin = rootfs / 'lib/modules' / version / 'modules.builtin'
        cache[version] = (set(builtin.read_text().splitlines())
                          if builtin.is_file()
                          and builtin.resolve().is_relative_to(rootfs.resolve())
                          else set())
    return match[2] in cache[version]


def adapt_manifest(text, rootfs, versions):
    """Expand mixed per-image entries so a loadable RT driver is never omitted."""
    result, omitted, cache = [], [], {}
    for line in text.splitlines(keepends=True):
        entry = line.strip()
        if not entry or entry.startswith('#') or ':' not in entry or not versions:
            result.append(line)
            continue
        source = entry.split(':', 1)[0]
        skipped = [missing_builtin(rootfs, source.replace(TOKEN, version),
                                   version, cache) for version in versions]
        if not any(skipped):
            result.append(line)
            continue
        for version, skip in zip(versions, skipped):
            if skip:
                omitted.append(source.replace(TOKEN, version))
            else:
                # The vendor loops over images. Explicit paths preserve all
                # remaining versions in that loop, including loadable drivers.
                result.append(entry.replace(TOKEN, version) + '\n')
    return ''.join(result), omitted


def restore_manifests(backup, lists):
    if not backup.exists():
        return
    if backup.is_symlink() or not backup.is_dir():
        raise RuntimeError(f'Invalid initrd manifest backup: {backup}')
    for original in backup.iterdir():
        if original.is_symlink() or not original.is_file():
            raise RuntimeError(f'Invalid saved manifest: {original}')
        os.replace(original, lists / original.name)
    backup.rmdir()


@contextlib.contextmanager
def adapted_manifests(bsp):
    rootfs = bsp / 'rootfs'
    lists = rootfs / 'etc/nv-update-initrd/list.d'
    # Outside list.d: NVIDIA must not concatenate backups into its input list.
    backup = lists.parent / '.eg-initrd-manifests-backup'
    with (bsp / '.eg-initrd.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        restore_manifests(backup, lists)
        versions = kernel_versions(rootfs) if lists.is_dir() else []
        changes, omitted = [], []
        for path in sorted(lists.iterdir()) if versions else []:
            if path.name.startswith('.') or not path.is_file() or path.is_symlink():
                continue
            old = path.read_text()
            new, skipped = adapt_manifest(old, rootfs, versions)
            if new != old:
                changes.append((path, new))
                omitted.extend(skipped)
        try:
            if changes:
                backup.mkdir()
            for path, text in changes:
                stat = path.stat()
                os.replace(path, backup / path.name)
                descriptor, temporary = tempfile.mkstemp(prefix='.eg-initrd-', dir=lists)
                try:
                    with os.fdopen(descriptor, 'w') as stream:
                        stream.write(text)
                        stream.flush()
                        os.fchmod(stream.fileno(), stat.st_mode & 0o7777)
                        os.fchown(stream.fileno(), stat.st_uid, stat.st_gid)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            for name in omitted:
                print(f'Initrd: driver built into kernel, no module file required: {name}', flush=True)
            yield omitted
        finally:
            restore_manifests(backup, lists)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bsp', required=True, type=Path)
    args = parser.parse_args()
    bsp = args.bsp.resolve()
    updater = bsp / 'tools/l4t_update_initrd.sh'
    if not updater.is_file():
        parser.error(f'NVIDIA initrd updater not found: {updater}')
    process = None

    def interrupted(signum, _frame):
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        raise SystemExit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with adapted_manifests(bsp):
        process = subprocess.Popen([str(updater)], cwd=bsp, start_new_session=True)
        try:
            return process.wait()
        finally:
            # Never wait from the signal handler: it may interrupt Popen.wait
            # while its internal waitpid lock is held by this same thread.
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, signal.SIG_IGN)
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


if __name__ == '__main__':
    raise SystemExit(main())
