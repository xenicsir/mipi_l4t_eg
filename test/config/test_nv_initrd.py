#!/usr/bin/env python3
"""Check built-in initrd drivers, mixed images and manifest restoration."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools/update_bsp_initrd.py'
spec = importlib.util.spec_from_file_location('nv_initrd', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

VERSION = '5.15.185-tegra-eg'
RELATIVE = 'kernel/drivers/nvme/host/nvme.ko'
ENTRY = '/lib/modules/<KERNEL_VERSION>/' + RELATIVE
ROW = ENTRY + ':' + ENTRY + '\n'


class InitrdTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bsp = Path(self.temporary.name)
        self.rootfs = self.bsp / 'rootfs'
        self.lists = self.rootfs / 'etc/nv-update-initrd/list.d'
        self.lists.mkdir(parents=True)
        self.manifest = self.lists / 'modules'
        self.original = '# vendor header\n' + ROW
        self.manifest.write_text(self.original)
        updater = self.rootfs / 'usr/sbin/nv-update-initrd'
        updater.parent.mkdir(parents=True)
        updater.write_text('IMAGES_PATH=("/boot/Image" "/boot/Image.real-time")\n')
        self.image('Image', VERSION)
        self.builtin(VERSION)

    def image(self, name, version):
        image = self.rootfs / 'boot' / name
        image.parent.mkdir(exist_ok=True)
        image.write_bytes(b'ARM image\0Linux version ' + version.encode() + b' compiler\0')

    def builtin(self, version, entries=(RELATIVE,)):
        directory = self.rootfs / 'lib/modules' / version
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'modules.builtin').write_text(''.join(name + '\n' for name in entries))

    def vendor_command(self, body):
        path = self.bsp / 'tools/l4t_update_initrd.sh'
        path.parent.mkdir(exist_ok=True)
        path.write_text('#!/bin/sh\nset -eu\n' + body)
        path.chmod(0o755)

    def test_only_missing_builtin_is_removed(self):
        unknown = '/lib/modules/<KERNEL_VERSION>/kernel/missing.ko:/destination\n'
        wildcard = '/lib/modules/<KERNEL_VERSION>/modules*:/destination\n'
        text = '# copyright\n' + ROW + unknown + wildcard + '/missing/tool:/bin/tool\n'
        result, omitted = module.adapt_manifest(text, self.rootfs, [VERSION])
        self.assertEqual(result, text.replace(ROW, ''))
        self.assertEqual(omitted, [ENTRY.replace(module.TOKEN, VERSION)])

    def test_existing_module_is_preserved_even_with_stale_builtin_metadata(self):
        path = self.rootfs / 'lib/modules' / VERSION / RELATIVE
        path.parent.mkdir(parents=True)
        path.write_bytes(b'loadable module')
        self.assertEqual(module.adapt_manifest(ROW, self.rootfs, [VERSION]), (ROW, []))

    def test_unknown_or_different_kernel_is_not_hidden(self):
        self.builtin(VERSION, ())
        self.assertEqual(module.adapt_manifest(ROW, self.rootfs, [VERSION]), (ROW, []))
        self.builtin(VERSION)
        fixed = ROW.replace(module.TOKEN, VERSION)
        self.assertEqual(module.adapt_manifest(fixed, self.rootfs, ['6.8.12-other']), (fixed, []))

    def test_mixed_images_keep_loadable_realtime_driver(self):
        realtime = '5.15.185-rt-tegra'
        self.image('Image.real-time', realtime)
        self.builtin(realtime, ())
        path = self.rootfs / 'lib/modules' / realtime / RELATIVE
        path.parent.mkdir(parents=True)
        path.write_bytes(b'RT module')
        versions = module.kernel_versions(self.rootfs)
        self.assertEqual(versions, [VERSION, realtime])
        result, omitted = module.adapt_manifest(ROW, self.rootfs, versions)
        self.assertEqual(result, ROW.replace(module.TOKEN, realtime))
        self.assertEqual(omitted, [ENTRY.replace(module.TOKEN, VERSION)])

    def test_unsupported_image_expression_leaves_manifest_unchanged(self):
        (self.rootfs / 'usr/sbin/nv-update-initrd').write_text('IMAGES_PATH=("/boot/$IMAGE")\n')
        with module.adapted_manifests(self.bsp) as omitted:
            self.assertEqual(omitted, [])
            self.assertEqual(self.manifest.read_text(), self.original)

    def test_restore_after_success_failure_and_interruption(self):
        original_stat = self.manifest.stat()
        for failure in (None, RuntimeError, KeyboardInterrupt):
            with self.subTest(failure=failure):
                try:
                    with module.adapted_manifests(self.bsp):
                        self.assertEqual(self.manifest.read_text(), '# vendor header\n')
                        if failure:
                            raise failure()
                except (RuntimeError, KeyboardInterrupt):
                    pass
                self.assertEqual(self.manifest.read_text(), self.original)
                self.assertEqual(self.manifest.stat().st_ino, original_stat.st_ino)
                self.assertFalse((self.lists.parent / '.eg-initrd-manifests-backup').exists())

    def test_recover_unfinished_previous_update(self):
        backup = self.lists.parent / '.eg-initrd-manifests-backup'
        backup.mkdir()
        os.replace(self.manifest, backup / self.manifest.name)
        self.manifest.write_text('interrupted temporary content\n')
        with module.adapted_manifests(self.bsp):
            self.assertEqual(self.manifest.read_text(), '# vendor header\n')
        self.assertEqual(self.manifest.read_text(), self.original)
        self.assertFalse(backup.exists())

    def test_real_child_failure_is_propagated_and_manifest_restored(self):
        self.vendor_command('cat rootfs/etc/nv-update-initrd/list.d/modules > observed\nexit 17\n')
        result = subprocess.run([sys.executable, str(TOOL), '--bsp', str(self.bsp)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertEqual((self.bsp / 'observed').read_text(), '# vendor header\n')
        self.assertEqual(self.manifest.read_text(), self.original)

    def test_sigterm_restores_manifest_and_stops_child(self):
        self.vendor_command('echo "$$" > child.pid\n: > ready\nsleep 60\n')
        process = subprocess.Popen([sys.executable, str(TOOL), '--bsp', str(self.bsp)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not (self.bsp / 'ready').exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail('Helper exited before starting its child: ' + str(process.communicate()))
                time.sleep(0.01)
            self.assertTrue((self.bsp / 'ready').exists())
            child = int((self.bsp / 'child.pid').read_text())
            process.send_signal(signal.SIGTERM)
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 128 + signal.SIGTERM, out + err)
            self.assertEqual(self.manifest.read_text(), self.original)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
