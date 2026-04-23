"""
Device Tree object model over pylibfdt.

DeviceTree wraps an FDT blob and exposes nodes as Node objects.
Node provides typed property access, status resolution (with implicit-okay),
phandle lookup, and child navigation by name or pattern.

Usage:
    dt = DeviceTree.from_dtb("/boot/kernel_merged.dtb")
    nvcsi = dt.node_at_path("/host1x@13e00000/nvcsi@15a00000")
    for ch in nvcsi.children_matching(r'channel@\\d+'):
        if ch.is_active:
            ...
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from typing import Iterator

import libfdt


STATUS_OKAY = "okay"
STATUS_DISABLED = "disabled"
STATUS_IMPLICIT_OKAY = "implicit-okay"


class DeviceTree:
    """Wrapper around libfdt.Fdt with cached Node objects and phandle index."""

    def __init__(self, dtb_bytes: bytes):
        self._fdt = libfdt.Fdt(dtb_bytes)
        self._node_cache: dict[int, Node] = {}
        self._phandle_cache: dict[int, Node] | None = None

    @classmethod
    def from_dtb(cls, path: str) -> "DeviceTree":
        with open(path, "rb") as f:
            return cls(f.read())

    @classmethod
    def from_dts(cls, path: str) -> "DeviceTree":
        """Compile a .dts source file to DTB via dtc, then parse."""
        with tempfile.NamedTemporaryFile(suffix=".dtb", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            r = subprocess.run(
                ["dtc", "-I", "dts", "-O", "dtb", "-o", tmp_path, path],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise ValueError(f"dtc failed on {path}: {r.stderr.strip()}")
            return cls.from_dtb(tmp_path)
        finally:
            import os
            try: os.remove(tmp_path)
            except OSError: pass

    @property
    def root(self) -> "Node":
        return self.node_at(0)

    def node_at(self, offset: int) -> "Node":
        """Get a Node by its FDT offset (cached)."""
        cached = self._node_cache.get(offset)
        if cached is not None:
            return cached
        n = Node(self, offset)
        self._node_cache[offset] = n
        return n

    def node_at_path(self, path: str) -> "Node | None":
        """Lookup a node by absolute path. Returns None if absent."""
        try:
            off = self._fdt.path_offset(path)
        except libfdt.FdtException:
            return None
        if off < 0:
            return None
        return self.node_at(off)

    def node_by_phandle(self, phandle: int) -> "Node | None":
        """Lookup a node by its phandle value. Returns None if absent."""
        off = self._fdt.node_offset_by_phandle(phandle, libfdt.QUIET_NOTFOUND)
        if off < 0:
            return None
        return self.node_at(off)

    def phandle_index(self) -> dict[int, "Node"]:
        """Return dict of all phandles in the DTB → Node. Built lazily, cached."""
        if self._phandle_cache is not None:
            return self._phandle_cache
        idx: dict[int, Node] = {}
        for n in self._iter_all_nodes():
            ph = n.phandle
            if ph is not None:
                idx[ph] = n
        self._phandle_cache = idx
        return idx

    def _iter_all_nodes(self) -> Iterator["Node"]:
        """Depth-first iteration over every node in the DTB."""
        def walk(offset: int):
            yield self.node_at(offset)
            child = self._fdt.first_subnode(offset, libfdt.QUIET_NOTFOUND)
            while child >= 0:
                yield from walk(child)
                child = self._fdt.next_subnode(child, libfdt.QUIET_NOTFOUND)
        yield from walk(0)

    def all_nodes(self) -> list["Node"]:
        return list(self._iter_all_nodes())

    # --- Helpers for paths that differ between 35.x and 36.x ---

    def node_at_any(self, *paths: str) -> "Node | None":
        """Try each candidate path, return the first match. Useful for
        /host1x vs /bus@0/host1x (36.x prefix)."""
        for p in paths:
            n = self.node_at_path(p)
            if n is not None:
                return n
        return None


class Node:
    """A single DT node. Properties are accessed via typed getters."""

    __slots__ = ("_dt", "_offset")

    def __init__(self, dt: DeviceTree, offset: int):
        self._dt = dt
        self._offset = offset

    # --- identity ---

    @property
    def name(self) -> str:
        return self._dt._fdt.get_name(self._offset)

    @property
    def path(self) -> str:
        return self._dt._fdt.get_path(self._offset)

    @property
    def offset(self) -> int:
        return self._offset

    def __repr__(self) -> str:
        return f"<Node {self.path}>"

    def __eq__(self, other) -> bool:
        return isinstance(other, Node) and other._offset == self._offset and other._dt is self._dt

    def __hash__(self) -> int:
        return hash((id(self._dt), self._offset))

    # --- navigation ---

    @property
    def parent(self) -> "Node | None":
        if self._offset == 0:
            return None
        po = self._dt._fdt.parent_offset(self._offset, libfdt.QUIET_NOTFOUND)
        return None if po < 0 else self._dt.node_at(po)

    @property
    def children(self) -> list["Node"]:
        out: list[Node] = []
        c = self._dt._fdt.first_subnode(self._offset, libfdt.QUIET_NOTFOUND)
        while c >= 0:
            out.append(self._dt.node_at(c))
            c = self._dt._fdt.next_subnode(c, libfdt.QUIET_NOTFOUND)
        return out

    def child(self, name: str) -> "Node | None":
        """Exact name match on immediate children."""
        for c in self.children:
            if c.name == name:
                return c
        return None

    def children_matching(self, pattern: str) -> list["Node"]:
        """Regex match on immediate children names."""
        rx = re.compile(pattern)
        return [c for c in self.children if rx.fullmatch(c.name)]

    def child_matching(self, pattern: str) -> "Node | None":
        m = self.children_matching(pattern)
        return m[0] if m else None

    def descendants(self) -> Iterator["Node"]:
        """Depth-first iteration over all descendants (excluding self)."""
        def walk(off):
            c = self._dt._fdt.first_subnode(off, libfdt.QUIET_NOTFOUND)
            while c >= 0:
                yield self._dt.node_at(c)
                yield from walk(c)
                c = self._dt._fdt.next_subnode(c, libfdt.QUIET_NOTFOUND)
        yield from walk(self._offset)

    def find_by_name_prefix(self, prefix: str) -> list["Node"]:
        """All descendants whose name starts with `prefix`."""
        return [n for n in self.descendants() if n.name.startswith(prefix)]

    def find_by_compatible(self, compat: str) -> list["Node"]:
        """All descendants whose compatible property contains `compat`."""
        return [n for n in self.descendants() if compat in n.compatible]

    # --- properties ---

    def has_prop(self, name: str) -> bool:
        return self._getprop(name) is not None

    def prop_names(self) -> list[str]:
        out = []
        po = self._dt._fdt.first_property_offset(self._offset, libfdt.QUIET_NOTFOUND)
        while po >= 0:
            out.append(self._dt._fdt.get_property_by_offset(po).name)
            po = self._dt._fdt.next_property_offset(po, libfdt.QUIET_NOTFOUND)
        return out

    def _getprop(self, name: str):
        """Raw getprop → Property object or None. Handles pylibfdt's int-error return."""
        p = self._dt._fdt.getprop(self._offset, name, libfdt.QUIET_NOTFOUND)
        # pylibfdt returns a negative int (FDT_ERR_*) instead of None for missing props
        if p is None or isinstance(p, int):
            return None
        return p

    def get_bytes(self, name: str) -> bytes | None:
        p = self._getprop(name)
        return None if p is None else bytes(p)

    def get_u32(self, name: str) -> int | None:
        p = self._getprop(name)
        if p is None or len(p) < 4:
            return None
        return p.as_uint32()

    def get_u32_list(self, name: str) -> list[int] | None:
        b = self.get_bytes(name)
        if b is None or len(b) % 4 != 0:
            return None
        return [int.from_bytes(b[i:i+4], "big") for i in range(0, len(b), 4)]

    def get_string(self, name: str) -> str | None:
        """First null-terminated string in the property."""
        b = self.get_bytes(name)
        if b is None:
            return None
        return b.rstrip(b"\x00").split(b"\x00")[0].decode("ascii", errors="replace")

    def get_string_list(self, name: str) -> list[str]:
        """List of null-terminated strings (compatible, etc.)."""
        b = self.get_bytes(name)
        if b is None:
            return []
        return [s.decode("ascii", errors="replace")
                for s in b.rstrip(b"\x00").split(b"\x00") if s]

    # --- semantic helpers ---

    @property
    def status(self) -> str:
        """Return 'okay', 'disabled', or 'implicit-okay' (no status prop)."""
        s = self.get_string("status")
        if s is None:
            return STATUS_IMPLICIT_OKAY
        return s

    @property
    def is_active(self) -> bool:
        """True unless the node has status='disabled'."""
        return self.status != STATUS_DISABLED

    @property
    def is_ancestor_active(self) -> bool:
        """True if self and every ancestor have non-disabled status."""
        n: Node | None = self
        while n is not None:
            if not n.is_active:
                return False
            n = n.parent
        return True

    @property
    def phandle(self) -> int | None:
        ph = self._dt._fdt.get_phandle(self._offset)
        return ph if ph != 0 else None

    @property
    def compatible(self) -> list[str]:
        return self.get_string_list("compatible")

    # --- endpoint/graph helpers ---

    def remote_endpoint(self) -> "Node | None":
        """If this node has a remote-endpoint phandle, return the target node."""
        ph = self.get_u32("remote-endpoint")
        if ph is None:
            return None
        return self._dt.node_by_phandle(ph)
