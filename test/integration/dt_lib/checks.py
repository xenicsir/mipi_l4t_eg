"""
Integrity checks over a merged Device Tree.

Validation is SENSOR-CENTRIC: we start from active Exosens sensor nodes
(xenics_dione_ir, eg_ec, ilumos, microlynx) and only validate what belongs
to their chain. NVIDIA heritage (disabled reference sensors, unused
channels, inherited camera-platform modules) is intentionally ignored —
those are not bugs, they are leftovers from the base DTB that do not
affect runtime.

Two modes:
  BASE_ONLY  — only the base DTBO applied, no per-port camera overlay.
               Skips per-camera lookups (sensor presence by camera name,
               bus-width match).
  PER_PORT   — base + per-port camera overlay applied. All checks run.

Each check returns CheckResult(label, status, detail).
status ∈ {"ok", "skip", "FAIL"}.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .tree import DeviceTree, Node
from .graph import trace_sensor_chain
from .nvcsi import (
    NVCSIRoot, TegraCaptureVI, CameraPlatform,
    find_nvcsi, find_vi, find_camera_platform,
    find_active_sensors, sensor_primary_endpoint, sensor_tegra_sinterface,
    expected_port_index_for_serial,
    EXOSENS_SENSOR_PREFIXES, REFERENCE_SENSOR_PREFIXES,
)


class CheckMode(Enum):
    BASE_ONLY = "base_only"
    PER_PORT = "per_port"


@dataclass
class CheckResult:
    label: str
    status: str                  # "ok" | "skip" | "FAIL"
    detail: str = ""

    def __str__(self) -> str:
        if self.detail:
            return f"{self.status}: {self.label} — {self.detail}"
        return f"{self.status}: {self.label}"


def _ok(label: str, detail: str = "") -> CheckResult:
    return CheckResult(label, "ok", detail)


def _fail(label: str, detail: str) -> CheckResult:
    return CheckResult(label, "FAIL", detail)


def _skip(label: str, detail: str = "") -> CheckResult:
    return CheckResult(label, "skip", detail)


# Camera name → expected sensor name prefix and CSI bus width
CAMERA_NODE = {
    "Dione":        ("xenics_dione", 2),
    "MicroCube":    ("eg_ec",        1),
    "MicroCube640": ("eg_ec",        1),
    "SmartIR640":   ("eg_ec",        2),
    "Crius1280":    ("eg_ec",        2),
    "iLumos":       ("ilumos",       2),
    "Microlynx":    ("microlynx",    2),
}

# Device-name prefixes used by tegra-camera-platform/moduleN/drivernode0/devname
# for our Exosens cameras. Any other devname is considered NVIDIA-inherited
# and is not validated (not our responsibility to clean up the base DTB).
EXOSENS_DEVNAME_PREFIXES = ("dione_ir", "eg_ec", "ilumos", "microlynx")


# ---------------------------------------------------------------------------
# Scope helpers — which (channel, port) tuples are actually used by Exosens?
# ---------------------------------------------------------------------------

def find_exosens_used_channels(dt: DeviceTree) -> set[int]:
    """Return set of NVCSI channel indices reached by active Exosens sensors."""
    used: set[int] = set()
    for sensor in find_active_sensors(dt):
        ep = sensor_primary_endpoint(sensor)
        if ep is None:
            continue
        nvcsi_in = ep.remote_endpoint()
        if nvcsi_in is None:
            continue
        # Walk up until we find channel@N
        n = nvcsi_in.parent
        while n is not None and not re.fullmatch(r"channel@\d+", n.name):
            n = n.parent
        if n is not None:
            idx = int(n.name.split("@", 1)[1], 0)
            used.add(idx)
    return used


def _sensor_devname_is_exosens(devname: str | None) -> bool:
    if devname is None:
        return False
    return any(devname.startswith(p + " ") for p in EXOSENS_DEVNAME_PREFIXES)


# ---------------------------------------------------------------------------
# Check: at least one active Exosens sensor (the overlay actually activated something)
# ---------------------------------------------------------------------------

def check_any_exosens_sensor_active(dt: DeviceTree) -> list[CheckResult]:
    label = "exosens_sensor_present"
    sensors = find_active_sensors(dt)
    if not sensors:
        return [_fail(label, "no active Exosens sensor in merged DT")]
    return [_ok(label, f"{len(sensors)} active: "
                f"{', '.join(s.name for s in sensors[:4])}")]


# ---------------------------------------------------------------------------
# Check: when camera is specified (PER_PORT), the requested camera must be active
# ---------------------------------------------------------------------------

def check_camera_sensor_active(dt: DeviceTree, camera: str) -> list[CheckResult]:
    label = f"camera_sensor_active[{camera}]"
    if camera not in CAMERA_NODE:
        return [_skip(label, f"unknown camera {camera!r}")]
    prefix, _ = CAMERA_NODE[camera]
    found = [n for n in dt.root.descendants()
             if n.name.startswith(prefix) and n.is_active]
    if not found:
        return [_fail(label, f"no active sensor with name prefix {prefix!r}")]
    return [_ok(label, f"{len(found)} active: {found[0].name}")]


# ---------------------------------------------------------------------------
# Check: no active IMX219 / IMX477 reference sensors (we disable them)
# ---------------------------------------------------------------------------

def check_no_reference_imx(dt: DeviceTree) -> list[CheckResult]:
    out = []
    for prefix in REFERENCE_SENSOR_PREFIXES:
        label = f"no_active[{prefix}]"
        active = [n for n in dt.root.descendants()
                  if n.name.startswith(prefix) and n.is_active]
        if active:
            out.append(_fail(label, f"{len(active)} active: {[n.path for n in active[:3]]}"))
        else:
            out.append(_ok(label))
    return out


# ---------------------------------------------------------------------------
# Check: infrastructure of USED channels only (sensor-centric)
# ---------------------------------------------------------------------------

def check_used_channels_infrastructure(dt: DeviceTree,
                                       used_channels: set[int]) -> list[CheckResult]:
    """For each channel used by an active Exosens sensor, verify that the
    channel node, its port@0, port@1, and the corresponding VI port@N are
    all active.  Channels NOT used by Exosens are ignored entirely."""
    out: list[CheckResult] = []
    nvcsi = find_nvcsi(dt)
    vi = find_vi(dt)

    if nvcsi is None:
        return [_fail("nvcsi", "NVCSI root node not found")]

    if not used_channels:
        out.append(_skip("used_channels", "no active Exosens sensor → nothing to validate"))
        return out

    for ch_idx in sorted(used_channels):
        ch = nvcsi.channel(ch_idx)
        label_ch = f"nvcsi/channel@{ch_idx}"
        if ch is None:
            out.append(_fail(label_ch, "used by Exosens sensor but absent from DT"))
            continue
        if not ch.is_active:
            out.append(_fail(label_ch, "disabled"))
            continue
        out.append(_ok(label_ch))

        for side in (0, 1):
            p = ch.port(side)
            plabel = f"{label_ch}/port@{side}"
            if p is None:
                # Implicit-okay per DT spec; but for a used channel we expect
                # both ports to exist. Tolerate absent port@1 on overlays that
                # leave it implicit.
                out.append(_ok(plabel, "absent (implicit-okay)"))
            elif not p.is_active:
                out.append(_fail(plabel, "disabled"))
            else:
                out.append(_ok(plabel))

        if vi is not None:
            vp = vi.port(ch_idx)
            vlabel = f"vi/port@{ch_idx}"
            if vp is None:
                out.append(_ok(vlabel, "absent (implicit-okay)"))
            elif not vp.is_active:
                out.append(_fail(vlabel, "disabled"))
            else:
                out.append(_ok(vlabel))

    return out


# ---------------------------------------------------------------------------
# Check: bus-width on the active camera endpoint (PER_PORT only)
# ---------------------------------------------------------------------------

def check_active_endpoint_bus_width(dt: DeviceTree,
                                    camera: str, port: int,
                                    l4t_mode: str) -> list[CheckResult]:
    label = f"nvcsi/channel@{port}/port@0/endpoint.bus-width"
    if camera not in CAMERA_NODE:
        return [_skip(label, f"unknown camera {camera!r}")]
    _, expected_bw = CAMERA_NODE[camera]

    nvcsi = find_nvcsi(dt)
    if nvcsi is None:
        return [_skip(label, "no NVCSI")]
    ch = nvcsi.channel(port)
    if ch is None:
        return [_skip(label, f"channel@{port} absent")]
    p0 = ch.port(0)
    if p0 is None:
        return [_skip(label, "port@0 absent")]

    # Endpoint index convention: 36.x → port*2, 35.x/32.x → 0
    ep_idx = port * 2 if l4t_mode == "36x" else 0
    ep = p0.node.child(f"endpoint@{ep_idx}")
    if ep is None or not ep.is_active:
        actives = list(p0.active_endpoints())
        if not actives:
            return [_fail(label, "no active endpoint")]
        ep = actives[0]

    bw = ep.get_u32("bus-width")
    if bw is None:
        return [_ok(label, "no bus-width property")]
    if bw != expected_bw:
        return [_fail(label, f"bus-width={bw} expected {expected_bw}")]
    return [_ok(label, f"bus-width={bw}")]


# ---------------------------------------------------------------------------
# Check: graph traversal from each active Exosens sensor
# ---------------------------------------------------------------------------

def _csi5_port_to_stream(csi_port: int) -> int:
    """Map a raw NVCSI port index (0-7, A-H) to its RTCPU stream ID (0-5).

    Mirrors csi5_port_to_stream() in drivers/media/platform/tegra/camera/nvcsi/csi5_fops.c:
      - Ports A-D (0-3): stream = port  (one brick per port)
      - Ports E-H (4-7): pairs share a stream: (E,F)→4, (G,H)→5

    The VI endpoint's port-index must equal this stream ID (used directly as
    csi_stream_id in vi5_fops.c). MAX_NVCSI_STREAM_IDS=6 so valid range is 0-5.
    """
    NVCSI_PORT_E = 4
    if csi_port < NVCSI_PORT_E:
        return csi_port
    return ((csi_port - NVCSI_PORT_E) >> 1) + NVCSI_PORT_E


def check_sensor_graph_chains(dt: DeviceTree, camera: Optional[str] = None) -> list[CheckResult]:
    out = []
    sensors = find_active_sensors(dt)
    if camera is not None:
        prefix = CAMERA_NODE.get(camera, ("",))[0]
        sensors = [s for s in sensors if s.name.startswith(prefix)]
    for s in sensors:
        label = f"graph[{s.name}]"
        ep = sensor_primary_endpoint(s)
        if ep is None:
            out.append(_skip(label, "no primary endpoint"))
            continue
        r = trace_sensor_chain(ep)
        if not r.ok:
            out.append(_fail(label, "; ".join(r.errors)))
            continue
        out.append(_ok(label, r.describe()))
        # The VI endpoint's port-index is used directly as RTCPU csi_stream_id.
        # It must equal csi5_port_to_stream(nvcsi_in.port_index), where
        # nvcsi_in.port_index is the raw NVCSI port (0-7). For ports 0-3 the
        # stream equals the port, for 4-7 pairs share a stream (E/F→4, G/H→5).
        # Mismatch causes "Invalid NVCSI stream Id" kernel crash at stream time.
        nvcsi_in_link = next((lnk for lnk in r.links if lnk.role == "nvcsi_in"), None)
        vi_link = next((lnk for lnk in r.links if lnk.role == "vi"), None)
        if (nvcsi_in_link is not None and vi_link is not None
                and nvcsi_in_link.port_index is not None
                and vi_link.port_index is not None):
            expected_stream = _csi5_port_to_stream(nvcsi_in_link.port_index)
            if vi_link.port_index != expected_stream:
                out.append(_fail(f"vi_port_index[{s.name}]",
                    f"NVCSI port-index={nvcsi_in_link.port_index} → "
                    f"expected stream={expected_stream} but "
                    f"VI endpoint port-index={vi_link.port_index} "
                    f"(fix: set VI endpoint port-index={expected_stream})"))
    if not sensors:
        out.append(_skip("graph", "no active Exosens sensors"))
    return out


# ---------------------------------------------------------------------------
# Check: tegra_sinterface ↔ port-index coherence on Exosens sensors
# (strict — we want to flag DTSI inconsistencies even when the driver tolerates them)
# ---------------------------------------------------------------------------

def check_sinterface_port_index(dt: DeviceTree) -> list[CheckResult]:
    """Check that tegra_sinterface matches port-index.

    Ground truth is `port-index` (used by the Tegra driver at runtime).
    `tegra_sinterface` is informational and often wrong; the driver ignores
    the mismatch so the overlay still works.  When this check fails, the fix
    is always to update `tegra_sinterface` in the DTSI to match `port-index`,
    NEVER the other way around (that would break a working overlay).
    """
    out = []
    for s in find_active_sensors(dt):
        label = f"sinterface_port_index[{s.name}]"
        si = sensor_tegra_sinterface(s)
        if si is None:
            out.append(_skip(label, "no tegra_sinterface in modeN"))
            continue
        ep = sensor_primary_endpoint(s)
        if ep is None:
            out.append(_skip(label, "no primary endpoint"))
            continue
        pi_sensor = ep.get_u32("port-index")
        if pi_sensor is None:
            out.append(_skip(label, "no port-index on sensor endpoint"))
            continue

        # port-index is ground truth: compute what tegra_sinterface SHOULD be.
        expected_si = f"serial_{chr(ord('a') + pi_sensor)}" if 0 <= pi_sensor <= 7 else None
        if si != expected_si:
            out.append(_fail(label,
                f"port-index={pi_sensor} → tegra_sinterface should be {expected_si!r} "
                f"but is {si!r} (fix: update tegra_sinterface in DTSI, NOT port-index)"))
            continue

        # Also verify the NVCSI side port-index matches (a mismatch here IS a
        # real bug — the overlay is wiring the sensor to the wrong CSI pipe).
        nvcsi_in = ep.remote_endpoint()
        if nvcsi_in is not None:
            pi_nvcsi = nvcsi_in.get_u32("port-index")
            if pi_nvcsi is not None and pi_nvcsi != pi_sensor:
                out.append(_fail(label,
                    f"sensor port-index={pi_sensor} but NVCSI endpoint port-index={pi_nvcsi}"))
                continue
        out.append(_ok(label, f"{si}↔pi={pi_sensor}"))
    if not out:
        out.append(_skip("sinterface_port_index", "no active Exosens sensors"))
    return out


# ---------------------------------------------------------------------------
# Check: endpoint conflicts in USED NVCSI ports (sensor-centric)
# ---------------------------------------------------------------------------

def check_endpoint_conflicts(dt: DeviceTree,
                             used_channels: set[int]) -> list[CheckResult]:
    """For each NVCSI channel@N/port@M where N is used by an Exosens sensor:
      - at most 1 active endpoint
      - no broken remote-endpoint phandles (the Tegra VI driver scans ALL
        endpoint children of a port regardless of status)
    """
    out = []
    nvcsi = find_nvcsi(dt)
    if nvcsi is None or not used_channels:
        return out
    phandle_idx = dt.phandle_index()

    for ch_idx in sorted(used_channels):
        ch = nvcsi.channel(ch_idx)
        if ch is None:
            continue
        for side in (0, 1):
            p = ch.port(side)
            if p is None:
                continue
            label = f"nvcsi/channel@{ch_idx}/port@{side}"
            eps = p.endpoints()
            actives = [e for e in eps if e.is_active]

            if len(actives) > 1:
                out.append(_fail(f"{label}.active_count",
                    f"{len(actives)} active endpoints (max 1): "
                    + ",".join(e.name for e in actives)))

            for e in eps:
                re_ph = e.get_u32("remote-endpoint")
                if re_ph is None:
                    if e.is_active:
                        out.append(_fail(f"{label}/{e.name}.remote-endpoint",
                            "active endpoint without remote-endpoint"))
                    else:
                        out.append(_fail(f"{label}/{e.name}.remote-endpoint",
                            "disabled endpoint without remote-endpoint (still scanned by driver)"))
                    continue
                if re_ph not in phandle_idx:
                    out.append(_fail(f"{label}/{e.name}.remote-endpoint",
                        f"phandle 0x{re_ph:x} → no node (orphaned link)"))
    return out


# ---------------------------------------------------------------------------
# Check: tegra-camera-platform/modules coherence for EXOSENS modules only
# ---------------------------------------------------------------------------

def check_exosens_modules(dt: DeviceTree) -> list[CheckResult]:
    """Only validate camera-platform modules whose devname starts with an
    Exosens prefix (dione_ir, eg_ec, ilumos, microlynx). NVIDIA-inherited
    modules (ov5693, ar0234, imx274, imx219, ...) are not our concern and
    are intentionally left alone in the overlay."""
    out = []
    cp = find_camera_platform(dt)
    if cp is None:
        return [_skip("camera-platform", "/tegra-camera-platform absent")]

    modules = cp.modules()
    if not modules:
        return [_skip("camera-platform", "no modules")]

    checked = 0
    for mod in modules:
        devname = mod.devname
        if not _sensor_devname_is_exosens(devname):
            continue
        checked += 1
        label = f"camera-platform/module{mod.index}[{devname}]"
        proc = mod.proc_device_tree
        if proc is None:
            out.append(_fail(label, "no proc-device-tree"))
            continue
        if proc.startswith("/proc/device-tree"):
            target_path = proc[len("/proc/device-tree"):]
        else:
            target_path = proc
        if not target_path.startswith("/"):
            target_path = "/" + target_path
        # On 36.x, top-level buses live under /bus@0/ whereas the overlays
        # still write the 35.x-style path without the prefix. Try both.
        target = dt.node_at_path(target_path)
        if target is None and not target_path.startswith("/bus@0/"):
            target = dt.node_at_path("/bus@0" + target_path)
        if target is None:
            out.append(_fail(label, f"proc-device-tree target absent: {target_path}"))
            continue
        if not target.is_active:
            out.append(_fail(label, f"proc-device-tree target disabled: {target_path}"))
            continue
        out.append(_ok(label, f"→ {target.name}"))

    if checked == 0:
        out.append(_skip("camera-platform", "no Exosens-owned modules"))
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_checks(dt: DeviceTree,
               mode: CheckMode,
               camera: Optional[str] = None,
               port: Optional[int] = None,
               l4t_mode: str = "36x",
               total_ports: int = 4) -> list[CheckResult]:
    """Run the appropriate battery of checks for the given mode."""
    out: list[CheckResult] = [_ok("dtb_parseable")]

    # Reference IMX must never be active (we disable them)
    out += check_no_reference_imx(dt)

    # At least one active Exosens sensor must exist
    out += check_any_exosens_sensor_active(dt)

    # Graph chains: only for the configured camera (PER_PORT), skipped in BASE_ONLY
    # (BASE_ONLY checks infrastructure, not per-sensor chains)
    if mode == CheckMode.PER_PORT:
        out += check_sensor_graph_chains(dt, camera=camera)

    # Sensor-centric infrastructure: only validate used channels + their VI port
    used_channels = find_exosens_used_channels(dt)
    out += check_used_channels_infrastructure(dt, used_channels)

    # Strict sinterface/port-index coherence on Exosens sensors
    out += check_sinterface_port_index(dt)

    # Endpoint conflicts only in used NVCSI ports
    out += check_endpoint_conflicts(dt, used_channels)

    # camera-platform modules: only Exosens-owned modules
    out += check_exosens_modules(dt)

    # PER_PORT mode adds per-camera sensor check and bus-width on that port
    if mode == CheckMode.PER_PORT:
        if camera is not None:
            out += check_camera_sensor_active(dt, camera)
        if camera is not None and port is not None:
            out += check_active_endpoint_bus_width(dt, camera, port, l4t_mode)

    return out


def summarize(results: list[CheckResult]) -> tuple[int, int, int]:
    """Return (n_ok, n_skip, n_fail)."""
    ok = sum(1 for r in results if r.status == "ok")
    sk = sum(1 for r in results if r.status == "skip")
    fl = sum(1 for r in results if r.status == "FAIL")
    return ok, sk, fl
