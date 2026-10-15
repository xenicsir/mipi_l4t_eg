#!/usr/bin/env python3
"""Compatibility entry point for exosensCamCtrl.py; an explicit device is required."""

from functools import partial
import os
import sys

# Compatibility wrappers live alongside the standalone implementation.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import exosensCamCtrl as _ctrl

read_reg32 = partial(_ctrl.read_reg32, camera_type='ilumos')
read_reg32f = partial(_ctrl.read_reg32f, camera_type='ilumos')
write_reg32 = partial(_ctrl.write_reg32, camera_type='ilumos')
write_reg32f = partial(_ctrl.write_reg32f, camera_type='ilumos')
read_string = partial(_ctrl.read_string, camera_type='ilumos')
console = partial(_ctrl.console, camera_type='ilumos')
main = partial(_ctrl.main, camera_type='ilumos')

if __name__ == '__main__':
    sys.exit(main())
