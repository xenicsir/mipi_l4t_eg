"""
Graph traversal over DT endpoints (of_graph).

Jetson CSI pipeline:

    sensor@addr
      └─ ports/port@0/endpoint                 [A]  (camera side)
          └─ remote-endpoint = <NVCSI_in>      [B]

    nvcsi@.../channel@N
      └─ ports/port@0/endpoint@K               [B]  (camera-side input)
          └─ remote-endpoint = <A>
      └─ ports/port@1/endpoint@K+1             [C]  (VI-side output)
          └─ remote-endpoint = <D>

    tegra-capture-vi/ports/port@N/endpoint     [D]
      └─ remote-endpoint = <C>

Each hop MUST be reciprocal: B's remote is A, and A's remote is B.
Each intermediate node (ports container, channel, port@X) must be active.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .tree import DeviceTree, Node


@dataclass
class ChainLink:
    """One endpoint in the traversal chain."""
    node: Node
    role: str                                        # "sensor" | "nvcsi_in" | "nvcsi_out" | "vi"
    port_index: Optional[int] = None                 # port-index property value
    bus_width: Optional[int] = None                  # bus-width property value

    def __repr__(self) -> str:
        return f"<{self.role} {self.node.path} pi={self.port_index} bw={self.bus_width}>"


@dataclass
class ChainResult:
    """Result of trace_sensor_chain. links is populated up to the failure point.

    errors    — fatal issues in phase A (sensor → NVCSI_in). These block runtime.
    warnings  — issues in phase B (NVCSI_in → NVCSI_out → VI). The Tegra driver
                often tolerates an incomplete port@1/VI chain because the
                NVCSI↔VI binding is also resolved at probe time without going
                through a DT graph link. Report but don't FAIL the overall check.
    """
    links: list[ChainLink] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def describe(self) -> str:
        path = " → ".join(f"{l.role}(pi={l.port_index})" for l in self.links)
        parts = [path]
        if self.errors:
            parts.append("errors: " + "; ".join(self.errors))
        if self.warnings:
            parts.append("warn: " + "; ".join(self.warnings))
        return " | ".join(parts)


def _endpoint_port_index(ep: Node) -> Optional[int]:
    return ep.get_u32("port-index")


def _endpoint_bus_width(ep: Node) -> Optional[int]:
    return ep.get_u32("bus-width")


def _reciprocal_check(a: Node, b: Node) -> Optional[str]:
    """Return an error string if a.remote != b or b.remote != a."""
    ar = a.remote_endpoint()
    br = b.remote_endpoint()
    if ar is None:
        return f"{a.path} has no remote-endpoint"
    if br is None:
        return f"{b.path} has no remote-endpoint"
    if ar != b:
        return f"{a.path}.remote → {ar.path} expected {b.path}"
    if br != a:
        return f"{b.path}.remote → {br.path} expected {a.path}"
    return None


def _channel_port1_endpoint(channel: Node) -> Optional[Node]:
    """Return the NVCSI-out endpoint inside channel@N/ports/port@1.
    A channel's port@1 typically has exactly one endpoint; if several,
    take the first active one."""
    ports = channel.child("ports")
    if ports is None:
        return None
    p1 = ports.child_matching(r"port@1")
    if p1 is None:
        return None
    for ep in p1.children_matching(r"endpoint(@\d+)?"):
        if ep.is_active:
            return ep
    return None


def trace_sensor_chain(sensor_endpoint: Node) -> ChainResult:
    """
    Starting from a sensor's ports/port@0/endpoint, walk:
      sensor_ep → NVCSI_in_ep (channel@N/port@0/endpoint@K)
                → NVCSI_out_ep (channel@N/port@1/endpoint@K+1)
                → VI_ep (tegra-capture-vi/ports/port@N/endpoint)

    Every step validates reciprocal remote-endpoint and
    status-active on each ancestor node.
    """
    res = ChainResult()

    # Link 1: sensor endpoint
    if not sensor_endpoint.is_ancestor_active:
        res.errors.append(f"sensor endpoint ancestor disabled: {sensor_endpoint.path}")
    res.links.append(ChainLink(
        sensor_endpoint, role="sensor",
        port_index=_endpoint_port_index(sensor_endpoint),
        bus_width=_endpoint_bus_width(sensor_endpoint),
    ))

    # Link 2: NVCSI input endpoint (via remote-endpoint from sensor)
    nvcsi_in = sensor_endpoint.remote_endpoint()
    if nvcsi_in is None:
        res.errors.append(f"{sensor_endpoint.path}: remote-endpoint missing or broken")
        return res
    # reciprocal check sensor ↔ nvcsi_in
    err = _reciprocal_check(sensor_endpoint, nvcsi_in)
    if err:
        res.errors.append(err)
        return res
    if not nvcsi_in.is_ancestor_active:
        res.errors.append(f"NVCSI in endpoint ancestor disabled: {nvcsi_in.path}")
    res.links.append(ChainLink(
        nvcsi_in, role="nvcsi_in",
        port_index=_endpoint_port_index(nvcsi_in),
        bus_width=_endpoint_bus_width(nvcsi_in),
    ))

    # -----------------------------------------------------------------
    # Phase B — NVCSI_in → channel → NVCSI_out → VI  (non-fatal: warnings)
    # -----------------------------------------------------------------
    channel = nvcsi_in.parent
    while channel is not None and not _looks_like_channel(channel):
        channel = channel.parent
    if channel is None:
        res.warnings.append(f"{nvcsi_in.path}: no channel@N ancestor")
        return res

    nvcsi_out = _channel_port1_endpoint(channel)
    if nvcsi_out is None:
        res.warnings.append(f"{channel.path}: no active endpoint in port@1")
        return res
    if not nvcsi_out.is_ancestor_active:
        res.warnings.append(f"NVCSI out endpoint ancestor disabled: {nvcsi_out.path}")
    res.links.append(ChainLink(
        nvcsi_out, role="nvcsi_out",
        port_index=_endpoint_port_index(nvcsi_out),
        bus_width=_endpoint_bus_width(nvcsi_out),
    ))

    vi_ep = nvcsi_out.remote_endpoint()
    if vi_ep is None:
        res.warnings.append(f"{nvcsi_out.path}: remote-endpoint missing or broken")
        return res
    rerr = _reciprocal_check(nvcsi_out, vi_ep)
    if rerr:
        res.warnings.append(rerr)
        return res
    if not vi_ep.is_ancestor_active:
        res.warnings.append(f"VI endpoint ancestor disabled: {vi_ep.path}")
    res.links.append(ChainLink(
        vi_ep, role="vi",
        port_index=_endpoint_port_index(vi_ep),
        bus_width=_endpoint_bus_width(vi_ep),
    ))

    # VI endpoint must be under a recognised VI root (T234: tegra-capture-vi ;
    # T210/T186/T194: host1x/vi).
    path = vi_ep.path
    if "tegra-capture-vi" not in path and "/host1x/vi" not in path:
        res.warnings.append(f"VI endpoint not under recognised VI root: {path}")

    return res


def _looks_like_channel(node: Node) -> bool:
    """Heuristic: NVCSI channel nodes are named channel@N."""
    import re
    return bool(re.fullmatch(r"channel@\d+", node.name))
