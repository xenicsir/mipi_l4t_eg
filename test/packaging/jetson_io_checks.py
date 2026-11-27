"""Validate the EG JetsonIO import graph independently of physical Jetson data."""
import os
from pathlib import Path
import subprocess

REQUIRED_FILES = (
    'config-by-hardware.py', 'Jetson/__init__.py', 'Jetson/board.py',
    'Jetson/header.py', 'Jetson/header_def.py', 'Jetson/io.py', 'Jetson/pmx.py',
    'Linux/__init__.py', 'Linux/debugfs.py', 'Linux/dt.py',
    'Linux/extlinux.py', 'Linux/pinctrl.py',
)
REQUIRED_DIRS = ('Headers', 'Utils')


def check_tree(directory, supplier_root=None):
    """Use lstat semantics: absolute target links are intentionally dangling on hosts."""
    directory = Path(directory)
    errors = []
    for relative in REQUIRED_FILES + REQUIRED_DIRS:
        path = directory/relative
        if path.is_symlink():
            target = os.readlink(path)
            if not target.startswith('/opt/nvidia/jetson-io/'):
                errors.append('Unexpected JetsonIO link target: %s -> %s' % (relative, target))
            elif supplier_root is not None:
                actual = Path(supplier_root)/target.lstrip('/')
                valid = actual.is_dir() if relative in REQUIRED_DIRS else actual.is_file()
                if not valid:
                    errors.append('Missing supplier JetsonIO target: '+target)
        elif not (path.is_dir() if relative in REQUIRED_DIRS else path.is_file()):
            errors.append('Missing JetsonIO asset: '+relative)
    entry = directory/'config-by-hardware.py'
    if not entry.is_file() or not os.access(entry, os.X_OK):
        errors.append('JetsonIO config-by-hardware.py is not executable')
    return errors


def require_imports(entry='/opt/eg/jetson-io/config-by-hardware.py'):
    """--help imports the real modules but exits before board/sysfs inspection."""
    try:
        result = subprocess.run([str(entry), '--help'], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('JetsonIO software preflight failed: '+str(exc)) from exc
    if result.returncode:
        raise RuntimeError('JetsonIO software preflight failed: '+
                           (result.stderr or result.stdout).strip())
    return result
