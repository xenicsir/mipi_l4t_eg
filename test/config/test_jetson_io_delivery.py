#!/usr/bin/env python3
"""Reject incomplete JetsonIO packages even when unrelated Jetson.GPIO is installed."""
import os
import ast
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test/packaging'))
from jetson_io_checks import check_tree, require_imports, REQUIRED_FILES, REQUIRED_DIRS


class JetsonIODeliveryTests(unittest.TestCase):
    def test_every_source_overlay_keeps_import_assets_and_executable_mode(self):
        paths=sorted((ROOT/'sources').glob('*/Linux_for_Tegra/rootfs/opt/eg/jetson-io'))
        self.assertGreater(len(paths),10)
        for path in paths:
            with self.subTest(version=path.parts[-7]):self.assertEqual(check_tree(path),[])

    def fixture(self, root):
        eg=root/'eg';vendor=root/'supplier/opt/nvidia/jetson-io';site=root/'site'
        shutil.copytree(ROOT/'sources/39.2.2/Linux_for_Tegra/rootfs/opt/eg/jetson-io',eg,symlinks=True)
        for name in REQUIRED_FILES:
            if name in ('config-by-hardware.py','Jetson/board.py','Linux/extlinux.py'):continue
            p=vendor/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('')
        for name in ('Headers/__init__.py','Utils/__init__.py','Utils/dtc.py','Utils/fio.py','Utils/syscall.py',
                     'config-by-function.py','config-by-pin.py','jetson-io.py'):
            p=vendor/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('')
        (site/'Jetson').mkdir(parents=True);(site/'Jetson/__init__.py').write_text('GPIO_PACKAGE=True\n')
        self.assertEqual(check_tree(eg,root/'supplier'),[])
        # Simulate absolute target-root links inside this isolated host fixture.
        for path in eg.rglob('*'):
            if path.is_symlink():
                target=root/'supplier'/os.readlink(path).lstrip('/');path.unlink();path.symlink_to(target)
        return eg,site

    def test_real_entrypoint_imports_with_competing_gpio_package(self):
        with tempfile.TemporaryDirectory() as d:
            eg,site=self.fixture(Path(d))
            with patch.dict(os.environ,{'PYTHONPATH':str(site)}):
                self.assertEqual(require_imports(eg/'config-by-hardware.py').returncode,0)
                (eg/'Jetson/__init__.py').unlink()
                with self.assertRaisesRegex(RuntimeError,'software preflight'):
                    require_imports(eg/'config-by-hardware.py')

    def test_missing_links_and_executable_mode_are_real_failures(self):
        with tempfile.TemporaryDirectory() as d:
            eg=Path(d)/'eg';eg.mkdir()
            (eg/'config-by-hardware.py').write_text('#!/usr/bin/env python3\n')
            errors=check_tree(eg)
            self.assertIn('Missing JetsonIO asset: Jetson/__init__.py',errors)
            self.assertIn('JetsonIO config-by-hardware.py is not executable',errors)
            with self.assertRaisesRegex(RuntimeError,'software preflight'):
                require_imports(eg/'config-by-hardware.py')

    def test_installation_xfail_never_accepts_an_import_error(self):
        def load_function(path,name,context):
            tree=ast.parse(path.read_text())
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),context)
            return context[name]
        failure=Mock(side_effect=RuntimeError('JetsonIO software preflight failed: ImportError'))
        context={'os':SimpleNamespace(path=SimpleNamespace(exists=lambda p:True)), 'require_imports':failure}
        check=load_function(ROOT/'test/qemu_install/test_apt_install.py','cbh_only_failure',context)
        for rc in (0,1):
            with self.assertRaisesRegex(RuntimeError,'ImportError'):check(rc)
        context=dict(os=SimpleNamespace(path=SimpleNamespace(exists=lambda p:True,basename=os.path.basename),makedirs=Mock()),
            Entry=object,BOOT='/boot',prepare_fixtures=Mock(),install_real_jetson_io=Mock(),setup_device_tree_symlink=Mock(),
            package_name_from_path=lambda p:'package',dpkg_purge=Mock(),dpkg_install=lambda e:(1,'','ImportError'),require_imports=failure)
        test=load_function(ROOT/'test/qemu_install/test_dpkg_install.py','test_one',context)
        result=test(SimpleNamespace(package_path='/package.deb',base_dtb='/base.dtb'),'fresh')
        self.assertEqual(result[0],'fail');self.assertIn('ImportError',result[1])

    def test_fresh_p3768_port_fallback_preserves_live_device_tree_counts(self):
        script=(ROOT/'sources/common/Linux_for_Tegra/rootfs/usr/bin/detect_jetson_board.sh').read_text()
        function=re.search(r'^detect_camera_ports\(\) \{.*?^\}',script,re.M|re.S).group()
        for compatible,count,expected,rc in [('nvidia,p3768-0000+p3767-0005-super',None,'2',0),
                                            ('nvidia,tegra234',None,'0',1),
                                            ('nvidia,p3768-0000+p3767-0005',4,'4',0)]:
            with self.subTest(compatible=compatible,count=count),tempfile.TemporaryDirectory() as d:
                root=Path(d)
                if count is not None:
                    p=root/'host1x@13e00000/nvcsi@15a00000/num-channels';p.parent.mkdir(parents=True);p.write_bytes(count.to_bytes(4,'big'))
                code='VERBOSE=0\n'+function.replace('/proc/device-tree',d)+'\ndetect_camera_ports "$1"\n'
                p=subprocess.run(['bash','-c',code,'test',compatible],capture_output=True,text=True)
                self.assertEqual((p.returncode,p.stdout.strip()),(rc,expected),p.stderr)

if __name__=='__main__':unittest.main()
