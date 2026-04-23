"""
dt_lib — libfdt-based DeviceTree parsing and validation for Jetson overlays.

Public API:
    from dt_lib import DeviceTree, Node
    from dt_lib.nvcsi import NVCSIRoot, CameraPlatform, Sensor
    from dt_lib.graph import trace_sensor_chain, ChainLink
    from dt_lib.checks import run_checks, CheckResult, CheckMode
"""
from .tree import DeviceTree, Node

__all__ = ["DeviceTree", "Node"]
