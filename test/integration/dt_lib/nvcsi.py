"""
Domain helpers for Jetson camera subsystem.

  NVCSIRoot      wraps /host1x@.../nvcsi@...      (channels, num_channels)
  TegraCaptureVI wraps /tegra-capture-vi          (ports)
  CameraPlatform wraps /tegra-camera-platform     (modules)

  find_active_sensors(dt)  → list of sensor nodes (xenics_*, ilumos_*, etc.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .tree import DeviceTree, Node


# Sensor node name prefixes we care about (our Exosens cameras + NVIDIA reference IMX)
EXOSENS_SENSOR_PREFIXES = (
    "xenics_dione_ir",
    "eg_ec",
    "ilumos",
    "microlynx",
)

REFERENCE_SENSOR_PREFIXES = (
    "rbpcv2_imx219",
    "rbpcv3_imx477",
)

# tegra_sinterface → expected port-index (T234 Orin mapping)
# serial_a..serial_h → 0..7
SERIAL_TO_PORT_INDEX = {
    f"serial_{chr(ord('a') + i)}": i for i in range(8)
}


@dataclass
class NVCSIRoot:
    node: Node

    @property
    def num_channels(self) -> Optional[int]:
        return self.node.get_u32("num-channels")

    def channels(self) -> list["Channel"]:
        return [Channel(n) for n in self.node.children_matching(r"channel@\d+")]

    def channel(self, idx: int) -> "Channel | None":
        n = self.node.child(f"channel@{idx}")
        return None if n is None else Channel(n)


@dataclass
class Channel:
    node: Node

    @property
    def index(self) -> int:
        return int(self.node.name.split("@", 1)[1], 0)

    @property
    def is_active(self) -> bool:
        return self.node.is_active

    def port(self, idx: int) -> "CSIPort | None":
        ports = self.node.child("ports")
        if ports is None:
            return None
        p = ports.child(f"port@{idx}")
        return None if p is None else CSIPort(p)

    def port0(self) -> "CSIPort | None":
        return self.port(0)

    def port1(self) -> "CSIPort | None":
        return self.port(1)


@dataclass
class CSIPort:
    node: Node

    @property
    def is_active(self) -> bool:
        return self.node.is_active

    def endpoints(self) -> list[Node]:
        # matches endpoint and endpoint@N
        return self.node.children_matching(r"endpoint(@\d+)?")

    def active_endpoints(self) -> list[Node]:
        return [e for e in self.endpoints() if e.is_active]


@dataclass
class TegraCaptureVI:
    node: Node

    def ports(self) -> list[Node]:
        ports = self.node.child("ports")
        if ports is None:
            return []
        return ports.children_matching(r"port@\d+")

    def port(self, idx: int) -> Node | None:
        ports = self.node.child("ports")
        if ports is None:
            return None
        return ports.child(f"port@{idx}")


@dataclass
class CameraPlatform:
    node: Node

    def modules_container(self) -> Node | None:
        return self.node.child("modules")

    def modules(self) -> list["CameraModule"]:
        m = self.modules_container()
        if m is None:
            return []
        return [CameraModule(n) for n in m.children_matching(r"module\d+")]

    def module(self, idx: int) -> "CameraModule | None":
        m = self.modules_container()
        if m is None:
            return None
        n = m.child(f"module{idx}")
        return None if n is None else CameraModule(n)


@dataclass
class CameraModule:
    node: Node

    @property
    def index(self) -> int:
        return int(re.search(r"\d+$", self.node.name).group(0))

    def drivernode0(self) -> Node | None:
        return self.node.child("drivernode0")

    @property
    def devname(self) -> str | None:
        dn = self.drivernode0()
        return None if dn is None else dn.get_string("devname")

    @property
    def proc_device_tree(self) -> str | None:
        dn = self.drivernode0()
        return None if dn is None else dn.get_string("proc-device-tree")


# ---------------------------------------------------------------------------
# Top-level lookups — handle 35.x vs 36.x path differences
# ---------------------------------------------------------------------------

_NVCSI_PATHS = [
    "/host1x@13e00000/nvcsi@15a00000",        # 35.x T234
    "/bus@0/host1x@13e00000/nvcsi@15a00000",  # 36.x T234
    "/host1x/nvcsi@150c0000",                 # 32.x T186
    "/host1x/nvcsi",                          # 32.x T210
]

_VI_PATHS = [
    "/tegra-capture-vi",   # T234 (35.x, 36.x) and T194 (Xavier)
    "/host1x/vi",          # T186 (TX2) and T210 (Nano porg)
]

_CAMERA_PLATFORM_PATHS = [
    "/tegra-camera-platform",
]


def find_nvcsi(dt: DeviceTree) -> NVCSIRoot | None:
    n = dt.node_at_any(*_NVCSI_PATHS)
    return None if n is None else NVCSIRoot(n)


def find_vi(dt: DeviceTree) -> TegraCaptureVI | None:
    n = dt.node_at_any(*_VI_PATHS)
    return None if n is None else TegraCaptureVI(n)


def find_camera_platform(dt: DeviceTree) -> CameraPlatform | None:
    n = dt.node_at_any(*_CAMERA_PLATFORM_PATHS)
    return None if n is None else CameraPlatform(n)


def find_active_sensors(dt: DeviceTree,
                        prefixes: tuple[str, ...] = EXOSENS_SENSOR_PREFIXES) -> list[Node]:
    """All sensor nodes with a matching name prefix, active, and with port@0/endpoint."""
    out = []
    for n in dt.root.descendants():
        if not any(n.name.startswith(p) for p in prefixes):
            continue
        if not n.is_active:
            continue
        ports = n.child("ports")
        if ports is None:
            continue
        p0 = ports.child_matching(r"port@0")
        if p0 is None:
            continue
        ep = p0.child_matching(r"endpoint(@\d+)?")
        if ep is None:
            continue
        out.append(n)
    return out


def find_sensors_by_compat(dt: DeviceTree, compat_substr: str) -> list[Node]:
    """Find all sensor nodes whose compatible property contains compat_substr."""
    return [n for n in dt.root.descendants()
            if any(compat_substr in c for c in n.compatible)]


def sensor_primary_endpoint(sensor: Node) -> Node | None:
    """Return the port@0/endpoint of a sensor, or None."""
    ports = sensor.child("ports")
    if ports is None:
        return None
    p0 = ports.child_matching(r"port@0")
    if p0 is None:
        return None
    return p0.child_matching(r"endpoint(@\d+)?")


def sensor_active_mode(sensor: Node) -> Node | None:
    """Return the first modeN child of a sensor (NVIDIA sensor mode convention)."""
    for c in sensor.children:
        if re.fullmatch(r"mode\d+", c.name):
            return c
    return None


def sensor_tegra_sinterface(sensor: Node) -> str | None:
    """Read tegra_sinterface from any modeN of the sensor (must be consistent)."""
    mode = sensor_active_mode(sensor)
    if mode is None:
        return None
    return mode.get_string("tegra_sinterface")


def expected_port_index_for_serial(serial: str) -> int | None:
    """serial_a=0, serial_b=1, ... serial_h=7. None if unrecognized."""
    return SERIAL_TO_PORT_INDEX.get(serial)
